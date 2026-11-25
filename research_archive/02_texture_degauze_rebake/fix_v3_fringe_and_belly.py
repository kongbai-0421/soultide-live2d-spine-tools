import os
import csv
import cv2
import numpy as np
from PIL import Image, ImageDraw

s = r".\_scratch\lilyiro05_inspect"
orig_atlas = np.array(Image.open(s + r"\SoulDress_Lilyiro_05_orig_with_gauze_backup.png").convert("RGBA"))
# Start from our V2 atlas (which already has the perfect AI-baked & Lab-calibrated 83_1 chest!)
v2_atlas = np.array(Image.open(s + r"\SoulDress_Lilyiro_05_v2_test.png").convert("RGBA"))
# Also load V1 atlas (before V2 hard-cut of V-notch, so we can make a silky-smooth AA cut on 83_1!)
v1_atlas = np.array(Image.open(s + r"\SoulDress_Lilyiro_05_ai_baked_test.png").convert("RGBA"))
gen_im = np.array(Image.open(r"E:\库\下载\Generated Image November 22, 2026 - 8_09PM.jpg").convert("RGB"))
M_gen_to_06 = np.load(s + r"\M_gen_to_06_context.npy")
M_06_to_gen = cv2.invertAffineTransform(M_gen_to_06)

H, W = v2_atlas.shape[:2]

def pma_to_straight(pma):
    out = np.zeros_like(pma)
    a = pma[:, :, 3]
    nz = a > 0
    af = a[nz].astype(np.float32)[:, None] / 255.0
    out[nz, :3] = np.clip(np.round(pma[nz, :3].astype(np.float32) / af), 0, 255).astype(np.uint8)
    out[nz, 3] = a[nz]
    return out

def straight_to_pma(st):
    out = np.zeros_like(st)
    a = st[:, :, 3]
    af = a.astype(np.float32) / 255.0
    for c in range(3):
        out[:, :, c] = np.clip(np.round(st[:, :, c].astype(np.float32) * af), 0, 255).astype(np.uint8)
    out[:, :, 3] = a
    out[a == 0] = 0
    for c in range(3):
        out[:, :, c] = np.minimum(out[:, :, c], out[:, :, 3])
    return out

def load_uv_and_maps(csv_path, rx, ry, rw, rh):
    map_cx = np.full((rh, rw), -1.0, dtype=np.float32)
    map_cy = np.full((rh, rw), -1.0, dtype=np.float32)
    uv_mask = np.zeros((rh, rw), dtype=np.uint8)
    with open(csv_path, "r", encoding="utf-8") as f:
        tris = [[float(v) for v in row] for row in csv.reader(f)]
    for row in tris:
        cx0, cy0, cx1, cy1, cx2, cy2 = row[0:6]
        u0, v0, u1, v1, u2, v2 = row[6]-rx, row[7]-ry, row[8]-rx, row[9]-ry, row[10]-rx, row[11]-ry
        x0, x1 = max(0, int(np.floor(min(u0, u1, u2)))), min(rw-1, int(np.ceil(max(u0, u1, u2))))
        y0, y1 = max(0, int(np.floor(min(v0, v1, v2)))), min(rh-1, int(np.ceil(max(v0, v1, v2))))
        if x0 > x1 or y0 > y1: continue
        denom = (v1 - v2)*(u0 - u2) + (u2 - u1)*(v0 - v2)
        if abs(denom) < 1e-6: continue
        inv_d = 1.0 / denom
        yy, xx = np.mgrid[y0:y1+1, x0:x1+1]
        fx, fy = xx.astype(np.float32) + 0.5, yy.astype(np.float32) + 0.5
        w0 = ((v1 - v2)*(fx - u2) + (u2 - u1)*(fy - v2)) * inv_d
        w1 = ((v2 - v0)*(fx - u2) + (u0 - u2)*(fy - v2)) * inv_d
        w2 = 1.0 - w0 - w1
        ins = (w0 >= -1e-3) & (w1 >= -1e-3) & (w2 >= -1e-3)
        if ins.any():
            map_cx[y0:y1+1, x0:x1+1][ins] = w0[ins]*cx0 + w1[ins]*cx1 + w2[ins]*cx2
            map_cy[y0:y1+1, x0:x1+1][ins] = w0[ins]*cy0 + w1[ins]*cy1 + w2[ins]*cy2
            uv_mask[y0:y1+1, x0:x1+1][ins] = 255
    return uv_mask > 0, map_cx, map_cy

