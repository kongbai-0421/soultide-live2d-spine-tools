r"""Step 7 Post-Pass: Restore Original Client Hidden Background Animations & BoneFollower Ambient Particles.

Restores previously untouched official client animations directly into the rebuilt v2 Composite Spine 3.8 submodels:
1. `1802_SakuyaMako_S3` (`朔耶真子/情系站缘`):
   - 24.5s `FX_UI_SakuyaMako_S3_Background_Train` (train approach, stop, sliding `Image_Door_02`, headlight fade, departure, CanvasGroup alpha)
   - 24.5s `FX_UI_SakuyaMako_S3_Background_Light` (`Image_Light_01` platform indicator toggle)
2. `2502_Alisa_S3` (`爱莉莎/完美篇章`):
   - 6.1s `FX_UI_Alisa_S3_Background_Ithil` (`Layer_02/Anim/Image_02` glide, bounce squash-stretch, alpha fade)
3. `604_Asuna_S9` (`星见亚砂/盛夏游乐场`):
   - 60.1s `FX_Asuna_S9_Background` (360° continuous Ferris wheel rotation on `motianl` + `chexiang` + `chexiang (1)`)
4. `1102_NicoletteLamel_S3` (`尼柯莱特/至深理欲`):
   - 5.083s 60-frame `UI.Image.m_Sprite` flipbook animation on `Layer_01/ActionBg/Image_01`
5. 4 `BoneFollower` SoulAction ambient particle systems (`1503_Dreizehn_S4`, `2201_Andrea_S2`,
   `2901_EtsukazuMiko_S2`, `3001_TsukinoMiyo_S2`) anchored at exact rest-pose Spine bone world coordinates.

Strictly non-destructive to main Person files, audio, BGM, and `soultide.db`.
"""

from __future__ import annotations

import copy
import io
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
SCRIPTS_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本")
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
UNITY_EXE = r"D:\Program Files\Unity\Hub\Editor\2021.3.34f1\Editor\Unity.exe"
UNITY_PROJ = TOOLS_DIR / "SoulTideBatchFxUnity"

