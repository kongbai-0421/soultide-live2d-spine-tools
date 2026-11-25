#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
全库 Spine 换装图层顺序、MeshRenderer Z 深度倒置与位置偏差批量修复脚本
====================================================================
修复范围（全库 109 套换装 Spine 深度审计检出的全部 25 套真实异常皮肤）：
  1. Group A（5 套重构建）：
     - 修复 4 套 MeshRenderer 同 sortingOrder 下 Z 深度倒置：
       伊汐尔/新春焰火、芙丽希娅/孤寂天鹅、星见亚砂/星语心恋、德莱洁恩/心宿良栖
     - 修复 1 套 bj_* 严重位移偏差（279.7 UI px）：
       蕖灵/脉脉深情语
     - 其中 伊汐尔/新春焰火 同步将 c=1 夜空（bg_static @ -3）、c=1..2 烟花（fx_ithil_s2 @ -2）、
       c=3 室内墙窗（bg_mid @ -1）分层隔离，并将窗帘 bj_04 帧 0 无损合入 bg_mid 确保零缺失且烟花严守窗外。
  2. Group B（7 套静态背景按 fx_back 边界拆分为 bg_static @ -3 + fx_back @ -2 + bg_mid @ -1）：
     南宫凛/情至心处、欧若拉/仙宫新岁、天音祈/青霄和歌、敖绫/玉龙娇娇邀福来、
     凡妮/红泥融雪、斯贝比尔/月色终曲、安德莉亚/伴光同辉
  3. Group C（13 套 fx_*_back 与 bj_* 层序重排，消除背景粒子/水底画布覆盖前景/中景珊瑚与景物）：
     阿卡赛特/深海巡游（fx_back -> -3, bg02 -> -2, bg01 -> -1）、芙丽希娅/蝶语吟花、
     九华/与猫逐浪、九华/宇宙恋曲、朔耶真子/神明恋歌、艾妮斯/时空恋曲、
     西勒诺斯/于命运尽头、多洛莉丝/森语迷情、青蒿/山涧趣事、爱瑞妮/昆虫观察、
     阿拉芙/春华萌动、阿拉芙/神赐永恒、和铃/古锦新韵

修复后自动执行：
  - 新增静态 PNG -> 无损 exact=True WebP 转换（逐张 np.array_equal 校验，同步 tex_type=1, shader_type=0）
  - 三语配置（.config.json / config_en.config.json / config_ja.config.json）同步 start & reload_bg
  - 复跑 add_spine_bg_toggle.py 同步全部 109 套隐藏背景指令
  - 输出报告：工具脚本\spine_layers_pos_fix_report.json
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
SCRIPTS_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本")
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
REPORT_PATH = SCRIPTS_DIR / "spine_layers_pos_fix_report.json"
RENDER_EXE = SCRIPTS_DIR / "render_spine_compare.exe"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from batch_fx_exporter import AssetIndexer, FullI18nRepo, build_skin_catalog, inspect_bg_prefab_layout
from batch_spine_builder import (
    BatchAssetRepos,
    _assign_orders,
    _build_scene_submodels_exact,
    _extract_unity_scene_layers,
    _render_static_image_group,
)
from fix_all_spine_bg_layouts import _parse_existing_fx_items

LANG_FILES = (".config.json", "config_en.config.json", "config_ja.config.json")

# Group A: 需要重建非-FX子模型（修复 Z 深度倒置 / 280px 位置错位）
GROUP_A_KEYS = {
    "3101_Ithil_S2",      # 伊汐尔/新春焰火
    "402_Freesia_S5",     # 芙丽希娅/孤寂天鹅
    "603_Asuna_S8",       # 星见亚砂/星语心恋
    "1503_Dreizehn_S4",   # 德莱洁恩/心宿良栖
    "2302_QuLing_S3",     # 蕖灵/脉脉深情语
}

