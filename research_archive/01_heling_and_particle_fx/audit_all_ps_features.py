import os, sys, json
from pathlib import Path
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

repo = bfe.FullI18nRepo()
skins = bfe.build_skin_catalog(repo)
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
art_objs = {o.path_id: o for o in art_env.objects}
ui_go = {o.peek_name().lower(): o.path_id for o in ui_env.objects if o.type.name == 'GameObject' and o.peek_name()}
art_go = {o.peek_name().lower(): o.path_id for o in art_env.objects if o.type.name == 'GameObject' and o.peek_name()}
art_c = {k.lower(): v.path_id for k, v in (art_env.container or {}).items()}

# Audit EVERY ParticleSystem across all 101 FX skins for unexported/mis-exported Unity features:
counts = {
    'simSpeed_neq_1': [],
    'vel_inWorldSpace': [],
    'vel_orbital_radial_speedMod': [],
    'limit_vel_enabled': [],
    'inherit_vel_enabled': [],
    'sizeBySpeed_enabled': [],
    'colBySpeed_enabled': [],
    'shape_angle_neq_25': 0,
    'shape_types': {},
    'scaling_modes': {},
    'sim_spaces': {},
    'burst_cycle_infinite_or_gt1': [],
    'col_module_mode2_or_3': 0,
    'size_module_separateAxes': [],
    'sub_module_details': [],
}

def audit_tree(skin_key, clip_tag, objs, gid):
    def walk(g_id):
        go = objs[g_id].read()
        if not go.m_IsActive or 'harmonious' in go.m_Name.lower(): return
        rt = None
        for cr in go.m_Component:
            co = objs.get(cr.component.path_id)
            if not co: continue
            if co.type.name in ('Transform', 'RectTransform'): rt = co.read()
            elif co.type.name == 'ParticleSystem':
                tt = co.read_typetree()
                em = tt.get('EmissionModule', {})
                if not em.get('enabled'): continue
                sim_spd = float(tt.get('simulationSpeed', 1.0))
                if abs(sim_spd - 1.0) > 1e-3:
                    counts['simSpeed_neq_1'].append((skin_key, clip_tag, go.m_Name, round(sim_spd, 3)))
                sm = int(tt.get('scalingMode', 0))
                counts['scaling_modes'][sm] = counts['scaling_modes'].get(sm, 0) + 1
                sp = int(tt.get('moveWithTransform', 0))
                counts['sim_spaces'][sp] = counts['sim_spaces'].get(sp, 0) + 1
                vel = tt.get('VelocityModule', {})
                if vel.get('enabled'):
                    if vel.get('inWorldSpace'):
                        counts['vel_inWorldSpace'].append((skin_key, clip_tag, go.m_Name))
                    for fk in ('orbitalX', 'orbitalY', 'orbitalZ', 'radial'):
                        c = vel.get(fk, {})
                        if abs(float(c.get('scalar', 0))) > 1e-4 or abs(float(c.get('minScalar', 0))) > 1e-4:
                            counts['vel_orbital_radial_speedMod'].append((skin_key, clip_tag, go.m_Name, fk, c.get('scalar')))
                    sm_v = vel.get('speedModifier', {})
                    if sm_v and abs(float(sm_v.get('scalar', 1.0)) - 1.0) > 1e-4:
                        counts['vel_orbital_radial_speedMod'].append((skin_key, clip_tag, go.m_Name, 'speedModifier', sm_v.get('scalar')))
                if tt.get('ClampVelocityModule', {}).get('enabled'):
                    counts['limit_vel_enabled'].append((skin_key, clip_tag, go.m_Name, tt['ClampVelocityModule'].get('dampen')))
                if tt.get('InheritVelocityModule', {}).get('enabled'):
                    counts['inherit_vel_enabled'].append((skin_key, clip_tag, go.m_Name))
                if tt.get('SizeBySpeedModule', {}).get('enabled'):
                    counts['sizeBySpeed_enabled'].append((skin_key, clip_tag, go.m_Name))
                if tt.get('ColorBySpeedModule', {}).get('enabled'):
                    counts['colBySpeed_enabled'].append((skin_key, clip_tag, go.m_Name))
                sh = tt.get('ShapeModule', {})
                if sh.get('enabled'):
                    st = int(sh.get('type', 0))
                    counts['shape_types'][st] = counts['shape_types'].get(st, 0) + 1
                szm = tt.get('SizeModule', {})
                if szm.get('enabled') and szm.get('separateAxes'):
                    counts['size_module_separateAxes'].append((skin_key, clip_tag, go.m_Name))
                for b in em.get('m_Bursts', []):
                    if b.get('cycleCount', 1) != 1:
                        counts['burst_cycle_infinite_or_gt1'].append((skin_key, clip_tag, go.m_Name, b.get('cycleCount'), b.get('repeatInterval')))
                sub = tt.get('SubModule', {})
                if sub.get('enabled'):
                    counts['sub_module_details'].append((skin_key, clip_tag, go.m_Name, sub.get('subEmitters')))
        if rt and hasattr(rt, 'm_Children'):
            for ch in rt.m_Children:
                if ch.path_id in objs:
                    walk(objs[ch.path_id].read().m_GameObject.path_id)
    walk(gid)

for sk in skins:
    bgp = Path(sk['bg_prefab']).name.lower()
    if bgp in ui_go: audit_tree(sk['skin_key'], 'idle', ui_objs, ui_go[bgp])
    elif bgp in art_go: audit_tree(sk['skin_key'], 'idle', art_objs, art_go[bgp])
    for eid, pf in sk['effect_prefabs'].items():
        ck = f"assets/03_prefabs/art_prefabs/effect/{pf.lower()}.prefab"
        gid = art_c.get(ck) or art_go.get(Path(pf).name.lower())
        if gid: audit_tree(sk['skin_key'], f'fx_{eid}', art_objs, gid)

print("simSpeed != 1:", len(counts['simSpeed_neq_1']), counts['simSpeed_neq_1'][:20])
print("vel inWorldSpace:", len(counts['vel_inWorldSpace']), counts['vel_inWorldSpace'][:15])
print("vel orbital/radial/speedMod:", len(counts['vel_orbital_radial_speedMod']), counts['vel_orbital_radial_speedMod'][:20])
print("limit_vel_enabled:", len(counts['limit_vel_enabled']), counts['limit_vel_enabled'][:15])
print("inherit_vel_enabled:", len(counts['inherit_vel_enabled']), counts['inherit_vel_enabled'][:10])
print("sizeBySpeed:", len(counts['sizeBySpeed_enabled']), counts['sizeBySpeed_enabled'][:10])
print("colBySpeed:", len(counts['colBySpeed_enabled']), counts['colBySpeed_enabled'][:10])
print("size_module_separateAxes:", len(counts['size_module_separateAxes']), counts['size_module_separateAxes'][:10])
print("burst cycle != 1:", len(counts['burst_cycle_infinite_or_gt1']), counts['burst_cycle_infinite_or_gt1'][:15])
print("scaling_modes:", counts['scaling_modes'])
print("sim_spaces (0=Local,1=World,2=Custom):", counts['sim_spaces'])
print("shape_types:", counts['shape_types'])
print("sub_module_details count:", len(counts['sub_module_details']))
EOF