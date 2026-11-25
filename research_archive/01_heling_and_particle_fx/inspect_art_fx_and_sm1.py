import json, sys
from pathlib import Path

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_objs = {o.path_id: o for o in art_env.objects}
ui_objs = {o.path_id: o for o in ui_env.objects}

# 1. Inspect fx_9008124, fx_9008114, fx_9008143, fx_9008161 using exact GO name + container
print('=== 1. Effect Prefabs in art_prefabs.ab ===')
art_go = {}
for o in art_env.objects:
    if o.type.name == 'GameObject':
        nm = (o.peek_name() or '').lower()
        if nm in ('fx_9008124', 'fx_9008114', 'fx_9008143', 'fx_9008161'):
            art_go.setdefault(nm, []).append(o.path_id)
print('Found GOs:', art_go)
for ck, cv in (art_env.container or {}).items():
    if any(x in ck.lower() for x in ('9008124', '9008114', '9008143', '9008161')):
        print('  container:', ck, cv.path_id)

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

for nm, gids in art_go.items():
    for gid in gids[:1]:
        print(f'\n*** {nm} (gid={gid}) ***')
        stack = [(gid, nm)]
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
            if ps or cid == gid:
                lp = tr.get('m_LocalPosition', {}) if tr else {}
                ls = tr.get('m_LocalScale', {}) if tr else {}
                lr = tr.get('m_LocalRotation', {}) if tr else {}
                ps_info = ''
                if ps:
                    init = ps['InitialModule']
                    minfo = res_mesh(psr_co, psr) if psr and psr.get('m_RenderMode') == 4 else None
                    ps_info = f"sm={ps['scalingMode']} maxP={init['maxNumParticles']} sz={init['startSize']['scalar']}(m={init['startSize']['minMaxState']}) sz3d={init['size3D']} szY={init['startSizeY']['scalar']} rm={psr['m_RenderMode'] if psr else None} mesh={minfo} align={psr.get('m_RenderAlignment') if psr else None}"
                print(f'  [act={go.m_IsActive}] {path}: pos=({lp.get("x",0):.1f},{lp.get("y",0):.1f}) sc=({ls.get("x",1):.3f},{ls.get("y",1):.3f},{ls.get("z",1):.3f}) {ps_info}')
            if tr:
                for ch in tr.get('m_Children', []):
                    cp = ch.get('m_PathID')
                    if cp in art_objs:
                        cgo = art_objs[cp].read_typetree().get('m_GameObject', {}).get('m_PathID')
                        if cgo in art_objs:
                            stack.append((cgo, path + '/' + (art_objs[cgo].peek_name() or '')))

# 2. Check ALL 82 sm==1 nodes in manifest: idle vs fx_*, lsc, startSize, texture, shapeRadius
print('\n=== 2. Analyze ALL sm==1 nodes in manifest (raw lsc vs canvas factor) ===')
man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))
for sk in man['skins']:
    for c in sk['clips']:
        for n in c['nodes']:
            if n['scalingMode'] == 1:
                ws = n['world_scale']
                lsc = [round(x/100.0, 4) for x in ws]
                sz_s = n['sizeX']['scalar'] if n['size3D'] else n['size']['scalar']
                print(f"  {sk['skin_key']} {c['clip']} '{n['name']}': lsc={lsc} sz={sz_s:.2f} (100x={sz_s*ws[0]:.0f}, 37.5x={sz_s*lsc[0]*37.5:.0f}, 1x={sz_s*lsc[0]:.1f}) sh={n['shapeType']}(r={n['shapeRadius']:.1f}) tex={n['texName']} rm={n['renderMode']}")

# 3. Also check ALL meshes used by manifest rm==4 nodes!
print('\n=== 3. Resolved Mesh Extents of ALL rm==4 nodes in manifest ===')
man_rm4 = {}
for sk in man['skins']:
    for c in sk['clips']:
        for n in c['nodes']:
            if n.get('renderMode') == 4:
                man_rm4.setdefault((sk['skin_key'], c['clip'], n['name']), (n['world_scale'], n['size'], n['size3D'], n['sizeY'], n['texName']))
# Map manifest skins to prefab roots to print exact Mesh for every rm==4 manifest node!
for sk in man['skins']:
    bgn = Path(sk['skin_key'].split('_', 1)[1] + '_Background').lower()
    # check idle rm==4
    for c in sk['clips']:
        if any(n.get('renderMode') == 4 for n in c['nodes']):
            rm4s = [n for n in c['nodes'] if n.get('renderMode') == 4]
            if rm4s:
                pass
print(f'Manifest rm==4 node instances: {len(man_rm4)}')

# 4. Also check 01_scenes/girl.ab & 03_prefabs UI root canvases (where dress Background prefabs are mounted in SoulTide!)
print('\n=== 4. Check 01_scenes/*.ab & ui.ab root UI/Home/Girl panels & CanvasScalers ===')
for abp in sorted((sc.CDN_ROOT / '01_scenes').glob('*.ab')):
    env = sc.load_ab(abp)
    objs = {o.path_id: o for o in env.objects}
    for o in env.objects:
        if o.type.name == 'CanvasScaler':
            cs = o.read_typetree()
            gp = cs.get('m_GameObject', {}).get('m_PathID')
            gnm = objs[gp].peek_name() if gp in objs else ''
            print(f'  [{abp.name}] {gnm} Scaler: mode={cs.get("m_UiScaleMode")} res={cs.get("m_ReferenceResolution")} match={cs.get("m_MatchWidthOrHeight")} ppu={cs.get("m_ReferencePixelsPerUnit")}')
        elif o.type.name == 'Canvas':
            cv = o.read_typetree()
            gp = cv.get('m_GameObject', {}).get('m_PathID')
            gnm = objs[gp].peek_name() if gp in objs else ''
            sc_v = None
            for cr in objs[gp].read().m_Component if gp in objs else []:
                co = objs.get(cr.component.path_id)
                if co and co.type.name in ('Transform', 'RectTransform'):
                    ls = co.read_typetree().get('m_LocalScale', {})
                    sc_v = (round(ls.get('x',1),5), round(ls.get('y',1),5))
            print(f'  [{abp.name}] {gnm} Canvas: rm={cv.get("m_RenderMode")} sc={sc_v} pd={cv.get("m_PlaneDistance")}')
