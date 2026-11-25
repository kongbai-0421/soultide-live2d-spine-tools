import json, sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

# 1. Compress bg_2002_ennis_s3, bg_4402_dora_s3, bg_404_freesia_s6 for visual check
out_prev = Path(r".\_scratch\audit_previews")
for pat in ("bg_2002_ennis_s3.png", "bg_4402_dora_s3.png", "bg_404_freesia_s6.png"):
    hits = list(Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine").glob(f"*/*/submodels/bg_static/{pat}"))
    if hits:
        im = Image.open(hits[0]).convert("RGBA")
        bg = Image.new("RGBA", im.size, (20, 24, 34, 255))
        c = Image.alpha_composite(bg, im).convert("RGB")
        c.resize((c.width // 2, c.height // 2), Image.Resampling.LANCZOS).save(out_prev / f"chk_{Path(pat).stem}_50pct.jpg", "JPEG", quality=80)
        print("Preview saved:", hits[0], im.size)

# 2. Check ALL SubEmitter `properties` flags in ABs & TrailModule `m_Materials[1]` + Trail params + Shader UV/Dissolve/Mask02 properties
idx = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
cat = bfe.build_skin_catalog(repo)

# Collect all particle prefabs referenced by skins
seen_prefabs = set()
sub_props = {}
shader_props = {}

def scan_ps_tree(objs, gpid, ctx):
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
    if ps:
        se = ps.get("SubModule", {})
        if se.get("enabled"):
            for ent in se.get("subEmitters", []):
                ep = ent.get("emitter", {}).get("m_PathID", 0)
                if ep != 0:
                    sub_props[f"{ctx}/{name} -> pid={ep}"] = {
                        "type": ent.get("type"),
                        "properties": ent.get("properties"),
                        "emitProb": ent.get("emitProbability"),
                    }
        if psr:
            for mi, mref in enumerate(psr.get("m_Materials", [])):
                mobj = idx.resolve_ext(objs[gpid].assets_file, mref.get("m_FileID", 0), mref.get("m_PathID", 0))
                if mobj and mobj.type.name == "Material":
                    mt = mobj.read_typetree()
                    sref = mt.get("m_Shader", {})
                    sobj = idx.resolve_ext(mobj.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
                    sname = "?"
                    decl = set()
                    if sobj and sobj.type.name == "Shader":
                        st = sobj.read_typetree()
                        sname = st.get("m_ParsedForm", {}).get("m_Name", "?")
                        for p in st.get("m_ParsedForm", {}).get("m_PropInfo", {}).get("m_Props", []):
                            decl.add(p.get("m_Name", ""))
                    sp = mt.get("m_SavedProperties", {})
                    flts = dict(sp.get("m_Floats", []))
                    cols = dict(sp.get("m_Colors", []))
                    texs = dict(sp.get("m_TexEnvs", []))
                    shader_props.setdefault(sname, {"decl": decl, "used_flts": set(), "used_cols": set(), "used_texs": set(), "mats": set()})
                    shader_props[sname]["used_flts"].update(flts.keys())
                    shader_props[sname]["used_cols"].update(cols.keys())
                    shader_props[sname]["used_texs"].update(texs.keys())
                    shader_props[sname]["mats"].add(mt.get("m_Name", "?"))
    if tf:
        for ch in tf.get("m_Children", []):
            ct = objs.get(ch["m_PathID"])
            if ct: scan_ps_tree(objs, ct.read_typetree()["m_GameObject"]["m_PathID"], ctx)

for r in cat:
    if r.get("bg_prefab"):
        bp = Path(r["bg_prefab"]).stem.lower()
        if bp in idx.ui_go_by_name:
            scan_ps_tree(idx.ui_objs, idx.ui_go_by_name[bp][0], f"{r['skin_key']}/bg")
        elif bp in idx.art_go_by_name:
            scan_ps_tree(idx.art_objs, idx.art_go_by_name[bp][0], f"{r['skin_key']}/bg")
    for eid, ep in (r.get("effect_prefabs") or {}).items():
        for k, pid in idx.art_container.items():
            if ep.lower() in k.lower():
                co = idx.art_objs[pid].read_typetree()
                gpid = co["m_GameObject"]["m_PathID"] if "m_GameObject" in co else pid
                scan_ps_tree(idx.art_objs, gpid, f"{r['skin_key']}/fx_{eid}")
                break

print(f"\n=== ALL ACTIVE SUBEMITTERS ({len(sub_props)}) ===")
for k, v in sorted(sub_props.items()):
    print(f"  {k}: {v}")

print(f"\n=== SHADER DECLARED PROPERTIES VS MATERIAL USED PROPS ({len(shader_props)} shaders) ===")
for sn, info in sorted(shader_props.items()):
    if any(k in sn.lower() for k in ("uv", "rongjie", "dissolve", "raodong", "mask", "particle", "add", "alpha", "lizi")):
        print(f"  Shader {sn!r} (mats={len(info['mats'])}):")
        print(f"    DECL: {sorted(info['decl'])}")
        print(f"    FLTS: {sorted(info['used_flts'] & info['decl'])}")
        print(f"    COLS: {sorted(info['used_cols'] & info['decl'])}")
        print(f"    TEXS: {sorted(info['used_texs'] & info['decl'])}")
