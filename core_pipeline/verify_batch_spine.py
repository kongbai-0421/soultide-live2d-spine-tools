"""End-to-end structural and asset verification for ALL batch-built SoulTide Spine packages."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from batch_spine_builder import parse_spine38_binary

SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
DB_PATH = Path(r"D:\A灵魂潮汐-本地化\服务器\soultide.db")
VERIFY_REPORT_PATH = TOOLS_DIR / "batch_spine_verify_report.json"
EXPECTED_SPINE_VK_CODES = {65, 66, 67, 68, 69, 70, 71, 72, 77, 78, 82, 114}


def _assert_spine_mtn_ref(mots: dict[str, Any], ref: str, label: str) -> None:
    if ":" in ref:
        tgrp, tname = ref.split(":", 1)
        assert tgrp in mots, f"{label} target group missing: {ref}"
        assert any(m.get("name") == tname for m in mots[tgrp]), (
            f"{label} target motion name '{tname}' missing in group '{tgrp}'"
        )
    else:
        assert ref in mots, f"{label} target group missing: {ref}"


def _verify_spine_key_trigger_and_cmds(
    skin_dir: Path,
    cfg: dict[str, Any],
    cfg_label: str,
    root_anims: set[str] | None = None,
    root_slots: set[str] | None = None,
) -> None:
    mots = cfg["motions"]
    if root_anims is not None:
        has_marry_anim = any("marry" in a.lower() or "oath" in a.lower() for a in root_anims)
        if not has_marry_anim:
            assert "誓约模式全动作" not in mots, f"{cfg_label}: non-oath skin must not have '誓约模式全动作'"
    kt = (cfg.get("controllers") or {}).get("key_trigger") or {}
    assert kt.get("enabled") is True, f"{cfg_label}: controllers.key_trigger.enabled must be true"
    items = kt.get("items") or []
    assert len(items) >= 7, f"{cfg_label}: expected >=7 key_trigger items, got {len(items)}"
    seen_inputs: set[int] = set()
    for it in items:
        inp = it.get("input")
        assert inp in EXPECTED_SPINE_VK_CODES, f"{cfg_label}: invalid Windows VK input code in key_trigger: {it}"
        assert inp not in seen_inputs, f"{cfg_label}: duplicate key_trigger input code: {inp}"
        seen_inputs.add(inp)
        dm = it.get("down_mtn")
        um = it.get("up_mtn")
        assert dm or um, f"{cfg_label}: key_trigger item has neither down_mtn nor up_mtn: {it}"
        if dm:
            _assert_spine_mtn_ref(mots, dm, f"{cfg_label}:key_trigger({inp}).down_mtn")
        if um:
            _assert_spine_mtn_ref(mots, um, f"{cfg_label}:key_trigger({inp}).up_mtn")

    for grp, grp_items in mots.items():
        for item in grp_items:
            if item.get("next_mtn"):
                _assert_spine_mtn_ref(mots, item["next_mtn"], f"{cfg_label}:{grp}.next_mtn")
            for ch in item.get("choices") or []:
                _assert_spine_mtn_ref(mots, ch["next_mtn"], f"{cfg_label}:{grp}.choice.next_mtn")
            if grp in ("reload_bg", "背景开关") and item.get("command"):
                seen_add = False
                for seg in item["command"].split(";"):
                    toks = seg.strip().split()
                    if not toks:
                        continue
                    if toks[0] == "remove_submodel":
                        assert len(toks) >= 2, f"{cfg_label}:{grp} invalid remove_submodel: {seg}"
                        assert (skin_dir / toks[1]).is_file(), f"{cfg_label}:{grp} missing submodel file: {toks[1]}"
                        if grp == "reload_bg":
                            assert not seen_add, f"{cfg_label}:reload_bg has remove_submodel after add_submodel: {item['command']}"
                    elif toks[0] == "add_submodel":
                        assert len(toks) == 3, f"{cfg_label}:{grp} invalid add_submodel: {seg}"
                        assert (skin_dir / toks[1]).is_file(), f"{cfg_label}:{grp} missing submodel file: {toks[1]}"
                        seen_add = True
                    elif toks[0] == "slot_opacities":
                        assert len(toks) >= 2 and toks[1] in ("lock", "set", "unlock"), (
                            f"{cfg_label}:{grp} invalid slot_opacities verb: {seg}"
                        )
                        if toks[1] in ("lock", "set"):
                            assert len(toks) in (4, 5), f"{cfg_label}:{grp} invalid slot_opacities args: {seg}"
                            float(toks[3])
                            if len(toks) == 5:
                                float(toks[4])
                        if len(toks) >= 3 and toks[2] and root_slots is not None:
                            for sn in toks[2].split(","):
                                assert sn in root_slots, f"{cfg_label}:{grp} slot_opacities unknown slot '{sn}'"


def _check_ogg(p: Path) -> None:
    assert p.is_file(), f"Missing OGG audio: {p}"
    assert p.suffix.lower() == ".ogg", f"Expected .ogg extension, got {p}"
    hdr = p.read_bytes()[:4]
    assert hdr == b"OggS", f"Invalid OggS header in {p}: {hdr!r}"


def _parse_atlas_regions(atlas_path: Path, model_dir: Path) -> list[str]:
    lines = atlas_path.read_text(encoding="utf-8").splitlines()
    cur_png = None
    cur_w = cur_h = 0
    regions: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if s.lower().endswith((".png", ".webp")):
            cur_png = model_dir / s
            assert cur_png.is_file(), f"Atlas page image missing: {cur_png}"
            i += 1
            sz_line = lines[i].strip()
            assert sz_line.startswith("size:"), f"Expected size line, got {sz_line}"
            cur_w, cur_h = [int(v.strip()) for v in sz_line[5:].split(",")]
            with Image.open(cur_png) as im:
                assert im.size == (cur_w, cur_h), f"{cur_png} size {im.size} != atlas {(cur_w, cur_h)}"
            while i + 1 < len(lines) and any(
                lines[i + 1].strip().startswith(p) for p in ("format:", "filter:", "repeat:", "size:")
            ):
                i += 1
        elif not ln.startswith((" ", "\t")) and ":" not in s:
            rname = s
            regions.append(rname)
            xy = sz = None
            rot = "false"
            while i + 1 < len(lines) and (lines[i + 1].startswith((" ", "\t")) or ":" in lines[i + 1]):
                i += 1
                kv = lines[i].strip()
                if kv.startswith("xy:"):
                    xy = [int(v.strip()) for v in kv[3:].split(",")]
                elif kv.startswith("size:"):
                    sz = [int(v.strip()) for v in kv[5:].split(",")]
                elif kv.startswith("rotate:"):
                    rot = kv[7:].strip().lower()
            assert xy is not None and sz is not None, f"Incomplete region '{rname}' in {atlas_path}"
            x, y = xy
            w, h = sz
            pw, ph = (h, w) if rot in ("true", "90", "270") else (w, h)
            assert 0 <= x and 0 <= y and x + pw <= cur_w and y + ph <= cur_h, (
                f"Atlas region '{rname}' out of bounds ({x},{y},{pw},{ph}) in {cur_png.name} ({cur_w}x{cur_h})"
            )
        i += 1
    assert regions, f"No atlas regions parsed in {atlas_path}"
    return regions


def _inspect_skeleton(skel_path: Path) -> tuple[str, set[str], set[str]]:
    assert skel_path.is_file(), f"Missing skeleton: {skel_path}"
    raw = skel_path.read_bytes()
    if raw.lstrip().startswith(b"{"):
        data = json.loads(raw.decode("utf-8"))
        ver = data["skeleton"]["spine"]
        anims = set(data.get("animations", {}).keys())
        bones = {b["name"] for b in data.get("bones", [])}
        return ver, anims, bones
    assert b"3.8.79" in raw[:128], f"Unexpected binary Spine version header in {skel_path}"
    parsed = parse_spine38_binary(raw)
    return parsed["version"], set(parsed["anims"]), {b["name"] for b in parsed["bones"]}


def verify_skin_dir(skin_dir: Path) -> dict[str, Any]:
    cfg_path = skin_dir / ".config.json"
    assert cfg_path.is_file(), f"Missing .config.json in {skin_dir}"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    assert cfg.get("type") == 9, f"Unexpected config type {cfg.get('type')}"
    opts = cfg["options"]
    base_scale = float(opts["scale_factor"])
    assert float(opts["position_x"]) == 0.0 and float(opts["position_y"]) == 0.0, "Main position must be (0.0, 0.0)"

    ver, root_anims, root_bones = _inspect_skeleton(skin_dir / cfg["skeleton"])
    assert ver.startswith("3.8."), f"Unexpected Spine version: {ver}"

    for a in cfg["atlases"]:
        _parse_atlas_regions(skin_dir / a["atlas"], skin_dir)
        for tex in a["textures"]:
            assert (skin_dir / tex).is_file(), f"Missing texture {tex}"

    hit_areas = cfg.get("hit_areas", [])
    assert len(hit_areas) >= 3, f"Expected at least 3 hit_areas entries, found {len(hit_areas)}"
    seen_ha_bones: set[str] = set()
    bg_bone_re = re.compile(
        r"(?:^|_)(?:bg|bj|background|back|yingzi|shadow|deng|light|shafa|sofa|zhuo|table|yi|chair|"
        r"chuang|bed|window|chuanghu|cloud|yun|shui|water|hua_|flower|tree|shu_|cat|mao|dog|gou|"
        r"bird|niao|book|shu\d|cup|bei|wine|jiu|lazhu|candle|guang|fx|effect|smoke|yanwu|wuzi|"
        r"room|floor|diban|wall|qiang|curtain|chuanglian|pillow|zhentou|qiu|ball|umbrella|san|"
        r"frame|kuang|mirror|jingzi|clock|zhong|music|yinfu|star|xing|moon|yue)(?:_|\d|$)",
        re.I,
    )
    for ha in hit_areas:
        bid = ha["id"]
        hmot = ha["motion"]
        assert bid in root_bones, f"HitArea bone '{bid}' missing from skeleton"
        assert bid != "root", f"HitArea bone cannot be 'root' in {skin_dir}"
        assert not bg_bone_re.search(bid), f"HitArea bone '{bid}' for '{hmot}' is a background/prop bone"
        if hmot == "胸":
            assert not re.search(r"(xiaoxiong|fasheng|guazhui|tou|lian|shou|tui|jiao)", bid, re.I), (
                f"HitArea '胸' bound to invalid bone '{bid}'"
            )
        elif hmot == "足":
            assert not re.search(
                r"(zui|zuiba|bizui|zuoshou|zuobi|zuodabi|zuoxiaobi|zuoxiu|zuoyan|zuomei|zuojiemao|tou|lian|xiong|shou|qun|weisha|fasheng|guazhui)",
                bid,
                re.I,
            ), f"HitArea '足' bound to invalid bone '{bid}'"
        assert bid not in seen_ha_bones, f"Duplicate HitArea bone '{bid}' in {skin_dir}"
        seen_ha_bones.add(bid)
        assert hmot in cfg["motions"], f"HitArea motion '{hmot}' missing"
        assert float(ha.get("width", 0)) > 0 and float(ha.get("height", 0)) > 0, f"Invalid HitArea size: {ha}"

    idle_list = cfg["motions"].get("idle", [])
    assert len(idle_list) == 1 and idle_list[0].get("file_loop") is True, f"Invalid idle group: {idle_list}"

    # Verify Submodels from motions["start"]
    sub_models_by_id: dict[str, dict[str, Any]] = {}
    sub_specs: list[dict[str, Any]] = []
    seen_ids = {opts["id"]}
    used_orders: set[int] = set()

    start_items = cfg["motions"].get("start", [])
    start_cmd = start_items[0].get("command", "") if start_items else ""
    if start_cmd:
        for cmd in start_cmd.split(";"):
            cmd = cmd.strip()
            if not cmd:
                continue
            toks = cmd.split()
            assert len(toks) == 3 and toks[0] == "add_submodel", f"Unexpected start cmd: {cmd}"
            sub_cfg_path = skin_dir / toks[1]
            order = int(toks[2])
            assert -3 <= order <= 3 and order != 0 and order not in used_orders, f"Invalid/dup order: {order}"
            used_orders.add(order)

            sc = json.loads(sub_cfg_path.read_text(encoding="utf-8"))
            sopts = sc["options"]
            sid = sopts["id"]
            assert sid not in seen_ids, f"Duplicate submodel ID: {sid}"
            seen_ids.add(sid)
            assert float(sopts["position_x"]) == 0.0 and float(sopts["position_y"]) == 0.0, f"Submodel {sid} pos != (0,0)"
            ssc = float(sopts["scale_factor"])
            assert base_scale * 0.1 <= ssc <= base_scale * 4.0, (
                f"Submodel {sid} scale_factor={ssc} uncalibrated vs base_scale={base_scale}"
            )

            sdir = sub_cfg_path.parent
            sver, sanims, _ = _inspect_skeleton(sdir / sc["skeleton"])
            assert sver.startswith("3.8."), f"Submodel {sid} Spine version={sver}"
            regions = []
            for a in sc["atlases"]:
                regions.extend(_parse_atlas_regions(sdir / a["atlas"], sdir))
            sub_models_by_id[sid] = {"cfg": sc, "anims": sanims, "ver": sver, "regions": len(regions), "order": order}
            sub_specs.append({"id": sid, "order": order, "scale": ssc, "regions": len(regions)})

    assert len(sub_specs) <= 6, f"Exceeded max 6 submodels: {len(sub_specs)}"

    is_battlehead = skin_dir.name.startswith("原皮") or (not start_cmd and "战斗与动作" in cfg["motions"])
    orig_voice_only_grps = {"头", "胸", "左手", "右手", "腿", "足", "闲聊与问答"}
    cmd_only_grps = {"背景开关", "背景菜单"}

    wavs_checked: set[str] = set()
    start_mtn_cmds = 0
    for grp, items in cfg["motions"].items():
        for item in items:
            mfile = item.get("file", "")
            if is_battlehead and grp in orig_voice_only_grps:
                assert mfile == "", f"战斗/原皮 Spine '{skin_dir.name}' group '{grp}' must be voice-only (file==''), got '{mfile}'"
            elif grp in cmd_only_grps and mfile == "":
                pass
            else:
                assert mfile in root_anims, f"Anim '{mfile}' missing in main skeleton"
            if "sound" in item and item["sound"]:
                _check_ogg(skin_dir / item["sound"])
                wavs_checked.add(item["sound"])
            if "text" in item and item["text"]:
                assert "{$br}" not in item["text"] and "I18N" not in item["text"], f"Dirty text: {item['text']}"
            if "command" in item and item["command"].startswith("start_mtn "):
                _, tid, gm = item["command"].split()
                tgrp, tmtn = gm.split(":")
                assert tid in sub_models_by_id, f"Target submodel {tid} missing"
                sm = sub_models_by_id[tid]
                assert tgrp in sm["cfg"]["motions"], f"Target group {tgrp} missing in {tid}"
                assert any(m["name"] == tmtn for m in sm["cfg"]["motions"][tgrp]), f"Target mtn {tmtn} missing in {tid}"
                assert tmtn in sm["anims"], f"Spine anim '{tmtn}' missing in {tid}"
                start_mtn_cmds += 1

    leftover_wavs = (
        (list((skin_dir / "audio").glob("*.wav")) if (skin_dir / "audio").is_dir() else [])
        + (list((skin_dir / "bgm").glob("*.wav")) if (skin_dir / "bgm").is_dir() else [])
    )
    assert not leftover_wavs, f"Found leftover .wav files in {skin_dir}: {leftover_wavs[:3]}"

    bgm_files = list((skin_dir / "bgm").glob("*.ogg")) if (skin_dir / "bgm").is_dir() else []
    for bf in bgm_files:
        _check_ogg(bf)

    # Lazily resolve main skeleton slot names only if slot_opacities command is used
    root_slots: set[str] | None = None
    if any(
        "slot_opacities" in str(it.get("command") or "")
        for g in ("reload_bg", "背景开关")
        for it in (cfg["motions"].get(g) or [])
    ):
        import spine38_binary_to_json as _s38
        _raw = (skin_dir / cfg["skeleton"]).read_bytes()
        _sd = json.loads(_raw.decode("utf-8-sig")) if _raw.lstrip().startswith(b"{") else _s38.spine38_binary_to_json(_raw)
        root_slots = {sl["name"] for sl in (_sd.get("slots") or [])}

    # Verify KeyTrigger VK codes, choice/next_mtn refs, non-oath guard, and reload_bg/bg_toggle commands
    _verify_spine_key_trigger_and_cmds(skin_dir, cfg, ".config.json", root_anims, root_slots)

    # Verify Scheme A sibling multi-language configs (config_en.config.json & config_ja.config.json)
    for lang_fn in ("config_en.config.json", "config_ja.config.json"):
        lp = skin_dir / lang_fn
        assert lp.is_file(), f"Missing Scheme A multi-language config: {lp}"
        lcfg = json.loads(lp.read_text(encoding="utf-8"))
        assert set(lcfg["motions"].keys()) == set(cfg["motions"].keys()), f"{lang_fn} motions group mismatch"
        assert lcfg.get("hit_areas") == cfg.get("hit_areas"), f"{lang_fn} hit_areas out of sync with .config.json"
        assert (lcfg.get("controllers") or {}).get("key_trigger") == (cfg.get("controllers") or {}).get("key_trigger"), (
            f"{lang_fn} controllers.key_trigger out of sync with .config.json"
        )
        _verify_spine_key_trigger_and_cmds(skin_dir, lcfg, lang_fn, root_anims, root_slots)
        for lgrp, litems in lcfg["motions"].items():
            for litem in litems:
                lmfile = litem.get("file", "")
                if is_battlehead and lgrp in orig_voice_only_grps:
                    assert lmfile == "", f"{lang_fn} 战斗/原皮 group '{lgrp}' must have file=='', got '{lmfile}'"
                elif lgrp in cmd_only_grps and lmfile == "":
                    pass
                else:
                    assert lmfile in root_anims, f"{lang_fn} anim '{lmfile}' missing"
                if "sound" in litem and litem["sound"]:
                    assert litem["sound"].lower().endswith(".ogg"), f"{lang_fn} sound not .ogg: {litem['sound']}"
                    if litem["sound"] not in wavs_checked:
                        _check_ogg(skin_dir / litem["sound"])
                if "text" in litem and litem["text"]:
                    assert "{$br}" not in litem["text"] and "I18N" not in litem["text"], f"Dirty text in {lang_fn}: {litem['text']}"

    return {
        "valid": True,
        "spine_version": ver,
        "base_scale": base_scale,
        "submodels": len(sub_specs),
        "sub_orders": [s["order"] for s in sub_specs],
        "start_mtn_cmds": start_mtn_cmds,
        "wavs_on_disk": len(list((skin_dir / "audio").glob("*.ogg"))) if (skin_dir / "audio").is_dir() else 0,
        "wavs_bound": len(wavs_checked),
        "bgm_count": len(bgm_files),
        "hit_areas": len(cfg.get("hit_areas", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify SoulTide Spine packages (prefer --only for incremental changes).")
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated <char>/<skin> or substring filter to verify ONLY modified skins (recommended)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(8, os.cpu_count() or 4)),
        help="Parallel verification worker threads",
    )
    args = parser.parse_args()

    skin_dirs = sorted(p.parent for p in SPINE_ROOT.glob("*/*/.config.json"))
    if args.only:
        wants = [x.strip().replace("\\", "/") for x in args.only.split(",") if x.strip()]
        skin_dirs = [
            sd for sd in skin_dirs
            if any(w in str(sd.relative_to(SPINE_ROOT)).replace("\\", "/") for w in wants)
        ]
        assert skin_dirs, f"--only filter matched 0 Spine skins: {args.only}"
    passed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    def _check_one(sd: Path):
        rel = str(sd.relative_to(SPINE_ROOT))
        try:
            res = verify_skin_dir(sd)
            res["skin"] = rel
            return True, res
        except Exception as exc:
            return False, {"skin": rel, "valid": False, "error": str(exc)}

    n_workers = max(1, min(args.workers, len(skin_dirs))) if skin_dirs else 1
    results = (
        list(ThreadPoolExecutor(max_workers=n_workers).map(_check_one, skin_dirs))
        if n_workers > 1
        else [_check_one(sd) for sd in skin_dirs]
    )
    for ok, item in results:
        if ok:
            passed.append(item)
        else:
            failed.append(item)

    db_stat = DB_PATH.stat()
    assert db_stat.st_size == 83886080, f"soultide.db size changed: {db_stat.st_size}"

    report = {
        "total_skins": len(skin_dirs),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "soultide_db": {"size_bytes": db_stat.st_size, "mtime": db_stat.st_mtime},
        "failed": failed,
        "passed": passed,
    }
    if not args.only:
        VERIFY_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "filter": args.only or "ALL",
                "total_skins": report["total_skins"],
                "passed_count": report["passed_count"],
                "failed_count": report["failed_count"],
                "soultide_db": report["soultide_db"],
                "failed": failed,
                "report_path": str(VERIFY_REPORT_PATH) if not args.only else "(skipped for --only incremental check)",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
