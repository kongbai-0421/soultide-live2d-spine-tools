r"""Apply SoulTide Live2D motion-triggered & menu main-form switching for Live2DViewerEX.

Implements two complementary capabilities across 4 dolls (10 Live2D skins, 3 languages each):

A. Motion-triggered temporary form switching (while in default main form, never cuts voice):
   1. Netsuki (梦咲音月, 3 skins: 原皮 / 春竹贺晓 / 此情无垢):
      - Unpacks official red-form texture (`Textures/netsuki_texture_00_00.png`) from Offline CDN.
      - Applies `replace_tex 0 Textures/netsuki_texture_00_00.png` (`Command`) and
        `replace_tex 0 <base_texture_0>` (`PostCommand`) on all official `TextureChange` motions.
   2. Ithil (伊汐尔: 原皮 / 新春焰火), EtsukazuMiko (越一弥心: 原皮 / 邂逅风纪 / 时尚同桌),
      RubyRose (露比·罗斯: 原皮 / 圣诞怪盗) — Scheme A (`add_submodel` seamless takeover):
      - Builds self-contained `submodels/henshin/sub_henshin.model3.json` inside each skin.
      - Parent `Start` loads submodel (`add_submodel ... 1`), `IsTransfigurationAction` motions
        hide main via `parts lock` + drive `start_mtn <sub_id> Show_<stem>` + restore via
        `PostCommand`, with zero-IO failsafe restore on `Idle` & non-transfig motions.

B. Menu-triggered permanent Main-Form switching (`change_model`, zero `../` paths, LPK-safe):
   - Adds a top-level choice in `Tap` and `语音菜单` (3 languages: zh / en / ja) pointing to
     `Form_Switch_Main` (`menu_silent.motion3.json`, `FadeIn=0`, `FadeOut=0`):
     * In default configs (`.model3.json` / `model_en.model3.json` / `model_ja.model3.json`):
       switches to sibling root transformed main-form config via `change_model`:
       - Netsuki: `model_red.model3.json` / `model_red_en.model3.json` / `model_red_ja.model3.json`
         (reuses `.moc3`/`motions/`/`audio/`, binds `Textures[0]` to red texture, zero `replace_tex` overhead).
       - Scheme A dolls: `model_henshin.model3.json` / `model_henshin_en.model3.json` / `model_henshin_ja.model3.json`
         (references `submodels/henshin/` `.moc3`/`Textures/`/`Physics`/`motions/` + parent `audio/`,
         with full native LipSync, transformed HitAreas, and all skin voices & motions).
     * In transformed main-form configs:
       switches back to the exact matching language default config (`change_model .model3.json` /
       `model_en.model3.json` / `model_ja.model3.json`).

Idempotent: safe to re-run at any time.
"""

from __future__ import annotations

import copy
import ctypes
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from audit_live2d_touch import init_cubism_core
from soultide_common import DECOMPILED_DIR, LuaTableRepo, load_ab, parse_lua_flat_table, write_json

LIVE2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
CDN_L2D_RES = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android\20_live2d\live2d_resources")
REPORT_PATH = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本\l2d_model_switch_report.json")

LANG_SPECS: tuple[tuple[str, str, str], ...] = (
    ("zh", ".model3.json", ""),
    ("en", "model_en.model3.json", "_en"),
    ("ja", "model_ja.model3.json", "_ja"),
)

FORM_SWITCH_GROUP = "Form_Switch_Main"

MENU_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "netsuki": {
        "to_alt": {
            "zh": "★ 形态切换：将红发形态设为主形态",
            "en": "★ Form Switch: Set Red-Hair Form as Main",
            "ja": "★ 形態切替：赤髪形態をメインに設定",
        },
        "to_default": {
            "zh": "★ 形态切换：切回默认主形态",
            "en": "★ Form Switch: Return to Default Main Form",
            "ja": "★ 形態切替：デフォルトメイン形態に戻す",
        },
    },
    "henshin": {
        "to_alt": {
            "zh": "★ 形态切换：将变身形态设为主形态",
            "en": "★ Form Switch: Set Transformed Form as Main",
            "ja": "★ 形態切替：変身形態をメインに設定",
        },
        "to_default": {
            "zh": "★ 形态切换：切回默认主形态",
            "en": "★ Form Switch: Return to Default Main Form",
            "ja": "★ 形態切替：デフォルトメイン形態に戻す",
        },
    },
    "colcher": {
        "to_alt": {
            "zh": "★ 形态切换：将柯露雪儿剧情形态设为主形态",
            "en": "★ Form Switch: Set Colcher Story Form as Main",
            "ja": "★ 形態切替：コルシェル演出形態をメインに設定",
        },
        "to_default": {
            "zh": "★ 形态切换：切回默认主形态",
            "en": "★ Form Switch: Return to Default Main Form",
            "ja": "★ 形態切替：デフォルトメイン形態に戻す",
        },
    },
}

