import sys
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

for rel, tid, label in [
    ("03_prefabs/ui.ab", 8268094511723853665, "Aurora_S4_Background"),
    ("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_chat.prefab", "chat"),
    ("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab", "touch1"),
]:
    print("===", label, "===")
    env = load_ab(CDN_ROOT / rel)
    obj = {o.path_id: o for o in env.objects}
    rid = tid if isinstance(tid, int) else {k.lower(): v.path_id for k, v in env.container.items()}[tid.lower()]
    def w(gid):
        go = obj[gid].read()
        rt = None
        if not go.m_IsActive: return
        for c in go.m_Component:
            co = obj.get(c.component.path_id)
            if not co: continue
            if co.type.name in ("RectTransform", "Transform"): rt = co.read()
            elif co.type.name == "ParticleSystem":
                tt = co.read_typetree()
                sh = tt.get("ShapeModule", {})
                if tt.get("EmissionModule", {}).get("enabled"):
                    psr_info = ""
                    for c2 in go.m_Component:
                        co2 = obj.get(c2.component.path_id)
                        if co2 and co2.type.name == "ParticleSystemRenderer":
                            p = co2.read_typetree()
                            psr_info = f"mode={p.get('m_RenderMode')} velSc={p.get('m_VelocityScale')} lenSc={p.get('m_LengthScale')} pivot={p.get('m_Pivot')}"
                    print(f"  {go.m_Name:16s} sh_rot={sh.get('m_Rotation')} sh_pos={sh.get('m_Position')} {psr_info}")
        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in obj:
                    w(obj[ch.path_id].read().m_GameObject.path_id)
    w(rid)
