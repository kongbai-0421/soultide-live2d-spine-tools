r"""Batch-fix all Live2D and Spine KeyTrigger / menu / reload_bg configs in place.

Fixes 4 Live2DViewerEX bytecode-verified root causes across the entire fleet:
1. Spine (all 163 skins / 489 configs): Remap lowercase ASCII (97..103, 104, 109, 110, 114)
   and Unity KeyCode.F3 (284) to Windows Virtual-Key codes polled by `lwtray.exe`
   `GetAsyncKeyState`:
   - A..G = 65..71 (`闲聊与问答`, `头`, `左手`, `右手`, `胸`, `腿`, `足`)
   - H = 72 (`背景菜单`), M = 77 (`誓约模式全动作`), N = 78 (`普通模式全动作`),
     R = 82 (`reload_bg`), F3 = 114 (`背景菜单`)
2. Spine dressed skins (109 skins / 327 configs): Fix `背景菜单` choice `next_mtn` from
   invalid numeric indices (`背景开关:0` / `背景开关:1`) to exact motion names
   (`背景开关:hide_bg` / `背景开关:show_bg`).
3. Spine dressed skins (109 skins / 327 configs): Rebuild `reload_bg` so every current
   submodel (and any `touch_only.config.json`) is removed FIRST and then all current
   submodels are added in exact `start` order (zero stale v1 paths).
4. Live2D oath-ring skins (all configs with `ParamRingOn` expressions & `Input: 82`):
   Inject motion group `"誓约戒指切换"` (`MotionDuration: 50`, `PostCommand: "next_exp"`,
   `File: "motions/menu_silent.motion3.json"`) and bind `{"Input": 82, "DownMtn": "誓约戒指切换"}`
   (replacing invalid `{"Input": 82, "Name": "佩戴誓约戒指"}`).

Idempotent: safe to re-run at any time. Does NOT modify `soultide.db` or `.lpk` files.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

TOOLS_SCRIPT_DIR = Path(__file__).resolve().parent
if str(TOOLS_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_SCRIPT_DIR))

import add_spine_bg_toggle

LIVE2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
REPORT_PATH = TOOLS_SCRIPT_DIR / "key_trigger_fix_report.json"

RING_TOGGLE_MOTION = [
    {
        "Name": "toggle_ring",
        "File": "motions/menu_silent.motion3.json",
        "FadeIn": 0,
        "FadeOut": 0,
        "MotionDuration": 50,
        "PostCommand": "next_exp",
    }
]

LEGACY_SPINE_VK_MAP: dict[int, int] = {
    97: 65,   # 'a' -> VK_A
    98: 66,   # 'b' -> VK_B
    99: 67,   # 'c' -> VK_C
    100: 68,  # 'd' -> VK_D
    101: 69,  # 'e' -> VK_E
    102: 70,  # 'f' -> VK_F
    103: 71,  # 'g' -> VK_G
    104: 72,  # 'h' -> VK_H
    109: 77,  # 'm' -> VK_M
    110: 78,  # 'n' -> VK_N
    284: 114, # Unity KeyCode.F3 -> VK_F3
}


def fix_live2d_fleet() -> dict[str, Any]:
    scanned = 0
    submodel_skipped = 0
    ring_fixed = 0
    files_written = 0
    fixed_samples: list[str] = []

    for root, _dirs, files in os.walk(LIVE2D_ROOT):
        root_p = Path(root)
        is_sub = "submodels" in root_p.relative_to(LIVE2D_ROOT).parts
        for fn in sorted(files):
            if not fn.endswith(".model3.json"):
                continue
            fp = root_p / fn
            if is_sub:
                submodel_skipped += 1
                continue
            scanned += 1
            data = json.loads(fp.read_text(encoding="utf-8-sig"))
            fr = data.get("FileReferences") or {}
            exps = fr.get("Expressions") or []
            mots = fr.setdefault("Motions", {})
            ctrls = data.setdefault("Controllers", {})
            kt = ctrls.setdefault("KeyTrigger", {"Enabled": True, "Items": []})
            items = kt.get("Items") or []

            changed = False
            has_r_key = any(isinstance(it, dict) and it.get("Input") == 82 for it in items)
            has_ring_exps = len(exps) >= 2 and any(
                "ring_on" in (e.get("File") or "") for e in exps
            )

            if has_r_key or has_ring_exps:
                silent_p = root_p / "motions" / "menu_silent.motion3.json"
                if not silent_p.is_file():
                    raise FileNotFoundError(f"Missing menu_silent.motion3.json for {fp}")
                if mots.get("誓约戒指切换") != RING_TOGGLE_MOTION:
                    mots["誓约戒指切换"] = [dict(RING_TOGGLE_MOTION[0])]
                    changed = True

                new_items: list[dict[str, Any]] = []
                r_added = False
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    if it.get("Input") == 82:
                        if not r_added:
                            new_it = {"Input": 82, "DownMtn": "誓约戒指切换"}
                            if it != new_it:
                                changed = True
                            new_items.append(new_it)
                            r_added = True
                        else:
                            changed = True
                    else:
                        new_items.append(it)
                if not r_added:
                    new_items.append({"Input": 82, "DownMtn": "誓约戒指切换"})
                    changed = True

                if new_items != items:
                    kt["Items"] = new_items
                    changed = True
                ring_fixed += 1
                if len(fixed_samples) < 10:
                    fixed_samples.append(str(fp.relative_to(LIVE2D_ROOT)))

            if changed:
                fp.write_text(
                    json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                files_written += 1

    return {
        "main_configs_scanned": scanned,
        "submodel_configs_skipped": submodel_skipped,
        "ring_configs_verified_or_fixed": ring_fixed,
        "files_written": files_written,
        "sample_ring_configs": fixed_samples,
    }


def fix_spine_fleet() -> dict[str, Any]:
    scanned = 0
    files_written = 0
    remapped_items = 0

    for root, _dirs, files in os.walk(SPINE_ROOT):
        root_p = Path(root)
        if "submodels" in root_p.relative_to(SPINE_ROOT).parts:
            continue
        for fn in sorted(files):
            if not fn.endswith(".config.json"):
                continue
            fp = root_p / fn
            scanned += 1
            data = json.loads(fp.read_text(encoding="utf-8-sig"))
            kt = data.setdefault("controllers", {}).setdefault(
                "key_trigger", {"enabled": True, "items": []}
            )
            changed = False
            if kt.get("enabled") is not True:
                kt["enabled"] = True
                changed = True

            old_items = kt.get("items") or []
            new_items: list[dict[str, Any]] = []
            seen_inputs: set[int] = set()
            for it in old_items:
                if not isinstance(it, dict):
                    continue
                inp = it.get("input")
                dm = it.get("down_mtn")
                new_inp = inp
                if dm == "reload_bg" and inp == 114:
                    new_inp = 82  # ASCII 'r' (114 == VK_F3) -> VK_R (82)
                elif inp in LEGACY_SPINE_VK_MAP:
                    new_inp = LEGACY_SPINE_VK_MAP[inp]
                if new_inp != inp:
                    remapped_items += 1
                    changed = True
                if new_inp in seen_inputs:
                    changed = True
                    continue
                seen_inputs.add(new_inp)
                new_it = dict(it)
                new_it["input"] = new_inp
                new_items.append(new_it)

            if new_items != old_items:
                kt["items"] = new_items
                changed = True

            if changed:
                fp.write_text(
                    json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                files_written += 1

    # Re-run add_spine_bg_toggle to update 背景菜单 (:hide_bg / :show_bg),
    # clean reload_bg (remove-before-add, 0 stale v1 paths), and enforce F3(114) & H(72)
    add_spine_bg_toggle.main()
    bg_report = json.loads(add_spine_bg_toggle.REPORT_PATH.read_text(encoding="utf-8"))

    return {
        "main_configs_scanned": scanned,
        "vk_remapped_files_written": files_written,
        "vk_items_remapped": remapped_items,
        "bg_toggle_sync": {
            "skins_updated": bg_report["skins_updated"],
            "counts": bg_report["counts"],
            "touch_only_written": bg_report["touch_only_written"],
        },
    }


def main() -> None:
    l2d_res = fix_live2d_fleet()
    sp_res = fix_spine_fleet()
    report = {
        "live2d": l2d_res,
        "spine": sp_res,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== KEY TRIGGER FIX REPORT ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
