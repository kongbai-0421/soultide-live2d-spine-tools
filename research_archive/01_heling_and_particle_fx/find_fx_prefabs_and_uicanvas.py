import json, sys
from pathlib import Path

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

repo = bfe.FullI18nRepo()
skins = bfe.build_skin_catalog(repo)
for sk in skins:
    if sk['skin_key'] in ('2002_Ennis_S3', '1202_Virgina_S3', '3501_QingDai_S2', '402_Freesia_S5', '2301_QuLing_S2', '1903_Aurora_S5', '503_Benten_S4', '2001_Ennis_S2'):
        print(sk['skin_key'], 'bg=', sk['bg_prefab'], 'effects=', sk['effect_prefabs'])

art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
art_objs = {o.path_id: o for o in art_env.objects}
art_cont = {k.lower(): v.path_id for k, v in (art_env.container or {}).items()}
art_go = {}
for o in art_env.objects:
    if o.type.name == 'GameObject' and o.peek_name():
        art_go.setdefault(o.peek_name().lower(), []).append(o.path_id)

# Mesh lookup
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
                    e = mr.m_LocalAABB.m_Extent
                    mesh_lookup[(o.assets_file.name, o.path_id)] = (nm, mr.m_VertexData.m_VertexCount, (round(e.x,3), round(e.y,3), round(e.z,3)))
                except Exception:
                    mesh_lookup[(o.assets_file.name, o.path_id)] = (nm, None, None)

def res_mesh(co, psrt):
    mr = psrt.get('m_Mesh', {})
    fid, pid = mr.get('m_FileID', 0), mr.get('m_PathID', 0)
    if pid == 0: return 'NONE'
    af = co.assets_file
    cab = af.name if fid == 0 else (Path(af.externals[fid-1].path).name if 1 <= fid <= len(af.externals) else '?')
    return mesh_lookup.get((cab, pid), f'EXT({cab},{pid})')

for sk in skins:
    if sk['skin_key'] not in ('2002_Ennis_S3', '1202_Virgina_S3', '3501_QingDai_S2', '402_Freesia_S5'):
        continue
    for eid, pfn in sk['effect_prefabs'].items():
        if eid not in (9008124, 9008114, 9008143, 9008161): continue
        ck = f'assets/03_prefabs/art_prefabs/effect/{pfn.lower()}.prefab'
        gid = art_cont.get(ck) or (art_go.get(Path(pfn).name.lower(), [None])[0])
        print(f'\n*** {sk["skin_key"]} eid={eid} pfn={pfn} gid={gid} ***')
        if not gid: continue
        stack = [(gid, Path(pfn).name)]
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
            lp = tr.get('m_LocalPosition', {}) if tr else {}
            ls = tr.get('m_LocalScale', {}) if tr else {}
            lr = tr.get('m_LocalRotation', {}) if tr else {}
            ps_info = ''
            if ps:
                init = ps['InitialModule']
                minfo = res_mesh(psr_co, psr) if psr and psr.get('m_RenderMode') == 4 else None
                ps_info = f"sm={ps['scalingMode']} maxP={init['maxNumParticles']} sz={init['startSize']['scalar']}(m={init['startSize']['minMaxState']}) sz3d={init['size3D']} szY={init['startSizeY']['scalar']} szMod={ps.get('SizeModule',{}).get('enabled')} rm={psr['m_RenderMode'] if psr else None} mesh={minfo} align={psr.get('m_RenderAlignment') if psr else None}"
            print(f'  [act={go.m_IsActive}] {path}: pos=({lp.get("x",0):.1f},{lp.get("y",0):.1f}) sc=({ls.get("x",1):.3f},{ls.get("y",1):.3f},{ls.get("z",1):.3f}) rot=({lr.get("x",0):.2f},{lr.get("y",0):.2f},{lr.get("z",0):.2f},{lr.get("w",1):.2f}) {ps_info}')
            if tr:
                for ch in tr.get('m_Children', []):
                    cp = ch.get('m_PathID')
                    if cp in art_objs:
                        cgo = art_objs[cp].read_typetree().get('m_GameObject', {}).get('m_PathID')
                        if cgo in art_objs:
                            stack.append((cgo, path + '/' + (art_objs[cgo].peek_name() or '')))

# Also check Canvas / UIRoot prefabs in ui.ab!
print('\n=== UI Root / Window / CanvasScaler in ui.ab ===')
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
for o in ui_env.objects:
    if o.type.name == 'CanvasScaler':
        cs = o.read_typetree()
        gp = cs.get('m_GameObject', {}).get('m_PathID')
        gnm = ui_objs[gp].peek_name() if gp in ui_objs else ''
        if any(k in gnm.lower() for k in ('ui', 'root', 'home', 'girl', 'dress', 'main', 'show', 'bg')):
            print(f'  [ui.ab] {gnm} Scaler: mode={cs.get("m_UiScaleMode")} res={cs.get("m_ReferenceResolution")} match={cs.get("m_MatchWidthOrHeight")} ppu={cs.get("m_ReferencePixelsPerUnit")}')
    elif o.type.name == 'GameObject' and any(k in (o.peek_name() or '').lower() for k in ('uiroot', 'uicanvas', 'mainui')):
        print('  [ui.ab GO]', o.peek_name())
