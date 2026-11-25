import sys
from pathlib import Path

tools_dir = r"E:\A灵魂潮汐\tools"
sys.path.insert(0, tools_dir)
import batch_fx_exporter as bfe

repo = bfe.FullI18nRepo()
catalog = bfe.build_skin_catalog(repo)
indexer = bfe.AssetIndexer()

target_keys = {"1003_HagakureRuri_S4", "402_Freesia_S5"}
rot3d_nodes = []
rot_sep_nodes = []
total_ps = 0


def scan_tree(objs, gid, skin_key, clip_name):
    global total_ps
    if gid not in objs:
        return
    go = objs[gid].read()
    if not go.m_IsActive:
        return
    rt = None
    ps_tt = None
    rm = None
    align = None
    for cr in go.m_Component:
        co = objs.get(cr.component.path_id)
        if not co:
            continue
        if co.type.name in ("Transform", "RectTransform"):
            rt = co.read()
        elif co.type.name == "ParticleSystem":
            ps_tt = co.read_typetree()
        elif co.type.name == "ParticleSystemRenderer":
            r2 = co.read_typetree()
            rm = r2.get("m_RenderMode")
            align = r2.get("m_RenderAlignment")

    if ps_tt is not None and ps_tt.get("EmissionModule", {}).get("enabled"):
        total_ps += 1
        init = ps_tt.get("InitialModule", {})
        rot_m = ps_tt.get("RotationModule", {})
        is_target = skin_key in target_keys
        r3d = bool(init.get("rotation3D", False))
        rsep = bool(rot_m.get("enabled", False) and rot_m.get("separateAxes", False))
        info = (skin_key, clip_name, go.m_Name, rm, align, r3d, rsep)
        if r3d:
            rot3d_nodes.append(info)
        if rsep:
            rot_sep_nodes.append(info)
        if is_target and go.m_Name in ("xingxnig_zhuiluo", "yumao"):
            print("TARGET NODE:", info, flush=True)
            print("  ps keys with rot:", [k for k in init if "rot" in k.lower()], flush=True)
            for k in ("rotation3D", "startRotation", "startRotationX", "startRotationY"):
                v = init.get(k)
                print(
                    f"  init.{k}:",
                    v if isinstance(v, bool) else {kk: vv for kk, vv in (v or {}).items() if kk in ("scalar", "minScalar", "minMaxState")},
                    flush=True,
                )
            print("  rot_m enabled:", rot_m.get("enabled"), "sep:", rot_m.get("separateAxes"), flush=True)
            if rot_m.get("enabled"):
                for k in ("x", "y", "curve"):
                    v = rot_m.get(k) or {}
                    print(f"  rot_m.{k}:", {kk: vv for kk, vv in v.items() if kk in ("scalar", "minScalar", "minMaxState")}, flush=True)
            if rt:
                if hasattr(rt, "m_LocalRotation"):
                    print("  localRot:", rt.m_LocalRotation, flush=True)
                if hasattr(rt, "m_LocalScale"):
                    print("  localScale:", rt.m_LocalScale, flush=True)

    if rt and hasattr(rt, "m_Children"):
        for ch in rt.m_Children:
            if ch.path_id in objs:
                cg = objs[ch.path_id].read().m_GameObject.path_id
                scan_tree(objs, cg, skin_key, clip_name)


for s in catalog:
    if s["char_name"] == "欧若拉" and s["dress_name"] == "童话心绘":
        continue
    bgp_base = Path(s["bg_prefab"]).name.lower()
    if bgp_base in indexer.ui_go_by_name:
        bg_objs, bg_gid = indexer.ui_objs, indexer.ui_go_by_name[bgp_base][0]
    elif bgp_base in indexer.art_go_by_name:
        bg_objs, bg_gid = indexer.art_objs, indexer.art_go_by_name[bgp_base][0]
    else:
        bg_objs, bg_gid = None, None
    if bg_objs is not None:
        scan_tree(bg_objs, bg_gid, s["skin_key"], "idle")
    for eid, pf_name in s["effect_prefabs"].items():
        ck = f"assets/03_prefabs/art_prefabs/effect/{pf_name.lower()}.prefab"
        egid = indexer.art_container.get(ck)
        if egid is None:
            cands = indexer.art_go_by_name.get(Path(pf_name).name.lower(), [])
            egid = cands[0] if cands else None
        if egid is not None:
            scan_tree(indexer.art_objs, egid, s["skin_key"], f"fx_{eid}")

print(f"total_ps={total_ps}, rot3d={len(rot3d_nodes)}, rot_sep={len(rot_sep_nodes)}")
for x in rot3d_nodes[:40]:
    print("  rot3d:", x)
for x in rot_sep_nodes[:40]:
    print("  rot_sep:", x)
