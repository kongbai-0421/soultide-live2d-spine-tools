import os, sys
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Compare 55 live2d chars vs 55 spine chars vs 54 backup 原皮 chars
sp_chars = set(os.listdir(r'E:\A灵魂潮汐\Live2D与Spine模型\spine'))
l2d_chars = set(os.listdir(r'E:\A灵魂潮汐\Live2D与Spine模型\live2d'))
bk_chars = set(d for d in os.listdir(r'E:\A灵魂潮汐\备份\spine') if os.path.isdir(os.path.join(r'E:\A灵魂潮汐\备份\spine', d, '原皮')))
print('l2d - sp:', sorted(l2d_chars - sp_chars))
print('sp - l2d:', sorted(sp_chars - l2d_chars))
print('l2d - bk_原皮:', sorted(l2d_chars - bk_chars))
print('sp - bk_原皮:', sorted(sp_chars - bk_chars))

# 2. Inspect 23_spine/ui/batch1.ab defaultdress textures/animations/size vs BattleHead
env = sc.load_ab(sc.CDN_ROOT / '23_spine' / 'ui' / 'batch1.ab')
for k, ptr in sorted(env.container.items(), key=lambda kv: kv[0]):
    if 'defaultdress' in k and k.endswith('.skel.bytes'):
        obj = ptr.read()
        s = getattr(obj, 'm_Script', getattr(obj, 'script', b''))
        raw_len = len(s) if s is not None else 0
        print('ui/batch1 defaultdress:', k, 'len=', raw_len)

# 3. Inspect 23_spine/battle all skel names
b_dir = sc.CDN_ROOT / '23_spine' / 'battle'
battle_skels = []
for ab in sorted(b_dir.rglob('*.ab')):
    env = sc.load_ab(ab)
    for k in env.container.keys():
        if k.endswith('.skel.bytes'):
            battle_skels.append((ab.name, k))
print('Total 23_spine/battle .skel.bytes:', len(battle_skels))
dress01 = [x for x in battle_skels if 'dress_01' in x[1].lower() or 'battlehead' in x[1].lower()]
print('Dress_01 / BattleHead in 23_spine/battle:', len(dress01))
for x in sorted(dress01)[:15]:
    print(' ', x)

# 4. Inspect 23_spine/dressspine for any _01 / _s1 / default
d_dir = sc.CDN_ROOT / '23_spine' / 'dressspine'
d01 = []
for ab in sorted(d_dir.rglob('*.ab')):
    env = sc.load_ab(ab)
    for k in env.container.keys():
        if k.endswith('.skel.bytes') and ('_01' in k.lower() or '_s1' in k.lower() or 'default' in k.lower()):
            d01.append((ab.name, k))
print('DressSpine _01/_s1/default:', d01)
EOF