import os
from PIL import Image, ImageDraw

base = r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织"
atlas_path = os.path.join(base, "SoulDress_Lilyiro_05.atlas.txt")
png_path = os.path.join(base, "SoulDress_Lilyiro_05.png")
out_dir = r".\_scratch\lilyiro05_inspect"

regions = {}
cur = None
with open(atlas_path, "r", encoding="utf-8") as f:
    for line in f:
        s = line.rstrip("\r\n")
        if not s or s.endswith(".png") or s.startswith(("size:", "format:", "filter:", "repeat:")):
            continue
        if not s.startswith("  "):
            cur = s.strip()
            regions[cur] = {}
        elif cur:
            k, v = s.strip().split(":", 1)
            regions[cur][k.strip()] = v.strip()

atlas_img = Image.open(png_path).convert("RGBA")

# Check bu_* and 83_1 alpha/overlay
bu_names = [k for k in regions.keys() if k.startswith("bu_")]
print("bu regions:", bu_names)

cell = 300
cols = 5
rows = (len(bu_names) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cell, rows * cell), (35, 35, 45))
draw = ImageDraw.Draw(sheet)
for idx, name in enumerate(bu_names):
    r = regions[name]
    x, y = [int(v) for v in r["xy"].split(",")]
    w, h = [int(v) for v in r["size"].split(",")]
    crop = atlas_img.crop((x, y, x + w, y + h))
    scale = min((cell - 20) / max(1, w), (cell - 40) / max(1, h))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    thumb = crop.resize((nw, nh), Image.Resampling.LANCZOS)
    cx, cy = (idx % cols) * cell, (idx // cols) * cell
    bg = Image.new("RGBA", (nw, nh), (55, 55, 70, 255))
    bg.alpha_composite(thumb)
    sheet.paste(bg.convert("RGB"), (cx + (cell - nw)//2, cy + 30 + (cell - 40 - nh)//2))
    draw.text((cx + 8, cy + 6), f"{name} ({w}x{h})", fill=(255, 240, 120))

sheet.resize((sheet.width // 2, sheet.height // 2), Image.Resampling.LANCZOS).save(
    os.path.join(out_dir, "bu_regions_50.jpg"), "JPEG", quality=85
)

# Also inspect 83_1 closely: is there translucent gauze over the chest inside 83_1 itself?
# Let's zoom in on 83_1 vs 111.png at higher resolution (100% crop -> 50% preview -> actually keep 2x zoom so 50% preview is 1:1!)
r83_1 = regions["83_1"]
x, y = [int(v) for v in r83_1["xy"].split(",")]
w, h = [int(v) for v in r83_1["size"].split(",")]
c83_1 = atlas_img.crop((x, y, x + w, y + h))

# Composite 83_1 over 96 (torso behind it!) or black vs white to see alpha!
on_black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
on_black.alpha_composite(c83_1)
on_green = Image.new("RGBA", (w, h), (0, 255, 0, 255))
on_green.alpha_composite(c83_1)
alpha_vis = c83_1.split()[3].convert("RGB")

# Compare on_black, on_green, alpha_vis
z = Image.new("RGB", (w * 3 + 40, h + 60), (25, 25, 30))
dz = ImageDraw.Draw(z)
z.paste(on_black.convert("RGB"), (10, 40))
dz.text((10, 10), "83_1 on BLACK", fill=(255, 255, 100))
z.paste(on_green.convert("RGB"), (w + 20, 40))
dz.text((w + 20, 10), "83_1 on GREEN (check alpha)", fill=(255, 255, 100))
z.paste(alpha_vis, (w * 2 + 30, 40))
dz.text((w * 2 + 30, 10), "83_1 ALPHA channel", fill=(255, 255, 100))
z.resize((z.width // 2, z.height // 2), Image.Resampling.LANCZOS).save(
    os.path.join(out_dir, "83_1_alpha_50.jpg"), "JPEG", quality=85
)

# Also check bj_01, bj_03, and Live2D preview
for sub, fn in [("bj_01", "SoulDress_Lilyiro_05_BJ_01.png"), ("bj_03", "SoulDress_Lilyiro_05_BJ_03.png")]:
    p = os.path.join(base, "submodels", sub, fn)
    im = Image.open(p).convert("RGBA")
    bg = Image.new("RGBA", im.size, (30, 30, 40, 255))
    bg.alpha_composite(im)
    bg.convert("RGB").resize((im.width // 2, im.height // 2), Image.Resampling.LANCZOS).save(
        os.path.join(out_dir, f"{sub}_50.jpg"), "JPEG", quality=80
    )

# Also check Live2D version
l2d_prev = r"E:\A灵魂潮汐\tools\_doll_audit_previews\live2d\莉莉艾洛__花与剑的交织.jpg"
if os.path.exists(l2d_prev):
    im = Image.open(l2d_prev)
    im.convert("RGB").resize((im.width // 2, im.height // 2), Image.Resampling.LANCZOS).save(
        os.path.join(out_dir, "l2d_prev_50.jpg"), "JPEG", quality=80
    )

print("Done!")