for _p in (str(TOOLS_DIR), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from batch_fx_exporter import (
    AssetIndexer,
    FullI18nRepo,
    _extract_ps_nodes,
    _node_local_tf,
    build_skin_catalog,
    inspect_bg_prefab_layout,
    resolve_bg_prefab_root,
    resolve_soul_action_entity,
)
from batch_spine_builder import (
    _extract_unity_scene_layers,
    _read_sprite_rgba_untrimmed,
    eval_bone_world_positions,
    parse_spine38_binary,
)
from convert_fx_to_native_spine import (
    build_tex_index,
    compute_native_idle_period,
    emit_native_fx_nodes_into_skeleton,
    pack_shelf,
    rgba_hex,
    sanitize_id,
    save_exact_webp,
    to_pma,
    trim_sprite,
)
from rebuild_all_scenes_and_fx_v2 import (
    compute_viewport_spine_bounds,
    make_exact_coord_mappers,
    patch_all_language_configs,
    render_static_band_pma,
)
from rebuild_spine_scenes_from_art_prefabs import FastSceneRepos
from soultide_common import CDN_ROOT, load_ab
from spine38_binary_to_json import _tile_keyframes, animation_duration
from spine_fx_submodel_packer import _build_atlas_text, _pack_skyline


def _eval_unity_curve(kfs: list[dict[str, Any]], t: float, default: float = 0.0) -> float:
    if not kfs:
        return default
    if t <= float(kfs[0]["time"]):
        return float(kfs[0]["value"])
    if t >= float(kfs[-1]["time"]):
        return float(kfs[-1]["value"])
    for i in range(len(kfs) - 1):
        t0, t1 = float(kfs[i]["time"]), float(kfs[i + 1]["time"])
        if t0 <= t <= t1:
            u = (t - t0) / max(1e-6, t1 - t0)
            v0, v1 = float(kfs[i]["value"]), float(kfs[i + 1]["value"])
            return v0 + (v1 - v0) * u
    return float(kfs[-1]["value"])


def _eval_unity_vec_curve(kfs: list[dict[str, Any]], t: float, default: tuple[float, float] = (1.0, 1.0)) -> tuple[float, float]:
    if not kfs:
        return default
    if t <= float(kfs[0]["time"]):
        v = kfs[0]["value"]
        return float(v["x"]), float(v["y"])
    if t >= float(kfs[-1]["time"]):
        v = kfs[-1]["value"]
        return float(v["x"]), float(v["y"])
    for i in range(len(kfs) - 1):
        t0, t1 = float(kfs[i]["time"]), float(kfs[i + 1]["time"])
        if t0 <= t <= t1:
            u = (t - t0) / max(1e-6, t1 - t0)
            v0, v1 = kfs[i]["value"], kfs[i + 1]["value"]
            return (
                float(v0["x"]) + (float(v1["x"]) - float(v0["x"])) * u,
                float(v0["y"]) + (float(v1["y"]) - float(v0["y"])) * u,
            )
    v = kfs[-1]["value"]
    return float(v["x"]), float(v["y"])


def _read_legacy_clip(ab_path: Path, pid: int) -> dict[str, Any]:
    env = load_ab(ab_path)
    try:
        for obj in env.objects:
            if obj.path_id == pid:
                return obj.read_typetree()
    finally:
        del env
    raise FileNotFoundError(f"Clip pid={pid} not found in {ab_path}")


def _extend_existing_idle_to(idle_anim: dict[str, Any], old_dur: float, new_dur: float) -> None:
    """Cleanly tile all existing timelines in `idle_anim` from `old_dur` to `new_dur`."""
    if old_dur <= 0.05 or abs(new_dur - old_dur) < 0.05:
        idle_anim.setdefault("bones", {})["root"] = {
            "translate": [{"time": 0.0, "x": 0.0, "y": 0.0}, {"time": round(new_dur, 4), "x": 0.0, "y": 0.0}]
        }
        return
    for bn, tl in (idle_anim.get("bones") or {}).items():
        if bn == "root":
            continue
        for tn, kfs in list(tl.items()):
            tl[tn] = _tile_keyframes(kfs, old_dur, new_dur)
    for sl, tl in (idle_anim.get("slots") or {}).items():
        for tn, kfs in list(tl.items()):
            tl[tn] = _tile_keyframes(kfs, old_dur, new_dur, is_stepped_type=(tn == "attachment"))
    for nm, kfs in list((idle_anim.get("ik") or {}).items()):
        idle_anim["ik"][nm] = _tile_keyframes(kfs, old_dur, new_dur)
    for nm, kfs in list((idle_anim.get("transform") or {}).items()):
        idle_anim["transform"][nm] = _tile_keyframes(kfs, old_dur, new_dur)
    for nm, tl in (idle_anim.get("path") or {}).items():
        for tn, kfs in list(tl.items()):
            tl[tn] = _tile_keyframes(kfs, old_dur, new_dur)
    for sk_m in (idle_anim.get("deform") or {}).values():
        for sl_m in sk_m.values():
            for anm, kfs in list(sl_m.items()):
                sl_m[anm] = _tile_keyframes(kfs, old_dur, new_dur)
    idle_anim.setdefault("bones", {})["root"] = {
        "translate": [{"time": 0.0, "x": 0.0, "y": 0.0}, {"time": round(new_dur, 4), "x": 0.0, "y": 0.0}]
    }


def _append_atlas_page_to_submodel(
    sub_dir: Path,
    cfg: dict[str, Any],
    page_fn: str,
    atlas_block: str,
) -> None:
    atl_rec = cfg["atlases"][0]
    atl_p = sub_dir / atl_rec["atlas"]
    old_txt = atl_p.read_text(encoding="utf-8-sig").rstrip()
    atl_p.write_text(old_txt + "\n\n" + atlas_block.strip() + "\n", encoding="utf-8")
    if page_fn not in atl_rec["textures"]:
        atl_rec["textures"].append(page_fn)
        atl_rec["tex_names"].append(Path(page_fn).stem)


def _replace_static_band_texture(
    sub_dir: Path,
    skel: dict[str, Any],
    cfg: dict[str, Any],
    band_slot_name: str,
    imgs_to_bake: list[dict[str, Any]],
    layout: dict[str, Any],
) -> None:
    """Re-render a single specific static band (e.g. st_s00, st_s03, st_s05) in place without touching other bands!"""
    # Map e.g. 'st_s03' -> tex pattern '_st03_', bone 'st_b03', att 'st_03'
    suffix = band_slot_name.replace("st_s", "")
    tex_pat = f"_st{suffix}_"
    bone_name = f"st_b{suffix}"
    att_name = f"st_{suffix}"
    st_fn = next((t for t in cfg["atlases"][0]["textures"] if tex_pat in t), None)
    if not st_fn or not imgs_to_bake:
        return
    res = render_static_band_pma(imgs_to_bake, layout, 0.0)
    if res is None:
        return
    save_exact_webp(res["im"], sub_dir / st_fn)
    res["im"].close()

    atl_p = sub_dir / cfg["atlases"][0]["atlas"]
    lines = atl_p.read_text(encoding="utf-8-sig").splitlines()
    in_st = False
    for i, ln in enumerate(lines):
        if ln.strip() == st_fn:
            in_st = True
        elif in_st and ln.strip().startswith("size:") and not ln.startswith(" "):
            lines[i] = f"size: {res['w']},{res['h']}"
        elif in_st and ln.strip().startswith("size:") and ln.startswith("  "):
            lines[i] = f"  size: {res['w']}, {res['h']}"
        elif in_st and ln.strip().startswith("orig:"):
            lines[i] = f"  orig: {res['w']}, {res['h']}"
            in_st = False
    atl_p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for b in skel["bones"]:
        if b["name"] == bone_name:
            b["x"], b["y"] = res["x"], res["y"]
            b["scaleX"], b["scaleY"] = res["scaleX"], res["scaleY"]
    st_att = (skel["skins"][0]["attachments"].get(band_slot_name) or {}).get(att_name)
    if st_att:
        st_att["width"], st_att["height"] = res["w"], res["h"]


def _strip_static_paths_and_rerender_st00(
    sub_dir: Path,
    skel: dict[str, Any],
    cfg: dict[str, Any],
    skin: dict[str, Any],
    layout: dict[str, Any],
    repos: FastSceneRepos,
    indexer: AssetIndexer,
    exclude_path_substrs: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Re-render st_00 static backdrop without animated layers (only valid for single-static-band back submodels)."""
    scene = _extract_unity_scene_layers(repos, indexer, skin, layout)
    pk = scene["person_key"]
    back_imgs = [im for im in scene["img_layers"] if im["draw_key"] < pk]
    excluded = [im for im in back_imgs if any(s in im["path"] for s in exclude_path_substrs)]
    kept = [im for im in back_imgs if not any(s in im["path"] for s in exclude_path_substrs)]

    _replace_static_band_texture(sub_dir, skel, cfg, "st_s00", kept, layout)

    for im in kept:
        try:
            im["img"].close()
        except Exception:
            pass
    for im in scene["img_layers"]:
        if im not in excluded and im not in kept:
            try:
                im["img"].close()
            except Exception:
                pass
    return excluded


# ---------------------------------------------------------------------------
# 1. SakuyaMako_S3: 24.5s Train Approach/Stop/Door/Light/Departure + Platform Light
# ---------------------------------------------------------------------------

def patch_sakuyamako_s3(cat: dict[str, Any], indexer: AssetIndexer, repos: FastSceneRepos) -> str:
    sk = "1802_SakuyaMako_S3"
    skin = cat[sk]
    sub_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"] / "submodels" / "scene_back"
    cfg_p = sub_dir / ".config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
    skel_p = sub_dir / cfg["skeleton"]
    skel = json.loads(skel_p.read_text(encoding="utf-8-sig"))
    if any(b["name"] == "sm_train_root" for b in skel["bones"]):
        return "already_patched"

    layout = inspect_bg_prefab_layout(indexer, skin)
    coord_fn, size_fn, _ = make_exact_coord_mappers(layout, 0.0)
    p = layout["person"]
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])

    # Extract scene layers WITHOUT touching st_s00 (Bottom/Image_01, Image_03)!
    # Split Mid static band (st_s05) strictly into:
    #   1) st_s05       = Mid/Image_04 (dk=7, station back wall BEHIND train & lights)
    #   2) animated     = Mid/Anim_Light/* (dk=8..10) + Mid/Anim_Train/* (dk=11..15)
    #   3) st_s05_front = Mid/Image_05..Image_08 (dk=16..19, platform pillars/bench IN FRONT OF train!)
    scene = _extract_unity_scene_layers(repos, indexer, skin, layout)
    pk = scene["person_key"]
    back_imgs = [im for im in scene["img_layers"] if im["draw_key"] < pk]
    mid_imgs = [im for im in back_imgs if "/Mid/" in im["path"]]
    excluded = [im for im in mid_imgs if ("/Mid/Anim_Train/" in im["path"] or "/Mid/Anim_Light/" in im["path"])]
    min_anim_dk = min(im["draw_key"] for im in excluded)
    max_anim_dk = max(im["draw_key"] for im in excluded)
    mid_behind = [im for im in mid_imgs if im not in excluded and im["draw_key"] < min_anim_dk]
    mid_infront = [im for im in mid_imgs if im not in excluded and im["draw_key"] > max_anim_dk]

    # Re-render st_s05 in place with ONLY mid_behind (Mid/Image_04), leaving st_s00 100% untouched!
    _replace_static_band_texture(sub_dir, skel, cfg, "st_s05", mid_behind, layout)

    # Render mid_infront (Image_05..Image_08) as a separate foreground static slice placed AFTER the train!
    front_slice_res = render_static_band_pma(mid_infront, layout, 0.0) if mid_infront else None
    front_slice_fn = None
    if front_slice_res is not None:
        front_slice_fn = "scene_back_st05_front.webp"
        save_exact_webp(front_slice_res["im"], sub_dir / front_slice_fn)
        front_slice_res["im"].close()
        fw, fh = front_slice_res["w"], front_slice_res["h"]
        f_atl = "\n".join([
            front_slice_fn, f"size: {fw},{fh}", "format: RGBA8888", "filter: Linear,Linear", "repeat: none",
            "st_05_front", "  rotate: false", "  xy: 0, 0", f"  size: {fw}, {fh}", f"  orig: {fw}, {fh}", "  offset: 0, 0", "  index: -1",
        ])
        _append_atlas_page_to_submodel(sub_dir, cfg, front_slice_fn, f_atl)

    for im in scene["img_layers"]:
        if im not in excluded:
            try:
                im["img"].close()
            except Exception:
                pass

    by_name = {im["name"]: im for im in excluded}

    # Pack all train + light sprites onto one lossless PMA page
    pack_items = []
    name_to_reg: dict[str, tuple[str, float, float]] = {}
    for nm, im_rec in sorted(by_name.items()):
        im_pma = to_pma(im_rec["img"])
        cr, ow, oh, ox, oy = trim_sprite(im_pma, 1)
        rname = f"sm_{sanitize_id(nm)}"
        pack_items.append({"name": rname, "im": cr, "orig_w": ow, "orig_h": oh, "off_x": ox, "off_y": oy, "pad": 2})
        sw, sh = size_fn(im_rec["w"], im_rec["h"])
        name_to_reg[nm] = (rname, round(abs(sw), 2), round(abs(sh), 2))
        im_rec["img"].close()

    atlas_im, regions = pack_shelf(pack_items, pad=2)
    page_fn = "scene_back_train_anim.webp"
    save_exact_webp(atlas_im, sub_dir / page_fn)
    lines = [page_fn, f"size: {atlas_im.width},{atlas_im.height}", "format: RGBA8888", "filter: Linear,Linear", "repeat: none"]
    for r in regions:
        lines.extend([r["name"], "  rotate: false", f"  xy: {r['x']}, {r['y']}", f"  size: {r['w']}, {r['h']}",
                      f"  orig: {r['orig_w']}, {r['orig_h']}", f"  offset: {r['off_x']}, {r['off_y']}", "  index: -1"])
    atlas_im.close()
    _append_atlas_page_to_submodel(sub_dir, cfg, page_fn, "\n".join(lines))

    # Read exact 24.5s Unity Legacy Animation curves
    train_clip = _read_legacy_clip(CDN_ROOT / "14_effect/battle/_batch10.ab", -5162253395483497230)
    light_clip = _read_legacy_clip(CDN_ROOT / "14_effect/battle/_batch10.ab", -7181681618139761588)
    T_train = 24.5

    tr_sc_root = next((c["curve"]["m_Curve"] for c in train_clip["m_ScaleCurves"] if c["path"] == ""), [])
    tr_sc_door = next((c["curve"]["m_Curve"] for c in train_clip["m_ScaleCurves"] if c["path"] == "Door/Image_Door_02"), [])
    tr_ax = next((c["curve"]["m_Curve"] for c in train_clip["m_FloatCurves"] if c["path"] == "" and c["attribute"] == "m_AnchoredPosition.x"), [])
    tr_ay = next((c["curve"]["m_Curve"] for c in train_clip["m_FloatCurves"] if c["path"] == "" and c["attribute"] == "m_AnchoredPosition.y"), [])
    tr_cg_a = next((c["curve"]["m_Curve"] for c in train_clip["m_FloatCurves"] if c["path"] == "" and c["attribute"] == "m_Alpha"), [])
    tr_lgt_a = next((c["curve"]["m_Curve"] for c in train_clip["m_FloatCurves"] if c["path"] == "Image_Light" and c["attribute"] == "m_Color.a"), [])
    dr_ax = next((c["curve"]["m_Curve"] for c in train_clip["m_FloatCurves"] if c["path"] == "Door/Image_Door_02" and c["attribute"] == "m_AnchoredPosition.x"), [])
    dr_ay = next((c["curve"]["m_Curve"] for c in train_clip["m_FloatCurves"] if c["path"] == "Door/Image_Door_02" and c["attribute"] == "m_AnchoredPosition.y"), [])
    pl_lgt_a = next((c["curve"]["m_Curve"] for c in light_clip["m_FloatCurves"] if c["path"] == "Image_Light_01" and c["attribute"] == "m_Color.a"), [])

    # Extend existing scene_back idle to 24.5s cleanly
    idle_anim = skel["animations"].setdefault("idle", {})
    old_dur = animation_duration(idle_anim)
    _extend_existing_idle_to(idle_anim, old_dur, T_train)
    b_anims = idle_anim.setdefault("bones", {})
    s_anims = idle_anim.setdefault("slots", {})
    skin_att = skel["skins"][0]["attachments"]

    # Insert lights + train RIGHT AFTER st_s05 (Mid/Image_04), BEFORE st_s05_front (Image_05..Image_08)!
    insert_slot_idx = next((i + 1 for i, s in enumerate(skel["slots"]) if s["name"] == "st_s05"), len(skel["slots"]))
    new_slots = []

    # Exact Unity RectTransform hierarchy for Anim_Train (size=1700x900, pivot=0.5,0.5)
    # -> Door (anchMin/Max=(1.0,0.5) => +850.0, anchPos=(-556.7,-121.4), size=(128.49,506.77), pivot=(1.0,0.5))
    #    => Door pivot in Anim_Train local coords = (+293.3, -121.4); Door center = (+229.055, -121.4)
    # -> Image_Door_02 (anchMin/Max=(1.0, 0.509866) => offset (0, +5.0) from Door pivot, pivot=(1.0,0.5) => sprite center at (-46.0, 0))
    # -> Image_Door_01 (anchMin/Max=(0.5,0.5) => Door center (+229.055,-121.4) + anchPos(-31.948,-8.277) = (+197.107, -129.677) in Anim_Train!)
    ox, oy = coord_fn(0.0, 0.0)
    skel["bones"].append({"name": "sm_train_root", "parent": "root", "x": round(ox, 2), "y": round(oy, 2)})
    skel["bones"].append({"name": "sm_door_root", "parent": "sm_train_root", "x": round(293.3 / p_ux, 2), "y": round(-116.4 / p_uy, 2)})
    skel["bones"].append({"name": "sm_door_02", "parent": "sm_door_root", "x": 0.0, "y": 0.0})

    # Sample train root at all unique curve timestamps + fine approach/depart steps for exact cubic/linear motion
    key_ts = sorted({
        round(float(k["time"]), 4)
        for grp in (tr_sc_root, tr_ax, tr_ay, tr_cg_a, tr_lgt_a)
        for k in grp
    } | {round(t, 4) for t in np.linspace(0.567, 5.833, 24)} | {round(t, 4) for t in np.linspace(17.833, 24.5, 24)})

    b_anims["sm_train_root"] = {
        "translate": [
            {"time": t, "x": round(_eval_unity_curve(tr_ax, t, 0.0) / p_ux, 2), "y": round(_eval_unity_curve(tr_ay, t, 33.0) / p_uy, 2)}
            for t in key_ts
        ],
        "scale": [
            {"time": t, "x": round(_eval_unity_vec_curve(tr_sc_root, t)[0], 4), "y": round(_eval_unity_vec_curve(tr_sc_root, t)[1], 4)}
            for t in key_ts
        ],
    }

    door_ts = sorted({round(float(k["time"]), 4) for grp in (tr_sc_door, dr_ax, dr_ay) for k in grp} | {0.0, T_train})
    b_anims["sm_door_02"] = {
        "translate": [
            {"time": t, "x": round(_eval_unity_curve(dr_ax, t, 12.784) / p_ux, 2), "y": round(_eval_unity_curve(dr_ay, t, -8.402) / p_uy, 2)}
            for t in door_ts
        ],
        "scale": [
            {"time": t, "x": round(_eval_unity_vec_curve(tr_sc_door, t)[0], 4), "y": round(_eval_unity_vec_curve(tr_sc_door, t)[1], 4)}
            for t in door_ts
        ],
    }

    # Add platform lights first (dk=8,9,10: behind train!)
    light_slots = []
    for nm in ("Image_Light_03", "Image_Light_02", "Image_Light_01"):
        if nm not in name_to_reg:
            continue
        im_rec = by_name[nm]
        rname, sw, sh = name_to_reg[nm]
        lx, ly = coord_fn(im_rec["wx"], im_rec["wy"])
        sname = f"sm_{sanitize_id(nm)}"
        light_slots.append({"name": sname, "bone": "root", "attachment": rname})
        skin_att[sname] = {rname: {"x": round(lx, 2), "y": round(ly, 2), "width": sw, "height": sh}}
        if nm == "Image_Light_01":
            lts = sorted({round(float(k["time"]), 4) for k in pl_lgt_a} | {0.0, T_train})
            s_anims[sname] = {
                "color": [{"time": t, "color": rgba_hex(1.0, 1.0, 1.0, _eval_unity_curve(pl_lgt_a, t, 1.0))} for t in lts]
            }

    # Add train child slots (dk=11..15: Image_Train, Door_02, Door_01, Image_Head, Image_Light)
    train_children = [
        ("Image_Train", "sm_train_root", 246.0 / p_ux, -92.0 / p_uy, False),
        ("Image_Door_02", "sm_door_02", -46.0 / p_ux, 0.0, False),
        ("Image_Door_01", "sm_train_root", 197.11 / p_ux, -129.68 / p_uy, False),
        ("Image_Head", "sm_train_root", 480.0 / p_ux, -101.5 / p_uy, False),
        ("Image_Light", "sm_train_root", 603.9 / p_ux, -268.8 / p_uy, True),
    ]
    for nm, par_b, lx, ly, has_own_alpha in train_children:
        if nm not in name_to_reg:
            continue
        rname, sw, sh = name_to_reg[nm]
        sname = f"sm_{sanitize_id(nm)}"
        new_slots.append({"name": sname, "bone": par_b, "attachment": rname})
        skin_att[sname] = {rname: {"x": round(lx, 2), "y": round(ly, 2), "width": sw, "height": sh}}
        col_kfs = []
        for t in key_ts:
            a = _eval_unity_curve(tr_cg_a, t, 1.0)
            if has_own_alpha:
                a *= _eval_unity_curve(tr_lgt_a, t, 1.0)
            col_kfs.append({"time": t, "color": rgba_hex(1.0, 1.0, 1.0, a)})
        s_anims[sname] = {"color": col_kfs}

    # Wrap ONLY the moving train in viewport ClippingAttachment so train clips cleanly at station borders!
    vp_x, vp_y, vp_w, vp_h = compute_viewport_spine_bounds(layout, 0.0)
    clip_slot = {"name": "sm_train_clip", "bone": "root", "attachment": "sm_train_clip"}
    skin_att["sm_train_clip"] = {
        "sm_train_clip": {
            "type": "clipping",
            "end": new_slots[-1]["name"],
            "vertexCount": 4,
            "vertices": [
                round(vp_x, 2), round(vp_y, 2),
                round(vp_x + vp_w, 2), round(vp_y, 2),
                round(vp_x + vp_w, 2), round(vp_y + vp_h, 2),
                round(vp_x, 2), round(vp_y + vp_h, 2),
            ],
        }
    }

    # Foreground static slice (Image_05..Image_08: station columns/bench IN FRONT OF the train!)
    front_slots = []
    if front_slice_res is not None:
        skel["bones"].append({
            "name": "st_b05_front",
            "parent": "root",
            "x": front_slice_res["x"],
            "y": front_slice_res["y"],
            "scaleX": front_slice_res["scaleX"],
            "scaleY": front_slice_res["scaleY"],
        })
        front_slots.append({"name": "st_s05_front", "bone": "st_b05_front", "attachment": "st_05_front"})
        skin_att["st_s05_front"] = {
            "st_05_front": {"x": 0.0, "y": 0.0, "width": front_slice_res["w"], "height": front_slice_res["h"]}
        }

    skel["slots"][insert_slot_idx:insert_slot_idx] = light_slots + [clip_slot] + new_slots + front_slots

    skel_p.write_text(json.dumps(skel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return f"patched_train_24.5s (slots=+{len(light_slots)+len(new_slots)+len(front_slots)+1})"


# ---------------------------------------------------------------------------
# 2. Alisa_S3: 6.1s Layer_02/Anim/Image_02 Glide + Bounce + Alpha Fade
# ---------------------------------------------------------------------------

def patch_alisa_s3(cat: dict[str, Any], indexer: AssetIndexer, repos: FastSceneRepos) -> str:
    sk = "2502_Alisa_S3"
    skin = cat[sk]
    sub_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"] / "submodels" / "scene_back"
    cfg_p = sub_dir / ".config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
    skel_p = sub_dir / cfg["skeleton"]
    skel = json.loads(skel_p.read_text(encoding="utf-8-sig"))
    if any(b["name"] == "alisa_anim_b" for b in skel["bones"]):
        return "already_patched"

    layout = inspect_bg_prefab_layout(indexer, skin)
    coord_fn, size_fn, _ = make_exact_coord_mappers(layout, 0.0)
    p = layout["person"]
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])

    # In Alisa_S3 scene_back, static images are interleaved across 4 bands:
    #   st_s00: Image_01 (dk=1)
    #   bj0:    BG_05
    #   st_s03: Layer_02/Anim/Image_02 (dk=5), Image_04 (dk=6), Image_05 (dk=7), Image_06 (dk=8)
    #   bj1:    BG_03
    #   st_s05: Image_08..11 (dk=10..13)
    #   bj2:    BG_02
    #   st_s07: Image_13..15 (dk=15..17)
    #   bj3:    BG_01
    # ONLY strip Image_02 from st_s03 (leaving st_s00, st_s05, st_s07 untouched!),
    # and mount alisa_anim_s RIGHT BEFORE st_s03 (dk=5 < Image_04 dk=6)!
    scene = _extract_unity_scene_layers(repos, indexer, skin, layout)
    pk = scene["person_key"]
    back_imgs = [im for im in scene["img_layers"] if im["draw_key"] < pk]
    excluded = [im for im in back_imgs if "/Layer_02/Anim/" in im["path"]]
    if not excluded:
        for im in scene["img_layers"]:
            try:
                im["img"].close()
            except Exception:
                pass
        return "no_anim_sprite_found"

    st03_kept = [im for im in back_imgs if im["name"] in ("Image_04", "Image_05", "Image_06")]
    _replace_static_band_texture(sub_dir, skel, cfg, "st_s03", st03_kept, layout)

    for im in scene["img_layers"]:
        if im not in excluded:
            try:
                im["img"].close()
            except Exception:
                pass

    im_rec = excluded[0]
    im_pma = to_pma(im_rec["img"])
    im_rec["img"].close()
    cr, ow, oh, ox, oy = trim_sprite(im_pma, 1)
    rname = "alisa_anim_img02"
    atlas_im, regions = pack_shelf([{"name": rname, "im": cr, "orig_w": ow, "orig_h": oh, "off_x": ox, "off_y": oy, "pad": 2}], pad=2)
    page_fn = "scene_back_alisa_anim.webp"
    save_exact_webp(atlas_im, sub_dir / page_fn)
    lines = [page_fn, f"size: {atlas_im.width},{atlas_im.height}", "format: RGBA8888", "filter: Linear,Linear", "repeat: none"]
    for r in regions:
        lines.extend([r["name"], "  rotate: false", f"  xy: {r['x']}, {r['y']}", f"  size: {r['w']}, {r['h']}",
                      f"  orig: {r['orig_w']}, {r['orig_h']}", f"  offset: {r['off_x']}, {r['off_y']}", "  index: -1"])
    atlas_im.close()
    _append_atlas_page_to_submodel(sub_dir, cfg, page_fn, "\n".join(lines))

    clip = _read_legacy_clip(CDN_ROOT / "14_effect/battle/_batch12.ab", -9050042189126960761)
    sc_kfs = next((c["curve"]["m_Curve"] for c in clip["m_ScaleCurves"] if c["path"] == ""), [])
    ax_kfs = next((c["curve"]["m_Curve"] for c in clip["m_FloatCurves"] if c["attribute"] == "m_AnchoredPosition.x"), [])
    ay_kfs = next((c["curve"]["m_Curve"] for c in clip["m_FloatCurves"] if c["attribute"] == "m_AnchoredPosition.y"), [])
    al_kfs = next((c["curve"]["m_Curve"] for c in clip["m_FloatCurves"] if c["attribute"] == "m_Color.a"), [])

    idle_anim = skel["animations"].setdefault("idle", {})
    T_loop = max(6.1, animation_duration(idle_anim))
    # Tile 6.1s cleanly across T_loop
    base_ox, base_oy = coord_fn(0.0, 0.0)
    sw, sh = size_fn(im_rec["w"], im_rec["h"])
    skel["bones"].append({"name": "alisa_anim_b", "parent": "root", "x": round(base_ox, 2), "y": round(base_oy, 2)})
    sname = "alisa_anim_s"
    # Insert RIGHT BEFORE st_s03 (behind Image_04..Image_06 railing/bench, in front of Image_01 & bj0!)
    ins_i = next((i for i, s in enumerate(skel["slots"]) if s["name"] == "st_s03"), len(skel["slots"]))
    skel["slots"].insert(ins_i, {"name": sname, "bone": "alisa_anim_b", "attachment": rname})
    skel["skins"][0]["attachments"][sname] = {rname: {"x": 0.0, "y": 0.0, "width": round(abs(sw), 2), "height": round(abs(sh), 2)}}

    ts_6 = sorted({round(float(k["time"]), 4) for g in (sc_kfs, ax_kfs, ay_kfs, al_kfs) for k in g} | {0.0, 6.1})
    raw_tr = [{"time": t, "x": round(_eval_unity_curve(ax_kfs, t) / p_ux, 2), "y": round(_eval_unity_curve(ay_kfs, t) / p_uy, 2)} for t in ts_6]
    raw_sc = [{"time": t, "x": round(_eval_unity_vec_curve(sc_kfs, t)[0], 4), "y": round(_eval_unity_vec_curve(sc_kfs, t)[1], 4)} for t in ts_6]
    raw_cl = [{"time": t, "color": rgba_hex(1.0, 1.0, 1.0, _eval_unity_curve(al_kfs, t, 1.0))} for t in ts_6]

    idle_anim.setdefault("bones", {})["alisa_anim_b"] = {
        "translate": _tile_keyframes(raw_tr, 6.1, T_loop),
        "scale": _tile_keyframes(raw_sc, 6.1, T_loop),
    }
    idle_anim.setdefault("slots", {})[sname] = {
        "color": _tile_keyframes(raw_cl, 6.1, T_loop),
    }

    skel_p.write_text(json.dumps(skel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return f"patched_alisa_6.1s_into_{T_loop:.2f}s (st03_stripped=True, slot_idx={ins_i})"


# ---------------------------------------------------------------------------
# 3. Asuna_S9: 60.1s Rotating Ferris Wheel (`motianl` + `chexiang`)
# ---------------------------------------------------------------------------

def patch_asuna_s9(cat: dict[str, Any], indexer: AssetIndexer) -> str:
    sk = "604_Asuna_S9"
    skin = cat[sk]
    sub_root = SPINE_ROOT / skin["char_name"] / skin["dress_name"] / "submodels"

    # Find node indices of motianl (wheel) vs chexiang (gondola cabins) in fx_manifest.json
    mf = json.loads((UNITY_PROJ / "fx_manifest.json").read_text(encoding="utf-8-sig"))
    mf_s = next((s for s in mf["skins"] if s["skin_key"] == sk), None)
    ferris_nidxs = set()
    cabin_nidxs = set()
    for c in (mf_s or {}).get("clips") or []:
        if c["layer"] == "back":
            for i, n in enumerate(c.get("nodes") or []):
                if "/Effect/Animation/" in (n.get("path") or ""):
                    ferris_nidxs.add(i)
                    if "chexiang" in (n.get("name") or "").lower():
                        cabin_nidxs.add(i)
    if not ferris_nidxs:
        return "no_ferris_nodes"

    # Clean up any unused pivot on scene_back_1 and locate the actual scene_back* holding ferris bones
    sub_dir = None
    for cand in sorted(sub_root.glob("scene_back*")):
        cp = cand / ".config.json"
        if not cp.is_file():
            continue
        sc = json.loads(cp.read_text(encoding="utf-8-sig"))
        sk_p = cand / sc["skeleton"]
        sk_d = json.loads(sk_p.read_text(encoding="utf-8-sig"))
        has_ferris = any(any(f"_n{ni}_" in b["name"] for ni in ferris_nidxs) for b in sk_d.get("bones") or [])
        if has_ferris:
            sub_dir = cand
            break
        elif any(b["name"] == "asuna_ferris_pivot" for b in sk_d.get("bones") or []):
            # Remove unused pivot left on static-only scene_back_1
            sk_d["bones"] = [b for b in sk_d["bones"] if b["name"] != "asuna_ferris_pivot"]
            (sk_d.get("animations", {}).get("idle", {}).get("bones") or {}).pop("asuna_ferris_pivot", None)
            sk_p.write_text(json.dumps(sk_d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    if sub_dir is None:
        return "ferris_submodel_not_found"
    cfg_p = sub_dir / ".config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
    skel_p = sub_dir / cfg["skeleton"]
    skel = json.loads(skel_p.read_text(encoding="utf-8-sig"))

    # Find node indices for motianl, chexiang (pink), chexiang (1) (yellow), and star (pudding sparkle)
    chexiang_0_nidx = None
    chexiang_1_nidx = None
    star_nidx = None
    for c in (mf_s or {}).get("clips") or []:
        if c["layer"] == "back":
            for i, n in enumerate(c.get("nodes") or []):
                nm = (n.get("name") or "").strip().lower()
                if nm == "chexiang":
                    chexiang_0_nidx = i
                elif nm == "chexiang (1)":
                    chexiang_1_nidx = i
                elif nm == "star":
                    star_nidx = i

    idle_anim = skel["animations"].setdefault("idle", {})
    b_anims = idle_anim.setdefault("bones", {})
    s_anims = idle_anim.setdefault("slots", {})
    reparented = 0
    cabins_upright = 0
    already_piv = any(b["name"] == "asuna_ferris_pivot" for b in skel["bones"])

    if not already_piv:
        layout = inspect_bg_prefab_layout(indexer, skin)
        coord_fn, _, _ = make_exact_coord_mappers(layout, 0.0)
        # True world pivot = Layer_01 (-20.0, +27.0) + Animation (817.0, 344.5) = (797.0, 371.5) -> dead-center on motianl hub!
        px, py = coord_fn(797.0, 371.5)
        px, py = round(px, 2), round(py, 2)

        # Extend existing idle cleanly to ~54s/60s (exact integer multiple of old_dur closest to 60.1s!)
        old_dur = max(1.0, animation_duration(idle_anim))
        mult = max(1, int(round(60.1 / old_dur)))
        new_dur = round(old_dur * mult, 4)
        _extend_existing_idle_to(idle_anim, old_dur, new_dur)

        # Add ferris wheel pivot bone under fx_root
        skel["bones"].insert(2, {"name": "asuna_ferris_pivot", "parent": "fx_root", "x": px, "y": py})
        for b in skel["bones"]:
            bn = b["name"]
            for ni in ferris_nidxs:
                if f"_n{ni}_" in bn and b.get("parent") == "fx_root":
                    b["parent"] = "asuna_ferris_pivot"
                    if ni in cabin_nidxs:
                        b["transform"] = "noRotationOrReflection"
                        cabins_upright += 1
                    if bn in b_anims and "translate" in b_anims[bn]:
                        for kf in b_anims[bn]["translate"]:
                            kf["x"] = round(float(kf.get("x", 0.0)) - px, 2)
                            kf["y"] = round(float(kf.get("y", 0.0)) - py, 2)
                    reparented += 1
                    break

        b_anims["asuna_ferris_pivot"] = {
            "rotate": [
                {"time": 0.0, "angle": 0.0},
                {"time": round(new_dur / 3.0, 4), "angle": 240.0},
                {"time": round(2.0 * new_dur / 3.0, 4), "angle": 120.0},
                {"time": new_dur, "angle": 0.0},
            ]
        }
    else:
        new_dur = max(1.0, animation_duration(idle_anim))

    # Enforce exact official Unity ShapeModule.arc.mode = BurstSpread (3) for both 10-cabin rings!
    # Official wheel angle = 297.42° (-62.58°); chexiang TF rotZ = +0.043°; chexiang (1) TF rotZ = +16.043°.
    # Radius = 14.99 * 30 / 0.57 = 788.95 spine px (exact match to motianl rim).
    wheel_ang = 297.42
    for b in skel["bones"]:
        if "_n3_" in b["name"] and b["name"] in b_anims and b_anims[b["name"]].get("rotate"):
            wheel_ang = float(b_anims[b["name"]]["rotate"][0].get("angle", 297.42))
            break
    orbit_r = 788.95
    cabins_spread = 0
    for c_nidx, rot_off_deg in ((chexiang_0_nidx, 0.043), (chexiang_1_nidx, 16.043)):
        if c_nidx is None:
            continue
        ring_bones = sorted(
            [b for b in skel["bones"] if f"_n{c_nidx}_" in b["name"]],
            key=lambda b: b["name"],
        )
        if not ring_bones:
            continue
        step_deg = 360.0 / len(ring_bones)
        for k, b in enumerate(ring_bones):
            bn = b["name"]
            b["parent"] = "asuna_ferris_pivot"
            b["transform"] = "noRotationOrReflection"
            ang_rad = math.radians(wheel_ang + rot_off_deg + k * step_deg)
            cx = round(orbit_r * math.cos(ang_rad), 2)
            cy = round(orbit_r * math.sin(ang_rad), 2)
            if bn in b_anims and "translate" in b_anims[bn]:
                for kf in b_anims[bn]["translate"]:
                    kf["x"] = cx
                    kf["y"] = cy
                cabins_spread += 1

    # Align pudding sparkle (`star`, official startDelay=0.9s, life=2.0s, period=6.0s) to gb05_add (`saoguang` 0.06..1.50s)
    star_shifted = False
    if star_nidx is not None:
        star_bones = [b["name"] for b in skel["bones"] if f"_n{star_nidx}_" in b["name"]]
        for sbn in star_bones:
            att_kfs = (s_anims.get(sbn) or {}).get("attachment") or []
            first_on = next((float(k["time"]) for k in att_kfs if k.get("name")), None)
            if first_on is not None and abs((first_on % 6.0) - 0.9) > 0.05:
                delta = 0.9 - (first_on % 6.0)
                # Shift bone translate/scale/rotate timelines
                ba = b_anims.get(sbn) or {}
                for track_key, klist in ba.items():
                    if not isinstance(klist, list):
                        continue
                    new_kl = []
                    for kf in klist:
                        nk = dict(kf)
                        nt = round(float(nk.get("time", 0.0)) + delta, 4)
                        if nt >= 0.0:
                            nk["time"] = nt
                            new_kl.append(nk)
                    if new_kl:
                        new_kl[-1].pop("curve", None)
                        ba[track_key] = new_kl
                # Shift slot attachment/color timelines while preserving t=0.0 hidden sentinel
                sa = s_anims.get(sbn) or {}
                if "attachment" in sa:
                    new_att = [{"time": 0.0, "name": None}]
                    for kf in sa["attachment"]:
                        t0 = float(kf.get("time", 0.0))
                        if t0 == 0.0 or (kf.get("name") is None and abs(t0 % 18.0) < 1e-4):
                            continue
                        nt = round(t0 + delta, 4)
                        if nt > 0.0:
                            new_att.append({"time": nt, "name": kf.get("name")})
                    new_att.sort(key=lambda x: x["time"])
                    sa["attachment"] = new_att
                if "color" in sa:
                    new_col = [{"time": 0.0, "color": "ffffff00", "curve": "stepped"}]
                    for kf in sa["color"]:
                        t0 = float(kf.get("time", 0.0))
                        if t0 == 0.0 or (kf.get("color") == "ffffff00" and abs(t0 % 18.0) < 1e-4):
                            continue
                        nt = round(t0 + delta, 4)
                        if nt > 0.0:
                            nk = dict(kf)
                            nk["time"] = nt
                            new_col.append(nk)
                    new_col.sort(key=lambda x: x["time"])
                    if new_col:
                        new_col[-1].pop("curve", None)
                    sa["color"] = new_col
                star_shifted = True

    skel_p.write_text(json.dumps(skel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return (
        f"patched_ferris_wheel (already_piv={already_piv}, reparented={reparented}, "
        f"upright_cabins={cabins_upright}, burst_spread_cabins={cabins_spread}, "
        f"star_phase_aligned={star_shifted}, T={new_dur}s)"
    )


# ---------------------------------------------------------------------------
# 4. NicoletteLamel_S3: Infinite-FPS Native Spine 3D-Perspective Streetlamp Relay
#    (Replaces official 12-FPS choppy 60-frame flipbook with duplicate f57==f58 & missing f60)
# ---------------------------------------------------------------------------

def patch_nicolettelamel_s3(cat: dict[str, Any], indexer: AssetIndexer, repos: FastSceneRepos) -> str:
    sk = "1102_NicoletteLamel_S3"
    skin = cat[sk]
    sub_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"] / "submodels" / "scene_back"
    if not sub_dir.is_dir():
        sub_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"] / "submodels" / "scene_back_1"
    cfg_p = sub_dir / ".config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
    skel_p = sub_dir / cfg["skeleton"]
    skel = json.loads(skel_p.read_text(encoding="utf-8-sig"))
    if any(b["name"] == "nico_lamp_0" for b in skel["bones"]):
        return "already_patched"

    layout = inspect_bg_prefab_layout(indexer, skin)
    coord_fn, size_fn, _ = make_exact_coord_mappers(layout, 0.0)

    # Read 60 Sprite PPtrs from dressspine.ab AnimationClip
    env = load_ab(CDN_ROOT / "07_animations/dressspine.ab")
    pptr_list = []
    cab_name = ""
    try:
        for obj in env.objects:
            if obj.path_id == 7062648749748107738:
                tt = obj.read_typetree()
                exts = [Path(e.path).name for e in obj.assets_file.externals]
                pptr_list = (tt.get("m_ClipBindingConstant") or {}).get("pptrCurveMapping") or []
                if exts:
                    cab_name = exts[0]
                break
    finally:
        del env

    if not pptr_list or not cab_name:
        return "missing_pptr_list"

    excluded = _strip_static_paths_and_rerender_st00(
        sub_dir, skel, cfg, skin, layout, repos, indexer,
        exclude_path_substrs=("/Layer_01/ActionBg/Image_01",),
    )
    if not excluded:
        return "missing_actionbg_rect"
    im_rec = excluded[0]
    im_rec["img"].close()

    # Load unique ordered frames (skipping official duplicate f57==f58) and fit exact 3D pinhole trajectory!
    raw_frames: list[np.ndarray] = []
    seen_last = None
    orig_wh = (1149, 508)
    for pp in pptr_list:
        pid = int(pp["m_PathID"])
        if pid == seen_last:
            continue
        seen_last = pid
        sp_im = repos.get_sprite_image(cab_name, pid)
        if sp_im is None:
            continue
        rgba = sp_im.convert("RGBA")
        orig_wh = rgba.size
        raw_frames.append(np.array(rgba))
        sp_im.close()
        rgba.close()

    if len(raw_frames) < 57:
        return "insufficient_frames"

    bg_rgb = np.median(np.stack([f[..., :3] for f in raw_frames[::3]], axis=0), axis=0)
    bg_col = tuple(int(round(float(bg_rgb[..., c].mean()))) for c in range(3))  # ~(249, 249, 249)

    def _detect_lamps(arr: np.ndarray) -> list[dict[str, float]]:
        diff = np.abs(arr[..., :3].astype(np.float32) - bg_rgb).max(axis=2)
        mask = diff > 15.0
        col_has = mask.any(axis=0)
        W = len(col_has)
        runs, in_run, rs = [], False, 0
        for x in range(W):
            if col_has[x] and not in_run:
                if runs and x - runs[-1][1] <= 12:
                    rs = runs.pop()[0]
                else:
                    rs = x
                in_run = True
            elif not col_has[x] and in_run:
                runs.append((rs, x - 1))
                in_run = False
        if in_run:
            runs.append((rs, W - 1))
        objs = []
        for rx0, rx1 in runs:
            sub_m = mask[:, rx0:rx1 + 1]
            ys, xs_rel = np.where(sub_m)
            if len(xs_rel) < 25:
                continue
            xs = xs_rel + rx0
            x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
            bot_xs = xs[ys >= y1 - max(2, int((y1 - y0) * 0.05))]
            bx = float(bot_xs.mean()) if len(bot_xs) else float(xs.mean())
            top_xs = xs[ys <= y0 + max(2, int((y1 - y0) * 0.15))]
            tx = float(top_xs.mean()) if len(top_xs) else float(xs.mean())
            objs.append({
                "x0": x0, "x1": x1, "y0": y0, "y1": y1,
                "w": float(x1 - x0 + 1), "h": float(y1 - y0 + 1),
                "bx": bx, "by": float(y1),
                "tilt": float(np.degrees(np.arctan2(tx - bx, max(1.0, float(y1 - y0))))),
            })
        objs.sort(key=lambda o: o["bx"])
        return objs

    all_det = [_detect_lamps(arr) for arr in raw_frames]
    P_steps = 60.0
    s_all = np.concatenate([np.arange(0, len(raw_frames), dtype=np.float64), np.arange(0, 57, dtype=np.float64) + P_steps])
    h_all = np.concatenate([
        [all_det[f][0 if f < 50 else 1]["h"] for f in range(len(raw_frames))],
        [all_det[f][1 if f < 50 else 2]["h"] for f in range(57)],
    ]).astype(np.float64)
    bx_all = np.concatenate([
        [all_det[f][0 if f < 50 else 1]["bx"] for f in range(len(raw_frames))],
        [all_det[f][1 if f < 50 else 2]["bx"] for f in range(57)],
    ]).astype(np.float64)
    by_all = np.concatenate([
        [all_det[f][0 if f < 50 else 1]["by"] for f in range(len(raw_frames))],
        [all_det[f][1 if f < 50 else 2]["by"] for f in range(57)],
    ]).astype(np.float64)
    tilt_all = np.concatenate([
        [all_det[f][0 if f < 50 else 1]["tilt"] for f in range(len(raw_frames))],
        [all_det[f][1 if f < 50 else 2]["tilt"] for f in range(57)],
    ]).astype(np.float64)

    # Exact 3D pinhole fit (h rms=0.55px, bx rms=0.13px, by rms=0.34px, tilt rms=0.09 deg!)
    c1, c0 = np.polyfit(s_all, 1.0 / h_all, 1)
    h_fit = 1.0 / (c0 + c1 * s_all)
    p_bx = np.polyfit(h_fit, bx_all, 2)
    p_by = np.polyfit(h_fit, by_all, 1)
    p_tilt = np.polyfit(h_fit, tilt_all, 2)

    # Extract crisp high-res upright streetlamp sprite from frame 42 (h~368px) with clean color-matting alpha!
    fi_ref = 42
    o_ref = all_det[fi_ref][1]
    ref_arr = raw_frames[fi_ref]
    pad = 12
    x0, y0 = max(0, int(o_ref["x0"]) - pad), max(0, int(o_ref["y0"]) - pad)
    x1, y1 = min(ref_arr.shape[1], int(o_ref["x1"]) + pad), min(ref_arr.shape[0], int(o_ref["y1"]) + pad)
    patch = ref_arr[y0:y1, x0:x1, :3].astype(np.float32)
    bg_val = float(sum(bg_col)) / 3.0
    dist = np.maximum(0.0, bg_val - patch).max(axis=2)
    alpha = np.clip((dist - 4.0) / 18.0, 0.0, 1.0)
    fg = np.where(alpha[..., None] > 0.05, (patch - (1.0 - alpha[..., None]) * bg_val) / np.maximum(alpha[..., None], 0.05), 0.0)
    fg = np.clip(fg, 0.0, 255.0)
    lamp_im = Image.fromarray(np.dstack([fg, alpha * 255.0]).astype(np.uint8), "RGBA")

    piv_x = float(o_ref["bx"]) - x0
    piv_y = float(o_ref["by"]) - y0
    rot_im = lamp_im.rotate(float(o_ref["tilt"]), resample=Image.Resampling.BICUBIC, center=(piv_x, piv_y), expand=False)
    ra = np.array(rot_im)
    ys, xs = np.where(ra[..., 3] > 8)
    cx0, cx1, cy0, cy1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    tight_lamp = rot_im.crop((cx0, cy0, cx1 + 1, cy1 + 1))
    lamp_w, lamp_h = tight_lamp.size
    lamp_piv_x = piv_x - cx0
    lamp_piv_y = piv_y - cy0

    # Pack 16x16 pure sky quad + 1 crisp high-res streetlamp sprite onto ONE tiny lossless PMA WebP page (~15 KB!)
    sky_im = to_pma(Image.new("RGBA", (16, 16), (*bg_col, 255)))
    lamp_pma = to_pma(tight_lamp)
    pack_items = [
        {"name": "nico_sky", "im": sky_im, "orig_w": 16, "orig_h": 16, "off_x": 0, "off_y": 0, "pad": 2},
        {"name": "nico_lamp", "im": lamp_pma, "orig_w": lamp_w, "orig_h": lamp_h, "off_x": 0, "off_y": 0, "pad": 2},
    ]
    atlas_im, regs = pack_shelf(pack_items, pad=2)
    page_fn = "scene_back_nico_lamps.webp"
    save_exact_webp(atlas_im, sub_dir / page_fn)
    atl_lines = [page_fn, f"size: {atlas_im.width},{atlas_im.height}", "format: RGBA8888", "filter: Linear,Linear", "repeat: none"]
    for r in regs:
        atl_lines.extend([
            r["name"], "  rotate: false", f"  xy: {r['x']}, {r['y']}", f"  size: {r['w']}, {r['h']}",
            f"  orig: {r['orig_w']}, {r['orig_h']}", f"  offset: {r['off_x']}, {r['off_y']}", "  index: -1",
        ])
    atlas_im.close()
    _append_atlas_page_to_submodel(sub_dir, cfg, page_fn, "\n".join(atl_lines))

    # Mount parent ActionBg bone + 3 continuous relay lamp bones right BEFORE st_s00, clipped cleanly to st_s00 rect!
    cx, cy = coord_fn(im_rec["wx"], im_rec["wy"])
    sw, sh = size_fn(im_rec["w"], im_rec["h"])
    skel["bones"].append({
        "name": "nico_actionbg_b",
        "parent": "root",
        "x": round(cx, 2),
        "y": round(cy, 2),
        "scaleX": round(abs(sw) / max(1.0, float(orig_wh[0])), 6),
        "scaleY": round(abs(sh) / max(1.0, float(orig_wh[1])), 6),
    })
    for k in range(3):
        skel["bones"].append({"name": f"nico_lamp_{k}", "parent": "nico_actionbg_b", "x": 0.0, "y": 0.0})

    ins_i = next((i for i, s in enumerate(skel["slots"]) if s["name"] == "st_s00"), 0)
    st_slot = next((s for s in skel["slots"] if s["name"] == "st_s00"), None)
    new_slots = [{"name": "nico_sky_slot", "bone": "nico_actionbg_b", "attachment": "nico_sky"}]
    for k in range(3):
        new_slots.append({"name": f"nico_lamp_slot_{k}", "bone": f"nico_lamp_{k}", "attachment": "nico_lamp"})

    if st_slot:
        st_b = next((b for b in skel["bones"] if b["name"] == st_slot["bone"]), None)
        st_att = (skel["skins"][0]["attachments"].get("st_s00") or {}).get(st_slot.get("attachment") or "st_00")
        if st_b and st_att:
            bx_s0 = float(st_b.get("x", 0.0))
            by_s0 = float(st_b.get("y", 0.0))
            hw = float(st_att["width"]) * abs(float(st_b.get("scaleX", 1.0))) * 0.5
            hh = float(st_att["height"]) * abs(float(st_b.get("scaleY", 1.0))) * 0.5
            x0c, x1c, y0c, y1c = round(bx_s0 - hw, 2), round(bx_s0 + hw, 2), round(by_s0 - hh, 2), round(by_s0 + hh, 2)
            new_slots.insert(0, {"name": "nico_actionbg_clip", "bone": "root", "attachment": "nico_clip"})
            skel["skins"][0]["attachments"]["nico_actionbg_clip"] = {
                "nico_clip": {
                    "type": "clipping",
                    "end": "nico_lamp_slot_2",
                    "vertexCount": 4,
                    "vertices": [x0c, y0c, x1c, y0c, x1c, y1c, x0c, y1c],
                }
            }

    skel["slots"][ins_i:ins_i] = new_slots
    skel["skins"][0]["attachments"]["nico_sky_slot"] = {
        "nico_sky": {"x": 0.0, "y": 0.0, "width": orig_wh[0], "height": orig_wh[1]}
    }
    # Attachment offset so bone origin (0,0) sits right on the lamp pole base!
    att_lx = round(lamp_w * 0.5 - lamp_piv_x, 2)
    att_ly = round(lamp_piv_y - lamp_h * 0.5, 2)
    for k in range(3):
        skel["skins"][0]["attachments"][f"nico_lamp_slot_{k}"] = {
            "nico_lamp": {"x": att_lx, "y": att_ly, "width": lamp_w, "height": lamp_h}
        }

    # Build 3 exact continuous-phase relay timelines across T_loop (3 full seamless lamp cycles!)
    idle_anim = skel["animations"].setdefault("idle", {})
    T_loop = max(15.0, animation_duration(idle_anim))
    T_lamp = T_loop / 3.0  # ~5.3333s per lamp interval (original 5.0833s -> 4.9% match, 0% seam error!)
    b_anims = idle_anim.setdefault("bones", {})
    s_anims = idle_anim.setdefault("slots", {})

    def _eval_lamp_pose(s: float) -> tuple[float, float, float, float, float]:
        h_s = 1.0 / max(1e-5, float(c0 + c1 * s))
        bx_s = float(np.polyval(p_bx, h_s))
        by_s = float(np.polyval(p_by, h_s))
        tilt_s = float(np.polyval(p_tilt, h_s))
        lx = bx_s - orig_wh[0] * 0.5
        ly = orig_wh[1] * 0.5 - by_s
        sy = h_s / max(1.0, float(lamp_h))
        # Subtle 3D arm foreshortening (wide front-on at left s=0, narrower side-view at right s=120)
        sx_mul = float(np.clip(1.22 - 0.28 * (s / 120.0), 0.84, 1.26))
        sx = sy * sx_mul
        rot = -tilt_s  # Spine +angle is CCW; +tilt leans right (CW)
        return (round(lx, 2), round(ly, 2), round(sx, 4), round(sy, 4), round(rot, 2))

    # Active span: u in [0, 150] => s = u - 20 in [-20, +130]; invisible reset buffer u in (150, 180)
    # Sample 120 uniform keyframes over T_loop (dt ~ 0.133s -> <0.08px spline error at 60/120/240 FPS!)
    N_kf = 120
    for k in range(3):
        tr_kfs, sc_kfs, rt_kfs, col_kfs = [], [], [], []
        prev_u = None
        for i in range(N_kf + 1):
            t = round(T_loop * i / N_kf, 4)
            u = ((i / N_kf) * 180.0 + k * 60.0) % 180.0
            if i == N_kf:
                u = (k * 60.0) % 180.0  # bit-exact wrap State(T_loop) == State(0)
            s_eff = min(max(u - 20.0, -20.0), 130.0)
            if u <= 150.0:
                if u < 10.0:
                    a = u / 10.0
                elif u > 146.0:
                    a = (150.0 - u) / 4.0
                else:
                    a = 1.0
                lx, ly, sx, sy, rot = _eval_lamp_pose(s_eff)
            else:
                a = 0.0
                # Hold at exit until midpoint u=165, then snap cleanly to entry s=-20 while alpha=0!
                lx, ly, sx, sy, rot = _eval_lamp_pose(130.0 if u < 165.0 else -20.0)

            # Insert stepped curve on the previous keyframe whenever crossing the hidden reset midpoint u=165!
            if prev_u is not None and ((prev_u < 165.0 <= u) or (u < prev_u and prev_u >= 165.0 and u < 5.0)):
                if prev_u < 165.0 <= u:
                    tr_kfs[-1]["curve"] = "stepped"
                    sc_kfs[-1]["curve"] = "stepped"
                    rt_kfs[-1]["curve"] = "stepped"
            prev_u = u

            tr_kfs.append({"time": t, "x": lx, "y": ly})
            sc_kfs.append({"time": t, "x": sx, "y": sy})
            rt_kfs.append({"time": t, "angle": rot})
            col_kfs.append({"time": t, "color": rgba_hex(1.0, 1.0, 1.0, a)})

        b_anims[f"nico_lamp_{k}"] = {"translate": tr_kfs, "scale": sc_kfs, "rotate": rt_kfs}
        s_anims[f"nico_lamp_slot_{k}"] = {"color": col_kfs}

    skel_p.write_text(json.dumps(skel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return f"patched_infinite_fps_3lamps (T_loop={T_loop:.2f}s, T_lamp={T_lamp:.2f}s, sprite={lamp_w}x{lamp_h})"


# ---------------------------------------------------------------------------
# 5. 4 BoneFollower SoulAction Ambient Particle Systems
# ---------------------------------------------------------------------------

BONE_FOLLOWER_SPECS = [
    ("1503_Dreizehn_S4", "51", "EffectPoint_Flower"),
    ("2201_Andrea_S2", "neishouzhi", "Beer"),
    ("2901_EtsukazuMiko_S2", "11111111111", "Yinghua"),
    ("3001_TsukinoMiyo_S2", "yueye_34", "Point"),
]


def patch_4_bone_followers(cat: dict[str, Any], indexer: AssetIndexer) -> dict[str, str]:
    """Extract the 4 BoneFollower SoulAction ambient particle systems at exact rest-pose Spine bone coords,
    export trajectories via Unity SpineParticleExporter v2, and inject into each skin's front submodel."""
    full_indexer = AssetIndexer(light=False)
    bf_skins_manifest = []
    bf_meta: dict[str, dict[str, Any]] = {}
    saved_textures: set[str] = set()
    saved_meshes: set[str] = set()
    wrap_modes: dict[str, list[int]] = {}

    for sk, bone_name, go_name in BONE_FOLLOWER_SPECS:
        skin = cat.get(sk)
        if not skin:
            continue
        skin_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"]
        main_cfg = json.loads((skin_dir / ".config.json").read_text(encoding="utf-8-sig"))
        main_skel_raw = (skin_dir / main_cfg["skeleton"]).read_bytes()
        parsed = parse_spine38_binary(main_skel_raw)
        idle_anim_nm = "idle_marry" if "idle_marry" in parsed["anims"] else ("idle" if "idle" in parsed["anims"] else parsed["anims"][0])
        bpos = eval_bone_world_positions(parsed, idle_anim_nm)
        bx, by = bpos.get(bone_name, (0.0, 0.0))

        layout = inspect_bg_prefab_layout(full_indexer, skin)
        p = layout["person"]
        p_wx, p_wy = float(p["wx"]), float(p["wy"])
        p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
        p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
        bf_wx = p_wx + bx * p_ux
        bf_wy = p_wy + by * p_uy

        ent = resolve_soul_action_entity(full_indexer, skin)
        if ent is None:
            continue
        ent_objs, ent_gid = ent
        # Walk strictly inside this SoulAction entity subtree to find the exact BoneFollower GO!
        target_gid = None
        stack = [ent_gid]
        while stack and target_gid is None:
            cg = stack.pop()
            cgo = ent_objs[cg].read()
            if cgo.m_Name == go_name:
                for c in cgo.m_Component:
                    co = ent_objs.get(c.component.path_id)
                    if co and co.type.name == "MonoBehaviour":
                        try:
                            if co.read_typetree().get("boneName") == bone_name:
                                target_gid = cg
                                break
                        except Exception:
                            pass
                if target_gid is not None:
                    break
            for c in cgo.m_Component:
                co = ent_objs.get(c.component.path_id)
                if co and co.type.name in ("RectTransform", "Transform"):
                    rt = co.read()
                    if hasattr(rt, "m_Children"):
                        for ch in rt.m_Children:
                            if ch.path_id in ent_objs:
                                stack.append(ent_objs[ch.path_id].read().m_GameObject.path_id)
        if target_gid is None:
            continue

        world_scale_bone = max(1.0, p_ux * 100.0)
        nodes = _extract_ps_nodes(
            indexer=full_indexer,
            objs=ent_objs,
            root_gid=target_gid,
            base_pos=(bf_wx, bf_wy, 0.0),
            base_scale=(world_scale_bone, world_scale_bone, 1.0),
            base_rot=(0.0, 0.0, 0.0, 1.0),
            saved_textures=saved_textures,
            skip_harmonious=True,
            saved_meshes=saved_meshes,
            ignore_root_scale_rot=True,
            fixed_layer="front",
            tex_wrap_modes=wrap_modes,
        )
        if not nodes:
            continue
        bf_skins_manifest.append({
            "skin_key": sk,
            "canvas_w": int(layout["canvas_w"]),
            "canvas_h": int(layout["canvas_h"]),
            "cam_x": float(layout["cam_x"]),
            "cam_y": float(layout["cam_y"]),
            "person_wx": p_wx,
            "person_wy": p_wy,
            "ui_per_spine_x": p_ux,
            "ui_per_spine_y": p_uy,
            "person_z_deg": float(p.get("z_deg", 0.0)),
            "fps": 20,
            "output_dir": str(TOOLS_DIR / "_batch_fx_bonefollower" / sk),
            "clips": [{
                "clip": "idle_bf",
                "layer": "front",
                "duration": 16.0,
                "fps": 20,
                "warmup": 4.0,
                "crossfadeIdle": False,
                "useZeroCrossfade": False,
                "nodes": nodes,
            }],
        })
        bf_meta[sk] = {"skin": skin, "layout": layout, "bone_name": bone_name, "bx": bx, "by": by, "node_cnt": len(nodes)}

    if not bf_skins_manifest:
        return {}

    bf_mf_p = UNITY_PROJ / "_fx_bonefollower_manifest.json"
    bf_mf_p.write_text(json.dumps({"skins": bf_skins_manifest}, ensure_ascii=False), encoding="utf-8")
    bf_exp_dir = TOOLS_DIR / "_batch_fx_bonefollower_exp"
    bf_exp_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([
        UNITY_EXE, "-batchmode", "-quit", "-nographics", "-projectPath", str(UNITY_PROJ),
        "-executeMethod", "SoulTideSpineParticleExporter.ExportBatch",
        "-fxManifest", str(bf_mf_p),
        "-outDir", str(bf_exp_dir),
        "-logFile", str(UNITY_PROJ / "_log_bonefollower_exp.log"),
    ])
    if r.returncode != 0:
        return {"error": f"Unity BoneFollower export rc={r.returncode}"}

    tex_index = build_tex_index()
    out_status: dict[str, str] = {}
    for sk, meta in bf_meta.items():
        exp_p = bf_exp_dir / f"{sk}.json"
        if not exp_p.is_file():
            out_status[sk] = "export_missing"
            continue
        exp_data = json.loads(exp_p.read_text(encoding="utf-8-sig"))
        ec = (exp_data.get("clips") or [None])[0]
        if not ec or not ec.get("tracks"):
            out_status[sk] = "no_tracks"
            continue

        skin = meta["skin"]
        layout = meta["layout"]
        skin_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"]
        sub_root = skin_dir / "submodels"
        front_dir = sub_root / "scene_front"
        if not front_dir.is_dir():
            front_dir = sub_root / "scene_front_1"

        # If skin already has scene_front JSON, inject directly into scene_front!
        # Otherwise create a lightweight scene_front submodel and mount it at the next free positive slot!
        coord_fn, size_fn, _ = make_exact_coord_mappers(layout, 0.0)
        vp_bounds = compute_viewport_spine_bounds(layout, 0.0)

        # Pack textures for BF particles
        p_items = []
        tk2r: dict[tuple[str, int, int, bool], list[str]] = {}
        rc = 0
        for n in ec["nodes"]:
            tn = (n.get("tex") or "").strip()
            tp = tex_index.get(tn.lower()) or tex_index.get(Path(tn).stem.lower())
            if tp is None:
                continue
            tx, ty = max(1, int(n.get("tiles_x", 1))), max(1, int(n.get("tiles_y", 1)))
            is_uv = bool(n.get("is_uv_scroll", False))
            tkey = (tp.stem.lower(), tx, ty, is_uv)
            if tkey in tk2r:
                continue
            im_pma = to_pma(Image.open(tp))
            regs = []
            if is_uv or (tx == 1 and ty == 1):
                rn = f"bf{rc}_{sanitize_id(tp.stem)[:14]}"
                rc += 1
                cr, ow, oh, ox, oy = (im_pma, im_pma.width, im_pma.height, 0, 0) if is_uv else trim_sprite(im_pma, 1)
                p_items.append({"name": rn, "im": cr, "orig_w": ow, "orig_h": oh, "off_x": ox, "off_y": oy, "pad": 2})
                regs.append(rn)
            else:
                cwt, cht = max(1, im_pma.width // tx), max(1, im_pma.height // ty)
                for ti in range(tx * ty):
                    cx, cy = ti % tx, ti // tx
                    cr, ow, oh, ox, oy = trim_sprite(im_pma.crop((cx * cwt, cy * cht, (cx + 1) * cwt, (cy + 1) * cht)), 1)
                    rn = f"bf{rc}_{sanitize_id(tp.stem)[:10]}_t{ti}"
                    rc += 1
                    p_items.append({"name": rn, "im": cr, "orig_w": ow, "orig_h": oh, "off_x": ox, "off_y": oy, "pad": 2})
                    regs.append(rn)
            tk2r[tkey] = regs
        if not p_items:
            out_status[sk] = "no_textures"
            continue

        if front_dir.is_dir() and (front_dir / ".config.json").is_file():
            cfg_p = front_dir / ".config.json"
            cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
            skel_p = front_dir / cfg["skeleton"]
            skel = json.loads(skel_p.read_text(encoding="utf-8-sig"))
            if any(b["name"].startswith("bf0_") for b in skel["bones"]):
                out_status[sk] = "already_patched"
                continue
            sp_im, sp_regs = pack_shelf(p_items, pad=2)
            fn = f"{front_dir.name}_bf_pt.webp"
            save_exact_webp(sp_im, front_dir / fn)
            lines = [fn, f"size: {sp_im.width},{sp_im.height}", "format: RGBA8888", "filter: Linear,Linear", "repeat: none"]
            for r_reg in sp_regs:
                lines.extend([r_reg["name"], "  rotate: false", f"  xy: {r_reg['x']}, {r_reg['y']}", f"  size: {r_reg['w']}, {r_reg['h']}",
                              f"  orig: {r_reg['orig_w']}, {r_reg['orig_h']}", f"  offset: {r_reg['off_x']}, {r_reg['off_y']}", "  index: -1"])
            sp_im.close()
            _append_atlas_page_to_submodel(front_dir, cfg, fn, "\n".join(lines))

            idle_anim = skel["animations"].setdefault("idle", {})
            T_loop = max(12.0, animation_duration(idle_anim))
            emit_native_fx_nodes_into_skeleton(
                clip=ec, node_indices=None, anim_pref="bf0", parent_bone="fx_root",
                is_idle=True, T_loop=T_loop, T_sub=T_loop, repeat_cnt=1,
                tex_index=tex_index, tex_key_to_regs=tk2r,
                coord_fn=coord_fn, size_fn=size_fn, rot_offset_deg=0.0, viewport_rect=vp_bounds,
                bones=skel["bones"], slots=skel["slots"], skin_att=skel["skins"][0]["attachments"],
                bone_anims=idle_anim.setdefault("bones", {}), slot_anims=idle_anim.setdefault("slots", {}),
                total_bone_budget=120,
            )
            skel_p.write_text(json.dumps(skel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            out_status[sk] = f"injected_into_{front_dir.name} (bone={meta['bone_name']}, nodes={meta['node_cnt']})"
        else:
            # Create brand-new lightweight scene_front submodel and mount on positive slot!
            front_dir = sub_root / "scene_front"
            front_dir.mkdir(parents=True, exist_ok=True)
            sp_im, sp_regs = pack_shelf(p_items, pad=2)
            fn = "scene_front_bf.webp"
            save_exact_webp(sp_im, front_dir / fn)
            lines = ["", fn, f"size: {sp_im.width},{sp_im.height}", "format: RGBA8888", "filter: Linear,Linear", "repeat: none"]
            for r_reg in sp_regs:
                lines.extend([r_reg["name"], "  rotate: false", f"  xy: {r_reg['x']}, {r_reg['y']}", f"  size: {r_reg['w']}, {r_reg['h']}",
                              f"  orig: {r_reg['orig_w']}, {r_reg['orig_h']}", f"  offset: {r_reg['off_x']}, {r_reg['off_y']}", "  index: -1"])
            sp_im.close()
            (front_dir / "scene_front.atlas.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

            vp_x, vp_y, vp_w, vp_h = vp_bounds
            bones = [{"name": "root"}, {"name": "fx_root", "parent": "root", "x": 0.0, "y": 0.0}]
            slots: list[dict[str, Any]] = []
            skin_att: dict[str, Any] = {}
            ba: dict[str, Any] = {}
            sa: dict[str, Any] = {}
            T_loop, T_sub, rep_c = compute_native_idle_period(ec)
            emit_native_fx_nodes_into_skeleton(
                clip=ec, node_indices=None, anim_pref="bf0", parent_bone="fx_root",
                is_idle=True, T_loop=T_loop, T_sub=T_sub, repeat_cnt=rep_c,
                tex_index=tex_index, tex_key_to_regs=tk2r,
                coord_fn=coord_fn, size_fn=size_fn, rot_offset_deg=0.0, viewport_rect=vp_bounds,
                bones=bones, slots=slots, skin_att=skin_att, bone_anims=ba, slot_anims=sa,
                total_bone_budget=120,
            )
            ba["root"] = {"translate": [{"time": 0.0, "x": 0.0, "y": 0.0}, {"time": round(T_loop, 4), "x": 0.0, "y": 0.0}]}
            skel = {
                "skeleton": {"hash": f"{sk.lower()}_bf", "spine": "3.8.79", "x": vp_x, "y": vp_y, "width": vp_w, "height": vp_h},
                "bones": bones, "slots": slots,
                "skins": [{"name": "default", "attachments": skin_att}],
                "animations": {"idle": {"bones": ba, "slots": sa}},
            }
            (front_dir / "scene_front.json").write_text(json.dumps(skel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            main_cfg = json.loads((skin_dir / ".config.json").read_text(encoding="utf-8-sig"))
            base_scale = float(main_cfg.get("options", {}).get("scale_factor", 0.11) or 0.11)
            scfg = {
                "conf_ver": 1, "type": 9,
                "controllers": {"param_hit": {}, "param_loop": {}, "key_trigger": {}, "intimacy_system": {}, "slot_opacity": {}, "slot_color": {}},
                "hit_areas": [],
                "motions": {"idle": [{"name": "idle", "file": "idle", "fade_in": 0, "fade_out": 0, "file_loop": True}]},
                "options": {"id": f"{sk.lower()}_scene_front", "scale_factor": round(base_scale, 5), "position_x": 0.0, "position_y": 0.0, "tex_type": 1, "shader_type": 0, "edge_padding": False},
                "skeleton": "scene_front.json",
                "atlases": [{"atlas": "scene_front.atlas.txt", "tex_names": [Path(fn).stem], "textures": [fn]}],
            }
            (front_dir / ".config.json").write_text(json.dumps(scfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            # Mount into main skin start/reload_bg at first free positive slot (1, 2, or 3)
            old_cmd = (main_cfg.get("motions", {}).get("start") or [{}])[0].get("command", "")
            existing = []
            for seg in old_cmd.split(";"):
                toks = seg.strip().split()
                if len(toks) == 3 and toks[0] == "add_submodel":
                    existing.append((toks[1], int(toks[2])))
            used_pos = {o for _, o in existing if o > 0}
            free_o = next((o for o in (1, 2, 3) if o not in used_pos), None)
            if free_o is not None:
                existing.append(("submodels/scene_front/.config.json", free_o))
                existing.sort(key=lambda x: x[1])
                new_cmd = "; ".join(f"add_submodel {r} {o}" for r, o in existing)
                patch_all_language_configs(skin_dir, new_cmd, {})
                out_status[sk] = f"created_scene_front_at_{free_o} (bone={meta['bone_name']}, nodes={meta['node_cnt']})"
            else:
                out_status[sk] = "no_free_pos_slot"

    return out_status


def main() -> None:
    repo = FullI18nRepo()
    cat = {s["skin_key"]: s for s in build_skin_catalog(repo)}
    indexer = AssetIndexer(light=True)
    repos = FastSceneRepos(indexer)

    summary = {}
    for label, fn in (
        ("1802_SakuyaMako_S3", lambda: patch_sakuyamako_s3(cat, indexer, repos)),
        ("2502_Alisa_S3", lambda: patch_alisa_s3(cat, indexer, repos)),
        ("604_Asuna_S9", lambda: patch_asuna_s9(cat, indexer)),
        ("1102_NicoletteLamel_S3", lambda: patch_nicolettelamel_s3(cat, indexer, repos)),
        ("BoneFollowers_4", lambda: patch_4_bone_followers(cat, indexer)),
    ):
        try:
            res = fn()
            summary[label] = res
            print(f"[OK] {label}: {res}", flush=True)
        except Exception as exc:
            import traceback
            summary[label] = f"ERROR: {exc}"
            print(f"[ERR] {label}: {exc}\n{traceback.format_exc()}", flush=True)

    # Re-sync hide_bg / show_bg across all 109 skins!
    import add_spine_bg_toggle
    add_spine_bg_toggle.main()
    out_p = SCRIPTS_DIR / "step7_hidden_anims_report.json"
    out_p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nStep 7 Report -> {out_p}")


if __name__ == "__main__":
    main()
