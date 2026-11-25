import os
from PIL import Image, ImageDraw

atlas_path = r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.atlas.txt"
png_path = r"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织\SoulDress_Lilyiro_05.png"
out_dir = r".\_scratch\lilyiro05_inspect"
os.makedirs(out_dir, exist_ok=True)

# Parse atlas
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

target_names = ["96", "83", "83_1", "89", "84", "91", "86", "85", "79", "78", "77", "99", "97", "23", "58"]

# Create contact sheet
cell = 360
cols = 5
rows = (len(target_names) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cell, rows * cell), (35, 35, 45))
draw = ImageDraw.Draw(sheet)

for idx, name in enumerate(target_names):
    r = regions.get(name)
    if not r:
        continue
    x, y = [int(v) for v in r["xy"].split(",")]
    w, h = [int(v) for v in r["size"].split(",")]
    rot = r.get("rotate", "false")
    if rot in ("true", "90", "270"):
        bw, bh = h, w
    else:
        bw, bh = w, h
    crop = atlas_img.crop((x, y, x + bw, y + bh))
    if rot in ("true", "90"):
        crop = crop.rotate(-90, expand=True)
    elif rot == "270":
        crop = crop.rotate(90, expand=True)
    elif rot == "180":
        crop = crop.rotate(180, expand=True)

    # Fit inside cell - 30
    scale = min((cell - 20) / max(1, crop.width), (cell - 40) / max(1, crop.height))
    nw, nh = max(1, int(crop.width * scale)), max(1, int(crop.height * scale))
    thumb = crop.resize((nw, nh), Image.Resampling.LANCZOS)

    cx = (idx % cols) * cell
    cy = (idx // cols) * cell
    # checkerboard bg
    bg = Image.new("RGBA", (nw, nh), (55, 55, 70, 255))
    bg.alpha_composite(thumb)
    sheet.paste(bg.convert("RGB"), (cx + (cell - nw) // 2, cy + 30 + (cell - 40 - nh) // 2))
    draw.rectangle([cx, cy, cx + cell - 1, cy + cell - 1], outline=(100, 100, 120))
    draw.text((cx + 8, cy + 6), f"{name} ({w}x{h} rot={rot})", fill=(255, 240, 120))

# Save 50% preview for reading per global rule
sheet_small = sheet.resize((sheet.width // 2, sheet.height // 2), Image.Resampling.LANCZOS)
sheet_small.save(os.path.join(out_dir, "chest_regions_sheet_50.jpg"), "JPEG", quality=85)

# Also crop 83_1 at 1:1 next to 111.png chest crop, then save 50% preview
r83_1 = regions["83_1"]
x, y = [int(v) for v in r83_1["xy"].split(",")]
w, h = [int(v) for v in r83_1["size"].split(",")]
c83_1 = atlas_img.crop((x, y, x + w, y + h))
# Composite on black
bg83 = Image.new("RGBA", (w, h), (0, 0, 0, 255))
bg83.alpha_composite(c83_1)

img111 = Image.open(r"E:\库\下载\111.png").convert("RGBA")
# Chest in 111.png (1965x1618) is roughly x in [850, 1500], y in [400, 1050]
c111 = img111.crop((850, 400, 1550, 1050))
bg111 = Image.new("RGBA", c111.size, (0, 0, 0, 255))
bg111.alpha_composite(c111)

# Also check current 83 (dress)
r83 = regions["83"]
x2, y2 = [int(v) for v in r83["xy"].split(",")]
w2, h2 = [int(v) for v in r83["size"].split(",")]
c83 = atlas_img.crop((x2, y2, x2 + w2, y2 + h2))
bg83m = Image.new("RGBA", (w2, h2), (0, 0, 0, 255))
bg83m.alpha_composite(c83)

# Side by side comparison canvas
comp = Image.new("RGB", (1800, 800), (20, 20, 25))
d2 = ImageDraw.Draw(comp)
comp.paste(bg111.convert("RGB").resize((700, 650), Image.Resampling.LANCZOS), (20, 60))
d2.text((20, 20), "111.png (User Ref)", fill=(255, 255, 100))
comp.paste(bg83.convert("RGB").resize((520, int(520 * h / w)), Image.Resampling.LANCZOS), (740, 60))
d2.text((740, 20), f"Atlas 83_1 ({w}x{h})", fill=(255, 255, 100))
comp.paste(bg83m.convert("RGB").resize((480, int(480 * h2 / w2)), Image.Resampling.LANCZOS), (1290, 60))
d2.text((1290, 20), f"Atlas 83 ({w2}x{h2})", fill=(255, 255, 100))

comp_small = comp.resize((comp.width // 2, comp.height // 2), Image.Resampling.LANCZOS)
comp_small.save(os.path.join(out_dir, "chest_compare_50.jpg"), "JPEG", quality=85)
print("Saved inspection sheets!")
