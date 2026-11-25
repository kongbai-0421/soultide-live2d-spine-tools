import os
import csv
import cv2
import numpy as np
from PIL import Image, ImageDraw

s = r".\_scratch\lilyiro05_inspect"
atlas_path = r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png"
atlas = np.array(Image.open(atlas_path).convert("RGBA"))
H, W = atlas.shape[:2]

# ==============================================================================
# Helper: PMA <-> Straight Alpha
# ==============================================================================
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

def load_uv_mask(csv_path, rx, ry, rw, rh):
    m = np.zeros((rh, rw), dtype=np.uint8)
    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.reader(f):
            v = [float(x) for x in row]
            pts = np.array([[v[6]-rx, v[7]-ry], [v[8]-rx, v[9]-ry], [v[10]-rx, v[11]-ry]], dtype=np.float32)
            cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 255)
    return m

# ==============================================================================
# STEP 1: Fix slot 96 (xy=432,1001 size=414,376) — Remove bright white oval via harmonic interpolation!
# ==============================================================================
rx96, ry96, rw96, rh96 = 432, 1001, 414, 376
uv96 = load_uv_mask(os.path.join(s, "mesh_96_idle0.csv"), rx96, ry96, rw96, rh96) > 0
sub96_pma = atlas[ry96:ry96+rh96, rx96:rx96+rw96].copy()
sub96_st = pma_to_straight(sub96_pma)

# Locate the full white oval on the left half of slot 96!
# Looking at slot96_oval_detect_50.jpg:
#   The oval sits roughly inside ellipse center=(92, 232), axes=(95, 76), angle=-20 deg,
#   AND there are 2 tiny faint bright dots just right of it around (205, 250) and (165, 115).
# Let's detect the exact oval mask cleanly using ellipse + luminance check inside uv96!
yy96, xx96 = np.mgrid[0:rh96, 0:rw96]
# Rotate coords around center (90, 236) by +16 deg to match the oval tilt
cx0, cy0 = 86.0, 234.0
theta = np.radians(16.0)
xr = (xx96 - cx0) * np.cos(theta) + (yy96 - cy0) * np.sin(theta)
yr = -(xx96 - cx0) * np.sin(theta) + (yy96 - cy0) * np.cos(theta)
# Oval covers center (86,234) out to right edge x~185, top y~155, bottom y~316, left x~0
oval_ell = ((xr / 104.0) ** 2 + (yr / 82.0) ** 2) <= 1.0

