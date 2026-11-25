"""Batch builder for all SoulTide Live2DViewerEX packages.

Reads read-only SoulTide AssetBundles and decompiled Lua configs, inherits verified
ScaleFactor/PositionX/PositionY from E:\\A灵魂潮汐\\备份\\live2d, enforces strict
skin voice isolation, 0-curve menu_silent.motion3.json, VK key codes, minimal
.moc3-verified HitAreas, and single Idle motion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from soultide_common import (
    CDN_ROOT,
    DECOMPILED_DIR,
    LuaTableRepo,
    extract_wav_bytes,
    load_ab,
    parse_lua_flat_table,
    write_json,
)

L2D_AB_DIR = CDN_ROOT / "20_live2d/live2d_resources"
CV_AB_DIR = CDN_ROOT / "06_sounds/cv"
BACKUP_L2D_DIR = Path(r"E:\A灵魂潮汐\备份\live2d")
OUT_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")

INVALID_WIN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

TYPE_TO_GROUP = {
    201: "Morning",
    202: "Sad",
    211: "Noon",
    212: "Sad",
    221: "Evening",
    222: "Sad",
    231: "Midnight",
    232: "Sad",
    401: "Greeting",
    502: "Return",
    503: "Return",
    601: "Festival",
    602: "Festival",
    603: "Festival",
    605: "Festival",
    701: "Greeting",
    702: "Greeting",
    801: "Tap头",
    901: "Tap手",
    1001: "Tap胸",
    1101: "Tap臀部",
    1201: "Greeting",
    1301: "Gift",
    1302: "Gift",
    1303: "Gift",
    1311: "Gift",
    1312: "Gift",
    1313: "Gift",
    1314: "Gift",
    1315: "Gift",
    1321: "Food",
    1322: "Food",
    1323: "Food",
    1324: "Food",
    1325: "Food",
    1326: "Food",
    1327: "Food",
    1328: "Food",
    1329: "Food",
    1401: "TouchSpecial",
    1402: "TouchSpecial",
    1403: "TouchSpecial",
    1404: "TouchSpecial",
    1409: "TouchSpecial",
    1411: "Festival",
    1412: "Festival",
    1413: "Festival",
    1414: "Festival",
    1415: "Festival",
    1601: "System",
    1611: "System",
    1801: "System",
    1901: "System",
    2001: "System",
    2101: "System",
    2201: "System",
    2301: "Greeting",
    2401: "Festival",
}

SKIN_TOUCH_TYPE_TO_GROUP = {
    801: "Tap头",
    901: "Tap手",
    1001: "Tap胸",
    1101: "Tap臀部",
    1401: "Tap头",
    1402: "Tap头",
    1403: "Tap头",
    1404: "Tap头",
}

# Fallback character / skin names for AB models missing from CfgSoulTable / CfgDressTable
EXTRA_CHAR_NAMES = {
    "diana": "黛安娜",
}
EXTRA_SKIN_NAMES = {
    "live2d_netsuki_s3": "此情无垢",
}
VARIANT_LABELS = {
    "activity": "活动",
    "henshin": "变身",
    "colcher": "柯露雪儿剧情",
    "ennis": "艾妮斯剧情",
}

MENU_SILENT_MOTION = {
    "Version": 3,
    "Meta": {
        "Duration": 0.033,
        "Fps": 30.0,
        "Loop": False,
        "AreBeziersRestricted": True,
        "CurveCount": 0,
        "TotalSegmentCount": 0,
        "TotalPointCount": 0,
        "UserDataCount": 0,
        "TotalUserDataSize": 0,
    },
    "Curves": [],
}


class FullLuaRepo(LuaTableRepo):
    """LuaTableRepo subclass adding CfgI18NTable RefId resolution and fast CV reverse lookup."""

    def __init__(self, decompiled_dir: Path = DECOMPILED_DIR) -> None:
        super().__init__(decompiled_dir)
        self._i18n_refs: dict[int, dict[int, int]] = {}
        self._stem_to_cv: dict[str, int] | None = None

    def _ensure_shard(self, shard: int) -> None:
        if shard in self._i18n_shards:
            return
        txt = (self.dir / f"CfgI18NTable_{shard}.lua").read_text(encoding="utf-8", errors="ignore")
        pat_str = re.compile(
            r'\[(\d+)\]\s*=\s*\{\s*Id\s*=\s*\d+,\s*Str\s*=\s*"((?:[^"\\]|\\.)*)"',
            re.S,
        )
        pat_ref = re.compile(
            r'\[(\d+)\]\s*=\s*\{\s*Id\s*=\s*\d+,\s*RefId\s*=\s*(\d+)',
            re.S,
        )
        self._i18n_shards[shard] = {int(m.group(1)): m.group(2) for m in pat_str.finditer(txt)}
        self._i18n_refs[shard] = {int(m.group(1)): int(m.group(2)) for m in pat_ref.finditer(txt)}

    def get_i18n(self, i18n_id: int | None, _depth: int = 0) -> str:
        if not i18n_id or _depth > 8:
            return ""
        if self._i18n_ranges is None:
            route = (self.dir / "CfgI18NTable_Route.lua").read_text(encoding="utf-8", errors="ignore")
            self._i18n_ranges = [
                (int(a), int(b), int(c))
                for a, b, c in re.findall(r"\{\s*(\d+),\s*(\d+),\s*(\d+)\s*\}", route)
            ]
        shard = next((idx for lo, hi, idx in self._i18n_ranges if lo <= i18n_id <= hi), None)
        if shard is None:
            return ""
        self._ensure_shard(shard)
        if i18n_id in self._i18n_shards[shard]:
            raw = self._i18n_shards[shard][i18n_id]
            raw = (
                raw.replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\'", "'")
                .replace("\\\\", "\\")
            )
            return raw.replace("{$br}", "\n").strip()
        ref = self._i18n_refs[shard].get(i18n_id)
        return self.get_i18n(ref, _depth + 1) if ref else ""

    @property
    def stem_to_cv(self) -> dict[str, int]:
        if self._stem_to_cv is None:
            self._stem_to_cv = {}
            for cid, info in sorted(self.cv_map.items()):
                srel = self.sound_map.get(info["sound_id"] or -1, "")
                if srel:
                    self._stem_to_cv.setdefault(Path(srel).stem.lower(), cid)
        return self._stem_to_cv


DRESS_TAG_RE = re.compile(r"(dre[es]s\d+)", re.I)
PART_TO_L2D_TAP = {"head": "Tap头", "chest": "Tap胸", "hand": "Tap手", "leg": "Tap臀部", "foot": "Tap臀部"}
L2D_TAP_TO_PART = {"Tap头": "head", "Tap胸": "chest", "Tap手": "hand", "Tap臀部": "leg"}


def _extract_dress_tag(stem_low: str) -> str | None:
    """Normalize both `dressN` and game typo `dreesN` (e.g. HagakureRuri_drees3/4) to `dressN`."""
    m = DRESS_TAG_RE.search(stem_low)
    return m.group(1).lower().replace("drees", "dress") if m else None


def _guard_tap_group(grp: str, stem_low: str, zh_text: str, is_base: bool) -> str | None:
    """Ensure touch groups never receive cross-body-part voices; returns adjusted group or None to skip."""
    if grp not in ("Tap头", "Tap胸", "Tap手", "Tap臀部", "Tap躯干"):
        return grp
    from fix_spine_voice_routing import detect_semantic_parts, detect_sound_tag, infer_dress_suffix_part

    if is_base:
        stag = detect_sound_tag(stem_low)
        if grp == "Tap臀部" and (stag == "reaction" or "after_marriage_touch" in stem_low):
            return "TouchSpecial"
        if grp == "Tap胸" and (stag in ("head", "hand", "leg", "foot") or stem_low == "juewa_touch_locked"):
            return None
        if grp in L2D_TAP_TO_PART and stag in ("head", "chest", "hand", "leg", "foot") and stag != L2D_TAP_TO_PART[grp]:
            return PART_TO_L2D_TAP[stag]
        return grp

    sem = detect_semantic_parts(zh_text, stem_low)
    if grp == "Tap躯干":
        # Avoid dumping body-part-specific time greetings (_01.._03) into Tap躯干 -> Tap臀部/Tap胸
        if sem and re.search(r"dre[es]s\d+_0[1-4]$", stem_low):
            return None
        if sem:
            return PART_TO_L2D_TAP[sem[0]]
        return grp

    gpart = L2D_TAP_TO_PART[grp]
    if sem:
        conflict = [sp for sp in sem if sp != gpart and not (gpart == "leg" and sp == "foot")]
        if conflict:
            if re.search(r"dre[es]s\d+_0[1-4]$", stem_low):
                return None
            return PART_TO_L2D_TAP[conflict[0]]
    elif grp == "Tap头":
        suf = infer_dress_suffix_part(stem_low)
        if suf and suf != "head":
            return PART_TO_L2D_TAP[suf]
    return grp


def sanitize_win_name(name: str) -> str:
    """Clean a Chinese role/skin name into a safe Windows directory segment."""
    cleaned = INVALID_WIN_CHARS.sub("_", name).strip().strip(".")
    return cleaned or "unnamed"


def index_backup_options(backup_dir: Path = BACKUP_L2D_DIR) -> tuple[dict[str, dict], dict[str, dict]]:
    """Index Options (ScaleFactor, PositionX, PositionY) from backup .model3.json files.

    Returns (by_moc_sha256_prefix, by_moc_stem_fallback).
    """
    by_hash: dict[str, tuple[tuple[int, int, int], dict]] = {}
    by_stem: dict[str, tuple[tuple[int, int, int], dict]] = {}
    if not backup_dir.exists():
        return {}, {}

    for m3 in sorted(backup_dir.rglob(".model3.json")):
        try:
            data = json.loads(m3.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        opts = data.get("Options") or {}
        if "ScaleFactor" not in opts:
            continue
        fr = data.get("FileReferences") or {}
        moc_rel = fr.get("Moc") or ""
        moc_path = m3.parent / moc_rel
        rel_str = str(m3.relative_to(backup_dir).parent)
        score = (
            1 if rel_str.startswith("r18\\") else 0,
            1 if "副本" in rel_str else 0,
            len(rel_str),
        )
        clean_opts = {
            "ScaleFactor": float(opts["ScaleFactor"]),
            "PositionX": float(opts.get("PositionX", 0.0)),
            "PositionY": float(opts.get("PositionY", 0.0)),
        }
        stem = Path(moc_rel).stem.lower()
        if stem and (stem not in by_stem or score < by_stem[stem][0]):
            by_stem[stem] = (score, clean_opts)
        if moc_path.is_file():
            h = hashlib.sha256(moc_path.read_bytes()).hexdigest()[:16]
            if h not in by_hash or score < by_hash[h][0]:
                by_hash[h] = (score, clean_opts)

    return {k: v[1] for k, v in by_hash.items()}, {k: v[1] for k, v in by_stem.items()}


def load_metadata_tables(repo: FullLuaRepo) -> dict[str, Any]:
    """Parse CfgSoulTable, CfgSoulResTable, CfgDressTable, and ActionGroup tags."""
    soul_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgSoulTable.lua")
    res_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgSoulResTable.lua")
    dress_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgDressTable.lua")

    souls: dict[int, dict[str, Any]] = {}
    for sid, body in soul_tbl.items():
        m_name = re.search(r"Name\s*=\s*getI18NValue\((\d+)\)", body)
        m_head = re.search(r'SoulHead\s*=\s*"([^"]+)"', body)
        souls[sid] = {
            "name": repo.get_i18n(int(m_name.group(1))) if m_name else f"Soul_{sid}",
            "head_stem": Path(m_head.group(1)).stem.lower() if m_head else "",
        }

    # model_key -> list of SoulResIds pointing to it
    res_by_l2d: dict[str, list[int]] = {}
    rid_to_l2d: dict[int, str] = {}
    for rid, body in res_tbl.items():
        m_l2d = re.search(r'Live2D\s*=\s*"([^"]+)"', body)
        if m_l2d:
            mk = m_l2d.group(1).strip("/").split("/")[0].lower()
            res_by_l2d.setdefault(mk, []).append(rid)
            rid_to_l2d[rid] = mk

    # SoulResId -> list of dress entries
    dress_by_rid: dict[int, list[dict[str, Any]]] = {}
    for did, body in sorted(dress_tbl.items()):
        m_sid = re.search(r"SoulID\s*=\s*(\d+)", body)
        m_rid = re.search(r"SoulResID\s*=\s*(\d+)", body)
        m_name = re.search(r"Name\s*=\s*getI18NValue\((\d+)\)", body)
        m_init = re.search(r"InitialDress\s*=\s*(\d+)", body)
        m_hide = re.search(r"IsHide\s*=\s*(true|false)", body)
        if not (m_sid and m_rid):
            continue
        sid = int(m_sid.group(1))
        rid = int(m_rid.group(1))
        dinfo = {
            "did": did,
            "soul_id": sid,
            "rid": rid,
            "name": repo.get_i18n(int(m_name.group(1))) if m_name else "",
            "initial": int(m_init.group(1)) if m_init else 0,
            "is_hide": (m_hide.group(1) == "true") if m_hide else False,
        }
        dress_by_rid.setdefault(rid, []).append(dinfo)
        dress_by_rid.setdefault(rid + 1, []).append(dinfo)

    # Character key -> canonical playable SoulId (lowest 2001xxxx ID matching char_key)
    char_to_soul: dict[str, int] = {}
    for mk, rids in sorted(res_by_l2d.items()):
        if not mk.startswith("live2d_"):
            continue
        ck = mk[len("live2d_"):].split("_")[0]
        for r in rids:
            for d in dress_by_rid.get(r, []):
                sid = d["soul_id"]
                if 20010000 <= sid < 20020000:
                    if ck not in char_to_soul or sid < char_to_soul[ck]:
                        char_to_soul[ck] = sid

    # Index ActionGroups by SoulId, and compute per-model dress tags (e.g. dress1, dress2, ...)
    ag_by_soul: dict[int, list[tuple[int, str]]] = {}
    dress_tags_by_soul: dict[int, set[str]] = {}
    for gid, body in sorted(repo.action_groups.items()):
        ms = re.search(r"SoulId\s*=\s*(\d+)", body)
        if not ms:
            continue
        sid = int(ms.group(1))
        ag_by_soul.setdefault(sid, []).append((gid, body))

        m_res = re.search(r"SoulResId\s*=\s*\{([^}]+)\}", body)
        m_ract = re.search(r"SoulResAction\s*=\s*\{(.*?)\n\t\t\}", body, re.S)
        if m_res and m_ract:
            for sub in re.findall(r"\{([^}]*)\}", m_ract.group(1)):
                for aid_s in re.findall(r"\d+", sub):
                    act = repo.action_map.get(int(aid_s))
                    if act and act["cv"]:
                        st = repo.resolve_cv(act["cv"])["sound_stem"].lower()
                        dtag = _extract_dress_tag(st)
                        if dtag:
                            dress_tags_by_soul.setdefault(sid, set()).add(dtag)

    return {
        "souls": souls,
        "res_by_l2d": res_by_l2d,
        "dress_by_rid": dress_by_rid,
        "char_to_soul": char_to_soul,
        "ag_by_soul": ag_by_soul,
        "dress_tags_by_soul": dress_tags_by_soul,
    }


def scan_live2d_bundles() -> dict[str, dict[str, Any]]:
    """Scan all 41 ABs under 20_live2d/live2d_resources, keeping newest batch per model_key."""
    ab_files = sorted(
        L2D_AB_DIR.glob("*.ab"),
        key=lambda p: int(m.group()) if (m := re.search(r"\d+", p.stem)) else 0,
    )
    catalog: dict[str, dict[str, Any]] = {}
    for ab in ab_files:
        env = load_ab(ab)
        per_ab: dict[str, list[str]] = {}
        for cpath in sorted((env.container or {}).keys()):
            parts = cpath.split("/")
            if len(parts) >= 4 and parts[2].lower() == "live2d_resources":
                mk = parts[3].lower()
                per_ab.setdefault(mk, []).append(cpath)
        for mk, cpaths in per_ab.items():
            catalog[mk] = {
                "model_key": mk,
                "ab_path": ab,
                "ab_name": ab.name,
                "cpaths": cpaths,
            }
    return catalog


def resolve_model_identity(model_key: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Resolve SoulId, Chinese character name, raw skin name, base flag, and SoulResIds."""
    if not model_key.startswith("live2d_"):
        return {
            "char_key": model_key,
            "soul_id": None,
            "char_name": model_key,
            "skin_name": model_key,
            "variant": "",
            "stage": "",
            "is_base": False,
            "skin_res_ids": (),
        }

    tail = model_key[len("live2d_"):]
    parts = tail.split("_")
    char_key = parts[0]
    stage = parts[1] if len(parts) >= 2 else "s1"
    variant = "_".join(parts[2:]) if len(parts) >= 3 else ""
    is_base = stage == "s1"

    soul_id = meta["char_to_soul"].get(char_key)
    char_name = (
        meta["souls"].get(soul_id, {}).get("name")
        if soul_id
        else EXTRA_CHAR_NAMES.get(char_key, char_key)
    )

    # Resolve SoulResIds for this specific model_key
    raw_rids = meta["res_by_l2d"].get(model_key, [])
    dress_by_rid = meta["dress_by_rid"]

    matched_dresses: list[dict[str, Any]] = []
    for r in raw_rids:
        for d in dress_by_rid.get(r, []):
            if soul_id is None or d["soul_id"] == soul_id:
                matched_dresses.append(d)
    if not matched_dresses:
        for r in raw_rids:
            matched_dresses.extend(dress_by_rid.get(r, []))
    matched_dresses.sort(
        key=lambda d: (
            0 if (soul_id is not None and d["soul_id"] == soul_id) else 1,
            0 if (is_base and d["initial"] == 1) else 1,
            0 if (not is_base and d["initial"] == 0) else 1,
            d["did"],
        )
    )

    skin_res_ids: list[int] = []
    if is_base:
        # Avoid placeholder dresses (e.g. freesia 20020451 / asuna 20020691) polluting _s1
        init_rids = [d["rid"] for d in matched_dresses if d["initial"] == 1]
        for r in raw_rids:
            if not init_rids or r in init_rids or (r - 1) in init_rids:
                skin_res_ids.extend([r, r - 1])
        skin_name = "原皮"
        if variant:
            v_zh = VARIANT_LABELS.get(variant, variant)
            skin_name = f"原皮_{v_zh}"
    else:
        for r in raw_rids:
            skin_res_ids.extend([r, r - 1])
        if model_key in EXTRA_SKIN_NAMES:
            skin_name = EXTRA_SKIN_NAMES[model_key]
        elif matched_dresses and matched_dresses[0]["name"]:
            skin_name = matched_dresses[0]["name"]
        else:
            skin_name = stage.upper()
        if variant:
            v_zh = VARIANT_LABELS.get(variant, variant)
            skin_name = f"{skin_name}_{v_zh}"

    # Deduplicate while preserving order
    uniq_rids = tuple(dict.fromkeys(r for r in skin_res_ids if r > 0))
    return {
        "char_key": char_key,
        "soul_id": soul_id,
        "char_name": sanitize_win_name(char_name),
        "skin_name": sanitize_win_name(skin_name),
        "variant": variant,
        "stage": stage.upper(),
        "is_base": is_base,
        "skin_res_ids": uniq_rids,
    }


