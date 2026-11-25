#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SoulTide Spine ETC2 4x4 Edge Artifact Cleaner (V4.4 Production Tool)

Fixes ETC2 RGBA8 / DXT / ASTC 4x4 lossy compression artifacts on Spine Premultiplied Alpha (PMA) atlases:
  1. Eliminates A==0 & RGB>0 additive ghosting speckles and RGB>A PMA violations (strict PMA re-encode).
  2. Removes tiny isolated low-alpha floating speckles (<=24px, max side <=8px) and EAC halo tails.
  3. Core-Verified True Dark Contour & Color Trim Protection (Stage 1.5 + Stage 2):
       - Expands opaque dark contour reach to dist_trans <= 4.6px (matching Stage 2), combines
         eff_sdL_semi = min(sdL_init, signed_dL_pure) for 2px dark outlines on dark bases, adds
         core ink verification (L<=155 & dL<=-22, L<=95 & dL<=-6, or pure-white-base pale outlines
         L<=190 & dL<=-55) and narrow 2~4px dark feather/hair tip protection.
       - Rejects bright petal/skin ETC2 gray-rim false positives (T4) while protecting 100% of real
         1px dark outlines and continuous 1px high-chroma colored trims (true_color_trim).
  4. Broad 4x4 ETC2 Block Bilateral Rim De-Block (Stage 2):
       - Covers BOTH hard mixed blocks (a_min<=30) AND semi-mixed 4x4 blocks (a_min<=238, span>=20)
         out to dist_trans<=4.6px (full 4x4 diagonal 4.24px), referenced against pure_interior
         (~broad_mixed_blk & dist_trans>=3.0) with island/ray path-clear guard.
       - Repairs BOTH negative ETC2 darkening (T1a/b/c, elbow/shoulder/finger dotted seams) AND
         positive bright overshoot (T3) via exact RGB interpolation, purifying Stage 3 anchors.
  5. Dual-Channel Anti-Black-Hole Semi-Transparent Rebuild (Stage 3):
       - Strictly isolates anchor_fill (excludes true_dark_contour) from anchor_dark (used ONLY by
         outer low-A AA strictly closer to TDC than fill, never winning ties), plus straight-luminance
         Anti-Black-Hole guard -> eliminates V3.3 dark-anchor black-hole regression (T2).
       - Adds has_local_anc guard on 5x5 OOG bounds and cross-hue watercolor protection so painterly
         translucent clouds, sakura petals, and delicate lace/veils remain 100% intact.
  6. Protects Straight Alpha static layers (bg_static/bg_mid/fg_static/fx_*) and optional
     Additive/Screen UV masks; supports idempotent backup & --from-backup lossless re-processing
     with atomic original-format write (.png or lossless exact=True .webp with round-trip verification).
