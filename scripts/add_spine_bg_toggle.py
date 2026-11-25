r"""Add runtime 'Hide Background (Keep Touch FX)' toggle to all 109 dressed Spine skins.

Implements runtime hide-background (preserving touch FX) and main-skeleton
slot_opacities prop-toggle configuration across `.config.json`,
`config_en.config.json`, and `config_ja.config.json`:
- Class A (54 orig skins, 0 submodels): untouched.
- Class B (background/ambient-only dressed skins, no `start_mtn` touch FX):
  `hide_bg` removes all submodels cleanly; `show_bg` restores all submodels in exact `start` order.
- Class C (pure touch-FX submodel whose `idle` is already empty `{}`):
  `hide_bg` removes all non-touch submodels and preserves the touch-FX submodel untouched.
- Class D (shared ambient `idle` + `start_mtn` touch FX in the same `fx_*` submodel):
  Adds `"idle_empty"` animation to `submodels/fx_xxx/<skel>.json`, writes `touch_only.config.json`
  (same `options.id`, `idle -> idle_empty`, preserving all touch FX actions), and `hide_bg` swaps
  the ambient `fx_*` submodel to `touch_only.config.json` while removing all other background layers!

Adds:
- `motions["背景开关"]` with `hide_bg` and `show_bg` (`file: ""` so current voice/motion is never interrupted).
- `motions["背景菜单"]` popup choice menu (`file: ""`, localized zh/en/ja; `next_mtn` uses exact `group:name`).
- `motions["reload_bg"]` refreshed with clean remove-before-add sequence (including `touch_only` cleanup, zero stale paths).
- `controllers.key_trigger.items`: binds Windows VK `F3` (`114`) and `H` (`72`) to `"背景菜单"` (and normalizes legacy ASCII/Unity codes).

Idempotent: safe to re-run at any time.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
REPORT_PATH = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本\spine_bg_toggle_report.json")

LANG_SPECS: tuple[tuple[str, str], ...] = (
    ("zh", ".config.json"),
    ("en", "config_en.config.json"),
    ("ja", "config_ja.config.json"),
)

# Skins whose main Spine skeleton contains separable background / furniture / floating-prop slots
# that users may optionally hide together with the background via EX native
# `slot_opacities lock <slots> 0 0` (and cleanly restore + auto-unlock via `slot_opacities set <slots> 1 0`).
# All 38 entries have been 2-panel visually verified via Spine3_8 rendering to keep the character
# 100% intact (zero body cutoffs, zero hair/outfit/hand/interactive-prop removal).
EXTRA_HIDE_PROP_SLOTS: dict[str, list[str]] = {
    # 左侧独立泳圈小猫（保留互动海豚） (11 slots)
    "九华/与猫逐浪": [
        "jiuhua82", "jiuhua81", "jiuhua80", "jiuhua79", "jiuhua78", "jiuhua76", "jiuhua74", "jiuhua77",
        "jiuhua75", "jiuhua72", "jiuhua70",
    ],
    # 左侧独立逗猫棒与身下木凳 (6 slots)
    "九华/时光猫咖": ["jiuhua_113", "jiuhua_110", "jiuhua_98", "jiuhua_97", "jiuhua_96", "jiuhua_95"],
    # 面前木书桌与桌沿挂穗 (2 slots)
    "伊汐尔/新春焰火": ["zhuozi", "sui"],
    # 左下角独立沙滩球/珍珠 (3 slots)
    "光明云/云照海光": ["BBu2", "BBu1", "BBu0"],
    # 左上悬枝小鸟、悬浮蓝光蝶与左下青苔石（保留婚纱裙摆） (8 slots)
    "克拉丽丝/比翼双飞": ["bj", "k108", "k107", "k104", "k3", "k2", "k1", "k0"],
    # 两侧悬浮小人偶（保留后发与互动花瓣） (4 slots)
    "克洛托/清莹相思": ["k101", "k3", "k2", "k0"],
    # 身下榻榻米床榻、毛绒毯与右侧软枕 (4 slots)
    "凡妮/红泥融雪": ["69", "66", "65", "7"],
    # 脚下废墟机甲残骸与背景光 (5 slots)
    "南宫凛/异想骑士": ["wu", "jiqihou2", "jiqihou1", "jiqirenqian", "beijinguang"],
    # 背后镜面中的人物倒影 (9 slots)
    "南宫凛/情至心处": ["129", "128", "125", "123", "122", "121", "119", "118", "117"],
    # 3 只悬浮发光青兔与柜台/折叠椅/箱子/刨冰道具 (16 slots)
    "叶月雪/夏光幻雪": [
        "yizi", "yizituzi3", "yizituzi2", "yizituzi1", "xiangzi2", "zhuotai", "houtuzi4", "houtuzi3",
        "houtuzi2", "houtuzi1", "jintuzi3", "jintuzi2", "jintuzi1", "binggaoyingzi", "bingsha", "tuzihong",
    ],
    # 沙滩球、水波与脚边水花（保留身下泳圈） (4 slots)
    "叶隐琉璃/小美人鱼的夏日": ["shui_2", "qiu_3", "qiu_2", "qiu_1"],
    # 左下角独立悬浮蝴蝶结小包 (10 slots)
    "多洛莉丝/情蛊蝶恋": [
        "hudie191", "hudie1911", "hudie190", "hudie189", "hudie188", "hudie187", "hudie186", "hudie185",
        "hudie184", "hudie183",
    ],
    # 白色吧台椅底座与左侧立牌（保留双腿） (4 slots)
    "天音祈/爱玩兔丝": ["62", "51", "50", "48"],
    # 身下深色木质檐台（保留左手与衣袖 t82/t83/t84） (1 slot)
    "天音祈/青霄和歌": ["t94"],
    # 四周 4 件独立悬浮古宅摆件与玩偶（保留互动音符/补图） (13 slots)
    "密丝特/幽灵公馆": ["11", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "wawa2", "wawa1"],
    # 身下粗大树干与树枝 (4 slots)
    "拉薇拉/丛林猎手": ["tree1_bg", "tree", "shugan", "bg_shigan"],
    # 左侧悬浮冷饮杯与独立小挎包 (5 slots)
    "星见亚砂/盛夏游乐场": ["YS108", "YS107", "YS106", "YS101", "YS100"],
    # 右侧独立泰迪熊与彩色气球束（保留互动四季特效） (19 slots)
    "朔耶真子/情系站缘": [
        "qi32", "qi3", "qi22", "qi2", "qi11", "qi1", "qi01", "qi0", "wb", "st", "zuojio", "youjio",
        "erduo2", "erduo1", "xiaoxiongtou", "biyan", "lingjie", "zuomao", "youmao",
    ],
    # 漂浮花簇、水面倒影与水花（保留身下透明泳圈） (16 slots)
    "朔耶真子/真子漂流记": [
        "shuihua", "daoying", "hua8", "hua7", "hua6", "hua5", "hua4", "hua3", "hua2", "hua1", "hua13",
        "hua12", "lignt", "shui4", "shui3", "shui1",
    ],
    # 顶部横跨全屏的神社注连绳与风铃 (13 slots)
    "朔耶真子/神明恋歌": ["J2", "ZZ89", "ZZ88", "ZZ4", "ZZ3", "ZZ1", "BU3", "BU2", "BU1", "ZZ2", "ZZ0", "BU6", "J1"],
    # 左侧红灯笼、木茶桌、地面与前后背景熊猫（保留毛领 H_houmao） (28 slots)
    "梦咲音月/春竹贺晓": [
        "di", "h_xiongmao_9", "h_xiongmao_1", "h_xiongmao_10", "h_xiongmao_11", "h_xiongmao_8", "h_xiongmao_2",
        "h_xiongmao_12", "h_xiongmao_5", "h_xiongmao_3", "h_xiongmao_4", "h_xiongmao_6", "h_xiongmao_7",
        "zuo_2", "q_xiongmao_7", "q_xiongmao_3", "q_xiongmao_2", "q_xiongmao_8", "q_xiongmao_4", "q_xiongmao_1",
        "q_xiongmao_5", "q_xiongmao_6", "xiongmao_x", "denglong_2", "denglong_4", "denglong_1", "denglong_3",
        "zuo_3",
    ],
    # 四周桃花树枝与枝上挂饰（保留手中油纸伞） (18 slots)
    "欧若拉/仙宫新岁": [
        "shuzhihou3", "huahou", "shuzhihou2", "C_xianglian2", "shuzhihou1", "shuzhi4", "shuzhi4hua2",
        "shuzhi4hua1", "shuzhi3", "shuzhi2", "C_xianglian3", "C_xianglian1", "hua7", "hua6", "shuzhi1",
        "hua3", "hua2", "hua1",
    ],
    # 身下木凳与右侧独立白兔摆件 (5 slots)
    "欧若拉/完美公主": ["yizi", "tuzi_5", "tuzi_6", "tuzi_7", "tuzi_8"],
    # 周围 3 只独立悬浮小精灵与背景图层 (56 slots)
    "欧若拉/童话心绘": [
        "165", "164", "163", "162", "161", "160", "159", "158", "157", "156", "155", "154", "153",
        "152", "151", "150", "149", "148", "147", "146", "144", "143", "142", "141", "140", "139",
        "138", "137", "136", "135", "134", "133", "132", "130", "129", "128", "127", "126", "125",
        "124", "123", "122", "121", "120", "119", "118", "116", "117", "4", "3", "2", "1", "0", "lvbiaoqing",
        "lvshou3", "hongbiaoqing",
    ],
    # 4 张悬浮拍立得相框（含框内小人）与左侧独立兔子 (58 slots)
    "爱莉莎/幻想时刻": [
        "4_kuang2", "4_juese", "4_kuang1", "3_kuang2", "3_qunzi3", "3_tui1", "3_tui2", "3_qunzi2",
        "3_qunzi1", "3_kuang1", "2_kuang1", "2_qunzi4", "kk", "2_tui6", "2_tui5", "2_qunzi3", "2_qunzi2",
        "2_qunzi1", "2_tui4", "2_tui3", "2_tui2", "2_tui1", "2_kuang11", "1_kuang2", "1_houfa3", "1_houfa2",
        "1_houfa1", "1_bozi", "1_L_yan5", "1_L_yan4", "1_R_yan5", "1_R_yan4", "1_lian", "1_qianfaYY",
        "1_L_yan3", "1_L_yan2", "1_L_yan1", "1_R_yan3", "1_R_yan2", "1_R_yan1", "1_qianfa8", "zui4",
        "1_qianfa7", "1_qianfa10", "1_qianfa5", "1_qianfa4", "1_qianfa3", "1_qianfa2", "1_qianfa1",
        "1_qianfa9", "1_meimao", "1_shou3", "1_shou2", "1_shou1", "1_kuang1", "2", "0", "1",
    ],
    # 身下石棺长台与台面投影（保留外头发） (5 slots)
    "米涅德温/黎明百合": ["shouyinying", "guaicai1", "guaicai2", "qiandangbu2", "qiandangbu3"],
    # 上方独立悬空月相弧线与星光（保留身下云朵） (18 slots)
    "艾妮斯/时空恋曲": [
        "YUEX5", "YUEX4", "YUEX3", "YUEX2", "YUEX1", "YUEX0", "SP9", "SP8", "SP7", "SP6", "SP5", "SP4",
        "SP3", "SP2", "SP1", "SP0", "BU0", "BU17",
    ],
    # 身下蓝色长椅与左上角花枝（保留互动飞鸟纸鹤） (2 slots)
    "艾妮斯/虚晓流光": ["yizi", "hua2"],
    # 身后红布桌椅与地面装饰（保留怀抱互动小怪） (5 slots)
    "萨缇娅/魔王晚宴": ["di_2", "bu_3", "bu_2", "bu_1", "di_1"],
    # 面前古风木矮桌 (2 slots)
    "蕖灵/琼楼倚娇蕖": ["zhuozi_1", "zhuozi"],
    # 全屏荆棘蔷薇藤蔓与藤叶（保留 5 个后发槽位） (45 slots)
    "薇姬娜/午夜蔷薇": [
        "tengwan52", "tengwan71", "tengwan7", "tengwan7_leaf", "tengwan7_rose2", "tengwan7_rose1",
        "tengwan6_2", "tengwan6_11", "tengwan6_1", "tengwan6_leaf", "tengwan6_rose", "tengwan5", "tengwan51",
        "tengwan5_leaf", "tengwan5_rose", "L_ci23", "L_ci22", "L_ci2", "tengwan4_2", "tengwan4_1",
        "tengwan4_leaf", "tengwan41_leaf", "tengwan4_rose", "tengwan2_1", "tengwan2_rose2", "tengwan2_2_1",
        "R_ci2", "tengwan3_4", "tengwan3_2", "tengwan3_leaf", "tengwan31_leaf", "tengwan1_1", "tengwan1_leaf",
        "tengwan1_3", "tengwan1_leaf2", "tengwan11_leaf", "tengwan11_leaf2", "tengwan1_rose", "tengwan1_rose2",
        "tengwan1_7", "tengwan1_5", "tengwan1_4", "tengwan2_leaf", "tengwan22_leaf", "tengwan2_rose",
    ],
    # 左下沙滩球、沙滩巾与沙面（保留饮品托盘） (4 slots)
    "薇姬娜/盛夏甜心": ["tanzi", "qiu", "sha_1", "sha_3"],
    # 课桌、挂钩、耳机、汽水与投影 (7 slots)
    "西勒诺斯/波子跃动": ["shentiYY", "qishui", "zhuozi", "ErjiYY", "guagou2", "Erji", "guagou1"],
    # 街边流浪猫、杂草、路人剪影、金属护栏与悬挂书包（保留武士刀） (35 slots)
    "越一弥心/邂逅风纪": [
        "grass3", "cat1_tail", "cat1_body", "cat1_hand", "cat1_head", "cat1_eye", "passby3_body",
        "passby3_hair2", "passby3_hair1", "passby2_2", "passby2_1", "passby1_body", "passby1_hair",
        "grass2", "grass1", "char_shadow_ground", "bag3", "langan8", "langan7", "langan6", "langan5",
        "langan4", "langan3", "langan2", "langan1", "char_shadow_langan", "char_shadow_hand", "bag2",
        "bag1", "bag_doll", "bag_chain", "energyball_chain", "energyball", "energyball_light", "bag_jiazi",
    ],
    # 身后金色王座座椅（保留后发） (4 slots)
    "迦瓦娜/辉芒之子": ["zuoweiqiyu", "zuoweiqiyu1", "zuoweihou", "zuoweiqian"],
    # 独立悬浮全息镜（=△=） (2 slots)
    "阿卡赛特/心核恒慕": ["jingzi2", "yanwenzi"],
    # 左上像素小人、左中扫地机与黑猫、左下猫耳平板 (13 slots)
    "阿卡赛特/黏人心机": [
        "110", "tiandian", "feiwen", "aixin", "daiji", "shuiyi", "100", "99", "98_1", "98_2", "80_1",
        "80_2", "80_3",
    ],
    # 左侧独立小龙虾与脚边溪石 (7 slots)
    "青蒿/山涧趣事": ["MM120", "MM4", "MM3", "MM14", "MM2", "MM1", "MM0"],
}

MENU_TEXTS: dict[str, dict[str, str]] = {
    "zh": {
        "prompt": "背景显示开关（按 F3 / H 随时切换，隐藏背景时自动保留触摸特效）：",
        "hide": "隐藏背景（保留触摸特效）",
        "show": "恢复完整背景",
        "prompt_props": "背景与附带物件开关（按 F3 / H 随时切换）：",
        "hide_keep_props": "隐藏背景（保留人物附带物件）",
        "hide_with_props": "隐藏背景及附带物件（仅留人物）",
    },
    "en": {
        "prompt": "Background Toggle (Press F3 / H anytime; touch FX are preserved when hidden):",
        "hide": "Hide Background (Keep Touch FX)",
        "show": "Show Full Background",
        "prompt_props": "Background & Props Toggle (Press F3 / H anytime):",
        "hide_keep_props": "Hide Background (Keep Character Props)",
        "hide_with_props": "Hide Background & Props (Character Only)",
    },
    "ja": {
        "prompt": "背景表示切替（F3 / H キーでいつでも切替・非表示時もタッチエフェクト維持）：",
        "hide": "背景を非表示（タッチエフェクト維持）",
        "show": "背景を再表示",
        "prompt_props": "背景・付属小物表示切替（F3 / H キーでいつでも切替）：",
        "hide_keep_props": "背景を非表示（付属小物維持）",
        "hide_with_props": "背景と付属小物を非表示（キャラのみ）",
    },
}


def parse_start_submodels(cfg: dict[str, Any]) -> list[tuple[str, int]]:
    start_items = (cfg.get("motions") or {}).get("start") or []
    if not start_items:
        return []
    cmd = start_items[0].get("command") or ""
    subs: list[tuple[str, int]] = []
    for seg in cmd.split(";"):
        toks = seg.strip().split()
        if len(toks) == 3 and toks[0] == "add_submodel":
            subs.append((toks[1], int(toks[2])))
    return subs


def find_touch_fx_submodel_ids(cfg: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for grp, items in (cfg.get("motions") or {}).items():
        if grp in ("背景开关", "背景菜单"):
            continue
        for it in items:
            cmd = it.get("command") or ""
            for seg in cmd.split(";"):
                toks = seg.strip().split()
                if len(toks) >= 3 and toks[0] == "start_mtn":
                    ids.add(toks[1])
    return ids


def ensure_idle_empty_and_touch_only(sub_cfg_p: Path) -> str:
    """Add `idle_empty` to shared FX skeleton JSON and write `touch_only.config.json`.
    Returns relative path of `touch_only.config.json` from skin root."""
    sub_dir = sub_cfg_p.parent
    sc = json.loads(sub_cfg_p.read_text(encoding="utf-8-sig"))
    skel_p = sub_dir / sc["skeleton"]
    sk = json.loads(skel_p.read_text(encoding="utf-8-sig"))

    # Explicitly null out any non-clipping slot that has a default setup-pose attachment
    slot_nulls: dict[str, Any] = {}
    for sl in sk.get("slots") or []:
        sname = sl.get("name", "")
        att = sl.get("attachment")
        if att is not None and sname != "fx_clip":
            slot_nulls[sname] = {"attachment": [{"time": 0.0, "name": None}]}

    idle_empty_anim: dict[str, Any] = {"slots": slot_nulls} if slot_nulls else {}
    anims = sk.setdefault("animations", {})
    if anims.get("idle_empty") != idle_empty_anim:
        anims["idle_empty"] = idle_empty_anim
        skel_p.write_text(json.dumps(sk, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # Build touch_only.config.json preserving options.id and all touch motions
    tc = copy.deepcopy(sc)
    tmots = tc.setdefault("motions", {})
    tmots["idle"] = [{"name": "idle_empty", "file": "idle_empty", "file_loop": True}]
    if "start" in tmots:
        tmots["start"] = [{"name": "idle_empty", "file": "idle_empty"}]

    tc_p = sub_dir / "touch_only.config.json"
    tc_p.write_text(json.dumps(tc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return f"submodels/{sub_dir.name}/touch_only.config.json"


def is_idle_effectively_empty(sub_cfg_p: Path) -> bool:
    sc = json.loads(sub_cfg_p.read_text(encoding="utf-8-sig"))
    skel_p = sub_cfg_p.parent / sc["skeleton"]
    raw = skel_p.read_bytes()
    if not raw.lstrip().startswith(b"{"):
        return False
    sk = json.loads(raw.decode("utf-8-sig"))
    idle_a = (sk.get("animations") or {}).get("idle")
    return not idle_a or (not idle_a.get("bones") and not idle_a.get("slots"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Add/refresh Spine runtime Hide Background toggle.")
    parser.add_argument("--only", default="", help="Comma-separated doll/skin targets (skips overwriting full report).")
    args = parser.parse_args()
    only_set = {x.strip().replace("\\", "/") for x in args.only.split(",") if x.strip()}

    counts = {"A_orig_skip": 0, "B_pure_bg": 0, "C_pure_touch": 0, "D_shared_touch_only": 0}
    touch_only_written = 0
    skins_updated = 0
    details: list[dict[str, Any]] = []

    for main_cp in sorted(SPINE_ROOT.glob("*/*/.config.json")):
        sdir = main_cp.parent
        rel = f"{sdir.parent.name}/{sdir.name}"
        if only_set and rel not in only_set:
            continue
        cfg = json.loads(main_cp.read_text(encoding="utf-8-sig"))
        subs = parse_start_submodels(cfg)

        if not subs:
            counts["A_orig_skip"] += 1
            continue

        touch_ids = find_touch_fx_submodel_ids(cfg)

        # Classify each submodel
        remove_on_hide: list[str] = []
        readd_on_hide: list[tuple[str, int]] = []
        touch_only_rels: list[str] = []
        has_shared_touch = False
        has_pure_touch = False

        for sub_rel, order in subs:
            sub_cp = sdir / sub_rel
            sc = json.loads(sub_cp.read_text(encoding="utf-8-sig"))
            sid = (sc.get("options") or {}).get("id", "")
            if sid in touch_ids:
                if is_idle_effectively_empty(sub_cp):
                    # Class C: keep this pure touch FX submodel untouched!
                    has_pure_touch = True
                else:
                    # Class D: swap to touch_only.config.json
                    has_shared_touch = True
                    to_rel = ensure_idle_empty_and_touch_only(sub_cp)
                    touch_only_written += 1
                    touch_only_rels.append(to_rel)
                    remove_on_hide.append(sub_rel)
                    remove_on_hide.append(to_rel)
                    readd_on_hide.append((to_rel, order))
            else:
                remove_on_hide.append(sub_rel)

        if has_shared_touch:
            cls_name = "D_shared_touch_only"
        elif has_pure_touch:
            cls_name = "C_pure_touch"
        else:
            cls_name = "B_pure_bg"
        counts[cls_name] += 1

        hide_cmds = [f"remove_submodel {r}" for r in remove_on_hide] + [
            f"add_submodel {r} {o}" for r, o in readd_on_hide
        ]
        # On show_bg: remove any touch_only first, then re-add all original submodels cleanly
        show_cmds = [f"remove_submodel {r}" for r in touch_only_rels] + [
            f"add_submodel {r} {o}" for r, o in subs
        ]

        # Optional per-skin main-skeleton floating prop slots (hidden via EX native `slot_opacities`)
        prop_slots = EXTRA_HIDE_PROP_SLOTS.get(rel)
        prop_csv = ",".join(prop_slots) if prop_slots else ""
        if prop_csv:
            hide_cmd_str = "; ".join(hide_cmds + [f"slot_opacities set {prop_csv} 1 0"])
            hide_props_cmd_str = "; ".join(hide_cmds + [f"slot_opacities lock {prop_csv} 0 0"])
            show_cmd_str = "; ".join(show_cmds + [f"slot_opacities set {prop_csv} 1 0"])
        else:
            hide_cmd_str = "; ".join(hide_cmds)
            hide_props_cmd_str = ""
            show_cmd_str = "; ".join(show_cmds)

        # Clean reload_bg: remove all current submodels + any touch_only first, then re-add all in start order
        reload_rm_rels: list[str] = []
        for r in [sr for sr, _ in subs] + touch_only_rels:
            if r not in reload_rm_rels:
                reload_rm_rels.append(r)
        reload_parts = (
            [f"remove_submodel {r}" for r in reload_rm_rels]
            + [f"add_submodel {r} {o}" for r, o in subs]
        )
        if prop_csv:
            reload_parts.append(f"slot_opacities set {prop_csv} 1 0")
        reload_cmd_str = "; ".join(reload_parts)

        # Legacy Spine ASCII / Unity KeyCode -> official Windows VK map (lwtray GetAsyncKeyState)
        legacy_vk_remap = {
            97: 65,   # 'a' -> VK_A
            98: 66,   # 'b' -> VK_B
            99: 67,   # 'c' -> VK_C
            100: 68,  # 'd' -> VK_D
            101: 69,  # 'e' -> VK_E
            102: 70,  # 'f' -> VK_F
            103: 71,  # 'g' -> VK_G
            109: 77,  # 'm' -> VK_M
            110: 78,  # 'n' -> VK_N
        }

        # Update all 3 language configs identically
        for lang_code, lfn in LANG_SPECS:
            lp = sdir / lfn
            if not lp.is_file():
                continue
            ld = json.loads(lp.read_text(encoding="utf-8-sig"))
            mots = ld.setdefault("motions", {})
            mt = MENU_TEXTS[lang_code]

            if "reload_bg" in mots and mots["reload_bg"]:
                for ent in mots["reload_bg"]:
                    if isinstance(ent, dict):
                        ent["command"] = reload_cmd_str

            if prop_csv:
                mots["背景开关"] = [
                    {"name": "hide_bg", "file": "", "command": hide_cmd_str},
                    {"name": "hide_bg_and_props", "file": "", "command": hide_props_cmd_str},
                    {"name": "show_bg", "file": "", "command": show_cmd_str},
                ]
                mots["背景菜单"] = [
                    {
                        "name": "bg_toggle_menu",
                        "file": "",
                        "text": mt["prompt_props"],
                        "text_duration": 30000,
                        "choices": [
                            {"text": mt["hide_keep_props"], "next_mtn": "背景开关:hide_bg"},
                            {"text": mt["hide_with_props"], "next_mtn": "背景开关:hide_bg_and_props"},
                            {"text": mt["show"], "next_mtn": "背景开关:show_bg"},
                        ],
                    }
                ]
            else:
                mots["背景开关"] = [
                    {"name": "hide_bg", "file": "", "command": hide_cmd_str},
                    {"name": "show_bg", "file": "", "command": show_cmd_str},
                ]
                mots["背景菜单"] = [
                    {
                        "name": "bg_toggle_menu",
                        "file": "",
                        "text": mt["prompt"],
                        "text_duration": 30000,
                        "choices": [
                            {"text": mt["hide"], "next_mtn": "背景开关:hide_bg"},
                            {"text": mt["show"], "next_mtn": "背景开关:show_bg"},
                        ],
                    }
                ]

            kt = ld.setdefault("controllers", {}).setdefault("key_trigger", {"enabled": True, "items": []})
            kt["enabled"] = True
            items: list[dict[str, Any]] = []
            seen_inputs: set[int] = set()
            for it in kt.get("items") or []:
                dm = it.get("down_mtn")
                inp = it.get("input")
                if dm == "背景菜单" or inp in (104, 284, 72):
                    continue
                if dm == "reload_bg" and inp == 114:
                    inp = 82  # legacy ASCII 'r' (114 == VK_F3!) -> VK_R (82)
                elif inp in legacy_vk_remap:
                    inp = legacy_vk_remap[inp]
                if inp in (114, 72) or inp in seen_inputs:
                    continue
                seen_inputs.add(inp)
                new_it = dict(it)
                new_it["input"] = inp
                items.append(new_it)
            items.append({"input": 114, "down_mtn": "背景菜单"})  # VK_F3
            items.append({"input": 72, "down_mtn": "背景菜单"})   # VK_H
            kt["items"] = items

            lp.write_text(json.dumps(ld, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

        skins_updated += 1
        details.append({
            "skin": rel,
            "class": cls_name,
            "submodels": len(subs),
            "touch_only": touch_only_rels,
            "extra_hide_prop_slots": prop_slots or [],
        })

    report = {
        "counts": counts,
        "skins_updated": skins_updated,
        "touch_only_written": touch_only_written,
        "sample_details": details[:15],
    }
    if not only_set:
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
