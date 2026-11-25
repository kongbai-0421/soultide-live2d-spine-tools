import json, os, re, glob, sys
from pathlib import Path
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))

# 1. Check Unity logs for ANY warnings/errors/missing textures/shaders
print("=== 1. Unity Chunk Log Warnings/Errors ===")
log_root = Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity')
for lp in sorted(log_root.glob('batch_fx_unity_chunk_*.log')):
    lines = lp.read_text(encoding='utf-8', errors='replace').splitlines()
    warns = [l for l in lines if 'BatchFxRecorder' in l and ('Warning' in l or 'Missing' in l or 'ERROR' in l)]
    print(f"  {lp.name}: warnings/errors={len(warns)}")
    for w in warns[:15]: print("   ", w)

# 2. Inspect custom shaders in SoulTideBatchFxUnity
print("\n=== 2. Unity Shaders in SoulTideBatchFxUnity ===")
for sp in sorted((log_root / 'Assets').rglob('*.shader')):
    print(f"--- {sp.name} ---")
    print(sp.read_text(encoding='utf-8', errors='replace'))

# 3. Audit Particle Sizes, RenderModes, Additive vs Alpha, Masks, Tint, ScaleMode across all 101 skins
print("\n=== 3. Particle Size & Shader/Material Audit across 101 skins ===")
giant_nodes = []
tiny_nodes = []
mask_nodes = []
weird_tint = []
render_modes = {}
shaders_used = {}
max_scale1 = []
uv_non_square = []

for sk in man['skins']:
    cw, ch = sk['canvas_w'], sk['canvas_h']
    for c in sk['clips']:
        for n in c['nodes']:
            rm = n.get('renderMode', 0)
            render_modes[rm] = render_modes.get(rm, 0) + 1
            ws = n.get('world_scale', [1, 1, 1])
            sc_max = max(abs(ws[0]), abs(ws[1]))
            sz = n.get('size', {})
            sz_hi = max(abs(float(sz.get('scalar', 1))), abs(float(sz.get('minScalar', 1))))
            eff_px = sz_hi * sc_max
            # Estimate pixel coverage (also check size3D)
            if n.get('size3D'):
                sx = max(abs(n['sizeX'].get('scalar',1)), abs(n['sizeX'].get('minScalar',1))) * abs(ws[0])
                sy = max(abs(n['sizeY'].get('scalar',1)), abs(n['sizeY'].get('minScalar',1))) * abs(ws[1])
                eff_px = max(sx, sy)
            if eff_px > cw * 1.1:
                giant_nodes.append((sk['skin_key'], c['clip'], n['name'], round(eff_px,1), round(sz_hi,3), round(sc_max,2), n['scalingMode'], n['texName'], n['isAdditive']))
            elif eff_px < 1.5 and n.get('renderMode', 0) != 5:
                tiny_nodes.append((sk['skin_key'], c['clip'], n['name'], round(eff_px,3), round(sz_hi,3), round(sc_max,3), n['scalingMode'], n['texName']))
            if n.get('maskTexName'):
                mask_nodes.append((sk['skin_key'], c['clip'], n['name'], n['matName'], n['texName'], n['maskTexName'], n['isAdditive'], n.get('maskScale'), n.get('maskOffset')))
            t = n.get('tint', {})
            tm = n.get('tintMultiplier', 1.0)
            if max(t.get('r',0), t.get('g',0), t.get('b',0)) < 0.05 or t.get('a', 1) < 0.05:
                weird_tint.append((sk['skin_key'], c['clip'], n['name'], t, tm))

print("RenderModes:", render_modes)
print(f"Giant nodes (eff_px > 1.1*cw): {len(giant_nodes)}")
for x in giant_nodes[:25]: print(" ", x)
print(f"Tiny nodes (eff_px < 1.5px): {len(tiny_nodes)}")
for x in tiny_nodes[:25]: print(" ", x)
print(f"MaskTex nodes: {len(mask_nodes)}")
for x in mask_nodes[:25]: print(" ", x)
print(f"Near-zero tint nodes: {len(weird_tint)}")
for x in weird_tint[:15]: print(" ", x)

# 4. Inspect FX atlas page counts & empty FX check across built Spine packages
print("\n=== 4. Built FX Submodels Audit ===")
sp_root = Path(r'E:\A灵魂潮汐\Live2D与Spine模型\spine')
big_fx_pages = []
empty_fx = []
all_fx_cnt = 0
for cfg_p in sorted(sp_root.glob('*/*/submodels/fx_*/.config.json')):
    all_fx_cnt += 1
    sdir = cfg_p.parent
    c = json.loads(cfg_p.read_text(encoding='utf-8'))
    pages = len(c['atlases'][0]['textures'])
    atlas_txt = (sdir / c['atlases'][0]['atlas']).read_text(encoding='utf-8')
    if 'fx_empty' in atlas_txt:
        empty_fx.append(str(sdir.relative_to(sp_root)))
    if pages >= 30:
        big_fx_pages.append((str(sdir.relative_to(sp_root)), pages))
print(f"Total built fx_* submodels={all_fx_cnt}, empty_fx={empty_fx}, pages>=30 ({len(big_fx_pages)}): {big_fx_pages[:15]}")
EOF