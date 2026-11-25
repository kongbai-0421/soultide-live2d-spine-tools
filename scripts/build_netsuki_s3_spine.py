r"""Build complete v2 dressed Spine 3.8 Live2DViewerEX package for `梦咲音月 / 此情无垢` (`802_Netsuki_S3`).

Sources:
- `23_spine/dressspine/_batch16.ab`: `SoulDress_Netsuki_03` (main) + `SoulDress_Netsuki_03_BJ_01` (bj_01)
- `03_prefabs/art_prefabs.ab`: `Netsuki_S3_Background` (`Layer_01/Image_01`, `Layer_02/SoulDress_Netsuki_Bg_01`,
  `Point_Root/Spine_Scale`, `Layer_04/Effect` 6 particles, `Layer_05_Limit`), `DressSpine/Netsuki_S3/SoulDress_Netsuki`,
  `FX_UI/Netsuki_S3_Background_greet` (`fx_9008201` greet petals)
- `06_sounds/cv/_netsuki.ab`: all 10 exclusive `Netsuki_Dress2_01..10` clips -> `.ogg` (FFmpeg libvorbis -q:a 5)
  + 3 `Netsuki_After_Marriage_Chat/Touch/Fondle.ogg` from `live2d/梦咲音月/此情无垢/audio/`
- Localization workspace (`Netsuki_source.json` + EN/JA `Netsuki_translation.json`): all 13 official zh/en/ja lines
- Unity v2 hybrid FX: `_batch_fx_particles_v2/802_Netsuki_S3.json` (4 native 60 FPS + 1 touch native)
  + `_batch_fx_gpu_v2/802_Netsuki_S3/` (2 zero-crossfade GPU bands: `glow02` UV flow + `shu` distortion)

Complies 100% with fleet v2 standards:
- V4.4 ETC2 PMA edge cleanup (raw backups in `E:\A灵魂潮汐\备份\spine_etc2_before_clean\`)
- Lossless `exact=True` `.webp` (`tex_type=1`, `np.array_equal` verified)
- Unified composite `scene_back` (-2), `bj_01` (-1), `scene_front` (+1), pure-touch `fx_802_netsuki_s3_touch` (+2)
- 3-language Scheme A configs (`.config.json`, `config_en.config.json`, `config_ja.config.json`)
- Standard Windows `VK_*` `key_trigger` (`65..71, 77, 78, 82, 114, 72`), exact `背景开关:hide_bg/:show_bg`,
  clean remove-before-add `reload_bg`
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
SCRIPT_DIR = Path(__file__).resolve().parent
for p in (str(TOOLS_DIR), str(SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from soultide_common import CDN_ROOT, extract_wav_bytes, load_ab
from batch_fx_exporter import AssetIndexer, inspect_bg_prefab_layout
from batch_spine_builder import _compute_fallback_hit_areas, parse_spine38_binary
from convert_fx_to_native_spine import build_tex_index
from rebuild_spine_scenes_from_art_prefabs import FastSceneRepos, _extract_unity_scene_layers
import rebuild_all_scenes_and_fx_v2 as v2
import spine_etc2_clean_v3 as etc2_clean
import add_spine_bg_toggle as bg_toggle

SCRATCH = Path(r".\_scratch")
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
L2D_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d\梦咲音月\此情无垢")
ETC2_BACKUP_ROOT = Path(r"E:\A灵魂潮汐\备份\spine_etc2_before_clean")
TW_ROOT = Path(r"D:\A灵魂潮汐-本地化\服务器\translation-workspace")
FFMPEG_EXE = shutil.which("ffmpeg") or r"E:\软件\ffmpeg-N-120957-g66e40840d1-win64-gpl\bin\ffmpeg.exe"

NETSUKI_S3_SKIN: dict[str, Any] = {
    "ctrl_id": 802,
    "char_name": "梦咲音月",
    "dress_name": "此情无垢",
    "skin_key": "802_Netsuki_S3",
    "soul_id": 20010008,
    "res_ids": [20020830, 20020831],
    "bg_prefab": "MainCity_Dress_BG/Netsuki_S3_Background",
    "bg_slug": "Netsuki_S3",
    "soul_action_prefab": "DressSpine/Netsuki_S3/SoulDress_Netsuki",
    "spine_bgm": 0,
    "unlock_show": "/ART_Prefabs/Element/DressSpine/Netsuki_S3/SoulDress_Netsuki_Unlock_Spine.prefab",
    "effect_ids": [9008201],
    "effect_prefabs": {9008201: "FX_UI/Netsuki_S3_Background_greet"},
    "effect_orders": {9008201: 4},
}

# Official 13 voice actions for 此情无垢 (sound_id 108139..108148 + After_Marriage 108116..108118)
VOICE_SPECS: list[dict[str, Any]] = [
    {"id": 1,  "iid": "181266672", "ogg": "Netsuki_Dress2_01.ogg",            "ab_stem": "netsuki_dress2_01", "anim": "greet",  "fx": "fx_9008201"},
    {"id": 2,  "iid": "181266673", "ogg": "Netsuki_Dress2_02.ogg",            "ab_stem": "netsuki_dress2_02", "anim": "greet",  "fx": "fx_9008201"},
    {"id": 3,  "iid": "181266674", "ogg": "Netsuki_Dress2_03.ogg",            "ab_stem": "netsuki_dress2_03", "anim": "greet",  "fx": "fx_9008201"},
    {"id": 4,  "iid": "181266675", "ogg": "Netsuki_Dress2_04.ogg",            "ab_stem": "netsuki_dress2_04", "anim": "chat",   "fx": ""},
    {"id": 5,  "iid": "181266676", "ogg": "Netsuki_Dress2_05.ogg",            "ab_stem": "netsuki_dress2_05", "anim": "touch1", "fx": ""},
    {"id": 6,  "iid": "181266677", "ogg": "Netsuki_Dress2_06.ogg",            "ab_stem": "netsuki_dress2_06", "anim": "touch1", "fx": ""},
    {"id": 7,  "iid": "181266678", "ogg": "Netsuki_Dress2_07.ogg",            "ab_stem": "netsuki_dress2_07", "anim": "touch2", "fx": ""},
    {"id": 8,  "iid": "181266679", "ogg": "Netsuki_Dress2_08.ogg",            "ab_stem": "netsuki_dress2_08", "anim": "chat",   "fx": ""},
    {"id": 9,  "iid": "181266680", "ogg": "Netsuki_Dress2_09.ogg",            "ab_stem": "netsuki_dress2_09", "anim": "touch2", "fx": ""},
    {"id": 10, "iid": "181266681", "ogg": "Netsuki_Dress2_10.ogg",            "ab_stem": "netsuki_dress2_10", "anim": "touch1", "fx": ""},
    {"id": 11, "iid": "180005196", "ogg": "Netsuki_After_Marriage_Chat.ogg",  "ab_stem": "",                  "anim": "chat",   "fx": ""},
    {"id": 12, "iid": "180005197", "ogg": "Netsuki_After_Marriage_Touch.ogg", "ab_stem": "",                  "anim": "touch1", "fx": ""},
    {"id": 13, "iid": "180005198", "ogg": "Netsuki_After_Marriage_Fondle.ogg","ab_stem": "",                  "anim": "touch2", "fx": ""},
]

# Calibrated HitAreas (visually verified via render_spine_touch_previews & render_spine_composite_previews)
CALIBRATED_HIT_AREAS: list[dict[str, Any]] | None = [
    {"name": "头",   "id": "tou",    "motion": "头",   "width": 3.6, "height": 3.4, "center_x": -0.26, "center_y":  1.79},
    {"name": "胸",   "id": "ti2",    "motion": "胸",   "width": 2.6, "height": 2.0, "center_x": -0.41, "center_y":  0.30},
    {"name": "左手", "id": "R_shou", "motion": "左手", "width": 3.0, "height": 2.0, "center_x": -0.98, "center_y":  0.04},
    {"name": "右手", "id": "L_shou", "motion": "右手", "width": 2.6, "height": 2.2, "center_x":  0.70, "center_y":  0.32},
    {"name": "腿",   "id": "R_zu",   "motion": "腿",   "width": 3.0, "height": 3.8, "center_x":  0.98, "center_y": -2.12},
    {"name": "足",   "id": "R_zu2",  "motion": "足",   "width": 3.6, "height": 3.0, "center_x":  0.03, "center_y": -0.94},
]


def _probe_ogg_durations_ms(audio_dir: Path) -> dict[str, int]:
    ffprobe = str(Path(FFMPEG_EXE).with_name("ffprobe.exe"))
    if not Path(ffprobe).is_file():
        ffprobe = shutil.which("ffprobe") or "ffprobe"
    out: dict[str, int] = {}
    for sp in VOICE_SPECS:
        ogg_p = audio_dir / sp["ogg"]
        dur_ms = 4500
        if ogg_p.is_file():
            try:
                r = subprocess.run(
                    [ffprobe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(ogg_p)],
                    capture_output=True, text=True, timeout=10,
                )
                sec = float(r.stdout.strip())
                dur_ms = max(4500, min(14000, int(round(sec * 1000)) + 800))
            except Exception:
                pass
        out[sp["ogg"]] = dur_ms
    return out


def _save_lossless_webp(rgba: np.ndarray, out_path: Path) -> None:
    tmp = out_path.with_suffix(".tmp.webp")
    Image.fromarray(rgba, "RGBA").save(tmp, "WEBP", lossless=True, exact=True, quality=100, method=6)
    rt = np.array(Image.open(tmp).convert("RGBA"))
    if not np.array_equal(rgba, rt):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Lossless WebP exact=True round-trip mismatch: {out_path}")
    tmp.replace(out_path)


def _clean_and_convert_spine_tex_to_webp(model_dir: Path, backup_rel_dir: Path) -> str:
    """Apply V4.4 ETC2 PMA cleanup (idempotent backup) and convert any PNG texture in model_dir to lossless WebP."""
    cfg_p = model_dir / ".config.json"
    atlas_p = next(model_dir.glob("*.atlas.txt"))
    atlas_txt = atlas_p.read_text(encoding="utf-8-sig")

    pngs = list(model_dir.glob("*.png"))
    webps = list(model_dir.glob("*.webp"))
    tex_p = pngs[0] if pngs else webps[0]
    raw_rgba = np.array(Image.open(tex_p).convert("RGBA"))
    webp_fn = tex_p.stem + ".webp"
    webp_p = model_dir / webp_fn

    bk_p = ETC2_BACKUP_ROOT / backup_rel_dir / webp_fn
    if not bk_p.is_file():
        bk_p.parent.mkdir(parents=True, exist_ok=True)
        _save_lossless_webp(raw_rgba, bk_p)

    det = etc2_clean.detect_pma_etc2_atlas(raw_rgba)
    if det["needs_clean"]:
        cleaned_rgba, _ = etc2_clean.clean_etc2_spine_pma_v3(raw_rgba, protect_mask=None)
        status = "cleaned"
    else:
        cleaned_rgba = raw_rgba
        status = "already_clean"

    _save_lossless_webp(cleaned_rgba, webp_p)
    if tex_p.suffix.lower() == ".png" and tex_p.is_file():
        tex_p.unlink()

    old_png = tex_p.stem + ".png"
    if old_png in atlas_txt:
        atlas_p.write_text(atlas_txt.replace(old_png, webp_fn), encoding="utf-8", newline="")

    if cfg_p.is_file():
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
        cfg.setdefault("options", {})["tex_type"] = 1
        for a in cfg.get("atlases") or []:
            a["textures"] = [t[:-4] + ".webp" if t.lower().endswith(".png") else t for t in (a.get("textures") or [])]
        cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return status


def _load_3lang_texts() -> dict[str, dict[str, str]]:
    src = json.loads((TW_ROOT / "raw_source/人偶/Netsuki_source.json").read_text(encoding="utf-8"))
    en_tr = json.loads((TW_ROOT / "target_translation/英语/人偶/Netsuki_translation.json").read_text(encoding="utf-8"))
    ja_tr = json.loads((TW_ROOT / "target_translation/日语/人偶/Netsuki_translation.json").read_text(encoding="utf-8"))
    en_map = en_tr.get("translations", en_tr)
    ja_map = ja_tr.get("translations", ja_tr)

    zh_map: dict[str, str] = {}
    items = src if isinstance(src, list) else src.get("items", [])
    for it in items:
        if "item_id" in it and it.get("source_text"):
            zh_map[str(it["item_id"])] = str(it["source_text"]).replace("{$br}", "\n").strip()

    out: dict[str, dict[str, str]] = {}
    for sp in VOICE_SPECS:
        iid = sp["iid"]
        zh = zh_map[iid]
        en = (en_map.get(iid) or {}).get("translation", "").replace("{$br}", "\n").strip() or zh
        ja = (ja_map.get(iid) or {}).get("translation", "").replace("{$br}", "\n").strip() or zh
        out[iid] = {"zh": zh, "en": en, "ja": ja}
    return out


def _extract_audio_oggs(aud_dir: Path) -> None:
    aud_dir.mkdir(parents=True, exist_ok=True)
    # 1. Copy 3 verified After_Marriage OGGs from sibling Live2D
    for sp in VOICE_SPECS:
        if not sp["ab_stem"]:
            src_ogg = L2D_DIR / "audio" / sp["ogg"]
            assert src_ogg.is_file(), f"Missing Live2D audio: {src_ogg}"
            shutil.copy2(src_ogg, aud_dir / sp["ogg"])

    # 2. Extract 10 exclusive Netsuki_Dress2_01..10 AudioClips from _netsuki.ab -> FFmpeg Ogg Vorbis
    e_cv = load_ab(CDN_ROOT / "06_sounds/cv/_netsuki.ab")
    stem_to_obj = {}
    for obj in e_cv.objects:
        if obj.type.name == "AudioClip":
            d = obj.read()
            nm = getattr(d, "m_Name", "").lower()
            if nm.startswith("netsuki_dress2_"):
                stem_to_obj[nm] = obj

    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        for sp in VOICE_SPECS:
            if not sp["ab_stem"]:
                continue
            obj = stem_to_obj.get(sp["ab_stem"].lower())
            assert obj is not None, f"Missing AudioClip {sp['ab_stem']} in _netsuki.ab"
            wav_bytes = extract_wav_bytes(obj)
            wav_p = td_p / f"{sp['ab_stem']}.wav"
            wav_p.write_bytes(wav_bytes)
            out_ogg = aud_dir / sp["ogg"]
            r = subprocess.run(
                [FFMPEG_EXE, "-y", "-loglevel", "error", "-i", str(wav_p), "-c:a", "libvorbis", "-q:a", "5", str(out_ogg)],
                capture_output=True,
                text=True,
            )
            assert r.returncode == 0, f"FFmpeg failed for {sp['ogg']}: {r.stderr}"
            assert out_ogg.read_bytes()[:4] == b"OggS", f"Invalid OggS header in {out_ogg}"


def _load_fx_shumu_01_rgba() -> np.ndarray:
    """Load official Fx_shumu_01 RGBA texture (from Unity FxTex or directly from 14_effect/battle/_batch15.ab)."""
    cand = TOOLS_DIR / "SoulTideBatchFxUnity" / "Assets" / "Textures" / "Fx_shumu_01.png"
    if cand.is_file():
        return np.array(Image.open(cand).convert("RGBA"))
    env = load_ab(CDN_ROOT / "14_effect/battle/_batch15.ab")
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            d = obj.read()
            if d.m_Name == "Fx_shumu_01":
                return np.array(d.image.convert("RGBA"))
    raise FileNotFoundError("Fx_shumu_01 texture not found in Unity Assets or 14_effect/battle/_batch15.ab")


def _inject_native_shu_branches(sf_dir: Path, layout: dict[str, Any], vp_bounds: tuple[float, float, float, float]) -> dict[str, Any]:
    """Replace twitchy GPU-distorted `shu` (Fx_shumu_01) with 4 native Spine 3.8 infinite-FPS
    2-bone smooth-skinned swaying peach branches clipped cleanly to viewport bounds."""
    raw = _load_fx_shumu_01_rgba()
    H, W, _ = raw.shape
    mask = raw[:, :, 3] > 3

    # 4-connected components (pure numpy/deque, zero scipy dependency)
    labeled = np.zeros((H, W), dtype=np.int32)
    ncomp = 0
    ys_all, xs_all = np.where(mask)
    for y0, x0 in zip(ys_all.tolist(), xs_all.tolist()):
        if labeled[y0, x0] != 0:
            continue
        ncomp += 1
        q = deque([(y0, x0)])
        labeled[y0, x0] = ncomp
        while q:
            cy, cx = q.popleft()
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and labeled[ny, nx] == 0:
                    labeled[ny, nx] = ncomp
                    q.append((ny, nx))

    # Deterministic grouping into 4 distinct branches matching Fx_shumu_01 composition:
    #   b0: upper-left hanging branch (above umbrella) -> cx < 660, cy < 380
    #   b1: upper-right branch -> cx >= 660, cy < 300
    #   b3: lower-right hanging flower cluster -> x_min > 790 and y_max > 760
    #   b2: mid-right main hanging branch -> remaining cy >= 300
    branch_masks = {k: np.zeros((H, W), dtype=bool) for k in ("shu_b0", "shu_b1", "shu_b2", "shu_b3")}
    for cid in range(1, ncomp + 1):
        cm = labeled == cid
        ys, xs = np.where(cm)
        cx, cy = float(xs.mean()), float(ys.mean())
        xmin, ymax = int(xs.min()), int(ys.max())
        if cx < 660 and cy < 380:
            key = "shu_b0"
        elif cx >= 660 and cy < 300:
            key = "shu_b1"
        elif xmin > 790 and ymax > 760:
            key = "shu_b3"
        else:
            key = "shu_b2"
        branch_masks[key] |= cm

    # Exact Unity ParticleSystem world quad -> Spine world coordinate mapping
    vx0, vy0, vx1, vy1 = vp_bounds
    vp_cx, vp_cy = (vx0 + vx1) * 0.5, (vy0 + vy1) * 0.5
    spine_per_ui = (vx1 - vx0) / float(layout["canvas_w"])
    cam_x, cam_y = float(layout["cam_x"]), float(layout["cam_y"])
    shu_w_ui = 400.0 * 4.348187446594238
    shu_h_ui = 400.0 * 3.9217119216918945
    shu_cx_sp = vp_cx + (240.0 - cam_x) * spine_per_ui
    shu_cy_sp = vp_cy + (30.0 - cam_y) * spine_per_ui
    shu_w_sp = shu_w_ui * spine_per_ui
    shu_h_sp = shu_h_ui * spine_per_ui
    quad_x0 = shu_cx_sp - shu_w_sp * 0.5
    quad_y1 = shu_cy_sp + shu_h_sp * 0.5

    def px_to_spine(px: float, py: float) -> tuple[float, float]:
        return (
            quad_x0 + (px / float(W)) * shu_w_sp,
            quad_y1 - (py / float(H)) * shu_h_sp,
        )

    # Branch rigging specs (root anchor outside viewport clip border -> natural wind sway with phase lag)
    branch_specs = [
        {"key": "shu_b0", "root_px": (645.0, 56.0),  "tip_px": (260.0, 335.0), "cycles": 2, "phase": 0.00, "amp_base": 1.35, "amp_tip": 2.10},
        {"key": "shu_b1", "root_px": (978.0, 72.0),  "tip_px": (678.0, 252.0), "cycles": 2, "phase": 0.31, "amp_base": 1.15, "amp_tip": 1.85},
        {"key": "shu_b2", "root_px": (978.0, 395.0), "tip_px": (710.0, 725.0), "cycles": 2, "phase": 0.62, "amp_base": 1.40, "amp_tip": 2.20},
        {"key": "shu_b3", "root_px": (978.0, 605.0), "tip_px": (828.0, 780.0), "cycles": 3, "phase": 0.17, "amp_base": 1.20, "amp_tip": 1.75},
    ]

    # Crop each branch with 2px transparent pad, convert to strict PMA, and shelf-pack into 1 lossless WebP page
    pad = 2
    crops: list[dict[str, Any]] = []
    for sp in branch_specs:
        bm = branch_masks[sp["key"]]
        ys, xs = np.where(bm)
        assert len(xs) > 0, f"Empty mask for {sp['key']}"
        x0, x1 = max(0, int(xs.min()) - pad), min(W, int(xs.max()) + 1 + pad)
        y0, y1 = max(0, int(ys.min()) - pad), min(H, int(ys.max()) + 1 + pad)
        sub = raw[y0:y1, x0:x1].copy()
        sub[~bm[y0:y1, x0:x1]] = 0
        # Strict Premultiplied Alpha (required by EX DefaultPMAShader / tex_type=1)
        a = sub[:, :, 3:4].astype(np.float32) / 255.0
        rgb_pma = np.round(sub[:, :, :3].astype(np.float32) * a).clip(0, 255).astype(np.uint8)
        rgb_pma[sub[:, :, 3] == 0] = 0
        pma = np.concatenate([rgb_pma, sub[:, :, 3:4]], axis=2)
        crops.append({**sp, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "cw": x1 - x0, "ch": y1 - y0, "pma": pma})

    # Compact 2-row packing (b0 + b1 on row 0, b2 + b3 on row 1) with 4px gutter
    gutter = 4
    r0_w = crops[0]["cw"] + gutter + crops[1]["cw"] + 2 * gutter
    r0_h = max(crops[0]["ch"], crops[1]["ch"])
    r1_w = crops[2]["cw"] + gutter + crops[3]["cw"] + 2 * gutter
    r1_h = max(crops[2]["ch"], crops[3]["ch"])
    page_w = max(r0_w, r1_w)
    page_h = r0_h + r1_h + 3 * gutter
    # Round up to multiple of 4 for GPU friendliness
    page_w = ((page_w + 3) // 4) * 4
    page_h = ((page_h + 3) // 4) * 4
    atlas_rgba = np.zeros((page_h, page_w, 4), dtype=np.uint8)
    placements = [
        (gutter, gutter),
        (gutter + crops[0]["cw"] + gutter, gutter),
        (gutter, gutter + r0_h + gutter),
        (gutter + crops[2]["cw"] + gutter, gutter + r0_h + gutter),
    ]
    for cr, (ax, ay) in zip(crops, placements):
        atlas_rgba[ay:ay + cr["ch"], ax:ax + cr["cw"]] = cr["pma"]
        cr["ax"], cr["ay"] = ax, ay

    shu_tex_stem = "scene_front_shu"
    shu_webp_fn = f"{shu_tex_stem}.webp"
    _save_lossless_webp(atlas_rgba, sf_dir / shu_webp_fn)

    # Append page to scene_front.atlas.txt
    atlas_p = sf_dir / "scene_front.atlas.txt"
    atlas_lines = [
        "",
        shu_webp_fn,
        f"size: {page_w},{page_h}",
        "format: RGBA8888",
        "filter: Linear,Linear",
        "repeat: none",
    ]
    for cr in crops:
        atlas_lines.extend([
            cr["key"],
            "  rotate: false",
            f"  xy: {cr['ax']}, {cr['ay']}",
            f"  size: {cr['cw']}, {cr['ch']}",
            f"  orig: {cr['cw']}, {cr['ch']}",
            "  offset: 0, 0",
            "  index: -1",
        ])
    atlas_txt = atlas_p.read_text(encoding="utf-8-sig").rstrip() + "\n" + "\n".join(atlas_lines) + "\n"
    atlas_p.write_text(atlas_txt, encoding="utf-8")

    # Update scene_front/.config.json to register scene_front_shu.webp
    scfg_p = sf_dir / ".config.json"
    scfg = json.loads(scfg_p.read_text(encoding="utf-8-sig"))
    atl0 = scfg["atlases"][0]
    if shu_tex_stem not in atl0["tex_names"]:
        atl0["tex_names"].append(shu_tex_stem)
        atl0["textures"].append(shu_webp_fn)
    scfg_p.write_text(json.dumps(scfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # Patch scene_front.json: bones, fx_clip_shu, 4 skinned mesh slots, and smooth 20s idle sway curves
    sk_p = sf_dir / scfg["skeleton"]
    sk_data = json.loads(sk_p.read_text(encoding="utf-8-sig"))
    bones = sk_data["bones"]
    slots = sk_data["slots"]
    skin_atts = sk_data["skins"][0]["attachments"]
    idle_anim = sk_data["animations"]["idle"]
    anim_bones = idle_anim.setdefault("bones", {})

    # Determine idle loop duration (preserve existing 20.0s duration)
    loop_t = 20.0
    for sdata in (idle_anim.get("slots") or {}).values():
        for arr in sdata.values():
            if arr:
                loop_t = max(loop_t, float(arr[-1].get("time", 0.0)))
    for bdata in anim_bones.values():
        for arr in bdata.values():
            if arr:
                loop_t = max(loop_t, float(arr[-1].get("time", 0.0)))
    loop_t = round(loop_t, 4)

    # Add viewport clipping slot dedicated to the 4 peach branches (zero nested clips!)
    slots.append({"name": "fx_clip_shu", "bone": "root", "attachment": "fx_clip_shu"})
    skin_atts["fx_clip_shu"] = {
        "fx_clip_shu": {
            "type": "clipping",
            "end": "shu_b3",
            "vertexCount": 4,
            "vertices": [
                round(vx0, 2), round(vy0, 2),
                round(vx1, 2), round(vy0, 2),
                round(vx1, 2), round(vy1, 2),
                round(vx0, 2), round(vy1, 2),
            ],
        }
    }

    NX, NY = 8, 8
    n_steps = int(round(loop_t / 0.5))  # 0.5s steps -> 40 segments over 20s

    for cr in crops:
        bkey = cr["key"]
        base_wx, base_wy = px_to_spine(*cr["root_px"])
        tip_end_wx, tip_end_wy = px_to_spine(*cr["tip_px"])
        mid_wx = base_wx + 0.42 * (tip_end_wx - base_wx)
        mid_wy = base_wy + 0.42 * (tip_end_wy - base_wy)

        base_name = f"{bkey}_base"
        tip_name = f"{bkey}_tip"
        idx_base = len(bones)
        bones.append({"name": base_name, "parent": "root", "x": round(base_wx, 2), "y": round(base_wy, 2)})
        idx_tip = len(bones)
        bones.append({"name": tip_name, "parent": base_name, "x": round(mid_wx - base_wx, 2), "y": round(mid_wy - base_wy, 2)})

        # Build NX x NY grid skinned mesh with C1 smoothstep weights along root->tip axis
        dx_ax = tip_end_wx - base_wx
        dy_ax = tip_end_wy - base_wy
        ax_len2 = max(1.0, dx_ax * dx_ax + dy_ax * dy_ax)

        uvs: list[float] = []
        verts: list[float] = []
        for gy in range(NY + 1):
            v_frac = gy / float(NY)
            py = cr["y0"] + v_frac * cr["ch"]
            for gx in range(NX + 1):
                u_frac = gx / float(NX)
                px = cr["x0"] + u_frac * cr["cw"]
                wx, wy = px_to_spine(px, py)
                uvs.extend([round(u_frac, 5), round(v_frac, 5)])

                s = ((wx - base_wx) * dx_ax + (wy - base_wy) * dy_ax) / ax_len2
                s = max(0.0, min(1.0, (s - 0.15) / 0.80))
                w_tip = s * s * (3.0 - 2.0 * s)
                w_base = 1.0 - w_tip
                if w_tip <= 1e-4:
                    verts.extend([1, idx_base, round(wx - base_wx, 2), round(wy - base_wy, 2), 1.0])
                elif w_base <= 1e-4:
                    verts.extend([1, idx_tip, round(wx - mid_wx, 2), round(wy - mid_wy, 2), 1.0])
                else:
                    verts.extend([
                        2,
                        idx_base, round(wx - base_wx, 2), round(wy - base_wy, 2), round(w_base, 5),
                        idx_tip,  round(wx - mid_wx, 2),  round(wy - mid_wy, 2),  round(w_tip, 5),
                    ])

        tris: list[int] = []
        stride = NX + 1
        for gy in range(NY):
            for gx in range(NX):
                i00 = gy * stride + gx
                i10 = i00 + 1
                i01 = i00 + stride
                i11 = i01 + 1
                tris.extend([i00, i10, i11, i00, i11, i01])

        slots.append({"name": bkey, "bone": base_name, "attachment": bkey})
        skin_atts[bkey] = {
            bkey: {
                "type": "mesh",
                "uvs": uvs,
                "triangles": tris,
                "vertices": verts,
                "hull": 0,
                "width": cr["cw"],
                "height": cr["ch"],
            }
        }

        # Seamless infinite-FPS sinusoidal breeze rotation curves (zero endpoint discontinuity)
        cyc = cr["cycles"]
        ph = cr["phase"]
        rot_base: list[dict[str, Any]] = []
        rot_tip: list[dict[str, Any]] = []
        for k in range(n_steps + 1):
            t = round(loop_t * k / n_steps, 4)
            ang_b = cr["amp_base"] * math.sin(2.0 * math.pi * (cyc * k / n_steps + ph))
            # Subtle secondary harmonic + 0.18-cycle phase lag for organic willow-like tip follow-through
            ang_t = cr["amp_tip"] * math.sin(2.0 * math.pi * (cyc * k / n_steps + ph - 0.18))
            rot_base.append({"time": t, "angle": round(ang_b, 4)})
            rot_tip.append({"time": t, "angle": round(ang_t, 4)})
        anim_bones[base_name] = {"rotate": rot_base}
        anim_bones[tip_name] = {"rotate": rot_tip}

    sk_p.write_text(json.dumps(sk_data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    webp_kb = (sf_dir / shu_webp_fn).stat().st_size / 1024.0
    return {"page": shu_webp_fn, "size": f"{page_w}x{page_h}", "kb": round(webp_kb, 1), "branches": len(crops), "loop_t": loop_t}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Netsuki S3 (此情无垢) v2 Spine package")
    ap.add_argument("--front-only", action="store_true", help="Rebuild only submodels/scene_front (+ native peach branches) in place")
    args = ap.parse_args()

    skin_dir = SPINE_ROOT / "梦咲音月" / "此情无垢"
    if not args.front_only:
        if skin_dir.exists():
            shutil.rmtree(skin_dir)
        skin_dir.mkdir(parents=True, exist_ok=True)

        # 1. Extract main Spine SoulDress_Netsuki_03 from _batch16.ab
        e16 = load_ab(CDN_ROOT / "23_spine/dressspine/_batch16.ab")
        cm16 = {ptr.path_id: cp for cp, ptr in e16.container.items()}
        atlas_bytes = skel_bytes = None
        tex_rgba = None
        tex_name = ""
        for obj in e16.objects:
            cp = cm16.get(obj.path_id, "")
            if "souldress_netsuki_03/souldress_netsuki_03/" not in cp.lower():
                continue
            if obj.type.name == "TextAsset":
                d = obj.read()
                raw = d.m_Script if isinstance(d.m_Script, (bytes, bytearray)) else d.m_Script.encode("utf-8", "surrogateescape")
                if cp.endswith(".atlas.txt"):
                    atlas_bytes = bytes(raw)
                elif cp.endswith(".skel.bytes"):
                    skel_bytes = bytes(raw)
            elif obj.type.name == "Texture2D":
                d = obj.read()
                tex_name = d.m_Name
                tex_rgba = np.array(d.image.convert("RGBA"))
        assert atlas_bytes and skel_bytes and tex_rgba is not None

        skel_fn = "SoulDress_Netsuki_03.skel.json"
        atlas_fn = "SoulDress_Netsuki_03.atlas.txt"
        png_fn = f"{tex_name}.png"
        (skin_dir / skel_fn).write_bytes(skel_bytes)
        (skin_dir / atlas_fn).write_bytes(atlas_bytes)
        Image.fromarray(tex_rgba, "RGBA").save(skin_dir / png_fn, "PNG")
        main_etc2 = _clean_and_convert_spine_tex_to_webp(skin_dir, Path("梦咲音月/此情无垢"))
        webp_fn = f"{tex_name}.webp"
        print(f"[1/5] Main Spine extracted + V4.4 ETC2 ({main_etc2}) -> {webp_fn}", flush=True)

        # 2. Extract & encode all 13 audio .ogg clips + load 3-language texts
        _extract_audio_oggs(skin_dir / "audio")
        texts = _load_3lang_texts()
        print(f"[2/5] Extracted 13 .ogg voice clips + 3-language subtitles", flush=True)

    # 3. Assemble v2 submodels (scene_back, bj_01, scene_front, fx_802_netsuki_s3_touch)
    base_scale = 0.0726
    sk = NETSUKI_S3_SKIN["skin_key"]
    mf = json.loads((SCRATCH / "netsuki_s3_fx_manifest.json").read_text(encoding="utf-8-sig"))
    mf_skin = mf["skins"][0]
    gpu_plan = json.loads((SCRATCH / "netsuki_s3_gpu_bands_plan.json").read_text(encoding="utf-8-sig"))["skins"][sk]
    exp_data = json.loads((TOOLS_DIR / "_batch_fx_particles_v2" / f"{sk}.json").read_text(encoding="utf-8-sig"))

    indexer = AssetIndexer(light=True)
    repos = FastSceneRepos(indexer)
    tex_index = build_tex_index()
    layout = inspect_bg_prefab_layout(indexer, NETSUKI_S3_SKIN)
    scene = _extract_unity_scene_layers(repos, indexer, NETSUKI_S3_SKIN, layout)
    ps_by_path, _ = v2.extract_unified_ps_draw_keys(indexer, NETSUKI_S3_SKIN)

    person_key = scene["person_key"]
    img_layers = scene["img_layers"]
    back_imgs = [im for im in img_layers if im["draw_key"] < person_key]
    fg_imgs = [im for im in img_layers if im["draw_key"] > person_key]
    back_bjs = v2._dedup_bj_candidates([b for b in scene["bj_candidates"] if b["draw_key"] < person_key])
    front_bjs = v2._dedup_bj_candidates([b for b in scene["bj_candidates"] if b["draw_key"] > person_key])
    vp_bounds = v2.compute_viewport_spine_bounds(layout, 0.0)

    mf_clips_by_name = {c["clip"]: c for c in (mf_skin.get("clips") or [])}
    exp_clips_by_name = {c["clip"]: c for c in (exp_data.get("clips") or [])}

    back_idle_clips, front_idle_clips = [], []
    back_touch_specs, front_touch_specs = [], []
    for cname, p_ent in (gpu_plan.get("clips") or {}).items():
        side = "back" if p_ent.get("layer") == "back" else "front"
        ec = exp_clips_by_name.get(cname)
        if p_ent.get("kind") == "idle":
            # Exclude GPU-distorted `shu` band (idle__gb01_o4); replaced with infinite-FPS native Spine skinned peach branches!
            p_clean = copy.deepcopy(p_ent)
            p_clean["gpu_bands"] = [gb for gb in (p_clean.get("gpu_bands") or []) if gb.get("gpu_clip") != "idle__gb01_o4"]
            (back_idle_clips if side == "back" else front_idle_clips).append((cname, p_clean, ec))
        else:
            tspec = {"clip": cname, "mode": "native", "export_clip": ec}
            (back_touch_specs if side == "back" else front_touch_specs).append(tspec)

    sub_root = skin_dir / "submodels"
    sub_root.mkdir(parents=True, exist_ok=True)
    used_bj_names: set[str] = set()

    if args.front_only:
        sf_dir = sub_root / "scene_front"
        if sf_dir.exists():
            shutil.rmtree(sf_dir)
        front_assigned, front_tmap = v2._assemble_side(
            "front", fg_imgs, front_bjs, [], front_idle_clips, [],
            mf_clips_by_name, ps_by_path, sk, base_scale, sub_root, repos, layout,
            mf_skin, exp_data, tex_index, 0.0, False, vp_bounds, used_bj_names, 4,
        )
        shu_info = _inject_native_shu_branches(sf_dir, layout, vp_bounds)
        print(f"[front-only] Rebuilt scene_front ({front_assigned}) + native peach branches: {shu_info}", flush=True)
        return

    back_assigned, back_tmap = v2._assemble_side(
        "back", back_imgs, back_bjs, [], back_idle_clips, back_touch_specs,
        mf_clips_by_name, ps_by_path, sk, base_scale, sub_root, repos, layout,
        mf_skin, exp_data, tex_index, 0.0, False, vp_bounds, used_bj_names, 4,
    )
    front_assigned, front_tmap = v2._assemble_side(
        "front", fg_imgs, front_bjs, [], front_idle_clips, front_touch_specs,
        mf_clips_by_name, ps_by_path, sk, base_scale, sub_root, repos, layout,
        mf_skin, exp_data, tex_index, 0.0, False, vp_bounds, used_bj_names, 4,
    )
    shu_info = _inject_native_shu_branches(sub_root / "scene_front", layout, vp_bounds)
    print(f"      Native infinite-FPS peach branches injected into scene_front: {shu_info}", flush=True)

    # Clean & WebP-convert bj_01 (binary Spine submodel extracted as PNG)
    bj01_dir = sub_root / "bj_01"
    if bj01_dir.is_dir():
        bj_etc2 = _clean_and_convert_spine_tex_to_webp(bj01_dir, Path("梦咲音月/此情无垢/submodels/bj_01"))
        print(f"      bj_01 V4.4 ETC2 ({bj_etc2}) + lossless WebP applied", flush=True)

    all_assigned = back_assigned + front_assigned
    touch_owner_map = {**back_tmap, **front_tmap}
    print(f"[3/5] Submodels assembled: {all_assigned}, touch_owner_map={touch_owner_map}", flush=True)

    add_cmd_str = "; ".join(f"add_submodel {srel} {ord_v}" for _, srel, ord_v in all_assigned)
    reload_cmd_str = "; ".join(
        [f"remove_submodel {srel}" for _, srel, _ in all_assigned]
        + [f"add_submodel {srel} {ord_v}" for _, srel, ord_v in all_assigned]
    )
    touch_fx_id = touch_owner_map.get("fx_9008201", "")
    assert touch_fx_id, "Expected fx_9008201 in touch_owner_map"

    # Compute Hide/Show BG commands (Class C: remove scene_back/bj_01/scene_front, preserve pure-touch fx_802_netsuki_s3_touch!)
    bg_only_rels = [srel for sid, srel, _ in all_assigned if sid != touch_fx_id]
    hide_cmd_str = "; ".join(f"remove_submodel {r}" for r in bg_only_rels)
    show_cmd_str = add_cmd_str

    # 4. Build motions + hit_areas + 3-language configs
    parsed = parse_spine38_binary(skel_bytes)
    by_id = {sp["id"]: sp for sp in VOICE_SPECS}
    ogg_durs = _probe_ogg_durations_ms(skin_dir / "audio")

    def mk_mtn(vid: int, marry: bool, lang: str, name_override: str = "", cmd_override: str = "") -> dict[str, Any]:
        sp = by_id[vid]
        anim = f"{sp['anim']}_marry" if marry else sp["anim"]
        ent: dict[str, Any] = {
            "name": name_override or f"act_{vid:02d}_{'m' if marry else 'n'}",
            "file": anim,
            "fade_in": 100,
            "fade_out": 100,
            "sound": f"audio/{sp['ogg']}",
            "text": texts[sp["iid"]][lang],
            "text_duration": ogg_durs.get(sp["ogg"], 4500),
        }
        if cmd_override:
            ent["command"] = cmd_override
        elif sp["fx"]:
            ent["command"] = f"start_mtn {touch_fx_id} main:{sp['fx']}"
        return ent

    def build_motions(lang: str) -> dict[str, Any]:
        mt = bg_toggle.MENU_TEXTS[lang]
        return {
            "idle": [{"name": "idle_marry", "file": "idle_marry", "fade_in": 10, "fade_out": 10, "file_loop": True}],
            "start": [
                mk_mtn(1, True, lang, "start_morning", add_cmd_str),
                mk_mtn(2, True, lang, "start_noon",    add_cmd_str),
                mk_mtn(3, True, lang, "start_evening", add_cmd_str),
            ],
            "reload_bg": [{"name": "reload_submodels", "file": "idle_marry", "command": reload_cmd_str}],
            "闲聊与问答": [mk_mtn(v, True, lang) for v in (4, 11, 1, 2, 3, 8)],
            "头":         [mk_mtn(v, True, lang) for v in (5, 7, 13)],
            "左手":       [mk_mtn(v, True, lang) for v in (6, 10)],
            "右手":       [mk_mtn(v, True, lang) for v in (10, 6)],
            "胸":         [mk_mtn(v, True, lang) for v in (9, 8, 13)],
            "腿":         [mk_mtn(v, True, lang) for v in (12, 5, 7)],
            "足":         [mk_mtn(v, True, lang) for v in (12, 5)],
            "普通模式全动作": [mk_mtn(sp["id"], False, lang, f"normal_{sp['id']:02d}") for sp in VOICE_SPECS],
            "誓约模式全动作": [mk_mtn(sp["id"], True,  lang, f"marry_{sp['id']:02d}")  for sp in VOICE_SPECS],
            "背景开关": [
                {"name": "hide_bg", "file": "", "command": hide_cmd_str},
                {"name": "show_bg", "file": "", "command": show_cmd_str},
            ],
            "背景菜单": [
                {
                    "name": "bg_toggle_menu",
                    "file": "",
                    "text": mt["prompt"],
                    "text_duration": 30000,
                    "choices": [
                        {"text": mt["hide"], "next_mtn": "背景开关:hide_bg"},
                        {"text": mt["show"], "next_mtn": "背景开关:show_bg"},
                    ],
                }
            ],
        }

    zh_mots = build_motions("zh")
    if CALIBRATED_HIT_AREAS:
        hit_areas = [dict(h) for h in CALIBRATED_HIT_AREAS]
    else:
        hit_areas = _compute_fallback_hit_areas(parsed, "idle_marry", zh_mots)

    key_items = [
        {"input": 65,  "down_mtn": "闲聊与问答"},
        {"input": 66,  "down_mtn": "头"},
        {"input": 67,  "down_mtn": "左手"},
        {"input": 68,  "down_mtn": "右手"},
        {"input": 69,  "down_mtn": "胸"},
        {"input": 70,  "down_mtn": "腿"},
        {"input": 71,  "down_mtn": "足"},
        {"input": 77,  "down_mtn": "誓约模式全动作"},
        {"input": 78,  "down_mtn": "普通模式全动作"},
        {"input": 82,  "down_mtn": "reload_bg"},
        {"input": 114, "down_mtn": "背景菜单"},
        {"input": 72,  "down_mtn": "背景菜单"},
    ]

    for lang_code, cfg_fn in (("zh", ".config.json"), ("en", "config_en.config.json"), ("ja", "config_ja.config.json")):
        mots = zh_mots if lang_code == "zh" else build_motions(lang_code)
        cfg = {
            "conf_ver": 1,
            "type": 9,
            "controllers": {
                "param_hit": {},
                "param_loop": {},
                "key_trigger": {"enabled": True, "items": key_items},
                "eye_blink": {"min_interval": 500, "max_interval": 6000},
                "lip_sync": {"gain": 5.0},
                "mouse_tracking": {"smooth_time": 0.15},
                "auto_breath": {},
                "extra_motion": {},
                "accelerometer": {},
                "intimacy_system": {},
                "slot_opacity": {},
                "slot_color": {},
            },
            "hit_areas": hit_areas,
            "motions": mots,
            "options": {
                "id": "802_netsuki_s3_main",
                "scale_factor": base_scale,
                "position_x": 0.0,
                "position_y": 0.0,
                "tex_type": 1,
                "edge_padding": False,
                "shader_type": 0,
            },
            "skeleton": skel_fn,
            "atlases": [{"atlas": atlas_fn, "tex_names": [tex_name], "textures": [webp_fn]}],
        }
        (skin_dir / cfg_fn).write_text(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"[4/5] Wrote 3-language configs (.config.json / en / ja), hit_areas={len(hit_areas)}", flush=True)
    print(f"[5/5] DONE building 梦咲音月/此情无垢 -> {skin_dir}", flush=True)


if __name__ == "__main__":
    main()
