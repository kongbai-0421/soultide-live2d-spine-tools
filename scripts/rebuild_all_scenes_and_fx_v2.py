r"""Grand Unified Spine Scene & Hybrid FX Assembler v2 (All 109 Dressed Skins).

Systemically fixes ALL layer-order errors, texture wrap artifacts, dropped `bj_*` sub-spines,
missing `bg_mid` layers, behind-person touch FX, and particle loop defects:

1. Exact Unity `(sort_order, -wz, global_dfs)` total ordering across ALL Unity scene elements:
   static UI `Image` / `SpriteRenderer`, animated `bj_*` Spine skeletons, `Tween*` sprites,
   60 FPS Native Spine v2 particle nodes, AND Unity Zero-Crossfade GPU FX bands.
2. Composite Interleaved Spine 3.8.79 JSON submodels (`scene_back`, `scene_front`):
   - Interleaves arbitrary static image bands (`Order=1`, `Order=3`, ...), 60 FPS Native Spine v2
     particles (Multi-Bone Torus Phase-Relay + Water-Filling), tight-cropped Zero-Crossfade GPU
     FX bands (tiled cleanly over `T_loop = m * T_gpu` with 0 extra atlas pixels), and `Tween*`
     nodes in ONE Spine 3.8 submodel slot with non-nested per-FX-run `ClippingAttachment`s!
   - When a side has `<= avail_slots` runs, keeps every `bj_*` as an untouched native binary
     `.skel.json`. When a side exceeds `avail_slots` (the 38 `dropped_bjs` skins such as
     `Aoling_S2`, `Asuna_S7`, `Gawana_S3`, `Clarice_S3`), merges excess `bj_*` losslessly via
     `spine38_binary_to_json.py` (preserving original lossless PMA `.webp` pages bit-exact!).
3. Dedicated pure Touch FX submodels (`fx_touch` on front, `fx_touch_back` on back for the 4
   behind-person trigger FX): `idle = {}` so ambient loops NEVER reset on touch and `hide_bg`
   never flashes background layers.
4. Strictly non-destructive: NEVER modifies `audio/`, `bgm/`, main Person skeleton/textures,
   or `soultide.db`. Syncs `.config.json`, `config_en.config.json`, `config_ja.config.json`.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
SCRIPTS_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本")
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
UNITY_PROJ = TOOLS_DIR / "SoulTideBatchFxUnity"
FX_MANIFEST_PATH = UNITY_PROJ / "fx_manifest.json"
GPU_PLAN_PATH = UNITY_PROJ / "fx_gpu_bands_plan.json"
GPU_FRAMES_ROOT = TOOLS_DIR / "_batch_fx_gpu_v2"
PARTICLE_EXPORT_DIR = TOOLS_DIR / "_batch_fx_particles_v2"
FALLBACK_EXPORT_DIR = TOOLS_DIR / "_batch_fx_particles"
REPORT_PATH = SCRIPTS_DIR / "rebuild_all_v2_report.json"

for _p in (str(TOOLS_DIR), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from batch_fx_exporter import (
    AssetIndexer,
    FullI18nRepo,
    _is_censor_cloud,
    _node_local_tf,
    _qmul,
    _qrot,
    build_skin_catalog,
    inspect_bg_prefab_layout,
    resolve_bg_prefab_root,
    resolve_soul_action_entity,
)
from batch_spine_builder import (
    _SCENE_LAYOUT_OVERRIDES,
    _dedup_bj_candidates,
    _extract_spine_unit_from_ab,
    _extract_unity_scene_layers,
    _render_nine_slice,
    _save_lossless_pma_webp,
    parse_spine38_binary,
)
from convert_fx_to_native_spine import (
    _emit_tween_nodes_into_skeleton,
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
from rebuild_spine_scenes_from_art_prefabs import FastSceneRepos
from spine38_binary_to_json import (
    merge_spine38_into_composite,
    prefix_atlas_text,
    spine38_binary_to_json,
)
from spine_fx_submodel_packer import (
    _build_atlas_text,
    _pack_skyline,
    _process_frame_task,
)


# ---------------------------------------------------------------------------
# Unified Unity Global DFS Extractor (aligns Image, BJ, Tween, ParticleSystem)
# ---------------------------------------------------------------------------

def extract_unified_ps_draw_keys(
    indexer: AssetIndexer,
    skin: dict[str, Any],
) -> tuple[dict[str, tuple[int, float, int]], list[tuple[str, tuple[int, float, int]]]]:
    """Walk BgPrefab + SoulAction using the exact same DFS numbering as `_extract_unity_scene_layers`
    and return `(path_to_draw_key, ordered_ps_list)` for all active ParticleSystems."""
    objs, gid = resolve_bg_prefab_root(indexer, skin)
    ent_res = resolve_soul_action_entity(indexer, skin)

    dfs_seq = 0
    ps_by_path: dict[str, tuple[int, float, int]] = {}
    ps_ordered: list[tuple[str, tuple[int, float, int]]] = []
    person_found = False

    def walk(
        g: int,
        depth: int,
        ppos: tuple[float, float, float],
        pscale: tuple[float, float, float],
        pq: tuple[float, float, float, float],
        path: str,
        cur_sort_order: int,
        cur_objs: dict[int, Any] | None = None,
        from_entity: bool = False,
    ) -> None:
        nonlocal dfs_seq, person_found
        c_objs = cur_objs if cur_objs is not None else objs
        go = c_objs[g].read()
        if not go.m_IsActive:
            return
        low = go.m_Name.lower()
        if "harmonious" in low or "hitarea" in low or "cv_point" in low or _is_censor_cloud(low):
            return

        rt, _is_rect, (lx, ly, lz), (sx, sy, sz), lq = _node_local_tf(go, c_objs, ignore_root_pos=(depth == 0))
        rx, ry, rz = _qrot(pq, (lx * pscale[0], ly * pscale[1], lz * pscale[2]))
        wx, wy, wz = ppos[0] + rx, ppos[1] + ry, ppos[2] + rz
        wsx, wsy, wsz = pscale[0] * sx, pscale[1] * sy, pscale[2] * sz
        wq = _qmul(pq, lq)

        canvas_ord: int | None = None
        mono_ord: int | None = None
        if not from_entity:
            for c in go.m_Component:
                co = c_objs.get(c.component.path_id)
                if not co:
                    continue
                if co.type.name == "Canvas":
                    try:
                        ctt = co.read_typetree()
                        if ctt.get("m_OverrideSorting"):
                            canvas_ord = int(ctt.get("m_SortingOrder", 0))
                    except Exception:
                        pass
                elif co.type.name == "MonoBehaviour":
                    try:
                        tt = co.read_typetree()
                        if "Order" in tt and tt.get("m_Enabled", 1):
                            mono_ord = int(tt["Order"])
                    except Exception:
                        pass
            sort_order = mono_ord if mono_ord is not None else (canvas_ord if canvas_ord is not None else cur_sort_order)
        else:
            sort_order = cur_sort_order

        full_path = f"{path}/{go.m_Name}" if path else go.m_Name
        ps_by_path.setdefault(full_path, (sort_order, -round(wz, 3), dfs_seq + 1))
        ps_by_path.setdefault("/" + full_path, (sort_order, -round(wz, 3), dfs_seq + 1))
        for c in go.m_Component:
            co = c_objs.get(c.component.path_id)
            if not co:
                continue
            if co.type.name == "ParticleSystem":
                dfs_seq += 1
                dk = (sort_order, -round(wz, 3), dfs_seq)
                ps_by_path[full_path] = dk
                ps_by_path["/" + full_path] = dk
                ps_ordered.append((full_path, dk))
            elif co.type.name == "SpriteRenderer":
                dfs_seq += 1
            elif co.type.name == "MonoBehaviour":
                try:
                    tt = co.read_typetree()
                    if "m_Sprite" in tt and tt.get("m_Enabled", 1):
                        if (tt.get("m_Sprite") or {}).get("m_PathID", 0) != 0:
                            dfs_seq += 1
                    elif "skeletonDataAsset" in tt and tt.get("m_Enabled", 1):
                        dfs_seq += 1
                        if "person" in low and not any(t in low for t in ("_bg_", "_bj_")):
                            person_found = True
                except Exception:
                    pass

        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in c_objs:
                    cg = c_objs[ch.path_id].read().m_GameObject.path_id
                    walk(cg, depth + 1, (wx, wy, wz), (wsx, wsy, wsz), wq, full_path, sort_order, cur_objs=c_objs, from_entity=from_entity)

        if not from_entity and depth == 1 and go.m_Name == "Point_Root" and not person_found and ent_res is not None:
            ent_objs, ent_gid = ent_res
            walk(ent_gid, 0, (wx, wy, wz), (wsx, wsy, wsz), wq, f"{full_path}/SoulSpineCell/SpineRoot", sort_order, cur_objs=ent_objs, from_entity=True)

    walk(gid, 0, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), "", 0)
    return ps_by_path, ps_ordered


# ---------------------------------------------------------------------------
# Static Image Band Compositor (returns trimmed PMA Image + Spine transform)
# ---------------------------------------------------------------------------

def compute_canvas_crop_rect(layout: dict[str, Any], counter_rot_deg: float) -> tuple[int, int, int, int]:
    cw, ch = int(layout["canvas_w"]), int(layout["canvas_h"])
    cam_x, cam_y = float(layout["cam_x"]), float(layout["cam_y"])
    lim = layout.get("limit_rect") or {}
    cx0, cy0, cx1, cy1 = 0, 0, cw, ch
    if abs(counter_rot_deg) <= 0.25:
        if "x0" in lim and "x1" in lim:
            lx0, lx1 = float(lim["x0"]), float(lim["x1"])
            lim_w = lx1 - lx0
            if 1600.0 <= lim_w <= 2200.0 and ((cam_x + cw / 2.0) - lx1 > 30.0 or lx0 - (cam_x - cw / 2.0) > 30.0):
                cx0 = max(0, min(cw, int(round((lx0 - cam_x) + cw / 2.0))))
                cx1 = max(cx0, min(cw, int(round((lx1 - cam_x) + cw / 2.0))))
        if "y0" in lim and "y1" in lim:
            ly0, ly1 = float(lim["y0"]), float(lim["y1"])
            lim_h = ly1 - ly0
            if 1000.0 <= lim_h <= 1700.0 and ((cam_y + ch / 2.0) - ly1 > 30.0 or ly0 - (cam_y - ch / 2.0) > 30.0):
                cy0 = max(0, min(ch, int(round((cam_y - ly1) + ch / 2.0))))
                cy1 = max(cy0, min(ch, int(round((cam_y - ly0) + ch / 2.0))))
    return cx0, cy0, cx1, cy1


def compute_viewport_spine_bounds(
    layout: dict[str, Any],
    counter_rot_deg: float,
    crop_rect: tuple[int, int, int, int] | None = None,
) -> tuple[float, float, float, float]:
    cw, ch = float(layout["canvas_w"]), float(layout["canvas_h"])
    cam_x, cam_y = float(layout["cam_x"]), float(layout["cam_y"])
    bx0, by0, bx1, by1 = crop_rect if crop_rect is not None else compute_canvas_crop_rect(layout, counter_rot_deg)
    tw_out = max(4.0, float(bx1 - bx0))
    th_out = max(4.0, float(by1 - by0))
    p = layout["person"]
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
    base_dx = cam_x - float(p["wx"])
    base_dy = cam_y - float(p["wy"])
    if abs(counter_rot_deg) > 0.25:
        rad = math.radians(-counter_rot_deg)
        ca, sa = math.cos(rad), math.sin(rad)
        base_dx, base_dy = ca * base_dx - sa * base_dy, sa * base_dx + ca * base_dy
    trim_dx = ((bx0 + bx1) / 2.0) - cw / 2.0
    trim_dy = ch / 2.0 - ((by0 + by1) / 2.0)
    cx = (base_dx + trim_dx) / max(1e-5, p_ux)
    cy = (base_dy + trim_dy) / max(1e-5, p_uy)
    sw = tw_out / max(1e-5, p_ux)
    sh = th_out / max(1e-5, p_uy)
    return round(cx - sw / 2.0, 2), round(cy - sh / 2.0, 2), round(sw, 2), round(sh, 2)


def render_static_band_pma(
    img_layers: list[dict[str, Any]],
    layout: dict[str, Any],
    counter_rot_deg: float,
) -> dict[str, Any] | None:
    """Composite a contiguous band of Unity UI Images/SpriteRenderers into a trimmed PMA PIL Image + Spine placement."""
    if not img_layers:
        return None
    cw, ch = int(layout["canvas_w"]), int(layout["canvas_h"])
    cam_x, cam_y = float(layout["cam_x"]), float(layout["cam_y"])
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    rad_cr = math.radians(-counter_rot_deg)
    cos_cr, sin_cr = math.cos(rad_cr), math.sin(rad_cr)

    for lay in img_layers:
        im = lay["img"]
        tw = max(1, int(round(lay["w"])))
        th = max(1, int(round(lay["h"])))
        if im.size != (tw, th):
            if lay.get("img_type", 0) == 1 and lay.get("border"):
                im = _render_nine_slice(im, tw, th, lay["border"], lay["sx"], lay["sy"])
            else:
                im = im.resize((tw, th), Image.Resampling.LANCZOS)
        if lay["sx"] < 0:
            im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if lay["sy"] < 0:
            im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

        ang_deg = lay["z_deg"] - counter_rot_deg
        if abs(ang_deg) > 0.25 and abs(abs(ang_deg) - 360.0) > 0.25:
            im = im.rotate(ang_deg, resample=Image.Resampling.BICUBIC, expand=True)

        cr, cg, cb, ca = lay["color"]
        if cr < 0.99 or cg < 0.99 or cb < 0.99 or ca < 0.99:
            r, g, b, a = im.split()
            r = r.point(lambda v: int(round(v * max(0.0, min(1.0, cr)))))
            g = g.point(lambda v: int(round(v * max(0.0, min(1.0, cg)))))
            b = b.point(lambda v: int(round(v * max(0.0, min(1.0, cb)))))
            a = a.point(lambda v: int(round(v * max(0.0, min(1.0, ca)))))
            im = Image.merge("RGBA", (r, g, b, a))

        dx_w = lay["wx"] - cam_x
        dy_w = lay["wy"] - cam_y
        if abs(counter_rot_deg) > 0.25:
            dx_w, dy_w = cos_cr * dx_w - sin_cr * dy_w, sin_cr * dx_w + cos_cr * dy_w

        left = round(dx_w + (cw - im.width) / 2.0)
        top = round((-dy_w) + (ch - im.height) / 2.0)

        clip_x0, clip_y0, clip_x1, clip_y1 = 0, 0, cw, ch
        if lay.get("clip_rect") is not None:
            mx0, my0, mx1, my1 = lay["clip_rect"]
            if abs(counter_rot_deg) > 0.25:
                mcx = (mx0 + mx1) / 2.0 - cam_x
                mcy = (my0 + my1) / 2.0 - cam_y
                mcx, mcy = cos_cr * mcx - sin_cr * mcy, sin_cr * mcx + cos_cr * mcy
                mw, mh = (mx1 - mx0), (my1 - my0)
                cl_x0 = int(round(mcx - mw / 2.0 + cw / 2.0))
                cl_x1 = int(round(mcx + mw / 2.0 + cw / 2.0))
                cl_y0 = int(round(-mcy - mh / 2.0 + ch / 2.0))
                cl_y1 = int(round(-mcy + mh / 2.0 + ch / 2.0))
            else:
                cl_x0 = int(round((mx0 - cam_x) + cw / 2.0))
                cl_x1 = int(round((mx1 - cam_x) + cw / 2.0))
                cl_y0 = int(round((cam_y - my1) + ch / 2.0))
                cl_y1 = int(round((cam_y - my0) + ch / 2.0))
            clip_x0 = max(clip_x0, min(cl_x0, cl_x1))
            clip_x1 = min(clip_x1, max(cl_x0, cl_x1))
            clip_y0 = max(clip_y0, min(cl_y0, cl_y1))
            clip_y1 = min(clip_y1, max(cl_y0, cl_y1))

        dx = max(clip_x0, left)
        dy = max(clip_y0, top)
        sx0 = dx - left
        sy0 = dy - top
        cw_c = min(im.width - sx0, clip_x1 - dx)
        ch_c = min(im.height - sy0, clip_y1 - dy)
        if cw_c > 0 and ch_c > 0:
            sub = im.crop((sx0, sy0, sx0 + cw_c, sy0 + ch_c))
            canvas.alpha_composite(sub, (dx, dy))

    crop_x0, crop_y0, crop_x1, crop_y1 = compute_canvas_crop_rect(layout, counter_rot_deg)
    alpha_ch = canvas.getchannel("A")
    if (crop_x0, crop_y0, crop_x1, crop_y1) != (0, 0, cw, ch):
        sub_alpha = alpha_ch.crop((crop_x0, crop_y0, crop_x1, crop_y1))
        sub_bbox = sub_alpha.point(lambda v: 255 if v > 2 else 0).getbbox()
        bbox = (
            (crop_x0 + sub_bbox[0], crop_y0 + sub_bbox[1], crop_x0 + sub_bbox[2], crop_y0 + sub_bbox[3])
            if sub_bbox is not None
            else None
        )
    else:
        bbox = alpha_ch.point(lambda v: 255 if v > 2 else 0).getbbox()
    if bbox is None:
        canvas.close()
        return None

    bx0 = max(crop_x0, bbox[0])
    by0 = max(crop_y0, bbox[1])
    bx1 = min(crop_x1, bbox[2])
    by1 = min(crop_y1, bbox[3])
    tw_out, th_out = bx1 - bx0, by1 - by0
    if tw_out < 4 or th_out < 4:
        canvas.close()
        return None

    trimmed = canvas.crop((bx0, by0, bx1, by1))
    canvas.close()
    _arr = np.asarray(trimmed, dtype=np.float32).copy()
    _alpha = _arr[:, :, 3:4] / 255.0
    _arr[:, :, :3] = np.clip(np.round(_arr[:, :, :3] * _alpha), 0, 255)
    _arr[_arr[:, :, 3] == 0, :3] = 0
    trimmed_pma = Image.fromarray(_arr.astype(np.uint8), "RGBA")
    trimmed.close()

    p = layout["person"]
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
    trim_dx = ((bx0 + bx1) / 2.0) - cw / 2.0
    trim_dy = ch / 2.0 - ((by0 + by1) / 2.0)
    base_dx = cam_x - float(p["wx"])
    base_dy = cam_y - float(p["wy"])
    if abs(counter_rot_deg) > 0.25:
        base_dx, base_dy = cos_cr * base_dx - sin_cr * base_dy, sin_cr * base_dx + cos_cr * base_dy

    sx = (base_dx + trim_dx) / max(1e-5, p_ux)
    sy = (base_dy + trim_dy) / max(1e-5, p_uy)
    scale_x = 1.0 / max(1e-5, p_ux)
    scale_y = 1.0 / max(1e-5, p_uy)
    return {
        "im": trimmed_pma,
        "w": tw_out,
        "h": th_out,
        "x": round(sx, 4),
        "y": round(sy, 4),
        "scaleX": round(scale_x, 6),
        "scaleY": round(scale_y, 6),
        "crop_bbox": (bx0, by0, bx1, by1),
    }


# ---------------------------------------------------------------------------
# Coordinate Mapper (handles counter_rot_deg cleanly for native & GPU FX)
# ---------------------------------------------------------------------------

def make_exact_coord_mappers(layout: dict[str, Any], counter_rot_deg: float):
    p = layout["person"]
    p_wx, p_wy = float(p["wx"]), float(p["wy"])
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
    has_cr = abs(counter_rot_deg) > 0.25
    rad = math.radians(-counter_rot_deg)
    ca, sa = math.cos(rad), math.sin(rad)

    def coord_fn(wx: float, wy: float) -> tuple[float, float]:
        dx, dy = wx - p_wx, wy - p_wy
        if has_cr:
            dx, dy = ca * dx - sa * dy, sa * dx + ca * dy
        return dx / max(1e-5, p_ux), dy / max(1e-5, p_uy)

    def size_fn(pw: float, ph: float) -> tuple[float, float]:
        sw = math.copysign(max(1.0, abs(pw) / max(1e-5, p_ux)), -1.0 if pw < 0.0 else 1.0)
        sh = math.copysign(max(1.0, abs(ph) / max(1e-5, p_uy)), -1.0 if ph < 0.0 else 1.0)
        return sw, sh

    rot_off = -counter_rot_deg if has_cr else 0.0
    return coord_fn, size_fn, rot_off


def compute_bj_placement_in_main_spine(
    cand: dict[str, Any],
    layout: dict[str, Any],
    counter_rot_deg: float,
    preserve_scene_rot: bool,
) -> tuple[float, float, float, float, float]:
    """Return (tx_main, ty_main, rel_sx, rel_sy, rel_rot) for a bj_* skeleton inside Main-Person Spine space."""
    p = layout["person"]
    p_wx, p_wy = float(p["wx"]), float(p["wy"])
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
    p_deg = float(p.get("z_deg", 0.0))

    d_x = cand["wx"] - p_wx
    d_y = cand["wy"] - p_wy
    if abs(counter_rot_deg) > 0.25:
        rad = math.radians(-counter_rot_deg)
        ca, sa = math.cos(rad), math.sin(rad)
        d_x, d_y = ca * d_x - sa * d_y, sa * d_x + ca * d_y

    tx_main = d_x / max(1e-5, p_ux)
    ty_main = d_y / max(1e-5, p_uy)
    rel_sx = cand["ux"] / max(1e-5, p_ux)
    rel_sy = cand["uy"] / max(1e-5, p_uy)

    if preserve_scene_rot:
        rel_rot = cand["z_deg"]
    elif abs(counter_rot_deg) > 0.25:
        rel_rot = cand["z_deg"] - counter_rot_deg
    elif abs(p_deg) > 0.5 and abs(cand["z_deg"] - p_deg) < 1.0:
        rel_rot = 0.0
    else:
        rel_rot = cand["z_deg"]
    while rel_rot > 180.0:
        rel_rot -= 360.0
    while rel_rot < -180.0:
        rel_rot += 360.0
    if abs(rel_rot) < 0.25:
        rel_rot = 0.0
    if math.hypot(d_x, d_y) < 2.0:
        tx_main, ty_main = 0.0, 0.0
    return tx_main, ty_main, rel_sx, rel_sy, rel_rot


# ---------------------------------------------------------------------------
# Composite Spine 3.8 Submodel Builder (Interleaves Static + Native + GPU + Tween + BJ!)
# ---------------------------------------------------------------------------

def build_composite_submodel(
    out_dir: Path,
    model_name: str,
    model_id: str,
    base_scale: float,
    items: list[dict[str, Any]],  # ordered strictly back-to-front by Unity draw_key!
    layout: dict[str, Any],
    manifest_skin: dict[str, Any] | None,
    export_data: dict[str, Any] | None,
    repos: FastSceneRepos,
    tex_index: dict[str, Path],
    counter_rot_deg: float,
    preserve_scene_rot: bool,
    vp_bounds: tuple[float, float, float, float],
    frame_workers: int = 4,
) -> dict[str, Any] | None:
    """Build ONE Composite Spine 3.8 JSON submodel interleaving arbitrary static, native FX, GPU FX bands,
    Tweens, and merged BJ skeletons in exact Unity painter's order!"""
    if not items:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    coord_fn, size_fn, rot_off = make_exact_coord_mappers(layout, counter_rot_deg)

    # 1. Determine unified loop period T_loop across GPU bands, Native FX, and Tweens
    gpu_periods: list[float] = [
        float(it["duration"]) for it in items if it["kind"] == "gpu_band" and float(it.get("duration", 0)) > 0.5
    ]
    base_gpu_t = gpu_periods[0] if gpu_periods else None
    native_clips_used: list[tuple[dict[str, Any], set[int]]] = []
    tweens_used: list[dict[str, Any]] = []
    for it in items:
        if it["kind"] == "native_band":
            native_clips_used.append((it["export_clip"], set(it["node_indices"])))
        elif it["kind"] == "tween":
            tweens_used.append(it["tween"])

    if native_clips_used or tweens_used:
        # Compute period from first/largest native clip aligned to base_gpu_t (if present)
        if native_clips_used:
            # Merge all native node_indices on the same export clip for period estimation
            all_n_idxs: set[int] = set()
            ref_clip = native_clips_used[0][0]
            for ec, nset in native_clips_used:
                if ec is ref_clip:
                    all_n_idxs.update(nset)
            T_loop, T_sub, repeat_cnt = compute_native_idle_period(
                ref_clip,
                node_indices=all_n_idxs,
                tween_nodes=tweens_used or None,
                min_multiple_of=base_gpu_t,
                default_rec_dur=float((export_data or {}).get("record_dur") or 42.0),
            )
        else:
            T_loop = 16.0
            for grp in tweens_used:
                for tw in (grp.get("tweens") or []):
                    td = float(tw.get("duration", 0.0)) * (2.0 if int(tw.get("style", 1)) == 2 else 1.0)
                    T_loop = max(T_loop, td)
            if base_gpu_t:
                T_loop = round(max(1, int(round(T_loop / base_gpu_t))) * base_gpu_t, 4)
            T_sub, repeat_cnt = T_loop, 1
    elif base_gpu_t:
        T_loop = round(base_gpu_t, 4)
        T_sub, repeat_cnt = T_loop, 1
    else:
        # Static +/or BJ only: match longest BJ idle duration (or 0.0 if purely static)
        bj_durs = [float(it.get("bj_dur", 0.0)) for it in items if it["kind"] == "bj_merge"]
        T_loop = round(max(bj_durs), 4) if bj_durs and max(bj_durs) > 0.05 else 0.0
        T_sub, repeat_cnt = T_loop, 1

    # 2. Prepare atlas pages (multi-page .atlas.txt cleanly combining:
    #    (a) Static band images + Native particle / Tween sprites,
    #    (b) Tight-cropped GPU band frame sequences,
    #    (c) Verbatim lossless PMA .webp pages from merged BJ skeletons!)
    atlas_blocks: list[str] = []
    page_filenames: list[str] = []
    tex_names: list[str] = []
    page_idx_seq = 0

    def _next_page_name(tag: str) -> str:
        nonlocal page_idx_seq
        page_idx_seq += 1
        fn = f"{model_name}_{tag}_{page_idx_seq}.webp"
        page_filenames.append(fn)
        tex_names.append(Path(fn).stem)
        return fn

    # 2a. Static image bands: each rendered band gets its own dedicated lossless PMA .webp page
    #     (avoids padding bloat & preserves exact 1:1 resolution with zero repacking)
    static_reg_map: dict[int, tuple[str, dict[str, Any]]] = {}
    for idx, it in enumerate(items):
        if it["kind"] != "static_band":
            continue
        res = render_static_band_pma(it["imgs"], layout, counter_rot_deg)
        if res is None:
            continue
        rname = f"st_{idx:02d}"
        fn = _next_page_name(f"st{idx:02d}")
        save_exact_webp(res["im"], out_dir / fn)
        res["im"].close()
        tw_o, th_o = res["w"], res["h"]
        atlas_blocks.append(
            f"{fn}\n"
            f"size: {tw_o},{th_o}\n"
            f"format: RGBA8888\n"
            f"filter: Linear,Linear\n"
            f"repeat: none\n"
            f"{rname}\n"
            f"  rotate: false\n"
            f"  xy: 0, 0\n"
            f"  size: {tw_o}, {th_o}\n"
            f"  orig: {tw_o}, {th_o}\n"
            f"  offset: 0, 0\n"
            f"  index: -1"
        )
        static_reg_map[idx] = (rname, res)

    # 2b. Native particle sprites + Tween sprites packed onto ONE compact PMA sprite page
    pack_items: list[dict[str, Any]] = []
    tex_key_to_regs: dict[tuple[str, int, int, bool], list[str]] = {}
    reg_counter = 0

    for grp in tweens_used:
        for sp in (grp.get("sprites") or []):
            tname = (sp.get("tex") or "").strip()
            tp = tex_index.get(tname.lower()) or tex_index.get(Path(tname).stem.lower())
            if tp is None:
                continue
            tkey = (tp.stem.lower(), 1, 1, True)
            if tkey in tex_key_to_regs:
                continue
            im_pma = to_pma(Image.open(tp))
            rname = f"tw{reg_counter}_{sanitize_id(tp.stem)[:16]}"
            reg_counter += 1
            pack_items.append({
                "name": rname, "im": im_pma,
                "orig_w": im_pma.width, "orig_h": im_pma.height,
                "off_x": 0, "off_y": 0, "pad": 2,
            })
            tex_key_to_regs[tkey] = [rname]

    for ec, nset in native_clips_used:
        for n in ec.get("nodes") or []:
            if int(n["idx"]) not in nset:
                continue
            tname = (n.get("tex") or "").strip()
            tp = tex_index.get(tname.lower()) or tex_index.get(Path(tname).stem.lower())
            if tp is None:
                continue
            tx = max(1, int(n.get("tiles_x", 1)))
            ty = max(1, int(n.get("tiles_y", 1)))
            is_uv = bool(n.get("is_uv_scroll", False))
            tkey = (tp.stem.lower(), tx, ty, is_uv)
            if tkey in tex_key_to_regs:
                continue
            im_pma = to_pma(Image.open(tp))
            regs: list[str] = []
            if is_uv or (tx == 1 and ty == 1):
                rname = f"pt{reg_counter}_{sanitize_id(tp.stem)[:16]}"
                reg_counter += 1
                if is_uv:
                    pack_items.append({
                        "name": rname, "im": im_pma,
                        "orig_w": im_pma.width, "orig_h": im_pma.height,
                        "off_x": 0, "off_y": 0, "pad": 4,
                    })
                else:
                    cr, ow, oh, ox, oy = trim_sprite(im_pma, alpha_thr=1)
                    pack_items.append({
                        "name": rname, "im": cr,
                        "orig_w": ow, "orig_h": oh,
                        "off_x": ox, "off_y": oy, "pad": 2,
                    })
                regs.append(rname)
            else:
                cw_t = max(1, im_pma.width // tx)
                ch_t = max(1, im_pma.height // ty)
                for ti in range(tx * ty):
                    cx_t, cy_t = ti % tx, ti // tx
                    cell = im_pma.crop((cx_t * cw_t, cy_t * ch_t, (cx_t + 1) * cw_t, (cy_t + 1) * ch_t))
                    cr, ow, oh, ox, oy = trim_sprite(cell, alpha_thr=1)
                    rname = f"pt{reg_counter}_{sanitize_id(tp.stem)[:12]}_t{ti}"
                    reg_counter += 1
                    pack_items.append({
                        "name": rname, "im": cr,
                        "orig_w": ow, "orig_h": oh,
                        "off_x": ox, "off_y": oy, "pad": 2,
                    })
                    regs.append(rname)
            tex_key_to_regs[tkey] = regs

    if pack_items:
        sp_atlas_im, sp_regions = pack_shelf(pack_items, pad=2)
        fn = _next_page_name("pt")
        save_exact_webp(sp_atlas_im, out_dir / fn)
        lines = [
            fn,
            f"size: {sp_atlas_im.width},{sp_atlas_im.height}",
            "format: RGBA8888",
            "filter: Linear,Linear",
            "repeat: none",
        ]
        for r in sp_regions:
            lines.extend([
                r["name"],
                "  rotate: false",
                f"  xy: {r['x']}, {r['y']}",
                f"  size: {r['w']}, {r['h']}",
                f"  orig: {r['orig_w']}, {r['orig_h']}",
                f"  offset: {r['off_x']}, {r['off_y']}",
                "  index: -1",
            ])
        atlas_blocks.append("\n".join(lines))
        sp_atlas_im.close()

    # 2c. Tight-cropped GPU band frames (deduped across all GPU bands in this submodel!)
    gpu_band_indices = [idx for idx, it in enumerate(items) if it["kind"] == "gpu_band"]
    gpu_frame_lookup: dict[tuple[str, str, int], str | None] = {}
    gpu_region_orig: dict[str, tuple[int, int]] = {}
    gpu_canvas_wh: tuple[int, int] = (0, 0)
    if gpu_band_indices:
        frame_tasks = []
        for idx in gpu_band_indices:
            it = items[idx]
            gkey = f"gb{idx:02d}"
            for ch_name, paths in (("normal", it.get("normal_frames") or []), ("add", it.get("add_frames") or [])):
                for fi, fp in enumerate(paths):
                    frame_tasks.append((gkey, ch_name, fi, fp))
        if frame_tasks:
            if frame_workers > 1 and len(frame_tasks) > 8:
                with ThreadPoolExecutor(max_workers=min(frame_workers, len(frame_tasks))) as ex:
                    processed = list(ex.map(_process_frame_task, frame_tasks))
            else:
                processed = [_process_frame_task(t) for t in frame_tasks]

            hash_to_rname: dict[str, str] = {}
            unique_gpu_items = []
            g_cnt = 0
            for gkey, ch_name, fi, png_bytes, cw_i, ch_i, ow, oh, tl, tt, h in processed:
                if gpu_canvas_wh == (0, 0) and ow > 0:
                    gpu_canvas_wh = (ow, oh)
                if png_bytes is None:
                    gpu_frame_lookup[(gkey, ch_name, fi)] = None
                    continue
                dkey = f"{h}:{ow}x{oh}:{tl},{tt}"
                if dkey not in hash_to_rname:
                    g_cnt += 1
                    rname = f"gf_{g_cnt:04d}"
                    hash_to_rname[dkey] = rname
                    unique_gpu_items.append((rname, png_bytes, cw_i, ch_i, ow, oh, tl, tt))
                    gpu_region_orig[rname] = (ow, oh)
                gpu_frame_lookup[(gkey, ch_name, fi)] = hash_to_rname[dkey]
            processed.clear()

            if unique_gpu_items:
                pg_layouts, packed_regs = _pack_skyline(unique_gpu_items, max_size=4096, padding=2)
                unique_gpu_items.clear()
                pg_jobs = [(pg, _next_page_name("gf")) for pg in pg_layouts]

                def _encode_gpu_page(job: tuple[dict[str, Any], str]) -> tuple[str, int, int]:
                    pg, fn = job
                    pw, ph = pg["pw"], pg["ph"]
                    canvas = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
                    for _, png_bytes, _, _, px, py in pg["items"]:
                        with Image.open(io.BytesIO(png_bytes)) as sim:
                            canvas.paste(sim, (px, py))
                    save_exact_webp(canvas, out_dir / fn)
                    canvas.close()
                    pg["items"].clear()
                    return fn, pw, ph

                if frame_workers > 1 and len(pg_jobs) > 1:
                    with ThreadPoolExecutor(max_workers=min(frame_workers, len(pg_jobs))) as ex:
                        pg_metas = list(ex.map(_encode_gpu_page, pg_jobs))
                else:
                    pg_metas = [_encode_gpu_page(j) for j in pg_jobs]
                atlas_blocks.append(_build_atlas_text(pg_metas, packed_regs.values()).strip())

    # 3. Build unified Spine 3.8.79 skeleton!
    vp_x, vp_y, vp_w, vp_h = vp_bounds
    bones: list[dict[str, Any]] = [
        {"name": "root"},
        {"name": "fx_root", "parent": "root", "x": 0.0, "y": 0.0},
    ]

    # Add gpu_root bone if any GPU bands are present
    if gpu_band_indices and gpu_canvas_wh[0] > 0:
        p = layout["person"]
        p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
        p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
        mf_cw = float((manifest_skin or {}).get("canvas_w") or layout["canvas_w"])
        mf_ch = float((manifest_skin or {}).get("canvas_h") or layout["canvas_h"])
        mf_cx = float((manifest_skin or {}).get("cam_x") if manifest_skin is not None else layout["cam_x"])
        mf_cy = float((manifest_skin or {}).get("cam_y") if manifest_skin is not None else layout["cam_y"])
        dx_u = mf_cx - float(p["wx"])
        dy_u = mf_cy - float(p["wy"])
        if abs(counter_rot_deg) > 0.25:
            rad = math.radians(-counter_rot_deg)
            ca, sa = math.cos(rad), math.sin(rad)
            dx_u, dy_u = ca * dx_u - sa * dy_u, sa * dx_u + ca * dy_u
        gx = dx_u / max(1e-5, p_ux)
        gy = dy_u / max(1e-5, p_uy)
        gsx = (mf_cw / max(1e-5, p_ux)) / max(1.0, float(gpu_canvas_wh[0]))
        gsy = (mf_ch / max(1e-5, p_uy)) / max(1.0, float(gpu_canvas_wh[1]))
        gb: dict[str, Any] = {
            "name": "gpu_root",
            "parent": "root",
            "x": round(gx, 4),
            "y": round(gy, 4),
            "scaleX": round(gsx, 6),
            "scaleY": round(gsy, 6),
        }
        if abs(counter_rot_deg) > 0.25:
            gb["rotation"] = round(-counter_rot_deg, 4)
        bones.append(gb)

    slots: list[dict[str, Any]] = []
    skin_att: dict[str, Any] = {}
    ik_list: list[dict[str, Any]] = []
    tf_list: list[dict[str, Any]] = []
    path_list: list[dict[str, Any]] = []
    idle_anim: dict[str, Any] = {}
    bone_anims: dict[str, Any] = idle_anim.setdefault("bones", {})
    slot_anims: dict[str, Any] = idle_anim.setdefault("slots", {})
    constraint_order = 0

    clip_seq = 0

    def _open_fx_clip() -> str:
        nonlocal clip_seq
        clip_seq += 1
        cname = f"fx_clip_{clip_seq}"
        slots.append({"name": cname, "bone": "root", "attachment": cname})
        skin_att[cname] = {
            cname: {
                "type": "clipping",
                "end": "",
                "vertexCount": 4,
                "vertices": [
                    round(vp_x, 2), round(vp_y, 2),
                    round(vp_x + vp_w, 2), round(vp_y, 2),
                    round(vp_x + vp_w, 2), round(vp_y + vp_h, 2),
                    round(vp_x, 2), round(vp_y + vp_h, 2),
                ],
            }
        }
        return cname

    def _close_fx_clip(cname: str, start_slot_count: int) -> None:
        if len(slots) > start_slot_count:
            skin_att[cname][cname]["end"] = slots[-1]["name"]
        else:
            # No slots were emitted inside this clip; pop the unused clip slot!
            slots.pop()
            skin_att.pop(cname, None)

    # Walk all items strictly back-to-front!
    bj_merge_idx = 0
    for idx, it in enumerate(items):
        kind = it["kind"]
        if kind == "static_band":
            if idx not in static_reg_map:
                continue
            rname, res = static_reg_map[idx]
            bname = f"st_b{idx:02d}"
            sname = f"st_s{idx:02d}"
            bones.append({
                "name": bname,
                "parent": "root",
                "x": res["x"],
                "y": res["y"],
                "scaleX": res["scaleX"],
                "scaleY": res["scaleY"],
            })
            slots.append({"name": sname, "bone": bname, "attachment": rname})
            skin_att[sname] = {rname: {"x": 0.0, "y": 0.0, "width": res["w"], "height": res["h"]}}

        elif kind == "tween":
            _emit_tween_nodes_into_skeleton(
                [it["tween"]], tex_index, tex_key_to_regs,
                coord_fn, size_fn, rot_off,
                bones, slots, skin_att, bone_anims, slot_anims, max(1.0, T_loop),
                name_prefix=f"tw{idx}",
            )

        elif kind == "native_band":
            cname = _open_fx_clip()
            s_before = len(slots)
            emit_native_fx_nodes_into_skeleton(
                clip=it["export_clip"],
                node_indices=set(it["node_indices"]),
                anim_pref=f"nb{idx:02d}",
                parent_bone="fx_root",
                is_idle=True,
                T_loop=max(1.0, T_loop),
                T_sub=max(1.0, T_sub),
                repeat_cnt=repeat_cnt,
                tex_index=tex_index,
                tex_key_to_regs=tex_key_to_regs,
                coord_fn=coord_fn,
                size_fn=size_fn,
                rot_offset_deg=rot_off,
                viewport_rect=vp_bounds,
                bones=bones,
                slots=slots,
                skin_att=skin_att,
                bone_anims=bone_anims,
                slot_anims=slot_anims,
                total_bone_budget=480,
            )
            _close_fx_clip(cname, s_before)

        elif kind == "gpu_band":
            gkey = f"gb{idx:02d}"
            n_paths = it.get("normal_frames") or []
            a_paths = it.get("add_frames") or []
            fps = max(1.0, float(it.get("fps", 20.0)))
            dt = 1.0 / fps
            t_band = float(it.get("duration") or (max(len(n_paths), len(a_paths)) * dt))
            reps = max(1, int(round(max(t_band, T_loop) / max(0.1, t_band))))

            cname = _open_fx_clip()
            s_before = len(slots)
            for ch_name, paths, blend in (("normal", n_paths, "normal"), ("add", a_paths, "additive")):
                if not paths:
                    continue
                att_map: dict[str, dict[str, Any]] = {}
                for fi in range(len(paths)):
                    rn = gpu_frame_lookup.get((gkey, ch_name, fi))
                    if rn and rn not in att_map:
                        ow, oh = gpu_region_orig[rn]
                        att_map[rn] = {"x": 0.0, "y": 0.0, "width": ow, "height": oh}
                if not att_map:
                    continue
                sname = f"gb{idx:02d}_{ch_name}"
                s_def: dict[str, Any] = {"name": sname, "bone": "gpu_root", "attachment": None}
                if blend == "additive":
                    s_def["blend"] = "additive"
                slots.append(s_def)
                skin_att[sname] = att_map

                # Tile frame attachment timeline `reps` times cleanly across [0, T_loop] (0 extra atlas pixels!)
                keys: list[dict[str, Any]] = []
                last_val = "__INIT__"
                n_fr = len(paths)
                scale_dt = (T_loop / reps) / max(1e-5, n_fr * dt) if T_loop > 0.1 else 1.0
                for rep in range(reps):
                    base_t = rep * (T_loop / reps) if T_loop > 0.1 else 0.0
                    for fi in range(n_fr):
                        rn = gpu_frame_lookup.get((gkey, ch_name, fi))
                        if rn != last_val:
                            keys.append({"time": round(base_t + fi * dt * scale_dt, 4), "name": rn})
                            last_val = rn
                end_t = round(T_loop if T_loop > 0.1 else n_fr * dt, 4)
                keys.append({"time": end_t, "name": last_val})
                slot_anims[sname] = {"attachment": keys}
            _close_fx_clip(cname, s_before)

        elif kind == "bj_merge":
            cand = it["cand"]
            bj_prefix = f"bj{bj_merge_idx}_"
            bj_merge_idx += 1
            tmp_bj_dir = out_dir / f"_tmp_bj_{bj_merge_idx}"
            try:
                bj_env = repos.get_spine_env(cand["ab_name"])
                meta = _extract_spine_unit_from_ab(
                    bj_env,
                    cand["skel_cpath"],
                    tmp_bj_dir,
                    strip_bg=False,
                    save_webp=True,
                    clean_etc2=True,
                )
                skel_raw = (tmp_bj_dir / meta["skeleton"]).read_bytes()
                bj_json = spine38_binary_to_json(skel_raw)

                # Copy verbatim PMA .webp texture pages into out_dir & prefix .atlas.txt
                rename_map: dict[str, str] = {}
                for tex_fn in meta["textures"]:
                    new_fn = _next_page_name(f"bj{bj_merge_idx}")
                    shutil.copy2(tmp_bj_dir / tex_fn, out_dir / new_fn)
                    rename_map[tex_fn] = new_fn
                    rename_map[tex_fn.lower()] = new_fn
                orig_atlas = (tmp_bj_dir / meta["atlas"]).read_text(encoding="utf-8-sig")
                atlas_blocks.append(prefix_atlas_text(orig_atlas, bj_prefix, rename_map))

                tx_m, ty_m, rsx, rsy, rrot = compute_bj_placement_in_main_spine(
                    cand, layout, counter_rot_deg, preserve_scene_rot
                )
                constraint_order = merge_spine38_into_composite(
                    src_skel=bj_json,
                    prefix=bj_prefix,
                    anim_name=cand.get("anim", "idle"),
                    root_x=tx_m,
                    root_y=ty_m,
                    root_sx=rsx,
                    root_sy=rsy,
                    root_rot=rrot,
                    target_dur=max(T_loop, float(it.get("bj_dur", 1.0))),
                    dst_bones=bones,
                    dst_slots=slots,
                    dst_skin_att=skin_att,
                    dst_ik=ik_list,
                    dst_tf=tf_list,
                    dst_path=path_list,
                    dst_anim=idle_anim,
                    order_base=constraint_order,
                )
            finally:
                shutil.rmtree(tmp_bj_dir, ignore_errors=True)

    if not slots:
        shutil.rmtree(out_dir, ignore_errors=True)
        return None

    # Anchor root duration when animated
    if T_loop > 0.01:
        bone_anims["root"] = {
            "translate": [
                {"time": 0.0, "x": 0.0, "y": 0.0},
                {"time": round(T_loop, 4), "x": 0.0, "y": 0.0},
            ]
        }

    # Clean empty animation sub-dicts
    clean_idle = {k: v for k, v in idle_anim.items() if v}

    skel_json: dict[str, Any] = {
        "skeleton": {
            "hash": model_id,
            "spine": "3.8.79",
            "x": round(vp_x, 2),
            "y": round(vp_y, 2),
            "width": round(vp_w, 2),
            "height": round(vp_h, 2),
        },
        "bones": bones,
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin_att}],
        "animations": {"idle": clean_idle},
    }
    if ik_list:
        skel_json["ik"] = ik_list
    if tf_list:
        skel_json["transform"] = tf_list
    if path_list:
        skel_json["path"] = path_list

    atlas_file = f"{model_name}.atlas.txt"
    (out_dir / atlas_file).write_text("\n" + "\n\n".join(b for b in atlas_blocks if b.strip()) + "\n", encoding="utf-8")

    skel_file = f"{model_name}.json"
    (out_dir / skel_file).write_text(json.dumps(skel_json, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    cfg = {
        "conf_ver": 1,
        "type": 9,
        "controllers": {
            "param_hit": {},
            "param_loop": {},
            "key_trigger": {},
            "intimacy_system": {},
            "slot_opacity": {},
            "slot_color": {},
        },
        "hit_areas": [],
        "motions": {"idle": [{"name": "idle", "file": "idle", "fade_in": 0, "fade_out": 0, "file_loop": True}]},
        "options": {
            "id": model_id,
            "scale_factor": round(base_scale, 5),
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 1,
            "shader_type": 0,
            "edge_padding": False,
        },
        "skeleton": skel_file,
        "atlases": [{
            "atlas": atlas_file,
            "tex_names": tex_names,
            "textures": page_filenames,
        }],
    }
    (out_dir / ".config.json").write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {
        "id": model_id,
        "rel": f"submodels/{model_name}/.config.json",
        "bones": len(bones),
        "slots": len(slots),
        "pages": len(page_filenames),
        "T_loop": T_loop,
    }


# ---------------------------------------------------------------------------
# Dedicated Pure Touch-FX Submodel Builder (Supports Mixed Native & GPU clips!)
# ---------------------------------------------------------------------------

def build_pure_touch_submodel(
    out_dir: Path,
    model_name: str,
    model_id: str,
    base_scale: float,
    touch_specs: list[dict[str, Any]],  # [{clip, mode, export_clip, normal_frames, add_frames, fps}]
    layout: dict[str, Any],
    manifest_skin: dict[str, Any] | None,
    tex_index: dict[str, Path],
    counter_rot_deg: float,
    vp_bounds: tuple[float, float, float, float],
    frame_workers: int = 4,
) -> dict[str, Any] | None:
    """Build a dedicated pure Touch-FX submodel with `idle = {}` supporting both Native & GPU touch clips."""
    if not touch_specs:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    coord_fn, size_fn, rot_off = make_exact_coord_mappers(layout, counter_rot_deg)

    atlas_blocks: list[str] = []
    page_filenames: list[str] = []
    tex_names: list[str] = []
    page_seq = 0

    def _next_pg(tag: str) -> str:
        nonlocal page_seq
        page_seq += 1
        fn = f"{model_name}_{tag}_{page_seq}.webp"
        page_filenames.append(fn)
        tex_names.append(Path(fn).stem)
        return fn

    # 1. Pack native touch sprites
    native_specs = [ts for ts in touch_specs if ts["mode"] == "native" and ts.get("export_clip")]
    gpu_specs = [ts for ts in touch_specs if ts["mode"] == "gpu"]

    pack_items: list[dict[str, Any]] = []
    tex_key_to_regs: dict[tuple[str, int, int, bool], list[str]] = {}
    rcnt = 0
    for ts in native_specs:
        ec = ts["export_clip"]
        for n in ec.get("nodes") or []:
            tname = (n.get("tex") or "").strip()
            tp = tex_index.get(tname.lower()) or tex_index.get(Path(tname).stem.lower())
            if tp is None:
                continue
            tx = max(1, int(n.get("tiles_x", 1)))
            ty = max(1, int(n.get("tiles_y", 1)))
            is_uv = bool(n.get("is_uv_scroll", False))
            tkey = (tp.stem.lower(), tx, ty, is_uv)
            if tkey in tex_key_to_regs:
                continue
            im_pma = to_pma(Image.open(tp))
            regs = []
            if is_uv or (tx == 1 and ty == 1):
                rname = f"tp{rcnt}_{sanitize_id(tp.stem)[:14]}"
                rcnt += 1
                cr, ow, oh, ox, oy = (im_pma, im_pma.width, im_pma.height, 0, 0) if is_uv else trim_sprite(im_pma, 1)
                pack_items.append({"name": rname, "im": cr, "orig_w": ow, "orig_h": oh, "off_x": ox, "off_y": oy, "pad": 2})
                regs.append(rname)
            else:
                cw_t, ch_t = max(1, im_pma.width // tx), max(1, im_pma.height // ty)
                for ti in range(tx * ty):
                    cx_t, cy_t = ti % tx, ti // tx
                    cell = im_pma.crop((cx_t * cw_t, cy_t * ch_t, (cx_t + 1) * cw_t, (cy_t + 1) * ch_t))
                    cr, ow, oh, ox, oy = trim_sprite(cell, 1)
                    rname = f"tp{rcnt}_{sanitize_id(tp.stem)[:10]}_t{ti}"
                    rcnt += 1
                    pack_items.append({"name": rname, "im": cr, "orig_w": ow, "orig_h": oh, "off_x": ox, "off_y": oy, "pad": 2})
                    regs.append(rname)
            tex_key_to_regs[tkey] = regs

    if pack_items:
        sp_im, sp_regs = pack_shelf(pack_items, pad=2)
        fn = _next_pg("pt")
        save_exact_webp(sp_im, out_dir / fn)
        lines = [fn, f"size: {sp_im.width},{sp_im.height}", "format: RGBA8888", "filter: Linear,Linear", "repeat: none"]
        for r in sp_regs:
            lines.extend([r["name"], "  rotate: false", f"  xy: {r['x']}, {r['y']}", f"  size: {r['w']}, {r['h']}",
                          f"  orig: {r['orig_w']}, {r['orig_h']}", f"  offset: {r['off_x']}, {r['off_y']}", "  index: -1"])
        atlas_blocks.append("\n".join(lines))
        sp_im.close()

    # 2. Pack GPU touch frames
    gpu_lookup: dict[tuple[str, str, int], str | None] = {}
    gpu_orig: dict[str, tuple[int, int]] = {}
    gpu_cwh = (0, 0)
    if gpu_specs:
        ftasks = [
            (ts["clip"], ch, fi, fp)
            for ts in gpu_specs
            for ch, paths in (("normal", ts.get("normal_frames") or []), ("add", ts.get("add_frames") or []))
            for fi, fp in enumerate(paths)
        ]
        if ftasks:
            if frame_workers > 1 and len(ftasks) > 8:
                with ThreadPoolExecutor(max_workers=min(frame_workers, len(ftasks))) as ex:
                    proc = list(ex.map(_process_frame_task, ftasks))
            else:
                proc = [_process_frame_task(t) for t in ftasks]
            h2r: dict[str, str] = {}
            uniq = []
            gc_i = 0
            for cname, ch, fi, pb, cwi, chi, ow, oh, tl, tt, h in proc:
                if gpu_cwh == (0, 0) and ow > 0:
                    gpu_cwh = (ow, oh)
                if pb is None:
                    gpu_lookup[(cname, ch, fi)] = None
                    continue
                dk = f"{h}:{ow}x{oh}:{tl},{tt}"
                if dk not in h2r:
                    gc_i += 1
                    rn = f"tf_{gc_i:04d}"
                    h2r[dk] = rn
                    uniq.append((rn, pb, cwi, chi, ow, oh, tl, tt))
                    gpu_orig[rn] = (ow, oh)
                gpu_lookup[(cname, ch, fi)] = h2r[dk]
            proc.clear()
            if uniq:
                pgs, pregs = _pack_skyline(uniq, max_size=4096, padding=2)
                uniq.clear()
                pg_jobs = [(pg, _next_pg("gf")) for pg in pgs]

                def _enc_tpage(job: tuple[dict[str, Any], str]) -> tuple[str, int, int]:
                    pg, fn = job
                    cv = Image.new("RGBA", (pg["pw"], pg["ph"]), (0, 0, 0, 0))
                    for _, pb, _, _, px, py in pg["items"]:
                        with Image.open(io.BytesIO(pb)) as sim:
                            cv.paste(sim, (px, py))
                    save_exact_webp(cv, out_dir / fn)
                    cv.close()
                    pg["items"].clear()
                    return fn, pg["pw"], pg["ph"]

                if frame_workers > 1 and len(pg_jobs) > 1:
                    with ThreadPoolExecutor(max_workers=min(frame_workers, len(pg_jobs))) as ex:
                        pmetas = list(ex.map(_enc_tpage, pg_jobs))
                else:
                    pmetas = [_enc_tpage(j) for j in pg_jobs]
                atlas_blocks.append(_build_atlas_text(pmetas, pregs.values()).strip())

    # 3. Build Spine 3.8 skeleton
    vp_x, vp_y, vp_w, vp_h = vp_bounds
    bones: list[dict[str, Any]] = [{"name": "root"}, {"name": "fx_root", "parent": "root", "x": 0.0, "y": 0.0}]
    if gpu_specs and gpu_cwh[0] > 0:
        p = layout["person"]
        p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
        p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
        mf_cw = float((manifest_skin or {}).get("canvas_w") or layout["canvas_w"])
        mf_ch = float((manifest_skin or {}).get("canvas_h") or layout["canvas_h"])
        mf_cx = float((manifest_skin or {}).get("cam_x") if manifest_skin is not None else layout["cam_x"])
        mf_cy = float((manifest_skin or {}).get("cam_y") if manifest_skin is not None else layout["cam_y"])
        dx_u, dy_u = mf_cx - float(p["wx"]), mf_cy - float(p["wy"])
        if abs(counter_rot_deg) > 0.25:
            rad = math.radians(-counter_rot_deg)
            ca, sa = math.cos(rad), math.sin(rad)
            dx_u, dy_u = ca * dx_u - sa * dy_u, sa * dx_u + ca * dy_u
        gb: dict[str, Any] = {
            "name": "gpu_root",
            "parent": "root",
            "x": round(dx_u / max(1e-5, p_ux), 4),
            "y": round(dy_u / max(1e-5, p_uy), 4),
            "scaleX": round((mf_cw / max(1e-5, p_ux)) / max(1.0, float(gpu_cwh[0])), 6),
            "scaleY": round((mf_ch / max(1e-5, p_uy)) / max(1.0, float(gpu_cwh[1])), 6),
        }
        if abs(counter_rot_deg) > 0.25:
            gb["rotation"] = round(-counter_rot_deg, 4)
        bones.append(gb)

    slots: list[dict[str, Any]] = [{"name": "fx_clip", "bone": "root", "attachment": "fx_clip"}]
    skin_att: dict[str, Any] = {
        "fx_clip": {
            "fx_clip": {
                "type": "clipping",
                "end": "",
                "vertexCount": 4,
                "vertices": [
                    round(vp_x, 2), round(vp_y, 2),
                    round(vp_x + vp_w, 2), round(vp_y, 2),
                    round(vp_x + vp_w, 2), round(vp_y + vp_h, 2),
                    round(vp_x, 2), round(vp_y + vp_h, 2),
                ],
            }
        }
    }

    # Add shared GPU overlay slots if needed
    has_gpu_norm = any(ts.get("normal_frames") for ts in gpu_specs)
    has_gpu_add = any(ts.get("add_frames") for ts in gpu_specs)
    if has_gpu_norm:
        att_n = {}
        for ts in gpu_specs:
            for fi in range(len(ts.get("normal_frames") or [])):
                rn = gpu_lookup.get((ts["clip"], "normal", fi))
                if rn and rn not in att_n:
                    ow, oh = gpu_orig[rn]
                    att_n[rn] = {"x": 0.0, "y": 0.0, "width": ow, "height": oh}
        if att_n:
            slots.append({"name": "ov_normal", "bone": "gpu_root", "attachment": None})
            skin_att["ov_normal"] = att_n
        else:
            has_gpu_norm = False
    if has_gpu_add:
        att_a = {}
        for ts in gpu_specs:
            for fi in range(len(ts.get("add_frames") or [])):
                rn = gpu_lookup.get((ts["clip"], "add", fi))
                if rn and rn not in att_a:
                    ow, oh = gpu_orig[rn]
                    att_a[rn] = {"x": 0.0, "y": 0.0, "width": ow, "height": oh}
        if att_a:
            slots.append({"name": "ov_add", "bone": "gpu_root", "attachment": None, "blend": "additive"})
            skin_att["ov_add"] = att_a
        else:
            has_gpu_add = False

    animations: dict[str, Any] = {"idle": {}}
    motions: dict[str, list[dict[str, Any]]] = {
        "idle": [{"name": "idle", "file": "idle", "fade_in": 0, "fade_out": 0, "file_loop": True}],
        "main": [],
    }

    for ts in touch_specs:
        cname = ts["clip"]
        if ts["mode"] == "native" and ts.get("export_clip"):
            ba: dict[str, Any] = {}
            sa: dict[str, Any] = {}
            dur = emit_native_fx_nodes_into_skeleton(
                clip=ts["export_clip"],
                node_indices=None,
                anim_pref=sanitize_id(cname)[:14],
                parent_bone="fx_root",
                is_idle=False,
                T_loop=0.2,
                T_sub=0.0,
                repeat_cnt=1,
                tex_index=tex_index,
                tex_key_to_regs=tex_key_to_regs,
                coord_fn=coord_fn,
                size_fn=size_fn,
                rot_offset_deg=rot_off,
                viewport_rect=vp_bounds,
                bones=bones,
                slots=slots,
                skin_att=skin_att,
                bone_anims=ba,
                slot_anims=sa,
                total_bone_budget=320,
            )
            ba["root"] = {"translate": [{"time": 0.0, "x": 0.0, "y": 0.0}, {"time": round(dur, 4), "x": 0.0, "y": 0.0}]}
            animations[cname] = {"bones": ba, "slots": sa}
        else:
            fps = max(1.0, float(ts.get("fps", 20.0)))
            dt = 1.0 / fps
            nf = ts.get("normal_frames") or []
            af = ts.get("add_frames") or []
            max_fr = max(len(nf), len(af), 1)
            last_ne = 0
            for fi in range(max_fr):
                if (fi < len(nf) and gpu_lookup.get((cname, "normal", fi))) or (fi < len(af) and gpu_lookup.get((cname, "add", fi))):
                    last_ne = fi
            use_fr = min(max_fr, last_ne + 2)
            sa = {}
            for sname, ch, paths, exists in (("ov_normal", "normal", nf, has_gpu_norm), ("ov_add", "add", af, has_gpu_add)):
                if not exists:
                    continue
                if not paths:
                    sa[sname] = {"attachment": [{"time": 0.0, "name": None}]}
                    continue
                kfs = []
                lv = "__INIT__"
                for fi in range(min(len(paths), use_fr)):
                    rn = gpu_lookup.get((cname, ch, fi))
                    if rn != lv:
                        kfs.append({"time": round(fi * dt, 4), "name": rn})
                        lv = rn
                kfs.append({"time": round(use_fr * dt, 4), "name": None})
                sa[sname] = {"attachment": kfs}
            animations[cname] = {"slots": sa}

        motions["main"].append({"name": cname, "file": cname, "fade_in": 0, "fade_out": 0})

    if len(slots) <= 1 or not atlas_blocks:
        shutil.rmtree(out_dir, ignore_errors=True)
        return None
    skin_att["fx_clip"]["fx_clip"]["end"] = slots[-1]["name"]

    skel_json = {
        "skeleton": {
            "hash": model_id,
            "spine": "3.8.79",
            "x": round(vp_x, 2),
            "y": round(vp_y, 2),
            "width": round(vp_w, 2),
            "height": round(vp_h, 2),
        },
        "bones": bones,
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin_att}],
        "animations": animations,
    }
    atlas_file = f"{model_name}.atlas.txt"
    skel_file = f"{model_name}.json"
    (out_dir / atlas_file).write_text("\n" + "\n\n".join(b for b in atlas_blocks if b.strip()) + "\n", encoding="utf-8")
    (out_dir / skel_file).write_text(json.dumps(skel_json, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    cfg = {
        "conf_ver": 1,
        "type": 9,
        "controllers": {"param_hit": {}, "param_loop": {}, "key_trigger": {}, "intimacy_system": {}, "slot_opacity": {}, "slot_color": {}},
        "hit_areas": [],
        "motions": motions,
        "options": {
            "id": model_id,
            "scale_factor": round(base_scale, 5),
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 1,
            "shader_type": 0,
            "edge_padding": False,
        },
        "skeleton": skel_file,
        "atlases": [{"atlas": atlas_file, "tex_names": tex_names, "textures": page_filenames}],
    }
    (out_dir / ".config.json").write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {
        "id": model_id,
        "rel": f"submodels/{model_name}/.config.json",
        "clips": [ts["clip"] for ts in touch_specs],
    }


# ---------------------------------------------------------------------------
# Binary BJ Helper (untouched native binary submodel when runs <= avail_slots)
# ---------------------------------------------------------------------------

def build_standalone_binary_bj(
    cand: dict[str, Any],
    sub_name: str,
    skin_key: str,
    base_scale: float,
    sub_root: Path,
    repos: FastSceneRepos,
    layout: dict[str, Any],
    counter_rot_deg: float,
    preserve_scene_rot: bool,
) -> tuple[str, str]:
    tx_main, ty_main, rel_sx, rel_sy, rel_rot = compute_bj_placement_in_main_spine(
        cand, layout, counter_rot_deg, preserve_scene_rot
    )
    if 0.15 <= abs(rel_sx) <= 3.5:
        s_ratio = abs(rel_sx)
    else:
        s_ratio = max(0.15, min(3.5, (abs(rel_sx) + abs(rel_sy)) / 2.0))
    mul_sx = rel_sx / s_ratio
    mul_sy = rel_sy / s_ratio
    dx_sp = tx_main / s_ratio
    dy_sp = ty_main / s_ratio

    sdir = sub_root / sub_name
    bj_env = repos.get_spine_env(cand["ab_name"])
    meta = _extract_spine_unit_from_ab(
        bj_env,
        cand["skel_cpath"],
        sdir,
        strip_bg=False,
        root_shift=(dx_sp, dy_sp),
        root_scale=(mul_sx, mul_sy),
        root_rot=rel_rot,
        save_webp=True,
        clean_etc2=True,
    )
    anims = meta["parsed"]["anims"]
    chosen_anim = (
        cand["anim"]
        if cand["anim"] in anims
        else ("idle" if "idle" in anims else ("animation" if "animation" in anims else anims[0]))
    )
    sub_id = f"{skin_key.lower()}_{sub_name}"
    sub_cfg = {
        "conf_ver": 1,
        "type": 9,
        "controllers": {"param_hit": {}, "param_loop": {}, "intimacy_system": {}, "slot_opacity": {}, "slot_color": {}},
        "hit_areas": [],
        "motions": {"idle": [{"name": chosen_anim, "file": chosen_anim, "file_loop": True}]},
        "options": {
            "id": sub_id,
            "scale_factor": round(base_scale * s_ratio, 5),
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 1,
            "shader_type": 0,
            "edge_padding": False,
        },
        "skeleton": meta["skeleton"],
        "atlases": [{"atlas": meta["atlas"], "tex_names": meta["tex_names"], "textures": meta["textures"]}],
    }
    (sdir / ".config.json").write_text(json.dumps(sub_cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return sub_id, f"submodels/{sub_name}/.config.json"


# ---------------------------------------------------------------------------
# Side Planner: Exact Unity Interleaving + Smart 3-Slot Allocation
# ---------------------------------------------------------------------------

def _load_gpu_clip_frames(skin_key: str, gpu_clip_name: str) -> tuple[list[Path], list[Path]]:
    cdir = GPU_FRAMES_ROOT / skin_key / gpu_clip_name
    if not cdir.is_dir():
        return [], []
    nf = sorted((cdir / "normal").glob("frame_*.png")) if (cdir / "normal").is_dir() else []
    af = sorted((cdir / "add").glob("frame_*.png")) if (cdir / "add").is_dir() else []
    return nf, af


def _resolve_node_draw_key(
    node: dict[str, Any],
    ps_by_path: dict[str, tuple[int, float, int]],
    fallback_seq: int,
) -> tuple[int, float, int]:
    p = (node.get("path") or "").strip()
    if p in ps_by_path:
        return ps_by_path[p]
    if p.startswith("/") and p[1:] in ps_by_path:
        return ps_by_path[p[1:]]
    eff_o = int(node.get("effSortOrder", node.get("eff_sort_order", 0)))
    wz = 0.0
    wp = node.get("world_pos")
    if wp and len(wp) >= 3:
        wz = float(wp[2])
    dfs = int(node.get("dfsSeq", node.get("dfs_seq", fallback_seq)))
    return (eff_o, -round(wz, 3), 50000 + dfs)


def _assemble_side(
    side: str,  # "back" | "front"
    imgs: list[dict[str, Any]],
    bjs: list[dict[str, Any]],
    tweens: list[dict[str, Any]],
    idle_plan_clips: list[tuple[str, dict[str, Any], dict[str, Any] | None]],  # (clip_name, plan_entry, export_clip)
    touch_specs: list[dict[str, Any]],
    manifest_clips_by_name: dict[str, dict[str, Any]],
    ps_by_path: dict[str, tuple[int, float, int]],
    skin_key: str,
    base_scale: float,
    sub_root: Path,
    repos: FastSceneRepos,
    layout: dict[str, Any],
    manifest_skin: dict[str, Any] | None,
    export_data: dict[str, Any] | None,
    tex_index: dict[str, Path],
    counter_rot_deg: float,
    preserve_scene_rot: bool,
    vp_bounds: tuple[float, float, float, float],
    used_bj_names: set[str],
    frame_workers: int,
) -> tuple[list[tuple[str, str, int]], dict[str, str]]:
    """Build all submodels for one side (`back` in [-3,-2,-1] or `front` in [1,2,3]).
    Returns `(assigned_subs, touch_clip_to_submodel_id)`.
    """
    # 1. Collect all scene elements on this side with exact Unity draw_key
    raw_elements: list[dict[str, Any]] = []
    for im in imgs:
        raw_elements.append({"kind": "img", "draw_key": im["draw_key"], "img": im})
    for b in bjs:
        # Compute BJ idle duration up front in case we merge it
        env = repos.get_spine_env(b["ab_name"])
        ptr = {k.lower(): v for k, v in (env.container or {}).items()}[b["skel_cpath"].lower()]
        raw_b = ptr.read().m_Script.encode("utf-8", "surrogateescape")
        bj_js_dur = 0.0
        try:
            from spine38_binary_to_json import animation_duration
            # Fast peek only needed if we merge, store raw bytes length hint
            b["_raw_bytes_len"] = len(raw_b)
            # Only decode duration if > 2 bjs or > 3 runs
        except Exception:
            pass
        raw_elements.append({"kind": "bj", "draw_key": b["draw_key"], "cand": b})

    for tw in tweens:
        tw_p = (tw.get("path") or "").strip()
        if tw_p in ps_by_path:
            dk_tw = ps_by_path[tw_p]
        elif ("/" + tw_p) in ps_by_path:
            dk_tw = ps_by_path["/" + tw_p]
        else:
            dk_tw = (int(tw.get("sort_order", 1)), 0.0, int(tw.get("dfs_seq", 500)))
        raw_elements.append({"kind": "tween", "draw_key": dk_tw, "tween": tw})

    for cname, p_ent, exp_clip in idle_plan_clips:
        mf_clip = manifest_clips_by_name.get(cname) or {}
        mf_nodes = mf_clip.get("nodes") or []
        # Native nodes (one element per native node, later coalesced into contiguous native_band!)
        if exp_clip is not None:
            for ni in (p_ent.get("native_node_indices") or []):
                nd = mf_nodes[ni] if 0 <= ni < len(mf_nodes) else {}
                dk = _resolve_node_draw_key(nd, ps_by_path, ni)
                raw_elements.append({
                    "kind": "native_node",
                    "draw_key": dk,
                    "export_clip": exp_clip,
                    "node_idx": int(ni),
                })
        # GPU bands
        for gb in (p_ent.get("gpu_bands") or []):
            nf, af = _load_gpu_clip_frames(skin_key, gb["gpu_clip"])
            if not nf and not af:
                continue
            nidxs = gb.get("node_indices") or []
            dks = [_resolve_node_draw_key(mf_nodes[i], ps_by_path, i) for i in nidxs if 0 <= i < len(mf_nodes)]
            dk = min(dks) if dks else (int(gb.get("eff_sort_order", 0)), 0.0, 50000 + int(gb.get("min_dfs", 0)))
            raw_elements.append({
                "kind": "gpu_band",
                "draw_key": dk,
                "gpu_clip": gb["gpu_clip"],
                "normal_frames": nf,
                "add_frames": af,
                "duration": float(gb.get("duration", 6.0)),
                "fps": float(gb.get("fps", 20.0)),
            })

    raw_elements.sort(key=lambda e: e["draw_key"])

    # Coalesce adjacent `img` -> `static_band` and adjacent same-clip `native_node` -> `native_band`
    def _coalesce(elems: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in elems:
            if e["kind"] == "img":
                if out and out[-1]["kind"] == "static_band":
                    out[-1]["imgs"].append(e["img"])
                else:
                    out.append({"kind": "static_band", "draw_key": e["draw_key"], "imgs": [e["img"]]})
            elif e["kind"] == "native_node":
                if out and out[-1]["kind"] == "native_band" and out[-1]["export_clip"] is e["export_clip"]:
                    out[-1]["node_indices"].append(e["node_idx"])
                else:
                    out.append({
                        "kind": "native_band",
                        "draw_key": e["draw_key"],
                        "export_clip": e["export_clip"],
                        "node_indices": [e["node_idx"]],
                    })
            else:
                out.append(e)
        return out

    coalesced = _coalesce(raw_elements)

    # Partition into alternating [non-BJ composite run] and [BJ] runs
    runs: list[dict[str, Any]] = []
    for e in coalesced:
        if e["kind"] == "bj":
            runs.append({"type": "bj", "cand": e["cand"], "draw_key": e["draw_key"]})
        else:
            if runs and runs[-1]["type"] == "comp":
                runs[-1]["items"].append(e)
            else:
                runs.append({"type": "comp", "items": [e], "draw_key": e["draw_key"]})

    # Build dedicated touch submodel if any touch FX exist on this side
    touch_sub: dict[str, Any] | None = None
    touch_owner_map: dict[str, str] = {}
    if touch_specs:
        t_name = f"fx_{skin_key.lower()}_touch_back" if side == "back" else f"fx_{skin_key.lower()}_touch"
        touch_sub = build_pure_touch_submodel(
            out_dir=sub_root / t_name,
            model_name=t_name,
            model_id=t_name,
            base_scale=base_scale,
            touch_specs=touch_specs,
            layout=layout,
            manifest_skin=manifest_skin,
            tex_index=tex_index,
            counter_rot_deg=counter_rot_deg,
            vp_bounds=vp_bounds,
            frame_workers=frame_workers,
        )
        if touch_sub:
            for cn in touch_sub["clips"]:
                touch_owner_map[cn] = touch_sub["id"]

    max_scene_slots = 2 if touch_sub is not None else 3
    built_subs: list[tuple[str, str]] = []  # ordered strictly back-to-front!

    if len(runs) <= max_scene_slots:
        # All runs fit natively! Keep EVERY bj_* as untouched native binary!
        comp_i = 0
        bj_i = 0
        for run in runs:
            if run["type"] == "bj":
                bj_i += 1
                cand = run["cand"]
                stem = Path(cand["skel_cpath"]).name[:-len(".skel.bytes")].lower()
                m_num = re.search(r"(bj_\d+|bg_?\d+|tree\d*|robort_\d+|butterfly|grass|curtain|flower|carpet|umbrella)", stem)
                base_nm = m_num.group(1) if m_num else f"bj_{side}_{bj_i:02d}"
                snm = base_nm
                suf = 2
                while snm in used_bj_names:
                    snm = f"{base_nm}_{suf}"
                    suf += 1
                used_bj_names.add(snm)
                sid, srel = build_standalone_binary_bj(
                    cand, snm, skin_key, base_scale, sub_root, repos, layout, counter_rot_deg, preserve_scene_rot
                )
                built_subs.append((sid, srel))
            else:
                comp_i += 1
                cname_dir = f"scene_{side}" if comp_i == 1 and sum(1 for r in runs if r["type"] == "comp") == 1 else f"scene_{side}_{comp_i}"
                cid = f"{skin_key.lower()}_{cname_dir}"
                res = build_composite_submodel(
                    out_dir=sub_root / cname_dir,
                    model_name=cname_dir,
                    model_id=cid,
                    base_scale=base_scale,
                    items=run["items"],
                    layout=layout,
                    manifest_skin=manifest_skin,
                    export_data=export_data,
                    repos=repos,
                    tex_index=tex_index,
                    counter_rot_deg=counter_rot_deg,
                    preserve_scene_rot=preserve_scene_rot,
                    vp_bounds=vp_bounds,
                    frame_workers=frame_workers,
                )
                if res:
                    built_subs.append((res["id"], res["rel"]))
    else:
        # > max_scene_slots runs (e.g. Aoling_S2, Asuna_S7, Gawana_S3, Clarice_S3, RubyRose_S2):
        # Merge ALL items on this side (including ALL bj_* via lossless spine38_binary_to_json!)
        # into ONE single Composite Spine 3.8 JSON submodel in exact Unity draw_key order!
        from spine38_binary_to_json import animation_duration

        merged_items: list[dict[str, Any]] = []
        for e in coalesced:
            if e["kind"] == "bj":
                cand = e["cand"]
                env = repos.get_spine_env(cand["ab_name"])
                ptr = {k.lower(): v for k, v in (env.container or {}).items()}[cand["skel_cpath"].lower()]
                raw_b = ptr.read().m_Script.encode("utf-8", "surrogateescape")
                bj_js = spine38_binary_to_json(raw_b)
                anims = bj_js.get("animations") or {}
                anm = anims.get(cand.get("anim", "idle")) or anims.get("idle") or anims.get("animation") or (next(iter(anims.values())) if anims else {})
                bdur = animation_duration(anm) if anm else 0.0
                merged_items.append({"kind": "bj_merge", "cand": cand, "bj_dur": bdur, "draw_key": e["draw_key"]})
            else:
                merged_items.append(e)

        cname_dir = f"scene_{side}"
        cid = f"{skin_key.lower()}_{cname_dir}"
        res = build_composite_submodel(
            out_dir=sub_root / cname_dir,
            model_name=cname_dir,
            model_id=cid,
            base_scale=base_scale,
            items=merged_items,
            layout=layout,
            manifest_skin=manifest_skin,
            export_data=export_data,
            repos=repos,
            tex_index=tex_index,
            counter_rot_deg=counter_rot_deg,
            preserve_scene_rot=preserve_scene_rot,
            vp_bounds=vp_bounds,
            frame_workers=frame_workers,
        )
        if res:
            built_subs.append((res["id"], res["rel"]))

    if touch_sub:
        built_subs.append((touch_sub["id"], touch_sub["rel"]))

    # Assign strict Live2DViewerEX orders: [-3, -2, -1] behind Person, [1, 2, 3] in front of Person
    if side == "back":
        slots_ord = [-3, -2, -1][-len(built_subs):] if built_subs else []
    else:
        slots_ord = [1, 2, 3][:len(built_subs)]

    assigned = [(sid, srel, o) for (sid, srel), o in zip(built_subs, slots_ord)]
    return assigned, touch_owner_map


# ---------------------------------------------------------------------------
# Main Config Updater (Syncs start, reload_bg, AND start_mtn across zh/en/ja!)
# ---------------------------------------------------------------------------

def patch_all_language_configs(
    skin_dir: Path,
    new_add_cmd: str,
    touch_owner_map: dict[str, str],
) -> int:
    patched = 0
    for cfg_name in (".config.json", "config_en.config.json", "config_ja.config.json"):
        cfg_p = skin_dir / cfg_name
        if not cfg_p.is_file():
            continue
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
        motions = cfg.get("motions") or {}
        changed = False

        # 1. Update add_submodel/remove_submodel in start[*] and reload_bg[*]
        cur_sub_rels = [
            seg.strip().split()[1]
            for seg in new_add_cmd.split(";")
            if len(seg.strip().split()) == 3 and seg.strip().split()[0] == "add_submodel"
        ]
        for group_name in ("start", "reload_bg"):
            for ent in motions.get(group_name) or []:
                if not isinstance(ent, dict):
                    continue
                old_c = ent.get("command", "")
                if "add_submodel" in old_c or "remove_submodel" in old_c or group_name in ("start", "reload_bg"):
                    other_parts = [
                        part.strip()
                        for part in old_c.split(";")
                        if part.strip()
                        and not part.strip().startswith("add_submodel")
                        and not part.strip().startswith("remove_submodel")
                    ]
                    if group_name == "reload_bg":
                        rm_parts = [f"remove_submodel {r}" for r in cur_sub_rels]
                        parts = rm_parts + ([new_add_cmd] if new_add_cmd else []) + other_parts
                    else:
                        parts = ([new_add_cmd] if new_add_cmd else []) + other_parts
                    final_c = "; ".join(parts)
                    if final_c != old_c:
                        ent["command"] = final_c
                        changed = True

        # 2. Remap start_mtn <old_fx_id> <fx_9008xxx> -> start_mtn <actual_owner_id> <fx_9008xxx>
        if touch_owner_map:
            for grp, entries in motions.items():
                if grp in ("背景开关", "背景菜单"):
                    continue
                for ent in entries or []:
                    if not isinstance(ent, dict):
                        continue
                    old_c = ent.get("command", "")
                    if "start_mtn" not in old_c:
                        continue
                    new_parts = []
                    for seg in old_c.split(";"):
                        s = seg.strip()
                        if not s:
                            continue
                        toks = s.split()
                        if len(toks) >= 3 and toks[0] == "start_mtn":
                            anim_key = toks[2].split(":", 1)[-1]
                            if anim_key in touch_owner_map:
                                toks[1] = touch_owner_map[anim_key]
                                s = " ".join(toks)
                        new_parts.append(s)
                    final_c = "; ".join(new_parts)
                    if final_c != old_c:
                        ent["command"] = final_c
                        changed = True

        if changed:
            cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            patched += 1
    return patched


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Unified Spine Scene & Hybrid FX Assembler v2")
    ap.add_argument("--skins", type=str, default="", help="Comma-separated skin_key filter (e.g. 1001_HagakureRuri_S2,3301_Aoling_S2)")
    ap.add_argument("--all", action="store_true", help="Rebuild all 109 dressed Spine skins")
    ap.add_argument("--frame-workers", type=int, default=4, help="Parallel threads for GPU frame cropping")
    ap.add_argument("--skip-bg-toggle", action="store_true", help="Skip running add_spine_bg_toggle.py at the end")
    ap.add_argument("--skip-v2-done", action="store_true", help="Skip skins that already have scene_back or scene_front built")
    args = ap.parse_args()

    if not args.all and not args.skins:
        ap.error("Specify --skins <keys> or --all")

    want_skins = {x.strip().lower() for x in args.skins.split(",") if x.strip()} if args.skins else set()

    mf = json.loads(FX_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    mf_by_key = {s["skin_key"]: s for s in (mf.get("skins") or [])}
    gpu_plan_all = json.loads(GPU_PLAN_PATH.read_text(encoding="utf-8-sig"))["skins"]

    repo = FullI18nRepo()
    catalog = build_skin_catalog(repo)
    indexer = AssetIndexer(light=True)
    repos = FastSceneRepos(indexer)
    tex_index = build_tex_index()

    results = []
    errors = []

    for skin in catalog:
        sk = skin["skin_key"]
        if want_skins and sk.lower() not in want_skins:
            continue
        tag = f"{skin['char_name']}/{skin['dress_name']}"
        skin_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"]
        cfg_p = skin_dir / ".config.json"
        if not cfg_p.is_file():
            continue
        if args.skip_v2_done and (
            (skin_dir / "submodels" / "scene_back").is_dir()
            or (skin_dir / "submodels" / "scene_back_1").is_dir()
            or (skin_dir / "submodels" / "scene_front").is_dir()
        ):
            continue

        try:
            cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
            base_scale = float(cfg.get("options", {}).get("scale_factor", 0.11) or 0.11)
            sub_root = skin_dir / "submodels"

            ov = _SCENE_LAYOUT_OVERRIDES.get(sk, {})
            layout = inspect_bg_prefab_layout(indexer, skin)
            eff_layout = dict(layout)
            if "override_canvas" in ov:
                eff_layout["canvas_w"], eff_layout["canvas_h"] = ov["override_canvas"]
            if "override_cam" in ov:
                eff_layout["cam_x"], eff_layout["cam_y"] = ov["override_cam"]

            scene = _extract_unity_scene_layers(repos, indexer, skin, eff_layout)
            ps_by_path, _ = extract_unified_ps_draw_keys(indexer, skin)

            # Load manifest skin early so we skip ONLY static img_layers owned by active Tween nodes!
            mf_skin = mf_by_key.get(sk)
            all_tweens = (mf_skin or {}).get("tween_nodes") or []
            tw_prefixes = [("/" + (tw.get("path") or "").lstrip("/")).lower() for tw in all_tweens if tw.get("path")]

            img_layers = scene["img_layers"]
            if tw_prefixes:
                kept = []
                for im in img_layers:
                    ip = ("/" + im["path"].lstrip("/")).lower()
                    if any(ip == tp or ip.startswith(tp + "/") for tp in tw_prefixes):
                        try:
                            im["img"].close()
                        except Exception:
                            pass
                    else:
                        kept.append(im)
                img_layers = kept

            # Determine counter_rot_deg
            p_deg = float(eff_layout["person"].get("z_deg", 0.0))
            preserve_scene_rot = bool(ov.get("preserve_scene_rot", False))
            counter_rot_deg = 0.0
            if not preserve_scene_rot and abs(p_deg) > 0.5 and img_layers:
                big_imgs = [im for im in img_layers if im["w"] >= 1000.0 and im["h"] >= 600.0]
                if big_imgs and all(abs(im["z_deg"] - p_deg) < 1.0 for im in big_imgs):
                    counter_rot_deg = p_deg

            person_key = scene["person_key"]
            back_imgs = [im for im in img_layers if im["draw_key"] < person_key]
            fg_imgs = [im for im in img_layers if im["draw_key"] > person_key]
            back_bjs = _dedup_bj_candidates([b for b in scene["bj_candidates"] if b["draw_key"] < person_key])
            front_bjs = _dedup_bj_candidates([b for b in scene["bj_candidates"] if b["draw_key"] > person_key])

            vp_bounds = compute_viewport_spine_bounds(eff_layout, counter_rot_deg)

            # Load hybrid GPU plan and particle export data (prefer v2 export!)
            mf_clips_by_name = {c["clip"]: c for c in ((mf_skin or {}).get("clips") or [])}
            skin_plan = gpu_plan_all.get(sk) or {"clips": {}}

            exp_data = None
            for cand_p in (PARTICLE_EXPORT_DIR / f"{sk}.json", FALLBACK_EXPORT_DIR / f"{sk}.json"):
                if cand_p.is_file():
                    exp_data = json.loads(cand_p.read_text(encoding="utf-8-sig"))
                    break
            exp_clips_by_name = {c["clip"]: c for c in ((exp_data or {}).get("clips") or [])}

            # Split tweens by side
            back_tweens = [tw for tw in all_tweens if int(tw.get("sort_order", 1)) < person_key[0]]
            front_tweens = [tw for tw in all_tweens if int(tw.get("sort_order", 1)) >= person_key[0]]

            # Split idle & touch clips by exact Unity layer ("back" vs "front")
            back_idle_clips = []
            front_idle_clips = []
            back_touch_specs = []
            front_touch_specs = []

            for cname, p_ent in (skin_plan.get("clips") or {}).items():
                side = "back" if p_ent.get("layer") == "back" else "front"
                ec = exp_clips_by_name.get(cname)
                if p_ent.get("kind") == "idle":
                    (back_idle_clips if side == "back" else front_idle_clips).append((cname, p_ent, ec))
                else:
                    if p_ent.get("mode") == "native":
                        tspec = {"clip": cname, "mode": "native", "export_clip": ec}
                    else:
                        gb = (p_ent.get("gpu_bands") or [{}])[0]
                        nf, af = _load_gpu_clip_frames(sk, gb.get("gpu_clip", cname))
                        tspec = {
                            "clip": cname, "mode": "gpu",
                            "normal_frames": nf, "add_frames": af,
                            "fps": float(gb.get("fps", 20.0)),
                        }
                    (back_touch_specs if side == "back" else front_touch_specs).append(tspec)

            # Build into a clean staging directory first; swap atomically only on complete success!
            stage_root = skin_dir / "_submodels_v2_stage"
            if stage_root.exists():
                shutil.rmtree(stage_root, ignore_errors=True)
            stage_root.mkdir(parents=True, exist_ok=True)

            used_bj_names: set[str] = set()
            back_assigned, back_tmap = _assemble_side(
                "back", back_imgs, back_bjs, back_tweens, back_idle_clips, back_touch_specs,
                mf_clips_by_name, ps_by_path, sk, base_scale, stage_root, repos, eff_layout,
                mf_skin, exp_data, tex_index, counter_rot_deg, preserve_scene_rot, vp_bounds,
                used_bj_names, args.frame_workers,
            )
            front_assigned, front_tmap = _assemble_side(
                "front", fg_imgs, front_bjs, front_tweens, front_idle_clips, front_touch_specs,
                mf_clips_by_name, ps_by_path, sk, base_scale, stage_root, repos, eff_layout,
                mf_skin, exp_data, tex_index, counter_rot_deg, preserve_scene_rot, vp_bounds,
                used_bj_names, args.frame_workers,
            )

            # Close source images
            for im in img_layers:
                try:
                    im["img"].close()
                except Exception:
                    pass

            full_assigned = sorted(back_assigned + front_assigned, key=lambda x: x[2])
            touch_owner_map = {**back_tmap, **front_tmap}

            # Atomic swap of submodels/
            old_backup = skin_dir / "_submodels_v1_old"
            if old_backup.exists():
                shutil.rmtree(old_backup, ignore_errors=True)
            if sub_root.exists():
                sub_root.rename(old_backup)
            stage_root.rename(sub_root)
            if old_backup.exists():
                shutil.rmtree(old_backup, ignore_errors=True)

            new_cmd = "; ".join(f"add_submodel {rel} {ord_v}" for _, rel, ord_v in full_assigned)
            patched = patch_all_language_configs(skin_dir, new_cmd, touch_owner_map)

            total_bytes = sum(f.stat().st_size for f in sub_root.rglob("*") if f.is_file())
            rec = {
                "skin_key": sk,
                "tag": tag,
                "subs": [(Path(r).parent.name, o) for _, r, o in full_assigned],
                "touch_map": touch_owner_map,
                "submodels_mb": round(total_bytes / 1048576, 2),
                "patched_cfgs": patched,
            }
            results.append(rec)
            print(f"  [OK] {sk:24s} ({tag}): {rec['subs']} | {rec['submodels_mb']:.2f} MB", flush=True)
            gc.collect()

        except Exception as exc:
            import traceback
            errors.append({"skin_key": sk, "tag": tag, "error": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()})
            print(f"  [ERR] {sk} ({tag}): {exc}", flush=True)
            stage_root = skin_dir / "_submodels_v2_stage"
            if stage_root.exists():
                shutil.rmtree(stage_root, ignore_errors=True)

    if not args.skip_bg_toggle and not errors:
        print("\nRunning add_spine_bg_toggle.py to sync hide_bg/show_bg...", flush=True)
        import add_spine_bg_toggle
        add_spine_bg_toggle.main()

    report = {
        "ok": len(results),
        "errors": len(errors),
        "total_submodels_mb": round(sum(r["submodels_mb"] for r in results), 2),
        "items": results,
        "error_details": errors,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDONE: ok={len(results)}, errors={len(errors)}, total={report['total_submodels_mb']:.2f} MB -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
