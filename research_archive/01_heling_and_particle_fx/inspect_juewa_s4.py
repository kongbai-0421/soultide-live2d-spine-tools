import os, json, sys
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Inspect fx_juewa_s4.json animations
fx_dir = r'E:\A灵魂潮汐\Live2D与Spine模型\spine\九华\宇宙恋曲\submodels\fx_juewa_s4'
with open(os.path.join(fx_dir, 'fx_juewa_s4.json'), 'r', encoding='utf-8') as f:
    fj = json.load(f)
for an, ad in fj.get('animations', {}).items():
    mt = 0.0
    for sdict in ad.get('slots', {}).values():
        for tl in sdict.values():
            if tl:
                mt = max(mt, tl[-1].get('time', 0))
    print('fx anim:', an, 'slots=', len(ad.get('slots', {})), 'max_t=', mt)

# 2. Check Juewa_S4_Background.prefab FULL Unity tree
ab_p = sc.CDN_ROOT / '03_prefabs' / 'ui' / 'maincity_background' / 'juewa_s4_background.ab'
env = sc.load_ab(ab_p)

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
            ps_info = (
                f"PS(loop={d.get('looping')}, dur={d.get('lengthInSec')}, delay={d.get('startDelay',{}).get('scalar')}, "
                f"moveWT={d.get('moveWithTransform')}, scaleMode={d.get('scalingMode')}, "
                f"lt={main.get('startLifetime',{}).get('scalar')}/{main.get('startLifetime',{}).get('minScalar')}, "
                f"spd={main.get('startSpeed',{}).get('scalar')}/{main.get('startSpeed',{}).get('minScalar')}, "
                f"sz={main.get('startSize',{}).get('scalar')}/{main.get('startSize',{}).get('minScalar')}, "
                f"simSpd={d.get('simulationSpeed')}, "
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

print("\n=== AnimationClips in juewa_s4_background.ab ===")
for o in env.objects:
    if o.type.name == 'AnimationClip':
        c = o.read()
        print("Clip:", c.m_Name, "len:", c.m_MuscleClip.m_StopTime if hasattr(c, 'm_MuscleClip') else '?')
        d = o.read_typetree()
        print("  keys:", [k for k in d.keys()], "wrapMode:", d.get('m_WrapMode'), "sampleRate:", d.get('m_SampleRate'))
        print("  floatCurves:", len(d.get('m_FloatCurves', [])), "positionCurves:", len(d.get('m_PositionCurves', [])), "scaleCurves:", len(d.get('m_ScaleCurves', [])), "rotCurves:", len(d.get('m_RotationCurves', [])))
        for fc in d.get('m_FloatCurves', [])[:15]:
            print("    float:", fc.get('path'), fc.get('attribute'), [(k.get('time'), k.get('value')) for k in fc.get('curve', {}).get('m_Curve', [])[:6]])
        for pc in d.get('m_PositionCurves', [])[:10]:
            print("    pos:", pc.get('path'), [(k.get('time'), k.get('value')) for k in pc.get('curve', {}).get('m_Curve', [])[:6]])
EOF