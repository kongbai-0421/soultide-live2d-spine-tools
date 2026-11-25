r"""Bit-exact lossless storage optimizer for SoulTide Live2D & Spine packages.

Performs 3 strictly lossless optimizations in-place under `E:\A灵魂潮汐\Live2D与Spine模型\`:
1. Orphan cleanup: removes verified unreferenced FX PNGs (`fx_aurora_s4_8.png`, `_9.png`).
2. PNG -> Bit-Exact Lossless WebP (`lossless=True, exact=True, quality=100, method=4`):
   - Converts all Live2D and Spine PNG textures to `.webp`, verifies 100% pixel-identical
     RGBA round-trip (`np.array_equal(src_rgba, dec_rgba)`), keeps `.png` if `.webp` is not
     strictly smaller, then atomically updates all references:
     * Live2D `*.model3.json`: `FileReferences.Textures[]`, `Options.TexType = 1`, and any
       `replace_tex` commands in `Command` / `PostCommand`.
     * Spine `*.atlas.txt` & `*.config.json`: atlas page names, `textures[]`, and
       `options.tex_type = 1`.
3. Compact JSON minification (`separators=(",", ":")`):
   - Live2D `.motion3.json`, `.physics3.json`, `.model3.json`
   - Spine `.config.json` and UTF-8 JSON `.skel.json` (safely skips binary `.skel`)

Does NOT touch audio `.ogg` files (zero lossy audio re-encoding) or `soultide.db`.
Idempotent: safe to re-run at any time.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型")
LIVE2D_ROOT = ROOT / "live2d"
SPINE_ROOT = ROOT / "spine"
REPORT_PATH = ROOT / "工具脚本" / "storage_optimize_report.json"

ORPHAN_PNGS = [
    SPINE_ROOT / "欧若拉" / "童话心绘" / "submodels" / "fx_aurora_s4" / "fx_aurora_s4_8.png",
    SPINE_ROOT / "欧若拉" / "童话心绘" / "submodels" / "fx_aurora_s4" / "fx_aurora_s4_9.png",
]


def _convert_one_png_to_exact_webp(png_path_str: str) -> dict[str, Any]:
    png_p = Path(png_path_str)
    webp_p = png_p.with_suffix(".webp")
    orig_size = png_p.stat().st_size

    with Image.open(png_p) as im:
        rgba = im.convert("RGBA")
        src_arr = np.asarray(rgba)
        rgba.save(webp_p, "WEBP", lossless=True, exact=True, quality=100, method=4)

    new_size = webp_p.stat().st_size
    if new_size >= orig_size:
        webp_p.unlink(missing_ok=True)
        return {
            "path": png_path_str,
            "converted": False,
            "reason": "webp_not_smaller",
            "orig_bytes": orig_size,
            "new_bytes": orig_size,
        }

    # Mandatory bit-exact round-trip verification (guarantees PMA & A==0 RGB 0 tampering)
    with Image.open(webp_p) as wim:
        dec_arr = np.asarray(wim.convert("RGBA"))
    if src_arr.shape != dec_arr.shape or not np.array_equal(src_arr, dec_arr):
        webp_p.unlink(missing_ok=True)
        raise AssertionError(f"Bit-exact WebP check FAILED on {png_p}!")

    return {
        "path": png_path_str,
        "webp_path": str(webp_p),
        "converted": True,
        "orig_bytes": orig_size,
        "new_bytes": new_size,
    }


def _rewrite_l2d_refs(converted_map: dict[Path, Path]) -> int:
    """Update Textures[], Options.TexType=1, and replace_tex commands in all Live2D *.model3.json."""
    updated = 0
    for m3p in sorted(LIVE2D_ROOT.rglob("*.model3.json")):
        raw = m3p.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        mdir = m3p.parent
        changed = False

        fr = data.get("FileReferences") or {}
        texs = fr.get("Textures") or []
        new_texs: list[str] = []
        any_webp = False
        for t in texs:
            tp = (mdir / t).resolve()
            if tp in converted_map:
                nt = str(Path(t).with_suffix(".webp")).replace("\\", "/")
                new_texs.append(nt)
                changed = True
                any_webp = True
            else:
                new_texs.append(t)
                if t.lower().endswith(".webp"):
                    any_webp = True
        if changed:
            fr["Textures"] = new_texs

        # Update replace_tex commands
        for _grp, items in (fr.get("Motions") or {}).items():
            for it in items:
                for cf in ("Command", "PostCommand"):
                    c = it.get(cf)
                    if not c or "replace_tex" not in c:
                        continue
                    segs = []
                    seg_changed = False
                    for seg in c.split(";"):
                        s = seg.strip()
                        toks = s.split()
                        if len(toks) >= 3 and toks[0] == "replace_tex":
                            tp = (mdir / toks[2]).resolve()
                            if tp in converted_map:
                                toks[2] = str(Path(toks[2]).with_suffix(".webp")).replace("\\", "/")
                                s = " ".join(toks)
                                seg_changed = True
                        segs.append(s)
                    if seg_changed:
                        it[cf] = "; ".join(segs)
                        changed = True

        if any_webp:
            opt = data.setdefault("Options", {})
            if opt.get("TexType") != 1:
                opt["TexType"] = 1
                changed = True

        if changed:
            m3p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            updated += 1
    return updated


def _rewrite_spine_refs(converted_map: dict[Path, Path]) -> tuple[int, int]:
    """Update Spine *.atlas.txt page names and *.config.json textures[] + options.tex_type=1."""
    atlases_updated = 0
    configs_updated = 0

    for ap in sorted(SPINE_ROOT.rglob("*.atlas.txt")):
        adir = ap.parent
        lines = ap.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        new_lines = []
        changed = False
        for line in lines:
            stripped = line.strip()
            if stripped.lower().endswith(".png"):
                tp = (adir / stripped).resolve()
                if tp in converted_map:
                    eol = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
                    new_name = str(Path(stripped).with_suffix(".webp")).replace("\\", "/")
                    new_lines.append(new_name + eol)
                    changed = True
                    continue
            new_lines.append(line)
        if changed:
            ap.write_text("".join(new_lines), encoding="utf-8")
            atlases_updated += 1

    for cp in sorted(SPINE_ROOT.rglob("*.config.json")):
        cdir = cp.parent
        data = json.loads(cp.read_text(encoding="utf-8-sig"))
        changed = False
        has_webp = False

        # Check nested atlases[].textures (primary SpineViewerEX config schema!)
        if isinstance(data.get("atlases"), list):
            for atl in data["atlases"]:
                if isinstance(atl, dict) and isinstance(atl.get("textures"), list):
                    new_at = []
                    for t in atl["textures"]:
                        tp = (cdir / t).resolve()
                        webp_cand = (cdir / Path(t).with_suffix(".webp"))
                        if tp in converted_map or (t.lower().endswith(".png") and not (cdir / t).is_file() and webp_cand.is_file()):
                            new_at.append(str(Path(t).with_suffix(".webp")).replace("\\", "/"))
                            changed = True
                            has_webp = True
                        else:
                            new_at.append(t)
                            if t.lower().endswith(".webp"):
                                has_webp = True
                    atl["textures"] = new_at

        # Check top-level textures array if present
        if isinstance(data.get("textures"), list):
            new_t = []
            for t in data["textures"]:
                tp = (cdir / t).resolve()
                webp_cand = (cdir / Path(t).with_suffix(".webp"))
                if tp in converted_map or (t.lower().endswith(".png") and not (cdir / t).is_file() and webp_cand.is_file()):
                    new_t.append(str(Path(t).with_suffix(".webp")).replace("\\", "/"))
                    changed = True
                    has_webp = True
                else:
                    new_t.append(t)
                    if t.lower().endswith(".webp"):
                        has_webp = True
            if changed:
                data["textures"] = new_t

        # Check if any .webp exists in same directory (atlas page)
        if not has_webp:
            if any(cdir.glob("*.webp")):
                has_webp = True

        if has_webp:
            opt = data.setdefault("options", {})
            if opt.get("tex_type") != 1:
                opt["tex_type"] = 1
                changed = True
            if "shader_type" not in opt:
                opt["shader_type"] = 0
                changed = True

        if changed:
            cp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            configs_updated += 1

    return atlases_updated, configs_updated


def _compact_json_batch(paths: list[str]) -> tuple[int, int, int]:
    """Minify UTF-8 JSON files losslessly; skip binary .skel safely."""
    files_compacted = 0
    raw_total = 0
    new_total = 0
    for ps in paths:
        p = Path(ps)
        raw = p.read_bytes()
        raw_total += len(raw)
        if not raw.lstrip().startswith(b"{"):
            new_total += len(raw)
            continue
        obj = json.loads(raw.decode("utf-8-sig"))
        out = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(out) < len(raw):
            p.write_bytes(out)
            files_compacted += 1
            new_total += len(out)
        else:
            new_total += len(raw)
    return files_compacted, raw_total, new_total


def dir_size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def main() -> None:
    parser = argparse.ArgumentParser(description="Lossless storage optimizer for Live2D & Spine.")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    before_l2d = dir_size(LIVE2D_ROOT)
    before_spine = dir_size(SPINE_ROOT)

    # 1. Remove confirmed orphan PNGs
    removed_orphans: list[dict[str, Any]] = []
    for op in ORPHAN_PNGS:
        if op.is_file():
            sz = op.stat().st_size
            op.unlink()
            removed_orphans.append({"path": str(op.relative_to(ROOT)), "bytes": sz})

    # 2. Convert all remaining PNGs in live2d/ and spine/ to bit-exact lossless WebP
    l2d_pngs = sorted(LIVE2D_ROOT.rglob("*.png"))
    sp_pngs = sorted(SPINE_ROOT.rglob("*.png"))
    all_pngs = l2d_pngs + sp_pngs
    print(f"[WebP] Converting {len(all_pngs)} PNGs ({len(l2d_pngs)} Live2D + {len(sp_pngs)} Spine) with {args.workers} workers...", flush=True)

    converted_map: dict[Path, Path] = {}
    webp_stats = {
        "l2d_converted": 0, "l2d_kept_png": 0, "l2d_orig_bytes": 0, "l2d_new_bytes": 0,
        "sp_converted": 0, "sp_kept_png": 0, "sp_orig_bytes": 0, "sp_new_bytes": 0,
    }
    l2d_set = {str(p) for p in l2d_pngs}

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_convert_one_png_to_exact_webp, str(p)): str(p) for p in all_pngs}
        done = 0
        for fut in as_completed(futs):
            res = fut.result()
            done += 1
            is_l2d = res["path"] in l2d_set
            pref = "l2d" if is_l2d else "sp"
            webp_stats[f"{pref}_orig_bytes"] += res["orig_bytes"]
            webp_stats[f"{pref}_new_bytes"] += res["new_bytes"]
            if res["converted"]:
                webp_stats[f"{pref}_converted"] += 1
                converted_map[Path(res["path"]).resolve()] = Path(res["webp_path"]).resolve()
            else:
                webp_stats[f"{pref}_kept_png"] += 1
            if done % 200 == 0 or done == len(all_pngs):
                print(f"  [WebP] {done}/{len(all_pngs)} done...", flush=True)

    # Rewrite all Live2D & Spine config/atlas references BEFORE deleting old PNGs
    l2d_refs_updated = _rewrite_l2d_refs(converted_map)
    sp_atlases_updated, sp_configs_updated = _rewrite_spine_refs(converted_map)

    # Delete original PNGs that were bit-exact converted and referenced
    for old_png in converted_map:
        old_png.unlink()

    print(f"[WebP] Done. Updated {l2d_refs_updated} L2D configs, {sp_atlases_updated} Spine atlases, {sp_configs_updated} Spine configs.", flush=True)

    # 3. Compact JSON files across Live2D & Spine
    json_groups = {
        "l2d_motion3": [str(p) for p in LIVE2D_ROOT.rglob("*.motion3.json")],
        "l2d_model3": [str(p) for p in LIVE2D_ROOT.rglob("*.model3.json")],
        "l2d_physics3": [str(p) for p in LIVE2D_ROOT.rglob("*.physics3.json")],
        "l2d_exp3": [str(p) for p in LIVE2D_ROOT.rglob("*.exp3.json")],
        "spine_config": [str(p) for p in SPINE_ROOT.rglob("*.config.json")],
        "spine_skel_json": [str(p) for p in SPINE_ROOT.rglob("*.skel.json")],
        "spine_other_json": [
            str(p) for p in SPINE_ROOT.rglob("*.json")
            if not p.name.lower().endswith((".config.json", ".skel.json"))
        ],
    }
    json_stats: dict[str, Any] = {}
    for gname, paths in json_groups.items():
        if not paths:
            continue
        # Split into chunks for ProcessPoolExecutor
        chunks = [paths[i::args.workers] for i in range(args.workers)]
        chunks = [c for c in chunks if c]
        tot_comp = tot_raw = tot_new = 0
        with ProcessPoolExecutor(max_workers=min(args.workers, len(chunks))) as ex:
            for c, r, n in ex.map(_compact_json_batch, chunks):
                tot_comp += c
                tot_raw += r
                tot_new += n
        json_stats[gname] = {
            "files_scanned": len(paths),
            "files_compacted": tot_comp,
            "raw_bytes": tot_raw,
            "new_bytes": tot_new,
            "saved_bytes": tot_raw - tot_new,
        }
        print(f"  [JSON] {gname}: {tot_comp}/{len(paths)} compacted, saved {(tot_raw-tot_new)/1e6:.2f} MB", flush=True)

    after_l2d = dir_size(LIVE2D_ROOT)
    after_spine = dir_size(SPINE_ROOT)

    report = {
        "before_bytes": {"live2d": before_l2d, "spine": before_spine, "total": before_l2d + before_spine},
        "after_bytes": {"live2d": after_l2d, "spine": after_spine, "total": after_l2d + after_spine},
        "saved_bytes": {
            "live2d": before_l2d - after_l2d,
            "spine": before_spine - after_spine,
            "total": (before_l2d + before_spine) - (after_l2d + after_spine),
        },
        "saved_mb": {
            "live2d": round((before_l2d - after_l2d) / (1024 * 1024), 2),
            "spine": round((before_spine - after_spine) / (1024 * 1024), 2),
            "total": round(((before_l2d + before_spine) - (after_l2d + after_spine)) / (1024 * 1024), 2),
        },
        "removed_orphans": removed_orphans,
        "webp": {
            **webp_stats,
            "l2d_refs_updated": l2d_refs_updated,
            "sp_atlases_updated": sp_atlases_updated,
            "sp_configs_updated": sp_configs_updated,
        },
        "json_compact": json_stats,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