# ==============================================================================
# PART 1: Rebuild slot 96 belly/sternum with REALISTIC 3D shading + abdominal groove (NO flat block!)
# ==============================================================================
rx96, ry96, rw96, rh96 = 432, 1001, 414, 376
uv96, map96_cx, map96_cy = load_uv_and_maps(os.path.join(s, "mesh_96_idle0.csv"), rx96, ry96, rw96, rh96)

# Start from original slot 96 AND V2 harmonic-cleaned base
orig96_st = pma_to_straight(orig_atlas[ry96:ry96+rh96, rx96:rx96+rw96])
v2_96_st = pma_to_straight(v2_atlas[ry96:ry96+rh96, rx96:rx96+rw96])

# 1A) Inverse-UV bake the user's 2048x2048 AI image onto slot 96!
# Check which pixels of slot 96 are VISIBLE inside the diamond opening (not occluded by slot 83 dress or slot 83_1 breasts!)
# Load layer_83_redbox and layer_83_1_redbox (viewport: cx in [0..350], cy in [200..550])
l83_rb = np.array(Image.open(os.path.join(s, "layer_83_redbox.png")).convert("RGBA"))[:, :, 3]
l831_rb = np.array(Image.open(os.path.join(s, "layer_83_1_redbox.png")).convert("RGBA"))[:, :, 3]
# Full 700x700 visibility mask of slot 96 inside the diamond opening (cx < 260, cy in [220..520])
occ_96_700 = np.zeros((700, 700), dtype=np.uint8)
occ_96_700[200:550, 0:350] = np.maximum(l83_rb, l831_rb)

