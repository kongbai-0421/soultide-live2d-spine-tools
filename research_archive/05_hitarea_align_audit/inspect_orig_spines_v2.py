import os, re, sys
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Check all Backup 原皮 folders and their .skel / .atlas files
backup = r'E:\A灵魂潮汐\备份\spine'
print("=== Backup 原皮 summary ===")
for d in sorted(os.listdir(backup)):
    yp = os.path.join(backup, d, '原皮')
    if os.path.isdir(yp):
        files = [f for f in os.listdir(yp) if f.endswith('.skel') or f.endswith('.skel.json') or f.endswith('.skel.bytes')]
        print(f"  {d}: {files}")

# 2. Check all ui_doll_spineshow + homeland + battle + 03_prefabs/ui/character
for sub in ['homeland', 'battle', 'ui']:
    p = sc.CDN_ROOT / '23_spine' / sub
    abs_list = sorted(p.rglob('*.ab')) if p.exists() else []
    print(f"=== 23_spine/{sub}: {len(abs_list)} ABs ===")
    if sub == 'ui':
        for ab in abs_list:
            print(" ", ab.name)

# 3. Check 20010001..20010055 InitialDress in CfgSoulTable -> CfgDressTable -> CfgSoulResTable -> CfgElementEntityTable
soul_rows = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgSoulTable.lua')
dress_rows = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgDressTable.lua')
res_rows = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgSoulResTable.lua')
ent_rows = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgElementEntityTable.lua')
def get_int(body, f):
    m = re.search(rf'\b{f}\s*=\s*(-?\d+)', body)
    return int(m.group(1)) if m else None
def get_str(body, f):
    m = re.search(rf'\b{f}\s*=\s*"([^"]*)"', body)
    return m.group(1) if m else ''
repo = sc.LuaTableRepo()
s2d = {}
for did, b in dress_rows.items():
    if get_int(b, 'InitialDress') == 1 and did < 34000000:
        sid = get_int(b, 'SoulID')
        srid = get_int(b, 'SoulResID')
        rb = res_rows.get(srid, '')
        eid = get_int(rb, 'EntityId')
        ueid = get_int(rb, 'UIEntityId')
        hlid = get_int(rb, 'HomelandEntityId')
        uspid = get_int(rb, 'UISpineId')
        s2d[sid] = (did, srid, eid, get_str(ent_rows.get(eid,''), 'PrefabName'),
                    ueid, get_str(ent_rows.get(ueid,''), 'PrefabName'),
                    hlid, get_str(ent_rows.get(hlid,''), 'PrefabName'),
                    uspid, get_str(ent_rows.get(uspid,''), 'PrefabName'))
print(f"=== Playable souls with InitialDress <34000000: {len(s2d)} (total soul_rows={len(soul_rows)}) ===")
for sid in sorted(s2d.keys()):
    sb = soul_rows.get(sid, '')
    m = re.search(r'\bName\s*=\s*getI18NValue\((\d+)\)', sb)
    sname = repo.get_i18n(int(m.group(1))) if m else '?'
    t = s2d[sid]
    print(f"  {sid} {sname}: maze={t[3]} | ui={t[5]} | hl={t[7]} | uspine={t[9]}")