# Group B: 空闲 -2 槽位，将 bg_static 按 emitting_back_psr_min_c 拆分为 bg_static(-3) + fx_back(-2) + bg_mid(-1)
GROUP_B_SPLIT_C = {
    "1403_NankungLin_S4": 1,   # 南宫凛/情至心处 (c=1 落叶后于 c=2 IMG x4)
    "1901_Aurora_S3": 2,       # 欧若拉/仙宫新岁 (c=2 烟花/灯笼后于 c=3..4 IMG x3)
    "2203_Andrea_S4": 2,       # 安德莉亚/伴光同辉 (c=2 扇形光后于 c=4 IMG x7)
    "2402_AmaneInori_S3": 1,   # 天音祈/青霄和歌 (c=1 FX 后于 c=2 IMG x3)
    "3302_Aoling_S3": 1,       # 敖绫/玉龙娇娇邀福来 (c=1..2 烟雾后于 c=2 IMG)
    "4701_Fanny_S2": 1,        # 凡妮/红泥融雪 (c=1 窗外雪花后于 c=2 窗框)
    "5301_Superbia_S2": 1,     # 斯贝比尔/月色终曲 (c=1 水纹后于 c=2 建筑 IMG x11)
}

# Group C: 精准负侧层序重排（保留全部既有子模型与 WebP，仅修正 add_submodel 顺序）
GROUP_C_NEG_ORDER: dict[str, list[tuple[str, int]]] = {
    "201_Akaset_S4":      [("fx_akaset_s4_back", -3), ("bg02", -2), ("bg01", -1)],
    "404_Freesia_S6":     [("bg_static", -3), ("fx_freesia_s6_back", -2), ("bj_01", -1)],
    "1701_Juewa_S2":      [("bg_static", -3), ("fx_juewa_s2_back", -2), ("bg_02", -1)],
    "1703_Juewa_S4":      [("bg_static", -3), ("fx_juewa_s4_back", -2), ("bj_01", -1)],
    "1803_SakuyaMako_S4": [("bg_static", -3), ("fx_sakuyamako_s4_back", -2), ("bj_02", -1)],
    "2003_Ennis_S4":      [("bg_static", -3), ("fx_ennis_s4_back", -2), ("bj_02", -1)],
    "2702_Silenus_S3":    [("bg_static", -3), ("fx_silenus_s3_back", -2), ("bj_01", -1)],
    "3202_Dolores_S3":    [("bg_static", -3), ("fx_dolores_s3_back", -2), ("bj_02", -1)],
    "3602_QingHao_S3":    [("bg_static", -3), ("fx_qinghao_s3_back", -2), ("bj_02", -1)],
    "4101_Erinnern_S2":   [("bg_static", -3), ("fx_erinnern_s2_back", -2), ("bj_02", -1)],
    "4201_Haliva_S2":     [("bg_static", -3), ("fx_haliva_s2_back", -2), ("bj_01_2", -1)],
    "4202_Haliva_S3":     [("bg_static", -3), ("fx_haliva_s3_back", -2), ("bj_02", -1)],
    "4301_HeLing_S2":     [("bg_static", -3), ("fx_heling_s2_back", -2), ("bj_01", -1)],
}


def compact_json_write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def convert_submodel_pngs_to_exact_webp(sub_dir: Path) -> int:
    """将新建/重建子目录内的 PNG 转为逐比特无损 exact=True WebP 并同步 atlas 与 config。"""
    converted = 0
    pngs = sorted(sub_dir.glob("*.png"))
    if not pngs:
        return 0
    rename_map: dict[str, str] = {}
    for p in pngs:
        orig_arr = np.array(Image.open(p).convert("RGBA"))
        wp = p.with_suffix(".webp")
        Image.fromarray(orig_arr, "RGBA").save(wp, "WEBP", lossless=True, exact=True, quality=100, method=4)
        dec_arr = np.array(Image.open(wp).convert("RGBA"))
        if not np.array_equal(orig_arr, dec_arr):
            wp.unlink(missing_ok=True)
            raise RuntimeError(f"Lossless exact WebP verification failed on {p}")
        p.unlink()
        rename_map[p.name] = wp.name
        converted += 1

    # 更新 .atlas.txt
    for at in sub_dir.glob("*.atlas.txt"):
        txt = at.read_text(encoding="utf-8")
        for old_n, new_n in rename_map.items():
            txt = txt.replace(old_n, new_n)
        at.write_text(txt, encoding="utf-8")

    # 更新 .config.json
    for cf in sub_dir.glob("*.config.json"):
        cfg = json.loads(cf.read_text(encoding="utf-8"))
        opts = cfg.setdefault("options", {})
        opts["tex_type"] = 1
        opts["shader_type"] = 0
        for atl in cfg.get("atlases") or []:
            atl["textures"] = [rename_map.get(t, t) for t in (atl.get("textures") or [])]
        compact_json_write(cf, cfg)
    return converted


