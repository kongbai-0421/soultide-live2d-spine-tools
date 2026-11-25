"""Fix 和铃/古锦新韵 (4301_heling_s2):
1. Restore & center MAIN + all 4 submodels at (0, 0) with unified base_scale=0.077
   (matching 欧若拉/童话心绘 viewport coverage ~109%, eliminating giant 218% scale & (+4435,+1954) offset
    and fixing EX Studio's ApplyScaleAndPosition drift).
2. Repack fx_heling_s2_back & fx_heling_s2_front from 13x 4096x4096 PNGs (49.6MB / 800MB VRAM)
   into 2 compact PNGs (~2-3MB / ~40-50MB VRAM) with alpha<=3 noise trimming on soft sunbeams,
   36 frames @ 6fps (exact 6.0s loop), and exact fx_root scale compensation -> eliminates loading freeze!
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
sys.path.insert(0, str(TOOLS_DIR))

from batch_spine_builder import parse_spine38_binary, patch_binary_root_transform
from soultide_common import write_json
from spine_fx_submodel_packer import AnimSequenceSpec, pack_fx_submodel

SKIN_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\和铃\古锦新韵")
SEQ_DIR = TOOLS_DIR / "_batch_fx_sequences" / "4301_heling_s2"
TEMP_SEQ = Path(r".\_scratch\heling_fx_slim")

# Original bg_static center & scale ratio
OLD_BASE_SCALE = 0.154
NEW_BASE_SCALE = 0.077
BJ01_RATIO = 0.15785 / 0.154  # 1.025 exactly
NEW_BJ01_SCALE = round(NEW_BASE_SCALE * BJ01_RATIO, 6)  # 0.078925

SHIFT_X = -4435.2501
SHIFT_Y = -1954.25
ORIG_FX_SCALE = 2.777778  # 4250 / 1530


def prepare_slim_frames(src_dir: Path, dst_dir: Path, scale: float, step: int = 2, alpha_thresh: int = 0) -> list[Path]:
    dst_dir.mkdir(parents=True, exist_ok=True)
    src_pngs = sorted(src_dir.glob("*.png"))
    selected = src_pngs[::step]
    out_paths: list[Path] = []
    for i, sp in enumerate(selected):
        with Image.open(sp) as im:
            rgba = im.convert("RGBA")
            nw = max(1, int(round(rgba.width * scale)))
            nh = max(1, int(round(rgba.height * scale)))
            resized = rgba.resize((nw, nh), Image.Resampling.LANCZOS)
            if alpha_thresh > 0:
                r, g, b, a = resized.split()
                mask = a.point(lambda v: 255 if v > alpha_thresh else 0)
                # Zero out RGB + A where alpha <= alpha_thresh (safe for PMA)
                black = Image.new("L", resized.size, 0)
                r = Image.composite(r, black, mask)
                g = Image.composite(g, black, mask)
                b = Image.composite(b, black, mask)
                a = Image.composite(a, black, mask)
                resized = Image.merge("RGBA", (r, g, b, a))
            op = dst_dir / f"frame_{i:04d}.png"
            resized.save(op, "PNG", compress_level=1)
            out_paths.append(op)
    return out_paths


def main() -> None:
    # 0. Check main & bj_01 root transforms
    main_skel_p = SKIN_DIR / "SoulDress_HeLing_02.skel.json"
    main_raw = main_skel_p.read_bytes()
    main_parsed = parse_spine38_binary(main_raw)
    b0 = main_parsed["bones"][0]
    print("Main root before:", b0)
    # Check if root (idx 0) has any animation timeline
    root_anim_hits = [an for an, bmap in main_parsed.get("anim_bone_t0", {}).items() if 0 in bmap]
    print("Main root anim_bone_t0 hits:", root_anim_hits)
    assert not root_anim_hits, f"Root bone has animation timelines: {root_anim_hits}"

    bj_skel_p = SKIN_DIR / "submodels" / "bj_01" / "SoulDress_HeLing_02_BJ_01.skel.json"
    bj_raw = bj_skel_p.read_bytes()
    bj_parsed = parse_spine38_binary(bj_raw)
    bj_b0 = bj_parsed["bones"][0]
    print("bj_01 root before:", bj_b0)

    # Guard against double-shifting if run twice
    if abs(b0["x"]) < 100 and abs(b0["y"]) < 100:
        new_main_raw = patch_binary_root_transform(main_raw, main_parsed, dx=SHIFT_X, dy=SHIFT_Y)
        main_skel_p.write_bytes(new_main_raw)
        print("Patched MAIN root ->", parse_spine38_binary(new_main_raw)["bones"][0])
    else:
        print("MAIN root already shifted, skipping shift.")

    if bj_b0["x"] > 0:
        bj_dx = SHIFT_X / BJ01_RATIO
        bj_dy = SHIFT_Y / BJ01_RATIO
        new_bj_raw = patch_binary_root_transform(bj_raw, bj_parsed, dx=bj_dx, dy=bj_dy)
        bj_skel_p.write_bytes(new_bj_raw)
        print("Patched bj_01 root ->", parse_spine38_binary(new_bj_raw)["bones"][0])
    else:
        print("bj_01 root already shifted, skipping shift.")

    # 1. Center bg_static.skel.json and optimize bg_4301_heling_s2.png losslessly
    bg_skel_p = SKIN_DIR / "submodels" / "bg_static" / "bg_static.skel.json"
    bg_skel = json.loads(bg_skel_p.read_text(encoding="utf-8"))
    bg_skel["skeleton"]["x"] = -2125.0
    bg_skel["skeleton"]["y"] = -1416.67
    for b in bg_skel["bones"]:
        if b["name"] == "bg_root":
            b["x"] = 0.0
            b["y"] = 0.0
    write_json(bg_skel_p, bg_skel)
    print("Centered bg_static.skel.json at (0, 0)")

    bg_png_p = SKIN_DIR / "submodels" / "bg_static" / "bg_4301_heling_s2.png"
    old_bg_sz = bg_png_p.stat().st_size
    with Image.open(bg_png_p) as im:
        im.save(bg_png_p, "PNG", optimize=True)
    print(f"bg_4301_heling_s2.png lossless optimize: {old_bg_sz/1024/1024:.2f}MB -> {bg_png_p.stat().st_size/1024/1024:.2f}MB")

    # 2. Repack fx_heling_s2_back & fx_heling_s2_front into compact 1-page atlases
    if TEMP_SEQ.exists():
        shutil.rmtree(TEMP_SEQ)

    back_scale = 0.42
    back_frames = prepare_slim_frames(SEQ_DIR / "idle_back" / "normal", TEMP_SEQ / "back_normal", scale=back_scale, step=2, alpha_thresh=0)
    back_dir = SKIN_DIR / "submodels" / "fx_heling_s2_back"
    for old_png in back_dir.glob("*.png"):
        old_png.unlink()
    back_res = pack_fx_submodel(
        output_dir=back_dir,
        model_name="fx_heling_s2_back",
        model_id="4301_heling_s2_fx_back",
        sequences=[AnimSequenceSpec(name="idle", fps=6.0, loop=True, normal_frames=back_frames, motion_group="idle")],
        root_x=0.0,
        root_y=0.0,
        root_scale_x=round(ORIG_FX_SCALE / back_scale, 6),
        root_scale_y=round(ORIG_FX_SCALE / back_scale, 6),
        scale_factor=NEW_BASE_SCALE,
        max_atlas_size=4096,
        padding=2,
        frame_workers=4,
    )
    print("Repacked fx_heling_s2_back:", back_res)

    front_scale = 0.45
    front_norm_frames = prepare_slim_frames(SEQ_DIR / "idle_front" / "normal", TEMP_SEQ / "front_normal", scale=front_scale, step=2, alpha_thresh=0)
    front_add_frames = prepare_slim_frames(SEQ_DIR / "idle_front" / "add", TEMP_SEQ / "front_add", scale=front_scale, step=2, alpha_thresh=3)
    front_dir = SKIN_DIR / "submodels" / "fx_heling_s2_front"
    for old_png in front_dir.glob("*.png"):
        old_png.unlink()
    front_res = pack_fx_submodel(
        output_dir=front_dir,
        model_name="fx_heling_s2_front",
        model_id="4301_heling_s2_fx_front",
        sequences=[AnimSequenceSpec(name="idle", fps=6.0, loop=True, normal_frames=front_norm_frames, add_frames=front_add_frames, motion_group="idle")],
        root_x=0.0,
        root_y=0.0,
        root_scale_x=round(ORIG_FX_SCALE / front_scale, 6),
        root_scale_y=round(ORIG_FX_SCALE / front_scale, 6),
        scale_factor=NEW_BASE_SCALE,
        max_atlas_size=4096,
        padding=2,
        frame_workers=4,
    )
    print("Repacked fx_heling_s2_front:", front_res)

    # Clean temp frames
    shutil.rmtree(TEMP_SEQ, ignore_errors=True)

    # 3. Synchronize scale_factor & position_x/y=0 across MAIN (all 3 langs) + bg_static + bj_01
    for fn in (".config.json", "config_en.config.json", "config_ja.config.json"):
        p = SKIN_DIR / fn
        cfg = json.loads(p.read_text(encoding="utf-8"))
        opt = cfg.setdefault("options", {})
        opt["scale_factor"] = NEW_BASE_SCALE
        opt["position_x"] = 0.0
        opt["position_y"] = 0.0
        write_json(p, cfg)
        print(f"Synced {fn}: scale_factor={NEW_BASE_SCALE}, pos=(0,0)")

    for rel_sub, sf in [
        ("submodels/bg_static/.config.json", NEW_BASE_SCALE),
        ("submodels/bj_01/.config.json", NEW_BJ01_SCALE),
        ("submodels/fx_heling_s2_back/.config.json", NEW_BASE_SCALE),
        ("submodels/fx_heling_s2_front/.config.json", NEW_BASE_SCALE),
    ]:
        p = SKIN_DIR / rel_sub
        cfg = json.loads(p.read_text(encoding="utf-8"))
        opt = cfg.setdefault("options", {})
        opt["scale_factor"] = sf
        opt["position_x"] = 0.0
        opt["position_y"] = 0.0
        write_json(p, cfg)
        print(f"Synced {rel_sub}: scale_factor={sf}, pos=(0,0)")

    # Print final PNG & VRAM summary
    total_mb = 0.0
    total_vram = 0.0
    print("\n=== FINAL PNG & VRAM FOOTPRINT ===")
    for p in sorted(SKIN_DIR.rglob("*.png")):
        with Image.open(p) as im:
            w, h = im.size
        mb = p.stat().st_size / 1024 / 1024
        vram = w * h * 4 / 1024 / 1024
        total_mb += mb
        total_vram += vram
        print(f"  {mb:6.2f}MB  {w:4d}x{h:<4d}  VRAM={vram:5.1f}MB  {p.relative_to(SKIN_DIR)}")
    print(f"TOTAL PNG: {total_mb:.2f} MB  |  TOTAL VRAM: {total_vram:.1f} MB")


if __name__ == "__main__":
    main()
