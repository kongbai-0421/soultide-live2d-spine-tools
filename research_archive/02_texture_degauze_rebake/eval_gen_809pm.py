import os
import cv2
import numpy as np
from PIL import Image, ImageDraw

gen_path = r"E:\库\下载\Generated Image November 22, 2026 - 8_09PM.jpg"
kit_dir = r"E:\A灵魂潮汐\tools\_lilyiro05_edit_kit"
scratch_dir = r".\_scratch\lilyiro05_inspect"

im_gen = Image.open(gen_path).convert("RGB")
print("Generated image size:", im_gen.size, "mode:", im_gen.mode)

# Save 50% preview per global rule
w, h = max(1, im_gen.width // 2), max(1, im_gen.height // 2)
im_gen.resize((w, h), Image.Resampling.LANCZOS).save(os.path.join(scratch_dir, "gen_809pm_50.jpg"), "JPEG", quality=80)

# Compare against 06_chest_context_tri_cleared.png AND 07_83_1_tri_cleared_green_bg.png
ref06 = Image.open(os.path.join(kit_dir, "06_chest_context_tri_cleared.png")).convert("RGB")
ref07 = Image.open(os.path.join(kit_dir, "07_83_1_tri_cleared_green_bg.png")).convert("RGB")

g_gen = cv2.cvtColor(np.array(im_gen), cv2.COLOR_RGB2GRAY)
sift = cv2.SIFT_create(nfeatures=4000)
kp_g, des_g = sift.detectAndCompute(g_gen, None)

for name, ref in [("06_context", ref06), ("07_green", ref07)]:
    g_ref = cv2.cvtColor(np.array(ref), cv2.COLOR_RGB2GRAY)
    kp_r, des_r = sift.detectAndCompute(g_ref, None)
    bf = cv2.BFMatcher()
    matches = bf.knnMatch(des_r, des_g, k=2)
    good = [m for m, n in matches if m.distance < 0.72 * n.distance]
    print(f"vs {name} ({ref.size}): SIFT good matches={len(good)}")
    if len(good) >= 8:
        pts_r = np.float32([kp_r[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        pts_g = np.float32([kp_g[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        M, inl = cv2.estimateAffinePartial2D(pts_g, pts_r, method=cv2.RANSAC, ransacReprojThreshold=2.5)
        if M is not None and inl is not None:
            sc = np.hypot(M[0, 0], M[0, 1])
            ang = np.degrees(np.arctan2(M[1, 0], M[0, 0]))
            pred = cv2.transform(pts_g[inl.ravel() == 1], M)
            err = np.linalg.norm(pred - pts_r[inl.ravel() == 1], axis=2)
            print(f"  Partial2D: scale={sc:.5f}, ang={ang:.3f} deg, tx={M[0,2]:.2f}, ty={M[1,2]:.2f}, inliers={int(inl.sum())}/{len(good)}, err med={np.median(err):.3f}px mean={err.mean():.3f}px")

            # Also try direct resize if aspect ratio matches!
            warped = cv2.warpAffine(np.array(im_gen), M, ref.size, flags=cv2.INTER_LANCZOS4)
            diff = np.abs(warped.astype(np.float32) - np.array(ref, dtype=np.float32))
            print(f"  Warped vs {name}: overall mean_abs_diff={diff.mean():.2f}, median={np.median(diff):.2f}")

            # Save side-by-side + diff board
            rw, rh = ref.size
            board = Image.new("RGB", (rw * 3 + 40, rh + 50), (20, 20, 25))
            d = ImageDraw.Draw(board)
            board.paste(ref, (10, 35)); d.text((10, 10), f"REF ({name})", fill=(255,255,0))
            board.paste(Image.fromarray(warped), (rw + 20, 35)); d.text((rw + 20, 10), "Generated (aligned)", fill=(255,255,0))
            board.paste(Image.fromarray(np.clip(diff * 4.0, 0, 255).astype(np.uint8)), (rw * 2 + 30, 35)); d.text((rw * 2 + 30, 10), "|Gen - Ref| x4", fill=(255,255,0))
            board.resize((board.width // 2, board.height // 2), Image.Resampling.LANCZOS).save(
                os.path.join(scratch_dir, f"gen_vs_{name}_50.jpg"), "JPEG", quality=88
            )
            np.save(os.path.join(scratch_dir, f"M_gen_to_{name}.npy"), M)
