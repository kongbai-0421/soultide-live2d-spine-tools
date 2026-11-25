import sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as b

idx = b.AssetIndexer()
repo = b.FullI18nRepo()
skins = b.build_skin_catalog(repo)

targets = {
    "702_Minerdwen_S3",
    "402_Freesia_S5",
    "4501_RubyRose_S2",
    "404_Freesia_S6",
    "1803_SakuyaMako_S4",
    "4801_Micha_S2",
}

def dump_go(g, d=0):
    go = idx.art_objs[g].read()
    rt = None
    has_ps = False
    for c in go.m_Component:
        co = idx.art_objs.get(c.component.path_id)
        if not co:
            continue
        if co.type.name == "ParticleSystem":
            has_ps = True
        if co.type.name in ("Transform", "RectTransform"):
            rt = co.read()
            p, sc, r = rt.m_LocalPosition, rt.m_LocalScale, rt.m_LocalRotation
            ap = getattr(rt, "m_AnchoredPosition", None)
            ap_s = f" ap=({ap.x:.2f},{ap.y:.2f})" if ap is not None else ""
            ps_s = " [PS]" if has_ps else ""
            print("  " * d + f"[{go.m_IsActive}] {go.m_Name} ({co.type.name}) lp=({p.x:.2f},{p.y:.2f},{p.z:.2f}){ap_s} ls=({sc.x:.4f},{sc.y:.4f},{sc.z:.4f}) lr=({r.x:.3f},{r.y:.3f},{r.z:.3f},{r.w:.3f}){ps_s}")
    if rt and hasattr(rt, "m_Children"):
        for ch in rt.m_Children:
            if ch.path_id in idx.art_objs:
                cgid = idx.art_objs[ch.path_id].read().m_GameObject.path_id
                if cgid in idx.art_objs:
                    dump_go(cgid, d + 1)

for s in skins:
    if s["skin_key"] not in targets:
        continue
    lay = b.inspect_bg_prefab_layout(idx, s)
    print(f"\n=== {s['skin_key']} cam=({lay['cam_x']},{lay['cam_y']}) canvas={lay['canvas_w']}x{lay['canvas_h']} ===")
    print("  person:", lay["person"])
    print("  fx_point_root:", lay["fx_point_root"])
    for eid, pf in s["effect_prefabs"].items():
        ck = f"assets/03_prefabs/art_prefabs/effect/{pf.lower()}.prefab"
        gid = idx.art_container.get(ck)
        if not gid:
            cands = idx.art_go_by_name.get(Path(pf).name.lower(), [])
            gid = cands[0] if cands else None
        print(f"  EFFECT {eid}: {pf} -> gid={gid}")
        if gid:
            dump_go(gid, 2)