# Sample AI gen_im onto slot 96 UV coords
map96_gx = (M_06_to_gen[0, 0]*map96_cx + M_06_to_gen[0, 1]*map96_cy + M_06_to_gen[0, 2]).astype(np.float32)
map96_gy = (M_06_to_gen[1, 0]*map96_cx + M_06_to_gen[1, 1]*map96_cy + M_06_to_gen[1, 2]).astype(np.float32)
gen_aa = cv2.GaussianBlur(gen_im, (0, 0), sigmaX=1.0, sigmaY=1.0)
baked96_gen = cv2.remap(gen_aa, map96_gx, map96_gy, interpolation=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
baked96_occ = cv2.remap(occ_96_700, map96_cx, map96_cy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=255)

# Apply Lab color calibration so the diamond belly matches the V2 calibrated breasts & torso naturally
# (lit upper-belly skin should be slightly brighter than deep shadow torso [156], around L=168..182, NOT washed-out white 200+!)
lab_b96 = cv2.cvtColor(baked96_gen, cv2.COLOR_RGB2LAB).astype(np.float32)
# Compress overly bright white-oval lift from AI image (>175) while keeping all soft shading & gradients!
L_b = lab_b96[:, :, 0]
L_b_new = np.where(L_b > 165.0, 165.0 + (L_b - 165.0) * 0.52, L_b) - 4.0
lab_b96[:, :, 0] = np.clip(L_b_new, 0, 255)
lab_b96[:, :, 1] = np.clip(lab_b96[:, :, 1] + 0.5, 0, 255)
lab_b96[:, :, 2] = np.clip(lab_b96[:, :, 2] - 0.5, 0, 255)
baked96_calib = cv2.cvtColor(lab_b96.astype(np.uint8), cv2.COLOR_LAB2RGB)

# Identify diamond opening pixels strictly inside slot 96 AND strictly skin-colored (exclude any white dress edge!)
bR, bG, bB = baked96_gen[:, :, 0].astype(int), baked96_gen[:, :, 1].astype(int), baked96_gen[:, :, 2].astype(int)
is_ai_skin = (bR - bG >= 14) & (bG < 205)
diamond_vis = uv96 & (orig96_st[:, :, 3] >= 240) & (baked96_occ < 5) & is_ai_skin & (map96_cx >= 30) & (map96_cx <= 200) & (map96_cy >= 260) & (map96_cy <= 450)
ys_d, xs_d = np.where(diamond_vis)
print(f"[slot 96] Diamond opening visible skin pixels in slot 96 atlas: N={len(xs_d)}, x=[{xs_d.min()},{xs_d.max()}], y=[{ys_d.min()},{ys_d.max()}]")

# Compute centroid & orientation of the diamond opening in slot 96 atlas coords!
# Also check exact RGB stats of `baked96_calib` inside `diamond_vis` vs `v2_96_st` inside `diamond_vis`!
print("  v2_96_st (flat) in diamond mean RGB:", v2_96_st[diamond_vis, :3].mean(axis=0).round(1))
print("  baked96_calib   in diamond mean RGB:", baked96_calib[diamond_vis, :3].mean(axis=0).round(1))

# Construct a smooth 3D-shaded slot 96 base:
# Step i: Take V2 harmonic base in Lab space
lab_v2_96 = cv2.cvtColor(v2_96_st[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)

# Step ii: Blend in `baked96_calib` inside `diamond_vis` (eroded 2px from dress/breast occluder so zero dress white bleeds in!)
diamond_safe = cv2.erode(diamond_vis.astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0
# Also extend the diamond's bright sunlit skin tone smoothly outward into the oval area via harmonic extrapolation from (known torso + diamond_safe)!
# Wait — THIS IS GENIUS!!
# If we pin BOTH `known_torso` (outside oval) AND `diamond_safe` (the AI-painted natural belly with real shading!) as Dirichlet boundaries
# in Red-Black SOR Laplace solve across the remaining oval pixels, then:
#   1. Inside the diamond opening: 100% genuine AI-painted 3D sunlit skin + soft shading (NO flat block!!);
#   2. Surrounding the diamond (under the dress/breasts): 100% C1-smooth continuous extension of that EXACT skin tone & lighting gradient (ZERO seam when breathing/bouncing!!);
#   3. And then we enhance the subtle central abdominal/sternum groove (腹中线/腹沟) + soft under-breast ambient occlusion shadow!

yy96, xx96 = np.mgrid[0:rh96, 0:rw96]
cx0, cy0 = 86.0, 234.0
theta = np.radians(16.0)
xr = (xx96 - cx0)*np.cos(theta) + (yy96 - cy0)*np.sin(theta)
yr = -(xx96 - cx0)*np.sin(theta) + (yy96 - cy0)*np.cos(theta)
oval_ell = ((xr / 104.0)**2 + (yr / 82.0)**2) <= 1.0
lab_o96 = cv2.cvtColor(orig96_st[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
oval_bright = (lab_o96[:, :, 0] > 170) & (xx96 < 210)
oval_mask = (cv2.dilate((uv96 & (orig96_st[:, :, 3] >= 10) & (oval_ell | oval_bright)).astype(np.uint8)*255,
                        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0) & uv96 & (orig96_st[:, :, 3] > 0)

# Pin both outer healthy torso AND interior AI-painted diamond_safe!
known_outer = uv96 & (orig96_st[:, :, 3] >= 245) & (~oval_mask)
pinned = known_outer | diamond_safe
unknown = oval_mask & (~diamond_safe)
domain = pinned | unknown

u = orig96_st[:, :, :3].astype(np.float32).copy()
# Initialize unknown from V2 harmonic base
u[unknown] = v2_96_st[unknown, :3].astype(np.float32)
# Set pinned AI belly pixels inside diamond_safe!
u[diamond_safe] = baked96_calib[diamond_safe].astype(np.float32)
pinned_rgb = u.copy()

v_f = domain.astype(np.float32)
v_pad = np.pad(v_f, 1, mode='constant', constant_values=0.0)
n_cnt = np.maximum(v_pad[:-2, 1:-1] + v_pad[2:, 1:-1] + v_pad[1:-1, :-2] + v_pad[1:-1, 2:], 1.0)
rb = ((yy96 + xx96) % 2) == 0
m_red = unknown & rb
m_blk = unknown & (~rb)
omega = 1.80
for _ in range(450):
    u_pad = np.pad(u * v_f[:, :, None], ((1, 1), (1, 1), (0, 0)), mode='constant', constant_values=0.0)
    avg = (u_pad[:-2, 1:-1] + u_pad[2:, 1:-1] + u_pad[1:-1, :-2] + u_pad[1:-1, 2:]) / n_cnt[:, :, None]
    u[m_red] += omega * (avg[m_red] - u[m_red])
    u_pad = np.pad(u * v_f[:, :, None], ((1, 1), (1, 1), (0, 0)), mode='constant', constant_values=0.0)
    avg = (u_pad[:-2, 1:-1] + u_pad[2:, 1:-1] + u_pad[1:-1, :-2] + u_pad[1:-1, 2:]) / n_cnt[:, :, None]
    u[m_blk] += omega * (avg[m_blk] - u[m_blk])
    u[pinned] = pinned_rgb[pinned]

assert np.isfinite(u).all()

# Step iii: Sculpt a subtle, authentic anime abdominal centerline groove (腹中线 / 心窝沟) + soft 3D ribcage highlight!
# First check exact coordinates of the diamond centerline in slot 96!
# In 06_context coords, the diamond runs from bottom-left apex (~cx=52, cy=395) to the V-notch between breasts (~cx=155, cy=300)!
# Let's project those two anatomical endpoints into slot 96 atlas space using nearest match in (map96_cx, map96_cy)!
def ctx_to_96(target_cx, target_cy):
    d2 = (map96_cx - target_cx)**2 + (map96_cy - target_cy)**2
    d2[~uv96] = 1e12
    idx = np.argmin(d2)
    return int(idx % rw96), int(idx // rw96)

p_apex = ctx_to_96(52, 395)   # bottom-left tip of diamond opening (lower belly / navel direction)
p_notch = ctx_to_96(148, 308) # V-notch between the two breasts (sternum / epigastric hollow!)
p_top = ctx_to_96(100, 325)   # upper-left flank of diamond (sunlit upper rib)
p_bot = ctx_to_96(115, 390)   # lower-right flank of diamond (shadowed lower rib)
print(f"[slot 96] Anatomical landmarks: apex={p_apex}, V-notch={p_notch}, upper_flank={p_top}, lower_flank={p_bot}")

# Define natural abdominal centerline (linea alba / 腹中线) segment from slightly past apex to V-notch!
# Along this line:
#   - Centerline groove: soft cool-rose-purple depression (dL = -9.5, da = +2.2, db = -1.5), width sigma ~ 4.5px,
#     strongest near the sternum/epigastric hollow (closer to V-notch) and gently tapering toward the diamond tip!
#   - Flanking abdominal/rib fullness: subtle gentle highlight (+3.5 L) ~12px to either side of the groove (especially upper-left lit side +5.5 L)
#     giving authentic anime painterly belly volume!
ax, ay = float(p_apex[0]), float(p_apex[1])
bx, by = float(p_notch[0]), float(p_notch[1])
dx, dy = bx - ax, by - ay
seg_len = np.hypot(dx, dy) + 1e-6
ux_v, uy_v = dx / seg_len, dy / seg_len      # unit tangent along abdominal centerline (apex -> V-notch)
nx_v, ny_v = -uy_v, ux_v                     # unit normal perpendicular to centerline

# Signed coords (t along centerline [0..seg_len], s perpendicular)
rel_x = xx96.astype(np.float32) - ax
rel_y = yy96.astype(np.float32) - ay
t_coord = rel_x * ux_v + rel_y * uy_v
s_coord = rel_x * nx_v + rel_y * ny_v

# Slight natural curve of the torso centerline (gentle bow following lying pose)
t_norm = t_coord / seg_len  # 0 at diamond tip, 1 at V-notch
s_curved = s_coord - 3.5 * np.sin(np.pi * np.clip(t_norm, 0.0, 1.0))

# Longitudinal envelope: active from t_norm in [-0.15 .. 1.15], strongest in [0.15 .. 0.95]
t_env = np.clip((t_norm + 0.15) / 0.30, 0.0, 1.0) * np.clip((1.18 - t_norm) / 0.28, 0.0, 1.0)
# Smoothstep
t_env = t_env * t_env * (3.0 - 2.0 * t_env)

# Groove profile (soft gaussian trough along centerline, slightly sharper core + softer shadow halo)
groove_core = np.exp(-0.5 * (s_curved / 3.2)**2)
groove_soft = np.exp(-0.5 * (s_curved / 9.5)**2)
groove_mask = (0.65 * groove_core + 0.35 * groove_soft) * t_env

# Subtle under-breast / epigastric hollow deepen near V-notch (t_norm ~ 0.85..1.05)
hollow_mask = np.exp(-0.5 * ((t_norm - 0.92) / 0.22)**2) * np.exp(-0.5 * (s_curved / 16.0)**2)

# Flanking soft abdominal volume highlight (upper-left lit side s < 0 or > 0 — check which side p_top is on!)
s_top = (p_top[0] - ax)*nx_v + (p_top[1] - ay)*ny_v
lit_sign = 1.0 if s_top > 0 else -1.0
flank_lit = np.exp(-0.5 * ((s_curved - lit_sign * 13.0) / 10.0)**2) * t_env
flank_opp = np.exp(-0.5 * ((s_curved + lit_sign * 12.0) / 9.0)**2) * t_env

# Apply subtle painterly anatomical shading in Lab space ONLY inside oval_mask (feathered)
lab_u = cv2.cvtColor(np.clip(np.round(u), 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
sculpt_env = cv2.GaussianBlur(oval_mask.astype(np.float32), (0, 0), sigmaX=4.0, sigmaY=4.0)

# Apply abdominal centerline groove + hollow shadow + soft flanking volume highlights
lab_u[:, :, 0] += (-11.0 * groove_mask - 5.5 * hollow_mask + 5.0 * flank_lit + 2.5 * flank_opp) * sculpt_env
lab_u[:, :, 1] += (+2.4 * groove_mask + 1.2 * hollow_mask - 0.6 * flank_lit) * sculpt_env
lab_u[:, :, 2] += (-1.8 * groove_mask - 1.0 * hollow_mask + 0.8 * flank_lit) * sculpt_env

lab_u = np.clip(lab_u, 0, 255).astype(np.uint8)
rgb_u_sculpted = cv2.cvtColor(lab_u, cv2.COLOR_LAB2RGB).astype(np.float32)

# Feather seamlessly back into original slot 96
oval_feather = cv2.GaussianBlur(oval_mask.astype(np.float32), (0, 0), sigmaX=3.0, sigmaY=3.0)
oval_feather[~uv96] = 0.0
out96_rgb = np.clip(np.round(orig96_st[:, :, :3].astype(np.float32) * (1.0 - oval_feather[:, :, None]) + rgb_u_sculpted * oval_feather[:, :, None]), 0, 255).astype(np.uint8)
out96_st = orig96_st.copy()
out96_st[:, :, :3] = out96_rgb
out96_pma = straight_to_pma(out96_st)

# ==============================================================================
# PART 2: Fix slot 83_1 white fringe + jagged edge on the left V-notch & breast outlines!
# ==============================================================================
rx83, ry83, rw83, rh83 = 2, 752, 363, 315
uv83, _, _ = load_uv_and_maps(os.path.join(s, "mesh_83_1_idle0.csv"), rx83, ry83, rw83, rh83)

# Load V2's color-calibrated 83_1 (Straight Alpha)
v2_83_st = pma_to_straight(v2_atlas[ry83:ry83+rh83, rx83:rx83+rw83])
yy83, xx83 = np.mgrid[0:rh83, 0:rw83]

# Look closely at the red-circled white fringe in QQ20261122-204148.png and fringe_and_belly_diag_50.jpg:
#   It is on the LEFT outer edge of 83_1 (x < 95, y in [80..240]):
#   1) Alpha along the V-notch cut was hard-stepped (0 or 255) -> jagged stair-stepping!
#   2) The outermost 2..3px along that left silhouette (both upper breast bottom edge & lower breast left edge)
#      have pale whitish RGB (left over from the original gauze/highlight bleed)!
# Let's fix BOTH cleanly:
#   Step A: Slightly inset the jagged V-notch cut by 1.2px and apply smooth subpixel anti-aliasing (sigma=0.85)
#           ONLY in the left V-notch & lower-breast-left-rim zone (x < 95, y in [90..235])!
a_cur = v2_83_st[:, :, 3].copy()
left_rim_zone = (xx83 < 95) & (yy83 >= 85) & (yy83 <= 245) & uv83

# Compute signed distance to the opaque breast silhouette (a >= 128)
solid = (a_cur >= 128).astype(np.uint8)
dist_in = cv2.distanceTransform(solid, cv2.DIST_L2, 5)        # >0 inside solid
dist_out = cv2.distanceTransform(1 - solid, cv2.DIST_L2, 5)   # >0 outside solid

# In the left V-notch zone (x < 85, y in [105..225]):
#   - Pull alpha edge inward by 0.8px so the pale crusty outer 1px white fringe is gone,
#   - Replace hard step with silky 1.8px smooth anti-aliased ramp!
notch_zone = (xx83 < 85) & (yy83 >= 100) & (yy83 <= 230) & uv83
# Wait: don't nibble the lace cup on top-left (y < 108) or bottom-left lace tip (x < 25, y > 225)
# Only smooth the alpha border band where dist_in <= 3.5 and dist_out <= 2.5 inside notch_zone
border_band = notch_zone & (dist_in <= 3.5) & (dist_out <= 2.5)
# Signed distance: positive inside, negative outside
sdf = dist_in - dist_out
# Smooth AA alpha ramp: 0 at sdf <= 0.3, 255 at sdf >= 2.2 (insets 0.8px and gives 1.9px smooth AA!)
aa_alpha = np.clip((sdf - 0.35) / 1.85, 0.0, 1.0) * 255.0
# Smooth SDF slightly to eliminate any 1px pixel-staircase jitter!
sdf_smooth = cv2.GaussianBlur(sdf, (0, 0), sigmaX=1.0, sigmaY=1.0)
aa_alpha_smooth = np.clip((sdf_smooth - 0.45) / 1.75, 0.0, 1.0) * 255.0

a_new = a_cur.astype(np.float32)
# Blend smooth AA into notch_zone border (keep deep interior 255, deep exterior 0)
a_new[border_band] = aa_alpha_smooth[border_band]
a_new = np.clip(np.round(a_new), 0, 255).astype(np.uint8)

#   Step B: DEFRINGE RGB along the outermost 3.5px of that left breast rim (remove all bright white/grey fringe)!
#   For every pixel in `notch_zone` with `0 < dist_in <= 4.0` (the outer rim of the breasts facing the diamond/V-notch):
#   Replace its RGB with the clean interior breast contour color sampled ~3.5px further INWARD (where dist_in >= 3.5)!
rgb83_out = v2_83_st[:, :, :3].copy()
# Identify clean interior pixels (dist_in >= 3.5 and NOT bright white lace highlight G > 190 & B > 235)
# Actually: along the lower breast left rim (around y=170..225), just inside the rim is the dark purple-pink breast contour line!
# Let's check: any pixel in `notch_zone` with `dist_in <= 4.2` that is brighter/whiter than its inward neighbor -> replace with inward color!
clean_interior = (dist_in >= 3.8) & (a_cur >= 250) & uv83
# Build nearest clean interior pixel map using distanceTransformWithLabels!
# Note: restrict label source to clean_interior; compute nearest interior pixel for every pixel in the 363x315 patch!
_, labels_in = cv2.distanceTransformWithLabels((~clean_interior).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
# Map label id (1-based) to pixel coordinates!
int_ys, int_xs = np.where(clean_interior)
# distanceTransformWithLabels assigns labels 1..N in row-major order of zero pixels (clean_interior)!
# Wait: verify OpenCV label ordering safely by building lookup table directly!
lut_rgb = np.zeros((int(labels_in.max()) + 1, 3), dtype=np.uint8)
lut_rgb[labels_in[clean_interior]] = rgb83_out[clean_interior]
inward_rgb = lut_rgb[labels_in]  # (rh83, rw83, 3)

# Defringe band: outer 4px rim inside notch_zone where pixel is brighter (higher L) than inward_rgb, OR dist_in <= 2.8!
# Also gently darken outer 1.5px of the breast skin contour by -6 L (natural soft anime edge shadow against torso!)
rim_defringe = notch_zone & (a_new > 0) & (dist_in <= 4.2)
# Exclude the white lace scallops themselves ONLY if they are solid interior lace (actually in notch_zone y=110..215,
# look at fringe_and_belly_diag_50.jpg bottom-right: the white lace starts at y~185 bottom-left, and its outer edge IS white lace with a dark thin line!
# Wait: check whether lower lace cup touches the outer left rim in y=185..230!)
# Looking at QQ20261122-204148.png bottom red circle:
#   The white fringe runs along the SKIN of the lower breast right down to the lace border, AND along the outer rim of the lower lace where it meets the diamond!
#   Notice on the original AI image `gen_809pm`, that entire outer edge of the lower breast has a soft dark purple-pink contour line (NOT bright white)!
# So replacing pixels where `rim_defringe` with `inward_rgb` (or min(cur, inward) for luminance!) kills the white fringe cleanly without ever darkening the white lace interior!
cur_luma = rgb83_out.astype(np.float32).mean(axis=2)
inw_luma = inward_rgb.astype(np.float32).mean(axis=2)
# Smooth blend factor: 1.0 at dist_in <= 2.0, fading to 0.0 at dist_in == 4.2
w_def = np.clip((4.2 - dist_in) / 2.2, 0.0, 1.0) * notch_zone.astype(np.float32)
# Only apply where pixel is at the very outer rim (dist_in <= 2.2) OR brighter than inward color (white fringe!)
is_brighter = (cur_luma > inw_luma + 3.0) | (dist_in <= 2.4)
w_def = w_def * is_brighter.astype(np.float32)

rgb83_fixed = rgb83_out.astype(np.float32) * (1.0 - w_def[:, :, None]) + inward_rgb.astype(np.float32) * w_def[:, :, None]
# Add very subtle dark purple-pink contour antialias (-8 RGB on outermost 1.5px skin rim) so edge sits naturally on torso!
edge_shadow_w = np.clip((2.0 - dist_in) / 1.5, 0.0, 1.0) * (notch_zone & (a_new > 0)).astype(np.float32)
rgb83_fixed[:, :, 0] -= 6.0 * edge_shadow_w
rgb83_fixed[:, :, 1] -= 10.0 * edge_shadow_w
rgb83_fixed[:, :, 2] -= 4.0 * edge_shadow_w
rgb83_fixed = np.clip(np.round(rgb83_fixed), 0, 255).astype(np.uint8)

out83_st = v2_83_st.copy()
out83_st[:, :, :3] = rgb83_fixed
out83_st[:, :, 3] = a_new
out83_st[a_new == 0] = 0
out83_pma = straight_to_pma(out83_st)

# ==============================================================================
# PART 3: Assemble V3 test atlas starting from orig_atlas (STRICT zero leaks outside UV masks!)
# ==============================================================================
v3_atlas = orig_atlas.copy()
dst96 = v3_atlas[ry96:ry96+rh96, rx96:rx96+rw96].copy()
dst96[uv96] = out96_pma[uv96]
v3_atlas[ry96:ry96+rh96, rx96:rx96+rw96] = dst96

dst83 = v3_atlas[ry83:ry83+rh83, rx83:rx83+rw83].copy()
dst83[uv83] = out83_pma[uv83]
v3_atlas[ry83:ry83+rh83, rx83:rx83+rw83] = dst83

allowed = np.zeros((H, W), dtype=bool)
allowed[ry96:ry96+rh96, rx96:rx96+rw96] |= uv96
allowed[ry83:ry83+rh83, rx83:rx83+rw83] |= uv83
changed = np.abs(v3_atlas.astype(int) - orig_atlas.astype(int)).max(axis=2) > 0
leaked = changed & (~allowed)
print(f"Leaked pixels outside UV masks (96 + 83_1) vs ORIGINAL atlas: {int(leaked.sum())} (MUST BE 0)")
assert leaked.sum() == 0

v3_atlas_path = os.path.join(s, "SoulDress_Lilyiro_05_v3_test.png")
Image.fromarray(v3_atlas).save(v3_atlas_path)

# Save diagnostic preview of slot 96 V3
bg96 = Image.new("RGBA", (rw96, rh96), (35, 35, 45, 255))
c96_vis = out96_st.copy(); c96_vis[~uv96] = 0
bg96.alpha_composite(Image.fromarray(c96_vis))
bg96.convert("RGB").resize((rw96 // 2, rh96 // 2), Image.Resampling.LANCZOS).save(os.path.join(s, "slot96_v3_50.jpg"), "JPEG", quality=90)
print("Saved V3 test atlas and slot96_v3_50.jpg!")
