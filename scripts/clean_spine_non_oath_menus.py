r"""Remove redundant/non-existent `誓约模式全动作` menu and `VK_M (77)` key trigger
from all non-oath Spine skins (skins whose skeleton has NO `*_marry` / `*_oath` animations).

- Real oath Spine skins (26 skins with `*_marry` animations): untouched, keep `誓约模式全动作` + `VK_M (77)`.
- Non-oath dressed Spine skins (84 skins): remove `motions["誓约模式全动作"]` and
  `controllers.key_trigger.items` entry pointing to `"誓约模式全动作"` across all 3 language configs
  (`.config.json`, `config_en.config.json`, `config_ja.config.json`).
- Orig / battle Spine skins (65 skins): already have no oath menu, untouched.

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
import spine38_binary_to_json as s38

SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
REPORT_PATH = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本\spine_non_oath_clean_report.json")
LANG_FILES = (".config.json", "config_en.config.json", "config_ja.config.json")


def get_skeleton_anims(skin_dir: Path, cfg: dict[str, Any]) -> list[str]:
    skel_p = skin_dir / cfg["skeleton"]
    raw = skel_p.read_bytes()
    if raw.lstrip().startswith(b"{"):
        sd = json.loads(raw.decode("utf-8-sig"))
    else:
        sd = s38.spine38_binary_to_json(raw)
    return sorted((sd.get("animations") or {}).keys())


def main() -> None:
    oath_skins: list[dict[str, Any]] = []
    cleaned_skins: list[str] = []
    files_modified = 0
    already_clean_non_oath = 0

    for main_cp in sorted(SPINE_ROOT.glob("*/*/.config.json")):
        skin_dir = main_cp.parent
        rel = f"{skin_dir.parent.name}/{skin_dir.name}"
        cfg = json.loads(main_cp.read_text(encoding="utf-8-sig"))
        anims = get_skeleton_anims(skin_dir, cfg)
        marry_anims = [a for a in anims if "marry" in a.lower() or "oath" in a.lower()]

        if marry_anims:
            mots = cfg.get("motions") or {}
            norm_files = [x.get("file") for x in (mots.get("普通模式全动作") or [])]
            oath_files = [x.get("file") for x in (mots.get("誓约模式全动作") or [])]
            oath_skins.append({
                "skin": rel,
                "marry_anims": marry_anims,
                "has_oath_group": "誓约模式全动作" in mots,
                "has_oath_special": "誓约专属" in mots,
                "differs_from_normal": norm_files != oath_files,
            })
            continue

        skin_changed = False
        for fn in LANG_FILES:
            lp = skin_dir / fn
            if not lp.is_file():
                continue
            ld = json.loads(lp.read_text(encoding="utf-8-sig"))
            changed = False

            mots = ld.get("motions") or {}
            if "誓约模式全动作" in mots:
                del mots["誓约模式全动作"]
                changed = True

            kt = (ld.get("controllers") or {}).get("key_trigger")
            if isinstance(kt, dict) and isinstance(kt.get("items"), list):
                old_items = kt["items"]
                new_items = [
                    it for it in old_items
                    if it.get("down_mtn") != "誓约模式全动作" and it.get("up_mtn") != "誓约模式全动作"
                ]
                if len(new_items) != len(old_items):
                    kt["items"] = new_items
                    changed = True

            if changed:
                lp.write_text(json.dumps(ld, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                files_modified += 1
                skin_changed = True

        if skin_changed:
            cleaned_skins.append(rel)
        else:
            already_clean_non_oath += 1

    report = {
        "oath_skins_kept": len(oath_skins),
        "oath_skins_all_differ_from_normal": all(x["differs_from_normal"] for x in oath_skins),
        "non_oath_skins_cleaned": len(cleaned_skins),
        "files_modified": files_modified,
        "non_oath_already_clean": already_clean_non_oath,
        "cleaned_skins": cleaned_skins,
        "oath_skins": oath_skins,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("cleaned_skins", "oath_skins")}, ensure_ascii=False, indent=2))
    print(f"Cleaned {len(cleaned_skins)} non-oath skins ({files_modified} files). Kept {len(oath_skins)} real oath skins.")


if __name__ == "__main__":
    main()
