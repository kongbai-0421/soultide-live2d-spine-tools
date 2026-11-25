"""Comprehensive 182-package Live2D HitAreas spatial, anatomical, and structural auditor."""

from __future__ import annotations

import ctypes
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

LIVE2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
CORE_DLL = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Plugins\x86_64\Live2DCubismCore.dll"
)
OUT_JSON = Path(r"E:\A灵魂潮汐\tools\live2d_touch_audit_raw.json")


def init_cubism_core():
    core = ctypes.CDLL(str(CORE_DLL))
    core.csmReviveMocInPlace.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    core.csmReviveMocInPlace.restype = ctypes.c_void_p
    core.csmGetSizeofModel.argtypes = [ctypes.c_void_p]
    core.csmGetSizeofModel.restype = ctypes.c_uint32
    core.csmInitializeModelInPlace.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    core.csmInitializeModelInPlace.restype = ctypes.c_void_p
    core.csmUpdateModel.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableCount.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableCount.restype = ctypes.c_int32
    core.csmGetDrawableIds.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableIds.restype = ctypes.POINTER(ctypes.c_char_p)
    core.csmGetDrawableTextureIndices.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableTextureIndices.restype = ctypes.POINTER(ctypes.c_int32)
    core.csmGetDrawableVertexCounts.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableVertexCounts.restype = ctypes.POINTER(ctypes.c_int32)
    core.csmGetDrawableVertexPositions.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableVertexPositions.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    core.csmGetDrawableVertexUvs.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableVertexUvs.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    core.csmGetDrawableIndexCounts.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableIndexCounts.restype = ctypes.POINTER(ctypes.c_int32)
    core.csmGetDrawableIndices.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableIndices.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_uint16))
    core.csmGetDrawableOpacities.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableOpacities.restype = ctypes.POINTER(ctypes.c_float)
    # Cubism Core v6 (0x06000001+) removed csmGetDrawableRenderOrders in favor of csmGetRenderOrders.
    # Prefer the legacy export when present and fall back to csmGetRenderOrders otherwise.
    if hasattr(core, "csmGetDrawableRenderOrders"):
        core.csmGetDrawableRenderOrders.argtypes = [ctypes.c_void_p]
        core.csmGetDrawableRenderOrders.restype = ctypes.POINTER(ctypes.c_int32)
    elif hasattr(core, "csmGetRenderOrders"):
        core.csmGetRenderOrders.argtypes = [ctypes.c_void_p]
        core.csmGetRenderOrders.restype = ctypes.POINTER(ctypes.c_int32)
        core.csmGetDrawableRenderOrders = core.csmGetRenderOrders
    else:
        raise AttributeError("Neither 'csmGetDrawableRenderOrders' nor 'csmGetRenderOrders' found in Live2DCubismCore.dll")
    core.csmGetParameterCount.argtypes = [ctypes.c_void_p]
    core.csmGetParameterCount.restype = ctypes.c_int32
    core.csmGetParameterIds.argtypes = [ctypes.c_void_p]
    core.csmGetParameterIds.restype = ctypes.POINTER(ctypes.c_char_p)
    core.csmGetParameterValues.argtypes = [ctypes.c_void_p]
    core.csmGetParameterValues.restype = ctypes.POINTER(ctypes.c_float)
    return core


def get_drawable_render_orders(core, model):
    """Return per-drawable render orders across Cubism Core <= v5 and v6+."""
    fn = getattr(core, "csmGetDrawableRenderOrders", None) or core.csmGetRenderOrders
    return fn(model)


