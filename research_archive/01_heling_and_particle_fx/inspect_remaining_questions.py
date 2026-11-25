"""Inspect all 5 remaining investigation areas for SoulTide Unity FX particle audit."""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe
from soultide_common import CDN_ROOT, load_ab


def _quat_to_mat(q):
    x, y, z, w = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def _mat_mul3(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _parse_obj_bounds(obj_text: str):
    xs, ys, zs = [], [], []
    tris = 0
    for line in obj_text.splitlines():
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                xs.append(float(parts[1]))
                ys.append(float(parts[2]))
                zs.append(float(parts[3]))
        elif line.startswith("f "):
            tris += 1
    if not xs:
        return None
    return {
        "verts": len(xs),
        "faces": tris,
        "min": [round(min(xs), 4), round(min(ys), 4), round(min(zs), 4)],
        "max": [round(max(xs), 4), round(max(ys), 4), round(max(zs), 4)],
        "extent": [round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4), round(max(zs) - min(zs), 4)],
    }


def resolve_ext_any(obj_by_cab_pid, assets_file, file_id: int, path_id: int):
    if path_id == 0:
        return None
    if file_id == 0:
        cab = assets_file.name
    else:
        ext_idx = file_id - 1
        if ext_idx < 0 or ext_idx >= len(assets_file.externals):
            return None
        ext_path = assets_file.externals[ext_idx].path
        cab = Path(ext_path).name
    return obj_by_cab_pid.get((cab, path_id))


def dump_go_tree(go_pid: int, objs: dict, depth: int = 0, max_depth: int = 8):
    go = objs.get(go_pid)
    if not go:
        return []
    g = go.read()
    lines = []
    rt_info = ""
    comps = []
    rt_obj = None
    for c in g.m_Component:
        co = objs.get(c.component.path_id)
        if not co:
            continue
        cname = co.type.name
        comps.append(cname)
        if cname in ("RectTransform", "Transform"):
            rt_obj = co.read()
            pos = rt_obj.m_LocalPosition
            sc = rt_obj.m_LocalScale
            lr = rt_obj.m_LocalRotation
            if cname == "RectTransform":
                ap = rt_obj.m_AnchoredPosition
                sd = rt_obj.m_SizeDelta
                amin = rt_obj.m_AnchorMin
                amax = rt_obj.m_AnchorMax
                rt_info = (
                    f"RT ap=({ap.x:.2f},{ap.y:.2f}) posz={pos.z:.2f} sd=({sd.x:.1f},{sd.y:.1f}) "
                    f"anc=({amin.x:.2f},{amin.y:.2f}..{amax.x:.2f},{amax.y:.2f}) "
                    f"lsc=({sc.x:.4f},{sc.y:.4f},{sc.z:.4f}) rot=({lr.x:.3f},{lr.y:.3f},{lr.z:.3f},{lr.w:.3f})"
                )
            else:
                rt_info = (
                    f"TF pos=({pos.x:.2f},{pos.y:.2f},{pos.z:.2f}) "
                    f"lsc=({sc.x:.4f},{sc.y:.4f},{sc.z:.4f}) rot=({lr.x:.3f},{lr.y:.3f},{lr.z:.3f},{lr.w:.3f})"
                )
        elif cname == "Canvas":
            tt = co.read_typetree()
            rt_info += f" | Canvas(rm={tt.get('m_RenderMode')}, order={tt.get('m_SortingOrder')}, pd={tt.get('m_PlaneDistance')})"
        elif cname == "Camera":
            tt = co.read_typetree()
            rt_info += f" | Camera(ortho={tt.get('orthographic')}, size={tt.get('orthographic size')}, near={tt.get('near clip plane')}, far={tt.get('far clip plane')})"
        elif cname == "SkeletonGraphic":
            tt = co.read_typetree()
            rt_info += f" | SkeletonGraphic(anim={tt.get('startingAnimation')})"
        elif cname == "ParticleSystem":
            tt = co.read_typetree()
            rt_info += f" | PS(sm={tt.get('scalingMode')}, maxP={tt.get('InitialModule',{}).get('maxNumParticles')}, dur={tt.get('lengthInSec'):.2f}, delay={tt.get('startDelay',{}).get('scalar'):.2f})"
        elif cname == "ParticleSystemRenderer":
            tt = co.read_typetree()
            rt_info += f" | PSR(rm={tt.get('m_RenderMode')}, sort={tt.get('m_SortingOrder')}, maxPS={tt.get('m_MaxParticleSize')}, align={tt.get('m_RenderAlignment')})"
    active = getattr(g, "m_IsActive", True)
    lines.append(f"{'  ' * depth}[{g.m_Name}] active={active} {rt_info} comps={comps}")
    if rt_obj and depth < max_depth:
        for ch in rt_obj.m_Children:
            ch_tf = objs.get(ch.path_id)
            if ch_tf:
                t = ch_tf.read()
                ch_go_pid = t.m_GameObject.path_id
                lines.extend(dump_go_tree(ch_go_pid, objs, depth + 1, max_depth))
    return lines


