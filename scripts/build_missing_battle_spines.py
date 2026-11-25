r"""Build the 11 missing battle-only Spine 3.8 Live2DViewerEX packages.

Only builds skins that have NO existing package in `E:\A灵魂潮汐\Live2D与Spine模型\spine\`
and NO full-screen `dressspine` in the game (i.e. early skins whose only official Spine is
in `23_spine/battle/character/`):
  1. 阿卡赛特/冬日的黑猫  (Akaset_Dress_02_BattleHead)
  2. 阿卡赛特/黑鲨信号    (Akaset_Dress_03_BattleHead)
  3. 叶月雪/夏日盈雪      (HazukiYuki_Dress_02_BattleHead)
  4. 星见亚砂/夏樱_S2     (Asuna_Dress_02_BattleHead)
  5. 星见亚砂/夏樱_S3     (Asuna_Dress_03_BattleHead)
  6. 星见亚砂/夏樱_S4     (Asuna_Dress_04_BattleHead)
  7. 星见亚砂/夏樱_S5     (Asuna_Dress_05_BattleHead)
  8. 欧若拉/平安冬夜      (Aurora_Dress_02_BattleHead)
  9. 芙丽希娅/囚牢天使    (Freesia_Dress_02_BattleHead)
 10. 芙丽希娅/金铃锁愿    (Freesia_Dress_03_BattleHead)
 11. 莉莉艾洛/花间魑祟    (Lilyiro_Dress_02_BattleHead)

Follows 100% of SoulTide Live2DViewerEX fleet standards:
- Spine 3.8 binary `.skel.json` + `.atlas.txt` + V4.4 ETC2-cleaned lossless `exact=True` `.webp`
  (`options.tex_type = 1`, idempotent raw backup in `E:\A灵魂潮汐\备份\spine_etc2_before_clean\`)
- Scheme A sibling 3-language configs (`.config.json`, `config_en.config.json`, `config_ja.config.json`)
  sourced directly from each skin's verified 3-language Live2D package + `.ogg` voices (zero `.wav`)
- Pure-voice touch (`file: ""`) for `头/胸/左手/右手/腿/足/闲聊与问答`, `file: "idle"` for `start`,
  full battle combat animations in `战斗与动作`
- Standard Windows Virtual-Key `key_trigger` (`65..71` = `A..G`)
- Guarded bone-mapped `hit_areas` calibrated against idle skeleton geometry
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
SCRIPT_DIR = Path(__file__).resolve().parent
for p in (str(TOOLS_DIR), str(SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from soultide_common import CDN_ROOT, load_ab
from batch_spine_builder import _compute_fallback_hit_areas, parse_spine38_binary
import spine_etc2_clean_v3 as etc2_clean

L2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
BKP_SPINE_ROOT = Path(r"E:\A灵魂潮汐\备份\spine")
ETC2_BACKUP_ROOT = Path(r"E:\A灵魂潮汐\备份\spine_etc2_before_clean")
EXPORT_MASKS_EXE = SCRIPT_DIR / "export_spine_blend_masks.exe"
REPORT_PATH = SCRIPT_DIR / "missing_battle_spines_report.json"

TARGETS: list[dict[str, str]] = [
    {"char": "阿卡赛特", "skin": "冬日的黑猫", "ab": "batch1.ab", "folder": "akaset_02",      "stem": "Akaset_Dress_02_BattleHead",     "bkp": ""},
    {"char": "阿卡赛特", "skin": "黑鲨信号",   "ab": "batch1.ab", "folder": "akaset_03",      "stem": "Akaset_Dress_03_BattleHead",     "bkp": ""},
    {"char": "叶月雪",   "skin": "夏日盈雪",   "ab": "batch3.ab", "folder": "hazukiyuki_02",  "stem": "HazukiYuki_Dress_02_BattleHead", "bkp": "叶月雪/夏日盈雪"},
    {"char": "星见亚砂", "skin": "夏樱_S2",    "ab": "batch1.ab", "folder": "asuna_dress_02", "stem": "Asuna_Dress_02_BattleHead",      "bkp": "星见亚砂/夏樱"},
    {"char": "星见亚砂", "skin": "夏樱_S3",    "ab": "batch1.ab", "folder": "asuna_dress_03", "stem": "Asuna_Dress_03_BattleHead",      "bkp": "星见亚砂/夏樱"},
    {"char": "星见亚砂", "skin": "夏樱_S4",    "ab": "batch1.ab", "folder": "asuna_dress_04", "stem": "Asuna_Dress_04_BattleHead",      "bkp": "星见亚砂/夏樱"},
    {"char": "星见亚砂", "skin": "夏樱_S5",    "ab": "batch1.ab", "folder": "asuna_dress_05", "stem": "Asuna_Dress_05_BattleHead",      "bkp": "星见亚砂/夏樱"},
    {"char": "欧若拉",   "skin": "平安冬夜",   "ab": "batch2.ab", "folder": "aurora_02",      "stem": "Aurora_Dress_02_BattleHead",     "bkp": "欧若拉/平安冬夜"},
    {"char": "芙丽希娅", "skin": "囚牢天使",   "ab": "batch2.ab", "folder": "freesia_02",     "stem": "Freesia_Dress_02_BattleHead",    "bkp": ""},
    {"char": "芙丽希娅", "skin": "金铃锁愿",   "ab": "batch3.ab", "folder": "freesia_03",     "stem": "Freesia_Dress_03_BattleHead",    "bkp": "芙丽希娅/金铃锁愿"},
    {"char": "莉莉艾洛", "skin": "花间魑祟",   "ab": "batch3.ab", "folder": "lilyiro_02",     "stem": "Lilyiro_Dress_02_BattleHead",    "bkp": "莉莉艾洛/花间魑祟"},
]

LANG_MAP: tuple[tuple[str, str, str], ...] = (
    ("zh", ".model3.json",       ".config.json"),
    ("en", "model_en.model3.json", "config_en.config.json"),
    ("ja", "model_ja.model3.json", "config_ja.config.json"),
)

_ASUNA_CALIBRATED_HITS: list[dict[str, Any]] = [
    {"name": "头",   "id": "tou10",    "motion": "头",   "width": 6.2, "height": 6.4, "center_x": -0.2,  "center_y": -0.5},
    {"name": "胸",   "id": "shenti3",  "motion": "胸",   "width": 5.0, "height": 4.8, "center_x": -0.2,  "center_y": -1.0},
    {"name": "左手", "id": "L_shou_1", "motion": "左手", "width": 3.4, "height": 4.2, "center_x": -0.45, "center_y": -1.75},
    {"name": "右手", "id": "R_shou",   "motion": "右手", "width": 3.4, "height": 3.6, "center_x":  0.35, "center_y":  0.45},
    {"name": "腿",   "id": "R_tui2",   "motion": "腿",   "width": 5.5, "height": 8.5, "center_x":  0.8,  "center_y":  1.5},
    {"name": "足",   "id": "L_tui3",   "motion": "足",   "width": 4.2, "height": 4.4, "center_x":  0.5,  "center_y": -2.2},
]

CALIBRATED_HIT_AREAS: dict[str, list[dict[str, Any]]] = {
    "阿卡赛特/冬日的黑猫": [
        {"name": "头",   "id": "lian6",      "motion": "头",   "width": 4.0, "height": 3.8, "center_x": -0.2,  "center_y":  0.0},
        {"name": "胸",   "id": "shengti3",   "motion": "胸",   "width": 2.8, "height": 2.4, "center_x": -0.35, "center_y":  0.8},
        {"name": "左手", "id": "L_shou",     "motion": "左手", "width": 2.5, "height": 1.5, "center_x":  0.95, "center_y":  0.25},
        {"name": "右手", "id": "R_shou",     "motion": "右手", "width": 2.2, "height": 1.4, "center_x": -0.45, "center_y": -0.15},
        {"name": "腿",   "id": "L_datui",    "motion": "腿",   "width": 4.5, "height": 3.0, "center_x":  1.4,  "center_y": -2.2},
        {"name": "足",   "id": "L_xiaotui2", "motion": "足",   "width": 2.6, "height": 2.2, "center_x": -2.0,  "center_y":  0.0},
    ],
    "阿卡赛特/黑鲨信号": [
        {"name": "头",   "id": "Leye1",  "motion": "头",   "width": 5.5, "height": 5.5, "center_x":  0.0,  "center_y":  0.5},
        {"name": "胸",   "id": "Body2",  "motion": "胸",   "width": 2.8, "height": 2.8, "center_x": -0.6,  "center_y":  1.4},
        {"name": "左手", "id": "Lhand2", "motion": "左手", "width": 2.1, "height": 3.6, "center_x": -0.25, "center_y":  0.65},
        {"name": "右手", "id": "Rhand4", "motion": "右手", "width": 2.6, "height": 3.6, "center_x": -0.05, "center_y": -0.9},
        {"name": "腿",   "id": "LTui3",  "motion": "腿",   "width": 4.8, "height": 4.2, "center_x": -0.4,  "center_y": -0.4},
        {"name": "足",   "id": "RTui3",  "motion": "足",   "width": 3.6, "height": 3.6, "center_x":  2.4,  "center_y": -4.2},
    ],
    "叶月雪/夏日盈雪": [
        {"name": "头",   "id": "YouYanjie1", "motion": "头",   "width": 3.6, "height": 3.8, "center_x":  0.1,  "center_y":  0.0},
        {"name": "胸",   "id": "Shangshen2", "motion": "胸",   "width": 3.0, "height": 2.6, "center_x": -0.2,  "center_y":  0.4},
        {"name": "左手", "id": "ZuoShou",    "motion": "左手", "width": 2.2, "height": 2.6, "center_x": -0.25, "center_y":  2.25},
        {"name": "右手", "id": "YouShou3",   "motion": "右手", "width": 2.2, "height": 2.4, "center_x": -0.25, "center_y":  0.55},
        {"name": "腿",   "id": "ZuoJiao2",   "motion": "腿",   "width": 2.6, "height": 3.8, "center_x": -0.2,  "center_y":  0.6},
        {"name": "足",   "id": "ZuoJiao3",   "motion": "足",   "width": 2.2, "height": 2.6, "center_x": -0.1,  "center_y": -0.8},
    ],
    "星见亚砂/夏樱_S2": _ASUNA_CALIBRATED_HITS,
    "星见亚砂/夏樱_S3": _ASUNA_CALIBRATED_HITS,
    "星见亚砂/夏樱_S4": _ASUNA_CALIBRATED_HITS,
    "星见亚砂/夏樱_S5": _ASUNA_CALIBRATED_HITS,
    "欧若拉/平安冬夜": [
        {"name": "头",   "id": "L_yan1",  "motion": "头",   "width": 2.8, "height": 2.8, "center_x": -0.3,  "center_y":  0.4},
        {"name": "胸",   "id": "shenti5", "motion": "胸",   "width": 2.1, "height": 2.0, "center_x":  0.2,  "center_y": -0.3},
        {"name": "左手", "id": "R_shou2", "motion": "左手", "width": 1.5, "height": 2.0, "center_x": -0.53, "center_y":  0.02},
        {"name": "右手", "id": "L_shou2", "motion": "右手", "width": 1.8, "height": 2.0, "center_x":  0.2,  "center_y": -0.2},
        {"name": "腿",   "id": "R_tui2",  "motion": "腿",   "width": 3.4, "height": 3.4, "center_x": -0.2,  "center_y": -1.8},
        {"name": "足",   "id": "R_tui4",  "motion": "足",   "width": 1.8, "height": 2.6, "center_x":  0.1,  "center_y": -0.8},
    ],
    "芙丽希娅/囚牢天使": [
        {"name": "头",   "id": "head8",    "motion": "头",   "width": 2.4, "height": 2.4, "center_x": -0.1,  "center_y":  0.1},
        {"name": "胸",   "id": "body_1",   "motion": "胸",   "width": 2.0, "height": 1.8, "center_x": -0.3,  "center_y":  0.2},
        {"name": "左手", "id": "L_hand_4", "motion": "左手", "width": 1.5, "height": 1.6, "center_x": -0.05, "center_y": -0.45},
        {"name": "右手", "id": "R_hand_3", "motion": "右手", "width": 1.5, "height": 1.9, "center_x": -0.4,  "center_y":  0.05},
        {"name": "腿",   "id": "R_tui_1",  "motion": "腿",   "width": 2.4, "height": 2.4, "center_x":  0.2,  "center_y": -0.8},
        {"name": "足",   "id": "L_tui4",   "motion": "足",   "width": 1.8, "height": 1.8, "center_x": -0.2,  "center_y": -0.3},
    ],
    "芙丽希娅/金铃锁愿": [
        {"name": "头",   "id": "eye3",       "motion": "头",   "width": 2.6, "height": 2.8, "center_x":  0.4,  "center_y":  0.2},
        {"name": "胸",   "id": "liusu6",     "motion": "胸",   "width": 2.2, "height": 2.0, "center_x": -0.1,  "center_y": -0.5},
        {"name": "左手", "id": "L_shou",     "motion": "左手", "width": 1.5, "height": 1.5, "center_x": -0.05, "center_y":  0.0},
        {"name": "右手", "id": "R_shou3",    "motion": "右手", "width": 1.5, "height": 2.0, "center_x":  0.16, "center_y":  0.07},
        {"name": "腿",   "id": "R_xiaotui",  "motion": "腿",   "width": 2.6, "height": 3.4, "center_x": -0.3,  "center_y":  0.4},
        {"name": "足",   "id": "R_xiaotui2", "motion": "足",   "width": 2.0, "height": 2.0, "center_x": -0.2,  "center_y": -0.2},
    ],
    "莉莉艾洛/花间魑祟": [
        {"name": "头",   "id": "head7",     "motion": "头",   "width": 2.0, "height": 2.0, "center_x":  0.0,  "center_y":  0.2},
        {"name": "胸",   "id": "body_5",    "motion": "胸",   "width": 1.8, "height": 1.4, "center_x":  0.2,  "center_y": -0.1},
        {"name": "左手", "id": "dajianhou", "motion": "左手", "width": 1.4, "height": 1.4, "center_x":  0.45, "center_y": -0.1},
        {"name": "右手", "id": "R_hand3",   "motion": "右手", "width": 1.4, "height": 1.8, "center_x":  0.05, "center_y": -0.05},
        {"name": "腿",   "id": "body_11",   "motion": "腿",   "width": 2.0, "height": 2.6, "center_x":  0.2,  "center_y": -0.6},
        {"name": "足",   "id": "bone5",     "motion": "足",   "width": 1.8, "height": 1.8, "center_x": -0.2,  "center_y": -0.4},
    ],
}

BG_BONE_RE = re.compile(
    r"(?:^|_)(?:bg|bj|background|back|yingzi|shadow|deng|light|shafa|sofa|zhuo|table|yi|chair|"
    r"chuang|bed|window|chuanghu|cloud|yun|shui|water|hua_|flower|tree|shu_|cat|mao|dog|gou|"
    r"bird|niao|book|shu\d|cup|bei|wine|jiu|lazhu|candle|guang|fx|effect|smoke|yanwu|wuzi|"
    r"room|floor|diban|wall|qiang|curtain|chuanglian|pillow|zhentou|qiu|ball|umbrella|san|"
    r"frame|kuang|mirror|jingzi|clock|zhong|music|yinfu|star|xing|moon|yue)(?:_|\d|$)",
    re.I,
)
BAD_CHEST_RE = re.compile(r"(xiaoxiong|fasheng|guazhui|tou|lian|shou|tui|jiao)", re.I)
BAD_FOOT_RE = re.compile(
    r"(zui|zuiba|bizui|zuoshou|zuobi|zuodabi|zuoxiaobi|zuoxiu|zuoyan|zuomei|zuojiemao|tou|lian|xiong|shou|qun|weisha|fasheng|guazhui)",
    re.I,
)


def _save_lossless_webp(rgba: np.ndarray, out_path: Path) -> None:
    tmp_path = out_path.with_suffix(".tmp.webp")
    Image.fromarray(rgba, "RGBA").save(tmp_path, "WEBP", lossless=True, exact=True, quality=100, method=6)
    rt = np.array(Image.open(tmp_path).convert("RGBA"))
    if not np.array_equal(rgba, rt):
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Lossless WebP exact=True round-trip mismatch for {out_path}")
    tmp_path.replace(out_path)


def _load_l2d_3lang_voices(l2d_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load verified zh/en/ja voice entries aligned by group & sound from Live2D package."""
    lang_mots: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for code, l2d_fn, _ in LANG_MAP:
        d = json.loads((l2d_dir / l2d_fn).read_text(encoding="utf-8-sig"))
        lang_mots[code] = d.get("FileReferences", {}).get("Motions", {}) or {}

    out: dict[str, list[dict[str, Any]]] = {}
    zh_mots = lang_mots["zh"]
    for grp, zh_items in zh_mots.items():
        if not isinstance(zh_items, list) or grp.startswith("Menu") or grp in ("Tap", "语音菜单", "Idle", "誓约戒指切换", "Form_Switch_Main"):
            continue
        en_items = lang_mots["en"].get(grp) or []
        ja_items = lang_mots["ja"].get(grp) or []
        seen_snd: set[str] = set()
        bucket: list[dict[str, Any]] = []
        for idx, zit in enumerate(zh_items):
            snd = zit.get("Sound", "")
            if not snd:
                continue
            src_ogg = l2d_dir / snd
            if not src_ogg.is_file():
                continue
            if snd in seen_snd:
                continue
            seen_snd.add(snd)
            eit = en_items[idx] if idx < len(en_items) and en_items[idx].get("Sound") == snd else {}
            jit = ja_items[idx] if idx < len(ja_items) and ja_items[idx].get("Sound") == snd else {}
            bucket.append(
                {
                    "src_ogg": src_ogg,
                    "ogg_name": src_ogg.name,
                    "text": {
                        "zh": zit.get("Text", ""),
                        "en": eit.get("Text", "") or zit.get("Text", ""),
                        "ja": jit.get("Text", "") or zit.get("Text", ""),
                    },
                    "text_duration": int(zit.get("TextDuration", 3500) or 3500),
                }
            )
        if bucket:
            out[grp] = bucket
    return out


