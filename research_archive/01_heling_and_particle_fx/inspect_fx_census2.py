import json, os
from collections import Counter

d = json.load(open(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json', encoding='utf-8'))
skins = d.get('skins', d) if isinstance(d, dict) else d
if isinstance(skins, dict): skins = list(skins.values())

tex_dir = r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures'

for s in skins:
    if s.get('skin_key') == '4301_HeLing_S2':
        print("=== 4301_HeLing_S2 ALL 10 NODES ===")
        for c in s['clips']:
            print(f"\nCLIP {c['clip']} (dur={c['duration']}):")
            for n in c['nodes']:
                tn = n.get('texName', '')
                # find texture file size
                tpath = os.path.join(tex_dir, tn + '.png')
                tsize = os.path.getsize(tpath) if os.path.exists(tpath) else -1
                print(f"  {n['name']:10s} | tex={tn:18s} ({tsize//1024 if tsize>=0 else -1:4d}KB) | add={str(n.get('isAdditive')):5s} | renderMode={n.get('renderMode')} | mask={n.get('maskTexName')!r} | mask2={n.get('mask2TexName')!r} | diss={n.get('dissolveTexName')!r} | dist={n.get('distortTexName')!r} | trail={n.get('hasTrailMaterial')} | uvScroll={n.get('uvScroll')[:2]} | maxP={n.get('maxParticles')} rate={n.get('rate')} bursts={len(n.get('bursts',[]))}")
        break

# Fleet-wide census
total = 0
pure_billboard = 0
uv_scroll_only = 0
has_mask = 0
has_dissolve = 0
has_distort = 0
has_trail = 0
has_mesh_rm4 = 0
has_stretched_rm1 = 0
render_modes = Counter()
skins_pure_spine_convertible = 0
skins_with_shader_fx = 0

for s in skins:
    skin_complex = False
    for c in s.get('clips', []):
        for n in c.get('nodes', []):
            total += 1
            rm = n.get('renderMode', 0)
            render_modes[rm] += 1
            m1 = bool(n.get('maskTexName'))
            m2 = bool(n.get('mask2TexName'))
            ds = bool(n.get('dissolveTexName')) or (n.get('dissolve', 0) > 0)
            dt = bool(n.get('distortTexName')) or (n.get('distortStrength', 0) > 0)
            tr = bool(n.get('hasTrailMaterial'))
            uvs = any(abs(x) > 1e-6 for x in (n.get('uvScroll') or []))
            if m1 or m2: has_mask += 1
            if ds: has_dissolve += 1
            if dt: has_distort += 1
            if tr: has_trail += 1
            if rm == 4: has_mesh_rm4 += 1
            if rm == 1: has_stretched_rm1 += 1
            if not (m1 or m2 or ds or dt or tr):
                if uvs: uv_scroll_only += 1
                else: pure_billboard += 1
            else:
                skin_complex = True
    if skin_complex: skins_with_shader_fx += 1
    else: skins_pure_spine_convertible += 1

print(f"\n=== FLEET CENSUS ({len(skins)} skins, {total} nodes) ===")
print(f"  pure_billboard (no mask/dissolve/distort/trail/uvScroll): {pure_billboard}")
print(f"  uv_scroll_only (no mask/dissolve/distort/trail):          {uv_scroll_only}")
print(f"  has_mask: {has_mask}, has_dissolve: {has_dissolve}, has_distort: {has_distort}, has_trail: {has_trail}")
print(f"  renderModes: {dict(render_modes)}")
print(f"  skins with ZERO mask/dissolve/distort/trail: {skins_pure_spine_convertible} / {len(skins)}")
print(f"  skins with at least 1 shader/mask/trail node: {skins_with_shader_fx} / {len(skins)}")
