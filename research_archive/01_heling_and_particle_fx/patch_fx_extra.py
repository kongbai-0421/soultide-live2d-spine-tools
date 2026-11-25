import sys, json
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

OUT_DIR = Path(r".\_scratch\unity_fx_proj")
spec = json.loads((OUT_DIR / "fx_spec.json").read_text("utf-8"))

def collect_extra(rel, tid):
    env = load_ab(CDN_ROOT / rel)
    obj = {o.path_id: o for o in env.objects}
    rid = tid if isinstance(tid, int) else {k.lower(): v.path_id for k, v in env.container.items()}[tid.lower()]
    res = {}
    def w(gid):
        go = obj[gid].read()
        if not go.m_IsActive: return
        rt = None
        ps_sh = None
        psr_tt = None
        for c in go.m_Component:
            co = obj.get(c.component.path_id)
            if not co: continue
            if co.type.name in ("RectTransform", "Transform"): rt = co.read()
            elif co.type.name == "ParticleSystem":
                tt = co.read_typetree()
                if tt.get("EmissionModule", {}).get("enabled"):
                    ps_sh = tt.get("ShapeModule", {})
            elif co.type.name == "ParticleSystemRenderer":
                psr_tt = co.read_typetree()
        if ps_sh is not None:
            r = ps_sh.get("m_Rotation", {})
            p = ps_sh.get("m_Position", {})
            pv = psr_tt.get("m_Pivot", {}) if psr_tt else {}
            res[go.m_Name] = {
                "shapeRot": [float(r.get("x",0)), float(r.get("y",0)), float(r.get("z",0))],
                "shapePos": [float(p.get("x",0)), float(p.get("y",0)), float(p.get("z",0))],
                "renderMode": int(psr_tt.get("m_RenderMode", 0)) if psr_tt else 0,
                "velocityScale": float(psr_tt.get("m_VelocityScale", 0)) if psr_tt else 0.0,
                "lengthScale": float(psr_tt.get("m_LengthScale", 2)) if psr_tt else 2.0,
                "pivot": [float(pv.get("x",0)), float(pv.get("y",0)), float(pv.get("z",0))],
            }
        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in obj: w(obj[ch.path_id].read().m_GameObject.path_id)
    w(rid)
    return res

ex_idle = collect_extra("03_prefabs/ui.ab", 8268094511723853665)
ex_chat = collect_extra("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_chat.prefab")
ex_touch = collect_extra("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab")

for clip, ex in (("idle", ex_idle), ("fx_9008135", ex_chat), ("fx_9008136", ex_touch)):
    for n in spec[clip]["nodes"]:
        n.update(ex.get(n["name"], {}))
        print(clip, n["name"], "size=", n["size"]["mode"], n["size"]["scalar"], n["size"]["minScalar"], "shRot=", n.get("shapeRot"), "rm=", n.get("renderMode"), "colA=", round(n["startColor"]["a"],2), "tintA=", round(n["tint"]["a"],2))

(OUT_DIR / "fx_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
