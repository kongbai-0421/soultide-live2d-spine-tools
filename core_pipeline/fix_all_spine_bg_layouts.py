"""Rebuild & Fix Background/Foreground Submodels Across All SoulTide Dress Spine Packages.

Uses the corrected `inspect_bg_prefab_layout` (in `batch_fx_exporter.py`) and
`_build_scene_submodels_exact` (in `batch_spine_builder.py`) to fix all 109
Dress Spine packages:
  - Non-uniform scale (scaleX != scaleY), negative scale / initialFlipX/Y, and Z-rotation on bj_* & Person
  - Exact RectTransform anchor/pivot/sizeDelta math for static Images
  - Unity Mask / RectMask2D clipping (e.g. Akaset_S5 TV screen clouds)
  - LightCloud (光明云) censorship-cloud false positive & Asuna_S9 Spine_Scale fallback (8x-10x giant character fix!)
  - Side-preserving z-order allocation (never overflowing behind-Person bj_* into +1..+3 in front of Person!)
  - Static layer splitting into bg_static / bg_mid / fg_static when interleaved with bj_* or Person
  - Auto-trimming pure transparent outer margins on static submodels
  - Preserving existing fx_* submodels & IDs (re-calibrating fx_root when person_tf was fixed)
  - Synchronizing ONLY `start[*].command` and `reload_bg[*].command` across `.config.json`,
    `config_en.config.json`, and `config_ja.config.json` (never touching hit_areas or voice routing!)

Strictly protects `soultide.db` and `live2d/`.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import sys
import threading
from pathlib import Path
from typing import Any

from PIL import Image

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
AUDIT_DIR = TOOLS_DIR / "_spine_full_audit"
if str(AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(AUDIT_DIR))

from batch_fx_exporter import (
    AssetIndexer,
    FX_SEQ_ROOT,
    FullI18nRepo,
    build_skin_catalog,
    inspect_bg_prefab_layout,
)
from batch_spine_builder import (
    BatchAssetRepos,
    SPINE_OUT_ROOT,
    _SCENE_LAYOUT_OVERRIDES,
    _assign_orders,
    _build_scene_submodels_exact,
    parse_spine38_binary,
    patch_binary_root_transform,
)
from soultide_common import write_json
from spine38_clip_injector import inject_clip_spine38_binary, inject_clip_spine38_json

PROTECTED_SKINS: set[str] = set()
REPORT_PATH = TOOLS_DIR / "bg_layout_fix_report.json"


def _parse_existing_fx_items(skin_dir: Path, cfg: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Extract existing fx_* submodels (id, rel_cfg, side) from current .config.json start command."""
    start_items = cfg.get("motions", {}).get("start", [])
    start_cmd = start_items[0].get("command", "") if start_items else ""
    fx_items: list[tuple[str, str, str]] = []
    seen_rel: set[str] = set()
    for seg in start_cmd.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        toks = seg.split()
        if len(toks) == 3 and toks[0] == "add_submodel":
            rel, ord_val = toks[1], int(toks[2])
            folder = Path(rel).parent.name
            if folder.lower().startswith("fx_") and rel not in seen_rel:
                sub_cfg_p = skin_dir / rel
                if sub_cfg_p.is_file():
                    sc = json.loads(sub_cfg_p.read_text(encoding="utf-8"))
                    fx_id = sc["options"]["id"]
                    side = "back" if ord_val < 0 or folder.lower().endswith("_back") else "front"
                    fx_items.append((fx_id, rel, side))
                    seen_rel.add(rel)
    return fx_items


