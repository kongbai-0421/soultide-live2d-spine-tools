import json
from pathlib import Path
from PIL import Image
proj = Path(r".\_scratch\unity_fx_proj")
for fn in sorted((proj / "Assets" / "Textures").glob("*.png")):
    im = Image.open(fn).convert("RGBA")
    print(f"{fn.name:24s} size={im.size} alpha={im.split()[3].getextrema()} luma={im.convert('L').getextrema()}")
spec = json.loads((proj / "fx_spec.json").read_text("utf-8"))
for clip in ("idle", "fx_9008135", "fx_9008136"):
    for n in spec[clip]["nodes"]:
        if n.get("uvTiles") or n["name"] in ("beike", "bao", "shan", "stra", "FX_glow", "smoke"):
            print(clip, n["name"], "uvTiles=", n.get("uvTiles"), "shape=", n["shapeType"], "box=", n["shapeBox"], "rotOverLife=", n.get("rotOverLife"))