def assign_unique_output_dirs(identities: dict[str, dict[str, Any]]) -> None:
    """Ensure every model under the same character resolves to a unique folder name."""
    by_char_skin: dict[tuple[str, str], list[str]] = {}
    for mk, ident in sorted(identities.items()):
        if mk == "snow":
            continue
        by_char_skin.setdefault((ident["char_name"], ident["skin_name"]), []).append(mk)

    for (cname, sname), mks in by_char_skin.items():
        if len(mks) > 1:
            for mk in mks:
                ident = identities[mk]
                if ident["variant"]:
                    v_zh = VARIANT_LABELS.get(ident["variant"], ident["variant"])
                    base_sname = sname.removesuffix(f"_{v_zh}")
                    ident["skin_name"] = sanitize_win_name(f"{base_sname}_{ident['stage']}_{v_zh}")
                else:
                    ident["skin_name"] = sanitize_win_name(f"{sname}_{ident['stage']}")
        for mk in mks:
            ident = identities[mk]
            ident["out_dir"] = OUT_ROOT / ident["char_name"] / ident["skin_name"]


def choose_idle_motion(motions_by_stem: dict[str, str]) -> tuple[str, str] | None:
    """Select exactly ONE main Idle motion (prefer standby1, then standby2/standby)."""
    stems = sorted(motions_by_stem)
    for pat in (
        lambda s: s.endswith("_standby1") or s == "standby1",
        lambda s: "standby1" in s,
        lambda s: s.endswith("_standby2") or s == "standby2",
        lambda s: "standby2" in s,
        lambda s: "standby" in s,
    ):
        for s in stems:
            if pat(s):
                short = s.split("@live2d_")[-1]
                return short, motions_by_stem[s]
    if stems:
        s0 = stems[0]
        return s0.split("@live2d_")[-1], motions_by_stem[s0]
    return None