# Also include any bright pixel L > 170 on left x < 210 inside uv96 (catches any protruding rim of the oval!)
lab96 = cv2.cvtColor(sub96_st[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
oval_bright = (lab96[:, :, 0] > 170) & (xx96 < 210)
oval_mask = uv96 & (sub96_st[:, :, 3] >= 10) & (oval_ell | oval_bright)
# Dilate slightly (5px) inside uv96 to swallow the crisp circular edge completely!
oval_mask = (cv2.dilate(oval_mask.astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0) & uv96 & (sub96_st[:, :, 3] > 0)

print(f"[slot 96] Oval repair mask pixels: {int(oval_mask.sum())}")

# Solve smooth harmonic (Laplace) interpolation across oval_mask inside the valid torso domain!
# CRITICAL:
#   - known = opaque non-oval torso pixels (alpha >= 245) — NEVER include faint/dark outer AA pixels as known!
#   - domain = known | oval_mask (so Neumann BC applies cleanly at the outer silhouette of slot 96 -> ZERO black bleed!)
known = uv96 & (sub96_st[:, :, 3] >= 245) & (~oval_mask)
domain = known | oval_mask

rgb96_work = sub96_st[:, :, :3].astype(np.float32)
# Initialize oval_mask with mean color of known ring just around oval_mask (guarantees clean warm-pink start, zero black!)
ring = (cv2.dilate(oval_mask.astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))) > 0) & known
ring_mean = rgb96_work[ring].mean(axis=0)
print(f"[slot 96] Known boundary ring mean RGB: {ring_mean.round(1).tolist()}")

u = rgb96_work.copy()
u[oval_mask] = ring_mean

v_f = domain.astype(np.float32)
v_pad = np.pad(v_f, 1, mode='constant', constant_values=0.0)
n_cnt = v_pad[:-2, 1:-1] + v_pad[2:, 1:-1] + v_pad[1:-1, :-2] + v_pad[1:-1, 2:]
n_cnt = np.maximum(n_cnt, 1.0)

# Strictly stable Red-Black SOR (omega=1.80) for Laplace harmonic interpolation!
rb = ((yy96 + xx96) % 2) == 0
m_red = oval_mask & rb
m_blk = oval_mask & (~rb)
omega = 1.80

for it in range(450):
    u_valid = u * v_f[:, :, None]
    u_pad = np.pad(u_valid, ((1, 1), (1, 1), (0, 0)), mode='constant', constant_values=0.0)
    avg = (u_pad[:-2, 1:-1] + u_pad[2:, 1:-1] + u_pad[1:-1, :-2] + u_pad[1:-1, 2:]) / n_cnt[:, :, None]
    u[m_red] = u[m_red] + omega * (avg[m_red] - u[m_red])

    u_valid = u * v_f[:, :, None]
    u_pad = np.pad(u_valid, ((1, 1), (1, 1), (0, 0)), mode='constant', constant_values=0.0)
    avg = (u_pad[:-2, 1:-1] + u_pad[2:, 1:-1] + u_pad[1:-1, :-2] + u_pad[1:-1, 2:]) / n_cnt[:, :, None]
    u[m_blk] = u[m_blk] + omega * (avg[m_blk] - u[m_blk])
    u[known] = rgb96_work[known]

assert np.isfinite(u).all(), "Harmonic solve diverged!"
oval_feather = cv2.GaussianBlur(oval_mask.astype(np.float32), (0, 0), sigmaX=3.0, sigmaY=3.0)
oval_feather[~uv96] = 0.0
out96_rgb = np.clip(np.round(rgb96_work * (1.0 - oval_feather[:, :, None]) + u * oval_feather[:, :, None]), 0, 255).astype(np.uint8)
out96_st = sub96_st.copy()
out96_st[:, :, :3] = out96_rgb
out96_pma = straight_to_pma(out96_st)

# ==============================================================================
# STEP 2: Fix slot 83_1 (xy=2,752 size=363,315):
#   (2a) Remove left V-notch semi-transparent web (~259 px)
#   (2b) Lab color-match breast skin to surrounding torso skin (slot 96)!
# ==============================================================================
rx83, ry83, rw83, rh83 = 2, 752, 363, 315
uv83 = load_uv_mask(os.path.join(s, "mesh_83_1_idle0.csv"), rx83, ry83, rw83, rh83) > 0
sub83_pma = atlas[ry83:ry83+rh83, rx83:rx83+rw83].copy()
sub83_st = pma_to_straight(sub83_pma)

# (2a) Remove left V-notch semi-transparent web (x < 60, y in [105..195])
# Notice in slot96_and_notch_50.jpg: the web has alpha in [1..225] while the solid breasts on both sides have alpha >= 245!
# Use morphological opening on (a > 0) & (a < 238) in left zone so thin 1px breast outline AA is preserved, while the broad V-web is removed!
yy83, xx83 = np.mgrid[0:rh83, 0:rw83]
a83 = sub83_st[:, :, 3].copy()
left_zone = (xx83 < 65) & (yy83 >= 100) & (yy83 <= 200)
semi_web_cand = (left_zone & (a83 > 0) & (a83 < 242)).astype(np.uint8) * 255
# Opening with 3x3 ellipse removes 1px AA lines along breast contour, leaves the triangular web patch!
web_core = cv2.morphologyEx(semi_web_cand, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
# Dilate slightly ONLY within (a83 < 245) & left_zone so no semi-transparent fringe remains in the V-notch
web_mask = (cv2.dilate(web_core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0) & left_zone & (a83 < 246)
# Also remove any isolated low-alpha wispy pixels (a < 180) inside the V-notch
web_mask |= (left_zone & (a83 > 0) & (a83 < 175) & (xx83 < 45))
print(f"[slot 83_1] Left V-notch web removed pixels: {int(web_mask.sum())}")

sub83_st[web_mask] = 0

# (2b) Color-calibrate breast skin in 83_1 to match slot 96 torso skin seamlessly!
# Recompute clean pure-skin mask in 83_1 (same proven criteria that strictly excludes lace cups, straps, collar!)
rgb83 = sub83_st[:, :, :3].astype(np.float32)
R83, G83, B83 = rgb83[:, :, 0], rgb83[:, :, 1], rgb83[:, :, 2]
a83_new = sub83_st[:, :, 3]

is_skin83 = ((R83 - G83) >= 13) & (a83_new >= 200) & uv83
is_skin83[:, 255:] = False  # never touch collar
upper_lace = (xx83 < 115) & (yy83 < 130) & ((G83 > 182) | (B83 > 234))
lower_lace = (xx83 < 145) & (yy83 > 175) & ((G83 > 182) | (B83 > 234))
# Also exclude ONLY the bright white core of straps crossing right side of breasts (avoid leaving bright skin halo around straps!)
straps = (xx83 > 135) & (((G83 > 188) & (B83 > 228)) | ((B83 - R83) > 45))
is_skin83 &= (~upper_lace) & (~lower_lace) & (~straps)

# Keep main breast skin connected component(s)
nl, lbl, st_cc, _ = cv2.connectedComponentsWithStats(is_skin83.astype(np.uint8), connectivity=8)
skin83_cc = np.zeros_like(is_skin83)
for i in range(1, nl):
    if st_cc[i, cv2.CC_STAT_AREA] > 200:
        skin83_cc |= (lbl == i)
# Morphological close to include bright cleavage highlight & thin strap-adjacent skin cleanly
skin83_cc = cv2.morphologyEx(skin83_cc.astype(np.uint8) * 255, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0
# Re-exclude lace/straps/transparent
skin83_cc &= (~upper_lace) & (~lower_lace) & (~straps) & (a83_new >= 10) & uv83
# Soft feather mask so transition to lace/straps is 100% seamless
skin_w = cv2.GaussianBlur(skin83_cc.astype(np.float32), (0, 0), sigmaX=1.5, sigmaY=1.5)
skin_w[upper_lace | lower_lace | straps | (~uv83)] = 0.0

# Compute exact Lab color correction!
# Target reference: slot 96 breast-adjacent skin (Lab_mean = [156.6, 153.8, 98.1])
# Current 83_1 right-edge skin (Lab_mean = [160.9, 154.4, 95.0])
# Current 83_1 mid skin (Lab_mean = [165.4, 153.7, 96.7])
# Let's check exact delta on the skin_w > 0.8 pixels!
lab83 = cv2.cvtColor(sub83_st[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)

# Target Lab from repaired slot 96 breast-adjacent zone (x=210..275, y=100..260):
lab96_new = cv2.cvtColor(out96_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
ref96_patch = lab96_new[100:260, 210:275]
ref96_m = (out96_st[100:260, 210:275, 3] >= 250) & uv96[100:260, 210:275]
ref_L, ref_a, ref_b = ref96_patch[ref96_m].mean(axis=0)
print(f"[ColorCalib] Target slot96 adjacent Lab: [{ref_L:.2f}, {ref_a:.2f}, {ref_b:.2f}]")

# Measure 83_1 right-side skin (x=175..235, y=70..235) where it meets slot 96:
edge83_m = (skin_w > 0.7) & (xx83 >= 175) & (xx83 <= 235) & (a83_new >= 240)
cur_L, cur_a, cur_b = lab83[edge83_m].mean(axis=0)
print(f"[ColorCalib] Current 83_1 right-side Lab: [{cur_L:.2f}, {cur_a:.2f}, {cur_b:.2f}]")

dL_base = ref_L - cur_L   # negative (darkens slightly to remove remaining gauze lift!)
da_base = ref_a - cur_a   # subtle magenta/green alignment
db_base = ref_b - cur_b   # positive (+2.5..3.5, removes cold bluish cast so skin matches warm lavender-pink torso!)
print(f"[ColorCalib] Computed raw delta Lab: dL={dL_base:+.2f}, da={da_base:+.2f}, db={db_base:+.2f}")

# Apply smart highlight-preserving Lab correction:
# - Chroma (a*, b*): apply 100% of da_base, db_base across all skin pixels so hue/temperature matches torso identically!
# - Luminance (L*): apply full dL_base to midtones/shadows, taper down smoothly for bright specular highlights (L > 180)
#   so cleavage & breast specular highlights stay luminous & 3D!
L_ch = lab83[:, :, 0]
a_ch = lab83[:, :, 1]
b_ch = lab83[:, :, 2]

# Highlight protection factor: 1.0 when L <= 172, smoothly tapering to 0.35 when L >= 205
hl_protect = np.clip(1.0 - (L_ch - 172.0) / 50.0, 0.35, 1.0)
L_corr = np.clip(L_ch + dL_base * hl_protect * skin_w, 0.0, 255.0)
a_corr = np.clip(a_ch + da_base * skin_w, 0.0, 255.0)
b_corr = np.clip(b_ch + db_base * skin_w, 0.0, 255.0)

lab83_corr = np.dstack([L_corr, a_corr, b_corr]).astype(np.uint8)
rgb83_corr = cv2.cvtColor(lab83_corr, cv2.COLOR_LAB2RGB)

out83_st = sub83_st.copy()
out83_st[:, :, :3] = rgb83_corr
out83_st[a83_new == 0] = 0
out83_pma = straight_to_pma(out83_st)

# ==============================================================================
# STEP 3: Assemble test atlas (strictly inside UV masks of 96 and 83_1 ONLY!)
# ==============================================================================
test_atlas = atlas.copy()

# Write 96
dst96 = test_atlas[ry96:ry96+rh96, rx96:rx96+rw96].copy()
dst96[uv96] = out96_pma[uv96]
test_atlas[ry96:ry96+rh96, rx96:rx96+rw96] = dst96

# Write 83_1
dst83 = test_atlas[ry83:ry83+rh83, rx83:rx83+rw83].copy()
dst83[uv83] = out83_pma[uv83]
test_atlas[ry83:ry83+rh83, rx83:rx83+rw83] = dst83

# Strict zero-leak assertion
allowed = np.zeros((H, W), dtype=bool)
allowed[ry96:ry96+rh96, rx96:rx96+rw96] |= uv96
allowed[ry83:ry83+rh83, rx83:rx83+rw83] |= uv83
changed = np.abs(test_atlas.astype(int) - atlas.astype(int)).max(axis=2) > 0
leaked = changed & (~allowed)
print(f"Leaked pixels outside UV masks (96 + 83_1): {int(leaked.sum())} (MUST BE 0)")
assert leaked.sum() == 0

test_atlas_path = os.path.join(s, "SoulDress_Lilyiro_05_v2_test.png")
Image.fromarray(test_atlas).save(test_atlas_path)

# Diagnostic sheet for slot 96 & slot 83_1
def on_bg(st_rgba):
    bg = Image.new("RGBA", (st_rgba.shape[1], st_rgba.shape[0]), (35, 35, 45, 255))
    bg.alpha_composite(Image.fromarray(st_rgba))
    return bg.convert("RGB")

diag = Image.new("RGB", (rw96 * 2 + rw83 + 40, max(rh96, rh83) + 50), (20, 20, 25))
dr = ImageDraw.Draw(diag)
# Clean original 96 vis
c96_orig = sub96_st.copy(); c96_orig[~uv96] = 0
c96_new = out96_st.copy(); c96_new[~uv96] = 0
c83_new = out83_st.copy(); c83_new[~uv83] = 0
diag.paste(on_bg(c96_orig), (10, 35)); dr.text((10, 10), "slot 96 BEFORE (white oval)", fill=(255,255,0))
diag.paste(on_bg(c96_new), (rw96 + 20, 35)); dr.text((rw96 + 20, 10), "slot 96 AFTER (harmonic clean)", fill=(255,255,0))
diag.paste(on_bg(c83_new), (rw96 * 2 + 30, 35)); dr.text((rw96 * 2 + 30, 10), "slot 83_1 AFTER (V-notch + Lab calib)", fill=(255,255,0))
diag.resize((diag.width // 2, diag.height // 2), Image.Resampling.LANCZOS).save(os.path.join(s, "v2_parts_diag_50.jpg"), "JPEG", quality=88)
print("Saved v2 test atlas and v2_parts_diag_50.jpg!")
