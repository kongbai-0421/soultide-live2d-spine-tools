import os, sys, json
from pathlib import Path
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

# 1. Inspect SoulSpineCell.lua lines around PlayEffect and PlayRootAnimator
for fp in (sc.DECOMPILED_DIR).rglob('SoulSpineCell.lua'):
    lines = fp.read_text(encoding='utf-8', errors='ignore').splitlines()
    print(f"=== {fp} (total {len(lines)}) ===")
    print('\n'.join(f"{i}: {lines[i-1]}" for i in range(340, min(len(lines)+1, 560))))

# 2. Check exact layout for 1703_Juewa_S4, 1202_Virgina_S3, 101_Colcher_S2, 402_Freesia_S5, 3602_QingHao_S3, 4101_Erinnern_S2, 4501_RubyRose_S2
repo = bfe.FullI18nRepo()
skins = bfe.build_skin_catalog(repo)
idx = bfe.AssetIndexer()
for key in ['1703_Juewa_S4', '1202_Virgina_S3', '101_Colcher_S2', '402_Freesia_S5', '3602_QingHao_S3', '4101_Erinnern_S2', '4501_RubyRose_S2', '1903_Aurora_S4']:
    sk = [s for s in skins if s['skin_key'] == key][0]
    lay = bfe.inspect_bg_prefab_layout(idx, sk)
    print(f"LAYOUT {key}: cam=({lay['cam_x']},{lay['cam_y']}) canvas=({lay['canvas_w']}x{lay['canvas_h']}) person={lay['person']} fx_pr={lay['fx_point_root']}")
EOF