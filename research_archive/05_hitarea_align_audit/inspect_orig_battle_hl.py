import os, sys, json
from pathlib import Path
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# Check ALL 55 chars in Live2D vs Spine vs 备份\spine vs 23_spine
l2d_dir = Path(r'E:\A灵魂潮汐\Live2D与Spine模型\live2d')
sp_dir = Path(r'E:\A灵魂潮汐\Live2D与Spine模型\spine')
bk_dir = Path(r'E:\A灵魂潮汐\备份\spine')

# Collect all 23_spine/battle Dress_01_BattleHead and homeland and ui_doll_spineshow
battle_map = {}
for ab in sorted((sc.CDN_ROOT / '23_spine' / 'battle').rglob('*.ab')):
    env = sc.load_ab(ab)
    for k in (env.container or {}).keys():
        if k.endswith('.skel.bytes'):
            battle_map[Path(k).name[:-len('.skel.bytes')].lower()] = (ab.name, k)

hl_map = {}
for ab in sorted((sc.CDN_ROOT / '23_spine' / 'homeland').rglob('*.ab')):
    env = sc.load_ab(ab)
    for k in (env.container or {}).keys():
        if k.endswith('.skel.bytes'):
            hl_map[Path(k).name[:-len('.skel.bytes')].lower()] = (ab.name, k)

print("battle_map count:", len(battle_map), "hl_map count:", len(hl_map))
# Print sample hl_map entries
print("hl samples:", sorted(hl_map.keys())[:15])
# Check 黛安娜 (Diane?) or character #55 in battle_map & hl_map
print("battle entries not in Dress_02+:", sorted([k for k in battle_map if '_01_' in k or 'battlehead' in k and '_02' not in k and '_03' not in k and '_04' not in k and '_05' not in k])[:20])
for probe in ['dianna', 'diana', 'daianna', 'silenus', 'truda', 'ruby', 'joan', 'antonina', 'haliva', 'sbe']:
    m1 = [k for k in battle_map if probe in k]
    m2 = [k for k in hl_map if probe in k]
    if m1 or m2:
        print(f"probe '{probe}': battle={m1}, hl={m2}")
EOF