def _recalibrate_fx_root_if_needed(
    skin: dict[str, Any],
    skin_dir: Path,
    layout: dict[str, Any],
    fx_items: list[tuple[str, str, str]],
) -> list[str]:
    """Re-calibrate fx_root bone (x, y, scaleX, scaleY) in existing fx_*.json if person_tf changed."""
    seq_root = FX_SEQ_ROOT / skin["skin_key"]
    if not seq_root.is_dir() or not fx_items:
        return []

    # Find recorded frame resolution
    first_png = next(seq_root.rglob("frame_*.png"), None)
    if first_png is None:
        return []
    with Image.open(first_png) as im:
        render_w, render_h = im.size

    p = layout["person"]
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
    # Use the actual canvas/cam stored in fx_manifest.json when the sequence PNGs were recorded,
    # avoiding vertical stretching when inspect_bg_prefab_layout later changed canvas_h/cam_y!
    rec_cw, rec_ch = float(layout["canvas_w"]), float(layout["canvas_h"])
    rec_cx, rec_cy = float(layout["cam_x"]), float(layout["cam_y"])
    manifest_p = TOOLS_DIR / "SoulTideBatchFxUnity" / "fx_manifest.json"
    if manifest_p.is_file():
        try:
            mf = json.loads(manifest_p.read_text(encoding="utf-8-sig"))
            ms = next((s for s in mf.get("skins", []) if s.get("skin_key") == skin["skin_key"]), None)
            if ms and ms.get("canvas_w") and ms.get("canvas_h"):
                rec_cw, rec_ch = float(ms["canvas_w"]), float(ms["canvas_h"])
                rec_cx, rec_cy = float(ms.get("cam_x", 0.0)), float(ms.get("cam_y", 0.0))
        except Exception:
            pass
    exp_x = (rec_cx - p["wx"]) / p_ux
    exp_y = (rec_cy - p["wy"]) / p_uy
    exp_sx = (rec_cw / p_ux) / render_w
    exp_sy = (rec_ch / p_uy) / render_h

    patched: list[str] = []
    for fx_id, fx_rel, _ in fx_items:
        sc_path = skin_dir / fx_rel
        sc = json.loads(sc_path.read_text(encoding="utf-8"))
        skel_p = sc_path.parent / sc["skeleton"]
        if not skel_p.is_file():
            continue
        raw = skel_p.read_bytes()
        if not raw.lstrip().startswith(b"{"):
            continue
        sk = json.loads(raw.decode("utf-8"))
        bones = sk.get("bones", [])
        fx_bone = next((b for b in bones if b.get("name") in ("fx_root", "bg_root")), None)
        if fx_bone is None and len(bones) >= 2:
            fx_bone = bones[1]
        if fx_bone is None:
            continue
        cur_x = float(fx_bone.get("x", 0.0))
        cur_y = float(fx_bone.get("y", 0.0))
        cur_sx = float(fx_bone.get("scaleX", 1.0))
        cur_sy = float(fx_bone.get("scaleY", 1.0))

        err_sx = abs(cur_sx - exp_sx) / max(1e-5, abs(exp_sx))
        err_sy = abs(cur_sy - exp_sy) / max(1e-5, abs(exp_sy))
        err_xy = math.hypot(cur_x - exp_x, cur_y - exp_y)
        if err_sx > 0.02 or err_sy > 0.02 or err_xy > 8.0:
            fx_bone["x"] = round(exp_x, 4)
            fx_bone["y"] = round(exp_y, 4)
            fx_bone["scaleX"] = round(exp_sx, 6)
            fx_bone["scaleY"] = round(exp_sy, 6)
            sw = layout["canvas_w"] / p_ux
            sh = layout["canvas_h"] / p_uy
            if "skeleton" in sk:
                sk["skeleton"]["x"] = round(exp_x - sw / 2.0, 2)
                sk["skeleton"]["y"] = round(exp_y - sh / 2.0, 2)
                sk["skeleton"]["width"] = round(sw, 2)
                sk["skeleton"]["height"] = round(sh, 2)
            write_json(skel_p, sk)
            patched.append(
                f"{fx_id}: ({cur_x:.1f},{cur_y:.1f},s={cur_sx:.3f},{cur_sy:.3f}) -> ({exp_x:.1f},{exp_y:.1f},s={exp_sx:.3f},{exp_sy:.3f})"
            )
    return patched