NETSUKI_RED_SOURCES: dict[str, tuple[str, str]] = {
    "原皮": (
        "batch25.ab",
        "assets/20_live2d/live2d_resources/live2d_netsuki_s1/moc/netsuki.2048/netsuki_texture_00_00.png",
    ),
    "春竹贺晓": (
        "batch25.ab",
        "assets/20_live2d/live2d_resources/live2d_netsuki_s2/moc/netsuki.2048/netsuki_texture_00_00.png",
    ),
    "此情无垢": (
        "batch41.ab",
        "assets/20_live2d/live2d_resources/live2d_netsuki_s3/moc/netsuki.2048/netsuki_texture_00_00.png",
    ),
}

SCHEME_A_TARGETS: list[dict[str, Any]] = [
    {
        "doll": "伊汐尔",
        "soul_prefix": "31",
        "sub_source_skin": "原皮_变身",
        "label_key": "henshin",
        "parent_skins": ["原皮", "新春焰火"],
    },
    {
        "doll": "越一弥心",
        "soul_prefix": "29",
        "sub_source_skin": "原皮_变身",
        "label_key": "henshin",
        "parent_skins": ["原皮", "邂逅风纪", "时尚同桌"],
    },
    {
        "doll": "露比·罗斯",
        "soul_prefix": "45",
        "sub_source_skin": "原皮_柯露雪儿剧情",
        "label_key": "colcher",
        "parent_skins": ["原皮", "圣诞怪盗"],
    },
]


def _init_core_parts():
    core = init_cubism_core()
    core.csmGetPartCount.argtypes = [ctypes.c_void_p]
    core.csmGetPartCount.restype = ctypes.c_int32
    core.csmGetPartIds.argtypes = [ctypes.c_void_p]
    core.csmGetPartIds.restype = ctypes.POINTER(ctypes.c_char_p)
    core.csmGetDrawableParentPartIndices.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableParentPartIndices.restype = ctypes.POINTER(ctypes.c_int32)
    return core


def get_moc_part_ids(core, moc_path: Path) -> tuple[list[str], int, list[str]]:
    """Return (part_ids, drawable_count, orphan_drawable_ids) via Live2DCubismCore."""
    moc_bytes = moc_path.read_bytes()
    moc_buf = ctypes.create_string_buffer(len(moc_bytes) + 64)
    moc_addr = (ctypes.addressof(moc_buf) + 63) & ~63
    ctypes.memmove(moc_addr, moc_bytes, len(moc_bytes))
    moc = core.csmReviveMocInPlace(moc_addr, len(moc_bytes))
    if not moc:
        raise RuntimeError(f"Failed to revive MOC3: {moc_path}")
    msize = core.csmGetSizeofModel(moc)
    mod_buf = ctypes.create_string_buffer(msize + 64)
    mod_addr = (ctypes.addressof(mod_buf) + 63) & ~63
    model = core.csmInitializeModelInPlace(moc, mod_addr, msize)
    core.csmUpdateModel(model)

    part_count = core.csmGetPartCount(model)
    pids_ptr = core.csmGetPartIds(model)
    part_ids = [pids_ptr[i].decode("utf-8") for i in range(part_count)]

    dcnt = core.csmGetDrawableCount(model)
    dids_ptr = core.csmGetDrawableIds(model)
    dpart_ptr = core.csmGetDrawableParentPartIndices(model)
    orphans = [
        dids_ptr[i].decode("utf-8", "ignore")
        for i in range(dcnt)
        if dpart_ptr[i] < 0
    ]
    return part_ids, dcnt, orphans


def load_all_soul_actions() -> dict[int, str]:
    acts: dict[int, str] = {}
    for p in sorted(DECOMPILED_DIR.glob("CfgSoulActionTable_*.lua")):
        if p.name.endswith("_Route.lua"):
            continue
        acts.update(parse_lua_flat_table(p))
    return acts


