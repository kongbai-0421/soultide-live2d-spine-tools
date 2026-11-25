"""Render textured Live2D HitAreas visual audit previews (<= 700px, quality=80)."""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from audit_live2d_touch import LIVE2D_ROOT, get_drawable_render_orders, init_cubism_core

OUT_DIR = Path(r"E:\A灵魂潮汐\tools\_touch_audit_previews_l2d")

BOX_COLORS = {
    "头": (255, 59, 48),       # Red
    "胸": (255, 204, 0),      # Gold
    "左手": (0, 229, 255),    # Cyan
    "右手": (52, 199, 89),    # Green
    "臀部": (255, 45, 149),   # Magenta
    "躯干": (255, 149, 0),    # Orange
}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for fp in (
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ):
        if Path(fp).is_file():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_package_preview(
    core,
    pkg_dir: Path,
    out_path: Path,
    extra_boxes: list[dict[str, Any]] | None = None,
    max_dim: int = 700,
) -> Path:
    d0 = json.loads((pkg_dir / ".model3.json").read_text(encoding="utf-8"))
    fr = d0["FileReferences"]
    moc_bytes = (pkg_dir / fr["Moc"]).read_bytes()
    textures = fr.get("Textures") or []
    tex_rgba = [np.array(Image.open(pkg_dir / t).convert("RGBA")) for t in textures]

    moc_buf = ctypes.create_string_buffer(len(moc_bytes) + 64)
    moc_addr = (ctypes.addressof(moc_buf) + 63) & ~63
    ctypes.memmove(moc_addr, moc_bytes, len(moc_bytes))
    moc = core.csmReviveMocInPlace(moc_addr, len(moc_bytes))
    msize = core.csmGetSizeofModel(moc)
    mod_buf = ctypes.create_string_buffer(msize + 64)
    mod_addr = (ctypes.addressof(mod_buf) + 63) & ~63
    model = core.csmInitializeModelInPlace(moc, mod_addr, msize)
    core.csmUpdateModel(model)

    dcnt = core.csmGetDrawableCount(model)
    ids_ptr = core.csmGetDrawableIds(model)
    tidx_ptr = core.csmGetDrawableTextureIndices(model)
    vcnt_ptr = core.csmGetDrawableVertexCounts(model)
    vpos_ptr = core.csmGetDrawableVertexPositions(model)
    uvs_ptr = core.csmGetDrawableVertexUvs(model)
    icnt_ptr = core.csmGetDrawableIndexCounts(model)
    idxs_ptr = core.csmGetDrawableIndices(model)
    op_ptr = core.csmGetDrawableOpacities(model)
    ro_ptr = get_drawable_render_orders(core, model)

    draw_items = []
    vis_xs, vis_ys = [], []
    by_id: dict[str, dict[str, Any]] = {}

    for i in range(dcnt):
        did = ids_ptr[i].decode("utf-8", "ignore")
        vc = int(vcnt_ptr[i])
        ic = int(icnt_ptr[i])
        ti = int(tidx_ptr[i])
        op = float(op_ptr[i])
        ro = int(ro_ptr[i])

        if vc <= 0:
            continue
        pos = np.ctypeslib.as_array(vpos_ptr[i], shape=(vc, 2)).copy()
        uv = np.ctypeslib.as_array(uvs_ptr[i], shape=(vc, 2)).copy()
        x0, y0 = float(pos[:, 0].min()), float(pos[:, 1].min())
        x1, y1 = float(pos[:, 0].max()), float(pos[:, 1].max())
        by_id[did] = {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "w": x1 - x0, "h": y1 - y0, "op": op}

        if ic < 3 or ti < 0 or ti >= len(tex_rgba) or op <= 0.01:
            continue
        # Ignore extreme off-canvas stray drawables (e.g. H_houqun2 at 1100 in 欧若拉/童话心绘)
        if abs(x0) > 3.0 or abs(x1) > 3.0 or abs(y0) > 3.0 or abs(y1) > 3.0:
            continue

        idx = np.ctypeslib.as_array(idxs_ptr[i], shape=(ic // 3, 3)).copy()
        tex = tex_rgba[ti]
        th, tw = tex.shape[:2]
        c_uv = uv[idx].mean(axis=1)
        ux = np.clip((c_uv[:, 0] * tw).astype(int), 0, tw - 1)
        uy = np.clip(((1.0 - c_uv[:, 1]) * th).astype(int), 0, th - 1)
        tri_alpha = tex[uy, ux, 3]
        keep = tri_alpha > 4
        if not np.any(keep):
            continue

        kept_idx = idx[keep]
        used_v = np.unique(kept_idx)
        vis_xs.extend([float(pos[used_v, 0].min()), float(pos[used_v, 0].max())])
        vis_ys.extend([float(pos[used_v, 1].min()), float(pos[used_v, 1].max())])
        draw_items.append((ro, i, did, op, ti, pos, uv, kept_idx))

    hit_areas = d0.get("HitAreas") or []
    for ha in hit_areas:
        b = by_id.get(ha["Id"])
        if b and abs(b["x0"]) <= 3.0 and abs(b["x1"]) <= 3.0 and abs(b["y0"]) <= 3.0 and abs(b["y1"]) <= 3.0:
            vis_xs.extend([b["x0"], b["x1"]])
            vis_ys.extend([b["y0"], b["y1"]])

    if not vis_xs:
        vis_xs, vis_ys = [-0.6, 0.6], [-0.8, 0.8]

    vx0, vx1 = min(vis_xs), max(vis_xs)
    vy0, vy1 = min(vis_ys), max(vis_ys)
    vw = max(0.2, vx1 - vx0)
    vh = max(0.2, vy1 - vy0)
    pad_x = vw * 0.14
    pad_y = vh * 0.10
    vx0 -= pad_x
    vx1 += pad_x
    vy0 -= pad_y
    vy1 += pad_y
    vw = vx1 - vx0
    vh = vy1 - vy0

    header_h = 44
    avail_h = max_dim - header_h
    if vw / vh > max_dim / avail_h:
        cw = max_dim
        ch_body = max(200, int(round(cw * vh / vw)))
    else:
        ch_body = avail_h
        cw = max(220, int(round(ch_body * vw / vh)))
        cw = max(cw, 440)  # enough width for labels
    ch = ch_body + header_h

    # Re-center horizontal bounds if cw was widened for labels
    world_w_for_cw = vh * (cw / ch_body)
    if world_w_for_cw > vw:
        cx_mid = (vx0 + vx1) / 2.0
        vx0 = cx_mid - world_w_for_cw / 2.0
        vx1 = cx_mid + world_w_for_cw / 2.0
        vw = world_w_for_cw

    def to_px(wx: float, wy: float) -> tuple[float, float]:
        px = (wx - vx0) / vw * cw
        py = header_h + (vy1 - wy) / vh * ch_body
        return px, py

    canvas = np.full((ch, cw, 3), (34, 38, 46), dtype=np.uint8)
    # Subtle grid
    canvas[::32, :, :] = np.clip(canvas[::32, :, :].astype(np.int16) + 8, 0, 255).astype(np.uint8)
    canvas[:, ::32, :] = np.clip(canvas[:, ::32, :].astype(np.int16) + 8, 0, 255).astype(np.uint8)

    draw_items.sort(key=lambda x: (x[0], x[1]))

    for ro, i, did, op, ti, pos, uv, kept_idx in draw_items:
        tex = tex_rgba[ti]
        th, tw = tex.shape[:2]
        # Convert all vertices of this drawable to canvas px
        sx = (pos[:, 0] - vx0) / vw * cw
        sy = header_h + (vy1 - pos[:, 1]) / vh * ch_body
        ux = uv[:, 0] * tw
        uy = (1.0 - uv[:, 1]) * th

        for tri in kept_idx:
            src = np.float32([[ux[tri[0]], uy[tri[0]]], [ux[tri[1]], uy[tri[1]]], [ux[tri[2]], uy[tri[2]]]])
            dst = np.float32([[sx[tri[0]], sy[tri[0]]], [sx[tri[1]], sy[tri[1]]], [sx[tri[2]], sy[tri[2]]]])

            # Bounding rects
            rx0 = max(0, int(np.floor(dst[:, 0].min())))
            ry0 = max(header_h, int(np.floor(dst[:, 1].min())))
            rx1 = min(cw, int(np.ceil(dst[:, 0].max())) + 1)
            ry1 = min(ch, int(np.ceil(dst[:, 1].max())) + 1)
            if rx1 <= rx0 or ry1 <= ry0:
                continue

            sx0 = max(0, int(np.floor(src[:, 0].min())) - 1)
            sy0 = max(0, int(np.floor(src[:, 1].min())) - 1)
            sx1 = min(tw, int(np.ceil(src[:, 0].max())) + 2)
            sy1 = min(th, int(np.ceil(src[:, 1].max())) + 2)
            if sx1 <= sx0 or sy1 <= sy0:
                continue

            src_crop = tex[sy0:sy1, sx0:sx1]
            src_local = src - np.float32([sx0, sy0])
            dst_local = dst - np.float32([rx0, ry0])

            # Check degenerate triangle
            area2 = abs(
                (src_local[1, 0] - src_local[0, 0]) * (src_local[2, 1] - src_local[0, 1])
                - (src_local[2, 0] - src_local[0, 0]) * (src_local[1, 1] - src_local[0, 1])
            )
            if area2 < 1e-4:
                continue
            darea2 = abs(
                (dst_local[1, 0] - dst_local[0, 0]) * (dst_local[2, 1] - dst_local[0, 1])
                - (dst_local[2, 0] - dst_local[0, 0]) * (dst_local[1, 1] - dst_local[0, 1])
            )
            if darea2 < 0.25:
                continue

            M = cv2.getAffineTransform(src_local, dst_local)
            dw, dh = rx1 - rx0, ry1 - ry0
            warped = cv2.warpAffine(
                src_crop, M, (dw, dh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT
            )
            mask = np.zeros((dh, dw), dtype=np.uint8)
            cv2.fillConvexPoly(mask, np.int32(np.round(dst_local)), 255)
            alpha = (warped[..., 3].astype(np.float32) / 255.0) * (mask.astype(np.float32) / 255.0) * op
            a3 = alpha[..., None]
            bg = canvas[ry0:ry1, rx0:rx1].astype(np.float32)
            fg = warped[..., :3].astype(np.float32)
            canvas[ry0:ry1, rx0:rx1] = np.clip(fg * a3 + bg * (1.0 - a3), 0, 255).astype(np.uint8)

    img = Image.fromarray(canvas, mode="RGB").convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    draw = ImageDraw.Draw(img)

    font_hdr = _load_font(15)
    font_lbl = _load_font(13)

    # Header bar
    draw.rectangle([0, 0, cw, header_h], fill=(20, 24, 30, 255))
    rel = f"{pkg_dir.parent.name}/{pkg_dir.name}"
    draw.text((8, 12), f"{rel}  (HitAreas={len(hit_areas)})", fill=(240, 245, 250, 255), font=font_hdr)

    # Draw HitAreas boxes
    label_y_used: list[tuple[int, int]] = []
    for idx_h, ha in enumerate(hit_areas):
        name = ha["Name"]
        hid = ha["Id"]
        col = BOX_COLORS.get(name, (200, 200, 255))
        b = by_id.get(hid)
        if not b:
            continue
        px0, py1 = to_px(b["x0"], b["y0"])
        px1, py0 = to_px(b["x1"], b["y1"])
        px0, px1 = min(px0, px1), max(px0, px1)
        py0, py1 = min(py0, py1), max(py0, py1)
        odraw.rectangle([px0, py0, px1, py1], fill=(col[0], col[1], col[2], 45), outline=(col[0], col[1], col[2], 235), width=2)

        lbl = f"{name}:{hid}"
        lx = int(max(4, min(cw - 170, px0)))
        ly = int(max(header_h + 2, py0 - 16))
        for prev_x, prev_y in label_y_used:
            if abs(lx - prev_x) < 120 and abs(ly - prev_y) < 16:
                ly = prev_y + 16
        label_y_used.append((lx, ly))
        odraw.rectangle([lx - 2, ly - 1, lx + len(lbl) * 8 + 14, ly + 15], fill=(15, 18, 24, 200))
        odraw.text((lx + 1, ly), lbl, fill=(col[0], col[1], col[2], 255), font=font_lbl)

    if extra_boxes:
        for eb in extra_boxes:
            px0, py1 = to_px(eb["x0"], eb["y0"])
            px1, py0 = to_px(eb["x1"], eb["y1"])
            odraw.rectangle([px0, py0, px1, py1], outline=(255, 255, 255, 220), width=1)
            odraw.text((px0 + 2, py0 + 2), eb["label"], fill=(255, 255, 255, 255), font=font_lbl)

    img = Image.alpha_composite(img, overlay).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=80)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rels", nargs="*", help="Specific rel paths like 伊汐尔/原皮_变身")
    parser.add_argument("--all-flagged", action="store_true", help="Render all flagged from live2d_touch_audit_raw.json")
    args = parser.parse_args()

    core = init_cubism_core()
    rels: list[str] = list(args.rels or [])
    if args.all_flagged:
        raw = json.loads(Path(r"E:\A灵魂潮汐\tools\live2d_touch_audit_raw.json").read_text("utf-8"))
        rels.extend(raw["flagged_rels"])
    # Dedupe preserving order
    seen = set()
    uniq = []
    for r in rels:
        if r not in seen:
            seen.add(r)
            uniq.append(r)

    for rel in uniq:
        pkg_dir = LIVE2D_ROOT / rel
        fname = rel.replace("/", "__") + ".jpg"
        out = render_package_preview(core, pkg_dir, OUT_DIR / fname)
        print("Rendered:", out)


if __name__ == "__main__":
    main()