def find_ps_in_prefab(prefab_name: str, objs: dict, go_by_name: dict):
    base = Path(prefab_name).name.lower()
    pids = go_by_name.get(base, [])
    if not pids:
        return []
    out = []

    def walk(gid, path, parent_ws):
        go = objs.get(gid)
        if not go:
            return
        g = go.read()
        tf_obj = None
        ps_tt = None
        psr_tt = None
        for c in g.m_Component:
            co = objs.get(c.component.path_id)
            if not co:
                continue
            if co.type.name in ("Transform", "RectTransform"):
                tf_obj = co.read()
            elif co.type.name == "ParticleSystem":
                ps_tt = co.read_typetree()
            elif co.type.name == "ParticleSystemRenderer":
                psr_tt = co.read_typetree()
        if tf_obj:
            ls = tf_obj.m_LocalScale
            lp = tf_obj.m_LocalPosition
            ws = [parent_ws[0] * ls.x, parent_ws[1] * ls.y, parent_ws[2] * ls.z]
        else:
            ls = lp = None
            ws = list(parent_ws)
        cur_path = f"{path}/{g.m_Name}" if path else g.m_Name
        if ps_tt is not None:
            out.append({
                "path": cur_path,
                "active": getattr(g, "m_IsActive", True),
                "lpos": [lp.x, lp.y, lp.z] if lp else None,
                "lsc": [ls.x, ls.y, ls.z] if ls else None,
                "wsc_from_prefab": ws,
                "ps": ps_tt,
                "psr": psr_tt,
                "assets_file": go.assets_file,
            })
        if tf_obj:
            for ch in tf_obj.m_Children:
                ctf = objs.get(ch.path_id)
                if ctf:
                    walk(ctf.read().m_GameObject.path_id, cur_path, ws)

    walk(pids[0], "", [1.0, 1.0, 1.0])
    return out


