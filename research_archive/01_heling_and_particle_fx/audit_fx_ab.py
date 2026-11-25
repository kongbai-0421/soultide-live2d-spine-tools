import json, sys, os
from pathlib import Path
from collections import Counter
from PIL import Image

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))
tex_dir = Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures')

ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
art_objs = {o.path_id: o for o in art_env.objects}

def resolve_name(objs, ptr):
    if not ptr: return None
    fid = ptr.get('m_FileID', 0)
    pid = ptr.get('m_PathID', 0)
    if fid == 0 and pid in objs:
        return objs[pid].peek_name()
    return f'ext({fid},{pid})'

def dump_ps_tree(env, objs, name_sub):
    for o in env.objects:
        if o.type.name == 'GameObject' and (o.peek_name() or '').lower() == name_sub.lower():
            root = o.peek_name()
            print(f'*** Prefab [{root}]')
            stack = [(o.path_id, root, 0)]
            seen = set()
            while stack:
                gid, path, depth = stack.pop(0)
                if gid in seen or gid not in objs: continue
                seen.add(gid)
                go = objs[gid].read()
                tr = ps = psr = None
                for cr in go.m_Component:
                    co = objs.get(cr.component.path_id)
                    if not co: continue
                    if co.type.name in ('Transform', 'RectTransform'): tr = co
                    elif co.type.name == 'ParticleSystem': ps = co
                    elif co.type.name == 'ParticleSystemRenderer': psr = co
                trt = tr.read_typetree() if tr else {}
                ls = trt.get('m_LocalScale', {})
                lp = trt.get('m_LocalPosition', {})
                if ps and psr:
                    pst = ps.read_typetree(); psrt = psr.read_typetree()
                    init = pst.get('InitialModule', {})
                    em = pst.get('EmissionModule', {})
                    sh = pst.get('ShapeModule', {})
                    szm = pst.get('SizeModule', {})
                    mat_info = []
                    for m in psrt.get('m_Materials', []):
                        mp = m.get('m_PathID', 0)
                        if m.get('m_FileID') == 0 and mp in objs:
                            mt = objs[mp].read_typetree()
                            shn = resolve_name(objs, mt.get('m_Shader'))
                            sp = mt.get('m_SavedProperties', {})
                            texs = {k: resolve_name(objs, v.get('m_Texture')) for k, v in sp.get('m_TexEnvs', []) if v.get('m_Texture', {}).get('m_PathID')}
                            flts = {k: round(v, 3) for k, v in sp.get('m_Floats', [])}
                            cols = {k: [round(v[c], 3) for c in ('r','g','b','a')] for k, v in sp.get('m_Colors', [])}
                            mat_info.append((mt.get('m_Name'), shn, texs, flts, cols))
                    print(f'  {"  "*min(depth,4)}[act={go.m_IsActive}] {path} lpos=({lp.get("x",0):.1f},{lp.get("y",0):.1f},{lp.get("z",0):.1f}) lsc=({ls.get("x",1):.3f},{ls.get("y",1):.3f},{ls.get("z",1):.3f})')
                    print(f'    sm={pst.get("scalingMode")} rm={psrt.get("m_RenderMode")} rmode_en={psrt.get("m_Enabled")} mesh={resolve_name(objs, psrt.get("m_Mesh"))} sz={init.get("startSize")} sz3d={init.get("size3D")} szX={init.get("startSizeX",{}).get("scalar")} szY={init.get("startSizeY",{}).get("scalar")} szMod=({szm.get("enabled")},{szm.get("separateAxes")}) em=({em.get("enabled")},rate={em.get("rateOverTime",{}).get("scalar")},bursts={len(em.get("m_Bursts",[]))}) sh=({sh.get("type")},r={sh.get("radius",{}).get("value")})')
                    print(f'    mats={mat_info}')
                for ch in trt.get('m_Children', []):
                    cp = ch.get('m_PathID')
                    if cp in objs:
                        ct = objs[cp].read_typetree()
                        cgo = ct.get('m_GameObject', {}).get('m_PathID')
                        if cgo in objs:
                            stack.append((cgo, path + '/' + (objs[cgo].peek_name() or ''), depth + 1))

for p in ['Aurora_S5_Background', 'QuLing_S2_Background', 'Benten_S4_Background', 'Gawana_S2_Background', 'Ennis_S2_Background', 'Clarice_S3_Background', 'fx_9008114', 'fx_9008107']:
    dump_ps_tree(ui_env, ui_objs, p)
    dump_ps_tree(art_env, art_objs, p)

