import sys, re
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Check RectTransform anchorMin/Max & localPos vs anchoredPos
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
art_objs = {o.path_id: o for o in art_env.objects}
art_c = {k.lower(): v.path_id for k, v in (art_env.container or {}).items()}
for p in ['assets/03_prefabs/art_prefabs/effect/fx_ui/fx_freesia_s5_background_touch01.prefab',
          'assets/03_prefabs/art_prefabs/effect/fx_ui/juewa_s4_background_touch2.prefab',
          'assets/03_prefabs/art_prefabs/effect/fx_ui/juewa_s4_background_chat.prefab',
          'assets/03_prefabs/art_prefabs/effect/fx_ui/virgina_s3_dress01.prefab']:
    gid = art_c[p]
    print('===', p.split('/')[-1], '===')
    def d(g, depth=0):
        go = art_objs[g].read()
        for cr in go.m_Component:
            co = art_objs[cr.component.path_id]
            if co.type.name in ('Transform','RectTransform'):
                rt = co.read()
                pad = '  ' * depth
                if co.type.name == 'RectTransform':
                    print(f'{pad}{go.m_Name}: pos=({rt.m_LocalPosition.x:.1f},{rt.m_LocalPosition.y:.1f}) anch=({rt.m_AnchoredPosition.x:.1f},{rt.m_AnchoredPosition.y:.1f}) amin=({rt.m_AnchorMin.x},{rt.m_AnchorMin.y}) amax=({rt.m_AnchorMax.x},{rt.m_AnchorMax.y}) sc=({rt.m_LocalScale.x:.3f},{rt.m_LocalScale.y:.3f})')
                else:
                    print(f'{pad}{go.m_Name} (TF): pos=({rt.m_LocalPosition.x:.1f},{rt.m_LocalPosition.y:.1f}) sc=({rt.m_LocalScale.x:.3f},{rt.m_LocalScale.y:.3f})')
                for ch in rt.m_Children:
                    d(art_objs[ch.path_id].read().m_GameObject.path_id, depth+1)
                break
    d(gid)

# 2. Check ALL characters with CfgSoulTable & 黛安娜
repo = sc.LuaTableRepo()
s_tbl = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgSoulTable.lua')
print("\n=== Characters with ID >= 20010045 or 黛 ===")
for sid, b in sorted(s_tbl.items()):
    m = re.search(r'Name\s*=\s*getI18NValue\((\d+)\)', b)
    nm = repo.get_i18n(int(m.group(1))) if m else ''
    if nm and ('第' not in nm) and (sid >= 20010045 or '黛' in nm):
        m2 = re.search(r'SoulHead\s*=\s*"([^"]+)"', b)
        slug = m2.group(1).split('/')[-1].replace('.png','') if m2 else ''
        print(' ', sid, nm, slug)
EOF