def main():
    manifest = json.loads(Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json").read_text(encoding="utf-8"))
    skins_by_key = {s["skin_key"]: s for s in manifest["skins"]}

    # Index EVERYTHING (including Mesh!) + Shaders + Prefabs
    print("=== Indexing all ABs (Materials, Textures, Shaders, Meshes) ===")
    obj_by_cab_pid = {}
    mesh_objs = {}
    shader_props = {}  # (cab, pid) -> {name, props}
    shader_by_name = {}
    tex_by_name = {}
    for sub_dir in ("14_effect", "15_shader", "03_prefabs"):
        for ab in sorted((CDN_ROOT / sub_dir).rglob("*.ab")):
            env = load_ab(ab)
            for obj in env.objects:
                cab = obj.assets_file.name
                tname = obj.type.name
                if tname in ("Material", "Texture2D", "Shader", "Sprite", "Mesh"):
                    obj_by_cab_pid[(cab, obj.path_id)] = (obj, ab.name)
                if tname == "Mesh":
                    mesh_objs[(cab, obj.path_id)] = (obj, ab.name)
                elif tname == "Texture2D":
                    nm = obj.peek_name()
                    if nm:
                        tex_by_name.setdefault(nm.lower(), (obj, ab.name))
                elif tname == "Shader":
                    try:
                        tt = obj.read_typetree()
                        pf = tt.get("m_ParsedForm", {})
                        sname = pf.get("m_Name") or tt.get("m_Name") or ""
                        props = []
                        for p in pf.get("m_PropInfo", {}).get("m_Props", []):
                            props.append({
                                "name": p.get("m_Name"),
                                "type": p.get("m_Type"),  # 0=Color,1=Vector,2=Float,3=Range,4=TexEnv
                                "def": p.get("m_DefValue"),
                            })
                        info = {"name": sname, "ab": ab.name, "props": props, "prop_names": {p["name"] for p in props}}
                        shader_props[(cab, obj.path_id)] = info
                        if sname:
                            shader_by_name[sname] = info
                    except Exception as e:
                        print(f"Shader parse err {ab.name} {obj.path_id}: {e}")

    ui_env = load_ab(CDN_ROOT / "03_prefabs/ui.ab")
    art_env = load_ab(CDN_ROOT / "03_prefabs/art_prefabs.ab")
    ui_objs = {o.path_id: o for o in ui_env.objects}
    art_objs = {o.path_id: o for o in art_env.objects}
    ui_go = defaultdict(list)
    for o in ui_env.objects:
        if o.type.name == "GameObject" and o.peek_name():
            ui_go[o.peek_name().lower()].append(o.path_id)
    art_go = defaultdict(list)
    for o in art_env.objects:
        if o.type.name == "GameObject" and o.peek_name():
            art_go[o.peek_name().lower()].append(o.path_id)

    repo = bfe.FullI18nRepo()
    catalog_list = bfe.build_skin_catalog(repo)
    skin_cat_map = {c["skin_key"]: c for c in catalog_list}

    # =========================================================================
    # SECTION 1: 402_Freesia_S5 (Freesia_S5_Background & fx_9008161)
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 1: 402_Freesia_S5 (Freesia_S5_Background & FX_Freesia_S5_Background_Touch01)")
    print("=" * 80)
    if "freesia_s5_background" in ui_go:
        print("--- Freesia_S5_Background hierarchy in ui.ab ---")
        for ln in dump_go_tree(ui_go["freesia_s5_background"][0], ui_objs, max_depth=8):
            print(" ", ln)
    fskin = skins_by_key.get("402_Freesia_S5")
    if fskin:
        print(f"Manifest 402_Freesia_S5 cam=({fskin['cam_x']:.2f},{fskin['cam_y']:.2f}) canvas=({fskin['canvas_w']}x{fskin['canvas_h']})")
        for cl in fskin["clips"]:
            print(f"  clip={cl['clip']} dur={cl['duration']} nodes={len(cl['nodes'])}")
            for n in cl["nodes"]:
                print(
                    f"    node={n['name']} add={n['isAdditive']} active_pos={n['world_pos']} wsc={n['world_scale']} "
                    f"wrot={n['world_rot']} sm={n['scalingMode']} rm={n['renderMode']} sz=({n['size'].get('mode')},{n['size'].get('scalar')}) "
                    f"rate={n['rate']} bursts={n['bursts']} delay={n['startDelay']} lt={n['lifetime'].get('scalar')} "
                    f"tint=({n['tint']['r']:.2f},{n['tint']['g']:.2f},{n['tint']['b']:.2f},{n['tint']['a']:.2f}) mul={n['tintMultiplier']} "
                    f"tex={n['texName']} mask={n['maskTexName']}"
                )
    ps_touch = find_ps_in_prefab("FX_Freesia_S5_Background_Touch01", art_objs, art_go)
    print(f"--- FX_Freesia_S5_Background_Touch01 PS nodes ({len(ps_touch)}) ---")
    for item in ps_touch:
        psr = item["psr"] or {}
        mrefs = psr.get("m_Materials", [])
        mat_desc = []
        for mr in mrefs:
            res = resolve_ext_any(obj_by_cab_pid, item["assets_file"], mr.get("m_FileID", 0), mr.get("m_PathID", 0))
            if res:
                mobj, mab = res
                mtt = mobj.read_typetree()
                sh = mtt.get("m_Shader", {})
                sh_res = resolve_ext_any(obj_by_cab_pid, mobj.assets_file, sh.get("m_FileID", 0), sh.get("m_PathID", 0))
                sh_name = shader_props.get((sh_res[0].assets_file.name, sh_res[0].path_id), {}).get("name", "builtin/unknown") if sh_res else f"builtin(pid={sh.get('m_PathID')})"
                sp = mtt.get("m_SavedProperties", {})
                flts = dict(sp.get("m_Floats", []))
                cols = {k: (round(v["r"],3), round(v["g"],3), round(v["b"],3), round(v["a"],3)) for k, v in sp.get("m_Colors", [])}
                texs = {}
                for k, tv in sp.get("m_TexEnvs", []):
                    tr = tv.get("m_Texture", {})
                    tres = resolve_ext_any(obj_by_cab_pid, mobj.assets_file, tr.get("m_FileID", 0), tr.get("m_PathID", 0))
                    tname = tres[0].peek_name() if tres else None
                    tstat = ""
                    if tres:
                        img = tres[0].read().image.convert("RGBA")
                        arr = np.array(img)
                        tstat = f"{img.size} rgb_max={arr[:,:,:3].max()} a_max={arr[:,:,3].max()} a_mean={arr[:,:,3].mean():.1f}"
                    texs[k] = f"{tname}({tstat}) sc={tv.get('m_Scale')} off={tv.get('m_Offset')}"
                mat_desc.append(f"mat={mtt.get('m_Name')} shader={sh_name} flts={flts} cols={cols} texs={texs}")
        print(f"  {item['path']} active={item['active']} lpos={item['lpos']} lsc={item['lsc']} wsc={item['wsc_from_prefab']} maxPS={psr.get('m_MaxParticleSize')} rm={psr.get('m_RenderMode')}")
        for md in mat_desc:
            print(f"    {md}")

    # =========================================================================
    # SECTION 2: ALL 107 rm == 4 (Mesh) nodes in fx_manifest.json + Mesh Bounds
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 2: ALL rm == 4 (Mesh) nodes & exact m_Mesh bounds")
    print("=" * 80)
    mesh_cache = {}
    rm4_rows = []
    # Build lookup (prefab_base, node_name) -> m_Mesh from raw prefabs
    prefab_ps_cache = {}

    for s in manifest["skins"]:
        sk = s["skin_key"]
        cat = skin_cat_map.get(sk)
        bg_base = Path(cat["bg_prefab"]).name.lower() if cat and cat.get("bg_prefab") else None
        for cl in s["clips"]:
            clip_name = cl["clip"]
            prefab_nodes = []
            if bg_base and bg_base in ui_go:
                if ("ui", bg_base) not in prefab_ps_cache:
                    prefab_ps_cache[("ui", bg_base)] = find_ps_in_prefab(bg_base, ui_objs, ui_go)
                prefab_nodes.extend(prefab_ps_cache[("ui", bg_base)])
            if cat and clip_name.startswith("fx_"):
                eid = int(clip_name[3:]) if clip_name[3:].isdigit() else -1
                eff_pf = cat.get("effect_prefabs", {}).get(eid, "")
                if eff_pf:
                    eb = Path(eff_pf).name.lower()
                    if ("art", eb) not in prefab_ps_cache:
                        prefab_ps_cache[("art", eb)] = find_ps_in_prefab(eb, art_objs, art_go)
                    prefab_nodes.extend(prefab_ps_cache[("art", eb)])
            by_node_name = defaultdict(list)
            for pn in prefab_nodes:
                by_node_name[pn["path"].split("/")[-1]].append(pn)

            for idx, n in enumerate(cl["nodes"]):
                if n["renderMode"] != 4:
                    continue
                cands = by_node_name.get(n["name"], [])
                mesh_info = None
                for pn in cands:
                    psr = pn["psr"] or {}
                    mref = psr.get("m_Mesh", {})
                    m_res = resolve_ext_any(obj_by_cab_pid, pn["assets_file"], mref.get("m_FileID", 0), mref.get("m_PathID", 0))
                    if m_res:
                        mobj, mab = m_res
                        key = (mobj.assets_file.name, mobj.path_id)
                        if key not in mesh_cache:
                            try:
                                m = mobj.read()
                                obj_txt = m.export()
                                bnd = _parse_obj_bounds(obj_txt)
                                mesh_cache[key] = {"name": m.m_Name, "ab": mab, "pid": mobj.path_id, "bounds": bnd}
                            except Exception as e:
                                mesh_cache[key] = {"name": mobj.peek_name(), "ab": mab, "pid": mobj.path_id, "err": str(e)}
                        mesh_info = mesh_cache[key]
                        break
                    else:
                        mesh_info = {"name": f"BUILTIN_OR_NULL(fid={mref.get('m_FileID')},pid={mref.get('m_PathID')})"}
                rm4_rows.append({
                    "skin": sk,
                    "clip": clip_name,
                    "node": n["name"],
                    "sm": n["scalingMode"],
                    "wsc": [round(x, 3) for x in n["world_scale"]],
                    "sz": n["size"].get("scalar"),
                    "mesh": mesh_info,
                })

    print(f"Total rm==4 manifest nodes: {len(rm4_rows)}; unique custom meshes resolved: {len(mesh_cache)}")
    mesh_usage = Counter()
    for r in rm4_rows:
        mn = (r["mesh"] or {}).get("name", "NONE")
        mesh_usage[mn] += 1
    print("--- Unique Meshes summary ---")
    for key, minfo in sorted(mesh_cache.items(), key=lambda kv: kv[1].get("name", "")):
        bnd = minfo.get("bounds") or {}
        print(f"  mesh={minfo['name']:30s} ab={minfo['ab']:22s} count={mesh_usage[minfo['name']]:3d} verts={bnd.get('verts')} ext={bnd.get('extent')} min={bnd.get('min')} max={bnd.get('max')}")
    print("--- rm==4 nodes with huge effective mesh size (max_dim * wsc * sz > 1200) OR non-standard/builtin ---")
    for r in rm4_rows:
        mi = r["mesh"] or {}
        bnd = mi.get("bounds") or {}
        ext = bnd.get("extent") or [1, 1, 0]
        eff_x = ext[0] * abs(r["wsc"][0]) * float(r["sz"] or 1)
        eff_y = ext[1] * abs(r["wsc"][1]) * float(r["sz"] or 1)
        if max(eff_x, eff_y) > 1200 or max(eff_x, eff_y) < 10 or not bnd:
            print(f"  {r['skin']} / {r['clip']} / {r['node']}: sm={r['sm']} wsc={r['wsc']} sz={r['sz']} mesh={mi.get('name')} ext={ext} -> eff=({eff_x:.1f}, {eff_y:.1f})")

    # =========================================================================
    # SECTION 3: sm == 1 outliers & huge sm == 0 nodes
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 3: sm == 1 nodes & huge sm == 0 nodes (transform chains & maxParticleSize)")
    print("=" * 80)
    sm1_items = []
    for s in manifest["skins"]:
        sk = s["skin_key"]
        for cl in s["clips"]:
            for n in cl["nodes"]:
                wsc = n["world_scale"]
                sz_s = n["size"].get("scalar", 1.0)
                if n["size3D"]:
                    sz_s = max(abs(n["sizeX"].get("scalar", 0)), abs(n["sizeY"].get("scalar", 0)))
                eff = max(abs(wsc[0]), abs(wsc[1])) * abs(sz_s)
                if n["scalingMode"] == 1 or eff > 1800:
                    sm1_items.append((eff, n["scalingMode"], sk, cl["clip"], n["name"], n["renderMode"], wsc, sz_s, n["maxParticles"], n["rate"], n["bursts"]))
    sm1_items.sort(key=lambda x: x[0], reverse=True)
    print(f"Total (sm==1 or eff>1800) nodes: {len(sm1_items)}. Showing top 35:")
    for eff, sm, sk, cln, nn, rm, wsc, szs, mp, rt, br in sm1_items[:35]:
        print(f"  eff={eff:9.1f} sm={sm} rm={rm} {sk:24s} {cln:12s} {nn:20s} wsc={[round(x,2) for x in wsc]} sz={szs:.2f} maxP={mp} rate={rt} bursts={len(br)}")

    outlier_targets = [
        ("503_Benten_S4", "cahihonghuan"),
        ("1101_NicoletteLamel_S2", "glow2"),
        ("2001_Ennis_S2", "water"),
        ("2301_QuLing_S2", "water"),
        ("601_Asuna_S6", "particle2"),
        ("1901_Aurora_S3", "SubEmitter1"),
        ("3101_Ithil_S2", "SubEmitter1"),
        ("3601_QingHao_S2", "bao"),
        ("1301_Satya_S2", "smoke"),
        ("4501_RubyRose_S2", "pingmu"),
        ("4301_HeLing_S2", "yun"),
        ("2802_Mist_S3", "shui02"),
        ("3801_LightCloud_S2", "shui"),
        ("2002_Ennis_S3", "an"),
    ]
    print("--- Detailed prefab hierarchy for targeted outlier skins ---")
    seen_prefabs = set()
    for sk, target_node in outlier_targets:
        cat = skin_cat_map.get(sk)
        if not cat:
            print(f"  [MISS cat] {sk}")
            continue
        bgp = Path(cat["bg_prefab"]).name.lower()
        if bgp not in seen_prefabs and bgp in ui_go:
            seen_prefabs.add(bgp)
            print(f"  [UI Prefab {bgp} for {sk}]")
            for ln in dump_go_tree(ui_go[bgp][0], ui_objs, max_depth=7):
                if any(k in ln for k in ("Canvas", "Background", "Point", target_node, "FX_", "Camera", "Skeleton", "sm=")):
                    print("   ", ln)
        # Also check effect_prefabs of that skin containing target_node
        for eid, eff_pf in cat.get("effect_prefabs", {}).items():
            ep = Path(eff_pf).name.lower()
            if ep and ep not in seen_prefabs and ep in art_go:
                pns = find_ps_in_prefab(ep, art_objs, art_go)
                if any(p["path"].split("/")[-1] == target_node for p in pns):
                    seen_prefabs.add(ep)
                    print(f"  [Effect Prefab {ep} ({sk}/fx_{eid})]")
                    for ln in dump_go_tree(art_go[ep][0], art_objs, max_depth=6):
                        print("   ", ln)

    # =========================================================================
    # SECTION 4: Shaders in 15_shader/*.ab vs Material saved properties & null m_Materials[0]
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 4: Shaders declared props vs Material m_SavedProperties & m_Materials slots")
    print("=" * 80)
    print(f"Parsed {len(shader_props)} shaders from 15_shader/03_prefabs/14_effect.")
    key_props = {"_Intensity", "_Brightness", "_Alphe", "_Alpha", "_qiangdu", "_Power_i", "_mask02", "_Rongjie_tietu", "_UV_t", "_Mask_U", "_Mask_V", "_Rongjie", "_Raodong_tex", "_quse", "_offon", "_mask_offon", "_Color", "_color", "_TintColor", "_Main_color", "_Edge_color", "_Ruanying"}
    for sname, sinfo in sorted(shader_by_name.items()):
        inter = sorted(sinfo["prop_names"] & key_props)
        all_p = [f"{p['name']}(t={p['type']})" for p in sinfo["props"]]
        print(f"  Shader '{sname}' [{sinfo['ab']}]: {all_p}")

    # Audit every material referenced across all manifest prefabs
    intensity_used_by_shader = Counter()
    intensity_stale_zero = []
    alphe_gt_one = []
    mask2_mats = Counter()
    uvscroll_mats = Counter()
    dissolve_mats = Counter()
    null_slot0_nodes = []

    checked_mats = set()
    for k_pf, pns in list(prefab_ps_cache.items()):
        pass
    # Actually scan ALL skins' UI + Effect prefabs once
    all_ps_records = []
    for s in manifest["skins"]:
        cat = skin_cat_map.get(s["skin_key"])
        if not cat:
            continue
        bgp = Path(cat["bg_prefab"]).name.lower()
        if bgp in ui_go:
            for pn in find_ps_in_prefab(bgp, ui_objs, ui_go):
                all_ps_records.append((s["skin_key"], "bg", pn))
        for eid, eff_pf in cat.get("effect_prefabs", {}).items():
            ep = Path(eff_pf).name.lower()
            if ep in art_go:
                for pn in find_ps_in_prefab(ep, art_objs, art_go):
                    all_ps_records.append((s["skin_key"], f"fx_{eid}", pn))

    max_ps_dist = Counter()
    align_dist = Counter()
    for sk, src, pn in all_ps_records:
        psr = pn["psr"] or {}
        max_ps_dist[round(float(psr.get("m_MaxParticleSize", -1)), 3)] += 1
        align_dist[int(psr.get("m_RenderAlignment", -1))] += 1
        mrefs = psr.get("m_Materials", [])
        if mrefs and mrefs[0].get("m_PathID", 0) == 0:
            non_zero = [(i, mr) for i, mr in enumerate(mrefs) if mr.get("m_PathID", 0) != 0]
            null_slot0_nodes.append((sk, src, pn["path"], len(mrefs), non_zero))
        for mr in mrefs:
            res = resolve_ext_any(obj_by_cab_pid, pn["assets_file"], mr.get("m_FileID", 0), mr.get("m_PathID", 0))
            if not res:
                continue
            mobj, mab = res
            mkey = (mobj.assets_file.name, mobj.path_id)
            if mkey in checked_mats:
                continue
            checked_mats.add(mkey)
            mtt = mobj.read_typetree()
            sh = mtt.get("m_Shader", {})
            sh_res = resolve_ext_any(obj_by_cab_pid, mobj.assets_file, sh.get("m_FileID", 0), sh.get("m_PathID", 0))
            sinfo = shader_props.get((sh_res[0].assets_file.name, sh_res[0].path_id)) if sh_res else None
            sname = sinfo["name"] if sinfo else f"builtin({sh.get('m_PathID')})"
            declared = sinfo["prop_names"] if sinfo else set()
            sp = mtt.get("m_SavedProperties", {})
            flts = dict(sp.get("m_Floats", []))
            texs = {k: (v.get("m_Texture", {}).get("m_PathID", 0) != 0) for k, v in sp.get("m_TexEnvs", [])}
            if "_Intensity" in flts:
                has_in_shader = "_Intensity" in declared
                intensity_used_by_shader[(sname, has_in_shader, round(flts["_Intensity"], 3))] += 1
                if flts["_Intensity"] == 0.0 and not has_in_shader:
                    intensity_stale_zero.append((mtt.get("m_Name"), sname))
            if "_Alphe" in flts and flts["_Alphe"] > 1.0 and "_Alphe" in declared:
                alphe_gt_one.append((mtt.get("m_Name"), sname, flts["_Alphe"]))
            if texs.get("_mask02"):
                mask2_mats[(sname, "_mask_offon" in flts and flts["_mask_offon"])] += 1
            if texs.get("_Rongjie_tietu") or flts.get("_Rongjie", 0) > 0:
                dissolve_mats[sname] += 1
            if abs(flts.get("_UV_t", 0)) > 1e-4 or abs(flts.get("_Mask_U", 0)) > 1e-4 or abs(flts.get("_Mask_V", 0)) > 1e-4:
                uvscroll_mats[sname] += 1

    print(f"Manifest-referenced PS MaxParticleSize distribution: {dict(max_ps_dist.most_common(12))}")
    print(f"Manifest-referenced PS RenderAlignment distribution: {dict(align_dist)}")
    print(f"Nodes with NULL m_Materials[0]: {null_slot0_nodes}")
    print(f"Unique materials inspected: {len(checked_mats)}")
    print(f"_Intensity in m_Floats vs Shader declared: {dict(intensity_used_by_shader.most_common(20))}")
    print(f"Stale _Intensity==0 NOT in shader ({len(intensity_stale_zero)}): {intensity_stale_zero[:15]}")
    print(f"_Alphe > 1.0 IN shader ({len(alphe_gt_one)}): sample={alphe_gt_one[:10]}")
    print(f"_mask02 non-null mats: {dict(mask2_mats)}")
    print(f"Dissolve (_Rongjie_tietu / _Rongjie>0) mats: {dict(dissolve_mats)}")
    print(f"UV Scroll (_UV_t / _Mask_U / _Mask_V != 0) mats: {dict(uvscroll_mats)}")

    # =========================================================================
    # SECTION 5: 3501_QingDai_S2 fx_9008143 & SubEmitters + 4 empty channels check
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 5: 3501_QingDai_S2 (fx_9008143) & SubEmitter + 4 empty channels check")
    print("=" * 80)
    qskin = skins_by_key.get("3501_QingDai_S2")
    if qskin:
        for cl in qskin["clips"]:
            print(f"  clip={cl['clip']} dur={cl['duration']}")
            for idx, n in enumerate(cl["nodes"]):
                print(
                    f"    [{idx}] {n['name']:15s} subChild={n['isSubEmitterChild']} subs={n['subEmitters']} add={n['isAdditive']} "
                    f"wpos={[round(x,1) for x in n['world_pos']]} wsc={[round(x,2) for x in n['world_scale']]} "
                    f"dur={n['duration']} delay={n['startDelay']} loop={n['looping']} lt={n['lifetime'].get('scalar')} "
                    f"sz={n['size'].get('scalar')} rate={n['rate']} bursts={n['bursts']} tint={n['tint']} mul={n['tintMultiplier']} "
                    f"tex={n['texName']} mask={n['maskTexName']}"
                )
    # Check SubEmitterModules directly in art_prefabs for QingDai_S2
    qcat = skin_cat_map.get("3501_QingDai_S2")
    if qcat:
        for eid, eff_pf in qcat.get("effect_prefabs", {}).items():
            ep = Path(eff_pf).name.lower()
            if ep in art_go:
                print(f"  --- Raw AB {ep} (fx_{eid}) ---")
                for ln in dump_go_tree(art_go[ep][0], art_objs, max_depth=6):
                    print("   ", ln)
                for pn in find_ps_in_prefab(ep, art_objs, art_go):
                    sem = pn["ps"].get("SubModule", {})
                    if sem.get("enabled"):
                        print(f"    SubModule on {pn['path']}: {sem.get('subEmitters')}")
                    em = pn["ps"].get("EmissionModule", {})
                    print(f"    PS {pn['path']}: Emission={em}, startDelay={pn['ps'].get('startDelay')}, InitialSize={pn['ps'].get('InitialModule',{}).get('startSize')}")

    # Summary of ALL SubEmitter configs across entire manifest
    sub_summary = []
    for s in manifest["skins"]:
        for cl in s["clips"]:
            for idx, n in enumerate(cl["nodes"]):
                if n.get("subEmitters"):
                    for se in n["subEmitters"]:
                        ti = se["targetIdx"]
                        ch = cl["nodes"][ti] if 0 <= ti < len(cl["nodes"]) else None
                        sub_summary.append({
                            "skin": s["skin_key"],
                            "clip": cl["clip"],
                            "parent": n["name"],
                            "parent_rate": n["rate"],
                            "parent_bursts": len(n["bursts"]),
                            "parent_delay": n["startDelay"],
                            "se": se,
                            "child": ch["name"] if ch else None,
                            "child_rate": ch["rate"] if ch else None,
                            "child_bursts": len(ch["bursts"]) if ch else None,
                            "child_loop": ch["looping"] if ch else None,
                            "child_add": ch["isAdditive"] if ch else None,
                        })
    print(f"Total SubEmitter links in manifest: {len(sub_summary)}")
    for ss in sub_summary:
        print(f"  {ss['skin']}/{ss['clip']}: {ss['parent']}(rate={ss['parent_rate']},b={ss['parent_bursts']},d={ss['parent_delay']}) -> [{ss['se']['type']},prop={ss['se']['properties']},p={ss['se']['emitProbability']}] -> {ss['child']}(rate={ss['child_rate']},b={ss['child_bursts']},loop={ss['child_loop']},add={ss['child_add']})")

    # Check actual rendered frames in the 4 empty / suspected clips
    seq_root = Path(r"E:\A灵魂潮汐\tools\_batch_fx_sequences")
    check_dirs = [
        seq_root / "3501_QingDai_S2" / "fx_9008143" / "normal",
        seq_root / "3501_QingDai_S2" / "fx_9008143" / "add",
        seq_root / "402_Freesia_S5" / "fx_9008161" / "normal",
        seq_root / "402_Freesia_S5" / "fx_9008161" / "add",
        seq_root / "2301_QuLing_S2" / "idle" / "normal",
        seq_root / "603_Asuna_S8" / "idle" / "add",
    ]
    print("--- PNG pixel scan on target folders ---")
    for d in check_dirs:
        if not d.exists():
            print(f"  MISSING {d}")
            continue
        pngs = sorted(d.glob("*.png"))
        non_empty = []
        for p in pngs:
            arr = np.array(Image.open(p).convert("RGBA"))
            amax = int(arr[:, :, 3].max()) if arr.shape[2] == 4 else int(arr[:, :, :3].max())
            rmax = int(arr[:, :, :3].max())
            if amax > 0 or rmax > 0:
                nz = np.argwhere(np.maximum(arr[:, :, 3], arr[:, :, :3].max(axis=2)) > 0)
                y0, x0 = nz.min(axis=0)
                y1, x1 = nz.max(axis=0)
                non_empty.append((p.name, amax, rmax, (int(x0), int(y0), int(x1), int(y1))))
        print(f"  {d}: total={len(pngs)}, non_empty={len(non_empty)}")
        for row in non_empty[:8]:
            print(f"    {row}")
        if len(non_empty) > 8:
            print(f"    ... last={non_empty[-2:]}")


if __name__ == "__main__":
    main()
