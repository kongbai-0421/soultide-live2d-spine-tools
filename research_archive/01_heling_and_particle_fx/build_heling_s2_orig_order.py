"""Rebuild 和铃/古锦新韵 bg_static (-3) and fx_heling_s2_back (-1) with 100% ORIGINAL Unity game layer order:
  -3 (bg_static):         Layer_01 sky (04) -> scrolling clouds (yun, 90.9s) -> LED screen backdrop (03)
  -2 (bj_01):             Layer_02 Child 0: 3D Panda & Bamboo Spine (SoulDress_HeLing_BG_01)
  -1 (fx_heling_s2_back): Layer_02 Child 1: Buildings/Overpass/Pavilion (01) -> Bamboo leaves FX (lizi x4, 15.15s)
   0 (MAIN):              Point_Root: Heling + Scooter
  +3 (fx_heling_s2_front): Layer_04: Sunbeams (guang), Streaks (guangxian), Rainbow (caihong), Petals (huaban), Leaves (yezi)

All textures are native lossless PMA WebP (lossless=True, exact=True, verified 0-diff bit-for-bit!).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

sys.path.insert(0, r".\_scratch")
import build_heling_s2_scheme1 as s1

ORIG_LAYERS_DIR = Path(r".\_scratch\heling_orig_layers")
SKIN_DIR = s1.SKIN_DIR
TEX_DIR = s1.TEX_DIR
PARTICLES_JSON = s1.PARTICLES_JSON

BG_W = 4250.0
BG_H = 2833.3333
BASE_SCALE = 0.077
UI_TO_SPINE = 2.5  # 4250 / 1700 exact!
CAM_UI_X = 3.0
CAM_UI_Y = -51.0


def pack_exact_atlas(items: list[dict[str, Any]], max_w: int = 2048, pad: int = 4) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Shelf packer supporting up to 2048x2048 compact power-of-two / NPOT sizes."""
    ordered = sorted(items, key=lambda it: (-it["im"].height, -it["im"].width))
    candidates = [
        (512, 512), (1024, 512), (1024, 1024),
        (2048, 1024), (2048, 1536), (2048, 2048),
    ]
    for cand_w, cand_h in candidates:
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
            meta = []
            for it, px, py in placements:
                atlas.paste(it["im"], (px, py))
                w, h = it["im"].size
                meta.append({
                    "name": it["name"],
                    "x": px, "y": py, "w": w, "h": h,
                    "orig_w": it["orig_w"], "orig_h": it["orig_h"],
                    "off_x": it["off_x"], "off_y": it["off_y"],
                })
            return atlas, meta
    raise RuntimeError("Could not pack atlas within 2048x2048")