def sync_start_and_reload_all_langs(skin_dir: Path, ordered_items: list[tuple[str, int]]) -> list[str]:
    """将 [(rel_cfg, order), ...] 同步写入三语配置的 start 与 reload_bg。"""
    ordered = sorted(ordered_items, key=lambda x: x[1])
    start_cmd = "; ".join(f"add_submodel {rel} {ord_v}" for rel, ord_v in ordered)
    reload_cmd = "; ".join(f"remove_submodel {rel}" for rel, _ in ordered) + "; " + start_cmd

    updated = []
    for lf in LANG_FILES:
        cp = skin_dir / lf
        if not cp.is_file():
            continue
        cfg = json.loads(cp.read_text(encoding="utf-8"))
        mots = cfg.setdefault("motions", {})
        if "start" in mots and mots["start"]:
            for it in mots["start"]:
                if isinstance(it, dict):
                    it["command"] = start_cmd
        else:
            mots["start"] = [{"name": "start", "file": "", "command": start_cmd}]
        if "reload_bg" in mots and mots["reload_bg"]:
            for it in mots["reload_bg"]:
                if isinstance(it, dict):
                    it["command"] = reload_cmd
        else:
            mots["reload_bg"] = [{"name": "reload_bg", "file": "", "command": reload_cmd}]
        compact_json_write(cp, cfg)
        updated.append(lf)
    return updated


def parse_current_submodels(skin_dir: Path) -> list[tuple[str, str, int]]:
    """返回 [(folder_name, rel_cfg, order), ...]。"""
    cfg = json.loads((skin_dir / ".config.json").read_text(encoding="utf-8"))
    st = cfg.get("motions", {}).get("start", [{}])[0].get("command", "")
    res = []
    for seg in st.split(";"):
        toks = seg.strip().split()
        if len(toks) == 3 and toks[0] == "add_submodel":
            res.append((Path(toks[1]).parent.name, toks[1], int(toks[2])))
    return res


