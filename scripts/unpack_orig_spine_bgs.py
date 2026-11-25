"""Unpack SoulTide base-skin (原皮) portrait & background reference assets from offline CDN.

Investigates and extracts all official base-skin (Dress_01) standing art (立绘) and
background-related assets across the offline Android CDN:
  1. 01_原皮完整立绘_Battle01/        (54/54 dolls, prefers 99_origin uncensored)
  2. 02_祈愿纯人物立绘_LotterySoul/   (54/54 dolls from lotterysoul/_soulbatch1.ab)
  3. 03_单UP卡池宽屏场景_SoloUp/
       - 纯背景分层/                  (6 SoloUp pure BGs + TsukinoMiyo_S1_Background 5 layers)
       - 人物场景合图/                (25 dolls' 1700x750 full-scene banners)
  4. 04_特殊原皮背景素材/             (Clotho_DefaultDress_BJ_01..04 + Lilyiro bj_a)
  5. manifest.json                    (complete 54-doll index)

Output directory:
  E:\\A灵魂潮汐\\spine背景\\原皮立绘与背景解包\\
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from soultide_common import CDN_ROOT, DECOMPILED_DIR, LuaTableRepo, load_ab, parse_lua_flat_table, write_json

OUT_ROOT = Path(r"E:\A灵魂潮汐\spine背景\原皮立绘与背景解包")
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")


def build_slug_to_cn() -> dict[str, tuple[str, int]]:
    """Map lowercase English slug -> (canonical Chinese folder name, soul_id)."""
    repo = LuaTableRepo()
    soul_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgSoulTable.lua")
    # Build slug -> (raw_cn, soul_id) from CfgSoulTable + CfgDressTable
    dress_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgDressTable.lua")
    sid_to_slug: dict[int, str] = {}
    for did, body in dress_tbl.items():
        if not re.search(r"InitialDress\s*=\s*1\b", body):
            continue
        ms = re.search(r"SoulID\s*=\s*(\d+)", body)
        mi = re.search(r'Image\s*=\s*"[^"]*Image_([A-Za-z0-9]+)_Dress_01_Battle01\.png"', body, re.I)
        if ms and mi:
            sid = int(ms.group(1))
            if 20010000 <= sid < 20020000:
                sid_to_slug[sid] = mi.group(1).lower()

    # Canonical Chinese names from existing spine/ folders
    canon_names = {p.name for p in SPINE_ROOT.iterdir() if p.is_dir()}
    # Known exact overrides from BattleHead filenames in spine/<char>/原皮/
    slug_to_canon: dict[str, tuple[str, int]] = {
        "juewa": ("九华", 20010017),
        "nicolettelamel": ("尼柯莱特", 20010011),
    }
    for char_dir in sorted(SPINE_ROOT.iterdir()):
        yp = char_dir / "原皮"
        if not yp.is_dir():
            continue
        for fp in yp.iterdir():
            m = re.match(r"([A-Za-z0-9]+)\s*_Dress(?:_01)?_BattleHead", fp.name, re.I)
            if m:
                slug = m.group(1).lower()
                # find matching sid
                matched_sid = next((s for s, sl in sid_to_slug.items() if sl == slug), 0)
                slug_to_canon[slug] = (char_dir.name, matched_sid)
                break

    # Fill any remaining from CfgSoulTable
    for sid, slug in sid_to_slug.items():
        if slug in slug_to_canon:
            continue
        body = soul_tbl.get(sid, "")
        mn = re.search(r"\bName\s*=\s*getI18NValue\((\d+)\)", body)
        cn = repo.get_i18n(int(mn.group(1))) if mn else slug
        # Prefer canon name if close
        if cn not in canon_names:
            for c in canon_names:
                if cn and (cn in c or c in cn):
                    cn = c
                    break
        slug_to_canon[slug] = (cn or slug, sid)

    return slug_to_canon


def extract_all() -> None:
    slug_map = build_slug_to_cn()
    dir_b01 = OUT_ROOT / "01_原皮完整立绘_Battle01"
    dir_ls = OUT_ROOT / "02_祈愿纯人物立绘_LotterySoul"
    dir_pure = OUT_ROOT / "03_单UP卡池宽屏场景_SoloUp" / "纯背景分层"
    dir_merged = OUT_ROOT / "03_单UP卡池宽屏场景_SoloUp" / "人物场景合图"
    dir_spec = OUT_ROOT / "04_特殊原皮背景素材"
    for d in (dir_b01, dir_ls, dir_pure, dir_merged, dir_spec):
        d.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict[str, Any]] = {}

    def ensure_rec(slug: str) -> dict[str, Any]:
        cn, sid = slug_map.get(slug, (slug, 0))
        return manifest.setdefault(slug, {
            "slug": slug,
            "cn_name": cn,
            "soul_id": sid,
            "battle01": None,
            "lotterysoul": None,
            "soloup_pure_bg": [],
            "soloup_merged": [],
            "special_bg": [],
        })

    # 1. Extract all 54 Battle01 (99_origin overrides normal)
    b01_sources: dict[str, tuple[str, str, Any]] = {}
    for rel in [
        "05_images/image_resources/soulresources/_soulresourcesalldress.ab",
        "05_images/image_resources/soulresources/_soulresourcesalldress2.ab",
        "99_origin/_05_images.ab",
    ]:
        env = load_ab(CDN_ROOT / rel)
        for k, pptr in sorted((env.container or {}).items(), key=lambda x: x[0]):
            kl = k.lower()
            m = re.search(r"image_([a-z0-9]+)_dress_01_battle01\.png$", kl)
            if m:
                slug = m.group(1)
                obj = pptr.read()
                if hasattr(obj, "image"):
                    b01_sources[slug] = (rel, k, obj.image.convert("RGBA"))

    for slug, (rel, k, im) in sorted(b01_sources.items()):
        rec = ensure_rec(slug)
        cn = rec["cn_name"]
        tag = "_99origin" if rel.startswith("99_origin") else ""
        out_p = dir_b01 / f"{cn}_{slug}_Dress_01_Battle01{tag}.png"
        im.save(out_p, "PNG")
        rec["battle01"] = {
            "file": str(out_p.relative_to(OUT_ROOT)),
            "size": [im.width, im.height],
            "source_ab": rel,
            "uncensored_99origin": rel.startswith("99_origin"),
        }
    print(f"[1/4] Extracted {len(b01_sources)} Battle01 portraits -> {dir_b01}")

    # 2. Extract all 54 LotterySoul
    ls_env = load_ab(CDN_ROOT / "05_images/maincity/lotteryui/lotterysoul/_soulbatch1.ab")
    ls_cnt = 0
    for k, pptr in sorted((ls_env.container or {}).items(), key=lambda x: x[0]):
        kl = k.lower()
        m = re.search(r"lotterysoul_([a-z0-9]+)\.png$", kl)
        if not m:
            continue
        slug = m.group(1)
        obj = pptr.read()
        if not hasattr(obj, "image"):
            continue
        im = obj.image.convert("RGBA")
        rec = ensure_rec(slug)
        out_p = dir_ls / f"{rec['cn_name']}_{slug}_LotterySoul.png"
        im.save(out_p, "PNG")
        rec["lotterysoul"] = {
            "file": str(out_p.relative_to(OUT_ROOT)),
            "size": [im.width, im.height],
        }
        ls_cnt += 1
    print(f"[2/4] Extracted {ls_cnt} LotterySoul cutouts -> {dir_ls}")

    # 3. Extract SoloUp 1700x750 banners (split into pure-BG layered vs character-merged)
    # Verified visually from all_soloup_large_half.jpg:
    PURE_BG_FILES = {
        "lotteryui_doll_soloup_18_amaneinori_01.png": "amaneinori",
        "lotteryui_doll_soloup_28_mist_01.png": "mist",
        "lotteryui_doll_soloup_29_etsukazumiko_01.png": "etsukazumiko",
        "fx_ui_clarice_bg.png": "clarice",
        "micha_solo_bg.png": "micha",
        "micha_solo_bg_02.png": "micha",
        "micha_solo_bg_03.png": "micha",
        "truda_soloup_bg_01.png": "truda",
    }
    SKIP_CHAR_OR_TEXT_ONLY = {
        "lotteryui_doll_soloup_28_dollmist_01.png",
        "lotteryui_doll_soloup_29_etsukazumiko_02.png",
        "lotteryui_doll_soloup_29_etsukazumiko_04.png",
        "lotteryui_doll_soloup_29_etsukazumiko_07.png",
        "fx_ui_clarice_ch.png",
        "micha_solo_bg_04.png",
        "truda_soloup_bg_02.png",
        "lotteryui_doll_soloup_54_aria_03.png",
    }
    pure_cnt = 0
    merged_cnt = 0
    for rel in [
        "05_images/maincity/lotteryui/_batch1.ab",
        "05_images/maincity/lotteryui/_batch2.ab",
        "05_images/maincity/lotteryui/_batch3.ab",
        "05_images/maincity/lotteryui/_batch4.ab",
    ]:
        env = load_ab(CDN_ROOT / rel)
        for k, pptr in sorted((env.container or {}).items(), key=lambda x: x[0]):
            kl = k.lower()
            if "doll_soloup" not in kl or not kl.endswith(".png"):
                continue
            fn = Path(kl).name
            if any(w in fn for w in ("artfont", "tittle", "title", "frame")) or fn in SKIP_CHAR_OR_TEXT_ONLY:
                continue
            obj = pptr.read()
            if not hasattr(obj, "image"):
                continue
            im = obj.image.convert("RGBA")
            if im.width < 800 or im.height < 500:
                continue
            fld = Path(kl).parent.name
            m = re.search(r"doll_soloup_\d+_([a-z0-9]+)$", fld)
            slug = PURE_BG_FILES.get(fn) or (m.group(1) if m else fld)
            rec = ensure_rec(slug)
            if fn in PURE_BG_FILES:
                out_p = dir_pure / f"{rec['cn_name']}_{slug}_{fn}"
                im.save(out_p, "PNG")
                rec["soloup_pure_bg"].append({"file": str(out_p.relative_to(OUT_ROOT)), "size": [im.width, im.height], "ab": rel})
                pure_cnt += 1
            else:
                out_p = dir_merged / f"{rec['cn_name']}_{slug}_{fn}"
                im.save(out_p, "PNG")
                rec["soloup_merged"].append({"file": str(out_p.relative_to(OUT_ROOT)), "size": [im.width, im.height], "ab": rel})
                merged_cnt += 1

    # Also extract orphan TsukinoMiyo_S1_Background (5 layered PNGs) into pure_bg/
    tm_env = load_ab(CDN_ROOT / "05_images/image_resources/dress_bg/dressbackground/_batch1.ab")
    tm_dir = dir_pure / "月野未夜_tsukinomiyo_S1_Background分层"
    tm_dir.mkdir(parents=True, exist_ok=True)
    tm_cnt = 0
    for k, pptr in sorted((tm_env.container or {}).items(), key=lambda x: x[0]):
        if "tsukinomiyo_s1_background" in k.lower() and k.lower().endswith(".png"):
            im = pptr.read().image.convert("RGBA")
            out_p = tm_dir / Path(k).name
            im.save(out_p, "PNG")
            ensure_rec("tsukinomiyo")["special_bg"].append({"file": str(out_p.relative_to(OUT_ROOT)), "size": [im.width, im.height]})
            tm_cnt += 1
    print(f"[3/4] Extracted SoloUp: {pure_cnt} pure BG + {merged_cnt} merged banners + {tm_cnt} TsukinoMiyo_S1 layers")

    # 4. Extract special orig Spine BG assets: Clotho_DefaultDress_BJ_01..04 (atlases/PNGs) & Lilyiro bj_a crop
    ui_env = load_ab(CDN_ROOT / "23_spine/ui/batch1.ab")
    clotho_dir = dir_spec / "克洛托_Clotho_DefaultDress_BJ_01_04"
    clotho_dir.mkdir(parents=True, exist_ok=True)
    cl_cnt = 0
    for k, pptr in sorted((ui_env.container or {}).items(), key=lambda x: x[0]):
        kl = k.lower()
        if "clotho_defaultdress_bj_" in kl:
            if kl.endswith(".png"):
                im = pptr.read().image.convert("RGBA")
                out_p = clotho_dir / Path(k).name
                im.save(out_p, "PNG")
                ensure_rec("clotho")["special_bg"].append({"file": str(out_p.relative_to(OUT_ROOT)), "size": [im.width, im.height]})
                cl_cnt += 1
            elif kl.endswith((".atlas.txt", ".skel.bytes")):
                raw = pptr.read().m_Script
                data = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else bytes(raw)
                (clotho_dir / Path(k).name).write_bytes(data)

    # Extract Lilyiro BattleHead embedded bj_a region crop
    li_env = load_ab(CDN_ROOT / "23_spine/battle/character/batch3.ab")
    for k, pptr in (li_env.container or {}).items():
        if "lilyiro_dress_01_battlehead.png" in k.lower():
            im = pptr.read().image.convert("RGBA")
            # From atlas: bj_a rotate: true, xy: 740, 414, size: 556, 245 -> rotated box is w=245, h=556
            crop = im.crop((740, 414, 740 + 245, 414 + 556)).transpose(Image.Transpose.ROTATE_270)
            out_p = dir_spec / "莉莉艾洛_lilyiro_BattleHead_bj_a.png"
            crop.save(out_p, "PNG")
            ensure_rec("lilyiro")["special_bg"].append({"file": str(out_p.relative_to(OUT_ROOT)), "size": [crop.width, crop.height]})
            break
    print(f"[4/4] Extracted special orig BG assets: Clotho BJ PNGs={cl_cnt} + Lilyiro bj_a")

    summary = {
        "out_root": str(OUT_ROOT),
        "total_dolls": len(manifest),
        "battle01_count": len(b01_sources),
        "battle01_99origin_count": sum(1 for v in manifest.values() if v["battle01"] and v["battle01"]["uncensored_99origin"]),
        "lotterysoul_count": ls_cnt,
        "soloup_pure_bg_files": pure_cnt,
        "soloup_pure_bg_dolls": sorted(set(PURE_BG_FILES.values())),
        "soloup_merged_files": merged_cnt,
        "tsukinomiyo_s1_layers": tm_cnt,
        "clotho_defaultdress_bj_pngs": cl_cnt,
        "dolls": [manifest[s] for s in sorted(manifest)],
    }
    write_json(OUT_ROOT / "manifest.json", summary)
    print(f"DONE -> {OUT_ROOT / 'manifest.json'}")


if __name__ == "__main__":
    extract_all()
