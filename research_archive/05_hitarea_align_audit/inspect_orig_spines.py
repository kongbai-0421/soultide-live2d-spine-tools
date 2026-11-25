import os, re, sys
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

dress_rows = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgDressTable.lua')
res_rows = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgSoulResTable.lua')
ent_rows = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgElementEntityTable.lua') if (sc.DECOMPILED_DIR / 'CfgElementEntityTable.lua').exists() else {}
soul_rows = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgSoulTable.lua')

print('CfgElementEntityTable rows:', len(ent_rows))
for k in sorted(ent_rows.keys())[:3]:
    print(' ', k, ent_rows[k][:250].replace('\n', ' '))

def get_int(body, field):
    m = re.search(rf'\b{field}\s*=\s*(-?\d+)', body)
    return int(m.group(1)) if m else None
def get_str(body, field):
    m = re.search(rf'\b{field}\s*=\s*"([^"]*)"', body)
    return m.group(1) if m else ''

repo = sc.LuaTableRepo()
init_dresses = []
for did, body in sorted(dress_rows.items()):
    if get_int(body, 'InitialDress') == 1:
        srid = get_int(body, 'SoulResID')
        sid = get_int(body, 'SoulID')
        dshow = get_str(body, 'DressUnlockShow')
        rbody = res_rows.get(srid, '')
        eid = get_int(rbody, 'EntityId')
        ueid = get_int(rbody, 'UIEntityId')
        uspid = get_int(rbody, 'UISpineId')
        sac = get_int(rbody, 'SpineActionControl')
        epref = get_str(ent_rows.get(eid, ''), 'PrefabName')
        uepref = get_str(ent_rows.get(ueid, ''), 'PrefabName')
        usppref = get_str(ent_rows.get(uspid, ''), 'PrefabName')
        # Soul name
        sbody = soul_rows.get(sid, '')
        m_name = re.search(r'\bName\s*=\s*getI18NValue\((\d+)\)', sbody)
        sname = repo.get_i18n(int(m_name.group(1))) if m_name else str(sid)
        init_dresses.append((did, sid, sname, srid, eid, ueid, uspid, sac, epref, uepref, usppref, dshow))

print('InitialDress == 1 count:', len(init_dresses))
for row in init_dresses:
    print(f"did={row[0]} soul={row[1]}({row[2]}) eid={row[4]}({row[8]}) ueid={row[5]}({row[9]}) uspid={row[6]}({row[10]}) sac={row[7]} dshow={row[11]}")
EOF