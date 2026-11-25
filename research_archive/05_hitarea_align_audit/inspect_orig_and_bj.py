import os, sys, json
from pathlib import Path
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
from batch_spine_builder import parse_spine38_binary

# 1. Check Juewa_S4 bj_01 / bj_02 & all 109 built spine submodels
p = Path(r'E:\A灵魂潮汐\Live2D与Spine模型\spine\九华\宇宙恋曲\submodels')
for sub in ('bj_01', 'bj_02'):
    cfg = json.loads((p / sub / '.config.json').read_text(encoding='utf-8'))
    raw = (p / sub / cfg['skeleton']).read_bytes()
    parsed = parse_spine38_binary(raw)
    print(f"Juewa_S4 {sub}: opts={cfg['options']} motions={cfg['motions']} bounds={parsed['bounds']} anims={parsed['anims']}")

# 2. Check ALL 55 live2d chars' 原皮 and match against 23_spine/battle and 23_spine/ui defaultdress
l2d_dir = Path(r'E:\A灵魂潮汐\Live2D与Spine模型\live2d')
l2d_chars = sorted([d.name for d in l2d_dir.iterdir() if d.is_dir()])
print(f"\nLive2D chars ({len(l2d_chars)}):", l2d_chars)

# Check what BattleHead / Dress_01 / defaultdress / homeland ABs exist across 23_spine
battle_ab_skels = {}
for ab in sorted((sc.CDN_ROOT / '23_spine' / 'battle').rglob('*.ab')):
    env = sc.load_ab(ab)
    for k in (env.container or {}).keys():
        if k.endswith('.skel.bytes'):
            battle_ab_skels[k.lower()] = (ab.name, k)

# Check any 黛安娜 / Diana anywhere in 23_spine
all_23_hits = []
for ab in sorted((sc.CDN_ROOT / '23_spine').rglob('*.ab')):
    env = sc.load_ab(ab)
    for k in (env.container or {}).keys():
        low = k.lower()
        if any(x in low for x in ('diana', 'diane', 'daianna', 'defaultdress', 'spineshow')):
            all_23_hits.append((str(ab.relative_to(sc.CDN_ROOT / '23_spine')), k))
print("\n23_spine diana/defaultdress/spineshow hits:")
for x in all_23_hits:
    print(" ", x)

# 3. Check a sample BattleHead binary spine bounds & animations
for sample_k in ['assets/23_spine/battle/character/juewa/juewa_dress_01_battlehead.skel.bytes',
                 'assets/23_spine/battle/character/aurora/aurora_dress_01_battlehead.skel.bytes',
                 'assets/23_spine/battle/character/alisa/alisa_dress_01_battlehead.skel.bytes']:
    if sample_k in battle_ab_skels:
        abn, orig_k = battle_ab_skels[sample_k]
        env = sc.load_ab(sc.CDN_ROOT / '23_spine' / 'battle' / abn)
        obj = env.container[orig_k].read()
        raw = obj.m_Script.encode('utf-8', 'surrogateescape')
        parsed = parse_spine38_binary(raw)
        print(f"BattleHead {sample_k}: anims={parsed['anims']} bounds={parsed['bounds']}")

# 4. Check CfgSoulTable -> CfgSoulResTable for 黛安娜 (and all 55 Live2D chars' BattleHead EntityId)
import re
soul_tbl = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgSoulTable.lua')
repo = sc.LuaTableRepo()
for sid, body in sorted(soul_tbl.items()):
    m = re.search(r'Name\s*=\s*getI18NValue\((\d+)\)', body)
    nm = repo.get_i18n(int(m.group(1))) if m else ''
    if '黛' in nm or '安娜' in nm:
        print("Soul match:", sid, nm, body[:300].replace('\n', ' '))
EOF