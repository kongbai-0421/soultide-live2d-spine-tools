import json
d = json.load(open(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json', encoding='utf-8'))
skins = d.get('skins', d) if isinstance(d, dict) else d
for s in (skins.values() if isinstance(skins, dict) else skins):
    if s.get('skin_key') == '4301_HeLing_S2':
        for c in s['clips']:
            print(f"=== CLIP: {c['clip']} (layer={c['layer']}, dur={c['duration']}, nodes={len(c['nodes'])}) ===")
            for i, n in enumerate(c['nodes']):
                print(f"  [{i}] name={n['name']} maxP={n['maxParticles']} rate={n['rate']} bursts={len(n.get('bursts',[]))} mat={n.get('matName')}")
                mkeys = {k: v for k, v in n.items() if any(w in k.lower() for w in ['mat','tex','shader','uv','scroll','distort','dissolve','blend','mesh','render','speed','vel','rot','noise','size','shape','col'])}
                # prune null/false/0
                clean = {}
                for k, v in mkeys.items():
                    if v in (None, False, 0, 0.0, '', []): continue
                    if isinstance(v, dict) and v.get('scalar') == 0 and not v.get('keys'): continue
                    clean[k] = v
                print("      ", json.dumps(clean, ensure_ascii=False)[:600])
