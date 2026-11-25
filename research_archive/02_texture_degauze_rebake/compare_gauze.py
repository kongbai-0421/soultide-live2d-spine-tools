import numpy as np
from PIL import Image, ImageDraw

im111 = Image.open(r"E:\库\下载\111.png").convert("RGBA")
imcur = Image.open(r".\_scratch\lilyiro05_inspect\current_main_render.png").convert("RGBA")

# Also check if 83_1 has gauze ONLY in the semi-transparent triangle, OR ALSO painted onto the opaque breast skin!
# Wait: look at 111.png chest:
# Crop 111.png chest (roughly x=950..1500, y=420..1020) and current_main_render chest (x=100..650, y=220..820)
c1 = im111.crop((950, 420, 1550, 1020))
c2 = imcur.crop((80, 200, 680, 800))

# Composite both on black
b1 = Image.new("RGBA", c1.size, (0, 0, 0, 255)); b1.alpha_composite(c1)
b2 = Image.new("RGBA", c2.size, (0, 0, 0, 255)); b2.alpha_composite(c2)

# Make a side-by-side image at 2x? No, keep 600x600 each -> 1240x660, then save 50% preview = 620x330
# Actually let's crop tighter around the upper chest + straps + breasts: 450x450 each -> 920x500 -> 50% = 460x250
# Let's check exact coordinates in both images by finding the purple flower on upper strap / neck pendant
# Even better: compute 2x2 grid: [111 chest, cur chest] and [111 contrast-boosted, cur contrast-boosted]
def boost(im):
    arr = np.array(im.convert("RGB"), dtype=np.float32)
    # Enhance local contrast / saturation to make faint white gauze pop!
    mean = arr.mean(axis=(0,1), keepdims=True)
    out = np.clip((arr - mean) * 1.8 + 128, 0, 255).astype(np.uint8)
    return Image.fromarray(out)

grid = Image.new("RGB", (1240, 1280), (20, 20, 20))
d = ImageDraw.Draw(grid)
grid.paste(b1.convert("RGB"), (10, 40))
d.text((10, 10), "111.png chest crop", fill=(255,255,0))
grid.paste(b2.convert("RGB"), (630, 40))
d.text((630, 10), "Current Spine chest crop", fill=(255,255,0))
grid.paste(boost(b1), (10, 670))
d.text((10, 645), "111.png contrast x1.8", fill=(255,255,0))
grid.paste(boost(b2), (630, 670))
d.text((630, 645), "Current Spine contrast x1.8", fill=(255,255,0))

grid.resize((grid.width // 2, grid.height // 2), Image.Resampling.LANCZOS).save(
    r".\_scratch\lilyiro05_inspect\compare_gauze_50.jpg", "JPEG", quality=88
)
print("Saved compare_gauze_50.jpg")
