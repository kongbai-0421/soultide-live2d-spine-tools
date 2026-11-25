import json
from pathlib import Path

txt = Path(r'.\_scratch\.system_generated\steps\4459\output.txt').read_text(encoding='utf-8', errors='replace').splitlines()
pids = [
    '9076621251284227344', '1476093635197393937', '-1075113292880553162',
    '-5371216518145074825', '-2882234646681408847', '-945509343750945775',
    '5389071715300839937', '8665360252727739062', '8829493088806448665',
    '-7665262404106375586', '2843555733212822540', '2430647832406757683'
]
print('=== Resolved Shader PIDs ===')
for i, l in enumerate(txt):
    if any(p in l for p in pids):
        print(l)
        if i + 1 < len(txt) and 'props:' in txt[i + 1]:
            print(txt[i + 1])

print('\n=== Empty & Suspect FX Nodes Detail ===')
man = json.loads(Path(r'E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json').read_text(encoding='utf-8'))
targets = {
    ('402_Freesia_S5', 'fx_9008161'),
    ('603_Asuna_S8', 'idle'),
    ('2301_QuLing_S2', 'idle'),
    ('3501_QingDai_S2', 'fx_9008143'),
    ('1202_Virgina_S3', 'fx_9008114'),
    ('2002_Ennis_S3', 'fx_9008124'),
}
for sk in man['skins']:
    for c in sk['clips']:
        if (sk['skin_key'], c['clip']) in targets:
            cw, ch = sk['canvas_w'], sk['canvas_h']
            print(f"[{sk['skin_key']} {c['clip']}] ({cw}x{ch})")
            for n in c['nodes']:
                sz = n.get('size', {})
                print(
                    f"  {n['name']}: add={n.get('additive')} rm={n.get('renderMode')} sm={n.get('scalingMode')} "
                    f"tex={n.get('texName')} mask={n.get('maskTexName')} mat={n.get('matName')} "
                    f"pos={n.get('pos')} ws={n.get('world_scale')} sz=(m={sz.get('mode')},sc={sz.get('scalar')},min={sz.get('minScalar')}) "
                    f"sz3d={n.get('size3D')} szY={n.get('sizeY',{}).get('scalar')} rate={n.get('emissionRate')} bursts={n.get('bursts')} lt={n.get('lifetime')} delay={n.get('startDelay')} col={n.get('startColor')} tint={n.get('tintColor')}"
                )
