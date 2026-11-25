"""End-to-end structural and asset verification for Aurora_S4 Live2D & Spine EX packages."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from PIL import Image

LIVE2D_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d\欧若拉\童话心绘")
SPINE_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\欧若拉\童话心绘")
DB_PATH = Path(r"D:\A灵魂潮汐-本地化\服务器\soultide.db")
UNITY_EXE = Path(r"D:\Program Files\Unity\Hub\Editor\2021.3.34f1\Editor\Unity.exe")


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
        if s.lower().endswith(".png"):
            cur_png = model_dir / s
            assert cur_png.is_file(), f"Atlas page PNG missing: {cur_png}"
            i += 1
            sz_line = lines[i].strip()
            assert sz_line.startswith("size:"), f"Expected size line, got {sz_line}"
            cur_w, cur_h = [int(v.strip()) for v in sz_line[5:].split(",")]
            with Image.open(cur_png) as im:
                assert im.size == (cur_w, cur_h), f"{cur_png} size {im.size} != atlas {(cur_w, cur_h)}"
            # Skip format, filter, repeat lines
            while i + 1 < len(lines) and any(lines[i + 1].strip().startswith(p) for p in ("format:", "filter:", "repeat:", "size:")):
                i += 1
        elif not ln.startswith((" ", "\t")) and ":" not in s:
            rname = s
            regions.append(rname)
            xy = sz = None
            while i + 1 < len(lines) and lines[i + 1].startswith((" ", "\t")):
                i += 1
                kv = lines[i].strip()
                if kv.startswith("xy:"):
                    xy = [int(v.strip()) for v in kv[3:].split(",")]
                elif kv.startswith("size:"):
                    sz = [int(v.strip()) for v in kv[5:].split(",")]
            assert xy is not None and sz is not None, f"Incomplete region '{rname}' in {atlas_path}"
            x, y = xy
            w, h = sz
            assert 0 <= x and 0 <= y and x + w <= cur_w and y + h <= cur_h, (
                f"Atlas region '{rname}' out of bounds ({x},{y},{w},{h}) in {cur_png.name} ({cur_w}x{cur_h})"
            )
        i += 1
    assert regions, f"No atlas regions parsed in {atlas_path}"
    return regions


def _inspect_spine_skeleton(skel_path: Path) -> tuple[str, set[str]]:
    assert skel_path.is_file(), f"Missing skeleton: {skel_path}"
    raw = skel_path.read_bytes()
    if raw.lstrip().startswith(b"{"):
        data = json.loads(raw.decode("utf-8"))
        ver = data["skeleton"]["spine"]
        anims = set(data.get("animations", {}).keys())
        bones = {b["name"] for b in data.get("bones", [])}
        return ver, anims | bones
    assert b"3.8.79" in raw[:128], f"Unexpected binary Spine version header in {skel_path}"
    tokens = {m.decode("ascii", "ignore") for m in re.findall(rb"[A-Za-z0-9_./-]{2,}", raw)}
    return "3.8.79", tokens


def verify_live2d() -> dict:
    cfg_path = LIVE2D_DIR / ".model3.json"
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    fr = data["FileReferences"]
    moc_bytes = (LIVE2D_DIR / fr["Moc"]).read_bytes()
    assert moc_bytes.startswith(b"MOC3"), "Invalid .moc3 magic"
    assert b"ParamRingOn" in moc_bytes

    for phys_key in (fr["Physics"], fr["PhysicsV2"]["File"]):
        json.loads((LIVE2D_DIR / phys_key).read_text(encoding="utf-8"))

    for t in fr["Textures"]:
        tp = LIVE2D_DIR / t
        assert tp.is_file()
        with Image.open(tp) as im:
            assert im.width > 0 and im.height > 0

    for exp in fr["Expressions"]:
        ep = LIVE2D_DIR / exp["File"]
        ed = json.loads(ep.read_text(encoding="utf-8"))
        assert any(p["Id"] == "ParamRingOn" for p in ed["Parameters"])

    mots = fr["Motions"]
    mot_files_checked = 0
    wavs_checked = set()
    for grp, items in mots.items():
        assert items, f"Empty Live2D motion group: {grp}"
        for item in items:
            mf = LIVE2D_DIR / item["File"]
            json.loads(mf.read_text(encoding="utf-8"))
            mot_files_checked += 1
            if "Sound" in item:
                _check_ogg(LIVE2D_DIR / item["Sound"])
                wavs_checked.add(item["Sound"])
            if "Text" in item:
                assert "{$br}" not in item["Text"] and "I18N" not in item["Text"]
            for ch in item.get("Choices", []):
                nxt = ch["NextMtn"]
                tgrp = nxt.split(":", 1)[0]
                assert tgrp in mots, f"Choice NextMtn group missing: {nxt}"
            if grp in ("Tap", "语音菜单") or grp.startswith("Menu_Cat_"):
                assert item["File"] == "motions/menu_silent.motion3.json", (
                    f"Menu node {grp} must use silent motion, got {item['File']}"
                )
                assert item.get("FadeIn") == 0 and item.get("FadeOut") == 0, (
                    f"Menu node {grp} must have FadeIn/FadeOut == 0"
                )

    silent_mot = json.loads((LIVE2D_DIR / "motions/menu_silent.motion3.json").read_text(encoding="utf-8"))
    assert silent_mot["Meta"]["CurveCount"] == 0 and silent_mot["Curves"] == []

    for ha in data["HitAreas"]:
        assert ha["Id"].encode("ascii") in moc_bytes, f"HitArea ID missing from moc3: {ha['Id']}"
        assert ha["Motion"] in mots, f"HitArea Motion group missing: {ha['Motion']}"

    for lang_fn in ("model_en.model3.json", "model_ja.model3.json"):
        assert (LIVE2D_DIR / lang_fn).is_file(), f"Missing {lang_fn}"

    assert not list((LIVE2D_DIR / "audio").glob("*.wav")), "Leftover WAVs in Live2D audio/"
    disk_mots = list((LIVE2D_DIR / "motions").glob("*.motion3.json"))
    disk_wavs = list((LIVE2D_DIR / "audio").glob("*.ogg"))
    return {
        "valid": True,
        "moc_bytes": len(moc_bytes),
        "motions_on_disk": len(disk_mots),
        "motions_bound": mot_files_checked,
        "wavs_on_disk": len(disk_wavs),
        "wavs_bound": len(wavs_checked),
        "hit_areas": len(data["HitAreas"]),
        "expressions": len(fr["Expressions"]),
        "groups": len(mots),
    }


def verify_spine() -> dict:
    root_cfg = json.loads((SPINE_DIR / ".config.json").read_text(encoding="utf-8"))
    ver, root_tokens = _inspect_spine_skeleton(SPINE_DIR / root_cfg["skeleton"])
    for a in root_cfg["atlases"]:
        _parse_atlas_regions(SPINE_DIR / a["atlas"], SPINE_DIR)
        for tex in a["textures"]:
            assert (SPINE_DIR / tex).is_file()

    for ha in root_cfg["hit_areas"]:
        assert ha["id"] in root_tokens, f"Spine HitArea ID {ha['id']} missing from skeleton"
        assert ha["motion"] in root_cfg["motions"], f"HitArea motion {ha['motion']} missing"

    # Extract submodel commands from 'start' motion
    start_cmds = root_cfg["motions"]["start"][0]["command"].split(";")
    sub_specs = []
    seen_ids = {root_cfg["options"]["id"]}
    sub_models_by_id: dict[str, dict] = {}
    used_orders = set()

    for cmd in start_cmds:
        toks = cmd.strip().split()
        assert len(toks) == 3 and toks[0] == "add_submodel", f"Unexpected start cmd: {cmd}"
        sub_cfg_path = SPINE_DIR / toks[1]
        order = int(toks[2])
        assert -3 <= order <= 3 and order != 0 and order not in used_orders, f"Invalid/dup order: {order}"
        used_orders.add(order)
        sc = json.loads(sub_cfg_path.read_text(encoding="utf-8"))
        sid = sc["options"]["id"]
        assert sid not in seen_ids, f"Duplicate model ID: {sid}"
        seen_ids.add(sid)
        sdir = sub_cfg_path.parent
        sver, stokens = _inspect_spine_skeleton(sdir / sc["skeleton"])
        regions = []
        for a in sc["atlases"]:
            regions.extend(_parse_atlas_regions(sdir / a["atlas"], sdir))
        sub_models_by_id[sid] = {"cfg": sc, "tokens": stokens, "ver": sver, "regions": len(regions), "order": order}
        sub_specs.append({"id": sid, "order": order, "spine_ver": sver, "atlas_regions": len(regions)})

    assert len(sub_specs) <= 6, "Exceeded EX max 6 submodels"

    wavs_checked = set()
    start_mtn_cmds = 0
    for grp, items in root_cfg["motions"].items():
        for item in items:
            assert item["file"] in root_tokens, f"Animation '{item['file']}' missing in main skel"
            if "sound" in item:
                _check_ogg(SPINE_DIR / item["sound"])
                wavs_checked.add(item["sound"])
            if "text" in item:
                assert "{$br}" not in item["text"] and "I18N" not in item["text"]
            if "command" in item and item["command"].startswith("start_mtn "):
                _, tid, gm = item["command"].split()
                tgrp, tmtn = gm.split(":")
                assert tid in sub_models_by_id, f"Target submodel {tid} missing"
                sm = sub_models_by_id[tid]
                assert tgrp in sm["cfg"]["motions"], f"Target group {tgrp} missing in {tid}"
                assert any(m["name"] == tmtn for m in sm["cfg"]["motions"][tgrp]), f"Target mtn {tmtn} missing in {tid}"
                assert tmtn in sm["tokens"], f"Spine anim '{tmtn}' missing in {tid}"
                start_mtn_cmds += 1

    bgm_file = SPINE_DIR / "bgm/BGM_SkinMusic05_Aurora_S4.ogg"
    _check_ogg(bgm_file)
    for lang_fn in ("config_en.config.json", "config_ja.config.json"):
        assert (SPINE_DIR / lang_fn).is_file(), f"Missing {lang_fn}"
    assert not list((SPINE_DIR / "audio").glob("*.wav")), "Leftover WAVs in Spine audio/"
    assert not list((SPINE_DIR / "bgm").glob("*.wav")), "Leftover WAVs in Spine bgm/"

    return {
        "valid": True,
        "spine_version": ver,
        "submodels": sub_specs,
        "start_mtn_cmds_verified": start_mtn_cmds,
        "wavs_on_disk": len(list((SPINE_DIR / "audio").glob("*.ogg"))),
        "wavs_bound": len(wavs_checked),
        "bgm_verified": bgm_file.name,
        "hit_areas": len(root_cfg["hit_areas"]),
        "groups": len(root_cfg["motions"]),
    }


def main() -> None:
    l2d = verify_live2d()
    sp = verify_spine()
    db_stat = DB_PATH.stat()
    report = {
        "live2d": l2d,
        "spine": sp,
        "soultide_db": {"size_bytes": db_stat.st_size, "mtime": db_stat.st_mtime},
        "unity_2021_3_34f1_installed": UNITY_EXE.is_file(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
