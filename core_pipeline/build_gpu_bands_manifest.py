"""Build Node-Level Hybrid GPU-Band Manifest for SoulTide Unity Zero-Crossfade Recorder.

Splits every skin's idle clips (`idle`, `idle_back`, `idle_front`) at the subEmitter-tree level:
- Pure native-eligible trees (no trails/mask/distort/dissolve/customMesh/rot3d/customData) are
  rescued completely from GPU frame-sequence recording and rendered as crisp 60 FPS Native Spine!
- Only GPU-blocked trees are emitted into `fx_gpu_bands_manifest.json`, partitioned into exact
  contiguous `(effSortOrder, dfsSeq)` bands so static images (e.g. `Mid` Order=3) and native
  particles can sandwich strictly between GPU bands inside ONE composite Spine 3.8 skeleton!
- All GPU bands on the same side share a single optimal period `T_gpu` so `T_loop = m * T_gpu`
  tiles cleanly with zero LCM blowup.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
SCRIPTS_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本")
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from batch_fx_exporter import _compute_optimal_gpu_period
from convert_fx_to_native_spine import compute_gpu_blocked_node_indices

UNITY_PROJ = TOOLS_DIR / "SoulTideBatchFxUnity"
SRC_MANIFEST = UNITY_PROJ / "fx_manifest.json"
OUT_MANIFEST = UNITY_PROJ / "fx_gpu_bands_manifest.json"
OUT_PLAN = UNITY_PROJ / "fx_gpu_bands_plan.json"
GPU_FRAMES_ROOT = TOOLS_DIR / "_batch_fx_gpu_v2"


def _extract_subemitter_trees(nodes: list[dict[str, Any]]) -> list[list[int]]:
    """Group node indices into root + descendant subEmitter trees."""
    n = len(nodes)
    visited: set[int] = set()
    trees: list[list[int]] = []

    def dfs(u: int, out: list[int]) -> None:
        if u < 0 or u >= n or u in visited:
            return
        visited.add(u)
        out.append(u)
        for se in (nodes[u].get("subEmitters") or []):
            dfs(int(se.get("targetIdx", -1)), out)

    for i, nd in enumerate(nodes):
        if nd.get("isSubEmitterChild"):
            continue
        if i not in visited:
            t: list[int] = []
            dfs(i, t)
            if t:
                trees.append(t)
    # Any orphaned child cycles
    for i in range(n):
        if i not in visited:
            t = []
            dfs(i, t)
            if t:
                trees.append(t)
    return trees


def _slice_and_reindex_nodes(nodes: list[dict[str, Any]], keep_indices: list[int]) -> list[dict[str, Any]]:
    """Slice a subset of clip nodes and re-index all `subEmitters[].targetIdx` cleanly."""
    keep_sorted = sorted(set(keep_indices))
    old_to_new = {old_i: new_i for new_i, old_i in enumerate(keep_sorted)}
    out: list[dict[str, Any]] = []
    for old_i in keep_sorted:
        nd = copy.deepcopy(nodes[old_i])
        if nd.get("subEmitters"):
            new_ses = []
            for se in nd["subEmitters"]:
                t_old = int(se.get("targetIdx", -1))
                if t_old in old_to_new:
                    nse = dict(se)
                    nse["targetIdx"] = old_to_new[t_old]
                    new_ses.append(nse)
            nd["subEmitters"] = new_ses
        out.append(nd)
    return out


def _pick_clean_gpu_period(gpu_nodes: list[dict[str, Any]]) -> float:
    """Pick optimal T_gpu from clean divisors/periods so T_loop = m * T_gpu stays compact."""
    raw_t = _compute_optimal_gpu_period(gpu_nodes)
    # Prefer clean 0.5s grid in [4.0, 10.0] favoring 4, 5, 6, 8, 10 for crisp multi-band tiling
    clean_cands = [4.0, 4.5, 5.0, 6.0, 7.5, 8.0, 9.0, 10.0]
    best = min(clean_cands, key=lambda c: abs(c - raw_t))
    return float(best)


def build_gpu_bands_manifest(
    src_manifest_path: Path = SRC_MANIFEST,
    out_manifest_path: Path = OUT_MANIFEST,
    out_plan_path: Path = OUT_PLAN,
    skin_filter: set[str] | None = None,
) -> dict[str, Any]:
    mf = json.loads(src_manifest_path.read_text(encoding="utf-8-sig"))
    out_skins: list[dict[str, Any]] = []
    plan: dict[str, Any] = {}

    stats = {
        "total_skins_in_manifest": 0,
        "skins_needing_gpu": 0,
        "idle_clips_total": 0,
        "idle_clips_pure_native": 0,
        "idle_clips_hybrid_or_gpu": 0,
        "idle_nodes_total": 0,
        "idle_nodes_native": 0,
        "idle_nodes_gpu": 0,
        "idle_gpu_bands": 0,
        "touch_clips_total": 0,
        "touch_clips_native": 0,
        "touch_clips_gpu": 0,
    }

    for skin in mf.get("skins") or []:
        sk = skin["skin_key"]
        if skin_filter and sk.lower() not in skin_filter:
            continue
        stats["total_skins_in_manifest"] += 1

        gpu_clips_for_skin: list[dict[str, Any]] = []
        skin_plan: dict[str, Any] = {"skin_key": sk, "output_dir": str(GPU_FRAMES_ROOT / sk), "clips": {}}

        for clip in skin.get("clips") or []:
            cname = clip["clip"]
            nodes = clip.get("nodes") or []
            if not nodes:
                continue
            is_idle = cname.lower().startswith("idle")
            blocked_set = compute_gpu_blocked_node_indices(nodes)

            if not is_idle:
                stats["touch_clips_total"] += 1
                if not blocked_set:
                    stats["touch_clips_native"] += 1
                    skin_plan["clips"][cname] = {
                        "kind": "touch",
                        "layer": clip.get("layer", "front"),
                        "mode": "native",
                        "native_node_indices": list(range(len(nodes))),
                        "gpu_bands": [],
                    }
                else:
                    stats["touch_clips_gpu"] += 1
                    c_copy = copy.deepcopy(clip)
                    c_copy["useZeroCrossfade"] = False
                    c_copy["crossfadeIdle"] = False
                    gpu_clips_for_skin.append(c_copy)
                    skin_plan["clips"][cname] = {
                        "kind": "touch",
                        "layer": clip.get("layer", "front"),
                        "mode": "gpu",
                        "native_node_indices": [],
                        "gpu_bands": [{
                            "gpu_clip": cname,
                            "eff_sort_order": min(int(n.get("effSortOrder", 0)) for n in nodes),
                            "min_dfs": min(int(n.get("dfsSeq", i)) for i, n in enumerate(nodes)),
                            "node_indices": list(range(len(nodes))),
                            "duration": float(clip.get("duration", 3.0)),
                            "fps": float(clip.get("fps", 20.0)),
                        }],
                    }
                continue

            # Idle clip: Node-Level Hybrid Split + Contiguous (effSortOrder, dfsSeq) GPU Banding!
            stats["idle_clips_total"] += 1
            stats["idle_nodes_total"] += len(nodes)
            trees = _extract_subemitter_trees(nodes)
            tree_recs = []
            for t_idxs in trees:
                is_gpu = any(i in blocked_set for i in t_idxs)
                eff_ord = min(int(nodes[i].get("effSortOrder", 0)) for i in t_idxs)
                min_dfs = min(int(nodes[i].get("dfsSeq", i)) for i in t_idxs)
                max_dfs = max(int(nodes[i].get("dfsSeq", i)) for i in t_idxs)
                tree_recs.append({
                    "idxs": t_idxs,
                    "is_gpu": is_gpu,
                    "eff_ord": eff_ord,
                    "min_dfs": min_dfs,
                    "max_dfs": max_dfs,
                })
            tree_recs.sort(key=lambda r: (r["eff_ord"], r["min_dfs"]))

            native_idxs = sorted(i for r in tree_recs if not r["is_gpu"] for i in r["idxs"])
            gpu_idxs = sorted(i for r in tree_recs if r["is_gpu"] for i in r["idxs"])
            stats["idle_nodes_native"] += len(native_idxs)
            stats["idle_nodes_gpu"] += len(gpu_idxs)

            if not gpu_idxs:
                stats["idle_clips_pure_native"] += 1
                skin_plan["clips"][cname] = {
                    "kind": "idle",
                    "layer": clip.get("layer", "front"),
                    "mode": "native",
                    "native_node_indices": native_idxs,
                    "gpu_bands": [],
                }
                continue

            stats["idle_clips_hybrid_or_gpu"] += 1
            # Pick ONE unified optimal T_gpu across all GPU nodes of this clip so all bands tile cleanly together!
            all_gpu_nodes = [nodes[i] for i in gpu_idxs]
            t_gpu_clip = _pick_clean_gpu_period(all_gpu_nodes)

            # Group consecutive GPU trees with identical eff_ord (breaking on any eff_ord change OR native tree between them!)
            bands: list[dict[str, Any]] = []
            cur_band: dict[str, Any] | None = None
            for tr in tree_recs:
                if not tr["is_gpu"]:
                    cur_band = None
                    continue
                if cur_band is None or cur_band["eff_ord"] != tr["eff_ord"]:
                    cur_band = {
                        "eff_ord": tr["eff_ord"],
                        "min_dfs": tr["min_dfs"],
                        "max_dfs": tr["max_dfs"],
                        "node_indices": list(tr["idxs"]),
                    }
                    bands.append(cur_band)
                else:
                    cur_band["min_dfs"] = min(cur_band["min_dfs"], tr["min_dfs"])
                    cur_band["max_dfs"] = max(cur_band["max_dfs"], tr["max_dfs"])
                    cur_band["node_indices"].extend(tr["idxs"])

            band_plan_entries = []
            for bi, bd in enumerate(bands):
                b_clip_name = f"{cname}__gb{bi:02d}_o{bd['eff_ord']}"
                b_nodes = _slice_and_reindex_nodes(nodes, bd["node_indices"])
                fps = float(clip.get("fps", 20.0))
                gpu_clips_for_skin.append({
                    "clip": b_clip_name,
                    "layer": clip.get("layer", "front"),
                    "duration": t_gpu_clip,
                    "fps": fps,
                    "warmup": float(clip.get("warmup", 4.0)),
                    "crossfadeIdle": False,
                    "useZeroCrossfade": True,
                    "nodes": b_nodes,
                })
                band_plan_entries.append({
                    "gpu_clip": b_clip_name,
                    "eff_sort_order": bd["eff_ord"],
                    "min_dfs": bd["min_dfs"],
                    "max_dfs": bd["max_dfs"],
                    "node_indices": sorted(set(bd["node_indices"])),
                    "duration": t_gpu_clip,
                    "fps": fps,
                })
                stats["idle_gpu_bands"] += 1

            skin_plan["clips"][cname] = {
                "kind": "idle",
                "layer": clip.get("layer", "front"),
                "mode": "hybrid" if native_idxs else "gpu",
                "native_node_indices": native_idxs,
                "gpu_period": t_gpu_clip,
                "gpu_bands": band_plan_entries,
            }

        plan[sk] = skin_plan
        if gpu_clips_for_skin:
            stats["skins_needing_gpu"] += 1
            s_copy = copy.deepcopy(skin)
            s_copy["output_dir"] = str(GPU_FRAMES_ROOT / sk)
            s_copy["clips"] = gpu_clips_for_skin
            out_skins.append(s_copy)

    out_manifest = {"skins": out_skins}
    out_manifest_path.write_text(json.dumps(out_manifest, ensure_ascii=False), encoding="utf-8")
    out_plan_path.write_text(json.dumps({"stats": stats, "skins": plan}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"Wrote GPU manifest ({len(out_skins)} skins) -> {out_manifest_path}")
    print(f"Wrote hybrid plan -> {out_plan_path}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Node-Level Hybrid GPU-Band manifest for Unity Recorder")
    ap.add_argument("--skins", type=str, default="", help="Optional comma-separated skin_key filter")
    ap.add_argument("--manifest-out", type=str, default=str(OUT_MANIFEST))
    ap.add_argument("--plan-out", type=str, default=str(OUT_PLAN))
    args = ap.parse_args()
    sf = {x.strip().lower() for x in args.skins.split(",") if x.strip()} if args.skins else None
    build_gpu_bands_manifest(
        src_manifest_path=SRC_MANIFEST,
        out_manifest_path=Path(args.manifest_out),
        out_plan_path=Path(args.plan_out),
        skin_filter=sf,
    )


if __name__ == "__main__":
    main()
