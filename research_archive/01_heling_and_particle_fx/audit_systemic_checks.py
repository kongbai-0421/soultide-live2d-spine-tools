import json, sys
from pathlib import Path
from collections import Counter
from PIL import Image

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))
seq_root = Path(r'E:\A灵魂潮汐\tools\_batch_fx_sequences')
tex_dir = Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures')

print('=== 1. Check actual rendered frame counts & bboxes for Freesia_S5, Asuna_S8, QuLing_S2, QingDai_S2, Aurora_S3, Ithil_S2, Benten_S4, Ennis_S2 ===')
for sk in man['skins']:
    if sk['skin_key'] in ('402_Freesia_S5', '603_Asuna_S8', '2301_QuLing_S2', '3501_QingDai_S2', '1901_Aurora_S3', '3101_Ithil_S2', '503_Benten_S4', '2001_Ennis_S2'):
        for c in sk['clips']:
            sdir = seq_root / sk['skin_key'] / c['clip']
            res = {}
            for ch in ('normal', 'add'):
                chd = sdir / ch
                if chd.is_dir():
                    ne = sum(1 for p in chd.glob('frame_*.png') if Image.open(p).getbbox() is not None)
                    res[ch] = ne
            n_norm = sum(1 for n in c['nodes'] if not n['isAdditive'])
            n_add = sum(1 for n in c['nodes'] if n['isAdditive'])
            subs = [(c['nodes'][se['targetIdx']]['name'], c['nodes'][se['targetIdx']]['isAdditive']) for n in c['nodes'] for se in n.get('subEmitters', [])]
            print(f"  {sk['skin_key']} {c['clip']}: ren={res} nodes=(norm:{n_norm}, add:{n_add}) subs={subs}")
            if sk['skin_key'] == '402_Freesia_S5' and c['clip'] == 'fx_9008161':
                for n in c['nodes']:
                    print(f"    Freesia {n['name']}: add={n['isAdditive']} tex={n['texName']} mask={n['maskTexName']} pos={n['world_pos']} ws={n['world_scale']} tintMul={n['tintMultiplier']} tint={n['tint']} sz3d={n['size3D']} sz={n['size']['scalar']} szY={n['sizeY']['scalar']} bursts={n['bursts']}")

print('\n=== 2. Check PSR m_MaxParticleSize / m_RenderAlignment / m_MaskInteraction across ABs ===')
max_ps_vals = Counter()
align_vals = Counter()
mask_int_vals = Counter()
for abn in ('ui.ab', 'art_prefabs.ab'):
    env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / abn)
    for o in env.objects:
        if o.type.name == 'ParticleSystemRenderer':
            tt = o.read_typetree()
            max_ps_vals[round(tt.get('m_MaxParticleSize', 0.5), 2)] += 1
            align_vals[tt.get('m_RenderAlignment', 0)] += 1
            mask_int_vals[tt.get('m_MaskInteraction', 0)] += 1
print('m_MaxParticleSize dist:', max_ps_vals.most_common(15))
print('m_RenderAlignment dist:', align_vals.most_common(10))
print('m_MaskInteraction dist:', mask_int_vals.most_common(10))

print('\n=== 3. Check ALL materials with _mask02, _Rongjie, _UV_t, _offon, _Alphe, _qiangdu, _quse, or texScale != [1,1] ===')
ab_mats = {}
for abp in sorted(sc.CDN_ROOT.rglob('*.ab')):
    env = sc.load_ab(abp)
    objs = {o.path_id: o for o in env.objects}
    for o in env.objects:
        if o.type.name == 'Material':
            nm = o.peek_name() or ''
            if nm and nm not in ab_mats:
                mt = o.read_typetree()
                sp = mt.get('m_Shader', {})
                shn = ''
                if sp.get('m_FileID') == 0 and sp.get('m_PathID') in objs:
                    shn = objs[sp['m_PathID']].peek_name() or ''
                saved = mt.get('m_SavedProperties', {})
                texs = {}
                for k, v in saved.get('m_TexEnvs', []):
                    pid = v.get('m_Texture', {}).get('m_PathID', 0)
                    if pid:
                        texs[k] = (pid, v.get('m_Scale'), v.get('m_Offset'))
                flts = {k: round(float(v), 3) for k, v in saved.get('m_Floats', [])}
                cols = {k: [round(v[c], 3) for c in ('r','g','b','a')] for k, v in saved.get('m_Colors', [])}
                ab_mats[nm] = (sp.get('m_PathID'), shn, texs, flts, cols)

used_mats = {}
for sk in man['skins']:
    for c in sk['clips']:
        for n in c['nodes']:
            mn = n.get('matName', '')
            if mn:
                used_mats.setdefault(mn, []).append((sk['skin_key'], c['clip'], n['name'], n['texName'], n['maskTexName'], n['isAdditive']))

with_mask02 = []
with_dissolve = []
with_uv_scroll = []
with_offon = []
with_intensity = []
with_alpha_mul = []
for mn, users in used_mats.items():
    if mn not in ab_mats: continue
    spid, shn, texs, flts, cols = ab_mats[mn]
    if '_mask02' in texs or '_Rongjie_tietu' in texs:
        with_mask02.append((mn, list(texs.keys()), flts.get('_Mask_U'), flts.get('_Mask_V'), cols.get('_UV_t'), users[:2]))
    if flts.get('_Rongjie', 0) > 0.01 or '_Main_tex' in texs:
        with_dissolve.append((mn, flts.get('_Rongjie'), flts.get('_Ruanying'), flts.get('_Alpha'), flts.get('_Alphe'), users[:2]))
    uvt = cols.get('_UV_t', [0,0,0,0])
    if any(abs(x) > 0.01 for x in uvt) or abs(flts.get('_Mask_U', 0)) > 0.01 or abs(flts.get('_Mask_V', 0)) > 0.01:
        with_uv_scroll.append((mn, uvt[:2], flts.get('_Mask_U'), flts.get('_Mask_V'), users[:2]))
    if '_offon' in flts or '_mask_offon' in flts:
        with_offon.append((mn, spid, flts.get('_offon'), flts.get('_mask_offon'), flts.get('_Alphe'), users[:1]))
    if '_Intensity' in flts or '_Brightness' in flts:
        with_intensity.append((mn, spid, shn, flts.get('_Intensity'), flts.get('_Brightness'), users[:1]))
    if flts.get('_Alphe', 1.0) > 1.05 or flts.get('_qiangdu', 1.0) > 1.05 or flts.get('_MainTexIntensity', 1.0) > 1.05:
        with_alpha_mul.append((mn, spid, shn, flts.get('_Alphe'), flts.get('_qiangdu'), flts.get('_MainTexIntensity'), users[:1]))

print(f'Materials with _mask02/_Rongjie_tietu: {len(with_mask02)}')
for r in with_mask02[:25]: print('  MASK02:', r)
print(f'Materials with _Rongjie or _Main_tex: {len(with_dissolve)}')
for r in with_dissolve[:25]: print('  RONGJIE:', r)
print(f'Materials with UV scroll (_UV_t / _Mask_UV): {len(with_uv_scroll)}')
for r in with_uv_scroll[:20]: print('  UV:', r)
print(f'Materials with _Intensity / _Brightness: {len(with_intensity)}')
for r in with_intensity[:20]: print('  INT:', r)
print(f'Materials with _Alphe / _qiangdu > 1: {len(with_alpha_mul)}')
for r in with_alpha_mul[:20]: print('  AMUL:', r)