# 2. Check ALL materials used across fx_manifest skins by material name -> AB Shader & Props
print('\n=== 2. Manifest Materials -> AB Shader & Alpha/Mask Analysis ===')
mat_nodes = {}
for sk in man['skins']:
    for c in sk['clips']:
        for n in c['nodes']:
            mn = n.get('matName', '')
            if mn not in mat_nodes:
                mat_nodes[mn] = (sk['skin_key'], c['clip'], n['name'], n.get('add'), n.get('texName'), n.get('maskTexName', ''))

ab_mats = {}
for env, objs in [(ui_env, ui_objs), (art_env, art_objs)]:
    for o in env.objects:
        if o.type.name == 'Material':
            nm = o.peek_name() or ''
            if nm in mat_nodes and nm not in ab_mats:
                mt = o.read_typetree()
                shn = resolve_name(objs, mt.get('m_Shader'))
                sp = mt.get('m_SavedProperties', {})
                texs = {k: resolve_name(objs, v.get('m_Texture')) for k, v in sp.get('m_TexEnvs', []) if v.get('m_Texture', {}).get('m_PathID')}
                flts = {k: round(v, 3) for k, v in sp.get('m_Floats', [])}
                cols = {k: [round(v[c], 3) for c in ('r','g','b','a')] for k, v in sp.get('m_Colors', [])}
                ab_mats[nm] = (shn, texs, flts, cols)

shader_counts = Counter(v[0] for v in ab_mats.values())
print('Shader counts across manifest materials:', shader_counts)

# Check textures whose alpha channel is uniformly 255 (RGB grayscale or opaque!) used in non-additive OR masked materials
opaque_alpha_tex = []
for mn, info in mat_nodes.items():
    sk_k, cl, nn, is_add, tn, mtn = info
    shn, texs, flts, cols = ab_mats.get(mn, ('MISSING', {}, {}, {}))
    tp = tex_dir / f'{tn}.png'
    a_min = a_max = -1
    if tn and tp.exists():
        im = Image.open(tp).convert('RGBA')
        a_min, a_max = im.getchannel('A').getextrema()
    ma_min = ma_max = -1
    if mtn and (tex_dir / f'{mtn}.png').exists():
        mim = Image.open(tex_dir / f'{mtn}.png').convert('RGBA')
        ma_min, ma_max = mim.getchannel('A').getextrema()
    if (a_min >= 250 and not is_add) or (mtn and ma_min >= 200) or (len(texs) > 2) or (shn and 'add' not in str(shn).lower() and 'alpha' not in str(shn).lower() and 'particle' not in str(shn).lower()):
        opaque_alpha_tex.append((sk_k, cl, nn, mn, shn, is_add, tn, (a_min,a_max), mtn, (ma_min,ma_max), flts, list(texs.keys())))

print(f'Suspicious Material/Shader/Alpha/Mask entries: {len(opaque_alpha_tex)}')
for row in opaque_alpha_tex[:60]:
    print('  MAT:', row)

# 3. Check all built Spine .config.json and fx_*.json calibration bounds
print('\n=== 3. Built Spine Package Calibration Audit ===')
sp_root = Path(r'E:\A灵魂潮汐\Live2D与Spine模型\spine')
fx_scales = []
orig_checks = []
for cfg_p in sorted(sp_root.rglob('*.config.json')):
    cfg = json.loads(cfg_p.read_text(encoding='utf-8'))
    rel = cfg_p.relative_to(sp_root)
    is_orig = cfg_p.parent.name in ('原皮', '原皮(立绘)')
    sc_val = cfg.get('scale_factor')
    if is_orig:
        if not sc_val or float(sc_val) > 5.0 or float(sc_val) < 0.05:
            orig_checks.append((str(rel), sc_val))
    for sub in cfg.get('submodels', []):
        nm = sub.get('name', '')
        sp = sub.get('scaleX'), sub.get('scaleY')
        if nm.startswith('fx_'):
            fx_scales.append((str(rel), nm, sub.get('x'), sub.get('y'), sp[0], sp[1]))
        elif abs(float(sub.get('scaleX', 1) or 1)) > 5 or abs(float(sub.get('scaleX', 1) or 1)) < 0.05:
            orig_checks.append((str(rel) + '/' + nm, sub.get('scaleX')))
print('Weird orig/bg scale_factor/submodels:', orig_checks)
weird_fx_scales = [x for x in fx_scales if abs(float(x[4] or 0)) < 0.05 or abs(float(x[4] or 0)) > 1.5]
print(f'Total fx submodels: {len(fx_scales)}, weird scales (<0.05 or >1.5): {len(weird_fx_scales)}')
for x in weird_fx_scales:
    print('  WEIRD_FX:', x)
