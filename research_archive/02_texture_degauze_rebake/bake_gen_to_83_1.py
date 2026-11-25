import os
import csv
import cv2
import numpy as np
from PIL import Image, ImageDraw

scratch_dir = r".\_scratch\lilyiro05_inspect"
kit_dir = r"E:\A灵魂潮汐\tools\_lilyiro05_edit_kit"
spine_png = r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png"
gen_path = r"E:\库\下载\Generated Image November 22, 2026 - 8_09PM.jpg"

# Load inputs
atlas_orig = np.array(Image.open(spine_png).convert("RGBA"))
ref06 = np.array(Image.open(os.path.join(kit_dir, "06_chest_context_tri_cleared.png")).convert("RGB"))
occ06 = np.array(Image.open(os.path.join(scratch_dir, "occluders_above_83_1_idle0.png")).convert("L"))
gen_im = np.array(Image.open(gen_path).convert("RGB"))
M_gen_to_06 = np.load(os.path.join(scratch_dir, "M_gen_to_06_context.npy"))  # 2x3
M_06_to_gen = cv2.invertAffineTransform(M_gen_to_06)  # 2x3

# 83_1 rect in atlas
rx, ry, rw, rh = 2, 752, 363, 315

# Build inverse UV lookup map in 83_1 local coords (rh x rw):
# For each pixel (u_loc, v_loc) -> atlas pixel (rx+u_loc+0.5, ry+v_loc+0.5) -> (cx, cy) in 06_context
map_cx = np.full((rh, rw), -1.0, dtype=np.float32)
map_cy = np.full((rh, rw), -1.0, dtype=np.float32)
uv_mask = np.zeros((rh, rw), dtype=np.uint8)

with open(os.path.join(scratch_dir, "mesh_83_1_idle0.csv"), "r", encoding="utf-8") as f:
    tris = [[float(v) for v in row] for row in csv.reader(f)]

for row in tris:
    cx0, cy0, cx1, cy1, cx2, cy2 = row[0:6]
    u0, v0, u1, v1, u2, v2 = row[6] - rx, row[7] - ry, row[8] - rx, row[9] - ry, row[10] - rx, row[11] - ry

    x0 = max(0, int(np.floor(min(u0, u1, u2))))
    x1 = min(rw - 1, int(np.ceil(max(u0, u1, u2))))
    y0 = max(0, int(np.floor(min(v0, v1, v2))))
    y1 = min(rh - 1, int(np.ceil(max(v0, v1, v2))))
    if x0 > x1 or y0 > y1:
        continue

    denom = (v1 - v2) * (u0 - u2) + (u2 - u1) * (v0 - v2)
    if abs(denom) < 1e-6:
        continue
    inv_d = 1.0 / denom

    yy, xx = np.mgrid[y0:y1+1, x0:x1+1]
    fx = xx.astype(np.float32) + 0.5
    fy = yy.astype(np.float32) + 0.5
    w0 = ((v1 - v2) * (fx - u2) + (u2 - u1) * (fy - v2)) * inv_d
    w1 = ((v2 - v0) * (fx - u2) + (u0 - u2) * (fy - v2)) * inv_d
    w2 = 1.0 - w0 - w1
    inside = (w0 >= -1e-3) & (w1 >= -1e-3) & (w2 >= -1e-3)

    if inside.any():
        sub_cx = map_cx[y0:y1+1, x0:x1+1]
        sub_cy = map_cy[y0:y1+1, x0:x1+1]
        sub_m = uv_mask[y0:y1+1, x0:x1+1]
        sub_cx[inside] = w0[inside] * cx0 + w1[inside] * cx1 + w2[inside] * cx2
        sub_cy[inside] = w0[inside] * cy0 + w1[inside] * cy1 + w2[inside] * cy2
        sub_m[inside] = 255

