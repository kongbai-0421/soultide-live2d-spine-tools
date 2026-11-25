"""Batch Live2DViewerEX Spine Package Builder for SoulTide (all 111 Dress Spine entries).

Builds complete Spine 3.8.79 packages under:
  E:\\A灵魂潮汐\\Live2D与Spine模型\\spine\\<角色名>\\<皮肤名>\\

Builds all Dress Spine packages including `欧若拉\\童话心绘`, while preserving all read-only
assets and shared tools. Supports `--resume`, `--char`, `--ctrl`, `--limit`, and per-skin
exception isolation with full JSON reporting.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
import gc
import json
import math
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from batch_fx_exporter import (
    AssetIndexer,
    BLACK_LETTERBOX_CABS,
    FX_SEQ_ROOT,
    FullI18nRepo,
    SKIP_IMAGE_NAMES,
    _is_censor_cloud,
    _node_local_tf,
    _qmul,
    _qrot,
    build_skin_catalog,
    inspect_bg_prefab_layout,
    resolve_bg_prefab_root,
    resolve_soul_action_entity,
)
from soultide_common import CDN_ROOT, load_ab, write_json
from spine_fx_submodel_packer import AnimSequenceSpec, pack_fx_submodel

SPINE_OUT_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
BACKUP_SPINE_ROOT = Path(r"E:\A灵魂潮汐\备份\spine")
REPORT_PATH = TOOLS_DIR / "batch_spine_build_report.json"

BLACK_LETTERBOX_CAB = "CAB-055435a60c36b7081bba8594353412b1"
STRIP_SLOT_RE = re.compile(r"(harmonious|cloud|^beijing\d*$|^bj_?\d+$)", re.I)

# Declarative per-skin scene layout overrides (audited against official Unity BgPrefab & SoulAction)
_SCENE_LAYOUT_OVERRIDES: dict[str, dict[str, Any]] = {
    # 拉薇拉/丛林猎手: Axis-aligned Image_01 (1702x1084 @ cam=(1,162)) upright viewport + unified -10 deg scene rotation
    "901_Lavira_S2": {
        "override_canvas": (1702, 1084),
        "override_cam": (1.0, 162.0),
        "preserve_scene_rot": True,
        "main_root_rot": -10.0,
    },
    # 露比·罗斯/圣诞怪盗: -3 bg_static(夜空) -> -2 fx_back(雪花) -> -1 bg_mid(完整窗框窗棂) | +1 bj_02(与人物零重叠) -> +2 bj_01 -> +3 fx_front
    "4501_RubyRose_S2": {
        "sandwich_bg_mid_min_ord": 2,
        "promote_back_bj_to_pos": ("souldress_rubyrose_02_bj_02.skel.bytes",),
    },
    # 安东妮娜/场间休憩: -3 bg_static(体育馆) -> -2 fx_back(冰块+水瓶) -> -1 bg_mid(Image_09 冰桶外壳) | +1 fx_front(桶外水滴+触发)
    "3901_Antonina_S2": {
        "sandwich_bg_mid_min_ord": 2,
    },
    # 迦瓦娜/闲暇的驯兽师: -3 bg_static(舞台+观众+地毯) -> -2 fx_back(含qizhi01..04彩旗) -> -1 bg_mid(Image_18左右红幕布+Image_21右木柱)
    "1601_Gawana_S2": {
        "sandwich_bg_mid_names": frozenset({"Image_18", "Image_21"}),
    },
    # 芙丽希娅/甜蜜游乐园: -3 bg_static -> -2 bj_03 -> -1 bg_mid | +1 bj_01(左前2大木马, UI X<=+2 vs MAIN X>=+113 零重叠)
    "401_Freesia_S4": {
        "promote_back_bj_to_pos": ("souldress_freesia_04_bj_01.skel.bytes",),
    },
    # 星见亚砂/星语心恋: 跳过 Bottom/Image_00 与 Image_00_Anim(90s星轨), -3 预留给 fx_asuna_s8_back(底空+旋转星轨+流星) -> -2 bg_static(黑铁窗框) -> -1 bj_05(抱枕)
    "603_Asuna_S8": {
        "skip_img_path_substrs": ("/Bottom/Image_00",),
        "reserve_neg_slot": -3,
    },
    # 阿卡赛特/黏人心机: 跳过 Mask/Anim1 & Anim2(云层), -3 bg_static(房间+天空) -> -2 预留给 fx_akaset_s5_back(云层) -> -1 bg_mid(Image_04窗框+07+08)
    "202_Akaset_S5": {
        "skip_img_path_substrs": ("/Mask/Anim1/", "/Mask/Anim2/"),
        "sandwich_bg_mid_names": frozenset({"Image_04", "Image_07", "Image_08"}),
    },
}

_ETC2_CLEANER_FUNCS: tuple[Any, Any] | None = None


def _get_etc2_cleaner():
    global _ETC2_CLEANER_FUNCS
    if _ETC2_CLEANER_FUNCS is None:
        cleaner_dir = r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本"
        if cleaner_dir not in sys.path:
            sys.path.insert(0, cleaner_dir)
        from spine_etc2_clean_v3 import clean_etc2_spine_pma_v3, detect_pma_etc2_atlas
        _ETC2_CLEANER_FUNCS = (detect_pma_etc2_atlas, clean_etc2_spine_pma_v3)
    return _ETC2_CLEANER_FUNCS


def _save_lossless_pma_webp(im: Image.Image, dest_path: Path, clean_etc2: bool = False) -> None:
    """Save RGBA image as bit-exact lossless WebP (lossless=True, exact=True) with strict PMA (RGB <= A, A==0 -> RGB=0).
    Never uses lossy VP8 encoding on PMA Spine atlases (eliminates 4x4 bright mosaic corruption!).
    """
    arr = np.asarray(im.convert("RGBA"), dtype=np.uint8).copy()
    if clean_etc2:
        detect_fn, clean_fn = _get_etc2_cleaner()
        det = detect_fn(arr)
        if det.get("needs_clean"):
            arr, _ = clean_fn(arr)
    # Enforce strict PMA invariant
    a = arr[:, :, 3]
    arr[:, :, :3] = np.minimum(arr[:, :, :3], a[:, :, None])
    arr[a == 0, :3] = 0
    tmp_path = dest_path.with_suffix(".tmp.webp")
    Image.fromarray(arr, "RGBA").save(tmp_path, "WEBP", lossless=True, exact=True, quality=100, method=6)
    rt = np.asarray(Image.open(tmp_path).convert("RGBA"), dtype=np.uint8)
    if not np.array_equal(arr, rt):
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Lossless WebP exact=True round-trip mismatch on {dest_path}")
    os.replace(tmp_path, dest_path)


# ---------------------------------------------------------------------------
# Spine 3.8.79 Binary Parser & In-Place Root/Slot Patcher
# ---------------------------------------------------------------------------

class _BinReader:
    def __init__(self, data: bytes) -> None:
        self.b = data
        self.p = 0

    def u8(self) -> int:
        v = self.b[self.p]
        self.p += 1
        return v

    def bool(self) -> bool:
        return self.u8() != 0

    def f32(self) -> float:
        v = struct.unpack_from(">f", self.b, self.p)[0]
        self.p += 4
        return v

    def varint(self, opt: bool = True) -> int:
        res = 0
        shift = 0
        while True:
            b = self.b[self.p]
            self.p += 1
            res |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return res if opt else ((res >> 1) ^ -(res & 1))

    def str(self) -> str | None:
        ln = self.varint(True)
        if ln == 0:
            return None
        ln -= 1
        s = self.b[self.p : self.p + ln].decode("utf-8", "replace")
        self.p += ln
        return s

    def skip(self, n: int) -> None:
        self.p += n


def _skip_vertices(r: _BinReader, vc: int) -> None:
    if not r.bool():
        r.skip(vc * 8)
        return
    for _ in range(vc):
        bc = r.varint(True)
        for _ in range(bc):
            r.varint(True)
            r.skip(12)


def _skip_skin(r: _BinReader, noness: bool, default_skin: bool) -> None:
    if default_skin:
        sc = r.varint(True)
        if sc == 0:
            return
    else:
        r.varint(True)
        for _ in range(r.varint(True)):
            r.varint(True)
        for _ in range(r.varint(True)):
            r.varint(True)
        for _ in range(r.varint(True)):
            r.varint(True)
        for _ in range(r.varint(True)):
            r.varint(True)
        sc = r.varint(True)
    for _ in range(sc):
        r.varint(True)
        for _ in range(r.varint(True)):
            r.varint(True)
            r.varint(True)
            atype = r.u8()
            if atype == 0:
                r.varint(True)
                r.skip(32)
            elif atype == 1:
                vc = r.varint(True)
                _skip_vertices(r, vc)
                if noness:
                    r.skip(4)
            elif atype == 2:
                r.varint(True)
                r.skip(4)
                vc = r.varint(True)
                r.skip(vc * 8)
                tc = r.varint(True)
                r.skip(tc * 2)
                _skip_vertices(r, vc)
                r.varint(True)
                if noness:
                    ec = r.varint(True)
                    r.skip(ec * 2)
                    r.skip(8)
            elif atype == 3:
                r.varint(True)
                r.skip(4)
                r.varint(True)
                r.varint(True)
                r.skip(1)
                if noness:
                    r.skip(8)
            elif atype == 4:
                r.skip(2)
                vc = r.varint(True)
                _skip_vertices(r, vc)
                r.skip((vc // 3) * 4)
                if noness:
                    r.skip(4)
            elif atype == 5:
                r.skip(12)
                if noness:
                    r.skip(4)
            elif atype == 6:
                r.varint(True)
                vc = r.varint(True)
                _skip_vertices(r, vc)
                if noness:
                    r.skip(4)


def _skip_curve(r: _BinReader) -> None:
    if r.u8() == 2:
        r.skip(16)


def parse_spine38_binary(raw: bytes) -> dict[str, Any]:
    """Parse Spine 3.8.79 binary skeleton: header, bounds, bones, slots, animations."""
    r = _BinReader(raw)
    _ = r.str()
    ver = r.str() or ""
    bx, by, bw, bh = struct.unpack_from(">4f", r.b, r.p)
    r.skip(16)
    noness = r.bool()
    if noness:
        r.f32()
        r.str()
        r.str()
    strs = [None] + [r.str() for _ in range(r.varint(True))]

    bones: list[dict[str, Any]] = []
    root_xy_offset: int | None = None
    n_bones = r.varint(True)
    for i in range(n_bones):
        nm = r.str() or ""
        par = r.varint(True) if i > 0 else -1
        rot = r.f32()
        if i == 0:
            root_xy_offset = r.p
        x = r.f32()
        y = r.f32()
        sx = r.f32()
        sy = r.f32()
        shx = r.f32()
        shy = r.f32()
        _len = r.f32()
        tmode = r.varint(True)
        _skin_req = r.bool()
        if noness:
            r.skip(4)
        bones.append({
            "name": nm,
            "parent": par,
            "rot": rot,
            "x": x,
            "y": y,
            "sx": sx,
            "sy": sy,
            "tmode": tmode,
        })

    slots: list[dict[str, Any]] = []
    for _ in range(r.varint(True)):
        sn = r.str() or ""
        bi = r.varint(True)
        r.skip(8)
        att_pos = r.p
        att_idx = r.varint(True)
        att_name = strs[att_idx] if att_idx < len(strs) else None
        _blend = r.varint(True)
        slots.append({"name": sn, "bone": bi, "att_pos": att_pos, "att_idx": att_idx, "attachment": att_name})

    for _ in range(r.varint(True)):  # IK
        r.str()
        r.varint(True)
        r.bool()
        for _ in range(r.varint(True)):
            r.varint(True)
        r.varint(True)
        r.skip(12)
    for _ in range(r.varint(True)):  # Transform
        r.str()
        r.varint(True)
        r.bool()
        for _ in range(r.varint(True)):
            r.varint(True)
        r.varint(True)
        r.skip(42)
    for _ in range(r.varint(True)):  # Path
        r.str()
        r.varint(True)
        r.bool()
        for _ in range(r.varint(True)):
            r.varint(True)
        r.varint(True)
        r.varint(True)
        r.varint(True)
        r.varint(True)
        r.skip(20)

    _skip_skin(r, noness, True)
    for _ in range(r.varint(True)):
        _skip_skin(r, noness, False)
    for _ in range(r.varint(True)):  # Events
        r.str()
        r.varint(False)
        r.f32()
        r.str()
        r.str()
        r.str()

    anims: list[str] = []
    anim_bone_t0: dict[str, dict[int, dict[str, Any]]] = {}
    n_anims = r.varint(True)
    for ai in range(n_anims):
        aname = r.str() or f"anim_{ai}"
        anims.append(aname)
        b_t0: dict[int, dict[str, Any]] = {}
        # Slot timelines
        for _ in range(r.varint(True)):
            r.varint(True)
            for _ in range(r.varint(True)):
                tt = r.u8()
                fc = r.varint(True)
                if tt == 0:
                    for _ in range(fc):
                        r.f32()
                        r.varint(True)
                else:
                    nf = 8 if tt == 1 else 12
                    for fi in range(fc):
                        r.skip(nf)
                        if fi < fc - 1:
                            _skip_curve(r)
        # Bone timelines (capture t=0 pose for idle hitbox calculation)
        for _ in range(r.varint(True)):
            bidx = r.varint(True)
            rec: dict[str, Any] = {}
            for _ in range(r.varint(True)):
                tt = r.u8()
                fc = r.varint(True)
                for fi in range(fc):
                    t_val = r.f32()
                    if tt == 0:
                        v0 = r.f32()
                        if fi == 0 and t_val <= 0.05:
                            rec["rot"] = v0
                    else:
                        v0, v1 = r.f32(), r.f32()
                        if fi == 0 and t_val <= 0.05:
                            if tt == 1:
                                rec["trans"] = (v0, v1)
                            elif tt == 2:
                                rec["scale"] = (v0, v1)
                    if fi < fc - 1:
                        _skip_curve(r)
            if rec:
                b_t0[bidx] = rec
        anim_bone_t0[aname] = b_t0

        if ai < n_anims - 1:
            for _ in range(r.varint(True)):  # IK
                r.varint(True)
                fc = r.varint(True)
                for fi in range(fc):
                    r.skip(14)
                    if fi < fc - 1:
                        _skip_curve(r)
            for _ in range(r.varint(True)):  # Transform
                r.varint(True)
                fc = r.varint(True)
                for fi in range(fc):
                    r.skip(20)
                    if fi < fc - 1:
                        _skip_curve(r)
            for _ in range(r.varint(True)):  # Path
                r.varint(True)
                for _ in range(r.varint(True)):
                    tt = r.u8()
                    fc = r.varint(True)
                    nf = 12 if tt == 2 else 8
                    for fi in range(fc):
                        r.skip(nf)
                        if fi < fc - 1:
                            _skip_curve(r)
            for _ in range(r.varint(True)):  # Deform
                r.varint(True)
                for _ in range(r.varint(True)):
                    r.varint(True)
                    for _ in range(r.varint(True)):
                        r.varint(True)
                        fc = r.varint(True)
                        for fi in range(fc):
                            r.f32()
                            end = r.varint(True)
                            if end > 0:
                                r.varint(True)
                                r.skip(end * 4)
                            if fi < fc - 1:
                                _skip_curve(r)
            for _ in range(r.varint(True)):  # DrawOrder
                r.f32()
                for _ in range(r.varint(True)):
                    r.varint(True)
                    r.varint(True)
            for _ in range(r.varint(True)):  # Event
                r.f32()
                r.varint(True)
                r.varint(False)
                r.f32()
                if r.bool():
                    r.str()

    return {
        "version": ver,
        "bounds": (bx, by, bw, bh),
        "bones": bones,
        "slots": slots,
        "anims": anims,
        "anim_bone_t0": anim_bone_t0,
        "root_xy_offset": root_xy_offset,
    }


def strip_embedded_bg_slots_binary(raw: bytes, parsed: dict[str, Any]) -> bytes:
    """Clear non-null default attachments on any embedded bj/beijing/harmonious/cloud slots."""
    buf = bytearray(raw)
    # Note: varint(0) is 1 byte (0x00). Only patch if att_idx is 1..127 (1-byte varint) for safe in-place clearing
    for sl in parsed["slots"]:
        if sl["attachment"] and STRIP_SLOT_RE.search(sl["name"]):
            if 0 < sl["att_idx"] < 128:
                buf[sl["att_pos"]] = 0
    return bytes(buf)


def shift_binary_root_xy(raw: bytes, parsed: dict[str, Any], dx: float, dy: float) -> bytes:
    """Shift Spine 3.8.79 binary root bone (index 0) (x, y) in-place."""
    return patch_binary_root_transform(raw, parsed, dx=dx, dy=dy)


def patch_binary_root_transform(
    raw: bytes,
    parsed: dict[str, Any],
    dx: float = 0.0,
    dy: float = 0.0,
    mul_sx: float = 1.0,
    mul_sy: float = 1.0,
    add_rot: float = 0.0,
) -> bytes:
    """Patch Spine 3.8.79 binary root bone (index 0) (rot, x, y, scaleX, scaleY) in-place."""
    off = parsed.get("root_xy_offset")
    if off is None or off < 4 or not parsed["bones"]:
        return raw
    b0 = parsed["bones"][0]
    rad = math.radians(add_rot)
    ca, sa = math.cos(rad), math.sin(rad)
    bx0, by0 = float(b0["x"]) * float(mul_sx), float(b0["y"]) * float(mul_sy)
    rx0 = ca * bx0 - sa * by0
    ry0 = sa * bx0 + ca * by0
    new_rot = float(b0["rot"]) + float(add_rot)
    new_x = rx0 + float(dx)
    new_y = ry0 + float(dy)
    new_sx = float(b0["sx"]) * float(mul_sx)
    new_sy = float(b0["sy"]) * float(mul_sy)
    buf = bytearray(raw)
    struct.pack_into(">5f", buf, off - 4, new_rot, new_x, new_y, new_sx, new_sy)
    return bytes(buf)


def eval_bone_world_positions(parsed: dict[str, Any], anim_name: str) -> dict[str, tuple[float, float]]:
    """Evaluate exact Spine 3.8 bone world positions (respecting noRotationOrReflection)."""
    b_t0 = parsed["anim_bone_t0"].get(anim_name, {})
    mats: list[tuple[float, float, float, float, float, float]] = []
    out: dict[str, tuple[float, float]] = {}
    for idx, b in enumerate(parsed["bones"]):
        lx, ly, lrot, lsx, lsy = b["x"], b["y"], b["rot"], b["sx"], b["sy"]
        if idx in b_t0:
            rec = b_t0[idx]
            if "trans" in rec:
                lx += rec["trans"][0]
                ly += rec["trans"][1]
            if "rot" in rec:
                lrot += rec["rot"]
            if "scale" in rec:
                lsx *= rec["scale"][0]
                lsy *= rec["scale"][1]
        rad = math.radians(lrot)
        ca, sa = math.cos(rad), math.sin(rad)
        la, lb, lc, ld = ca * lsx, -sa * lsy, sa * lsx, ca * lsy
        par = b["parent"]
        if 0 <= par < len(mats):
            pa, pb, px, pc, pd, py = mats[par]
            wx = pa * lx + pb * ly + px
            wy = pc * lx + pd * ly + py
            if b["tmode"] == 2:  # noRotationOrReflection
                s = math.hypot(pa, pc)
                mats.append((la * s, lb * s, wx, lc * s, ld * s, wy))
            else:
                mats.append((pa * la + pb * lc, pa * lb + pb * ld, wx, pc * la + pd * lc, pc * lb + pd * ld, wy))
        else:
            wx, wy = lx, ly
            mats.append((la, lb, wx, lc, ld, wy))
        out[b["name"]] = (wx, wy)
    return out


# ---------------------------------------------------------------------------
# Bundle Indexing (Spine, DressBackground Sprites, CV, BGM, Backup Configs)
# ---------------------------------------------------------------------------

class BatchAssetRepos:
    """Lazy-cached index of all Spine, BG Sprite, CV, BGM, and Backup config assets."""

    def __init__(self, indexer: AssetIndexer, workers: int | None = None, max_cached_abs: int = 8) -> None:
        self.indexer = indexer
        self.workers = max(1, workers or min(4, os.cpu_count() or 4))
        self.max_cached_abs = max(4, int(max_cached_abs))
        self._ab_lru: OrderedDict[Path, Any] = OrderedDict()
        self._lru_lock = threading.RLock()
        self.spine_ab_paths: dict[str, Path] = {}
        self.spine_units_by_cpath: dict[str, tuple[str, str]] = {}  # lower cpath -> (ab_name, exact_cpath)
        self.spine_units_by_stem: dict[str, list[tuple[str, str]]] = defaultdict(list)

        if getattr(indexer, "dress_spine_units", None):
            print(f"[BatchRepos] Reusing {len(indexer.dress_spine_units)} dressspine/*.ab index from AssetIndexer...", flush=True)
            for ab_name, (ab_path, cpaths) in indexer.dress_spine_units.items():
                self.spine_ab_paths[ab_name] = ab_path
                for cpath in cpaths:
                    low = cpath.lower()
                    self.spine_units_by_cpath[low] = (ab_name, cpath)
                    stem = Path(cpath).name[:-len(".skel.bytes")].lower()
                    self.spine_units_by_stem[stem].append((ab_name, cpath))
        else:
            dress_abs = sorted((CDN_ROOT / "23_spine/dressspine").glob("*.ab"))
            print(f"[BatchRepos] Indexing lightweight locators for {len(dress_abs)} dressspine/*.ab...", flush=True)
            for ab_path in dress_abs:
                env = load_ab(ab_path)
                self.spine_ab_paths[ab_path.name] = ab_path
                for cpath in (env.container or {}).keys():
                    if cpath.lower().endswith(".skel.bytes"):
                        low = cpath.lower()
                        self.spine_units_by_cpath[low] = (ab_path.name, cpath)
                        stem = Path(cpath).name[:-len(".skel.bytes")].lower()
                        self.spine_units_by_stem[stem].append((ab_path.name, cpath))
                del env
            gc.collect()

        sprite_abs = [
            ab
            for sub_dir in ("05_images/image_resources/dress_bg", "05_images/image_resources/soulresources")
            if (CDN_ROOT / sub_dir).exists()
            for ab in sorted((CDN_ROOT / sub_dir).rglob("*.ab"))
        ]
        print(f"[BatchRepos] Indexing lightweight locators for {len(sprite_abs)} sprite ABs...", flush=True)
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

        cv_abs = sorted((CDN_ROOT / "06_sounds/cv").rglob("*.ab"))
        bgm_abs = sorted((CDN_ROOT / "06_sounds/bgm").rglob("*.ab"))
        print(f"[BatchRepos] Indexing lightweight locators for {len(cv_abs)} CV & {len(bgm_abs)} BGM ABs...", flush=True)
        self.cv_loc: dict[str, tuple[str, Path, int]] = {}
        self.bgm_loc: dict[str, tuple[str, Path, int]] = {}
        for i, ab_path in enumerate(cv_abs, 1):
            env = load_ab(ab_path)
            for obj in env.objects:
                if obj.type.name == "AudioClip":
                    nm = obj.peek_name()
                    if nm:
                        self.cv_loc[nm.lower()] = (nm, ab_path, obj.path_id)
            del env
            if i % 16 == 0:
                gc.collect()
        for i, ab_path in enumerate(bgm_abs, 1):
            env = load_ab(ab_path)
            for obj in env.objects:
                if obj.type.name == "AudioClip":
                    nm = obj.peek_name()
                    if nm:
                        self.bgm_loc[nm.lower()] = (nm, ab_path, obj.path_id)
            del env
            if i % 16 == 0:
                gc.collect()
        gc.collect()

        print("[BatchRepos] Indexing backup spine configs...", flush=True)
        self.bkp_by_pair: dict[tuple[str, str], Path] = {}
        self.bkp_by_skel: dict[str, Path] = {}
        alias_char = {
            "傲慢": "斯贝比尔",
            "安东尼娜": "安东妮娜",
            "安东": "安东妮娜",
            "艾尼斯": "艾妮斯",
            "贞德": "贞德·卢瓦尔",
            "露比": "露比·罗斯",
            "艾瑞妮": "爱瑞妮",
            "莎缇娅": "萨缇娅",
            "菲菲": "菲洛多希",
            "亚砂": "星见亚砂",
            "南宫": "南宫凛",
        }
        alias_dress = {
            "公主": "完美公主",
            "泳装": "明媚之约",
            "玉龙娇娇纳福来": "玉龙娇娇邀福来",
        }
        for p in sorted(BACKUP_SPINE_ROOT.rglob(".config.json")):
            rel = p.parent.relative_to(BACKUP_SPINE_ROOT)
            if len(rel.parts) < 2:
                continue
            ch_nm = alias_char.get(rel.parts[0], rel.parts[0])
            dr_nm = alias_dress.get(rel.parts[1], rel.parts[1])
            try:
                d = json.loads(p.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            has_ha = bool(d.get("hit_areas"))
            prev = self.bkp_by_pair.get((ch_nm, dr_nm))
            if prev is None:
                self.bkp_by_pair[(ch_nm, dr_nm)] = p
            elif has_ha:
                try:
                    prev_ha = bool(json.loads(prev.read_text(encoding="utf-8")).get("hit_areas"))
                except Exception:
                    prev_ha = False
                if not prev_ha:
                    self.bkp_by_pair[(ch_nm, dr_nm)] = p
            sk = Path(d.get("skeleton", "")).stem.lower().replace(".skel", "")
            if sk and has_ha:
                self.bkp_by_skel.setdefault(sk, p)

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

    def get_cv_samples(self, low_stem: str) -> tuple[str, bytes] | None:
        loc = self.cv_loc.get(low_stem)
        if loc is None:
            return None
        cname, ab_path, obj_pid = loc
        with self._lru_lock:
            env = self._get_ab_env_lru(ab_path)
            for obj in env.objects:
                if obj.path_id == obj_pid and obj.type.name == "AudioClip":
                    samples = obj.read().samples
                    if samples:
                        _, wb = next(iter(samples.items()))
                        return cname, bytes(wb)
        return None

    def get_bgm_samples(self, low_stem: str) -> tuple[str, bytes] | None:
        loc = self.bgm_loc.get(low_stem)
        if loc is None:
            return None
        cname, ab_path, obj_pid = loc
        with self._lru_lock:
            env = self._get_ab_env_lru(ab_path)
            for obj in env.objects:
                if obj.path_id == obj_pid and obj.type.name == "AudioClip":
                    samples = obj.read().samples
                    if samples:
                        _, wb = next(iter(samples.items()))
                        return cname, bytes(wb)
        return None


def _read_sprite_rgba_untrimmed(sp_obj) -> Image.Image:
    """Read Unity Sprite as RGBA restored to its full m_Rect canvas using m_RD.textureRectOffset.

    UnityPy's `Sprite.image` returns the tight-packed `m_RD.textureRect` without transparent
    outer padding, which otherwise stretches corner/trimmed sprites (e.g. AmaneInori_S2 Image_4,
    RubyRose_S2 Image_02, NicoletteLamel_S2 Image_04) to fill the entire RectTransform.
    """
    im = sp_obj.read().image.convert("RGBA")
    try:
        tt = sp_obj.read_typetree()
        m_rect = tt.get("m_Rect") or {}
        mw = float(m_rect.get("width", 0.0))
        mh = float(m_rect.get("height", 0.0))
        if mw > 1.0 and mh > 1.0 and (abs(mw - im.width) > 2.0 or abs(mh - im.height) > 2.0):
            rd = tt.get("m_RD") or {}
            tr = rd.get("textureRect") or {}
            off = rd.get("textureRectOffset") or {}
            tr_w = float(tr.get("width", 0.0))
            tr_h = float(tr.get("height", 0.0))
            ox = float(off.get("x", 0.0))
            oy = float(off.get("y", 0.0))
            if tr_w > 1.0 and tr_h > 1.0 and tr_w <= mw + 2.0 and tr_h <= mh + 2.0:
                sx = im.width / tr_w
                sy = im.height / tr_h
                full_w = max(im.width, int(round(mw * sx)))
                full_h = max(im.height, int(round(mh * sy)))
                px = int(round(ox * sx))
                # Unity Sprite Y is bottom-up; PIL Y is top-down
                py = int(round((mh - oy - tr_h) * sy))
                if 0 <= px <= full_w - im.width + 2 and 0 <= py <= full_h - im.height + 2:
                    px = min(px, full_w - im.width)
                    py = min(py, full_h - im.height)
                    full = Image.new("RGBA", (full_w, full_h), (0, 0, 0, 0))
                    full.paste(im, (px, py))
                    im.close()
                    return full
    except Exception:
        pass
    return im


def _extract_spine_unit_from_ab(
    env,
    skel_cpath: str,
    dest_dir: Path,
    strip_bg: bool = False,
    root_shift: tuple[float, float] = (0.0, 0.0),
    root_scale: tuple[float, float] = (1.0, 1.0),
    root_rot: float = 0.0,
    asset_lock: threading.RLock | None = None,
    save_webp: bool = True,
    clean_etc2: bool = True,
) -> dict[str, Any]:
    """Extract .skel.bytes (saved as .skel.json), .atlas.txt, and .png pages from AB."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    unit_dir = str(Path(skel_cpath).parent).replace("\\", "/").lower() + "/"
    unit_stem = Path(skel_cpath).name[:-len(".skel.bytes")].lower()

    atlas_name = ""
    atlas_txt = ""
    atlas_pages: list[tuple[str, tuple[int, int] | None]] = []
    img_map: dict[str, Image.Image] = {}
    tex_files: list[str] = []
    tex_names: list[str] = []
    skel_raw = b""

    cont_items = sorted((env.container or {}).items(), key=lambda kv: kv[0])
    skels_in_dir = [
        cp for cp, _ in cont_items
        if cp.lower().startswith(unit_dir) and cp.lower().endswith(".skel.bytes")
    ]
    strict_stem = len(skels_in_dir) > 1

    def _matches(cp: str) -> bool:
        low = cp.lower()
        if strict_stem and (low.endswith(".skel.bytes") or low.endswith(".atlas.txt")):
            return low == skel_cpath.lower() or Path(low).name.startswith(unit_stem + ".")
        return low.startswith(unit_dir) or Path(low).name.startswith(unit_stem + ".")

    with (asset_lock if asset_lock is not None else nullcontext()):
        for cpath, ptr in cont_items:
            low = cpath.lower()
            if not _matches(cpath):
                continue
            if low.endswith(".atlas.txt"):
                txt = ptr.read().m_Script
                first_line = next((ln.strip() for ln in txt.splitlines() if ln.strip()), "")
                canon_stem = Path(first_line).stem if first_line else Path(cpath).name[:-10]
                atlas_name = f"{canon_stem}.atlas.txt"
                atlas_txt = txt
                atlas_pages.clear()
                lines = txt.splitlines()
                for li, ln in enumerate(lines):
                    s = ln.strip()
                    if s.lower().endswith(".png"):
                        psz = None
                        if li + 1 < len(lines) and lines[li + 1].strip().startswith("size:"):
                            try:
                                pw, ph = [int(v.strip()) for v in lines[li + 1].strip()[5:].split(",")]
                                psz = (pw, ph)
                            except Exception:
                                psz = None
                        atlas_pages.append((s, psz))
            elif low.endswith(".png"):
                im = ptr.read().image.convert("RGBA")
                img_map[Path(cpath).name.lower()] = im
            elif low.endswith(".skel.bytes"):
                skel_raw = ptr.read().m_Script.encode("utf-8", "surrogateescape")

    if not skel_raw or not atlas_name or not img_map:
        raise FileNotFoundError(f"Incomplete Spine unit for {skel_cpath} (skel={len(skel_raw)}, atlas={atlas_name}, imgs={len(img_map)})")

    out_atlas_txt = atlas_txt
    for page, psz in atlas_pages:
        im = img_map.get(page.lower()) or next(iter(img_map.values()))
        if psz is not None and im.size != psz:
            im = im.resize(psz, Image.Resampling.LANCZOS)
        if save_webp:
            wp_name = f"{Path(page).stem}.webp"
            _save_lossless_pma_webp(im, dest_dir / wp_name, clean_etc2=clean_etc2)
            out_atlas_txt = out_atlas_txt.replace(page, wp_name)
            tex_files.append(wp_name)
        else:
            im.save(dest_dir / page, "PNG")
            tex_files.append(page)
        tex_names.append(Path(page).stem)
    (dest_dir / atlas_name).write_text(out_atlas_txt, encoding="utf-8")

    parsed = parse_spine38_binary(skel_raw)
    if strip_bg:
        skel_raw = strip_embedded_bg_slots_binary(skel_raw, parsed)
    if (
        abs(root_shift[0]) > 1e-3
        or abs(root_shift[1]) > 1e-3
        or abs(root_scale[0] - 1.0) > 1e-4
        or abs(root_scale[1] - 1.0) > 1e-4
        or abs(root_rot) > 1e-2
    ):
        skel_raw = patch_binary_root_transform(
            skel_raw,
            parsed,
            dx=root_shift[0],
            dy=root_shift[1],
            mul_sx=root_scale[0],
            mul_sy=root_scale[1],
            add_rot=root_rot,
        )

    base_stem = tex_names[0] if tex_names else Path(atlas_name).name[:-10]
    skel_name = f"{base_stem}.skel.json"
    (dest_dir / skel_name).write_bytes(skel_raw)

    return {
        "skeleton": skel_name,
        "atlas": atlas_name,
        "tex_names": tex_names,
        "textures": tex_files,
        "tex_type": 1 if save_webp else 0,
        "parsed": parsed,
    }


