from pathlib import Path
from PIL import Image, ImageChops, ImageDraw

seq_root = Path(r"E:\A灵魂潮汐\tools\_aurora_fx_sequences")
bg = Image.open(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\submodels\bg_static\bg_aurora_s4.png").resize((884, 588)).convert("RGBA")

def pma_normal_over(dst: Image.Image, pma_src: Image.Image) -> Image.Image:
    # Spine DefaultPMAShader Blend One OneMinusSrcAlpha: dst * (1 - src.a) + src.rgb
    sr, sg, sb, sa = pma_src.split()
    inv_a = sa.point(lambda v: 255 - v)
    dr, dg, db, da = dst.split()
    out_r = ImageChops.add(ImageChops.multiply(dr, inv_a), sr)
    out_g = ImageChops.add(ImageChops.multiply(dg, inv_a), sg)
    out_b = ImageChops.add(ImageChops.multiply(db, inv_a), sb)
    return Image.merge("RGBA", (out_r, out_g, out_b, da))

def pma_add_over(dst: Image.Image, add_src: Image.Image) -> Image.Image:
    # Spine DefaultPMAShader Blend One One: dst.rgb + src.rgb (does NOT multiply by src.a!)
    sr, sg, sb, _ = add_src.split()
    dr, dg, db, da = dst.split()
    return Image.merge("RGBA", (ImageChops.add(dr, sr), ImageChops.add(dg, sg), ImageChops.add(db, sb), da))

def composite_ex_exact(clip_name: str, frame_idx: int) -> Image.Image:
    canvas = bg.copy()
    norm_p = seq_root / clip_name / "normal" / f"frame_{frame_idx:04d}.png"
    add_p = seq_root / clip_name / "add" / f"frame_{frame_idx:04d}.png"
    if norm_p.exists():
        canvas = pma_normal_over(canvas, Image.open(norm_p).convert("RGBA"))
    if add_p.exists():
        canvas = pma_add_over(canvas, Image.open(add_p).convert("RGBA"))
    return canvas

tiles = [
    ("idle f0", composite_ex_exact("idle", 0)),
    ("idle f15", composite_ex_exact("idle", 15)),
    ("fx_9008135 f8", composite_ex_exact("fx_9008135", 8)),
    ("fx_9008135 f18", composite_ex_exact("fx_9008135", 18)),
    ("fx_9008136 f8", composite_ex_exact("fx_9008136", 8)),
    ("fx_9008136 f18", composite_ex_exact("fx_9008136", 18)),
]
sheet = Image.new("RGB", (884 * 2, 588 * 3), (20, 20, 28))
dr = ImageDraw.Draw(sheet)
for idx, (lbl, im) in enumerate(tiles):
    r, c = divmod(idx, 2)
    sheet.paste(im.convert("RGB"), (c * 884, r * 588))
    dr.text((c * 884 + 12, r * 588 + 12), lbl, fill=(255, 255, 100))

out = Path(r".\_scratch\unity_fx_proj\fx_unity_pma_preview_50pct.jpg")
sheet.resize((sheet.width // 2, sheet.height // 2), Image.Resampling.LANCZOS).save(out, "JPEG", quality=80)
print("Saved EX-faithful PMA preview:", out)
