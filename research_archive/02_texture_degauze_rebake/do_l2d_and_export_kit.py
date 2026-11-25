import os
import csv
import shutil
import cv2
import numpy as np
from PIL import Image, ImageDraw

# ==============================================================================
# PART 1: Replace Live2D Lilyiro 花与剑的交织 texture with de-gauzed backup
# ==============================================================================
l2d_curr_path = r"E:\A灵魂潮汐\Live2D与Spine模型\live2d\莉莉艾洛\花与剑的交织\Textures\lilyiro_texture_00.png"
l2d_bak_degauze_path = r"E:\A灵魂潮汐\备份\live2d\莉莉艾洛\婚纱 - 副本\Textures\Lilyiro_texture_00.png"
scratch_dir = r".\_scratch\lilyiro05_inspect"
os.makedirs(scratch_dir, exist_ok=True)

backup_orig = os.path.join(scratch_dir, "lilyiro_texture_00_backup_with_gauze.png")
if not os.path.exists(backup_orig):
    shutil.copy2(l2d_curr_path, backup_orig)

curr_arr = np.array(Image.open(backup_orig).convert("RGBA"))
bak_arr = np.array(Image.open(l2d_bak_degauze_path).convert("RGBA"))

# Verify exact diff region for x < 2040
d = np.abs(curr_arr.astype(np.int16) - bak_arr.astype(np.int16)).max(axis=2)
ys, xs = np.where((d > 0) & (np.arange(2048)[None, :] < 2040))
print(f"[Live2D] Exact diff region (x<2040): count={len(xs)}, x=[{xs.min()},{xs.max()}], y=[{ys.min()},{ys.max()}]")

# Patch ONLY the chest gauze bbox x=[895..1245], y=[700..900] so right edge x>=2044 stays untouched
out_l2d = curr_arr.copy()
out_l2d[700:900, 895:1245] = bak_arr[700:900, 895:1245]
# Clean any zero-alpha RGB in the patched area
patch = out_l2d[700:900, 895:1245]
patch[patch[:, :, 3] == 0] = 0
out_l2d[700:900, 895:1245] = patch

Image.fromarray(out_l2d).save(l2d_curr_path, optimize=True)
print(f"[Live2D] Updated: {l2d_curr_path} ({os.path.getsize(l2d_curr_path):,} bytes)")

