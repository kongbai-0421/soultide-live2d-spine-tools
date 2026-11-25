import os, sys, json
from pathlib import Path
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
from batch_spine_builder import parse_spine38_binary

# 1. Inspect SoulDress_Juewa_04 bounds and root in built package + raw AB
p_dir = Path(r'E:\A灵魂潮汐\Live2D与Spine模型\spine\九华\宇宙恋曲')
raw = (p_dir / 'SoulDress_Juewa_04.skel.json').read_bytes()
parsed = parse_spine38_binary(raw)
print('SoulDress_Juewa_04 parsed bounds:', parsed['bounds'], 'root:', parsed['bones'][0], 'anims:', parsed['anims'])

# Inspect where person UI center lands in 1768x1176 bg_static canvas!
# In batch_fx_exporter layout for Juewa_S4: cam=(0, 73), person=(wx=301.628, wy=-550.18, ui_per_spine=0.5628)
bx, by, bw, bh = parsed['bounds']
p_wx, p_wy, ups = 301.628, -550.18, 0.5628
cam_x, cam_y = 0.0, 73.0
# In UI coords relative to cam center:
cx_ui = p_wx + (bx + bw/2.0) * ups - cam_x
cy_ui = p_wy + (by + bh/2.0) * ups - cam_y
print(f"Juewa girl+panda bbox center rel to canvas center: x={cx_ui:.1f}, y={cy_ui:.1f}, width={bw*ups:.1f}, height={bh*ups:.1f}")
print(f"X range rel to center: [{p_wx + bx*ups - cam_x:.1f}, {p_wx + (bx+bw)*ups - cam_x:.1f}]")
print(f"Y range rel to center: [{p_wy + by*ups - cam_y:.1f}, {p_wy + (by+bh)*ups - cam_y:.1f}]")

# Compare with touch2 glow & paopao:
# Case A (Point_Root=+183.4,-132.8, scale=0.94): glow=(+358, -437), paopao=(+355.6, -482.3)
# Case B (Canvas root anch=(0, 74)): glow=(+185.6, -245), paopao=(+183.0, -293)
print("glow Case A (Point_Root) rel to center:", (358.0 - cam_x, -364.2 - cam_y))
print("glow Case B (Canvas root 0,74) rel to center:", (185.6 - cam_x, (-246.0 + 74.0) - cam_y))

# 2. Check Juewa_S4_Background_touch2 & chat GameObject Components (Canvas? RectTransform? Collider? Script?)
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
art_objs = {o.path_id: o for o in art_env.objects}
for k, ptr in (art_env.container or {}).items():
    if 'juewa_s4_background_' in k.lower():
        go = art_objs[ptr.path_id].read()
        print(f"\nPrefab {k}: components={[art_objs[c.component.path_id].type.name for c in go.m_Component]}")
        for c in go.m_Component:
            co = art_objs[c.component.path_id]
            if co.type.name == 'MonoBehaviour':
                print("  MonoBehaviour:", co.read_typetree())

# 3. Check SoulDress_Juewa_04 in art_prefabs.ab and ui.ab: does Point_Root (50000) appear in ANY Lua / C# MonoBehaviour?
# Check Component on SoulDress_Juewa/Point_Root in ui.ab & art_prefabs.ab
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
for o in ui_env.objects:
    if o.type.name == 'GameObject' and (o.peek_name() or '').lower() == 'juewa_s4_background':
        def find_pr(gid, path=''):
            g = ui_objs[gid].read()
            cur = f"{path}/{g.m_Name}"
            rt = None
            for cr in g.m_Component:
                co = ui_objs.get(cr.component.path_id)
                if not co: continue
                if co.type.name in ('Transform','RectTransform'): rt = co.read()
                elif 'point_root' in g.m_Name.lower() or 'Effect' in g.m_Name:
                    if co.type.name == 'MonoBehaviour':
                        print(f"  Comp on {cur}: {co.read_typetree()}")
            for ch in getattr(rt, 'm_Children', []):
                if ch.path_id in ui_objs: find_pr(ui_objs[ch.path_id].read().m_GameObject.path_id, cur)
        find_pr(o.path_id)
        break
EOF