def collect_trigger_sets(
    repo: LuaTableRepo,
    all_acts: dict[int, str],
    predicate,
) -> tuple[set[str], set[str]]:
    """Return (matched_action_names, matched_sound_stems_lower)."""
    act_names: set[str] = set()
    sound_stems: set[str] = set()
    for kid, body in all_acts.items():
        if not predicate(kid, body):
            continue
        act_names.add(f"act_{kid}")
        cv_m = re.search(r'CV\s*=\s*"([^"]+)"', body)
        if cv_m and cv_m.group(1).isdigit():
            cv_id = int(cv_m.group(1))
            if cv_id in repo.cv_map:
                sid = repo.cv_map[cv_id]["sound_id"]
                fn = repo.sound_map.get(sid, "") if sid else ""
                if fn:
                    sound_stems.add(Path(fn).stem.lower())
    return act_names, sound_stems


def is_managed_cmd(token: str) -> bool:
    t = token.strip()
    return (
        t.startswith("replace_tex ")
        or t.startswith("add_submodel submodels/henshin/")
        or t.startswith("parts lock ")
        or t == "parts unlock"
        or t.startswith("parts unlock ")
        or (t.startswith("start_mtn ") and ("_henshin_sub " in t))
        or t.startswith("change_model ")
    )


def merge_commands(existing: str | None, new_cmds: list[str]) -> str | None:
    """Replace only our managed commands while preserving any unrelated commands."""
    kept: list[str] = []
    if existing:
        for seg in existing.split(";"):
            seg_s = seg.strip()
            if seg_s and not is_managed_cmd(seg_s):
                kept.append(seg_s)
    combined = kept + [c.strip() for c in new_cmds if c and c.strip()]
    return "; ".join(combined) if combined else None


def set_cmd_field(item: dict[str, Any], field: str, new_cmds: list[str]) -> None:
    merged = merge_commands(item.get(field), new_cmds)
    if merged:
        item[field] = merged
    else:
        item.pop(field, None)


def item_matches_trigger(
    item: dict[str, Any],
    act_names: set[str],
    sound_stems: set[str],
) -> bool:
    name = (item.get("Name") or "").strip()
    if name in act_names:
        return True
    snd = item.get("Sound") or ""
    if snd and Path(snd).stem.lower() in sound_stems:
        return True
    return False


def inject_form_switch_menu(
    data: dict[str, Any],
    choice_text: str,
    target_model_json: str,
    motion_name: str,
) -> None:
    """Idempotently add/update top-level Form_Switch_Main entry in Tap & 语音菜单."""
    mots = data["FileReferences"]["Motions"]
    for menu_grp in ("Tap", "语音菜单"):
        items = mots.get(menu_grp)
        if not items:
            continue
        choices = [
            ch for ch in (items[0].get("Choices") or [])
            if ch.get("NextMtn") != FORM_SWITCH_GROUP
        ]
        choices.append({"Text": choice_text, "NextMtn": FORM_SWITCH_GROUP})
        items[0]["Choices"] = choices

    mots[FORM_SWITCH_GROUP] = [
        {
            "Name": motion_name,
            "File": "motions/menu_silent.motion3.json",
            "FadeIn": 0,
            "FadeOut": 0,
            "Command": f"change_model {target_model_json}",
        }
    ]


def unpack_netsuki_red_textures() -> dict[str, dict[str, Any]]:
    """Extract official red-form Netsuki texture_00_00.png into each skin's Textures/."""
    loaded_envs: dict[str, Any] = {}
    results: dict[str, dict[str, Any]] = {}

    for skin, (ab_name, container_path) in NETSUKI_RED_SOURCES.items():
        ab_path = CDN_L2D_RES / ab_name
        if not ab_path.is_file():
            raise FileNotFoundError(f"Missing CDN AssetBundle: {ab_path}")
        if ab_name not in loaded_envs:
            loaded_envs[ab_name] = load_ab(ab_path)
        env = loaded_envs[ab_name]

        found_img = None
        for path_key, obj in env.container.items():
            if path_key.lower() == container_path.lower():
                if obj.type.name == "Texture2D":
                    found_img = obj.read().image
                    break
        if found_img is None:
            raise RuntimeError(f"Texture not found in {ab_name}: {container_path}")

        skin_dir = LIVE2D_ROOT / "梦咲音月" / skin
        m3 = json.loads((skin_dir / ".model3.json").read_text(encoding="utf-8-sig"))
        base_tex_rel = m3["FileReferences"]["Textures"][0]
        base_tex_abs = skin_dir / base_tex_rel
        with Image.open(base_tex_abs) as base_im:
            base_size = base_im.size

        if found_img.size != base_size:
            raise AssertionError(
                f"梦咲音月/{skin} red texture size {found_img.size} != base {base_size}"
            )

        out_rel = "Textures/netsuki_texture_00_00.png"
        out_abs = skin_dir / out_rel
        out_abs.parent.mkdir(parents=True, exist_ok=True)
        found_img.convert("RGBA").save(out_abs, "PNG")

        results[skin] = {
            "ab": ab_name,
            "container": container_path,
            "base_tex_rel": base_tex_rel,
            "red_tex_rel": out_rel,
            "size": list(found_img.size),
            "bytes": out_abs.stat().st_size,
        }
    return results


