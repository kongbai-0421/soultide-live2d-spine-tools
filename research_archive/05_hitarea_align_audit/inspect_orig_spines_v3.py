import os, sys, json
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Inspect backup 原皮 example (九华, 克洛托, 欧若拉, 爱莉莎)
for ch in ['九华', '克洛托', '欧若拉', '爱莉莎', '密丝特']:
    yp = os.path.join(r'E:\A灵魂潮汐\备份\spine', ch, '原皮')
    files = os.listdir(yp)
    cfg = json.load(open(os.path.join(yp, '.config.json'), 'r', encoding='utf-8'))
    skels = [f for f in files if f.endswith('.skel.json')]
    sj = json.load(open(os.path.join(yp, skels[0]), 'r', encoding='utf-8'))
    print(f'Backup 原皮 [{ch}]: skel={skels[0]}, anims={list(sj.get("animations", {}).keys())}, motions={list(cfg.get("motions", {}).keys())}')

# 2. Compare 23_spine/ui/batch1.ab defaultdress vs 23_spine/battle vs 23_spine/homeland
for sub in ['homeland', 'battle', 'ui']:
    p = sc.CDN_ROOT / '23_spine' / sub
    for ab in sorted(p.rglob('*.ab')):
        env = sc.load_ab(ab)
        names = sorted([n for n in env.container.keys() if n.endswith('.skel.bytes')])
        if sub == 'ui' and ab.name == 'batch1.ab':
            dd = [n for n in names if 'default' in n]
            print(f'23_spine/ui/batch1.ab default/spineshow ({len(dd)}):')
            for d in dd: print(' ', d)
        elif sub != 'ui':
            print(f'23_spine/{sub}/{ab.name}: {len(names)} skels, sample={names[:4]}')
EOF