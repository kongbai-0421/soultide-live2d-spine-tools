import numpy as np
from PIL import Image, ImageDraw

out_dir = r".\_scratch\lilyiro05_inspect"
w = np.array(Image.open(out_dir + r"\111_warped_to_setup.png").convert("RGBA"), dtype=np.float32)
s = np.array(Image.open(out_dir + r"\setup_pose_full.png").convert("RGBA"), dtype=np.float32)
n96 = np.array(Image.open(out_dir + r"\setup_pose_96.png").convert("RGBA"), dtype=np.float32)

# Print exact diff inside the strap triangle (x=1310..1490, y=560..780 in setup coords)
tx0, ty0, tx1, ty1 = 1280, 560, 1520, 820
wt = w[ty0:ty1, tx0:tx1, :3] * (w[ty0:ty1, tx0:tx1, 3:4] / 255.0)
st = s[ty0:ty1, tx0:tx1, :3]
nt = n96[ty0:ty1, tx0:tx1, :3]

d_ws = np.abs(st - wt)
d_sn = st - nt # how much brighter/whiter setup is over bare torso 96!
d_wn = wt - nt

print("Triangle [1280:1520, 560:820]:")
print("  |Setup - 111|: mean=", d_ws.mean(), "p50=", np.median(d_ws), "p90=", np.percentile(d_ws, 90))
print("  (Setup - 96) RGB mean:", d_sn.mean(axis=(0,1)), "p90:", np.percentile(d_sn, 90, axis=(0,1)))
print("  (111 - 96)   RGB mean:", d_wn.mean(axis=(0,1)), "p90:", np.percentile(d_wn, 90, axis=(0,1)))

# Check full body diff between 111 and SetupPose (save 50% visual so we can see EVERY difference on the whole body!)
w_full = w[:, :, :3] * (w[:, :, 3:4] / 255.0)
s_full = s[:, :, :3]
diff_full = np.clip(np.abs(s_full - w_full) * 3.0, 0, 255).astype(np.uint8)
# Crop body area x=100..2100, y=100..1650
Image.fromarray(diff_full[100:1650, 100:2100]).resize((1000, 775), Image.Resampling.LANCZOS).save(
    out_dir + r"\fullbody_diff_111_vs_setup_50.jpg", "JPEG", quality=85
)

# Zoom 2x on the triangle region [1240:1540, 540:840] (300x300 -> 3 panels -> 940x360 -> 50% = 470x180, wait: let's make each panel 600x600 so 50% is 300x300 = 1:1!)
zx0, zy0, zx1, zy1 = 1150, 520, 1550, 920 # 400x400
def norm_enh(arr):
    # High contrast enhance to make translucent gauze clearly visible
    m = np.median(arr)
    return np.clip((arr - m) * 2.5 + 128, 0, 255).astype(np.uint8)

p1 = Image.fromarray(norm_enh(w_full[zy0:zy1, zx0:zx1]))
p2 = Image.fromarray(norm_enh(s_full[zy0:zy1, zx0:zx1]))
p3 = Image.fromarray(norm_enh(n96[zy0:zy1, zx0:zx1, :3]))
p4 = Image.fromarray(np.clip(np.abs(s_full[zy0:zy1, zx0:zx1] - w_full[zy0:zy1, zx0:zx1]) * 8.0, 0, 255).astype(np.uint8))

# Put 4 panels 2x2 at 800x800 each? No, keep original 400x400 -> 820x860 -> 50% = 410x430
zoom_board = Image.new("RGB", (830, 870), (20, 20, 25))
dz = ImageDraw.Draw(zoom_board)
zoom_board.paste(p1, (10, 30)); dz.text((10, 8), "111.png (contrast x2.5)", fill=(255,255,0))
zoom_board.paste(p2, (420, 30)); dz.text((420, 8), "Spine SetupPose (contrast x2.5)", fill=(255,255,0))
zoom_board.paste(p3, (10, 460)); dz.text((10, 438), "Spine slot 96 bare torso (contrast x2.5)", fill=(255,255,0))
zoom_board.paste(p4, (420, 460)); dz.text((420, 438), "|Setup - 111| x8", fill=(255,255,0))
zoom_board.resize((zoom_board.width // 2, zoom_board.height // 2), Image.Resampling.LANCZOS).save(
    out_dir + r"\triangle_zoom_50.jpg", "JPEG", quality=88
)
print("Saved triangle_zoom_50.jpg and fullbody_diff_111_vs_setup_50.jpg")
