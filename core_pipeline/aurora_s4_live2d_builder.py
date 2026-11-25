"""Build a complete Live2DViewerEX package for Aurora's '童话心绘' (Aurora_S4) Live2D model."""

from __future__ import annotations

import json
import re
from pathlib import Path

from soultide_common import CDN_ROOT, LuaTableRepo, extract_wav_bytes, load_ab, write_json

SOUL_ID = 20010019
SKIN_RES_IDS = (20021941, 20021940)
OUT_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d\欧若拉\童话心绘")
BATCH35_AB = CDN_ROOT / "20_live2d/live2d_resources/batch35.ab"
CV_AURORA_AB = CDN_ROOT / "06_sounds/cv/_aurora.ab"


# Map SoulTide CfgSoulActionGroupTable Type -> Live2DViewerEX Motion Group
TYPE_TO_GROUP = {
    201: "Morning",
    202: "Sad",
    211: "Noon",
    212: "Sad",
    221: "Evening",
    222: "Sad",
    231: "Midnight",
    232: "Sad",
    401: "Greeting",
    502: "Return",
    503: "Return",
    601: "Festival",
    602: "Festival",
    603: "Festival",
    605: "Festival",
    701: "Greeting",
    702: "Greeting",
    801: "Tap头",
    901: "Tap手",
    1001: "Tap腰臀",
    1101: "Tap胸",
    1201: "Greeting",
    1301: "Gift",
    1302: "Gift",
    1303: "Gift",
    1311: "Gift",
    1312: "Gift",
    1313: "Gift",
    1314: "Gift",
    1315: "Gift",
    1321: "Food",
    1322: "Food",
    1323: "Food",
    1324: "Food",
    1325: "Food",
    1326: "Food",
    1327: "Food",
    1328: "Food",
    1329: "Food",
    1401: "Tap足",
    1402: "Tap足",
    1403: "Tap足",
    1404: "Tap足",
    1409: "TouchSpecial",
    1411: "Festival",
    1412: "Festival",
    1413: "Festival",
    1414: "Festival",
    1415: "Festival",
    1601: "System",
    1611: "System",
    1801: "System",
    1901: "System",
    2001: "System",
    2101: "System",
    2201: "System",
    2401: "Festival",
}


