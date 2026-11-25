"""Build a complete Live2DViewerEX Spine package for Aurora's '童话心绘' (Aurora_S4) skin.

Includes:
- Main Spine 3.8 binary (`SoulDress_Aurora_04.skel.json` + `.atlas.txt` + `.png`)
- All 13 official Spine voice lines (.wav) + exact Chinese subtitles (Marry + Normal states)
- BGM bonus (`BGM_SkinMusic05_Aurora_S4.wav`)
- Submodels:
  * -3: `bg_static` (composited `Image_01/02/03/05` aligned to Unity UI `Aurora_S4_Background`)
  * -2: `bj_03` (animated canopy Spine)
  * -1: `bj_02` (animated moon-vine & petals Spine)
  * +1: `bj_01` (animated foreground thorn-vine Spine)
  * +2: `fx_aurora_s4` (Frame-Sequence Spine 3.8 Submodel with Normal + Additive slots,
        synthesized from extracted game particle sprites for ambient loop, 9008135 chat, 9008136 touch1;
        drop-in replaceable by Unity 2021.3 captures via SoulTideFxRecorder.cs + spine_fx_submodel_packer.py)
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from PIL import Image, ImageChops, ImageEnhance

from soultide_common import CDN_ROOT, LuaTableRepo, extract_wav_bytes, load_ab, write_json
from spine_fx_submodel_packer import AnimSequenceSpec, pack_fx_submodel

OUT_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\欧若拉\童话心绘")
FX_SPRITE_CACHE = Path(r"E:\A灵魂潮汐\tools\_aurora_fx_sprites")
FX_SEQ_SRC = Path(r"E:\A灵魂潮汐\tools\_aurora_fx_sequences")

BATCH4_SPINE_AB = CDN_ROOT / "23_spine/dressspine/_batch4.ab"
BATCH4_BG_AB = CDN_ROOT / "05_images/image_resources/dress_bg/dressbackground/_batch4.ab"
CV_AURORA_AB = CDN_ROOT / "06_sounds/cv/_aurora.ab"
BGM_BATCH10_AB = CDN_ROOT / "06_sounds/bgm/dressspine/batch10.ab"

# Verified Unity UI geometry from Aurora_S4_Background.prefab (Point_Root=0.86, Spine_Scale=0.1158, Person=5.97)
AURORA_UI_ORIGIN_X = 33.8989
AURORA_UI_ORIGIN_Y = -493.0542
AURORA_UI_PER_SPINE = 0.59454  # 0.86 * 0.1158 * 5.97
BG_CANVAS_W = 1768
BG_CANVAS_H = 1176
BG_CENTER_UI_X = 0.0
BG_CENTER_UI_Y = 11.44


def ui_to_spine_rect(cx: float, cy: float, w_px: float, h_px: float) -> tuple[float, float, float, float]:
    """Convert Unity UI RectTransform center/size into parent Spine 3.8 local coordinates."""
    sx = (cx - AURORA_UI_ORIGIN_X) / AURORA_UI_PER_SPINE
    sy = (cy - AURORA_UI_ORIGIN_Y) / AURORA_UI_PER_SPINE
    return sx, sy, w_px / AURORA_UI_PER_SPINE, h_px / AURORA_UI_PER_SPINE


def _extract_spine_bundle_unit(container: dict, prefix: str, dest_dir: Path) -> dict[str, str]:
    """Extract .skel.bytes (saved as .skel.json matching EX convention), .atlas.txt, and .png."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    skel_name = ""
    atlas_name = ""
    tex_names: list[str] = []
    tex_files: list[str] = []
    img_map: dict[str, Image.Image] = {}

    # Read atlas first so PNG filename matches exact case inside atlas header
    atlas_pages: list[str] = []
    for cpath, ptr in sorted(container.items()):
        low = cpath.lower()
        if prefix not in low:
            continue
        if low.endswith(".atlas.txt"):
            txt = ptr.read().m_Script
            # Preserve canonical PascalCase from first non-empty line
            first_line = next((ln.strip() for ln in txt.splitlines() if ln.strip()), "")
            canon_stem = Path(first_line).stem if first_line else Path(cpath).name[:-10]
            atlas_name = f"{canon_stem}.atlas.txt"
            (dest_dir / atlas_name).write_text(txt, encoding="utf-8")
            for ln in txt.splitlines():
                s = ln.strip()
                if s.lower().endswith(".png"):
                    atlas_pages.append(s)

    for cpath, ptr in sorted(container.items()):
        low = cpath.lower()
        if prefix not in low:
            continue
        if low.endswith(".png"):
            im = ptr.read().image.convert("RGBA")
            img_map[Path(cpath).name.lower()] = im

    for page in atlas_pages:
        im = img_map.get(page.lower()) or next(iter(img_map.values()))
        im.save(dest_dir / page, "PNG")
        tex_files.append(page)
        tex_names.append(Path(page).stem)

    for cpath, ptr in sorted(container.items()):
        low = cpath.lower()
        if prefix not in low:
            continue
        if low.endswith(".skel.bytes"):
            raw_b = ptr.read().m_Script.encode("utf-8", "surrogateescape")
            base_stem = tex_names[0] if tex_names else Path(atlas_name).name[:-10]
            skel_name = f"{base_stem}.skel.json"
            (dest_dir / skel_name).write_bytes(raw_b)

    return {
        "skeleton": skel_name,
        "atlas": atlas_name,
        "tex_names": tex_names,
        "textures": tex_files,
    }


