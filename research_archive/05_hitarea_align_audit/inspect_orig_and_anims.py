import os, sys, json
from pathlib import Path
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. List ALL 55 Dress_01 / Dress_BattleHead in 23_spine/battle + check Diana / 黛安娜
d01 = []
diana_hits = []
for ab in sorted((sc.CDN_ROOT / '23_spine').rglob('*.ab')):
    env = sc.load_ab(ab)
    for k in (env.container or {}).keys():
        low = k.lower()
        if not k.endswith('.skel.bytes'): continue
        if 'battlehead' in low and ('_01_' in low or '_dress_battlehead' in low):
            d01.append((str(ab.relative_to(sc.CDN_ROOT / '23_spine')), Path(k).name))
        if any(x in low for x in ('diana', 'diane', 'daianna', 'dn', 'dai')):
            diana_hits.append((str(ab.relative_to(sc.CDN_ROOT / '23_spine')), k))
print("d01 count:", len(d01))
for x in sorted(d01, key=lambda t: t[1].lower()):
    print(" ", x[1], "<-", x[0])
print("diana hits in ALL 23_spine:", diana_hits)

# 2. Check the 14 skins with Animator/Animation to see what properties those AnimationClips animate
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
for name, env in [('ui.ab', ui_env), ('art_prefabs.ab', art_env)]:
    clips = [o for o in env.objects if o.type.name == 'AnimationClip']
    print(f"\n{name} total AnimationClips: {len(clips)}")
    for c in clips:
        nm = (c.peek_name() or '').lower()
        if any(k in nm for k in ('juewa', 'clotho', 'qingdai', 'benten', 'silenus', 'dreizehn', 'haliva', 'clarice', 'aria', 'aoling', 'sakuya', 'mist', 'alisa', 'asuna', 'nicolette')):
            d = c.read_typetree()
            paths = list({fc.get('path','') + ':' + fc.get('attribute','') for fc in d.get('m_FloatCurves', [])})[:6]
            ppaths = [pc.get('path','') for pc in d.get('m_PositionCurves', [])][:4]
            print(f"  {c.peek_name()} (wrap={d.get('m_WrapMode')}): floats={paths}, pos={ppaths}")
EOF