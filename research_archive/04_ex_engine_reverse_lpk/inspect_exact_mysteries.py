import json, sys, struct
from pathlib import Path
from PIL import Image

sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Inspect _mask02 / extra tex PIDs across ALL ABs + all Meshes for rm==4
tex_pids_to_resolve = {2361147680285149496, 8265507824761893002, -1965075694181762266}
mesh_stats = {}
tex_by_pid = {}
mat_info = {}

man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))

print('=== 1. Check all rm==4 nodes & resolve actual Mesh + resolve extra shader tex props ===')
rm4_nodes = []
for sk in man['skins']:
    for c in sk['clips']:
        for n in c['nodes']:
            if n.get('renderMode') == 4:
                rm4_nodes.append((sk['skin_key'], c['clip'], n['name'], n['matName'], n['texName']))
print(f'Total rm==4 nodes in manifest: {len(rm4_nodes)}')

# Index all Texture2D and Mesh across CDN ABs used by effect/prefabs
mesh_usage = {}
extra_tex_usage = {}
for ab_dir in ('03_prefabs', '14_effect', '15_shader', '02_art'):
    pdir = sc.CDN_ROOT / ab_dir
    if not pdir.exists(): continue
    for ab_p in sorted(pdir.rglob('*.ab')):
        env = sc.load_ab(ab_p)
        objs = {o.path_id: o for o in env.objects}
        for o in env.objects:
            if o.type.name == 'Texture2D' and o.path_id in tex_pids_to_resolve:
                tex_by_pid[o.path_id] = (ab_p.name, o.peek_name(), o.read().image.size)
            elif o.type.name == 'Mesh':
                nm = o.peek_name() or f'mesh_{o.path_id}'
                try:
                    mr = o.read()
                    vcnt = getattr(getattr(mr, 'm_VertexData', None), 'm_VertexCount', None)
                    lb = getattr(mr, 'm_LocalAABB', None)
                    ext = getattr(lb, 'm_Extent', None)
                    ext_s = (round(ext.x, 3), round(ext.y, 3), round(ext.z, 3)) if ext else None
                except Exception as e:
                    vcnt = f'err:{e}'; ext_s = None
                mesh_usage[(o.assets_file.name, o.path_id)] = (ab_p.name, nm, vcnt, ext_s)

print('Resolved _mask02 PIDs:', tex_by_pid)

# Map ParticleSystemRenderer m_Mesh from ui.ab & art_prefabs.ab
for abn in ('ui.ab', 'art_prefabs.ab'):
    env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / abn)
    objs = {o.path_id: o for o in env.objects}
    for o in env.objects:
        if o.type.name == 'ParticleSystemRenderer':
            tt = o.read_typetree()
            if tt.get('m_RenderMode') == 4:
                mr = tt.get('m_Mesh', {})
                fid, pid = mr.get('m_FileID', 0), mr.get('m_PathID', 0)
                gnm = objs[tt.get('m_GameObject', {}).get('m_PathID', 0)].peek_name() if tt.get('m_GameObject', {}).get('m_PathID', 0) in objs else ''
                cab = o.assets_file.name if fid == 0 else (Path(o.assets_file.externals[fid-1].path).name if 1 <= fid <= len(o.assets_file.externals) else '?')
                minfo = mesh_usage.get((cab, pid), f'UNRESOLVED({cab},{pid})')
                k = str(minfo)
                extra_tex_usage.setdefault(k, []).append((abn, gnm))

print(f'\nDistinct rm==4 Mesh assets across ui.ab & art_prefabs.ab: {len(extra_tex_usage)}')
for k, v in sorted(extra_tex_usage.items(), key=lambda x: -len(x[1])):
    print(f'  [{len(v):3d}] {k} | sample GOs={v[:4]}')

# 2. Check Ennis_S3 fx_9008124 an size, rot, uv, render_w/h, and compare frame_0167 pixels!
print('\n=== 2. Ennis_S3 fx_9008124 & QuLing_S2 & QingDai_S2 fx_9008143 raw AB ===')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
art_objs = {o.path_id: o for o in art_env.objects}
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}

def inspect_node(objs, go_name):
    for o in objs.values():
        if o.type.name == 'GameObject' and (o.peek_name() or '') == go_name:
            go = o.read()
            tr = ps = psr = None
            for cr in go.m_Component:
                co = objs.get(cr.component.path_id)
                if not co: continue
                if co.type.name in ('Transform', 'RectTransform'): tr = co.read_typetree()
                elif co.type.name == 'ParticleSystem': ps = co.read_typetree()
                elif co.type.name == 'ParticleSystemRenderer': psr = co.read_typetree()
            if ps:
                print(f'  GO={go_name} pid={o.path_id}: lpos={tr.get("m_LocalPosition")} lrot={tr.get("m_LocalRotation")} lsc={tr.get("m_LocalScale")}')
                init = ps.get('InitialModule', {})
                print(f'    maxP={init.get("maxNumParticles")} sz={init.get("startSize")} sz3D={init.get("size3D")} szY={init.get("startSizeY")} spd={init.get("startSpeed")} delay={ps.get("startDelay")} dur={ps.get("lengthInSec")}')
                print(f'    subM={ps.get("SubModule")} em={ps.get("EmissionModule")} vel={ps.get("VelocityModule")} uv={ps.get("UVModule")}')
                if psr:
                    print(f'    PSR rm={psr.get("m_RenderMode")} mesh={psr.get("m_Mesh")} lenSc={psr.get("m_LengthScale")} velSc={psr.get("m_VelocityScale")} align={psr.get("m_RenderAlignment")} sort={psr.get("m_SortMode")}')

for nm in ('fx_9008124', 'fx_9008114', 'fx_9008143'):
    for gid, obj in art_objs.items():
        if obj.type.name == 'GameObject' and (obj.peek_name() or '') == nm:
            print(f'\n*** Prefab Tree {nm} ***')
            stack = [(gid, nm)]
            while stack:
                cid, path = stack.pop(0)
                go = art_objs[cid].read()
                tr = ps = psr = None
                for cr in go.m_Component:
                    co = art_objs.get(cr.component.path_id)
                    if not co: continue
                    if co.type.name in ('Transform', 'RectTransform'): tr = co.read_typetree()
                    elif co.type.name == 'ParticleSystem': ps = co.read_typetree()
                    elif co.type.name == 'ParticleSystemRenderer': psr = co.read_typetree()
                if ps:
                    init = ps.get('InitialModule', {})
                    print(f'  [act={go.m_IsActive}] {path}: lpos={tr.get("m_LocalPosition")} lsc={tr.get("m_LocalScale")} maxP={init.get("maxNumParticles")} sz={init.get("startSize",{}).get("scalar")} sz3D={init.get("size3D")} szY={init.get("startSizeY",{}).get("scalar")} rm={psr.get("m_RenderMode") if psr else None} mesh={psr.get("m_Mesh") if psr else None}')
                if tr:
                    for ch in tr.get('m_Children', []):
                        cp = ch.get('m_PathID')
                        if cp in art_objs:
                            cgo = art_objs[cp].read_typetree().get('m_GameObject', {}).get('m_PathID')
                            if cgo in art_objs:
                                stack.append((cgo, path + '/' + (art_objs[cgo].peek_name() or '')))

inspect_node(ui_objs, 'water')