def build_verified_hit_areas(moc_raw: bytes, motion_groups: dict[str, list[dict]]) -> list[dict[str, str]]:
    """Build HitAreas strictly verified against CubismCore csmGetDrawableIds and non-empty groups."""
    import ctypes
    core_dll = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Plugins\x86_64\Live2DCubismCore.dll")
    drawable_ids: set[str] = set()
    if core_dll.is_file():
        core = ctypes.CDLL(str(core_dll))
        core.csmReviveMocInPlace.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        core.csmReviveMocInPlace.restype = ctypes.c_void_p
        core.csmGetSizeofModel.argtypes = [ctypes.c_void_p]
        core.csmGetSizeofModel.restype = ctypes.c_uint32
        core.csmInitializeModelInPlace.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
        core.csmInitializeModelInPlace.restype = ctypes.c_void_p
        core.csmGetDrawableCount.argtypes = [ctypes.c_void_p]
        core.csmGetDrawableCount.restype = ctypes.c_int32
        core.csmGetDrawableIds.argtypes = [ctypes.c_void_p]
        core.csmGetDrawableIds.restype = ctypes.POINTER(ctypes.c_char_p)
        mb = ctypes.create_string_buffer(len(moc_raw) + 64)
        ma = (ctypes.addressof(mb) + 63) & ~63
        ctypes.memmove(ma, moc_raw, len(moc_raw))
        moc = core.csmReviveMocInPlace(ma, len(moc_raw))
        if moc:
            msz = core.csmGetSizeofModel(moc)
            modb = ctypes.create_string_buffer(msz + 64)
            moda = (ctypes.addressof(modb) + 63) & ~63
            model = core.csmInitializeModelInPlace(moc, moda, msz)
            dcnt = core.csmGetDrawableCount(model)
            dids = core.csmGetDrawableIds(model)
            drawable_ids = {dids[i].decode("utf-8", "ignore") for i in range(dcnt)}

    # Redistribute Tap躯干 into real drawable touch groups if neither Body2 nor Body is a Drawable ID
    if "Tap躯干" in motion_groups and not ({"Body2", "Body"} & drawable_ids):
        torso_items = motion_groups.pop("Tap躯干", [])
        if torso_items:
            fallback_grp = next((g for g in ("Tap臀部", "Tap胸", "Tap手", "Tap头") if g in motion_groups), "Tap臀部")
            dest = motion_groups.setdefault(fallback_grp, [])
            seen_keys = {(m.get("File"), m.get("Sound"), m.get("Text")) for m in dest}
            for item in torso_items:
                k = (item.get("File"), item.get("Sound"), item.get("Text"))
                if k not in seen_keys:
                    dest.append(item)
                    seen_keys.add(k)

    specs = [
        ("头", ("DREFTouchBoxHead2", "DREFTouchBoxHead"), "Tap头"),
        ("左手", ("DREFTouchBoxHandL2", "DREFTouchBoxHandL"), "Tap手"),
        ("右手", ("DREFTouchBoxHandR2", "DREFTouchBoxHandR"), "Tap手"),
        ("胸", ("DREFTouchBoxBra2", "DREFTouchBoxBra"), "Tap胸"),
        ("躯干", ("Body2", "Body"), "Tap躯干"),
        ("臀部", ("DREFTouchBoxHip2", "DREFTouchBoxHip"), "Tap臀部"),
    ]
    fallback_grp = next((g for g in ("Tap头", "Tap胸", "Tap手", "Tap臀部", "Tap躯干") if motion_groups.get(g)), "")
    hits: list[dict[str, str]] = []
    for name, id_cands, mtn_grp in specs:
        target_grp = mtn_grp if motion_groups.get(mtn_grp) else (fallback_grp if mtn_grp != "Tap躯干" else "")
        if not target_grp:
            continue
        for cid in id_cands:
            if (cid in drawable_ids) if drawable_ids else (cid.encode("ascii") in moc_raw):
                hits.append({"Name": name, "Id": cid, "Motion": target_grp})
                break
    return hits