def _build_static_bg_submodel(out_sub_dir: Path) -> str:
    """Composite Image_01/02/03/05 onto a 1768x1176 canvas and emit Spine 3.8 static submodel."""
    out_sub_dir.mkdir(parents=True, exist_ok=True)
    bg4 = load_ab(BATCH4_BG_AB)
    sprites: dict[str, Image.Image] = {}
    for obj in bg4.objects:
        if obj.type.name == "Sprite":
            sp = obj.read()
            if "aurora_s4_background_" in sp.m_Name.lower():
                sprites[sp.m_Name] = sp.image.convert("RGBA")

    canvas = Image.new("RGBA", (BG_CANVAS_W, BG_CANVAS_H), (0, 0, 0, 0))
    layers = [
        ("Aurora_S4_Background_02", 0.0, 11.44, 1768.0, 1176.0),
        ("Aurora_S4_Background_03", 0.0, -145.60, 1768.0, 320.0),
        ("Aurora_S4_Background_04", 0.0, 80.60, 1768.0, 1038.0),
        ("Aurora_S4_Background_06", 0.0, 11.44, 1768.0, 1176.0),
    ]
    for sp_name, ucx, ucy, uw, uh in layers:
        im = sprites[sp_name]
        # Convert Unity UI center `(ucx, ucy)` into top-left PIL pixel coords on BG_CANVAS
        left = round((ucx - BG_CENTER_UI_X) + (BG_CANVAS_W - uw) / 2.0)
        top = round((BG_CENTER_UI_Y - ucy) + (BG_CANVAS_H - uh) / 2.0)
        canvas.alpha_composite(im, (left, top))

    tex_file = "bg_aurora_s4.png"
    canvas.save(out_sub_dir / tex_file, "PNG")

    atlas_txt = (
        f"\n{tex_file}\n"
        f"size: {BG_CANVAS_W},{BG_CANVAS_H}\n"
        f"format: RGBA8888\n"
        f"filter: Linear,Linear\n"
        f"repeat: none\n"
        f"bg_aurora_s4\n"
        f"  rotate: false\n"
        f"  xy: 0, 0\n"
        f"  size: {BG_CANVAS_W}, {BG_CANVAS_H}\n"
        f"  orig: {BG_CANVAS_W}, {BG_CANVAS_H}\n"
        f"  offset: 0, 0\n"
        f"  index: -1\n"
    )
    atlas_file = "bg_static.atlas.txt"
    (out_sub_dir / atlas_file).write_text(atlas_txt, encoding="utf-8")

    sx, sy, sw, sh = ui_to_spine_rect(BG_CENTER_UI_X, BG_CENTER_UI_Y, BG_CANVAS_W, BG_CANVAS_H)
    scale = 1.0 / AURORA_UI_PER_SPINE
    skel_json = {
        "skeleton": {
            "hash": "aurora_s4_bg_static",
            "spine": "3.8.79",
            "x": round(sx - sw / 2.0, 2),
            "y": round(sy - sh / 2.0, 2),
            "width": round(sw, 2),
            "height": round(sh, 2),
        },
        "bones": [
            {"name": "root"},
            {"name": "bg_root", "parent": "root", "x": round(sx, 4), "y": round(sy, 4), "scaleX": round(scale, 6), "scaleY": round(scale, 6)},
        ],
        "slots": [{"name": "bg_slot", "bone": "bg_root", "attachment": "bg_aurora_s4"}],
        "skins": [
            {
                "name": "default",
                "attachments": {
                    "bg_slot": {
                        "bg_aurora_s4": {"x": 0.0, "y": 0.0, "width": BG_CANVAS_W, "height": BG_CANVAS_H}
                    }
                },
            }
        ],
        "animations": {"idle": {}},
    }
    skel_file = "bg_static.skel.json"
    write_json(out_sub_dir / skel_file, skel_json)

    cfg = {
        "conf_ver": 1,
        "type": 9,
        "controllers": {
            "param_hit": {},
            "param_loop": {},
            "intimacy_system": {},
            "slot_opacity": {},
            "slot_color": {},
        },
        "hit_areas": [],
        "motions": {"idle": [{"name": "idle", "file": "idle", "file_loop": True}]},
        "options": {
            "id": "aurora_s4_bg_static",
            "scale_factor": 0.11,
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 0,
            "edge_padding": False,
        },
        "skeleton": skel_file,
        "atlases": [{"atlas": atlas_file, "tex_names": ["bg_aurora_s4"], "textures": [tex_file]}],
    }
    write_json(out_sub_dir / ".config.json", cfg)
    return "submodels/bg_static/.config.json"


