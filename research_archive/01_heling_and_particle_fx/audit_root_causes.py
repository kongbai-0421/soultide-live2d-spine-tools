import json, sys
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Check 01_scenes/home.ab Canvas & Camera & Parent Hierarchy + scalingMode==1 nodes vs siblings
print('=== 1. Home Scene Hierarchy & Scale Math ===')
home_env = sc.load_ab(sc.CDN_ROOT / '01_scenes' / 'home.ab')
home_objs = {o.path_id: o for o in home_env.objects}
for o in home_env.objects:
    if o.type.name == 'GameObject':
        nm = o.peek_name() or ''
        if any(k in nm.lower() for k in ('canvas', 'camera', 'bg', 'background', 'uiroot', 'root', 'home')):
            go = o.read()
            info = []
            for cr in go.m_Component:
                co = home_objs.get(cr.component.path_id)
                if not co: continue
                if co.type.name in ('Transform', 'RectTransform'):
                    ct = co.read_typetree()
                    ls = ct.get('m_LocalScale', {})
                    lp = ct.get('m_LocalPosition', {})
                    sd = ct.get('m_SizeDelta', {})
                    info.append(f'pos=({lp.get("x",0):.1f},{lp.get("y",0):.1f},{lp.get("z",0):.1f}) sc=({ls.get("x",1):.5f},{ls.get("y",1):.5f},{ls.get("z",1):.5f}) sd=({sd.get("x",0):.1f},{sd.get("y",0):.1f})')
                elif co.type.name == 'Camera':
                    ct = co.read_typetree()
                    info.append(f'Cam(ortho={ct.get("orthographic")},size={ct.get("orthographic size")})')
                elif co.type.name == 'Canvas':
                    ct = co.read_typetree()
                    info.append(f'Canvas(rm={ct.get("m_RenderMode")},pd={ct.get("m_PlaneDistance")})')
                elif co.type.name == 'CanvasScaler':
                    ct = co.read_typetree()
                    info.append(f'Scaler(mode={ct.get("m_UiScaleMode")},res={ct.get("m_ReferenceResolution")},match={ct.get("m_MatchWidthOrHeight")},ppu={ct.get("m_ReferencePixelsPerUnit")})')
            print(f'  [home.ab] {nm}: {info}')

