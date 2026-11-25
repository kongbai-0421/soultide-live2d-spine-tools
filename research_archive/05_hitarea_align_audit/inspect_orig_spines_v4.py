import os, sys, json
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Inspect backup 原皮 example cleanly
for ch in ['九华', '克洛托', '欧若拉', '爱莉莎', '密丝特']:
    yp = os.path.join(r'E:\A灵魂潮汐\备份\spine', ch, '原皮')
    files = os.listdir(yp)
    cfg = json.load(open(os.path.join(yp, '.config.json'), 'r', encoding='utf-8'))
    skels = [f for f in files if f.endswith('.skel.json')]
    if skels:
        raw = open(os.path.join(yp, skels[0]), 'rb').read()
        print(f'Backup 原皮 [{ch}]: skel={skels[0]} is_json={raw[:1]==b"{"} bytes={len(raw)}, motions={list(cfg.get("motions", {}).keys())}')
        print(f'  cfg skeleton={cfg.get("skeleton")} opts={cfg.get("options")} sample_mtn={list(cfg.get("motions", {}).items())[:2]}')

# 2. Check existing Spine output dir character count and skins
sp_out = r'E:\A灵魂潮汐\Live2D与Spine模型\spine'
l2d_out = r'E:\A灵魂潮汐\Live2D与Spine模型\live2d'
sp_chars = sorted(os.listdir(sp_out))
l2d_chars = sorted(os.listdir(l2d_out))
print(f'Output spine chars: {len(sp_chars)}, Output live2d chars: {len(l2d_chars)}')
l2d_yp = [c for c in l2d_chars if os.path.isdir(os.path.join(l2d_out, c, '原皮'))]
sp_yp = [c for c in sp_chars if os.path.isdir(os.path.join(sp_out, c, '原皮'))]
print(f'Output live2d chars with 原皮: {len(l2d_yp)}, Output spine chars with 原皮: {len(sp_yp)}')
missing_sp_chars = set(l2d_yp) - set(sp_chars)
print('Chars in live2d/原皮 not in spine chars:', sorted(missing_sp_chars))
print('Backup chars count:', len([d for d in os.listdir(r'E:\A灵魂潮汐\备份\spine') if os.path.isdir(os.path.join(r'E:\A灵魂潮汐\备份\spine', d, '原皮'))]))
EOF