def _extract_real_fx_sprites() -> dict[str, Image.Image]:
    """Extract all 16 real particle textures referenced by Aurora_S4 FX prefabs."""
    FX_SPRITE_CACHE.mkdir(parents=True, exist_ok=True)
    needed_bundles = {
        "14_effect/battle/_batch1.ab": ["FX_glow110"],
        "14_effect/battle/_batch3.ab": ["FX_ZC_Trail007", "FX_ZC_Noise01"],
        "14_effect/battle/_batch4.ab": ["zxy_gra_sgx_01", "FX_ZC_Glow017", "FX_ZC_Glow019"],
        "14_effect/battle/_batch5.ab": ["zxy_czy_ansdzbaodian"],
        "14_effect/battle/_batch6.ab": ["FX_gra_xinfen"],
        "14_effect/battle/_batch9.ab": ["FX_ZC_Glow028"],
        "14_effect/battle/_batch10.ab": ["FX_ZC_Special426", "FX_ZC_Mask139"],
        "14_effect/battle/_batch11.ab": ["FX_cxj_shizi_04", "FX_cxj_beike_02_2x2", "FX_cxj_beike_01"],
        "14_effect/battle/_common.ab": ["FX_FH_Line_Tile_01"],
        "14_effect/ui/batch1.ab": ["FX_mask13"],
        "14_effect/ui/batch2.ab": ["FX_xingxing_109", "FX_glow130"],
    }
    sprites: dict[str, Image.Image] = {}
    for rel, names in needed_bundles.items():
        want = {n.lower(): n for n in names}
        missing = [n for low, n in want.items() if not (FX_SPRITE_CACHE / f"{n}.png").exists()]
        if missing:
            env = load_ab(CDN_ROOT / rel)
            for obj in env.objects:
                if obj.type.name == "Texture2D":
                    nm = obj.peek_name()
                    if nm.lower() in want:
                        im = obj.read().image.convert("RGBA")
                        im.save(FX_SPRITE_CACHE / f"{want[nm.lower()]}.png", "PNG")
        for n in names:
            sprites[n] = Image.open(FX_SPRITE_CACHE / f"{n}.png").convert("RGBA")
    return sprites


def _tint_and_alpha(
    im: Image.Image,
    rgb: tuple[int, int, int],
    alpha_mul: float,
    premultiply_for_add: bool = False,
    preserve_sprite_rgb: bool = False,
) -> Image.Image:
    """Tint a particle sprite, automatically picking Alpha vs Luma mask and avoiding white clipping."""
    r, g, b, a = im.split()
    luma = im.convert("L")
    a_ext = a.getextrema()
    l_ext = luma.getextrema()

    if a_ext == (255, 255):
        # Opaque alpha -> shape mask lives in luminance (Additive black-bg texture)
        mask = luma
    else:
        # Transparent texture -> shape mask lives in Alpha channel
        mask = a

    out_a = mask.point(lambda v: max(0, min(255, int(round(v * alpha_mul)))))
    if preserve_sprite_rgb:
        tr, tg, tb = r, g, b
    elif l_ext == (255, 255) or a_ext == (255, 255):
        # Pure white RGB with shape in alpha, OR black-bg texture with shape in luma
        tr = mask.point(lambda v: int(round((255 if l_ext == (255, 255) else v) * rgb[0] / 255.0)))
        tg = mask.point(lambda v: int(round((255 if l_ext == (255, 255) else v) * rgb[1] / 255.0)))
        tb = mask.point(lambda v: int(round((255 if l_ext == (255, 255) else v) * rgb[2] / 255.0)))
    else:
        # Texture carries both RGB shading and Alpha mask
        tr = r.point(lambda v: int(round(v * rgb[0] / 255.0)))
        tg = g.point(lambda v: int(round(v * rgb[1] / 255.0)))
        tb = b.point(lambda v: int(round(v * rgb[2] / 255.0)))

    if premultiply_for_add:
        # Store effective linear additive light contribution inside RGB so canvas addition respects alpha_mul
        tr = ImageChops.multiply(tr, out_a)
        tg = ImageChops.multiply(tg, out_a)
        tb = ImageChops.multiply(tb, out_a)
        # Keep crisp non-zero alpha mask where light > 0 so Spine additive shader & tight-crop stay clean
        lum_add = Image.merge("RGB", (tr, tg, tb)).convert("L")
        add_a = lum_add.point(lambda v: 0 if v < 2 else min(255, v * 3))
        return Image.merge("RGBA", (tr, tg, tb, add_a))

    return Image.merge("RGBA", (tr, tg, tb, out_a))


def _paste_centered(canvas: Image.Image, sprite: Image.Image, cx: float, cy: float, angle: float = 0.0) -> None:
    if angle != 0.0:
        sprite = sprite.rotate(angle, resample=Image.Resampling.BILINEAR, expand=True)
    x = int(round(cx - sprite.width / 2.0))
    y = int(round(cy - sprite.height / 2.0))
    if x >= canvas.width or y >= canvas.height or x + sprite.width <= 0 or y + sprite.height <= 0:
        return
    canvas.alpha_composite(sprite, dest=(max(0, x), max(0, y)), source=(max(0, -x), max(0, -y)))


