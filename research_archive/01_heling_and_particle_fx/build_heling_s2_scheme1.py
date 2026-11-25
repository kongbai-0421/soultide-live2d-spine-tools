"""Build Native Spine 3.8 Particle/UV-Scroll FX + 100% Lossless WebP for 和铃/古锦新韵."""

from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

PARTICLES_JSON = Path(r".\_scratch\heling_s2_particles.json")
TEX_DIR = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures")
SKIN_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\和铃\古锦新韵")
BACKUP_DIR = Path(r".\_scratch\heling_s2_backup_pngs")

BG_W = 4250.0
BG_H = 2833.3333
BASE_SCALE = 0.077


def to_pma(im: Image.Image) -> Image.Image:
    arr = np.array(im.convert("RGBA"), dtype=np.float32)
    a = arr[:, :, 3:4] / 255.0
    arr[:, :, :3] = np.clip(np.round(arr[:, :, :3] * a), 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def trim_sprite(im: Image.Image, alpha_thr: int = 1) -> tuple[Image.Image, int, int, int, int]:
    """Return (cropped_im, orig_w, orig_h, spine_offset_x, spine_offset_y).
    Spine atlas offset_x = left trim, offset_y = bottom trim (Spine Y-up!)."""
    ow, oh = im.size
    arr = np.array(im.convert("RGBA"))
    mask = arr[:, :, 3] >= alpha_thr
    if not mask.any():
        return im.crop((0, 0, 2, 2)), ow, oh, 0, oh - 2
    ys, xs = np.where(mask)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    cropped = im.crop((x0, y0, x1, y1))
    off_x = x0
    off_y = oh - y1  # distance from bottom!
    return cropped, ow, oh, off_x, off_y


def pack_shelf(items: list[dict[str, Any]], max_w: int = 1024, pad: int = 2) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Simple shelf packer returning power-of-two RGBA atlas image + placed region metadata."""
    # Sort tallest first for tight packing
    ordered = sorted(items, key=lambda it: (-it["im"].height, -it["im"].width))
    # Try compact power-of-two widths/heights
    for cand_w, cand_h in [(512, 512), (1024, 512), (1024, 1024), (2048, 1024)]:
        if cand_w > max_w:
            continue
        x = 0
        y = 0
        row_h = 0
        placements = []
        ok = True
        for it in ordered:
            w, h = it["im"].size
            p = it.get("pad", pad)
            if w > cand_w:
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
                    "x": px,
                    "y": py,
                    "w": w,
                    "h": h,
                    "orig_w": it["orig_w"],
                    "orig_h": it["orig_h"],
                    "off_x": it["off_x"],
                    "off_y": it["off_y"],
                })
            return atlas, placed_meta
    raise RuntimeError("Failed to pack sprites into atlas")


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
    # shortest angle interpolation for idx 5
    d = (p1[5] - p0[5] + 180.0) % 360.0 - 180.0
    res[5] = p0[5] + d * alpha
    res.append(p0[10])
    return res


def decimate_1d(times: list[float], vals: list[float], tol: float, max_step: float | None = None) -> list[int]:
    """Douglas-Peucker style index selection preserving linear interpolation within `tol`."""
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
            pred = v0 + (v1 - v0) * u
            err = abs(vals[i] - pred)
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
            px = xs[i0] + (xs[i1] - xs[i0]) * u
            py = ys[i0] + (ys[i1] - ys[i0]) * u
            err = math.hypot(xs[i] - px, ys[i] - py)
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
    ri = max(0, min(255, int(round(r * 255))))
    gi = max(0, min(255, int(round(g * 255))))
    bi = max(0, min(255, int(round(b * 255))))
    ai = max(0, min(255, int(round(a * 255))))
    return f"{ri:02x}{gi:02x}{bi:02x}{ai:02x}"


def build_periodic_pool(
    tracks: list[dict[str, Any]],
    t_win_start: float,
    period: float,
    cam_x: float,
    cam_y: float,
    scale_u2s: float,
    region_fn,
    max_bones_hint: int = 64,
) -> list[list[dict[str, Any]]]:
    """Select complete tracks born in [t_win_start, t_win_start + period),
    wrap them seamlessly modulo `period`, and pack onto minimum pooled bones."""
    # Filter complete tracks in window
    selected = []
    for tr in tracks:
        if not (tr["born_in_window"] and tr["dead_in_window"]):
            continue
        t_start = tr["pts"][0][0]
        if t_win_start <= t_start < t_win_start + period:
            selected.append(tr)
    # Sort by start time
    selected.sort(key=lambda tr: tr["pts"][0][0])

    # Convert each track into 1 or 2 segments within [0, period]
    # Each pool item has intervals on [0, period] that cannot overlap on the same bone!
    items: list[dict[str, Any]] = []
    for tr in selected:
        pts = tr["pts"]
        if len(pts) < 2:
            continue
        # Shift time by t_win_start and scale coords to Spine
        spts = []
        for p in pts:
            t_rel = p[0] - t_win_start
            sx = (p[1] - cam_x) * scale_u2s
            sy = (p[2] - cam_y) * scale_u2s
            sw = max(1.0, p[3] * scale_u2s)
            sh = max(1.0, p[4] * scale_u2s)
            rot = p[5]
            r, g, b, a = p[6], p[7], p[8], p[9]
            tile = int(p[10])
            spts.append([t_rel, sx, sy, sw, sh, rot, r, g, b, a, tile])

        # Ensure exact a=0 start and end points if close
        if spts[0][9] > 0.002:
            p_head = list(spts[0])
            p_head[0] = max(0.0, spts[0][0] - 0.02)
            p_head[9] = 0.0
            spts.insert(0, p_head)
        if spts[-1][9] > 0.002:
            p_tail = list(spts[-1])
            p_tail[0] = spts[-1][0] + 0.02
            p_tail[9] = 0.0
            spts.append(p_tail)

        # If track duration >= period - 0.1, clamp slightly so it never overlaps itself on wrap
        dur = spts[-1][0] - spts[0][0]
        if dur > period - 0.1:
            factor = (period - 0.15) / dur
            t0 = spts[0][0]
            for p in spts:
                p[0] = t0 + (p[0] - t0) * factor

        reg = region_fn(tr["node"], int(spts[0][10]))
        t_a, t_b = spts[0][0], spts[-1][0]
        segs = []
        if t_b <= period:
            segs.append((t_a, t_b, spts, False, False))
        else:
            # Split cleanly at t = period!
            seg1 = []
            seg2 = []
            bd_pt = None
            for i in range(len(spts) - 1):
                p0, p1 = spts[i], spts[i + 1]
                if p1[0] < period:
                    seg1.append(p0)
                elif p0[0] <= period <= p1[0]:
                    seg1.append(p0)
                    alpha = (period - p0[0]) / max(1e-6, p1[0] - p0[0])
                    bd_pt = interp_pt(p0, p1, alpha)
                    bd_end = list(bd_pt); bd_end[0] = period
                    bd_start = list(bd_pt); bd_start[0] = 0.0
                    seg1.append(bd_end)
                    seg2.append(bd_start)
                else:
                    p_wrap = list(p0); p_wrap[0] -= period
                    seg2.append(p_wrap)
            p_last = list(spts[-1]); p_last[0] -= period
            seg2.append(p_last)
            # Head segment [0, t_b - period] then tail segment [t_a, period]
            segs.append((0.0, seg2[-1][0], seg2, True, False))   # wraps_from_end=True
            segs.append((seg1[0][0], period, seg1, False, True)) # wraps_to_start=True

        items.append({
            "node": tr["node"],
            "region": reg,
            "segs": segs,
            "intervals": [(s[0], s[1]) for s in segs],
        })

    # Greedy interval packing onto minimum bones (gap >= 0.04s between non-wrapped segments)
    bones: list[list[dict[str, Any]]] = []
    bone_intervals: list[list[tuple[float, float]]] = []
    for it in items:
        placed = False
        for bi, b_ivs in enumerate(bone_intervals):
            conflict = False
            for a0, a1 in it["intervals"]:
                for b0, b1 in b_ivs:
                    if not (a1 + 0.04 <= b0 or b1 + 0.04 <= a0):
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
            bones.append([it])
            bone_intervals.append(list(it["intervals"]))

    return bones


def emit_bone_timelines(
    bone_items: list[dict[str, Any]],
    period: float,
    repeat_count: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build Spine 3.8 bone_anim and slot_anim dicts for one pooled bone over `period * repeat_count`."""
    # Flatten all segments sorted by start time within [0, period]
    flat_segs = []
    for it in bone_items:
        for (t0, t1, pts, wraps_from_end, wraps_to_start) in it["segs"]:
            flat_segs.append({
                "t0": t0,
                "t1": t1,
                "pts": pts,
                "region": it["region"],
                "wraps_from_end": wraps_from_end,
                "wraps_to_start": wraps_to_start,
            })
    flat_segs.sort(key=lambda s: s["t0"])

    tr_keys: list[dict[str, Any]] = []
    sc_keys: list[dict[str, Any]] = []
    rt_keys: list[dict[str, Any]] = []
    col_keys: list[dict[str, Any]] = []
    att_keys: list[dict[str, Any]] = []

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

            i_pos = decimate_2d(times, xs, ys, tol=0.6)
            i_sc = decimate_2d(times, sxs, sys_, tol=0.006)
            i_rt = decimate_1d(times, rots, tol=0.4, max_step=90.0)
            i_col = decimate_rgba(times, cols, tol=0.012)

            # Determine if we should step at end of this segment
            is_end_wrap = seg["wraps_to_start"]
            # Attachment ON at start of segment
            t_start_abs = round(base_t + times[0], 4)
            t_end_abs = round(base_t + times[-1], 4)

            if rep == 0 and si == 0 and times[0] > 0.001:
                # Initially hidden until first segment starts
                att_keys.append({"time": 0.0, "name": None})
                col_keys.append({"time": 0.0, "color": "ffffff00", "curve": "stepped"})

            # Avoid duplicate exact time on wrapped seam between rep k and rep k+1
            if not (rep > 0 and seg["wraps_from_end"]):
                att_keys.append({"time": t_start_abs, "name": seg["region"]})

            for idx_k, idx in enumerate(i_pos):
                if rep > 0 and seg["wraps_from_end"] and idx_k == 0:
                    continue
                kf: dict[str, Any] = {
                    "time": round(base_t + times[idx], 4),
                    "x": round(xs[idx], 2),
                    "y": round(ys[idx], 2),
                }
                if idx_k == len(i_pos) - 1 and not is_end_wrap:
                    kf["curve"] = "stepped"
                tr_keys.append(kf)

            for idx_k, idx in enumerate(i_sc):
                if rep > 0 and seg["wraps_from_end"] and idx_k == 0:
                    continue
                kf = {
                    "time": round(base_t + times[idx], 4),
                    "x": round(sxs[idx], 4),
                    "y": round(sys_[idx], 4),
                }
                if idx_k == len(i_sc) - 1 and not is_end_wrap:
                    kf["curve"] = "stepped"
                sc_keys.append(kf)

            for idx_k, idx in enumerate(i_rt):
                if rep > 0 and seg["wraps_from_end"] and idx_k == 0:
                    continue
                kf = {
                    "time": round(base_t + times[idx], 4),
                    "angle": round(rots[idx] % 360.0, 2),
                }
                if idx_k == len(i_rt) - 1 and not is_end_wrap:
                    kf["curve"] = "stepped"
                rt_keys.append(kf)

            for idx_k, idx in enumerate(i_col):
                if rep > 0 and seg["wraps_from_end"] and idx_k == 0:
                    continue
                r, g, b, a = cols[idx]
                kf = {
                    "time": round(base_t + times[idx], 4),
                    "color": rgba_hex(r, g, b, a),
                }
                if idx_k == len(i_col) - 1 and not is_end_wrap:
                    kf["curve"] = "stepped"
                col_keys.append(kf)

            # Hide attachment cleanly when track finishes (unless it wraps across period end!)
            if not is_end_wrap:
                att_keys.append({"time": t_end_abs, "name": None})

    # Ensure strictly monotonic times (dedupe tiny overlaps) and NEVER put "curve" on final keyframe!
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

    bone_anim = {
        "translate": dedupe(tr_keys),
        "scale": dedupe(sc_keys),
        "rotate": dedupe(rt_keys),
    }
    slot_anim = {
        "attachment": dedupe(att_keys),
        "color": dedupe(col_keys),
    }
    return bone_anim, slot_anim


def save_lossless_webp(im: Image.Image, out_path: Path) -> None:
    rgba = im.convert("RGBA")
    rgba.save(out_path, "WEBP", lossless=True, exact=True, quality=100, method=4)
    # Bit-for-bit exactness check (critical for Spine PMA alpha==0 pixels!)
    src_arr = np.array(rgba)
    dec_arr = np.array(Image.open(out_path).convert("RGBA"))
    assert src_arr.shape == dec_arr.shape and np.array_equal(src_arr, dec_arr), (
        f"WebP exactness failed for {out_path}: max_diff={np.abs(src_arr.astype(int)-dec_arr.astype(int)).max()}"
    )


def build_fx_back(data: dict[str, Any]) -> dict[str, Any]:
    sub_dir = SKIN_DIR / "submodels" / "fx_heling_s2_back"
    cam_x, cam_y = data["cam_x"], data["cam_y"]
    scale_u2s = BG_W / float(data["canvas_w"])

    clip = next(c for c in data["clips"] if c["clip"] == "idle_back")
    uvq = clip["uv_quads"][0]

    # 1. Build 100% lossless PMA WebP atlas: yun (1024x512) + 6 trimmed lizi tiles
    yun_im = to_pma(Image.open(TEX_DIR / "FX_cf_yun14.png"))
    lizi_sheet = to_pma(Image.open(TEX_DIR / "FX_cf_lizi11_b.png"))
    lw, lh = lizi_sheet.size
    tx_n, ty_n = 3, 2
    cw, ch = lw // tx_n, lh // ty_n

    pack_items = [{
        "name": "yun",
        "im": yun_im,
        "orig_w": yun_im.width,
        "orig_h": yun_im.height,
        "off_x": 0,
        "off_y": 0,
        "pad": 4,
    }]
    for ti in range(tx_n * ty_n):
        tx = ti % tx_n
        ty = ti // tx_n
        cell = lizi_sheet.crop((tx * cw, ty * ch, (tx + 1) * cw, (ty + 1) * ch))
        cr, ow, oh, ox, oy = trim_sprite(cell, alpha_thr=1)
        pack_items.append({
            "name": f"lizi_t{ti}",
            "im": cr,
            "orig_w": ow,
            "orig_h": oh,
            "off_x": ox,
            "off_y": oy,
            "pad": 2,
        })

    atlas_im, regions = pack_shelf(pack_items, max_w=1024, pad=2)
    # Remove any old pngs in fx_heling_s2_back
    for old_f in list(sub_dir.glob("*.png")) + list(sub_dir.glob("*.webp")):
        old_f.unlink()

    webp_name = "fx_heling_s2_back.webp"
    save_lossless_webp(atlas_im, sub_dir / webp_name)
    write_atlas_txt(sub_dir / "fx_heling_s2_back.atlas.txt", webp_name, atlas_im.width, atlas_im.height, regions)

    # 2. Build Native Spine 3.8 skeleton
    T_back = round(1.0 / abs(uvq["uv_u"]), 4)  # 90.9091s exact 1 full cloud wrap!
    repeat_lizi = 6
    T_sub = T_back / repeat_lizi  # 15.1515s

    yun_cx = round((uvq["x"] - cam_x) * scale_u2s, 2)
    yun_cy = round((uvq["y"] - cam_y) * scale_u2s, 2)
    yun_w = round(uvq["w"] * scale_u2s, 2)
    yun_h = round(uvq["h"] * scale_u2s, 2)
    yun_col = rgba_hex(uvq["r"], uvq["g"], uvq["b"], uvq["a"])
    # uv_u > 0 => texture scrolls left (-x)
    scroll_dir = -1.0 if uvq["uv_u"] > 0 else 1.0

    # Pool lizi particles across all 4 lizi emitters (nodes 1..4)
    lizi_tracks = [tr for tr in clip["tracks"] if tr["node"] in (1, 2, 3, 4)]
    lizi_bones = build_periodic_pool(
        lizi_tracks,
        t_win_start=1.0,
        period=T_sub,
        cam_x=cam_x,
        cam_y=cam_y,
        scale_u2s=scale_u2s,
        region_fn=lambda node_idx, tile: f"lizi_t{tile % 6}",
    )

    bones = [
        {"name": "root"},
        {"name": "yun_1", "parent": "root", "x": yun_cx, "y": yun_cy},
        {"name": "yun_2", "parent": "root", "x": round(yun_cx - scroll_dir * yun_w, 2), "y": yun_cy},
    ]
    slots = [
        {"name": "fx_clip", "bone": "root", "attachment": "fx_clip"},
        {"name": "yun_1", "bone": "yun_1", "color": yun_col, "attachment": "yun"},
        {"name": "yun_2", "bone": "yun_2", "color": yun_col, "attachment": "yun"},
    ]
    skin_att: dict[str, Any] = {
        "fx_clip": {
            "fx_clip": {
                "type": "clipping",
                "end": "",  # filled below
                "vertexCount": 4,
                "vertices": [
                    -round(BG_W / 2, 2), -round(BG_H / 2, 2),
                    round(BG_W / 2, 2), -round(BG_H / 2, 2),
                    round(BG_W / 2, 2), round(BG_H / 2, 2),
                    -round(BG_W / 2, 2), round(BG_H / 2, 2),
                ],
            }
        },
        "yun_1": {"yun": {"width": yun_w, "height": yun_h}},
        "yun_2": {"yun": {"width": yun_w, "height": yun_h}},
    }

    bone_anims: dict[str, Any] = {
        "yun_1": {
            "translate": [
                {"time": 0.0, "x": 0.0, "y": 0.0},
                {"time": T_back, "x": round(scroll_dir * yun_w, 2), "y": 0.0},
            ]
        },
        "yun_2": {
            "translate": [
                {"time": 0.0, "x": 0.0, "y": 0.0},
                {"time": T_back, "x": round(scroll_dir * yun_w, 2), "y": 0.0},
            ]
        },
    }
    slot_anims: dict[str, Any] = {}

    for bi, bitems in enumerate(lizi_bones):
        bname = f"lizi_{bi:02d}"
        bones.append({"name": bname, "parent": "root"})
        slots.append({"name": bname, "bone": bname, "color": "ffffff00"})
        # Attach all 6 tile variants (unit 100x100) so slot can switch tiles cleanly
        skin_att[bname] = {f"lizi_t{t}": {"width": 100.0, "height": 100.0} for t in range(6)}
        ba, sa = emit_bone_timelines(bitems, period=T_sub, repeat_count=repeat_lizi)
        bone_anims[bname] = ba
        slot_anims[bname] = sa

    skin_att["fx_clip"]["fx_clip"]["end"] = slots[-1]["name"]

    skel = {
        "skeleton": {
            "hash": "fx_heling_s2_back",
            "spine": "3.8.79",
            "x": -round(BG_W / 2, 2),
            "y": -round(BG_H / 2, 2),
            "width": round(BG_W, 2),
            "height": round(BG_H, 2),
        },
        "bones": bones,
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin_att}],
        "animations": {
            "idle": {
                "bones": bone_anims,
                "slots": slot_anims,
            }
        },
    }
    (sub_dir / "fx_heling_s2_back.json").write_text(
        json.dumps(skel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    skel_kb = round((sub_dir / "fx_heling_s2_back.json").stat().st_size / 1024, 1)

    cfg = json.loads((sub_dir / ".config.json").read_text(encoding="utf-8"))
    cfg["options"]["scale_factor"] = BASE_SCALE
    cfg["options"]["position_x"] = 0.0
    cfg["options"]["position_y"] = 0.0
    cfg["options"]["tex_type"] = 1
    cfg["atlases"] = [{
        "atlas": "fx_heling_s2_back.atlas.txt",
        "tex_names": ["fx_heling_s2_back"],
        "textures": [webp_name],
    }]
    (sub_dir / ".config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "layer": "fx_heling_s2_back",
        "atlas_size": atlas_im.size,
        "webp_kb": round((sub_dir / webp_name).stat().st_size / 1024, 1),
        "vram_mb": round(atlas_im.width * atlas_im.height * 4 / (1024 * 1024), 2),
        "bones": len(bones),
        "skel_kb": skel_kb,
        "duration": T_back,
    }


def build_fx_front(data: dict[str, Any]) -> dict[str, Any]:
    sub_dir = SKIN_DIR / "submodels" / "fx_heling_s2_front"
    cam_x, cam_y = data["cam_x"], data["cam_y"]
    scale_u2s = BG_W / float(data["canvas_w"])

    clip = next(c for c in data["clips"] if c["clip"] == "idle_front")

    # 1. Build 100% lossless PMA WebP atlas for all 5 front textures
    pack_items = []
    # huaban (2x2 tiles)
    hb_sheet = to_pma(Image.open(TEX_DIR / "FX_cf_huaban09.png"))
    hw, hh = hb_sheet.size
    for ti in range(4):
        tx, ty = ti % 2, ti // 2
        cell = hb_sheet.crop((tx * (hw // 2), ty * (hh // 2), (tx + 1) * (hw // 2), (ty + 1) * (hh // 2)))
        cr, ow, oh, ox, oy = trim_sprite(cell, alpha_thr=1)
        pack_items.append({
            "name": f"huaban_t{ti}", "im": cr, "orig_w": ow, "orig_h": oh, "off_x": ox, "off_y": oy, "pad": 2
        })
    # Other 4 single textures (NO alpha hard cut! keep exact full-feather alpha!)
    for rname, fname in [
        ("yezi", "FX_cf_lhuaban10.png"),
        ("guang", "FX_ZC_Glow017.png"),
        ("guangxian", "FX_glow01.png"),
        ("caihong", "FX_ZC_Glow019.png"),
    ]:
        im = to_pma(Image.open(TEX_DIR / fname))
        cr, ow, oh, ox, oy = trim_sprite(im, alpha_thr=1)
        pack_items.append({
            "name": rname, "im": cr, "orig_w": ow, "orig_h": oh, "off_x": ox, "off_y": oy, "pad": 2
        })

    atlas_im, regions = pack_shelf(pack_items, max_w=1024, pad=2)
    for old_f in list(sub_dir.glob("*.png")) + list(sub_dir.glob("*.webp")):
        old_f.unlink()

    webp_name = "fx_heling_s2_front.webp"
    save_lossless_webp(atlas_im, sub_dir / webp_name)
    write_atlas_txt(sub_dir / "fx_heling_s2_front.atlas.txt", webp_name, atlas_im.width, atlas_im.height, regions)

    # 2. Pool each node group cleanly over T_front = 18.0s
    T_front = 18.0
    t_win_start = 2.0

    # Group nodes by (additive, sort_order, idx)
    node_specs = sorted(clip["nodes"], key=lambda n: (n["sort_order"], n["idx"]))

    bones = [{"name": "root"}]
    slots = [{"name": "fx_clip", "bone": "root", "attachment": "fx_clip"}]
    skin_att: dict[str, Any] = {
        "fx_clip": {
            "fx_clip": {
                "type": "clipping",
                "end": "",
                "vertexCount": 4,
                "vertices": [
                    -round(BG_W / 2, 2), -round(BG_H / 2, 2),
                    round(BG_W / 2, 2), -round(BG_H / 2, 2),
                    round(BG_W / 2, 2), round(BG_H / 2, 2),
                    -round(BG_W / 2, 2), round(BG_H / 2, 2),
                ],
            }
        }
    }
    bone_anims: dict[str, Any] = {}
    slot_anims: dict[str, Any] = {}

    node_region_map = {
        0: (lambda _n, tile: f"huaban_t{tile % 4}", [f"huaban_t{t}" for t in range(4)], False),
        1: (lambda _n, _t: "yezi", ["yezi"], False),
        2: (lambda _n, _t: "guang", ["guang"], True),
        3: (lambda _n, _t: "guangxian", ["guangxian"], True),
        4: (lambda _n, _t: "caihong", ["caihong"], True),
    }

    for n in node_specs:
        ni = n["idx"]
        reg_fn, all_regs, is_add = node_region_map[ni]
        ntrs = [tr for tr in clip["tracks"] if tr["node"] == ni]
        # For yezi (very rare burst every ~10s), if [2, 20) has < 1 track, shift window to [0, 18)
        win_s = t_win_start
        pooled = build_periodic_pool(
            ntrs, t_win_start=win_s, period=T_front,
            cam_x=cam_x, cam_y=cam_y, scale_u2s=scale_u2s, region_fn=reg_fn
        )
        if not pooled and ntrs:
            pooled = build_periodic_pool(
                ntrs, t_win_start=0.0, period=T_front,
                cam_x=cam_x, cam_y=cam_y, scale_u2s=scale_u2s, region_fn=reg_fn
            )
        prefix = n["name"].replace(" ", "_")
        for bi, bitems in enumerate(pooled):
            bname = f"{prefix}_{bi:02d}"
            bones.append({"name": bname, "parent": "root"})
            slot_obj: dict[str, Any] = {"name": bname, "bone": bname, "color": "ffffff00"}
            if is_add:
                slot_obj["blend"] = "additive"
            slots.append(slot_obj)
            skin_att[bname] = {rn: {"width": 100.0, "height": 100.0} for rn in all_regs}
            ba, sa = emit_bone_timelines(bitems, period=T_front, repeat_count=1)
            bone_anims[bname] = ba
            slot_anims[bname] = sa

    # Add exact end-time anchor on root so Spine animation duration is guaranteed == T_front
    bone_anims["root"] = {
        "translate": [
            {"time": 0.0, "x": 0.0, "y": 0.0},
            {"time": T_front, "x": 0.0, "y": 0.0},
        ]
    }
    skin_att["fx_clip"]["fx_clip"]["end"] = slots[-1]["name"]

    skel = {
        "skeleton": {
            "hash": "fx_heling_s2_back",
            "spine": "3.8.79",
            "x": -round(BG_W / 2, 2),
            "y": -round(BG_H / 2, 2),
            "width": round(BG_W, 2),
            "height": round(BG_H, 2),
        },
        "bones": bones,
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin_att}],
        "animations": {
            "idle": {
                "bones": bone_anims,
                "slots": slot_anims,
            }
        },
    }
    (sub_dir / "fx_heling_s2_front.json").write_text(
        json.dumps(skel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    skel_kb = round((sub_dir / "fx_heling_s2_front.json").stat().st_size / 1024, 1)

    cfg = json.loads((sub_dir / ".config.json").read_text(encoding="utf-8"))
    cfg["options"]["scale_factor"] = BASE_SCALE
    cfg["options"]["position_x"] = 0.0
    cfg["options"]["position_y"] = 0.0
    cfg["options"]["tex_type"] = 1
    cfg["atlases"] = [{
        "atlas": "fx_heling_s2_front.atlas.txt",
        "tex_names": ["fx_heling_s2_front"],
        "textures": [webp_name],
    }]
    (sub_dir / ".config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "layer": "fx_heling_s2_front",
        "atlas_size": atlas_im.size,
        "webp_kb": round((sub_dir / webp_name).stat().st_size / 1024, 1),
        "vram_mb": round(atlas_im.width * atlas_im.height * 4 / (1024 * 1024), 2),
        "bones": len(bones),
        "skel_kb": skel_kb,
        "duration": T_front,
    }


def convert_static_layers_to_lossless_webp() -> list[dict[str, Any]]:
    """Convert MAIN, bj_01, and bg_static PNG textures to 100% lossless WebP."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        (SKIN_DIR, [".config.json", "config_en.config.json", "config_ja.config.json"]),
        (SKIN_DIR / "submodels" / "bj_01", [".config.json"]),
        (SKIN_DIR / "submodels" / "bg_static", [".config.json"]),
    ]
    results = []
    for folder, cfg_names in targets:
        main_cfg = json.loads((folder / cfg_names[0]).read_text(encoding="utf-8"))
        for atl in main_cfg.get("atlases", []):
            atlas_path = folder / atl["atlas"]
            atlas_txt = atlas_path.read_text(encoding="utf-8")
            new_texs = []
            for tex_rel in atl["textures"]:
                src = folder / tex_rel
                if tex_rel.lower().endswith(".png") and src.exists():
                    # Backup PNG once
                    bk = BACKUP_DIR / f"{folder.name}__{src.name}"
                    if not bk.exists():
                        shutil.copy2(src, bk)
                    dst_rel = tex_rel[:-4] + ".webp"
                    dst = folder / dst_rel
                    png_kb = src.stat().st_size / 1024.0
                    with Image.open(src) as im:
                        w, h = im.size
                        save_lossless_webp(im, dst)
                    webp_kb = dst.stat().st_size / 1024.0
                    atlas_txt = atlas_txt.replace(tex_rel, dst_rel)
                    src.unlink()
                    new_texs.append(dst_rel)
                    results.append({
                        "layer": folder.name,
                        "file": dst_rel,
                        "size": (w, h),
                        "png_kb": round(png_kb, 1),
                        "webp_kb": round(webp_kb, 1),
                        "saved_pct": round((1 - webp_kb / png_kb) * 100, 1),
                    })
                else:
                    new_texs.append(tex_rel)
            atlas_path.write_text(atlas_txt, encoding="utf-8")
            atl["textures"] = new_texs

        # Update all config variants in this folder
        for cname in cfg_names:
            cp = folder / cname
            if not cp.exists():
                continue
            c = json.loads(cp.read_text(encoding="utf-8"))
            c["options"]["tex_type"] = 1
            for i, atl in enumerate(c.get("atlases", [])):
                atl["textures"] = [
                    (t[:-4] + ".webp") if t.lower().endswith(".png") else t
                    for t in atl.get("textures", [])
                ]
            cp.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def main() -> None:
    data = json.loads(PARTICLES_JSON.read_text(encoding="utf-8-sig"))
    r_back = build_fx_back(data)
    r_front = build_fx_front(data)
    r_static = convert_static_layers_to_lossless_webp()

    print("=== SCHEME 1 + LOSSLESS WEBP BUILD COMPLETE ===")
    print("FX BACK :", json.dumps(r_back, ensure_ascii=False))
    print("FX FRONT:", json.dumps(r_front, ensure_ascii=False))
    for rs in r_static:
        print("STATIC  :", json.dumps(rs, ensure_ascii=False))

    # Total disk & VRAM summary
    total_tex_kb = 0.0
    total_vram_mb = 0.0
    tex_files = list(SKIN_DIR.rglob("*.webp")) + list(SKIN_DIR.rglob("*.png"))
    for p in sorted(tex_files):
        sz = p.stat().st_size / 1024.0
        with Image.open(p) as im:
            w, h = im.size
        vram = w * h * 4 / (1024 * 1024)
        total_tex_kb += sz
        total_vram_mb += vram
        print(f"  TEX {str(p.relative_to(SKIN_DIR)):45s} {w:4d}x{h:4d}  {sz:7.1f} KB  {vram:5.2f} MB VRAM")
    print(f"TOTAL TEXTURES: {len(tex_files)} files, {total_tex_kb/1024:.2f} MB disk, {total_vram_mb:.2f} MB VRAM")


if __name__ == "__main__":
    main()
