"""Single-doll Live2D & Spine visual audit helper for Gemini 4 Hydrogen workers.

Strictly operates ONLY on the specified `--doll <角色名>` packages so workers
never touch or re-verify other dolls in the fleet.

Subcommands:
  --doll <name> --prepare
      Render Live2D previews + Spine composite/hit-area previews (with `.meta.json`)
      for all skins of `<name>` and print a concise structured diagnostic summary.

  --doll <name> --update-l2d <skin> (--hit-areas-json ... | --hit-areas-file ...)
      Validate and update `HitAreas` across `.model3.json` / `model_en` / `model_ja`
      for one Live2D skin of `<name>`, then re-render its preview JPG.

  --doll <name> --verify
      Run strict single-doll verification ONLY for `<name>`'s Live2D & Spine packages
      (Live2D `verify_package` + `inspect_package`, Spine `verify_skin_dir` + live
      `bg_static` containment check `out_of_bg_count == 0`, plus `soultide.db` size).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from audit_live2d_touch import init_cubism_core, inspect_package
from render_live2d_touch_previews import render_package_preview
from soultide_common import write_json
from verify_batch_live2d import verify_package as verify_l2d_package
from verify_batch_spine import verify_skin_dir as verify_spine_package

ROOT_OUT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型")
LIVE2D_ROOT = ROOT_OUT / "live2d"
SPINE_ROOT = ROOT_OUT / "spine"
DB_PATH = Path(r"D:\A灵魂潮汐-本地化\服务器\soultide.db")
EXPECTED_DB_SIZE = 83886080

AUDIT_DIR = TOOLS_DIR / "_doll_audit_previews"
AUDIT_L2D_DIR = AUDIT_DIR / "live2d"
AUDIT_SPINE_DIR = AUDIT_DIR / "spine"
COMPOSITE_RENDERER_PY = TOOLS_DIR / "render_spine_composite_previews.py"

L2D_LANG_FILES = (".model3.json", "model_en.model3.json", "model_ja.model3.json")

BG_PROP_BONE_RE = re.compile(
    r"(^root$|^bj|_bj|^beijing|beijing\d|^bg_|_bg_|cloud|harmonious|^ying|_ying|shadow|"
    r"(?:^|_)(?:bg|bj|background|back|yingzi|shadow|deng|light|shafa|sofa|zhuo|table|yi|chair|"
    r"chuang|bed|window|chuanghu|cloud|yun|shui|water|hua_|flower|tree|shu_|cat|mao|dog|gou|"
    r"bird|niao|book|shu\d|cup|bei|wine|jiu|lazhu|candle|guang|fx|effect|smoke|yanwu|wuzi|"
    r"room|floor|diban|wall|qiang|curtain|chuanglian|pillow|zhentou|qiu|ball|umbrella|san|"
    r"frame|kuang|mirror|jingzi|clock|zhong|music|yinfu|star|xing|moon|yue|qunzi|xiong_shadow|"
    r"weisha|fasheng|guazhui)(?:_|\d|$))",
    re.I,
)


def _extract_l2d_drawable_boxes(core, pkg_dir: Path) -> dict[str, dict[str, Any]]:
    cfg = json.loads((pkg_dir / ".model3.json").read_text(encoding="utf-8"))
    fr = cfg["FileReferences"]
    moc_bytes = (pkg_dir / fr["Moc"]).read_bytes()

    moc_buf = ctypes.create_string_buffer(len(moc_bytes) + 64)
    moc_addr = (ctypes.addressof(moc_buf) + 63) & ~63
    ctypes.memmove(moc_addr, moc_bytes, len(moc_bytes))
    moc = core.csmReviveMocInPlace(moc_addr, len(moc_bytes))
    msize = core.csmGetSizeofModel(moc)
    mod_buf = ctypes.create_string_buffer(msize + 64)
    mod_addr = (ctypes.addressof(mod_buf) + 63) & ~63
    model = core.csmInitializeModelInPlace(moc, mod_addr, msize)
    core.csmUpdateModel(model)

    dcnt = core.csmGetDrawableCount(model)
    ids_ptr = core.csmGetDrawableIds(model)
    vcnt_ptr = core.csmGetDrawableVertexCounts(model)
    vpos_ptr = core.csmGetDrawableVertexPositions(model)
    icnt_ptr = core.csmGetDrawableIndexCounts(model)
    op_ptr = core.csmGetDrawableOpacities(model)

    out: dict[str, dict[str, Any]] = {}
    for i in range(dcnt):
        did = ids_ptr[i].decode("utf-8", "ignore")
        vc = int(vcnt_ptr[i])
        ic = int(icnt_ptr[i])
        op = float(op_ptr[i])
        if vc > 0:
            pos = np.ctypeslib.as_array(vpos_ptr[i], shape=(vc, 2))
            x0, y0 = float(pos[:, 0].min()), float(pos[:, 1].min())
            x1, y1 = float(pos[:, 0].max()), float(pos[:, 1].max())
            out[did] = {
                "x0": round(x0, 3),
                "y0": round(y0, 3),
                "x1": round(x1, 3),
                "y1": round(y1, 3),
                "cx": round((x0 + x1) * 0.5, 3),
                "cy": round((y0 + y1) * 0.5, 3),
                "w": round(x1 - x0, 3),
                "h": round(y1 - y0, 3),
                "vc": vc,
                "ic": ic,
                "op": round(op, 3),
            }
        else:
            out[did] = {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0, "cx": 0.0, "cy": 0.0, "w": 0.0, "h": 0.0, "vc": 0, "ic": ic, "op": round(op, 3)}
    return out


def _get_doll_packages(doll: str) -> tuple[list[Path], list[Path]]:
    l2_dir = LIVE2D_ROOT / doll
    sp_dir = SPINE_ROOT / doll
    l2_pkgs = sorted(p.parent for p in l2_dir.glob("*/.model3.json")) if l2_dir.is_dir() else []
    sp_pkgs = sorted(p.parent for p in sp_dir.glob("*/.config.json")) if sp_dir.is_dir() else []
    if not l2_pkgs and not sp_pkgs:
        raise FileNotFoundError(f"No Live2D or Spine packages found for doll '{doll}'")
    return l2_pkgs, sp_pkgs


def _render_spine_doll(sp_pkgs: list[Path], doll: str) -> dict[str, Path]:
    if not sp_pkgs:
        return {}
    AUDIT_SPINE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(COMPOSITE_RENDERER_PY),
        "--with-hits",
        "--emit-meta",
        "--skip-fx",
        "--out-dir",
        str(AUDIT_SPINE_DIR),
    ]
    for p in sp_pkgs:
        cmd.extend(["--only", f"{doll}/{p.name}"])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Spine composite render failed for {doll}:\n{r.stderr}\n{r.stdout}")
    meta_map: dict[str, Path] = {}
    for p in sp_pkgs:
        skin = p.name
        matches = sorted(AUDIT_SPINE_DIR.glob(f"*_{doll}__{skin}.meta.json"))
        if not matches:
            raise FileNotFoundError(f"Missing .meta.json after rendering {doll}/{skin}")
        meta_map[f"{doll}/{skin}"] = matches[0]
    return meta_map


def cmd_prepare(doll: str) -> dict[str, Any]:
    l2_pkgs, sp_pkgs = _get_doll_packages(doll)
    AUDIT_L2D_DIR.mkdir(parents=True, exist_ok=True)
    core = init_cubism_core() if l2_pkgs else None

    l2_summaries: list[dict[str, Any]] = []
    for pkg in l2_pkgs:
        rel = f"{doll}/{pkg.name}"
        jpg_path = AUDIT_L2D_DIR / f"{doll}__{pkg.name}.jpg"
        render_package_preview(core, pkg, jpg_path)
        audit_info = inspect_package(core, pkg)
        dboxes = _extract_l2d_drawable_boxes(core, pkg)
        dref_boxes = {
            did: {k: v for k, v in info.items() if k in ("x0", "y0", "x1", "y1", "cx", "cy", "w", "h", "vc", "ic")}
            for did, info in dboxes.items()
            if did.startswith(("DREFTouchBox", "HitArea")) and info["vc"] > 0 and info["ic"] >= 3
        }
        # Visible anatomical candidates if DREFTouchBox needs verification/fallback
        anat_re = re.compile(r"(head|face|tou|lian|xiong|bra|ru\d*|hand|shou|arm|hip|tun|leg|tui|foot|jiao|body)", re.I)
        vis_cands = {
            did: {k: info[k] for k in ("cx", "cy", "w", "h")}
            for did, info in dboxes.items()
            if info["vc"] > 0 and info["ic"] >= 3 and info["op"] > 0.05 and anat_re.search(did)
            and not did.startswith(("DREFTouchBox", "HitArea"))
            and info["w"] <= 1.2 and info["h"] <= 1.2
        }
        l2_summaries.append({
            "rel": rel,
            "preview_jpg": str(jpg_path),
            "char_bbox": audit_info["char_bbox"],
            "flags": audit_info["flags"],
            "hit_areas": [
                {
                    "Name": h.get("Name"),
                    "Id": h.get("Id"),
                    "Motion": h.get("Motion"),
                    "cx": h.get("cx"),
                    "cy": h.get("cy"),
                    "w": h.get("w"),
                    "h": h.get("h"),
                    "nx": h.get("nx"),
                    "ny": h.get("ny"),
                }
                for h in audit_info["hit_areas"]
            ],
            "dref_touch_boxes": dref_boxes,
            "visible_anatomical_count": len(vis_cands),
        })

    meta_map = _render_spine_doll(sp_pkgs, doll)
    sp_summaries: list[dict[str, Any]] = []
    for pkg in sp_pkgs:
        rel = f"{doll}/{pkg.name}"
        meta_p = meta_map[rel]
        meta = json.loads(meta_p.read_text(encoding="utf-8-sig"))
        cfg = json.loads((pkg / ".config.json").read_text(encoding="utf-8"))
        bg_rect = meta.get("bg_rect")
        # Candidate bones strictly inside bg_rect (or all valid bones if 原皮)
        cands = []
        for bm in meta.get("bones", []):
            bid = bm["id"]
            if BG_PROP_BONE_RE.search(bid):
                continue
            if bg_rect is not None and not bm.get("in_bg", True):
                continue
            # Also ignore extreme outliers far outside character bbox unless attached to visible slot
            mb = meta.get("main_bbox")
            if mb and (bm["wx"] < mb["x0"] - 80 or bm["wx"] > mb["x1"] + 80 or bm["wy"] < mb["y0"] - 80 or bm["wy"] > mb["y1"] + 80):
                continue
            cands.append({
                "id": bid,
                "wx": bm["wx"],
                "wy": bm["wy"],
                "slots": bm.get("slots", []),
            })
        cands.sort(key=lambda b: (-b["wy"], b["wx"]))
        sp_summaries.append({
            "rel": rel,
            "is_orig": pkg.name == "原皮",
            "preview_jpg": meta["jpg"],
            "meta_json": str(meta_p),
            "submodels": meta.get("submodels", []),
            "bg_rect": bg_rect,
            "main_bbox": meta.get("main_bbox"),
            "out_of_bg_count": meta.get("out_of_bg_count", 0),
            "available_touch_motions": [
                g for g in ("头", "胸", "左手", "右手", "腿", "足")
                if g in cfg.get("motions", {})
            ],
            "hit_areas_raw": cfg.get("hit_areas", []),
            "hit_areas_live": meta.get("hit_areas", []),
            "in_bg_candidate_bones": cands,
        })

    summary = {
        "doll": doll,
        "live2d_count": len(l2_summaries),
        "spine_count": len(sp_summaries),
        "prepare_json": str(AUDIT_DIR / f"{doll}_prepare.json"),
        "live2d": l2_summaries,
        "spine": sp_summaries,
    }
    write_json(AUDIT_DIR / f"{doll}_prepare.json", summary)
    return summary


def cmd_update_l2d(doll: str, skin: str, raw_hit_areas: Any) -> dict[str, Any]:
    pkg_dir = LIVE2D_ROOT / doll / skin
    main_p = pkg_dir / ".model3.json"
    if not main_p.is_file():
        raise FileNotFoundError(f"Live2D package not found: {pkg_dir}")
    if not isinstance(raw_hit_areas, list) or len(raw_hit_areas) < 4:
        raise ValueError(f"HitAreas must contain at least 4 entries for {doll}/{skin}")

    core = init_cubism_core()
    dboxes = _extract_l2d_drawable_boxes(core, pkg_dir)
    main_cfg = json.loads(main_p.read_text(encoding="utf-8"))
    mots = (main_cfg.get("FileReferences") or {}).get("Motions") or {}

    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    bound_motions: set[str] = set()
    for i, ha in enumerate(raw_hit_areas):
        if not isinstance(ha, dict):
            raise ValueError(f"HitAreas[{i}] must be a dict")
        name = str(ha.get("Name", "")).strip()
        hid = str(ha.get("Id", "")).strip()
        hmot = str(ha.get("Motion", "")).strip()
        if not name or not hid or not hmot:
            raise ValueError(f"HitAreas[{i}] must have Name, Id, Motion")
        if hid not in dboxes:
            raise ValueError(f"HitAreas[{i}] Id '{hid}' is not a valid Drawable ID in .moc3")
        if dboxes[hid]["vc"] <= 0 or dboxes[hid]["ic"] < 3:
            raise ValueError(f"HitAreas[{i}] Id '{hid}' has empty geometry (vc={dboxes[hid]['vc']}, ic={dboxes[hid]['ic']})")
        if hid in seen_ids:
            raise ValueError(f"Duplicate Drawable Id '{hid}' in HitAreas")
        seen_ids.add(hid)
        if hmot not in mots or not mots[hmot]:
            raise ValueError(f"Motion group '{hmot}' missing or empty in {doll}/{skin}")
        bound_motions.add(hmot)
        normalized.append({"Name": name, "Id": hid, "Motion": hmot})

    for tg in ("Tap头", "Tap手", "Tap胸", "Tap臀部", "Tap躯干"):
        if tg in mots and tg not in bound_motions:
            raise ValueError(f"Existing Tap group '{tg}' would become unbound!")

    written: list[str] = []
    for fn in L2D_LANG_FILES:
        lp = pkg_dir / fn
        if not lp.is_file():
            raise FileNotFoundError(f"Missing Live2D language config: {lp}")
        d = json.loads(lp.read_text(encoding="utf-8"))
        d["HitAreas"] = normalized
        write_json(lp, d)
        written.append(str(lp))

    jpg_path = AUDIT_L2D_DIR / f"{doll}__{skin}.jpg"
    render_package_preview(core, pkg_dir, jpg_path)
    post_audit = inspect_package(core, pkg_dir)
    if post_audit["flags"]:
        raise RuntimeError(f"Post-update Live2D audit flagged issues for {doll}/{skin}: {post_audit['flags']}")
    return {
        "rel": f"{doll}/{skin}",
        "hit_areas_count": len(normalized),
        "written": written,
        "preview_jpg": str(jpg_path),
        "flags": post_audit["flags"],
    }


def cmd_verify(doll: str) -> dict[str, Any]:
    l2_pkgs, sp_pkgs = _get_doll_packages(doll)
    core = init_cubism_core() if l2_pkgs else None
    meta_map = _render_spine_doll(sp_pkgs, doll) if sp_pkgs else {}

    l2_results: list[dict[str, Any]] = []
    sp_results: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for pkg in l2_pkgs:
        rel = f"{doll}/{pkg.name}"
        try:
            vres = verify_l2d_package(pkg)
            ares = inspect_package(core, pkg)
            if ares["flags"]:
                raise AssertionError(f"audit_live2d_touch flags: {ares['flags']}")
            l2_results.append({
                "rel": rel,
                "valid": True,
                "hit_areas": vres["hit_areas"],
                "wavs_bound": vres["wavs_bound"],
            })
        except Exception as exc:
            item = {"type": "live2d", "rel": rel, "valid": False, "error": str(exc)}
            l2_results.append(item)
            failed.append(item)

    for pkg in sp_pkgs:
        rel = f"{doll}/{pkg.name}"
        try:
            vres = verify_spine_package(pkg)
            meta = json.loads(meta_map[rel].read_text(encoding="utf-8-sig"))
            out_cnt = int(meta.get("out_of_bg_count", 0))
            if meta.get("has_bg_box") and out_cnt > 0:
                bad = [
                    f"{h['name']}({h['id']}) ov=(L={h['ov_l']},R={h['ov_r']},B={h['ov_b']},T={h['ov_t']})"
                    for h in meta.get("hit_areas", [])
                    if h.get("out_of_bg")
                ]
                raise AssertionError(f"Spine hit_areas exceed bg_static bounds: {bad}")
            sp_results.append({
                "rel": rel,
                "valid": True,
                "hit_areas": vres["hit_areas"],
                "submodels": vres["submodels"],
                "out_of_bg_count": out_cnt,
            })
        except Exception as exc:
            item = {"type": "spine", "rel": rel, "valid": False, "error": str(exc)}
            sp_results.append(item)
            failed.append(item)

    db_size = DB_PATH.stat().st_size
    if db_size != EXPECTED_DB_SIZE:
        failed.append({"type": "db", "rel": "soultide.db", "valid": False, "error": f"size={db_size}"})

    return {
        "doll": doll,
        "passed": len(failed) == 0,
        "live2d_total": len(l2_pkgs),
        "spine_total": len(sp_pkgs),
        "failed_count": len(failed),
        "failed": failed,
        "live2d": l2_results,
        "spine": sp_results,
        "soultide_db_size": db_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-doll Live2D & Spine visual audit helper.")
    parser.add_argument("--doll", required=True, help="Target doll character name, e.g. '菲洛多希'")
    parser.add_argument("--prepare", action="store_true", help="Render previews and print diagnostic summary")
    parser.add_argument("--verify", action="store_true", help="Run single-doll verification ONLY")
    parser.add_argument("--update-l2d", type=str, default="", help="Update Live2D HitAreas for specified skin")
    parser.add_argument("--hit-areas-json", type=str, default="", help="HitAreas JSON string")
    parser.add_argument("--hit-areas-file", type=str, default="", help="Path to HitAreas JSON file")
    args = parser.parse_args()

    if args.prepare:
        res = cmd_prepare(args.doll)
        compact = {
            "doll": res["doll"],
            "live2d_count": res["live2d_count"],
            "spine_count": res["spine_count"],
            "prepare_json": res["prepare_json"],
            "live2d": [
                {
                    "rel": s["rel"],
                    "preview_jpg": s["preview_jpg"],
                    "flags": s["flags"],
                    "hit_areas": [(h["Name"], h["Id"], h["Motion"]) for h in s["hit_areas"]],
                    "dref_keys": sorted(s["dref_touch_boxes"].keys()),
                }
                for s in res["live2d"]
            ],
            "spine": [
                {
                    "rel": s["rel"],
                    "preview_jpg": s["preview_jpg"],
                    "meta_json": s["meta_json"],
                    "submodels": s["submodels"],
                    "bg_rect": s["bg_rect"],
                    "out_of_bg_count": s["out_of_bg_count"],
                    "hit_areas": [
                        {
                            "name": h["name"],
                            "id": h["id"],
                            "out": h["out_of_bg"],
                            "ov": [h["ov_l"], h["ov_r"], h["ov_b"], h["ov_t"]],
                        }
                        for h in s["hit_areas_live"]
                    ],
                    "slotted_in_bg_bones": [
                        b for b in s["in_bg_candidate_bones"] if b.get("slots")
                    ][:40],
                }
                for s in res["spine"]
            ],
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        return 0
    if args.update_l2d:
        if args.hit_areas_json:
            raw = json.loads(args.hit_areas_json)
        elif args.hit_areas_file:
            raw = json.loads(Path(args.hit_areas_file).read_text(encoding="utf-8-sig"))
        else:
            raw = json.loads(sys.stdin.read())
        if isinstance(raw, dict) and "HitAreas" in raw:
            raw = raw["HitAreas"]
        res = cmd_update_l2d(args.doll, args.update_l2d, raw)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.verify:
        res = cmd_verify(args.doll)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["passed"] else 1

    parser.error("Must specify one of --prepare, --update-l2d <skin>, or --verify")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
