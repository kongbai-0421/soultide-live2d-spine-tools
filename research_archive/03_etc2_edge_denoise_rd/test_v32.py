import cv2
import numpy as np
from PIL import Image
import os, time


def clean_etc2_spine_pma_v32(src_rgba: np.ndarray, protect_mask: np.ndarray = None, uv_mask: np.ndarray = None):
    """
    V3.2 (Continuity-Verified Lineart-Safe) Physics-based ETC2 4x4 edge artifact cleaner.
    Fixes V3.1's blind spot where isolated/dotted ETC2-darkened pixels on outline-free joints
    (elbows, fingers) and bright sakura petals/ribbons were misclassified as 1px dark lineart.
    Uses 8-connected contour span + 7x7 local dark-edge fraction to distinguish TRUE continuous
    dark outlines from dotted/isolated ETC2 dark compression speckles.
    """
    t0 = time.time()
    H, W = src_rgba.shape[:2]
    r = src_rgba[..., 0].astype(np.float32)
    g = src_rgba[..., 1].astype(np.float32)
    b = src_rgba[..., 2].astype(np.float32)
    a = src_rgba[..., 3].astype(np.float32)

    pma_viol = np.maximum(0.0, np.maximum(np.maximum(r, g), b) - a)

    # ------------------------------------------------------------------
    # Stage 1: Alpha hygiene (floating ETC2 micro-speckles + EAC halo tail)
    # ------------------------------------------------------------------
    a_clean = a.copy()

    solid_any = (a_clean >= 48).astype(np.uint8)
    dist_solid = cv2.distanceTransform(1 - solid_any, cv2.DIST_L2, 5) if np.any(solid_any) else np.full((H, W), 999.0, np.float32)
    far_low = ((a_clean >= 1) & (a_clean <= 18) & (dist_solid > 3.0)).astype(np.uint8)
    ncc, lbl, stats, _ = cv2.connectedComponentsWithStats(far_low, connectivity=8)
    speckles_killed = 0
    if ncc > 1:
        areas = stats[:, cv2.CC_STAT_AREA]
        ws = stats[:, cv2.CC_STAT_WIDTH]
        hs = stats[:, cv2.CC_STAT_HEIGHT]
        kill_ids = (areas <= 24) & (np.maximum(ws, hs) <= 8)
        kill_ids[0] = False
        kill_mask = kill_ids[lbl]
        if protect_mask is not None:
            kill_mask &= (~protect_mask)
        speckles_killed = int(kill_mask.sum())
        a_clean[kill_mask] = 0.0

    opaque_230 = (a_clean >= 230).astype(np.uint8)
    dist_op230 = cv2.distanceTransform(1 - opaque_230, cv2.DIST_L2, 5) if np.any(opaque_230) else np.full((H, W), 999.0, np.float32)
    k3 = np.ones((3, 3), np.uint8)
    a_max3 = cv2.dilate(a_clean, k3)
    a_min3 = cv2.erode(a_clean, k3)
    halo_tail = (a_clean >= 1) & (a_clean <= 5) & (dist_op230 >= 2.5) & (dist_op230 <= 5.0) & (a_max3 <= 16)
    if protect_mask is not None:
        halo_tail &= (~protect_mask)
    a_clean[halo_tail] = 0.0

    if uv_mask is not None:
        safe_uv = cv2.dilate(uv_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0
        ext_kill = ~safe_uv
        if protect_mask is not None:
            ext_kill &= (~protect_mask)
        a_clean[ext_kill] = 0.0

    a_safe = np.maximum(a_clean, 1.0)
    straight = np.stack([
        np.clip(r * 255.0 / a_safe, 0.0, 255.0),
        np.clip(g * 255.0 / a_safe, 0.0, 255.0),
        np.clip(b * 255.0 / a_safe, 0.0, 255.0),
    ], axis=-1)

    # ------------------------------------------------------------------
    # Compute 4x4 ETC2 block diagnostics
    # ------------------------------------------------------------------
    bh, bw = H // 4, W // 4
    mixed_blk = np.zeros((H, W), dtype=bool)
    soft_mixed_blk = np.zeros((H, W), dtype=bool)
    viol_blk = np.zeros((H, W), dtype=bool)
    if bh > 0 and bw > 0:
        a_blk = a_clean[:bh * 4, :bw * 4].reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(bh, bw, 16)
        v_blk = pma_viol[:bh * 4, :bw * 4].reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(bh, bw, 16)
        a_blk_max = a_blk.max(axis=2)
        a_blk_min = a_blk.min(axis=2)
        v_blk_max = v_blk.max(axis=2)

        mixed_blk[:bh * 4, :bw * 4] = np.repeat(np.repeat((a_blk_max >= 160) & (a_blk_min <= 30) & ((a_blk_max - a_blk_min) >= 60), 4, axis=0), 4, axis=1)
        soft_mixed_blk[:bh * 4, :bw * 4] = np.repeat(np.repeat((a_blk_max >= 35) & (a_blk_min <= 8) & ((a_blk_max - a_blk_min) >= 30), 4, axis=0), 4, axis=1)
        viol_blk[:bh * 4, :bw * 4] = np.repeat(np.repeat(v_blk_max >= 5.0, 4, axis=0), 4, axis=1)

    trans = (a_clean <= 10).astype(np.uint8)
    dist_trans = cv2.distanceTransform(1 - trans, cv2.DIST_L2, 5) if np.any(trans) else np.full((H, W), 999.0, np.float32)

    # ------------------------------------------------------------------
    # Stage 1.5: Pre-compute TRUE Continuous Dark Lineart Mask
    #   (Distinguishes continuous 1px dark outlines from isolated/dotted
    #    ETC2 dark speckles on elbow joints, fingers, sakura petals!)
    # ------------------------------------------------------------------
    pure_interior = (a_clean >= 245) & (~mixed_blk) & (dist_trans >= 2.2)
    lab_cur_all = cv2.cvtColor(straight.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)

    has_pure = np.any(pure_interior)
    if has_pure:
        dist_pure, lbl_pure = cv2.distanceTransformWithLabels(
            (1 - pure_interior.astype(np.uint8)), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
        )
        py, px = np.where(pure_interior)
        nearest_pure_rgb = straight[py, px][lbl_pure.ravel() - 1].reshape(H, W, 3)
        lab_pure = cv2.cvtColor(nearest_pure_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        signed_dL_pure = lab_cur_all[..., 0] - lab_pure[..., 0]
        dark_opaque_rim = (a_clean >= 242) & (dist_trans <= 2.5) & (dist_pure <= 5.5) & (signed_dL_pure < -14.0)
    else:
        dark_opaque_rim = np.zeros((H, W), dtype=bool)
        dist_pure = np.full((H, W), 999.0, np.float32)
        lab_pure = lab_cur_all
        signed_dL_pure = np.zeros((H, W), np.float32)

    # Initial opaque/plateau anchors (before lineart refinement)
    a_span3 = a_max3 - a_min3
    plateau_semi = (a_clean >= 35) & (a_clean < 242) & (a_span3 <= 6.0) & (~soft_mixed_blk) & (dist_trans >= 2.2)
    anchor_op = (a_clean >= 242)
    anchor_init = (anchor_op | plateau_semi).astype(np.uint8)

    true_dark_lineart = np.zeros((H, W), dtype=bool)
    if np.any(anchor_init):
        dist_ai, lbl_ai = cv2.distanceTransformWithLabels(1 - anchor_init, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        ay0, ax0 = np.where(anchor_init > 0)
        ref_init = straight[ay0, ax0][lbl_ai.ravel() - 1].reshape(H, W, 3)
        lab_ri = cv2.cvtColor(ref_init.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        sdL_init = lab_cur_all[..., 0] - lab_ri[..., 0]

        # Candidate dark pixels along semi-transparent edges (no PMA violation)
        dark_semi_cand = (a_clean >= 25.0) & (a_clean < 242.0) & (dist_ai <= 4.5) & (sdL_init < -14.0) & (pma_viol <= 1.0)
        dark_union = (dark_semi_cand | dark_opaque_rim).astype(np.uint8)

        # Criterion 1: 8-connected contour continuity (span >= 8px AND area >= 10px)
        # Kills 1-6px isolated ETC2 dark dots on joints & sakura petals!
        ncc_d, lbl_d, stats_d, _ = cv2.connectedComponentsWithStats(dark_union, connectivity=8)
        cont_ok = np.zeros((H, W), dtype=bool)
        if ncc_d > 1:
            d_areas = stats_d[:, cv2.CC_STAT_AREA]
            d_spans = np.maximum(stats_d[:, cv2.CC_STAT_WIDTH], stats_d[:, cv2.CC_STAT_HEIGHT])
            keep_d = (d_areas >= 10) & (d_spans >= 8)
            keep_d[0] = False
            cont_ok = keep_d[lbl_d]

        # Criterion 2: Local 7x7 dark-edge density (dark pixels must form a dense edge, not sparse dots in bright skin!)
        edge_band = (((a_clean >= 20.0) & (a_clean < 242.0) & (dist_ai <= 4.0)) | dark_opaque_rim).astype(np.float32)
        n_dark7 = cv2.boxFilter(dark_union.astype(np.float32), -1, (7, 7), normalize=False)
        n_edge7 = cv2.boxFilter(edge_band, -1, (7, 7), normalize=False)
        dark_frac7 = n_dark7 / np.maximum(n_edge7, 1.0)

        # True continuous dark lineart: connected contour + consistent local dark density (or adjacent to dark opaque rim!)
        adj_dark_op = cv2.dilate(dark_opaque_rim.astype(np.uint8), k3) > 0
        true_dark_lineart = dark_semi_cand & cont_ok & ((dark_frac7 >= 0.42) | adj_dark_op) & (a_clean >= 40.0)

    # ------------------------------------------------------------------
    # Stage 2: Mixed 4x4 ETC2 block opaque outer-rim chroma/luma de-block
    # ------------------------------------------------------------------
    rim_repaired = 0
    if has_pure:
        rim_cand = mixed_blk & (a_clean >= 175) & (dist_trans <= 3.2) & (dist_pure <= 5.0)
        if protect_mask is not None:
            rim_cand &= (~protect_mask)

        dL = np.abs(signed_dL_pure)
        dab = np.sqrt((lab_cur_all[..., 1] - lab_pure[..., 1]) ** 2 + (lab_cur_all[..., 2] - lab_pure[..., 2]) ** 2)

        # Only protect dark opaque rim if it belongs to a CONTINUOUS dark contour (not an isolated darkened ETC2 block!)
        rim_is_true_dark = dark_opaque_rim & (cv2.dilate(true_dark_lineart.astype(np.uint8), k3) > 0 if np.any(true_dark_lineart) else False)
        # Also protect any dark_opaque_rim whose own connected component in dark_opaque_rim has span >= 8
        ncc_r, lbl_r, stats_r, _ = cv2.connectedComponentsWithStats(dark_opaque_rim.astype(np.uint8), connectivity=8)
        if ncc_r > 1:
            r_spans = np.maximum(stats_r[:, cv2.CC_STAT_WIDTH], stats_r[:, cv2.CC_STAT_HEIGHT])
            r_areas = stats_r[:, cv2.CC_STAT_AREA]
            r_keep = (r_areas >= 8) & (r_spans >= 7)
            r_keep[0] = False
            rim_is_true_dark |= r_keep[lbl_r]

        sim_L_chroma = np.where(rim_is_true_dark, np.clip((24.0 - dL) / 12.0, 0.0, 1.0), 1.0)
        chroma_w = np.where(rim_cand, np.clip((dab - 2.0) / 4.5, 0.0, 1.0) * sim_L_chroma, 0.0)
        # Fix darkened isolated ETC2 rim blocks (e.g. sakura/joint caps where rim_is_true_dark is False!)
        lum_w = np.where(
            rim_cand & (~rim_is_true_dark) & ((dab > 3.2) | (signed_dL_pure < -12.0)),
            np.clip(np.maximum((dab - 2.5) / 5.0, (-signed_dL_pure - 10.0) / 18.0), 0.0, 0.85),
            0.0,
        )

        lab_fixed = lab_cur_all.copy()
        lab_fixed[..., 0] = lab_cur_all[..., 0] * (1.0 - lum_w) + lab_pure[..., 0] * lum_w
        lab_fixed[..., 1] = lab_cur_all[..., 1] * (1.0 - chroma_w) + lab_pure[..., 1] * chroma_w
        lab_fixed[..., 2] = lab_cur_all[..., 2] * (1.0 - chroma_w) + lab_pure[..., 2] * chroma_w

        rgb_fixed = cv2.cvtColor(np.clip(lab_fixed, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
        straight = np.where(rim_cand[..., None], rgb_fixed, straight)
        rim_repaired = int(np.sum((chroma_w > 0.05) | (lum_w > 0.05)))

    # ------------------------------------------------------------------
    # Stage 3: Semi-Transparent Edge, Joint-Seam & Petal Rebuild
    # ------------------------------------------------------------------
    # Anchor includes: opaque pixels + flat semi-transparent plateaus + verified continuous true dark lineart (A>=110)!
    # That way AA pixels immediately outside a TRUE dark outline inherit the dark outline color,
    # while dotted ETC2 dark speckles on outline-free joints & sakura petals inherit the clean bright skin/petal color!
    anchor = (anchor_op | plateau_semi | (true_dark_lineart & (a_clean >= 110.0))).astype(np.uint8)

    semi_repaired = 0
    dark_speckles_crushed = 0
    semi_target = np.zeros((H, W), dtype=bool)
    straight_out = straight.copy()

    if np.any(anchor):
        dist_anc, lbl_anc = cv2.distanceTransformWithLabels(1 - anchor, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        ay, ax = np.where(anchor > 0)
        raw_ref_rgb = straight[ay, ax][lbl_anc.ravel() - 1].reshape(H, W, 3)

        # Edge-preserving bilateral smooth on anchor reference (removes single-px anchor jitter while keeping dark outlines crisp!)
        ref_rgb = cv2.bilateralFilter(
            np.clip(raw_ref_rgb, 0, 255).astype(np.uint8), d=5, sigmaColor=20, sigmaSpace=2.5
        ).astype(np.float32)

        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        loc_max = cv2.dilate(np.where(anchor[..., None] > 0, straight, 0.0), k5)
        loc_min = cv2.erode(np.where(anchor[..., None] > 0, straight, 255.0), k5)
        oog_hi = np.sqrt((np.maximum(0.0, straight - (loc_max + 8.0)) ** 2).sum(axis=-1))
        oog_lo = np.sqrt((np.maximum(0.0, (loc_min - 8.0) - straight) ** 2).sum(axis=-1))

        near_edge_band = (dist_trans <= 5.5) | soft_mixed_blk
        semi_target = (a_clean >= 1.0) & (anchor == 0) & (dist_anc <= 6.5) & near_edge_band
        if protect_mask is not None:
            semi_target &= (~protect_mask)

        lab_s = cv2.cvtColor(np.clip(straight, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        lab_r = cv2.cvtColor(np.clip(ref_rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)

        signed_dL_sr = lab_s[..., 0] - lab_r[..., 0]
        dL_sr = np.abs(signed_dL_sr)
        dab_sr = np.sqrt((lab_s[..., 1] - lab_r[..., 1]) ** 2 + (lab_s[..., 2] - lab_r[..., 2]) ** 2)

        # Now ONLY verified continuous dark lineart is protected!
        # Isolated / dotted ETC2 dark speckles (true_dark_lineart == False) are aggressively rebuilt!
        w_low_a = np.clip((90.0 - a_clean) / 50.0, 0.0, 1.0)
        w_viol = np.where(
            (pma_viol > 8.0) | ((pma_viol > 2.0) & (dab_sr > 4.0)),
            np.clip((pma_viol - 1.5) / 6.0, 0.0, 1.0),
            0.0,
        )
        w_oog_hi = np.clip((oog_hi - 6.0) / 16.0, 0.0, 1.0)
        # For non-lineart pixels, oog_lo (sudden dark/black ETC2 drop on bright skin/sakura!) IS a compression artifact!
        w_oog_lo = np.where(~true_dark_lineart, np.clip((oog_lo - 10.0) / 18.0, 0.0, 1.0), 0.0)
        w_dark_speckle = np.where(
            (~true_dark_lineart) & (signed_dL_sr < -12.0),
            np.clip((-signed_dL_sr - 10.0) / 16.0, 0.0, 1.0),
            0.0,
        )

        anc_is_op = anchor_op[ay, ax][lbl_anc.ravel() - 1].reshape(H, W)
        w_feather = np.where(
            anc_is_op & (dist_trans <= 5.5) & (~true_dark_lineart),
            np.clip((242.0 - a_clean) / 80.0, 0.45, 1.0),
            0.0,
        )
        w_chroma_spike = np.where(soft_mixed_blk & (dab_sr > 4.0), np.clip((dab_sr - 3.0) / 7.0, 0.0, 0.95), 0.0)

        w_full = np.maximum.reduce([w_low_a, w_viol, w_oog_hi, w_oog_lo, w_dark_speckle, w_feather, w_chroma_spike])
        w_full = np.where(semi_target & (~true_dark_lineart), w_full, 0.0)
        semi_repaired = int(np.sum(w_full > 0.05))
        dark_speckles_crushed = int(np.sum(semi_target & (~true_dark_lineart) & (signed_dL_sr < -14.0)))

        # For verified continuous dark lineart: preserve L*, only despill extreme chroma spikes
        w_lineart_ab = np.where(
            semi_target & true_dark_lineart & soft_mixed_blk & (dab_sr > 10.0),
            np.clip((dab_sr - 9.0) / 14.0, 0.0, 0.65),
            0.0,
        )

        straight_out = straight * (1.0 - w_full[..., None]) + ref_rgb * w_full[..., None]

        if np.any(w_lineart_ab > 0.01):
            lab_la = lab_s.copy()
            lab_la[..., 1] = lab_s[..., 1] * (1.0 - w_lineart_ab) + lab_r[..., 1] * w_lineart_ab
            lab_la[..., 2] = lab_s[..., 2] * (1.0 - w_lineart_ab) + lab_r[..., 2] * w_lineart_ab
            rgb_la = cv2.cvtColor(np.clip(lab_la, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
            straight_out = np.where((w_lineart_ab > 0.01)[..., None], rgb_la, straight_out)

    # ------------------------------------------------------------------
    # Stage 4: Strict PMA Re-encode (RGB <= A, A==0 -> RGBA=0)
    # ------------------------------------------------------------------
    a_u8 = np.clip(np.rint(a_clean), 0, 255).astype(np.uint8)
    af = a_u8.astype(np.float32) / 255.0
    rgb_pma = np.clip(np.rint(straight_out * af[..., None]), 0, 255).astype(np.uint8)
    rgb_pma = np.minimum(rgb_pma, a_u8[..., None])
    out = np.concatenate([rgb_pma, a_u8[..., None]], axis=-1)

    if protect_mask is not None:
        out = np.where(protect_mask[..., None], src_rgba, out)

    dt = time.time() - t0
    return out, {
        'elapsed_s': round(dt, 2),
        'orig_a0_rgb': int(np.sum((src_rgba[..., 3] == 0) & (src_rgba[..., :3].max(axis=2) > 0))),
        'orig_rgb_gt_a': int(np.sum(src_rgba[..., :3].max(axis=2) > src_rgba[..., 3])),
        'new_a0_rgb': int(np.sum((out[..., 3] == 0) & (out[..., :3].max(axis=2) > 0))),
        'new_rgb_gt_a': int(np.sum(out[..., :3].max(axis=2) > out[..., 3])),
        'speckles_killed_px': speckles_killed,
        'rim_repaired_px': rim_repaired,
        'semi_repaired_px': semi_repaired,
        'dark_speckles_crushed_px': dark_speckles_crushed,
        'true_dark_lineart_protected_px': int(np.sum(true_dark_lineart)),
        'untouched_pure_interior_pct': round(100.0 * float(np.sum(pure_interior)) / max(1, int(np.sum(a >= 240))), 2),
    }


if __name__ == '__main__':
    d = r'.\_scratch\edge_noise_study'
    tests = [
        ('benten_main', r'E:\A灵魂潮汐\备份\spine_etc2_before_clean\神纳木弁天\神前结契\SoulDress_Benten_04.png'),
        ('benten_bj01', r'E:\A灵魂潮汐\备份\spine_etc2_before_clean\神纳木弁天\神前结契\submodels\bj_01\SoulDress_Benten_04_BJ_01.png'),
        ('haliva_03',   r'E:\A灵魂潮汐\备份\spine_etc2_before_clean\阿拉芙\神赐永恒\SoulDress_Haliva_03.png'),
    ]
    for tag, path in tests:
        src = np.array(Image.open(path).convert('RGBA'))
        out, st = clean_etc2_spine_pma_v32(src)
        print(f'=== {tag} V3.2 ===\n  {st}')
        Image.fromarray(out, 'RGBA').save(os.path.join(d, f'{tag}_v32.png'))