# Convert (map_cx, map_cy) directly to 2048x2048 gen image coords for crisp supersampled downsampling!
map_gx = (M_06_to_gen[0, 0] * map_cx + M_06_to_gen[0, 1] * map_cy + M_06_to_gen[0, 2]).astype(np.float32)
map_gy = (M_06_to_gen[1, 0] * map_cx + M_06_to_gen[1, 1] * map_cy + M_06_to_gen[1, 2]).astype(np.float32)

# Pre-filter gen_im slightly (anti-alias for 2048 -> 700 -> ~363 scale ratio ~3x) before remap so zero aliasing!
# Exact scale from gen (2048) to atlas 83_1: 1 atlas px ~ 1.75 context px ~ 5.1 gen px!
# So a Gaussian blur sigma=1.1 on 2048x2048 before cubic sampling prevents moire and keeps crispness!
gen_aa = cv2.GaussianBlur(gen_im, (0, 0), sigmaX=1.0, sigmaY=1.0)
baked_gen_rgb = cv2.remap(gen_aa, map_gx, map_gy, interpolation=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
baked_ref_rgb = cv2.remap(ref06, map_cx, map_cy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
baked_occ = cv2.remap(occ06, map_cx, map_cy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)

# Load our clean triangle-cleared 83_1 straight alpha base
tri_clean_straight = np.array(Image.open(os.path.join(kit_dir, "03_83_1_triangle_cleared_straight.png")).convert("RGBA"))
orig_rgb = tri_clean_straight[:, :, :3].astype(np.float32)
orig_a = tri_clean_straight[:, :, 3]

# Self-consistency check: compare baked_ref_rgb vs orig_rgb on opaque unoccluded pixels!
check_mask = (uv_mask > 0) & (orig_a >= 250) & (baked_occ < 5)
self_err = np.abs(baked_ref_rgb[check_mask].astype(np.float32) - orig_rgb[check_mask])
print(f"Self-consistency check (baked ref06 vs orig 83_1): mean={self_err.mean():.2f}, median={np.median(self_err):.2f}, p90={np.percentile(self_err, 90):.2f}")

# Construct ULTRA-PRECISE skin replacement mask in 83_1 atlas space (rh x rw):
# Look at color difference between skin and white lace/straps in orig_rgb:
R = orig_rgb[:, :, 0]
G = orig_rgb[:, :, 1]
B = orig_rgb[:, :, 2]

# Skin in 83_1 has cool lavender-pink hue:
#   - White lace cups & white straps are bright bluish-white: typically G >= 182 or (B - R) >= 26 or (R > 225 and G > 205)
#   - Skin pixels have R > G + 14 and B - R <= 45 and G < 192 (except bright cleavage highlight where R~230, G~195, B~235 — wait! Let's check cleavage highlight values!)
# Let's inspect the exact RGB of cleavage highlight vs upper/lower lace!
print("Sample skin/lace RGB in 03_83_1:")
for (px, py, lbl) in [
    (120, 130, "cleavage mid"),
    (115, 165, "cleavage bright"),
    (160, 150, "chest skin"),
    (195, 120, "upper breast"),
    (190, 210, "lower breast"),
    (55, 65, "upper lace"),
    (65, 225, "lower lace"),
    (120, 250, "lower lace flower"),
    (210, 80, "upper strap"),
    (215, 235, "lower strap"),
]:
    print(f"  ({px:3d},{py:3d}) {lbl:18s}: RGBA={tri_clean_straight[py, px].tolist()}  baked_gen={baked_gen_rgb[py, px].tolist()}")

# Better yet: look at what AI ACTUALLY changed!
# In atlas space, let's compute diff = |baked_gen_rgb - baked_ref_rgb|!
# Remember from gen_vs_06_context_50.jpg: AI ONLY changed:
#   1) The chest skin & cleavage (large smooth region in the middle of the breasts!)
#   2) A small bit of the upper-left lace edge (which we want to EXCLUDE!)
# So we can combine:
#   (a) Main breast skin region mask (exclude upper lace cup, lower lace cup, collar, straps, and occluders!)
# Let's identify non-skin (lace + straps + collar) cleanly:
#   - Collar is x >= 240 (plus straps crossing right side)
#   - White straps & white lace have either (B > 228 and G > 192) or (B - R > 34 and B > 200) or (G > 200 and B > 235)
#   - Wait: let's also exclude pixels where R - G < 12 (white/blue lace & straps are neutral/blue, skin always has R > G + 15!)
# Let's test `is_skin_color = (R - G >= 13) & (orig_a >= 240) & (uv_mask > 0)`!
is_skin_color = ((R - G) >= 13) & (orig_a >= 240) & (uv_mask > 0)
# Restrict to x < 258 (never touch collar on far right!) and exclude bright white upper/lower lace cup highlights!
is_skin_color[:, 258:] = False
# Exclude bright white lace cups (upper lace cup x<115,y<125 where G>180; lower lace cup y>175,x<145 where G>180 or B>232)
upper_lace = (np.arange(rw)[None, :] < 115) & (np.arange(rh)[:, None] < 130) & ((G > 182) | (B > 234))
lower_lace = (np.arange(rw)[None, :] < 145) & (np.arange(rh)[:, None] > 175) & ((G > 182) | (B > 234))
is_skin_color &= (~upper_lace) & (~lower_lace)
# Keep ONLY the largest connected component (the contiguous breasts & cleavage skin!)
num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(is_skin_color.astype(np.uint8), connectivity=8)
if num_labels > 1:
    # Sort components by area descending
    areas = [(stats[i, cv2.CC_STAT_AREA], i) for i in range(1, num_labels)]
    areas.sort(reverse=True)
    print("Top skin connected components (area, label):", areas[:5])
    # Take components with area > 800 (in case straps split a small chunk of breast skin!)
    skin_cc = np.zeros_like(is_skin_color)
    for area, lid in areas:
        if area > 400:
            skin_cc |= (labels == lid)
else:
    skin_cc = is_skin_color

# Fill tiny interior holes inside skin_cc (e.g. a bright highlight spot inside cleavage where R-G dipped slightly)
# Use morphological close (9x9) ONLY restricted to non-lace (B < 245 or G < 215) & opaque
kernel9 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
skin_closed = cv2.morphologyEx(skin_cc.astype(np.uint8) * 255, cv2.MORPH_CLOSE, kernel9) > 0
# Erode by 2px away from straps/lace boundaries so we never bleed into lace/straps, EXCEPT keep cleavage interior!
# Actually check occluders (slot 91 purple flower, slot 86 blue pendant, etc.):
occ_dil = cv2.dilate((baked_occ >= 10).astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) > 0

# Final hard skin mask: inside skin_closed, NOT occluded by slot 91/86/etc., NOT touching outer alpha edge (erode opaque mask by 2px)
opaque_eroded = cv2.erode((orig_a >= 248).astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0
# Note: we DO want to cover up to 1px of cleavage left edge (where breasts meet dress), so only erode by 3x3
opaque_eroded = cv2.erode((orig_a >= 245).astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) > 0

hard_mask = skin_closed & opaque_eroded & (~occ_dil)
# Also erode hard_mask by 1px away from non-skin (straps/lace) and Gaussian feather sigma=2.2
hard_eroded = cv2.erode(hard_mask.astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
blend_w = cv2.GaussianBlur(hard_eroded.astype(np.float32) / 255.0, (0, 0), sigmaX=2.2, sigmaY=2.2)
# Strictly zero outside opaque & unoccluded & uv_mask!
blend_w[(uv_mask == 0) | (orig_a < 230) | (baked_occ >= 20)] = 0.0

# Blend in Straight Alpha space!
new_rgb_straight = orig_rgb * (1.0 - blend_w[:, :, None]) + baked_gen_rgb.astype(np.float32) * blend_w[:, :, None]
new_rgb_straight = np.clip(np.round(new_rgb_straight), 0, 255).astype(np.uint8)

# Convert back to STRICT PMA: RGB_pma = round(RGB_straight * A / 255), A==0 -> RGBA=0
out_83_1_pma = np.zeros((rh, rw, 4), dtype=np.uint8)
af = orig_a.astype(np.float32) / 255.0
for c in range(3):
    out_83_1_pma[:, :, c] = np.clip(np.round(new_rgb_straight[:, :, c].astype(np.float32) * af), 0, 255).astype(np.uint8)
out_83_1_pma[:, :, 3] = orig_a
out_83_1_pma[orig_a == 0] = 0
# Strict PMA guarantee: RGB <= A
for c in range(3):
    out_83_1_pma[:, :, c] = np.minimum(out_83_1_pma[:, :, c], out_83_1_pma[:, :, 3])

# Write ONLY inside 83_1 UV mesh mask onto a test copy of atlas!
test_atlas = atlas_orig.copy()
sub_dst = test_atlas[ry:ry+rh, rx:rx+rw].copy()
m_bool = uv_mask > 0
sub_dst[m_bool] = out_83_1_pma[m_bool]
test_atlas[ry:ry+rh, rx:rx+rw] = sub_dst

# Verify ZERO neighbor pixels touched!
outside_changed = np.abs(test_atlas.astype(int) - atlas_orig.astype(int)).max(axis=2) > 0
full_uv_mask = np.zeros(atlas_orig.shape[:2], dtype=bool)
full_uv_mask[ry:ry+rh, rx:rx+rw] = m_bool
leaked = outside_changed & (~full_uv_mask)
print(f"Leaked pixels outside 83_1 UV mesh: {int(leaked.sum())} (MUST BE 0)")
assert leaked.sum() == 0

test_atlas_path = os.path.join(scratch_dir, "SoulDress_Lilyiro_05_ai_baked_test.png")
Image.fromarray(test_atlas).save(test_atlas_path)

# Diagnostic sheet: [03_orig, baked_gen_raw, blend_w + occ vis, final_83_1_straight]
vis_mask = orig_rgb.astype(np.uint8).copy()
# Green tint = blend_w, Red tint = occluded by upper slots (slot 91 flower, slot 86 pendant)
vis_mask[:, :, 1] = np.clip(vis_mask[:, :, 1].astype(np.float32) + blend_w * 120, 0, 255).astype(np.uint8)
vis_mask[occ_dil & m_bool, 0] = 255
vis_mask[occ_dil & m_bool, 1] = 40

def on_dark(rgba_straight):
    bg = Image.new("RGBA", (rw, rh), (35, 35, 45, 255))
    bg.alpha_composite(Image.fromarray(rgba_straight))
    return bg.convert("RGB")

final_straight_vis = np.dstack([new_rgb_straight, orig_a])
final_straight_vis[orig_a == 0] = 0

diag = Image.new("RGB", (rw * 4 + 50, rh + 50), (20, 20, 25))
dr = ImageDraw.Draw(diag)
diag.paste(on_dark(tri_clean_straight), (10, 35)); dr.text((10, 10), "1. Orig 83_1 (tri cleared)", fill=(255,255,0))
diag.paste(Image.fromarray(baked_gen_rgb), (rw + 20, 35)); dr.text((rw + 20, 10), "2. Raw Inverse-Baked AI", fill=(255,255,0))
diag.paste(Image.fromarray(vis_mask), (rw * 2 + 30, 35)); dr.text((rw * 2 + 30, 10), "3. Mask (Green=AI, Red=Occ)", fill=(255,255,0))
diag.paste(on_dark(final_straight_vis), (rw * 3 + 40, 35)); dr.text((rw * 3 + 40, 10), "4. Final Blended 83_1", fill=(255,255,0))
diag.resize((diag.width // 2, diag.height // 2), Image.Resampling.LANCZOS).save(
    os.path.join(scratch_dir, "ai_bake_diag_50.jpg"), "JPEG", quality=88
)
print("Saved test atlas and ai_bake_diag_50.jpg!")
