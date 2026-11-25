import numpy as np
from PIL import Image, ImageDraw

out_dir = r".\_scratch\lilyiro05_inspect"
im111 = Image.open(r"E:\库\下载\111.png").convert("RGBA")
imsetup = Image.open(out_dir + r"\setup_pose_full.png").convert("RGBA")
im96 = Image.open(out_dir + r"\setup_pose_96.png").convert("RGBA")

a111 = np.array(im111, dtype=np.float32)
asetup = np.array(imsetup, dtype=np.float32)

# Find exact affine/scale+translate alignment using normalized cross correlation on a distinctive feature:
# The purple flower + lace cup + collar in chest area!
# In setup_pose_full (minX=-1150, maxY=1180):
# slot 83_1 world bounds: x=[-160, 443], y=[146, 674]
# -> image coords: px = x - (-1150) = x + 1150 -> [990, 1593]
# -> py = 1180 - y -> [506, 1034]
# Let's check non-zero bbox of 111.png vs setup_pose_full
ys1, xs1 = np.where(a111[:, :, 3] > 20)
print(f"111.png non-empty bbox: x=[{xs1.min()},{xs1.max()}] w={xs1.max()-xs1.min()}, y=[{ys1.min()},{ys1.max()}] h={ys1.max()-ys1.min()}")

# Template: crop around the collar + lower cup + shoulder strap in setup_pose_full (x=1050..1550, y=520..980)
# Wait: let's match at multiple scales around 1.0 using coarse-to-fine grid search on grayscale!
def to_gray(arr):
    return 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]

g_setup = to_gray(asetup)
g_111 = to_gray(a111)

# Let's use the lace + collar + head/eye region for robust matching!
# In setup: x=1000..1750, y=250..1000 -> size 750x750
# Check if cv2 is installed
try:
    import cv2
    has_cv2 = True
except ImportError:
    has_cv2 = False
print("has_cv2:", has_cv2)