class CvCache:
    """Per-character AudioClip index and decoded WAV cache to avoid re-loading CV ABs."""

    def __init__(self) -> None:
        self._cur_char: str | None = None
        self._clip_by_lower: dict[str, tuple[str, Any]] = {}
        self._wav_cache: dict[str, tuple[str, bytes]] = {}
        self._all_dress_tags: set[str] = set()

    def load_character(self, char_key: str) -> None:
        if self._cur_char == char_key:
            return
        self._cur_char = char_key
        self._clip_by_lower = {}
        self._wav_cache = {}
        self._all_dress_tags = set()

        cv_ab = CV_AB_DIR / f"_{char_key}.ab"
        if not cv_ab.is_file():
            return
        env = load_ab(cv_ab)
        for obj in env.objects:
            if obj.type.name == "AudioClip":
                cname = obj.peek_name()
                low = cname.lower()
                self._clip_by_lower[low] = (cname, obj)
                dtag = _extract_dress_tag(low)
                if dtag:
                    self._all_dress_tags.add(dtag)

    @property
    def clip_by_lower(self) -> dict[str, tuple[str, Any]]:
        return self._clip_by_lower

    @property
    def all_dress_tags(self) -> set[str]:
        return self._all_dress_tags

    def get_wav(self, stem: str) -> tuple[str, bytes] | None:
        low = stem.lower()
        if not low:
            return None
        if low in self._wav_cache:
            return self._wav_cache[low]
        item = self._clip_by_lower.get(low)
        if not item:
            return None
        cname, obj = item
        wav_bytes = extract_wav_bytes(obj)
        res = (f"{cname}.wav", wav_bytes)
        self._wav_cache[low] = res
        return res


