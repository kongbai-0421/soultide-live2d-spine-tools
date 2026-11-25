import os, sys, json
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

# 1. Check how many of the 101 FX skins actually have SubModule or Animator/Animation on BgPrefab or EffectId prefabs
repo = bfe.FullI18nRepo()
skins = bfe.build_skin_catalog(repo)
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
art_objs = {o.path_id: o for o in art_env.objects}
ui_go_by_name = {}
for o in ui_env.objects:
    if o.type.name == 'GameObject' and o.peek_name():
        ui_go_by_name.setdefault(o.peek_name().lower(), o.path_id)
art_go_by_name = {}
for o in art_env.objects:
    if o.type.name == 'GameObject' and o.peek_name():
        art_go_by_name.setdefault(o.peek_name().lower(), o.path_id)
art_c = {k.lower(): v.path_id for k, v in (art_env.container or {}).items()}

def check_tree(objs, gid):
    res = {'submodules': [], 'animators': [], 'inactive_ps': [], 'ps_loop_false_em': []}
    def walk(g_id):
        go = objs[g_id].read()
        if not go.m_IsActive or 'harmonious' in go.m_Name.lower():
            return
        rt = None
        for cr in go.m_Component:
            co = objs.get(cr.component.path_id)
            if not co: continue
            if co.type.name in ('Transform', 'RectTransform'): rt = co.read()
            elif co.type.name == 'ParticleSystem':
                tt = co.read_typetree()
                em = tt.get('EmissionModule', {})
                sub = tt.get('SubModule', {})
                if sub.get('enabled'):
                    res['submodules'].append(go.m_Name)
                if em.get('enabled') and not tt.get('looping'):
                    res['ps_loop_false_em'].append((go.m_Name, round(tt.get('lengthInSec',0),2), round(tt.get('InitialModule',{}).get('startLifetime',{}).get('scalar',0),2)))
            elif co.type.name in ('Animator', 'Animation'):
                d = co.read_typetree()
                has_ctrl = (d.get('m_Controller', {}).get('m_PathID', 0) != 0) or (d.get('m_Animation', {}).get('m_PathID', 0) != 0) or bool(d.get('m_Animations'))
                if has_ctrl:
                    res['animators'].append((go.m_Name, co.type.name))
        if rt and hasattr(rt, 'm_Children'):
            for ch in rt.m_Children:
                if ch.path_id in objs:
                    walk(objs[ch.path_id].read().m_GameObject.path_id)
    walk(gid)
    return res

sub_skins, anim_skins, idle_nf_skins = [], [], []
for sk in skins:
    bgp = os.path.basename(sk['bg_prefab']).lower()
    if bgp in ui_go_by_name:
        r = check_tree(ui_objs, ui_go_by_name[bgp])
    elif bgp in art_go_by_name:
        r = check_tree(art_objs, art_go_by_name[bgp])
    else:
        r = {'submodules': [], 'animators': [], 'ps_loop_false_em': []}
    if r['submodules']: sub_skins.append((sk['skin_key'], 'bg', r['submodules']))
    if r['animators']: anim_skins.append((sk['skin_key'], 'bg', r['animators']))
    if r['ps_loop_false_em']: idle_nf_skins.append((sk['skin_key'], r['ps_loop_false_em']))
    for eid, pf in sk['effect_prefabs'].items():
        ck = f"assets/03_prefabs/art_prefabs/effect/{pf.lower()}.prefab"
        gid = art_c.get(ck) or art_go_by_name.get(os.path.basename(pf).lower())
        if gid:
            r2 = check_tree(art_objs, gid)
            if r2['submodules']: sub_skins.append((sk['skin_key'], f'fx_{eid}', r2['submodules']))
            if r2['animators']: anim_skins.append((sk['skin_key'], f'fx_{eid}', r2['animators']))

print(f"Skins with SubModule: {len(sub_skins)} -> {sub_skins}")
print(f"Skins with Animator/Animation: {len(anim_skins)} -> {anim_skins}")
print(f"Skins with non-looping idle PS: {len(idle_nf_skins)}")
for x in idle_nf_skins[:15]:
    print(' ', x)

# 2. Check Point_Root + Virgina_S3 + Freesia_S5 + Colcher_S2 effect coordinates vs SoulTide Lua
for target_key in ['1202_Virgina_S3', '402_Freesia_S5', '101_Colcher_S2', '1703_Juewa_S4', '1903_Aurora_S4']:
    sk = [s for s in skins if s['skin_key'] == target_key]
    if not sk: continue
    sk = sk[0]
    bgp = os.path.basename(sk['bg_prefab']).lower()
    objs, gid = (ui_objs, ui_go_by_name[bgp]) if bgp in ui_go_by_name else (art_objs, art_go_by_name[bgp])
    print(f"\n=== Point_Root check for {target_key} ===")
    for eid, pf in sk['effect_prefabs'].items():
        ck = f"assets/03_prefabs/art_prefabs/effect/{pf.lower()}.prefab"
        egid = art_c.get(ck) or art_go_by_name.get(os.path.basename(pf).lower())
        if egid:
            ego = art_objs[egid].read()
            # print root and direct PS children local positions
            ert = [art_objs[c.component.path_id].read() for c in ego.m_Component if c.component.path_id in art_objs and art_objs[c.component.path_id].type.name in ('Transform','RectTransform')][0]
            print(f"  fx_{eid} ({pf}) root pos=({ert.m_LocalPosition.x:.1f},{ert.m_LocalPosition.y:.1f}) scale=({ert.m_LocalScale.x:.3f},{ert.m_LocalScale.y:.3f})")
            for ch in getattr(ert, 'm_Children', []):
                cgo = art_objs[art_objs[ch.path_id].read().m_GameObject.path_id].read()
                crt = art_objs[ch.path_id].read()
                print(f"    child {cgo.m_Name}: lpos=({crt.m_LocalPosition.x:.1f},{crt.m_LocalPosition.y:.1f}) lscale=({crt.m_LocalScale.x:.3f},{crt.m_LocalScale.y:.3f})")
                for ch2 in getattr(crt, 'm_Children', []):
                    cgo2 = art_objs[art_objs[ch2.path_id].read().m_GameObject.path_id].read()
                    crt2 = art_objs[ch2.path_id].read()
                    print(f"      grandchild {cgo2.m_Name}: lpos=({crt2.m_LocalPosition.x:.1f},{crt2.m_LocalPosition.y:.1f}) lscale=({crt2.m_LocalScale.x:.3f},{crt2.m_LocalScale.y:.3f})")
EOF