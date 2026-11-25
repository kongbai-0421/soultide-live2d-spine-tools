"""Final precision checks before patching batch_fx_exporter.py + SoulTideBatchFxRecorder.cs:
1. Check all 01_scenes/*.ab Cameras/Canvases (where does UI Canvas scale come from?)
2. Check ALL Effect prefab root transforms + why Freesia_S5 Touch01 ended at [850.6, 520.0]
3. Inspect the 5 active Effect AnimatorControllers & AnimationClip genericBindings
4. Inspect 503_Benten_S4 cahihonghuan, 1101_NicoletteLamel_S2 glow1/2, 402_Freesia_S5 posui/yumao, 2002_Ennis_S3 trail0/SubEmitter0, and shader color/alpha/intensity semantics
5. Identify builtin mesh fid/pid=10210 & check TrailModule properties across all 31 active Trail nodes
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe
from soultide_common import CDN_ROOT, DECOMPILED_DIR, load_ab


def main():
    # 1. Check 01_scenes/*.ab Cameras & Canvases + Main/GameEntry in analysis
    print("=" * 80)
    print("1. All 01_scenes/*.ab Cameras & Canvases")
    print("=" * 80)
    for ab in sorted((CDN_ROOT / "01_scenes").glob("*.ab")):
        env = load_ab(ab)
        objs = {o.path_id: o for o in env.objects}
        cams = [o for o in env.objects if o.type.name == "Camera"]
        cans = [o for o in env.objects if o.type.name == "Canvas"]
        if cams or cans:
            print(f" Scene AB: {ab.name}")
            for o in cams:
                tt = o.read_typetree()
                go = objs.get(tt.get("m_GameObject", {}).get("m_PathID", 0))
                print(f"   Cam '{go.peek_name() if go else '?'}': ortho={tt.get('orthographic')} size={tt.get('orthographic size')} depth={tt.get('m_Depth')} mask={tt.get('m_CullingMask')}")
            for o in cans:
                tt = o.read_typetree()
                go = objs.get(tt.get("m_GameObject", {}).get("m_PathID", 0))
                rt_str = ""
                if go:
                    g = go.read()
                    for c in g.m_Component:
                        co = objs.get(c.component.path_id)
                        if co and co.type.name in ("RectTransform", "Transform"):
                            r = co.read()
                            rt_str = f"pos=({r.m_LocalPosition.x:.2f},{r.m_LocalPosition.y:.2f},{r.m_LocalPosition.z:.2f}) lsc=({r.m_LocalScale.x:.4f},{r.m_LocalScale.y:.4f},{r.m_LocalScale.z:.4f})"
                print(f"   Canvas '{go.peek_name() if go else '?'}': rm={tt.get('m_RenderMode')} pd={tt.get('m_PlaneDistance')} {rt_str}")

    # 2. Check Effect prefab roots + batch_fx_exporter placement for Freesia_S5, QingDai_S2, etc.
    indexer = bfe.AssetIndexer()
    repo = bfe.FullI18nRepo()
    catalog = {c["skin_key"]: c for c in bfe.build_skin_catalog(repo)}
    manifest = json.loads(Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json").read_text(encoding="utf-8"))
    active_skins = {s["skin_key"] for s in manifest["skins"]}

    print("\n" + "=" * 80)
    print("2. Effect Prefab root Transform & extreme effect positions in manifest")
    print("=" * 80)
    non_zero_roots = []
    for sk, cat in sorted(catalog.items()):
        if sk not in active_skins:
            continue
        for eid, ep in cat.get("effect_prefabs", {}).items():
            eb = Path(ep).name.lower()
            pids = indexer.art_go_by_name.get(eb, [])
            if not pids:
                continue
            go = indexer.art_objs[pids[0]].read()
            is_rect, lpos, lsc, lq = bfe._node_local_tf(go, indexer.art_objs, ignore_root_pos=False)[1:5]
            # Also check RectTransform sizeDelta / anchor if RectTransform
            if any(abs(v) > 1e-3 for v in lpos) or any(abs(v - 1.0) > 1e-3 for v in lsc) or any(abs(v) > 1e-3 for v in lq[:3]):
                non_zero_roots.append((sk, f"fx_{eid}", ep, is_rect, [round(x, 2) for x in lpos], [round(x, 3) for x in lsc], [round(x, 3) for x in lq]))
    print(f"Effect Prefabs with non-identity root TF ({len(non_zero_roots)}):")
    for row in non_zero_roots:
        print(f"  {row}")

    # Check UI root Canvases & GirlDressShowUI / MainUI / GirlUI
    print("--- UI Canvases in ui.ab / GameEntry ---")
    for ui_name in ("mainui", "girldressshowui", "girlui"):
        if ui_name in indexer.ui_go_by_name:
            g = indexer.ui_objs[indexer.ui_go_by_name[ui_name][0]].read()
            print(f" Found UI prefab: {g.m_Name}")
    for ab in sorted((CDN_ROOT / "00_boot").glob("*.ab")) if (CDN_ROOT / "00_boot").exists() else []:
        env = load_ab(ab)
        for o in env.objects:
            if o.type.name in ("Camera", "Canvas"):
                print(f" 00_boot/{ab.name}: {o.type.name} {o.peek_name()}")

    # Check how many manifest fx_* clips have nodes whose mean/median pos is far outside canvas relative to camera!
    print("--- Manifest fx_* nodes far from camera (> 900 world units in x or > 650 in y) ---")
    for s in manifest["skins"]:
        cx, cy = s["cam_x"], s["cam_y"]
        hw, hh = s["canvas_w"] / 2.0, s["canvas_h"] / 2.0
        for cl in s["clips"]:
            if not cl["clip"].startswith("fx_"):
                continue
            for n in cl["nodes"]:
                wx, wy = n["world_pos"][0], n["world_pos"][1]
                if abs(wx - cx) > hw + 150 or abs(wy - cy) > hh + 150:
                    print(f"  OOB fx: {s['skin_key']} / {cl['clip']} / {n['name']}: wpos=({wx:.1f},{wy:.1f}) vs cam=({cx:.1f},{cy:.1f}) +/- ({hw:.0f},{hh:.0f})")

    # Check how many UI background prefabs have active SkeletonGraphic vs Spine under Point_Root
    # Wait: check 402_Freesia_S5 SoulDress_Freesia prefab in 23_spine or 03_prefabs!
    print("\n--- Check Freesia_S5 SoulDress_Freesia & QingDai_S2 SoulDress_QingDai_S2 Transform hierarchy ---")
    for name in ("souldress_freesia", "souldress_freesia_person", "souldress_qingdai_s2", "souldress_qingdai_s2_person"):
        if name in indexer.art_go_by_name:
            print(f" art_prefabs match '{name}'")
        if name in indexer.ui_go_by_name:
            print(f" ui match '{name}'")

    # 3. Inspect all 5 Effect AnimatorControllers genericBindings & curves
    print("\n" + "=" * 80)
    print("3. Inspect all 5 Effect AnimatorControllers")
    print("=" * 80)
    ctrl_objs = {}
    clip_objs = {}
    for sub in ("03_prefabs", "14_effect"):
        for ab in sorted((CDN_ROOT / sub).rglob("*.ab")):
            env = load_ab(ab)
            for o in env.objects:
                if o.type.name == "AnimatorController":
                    ctrl_objs[(o.assets_file.name, o.path_id)] = (o, ab.name)
                elif o.type.name == "AnimationClip":
                    clip_objs[(o.assets_file.name, o.path_id)] = (o, ab.name)

    for pf in ("FX_Mist_S3_Background_chat", "FX_Clotho_S2_Background_touch1", "QingDai_S2_Background_touch2", "Benten_S3_Background_touch3", "Dreizehn_S4_Background"):
        # Check Dreizehn Animation inside UI or art
        if pf.lower() in indexer.art_go_by_name:
            pids = indexer.art_go_by_name[pf.lower()]
            objs = indexer.art_objs
        elif pf.lower() in indexer.ui_go_by_name:
            pids = indexer.ui_go_by_name[pf.lower()]
            objs = indexer.ui_objs
        else:
            continue
        def find_anim(gid):
            g = objs[gid].read()
            tf = None
            for c in g.m_Component:
                co = objs.get(c.component.path_id)
                if co and co.type.name in ("Transform", "RectTransform"): tf = co.read()
                elif co and co.type.name == "Animator":
                    att = co.read_typetree()
                    cref = att.get("m_Controller", {})
                    fid, pid = cref.get("m_FileID", 0), cref.get("m_PathID", 0)
                    cab = co.assets_file.name if fid == 0 else Path(co.assets_file.externals[fid - 1].path).name
                    res = ctrl_objs.get((cab, pid))
                    if res:
                        cobj, _ = res
                        ctt = cobj.read_typetree()
                        print(f" Controller '{cobj.peek_name()}' on '{pf}/{g.m_Name}':")
                        for clref in ctt.get("m_AnimationClips", []):
                            cfid, cpid = clref.get("m_FileID", 0), clref.get("m_PathID", 0)
                            ccab = cobj.assets_file.name if cfid == 0 else Path(cobj.assets_file.externals[cfid - 1].path).name
                            clres = clip_objs.get((ccab, cpid))
                            if clres:
                                clobj, clab = clres
                                cltt = clobj.read_typetree()
                                cbc = cltt.get("m_ClipBindingConstant", {})
                                gbs = cbc.get("genericBindings", [])
                                print(f"   Clip '{clobj.peek_name()}' ({clab}) stop={cltt.get('m_MuscleClip',{}).get('m_StopTime')} bindings={len(gbs)}")
                                # Note UnityPy path hashes or check m_DenseClip/m_StreamedClip
                                mc = cltt.get("m_MuscleClip", {}).get("m_Clip", {})
                                dc = mc.get("m_DenseClip", {})
                                cc = mc.get("m_ConstantClip", {})
                                sc = mc.get("m_StreamedClip", {})
                                print(f"     genericBindings sample: {gbs[:12]}")
                                print(f"     Dense(frames={dc.get('m_FrameCount')}, curves={dc.get('m_CurveCount')}, sample={dc.get('m_SampleRate')}) Const(len={len(cc.get('data',[]))}) Stream(curves={sc.get('curveCount')})")
            if tf:
                for ch in tf.m_Children:
                    ctf = objs.get(ch.path_id)
                    if ctf: find_anim(ctf.read().m_GameObject.path_id)
        find_anim(pids[0])

    # 4. Inspect 503_Benten_S4 cahihonghuan, 1101_NicoletteLamel_S2 glow1/2, 402_Freesia_S5 posui/yumao, 2002_Ennis_S3 trail0/SubEmitter0
    print("\n" + "=" * 80)
    print("4. Inspect 503_Benten_S4 cahihonghuan & caiguang, 1101_NicoletteLamel_S2 glow1/2, 2002_Ennis_S3 SubEmitter0")
    print("=" * 80)
    for sk, pf, nnames in [
        ("503_Benten_S4", "Benten_S4_Background", {"cahihonghuan", "caiguang", "huaban"}),
        ("1101_NicoletteLamel_S2", "NicoletteLamel_S2_Background", {"glow1", "glow2"}),
        ("1301_Satya_S2", "Satya_S2_Background", {"smoke", "glow1", "glow2"}),
        ("101_Colcher_S2", "Colcher_S2_Background", {"glow1", "glow2", "glow3"}),
    ]:
        pids = indexer.ui_go_by_name.get(pf.lower(), [])
        if not pids: continue
        def walk_ps(gid, path, pws):
            go = indexer.ui_objs[gid].read()
            tf = None; ps = None; psr = None
            for c in go.m_Component:
                co = indexer.ui_objs.get(c.component.path_id)
                if not co: continue
                if co.type.name in ("Transform", "RectTransform"): tf = co.read()
                elif co.type.name == "ParticleSystem": ps = co.read_typetree()
                elif co.type.name == "ParticleSystemRenderer": psr = co.read_typetree()
            ls = (tf.m_LocalScale.x, tf.m_LocalScale.y, tf.m_LocalScale.z) if tf else (1,1,1)
            ws = [pws[0]*ls[0], pws[1]*ls[1], pws[2]*ls[2]]
            cp = f"{path}/{go.m_Name}" if path else go.m_Name
            if ps and go.m_Name in nnames:
                init = ps.get("InitialModule", {})
                szm = ps.get("SizeModule", {})
                print(f" {sk} [{cp}] active={go.m_IsActive} sm={ps.get('scalingMode')} lsc={[round(x,3) for x in ls]} ws={[round(x,3) for x in ws]} sz=({init.get('startSize',{}).get('minMaxState')},{init.get('startSize',{}).get('scalar')},{init.get('startSize',{}).get('minScalar')}) szLife_en={szm.get('enabled')} maxPS={psr.get('m_MaxParticleSize') if psr else None}")
                if szm.get("enabled"):
                    print(f"    szOverLife={szm.get('curve')}")
            if tf:
                for ch in tf.m_Children:
                    ctf = indexer.ui_objs.get(ch.path_id)
                    if ctf: walk_ps(ctf.read().m_GameObject.path_id, cp, ws)
        walk_ps(pids[0], "", [1.0, 1.0, 1.0])

    # Check 2002_Ennis_S3 trail0 / SubEmitter0 raw & PNG
    pids = indexer.art_go_by_name.get("ennis_s3_chat", [])
    if pids:
        def walk_a(gid, path):
            go = indexer.art_objs[gid].read()
            tf = None; ps = None; psr = None
            for c in go.m_Component:
                co = indexer.art_objs.get(c.component.path_id)
                if not co: continue
                if co.type.name in ("Transform", "RectTransform"): tf = co.read()
                elif co.type.name == "ParticleSystem": ps = co.read_typetree()
                elif co.type.name == "ParticleSystemRenderer": psr = co.read_typetree()
            cp = f"{path}/{go.m_Name}" if path else go.m_Name
            if ps and go.m_Name in ("trail0", "SubEmitter0"):
                em = ps.get("EmissionModule", {})
                sub = ps.get("SubModule", {})
                print(f" Ennis_S3 [{cp}]: sm={ps.get('scalingMode')} sz={ps.get('InitialModule',{}).get('startSize')} em={em} sub={sub}")
            if tf:
                for ch in tf.m_Children:
                    ctf = indexer.art_objs.get(ch.path_id)
                    if ctf: walk_a(ctf.read().m_GameObject.path_id, cp)
        walk_a(pids[0], "")

    # 5. Check shader / material properties semantics: _Alphe, _Alpha, _Main_color, _qiangdu, _color, _Color, _TintColor across all 548 mats
    print("\n" + "=" * 80)
    print("5. Material property & builtin mesh pid check")
    print("=" * 80)
    shader_by_key = {}
    for (cab, pid), obj in indexer.obj_by_cab_pid.items():
        if obj.type.name == "Shader":
            try:
                tt = obj.read_typetree()
                pf = tt.get("m_ParsedForm", {})
                sn = pf.get("m_Name") or tt.get("m_Name") or ""
                props = {p.get("m_Name") for p in pf.get("m_PropInfo", {}).get("m_Props", [])}
                shader_by_key[(cab, pid)] = (sn, props)
            except Exception:
                pass

    mat_patterns = Counter()
    low_alpha_or_color_mats = []
    for (cab, pid), obj in indexer.obj_by_cab_pid.items():
        if obj.type.name != "Material":
            continue
        mtt = obj.read_typetree()
        sh = mtt.get("m_Shader", {})
        sh_obj = indexer.resolve_ext(obj.assets_file, sh.get("m_FileID", 0), sh.get("m_PathID", 0))
        if sh_obj:
            sn, sprops = shader_by_key.get((sh_obj.assets_file.name, sh_obj.path_id), ("?", set()))
        else:
            sn, sprops = f"builtin({sh.get('m_PathID')})", set()
        sp = mtt.get("m_SavedProperties", {})
        flts = dict(sp.get("m_Floats", []))
        cols = {k: (v["r"], v["g"], v["b"], v["a"]) for k, v in sp.get("m_Colors", [])}
        # Record what tint/alpha properties are declared vs values
        if "_Alphe" in sprops:
            v = flts.get("_Alphe", 1.0)
            if abs(v - 1.0) > 1e-3:
                mat_patterns[("Alphe!=1", sn)] += 1
        if "_Alpha" in sprops:
            v = flts.get("_Alpha", 1.0)
            if abs(v - 1.0) > 1e-3:
                mat_patterns[("Alpha!=1", sn)] += 1
        if "_qiangdu" in sprops:
            v = flts.get("_qiangdu", 1.0)
            if abs(v - 1.0) > 1e-3:
                mat_patterns[("qiangdu!=1", sn)] += 1
        if "_Main_color" in sprops:
            mat_patterns[("_Main_color", sn)] += 1
        if "_color" in sprops:
            mat_patterns[("_color", sn)] += 1
        if "_Brightness" in sprops or "_Brightness" in flts:
            mat_patterns[("_Brightness", sn, "_Brightness" in sprops, round(flts.get("_Brightness", 1.0), 2))] += 1

    print("Material tint/alpha patterns:")
    for k, v in mat_patterns.most_common():
        print(f"  {k}: {v}")

    # Check builtin mesh pathIDs on rm==4 nodes
    builtin_pids = Counter()
    for o in list(indexer.ui_objs.values()) + list(indexer.art_objs.values()):
        if o.type.name == "ParticleSystemRenderer":
            tt = o.read_typetree()
            if tt.get("m_RenderMode") == 4:
                mr = tt.get("m_Mesh", {})
                res = indexer.resolve_ext(o.assets_file, mr.get("m_FileID", 0), mr.get("m_PathID", 0))
                if not res:
                    fid = mr.get("m_FileID", 0)
                    ext = o.assets_file.externals[fid - 1].path if fid > 0 and fid - 1 < len(o.assets_file.externals) else "self"
                    builtin_pids[(ext, mr.get("m_PathID", 0))] += 1
    print(f"rm==4 unresolved m_Mesh refs: {dict(builtin_pids)}")


if __name__ == "__main__":
    main()
