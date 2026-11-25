import json
import re
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

SCRATCH = Path(r".\_scratch")
PILOT_MANIFEST = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\pilot_manifest.json")
FX_OUT_ROOT = Path(r"E:\A灵魂潮汐\tools\_batch_fx_sequences")
PILOT_LOG = SCRATCH / "unity_pilot.log"
PREVIEW_DIR = SCRATCH / "pilot_previews"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

print("=== 1. LOG SCAN ===")
log_lines = PILOT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
interesting = []
for idx, line in enumerate(log_lines, 1):
    low = line.lower()
    if any(k in low for k in ["error", "exception", "warning", "shader", "failed", "missing", "soultidebatchfxrecorder"]):
        if "shadercompiler" in low or "mipmaps" in low or "licensing" in low:
            continue
        interesting.append(f"L{idx}: {line[:220]}")
print(f"Total log lines={len(log_lines)}, interesting={len(interesting)}")
for s in interesting[:80]:
    print(" ", s)

print("\n=== 2. PILOT PIXEL & BBOX AUDIT ===")
manifest = json.loads(PILOT_MANIFEST.read_text(encoding="utf-8"))
for skin in manifest["skins"]:
    skey = skin["skin_key"]
    cw, ch = skin["canvas_w"], skin["canvas_h"]
    rw, rh = skin["render_w"], skin["render_h"]
    print(f"\n[{skey}] canvas={cw}x{ch} render={rw}x{rh} cam=({skin['cam_x']},{skin['cam_y']})")
    for clip in skin["clips"]:
        cname = clip["clip"]
        nodes = clip["nodes"]
        exp_norm = any(
            (n.get("hasMainMaterial", True) and n.get("renderMode", 0) != 5 and not n.get("isAdditive", True))
            or (n.get("trailsEnabled", False) and not n.get("trailIsAdditive", False))
            for n in nodes
        )
        exp_add = any(
            (n.get("hasMainMaterial", True) and n.get("renderMode", 0) != 5 and n.get("isAdditive", True))
            or (n.get("trailsEnabled", False) and n.get("trailIsAdditive", False))
            for n in nodes
        )
        cdir = FX_OUT_ROOT / skey / cname
        stat_str = []
        best_frame_info = {}
        for ch_name, exp in [("normal", exp_norm), ("add", exp_add)]:
            frames = sorted((cdir / ch_name).glob("frame_*.png"))
            non_empty = 0
            max_px = 0
            max_a = 0
            union_box = None
            peak_area = -1
            peak_path = None
            for fp in frames:
                arr = np.asarray(Image.open(fp).convert("RGBA"))
                if ch_name == "add":
                    mask = (arr[:, :, 0] > 2) | (arr[:, :, 1] > 2) | (arr[:, :, 2] > 2)
                    val_max = int(arr[:, :, :3].max())
                else:
                    mask = arr[:, :, 3] > 2
                    val_max = int(arr[:, :, 3].max())
                if mask.any():
                    non_empty += 1
                    ys, xs = np.where(mask)
                    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
                    if union_box is None:
                        union_box = [x0, y0, x1, y1]
                    else:
                        union_box = [min(union_box[0], x0), min(union_box[1], y0), max(union_box[2], x1), max(union_box[3], y1)]
                    area = int(mask.sum())
                    if area > peak_area:
                        peak_area = area
                        peak_path = fp
                max_px = max(max_px, int(arr[:, :, :3].max()))
                max_a = max(max_a, int(arr[:, :, 3].max()))
            bw = (union_box[2] - union_box[0] + 1) if union_box else 0
            bh = (union_box[3] - union_box[1] + 1) if union_box else 0
            flag = ""
            if exp and non_empty == 0:
                flag = " [EXPECTED_NONEMPTY_BUT_EMPTY!]"
            elif (not exp) and non_empty > 0:
                flag = " [UNEXPECTED_NONEMPTY!]"
            stat_str.append(
                f"{ch_name}(exp={int(exp)}): {non_empty}/{len(frames)} nonEmpty maxRGB={max_px} maxA={max_a} bbox={union_box}({bw}x{bh}){flag}"
            )
            best_frame_info[ch_name] = peak_path
        print(f"  {cname}: " + " | ".join(stat_str))

        # Generate a single 50% JPG composite preview at peak frames (norm + add over dark bg)
        norm_p = best_frame_info.get("normal")
        add_p = best_frame_info.get("add")
        if norm_p or add_p:
            mid_p = None
            sample_frames = sorted((cdir / ("normal" if norm_p else "add")).glob("frame_*.png"))
            if sample_frames:
                mid_idx = len(sample_frames) // 2
                n_mid = cdir / "normal" / sample_frames[mid_idx].name
                a_mid = cdir / "add" / sample_frames[mid_idx].name
            else:
                n_mid, a_mid = norm_p, add_p

            def render_comp(np_path, ap_path, label):
                canvas = np.full((rh, rw, 3), 24.0, dtype=np.float32)
                # checkerboard subtle grid
                yy, xx = np.mgrid[0:rh, 0:rw]
                chk = (((xx // 32) + (yy // 32)) % 2) == 0
                canvas[chk] = 34.0
                if np_path and np_path.is_file():
                    na = np.asarray(Image.open(np_path).convert("RGBA"), dtype=np.float32) / 255.0
                    a = na[:, :, 3:4]
                    canvas = canvas * (1.0 - a) + (na[:, :, :3] * 255.0) * a
                if ap_path and ap_path.is_file():
                    aa = np.asarray(Image.open(ap_path).convert("RGBA"), dtype=np.float32) / 255.0
                    canvas = np.clip(canvas + aa[:, :, :3] * 255.0, 0, 255)
                im = Image.fromarray(canvas.astype(np.uint8), "RGB")
                dr = ImageDraw.Draw(im)
                dr.rectangle([0, 0, rw, 22], fill=(0, 0, 0))
                dr.text((6, 4), f"{skey} / {cname} ({label})", fill=(255, 240, 140))
                return im

            p1 = render_comp(norm_p, add_p, "peak")
            # Save at 50% JPG quality=80
            pw, ph = max(1, p1.width // 2), max(1, p1.height // 2)
            out_jpg = PREVIEW_DIR / f"{skey}__{cname}_50pct.jpg"
            p1.resize((pw, ph), Image.Resampling.LANCZOS).save(out_jpg, "JPEG", quality=80)

# Build 2 montage sheets (3x6 tiles scaled down at 50% JPG q80) for easy visual overview
jpgs = sorted(PREVIEW_DIR.glob("*__*_50pct.jpg"))
print(f"\nGenerated {len(jpgs)} 50% JPG previews in {PREVIEW_DIR}")
tile_w, tile_h = 400, 260
cols = 3
for sheet_idx in range(0, len(jpgs), 15):
    batch = jpgs[sheet_idx : sheet_idx + 15]
    rows = (len(batch) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), (16, 16, 16))
    for i, jp in enumerate(batch):
        im = Image.open(jp)
        im.thumbnail((tile_w - 4, tile_h - 4), Image.Resampling.LANCZOS)
        r, c = divmod(i, cols)
        sheet.paste(im, (c * tile_w + 2, r * tile_h + 2))
    # Save directly as pre-compressed montage (<1200x1300) AND also keep individual 50pct jpgs
    out_sheet = SCRATCH / f"pilot_sheet_{sheet_idx // 15}_50pct.jpg"
    sw, sh = max(1, sheet.width), max(1, sheet.height)
    sheet.save(out_sheet, "JPEG", quality=80)
    print(f"Sheet saved: {out_sheet} ({sw}x{sh})")