# 2. Check Virgina_S3 fx_9008114 non-empty frames & peak frames + Clarice_S3 / QuLing_S2 textures + Ennis_S3 manifest
print('\n=== 2. Check Virgina_S3 fx_9008114 frames & textures ===')
seq_root = Path(r'E:\A灵魂潮汐\tools\_batch_fx_sequences')
out_dir = Path(r'.\_scratch\audit_previews')
for ch in ('normal', 'add'):
    cdir = seq_root / '1202_Virgina_S3' / 'fx_9008114' / ch
    if not cdir.is_dir(): continue
    ne_frames = []
    for p in sorted(cdir.glob('frame_*.png')):
        bb = Image.open(p).getbbox()
        if bb:
            ne_frames.append((p, bb, (bb[2]-bb[0])*(bb[3]-bb[1])))
    print(f'  1202_Virgina_S3 fx_9008114/{ch}: {len(ne_frames)} non-empty, first={ne_frames[0][0].name if ne_frames else None}, last={ne_frames[-1][0].name if ne_frames else None}')
    if ne_frames:
        # pick peak + 3 distributed non-empty
        picks = [ne_frames[0][0], ne_frames[len(ne_frames)//3][0], ne_frames[(2*len(ne_frames))//3][0], ne_frames[-1][0]]
        ims = [Image.open(p).convert('RGBA') for p in picks]
        cw, ch_h = ims[0].size
        grid = Image.new('RGB', (cw*2, ch_h*2), (30, 34, 42))
        bg = Image.new('RGBA', (cw, ch_h), (30, 34, 42, 255))
        for idx, (p, im) in enumerate(zip(picks, ims)):
            comp = Image.alpha_composite(bg, im).convert('RGB')
            x, y = (idx % 2) * cw, (idx // 2) * ch_h
            grid.paste(comp, (x, y))
            ImageDraw.Draw(grid).text((x+6, y+6), f'Virgina_S3 {ch} {p.name} bb={im.getbbox()}', fill=(255,220,100))
        outp = out_dir / f'1202_Virgina_S3_fx_9008114_{ch}_peak_50pct.jpg'
        grid.resize((grid.width//2, grid.height//2), Image.Resampling.LANCZOS).save(outp, 'JPEG', quality=80)
        print(f'  Saved peak preview: {outp.name}')

tex_dir = Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures')
for tn in ('FX_glow04_01', 'FX_ZC_Mask003', 'FX_ZC_Noise016', 'FX_FH_Line_Tile_01', 'FX_gra_WL_142', 'FX_UItrail03_2', 'FX_UI_liehen01', 'FX_ZC_Noise019'):
    tp = tex_dir / f'{tn}.png'
    if tp.exists():
        im = Image.open(tp).convert('RGBA')
        print(f'  TEX {tn}: {im.size} ext={im.getextrema()} c={im.getpixel((0,0))} m={im.getpixel((im.width//2, im.height//2))}')

# 3. Check additive vs shader blend mismatch & opaque-alpha grayscale RGB in AlphaBlended across ALL 101 manifest skins
print('\n=== 3. Full Material / Shader / Additive / Opaque-Alpha Audit across 101 Skins ===')
sh_ab = sc.load_ab(sc.CDN_ROOT / '15_shader' / '15_shader_base.ab')
sh_by_pid = {}
for o in sh_ab.objects:
    if o.type.name == 'Shader':
        st = o.read_typetree()
        pf = st.get('m_ParsedForm', {})
        nm = pf.get('m_Name', o.peek_name())
        src = dst = None
        for ss in pf.get('m_SubShaders', []):
            for pa in ss.get('m_Passes', []):
                rt0 = pa.get('m_State', {}).get('rtBlend0', {})
                d = rt0.get('destBlend', {}).get('val')
                s = rt0.get('srcBlend', {}).get('val')
                if d is not None:
                    src, dst = s, d
                    break
            if dst is not None: break
        sh_by_pid[o.path_id] = (nm, src, dst)

ab_mats = {}
for ab_p in sorted(sc.CDN_ROOT.rglob('*.ab')):
    env = sc.load_ab(ab_p)
    objs = {o.path_id: o for o in env.objects}
    for o in env.objects:
        if o.type.name == 'Material':
            nm = o.peek_name() or ''
            if nm and nm not in ab_mats:
                mt = o.read_typetree()
                sp = mt.get('m_Shader', {})
                shn = ''; src = dst = None
                if sp.get('m_FileID') == 0 and sp.get('m_PathID') in objs:
                    shn = objs[sp['m_PathID']].peek_name() or ''
                elif sp.get('m_PathID') in sh_by_pid:
                    shn, src, dst = sh_by_pid[sp['m_PathID']]
                saved = mt.get('m_SavedProperties', {})
                flts = {k: float(v) for k, v in saved.get('m_Floats', [])}
                ab_mats[nm] = (shn, src, dst, flts)

man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))
blend_mismatches = set()
alpha_opaque_rgb = set()
for sk in man['skins']:
    for c in sk['clips']:
        for n in c['nodes']:
            mn = n.get('matName', '')
            if not mn or mn not in ab_mats: continue
            shn, src, dst, flts = ab_mats[mn]
            # check actual GPU blend mode
            actual_add = None
            if dst is not None:
                actual_add = (abs(dst - 1.0) < 0.1)
            elif 'additive' in shn.lower():
                actual_add = True
            elif 'alpha blended' in shn.lower() or 'standard' in shn.lower():
                if 'standard' in shn.lower():
                    actual_add = (abs(flts.get('_DstBlend', 10.0) - 1.0) < 0.1)
                else:
                    actual_add = False
            # NOTE: FX_qqc/UVliudong has _offon: check whether _offon switches alpha vs additive!
            if actual_add is not None and bool(n.get('isAdditive')) != actual_add:
                blend_mismatches.add((sk['skin_key'], c['clip'], n['name'], mn, shn, f'manifest_add={n.get("isAdditive")}', f'shader_dst={dst}', f'_offon={flts.get("_offon")}', f'_DstB={flts.get("_DstBlend")}'))
            # check if isAdditive==False (or actual_add==False) & tex has uniform alpha=255
            tn = n.get('texName', '')
            tp = tex_dir / f'{tn}.png'
            if (not n.get('isAdditive') or actual_add is False) and tn and tp.exists():
                im = Image.open(tp).convert('RGBA')
                a_min, a_max = im.getchannel('A').getextrema()
                c0 = im.getpixel((0, 0))
                if a_min >= 245 and max(c0[0], c0[1], c0[2]) <= 25:
                    alpha_opaque_rgb.add((sk['skin_key'], c['clip'], n['name'], mn, shn, tn, c0, f'a=({a_min},{a_max})', n.get('maskTexName', '')))

print(f'Blend mode mismatches: {len(blend_mismatches)}')
for x in sorted(blend_mismatches)[:50]:
    print('  MISMATCH:', x)
print(f'Non-additive opaque-alpha dark-corner textures: {len(alpha_opaque_rgb)}')
for x in sorted(alpha_opaque_rgb)[:50]:
    print('  OPAQUE_ALPHA:', x)

# 4. Also check Ennis_S3 skin metadata in manifest
for sk in man['skins']:
    if sk['skin_key'] == '2002_Ennis_S3':
        print('\n=== 2002_Ennis_S3 skin header ===', {k: v for k, v in sk.items() if k != 'clips'})
