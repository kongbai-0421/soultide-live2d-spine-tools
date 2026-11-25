"""Batch build SoulTide base-skin (原皮) Live2DViewerEX Spine 3.8 packages.

Builds:
  All 54 playable characters' official base-skin BattleHead Spines under:
    E:\\A灵魂潮汐\\Live2D与Spine模型\\spine\\<角色名>\\原皮\\

Sources voices, Chinese subtitles, and interaction mappings from each character's
verified Live2D `原皮` package, and keeps all output `(position_x=0, position_y=0)`
calibrated with valid bone-mapped `hit_areas` and `verify_batch_spine.py` compliance.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from batch_spine_builder import (
    BACKUP_SPINE_ROOT,
    SPINE_OUT_ROOT,
    _compute_fallback_hit_areas,
    _extract_spine_unit_from_ab,
    parse_spine38_binary,
)
from soultide_common import CDN_ROOT, load_ab, write_json

L2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
REPORT_PATH = TOOLS_DIR / "batch_orig_spine_build_report.json"

# Backup folder name -> canonical output character folder name
BKP_TO_CANON_CHAR: dict[str, str] = {
    "傲慢": "斯贝比尔",
    "安东尼娜": "安东妮娜",
    "艾尼斯": "艾妮斯",
    "贞德": "贞德·卢瓦尔",
    "露比": "露比·罗斯",
}

# BattleHead filename overrides when stem differs from <Slug>_Dress_01_BattleHead
EXTRA_BACKUP_MATCHES: dict[str, str] = {
    "和铃": "heling_dress_battlehead",
    "菲洛多希": "philodoxy_dress_battlehead",
    "越一弥心": "etsukazumiko_dress_battlehead",
}


def _index_battlehead_units() -> dict[str, tuple[Any, str]]:
    """Index all Dress_01 / Dress BattleHead .skel.bytes across 23_spine/battle."""
    out: dict[str, tuple[Any, str]] = {}
    for ab in sorted((CDN_ROOT / "23_spine" / "battle").rglob("*.ab")):
        env = load_ab(ab)
        for k in (env.container or {}).keys():
            low = k.lower()
            if not low.endswith(".skel.bytes"):
                continue
            if "battlehead" in low and ("_01_" in low or "_dress_battlehead" in low):
                stem = Path(k).name[: -len(".skel.bytes")].lower().strip()
                out[stem] = (env, k)
    return out


def _pick_idle_anim(anims: list[str]) -> str:
    for cand in ("idle", "standby", "standby2", "animation"):
        if cand in anims:
            return cand
    return anims[0]


def _pick_greet_anim(anims: list[str], idle_anim: str) -> str:
    for cand in ("greet1", "greet", "victory", "action", "skill", "special", "attack"):
        if cand in anims:
            return cand
    return idle_anim


def _resolve_battlehead_stem(char_bkp_dir: Path, char_name: str, bh_index: dict[str, tuple[Any, str]]) -> str | None:
    """Resolve canonical 23_spine/battle stem from 备份/spine/<char>/原皮/."""
    yp = char_bkp_dir / "原皮"
    if char_bkp_dir.name in EXTRA_BACKUP_MATCHES:
        k = EXTRA_BACKUP_MATCHES[char_bkp_dir.name]
        if k in bh_index:
            return k
    if char_name in EXTRA_BACKUP_MATCHES:
        k = EXTRA_BACKUP_MATCHES[char_name]
        if k in bh_index:
            return k

    for fp in sorted(yp.iterdir()):
        if fp.name.endswith((".skel", ".skel.json", ".skel.skel", ".atlas.txt")):
            stem = re.sub(r"(\.skel(\.json|\.skel)?|\.atlas\.txt)$", "", fp.name, flags=re.I)
            low_ns = stem.lower().replace(" ", "")
            # Direct stem match or whitespace-tolerant match (e.g. "Juewa _Dress_01_BattleHead")
            if stem.lower() in bh_index:
                return stem.lower()
            for cand in bh_index:
                if cand.replace(" ", "") == low_ns:
                    return cand
    return None


def _load_l2d_voices(canon_char: str) -> dict[str, list[dict[str, Any]]]:
    """Read verified Live2D 原皮 voice/subtitle items grouped by semantic category."""
    l2d_dir = L2D_ROOT / canon_char / "原皮"
    cfg_p = l2d_dir / ".model3.json"
    out: dict[str, list[dict[str, Any]]] = {}
    if not cfg_p.is_file():
        return out
    data = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
    motions = data.get("FileReferences", {}).get("Motions", {})
    seen_sounds: dict[str, set[str]] = {}
    for grp, items in motions.items():
        if not isinstance(items, list) or grp.startswith("Menu"):
            continue
        for it in items:
            snd = it.get("Sound", "")
            if not snd:
                continue
            src_wav = l2d_dir / snd
            if not src_wav.is_file():
                continue
            key = f"{snd}|{it.get('Text', '')}"
            s = seen_sounds.setdefault(grp, set())
            if key in s:
                continue
            s.add(key)
            out.setdefault(grp, []).append({
                "src_wav": src_wav,
                "wav_name": src_wav.name,
                "text": it.get("Text", ""),
                "text_duration": int(it.get("TextDuration", 3500) or 3500),
            })
    return out


def _build_package(
    canon_char: str,
    skin_folder: str,
    model_id: str,
    main_env: Any,
    main_cpath: str,
    bkp_cfg: dict[str, Any] | None,
    bj_specs: list[tuple[Any, str]] | None = None,
    default_target_height: float = 540.0,
) -> dict[str, Any]:
    """Extract skeleton + voices + hit_areas and write a complete EX Spine 3.8 package."""
    out_dir = SPINE_OUT_ROOT / canon_char / skin_folder
    if out_dir.exists():
        shutil.rmtree(out_dir)
    aud_dir = out_dir / "audio"
    aud_dir.mkdir(parents=True, exist_ok=True)

    main_meta = _extract_spine_unit_from_ab(main_env, main_cpath, out_dir, strip_bg=True)
    parsed = main_meta["parsed"]
    anims = parsed["anims"]
    bones = {b["name"] for b in parsed["bones"]}
    idle_anim = _pick_idle_anim(anims)
    greet_anim = _pick_greet_anim(anims, idle_anim)

    # Calibrate base_scale from backup config if sane, else auto-scale cleanly from skeleton bounds
    bh = max(100.0, float(parsed["bounds"][3]))
    auto_scale = round(max(0.05, min(0.38, default_target_height / bh)), 5)
    base_scale = auto_scale
    if bkp_cfg:
        b_sc = float(bkp_cfg.get("options", {}).get("scale_factor", 0.0) or 0.0)
        if 0.04 <= b_sc <= 0.42:
            base_scale = round(b_sc, 5)

    # Build optional bj_* dynamic background submodels (e.g. Clotho_defaultdress_bj_01..04)
    sub_cmds: list[str] = []
    if bj_specs:
        neg_orders = [-3, -2, -1]
        pos_orders = [1, 2, 3]
        for idx, (bj_env, bj_cpath) in enumerate(bj_specs, start=1):
            sub_name = f"bj_{idx:02d}"
            sdir = out_dir / "submodels" / sub_name
            bj_meta = _extract_spine_unit_from_ab(bj_env, bj_cpath, sdir, strip_bg=False)
            bj_anims = bj_meta["parsed"]["anims"]
            bj_idle = _pick_idle_anim(bj_anims)
            ord_val = neg_orders.pop(0) if neg_orders else pos_orders.pop(0)
            bj_cfg = {
                "conf_ver": 1,
                "type": 9,
                "controllers": {"param_hit": {}, "param_loop": {}, "intimacy_system": {}, "slot_opacity": {}, "slot_color": {}},
                "hit_areas": [],
                "motions": {"idle": [{"name": bj_idle, "file": bj_idle, "file_loop": True}]},
                "options": {
                    "id": f"{model_id}_{sub_name}",
                    "scale_factor": base_scale,
                    "position_x": 0.0,
                    "position_y": 0.0,
                    "tex_type": 0,
                    "edge_padding": False,
                },
                "skeleton": bj_meta["skeleton"],
                "atlases": [{"atlas": bj_meta["atlas"], "tex_names": bj_meta["tex_names"], "textures": bj_meta["textures"]}],
            }
            write_json(sdir / ".config.json", bj_cfg)
            sub_cmds.append(f"add_submodel submodels/{sub_name}/.config.json {ord_val}")
    submodel_cmd = "; ".join(sub_cmds)

    # Copy all Live2D 原皮 WAVs into audio/ cleanly
    voices = _load_l2d_voices(canon_char)
    copied_wavs: set[str] = set()

    def mk_mtn(name: str, anim_file: str, vitem: dict[str, Any] | None = None, cmd: str = "") -> dict[str, Any]:
        ent: dict[str, Any] = {
            "name": name,
            "file": anim_file,
        }
        if anim_file:
            ent["fade_in"] = 100
            ent["fade_out"] = 100
        if vitem:
            wn = vitem["wav_name"]
            if wn not in copied_wavs:
                shutil.copy2(vitem["src_wav"], aud_dir / wn)
                copied_wavs.add(wn)
            ent["sound"] = f"audio/{wn}"
            if vitem["text"]:
                ent["text"] = vitem["text"]
                ent["text_duration"] = vitem["text_duration"]
        if cmd:
            ent["command"] = cmd
        return ent

    def pick_from_groups(grps: tuple[str, ...]) -> list[dict[str, Any]]:
        res: list[dict[str, Any]] = []
        seen: set[str] = set()
        for g in grps:
            for v in voices.get(g, []):
                if v["wav_name"] not in seen:
                    seen.add(v["wav_name"])
                    res.append(v)
        return res

    def pick_tagged(grps: tuple[str, ...], allow_subs: tuple[str, ...], ban_stems: set[str] | None = None) -> list[dict[str, Any]]:
        res: list[dict[str, Any]] = []
        seen: set[str] = set()
        for g in grps:
            for v in voices.get(g, []):
                wn = v["wav_name"]
                low = Path(wn).stem.lower()
                if wn in seen or (ban_stems and low in ban_stems):
                    continue
                if "touch_reaction" in low or "after_marriage_touch" in low:
                    continue
                if any(sub in low for sub in allow_subs):
                    seen.add(wn)
                    res.append(v)
        return res

    # Build rich EX motions dictionary (strict per-part voice routing, zero cross-part leakage)
    start_voices = pick_from_groups(("Morning", "Noon", "Evening", "Greeting", "Start"))
    chat_voices = pick_from_groups(("Greeting", "Morning", "Noon", "Evening", "Midnight", "Gift", "Food", "Archive", "Sad", "TouchSpecial"))
    tap_head = pick_tagged(("Tap头",), ("touch_head",)) or pick_from_groups(("Tap头",))
    tap_chest = pick_tagged(("Tap胸",), ("touch_breast", "touch_chest", "touch_bra", "touch_locked"), ban_stems={"juewa_touch_locked"}) or pick_from_groups(("Tap胸",))
    tap_hand = pick_tagged(("Tap手",), ("touch_hand",)) or pick_from_groups(("Tap手",))
    tap_leg = pick_tagged(("Tap臀部",), ("touch_hip", "touch_leg", "touch_locked")) or pick_from_groups(("Tap臀部",))
    battle_voices = pick_from_groups(("Battle", "ExtraMotions"))

    other_anims = [a for a in anims if a != idle_anim]
    def anim_at(i: int, fallback: str) -> str:
        return other_anims[i % len(other_anims)] if other_anims else fallback

    start_items: list[dict[str, Any]] = []
    for idx, v in enumerate((start_voices[:3] if start_voices else [None])):
        start_items.append(mk_mtn(f"start_{idx}", idle_anim, v, cmd=submodel_cmd))

    def map_group(vlist: list[dict[str, Any]], tag: str, max_items: int = 8) -> list[dict[str, Any]]:
        # 原皮 Spine 触摸与闲聊仅触发语音和字幕，不触发战斗/受击动画 (file="")
        if vlist:
            return [mk_mtn(f"{tag}_{i:02d}", "", v) for i, v in enumerate(vlist[:max_items])]
        return [mk_mtn(f"{tag}_00", "")]

    # Full battle/animation showcase
    action_items: list[dict[str, Any]] = []
    for i, a in enumerate(anims):
        if a == idle_anim:
            continue
        bv = battle_voices[i % len(battle_voices)] if battle_voices else None
        action_items.append(mk_mtn(f"anim_{a}", a, bv))

    motions: dict[str, Any] = {
        "idle": [{"name": idle_anim, "file": idle_anim, "fade_in": 10, "fade_out": 10, "file_loop": True}],
        "start": start_items,
        "闲聊与问答": map_group(chat_voices or start_voices, "chat", max_items=16),
        "头": map_group(tap_head, "head", max_items=6),
        "左手": map_group(tap_hand, "lhand", max_items=4),
        "右手": map_group(list(reversed(tap_hand)) if tap_hand else [], "rhand", max_items=4),
        "胸": map_group(tap_chest, "chest", max_items=6),
        "腿": map_group(tap_leg, "leg", max_items=4),
        "足": map_group(list(reversed(tap_leg)) if tap_leg else [], "foot", max_items=4),
    }
    if action_items:
        motions["战斗与动作"] = action_items
    if submodel_cmd:
        motions["reload_bg"] = [{"name": "reload_submodels", "file": idle_anim, "command": submodel_cmd}]

    # Hit areas (inherit valid bones from backup or compute cleanly from idle pose)
    hit_areas: list[dict[str, Any]] = []
    if bkp_cfg and bkp_cfg.get("hit_areas"):
        for ha in bkp_cfg["hit_areas"]:
            bid = str(ha.get("id", ""))
            mot = str(ha.get("motion", ""))
            if bid in bones:
                if mot == "身体":
                    mot = "胸"
                if mot not in motions:
                    mot = "头" if "头" in motions else "闲聊与问答"
                nha = {
                    "name": ha.get("name", mot),
                    "id": bid,
                    "motion": mot,
                    "width": float(ha.get("width", 1.5)),
                    "height": float(ha.get("height", 1.5)),
                }
                if "center_x" in ha:
                    nha["center_x"] = float(ha["center_x"])
                if "center_y" in ha:
                    nha["center_y"] = float(ha["center_y"])
                hit_areas.append(nha)
    if not hit_areas:
        hit_areas = _compute_fallback_hit_areas(parsed, idle_anim, motions)

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
            "id": model_id,
            "scale_factor": base_scale,
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 0,
            "edge_padding": False,
            "shader_type": 0,
        },
        "skeleton": main_meta["skeleton"],
        "atlases": [{"atlas": main_meta["atlas"], "tex_names": main_meta["tex_names"], "textures": main_meta["textures"]}],
    }
    write_json(out_dir / ".config.json", cfg)
    return {
        "char": canon_char,
        "skin": skin_folder,
        "out_dir": str(out_dir),
        "anims": len(anims),
        "wavs": len(copied_wavs),
        "hit_areas": len(hit_areas),
        "submodels": len(sub_cmds),
        "base_scale": base_scale,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build all base-skin (原皮) Spine 3.8 packages.")
    parser.add_argument("--char", type=str, default="", help="Filter by character name substring")
    args = parser.parse_args()

    bh_index = _index_battlehead_units()
    built: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    # 1. Build all 54 playable characters' BattleHead 原皮 packages
    for d in sorted(BACKUP_SPINE_ROOT.iterdir()):
        if not d.is_dir() or not (d / "原皮").is_dir():
            continue
        canon_char = BKP_TO_CANON_CHAR.get(d.name, d.name)
        if args.char and args.char not in canon_char:
            continue
        try:
            stem = _resolve_battlehead_stem(d, canon_char, bh_index)
            if not stem:
                raise FileNotFoundError(f"Could not map BattleHead in 23_spine/battle for {d.name}")
            env, cpath = bh_index[stem]
            bkp_cfg_p = d / "原皮" / ".config.json"
            bkp_cfg = json.loads(bkp_cfg_p.read_text(encoding="utf-8-sig")) if bkp_cfg_p.is_file() else None
            res = _build_package(
                canon_char=canon_char,
                skin_folder="原皮",
                model_id=f"{stem}_orig",
                main_env=env,
                main_cpath=cpath,
                bkp_cfg=bkp_cfg,
                bj_specs=None,
                default_target_height=460.0,
            )
            built.append(res)
            print(f"[原皮] OK {canon_char}/原皮 (anims={res['anims']}, wavs={res['wavs']}, ha={res['hit_areas']}, scale={res['base_scale']})", flush=True)
        except Exception as exc:
            errors.append({"target": f"{canon_char}/原皮", "error": str(exc)})
            print(f"[原皮] ERROR {canon_char}/原皮: {exc}", flush=True)

    report = {"built_count": len(built), "error_count": len(errors), "errors": errors, "built": built}
    write_json(REPORT_PATH, report)
    print(f"[batch_orig_spine_builder] DONE built={len(built)} errors={len(errors)} -> {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    main()
