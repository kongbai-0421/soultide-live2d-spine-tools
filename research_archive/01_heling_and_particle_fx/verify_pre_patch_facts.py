import sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import load_ab, CDN_ROOT
import batch_fx_exporter as bfe

print("CDN_ROOT:", CDN_ROOT, [p.name for p in CDN_ROOT.iterdir() if p.is_dir()])

# 1. Test Mesh.export() on meshes across CDN_ROOT (finding CAB-e181e... / Mesh ABs)
cnt_meshes = 0
sample_errs = []
sample_ok = []
for ab in sorted((CDN_ROOT / "14_effect").rglob("*.ab")) if (CDN_ROOT / "14_effect").exists() else sorted(CDN_ROOT.rglob("*.ab")):
    if cnt_meshes >= 20:
        break
    env = load_ab(ab)
    for o in env.objects:
        if o.type.name == "Mesh":
            cnt_meshes += 1
            try:
                m = o.read()
                obj_txt = m.export()
                if obj_txt and "v " in obj_txt:
                    vs = [l for l in obj_txt.splitlines() if l.startswith("v ")]
                    vts = [l for l in obj_txt.splitlines() if l.startswith("vt ")]
                    xs = [float(l.split()[1]) for l in vs]
                    ys = [float(l.split()[2]) for l in vs]
                    zs = [float(l.split()[3]) for l in vs]
                    if len(sample_ok) < 8:
                        sample_ok.append((ab.name, o.path_id, m.m_Name, len(vs), len(vts), f"x=({min(xs):.3f}..{max(xs):.3f}) y=({min(ys):.3f}..{max(ys):.3f}) z=({min(zs):.3f}..{max(zs):.3f})"))
                else:
                    sample_errs.append((ab.name, o.path_id, m.m_Name, "no v in export"))
            except Exception as e:
                sample_errs.append((ab.name, str(o.path_id), repr(e)))
print(f"Checked {cnt_meshes} meshes; ok={len(sample_ok)} errs={len(sample_errs)}")
for s in sample_ok: print("  OK:", s)
for e in sample_errs[:5]: print("  ERR:", e)

# 2. Check _mask_offon / _offon & Shader additive
idx = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
cat = bfe.build_skin_catalog(repo)

mask_offon_vals = {}
sh_seen = set()

def scan(objs, gpid):
    go = objs[gpid].read_typetree()
    if not go.get("m_IsActive", True): return
    tf = None; psr = None
    for c in go.get("m_Component", []):
        o = objs.get(c["component"]["m_PathID"])
        if not o: continue
        if o.type.name in ("Transform", "RectTransform"): tf = o.read_typetree()
        elif o.type.name == "ParticleSystemRenderer": psr = o.read_typetree()
    if psr:
        af = objs[gpid].assets_file
        for mref in psr.get("m_Materials", []):
            mo = idx.resolve_ext(af, mref.get("m_FileID", 0), mref.get("m_PathID", 0))
            if mo and mo.type.name == "Material":
                mt = mo.read_typetree()
                sp = mt.get("m_SavedProperties", {})
                flts = dict(sp.get("m_Floats", []))
                texs = dict(sp.get("m_TexEnvs", []))
                sr = mt.get("m_Shader", {})
                so = idx.resolve_ext(mo.assets_file, sr.get("m_FileID", 0), sr.get("m_PathID", 0))
                sn = so.read_typetree().get("m_ParsedForm", {}).get("m_Name", "?") if (so and so.type.name=="Shader") else "?"
                if so and sn not in sh_seen:
                    sh_seen.add(sn)
                    print(f"  Shader {sn!r} -> is_shader_additive={idx.is_shader_additive(so, sn, flts)}")
                if "UVliudong" in sn:
                    has_m1 = texs.get("_mask", {}).get("m_Texture", {}).get("m_PathID", 0) != 0
                    has_m2 = texs.get("_mask02", {}).get("m_Texture", {}).get("m_PathID", 0) != 0
                    k = (sn, flts.get("_mask_offon"), flts.get("_offon"), has_m1, has_m2)
                    mask_offon_vals[k] = mask_offon_vals.get(k, 0) + 1
    if tf:
        for ch in tf.get("m_Children", []):
            ct = objs.get(ch["m_PathID"])
            if ct: scan(objs, ct.read_typetree()["m_GameObject"]["m_PathID"])

for r in cat:
    if r.get("bg_prefab"):
        bp = Path(r["bg_prefab"]).stem.lower()
        if bp in idx.ui_go_by_name: scan(idx.ui_objs, idx.ui_go_by_name[bp][0])
        elif bp in idx.art_go_by_name: scan(idx.art_objs, idx.art_go_by_name[bp][0])
    for eid, ep in (r.get("effect_prefabs") or {}).items():
        for k, pid in idx.art_container.items():
            if ep.lower() in k.lower():
                co = idx.art_objs[pid].read_typetree()
                gpid = co["m_GameObject"]["m_PathID"] if "m_GameObject" in co else pid
                scan(idx.art_objs, gpid)
                break

print("\nUVliudong (_mask_offon, _offon, has_m1, has_m2) counts:")
for k, cnt in sorted(mask_offon_vals.items()):
    print(f"  {cnt:3d} {k}")
