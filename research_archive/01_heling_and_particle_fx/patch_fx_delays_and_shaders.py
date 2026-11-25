import json, math, sys
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

OUT_DIR = Path(r".\_scratch\unity_fx_proj")
spec = json.loads((OUT_DIR / "fx_spec.json").read_text("utf-8"))

# 1. Patch true startDelay, UV frameOverTime, and exact game Shader isAdditive flags!
env = load_ab(CDN_ROOT / "03_prefabs/art_prefabs.ab")
obj = {o.path_id: o for o in env.objects}
def collect_delays_and_uv(k):
    rid = {kk.lower(): v.path_id for kk, v in env.container.items()}[k.lower()]
    res = {}
    def w(gid):
        go = obj[gid].read(); rt = None
        for c in go.m_Component:
            co = obj.get(c.component.path_id)
            if not co: continue
            if co.type.name in ("RectTransform", "Transform"): rt = co.read()
            elif co.type.name == "ParticleSystem":
                tt = co.read_typetree()
                uv = tt.get("UVModule", {})
                fot = uv.get("frameOverTime", {})
                res[go.m_Name] = {
                    "startDelay": float(tt.get("startDelay", {}).get("scalar", 0.0)),
                    "uvMode": int(uv.get("mode", 0)) if uv.get("enabled") else -1,
                    "uvAnim": int(uv.get("animationType", 0)),
                    "uvRowMode": int(uv.get("rowMode", 0)),
                    "uvFrameMode": int(fot.get("minMaxState", 1)),
                    "uvFrameScalar": float(fot.get("scalar", 1.0)),
                    "uvFrameMin": float(fot.get("minScalar", 0.0)),
                }
        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children: w(obj[ch.path_id].read().m_GameObject.path_id)
    w(rid)
    return res

d_chat = collect_delays_and_uv("assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_chat.prefab")
d_touch = collect_delays_and_uv("assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab")

# Exact Blend modes verified from Unity Material Shaders in task-3450:
# Alpha Blended: yinghuochong (chat), beike & xianglian (touch1)
# Additive / UVliudong Glow: all idle (incl. smoke), aixin, bao, glow01, lizi_san, shan, xianglian_glow
ALPHA_NAMES = {"yinghuochong", "beike", "xianglian"}

for clip, dmap in (("idle", {}), ("fx_9008135", d_chat), ("fx_9008136", d_touch)):
    for n in spec[clip]["nodes"]:
        n.update(dmap.get(n["name"], {"startDelay": 0.0, "uvMode": -1}))
        n["isAdditive"] = n["name"] not in ALPHA_NAMES
        print(clip, n["name"], f"delay={n.get('startDelay',0):.2f}s add={n['isAdditive']} uvFMode={n.get('uvFrameMode',-1)}")

(OUT_DIR / "fx_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

# 2. Check hand bone positions at t=5.0s in touch1 / touch1_marry!
skel = json.loads(Path(r"E:\A灵魂潮汐\备份\spine\欧若拉\童话心绘\有背景\SoulDress_Aurora_04.skel.json").read_text("utf-8"))
def eval_curve(arr, t, keys, default):
    if not arr: return default
    if t <= arr[0].get("time", 0.0):
        return tuple(arr[0].get(k, default[i]) for i, k in enumerate(keys))
    for i in range(len(arr) - 1):
        t0, t1 = arr[i].get("time", 0.0), arr[i+1].get("time", 0.0)
        if t0 <= t <= t1:
            u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return tuple(arr[i].get(k, default[j])*(1-u) + arr[i+1].get(k, default[j])*u for j, k in enumerate(keys))
    return tuple(arr[-1].get(k, default[i]) for i, k in enumerate(keys))

for aname in ("touch1", "touch1_marry"):
    ba = skel["animations"].get(aname, {}).get("bones", {})
    bm = {}
    for b in skel["bones"]:
        nm = b["name"]; par = b.get("parent")
        if nm in ("z", "beijing1", "beijing2", "z2"): continue
        lx, ly = b.get("x", 0.0), b.get("y", 0.0)
        lrot = b.get("rotation", 0.0); lsx = b.get("scaleX", 1.0); lsy = b.get("scaleY", 1.0)
        if nm in ba:
            if "translate" in ba[nm]: dx, dy = eval_curve(ba[nm]["translate"], 5.0, ("x","y"), (0,0)); lx += dx; ly += dy
            if "rotate" in ba[nm]: dr, = eval_curve(ba[nm]["rotate"], 5.0, ("angle",), (0,)); lrot += dr
            if "scale" in ba[nm]: dsx, dsy = eval_curve(ba[nm]["scale"], 5.0, ("x","y"), (1,1)); lsx *= dsx; lsy *= dsy
        rad = math.radians(lrot); ca, sa = math.cos(rad), math.sin(rad)
        la, lb, lc, ld = ca*lsx, -sa*lsy, sa*lsx, ca*lsy
        if par and par in bm:
            pa, pb, px, pc, pd, py = bm[par]
            wx, wy = pa*lx + pb*ly + px, pc*lx + pd*ly + py
            if b.get("transform", "normal") == "noRotationOrReflection":
                s = math.hypot(pa, pc)
                bm[nm] = (la*s, lb*s, wx, lc*s, ld*s, wy)
            else:
                bm[nm] = (pa*la+pb*lc, pa*lb+pb*ld, wx, pc*la+pd*lc, pc*lb+pd*ld, wy)
        else:
            bm[nm] = (la, lb, lx, lc, ld, ly)
    print(f"{aname} @t=5s: bone 113(Lhand)={bm.get('113',(0,0,0,0,0,0))[2]:.1f},{bm.get('113',(0,0,0,0,0,0))[5]:.1f}  bone 321(Rhand)={bm.get('321',(0,0,0,0,0,0))[2]:.1f},{bm.get('321',(0,0,0,0,0,0))[5]:.1f}  chuxian=(192.0, 826.0)")
