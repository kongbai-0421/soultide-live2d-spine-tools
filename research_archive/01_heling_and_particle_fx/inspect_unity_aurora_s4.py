import sys
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

def dump_bundle_prefab(rel, targets):
    print(f"\n================ {rel} ================")
    env = load_ab(CDN_ROOT / rel)
    obj_by_id = {o.path_id: o for o in env.objects}

    def dump_go(go_id, indent=0):
        go = obj_by_id[go_id].read()
        comps = [obj_by_id[c.component.path_id] for c in go.m_Component if getattr(c, "component", None) and c.component.path_id in obj_by_id]
        rt = None
        rt_info = ""
        extras = []
        for co in comps:
            if co.type.name in ("RectTransform", "Transform"):
                rt = co.read()
                pos = rt.m_LocalPosition
                sc = rt.m_LocalScale
                if co.type.name == "RectTransform":
                    ap = rt.m_AnchoredPosition
                    sd = rt.m_SizeDelta
                    anc0, anc1 = rt.m_AnchorMin, rt.m_AnchorMax
                    rt_info = f"Rect(anch=({ap.x:.2f},{ap.y:.2f}), size=({sd.x:.1f},{sd.y:.1f}), a=({anc0.x:.2f},{anc0.y:.2f})-({anc1.x:.2f},{anc1.y:.2f}), pos=({pos.x:.2f},{pos.y:.2f},{pos.z:.2f}), sc=({sc.x:.4f},{sc.y:.4f},{sc.z:.4f}))"
                else:
                    rt_info = f"Tf(pos=({pos.x:.3f},{pos.y:.3f},{pos.z:.3f}), sc=({sc.x:.4f},{sc.y:.4f},{sc.z:.4f}))"
            elif co.type.name == "ParticleSystemRenderer":
                psr = co.read()
                mat_name = "?"
                if psr.m_Materials and psr.m_Materials[0].path_id in obj_by_id:
                    mat_name = obj_by_id[psr.m_Materials[0].path_id].peek_name()
                extras.append(f"PSR(mat={mat_name}, sort={psr.m_SortingOrder})")
            elif co.type.name == "ParticleSystem":
                ps = co.read()
                dur = getattr(ps, "lengthInSec", "?")
                loop = getattr(ps, "looping", "?")
                extras.append(f"PS(dur={dur}, loop={loop})")
            elif co.type.name == "MonoBehaviour":
                try:
                    mb = co.read()
                    sn = obj_by_id[mb.m_Script.path_id].peek_name() if mb.m_Script.path_id in obj_by_id else "?"
                    extras.append(f"MB({sn})")
                except Exception:
                    extras.append("MB(?)")
            elif co.type.name != "CanvasRenderer":
                extras.append(co.type.name)
        print("  " * indent + f"{go.m_Name} [act={go.m_IsActive}] {rt_info} {extras}")
        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in obj_by_id:
                    ch_tf = obj_by_id[ch.path_id].read()
                    if ch_tf.m_GameObject.path_id in obj_by_id:
                        dump_go(ch_tf.m_GameObject.path_id, indent + 1)

    c_map = {k.lower(): v for k, v in (env.container or {}).items()}
    for t in targets:
        if t.startswith("ID:"):
            pid = int(t[3:])
            print(f"--- {t} ---")
            dump_go(pid)
        else:
            ptr = c_map.get(t.lower())
            if ptr:
                print(f"--- {t} ---")
                dump_go(ptr.path_id)

dump_bundle_prefab("03_prefabs/ui.ab", ["ID:8268094511723853665", "ID:-2364402539493143708", "ID:-1373463960992787037", "ID:3373706024580559637"])
dump_bundle_prefab("03_prefabs/art_prefabs.ab", [
    "assets/03_prefabs/art_prefabs/element/dressspine/aurora_s4/souldress_aurora.prefab",
    "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_chat.prefab",
    "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab",
])
