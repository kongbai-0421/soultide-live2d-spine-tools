import csv
import cv2
import numpy as np
from PIL import Image, ImageDraw

s = r".\_scratch\lilyiro05_inspect"
atlas = np.array(Image.open(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png").convert("RGBA"))
orig_atlas = np.array(Image.open(s + r"\SoulDress_Lilyiro_05_orig_with_gauze_backup.png").convert("RGBA"))
render = np.array(Image.open(s + r"\final_applied_render.png").convert("RGB"))

# 1. Measure skin RGB & Lab across 3 zones in final_applied_render (1000x900):
# Wait: crop (80, 180, 780, 880) is 06_context (700x700). Let's work in 06_context coords!
ctx = render[180:880, 80:780]  # 700x700
# Also load layer_96_redbox & layer_83_1_redbox? Better: measure directly in atlas space for 96 (neck/collarbone side) vs 83_1 (breast skin) vs 97/79 (arms)!
# In atlas:
#   slot 96: xy=432,1001 size=414,376
#   slot 83_1: xy=2,752 size=363,315
s96 = atlas[1001:1001+376, 432:432+414]
s83_1 = atlas[752:752+315, 2:2+363]
s83_1_orig = orig_atlas[752:752+315, 2:2+363]

def stats(name, rgb_arr):
    # rgb_arr: Nx3 uint8
    lab = cv2.cvtColor(rgb_arr.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    m_rgb = rgb_arr.mean(axis=0)
    m_lab = lab.mean(axis=0)
    s_lab = lab.std(axis=0)
    print(f"{name:26s}: N={len(rgb_arr):5d}  RGB_mean=[{m_rgb[0]:5.1f},{m_rgb[1]:5.1f},{m_rgb[2]:5.1f}]  Lab_mean=[{m_lab[0]:5.1f},{m_lab[1]:5.1f},{m_lab[2]:5.1f}]  Lab_std=[{s_lab[0]:4.1f},{s_lab[1]:4.1f},{s_lab[2]:4.1f}]")

# Sample clean torso skin on slot 96 (right half, away from white oval, away from collarbone lines):
# In 96 (414x376): white oval is roughly x in [0..220], y in [140..330]; clean mid-chest/collarbone skin is x in [210..330], y in [120..260]
m96_clean = s96[120:260, 220:340]
m96_clean_px = m96_clean[m96_clean[:, :, 3] >= 250, :3]
stats("slot96 clean torso skin", m96_clean_px)

# Sample slot 96 right near where 83_1 breast right edge meets 96 (x in [200..260], y in [100..280])
m96_border = s96[100:260, 210:270]
m96_border_px = m96_border[m96_border[:, :, 3] >= 250, :3]
stats("slot96 breast-adjacent", m96_border_px)

# Sample slot 96 white oval interior (x in [40..170], y in [180..290])
m96_oval = s96[180:290, 40:170]
m96_oval_px = m96_oval[m96_oval[:, :, 3] >= 250, :3]
stats("slot96 WHITE OVAL", m96_oval_px)

# Sample 83_1 current AI-baked skin (mid breast region: x in [120..220], y in [80..230], excluding straps/lace)
sub_83_curr = s83_1[80:230, 120:220]
sub_83_orig = s83_1_orig[80:230, 120:220]
mask_skin_sample = (sub_83_curr[:, :, 3] >= 250) & ((sub_83_curr[:, :, 0].astype(int) - sub_83_curr[:, :, 1].astype(int)) >= 15) & (sub_83_curr[:, :, 1] < 185)
stats("83_1 CURRENT (AI baked)", sub_83_curr[mask_skin_sample, :3])
stats("83_1 ORIG (pre-AI)", sub_83_orig[mask_skin_sample, :3])

# Also sample right edge of 83_1 breasts (x in [180..225], y in [70..230]) vs 96 adjacent!
sub_83_edge = s83_1[70:230, 180:225]
mask_edge = (sub_83_edge[:, :, 3] >= 250) & ((sub_83_edge[:, :, 0].astype(int) - sub_83_edge[:, :, 1].astype(int)) >= 15) & (sub_83_edge[:, :, 1] < 185)
stats("83_1 RIGHT EDGE (curr)", sub_83_edge[mask_edge, :3])

# Also sample arm skin (slot 97: xy=2,1436 size=172,326 rot=180; slot 79: xy=757,712 size=282,235 rot=true)
s97 = atlas[1436:1436+326, 2:2+172]
m97 = s97[100:240, 50:120]
m97_px = m97[(m97[:, :, 3] >= 250) & ((m97[:,:,0].astype(int)-m97[:,:,1].astype(int)) >= 15), :3]
stats("slot97 arm skin", m97_px)

# Detect the exact bright white oval in slot 96!
# Build UV mask for 96
rw96, rh96 = 414, 376
m96_uv = np.zeros((rh96, rw96), dtype=np.uint8)
with open(s + r"\mesh_96_idle0.csv", "r", encoding="utf-8") as f:
    for row in csv.reader(f):
        v = [float(x) for x in row]
        pts = np.array([[v[6]-432, v[7]-1001], [v[8]-432, v[9]-1001], [v[10]-432, v[11]-1001]], dtype=np.float32)
        cv2.fillPoly(m96_uv, [np.round(pts).astype(np.int32)], 255)

# In slot 96, check luminance L and (B, G) to see how cleanly the white oval separates from normal torso skin!
lab96 = cv2.cvtColor(s96[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
L96 = lab96[:, :, 0]
# Also check left side x < 230
oval_cand = (m96_uv > 0) & (s96[:, :, 3] >= 200) & (L96 > 176) & (np.arange(rw96)[None, :] < 235)
print(f"slot96 oval candidate pixels (L>176, x<235): {int(oval_cand.sum())}")
# Also check where the diamond opening projects onto slot 96!
# Save visual of slot 96 with oval_cand outline + L96 heatmap!
vis96 = s96[:, :, :3].copy()
vis96[oval_cand, 1] = np.clip(vis96[oval_cand, 1].astype(int) + 90, 0, 255).astype(np.uint8)
Image.fromarray(vis96).resize((rw96 // 2, rh96 // 2), Image.Resampling.LANCZOS).save(s + r"\slot96_oval_detect_50.jpg", "JPEG", quality=88)
print("Saved slot96_oval_detect_50.jpg")
