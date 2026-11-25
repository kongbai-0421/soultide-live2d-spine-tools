import json, sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

pids = {
    9076621251284227344, 1476093635197393937, -1075113292880553162,
    -5371216518145074825, -2882234646681408847, -945509343750945775,
    5389071715300839937, 8665360252727739062, 8829493088806448665,
    -7665262404106375586, 2843555733212822540, 2430647832406757683,
}

print('=== 1. Resolve Shader PIDs & Cameras across ABs ===')
for ab_p in sorted(sc.CDN_ROOT.rglob('*.ab')):
    env = sc.load_ab(ab_p)
    objs = {o.path_id: o for o in env.objects}
    for o in env.objects:
        if o.type.name == 'Shader':
            if o.path_id in pids or 'shader' in ab_p.name.lower():
                nm = o.peek_name() or ''
                props = []
                try:
                    st = o.read_typetree()
                    pf = st.get('m_ParsedForm', {})
                    nm = nm or pf.get('m_Name', '')
                    for pr in pf.get('m_PropInfo', {}).get('m_Props', []):
                        props.append((pr.get('m_Name'), pr.get('m_Description'), pr.get('m_Type')))
                except Exception:
                    pass
                print(f'  SHADER [{ab_p.relative_to(sc.CDN_ROOT)}] pid={o.path_id} -> {nm}')
                if props:
                    print(f'    props: {props[:25]}')
        elif o.type.name == 'Camera':
            ct = o.read_typetree()
            go_pid = ct.get('m_GameObject', {}).get('m_PathID')
            gnm = objs[go_pid].peek_name() if go_pid in objs else ''
            print(f'  CAMERA [{ab_p.relative_to(sc.CDN_ROOT)}] {gnm} ortho={ct.get("orthographic")} size={ct.get("orthographic size")} fov={ct.get("field of view")}')
        elif o.type.name == 'CanvasScaler':
            cs = o.read_typetree()
            print(f'  SCALER [{ab_p.relative_to(sc.CDN_ROOT)}] mode={cs.get("m_UiScaleMode")} res={cs.get("m_ReferenceResolution")} match={cs.get("m_MatchWidthOrHeight")} ppu={cs.get("m_ReferencePixelsPerUnit")}')

print('\n=== 2. Check Ennis_S3 FX_ZC_Mask214 & Clarice_S3 yuan_glow textures ===')
tex_dir = Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures')
for tn in ('FX_ZC_Mask214', 'FX_ZC_Mask215', 'FX_ZC_Mask003', 'FX_ZC_Noise016', 'FX_gra_trail', 'FX_mask13', 'FX_ZC_Noise013', 'FX_ZC_Mask195', 'FX_mask22', 'FX_ZC_Noise007', 'FX_gra_WL_142', 'FX_UItrail03_2'):
    tp = tex_dir / f'{tn}.png'
    if tp.exists():
        im = Image.open(tp).convert('RGBA')
        print(f'  {tn}: size={im.size} extrema={im.getextrema()} corner={im.getpixel((0,0))} mid={im.getpixel((im.width//2, im.height//2))}')
    else:
        print(f'  {tn}: MISSING')

print('\n=== 3. Check 4 Empty FX Channels in fx_manifest.json ===')
man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))
targets = {
    ('402_Freesia_S5', 'fx_9008161'),
    ('603_Asuna_S8', 'idle'),
    ('2301_QuLing_S2', 'idle'),
    ('3501_QingDai_S2', 'fx_9008143'),
}
for sk in man['skins']:
    for c in sk['clips']:
        if (sk['skin_key'], c['clip']) in targets:
            print(f'  [{sk["skin_key"]} {c["clip"]}] ({sk["canvas_w"]}x{sk["canvas_h"]}):')
            for n in c['nodes']:
                print(f'    node={n["name"]} add={n["add"]} rm={n["renderMode"]} sm={n["scalingMode"]} tex={n["texName"]} mask={n.get("maskTexName")} pos={n["pos"]} lpos={n.get("local_pos")} wscale={n["world_scale"]} sz={n["size"]} lt={n["lifetime"]} rate={n["emissionRate"]} bursts={n.get("bursts")} delay={n["startDelay"]} col={n["startColor"]}')
