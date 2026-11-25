import json, sys
from pathlib import Path
from PIL import Image
import numpy as np
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

idx = bfe.AssetIndexer()

# 1. Check Freesia_S5_Background sprites
for pid_key, pid in idx.art_container.items():
    if "freesia_s5_background" in pid_key.lower() and "prefab" in pid_key.lower():
        co = idx.art_objs[pid].read_typetree()
        gpid = co["m_GameObject"]["m_PathID"] if "m_GameObject" in co else pid
        print("=== Freesia_S5_Background RectTransforms & Sprite names ===", pid_key)
        def walk_img(gp, wx=0.0, wy=0.0, wsx=1.0, wsy=1.0, depth=0):
            go = idx.art_objs[gp].read_typetree()
            tf = None
            sp_name = ""
            for c in go.get("m_Component", []):
                o = idx.art_objs.get(c["component"]["m_PathID"])
                if not o: continue
                t = o.read_typetree()
                if "m_Father" in t and ("m_LocalPosition" in t or "m_AnchoredPosition" in t):
                    tf = t
                elif "m_Sprite" in t:
                    sref = t["m_Sprite"]
                    so = idx.resolve_ext(o.assets_file, sref.get("m_FileID", 0), sref.get("m_PathID", 0))
                    if so:
                        sp_name = so.read_typetree().get("m_Name", "?")
            lp = tf.get("m_LocalPosition", {"x":0,"y":0}) if tf else {"x":0,"y":0}
            ap = tf.get("m_AnchoredPosition") if tf else None
            ls = tf.get("m_LocalScale", {"x":1,"y":1}) if tf else {"x":1,"y":1}
            sd = tf.get("m_SizeDelta", {"x":0,"y":0}) if tf else {"x":0,"y":0}
            lx = ap["x"] if ap is not None else lp["x"]
            ly = ap["y"] if ap is not None else lp["y"]
            if depth == 0: lx, ly = 0.0, 0.0
            nx, ny = wx + lx * wsx, wy + ly * wsy
            nsx, nsy = wsx * ls["x"], wsy * ls["y"]
            if sp_name:
                print(f"  img={go.get('m_Name'):15s} sp={sp_name:28s} pos=({nx:.1f},{ny:.1f}) size=({sd['x']*nsx:.1f}x{sd['y']*nsy:.1f})")
            if tf:
                for ch in tf.get("m_Children", []):
                    ct = idx.art_objs.get(ch["m_PathID"])
                    if ct:
                        walk_img(ct.read_typetree()["m_GameObject"]["m_PathID"], nx, ny, nsx, nsy, depth+1)
        walk_img(gpid)

# 2. Check ALL bg_static PNGs for empty/transparent margins (indicates wrong cam_x / cam_y!)
print("\n=== SCANNING ALL bg_static PNGs FOR EMPTY MARGINS (>20px) ===")
for bgp in sorted(Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine").glob("*/*/submodels/bg_static/bg_*.png")):
    with Image.open(bgp) as im:
        arr = np.array(im.convert("RGBA"))
    a = arr[:, :, 3]
    ys, xs = np.where(a > 5)
    if len(xs) == 0:
        print(f"  EMPTY BG: {bgp}")
        continue
    h, w = a.shape
    ml, mr, mt, mb = int(xs.min()), int(w - 1 - xs.max()), int(ys.min()), int(h - 1 - ys.max())
    if max(ml, mr, mt, mb) > 20:
        print(f"  MARGIN: {bgp.name:30s} size=({w}x{h}) margins L={ml} R={mr} T={mt} B={mb}")

# 3. Save 50% JPG previews of RubyRose_S2 bg & FX_cf_xuehua03 / FX_ZC_Mask137
out_prev = Path(r".\_scratch\audit_previews")
for label, pat in [
    ("bg_4501_rubyrose_s2", r"bg_4501_*.png"),
    ("tex_FX_cf_xuehua03", None),
    ("tex_FX_ZC_Mask137", None),
]:
    if pat:
        hits = list(Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine").glob(f"*/*/submodels/bg_static/{pat}"))
        pp = hits[0] if hits else None
    else:
        pp = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures") / (label.replace("tex_", "") + ".png")
    if pp and pp.exists():
        im = Image.open(pp).convert("RGBA")
        bg = Image.new("RGBA", im.size, (20, 24, 34, 255))
        comp = Image.alpha_composite(bg, im).convert("RGB")
        comp.resize((max(1, comp.width // 2), max(1, comp.height // 2)), Image.Resampling.LANCZOS).save(out_prev / f"{label}_50pct.jpg", "JPEG", quality=80)
        print("Saved:", label, pp.name, im.size)
