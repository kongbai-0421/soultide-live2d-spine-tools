import json, sys
from pathlib import Path
from PIL import Image, ImageOps
import numpy as np

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

manifest = json.loads(Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json").read_text(encoding="utf-8"))
by_sk = {s["skin_key"]: s for s in manifest["skins"]}

# Check detailed manifest nodes for key suspects
targets = [
    ("402_Freesia_S5", "fx_9008161", None),
    ("4501_RubyRose_S2", "fx_9008180", None),
    ("503_Benten_S4", "idle", "cahihonghuan"),
    ("1101_NicoletteLamel_S2", "idle", "glow2"),
    ("2001_Ennis_S2", "idle", "water"),
    ("2002_Ennis_S3", "fx_9008124", "an"),
    ("2301_QuLing_S2", "idle", "water"),
    ("601_Asuna_S6", "idle", "particle2"),
    ("4301_HeLing_S2", "idle", "yun"),
]
for sk, cln, nn in targets:
    s = by_sk[sk]
    print(f"=== {sk} cam=({s['cam_x']},{s['cam_y']}) canvas=({s['canvas_w']}x{s['canvas_h']}) render=({s['render_w']}x{s['render_h']}) ===")
    for cl in s["clips"]:
        if cl["clip"] != cln: continue
        for n in cl["nodes"]:
            if nn and n["name"] != nn: continue
            sz = (n["sizeX"]["scalar"], n["sizeY"]["scalar"], n["sizeZ"]["scalar"]) if n["size3D"] else n["size"]["scalar"]
            print(f"  node={n['name']:15s} sm={n['scalingMode']} rm={n['renderMode']} sz3d={n['size3D']} sz={sz} wpos={[round(x,1) for x in n['world_pos']]} wsc={[round(x,3) for x in n['world_scale']]} vel=({n['velX']:.1f},{n['velY']:.1f}) spd={n['speed'].get('scalar')} col={n['startColor']} colOL={len((n['colOverLife'] or {}).get('akeys',[]))} ak={(n['colOverLife'] or {}).get('akeys')} szOL={n['sizeOverLife']} mul={n['tintMultiplier']} tex={n['texName']} mask={n['maskTexName']}")

# Check FX_UI_liehen01.png appearance (RGBA + RGB channels) -> save 50% JPG preview
tex_dir = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures")
out_prev = Path(r".\_scratch\audit_previews")
for tn in ("FX_UI_liehen01.png", "Fx_cfl_caihongguang_02.png", "FX_by_trail01.png", "FX_cf_bjxuehua_b.png", "FX_gra_WL_142.png"):
    tp = tex_dir / tn
    if tp.exists():
        im = Image.open(tp).convert("RGBA")
        # Composite on dark bg and double size if < 256 before 50% rule? No, follow 50% WxH JPG q=80 of original image on dark bg!
        bg = Image.new("RGBA", im.size, (20, 24, 34, 255))
        comp = Image.alpha_composite(bg, im).convert("RGB")
        w, h = max(1, comp.width // 2), max(1, comp.height // 2)
        comp.resize((w, h), Image.Resampling.LANCZOS).save(out_prev / f"tex_{Path(tn).stem}_50pct.jpg", "JPEG", quality=80)
        # For FX_UI_liehen01, also check its RGB and Alpha separately
        if tn == "FX_UI_liehen01.png":
            a_vis = im.split()[3].point(lambda p: min(255, p * 4)).convert("RGB")
            a_vis.resize((w, h), Image.Resampling.LANCZOS).save(out_prev / "tex_FX_UI_liehen01_alpha4x_50pct.jpg", "JPEG", quality=80)
            # Notice UV distribution of alpha>10 pixels!
            arr = np.array(im)
            nz = np.argwhere(arr[:,:,3] > 5)
            print(f"FX_UI_liehen01 alpha>5 bbox: x=({nz[:,1].min()}..{nz[:,1].max()}) y=({nz[:,0].min()}..{nz[:,0].max()}) count={len(nz)}")
    else:
        print(f"MISSING tex: {tn}")