def _add_composite(dst: Image.Image, src: Image.Image, cx: float, cy: float, angle: float = 0.0) -> None:
    """Accumulate additive glow RGB onto dst (`src` must be premultiplied for add)."""
    if angle != 0.0:
        src = src.rotate(angle, resample=Image.Resampling.BILINEAR, expand=True)
    x = int(round(cx - src.width / 2.0))
    y = int(round(cy - src.height / 2.0))
    if x >= dst.width or y >= dst.height or x + src.width <= 0 or y + src.height <= 0:
        return
    dx = max(0, x)
    dy = max(0, y)
    sx0 = max(0, -x)
    sy0 = max(0, -y)
    cw = min(src.width - sx0, dst.width - dx)
    ch = min(src.height - sy0, dst.height - dy)
    if cw <= 0 or ch <= 0:
        return
    sub_dst = dst.crop((dx, dy, dx + cw, dy + ch))
    sub_src = src.crop((sx0, sy0, sx0 + cw, sy0 + ch))
    r1, g1, b1, a1 = sub_dst.split()
    r2, g2, b2, a2 = sub_src.split()
    nr = ImageChops.add(r1, r2)
    ng = ImageChops.add(g1, g2)
    nb = ImageChops.add(b1, b2)
    na = ImageChops.lighter(a1, a2)
    dst.paste(Image.merge("RGBA", (nr, ng, nb, na)), (dx, dy))