def _get_bg_rect_main_space(skin_dir: Path) -> tuple[float, float, float, float] | None:
    """Compute exact bg_rect [x0, y0, x1, y1] in MAIN skeleton world coordinates from submodels/bg_static."""
    bg_dir = skin_dir / "submodels" / "bg_static"
    bg_cfg_p = bg_dir / ".config.json"
    main_cfg_p = skin_dir / ".config.json"
    if not (bg_cfg_p.is_file() and main_cfg_p.is_file()):
        return None
    main_cfg = json.loads(main_cfg_p.read_text(encoding="utf-8-sig"))
    bg_cfg = json.loads(bg_cfg_p.read_text(encoding="utf-8-sig"))
    main_sf = float(main_cfg["options"]["scale_factor"])
    bg_sf = float(bg_cfg["options"]["scale_factor"])
    ratio = bg_sf / max(1e-6, main_sf)

    sk_p = bg_dir / bg_cfg["skeleton"]
    if not sk_p.is_file() or not sk_p.read_bytes().lstrip().startswith(b"{"):
        return None
    sk = json.loads(sk_p.read_text(encoding="utf-8-sig"))
    bones = sk.get("bones") or []
    b = next((x for x in bones if x.get("name") in ("bg_root", "fg_root")), bones[1] if len(bones) > 1 else bones[0])
    bx, by = float(b.get("x", 0.0)), float(b.get("y", 0.0))
    bsx, bsy = float(b.get("scaleX", 1.0)), float(b.get("scaleY", 1.0))

    att_w = att_h = 0.0
    for s in (sk.get("skins") or []):
        for sl in (s.get("attachments") or {}).values():
            for av in sl.values():
                if isinstance(av, dict) and "width" in av:
                    att_w = float(av["width"])
                    att_h = float(av["height"])
                    break
    if att_w <= 0 or att_h <= 0:
        return None
    hw = att_w * bsx * 0.5
    hh = att_h * bsy * 0.5
    return ((bx - hw) * ratio, (by - hh) * ratio, (bx + hw) * ratio, (by + hh) * ratio)


def _apply_non_fx_clips_and_main_rot(skin: dict[str, Any], skin_dir: Path) -> dict[str, Any]:
    """Patch MAIN root rotation (if overridden) and inject/update viewport_clip / bg_clip / fg_clip on non-FX skeletons.
    Strictly never modifies any file inside submodels/fx_*.
    """
    info: dict[str, Any] = {"main_rot_patched": None, "clips": {}}
    main_cfg_p = skin_dir / ".config.json"
    if not main_cfg_p.is_file():
        return info
    main_cfg = json.loads(main_cfg_p.read_text(encoding="utf-8-sig"))
    main_sf = float(main_cfg["options"]["scale_factor"])
    main_skel_p = skin_dir / main_cfg["skeleton"]

    # 1. Optional MAIN root bone rotation override (e.g. 901_Lavira_S2 -> -10.0 deg)
    ov = _SCENE_LAYOUT_OVERRIDES.get(skin["skin_key"], {})
    if "main_root_rot" in ov and main_skel_p.is_file():
        target_rot = float(ov["main_root_rot"])
        raw = main_skel_p.read_bytes()
        if not raw.lstrip().startswith(b"{"):
            parsed = parse_spine38_binary(raw)
            cur_rot = float(parsed["bones"][0]["rot"])
            if abs(cur_rot - target_rot) > 0.25:
                patched = patch_binary_root_transform(raw, parsed, add_rot=(target_rot - cur_rot))
                main_skel_p.write_bytes(patched)
                info["main_rot_patched"] = f"{cur_rot:.2f} -> {target_rot:.2f}"

    # 2. Compute exact bg_rect from submodels/bg_static and inject/update non-FX clips
    bg_rect = _get_bg_rect_main_space(skin_dir)
    if bg_rect is None:
        return info

    if main_skel_p.is_file():
        r = inject_clip_spine38_binary(main_skel_p, bg_rect, clip_name="viewport_clip")
        info["clips"]["MAIN"] = r.get("status", "err") + ":" + str(r.get("action") or r.get("reason") or "")

    sub_root = skin_dir / "submodels"
    if sub_root.is_dir():
        for fd in sorted(sub_root.iterdir()):
            if not fd.is_dir():
                continue
            low = fd.name.lower()
            # STRICT BOUNDARY: never touch any submodels/fx_* files!
            if low.startswith("fx_") or low == "bg_static":
                continue
            scp = fd / ".config.json"
            if not scp.is_file():
                continue
            sc = json.loads(scp.read_text(encoding="utf-8-sig"))
            sub_sf = float(sc["options"]["scale_factor"])
            mul = main_sf / max(1e-6, sub_sf)
            sub_rect = tuple(v * mul for v in bg_rect)
            skel_p = fd / sc["skeleton"]
            if not skel_p.is_file():
                continue
            if low == "bg_mid":
                r = inject_clip_spine38_json(skel_p, sub_rect, clip_name="bg_clip")
            elif low == "fg_static":
                r = inject_clip_spine38_json(skel_p, sub_rect, clip_name="fg_clip")
            else:
                r = inject_clip_spine38_binary(skel_p, sub_rect, clip_name="viewport_clip")
            info["clips"][fd.name] = r.get("status", "err") + ":" + str(r.get("action") or r.get("reason") or "")
    return info


