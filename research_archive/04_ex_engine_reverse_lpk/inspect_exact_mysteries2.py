"""Deep targeted audit of remaining FX mysteries:
1. Freesia_S5 / fx_* spawn anchor (Point_Root vs Cv_Point vs Root) across all 109 skins
2. ALL sm == 1 nodes (all ~82) + giant sm == 0 nodes (RubyRose_S2 pingmu, HeLing_S2 yun)
3. 3501_QingDai_S2 fx_9008143 full modules & Animator + 2301_QuLing_S2 water + 603_Asuna_S8/1601_Gawana/2802_Mist/3602_QingHao slot1 mats
4. home.ab BackgroundCanvas / Camera setup + Unity builtin pid 10210 check
5. Material color/alpha/intensity/UV props semantic check across all 548 materials
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe
from soultide_common import CDN_ROOT, DECOMPILED_DIR, load_ab


def main():
    manifest = json.loads(Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json").read_text(encoding="utf-8"))
    skins_by_key = {s["skin_key"]: s for s in manifest["skins"]}

    # 1. Inspect home.ab
    print("=" * 80)
    print("1. home.ab Camera & Canvas hierarchy")
    print("=" * 80)
    home_ab = CDN_ROOT / "01_scenes" / "home.ab"
    if home_ab.exists():
        env = load_ab(home_ab)
        objs = {o.path_id: o for o in env.objects}
        for o in env.objects:
            if o.type.name == "Camera":
                tt = o.read_typetree()
                go = objs.get(tt.get("m_GameObject", {}).get("m_PathID", 0))
                print(" Camera:", go.peek_name() if go else "?", "ortho=", tt.get("orthographic"), "size=", tt.get("orthographic size"), "near=", tt.get("near clip plane"), "far=", tt.get("far clip plane"))
            elif o.type.name == "Canvas":
                tt = o.read_typetree()
                goid = tt.get("m_GameObject", {}).get("m_PathID", 0)
                go = objs.get(goid)
                gname = go.peek_name() if go else "?"
                # Find RectTransform on same GO
                rt_info = ""
                if go:
                    g = go.read()
                    for c in g.m_Component:
                        co = objs.get(c.component.path_id)
                        if co and co.type.name in ("RectTransform", "Transform"):
                            r = co.read()
                            rt_info = f"pos=({r.m_LocalPosition.x},{r.m_LocalPosition.y},{r.m_LocalPosition.z}) lsc=({r.m_LocalScale.x},{r.m_LocalScale.y},{r.m_LocalScale.z})"
                print(" Canvas:", gname, "rm=", tt.get("m_RenderMode"), "pd=", tt.get("m_PlaneDistance"), "pixPerf=", tt.get("m_PixelPerfect"), rt_info)
            elif o.type.name == "MonoBehaviour":
                nm = o.peek_name() or ""
                try:
                    tt = o.read_typetree()
                    if "m_UiScaleMode" in tt or "m_ReferenceResolution" in tt:
                        goid = tt.get("m_GameObject", {}).get("m_PathID", 0)
                        go = objs.get(goid)
                        print(" CanvasScaler:", go.peek_name() if go else "?", tt)
                except Exception:
                    pass

    # 2. Index ABs
    indexer = bfe.AssetIndexer()
    repo = bfe.FullI18nRepo()
    catalog = {c["skin_key"]: c for c in bfe.build_skin_catalog(repo)}

    # Check how inspect_bg_prefab_layout computes Point_Root & fx_point for Freesia_S5 and QingDai_S2 and outliers
    print("\n" + "=" * 80)
    print("2. inspect_bg_prefab_layout for Freesia_S5, QingDai_S2, Benten_S4, Ennis_S2, QuLing_S2, Nicolette_S2, RubyRose_S2")
    print("=" * 80)
    for sk in ["402_Freesia_S5", "3501_QingDai_S2", "503_Benten_S4", "2001_Ennis_S2", "2301_QuLing_S2", "1101_NicoletteLamel_S2", "4501_RubyRose_S2", "4301_HeLing_S2", "1301_Satya_S2", "101_Colcher_S2", "501_Benten_S2", "1901_Aurora_S3"]:
        cat = catalog.get(sk)
        if not cat:
            continue
        lay = bfe.inspect_bg_prefab_layout(indexer, cat)
        print(f" {sk}: person_anchor={lay.get('person_anchor')} person_scale={lay.get('person_scale')} fx_point_pos={lay.get('fx_point_pos')} fx_point_scale={lay.get('fx_point_scale')} fx_point_name={lay.get('fx_point_name')} cam={lay.get('cam')} canvas={lay.get('canvas_size')}")

    # Check ALL sm == 1 nodes across entire manifest + giant sm==0 non-mesh nodes
    print("\n" + "=" * 80)
    print("3. ALL sm == 1 nodes in fx_manifest.json + raw parent/localScale")
    print("=" * 80)
    # Also scan raw prefabs for exact ps.initialModule, localScale, parent world scale
    sm1_all = []
    for s in manifest["skins"]:
        sk = s["skin_key"]
        for cl in s["clips"]:
            for n in cl["nodes"]:
                sz = n["size"]
                sz_v = max(abs(n["sizeX"]["scalar"]), abs(n["sizeY"]["scalar"])) if n["size3D"] else sz["scalar"]
                eff = max(abs(n["world_scale"][0]), abs(n["world_scale"][1])) * sz_v
                if n["scalingMode"] == 1:
                    sm1_all.append((eff, sk, cl["clip"], n["name"], n["renderMode"], n["world_scale"], sz["mode"], sz_v, n["texName"], n["tint"]["a"], n["tintMultiplier"]))
    sm1_all.sort(key=lambda x: x[0], reverse=True)
    print(f"Total sm==1 nodes: {len(sm1_all)}")
    for row in sm1_all:
        eff, sk, cln, nn, rm, wsc, szm, szv, tex, ta, mul = row
        print(f"  eff={eff:8.1f} rm={rm} {sk:24s} {cln:12s} {nn:20s} wsc={[round(x,2) for x in wsc]} sz=({szm},{szv:.2f}) a={ta:.2f} mul={mul} tex={tex}")

    # Check exact prefab details for QuLing_S2 water, Asuna_S8 trail01, Gawana_S2 particle2, Mist_S3 bd_trail, QingHao_S3 bd_trail/nq, RubyRose_S2 pingmu, HeLing_S2 yun, QingDai_S2 fx_9008143
    print("\n" + "=" * 80)
    print("4. Deep inspection of problem prefabs & materials & Animators")
    print("=" * 80)
    def resolve_any(af, fid, pid):
        return indexer.resolve_ext(af, fid, pid)

    def dump_ps_detail(objs, go_by_name, prefab_name, node_filter=None):
        pids = go_by_name.get(Path(prefab_name).name.lower(), [])
        if not pids:
            print(f"  [NOT FOUND prefab {prefab_name}]")
            return
        def walk(gid, path, pws):
            go = objs.get(gid)
            if not go: return
            g = go.read()
            tf = None; ps = None; psr = None; anim = None
            for c in g.m_Component:
                co = objs.get(c.component.path_id)
                if not co: continue
                if co.type.name in ("Transform", "RectTransform"): tf = co.read()
                elif co.type.name == "ParticleSystem": ps = co.read_typetree()
                elif co.type.name == "ParticleSystemRenderer": psr = co.read_typetree()
                elif co.type.name == "Animator": anim = co.read_typetree()
            ls = (tf.m_LocalScale.x, tf.m_LocalScale.y, tf.m_LocalScale.z) if tf else (1,1,1)
            ws = [pws[0]*ls[0], pws[1]*ls[1], pws[2]*ls[2]]
            cp = f"{path}/{g.m_Name}" if path else g.m_Name
            if anim:
                ctrl_ref = anim.get("m_Controller", {})
                print(f"  ANIMATOR on {cp}: controller={ctrl_ref} enabled={anim.get('m_Enabled')}")
            if ps and (node_filter is None or g.m_Name in node_filter):
                init = ps.get("InitialModule", {})
                em = ps.get("EmissionModule", {})
                sh = ps.get("ShapeModule", {})
                vel = ps.get("VelocityModule", {})
                tr = ps.get("TrailModule", {})
                sub = ps.get("SubModule", {})
                col = ps.get("ColorModule", {})
                szm = ps.get("SizeModule", {})
                print(f"  PS [{cp}] active={getattr(g,'m_IsActive',True)} lsc={[round(x,3) for x in ls]} ws={[round(x,3) for x in ws]}")
                print(f"    sm={ps.get('scalingMode')} spd={init.get('startSpeed')} sz={init.get('startSize')} sz3d={init.get('size3D')} lt={init.get('startLifetime')} maxP={init.get('maxNumParticles')} delay={ps.get('startDelay')}")
                print(f"    col={init.get('startColor')} colOverLife_en={col.get('enabled')} szOverLife_en={szm.get('enabled')} sizeOverLife={szm.get('curve') if szm.get('enabled') else None}")
                print(f"    em_en={em.get('enabled')} rateT={em.get('rateOverTime')} rateD={em.get('rateOverDistance')} bursts={em.get('m_Bursts')}")
                print(f"    shape_en={sh.get('enabled')} type={sh.get('type')} vel_en={vel.get('enabled')} trails_en={tr.get('enabled')} sub_en={sub.get('enabled')}")
                if psr:
                    print(f"    PSR rm={psr.get('m_RenderMode')} velSc={psr.get('m_VelocityScale')} lenSc={psr.get('m_LengthScale')} camVel={psr.get('m_CameraVelocityScale')} maxPS={psr.get('m_MaxParticleSize')} sortFudge={psr.get('m_SortingFudge')} mats={psr.get('m_Materials')}")
                    for mi, mr in enumerate(psr.get("m_Materials", [])):
                        mo = resolve_any(go.assets_file, mr.get("m_FileID", 0), mr.get("m_PathID", 0))
                        if mo:
                            mtt = mo.read_typetree()
                            sp = mtt.get("m_SavedProperties", {})
                            flts = dict(sp.get("m_Floats", []))
                            cols = {k: (round(v["r"],3), round(v["g"],3), round(v["b"],3), round(v["a"],3)) for k, v in sp.get("m_Colors", [])}
                            print(f"      mat[{mi}]={mtt.get('m_Name')} flts={flts} cols={cols}")
            if tf:
                for ch in tf.m_Children:
                    ctf = objs.get(ch.path_id)
                    if ctf: walk(ctf.read().m_GameObject.path_id, cp, ws)
        walk(pids[0], "", [1.0, 1.0, 1.0])

    print("--- 2301_QuLing_S2 water ---")
    dump_ps_detail(indexer.ui_objs, indexer.ui_go_by_name, "QuLing_S2_Background", {"water", "particle2"})
    print("--- 603_Asuna_S8 trail01 ---")
    dump_ps_detail(indexer.ui_objs, indexer.ui_go_by_name, "Asuna_S8_Background", {"trail01"})
    print("--- 1601_Gawana_S2 particle2 ---")
    dump_ps_detail(indexer.art_objs, indexer.art_go_by_name, "Gawana_dress01", {"particle2", "particle2 (1)"})
    print("--- 2802_Mist_S3 bd_trail ---")
    dump_ps_detail(indexer.art_objs, indexer.art_go_by_name, "FX_Mist_S3_Background_touch01", {"bd_trail (1)", "bd_trail (2)"})
    print("--- 3602_QingHao_S3 bd_trail & nq ---")
    dump_ps_detail(indexer.art_objs, indexer.art_go_by_name, "FX_QingHao_S3_Background_greet", {"bd_trail", "nq"})
    print("--- 4501_RubyRose_S2 pingmu ---")
    dump_ps_detail(indexer.art_objs, indexer.art_go_by_name, "FX_RubyRose_S2_Background_chat", {"pingmu"})
    print("--- 4301_HeLing_S2 yun ---")
    dump_ps_detail(indexer.ui_objs, indexer.ui_go_by_name, "HeLing_S2_Background", {"yun"})
    print("--- 3501_QingDai_S2 fx_9008143 (all) ---")
    dump_ps_detail(indexer.art_objs, indexer.art_go_by_name, "QingDai_S2_Background_touch2")

    # Also check ALL frames 30..216 of 3501_QingDai_S2/fx_9008143/normal AND whether Animator clips exist in art_prefabs
    print("\n--- Check 3501_QingDai_S2/fx_9008143/normal frames 35..170 ---")
    d = Path(r"E:\A灵魂潮汐\tools\_batch_fx_sequences\3501_QingDai_S2\fx_9008143\normal")
    for idx in [1, 20, 36, 37, 38, 40, 45, 54, 72, 90, 120, 160, 162, 163]:
        p = d / f"frame_{idx:04d}.png"
        if p.exists():
            arr = np.array(Image.open(p).convert("RGBA"))
            nz = np.argwhere(arr[:,:,3] > 0)
            bb = (int(nz[:,1].min()), int(nz[:,0].min()), int(nz[:,1].max()), int(nz[:,0].max())) if len(nz) else None
            print(f"  {p.name}: nonzero={len(nz)} amax={arr[:,:,3].max()} bb={bb}")

    # 5. Lua search for how game attaches Dress FX & Point_Root
    print("\n" + "=" * 80)
    print("5. Search Lua scripts for BgPrefabs / Cv_Point / Point_Root / DressUnlockShow")
    print("=" * 80)
    pat_files = []
    for lf in DECOMPILED_DIR.rglob("*.lua"):
        if "Table" in lf.name or "I18N" in lf.name:
            continue
        txt = lf.read_text(encoding="utf-8", errors="ignore")
        if any(k in txt for k in ("Cv_Point", "Point_Root", "BgPrefabs", "EffectID", "SpineAction")):
            print(f"  Lua match: {lf.relative_to(DECOMPILED_DIR)}")
            for i, line in enumerate(txt.splitlines(), 1):
                if any(k in line for k in ("Cv_Point", "Point_Root", "BgPrefabs", "EffectID")):
                    print(f"    L{i}: {line.strip()[:140]}")


if __name__ == "__main__":
    main()
