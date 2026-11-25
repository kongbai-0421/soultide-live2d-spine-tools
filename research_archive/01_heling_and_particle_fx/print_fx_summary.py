import json
from pathlib import Path
spec = json.loads(Path(r".\_scratch\unity_fx_proj\fx_spec.json").read_text("utf-8"))
for clip, data in spec.items():
    print("===", clip, "===")
    for n in data["nodes"]:
        print(f"  {n['name']:15s} pos={[round(x,1) for x in n['world_pos']]} sc={[round(x,3) for x in n['world_scale']]} scaling={n['scalingMode']} size=({n['size']['scalar']},{n['size']['minScalar']}) shape={n['shapeType']}:{n['shapeRadius']}:{[round(x,1) for x in n['shapeBox']]} rate={n['rate']} bursts={n['bursts']}")
