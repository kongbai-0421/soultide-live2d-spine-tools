"""Apply targeted fixes for the 3 base-skin (原皮) Spine models flagged in visual review:
  1. 克洛托/原皮: Upgrade main Spine to full Clotho_DefaultDress (92 regions incl. wheelchair + dolls)
     + V4.4 ETC2 clean + shift BJ_01 root (+160, +850) to match official Battle01 composition.
  2. 越一弥心/原皮: Remove wrong white HYPOCRITICAL banner, restore clean configs, move mecha
     SoloUp & Battle01 assets to 待去人补全原皮背景/.
  3. 密丝特/原皮: Remove text-contaminated promo banner, restore clean configs, move Mist SoloUp
     banner to 待去人补全原皮背景/01_单UP宽屏场景_优先去人/ for top-left text erasure (and foot-to-floor
     alignment once clean BG is ready).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
SCRIPTS_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本")
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from batch_spine_builder import parse_spine38_binary, shift_binary_root_xy
from soultide_common import CDN_ROOT, load_ab, write_json

SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
UNPACK_ROOT = Path(r"E:\A灵魂潮汐\spine背景\原皮立绘与背景解包")
INPAINT_ROOT = Path(r"E:\A灵魂潮汐\spine背景\待去人补全原皮背景")


def remove_bg_from_orig(char_name: str) -> list[str]:
    skin_dir = SPINE_ROOT / char_name / "原皮"
    sub_dir = skin_dir / "submodels"
    if sub_dir.exists():
        shutil.rmtree(sub_dir)
    updated = []
    for cfg_name in (".config.json", "config_en.config.json", "config_ja.config.json"):
        cfg_p = skin_dir / cfg_name
        if not cfg_p.is_file():
            continue
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
        motions = cfg.get("motions", {})
        for item in motions.get("start", []):
            item.pop("command", None)
        motions.pop("reload_bg", None)
        write_json(cfg_p, cfg)
        updated.append(cfg_name)
    return updated


def fix_clotho() -> dict:
    skin_dir = SPINE_ROOT / "克洛托" / "原皮"
    # 1. Extract Clotho_DefaultDress from 23_spine/ui/batch1.ab (complete 92 regions incl. wheelchair & dolls!)
    uienv = load_ab(CDN_ROOT / "23_spine/ui/batch1.ab")
    for k, pptr in sorted((uienv.container or {}).items(), key=lambda x: x[0]):
        kl = k.lower()
        if "clotho_defaultdress/clotho_defaultdress." in kl:
            if kl.endswith(".png"):
                pptr.read().image.convert("RGBA").save(skin_dir / "Clotho_DefaultDress.png", "PNG")
            elif kl.endswith(".atlas.txt"):
                raw = pptr.read().m_Script
                b = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else bytes(raw)
                (skin_dir / "Clotho_DefaultDress.atlas.txt").write_bytes(b)
            elif kl.endswith(".skel.bytes"):
                raw = pptr.read().m_Script
                b = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else bytes(raw)
                (skin_dir / "Clotho_DefaultDress.skel.json").write_bytes(b)

    # Remove old BattleHead skeleton/atlas/png files cleanly
    for old_name in (
        "Clotho_Dress_01_BattleHead.skel.json",
        "Clotho_Dress_01_BattleHead.atlas.txt",
        "Clotho_Dress_01_BattleHead.png",
    ):
        op = skin_dir / old_name
        if op.is_file():
            op.unlink()

    # 2. Shift BJ_01 binary root bone from fresh unpacked source by (dx=+160, dy=+850) so sword sister
    # sits directly above Clotho's wheelchair matching official Battle01 composition!
    bj1_src = UNPACK_ROOT / "04_特殊原皮背景素材" / "克洛托_Clotho_DefaultDress_BJ_01_04" / "Clotho_DefaultDress_BJ_01.skel.bytes"
    raw_bj1 = bj1_src.read_bytes()
    parsed_bj1 = parse_spine38_binary(raw_bj1)
    shifted_bj1 = shift_binary_root_xy(raw_bj1, parsed_bj1, dx=160.0, dy=850.0)
    (skin_dir / "submodels" / "bj_01" / "Clotho_DefaultDress_BJ_01.skel.json").write_bytes(shifted_bj1)

    # 3. Update all 3 config files to point to Clotho_DefaultDress and valid anims (idle, greet1, greet2)
    submodel_cmd = (
        "add_submodel submodels/bj_02/.config.json -3; "
        "add_submodel submodels/bj_03/.config.json -2; "
        "add_submodel submodels/bj_01/.config.json -1; "
        "add_submodel submodels/bj_04/.config.json 1"
    )
    updated = []
    for cfg_name in (".config.json", "config_en.config.json", "config_ja.config.json"):
        cfg_p = skin_dir / cfg_name
        if not cfg_p.is_file():
            continue
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
        cfg["skeleton"] = "Clotho_DefaultDress.skel.json"
        cfg["atlases"] = [
            {
                "atlas": "Clotho_DefaultDress.atlas.txt",
                "tex_names": ["Clotho_DefaultDress"],
                "textures": ["Clotho_DefaultDress.png"],
            }
        ]
        motions = cfg.get("motions", {})
        for item in motions.get("start", []):
            item["file"] = "idle"
            item["command"] = submodel_cmd
        motions["reload_bg"] = [{"name": "reload_submodels", "file": "idle", "command": submodel_cmd}]
        # Keep battle/action menu valid with Clotho_DefaultDress's actual animations (greet1, greet2)
        for mkey in list(motions.keys()):
            if mkey in ("战斗与动作", "Battle & Actions", "バトル＆アクション"):
                old_items = motions[mkey]
                new_items = []
                for idx, an in enumerate(("greet1", "greet2")):
                    base = dict(old_items[idx]) if idx < len(old_items) else {}
                    base["name"] = f"anim_{an}"
                    base["file"] = an
                    base.setdefault("fade_in", 100)
                    base.setdefault("fade_out", 100)
                    new_items.append(base)
                motions[mkey] = new_items
        write_json(cfg_p, cfg)
        updated.append(cfg_name)

    # 4. Run V4.4 ETC2 edge cleanup on 克洛托 (covers new Clotho_DefaultDress.png & BJ_01..04)
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "spine_etc2_clean_v3.py"), "--doll", "克洛托", "--workers", "4"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ETC2 clean failed on 克洛托:\n{proc.stdout}\n{proc.stderr}")

    return {"char": "克洛托", "updated_configs": updated, "bj1_shift": [160.0, 850.0]}


def update_inpaint_folder() -> dict:
    dir_solo = INPAINT_ROOT / "01_单UP宽屏场景_优先去人"
    dir_b01 = INPAINT_ROOT / "02_其余原皮立绘_Battle01"
    dir_solo.mkdir(parents=True, exist_ok=True)
    dir_b01.mkdir(parents=True, exist_ok=True)

    # 1. Add Mist promo banner (only needs top-left text removed)
    mist_src = UNPACK_ROOT / "03_单UP卡池宽屏场景_SoloUp" / "纯背景分层" / "密丝特_mist_lotteryui_doll_soloup_28_mist_01.png"
    shutil.copy2(mist_src, dir_solo / "密丝特_mist_SoloUp_1700x750_仅需去左上文字.png")

    # 2. Add EtsukazuMiko mecha banner from lotteryui/_batch2.ab (1330x750) + Battle01
    b2 = load_ab(CDN_ROOT / "05_images/maincity/lotteryui/_batch2.ab")
    for k, pptr in (b2.container or {}).items():
        if "lotteryui_doll_soloup_29_etsukazumiko_02.png" in k.lower():
            pptr.read().image.convert("RGBA").save(dir_solo / "越一弥心_etsukazumiko_SoloUp_1330x750_机甲合图.png", "PNG")
            break
    et_b01 = UNPACK_ROOT / "01_原皮完整立绘_Battle01" / "越一弥心_etsukazumiko_Dress_01_Battle01.png"
    if et_b01.is_file():
        shutil.copy2(et_b01, dir_b01 / "越一弥心_etsukazumiko_Battle01.png")

    # Regenerate 清单与说明.txt accurately
    solo_files = sorted(p.name for p in dir_solo.glob("*.png"))
    b01_files = sorted(p.name for p in dir_b01.glob("*.png"))
    readme = [
        "=== 待去人/去字补全的原皮背景素材清单 ===",
        "",
        "说明：",
        "- 当前已完成「零修图直挂」的 5 位原皮 Spine：",
        "  1) 克洛托/原皮（完整轮椅版 Clotho_DefaultDress + 4 套动态背景 Spine BJ_01..04 + 位置校准）",
        "  2) 天音祈/原皮（1700x750 暗星日蚀纯背景）",
        "  3) 克拉丽丝/原皮（1700x750 蓝光时钟漩涡纯背景）",
        "  4) 米迦/原皮（1700x750 烈焰金字塔合成纯背景）",
        "  5) 笃妲/原皮（1700x750 暗紫宫殿纯背景）",
        "- 密丝特：原单 UP 背景左上方自带宣传文字且需下调背景高度以对齐露台地板，已撤下并放入 01 目录（仅需擦除左上角文字，无需去人）。",
        "- 越一弥心：原单 UP 01 为黑白文字涂鸦底纹并非立绘背景，已撤下并将机甲合图（1330x750）与原皮立绘分别放入 01 / 02 目录。",
        "- 月野未夜的孤儿 S1_Background 经确认是皮肤背景已跳过，月野未夜原皮单 UP 图保留在 01 目录。",
        "- 建议处理完成后保持 <中文角色名>_<slug> 前缀存回，我可一键批量挂入对应原皮 Spine 并微调人物与地面/场景的对齐位置。",
        "",
        f"--- 01_单UP宽屏场景_优先去人（共 {len(solo_files)} 张） ---",
        *[f"  {i+1:02d}. {fn}" for i, fn in enumerate(solo_files)],
        "",
        f"--- 02_其余原皮立绘_Battle01（共 {len(b01_files)} 张，优先 99_origin 无和谐原版） ---",
        *[f"  {i+1:02d}. {fn}" for i, fn in enumerate(b01_files)],
        "",
    ]
    (INPAINT_ROOT / "清单与说明.txt").write_text("\n".join(readme), encoding="utf-8")
    return {"solo_count": len(solo_files), "b01_count": len(b01_files)}


def main() -> None:
    r_cl = fix_clotho()
    print("[FIX] 克洛托/原皮 OK:", r_cl)
    r_et = remove_bg_from_orig("越一弥心")
    print("[FIX] 越一弥心/原皮 removed wrong bg:", r_et)
    r_mi = remove_bg_from_orig("密丝特")
    print("[FIX] 密丝特/原皮 removed text-baked bg:", r_mi)
    r_in = update_inpaint_folder()
    print("[FIX] Inpainting folder updated:", r_in)

    # Update report json
    rep_p = SCRIPTS_DIR / "orig_spine_bg_mount_report.json"
    rep = json.loads(rep_p.read_text(encoding="utf-8"))
    rep["mounted"] = [m for m in rep["mounted"] if m["char"] not in ("越一弥心", "密丝特")]
    for m in rep["mounted"]:
        if m["char"] == "克洛托":
            m["mode"] = "Clotho_DefaultDress (92 regions incl. wheelchair+dolls) + 4x BJ_01..04 (BJ_01 shifted +160,+850) + V4.4 ETC2 cleaned"
    rep["removed_and_moved_to_inpaint"] = ["越一弥心", "密丝特"]
    rep["inpainting_folder"] = {"inpaint_root": str(INPAINT_ROOT), **r_in}
    write_json(rep_p, rep)


if __name__ == "__main__":
    main()
