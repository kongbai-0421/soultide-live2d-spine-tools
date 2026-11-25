import sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

idx = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
cat = bfe.build_skin_catalog(repo)

# 1. Check cam changes with >=1600 filter
print("=== 1. Cam layout diff when preferring w >= 1600 ===")
for sk in cat:
    if not sk.get("bg_prefab"): continue
    lay = bfe.inspect_bg_prefab_layout(idx, sk)
    # Re-walk bg_images quickly using same logic:
    bgp = sk["bg_prefab"]
    base = Path(bgp).name.lower()
    objs = idx.ui_objs if base in idx.ui_go_by_name else idx.art_objs
    gid = idx.ui_go_by_name[base][0] if base in idx.ui_go_by_name else idx.art_go_by_name[base][0]
    imgs = []
    def w(g, d, pp, ps, pq, in_h):
        go = objs[g].read(); nm = go.m_Name; low = nm.lower(); ih = in_h or ("harmonious" in low)
        rt, ir, (lx,ly,lz), (sx,sy,sz), lq = bfe._node_local_tf(go, objs, ignore_root_pos=(d==0))
        rx, ry, rz = bfe._qrot(pq, (lx*ps[0], ly*ps[1], lz*ps[2]))
        wx, wy, wz = pp[0]+rx, pp[1]+ry, pp[2]+rz
        wsx, wsy, wsz = ps[0]*sx, ps[1]*sy, ps[2]*sz
        wq = bfe._qmul(pq, lq)
        if go.m_IsActive and not ih:
            for c in go.m_Component:
                co = objs.get(c.component.path_id)
                if co and co.type.name=="MonoBehaviour":
                    try:
                        tt=co.read_typetree()
                        if "m_Sprite" in tt and low not in bfe.SKIP_IMAGE_NAMES:
                            sd = rt.m_SizeDelta if ir else None
                            if sd: imgs.append({"name":nm,"wx":wx,"wy":wy,"w":float(sd.x)*abs(wsx),"h":float(sd.y)*abs(wsy)})
                    except: pass
        if rt and hasattr(rt,"m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in objs: w(objs[ch.path_id].read().m_GameObject.path_id, d+1, (wx,wy,wz), (wsx,wsy,wsz), wq, ih)
    w(gid, 0, (0,0,0), (1,1,1), (0,0,0,1), False)
    big = [im for im in imgs if im["w"] >= 1000 and im["h"] >= 600]
    full = [im for im in big if im["w"] >= 1600]
    pool = full or big
    if pool:
        mb = min(pool, key=lambda x: (0 if x["name"].lower() in ("image_01","image_02") else 1, abs(x["w"]-1768)+abs(x["h"]-1176)))
        if abs(mb["wx"] - lay["cam_x"]) > 5 or abs(mb["wy"] - lay["cam_y"]) > 5:
            print(f"  CHANGED {sk['skin_key']}: old=({lay['cam_x']},{lay['cam_y']}) {lay['canvas_w']}x{lay['canvas_h']} -> new=({round(mb['wx'],1)},{round(mb['wy'],1)}) {mb['w']:.0f}x{mb['h']:.0f} [{mb['name']}]")

# 2. Check all Trail nodes main vs trail blend mode & widthOverTrail curve details
print("\n=== 2. Trail nodes main vs trail blend mode ===")
def check_trails(objs, gp, ctx):
    go = objs[gp].read_typetree()
    if not go.get("m_IsActive", True): return
    tf=None; ps=None; psr=None
    for c in go.get("m_Component", []):
        o = objs.get(c["component"]["m_PathID"])
        if not o: continue
        if o.type.name in ("Transform","RectTransform"): tf=o.read_typetree()
        elif o.type.name=="ParticleSystem": ps=o.read_typetree()
        elif o.type.name=="ParticleSystemRenderer": psr=o.read_typetree()
    if ps and psr and ps.get("TrailModule",{}).get("enabled"):
        mrefs=psr.get("m_Materials",[])
        def minfo(mref):
            if not mref or mref.get("m_PathID",0)==0: return ("NONE", None)
            mo = idx.resolve_ext(objs[gp].assets_file, mref.get("m_FileID",0), mref.get("m_PathID",0))
            if not mo or mo.type.name!="Material": return ("UNRES", None)
            mt=mo.read_typetree()
            sp=mt.get("m_SavedProperties",{}); flts={k:float(v) for k,v in sp.get("m_Floats",[])}
            sr=mt.get("m_Shader",{}); so=idx.resolve_ext(mo.assets_file, sr.get("m_FileID",0), sr.get("m_PathID",0))
            sn=so.read_typetree().get("m_ParsedForm",{}).get("m_Name","?") if (so and so.type.name=="Shader") else "?"
            return (mt.get("m_Name"), idx.is_shader_additive(so, sn, flts))
        m0 = minfo(mrefs[0] if len(mrefs)>0 else None)
        m1 = minfo(mrefs[1] if len(mrefs)>1 else None)
        tm = ps.get("TrailModule", {})
        print(f"  {ctx}/{go['m_Name']:18s} rm={psr.get('m_RenderMode')} main={m0} trail={m1} wOT_mode={tm.get('widthOverTrail',{}).get('minMaxState')} ratio={tm.get('ratio')} ribbon={tm.get('ribbonCount')} texMode={tm.get('textureMode')}")
    if tf:
        for ch in tf.get("m_Children", []):
            ct = objs.get(ch["m_PathID"])
            if ct: check_trails(objs, ct.read_typetree()["m_GameObject"]["m_PathID"], ctx)

for sk in cat:
    if sk.get("bg_prefab"):
        bp=Path(sk["bg_prefab"]).stem.lower()
        if bp in idx.ui_go_by_name: check_trails(idx.ui_objs, idx.ui_go_by_name[bp][0], sk["skin_key"]+"/bg")
        elif bp in idx.art_go_by_name: check_trails(idx.art_objs, idx.art_go_by_name[bp][0], sk["skin_key"]+"/bg")
    for eid, ep in (sk.get("effect_prefabs") or {}).items():
        for k, pid in idx.art_container.items():
            if ep.lower() in k.lower():
                co=idx.art_objs[pid].read_typetree()
                check_trails(idx.art_objs, co["m_GameObject"]["m_PathID"] if "m_GameObject" in co else pid, f"{sk['skin_key']}/fx_{eid}")
                break
