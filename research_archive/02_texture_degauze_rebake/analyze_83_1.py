import numpy as np
from PIL import Image, ImageDraw

atlas = np.array(Image.open(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png").convert("RGBA"))
# 83_1: xy=2,752 size=363,315
r83_1 = atlas[752:752+315, 2:2+363]
# 96: xy=432,1001 size=414,376
r96 = atlas[1001:1001+376, 432:432+414]

print("83_1 shape:", r83_1.shape)
a = r83_1[:, :, 3]
# Find semi-transparent pixels (5 < a < 245)
semi = (a > 5) & (a < 245)
print("83_1 semi-transparent pixels count:", int(semi.sum()), f"({semi.mean()*100:.2f}%)")

# Visualize where semi-transparent pixels are in 83_1 (highlight in bright red/yellow by alpha)
vis = np.zeros((315, 363, 3), dtype=np.uint8)
# Background checkerboard
yy, xx = np.mgrid[0:315, 0:363]
chk = (((xx // 8) + (yy // 8)) % 2) * 30 + 30
vis[:, :, 0] = chk; vis[:, :, 1] = chk; vis[:, :, 2] = chk

# Composite 83_1 PMA onto vis
af = a.astype(np.float32) / 255.0
for c in range(3):
    vis[:, :, c] = np.clip(r83_1[:, :, c].astype(np.float32) + vis[:, :, c].astype(np.float32) * (1.0 - af), 0, 255).astype(np.uint8)

# Second panel: alpha heatmap (0=black, 1..250=colored jet-like, 251..255=white)
heat = np.zeros((315, 363, 3), dtype=np.uint8)
heat[a >= 250] = [255, 255, 255]
mid = (a > 2) & (a < 250)
heat[mid, 0] = np.clip(a[mid].astype(np.int32) * 2, 0, 255).astype(np.uint8)
heat[mid, 1] = np.clip(255 - np.abs(a[mid].astype(np.int32) - 128) * 2, 0, 255).astype(np.uint8)
heat[mid, 2] = np.clip(255 - a[mid].astype(np.int32), 0, 255).astype(np.uint8)

# Third panel: zoom into the upper chest / straps region of 111.png vs current_main_render.png
im111 = Image.open(r"E:\库\下载\111.png").convert("RGB")
imcur = Image.open(r".\_scratch\lilyiro05_inspect\current_main_render.png").convert("RGB")

# Combine vis + heat at 2x so 50% preview is 1:1
panel = Image.new("RGB", (363 * 2 + 30, 315 + 40), (20, 20, 20))
panel.paste(Image.fromarray(vis), (10, 30))
panel.paste(Image.fromarray(heat), (383, 30))
d = ImageDraw.Draw(panel)
d.text((10, 8), "83_1 over checkerboard (PMA)", fill=(255,255,0))
d.text((383, 8), "83_1 Alpha Heatmap (white>=250, color=semi, black<=2)", fill=(255,255,0))

# Save 1:1 raw and 50% scaled for agent viewing (Wait: 363*2+30=756 -> resize 2x then 50% is cheating! Let's respect rule: save full panel and 50% preview)
panel.save(r".\_scratch\lilyiro05_inspect\83_1_heat_full.png")
panel.resize((panel.width // 2, panel.height // 2), Image.Resampling.LANCZOS).save(
    r".\_scratch\lilyiro05_inspect\83_1_heat_50.jpg", "JPEG", quality=85
)

# Print alpha stats inside the triangle between straps (rough box x=210..300, y=50..180)
tri_box = r83_1[50:180, 210:300]
print("Triangle box alpha percentiles [10,25,50,75,90]:", np.percentile(tri_box[:, :, 3], [10, 25, 50, 75, 90]))
# Sample specific points in 83_1:
for (px, py, desc) in [
    (255, 85, "upper strap triangle"),
    (250, 145, "mid strap triangle"),
    (120, 130, "cleavage skin"),
    (180, 160, "lower breast skin"),
    (50, 50, "top lace"),
]:
    print(f"  ({px},{py}) {desc}: RGBA={r83_1[py, px].tolist()}")

# Also check if 111.png has the EXACT same gauze as current_main_render.png
# Check histogram/crop of 111.png around the strap triangle
print("111.png size:", im111.size, "current_main_render size:", imcur.size)