def apply_netsuki(repo: LuaTableRepo, all_acts: dict[int, str]) -> dict[str, Any]:
    tex_info = unpack_netsuki_red_textures()
    act_names, sound_stems = collect_trigger_sets(
        repo, all_acts, lambda _k, b: "TextureChange" in b
    )

    skin_reports: dict[str, Any] = {}
    for skin, tinfo in tex_info.items():
        skin_dir = LIVE2D_ROOT / "梦咲音月" / skin
        base_tex_rel = tinfo["base_tex_rel"]
        red_tex_rel = tinfo["red_tex_rel"]

        lang_counts: dict[str, int] = {}
        matched_groups_sample: list[str] = []
        alt_files_written: list[str] = []

        for lang_code, lang_fn, alt_suf in LANG_SPECS:
            alt_fn = f"model_red{alt_suf}.model3.json"
            cfg_p = skin_dir / lang_fn
            data = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
            mots = data["FileReferences"]["Motions"]
            hits = 0

            # 1. Patch default config (temporary replace_tex + menu switch to model_red)
            for grp, items in mots.items():
                if grp == FORM_SWITCH_GROUP:
                    continue
                for idx, item in enumerate(items):
                    if item_matches_trigger(item, act_names, sound_stems):
                        set_cmd_field(item, "Command", [f"replace_tex 0 {red_tex_rel}"])
                        set_cmd_field(item, "PostCommand", [f"replace_tex 0 {base_tex_rel}"])
                        hits += 1
                        if lang_code == "zh" and not grp.startswith("Menu"):
                            matched_groups_sample.append(f"{grp}[{idx}]")
                    else:
                        set_cmd_field(item, "Command", [])
                        set_cmd_field(item, "PostCommand", [])

            inject_form_switch_menu(
                data=data,
                choice_text=MENU_LABELS["netsuki"]["to_alt"][lang_code],
                target_model_json=alt_fn,
                motion_name="form_switch_to_red",
            )
            write_json(cfg_p, data)
            lang_counts[lang_fn] = hits

            # 2. Build sibling permanent red main-form config (zero replace_tex overhead)
            red_data = copy.deepcopy(data)
            red_data["FileReferences"]["Textures"][0] = red_tex_rel
            red_opt = red_data.setdefault("Options", {})
            base_id = red_opt.get("Id") or f"live2d_netsuki_{skin}"
            red_opt["Id"] = f"{base_id}_red_main"

            for grp, items in red_data["FileReferences"]["Motions"].items():
                if grp == FORM_SWITCH_GROUP:
                    continue
                for item in items:
                    set_cmd_field(item, "Command", [])
                    set_cmd_field(item, "PostCommand", [])

            inject_form_switch_menu(
                data=red_data,
                choice_text=MENU_LABELS["netsuki"]["to_default"][lang_code],
                target_model_json=lang_fn,
                motion_name="form_switch_to_default",
            )
            write_json(skin_dir / alt_fn, red_data)
            alt_files_written.append(alt_fn)

        if len(set(lang_counts.values())) != 1:
            raise AssertionError(f"Language sync mismatch for 梦咲音月/{skin}: {lang_counts}")

        skin_reports[skin] = {
            **tinfo,
            "matched_items_per_lang": lang_counts[".model3.json"],
            "lang_files_updated": [x[1] for x in LANG_SPECS],
            "alt_main_configs": alt_files_written,
            "non_menu_hits_sample": matched_groups_sample[:10],
        }

    return {
        "mode": "replace_tex + change_model_main_form",
        "trigger_action_count": len(act_names),
        "trigger_sound_stems": len(sound_stems),
        "skins": skin_reports,
    }


