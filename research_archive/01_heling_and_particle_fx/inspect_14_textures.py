from pathlib import Path
from PIL import Image, ImageDraw

tex_dir = Path(r".\_scratch\unity_fx_proj\Assets\Textures")
files = sorted(tex_dir.glob("*.png"))
cols = 4
cw, ch = 220, 220
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cw, rows * ch), (28, 30, 38))
dr = ImageDraw.Draw(sheet)
for idx, fp in enumerate(files):
    r, c = divmod(idx, cols)
    im = Image.open(fp).convert("RGBA")
    bg = Image.new("RGBA", im.size, (18, 22, 30, 255))
    bg.alpha_composite(im)
    th = bg.convert("RGB")
    th.thumbnail((cw - 16, ch - 36), Image.Resampling.LANCZOS)
    sheet.paste(th, (c * cw + 8, r * ch + 28))
    dr.text((c * cw + 6, r * ch + 4), fp.stem[:24], fill=(255, 240, 120))

out = Path(r".\_scratch\fx_debug\all_14_fx_textures_50pct.jpg")
out.parent.mkdir(parents=True, exist_ok=True)
sheet.resize((sheet.width // 2, sheet.height // 2)).save(out, "JPEG", quality=50)
print("Saved:", out)
