import json, sys
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Inspect shader blend states in 15_shader_base.ab
sh_ab = sc.CDN_ROOT / '15_shader' / '15_shader_base.ab'
env = sc.load_ab(sh_ab)
pids = {
    9076621251284227344, 1476093635197393937, -1075113292880553162,
    -5371216518145074825, -2882234646681408847, -945509343750945775,
    5389071715300839937, 8665360252727739062, 8829493088806448665,
    -7665262404106375586, 2843555733212822540, 2430647832406757683,
}
print('=== 1. Shader SubShader Blend States in 15_shader_base.ab ===')
for o in env.objects:
    if o.type.name == 'Shader' and o.path_id in pids:
        st = o.read_typetree()
        pf = st.get('m_ParsedForm', {})
        nm = pf.get('m_Name', o.peek_name())
        blends = []
        for ss in pf.get('m_SubShaders', []):
            for pa in ss.get('m_Passes', []):
                stb = pa.get('m_State', {})
                rt0 = stb.get('rtBlend0', {})
                blends.append((
                    pa.get('m_Name'),
                    stb.get('m_Name'),
                    rt0.get('srcBlend', {}).get('val'),
                    rt0.get('destBlend', {}).get('val'),
                    rt0.get('srcBlendAlpha', {}).get('val'),
                    rt0.get('destBlendAlpha', {}).get('val'),
                    stb.get('culling', {}).get('val'),
                    stb.get('zWrite', {}).get('val'),
                ))
        print(f'  {nm} (pid={o.path_id}): passes={blends}')

# 2. Dump FULL node JSON for QuLing_S2 water, Virgina_S3 fx_9008114 glow01/glow02, Ennis_S3 an, Clarice_S3 FX_glow/yuan_glow, Gawana_S2 wepon, Benten_S4 cahihonghuan, QingDai_S2 fx_9008143 shan/bao
man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))
print('\n=== 2. Manifest full node specs for key suspects ===')
checks = [
    ('2301_QuLing_S2', 'idle', 'water'),
    ('1202_Virgina_S3', 'fx_9008114', 'glow01'),
    ('2002_Ennis_S3', 'fx_9008124', 'an'),
    ('4602_Clarice_S3', 'idle', 'FX_glow'),
    ('4602_Clarice_S3', 'idle', 'yuan_glow (1)'),
    ('1903_Aurora_S5', 'idle', 'FX_glow'),
    ('503_Benten_S4', 'idle', 'cahihonghuan'),
    ('1601_Gawana_S2', 'fx_9008107', 'wepon'),
    ('3501_QingDai_S2', 'fx_9008143', 'shan'),
    ('3501_QingDai_S2', 'fx_9008143', 'baozhu'),
    ('603_Asuna_S8', 'idle', 'trail01'),
]
for sk in man['skins']:
    for c in sk['clips']:
        for n in c['nodes']:
            if (sk['skin_key'], c['clip'], n['name']) in checks:
                print(f"\n--- {sk['skin_key']} / {c['clip']} / {n['name']} ---")
                print(json.dumps(n, ensure_ascii=False))

# 3. Check Raw AB QuLing_S2 water ParticleSystemRenderer & Velocity & Rotation & Shape + Asuna_S8 + QingDai_S2 fx_9008143
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
for abn, aenv in [('ui.ab', ui_env), ('art_prefabs.ab', art_env)]:
    objs = {o.path_id: o for o in aenv.objects}
    for o in aenv.objects:
        if o.type.name == 'GameObject' and (o.peek_name() or '') in ('QuLing_S2_Background', 'fx_9008143', 'fx_9008161', 'Asuna_S8_Background'):
            print(f'\n=== Raw AB Tree [{abn}] {o.peek_name()} ===')
            stack = [(o.path_id, o.peek_name())]
            seen = set()
            while stack:
                gid, path = stack.pop(0)
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
                if ps:
                    pst = ps.read_typetree()
                    psrt = psr.read_typetree() if psr else {}
                    em = pst.get('EmissionModule', {})
                    vel = pst.get('VelocityModule', {})
                    init = pst.get('InitialModule', {})
                    subm = pst.get('SubModule', {})
                    print(f'  [act={go.m_IsActive}] {path}: lpos={trt.get("m_LocalPosition")} lsc={trt.get("m_LocalScale")}')
                    print(f'    playOnAwake={pst.get("playOnAwake")} em_en={em.get("enabled")} rate={em.get("rateOverTime")} bursts={em.get("m_Bursts")} spd={init.get("startSpeed")} vel_en={vel.get("enabled")} sub_en={subm.get("enabled")}')
                    print(f'    rm={psrt.get("m_RenderMode")} velSc={psrt.get("m_VelocityScale")} lenSc={psrt.get("m_LengthScale")} camVelSc={psrt.get("m_CameraVelocityScale")} psr_en={psrt.get("m_Enabled")} sort={psrt.get("m_SortMode")} mat={psrt.get("m_Materials")}')
                for ch in trt.get('m_Children', []):
                    cp = ch.get('m_PathID')
                    if cp in objs:
                        cgo = objs[cp].read_typetree().get('m_GameObject', {}).get('m_PathID')
                        if cgo in objs:
                            stack.append((cgo, path + '/' + (objs[cgo].peek_name() or '')))

# 4. Save 50% JPG previews of Virgina_S3 fx_9008114 add, Gawana_S2 fx_9008107 add, Freesia_S5 fx_9008161 add, Ennis_S3 fx_9008124 add
seq_root = Path(r'E:\A灵魂潮汐\tools\_batch_fx_sequences')
out_dir = Path(r'.\_scratch\audit_previews')
for sk, cl, ch in [
    ('1202_Virgina_S3', 'fx_9008114', 'add'),
    ('1202_Virgina_S3', 'fx_9008114', 'normal'),
    ('1601_Gawana_S2', 'fx_9008107', 'add'),
    ('402_Freesia_S5', 'fx_9008161', 'add'),
    ('2002_Ennis_S3', 'fx_9008124', 'add'),
]:
    cdir = seq_root / sk / cl / ch
    if not cdir.is_dir(): continue
    frames = sorted(cdir.glob('frame_*.png'))
    if not frames: continue
    picks = [frames[int(i*(len(frames)-1)/3)] for i in range(4)]
    ims = [Image.open(p).convert('RGBA') for p in picks]
    cw, ch_h = ims[0].size
    grid = Image.new('RGB', (cw*2, ch_h*2), (30, 34, 42))
    bg = Image.new('RGBA', (cw, ch_h), (30, 34, 42, 255))
    for idx, (p, im) in enumerate(zip(picks, ims)):
        comp = Image.alpha_composite(bg, im).convert('RGB')
        x, y = (idx % 2) * cw, (idx // 2) * ch_h
        grid.paste(comp, (x, y))
        ImageDraw.Draw(grid).text((x+6, y+6), f'{sk} {cl}/{ch} {p.name} bb={im.getbbox()}', fill=(255,220,100))
    w2, h2 = max(1, grid.width // 2), max(1, grid.height // 2)
    outp = out_dir / f'{sk}_{cl}_{ch}_50pct.jpg'
    grid.resize((w2, h2), Image.Resampling.LANCZOS).save(outp, 'JPEG', quality=80)
    print('Saved preview:', outp.name)
