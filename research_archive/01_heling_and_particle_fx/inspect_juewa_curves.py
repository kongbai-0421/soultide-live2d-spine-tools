import json, os, sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

man = json.load(open(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json', 'r', encoding='utf-8'))
j4 = [j for j in man['skins'] if j['skin_key'] == '1703_Juewa_S4'][0]
print("=== 1703_Juewa_S4 detailed node curves ===")
for c in j4['clips']:
    print(f"CLIP {c['clip']} (dur={c['duration']}, warmup={c['warmup']}, fps={c['fps']}):")
    for n in c['nodes']:
        print(f"  NODE {n['name']}: pos={[round(x,1) for x in n['world_pos']]} scale={[round(x,2) for x in n['world_scale']]} rot={[round(x,3) for x in n['world_rot']]}")
        print(f"    loop={n['looping']} dur={n['duration']} delay={n['startDelay']} lt={n['lifetime']} spd={n['speed']} sz={n['size']}")
        print(f"    vel=({n['velX']}, {n['velY']}, {n['velZ']}) colOverLife={n['colOverLife']}")
        print(f"    sizeOverLife={n['sizeOverLife']}")
        print(f"    rot={n['rotation']} rotOverLife={n['rotOverLife']} {n['rotOverLifeCurve']}")
        print(f"    uv={n['uvTiles']} uvMode={n['uvMode']} uvAnim={n['uvAnim']} uvFrameMode={n['uvFrameMode']} uvFrameScalar={n['uvFrameScalar']} uvFrameKeys={n['uvFrameKeys']}")
        print(f"    bursts={n['bursts']} rate={n['rate']} noise={n['noiseEnabled']} rm={n['renderMode']}")

# Check ALL skins in manifest for scale/pos/buggy patterns:
# e.g., check spine_scale_parent_tf overwrite bug, check velocity scalingMode=1 bug, check loop=False in idle, check Animator
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
art_objs = {o.path_id: o for o in art_env.objects}
ui_go = {o.peek_name().lower(): o.path_id for o in ui_env.objects if o.type.name == 'GameObject' and o.peek_name()}

# Check frame-by-frame pixel mass / centroid of 1703_Juewa_S4 idle & fx_9008193
seq_dir = Path(r'E:\A灵魂潮汐\tools\_batch_fx_sequences\1703_Juewa_S4')
for clip in ('idle', 'fx_9008193', 'fx_9008194'):
    for ch in ('normal', 'add'):
        p = seq_dir / clip / ch
        if not p.is_dir(): continue
        fs = sorted(p.glob('frame_*.png'))
        print(f"\n=== Alpha pixel sum per frame for {clip}/{ch} ({len(fs)} frames) ===")
        sums = []
        for i, fp in enumerate(fs):
            if i % max(1, len(fs)//12) == 0 or i == len(fs)-1:
                im = Image.open(fp)
                px = list(im.getdata())
                nz = sum(1 for r,g,b,a in px if a > 5)
                sums.append((i, nz))
        print(" ", sums)
EOF