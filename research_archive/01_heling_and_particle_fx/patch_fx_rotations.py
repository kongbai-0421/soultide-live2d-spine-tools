import sys, json
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

OUT_DIR = Path(r".\_scratch\unity_fx_proj")
spec = json.loads((OUT_DIR / "fx_spec.json").read_text("utf-8"))

def collect_rotations(rel, tid):
    env = load_ab(CDN_ROOT / rel)
    obj_by_id = {o.path_id: o for o in env.objects}
    rid = tid if isinstance(tid, int) else {k.lower(): v.path_id for k, v in env.container.items()}[tid.lower()]
    rots = {}
    def qmul(a, b):
        x1,y1,z1,w1 = a; x2,y2,z2,w2 = b
        return (
            w1*x2 + x1*w2 + y1*z2 - z1*y2,
            w1*y2 - x1*z2 + y1*w2 + z1*x2,
            w1*z2 + x1*y2 - y1*x2 + z1*w2,
            w1*w2 - x1*x2 - y1*y2 - z1*z2,
        )
    def walk(gid, pq=(0.0,0.0,0.0,1.0)):
        go = obj_by_id[gid].read()
        if not go.m_IsActive: return
        rt = None; lq = (0.0,0.0,0.0,1.0)
        for c in go.m_Component:
            co = obj_by_id.get(c.component.path_id)
            if co and co.type.name in ("RectTransform", "Transform"):
                rt = co.read()
                lr = rt.m_LocalRotation
                lq = (float(lr.x), float(lr.y), float(lr.z), float(lr.w))
        wq = qmul(pq, lq)
        rots[go.m_Name] = wq
        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in obj_by_id:
                    walk(obj_by_id[ch.path_id].read().m_GameObject.path_id, wq)
    walk(rid)
    return rots

# Collect exact world quaternions + transformPoint_Root for fx_9008135 / fx_9008136!
r_idle = collect_rotations("03_prefabs/ui.ab", 8268094511723853665)
r_chat = collect_rotations("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_chat.prefab")
r_touch = collect_rotations("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab")

for n in spec["idle"]["nodes"]:
    n["world_rot"] = list(r_idle.get(n["name"], [0,0,0,1]))

# For fx_9008135 & fx_9008136 spawned under Aurora_S4 Point_Root (UI origin (33.8989, -504.4942), scale 0.59454):
PR_X, PR_Y, PR_SC = 33.8989, -504.4942, 0.59454
for clip, rmap in (("fx_9008135", r_chat), ("fx_9008136", r_touch)):
    for n in spec[clip]["nodes"]:
        n["world_rot"] = list(rmap.get(n["name"], [0,0,0,1]))
        ox, oy, oz = n["world_pos"]
        # Undo earlier (0, -11.44) hack on chat/touch1 so we convert raw Point_Root local cleanly:
        oy_raw = oy + 11.44
        n["world_pos"] = [PR_X + ox * PR_SC, PR_Y + oy_raw * PR_SC, oz * PR_SC]
        n["world_scale"] = [s * PR_SC for s in n["world_scale"]]

(OUT_DIR / "fx_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
print("Updated fx_spec.json with world_rot and Point_Root transforms!")
for clip in ("idle", "fx_9008135", "fx_9008136"):
    print(clip, [(n["name"], [round(v,1) for v in n["world_pos"]], [round(v,2) for v in n["world_rot"]], [round(v,2) for v in n["world_scale"]]) for n in spec[clip]["nodes"]])
