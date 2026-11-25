"""Comprehensive Background / Foreground Submodel Layout Auditor for ALL 163 SoulTide Spine Packages.

Audits every Spine package under `E:\\A灵魂潮汐\\Live2D与Spine模型\\spine` against:
  1. Original Unity `BgPrefabs` in `03_prefabs/ui.ab` and `03_prefabs/art_prefabs.ab`
  2. Exact Unity RectTransform / Transform math (anchors, pivot, sizeDelta, localScale X/Y, rotation, Canvas sortingOrder)
  3. Built `submodels/*/.config.json` & `.skel.json` (scale_factor, root bone x/y/sx/sy, bounds, animations, z-order)
  4. Interleaving between static Images, dynamic `bj_*` Spines, and `Person` (detecting mid-bg and fg-static layers)
  5. `原皮` packages & `fx_*` submodel alignment

Writes a detailed JSON report to `E:\\A灵魂潮汐\\tools\\bg_layout_audit_report.json`.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from batch_fx_exporter import (
    AssetIndexer,
    FullI18nRepo,
    SKIP_IMAGE_NAMES,
    _node_local_tf,
    _qmul,
    _qrot,
    build_skin_catalog,
    inspect_bg_prefab_layout,
)
from batch_spine_builder import SPINE_OUT_ROOT, parse_spine38_binary

REPORT_PATH = TOOLS_DIR / "bg_layout_audit_report.json"

# Both CABs seen in codebase for black letterbox bars
BLACK_LETTERBOX_CABS = {
    "CAB-74b9d108c9d0a1a5256f5c9547791b74",
    "CAB-055435a60c36b7081bba8594353412b1",
}


def _read_skel_info(skel_path: Path) -> dict[str, Any]:
    raw = skel_path.read_bytes()
    if raw.lstrip().startswith(b"{"):
        d = json.loads(raw.decode("utf-8"))
        sk = d.get("skeleton", {})
        bones = d.get("bones", [])
        b0 = bones[0] if bones else {}
        b1 = bones[1] if len(bones) > 1 else None
        return {
            "format": "json",
            "version": sk.get("spine", ""),
            "bounds": [float(sk.get("x", 0)), float(sk.get("y", 0)), float(sk.get("width", 0)), float(sk.get("height", 0))],
            "root": {
                "name": b0.get("name", "root"),
                "x": float(b0.get("x", 0)),
                "y": float(b0.get("y", 0)),
                "sx": float(b0.get("scaleX", 1)),
                "sy": float(b0.get("scaleY", 1)),
                "rot": float(b0.get("rotation", 0)),
            },
            "bone1": b1,
            "anims": list(d.get("animations", {}).keys()),
            "root_animated": any("root" in (a.get("bones") or {}) for a in d.get("animations", {}).values()),
        }
    p = parse_spine38_binary(raw)
    b0 = p["bones"][0] if p["bones"] else {}
    root_anim = any(0 in bt for bt in p["anim_bone_t0"].values())
    return {
        "format": "binary",
        "version": p["version"],
        "bounds": [float(v) for v in p["bounds"]],
        "root": {
            "name": b0.get("name", "root"),
            "x": float(b0.get("x", 0)),
            "y": float(b0.get("y", 0)),
            "sx": float(b0.get("sx", 1)),
            "sy": float(b0.get("sy", 1)),
            "rot": float(b0.get("rot", 0)),
        },
        "anims": p["anims"],
        "root_animated": root_anim,
    }


def _parse_unity_prefab_full(indexer: AssetIndexer, skin: dict[str, Any]) -> dict[str, Any]:
    bgp = skin["bg_prefab"]
    base = Path(bgp).name.lower()
    if base in indexer.ui_go_by_name:
        objs = indexer.ui_objs
        root_gid = indexer.ui_go_by_name[base][0]
    elif base in indexer.art_go_by_name:
        objs = indexer.art_objs
        root_gid = indexer.art_go_by_name[base][0]
    else:
        return {"error": f"BgPrefab {bgp} not found"}

    elements: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    dfs_seq = 0

    # In Unity UI, a Canvas sits at root with reference resolution (typically 1700x750 or root RectTransform sizeDelta).
    # For RectTransform children with non-center anchors/pivots, we compute exact rect center and size from parent rect!
    def walk(
        gid: int,
        depth: int,
        ppos: tuple[float, float, float],
        pscale: tuple[float, float, float],
        pq: tuple[float, float, float, float],
        parent_rect_size: tuple[float, float],
        parent_pivot: tuple[float, float],
        path: str,
        in_harm: bool,
        cur_sort_order: int,
    ):
        nonlocal dfs_seq
        go = objs[gid].read()
        nm = go.m_Name
        low = nm.lower()
        cur_path = f"{path}/{nm}" if path else nm
        in_harm_here = in_harm or ("harmonious" in low)

        if not go.m_IsActive:
            return
        if in_harm_here or "hitarea" in low or "cv_point" in low:
            return

        rt, is_rect, (lx, ly, lz), (sx, sy, sz), lq = _node_local_tf(go, objs, ignore_root_pos=(depth == 0))

        # Check SortingOrder from Canvas or Order MonoBehaviour
        sort_order = cur_sort_order
        for c in go.m_Component:
            co = objs.get(c.component.path_id)
            if not co:
                continue
            if co.type.name == "Canvas":
                try:
                    ctt = co.read_typetree()
                    if ctt.get("m_OverrideSorting"):
                        sort_order = int(ctt.get("m_SortingOrder", sort_order))
                except Exception:
                    pass
            elif co.type.name == "MonoBehaviour":
                try:
                    tt = co.read_typetree()
                    if "Order" in tt:
                        sort_order = int(tt["Order"])
                except Exception:
                    pass

        # Exact RectTransform calculation vs current _node_local_tf
        rect_w = rect_h = 0.0
        piv_x = piv_y = 0.5
        amin_x = amin_y = amax_x = amax_y = 0.5
        exact_lx, exact_ly = lx, ly
        center_dx_local = center_dy_local = 0.0
        is_non_default_rect = False

        if is_rect and rt is not None:
            sd = rt.m_SizeDelta
            amin = rt.m_AnchorMin
            amax = rt.m_AnchorMax
            piv = rt.m_Pivot
            ap = rt.m_AnchoredPosition
            lpos = rt.m_LocalPosition

            amin_x, amin_y = float(amin.x), float(amin.y)
            amax_x, amax_y = float(amax.x), float(amax.y)
            piv_x, piv_y = float(piv.x), float(piv.y)

            pw, ph = parent_rect_size
            ppiv_x, ppiv_y = parent_pivot

            if depth == 0:
                rect_w, rect_h = float(sd.x), float(sd.y)
                exact_lx, exact_ly = 0.0, 0.0
            else:
                rect_w = pw * (amax_x - amin_x) + float(sd.x)
                rect_h = ph * (amax_y - amin_y) + float(sd.y)
                # Anchor reference point relative to parent pivot:
                # Parent rect spans [-ppiv_x * pw, (1-ppiv_x) * pw]
                # Anchor point for pivot in parent local space:
                anchor_x = (amin_x + (amax_x - amin_x) * piv_x - ppiv_x) * pw
                anchor_y = (amin_y + (amax_y - amin_y) * piv_y - ppiv_y) * ph
                exact_lx = anchor_x + float(ap.x)
                exact_ly = anchor_y + float(ap.y)

                if (
                    abs(amin_x - 0.5) > 1e-3
                    or abs(amin_y - 0.5) > 1e-3
                    or abs(amax_x - 0.5) > 1e-3
                    or abs(amax_y - 0.5) > 1e-3
                    or abs(piv_x - 0.5) > 1e-3
                    or abs(piv_y - 0.5) > 1e-3
                ):
                    is_non_default_rect = True

            # Offset from this node's pivot to its geometric center in local space
            center_dx_local = (0.5 - piv_x) * rect_w
            center_dy_local = (0.5 - piv_y) * rect_h
        else:
            rect_w, rect_h = 0.0, 0.0

        # Old (current pipeline) world pos
        rx_old, ry_old, rz_old = _qrot(pq, (lx * pscale[0], ly * pscale[1], lz * pscale[2]))
        wx_old, wy_old, wz_old = ppos[0] + rx_old, ppos[1] + ry_old, ppos[2] + rz_old

        # Exact world pos of pivot
        rx, ry, rz = _qrot(pq, (exact_lx * pscale[0], exact_ly * pscale[1], lz * pscale[2]))
        wx, wy, wz = ppos[0] + rx, ppos[1] + ry, ppos[2] + rz
        wsx, wsy, wsz = pscale[0] * sx, pscale[1] * sy, pscale[2] * sz
        wq = _qmul(pq, lq)
        z_deg = math.degrees(2.0 * math.atan2(wq[2], wq[3]))

        # Exact geometric center of Image in world space
        cdx, cdy, _ = _qrot(wq, (center_dx_local * wsx, center_dy_local * wsy, 0.0))
        img_cx, img_cy = wx + cdx, wy + cdy

        for c in go.m_Component:
            co = objs.get(c.component.path_id)
            if not co or co.type.name != "MonoBehaviour":
                continue
            try:
                tt = co.read_typetree()
                sn = objs[tt["m_Script"]["m_PathID"]].peek_name() if tt.get("m_Script", {}).get("m_PathID") in objs else ""
                if "m_Sprite" in tt and low not in SKIP_IMAGE_NAMES:
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
                    sd = rt.m_SizeDelta if is_rect else None
                    old_w = float(sd.x) * abs(wsx) if sd else 0.0
                    old_h = float(sd.y) * abs(wsy) if sd else 0.0
                    exact_w = rect_w * abs(wsx)
                    exact_h = rect_h * abs(wsy)
                    if exact_w <= 1.0 and old_w <= 1.0:
                        continue
                    dfs_seq += 1
                    el = {
                        "kind": "image",
                        "name": nm,
                        "path": cur_path,
                        "dfs": dfs_seq,
                        "sort_order": sort_order,
                        "wx": round(img_cx, 2),
                        "wy": round(img_cy, 2),
                        "wx_old": round(wx_old, 2),
                        "wy_old": round(wy_old, 2),
                        "w": round(exact_w, 2),
                        "h": round(exact_h, 2),
                        "w_old": round(old_w, 2),
                        "h_old": round(old_h, 2),
                        "wsx": round(wsx, 5),
                        "wsy": round(wsy, 5),
                        "z_deg": round(z_deg, 2),
                        "non_default_rect": is_non_default_rect,
                        "anchor_min": [round(amin_x, 3), round(amin_y, 3)],
                        "anchor_max": [round(amax_x, 3), round(amax_y, 3)],
                        "pivot": [round(piv_x, 3), round(piv_y, 3)],
                        "preserve_aspect": bool(tt.get("m_PreserveAspect", 0)),
                        "cab": cab,
                        "pid": pid,
                    }
                    elements.append(el)
                    if (
                        abs(img_cx - wx_old) > 2.0
                        or abs(img_cy - wy_old) > 2.0
                        or abs(exact_w - old_w) > 2.0
                        or abs(exact_h - old_h) > 2.0
                    ):
                        anomalies.append({
                            "type": "image_rect_mismatch",
                            "name": nm,
                            "path": cur_path,
                            "old": [round(wx_old, 1), round(wy_old, 1), round(old_w, 1), round(old_h, 1)],
                            "exact": [round(img_cx, 1), round(img_cy, 1), round(exact_w, 1), round(exact_h, 1)],
                            "anchor_min": el["anchor_min"],
                            "anchor_max": el["anchor_max"],
                            "pivot": el["pivot"],
                        })
                elif "skeletonDataAsset" in tt and "cloud" not in low:
                    sref = tt["skeletonDataAsset"]
                    sda = indexer.resolve_sda(co.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
                    if not sda or not sda["skel_cpath"]:
                        continue
                    is_graphic = "Graphic" in sn
                    is_person = ("person" in low) and not any(t in low for t in ("_bg_", "_bj_"))
                    sda_sc = float(sda["scale"])
                    mult = 100.0 if is_graphic else 1.0
                    ux = wsx * sda_sc * mult
                    uy = wsy * sda_sc * mult
                    flip_x = bool(tt.get("initialFlipX", 0))
                    flip_y = bool(tt.get("initialFlipY", 0))
                    if flip_x:
                        ux = -ux
                    if flip_y:
                        uy = -uy
                    dfs_seq += 1
                    el = {
                        "kind": "person" if is_person else "spine_sub",
                        "name": nm,
                        "path": cur_path,
                        "dfs": dfs_seq,
                        "sort_order": sort_order,
                        "is_graphic": is_graphic,
                        "script": sn,
                        "sda_scale": round(sda_sc, 6),
                        "ab_name": sda["ab_name"],
                        "skel_cpath": sda["skel_cpath"],
                        "wx": round(wx, 2),
                        "wy": round(wy, 2),
                        "wz": round(wz, 2),
                        "wx_old": round(wx_old, 2),
                        "wy_old": round(wy_old, 2),
                        "wsx": round(wsx, 5),
                        "wsy": round(wsy, 5),
                        "ux": round(ux, 6),
                        "uy": round(uy, 6),
                        "z_deg": round(z_deg, 2),
                        "flip_x": flip_x,
                        "flip_y": flip_y,
                        "anim": tt.get("startingAnimation") or tt.get("_animationName") or "idle",
                        "under_spine_scale": "spine_scale" in cur_path.lower(),
                        "non_default_rect": is_non_default_rect,
                    }
                    elements.append(el)
                    if abs(abs(ux) - abs(uy)) / max(1e-6, abs(ux), abs(uy)) > 0.01:
                        anomalies.append({
                            "type": "spine_non_uniform_scale",
                            "kind": el["kind"],
                            "name": nm,
                            "ux": el["ux"],
                            "uy": el["uy"],
                            "ratio_y_over_x": round(uy / ux, 4) if abs(ux) > 1e-6 else None,
                        })
                    if ux < 0 or uy < 0:
                        anomalies.append({
                            "type": "spine_negative_scale",
                            "kind": el["kind"],
                            "name": nm,
                            "ux": el["ux"],
                            "uy": el["uy"],
                            "flip_x": flip_x,
                            "flip_y": flip_y,
                        })
                    if abs(z_deg) > 0.5 and abs(abs(z_deg) - 360.0) > 0.5:
                        anomalies.append({
                            "type": "spine_rotated",
                            "kind": el["kind"],
                            "name": nm,
                            "z_deg": el["z_deg"],
                        })
                    if abs(wx - wx_old) > 2.0 or abs(wy - wy_old) > 2.0:
                        anomalies.append({
                            "type": "spine_anchor_pos_mismatch",
                            "kind": el["kind"],
                            "name": nm,
                            "old": [round(wx_old, 1), round(wy_old, 1)],
                            "exact": [round(wx, 1), round(wy, 1)],
                        })
            except Exception:
                pass

        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in objs:
                    walk(
                        objs[ch.path_id].read().m_GameObject.path_id,
                        depth + 1,
                        (wx, wy, wz),
                        (wsx, wsy, wsz),
                        wq,
                        (rect_w, rect_h) if is_rect else parent_rect_size,
                        (piv_x, piv_y) if is_rect else parent_pivot,
                        cur_path,
                        in_harm_here,
                        sort_order,
                    )

    walk(root_gid, 0, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (1700.0, 750.0), (0.5, 0.5), "", False, 0)

    # Sort elements in Unity actual draw order: (sort_order, dfs)
    ordered = sorted(elements, key=lambda e: (e["sort_order"], e["dfs"]))
    return {"elements": ordered, "anomalies": anomalies}


def main() -> None:
    repo = FullI18nRepo()
    catalog = build_skin_catalog(repo)
    cat_by_pair = {(s["char_name"], s["dress_name"]): s for s in catalog}

    indexer = AssetIndexer(light=True)

    skin_dirs = sorted(p.parent for p in SPINE_OUT_ROOT.glob("*/*/.config.json"))
    print(f"[audit] Scanning {len(skin_dirs)} Spine packages (catalog={len(catalog)})...", flush=True)

    findings: list[dict[str, Any]] = []
    summary_counts: dict[str, int] = defaultdict(int)

    for sdir in skin_dirs:
        rel = str(sdir.relative_to(SPINE_OUT_ROOT)).replace("\\", "/")
        char_name, dress_name = rel.split("/", 1)
        cfg = json.loads((sdir / ".config.json").read_text(encoding="utf-8"))
        base_scale = float(cfg["options"]["scale_factor"])

        # Parse built submodels from start command
        start_items = cfg.get("motions", {}).get("start", [])
        start_cmd = start_items[0].get("command", "") if start_items else ""
        built_subs: list[dict[str, Any]] = []
        for cmd in start_cmd.split(";"):
            cmd = cmd.strip()
            if not cmd:
                continue
            toks = cmd.split()
            if len(toks) == 3 and toks[0] == "add_submodel":
                sub_rel, ord_s = toks[1], int(toks[2])
                sub_cfg_p = sdir / sub_rel
                sub_cfg = json.loads(sub_cfg_p.read_text(encoding="utf-8"))
                sk_info = _read_skel_info(sub_cfg_p.parent / sub_cfg["skeleton"])
                built_subs.append({
                    "rel": sub_rel,
                    "folder": sub_cfg_p.parent.name,
                    "order": ord_s,
                    "id": sub_cfg["options"]["id"],
                    "scale_factor": float(sub_cfg["options"]["scale_factor"]),
                    "pos_x": float(sub_cfg["options"]["position_x"]),
                    "pos_y": float(sub_cfg["options"]["position_y"]),
                    "skel": sk_info,
                })

        sk = cat_by_pair.get((char_name, dress_name))
        if sk is None:
            # Orig skin or special
            if built_subs:
                summary_counts["orig_with_submodels"] += 1
                findings.append({"skin": rel, "type": "non_catalog_with_subs", "built_subs": built_subs})
            continue

        layout = inspect_bg_prefab_layout(indexer, sk)
        prefab = _parse_unity_prefab_full(indexer, sk)
        if "error" in prefab:
            findings.append({"skin": rel, "issues": [{"type": "prefab_missing", "detail": prefab["error"]}]})
            summary_counts["prefab_missing"] += 1
            continue

        issues: list[dict[str, Any]] = list(prefab["anomalies"])
        ordered = prefab["elements"]

        # Find Person element in ordered draw list
        person_els = [e for e in ordered if e["kind"] == "person"]
        person_el = person_els[0] if person_els else None
        p_key = (person_el["sort_order"], person_el["dfs"]) if person_el else (layout.get("person_order") or 3, 999999)
        p_ux = person_el["ux"] if person_el else float(layout["person"]["ui_per_spine"])
        p_uy = person_el["uy"] if person_el else float(layout["person"]["ui_per_spine"])
        p_wx = person_el["wx"] if person_el else float(layout["person"]["wx"])
        p_wy = person_el["wy"] if person_el else float(layout["person"]["wy"])

        # 1. Check static Image interleaving relative to bj_* spines and Person
        spine_subs = [e for e in ordered if e["kind"] == "spine_sub"]
        img_els = [e for e in ordered if e["kind"] == "image"]

        # Are there static images AFTER Person?
        fg_images = [im for im in img_els if (im["sort_order"], im["dfs"]) > p_key]
        if fg_images:
            issues.append({
                "type": "fg_static_image_flattened_behind_person",
                "count": len(fg_images),
                "names": [f"{im['name']}(ord={im['sort_order']},w={im['w']}x{im['h']})" for im in fg_images],
            })

        # Are there static images behind Person that are AFTER a behind-Person spine_sub?
        back_spines = [sp for sp in spine_subs if (sp["sort_order"], sp["dfs"]) < p_key]
        if back_spines:
            earliest_back_sp = min((sp["sort_order"], sp["dfs"]) for sp in back_spines)
            mid_images = [
                im for im in img_els
                if earliest_back_sp < (im["sort_order"], im["dfs"]) < p_key
            ]
            if mid_images:
                issues.append({
                    "type": "mid_static_image_flattened_behind_bj",
                    "count": len(mid_images),
                    "names": [f"{im['name']}(ord={im['sort_order']},w={im['w']}x{im['h']})" for im in mid_images],
                    "bj_before": [sp["name"] for sp in back_spines if (sp["sort_order"], sp["dfs"]) < max((im["sort_order"], im["dfs"]) for im in mid_images)],
                })

        # 2. Check duplicate Spine submodels (same skel_cpath at different positions)
        by_skel: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for sp in spine_subs:
            by_skel[sp["skel_cpath"].lower()].append(sp)
        for k_sk, lst in by_skel.items():
            if len(lst) > 1:
                distinct_pos = any(
                    math.hypot(a["wx"] - b["wx"], a["wy"] - b["wy"]) > 5.0
                    or abs(a["ux"] - b["ux"]) > 0.01
                    or abs(a["uy"] - b["uy"]) > 0.01
                    for a in lst for b in lst
                )
                if distinct_pos:
                    issues.append({
                        "type": "duplicate_bj_skel_dropped",
                        "skel": Path(k_sk).name,
                        "instances": [{"name": x["name"], "w": [x["wx"], x["wy"]], "u": [x["ux"], x["uy"]]} for x in lst],
                    })

        # 3. Compare EVERY spine_sub against built bj_* submodels
        built_bj = [b for b in built_subs if not b["folder"].startswith(("bg_static", "fx_"))]
        for sp in spine_subs:
            sp_stem = Path(sp["skel_cpath"]).name[:-len(".skel.bytes")].lower()
            expected_front = (sp["sort_order"], sp["dfs"]) > p_key
            # Match to built_bj by skeleton filename stem
            matched = None
            for bb in built_bj:
                bb_stem = Path(bb["rel"]).parent.name
                # also check skeleton file inside bb
                sub_cfg = json.loads((sdir / bb["rel"]).read_text(encoding="utf-8"))
                sk_stem = Path(sub_cfg["skeleton"]).name[:-len(".skel.json")].lower()
                if sk_stem == sp_stem:
                    matched = bb
                    break

            if matched is None:
                issues.append({
                    "type": "spine_sub_missing_in_build",
                    "name": sp["name"],
                    "skel": sp_stem,
                    "expected_front": expected_front,
                    "total_spine_subs": len(spine_subs),
                    "total_built_subs": len(built_subs),
                })
                continue

            # Check front/back order
            built_front = matched["order"] > 0
            if built_front != expected_front:
                issues.append({
                    "type": "bj_zorder_wrong_side",
                    "folder": matched["folder"],
                    "name": sp["name"],
                    "built_order": matched["order"],
                    "unity_sort_order": sp["sort_order"],
                    "person_sort_order": p_key[0],
                    "expected_front": expected_front,
                })

            # Check X and Y scale & position accuracy!
            # Screen_x = S_sub * (root.x + root.sx * vx)
            # Expected screen_x = S_main * ((sp.wx - p_wx)/p_ux + (sp.ux/p_ux) * vx)
            s_ratio = matched["scale_factor"] / max(1e-6, base_scale)
            built_eff_rx = s_ratio * matched["skel"]["root"]["sx"]
            built_eff_ry = s_ratio * matched["skel"]["root"]["sy"]
            exp_rx = sp["ux"] / p_ux if abs(p_ux) > 1e-6 else 1.0
            exp_ry = sp["uy"] / p_uy if abs(p_uy) > 1e-6 else 1.0

            built_dx_ui = matched["skel"]["root"]["x"] * s_ratio * p_ux
            built_dy_ui = matched["skel"]["root"]["y"] * s_ratio * p_uy
            exp_dx_ui = sp["wx"] - p_wx
            exp_dy_ui = sp["wy"] - p_wy

            err_sx = abs(built_eff_rx - exp_rx) / max(1e-5, abs(exp_rx))
            err_sy = abs(built_eff_ry - exp_ry) / max(1e-5, abs(exp_ry))
            err_dx = abs(built_dx_ui - exp_dx_ui)
            err_dy = abs(built_dy_ui - exp_dy_ui)

            if err_sx > 0.02 or err_sy > 0.02 or err_dx > 4.0 or err_dy > 4.0:
                issues.append({
                    "type": "bj_transform_mismatch",
                    "folder": matched["folder"],
                    "name": sp["name"],
                    "skel": sp_stem,
                    "is_graphic": sp["is_graphic"],
                    "under_spine_scale": sp["under_spine_scale"],
                    "unity_u": [sp["ux"], sp["uy"]],
                    "person_u": [round(p_ux, 6), round(p_uy, 6)],
                    "exp_ratio": [round(exp_rx, 4), round(exp_ry, 4)],
                    "built_ratio": [round(built_eff_rx, 4), round(built_eff_ry, 4)],
                    "exp_dxy_ui": [round(exp_dx_ui, 1), round(exp_dy_ui, 1)],
                    "built_dxy_ui": [round(built_dx_ui, 1), round(built_dy_ui, 1)],
                    "root_animated": matched["skel"]["root_animated"],
                    "bounds": [round(v, 1) for v in matched["skel"]["bounds"]],
                })

            # Also flag suspiciously tiny or huge rendered UI size of bj_* (e.g. Spine_Scale bug!)
            bw, bh = matched["skel"]["bounds"][2], matched["skel"]["bounds"][3]
            ui_w = abs(bw * sp["ux"])
            ui_h = abs(bh * sp["uy"])
            if (ui_w > 0 and ui_w < 80 and bw > 500) or ui_w > 4500:
                issues.append({
                    "type": "bj_suspicious_ui_size",
                    "folder": matched["folder"],
                    "name": sp["name"],
                    "bw_bh": [round(bw, 1), round(bh, 1)],
                    "unity_ui_wh": [round(ui_w, 1), round(ui_h, 1)],
                    "is_graphic": sp["is_graphic"],
                    "under_spine_scale": sp["under_spine_scale"],
                    "wsx_wsy": [sp["wsx"], sp["wsy"]],
                    "sda_scale": sp["sda_scale"],
                })

        # 4. Check bg_static coverage & canvas clipping
        bg_static_sub = next((b for b in built_subs if b["folder"] == "bg_static"), None)
        if bg_static_sub and img_els:
            cw, ch = layout["canvas_w"], layout["canvas_h"]
            cam_x, cam_y = layout["cam_x"], layout["cam_y"]
            cx0, cx1 = cam_x - cw / 2.0, cam_x + cw / 2.0
            cy0, cy1 = cam_y - ch / 2.0, cam_y + ch / 2.0
            for im in img_els:
                if any(k in im["name"].lower() for k in ("shadow", "lift", "limit", "mask")):
                    continue
                ix0, ix1 = im["wx"] - im["w"] / 2.0, im["wx"] + im["w"] / 2.0
                iy0, iy1 = im["wy"] - im["h"] / 2.0, im["wy"] + im["h"] / 2.0
                # Check if image extends significantly outside canvas (> 80px) while overlapping canvas
                if ix1 < cx0 or ix0 > cx1 or iy1 < cy0 or iy0 > cy1:
                    issues.append({
                        "type": "bg_image_outside_canvas",
                        "name": im["name"],
                        "img_box": [round(ix0, 1), round(iy0, 1), round(ix1, 1), round(iy1, 1)],
                        "canvas_box": [round(cx0, 1), round(cy0, 1), round(cx1, 1), round(cy1, 1)],
                    })

        if issues:
            for iss in issues:
                summary_counts[iss["type"]] += 1
            findings.append({
                "skin": rel,
                "skin_key": sk["skin_key"],
                "bg_prefab": sk["bg_prefab"],
                "base_scale": base_scale,
                "canvas": [layout["canvas_w"], layout["canvas_h"], layout["cam_x"], layout["cam_y"]],
                "built_sub_orders": [(b["folder"], b["order"], b["scale_factor"]) for b in built_subs],
                "issues": issues,
            })

    report = {
        "total_packages_scanned": len(skin_dirs),
        "packages_with_issues": len(findings),
        "summary_counts": dict(sorted(summary_counts.items())),
        "findings": findings,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "total_packages_scanned": report["total_packages_scanned"],
        "packages_with_issues": report["packages_with_issues"],
        "summary_counts": report["summary_counts"],
        "report_path": str(REPORT_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
