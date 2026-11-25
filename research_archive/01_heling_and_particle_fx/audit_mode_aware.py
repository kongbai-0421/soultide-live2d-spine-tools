import json
from pathlib import Path

man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))

def curve_hi(c):
    if not c:
        return 1.0
    m = c.get('mode', 0)
    sc = abs(float(c.get('scalar', 1.0)))
    mn = abs(float(c.get('minScalar', 1.0)))
    if m == 0:
        return sc
    if m == 3:
        return max(sc, mn)
    ks = c.get('keys', [])
    if ks:
        mx = max(abs(float(k.get('v', 1.0))) for k in ks)
        return sc * mx if sc > 1e-6 else mx
    return sc

true_giants = []
sm1_nodes = []
tint_low = []
for sk in man['skins']:
    cw, ch = sk['canvas_w'], sk['canvas_h']
    for c in sk['clips']:
        for n in c['nodes']:
            ws = n['world_scale']
            if n['size3D']:
                vx = curve_hi(n['sizeX'])
                vy = curve_hi(n['sizeY'])
                eff = max(vx * abs(ws[0]), vy * abs(ws[1]))
                sz_desc = f'3D({vx:.1f},{vy:.1f})'
            else:
                s = curve_hi(n['size'])
                eff = s * max(abs(ws[0]), abs(ws[1]))
                sz_desc = f'{s:.1f}'
            if n['scalingMode'] == 1:
                sm1_nodes.append((sk['skin_key'], c['clip'], n['name'], round(eff, 1), sz_desc, [round(x, 2) for x in ws], n['texName']))
            if eff > cw * 1.1:
                true_giants.append((sk['skin_key'], c['clip'], n['name'], round(eff, 1), sz_desc, [round(x, 2) for x in ws], f"sm={n['scalingMode']}", f"rm={n['renderMode']}", n['texName']))
            if float(n.get('tintMultiplier', 1.0)) < 0.99:
                tint_low.append((sk['skin_key'], c['clip'], n['name'], n['matName'], n.get('tintMultiplier'), n.get('tint')))

print(f'TRUE giants (mode-aware eff_px > 1.1*cw): {len(true_giants)}')
for r in true_giants:
    print('  GIANT:', r)
print(f'\nscalingMode==1 nodes ({len(sm1_nodes)}): sorted top 35 by eff_px:')
for r in sorted(sm1_nodes, key=lambda x: -x[3])[:35]:
    print('  SM1:', r)
print(f'\ntintMultiplier < 1.0 nodes: {len(tint_low)}')
for r in tint_low[:20]:
    print('  LOW_TINT:', r)
