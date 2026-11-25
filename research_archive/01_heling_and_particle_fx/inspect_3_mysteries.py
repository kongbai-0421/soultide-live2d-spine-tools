import sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as b

idx = b.AssetIndexer()
repo = b.FullI18nRepo()
skins = b.build_skin_catalog(repo)
by_key = {s["skin_key"]: s for s in skins}

def dump_go_tree(objs, gid, depth=0):
    go = objs[gid].read()
    rt = None
    tr_str = ""
    comps = []
    for c in go.m_Component:
        co = objs.get(c.component.path_id)
        if not co:
            continue
        comps.append(co.type.name)
        if co.type.name in ("Transform", "RectTransform"):
            rt = co.read()
            p = rt.m_LocalPosition
            s = rt.m_LocalScale
            r = rt.m_LocalRotation
            ap = getattr(rt, "m_AnchoredPosition", None)
            ap_s = f" ap=({ap.x:.3f},{ap.y:.3f})" if ap is not None else ""
            tr_str = f"lp=({p.x:.3f},{p.y:.3f},{p.z:.3f}){ap_s} ls=({s.x:.4f},{s.y:.4f},{s.z:.4f}) lr=({r.x:.4f},{r.y:.4f},{r.z:.4f},{r.w:.4f})"
    print("  " * depth + f"[{go.m_IsActive}] {go.m_Name} {tr_str} comps={comps}")
    if rt is not None:
        for ch in rt.m_Children:
            cobj = objs.get(ch.path_id)
            if cobj:
                cr = cobj.read()
                cgid = cr.m_GameObject.path_id
                if cgid in objs:
                    dump_go_tree(objs, cgid, depth + 1)

# 1. Inspect 702_Minerdwen_S3 bg_prefab + fx_9008162
for skey in ["702_Minerdwen_S3", "2301_QuLing_S2", "603_Asuna_S8"]:
    sk = by_key[skey]
    print(f"\n================ {skey} ================")
    bgp = Path(sk["bg_prefab"]).name.lower()
    objs = idx.ui_objs if bgp in idx.ui_go_by_name else idx.art_objs
    gids = idx.ui_go_by_name.get(bgp) or idx.art_go_by_name.get(bgp)
    print("BG PREFAB:", sk["bg_prefab"])
    dump_go_tree(objs, gids[0])
    layout = b.inspect_bg_prefab_layout(idx, sk)
    print("LAYOUT:", {k: v for k, v in layout.items() if k != "layers"})
    for eid in sk.get("ef_ids", []):
        ep = repo.effect_path_by_id.get(eid, "")
        eb = Path(ep).name.lower()
        cands = idx.art_go_by_name.get(eb, [])
        print(f"EFFECT {eid}: {ep} cands={len(cands)}")
        if cands:
            dump_go_tree(idx.art_objs, cands[0])