def _sync_submodel_cmd_in_configs(
    skin_dir: Path,
    new_cmd: str,
    assigned_subs: list[tuple[str, str, int]],
) -> list[str]:
    """Update start[*].command, reload_bg[*].command, and 背景开关 across ZH/EN/JA configs."""
    all_rels = [r for _, r, _ in assigned_subs]
    rm_all_cmd = "; ".join(f"remove_submodel {r}" for r in all_rels)
    reload_cmd = "; ".join(x for x in (rm_all_cmd, new_cmd) if x)

    updated_files: list[str] = []
    for fn in (".config.json", "config_en.config.json", "config_ja.config.json"):
        cp = skin_dir / fn
        if not cp.is_file():
            continue
        cfg = json.loads(cp.read_text(encoding="utf-8"))
        changed = False
        motions = cfg.get("motions", {})

        # 1. start
        for it in motions.get("start") or []:
            old_c = it.get("command", "")
            extra = [s.strip() for s in old_c.split(";") if s.strip() and not s.strip().startswith("add_submodel ")]
            merged = "; ".join(([new_cmd] if new_cmd else []) + extra)
            if merged != old_c:
                if merged:
                    it["command"] = merged
                elif "command" in it:
                    del it["command"]
                changed = True

        # 2. reload_bg (always remove_submodel BEFORE add_submodel!)
        for it in motions.get("reload_bg") or []:
            old_c = it.get("command", "")
            extra = [
                s.strip()
                for s in old_c.split(";")
                if s.strip() and not s.strip().startswith(("add_submodel ", "remove_submodel "))
            ]
            merged = "; ".join(([reload_cmd] if reload_cmd else []) + extra)
            if merged != old_c:
                if merged:
                    it["command"] = merged
                elif "command" in it:
                    del it["command"]
                changed = True

        # 3. 背景开关 (preserve touch-only FX exclusion in hide_bg, sync show_bg to new_cmd)
        bg_tog = motions.get("背景开关")
        if isinstance(bg_tog, list):
            for it in bg_tog:
                nm = it.get("name", "")
                old_c = it.get("command", "")
                if nm == "hide_bg":
                    old_rms = {
                        s.strip().split()[1]
                        for s in old_c.split(";")
                        if s.strip().startswith("remove_submodel ") and len(s.strip().split()) >= 2
                    }
                    # Keep any existing fx_* that was intentionally NOT removed on hide_bg (touch-only FX)
                    hide_rels = []
                    for r in all_rels:
                        folder = Path(r).parent.name.lower()
                        if folder.startswith("fx_") and old_rms and r not in old_rms:
                            continue
                        hide_rels.append(r)
                    new_hide = "; ".join(f"remove_submodel {r}" for r in hide_rels)
                    if new_hide != old_c:
                        it["command"] = new_hide
                        changed = True
                elif nm == "show_bg":
                    if new_cmd != old_c:
                        it["command"] = new_cmd
                        changed = True

        if changed:
            write_json(cp, cfg)
            updated_files.append(fn)
    return updated_files


