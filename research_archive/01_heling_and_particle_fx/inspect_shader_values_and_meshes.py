import json, sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

idx = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
cat = bfe.build_skin_catalog(repo)

mat_samples = defaultdict(list)
trail_nodes = []
mesh_refs = defaultdict(int)
custom_stream_nodes = []

def scan(objs, gpid, ctx):
    go = objs[gpid].read_typetree()
    if not go.get("m_IsActive", True):
        return
    name = go.get("m_Name", "?")
    tf = None; ps = None; psr = None
    for c in go.get("m_Component", []):
        o = objs.get(c["component"]["m_PathID"])
        if not o: continue
        if o.type.name in ("Transform", "RectTransform"): tf = o.read_typetree()
        elif o.type.name == "ParticleSystem": ps = o.read_typetree()
        elif o.type.name == "ParticleSystemRenderer": psr = o.read_typetree()
    if ps and psr:
        af = objs[gpid].assets_file
        if ps.get("TrailModule", {}).get("enabled"):
            mrefs = psr.get("m_Materials", [])
            tmat = None
            if len(mrefs) > 1:
                mo = idx.resolve_ext(af, mrefs[1].get("m_FileID", 0), mrefs[1].get("m_PathID", 0))
                if mo and mo.type.name == "Material":
                    tmat = mo.read_typetree().get("m_Name")
            trail_nodes.append((ctx, name, ps.get("TrailModule"), tmat, psr.get("m_RenderMode")))
        if psr.get("m_RenderMode") == 4:
            for mf in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3"):
                mr = psr.get(mf, {})
                pid = mr.get("m_PathID", 0)
                if pid != 0:
                    mo = idx.resolve_ext(af, mr.get("m_FileID", 0), pid)
                    if mo and mo.type.name == "Mesh":
                        mt = mo.read_typetree()
                        mesh_refs[(af.name if mr.get("m_FileID",0)==0 else str(mo.assets_file.name), pid, mt.get("m_Name","?"))] += 1
                    else:
                        ext_p = af.externals[mr["m_FileID"]-1].path if 0 < mr.get("m_FileID",0) <= len(af.externals) else "local"
                        mesh_refs[(ext_p, pid, f"UNRESOLVED({mo.type.name if mo else 'None'})")] += 1
        if psr.get("m_UseCustomVertexStreams") and psr.get("m_VertexStreams"):
            custom_stream_nodes.append((ctx, name, psr.get("m_VertexStreams")))
        for mref in psr.get("m_Materials", []):
            mo = idx.resolve_ext(af, mref.get("m_FileID", 0), mref.get("m_PathID", 0))
            if mo and mo.type.name == "Material":
                mt = mo.read_typetree()
                sr = mt.get("m_Shader", {})
                so = idx.resolve_ext(mo.assets_file, sr.get("m_FileID", 0), sr.get("m_PathID", 0))
                sn = so.read_typetree().get("m_ParsedForm", {}).get("m_Name", "?") if (so and so.type.name=="Shader") else "?"
                if any(k in sn.lower() for k in ("uv", "rongjie", "raodong")):
                    sp = mt.get("m_SavedProperties", {})
                    flts = {k: round(v, 3) for k, v in sp.get("m_Floats", [])}
                    cols = {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in sp.get("m_Colors", [])}
                    texs = {k: (v.get("m_Scale"), v.get("m_Offset"), v.get("m_Texture", {}).get("m_PathID", 0) != 0) for k, v in sp.get("m_TexEnvs", [])}
                    mat_samples[sn].append((mt.get("m_Name"), flts, cols, texs))
    if tf:
        for ch in tf.get("m_Children", []):
            ct = objs.get(ch["m_PathID"])
            if ct: scan(objs, ct.read_typetree()["m_GameObject"]["m_PathID"], ctx)

for r in cat:
    if r.get("bg_prefab"):
        bp = Path(r["bg_prefab"]).stem.lower()
        if bp in idx.ui_go_by_name: scan(idx.ui_objs, idx.ui_go_by_name[bp][0], f"{r['skin_key']}/bg")
        elif bp in idx.art_go_by_name: scan(idx.art_objs, idx.art_go_by_name[bp][0], f"{r['skin_key']}/bg")
    for eid, ep in (r.get("effect_prefabs") or {}).items():
        for k, pid in idx.art_container.items():
            if ep.lower() in k.lower():
                co = idx.art_objs[pid].read_typetree()
                gpid = co["m_GameObject"]["m_PathID"] if "m_GameObject" in co else pid
                scan(idx.art_objs, gpid, f"{r['skin_key']}/fx_{eid}")
                break

print("=== MATERIAL PROPERTY SAMPLES ===")
for sn, items in sorted(mat_samples.items()):
    print(f"\nShader: {sn} ({len(items)} usages)")
    seen = set()
    for mname, flts, cols, texs in items:
        if mname in seen: continue
        seen.add(mname)
        print(f"  Mat={mname!r} flts={flts} cols={cols}")
        if len(seen) >= 6: break

print(f"\n=== CUSTOM VERTEX STREAM NODES ({len(custom_stream_nodes)}) ===")
for row in custom_stream_nodes[:20]:
    print(" ", row)

print(f"\n=== TRAIL NODES ({len(trail_nodes)}) ===")
for ctx, name, tm, tmat, rm in trail_nodes:
    print(f"  {ctx}/{name} rm={rm} tmat={tmat!r} mode={tm.get('mode')} life={tm.get('lifetime',{}).get('scalar')} minDist={tm.get('minVertexDistance')} ws={tm.get('worldSpace')} die={tm.get('dieWithParticles')} wOT={tm.get('widthOverTrail',{}).get('scalar')} inheritC={tm.get('inheritParticleColor')} sizeAW={tm.get('sizeAffectsWidth')} col={tm.get('colorOverLifetime',{}).get('maxColor')} / {tm.get('colorOverTrail',{}).get('maxColor')}")

print(f"\n=== MESH REFS ({len(mesh_refs)}) ===")
for k, cnt in sorted(mesh_refs.items(), key=lambda kv: -kv[1]):
    print(f"  cnt={cnt:3d} {k}")
