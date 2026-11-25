import numpy as np
from PIL import Image, ImageDraw

out_dir = r".\_scratch\lilyiro05_inspect"

def get_crop(path, x, y, w, h, rot=False):
    im = Image.open(path).convert("RGBA")
    if rot:
        return im.crop((x, y, x+h, y+w)).rotate(-90, expand=True)
    return im.crop((x, y, x+w, y+h))

c0 = np.array(get_crop(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png", 2, 752, 363, 315, False))
c2 = np.array(get_crop(r"E:\A灵魂潮汐\备份\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png", 2617, 1444, 363, 315, True))
c5 = np.array(get_crop(r"E:\A灵魂潮汐\备份\spine\莉莉艾洛\花与剑的交织\莉莉婚纱无背景\1\SoulDress_Lilyiro_05.png", 2419, 823, 363, 315, False))

print("c2 vs c5 max diff:", np.abs(c2.astype(int) - c5.astype(int)).max())

# Check diff between c0 and c2:
d_rgb = np.abs(c0[:, :, :3].astype(int) - c2[:, :, :3].astype(int))
d_a = np.abs(c0[:, :, 3].astype(int) - c2[:, :, 3].astype(int))
print("c0 vs c2: rgb diff>5 px:", int((d_rgb.max(axis=2) > 5).sum()), "alpha diff>5 px:", int((d_a > 5).sum()))

# Check if c0 is straight alpha or premultiplied alpha!
# In straight alpha, pixels with small alpha (e.g. a=19) can have RGB > a (like 200, 180, 220).
# In premultiplied alpha, RGB <= a ALWAYS!
a0 = c0[:, :, 3]
rgb0_max = c0[:, :, :3].max(axis=2)
exceed0 = (rgb0_max > a0 + 2) & (a0 > 0) & (a0 < 250)
a2 = c2[:, :, 3]
rgb2_max = c2[:, :, :3].max(axis=2)
exceed2 = (rgb2_max > a2 + 2) & (a2 > 0) & (a2 < 250)
print(f"c0 (curr) RGB > Alpha count (semi px): {int(exceed0.sum())} -> {'STRAIGHT' if exceed0.sum() > 100 else 'PREMULTIPLIED'}")
print(f"c2 (bak)  RGB > Alpha count (semi px): {int(exceed2.sum())} -> {'STRAIGHT' if exceed2.sum() > 100 else 'PREMULTIPLIED'}")

# Sample triangle pixels in c0 vs c2
for (px, py, desc) in [(250, 145, "mid tri"), (235, 110, "upper tri"), (225, 175, "lower tri"), (120, 130, "cleavage"), (80, 195, "lower breast top"), (160, 140, "chest center")]:
    print(f"  ({px},{py}) {desc:16s} c0={c0[py,px].tolist()}  c2={c2[py,px].tolist()}")

# Visualize c0 vs c2 RGB diff & Alpha diff at 2x (then 50% preview = 1:1!)
# Wait: per global rule, save full 4-panel board and its 50% preview.
W, H = 363, 315
def on_black_pma(arr):
    # composite PMA on dark grey (30,30,35)
    a = arr[:, :, 3:4].astype(np.float32) / 255.0
    rgb = arr[:, :, :3].astype(np.float32)
    out = np.clip(rgb + 30.0 * (1.0 - a), 0, 255).astype(np.uint8)
    return out

board = Image.new("RGB", (W * 2 + 30, H * 2 + 70), (20, 20, 25))
dr = ImageDraw.Draw(board)
board.paste(Image.fromarray(on_black_pma(c0)), (10, 30)); dr.text((10, 8), "c0 (Current)", fill=(255,255,0))
board.paste(Image.fromarray(on_black_pma(c2)), (W+20, 30)); dr.text((W+20, 8), "c2 (Backup Modified)", fill=(255,255,0))
board.paste(Image.fromarray(np.clip(d_rgb * 4, 0, 255).astype(np.uint8)), (10, H+55)); dr.text((10, H+35), "|c0 - c2| RGB x4", fill=(255,255,0))
# Alpha diff: red = c0 > c2 (removed alpha), green = c2 > c0 (added alpha)
advis = np.zeros((H, W, 3), dtype=np.uint8)
advis[:, :, 0] = np.clip((c0[:, :, 3].astype(int) - c2[:, :, 3].astype(int)) * 4, 0, 255).astype(np.uint8)
advis[:, :, 1] = np.clip((c2[:, :, 3].astype(int) - c0[:, :, 3].astype(int)) * 4, 0, 255).astype(np.uint8)
advis[:, :, 2] = (c2[:, :, 3] > 2).astype(np.uint8) * 60
board.paste(Image.fromarray(advis), (W+20, H+55)); dr.text((W+20, H+35), "Alpha diff (Red=removed in c2, Blue=c2 mask)", fill=(255,255,0))

board.save(out_dir + r"\c0_vs_c2_full.png")
board.resize((board.width // 2, board.height // 2), Image.Resampling.LANCZOS).save(out_dir + r"\c0_vs_c2_50.jpg", "JPEG", quality=88)
print("Saved c0_vs_c2_50.jpg")
