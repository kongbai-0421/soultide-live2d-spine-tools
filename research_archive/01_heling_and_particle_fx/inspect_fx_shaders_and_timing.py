import json, math, sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

# 1. Check exact Shader names and startDelay for all 3 prefabs!
cab_shd = {}
for ab_dir in ("14_effect", "15_shader", "03_prefabs"):
    for ab in sorted((CDN_ROOT / ab_dir).rglob("*.ab")):
        env = load_ab(ab)
        for sf_name, sf in env.files.items():
            subs = sf.files.items() if isinstance(getattr(sf, "files", None), dict) else [(sf_name, sf)]
            for k, sub in subs:
                if k.startswith("CAB-") and hasattr(sub, "objects"):
                    for pid, obj in sub.objects.items():
                        if obj.type.name in ("Material", "Shader"):
                            cab_shd[(k, pid)] = obj

def res(sf, fid, pid):
    if pid == 0: return None
    if fid == 0: return sf.objects.get(pid)
    if 1 <= fid <= len(sf.externals):
        return cab_shd.get((Path(sf.externals[fid-1].path).name, pid))
    return None

for rel, tid, lbl in [
    ("03_prefabs/ui.ab", 8268094511723853665, "idle"),
    ("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_chat.prefab", "chat"),
    ("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab", "touch1"),
]:
    print("===", lbl, "===")
    env = load_ab(CDN_ROOT / rel)
    obj = {o.path_id: o for o in env.objects}
    rid = tid if isinstance(tid, int) else {k.lower(): v.path_id for k,v in env.container.items()}[tid.lower()]
    def w(gid):
        go = obj[gid].read(); rt = None
        if not go.m_IsActive: return
        for c in go.m_Component:
            co = obj.get(c.component.path_id)
            if not co: continue
            if co.type.name in ("RectTransform", "Transform"): rt = co.read()
            elif co.type.name == "ParticleSystem":
                tt = co.read_typetree()
                if tt.get("EmissionModule", {}).get("enabled"):
                    shd_name = "?"; mat_name = "?"; src_b = dst_b = None
                    for c2 in go.m_Component:
                        co2 = obj.get(c2.component.path_id)
                        if co2 and co2.type.name == "ParticleSystemRenderer":
                            mref = co2.read_typetree().get("m_Materials", [{}])[0]
                            mobj = res(co2.assets_file, mref.get("m_FileID", 0), mref.get("m_PathID", 0))
                            if mobj:
                                mtt = mobj.read_typetree()
                                mat_name = mtt.get("m_Name")
                                sref = mtt.get("m_Shader", {})
                                sobj = res(mobj.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
                                if sobj:
                                    shd_name = sobj.read().m_ParsedForm.m_Name if hasattr(sobj.read(), "m_ParsedForm") else sobj.peek_name()
                                flts = {k: v for k, v in mtt.get("m_SavedProperties", {}).get("m_Floats", [])}
                                src_b, dst_b = flts.get("_SrcBlend"), flts.get("_DstBlend")
                    print(f"  {go.m_Name:15s} delay={tt.get('startDelay',{}).get('scalar',0):.2f}s dur={tt.get('lengthInSec'):.2f}s mat={mat_name} shader={shd_name} blend=({src_b},{dst_b})")
        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children: w(obj[ch.path_id].read().m_GameObject.path_id)
    w(rid)

# 2. Check Aurora touch1_marry / touch1 bone 113 & 321 keyframes in backup skel.json!
skel = json.loads(Path(r"E:\A灵魂潮汐\备份\spine\欧若拉\童话心绘\有背景\SoulDress_Aurora_04.skel.json").read_text("utf-8"))
for aname in ("touch1", "touch1_marry"):
    anim = skel["animations"].get(aname, {})
    print(f"=== {aname} bone events / slots / hand times ===")
    for sname, tracks in anim.get("slots", {}).items():
        if any(k in sname.lower() for k in ("beike", "xiang", "hua", "hand", "shou")):
            print("  slot", sname, list(tracks.keys()))
    print("  113 rot/trans times:", [k.get("time", 0) for k in anim.get("bones", {}).get("113", {}).get("rotate", [])])
    print("  321 rot/trans times:", [k.get("time", 0) for k in anim.get("bones", {}).get("321", {}).get("rotate", [])])