"""

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import time
import cv2
import numpy as np
from PIL import Image


def detect_pma_etc2_atlas(rgba: np.ndarray) -> dict:
    H, W = rgba.shape[:2]
    r = rgba[..., 0].astype(np.int32)
    g = rgba[..., 1].astype(np.int32)
    b = rgba[..., 2].astype(np.int32)
    a = rgba[..., 3].astype(np.int32)
    mx = np.maximum(np.maximum(r, g), b)
    diff = mx - a

    a0_rgb = int(np.sum((a == 0) & (mx > 0)))
    viol = int(np.sum(diff > 0))
    viol15 = int(np.sum(diff > 15))

    gx = np.abs(np.diff(rgba.astype(np.float32), axis=1)).mean(axis=2)
    b4 = float(gx[:, 3::4].mean()) if W >= 8 else 0.0
    inn_idx = [j for j in range(gx.shape[1]) if (j + 1) % 4 != 0]
    inn = float(gx[:, inn_idx].mean()) if inn_idx else 1.0
    blk_ratio = b4 / max(inn, 1e-6)

    big_viol_mask = ((a >= 10) & (a <= 210) & (diff > 25)).astype(np.uint8)
    ncc, _, stats, _ = cv2.connectedComponentsWithStats(big_viol_mask, connectivity=8)
    max_big_comp = int(stats[1:, cv2.CC_STAT_AREA].max()) if ncc > 1 else 0

    is_straight_or_glow = ((max_big_comp > 400) and (a0_rgb < 200)) or ((a0_rgb == 0) and (max_big_comp >= 20))
    needs_clean = (not is_straight_or_glow) and (
        (viol > 100) or (a0_rgb > 50) or (blk_ratio > 1.06 and viol > 20)
    )

    return {
        'needs_clean': bool(needs_clean),
        'is_straight_or_glow': bool(is_straight_or_glow),
        'blk_ratio_4x4': round(blk_ratio, 4),
        'a0_rgb': a0_rgb,
        'viol': viol,
        'viol15': viol15,
        'max_big_viol_comp': max_big_comp,
    }


def _path_clear_mask(a_clean: np.ndarray, cc_solid: np.ndarray, ry: np.ndarray, rx: np.ndarray) -> np.ndarray:
    """Check that pixels with a_clean > 10 stay inside the same non-transparent island
    and do not jump across a transparent gap along the ray to (ry, rx)."""
    H, W = a_clean.shape
    yy, xx = np.indices((H, W), dtype=np.int32)
    same_cc = (cc_solid == cc_solid[ry, rx])
    m1y = (3 * yy + ry) >> 2
    m1x = (3 * xx + rx) >> 2
    m2y = (yy + ry) >> 1
    m2x = (xx + rx) >> 1
    m3y = (yy + 3 * ry) >> 2
    m3x = (xx + 3 * rx) >> 2
    ray_ok = (a_clean[m1y, m1x] > 10.0) & (a_clean[m2y, m2x] > 10.0) & (a_clean[m3y, m3x] > 10.0)
    return same_cc & ray_ok


def clean_etc2_spine_pma_v3(
    src_rgba: np.ndarray,
    protect_mask: np.ndarray = None,
    uv_mask: np.ndarray = None,
):
    """V4.4 ETC2 4x4 PMA cleaner (retains v3 symbol for backward compatibility)."""
    t0 = time.time()
    H, W = src_rgba.shape[:2]
    r = src_rgba[..., 0].astype(np.float32)
    g = src_rgba[..., 1].astype(np.float32)
    b = src_rgba[..., 2].astype(np.float32)
    a = src_rgba[..., 3].astype(np.float32)

    src_max_rgb = np.maximum(np.maximum(r, g), b)
    pma_viol = np.maximum(0.0, src_max_rgb - a)

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
    # Stage 1.2: 4x4 ETC2 block diagnostics + island connectivity
    # ------------------------------------------------------------------
    bh, bw = H // 4, W // 4
    mixed_blk = np.zeros((H, W), dtype=bool)
    broad_mixed_blk = np.zeros((H, W), dtype=bool)
    soft_mixed_blk = np.zeros((H, W), dtype=bool)
    if bh > 0 and bw > 0:
        a_blk = a_clean[:bh * 4, :bw * 4].reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(bh, bw, 16)
        a_blk_max = a_blk.max(axis=2)
        a_blk_min = a_blk.min(axis=2)
        a_blk_span = a_blk_max - a_blk_min
        mixed_blk[:bh * 4, :bw * 4] = np.repeat(np.repeat((a_blk_max >= 160) & (a_blk_min <= 30) & (a_blk_span >= 60), 4, axis=0), 4, axis=1)
        broad_mixed_blk[:bh * 4, :bw * 4] = np.repeat(np.repeat((a_blk_max >= 160) & (a_blk_min <= 238) & (a_blk_span >= 20), 4, axis=0), 4, axis=1)
        soft_mixed_blk[:bh * 4, :bw * 4] = np.repeat(np.repeat((a_blk_max >= 35) & (a_blk_min <= 8) & (a_blk_span >= 30), 4, axis=0), 4, axis=1)
    semi_mixed_only = broad_mixed_blk & (~mixed_blk)

    trans = (a_clean <= 10).astype(np.uint8)
    dist_trans = cv2.distanceTransform(1 - trans, cv2.DIST_L2, 5) if np.any(trans) else np.full((H, W), 999.0, np.float32)
    _, cc_solid = cv2.connectedComponents((a_clean > 10).astype(np.uint8), connectivity=8)

    # ------------------------------------------------------------------
    # Stage 1.5: Core-Verified Unified True Dark Contour Detector (Fixes T4)
    # ------------------------------------------------------------------
    pure_interior = (a_clean >= 245) & (~broad_mixed_blk) & (dist_trans >= 3.0)
    lab_cur_all = cv2.cvtColor(np.clip(np.rint(straight), 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)

    has_pure = np.any(pure_interior)
    if has_pure:
        dist_pure, lbl_pure = cv2.distanceTransformWithLabels(
            (1 - pure_interior.astype(np.uint8)), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
        )
        py, px = np.where(pure_interior)
        idx_p = lbl_pure.ravel() - 1
        ry_p = py[idx_p].reshape(H, W)
        rx_p = px[idx_p].reshape(H, W)
        nearest_pure_rgb = straight[ry_p, rx_p]
        pure_path_ok = _path_clear_mask(a_clean, cc_solid, ry_p, rx_p)
        lab_pure = cv2.cvtColor(np.clip(np.rint(nearest_pure_rgb), 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        signed_dL_pure = lab_cur_all[..., 0] - lab_pure[..., 0]
    else:
        dist_pure = np.full((H, W), 999.0, np.float32)
        nearest_pure_rgb = straight
        pure_path_ok = np.zeros((H, W), dtype=bool)
        lab_pure = lab_cur_all
        signed_dL_pure = np.zeros((H, W), np.float32)

    a_span3 = a_max3 - a_min3
    plateau_semi = (a_clean >= 35) & (a_clean < 242) & (a_span3 <= 6.0) & (~soft_mixed_blk) & (dist_trans >= 2.2)
    anchor_init = ((a_clean >= 242.0) | plateau_semi).astype(np.uint8)

    true_dark_contour = np.zeros((H, W), dtype=bool)
    if np.any(anchor_init):
        dist_ai, lbl_ai = cv2.distanceTransformWithLabels(1 - anchor_init, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        ay0, ax0 = np.where(anchor_init > 0)
        idx_ai = lbl_ai.ravel() - 1
        ry_ai = ay0[idx_ai].reshape(H, W)
        rx_ai = ax0[idx_ai].reshape(H, W)
        ref_init = straight[ry_ai, rx_ai]
        ai_path_ok = _path_clear_mask(a_clean, cc_solid, ry_ai, rx_ai)
        lab_ri = cv2.cvtColor(np.clip(np.rint(ref_init), 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        sdL_init = lab_cur_all[..., 0] - lab_ri[..., 0]

        has_near_pure = has_pure & (dist_pure <= 6.5) & pure_path_ok
        eff_sdL_semi = np.where(has_near_pure, np.minimum(sdL_init, signed_dL_pure), sdL_init)
        L_cur = lab_cur_all[..., 0]

        semi_viol_ok = (pma_viol <= 1.0) | ((pma_viol <= 2.0) & (L_cur <= 110.0))
        dark_semi_delta = (eff_sdL_semi < -12.0) | ((L_cur <= 65.0) & (eff_sdL_semi < -6.0))
        dark_op_delta = (signed_dL_pure < -12.0) | ((L_cur <= 65.0) & (signed_dL_pure < -6.0))

        dark_semi_cand = (a_clean >= 30.0) & (a_clean < 242.0) & ((dist_ai <= 5.5) | has_near_pure) & (ai_path_ok | has_near_pure) & dark_semi_delta & semi_viol_ok
        dark_op_cand = (a_clean >= 242.0) & (dist_trans <= 4.6) & (dist_pure <= 6.5) & pure_path_ok & dark_op_delta
        dark_union = (dark_semi_cand | dark_op_cand).astype(np.uint8)

        ncc_d, lbl_d, stats_d, _ = cv2.connectedComponentsWithStats(dark_union, connectivity=8)
        if ncc_d > 1:
            d_areas = stats_d[:, cv2.CC_STAT_AREA]
            d_spans = np.maximum(stats_d[:, cv2.CC_STAT_WIDTH], stats_d[:, cv2.CC_STAT_HEIGHT])
            comp_max_a = np.zeros(ncc_d, dtype=np.float32)
            np.maximum.at(comp_max_a, lbl_d.ravel(), a_clean.ravel())
            comp_hi_a = np.bincount(lbl_d.ravel(), weights=(a_clean.ravel() >= 120.0), minlength=ncc_d)
            comp_hi_ratio = comp_hi_a / np.maximum(d_areas, 1)

            eff_dL = np.where(a_clean >= 242.0, signed_dL_pure, eff_sdL_semi)
            is_core_ink = (
                ((L_cur <= 155.0) & (eff_dL <= -22.0) & (a_clean >= 60.0))
                | ((L_cur <= 95.0) & (eff_dL <= -6.0) & (a_clean >= 60.0))
                | ((L_cur <= 190.0) & (eff_dL <= -55.0) & (a_clean >= 80.0))
            )
            comp_core_cnt = np.bincount(lbl_d.ravel(), weights=is_core_ink.ravel(), minlength=ncc_d)
            comp_core_ratio = comp_core_cnt / np.maximum(d_areas, 1)

            keep_d = (
                (d_areas >= 9)
                & (d_spans >= 8)
                & (comp_max_a >= 140.0)
                & (comp_hi_ratio >= 0.25)
                & (comp_core_cnt >= 3)
                & (comp_core_ratio >= 0.08)
            )
            is_thin_tip_dark = (dist_pure > 6.5) & (L_cur <= 115.0) & (eff_dL <= -25.0) & (a_clean >= 80.0) & (pma_viol <= 1.0)
            comp_tip_cnt = np.bincount(lbl_d.ravel(), weights=is_thin_tip_dark.ravel(), minlength=ncc_d)
            keep_tip = (d_areas >= 3) & (d_spans >= 3) & (comp_max_a >= 120.0) & (comp_tip_cnt >= 2)
            keep_d |= keep_tip
            keep_d[0] = False
            true_dark_contour = keep_d[lbl_d]

    # ------------------------------------------------------------------
    # Stage 2: Broad 4x4 ETC2 Block Bilateral Rim De-Block (Fixes T1a/b/c + T3)
    # ------------------------------------------------------------------
    rim_repaired = 0
    true_color_trim = np.zeros((H, W), dtype=bool)
    if has_pure:
        rim_cand = broad_mixed_blk & (a_clean >= 175.0) & (dist_trans <= 4.6) & (dist_pure <= 6.5) & pure_path_ok
        if protect_mask is not None:
            rim_cand &= (~protect_mask)

        dL = np.abs(signed_dL_pure)
        dab = np.sqrt((lab_cur_all[..., 1] - lab_pure[..., 1]) ** 2 + (lab_cur_all[..., 2] - lab_pure[..., 2]) ** 2)

        trim_cand = (a_clean >= 150.0) & (dist_trans <= 4.6) & (dist_pure <= 6.5) & pure_path_ok & (dab > 18.0) & (pma_viol <= 2.0) & (~true_dark_contour)
        if np.any(trim_cand):
            ncc_t, lbl_t, stats_t, _ = cv2.connectedComponentsWithStats(trim_cand.astype(np.uint8), connectivity=8)
            if ncc_t > 1:
                t_areas = stats_t[:, cv2.CC_STAT_AREA]
                t_spans = np.maximum(stats_t[:, cv2.CC_STAT_WIDTH], stats_t[:, cv2.CC_STAT_HEIGHT])
                keep_t = (t_areas >= 6) & (t_spans >= 6)
                keep_t[0] = False
                true_color_trim = keep_t[lbl_t]

        rim_non_tdc = rim_cand & (~true_dark_contour) & (~true_color_trim)
        semi_trim_guard = semi_mixed_only & ((dab > 16.0) | (signed_dL_pure > 26.0) | (signed_dL_pure < -35.0))
        bright_rimlight_guard = (a_clean >= 250.0) & (pma_viol <= 0.5) & (signed_dL_pure > 30.0)
        rim_fixable = rim_non_tdc & (~semi_trim_guard) & (~bright_rimlight_guard)

        w_neg_L = np.clip((-signed_dL_pure - 2.5) / 5.5, 0.0, 1.0)
        w_pos_L = np.where(signed_dL_pure <= 30.0, np.clip((signed_dL_pure - 3.0) / 6.0, 0.0, 1.0), 0.0)
        w_ab = np.clip((dab - 1.5) / 3.5, 0.0, 1.0)
        w_rim = np.where(rim_fixable, np.maximum.reduce([w_neg_L, w_pos_L, w_ab]), 0.0)

        straight = np.where(
            (w_rim > 0.01)[..., None],
            straight * (1.0 - w_rim[..., None]) + nearest_pure_rgb * w_rim[..., None],
            straight,
        )

        rim_tdc = rim_cand & true_dark_contour & mixed_blk
        sim_L_chroma = np.clip((22.0 - dL) / 11.0, 0.0, 1.0)
        tdc_chroma_w = np.where(rim_tdc & (dab > 4.0), np.clip((dab - 3.5) / 6.0, 0.0, 0.85) * sim_L_chroma, 0.0)
        if np.any(tdc_chroma_w > 0.05):
            lab_tdc = lab_cur_all.copy()
            lab_tdc[..., 1] = lab_cur_all[..., 1] * (1.0 - tdc_chroma_w) + lab_pure[..., 1] * tdc_chroma_w
            lab_tdc[..., 2] = lab_cur_all[..., 2] * (1.0 - tdc_chroma_w) + lab_pure[..., 2] * tdc_chroma_w
            rgb_tdc = cv2.cvtColor(np.clip(lab_tdc, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
            straight = np.where((tdc_chroma_w > 0.05)[..., None], rgb_tdc, straight)

        rim_repaired = int(np.sum((w_rim > 0.05) | (tdc_chroma_w > 0.05)))

    # ------------------------------------------------------------------
    # Stage 3: Dual-Channel Anchor Semi-Transparent Rebuild (Fixes T2, T3, T5)
    # ------------------------------------------------------------------
    anchor_op_clean = (a_clean >= 242.0) & (~true_dark_contour)
    anchor_fill = (anchor_op_clean | (plateau_semi & (~true_dark_contour)) | true_color_trim).astype(np.uint8)
    anchor_dark = (true_dark_contour & (a_clean >= 80.0)).astype(np.uint8)

    semi_repaired = 0
    dark_speckles_crushed = 0
    semi_target = np.zeros((H, W), dtype=bool)
    straight_out = straight.copy()

    if np.any(anchor_fill):
        dist_fill, lbl_fill = cv2.distanceTransformWithLabels(1 - anchor_fill, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        ay, ax = np.where(anchor_fill > 0)
        idx_f = lbl_fill.ravel() - 1
        ry_f = ay[idx_f].reshape(H, W)
        rx_f = ax[idx_f].reshape(H, W)
        raw_ref_fill = straight[ry_f, rx_f]
        anc_is_op = anchor_op_clean[ry_f, rx_f]

        ref_fill = cv2.bilateralFilter(
            np.clip(np.rint(raw_ref_fill), 0, 255).astype(np.uint8), d=5, sigmaColor=18, sigmaSpace=2.0
        ).astype(np.float32)

        fill_path_ok = np.where(a_clean > 10.0, _path_clear_mask(a_clean, cc_solid, ry_f, rx_f), True)

        if np.any(anchor_dark):
            dist_dark, lbl_dark = cv2.distanceTransformWithLabels(1 - anchor_dark, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
            dy, dx = np.where(anchor_dark > 0)
            idx_dk = lbl_dark.ravel() - 1
            ref_dark = straight[dy[idx_dk], dx[idx_dk]].reshape(H, W, 3)
        else:
            dist_dark = np.full((H, W), 999.0, np.float32)
            ref_dark = ref_fill

        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        has_local_anc = cv2.dilate(anchor_fill, k5) > 0
        loc_max = cv2.dilate(np.where(anchor_fill[..., None] > 0, straight, 0.0), k5)
        loc_min = cv2.erode(np.where(anchor_fill[..., None] > 0, straight, 255.0), k5)
        oog_hi = np.sqrt((np.maximum(0.0, straight - (loc_max + 8.0)) ** 2).sum(axis=-1))
        oog_lo = np.sqrt((np.maximum(0.0, (loc_min - 8.0) - straight) ** 2).sum(axis=-1))

        near_edge_band = (dist_trans <= 5.5) | soft_mixed_blk
        is_any_anchor = (anchor_fill > 0) | (anchor_dark > 0)
        dist_nearest = np.minimum(dist_fill, dist_dark)
        semi_target = (a_clean >= 1.0) & (~is_any_anchor) & (dist_nearest <= 6.5) & near_edge_band
        if protect_mask is not None:
            semi_target &= (~protect_mask)

        lab_s = cv2.cvtColor(np.clip(np.rint(straight), 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        lab_rf = cv2.cvtColor(np.clip(np.rint(ref_fill), 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)

        signed_dL_sf = lab_s[..., 0] - lab_rf[..., 0]
        dab_sf = np.sqrt((lab_s[..., 1] - lab_rf[..., 1]) ** 2 + (lab_s[..., 2] - lab_rf[..., 2]) ** 2)

        use_dark_ref = (
            semi_target
            & (~true_dark_contour)
            & (dist_dark <= 2.5)
            & (dist_dark < dist_fill - 1e-3)
            & (
                (a_clean < 35.0)
                | ((a_clean < 80.0) & (signed_dL_sf < -15.0))
            )
        )

        dark_mismatch_guard = (
            (~use_dark_ref)
            & (lab_rf[..., 0] < 145.0)
            & (signed_dL_sf > 45.0)
            & (
                ((a_clean >= 50.0) & (lab_s[..., 0] >= 135.0) & (pma_viol <= 4.0))
                | ((a_clean >= 85.0) & (lab_s[..., 0] >= 180.0))
            )
        )

        sharp_op_edge = anc_is_op & (dist_trans <= 3.8) & (dist_fill <= 3.8) & (dist_pure <= 6.5)

        watercolor_hue_keep = np.where(
            (~sharp_op_edge) & (a_clean >= 90.0) & (pma_viol <= 3.0),
            np.clip((14.0 - dab_sf) / 5.0, 0.0, 1.0),
            1.0,
        )

        w_low_a = np.clip((90.0 - a_clean) / 50.0, 0.0, 1.0)
        w_viol = np.where(
            (pma_viol > 6.0) | ((pma_viol > 1.5) & (dab_sf > 3.5) & (watercolor_hue_keep > 0.3)),
            np.clip((pma_viol - 1.0) / 5.0, 0.0, 1.0),
            0.0,
        )
        w_oog_hi = np.where(has_local_anc, np.clip((oog_hi - 5.0) / 14.0, 0.0, 1.0) * watercolor_hue_keep, 0.0)
        w_oog_lo = np.where(has_local_anc, np.clip((oog_lo - 6.0) / 14.0, 0.0, 1.0) * watercolor_hue_keep, 0.0)
        w_dark_speckle = np.where(
            sharp_op_edge & (signed_dL_sf < -4.0),
            np.clip((-signed_dL_sf - 3.0) / 7.0, 0.0, 1.0),
            np.where(
                (~sharp_op_edge) & (signed_dL_sf < -12.0),
                np.clip((-signed_dL_sf - 10.0) / 16.0, 0.0, 1.0) * watercolor_hue_keep,
                0.0,
            ),
        )
        w_bright_spike = np.where(
            sharp_op_edge & (signed_dL_sf > 4.5) & (signed_dL_sf <= 45.0),
            np.clip((signed_dL_sf - 3.5) / 7.5, 0.0, 1.0),
            0.0,
        )
        w_feather_floor = np.where(sharp_op_edge & broad_mixed_blk, 0.78, 0.45)
        w_feather = np.where(
            anc_is_op & (dist_trans <= 5.5),
            np.clip((245.0 - a_clean) / 60.0, w_feather_floor, 1.0) * watercolor_hue_keep,
            0.0,
        )
        w_chroma_spike = np.where(
            (soft_mixed_blk | (sharp_op_edge & broad_mixed_blk)) & (dab_sf > 2.5),
            np.clip((dab_sf - 2.0) / 5.0, 0.0, 1.0) * watercolor_hue_keep,
            0.0,
        )

        w_fill = np.maximum.reduce([
            w_low_a, w_viol, w_oog_hi, w_oog_lo,
            w_dark_speckle, w_bright_spike, w_feather, w_chroma_spike
        ])
        w_fill = np.where(
            semi_target & (~true_dark_contour) & (~use_dark_ref) & (~dark_mismatch_guard) & fill_path_ok & (dist_fill <= 6.5),
            w_fill,
            0.0,
        )

        w_dark = np.where(
            use_dark_ref,
            np.clip((80.0 - a_clean) / 45.0, 0.60, 1.0),
            0.0,
        )

        semi_repaired = int(np.sum((w_fill > 0.05) | (w_dark > 0.05)))
        dark_speckles_crushed = int(np.sum(semi_target & (~true_dark_contour) & (~use_dark_ref) & (signed_dL_sf < -6.0) & (w_fill > 0.2)))

        straight_out = straight * (1.0 - w_fill[..., None]) + ref_fill * w_fill[..., None]
        if np.any(w_dark > 0.01):
            straight_out = np.where(
                (w_dark > 0.01)[..., None],
                straight * (1.0 - w_dark[..., None]) + ref_dark * w_dark[..., None],
                straight_out,
            )

        w_lineart_ab = np.where(
            semi_target & true_dark_contour & soft_mixed_blk & (dab_sf > 10.0),
            np.clip((dab_sf - 9.0) / 14.0, 0.0, 0.65),
            0.0,
        )
        if np.any(w_lineart_ab > 0.01):
            lab_la = lab_s.copy()
            lab_la[..., 1] = lab_s[..., 1] * (1.0 - w_lineart_ab) + lab_rf[..., 1] * w_lineart_ab
            lab_la[..., 2] = lab_s[..., 2] * (1.0 - w_lineart_ab) + lab_rf[..., 2] * w_lineart_ab
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
        'dark_lineart_protected_px': int(np.sum(true_dark_contour)),
        'color_trim_protected_px': int(np.sum(true_color_trim)),
        'untouched_pure_interior_pct': round(100.0 * float(np.sum(pure_interior)) / max(1, int(np.sum(a >= 240))), 2),
        'lace_veil_interior_preserved_px': int(np.sum((a_clean >= 20) & (a_clean < 242) & (~semi_target))),
    }


clean_etc2_spine_pma_v4 = clean_etc2_spine_pma_v3


def collect_spine_targets(spine_root: str, doll_filter: str = None, include_submodels: bool = True):
    targets = []
    for doll in sorted(os.listdir(spine_root)):
        if doll_filter and doll != doll_filter:
            continue
        dp = os.path.join(spine_root, doll)
        if not os.path.isdir(dp):
            continue
        for skin in sorted(os.listdir(dp)):
            sp = os.path.join(dp, skin)
            if not os.path.isdir(sp):
                continue
            for f in sorted(os.listdir(sp)):
                if f.lower().endswith(('.png', '.webp')):
                    targets.append((os.path.join(sp, f), 'main'))
            if include_submodels:
                sub_root = os.path.join(sp, 'submodels')
                if os.path.isdir(sub_root):
                    for sub in sorted(os.listdir(sub_root)):
                        sub_low = sub.lower()
                        if sub_low.startswith(('fx_', 'bg_static', 'fg_static', 'bg_mid')):
                            continue
                        sub_dir = os.path.join(sub_root, sub)
                        if not os.path.isdir(sub_dir):
                            continue
                        for f in sorted(os.listdir(sub_dir)):
                            if f.lower().endswith(('.png', '.webp')):
                                targets.append((os.path.join(sub_dir, f), f'sub:{sub}'))
    return targets


def load_protect_manifest(mask_dir: str) -> dict:
    res = {}
    if not mask_dir:
        return res
    tsv = os.path.join(mask_dir, 'manifest.tsv')
    if not os.path.isfile(tsv):
        return res
    with open(tsv, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.rstrip('\r\n').split('\t')
            if len(parts) >= 2 and os.path.isfile(parts[1]):
                res[os.path.normcase(os.path.abspath(parts[0]))] = parts[1]
    return res


def process_one(task):
    tex_path, cat, spine_root, backup_dir, from_backup, dry_run, mask_path = task
    rel = os.path.relpath(tex_path, spine_root)
    ext = os.path.splitext(tex_path)[1].lower()
    bk_path = os.path.join(backup_dir, rel) if backup_dir else ''
    read_path = bk_path if (from_backup and bk_path and os.path.isfile(bk_path)) else tex_path
    orig_bytes = os.path.getsize(read_path)
    try:
        src = np.array(Image.open(read_path).convert('RGBA'))
        det = detect_pma_etc2_atlas(src)
        if not det['needs_clean']:
            reason = 'straight_or_glow' if det['is_straight_or_glow'] else 'already_clean'
            return {
                'rel': rel, 'cat': cat, 'status': 'skipped', 'reason': reason,
                'size_before': orig_bytes, 'size_after': os.path.getsize(tex_path), 'detect': det,
            }

        pmask = None
        if mask_path and os.path.isfile(mask_path):
            m = np.array(Image.open(mask_path).convert('L'))
            if m.shape == src.shape[:2]:
                pmask = m > 0

        if dry_run:
            return {
                'rel': rel, 'cat': cat, 'status': 'would_clean',
                'size_before': orig_bytes, 'size_after': orig_bytes, 'detect': det,
            }

        out, st = clean_etc2_spine_pma_v3(src, protect_mask=pmask)

        # Idempotent backup (never overwrite existing original backup)
        if bk_path and not os.path.exists(bk_path):
            os.makedirs(os.path.dirname(bk_path), exist_ok=True)
            shutil.copy2(tex_path, bk_path)

        tmp_path = tex_path + '.v3tmp' + ext
        out_im = Image.fromarray(out, 'RGBA')
        if ext == '.webp':
            out_im.save(tmp_path, 'WEBP', lossless=True, exact=True, quality=100, method=6)
            rt = np.array(Image.open(tmp_path).convert('RGBA'))
            if not np.array_equal(out, rt):
                os.remove(tmp_path)
                raise RuntimeError('Lossless WebP exact=True round-trip mismatch!')
        else:
            out_im.save(tmp_path, 'PNG', optimize=True)
            rt = np.array(Image.open(tmp_path).convert('RGBA'))
            if not np.array_equal(out, rt):
                os.remove(tmp_path)
                raise RuntimeError('PNG round-trip mismatch!')

        os.replace(tmp_path, tex_path)
        new_bytes = os.path.getsize(tex_path)
        return {
            'rel': rel, 'cat': cat, 'status': 'cleaned',
            'used_backup_src': (read_path == bk_path),
            'size_before': orig_bytes, 'size_after': new_bytes,
            'detect': det, 'stats': st,
        }
    except Exception as e:
        return {
            'rel': rel, 'cat': cat, 'status': 'error', 'error': str(e),
            'size_before': orig_bytes, 'size_after': orig_bytes,
        }


def main():
    ap = argparse.ArgumentParser(description='SoulTide Spine ETC2 Edge Artifact Cleaner V4.4')
    ap.add_argument('--root', default=r'E:\A灵魂潮汐\Live2D与Spine模型\spine', help='Spine models root directory')
    ap.add_argument('--doll', default=None, help='Only process one doll folder name')
    ap.add_argument('--backup-dir', default=r'E:\A灵魂潮汐\备份\spine_etc2_before_clean', help='Idempotent backup directory (empty to disable)')
    ap.add_argument('--from-backup', action='store_true', help='Re-process cleanly from original files in --backup-dir when present')
    ap.add_argument('--mask-dir', default='', help='Optional directory containing Additive/Screen protect masks manifest.tsv')
    ap.add_argument('--no-submodels', action='store_true', help='Skip Spine submodels (bj_*, bg_*)')
    ap.add_argument('--workers', type=int, default=8, help='Parallel worker processes')
    ap.add_argument('--dry-run', action='store_true', help='Scan and report without modifying files')
    ap.add_argument('--report', default=r'E:\A灵魂潮汐\Live2D与Spine模型\工具脚本\spine_etc2_clean_report.json', help='JSON report output path')
    args = ap.parse_args()

    t_start = time.time()
    targets = collect_spine_targets(args.root, args.doll, include_submodels=(not args.no_submodels))
    mask_map = load_protect_manifest(args.mask_dir)
    tasks = [
        (p, cat, args.root, args.backup_dir, args.from_backup, args.dry_run, mask_map.get(os.path.normcase(os.path.abspath(p))))
        for p, cat in targets
    ]
    print(f'V4.4 Discovered {len(tasks)} Spine atlas textures (workers={args.workers}, from_backup={args.from_backup}, dry_run={args.dry_run})...', flush=True)

    results = []
    done = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for res in ex.map(process_one, tasks):
            results.append(res)
            done += 1
            if done % 25 == 0 or done == len(tasks) or res['status'] == 'error':
                print(f'  [{done:3d}/{len(tasks)}] {res["status"]:11s} {res["rel"]}', flush=True)

    cleaned = [r for r in results if r['status'] == 'cleaned']
    would = [r for r in results if r['status'] == 'would_clean']
    skipped_clean = [r for r in results if r['status'] == 'skipped' and r.get('reason') == 'already_clean']
    skipped_straight = [r for r in results if r['status'] == 'skipped' and r.get('reason') == 'straight_or_glow']
    errors = [r for r in results if r['status'] == 'error']

    summary = {
        'version': 'V4.4',
        'elapsed_s': round(time.time() - t_start, 2),
        'total_scanned': len(results),
        'cleaned': len(cleaned),
        'used_backup_src': sum(1 for r in cleaned if r.get('used_backup_src')),
        'would_clean': len(would),
        'skipped_already_clean': len(skipped_clean),
        'skipped_straight_or_glow': len(skipped_straight),
        'errors': len(errors),
        'total_orig_a0_rgb_fixed': sum(r['stats']['orig_a0_rgb'] for r in cleaned),
        'total_orig_rgb_gt_a_fixed': sum(r['stats']['orig_rgb_gt_a'] for r in cleaned),
        'total_new_a0_rgb': sum(r['stats']['new_a0_rgb'] for r in cleaned),
        'total_new_rgb_gt_a': sum(r['stats']['new_rgb_gt_a'] for r in cleaned),
        'total_speckles_killed_px': sum(r['stats']['speckles_killed_px'] for r in cleaned),
        'total_rim_repaired_px': sum(r['stats']['rim_repaired_px'] for r in cleaned),
        'total_semi_repaired_px': sum(r['stats']['semi_repaired_px'] for r in cleaned),
        'total_dark_speckles_crushed_px': sum(r['stats']['dark_speckles_crushed_px'] for r in cleaned),
        'total_dark_lineart_protected_px': sum(r['stats']['dark_lineart_protected_px'] for r in cleaned),
        'total_color_trim_protected_px': sum(r['stats']['color_trim_protected_px'] for r in cleaned),
        'total_bytes_before': sum(r['size_before'] for r in cleaned),
        'total_bytes_after': sum(r['size_after'] for r in cleaned),
        'backup_dir': args.backup_dir,
    }
    print('\n=== SUMMARY (V4.4) ===', flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if errors:
        print('\nERRORS:', flush=True)
        for r in errors:
            print(f'  {r["rel"]}: {r.get("error")}', flush=True)

    if args.report:
        os.makedirs(os.path.dirname(args.report), exist_ok=True)
        with open(args.report, 'w', encoding='utf-8') as f:
            json.dump({'summary': summary, 'results': results}, f, ensure_ascii=False, indent=2)
        print(f'Report saved: {args.report}', flush=True)


if __name__ == '__main__':
    main()
