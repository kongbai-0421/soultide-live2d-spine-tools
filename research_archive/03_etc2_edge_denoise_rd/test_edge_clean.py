import cv2
import numpy as np
from PIL import Image
import time

def clean_etc2_spine_pma(src_rgba: np.ndarray, uv_mask: np.ndarray = None, aggressive_rim: bool = True):
    """
    Physics-based ETC2 4x4 / DXT / ASTC edge artifact cleaner for Spine PMA atlases.
    Input/Output: uint8 (H, W, 4) Premultiplied Alpha RGBA.
    """
    t0 = time.time()
    H, W = src_rgba.shape[:2]
    r = src_rgba[..., 0].astype(np.float32)
    g = src_rgba[..., 1].astype(np.float32)
    b = src_rgba[..., 2].astype(np.float32)
    a = src_rgba[..., 3].astype(np.float32)

    # ------------------------------------------------------------------
    # Stage 1: Strict PMA cleanup + floating ETC2 micro-speckle removal
    # ------------------------------------------------------------------
    a_clean = a.copy()

    # 1a. Remove tiny isolated low-alpha blobs far from any solid content (<= 24 px, 1<=A<=18)
    solid_any = (a_clean >= 64).astype(np.uint8)
    dist_solid = cv2.distanceTransform(1 - solid_any, cv2.DIST_L2, 5)
    far_low = ((a_clean >= 1) & (a_clean <= 18) & (dist_solid > 3.0)).astype(np.uint8)
    ncc, lbl, stats, _ = cv2.connectedComponentsWithStats(far_low, connectivity=8)
    if ncc > 1:
        areas = stats[:, cv2.CC_STAT_AREA]
        kill_ids = (areas <= 24)
        kill_ids[0] = False
        kill_mask = kill_ids[lbl]
        a_clean[kill_mask] = 0.0

    # 1b. Trim EAC 4x4 alpha halo tail: very faint alpha (1..6) sitting >= 2.2px away from opaque (A>=230)
    # ONLY if there is an opaque pixel nearby (within 5px, i.e. edge halo, NOT soft blush/glow!)
    opaque_230 = (a_clean >= 230).astype(np.uint8)
    dist_op230 = cv2.distanceTransform(1 - opaque_230, cv2.DIST_L2, 5)
    halo_tail = (a_clean >= 1) & (a_clean <= 6) & (dist_op230 >= 2.2) & (dist_op230 <= 5.5)
    a_clean[halo_tail] = 0.0

    # 1c. Optional: clear pixels completely outside any Spine UV triangle (+2px safety margin)
    if uv_mask is not None:
        safe_uv = cv2.dilate(uv_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0
        a_clean[~safe_uv] = 0.0

    # Unpremultiply current pixels safely
    a_safe = np.maximum(a_clean, 1.0)
    sr = np.clip(r * 255.0 / a_safe, 0.0, 255.0)
    sg = np.clip(g * 255.0 / a_safe, 0.0, 255.0)
    sb = np.clip(b * 255.0 / a_safe, 0.0, 255.0)
    straight = np.stack([sr, sg, sb], axis=-1) # float32 0..255

    # ------------------------------------------------------------------
    # Stage 3 FIRST (before Stage 2 pulls colors from opaque rim!):
    # Clean mixed 4x4 ETC2 block chroma corruption on opaque outer rim!
    # ------------------------------------------------------------------
    # Identify 4x4 blocks that contain both high-alpha (>=200) and transparent/near-transparent (<=10)
    bh, bw = H // 4, W // 4
    a_blk = a_clean[:bh*4, :bw*4].reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(bh, bw, 16)
    mixed_blk_small = (a_blk.max(axis=2) >= 200) & (a_blk.min(axis=2) <= 10)
    mixed_blk = np.zeros((H, W), dtype=bool)
    mixed_blk[:bh*4, :bw*4] = np.repeat(np.repeat(mixed_blk_small, 4, axis=0), 4, axis=1)

    trans = (a_clean <= 10).astype(np.uint8)
    dist_trans = cv2.distanceTransform(1 - trans, cv2.DIST_L2, 5)

    # Pure interior anchor: opaque (>=245), NOT in a mixed 4x4 block, and >= 2.2px from transparent
    pure_interior = (a_clean >= 245) & (~mixed_blk) & (dist_trans >= 2.2)

    if aggressive_rim and np.any(pure_interior):
        dist_pure, lbl_pure = cv2.distanceTransformWithLabels(
            (1 - pure_interior.astype(np.uint8)), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
        )
        py, px = np.where(pure_interior)
        pure_rgb_flat = straight[py, px]
        nearest_pure_rgb = pure_rgb_flat[lbl_pure.ravel() - 1].reshape(H, W, 3)

        # Convert straight & nearest_pure to CIELAB (float32)
        lab_cur = cv2.cvtColor(straight.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        lab_pure = cv2.cvtColor(nearest_pure_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)

        # Target: opaque/high-alpha rim inside mixed 4x4 blocks (close to transparent AND close to pure interior)
        rim_cand = mixed_blk & (a_clean >= 180) & (dist_trans <= 2.8) & (dist_pure <= 4.5)

        dL = np.abs(lab_cur[..., 0] - lab_pure[..., 0])
        da = lab_cur[..., 1] - lab_pure[..., 1]
        db = lab_cur[..., 2] - lab_pure[..., 2]
        dab = np.sqrt(da * da + db * db)

        # Only correct chroma when luminance is reasonably similar (protects dark outlines on light skin!)
        # If rim is a dark outline (dL > 28), don't pull its chroma from light skin.
        # If dL <= 28 and dab > 3.0 (greenish/grayish ETC2 shift!), smoothly pull (a*, b*) to pure interior!
        # Also if it's a very slight luminance blockiness on a smooth highlight edge (dL in 3..16 & dab > 4), soften L* gently.
        sim_L = np.clip((28.0 - dL) / 14.0, 0.0, 1.0)
        chroma_w = np.clip((dab - 2.5) / 6.0, 0.0, 1.0) * sim_L
        chroma_w = np.where(rim_cand, chroma_w, 0.0)

        # Light luminance de-blocking only when chroma is clearly corrupted (indicating ETC2 block strain)
        lum_w = np.where(rim_cand & (dab > 5.0) & (dL <= 18.0), 0.55 * sim_L, 0.0)

        lab_fixed = lab_cur.copy()
        lab_fixed[..., 0] = lab_cur[..., 0] * (1.0 - lum_w) + lab_pure[..., 0] * lum_w
        lab_fixed[..., 1] = lab_cur[..., 1] * (1.0 - chroma_w) + lab_pure[..., 1] * chroma_w
        lab_fixed[..., 2] = lab_cur[..., 2] * (1.0 - chroma_w) + lab_pure[..., 2] * chroma_w

        rgb_fixed = cv2.cvtColor(np.clip(lab_fixed, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
        straight = np.where(rim_cand[..., None], rgb_fixed, straight)

    # ------------------------------------------------------------------
    # Stage 2: Semi-transparent anti-aliased edge straight-color rebuild
    # ------------------------------------------------------------------
    # Build anchor mask of reliable opaque pixels (A >= 240)
    # Note: because Stage 3 already cleaned the mixed-block opaque rim, nearest opaque pixel
    # BOTH preserves 1px dark lineart AND has clean chroma!
    anchor = (a_clean >= 240).astype(np.uint8)
    dist_anc, lbl_anc = cv2.distanceTransformWithLabels(1 - anchor, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ay, ax = np.where(anchor > 0)
    anc_rgb_flat = straight[ay, ax]
    ref_rgb = anc_rgb_flat[lbl_anc.ravel() - 1].reshape(H, W, 3)

    # Compute local 5x5 bounding box of anchor RGB to detect out-of-gamut ETC2 spikes
    # (fill non-anchor with 255 for min, 0 for max)
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    rgb_for_max = np.where(anchor[..., None] > 0, straight, 0.0)
    rgb_for_min = np.where(anchor[..., None] > 0, straight, 255.0)
    loc_max = cv2.dilate(rgb_for_max, k5)
    loc_min = cv2.erode(rgb_for_min, k5)

    # Out-of-gamut excess (how far straight color jumps outside local opaque gamut)
    oog_hi = np.maximum(0.0, straight - (loc_max + 8.0))
    oog_lo = np.maximum(0.0, (loc_min - 8.0) - straight)
    oog = np.sqrt((oog_hi**2 + oog_lo**2).sum(axis=-1))

    # Original PMA violation amount
    pma_viol = np.maximum(0.0, np.maximum(np.maximum(r, g), b) - a_clean)

    # Semi-transparent edge band near opaque parts (dist <= 3.5px)
    semi_edge = (a_clean >= 1.0) & (a_clean < 240.0) & (dist_anc <= 3.8)

    # Replacement weight:
    # 1) Low alpha (<= 60): SNR completely ruined by ETC2 -> full clean reference color
    # 2) Any PMA violation (> 1.5) -> full clean reference color
    # 3) Medium alpha (60..240): blend smoothly based on (1 - a/240) + out-of-gamut spike!
    w_low_a = np.clip((90.0 - a_clean) / 55.0, 0.0, 1.0)        # 1.0 for a<=35, ramps down to 0 at a=90
    w_viol = np.clip((pma_viol - 1.0) / 4.0, 0.0, 1.0)
    w_oog = np.clip((oog - 6.0) / 18.0, 0.0, 1.0)
    # Also gentle baseline chroma pull for a in 90..220 inside mixed 4x4 blocks
    w_base = np.where(mixed_blk, np.clip((225.0 - a_clean) / 180.0, 0.0, 0.65), 0.0)

    w_rep = np.maximum.reduce([w_low_a, w_viol, w_oog, w_base])
    w_rep = np.where(semi_edge, w_rep, 0.0)

    straight_out = straight * (1.0 - w_rep[..., None]) + ref_rgb * w_rep[..., None]

    # Also handle semi-transparent pixels FAR from opaque (like translucent veils/blush/glows)
    # ONLY clamp PMA violations (RGB > A) without touching their true colors!
    far_semi = (a_clean >= 1.0) & (a_clean < 240.0) & (dist_anc > 3.8)
    # For far_semi, straight_out is already clamped to [0, 255] via unpremul, which automatically fixes RGB > A!

    # ------------------------------------------------------------------
    # Stage 4: Strict PMA Re-encode (exact RGB <= A, A==0 -> RGBA=0)
    # ------------------------------------------------------------------
    a_u8 = np.clip(np.rint(a_clean), 0, 255).astype(np.uint8)
    af = a_u8.astype(np.float32) / 255.0
    rgb_pma = np.clip(np.rint(straight_out * af[..., None]), 0, 255).astype(np.uint8)
    # Strictly enforce RGB <= A and A==0 -> RGB=0
    rgb_pma = np.minimum(rgb_pma, a_u8[..., None])
    out = np.concatenate([rgb_pma, a_u8[..., None]], axis=-1)

    dt = time.time() - t0
    stats_out = {
        'elapsed_s': round(dt, 2),
        'orig_a0_rgb': int(np.sum((src_rgba[...,3]==0) & (src_rgba[...,:3].max(axis=2)>0))),
        'orig_rgb_gt_a': int(np.sum(src_rgba[...,:3].max(axis=2) > src_rgba[...,3])),
        'new_a0_rgb': int(np.sum((out[...,3]==0) & (out[...,:3].max(axis=2)>0))),
        'new_rgb_gt_a': int(np.sum(out[...,:3].max(axis=2) > out[...,3])),
        'semi_repaired_px': int(np.sum(w_rep > 0.05)),
        'rim_repaired_px': int(np.sum(rim_cand & (chroma_w > 0.05))) if (aggressive_rim and np.any(pure_interior)) else 0,
        'untouched_pure_interior_pct': round(100.0 * np.sum(pure_interior) / max(1, np.sum(a >= 240)), 2),
    }
    return out, stats_out

if __name__ == '__main__':
    d = r'.\_scratch\edge_noise_study'
    src = np.array(Image.open(r'E:\A灵魂潮汐\人偶spine\Texture2D\SoulDress_Lilyiro_05.png').convert('RGBA'))
    out, st = clean_etc2_spine_pma(src)
    print('Stats:', st)
    Image.fromarray(out, 'RGBA').save(d + r'\test_cleaned.png')
    print('Saved test_cleaned.png')
