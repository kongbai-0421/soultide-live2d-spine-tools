"""Reusable helper CLI to validate and update Spine hit_areas across all 3 language configs.

Validates:
  - Every hit_area bone `id` exists in the actual Spine 3.8 skeleton (no `root`, no duplicates).
  - Every hit_area `motion` exists in `motions` and `width`/`height` are positive.
Writes the identical `hit_areas` list to `.config.json`, `config_en.config.json`, and
`config_ja.config.json`, then immediately re-renders the model's preview JPG via
`render_spine_touch_previews.py --only <rel>`.

Usage examples:
  python update_spine_hit_areas.py --rel "伊汐尔/原皮" --hit-areas-json '[{"name":"头",...}]'
  python update_spine_hit_areas.py --rel "伊汐尔/原皮" --hit-areas-file hits.json
  python update_spine_hit_areas.py "伊汐尔/原皮" hits.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from batch_spine_builder import parse_spine38_binary
from soultide_common import write_json

SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
RENDERER_PY = TOOLS_DIR / "render_spine_touch_previews.py"
COMPOSITE_RENDERER_PY = TOOLS_DIR / "render_spine_composite_previews.py"
AUDIT_SPINE_OUT = TOOLS_DIR / "_doll_audit_previews" / "spine"
READONLY_MODELS: set[str] = set()
LANG_FILES = (".config.json", "config_en.config.json", "config_ja.config.json")


def _load_skeleton_bones(skel_path: Path) -> set[str]:
    if not skel_path.is_file():
        raise FileNotFoundError(f"Missing skeleton file: {skel_path}")
    raw = skel_path.read_bytes()
    if raw.lstrip().startswith(b"{"):
        data = json.loads(raw.decode("utf-8"))
        return {b["name"] for b in data.get("bones", [])}
    parsed = parse_spine38_binary(raw)
    return {b["name"] for b in parsed["bones"]}


def _validate_and_normalize_hit_areas(
    hit_areas: Any,
    bones: set[str],
    motions: dict[str, Any],
    rel: str,
) -> list[dict[str, Any]]:
    if not isinstance(hit_areas, list) or len(hit_areas) < 3:
        raise ValueError(f"hit_areas must contain at least 3 entries for {rel}")

    seen_bones: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for idx, ha in enumerate(hit_areas):
        if not isinstance(ha, dict):
            raise ValueError(f"hit_areas[{idx}] must be an object")
        bid = str(ha.get("id", "")).strip()
        name = str(ha.get("name", "")).strip()
        motion = str(ha.get("motion", name)).strip()
        if not bid:
            raise ValueError(f"hit_areas[{idx}] missing bone 'id'")
        if bid == "root":
            raise ValueError(f"hit_areas[{idx}] cannot bind bone 'root'")
        if bid not in bones:
            raise ValueError(f"hit_areas[{idx}] bone '{bid}' does not exist in skeleton of {rel}")
        if bid in seen_bones:
            raise ValueError(f"Duplicate bone '{bid}' in hit_areas for {rel}")
        seen_bones.add(bid)

        if not name:
            raise ValueError(f"hit_areas[{idx}] missing 'name'")
        if motion not in motions:
            raise ValueError(f"hit_areas[{idx}] motion '{motion}' not found in motions of {rel}")

        width = float(ha.get("width", 0))
        height = float(ha.get("height", 0))
        if width <= 0 or height <= 0:
            raise ValueError(f"hit_areas[{idx}] width/height must be > 0, got ({width}, {height})")

        entry: dict[str, Any] = {
            "name": name,
            "id": bid,
            "motion": motion,
            "width": round(width, 3),
            "height": round(height, 3),
        }
        if "center_x" in ha and ha["center_x"] is not None:
            entry["center_x"] = round(float(ha["center_x"]), 3)
        if "center_y" in ha and ha["center_y"] is not None:
            entry["center_y"] = round(float(ha["center_y"]), 3)
        normalized.append(entry)
    return normalized


def _render_composite_and_load_meta(rel: str, force: bool = False) -> dict[str, Any] | None:
    char_nm, skin_nm = rel.split("/", 1)
    matches = sorted(AUDIT_SPINE_OUT.glob(f"*_{char_nm}__{skin_nm}.meta.json")) if AUDIT_SPINE_OUT.is_dir() else []
    if force or not matches:
        r = subprocess.run(
            [
                sys.executable,
                str(COMPOSITE_RENDERER_PY),
                "--only",
                rel,
                "--with-hits",
                "--emit-meta",
                "--skip-fx",
                "--out-dir",
                str(AUDIT_SPINE_OUT),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"Composite render failed for {rel}:\n{r.stderr}\n{r.stdout}")
        matches = sorted(AUDIT_SPINE_OUT.glob(f"*_{char_nm}__{skin_nm}.meta.json"))
    if not matches:
        return None
    return json.loads(matches[0].read_text(encoding="utf-8-sig"))


def _validate_bg_bounds(rel: str, normalized: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    bg_rect = meta.get("bg_rect")
    if not bg_rect:
        return
    bg_x0, bg_x1 = float(bg_rect["x0"]), float(bg_rect["x1"])
    bg_y0, bg_y1 = float(bg_rect["y0"]), float(bg_rect["y1"])
    bone_map = {b["id"]: b for b in meta.get("bones", [])}
    tol = 5.0
    for ha in normalized:
        bid = ha["id"]
        bm = bone_map.get(bid)
        if not bm:
            continue
        bcx = float(bm["wx"]) + float(ha.get("center_x", 0.0)) * 100.0
        bcy = float(bm["wy"]) + float(ha.get("center_y", 0.0)) * 100.0
        hw = float(ha["width"]) * 100.0
        hh = float(ha["height"]) * 100.0
        hx0, hx1 = bcx - hw * 0.5, bcx + hw * 0.5
        hy0, hy1 = bcy - hh * 0.5, bcy + hh * 0.5
        ov_l = max(0.0, bg_x0 - hx0)
        ov_r = max(0.0, hx1 - bg_x1)
        ov_b = max(0.0, bg_y0 - hy0)
        ov_t = max(0.0, hy1 - bg_y1)
        center_out = not (bg_x0 - tol <= bcx <= bg_x1 + tol and bg_y0 - tol <= bcy <= bg_y1 + tol)
        if center_out or max(ov_l, ov_r, ov_b, ov_t) > tol:
            raise ValueError(
                f"hit_area '{ha['name']}' (bone={bid}) overflows bg_static bounds "
                f"[{bg_x0:.1f}..{bg_x1:.1f}]x[{bg_y0:.1f}..{bg_y1:.1f}] for {rel}: "
                f"box=[{hx0:.1f}..{hx1:.1f}]x[{hy0:.1f}..{hy1:.1f}], "
                f"ov=(L={ov_l:.1f}, R={ov_r:.1f}, B={ov_b:.1f}, T={ov_t:.1f})"
            )


def update_model_hit_areas(rel: str, raw_hit_areas: Any, rerender: bool = True) -> dict[str, Any]:
    rel = rel.replace("\\", "/").strip("/")
    if rel in READONLY_MODELS:
        raise PermissionError(f"Model '{rel}' is protected/readonly and cannot be modified.")

    skin_dir = SPINE_ROOT / rel
    main_cfg_p = skin_dir / ".config.json"
    if not main_cfg_p.is_file():
        raise FileNotFoundError(f"Model config not found: {main_cfg_p}")

    main_cfg = json.loads(main_cfg_p.read_text(encoding="utf-8"))
    bones = _load_skeleton_bones(skin_dir / main_cfg["skeleton"])
    normalized = _validate_and_normalize_hit_areas(raw_hit_areas, bones, main_cfg.get("motions", {}), rel)

    has_bg_static = (skin_dir / "submodels" / "bg_static" / ".config.json").is_file()
    if has_bg_static:
        meta = _render_composite_and_load_meta(rel, force=False)
        if meta is not None:
            _validate_bg_bounds(rel, normalized, meta)

    written_files: list[str] = []
    for fn in LANG_FILES:
        lp = skin_dir / fn
        if not lp.is_file():
            raise FileNotFoundError(f"Missing Scheme A config file: {lp}")
        cfg = json.loads(lp.read_text(encoding="utf-8"))
        cfg["hit_areas"] = normalized
        write_json(lp, cfg)
        written_files.append(str(lp))

    render_msg = ""
    composite_msg = ""
    if rerender:
        rc = subprocess.run(
            [
                sys.executable,
                str(COMPOSITE_RENDERER_PY),
                "--only",
                rel,
                "--with-hits",
                "--emit-meta",
                "--skip-fx",
                "--out-dir",
                str(AUDIT_SPINE_OUT),
            ],
            capture_output=True,
            text=True,
        )
        if rc.returncode != 0:
            raise RuntimeError(f"Composite re-render failed for {rel}:\n{rc.stderr}\n{rc.stdout}")
        composite_msg = rc.stdout.strip()

        r = subprocess.run(
            [sys.executable, str(RENDERER_PY), "--only", rel],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"Touch preview re-render failed for {rel}:\n{r.stderr}\n{r.stdout}")
        render_msg = r.stdout.strip()

    return {
        "rel": rel,
        "hit_areas_count": len(normalized),
        "written_files": written_files,
        "composite_render": composite_msg,
        "render": render_msg,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate & update hit_areas across 3 language configs and re-render preview.")
    parser.add_argument("pos_rel", nargs="?", default="", help="Optional positional model rel path, e.g. '伊汐尔/原皮'")
    parser.add_argument("pos_json", nargs="?", default="", help="Optional positional JSON string or path to JSON file")
    parser.add_argument("--rel", type=str, default="", help="Model rel path, e.g. '伊汐尔/原皮'")
    parser.add_argument("--hit-areas-json", type=str, default="", help="JSON string of updated hit_areas array")
    parser.add_argument("--hit-areas-file", type=str, default="", help="Path to JSON file containing hit_areas array")
    parser.add_argument("--no-render", action="store_true", help="Skip re-rendering preview JPG")
    args = parser.parse_args()

    rel = (args.rel or args.pos_rel).strip()
    if not rel:
        parser.error("Must provide --rel or positional model rel path")

    if args.hit_areas_json:
        raw = json.loads(args.hit_areas_json)
    elif args.hit_areas_file:
        raw = json.loads(Path(args.hit_areas_file).read_text(encoding="utf-8-sig"))
    elif args.pos_json:
        p = Path(args.pos_json)
        if p.is_file():
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
        else:
            raw = json.loads(args.pos_json)
    else:
        raw = json.loads(sys.stdin.read())

    if isinstance(raw, dict) and "hit_areas" in raw:
        raw = raw["hit_areas"]

    res = update_model_hit_areas(rel, raw, rerender=not args.no_render)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
