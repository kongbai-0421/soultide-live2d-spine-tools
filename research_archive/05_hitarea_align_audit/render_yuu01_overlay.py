import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

cache = json.loads(Path(r"E:\A灵魂潮汐\tools\_spine38_geom_cache.json").read_text(encoding="utf-8-sig"))

# 1. Inspect 朔耶真子/真子漂流记
g_m = cache["朔耶真子/真子漂流记"]
cfg_m = json.loads(Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\朔耶真子\真子漂流记\.config.json").read_text(encoding="utf-8"))
bmap_m = {b["name"]: b for b in g_m["bones"]}
print("=== 朔耶真子/真子漂流记 ===")
for ha in cfg_m["hit_areas"]:
    b = bmap_m[ha["id"]]
    print(" ", ha, "bone_w=", (b["wx"], b["wy"]), "vc=", (b.get("vcx"), b.get("vcy")))

# 2. Inspect & render 月本柚/原皮 onto QQ20261119-210903.png
g_y = cache["月本柚/原皮"]
cfg_y = json.loads(Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\月本柚\原皮\.config.json").read_text(encoding="utf-8"))
bmap_y = {b["name"]: b for b in g_y["bones"]}
print("\n=== 月本柚/原皮 new hit_areas ===")
for ha in cfg_y["hit_areas"]:
    b = bmap_y[ha["id"]]
    bx = b["wx"] + float(ha.get("center_x", 0.0)) * 100.0
    by = b["wy"] + float(ha.get("center_y", 0.0)) * 100.0
    print(f"  {ha['name']} ({ha['id']}): center_sp=({bx:.1f}, {by:.1f}), size_sp=({ha['width']*100:.0f}, {ha['height']*100:.0f})")

# Fit screenshot transform from the old red boxes in QQ20261119-210903.png:
# Old '足' (bone '1', wx=-45.3, wy=71.9, cx=0.15, cy=0.78 -> sp=(-30.3, 149.9), size=(458, 293))
# Old '腿' (bone '2', wx=175.2, wy=286.6 -> sp=(175.2, 286.6), size=(550, 513))
# Old '头' (bone 'u_81', wx=11.0, wy=1918.0?, cx=0.23, cy=-1.84 -> sp=(34, 1734))
# Let's detect exact red-box centers in QQ20261119-210903.png to fit (s_px, ox, oy)!
import numpy as np
img = Image.open(r"E:\库\下载\QQ20261119-210903.png").convert("RGB")
arr = np.array(img)
red_mask = (arr[:, :, 0] > 210) & (arr[:, :, 1] < 90) & (arr[:, :, 2] < 90)
ys, xs = np.where(red_mask)
# Top red edge of old '头' box vs bottom red edge of old '足' box:
print(f"Screenshot red pixels bounds: x=[{xs.min()}, {xs.max()}], y=[{ys.min()}, {ys.max()}]")

# Old '头' box (u_81):
u81 = bmap_y["u_81"]
old_head_cy = u81["wy"] - 1.84 * 100.0
old_head_top = old_head_cy + 4.21 * 50.0
# Old '足' box (1):
b1 = bmap_y["1"]
old_foot_cy = b1["wy"] + 0.78 * 100.0
old_foot_bot = old_foot_cy - 2.93 * 50.0
# Old '腿' box (2):
b2 = bmap_y["2"]
old_leg_right = b2["wx"] + 5.50 * 50.0
old_foot_left = b1["wx"] + 0.15 * 100.0 - 4.58 * 50.0

s_px = (ys.max() - ys.min()) / (old_head_top - old_foot_bot)
ox = xs.max() - old_leg_right * s_px
oy = ys.min() + old_head_top * s_px
print(f"Fitted camera: s_px={s_px:.4f}, ox={ox:.1f}, oy={oy:.1f}")

draw = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 28)
except Exception:
    font = ImageFont.load_default()

for ha in cfg_y["hit_areas"]:
    b = bmap_y[ha["id"]]
    cx_sp = b["wx"] + float(ha.get("center_x", 0.0)) * 100.0
    cy_sp = b["wy"] + float(ha.get("center_y", 0.0)) * 100.0
    w_sp = float(ha["width"]) * 100.0
    h_sp = float(ha["height"]) * 100.0
    px = ox + cx_sp * s_px
    py = oy - cy_sp * s_px
    pw = w_sp * s_px
    ph = h_sp * s_px
    x0, y0, x1, y1 = px - pw / 2, py - ph / 2, px + pw / 2, py + ph / 2
    draw.rectangle([x0, y0, x1, y1], outline=(0, 220, 60), width=6)
    label = f"{ha['name']} ({ha['id']})"
    draw.rectangle([x0, max(0, y0 - 34), x0 + len(label) * 16 + 16, max(34, y0)], fill=(0, 150, 40))
    draw.text((x0 + 8, max(2, y0 - 32)), label, fill=(255, 255, 255), font=font)

out_full = Path(r".\_scratch\yuu01_orig_touch_before_after.png")
out_prev = Path(r".\_scratch\yuu01_orig_touch_before_after_preview.jpg")
img.save(out_full, "PNG")
w, h = max(1, img.width // 2), max(1, img.height // 2)
img.resize((w, h), Image.Resampling.LANCZOS).save(out_prev, "JPEG", quality=80)
print("Saved preview:", out_prev)
