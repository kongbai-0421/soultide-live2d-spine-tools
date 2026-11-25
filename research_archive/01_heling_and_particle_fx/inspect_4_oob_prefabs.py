import sys
from pathlib import Path
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
art_objs = {o.path_id: o for o in art_env.objects}
art_c = {k.lower(): v.path_id for k, v in (art_env.container or {}).items()}
ui_go = {o.peek_name().lower(): o.path_id for o in ui_env.objects if o.type.name == 'GameObject' and o.peek_name()}
art_go = {o.peek_name().lower(): o.path_id for o in art_env.objects if o.type.name == 'GameObject' and o.peek_name()}

def dump(objs, gid, d=0, maxd=5):
    go = objs[gid].read()
    rt = None
    ps = ''
    for cr in go.m_Component:
        co = objs.get(cr.component.path_id)
        if not co: continue
        if co.type.name in ('Transform','RectTransform'): rt = co.read()
        elif co.type.name == 'ParticleSystem':
            tt = co.read_typetree()
            sh = tt.get('ShapeModule', {})
            vel = tt.get('VelocityModule', {})
            ps = f" PS(em={tt.get('EmissionModule',{}).get('enabled')} dur={tt.get('lengthInSec')} lt={tt.get('InitialModule',{}).get('startLifetime',{}).get('scalar')} spd={tt.get('InitialModule',{}).get('startSpeed',{}).get('scalar')} sz={tt.get('InitialModule',{}).get('startSize',{}).get('scalar')} vel=({vel.get('x',{}).get('scalar')},{vel.get('y',{}).get('scalar')}) sm={tt.get('scalingMode')} box={sh.get('m_Scale')})"
    lp, ls = rt.m_LocalPosition, rt.m_LocalScale
    ap = getattr(rt, 'm_AnchoredPosition', None)
    ap_s = f"anch=({ap.x:.1f},{ap.y:.1f})" if ap else ""
    print(f"{'  '*d}[{go.m_IsActive}] {go.m_Name} pos=({lp.x:.1f},{lp.y:.1f}) sc=({ls.x:.3f},{ls.y:.3f}) {ap_s}{ps}")
    if d < maxd:
        for ch in getattr(rt, 'm_Children', []):
            if ch.path_id in objs: dump(objs, objs[ch.path_id].read().m_GameObject.path_id, d+1, maxd)

for name, objs, dct in [
    ('assets/03_prefabs/art_prefabs/effect/fx_ui/fx_freesia_s5_background_touch01.prefab', art_objs, art_c),
    ('assets/03_prefabs/art_prefabs/effect/fx_ui/juewa_s2_dress01.prefab', art_objs, art_c),
    ('juewa_s2_background', ui_objs, ui_go),
    ('heling_s2_background', ui_objs, ui_go),
]:
    gid = dct.get(name)
    print(f"\n=== {name} (gid={gid}) ===")
    if gid: dump(objs, gid)
EOF