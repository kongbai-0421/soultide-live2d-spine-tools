"""Full-fleet Voice & Subtitle Touch-Routing Auditor and Fixer for SoulTide.

Audits and fixes cross-body-part voice/subtitle routing across:
  1. All 109 Dress Spine packages
  2. All 54 原皮 Spine packages (strictly preserving `file == ""` voice-only touch groups)
  3. All 182 Live2D packages

Uses 3-signal fusion:
  - Signal 1: Explicit base CV filename tags (`_touch_head`, `_touch_breast`, `_touch_hand`, `_touch_hip`, `_touch_reaction`)
  - Signal 2: High-precision ZH + EN semantic body-part classification (vetoes cross-part leakage)
  - Signal 3: Official game Lua `CfgSoulActionGroupTable` `Type` (`801=head`, `901=hand`, `1001=chest`, `1101=leg`)
              + `CfgSoulSpineActionTable.ActionName` + canonical dress suffix (`_05/_06=hand`, `_07=leg`, `_08/_09=chest`, `_10=head`)

Keeps all 3 sibling language configs 100% synchronized:
  - Spine : `.config.json`, `config_en.config.json`, `config_ja.config.json`
  - Live2D: `.model3.json`, `model_en.model3.json`, `model_ja.model3.json`
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from batch_fx_exporter import FullI18nRepo, build_skin_catalog

SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
L2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
REPORT_PATH = TOOLS_DIR / "voice_routing_fix_report.json"

PROTECTED_RELS: set[tuple[str, str]] = set()

TYPE_TO_PART: dict[int, str] = {
    801: "head",
    901: "hand",
    1001: "chest",
    1101: "leg",
}

SPINE_GROUP_TO_PART: dict[str, str] = {
    "头": "head",
    "胸": "chest",
    "左手": "hand",
    "右手": "hand",
    "腿": "leg",
    "足": "foot",
}

L2D_GROUP_TO_PART: dict[str, str] = {
    "Tap头": "head",
    "Tap胸": "chest",
    "Tap手": "hand",
    "Tap臀部": "leg",
}

# ---------------------------------------------------------------------------
# Signal 1: Explicit Sound Filename Tags
# ---------------------------------------------------------------------------

SOUND_TAG_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("head", re.compile(r"(?:^|_)(?:touch_?head|head_?touch)(?:_|$|\d)", re.I)),
    ("chest", re.compile(r"(?:^|_)(?:touch_?(?:breast|chest|bra|boob)|(?:breast|chest|bra)_?touch)(?:_|$|\d)", re.I)),
    ("hand", re.compile(r"(?:^|_)(?:touch_?hand|hand_?touch)(?:_|$|\d)", re.I)),
    ("leg", re.compile(r"(?:^|_)(?:touch_?(?:hip|leg|thigh|butt)|(?:hip|leg)_?touch)(?:_|$|\d)", re.I)),
    ("foot", re.compile(r"(?:^|_)(?:touch_?(?:foot|feet|shoe)|(?:foot|feet)_?touch)(?:_|$|\d)", re.I)),
    ("reaction", re.compile(r"(?:^|_)touch_?reaction(?:_|$|\d)", re.I)),
    ("locked", re.compile(r"(?:^|_)touch_?locked(?:_|$|\d)", re.I)),
]


def detect_sound_tag(sound_path: str) -> str | None:
    stem = Path(sound_path).stem.lower() if sound_path else ""
    if not stem:
        return None
    for tag, pat in SOUND_TAG_RULES:
        if pat.search(stem):
            return tag
    return None


# ---------------------------------------------------------------------------
# Signal 2: High-Precision Semantic Body-Part Classifier (ZH + EN)
# ---------------------------------------------------------------------------

# Idiom/false-positive scrubbers applied before semantic regex
ZH_FALSE_POSITIVE_RE = re.compile(
    r"胸有成竹|天涯海角|角色|主角|配角|视角|角度|角落|嘴角|眼角|街角|三角|"
    r"头好晕|点头|抬头|回头|摇头|低头|转头|歪头|埋头|昂头|垂头|尽头|念头|从头|带头|开头|到头|"
    r"里头|外头|甜头|苦头|话头|拳头|骨头|石头|木头|镜头|源头|兆头|街头|桥头|床头|枕头|馒头|"
    r"斧头|罐头|浪头|风头|丫头|老头|年头|钟头|领头|出头|碰头|聚头|白头|矛头|箭头|眉头|"
    r"住手|放手|停手|下手|出手|动手|帮手|对手|高手|新手|老手|助手|猎手|水手|枪手|杀手|凶手|"
    r"黑手|插手|接手|交手|联手|顺手|随手|亲手|束手|棘手|拿手|得手|失手|分手|招手|挥手|摆手|"
    r"拍手|伸手|举手|抬手|背手|摊手|洗手|手下|手艺|手段|手工|手法|手笔|手续|手稿|手记|手册|"
    r"手杖|手捧花|手机|手表|手办|手电|手帕|手巾|围裙"
)

SEM_ZH_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "head",
        re.compile(
            r"(?:摸.{0,4}(?:头|脑袋|脑瓜|头发|发丝|耳朵|耳尖|猫耳|兔耳|狐耳|龙角|呆毛|刘海))"
            r"|(?:揉.{0,4}(?:头|脑袋|脑瓜|头发|耳朵|刘海))"
            r"|(?:摸摸头|摸头|梳头|理头发|捋头发|弄乱.{0,3}(?:头发|发型|刘海))"
            r"|(?:头发|发型|刘海|头饰|发饰|发卡|帽子|兔耳|猫耳|狐耳|兽耳|龙角|耳朵|头纱|呆毛|脑袋|脑瓜)"
        ),
    ),
    (
        "chest",
        re.compile(r"(?:胸口|胸部|胸前|心口|欧派|丰满|酥胸|文胸|胸罩|领口|事业线|胸腔|胸膛)"),
    ),
    (
        "hand",
        re.compile(
            r"(?:牵.{0,2}手|拉.{0,2}手|握.{0,3}手|十指|指尖|手指|手心|手掌|手背|手腕|手臂|手套|指甲|拉勾|握手|碰.{0,2}手|摸.{0,2}手|暖.{0,3}手|双手|扳手腕|掰.{0,1}手腕)"
        ),
    ),
    (
        "leg",
        re.compile(
            r"(?:大腿|小腿|双腿|美腿|腿上|腿软|腿环|膝盖|膝枕|裙底|裙子要掉|丝袜|黑丝|白丝|吊带袜|过膝袜|长筒袜|屁股|臀部|尾巴|猫尾|腰带|细腰|腰间)"
        ),
    ),
    (
        "foot",
        re.compile(r"(?:脚丫|脚趾|脚底|脚心|脚背|脚踝|玉足|双足|小脚|光脚|赤脚|裸足|足尖|足底|高跟鞋|靴子|凉鞋|拖鞋|鞋带)"),
    ),
]

# Explicit non-foot lower-body markers (used so `足` avoids tail/skirt/waist lines when a neutral line exists)
LEG_NOT_FOOT_RE = re.compile(r"(?:尾巴|猫尾|裙底|裙子要掉|屁股|臀部|腰带|细腰|腰间|大腿|腿环|膝枕)")

# Per-stem explicit disambiguation overrides where multi-part words appear in one line
STEM_SEMANTIC_OVERRIDE: dict[str, str] = {
    "juewa_dress2_07": "leg",        # "除了女仆装和猫耳外，本喵的制胜猫尾！" -> official 1101 leg/tail
    "juewa_touch_locked": "leg",     # "猫咪的尾巴碰不得。" -> tail/leg only (not chest)
    "silenus_dress1_07": "leg",      # "特意把裙子改短了……明明都染发了" -> official 1101 skirt/leg
    "amaneinori_dress1_09": "leg",   # "比起这里，毛茸茸的尾巴才更治愈~" -> explicitly mentions 尾巴
    "amaneinori_dress2_09": "leg",   # "腰带有点松了？" -> explicitly mentions 腰带
    "haliva_dress2_09": "leg",       # "裙、裙子要掉下去啦" -> explicitly mentions 裙子滑落
    "freesia_dress2_09": "hand",     # "约定好了，拉勾！" -> explicitly mentions 拉勾
    "sakuyamako_after_marriage_touch": "hand",  # "你是想和吾扳手腕吗？" -> hand
    "silenus_after_marriage_touch": "head",     # "就像是我的头发丝一样" -> head
}


def detect_semantic_parts(zh_text: str, stem: str = "") -> list[str]:
    low = stem.lower()
    if low in STEM_SEMANTIC_OVERRIDE:
        return [STEM_SEMANTIC_OVERRIDE[low]]
    if not zh_text:
        return []
    cleaned = ZH_FALSE_POSITIVE_RE.sub("", zh_text)
    found: list[str] = []
    for part, pat in SEM_ZH_RULES:
        if pat.search(cleaned):
            found.append(part)
    return found


def infer_dress_suffix_part(stem: str) -> str | None:
    """Canonical SoulTide dress CV numbering: _05/_06=hand, _07=leg, _08/_09=chest, _10=head."""
    m = re.search(r"dre[es]s\d+_(\d+)$", stem.lower())
    if not m:
        return None
    num = int(m.group(1))
    if num in (5, 6):
        return "hand"
    if num == 7:
        return "leg"
    if num in (8, 9):
        return "chest"
    if num == 10:
        return "head"
    return None


def infer_action_name_part(action_name: str) -> str | None:
    if not action_name:
        return None
    if action_name.endswith("-头"):
        return "head"
    if action_name.endswith("-手"):
        return "hand"
    if action_name.endswith("-腿"):
        return "leg"
    if action_name.endswith("-身体") or action_name.endswith("-胸"):
        return "chest"
    return None


# ---------------------------------------------------------------------------
# Build Official Metadata Index from Decompiled Lua Tables
# ---------------------------------------------------------------------------

def build_official_stem_index(repo: FullI18nRepo) -> tuple[dict[str, set[int]], dict[int, str]]:
    """Return (stem_lower -> set of CfgSoulActionGroupTable Types, spine_aid -> ActionName)."""
    stem_to_gtypes: dict[str, set[int]] = defaultdict(set)
    for _gid, body in repo.action_groups.items():
        mt = re.search(r"Type\s*=\s*(\d+)", body)
        if not mt:
            continue
        gtype = int(mt.group(1))
        for field in ("MoodActionID", "SoulResAction"):
            m = re.search(rf"{field}\s*=\s*\{{(.*?)\n\t\t\}}", body, re.S)
            if m:
                for aid_s in re.findall(r"\d{6,}", m.group(1)):
                    act = repo.action_map.get(int(aid_s))
                    if act and act["cv"]:
                        st = repo.resolve_cv(act["cv"])["sound_stem"].lower()
                        if st:
                            stem_to_gtypes[st].add(gtype)

    aid_to_aname: dict[int, str] = {}
    for aid, body in repo.spine_actions.items():
        m_an = re.search(r"ActionName\s*=\s*getI18NValue\((\d+)\)", body)
        if m_an:
            aid_to_aname[aid] = repo.get_i18n(int(m_an.group(1)))

    return stem_to_gtypes, aid_to_aname


def classify_dress_item(
    stem: str,
    zh_text: str,
    action_name: str,
    stem_to_gtypes: dict[str, set[int]],
) -> tuple[str | None, str]:
    """Classify a dress voice line into ('head'|'chest'|'hand'|'leg'|'foot'|None, reason)."""
    low = stem.lower()

    # 1. Explicit override / high-precision semantic signal (vetoes cross-part leakage)
    sem_parts = detect_semantic_parts(zh_text, low)
    if len(sem_parts) == 1:
        return sem_parts[0], "semantic"

    # 2. Explicit ActionName body-part tag (e.g. 情系站缘)
    an_part = infer_action_name_part(action_name)
    if an_part:
        return an_part, "action_name"

    # 3. Official CfgSoulActionGroupTable Type (801/901/1001/1101)
    gtypes = stem_to_gtypes.get(low, set())
    oparts = sorted({TYPE_TO_PART[t] for t in gtypes if t in TYPE_TO_PART})
    if len(oparts) == 1:
        return oparts[0], "official_type"
    if len(oparts) > 1:
        # Disambiguate multi-type via semantic overlap, then canonical dress suffix
        for sp in sem_parts:
            if sp in oparts:
                return sp, "official+semantic"
        suf = infer_dress_suffix_part(low)
        if suf and suf in oparts:
            return suf, "official+suffix"
        return oparts[0], "official_first"

    # 4. Canonical dress suffix fallback (_05.._10)
    suf = infer_dress_suffix_part(low)
    if suf:
        return suf, "dress_suffix"

    if sem_parts:
        return sem_parts[0], "semantic_first"
    return None, "neutral"


def is_neutral_text(zh_text: str, stem: str = "") -> bool:
    return len(detect_semantic_parts(zh_text, stem)) == 0


# ---------------------------------------------------------------------------
# Audit Helper (checks all 163 Spine & 182 Live2D configs for conflicts)
# ---------------------------------------------------------------------------

def audit_spine_pkg(
    pkg_dir: Path,
    stem_to_gtypes: dict[str, set[int]],
) -> list[dict[str, Any]]:
    cfg = json.loads((pkg_dir / ".config.json").read_text(encoding="utf-8-sig"))
    is_orig = pkg_dir.name == "原皮"
    mots = cfg.get("motions", {})
    conflicts: list[dict[str, Any]] = []
    for grp, gpart in SPINE_GROUP_TO_PART.items():
        for it in mots.get(grp, []):
            snd = it.get("sound", "")
            stem = Path(snd).stem if snd else ""
            low = stem.lower()
            txt = it.get("text", "")
            stag = detect_sound_tag(snd)
            if is_orig:
                # For 原皮 Spine: sound tag is authoritative
                if stag == "reaction" or "after_marriage_touch" in low:
                    conflicts.append({"group": grp, "kind": "reaction_leak", "stem": stem, "text": txt})
                elif stag in ("head", "chest", "hand", "leg", "foot"):
                    if stag != gpart and not (gpart == "foot" and stag == "leg"):
                        conflicts.append({"group": grp, "kind": f"sound_tag:{stag}", "stem": stem, "text": txt})
                elif stag == "locked" and low == "juewa_touch_locked" and gpart != "leg" and gpart != "foot":
                    conflicts.append({"group": grp, "kind": "semantic:leg", "stem": stem, "text": txt})
            else:
                sem = detect_semantic_parts(txt, low)
                for sp in sem:
                    if sp != gpart and not (gpart == "foot" and sp == "leg" and not LEG_NOT_FOOT_RE.search(txt)) and not (gpart == "leg" and sp == "foot"):
                        conflicts.append({"group": grp, "kind": f"semantic:{sp}", "stem": stem, "text": txt})
                # Also check if foot has tail/skirt/waist line
                if gpart == "foot" and LEG_NOT_FOOT_RE.search(txt):
                    conflicts.append({"group": grp, "kind": "foot_tail_or_skirt", "stem": stem, "text": txt})
    return conflicts


def audit_live2d_pkg(
    pkg_dir: Path,
    stem_to_gtypes: dict[str, set[int]],
) -> list[dict[str, Any]]:
    cfg = json.loads((pkg_dir / ".model3.json").read_text(encoding="utf-8-sig"))
    is_base = pkg_dir.name.startswith("原皮")
    mots = cfg.get("FileReferences", {}).get("Motions", {})
    conflicts: list[dict[str, Any]] = []
    # Check cross-dress tag leak in non-base skins
    dress_tags = Counter()
    if not is_base:
        for grp in ("Tap头", "Tap胸", "Tap手", "Tap臀部"):
            for it in mots.get(grp, []):
                m = re.search(r"(dre[es]s\d+)", Path(it.get("Sound", "")).stem.lower())
                if m:
                    dress_tags[m.group(1).replace("drees", "dress")] += 1
    dominant_dress = dress_tags.most_common(1)[0][0] if dress_tags else None

    for grp, gpart in L2D_GROUP_TO_PART.items():
        for it in mots.get(grp, []):
            snd = it.get("Sound", "")
            stem = Path(snd).stem if snd else ""
            low = stem.lower()
            txt = it.get("Text", "")
            stag = detect_sound_tag(snd)
            if is_base:
                if grp == "Tap臀部" and (stag == "reaction" or "after_marriage_touch" in low):
                    conflicts.append({"group": grp, "kind": "reaction_in_hip", "stem": stem, "text": txt})
                elif stag in ("head", "chest", "hand", "leg", "foot") and stag != gpart:
                    conflicts.append({"group": grp, "kind": f"sound_tag:{stag}", "stem": stem, "text": txt})
                elif stag == "locked" and low == "juewa_touch_locked" and gpart != "leg":
                    conflicts.append({"group": grp, "kind": "semantic:leg", "stem": stem, "text": txt})
            else:
                if "_touch_" in low:
                    conflicts.append({"group": grp, "kind": "base_touch_leak", "stem": stem, "text": txt})
                m = re.search(r"(dre[es]s\d+)", low)
                if m and dominant_dress and m.group(1).replace("drees", "dress") != dominant_dress:
                    conflicts.append({"group": grp, "kind": f"cross_skin:{m.group(1)}", "stem": stem, "text": txt})
                sem = detect_semantic_parts(txt, low)
                for sp in sem:
                    if sp != gpart and not (gpart == "leg" and sp == "foot"):
                        conflicts.append({"group": grp, "kind": f"semantic:{sp}", "stem": stem, "text": txt})
    return conflicts


# ---------------------------------------------------------------------------
# Fixer 1: Dress Spine (108 editable packages)
# ---------------------------------------------------------------------------

def _load_3lang_spine(pkg_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        "zh": json.loads((pkg_dir / ".config.json").read_text(encoding="utf-8-sig")),
        "en": json.loads((pkg_dir / "config_en.config.json").read_text(encoding="utf-8-sig")),
        "ja": json.loads((pkg_dir / "config_ja.config.json").read_text(encoding="utf-8-sig")),
    }


def _save_3lang_spine(pkg_dir: Path, cfgs: dict[str, dict[str, Any]]) -> None:
    mapping = {
        "zh": pkg_dir / ".config.json",
        "en": pkg_dir / "config_en.config.json",
        "ja": pkg_dir / "config_ja.config.json",
    }
    for lang, p in mapping.items():
        p.write_text(json.dumps(cfgs[lang], ensure_ascii=False, indent=2), encoding="utf-8")


def fix_dress_spine_pkg(
    pkg_dir: Path,
    skin_meta: dict[str, Any] | None,
    stem_to_gtypes: dict[str, set[int]],
    aid_to_aname: dict[int, str],
    apply: bool,
) -> dict[str, Any]:
    cfgs = _load_3lang_spine(pkg_dir)
    zh_mots = cfgs["zh"]["motions"]
    en_mots = cfgs["en"]["motions"]
    ja_mots = cfgs["ja"]["motions"]

    # Build unified action registry from 誓约模式全动作 (and 闲聊与问答 / 誓约专属 / touch groups)
    # Keyed by action_id (int) if parseable from name, plus fallback by sound_stem.
    # For each key, store {"zh": item, "en": item, "ja": item, "aid": int|None, "stem": str}
    entries_by_aid: dict[int, dict[str, Any]] = {}
    entries_by_stem: dict[str, dict[str, Any]] = {}
    ordered_keys: list[tuple[int | None, str]] = []

    def _clean_item(item: dict[str, Any]) -> dict[str, Any]:
        c = copy.deepcopy(item)
        nm = c.get("name", "")
        if nm.startswith("marry_sp_"):
            nm = nm[len("marry_sp_"):]
        elif nm.startswith("marry_"):
            nm = nm[len("marry_"):]
        elif nm.startswith("normal_"):
            nm = nm[len("normal_"):]
        c["name"] = nm
        return c

    def _register_group(grp_name: str) -> None:
        zl = zh_mots.get(grp_name, [])
        el = en_mots.get(grp_name, [])
        jl = ja_mots.get(grp_name, [])
        if not (len(zl) == len(el) == len(jl)):
            raise ValueError(f"{pkg_dir} group '{grp_name}' 3-lang length mismatch: {len(zl)}/{len(el)}/{len(jl)}")
        for zi, ei, ji in zip(zl, el, jl):
            cz, ce, cj = _clean_item(zi), _clean_item(ei), _clean_item(ji)
            m_aid = re.match(r"^(\d+)_", cz.get("name", ""))
            aid = int(m_aid.group(1)) if m_aid else None
            stem = Path(cz.get("sound", "")).stem.lower() if cz.get("sound") else ""
            rec = {"zh": cz, "en": ce, "ja": cj, "aid": aid, "stem": stem}
            if aid is not None and aid not in entries_by_aid:
                entries_by_aid[aid] = rec
                ordered_keys.append((aid, stem))
            if stem and stem not in entries_by_stem:
                entries_by_stem[stem] = rec
                if aid is None:
                    ordered_keys.append((None, stem))

    for g in ("誓约模式全动作", "誓约专属", "闲聊与问答", "头", "胸", "左手", "右手", "腿", "足"):
        if g in zh_mots:
            _register_group(g)

    # Determine touch pool (TouchFeedback + MarryAction) vs standby/greet neutral pool
    touch_records: list[dict[str, Any]] = []
    seen_rec_ids: set[int] = set()
    if skin_meta:
        cf = skin_meta["ctrl_fields"]
        for aid in list(cf.get("TouchFeedback", [])) + list(cf.get("MarryAction", [])):
            rec = entries_by_aid.get(aid)
            if rec is not None and id(rec) not in seen_rec_ids:
                seen_rec_ids.add(id(rec))
                touch_records.append(rec)
    if not touch_records:
        # Fallback: existing items in the 6 touch groups
        for g in ("头", "胸", "左手", "右手", "腿", "足"):
            for zi in zh_mots.get(g, []):
                stem = Path(zi.get("sound", "")).stem.lower() if zi.get("sound") else ""
                rec = entries_by_stem.get(stem)
                if rec is not None and id(rec) not in seen_rec_ids:
                    seen_rec_ids.add(id(rec))
                    touch_records.append(rec)

    # Classify every touch record
    buckets: dict[str, list[dict[str, Any]]] = {
        "head": [],
        "chest": [],
        "hand": [],
        "leg": [],
        "foot": [],
        "neutral": [],
    }
    for rec in touch_records:
        aid = rec["aid"]
        aname = aid_to_aname.get(aid, "") if aid is not None else ""
        part, _reason = classify_dress_item(rec["stem"], rec["zh"].get("text", ""), aname, stem_to_gtypes)
        if part is None:
            buckets["neutral"].append(rec)
        else:
            buckets[part].append(rec)

    # Build neutral fallback pool (prefer neutral touch lines -> StandbyAction -> neutral greetings -> any non-conflicting line)
    neutral_pool: list[dict[str, Any]] = list(buckets["neutral"])
    neutral_seen = {id(r) for r in neutral_pool}

    def _add_neutral_if_clean(rec: dict[str, Any] | None) -> None:
        if rec is None or id(rec) in neutral_seen:
            return
        txt = rec["zh"].get("text", "")
        if is_neutral_text(txt, rec["stem"]):
            neutral_seen.add(id(rec))
            neutral_pool.append(rec)

    # Prefer StandbyAction first, then non-conflicting touch items (without semantic body-part mentions), then greetings
    if skin_meta:
        cf = skin_meta["ctrl_fields"]
        if cf.get("StandbyAction") in entries_by_aid:
            _add_neutral_if_clean(entries_by_aid[cf["StandbyAction"]])
    for rec in touch_records:
        _add_neutral_if_clean(rec)
    if skin_meta:
        cf = skin_meta["ctrl_fields"]
        for k in ("MorningGreetings", "NoonGreetings", "EveningGreetings"):
            if cf.get(k) in entries_by_aid:
                _add_neutral_if_clean(entries_by_aid[cf[k]])
    for aid, rec in entries_by_aid.items():
        _add_neutral_if_clean(rec)

    def _dedup_recs(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for r in recs:
            key = r["stem"] or r["zh"].get("name", "")
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    # Assemble the 6 touch groups cleanly!
    head_list = _dedup_recs(buckets["head"])
    chest_list = _dedup_recs(buckets["chest"])
    hand_list = _dedup_recs(buckets["hand"])
    leg_list = _dedup_recs(buckets["leg"] + buckets["foot"])
    foot_dedicated = _dedup_recs(buckets["foot"])
    # For 足: use dedicated foot lines if any; else non-tail/skirt/waist leg lines; else neutral pool (avoiding tail/skirt!)
    leg_ok_for_foot = [r for r in buckets["leg"] if not LEG_NOT_FOOT_RE.search(r["zh"].get("text", ""))]
    foot_list = foot_dedicated or _dedup_recs(leg_ok_for_foot)

    # Guarantee non-empty for every group using strictly neutral fallback lines
    def _ensure_non_empty(lst: list[dict[str, Any]], offset: int) -> list[dict[str, Any]]:
        if lst:
            return lst
        if neutral_pool:
            pick = neutral_pool[offset % len(neutral_pool)]
            return [pick]
        # Ultimate fallback: any record in package
        return [touch_records[0]] if touch_records else []

    head_final = _ensure_non_empty(head_list, 0)
    chest_final = _ensure_non_empty(chest_list, 1)
    lhand_final = _ensure_non_empty(hand_list, 2)
    rhand_final = list(reversed(lhand_final)) if len(lhand_final) >= 2 else list(lhand_final)
    leg_final = _ensure_non_empty(leg_list, 3)
    foot_final = _ensure_non_empty(foot_list, 4)

    new_groups = {
        "头": head_final,
        "左手": lhand_final,
        "右手": rhand_final,
        "胸": chest_final,
        "腿": leg_final,
        "足": foot_final,
    }

    changed = False
    for grp, recs in new_groups.items():
        if grp not in zh_mots:
            continue
        old_stems = [it.get("sound", "") for it in zh_mots[grp]]
        new_stems = [r["zh"].get("sound", "") for r in recs]
        if old_stems != new_stems:
            changed = True
        if apply:
            cfgs["zh"]["motions"][grp] = [copy.deepcopy(r["zh"]) for r in recs]
            cfgs["en"]["motions"][grp] = [copy.deepcopy(r["en"]) for r in recs]
            cfgs["ja"]["motions"][grp] = [copy.deepcopy(r["ja"]) for r in recs]

    if apply and changed:
        _save_3lang_spine(pkg_dir, cfgs)

    return {
        "changed": changed,
        "counts": {g: len(recs) for g, recs in new_groups.items()},
    }


# ---------------------------------------------------------------------------
# Fixer 2: 原皮 Spine (54 packages)
# ---------------------------------------------------------------------------

def fix_orig_spine_pkg(pkg_dir: Path, apply: bool) -> dict[str, Any]:
    cfgs = _load_3lang_spine(pkg_dir)
    zh_mots = cfgs["zh"]["motions"]
    en_mots = cfgs["en"]["motions"]
    ja_mots = cfgs["ja"]["motions"]

    # Collect all items currently in the 6 touch groups + 闲聊与问答, keyed by sound path
    by_sound: dict[str, dict[str, dict[str, Any]]] = {}
    grp_items: dict[str, list[str]] = {}
    for grp in ("头", "胸", "左手", "右手", "腿", "足", "闲聊与问答"):
        zl = zh_mots.get(grp, [])
        el = en_mots.get(grp, [])
        jl = ja_mots.get(grp, [])
        if not (len(zl) == len(el) == len(jl)):
            raise ValueError(f"{pkg_dir} 原皮 group '{grp}' 3-lang mismatch: {len(zl)}/{len(el)}/{len(jl)}")
        grp_items[grp] = []
        for zi, ei, ji in zip(zl, el, jl):
            snd = zi.get("sound", "")
            grp_items[grp].append(snd)
            if snd and snd not in by_sound:
                # Enforce voice-only invariant (file == "")
                cz, ce, cj = copy.deepcopy(zi), copy.deepcopy(ei), copy.deepcopy(ji)
                cz["file"] = ""
                ce["file"] = ""
                cj["file"] = ""
                by_sound[snd] = {"zh": cz, "en": ce, "ja": cj}

    def _collect_by_tag(allowed_tags: set[str], source_grps: tuple[str, ...], ban_stems: set[str] | None = None) -> list[str]:
        res: list[str] = []
        seen: set[str] = set()
        for g in source_grps:
            for snd in grp_items.get(g, []):
                if not snd or snd in seen:
                    continue
                low = Path(snd).stem.lower()
                if ban_stems and low in ban_stems:
                    continue
                stag = detect_sound_tag(snd)
                if stag in allowed_tags:
                    seen.add(snd)
                    res.append(snd)
        return res

    head_snds = _collect_by_tag({"head"}, ("头", "胸", "左手", "右手", "腿", "足"))
    chest_snds = _collect_by_tag({"chest", "locked"}, ("胸", "头", "左手", "右手", "腿", "足"), ban_stems={"juewa_touch_locked"})
    hand_snds = _collect_by_tag({"hand"}, ("左手", "右手", "胸", "头", "腿", "足"))
    leg_snds = _collect_by_tag({"leg", "locked"}, ("腿", "足", "胸", "头", "左手", "右手"))

    # Keep any dropped reaction/after_marriage sounds referenced in 闲聊与问答 so 0 .ogg files become orphaned
    kept_touch_snds = set(head_snds) | set(chest_snds) | set(hand_snds) | set(leg_snds)
    chat_snds = list(grp_items.get("闲聊与问答", []))
    chat_seen = set(chat_snds)
    for g in ("头", "胸", "左手", "右手", "腿", "足"):
        for snd in grp_items.get(g, []):
            if snd and snd not in kept_touch_snds and snd not in chat_seen:
                chat_seen.add(snd)
                chat_snds.append(snd)

    new_plan = {
        "头": ("head", head_snds),
        "胸": ("chest", chest_snds),
        "左手": ("lhand", hand_snds),
        "右手": ("rhand", list(reversed(hand_snds)) if len(hand_snds) >= 2 else list(hand_snds)),
        "腿": ("leg", leg_snds),
        "足": ("foot", list(reversed(leg_snds)) if len(leg_snds) >= 2 else list(leg_snds)),
    }

    changed = False
    for grp, (tag, snds) in new_plan.items():
        if not snds:
            raise ValueError(f"{pkg_dir} 原皮 group '{grp}' would become empty!")
        if grp_items.get(grp, []) != snds:
            changed = True
        if apply:
            for lang in ("zh", "en", "ja"):
                new_list = []
                for idx, snd in enumerate(snds):
                    it = copy.deepcopy(by_sound[snd][lang])
                    it["name"] = f"{tag}_{idx:02d}"
                    it["file"] = ""
                    new_list.append(it)
                cfgs[lang]["motions"][grp] = new_list

    if chat_snds != grp_items.get("闲聊与问答", []):
        changed = True
        if apply:
            extra_start = len(grp_items.get("闲聊与问答", []))
            for lang in ("zh", "en", "ja"):
                cur_list = list(cfgs[lang]["motions"].get("闲聊与问答", []))
                for offset, snd in enumerate(chat_snds[extra_start:]):
                    it = copy.deepcopy(by_sound[snd][lang])
                    it["name"] = f"chat_touch_{offset:02d}"
                    it["file"] = ""
                    cur_list.append(it)
                cfgs[lang]["motions"]["闲聊与问答"] = cur_list

    if apply and changed:
        _save_3lang_spine(pkg_dir, cfgs)

    return {
        "changed": changed,
        "counts": {g: len(s) for g, (_, s) in new_plan.items()},
        "chat_added": len(chat_snds) - len(grp_items.get("闲聊与问答", [])),
    }


# ---------------------------------------------------------------------------
# Fixer 3: Live2D (all 182 packages)
# ---------------------------------------------------------------------------

def _load_3lang_l2d(pkg_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        "zh": json.loads((pkg_dir / ".model3.json").read_text(encoding="utf-8-sig")),
        "en": json.loads((pkg_dir / "model_en.model3.json").read_text(encoding="utf-8-sig")),
        "ja": json.loads((pkg_dir / "model_ja.model3.json").read_text(encoding="utf-8-sig")),
    }


def _save_3lang_l2d(pkg_dir: Path, cfgs: dict[str, dict[str, Any]]) -> None:
    mapping = {
        "zh": pkg_dir / ".model3.json",
        "en": pkg_dir / "model_en.model3.json",
        "ja": pkg_dir / "model_ja.model3.json",
    }
    for lang, p in mapping.items():
        p.write_text(json.dumps(cfgs[lang], ensure_ascii=False, indent=2), encoding="utf-8")


def fix_live2d_pkg(
    pkg_dir: Path,
    stem_to_gtypes: dict[str, set[int]],
    apply: bool,
) -> dict[str, Any]:
    cfgs = _load_3lang_l2d(pkg_dir)
    zh_mots = cfgs["zh"]["FileReferences"]["Motions"]
    en_mots = cfgs["en"]["FileReferences"]["Motions"]
    ja_mots = cfgs["ja"]["FileReferences"]["Motions"]

    is_base = pkg_dir.name.startswith("原皮")
    changed = False
    moves: list[str] = []

    def _triple_list(grp: str) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
        zl = zh_mots.get(grp, [])
        el = en_mots.get(grp, [])
        jl = ja_mots.get(grp, [])
        if not (len(zl) == len(el) == len(jl)):
            raise ValueError(f"{pkg_dir} L2D group '{grp}' 3-lang mismatch: {len(zl)}/{len(el)}/{len(jl)}")
        return list(zip(zl, el, jl))

    def _set_triple(grp: str, triples: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]) -> None:
        zh_mots[grp] = [copy.deepcopy(t[0]) for t in triples]
        en_mots[grp] = [copy.deepcopy(t[1]) for t in triples]
        ja_mots[grp] = [copy.deepcopy(t[2]) for t in triples]

    def _append_unique(grp: str, triple: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]) -> None:
        cur = _triple_list(grp)
        sig = (triple[0].get("File", ""), triple[0].get("Sound", ""), triple[0].get("Text", ""))
        existing = {(t[0].get("File", ""), t[0].get("Sound", ""), t[0].get("Text", "")) for t in cur}
        if sig not in existing:
            cur.append(triple)
            _set_triple(grp, cur)

    if is_base:
        # 1. Move Touch_Reaction & After_Marriage_Touch OUT of Tap臀部 into TouchSpecial (when Tap臀部 has real Touch_Hip)
        if "Tap臀部" in zh_mots:
            hip_triples = _triple_list("Tap臀部")
            has_real_hip = any("touch_hip" in Path(t[0].get("Sound", "")).stem.lower() for t in hip_triples)
            if has_real_hip:
                kept_hip = []
                moved_hip = []
                for t in hip_triples:
                    low = Path(t[0].get("Sound", "")).stem.lower()
                    stag = detect_sound_tag(t[0].get("Sound", ""))
                    if stag == "reaction" or "after_marriage_touch" in low:
                        moved_hip.append(t)
                    else:
                        kept_hip.append(t)
                if moved_hip and kept_hip:
                    changed = True
                    moves.append(f"Tap臀部->TouchSpecial:{len(moved_hip)}")
                    if apply:
                        _set_triple("Tap臀部", kept_hip)
                        for t in moved_hip:
                            _append_unique("TouchSpecial", t)

        # 2. Remove Aurora_Touch_Hand_05 and Juewa_Touch_Locked from Tap胸 (already in Tap手 / Tap臀部)
        if "Tap胸" in zh_mots:
            chest_triples = _triple_list("Tap胸")
            kept_chest = []
            dropped_chest = []
            for t in chest_triples:
                low = Path(t[0].get("Sound", "")).stem.lower()
                stag = detect_sound_tag(t[0].get("Sound", ""))
                if (stag in ("head", "hand", "leg", "foot")) or low == "juewa_touch_locked":
                    dropped_chest.append(t)
                else:
                    kept_chest.append(t)
            if dropped_chest and kept_chest:
                changed = True
                moves.append(f"Tap胸_drop:{[Path(t[0].get('Sound','')).stem for t in dropped_chest]}")
                if apply:
                    _set_triple("Tap胸", kept_chest)
    else:
        # Non-base Live2D skin
        # Detect dominant dress tag (handles drees typo in 叶隐琉璃/绵绵小懒虫 and 不断的红线)
        dress_tags = Counter()
        for grp in ("Tap头", "Tap胸", "Tap手", "Tap臀部"):
            for it in zh_mots.get(grp, []):
                m = re.search(r"(dre[es]s\d+)", Path(it.get("Sound", "")).stem.lower())
                if m:
                    dress_tags[m.group(1).replace("drees", "dress")] += 1
        dominant_dress = dress_tags.most_common(1)[0][0] if dress_tags else None
        # Special guard: for 叶隐琉璃/绵绵小懒虫 -> dress3, 不断的红线 -> dress4
        if pkg_dir.parent.name == "叶隐琉璃" and pkg_dir.name == "绵绵小懒虫":
            dominant_dress = "dress3"
        elif pkg_dir.parent.name == "叶隐琉璃" and pkg_dir.name == "不断的红线":
            dominant_dress = "dress4"

        bound_tap_grps = {ha.get("Motion", "") for ha in cfgs["zh"].get("HitAreas", [])}
        part_to_l2d = {"head": "Tap头", "chest": "Tap胸", "hand": "Tap手", "leg": "Tap臀部", "foot": "Tap臀部"}

        # Check all non-tap groups to know which sounds already exist elsewhere (Morning/Noon/Evening/Archive)
        non_tap_sounds: set[str] = set()
        for g, items in zh_mots.items():
            if g not in ("Tap头", "Tap胸", "Tap手", "Tap臀部", "Tap躯干"):
                for it in items:
                    if it.get("Sound"):
                        non_tap_sounds.add(it["Sound"].lower())

        # Collect current triples per Tap* group
        cur_taps: dict[str, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = {
            g: _triple_list(g) for g in ("Tap头", "Tap胸", "Tap手", "Tap臀部") if g in zh_mots
        }
        new_taps: dict[str, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = {g: [] for g in cur_taps}
        pending_reroutes: list[tuple[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = []
        removed_to_archive: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []

        for grp, triples in cur_taps.items():
            gpart = L2D_GROUP_TO_PART[grp]
            for t in triples:
                snd = t[0].get("Sound", "")
                stem = Path(snd).stem if snd else ""
                low = stem.lower()
                txt = t[0].get("Text", "")

                # 1. Drop cross-skin dress leak (e.g. drees4 inside 绵绵小懒虫)
                md = re.search(r"(dre[es]s\d+)", low)
                if md and dominant_dress and md.group(1).replace("drees", "dress") != dominant_dress:
                    changed = True
                    moves.append(f"{grp}_drop_cross_skin:{stem}")
                    continue

                # 2. Check strict semantic body-part conflict
                sem = detect_semantic_parts(txt, low)
                sem_conflict = [sp for sp in sem if sp != gpart and not (gpart == "leg" and sp == "foot")]
                if sem_conflict:
                    target_part = sem_conflict[0]
                    target_grp = part_to_l2d[target_part]
                    changed = True
                    # If this is a time greeting (e.g. _01/_02/_03) already in Morning/Noon/Evening, just drop from wrong Tap group!
                    if snd.lower() in non_tap_sounds and re.search(r"dre[es]s\d+_0[1-4]$", low):
                        moves.append(f"{grp}_drop_greet:{stem}")
                    elif target_grp in new_taps and target_grp in bound_tap_grps:
                        moves.append(f"{grp}->{target_grp}:{stem}")
                        pending_reroutes.append((target_grp, t))
                    else:
                        moves.append(f"{grp}->Archive:{stem}")
                        removed_to_archive.append(t)
                    continue

                # 3. Check official ActionGroup Type conflict for After_Marriage_* dumped into Tap头
                #    (only reroute if semantically neutral — never override explicit head semantics!)
                if "after_marriage" in low and grp == "Tap头" and not sem:
                    gtypes = stem_to_gtypes.get(low, set())
                    oparts = sorted({TYPE_TO_PART[x] for x in gtypes if x in TYPE_TO_PART})
                    if oparts and "head" not in oparts:
                        target_grp = part_to_l2d[oparts[0]]
                        if target_grp in new_taps and target_grp in bound_tap_grps:
                            changed = True
                            moves.append(f"{grp}->{target_grp}:{stem}")
                            pending_reroutes.append((target_grp, t))
                            continue

                new_taps[grp].append(t)

        # Apply reroutes (deduped)
        for tgrp, t in pending_reroutes:
            sig = (t[0].get("File", ""), t[0].get("Sound", ""), t[0].get("Text", ""))
            existing = {(x[0].get("File", ""), x[0].get("Sound", ""), x[0].get("Text", "")) for x in new_taps[tgrp]}
            if sig not in existing:
                new_taps[tgrp].append(t)

        # Safety: ensure no bound Tap* group becomes empty
        for grp in list(new_taps.keys()):
            if not new_taps[grp]:
                # Restore a neutral item from original group or fallback to original if all conflicted
                neutral_orig = [t for t in cur_taps[grp] if is_neutral_text(t[0].get("Text", ""), Path(t[0].get("Sound", "")).stem)]
                new_taps[grp] = neutral_orig[:1] if neutral_orig else cur_taps[grp][:1]

        if changed and apply:
            for grp, triples in new_taps.items():
                _set_triple(grp, triples)
            for t in removed_to_archive:
                _append_unique("Archive", t)

    if apply and changed:
        _save_3lang_l2d(pkg_dir, cfgs)

    return {"changed": changed, "moves": moves}


# ---------------------------------------------------------------------------
# Main Driver
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and fix touch-trigger voice routing across Spine & Live2D.")
    parser.add_argument("--apply", action="store_true", help="Write changes to disk (default is dry-run audit)")
    args = parser.parse_args()

    repo = FullI18nRepo()
    stem_to_gtypes, aid_to_aname = build_official_stem_index(repo)
    catalog = build_skin_catalog(repo)
    skin_by_pair = {(sk["char_name"], sk["dress_name"]): sk for sk in catalog}

    spine_dirs = sorted(p.parent for p in SPINE_ROOT.glob("*/*/.config.json"))
    l2d_dirs = sorted(p.parent for p in L2D_ROOT.glob("*/*/.model3.json"))

    # --- Pre-fix Audit ---
    pre_spine_conflicts: dict[str, list[dict[str, Any]]] = {}
    for sd in spine_dirs:
        rel = f"{sd.parent.name}/{sd.name}"
        c = audit_spine_pkg(sd, stem_to_gtypes)
        if c:
            pre_spine_conflicts[rel] = c

    pre_l2d_conflicts: dict[str, list[dict[str, Any]]] = {}
    for ld in l2d_dirs:
        rel = f"{ld.parent.name}/{ld.name}"
        c = audit_live2d_pkg(ld, stem_to_gtypes)
        if c:
            pre_l2d_conflicts[rel] = c

    # --- Apply / Dry-Run Fixes ---
    dress_changed = 0
    orig_changed = 0
    l2d_changed = 0
    protected_audit: dict[str, Any] = {}
    fix_details: dict[str, Any] = {"dress_spine": {}, "orig_spine": {}, "live2d": {}}

    for sd in spine_dirs:
        pair = (sd.parent.name, sd.name)
        rel = f"{pair[0]}/{pair[1]}"
        if pair in PROTECTED_RELS:
            protected_audit[f"spine/{rel}"] = pre_spine_conflicts.get(rel, [])
            continue
        if sd.name == "原皮":
            res = fix_orig_spine_pkg(sd, apply=args.apply)
            if res["changed"]:
                orig_changed += 1
                fix_details["orig_spine"][rel] = res
        else:
            res = fix_dress_spine_pkg(sd, skin_by_pair.get(pair), stem_to_gtypes, aid_to_aname, apply=args.apply)
            if res["changed"]:
                dress_changed += 1
                fix_details["dress_spine"][rel] = res

    for ld in l2d_dirs:
        pair = (ld.parent.name, ld.name)
        rel = f"{pair[0]}/{pair[1]}"
        if pair in PROTECTED_RELS:
            protected_audit[f"live2d/{rel}"] = pre_l2d_conflicts.get(rel, [])
            continue
        res = fix_live2d_pkg(ld, stem_to_gtypes, apply=args.apply)
        if res["changed"]:
            l2d_changed += 1
            fix_details["live2d"][rel] = res

    # --- Post-fix Audit (only meaningful when --apply) ---
    post_spine_conflicts: dict[str, list[dict[str, Any]]] = {}
    post_l2d_conflicts: dict[str, list[dict[str, Any]]] = {}
    if args.apply:
        for sd in spine_dirs:
            pair = (sd.parent.name, sd.name)
            rel = f"{pair[0]}/{pair[1]}"
            c = audit_spine_pkg(sd, stem_to_gtypes)
            if c:
                post_spine_conflicts[rel] = c
        for ld in l2d_dirs:
            pair = (ld.parent.name, ld.name)
            rel = f"{pair[0]}/{pair[1]}"
            c = audit_live2d_pkg(ld, stem_to_gtypes)
            if c:
                post_l2d_conflicts[rel] = c

    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "total_spine": len(spine_dirs),
        "total_live2d": len(l2d_dirs),
        "pre_spine_conflict_pkgs": len(pre_spine_conflicts),
        "pre_spine_conflict_items": sum(len(v) for v in pre_spine_conflicts.values()),
        "pre_l2d_conflict_pkgs": len(pre_l2d_conflicts),
        "pre_l2d_conflict_items": sum(len(v) for v in pre_l2d_conflicts.values()),
        "dress_spine_changed": dress_changed,
        "orig_spine_changed": orig_changed,
        "live2d_changed": l2d_changed,
        "post_spine_conflict_pkgs_excl_protected": len([k for k in post_spine_conflicts if tuple(k.split("/", 1)) not in PROTECTED_RELS]),
        "post_l2d_conflict_pkgs_excl_protected": len([k for k in post_l2d_conflicts if tuple(k.split("/", 1)) not in PROTECTED_RELS]),
        "protected_readonly_audit": protected_audit,
    }
    report = {
        "summary": summary,
        "pre_spine_conflicts": pre_spine_conflicts,
        "pre_l2d_conflicts": pre_l2d_conflicts,
        "post_spine_conflicts": post_spine_conflicts,
        "post_l2d_conflicts": post_l2d_conflicts,
        "fix_details": fix_details,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.apply:
        rem_sp = {k: v for k, v in post_spine_conflicts.items() if tuple(k.split("/", 1)) not in PROTECTED_RELS}
        rem_l2 = {k: v for k, v in post_l2d_conflicts.items() if tuple(k.split("/", 1)) not in PROTECTED_RELS}
        if rem_sp:
            print("REMAINING SPINE CONFLICTS:", json.dumps(rem_sp, ensure_ascii=False, indent=2))
        if rem_l2:
            print("REMAINING LIVE2D CONFLICTS:", json.dumps(rem_l2, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
