"""Batch Unity 2021.3.34f1 FX Spec Exporter & GPU Recorder Driver for SoulTide.

Parses all 111 Dress Spine entries from Lua config tables (`CfgSoulSpineActionControlTable`,
`CfgSoulSpineActionTable`, `CfgSoulResTable`, `CfgDressTable`, `CfgSoulTable`, `CfgEffectTable`,
`CfgEffectEntityTable`), resolves their `BgPrefabs` (`03_prefabs/ui.ab`, `03_prefabs/art_prefabs.ab`)
and `EffectId` prefabs (`art_prefabs.ab`), extracts full ParticleSystem module specs and textures
from `14_effect/**/*.ab` + `15_shader/**/*.ab`, writes `fx_manifest.json`, and drives a single
GPU batchmode launch of `SoulTideBatchFxUnity` (`Unity.exe -batchmode -quit`, NO `-nographics`).
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import gc
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from soultide_common import CDN_ROOT, DECOMPILED_DIR, LuaTableRepo, load_ab, parse_lua_flat_table, write_json

UNITY_EXE = Path(r"D:\Program Files\Unity\Hub\Editor\2021.3.34f1\Editor\Unity.exe")
UNITY_PROJ = TOOLS_DIR / "SoulTideBatchFxUnity"
TEX_DIR = UNITY_PROJ / "Assets" / "Textures"
MESH_DIR = UNITY_PROJ / "Assets" / "Meshes"
FX_SEQ_ROOT = TOOLS_DIR / "_batch_fx_sequences"
MANIFEST_PATH = UNITY_PROJ / "fx_manifest.json"
DEFAULT_LOG_PATH = UNITY_PROJ / "batch_fx_unity.log"

SKIP_IMAGE_NAMES = {"image_up", "image_down", "image_left", "image_right", "image_lift", "image_top", "image_bottom"}
BLACK_LETTERBOX_CAB = "CAB-74b9d108c9d0a1a5256f5c9547791b74"
BLACK_LETTERBOX_CABS = {
    "CAB-74b9d108c9d0a1a5256f5c9547791b74",
    "CAB-055435a60c36b7081bba8594353412b1",
}
SKIP_LAYOUT_KW = ("shadow", "lift", "limit", "mask", "anim")
INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


def _is_censor_cloud(low_name: str) -> bool:
    """True only for censorship cloud overlays (not character LightCloud = 光明云)."""
    return "souldress_cloud" in low_name or "mainui_cloud" in low_name


class FullI18nRepo(LuaTableRepo):
    """LuaTableRepo extension that recursively resolves `RefId` chains in `CfgI18NTable`."""

    def __init__(self, decompiled_dir: Path = DECOMPILED_DIR) -> None:
        super().__init__(decompiled_dir)
        self._ref_shards: dict[int, dict[int, int]] = {}

    def get_i18n(self, i18n_id: int | None, _depth: int = 0) -> str:
        if not i18n_id or _depth > 8:
            return ""
        val = super().get_i18n(i18n_id)
        if val:
            return val
        if self._i18n_ranges:
            shard = next((idx for lo, hi, idx in self._i18n_ranges if lo <= i18n_id <= hi), None)
            if shard is not None:
                if shard not in self._ref_shards:
                    txt = (self.dir / f"CfgI18NTable_{shard}.lua").read_text(encoding="utf-8", errors="ignore")
                    pat = re.compile(r"\[(\d+)\]\s*=\s*\{\s*Id\s*=\s*\d+,\s*RefId\s*=\s*(\d+)", re.S)
                    self._ref_shards[shard] = {int(m.group(1)): int(m.group(2)) for m in pat.finditer(txt)}
                ref_id = self._ref_shards[shard].get(i18n_id)
                if ref_id:
                    return self.get_i18n(ref_id, _depth + 1)
        return ""


def sanitize_name(s: str) -> str:
    return INVALID_FS_CHARS.sub("_", s.strip())


def build_skin_catalog(repo: FullI18nRepo) -> list[dict[str, Any]]:
    """Build canonical skin catalog across all 111 CfgSoulSpineActionControlTable entries."""
    dress_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgDressTable.lua")
    soul_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgSoulTable.lua")
    res_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgSoulResTable.lua")
    eff_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgEffectTable.lua")
    eff_ent_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgEffectEntityTable.lua")
    elem_ent_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgElementEntityTable.lua")

    soul_names: dict[int, str] = {}
    for sid, body in soul_tbl.items():
        m = re.search(r"Name\s*=\s*getI18NValue\((\d+)\)", body)
        soul_names[sid] = sanitize_name(repo.get_i18n(int(m.group(1)))) if m else f"Soul_{sid}"

    res_to_dress: dict[int, dict[str, Any]] = {}
    for did, body in dress_tbl.items():
        m_srid = re.search(r"SoulResID\s*=\s*(\d+)", body)
        m_sid = re.search(r"SoulID\s*=\s*(\d+)", body)
        m_name = re.search(r"Name\s*=\s*getI18NValue\((\d+)\)", body)
        m_show = re.search(r'DressUnlockShow\s*=\s*"([^"]+)"', body)
        if m_srid:
            srid = int(m_srid.group(1))
            res_to_dress[srid] = {
                "dress_id": did,
                "soul_id": int(m_sid.group(1)) if m_sid else None,
                "dress_name": sanitize_name(repo.get_i18n(int(m_name.group(1)))) if m_name else f"Dress_{did}",
                "unlock_show": m_show.group(1) if m_show else "",
            }

    ctrl_to_res: dict[int, list[int]] = defaultdict(list)
    for rsid, body in res_tbl.items():
        m = re.search(r"SpineActionControl\s*=\s*(\d+)", body)
        if m:
            ctrl_to_res[int(m.group(1))].append(rsid)

    eff_to_prefab: dict[int, str] = {}
    for eid, eb in eff_tbl.items():
        m_ent = re.search(r"EntityID\s*=\s*(\d+)", eb)
        if not m_ent:
            continue
        ent_b = eff_ent_tbl.get(int(m_ent.group(1)), "")
        m_pf = re.search(r'PrefabName\s*=\s*"([^"]+)"', ent_b)
        if m_pf:
            eff_to_prefab[eid] = m_pf.group(1)

    raw_skins: list[dict[str, Any]] = []
    for cid, cbody in sorted(repo.spine_control.items()):
        res_ids = sorted(ctrl_to_res.get(cid, []))
        bg_prefab = ""
        spine_bgm = None
        dress_hit = None
        for rsid in res_ids:
            rb = res_tbl[rsid]
            mb = re.search(r'BgPrefabs\s*=\s*"([^"]+)"', rb)
            if mb:
                bg_prefab = mb.group(1)
            mbgm = re.search(r"SpineBGM\s*=\s*(\d+)", rb)
            if mbgm:
                spine_bgm = int(mbgm.group(1))
            for cand in (rsid, rsid - 1, rsid + 1):
                if cand in res_to_dress:
                    dress_hit = res_to_dress[cand]
                    break

        soul_id = dress_hit["soul_id"] if dress_hit else None
        char_name = soul_names.get(soul_id, f"Soul_{soul_id}")
        dress_name = dress_hit["dress_name"] if dress_hit else f"Ctrl_{cid}"
        unlock_show = dress_hit["unlock_show"] if dress_hit else ""

        # Parse actions referenced by this control
        action_ids: list[int] = []
        ctrl_fields: dict[str, Any] = {}
        for k in ("MorningGreetings", "NoonGreetings", "EveningGreetings", "StandbyAction"):
            m = re.search(rf"{k}\s*=\s*(\d+)", cbody)
            if m:
                aid = int(m.group(1))
                ctrl_fields[k] = aid
                action_ids.append(aid)
        for k in ("TouchFeedback", "MarryAction"):
            m = re.search(rf"{k}\s*=\s*\{{([^}}]+)\}}", cbody)
            if m:
                arr = [int(x) for x in re.findall(r"\d+", m.group(1))]
                ctrl_fields[k] = arr
                action_ids.extend(arr)
        is_change_idle = bool(re.search(r"IsChangeIdle\s*=\s*true", cbody))

        # Collect unique EffectIds & EffectOrders
        eff_ids: list[int] = []
        seen_eff: set[int] = set()
        eff_orders: dict[int, int] = {}
        for aid in action_ids:
            ab = repo.spine_actions.get(aid, "")
            for ek, ok in (("EffectId", "EffectOrder"), ("MarryEffectId", "MarryEffectOrder")):
                me = re.search(rf"{ek}\s*=\s*(\d+)", ab)
                if me:
                    eid = int(me.group(1))
                    mo = re.search(rf"{ok}\s*=\s*(-?\d+)", ab)
                    if mo and eid not in eff_orders:
                        eff_orders[eid] = int(mo.group(1))
                    if eid not in seen_eff and eid in eff_to_prefab:
                        seen_eff.add(eid)
                        eff_ids.append(eid)

        bg_slug = Path(bg_prefab).name.replace("_Background", "")
        m_sa = re.search(r"SoulAction\s*=\s*(\d+)", cbody)
        soul_action_prefab = ""
        if m_sa:
            eb = elem_ent_tbl.get(int(m_sa.group(1)), "")
            m_ep = re.search(r'PrefabName\s*=\s*"([^"]+)"', eb)
            if m_ep:
                soul_action_prefab = m_ep.group(1)
        raw_skins.append({
            "ctrl_id": cid,
            "char_name": char_name,
            "dress_name": dress_name,
            "skin_key": f"{cid}_{bg_slug}",
            "soul_id": soul_id,
            "res_ids": res_ids,
            "bg_prefab": bg_prefab,
            "bg_slug": bg_slug,
            "soul_action_prefab": soul_action_prefab,
            "spine_bgm": spine_bgm,
            "unlock_show": unlock_show,
            "ctrl_fields": ctrl_fields,
            "is_change_idle": is_change_idle,
            "action_ids": action_ids,
            "effect_ids": eff_ids,
            "effect_prefabs": {eid: eff_to_prefab[eid] for eid in eff_ids},
            "effect_orders": {eid: eff_orders.get(eid, 0) for eid in eff_ids},
        })

    # Deduplicate exact (char_name, dress_name) pairs (402/403 Freesia S5, 604/605 Asuna S9)
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for sk in raw_skins:
        key = (sk["char_name"], sk["dress_name"])
        if key not in dedup:
            sk["merged_ctrl_ids"] = [sk["ctrl_id"]]
            dedup[key] = sk
        else:
            dedup[key]["merged_ctrl_ids"].append(sk["ctrl_id"])
            for eid, pf in sk["effect_prefabs"].items():
                if eid not in dedup[key]["effect_prefabs"]:
                    dedup[key]["effect_ids"].append(eid)
                    dedup[key]["effect_prefabs"][eid] = pf
    return list(dedup.values())


class _LazyCabObjMap:
    """Bounded-LRU lazy lookup for (cab_name, path_id) -> UnityPy ObjectReader.

    Prevents holding all 1,039 14_effect/15_shader/04_models UnityPy Environments
    in RAM simultaneously (reducing peak RAM from ~17.2 GB to ~230 MB).
    """

    def __init__(self, max_cached_envs: int = 16) -> None:
        self.static_objs: dict[tuple[str, int], Any] = {}
        self.cab_to_ab: dict[str, Path] = {}
        self._env_cache: dict[Path, dict[tuple[str, int], Any]] = {}
        self._max_cached = max(4, max_cached_envs)

    def __setitem__(self, key: tuple[str, int], val: Any) -> None:
        self.static_objs[key] = val

    def register_cab(self, cab: str, ab_path: Path) -> None:
        self.cab_to_ab.setdefault(cab, ab_path)

    def get(self, key: tuple[str, int], default: Any = None) -> Any:
        if key in self.static_objs:
            return self.static_objs[key]
        cab, pid = key
        ab_path = self.cab_to_ab.get(cab)
        if ab_path is None:
            return default
        if ab_path in self._env_cache:
            obj_map = self._env_cache.pop(ab_path)
            self._env_cache[ab_path] = obj_map
            return obj_map.get(key, default)
        env = load_ab(ab_path)
        obj_map: dict[tuple[str, int], Any] = {}
        for obj in env.objects:
            if obj.type.name in ("Material", "Texture2D", "Shader", "Sprite", "Mesh"):
                obj_map[(obj.assets_file.name, obj.path_id)] = obj
        while len(self._env_cache) >= self._max_cached:
            oldest_key = next(iter(self._env_cache))
            del self._env_cache[oldest_key]
            gc.collect()
        self._env_cache[ab_path] = obj_map
        return obj_map.get(key, default)

    def __getitem__(self, key: tuple[str, int]) -> Any:
        res = self.get(key, None)
        if res is None:
            raise KeyError(key)
        return res

    def __contains__(self, key: tuple[str, int]) -> bool:
        return self.get(key, None) is not None


class AssetIndexer:
    """Indexes Materials, Shaders, Textures, Sprites, SkeletonDataAssets across SoulTide bundles."""

    def __init__(self, workers: int | None = None, light: bool = False) -> None:
        if workers is None:
            workers = max(1, min(8, os.cpu_count() or 4))
        self.workers = max(1, workers)
        self.light = light
        self._envs: list[Any] = []
        self.dress_envs: dict[str, Any] = {}
        self.dress_spine_units: dict[str, tuple[Path, list[str]]] = {}
        self.obj_by_cab_pid: Any = _LazyCabObjMap(max_cached_envs=16)
        self.tex_by_lower: dict[str, Any] = {}
        self.sda_by_cab_pid: dict[tuple[str, int], dict[str, Any]] = {}
        self.shader_blend_cache: dict[tuple[str, int], bool] = {}

        self.ui_env = load_ab(CDN_ROOT / "03_prefabs/ui.ab")
        self.art_env = load_ab(CDN_ROOT / "03_prefabs/art_prefabs.ab")

        if not light:
            fx_abs = [
                ab
                for sub_dir in ("14_effect", "15_shader", "04_models")
                if (CDN_ROOT / sub_dir).exists()
                for ab in sorted((CDN_ROOT / sub_dir).rglob("*.ab"))
            ]
            # Extra bundles referenced by FX materials (alpha masks, noise) and Tween background sprites
            for extra_rel in (
                "common/plugins_util/alphamasking/alphamasking.ab",
                "23_spine/npc/batch1.ab",
                "05_images/image_resources/dress_bg/dressbackground/_batch1.ab",
                "05_images/image_resources/dress_bg/dressbackground/_batch3.ab",
            ):
                ep = CDN_ROOT / extra_rel
                if ep.is_file() and ep not in fx_abs:
                    fx_abs.append(ep)
            print(f"[AssetIndexer] Indexing {len(fx_abs)} bundles across 14_effect/15_shader/04_models+extras (lazy CAB map)...", flush=True)
            cab_cache_path = TOOLS_DIR / "_cab_index_cache.json"
            cab_cache: dict[str, dict[str, Any]] = {}
            if cab_cache_path.exists():
                try:
                    cab_cache = json.loads(cab_cache_path.read_text(encoding="utf-8"))
                except Exception:
                    cab_cache = {}
            cache_dirty = False

            def _scan_fx_ab_cabs(ab_path: Path) -> tuple[Path, list[str]]:
                env = load_ab(ab_path)
                cabs = sorted({obj.assets_file.name for obj in env.objects})
                del env
                return ab_path, cabs

            for i, ab_path in enumerate(fx_abs, 1):
                k = str(ab_path)
                st = ab_path.stat()
                ent = cab_cache.get(k)
                if ent and ent.get("mtime_ns") == st.st_mtime_ns and ent.get("size") == st.st_size:
                    cabs = ent.get("cabs", [])
                else:
                    _, cabs = _scan_fx_ab_cabs(ab_path)
                    cab_cache[k] = {"mtime_ns": st.st_mtime_ns, "size": st.st_size, "cabs": cabs}
                    cache_dirty = True
                    if i % 64 == 0:
                        gc.collect()
                for cab in cabs:
                    self.obj_by_cab_pid.register_cab(cab, ab_path)
            if cache_dirty:
                try:
                    write_json(cab_cache_path, cab_cache)
                except Exception:
                    pass
            gc.collect()

            for p_env in (self.ui_env, self.art_env):
                for obj in p_env.objects:
                    if obj.type.name in ("Material", "Texture2D", "Shader", "Sprite", "Mesh"):
                        cab = obj.assets_file.name
                        self.obj_by_cab_pid[(cab, obj.path_id)] = obj

        dress_abs = sorted((CDN_ROOT / "23_spine/dressspine").glob("*.ab"))
        print(f"[AssetIndexer] Indexing {len(dress_abs)} 23_spine/dressspine SkeletonDataAssets (lightweight)...", flush=True)
        dress_cache_path = TOOLS_DIR / "_dress_sda_cache.json"
        dress_cache: dict[str, dict[str, Any]] = {}
        if dress_cache_path.exists():
            try:
                dress_cache = json.loads(dress_cache_path.read_text(encoding="utf-8"))
            except Exception:
                dress_cache = {}
        dress_cache_dirty = False

        def _scan_dress_ab(ab_path: Path):
            env = load_ab(ab_path)
            c_rev = {v.path_id: k for k, v in (env.container or {}).items()}
            cpaths = [cpath for cpath in (env.container or {}).keys() if cpath.lower().endswith(".skel.bytes")]
            sdas = []
            for obj in env.objects:
                if obj.type.name == "MonoBehaviour":
                    nm = obj.peek_name() or ""
                    if "skeletondata" in nm.lower() or "souldress" in nm.lower() or "cloud" in nm.lower():
                        try:
                            tt = obj.read_typetree()
                            if "skeletonJSON" in tt:
                                jpid = tt["skeletonJSON"].get("m_PathID", 0)
                                sdas.append([
                                    [obj.assets_file.name, int(obj.path_id)],
                                    {
                                        "ab_name": ab_path.name,
                                        "skel_cpath": c_rev.get(jpid, ""),
                                        "sda_name": tt.get("m_Name", ""),
                                        "scale": float(tt.get("scale", 0.01)),
                                    },
                                ])
                        except Exception:
                            pass
            del env
            return ab_path, cpaths, sdas

        for i, ab_path in enumerate(dress_abs, 1):
            k_str = str(ab_path)
            st = ab_path.stat()
            ent = dress_cache.get(k_str)
            if ent and ent.get("mtime_ns") == st.st_mtime_ns and ent.get("size") == st.st_size:
                cpaths = ent.get("cpaths", [])
                sdas = ent.get("sdas", [])
            else:
                _, cpaths, sdas = _scan_dress_ab(ab_path)
                dress_cache[k_str] = {
                    "mtime_ns": st.st_mtime_ns,
                    "size": st.st_size,
                    "cpaths": cpaths,
                    "sdas": sdas,
                }
                dress_cache_dirty = True
                if i % 8 == 0:
                    gc.collect()
            self.dress_spine_units[ab_path.name] = (ab_path, cpaths)
            for k_pair, v in sdas:
                self.sda_by_cab_pid[(k_pair[0], int(k_pair[1]))] = v
        if dress_cache_dirty:
            try:
                write_json(dress_cache_path, dress_cache)
            except Exception:
                pass
        gc.collect()
        self.ui_objs = {o.path_id: o for o in self.ui_env.objects}
        self.art_objs = {o.path_id: o for o in self.art_env.objects}
        self.ui_go_by_name: dict[str, list[int]] = defaultdict(list)
        for o in self.ui_env.objects:
            if o.type.name == "GameObject":
                nm = o.peek_name()
                if nm:
                    self.ui_go_by_name[nm.lower()].append(o.path_id)
        self.art_go_by_name: dict[str, list[int]] = defaultdict(list)
        for o in self.art_env.objects:
            if o.type.name == "GameObject":
                nm = o.peek_name()
                if nm:
                    self.art_go_by_name[nm.lower()].append(o.path_id)
        self.art_container = {k.lower(): v.path_id for k, v in (self.art_env.container or {}).items()}

    def resolve_ext(self, sf, fid: int, pid: int):
        if pid == 0:
            return None
        if fid == 0:
            return sf.objects.get(pid)
        if 1 <= fid <= len(sf.externals):
            cab = Path(sf.externals[fid - 1].path).name
            return self.obj_by_cab_pid.get((cab, pid))
        return None

    def resolve_sda(self, sf, fid: int, pid: int) -> dict[str, Any] | None:
        if pid == 0:
            return None
        if fid == 0:
            return self.sda_by_cab_pid.get((sf.name, pid))
        if 1 <= fid <= len(sf.externals):
            cab = Path(sf.externals[fid - 1].path).name
            return self.sda_by_cab_pid.get((cab, pid))
        return None

    def is_shader_additive(self, shd_obj, shd_name: str, flts: dict[str, float]) -> bool:
        low = shd_name.lower()
        # Only Standard / Standard Unlit shaders drive blend mode dynamically via _DstBlend
        if "standard" in low and "_DstBlend" in flts and flts["_DstBlend"] > 0.5:
            return abs(flts["_DstBlend"] - 1.0) < 0.1
        # Fast explicit check for standard Unity legacy/mobile particle shaders
        if "additive" in low or "_add" in low or "add" in low.split("/"):
            return True
        if "alpha blended" in low or "alphablend" in low or "blended" in low:
            return False
        if shd_obj is not None:
            key = (shd_obj.assets_file.name, shd_obj.path_id)
            if key not in self.shader_blend_cache:
                is_add: bool | None = None
                try:
                    sr = shd_obj.read()
                    pf = getattr(sr, "m_ParsedForm", None)
                    if pf and getattr(pf, "m_SubShaders", None):
                        for ss in pf.m_SubShaders:
                            for pss in getattr(ss, "m_Passes", []):
                                st = getattr(pss, "m_State", None)
                                rt0 = getattr(st, "rtBlend0", None) if st else None
                                dest = getattr(rt0, "destBlend", None) if rt0 else None
                                val = getattr(dest, "val", None) if dest else None
                                if val is not None:
                                    if abs(val - 1.0) < 0.1:
                                        is_add = True
                                        break
                                    if abs(val - 10.0) < 0.1:
                                        is_add = False
                                        break
                            if is_add is not None:
                                break
                except Exception:
                    pass
                if is_add is None:
                    if any(k in low for k in ("blend", "alpha", "rongjie", "dissolution")) and "add" not in low:
                        is_add = False
                    else:
                        is_add = True
                self.shader_blend_cache[key] = is_add
            return self.shader_blend_cache[key]
        return not any(k in low for k in ("blend", "alpha", "rongjie", "dissolution")) or "add" in low


def _qmul(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x1, y1, z1, w1 = a
    x2, y2, z2, w2 = b
    return (
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    )


def _qrot(q: tuple[float, float, float, float], v: tuple[float, float, float]) -> tuple[float, float, float]:
    qx, qy, qz, qw = q
    vx, vy, vz = v
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    return (
        vx + qw * tx + (qy * tz - qz * ty),
        vy + qw * ty + (qz * tx - qx * tz),
        vz + qw * tz + (qx * ty - qy * tx),
    )


def _dump_curve(curve_dict: Any, default_scalar: float = 1.0) -> dict[str, Any]:
    if not isinstance(curve_dict, dict):
        return {"mode": 0, "scalar": float(curve_dict or default_scalar), "minScalar": float(curve_dict or default_scalar), "keys": [], "minKeys": []}
    mc = curve_dict.get("maxCurve", {})
    minc = curve_dict.get("minCurve", {})
    keys = [
        {
            "t": float(k.get("time", 0.0)),
            "v": float(k.get("value", 0.0)),
            "in": float(k.get("inSlope", 0.0)),
            "out": float(k.get("outSlope", 0.0)),
        }
        for k in mc.get("m_Curve", [])
    ]
    min_keys = [
        {
            "t": float(k.get("time", 0.0)),
            "v": float(k.get("value", 0.0)),
            "in": float(k.get("inSlope", 0.0)),
            "out": float(k.get("outSlope", 0.0)),
        }
        for k in minc.get("m_Curve", [])
    ]
    return {
        "mode": int(curve_dict.get("minMaxState", 0)),
        "scalar": float(curve_dict.get("scalar", default_scalar)),
        "minScalar": float(curve_dict.get("minScalar", default_scalar)),
        "keys": keys,
        "minKeys": min_keys,
    }


def _dump_gradient(grad_dict: Any) -> dict[str, Any] | None:
    if not isinstance(grad_dict, dict):
        return None
    mg = grad_dict.get("maxGradient", {})
    nck = int(mg.get("m_NumColorKeys", 0))
    nak = int(mg.get("m_NumAlphaKeys", 0))
    ckeys = []
    for i in range(nck):
        col = mg.get(f"key{i}", {"r": 1.0, "g": 1.0, "b": 1.0})
        t = float(mg.get(f"ctime{i}", 0)) / 65535.0
        ckeys.append({"t": t, "r": float(col.get("r", 1.0)), "g": float(col.get("g", 1.0)), "b": float(col.get("b", 1.0))})
    akeys = []
    for i in range(nak):
        col = mg.get(f"key{i}", {"a": 1.0})
        t = float(mg.get(f"atime{i}", 0)) / 65535.0
        akeys.append({"t": t, "a": float(col.get("a", 1.0))})
    if not ckeys and not akeys:
        return None
    return {"mode": int(grad_dict.get("minMaxState", 0)), "ckeys": ckeys, "akeys": akeys}


def _node_local_tf(
    go,
    objs: dict[int, Any],
    ignore_root_pos: bool = False,
    ignore_root_scale_rot: bool = False,
):
    rt = None
    lx = ly = lz = 0.0
    sx = sy = sz = 1.0
    lq = (0.0, 0.0, 0.0, 1.0)
    is_rect = False
    for c in go.m_Component:
        co = objs.get(c.component.path_id)
        if co and co.type.name in ("RectTransform", "Transform"):
            rt = co.read()
            pos = rt.m_LocalPosition
            sc = rt.m_LocalScale
            lr = rt.m_LocalRotation
            if ignore_root_scale_rot:
                lq = (0.0, 0.0, 0.0, 1.0)
                if max(abs(float(sc.x)), abs(float(sc.y))) > 1.05:
                    sx, sy, sz = 1.0, 1.0, 1.0
                else:
                    sx, sy, sz = float(sc.x), float(sc.y), float(sc.z)
            else:
                lq = (float(lr.x), float(lr.y), float(lr.z), float(lr.w))
                sx, sy, sz = float(sc.x), float(sc.y), float(sc.z)
            if co.type.name == "RectTransform":
                is_rect = True
                ap = rt.m_AnchoredPosition
                lx, ly, lz = (0.0, 0.0, 0.0) if ignore_root_pos else (float(ap.x), float(ap.y), float(pos.z))
            else:
                lx, ly, lz = (0.0, 0.0, 0.0) if ignore_root_pos else (float(pos.x), float(pos.y), float(pos.z))
            break
    return rt, is_rect, (lx, ly, lz), (sx, sy, sz), lq


def resolve_bg_prefab_root(indexer: AssetIndexer, skin: dict[str, Any]) -> tuple[dict[int, Any], int]:
    """Resolve official runtime BgPrefab from art_prefabs.ab (MainUI.lua -> UIGlobalApi.GetElementPrefab).

    NEVER prefer stale editor copies in ui.ab over art_prefabs.ab!
    """
    bgp = skin["bg_prefab"]
    base = Path(bgp).name.lower()
    art_key = f"assets/03_prefabs/art_prefabs/element/{bgp.lower().replace(chr(92), '/')}.prefab"
    art_gid = indexer.art_container.get(art_key)
    if art_gid is None:
        art_gid = next((g for k, g in indexer.art_container.items() if k.endswith(f"/{base}.prefab")), None)
    if art_gid is not None:
        return indexer.art_objs, art_gid
    if base in indexer.art_go_by_name:
        return indexer.art_objs, indexer.art_go_by_name[base][0]
    if base in indexer.ui_go_by_name:
        return indexer.ui_objs, indexer.ui_go_by_name[base][0]
    raise KeyError(f"BgPrefab '{bgp}' not found in art_prefabs.ab or ui.ab")


def resolve_soul_action_entity(indexer: AssetIndexer, skin: dict[str, Any]) -> tuple[dict[int, Any], int] | None:
    """Resolve official runtime SoulAction entity prefab from art_prefabs.ab (SoulSpineCell.ShowSpine)."""
    sa_pf = (skin.get("soul_action_prefab") or "").strip().lower().replace("\\", "/")
    if sa_pf:
        exact_key = f"assets/03_prefabs/art_prefabs/element/{sa_pf}.prefab"
        gid = indexer.art_container.get(exact_key)
        if gid is not None:
            return indexer.art_objs, gid
        for k, g in indexer.art_container.items():
            if sa_pf in k and k.endswith(".prefab"):
                return indexer.art_objs, g
    slug_dir = skin["bg_slug"].lower()
    cand_key = next(
        (k for k in indexer.art_container if f"dressspine/{slug_dir}/souldress_" in k and "_person" not in k and "_bg_" not in k and "_bj_" not in k and "unlock" not in k),
        None,
    )
    if cand_key:
        return indexer.art_objs, indexer.art_container[cand_key]
    return None


def inspect_bg_prefab_layout(
    indexer: AssetIndexer,
    skin: dict[str, Any],
) -> dict[str, Any]:
    """Compute exact UI canvas geometry, Person Spine transform, and FX Point_Root transform
    strictly following SoulTide's official MainUI.LoadSpineBG + SoulSpineCell.ShowSpine runtime."""
    objs, root_gid = resolve_bg_prefab_root(indexer, skin)

    bg_images: list[dict[str, Any]] = []
    limit_edges: dict[str, float] = {}
    person_tf: dict[str, Any] | None = None
    person_order: int | None = None
    fx_point_root_tf: dict[str, Any] | None = None
    point_root_tf: dict[str, Any] | None = None
    spine_scale_parent_tf: dict[str, Any] | None = None
    spine_scale_tf: dict[str, Any] | None = None
    spine_scale_local: tuple[float, float, float] | None = None
    dfs_seq = 0

    def walk(
        gid: int,
        depth: int,
        ppos,
        pscale,
        pq,
        parent_rect_size: tuple[float, float],
        parent_pivot: tuple[float, float],
        path: str,
        in_harm: bool,
        cur_order: int | None,
        from_entity: bool = False,
    ):
        nonlocal person_tf, person_order, fx_point_root_tf, point_root_tf, spine_scale_parent_tf, spine_scale_tf, spine_scale_local, dfs_seq
        go = objs[gid].read()
        nm = go.m_Name
        low = nm.lower()
        cur_path = f"{path}/{nm}" if path else nm
        in_harm_here = in_harm or ("harmonious" in low)

        rt, is_rect, (lx, ly, lz), (sx, sy, sz), lq = _node_local_tf(go, objs, ignore_root_pos=(depth == 0))
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

        canvas_ord: int | None = None
        mono_ord: int | None = None
        if not from_entity:
            for c in go.m_Component:
                co = objs.get(c.component.path_id)
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
            # Runtime truth: SortedComponentOrder always overwrites Canvas.sortingOrder!
            node_order = mono_ord if mono_ord is not None else (canvas_ord if canvas_ord is not None else cur_order)
        else:
            node_order = cur_order

        if not from_entity and depth == 1 and nm == "Point_Root" and go.m_IsActive:
            point_root_tf = {
                "wx": wx, "wy": wy, "wz": wz,
                "wsx": wsx, "wsy": wsy, "wsz": wsz,
                "wq": wq,
                "rect_sz": (rect_w, rect_h) if is_rect else parent_rect_size,
                "piv": (piv_x, piv_y) if is_rect else parent_pivot,
                "sort_order": node_order if node_order is not None else 3,
            }

        if not from_entity and low == "spine_scale" and go.m_IsActive:
            spine_scale_tf = {"wx": wx, "wy": wy, "wsx": wsx, "wsy": wsy, "wq": wq, "sort_order": node_order}
            if depth == 2 and path.endswith("Point_Root"):
                spine_scale_local = (sx, sy, sz)

        if (
            "souldress_" in low
            and not any(k in low for k in ("_person", "_bg_", "_bj_", "_tree", "_prop", "_fx", "hitarea"))
            and not _is_censor_cloud(low)
            and not re.search(r"_\d+$", low)
        ):
            in_pr_chain = ("point_root" in path.lower() or "spine_scale" in path.lower())
            if spine_scale_parent_tf is None or (in_pr_chain and not spine_scale_parent_tf.get("in_pr_chain")):
                spine_scale_parent_tf = {
                    "wx": wx,
                    "wy": wy,
                    "wsx": wsx,
                    "wsy": wsy,
                    "wq": wq,
                    "in_pr_chain": in_pr_chain,
                    "sort_order": node_order,
                }

        if go.m_IsActive and is_rect and "limit" in path.lower():
            w_lim = rect_w * abs(wsx)
            h_lim = rect_h * abs(wsy)
            if w_lim > 1.0 and h_lim > 1.0:
                if low in ("image_left", "image_lift"):
                    limit_edges["x0"] = img_cx + w_lim / 2.0
                elif low == "image_right":
                    limit_edges["x1"] = img_cx - w_lim / 2.0
                elif low in ("image_up", "image_top"):
                    limit_edges["y1"] = img_cy - h_lim / 2.0
                elif low in ("image_down", "image_bottom"):
                    limit_edges["y0"] = img_cy + h_lim / 2.0

        if go.m_IsActive and not in_harm_here and "hitarea" not in path.lower() and "cv_point" not in low:
            for c in go.m_Component:
                co = objs.get(c.component.path_id)
                if not co or co.type.name != "MonoBehaviour":
                    continue
                try:
                    tt = co.read_typetree()
                    if "m_Sprite" in tt and low not in SKIP_IMAGE_NAMES:
                        sref = tt["m_Sprite"]
                        fid, pid = sref.get("m_FileID", 0), sref.get("m_PathID", 0)
                        cab = co.assets_file.name if fid == 0 else (Path(co.assets_file.externals[fid - 1].path).name if 1 <= fid <= len(co.assets_file.externals) else "")
                        if pid == 0 or cab in BLACK_LETTERBOX_CABS:
                            continue
                        w_px = rect_w * abs(wsx) if is_rect else 0.0
                        h_px = rect_h * abs(wsy) if is_rect else 0.0
                        if w_px > 1.0 and h_px > 1.0:
                            dfs_seq += 1
                            bg_images.append({"name": nm, "wx": img_cx, "wy": img_cy, "w": w_px, "h": h_px, "pid": pid, "z_deg": z_deg})
                    elif (
                        "skeletonDataAsset" in tt
                        and "person" in low
                        and not _is_censor_cloud(low)
                        and not any(t in low for t in ("_bg_", "_bj_"))
                    ):
                        sref = tt["skeletonDataAsset"]
                        sda = indexer.resolve_sda(co.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
                        sn = objs[tt["m_Script"]["m_PathID"]].peek_name() if tt.get("m_Script", {}).get("m_PathID") in objs else ""
                        is_graphic = "Graphic" in sn
                        sda_sc = sda["scale"] if sda else 0.01
                        mult = 100.0 if is_graphic else 1.0
                        ui_per_spine_x = abs(wsx) * sda_sc * mult
                        ui_per_spine_y = abs(wsy) * sda_sc * mult
                        dfs_seq += 1
                        person_tf = {
                            "wx": wx,
                            "wy": wy,
                            "ui_per_spine": ui_per_spine_x,
                            "ui_per_spine_x": ui_per_spine_x,
                            "ui_per_spine_y": ui_per_spine_y,
                            "wsx": wsx,
                            "wsy": wsy,
                            "z_deg": round(z_deg, 4),
                            "sort_order": node_order if node_order is not None else 3,
                            "dfs": dfs_seq,
                        }
                        if node_order is not None:
                            person_order = node_order
                except Exception:
                    pass

        # Capture Point_Root inside SoulDress_<Char> even when inactive (used as FX_UI spawn anchor!)
        if low == "point_root" and (from_entity or (depth >= 2 and "souldress_" in path.lower())):
            fx_point_root_tf = {"wx": wx, "wy": wy, "wz": wz, "wsx": wsx, "wsy": wsy, "wsz": wsz, "wq": wq}

        if rt and hasattr(rt, "m_Children"):
            child_parent_sz = (rect_w, rect_h) if is_rect else parent_rect_size
            child_parent_piv = (piv_x, piv_y) if is_rect else parent_pivot
            for ch in rt.m_Children:
                if ch.path_id in objs:
                    walk(
                        objs[ch.path_id].read().m_GameObject.path_id,
                        depth + 1,
                        (wx, wy, wz),
                        (wsx, wsy, wsz),
                        wq,
                        child_parent_sz,
                        child_parent_piv,
                        cur_path,
                        in_harm_here,
                        node_order,
                        from_entity=from_entity,
                    )

    walk(root_gid, 0, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (1700.0, 750.0), (0.5, 0.5), "", False, None, from_entity=False)

    # Official SoulTide runtime: spawn SoulAction entity at Vector3.zero under Point_Root -> SpineRoot(Spine_Scale.localScale)
    if person_tf is None or fx_point_root_tf is None:
        ent_res = resolve_soul_action_entity(indexer, skin)
        if ent_res is not None:
            ent_objs, ent_gid = ent_res
            old_objs = objs
            objs = ent_objs
            if point_root_tf is not None:
                ss_sx, ss_sy, ss_sz = spine_scale_local if spine_scale_local is not None else (0.1, 0.1, 1.0)
                walk(
                    ent_gid,
                    0,
                    (point_root_tf["wx"], point_root_tf["wy"], point_root_tf["wz"]),
                    (point_root_tf["wsx"] * ss_sx, point_root_tf["wsy"] * ss_sy, point_root_tf["wsz"] * ss_sz),
                    point_root_tf["wq"],
                    point_root_tf["rect_sz"],
                    point_root_tf["piv"],
                    "Point_Root/SoulSpineCell/SpineRoot",
                    False,
                    point_root_tf["sort_order"],
                    from_entity=True,
                )
            else:
                base_tf = spine_scale_parent_tf or spine_scale_tf or {"wx": 0.0, "wy": 0.0, "wsx": 1.0, "wsy": 1.0, "wq": (0.0, 0.0, 0.0, 1.0), "sort_order": 3}
                walk(
                    ent_gid,
                    0,
                    (base_tf["wx"], base_tf["wy"], 0.0),
                    (base_tf["wsx"], base_tf["wsy"], 1.0),
                    base_tf["wq"],
                    (1700.0, 750.0),
                    (0.5, 0.5),
                    "Point_Root/SoulSpineCell/SpineRoot",
                    False,
                    base_tf.get("sort_order", 3),
                    from_entity=True,
                )
            objs = old_objs

    # Determine canvas center & size from centered full-width backdrop layers (unioning adjacent sky/ground strips)
    real_imgs = [
        im for im in bg_images
        if not any(k in im["name"].lower() for k in SKIP_LAYOUT_KW)
        and abs(im["wx"]) < 600.0 and abs(im["wy"]) < 600.0
    ]
    full_w = [im for im in real_imgs if im["w"] >= 1400.0 and im["h"] >= 350.0]
    tall_full = [im for im in full_w if im["h"] >= 850.0]

    canvas_w, canvas_h = 1700, 1132
    cam_x, cam_y = 0.0, 0.0
    if tall_full:
        main_bg = max(
            tall_full,
            key=lambda x: (
                round(x["w"] * min(x["h"], 1700.0), -3),
                -(abs(x["wx"]) + abs(x["wy"])),
            ),
        )
        x0 = main_bg["wx"] - main_bg["w"] / 2.0
        x1 = main_bg["wx"] + main_bg["w"] / 2.0
        y0 = main_bg["wy"] - main_bg["h"] / 2.0
        y1 = main_bg["wy"] + main_bg["h"] / 2.0
        for im in full_w:
            if abs(im["wx"] - main_bg["wx"]) < 150.0 and im["w"] >= main_bg["w"] * 0.9:
                iy0, iy1 = im["wy"] - im["h"] / 2.0, im["wy"] + im["h"] / 2.0
                if iy0 <= y1 + 10.0 and iy1 >= y0 - 10.0:
                    ny0, ny1 = min(y0, iy0), max(y1, iy1)
                    if ny1 - ny0 <= 1700.0:
                        y0, y1 = ny0, ny1
        cam_x = (x0 + x1) / 2.0
        cam_y = (y0 + y1) / 2.0
        canvas_w = max(1280, min(2560, int(round((x1 - x0) / 2.0) * 2)))
        canvas_h = max(720, min(1700, int(round((y1 - y0) / 2.0) * 2)))
    elif full_w:
        anchor = min(full_w, key=lambda x: abs(x["wx"]) + abs(x["wy"]))
        x0, x1 = anchor["wx"] - anchor["w"] / 2.0, anchor["wx"] + anchor["w"] / 2.0
        y0, y1 = anchor["wy"] - anchor["h"] / 2.0, anchor["wy"] + anchor["h"] / 2.0
        for im in full_w:
            if abs(im["wx"] - anchor["wx"]) < 150.0:
                iy0, iy1 = im["wy"] - im["h"] / 2.0, im["wy"] + im["h"] / 2.0
                if max(y0, iy0) <= min(y1, iy1) + 50.0:
                    y0, y1 = min(y0, iy0), max(y1, iy1)
        cam_x = (x0 + x1) / 2.0
        cam_y = (y0 + y1) / 2.0
        canvas_w = max(1280, min(2560, int(round((x1 - x0) / 2.0) * 2)))
        canvas_h = max(720, min(1700, int(round((y1 - y0) / 2.0) * 2)))
    elif bg_images:
        main_bg = max(bg_images, key=lambda x: x["w"] * x["h"])
        cam_x, cam_y = float(main_bg["wx"]), float(main_bg["wy"])

    if person_tf is None:
        person_tf = {
            "wx": 0.0,
            "wy": -450.0,
            "ui_per_spine": 0.5,
            "ui_per_spine_x": 0.5,
            "ui_per_spine_y": 0.5,
            "wsx": 50.0,
            "wsy": 50.0,
            "z_deg": 0.0,
            "sort_order": 3,
            "dfs": 999999,
        }
    if fx_point_root_tf is None:
        fx_point_root_tf = {
            "wx": person_tf["wx"],
            "wy": person_tf["wy"],
            "wz": 0.0,
            "wsx": person_tf["ui_per_spine"],
            "wsy": person_tf["ui_per_spine"],
            "wsz": person_tf["ui_per_spine"],
            "wq": (0.0, 0.0, 0.0, 1.0),
        }

    return {
        "canvas_w": canvas_w,
        "canvas_h": canvas_h,
        "cam_x": round(cam_x, 4),
        "cam_y": round(cam_y, 4),
        "limit_rect": limit_edges,
        "person": person_tf,
        "person_order": person_order,
        "fx_point_root": fx_point_root_tf,
    }


def _save_tex_env(
    indexer: AssetIndexer,
    mobj,
    tex_envs: list[Any],
    keys: tuple[str, ...],
    saved_textures: set[str],
    fallback_non_mask: bool = False,
    tex_wrap_modes: dict[str, list[int]] | None = None,
) -> tuple[str, list[float], list[float], list[int]]:
    chosen_tv = None
    for preferred in keys:
        for tk, tv in tex_envs:
            if tk == preferred and tv.get("m_Texture", {}).get("m_PathID", 0) != 0:
                chosen_tv = tv
                break
        if chosen_tv is not None:
            break
    if chosen_tv is None and fallback_non_mask:
        for tk, tv in tex_envs:
            if "mask" not in tk.lower() and tv.get("m_Texture", {}).get("m_PathID", 0) != 0:
                chosen_tv = tv
                break
    if chosen_tv is None:
        return "", [1.0, 1.0], [0.0, 0.0], [0, 0]

    ts = chosen_tv.get("m_Scale", {})
    to = chosen_tv.get("m_Offset", {})
    scale = [float(ts.get("x", 1.0)), float(ts.get("y", 1.0))]
    offset = [float(to.get("x", 0.0)), float(to.get("y", 0.0))]
    tref = chosen_tv.get("m_Texture", {})
    tobj = indexer.resolve_ext(mobj.assets_file, tref.get("m_FileID", 0), tref.get("m_PathID", 0))
    if tobj is None or tobj.type.name != "Texture2D":
        return "", scale, offset, [0, 0]
    tname = tobj.peek_name() or f"tex_{tobj.path_id}"
    wrap_uv = [0, 0]
    try:
        ttt = tobj.read_typetree()
        tset = ttt.get("m_TextureSettings") or {}
        wu = int(tset.get("m_WrapU", tset.get("m_WrapMode", 0)))
        wv = int(tset.get("m_WrapV", tset.get("m_WrapMode", 0)))
        wrap_uv = [wu, wv]
    except Exception:
        wrap_uv = [0, 0]
    if tex_wrap_modes is not None and tname:
        # Preserve original Clamp (1) if seen on this texture, or record first exact setting
        prev = tex_wrap_modes.get(tname)
        if prev is None:
            tex_wrap_modes[tname] = list(wrap_uv)
        else:
            # Prefer exact original setting from Texture2D asset (identical for same texture asset)
            tex_wrap_modes[tname] = list(wrap_uv)
    if tname not in saved_textures:
        TEX_DIR.mkdir(parents=True, exist_ok=True)
        out_png = TEX_DIR / f"{tname}.png"
        if not out_png.exists():
            tobj.read().image.convert("RGBA").save(out_png, "PNG")
        saved_textures.add(tname)
    return tname, scale, offset, wrap_uv


def _extract_material_dto(
    indexer: AssetIndexer,
    assets_file,
    mref: dict[str, Any] | None,
    saved_textures: set[str],
    tex_wrap_modes: dict[str, list[int]] | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """Extract shader-validated tint, intensity/alpha, textures, mask2, dissolve, distort, and UV scroll."""
    if not mref or int(mref.get("m_PathID", 0)) == 0:
        return None, False
    mobj = indexer.resolve_ext(assets_file, mref.get("m_FileID", 0), mref.get("m_PathID", 0))
    if not mobj:
        return None, False

    mtt = mobj.read_typetree()
    mat_name = mtt.get("m_Name", "")
    sp = mtt.get("m_SavedProperties", {})
    flts = {fk: float(fv) for fk, fv in sp.get("m_Floats", [])}
    cols = {ck: cv for ck, cv in sp.get("m_Colors", [])}
    tex_envs = sp.get("m_TexEnvs", [])

    sref = mtt.get("m_Shader", {})
    sobj = indexer.resolve_ext(mobj.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
    shd_name = ""
    decl_props: set[str] = set()
    if sobj:
        try:
            sr = sobj.read()
            pf = getattr(sr, "m_ParsedForm", None)
            if pf is not None:
                shd_name = getattr(pf, "m_Name", "") or (sobj.peek_name() or "")
                pi = getattr(pf, "m_PropInfo", None)
                if pi is not None:
                    for p in getattr(pi, "m_Props", []) or []:
                        pn = getattr(p, "m_Name", "")
                        if pn:
                            decl_props.add(pn)
            else:
                shd_name = sobj.peek_name() or ""
        except Exception:
            shd_name = sobj.peek_name() or ""

    shd_low = shd_name.lower()
    skip_distort = any(k in shd_low for k in ("niuqu", "distort", "fakerefraction"))
    is_add = indexer.is_shader_additive(sobj, shd_name, flts)

    # Resolve tint color using only shader-declared properties (avoids stale leftover _TintColor / _Intensity)
    tint = {"r": 0.5, "g": 0.5, "b": 0.5, "a": 0.5}
    def _declared(prop: str) -> bool:
        return (not decl_props) or (prop in decl_props)

    color_picked = False
    for ckey in ("_Color", "_Main_color", "_MainColor", "_color"):
        if ckey in cols and (ckey in decl_props or ("_TintColor" not in decl_props and not decl_props)):
            c_raw = cols[ckey]
            tint = {
                "r": float(c_raw.get("r", 1.0)) * 0.5,
                "g": float(c_raw.get("g", 1.0)) * 0.5,
                "b": float(c_raw.get("b", 1.0)) * 0.5,
                "a": float(c_raw.get("a", 1.0)) * 0.5,
            }
            color_picked = True
            break
    if not color_picked and "_TintColor" in cols and _declared("_TintColor"):
        c_raw = cols["_TintColor"]
        tint = {
            "r": float(c_raw.get("r", 0.5)),
            "g": float(c_raw.get("g", 0.5)),
            "b": float(c_raw.get("b", 0.5)),
            "a": float(c_raw.get("a", 0.5)),
        }
        color_picked = True
    if not color_picked:
        for ckey in ("_Color", "_Main_color", "_MainColor", "_color"):
            if ckey in cols:
                c_raw = cols[ckey]
                tint = {
                    "r": float(c_raw.get("r", 1.0)) * 0.5,
                    "g": float(c_raw.get("g", 1.0)) * 0.5,
                    "b": float(c_raw.get("b", 1.0)) * 0.5,
                    "a": float(c_raw.get("a", 1.0)) * 0.5,
                }
                break

    tint_mul = 1.0
    for fkey in ("_qiangdu", "_Intensity", "_Brightness"):
        if fkey in flts and fkey in decl_props:
            tint_mul = max(0.0, min(8.0, float(flts[fkey])))
            break
    for akey in ("_Alphe", "_Alpha"):
        if akey in flts and akey in decl_props:
            tint["a"] = max(0.0, min(4.0, tint["a"] * max(0.0, min(8.0, float(flts[akey])))))
            break

    tex_name, tex_scale, tex_offset, tex_wrap = _save_tex_env(
        indexer, mobj, tex_envs,
        ("_MainTex", "_Texture", "_Dffuse", "_Main_tex", "_Diffuse", "_Main_Tex", "_BaseTex", "_Tex"),
        saved_textures, fallback_non_mask=True, tex_wrap_modes=tex_wrap_modes,
    )
    mask_name, mask_scale, mask_offset, mask_wrap = _save_tex_env(
        indexer, mobj, tex_envs,
        ("_Mask", "_mask", "_MaskTex", "_mask_1", "_SoftMask"),
        saved_textures, tex_wrap_modes=tex_wrap_modes,
    )
    mask2_name, mask2_scale, mask2_offset, mask2_wrap = _save_tex_env(
        indexer, mobj, tex_envs,
        ("_mask02", "_Mask02", "_MaskTex2"),
        saved_textures, tex_wrap_modes=tex_wrap_modes,
    )
    diss_name, diss_scale, diss_offset, diss_wrap = _save_tex_env(
        indexer, mobj, tex_envs,
        ("_Rongjie_tietu",),
        saved_textures, tex_wrap_modes=tex_wrap_modes,
    )
    dist_name, dist_scale, dist_offset, dist_wrap = _save_tex_env(
        indexer, mobj, tex_envs,
        ("_Raodong_tex", "_NoiseTex"),
        saved_textures, tex_wrap_modes=tex_wrap_modes,
    )

    dissolve = float(flts.get("_Rongjie", 0.0)) if ("_Rongjie" in decl_props and diss_name) else 0.0
    dissolve_soft = max(0.01, float(flts.get("_Ruanying", 0.5))) if "_Ruanying" in decl_props else 0.5
    distort_strength = float(flts.get("_G_Raodong_qiangdu", 0.0)) if ("_G_Raodong_qiangdu" in decl_props and dist_name) else 0.0
    custom_data_flag = bool(flts.get("_offon", 0.0) > 0.5)

    uv_t = cols.get("_UV_t", {}) if "_UV_t" in decl_props else {}
    rd_uv = cols.get("_Rongdong_UV", {}) if "_Rongdong_UV" in decl_props else {}
    uv_scroll = [
        float(uv_t.get("r", 0.0)),
        float(uv_t.get("g", 0.0)),
        float(flts.get("_Mask_U", 0.0)) if "_Mask_U" in decl_props else 0.0,
        float(flts.get("_Mask_V", 0.0)) if "_Mask_V" in decl_props else 0.0,
        float(uv_t.get("b", 0.0)),
        float(uv_t.get("a", 0.0)),
        float(rd_uv.get("r", 0.0)),
        float(rd_uv.get("g", 0.0)),
    ]

    return {
        "matName": mat_name,
        "shaderName": shd_name,
        "customDataFlag": custom_data_flag,
        "texName": tex_name,
        "texScale": tex_scale,
        "texOffset": tex_offset,
        "texWrap": tex_wrap,
        "maskTexName": mask_name,
        "maskScale": mask_scale,
        "maskOffset": mask_offset,
        "maskWrap": mask_wrap,
        "mask2TexName": mask2_name,
        "mask2Scale": mask2_scale,
        "mask2Offset": mask2_offset,
        "mask2Wrap": mask2_wrap,
        "dissolveTexName": diss_name,
        "dissolveScale": diss_scale,
        "dissolveOffset": diss_offset,
        "dissolveWrap": diss_wrap,
        "dissolve": dissolve,
        "dissolveSoft": dissolve_soft,
        "distortTexName": dist_name,
        "distortScale": dist_scale,
        "distortOffset": dist_offset,
        "distortWrap": dist_wrap,
        "distortStrength": distort_strength,
        "uvScroll": uv_scroll,
        "isAdditive": is_add,
        "tint": tint,
        "tintMultiplier": tint_mul,
    }, skip_distort


def _resolve_mesh_name(
    indexer: AssetIndexer,
    assets_file,
    mref: dict[str, Any] | None,
    saved_meshes: set[str],
) -> str:
    """Resolve custom Mesh object (exporting unique .obj) or Unity builtin primitive."""
    if not mref:
        return ""
    fid = int(mref.get("m_FileID", 0))
    pid = int(mref.get("m_PathID", 0))
    if pid == 0:
        return ""
    if pid == 10210:
        return "BUILTIN_QUAD"
    if pid == 10209:
        return "BUILTIN_PLANE"
    if pid == 10202:
        return "BUILTIN_CUBE"

    mobj = indexer.resolve_ext(assets_file, fid, pid)
    if mobj is None or mobj.type.name != "Mesh":
        return ""
    m = mobj.read()
    mname = sanitize_name(getattr(m, "m_Name", "") or f"mesh_{abs(pid)}")
    unique_stem = f"{mname}_{abs(pid) % 100000000:08d}"
    if unique_stem not in saved_meshes:
        MESH_DIR.mkdir(parents=True, exist_ok=True)
        out_obj = MESH_DIR / f"{unique_stem}.obj"
        if not out_obj.exists():
            obj_txt = m.export()
            if obj_txt and "v " in obj_txt:
                out_obj.write_text(obj_txt, encoding="utf-8")
            else:
                return ""
        saved_meshes.add(unique_stem)
    return unique_stem


def _extract_ps_nodes(
    indexer: AssetIndexer,
    objs: dict[int, Any],
    root_gid: int,
    base_pos: tuple[float, float, float],
    base_scale: tuple[float, float, float],
    base_rot: tuple[float, float, float, float],
    saved_textures: set[str],
    skip_harmonious: bool = True,
    saved_meshes: set[str] | None = None,
    ignore_root_scale_rot: bool = False,
    person_order: int | None = None,
    fixed_layer: str | None = None,
    tex_wrap_modes: dict[str, list[int]] | None = None,
) -> list[dict[str, Any]]:
    """Walk prefab tree from root_gid and serialize all active ParticleSystems."""
    if saved_meshes is None:
        saved_meshes = set()
    nodes: list[dict[str, Any]] = []
    seen_person = False
    dfs_counter = 0

    def walk(gid: int, ppos, pscale, pq, depth: int, in_harm: bool, cur_path: str, cur_order: int | None):
        nonlocal seen_person, dfs_counter
        go = objs[gid].read()
        if not go.m_IsActive:
            return
        low = go.m_Name.lower()
        in_harm_here = in_harm or ("harmonious" in low)
        if skip_harmonious and in_harm_here:
            return
        next_path = f"{cur_path}/{go.m_Name}" if cur_path else go.m_Name

        rt, _, (lx, ly, lz), (sx, sy, sz), lq = _node_local_tf(
            go, objs, ignore_root_pos=(depth == 0), ignore_root_scale_rot=(depth == 0 and ignore_root_scale_rot)
        )
        rx, ry, rz = _qrot(pq, (lx * pscale[0], ly * pscale[1], lz * pscale[2]))
        wx, wy, wz = ppos[0] + rx, ppos[1] + ry, ppos[2] + rz
        wsx, wsy, wsz = pscale[0] * sx, pscale[1] * sy, pscale[2] * sz
        wq = _qmul(pq, lq)

        # Official SoulTide runtime: SortedComponentOrder strictly overrides Canvas.sortingOrder
        # regardless of component array order on the GameObject!
        mono_ord: int | None = None
        canv_ord: int | None = None
        sg_ord: int | None = None
        for c in go.m_Component:
            co = objs.get(c.component.path_id)
            if not co:
                continue
            if co.type.name == "Canvas":
                try:
                    ctt = co.read_typetree()
                    if ctt.get("m_OverrideSorting") or int(ctt.get("m_SortingOrder", 0)) != 0:
                        canv_ord = int(ctt.get("m_SortingOrder", 0))
                except Exception:
                    pass
                continue
            if co.type.name == "SortingGroup":
                try:
                    stt = co.read_typetree()
                    sg_ord = int(stt.get("m_SortingOrder", 0))
                except Exception:
                    pass
                continue
            if co.type.name != "MonoBehaviour":
                continue
            try:
                tt = co.read_typetree()
                if "Order" in tt and ("fixDrawOrder" in tt or "UIRootCanvas" in tt) and tt.get("m_Enabled", 1):
                    mono_ord = int(tt["Order"])
                elif "skeletonDataAsset" in tt and "person" in low and "cloud" not in low and not any(t in low for t in ("_bg_", "_bj_")):
                    seen_person = True
            except Exception:
                pass
        node_order = (
            mono_ord if mono_ord is not None
            else (sg_ord if sg_ord is not None else (canv_ord if canv_ord is not None else cur_order))
        )

        for c in go.m_Component:
            co = objs.get(c.component.path_id)
            if not co or co.type.name != "ParticleSystem":
                continue
            tt = co.read_typetree()
            em = tt.get("EmissionModule", {})
            if not em.get("enabled"):
                continue

            init = tt.get("InitialModule", {})
            sh = tt.get("ShapeModule", {})
            col_m = tt.get("ColorModule", {})
            sz_m = tt.get("SizeModule", {})
            vel_m = tt.get("VelocityModule", {})
            lim_m = tt.get("ClampVelocityModule", {})
            sub_m = tt.get("SubModule", {})
            rot_m = tt.get("RotationModule", {})
            rot_spd_m = tt.get("RotationBySpeedModule", {})
            noise_m = tt.get("NoiseModule", {})
            force_m = tt.get("ForceModule", {})
            uv_m = tt.get("UVModule", {})
            trail_m = tt.get("TrailModule", {})
            cd_m = tt.get("CustomDataModule", {})

            scaling_mode = int(tt.get("scalingMode", 0))
            if scaling_mode == 1:
                # Unity ParticleSystemScalingMode.Local ignores parent/Canvas (~1/37.5) scale -> 37.5 UI px per unit;
                # if local scale is already authored in UI px (> 5.0), keep 1.0x to avoid 100x explosion (e.g. Benten_S4).
                if max(abs(sx), abs(sy)) > 5.0:
                    eff_scale = [sx, sy, sz]
                else:
                    eff_scale = [sx * 37.5, sy * 37.5, sz * 37.5]
            else:
                eff_scale = [wsx, wsy, wsz]
            if abs(eff_scale[2]) < 1e-4:
                eff_scale[2] = 1.0

            trails_enabled = bool(trail_m.get("enabled", False))
            has_main_mat = False
            main_dto: dict[str, Any] = {
                "matName": "",
                "shaderName": "",
                "customDataFlag": False,
                "texName": "",
                "texScale": [1.0, 1.0],
                "texOffset": [0.0, 0.0],
                "texWrap": [0, 0],
                "maskTexName": "",
                "maskScale": [1.0, 1.0],
                "maskOffset": [0.0, 0.0],
                "maskWrap": [0, 0],
                "mask2TexName": "",
                "mask2Scale": [1.0, 1.0],
                "mask2Offset": [0.0, 0.0],
                "mask2Wrap": [0, 0],
                "dissolveTexName": "",
                "dissolveScale": [1.0, 1.0],
                "dissolveOffset": [0.0, 0.0],
                "dissolveWrap": [0, 0],
                "dissolve": 0.0,
                "dissolveSoft": 0.5,
                "distortTexName": "",
                "distortScale": [1.0, 1.0],
                "distortOffset": [0.0, 0.0],
                "distortWrap": [0, 0],
                "distortStrength": 0.0,
                "uvScroll": [0.0] * 8,
                "isAdditive": True,
                "tint": {"r": 0.5, "g": 0.5, "b": 0.5, "a": 0.5},
                "tintMultiplier": 1.0,
            }
            trail_dto: dict[str, Any] = dict(main_dto)
            has_trail_mat = False
            skip_distort = False
            sort_order = 0
            render_mode = 0
            render_align = 0
            max_particle_size = 0.5
            mesh_name = ""
            vel_scale = 0.0
            len_scale = 2.0
            pivot = [0.0, 0.0, 0.0]
            flip = [0.0, 0.0, 0.0]

            for c2 in go.m_Component:
                co2 = objs.get(c2.component.path_id)
                if not co2 or co2.type.name != "ParticleSystemRenderer":
                    continue
                psr = co2.read_typetree()
                sort_order = int(psr.get("m_SortingOrder", 0))
                render_mode = int(psr.get("m_RenderMode", 0))
                render_align = int(psr.get("m_RenderAlignment", 0))
                max_particle_size = float(psr.get("m_MaxParticleSize", 0.5))
                vel_scale = float(psr.get("m_VelocityScale", 0.0))
                len_scale = float(psr.get("m_LengthScale", 2.0))
                pv = psr.get("m_Pivot", {})
                pivot = [float(pv.get("x", 0.0)), float(pv.get("y", 0.0)), float(pv.get("z", 0.0))]
                fl = psr.get("m_Flip", {})
                flip = [float(fl.get("x", 0.0)), float(fl.get("y", 0.0)), float(fl.get("z", 0.0))]

                if render_mode == 4:
                    mesh_name = _resolve_mesh_name(indexer, co2.assets_file, psr.get("m_Mesh"), saved_meshes)

                mrefs = psr.get("m_Materials", [])
                if mrefs:
                    md, sk_d = _extract_material_dto(indexer, co2.assets_file, mrefs[0], saved_textures, tex_wrap_modes=tex_wrap_modes)
                    if md is not None:
                        has_main_mat = True
                        main_dto = md
                        skip_distort = sk_d
                if trails_enabled:
                    tref = mrefs[1] if len(mrefs) > 1 else (mrefs[0] if mrefs else None)
                    td, _ = _extract_material_dto(indexer, co2.assets_file, tref, saved_textures, tex_wrap_modes=tex_wrap_modes)
                    if td is not None:
                        has_trail_mat = True
                        trail_dto = td

            if skip_distort or (not has_main_mat and not (trails_enabled and has_trail_mat)):
                continue

            uv_fot = uv_m.get("frameOverTime", {})
            uv_fot_keys = [
                {
                    "t": float(k.get("time", 0.0)),
                    "v": float(k.get("value", 0.0)),
                    "in": float(k.get("inSlope", 0.0)),
                    "out": float(k.get("outSlope", 0.0)),
                }
                for k in uv_fot.get("maxCurve", {}).get("m_Curve", [])
            ]
            sh_rot = sh.get("m_Rotation", {})
            sh_pos = sh.get("m_Position", {})
            sh_box = sh.get("m_Scale", {})
            sc_mod = init.get("startColor", {})
            rate_curve = _dump_curve(em.get("rateOverTime", {}), 0.0)
            rate_dist_curve = _dump_curve(em.get("rateOverDistance", {}), 0.0)
            vel_x_c = _dump_curve(vel_m.get("x", {}), 0.0) if vel_m.get("enabled") else None
            vel_y_c = _dump_curve(vel_m.get("y", {}), 0.0) if vel_m.get("enabled") else None
            vel_z_c = _dump_curve(vel_m.get("z", {}), 0.0) if vel_m.get("enabled") else None
            rot_c = _dump_curve(rot_m.get("curve", {}), 0.0) if rot_m.get("enabled") else None

            bursts = []
            for b in em.get("m_Bursts", []):
                cc = b.get("countCurve", {})
                bursts.append({
                    "time": float(b.get("time", 0.0)),
                    "count": float(cc.get("scalar", 0.0)),
                    "minCount": float(cc.get("minScalar", 0.0)),
                    "mode": int(cc.get("minMaxState", 0)),
                    "cycleCount": int(b.get("cycleCount", 1)),
                    "repeatInterval": float(b.get("repeatInterval", 0.01)),
                })

            if fixed_layer is not None:
                node_layer = fixed_layer
            elif person_order is not None and node_order is not None and node_order != person_order:
                node_layer = "front" if node_order > person_order else "back"
            else:
                path_low = next_path.lower()
                is_front = seen_person or any(k in path_low for k in ("/top", "/front", "/limit", "/layer_04", "/layer_05")) or (wz < -0.5)
                node_layer = "front" if is_front else "back"

            rbs_range_raw = rot_spd_m.get("range", {}) if rot_spd_m.get("enabled") else {}
            rbs_range = (
                [float(rbs_range_raw.get("x", 0.0)), float(rbs_range_raw.get("y", 1.0))]
                if isinstance(rbs_range_raw, dict)
                else [0.0, 1.0]
            )
            noise_en = bool(noise_m.get("enabled", False))
            force_en = bool(force_m.get("enabled", False))
            rbs_en = bool(rot_spd_m.get("enabled", False))
            cd_en = bool(cd_m.get("enabled", False)) and int(cd_m.get("mode0", 0)) == 1
            cd_x = _dump_curve(cd_m.get("vector0_0", {}), 0.0) if cd_en else None
            cd_y = _dump_curve(cd_m.get("vector0_1", {}), 0.0) if cd_en else None
            cd_z = _dump_curve(cd_m.get("vector0_2", {}), 0.0) if cd_en else None
            cd_w = _dump_curve(cd_m.get("vector0_3", {}), 0.0) if cd_en else None
            # Shader custom data semantics:
            # 0 = UVliudong standard (xy=mainUv offset, z=maskU offset, w=dissolve/maskV)
            # 1 = raodong_alphablended (y modulates distort strength)
            cd_mode = 1 if "raodong_alpha" in (main_dto.get("shaderName") or "").lower() else 0
            dfs_counter += 1

            nodes.append({
                "_ps_pid": co.path_id,
                "_raw_sub": list(sub_m.get("subEmitters", [])) if sub_m.get("enabled") else [],
                "isSubEmitterChild": False,
                "subEmitters": [],
                "layer": node_layer,
                "effSortOrder": int(node_order if node_order is not None else 0),
                "dfsSeq": dfs_counter,
                "path": next_path,
                "name": go.m_Name,
                "customDataEnabled": cd_en,
                "customDataMode": cd_mode,
                "custom1X": cd_x,
                "custom1Y": cd_y,
                "custom1Z": cd_z,
                "custom1W": cd_w,
                "world_pos": [wx, wy, wz],
                "world_scale": eff_scale,
                "world_rot": [wq[0], wq[1], wq[2], wq[3]],
                "duration": float(tt.get("lengthInSec", 2.0)),
                "startDelay": float(tt.get("startDelay", {}).get("scalar", 0.0)),
                "looping": bool(tt.get("looping", False)),
                "prewarm": bool(tt.get("prewarm", False)),
                "ringBufferMode": int(tt.get("ringBufferMode", 0)),
                "ringBufferLoopRange": [
                    float((tt.get("ringBufferLoopRange") or {}).get("x", 0.0)),
                    float((tt.get("ringBufferLoopRange") or {}).get("y", 1.0)),
                ],
                "scalingMode": scaling_mode,
                "simulationSpeed": float(tt.get("simulationSpeed", 1.0)),
                "simulationSpace": int(tt.get("moveWithTransform", 0)),
                "gravityModifier": _dump_curve(init.get("gravityModifier", {}), 0.0),
                "gravityScale": 37.5,
                "lifetime": _dump_curve(init.get("startLifetime", {}), 1.0),
                "speed": _dump_curve(init.get("startSpeed", {}), 0.0),
                "size": _dump_curve(init.get("startSize", {}), 1.0),
                "size3D": bool(init.get("size3D", False)),
                "sizeX": _dump_curve(init.get("startSize", {}), 1.0),
                "sizeY": _dump_curve(init.get("startSizeY", {}), 1.0),
                "sizeZ": _dump_curve(init.get("startSizeZ", {}), 1.0),
                "rotation": _dump_curve(init.get("startRotation", {}), 0.0),
                "rotation3D": bool(init.get("rotation3D", False)),
                "rotationX": _dump_curve(init.get("startRotationX", {}), 0.0),
                "rotationY": _dump_curve(init.get("startRotationY", {}), 0.0),
                "startColor": sc_mod.get("maxColor", {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}),
                "startColorMin": sc_mod.get("minColor", {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}),
                "startColorMode": int(sc_mod.get("minMaxState", 0)),
                "startColorGrad": _dump_gradient(sc_mod),
                "maxParticles": int(init.get("maxNumParticles", 50)),
                "rate": float(rate_curve["scalar"]),
                "rateCurve": rate_curve,
                "rateOverDistance": float(rate_dist_curve["scalar"]),
                "rateOverDistanceCurve": rate_dist_curve,
                "bursts": bursts,
                "shapeEnabled": bool(sh.get("enabled", False)),
                "shapeType": int(sh.get("type", 0)),
                "shapeRadius": float(sh.get("radius", {}).get("value", 1.0)),
                "shapeArc": float(sh.get("arc", {}).get("value", 360.0)),
                "shapeAngle": float(sh.get("angle", 25.0)),
                "shapeRadiusThickness": float(sh.get("radiusThickness", 1.0)),
                "shapeRandomDir": float(sh.get("randomDirectionAmount", 0.0)),
                "shapeSphericalDir": float(sh.get("sphericalDirectionAmount", 0.0)),
                "shapeAlignToDir": bool(sh.get("alignToDirection", False)),
                "shapeBox": [float(sh_box.get("x", 1.0)), float(sh_box.get("y", 1.0)), float(sh_box.get("z", 1.0))],
                "shapeRot": [float(sh_rot.get("x", 0.0)), float(sh_rot.get("y", 0.0)), float(sh_rot.get("z", 0.0))],
                "shapePos": [float(sh_pos.get("x", 0.0)), float(sh_pos.get("y", 0.0)), float(sh_pos.get("z", 0.0))],
                "colOverLife": _dump_gradient(col_m.get("gradient", {})) if col_m.get("enabled") else None,
                "sizeOverLife": _dump_curve(sz_m.get("curve", {}), 1.0) if sz_m.get("enabled") else None,
                "sizeOverLifeSeparateAxes": bool(sz_m.get("separateAxes", False)) if sz_m.get("enabled") else False,
                "sizeOverLifeY": _dump_curve(sz_m.get("y", {}), 1.0) if (sz_m.get("enabled") and sz_m.get("separateAxes")) else None,
                "sizeOverLifeZ": _dump_curve(sz_m.get("z", {}), 1.0) if (sz_m.get("enabled") and sz_m.get("separateAxes")) else None,
                "velEnabled": bool(vel_m.get("enabled", False)),
                "velX": float(vel_x_c["scalar"]) if vel_x_c else 0.0,
                "velY": float(vel_y_c["scalar"]) if vel_y_c else 0.0,
                "velZ": float(vel_z_c["scalar"]) if vel_z_c else 0.0,
                "velXCurve": vel_x_c,
                "velYCurve": vel_y_c,
                "velZCurve": vel_z_c,
                "velInWorldSpace": bool(vel_m.get("inWorldSpace", False)) if vel_m.get("enabled") else False,
                "velOrbitalX": _dump_curve(vel_m.get("orbitalX", {}), 0.0) if vel_m.get("enabled") else None,
                "velOrbitalY": _dump_curve(vel_m.get("orbitalY", {}), 0.0) if vel_m.get("enabled") else None,
                "velOrbitalZ": _dump_curve(vel_m.get("orbitalZ", {}), 0.0) if vel_m.get("enabled") else None,
                "velOrbitalOffsetX": _dump_curve(vel_m.get("orbitalOffsetX", {}), 0.0) if vel_m.get("enabled") else None,
                "velOrbitalOffsetY": _dump_curve(vel_m.get("orbitalOffsetY", {}), 0.0) if vel_m.get("enabled") else None,
                "velOrbitalOffsetZ": _dump_curve(vel_m.get("orbitalOffsetZ", {}), 0.0) if vel_m.get("enabled") else None,
                "velRadial": _dump_curve(vel_m.get("radial", {}), 0.0) if vel_m.get("enabled") else None,
                "velSpeedModifier": _dump_curve(vel_m.get("speedModifier", {}), 1.0) if vel_m.get("enabled") else None,
                "limitVelEnabled": bool(lim_m.get("enabled", False)),
                "limitVelSeparateAxes": bool(lim_m.get("separateAxis", False)) if lim_m.get("enabled") else False,
                "limitVel": _dump_curve(lim_m.get("magnitude", {}), 1.0) if lim_m.get("enabled") else None,
                "limitVelX": _dump_curve(lim_m.get("x", {}), 1.0) if lim_m.get("enabled") else None,
                "limitVelY": _dump_curve(lim_m.get("y", {}), 1.0) if lim_m.get("enabled") else None,
                "limitVelZ": _dump_curve(lim_m.get("z", {}), 1.0) if lim_m.get("enabled") else None,
                "limitVelDampen": float(lim_m.get("dampen", 1.0)) if lim_m.get("enabled") else 1.0,
                "limitVelDrag": _dump_curve(lim_m.get("drag", {}), 0.0) if lim_m.get("enabled") else None,
                "limitVelInWorld": bool(lim_m.get("inWorldSpace", False)) if lim_m.get("enabled") else False,
                "limitVelMulSize": bool(lim_m.get("multiplyDragByParticleSize", False)) if lim_m.get("enabled") else False,
                "limitVelMulVel": bool(lim_m.get("multiplyDragByParticleVelocity", False)) if lim_m.get("enabled") else False,
                "rotOverLifeEnabled": bool(rot_m.get("enabled", False)),
                "rotOverLifeSeparateAxes": bool(rot_m.get("separateAxes", False)) if rot_m.get("enabled") else False,
                "rotOverLife": float(rot_c["scalar"]) if rot_c else 0.0,
                "rotOverLifeCurve": rot_c,
                "rotOverLifeX": _dump_curve(rot_m.get("x", {}), 0.0) if (rot_m.get("enabled") and rot_m.get("separateAxes")) else None,
                "rotOverLifeY": _dump_curve(rot_m.get("y", {}), 0.0) if (rot_m.get("enabled") and rot_m.get("separateAxes")) else None,
                "noiseEnabled": noise_en,
                "noiseSeparateAxes": bool(noise_m.get("separateAxes", False)) if noise_en else False,
                "noiseStrength": float(noise_m.get("strength", {}).get("scalar", 1.0)) if noise_en else 0.0,
                "noiseStrengthCurve": _dump_curve(noise_m.get("strength", {}), 1.0) if noise_en else None,
                "noiseStrengthYCurve": _dump_curve(noise_m.get("strengthY", {}), 0.0) if (noise_en and noise_m.get("separateAxes")) else None,
                "noiseStrengthZCurve": _dump_curve(noise_m.get("strengthZ", {}), 0.0) if (noise_en and noise_m.get("separateAxes")) else None,
                "noiseFrequency": float(noise_m.get("frequency", 0.5)) if noise_en else 0.5,
                "noiseScrollSpeed": float(noise_m.get("scrollSpeed", {}).get("scalar", 0.0)) if noise_en else 0.0,
                "noiseScrollSpeedCurve": _dump_curve(noise_m.get("scrollSpeed", {}), 0.0) if noise_en else None,
                "noiseDamping": bool(noise_m.get("damping", True)) if noise_en else True,
                "noiseOctaves": int(noise_m.get("octaves", 1)) if noise_en else 1,
                "noiseOctaveMultiplier": float(noise_m.get("octaveMultiplier", 0.5)) if noise_en else 0.5,
                "noiseOctaveScale": float(noise_m.get("octaveScale", 2.0)) if noise_en else 2.0,
                "noiseQuality": int(noise_m.get("quality", 2)) if noise_en else 2,
                "noisePosAmountCurve": _dump_curve(noise_m.get("positionAmount", {}), 1.0) if noise_en else None,
                "noiseRotAmountCurve": _dump_curve(noise_m.get("rotationAmount", {}), 0.0) if noise_en else None,
                "noiseSizeAmountCurve": _dump_curve(noise_m.get("sizeAmount", {}), 0.0) if noise_en else None,
                "forceEnabled": force_en,
                "forceInWorldSpace": bool(force_m.get("inWorldSpace", False)) if force_en else False,
                "forceRandomized": bool(force_m.get("randomizePerFrame", False)) if force_en else False,
                "forceX": float(force_m.get("x", {}).get("scalar", 0.0)) if force_en else 0.0,
                "forceY": float(force_m.get("y", {}).get("scalar", 0.0)) if force_en else 0.0,
                "forceZ": float(force_m.get("z", {}).get("scalar", 0.0)) if force_en else 0.0,
                "forceXCurve": _dump_curve(force_m.get("x", {}), 0.0) if force_en else None,
                "forceYCurve": _dump_curve(force_m.get("y", {}), 0.0) if force_en else None,
                "forceZCurve": _dump_curve(force_m.get("z", {}), 0.0) if force_en else None,
                "rotBySpeedEnabled": rbs_en,
                "rotBySpeedSeparateAxes": bool(rot_spd_m.get("separateAxes", False)) if rbs_en else False,
                "rotBySpeedCurve": _dump_curve(rot_spd_m.get("curve", {}), 0.0) if rbs_en else None,
                "rotBySpeedX": _dump_curve(rot_spd_m.get("x", {}), 0.0) if (rbs_en and rot_spd_m.get("separateAxes")) else None,
                "rotBySpeedY": _dump_curve(rot_spd_m.get("y", {}), 0.0) if (rbs_en and rot_spd_m.get("separateAxes")) else None,
                "rotBySpeedRange": rbs_range,
                "uvTiles": [int(uv_m.get("tilesX", 1)), int(uv_m.get("tilesY", 1)), float(uv_m.get("cycles", 1.0))] if uv_m.get("enabled") else None,
                "uvMode": int(uv_m.get("mode", 0)) if uv_m.get("enabled") else -1,
                "uvAnim": int(uv_m.get("animationType", 0)),
                "uvRowMode": int(uv_m.get("rowMode", 0)),
                "uvFrameMode": int(uv_fot.get("minMaxState", 1)),
                "uvFrameScalar": float(uv_fot.get("scalar", 1.0)),
                "uvFrameMin": float(uv_fot.get("minScalar", 0.0)),
                "uvFrameKeys": uv_fot_keys,
                "hasMainMaterial": has_main_mat,
                **main_dto,
                "sortOrder": sort_order,
                "renderMode": render_mode,
                "renderAlignment": render_align,
                "maxParticleSize": max_particle_size,
                "meshName": mesh_name,
                "velocityScale": vel_scale,
                "lengthScale": len_scale,
                "pivot": pivot,
                "flip": flip,
                "trailsEnabled": trails_enabled and has_trail_mat,
                "trailMode": int(trail_m.get("mode", 0)) if trails_enabled else 0,
                "trailRatio": float(trail_m.get("ratio", 1.0)) if trails_enabled else 1.0,
                "trailLifetime": _dump_curve(trail_m.get("lifetime", {}), 0.5) if trails_enabled else None,
                "trailMinVertexDist": float(trail_m.get("minVertexDistance", 0.2)) if trails_enabled else 0.2,
                "trailWorldSpace": bool(trail_m.get("worldSpace", False)) if trails_enabled else False,
                "trailDieWithParticles": bool(trail_m.get("dieWithParticles", True)) if trails_enabled else True,
                "trailSizeAffectsWidth": bool(trail_m.get("sizeAffectsWidth", True)) if trails_enabled else True,
                "trailSizeAffectsLifetime": bool(trail_m.get("sizeAffectsLifetime", False)) if trails_enabled else False,
                "trailInheritColor": bool(trail_m.get("inheritParticleColor", True)) if trails_enabled else True,
                "trailTextureMode": int(trail_m.get("textureMode", 0)) if trails_enabled else 0,
                "trailRibbonCount": int(trail_m.get("ribbonCount", 1)) if trails_enabled else 1,
                "trailWidthOverTrail": _dump_curve(trail_m.get("widthOverTrail", {}), 1.0) if trails_enabled else None,
                "trailColorOverLifetime": _dump_gradient(trail_m.get("colorOverLifetime", {})) if trails_enabled else None,
                "trailColorOverTrail": _dump_gradient(trail_m.get("colorOverTrail", {})) if trails_enabled else None,
                "hasTrailMaterial": has_trail_mat,
                "trailTexName": trail_dto["texName"],
                "trailTexScale": trail_dto["texScale"],
                "trailTexOffset": trail_dto["texOffset"],
                "trailTexWrap": trail_dto["texWrap"],
                "trailMaskTexName": trail_dto["maskTexName"],
                "trailMaskScale": trail_dto["maskScale"],
                "trailMaskOffset": trail_dto["maskOffset"],
                "trailMaskWrap": trail_dto["maskWrap"],
                "trailMask2TexName": trail_dto["mask2TexName"],
                "trailMask2Scale": trail_dto["mask2Scale"],
                "trailMask2Offset": trail_dto["mask2Offset"],
                "trailMask2Wrap": trail_dto["mask2Wrap"],
                "trailDissolveTexName": trail_dto["dissolveTexName"],
                "trailDissolveScale": trail_dto["dissolveScale"],
                "trailDissolveOffset": trail_dto["dissolveOffset"],
                "trailDissolveWrap": trail_dto["dissolveWrap"],
                "trailDissolve": trail_dto["dissolve"],
                "trailDissolveSoft": trail_dto["dissolveSoft"],
                "trailDistortTexName": trail_dto["distortTexName"],
                "trailDistortScale": trail_dto["distortScale"],
                "trailDistortOffset": trail_dto["distortOffset"],
                "trailDistortWrap": trail_dto["distortWrap"],
                "trailDistortStrength": trail_dto["distortStrength"],
                "trailUvScroll": trail_dto["uvScroll"],
                "trailIsAdditive": trail_dto["isAdditive"],
                "trailTint": trail_dto["tint"],
                "trailTintMultiplier": trail_dto["tintMultiplier"],
            })

        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in objs:
                    walk(objs[ch.path_id].read().m_GameObject.path_id, (wx, wy, wz), (wsx, wsy, wsz), wq, depth + 1, in_harm_here, next_path, node_order)

    walk(root_gid, base_pos, base_scale, base_rot, 0, False, "", None)

    # Wire SubEmitter references and strip temporary private metadata keys
    pid_to_idx = {n["_ps_pid"]: i for i, n in enumerate(nodes)}
    for n in nodes:
        for se in n.pop("_raw_sub", []):
            em_ref = se.get("emitter", {})
            tpid = int(em_ref.get("m_PathID", 0))
            if tpid in pid_to_idx:
                tidx = pid_to_idx[tpid]
                n["subEmitters"].append({
                    "targetIdx": tidx,
                    "type": int(se.get("type", 0)),
                    "properties": int(se.get("properties", 0)),
                    "emitProbability": float(se.get("emitProbability", 1.0)),
                })
                nodes[tidx]["isSubEmitterChild"] = True
                nodes[tidx]["layer"] = n["layer"]
        n.pop("_ps_pid", None)
    return nodes


def _filter_nodes_by_layer(nodes: list[dict[str, Any]], target_layer: str) -> list[dict[str, Any]]:
    """Return deep copy of root nodes in target_layer plus their subEmitter descendants, remapping targetIdx."""
    import copy

    keep_indices: list[int] = []
    seen: set[int] = set()

    def add_tree(idx: int) -> None:
        if idx in seen or idx < 0 or idx >= len(nodes):
            return
        seen.add(idx)
        keep_indices.append(idx)
        for se in nodes[idx].get("subEmitters", []):
            add_tree(int(se["targetIdx"]))

    for i, n in enumerate(nodes):
        if not n.get("isSubEmitterChild") and n.get("layer") == target_layer:
            add_tree(i)

    old_to_new = {old: new for new, old in enumerate(keep_indices)}
    out: list[dict[str, Any]] = []
    for old in keep_indices:
        c = copy.deepcopy(nodes[old])
        new_subs = []
        for se in c.get("subEmitters", []):
            t = int(se["targetIdx"])
            if t in old_to_new:
                se2 = dict(se)
                se2["targetIdx"] = old_to_new[t]
                new_subs.append(se2)
        c["subEmitters"] = new_subs
        out.append(c)
    return out


def _estimate_clip_duration(nodes: list[dict[str, Any]], is_idle: bool) -> float:
    if is_idle:
        return 2.0
    max_t = 0.0
    for n in nodes:
        lt = n["lifetime"]
        max_lt = max(float(lt.get("scalar", 1.0)), float(lt.get("minScalar", 1.0)), 0.5)
        span = float(n.get("startDelay", 0.0)) + (3.0 if n.get("looping") else float(n.get("duration", 2.0))) + max_lt
        max_t = max(max_t, span)
    # Snap up to clean 0.5s boundary, bounded to [1.5s, 14.0s] to keep atlases lean
    return max(1.5, min(14.0, math.ceil(max_t * 2.0) / 2.0))


def _extract_tween_nodes(
    indexer: AssetIndexer,
    objs: dict[int, Any],
    root_gid: int | None,
    saved_textures: set[str],
    person_order: int | None = None,
) -> list[dict[str, Any]]:
    """Extract active NGUI/UGUI TweenRotation / TweenPosition / TweenScale background layers."""
    if root_gid is None or not objs:
        return []
    tween_groups: list[dict[str, Any]] = []

    def _save_sprite(co, sref: dict[str, Any]) -> str:
        if not sref or int(sref.get("m_PathID", 0)) == 0:
            return ""
        sobj = indexer.resolve_ext(co.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
        if sobj is None or sobj.type.name not in ("Sprite", "Texture2D"):
            return ""
        sname = (sobj.peek_name() or f"sp_{sobj.path_id}").strip()
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", sname)
        tkey = f"tween_{safe}"
        if tkey not in saved_textures:
            TEX_DIR.mkdir(parents=True, exist_ok=True)
            out_png = TEX_DIR / f"{tkey}.png"
            if not out_png.exists():
                sobj.read().image.convert("RGBA").save(out_png, "PNG")
            saved_textures.add(tkey)
        return tkey

    def walk(
        gid: int,
        depth: int,
        ppos: tuple[float, float, float],
        pscale: tuple[float, float, float],
        pq: tuple[float, float, float, float],
        psize: tuple[float, float],
        ppiv: tuple[float, float],
        path: str,
        cur_order: int | None,
        cur_mask: dict[str, float] | None,
        active_group: dict[str, Any] | None,
    ) -> None:
        if gid not in objs:
            return
        go = objs[gid].read()
        if not go.m_IsActive:
            return
        nm = go.m_Name
        low = nm.lower()
        if any(k in low for k in ("harmonious", "hexie", "mask_censor")):
            return
        cur_path = f"{path}/{nm}" if path else nm
        rt, is_rect, (lx, ly, lz), (sx, sy, sz), lq = _node_local_tf(go, objs, ignore_root_pos=(depth == 0))
        rw = rh = 0.0
        px = py = 0.5
        elx, ely = lx, ly
        if is_rect and rt is not None:
            sd, amin, amax, piv, ap = rt.m_SizeDelta, rt.m_AnchorMin, rt.m_AnchorMax, rt.m_Pivot, rt.m_AnchoredPosition
            px, py = float(piv.x), float(piv.y)
            if depth == 0:
                rw, rh = float(sd.x), float(sd.y)
                elx = ely = 0.0
            else:
                pw, ph = psize
                ppx, ppy = ppiv
                rw = pw * (float(amax.x) - float(amin.x)) + float(sd.x)
                rh = ph * (float(amax.y) - float(amin.y)) + float(sd.y)
                elx = (float(amin.x) + (float(amax.x) - float(amin.x)) * px - ppx) * pw + float(ap.x)
                ely = (float(amin.y) + (float(amax.y) - float(amin.y)) * py - ppy) * ph + float(ap.y)

        rx, ry, rz = _qrot(pq, (elx * pscale[0], ely * pscale[1], lz * pscale[2]))
        wx, wy, wz = ppos[0] + rx, ppos[1] + ry, ppos[2] + rz
        wsx, wsy, wsz = pscale[0] * sx, pscale[1] * sy, pscale[2] * sz
        wq = _qmul(pq, lq)
        z_deg = math.degrees(math.atan2(2.0 * (wq[3] * wq[2] + wq[0] * wq[1]), 1.0 - 2.0 * (wq[1] * wq[1] + wq[2] * wq[2])))
        img_cx = wx + (0.5 - px) * rw * wsx
        img_cy = wy + (0.5 - py) * rh * wsy

        node_order = cur_order
        node_mask = cur_mask
        tweens: list[dict[str, Any]] = []
        img_sprite_ref = None
        img_sprite_tex = ""
        img_color = {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}

        for c in go.m_Component:
            co = objs.get(c.component.path_id)
            if not co:
                continue
            if co.type.name == "Canvas":
                try:
                    ctt = co.read_typetree()
                    if ctt.get("m_OverrideSorting"):
                        node_order = int(ctt.get("m_SortingOrder", 0))
                except Exception:
                    pass
            elif co.type.name == "MonoBehaviour":
                try:
                    tt = co.read_typetree()
                except Exception:
                    continue
                if "Order" in tt and tt.get("m_Enabled", 1):
                    node_order = int(tt["Order"])
                if ("m_ShowMaskGraphic" in tt or ("m_Padding" in tt and "m_Softness" in tt)) and is_rect and rw > 1.0 and rh > 1.0:
                    node_mask = {
                        "cx": round(img_cx, 3),
                        "cy": round(img_cy, 3),
                        "w": round(rw * abs(wsx), 3),
                        "h": round(rh * abs(wsy), 3),
                    }
                if "from" in tt and "to" in tt and "duration" in tt and tt.get("m_Enabled", 1):
                    sc_pid = tt.get("m_Script", {}).get("m_PathID")
                    sn = objs[sc_pid].peek_name() if sc_pid in objs else ""
                    if sn in ("TweenRotation", "TweenPosition", "TweenScale"):
                        fr = tt.get("from") or {}
                        to = tt.get("to") or {}
                        tweens.append({
                            "type": sn,
                            "from": [float(fr.get("x", 0.0)), float(fr.get("y", 0.0)), float(fr.get("z", 0.0))],
                            "to": [float(to.get("x", 0.0)), float(to.get("y", 0.0)), float(to.get("z", 0.0))],
                            "duration": max(0.1, float(tt.get("duration", 10.0))),
                            "style": int(tt.get("style", 1)),
                        })
                if "m_Sprite" in tt and tt.get("m_Enabled", 1):
                    sref = tt["m_Sprite"]
                    col = tt.get("m_Color") or {}
                    img_color = {
                        "r": float(col.get("r", 1.0)),
                        "g": float(col.get("g", 1.0)),
                        "b": float(col.get("b", 1.0)),
                        "a": float(col.get("a", 1.0)),
                    }
                    img_sprite_ref = (co, sref)

        if img_sprite_ref is not None and (tweens or active_group is not None):
            img_sprite_tex = _save_sprite(img_sprite_ref[0], img_sprite_ref[1])

        grp = active_group
        if tweens:
            layer = "front" if (person_order is not None and node_order is not None and node_order > person_order) else "back"
            grp = {
                "name": nm,
                "path": cur_path,
                "layer": layer,
                "sort_order": int(node_order if node_order is not None else 1),
                "parent_wx": round(ppos[0], 4),
                "parent_wy": round(ppos[1], 4),
                "parent_wsx": round(pscale[0], 6),
                "parent_wsy": round(pscale[1], 6),
                "world_pos": [round(wx, 4), round(wy, 4)],
                "local_pos": [round(elx, 4), round(ely, 4)],
                "local_scale": [round(sx, 6), round(sy, 6)],
                "z_deg": round(z_deg, 4),
                "mask": node_mask,
                "tweens": tweens,
                "sprites": [],
            }
            tween_groups.append(grp)

        if grp is not None and img_sprite_tex and rw > 1.0 and rh > 1.0:
            # Store sprite offset relative to the Tween group's UNSCALED local space so TweenPosition/Scale/Rotation act cleanly
            if grp["path"] == cur_path:
                rel_x = (0.5 - px) * rw
                rel_y = (0.5 - py) * rh
                sp_w = rw * abs(pscale[0])
                sp_h = rh * abs(pscale[1])
            else:
                # Child image under Tween group
                rel_x = (img_cx - grp["world_pos"][0]) / max(1e-6, abs(grp["parent_wsx"] * grp["local_scale"][0]))
                rel_y = (img_cy - grp["world_pos"][1]) / max(1e-6, abs(grp["parent_wsy"] * grp["local_scale"][1]))
                sp_w = rw * abs(wsx) / max(1e-6, abs(grp["local_scale"][0]))
                sp_h = rh * abs(wsy) / max(1e-6, abs(grp["local_scale"][1]))
            grp["sprites"].append({
                "name": nm,
                "tex": img_sprite_tex,
                "rel_x": round(rel_x, 3),
                "rel_y": round(rel_y, 3),
                "w": round(sp_w, 3),
                "h": round(sp_h, 3),
                "color": img_color,
            })

        if rt and hasattr(rt, "m_Children"):
            csz = (rw, rh) if is_rect else psize
            cpv = (px, py) if is_rect else ppiv
            for ch in rt.m_Children:
                if ch.path_id in objs:
                    walk(
                        objs[ch.path_id].read().m_GameObject.path_id,
                        depth + 1,
                        (wx, wy, wz),
                        (wsx, wsy, wsz),
                        wq,
                        csz,
                        cpv,
                        cur_path,
                        node_order,
                        node_mask,
                        grp,
                    )

    walk(root_gid, 0, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (1700.0, 750.0), (0.5, 0.5), "", None, None, None)
    return [g for g in tween_groups if g["sprites"]]


def _compute_optimal_gpu_period(nodes: list[dict[str, Any]]) -> float:
    """Choose optimal loop period T* in [4.0, 10.0]s (step 0.25s) minimizing integer-cycle snap error
    across fast/medium UV scroll speeds (|v| >= 0.08/s), ringBufferMode=2 loop periods, and regular bursts."""
    fast_uvs: list[float] = []
    rbm2_periods: list[float] = []
    burst_durs: list[float] = []
    for n in nodes:
        sim_spd = float(n.get("simulationSpeed", 1.0)) or 1.0
        rbm = int(n.get("ringBufferMode", 0))
        lt_d = n.get("lifetime") or {}
        lt_hi = max(float(lt_d.get("scalar", 1.0)), float(lt_d.get("minScalar", 1.0))) / sim_spd
        dur = float(n.get("duration", 5.0)) / sim_spd
        if rbm == 2:
            rbr = n.get("ringBufferLoopRange") or [0.0, 1.0]
            span = max(0.05, float(rbr[1]) - float(rbr[0]))
            prb = lt_hi * span
            if 0.5 <= prb <= 15.0:
                rbm2_periods.append(prb)
        elif rbm == 0 and lt_hi < 99.0:
            rate_eff = float(n.get("rate", 0.0)) * sim_spd
            if rate_eff <= 0.01 and n.get("bursts") and 1.0 <= dur <= 10.0:
                burst_durs.append(dur)
        for v in (n.get("uvScroll") or [])[:8]:
            av = abs(float(v))
            if av >= 0.08:
                fast_uvs.append(av)

    if not fast_uvs and not rbm2_periods and not burst_durs:
        return 6.0

    def _err(T: float) -> float:
        errs = []
        for v in fast_uvs:
            k = max(1, int(round(v * T)))
            errs.append(abs(k / T - v) / v)
        for p in rbm2_periods:
            if p <= T * 1.25:
                k = max(1, int(round(T / p)))
                errs.append(abs((T / k) - p) / p)
        for bd in burst_durs:
            if bd <= T * 1.15:
                k = max(1, int(round(T / bd)))
                errs.append(abs((T / k) - bd) / bd * 0.5)
        return max(errs) if errs else 0.0

    best_T = 6.0
    best_e = _err(6.0)
    for ti in range(16, 41):  # 4.0s .. 10.0s in 0.25s steps
        T = ti * 0.25
        e = _err(T)
        if e < best_e - 1e-4 or (abs(e - best_e) <= 1e-4 and abs(T - 6.0) < abs(best_T - 6.0)):
            best_T, best_e = T, e
    return round(best_T, 4)


def build_manifest(
    skins: list[dict[str, Any]],
    indexer: AssetIndexer,
    skip_aurora_s4: bool = False,
    resume: bool = False,
) -> dict[str, Any]:
    """Build Unity batch FX manifest for selected skins and extract referenced Texture2Ds."""
    saved_textures: set[str] = set()
    saved_meshes: set[str] = set()
    tex_wrap_modes: dict[str, list[int]] = {}
    wrap_json_path = UNITY_PROJ / "tex_wrap_modes.json"
    if wrap_json_path.is_file():
        try:
            old_wrap = json.loads(wrap_json_path.read_text(encoding="utf-8-sig"))
            if isinstance(old_wrap, dict):
                tex_wrap_modes.update(old_wrap)
        except Exception:
            pass
    manifest_skins: list[dict[str, Any]] = []
    layout_cache: dict[str, dict[str, Any]] = {}

    for sk in skins:
        if skip_aurora_s4 and sk["char_name"] == "欧若拉" and sk["dress_name"] == "童话心绘":
            continue

        layout = inspect_bg_prefab_layout(indexer, sk)
        layout_cache[sk["skin_key"]] = layout
        skin_out_dir = FX_SEQ_ROOT / sk["skin_key"]

        clips: list[dict[str, Any]] = []
        # 1. Idle FX from official art_prefabs.ab BgPrefab
        bg_objs, bg_gid = resolve_bg_prefab_root(indexer, sk)
        tween_nodes = _extract_tween_nodes(
            indexer,
            bg_objs,
            bg_gid,
            saved_textures,
            person_order=layout.get("person_order"),
        )
        # Special sandwich layer for Asuna_S8: Bottom/Image_00 (static night sky) sits right beneath Bottom/Image_00_Anim
        # so fx_asuna_s8_back (-3) can render Image_00 -> Image_00_Anim (90s star trails) -> trail01 behind bg_static (-2)!
        if sk["skin_key"] == "603_Asuna_S8" and tween_nodes and bg_gid is not None:
            for obj_id, obj_val in bg_objs.items():
                if obj_val.type.name != "GameObject":
                    continue
                try:
                    go_r = obj_val.read()
                    if go_r.m_Name == "Image_00" and go_r.m_IsActive:
                        for comp_ref in go_r.m_Component:
                            co = bg_objs.get(comp_ref.component.path_id)
                            if co and co.type.name == "MonoBehaviour":
                                tt = co.read_typetree()
                                if "m_Sprite" in tt:
                                    sref = tt["m_Sprite"]
                                    sobj = indexer.resolve_ext(co.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
                                    if sobj is not None and sobj.type.name in ("Sprite", "Texture2D"):
                                        tkey = "tween_Asuna_S8_Image_00"
                                        if tkey not in saved_textures:
                                            TEX_DIR.mkdir(parents=True, exist_ok=True)
                                            out_png = TEX_DIR / f"{tkey}.png"
                                            if not out_png.exists():
                                                sobj.read().image.convert("RGBA").save(out_png, "PNG")
                                            saved_textures.add(tkey)
                                        tween_nodes.insert(0, {
                                            "name": "Image_00_StaticSky",
                                            "path": "Asuna_S8_Background/Bottom/Image_00",
                                            "layer": "back",
                                            "sort_order": 0,
                                            "parent_wx": 0.0,
                                            "parent_wy": 0.0,
                                            "parent_wsx": 1.0,
                                            "parent_wsy": 1.0,
                                            "world_pos": [0.0, 60.0],
                                            "local_pos": [0.0, 60.0],
                                            "local_scale": [1.0, 1.0],
                                            "z_deg": 0.0,
                                            "mask": None,
                                            "tweens": [],
                                            "sprites": [{
                                                "name": "Image_00",
                                                "tex": tkey,
                                                "rel_x": 0.0,
                                                "rel_y": 0.0,
                                                "w": 1700.0,
                                                "h": 1131.0,
                                                "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
                                            }],
                                        })
                                        break
                        break
                except Exception:
                    pass
        idle_nodes = _extract_ps_nodes(
            indexer,
            bg_objs,
            bg_gid,
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            saved_textures,
            saved_meshes=saved_meshes,
            person_order=layout.get("person_order"),
            tex_wrap_modes=tex_wrap_modes,
        )
        if idle_nodes:
            # Make transient non-looping ambient idle emitters loop cleanly;
            # NEVER overwrite looping/maxParticles/duration on ringBufferMode != 0 (PauseUntilReplaced / LoopUntilReplaced)
            # or >=99s persistent ambient layers!
            max_idle_lt = 4.0
            for n in idle_nodes:
                if n.get("isSubEmitterChild"):
                    continue
                rbm = int(n.get("ringBufferMode", 0))
                lt = n["lifetime"]
                sim_spd = float(n.get("simulationSpeed", 1.0)) or 1.0
                lt_hi = max(float(lt.get("scalar", 1.0)), float(lt.get("minScalar", 1.0))) / sim_spd
                if rbm != 0:
                    # Ring-buffer particle persists indefinitely after initial spawn; keep native Unity settings intact
                    max_idle_lt = max(max_idle_lt, min(lt_hi, 6.0))
                    continue
                if lt_hi < 99.0:
                    max_idle_lt = max(max_idle_lt, lt_hi)
                    if not n.get("looping"):
                        n["looping"] = True
                        if int(n.get("maxParticles", 1)) == 1:
                            n["maxParticles"] = 2
                        if float(n.get("rate", 0.0)) <= 0.0 and n.get("bursts"):
                            n["duration"] = max(float(n.get("duration", 2.0)), lt_hi * sim_spd)
            idle_warmup = max(4.0, min(60.0, math.ceil(max_idle_lt + 2.0)))
            has_back = any((not n.get("isSubEmitterChild")) and n.get("layer") == "back" for n in idle_nodes)
            has_front = any((not n.get("isSubEmitterChild")) and n.get("layer") == "front" for n in idle_nodes)
            if has_back and has_front:
                for lname, cname in (("back", "idle_back"), ("front", "idle_front")):
                    lnodes = _filter_nodes_by_layer(idle_nodes, lname)
                    if lnodes:
                        t_opt = _compute_optimal_gpu_period(lnodes)
                        clips.append({
                            "clip": cname,
                            "layer": lname,
                            "fps": 16.0,
                            "duration": t_opt,
                            "warmup": idle_warmup,
                            "crossfadeIdle": False,
                            "useZeroCrossfade": True,
                            "blendDuration": 0.0,
                            "nodes": lnodes,
                        })
            else:
                only_layer = "front" if has_front else "back"
                t_opt = _compute_optimal_gpu_period(idle_nodes)
                clips.append({
                    "clip": "idle",
                    "layer": only_layer,
                    "fps": 16.0,
                    "duration": t_opt,
                    "warmup": idle_warmup,
                    "crossfadeIdle": False,
                    "useZeroCrossfade": True,
                    "blendDuration": 0.0,
                    "nodes": idle_nodes,
                })

        # 2. Triggered EffectIds from art_prefabs.ab
        pr = layout["fx_point_root"]
        p_ord = layout.get("person_order")
        for eid, pf_name in sk["effect_prefabs"].items():
            ck = f"assets/03_prefabs/art_prefabs/effect/{pf_name.lower()}.prefab"
            egid = indexer.art_container.get(ck)
            if egid is None:
                cands = indexer.art_go_by_name.get(Path(pf_name).name.lower(), [])
                egid = cands[0] if cands else None
            if egid is None:
                continue
            eff_ord = sk.get("effect_orders", {}).get(eid, 0)
            fx_layer = "back" if (p_ord is not None and eff_ord != 0 and eff_ord < p_ord) else "front"
            ef_nodes = _extract_ps_nodes(
                indexer,
                indexer.art_objs,
                egid,
                (pr["wx"], pr["wy"], pr["wz"]),
                (pr["wsx"], pr["wsy"], pr["wsz"]),
                pr["wq"],
                saved_textures,
                saved_meshes=saved_meshes,
                ignore_root_scale_rot=True,
                person_order=p_ord,
                fixed_layer=fx_layer,
                tex_wrap_modes=tex_wrap_modes,
            )
            if ef_nodes:
                clips.append({
                    "clip": f"fx_{eid}",
                    "layer": fx_layer,
                    "fps": 18.0,
                    "duration": _estimate_clip_duration(ef_nodes, is_idle=False),
                    "warmup": 0.0,
                    "crossfadeIdle": False,
                    "nodes": ef_nodes,
                })

        if not clips and not tween_nodes:
            continue

        if resume and clips and all((skin_out_dir / c["clip"]).is_dir() and (any((skin_out_dir / c["clip"] / "normal").glob("frame_*.png")) or any((skin_out_dir / c["clip"] / "add").glob("frame_*.png"))) for c in clips):
            continue

        cw, ch = layout["canvas_w"], layout["canvas_h"]
        rw = max(64, int(round(cw * 0.6 / 2.0) * 2))
        rh = max(64, int(round(ch * 0.6 / 2.0) * 2))
        p_tf = layout["person"]
        manifest_skins.append({
            "skin_key": sk["skin_key"],
            "output_dir": str(skin_out_dir),
            "cam_x": layout["cam_x"],
            "cam_y": layout["cam_y"],
            "canvas_w": cw,
            "canvas_h": ch,
            "render_w": rw,
            "render_h": rh,
            "fps": 16.0,
            "person_wx": round(float(p_tf["wx"]), 4),
            "person_wy": round(float(p_tf["wy"]), 4),
            "ui_per_spine_x": round(float(p_tf.get("ui_per_spine_x", p_tf["ui_per_spine"])), 6),
            "ui_per_spine_y": round(float(p_tf.get("ui_per_spine_y", p_tf["ui_per_spine"])), 6),
            "person_z_deg": round(float(p_tf.get("z_deg", 0.0)), 4),
            "clips": clips,
            "tween_nodes": tween_nodes,
        })

    if tex_wrap_modes:
        write_json(wrap_json_path, tex_wrap_modes)

    return {
        "skins": manifest_skins,
        "textures_extracted": len(saved_textures),
        "tex_wrap_modes": tex_wrap_modes,
        "layouts": layout_cache,
    }


def run_unity_batch(
    manifest_path: Path,
    log_path: Path = DEFAULT_LOG_PATH,
    project_path: Path = UNITY_PROJ,
) -> int:
    """Execute Unity 2021.3.34f1 GPU batchmode recording WITHOUT -nographics."""
    if not UNITY_EXE.is_file():
        raise FileNotFoundError(f"Unity Editor not found: {UNITY_EXE}")
    cmd = [
        str(UNITY_EXE),
        "-batchmode",
        "-quit",
        "-projectPath",
        str(project_path),
        "-executeMethod",
        "SoulTideBatchFxRecorder.BuildAndCaptureAll",
        "-fxManifest",
        str(manifest_path),
        "-logFile",
        str(log_path),
    ]
    print(f"[UnityBatch:{project_path.name}] Launching:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, check=False)
    print(f"[UnityBatch:{project_path.name}] Exit code: {proc.returncode}", flush=True)
    return proc.returncode


def run_unity_batch_parallel(
    skins: list[dict[str, Any]],
    unity_workers: int,
    log_dir: Path = UNITY_PROJ,
) -> int:
    """Run multiple isolated Unity 2021.3.34f1 batchmode GPU workers in parallel with load balancing."""
    n = max(1, min(unity_workers, len(skins)))
    if n == 1:
        return run_unity_batch(MANIFEST_PATH, DEFAULT_LOG_PATH, UNITY_PROJ)

    # Greedy LPT load-balancing by estimated frame/node cost
    def _skin_cost(s: dict[str, Any]) -> float:
        return sum(max(1.0, float(c.get("duration", 2.0))) * max(1, len(c.get("nodes", []))) for c in s.get("clips", []))

    buckets: list[list[dict[str, Any]]] = [[] for _ in range(n)]
    loads = [0.0] * n
    for sk in sorted(skins, key=_skin_cost, reverse=True):
        bi = min(range(n), key=lambda i: loads[i])
        buckets[bi].append(sk)
        loads[bi] += _skin_cost(sk)

    workers_root = TOOLS_DIR / "_unity_workers"
    if workers_root.exists():
        shutil.rmtree(workers_root, ignore_errors=True)
    workers_root.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    def _copy_dir_fast(src: Path, dst: Path) -> None:
        if os.name == "nt":
            dst.mkdir(parents=True, exist_ok=True)
            # Robocopy exit codes 0-7 indicate success on Windows
            res = subprocess.run(
                ["robocopy", str(src), str(dst), "/E", "/MT:16", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP"],
                check=False,
                capture_output=True,
            )
            if res.returncode <= 7:
                return
        shutil.copytree(src, dst, dirs_exist_ok=True)

    def _run_one_worker(idx: int) -> dict[str, Any]:
        wproj = workers_root / f"worker_{idx}"
        wproj.mkdir(parents=True, exist_ok=True)
        for sub in ("Assets", "Packages", "ProjectSettings", "Library"):
            src = UNITY_PROJ / sub
            if src.exists():
                _copy_dir_fast(src, wproj / sub)
        wmanifest = wproj / "fx_manifest.json"
        wlog = log_dir / f"batch_fx_unity_worker_{idx}.log"
        write_json(wmanifest, {"skins": buckets[idx]})
        print(f"[UnityWorker {idx}] Assigned {len(buckets[idx])} skins (est_cost={loads[idx]:.1f})", flush=True)
        rc = run_unity_batch(wmanifest, wlog, wproj)
        wsum_path = wproj / "batch_unity_summary.json"
        wsum = json.loads(wsum_path.read_text(encoding="utf-8-sig")) if wsum_path.is_file() else {"ok": 0, "errors": len(buckets[idx]), "items": []}
        return {"worker": idx, "rc": rc, "summary": wsum, "log": str(wlog)}

    try:
        with ThreadPoolExecutor(max_workers=n) as ex:
            results = list(ex.map(_run_one_worker, range(n)))
    finally:
        if os.name == "nt" and workers_root.exists():
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(workers_root)], check=False)
        shutil.rmtree(workers_root, ignore_errors=True)

    merged_items: list[Any] = []
    total_ok = 0
    total_err = 0
    final_rc = 0
    for r in results:
        if r["rc"] != 0:
            final_rc = r["rc"]
        s = r["summary"]
        total_ok += int(s.get("ok", 0))
        total_err += int(s.get("errors", 0))
        merged_items.extend(s.get("items", []))

    write_json(UNITY_PROJ / "batch_unity_summary.json", {"ok": total_ok, "errors": total_err, "items": merged_items})
    print(f"[UnityParallel] Combined ok={total_ok}, errors={total_err}, rc={final_rc}", flush=True)
    if final_rc == 0 and total_err > 0:
        final_rc = 1
    return final_rc


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch export and Unity-record SoulTide Spine FX.")
    parser.add_argument("--char", type=str, default="", help="Filter by character name substring")
    parser.add_argument("--skins", type=str, default="", help="Optional comma-separated skin_key filter")
    parser.add_argument("--ctrl", type=int, action="append", default=[], help="Filter by SpineActionControl ID")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of skins")
    parser.add_argument("--resume", action="store_true", help="Skip skins whose FX PNG sequences already exist")
    parser.add_argument("--export-only", action="store_true", help="Write fx_manifest.json and textures without launching Unity")
    parser.add_argument("--manifest-out", type=str, default="", help="Optional alternate manifest output path")
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)), help="Parallel AB indexing workers")
    parser.add_argument("--unity-workers", type=int, default=2, help="Parallel isolated Unity GPU batchmode workers")
    parser.add_argument("--chunk-size", type=int, default=0, help="Optional legacy chunk size per single-project Unity invocation")
    args = parser.parse_args()

    repo = FullI18nRepo()
    skins = build_skin_catalog(repo)
    if args.skins:
        sk_set = {x.strip().lower() for x in args.skins.split(",") if x.strip()}
        skins = [s for s in skins if s["skin_key"].lower() in sk_set]
    if args.char:
        skins = [s for s in skins if args.char in s["char_name"]]
    if args.ctrl:
        cset = set(args.ctrl)
        skins = [s for s in skins if s["ctrl_id"] in cset or any(c in cset for c in s["merged_ctrl_ids"])]
    if args.limit > 0:
        skins = skins[: args.limit]

    indexer = AssetIndexer(workers=args.workers)
    res = build_manifest(skins, indexer, skip_aurora_s4=False, resume=args.resume)
    manifest = {"skins": res["skins"]}
    out_manifest = Path(args.manifest_out) if args.manifest_out else MANIFEST_PATH
    write_json(out_manifest, manifest)
    total_clips = sum(len(s["clips"]) for s in manifest["skins"])
    print(
        f"[batch_fx_exporter] Manifest skins={len(manifest['skins'])}, clips={total_clips}, "
        f"new_textures={res['textures_extracted']}, wrap_modes={len(res.get('tex_wrap_modes', {}))} -> {out_manifest}",
        flush=True,
    )

    if args.export_only or not manifest["skins"]:
        return

    if not args.resume:
        for skm in manifest["skins"]:
            sdir = Path(skm["output_dir"])
            if sdir.exists():
                shutil.rmtree(sdir, ignore_errors=True)

    if args.unity_workers > 1:
        rc = run_unity_batch_parallel(manifest["skins"], args.unity_workers, UNITY_PROJ)
        if rc != 0:
            raise RuntimeError(f"Parallel Unity batch recorder failed with exit code {rc}")
    elif args.chunk_size > 0 and len(manifest["skins"]) > args.chunk_size:
        for i in range(0, len(manifest["skins"]), args.chunk_size):
            chunk = manifest["skins"][i : i + args.chunk_size]
            cpath = UNITY_PROJ / f"fx_manifest_chunk_{i // args.chunk_size}.json"
            write_json(cpath, {"skins": chunk})
            rc = run_unity_batch(cpath, UNITY_PROJ / f"batch_fx_unity_chunk_{i // args.chunk_size}.log")
            if rc != 0:
                print(f"[batch_fx_exporter] WARNING chunk {i} exited with code {rc}", flush=True)
    else:
        rc = run_unity_batch(MANIFEST_PATH, DEFAULT_LOG_PATH)
        if rc != 0:
            raise RuntimeError(f"Unity batch recorder failed with exit code {rc} (see {DEFAULT_LOG_PATH})")


if __name__ == "__main__":
    main()