def _build_fx_submodel(out_sub_dir: Path, prefer_unity_captures: bool = True) -> str:
    """Pack Unity-recorded FX PNG sequences (or synthesized fallback) into Spine 3.8 FX Submodel."""
    W, H = 884, 588  # 0.5x of 1768x1176 Aurora_S4_Background
    unity_ready = (
        prefer_unity_captures
        and (FX_SEQ_SRC / "idle/add").is_dir()
        and ((FX_SEQ_SRC / "fx_9008135/normal").is_dir() or (FX_SEQ_SRC / "fx_9008135/add").is_dir())
        and (FX_SEQ_SRC / "fx_9008136/normal").is_dir()
        and (FX_SEQ_SRC / "fx_9008136/add").is_dir()
        and any((FX_SEQ_SRC / "idle/add").glob("frame_*.png"))
    )
    if unity_ready:
        idle_norm_files = sorted((FX_SEQ_SRC / "idle/normal").glob("frame_*.png")) if (FX_SEQ_SRC / "idle/normal").is_dir() else []
        idle_add_files = sorted((FX_SEQ_SRC / "idle/add").glob("frame_*.png"))
        chat_norm_files = sorted((FX_SEQ_SRC / "fx_9008135/normal").glob("frame_*.png")) if (FX_SEQ_SRC / "fx_9008135/normal").is_dir() else []
        chat_add_files = sorted((FX_SEQ_SRC / "fx_9008135/add").glob("frame_*.png")) if (FX_SEQ_SRC / "fx_9008135/add").is_dir() else []
        t1_norm_files = sorted((FX_SEQ_SRC / "fx_9008136/normal").glob("frame_*.png"))
        t1_add_files = sorted((FX_SEQ_SRC / "fx_9008136/add").glob("frame_*.png"))
        print(f"Using Unity-recorded FX sequences from {FX_SEQ_SRC} "
              f"(idle={len(idle_add_files)}, chat={max(len(chat_norm_files), len(chat_add_files))}, touch1={len(t1_add_files)})")
    else:
        import shutil
        if FX_SEQ_SRC.exists():
            shutil.rmtree(FX_SEQ_SRC)
        sp = _extract_real_fx_sprites()
        FX_SEQ_SRC.mkdir(parents=True, exist_ok=True)

        # Pre-scale base sprites (all sourced directly from official 14_effect bundles)
        star_64 = sp["FX_xingxing_109"].resize((22, 22), Image.Resampling.LANCZOS)
        shan_s = sp["FX_cxj_shizi_04"].resize((38, 38), Image.Resampling.LANCZOS)
        glow_bg1 = sp["FX_glow130"].resize((120, 120), Image.Resampling.LANCZOS)
        glow_bg2 = sp["FX_ZC_Glow017"].resize((96, 175), Image.Resampling.LANCZOS)
        glow_02 = sp["FX_ZC_Glow019"].resize((280, 280), Image.Resampling.LANCZOS)
        smoke_tex = sp["FX_ZC_Special426"].resize((380, 200), Image.Resampling.LANCZOS)
        firefly = sp["FX_ZC_Glow028"].resize((34, 34), Image.Resampling.LANCZOS)
        aixin_s = sp["FX_gra_xinfen"].resize((54, 54), Image.Resampling.LANCZOS)
        xianglian_s = sp["FX_cxj_beike_01"].resize((68, 68), Image.Resampling.LANCZOS)
        glow110 = sp["FX_glow110"].resize((130, 130), Image.Resampling.LANCZOS)
        shan_big = sp["zxy_gra_sgx_01"].resize((190, 110), Image.Resampling.LANCZOS)
        bao_sheet = sp["zxy_czy_ansdzbaodian"]  # 1024x512 -> two 512x512 shockwave halves
        bao_frames = [
            bao_sheet.crop((0, 0, 512, 512)).resize((180, 180), Image.Resampling.LANCZOS),
            bao_sheet.crop((512, 0, 1024, 512)).resize((180, 180), Image.Resampling.LANCZOS),
        ]
        beike_2x2 = sp["FX_cxj_beike_02_2x2"]   # 256x256 (4 128x128 frames)
        beike_frames = [
            beike_2x2.crop((c * 128, r * 128, (c + 1) * 128, (r + 1) * 128)).resize((46, 46), Image.Resampling.LANCZOS)
            for r in range(2) for c in range(2)
        ]

        # 1. Idle seamless ambient FX loop (30 frames @ 15fps = 2.0s)
        idle_norm_dir = FX_SEQ_SRC / "idle/normal"
        idle_add_dir = FX_SEQ_SRC / "idle/add"
        idle_norm_dir.mkdir(parents=True, exist_ok=True)
        idle_add_dir.mkdir(parents=True, exist_ok=True)
        idle_n = 30
        star_pts = [
            (160, 150, 0.0), (280, 95, 0.25), (670, 120, 0.55), (750, 220, 0.8),
            (210, 320, 0.4), (620, 270, 0.15), (410, 88, 0.65),
        ]
        shan_pts = [(468, 315, 0.1), (366, 379, 0.45), (282, 167, 0.78)]
        idle_norm_files, idle_add_files = [], []

        for i in range(idle_n):
            ph = i / idle_n
            ang = 2.0 * math.pi * ph
            im_n = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            im_a = Image.new("RGBA", (W, H), (0, 0, 0, 0))

            sm_a = 0.22 + 0.08 * math.sin(ang)
            sm = _tint_and_alpha(smoke_tex, (130, 185, 245), sm_a)
            _paste_centered(im_n, sm, 560 + 28 * math.cos(ang), 495 + 6 * math.sin(ang))

            g_pulse = 0.22 + 0.10 * math.sin(ang)
            _add_composite(im_a, _tint_and_alpha(glow_bg2, (135, 205, 255), g_pulse, premultiply_for_add=True), 690, 145, angle=-22)
            _add_composite(im_a, _tint_and_alpha(glow_bg1, (125, 200, 255), 0.20 + 0.08 * math.cos(ang), premultiply_for_add=True), 418, 215)
            _add_composite(im_a, _tint_and_alpha(glow_02, (110, 185, 255), 0.24 + 0.08 * math.sin(ang + 1.0), premultiply_for_add=True), 485, 430)

            for sx0, sy0, phi in star_pts:
                tw = max(0.0, math.sin(ang + phi * 2.0 * math.pi)) ** 2
                if tw > 0.08:
                    _add_composite(im_a, _tint_and_alpha(star_64, (205, 238, 255), 0.65 * tw, premultiply_for_add=True), sx0, sy0)
            for x0, y0, phi in shan_pts:
                tw = 0.25 + 0.65 * (0.5 + 0.5 * math.sin(ang + phi * 2.0 * math.pi))
                _add_composite(im_a, _tint_and_alpha(shan_s, (175, 228, 255), 0.52 * tw, premultiply_for_add=True), x0, y0, angle=20 * math.sin(ang))

            pn = idle_norm_dir / f"frame_{i:04d}.png"
            pa = idle_add_dir / f"frame_{i:04d}.png"
            im_n.save(pn, "PNG")
            im_a.save(pa, "PNG")
            idle_norm_files.append(pn)
            idle_add_files.append(pa)

        # 2. Chat FX 9008135
        chat_add_dir = FX_SEQ_SRC / "fx_9008135/add"
        chat_add_dir.mkdir(parents=True, exist_ok=True)
        chat_files = []
        swarm_seeds = [(520 + (k * 37) % 160 - 80, 420 - (k * 29) % 140, k * 0.42) for k in range(12)]
        for i in range(30):
            t = i / 29.0
            env_a = math.sin(math.pi * t)
            im_a = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            for j, (bx, by, ph) in enumerate(swarm_seeds):
                px = bx + 26 * math.sin(t * 4.5 + ph)
                py = by - 135 * t + 12 * math.cos(t * 5.0 + ph)
                a_val = env_a * (0.35 + 0.45 * abs(math.sin(t * 6.2 + ph)))
                sc = 0.55 + 0.45 * math.sin(t * 3.1 + ph)
                sp_r = firefly.resize((max(8, int(34 * sc)), max(8, int(34 * sc))), Image.Resampling.BILINEAR)
                col = (255, 220, 145) if j % 2 == 0 else (150, 225, 255)
                _add_composite(im_a, _tint_and_alpha(sp_r, col, a_val, premultiply_for_add=True), px, py)
            p = chat_add_dir / f"frame_{i:04d}.png"
            im_a.save(p, "PNG")
            chat_files.append(p)

        # 3. Touch1 FX 9008136
        t1_norm_dir = FX_SEQ_SRC / "fx_9008136/normal"
        t1_add_dir = FX_SEQ_SRC / "fx_9008136/add"
        t1_norm_dir.mkdir(parents=True, exist_ok=True)
        t1_add_dir.mkdir(parents=True, exist_ok=True)
        t1_norm_files, t1_add_files = [], []
        ax, ay = 488.0, 245.0
        for i in range(36):
            t = i / 35.0
            env = math.sin(math.pi * t)
            im_n = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            im_a = Image.new("RGBA", (W, H), (0, 0, 0, 0))

            xl = _tint_and_alpha(xianglian_s, (255, 255, 255), min(1.0, env * 0.95), preserve_sprite_rgb=True)
            _paste_centered(im_n, xl, ax, ay - 22 * t)
            _add_composite(im_a, _tint_and_alpha(glow110, (145, 210, 255), 0.36 * env, premultiply_for_add=True), ax, ay - 22 * t)

            for k in range(5):
                ang_k = (k / 5.0) * 2.0 * math.pi + t * 1.4
                rad = 25 + 95 * t
                bk = _tint_and_alpha(beike_frames[(i // 3 + k) % 4], (210, 238, 255), 0.72 * env, premultiply_for_add=True, preserve_sprite_rgb=True)
                _add_composite(im_a, bk, ax + rad * math.cos(ang_k), ay - 20 + 0.65 * rad * math.sin(ang_k), angle=t * 90)

            for k in range(6):
                ang_k = (k / 6.0) * 2.0 * math.pi + 0.4
                rad = 18 + 80 * (t ** 0.85)
                hx = ax + rad * math.cos(ang_k)
                hy = ay - 45 * t + 0.55 * rad * math.sin(ang_k)
                _add_composite(im_a, _tint_and_alpha(aixin_s, (255, 165, 215), 0.52 * env, premultiply_for_add=True), hx, hy)

            if 0.12 <= t <= 0.65:
                bt = (t - 0.12) / 0.53
                ba = math.sin(math.pi * bt)
                b_sp = bao_frames[0 if bt < 0.5 else 1]
                _add_composite(im_a, _tint_and_alpha(b_sp, (180, 232, 255), 0.42 * ba, premultiply_for_add=True), ax, ay)
                _add_composite(im_a, _tint_and_alpha(shan_big, (205, 240, 255), 0.38 * ba, premultiply_for_add=True), ax, ay, angle=15)

            for k in range(10):
                ang_k = k * 0.628 + t * 0.8
                rad = 30 + 135 * t
                lx = ax + rad * math.cos(ang_k)
                ly = ay - 15 * t + rad * 0.7 * math.sin(ang_k)
                _add_composite(im_a, _tint_and_alpha(firefly, (175, 232, 255), 0.48 * env, premultiply_for_add=True), lx, ly)

            pn = t1_norm_dir / f"frame_{i:04d}.png"
            pa = t1_add_dir / f"frame_{i:04d}.png"
            im_n.save(pn, "PNG")
            im_a.save(pa, "PNG")
            t1_norm_files.append(pn)
            t1_add_files.append(pa)

    sx, sy, sw, sh = ui_to_spine_rect(BG_CENTER_UI_X, BG_CENTER_UI_Y, BG_CANVAS_W, BG_CANVAS_H)
    root_sx = sw / W
    root_sy = sh / H
    seq_fps = 12.0 if unity_ready else 15.0
    if not unity_ready:
        chat_norm_files = []
        chat_add_files = chat_files
    sequences = [
        AnimSequenceSpec(
            name="idle",
            fps=seq_fps,
            loop=True,
            is_overlay=False,
            normal_frames=idle_norm_files,
            add_frames=idle_add_files,
            motion_group="idle",
        ),
        AnimSequenceSpec(
            name="fx_9008135",
            fps=seq_fps,
            loop=False,
            is_overlay=True,
            normal_frames=chat_norm_files,
            add_frames=chat_add_files,
            motion_group="main",
        ),
        AnimSequenceSpec(
            name="fx_9008136",
            fps=seq_fps,
            loop=False,
            is_overlay=True,
            normal_frames=t1_norm_files,
            add_frames=t1_add_files,
            motion_group="main",
        ),
    ]
    pack_fx_submodel(
        output_dir=out_sub_dir,
        model_name="fx_aurora_s4",
        model_id="aurora_s4_fx",
        sequences=sequences,
        root_x=sx,
        root_y=sy,
        root_scale_x=root_sx,
        root_scale_y=root_sy,
        scale_factor=0.11,
        max_atlas_size=2048,
        padding=2,
    )
    return "submodels/fx_aurora_s4/.config.json"


def build_aurora_s4_spine(out_dir: Path = OUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    aud_dir = out_dir / "audio"
    bgm_dir = out_dir / "bgm"
    sub_root = out_dir / "submodels"
    for d in (aud_dir, bgm_dir, sub_root):
        d.mkdir(parents=True, exist_ok=True)

    b4 = load_ab(BATCH4_SPINE_AB)
    cont = b4.container or {}

    # 1. Extract main Spine model (`souldress_aurora_04/`)
    main_meta = _extract_spine_bundle_unit(cont, "souldress_aurora_04/souldress_aurora_04.", out_dir)

    # 2. Extract animated background submodels BJ_01 / BJ_02 / BJ_03
    # Scale factors calibrated directly to Aurora_S4_Background.prefab relative to aurora_s4_main (0.11)
    bj_specs = [
        ("bj_03", "souldress_aurora_04_bj_03", 0.10968),
        ("bj_02", "souldress_aurora_04_bj_02", 0.10968),
        ("bj_01", "souldress_aurora_04_bj_01", 0.11006),
    ]
    for sub_name, prefix_key, rel_scale in bj_specs:
        sdir = sub_root / sub_name
        meta = _extract_spine_bundle_unit(cont, f"/{prefix_key}/{prefix_key}.", sdir)
        sub_cfg = {
            "conf_ver": 1,
            "type": 9,
            "controllers": {
                "param_hit": {},
                "param_loop": {},
                "intimacy_system": {},
                "slot_opacity": {},
                "slot_color": {},
            },
            "hit_areas": [],
            "motions": {"idle": [{"name": "idle", "file": "idle", "file_loop": True}]},
            "options": {
                "id": f"aurora_s4_{sub_name}",
                "scale_factor": rel_scale,
                "position_x": 0.0,
                "position_y": 0.0,
                "tex_type": 0,
                "edge_padding": False,
            },
            "skeleton": meta["skeleton"],
            "atlases": [
                {"atlas": meta["atlas"], "tex_names": meta["tex_names"], "textures": meta["textures"]}
            ],
        }
        write_json(sdir / ".config.json", sub_cfg)

    # 3. Build composited static BG submodel (-3) and Frame-Sequence FX submodel (+2)
    _build_static_bg_submodel(sub_root / "bg_static")
    _build_fx_submodel(sub_root / "fx_aurora_s4")

    # 4. Extract ALL 13 official Spine WAV voices + Skin BGM
    cv_env = load_ab(CV_AURORA_AB)
    clip_by_lower = {obj.peek_name().lower(): obj for obj in cv_env.objects if obj.type.name == "AudioClip"}
    repo = LuaTableRepo()

    extracted_wavs: dict[str, str] = {}
    spine_rows: dict[int, dict] = {}
    for aid in range(192001, 192014):
        body = repo.spine_actions[aid]
        cv_id = int(re.search(r"CV\s*=\s*(\d+)", body).group(1))
        st = re.search(r'SoulActionState\s*=\s*"([^"]+)"', body).group(1)
        mst = re.search(r'MarryActionState\s*=\s*"([^"]+)"', body).group(1)
        eff_m = re.search(r"EffectId\s*=\s*(\d+)", body)
        eff_id = int(eff_m.group(1)) if eff_m else None
        cv_info = repo.resolve_cv(cv_id)
        stem = cv_info["sound_stem"]
        clip_obj = clip_by_lower[stem.lower()]
        cname = clip_obj.peek_name()
        wav_rel = f"audio/{cname}.wav"
        (out_dir / wav_rel).write_bytes(extract_wav_bytes(clip_obj))
        extracted_wavs[cname] = wav_rel
        spine_rows[aid] = {
            "id": aid,
            "state": st,
            "marry_state": mst,
            "effect_id": eff_id,
            "sound": wav_rel,
            "text": cv_info["text"],
            "text_duration": cv_info["duration_ms"],
        }

    # Skin BGM (`BGM_SkinMusic05_Aurora_S4.wav`)
    bgm_env = load_ab(BGM_BATCH10_AB)
    for obj in bgm_env.objects:
        if obj.type.name == "AudioClip" and obj.peek_name() == "BGM_SkinMusic05_Aurora_S4":
            (bgm_dir / "BGM_SkinMusic05_Aurora_S4.wav").write_bytes(extract_wav_bytes(obj))
            break

    # Helper to construct a Spine motion entry with optional synced FX command
    def mk_mtn(aid: int, use_marry: bool = True, idx_label: str = "") -> dict:
        row = spine_rows[aid]
        anim = row["marry_state"] if use_marry else row["state"]
        item: dict = {
            "name": f"{idx_label or aid}_{anim}",
            "file": anim,
            "fade_in": 100,
            "fade_out": 100,
            "sound": row["sound"],
            "text": row["text"],
            "text_duration": row["text_duration"],
        }
        if row["effect_id"] == 9008135:
            item["command"] = "start_mtn aurora_s4_fx main:fx_9008135"
        elif row["effect_id"] == 9008136:
            item["command"] = "start_mtn aurora_s4_fx main:fx_9008136"
        return item

    # Wire ALL 5 submodels automatically on load via "start" motion (+ key 'r' reload)
    submodel_cmd = (
        "add_submodel submodels/bg_static/.config.json -3; "
        "add_submodel submodels/bj_03/.config.json -2; "
        "add_submodel submodels/bj_02/.config.json -1; "
        "add_submodel submodels/bj_01/.config.json 1; "
        "add_submodel submodels/fx_aurora_s4/.config.json 2"
    )

    reload_cmd = "; ".join(
        [
            f"remove_submodel {seg.strip().split()[1]}"
            for seg in submodel_cmd.split(";")
            if len(seg.strip().split()) == 3 and seg.strip().split()[0] == "add_submodel"
        ]
        + [submodel_cmd]
    )

    motions = {
        "idle": [
            {"name": "idle_marry", "file": "idle_marry", "fade_in": 10, "fade_out": 10, "file_loop": True},
        ],
        "start": [
            {**mk_mtn(192001, True, "start_morning"), "command": submodel_cmd},
            {**mk_mtn(192002, True, "start_noon"), "command": submodel_cmd},
            {**mk_mtn(192003, True, "start_evening"), "command": submodel_cmd},
        ],
        "reload_bg": [
            {"name": "reload_submodels", "file": "idle_marry", "command": reload_cmd},
        ],
        "闲聊与问答": [
            mk_mtn(192004, True), mk_mtn(192008, True), mk_mtn(192009, True),
            mk_mtn(192001, True), mk_mtn(192002, True), mk_mtn(192003, True),
        ],
        "头": [
            mk_mtn(192003, True), mk_mtn(192011, True), mk_mtn(192007, True),
        ],
        "左手": [
            mk_mtn(192005, True), mk_mtn(192006, True), mk_mtn(192012, True),
        ],
        "右手": [
            mk_mtn(192009, True), mk_mtn(192006, True), mk_mtn(192008, True),
        ],
        "胸": [
            mk_mtn(192007, True), mk_mtn(192005, True), mk_mtn(192004, True), mk_mtn(192012, True),
        ],
        "腿": [
            mk_mtn(192008, True), mk_mtn(192009, True), mk_mtn(192010, True),
        ],
        "足": [
            mk_mtn(192010, True), mk_mtn(192013, True),
        ],
        "普通模式全动作": [
            mk_mtn(aid, False, f"normal_{aid}") for aid in range(192001, 192014)
        ],
        "誓约模式全动作": [
            mk_mtn(aid, True, f"marry_{aid}") for aid in range(192001, 192014)
        ],
    }

    # Inherit calibrated hit_areas (bone IDs: 47, 113, 321, 83, 88, 84, 87) & options from verified backup
    hit_areas = [
        {"name": "头", "id": "47", "motion": "头", "width": 2.5, "height": 2.0, "center_x": 0.5, "center_y": -0.5},
        {"name": "左手", "id": "113", "motion": "左手", "width": 0.7, "height": 1.0},
        {"name": "右手", "id": "321", "motion": "右手", "width": 0.6, "height": 1.0},
        {"name": "腿", "id": "83", "motion": "腿", "width": 4.0, "height": 5.0, "center_x": -3.0, "center_y": 2.0},
        {"name": "胸", "id": "88", "motion": "胸", "width": 2.0, "height": 1.5, "center_x": 0.3, "center_y": 0.5},
        {"name": "足", "id": "84", "motion": "足", "width": 2.0, "height": 1.0, "center_x": -1.0, "center_y": -0.1},
        {"name": "足", "id": "87", "motion": "足", "width": 2.0, "height": 1.0, "center_x": -1.0, "center_y": -0.4},
    ]

    cfg = {
        "conf_ver": 1,
        "type": 9,
        "controllers": {
            "param_hit": {},
            "param_loop": {},
            "key_trigger": {
                "enabled": True,
                "items": [
                    {"input": 65, "down_mtn": "闲聊与问答"},  # VK_A
                    {"input": 66, "down_mtn": "头"},          # VK_B
                    {"input": 67, "down_mtn": "左手"},        # VK_C
                    {"input": 68, "down_mtn": "右手"},        # VK_D
                    {"input": 69, "down_mtn": "胸"},          # VK_E
                    {"input": 70, "down_mtn": "腿"},          # VK_F
                    {"input": 71, "down_mtn": "足"},          # VK_G
                    {"input": 77, "down_mtn": "誓约模式全动作"},  # VK_M
                    {"input": 78, "down_mtn": "普通模式全动作"},  # VK_N
                    {"input": 82, "down_mtn": "reload_bg"},    # VK_R
                ],
            },
            "eye_blink": {"min_interval": 500, "max_interval": 6000},
            "lip_sync": {"gain": 5.0},
            "mouse_tracking": {"smooth_time": 0.15},
            "auto_breath": {},
            "extra_motion": {},
            "accelerometer": {},
            "intimacy_system": {},
            "slot_opacity": {},
            "slot_color": {},
        },
        "hit_areas": hit_areas,
        "motions": motions,
        "options": {
            "id": "aurora_s4_main",
            "scale_factor": 0.11,
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 0,
            "edge_padding": False,
            "shader_type": 0,
        },
        "skeleton": main_meta["skeleton"],
        "atlases": [
            {
                "atlas": main_meta["atlas"],
                "tex_names": main_meta["tex_names"],
                "textures": main_meta["textures"],
            }
        ],
    }
    write_json(out_dir / ".config.json", cfg)
    return {
        "out_dir": str(out_dir),
        "main_skeleton": main_meta["skeleton"],
        "submodels": ["bg_static (-3)", "bj_03 (-2)", "bj_02 (-1)", "bj_01 (+1)", "fx_aurora_s4 (+2)"],
        "wavs_extracted": len(extracted_wavs),
        "bgm_extracted": (bgm_dir / "BGM_SkinMusic05_Aurora_S4.wav").exists(),
        "hit_areas": len(hit_areas),
        "motion_groups": {k: len(v) for k, v in motions.items()},
    }


if __name__ == "__main__":
    summary = build_aurora_s4_spine()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
