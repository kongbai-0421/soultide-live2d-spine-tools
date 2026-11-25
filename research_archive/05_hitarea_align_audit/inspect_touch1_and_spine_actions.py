import sys, re, json
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, LuaTableRepo, load_ab

repo = LuaTableRepo()
print("=== ALL 13 Spine actions 192001..192013 ===")
for aid in range(192001, 192014):
    body = repo.spine_actions[aid]
    cv_id = int(re.search(r"CV\s*=\s*(\d+)", body).group(1))
    st = re.search(r'SoulActionState\s*=\s*"([^"]+)"', body).group(1)
    mst = re.search(r'MarryActionState\s*=\s*"([^"]+)"', body).group(1)
    eff = re.search(r"EffectId\s*=\s*(\d+)", body)
    meff = re.search(r"MarryEffectId\s*=\s*(\d+)", body)
    ed = re.search(r"EffectDelay\s*=\s*([\d.]+)", body)
    med = re.search(r"MarryEffectDelay\s*=\s*([\d.]+)", body)
    cv = repo.resolve_cv(cv_id)
    print(f"  {aid}: st={st:10s} mst={mst:14s} eff={eff.group(1) if eff else '-':7s}(d={ed.group(1) if ed else '-'}) meff={meff.group(1) if meff else '-':7s}(d={med.group(1) if med else '-'}) txt={cv['text']}")

print("\n=== Full raw ParticleSystem dump of aurora_s4_background_touch1.prefab ===")
env = load_ab(CDN_ROOT / "03_prefabs/art_prefabs.ab")
obj = {o.path_id: o for o in env.objects}
rid = {k.lower(): v.path_id for k, v in env.container.items()}["assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab"]

def w(gid, ind=0):
    go = obj[gid].read()
    rt = None
    pos = sc = rot = None
    for c in go.m_Component:
        co = obj.get(c.component.path_id)
        if not co: continue
        if co.type.name in ("RectTransform", "Transform"):
            rt = co.read()
            pos = (rt.m_LocalPosition.x, rt.m_LocalPosition.y, rt.m_LocalPosition.z)
            sc = (rt.m_LocalScale.x, rt.m_LocalScale.y, rt.m_LocalScale.z)
            rot = (rt.m_LocalRotation.x, rt.m_LocalRotation.y, rt.m_LocalRotation.z, rt.m_LocalRotation.w)
        elif co.type.name == "ParticleSystem":
            tt = co.read_typetree()
            init = tt.get("InitialModule", {})
            em = tt.get("EmissionModule", {})
            uv = tt.get("UVModule", {})
            sz = tt.get("SizeModule", {})
            col = tt.get("ColorModule", {})
            vel = tt.get("VelocityModule", {})
            rotm = tt.get("RotationModule", {})
            print("  "*ind + f"[{go.m_Name}] act={go.m_IsActive} pos={pos} sc={sc} rot={rot}")
            print("  "*ind + f"  dur={tt.get('lengthInSec')} loop={tt.get('looping')} delay={tt.get('startDelay')} scaling={tt.get('scalingMode')} simSpace={tt.get('moveWithTransform')}")
            print("  "*ind + f"  init: life={init.get('startLifetime',{}).get('minMaxState')}:{init.get('startLifetime',{}).get('scalar')}/{init.get('startLifetime',{}).get('minScalar')} spd={init.get('startSpeed',{}).get('minMaxState')}:{init.get('startSpeed',{}).get('scalar')}/{init.get('startSpeed',{}).get('minScalar')} size={init.get('startSize',{}).get('minMaxState')}:{init.get('startSize',{}).get('scalar')}/{init.get('startSize',{}).get('minScalar')} rotZ={init.get('startRotation',{}).get('minMaxState')}:{init.get('startRotation',{}).get('scalar')}/{init.get('startRotation',{}).get('minScalar')} grav={init.get('gravityModifier',{}).get('scalar')}")
            if sz.get("enabled"):
                print("  "*ind + f"  sizeOverLife: {[(round(k['time'],2), round(k['value'],2)) for k in sz.get('curve',{}).get('maxCurve',{}).get('m_Curve',[])]}")
            if col.get("enabled"):
                mg = col.get("gradient",{}).get("maxGradient",{})
                print("  "*ind + f"  colOverLife: ak={[(mg.get(f'atime{i}',0)/65535.0, round(mg.get(f'key{i}',{}).get('a',1),2)) for i in range(mg.get('m_NumAlphaKeys',0))]} ck={[(mg.get(f'ctime{i}',0)/65535.0, round(mg.get(f'key{i}',{}).get('r',1),2), round(mg.get(f'key{i}',{}).get('g',1),2), round(mg.get(f'key{i}',{}).get('b',1),2)) for i in range(mg.get('m_NumColorKeys',0))]}")
            if uv.get("enabled"):
                print("  "*ind + f"  UV: mode={uv.get('mode')} anim={uv.get('animationType')} rowMode={uv.get('rowMode')} rowIdx={uv.get('rowIndex')} tiles=({uv.get('tilesX')},{uv.get('tilesY')}) cycles={uv.get('cycles')} frameOverTime={uv.get('frameOverTime')} startFrame={uv.get('startFrame')}")
            if vel.get("enabled"):
                print("  "*ind + f"  Vel: x={vel.get('x',{}).get('scalar')} y={vel.get('y',{}).get('scalar')} z={vel.get('z',{}).get('scalar')}")
            if rotm.get("enabled"):
                print("  "*ind + f"  Rot: curve={rotm.get('curve',{}).get('scalar')}")
    if rt and hasattr(rt, "m_Children"):
        for ch in rt.m_Children: w(obj[ch.path_id].read().m_GameObject.path_id, ind+1)
w(rid)
