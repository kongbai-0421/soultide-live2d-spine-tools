"""Compare exact Unity Layer_02 order (bj_01 behind vs in front of Background_01) and inspect."""
import json, subprocess
from pathlib import Path
from PIL import Image

# Use existing render of bg_static+bj_01 vs render ONLY bj_01!
# Better: let's inspect bj_01's exact pixel overlay on top of HeLing_S2_Background_01!
# Wait: we can just composite our rendered heling_scheme1_t0 with HeLing_S2_Background_01 on top vs below!
# Even cleaner: run a 1-second test using _spine38_composite_renderer.exe on bj_01 alone? No, just compute from bg_4301!
# Actually, let's check what happens if we build bg_sky+yun+scr as order -3, bj_01 as -2, bg_buildings+lizi as -1 (EXACT UNITY ORDER)!
# Let's check exact world coords of all 3 images in Unity (1.5x canvas=2550x1700 vs 1700x1131):
# Wait: in Unity HeLing_S2_Background:
#   Layer_01/Image_02: world=(3.0, -50.0), size=(1700, 1131)
#   Layer_01/Image:    world=(-285.0, 160.0), size=(778, 470)
#   Layer_02/Image:    world=(4.0, -52.0), size=(1700, 1131)
# Look at cam=(4.5, -76.5) and canvas=(2550, 1700):
#   4.5 / 1.5 = 3.0 !!  -76.5 / 1.5 = -51.0 !!  2550 / 1.5 = 1700 !!  1700 / 1.5 = 1133.33 !!
# THAT'S WHY! batch_fx_exporter multiplied Unity UI coords by 1.5!
# So in Centered Spine coords (where bg_static is 4250 x 2833.3333 centered at (0,0), corresponding to Unity 1700 x 1133.3333 centered at (3.0, -51.0)):
#   SCALE_UI_TO_SPINE = 4250.0 / 1700.0 = 2.5 EXACT!!
# Let's verify against bg_4301_heling_s2.png (2550x1700)!
d = Path(r".\_scratch\heling_orig_layers")
orig_bg = Image.open(r".\_scratch\heling_s2_backup_pngs\bg_static__bg_4301_heling_s2.png").convert("RGBA")
l1_sky = Image.open(d / "L1_Image_02__HeLing_S2_Background_04.png").convert("RGBA")
l1_scr = Image.open(d / "L1_Image__HeLing_S2_Background_03.png").convert("RGBA")
l2_bld = Image.open(d / "L2_Image__HeLing_S2_Background_01.png").convert("RGBA")

# Compose l1_sky + l1_scr + l2_bld at 1.5x onto 2550x1700 centered at (4.5, -76.5) and compare to orig_bg!
import numpy as np
canvas = Image.new("RGBA", (2550, 1700), (0, 0, 0, 0))
def paste_ui(dst, im, wx_ui, wy_ui):
    w = int(round(im.width * 1.5))
    h = int(round(im.height * 1.5))
    r = im.resize((w, h), Image.Resampling.LANCZOS)
    cx = (wx_ui * 1.5 - 4.5) + 2550 / 2.0
    cy = 1700 / 2.0 - (wy_ui * 1.5 - (-76.5))
    x0 = int(round(cx - w / 2.0))
    y0 = int(round(cy - h / 2.0))
    print(f"  paste {im.size} -> ({w}x{h}) at ({x0}, {y0})")
    # safe crop/paste
    tmp = Image.new("RGBA", dst.size, (0, 0, 0, 0))
    tmp.paste(r, (x0, y0))
    return Image.alpha_composite(dst, tmp)

canvas = paste_ui(canvas, l1_sky, 3.0, -50.0)
canvas = paste_ui(canvas, l1_scr, -285.0, 160.0)
canvas = paste_ui(canvas, l2_bld, 4.0, -52.0)
diff = np.abs(np.array(canvas, dtype=int) - np.array(orig_bg, dtype=int)).mean()
print("Mean pixel diff vs orig_bg:", diff)