# Verify Live2D patch visually
crop_before = Image.fromarray(curr_arr[680:920, 880:1280])
crop_after = Image.fromarray(out_l2d[680:920, 880:1280])
comp_l2d = Image.new("RGB", (830, 280), (25, 25, 30))
dl = ImageDraw.Draw(comp_l2d)
bg1 = Image.new("RGBA", crop_before.size, (35, 35, 45, 255)); bg1.alpha_composite(crop_before)
bg2 = Image.new("RGBA", crop_after.size, (35, 35, 45, 255)); bg2.alpha_composite(crop_after)
comp_l2d.paste(bg1.convert("RGB"), (10, 30)); dl.text((10, 8), "Live2D BEFORE", fill=(255,255,0))
comp_l2d.paste(bg2.convert("RGB"), (420, 30)); dl.text((420, 8), "Live2D AFTER (de-gauzed)", fill=(255,255,0))
comp_l2d.resize((comp_l2d.width // 2, comp_l2d.height // 2), Image.Resampling.LANCZOS).save(
    os.path.join(scratch_dir, "l2d_replaced_check_50.jpg"), "JPEG", quality=88
)

# ==============================================================================
# PART 2: Export clean Spine 83_1 part kit for user editing
# ==============================================================================
kit_dir = r"E:\A灵魂潮汐\tools\_lilyiro05_edit_kit"
os.makedirs(kit_dir, exist_ok=True)

spine_png = r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png"
mesh_csv = os.path.join(scratch_dir, "mesh_83_1_setup.csv")
atlas = np.array(Image.open(spine_png).convert("RGBA"))
H, W = atlas.shape[:2]

# Build exact UV triangle mask for 83_1
mask_full = np.zeros((H, W), dtype=np.uint8)
with open(mesh_csv, "r", encoding="utf-8") as f:
    for row in csv.reader(f):
        vals = [float(v) for v in row]
        pts = np.array([[vals[6], vals[7]], [vals[8], vals[9]], [vals[10], vals[11]]], dtype=np.float32)
        cv2.fillPoly(mask_full, [np.round(pts).astype(np.int32)], 255)

# Crop 83_1 rect: xy=2,752 size=363,315
rx, ry, rw, rh = 2, 752, 363, 315
sub_mask = mask_full[ry:ry+rh, rx:rx+rw] > 0
c0_pma = atlas[ry:ry+rh, rx:rx+rw].copy()

# Zero out ALL pixels outside 83_1 UV mesh (removes all 15,281 neighboring region pixels!)
clean_pma = np.zeros_like(c0_pma)
clean_pma[sub_mask] = c0_pma[sub_mask]

# Convert PMA -> Straight Alpha for Photoshop / AI editors
def pma_to_straight(pma_rgba):
    out = np.zeros_like(pma_rgba)
    a = pma_rgba[:, :, 3]
    nz = a > 0
    af = a[nz].astype(np.float32)[:, None] / 255.0
    rgb = np.clip(np.round(pma_rgba[nz, :3].astype(np.float32) / af), 0, 255).astype(np.uint8)
    out[nz, :3] = rgb
    out[nz, 3] = a[nz]
    return out

clean_straight = pma_to_straight(clean_pma)

# Save 01: Clean 83_1 Straight Alpha (for editing)
Image.fromarray(clean_straight).save(os.path.join(kit_dir, "01_83_1_clean_straight.png"))
# Save 02: Clean 83_1 Original PMA (reference)
Image.fromarray(clean_pma).save(os.path.join(kit_dir, "02_83_1_clean_pma.png"))
# Save 04: Exact UV Mesh Mask (white = inside 83_1 polygon)
Image.fromarray(mask_full[ry:ry+rh, rx:rx+rw]).save(os.path.join(kit_dir, "04_83_1_uv_mesh_mask.png"))

# Create 03: Triangle semi-transparent gauze cleared version (keeping straps + collar + breasts 100% intact!)
# Notice in 83_1: the translucent gauze triangle between straps & collar has alpha in [5..160] AND sits in the right half (x >= 180)
# Wait: let's check connected component of semi-transparent gauze (3 < a < 160) so we don't touch AA edges of straps or breast soft edge!
a_clean = clean_pma[:, :, 3]
# Find pixels with 1 <= a <= 115 (gauze core is alpha 18..90; strap AA is 1..2px thin!)
# Use morphological opening (3x3) on (a > 5) & (a < 150) to isolate ONLY broad translucent gauze patches, NOT thin 1px anti-aliased edges!
semi_broad = ((a_clean >= 5) & (a_clean <= 155)).astype(np.uint8) * 255
kernel3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
gauze_core = cv2.morphologyEx(semi_broad, cv2.MORPH_OPEN, kernel3)
# Dilate back slightly ONLY within (a_clean < 180) to cleanly meet the strap & breast edges without nibbling opaque pixels!
kernel_d = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
gauze_mask = (cv2.dilate(gauze_core, kernel_d) > 0) & (a_clean < 185)
# Restrict to x >= 175 (right of cleavage/breasts, where the triangle gauze lives; avoid touching left edge shadow)
gauze_mask[:, :175] = False

print(f"[Spine 83_1] Detected broad translucent triangle gauze pixels: {int(gauze_mask.sum())}")

tri_cleared_pma = clean_pma.copy()
tri_cleared_pma[gauze_mask] = 0
# Also smooth 1px transition at breast right contour? Keep raw first, check visually!
tri_cleared_straight = pma_to_straight(tri_cleared_pma)
Image.fromarray(tri_cleared_straight).save(os.path.join(kit_dir, "03_83_1_triangle_cleared_straight.png"))

# Also write a temp atlas with ONLY triangle gauze cleared so we can render 06_chest_context_tri_cleared.png!
atlas_tri_cleared = atlas.copy()
sub_out = atlas[ry:ry+rh, rx:rx+rw].copy()
sub_out[sub_mask] = tri_cleared_pma[sub_mask]
atlas_tri_cleared[ry:ry+rh, rx:rx+rw] = sub_out
Image.fromarray(atlas_tri_cleared).save(os.path.join(scratch_dir, "SoulDress_Lilyiro_05_tri_cleared_test.png"))

print("[Spine 83_1] Exported 01..04 to", kit_dir)
