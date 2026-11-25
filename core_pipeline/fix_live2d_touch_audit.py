"""Apply calibrated HitAreas & Tap躯干 fixes to the 10 flagged Live2D packages."""

from __future__ import annotations

import json
from pathlib import Path

from soultide_common import write_json

LIVE2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")

LANG_FILES = (".model3.json", "model_en.model3.json", "model_ja.model3.json")

BODY2_PACKAGES = (
    "安德莉亚/伴光同辉",
    "安德莉亚/键上舞影",
    "安德莉亚/麦芒气泡",
    "欧若拉/仙宫新岁",
    "欧若拉/平安冬夜",
    "欧若拉/童话心绘",
    "爱莉莎/完美篇章",
)


def main() -> None:
    modified: list[str] = []

    # 1. 伊汐尔/原皮_变身: bind artist-authored HitArea* touch boxes
    p_yxy = LIVE2D_ROOT / "伊汐尔/原皮_变身"
    yxy_hits = [
        {"Name": "头", "Id": "HitArea2", "Motion": "Tap头"},
        {"Name": "左手", "Id": "HitArea3", "Motion": "Tap手"},
        {"Name": "右手", "Id": "HitArea", "Motion": "Tap手"},
        {"Name": "胸", "Id": "HitArea4", "Motion": "Tap胸"},
        {"Name": "臀部", "Id": "HitArea5", "Motion": "Tap臀部"},
    ]
    for fn in LANG_FILES:
        lp = p_yxy / fn
        d = json.loads(lp.read_text(encoding="utf-8"))
        d["HitAreas"] = yxy_hits
        write_json(lp, d)
    modified.append("伊汐尔/原皮_变身")

    # 2. 和铃/原皮 & 和铃/古锦新韵: bind artist-authored HitArea2 for 臀部
    for rel in ("和铃/原皮", "和铃/古锦新韵"):
        pkg = LIVE2D_ROOT / rel
        for fn in LANG_FILES:
            lp = pkg / fn
            d = json.loads(lp.read_text(encoding="utf-8"))
            new_hits = []
            for h in d.get("HitAreas") or []:
                if h.get("Name") == "臀部":
                    new_hits.append({"Name": "臀部", "Id": "HitArea2", "Motion": "Tap臀部"})
                else:
                    new_hits.append(dict(h))
            d["HitAreas"] = new_hits
            write_json(lp, d)
        modified.append(rel)

    # 3. 7 Body2 packages: redistribute Tap躯干 -> Tap臀部/Tap胸/Tap手/Tap头 and remove Body2
    core_taps = ("Tap臀部", "Tap胸", "Tap手", "Tap头")
    for rel in BODY2_PACKAGES:
        pkg = LIVE2D_ROOT / rel
        for fn in LANG_FILES:
            lp = pkg / fn
            raw_txt = lp.read_text(encoding="utf-8")
            assert "Tap躯干:" not in raw_txt, f"Unexpected Choice NextMtn Tap躯干: in {lp}"
            d = json.loads(raw_txt)
            mots = d["FileReferences"]["Motions"]
            if "Tap躯干" in mots:
                torso_items = mots.pop("Tap躯干")
                for t_item in torso_items:
                    sig = (t_item.get("File", ""), t_item.get("Sound", ""))
                    eligible = [
                        g for g in core_taps
                        if not any((x.get("File", ""), x.get("Sound", "")) == sig for x in mots.get(g, []))
                    ]
                    dst_g = min(eligible or core_taps, key=lambda g: len(mots.get(g, [])))
                    mots.setdefault(dst_g, []).append(dict(t_item))
            d["HitAreas"] = [h for h in (d.get("HitAreas") or []) if h.get("Id") != "Body2"]
            write_json(lp, d)
        modified.append(rel)

    print("Modified packages:", len(modified))
    for m in modified:
        print(" ", m)


if __name__ == "__main__":
    main()