def resolve_fallback_motion(
    orig_mot_name: str,
    src_mot_map: dict[str, str],
    idle_name: str,
) -> str:
    """Map a parent-only motion (e.g. skin fashion/sad) to a compatible transformed motion."""
    low = orig_mot_name.lower()
    if low in src_mot_map:
        return src_mot_map[low]

    candidates: list[str] = []
    if "fashion" in low:
        candidates.extend(["greet1", "greet2", "insert01", "standby1"])
    elif "greet_sad" in low or "sad" in low:
        candidates.extend(["insert_sad", "greet_sad", "sad", "greet1", "insert01", "standby1"])
    else:
        candidates.extend(["greet1", "insert01", "standby1"])

    for kw in candidates:
        for k, v in sorted(src_mot_map.items()):
            if f"@live2d_{kw}." in k or f"_{kw}." in k:
                return v
    return idle_name


def build_submodel_bundle(
    core,
    parent_dir: Path,
    parent_options_id: str,
    sub_source_dir: Path,
    needed_transfig_motions: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create self-contained `submodels/henshin/` bundle supporting BOTH:
    1) Temporary Scheme A takeover (`submodels/henshin/sub_henshin.model3.json`), AND
    2) Permanent root main-form (`model_henshin*.model3.json` in parent_dir).

    Copies ALL non-menu `.motion3.json` from `sub_source_dir/motions/` into
    `submodels/henshin/motions/` so permanent main-form has full animations.
    """
    src_m3 = json.loads((sub_source_dir / ".model3.json").read_text(encoding="utf-8-sig"))
    src_fr = src_m3["FileReferences"]

    sub_dir = parent_dir / "submodels" / "henshin"
    if sub_dir.exists():
        shutil.rmtree(sub_dir)
    (sub_dir / "Textures").mkdir(parents=True, exist_ok=True)
    (sub_dir / "motions").mkdir(parents=True, exist_ok=True)

    # 1. Copy MOC3
    moc_rel = src_fr["Moc"]
    shutil.copy2(sub_source_dir / moc_rel, sub_dir / moc_rel)

    # 2. Copy Textures
    tex_rels: list[str] = []
    for trel in src_fr["Textures"]:
        dst_t = sub_dir / trel
        dst_t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sub_source_dir / trel, dst_t)
        tex_rels.append(trel)

    # 3. Copy Physics (if present)
    phys_rel = src_fr.get("Physics")
    if phys_rel and (sub_source_dir / phys_rel).is_file():
        shutil.copy2(sub_source_dir / phys_rel, sub_dir / phys_rel)
    else:
        phys_rel = None

    # 4. Copy ALL real motions from transformed source (skip menu_silent, parent has it)
    src_mot_map: dict[str, str] = {}
    for p in sorted((sub_source_dir / "motions").glob("*.motion3.json")):
        if p.name.lower() == "menu_silent.motion3.json":
            continue
        shutil.copy2(p, sub_dir / "motions" / p.name)
        src_mot_map[p.name.lower()] = p.name

    idle_items = src_fr.get("Motions", {}).get("Idle") or []
    if not idle_items:
        raise RuntimeError(f"No Idle motion found in {sub_source_dir}")
    idle_name = Path(idle_items[0]["File"]).name
    if idle_name.lower() not in src_mot_map:
        raise FileNotFoundError(f"Missing Idle motion '{idle_name}' in {sub_source_dir}")
    idle_rel = f"motions/{src_mot_map[idle_name.lower()]}"

    transfig_rel_map: dict[str, str] = {}
    for mf_name in sorted(needed_transfig_motions):
        actual = src_mot_map.get(mf_name.lower())
        if actual is None:
            raise FileNotFoundError(
                f"Required transformed motion '{mf_name}' missing in {sub_source_dir / 'motions'}"
            )
        transfig_rel_map[mf_name.lower()] = f"motions/{actual}"

    # 5. Inspect Cubism3 Part IDs of submodel MOC3
    sub_parts, sub_dcnt, sub_orphans = get_moc_part_ids(core, sub_dir / moc_rel)
    non_touch_orphans = [
        o for o in sub_orphans if not o.startswith(("DREFTouchBox", "HitArea"))
    ]
    if non_touch_orphans:
        raise AssertionError(
            f"Unexpected visible orphan drawables in {sub_source_dir}: {non_touch_orphans}"
        )

    parts_csv = ",".join(sub_parts)
    hide_instant = f"parts lock {parts_csv} 0 0"
    hide_fade = f"parts lock {parts_csv} 0 80"

    sub_id = f"{parent_options_id}_henshin_sub"
    sub_motions: dict[str, list[dict[str, Any]]] = {
        "Start": [
            {
                "Name": "sub_start_hide",
                "File": idle_rel,
                "FadeIn": 0,
                "FadeOut": 0,
                "Command": hide_instant,
            }
        ],
        "Idle": [
            {
                "Name": "sub_idle",
                "File": idle_rel,
                "FadeIn": 0,
                "FadeOut": 150,
            }
        ],
        "Hide": [
            {
                "Name": "sub_hide",
                "File": idle_rel,
                "FadeIn": 0,
                "FadeOut": 0,
                "Command": hide_fade,
            }
        ],
    }

    for _mf_lower, rel_p in sorted(transfig_rel_map.items()):
        stem = Path(rel_p).stem
        if stem.endswith(".motion3"):
            stem = stem[:-8]
        grp_name = f"Show_{stem}"
        sub_motions[grp_name] = [
            {
                "Name": grp_name,
                "File": rel_p,
                "FadeIn": 150,
                "FadeOut": 150,
                "Command": "parts unlock",
            }
        ]

    src_opt = dict(src_m3.get("Options") or {})
    sub_options = {
        "Id": sub_id,
        "ScaleFactor": src_opt.get("ScaleFactor", 1.5),
        "PositionX": src_opt.get("PositionX", 0.0),
        "PositionY": src_opt.get("PositionY", 0.0),
        "TexType": src_opt.get("TexType", 0),
    }

    src_ctrl = src_m3.get("Controllers") or {}
    mouse_tracking = src_ctrl.get("MouseTracking") or {"Enabled": True, "SmoothTime": 0.15}
    sub_controllers = {
        "EyeBlink": {"Enabled": False},
        "AutoBreath": {"Enabled": False},
        "ExtraMotion": {"Enabled": False},
        "MouseTracking": mouse_tracking,
        "LipSync": {"Enabled": False, "Gain": 5.0},
        "KeyTrigger": {"Enabled": False},
    }

    sub_fr: dict[str, Any] = {
        "Moc": moc_rel,
        "Textures": tex_rels,
        "Motions": sub_motions,
    }
    if phys_rel:
        sub_fr["Physics"] = phys_rel
        sub_fr["PhysicsV2"] = {"File": phys_rel}

    sub_cfg = {
        "Version": 3,
        "Type": 0,
        "ConfVer": 3,
        "FileReferences": sub_fr,
        "Controllers": sub_controllers,
        "HitAreas": [],
        "Options": sub_options,
    }

    sub_cfg_rel = "submodels/henshin/sub_henshin.model3.json"
    write_json(parent_dir / sub_cfg_rel, sub_cfg)

    bundle_bytes = sum(p.stat().st_size for p in sub_dir.rglob("*") if p.is_file())
    sub_info = {
        "sub_id": sub_id,
        "sub_cfg_rel": sub_cfg_rel,
        "sub_parts_count": len(sub_parts),
        "sub_drawables_count": sub_dcnt,
        "sub_orphan_drawables": sub_orphans,
        "show_groups_count": len(transfig_rel_map),
        "total_copied_motions": len(src_mot_map),
        "bundle_bytes": bundle_bytes,
        "options": sub_options,
    }
    bundle_meta = {
        "moc_rel": moc_rel,
        "tex_rels": tex_rels,
        "phys_rel": phys_rel,
        "idle_name": src_mot_map[idle_name.lower()],
        "src_mot_map": src_mot_map,
        "src_options": src_opt,
        "src_hit_areas": copy.deepcopy(src_m3.get("HitAreas") or []),
        "src_expressions": copy.deepcopy(src_fr.get("Expressions") or []),
    }
    return sub_info, bundle_meta


def build_root_henshin_main_config(
    parent_data: dict[str, Any],
    parent_options_id: str,
    bundle_meta: dict[str, Any],
    lang_code: str,
    orig_lang_fn: str,
    label_key: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build sibling root `model_henshin*.model3.json` for permanent transformed main form."""
    hm = copy.deepcopy(parent_data)
    fr = hm["FileReferences"]
    prefix = "submodels/henshin/"

    fr["Moc"] = f"{prefix}{bundle_meta['moc_rel']}"
    fr["Textures"] = [f"{prefix}{t}" for t in bundle_meta["tex_rels"]]
    if bundle_meta["phys_rel"]:
        fr["Physics"] = f"{prefix}{bundle_meta['phys_rel']}"
        fr["PhysicsV2"] = {"File": f"{prefix}{bundle_meta['phys_rel']}"}
    else:
        fr.pop("Physics", None)
        fr.pop("PhysicsV2", None)

    if bundle_meta["src_expressions"]:
        fr["Expressions"] = bundle_meta["src_expressions"]
    else:
        fr.pop("Expressions", None)

    src_mot_map = bundle_meta["src_mot_map"]
    idle_name = bundle_meta["idle_name"]
    remapped: dict[str, str] = {}

    for grp, items in fr["Motions"].items():
        if grp == FORM_SWITCH_GROUP:
            continue
        for item in items:
            # Strip temporary submodel takeover commands (we ARE the main transformed model)
            set_cmd_field(item, "Command", [])
            set_cmd_field(item, "PostCommand", [])

            cur_rel = item.get("File", "")
            cur_name = Path(cur_rel).name
            if cur_name.lower() == "menu_silent.motion3.json":
                item["File"] = "motions/menu_silent.motion3.json"
            elif grp == "Idle":
                item["Name"] = "standby1" if "standby1" in idle_name.lower() else item.get("Name", "Idle")
                item["File"] = f"{prefix}motions/{idle_name}"
                item["FadeIn"] = 0
            else:
                mapped_name = resolve_fallback_motion(cur_name, src_mot_map, idle_name)
                if mapped_name.lower() != cur_name.lower():
                    remapped[cur_name] = mapped_name
                item["File"] = f"{prefix}motions/{mapped_name}"

    # Use transformed MOC3's verified HitAreas (filtered only if any motion group absent)
    valid_hit_areas = [
        ha for ha in bundle_meta["src_hit_areas"]
        if ha.get("Motion") in fr["Motions"]
    ]
    hm["HitAreas"] = valid_hit_areas

    # Calibrated Options of the transformed model with unique main ID
    src_opt = bundle_meta["src_options"]
    hm["Options"] = {
        "Id": f"{parent_options_id}_henshin_main",
        "ScaleFactor": src_opt.get("ScaleFactor", 1.5),
        "PositionX": src_opt.get("PositionX", 0.0),
        "PositionY": src_opt.get("PositionY", 0.0),
        "TexType": src_opt.get("TexType", 0),
    }

    # Menu switch back to exact matching language default config
    inject_form_switch_menu(
        data=hm,
        choice_text=MENU_LABELS[label_key]["to_default"][lang_code],
        target_model_json=orig_lang_fn,
        motion_name="form_switch_to_default",
    )
    return hm, remapped


