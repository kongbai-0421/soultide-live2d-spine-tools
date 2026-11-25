r"""Switch all Live2D packages' Idle motion to standby1 and set FadeIn=0 across all 3 languages.

Rules:
- Scans every `<doll>/<skin>/.model3.json` under `E:\A灵魂潮汐\Live2D与Spine模型\live2d\`.
- Updates `.model3.json`, `model_en.model3.json`, and `model_ja.model3.json` identically.
- Finds the exact `*standby1.motion3.json` in `motions/` (falling back to
  `*standby1_*.motion3.json` such as `ch_sakuyamako@live2d_standby1_white.motion3.json`
  when exact `standby1` does not exist; if no `standby1` exists at all, keeps current
  `Idle[0]["File"]` and still sets `"FadeIn": 0`).
- Preserves existing `Command` / `PostCommand` / other keys on `Idle[0]` (e.g., Scheme A
  submodel failsafe commands on 伊汐尔 / 越一弥心 / 露比·罗斯).

Idempotent: safe to re-run at any time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from soultide_common import write_json

LIVE2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
LANG_FILES = (".model3.json", "model_en.model3.json", "model_ja.model3.json")
REPORT_PATH = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本\l2d_idle_standby1_report.json")


def find_standby1(pkg_dir: Path) -> tuple[str | None, str | None, str]:
    """Return (rel_file, name, match_kind)."""
    mots = sorted((pkg_dir / "motions").glob("*.motion3.json"))
    exact = [
        m for m in mots
        if m.name.lower().endswith("@live2d_standby1.motion3.json")
        or m.name.lower().endswith("_standby1.motion3.json")
        or m.name.lower() == "standby1.motion3.json"
    ]
    if len(exact) == 1:
        return f"motions/{exact[0].name}", "standby1", "exact_standby1"
    if len(exact) > 1:
        raise RuntimeError(f"Multiple exact standby1 candidates in {pkg_dir}: {[m.name for m in exact]}")

    variant = [
        m for m in mots
        if "standby1_" in m.name.lower()
    ]
    if len(variant) == 1:
        stem = variant[0].stem
        if stem.endswith(".motion3"):
            stem = stem[:-8]
        name = stem.split("@live2d_")[-1] if "@live2d_" in stem else stem
        return f"motions/{variant[0].name}", name, "variant_standby1"
    if len(variant) > 1:
        raise RuntimeError(f"Multiple standby1 variant candidates in {pkg_dir}: {[m.name for m in variant]}")

    return None, None, "no_standby1_keep_file"


def main() -> None:
    pkgs = sorted(p.parent for p in LIVE2D_ROOT.glob("*/*/.model3.json"))
    counts = {
        "total_packages": len(pkgs),
        "exact_standby1": 0,
        "variant_standby1": 0,
        "no_standby1_keep_file": 0,
        "lang_files_written": 0,
    }
    special_cases: list[dict[str, Any]] = []

    for pkg in pkgs:
        rel = f"{pkg.parent.name}/{pkg.name}"
        target_file, target_name, kind = find_standby1(pkg)
        counts[kind] += 1

        before_file = None
        after_file = None

        for lang_fn in LANG_FILES:
            cfg_p = pkg / lang_fn
            if not cfg_p.is_file():
                raise FileNotFoundError(f"Missing language config: {cfg_p}")
            data = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
            idle_list = data["FileReferences"]["Motions"].get("Idle") or []
            if len(idle_list) != 1:
                raise AssertionError(f"{rel}/{lang_fn}: expected 1 Idle entry, got {len(idle_list)}")

            item = idle_list[0]
            if lang_fn == ".model3.json":
                before_file = item.get("File")

            if target_file is not None:
                # Validate target motion file is readable JSON
                if lang_fn == ".model3.json":
                    json.loads((pkg / target_file).read_text(encoding="utf-8-sig"))
                item["Name"] = target_name
                item["File"] = target_file
            item["FadeIn"] = 0

            if lang_fn == ".model3.json":
                after_file = item.get("File")

            write_json(cfg_p, data)
            counts["lang_files_written"] += 1

        if kind != "exact_standby1":
            special_cases.append({
                "package": rel,
                "kind": kind,
                "before_file": before_file,
                "after_file": after_file,
                "FadeIn": 0,
            })

    report = {
        "counts": counts,
        "special_cases": special_cases,
    }
    write_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