if has_cv2:
    # Use AKAZE or SIFT feature matching on chest+head+dress to find exact similarity/affine transform!
    sift = cv2.SIFT_create(nfeatures=4000)
    # Mask setup to body region (exclude long hair bottom-right / flower in hand if absent in 111)
    u_setup = g_setup.astype(np.uint8)
    u_111 = g_111.astype(np.uint8)
    # Focus on chest+collar+dress+legs (x=400..1700, y=150..1150 in setup)
    mask_s = np.zeros_like(u_setup)
    mask_s[150:1150, 400:1700] = 255
    kp1, des1 = sift.detectAndCompute(u_setup, mask_s)
    kp2, des2 = sift.detectAndCompute(u_111, None)
    bf = cv2.BFMatcher()
    matches = bf.knnMatch(des1, des2, k=2)
    good = [m for m, n in matches if m.distance < 0.72 * n.distance]
    print(f"SIFT good matches: {len(good)}")
    pts1 = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    M, inliers = cv2.estimateAffinePartial2D(pts2, pts1, method=cv2.RANSAC, ransacReprojThreshold=2.5)
    print("AffinePartial2D (111 -> setup):\n", M)
    print("Inliers:", int(inliers.sum()), "/", len(good))
    scale = np.hypot(M[0, 0], M[0, 1])
    angle = np.degrees(np.arctan2(M[1, 0], M[0, 0]))
    print(f"Scale={scale:.6f}, Angle={angle:.4f} deg, Tx={M[0,2]:.3f}, Ty={M[1,2]:.3f}")

    # Also compute chest-only local affine (pts inside chest x=950..1620, y=450..1050)
    chest_good = [m for m in good if 950 <= kp1[m.queryIdx].pt[0] <= 1620 and 450 <= kp1[m.queryIdx].pt[1] <= 1050]
    print(f"Chest-only SIFT matches: {len(chest_good)}")
    if len(chest_good) >= 6:
        cp1 = np.float32([kp1[m.queryIdx].pt for m in chest_good]).reshape(-1, 1, 2)
        cp2 = np.float32([kp2[m.trainIdx].pt for m in chest_good]).reshape(-1, 1, 2)
        Mc, cinl = cv2.estimateAffinePartial2D(cp2, cp1, method=cv2.RANSAC, ransacReprojThreshold=1.5)
        sc_c = np.hypot(Mc[0, 0], Mc[0, 1])
        ang_c = np.degrees(np.arctan2(Mc[1, 0], Mc[0, 0]))
        print(f"Chest-only Partial2D: Scale={sc_c:.6f}, Angle={ang_c:.4f} deg, Tx={Mc[0,2]:.3f}, Ty={Mc[1,2]:.3f}, inliers={int(cinl.sum())}/{len(chest_good)}")
        # Check residual error on inliers
        pred = cv2.transform(cp2[cinl.ravel() == 1], Mc)
        err = np.linalg.norm(pred - cp1[cinl.ravel() == 1], axis=2)
        print(f"Chest inlier reproj err: mean={err.mean():.3f}px, median={np.median(err):.3f}px, max={err.max():.3f}px")

        # Warp 111.png onto setup_pose canvas using Mc
        warped = cv2.warpAffine(np.array(im111), Mc, (imsetup.width, imsetup.height), flags=cv2.INTER_LANCZOS4)
        Image.fromarray(warped).save(out_dir + r"\111_warped_to_setup.png")

        # Compute chest crop diff (x=960..1620, y=470..1060)
        x0, y0, x1, y1 = 960, 470, 1620, 1060
        w_crop = warped[y0:y1, x0:x1]
        s_crop = np.array(imsetup)[y0:y1, x0:x1]
        n96_crop = np.array(im96)[y0:y1, x0:x1]

        # Composite on black
        def over_black(rgba):
            a = rgba[:, :, 3:4].astype(np.float32) / 255.0
            # Note: setup_pose_full is already premul in SaveFb? Let's check: SaveFb wrote r*255 where fb was premul!
            return rgba[:, :, :3].astype(np.float32)

        # For warped 111 (straight alpha):
        w_rgb = w_crop[:, :, :3].astype(np.float32) * (w_crop[:, :, 3:4].astype(np.float32) / 255.0)
        s_rgb = s_crop[:, :, :3].astype(np.float32)
        diff = np.abs(w_rgb - s_rgb)
        diff_amp = np.clip(diff * 4.0, 0, 255).astype(np.uint8)
        # Signed diff (setup - 111): positive = white gauze added on setup!
        signed = s_rgb - w_rgb
        pos_vis = np.clip(signed * 5.0, 0, 255).astype(np.uint8)
        neg_vis = np.clip(-signed * 5.0, 0, 255).astype(np.uint8)

        # Build 2x3 diagnostic board
        cw, ch = x1 - x0, y1 - y0
        board = Image.new("RGB", (cw * 3 + 40, ch * 2 + 80), (15, 15, 20))
        d = ImageDraw.Draw(board)
        board.paste(Image.fromarray(w_rgb.astype(np.uint8)), (10, 35))
        d.text((10, 10), "111.png warped to SetupPose", fill=(255,255,0))
        board.paste(Image.fromarray(s_rgb.astype(np.uint8)), (cw + 20, 35))
        d.text((cw + 20, 10), "Current Spine SetupPose", fill=(255,255,0))
        board.paste(Image.fromarray(n96_crop[:, :, :3]), (cw * 2 + 30, 35))
        d.text((cw * 2 + 30, 10), "Underlying slot 96 (bare torso)", fill=(255,255,0))

        board.paste(Image.fromarray(diff_amp), (10, ch + 65))
        d.text((10, ch + 42), "|Setup - 111| x4", fill=(255,255,0))
        board.paste(Image.fromarray(pos_vis), (cw + 20, ch + 65))
        d.text((cw + 20, ch + 42), "max(0, Setup - 111) x5 (ADDED WHITE GAUZE!)", fill=(255,255,0))
        board.paste(Image.fromarray(neg_vis), (cw * 2 + 30, ch + 65))
        d.text((cw * 2 + 30, ch + 42), "max(0, 111 - Setup) x5", fill=(255,255,0))

        board.resize((board.width // 2, board.height // 2), Image.Resampling.LANCZOS).save(
            out_dir + r"\align_diff_board_50.jpg", "JPEG", quality=88
        )
        print("Saved align_diff_board_50.jpg")
