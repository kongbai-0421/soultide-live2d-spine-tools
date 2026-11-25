import json, sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_objs = {o.path_id: o for o in art_env.objects}
ui_objs = {o.path_id: o for o in ui_env.objects}
cont = {k.lower(): v.path_id for k, v in (art_env.container or {}).items()}

# Build mesh lookup from all art/effect/prefab ABs
mesh_lookup = {}
for sub in ('03_prefabs', '14_effect', '02_art'):
    pdir = sc.CDN_ROOT / sub
    if not pdir.exists(): continue
    for abp in sorted(pdir.rglob('*.ab')):
        env = sc.load_ab(abp)
        for o in env.objects:
            if o.type.name == 'Mesh':
                nm = o.peek_name() or f'mesh_{o.path_id}'
                try:
                    mr = o.read()
                    lb = mr.m_LocalAABB
                    e = lb.m_Extent
                    c = lb.m_Center
                    mesh_lookup[(o.assets_file.name, o.path_id)] = (nm, mr.m_VertexData.m_VertexCount, (round(e.x,3), round(e.y,3), round(e.z,3)), (round(c.x,3), round(c.y,3), round(c.z,3)))
                except Exception as ex:
                    mesh_lookup[(o.assets_file.name, o.path_id)] = (nm, f'err:{ex}', None, None)

def resolve_mesh_info(co_comp, psrt):
    mr = psrt.get('m_Mesh', {})
    fid, pid = mr.get('m_FileID', 0), mr.get('m_PathID', 0)
    if pid == 0: return 'NONE'
    af = co_comp.assets_file
    cab = af.name if fid == 0 else (Path(af.externals[fid-1].path).name if 1 <= fid <= len(af.externals) else '?')
    return mesh_lookup.get((cab, pid), f'EXT({cab},{pid})')

print('=== 1. Effect Prefabs: fx_9008124 (Ennis_S3), fx_9008114 (Virgina_S3), fx_9008143 (QingDai_S2), fx_9008161 (Freesia_S5) ===')
for eid in ('fx_9008124', 'fx_9008114', 'fx_9008143', 'fx_9008161'):
    matches = [(k, v) for k, v in cont.items() if eid in k]
    for ck, gid in matches[:1]:
        print(f'\n*** {eid} ({ck}) ***')
        stack = [(gid, eid)]
        while stack:
            cid, path = stack.pop(0)
            go = art_objs[cid].read()
            tr = ps = psr = psr_co = None
            for cr in go.m_Component:
                co = art_objs.get(cr.component.path_id)
                if not co: continue
                if co.type.name in ('Transform', 'RectTransform'): tr = co.read_typetree()
                elif co.type.name == 'ParticleSystem': ps = co.read_typetree()
                elif co.type.name == 'ParticleSystemRenderer': psr_co = co; psr = co.read_typetree()
            if ps:
                init = ps.get('InitialModule', {})
                lp = tr.get('m_LocalPosition', {})
                ls = tr.get('m_LocalScale', {})
                lr = tr.get('m_LocalRotation', {})
                minfo = resolve_mesh_info(psr_co, psr) if psr and psr.get('m_RenderMode') == 4 else None
                print(f'  [act={go.m_IsActive}] {path}: pos=({lp.get("x",0):.1f},{lp.get("y",0):.1f}) sc=({ls.get("x",1):.3f},{ls.get("y",1):.3f},{ls.get("z",1):.3f}) rot=({lr.get("x",0):.2f},{lr.get("y",0):.2f},{lr.get("z",0):.2f},{lr.get("w",1):.2f})')
                print(f'    sm={ps.get("scalingMode")} maxP={init.get("maxNumParticles")} sz={init.get("startSize",{}).get("scalar")} sz3D={init.get("size3D")} szY={init.get("startSizeY",{}).get("scalar")} szZ={init.get("startSizeZ",{}).get("scalar")} rm={psr.get("m_RenderMode") if psr else None} mesh={minfo}')
            if tr:
                for ch in tr.get('m_Children', []):
                    cp = ch.get('m_PathID')
                    if cp in art_objs:
                        cgo = art_objs[cp].read_typetree().get('m_GameObject', {}).get('m_PathID')
                        if cgo in art_objs:
                            stack.append((cgo, path + '/' + (art_objs[cgo].peek_name() or '')))

print('\n=== 2. Check Ennis_S3 & Virgina_S3 Point_Root / FX parent chain in ui.ab ===')
for bgn in ('ennis_s3_background', 'virgina_s3_background', 'benten_s4_background', 'aurora_s5_background', 'quling_s2_background'):
    for gid, o in ui_objs.items():
        if o.type.name == 'GameObject' and (o.peek_name() or '').lower() == bgn:
            print(f'\n*** UI {o.peek_name()} (pid={gid}) ***')
            stack = [(gid, o.peek_name())]
            while stack:
                cid, path = stack.pop(0)
                go = ui_objs[cid].read()
                tr = ps = psr = psr_co = None
                for cr in go.m_Component:
                    co = ui_objs.get(cr.component.path_id)
                    if not co: continue
                    if co.type.name in ('Transform', 'RectTransform'): tr = co.read_typetree()
                    elif co.type.name == 'ParticleSystem': ps = co.read_typetree()
                    elif co.type.name == 'ParticleSystemRenderer': psr_co = co; psr = co.read_typetree()
                ls = tr.get('m_LocalScale', {}) if tr else {}
                if ps or 'point_root' in path.lower() or 'souldress' in path.lower():
                    minfo = resolve_mesh_info(psr_co, psr) if psr and psr.get('m_RenderMode') == 4 else None
                    ps_s = f'sm={ps.get("scalingMode")} sz={ps["InitialModule"]["startSize"]["scalar"]} sz3d={ps["InitialModule"]["size3D"]} rm={psr.get("m_RenderMode")} mesh={minfo}' if ps and psr else ''
                    print(f'  [act={go.m_IsActive}] {path}: lsc=({ls.get("x",1):.4f},{ls.get("y",1):.4f},{ls.get("z",1):.4f}) {ps_s}')
                if tr:
                    for ch in tr.get('m_Children', []):
                        cp = ch.get('m_PathID')
                        if cp in ui_objs:
                            cgo = ui_objs[cp].read_typetree().get('m_GameObject', {}).get('m_PathID')
                            if cgo in ui_objs:
                                stack.append((cgo, path + '/' + (ui_objs[cgo].peek_name() or '')))

# 3. Export 50pct texture previews
tex_dir = Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures')
out_dir = Path(r'.\_scratch\audit_previews')
for tn in ('FX_glow04_01', 'FX_ZC_Mask214', 'FX_ZC_Mask003', 'FX_mask13', 'Fx_cfl_caihongguang_02', 'FX_gra_WL_142'):
    tp = tex_dir / f'{tn}.png'
    if tp.exists():
        im = Image.open(tp).convert('RGBA')
        bg = Image.new('RGBA', im.size, (30, 34, 42, 255))
        # save both composite and alpha channel side by side!
        vis = Image.new('RGB', (im.width * 2, im.height))
        vis.paste(Image.alpha_composite(bg, im).convert('RGB'), (0, 0))
        vis.paste(im.getchannel('A').convert('RGB'), (im.width, 0))
        vis.resize((max(1, vis.width // 2), max(1, vis.height // 2)), Image.Resampling.LANCZOS).save(out_dir / f'tex_{tn}_50pct.jpg', 'JPEG', quality=80)
print('\nSaved texture previews.')
