"""Full-fleet verification script for all SoulTide Live2DViewerEX packages."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image

LIVE2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
DB_PATH = Path(r"D:\A灵魂潮汐-本地化\服务器\soultide.db")
CORE_DLL = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Plugins\x86_64\Live2DCubismCore.dll"
)
EXPECTED_DB_SIZE = 83886080
EXPECTED_VK_CODES = {49, 77, 86, 82}
BANNED_HIT_IDS = ("L_Foot", "R_Foot")
_CUBISM_CORE = None


def _get_cubism_core():
    global _CUBISM_CORE
    if _CUBISM_CORE is not None:
        return _CUBISM_CORE
    if not CORE_DLL.is_file():
        return None
    core = ctypes.CDLL(str(CORE_DLL))
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
    core.csmGetDrawableTextureIndices.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableTextureIndices.restype = ctypes.POINTER(ctypes.c_int32)
    core.csmGetDrawableVertexCounts.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableVertexCounts.restype = ctypes.POINTER(ctypes.c_int32)
    core.csmGetDrawableVertexUvs.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableVertexUvs.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    core.csmGetDrawableIndexCounts.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableIndexCounts.restype = ctypes.POINTER(ctypes.c_int32)
    core.csmGetDrawableIndices.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableIndices.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_uint16))
    core.csmGetDrawableOpacities.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableOpacities.restype = ctypes.POINTER(ctypes.c_float)
    core.csmGetParameterCount.argtypes = [ctypes.c_void_p]
    core.csmGetParameterCount.restype = ctypes.c_int32
    core.csmGetParameterIds.argtypes = [ctypes.c_void_p]
    core.csmGetParameterIds.restype = ctypes.POINTER(ctypes.c_char_p)
    _CUBISM_CORE = core
    return core


def _check_ogg(p: Path) -> None:
    if not p.is_file():
        raise AssertionError(f"Missing OGG audio: {p}")
    if p.suffix.lower() != ".ogg":
        raise AssertionError(f"Expected .ogg extension, got: {p}")
    with p.open("rb") as f:
        hdr = f.read(4)
    if hdr != b"OggS":
        raise AssertionError(f"Invalid OggS header in {p}: {hdr!r}")


def verify_package(pkg_dir: Path) -> dict[str, Any]:
    """Validate a single Live2DViewerEX package directory against all standards."""
    cfg_path = pkg_dir / ".model3.json"
    if not cfg_path.is_file():
        raise AssertionError(f"Missing .model3.json in {pkg_dir}")

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    fr = data["FileReferences"]

    # 1. MOC3 header
    moc_path = pkg_dir / fr["Moc"]
    if not moc_path.is_file():
        raise AssertionError(f"Missing MOC3: {moc_path}")
    moc_bytes = moc_path.read_bytes()
    if not moc_bytes.startswith(b"MOC3"):
        raise AssertionError(f"Invalid MOC3 magic in {moc_path}")

    # 2. Textures
    textures = fr.get("Textures") or []
    if not textures:
        raise AssertionError("FileReferences.Textures is empty")
    for t in textures:
        tp = pkg_dir / t
        if not tp.is_file():
            raise AssertionError(f"Missing texture: {tp}")
        with Image.open(tp) as im:
            if im.width <= 0 or im.height <= 0:
                raise AssertionError(f"Invalid texture dimensions: {tp}")

    # 3. Physics (when referenced) & CubismCore MOC3 <-> Texture <-> Physics integrity
    has_physics = False
    phys_dict = None
    phys_v1 = fr.get("Physics")
    phys_v2 = (fr.get("PhysicsV2") or {}).get("File")
    if phys_v1 != phys_v2:
        raise AssertionError(f"Physics ({phys_v1}) != PhysicsV2.File ({phys_v2})")
    for phys_key in (phys_v1, phys_v2):
        if phys_key:
            has_physics = True
            pp = pkg_dir / phys_key
            if not pp.is_file():
                raise AssertionError(f"Missing physics file: {pp}")
            phys_dict = json.loads(pp.read_text(encoding="utf-8"))

    uv_hit_ratio = None
    valid_drawable_ids: set[str] | None = None
    core = _get_cubism_core()
    if core is not None:
        moc_buf = ctypes.create_string_buffer(len(moc_bytes) + 64)
        moc_addr = (ctypes.addressof(moc_buf) + 63) & ~63
        ctypes.memmove(moc_addr, moc_bytes, len(moc_bytes))
        moc = core.csmReviveMocInPlace(moc_addr, len(moc_bytes))
        if not moc:
            raise AssertionError(f"CubismCore failed to revive MOC3: {moc_path}")
        msize = core.csmGetSizeofModel(moc)
        mod_buf = ctypes.create_string_buffer(msize + 64)
        mod_addr = (ctypes.addressof(mod_buf) + 63) & ~63
        model = core.csmInitializeModelInPlace(moc, mod_addr, msize)

        dcnt = core.csmGetDrawableCount(model)
        dids_ptr = core.csmGetDrawableIds(model)
        valid_drawable_ids = {dids_ptr[i].decode("utf-8", "ignore") for i in range(dcnt)}
        tidx_ptr = core.csmGetDrawableTextureIndices(model)
        vcnt_ptr = core.csmGetDrawableVertexCounts(model)
        uvs_ptr = core.csmGetDrawableVertexUvs(model)
        icnt_ptr = core.csmGetDrawableIndexCounts(model)
        idxs_ptr = core.csmGetDrawableIndices(model)
        op_ptr = core.csmGetDrawableOpacities(model)
        tex_alphas = [np.array(Image.open(pkg_dir / t).convert("RGBA"))[..., 3] for t in textures]

        tt = ht = 0
        for i in range(dcnt):
            ti = tidx_ptr[i]
            if ti < 0 or ti >= len(tex_alphas):
                raise AssertionError(f"Drawable {i} TextureIndex={ti} out of range (textures={len(tex_alphas)})")
            vc = vcnt_ptr[i]
            ic = icnt_ptr[i]
            if vc <= 0 or ic < 3 or op_ptr[i] <= 0.01:
                continue
            alp = tex_alphas[ti]
            h, w = alp.shape
            uv = np.ctypeslib.as_array(uvs_ptr[i], shape=(vc, 2))
            idx = np.ctypeslib.as_array(idxs_ptr[i], shape=(ic // 3, 3))
            c_uv = uv[idx].mean(axis=1)
            xs = np.clip((c_uv[:, 0] * w).astype(int), 0, w - 1)
            ys = np.clip(((1.0 - c_uv[:, 1]) * h).astype(int), 0, h - 1)
            vals = alp[ys, xs]
            tt += len(vals)
            ht += int((vals > 8).sum())
        uv_hit_ratio = ht / max(1, tt)
        if uv_hit_ratio < 0.50:
            raise AssertionError(f"Low MOC3 UV-to-Texture alpha hit ratio ({uv_hit_ratio:.3f} < 0.50); possible MOC/texture mismatch")

        if phys_dict is not None:
            pcnt = core.csmGetParameterCount(model)
            pids_ptr = core.csmGetParameterIds(model)
            valid_pids = {pids_ptr[i].decode("utf-8", "ignore") for i in range(pcnt)}
            for ps in phys_dict.get("PhysicsSettings") or []:
                for inp in ps.get("Input") or []:
                    pid = (inp.get("Source") or {}).get("Id", "")
                    if pid and pid not in valid_pids:
                        raise AssertionError(f"Physics Input Source Id '{pid}' missing in MOC3")
                for outp in ps.get("Output") or []:
                    pid = (outp.get("Destination") or {}).get("Id", "")
                    if pid and pid not in valid_pids:
                        raise AssertionError(f"Physics Output Destination Id '{pid}' missing in MOC3")

    # 4. Expressions
    exps = fr.get("Expressions") or []
    has_ring_param = b"ParamRingOn" in moc_bytes
    if has_ring_param and not exps:
        raise AssertionError("MOC3 contains ParamRingOn but FileReferences.Expressions is empty")
    for exp in exps:
        ep = pkg_dir / exp["File"]
        if not ep.is_file():
            raise AssertionError(f"Missing expression file: {ep}")
        ed = json.loads(ep.read_text(encoding="utf-8"))
        if not ed.get("Parameters"):
            raise AssertionError(f"Expression has no Parameters: {ep}")

    # 5. Controllers & Motions
    mots = fr.get("Motions") or {}
    ctrls = data.get("Controllers") or {}
    if ctrls.get("EyeBlink", {}).get("Enabled") is not False:
        raise AssertionError("Controllers.EyeBlink.Enabled must be false")
    if ctrls.get("AutoBreath", {}).get("Enabled") is not False:
        raise AssertionError("Controllers.AutoBreath.Enabled must be false")
    if ctrls.get("ExtraMotion", {}).get("Enabled") is not False:
        raise AssertionError("Controllers.ExtraMotion.Enabled must be false")
    mt = ctrls.get("MouseTracking") or {}
    if mt.get("Enabled") is not True or mt.get("SmoothTime") != 0.15:
        raise AssertionError(f"Invalid MouseTracking controller: {mt}")
    if (ctrls.get("LipSync") or {}).get("Gain") != 5.0:
        raise AssertionError(f"Invalid LipSync controller: {ctrls.get('LipSync')}")

    def _assert_mtn_ref(mots_dict: dict[str, Any], ref: str, label: str) -> None:
        if ":" in ref:
            tgrp, tname = ref.split(":", 1)
            if tgrp not in mots_dict:
                raise AssertionError(f"{label} target group missing: {ref}")
            if not any(m.get("Name") == tname for m in mots_dict[tgrp]):
                raise AssertionError(f"{label} target motion name '{tname}' missing in group '{tgrp}'")
        elif ref not in mots_dict:
            raise AssertionError(f"{label} target group missing: {ref}")

    kt = ctrls.get("KeyTrigger") or {}
    if kt.get("Enabled") is not True:
        raise AssertionError("Controllers.KeyTrigger.Enabled must be true")
    seen_kt_inputs: set[int] = set()
    kt_by_input: dict[int, dict[str, Any]] = {}
    for item in kt.get("Items") or []:
        inp = item.get("Input")
        if inp not in EXPECTED_VK_CODES:
            raise AssertionError(f"Non-standard KeyTrigger Input code: {item}")
        if inp in seen_kt_inputs:
            raise AssertionError(f"Duplicate KeyTrigger Input code: {inp}")
        seen_kt_inputs.add(inp)
        kt_by_input[inp] = item
        dm = item.get("DownMtn")
        um = item.get("UpMtn")
        if not dm and not um:
            raise AssertionError(f"KeyTrigger item has neither DownMtn nor UpMtn: {item}")
        if dm:
            _assert_mtn_ref(mots, dm, f"KeyTrigger({inp}).DownMtn")
        if um:
            _assert_mtn_ref(mots, um, f"KeyTrigger({inp}).UpMtn")
    if has_ring_param:
        r_item = kt_by_input.get(82)
        if not r_item or r_item.get("DownMtn") != "誓约戒指切换":
            raise AssertionError(f"ParamRingOn model must bind VK_R(82) to '誓约戒指切换', got: {r_item}")
        ring_mots = mots.get("誓约戒指切换") or []
        if not ring_mots or ring_mots[0].get("PostCommand") != "next_exp" or int(ring_mots[0].get("MotionDuration", 0)) < 50:
            raise AssertionError(f"Invalid '誓约戒指切换' motion entry: {ring_mots}")

    # 6. Motions, Idle (1 default or VarFloats-gated multi-idle), silent menu, Choices, WAVs, I18N clean
    idle = mots.get("Idle") or []
    if not idle:
        raise AssertionError("Idle group must contain at least 1 motion, found 0")
    if len(idle) > 1:
        has_default_zero = False
        for it in idle:
            vfs = it.get("VarFloats") or []
            if not any(
                vf.get("Name") == "idle_mode"
                and vf.get("Type") == 1
                and isinstance(vf.get("Code"), str)
                and vf["Code"].startswith("equal ")
                for vf in vfs
            ):
                raise AssertionError(f"Multi-Idle entry missing idle_mode VarFloats condition: {it}")
            if any(vf.get("Name") == "idle_mode" and vf.get("Code") == "equal 0" for vf in vfs):
                has_default_zero = True
        if not has_default_zero:
            raise AssertionError("Multi-Idle group missing default 'equal 0' entry")

    silent_path = pkg_dir / "motions/menu_silent.motion3.json"
    if not silent_path.is_file():
        raise AssertionError("Missing motions/menu_silent.motion3.json")
    silent_mot = json.loads(silent_path.read_text(encoding="utf-8"))
    if silent_mot.get("Meta", {}).get("CurveCount") != 0 or silent_mot.get("Curves") != []:
        raise AssertionError("menu_silent.motion3.json must have 0 curves")

    mot_files_bound = 0
    checked_mots: set[str] = set()
    wavs_checked: set[str] = set()
    for grp, items in mots.items():
        if not items:
            raise AssertionError(f"Empty motion group: {grp}")
        for item in items:
            rel_mf = item["File"]
            if rel_mf not in checked_mots:
                mf = pkg_dir / rel_mf
                if not mf.is_file():
                    raise AssertionError(f"Missing motion file: {mf}")
                json.loads(mf.read_text(encoding="utf-8"))
                checked_mots.add(rel_mf)
            mot_files_bound += 1

            if "Sound" in item:
                if item["Sound"] not in wavs_checked:
                    _check_ogg(pkg_dir / item["Sound"])
                    wavs_checked.add(item["Sound"])

            if "Text" in item:
                txt = item["Text"]
                if "{$br}" in txt or "I18N" in txt:
                    raise AssertionError(f"Unresolved tag in Text: {txt[:60]}")

            if item.get("NextMtn"):
                _assert_mtn_ref(mots, item["NextMtn"], f"{grp}.NextMtn")

            for ch in item.get("Choices") or []:
                _assert_mtn_ref(mots, ch["NextMtn"], f"{grp}.Choice.NextMtn")

            if grp in ("Tap", "语音菜单", "誓约戒指切换") or grp.startswith("Menu_Cat_"):
                if item.get("File") != "motions/menu_silent.motion3.json":
                    raise AssertionError(f"Menu node {grp} must use menu_silent.motion3.json, got {item.get('File')}")
                if item.get("FadeIn") != 0 or item.get("FadeOut") != 0:
                    raise AssertionError(f"Menu node {grp} must have FadeIn=0 and FadeOut=0")

    # Verify all OGGs on disk in audio/ have valid OggS headers and 0 WAVs remain
    leftover_wavs = sorted((pkg_dir / "audio").glob("*.wav")) if (pkg_dir / "audio").is_dir() else []
    if leftover_wavs:
        raise AssertionError(f"Found leftover .wav files in {pkg_dir / 'audio'}: {leftover_wavs[:3]}")
    disk_wavs = sorted((pkg_dir / "audio").glob("*.ogg")) if (pkg_dir / "audio").is_dir() else []
    for w in disk_wavs:
        if f"audio/{w.name}" not in wavs_checked:
            _check_ogg(w)

    # 6B. Verify Scheme A sibling multi-language configs (model_en.model3.json & model_ja.model3.json)
    for lang_fn in ("model_en.model3.json", "model_ja.model3.json"):
        lp = pkg_dir / lang_fn
        if not lp.is_file():
            raise AssertionError(f"Missing Scheme A multi-language config: {lp}")
        ld = json.loads(lp.read_text(encoding="utf-8"))
        if (ld.get("Controllers") or {}).get("KeyTrigger") != kt:
            raise AssertionError(f"{lang_fn} Controllers.KeyTrigger out of sync with .model3.json")
        lmots = (ld.get("FileReferences") or {}).get("Motions") or {}
        if set(lmots.keys()) != set(mots.keys()):
            raise AssertionError(f"{lang_fn} motion groups mismatch vs .model3.json")
        for lgrp, litems in lmots.items():
            for litem in litems:
                if "Sound" in litem:
                    if not litem["Sound"].lower().endswith(".ogg"):
                        raise AssertionError(f"{lang_fn} Sound not .ogg: {litem['Sound']}")
                    if litem["Sound"] not in wavs_checked:
                        _check_ogg(pkg_dir / litem["Sound"])
                if "Text" in litem:
                    ltxt = litem["Text"]
                    if "{$br}" in ltxt or "I18N" in ltxt:
                        raise AssertionError(f"Unresolved tag in {lang_fn} Text: {ltxt[:60]}")
                if litem.get("NextMtn"):
                    _assert_mtn_ref(lmots, litem["NextMtn"], f"{lang_fn}:{lgrp}.NextMtn")
                for ch in litem.get("Choices") or []:
                    _assert_mtn_ref(lmots, ch["NextMtn"], f"{lang_fn}:{lgrp}.Choice.NextMtn")

    # 7. HitAreas verified against exact CubismCore Drawable IDs and motion groups
    hit_areas = data.get("HitAreas") or []
    if len(hit_areas) < 4:
        raise AssertionError(f"Expected at least 4 HitAreas entries, found {len(hit_areas)}")
    seen_ha_ids: set[str] = set()
    bound_tap_motions: set[str] = set()
    for ha in hit_areas:
        hid = ha.get("Id", "")
        if any(b in hid for b in BANNED_HIT_IDS):
            raise AssertionError(f"Banned misleading HitArea ID found: {hid}")
        if valid_drawable_ids is not None:
            if hid not in valid_drawable_ids:
                raise AssertionError(f"HitArea ID '{hid}' is not a valid Drawable (ArtMesh) ID in {moc_path.name}")
        elif hid.encode("ascii") not in moc_bytes:
            raise AssertionError(f"HitArea ID '{hid}' not found in {moc_path.name}")
        if hid in seen_ha_ids:
            raise AssertionError(f"Duplicate HitArea Drawable ID '{hid}' in {pkg_dir}")
        seen_ha_ids.add(hid)
        hmot = ha.get("Motion", "")
        if hmot not in mots:
            raise AssertionError(f"HitArea Motion group '{hmot}' missing from Motions")
        bound_tap_motions.add(hmot)

    for tg in ("Tap头", "Tap手", "Tap胸", "Tap臀部", "Tap躯干"):
        if tg in mots and tg not in bound_tap_motions:
            raise AssertionError(f"Motion group '{tg}' exists in Motions but has no HitAreas trigger bound to it")

    for lang_fn in ("model_en.model3.json", "model_ja.model3.json"):
        ld = json.loads((pkg_dir / lang_fn).read_text(encoding="utf-8"))
        if ld.get("HitAreas") != hit_areas:
            raise AssertionError(f"{lang_fn} HitAreas out of sync with .model3.json")

    # 8. Strict non-base skin body touch voice isolation check
    skin_name = pkg_dir.name
    is_base = skin_name == "原皮" or skin_name.startswith("原皮_")
    if not is_base:
        for tg in ("Tap头", "Tap手", "Tap胸", "Tap臀部", "Tap躯干"):
            for item in mots.get(tg, []):
                snd = (item.get("Sound") or "").lower()
                if "_touch_" in snd:
                    raise AssertionError(f"Base touch voice leaked into non-base {tg}: {snd}")

    disk_mots = sorted((pkg_dir / "motions").glob("*.motion3.json"))
    return {
        "package": f"{pkg_dir.parent.name}/{pkg_dir.name}",
        "valid": True,
        "moc_bytes": len(moc_bytes),
        "has_physics": has_physics,
        "has_ring": has_ring_param,
        "expressions": len(exps),
        "hit_areas": len(hit_areas),
        "motions_on_disk": len(disk_mots),
        "motions_bound": mot_files_bound,
        "wavs_on_disk": len(disk_wavs),
        "wavs_bound": len(wavs_checked),
        "groups": len(mots),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify SoulTide Live2DViewerEX packages (prefer --only for incremental changes).")
    parser.add_argument("--char", help="Only verify packages under matching character name.")
    parser.add_argument("--only", help="Comma-separated <char>/<skin> or substring filter to verify ONLY modified packages.")
    parser.add_argument("--report-out", help="Optional path to write full JSON verification report.")
    args = parser.parse_args()

    pkg_dirs = sorted(p.parent for p in LIVE2D_ROOT.glob("*/*/.model3.json"))
    if args.char:
        pkg_dirs = [p for p in pkg_dirs if args.char in p.parent.name]
    if args.only:
        wants = [x.strip().replace("\\", "/") for x in args.only.split(",") if x.strip()]
        pkg_dirs = [
            p for p in pkg_dirs
            if any(w in f"{p.parent.name}/{p.name}" for w in wants)
        ]

    passed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    notes: list[str] = []

    for pkg_dir in pkg_dirs:
        rel = f"{pkg_dir.parent.name}/{pkg_dir.name}"
        try:
            res = verify_package(pkg_dir)
            passed.append(res)
            if not res["has_physics"]:
                notes.append(f"{rel}: no physics3.json in source AB (Physics omitted cleanly)")
        except Exception as exc:
            failed.append({"package": rel, "error": str(exc)})

    db_stat = DB_PATH.stat()
    db_ok = db_stat.st_size == EXPECTED_DB_SIZE

    total_mots_disk = sum(r["motions_on_disk"] for r in passed)
    total_wavs_disk = sum(r["wavs_on_disk"] for r in passed)
    total_wavs_bound = sum(r["wavs_bound"] for r in passed)

    report = {
        "valid": len(failed) == 0 and db_ok and len(passed) > 0,
        "packages_scanned": len(pkg_dirs),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "failed": failed,
        "notes": notes,
        "totals": {
            "motions_on_disk": total_mots_disk,
            "wavs_on_disk": total_wavs_disk,
            "wavs_bound": total_wavs_bound,
        },
        "soultide_db": {
            "size_bytes": db_stat.st_size,
            "mtime": db_stat.st_mtime,
            "size_unchanged": db_ok,
        },
    }

    if args.report_out:
        Path(args.report_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
