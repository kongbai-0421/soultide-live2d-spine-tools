"""Reusable Frame-Sequence PNG -> Spine 3.8 Submodel Packer for Live2DViewerEX.

Packs one or more animation sequences (each with optional `normal` and `add` PNG frame folders)
into a Tight-Bounds-cropped Spine 3.8 texture atlas + skeleton JSON + Live2DViewerEX `.config.json`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import numpy as np
from PIL import Image


@dataclass
class AnimSequenceSpec:
    """Definition of one animation inside a Spine FX submodel."""

    name: str
    fps: float = 15.0
    loop: bool = False
    is_overlay: bool = False
    normal_frames: list[Path] | None = None
    add_frames: list[Path] | None = None
    motion_group: str | None = None


@dataclass
class _PackedRegion:
    region_name: str
    page_idx: int
    x: int
    y: int
    w: int
    h: int
    orig_w: int
    orig_h: int
    trim_x: int
    trim_y: int  # PIL top-down y


def _sha256_rgba(im: Image.Image) -> str:
    return hashlib.sha256(im.tobytes()).hexdigest()


def _tight_crop_frame(path: Path) -> tuple[Image.Image | None, int, int, int, int]:
    """Crop a PNG to its non-transparent bounding box. Returns (cropped, orig_w, orig_h, left, top)."""
    with Image.open(path) as src:
        im = src.convert("RGBA")
    orig_w, orig_h = im.size
    bbox = im.getbbox()
    if bbox is None:
        return None, orig_w, orig_h, 0, 0
    l, t, r, b = bbox
    return im.crop((l, t, r, b)), orig_w, orig_h, l, t


def _process_frame_task(
    task: tuple[str, str, int, Path],
) -> tuple[str, str, int, bytes | None, int, int, int, int, int, int, str]:
    """Worker helper for parallel frame cropping, SHA-256 hashing, and compact PNG byte buffering."""
    seq_name, ch_name, idx, path = task
    cropped, ow, oh, tl, tt = _tight_crop_frame(path)
    if cropped is None:
        return seq_name, ch_name, idx, None, 0, 0, ow, oh, tl, tt, ""
    digest = _sha256_rgba(cropped)
    cw, ch = cropped.size
    buf = io.BytesIO()
    cropped.save(buf, format="PNG", compress_level=1)
    cropped.close()
    return seq_name, ch_name, idx, buf.getvalue(), cw, ch, ow, oh, tl, tt, digest


def _pack_skyline(
    unique_items: list[tuple[str, bytes, int, int, int, int, int, int]],
    max_size: int = 4096,
    padding: int = 2,
) -> tuple[list[dict], dict[str, _PackedRegion]]:
    """Plan compact shelf packing of cropped sprites into pages without pre-allocating RGBA canvases."""
    ordered = sorted(unique_items, key=lambda x: (-x[3], -x[2], x[0]))
    pages: list[dict] = []
    regions: dict[str, _PackedRegion] = {}

    def new_page():
        return {"w": max_size, "h": max_size, "x": padding, "y": padding, "row_h": 0, "items": []}

    cur = new_page()
    for name, png_bytes, w, h, orig_w, orig_h, tl, tt in ordered:
        if w + 2 * padding > max_size or h + 2 * padding > max_size:
            raise ValueError(f"Frame {name} ({w}x{h}) exceeds max atlas page {max_size}")
        if cur["x"] + w + padding > cur["w"]:
            cur["x"] = padding
            cur["y"] += cur["row_h"] + padding
            cur["row_h"] = 0
        if cur["y"] + h + padding > cur["h"]:
            pages.append(cur)
            cur = new_page()
        px, py = cur["x"], cur["y"]
        cur["x"] += w + padding
        cur["row_h"] = max(cur["row_h"], h)
        cur["items"].append((name, png_bytes, w, h, px, py))
        regions[name] = _PackedRegion(
            region_name=name,
            page_idx=len(pages),
            x=px,
            y=py,
            w=w,
            h=h,
            orig_w=orig_w,
            orig_h=orig_h,
            trim_x=tl,
            trim_y=tt,
        )
    if cur["items"] or not pages:
        pages.append(cur)

    page_layouts: list[dict] = []
    for pg in pages:
        if not pg["items"]:
            page_layouts.append({"pw": 64, "ph": 64, "items": []})
            continue
        max_x = max(x + w + padding for _, _, w, _, x, _ in pg["items"])
        max_y = max(y + h + padding for _, _, _, h, _, y in pg["items"])
        pw = 64
        while pw < max_x and pw < max_size:
            pw *= 2
        ph = 64
        while ph < max_y and ph < max_size:
            ph *= 2
        page_layouts.append({"pw": min(pw, max_size), "ph": min(ph, max_size), "items": pg["items"]})

    return page_layouts, regions


def _build_atlas_text(
    page_metas: list[tuple[str, int, int]],
    regions: Iterable[_PackedRegion],
) -> str:
    by_page: dict[int, list[_PackedRegion]] = {}
    for r in regions:
        by_page.setdefault(r.page_idx, []).append(r)

    lines: list[str] = []
    for idx, (fname, pw, ph) in enumerate(page_metas):
        lines.append("")
        lines.append(fname)
        lines.append(f"size: {pw},{ph}")
        lines.append("format: RGBA8888")
        lines.append("filter: Linear,Linear")
        lines.append("repeat: none")
        for r in sorted(by_page.get(idx, []), key=lambda x: x.region_name):
            # Spine atlas `offset` is from bottom-left of original uncropped image!
            spine_offset_y = r.orig_h - r.trim_y - r.h
            lines.append(r.region_name)
            lines.append("  rotate: false")
            lines.append(f"  xy: {r.x}, {r.y}")
            lines.append(f"  size: {r.w}, {r.h}")
            lines.append(f"  orig: {r.orig_w}, {r.orig_h}")
            lines.append(f"  offset: {r.trim_x}, {spine_offset_y}")
            lines.append("  index: -1")
    return "\n".join(lines) + "\n"


def _save_exact_webp(im: Image.Image, out_path: Path) -> None:
    rgba = im.convert("RGBA")
    rgba.save(out_path, "WEBP", lossless=True, exact=True, quality=100, method=4)
    src_arr = np.asarray(rgba)
    with Image.open(out_path) as dec:
        dec_arr = np.asarray(dec.convert("RGBA"))
    if src_arr.shape != dec_arr.shape or not np.array_equal(src_arr, dec_arr):
        out_path.unlink(missing_ok=True)
        raise AssertionError(f"Bit-exact WebP check failed: {out_path}")


def pack_fx_submodel(
    output_dir: Path,
    model_name: str,
    model_id: str,
    sequences: list[AnimSequenceSpec],
    root_x: float = 0.0,
    root_y: float = 0.0,
    root_scale_x: float = 1.0,
    root_scale_y: float = 1.0,
    root_rotation: float = 0.0,
    scale_factor: float = 1.0,
    max_atlas_size: int = 4096,
    padding: int = 2,
    frame_workers: int = 1,
    use_webp: bool = True,
    clip_rect: tuple[float, float, float, float] | None = None,
) -> dict:
    """Pack frame sequences into a ready-to-load Spine 3.8 Submodel folder."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Scan & deduplicate frames using compact PNG byte buffers (parallel crop/hash when frame_workers > 1)
    hash_to_region_name: dict[str, str] = {}
    unique_items: list[tuple[str, bytes, int, int, int, int, int, int]] = []
    # Map (seq_name, channel, frame_idx) -> region_name | None (None = empty frame)
    frame_lookup: dict[tuple[str, str, int], str | None] = {}
    canvas_size: tuple[int, int] = (0, 0)
    counter = 0

    frame_tasks = [
        (seq.name, ch_name, idx, p)
        for seq in sequences
        for ch_name, paths in (("normal", seq.normal_frames or []), ("add", seq.add_frames or []))
        for idx, p in enumerate(paths)
    ]
    if frame_workers > 1 and len(frame_tasks) > 8:
        with ThreadPoolExecutor(max_workers=min(frame_workers, len(frame_tasks))) as ex:
            processed = list(ex.map(_process_frame_task, frame_tasks))
    else:
        processed = [_process_frame_task(t) for t in frame_tasks]

    for seq_name, ch_name, idx, png_bytes, cw_i, ch_i, ow, oh, tl, tt, h in processed:
        if canvas_size == (0, 0):
            canvas_size = (ow, oh)
        if png_bytes is None:
            frame_lookup[(seq_name, ch_name, idx)] = None
            continue
        dedup_key = f"{h}:{ow}x{oh}:{tl},{tt}"
        if dedup_key not in hash_to_region_name:
            counter += 1
            rname = f"fx_{counter:04d}"
            hash_to_region_name[dedup_key] = rname
            unique_items.append((rname, png_bytes, cw_i, ch_i, ow, oh, tl, tt))
        frame_lookup[(seq_name, ch_name, idx)] = hash_to_region_name[dedup_key]
    processed.clear()

    if not unique_items:
        empty = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        ebuf = io.BytesIO()
        empty.save(ebuf, format="PNG")
        empty.close()
        unique_items.append(("fx_empty", ebuf.getvalue(), 4, 4, canvas_size[0] or 64, canvas_size[1] or 64, 0, 0))

    # 2. Plan atlas pages, then stream-render & save one page at a time to keep RAM tiny
    page_layouts, regions = _pack_skyline(unique_items, max_size=max_atlas_size, padding=padding)
    unique_items.clear()

    num_pages = len(page_layouts)
    ext = "webp" if use_webp else "png"
    page_filenames = [
        f"{model_name}.{ext}" if num_pages == 1 else f"{model_name}_{i + 1}.{ext}"
        for i in range(num_pages)
    ]
    tex_names = [Path(fn).stem for fn in page_filenames]
    for old_tex in list(output_dir.glob(f"{model_name}*.png")) + list(output_dir.glob(f"{model_name}*.webp")):
        if old_tex.stem == model_name or re.match(rf"^{re.escape(model_name)}_\d+$", old_tex.stem):
            old_tex.unlink()

    page_metas: list[tuple[str, int, int]] = []
    for fn, pg in zip(page_filenames, page_layouts):
        pw, ph = pg["pw"], pg["ph"]
        canvas = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        for _, png_bytes, _, _, px, py in pg["items"]:
            with Image.open(io.BytesIO(png_bytes)) as sprite_im:
                canvas.paste(sprite_im, (px, py))
        if use_webp:
            _save_exact_webp(canvas, output_dir / fn)
        else:
            canvas.save(output_dir / fn, "PNG")
        canvas.close()
        pg["items"].clear()
        page_metas.append((fn, pw, ph))
    page_layouts.clear()

    atlas_text = _build_atlas_text(page_metas, regions.values())
    atlas_file = f"{model_name}.atlas.txt"
    (output_dir / atlas_file).write_text(atlas_text, encoding="utf-8")

    # 3. Build Spine 3.8 JSON with Normal + Additive slots (base ambient + overlay trigger slots)
    cw, ch = canvas_size if canvas_size != (0, 0) else (1024, 1024)
    has_base_norm = any(seq.normal_frames and not seq.is_overlay for seq in sequences)
    has_base_add = any(seq.add_frames and not seq.is_overlay for seq in sequences)
    has_ov_norm = any(seq.normal_frames and seq.is_overlay for seq in sequences)
    has_ov_add = any(seq.add_frames and seq.is_overlay for seq in sequences)

    slots: list[dict] = []
    skin_attachments: dict[str, dict[str, dict]] = {}
    if clip_rect is not None:
        cx0, cy0, cw_clip, ch_clip = clip_rect
        slots.append({"name": "fx_clip", "bone": "root", "attachment": "fx_clip"})
        skin_attachments["fx_clip"] = {
            "fx_clip": {
                "type": "clipping",
                "end": "",
                "vertexCount": 4,
                "vertices": [
                    round(cx0, 2), round(cy0, 2),
                    round(cx0 + cw_clip, 2), round(cy0, 2),
                    round(cx0 + cw_clip, 2), round(cy0 + ch_clip, 2),
                    round(cx0, 2), round(cy0 + ch_clip, 2),
                ],
            }
        }

    def register_slot(slot_name: str, blend: str, is_overlay_slot: bool):
        slot_def: dict = {"name": slot_name, "bone": "fx_root", "attachment": None}
        if blend == "additive":
            slot_def["blend"] = "additive"
        slots.append(slot_def)
        att_map: dict[str, dict] = {}
        # Populate attachments used by sequences mapped to this slot
        for seq in sequences:
            if bool(seq.is_overlay) != is_overlay_slot:
                continue
            ch_key = "add" if blend == "additive" else "normal"
            paths = seq.add_frames if blend == "additive" else seq.normal_frames
            if not paths:
                continue
            for idx in range(len(paths)):
                rname = frame_lookup[(seq.name, ch_key, idx)]
                if rname and rname not in att_map:
                    att_map[rname] = {"x": 0.0, "y": 0.0, "width": ow_of(rname), "height": oh_of(rname)}
        skin_attachments[slot_name] = att_map

    def ow_of(rname: str) -> int:
        return regions[rname].orig_w

    def oh_of(rname: str) -> int:
        return regions[rname].orig_h

    if has_base_norm:
        register_slot("fx_base_normal", "normal", False)
    if has_base_add:
        register_slot("fx_base_add", "additive", False)
    if has_ov_norm:
        register_slot("fx_overlay_normal", "normal", True)
    if has_ov_add:
        register_slot("fx_overlay_add", "additive", True)

    animations: dict[str, dict] = {}
    base_idle = next((s for s in sequences if not s.is_overlay and s.name == "idle"), None)
    for seq in sequences:
        slot_timelines: dict[str, dict] = {}
        dt = 1.0 / max(1.0, seq.fps)
        channels = (
            ("fx_overlay_normal" if seq.is_overlay else "fx_base_normal", "normal", seq.normal_frames),
            ("fx_overlay_add" if seq.is_overlay else "fx_base_add", "add", seq.add_frames),
        )
        max_frames = max(len(seq.normal_frames or []), len(seq.add_frames or []), 1)
        # Trim trailing empty frames on one-shot overlay clips while keeping leading delay intact
        if seq.is_overlay:
            last_non_empty = 0
            for idx in range(max_frames):
                n_has = seq.normal_frames and idx < len(seq.normal_frames) and frame_lookup[(seq.name, "normal", idx)] is not None
                a_has = seq.add_frames and idx < len(seq.add_frames) and frame_lookup[(seq.name, "add", idx)] is not None
                if n_has or a_has:
                    last_non_empty = idx
            max_frames = min(max_frames, last_non_empty + 2)

        for sname, ch_key, paths in channels:
            if not paths:
                if (sname == "fx_overlay_normal" and has_ov_norm) or (sname == "fx_overlay_add" and has_ov_add):
                    slot_timelines[sname] = {"attachment": [{"time": 0.0, "name": None}]}
                continue
            use_len = min(len(paths), max_frames) if seq.is_overlay else len(paths)
            keys: list[dict] = []
            last_val = "__INIT__"
            for idx in range(use_len):
                rname = frame_lookup[(seq.name, ch_key, idx)]
                if rname != last_val:
                    keys.append({"time": round(idx * dt, 4), "name": rname})
                    last_val = rname
            # Ensure exact duration end key (loop holds last frame cleanly or one-shot clears to null)
            end_t = round(use_len * dt, 4)
            keys.append({"time": end_t, "name": last_val if seq.loop else None})
            slot_timelines[sname] = {"attachment": keys}
        # Keep ambient base slots alive on Track 0 at true base_idle.fps while an overlay trigger plays
        if seq.is_overlay and base_idle is not None:
            idle_fps = max(1.0, base_idle.fps)
            for b_sname, ch_key, b_paths in (
                ("fx_base_normal", "normal", base_idle.normal_frames),
                ("fx_base_add", "add", base_idle.add_frames),
            ):
                if not b_paths:
                    continue
                b_keys: list[dict] = []
                last_val = "__INIT__"
                for idx in range(max_frames):
                    t_cur = idx * dt
                    b_idx = int(t_cur * idle_fps + 1e-4) % len(b_paths)
                    rname = frame_lookup[(base_idle.name, ch_key, b_idx)]
                    if rname != last_val:
                        b_keys.append({"time": round(t_cur, 4), "name": rname})
                        last_val = rname
                b_keys.append({"time": round(max_frames * dt, 4), "name": last_val})
                slot_timelines[b_sname] = {"attachment": b_keys}
        animations[seq.name] = {"slots": slot_timelines}

    if clip_rect is not None and len(slots) > 1:
        skin_attachments["fx_clip"]["fx_clip"]["end"] = slots[-1]["name"]
        sk_x, sk_y, sk_w, sk_h = clip_rect
    else:
        sk_x = -cw * root_scale_x / 2.0 + root_x
        sk_y = -ch * root_scale_y / 2.0 + root_y
        sk_w = cw * root_scale_x
        sk_h = ch * root_scale_y

    fx_root_bone: dict = {
        "name": "fx_root",
        "parent": "root",
        "x": round(root_x, 4),
        "y": round(root_y, 4),
        "scaleX": round(root_scale_x, 6),
        "scaleY": round(root_scale_y, 6),
    }
    if abs(root_rotation) > 0.01:
        fx_root_bone["rotation"] = round(root_rotation, 4)

    skel_json = {
        "skeleton": {
            "hash": f"fx_{model_id}",
            "spine": "3.8.79",
            "x": round(sk_x, 2),
            "y": round(sk_y, 2),
            "width": round(sk_w, 2),
            "height": round(sk_h, 2),
        },
        "bones": [
            {"name": "root"},
            fx_root_bone,
        ],
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin_attachments}],
        "animations": animations,
    }
    skel_file = f"{model_name}.json"
    (output_dir / skel_file).write_text(json.dumps(skel_json, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4. Build Live2DViewerEX Spine .config.json
    motions: dict[str, list[dict]] = {}
    for seq in sequences:
        grp = seq.motion_group or ("idle" if seq.name == "idle" else "main")
        motions.setdefault(grp, []).append(
            {
                "name": seq.name,
                "file": seq.name,
                "fade_in": 0,
                "fade_out": 0,
                **({"file_loop": True} if seq.loop else {}),
            }
        )

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
        "motions": motions,
        "options": {
            "id": model_id,
            "scale_factor": scale_factor,
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 1 if use_webp else 0,
            "shader_type": 0,
            "edge_padding": False,
        },
        "skeleton": skel_file,
        "atlases": [
            {
                "atlas": atlas_file,
                "tex_names": tex_names,
                "textures": page_filenames,
            }
        ],
    }
    cfg_path = output_dir / ".config.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "config_path": str(cfg_path),
        "skeleton": skel_file,
        "atlas": atlas_file,
        "pages": num_pages,
        "unique_regions": len(regions),
        "animations": list(animations.keys()),
    }