def _find_main_skel_unit(repos: BatchAssetRepos, indexer: AssetIndexer, skin: dict[str, Any]) -> tuple[str, str]:
    """Find (ab_name, skel_cpath) for the skin's main character Spine (SoulAction entity first, then BgPrefab)."""
    bgp = skin["bg_prefab"]
    ent_res = resolve_soul_action_entity(indexer, skin)
    search_roots = []
    if ent_res is not None:
        search_roots.append(ent_res)
    search_roots.append(resolve_bg_prefab_root(indexer, skin))

    found: list[tuple[str, str]] = []

    for objs, gid in search_roots:
        def walk(g: int, in_harm: bool):
            go = objs[g].read()
            low = go.m_Name.lower()
            if in_harm or "harmonious" in low:
                return
            rt = None
            for c in go.m_Component:
                co = objs.get(c.component.path_id)
                if not co:
                    continue
                if co.type.name in ("RectTransform", "Transform"):
                    rt = co.read()
                elif co.type.name == "MonoBehaviour" and "person" in low and not _is_censor_cloud(low) and not any(t in low for t in ("_bg_", "_bj_")):
                    try:
                        tt = co.read_typetree()
                        if "skeletonDataAsset" in tt:
                            sref = tt["skeletonDataAsset"]
                            sda = indexer.resolve_sda(co.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
                            if sda and sda["skel_cpath"] and not any(t in sda["skel_cpath"].lower() for t in ("_bg_", "_bj_")):
                                found.append((sda["ab_name"], sda["skel_cpath"]))
                    except Exception:
                        pass
            if rt and hasattr(rt, "m_Children"):
                for ch in rt.m_Children:
                    if ch.path_id in objs:
                        walk(objs[ch.path_id].read().m_GameObject.path_id, False)

        walk(gid, False)
        if found:
            return found[0]

    # Fallback via art_prefabs.ab souldress_<char>.prefab or bg_slug directory in dressspine
    slug = skin["bg_slug"].lower()
    for low_cp, pair in repos.spine_units_by_cpath.items():
        if f"/{slug}/" in low_cp or f"souldress_{slug}/" in low_cp:
            if not any(t in low_cp for t in ("_bj_", "_bg_", "_tree", "_robort", "_butterfly", "_grass")):
                return pair
    # Normalize e.g. Asuna_S9 -> souldress_asuna_09
    m = re.match(r"^([a-z0-9]+)_s(\d+)$", slug)
    if m:
        ch_part, num_part = m.group(1), int(m.group(2))
        cand_stem = f"souldress_{ch_part}_{num_part:02d}"
        if cand_stem in repos.spine_units_by_stem:
            return repos.spine_units_by_stem[cand_stem][0]
    raise FileNotFoundError(f"Cannot locate main Spine skeleton for {skin['skin_key']} ({bgp})")


def _render_nine_slice(
    im: Image.Image,
    tw: int,
    th: int,
    border: tuple[float, float, float, float],
    scale_x: float,
    scale_y: float,
) -> Image.Image:
    """Exact Unity UGUI Image.Type.Sliced (9-slice) renderer. border=(L, B, R, T) in Sprite pixels."""
    sw, sh = im.size
    bl, bb, br, bt = border
    if max(bl, bb, br, bt) <= 0.5:
        return im.resize((tw, th), Image.Resampling.LANCZOS)
    sL = max(0, min(sw, int(round(bl))))
    sR = max(0, min(sw - sL, int(round(br))))
    sT = max(0, min(sh, int(round(bt))))
    sB = max(0, min(sh - sT, int(round(bb))))

    dL = bl * abs(scale_x)
    dR = br * abs(scale_x)
    dT = bt * abs(scale_y)
    dB = bb * abs(scale_y)
    if dL + dR > tw and (dL + dR) > 0:
        f = tw / (dL + dR)
        dL *= f
        dR *= f
    if dT + dB > th and (dT + dB) > 0:
        f = th / (dT + dB)
        dT *= f
        dB *= f
    iL, iR = int(round(dL)), int(round(dR))
    iT, iB = int(round(dT)), int(round(dB))

    xs_src = [(0, sL), (sL, sw - sR), (sw - sR, sw)]
    xs_dst = [(0, iL), (iL, tw - iR), (tw - iR, tw)]
    ys_src = [(0, sT), (sT, sh - sB), (sh - sB, sh)]
    ys_dst = [(0, iT), (iT, th - iB), (th - iB, th)]

    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    for (sx0, sx1), (dx0, dx1) in zip(xs_src, xs_dst):
        if sx1 <= sx0 or dx1 <= dx0:
            continue
        for (sy0, sy1), (dy0, dy1) in zip(ys_src, ys_dst):
            if sy1 <= sy0 or dy1 <= dy0:
                continue
            patch = im.crop((sx0, sy0, sx1, sy1))
            dw, dh = dx1 - dx0, dy1 - dy0
            if patch.size != (dw, dh):
                patch = patch.resize((dw, dh), Image.Resampling.LANCZOS)
            out.paste(patch, (dx0, dy0))
    return out


def _render_static_image_group(
    img_layers: list[dict[str, Any]],
    skin: dict[str, Any],
    layout: dict[str, Any],
    base_scale: float,
    out_sub_dir: Path,
    sub_folder_name: str,
    counter_rot_deg: float = 0.0,
) -> dict[str, Any] | None:
    """Composite a subset of Unity UI Images with Mask clipping & alpha auto-trim into a Spine 3.8 submodel."""
    if not img_layers:
        return None

    cw, ch = layout["canvas_w"], layout["canvas_h"]
    cam_x, cam_y = layout["cam_x"], layout["cam_y"]
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

        # Clip to canvas AND optional Unity Mask / RectMask2D clip rect
        clip_x0, clip_y0, clip_x1, clip_y1 = 0, 0, cw, ch
        if lay.get("clip_rect") is not None:
            mx0, my0, mx1, my1 = lay["clip_rect"]
            # Convert world clip rect to canvas pixel coordinates (Y inverted)
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

    # Clamp parallax overhang beyond active Unity Limit letterbox viewport (e.g. Dreizehn_S3 +321px right sky overhang)
    lim = layout.get("limit_rect") or {}
    crop_x0, crop_y0, crop_x1, crop_y1 = 0, 0, cw, ch
    if abs(counter_rot_deg) <= 0.25:
        if "x0" in lim and "x1" in lim:
            lx0, lx1 = float(lim["x0"]), float(lim["x1"])
            lim_w = lx1 - lx0
            if 1600.0 <= lim_w <= 2200.0 and ((cam_x + cw / 2.0) - lx1 > 30.0 or lx0 - (cam_x - cw / 2.0) > 30.0):
                crop_x0 = max(0, min(cw, int(round((lx0 - cam_x) + cw / 2.0))))
                crop_x1 = max(crop_x0, min(cw, int(round((lx1 - cam_x) + cw / 2.0))))
        if "y0" in lim and "y1" in lim:
            ly0, ly1 = float(lim["y0"]), float(lim["y1"])
            lim_h = ly1 - ly0
            if 1000.0 <= lim_h <= 1700.0 and ((cam_y + ch / 2.0) - ly1 > 30.0 or ly0 - (cam_y - ch / 2.0) > 30.0):
                crop_y0 = max(0, min(ch, int(round((cam_y - ly1) + ch / 2.0))))
                crop_y1 = max(crop_y0, min(ch, int(round((cam_y - ly0) + ch / 2.0))))

    # Auto-trim pure transparent outer margins (eliminates empty checkerboard strips while keeping exact world coords)
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

    bx0, by0, bx1, by1 = bbox
    bx0 = max(crop_x0, bx0)
    by0 = max(crop_y0, by0)
    bx1 = min(crop_x1, bx1)
    by1 = min(crop_y1, by1)
    tw_out = bx1 - bx0
    th_out = by1 - by0
    if tw_out < 4 or th_out < 4:
        canvas.close()
        return None

    trimmed = canvas.crop((bx0, by0, bx1, by1))
    canvas.close()

    # Live2DViewerEX renders Spine submodels with DefaultPMAShader (Blend One OneMinusSrcAlpha).
    # Convert Pillow Straight-Alpha RGBA composite to strict Premultiplied Alpha so semi-transparent
    # edges and shadows never produce bright halos or glowing patches under PMA blending.
    _arr = np.asarray(trimmed, dtype=np.float32).copy()
    _alpha = _arr[:, :, 3:4] / 255.0
    _arr[:, :, :3] = np.clip(np.round(_arr[:, :, :3] * _alpha), 0, 255)
    _arr[_arr[:, :, 3] == 0, :3] = 0
    trimmed_pma = Image.fromarray(_arr.astype(np.uint8), "RGBA")
    trimmed.close()

    out_sub_dir.mkdir(parents=True, exist_ok=True)
    slug = skin["skin_key"].lower()
    region_name = f"{sub_folder_name}_{slug}" if sub_folder_name != "bg_static" else f"bg_{slug}"
    tex_file = f"{region_name}.webp"
    _save_lossless_pma_webp(trimmed_pma, out_sub_dir / tex_file, clean_etc2=False)
    trimmed_pma.close()

    atlas_txt = (
        f"\n{tex_file}\n"
        f"size: {tw_out},{th_out}\n"
        f"format: RGBA8888\n"
        f"filter: Linear,Linear\n"
        f"repeat: none\n"
        f"{region_name}\n"
        f"  rotate: false\n"
        f"  xy: 0, 0\n"
        f"  size: {tw_out}, {th_out}\n"
        f"  orig: {tw_out}, {th_out}\n"
        f"  offset: 0, 0\n"
        f"  index: -1\n"
    )
    atlas_file = f"{sub_folder_name}.atlas.txt"
    (out_sub_dir / atlas_file).write_text(atlas_txt, encoding="utf-8")

    p = layout["person"]
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
    trim_dx = ((bx0 + bx1) / 2.0) - cw / 2.0
    trim_dy = ch / 2.0 - ((by0 + by1) / 2.0)
    base_dx = cam_x - p["wx"]
    base_dy = cam_y - p["wy"]
    if abs(counter_rot_deg) > 0.25:
        base_dx, base_dy = cos_cr * base_dx - sin_cr * base_dy, sin_cr * base_dx + cos_cr * base_dy

    sx = (base_dx + trim_dx) / p_ux
    sy = (base_dy + trim_dy) / p_uy
    scale_x = 1.0 / p_ux
    scale_y = 1.0 / p_uy
    sw = tw_out * scale_x
    sh = th_out * scale_y

    skel_json = {
        "skeleton": {
            "hash": region_name,
            "spine": "3.8.79",
            "x": round(sx - sw / 2.0, 2),
            "y": round(sy - sh / 2.0, 2),
            "width": round(sw, 2),
            "height": round(sh, 2),
        },
        "bones": [
            {"name": "root"},
            {
                "name": "bg_root",
                "parent": "root",
                "x": round(sx, 4),
                "y": round(sy, 4),
                "scaleX": round(scale_x, 6),
                "scaleY": round(scale_y, 6),
            },
        ],
        "slots": [{"name": "bg_slot", "bone": "bg_root", "attachment": region_name}],
        "skins": [{"name": "default", "attachments": {"bg_slot": {region_name: {"x": 0.0, "y": 0.0, "width": tw_out, "height": th_out}}}}],
        "animations": {"idle": {}},
    }
    skel_file = f"{sub_folder_name}.skel.json"
    write_json(out_sub_dir / skel_file, skel_json)

    sub_id = f"{slug}_{sub_folder_name}"
    cfg = {
        "conf_ver": 1,
        "type": 9,
        "controllers": {"param_hit": {}, "param_loop": {}, "intimacy_system": {}, "slot_opacity": {}, "slot_color": {}},
        "hit_areas": [],
        "motions": {"idle": [{"name": "idle", "file": "idle", "file_loop": True}]},
        "options": {
            "id": sub_id,
            "scale_factor": round(base_scale, 5),
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 1,
            "edge_padding": False,
            "shader_type": 0,
        },
        "skeleton": skel_file,
        "atlases": [{"atlas": atlas_file, "tex_names": [region_name], "textures": [tex_file]}],
    }
    write_json(out_sub_dir / ".config.json", cfg)
    return {
        "id": sub_id,
        "folder": sub_folder_name,
        "rel": f"submodels/{sub_folder_name}/.config.json",
        "area_px": tw_out * th_out,
        "size": (tw_out, th_out),
    }


def _extract_unity_scene_layers(
    repos: BatchAssetRepos,
    indexer: AssetIndexer,
    skin: dict[str, Any],
    layout: dict[str, Any],
    asset_lock: threading.RLock | None = None,
) -> dict[str, Any]:
    """Walk official art_prefabs.ab BgPrefab + SoulAction entity with exact Unity RectTransform,
    Mask, SortedComponentOrder, SpriteRenderer, flip, rotation, Z-depth, and scaleX/Y."""
    lock_ctx = asset_lock if asset_lock is not None else nullcontext()
    objs, gid = resolve_bg_prefab_root(indexer, skin)
    ent_res = resolve_soul_action_entity(indexer, skin)

    img_layers: list[dict[str, Any]] = []
    bj_candidates: list[dict[str, Any]] = []
    fx_nodes_keys: list[tuple[int, float, int]] = []
    person_key: tuple[int, float, int] | None = None
    spine_scale_factor = 1.0
    dfs_seq = 0

    def walk(
        g: int,
        depth: int,
        ppos: tuple[float, float, float],
        pscale: tuple[float, float, float],
        pq: tuple[float, float, float, float],
        parent_rect_size: tuple[float, float],
        parent_pivot: tuple[float, float],
        path: str,
        in_harm: bool,
        cur_sort_order: int,
        clip_rect: tuple[float, float, float, float] | None,
        cur_objs: dict[int, Any] | None = None,
        from_entity: bool = False,
    ):
        nonlocal person_key, spine_scale_factor, dfs_seq
        c_objs = cur_objs if cur_objs is not None else objs
        go = c_objs[g].read()
        if not go.m_IsActive:
            return
        low = go.m_Name.lower()
        if in_harm or "harmonious" in low or "hitarea" in low or "cv_point" in low or _is_censor_cloud(low):
            return

        rt, is_rect, (lx, ly, lz), (sx, sy, sz), lq = _node_local_tf(go, c_objs, ignore_root_pos=(depth == 0))

        rect_w = rect_h = 0.0
        piv_x = piv_y = 0.5
        exact_lx, exact_ly = lx, ly
        center_dx_local = center_dy_local = 0.0
        if is_rect and rt is not None:
            sd = rt.m_SizeDelta
            amin = rt.m_AnchorMin
            amax = rt.m_AnchorMax
            piv = rt.m_Pivot
            ap = rt.m_AnchoredPosition
            piv_x, piv_y = float(piv.x), float(piv.y)
            if depth == 0:
                rect_w, rect_h = float(sd.x), float(sd.y)
                exact_lx, exact_ly = 0.0, 0.0
            else:
                pw, ph = parent_rect_size
                ppiv_x, ppiv_y = parent_pivot
                rect_w = pw * (float(amax.x) - float(amin.x)) + float(sd.x)
                rect_h = ph * (float(amax.y) - float(amin.y)) + float(sd.y)
                anchor_x = (float(amin.x) + (float(amax.x) - float(amin.x)) * piv_x - ppiv_x) * pw
                anchor_y = (float(amin.y) + (float(amax.y) - float(amin.y)) * piv_y - ppiv_y) * ph
                exact_lx = anchor_x + float(ap.x)
                exact_ly = anchor_y + float(ap.y)
            center_dx_local = (0.5 - piv_x) * rect_w
            center_dy_local = (0.5 - piv_y) * rect_h

        rx, ry, rz = _qrot(pq, (exact_lx * pscale[0], exact_ly * pscale[1], lz * pscale[2]))
        wx, wy, wz = ppos[0] + rx, ppos[1] + ry, ppos[2] + rz
        wsx, wsy, wsz = pscale[0] * sx, pscale[1] * sy, pscale[2] * sz
        wq = _qmul(pq, lq)
        z_deg = math.degrees(2.0 * math.atan2(wq[2], wq[3]))
        cdx, cdy, _ = _qrot(wq, (center_dx_local * wsx, center_dy_local * wsy, 0.0))
        img_cx, img_cy = wx + cdx, wy + cdy

        if not from_entity and low == "spine_scale":
            spine_scale_factor = abs(sx)

        canvas_ord: int | None = None
        mono_ord: int | None = None
        node_has_mask = False
        show_mask_graphic = True
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
                        sn = c_objs[tt["m_Script"]["m_PathID"]].peek_name() if tt.get("m_Script", {}).get("m_PathID") in c_objs else ""
                        if "Order" in tt and tt.get("m_Enabled", 1):
                            mono_ord = int(tt["Order"])
                        if sn in ("Mask", "RectMask2D") and tt.get("m_Enabled", 1):
                            node_has_mask = True
                            if sn == "Mask":
                                show_mask_graphic = bool(tt.get("m_ShowMaskGraphic", 1))
                    except Exception:
                        pass
            # Official SoulTide runtime: SortedComponentOrder always overrides Canvas.sortingOrder!
            sort_order = mono_ord if mono_ord is not None else (canvas_ord if canvas_ord is not None else cur_sort_order)
        else:
            # SoulSpineCell.ShowSpineSuccess sets ALL Renderers inside SoulAction entity to Point_Root's Canvas.sortingOrder!
            sort_order = cur_sort_order

        child_clip = clip_rect
        if node_has_mask and is_rect:
            mw = rect_w * abs(wsx)
            mh = rect_h * abs(wsy)
            if mw > 1.0 and mh > 1.0:
                new_clip = (img_cx - mw / 2.0, img_cy - mh / 2.0, img_cx + mw / 2.0, img_cy + mh / 2.0)
                if child_clip is None:
                    child_clip = new_clip
                else:
                    child_clip = (
                        max(child_clip[0], new_clip[0]),
                        max(child_clip[1], new_clip[1]),
                        min(child_clip[2], new_clip[2]),
                        min(child_clip[3], new_clip[3]),
                    )

        for c in go.m_Component:
            co = c_objs.get(c.component.path_id)
            if not co:
                continue
            if co.type.name == "ParticleSystem":
                dfs_seq += 1
                fx_nodes_keys.append((sort_order, -round(wz, 3), dfs_seq))
                continue
            if co.type.name == "SpriteRenderer":
                try:
                    tt = co.read_typetree()
                    if not tt.get("m_Enabled", 1):
                        continue
                    sref = tt.get("m_Sprite", {})
                    fid, pid = sref.get("m_FileID", 0), sref.get("m_PathID", 0)
                    if pid == 0:
                        continue
                    cab = (
                        co.assets_file.name
                        if fid == 0
                        else (Path(co.assets_file.externals[fid - 1].path).name if 1 <= fid <= len(co.assets_file.externals) else "")
                    )
                    if cab in BLACK_LETTERBOX_CABS:
                        continue
                    sp_obj = (co.assets_file.objects.get(pid) if fid == 0 else None) or indexer.obj_by_cab_pid.get((cab, pid))
                    if sp_obj is not None:
                        if sp_obj.type.name != "Sprite":
                            continue
                        pil_img = _read_sprite_rgba_untrimmed(sp_obj)
                        stt = sp_obj.read_typetree()
                        ppu = float(stt.get("m_PixelsToUnits", 100.0) or 100.0)
                        pv = stt.get("m_Pivot") or {"x": 0.5, "y": 0.5}
                        sp_piv_x, sp_piv_y = float(pv.get("x", 0.5)), float(pv.get("y", 0.5))
                    else:
                        sres = repos.get_sprite_image_and_meta(cab, pid)
                        if sres is None:
                            continue
                        pil_img, ppu, sp_piv_x, sp_piv_y = sres[0], sres[1], sres[2], sres[3]
                    sr_sx = -wsx if tt.get("m_FlipX", False) else wsx
                    sr_sy = -wsy if tt.get("m_FlipY", False) else wsy
                    w_px = (pil_img.width / ppu) * abs(sr_sx)
                    h_px = (pil_img.height / ppu) * abs(sr_sy)
                    if w_px <= 1.0 or h_px <= 1.0:
                        continue
                    p_dx_l = (0.5 - sp_piv_x) * (pil_img.width / ppu) * sr_sx
                    p_dy_l = (0.5 - sp_piv_y) * (pil_img.height / ppu) * sr_sy
                    sdx, sdy, _ = _qrot(wq, (p_dx_l, p_dy_l, 0.0))
                    mcol = tt.get("m_Color", {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0})
                    dfs_seq += 1
                    img_layers.append({
                        "name": go.m_Name,
                        "path": f"{path}/{go.m_Name}",
                        "sort_order": sort_order,
                        "dfs": dfs_seq,
                        "draw_key": (sort_order, -round(wz, 3), dfs_seq),
                        "img": pil_img,
                        "wx": wx + sdx,
                        "wy": wy + sdy,
                        "w": w_px,
                        "h": h_px,
                        "sx": sr_sx,
                        "sy": sr_sy,
                        "z_deg": z_deg,
                        "clip_rect": clip_rect,
                        "color": (float(mcol.get("r", 1.0)), float(mcol.get("g", 1.0)), float(mcol.get("b", 1.0)), float(mcol.get("a", 1.0))),
                    })
                except Exception:
                    pass
                continue
            if co.type.name != "MonoBehaviour":
                continue
            try:
                tt = co.read_typetree()
                sn = c_objs[tt["m_Script"]["m_PathID"]].peek_name() if tt.get("m_Script", {}).get("m_PathID") in c_objs else ""
                if "m_Sprite" in tt and low not in SKIP_IMAGE_NAMES and tt.get("m_Enabled", 1):
                    if node_has_mask and not show_mask_graphic:
                        continue
                    sref = tt["m_Sprite"]
                    fid, pid = sref.get("m_FileID", 0), sref.get("m_PathID", 0)
                    if pid == 0:
                        continue
                    cab = (
                        co.assets_file.name
                        if fid == 0
                        else (Path(co.assets_file.externals[fid - 1].path).name if 1 <= fid <= len(co.assets_file.externals) else "")
                    )
                    if cab in BLACK_LETTERBOX_CABS:
                        continue
                    w_px = rect_w * abs(wsx) if is_rect else 0.0
                    h_px = rect_h * abs(wsy) if is_rect else 0.0
                    if w_px <= 1.0 or h_px <= 1.0:
                        continue
                    sp_border = (0.0, 0.0, 0.0, 0.0)
                    img_type = int(tt.get("m_Type", 0))
                    sp_obj = (co.assets_file.objects.get(pid) if fid == 0 else None) or indexer.obj_by_cab_pid.get((cab, pid))
                    if sp_obj is not None:
                        if sp_obj.type.name != "Sprite":
                            continue
                        pil_img = _read_sprite_rgba_untrimmed(sp_obj)
                        if img_type == 1:
                            bd = sp_obj.read_typetree().get("m_Border") or {}
                            sp_border = (float(bd.get("x", 0.0)), float(bd.get("y", 0.0)), float(bd.get("z", 0.0)), float(bd.get("w", 0.0)))
                    else:
                        if img_type == 1:
                            sres = repos.get_sprite_image_and_meta(cab, pid)
                            if sres is None:
                                continue
                            pil_img = sres[0]
                            sp_border = sres[4] if len(sres) > 4 else (0.0, 0.0, 0.0, 0.0)
                        else:
                            pil_img = repos.get_sprite_image(cab, pid)
                            if pil_img is None:
                                continue
                    mcol = tt.get("m_Color", {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0})
                    dfs_seq += 1
                    img_layers.append({
                        "name": go.m_Name,
                        "path": f"{path}/{go.m_Name}",
                        "sort_order": sort_order,
                        "dfs": dfs_seq,
                        "draw_key": (sort_order, 0.0, dfs_seq),
                        "img": pil_img,
                        "wx": img_cx,
                        "wy": img_cy,
                        "w": w_px,
                        "h": h_px,
                        "sx": wsx,
                        "sy": wsy,
                        "z_deg": z_deg,
                        "clip_rect": clip_rect,
                        "img_type": img_type,
                        "border": sp_border,
                        "color": (float(mcol.get("r", 1.0)), float(mcol.get("g", 1.0)), float(mcol.get("b", 1.0)), float(mcol.get("a", 1.0))),
                    })
                elif "skeletonDataAsset" in tt and tt.get("m_Enabled", 1):
                    is_graphic = "Graphic" in sn
                    z_tie = 0.0 if is_graphic else -round(wz, 3)
                    if "person" in low and not any(t in low for t in ("_bg_", "_bj_")):
                        dfs_seq += 1
                        person_key = (sort_order, z_tie, dfs_seq)
                        continue
                    sref = tt["skeletonDataAsset"]
                    sda = indexer.resolve_sda(co.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
                    if not sda or not sda["skel_cpath"]:
                        continue
                    mult = 100.0 if is_graphic else 1.0
                    ux = wsx * float(sda["scale"]) * mult
                    uy = wsy * float(sda["scale"]) * mult
                    if tt.get("initialFlipX", 0):
                        ux = -ux
                    if tt.get("initialFlipY", 0):
                        uy = -uy
                    anim = tt.get("startingAnimation") or tt.get("_animationName") or "idle"
                    dfs_seq += 1
                    bj_candidates.append({
                        "go_name": go.m_Name,
                        "path": f"{path}/{go.m_Name}",
                        "ab_name": sda["ab_name"],
                        "skel_cpath": sda["skel_cpath"],
                        "sort_order": sort_order,
                        "dfs": dfs_seq,
                        "draw_key": (sort_order, z_tie, dfs_seq),
                        "wx": wx,
                        "wy": wy,
                        "wz": wz,
                        "ux": ux,
                        "uy": uy,
                        "z_deg": z_deg,
                        "is_graphic": is_graphic,
                        "under_spine_scale": ("spine_scale" in path.lower() or from_entity),
                        "anim": anim,
                    })
            except Exception:
                pass

        ss_local_here: tuple[float, float, float] | None = None
        if rt and hasattr(rt, "m_Children"):
            child_sz = (rect_w, rect_h) if is_rect else parent_rect_size
            child_piv = (piv_x, piv_y) if is_rect else parent_pivot
            for ch in rt.m_Children:
                if ch.path_id in c_objs:
                    cg = c_objs[ch.path_id].read().m_GameObject.path_id
                    if not from_entity and depth == 1 and go.m_Name == "Point_Root":
                        cgo = c_objs[cg].read()
                        if cgo.m_Name == "Spine_Scale" and cgo.m_IsActive:
                            _, _, _, ss_local_here, _ = _node_local_tf(cgo, c_objs)
                    walk(
                        cg,
                        depth + 1,
                        (wx, wy, wz),
                        (wsx, wsy, wsz),
                        wq,
                        child_sz,
                        child_piv,
                        f"{path}/{go.m_Name}",
                        False,
                        sort_order,
                        child_clip,
                        cur_objs=c_objs,
                        from_entity=from_entity,
                    )

        # Official SoulTide runtime: MainUI.LoadSpineBG reparents SoulSpineCell as last child of Point_Root,
        # sets goSpineRoot.localScale = Spine_Scale.localScale (fallback 0.1), and spawns SoulAction entity at Vector3.zero!
        if not from_entity and depth == 1 and go.m_Name == "Point_Root" and person_key is None and ent_res is not None:
            ent_objs, ent_gid = ent_res
            esx, esy, esz = ss_local_here if ss_local_here is not None else (0.1, 0.1, 1.0)
            child_sz = (rect_w, rect_h) if is_rect else parent_rect_size
            child_piv = (piv_x, piv_y) if is_rect else parent_pivot
            walk(
                ent_gid,
                0,
                (wx, wy, wz),
                (wsx * esx, wsy * esy, wsz * esz),
                wq,
                child_sz,
                child_piv,
                f"{path}/Point_Root/SoulSpineCell/SpineRoot",
                False,
                sort_order,
                child_clip,
                cur_objs=ent_objs,
                from_entity=True,
            )

    with lock_ctx:
        walk(gid, 0, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (1700.0, 750.0), (0.5, 0.5), "", False, 0, None)

        if person_key is None:
            p_ord = layout["person"].get("sort_order")
            if p_ord is None:
                p_ord = layout.get("person_order") if layout.get("person_order") is not None else 3
            person_key = (int(p_ord), 0.0, 999999)

        # Peek binary bounds & compute rendered area for every bj candidate
        p = layout["person"]
        p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
        for cand in bj_candidates:
            env = repos.get_spine_env(cand["ab_name"])
            ptr = {k.lower(): v for k, v in (env.container or {}).items()}[cand["skel_cpath"].lower()]
            raw = ptr.read().m_Script.encode("utf-8", "surrogateescape")
            parsed = parse_spine38_binary(raw)
            bw, bh = parsed["bounds"][2], parsed["bounds"][3]
            b_ux, b_uy = cand["ux"], cand["uy"]
            if (
                not cand["is_graphic"]
                and cand["under_spine_scale"]
                and 0.05 < spine_scale_factor < 0.35
                and (abs(b_ux) / max(1e-5, p_ux)) < 0.25
                and bw > 1500
                and bw * abs(b_ux) < 400
            ):
                b_ux /= spine_scale_factor
                b_uy /= spine_scale_factor
                cand["ux"] = b_ux
                cand["uy"] = b_uy
            cand["area"] = abs(bw * bh) * abs(b_ux * b_uy)

    img_layers.sort(key=lambda x: x["draw_key"])
    bj_candidates.sort(key=lambda x: x["draw_key"])
    return {
        "img_layers": img_layers,
        "bj_candidates": bj_candidates,
        "person_key": person_key,
        "fx_nodes_keys": fx_nodes_keys,
    }


def _dedup_bj_candidates(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep distinct instances when count == 2 (e.g. left/right props); dedup identical overlaps or swarms (>2)."""
    by_skel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cands:
        by_skel[c["skel_cpath"].lower()].append(c)

    kept: list[dict[str, Any]] = []
    for k, lst in by_skel.items():
        if len(lst) == 1:
            kept.append(lst[0])
        elif len(lst) == 2:
            a, b = lst[0], lst[1]
            same_spot = (
                math.hypot(a["wx"] - b["wx"], a["wy"] - b["wy"]) < 5.0
                and abs(a["ux"] - b["ux"]) < 0.01
                and abs(a["uy"] - b["uy"]) < 0.01
                and abs(a["z_deg"] - b["z_deg"]) < 1.0
            )
            if same_spot:
                kept.append(a)
            else:
                kept.extend([a, b])
        else:
            # Swarm of 3+ identical props (e.g. Superbia's 17 butterflies): keep first representative instance
            kept.append(lst[0])
    kept.sort(key=lambda x: x["draw_key"])
    return kept


def _build_scene_submodels_exact(
    repos: BatchAssetRepos,
    indexer: AssetIndexer,
    skin: dict[str, Any],
    layout: dict[str, Any],
    base_scale: float,
    sub_root: Path,
    has_back_fx: bool,
    has_front_fx: bool,
    asset_lock: threading.RLock | None = None,
    clean_old_non_fx: bool = False,
    force_fx_sides: tuple[bool, bool] | None = None,
) -> tuple[list[tuple[str, str, int]], bool]:
    """Build all static (bg_static, bg_mid, fg_static) and dynamic (bj_*) submodels with exact Unity geometry & side-preserving z-orders.

    Returns (assigned_non_fx_subs, can_split_fx), where assigned_non_fx_subs is [(sub_id, rel_cfg, order)].
    """
    lock_ctx = asset_lock if asset_lock is not None else nullcontext()
    if clean_old_non_fx and sub_root.is_dir():
        for d in list(sub_root.iterdir()):
            if d.is_dir() and not d.name.lower().startswith("fx_"):
                shutil.rmtree(d, ignore_errors=True)

    ov = _SCENE_LAYOUT_OVERRIDES.get(skin["skin_key"], {})
    eff_layout = dict(layout)
    if "override_canvas" in ov:
        eff_layout["canvas_w"], eff_layout["canvas_h"] = ov["override_canvas"]
    if "override_cam" in ov:
        eff_layout["cam_x"], eff_layout["cam_y"] = ov["override_cam"]

    scene = _extract_unity_scene_layers(repos, indexer, skin, eff_layout, asset_lock=asset_lock)
    img_layers = scene["img_layers"]
    skip_substrs = ov.get("skip_img_path_substrs") or ()
    if skip_substrs:
        kept_imgs = []
        for im in img_layers:
            if any(sub in im["path"] for sub in skip_substrs):
                try:
                    im["img"].close()
                except Exception:
                    pass
            else:
                kept_imgs.append(im)
        img_layers = kept_imgs
    bj_all = scene["bj_candidates"]
    person_key = scene["person_key"]

    p = eff_layout["person"]
    p_wx, p_wy = float(p["wx"]), float(p["wy"])
    p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
    p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
    p_deg = float(p.get("z_deg", 0.0))
    preserve_scene_rot = bool(ov.get("preserve_scene_rot", False))

    # Determine if main backdrop images share Person's rotation (e.g. Asuna_S6 +7.2 deg -> counter-rotate cleanly)
    counter_rot_deg = 0.0
    if not preserve_scene_rot and abs(p_deg) > 0.5 and img_layers:
        big_imgs = [im for im in img_layers if im["w"] >= 1000.0 and im["h"] >= 600.0]
        if big_imgs and all(abs(im["z_deg"] - p_deg) < 1.0 for im in big_imgs):
            counter_rot_deg = p_deg

    back_imgs = [im for im in img_layers if im["draw_key"] < person_key]
    fg_imgs = [im for im in img_layers if im["draw_key"] > person_key]
    back_bjs = _dedup_bj_candidates([b for b in bj_all if b["draw_key"] < person_key])
    front_bjs = _dedup_bj_candidates([b for b in bj_all if b["draw_key"] > person_key])

    # Optional non-overlapping back_bj promotion to positive side (e.g. RubyRose_S2 bj_02, Freesia_S4 bj_01)
    promote_skels = {s.lower() for s in (ov.get("promote_back_bj_to_pos") or ())}
    if promote_skels:
        promoted = [b for b in back_bjs if Path(b["skel_cpath"]).name.lower() in promote_skels]
        back_bjs = [b for b in back_bjs if Path(b["skel_cpath"]).name.lower() not in promote_skels]
        for pb in promoted:
            pb_copy = dict(pb)
            # Place promoted non-overlapping BJ first among positive slots (closest to person, behind real fg BJs)
            pb_copy["draw_key"] = (person_key[0], -999.0, pb["draw_key"][2])
            front_bjs.append(pb_copy)
        front_bjs.sort(key=lambda x: x["draw_key"])

    # Decide FX split vs single layer: reserve slots strictly on matching side
    # Behind Person has 3 slots (-3, -2, -1); Front of Person has 3 slots (+1, +2, +3).
    if force_fx_sides is not None:
        want_fx_back, want_fx_front = force_fx_sides
        can_split_fx = want_fx_back and want_fx_front
    else:
        want_fx_back = has_back_fx and not has_front_fx
        want_fx_front = has_front_fx
        can_split_fx = False
        if has_back_fx and has_front_fx:
            # Split FX only if behind-Person doesn't need all 3 slots for bg_static + bj + bg_mid
            est_neg = (1 if back_imgs else 0) + len(back_bjs)
            est_pos = (1 if fg_imgs else 0) + len(front_bjs)
            if est_neg <= 2 and est_pos <= 2:
                can_split_fx = True
                want_fx_back = True
                want_fx_front = True

    sandwich_min_ord = ov.get("sandwich_bg_mid_min_ord")
    sandwich_names = ov.get("sandwich_bg_mid_names")
    reserve_neg_slot = ov.get("reserve_neg_slot")
    is_fx_sandwich = (sandwich_min_ord is not None) or bool(sandwich_names)

    if is_fx_sandwich:
        # Reserve -2 explicitly for fx_back between bg_static(-3) and bg_mid(-1)!
        avail_neg = [-3, -1]
    elif reserve_neg_slot is not None:
        avail_neg = [s for s in (-3, -2, -1) if s != int(reserve_neg_slot)]
    else:
        avail_neg = [-3, -2] if want_fx_back else [-3, -2, -1]
    avail_pos = [1, 2] if want_fx_front else [1, 2, 3]

    # --- Helper to materialize one bj candidate ---
    used_bj_names: set[str] = set()

    def _build_one_bj(cand: dict[str, Any], idx_hint: int) -> tuple[str, str]:
        stem = Path(cand["skel_cpath"]).name[:-len(".skel.bytes")].lower()
        m_num = re.search(r"(bj_\d+|bg_?\d+|tree\d*|robort_\d+|butterfly|grass|curtain|flower|carpet|umbrella)", stem)
        base_nm = m_num.group(1) if m_num else f"bj_{idx_hint:02d}"
        sub_name = base_nm
        suffix_i = 2
        while sub_name in used_bj_names:
            sub_name = f"{base_nm}_{suffix_i}"
            suffix_i += 1
        used_bj_names.add(sub_name)

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
        # Wrap to [-180, 180]
        while rel_rot > 180.0:
            rel_rot -= 360.0
        while rel_rot < -180.0:
            rel_rot += 360.0
        if abs(rel_rot) < 0.25:
            rel_rot = 0.0

        # Choose calibrated scale_factor within verify_batch_spine.py [0.1, 4.0] bounds
        if 0.15 <= abs(rel_sx) <= 3.5:
            s_ratio = abs(rel_sx)
        else:
            s_ratio = max(0.15, min(3.5, (abs(rel_sx) + abs(rel_sy)) / 2.0))

        mul_sx = rel_sx / s_ratio
        mul_sy = rel_sy / s_ratio
        dx_sp = tx_main / s_ratio
        dy_sp = ty_main / s_ratio
        if math.hypot(d_x, d_y) < 2.0:
            dx_sp, dy_sp = 0.0, 0.0

        sdir = sub_root / sub_name
        with lock_ctx:
            bj_env = repos.get_spine_env(cand["ab_name"])
            meta = _extract_spine_unit_from_ab(
                bj_env,
                cand["skel_cpath"],
                sdir,
                strip_bg=False,
                root_shift=(dx_sp, dy_sp),
                root_scale=(mul_sx, mul_sy),
                root_rot=rel_rot,
                asset_lock=asset_lock,
                save_webp=True,
                clean_etc2=True,
            )

        anims = meta["parsed"]["anims"]
        chosen_anim = (
            cand["anim"]
            if cand["anim"] in anims
            else ("idle" if "idle" in anims else ("animation" if "animation" in anims else anims[0]))
        )
        rel_scale = round(base_scale * s_ratio, 5)
        sub_id = f"{skin['skin_key'].lower()}_{sub_name}"
        sub_cfg = {
            "conf_ver": 1,
            "type": 9,
            "controllers": {"param_hit": {}, "param_loop": {}, "intimacy_system": {}, "slot_opacity": {}, "slot_color": {}},
            "hit_areas": [],
            "motions": {"idle": [{"name": chosen_anim, "file": chosen_anim, "file_loop": True}]},
            "options": {
                "id": sub_id,
                "scale_factor": rel_scale,
                "position_x": 0.0,
                "position_y": 0.0,
                "tex_type": meta.get("tex_type", 1),
                "edge_padding": False,
            },
            "skeleton": meta["skeleton"],
            "atlases": [{"atlas": meta["atlas"], "tex_names": meta["tex_names"], "textures": meta["textures"]}],
        }
        write_json(sdir / ".config.json", sub_cfg)
        return sub_id, f"submodels/{sub_name}/.config.json"

    assigned: list[tuple[str, str, int]] = []

    def _bj_priority(x: dict[str, Any]) -> float:
        boost = 2.5 if (x.get("under_spine_scale") or x.get("sort_order") == person_key[0]) else 1.0
        return float(x["area"]) * boost

    # --- 1. BEHIND PERSON (strictly order < 0) ---
    neg_items: list[tuple[tuple[int, float, int], str, str]] = []  # (draw_key, sub_id, rel_cfg)
    if is_fx_sandwich:
        if sandwich_names:
            pre_imgs = [im for im in back_imgs if im["name"] not in sandwich_names]
            mid_imgs = [im for im in back_imgs if im["name"] in sandwich_names]
        else:
            pre_imgs = [im for im in back_imgs if im["sort_order"] < int(sandwich_min_ord)]
            mid_imgs = [im for im in back_imgs if im["sort_order"] >= int(sandwich_min_ord)]
        if pre_imgs:
            bg_res = _render_static_image_group(pre_imgs, skin, eff_layout, base_scale, sub_root / "bg_static", "bg_static", counter_rot_deg)
            if bg_res:
                neg_items.append(((0, 0.0, 0), bg_res["id"], bg_res["rel"]))
        if mid_imgs:
            mid_res = _render_static_image_group(mid_imgs, skin, eff_layout, base_scale, sub_root / "bg_mid", "bg_mid", counter_rot_deg)
            if mid_res:
                neg_items.append(((999999, 0.0, 999999), mid_res["id"], mid_res["rel"]))
    elif not back_bjs:
        if back_imgs:
            bg_res = _render_static_image_group(back_imgs, skin, eff_layout, base_scale, sub_root / "bg_static", "bg_static", counter_rot_deg)
            if bg_res:
                neg_items.append((back_imgs[0]["draw_key"], bg_res["id"], bg_res["rel"]))
    else:
        # Fix Defect C1: select kept_bjs FIRST, then split pre_imgs/mid_imgs strictly around kept_bjs!
        rem_if_mid = max(0, len(avail_neg) - 2)
        cand_kept_bjs = sorted(back_bjs, key=lambda x: -_bj_priority(x))[:rem_if_mid]
        cand_kept_bjs.sort(key=lambda x: x["draw_key"])
        split_bj_key = cand_kept_bjs[-1]["draw_key"] if cand_kept_bjs else back_bjs[0]["draw_key"]
        pre_imgs = [im for im in back_imgs if im["draw_key"] < split_bj_key]
        mid_imgs = [im for im in back_imgs if im["draw_key"] > split_bj_key]

        use_mid_split = False
        mid_res: dict[str, Any] | None = None
        if cand_kept_bjs and mid_imgs and len(avail_neg) >= (1 if pre_imgs else 0) + 2:
            # Check if mid_imgs produces significant foreground-masking pixels
            mid_res = _render_static_image_group(mid_imgs, skin, eff_layout, base_scale, sub_root / "bg_mid", "bg_mid", counter_rot_deg)
            if mid_res is not None:
                rem_if_mid_eff = len(avail_neg) - (1 if pre_imgs else 0) - 1
                # Keep bg_mid when it fits all back_bjs OR has substantial masking area (>= 60,000 px^2)
                if len(back_bjs) <= rem_if_mid_eff or mid_res["area_px"] >= 60000:
                    use_mid_split = True
                else:
                    shutil.rmtree(sub_root / "bg_mid", ignore_errors=True)
                    mid_res = None

        if use_mid_split and mid_res is not None:
            if pre_imgs:
                bg_res = _render_static_image_group(pre_imgs, skin, eff_layout, base_scale, sub_root / "bg_static", "bg_static", counter_rot_deg)
                if bg_res:
                    neg_items.append(((0, 0.0, 0), bg_res["id"], bg_res["rel"]))
            rem_bj = len(avail_neg) - len(neg_items) - 1
            kept_bjs = cand_kept_bjs[: max(0, rem_bj)]
            for bi, cand in enumerate(kept_bjs, 1):
                sid, rel = _build_one_bj(cand, bi)
                neg_items.append((cand["draw_key"], sid, rel))
            # mid_imgs[0]["draw_key"] is strictly > split_bj_key == kept_bjs[-1]["draw_key"]!
            neg_items.append((mid_imgs[-1]["draw_key"], mid_res["id"], mid_res["rel"]))
        else:
            if back_imgs:
                bg_res = _render_static_image_group(back_imgs, skin, eff_layout, base_scale, sub_root / "bg_static", "bg_static", counter_rot_deg)
                if bg_res:
                    neg_items.append(((0, 0.0, 0), bg_res["id"], bg_res["rel"]))
            rem_bj = len(avail_neg) - len(neg_items)
            kept_bjs = sorted(back_bjs, key=lambda x: -_bj_priority(x))[: max(0, rem_bj)]
            kept_bjs.sort(key=lambda x: x["draw_key"])
            for bi, cand in enumerate(kept_bjs, 1):
                sid, rel = _build_one_bj(cand, bi)
                neg_items.append((cand["draw_key"], sid, rel))

    neg_items.sort(key=lambda x: x[0])
    for (_, sid, rel), ord_v in zip(neg_items, avail_neg):
        assigned.append((sid, rel, ord_v))

    # --- 2. IN FRONT OF PERSON (strictly order > 0) ---
    pos_items: list[tuple[tuple[int, float, int], str, str]] = []
    fg_res: dict[str, Any] | None = None
    if fg_imgs and len(avail_pos) >= 1:
        fg_res = _render_static_image_group(fg_imgs, skin, eff_layout, base_scale, sub_root / "fg_static", "fg_static", counter_rot_deg)

    rem_front_bj = len(avail_pos) - (1 if fg_res is not None else 0)
    kept_front_bjs = sorted(front_bjs, key=lambda x: -_bj_priority(x))[: max(0, rem_front_bj)]
    kept_front_bjs.sort(key=lambda x: x["draw_key"])
    for fi, cand in enumerate(kept_front_bjs, 1):
        sid, rel = _build_one_bj(cand, fi)
        pos_items.append((cand["draw_key"], sid, rel))
    if fg_res is not None:
        pos_items.append((fg_imgs[0]["draw_key"], fg_res["id"], fg_res["rel"]))

    pos_items.sort(key=lambda x: x[0])
    for (_, sid, rel), ord_v in zip(pos_items, avail_pos):
        assigned.append((sid, rel, ord_v))

    # Close all loaded PIL sprites to keep RAM low
    for im in img_layers:
        try:
            im["img"].close()
        except Exception:
            pass
    img_layers.clear()

    return assigned, can_split_fx


def _assign_orders(
    non_fx_assigned: list[tuple[str, str, int]],
    fx_items: list[tuple[str, str, str]],
) -> list[tuple[str, str, int]]:
    """Combine side-preserving non-FX submodels with FX submodels (total <= 6, never crossing order 0).
    Preserves intentional negative-slot reservations (e.g. (-3 bg_static, -1 bg_mid) sandwiching fx_back at -2,
    or (-2 bg_static, -1 bj_05) reserving -3 for fx_asuna_s8_back).
    """
    assigned = list(non_fx_assigned)
    neg_non_fx = sorted([x for x in assigned if x[2] < 0], key=lambda x: x[2])
    pos_non_fx = sorted([x for x in assigned if x[2] > 0], key=lambda x: x[2])
    neg_explicit_ords = tuple(x[2] for x in neg_non_fx)
    preserve_neg_gap = neg_explicit_ords in ((-3, -1), (-2, -1))

    rebased: list[tuple[str, str, int]] = []
    if preserve_neg_gap:
        rebased.extend(neg_non_fx)
    else:
        neg_sorted = sorted(neg_non_fx, key=lambda x: (0 if "/bg_static/" in x[1].replace("\\", "/") else 1, x[2]))
        for idx, (sid, rel, _) in enumerate(neg_sorted):
            rebased.append((sid, rel, -3 + idx))
    for idx, (sid, rel, _) in enumerate(pos_non_fx):
        rebased.append((sid, rel, 1 + idx))
    assigned = rebased

    used = {o for _, _, o in assigned}
    avail_neg = [o for o in (-3, -2, -1) if o not in used]
    avail_pos = [o for o in (1, 2, 3) if o not in used]

    for fx_id, fx_rel, fx_layer in fx_items:
        if fx_layer == "back":
            ord_val = avail_neg.pop(-1) if avail_neg else (avail_pos.pop(0) if avail_pos else -1)
        else:
            ord_val = avail_pos.pop(-1) if avail_pos else (avail_neg.pop(-1) if avail_neg else 3)
        assigned.append((fx_id, fx_rel, ord_val))

    assigned.sort(key=lambda x: x[2])
    return assigned


def _detect_skin_fx_layers(skin: dict[str, Any]) -> tuple[bool, bool, dict[str, Any]]:
    """Inspect recorded FX sequence dir & clip_meta.json to detect presence of back and front clips."""
    seq_root = FX_SEQ_ROOT / skin["skin_key"]
    if not seq_root.is_dir():
        return False, False, {}
    clip_meta: dict[str, Any] = {}
    meta_path = seq_root / "clip_meta.json"
    if meta_path.is_file():
        try:
            clip_meta = json.loads(meta_path.read_text(encoding="utf-8-sig")).get("clips", {})
        except Exception:
            clip_meta = {}

    def _has_frames(cdir: Path) -> bool:
        return cdir.is_dir() and (
            any((cdir / "normal").glob("frame_*.png")) or any((cdir / "add").glob("frame_*.png"))
        )

    has_back = _has_frames(seq_root / "idle_back")
    has_front = _has_frames(seq_root / "idle_front")
    if _has_frames(seq_root / "idle"):
        lay = clip_meta.get("idle", {}).get("layer", "front")
        if lay == "back":
            has_back = True
        else:
            has_front = True
    for eid in skin["effect_ids"]:
        cname = f"fx_{eid}"
        if _has_frames(seq_root / cname):
            lay = clip_meta.get(cname, {}).get("layer", "front")
            if lay == "back":
                has_back = True
            else:
                has_front = True
    return has_back, has_front, clip_meta


def _merge_idle_layer_frames(back_dir: Path, front_dir: Path, out_dir: Path) -> tuple[list[Path], list[Path]]:
    """Composite idle_back + idle_front frames into out_dir when submodel quota prevents splitting."""
    out_norm_paths: list[Path] = []
    out_add_paths: list[Path] = []

    b_norm = sorted((back_dir / "normal").glob("frame_*.png")) if (back_dir / "normal").is_dir() else []
    f_norm = sorted((front_dir / "normal").glob("frame_*.png")) if (front_dir / "normal").is_dir() else []
    if b_norm or f_norm:
        ndir = out_dir / "normal"
        ndir.mkdir(parents=True, exist_ok=True)
        n = max(len(b_norm), len(f_norm))
        for i in range(n):
            bp = b_norm[i] if i < len(b_norm) else None
            fp = f_norm[i] if i < len(f_norm) else None
            out_p = ndir / f"frame_{i:04d}.png"
            if bp is not None and fp is not None:
                with Image.open(bp) as bim, Image.open(fp) as fim:
                    comp = Image.alpha_composite(bim.convert("RGBA"), fim.convert("RGBA"))
                    comp.save(out_p, "PNG")
                    comp.close()
            else:
                shutil.copy2(bp or fp, out_p)
            out_norm_paths.append(out_p)

    b_add = sorted((back_dir / "add").glob("frame_*.png")) if (back_dir / "add").is_dir() else []
    f_add = sorted((front_dir / "add").glob("frame_*.png")) if (front_dir / "add").is_dir() else []
    if b_add or f_add:
        adir = out_dir / "add"
        adir.mkdir(parents=True, exist_ok=True)
        n = max(len(b_add), len(f_add))
        for i in range(n):
            bp = b_add[i] if i < len(b_add) else None
            fp = f_add[i] if i < len(f_add) else None
            out_p = adir / f"frame_{i:04d}.png"
            if bp is not None and fp is not None:
                with Image.open(bp) as bim, Image.open(fp) as fim:
                    ba = np.asarray(bim.convert("RGBA"), dtype=np.uint16)
                    fa = np.asarray(fim.convert("RGBA"), dtype=np.uint16)
                    rgb = np.minimum(255, ba[:, :, :3] + fa[:, :, :3]).astype(np.uint8)
                    alpha = np.max(rgb, axis=2, keepdims=True)
                    merged = np.concatenate([rgb, alpha], axis=2)
                    Image.fromarray(merged, mode="RGBA").save(out_p, "PNG")
            else:
                shutil.copy2(bp or fp, out_p)
            out_add_paths.append(out_p)

    return out_norm_paths, out_add_paths


def _build_fx_submodels_for_skin(
    skin: dict[str, Any],
    layout: dict[str, Any],
    base_scale: float,
    sub_root: Path,
    split_layers: bool,
    clip_meta: dict[str, Any],
    frame_workers: int = 1,
) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    """Pack Unity-recorded FX sequences into 1 (merged) or 2 (fx_back + fx_front) Spine 3.8 FX submodels."""
    seq_root = FX_SEQ_ROOT / skin["skin_key"]
    if not seq_root.is_dir():
        return [], {}

    def _clip_fps(cname: str, default_fps: float = 18.0) -> float:
        info = clip_meta.get(cname, {})
        val = float(info.get("fps", default_fps) or default_fps)
        return val if val > 0.1 else default_fps

    def _clip_layer(cname: str, default_layer: str = "front") -> str:
        lay = clip_meta.get(cname, {}).get("layer", default_layer)
        return "back" if lay == "back" else "front"

    def _pack_one(model_name: str, fx_id: str, sequences: list[AnimSequenceSpec]) -> tuple[str, str]:
        first_frame = next(
            (p for seq in sequences for p in ((seq.normal_frames or []) + (seq.add_frames or []))),
            None,
        )
        render_w = max(64, layout["canvas_w"] // 2)
        render_h = max(64, layout["canvas_h"] // 2)
        if first_frame is not None:
            with Image.open(first_frame) as im:
                render_w, render_h = im.size
        p = layout["person"]
        p_ux = float(p.get("ui_per_spine_x") or p["ui_per_spine"])
        p_uy = float(p.get("ui_per_spine_y") or p["ui_per_spine"])
        rec_cw, rec_ch = float(layout["canvas_w"]), float(layout["canvas_h"])
        rec_cx, rec_cy = float(layout["cam_x"]), float(layout["cam_y"])
        _mf_p = TOOLS_DIR / "SoulTideBatchFxUnity" / "fx_manifest.json"
        if _mf_p.is_file():
            try:
                _mf = json.loads(_mf_p.read_text(encoding="utf-8-sig"))
                _ms = next((s for s in _mf.get("skins", []) if s.get("skin_key") == skin["skin_key"]), None)
                if _ms and _ms.get("canvas_w") and _ms.get("canvas_h"):
                    rec_cw, rec_ch = float(_ms["canvas_w"]), float(_ms["canvas_h"])
                    rec_cx, rec_cy = float(_ms.get("cam_x", 0.0)), float(_ms.get("cam_y", 0.0))
            except Exception:
                pass
        sx = (rec_cx - p["wx"]) / p_ux
        sy = (rec_cy - p["wy"]) / p_uy
        sw = rec_cw / p_ux
        sh = rec_ch / p_uy
        pack_fx_submodel(
            output_dir=sub_root / model_name,
            model_name=model_name,
            model_id=fx_id,
            sequences=sequences,
            root_x=sx,
            root_y=sy,
            root_scale_x=sw / render_w,
            root_scale_y=sh / render_h,
            scale_factor=round(base_scale, 5),
            max_atlas_size=4096,
            padding=2,
            frame_workers=frame_workers,
        )
        return fx_id, f"submodels/{model_name}/.config.json"

    slug = skin["bg_slug"].lower()
    key_low = skin["skin_key"].lower()
    fx_items: list[tuple[str, str, str]] = []
    fx_target_by_clip: dict[str, str] = {}

    if split_layers:
        for lname in ("back", "front"):
            seqs: list[AnimSequenceSpec] = []
            idle_sub = seq_root / f"idle_{lname}"
            idle_single = seq_root / "idle"
            if idle_sub.is_dir():
                in_norm = sorted((idle_sub / "normal").glob("frame_*.png")) if (idle_sub / "normal").is_dir() else []
                in_add = sorted((idle_sub / "add").glob("frame_*.png")) if (idle_sub / "add").is_dir() else []
                if in_norm or in_add:
                    seqs.append(AnimSequenceSpec(
                        name="idle",
                        fps=_clip_fps(f"idle_{lname}", 18.0),
                        loop=True,
                        is_overlay=False,
                        normal_frames=in_norm,
                        add_frames=in_add,
                        motion_group="idle",
                    ))
            elif idle_single.is_dir() and _clip_layer("idle", "front") == lname:
                in_norm = sorted((idle_single / "normal").glob("frame_*.png")) if (idle_single / "normal").is_dir() else []
                in_add = sorted((idle_single / "add").glob("frame_*.png")) if (idle_single / "add").is_dir() else []
                if in_norm or in_add:
                    seqs.append(AnimSequenceSpec(
                        name="idle",
                        fps=_clip_fps("idle", 18.0),
                        loop=True,
                        is_overlay=False,
                        normal_frames=in_norm,
                        add_frames=in_add,
                        motion_group="idle",
                    ))

            layer_clips: list[str] = []
            for eid in skin["effect_ids"]:
                cname = f"fx_{eid}"
                if _clip_layer(cname, "front") != lname:
                    continue
                cdir = seq_root / cname
                if not cdir.is_dir():
                    continue
                cn = sorted((cdir / "normal").glob("frame_*.png")) if (cdir / "normal").is_dir() else []
                ca = sorted((cdir / "add").glob("frame_*.png")) if (cdir / "add").is_dir() else []
                if cn or ca:
                    seqs.append(AnimSequenceSpec(
                        name=cname,
                        fps=_clip_fps(cname, 18.0),
                        loop=False,
                        is_overlay=True,
                        normal_frames=cn,
                        add_frames=ca,
                        motion_group="main",
                    ))
                    layer_clips.append(cname)

            if seqs:
                mname = f"fx_{slug}_{lname}"
                fx_id = f"{key_low}_fx_{lname}"
                _, rel_cfg = _pack_one(mname, fx_id, seqs)
                fx_items.append((fx_id, rel_cfg, lname))
                for cname in layer_clips:
                    fx_target_by_clip[cname] = fx_id
        return fx_items, fx_target_by_clip

    # Single FX submodel (either single-layer FX or quota-full merged fallback)
    seqs = []
    tmp_merge_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        idle_back_dir = seq_root / "idle_back"
        idle_front_dir = seq_root / "idle_front"
        idle_dir = seq_root / "idle"
        only_layer = "front"

        if idle_back_dir.is_dir() and idle_front_dir.is_dir():
            tmp_merge_dir = tempfile.TemporaryDirectory(prefix="fx_merge_")
            in_norm, in_add = _merge_idle_layer_frames(idle_back_dir, idle_front_dir, Path(tmp_merge_dir.name))
            if in_norm or in_add:
                seqs.append(AnimSequenceSpec(
                    name="idle",
                    fps=_clip_fps("idle_front", _clip_fps("idle_back", 18.0)),
                    loop=True,
                    is_overlay=False,
                    normal_frames=in_norm,
                    add_frames=in_add,
                    motion_group="idle",
                ))
        elif idle_dir.is_dir() or idle_back_dir.is_dir() or idle_front_dir.is_dir():
            src_idle = idle_dir if idle_dir.is_dir() else (idle_front_dir if idle_front_dir.is_dir() else idle_back_dir)
            src_name = src_idle.name
            only_layer = "back" if src_name == "idle_back" else _clip_layer(src_name, "front")
            in_norm = sorted((src_idle / "normal").glob("frame_*.png")) if (src_idle / "normal").is_dir() else []
            in_add = sorted((src_idle / "add").glob("frame_*.png")) if (src_idle / "add").is_dir() else []
            if in_norm or in_add:
                seqs.append(AnimSequenceSpec(
                    name="idle",
                    fps=_clip_fps(src_name, 18.0),
                    loop=True,
                    is_overlay=False,
                    normal_frames=in_norm,
                    add_frames=in_add,
                    motion_group="idle",
                ))

        packed_clips: list[str] = []
        has_front_clip = (only_layer == "front") and bool(seqs)
        for eid in skin["effect_ids"]:
            cname = f"fx_{eid}"
            cdir = seq_root / cname
            if not cdir.is_dir():
                continue
            cn = sorted((cdir / "normal").glob("frame_*.png")) if (cdir / "normal").is_dir() else []
            ca = sorted((cdir / "add").glob("frame_*.png")) if (cdir / "add").is_dir() else []
            if cn or ca:
                if _clip_layer(cname, "front") == "front":
                    has_front_clip = True
                seqs.append(AnimSequenceSpec(
                    name=cname,
                    fps=_clip_fps(cname, 18.0),
                    loop=False,
                    is_overlay=True,
                    normal_frames=cn,
                    add_frames=ca,
                    motion_group="main",
                ))
                packed_clips.append(cname)

        if not seqs:
            return [], {}
        single_layer = "front" if (has_front_clip or (idle_back_dir.is_dir() and idle_front_dir.is_dir())) else "back"
        mname = f"fx_{slug}"
        fx_id = f"{key_low}_fx"
        _, rel_cfg = _pack_one(mname, fx_id, seqs)
        fx_items.append((fx_id, rel_cfg, single_layer))
        for cname in packed_clips:
            fx_target_by_clip[cname] = fx_id
        return fx_items, fx_target_by_clip
    finally:
        if tmp_merge_dir is not None:
            tmp_merge_dir.cleanup()


def _resolve_backup_cfg(repos: BatchAssetRepos, skin: dict[str, Any], main_skel_name: str) -> dict[str, Any] | None:
    cn, dn = skin["char_name"], skin["dress_name"]
    cand = repos.bkp_by_pair.get((cn, dn))
    if cand is None:
        sk_stem = Path(main_skel_name).stem.lower().replace(".skel", "")
        cand = repos.bkp_by_skel.get(sk_stem)
    if cand is None:
        return None
    try:
        return json.loads(cand.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute_fallback_hit_areas(parsed: dict[str, Any], idle_anim: str, motions: dict[str, Any]) -> list[dict[str, Any]]:
    """Estimate accurate hit_areas from real Spine 3.8 bone world coordinates in idle pose."""
    world_pos = eval_bone_world_positions(parsed, idle_anim)
    if not world_pos:
        return []
    xs = [xy[0] for xy in world_pos.values()]
    ys = [xy[1] for xy in world_pos.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    h = max(100.0, max_y - min_y)
    cx = (min_x + max_x) / 2.0

    def pick_bone(keywords: tuple[str, ...], target_x: float, target_y: float) -> str:
        # Prefer named bone if found, else closest bone to target fraction
        named = [bn for bn in world_pos if any(k in bn.lower() for k in keywords) and "beijing" not in bn.lower()]
        if named:
            return min(named, key=lambda bn: math.hypot(world_pos[bn][0] - target_x, world_pos[bn][1] - target_y))
        return min(world_pos.keys(), key=lambda bn: math.hypot(world_pos[bn][0] - target_x, world_pos[bn][1] - target_y))

    targets = [
        ("头", ("head", "tou", "face", "lian"), cx, min_y + 0.78 * h, 2.5, 2.2),
        ("左手", ("hand_l", "l_hand", "zuoshou", "shou_l", "arm_l"), cx - 0.15 * h, min_y + 0.52 * h, 1.5, 1.5),
        ("右手", ("hand_r", "r_hand", "youshou", "shou_r", "arm_r"), cx + 0.15 * h, min_y + 0.52 * h, 1.5, 1.5),
        ("胸", ("chest", "xiong", "breast", "body", "shen"), cx, min_y + 0.58 * h, 2.2, 1.8),
        ("腿", ("leg", "tui", "thigh", "skirt", "qun"), cx, min_y + 0.30 * h, 3.2, 3.5),
        ("足", ("foot", "jiao", "zu", "shoe"), cx, min_y + 0.10 * h, 2.5, 1.5),
    ]
    out: list[dict[str, Any]] = []
    for name, kws, tx, ty, w, hh in targets:
        if name not in motions:
            continue
        bid = pick_bone(kws, tx, ty)
        out.append({"name": name, "id": bid, "motion": name, "width": w, "height": hh})
    return out


def build_one_skin(
    skin: dict[str, Any],
    repo: FullI18nRepo,
    indexer: AssetIndexer,
    repos: BatchAssetRepos,
    out_dir: Path,
    asset_lock: threading.RLock | None = None,
    frame_workers: int = 1,
) -> dict[str, Any]:
    lock_ctx = asset_lock if asset_lock is not None else nullcontext()
    out_dir.mkdir(parents=True, exist_ok=True)
    aud_dir = out_dir / "audio"
    bgm_dir = out_dir / "bgm"
    sub_root = out_dir / "submodels"
    for d in (aud_dir, bgm_dir, sub_root):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Extract main Spine skeleton & strip any embedded bg/harmonious slot attachments
    with lock_ctx:
        ab_name, skel_cpath = _find_main_skel_unit(repos, indexer, skin)
        main_env = repos.get_spine_env(ab_name)
        main_meta = _extract_spine_unit_from_ab(main_env, skel_cpath, out_dir, strip_bg=True, asset_lock=asset_lock)
    main_parsed = main_meta["parsed"]
    main_anims = set(main_parsed["anims"])
    main_bones = {b["name"] for b in main_parsed["bones"]}

    # Determine base_scale & backup config
    bkp_cfg = _resolve_backup_cfg(repos, skin, main_meta["skeleton"])
    base_scale = 0.11
    if bkp_cfg:
        sc = float(bkp_cfg.get("options", {}).get("scale_factor", 0.11) or 0.11)
        if 0.04 <= sc <= 0.45:
            base_scale = round(sc, 5)

    # 2. Compute layout & build submodels (<= 6 total, strictly side-preserving!)
    with lock_ctx:
        layout = inspect_bg_prefab_layout(indexer, skin)

    has_back_fx, has_front_fx, clip_meta = _detect_skin_fx_layers(skin)
    non_fx_assigned, can_split_fx = _build_scene_submodels_exact(
        repos=repos,
        indexer=indexer,
        skin=skin,
        layout=layout,
        base_scale=base_scale,
        sub_root=sub_root,
        has_back_fx=has_back_fx,
        has_front_fx=has_front_fx,
        asset_lock=asset_lock,
        clean_old_non_fx=True,
    )
    for old_fx_dir in sub_root.glob("fx_*"):
        if old_fx_dir.is_dir():
            shutil.rmtree(old_fx_dir, ignore_errors=True)

    fx_items, fx_target_by_clip = _build_fx_submodels_for_skin(
        skin,
        layout,
        base_scale,
        sub_root,
        split_layers=can_split_fx,
        clip_meta=clip_meta,
        frame_workers=frame_workers,
    )
    assigned_subs = _assign_orders(non_fx_assigned, fx_items)
    submodel_cmd = "; ".join(f"add_submodel {rel} {order}" for _, rel, order in assigned_subs)

    # 3. Extract all WAV voices + Chinese subtitles
    extracted_wavs: dict[str, str] = {}
    pending_writes: list[tuple[Path, bytes]] = []
    spine_rows: dict[int, dict[str, Any]] = {}
    with lock_ctx:
        for aid in skin["action_ids"]:
            if aid in spine_rows:
                continue
            body = repo.spine_actions.get(aid, "")
            if not body:
                continue
            m_cv = re.search(r"CV\s*=\s*(\d+)", body)
            m_st = re.search(r'SoulActionState\s*=\s*"([^"]+)"', body)
            m_mst = re.search(r'MarryActionState\s*=\s*"([^"]+)"', body)
            m_eff = re.search(r"EffectId\s*=\s*(\d+)", body)
            m_meff = re.search(r"MarryEffectId\s*=\s*(\d+)", body)

            cv_id = int(m_cv.group(1)) if m_cv else None
            cv_info = repo.resolve_cv(cv_id)
            wav_rel = ""
            if cv_info["sound_stem"]:
                low_stem = cv_info["sound_stem"].lower()
                cv_res = repos.get_cv_samples(low_stem)
                if cv_res is not None:
                    cname, raw_bytes = cv_res
                    wav_rel = f"audio/{cname}.wav"
                    if cname not in extracted_wavs:
                        pending_writes.append((out_dir / wav_rel, raw_bytes))
                        extracted_wavs[cname] = wav_rel

            st = m_st.group(1) if m_st else "idle"
            mst = m_mst.group(1) if m_mst else st
            spine_rows[aid] = {
                "id": aid,
                "state": st,
                "marry_state": mst,
                "effect_id": int(m_eff.group(1)) if m_eff else None,
                "marry_effect_id": int(m_meff.group(1)) if m_meff else None,
                "sound": wav_rel,
                "text": cv_info["text"],
                "text_duration": cv_info["duration_ms"],
            }

        # 4. Extract BGM if present
        bgm_name = ""
        if skin["spine_bgm"]:
            srel = repo.sound_map.get(skin["spine_bgm"], "")
            if srel:
                bstem = Path(srel).stem.lower()
                bgm_res = repos.get_bgm_samples(bstem)
                if bgm_res is not None:
                    cname, raw_bytes = bgm_res
                    pending_writes.append((bgm_dir / f"{cname}.wav", raw_bytes))
                    bgm_name = f"{cname}.wav"

    for dest_p, data_bytes in pending_writes:
        dest_p.write_bytes(data_bytes)

    # 5. Build Motions
    idle_anim = (
        "idle_marry" if "idle_marry" in main_anims
        else ("idle" if "idle" in main_anims
              else ("animation" if "animation" in main_anims else main_parsed["anims"][0]))
    )

    def pick_anim(name: str, fallback: str) -> str:
        if name in main_anims:
            return name
        if fallback in main_anims:
            return fallback
        return idle_anim

    def mk_mtn(aid: int, use_marry: bool = True, idx_label: str = "") -> dict[str, Any]:
        row = spine_rows[aid]
        anim = pick_anim(row["marry_state"] if use_marry else row["state"], row["state"])
        item: dict[str, Any] = {
            "name": f"{idx_label or aid}_{anim}",
            "file": anim,
            "fade_in": 100,
            "fade_out": 100,
        }
        if row["sound"]:
            item["sound"] = row["sound"]
        if row["text"]:
            item["text"] = row["text"]
            item["text_duration"] = row["text_duration"]
        eff = (row["marry_effect_id"] or row["effect_id"]) if use_marry else row["effect_id"]
        if eff and f"fx_{eff}" in fx_target_by_clip:
            target_fx_id = fx_target_by_clip[f"fx_{eff}"]
            item["command"] = f"start_mtn {target_fx_id} main:fx_{eff}"
        return item

    cf = skin["ctrl_fields"]
    all_aids = list(dict.fromkeys(skin["action_ids"]))
    start_aids = [cf[k] for k in ("MorningGreetings", "NoonGreetings", "EveningGreetings") if k in cf and cf[k] in spine_rows]
    if not start_aids and all_aids:
        start_aids = all_aids[:1]
    start_labels = ("start_morning", "start_noon", "start_evening")
    start_items = []
    for i, aid in enumerate(start_aids):
        lbl = start_labels[i] if i < len(start_labels) else f"start_{i}"
        ent = mk_mtn(aid, True, lbl)
        if submodel_cmd:
            ent["command"] = submodel_cmd
        start_items.append(ent)

    touch_fb = [aid for aid in cf.get("TouchFeedback", []) if aid in spine_rows]
    marry_acts = [aid for aid in cf.get("MarryAction", []) if aid in spine_rows]
    standby_aid = cf.get("StandbyAction") if cf.get("StandbyAction") in spine_rows else None
    pool_chat = [aid for aid in ([standby_aid] if standby_aid else []) + start_aids + touch_fb if aid in spine_rows]
    if not pool_chat:
        pool_chat = [aid for aid in all_aids if aid in spine_rows]

    # Route touch voices strictly by official CfgSoulActionGroupTable Type + semantic body-part guards
    from fix_spine_voice_routing import (
        LEG_NOT_FOOT_RE,
        build_official_stem_index,
        classify_dress_item,
        is_neutral_text,
    )

    with lock_ctx:
        vr_index = getattr(repo, "_voice_routing_index", None)
        if vr_index is None:
            vr_index = build_official_stem_index(repo)
            setattr(repo, "_voice_routing_index", vr_index)
    stem_to_gtypes, aid_to_aname = vr_index

    def _row_stem(aid: int) -> str:
        snd = spine_rows[aid].get("sound", "")
        return Path(snd).stem.lower() if snd else ""

    touch_pool = list(dict.fromkeys(touch_fb + marry_acts)) or list(dict.fromkeys(pool_chat))
    buckets: dict[str, list[int]] = {"head": [], "chest": [], "hand": [], "leg": [], "foot": [], "neutral": []}
    for aid in touch_pool:
        st = _row_stem(aid)
        part, _ = classify_dress_item(st, spine_rows[aid].get("text", ""), aid_to_aname.get(aid, ""), stem_to_gtypes)
        buckets[part if part is not None else "neutral"].append(aid)

    neutral_pool: list[int] = list(buckets["neutral"])
    neutral_seen = set(neutral_pool)

    def _add_neutral(aid: int | None) -> None:
        if aid is None or aid in neutral_seen or aid not in spine_rows:
            return
        if is_neutral_text(spine_rows[aid].get("text", ""), _row_stem(aid)):
            neutral_seen.add(aid)
            neutral_pool.append(aid)

    _add_neutral(standby_aid)
    for aid in touch_pool:
        _add_neutral(aid)
    for aid in start_aids:
        _add_neutral(aid)
    for aid in all_aids:
        _add_neutral(aid)

    def _dedup_aids(aids: list[int]) -> list[int]:
        out: list[int] = []
        seen: set[str] = set()
        for aid in aids:
            key = _row_stem(aid) or str(aid)
            if key not in seen:
                seen.add(key)
                out.append(aid)
        return out

    def _ensure_part(aids: list[int], offset: int) -> list[int]:
        if aids:
            return aids
        if neutral_pool:
            return [neutral_pool[offset % len(neutral_pool)]]
        return touch_pool[:1] if touch_pool else []

    head_aids = _ensure_part(_dedup_aids(buckets["head"]), 0)
    chest_aids = _ensure_part(_dedup_aids(buckets["chest"]), 1)
    lhand_aids = _ensure_part(_dedup_aids(buckets["hand"]), 2)
    rhand_aids = list(reversed(lhand_aids)) if len(lhand_aids) >= 2 else list(lhand_aids)
    leg_aids = _ensure_part(_dedup_aids(buckets["leg"] + buckets["foot"]), 3)
    foot_dedicated = _dedup_aids(buckets["foot"])
    leg_ok_for_foot = [aid for aid in buckets["leg"] if not LEG_NOT_FOOT_RE.search(spine_rows[aid].get("text", ""))]
    foot_aids = _ensure_part(foot_dedicated or _dedup_aids(leg_ok_for_foot), 4)

    reload_cmd = ""
    if submodel_cmd:
        rm_parts = [
            f"remove_submodel {seg.strip().split()[1]}"
            for seg in submodel_cmd.split(";")
            if len(seg.strip().split()) == 3 and seg.strip().split()[0] == "add_submodel"
        ]
        reload_cmd = "; ".join(rm_parts + [submodel_cmd])

    has_marry_anim = any("marry" in a.lower() or "oath" in a.lower() for a in main_anims)
    motions: dict[str, Any] = {
        "idle": [{"name": idle_anim, "file": idle_anim, "fade_in": 10, "fade_out": 10, "file_loop": True}],
        "start": start_items,
        "reload_bg": [{"name": "reload_submodels", "file": idle_anim, **({"command": reload_cmd} if reload_cmd else {})}],
        "闲聊与问答": [mk_mtn(aid, True) for aid in dict.fromkeys(pool_chat)],
        "头": [mk_mtn(aid, True) for aid in head_aids],
        "左手": [mk_mtn(aid, True) for aid in lhand_aids],
        "右手": [mk_mtn(aid, True) for aid in rhand_aids],
        "胸": [mk_mtn(aid, True) for aid in chest_aids],
        "腿": [mk_mtn(aid, True) for aid in leg_aids],
        "足": [mk_mtn(aid, True) for aid in foot_aids],
        "普通模式全动作": [mk_mtn(aid, False, f"normal_{aid}") for aid in all_aids if aid in spine_rows],
    }
    if has_marry_anim:
        motions["誓约模式全动作"] = [mk_mtn(aid, True, f"marry_{aid}") for aid in all_aids if aid in spine_rows]
    if marry_acts:
        motions["誓约专属"] = [mk_mtn(aid, True, f"marry_sp_{aid}") for aid in marry_acts]
    motions = {k: v for k, v in motions.items() if v}

    # 6. Inherit or compute hit_areas
    hit_areas: list[dict[str, Any]] = []
    if bkp_cfg and bkp_cfg.get("hit_areas"):
        for ha in bkp_cfg["hit_areas"]:
            bid = str(ha.get("id", ""))
            mot = str(ha.get("motion", ""))
            if bid in main_bones:
                if mot not in motions:
                    mot = "闲聊与问答" if "闲聊与问答" in motions else "头"
                nha = {
                    "name": ha.get("name", mot),
                    "id": bid,
                    "motion": mot,
                    "width": float(ha.get("width", 1.5)),
                    "height": float(ha.get("height", 1.5)),
                }
                if "center_x" in ha:
                    nha["center_x"] = float(ha["center_x"])
                if "center_y" in ha:
                    nha["center_y"] = float(ha["center_y"])
                hit_areas.append(nha)
    if not hit_areas:
        hit_areas = _compute_fallback_hit_areas(main_parsed, idle_anim, motions)

    cfg = {
        "conf_ver": 1,
        "type": 9,
        "controllers": {
            "param_hit": {},
            "param_loop": {},
            "key_trigger": {
                "enabled": True,
                "items": [
                    {"input": 65, "down_mtn": "闲聊与问答"},  # VK_A
                    {"input": 66, "down_mtn": "头"},          # VK_B
                    {"input": 67, "down_mtn": "左手"},        # VK_C
                    {"input": 68, "down_mtn": "右手"},        # VK_D
                    {"input": 69, "down_mtn": "胸"},          # VK_E
                    {"input": 70, "down_mtn": "腿"},          # VK_F
                    {"input": 71, "down_mtn": "足"},          # VK_G
                    *([{"input": 77, "down_mtn": "誓约模式全动作"}] if has_marry_anim else []),  # VK_M
                    {"input": 78, "down_mtn": "普通模式全动作"},  # VK_N
                    {"input": 82, "down_mtn": "reload_bg"},    # VK_R
                ],
            },
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
        "motions": motions,
        "options": {
            "id": f"{skin['skin_key'].lower()}_main",
            "scale_factor": base_scale,
            "position_x": 0.0,
            "position_y": 0.0,
            "tex_type": 0,
            "edge_padding": False,
            "shader_type": 0,
        },
        "skeleton": main_meta["skeleton"],
        "atlases": [{"atlas": main_meta["atlas"], "tex_names": main_meta["tex_names"], "textures": main_meta["textures"]}],
    }
    write_json(out_dir / ".config.json", cfg)

    return {
        "skin_key": skin["skin_key"],
        "ctrl_ids": skin["merged_ctrl_ids"],
        "char_name": skin["char_name"],
        "dress_name": skin["dress_name"],
        "out_dir": str(out_dir),
        "base_scale": base_scale,
        "submodels": [f"{sid} ({ord_})" for sid, _, ord_ in assigned_subs],
        "wavs_extracted": len(extracted_wavs),
        "bgm": bgm_name or None,
        "hit_areas": len(hit_areas),
        "hit_source": "backup" if (bkp_cfg and bkp_cfg.get("hit_areas") and hit_areas) else "computed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch build SoulTide Live2DViewerEX Spine packages.")
    parser.add_argument("--char", type=str, default="", help="Filter by character name substring")
    parser.add_argument("--ctrl", type=int, action="append", default=[], help="Filter by SpineActionControl ID")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of skins built")
    parser.add_argument("--resume", action="store_true", help="Skip skins that already have .config.json")
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(4, os.cpu_count() or 4)),
        help="Parallel worker threads for AB loading and skin packing",
    )
    args = parser.parse_args()

    repo = FullI18nRepo()
    # Pre-warm lazy Lua table caches & voice-routing index before entering multi-threaded phase
    _ = (repo.spine_actions, repo.cv_map, repo.sound_map, repo.action_groups, repo.action_map)
    from fix_spine_voice_routing import build_official_stem_index
    setattr(repo, "_voice_routing_index", build_official_stem_index(repo))
    catalog = build_skin_catalog(repo)
    if args.char:
        catalog = [s for s in catalog if args.char in s["char_name"]]
    if args.ctrl:
        cset = set(args.ctrl)
        catalog = [s for s in catalog if s["ctrl_id"] in cset or any(c in cset for c in s["merged_ctrl_ids"])]
    if args.limit > 0:
        catalog = catalog[: args.limit]

    indexer = AssetIndexer(workers=args.workers, light=True)
    repos = BatchAssetRepos(indexer, workers=args.workers)

    built_items: list[tuple[int, dict[str, Any]]] = []
    skipped_items: list[tuple[int, str]] = []
    error_items: list[tuple[int, dict[str, Any]]] = []
    work_queue: list[tuple[int, dict[str, Any], str, Path]] = []

    for idx, sk in enumerate(catalog, start=1):
        label = f"{sk['char_name']}/{sk['dress_name']}"
        out_dir = SPINE_OUT_ROOT / sk["char_name"] / sk["dress_name"]

        if args.resume and (out_dir / ".config.json").is_file():
            skipped_items.append((idx, f"{label} (resume existing)"))
            print(f"[{idx}/{len(catalog)}] SKIP {label} (resume existing)", flush=True)
            continue

        work_queue.append((idx, sk, label, out_dir))

    asset_lock = threading.RLock()
    print_lock = threading.Lock()
    total_cat = len(catalog)
    n_workers = max(1, min(args.workers, len(work_queue))) if work_queue else 1
    frame_workers = max(1, min(8, (os.cpu_count() or 4) // 2)) if n_workers == 1 else 1
    print(f"[batch_spine_builder] Building {len(work_queue)} skins (workers={n_workers}, frame_workers={frame_workers})...", flush=True)

    def _run_skin(item: tuple[int, dict[str, Any], str, Path]):
        idx, sk, label, out_dir = item
        try:
            res = build_one_skin(sk, repo, indexer, repos, out_dir, asset_lock=asset_lock, frame_workers=frame_workers)
            with print_lock:
                print(
                    f"[{idx}/{total_cat}] OK {label}: subs={len(res['submodels'])} wav={res['wavs_extracted']} bgm={res['bgm']} ha={res['hit_areas']}({res['hit_source']})",
                    flush=True,
                )
            return ("ok", idx, res)
        except Exception as exc:
            import traceback
            err = {"skin_key": sk["skin_key"], "label": label, "error": str(exc), "trace": traceback.format_exc()}
            with print_lock:
                print(f"[{idx}/{total_cat}] ERROR {label}: {exc}", flush=True)
            return ("err", idx, err)

    if n_workers > 1:
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futs = [ex.submit(_run_skin, it) for it in work_queue]
            for fut in as_completed(futs):
                kind, idx, payload = fut.result()
                if kind == "ok":
                    built_items.append((idx, payload))
                else:
                    error_items.append((idx, payload))
    else:
        for it in work_queue:
            kind, idx, payload = _run_skin(it)
            if kind == "ok":
                built_items.append((idx, payload))
            else:
                error_items.append((idx, payload))

    built = [x[1] for x in sorted(built_items, key=lambda t: t[0])]
    skipped = [x[1] for x in sorted(skipped_items, key=lambda t: t[0])]
    errors = [x[1] for x in sorted(error_items, key=lambda t: t[0])]

    report = {
        "total_catalog_skins": len(catalog),
        "workers": n_workers,
        "built_count": len(built),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "skipped": skipped,
        "errors": errors,
        "built": built,
    }
    write_json(REPORT_PATH, report)
    print(f"[batch_spine_builder] DONE built={len(built)} skipped={len(skipped)} errors={len(errors)} -> {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    main()
