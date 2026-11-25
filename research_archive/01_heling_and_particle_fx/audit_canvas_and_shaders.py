import json, sys, os
from pathlib import Path
from collections import Counter
import UnityPy
from PIL import Image

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Inspect UI Canvas / Camera setup in ui.ab / prefabs
print('=== 1. Search Canvas / Camera / UIRoot in 03_prefabs ===')
for ab_name in ['ui.ab', 'art_prefabs.ab']:
    ab_p = sc.CDN_ROOT / '03_prefabs' / ab_name
    if not ab_p.exists(): continue
    env = sc.load_ab(ab_p)
    objs = {o.path_id: o for o in env.objects}
    for o in env.objects:
        if o.type.name == 'GameObject':
            nm = (o.peek_name() or '')
            if any(k in nm.lower() for k in ('uiroot', 'canvas', 'uicamera', 'maincamera', 'homepanel', 'background')):
                if 'background' in nm.lower() and not any(k in nm.lower() for k in ('root', 'canvas', 'panel', 'view', 'window')):
                    continue
                go = o.read()
                comps = []
                for cr in go.m_Component:
                    co = objs.get(cr.component.path_id)
                    if not co: continue
                    if co.type.name == 'Camera':
                        ct = co.read_typetree()
                        comps.append(f'Camera(ortho={ct.get("orthographic")},orthoSize={ct.get("orthographic size")},fov={ct.get("field of view")})')
                    elif co.type.name == 'Canvas':
                        ct = co.read_typetree()
                        comps.append(f'Canvas(rm={ct.get("m_RenderMode")},planeDist={ct.get("m_PlaneDistance")})')
                    elif co.type.name == 'CanvasScaler':
                        ct = co.read_typetree()
                        comps.append(f'CanvasScaler(mode={ct.get("m_UiScaleMode")},refRes={ct.get("m_ReferenceResolution")},match={ct.get("m_MatchWidthOrHeight")})')
                    elif co.type.name in ('Transform', 'RectTransform'):
                        ct = co.read_typetree()
                        ls = ct.get('m_LocalScale', {})
                        comps.append(f'{co.type.name}(scale=({ls.get("x"):.5f},{ls.get("y"):.5f},{ls.get("z"):.5f}))')
                if any('Camera' in c or 'Canvas' in c for c in comps):
                    print(f'  [{ab_name}] {nm}: {comps}')

# Also inspect sub-prefab structure for Virgina_S3, Gawana_S2 (fx_9008107), Ennis_S3 (fx_9008124), QuLing_S2, Freesia_S5 (fx_9008161), QingDai_S2 (fx_9008143)
print('\n=== 2. Inspect ALL Materials & Shaders across ALL ABs ===')
man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))
needed_mats = {}
for sk in man['skins']:
    for c in sk['clips']:
        for n in c['nodes']:
            mn = n.get('matName', '')
            if mn:
                needed_mats.setdefault(mn, []).append((sk['skin_key'], c['clip'], n['name'], n.get('add'), n.get('texName'), n.get('maskTexName', '')))

ab_files = sorted(sc.CDN_ROOT.rglob('*.ab'))
print(f'Scanning {len(ab_files)} .ab files for {len(needed_mats)} materials...')
found_mats = {}
shader_names_by_pid = {}
for ab_p in ab_files:
    env = sc.load_ab(ab_p)
    objs = {o.path_id: o for o in env.objects}
    for o in env.objects:
        if o.type.name == 'Shader':
            shader_names_by_pid[(ab_p.name, o.path_id)] = o.peek_name() or ''
            try:
                st = o.read_typetree()
                pf = st.get('m_ParsedForm', {})
                if pf.get('m_Name'):
                    shader_names_by_pid[(ab_p.name, o.path_id)] = pf['m_Name']
            except Exception:
                pass
    for o in env.objects:
        if o.type.name == 'Material':
            nm = o.peek_name() or ''
            if nm in needed_mats and nm not in found_mats:
                mt = o.read_typetree()
                sp = mt.get('m_Shader', {})
                shn = ''
                if sp.get('m_FileID') == 0 and sp.get('m_PathID') in objs:
                    shn = objs[sp['m_PathID']].peek_name() or ''
                    if not shn:
                        try:
                            shn = objs[sp['m_PathID']].read_typetree().get('m_ParsedForm', {}).get('m_Name', '')
                        except Exception:
                            pass
                else:
                    shn = f'ext({sp.get("m_FileID")},{sp.get("m_PathID")})'
                saved = mt.get('m_SavedProperties', {})
                texs = {k: (v.get('m_Texture', {}).get('m_PathID', 0), round(v.get('m_Scale',{}).get('x',1),2), round(v.get('m_Scale',{}).get('y',1),2)) for k, v in saved.get('m_TexEnvs', [])}
                flts = {k: round(v, 3) for k, v in saved.get('m_Floats', [])}
                cols = {k: [round(v[c], 3) for c in ('r','g','b','a')] for k, v in saved.get('m_Colors', [])}
                found_mats[nm] = (ab_p.name, shn, mt.get('m_ShaderKeywords', ''), texs, flts, cols)

print(f'Resolved {len(found_mats)} / {len(needed_mats)} materials!')
# Print all distinct shaders (by keywords/shader name/floats pattern)
sh_counter = Counter((v[1], v[2]) for v in found_mats.values())
print('Top shader+keywords combos:')
for k, cnt in sh_counter.most_common(40):
    print(f'  {cnt:4d}: {k}')

# Specific checks on Virgina_S3, Ennis_S3, Gawana_S2, Benten_S4, QuLing_S2, Aurora_S5
print('\n=== 3. Specific Suspect Materials ===')
for mn, users in needed_mats.items():
    if any(u[0] in ('1202_Virgina_S3', '2002_Ennis_S3', '1601_Gawana_S2', '503_Benten_S4', '2301_QuLing_S2', '1903_Aurora_S5', '402_Freesia_S5', '3501_QingDai_S2') for u in users):
        print(f'  {mn} -> {found_mats.get(mn)} | users={users[:3]}')
