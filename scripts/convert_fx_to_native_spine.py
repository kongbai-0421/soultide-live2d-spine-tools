r"""Batch convert pure-particle / UV-scroll Spine `fx_*` submodels to Native Spine 3.8 Bone Particles.

Reads Unity-exported particle tracks from `E:\A灵魂潮汐\tools\_batch_fx_particles\<skin_key>.json`
(produced by `SoulTideSpineParticleExporter.ExportBatch`) and rebuilds every eligible 100%-pure
`fx_*` submodel folder under `E:\A灵魂潮汐\Live2D与Spine模型\spine\` into:
  - A compact power-of-two PMA sprite atlas encoded as bit-exact lossless `.webp` (`exact=True`,
    verified with `np.array_equal`),
  - A native Spine 3.8 JSON skeleton with 4-vertex `ClippingAttachment` matching the exact
    existing FX canvas bounds (`skeleton.width/height`) and preserving `options.id`, `scale_factor`,
    and all `motions` animation names (supporting looping `idle`, UV-scrolling quads, and one-shot
    touch `fx_9008xxx` animations).

Safety guarantees:
  - Only converts `fx_*` folders whose clips have ZERO shader blockers (trails/dissolve/distort/mask/custom-mesh/rot3d).
  - Never replaces a folder unless all textures resolve, all non-empty clips produce valid animations,
    and total folder size shrinks strictly.
  - Saves a detailed report to `E:\A灵魂潮汐\Live2D与Spine模型\工具脚本\fx_native_particle_report.json`.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from batch_fx_exporter import FullI18nRepo, build_skin_catalog

MANIFEST_PATH = TOOLS_DIR / "SoulTideBatchFxUnity" / "fx_manifest.json"
TEX_DIR = TOOLS_DIR / "SoulTideBatchFxUnity" / "Assets" / "Textures"
EXPORT_DIR = TOOLS_DIR / "_batch_fx_particles"
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
REPORT_PATH = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本\fx_native_particle_report.json")


def to_pma(im: Image.Image) -> Image.Image:
    arr = np.array(im.convert("RGBA"), dtype=np.float32)
    a = arr[:, :, 3:4] / 255.0
    arr[:, :, :3] = np.clip(np.round(arr[:, :, :3] * a), 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def trim_sprite(im: Image.Image, alpha_thr: int = 1) -> tuple[Image.Image, int, int, int, int]:
    ow, oh = im.size
    arr = np.array(im.convert("RGBA"))
    mask = arr[:, :, 3] >= alpha_thr
    if not mask.any():
        return im.crop((0, 0, 2, 2)), ow, oh, 0, max(0, oh - 2)
    ys, xs = np.where(mask)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    return im.crop((x0, y0, x1, y1)), ow, oh, x0, oh - y1


def pack_shelf(items: list[dict[str, Any]], pad: int = 2) -> tuple[Image.Image, list[dict[str, Any]]]:
    ordered = sorted(items, key=lambda it: (-it["im"].height, -it["im"].width))
    candidates = [
        (256, 256), (512, 256), (512, 512),
        (1024, 512), (1024, 1024),
        (2048, 1024), (2048, 2048),
        (4096, 2048), (4096, 4096),
    ]
    for cand_w, cand_h in candidates:
        x = y = row_h = 0
        placements = []
        ok = True
        for it in ordered:
            w, h = it["im"].size
            p = it.get("pad", pad)
            if w > cand_w or h > cand_h:
                ok = False
                break
            if x > 0 and x + w + p > cand_w:
                x = 0
                y += row_h + p
                row_h = 0
            if y + h > cand_h:
                ok = False
                break
            placements.append((it, x, y))
            x += w + p
            if h > row_h:
                row_h = h
        if ok:
            atlas = Image.new("RGBA", (cand_w, cand_h), (0, 0, 0, 0))
            placed_meta = []
            for it, px, py in placements:
                atlas.paste(it["im"], (px, py))
                w, h = it["im"].size
                placed_meta.append({
                    "name": it["name"],
                    "x": px, "y": py, "w": w, "h": h,
                    "orig_w": it["orig_w"], "orig_h": it["orig_h"],
                    "off_x": it["off_x"], "off_y": it["off_y"],
                })
            return atlas, placed_meta
    raise RuntimeError("Failed to pack FX sprites even into 4096x4096 atlas")


def write_atlas_txt(path: Path, page_filename: str, w: int, h: int, regions: list[dict[str, Any]]) -> None:
    lines = [
        "",
        page_filename,
        f"size: {w},{h}",
        "format: RGBA8888",
        "filter: Linear,Linear",
        "repeat: none",
    ]
    for r in regions:
        lines.extend([
            r["name"],
            "  rotate: false",
            f"  xy: {r['x']}, {r['y']}",
            f"  size: {r['w']}, {r['h']}",
            f"  orig: {r['orig_w']}, {r['orig_h']}",
            f"  offset: {r['off_x']}, {r['off_y']}",
            "  index: -1",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_exact_webp(im: Image.Image, out_path: Path) -> None:
    rgba = im.convert("RGBA")
    rgba.save(out_path, "WEBP", lossless=True, exact=True, quality=100, method=4)
    src_arr = np.asarray(rgba)
    with Image.open(out_path) as dec:
        dec_arr = np.asarray(dec.convert("RGBA"))
    if src_arr.shape != dec_arr.shape or not np.array_equal(src_arr, dec_arr):
        out_path.unlink(missing_ok=True)
        raise AssertionError(f"Bit-exact WebP check failed: {out_path}")


def unwrap_angles(angles: list[float]) -> list[float]:
    if not angles:
        return []
    out = [angles[0]]
    for a in angles[1:]:
        prev = out[-1]
        d = (a - prev + 180.0) % 360.0 - 180.0
        out.append(prev + d)
    return out


def interp_pt(p0: list[float], p1: list[float], alpha: float) -> list[float]:
    res = [p0[i] + (p1[i] - p0[i]) * alpha for i in range(10)]
    d = (p1[5] - p0[5] + 180.0) % 360.0 - 180.0
    res[5] = p0[5] + d * alpha
    res.append(p0[10])
    return res


def decimate_1d(times: list[float], vals: list[float], tol: float, max_step: float | None = None) -> list[int]:
    n = len(times)
    if n <= 2:
        return list(range(n))
    keep = {0, n - 1}
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        t0, t1 = times[i0], times[i1]
        v0, v1 = vals[i0], vals[i1]
        dt = max(1e-6, t1 - t0)
        best_idx = -1
        best_err = tol
        if max_step is not None and abs(v1 - v0) > max_step:
            best_idx = (i0 + i1) // 2
            best_err = max_step + 1.0
        for i in range(i0 + 1, i1):
            u = (times[i] - t0) / dt
            err = abs(vals[i] - (v0 + (v1 - v0) * u))
            if err > best_err:
                best_err = err
                best_idx = i
        if best_idx != -1:
            keep.add(best_idx)
            stack.append((i0, best_idx))
            stack.append((best_idx, i1))
    return sorted(keep)


def decimate_2d(times: list[float], xs: list[float], ys: list[float], tol: float) -> list[int]:
    n = len(times)
    if n <= 2:
        return list(range(n))
    keep = {0, n - 1}
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        t0, t1 = times[i0], times[i1]
        dt = max(1e-6, t1 - t0)
        best_idx = -1
        best_err = tol
        for i in range(i0 + 1, i1):
            u = (times[i] - t0) / dt
            err = math.hypot(
                xs[i] - (xs[i0] + (xs[i1] - xs[i0]) * u),
                ys[i] - (ys[i0] + (ys[i1] - ys[i0]) * u),
            )
            if err > best_err:
                best_err = err
                best_idx = i
        if best_idx != -1:
            keep.add(best_idx)
            stack.append((i0, best_idx))
            stack.append((best_idx, i1))
    return sorted(keep)


def decimate_rgba(times: list[float], cols: list[tuple[float, float, float, float]], tol: float) -> list[int]:
    n = len(times)
    if n <= 2:
        return list(range(n))
    keep = {0, n - 1}
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        t0, t1 = times[i0], times[i1]
        dt = max(1e-6, t1 - t0)
        best_idx = -1
        best_err = tol
        c0, c1 = cols[i0], cols[i1]
        for i in range(i0 + 1, i1):
            u = (times[i] - t0) / dt
            err = max(abs(cols[i][k] - (c0[k] + (c1[k] - c0[k]) * u)) for k in range(4))
            if err > best_err:
                best_err = err
                best_idx = i
        if best_idx != -1:
            keep.add(best_idx)
            stack.append((i0, best_idx))
            stack.append((best_idx, i1))
    return sorted(keep)


def rgba_hex(r: float, g: float, b: float, a: float) -> str:
    return (
        f"{max(0, min(255, int(round(r * 255)))):02x}"
        f"{max(0, min(255, int(round(g * 255)))):02x}"
        f"{max(0, min(255, int(round(b * 255)))):02x}"
        f"{max(0, min(255, int(round(a * 255)))):02x}"
    )


def _pack_items_to_bones(
    items: list[dict[str, Any]],
    max_bones: int = 90,
    gap: float = 0.015,
) -> list[list[dict[str, Any]]]:
    bones: list[list[dict[str, Any]]] = []
    bone_ivs: list[list[tuple[float, float]]] = []
    for it in items:
        placed = False
        for bi, b_ivs in enumerate(bone_ivs):
            conflict = False
            for a0, a1 in it["intervals"]:
                for b0, b1 in b_ivs:
                    if not (a1 + gap <= b0 or b1 + gap <= a0):
                        conflict = True
                        break
                if conflict:
                    break
            if not conflict:
                bones[bi].append(it)
                b_ivs.extend(it["intervals"])
                placed = True
                break
        if not placed:
            if len(bones) >= max_bones:
                continue
            bones.append([it])
            bone_ivs.append(list(it["intervals"]))
    return bones


def _inside_rect(x: float, y: float, rect: tuple[float, float, float, float] | None, margin: float = 10.0) -> bool:
    if rect is None:
        return True
    rx, ry, rw, rh = rect
    return (rx - margin) <= x <= (rx + rw + margin) and (ry - margin) <= y <= (ry + rh + margin)


def _apply_smooth_fade(
    spts: list[list[Any]],
    fade_in: bool,
    fade_out: bool,
    has_orig_fade_in: bool = False,
    has_orig_fade_out: bool = False,
    viewport_rect: tuple[float, float, float, float] | None = None,
) -> None:
    """Preserve Unity's original Color/SizeOverLifetime fade; apply tiny micro-fade ONLY for abrupt in-viewport pops."""
    if len(spts) < 2:
        return
    t0, t1 = spts[0][0], spts[-1][0]
    dur = t1 - t0
    if dur <= 1e-4:
        return
    if fade_in and not has_orig_fade_in:
        a0 = spts[0][9]
        if a0 > 0.12 and dur >= 0.20 and _inside_rect(spts[0][1], spts[0][2], viewport_rect):
            ft = min(0.08, dur * 0.08)
            for p in spts:
                dt = p[0] - t0
                if dt >= ft:
                    break
                u = max(0.0, min(1.0, dt / max(1e-5, ft)))
                p[9] *= u * u * (3.0 - 2.0 * u)
            spts[0][9] = 0.0
    if fade_out and not has_orig_fade_out:
        t1 = spts[-1][0]
        a1 = spts[-1][9]
        if a1 > 0.12 and dur >= 0.20 and _inside_rect(spts[-1][1], spts[-1][2], viewport_rect):
            ft = min(0.08, dur * 0.08)
            for p in reversed(spts):
                dt = t1 - p[0]
                if dt >= ft:
                    break
                u = max(0.0, min(1.0, dt / max(1e-5, ft)))
                p[9] *= u * u * (3.0 - 2.0 * u)
            spts[-1][9] = 0.0