def apply_scheme_a_doll(
    core,
    repo: LuaTableRepo,
    all_acts: dict[int, str],
    spec: dict[str, Any],
) -> dict[str, Any]:
    doll = spec["doll"]
    prefix = spec["soul_prefix"]
    label_key = spec["label_key"]
    sub_source_dir = LIVE2D_ROOT / doll / spec["sub_source_skin"]
    if not (sub_source_dir / ".model3.json").is_file():
        raise FileNotFoundError(f"Missing transformed source package: {sub_source_dir}")

    act_names, sound_stems = collect_trigger_sets(
        repo,
        all_acts,
        lambda k, b: str(k).startswith(prefix) and "IsTransfigurationAction = true" in b,
    )

    skin_reports: dict[str, Any] = {}
    for skin in spec["parent_skins"]:
        parent_dir = LIVE2D_ROOT / doll / skin
        base_m3 = json.loads((parent_dir / ".model3.json").read_text(encoding="utf-8-sig"))
        parent_opt_id = (base_m3.get("Options") or {}).get("Id")
        if not parent_opt_id:
            raise ValueError(f"Missing Options.Id in {parent_dir / '.model3.json'}")

        needed_mots: set[str] = set()
        for grp, items in base_m3["FileReferences"]["Motions"].items():
            if grp == FORM_SWITCH_GROUP:
                continue
            for item in items:
                if item_matches_trigger(item, act_names, sound_stems):
                    needed_mots.add(Path(item["File"]).name)

        if not needed_mots:
            raise RuntimeError(f"Zero matched IsTransfigurationAction motions in {doll}/{skin}")

        sub_info, bundle_meta = build_submodel_bundle(
            core=core,
            parent_dir=parent_dir,
            parent_options_id=parent_opt_id,
            sub_source_dir=sub_source_dir,
            needed_transfig_motions=needed_mots,
        )
        sub_id = sub_info["sub_id"]
        sub_cfg_rel = sub_info["sub_cfg_rel"]

        main_parts, main_dcnt, main_orphans = get_moc_part_ids(
            core, parent_dir / base_m3["FileReferences"]["Moc"]
        )
        non_touch_orphans = [
            o for o in main_orphans if not o.startswith(("DREFTouchBox", "HitArea"))
        ]
        if non_touch_orphans:
            raise AssertionError(
                f"Unexpected visible orphan drawables in {doll}/{skin}: {non_touch_orphans}"
            )
        main_hide_cmd = f"parts lock {','.join(main_parts)} 0 80"
        restore_cmds = ["parts unlock", f"start_mtn {sub_id} Hide"]

        lang_hit_counts: dict[str, int] = {}
        non_menu_sample: list[str] = []
        alt_files_written: list[str] = []
        remapped_motions: dict[str, str] = {}

        for lang_code, lang_fn, alt_suf in LANG_SPECS:
            alt_fn = f"model_henshin{alt_suf}.model3.json"
            cfg_p = parent_dir / lang_fn
            data = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
            mots = data["FileReferences"]["Motions"]
            hits = 0

            # 1. Patch default parent config (Scheme A temporary takeover + menu switch)
            for grp, items in mots.items():
                if grp == FORM_SWITCH_GROUP:
                    continue
                for idx, item in enumerate(items):
                    is_transfig = item_matches_trigger(item, act_names, sound_stems)
                    if grp == "Start":
                        cmds = [f"add_submodel {sub_cfg_rel} 1"]
                        if is_transfig:
                            stem = Path(item["File"]).stem
                            if stem.endswith(".motion3"):
                                stem = stem[:-8]
                            cmds.extend([main_hide_cmd, f"start_mtn {sub_id} Show_{stem}"])
                            set_cmd_field(item, "Command", cmds)
                            set_cmd_field(item, "PostCommand", restore_cmds)
                            hits += 1
                        else:
                            set_cmd_field(item, "Command", cmds)
                            set_cmd_field(item, "PostCommand", [])
                    elif is_transfig:
                        stem = Path(item["File"]).stem
                        if stem.endswith(".motion3"):
                            stem = stem[:-8]
                        set_cmd_field(
                            item,
                            "Command",
                            [main_hide_cmd, f"start_mtn {sub_id} Show_{stem}"],
                        )
                        set_cmd_field(item, "PostCommand", restore_cmds)
                        hits += 1
                        if lang_code == "zh" and not grp.startswith("Menu"):
                            non_menu_sample.append(f"{grp}[{idx}]->Show_{stem}")
                    else:
                        set_cmd_field(item, "Command", restore_cmds)
                        set_cmd_field(item, "PostCommand", [])

            inject_form_switch_menu(
                data=data,
                choice_text=MENU_LABELS[label_key]["to_alt"][lang_code],
                target_model_json=alt_fn,
                motion_name="form_switch_to_henshin",
            )
            write_json(cfg_p, data)
            lang_hit_counts[lang_fn] = hits

            # 2. Build sibling root permanent transformed main-form config
            hm_data, remapped = build_root_henshin_main_config(
                parent_data=data,
                parent_options_id=parent_opt_id,
                bundle_meta=bundle_meta,
                lang_code=lang_code,
                orig_lang_fn=lang_fn,
                label_key=label_key,
            )
            if lang_code == "zh":
                remapped_motions = remapped
            write_json(parent_dir / alt_fn, hm_data)
            alt_files_written.append(alt_fn)

        if len(set(lang_hit_counts.values())) != 1:
            raise AssertionError(
                f"Language sync mismatch for {doll}/{skin}: {lang_hit_counts}"
            )

        skin_reports[skin] = {
            "parent_options_id": parent_opt_id,
            "main_parts_count": len(main_parts),
            "main_drawables_count": main_dcnt,
            "main_orphan_drawables": main_orphans,
            "matched_items_per_lang": lang_hit_counts[".model3.json"],
            "lang_files_updated": [x[1] for x in LANG_SPECS],
            "alt_main_configs": alt_files_written,
            "alt_main_remapped_motions": remapped_motions,
            "non_menu_hits_sample": non_menu_sample[:10],
            "submodel": sub_info,
        }

    return {
        "mode": "scheme_a_submodel_takeover + change_model_main_form",
        "sub_source_skin": spec["sub_source_skin"],
        "trigger_action_count": len(act_names),
        "trigger_sound_stems": len(sound_stems),
        "skins": skin_reports,
    }


def main() -> None:
    core = _init_core_parts()
    repo = LuaTableRepo()
    all_acts = load_all_soul_actions()

    report: dict[str, Any] = {
        "梦咲音月": apply_netsuki(repo, all_acts),
    }
    for spec in SCHEME_A_TARGETS:
        report[spec["doll"]] = apply_scheme_a_doll(core, repo, all_acts, spec)

    write_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nReport saved to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
