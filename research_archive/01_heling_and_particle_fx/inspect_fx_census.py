import json, os

d = json.load(open(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json', encoding='utf-8'))
skins = d.get('skins', d) if isinstance(d, dict) else d
if isinstance(skins, dict): skins = list(skins.values())

# 1. Full detail of 4301_HeLing_S2 materials & textures
for s in skins:
    if s.get('skin_key') == '4301_HeLing_S2':
        print("=== 4301_HeLing_S2 FULL MATERIAL / SHADER DETAILS ===")
        for c in s['clips']:
            print(f"\nCLIP {c['clip']}:")
            for n in c['nodes']:
                tex_keys = {k: v for k, v in n.items() if k in (
                    'name','matName','shader','blend','renderMode','meshPath','mainTex','maskTex','noiseTex',
                    'mainTexST','maskTexST','noiseTexST','tintColor','color','alpha','emissionColor',
                    'uvSpeed','uvScroll','uSpeed','vSpeed','maskSpeed','noiseSpeed','distort','dissolve',
                    'customData','useCustomData','isAdditive','blendMode','props','floatProps','vecProps','texProps'
                ) or 'tex' in k.lower() or 'shader' in k.lower() or 'mat' in k.lower() or 'speed' in k.lower() or 'scroll' in k.lower() or 'blend' in k.lower() or 'distort' in k.lower() or 'dissolve' in k.lower() or 'mask' in k.lower() or 'prop' in k.lower()}
                print(" ", n['name'], "=>", json.dumps(tex_keys, ensure_ascii=False))
        break

# 2. Fleet-wide shader/feature census across all skins
from collections import Counter
shaders = Counter()
has_mask = 0
has_noise = 0
has_mesh = 0
total_nodes = 0
for s in skins:
    for c in s.get('clips', []):
        for n in c.get('nodes', []):
            total_nodes += 1
            shaders[n.get('shaderName') or n.get('shader') or 'unknown'] += 1
            if n.get('maskTex') or n.get('maskTexPath'): has_mask += 1
            if n.get('noiseTex') or n.get('noiseTexPath'): has_noise += 1
            if n.get('meshPath'): has_mesh += 1

print(f"\n=== FLEET FX CENSUS: {len(skins)} skins, {total_nodes} nodes ===")
print(f"has_mask={has_mask}, has_noise={has_noise}, has_mesh={has_mesh}")
for k, v in shaders.most_common(20):
    print(f"  {v:4d}  {k}")