def _sample_track_at(pts: list[list[Any]], t_query: float) -> list[Any]:
    if t_query <= pts[0][0]:
        out = list(pts[0]); out[0] = t_query; return out
    if t_query >= pts[-1][0]:
        out = list(pts[-1]); out[0] = t_query; return out
    lo, hi = 0, len(pts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if pts[mid][0] <= t_query:
            lo = mid
        else:
            hi = mid
    p0, p1 = pts[lo], pts[hi]
    alpha = (t_query - p0[0]) / max(1e-6, p1[0] - p0[0])
    out = interp_pt(p0, p1, alpha)
    out[0] = t_query
    return out


def _slice_track_torus_laps(spts: list[list[Any]], period: float) -> list[tuple[float, float, list[list[Any]], bool, bool, bool]]:
    """Multi-Bone Torus Phase-Relay: slice arbitrary-duration track across every k*period boundary at 1.00x true speed!"""
    if len(spts) < 2 or period <= 1e-4:
        return []
    t_start = spts[0][0]
    t_end = spts[-1][0]
    if t_end <= period + 1e-5:
        return [(max(0.0, t_start), min(period, t_end), spts, False, False, False)]

    k_max = int(math.floor((t_end - 1e-5) / period))
    segs: list[tuple[float, float, list[list[Any]], bool, bool, bool]] = []
    for k in range(k_max + 1):
        win_a = k * period
        win_b = (k + 1) * period
        lo = max(t_start, win_a)
        hi = min(t_end, win_b)
        if hi - lo <= 1e-4:
            continue
        w_from = (k > 0 and lo <= win_a + 1e-4)
        w_to = (k < k_max and hi >= win_b - 1e-4)
        lap_pts: list[list[Any]] = []
        p_lo = _sample_track_at(spts, lo)
        p_lo[0] = 0.0 if w_from else max(0.0, lo - win_a)
        lap_pts.append(p_lo)
        for p in spts:
            if lo + 1e-4 < p[0] < hi - 1e-4:
                pc = list(p)
                pc[0] = max(0.0, min(period, p[0] - win_a))
                lap_pts.append(pc)
        p_hi = _sample_track_at(spts, hi)
        p_hi[0] = period if w_to else max(0.0, min(period, hi - win_a))
        lap_pts.append(p_hi)
        if len(lap_pts) >= 2:
            segs.append((lap_pts[0][0], lap_pts[-1][0], lap_pts, w_from, w_to, False))
    return segs


def _build_persistent_loop_spts(
    pts: list[list[Any]],
    t_win_start: float,
    period: float,
    coord_fn,
    size_fn,
    rot_offset_deg: float,
    ring_buffer_mode: int,
    rb_nat_period: float = 0.0,
) -> list[list[Any]]:
    """Build seamless cyclic trajectory for persistent/ringBufferMode tracks without 0.35s reverse-snap."""
    # If ringBufferMode == 2 has a valid natural period P_rb, slice ONE exact natural cycle and tile it cleanly!
    if ring_buffer_mode == 2 and 0.25 <= rb_nat_period <= period * 1.35:
        t_avail = pts[-1][0] - t_win_start
        if t_avail >= rb_nat_period - 0.05:
            reps = max(1, int(round(period / rb_nat_period)))
            cyc_t = period / reps
            # Sample one natural cycle [t_win_start, t_win_start + rb_nat_period]
            raw_cyc = [_sample_track_at(pts, t_win_start)]
            for p in pts:
                if t_win_start + 1e-4 < p[0] < t_win_start + rb_nat_period - 1e-4:
                    raw_cyc.append(list(p))
            raw_cyc.append(_sample_track_at(pts, t_win_start + rb_nat_period))
            cyc_spts = []
            for p in raw_cyc:
                u = max(0.0, min(1.0, (p[0] - t_win_start) / max(1e-5, rb_nat_period)))
                sx, sy = coord_fn(p[1], p[2])
                sw, sh = size_fn(p[3], p[4])
                cyc_spts.append([u * cyc_t, sx, sy, sw, sh, p[5] + rot_offset_deg, p[6], p[7], p[8], p[9], int(p[10])])
            # Subtle full-cycle closure correction (spread across full cycle -> C1 velocity, zero snap!)
            if len(cyc_spts) >= 2:
                p0, p1 = cyc_spts[0], cyc_spts[-1]
                for p in cyc_spts:
                    u = p[0] / max(1e-5, cyc_t)
                    for k in (1, 2, 3, 4, 6, 7, 8, 9):
                        p[k] = p[k] + (p0[k] - p1[k]) * u
                    d_ang = (p0[5] - p1[5] + 180.0) % 360.0 - 180.0
                    p[5] = p[5] + d_ang * u
            out: list[list[Any]] = []
            for rep in range(reps):
                bt = rep * cyc_t
                for ci, p in enumerate(cyc_spts):
                    if rep > 0 and ci == 0:
                        continue
                    pc = list(p)
                    pc[0] = min(period, bt + p[0])
                    out.append(pc)
            return out

    # Standard persistent / ringBufferMode=1 / eternal: full-period slice + smooth full-period drift closure
    sliced = [_sample_track_at(pts, t_win_start)]
    for p in pts:
        if t_win_start + 1e-4 < p[0] < t_win_start + period - 1e-4:
            sliced.append(list(p))
    sliced.append(_sample_track_at(pts, t_win_start + period))
    spts = []
    for p in sliced:
        t_rel = max(0.0, min(period, p[0] - t_win_start))
        sx, sy = coord_fn(p[1], p[2])
        sw, sh = size_fn(p[3], p[4])
        spts.append([t_rel, sx, sy, sw, sh, p[5] + rot_offset_deg, p[6], p[7], p[8], p[9], int(p[10])])
    if len(spts) >= 2:
        p0, p1 = spts[0], spts[-1]
        for p in spts:
            u = p[0] / max(1e-5, period)
            for k in (1, 2, 3, 4, 6, 7, 8, 9):
                p[k] = p[k] + (p0[k] - p1[k]) * u
            d_ang = (p0[5] - p1[5] + 180.0) % 360.0 - 180.0
            p[5] = p[5] + d_ang * u
    return spts


def build_periodic_pool(
    tracks: list[dict[str, Any]],
    t_win_start: float,
    period: float,
    coord_fn,
    size_fn,
    rot_offset_deg: float,
    region_fn,
    max_bones: int = 80,
    ring_buffer_mode: int = 0,
    max_particles: int = 50,
    node_meta: dict[str, Any] | None = None,
    viewport_rect: tuple[float, float, float, float] | None = None,
    subsample_ratio: float = 1.0,
) -> list[list[dict[str, Any]]]:
    has_fi = bool((node_meta or {}).get("has_orig_fade_in", False))
    has_fo = bool((node_meta or {}).get("has_orig_fade_out", False))
    rb_range = (node_meta or {}).get("ring_buffer_loop_range") or [0.0, 1.0]
    sim_spd = max(1e-3, float((node_meta or {}).get("sim_speed", 1.0) or 1.0))

    # 1. Handle persistent / ringBufferMode tracks that stay alive across the window
    persistent_candidates = [
        tr for tr in tracks
        if len(tr["pts"]) >= 2
        and (ring_buffer_mode != 0 or (not tr["born_in_window"] and not tr["dead_in_window"]))
        and tr["pts"][0][0] <= t_win_start + 0.1
        and tr["pts"][-1][0] >= t_win_start + min(period, 1.0) - 0.1
    ]
    if ring_buffer_mode != 0 and persistent_candidates:
        items: list[dict[str, Any]] = []
        for tr in persistent_candidates[:max_bones]:
            pts = tr["pts"]
            lf = float(tr.get("life", 0.0))
            rb_nat = 0.0
            if ring_buffer_mode == 2 and 0.1 < lf < 99.0:
                rb_nat = (lf / sim_spd) * max(0.05, float(rb_range[1]) - float(rb_range[0]))
            spts = _build_persistent_loop_spts(
                pts, t_win_start, period, coord_fn, size_fn, rot_offset_deg,
                ring_buffer_mode=ring_buffer_mode, rb_nat_period=rb_nat,
            )
            if len(spts) < 2:
                continue
            reg = region_fn(tr["node"], int(spts[0][10]))
            segs = [(0.0, period, spts, False, False, True)]
            items.append({
                "node": tr["node"],
                "region": reg,
                "region_fn": region_fn,
                "segs": segs,
                "intervals": [(0.0, period)],
            })
        return [[it] for it in items[:max_bones]]

    selected = [
        tr for tr in tracks
        if tr["born_in_window"] and tr["dead_in_window"]
        and t_win_start <= tr["pts"][0][0] < t_win_start + period
    ]
    # Fallback for long-lived particles that stayed alive through the entire window
    if not selected and persistent_candidates:
        return build_periodic_pool(
            persistent_candidates, t_win_start, period,
            coord_fn, size_fn, rot_offset_deg, region_fn,
            max_bones=max_bones, ring_buffer_mode=1, max_particles=max_particles,
            node_meta=node_meta, viewport_rect=viewport_rect,
        )
    if not selected:
        selected = [
            tr for tr in tracks
            if len(tr["pts"]) >= 2 and t_win_start <= tr["pts"][0][0] < t_win_start + period
        ]
    if not selected:
        selected = [tr for tr in tracks if len(tr["pts"]) >= 2][:max_bones]

    selected.sort(key=lambda tr: tr["pts"][0][0])
    # Time-stratified subsampling (evenly spaced across [0, period], NEVER dropping the tail of the loop!)
    if 0.0 < subsample_ratio < 0.999 and len(selected) > 4:
        keep_n = max(2, int(round(len(selected) * subsample_ratio)))
        if keep_n < len(selected):
            idxs = [int(round(i * (len(selected) - 1) / max(1, keep_n - 1))) for i in range(keep_n)]
            selected = [selected[i] for i in sorted(set(idxs))]

    items = []
    for tr in selected:
        pts = tr["pts"]
        if len(pts) < 2:
            continue
        t_base = t_win_start if pts[0][0] >= t_win_start else pts[0][0]
        spts = []
        for p in pts:
            t_rel = max(0.0, p[0] - t_base)
            sx, sy = coord_fn(p[1], p[2])
            sw, sh = size_fn(p[3], p[4])
            spts.append([t_rel, sx, sy, sw, sh, p[5] + rot_offset_deg, p[6], p[7], p[8], p[9], int(p[10])])

        _apply_smooth_fade(
            spts,
            fade_in=bool(tr["born_in_window"] or not tr["dead_in_window"]),
            fade_out=bool(tr["dead_in_window"] or not tr["born_in_window"]),
            has_orig_fade_in=has_fi,
            has_orig_fade_out=has_fo,
            viewport_rect=viewport_rect,
        )

        reg = region_fn(tr["node"], int(spts[0][10]))
        # Multi-Bone Torus Phase-Relay: preserve 1.00x true speed by emitting each wrapped lap as an independent interval!
        lap_segs = _slice_track_torus_laps(spts, period)
        if len(lap_segs) <= 1:
            if lap_segs:
                items.append({
                    "node": tr["node"],
                    "region": reg,
                    "region_fn": region_fn,
                    "segs": lap_segs,
                    "intervals": [(lap_segs[0][0], lap_segs[0][1])],
                })
        else:
            # Check if all laps are mutually disjoint (e.g. dur < period wrapping once over period -> 2 disjoint laps!)
            if len(lap_segs) == 2 and lap_segs[1][1] + 0.02 <= lap_segs[0][0]:
                # Classic single wrap fits cleanly on ONE bone with zero self-overlap
                ordered_pair = [lap_segs[1], lap_segs[0]]
                items.append({
                    "node": tr["node"],
                    "region": reg,
                    "region_fn": region_fn,
                    "segs": ordered_pair,
                    "intervals": [(s[0], s[1]) for s in ordered_pair],
                })
            else:
                # Multi-lap track (dur >= period): relay each lap across separate bones seamlessly at t = 0 / period!
                for seg in lap_segs:
                    items.append({
                        "node": tr["node"],
                        "region": reg,
                        "region_fn": region_fn,
                        "segs": [seg],
                        "intervals": [(seg[0], seg[1])],
                    })

    # Always keep gap >= 0.015s so dedupe NEVER overwrites a preceding segment's stepped end keyframe!
    return _pack_items_to_bones(items, max_bones=max_bones, gap=0.015)


def water_fill_budgets(demands: list[int], total_budget: int = 480) -> list[int]:
    """Fair water-filling bone allocation: small nodes get 100% of demand; only extreme outliers cap smoothly."""
    if not demands:
        return []
    if sum(demands) <= total_budget:
        return list(demands)
    n = len(demands)
    rem_budget = total_budget
    caps = [0] * n
    active = list(range(n))
    while active and rem_budget > 0:
        share = max(1, rem_budget // len(active))
        next_active = []
        satisfied_any = False
        for i in active:
            if demands[i] <= share:
                caps[i] = demands[i]
                rem_budget -= demands[i]
                satisfied_any = True
            else:
                next_active.append(i)
        if not satisfied_any:
            # Distribute remaining evenly among still-capped nodes
            base_s = rem_budget // len(next_active)
            extra = rem_budget % len(next_active)
            for idx_k, i in enumerate(next_active):
                caps[i] = max(1, base_s + (1 if idx_k < extra else 0))
            break
        active = next_active
    return caps


def build_oneshot_pool(
    tracks: list[dict[str, Any]],
    coord_fn,
    size_fn,
    rot_offset_deg: float,
    region_fn,
    max_bones: int = 80,
    node_meta: dict[str, Any] | None = None,
    viewport_rect: tuple[float, float, float, float] | None = None,
) -> tuple[list[list[dict[str, Any]]], float]:
    has_fi = bool((node_meta or {}).get("has_orig_fade_in", False))
    has_fo = bool((node_meta or {}).get("has_orig_fade_out", False))
    selected = sorted((tr for tr in tracks if len(tr["pts"]) >= 2), key=lambda tr: tr["pts"][0][0])
    items: list[dict[str, Any]] = []
    max_t = 0.2
    for tr in selected:
        pts = tr["pts"]
        spts = []
        for p in pts:
            t_rel = max(0.0, p[0])
            sx, sy = coord_fn(p[1], p[2])
            sw, sh = size_fn(p[3], p[4])
            spts.append([t_rel, sx, sy, sw, sh, p[5] + rot_offset_deg, p[6], p[7], p[8], p[9], int(p[10])])
        _apply_smooth_fade(
            spts, fade_in=(spts[0][0] > 0.02), fade_out=True,
            has_orig_fade_in=has_fi, has_orig_fade_out=has_fo, viewport_rect=viewport_rect,
        )
        max_t = max(max_t, spts[-1][0])
        reg = region_fn(tr["node"], int(spts[0][10]))
        segs = [(spts[0][0], spts[-1][0], spts, False, False, False)]
        items.append({
            "node": tr["node"],
            "region": reg,
            "region_fn": region_fn,
            "segs": segs,
            "intervals": [(spts[0][0], spts[-1][0])],
        })
    return _pack_items_to_bones(items, max_bones=max_bones, gap=0.015), round(max_t, 4)


def emit_bone_timelines(
    bone_items: list[dict[str, Any]],
    period: float,
    repeat_count: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    flat_segs = []
    for it in bone_items:
        rfn = it.get("region_fn")
        nidx = it.get("node", 0)
        for seg_tup in it["segs"]:
            t0, t1, pts, w_from, w_to = seg_tup[:5]
            is_pers = bool(seg_tup[5]) if len(seg_tup) > 5 else False
            flat_segs.append({
                "t0": t0, "t1": t1, "pts": pts,
                "node": nidx,
                "region": it["region"],
                "region_fn": rfn,
                "wraps_from_end": w_from, "wraps_to_start": w_to,
                "is_persistent": is_pers,
            })
    flat_segs.sort(key=lambda s: s["t0"])
    bone_has_t0_wrap = any(s["wraps_from_end"] and s["t0"] <= 1e-3 for s in flat_segs)
    bone_has_tend_wrap = any(s["wraps_to_start"] and s["t1"] >= period - 1e-3 for s in flat_segs)
    same_bone_continuous_wrap = bone_has_t0_wrap and bone_has_tend_wrap

    tr_keys, sc_keys, rt_keys, col_keys, att_keys = [], [], [], [], []
    for rep in range(repeat_count):
        base_t = rep * period
        for si, seg in enumerate(flat_segs):
            pts = seg["pts"]
            times = [p[0] for p in pts]
            xs = [p[1] for p in pts]
            ys = [p[2] for p in pts]
            sxs = [p[3] / 100.0 for p in pts]
            sys_ = [p[4] / 100.0 for p in pts]
            rots = unwrap_angles([p[5] for p in pts])
            cols = [(p[6], p[7], p[8], p[9]) for p in pts]

            i_pos = decimate_2d(times, xs, ys, tol=0.75)
            i_sc = decimate_2d(times, sxs, sys_, tol=0.008)
            i_rt = decimate_1d(times, rots, tol=0.5, max_step=90.0)
            i_col = decimate_rgba(times, cols, tol=0.015)

            is_end_wrap = seg["wraps_to_start"]
            # If this bone hands off to a DIFFERENT relay bone at internal boundary (rep < repeat_count - 1),
            # we must turn THIS bone off at base_t + period while the relay bone turns on at base_t + period!
            must_off_at_internal_boundary = (
                is_end_wrap and (not same_bone_continuous_wrap) and (rep < repeat_count - 1)
            )
            skip_dup_start = (rep > 0 and seg["wraps_from_end"] and same_bone_continuous_wrap)

            t_start_abs = round(base_t + times[0], 4)
            t_end_abs = round(base_t + times[-1], 4)

            if rep == 0 and si == 0 and times[0] > 0.001:
                att_keys.append({"time": 0.0, "name": None})
                col_keys.append({"time": 0.0, "color": "ffffff00", "curve": "stepped"})

            # Emit per-frame tile switches (supports TextureSheetAnimation flipbooks natively!)
            rfn = seg["region_fn"]
            nidx = seg["node"]
            last_reg = None
            for pi_idx, p in enumerate(pts):
                reg_now = rfn(nidx, int(p[10])) if rfn is not None else seg["region"]
                if pi_idx == 0:
                    if not skip_dup_start:
                        att_keys.append({"time": t_start_abs, "name": reg_now})
                    last_reg = reg_now
                elif reg_now != last_reg:
                    att_keys.append({"time": round(base_t + p[0], 4), "name": reg_now})
                    last_reg = reg_now

            step_at_end = (not is_end_wrap and not seg["is_persistent"]) or must_off_at_internal_boundary

            for idx_k, idx in enumerate(i_pos):
                if skip_dup_start and idx_k == 0:
                    continue
                kf: dict[str, Any] = {"time": round(base_t + times[idx], 4), "x": round(xs[idx], 2), "y": round(ys[idx], 2)}
                if idx_k == len(i_pos) - 1 and step_at_end:
                    kf["curve"] = "stepped"
                tr_keys.append(kf)

            for idx_k, idx in enumerate(i_sc):
                if skip_dup_start and idx_k == 0:
                    continue
                kf = {"time": round(base_t + times[idx], 4), "x": round(sxs[idx], 4), "y": round(sys_[idx], 4)}
                if idx_k == len(i_sc) - 1 and step_at_end:
                    kf["curve"] = "stepped"
                sc_keys.append(kf)

            for idx_k, idx in enumerate(i_rt):
                if skip_dup_start and idx_k == 0:
                    continue
                kf = {"time": round(base_t + times[idx], 4), "angle": round(rots[idx] % 360.0, 2)}
                if idx_k == len(i_rt) - 1 and step_at_end:
                    kf["curve"] = "stepped"
                rt_keys.append(kf)

            for idx_k, idx in enumerate(i_col):
                if skip_dup_start and idx_k == 0:
                    continue
                r, g, b, a = cols[idx]
                kf = {"time": round(base_t + times[idx], 4), "color": rgba_hex(r, g, b, a)}
                if idx_k == len(i_col) - 1 and step_at_end:
                    kf["curve"] = "stepped"
                col_keys.append(kf)

            if (not is_end_wrap and not seg["is_persistent"]) or must_off_at_internal_boundary:
                att_keys.append({"time": t_end_abs, "name": None})

    def dedupe(kfs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for k in kfs:
            if out and k["time"] <= out[-1]["time"] + 1e-5:
                out[-1] = k
            else:
                out.append(k)
        if out and "curve" in out[-1]:
            out[-1].pop("curve", None)
        return out

    return (
        {"translate": dedupe(tr_keys), "scale": dedupe(sc_keys), "rotate": dedupe(rt_keys)},
        {"attachment": dedupe(att_keys), "color": dedupe(col_keys)},
    )


def node_blockers(n: dict[str, Any]) -> list[str]:
    b = []
    if n.get("trailsEnabled"): b.append("trails")
    if n.get("dissolve", 0) and float(n.get("dissolve", 0)) > 0: b.append("dissolve")
    if n.get("distortStrength", 0) and abs(float(n.get("distortStrength", 0))) > 1e-4: b.append("distort")
    if n.get("maskTexName") or n.get("mask2TexName"): b.append("mask")
    if n.get("renderMode") == 4 and (n.get("meshName") or "").upper() not in ("", "BUILTIN_QUAD"): b.append("mesh")
    if n.get("rotation3D"): b.append("rot3d")
    if n.get("customDataEnabled"): b.append("custom_data")
    return b


def compute_gpu_blocked_node_indices(nodes: list[dict[str, Any]]) -> set[int]:
    """Return set of node indices that must stay on GPU (propagated across connected subEmitter trees)."""
    n_cnt = len(nodes)
    adj: dict[int, set[int]] = {i: set() for i in range(n_cnt)}
    for i, n in enumerate(nodes):
        for se in (n.get("subEmitters") or []):
            t = int(se.get("targetIdx", -1))
            if 0 <= t < n_cnt:
                adj[i].add(t)
                adj[t].add(i)
    blocked: set[int] = set()
    visited: set[int] = set()
    for i in range(n_cnt):
        if i in visited:
            continue
        comp: list[int] = []
        stack = [i]
        while stack:
            u = stack.pop()
            if u in visited:
                continue
            visited.add(u)
            comp.append(u)
            stack.extend(adj[u] - visited)
        if any(node_blockers(nodes[u]) for u in comp):
            blocked.update(comp)
    return blocked


def build_tex_index() -> dict[str, Path]:
    idx: dict[str, Path] = {}
    for p in TEX_DIR.glob("*.png"):
        idx[p.stem.lower()] = p
        idx[p.name.lower()] = p
    return idx


def sanitize_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


def _read_bg_static_bounds(submodels_dir: Path) -> tuple[float, float, float, float] | None:
    bg_dir = submodels_dir / "bg_static"
    if not bg_dir.is_dir():
        return None
    bg_js = None
    cfg_p = bg_dir / ".config.json"
    if cfg_p.is_file():
        try:
            sk_name = json.loads(cfg_p.read_text(encoding="utf-8-sig")).get("skeleton", "")
            if sk_name and (bg_dir / sk_name).is_file():
                bg_js = bg_dir / sk_name
        except Exception:
            pass
    if bg_js is None:
        for cand in ("bg_static.skel.json", "bg_static.json"):
            if (bg_dir / cand).is_file():
                bg_js = bg_dir / cand
                break
    if bg_js is None:
        return None
    try:
        d = json.loads(bg_js.read_text(encoding="utf-8-sig"))
        sk = d.get("skeleton") or {}
        w = float(sk.get("width") or 0.0)
        h = float(sk.get("height") or 0.0)
        if w > 10.0 and h > 10.0:
            return float(sk.get("x", -w / 2.0)), float(sk.get("y", -h / 2.0)), w, h
    except Exception:
        return None
    return None


def _make_coord_mappers(
    export_data: dict[str, Any],
    bg_x: float,
    bg_y: float,
    bg_w: float,
    bg_h: float,
):
    """Return (fx_root_x, fx_root_y, coord_fn, size_fn, rot_offset_deg)."""
    ux = float(export_data.get("ui_per_spine_x") or 0.0)
    uy = float(export_data.get("ui_per_spine_y") or 0.0)
    if ux > 1e-6 and uy > 1e-6:
        p_wx = float(export_data.get("person_wx") or 0.0)
        p_wy = float(export_data.get("person_wy") or 0.0)
        # All bg_static submodels (including Lavira_S2 after MAIN -10° rotation) are upright (0°) in Spine space!
        rot_off = 0.0

        def coord_fn(wx: float, wy: float) -> tuple[float, float]:
            return (wx - p_wx) / ux, (wy - p_wy) / uy

        def size_fn(pw: float, ph: float) -> tuple[float, float]:
            sw = math.copysign(max(1.0, abs(pw) / ux), -1.0 if pw < 0.0 else 1.0)
            sh = math.copysign(max(1.0, abs(ph) / uy), -1.0 if ph < 0.0 else 1.0)
            return sw, sh

        return 0.0, 0.0, coord_fn, size_fn, rot_off

    # Legacy fallback when person_wx/ui_per_spine_x are absent
    cam_x = float(export_data["cam_x"])
    cam_y = float(export_data["cam_y"])
    scale_u2s = bg_w / max(1.0, float(export_data["canvas_w"]))
    bg_cx = round(bg_x + bg_w / 2.0, 2)
    bg_cy = round(bg_y + bg_h / 2.0, 2)

    def coord_fn_legacy(wx: float, wy: float) -> tuple[float, float]:
        return (wx - cam_x) * scale_u2s, (wy - cam_y) * scale_u2s

    def size_fn_legacy(pw: float, ph: float) -> tuple[float, float]:
        sw = math.copysign(max(1.0, abs(pw) * scale_u2s), -1.0 if pw < 0.0 else 1.0)
        sh = math.copysign(max(1.0, abs(ph) * scale_u2s), -1.0 if ph < 0.0 else 1.0)
        return sw, sh

    return bg_cx, bg_cy, coord_fn_legacy, size_fn_legacy, 0.0


def _emit_tween_nodes_into_skeleton(
    tween_nodes: list[dict[str, Any]],
    tex_index: dict[str, Path],
    tex_key_to_regs: dict[tuple[str, int, int, bool], list[str]],
    coord_fn,
    size_fn,
    rot_offset_deg: float,
    bones: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    skin_att: dict[str, Any],
    bone_anims: dict[str, Any],
    slot_anims: dict[str, Any],
    target_dur: float,
    name_prefix: str = "tw",
) -> float:
    """Emit static/TweenRotation/TweenPosition/TweenScale nodes into idle animation; returns required duration."""
    req_dur = target_dur
    for gi, grp in enumerate(tween_nodes):
        sprites = grp.get("sprites") or []
        if not sprites:
            continue
        tweens = grp.get("tweens") or []
        p_wx = float(grp.get("parent_wx", 0.0))
        p_wy = float(grp.get("parent_wy", 0.0))
        p_wsx = float(grp.get("parent_wsx", 1.0))
        p_wsy = float(grp.get("parent_wsy", 1.0))
        init_wx, init_wy = float(grp["world_pos"][0]), float(grp["world_pos"][1])
        init_scx, init_scy = float(grp.get("local_scale", [1.0, 1.0])[0]), float(grp.get("local_scale", [1.0, 1.0])[1])
        init_zdeg = float(grp.get("z_deg", 0.0))

        # Check if group has a parent UI Mask (e.g. Akaset_S5 window 640x298)
        mask_info = grp.get("mask")
        mask_slot_name = None
        if mask_info and mask_info.get("w", 0) > 2 and mask_info.get("h", 0) > 2:
            mcx, mcy = coord_fn(float(mask_info["cx"]), float(mask_info["cy"]))
            mw, mh = size_fn(float(mask_info["w"]), float(mask_info["h"]))
            mw, mh = abs(mw), abs(mh)
            mask_slot_name = f"{name_prefix}_mask_{gi}"
            slots.append({"name": mask_slot_name, "bone": "fx_root", "attachment": mask_slot_name})
            skin_att[mask_slot_name] = {
                mask_slot_name: {
                    "type": "clipping",
                    "end": "",
                    "vertexCount": 4,
                    "vertices": [
                        round(mcx - mw / 2.0, 2), round(mcy - mh / 2.0, 2),
                        round(mcx + mw / 2.0, 2), round(mcy - mh / 2.0, 2),
                        round(mcx + mw / 2.0, 2), round(mcy + mh / 2.0, 2),
                        round(mcx - mw / 2.0, 2), round(mcy + mh / 2.0, 2),
                    ],
                }
            }

        # Determine base rest position/scale/rotation from Tween `from` when present
        pos_tw = next((tw for tw in tweens if tw.get("type") == "TweenPosition"), None)
        rot_tw = next((tw for tw in tweens if tw.get("type") == "TweenRotation"), None)
        scl_tw = next((tw for tw in tweens if tw.get("type") == "TweenScale"), None)

        if pos_tw:
            fr_wx = p_wx + float(pos_tw["from"][0]) * p_wsx
            fr_wy = p_wy + float(pos_tw["from"][1]) * p_wsy
            to_wx = p_wx + float(pos_tw["to"][0]) * p_wsx
            to_wy = p_wy + float(pos_tw["to"][1]) * p_wsy
        else:
            fr_wx, fr_wy = init_wx, init_wy
            to_wx, to_wy = init_wx, init_wy

        bx0, by0 = coord_fn(fr_wx, fr_wy)
        bx1, by1 = coord_fn(to_wx, to_wy)
        base_rot = (float(rot_tw["from"][2]) if rot_tw else init_zdeg) + rot_offset_deg
        base_sx = float(scl_tw["from"][0]) if scl_tw else init_scx
        base_sy = float(scl_tw["from"][1]) if scl_tw else init_scy

        g_bone = f"{name_prefix}_g{gi}"
        b_def: dict[str, Any] = {
            "name": g_bone,
            "parent": "fx_root",
            "x": round(bx0, 2),
            "y": round(by0, 2),
        }
        if abs(base_rot) > 0.01:
            b_def["rotation"] = round(base_rot % 360.0, 2)
        if abs(base_sx - 1.0) > 1e-4 or abs(base_sy - 1.0) > 1e-4:
            b_def["scaleX"] = round(base_sx, 5)
            b_def["scaleY"] = round(base_sy, 5)
        bones.append(b_def)

        # Build bone timelines for this Tween group
        g_anim: dict[str, Any] = {}
        if pos_tw:
            tw_dur = max(0.5, float(pos_tw.get("duration", 60.0)))
            style = int(pos_tw.get("style", 1))
            dx, dy = round(bx1 - bx0, 2), round(by1 - by0, 2)
            if style == 2:  # PingPong
                cy_dur = tw_dur * 2.0
                req_dur = max(req_dur, cy_dur)
                k = max(1, int(round(req_dur / cy_dur)))
                seg_t = req_dur / k
                tks = []
                for ci in range(k):
                    t_a = round(ci * seg_t, 4)
                    t_m = round((ci + 0.5) * seg_t, 4)
                    tks.append({"time": t_a, "x": 0.0, "y": 0.0})
                    tks.append({"time": t_m, "x": dx, "y": dy})
                tks.append({"time": round(req_dur, 4), "x": 0.0, "y": 0.0})
                g_anim["translate"] = tks
            else:  # Loop
                req_dur = max(req_dur, tw_dur)
                k = max(1, int(round(req_dur / tw_dur)))
                seg_t = req_dur / k
                tks = []
                for ci in range(k):
                    t_a = round(ci * seg_t, 4)
                    t_b = round((ci + 1) * seg_t - (0.0005 if ci < k - 1 else 0.0), 4)
                    tks.append({"time": t_a, "x": 0.0, "y": 0.0})
                    kf_e: dict[str, Any] = {"time": t_b, "x": dx, "y": dy}
                    if ci < k - 1:
                        kf_e["curve"] = "stepped"
                    tks.append(kf_e)
                g_anim["translate"] = tks

        if rot_tw:
            tw_dur = max(0.5, float(rot_tw.get("duration", 90.0)))
            delta_z = float(rot_tw["to"][2]) - float(rot_tw["from"][2])
            style = int(rot_tw.get("style", 1))
            if style == 2:  # PingPong
                cy_dur = tw_dur * 2.0
                req_dur = max(req_dur, cy_dur)
                g_anim["rotate"] = [
                    {"time": 0.0, "angle": 0.0},
                    {"time": round(tw_dur, 4), "angle": round(delta_z, 2)},
                    {"time": round(cy_dur, 4), "angle": 0.0},
                ]
            else:
                req_dur = max(req_dur, tw_dur)
                steps = max(3, int(math.ceil(abs(delta_z) / 120.0)))
                rks = []
                for si_r in range(steps + 1):
                    ang = (delta_z * si_r / steps) % 360.0
                    rks.append({"time": round(tw_dur * si_r / steps, 4), "angle": round(ang, 2)})
                g_anim["rotate"] = rks

        if scl_tw:
            tw_dur = max(0.5, float(scl_tw.get("duration", 20.0)))
            style = int(scl_tw.get("style", 1))
            rx = float(scl_tw["to"][0]) / max(1e-5, base_sx)
            ry = float(scl_tw["to"][1]) / max(1e-5, base_sy)
            if style == 2:  # PingPong
                cy_dur = tw_dur * 2.0
                req_dur = max(req_dur, cy_dur)
                g_anim["scale"] = [
                    {"time": 0.0, "x": 1.0, "y": 1.0},
                    {"time": round(tw_dur, 4), "x": round(rx, 5), "y": round(ry, 5)},
                    {"time": round(cy_dur, 4), "x": 1.0, "y": 1.0},
                ]
            else:
                req_dur = max(req_dur, tw_dur)
                g_anim["scale"] = [
                    {"time": 0.0, "x": 1.0, "y": 1.0},
                    {"time": round(tw_dur, 4), "x": round(rx, 5), "y": round(ry, 5)},
                ]

        if g_anim:
            bone_anims[g_bone] = g_anim

        # Attach child sprites to g_bone
        last_sp_slot = None
        for si_s, sp in enumerate(sprites):
            tname = (sp.get("tex") or "").strip()
            tp = tex_index.get(tname.lower()) or tex_index.get(Path(tname).stem.lower())
            if tp is None:
                continue
            regs = tex_key_to_regs.get((tp.stem.lower(), 1, 1, True))
            if not regs:
                continue
            rname = regs[0]
            # Convert sprite local offset & size into Spine units
            ox0, oy0 = coord_fn(0.0, 0.0)
            ox1, oy1 = coord_fn(float(sp.get("rel_x", 0.0)) * p_wsx, float(sp.get("rel_y", 0.0)) * p_wsy)
            sw_s, sh_s = size_fn(float(sp["w"]), float(sp["h"]))
            sname = f"{name_prefix}_g{gi}_s{si_s}"
            col = sp.get("color") or {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}
            slots.append({
                "name": sname,
                "bone": g_bone,
                "color": rgba_hex(col.get("r", 1.0), col.get("g", 1.0), col.get("b", 1.0), col.get("a", 1.0)),
                "attachment": rname,
            })
            skin_att[sname] = {
                rname: {
                    "x": round(ox1 - ox0, 2),
                    "y": round(oy1 - oy0, 2),
                    "width": round(abs(sw_s), 2),
                    "height": round(abs(sh_s), 2),
                }
            }
            slot_anims[sname] = {"attachment": [{"time": 0.0, "name": rname}]}
            last_sp_slot = sname

        if mask_slot_name and last_sp_slot:
            skin_att[mask_slot_name][mask_slot_name]["end"] = last_sp_slot

    return req_dur


def emit_uv_quad_into_skeleton(
    uvq: dict[str, Any],
    bname_prefix: str,
    parent_bone: str,
    rname: str,
    coord_fn,
    size_fn,
    rot_offset_deg: float,
    dur_q: float,
    bones: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    skin_att: dict[str, Any],
    bone_anims: dict[str, Any],
    slot_anims: dict[str, Any],
) -> None:
    """Emit a UV-scrolling quad with exact rotated local U/V axis support and 2x2 diagonal tiling."""
    cx, cy = coord_fn(float(uvq["x"]), float(uvq["y"]))
    cx, cy = round(cx, 2), round(cy, 2)
    qw, qh = size_fn(float(uvq["w"]), float(uvq["h"]))
    qw, qh = round(max(2.0, abs(qw)), 2), round(max(2.0, abs(qh)), 2)
    qrot = round(float(uvq.get("rot", 0.0)) + rot_offset_deg, 2)
    qcol = rgba_hex(uvq["r"], uvq["g"], uvq["b"], uvq["a"])
    uv_u = float(uvq.get("uv_u", 0.0))
    uv_v = float(uvq.get("uv_v", 0.0))

    # Anchor bone holds world position + rotation so child tiles ALWAYS slide along exact local U/V axes!
    anchor_name = f"{bname_prefix}_anc"
    anc_obj: dict[str, Any] = {"name": anchor_name, "parent": parent_bone, "x": cx, "y": cy}
    if abs(qrot) > 0.01:
        anc_obj["rotation"] = qrot
    bones.append(anc_obj)

    has_u = abs(uv_u) > 1e-4
    has_v = abs(uv_v) > 1e-4
    dir_u = -1.0 if uv_u > 0 else 1.0
    dir_v = -1.0 if uv_v > 0 else 1.0
    ku = max(1, int(round(dur_q * abs(uv_u)))) if has_u else 0
    kv = max(1, int(round(dur_q * abs(uv_v)))) if has_v else 0

    if has_u and has_v:
        # 2x2 diagonal UV scroll tile grid
        tile_offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]
        k_wraps = max(ku, kv)
        dx = round(dir_u * qw, 2)
        dy = round(dir_v * qh, 2)
    elif has_u:
        tile_offsets = [(0, 0), (1, 0)]
        k_wraps = ku
        dx = round(dir_u * qw, 2)
        dy = 0.0
    else:
        tile_offsets = [(0, 0), (0, 1)]
        k_wraps = max(1, kv)
        dx = 0.0
        dy = round(dir_v * qh, 2)

    seg_t = dur_q / max(1, k_wraps)
    for ti, (ix, iy) in enumerate(tile_offsets):
        bname = f"{bname_prefix}_t{ti}"
        bx = round(-dir_u * qw * ix, 2) if ix else 0.0
        by = round(-dir_v * qh * iy, 2) if iy else 0.0
        bones.append({"name": bname, "parent": anchor_name, "x": bx, "y": by})
        s_obj: dict[str, Any] = {"name": bname, "bone": bname, "color": "ffffff00"}
        if uvq.get("additive"):
            s_obj["blend"] = "additive"
        slots.append(s_obj)
        skin_att[bname] = {rname: {"width": qw, "height": qh}}
        t_keys = []
        for wi in range(k_wraps):
            t0 = round(wi * seg_t, 4)
            t1 = round((wi + 1) * seg_t - (0.0005 if wi < k_wraps - 1 else 0.0), 4)
            t_keys.append({"time": t0, "x": 0.0, "y": 0.0})
            kf_end: dict[str, Any] = {"time": t1, "x": dx, "y": dy}
            if wi < k_wraps - 1:
                kf_end["curve"] = "stepped"
            t_keys.append(kf_end)
        bone_anims[bname] = {"translate": t_keys}
        slot_anims[bname] = {
            "attachment": [{"time": 0.0, "name": rname}],
            "color": [{"time": 0.0, "color": qcol}],
        }


def emit_native_fx_nodes_into_skeleton(
    clip: dict[str, Any],
    node_indices: set[int] | None,
    anim_pref: str,
    parent_bone: str,
    is_idle: bool,
    T_loop: float,
    T_sub: float,
    repeat_cnt: int,
    tex_index: dict[str, Path],
    tex_key_to_regs: dict[tuple[str, int, int, bool], list[str]],
    coord_fn,
    size_fn,
    rot_offset_deg: float,
    viewport_rect: tuple[float, float, float, float] | None,
    bones: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    skin_att: dict[str, Any],
    bone_anims: dict[str, Any],
    slot_anims: dict[str, Any],
    total_bone_budget: int = 480,
) -> float:
    """Emit selected (or all) native FX nodes + UV quads in exact (eff_sort_order, sort_order, dfs_seq) order.

    Uses Water-Filling bone allocation + time-stratified subsampling + Multi-Bone Torus Phase-Relay.
    Returns max animation duration produced.
    """
    all_nodes = clip.get("nodes") or []
    sel_nodes = [n for n in all_nodes if node_indices is None or n["idx"] in node_indices]
    uv_by_idx = {int(q["node_idx"]): q for q in (clip.get("uv_quads") or [])}
    ordered_nodes = sorted(
        sel_nodes,
        key=lambda n: (int(n.get("eff_sort_order", 0)), int(n.get("sort_order", 0)), int(n.get("dfs_seq", n["idx"])), int(n["idx"])),
    )

    # Pass 1: Pre-pack non-UV nodes unconstrained to measure exact natural bone demand (Water-Filling!)
    tracks_by_node: dict[int, list[dict[str, Any]]] = {}
    for tr in (clip.get("tracks") or []):
        ni = int(tr["node"])
        if node_indices is None or ni in node_indices:
            tracks_by_node.setdefault(ni, []).append(tr)

    prepared: list[dict[str, Any]] = []
    demands: list[int] = []
    max_anim_dur = T_loop if is_idle else 0.2

    for n in ordered_nodes:
        ni = int(n["idx"])
        tname = (n.get("tex") or "").strip()
        tp = tex_index.get(tname.lower()) or tex_index.get(Path(tname).stem.lower())
        if tp is None:
            continue
        if n.get("is_uv_scroll"):
            uvq = uv_by_idx.get(ni)
            regs = tex_key_to_regs.get((tp.stem.lower(), 1, 1, True))
            if uvq and regs:
                prepared.append({"kind": "uv", "n": n, "uvq": uvq, "rname": regs[0]})
            continue

        tx = max(1, int(n.get("tiles_x", 1)))
        ty = max(1, int(n.get("tiles_y", 1)))
        regs = tex_key_to_regs.get((tp.stem.lower(), tx, ty, False))
        ntrs = tracks_by_node.get(ni) or []
        if not regs or not ntrs:
            continue

        n_regs = len(regs)
        reg_fn = lambda _n, tile, _regs=regs, _nr=n_regs: _regs[tile % _nr]
        rbm = int(n.get("ring_buffer_mode", 0))
        max_p = int(n.get("max_particles", 50))
        if is_idle:
            pooled = build_periodic_pool(
                ntrs, t_win_start=1.5, period=T_sub,
                coord_fn=coord_fn, size_fn=size_fn, rot_offset_deg=rot_offset_deg,
                region_fn=reg_fn, max_bones=999,
                ring_buffer_mode=rbm, max_particles=max_p,
                node_meta=n, viewport_rect=viewport_rect,
            )
            t_used = 1.5
            if not pooled:
                pooled = build_periodic_pool(
                    ntrs, t_win_start=0.0, period=T_sub,
                    coord_fn=coord_fn, size_fn=size_fn, rot_offset_deg=rot_offset_deg,
                    region_fn=reg_fn, max_bones=999,
                    ring_buffer_mode=rbm, max_particles=max_p,
                    node_meta=n, viewport_rect=viewport_rect,
                )
                t_used = 0.0
            period_used = T_sub
            rep_used = repeat_cnt
        else:
            pooled, oneshot_dur = build_oneshot_pool(
                ntrs, coord_fn=coord_fn, size_fn=size_fn, rot_offset_deg=rot_offset_deg,
                region_fn=reg_fn, max_bones=999,
                node_meta=n, viewport_rect=viewport_rect,
            )
            max_anim_dur = max(max_anim_dur, oneshot_dur)
            t_used = 0.0
            period_used = oneshot_dur
            rep_used = 1

        if pooled:
            demands.append(len(pooled))
            prepared.append({
                "kind": "ps", "n": n, "regs": regs, "reg_fn": reg_fn,
                "ntrs": ntrs, "pooled": pooled, "t_used": t_used,
                "period_used": period_used, "rep_used": rep_used,
                "demand_idx": len(demands) - 1,
            })

    caps = water_fill_budgets(demands, total_budget=total_bone_budget)

    # Pass 2: Re-pack any over-budget node with time-stratified subsampling, then emit strictly in painter's order!
    uv_counter = 0
    for item in prepared:
        n = item["n"]
        ni = int(n["idx"])
        if item["kind"] == "uv":
            emit_uv_quad_into_skeleton(
                item["uvq"], f"{anim_pref}_uv{ni}_{uv_counter}", parent_bone, item["rname"],
                coord_fn, size_fn, rot_offset_deg, T_loop if is_idle else 3.0,
                bones, slots, skin_att, bone_anims, slot_anims,
            )
            uv_counter += 1
            continue

        cap = caps[item["demand_idx"]]
        pooled = item["pooled"]
        if len(pooled) > cap and is_idle and int(n.get("ring_buffer_mode", 0)) == 0:
            ratio = max(0.15, (cap / max(1, len(pooled))) * 0.96)
            pooled = build_periodic_pool(
                item["ntrs"], t_win_start=item["t_used"], period=item["period_used"],
                coord_fn=coord_fn, size_fn=size_fn, rot_offset_deg=rot_offset_deg,
                region_fn=item["reg_fn"], max_bones=cap,
                ring_buffer_mode=0, max_particles=int(n.get("max_particles", 50)),
                node_meta=n, viewport_rect=viewport_rect, subsample_ratio=ratio,
            )
        else:
            pooled = pooled[:cap]

        regs = item["regs"]
        for bi, bitems in enumerate(pooled):
            bname = f"{anim_pref}_n{ni}_{bi:02d}"
            bones.append({"name": bname, "parent": parent_bone})
            s_obj: dict[str, Any] = {"name": bname, "bone": bname, "color": "ffffff00"}
            if n.get("additive"):
                s_obj["blend"] = "additive"
            slots.append(s_obj)
            skin_att[bname] = {rn: {"width": 100.0, "height": 100.0} for rn in regs}
            ba, sa = emit_bone_timelines(bitems, period=item["period_used"], repeat_count=item["rep_used"])
            bone_anims[bname] = ba
            slot_anims[bname] = sa

    return max_anim_dur


def compute_native_idle_period(
    clip: dict[str, Any],
    node_indices: set[int] | None = None,
    tween_nodes: list[dict[str, Any]] | None = None,
    min_multiple_of: float | None = None,
    default_rec_dur: float = 42.0,
) -> tuple[float, float, int]:
    """Compute optimal (T_loop, T_sub, repeat_cnt) preserving true speed and aligning periodic pulses/bursts/GPU T."""
    nodes = [n for n in (clip.get("nodes") or []) if node_indices is None or n["idx"] in node_indices]
    uv_quads = [q for q in (clip.get("uv_quads") or []) if node_indices is None or int(q["node_idx"]) in node_indices]
    clip_rec_dur = float(clip.get("record_dur") or default_rec_dur)

    # With Multi-Bone Torus Phase-Relay, T_sub no longer needs to exceed max_life!
    # We just need T_sub comfortably inside [12, 24] so particles have rich variety and clean sampling inside clip_rec_dur!
    safe_sub_hi = max(12.0, min(24.0, clip_rec_dur - 4.0))
    base_sub = min(safe_sub_hi, 16.0)

    # Detect periodic pulsing or regular multi-particle burst emitters (max_particles <= 20, regular burst_interval)
    pulse_cands: list[float] = []
    for n in nodes:
        if n.get("is_uv_scroll") or int(n.get("ring_buffer_mode", 0)) != 0:
            continue
        pni = int(n["idx"])
        b_int = float(n.get("burst_interval", 0.0) or 0.0)
        b_cnt = int(n.get("burst_count", 0) or 0)
        if b_cnt > 0 and 0.5 <= b_int <= 12.0:
            pulse_cands.append(round(b_int, 3))
            continue
        if int(n.get("max_particles", 50)) <= 2:
            births = sorted(
                float(tr["pts"][0][0]) for tr in (clip.get("tracks") or [])
                if tr["node"] == pni and tr.get("born_in_window") and tr.get("pts")
            )
            if len(births) >= 3:
                diffs = [births[i + 1] - births[i] for i in range(len(births) - 1) if births[i + 1] - births[i] > 0.5]
                if diffs:
                    diffs.sort()
                    med = diffs[len(diffs) // 2]
                    if 1.0 <= med <= 12.0 and all(abs(d - med) <= 0.15 for d in diffs):
                        pulse_cands.append(round(med, 3))

    if min_multiple_of and min_multiple_of > 0.5:
        # Align strictly to an integer multiple of GPU band period T_gpu so GPU repeats seamlessly!
        mult = max(1, int(round(max(12.0, base_sub) / min_multiple_of)))
        base_sub = round(mult * min_multiple_of, 4)
        if base_sub > safe_sub_hi and mult > 1:
            base_sub = round(max(1, int(math.floor(safe_sub_hi / min_multiple_of))) * min_multiple_of, 4)
    elif pulse_cands and not uv_quads:
        p_dom = max(set(pulse_cands), key=pulse_cands.count)
        mult = max(1, int(round(base_sub / p_dom)))
        snapped = round(mult * p_dom, 4)
        if 8.0 <= snapped <= safe_sub_hi + 0.5:
            base_sub = snapped

    if uv_quads:
        uv_speeds = [
            max(abs(float(q.get("uv_u", 0.0))), abs(float(q.get("uv_v", 0.0))))
            for q in uv_quads
        ]
        sp_min = max(0.01, min(uv_speeds))
        T_loop = round(min(92.0, max(base_sub, 1.0 / sp_min)), 4)
    else:
        T_loop = round(base_sub, 4)

    if tween_nodes:
        for grp in tween_nodes:
            for tw in (grp.get("tweens") or []):
                td = float(tw.get("duration", 0.0)) * (2.0 if int(tw.get("style", 1)) == 2 else 1.0)
                if td > T_loop:
                    T_loop = round(td, 4)

    if min_multiple_of and min_multiple_of > 0.5:
        mult_tot = max(1, int(round(T_loop / min_multiple_of)))
        T_loop = round(mult_tot * min_multiple_of, 4)

    repeat_cnt = max(1, int(round(T_loop / max(8.0, base_sub)))) if T_loop > safe_sub_hi + 2.0 else 1
    T_sub = round(T_loop / repeat_cnt, 4)
    return T_loop, T_sub, repeat_cnt



def convert_one_fx_folder(
    fd: Path,
    export_data: dict[str, Any],
    clip_mapping: dict[str, str],  # spine_anim_name -> export_clip_name
    tex_index: dict[str, Path],
    force: bool = False,
    tween_nodes: list[dict[str, Any]] | None = None,
    create_opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg_p = fd / ".config.json"
    if cfg_p.is_file():
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
        old_skel_p = fd / cfg["skeleton"]
        old_skel = json.loads(old_skel_p.read_text(encoding="utf-8-sig"))
        old_anims = list((old_skel.get("animations") or {}).keys())
        old_bytes = sum(f.stat().st_size for f in fd.rglob("*") if f.is_file())
        sk_meta = old_skel.get("skeleton") or {}
    else:
        if not create_opts:
            return {"status": "skipped", "reason": "missing_config_and_create_opts", "old_bytes": 0}
        fd.mkdir(parents=True, exist_ok=True)
        old_skel_p = fd / f"{fd.name}.json"
        old_anims = list(clip_mapping.keys()) or ["idle"]
        old_bytes = 0
        sk_meta = {}
        cfg = {
            "conf_ver": 1,
            "type": 9,
            "controllers": {
                "param_hit": {},
                "param_loop": {},
                "key_trigger": {},
                "intimacy_system": {},
                "slot_opacity": {},
                "slot_color": {},
            },
            "hit_areas": [],
            "motions": {
                "idle": [{"name": "idle", "file": "idle", "fade_in": 0, "fade_out": 0, "file_loop": True}],
            },
            "options": {
                "id": create_opts["model_id"],
                "scale_factor": create_opts["scale_factor"],
                "position_x": 0.0,
                "position_y": 0.0,
                "tex_type": 1,
                "shader_type": 0,
                "edge_padding": False,
            },
            "skeleton": old_skel_p.name,
            "atlases": [],
        }

    # Always lock fx_clip bounds to sibling bg_static.json when available!
    bg_bounds = _read_bg_static_bounds(fd.parent)
    if bg_bounds is not None:
        bg_x, bg_y, bg_w, bg_h = bg_bounds
    else:
        bg_w = float(sk_meta.get("width") or export_data["canvas_w"])
        bg_h = float(sk_meta.get("height") or export_data["canvas_h"])
        bg_x = float(sk_meta.get("x", -bg_w / 2.0))
        bg_y = float(sk_meta.get("y", -bg_h / 2.0))

    fx_rx, fx_ry, coord_fn, size_fn, rot_offset_deg = _make_coord_mappers(export_data, bg_x, bg_y, bg_w, bg_h)
    clips_by_name = {c["clip"]: c for c in (export_data.get("clips") or [])}

    # 1. Gather unique textures & tile grids across all mapped clips + tween_nodes
    pack_items: list[dict[str, Any]] = []
    tex_key_to_regs: dict[tuple[str, int, int, bool], list[str]] = {}
    reg_counter = 0

    for grp in (tween_nodes or []):
        for sp in (grp.get("sprites") or []):
            tname = (sp.get("tex") or "").strip()
            if not tname:
                continue
            tp = tex_index.get(tname.lower()) or tex_index.get(Path(tname).stem.lower())
            if tp is None:
                return {"status": "skipped", "reason": f"missing_tween_texture:{tname}", "old_bytes": old_bytes}
            tkey = (tp.stem.lower(), 1, 1, True)
            if tkey in tex_key_to_regs:
                continue
            im_pma = to_pma(Image.open(tp))
            rname = f"tw{reg_counter}_{sanitize_id(tp.stem)[:18]}"
            reg_counter += 1
            pack_items.append({
                "name": rname, "im": im_pma,
                "orig_w": im_pma.width, "orig_h": im_pma.height,
                "off_x": 0, "off_y": 0, "pad": 2,
            })
            tex_key_to_regs[tkey] = [rname]

    for anim_name, exp_clip_name in clip_mapping.items():
        clip = clips_by_name.get(exp_clip_name)
        if not clip:
            return {"status": "skipped", "reason": f"missing_export_clip:{exp_clip_name}", "old_bytes": old_bytes}
        for n in clip["nodes"]:
            tname = (n.get("tex") or "").strip()
            if not tname:
                continue
            tp = tex_index.get(tname.lower()) or tex_index.get(Path(tname).stem.lower())
            if tp is None:
                return {"status": "skipped", "reason": f"missing_texture:{tname}", "old_bytes": old_bytes}
            tx = max(1, int(n.get("tiles_x", 1)))
            ty = max(1, int(n.get("tiles_y", 1)))
            is_uv = bool(n.get("is_uv_scroll", False))
            tkey = (tp.stem.lower(), tx, ty, is_uv)
            if tkey in tex_key_to_regs:
                continue
            im_pma = to_pma(Image.open(tp))
            regs: list[str] = []
            if is_uv or (tx == 1 and ty == 1):
                rname = f"r{reg_counter}_{sanitize_id(tp.stem)[:18]}"
                reg_counter += 1
                if is_uv:
                    pack_items.append({
                        "name": rname, "im": im_pma,
                        "orig_w": im_pma.width, "orig_h": im_pma.height,
                        "off_x": 0, "off_y": 0, "pad": 4,
                    })
                else:
                    cr, ow, oh, ox, oy = trim_sprite(im_pma, alpha_thr=1)
                    pack_items.append({
                        "name": rname, "im": cr,
                        "orig_w": ow, "orig_h": oh,
                        "off_x": ox, "off_y": oy, "pad": 2,
                    })
                regs.append(rname)
            else:
                cw = max(1, im_pma.width // tx)
                ch = max(1, im_pma.height // ty)
                for ti in range(tx * ty):
                    cx, cy = ti % tx, ti // tx
                    cell = im_pma.crop((cx * cw, cy * ch, (cx + 1) * cw, (cy + 1) * ch))
                    cr, ow, oh, ox, oy = trim_sprite(cell, alpha_thr=1)
                    rname = f"r{reg_counter}_{sanitize_id(tp.stem)[:14]}_t{ti}"
                    reg_counter += 1
                    pack_items.append({
                        "name": rname, "im": cr,
                        "orig_w": ow, "orig_h": oh,
                        "off_x": ox, "off_y": oy, "pad": 2,
                    })
                    regs.append(rname)
            tex_key_to_regs[tkey] = regs

    if not pack_items:
        return {"status": "skipped", "reason": "no_pack_items", "old_bytes": old_bytes}

    atlas_im, regions = pack_shelf(pack_items, pad=2)

    # 2. Build unified Spine 3.8 skeleton with fx_root anchored cleanly in Main-Person Spine space
    bones: list[dict[str, Any]] = [
        {"name": "root"},
        {"name": "fx_root", "parent": "root", "x": fx_rx, "y": fx_ry},
    ]
    slots: list[dict[str, Any]] = [{"name": "fx_clip", "bone": "root", "attachment": "fx_clip"}]
    skin_att: dict[str, Any] = {
        "fx_clip": {
            "fx_clip": {
                "type": "clipping",
                "end": "",
                "vertexCount": 4,
                "vertices": [
                    round(bg_x, 2), round(bg_y, 2),
                    round(bg_x + bg_w, 2), round(bg_y, 2),
                    round(bg_x + bg_w, 2), round(bg_y + bg_h, 2),
                    round(bg_x, 2), round(bg_y + bg_h, 2),
                ],
            }
        }
    }
    animations: dict[str, Any] = {}

    for old_anim in old_anims:
        if old_anim == "idle_empty":
            continue
        is_idle = old_anim.lower() == "idle"
        if old_anim not in clip_mapping:
            if is_idle and tween_nodes:
                bone_anims: dict[str, Any] = {}
                slot_anims: dict[str, Any] = {}
                tw_dur = _emit_tween_nodes_into_skeleton(
                    tween_nodes, tex_index, tex_key_to_regs,
                    coord_fn, size_fn, rot_offset_deg,
                    bones, slots, skin_att, bone_anims, slot_anims, 16.0,
                )
                bone_anims["root"] = {
                    "translate": [{"time": 0.0, "x": 0.0, "y": 0.0}, {"time": round(tw_dur, 4), "x": 0.0, "y": 0.0}]
                }
                animations[old_anim] = {"bones": bone_anims, "slots": slot_anims}
            else:
                animations[old_anim] = {}
            continue

        exp_clip_name = clip_mapping[old_anim]
        clip = clips_by_name[exp_clip_name]
        anim_pref = sanitize_id(old_anim)[:14]

        bone_anims = {}
        slot_anims = {}

        if is_idle:
            T_loop, T_sub, repeat_cnt = compute_native_idle_period(
                clip, node_indices=None, tween_nodes=tween_nodes,
                default_rec_dur=float(export_data.get("record_dur") or 42.0),
            )
        else:
            T_loop, T_sub, repeat_cnt = 0.2, 0.0, 1

        if is_idle and tween_nodes:
            _emit_tween_nodes_into_skeleton(
                tween_nodes, tex_index, tex_key_to_regs,
                coord_fn, size_fn, rot_offset_deg,
                bones, slots, skin_att, bone_anims, slot_anims, T_loop,
            )

        max_anim_dur = emit_native_fx_nodes_into_skeleton(
            clip=clip,
            node_indices=None,
            anim_pref=anim_pref,
            parent_bone="fx_root",
            is_idle=is_idle,
            T_loop=T_loop,
            T_sub=T_sub,
            repeat_cnt=repeat_cnt,
            tex_index=tex_index,
            tex_key_to_regs=tex_key_to_regs,
            coord_fn=coord_fn,
            size_fn=size_fn,
            rot_offset_deg=rot_offset_deg,
            viewport_rect=(bg_x, bg_y, bg_w, bg_h),
            bones=bones,
            slots=slots,
            skin_att=skin_att,
            bone_anims=bone_anims,
            slot_anims=slot_anims,
            total_bone_budget=480,
        )

        # Root duration anchor so animation length is deterministic
        bone_anims["root"] = {
            "translate": [
                {"time": 0.0, "x": 0.0, "y": 0.0},
                {"time": round(max_anim_dur, 4), "x": 0.0, "y": 0.0},
            ]
        }
        animations[old_anim] = {"bones": bone_anims, "slots": slot_anims}

    if len(slots) <= 1:
        return {"status": "skipped", "reason": "no_particles_generated", "old_bytes": old_bytes}

    # Spine 3.8 does NOT support nested ClippingAttachments!
    # If all non-clip slots belong to a single Tween UI Mask (e.g. Akaset_S5 640x298 TV window),
    # replace fx_clip with the intersection of bg_static and that Mask and drop redundant inner clip slots.
    inner_clips = [s["name"] for s in slots[1:] if s["name"].startswith("tw_mask_")]
    if inner_clips:
        # Intersect bg_static rect with the inner mask rect on fx_clip and remove inner clip slots
        first_mc = skin_att[inner_clips[0]][inner_clips[0]]["vertices"]
        mx0, my0, mx1, my1 = first_mc[0], first_mc[1], first_mc[4], first_mc[5]
        ix0 = max(bg_x, mx0)
        iy0 = max(bg_y, my0)
        ix1 = min(bg_x + bg_w, mx1)
        iy1 = min(bg_y + bg_h, my1)
        if ix1 > ix0 + 2.0 and iy1 > iy0 + 2.0:
            skin_att["fx_clip"]["fx_clip"]["vertices"] = [
                round(ix0, 2), round(iy0, 2),
                round(ix1, 2), round(iy0, 2),
                round(ix1, 2), round(iy1, 2),
                round(ix0, 2), round(iy1, 2),
            ]
        slots = [s for s in slots if s["name"] not in inner_clips]
        for ic in inner_clips:
            skin_att.pop(ic, None)

    skin_att["fx_clip"]["fx_clip"]["end"] = slots[-1]["name"]

    new_skel = {
        "skeleton": {
            "hash": fd.name,
            "spine": "3.8.79",
            "x": round(bg_x, 2),
            "y": round(bg_y, 2),
            "width": round(bg_w, 2),
            "height": round(bg_h, 2),
        },
        "bones": bones,
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin_att}],
        "animations": animations,
    }
    new_skel_bytes = json.dumps(new_skel, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # Write candidate webp to temp path first to check strictly smaller size!
    tmp_webp = fd / f"_tmp_{fd.name}.webp"
    save_exact_webp(atlas_im, tmp_webp)
    est_new_bytes = tmp_webp.stat().st_size + len(new_skel_bytes) + 4096

    if not force and old_bytes > 0 and est_new_bytes >= old_bytes:
        tmp_webp.unlink(missing_ok=True)
        return {
            "status": "skipped",
            "reason": "not_smaller",
            "old_bytes": old_bytes,
            "est_new_bytes": est_new_bytes,
        }

    # Commit cleanly! Remove old textures and replace atlas + skel + config
    final_webp_name = f"{fd.name}.webp"
    final_atlas_name = f"{fd.name}.atlas.txt"
    for old_tex in list(fd.glob("*.png")) + list(fd.glob("*.webp")):
        if old_tex != tmp_webp:
            old_tex.unlink()
    tmp_webp.replace(fd / final_webp_name)

    for old_atl in list(fd.glob("*.atlas.txt")):
        if old_atl.name != final_atlas_name:
            old_atl.unlink()
    write_atlas_txt(fd / final_atlas_name, final_webp_name, atlas_im.width, atlas_im.height, regions)

    old_skel_p.write_bytes(new_skel_bytes)

    cfg["options"]["tex_type"] = 1
    cfg["options"]["shader_type"] = 0
    cfg["atlases"] = [{
        "atlas": final_atlas_name,
        "tex_names": [fd.name],
        "textures": [final_webp_name],
    }]
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    new_bytes = sum(f.stat().st_size for f in fd.rglob("*") if f.is_file())
    return {
        "status": "converted",
        "old_bytes": old_bytes,
        "new_bytes": new_bytes,
        "saved_bytes": old_bytes - new_bytes,
        "atlas_size": list(atlas_im.size),
        "bones": len(bones),
        "anims": list(animations.keys()),
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Convert heavy Spine fx_* frame sequences to native Spine 3.8 bone particles")
    ap.add_argument("--force", action="store_true", help="Re-convert already-native fx_* folders (e.g. to fix fx_root offset or updated bounds)")
    ap.add_argument("--skins", type=str, default="", help="Optional comma-separated skin_key filter")
    args = ap.parse_args()
    want_skins = {x.strip().lower() for x in args.skins.split(",") if x.strip()} if args.skins else set()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    cat = {s["skin_key"]: s for s in build_skin_catalog(FullI18nRepo())}
    tex_index = build_tex_index()

    converted_list = []
    skipped_list = []
    total_old = total_new = 0

    for s in manifest["skins"]:
        sk = s["skin_key"]
        if want_skins and sk.lower() not in want_skins:
            continue
        if sk == "4301_HeLing_S2" and not args.force:
            continue
        ci = cat.get(sk)
        if not ci:
            continue
        exp_p = EXPORT_DIR / f"{sk}.json"
        if not exp_p.is_file():
            continue

        cbn = {c["clip"]: c for c in s["clips"]}
        sdir = SPINE_ROOT / ci["char_name"] / ci["dress_name"] / "submodels"
        if not sdir.is_dir():
            continue

        export_data = None
        for fd in sorted(sdir.glob("fx_*")):
            if not fd.is_dir():
                continue
            cfg = json.loads((fd / ".config.json").read_text(encoding="utf-8-sig"))
            old_skel_obj = json.loads((fd / cfg["skeleton"]).read_text(encoding="utf-8-sig"))
            anims = [
                a for a in (old_skel_obj.get("animations") or {})
                if a != "idle_empty"
            ]
            # When --force is set, only force-overwrite folders that are ALREADY native-particle OR strictly smaller
            already_native = any(
                b.get("name") != "root" and ("_uv" in b.get("name", "") or "_n" in b.get("name", ""))
                for b in (old_skel_obj.get("bones") or [])
            )
            clip_map: dict[str, str] = {}
            for a in anims:
                if a in cbn:
                    clip_map[a] = a
                elif a == "idle" and fd.name.endswith("_back") and "idle_back" in cbn:
                    clip_map[a] = "idle_back"
                elif a == "idle" and fd.name.endswith("_front") and "idle_front" in cbn:
                    clip_map[a] = "idle_front"
                elif a == "idle" and "idle" in cbn:
                    clip_map[a] = "idle"
                elif a == "idle" and not fd.name.endswith(("_back", "_front")):
                    # Single-folder fx_* when manifest splits idle_back/idle_front: NEVER drop idle!
                    if "idle_front" in cbn and "idle_back" not in cbn:
                        clip_map[a] = "idle_front"
                    elif "idle_back" in cbn and "idle_front" not in cbn:
                        clip_map[a] = "idle_back"
                    elif "idle_back" in cbn and "idle_front" in cbn:
                        # Prefer splitting via spine_fx_submodel_packer rather than silently wiping idle to {}!
                        clip_map = {}
                        break
            if not clip_map:
                continue
            if any(node_blockers(n) for cn in clip_map.values() for n in cbn[cn]["nodes"]):
                continue

            if export_data is None:
                export_data = json.loads(exp_p.read_text(encoding="utf-8-sig"))

            res = convert_one_fx_folder(fd, export_data, clip_map, tex_index, force=(args.force and already_native))
            rel = f"{ci['char_name']}/{ci['dress_name']}/{fd.name}"
            if res["status"] == "converted":
                total_old += res["old_bytes"]
                total_new += res["new_bytes"]
                converted_list.append({"target": rel, "skin_key": sk, **res})
                print(
                    f"  [OK] {rel}: {res['old_bytes']/1048576:.2f} MB -> {res['new_bytes']/1048576:.2f} MB "
                    f"(atlas={res['atlas_size']}, bones={res['bones']})",
                    flush=True,
                )
            else:
                skipped_list.append({"target": rel, "skin_key": sk, **res})
                print(f"  [SKIP] {rel}: {res.get('reason')}", flush=True)

    report = {
        "converted_count": len(converted_list),
        "skipped_count": len(skipped_list),
        "old_mb": round(total_old / 1048576, 2),
        "new_mb": round(total_new / 1048576, 2),
        "saved_mb": round((total_old - total_new) / 1048576, 2),
        "converted": converted_list,
        "skipped": skipped_list,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("converted", "skipped")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