def build_bg_static_layer01(data: dict[str, Any]) -> dict[str, Any]:
    """Order -3 (bg_static): Layer_01 Sky (04) -> Clouds (yun) -> LED Screen Backdrop (03)."""
    sub_dir = SKIN_DIR / "submodels" / "bg_static"
    cam_x, cam_y = data["cam_x"], data["cam_y"]
    scale_u2s = BG_W / float(data["canvas_w"])

    clip = next(c for c in data["clips"] if c["clip"] == "idle_back")
    uvq = clip["uv_quads"][0]

    # Native original sprites converted to exact PMA
    sky_im = s1.to_pma(Image.open(ORIG_LAYERS_DIR / "L1_Image_02__HeLing_S2_Background_04.png"))
    yun_im = s1.to_pma(Image.open(TEX_DIR / "FX_cf_yun14.png"))
    scr_im = s1.to_pma(Image.open(ORIG_LAYERS_DIR / "L1_Image__HeLing_S2_Background_03.png"))
    scr_cr, scr_ow, scr_oh, scr_ox, scr_oy = s1.trim_sprite(scr_im, alpha_thr=1)

    pack_items = [
        {"name": "bg_sky", "im": sky_im, "orig_w": sky_im.width, "orig_h": sky_im.height, "off_x": 0, "off_y": 0, "pad": 4},
        {"name": "yun", "im": yun_im, "orig_w": yun_im.width, "orig_h": yun_im.height, "off_x": 0, "off_y": 0, "pad": 4},
        {"name": "bg_screen", "im": scr_cr, "orig_w": scr_ow, "orig_h": scr_oh, "off_x": scr_ox, "off_y": scr_oy, "pad": 4},
    ]
    atlas_im, regions = pack_exact_atlas(pack_items, max_w=2048, pad=4)

    for old_f in list(sub_dir.glob("*.png")) + list(sub_dir.glob("*.webp")):
        old_f.unlink()

    webp_name = "bg_4301_heling_s2.webp"
    s1.save_lossless_webp(atlas_im, sub_dir / webp_name)
    s1.write_atlas_txt(sub_dir / "bg_static.atlas.txt", webp_name, atlas_im.width, atlas_im.height, regions)

    # Exact Spine coordinates
    T_yun = round(1.0 / abs(uvq["uv_u"]), 4)  # 90.9091s
    yun_cx = round((uvq["x"] - cam_x) * scale_u2s, 2)
    yun_cy = round((uvq["y"] - cam_y) * scale_u2s, 2)
    yun_w = round(uvq["w"] * scale_u2s, 2)
    yun_h = round(uvq["h"] * scale_u2s, 2)
    yun_col = s1.rgba_hex(uvq["r"], uvq["g"], uvq["b"], uvq["a"])
    scroll_dir = -1.0 if uvq["uv_u"] > 0 else 1.0

    # LED screen backdrop: Unity UI world (-285.0, 160.0), size (778, 470)
    scr_cx = round((-285.0 - CAM_UI_X) * UI_TO_SPINE, 2)  # -720.0
    scr_cy = round((160.0 - CAM_UI_Y) * UI_TO_SPINE, 2)   # +527.5
    scr_w = round(778.0 * UI_TO_SPINE, 2)                 # 1945.0
    scr_h = round(470.0 * UI_TO_SPINE, 2)                 # 1175.0

    bones = [
        {"name": "root"},
        {"name": "bg_root", "parent": "root", "x": 0.0, "y": 0.0},
        {"name": "yun_1", "parent": "root", "x": yun_cx, "y": yun_cy},
        {"name": "yun_2", "parent": "root", "x": round(yun_cx - scroll_dir * yun_w, 2), "y": yun_cy},
    ]
    slots = [
        {"name": "bg_sky_slot", "bone": "bg_root", "attachment": "bg_sky"},
        {"name": "yun_clip", "bone": "root", "attachment": "yun_clip"},
        {"name": "yun_1", "bone": "yun_1", "color": yun_col, "attachment": "yun"},
        {"name": "yun_2", "bone": "yun_2", "color": yun_col, "attachment": "yun"},
        {"name": "bg_screen_slot", "bone": "bg_root", "attachment": "bg_screen"},
    ]
    skin_att = {
        "bg_sky_slot": {
            "bg_sky": {"x": 0.0, "y": 0.0, "width": round(BG_W, 2), "height": round(BG_H, 2)},
        },
        "yun_clip": {
            "yun_clip": {
                "type": "clipping",
                "end": "yun_2",
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
        "bg_screen_slot": {
            "bg_screen": {"x": scr_cx, "y": scr_cy, "width": scr_w, "height": scr_h},
        },
    }
    skel = {
        "skeleton": {
            "hash": "bg_4301_heling_s2",
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
                "bones": {
                    "yun_1": {
                        "translate": [
                            {"time": 0.0, "x": 0.0, "y": 0.0},
                            {"time": T_yun, "x": round(scroll_dir * yun_w, 2), "y": 0.0},
                        ]
                    },
                    "yun_2": {
                        "translate": [
                            {"time": 0.0, "x": 0.0, "y": 0.0},
                            {"time": T_yun, "x": round(scroll_dir * yun_w, 2), "y": 0.0},
                        ]
                    },
                }
            }
        },
    }
    (sub_dir / "bg_static.skel.json").write_text(
        json.dumps(skel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    cfg = json.loads((sub_dir / ".config.json").read_text(encoding="utf-8"))
    cfg["options"]["scale_factor"] = BASE_SCALE
    cfg["options"]["position_x"] = 0.0
    cfg["options"]["position_y"] = 0.0
    cfg["options"]["tex_type"] = 1
    cfg["options"]["shader_type"] = 0
    cfg["skeleton"] = "bg_static.skel.json"
    cfg["atlases"] = [{
        "atlas": "bg_static.atlas.txt",
        "tex_names": ["bg_4301_heling_s2"],
        "textures": [webp_name],
    }]
    cfg["motions"] = {
        "idle": [{"name": "idle", "file": "idle", "file_loop": True, "fade_in": 10, "fade_out": 10}]
    }
    (sub_dir / ".config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "layer": "bg_static (Layer_01: sky + yun + screen)",
        "atlas_size": atlas_im.size,
        "webp_kb": round((sub_dir / webp_name).stat().st_size / 1024, 1),
        "vram_mb": round(atlas_im.width * atlas_im.height * 4 / (1024 * 1024), 2),
        "duration": T_yun,
    }


def build_fx_back_layer02(data: dict[str, Any]) -> dict[str, Any]:
    """Order -1 (fx_heling_s2_back): Layer_02 Buildings/Overpass/Pavilion (01) -> Bamboo leaves (lizi x4)."""
    sub_dir = SKIN_DIR / "submodels" / "fx_heling_s2_back"
    cam_x, cam_y = data["cam_x"], data["cam_y"]
    scale_u2s = BG_W / float(data["canvas_w"])

    clip = next(c for c in data["clips"] if c["clip"] == "idle_back")

    # Buildings sprite (1700x1131 native, sky & billboard cutout transparent!) + 6 lizi bamboo leaf tiles
    bld_im = s1.to_pma(Image.open(ORIG_LAYERS_DIR / "L2_Image__HeLing_S2_Background_01.png"))
    lizi_sheet = s1.to_pma(Image.open(TEX_DIR / "FX_cf_lizi11_b.png"))
    lw, lh = lizi_sheet.size
    tx_n, ty_n = 3, 2
    cw, ch = lw // tx_n, lh // ty_n

    pack_items = [
        {"name": "bg_buildings", "im": bld_im, "orig_w": bld_im.width, "orig_h": bld_im.height, "off_x": 0, "off_y": 0, "pad": 4},
    ]
    for ti in range(tx_n * ty_n):
        tx, ty = ti % tx_n, ti // tx_n
        cell = lizi_sheet.crop((tx * cw, ty * ch, (tx + 1) * cw, (ty + 1) * ch))
        cr, ow, oh, ox, oy = s1.trim_sprite(cell, alpha_thr=1)
        pack_items.append({
            "name": f"lizi_t{ti}", "im": cr, "orig_w": ow, "orig_h": oh, "off_x": ox, "off_y": oy, "pad": 2
        })

    atlas_im, regions = pack_exact_atlas(pack_items, max_w=2048, pad=4)

    for old_f in list(sub_dir.glob("*.png")) + list(sub_dir.glob("*.webp")) + list(sub_dir.glob("*.skel.json")):
        old_f.unlink()

    webp_name = "fx_heling_s2_back.webp"
    s1.save_lossless_webp(atlas_im, sub_dir / webp_name)
    s1.write_atlas_txt(sub_dir / "fx_heling_s2_back.atlas.txt", webp_name, atlas_im.width, atlas_im.height, regions)

    # Buildings exact Unity UI position: world=(4.0, -52.0), size=(1700, 1131)
    bld_cx = round((4.0 - CAM_UI_X) * UI_TO_SPINE, 2)    # +2.5
    bld_cy = round((-52.0 - CAM_UI_Y) * UI_TO_SPINE, 2)  # -2.5
    bld_w = round(1700.0 * UI_TO_SPINE, 2)               # 4250.0
    bld_h = round(1131.0 * UI_TO_SPINE, 2)               # 2827.5

    # Pool lizi particles over clean 15.0s seamless cycle (no need for 90.9s repeat!)
    T_lizi = 15.0
    lizi_tracks = [tr for tr in clip["tracks"] if tr["node"] in (1, 2, 3, 4)]
    lizi_bones = s1.build_periodic_pool(
        lizi_tracks, t_win_start=1.0, period=T_lizi,
        cam_x=cam_x, cam_y=cam_y, scale_u2s=scale_u2s,
        region_fn=lambda node_idx, tile: f"lizi_t{tile % 6}",
    )

    bones = [{"name": "root"}]
    slots = [
        {"name": "fx_clip", "bone": "root", "attachment": "fx_clip"},
        {"name": "bg_buildings_slot", "bone": "root", "attachment": "bg_buildings"},
    ]
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
        },
        "bg_buildings_slot": {
            "bg_buildings": {"x": bld_cx, "y": bld_cy, "width": bld_w, "height": bld_h},
        },
    }
    bone_anims: dict[str, Any] = {
        "root": {
            "translate": [
                {"time": 0.0, "x": 0.0, "y": 0.0},
                {"time": T_lizi, "x": 0.0, "y": 0.0},
            ]
        }
    }
    slot_anims: dict[str, Any] = {}

    for bi, bitems in enumerate(lizi_bones):
        bname = f"lizi_{bi:02d}"
        bones.append({"name": bname, "parent": "root"})
        slots.append({"name": bname, "bone": bname, "color": "ffffff00"})
        skin_att[bname] = {f"lizi_t{t}": {"width": 100.0, "height": 100.0} for t in range(6)}
        ba, sa = s1.emit_bone_timelines(bitems, period=T_lizi, repeat_count=1)
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

    cfg = json.loads((sub_dir / ".config.json").read_text(encoding="utf-8"))
    cfg["options"]["scale_factor"] = BASE_SCALE
    cfg["options"]["position_x"] = 0.0
    cfg["options"]["position_y"] = 0.0
    cfg["options"]["tex_type"] = 1
    cfg["options"]["shader_type"] = 0
    cfg["skeleton"] = "fx_heling_s2_back.json"
    cfg["atlases"] = [{
        "atlas": "fx_heling_s2_back.atlas.txt",
        "tex_names": ["fx_heling_s2_back"],
        "textures": [webp_name],
    }]
    (sub_dir / ".config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "layer": "fx_heling_s2_back (Layer_02: buildings + lizi)",
        "atlas_size": atlas_im.size,
        "webp_kb": round((sub_dir / webp_name).stat().st_size / 1024, 1),
        "vram_mb": round(atlas_im.width * atlas_im.height * 4 / (1024 * 1024), 2),
        "bones": len(bones),
        "skel_kb": round((sub_dir / "fx_heling_s2_back.json").stat().st_size / 1024, 1),
        "duration": T_lizi,
    }


def main() -> None:
    data = json.loads(PARTICLES_JSON.read_text(encoding="utf-8-sig"))
    r1 = build_bg_static_layer01(data)
    r2 = build_fx_back_layer02(data)
    print("=== ORIGINAL GAME LAYER ORDER BUILD COMPLETE ===")
    print("ORDER -3:", json.dumps(r1, ensure_ascii=False))
    print("ORDER -1:", json.dumps(r2, ensure_ascii=False))

    total_kb = 0.0
    total_vram = 0.0
    for p in sorted(SKIN_DIR.rglob("*.webp")):
        sz = p.stat().st_size / 1024.0
        with Image.open(p) as im:
            w, h = im.size
        v = w * h * 4 / (1024 * 1024)
        total_kb += sz
        total_vram += v
        print(f"  {str(p.relative_to(SKIN_DIR)):48s} {w:4d}x{h:4d} {sz:7.1f} KB  {v:5.2f} MB VRAM")
    print(f"TOTAL: {total_kb/1024:.2f} MB disk, {total_vram:.2f} MB VRAM")


if __name__ == "__main__":
    main()
