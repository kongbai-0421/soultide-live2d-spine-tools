import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ps_code = r"""
$ErrorActionPreference = 'Stop'
$managed = 'C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed'
[System.Reflection.Assembly]::LoadFrom("$managed\Assembly-CSharp.dll") | Out-Null
Add-Type -TypeDefinition @"
using System;
using Spine3_8;
public class StubLoader : AttachmentLoader {
    public RegionAttachment NewRegionAttachment(Skin s, string n, string p) { return new RegionAttachment(n); }
    public MeshAttachment NewMeshAttachment(Skin s, string n, string p) { return new MeshAttachment(n); }
    public BoundingBoxAttachment NewBoundingBoxAttachment(Skin s, string n) { return new BoundingBoxAttachment(n); }
    public PathAttachment NewPathAttachment(Skin s, string n) { return new PathAttachment(n); }
    public PointAttachment NewPointAttachment(Skin s, string n) { return new PointAttachment(n); }
    public ClippingAttachment NewClippingAttachment(Skin s, string n) { return new ClippingAttachment(n); }
}
"@ -ReferencedAssemblies "$managed\Assembly-CSharp.dll","$managed\UnityEngine.CoreModule.dll"
$sb = New-Object Spine3_8.SkeletonBinary((New-Object StubLoader))
$sb.Scale = 1.0
$sd = $sb.ReadSkeletonData('E:\A灵魂潮汐\Live2D与Spine模型\spine\月本柚\明媚之约\SoulDress_Yuu_02.skel.json')
$sk = New-Object Spine3_8.Skeleton($sd)
$sk.SetToSetupPose()
$idle = $sd.FindAnimation('idle')
if ($idle -ne $null) {
    $idle.Apply($sk, 0, 0, $false, $null, 1.0, [Spine3_8.MixBlend]::Setup, [Spine3_8.MixDirection]::In)
}
$sk.UpdateWorldTransform()
$map = @{}
foreach ($b in $sk.Bones) {
    $map[$b.Data.Name] = @([math]::Round($b.WorldX, 2), [math]::Round($b.WorldY, 2))
}
$map | ConvertTo-Json -Compress
"""

raw_json = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps_code]).decode("utf-8").strip()
wpos = json.loads(raw_json)

cfg_p = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\月本柚\明媚之约\.config.json")
cfg = json.loads(cfg_p.read_text(encoding="utf-8"))

# Fit isotropic scale & offset from the 6 red boxes in QQ20261119-193830.png:
# bone130 (wx=2643.54, wy=1907.82) -> (578.0, 685.0)
# bone19  (wx=2527.14, wy=330.33)  -> (478.5, 1602.5)
s_px = (1602.5 - 685.0) / (wpos["bone130"][1] - wpos["bone19"][1])
ox = 578.0 - wpos["bone130"][0] * s_px
oy = 685.0 + wpos["bone130"][1] * s_px

img = Image.open(r"E:\库\下载\QQ20261119-193830.png").convert("RGB")
draw = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 26)
except Exception:
    font = ImageFont.load_default()

for ha in cfg["hit_areas"]:
    bname = ha["id"]
    wx, wy = wpos[bname]
    cx_sp = wx + float(ha.get("center_x", 0.0)) * 100.0
    cy_sp = wy + float(ha.get("center_y", 0.0)) * 100.0
    w_sp = float(ha["width"]) * 100.0
    h_sp = float(ha["height"]) * 100.0
    px = ox + cx_sp * s_px
    py = oy - cy_sp * s_px
    pw = w_sp * s_px
    ph = h_sp * s_px
    x0, y0, x1, y1 = px - pw / 2, py - ph / 2, px + pw / 2, py + ph / 2
    draw.rectangle([x0, y0, x1, y1], outline=(0, 230, 64), width=6)
    label = f"{ha['name']} ({bname})"
    draw.rectangle([x0, max(0, y0 - 34), x0 + len(label) * 16 + 16, max(34, y0)], fill=(0, 160, 40))
    draw.text((x0 + 8, max(2, y0 - 32)), label, fill=(255, 255, 255), font=font)
    print(f"New box {ha['name']} ({bname}): center=({px:.1f}, {py:.1f}), box=({x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f})")

out_full = Path(r".\_scratch\yuu02_touch_before_after.png")
out_prev = Path(r".\_scratch\yuu02_touch_before_after_preview.jpg")
img.save(out_full, "PNG")
w, h = max(1, img.width // 2), max(1, img.height // 2)
img.resize((w, h), Image.Resampling.LANCZOS).save(out_prev, "JPEG", quality=80)
print("Saved overlay and 50% preview:", out_prev)