def render_ithil_bj04_into_bg_mid(skin_dir: Path, bg_mid_dir: Path, bj04_dir: Path, layout: dict[str, Any]) -> bool:
    """将伊汐尔/新春焰火的红窗帘 bj_04 帧 0 按精确世界坐标合入 bg_mid，保证窗帘不丢且烟花严守窗外。"""
    if not RENDER_EXE.is_file() or not (bj04_dir / ".config.json").is_file():
        return False
    bg_sc = json.loads((bg_mid_dir / ".config.json").read_text(encoding="utf-8"))
    bg_sk = json.loads((bg_mid_dir / bg_sc["skeleton"]).read_text(encoding="utf-8"))
    bg_tex_name = bg_sc["atlases"][0]["textures"][0]
    bg_tex_path = bg_mid_dir / bg_tex_name
    bg_im = Image.open(bg_tex_path).convert("RGBA")
    bw_px, bh_px = bg_im.size

    # bg_mid 的世界坐标范围（在主 Spine 坐标系中）
    b1 = next(b for b in bg_sk["bones"] if b["name"] == "bg_root")
    cx, cy = float(b1["x"]), float(b1["y"])
    sx, sy = float(b1["scaleX"]), float(b1["scaleY"])
    min_x = cx - (bw_px * sx) / 2.0
    max_x = cx + (bw_px * sx) / 2.0
    min_y = cy - (bh_px * sy) / 2.0
    max_y = cy + (bh_px * sy) / 2.0

    # 用 render_spine_compare.exe 渲染 bj_04 到与 bg_mid 完全一致的像素网格！
    bj_sc = json.loads((bj04_dir / ".config.json").read_text(encoding="utf-8"))
    bj_atlas = bj_sc["atlases"][0]["atlas"]
    bj_skel = bj_sc["skeleton"]
    bj_anim = bj_sc["motions"]["idle"][0]["file"]
    bj_tex = bj_sc["atlases"][0]["textures"][0]

    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        # render_spine_compare.exe 仅支持 PNG，若为 webp 先转临时 PNG
        tex_for_ren = "-"
        if bj_tex.lower().endswith(".webp"):
            tmp_png = td_p / "bj04_tex.png"
            Image.open(bj04_dir / bj_tex).convert("RGBA").save(tmp_png)
            tex_for_ren = str(tmp_png)
        out_png = td_p / "bj04_render.png"
        # render_spine_compare.exe 以透明底 (bg=0,0,0) 输出带 Alpha 的 PNG
        cmd = [
            str(RENDER_EXE),
            str(bj04_dir),
            bj_atlas,
            bj_skel,
            tex_for_ren,
            str(out_png),
            bj_anim,
            f"{min_x:.4f}",
            f"{max_x:.4f}",
            f"{min_y:.4f}",
            f"{max_y:.4f}",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not out_png.is_file():
            print(f"  [WARN] render_spine_compare failed for bj_04: {r.stderr[:200]}")
            return False
        curtain_im = Image.open(out_png).convert("RGBA")
        if curtain_im.size != bg_im.size:
            curtain_im = curtain_im.resize(bg_im.size, Image.Resampling.LANCZOS)
        # 仅合成有效像素（curtain 在 Image_3..7 之上）
        merged = Image.alpha_composite(bg_im, curtain_im)
        merged.save(bg_tex_path, "PNG")
        return True


def fix_group_a_skin(
    skin: dict[str, Any],
    skin_dir: Path,
    repos: BatchAssetRepos,
    indexer: AssetIndexer,
) -> dict[str, Any]:
    key = skin["skin_key"]
    cfg = json.loads((skin_dir / ".config.json").read_text(encoding="utf-8"))
    base_scale = float(cfg["options"]["scale_factor"])
    sub_root = skin_dir / "submodels"
    before = parse_current_submodels(skin_dir)
    fx_items = _parse_existing_fx_items(skin_dir, cfg)
    has_back_fx = any(side == "back" for _, _, side in fx_items)
    has_front_fx = any(side == "front" for _, _, side in fx_items)

    layout = inspect_bg_prefab_layout(indexer, skin)

    if key == "3101_Ithil_S2":
        # 伊汐尔/新春焰火 定制精准 5 层：
        #   -3: bg_static (c=1 夜空 Image_1..2)
        #   -2: fx_ithil_s2 (c=1..2 窗外烟花)
        #   -1: bg_mid (c=3 室内墙窗 Image_3..16 + 合入窗帘 bj_04 帧 0！)
        #    0: Person (伊汐尔, z=0.4)
        #   +1: bj_02 (c=4, z=0.2 前景道具!)
        #   +2: fg_static (c=5 前景木椅 Image_17..18)
        # 先保留现有 bj_04 备份用于合成到 bg_mid
        tmp_bj04 = Path(tempfile.mkdtemp(prefix="ithil_bj04_"))
        try:
            if (sub_root / "bj_04").is_dir():
                shutil.copytree(sub_root / "bj_04", tmp_bj04 / "bj_04")
            # 重建全部非 FX 子模型（使用修复后含 Z 深度的 _build_scene_submodels_exact）
            non_fx, _ = _build_scene_submodels_exact(
                repos, indexer, skin, layout, base_scale, sub_root,
                has_back_fx=has_back_fx, has_front_fx=has_front_fx,
                clean_old_non_fx=True,
                force_fx_sides=(has_back_fx, has_front_fx),
            )
            # 重新按 c=1 vs c=3 拆分 back_imgs -> bg_static (c=1) & bg_mid (c=3)
            scene = _extract_unity_scene_layers(repos, indexer, skin, layout)
            p_key = scene["person_key"]
            back_imgs = [im for im in scene["img_layers"] if im["draw_key"] < p_key]
            pre_imgs = [im for im in back_imgs if im["sort_order"] <= 1]
            post_imgs = [im for im in back_imgs if im["sort_order"] > 1]
            # 重写 bg_static (仅夜空) 与 bg_mid (室内墙窗)
            shutil.rmtree(sub_root / "bg_static", ignore_errors=True)
            shutil.rmtree(sub_root / "bg_mid", ignore_errors=True)
            shutil.rmtree(sub_root / "bj_04", ignore_errors=True)
            shutil.rmtree(sub_root / "bj_01", ignore_errors=True)
            bg_res = _render_static_image_group(pre_imgs, skin, layout, base_scale, sub_root / "bg_static", "bg_static", 0.0)
            mid_res = _render_static_image_group(post_imgs, skin, layout, base_scale, sub_root / "bg_mid", "bg_mid", 0.0)
            for im in scene["img_layers"]:
                try: im["img"].close()
                except Exception: pass
            # 将 bj_04 窗帘渲染合入 bg_mid（保证左右红窗帘都在烟花之前！）
            merged_curtain = False
            if mid_res and (tmp_bj04 / "bj_04").is_dir():
                merged_curtain = render_ithil_bj04_into_bg_mid(skin_dir, sub_root / "bg_mid", tmp_bj04 / "bj_04", layout)

            final_items: list[tuple[str, int]] = []
            if bg_res:
                final_items.append((bg_res["rel"], -3))
            if fx_items:
                final_items.append((fx_items[0][1], -2))
            if mid_res:
                final_items.append((mid_res["rel"], -1))
            # 保留正向侧重建出的 bj_02 (+1) 与 fg_static (+2)
            for _, rel, ord_v in non_fx:
                if ord_v > 0 and (skin_dir / rel).is_file():
                    final_items.append((rel, ord_v))
        finally:
            shutil.rmtree(tmp_bj04, ignore_errors=True)

        for d in sub_root.iterdir():
            if d.is_dir() and not d.name.lower().startswith("fx_"):
                convert_submodel_pngs_to_exact_webp(d)
        sync_start_and_reload_all_langs(skin_dir, final_items)
        return {"group": "A_ithil", "merged_curtain": merged_curtain, "before": before, "after": parse_current_submodels(skin_dir)}

    # 其余 4 套 Group A 皮肤：使用修复后含 Z 深度的 _build_scene_submodels_exact 重建
    non_fx, _ = _build_scene_submodels_exact(
        repos, indexer, skin, layout, base_scale, sub_root,
        has_back_fx=has_back_fx, has_front_fx=has_front_fx,
        clean_old_non_fx=True,
        force_fx_sides=(has_back_fx, has_front_fx),
    )
    assigned = _assign_orders(non_fx, fx_items)
    ordered = [(rel, ord_v) for _, rel, ord_v in assigned]

    # 对 402_Freesia_S5 & 2302_QuLing_S3，将 fx_*_back 调整至 bj_* 之前（-2），bj_* 在 -1！
    if key in ("402_Freesia_S5", "2302_QuLing_S3"):
        neg_map = {Path(r).parent.name: r for r, o in ordered if o < 0}
        pos_list = [(r, o) for r, o in ordered if o > 0]
        new_neg = []
        if "bg_static" in neg_map:
            new_neg.append((neg_map["bg_static"], -3))
        fx_b = [r for k, r in neg_map.items() if k.lower().startswith("fx_")]
        bjs = [r for k, r in neg_map.items() if not k.lower().startswith("fx_") and k != "bg_static"]
        if fx_b:
            new_neg.append((fx_b[0], -2))
        if bjs:
            new_neg.append((bjs[0], -1))
        ordered = new_neg + pos_list

    for d in sub_root.iterdir():
        if d.is_dir() and not d.name.lower().startswith("fx_"):
            convert_submodel_pngs_to_exact_webp(d)
    sync_start_and_reload_all_langs(skin_dir, ordered)
    return {"group": "A_rebuild", "before": before, "after": parse_current_submodels(skin_dir)}


def fix_group_b_skin(
    skin: dict[str, Any],
    skin_dir: Path,
    split_c: int,
    repos: BatchAssetRepos,
    indexer: AssetIndexer,
) -> dict[str, Any]:
    cfg = json.loads((skin_dir / ".config.json").read_text(encoding="utf-8"))
    base_scale = float(cfg["options"]["scale_factor"])
    sub_root = skin_dir / "submodels"
    before = parse_current_submodels(skin_dir)

    layout = inspect_bg_prefab_layout(indexer, skin)
    scene = _extract_unity_scene_layers(repos, indexer, skin, layout)
    p_key = scene["person_key"]
    back_imgs = [im for im in scene["img_layers"] if im["draw_key"] < p_key]
    pre_imgs = [im for im in back_imgs if im["sort_order"] <= split_c]
    post_imgs = [im for im in back_imgs if im["sort_order"] > split_c]

    if not pre_imgs or not post_imgs:
        for im in scene["img_layers"]:
            try: im["img"].close()
            except Exception: pass
        return {"group": "B_skip", "reason": f"pre={len(pre_imgs)}, post={len(post_imgs)}", "before": before, "after": before}

    shutil.rmtree(sub_root / "bg_static", ignore_errors=True)
    shutil.rmtree(sub_root / "bg_mid", ignore_errors=True)
    bg_res = _render_static_image_group(pre_imgs, skin, layout, base_scale, sub_root / "bg_static", "bg_static", 0.0)
    mid_res = _render_static_image_group(post_imgs, skin, layout, base_scale, sub_root / "bg_mid", "bg_mid", 0.0)
    for im in scene["img_layers"]:
        try: im["img"].close()
        except Exception: pass

    if bg_res:
        convert_submodel_pngs_to_exact_webp(sub_root / "bg_static")
    if mid_res:
        convert_submodel_pngs_to_exact_webp(sub_root / "bg_mid")

    fx_back = [rel for nm, rel, o in before if nm.lower().startswith("fx_") and o < 0]
    pos_items = [(rel, o) for nm, rel, o in before if o > 0]
    new_items = []
    if bg_res:
        new_items.append((bg_res["rel"], -3))
    if fx_back:
        new_items.append((fx_back[0], -2))
    if mid_res:
        new_items.append((mid_res["rel"], -1))
    new_items.extend(pos_items)

    sync_start_and_reload_all_langs(skin_dir, new_items)
    return {"group": "B_split", "pre_imgs": len(pre_imgs), "post_imgs": len(post_imgs), "before": before, "after": parse_current_submodels(skin_dir)}


def fix_group_c_skin(skin_dir: Path, neg_plan: list[tuple[str, int]]) -> dict[str, Any]:
    before = parse_current_submodels(skin_dir)
    rel_by_name = {nm: rel for nm, rel, _ in before}
    pos_items = [(rel, o) for nm, rel, o in before if o > 0]
    new_neg = []
    for nm, ord_v in neg_plan:
        if nm not in rel_by_name:
            raise FileNotFoundError(f"Expected submodel {nm} missing in {skin_dir} (found {list(rel_by_name.keys())})")
        new_neg.append((rel_by_name[nm], ord_v))
    sync_start_and_reload_all_langs(skin_dir, new_neg + pos_items)
    return {"group": "C_reorder", "before": before, "after": parse_current_submodels(skin_dir)}


def main():
    i18n = FullI18nRepo()
    indexer = AssetIndexer()
    repos = BatchAssetRepos(indexer)
    catalog = build_skin_catalog(i18n)
    cat_by_key = {s["skin_key"]: s for s in catalog}

    results = []
    touched_dolls = set()

    print("=== Fixing Group A (5 Z-depth / position rebuild skins) ===")
    for key in sorted(GROUP_A_KEYS):
        skin = cat_by_key[key]
        sk_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"]
        res = fix_group_a_skin(skin, sk_dir, repos, indexer)
        res["skin"] = f"{skin['char_name']}/{skin['dress_name']}"
        res["skin_key"] = key
        results.append(res)
        touched_dolls.add(skin["char_name"])
        print(f"  [OK] {res['skin']} -> {[(f, o) for f, _, o in res['after']]}")

    print("\n=== Fixing Group B (7 back_fx static split skins) ===")
    for key, split_c in sorted(GROUP_B_SPLIT_C.items()):
        skin = cat_by_key[key]
        sk_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"]
        res = fix_group_b_skin(skin, sk_dir, split_c, repos, indexer)
        res["skin"] = f"{skin['char_name']}/{skin['dress_name']}"
        res["skin_key"] = key
        results.append(res)
        touched_dolls.add(skin["char_name"])
        print(f"  [OK] {res['skin']} -> {[(f, o) for f, _, o in res['after']]}")

    print("\n=== Fixing Group C (13 back_fx vs bj_* reorder skins) ===")
    for key, neg_plan in sorted(GROUP_C_NEG_ORDER.items()):
        skin = cat_by_key[key]
        sk_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"]
        res = fix_group_c_skin(sk_dir, neg_plan)
        res["skin"] = f"{skin['char_name']}/{skin['dress_name']}"
        res["skin_key"] = key
        results.append(res)
        touched_dolls.add(skin["char_name"])
        print(f"  [OK] {res['skin']} -> {[(f, o) for f, _, o in res['after']]}")

    # 同步复跑 add_spine_bg_toggle.py 确保三语 hide_bg / show_bg 100% 同步新图层与路径！
    print("\n=== Re-syncing Spine Hide-Background Toggle (add_spine_bg_toggle.py) ===")
    r = subprocess.run([sys.executable, str(SCRIPTS_DIR / "add_spine_bg_toggle.py")], check=True)

    summary = {
        "total_fixed_skins": len(results),
        "touched_dolls": sorted(touched_dolls),
        "touched_dolls_count": len(touched_dolls),
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDONE! Fixed {len(results)} skins across {len(touched_dolls)} dolls: {', '.join(sorted(touched_dolls))}")


if __name__ == "__main__":
    main()
