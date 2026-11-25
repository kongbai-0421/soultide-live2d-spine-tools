r"""Fix verified Spine background/submodel Z-order inversions against official Unity BgPrefabs.

Confirmed fixes across all 163 Spine packages (3 languages synced per skin):
1. 阿拉芙/春华萌动: move `bj_01_2` (Unity ord=1, dfs=11, behind Person ord=3) from `+2` -> `-2`.
2. 叶月雪/夏光幻雪: swap `bg_mid` (-2) and `bj_01` (-1) -> `bj_01` (-2), `bg_mid` (-1).
3. 爱莉莎/完美篇章: swap `bg_mid` (-2) and `bj_03` (-1) -> `bj_03` (-2), `bg_mid` (-1).
4. 薇姬娜/皎月环心: swap `bg_mid` (-2) and `bj_04` (-1) -> `bj_04` (-2), `bg_mid` (-1).
5. 迦瓦娜/辉芒之子: swap `bg_mid` (-2) and `bj_09` (-1) -> `bj_09` (-2), `bg_mid` (-1).

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

SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
REPORT_PATH = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本\spine_bg_layer_fix_report.json")
LANG_FILES = (".config.json", "config_en.config.json", "config_ja.config.json")

# Map: (doll, skin) -> { submodel_folder: target_z_order }
LAYER_FIXES: dict[tuple[str, str], dict[str, int]] = {
    ("阿拉芙", "春华萌动"): {"bj_01_2": -2},
    ("叶月雪", "夏光幻雪"): {"bj_01": -2, "bg_mid": -1},
    ("爱莉莎", "完美篇章"): {"bj_03": -2, "bg_mid": -1},
    ("薇姬娜", "皎月环心"): {"bj_04": -2, "bg_mid": -1},
    ("迦瓦娜", "辉芒之子"): {"bj_09": -2, "bg_mid": -1},
}


def rewrite_add_submodel_cmd(cmd: str, overrides: dict[str, int]) -> str:
    if not cmd:
        return cmd
    add_entries: list[tuple[int, int, str]] = []  # (order, orig_idx, cmd_str)
    other_cmds: list[str] = []

    for idx, seg in enumerate(cmd.split(";")):
        s = seg.strip()
        if not s:
            continue
        toks = s.split()
        if len(toks) == 3 and toks[0] == "add_submodel":
            sub_rel = toks[1]
            folder = sub_rel.split("/")[1] if "/" in sub_rel else sub_rel
            order = overrides.get(folder, int(toks[2]))
            add_entries.append((order, idx, f"add_submodel {sub_rel} {order}"))
        else:
            other_cmds.append(s)

    # Sort add_submodel cleanly from furthest back (-3) to furthest front (+3)
    add_entries.sort(key=lambda x: (x[0], x[1]))
    # Validate zero duplicate Z orders!
    orders = [x[0] for x in add_entries]
    if len(orders) != len(set(orders)):
        raise AssertionError(f"Duplicate Z-orders after rewrite: {add_entries}")

    return "; ".join([x[2] for x in add_entries] + other_cmds)


def main() -> None:
    results: list[dict[str, Any]] = []
    for (doll, skin), overrides in LAYER_FIXES.items():
        sdir = SPINE_ROOT / doll / skin
        if not (sdir / ".config.json").is_file():
            raise FileNotFoundError(f"Missing Spine skin: {sdir}")

        before_cmd = None
        after_cmd = None
        langs_updated: list[str] = []

        for lfn in LANG_FILES:
            cp = sdir / lfn
            if not cp.is_file():
                continue
            data = json.loads(cp.read_text(encoding="utf-8-sig"))
            mots = data.get("motions") or {}

            for grp in ("start", "Start", "reload_bg"):
                for item in mots.get(grp) or []:
                    if "command" in item and "add_submodel" in item["command"]:
                        if lfn == ".config.json" and grp in ("start", "Start") and before_cmd is None:
                            before_cmd = item["command"]
                        new_c = rewrite_add_submodel_cmd(item["command"], overrides)
                        item["command"] = new_c
                        if lfn == ".config.json" and grp in ("start", "Start") and after_cmd is None:
                            after_cmd = new_c

            cp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            langs_updated.append(lfn)

        results.append({
            "skin": f"{doll}/{skin}",
            "overrides": overrides,
            "langs_updated": langs_updated,
            "before_start_command": before_cmd,
            "after_start_command": after_cmd,
        })

    report = {"fixed_skins_count": len(results), "results": results}
    write_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