def build_aurora_s4_live2d(out_dir: Path = OUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_dir = out_dir / "Textures"
    mot_dir = out_dir / "motions"
    aud_dir = out_dir / "audio"
    exp_dir = out_dir / "expressions"
    for d in (tex_dir, mot_dir, aud_dir, exp_dir):
        d.mkdir(parents=True, exist_ok=True)
    for old_w in aud_dir.glob("*.wav"):
        old_w.unlink()

    # 1. Extract Live2D core assets (.moc3, .physics3.json, texture, all 80 motions)
    b35 = load_ab(BATCH35_AB)
    motions_by_stem: dict[str, str] = {}  # lower_stem -> relative path e.g. "motions/foo.motion3.json"
    moc_written = False
    phys_written = False
    tex_written = False

    for cpath, ptr in sorted((b35.container or {}).items()):
        low = cpath.lower()
        if "live2d_aurora_s4/" not in low:
            continue
        if low.endswith("/moc/aurora.asset"):
            moc_bytes = bytes(ptr.read_typetree()["_bytes"])
            if not moc_bytes.startswith(b"MOC3"):
                raise ValueError("Extracted aurora.asset does not start with MOC3 magic")
            (out_dir / "Aurora.moc3").write_bytes(moc_bytes)
            moc_written = True
        elif low.endswith("/moc/aurora.physics3.json"):
            txt = ptr.read().m_Script
            (out_dir / "Aurora.physics3.json").write_text(txt, encoding="utf-8")
            phys_written = True
        elif low.endswith("aurora_texture_00.png"):
            img = ptr.read().image.convert("RGBA")
            img.save(tex_dir / "Aurora_texture_00.png", "PNG")
            tex_written = True
        elif low.endswith(".motion3.json"):
            raw_name = Path(cpath).name
            stem_low = raw_name[:-len(".motion3.json")].lower()
            # Keep clean filename preserving extracted stem
            (mot_dir / raw_name).write_text(ptr.read().m_Script, encoding="utf-8")
            motions_by_stem[stem_low] = f"motions/{raw_name}"

    assert moc_written and phys_written and tex_written, "Missing core Live2D assets in batch35.ab"

    # Extract Drawable IDs from Aurora.moc3 to validate HitAreas strictly
    moc_raw = (out_dir / "Aurora.moc3").read_bytes()

    # 2. Index AudioClips in _aurora.ab
    cv_env = load_ab(CV_AURORA_AB)
    clip_by_lower: dict[str, tuple[str, object]] = {}
    for obj in cv_env.objects:
        if obj.type.name == "AudioClip":
            cname = obj.peek_name()
            clip_by_lower[cname.lower()] = (cname, obj)

    # 3. Collect ALL Aurora ActionGroups (SoulId = 20010019), resolving SoulResId=20021941 skin overrides
    repo = LuaTableRepo()
    extracted_wavs: dict[str, str] = {}  # stem_low -> rel "audio/<cname>.wav"
    motion_groups: dict[str, list[dict]] = {
        "Idle": [],
        "Start": [],
        "Tap头": [],
        "Tap胸": [],
        "Tap手": [],
        "Tap腰臀": [],
        "Tap足": [],
        "Tap": [],
        "Morning": [],
        "Noon": [],
        "Evening": [],
        "Midnight": [],
        "Greeting": [],
        "TouchSpecial": [],
        "Festival": [],
        "Gift": [],
        "Food": [],
        "Return": [],
        "System": [],
        "Sad": [],
        "ExtraMotions": [],
    }

    def ensure_wav(stem: str) -> str:
        low = stem.lower()
        if not low:
            return ""
        if low in extracted_wavs:
            return extracted_wavs[low]
        if low not in clip_by_lower:
            raise KeyError(f"AudioClip '{stem}' not found in {CV_AURORA_AB}")
        cname, obj = clip_by_lower[low]
        wav_bytes = extract_wav_bytes(obj)
        rel = f"audio/{cname}.wav"
        (out_dir / rel).write_bytes(wav_bytes)
        extracted_wavs[low] = rel
        return rel

    # Track per-group (motion_rel, sound_rel, text) deduplication so identical triplets aren't duplicated
    group_seen: dict[str, set[tuple[str, str, str]]] = {k: set() for k in motion_groups}
    used_motion_stems: set[str] = set()
    included_sound_stems: set[str] = set()

    def add_entry(grp: str, name: str, mot_rel: str, cv_id: int | None) -> None:
        if grp not in motion_groups:
            motion_groups[grp] = []
            group_seen[grp] = set()
        cv_info = repo.resolve_cv(cv_id)
        snd_rel = ensure_wav(cv_info["sound_stem"]) if cv_info["sound_stem"] else ""
        text = cv_info["text"]
        sig = (mot_rel, snd_rel, text)
        if sig in group_seen[grp]:
            return
        group_seen[grp].add(sig)
        used_motion_stems.add(Path(mot_rel).name.replace(".motion3.json", "").lower())
        if cv_info["sound_stem"]:
            included_sound_stems.add(cv_info["sound_stem"].lower())
        entry: dict = {"Name": name, "File": mot_rel}
        if snd_rel:
            entry["Sound"] = snd_rel
        if text:
            entry["Text"] = text
            entry["TextDuration"] = cv_info["duration_ms"]
        motion_groups[grp].append(entry)

    # 3A. Keep ONLY Aurora_S4 skin (20021941 / 20021940) actions on body touch areas!
    # All base-skin lines and remaining action groups go exclusively to the Voice Menu + named archives.
    SKIN_TOUCH_TYPE_TO_GROUP = {
        801: "Tap头",
        901: "Tap手",
        1001: "Tap臀部",
        1101: "Tap胸",
        1401: "Tap头",
        1402: "Tap头",
        1403: "Tap头",
        1404: "Tap头",
    }
    OTHER_VOICE_ENTRIES: list[tuple[str, str, dict]] = []  # (cat_label, sub_label, entry)

    def make_entry(name: str, mot_rel: str, cv_id: int | None) -> dict:
        cv_info = repo.resolve_cv(cv_id)
        snd_rel = ensure_wav(cv_info["sound_stem"]) if cv_info["sound_stem"] else ""
        text = cv_info["text"]
        used_motion_stems.add(Path(mot_rel).name.replace(".motion3.json", "").lower())
        if cv_info["sound_stem"]:
            included_sound_stems.add(cv_info["sound_stem"].lower())
        e: dict = {"Name": name, "File": mot_rel}
        if snd_rel:
            e["Sound"] = snd_rel
        if text:
            e["Text"] = text
            e["TextDuration"] = cv_info["duration_ms"]
        return e

    skin_seen_aids: set[int] = set()
    for gid, body in sorted(repo.action_groups.items()):
        if not re.search(rf"SoulId\s*=\s*{SOUL_ID}\b", body):
            continue
        gtype = int(re.search(r"Type\s*=\s*(\d+)", body).group(1))
        if gtype in (101, 102, 103):
            continue
        target_group = TYPE_TO_GROUP.get(gtype, "Greeting")

        m_res = re.search(r"SoulResId\s*=\s*\{([^}]+)\}", body)
        m_ract = re.search(r"SoulResAction\s*=\s*\{(.*?)\n\t\t\}", body, re.S)
        skin_aids: list[int] = []
        if m_res and m_ract:
            rids = [int(x) for x in re.findall(r"\d+", m_res.group(1))]
            sub_lists = re.findall(r"\{([^}]*)\}", m_ract.group(1))
            for srid in SKIN_RES_IDS:
                if srid in rids:
                    idx = rids.index(srid)
                    if idx < len(sub_lists):
                        skin_aids = [int(x) for x in re.findall(r"\d+", sub_lists[idx])]
                        break
        m_mood = re.search(r"MoodActionID\s*=\s*\{(.*?)\n\t\t\}", body, re.S)
        base_aids = [int(x) for x in re.findall(r"\d{6,}", m_mood.group(1))] if m_mood else []

        # Route ONLY skin_aids to touch groups (头/手/胸/臀部/躯干), never mix base_aids into body touches
        for aid in skin_aids:
            act = repo.action_map.get(aid)
            if not act or not act["body_action"]:
                continue
            mot_rel = motions_by_stem.get(act["body_action"].lower(), "")
            if not mot_rel:
                continue
            skin_seen_aids.add(aid)
            touch_grp = SKIN_TOUCH_TYPE_TO_GROUP.get(gtype)
            if touch_grp:
                add_entry(touch_grp, f"act_{aid}", mot_rel, act["cv"])
            else:
                # Daily/greeting/festival/gift skin overrides -> Tap躯干 AND named group
                add_entry("Tap躯干", f"act_{aid}", mot_rel, act["cv"])
                add_entry(target_group, f"act_{aid}", mot_rel, act["cv"])

        # Base-skin lines go ONLY into named archive/time/menu groups (NOT HitArea touch groups)
        base_dst = "Archive" if gtype in SKIN_TOUCH_TYPE_TO_GROUP else target_group
        for aid in base_aids:
            if aid in skin_seen_aids:
                continue
            act = repo.action_map.get(aid)
            if not act or not act["body_action"]:
                continue
            mot_rel = motions_by_stem.get(act["body_action"].lower(), "")
            if not mot_rel:
                continue
            add_entry(base_dst, f"act_{aid}", mot_rel, act["cv"])

    # 3B. Include any Aurora_S4 skin rows in CfgSoulActionTable not in ActionGroups (e.g. 191701209, 191400111)
    for aid, act in sorted(repo.action_map.items()):
        if act["soul_id"] != SOUL_ID or aid in skin_seen_aids:
            continue
        ba = act["body_action"] or ""
        cv_info = repo.resolve_cv(act["cv"])
        stem_low = cv_info["sound_stem"].lower()
        if "dress1" in stem_low or "dress2" in stem_low or "dress4" in stem_low:
            continue
        if not ("fashion3" in ba.lower() or "dress3" in stem_low or "after_marriage" in stem_low):
            continue
        mot_rel = motions_by_stem.get(ba.lower(), "")
        if mot_rel:
            skin_seen_aids.add(aid)
            dst_grp = "Tap躯干" if "gift" in stem_low else "Tap头"
            add_entry(dst_grp, f"act_{aid}", mot_rel, act["cv"])

    # 3C. Include remaining Aurora_* general CV lines (ONLY into categorized menu/archive groups, NEVER into Tap头/手/胸/臀部/躯干)
    fallback_motion_map = [
        ("touch_head", "Archive", "ch_aurora@live2d_greet2"),
        ("touch_breast", "Archive", "ch_aurora@live2d_insert02"),
        ("touch_hand", "Archive", "ch_aurora@live2d_fashion3_3"),
        ("touch_hip", "Archive", "ch_aurora@live2d_insert05_2"),
        ("touch_reaction", "TouchSpecial", "ch_aurora@live2d_insert02"),
        ("touch_locked", "Sad", "ch_aurora@live2d_sad_complete"),
        ("touch_unhappy", "Sad", "ch_aurora@live2d_greet_sad1"),
        ("about_", "Archive", "ch_aurora@live2d_greet2"),
        ("wedding", "Archive", "ch_aurora@live2d_fashion3_4"),
        ("firstmeeting", "Archive", "ch_aurora@live2d_greet1"),
        ("after_marriage", "Archive", "ch_aurora@live2d_fashion3_3"),
        ("favorite", "Archive", "ch_aurora@live2d_joyful_complete"),
        ("hate", "Archive", "ch_aurora@live2d_sad_complete"),
        ("shy", "Archive", "ch_aurora@live2d_greet2_2"),
        ("smile", "Archive", "ch_aurora@live2d_joyful"),
        ("aurora_sad", "Archive", "ch_aurora@live2d_sad"),
        ("mad", "Archive", "ch_aurora@live2d_angry"),
        ("amazed", "Archive", "ch_aurora@live2d_greet2_1"),
        ("hurt", "Battle", "ch_aurora@live2d_angry_complete"),
        ("attack", "Battle", "ch_aurora@live2d_serious"),
        ("skill", "Battle", "ch_aurora@live2d_serious_complete"),
        ("striked", "Battle", "ch_aurora@live2d_sad_complete"),
        ("strike", "Battle", "ch_aurora@live2d_serious_loop"),
        ("win", "Battle", "ch_aurora@live2d_joyful_complete_1"),
        ("defeat", "Battle", "ch_aurora@live2d_sad_loop"),
        ("dead", "Battle", "ch_aurora@live2d_sad_complete"),
        ("morning", "Morning", "ch_aurora@live2d_greet1"),
        ("noon", "Noon", "ch_aurora@live2d_greet2"),
        ("evening", "Evening", "ch_aurora@live2d_greet3"),
        ("greet", "Festival", "ch_aurora@live2d_greet2_2"),
    ]
    for cname_low, (cname, _obj) in sorted(clip_by_lower.items()):
        if not cname_low.startswith("aurora_"):
            continue
        if any(k in cname_low for k in ("dress1", "dress2", "dress4")):
            continue
        if cname_low in included_sound_stems:
            continue
        matched_cv_id = None
        for cid, info in repo.cv_map.items():
            srel = repo.sound_map.get(info["sound_id"] or -1, "")
            if srel and Path(srel).stem.lower() == cname_low:
                matched_cv_id = cid
                break
        target_grp = "Archive"
        mot_stem = "ch_aurora@live2d_greet2"
        for kw, grp, mstem in fallback_motion_map:
            if kw in cname_low:
                target_grp, mot_stem = grp, mstem
                break
        mot_rel = motions_by_stem.get(mot_stem, next(iter(motions_by_stem.values())))
        if matched_cv_id is not None:
            add_entry(target_grp, f"cv_{cname_low}", mot_rel, matched_cv_id)
        else:
            snd_rel = ensure_wav(cname)
            if target_grp not in motion_groups:
                motion_groups[target_grp] = []
                group_seen[target_grp] = set()
            motion_groups[target_grp].append({"Name": f"cv_{cname_low}", "File": mot_rel, "Sound": snd_rel})
            included_sound_stems.add(cname_low)

    # 4. Keep ONLY ONE Idle motion (standby2) so idle animations never overwrite each other
    idle_candidates = [
        ("standby2", "ch_aurora@live2d_standby2"),
    ]
    for nm, st in idle_candidates:
        if st in motions_by_stem:
            used_motion_stems.add(st)
            motion_groups["Idle"].append({"Name": nm, "File": motions_by_stem[st]})

    # Use skin morning/noon/evening greetings as Start pool
    for item in motion_groups["Morning"][:1] + motion_groups["Noon"][:1] + motion_groups["Evening"][:1]:
        start_item = dict(item)
        motion_groups["Start"].append(start_item)

    # Remove unused Tap腰臀 / Tap足 placeholders and keep clean 5 skin touch groups + global Tap menu
    # 5. Bind ALL remaining extracted .motion3.json into ExtraMotions so 80/80 are accessible
    for stem_low, rel in sorted(motions_by_stem.items()):
        if stem_low not in used_motion_stems:
            motion_groups["ExtraMotions"].append({"Name": stem_low, "File": rel})

    # 5B. Build interactive Choices Voice & Motion Menu (triggered by global Tap touch event OR KeyTrigger '1'/'M'/'V')
    # Create a dedicated 0-curve silent motion so opening/navigating the menu NEVER triggers greet2 or any other animation
    menu_silent_rel = "motions/menu_silent.motion3.json"
    menu_silent_motion = {
        "Version": 3,
        "Meta": {
            "Duration": 0.033,
            "Fps": 30.0,
            "Loop": False,
            "AreBeziersRestricted": True,
            "CurveCount": 0,
            "TotalSegmentCount": 0,
            "TotalPointCount": 0,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": [],
    }
    write_json(out_dir / menu_silent_rel, menu_silent_motion)
    menu_prompt_mot = menu_silent_rel
    menu_categories = [
        ("Menu_Cat_Skin", "童话心绘 · 皮肤全语音与动作", ["Tap头", "Tap手", "Tap胸", "Tap臀部", "Tap躯干"]),
        ("Menu_Cat_Time", "早/午/晚/深夜 时段问候", ["Morning", "Noon", "Evening", "Midnight"]),
        ("Menu_Cat_Social", "日常问候 / 节日 / 回归 / 系统", ["Greeting", "Festival", "Return", "System", "TouchSpecial", "Sad"]),
        ("Menu_Cat_Gift", "礼物与投喂互动", ["Gift", "Food"]),
        ("Menu_Cat_Archive", "誓约与人物档案语音", ["Archive"]),
        ("Menu_Cat_Battle", "战斗语音与技能动作", ["Battle"]),
        ("Menu_Cat_Motion", "纯动作预览 (其余Live2D动作)", ["ExtraMotions"]),
    ]

    play_item_counter = 0
    category_root_choices: list[dict] = []
    menu_extra_groups: dict[str, list[dict]] = {}

    for cat_id, cat_title, src_grps in menu_categories:
        cat_entries: list[tuple[str, dict]] = []
        cat_seen: set[tuple[str, str, str]] = set()
        for gname in src_grps:
            for item in motion_groups.get(gname, []):
                sig = (item["File"], item.get("Sound", ""), item.get("Text", ""))
                if sig in cat_seen:
                    continue
                cat_seen.add(sig)
                txt = (item.get("Text") or "").strip().replace("\n", " ")
                snd_stem = Path(item["Sound"]).stem if item.get("Sound") else Path(item["File"]).stem.replace("CH_Aurora@Live2D_", "")
                if txt:
                    btn_label = f"{txt[:20]}…" if len(txt) > 20 else txt
                else:
                    btn_label = snd_stem[:24]
                cat_entries.append((btn_label, item))
        if not cat_entries:
            continue

        # Paginate at 6 items per page so EX dialog popup stays clean & scrollable
        per_page = 6
        total_pages = (len(cat_entries) + per_page - 1) // per_page
        for pg in range(total_pages):
            page_grp = cat_id if pg == 0 else f"{cat_id}_p{pg + 1}"
            chunk = cat_entries[pg * per_page:(pg + 1) * per_page]
            choices_list: list[dict] = []
            for btn_label, item in chunk:
                play_item_counter += 1
                play_grp = f"MenuPlay_{play_item_counter:03d}"
                play_entry = dict(item)
                menu_extra_groups[play_grp] = [play_entry]
                choices_list.append({"Text": btn_label, "NextMtn": play_grp})
            if pg + 1 < total_pages:
                choices_list.append({"Text": f"下一页 ({pg + 2}/{total_pages}) ▶", "NextMtn": f"{cat_id}_p{pg + 2}"})
            if pg > 0:
                prev_grp = cat_id if pg == 1 else f"{cat_id}_p{pg}"
                choices_list.append({"Text": f"◀ 上一页 ({pg}/{total_pages})", "NextMtn": prev_grp})
            choices_list.append({"Text": "« 返回主语音菜单", "NextMtn": "语音菜单"})
            menu_extra_groups[page_grp] = [{
                "Name": page_grp,
                "File": menu_prompt_mot,
                "FadeIn": 0,
                "FadeOut": 0,
                "Text": f"【{cat_title}】({pg + 1}/{total_pages}) 点击选项立即播放：",
                "TextDuration": 60000,
                "Choices": choices_list,
            }]
        category_root_choices.append({"Text": f"{cat_title} ({len(cat_entries)})", "NextMtn": cat_id})

    menu_root_entry = {
        "Name": "语音菜单",
        "File": menu_prompt_mot,
        "FadeIn": 0,
        "FadeOut": 0,
        "Text": "请选择要播放的欧若拉语音与动作分类（按 1 / M / V 或点击空白裙摆处呼出）：",
        "TextDuration": 60000,
        "Choices": category_root_choices,
    }
    # Bind both global 'Tap' (non-HitArea touch event) and named '语音菜单' (KeyTrigger)
    motion_groups["Tap"] = [dict(menu_root_entry, Name="tap_voice_menu")]
    motion_groups["语音菜单"] = [dict(menu_root_entry)]
    motion_groups.update(menu_extra_groups)

    # Drop empty groups cleanly
    motion_groups = {k: v for k, v in motion_groups.items() if v}

    # 6. Create ParamRingOn toggle Expressions (.exp3.json) & KeyTrigger motion
    motion_groups["誓约戒指切换"] = [
        {
            "Name": "toggle_ring",
            "File": menu_prompt_mot,
            "FadeIn": 0,
            "FadeOut": 0,
            "MotionDuration": 50,
            "PostCommand": "next_exp",
        }
    ]
    ring_on_exp = {
        "Type": "Live2D Expression",
        "FadeInTime": 0.3,
        "FadeOutTime": 0.3,
        "Parameters": [{"Id": "ParamRingOn", "Value": 1.0, "Blend": "Overwrite"}],
    }
    ring_off_exp = {
        "Type": "Live2D Expression",
        "FadeInTime": 0.3,
        "FadeOutTime": 0.3,
        "Parameters": [{"Id": "ParamRingOn", "Value": 0.0, "Blend": "Overwrite"}],
    }
    write_json(exp_dir / "ring_on.exp3.json", ring_on_exp)
    write_json(exp_dir / "ring_off.exp3.json", ring_off_exp)

    # 7. Clean minimal HitAreas: ONLY 头 / 左手 / 右手 / 胸 / 躯干 / 臀部 (no leg/foot/fragmented boxes)
    candidate_hits = [
        {"Name": "头", "Id": "DREFTouchBoxHead", "Motion": "Tap头"},
        {"Name": "左手", "Id": "DREFTouchBoxHandL", "Motion": "Tap手"},
        {"Name": "右手", "Id": "DREFTouchBoxHandR", "Motion": "Tap手"},
        {"Name": "胸", "Id": "DREFTouchBoxBra", "Motion": "Tap胸"},
        {"Name": "躯干", "Id": "Body2", "Motion": "Tap躯干"},
        {"Name": "臀部", "Id": "DREFTouchBoxHip", "Motion": "Tap臀部"},
    ]
    verified_hits = [h for h in candidate_hits if h["Id"].encode("ascii") in moc_raw]

    model3 = {
        "ConfVer": 0,
        "Type": 0,
        "FileReferences": {
            "Moc": "Aurora.moc3",
            "Textures": ["Textures/Aurora_texture_00.png"],
            "Physics": "Aurora.physics3.json",
            "PhysicsV2": {"File": "Aurora.physics3.json"},
            "Expressions": [
                {"Name": "佩戴誓约戒指", "File": "expressions/ring_on.exp3.json"},
                {"Name": "取下誓约戒指", "File": "expressions/ring_off.exp3.json"},
            ],
            "Motions": motion_groups,
        },
        "Controllers": {
            "ParamHit": {},
            "ParamLoop": {},
            "KeyTrigger": {
                "Enabled": True,
                "Items": [
                    {"Input": 49, "DownMtn": "语音菜单"},  # '1' key (VK_1=49) -> open Voice & Motion Choices menu
                    {"Input": 77, "DownMtn": "语音菜单"},  # 'M' key (VK_M=77) -> open Voice & Motion Choices menu
                    {"Input": 86, "DownMtn": "语音菜单"},  # 'V' key (VK_V=86) -> open Voice & Motion Choices menu
                    {"Input": 82, "DownMtn": "誓约戒指切换"},  # 'R' key (VK_R=82) -> PostCommand next_exp ring toggle
                ],
            },
            "ParamTrigger": {},
            "AreaTrigger": {},
            "HandTrigger": {},
            "EyeBlink": {"MinInterval": 500, "MaxInterval": 6000, "Enabled": False},
            "LipSync": {"Gain": 5.0},
            "MouseTracking": {"SmoothTime": 0.15, "Enabled": True},
            "AutoBreath": {"Enabled": False},
            "ExtraMotion": {"Enabled": False},
            "Accelerometer": {"Enabled": True},
            "Microphone": {},
            "Transform": {},
            "FaceTracking": {"Enabled": True},
            "HandTracking": {},
            "ParamValue": {},
            "PartOpacity": {},
            "ArtmeshOpacity": {},
            "ArtmeshColor": {},
            "ArtmeshCulling": {"DefaultMode": 0},
            "IntimacySystem": {},
        },
        "HitAreas": verified_hits,
        "Options": {
            "Id": "aurora_s4_live2d",
            "ScaleFactor": 1.63913655,
            "PositionX": -0.0351872966,
            "PositionY": -0.256166071,
            "TexType": 0,
        },
    }

    write_json(out_dir / ".model3.json", model3)
    return {
        "out_dir": str(out_dir),
        "motions_extracted": len(motions_by_stem),
        "wavs_extracted": len(extracted_wavs),
        "hit_areas": len(verified_hits),
        "motion_groups": {k: len(v) for k, v in motion_groups.items()},
    }


if __name__ == "__main__":
    summary = build_aurora_s4_live2d()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
