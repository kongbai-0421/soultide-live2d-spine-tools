import json
man = json.load(open(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json', 'r', encoding='utf-8'))
print("=== FX_* clips whose nodes ALL or mostly fall outside canvas ===")
for sk in man['skins']:
    cw, ch = sk['canvas_w'], sk['canvas_h']
    cx, cy = sk['cam_x'], sk['cam_y']
    for c in sk['clips']:
        oob_nodes = []
        for n in c['nodes']:
            dx = n['world_pos'][0] - cx
            dy = n['world_pos'][1] - cy
            if abs(dx) > cw * 0.65 or abs(dy) > ch * 0.65:
                oob_nodes.append((n['name'], round(dx,1), round(dy,1), round(n['world_scale'][0],2)))
        if oob_nodes:
            print(f"  {sk['skin_key']} {c['clip']} (canvas={cw}x{ch}): {len(oob_nodes)}/{len(c['nodes'])} oob -> {oob_nodes[:3]}")
EOF