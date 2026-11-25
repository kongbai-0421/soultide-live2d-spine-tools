from pathlib import Path
from PIL import Image, ImageDraw

seq_root = Path(r"E:\A灵魂潮汐\tools\_aurora_fx_sequences")
out_dir = Path(r".\_scratch\fx_debug")
out_dir.mkdir(parents=True, exist_ok=True)

# 1. Inspect raw normal & add channels separately (on checkerboard/dark bg) so we see what is actually inside each frame!
tiles = []
for clip, f in [("idle", 0), ("idle", 15), ("fx_9008135", 10), ("fx_9008136", 5), ("fx_9008136", 12), ("fx_9008136", 20)]:
    for ch in ("normal", "add"):
        p = seq_root / clip / ch / f"frame_{f:04d}.png"
        if not p.exists(): continue
        im = Image.open(p).convert("RGBA")
        # Composite onto dark grey (30,35,45) using straight alpha to inspect both alpha silhouette and RGB
        bg = Image.new("RGBA", im.size, (30, 35, 45, 255))
        bg.alpha_composite(im)
        # Also create alpha-only grayscale preview
        a = im.split()[3]
        print(f"{clip}/{ch} f{f:02d}: size={im.size} alpha_ext={a.getextrema()} nonzero_px={sum(1 for v in a.getdata() if v>0)}")
        tiles.append((f"{clip}/{ch} f{f}", bg.convert("RGB")))

cols = 2
cw, ch_h = 884, 588
rows = (len(tiles) + 1) // 2
sheet = Image.new("RGB", (cw * cols, ch_h * rows), (15, 15, 20))
dr = ImageDraw.Draw(sheet)
for i, (lbl, im) in enumerate(tiles):
    r, c = divmod(i, cols)
    sheet.paste(im, (c * cw, r * ch_h))
    dr.text((c * cw + 12, r * ch_h + 12), lbl, fill=(255, 255, 0))
out_p = out_dir / "raw_channels_50pct.jpg"
sheet.resize((sheet.width // 2, sheet.height // 2)).save(out_p, "JPEG", quality=80)
print("Saved:", out_p)

# 2. Check fx_aurora_s4 atlas pages & sizes!
fx_dir = Path(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\submodels\fx_aurora_s4")
for png in sorted(fx_dir.glob("*.png")):
    im = Image.open(png)
    print("FX atlas PNG:", png.name, im.size, png.stat().st_size)
