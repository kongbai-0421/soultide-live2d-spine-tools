import os, sys, json
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

repo = bfe.FullI18nRepo()
catalog = bfe.build_skin_catalog(repo)
print('catalog count:', len(catalog))
j4 = [s for s in catalog if 'Juewa_S4' in s.get('skin_key', '') or '宇宙恋曲' in s.get('dress_name', '')][0]
print('1703_Juewa_S4 catalog:', json.dumps(j4, ensure_ascii=False, indent=2))

# Inspect BgPrefab AB and any Effect prefabs
ab_rel = j4.get('bg_ab') or j4.get('bg_prefab_ab')
print('All manifest or inspector functions in bfe:', [x for x in dir(bfe) if not x.startswith('_')])
EOF