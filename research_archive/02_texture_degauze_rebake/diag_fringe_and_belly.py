import os
import csv
import cv2
import numpy as np
from PIL import Image, ImageDraw

s = r".\_scratch\lilyiro05_inspect"
orig_atlas = np.array(Image.open(s + r"\SoulDress_Lilyiro_05_orig_with_gauze_backup.png").convert("RGBA"))
curr_atlas = np.array(Image.open(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png").convert("RGBA"))
gen_im = np.array(Image.open(r"E:\库\下载\Generated Image November 22, 2026 - 8_09PM.jpg").convert("RGB"))
M_gen_to_06 = np.load(s + r"\M_gen_to_06_context.npy")
M_06_to_gen = cv2.invertAffineTransform(M_gen_to_06)

# 1. Crop diamond opening in gen_im (in 06_context 700x700 coords, diamond + V-notch is roughly x=0..220, y=240..460)
# Map [0..220, 240..460] to gen_im (2048x2048) -> ~ [0..644, 702..1346]
g_crop = gen_im[680:1360, 0:680]  # 680x680!

# 2. Crop same region in v2_test_render (crop of 1000x900: offset x=80, y=180 -> x=80..300, y=420..640)
v2_ren = np.array(Image.open(s + r"\v2_test_render.png").convert("RGB"))
v2_crop = v2_ren[413:645, 80:312]  # 232x232 -> upscale 2x for inspection

# 3. Also inspect original slot 96 left half (x=0..240, y=120..360) with contrast boost to see what's painted under the white oval!
orig96 = orig_atlas[1001:1001+376, 432:432+414]
o96_crop = orig96[120:360, 0:240, :3]
o96_enh = np.clip((o96_crop.astype(np.float32) - o96_crop.mean()) * 2.5 + 128, 0, 255).astype(np.uint8)

# 4. Inspect current 83_1 left V-notch & breast outer edges (x=0..110, y=90..220) zoomed 4x on dark skin color (155,120,185)!
curr83 = curr_atlas[752:752+315, 2:2+363]
z83 = curr83[90:220, 0:110]
# Composite PMA onto torso skin tone [166, 133, 200] to clearly expose the EXACT white fringe pixels!
bg_skin = np.zeros((130, 110, 3), dtype=np.float32)
bg_skin[:, :, 0] = 166; bg_skin[:, :, 1] = 133; bg_skin[:, :, 2] = 200
a = z83[:, :, 3:4].astype(np.float32) / 255.0
comp_skin = np.clip(z83[:, :, :3].astype(np.float32) + bg_skin * (1.0 - a), 0, 255).astype(np.uint8)

# Build 2x2 inspection board
board = Image.new("RGB", (920, 960), (20, 20, 25))
d = ImageDraw.Draw(board)
board.paste(Image.fromarray(g_crop).resize((440, 440), Image.Resampling.LANCZOS), (10, 30)); d.text((10, 8), "AI gen_809pm diamond opening (HD)", fill=(255,255,0))
board.paste(Image.fromarray(v2_crop).resize((440, 440), Image.Resampling.NEAREST), (470, 30)); d.text((470, 8), "Current V2 render (zoomed)", fill=(255,255,0))
board.paste(Image.fromarray(o96_enh).resize((440, 440), Image.Resampling.LANCZOS), (10, 505)); d.text((10, 483), "Orig slot 96 left oval (contrast x2.5)", fill=(255,255,0))
board.paste(Image.fromarray(comp_skin).resize((440, 440), Image.Resampling.NEAREST), (470, 505)); d.text((470, 483), "Curr 83_1 edge over skin tone (exposes white fringe!)", fill=(255,255,0))

board.resize((board.width // 2, board.height // 2), Image.Resampling.LANCZOS).save(s + r"\fringe_and_belly_diag_50.jpg", "JPEG", quality=90)
print("Saved fringe_and_belly_diag_50.jpg")
