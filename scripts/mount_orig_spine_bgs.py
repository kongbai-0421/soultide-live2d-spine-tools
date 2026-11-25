"""Mount zero-inpainting official backgrounds onto base-skin (原皮) Spine models,
and organize character-baked backgrounds into a dedicated folder for image-editing inpainting.

Zero-inpainting direct mounts (7 dolls; 月野未夜 S1 orphan skipped per user):
  1. 克洛托/原皮: 4 native dynamic Spine submodels Clotho_DefaultDress_BJ_01..04
  2. 天音祈/原皮: bg_static (1700x750 SoloUp pure BG)
  3. 密丝特/原皮: bg_static (1700x750 SoloUp pure BG)
  4. 越一弥心/原皮: bg_static (1700x750 SoloUp pure BG)
  5. 克拉丽丝/原皮: bg_static (1700x750 SoloUp pure BG)
  6. 米迦/原皮: bg_static (1700x750 composite of micha_solo_bg + 02 ember + 03 flame ring)
  7. 笃妲/原皮: bg_static (1700x750 SoloUp pure BG)

Inpainting workspace created:
  E:\\A灵魂潮汐\\spine背景\\待去人补全原皮背景\\
    01_单UP宽屏场景_优先去人/   (25 dolls' 1700x750 SoloUp character+scene banners)
    02_其余原皮立绘_Battle01/   (22 dolls without SoloUp or direct-mount BG)
    清单与说明.txt
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
SCRIPTS_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本")
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from soultide_common import write_json

SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
UNPACK_ROOT = Path(r"E:\A灵魂潮汐\spine背景\原皮立绘与背景解包")
AUDIT_SPINE_DIR = TOOLS_DIR / "_doll_audit_previews" / "spine"
INPAINT_ROOT = Path(r"E:\A灵魂潮汐\spine背景\待去人补全原皮背景")


def _update_three_configs(skin_dir: Path, submodel_cmd: str, idle_anim: str = "idle") -> list[str]:
    updated = []
    for cfg_name in (".config.json", "config_en.config.json", "config_ja.config.json"):
        cfg_p = skin_dir / cfg_name
        if not cfg_p.is_file():
            continue
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
        motions = cfg.setdefault("motions", {})
        starts = motions.get("start", [])
        if not starts:
            starts = [{"name": "start_0", "file": idle_anim, "fade_in": 100, "fade_out": 100}]
            motions["start"] = starts
        for item in starts:
            item["command"] = submodel_cmd
        motions["reload_bg"] = [
            {
                "name": "reload_submodels",
                "file": idle_anim,
                "command": submodel_cmd,
            }
        ]
        write_json(cfg_p, cfg)
        updated.append(cfg_name)
    return updated


def _read_live_main_bbox(char_name: str) -> dict[str, float]:
    matches = sorted(AUDIT_SPINE_DIR.glob(f"*_{char_name}__原皮.meta.json"))
    if not matches:
        raise FileNotFoundError(f"Missing live audit meta for {char_name}/原皮 in {AUDIT_SPINE_DIR}")
    meta = json.loads(matches[0].read_text(encoding="utf-8-sig"))
    return meta["main_bbox"]


def _compose_micha_bg(pure_dir: Path) -> Image.Image:
    """Composite micha_solo_bg (1700x750) + micha_solo_bg_02 (ember) + micha_solo_bg_03 (flame ring)."""
    base = Image.open(pure_dir / "米迦_micha_micha_solo_bg.png").convert("RGBA")
    ov2 = Image.open(pure_dir / "米迦_micha_micha_solo_bg_02.png").convert("RGBA")
    ov3 = Image.open(pure_dir / "米迦_micha_micha_solo_bg_03.png").convert("RGBA")
    cw, ch = base.size  # 1700, 750

    # Relative offsets from LotteryUI_Doll_SoloUp_48_Micha.prefab centered on character (173, 17):
    # Image_02: anchoredPos=(222,-19), scale=1.20 -> rel=(+49, -36)
    # Image_03: anchoredPos=(100,+47), scale=1.20 -> rel=(-73, +30)
    # Keep scale slightly gentle (1.0) so full flame ring fits cleanly within 750px height without hard top/bottom crop.
    for ov, dx, dy, sc in ((ov2, 40, -20, 1.0), (ov3, -55, 18, 1.0)):
        nw, nh = int(round(ov.width * sc)), int(round(ov.height * sc))
        if (nw, nh) != ov.size:
            ov = ov.resize((nw, nh), Image.Resampling.LANCZOS)
        # Unity y-up -> PIL y-down
        px = int(round(cw / 2.0 + dx - nw / 2.0))
        py = int(round(ch / 2.0 - dy - nh / 2.0))
        layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        layer.paste(ov, (px, py))
        base = Image.alpha_composite(base, layer)

    return base.convert("RGB").convert("RGBA")


def mount_clotho() -> dict[str, Any]:
    skin_dir = SPINE_ROOT / "克洛托" / "原皮"
    cfg = json.loads((skin_dir / ".config.json").read_text(encoding="utf-8-sig"))
    base_scale = float(cfg["options"]["scale_factor"])
    model_id = str(cfg["options"]["id"])

    src_dir = UNPACK_ROOT / "04_特殊原皮背景素材" / "克洛托_Clotho_DefaultDress_BJ_01_04"
    # Official z-order verified against Clotho Battle01_ref:
    # bj_02 (dark hooded sister + gear at far back -3), bj_03 (golden wheel + white cloak -2),
    # bj_01 (sword sister + purple flame -1), bj_04 (animated fate threads +1)
    specs = [
        ("bj_01", "Clotho_DefaultDress_BJ_01", "idle", -1),
        ("bj_02", "Clotho_DefaultDress_BJ_02", "animation", -3),
        ("bj_03", "Clotho_DefaultDress_BJ_03", "animation", -2),
        ("bj_04", "Clotho_DefaultDress_BJ_04", "animation", 1),
    ]
    sub_cmds: list[str] = []
    for sub_name, stem, anim, z_ord in specs:
        sdir = skin_dir / "submodels" / sub_name
        if sdir.exists():
            shutil.rmtree(sdir)
        sdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_dir / f"{stem}.skel.bytes", sdir / f"{stem}.skel.json")
        shutil.copy2(src_dir / f"{stem}.atlas.txt", sdir / f"{stem}.atlas.txt")
        shutil.copy2(src_dir / f"{stem}.png", sdir / f"{stem}.png")

        bj_cfg = {
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
            "motions": {
                "idle": [{"name": anim, "file": anim, "file_loop": True}]
            },
            "options": {
                "id": f"{model_id}_{sub_name}",
                "scale_factor": base_scale,
                "position_x": 0.0,
                "position_y": 0.0,
                "tex_type": 0,
                "edge_padding": False,
            },
            "skeleton": f"{stem}.skel.json",
            "atlases": [
                {
                    "atlas": f"{stem}.atlas.txt",
                    "tex_names": [stem],
                    "textures": [f"{stem}.png"],
                }
            ],
        }
        write_json(sdir / ".config.json", bj_cfg)
        sub_cmds.append(f"add_submodel submodels/{sub_name}/.config.json {z_ord}")

    # Sort commands by z-order ascending for readability
    ordered_cmds = [
        f"add_submodel submodels/{sub_name}/.config.json {z_ord}"
        for sub_name, _, _, z_ord in sorted(specs, key=lambda x: x[3])
    ]
    submodel_cmd = "; ".join(ordered_cmds)
    updated = _update_three_configs(skin_dir, submodel_cmd, idle_anim="idle")

    # Run V4.4 ETC2 edge cleanup on 克洛托/原皮/submodels/bj_01..04 (PMA Spine atlases)
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "spine_etc2_clean_v3.py"),
        "--doll",
        "克洛托",
        "--workers",
        "4",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ETC2 clean failed on 克洛托:\n{proc.stdout}\n{proc.stderr}")

    return {
        "char": "克洛托",
        "mode": "4x dynamic Spine submodels (BJ_01..04) + V4.4 ETC2 cleaned",
        "submodel_cmd": submodel_cmd,
        "updated_configs": updated,
    }


def mount_static_soloup(char_name: str, slug: str, img: Image.Image) -> dict[str, Any]:
    skin_dir = SPINE_ROOT / char_name / "原皮"
    cfg = json.loads((skin_dir / ".config.json").read_text(encoding="utf-8-sig"))
    base_scale = float(cfg["options"]["scale_factor"])
    model_id = str(cfg["options"]["id"])

    mb = _read_live_main_bbox(char_name)
    cw = max(100.0, mb["x1"] - mb["x0"])
    ch = max(100.0, mb["y1"] - mb["y0"])
    cx = (mb["x0"] + mb["x1"]) / 2.0
    cy = (mb["y0"] + mb["y1"]) / 2.0

    iw, ih = img.size
    # Ensure character fits comfortably inside BG (out_of_bg_count == 0) with balanced framing
    scale_h = (ch * 1.28) / float(ih)
    scale_w = (cw * 1.18) / float(iw)
    bg_scale = round(max(scale_h, scale_w), 6)

    world_w = round(iw * bg_scale, 2)
    world_h = round(ih * bg_scale, 2)
    world_x = round(cx - world_w / 2.0, 2)
    world_y = round(cy - world_h / 2.0, 2)

    sdir = skin_dir / "submodels" / "bg_static"
    if sdir.exists():
        shutil.rmtree(sdir)
    sdir.mkdir(parents=True, exist_ok=True)

    tex_stem = f"bg_orig_{slug}"
    tex_png = f"{tex_stem}.png"
    img.convert("RGBA").save(sdir / tex_png, "PNG")

    atlas_txt = (
        f"\n{tex_png}\n"
        f"size: {iw},{ih}\n"
        f"format: RGBA8888\n"
        f"filter: Linear,Linear\n"
        f"repeat: none\n"
        f"{tex_stem}\n"
        f"  rotate: false\n"
        f"  xy: 0, 0\n"
        f"  size: {iw}, {ih}\n"
        f"  orig: {iw}, {ih}\n"
        f"  offset: 0, 0\n"
        f"  index: -1\n"
    )
    (sdir / "bg_static.atlas.txt").write_text(atlas_txt, encoding="utf-8")

    skel_json = {
        "skeleton": {
            "hash": tex_stem,
            "spine": "3.8.79",
            "x": world_x,
            "y": world_y,
            "width": world_w,
            "height": world_h,
        },
        "bones": [
            {"name": "root"},
            {
                "name": "bg_root",
                "parent": "root",
                "x": round(cx, 4),
                "y": round(cy, 4),
                "scaleX": bg_scale,
                "scaleY": bg_scale,
            },
        ],
        "slots": [
            {
                "name": "bg_slot",
                "bone": "bg_root",
                "attachment": tex_stem,
            }
        ],
        "skins": [
            {
                "name": "default",
                "attachments": {
                    "bg_slot": {
                        tex_stem: {
                            "x": 0.0,
                            "y": 0.0,
                            "width": iw,
                            "height": ih,
                        }
                    }
                },
            }
        ],
        "animations": {"idle": {}},
    }
    write_json(sdir / "bg_static.skel.json", skel_json)

    bg_cfg = {
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
        "motions": {
            "idle": [{"name": "idle", "file": "idle", "file_loop": True}]
        },
        "options": {
            "id": f"{model_id}_bg_static",
            "scale_factor": base_scale,
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 0,
            "edge_padding": False,
        },
        "skeleton": "bg_static.skel.json",
        "atlases": [
            {
                "atlas": "bg_static.atlas.txt",
                "tex_names": [tex_stem],
                "textures": [tex_png],
            }
        ],
    }
    write_json(sdir / ".config.json", bg_cfg)

    submodel_cmd = "add_submodel submodels/bg_static/.config.json -3"
    updated = _update_three_configs(skin_dir, submodel_cmd, idle_anim="idle")
    return {
        "char": char_name,
        "slug": slug,
        "mode": "bg_static (1700x750 Straight Alpha)",
        "bg_scale": bg_scale,
        "bg_center": [round(cx, 1), round(cy, 1)],
        "bg_rect": [world_x, world_y, round(world_x + world_w, 2), round(world_y + world_h, 2)],
        "main_bbox": mb,
        "updated_configs": updated,
    }


def prepare_inpainting_folder() -> dict[str, Any]:
    manifest = json.loads((UNPACK_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if INPAINT_ROOT.exists():
        shutil.rmtree(INPAINT_ROOT)
    dir_solo = INPAINT_ROOT / "01_单UP宽屏场景_优先去人"
    dir_b01 = INPAINT_ROOT / "02_其余原皮立绘_Battle01"
    dir_solo.mkdir(parents=True, exist_ok=True)
    dir_b01.mkdir(parents=True, exist_ok=True)

    # Already directly mounted with pure BG (no inpainting needed!)
    pure_mounted_slugs = {"amaneinori", "mist", "etsukazumiko", "clarice", "micha", "truda"}

    solo_list: list[str] = []
    b01_list: list[str] = []
    for d in manifest["dolls"]:
        slug = d["slug"]
        cn = d["cn_name"]
        if slug in pure_mounted_slugs:
            continue
        if d["soloup_merged"]:
            # Pick largest / primary merged SoloUp banner (note: clotho also has one in case user wants static BG behind BJ_01..04)
            entry = d["soloup_merged"][0]
            src = UNPACK_ROOT / entry["file"]
            tag = "_含动态BJ已直挂可选" if slug == "clotho" else ""
            dst = dir_solo / f"{cn}_{slug}_SoloUp_1700x750{tag}.png"
            shutil.copy2(src, dst)
            solo_list.append(f"{cn} ({slug}) -> {dst.name}")
        else:
            entry = d["battle01"]
            if entry:
                src = UNPACK_ROOT / entry["file"]
                tag = "_99origin" if entry.get("uncensored_99origin") else ""
                dst = dir_b01 / f"{cn}_{slug}_Battle01{tag}.png"
                shutil.copy2(src, dst)
                b01_list.append(f"{cn} ({slug}, {entry['size'][0]}x{entry['size'][1]}) -> {dst.name}")

    readme = [
        "=== 待去人补全的原皮背景素材清单 ===",
        "",
        "说明：",
        "- 已完成「零修图直挂」的 6 位纯背景角色（天音祈、密丝特、越一弥心、克拉丽丝、米迦、笃妲）已自动排除，无需去人。",
        "- 克洛托原皮已直挂官方 4 套动态 Spine 背景（BJ_01..04）；其 1700x750 单 UP 宽屏合图仍保留在 01 目录（标注 _含动态BJ已直挂可选）以备你想额外叠静态大背景。",
        "- 月野未夜的孤儿 S1_Background 经确认是皮肤背景已跳过，月野未夜的原皮单 UP 宽屏图已放在 01 目录。",
        "- 建议处理完去人补全后，保持原文件名（或保留 <中文名>_<slug> 前缀）存回，我可一键批量挂入对应原皮 Spine 的 submodels/bg_static。",
        "",
        f"--- 01_单UP宽屏场景_优先去人（共 {len(solo_list)} 位，全部为 1700x750 宽屏官方场景，注：爱莉莎/蕖灵右侧带少量宣传文字一并擦除即可） ---",
        *[f"  {i+1:02d}. {line}" for i, line in enumerate(solo_list)],
        "",
        f"--- 02_其余原皮立绘_Battle01（共 {len(b01_list)} 位，无单 UP 宽屏图；优先取 99_origin 无和谐原版，部分早期角色立绘为纯人物无场景底座，可按需挑选） ---",
        *[f"  {i+1:02d}. {line}" for i, line in enumerate(b01_list)],
        "",
    ]
    (INPAINT_ROOT / "清单与说明.txt").write_text("\n".join(readme), encoding="utf-8")
    return {
        "inpaint_root": str(INPAINT_ROOT),
        "soloup_count": len(solo_list),
        "battle01_count": len(b01_list),
    }


def main() -> None:
    results = []
    # 1. Clotho 4x dynamic Spine submodels
    results.append(mount_clotho())
    print("[MOUNT] OK 克洛托/原皮 (BJ_01..04 + V4.4 cleaned)")

    # 2. 6 SoloUp pure BG static submodels
    pure_dir = UNPACK_ROOT / "03_单UP卡池宽屏场景_SoloUp" / "纯背景分层"
    static_jobs = [
        ("天音祈", "amaneinori", Image.open(pure_dir / "天音祈_amaneinori_lotteryui_doll_soloup_18_amaneinori_01.png")),
        ("密丝特", "mist", Image.open(pure_dir / "密丝特_mist_lotteryui_doll_soloup_28_mist_01.png")),
        ("越一弥心", "etsukazumiko", Image.open(pure_dir / "越一弥心_etsukazumiko_lotteryui_doll_soloup_29_etsukazumiko_01.png")),
        ("克拉丽丝", "clarice", Image.open(pure_dir / "克拉丽丝_clarice_fx_ui_clarice_bg.png")),
        ("米迦", "micha", _compose_micha_bg(pure_dir)),
        ("笃妲", "truda", Image.open(pure_dir / "笃妲_truda_truda_soloup_bg_01.png")),
    ]
    for ch, slug, img in static_jobs:
        res = mount_static_soloup(ch, slug, img)
        results.append(res)
        print(f"[MOUNT] OK {ch}/原皮 (bg_scale={res['bg_scale']}, center={res['bg_center']})")

    # 3. Organize inpainting folder
    inp_res = prepare_inpainting_folder()
    print(f"[INPAINT] OK -> {inp_res}")

    out_rep = SCRIPTS_DIR / "orig_spine_bg_mount_report.json"
    write_json(out_rep, {"mounted": results, "inpainting_folder": inp_res})
    print(f"REPORT -> {out_rep}")


if __name__ == "__main__":
    main()