def _sanitize_hit_areas(hit_areas: list[dict[str, Any]], parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Ensure every initial hit_area satisfies verify_batch_spine.py bone guards."""
    valid_bones = [b["name"] for b in parsed["bones"] if b["name"] != "root" and not BG_BONE_RE.search(b["name"])]
    fallback_body = next((b for b in valid_bones if any(k in b.lower() for k in ("body", "spine", "chest", "torso", "shenti", "xiong"))), valid_bones[0])
    used: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for ha in hit_areas:
        bid = ha["id"]
        mot = ha["motion"]
        bad = (
            bid == "root"
            or BG_BONE_RE.search(bid) is not None
            or (mot == "胸" and BAD_CHEST_RE.search(bid) is not None)
            or (mot == "足" and BAD_FOOT_RE.search(bid) is not None)
            or bid in used
        )
        if bad:
            # Find a clean replacement bone not yet used
            cand = None
            for b in valid_bones:
                if b in used:
                    continue
                if mot == "胸" and BAD_CHEST_RE.search(b):
                    continue
                if mot == "足" and BAD_FOOT_RE.search(b):
                    continue
                cand = b
                break
            if not cand:
                continue
            ha = dict(ha, id=cand)
        used.add(ha["id"])
        cleaned.append(ha)
    return cleaned


def _compute_scale_factor(char: str, bkp_rel: str, cur_bh: float) -> float:
    # 1. Inherit calibrated scale from backup spine if sane
    if bkp_rel:
        bkp_cfg_p = BKP_SPINE_ROOT / bkp_rel / ".config.json"
        if bkp_cfg_p.is_file():
            bc = json.loads(bkp_cfg_p.read_text(encoding="utf-8-sig"))
            bsc = float((bc.get("options") or {}).get("scale_factor", 0.0) or 0.0)
            if 0.035 <= bsc <= 0.42:
                return round(bsc, 5)
    # 2. Match character's existing 原皮 on-screen height
    orig_dir = SPINE_ROOT / char / "原皮"
    orig_cfg = json.loads((orig_dir / ".config.json").read_text(encoding="utf-8-sig"))
    orig_sc = float(orig_cfg["options"]["scale_factor"])
    orig_bh = max(100.0, float(parse_spine38_binary((orig_dir / orig_cfg["skeleton"]).read_bytes())["bounds"][3]))
    scaled = orig_sc * orig_bh / max(100.0, cur_bh)
    return round(max(0.035, min(0.38, scaled)), 5)


def _extract_battle_unit(env: Any, folder: str) -> tuple[bytes, bytes, np.ndarray, str]:
    cm = {ptr.path_id: cp for cp, ptr in env.container.items()}
    atlas_bytes = skel_bytes = None
    tex_rgba = None
    tex_name = ""
    for obj in env.objects:
        cp = cm.get(obj.path_id, "")
        if not cp or Path(cp).parent.name.lower() != folder.lower():
            continue
        if obj.type.name == "TextAsset":
            d = obj.read()
            raw = d.m_Script if isinstance(d.m_Script, (bytes, bytearray)) else d.m_Script.encode("utf-8", "surrogateescape")
            if cp.endswith(".atlas.txt"):
                atlas_bytes = bytes(raw)
            elif cp.endswith(".skel.bytes"):
                skel_bytes = bytes(raw)
        elif obj.type.name == "Texture2D":
            d = obj.read()
            tex_name = d.m_Name
            tex_rgba = np.array(d.image.convert("RGBA"))
    assert atlas_bytes is not None and skel_bytes is not None and tex_rgba is not None, (
        f"Incomplete battle Spine unit for folder={folder}"
    )
    return atlas_bytes, skel_bytes, tex_rgba, tex_name


def build_one(spec: dict[str, str], ab_cache: dict[str, Any], force: bool = False) -> dict[str, Any]:
    char = spec["char"]
    skin = spec["skin"]
    ab_name = spec["ab"]
    folder = spec["folder"]
    stem = spec["stem"]
    out_dir = SPINE_ROOT / char / skin
    if out_dir.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing Spine package without --force: {out_dir}")

    if ab_name not in ab_cache:
        ab_cache[ab_name] = load_ab(CDN_ROOT / "23_spine" / "battle" / "character" / ab_name)
    atlas_bytes, skel_bytes, raw_rgba, tex_name = _extract_battle_unit(ab_cache[ab_name], folder)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    aud_dir = out_dir / "audio"
    aud_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write skeleton binary (named .skel.json matching fleet convention) & atlas (.png -> .webp)
    skel_fn = f"{stem}.skel.json"
    atlas_fn = f"{stem}.atlas.txt"
    webp_fn = f"{tex_name}.webp"
    (out_dir / skel_fn).write_bytes(skel_bytes)

    atlas_txt = atlas_bytes.decode("utf-8")
    old_png = f"{tex_name}.png"
    assert old_png in atlas_txt, f"Expected {old_png} in {stem} atlas"
    atlas_txt_webp = atlas_txt.replace(old_png, webp_fn, 1)
    (out_dir / atlas_fn).write_text(atlas_txt_webp, encoding="utf-8", newline="")

    # 2. Save raw backup WebP (idempotent) + run V4.4 ETC2 PMA cleaner + lossless exact=True WebP
    bk_webp = ETC2_BACKUP_ROOT / char / skin / webp_fn
    if not bk_webp.is_file():
        bk_webp.parent.mkdir(parents=True, exist_ok=True)
        _save_lossless_webp(raw_rgba, bk_webp)

    det = etc2_clean.detect_pma_etc2_atlas(raw_rgba)
    if det["needs_clean"]:
        cleaned_rgba, etc2_stats = etc2_clean.clean_etc2_spine_pma_v3(raw_rgba, protect_mask=None)
        etc2_status = "cleaned"
    else:
        cleaned_rgba = raw_rgba
        etc2_stats = {}
        etc2_status = "already_clean"
    _save_lossless_webp(cleaned_rgba, out_dir / webp_fn)

    # 3. Parse Spine 3.8 binary
    parsed = parse_spine38_binary(skel_bytes)
    anims = parsed["anims"]
    idle_anim = "idle" if "idle" in anims else anims[0]
    cur_bh = max(100.0, float(parsed["bounds"][3]))
    base_scale = _compute_scale_factor(char, spec["bkp"], cur_bh)

    # 4. Load verified 3-language voices from sibling Live2D package
    l2d_dir = L2D_ROOT / char / skin
    voices = _load_l2d_3lang_voices(l2d_dir)
    copied_oggs: set[str] = set()

    def pick_from_groups(grps: tuple[str, ...]) -> list[dict[str, Any]]:
        res: list[dict[str, Any]] = []
        seen: set[str] = set()
        for g in grps:
            for v in voices.get(g, []):
                if v["ogg_name"] not in seen:
                    seen.add(v["ogg_name"])
                    res.append(v)
        return res

    start_voices = pick_from_groups(("Start", "Morning", "Noon", "Evening", "Greeting"))
    chat_voices = pick_from_groups(("Greeting", "Morning", "Noon", "Evening", "Midnight", "Gift", "Food", "Archive", "Sad", "TouchSpecial"))
    tap_head = pick_from_groups(("Tap头",)) or chat_voices[:3]
    tap_chest = pick_from_groups(("Tap胸",)) or chat_voices[:3]
    tap_hand = pick_from_groups(("Tap手",)) or chat_voices[:3]
    tap_leg = pick_from_groups(("Tap臀部",)) or chat_voices[:3]
    battle_voices = pick_from_groups(("Battle", "ExtraMotions"))

    def mk_mtn(name: str, anim_file: str, lang: str, vitem: dict[str, Any] | None = None) -> dict[str, Any]:
        ent: dict[str, Any] = {"name": name, "file": anim_file}
        if anim_file:
            ent["fade_in"] = 100
            ent["fade_out"] = 100
        if vitem:
            on = vitem["ogg_name"]
            if on not in copied_oggs:
                shutil.copy2(vitem["src_ogg"], aud_dir / on)
                copied_oggs.add(on)
            ent["sound"] = f"audio/{on}"
            txt = vitem["text"].get(lang, "")
            if txt:
                ent["text"] = txt
                ent["text_duration"] = vitem["text_duration"]
        return ent

    def map_group(vlist: list[dict[str, Any]], tag: str, lang: str, max_items: int = 8) -> list[dict[str, Any]]:
        if vlist:
            return [mk_mtn(f"{tag}_{i:02d}", "", lang, v) for i, v in enumerate(vlist[:max_items])]
        return [mk_mtn(f"{tag}_00", "", lang)]

    def build_motions(lang: str) -> dict[str, Any]:
        start_items = [mk_mtn(f"start_{i}", idle_anim, lang, v) for i, v in enumerate((start_voices[:3] if start_voices else [None]))]
        action_items = [
            mk_mtn(f"anim_{a}", a, lang, battle_voices[i % len(battle_voices)] if battle_voices else None)
            for i, a in enumerate(a for a in anims if a != idle_anim)
        ]
        mots: dict[str, Any] = {
            "idle": [{"name": idle_anim, "file": idle_anim, "fade_in": 10, "fade_out": 10, "file_loop": True}],
            "start": start_items,
            "闲聊与问答": map_group(chat_voices or start_voices, "chat", lang, max_items=16),
            "头": map_group(tap_head, "head", lang, max_items=6),
            "左手": map_group(tap_hand, "lhand", lang, max_items=4),
            "右手": map_group(list(reversed(tap_hand)) if tap_hand else [], "rhand", lang, max_items=4),
            "胸": map_group(tap_chest, "chest", lang, max_items=6),
            "腿": map_group(tap_leg, "leg", lang, max_items=4),
            "足": map_group(list(reversed(tap_leg)) if tap_leg else [], "foot", lang, max_items=4),
        }
        if action_items:
            mots["战斗与动作"] = action_items
        return mots

    zh_motions = build_motions("zh")
    rel_key = f"{char}/{skin}"
    if rel_key in CALIBRATED_HIT_AREAS:
        hit_areas = [dict(h) for h in CALIBRATED_HIT_AREAS[rel_key]]
    else:
        raw_hits = _compute_fallback_hit_areas(parsed, idle_anim, zh_motions)
        hit_areas = _sanitize_hit_areas(raw_hits, parsed)
    model_id = f"{stem.lower()}_battle"

    # 5. Write all 3 language configs compactly
    for code, _, sp_fn in LANG_MAP:
        mots = zh_motions if code == "zh" else build_motions(code)
        cfg = {
            "conf_ver": 1,
            "type": 9,
            "controllers": {
                "param_hit": {},
                "param_loop": {},
                "key_trigger": {
                    "enabled": True,
                    "items": [
                        {"input": 65, "down_mtn": "闲聊与问答"},
                        {"input": 66, "down_mtn": "头"},
                        {"input": 67, "down_mtn": "左手"},
                        {"input": 68, "down_mtn": "右手"},
                        {"input": 69, "down_mtn": "胸"},
                        {"input": 70, "down_mtn": "腿"},
                        {"input": 71, "down_mtn": "足"},
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
            "motions": mots,
            "options": {
                "id": model_id,
                "scale_factor": base_scale,
                "position_x": 0.0,
                "position_y": 0.0,
                "tex_type": 1,
                "edge_padding": False,
                "shader_type": 0,
            },
            "skeleton": skel_fn,
            "atlases": [{"atlas": atlas_fn, "tex_names": [tex_name], "textures": [webp_fn]}],
        }
        (out_dir / sp_fn).write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    return {
        "skin": f"{char}/{skin}",
        "ab": f"{ab_name}:{folder}",
        "stem": stem,
        "spine_version": parsed["version"],
        "bones": len(parsed["bones"]),
        "anims": len(anims),
        "oggs": len(copied_oggs),
        "hit_areas": len(hit_areas),
        "scale_factor": base_scale,
        "etc2_status": etc2_status,
        "etc2_detect": det,
        "webp_bytes": (out_dir / webp_fn).stat().st_size,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the 11 missing battle-only Spine packages.")
    ap.add_argument("--force", action="store_true", help="Overwrite if target skin folder already exists")
    ap.add_argument("--only", type=str, default="", help="Only build matching <char>/<skin> substring")
    args = ap.parse_args()

    ab_cache: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    for spec in TARGETS:
        rel = f"{spec['char']}/{spec['skin']}"
        if args.only and args.only not in rel:
            continue
        res = build_one(spec, ab_cache, force=args.force)
        results.append(res)
        print(
            f"[OK] {rel:14s} | scale={res['scale_factor']:.4f} | oggs={res['oggs']:2d} | ha={res['hit_areas']} | etc2={res['etc2_status']} | webp={res['webp_bytes']//1024}KB",
            flush=True,
        )

    report = {"built_count": len(results), "results": results}
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport saved -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