def inspect_package(core, pkg_dir: Path) -> dict[str, Any]:
    rel = f"{pkg_dir.parent.name}/{pkg_dir.name}"
    cfg_path = pkg_dir / ".model3.json"
    en_path = pkg_dir / "model_en.model3.json"
    ja_path = pkg_dir / "model_ja.model3.json"

    d0 = json.loads(cfg_path.read_text(encoding="utf-8"))
    den = json.loads(en_path.read_text(encoding="utf-8")) if en_path.is_file() else None
    dja = json.loads(ja_path.read_text(encoding="utf-8")) if ja_path.is_file() else None

    fr = d0["FileReferences"]
    moc_bytes = (pkg_dir / fr["Moc"]).read_bytes()
    textures = fr.get("Textures") or []
    tex_alphas = [np.array(Image.open(pkg_dir / t).convert("RGBA"))[..., 3] for t in textures]

    moc_buf = ctypes.create_string_buffer(len(moc_bytes) + 64)
    moc_addr = (ctypes.addressof(moc_buf) + 63) & ~63
    ctypes.memmove(moc_addr, moc_bytes, len(moc_bytes))
    moc = core.csmReviveMocInPlace(moc_addr, len(moc_bytes))
    msize = core.csmGetSizeofModel(moc)
    mod_buf = ctypes.create_string_buffer(msize + 64)
    mod_addr = (ctypes.addressof(mod_buf) + 63) & ~63
    model = core.csmInitializeModelInPlace(moc, mod_addr, msize)
    core.csmUpdateModel(model)

    dcnt = core.csmGetDrawableCount(model)
    ids_ptr = core.csmGetDrawableIds(model)
    tidx_ptr = core.csmGetDrawableTextureIndices(model)
    vcnt_ptr = core.csmGetDrawableVertexCounts(model)
    vpos_ptr = core.csmGetDrawableVertexPositions(model)
    uvs_ptr = core.csmGetDrawableVertexUvs(model)
    icnt_ptr = core.csmGetDrawableIndexCounts(model)
    idxs_ptr = core.csmGetDrawableIndices(model)
    op_ptr = core.csmGetDrawableOpacities(model)
    ro_ptr = get_drawable_render_orders(core, model)

    drawables: dict[str, dict[str, Any]] = {}
    vis_xs = []
    vis_ys = []

    for i in range(dcnt):
        did = ids_ptr[i].decode("utf-8", "ignore")
        vc = int(vcnt_ptr[i])
        ic = int(icnt_ptr[i])
        ti = int(tidx_ptr[i])
        op = float(op_ptr[i])
        ro = int(ro_ptr[i])

        if vc > 0:
            pos = np.ctypeslib.as_array(vpos_ptr[i], shape=(vc, 2))
            uv = np.ctypeslib.as_array(uvs_ptr[i], shape=(vc, 2))
            x0, y0 = float(pos[:, 0].min()), float(pos[:, 1].min())
            x1, y1 = float(pos[:, 0].max()), float(pos[:, 1].max())
            u0, v0 = float(uv[:, 0].min()), float(uv[:, 1].min())
            u1, v1 = float(uv[:, 0].max()), float(uv[:, 1].max())

            # Compute fraction of non-transparent triangles
            alpha_hit = 0.0
            if ic >= 3 and 0 <= ti < len(tex_alphas):
                alp = tex_alphas[ti]
                th, tw = alp.shape
                idx = np.ctypeslib.as_array(idxs_ptr[i], shape=(ic // 3, 3))
                c_uv = uv[idx].mean(axis=1)
                xs = np.clip((c_uv[:, 0] * tw).astype(int), 0, tw - 1)
                ys = np.clip(((1.0 - c_uv[:, 1]) * th).astype(int), 0, th - 1)
                vals = alp[ys, xs]
                alpha_hit = float((vals > 8).mean()) if len(vals) > 0 else 0.0

                if op > 0.05 and alpha_hit > 0.05 and not did.startswith(("DREFTouchBox", "HitArea")):
                    # Keep non-transparent triangle vertices for silhouette (exclude off-canvas stray drawables)
                    if abs(x0) <= 3.0 and abs(x1) <= 3.0 and abs(y0) <= 3.0 and abs(y1) <= 3.0:
                        non_trans_tris = idx[vals > 8]
                        if len(non_trans_tris) > 0:
                            used_verts = np.unique(non_trans_tris)
                            v_sub = pos[used_verts]
                            vis_xs.append(float(v_sub[:, 0].min()))
                            vis_xs.append(float(v_sub[:, 0].max()))
                            vis_ys.append(float(v_sub[:, 1].min()))
                            vis_ys.append(float(v_sub[:, 1].max()))

            drawables[did] = {
                "x0": round(x0, 4),
                "y0": round(y0, 4),
                "x1": round(x1, 4),
                "y1": round(y1, 4),
                "w": round(x1 - x0, 4),
                "h": round(y1 - y0, 4),
                "cx": round((x0 + x1) / 2.0, 4),
                "cy": round((y0 + y1) / 2.0, 4),
                "op": round(op, 4),
                "vc": vc,
                "ic": ic,
                "ti": ti,
                "ro": ro,
                "u0": round(u0, 4),
                "v0": round(v0, 4),
                "u1": round(u1, 4),
                "v1": round(v1, 4),
                "alpha_hit": round(alpha_hit, 4),
            }
        else:
            drawables[did] = {
                "x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0,
                "w": 0.0, "h": 0.0, "cx": 0.0, "cy": 0.0,
                "op": round(op, 4), "vc": 0, "ic": ic, "ti": ti, "ro": ro,
                "u0": 0.0, "v0": 0.0, "u1": 0.0, "v1": 0.0, "alpha_hit": 0.0,
            }

    if vis_xs and vis_ys:
        char_x0, char_x1 = min(vis_xs), max(vis_xs)
        char_y0, char_y1 = min(vis_ys), max(vis_ys)
    else:
        char_x0, char_x1, char_y0, char_y1 = -1.0, 1.0, -1.0, 1.0
    char_w = max(1e-4, char_x1 - char_x0)
    char_h = max(1e-4, char_y1 - char_y0)

    hit_areas = d0.get("HitAreas") or []
    mots = fr.get("Motions") or {}
    is_base = pkg_dir.name == "原皮" or pkg_dir.name.startswith("原皮_")

    flags: list[str] = []
    hit_details: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    for ha in hit_areas:
        name = ha.get("Name", "")
        hid = ha.get("Id", "")
        hmot = ha.get("Motion", "")

        if hid in seen_ids:
            flags.append(f"duplicate_id:{hid}")
        seen_ids.add(hid)
        if name in seen_names:
            flags.append(f"duplicate_name:{name}")
        seen_names.add(name)

        if not hid.startswith(("DREFTouchBox", "HitArea")):
            flags.append(f"non_dref:{name}={hid}")

        if hid not in drawables:
            flags.append(f"missing_drawable:{name}={hid}")
            hit_details.append({"Name": name, "Id": hid, "Motion": hmot, "missing": True})
            continue

        d = drawables[hid]
        if d["vc"] == 0 or d["ic"] < 3:
            flags.append(f"zero_verts:{name}={hid}(vc={d['vc']},ic={d['ic']})")
        if d["w"] < 0.05 or d["h"] < 0.05:
            flags.append(f"tiny_area:{name}={hid}(w={d['w']:.3f},h={d['h']:.3f})")
        if d["w"] > 0.45 or d["h"] > 0.45 or (d["w"] * d["h"]) > 0.35 * (char_w * char_h):
            flags.append(
                f"huge_area:{name}={hid}(w={d['w']:.3f}/{char_w:.3f},h={d['h']:.3f}/{char_h:.3f})"
            )
        # Check overlap with character silhouette
        ix0 = max(d["x0"], char_x0)
        iy0 = max(d["y0"], char_y0)
        ix1 = min(d["x1"], char_x1)
        iy1 = min(d["y1"], char_y1)
        if ix1 <= ix0 or iy1 <= iy0:
            flags.append(f"off_body_no_overlap:{name}={hid}")
        elif not (char_x0 - 0.1 * char_w <= d["cx"] <= char_x1 + 0.1 * char_w and char_y0 - 0.1 * char_h <= d["cy"] <= char_y1 + 0.1 * char_h):
            flags.append(f"off_body_center:{name}={hid}(cx={d['cx']:.3f},cy={d['cy']:.3f})")

        # Relative normalized coordinates inside char silhouette
        nx = (d["cx"] - char_x0) / char_w
        ny = (d["cy"] - char_y0) / char_h
        info = {
            "Name": name,
            "Id": hid,
            "Motion": hmot,
            "nx": round(nx, 3),
            "ny": round(ny, 3),
            **d,
        }
        hit_details.append(info)
        by_name[name] = info

    # Anatomical checks
    head = by_name.get("头")
    chest = by_name.get("胸")
    hip = by_name.get("臀部")
    hand_l = by_name.get("左手")
    hand_r = by_name.get("右手")
    torso = by_name.get("躯干")

    if head and chest and head["cy"] <= chest["cy"]:
        flags.append(f"anatomical:head_below_chest(head={head['cy']:.3f},chest={chest['cy']:.3f})")
    if head and head["ny"] < 0.50:
        flags.append(f"anatomical:head_low(ny={head['ny']:.3f})")
    if hip and chest and hip["cy"] >= chest["cy"]:
        flags.append(f"anatomical:hip_above_chest(hip={hip['cy']:.3f},chest={chest['cy']:.3f})")
    if hip and hip["ny"] > 0.65:
        flags.append(f"anatomical:hip_high(ny={hip['ny']:.3f})")

    if head:
        for hname, hbox in (("左手", hand_l), ("右手", hand_r)):
            if hbox:
                dist = math.hypot(hbox["cx"] - head["cx"], hbox["cy"] - head["cy"])
                if dist < 0.10 * char_h or (
                    head["x0"] <= hbox["cx"] <= head["x1"] and head["y0"] <= hbox["cy"] <= head["y1"]
                ):
                    flags.append(f"anatomical:{hname}_stacked_on_head(dist={dist:.3f})")

    if hand_l and hand_r:
        dist_lr = math.hypot(hand_l["cx"] - hand_r["cx"], hand_l["cy"] - hand_r["cy"])
        if dist_lr < 0.05 * char_w and abs(hand_l["cy"] - hand_r["cy"]) < 0.05 * char_h:
            flags.append(f"anatomical:hands_stacked(dist={dist_lr:.3f})")

    # Motion & audio checks
    bound_mots = {h.get("Motion") for h in hit_areas}
    for tg in ("Tap头", "Tap手", "Tap胸", "Tap臀部", "Tap躯干"):
        if tg in mots:
            if not mots[tg]:
                flags.append(f"empty_tap_group:{tg}")
            if tg not in bound_mots:
                flags.append(f"unbound_tap_group:{tg}")
            if not is_base:
                for it in mots[tg]:
                    if "_touch_" in (it.get("Sound") or "").lower():
                        flags.append(f"base_audio_leak:{tg}:{it.get('Sound')}")
                        break

    for ha in hit_areas:
        hm = ha.get("Motion", "")
        if not mots.get(hm):
            flags.append(f"hit_target_empty_or_missing:{ha.get('Name')}->{hm}")

    # Sibling language config sync
    for lname, ld in (("model_en.model3.json", den), ("model_ja.model3.json", dja)):
        if ld is None:
            flags.append(f"missing_lang:{lname}")
        else:
            if ld.get("HitAreas") != hit_areas:
                flags.append(f"lang_hitareas_mismatch:{lname}")
            lmots = (ld.get("FileReferences") or {}).get("Motions") or {}
            for tg in ("Tap头", "Tap手", "Tap胸", "Tap臀部", "Tap躯干"):
                if len(lmots.get(tg, [])) != len(mots.get(tg, [])):
                    flags.append(f"lang_tap_len_mismatch:{lname}:{tg}")

    # Also list all DREFTouchBox* / Body* drawables in moc3
    dref_in_moc = {
        k: v for k, v in drawables.items()
        if k.startswith("DREFTouchBox") or k in ("Body", "Body2")
    }

    return {
        "rel": rel,
        "is_base": is_base,
        "char_bbox": {
            "x0": round(char_x0, 4), "y0": round(char_y0, 4),
            "x1": round(char_x1, 4), "y1": round(char_y1, 4),
            "w": round(char_w, 4), "h": round(char_h, 4),
        },
        "hit_areas": hit_details,
        "dref_in_moc": list(dref_in_moc.keys()),
        "flags": flags,
    }


def main():
    core = init_cubism_core()
    pkgs = sorted(p.parent for p in LIVE2D_ROOT.glob("*/*/.model3.json"))
    results = []
    flagged = []
    for p in pkgs:
        res = inspect_package(core, p)
        results.append(res)
        if res["flags"]:
            flagged.append(res)

    summary = {
        "total": len(results),
        "flagged_count": len(flagged),
        "flagged_rels": [r["rel"] for r in flagged],
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Total: {len(results)}, Flagged: {len(flagged)}")
    for r in flagged:
        print(f"  [FLAG] {r['rel']}: {r['flags']}")


if __name__ == "__main__":
    main()
