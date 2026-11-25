"""Surgical, non-destructive Spine scene rebuild from official SoulTide art_prefabs.ab + SoulAction runtime.

Fixes ALL root causes discovered by deep-diving SoulTide's MainUI.lua / GirlDressShowUI.lua / SoulSpineCell.lua:
1. Official art_prefabs.ab BgPrefab + dynamically spawned SoulAction entity under Point_Root -> Spine_Scale.localScale
   (instead of stale editor snapshot copies in ui.ab!).
2. SortedComponentOrder.Order takes strict runtime priority over Canvas.m_SortingOrder.
3. All active Unity SpriteRenderer art layers (previously ignored!) extracted with exact PPU, pivot, flip, color & Z-depth.
4. Exact Unity draw_key ordering across ALL submodels (bg_static, bg_mid, bj_*, fg_static, AND fx_*_back / fx_*_front!).
5. Exact fx_* skeleton bounds & fx_root transform synced to official art_prefabs.ab Person transform.

STRICTLY NON-DESTRUCTIVE:
- NEVER touches audio/*.ogg, bgm/*.ogg, main Person .webp/.skel.json/.atlas.txt, or multilingual subtitles!
- Converts all newly generated submodel PNGs to exact lossless WebP (lossless=True, exact=True + np.array_equal check).
- Updates add_submodel commands across ALL start[*] and reload_bg[*] entries in .config.json, config_en.config.json, config_ja.config.json.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import gc
import threading
import numpy as np
from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
SCRIPTS_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本")
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
FX_EXPORT_DIR = TOOLS_DIR / "_batch_fx_particles"
FX_MANIFEST_PATH = FX_EXPORT_DIR / "fx_manifest.json"
REPORT_PATH = SCRIPTS_DIR / "rebuild_art_prefabs_report.json"

sys.path.insert(0, str(TOOLS_DIR))
from batch_fx_exporter import AssetIndexer, FullI18nRepo, build_skin_catalog, inspect_bg_prefab_layout
from batch_spine_builder import (
    _build_scene_submodels_exact,
    _extract_unity_scene_layers,
    _read_sprite_rgba_untrimmed,
)
from soultide_common import CDN_ROOT, load_ab


class FastSceneRepos:
    """Lightweight repo for scene-only rebuilds (indexes dressspine + sprites only, skips 126 CV/BGM ABs!)."""

    def __init__(self, indexer: AssetIndexer, max_cached_abs: int = 16) -> None:
        self.indexer = indexer
        self.max_cached_abs = max_cached_abs
        self._ab_lru: OrderedDict[Path, Any] = OrderedDict()
        self._lru_lock = threading.RLock()
        self.spine_ab_paths: dict[str, Path] = {}
        self.spine_units_by_cpath: dict[str, tuple[str, str]] = {}
        self.spine_units_by_stem: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for ab_name, (ab_path, cpaths) in indexer.dress_spine_units.items():
            self.spine_ab_paths[ab_name] = ab_path
            for cpath in cpaths:
                low = cpath.lower()
                self.spine_units_by_cpath[low] = (ab_name, cpath)
                stem = Path(cpath).name[:-len(".skel.bytes")].lower()
                self.spine_units_by_stem[stem].append((ab_name, cpath))

        sprite_abs = [
            ab
            for sub_dir in ("05_images/image_resources/dress_bg", "05_images/image_resources/soulresources")
            if (CDN_ROOT / sub_dir).exists()
            for ab in sorted((CDN_ROOT / sub_dir).rglob("*.ab"))
        ]
        print(f"[FastSceneRepos] Indexing {len(sprite_abs)} sprite ABs (skipping CV/BGM)...", flush=True)
        self.sprite_loc_by_cab_pid: dict[tuple[str, int], tuple[Path, int]] = {}
        for i, ab_path in enumerate(sprite_abs, 1):
            env = load_ab(ab_path)
            for obj in env.objects:
                if obj.type.name == "Sprite":
                    self.sprite_loc_by_cab_pid[(obj.assets_file.name, obj.path_id)] = (ab_path, obj.path_id)
            del env
            if i % 16 == 0:
                gc.collect()
        gc.collect()

    def _get_ab_env_lru(self, ab_path: Path):
        env = self._ab_lru.get(ab_path)
        if env is not None:
            self._ab_lru.move_to_end(ab_path)
            return env
        env = load_ab(ab_path)
        self._ab_lru[ab_path] = env
        while len(self._ab_lru) > self.max_cached_abs:
            _, evicted = self._ab_lru.popitem(last=False)
            del evicted
        return env

    def get_spine_env(self, ab_name: str):
        ab_path = self.spine_ab_paths[ab_name]
        with self._lru_lock:
            return self._get_ab_env_lru(ab_path)

    def get_sprite_image(self, cab: str, pid: int) -> Image.Image | None:
        res = self.get_sprite_image_and_meta(cab, pid)
        return res[0] if res is not None else None

    def get_sprite_image_and_meta(self, cab: str, pid: int) -> tuple[Image.Image, float, float, float, tuple[float, float, float, float]] | None:
        loc = self.sprite_loc_by_cab_pid.get((cab, pid))
        if loc is None:
            return None
        ab_path, obj_pid = loc
        with self._lru_lock:
            env = self._get_ab_env_lru(ab_path)
            for obj in env.objects:
                if obj.path_id == obj_pid and obj.type.name == "Sprite" and obj.assets_file.name == cab:
                    im = _read_sprite_rgba_untrimmed(obj)
                    tt = obj.read_typetree()
                    ppu = float(tt.get("m_PixelsToUnits", 100.0) or 100.0)
                    pv = tt.get("m_Pivot") or {"x": 0.5, "y": 0.5}
                    bd = tt.get("m_Border") or {"x": 0.0, "y": 0.0, "z": 0.0, "w": 0.0}
                    border = (float(bd.get("x", 0.0)), float(bd.get("y", 0.0)), float(bd.get("z", 0.0)), float(bd.get("w", 0.0)))
                    return im, ppu, float(pv.get("x", 0.5)), float(pv.get("y", 0.5)), border
        return None


def _encode_one_png_to_lossless_webp(png_p: Path) -> tuple[str, str]:
    webp_p = png_p.with_suffix(".webp")
    with Image.open(png_p) as src_im:
        rgba = src_im.convert("RGBA")
        src_arr = np.asarray(rgba)
        rgba.save(webp_p, "WEBP", lossless=True, exact=True, quality=100, method=4)
    with Image.open(webp_p) as chk_im:
        chk_arr = np.asarray(chk_im.convert("RGBA"))
    if not np.array_equal(src_arr, chk_arr):
        webp_p.unlink(missing_ok=True)
        raise RuntimeError(f"Lossless WebP pixel mismatch on {png_p}")
    png_p.unlink()
    return png_p.name, webp_p.name


def convert_submodel_pngs_to_lossless_webp(sub_dir: Path, pool: ThreadPoolExecutor | None = None) -> int:
    """Losslessly convert any PNG textures in a freshly built submodel folder to exact lossless WebP."""
    pngs = sorted(sub_dir.glob("*.png"))
    if not pngs:
        return 0
    if pool is not None and len(pngs) > 1:
        pairs = list(pool.map(_encode_one_png_to_lossless_webp, pngs))
    else:
        pairs = [_encode_one_png_to_lossless_webp(p) for p in pngs]
    rename_map = dict(pairs)
    converted = len(pairs)

    # Update .atlas.txt
    for atl in sub_dir.glob("*.atlas.txt"):
        txt = atl.read_text(encoding="utf-8-sig")
        new_txt = txt
        for old_nm, new_nm in rename_map.items():
            new_txt = new_txt.replace(old_nm, new_nm)
        if new_txt != txt:
            atl.write_text(new_txt, encoding="utf-8")

    # Update .config.json
    cfg_p = sub_dir / ".config.json"
    if cfg_p.is_file():
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
        for atl_rec in cfg.get("atlases", []):
            atl_rec["textures"] = [rename_map.get(t, t) for t in atl_rec.get("textures", [])]
        opts = cfg.setdefault("options", {})
        opts["tex_type"] = 1
        opts.setdefault("shader_type", 0)
        cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    return converted


def sync_fx_submodel_bounds(
    fx_dir: Path,
    layout: dict[str, Any],
    fx_canvas_info: tuple[float, float, float, float] | None,
    counter_rot_deg: float = 0.0,
) -> bool:
    """Update fx_*.json skeleton bounds and (for frame-sequence FX) fx_root x/y/scale to match official layout."""
    cfg_p = fx_dir / ".config.json"
    if not cfg_p.is_file():
        return False
    cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
    skel_p = fx_dir / cfg["skeleton"]
    if not skel_p.is_file():
        return False
    d = json.loads(skel_p.read_text(encoding="utf-8-sig"))

    p = layout["person"]
    p_wx, p_wy = float(p["wx"]), float(p["wy"])
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])

    if fx_canvas_info is not None:
        cw, ch, cam_x, cam_y = fx_canvas_info
    else:
        cw, ch = float(layout["canvas_w"]), float(layout["canvas_h"])
        cam_x, cam_y = float(layout["cam_x"]), float(layout["cam_y"])

    dx_ui = cam_x - p_wx
    dy_ui = cam_y - p_wy
    if abs(counter_rot_deg) > 0.25:
        rad = math.radians(-counter_rot_deg)
        ca, sa = math.cos(rad), math.sin(rad)
        dx_ui, dy_ui = ca * dx_ui - sa * dy_ui, sa * dx_ui + ca * dy_ui

    new_w = cw / max(1e-5, p_ux)
    new_h = ch / max(1e-5, p_uy)
    new_cx = dx_ui / max(1e-5, p_ux)
    new_cy = dy_ui / max(1e-5, p_uy)
    new_x = new_cx - new_w / 2.0
    new_y = new_cy - new_h / 2.0

    sk = d.setdefault("skeleton", {})
    old_w = float(sk.get("width") or new_w)
    old_h = float(sk.get("height") or new_h)
    old_x = float(sk.get("x", new_x))
    old_y = float(sk.get("y", new_y))

    changed = (
        abs(new_x - old_x) > 0.5
        or abs(new_y - old_y) > 0.5
        or abs(new_w - old_w) > 0.5
        or abs(new_h - old_h) > 0.5
    )
    if not changed:
        return False

    sk["x"] = round(new_x, 2)
    sk["y"] = round(new_y, 2)
    sk["width"] = round(new_w, 2)
    sk["height"] = round(new_h, 2)

    bones = d.get("bones") or []
    is_native = any(
        b.get("name") not in ("root", "fx_root") and ("_uv" in b.get("name", "") or "_n" in b.get("name", ""))
        for b in bones
    )
    if not is_native:
        # Frame-sequence FX: update fx_root x/y and scale proportionally to new_w/old_w, new_h/old_h
        for b in bones:
            if b.get("name") == "fx_root":
                b["x"] = round(new_cx, 4)
                b["y"] = round(new_cy, 4)
                if "scaleX" in b and old_w > 1.0:
                    b["scaleX"] = round(float(b["scaleX"]) * (new_w / old_w), 6)
                if "scaleY" in b and old_h > 1.0:
                    b["scaleY"] = round(float(b["scaleY"]) * (new_h / old_h), 6)

    # Update fx_clip vertices if present
    for skin_rec in d.get("skins") or []:
        att = (skin_rec.get("attachments") or {}).get("fx_clip", {}).get("fx_clip")
        if isinstance(att, dict) and att.get("type") == "clipping":
            att["vertices"] = [
                round(new_x, 2), round(new_y, 2),
                round(new_x + new_w, 2), round(new_y, 2),
                round(new_x + new_w, 2), round(new_y + new_h, 2),
                round(new_x, 2), round(new_y + new_h, 2),
            ]

    skel_p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return True


def assign_exact_orders_with_fx(
    non_fx_assigned: list[tuple[str, str, int]],
    fx_dirs_info: list[tuple[str, str, str]],  # (fx_id, fx_rel, side: "back"|"front")
    scene: dict[str, Any],
) -> list[tuple[str, str, int]]:
    """Assign exact Live2DViewerEX orders (-3..-1 behind Person, 1..3 in front of Person)
    strictly following Unity draw_key order for BOTH non-FX and FX submodels!"""
    person_key = scene["person_key"]
    fx_keys = scene.get("fx_nodes_keys") or []
    back_fx_keys = [k for k in fx_keys if k < person_key]
    front_fx_keys = [k for k in fx_keys if k > person_key]

    # Build draw_key map for non-FX submodels from scene layers
    back_imgs = [im for im in scene["img_layers"] if im["draw_key"] < person_key]
    fg_imgs = [im for im in scene["img_layers"] if im["draw_key"] > person_key]
    back_bjs = [b for b in scene["bj_candidates"] if b["draw_key"] < person_key]
    front_bjs = [b for b in scene["bj_candidates"] if b["draw_key"] > person_key]

    def _guess_non_fx_key(rel: str, old_ord: int) -> tuple[int, float, int]:
        folder = Path(rel).parent.name.lower()
        if folder == "bg_static":
            return back_imgs[0]["draw_key"] if back_imgs else (0, 0.0, 0)
        if folder == "bg_mid":
            if back_bjs:
                after = [im["draw_key"] for im in back_imgs if im["draw_key"] > back_bjs[0]["draw_key"]]
                if after:
                    return after[0]
            return back_imgs[-1]["draw_key"] if back_imgs else (2, 0.0, 500)
        if folder == "fg_static":
            return fg_imgs[0]["draw_key"] if fg_imgs else (person_key[0] + 1, 0.0, 99999)
        # bj_* folder: match against back_bjs or front_bjs (normalize underscores e.g. bg02 vs bg_02)
        pool = back_bjs if old_ord < 0 else front_bjs
        fnorm = folder.replace("_", "")
        base_tok = re.sub(r"_\d+$", "", folder) if folder.count("_") >= 2 else folder
        bnorm = base_tok.replace("_", "")
        for b in pool:
            snorm = Path(b["skel_cpath"]).name.lower().replace("_", "")
            if fnorm in snorm or bnorm in snorm:
                return b["draw_key"]
        return (person_key[0] - 1 if old_ord < 0 else person_key[0] + 1, 0.0, 1000 + old_ord)

    neg_entries: list[tuple[tuple[int, float, int], str, str]] = []
    pos_entries: list[tuple[tuple[int, float, int], str, str]] = []

    for sid, rel, ord_v in non_fx_assigned:
        dk = _guess_non_fx_key(rel, ord_v)
        if ord_v < 0:
            neg_entries.append((dk, sid, rel))
        else:
            pos_entries.append((dk, sid, rel))

    for fx_id, fx_rel, side in fx_dirs_info:
        if side == "back":
            # Use minimum Unity back-FX draw_key (so e.g. Akaset_S4 BG01 at Order=1 goes BEFORE bg02 at Order=2!)
            dk = min(back_fx_keys) if back_fx_keys else (person_key[0], -999.0, 999999)
            neg_entries.append((dk, fx_id, fx_rel))
        else:
            dk = max(front_fx_keys) if front_fx_keys else (person_key[0] + 10, 0.0, 999999)
            pos_entries.append((dk, fx_id, fx_rel))

    neg_entries.sort(key=lambda x: x[0])
    pos_entries.sort(key=lambda x: x[0])

    # Assign orders cleanly within [-3, -2, -1] and [1, 2, 3]
    neg_slots = [-3, -2, -1][: len(neg_entries)]
    pos_slots = [1, 2, 3][: len(pos_entries)]

    assigned: list[tuple[str, str, int]] = []
    for (_, sid, rel), o in zip(neg_entries, neg_slots):
        assigned.append((sid, rel, o))
    for (_, sid, rel), o in zip(pos_entries, pos_slots):
        assigned.append((sid, rel, o))
    assigned.sort(key=lambda x: x[2])
    return assigned


def patch_config_submodel_commands(skin_dir: Path, new_cmd: str) -> int:
    """Update add_submodel commands in ALL start[*] and reload_bg[*] entries across all 3 language configs."""
    patched_files = 0
    for cfg_name in (".config.json", "config_en.config.json", "config_ja.config.json"):
        cfg_p = skin_dir / cfg_name
        if not cfg_p.is_file():
            continue
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
        motions = cfg.get("motions") or {}
        changed = False
        for group_name in ("start", "reload_bg"):
            for ent in motions.get(group_name) or []:
                if not isinstance(ent, dict):
                    continue
                old_c = ent.get("command", "")
                if "add_submodel" in old_c or group_name == "start":
                    # Preserve any non-add_submodel commands (e.g. start_mtn ...) if present
                    other_parts = [
                        part.strip()
                        for part in old_c.split(";")
                        if part.strip() and not part.strip().startswith("add_submodel")
                    ]
                    parts = ([new_cmd] if new_cmd else []) + other_parts
                    final_c = "; ".join(parts)
                    if final_c != old_c:
                        ent["command"] = final_c
                        changed = True
        if changed:
            cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            patched_files += 1
    return patched_files


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild Spine scenes from official art_prefabs.ab + SoulAction")
    ap.add_argument("--all", action="store_true", help="Rebuild all 109 dressed skins (default: rebuild affected + sync all)")
    ap.add_argument("--skins", nargs="*", help="Optional list of char/dress tags to rebuild")
    args = ap.parse_args()

    # Load fx_manifest canvas metadata (if available)
    fx_canvas_by_key: dict[str, tuple[float, float, float, float]] = {}
    if FX_MANIFEST_PATH.is_file():
        mf = json.loads(FX_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
        for s in mf.get("skins", []):
            fx_canvas_by_key[s["skin_key"]] = (
                float(s.get("canvas_w", 1700.0)),
                float(s.get("canvas_h", 1132.0)),
                float(s.get("cam_x", 0.0)),
                float(s.get("cam_y", 0.0)),
            )

    # Load affected list from complete_art_diff.json if --all and --skins not provided
    diff_path = Path(r".\_scratch\complete_art_diff.json")
    affected_set: set[str] | None = None
    if args.skins:
        affected_set = set(args.skins)
    elif not args.all and diff_path.is_file():
        affected_set = set(json.loads(diff_path.read_text(encoding="utf-8")).get("all_affected", []))

    repo = FullI18nRepo()
    catalog = build_skin_catalog(repo)
    indexer = AssetIndexer(light=True)
    repos = FastSceneRepos(indexer)
    webp_pool = ThreadPoolExecutor(max_workers=6)

    rebuilt = []
    fx_synced = []
    order_updated = []
    errors = []

    for skin in catalog:
        tag = f"{skin['char_name']}/{skin['dress_name']}"
        skin_dir = SPINE_ROOT / skin["char_name"] / skin["dress_name"]
        cfg_p = skin_dir / ".config.json"
        if not cfg_p.is_file():
            continue

        do_rebuild = (affected_set is None) or (tag in affected_set)
        if args.skins and not do_rebuild:
            continue
        try:
            cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
            base_scale = float(cfg.get("options", {}).get("scale_factor", 0.11) or 0.11)
            sub_root = skin_dir / "submodels"
            sub_root.mkdir(parents=True, exist_ok=True)

            # Discover existing fx_* submodels and their sides from current start[0] command & folder names
            start_cmd = ""
            if (cfg.get("motions") or {}).get("start"):
                start_cmd = cfg["motions"]["start"][0].get("command", "")
            existing_order_by_rel: dict[str, int] = {}
            for m in re.finditer(r"add_submodel\s+(\S+)\s+(-?\d+)", start_cmd):
                existing_order_by_rel[m.group(1)] = int(m.group(2))

            fx_dirs_info: list[tuple[str, str, str]] = []
            for fx_dir in sorted(sub_root.glob("fx_*")):
                if not fx_dir.is_dir():
                    continue
                fcfg_p = fx_dir / ".config.json"
                if not fcfg_p.is_file():
                    continue
                fcfg = json.loads(fcfg_p.read_text(encoding="utf-8-sig"))
                fid = fcfg.get("options", {}).get("id", fx_dir.name)
                frel = f"submodels/{fx_dir.name}/.config.json"
                if fx_dir.name.endswith("_back"):
                    side = "back"
                elif fx_dir.name.endswith("_front"):
                    side = "front"
                else:
                    old_o = existing_order_by_rel.get(frel, 1)
                    side = "back" if old_o < 0 else "front"
                fx_dirs_info.append((fid, frel, side))

            has_back_fx = any(s == "back" for _, _, s in fx_dirs_info)
            has_front_fx = any(s == "front" for _, _, s in fx_dirs_info)

            layout = inspect_bg_prefab_layout(indexer, skin)
            scene = _extract_unity_scene_layers(repos, indexer, skin, layout)

            # Fix single idle-only fx_* side using true art_prefabs.ab ParticleSystem order vs Point_Root!
            if len(fx_dirs_info) == 1 and not fx_dirs_info[0][1].endswith("_back/.config.json") and not fx_dirs_info[0][1].endswith("_front/.config.json"):
                fid0, frel0, side0 = fx_dirs_info[0]
                fdir0 = skin_dir / Path(frel0).parent
                fcfg0 = json.loads((fdir0 / ".config.json").read_text(encoding="utf-8-sig"))
                fsk0 = json.loads((fdir0 / fcfg0["skeleton"]).read_text(encoding="utf-8-sig"))
                fanims0 = [a for a in (fsk0.get("animations") or {}) if a != "idle_empty"]
                has_touch0 = any(a.startswith("fx_") for a in fanims0)
                pk = scene["person_key"]
                fxks = scene.get("fx_nodes_keys") or []
                if fxks and not has_touch0:
                    if all(k < pk for k in fxks):
                        side0 = "back"
                    elif all(k > pk for k in fxks):
                        side0 = "front"
                    fx_dirs_info = [(fid0, frel0, side0)]
                    has_back_fx = side0 == "back"
                    has_front_fx = side0 == "front"

            # Determine counter_rot_deg matching _build_scene_submodels_exact
            p_deg = float(layout["person"].get("z_deg", 0.0))
            counter_rot_deg = 0.0
            if abs(p_deg) > 0.5 and scene["img_layers"]:
                big_imgs = [im for im in scene["img_layers"] if im["w"] >= 1000.0 and im["h"] >= 600.0]
                if big_imgs and all(abs(im["z_deg"] - p_deg) < 1.0 for im in big_imgs):
                    counter_rot_deg = p_deg

            # Close scene images before calling _build_scene_submodels_exact (which reloads cleanly)
            for im in scene["img_layers"]:
                try:
                    im["img"].close()
                except Exception:
                    pass

            if do_rebuild:
                non_fx_assigned, _ = _build_scene_submodels_exact(
                    repos=repos,
                    indexer=indexer,
                    skin=skin,
                    layout=layout,
                    base_scale=base_scale,
                    sub_root=sub_root,
                    has_back_fx=has_back_fx,
                    has_front_fx=has_front_fx,
                    clean_old_non_fx=True,
                    force_fx_sides=(has_back_fx, has_front_fx),
                )
                # Convert any new PNG textures in non-FX submodels to exact lossless WebP in parallel
                sub_dirs_non_fx = [d for d in sorted(sub_root.iterdir()) if d.is_dir() and not d.name.lower().startswith("fx_")]
                all_pngs = [p for d in sub_dirs_non_fx for p in sorted(d.glob("*.png"))]
                webp_cnt = 0
                if all_pngs:
                    results = list(webp_pool.map(_encode_one_png_to_lossless_webp, all_pngs))
                    webp_cnt = len(results)
                    by_dir: dict[Path, dict[str, str]] = defaultdict(dict)
                    for png_p, (old_nm, new_nm) in zip(all_pngs, results):
                        by_dir[png_p.parent][old_nm] = new_nm
                    for d, rmap in by_dir.items():
                        for atl in d.glob("*.atlas.txt"):
                            txt = atl.read_text(encoding="utf-8-sig")
                            nt = txt
                            for o_n, n_n in rmap.items():
                                nt = nt.replace(o_n, n_n)
                            if nt != txt:
                                atl.write_text(nt, encoding="utf-8")
                        cp = d / ".config.json"
                        if cp.is_file():
                            scfg = json.loads(cp.read_text(encoding="utf-8-sig"))
                            for arec in scfg.get("atlases", []):
                                arec["textures"] = [rmap.get(t, t) for t in arec.get("textures", [])]
                            cp.write_text(json.dumps(scfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

                # Sync fx_* bounds & fx_root to new official art_prefabs.ab layout
                fx_cinfo = fx_canvas_by_key.get(skin["skin_key"])
                synced_fx_names = []
                for fx_dir in sorted(sub_root.glob("fx_*")):
                    if fx_dir.is_dir():
                        if sync_fx_submodel_bounds(fx_dir, layout, fx_cinfo, counter_rot_deg):
                            synced_fx_names.append(fx_dir.name)
                if synced_fx_names:
                    fx_synced.append({"skin": tag, "fx": synced_fx_names})

                # Re-assign exact Unity draw_key orders across ALL submodels (non-FX + FX)
                full_assigned = assign_exact_orders_with_fx(non_fx_assigned, fx_dirs_info, scene)
                new_cmd = "; ".join(f"add_submodel {rel} {ord_v}" for _, rel, ord_v in full_assigned)
                patched_cfgs = patch_config_submodel_commands(skin_dir, new_cmd)
                rebuilt.append({
                    "skin": tag,
                    "subs": [(rel, ord_v) for _, rel, ord_v in full_assigned],
                    "webp_converted": webp_cnt,
                    "fx_synced": synced_fx_names,
                    "patched_cfgs": patched_cfgs,
                })
                print(f"  [REBUILT] {tag}: {[(Path(r).parent.name, o) for _, r, o in full_assigned]} (webp={webp_cnt}, fx_sync={synced_fx_names})", flush=True)
            else:
                # Even for non-rebuilt skins, verify FX bounds match official layout & verify add_submodel order!
                fx_cinfo = fx_canvas_by_key.get(skin["skin_key"])
                synced_fx_names = []
                for fx_dir in sorted(sub_root.glob("fx_*")):
                    if fx_dir.is_dir():
                        if sync_fx_submodel_bounds(fx_dir, layout, fx_cinfo, counter_rot_deg):
                            synced_fx_names.append(fx_dir.name)
                if synced_fx_names:
                    fx_synced.append({"skin": tag, "fx": synced_fx_names})
                    print(f"  [FX-SYNC] {tag}: {synced_fx_names}", flush=True)

        except Exception as exc:
            import traceback
            errors.append({"skin": tag, "error": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()})
            print(f"  [ERROR] {tag}: {exc}", flush=True)

    webp_pool.shutdown(wait=True)
    report = {
        "rebuilt_count": len(rebuilt),
        "fx_synced_count": len(fx_synced),
        "error_count": len(errors),
        "rebuilt": rebuilt,
        "fx_synced": fx_synced,
        "errors": errors,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDONE: rebuilt={len(rebuilt)}, fx_synced={len(fx_synced)}, errors={len(errors)}")


if __name__ == "__main__":
    main()