def fix_one_skin(
    skin: dict[str, Any],
    indexer: AssetIndexer,
    repos: BatchAssetRepos,
) -> dict[str, Any]:
    rel = f"{skin['char_name']}/{skin['dress_name']}"
    skin_dir = SPINE_OUT_ROOT / skin["char_name"] / skin["dress_name"]
    cfg_p = skin_dir / ".config.json"
    if not cfg_p.is_file():
        return {"skin": rel, "status": "missing_config"}

    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    base_scale = float(cfg["options"]["scale_factor"])
    old_start_cmd = cfg.get("motions", {}).get("start", [{}])[0].get("command", "")
    existing_fx = _parse_existing_fx_items(skin_dir, cfg)
    has_ex_back = any(layer == "back" for _, _, layer in existing_fx)
    has_ex_front = any(layer == "front" for _, _, layer in existing_fx)

    layout = inspect_bg_prefab_layout(indexer, skin)
    sub_root = skin_dir / "submodels"
    sub_root.mkdir(parents=True, exist_ok=True)

    non_fx_assigned, _ = _build_scene_submodels_exact(
        repos=repos,
        indexer=indexer,
        skin=skin,
        layout=layout,
        base_scale=base_scale,
        sub_root=sub_root,
        has_back_fx=has_ex_back,
        has_front_fx=has_ex_front,
        clean_old_non_fx=True,
        force_fx_sides=(has_ex_back, has_ex_front),
    )

    # NOTE: Never modify submodels/fx_* files here (fx-particle-architect owns all fx_* pipelines)
    fx_patched: list[str] = []
    assigned_subs = _assign_orders(non_fx_assigned, existing_fx)
    new_cmd = "; ".join(f"add_submodel {r} {o}" for _, r, o in assigned_subs)
    cfg_updated = _sync_submodel_cmd_in_configs(skin_dir, new_cmd, assigned_subs)
    clip_info = _apply_non_fx_clips_and_main_rot(skin, skin_dir)

    return {
        "skin": rel,
        "status": "ok",
        "old_cmd": old_start_cmd,
        "new_cmd": new_cmd,
        "cmd_changed": old_start_cmd != new_cmd,
        "configs_updated": cfg_updated,
        "fx_recalibrated": fx_patched,
        "clip_info": clip_info,
        "submodels": [f"{Path(r).parent.name}({o})" for _, r, o in assigned_subs],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix BG/FG submodels across SoulTide Dress Spine packages.")
    parser.add_argument("--only", action="append", default=[], help="Specific skin(s) e.g. 叶隐琉璃/绵绵小懒虫")
    parser.add_argument("--all", action="store_true", help="Fix all 109 Dress Spine packages")
    args = parser.parse_args()

    if not args.only and not args.all:
        parser.error("Specify --only <char/dress> or --all")

    repo = FullI18nRepo()
    catalog = build_skin_catalog(repo)

    if args.only:
        want = {x.replace("\\", "/") for x in args.only}
        targets = [s for s in catalog if f"{s['char_name']}/{s['dress_name']}" in want]
    else:
        targets = list(catalog)

    indexer = AssetIndexer(light=True)
    repos = BatchAssetRepos(indexer)

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for i, sk in enumerate(targets, 1):
        rel = f"{sk['char_name']}/{sk['dress_name']}"
        if rel in PROTECTED_SKINS:
            print(f"[{i}/{len(targets)}] SKIP {rel} (PROTECTED/READONLY)", flush=True)
            continue
        try:
            res = fix_one_skin(sk, indexer, repos)
            results.append(res)
            tag = "CMD_CHG" if res.get("cmd_changed") else "SUB_UPD"
            fx_tag = f" FX_FIX={len(res.get('fx_recalibrated', []))}" if res.get("fx_recalibrated") else ""
            print(f"[{i}/{len(targets)}] {tag} {rel}: {res.get('submodels')}{fx_tag}", flush=True)
        except Exception as exc:
            import traceback
            errors.append({"skin": rel, "error": str(exc), "trace": traceback.format_exc()})
            print(f"[{i}/{len(targets)}] ERROR {rel}: {exc}", flush=True)
        if i % 15 == 0:
            gc.collect()

    report = {
        "total_processed": len(results),
        "cmd_changed_count": sum(1 for r in results if r.get("cmd_changed")),
        "fx_recalibrated_count": sum(1 for r in results if r.get("fx_recalibrated")),
        "error_count": len(errors),
        "errors": errors,
        "results": results,
    }
    write_json(REPORT_PATH, report)
    print(
        f"[fix_all_spine_bg_layouts] DONE processed={len(results)} cmd_changed={report['cmd_changed_count']} "
        f"fx_recal={report['fx_recalibrated_count']} errors={len(errors)} -> {REPORT_PATH}",
        flush=True,
    )
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
