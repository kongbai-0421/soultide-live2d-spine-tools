import json, os, sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))

# 1. Inspect ALL 51 Giant nodes details
print("=== ALL Giant nodes (eff_px > 1.1*cw) ===")
for sk in man['skins']:
    cw = sk['canvas_w']
    for c in sk['clips']:
        for n in c['nodes']:
            ws = n['world_scale']
            sc_max = max(abs(ws[0]), abs(ws[1]))
            sz = n['size']
            sz_hi = max(abs(float(sz['scalar'])), abs(float(sz['minScalar'])))
            eff_px = sz_hi * sc_max
            if n.get('size3D'):
                sx = max(abs(n['sizeX']['scalar']), abs(n['sizeX']['minScalar'])) * abs(ws[0])
                sy = max(abs(n['sizeY']['scalar']), abs(n['sizeY']['minScalar'])) * abs(ws[1])
                eff_px = max(sx, sy)
            if eff_px > cw * 1.1:
                print(f"  {sk['skin_key']} {c['clip']} '{n['name']}': eff_px={eff_px:.1f} (sz={sz_hi:.2f}, wscale={[round(x,2) for x in ws]}, sm={n['scalingMode']}, rm={n['renderMode']}, tex={n['texName']})")

# 2. Check QuLing_S2 why fx_quling_s2 had fx_empty
print("\n=== QuLing_S2 check ===")
q_skins = [s for s in man['skins'] if 'quling' in s['skin_key'].lower()]
for s in q_skins:
    print("  manifest:", s['skin_key'], [(c['clip'], len(c['nodes'])) for c in s['clips']])
q_seq = Path(r'E:\A灵魂潮汐\tools\_batch_fx_sequences')
for d in q_seq.glob('*QuLing*'):
    print("  seq dir:", d.name, [(p.parent.name + '/' + p.name, Image.open(p).getbbox()) for p in sorted(d.rglob('frame_0000.png'))[:6]])
    for clipdir in d.iterdir():
        if clipdir.is_dir():
            for ch in ('normal', 'add'):
                chd = clipdir / ch
                if chd.is_dir():
                    ne = sum(1 for fp in chd.glob('frame_*.png') if Image.open(fp).getbbox() is not None)
                    print(f"    {clipdir.name}/{ch}: {ne}/{len(list(chd.glob('frame_*.png')))} non-empty")

# 3. Inspect FX_Material_Virgina_S3_03 & other masked materials + textures
print("\n=== Check FX_ZC_Mask003 & FX_ZC_Noise016 images ===")
tex_dir = Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures')
for tn in ('FX_ZC_Mask003', 'FX_ZC_Noise016', 'FX_ZC_Glow019', 'FX_ZC_Mask139', 'FX_FH_Line_Tile_01'):
    tp = tex_dir / f'{tn}.png'
    if tp.exists():
        im = Image.open(tp).convert('RGBA')
        ext = im.getextrema()
        # check border pixels
        px_corner = im.getpixel((0, 0))
        px_mid = im.getpixel((im.width//2, im.height//2))
        print(f"  {tn}: size={im.size}, extrema={ext}, corner={px_corner}, center={px_mid}")

# 4. Inspect Aurora_S5, Virgina_S3, Ennis_S2 raw prefab ParticleSystems + Shaders + Meshes
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
art_objs = {o.path_id: o for o in art_env.objects}

# Check ALL renderMode==4 Meshes across ui.ab & art_prefabs.ab ParticleSystemRenderers
meshes = {}
for name, env, objs in [('ui', ui_env, ui_objs), ('art', art_env, art_objs)]:
    for o in env.objects:
        if o.type.name == 'ParticleSystemRenderer':
            d = o.read_typetree()
            if d.get('m_RenderMode') == 4:
                mref = d.get('m_Mesh', {})
                mpid = mref.get('m_PathID', 0)
                mfid = mref.get('m_FileID', 0)
                mname = f'fid={mfid},pid={mpid}'
                if mfid == 0 and mpid in objs:
                    mname = objs[mpid].peek_name()
                meshes[mname] = meshes.get(mname, 0) + 1
print("\n=== RenderMode==4 Mesh distribution ===")
for k, v in sorted(meshes.items(), key=lambda x: -x[1])[:20]:
    print(f"  {k}: {v}")

# Inspect Aurora_S5_Background & Virgina_S3_dress01 materials in raw AB
for o in ui_env.objects:
    if o.type.name == 'GameObject' and (o.peek_name() or '').lower() in ('aurora_s5_background', 'quling_s2_background', 'ennis_s2_background'):
        print(f"\n=== Raw UI Tree: {o.peek_name()} ===")
        def d(gid, depth=0):
            g = ui_objs[gid].read()
            rt = None
            info = ''
            for cr in g.m_Component:
                co = ui_objs.get(cr.component.path_id)
                if not co: continue
                if co.type.name in ('Transform', 'RectTransform'): rt = co.read()
                elif co.type.name == 'ParticleSystem':
                    tt = co.read_typetree()
                    init = tt.get('InitialModule', {})
                    info = f" PS(em={tt.get('EmissionModule',{}).get('enabled')} loop={tt.get('looping')} lt={init.get('startLifetime',{}).get('scalar')} sz={init.get('startSize',{}).get('scalar')} sm={tt.get('scalingMode')} delay={tt.get('startDelay',{}).get('scalar')})"
            lp, ls = rt.m_LocalPosition, rt.m_LocalScale
            ap = getattr(rt, 'm_AnchoredPosition', None)
            aps = f" anch=({ap.x:.1f},{ap.y:.1f})" if ap else ""
            if info or depth <= 2 or 'effect' in g.m_Name.lower() or 'fx' in g.m_Name.lower():
                print(f"{'  '*depth}[{g.m_IsActive}] {g.m_Name} pos=({lp.x:.1f},{lp.y:.1f}) sc=({ls.x:.4f},{ls.y:.4f}){aps}{info}")
            for ch in getattr(rt, 'm_Children', []):
                if ch.path_id in ui_objs: d(ui_objs[ch.path_id].read().m_GameObject.path_id, depth+1)
        d(o.path_id)
EOF