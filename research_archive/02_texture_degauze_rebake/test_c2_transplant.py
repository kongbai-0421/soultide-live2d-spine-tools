import os
import csv
import cv2
import numpy as np
from PIL import Image, ImageDraw

out_dir = r".\_scratch\lilyiro05_inspect"
curr_png = r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png"
bak_png = r"E:\A灵魂潮汐\备份\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png"
mesh_csv = os.path.join(out_dir, "mesh_83_1_setup.csv")

# 1. Load current 2048x2048 atlas
atlas = np.array(Image.open(curr_png).convert("RGBA"))
H, W = atlas.shape[:2]

# 2. Build exact UV triangle mask for slot 83_1 from mesh_83_1_setup.csv
mask = np.zeros((H, W), dtype=np.uint8)
with open(mesh_csv, "r", encoding="utf-8") as f:
    for row in csv.reader(f):
        vals = [float(v) for v in row]
        # cols 6..11 are atlas pixel coords u0*W, v0*H, u1*W, v1*H, u2*W, v2*H
        pts = np.array([
            [vals[6], vals[7]],
            [vals[8], vals[9]],
            [vals[10], vals[11]],
        ], dtype=np.float32)
        cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 255)

# Dilate mask by 2px for bilinear sampling margin, BUT check whether it touches any neighboring region!
# Let's check exact bounding box of mask vs 83_1 atlas rect (x=2..365, y=752..1067)
ys, xs = np.where(mask > 0)
print(f"83_1 UV mesh mask px={len(xs)}, bbox x=[{xs.min()},{xs.max()}], y=[{ys.min()},{ys.max()}]")

# Also check if any neighbor pixels are inside mask!
# Let's extract c2 (rotated 90 in bak_png at xy=2617,1444 size=363,315)
bak_im = Image.open(bak_png).convert("RGBA")
c2 = np.array(bak_im.crop((2617, 1444, 2617 + 315, 1444 + 363)).rotate(-90, expand=True))
# Clean residual alpha <= 4 in c2 (e.g. a=1..2 left in triangle)
c2_clean = c2.copy()
low_a = c2_clean[:, :, 3] <= 4
c2_clean[low_a] = 0
# Enforce strict PMA: RGB <= A
for ch in range(3):
    c2_clean[:, :, ch] = np.minimum(c2_clean[:, :, ch], c2_clean[:, :, 3])

# Paste c2_clean ONLY where mask > 0 inside 83_1 rect (x=2..365, y=752..1067)
out_atlas = atlas.copy()
sub_mask = mask[752:752+315, 2:2+363] > 0
# Dilate sub_mask by 1px inside rect ONLY where current alpha is low or part of 83_1
# Actually let's check what pixels inside the 363x315 rect are OUTSIDE sub_mask!
c0_sub = atlas[752:752+315, 2:2+363]
outside_nonzero = (~sub_mask) & (c0_sub[:, :, 3] > 5)
print(f"Non-empty pixels in 83_1 rect OUTSIDE 83_1 mesh (neighbor regions!): {int(outside_nonzero.sum())}")

# Apply mask-only replacement
sub_out = c0_sub.copy()
sub_out[sub_mask] = c2_clean[sub_mask]
out_atlas[752:752+315, 2:2+363] = sub_out

test_atlas_path = os.path.join(out_dir, "SoulDress_Lilyiro_05_c2_test.png")
Image.fromarray(out_atlas).save(test_atlas_path)

# Also save visualization of UV mesh mask overlaid on 83_1 rect
vis = np.zeros((315, 363, 3), dtype=np.uint8)
a0 = c0_sub[:, :, 3:4].astype(np.float32) / 255.0
vis = np.clip(c0_sub[:, :, :3].astype(np.float32) + 30 * (1 - a0), 0, 255).astype(np.uint8)
# Tint outside-mesh pixels red so we verify neighbor protection!
vis[~sub_mask, 0] = np.clip(vis[~sub_mask, 0].astype(int) + 120, 0, 255).astype(np.uint8)
# Draw mesh edges in cyan
edges = cv2.Canny(mask[752:752+315, 2:2+363], 50, 150)
vis[edges > 0] = [0, 255, 255]
Image.fromarray(vis).resize((363, 315)).save(os.path.join(out_dir, "mesh_mask_check.png"))
print("Saved test atlas and mesh mask check!")