def build_single_model(
    entry: dict[str, Any],
    ident: dict[str, Any],
    meta: dict[str, Any],
    repo: FullLuaRepo,
    cv_cache: CvCache,
    bk_by_hash: dict[str, dict],
    bk_by_stem: dict[str, dict],
    ab_env_cache: dict[Path, Any],
    skip_existing: bool = False,
) -> dict[str, Any]:
    """Extract assets and build a complete Live2DViewerEX package for one model."""
    mk = entry["model_key"]
    out_dir: Path = ident["out_dir"]

    if skip_existing and (out_dir / ".model3.json").is_file():
        return {"model_key": mk, "status": "skipped", "reason": "already_exists", "out_dir": str(out_dir)}

    ab_path: Path = entry["ab_path"]
    if ab_path not in ab_env_cache:
        ab_env_cache.clear()  # keep memory bounded while streaming ABs
        ab_env_cache[ab_path] = load_ab(ab_path)
    env = ab_env_cache[ab_path]
    container = env.container or {}

    from pathlib import PurePosixPath

    moc_ptr = None
    moc_name = ""
    phys_ptr = None
    phys_name = ""
    orig_m3_ptr = None
    orig_m3_cpath = ""
    moc_by_rel: dict[str, tuple[str, Any]] = {}
    phys_by_rel: dict[str, tuple[str, Any]] = {}
    png_by_rel: dict[str, tuple[str, Any]] = {}
    png_ptrs: dict[str, tuple[str, Any]] = {}
    mot_ptrs: list[tuple[str, Any]] = []

    for cpath in entry["cpaths"]:
        ptr = container[cpath]
        low = cpath.lower()
        fname = PurePosixPath(cpath).name
        if low.endswith(".asset") and "/moc/" in low:
            moc_ptr = ptr
            moc_name = PurePosixPath(cpath).stem
            moc_by_rel[low] = (moc_name, ptr)
        elif low.endswith(".physics3.json"):
            phys_ptr = ptr
            phys_name = fname
            phys_by_rel[low] = (fname, ptr)
        elif low.endswith(".model3.json"):
            orig_m3_ptr = ptr
            orig_m3_cpath = cpath
        elif low.endswith(".png"):
            png_by_rel[low] = (fname, ptr)
            # Prefer shallower path when multiple files share the same basename
            prev = png_ptrs.get(fname.lower())
            if prev is None or cpath.count("/") < prev[2]:
                png_ptrs[fname.lower()] = (fname, ptr, cpath.count("/"))
        elif low.endswith(".motion3.json"):
            mot_ptrs.append((fname, ptr))

    if moc_ptr is None or not png_ptrs or not mot_ptrs:
        return {
            "model_key": mk,
            "status": "skipped",
            "reason": f"incomplete_ab_assets(moc={moc_ptr is not None},png={len(png_ptrs)},mot={len(mot_ptrs)})",
            "out_dir": str(out_dir),
        }

    # Determine original moc/physics/texture relative paths from original .model3.json when present
    orig_tex_rels: list[str] = []
    m3_base = PurePosixPath(orig_m3_cpath).parent if orig_m3_cpath else None
    if orig_m3_ptr is not None:
        try:
            orig_m3 = json.loads(orig_m3_ptr.read().m_Script)
            fr0 = orig_m3.get("FileReferences") or {}
            if fr0.get("Moc"):
                moc_name = PurePosixPath(fr0["Moc"]).stem
                if m3_base is not None:
                    cand = str((m3_base / fr0["Moc"]).with_suffix(".asset")).lower()
                    if cand in moc_by_rel:
                        moc_ptr = moc_by_rel[cand][1]
            if fr0.get("Physics"):
                phys_name = PurePosixPath(fr0["Physics"]).name
                if m3_base is not None:
                    cand_p = str(m3_base / fr0["Physics"]).lower()
                    if cand_p in phys_by_rel:
                        phys_ptr = phys_by_rel[cand_p][1]
            for t in fr0.get("Textures") or []:
                orig_tex_rels.append(t)
        except Exception:
            pass

    moc_bytes = bytes(moc_ptr.read_typetree()["_bytes"])
    if not moc_bytes.startswith(b"MOC3"):
        return {"model_key": mk, "status": "failed", "reason": "invalid_moc3_magic", "out_dir": str(out_dir)}

    selected_pngs: list[tuple[str, Any]] = []
    for trel in orig_tex_rels:
        hit = None
        if m3_base is not None:
            cand_t = str(m3_base / trel).lower()
            hit = png_by_rel.get(cand_t)
        if hit is None:
            b = png_ptrs.get(PurePosixPath(trel).name.lower())
            if b is not None:
                hit = (b[0], b[1])
        if hit:
            selected_pngs.append(hit)
    if not selected_pngs:
        selected_pngs = [(v[0], v[1]) for _, v in sorted(png_ptrs.items())]

    # Prepare clean output directories
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_dir = out_dir / "Textures"
    mot_dir = out_dir / "motions"
    aud_dir = out_dir / "audio"
    exp_dir = out_dir / "expressions"
    for d in (tex_dir, mot_dir, aud_dir, exp_dir):
        d.mkdir(parents=True, exist_ok=True)
    for old_t in tex_dir.glob("*.png"):
        old_t.unlink()
    for old_w in aud_dir.glob("*.wav"):
        old_w.unlink()
    for old_m in mot_dir.glob("*.motion3.json"):
        old_m.unlink()
    for old_e in exp_dir.glob("*.exp3.json"):
        old_e.unlink()

    moc_filename = f"{moc_name}.moc3"
    (out_dir / moc_filename).write_bytes(moc_bytes)

    phys_filename: str | None = None
    if phys_ptr is not None:
        phys_filename = phys_name or f"{moc_name}.physics3.json"
        (out_dir / phys_filename).write_text(phys_ptr.read().m_Script, encoding="utf-8")

    tex_rels: list[str] = []
    for fname, ptr in selected_pngs:
        img = ptr.read().image.convert("RGBA")
        img.save(tex_dir / fname, "PNG")
        tex_rels.append(f"Textures/{fname}")

    motions_by_stem: dict[str, str] = {}
    for fname, ptr in mot_ptrs:
        (mot_dir / fname).write_text(ptr.read().m_Script, encoding="utf-8")
        stem_low = fname[:-len(".motion3.json")].lower()
        motions_by_stem[stem_low] = f"motions/{fname}"

    has_ring_param = b"ParamRingOn" in moc_bytes

    # Load CV AB for this character
    char_key = ident["char_key"]
    cv_cache.load_character(char_key)

    extracted_wavs: dict[str, str] = {}

    def ensure_wav(stem: str) -> str:
        low = stem.lower()
        if not low:
            return ""
        if low in extracted_wavs:
            return extracted_wavs[low]
        got = cv_cache.get_wav(low)
        if not got:
            return ""
        wname, wbytes = got
        rel = f"audio/{wname}"
        (out_dir / rel).write_bytes(wbytes)
        extracted_wavs[low] = rel
        return rel

    motion_groups: dict[str, list[dict]] = {
        "Idle": [],
        "Start": [],
        "Tap头": [],
        "Tap胸": [],
        "Tap手": [],
        "Tap臀部": [],
        "Tap躯干": [],
        "Tap": [],
        "Morning": [],
        "Noon": [],
        "Evening": [],
        "Midnight": [],
        "Greeting": [],
        "TouchSpecial": [],
        "Festival": [],
        "Gift": [],
        "Food": [],
        "Return": [],
        "System": [],
        "Sad": [],
        "Archive": [],
        "Battle": [],
        "ExtraMotions": [],
    }
    group_seen: dict[str, set[tuple[str, str, str]]] = {k: set() for k in motion_groups}
    used_motion_stems: set[str] = set()
    included_sound_stems: set[str] = set()

    def add_entry(grp: str, name: str, mot_rel: str, cv_id: int | None) -> None:
        cv_info = repo.resolve_cv(cv_id)
        guarded = _guard_tap_group(grp, cv_info["sound_stem"].lower(), cv_info["text"], ident["is_base"])
        if guarded is None:
            return
        grp = guarded
        if grp not in motion_groups:
            motion_groups[grp] = []
            group_seen[grp] = set()
        snd_rel = ensure_wav(cv_info["sound_stem"]) if cv_info["sound_stem"] else ""
        text = cv_info["text"]
        sig = (mot_rel, snd_rel, text)
        if sig in group_seen[grp]:
            return
        group_seen[grp].add(sig)
        used_motion_stems.add(Path(mot_rel).name[:-len(".motion3.json")].lower())
        if cv_info["sound_stem"] and snd_rel:
            included_sound_stems.add(cv_info["sound_stem"].lower())
        e: dict[str, Any] = {"Name": name, "File": mot_rel}
        if snd_rel:
            e["Sound"] = snd_rel
        if text:
            e["Text"] = text
            e["TextDuration"] = cv_info["duration_ms"]
        motion_groups[grp].append(e)

    soul_id: int | None = ident["soul_id"]
    skin_res_ids: tuple[int, ...] = ident["skin_res_ids"]
    is_base: bool = ident["is_base"]

    # Determine skin_dress_tags & other_dress_tags for strict cross-skin isolation
    skin_dress_tags: set[str] = set()
    skin_seen_aids: set[int] = set()
    skin_records: list[tuple[int, int, str]] = []  # (aid, gtype, target_group)
    base_records: list[tuple[int, int, str]] = []

    if soul_id is not None:
        for _gid, body in meta["ag_by_soul"].get(soul_id, []):
            m_t = re.search(r"Type\s*=\s*(\d+)", body)
            if not m_t:
                continue
            gtype = int(m_t.group(1))
            if gtype in (101, 102, 103):
                continue
            target_group = TYPE_TO_GROUP.get(gtype, "Greeting")

            m_res = re.search(r"SoulResId\s*=\s*\{([^}]+)\}", body)
            m_ract = re.search(r"SoulResAction\s*=\s*\{(.*?)\n\t\t\}", body, re.S)
            skin_aids: list[int] = []
            if m_res and m_ract and skin_res_ids:
                rids = [int(x) for x in re.findall(r"\d+", m_res.group(1))]
                sub_lists = re.findall(r"\{([^}]*)\}", m_ract.group(1))
                for srid in skin_res_ids:
                    if srid in rids:
                        idx = rids.index(srid)
                        if idx < len(sub_lists):
                            skin_aids = [int(x) for x in re.findall(r"\d+", sub_lists[idx])]
                            break
            m_mood = re.search(r"MoodActionID\s*=\s*\{(.*?)\n\t\t\}", body, re.S)
            base_aids = [int(x) for x in re.findall(r"\d{6,}", m_mood.group(1))] if m_mood else []

            for aid in skin_aids:
                skin_records.append((aid, gtype, target_group))
                act = repo.action_map.get(aid)
                if act and act["cv"]:
                    st = repo.resolve_cv(act["cv"])["sound_stem"].lower()
                    dtag = _extract_dress_tag(st)
                    if dtag:
                        skin_dress_tags.add(dtag)
            for aid in base_aids:
                base_records.append((aid, gtype, target_group))

    # Handle unregistered skin dress tag fallback (e.g. live2d_netsuki_s3 uses fashion2_* -> dress2)
    if not is_base and not skin_dress_tags:
        for mstem in motions_by_stem:
            mf = re.search(r"fashion(\d+)(?:_|$)", mstem)
            if mf:
                cand_tag = f"dress{mf.group(1)}"
                if cand_tag in cv_cache.all_dress_tags:
                    skin_dress_tags.add(cand_tag)

    all_soul_dress_tags = set(cv_cache.all_dress_tags)
    if soul_id is not None:
        all_soul_dress_tags |= meta["dress_tags_by_soul"].get(soul_id, set())
    other_dress_tags = all_soul_dress_tags if is_base else (all_soul_dress_tags - skin_dress_tags)

    def has_other_dress_tag(stem_low: str) -> bool:
        dtag = _extract_dress_tag(stem_low)
        return (dtag in other_dress_tags) if dtag else False

    # 3A. Route ActionGroups
    for aid, gtype, target_group in skin_records:
        act = repo.action_map.get(aid)
        if not act or not act["body_action"]:
            continue
        mot_rel = motions_by_stem.get(act["body_action"].lower(), "")
        if not mot_rel:
            continue
        skin_seen_aids.add(aid)
        if is_base:
            add_entry(target_group, f"act_{aid}", mot_rel, act["cv"])
        else:
            touch_grp = SKIN_TOUCH_TYPE_TO_GROUP.get(gtype)
            if touch_grp:
                add_entry(touch_grp, f"act_{aid}", mot_rel, act["cv"])
            else:
                add_entry("Tap躯干", f"act_{aid}", mot_rel, act["cv"])
                add_entry(target_group, f"act_{aid}", mot_rel, act["cv"])

    for aid, gtype, target_group in base_records:
        if aid in skin_seen_aids:
            continue
        act = repo.action_map.get(aid)
        if not act or not act["body_action"]:
            continue
        mot_rel = motions_by_stem.get(act["body_action"].lower(), "")
        if not mot_rel:
            continue
        if is_base:
            # Base skin binds base touches & all daily/time/archive groups normally
            add_entry(target_group, f"act_{aid}", mot_rel, act["cv"])
        else:
            # Non-base skin: strict isolation! Base touches go to Archive, never Tap头/手/胸/臀部/躯干
            base_dst = "Archive" if gtype in SKIN_TOUCH_TYPE_TO_GROUP else target_group
            add_entry(base_dst, f"act_{aid}", mot_rel, act["cv"])

    # 3B. Scattered CfgSoulActionTable rows not in ActionGroups
    if not is_base and soul_id is not None:
        char_prefix = f"ch_{char_key}@"
        for aid, act in sorted(repo.action_map.items()):
            if aid in skin_seen_aids:
                continue
            ba = act["body_action"] or ""
            ba_low = ba.lower()
            if act["soul_id"] != soul_id and not ba_low.startswith(char_prefix):
                continue
            mot_rel = motions_by_stem.get(ba_low, "")
            if not mot_rel:
                continue
            cv_info = repo.resolve_cv(act["cv"])
            stem_low = cv_info["sound_stem"].lower()
            if has_other_dress_tag(stem_low):
                continue
            is_skin_match = (
                (_extract_dress_tag(stem_low) in skin_dress_tags)
                or ("fashion" in ba_low)
                or ("after_marriage" in stem_low and has_ring_param)
            )
            if not is_skin_match:
                continue
            skin_seen_aids.add(aid)
            dst_grp = "Tap躯干" if "gift" in stem_low else "Tap头"
            add_entry(dst_grp, f"act_{aid}", mot_rel, act["cv"])

    # 3C. Remaining <char>_* general CV AudioClips -> categorized archive/battle/time groups ONLY
    fallback_motion_map = [
        ("touch_head", "Archive", f"ch_{char_key}@live2d_greet2"),
        ("touch_breast", "Archive", f"ch_{char_key}@live2d_insert02"),
        ("touch_hand", "Archive", f"ch_{char_key}@live2d_greet1"),
        ("touch_hip", "Archive", f"ch_{char_key}@live2d_insert05_2"),
        ("touch_reaction", "TouchSpecial", f"ch_{char_key}@live2d_insert02"),
        ("touch_locked", "Sad", f"ch_{char_key}@live2d_sad_complete"),
        ("touch_unhappy", "Sad", f"ch_{char_key}@live2d_greet_sad1"),
        ("about_", "Archive", f"ch_{char_key}@live2d_greet2"),
        ("wedding", "Archive", f"ch_{char_key}@live2d_joyful_complete"),
        ("firstmeeting", "Archive", f"ch_{char_key}@live2d_greet1"),
        ("after_marriage", "Archive", f"ch_{char_key}@live2d_joyful_complete"),
        ("favorite", "Archive", f"ch_{char_key}@live2d_joyful_complete"),
        ("hate", "Archive", f"ch_{char_key}@live2d_sad_complete"),
        ("shy", "Archive", f"ch_{char_key}@live2d_greet2_2"),
        ("smile", "Archive", f"ch_{char_key}@live2d_joyful"),
        (f"{char_key}_sad", "Archive", f"ch_{char_key}@live2d_sad"),
        ("mad", "Archive", f"ch_{char_key}@live2d_angry"),
        ("amazed", "Archive", f"ch_{char_key}@live2d_greet2_1"),
        ("hurt", "Battle", f"ch_{char_key}@live2d_angry_complete"),
        ("attack", "Battle", f"ch_{char_key}@live2d_serious"),
        ("skill", "Battle", f"ch_{char_key}@live2d_serious_complete"),
        ("striked", "Battle", f"ch_{char_key}@live2d_sad_complete"),
        ("strike", "Battle", f"ch_{char_key}@live2d_serious_loop"),
        ("win", "Battle", f"ch_{char_key}@live2d_joyful_complete_1"),
        ("defeat", "Battle", f"ch_{char_key}@live2d_sad_loop"),
        ("dead", "Battle", f"ch_{char_key}@live2d_sad_complete"),
        ("morning", "Morning", f"ch_{char_key}@live2d_greet1"),
        ("noon", "Noon", f"ch_{char_key}@live2d_greet2"),
        ("evening", "Evening", f"ch_{char_key}@live2d_greet3"),
        ("greet", "Festival", f"ch_{char_key}@live2d_greet2_2"),
    ]
    default_mot = (
        motions_by_stem.get(f"ch_{char_key}@live2d_greet2")
        or motions_by_stem.get(f"ch_{char_key}@live2d_greet1")
        or next(iter(motions_by_stem.values()))
    )
    for cname_low, (cname, _obj) in sorted(cv_cache.clip_by_lower.items()):
        if not cname_low.startswith(f"{char_key}_"):
            continue
        if has_other_dress_tag(cname_low):
            continue
        if cname_low in included_sound_stems:
            continue
        matched_cv_id = repo.stem_to_cv.get(cname_low)
        target_grp = "Archive"
        mot_stem = f"ch_{char_key}@live2d_greet2"
        for kw, grp, mstem in fallback_motion_map:
            if kw in cname_low:
                target_grp, mot_stem = grp, mstem
                break
        # If this clip belongs to THIS skin's dress<N> and isn't bound yet, route to Tap头 for non-base
        if not is_base and (_extract_dress_tag(cname_low) in skin_dress_tags):
            target_grp = "Tap躯干" if "gift" in cname_low else "Tap头"
            # Prefer a fashion motion if available in this skin AB
            fash_mots = sorted(k for k in motions_by_stem if "fashion" in k)
            if fash_mots:
                mot_stem = fash_mots[0]
        mot_rel = motions_by_stem.get(mot_stem, default_mot)
        if matched_cv_id is not None:
            add_entry(target_grp, f"cv_{cname_low}", mot_rel, matched_cv_id)
        else:
            snd_rel = ensure_wav(cname)
            if target_grp not in motion_groups:
                motion_groups[target_grp] = []
                group_seen[target_grp] = set()
            sig = (mot_rel, snd_rel, "")
            if sig not in group_seen[target_grp]:
                group_seen[target_grp].add(sig)
                motion_groups[target_grp].append({"Name": f"cv_{cname_low}", "File": mot_rel, "Sound": snd_rel})
                used_motion_stems.add(Path(mot_rel).name[:-len(".motion3.json")].lower())
                included_sound_stems.add(cname_low)

    # 4. Exactly ONE Idle motion
    idle_sel = choose_idle_motion(motions_by_stem)
    if idle_sel:
        nm, rel = idle_sel
        used_motion_stems.add(Path(rel).name[:-len(".motion3.json")].lower())
        motion_groups["Idle"].append({"Name": nm, "File": rel, "FadeIn": 0})

    # Start pool
    for item in motion_groups["Morning"][:1] + motion_groups["Noon"][:1] + motion_groups["Evening"][:1]:
        motion_groups["Start"].append(dict(item))

    # 5. Bind ALL remaining .motion3.json into ExtraMotions
    for stem_low, rel in sorted(motions_by_stem.items()):
        if stem_low not in used_motion_stems:
            motion_groups["ExtraMotions"].append({"Name": stem_low, "File": rel})

    # 5B. Generate 0-curve menu_silent.motion3.json & paginated Choices menu
    menu_silent_rel = "motions/menu_silent.motion3.json"
    write_json(out_dir / menu_silent_rel, MENU_SILENT_MOTION)

    skin_cat_title = (
        f"{ident['skin_name']} · 身体互动与触摸语音"
        if is_base
        else f"{ident['skin_name']} · 皮肤全语音与动作"
    )
    menu_categories = [
        ("Menu_Cat_Skin", skin_cat_title, ["Tap头", "Tap手", "Tap胸", "Tap臀部", "Tap躯干"]),
        ("Menu_Cat_Time", "早/午/晚/深夜 时段问候", ["Morning", "Noon", "Evening", "Midnight"]),
        ("Menu_Cat_Social", "日常问候 / 节日 / 回归 / 系统", ["Greeting", "Festival", "Return", "System", "TouchSpecial", "Sad"]),
        ("Menu_Cat_Gift", "礼物与投喂互动", ["Gift", "Food"]),
        ("Menu_Cat_Archive", "誓约与人物档案语音", ["Archive"]),
        ("Menu_Cat_Battle", "战斗语音与技能动作", ["Battle"]),
        ("Menu_Cat_Motion", "纯动作预览 (其余Live2D动作)", ["ExtraMotions"]),
    ]

    play_item_counter = 0
    category_root_choices: list[dict[str, str]] = []
    menu_extra_groups: dict[str, list[dict]] = {}

    for cat_id, cat_title, src_grps in menu_categories:
        cat_entries: list[tuple[str, dict]] = []
        cat_seen: set[tuple[str, str, str]] = set()
        for gname in src_grps:
            for item in motion_groups.get(gname, []):
                sig = (item["File"], item.get("Sound", ""), item.get("Text", ""))
                if sig in cat_seen:
                    continue
                cat_seen.add(sig)
                txt = (item.get("Text") or "").strip().replace("\n", " ")
                snd_stem = Path(item["Sound"]).stem if item.get("Sound") else Path(item["File"]).stem
                btn_label = f"{txt[:20]}…" if len(txt) > 20 else (txt or snd_stem[:24])
                cat_entries.append((btn_label, item))
        if not cat_entries:
            continue

        per_page = 6
        total_pages = (len(cat_entries) + per_page - 1) // per_page
        for pg in range(total_pages):
            page_grp = cat_id if pg == 0 else f"{cat_id}_p{pg + 1}"
            chunk = cat_entries[pg * per_page : (pg + 1) * per_page]
            choices_list: list[dict[str, str]] = []
            for btn_label, item in chunk:
                play_item_counter += 1
                play_grp = f"MenuPlay_{play_item_counter:03d}"
                menu_extra_groups[play_grp] = [dict(item)]
                choices_list.append({"Text": btn_label, "NextMtn": play_grp})
            if pg + 1 < total_pages:
                choices_list.append({"Text": f"下一页 ({pg + 2}/{total_pages}) ▶", "NextMtn": f"{cat_id}_p{pg + 2}"})
            if pg > 0:
                prev_grp = cat_id if pg == 1 else f"{cat_id}_p{pg}"
                choices_list.append({"Text": f"◀ 上一页 ({pg}/{total_pages})", "NextMtn": prev_grp})
            choices_list.append({"Text": "« 返回主语音菜单", "NextMtn": "语音菜单"})
            menu_extra_groups[page_grp] = [
                {
                    "Name": page_grp,
                    "File": menu_silent_rel,
                    "FadeIn": 0,
                    "FadeOut": 0,
                    "Text": f"【{cat_title}】({pg + 1}/{total_pages}) 点击选项立即播放：",
                    "TextDuration": 60000,
                    "Choices": choices_list,
                }
            ]
        category_root_choices.append({"Text": f"{cat_title} ({len(cat_entries)})", "NextMtn": cat_id})

    # Fallback if a cutscene-only model (e.g. rubyrose_s1_ennis) has only Idle and no other voices/motions
    if not category_root_choices and motion_groups.get("Idle"):
        idle_item = motion_groups["Idle"][0]
        play_item_counter += 1
        play_grp = f"MenuPlay_{play_item_counter:03d}"
        menu_extra_groups[play_grp] = [dict(idle_item)]
        menu_extra_groups["Menu_Cat_Motion"] = [
            {
                "Name": "Menu_Cat_Motion",
                "File": menu_silent_rel,
                "FadeIn": 0,
                "FadeOut": 0,
                "Text": "【动作预览】(1/1) 点击选项立即播放：",
                "TextDuration": 60000,
                "Choices": [
                    {"Text": idle_item["Name"], "NextMtn": play_grp},
                    {"Text": "« 返回主语音菜单", "NextMtn": "语音菜单"},
                ],
            }
        ]
        category_root_choices.append({"Text": "动作预览 (1)", "NextMtn": "Menu_Cat_Motion"})

    if category_root_choices:
        menu_root_entry = {
            "Name": "语音菜单",
            "File": menu_silent_rel,
            "FadeIn": 0,
            "FadeOut": 0,
            "Text": f"请选择要播放的{ident['char_name']}语音与动作分类（按 1 / M / V 或点击空白处呼出）：",
            "TextDuration": 60000,
            "Choices": category_root_choices,
        }
        motion_groups["Tap"] = [dict(menu_root_entry, Name="tap_voice_menu")]
        motion_groups["语音菜单"] = [dict(menu_root_entry)]
        motion_groups.update(menu_extra_groups)

    motion_groups = {k: v for k, v in motion_groups.items() if v}

    # 6. Expressions (ParamRingOn toggle when supported by .moc3)
    expressions_list: list[dict[str, str]] = []
    key_items: list[dict[str, Any]] = []
    if "语音菜单" in motion_groups:
        key_items.extend(
            [
                {"Input": 49, "DownMtn": "语音菜单"},  # VK_1
                {"Input": 77, "DownMtn": "语音菜单"},  # VK_M
                {"Input": 86, "DownMtn": "语音菜单"},  # VK_V
            ]
        )
    if has_ring_param:
        ring_on_exp = {
            "Type": "Live2D Expression",
            "FadeInTime": 0.3,
            "FadeOutTime": 0.3,
            "Parameters": [{"Id": "ParamRingOn", "Value": 1.0, "Blend": "Overwrite"}],
        }
        ring_off_exp = {
            "Type": "Live2D Expression",
            "FadeInTime": 0.3,
            "FadeOutTime": 0.3,
            "Parameters": [{"Id": "ParamRingOn", "Value": 0.0, "Blend": "Overwrite"}],
        }
        write_json(exp_dir / "ring_on.exp3.json", ring_on_exp)
        write_json(exp_dir / "ring_off.exp3.json", ring_off_exp)
        expressions_list = [
            {"Name": "佩戴誓约戒指", "File": "expressions/ring_on.exp3.json"},
            {"Name": "取下誓约戒指", "File": "expressions/ring_off.exp3.json"},
        ]
        motion_groups["誓约戒指切换"] = [
            {
                "Name": "toggle_ring",
                "File": menu_silent_rel,
                "FadeIn": 0,
                "FadeOut": 0,
                "MotionDuration": 50,
                "PostCommand": "next_exp",
            }
        ]
        key_items.append({"Input": 82, "DownMtn": "誓约戒指切换"})  # VK_R

    # 7. Clean minimal HitAreas verified against .moc3
    verified_hits = build_verified_hit_areas(moc_bytes, motion_groups)

    # 8. Inherit Options (ScaleFactor / PositionX / PositionY) from backup .moc3 SHA256 or stem
    moc_hash = hashlib.sha256(moc_bytes).hexdigest()[:16]
    opts_base = (
        bk_by_hash.get(moc_hash)
        or bk_by_stem.get(moc_name.lower())
        or {"ScaleFactor": 1.6, "PositionX": 0.0, "PositionY": 0.0}
    )

    file_refs: dict[str, Any] = {
        "Moc": moc_filename,
        "Textures": tex_rels,
    }
    if phys_filename:
        file_refs["Physics"] = phys_filename
        file_refs["PhysicsV2"] = {"File": phys_filename}
    file_refs["Expressions"] = expressions_list
    file_refs["Motions"] = motion_groups

    model3 = {
        "ConfVer": 0,
        "Type": 0,
        "FileReferences": file_refs,
        "Controllers": {
            "ParamHit": {},
            "ParamLoop": {},
            "KeyTrigger": {
                "Enabled": True,
                "Items": key_items,
            },
            "ParamTrigger": {},
            "AreaTrigger": {},
            "HandTrigger": {},
            "EyeBlink": {"MinInterval": 500, "MaxInterval": 6000, "Enabled": False},
            "LipSync": {"Gain": 5.0},
            "MouseTracking": {"SmoothTime": 0.15, "Enabled": True},
            "AutoBreath": {"Enabled": False},
            "ExtraMotion": {"Enabled": False},
            "Accelerometer": {"Enabled": True},
            "Microphone": {},
            "Transform": {},
            "FaceTracking": {"Enabled": True},
            "HandTracking": {},
            "ParamValue": {},
            "PartOpacity": {},
            "ArtmeshOpacity": {},
            "ArtmeshColor": {},
            "ArtmeshCulling": {"DefaultMode": 0},
            "IntimacySystem": {},
        },
        "HitAreas": verified_hits,
        "Options": {
            "Id": f"{mk}_live2d",
            "ScaleFactor": opts_base["ScaleFactor"],
            "PositionX": opts_base["PositionX"],
            "PositionY": opts_base["PositionY"],
            "TexType": 0,
        },
    }

    write_json(out_dir / ".model3.json", model3)
    return {
        "model_key": mk,
        "status": "built",
        "char": ident["char_name"],
        "skin": ident["skin_name"],
        "is_base": is_base,
        "out_dir": str(out_dir),
        "motions": len(motions_by_stem),
        "wavs": len(extracted_wavs),
        "hit_areas": len(verified_hits),
        "has_ring": has_ring_param,
        "has_physics": phys_filename is not None,
        "options_src": "hash" if moc_hash in bk_by_hash else ("stem" if moc_name.lower() in bk_by_stem else "default"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch build SoulTide Live2DViewerEX packages.")
    parser.add_argument("--char", help="Only build models whose char_key or Chinese name matches this substring.")
    parser.add_argument("--model", help="Only build models whose model_key matches this substring.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip models that already have .model3.json.")
    parser.add_argument("--dry-run", action="store_true", help="Only print resolved plan without writing files.")
    args = parser.parse_args()

    t0 = time.time()
    repo = FullLuaRepo()
    meta = load_metadata_tables(repo)
    catalog = scan_live2d_bundles()
    bk_by_hash, bk_by_stem = index_backup_options()

    identities: dict[str, dict[str, Any]] = {}
    for mk in sorted(catalog):
        identities[mk] = resolve_model_identity(mk, meta)
    assign_unique_output_dirs(identities)

    # Sort by (char_key, model_key) so CvCache stays warm across all skins of a character
    ordered_keys = sorted(catalog.keys(), key=lambda k: (identities[k]["char_key"], k))

    results: list[dict[str, Any]] = []
    cv_cache = CvCache()
    ab_env_cache: dict[Path, Any] = {}

    for mk in ordered_keys:
        ident = identities[mk]
        if args.char and args.char.lower() not in ident["char_key"] and args.char not in ident["char_name"]:
            continue
        if args.model and args.model.lower() not in mk:
            continue

        if mk == "snow":
            results.append({"model_key": mk, "status": "skipped", "reason": "non_character_weather_effect"})
            continue

        if args.dry_run:
            results.append({
                "model_key": mk,
                "status": "plan",
                "char": ident["char_name"],
                "skin": ident["skin_name"],
                "out_dir": str(ident["out_dir"]),
                "is_base": ident["is_base"],
                "ab": catalog[mk]["ab_name"],
            })
            continue

        res = build_single_model(
            entry=catalog[mk],
            ident=ident,
            meta=meta,
            repo=repo,
            cv_cache=cv_cache,
            bk_by_hash=bk_by_hash,
            bk_by_stem=bk_by_stem,
            ab_env_cache=ab_env_cache,
            skip_existing=args.skip_existing,
        )
        results.append(res)
        detail = res.get("reason") or f"mot={res['motions']} wav={res['wavs']} hit={res['hit_areas']}"
        print(f"[{res['status']:7s}] {mk:32s} -> {ident.get('char_name','')}/{ident.get('skin_name','')} ({detail})", flush=True)

    summary = {
        "elapsed_sec": round(time.time() - t0, 2),
        "total_processed": len(results),
        "built": sum(1 for r in results if r["status"] == "built"),
        "skipped": [r for r in results if r["status"] == "skipped"],
        "failed": [r for r in results if r["status"] == "failed"],
    }
    print("\n=== BATCH BUILD SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
