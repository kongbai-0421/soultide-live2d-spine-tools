import json, os, sys
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

man = json.load(open(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json', 'r', encoding='utf-8'))
skins = man['skins']

# 1. Check ParticleSystem flags in fx_manifest across all 101 skins
stats = {
    'total_skins': len(skins),
    'idle_clips': 0,
    'fx_clips': 0,
    'idle_non_loop_nodes': 0,
    'idle_lt_gt_2': 0,
    'scale_mode_1': 0,
    'scale_mode_2': 0,
    'has_rot_OverLife': 0,
    'has_noise': 0,
    'has_force': 0,
    'has_uv': 0,
    'fx_with_neg_pos_or_huge': [],
}
for sk in skins:
    for c in sk['clips']:
        is_idle = (c['clip'] == 'idle')
        if is_idle: stats['idle_clips'] += 1
        else: stats['fx_clips'] += 1
        for n in c['nodes']:
            if is_idle and not n['looping']:
                stats['idle_non_loop_nodes'] += 1
            lt = max(n['lifetime']['scalar'], n['lifetime']['minScalar'])
            if is_idle and lt > 2.0:
                stats['idle_lt_gt_2'] += 1
            if n['scalingMode'] == 1: stats['scale_mode_1'] += 1
            elif n['scalingMode'] == 2: stats['scale_mode_2'] += 1
            if n.get('rotOverLifeCurve'): stats['has_rot_OverLife'] += 1
            if n.get('noiseEnabled'): stats['has_noise'] += 1
            if n.get('forceEnabled'): stats['has_force'] += 1
            if n.get('uvTiles'): stats['has_uv'] += 1
            wx, wy = n['world_pos'][0], n['world_pos'][1]
            if abs(wx) > 1100 or abs(wy) > 800:
                stats['fx_with_neg_pos_or_huge'].append((sk['skin_key'], c['clip'], n['name'], round(wx,1), round(wy,1)))
print('Manifest stats:', json.dumps({k: v for k, v in stats.items() if k != 'fx_with_neg_pos_or_huge'}, indent=2))
print('Out-of-bounds world_pos count:', len(stats['fx_with_neg_pos_or_huge']))
for x in stats['fx_with_neg_pos_or_huge'][:20]:
    print('  oob:', x)

# 2. Scan raw art_prefabs FX_UI/*.prefab local positions vs ui.ab backgrounds (Point_Root vs (0,0))
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_objs = {o.path_id: o for o in art_env.objects}
fx_ui = [(k, p.path_id) for k, p in (art_env.container or {}).items() if '/effect/fx_ui/' in k.lower() and k.endswith('.prefab')]
print(f"\nTotal FX_UI prefabs in art_prefabs.ab: {len(fx_ui)}")
sub_em_count = 0
anim_count = 0
for k, pid in sorted(fx_ui):
    go = art_objs[pid].read()
    rt = None
    has_anim = False
    for cr in go.m_Component:
        co = art_objs.get(cr.component.path_id)
        if not co: continue
        if co.type.name in ('Transform', 'RectTransform'): rt = co.read()
        if co.type.name in ('Animator', 'Animation'): has_anim = True
    # scan children for subEmitters / Animator / scalingMode
    def scan(gid):
        global sub_em_count, anim_count
        g = art_objs[gid].read()
        r = None
        for cr in g.m_Component:
            co = art_objs.get(cr.component.path_id)
            if not co: continue
            if co.type.name in ('Transform', 'RectTransform'): r = co.read()
            elif co.type.name == 'ParticleSystem':
                tt = co.read_typetree()
                if tt.get('SubModule', {}).get('enabled'):
                    sub_em_count += 1
                    print('  SubModule in FX_UI:', k, g.m_Name)
            elif co.type.name in ('Animator', 'Animation'):
                anim_count += 1
                print('  Animator/Animation in FX_UI:', k, g.m_Name)
        if r and hasattr(r, 'm_Children'):
            for ch in r.m_Children:
                if ch.path_id in art_objs:
                    scan(art_objs[ch.path_id].read().m_GameObject.path_id)
    scan(pid)
print(f"FX_UI SubModule={sub_em_count}, Animator/Anim={anim_count}")
EOF