import os, sys, json
from pathlib import Path
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

# 1. Check art_prefabs SoulDress_* for Colcher_S2, Virgina_S3, Freesia_S5
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_objs = {o.path_id: o for o in art_env.objects}
ui_objs = {o.path_id: o for o in ui_env.objects}
art_c = {k.lower(): v.path_id for k, v in (art_env.container or {}).items()}
ui_go = {o.peek_name().lower(): o.path_id for o in ui_env.objects if o.type.name == 'GameObject' and o.peek_name()}

for k, pid in sorted(art_c.items()):
    if 'dressspine/' in k and any(x in k for x in ('colcher_s2', 'virgina_s3', 'freesia_s5', 'juewa_s4')) and k.endswith('.prefab') and '_bg' not in k and '_bj' not in k and 'unlock' not in k and 'person' not in k:
        print('=== art_prefabs:', k, '===')
        def dump(gid, d=0):
            go = art_objs[gid].read()
            rt = None
            for cr in go.m_Component:
                co = art_objs.get(cr.component.path_id)
                if co and co.type.name in ('Transform', 'RectTransform'): rt = co.read()
            lp, ls = rt.m_LocalPosition, rt.m_LocalScale
            ap = getattr(rt, 'm_AnchoredPosition', None)
            ap_s = f'anch=({ap.x:.1f},{ap.y:.1f})' if ap else ''
            print(f"{'  '*d}[{go.m_IsActive}] {go.m_Name} lpos=({lp.x:.1f},{lp.y:.1f}) lscale=({ls.x:.4f},{ls.y:.4f}) {ap_s}")
            for ch in getattr(rt, 'm_Children', []):
                if ch.path_id in art_objs: dump(art_objs[ch.path_id].read().m_GameObject.path_id, d+1)
        dump(pid)

# 2. Check ALL skins with EffectIds: compare (a) Spine/Point_Root, (b) Canvas-root, (c) SoulDress_X scale, (d) FX_UI coordinates
repo = bfe.FullI18nRepo()
skins = bfe.build_skin_catalog(repo)
art_go = {o.peek_name().lower(): o.path_id for o in art_env.objects if o.type.name == 'GameObject' and o.peek_name()}

print("\n=== EffectId Coordinate Ranges Across All Skins ===")
for sk in skins:
    if not sk['effect_prefabs']: continue
    bgp = Path(sk['bg_prefab']).name.lower()
    objs, bg_gid = (ui_objs, ui_go[bgp]) if bgp in ui_go else (art_objs, art_go[bgp])
    # find Point_Root / Spine_Scale / SoulDress_ / nested Point_Root
    info = []
    def wbg(gid, p=''):
        go = objs[gid].read()
        cur = f'{p}/{go.m_Name}'
        rt = None
        for cr in go.m_Component:
            co = objs.get(cr.component.path_id)
            if co and co.type.name in ('Transform', 'RectTransform'): rt = co.read()
        if any(t in cur.lower() for t in ('point_root', 'spine_scale', 'souldress_')) and '_person' not in cur.lower() and '_bg' not in cur.lower() and '_bj' not in cur.lower():
            lp, ls = rt.m_LocalPosition, rt.m_LocalScale
            ap = getattr(rt, 'm_AnchoredPosition', None)
            x, y = (ap.x, ap.y) if ap else (lp.x, lp.y)
            info.append((go.m_Name, round(x,1), round(y,1), round(ls.x,4), go.m_IsActive))
        for ch in getattr(rt, 'm_Children', []):
            if ch.path_id in objs: wbg(objs[ch.path_id].read().m_GameObject.path_id, cur)
    wbg(bg_gid)

    for eid, pf in sk['effect_prefabs'].items():
        ck = f"assets/03_prefabs/art_prefabs/effect/{pf.lower()}.prefab"
        egid = art_c.get(ck) or art_go.get(Path(pf).name.lower())
        if not egid: continue
        # collect PS max |pos| and root anch
        ego = art_objs[egid].read()
        ert = [art_objs[c.component.path_id].read() for c in ego.m_Component if c.component.path_id in art_objs and art_objs[c.component.path_id].type.name in ('Transform','RectTransform')][0]
        r_ap = getattr(ert, 'm_AnchoredPosition', None)
        rx, ry = (r_ap.x, r_ap.y) if r_ap else (ert.m_LocalPosition.x, ert.m_LocalPosition.y)
        ps_coords = []
        def wfx(gid, px=0, py=0, ps=1):
            g = art_objs[gid].read()
            r = None
            has_ps = False
            for cr in g.m_Component:
                co = art_objs.get(cr.component.path_id)
                if not co: continue
                if co.type.name in ('Transform', 'RectTransform'): r = co.read()
                elif co.type.name == 'ParticleSystem' and co.read_typetree().get('EmissionModule',{}).get('enabled'): has_ps = True
            lp, ls = r.m_LocalPosition, r.m_LocalScale
            ap = getattr(r, 'm_AnchoredPosition', None)
            lx, ly = (ap.x, ap.y) if (ap and (abs(ap.x)>0.01 or abs(ap.y)>0.01)) else (lp.x, lp.y)
            cx, cy, cs = px + lx*ps, py + ly*ps, ps * ls.x
            if has_ps: ps_coords.append((g.m_Name, round(cx,1), round(cy,1), round(cs,2)))
            for ch in getattr(r, 'm_Children', []):
                if ch.path_id in art_objs: wfx(art_objs[ch.path_id].read().m_GameObject.path_id, cx, cy, cs)
        wfx(egid)
        max_xy = max((max(abs(c[1]), abs(c[2])) for c in ps_coords), default=0)
        if max_xy > 1100 or sk['skin_key'] in ('1703_Juewa_S4', '101_Colcher_S2', '1202_Virgina_S3', '402_Freesia_S5', '1903_Aurora_S4'):
            print(f"  {sk['skin_key']} fx_{eid} root=({rx:.1f},{ry:.1f}, s={ert.m_LocalScale.x:.3f}) max|xy|={max_xy:.0f} chain={info} sample_ps={ps_coords[:3]}")
EOF