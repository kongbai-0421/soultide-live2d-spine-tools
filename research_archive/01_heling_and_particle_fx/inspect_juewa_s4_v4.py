import os, sys, json
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Inspect fx_manifest.json for 1703_Juewa_S4 + overall anomaly summary
man_p = r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json'
with open(man_p, 'r', encoding='utf-8') as f:
    man = json.load(f)
print('fx_manifest keys:', list(man.keys()) if isinstance(man, dict) else type(man))
jobs = man.get('skins', man.get('jobs', [])) if isinstance(man, dict) else man
print('fx_manifest total skins:', len(jobs))
j4 = [j for j in jobs if '1703_Juewa_S4' in j.get('skin_key', '')][0]
print('1703_Juewa_S4 job:')
print(json.dumps(j4, ensure_ascii=False, indent=2)[:4000])

# Scan all jobs for potential speed/scale/stutter/position issues
non_loop_idle = 0
scale_mode_1 = 0
big_eff_scale = []
long_lt_idle = []
sub_emitters = 0
for j in jobs:
    for c in j.get('clips', []):
        for n in c.get('nodes', []):
            sm = n.get('scalingMode', -1)
            es = n.get('world_scale', [1, 1, 1])
            if sm == 1:
                scale_mode_1 += 1
            if max(abs(x) for x in es) > 10:
                big_eff_scale.append((j['skin_key'], c['clip'], n['name'], sm, [round(x,2) for x in es], n.get('speed',{}).get('scalar'), (n.get('velX'), n.get('velY'))))
            if c.get('is_idle') and not n.get('looping'):
                non_loop_idle += 1
            if c.get('is_idle'):
                lt = max(n.get('lifetime',{}).get('scalar',0), n.get('lifetime',{}).get('minScalar',0))
                if lt > 2.5:
                    long_lt_idle.append((j['skin_key'], n['name'], lt, n.get('duration'), n.get('looping')))
print(f"Summary across {len(jobs)} jobs: scaleMode==1 nodes={scale_mode_1}, non_loop_idle={non_loop_idle}, long_lt_idle(>2.5s)={len(long_lt_idle)}, big_eff_scale(>10)={len(big_eff_scale)}")
for x in big_eff_scale[:15]:
    print('  big_scale:', x)
for x in long_lt_idle[:15]:
    print('  long_lt_idle:', x)

# 2. Inspect raw Unity tree of Juewa_S4_Background in ui.ab and FX_UI in art_prefabs.ab
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
art_objs = {o.path_id: o for o in art_env.objects}

def dump_tree(objs, gid, indent=0):
    go = objs[gid].read()
    rt = None
    ps = ''
    an = ''
    comps = []
    for c_ref in go.m_Component:
        co = objs.get(c_ref.component.path_id)
        if not co: continue
        cn = co.type.name
        if cn in ('Transform', 'RectTransform'):
            rt = co.read()
            lp, ls, lr = rt.m_LocalPosition, rt.m_LocalScale, rt.m_LocalRotation
            tf_s = f"pos=({lp.x:.2f},{lp.y:.2f},{lp.z:.2f}) scale=({ls.x:.4f},{ls.y:.4f},{ls.z:.4f}) rot=({lr.x:.2f},{lr.y:.2f},{lr.z:.2f},{lr.w:.2f})"
            if cn == 'RectTransform':
                sd, ap = rt.m_SizeDelta, rt.m_AnchoredPosition
                tf_s += f" anch=({ap.x:.1f},{ap.y:.1f}) size=({sd.x:.1f},{sd.y:.1f})"
        elif cn == 'ParticleSystem':
            d = co.read_typetree()
            init = d.get('InitialModule', {})
            vel = d.get('VelocityModule', {})
            sub = d.get('SubModule', {})
            col = d.get('ColorModule', {})
            sz = d.get('SizeModule', {})
            rot = d.get('RotationModule', {})
            uv = d.get('UVModule', {})
            sh = d.get('ShapeModule', {})
            noise = d.get('NoiseModule', {})
            force = d.get('ForceModule', {})
            ps = (f"PS(loop={d.get('looping')}, dur={d.get('lengthInSec')}, delay={d.get('startDelay',{}).get('scalar')}, "
                  f"simSpd={d.get('simulationSpeed')}, moveWT={d.get('moveWithTransform')}, scaleMode={d.get('scalingMode')}, "
                  f"lt={init.get('startLifetime',{}).get('scalar')}/{init.get('startLifetime',{}).get('minScalar')}, "
                  f"spd={init.get('startSpeed',{}).get('scalar')}/{init.get('startSpeed',{}).get('minScalar')}, "
                  f"sz={init.get('startSize',{}).get('scalar')}/{init.get('startSize',{}).get('minScalar')}, "
                  f"shape={sh.get('type')} rad={sh.get('radius',{}).get('value')}, "
                  f"velEn={vel.get('enabled')} X={vel.get('x',{}).get('scalar')}/{vel.get('x',{}).get('minScalar')} Y={vel.get('y',{}).get('scalar')}/{vel.get('y',{}).get('minScalar')} inWorld={vel.get('inWorldSpace')}, "
                  f"col={col.get('enabled')} sz={sz.get('enabled')} rot={rot.get('enabled')} uv={uv.get('enabled')} noise={noise.get('enabled')} force={force.get('enabled')} sub={sub.get('enabled')})")
            if sub.get('enabled'):
                ps += f" subEmitters={sub.get('subEmitters')}"
        elif cn in ('Animator', 'Animation'):
            d = co.read_typetree()
            an = f"{cn}(ctrl={d.get('m_Controller')}, anim={d.get('m_Animation')})"
        else:
            comps.append(cn)
    print(f"{'  '*indent}[{go.m_IsActive}] {go.m_Name} | {tf_s} | {comps}")
    if ps: print(f"{'  '*indent}  {ps}")
    if an: print(f"{'  '*indent}  {an}")
    if rt and hasattr(rt, 'm_Children'):
        for ch in rt.m_Children:
            if ch.path_id in objs:
                dump_tree(objs, objs[ch.path_id].read().m_GameObject.path_id, indent + 1)

for o in ui_env.objects:
    if o.type.name == 'GameObject' and (o.peek_name() or '').lower() == 'juewa_s4_background':
        print("\n=== ui.ab :: Juewa_S4_Background ===")
        dump_tree(ui_objs, o.path_id)
        break

for k, p in (art_env.container or {}).items():
    if 'juewa_s4' in k.lower():
        print(f"\n=== art_prefabs.ab :: {k} ===")
        o = art_objs.get(p.path_id)
        if o and o.type.name == 'GameObject':
            dump_tree(art_objs, p.path_id)
EOF