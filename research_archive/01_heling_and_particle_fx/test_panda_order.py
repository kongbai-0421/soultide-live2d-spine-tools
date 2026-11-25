"""Test Case A (Unity exact: bj_01 behind Background_01) vs Case B (Background_01 behind bj_01) visually!"""
import json, subprocess, os
from pathlib import Path
from PIL import Image

d = Path(r".\_scratch\heling_orig_layers")
out = Path(r".\_scratch")

# Quick check: render ONLY bj_01 onto transparent background? Easier: use our existing rendered
# heling_scheme1_t0 vs overlay l2_bld on top of the exact canvas rect!
# Even better: check exact pixel coordinates of bj_01 slots in Spine world space!
# Wait: we can run _spine38_composite_renderer.exe on a temp skin dir? Even faster: inspect bj_01 bbox!
# Wait - let's just overlay l2_bld onto our rendered `033_和铃__古锦新韵.jpg` (from _doll_audit_previews or scratch)!
# No, let's check exact canvas pixel bounds inside heling_scheme1_t0\033_和铃__古锦新韵.jpg:
# Or render using C# directly? Actually let's just composite l1_sky + l1_scr + l2_bld and check where bj_01's bones/slots are!
import sys
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from PIL import ImageDraw

# Let's check exact world bbox of bj_01 in our centered Spine coords (-2125..+2125 x -1416.67..+1416.67)
# by running a 10-line C# check or checking our existing rendered image!
# Look at `heling_scheme1_t0\033_和铃__古锦新韵.jpg`: it has a 1px cyan border around bg_rect [-2125..2125]x[-1416.67..1416.67]!
im_t0 = Image.open(out / "heling_scheme1_t0" / "033_和铃__古锦新韵.jpg").convert("RGBA")
import numpy as np
arr = np.array(im_t0)
# Find the cyan border or non-dark-checkerboard box (header is top ~30px)
# Actually let's check exact bg_rect mapping in _spine38_composite_renderer.cs:
# Even simpler: check where l2_bld alpha > 128 overlaps the panda billboard region in im_t0!
# Find image content bbox (skip top 36px header)
sub = arr[36:, :, :3]
# Checkerboard background is dark gray (<45), content is brighter
bright = (sub.max(axis=2) > 55)
ys, xs = np.where(bright)
x0, x1 = int(xs.min()), int(xs.max()) + 1
y0, y1 = int(ys.min()) + 36, int(ys.max()) + 37
print("Content box in t0:", x0, y0, x1, y1, "size:", x1 - x0, y1 - y0)

# Resize l2_bld to match (x1-x0, y1-y0) and paste ON TOP of im_t0 (Case A simulation: Buildings ON TOP of Panda!)
crop_b = im_t0.crop((x0, y0, x1, y1))  # Case B (Panda ON TOP of Buildings)
l2_bld = Image.open(d / "L2_Image__HeLing_S2_Background_01.png").convert("RGBA")
l2_res = l2_bld.resize(crop_b.size, Image.Resampling.LANCZOS)
crop_a = Image.alpha_composite(crop_b, l2_res)  # Case A (Buildings ON TOP of Panda - except note Heling is also under l2_bld here, focus on LEFT panda billboard!)

# Zoom in on left-half panda billboard [0..58% W, 10..65% H] side by side!
W, H = crop_b.size
box = (int(W * 0.05), int(H * 0.08), int(W * 0.60), int(H * 0.62))
zb = crop_b.crop(box).convert("RGB")
za = crop_a.crop(box).convert("RGB")
side = Image.new("RGB", (zb.width * 2 + 10, zb.height), (255, 255, 255))
side.paste(za, (0, 0))
side.paste(zb, (zb.width + 10, 0))
side.save(out / "compare_panda_A_vs_B.jpg", "JPEG", quality=85)
print("Saved compare_panda_A_vs_B.jpg (LEFT=Case A: Buildings ON TOP of Panda [Unity Sibling Order], RIGHT=Case B: Panda ON TOP of Buildings)")
