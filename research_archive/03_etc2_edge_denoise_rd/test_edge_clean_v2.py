import cv2
import numpy as np
from PIL import Image
import time

def clean_etc2_spine_pma_v2(src_rgba: np.ndarray, uv_mask: np.ndarray = None):
    """
    V2 Physics-based ETC2 4x4 / DXT / ASTC edge artifact cleaner for Spine PMA atlases.
    Handles:
      1. A==0 & RGB>0 additive ghosting + tiny isolated low-alpha speckles + EAC halo tails
      2. Mixed 4x4 block chroma & micro-luma de-blocking on opaque outer rims (with dark-lineart protection)
      3. Semi-transparent anti-aliased edges AND feathered seams (up to 6px) AND semi-transparent layers (like hair shadows A~72)
      4. Strict PMA re-encoding (RGB <= A, A==0 -> RGBA=0)
    """
    t0 = time.time()
    H, W = src_rgba.shape[:2]
    r = src_rgba[..., 0].astype(np.float32)
    g = src_rgba[..., 1].astype(np.float32)
    b = src_rgba[..., 2].astype(np.float32)
    a = src_rgba[..., 3].astype(np.float32)

    # ------------------------------------------------------------------
    # Stage 1: Alpha hygiene (floating ETC2 micro-speckles + EAC halo tail)
    # ------------------------------------------------------------------
    a_clean = a.copy()

    # 1a. Remove tiny isolated low-alpha blobs far from solid content (<= 24px, 1<=A<=18)
    solid_any = (a_clean >= 48).astype(np.uint8)
    dist_solid = cv2.distanceTransform(1 - solid_any, cv2.DIST_L2, 5)
    far_low = ((a_clean >= 1) & (a_clean <= 18) & (dist_solid > 3.0)).astype(np.uint8)
    ncc, lbl, stats, _ = cv2.connectedComponentsWithStats(far_low, connectivity=8)
    if ncc > 1:
        areas = stats[:, cv2.CC_STAT_AREA]
        kill_ids = (areas <= 24)
        kill_ids[0] = False
        a_clean[kill_ids[lbl]] = 0.0

    # 1b. Trim EAC alpha halo tail (1..6) sitting >=2.2px outside sharp opaque edges
    opaque_230 = (a_clean >= 230).astype(np.uint8)
    dist_op230 = cv2.distanceTransform(1 - opaque_230, cv2.DIST_L2, 5)
    # Check local alpha gradient so we only trim sharp-edge halos, NOT gradual 10px feathers
    k3 = np.ones((3, 3), np.uint8)
    a_max3 = cv2.dilate(a_clean, k3)
    a_min3 = cv2.erode(a_clean, k3)
    halo_tail = (a_clean >= 1) & (a_clean <= 5) & (dist_op230 >= 2.5) & (dist_op230 <= 5.0) & (a_max3 <= 18)
    a_clean[halo_tail] = 0.0

    if uv_mask is not None:
        safe_uv = cv2.dilate(uv_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0
        a_clean[~safe_uv] = 0.0

    # Unpremultiply safely
    a_safe = np.maximum(a_clean, 1.0)
    sr = np.clip(r * 255.0 / a_safe, 0.0, 255.0)
    sg = np.clip(g * 255.0 / a_safe, 0.0, 255.0)
    sb = np.clip(b * 255.0 / a_safe, 0.0, 255.0)
    straight = np.stack([sr, sg, sb], axis=-1)

    # ------------------------------------------------------------------
    # Stage 2: Mixed 4x4 ETC2 block opaque rim chroma/de-block repair
    # ------------------------------------------------------------------
    bh, bw = H // 4, W // 4
    a_blk = a_clean[:bh*4, :bw*4].reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(bh, bw, 16)
    # Any 4x4 block with significant alpha drop (>= 40) suffers ETC2 RGB-vs-alpha mismatch!
    a_blk_range = a_blk.max(axis=2) - a_blk.min(axis=2)
    mixed_blk_small = (a_blk.max(axis=2) >= 40) & (a_blk_range >= 35)
    mixed_blk = np.zeros((H, W), dtype=bool)
    mixed_blk[:bh*4, :bw*4] = np.repeat(np.repeat(mixed_blk_small, 4, axis=0), 4, axis=1)

    trans = (a_clean <= 10).astype(np.uint8)
    dist_trans = cv2.distanceTransform(1 - trans, cv2.DIST_L2, 5)

    # Pure interior pixels: high alpha, not in a mixed alpha-transition block
    pure_interior = (a_clean >= 245) & (~mixed_blk) & (dist_trans >= 2.2)

    rim_repaired = 0
    if np.any(pure_interior):
        dist_pure, lbl_pure = cv2.distanceTransformWithLabels(
            (1 - pure_interior.astype(np.uint8)), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
        )
        py, px = np.where(pure_interior)
        nearest_pure_rgb = straight[py, px][lbl_pure.ravel() - 1].reshape(H, W, 3)

        lab_cur = cv2.cvtColor(straight.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        lab_pure = cv2.cvtColor(nearest_pure_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)

        rim_cand = mixed_blk & (a_clean >= 170) & (dist_trans <= 3.2) & (dist_pure <= 5.0)
        dL = np.abs(lab_cur[..., 0] - lab_pure[..., 0])
        dab = np.sqrt((lab_cur[..., 1] - lab_pure[..., 1])**2 + (lab_cur[..., 2] - lab_pure[..., 2])**2)

        # Protect dark lineart (dL > 28) while cleaning ETC2 greenish/grayish shift on matching-luma rims
        sim_L = np.clip((28.0 - dL) / 14.0, 0.0, 1.0)
        chroma_w = np.where(rim_cand, np.clip((dab - 2.0) / 5.0, 0.0, 1.0) * sim_L, 0.0)
        lum_w = np.where(rim_cand & (dab > 4.0) & (dL <= 18.0), 0.65 * sim_L, 0.0)

        lab_fixed = lab_cur.copy()
        lab_fixed[..., 0] = lab_cur[..., 0] * (1.0 - lum_w) + lab_pure[..., 0] * lum_w
        lab_fixed[..., 1] = lab_cur[..., 1] * (1.0 - chroma_w) + lab_pure[..., 1] * chroma_w
        lab_fixed[..., 2] = lab_cur[..., 2] * (1.0 - chroma_w) + lab_pure[..., 2] * chroma_w

        rgb_fixed = cv2.cvtColor(np.clip(lab_fixed, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
        straight = np.where(rim_cand[..., None], rgb_fixed, straight)
        rim_repaired = int(np.sum(chroma_w > 0.05))

    # ------------------------------------------------------------------
    # Stage 3: Unified Edge & Feather-Seam Straight-Color Rebuild
    #   Includes BOTH opaque anchors (A>=240) AND flat semi-transparent
    #   plateau anchors (e.g. hair shadow A~72, flat within 3x3 & not mixed_blk)
    # ------------------------------------------------------------------
    # Local alpha flatness for semi-transparent layers (like Slot 67 hair shadow)
    a_span3 = a_max3 - a_min3
    plateau_semi = (a_clean >= 35) & (a_clean < 240) & (a_span3 <= 6.0) & (~mixed_blk)
    anchor = ((a_clean >= 240) | plateau_semi).astype(np.uint8)

    dist_anc, lbl_anc = cv2.distanceTransformWithLabels(1 - anchor, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ay, ax = np.where(anchor > 0)
    ref_rgb = straight[ay, ax][lbl_anc.ravel() - 1].reshape(H, W, 3)

    # Local 5x5 gamut of anchor pixels
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    loc_max = cv2.dilate(np.where(anchor[..., None] > 0, straight, 0.0), k5)
    loc_min = cv2.erode(np.where(anchor[..., None] > 0, straight, 255.0), k5)

    oog_hi = np.maximum(0.0, straight - (loc_max + 6.0))
    oog_lo = np.maximum(0.0, (loc_min - 6.0) - straight)
    oog = np.sqrt((oog_hi**2 + oog_lo**2).sum(axis=-1))

    pma_viol = np.maximum(0.0, np.maximum(np.maximum(r, g), b) - a_clean)

    # Semi-transparent edge & feather seam pixels (up to 6.5px from anchor)
    # Must NOT be an anchor itself!
    semi_target = (a_clean >= 1.0) & (anchor == 0) & (dist_anc <= 6.5)

    # Replacement weight:
    # - Low alpha (<= 45) -> 1.0 (ETC2 SNR destroyed)
    # - PMA violation (> 1) -> 1.0
    # - Out of local anchor gamut -> strong pull to ref_rgb
    # - Inside mixed 4x4 alpha-transition block -> stronger cleanup even for A in 60..235 (fixes Slot 96 feathered skin seam!)
    w_low_a = np.clip((100.0 - a_clean) / 55.0, 0.0, 1.0)
    w_viol = np.clip((pma_viol - 0.5) / 3.0, 0.0, 1.0)
    w_oog = np.clip((oog - 4.0) / 14.0, 0.0, 1.0)

    # In Lab space, check chroma deviation vs ref_rgb for feathered seams (protects dark outline luma while killing ETC2 chroma noise!)
    lab_s = cv2.cvtColor(np.clip(straight, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    lab_r = cv2.cvtColor(np.clip(ref_rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    dL_sr = np.abs(lab_s[..., 0] - lab_r[..., 0])
    dab_sr = np.sqrt((lab_s[..., 1] - lab_r[..., 1])**2 + (lab_s[..., 2] - lab_r[..., 2])**2)

    # On feathered seams (similar luma to anchor, e.g. Slot 96 on arm), aggressively smooth out ETC2 color noise!
    w_feather = np.where(mixed_blk & (dL_sr < 32.0), np.clip((240.0 - a_clean) / 140.0, 0.25, 0.90), 0.0)
    w_chroma_spike = np.where(mixed_blk & (dab_sr > 4.0), np.clip((dab_sr - 3.0) / 8.0, 0.0, 0.95), 0.0)

    w_rep = np.maximum.reduce([w_low_a, w_viol, w_oog, w_feather, w_chroma_spike])
    w_rep = np.where(semi_target, w_rep, 0.0)

    straight_out = straight * (1.0 - w_rep[..., None]) + ref_rgb * w_rep[..., None]

    # ------------------------------------------------------------------
    # Stage 4: Strict PMA Re-encode
    # ------------------------------------------------------------------
    a_u8 = np.clip(np.rint(a_clean), 0, 255).astype(np.uint8)
    af = a_u8.astype(np.float32) / 255.0
    rgb_pma = np.clip(np.rint(straight_out * af[..., None]), 0, 255).astype(np.uint8)
    rgb_pma = np.minimum(rgb_pma, a_u8[..., None])
    out = np.concatenate([rgb_pma, a_u8[..., None]], axis=-1)

    dt = time.time() - t0
    return out, {
        'elapsed_s': round(dt, 2),
        'orig_a0_rgb': int(np.sum((src_rgba[...,3]==0) & (src_rgba[...,:3].max(axis=2)>0))),
        'orig_rgb_gt_a': int(np.sum(src_rgba[...,:3].max(axis=2) > src_rgba[...,3])),
        'new_a0_rgb': int(np.sum((out[...,3]==0) & (out[...,:3].max(axis=2)>0))),
        'new_rgb_gt_a': int(np.sum(out[...,:3].max(axis=2) > out[...,3])),
        'semi_repaired_px': int(np.sum(w_rep > 0.05)),
        'rim_repaired_px': rim_repaired,
        'untouched_pure_interior_pct': round(100.0 * np.sum(pure_interior) / max(1, np.sum(a >= 240)), 2),
    }

if __name__ == '__main__':
    d = r'.\_scratch\edge_noise_study'
    src = np.array(Image.open(r'E:\A灵魂潮汐\人偶spine\Texture2D\SoulDress_Lilyiro_05.png').convert('RGBA'))
    out, st = clean_etc2_spine_pma_v2(src)
    print('V2 Stats:', st)
    Image.fromarray(out, 'RGBA').save(d + r'\test_cleaned_v2.png')
