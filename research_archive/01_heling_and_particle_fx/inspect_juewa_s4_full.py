import os, sys, json
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# Inspect fx_manifest for ALL clips of 1703_Juewa_S4 + ALL nodes in raw Juewa_S4_Background and chat/touch2
man = json.load(open(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json', 'r', encoding='utf-8'))
j4 = [j for j in man['skins'] if j['skin_key'] == '1703_Juewa_S4'][0]
print('=== fx_manifest 1703_Juewa_S4 ===')
for c in j4['clips']:
    print(f"clip={c['clip']} dur={c['duration']} warmup={c['warmup']} fps={c['fps']}")
    for n in c['nodes']:
        print(f"  node={n['name']} pos={[round(x,1) for x in n['world_pos']]} wscale={[round(x,2) for x in n['world_scale']]} "
              f"scaleMode={n['scalingMode']} loop={n['looping']} dur={n['duration']} delay={n['startDelay']} "
              f"lt=({n['lifetime']['minScalar']},{n['lifetime']['scalar']}) spd=({n['speed']['minScalar']},{n['speed']['scalar']}) "
              f"velX=({n['velX']},{n['velXCurve']}) velY=({n['velY']},{n['velYCurve']}) tex={n['texName']} mask={n['maskTexName']} "
              f"sort={n['sortOrder']} add={n['isAdditive']} bursts={n['bursts']} rate={n['rate']}")

# Inspect raw ParticleSystems in Juewa_S4_Background + chat + touch2
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
art_objs = {o.path_id: o for o in art_env.objects}

def dump_ps_all(objs, gid, path=''):
    go = objs[gid].read()
    cur = f"{path}/{go.m_Name}"
    rt = None
    for c_ref in go.m_Component:
        co = objs.get(c_ref.component.path_id)
        if not co: continue
        if co.type.name in ('Transform', 'RectTransform'):
            rt = co.read()
        elif co.type.name == 'ParticleSystem':
            d = co.read_typetree()
            em = d.get('EmissionModule', {})
            init = d.get('InitialModule', {})
            sub = d.get('SubModule', {})
            uv = d.get('UVModule', {})
            vel = d.get('VelocityModule', {})
            lp, ls = rt.m_LocalPosition, rt.m_LocalScale
            print(f"  [{go.m_IsActive}] {cur} lpos=({lp.x:.1f},{lp.y:.1f}) lscale=({ls.x:.3f},{ls.y:.3f}) "
                  f"emEn={em.get('enabled')} rate={em.get('rateOverTime',{}).get('scalar')} bursts={len(em.get('m_Bursts',[]))} "
                  f"loop={d.get('looping')} dur={d.get('lengthInSec')} lt={init.get('startLifetime',{}).get('scalar')} "
                  f"spd={init.get('startSpeed',{}).get('scalar')} sz={init.get('startSize',{}).get('scalar')} "
                  f"scaleMode={d.get('scalingMode')} velEn={vel.get('enabled')} subEn={sub.get('enabled')}")
            if sub.get('enabled'):
                print("    subEmitters:", sub.get('subEmitters'))
    if rt and hasattr(rt, 'm_Children'):
        for ch in rt.m_Children:
            if ch.path_id in objs:
                dump_ps_all(objs, objs[ch.path_id].read().m_GameObject.path_id, cur)

for o in ui_env.objects:
    if o.type.name == 'GameObject' and (o.peek_name() or '').lower() == 'juewa_s4_background':
        print("\n=== ALL ParticleSystems in ui.ab Juewa_S4_Background ===")
        dump_ps_all(ui_objs, o.path_id)
        break

for k, p in (art_env.container or {}).items():
    if 'juewa_s4_background_' in k.lower():
        print(f"\n=== ALL ParticleSystems in art_prefabs.ab {k} ===")
        dump_ps_all(art_objs, p.path_id)
EOF