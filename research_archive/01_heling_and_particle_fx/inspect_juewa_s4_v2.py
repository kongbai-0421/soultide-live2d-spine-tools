import os, sys, json, re
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

# 1. Inspect 1703_Juewa_S4 using bfe's exact prefab lookup
skins = bfe.discover_skins()
print('Total discovered skins in bfe:', len(skins))
j4 = [s for s in skins if '1703' in s['skin_key']][0]
print('1703 skin:', j4)
prefab_ab = sc.CDN_ROOT / j4['bg_ab']
print('prefab_ab:', prefab_ab, prefab_ab.exists())
env = sc.load_ab(prefab_ab)

def dump_go(go_ptr, indent=0):
    go = go_ptr.read()
    children = []
    rt_info = ''
    ps_info = ''
    anim_info = ''
    other_comps = []
    for c_ref in go.m_Component:
        c = c_ref.component.read()
        cname = c.type.name
        if cname in ('Transform', 'RectTransform'):
            lp = c.m_LocalPosition
            ls = c.m_LocalScale
            lr = c.m_LocalRotation
            rt_info = f'pos=({lp.x:.2f},{lp.y:.2f},{lp.z:.2f}) scale=({ls.x:.4f},{ls.y:.4f},{ls.z:.4f}) rot=({lr.x:.2f},{lr.y:.2f},{lr.z:.2f},{lr.w:.2f})'
            if cname == 'RectTransform':
                sd = c.m_SizeDelta
                ap = c.m_AnchoredPosition
                rt_info += f' anch=({ap.x:.1f},{ap.y:.1f}) size=({sd.x:.1f},{sd.y:.1f})'
            children = c.m_Children
        elif cname == 'ParticleSystem':
            d = c.read_typetree()
            main = d.get('InitialModule', {})
            vel = d.get('VelocityModule', {})
            sub = d.get('SubModule', {})
            col = d.get('ColorModule', {})
            sz = d.get('SizeModule', {})
            rot = d.get('RotationModule', {})
            lim = d.get('ClampVelocityModule', {})
            sh = d.get('ShapeModule', {})
            ps_info = (
                f"PS(loop={d.get('looping')}, dur={d.get('lengthInSec')}, delay={d.get('startDelay',{}).get('scalar')}, "
                f"moveWT={d.get('moveWithTransform')}, scaleMode={d.get('scalingMode')}, "
                f"lt={main.get('startLifetime',{}).get('scalar')}/{main.get('startLifetime',{}).get('minScalar')}, "
                f"spd={main.get('startSpeed',{}).get('scalar')}/{main.get('startSpeed',{}).get('minScalar')}, "
                f"sz={main.get('startSize',{}).get('scalar')}/{main.get('startSize',{}).get('minScalar')}, "
                f"simSpd={d.get('simulationSpeed')}, "
                f"shape={sh.get('type')} rad={sh.get('radius',{}).get('value')} box=({sh.get('boxThickness')},{sh.get('m_Scale')}), "
                f"velEn={vel.get('enabled')} X={vel.get('x',{}).get('scalar')}/{vel.get('x',{}).get('minScalar')} Y={vel.get('y',{}).get('scalar')}/{vel.get('y',{}).get('minScalar')}, "
                f"limEn={lim.get('enabled')}, colEn={col.get('enabled')}, szEn={sz.get('enabled')}, rotEn={rot.get('enabled')}, subEn={sub.get('enabled')})"
            )
            if sub.get('enabled'):
                ps_info += f" subEmitters={sub.get('subEmitters')}"
        elif cname in ('Animator', 'Animation'):
            d = c.read_typetree()
            anim_info = f"{cname}(ctrl={d.get('m_Controller')}, anim={d.get('m_Animation')}, anims={d.get('m_Animations')})"
        else:
            other_comps.append(cname)
    pad = '  ' * indent
    print(f"{pad}[{go.m_IsActive}] {go.m_Name} | {rt_info} | {other_comps}")
    if ps_info:
        print(f"{pad}  {ps_info}")
    if anim_info:
        print(f"{pad}  {anim_info}")
    for ch in children:
        t = ch.read()
        dump_go(t.m_GameObject, indent + 1)

for o in env.objects:
    if o.type.name == 'GameObject':
        go = o.read()
        for c_ref in go.m_Component:
            c = c_ref.component.read()
            if c.type.name in ('Transform', 'RectTransform') and c.m_Father.path_id == 0:
                dump_go(o)
                break

print("\n=== AnimationClips in juewa_s4_background ===")
for o in env.objects:
    if o.type.name == 'AnimationClip':
        c = o.read()
        d = o.read_typetree()
        print("Clip:", c.m_Name, "wrapMode:", d.get('m_WrapMode'), "sampleRate:", d.get('m_SampleRate'),
              "floatCurves:", len(d.get('m_FloatCurves', [])), "posCurves:", len(d.get('m_PositionCurves', [])),
              "scaleCurves:", len(d.get('m_ScaleCurves', [])), "rotCurves:", len(d.get('m_RotationCurves', [])))
        for fc in d.get('m_FloatCurves', [])[:12]:
            print("   float:", fc.get('path'), fc.get('attribute'), [(round(k.get('time',0),3), round(k.get('value',0),3)) for k in fc.get('curve', {}).get('m_Curve', [])[:8]])
        for pc in d.get('m_PositionCurves', [])[:8]:
            print("   pos:", pc.get('path'), [(round(k.get('time',0),3), k.get('value')) for k in pc.get('curve', {}).get('m_Curve', [])[:8]])
