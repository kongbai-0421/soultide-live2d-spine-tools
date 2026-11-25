import sys, json
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

OUT_DIR = Path(r".\_scratch\unity_fx_proj")
TEX_DIR = OUT_DIR / "Assets" / "Textures"
TEX_DIR.mkdir(parents=True, exist_ok=True)

# 1. Index Materials, Textures, Shaders across 14_effect + 03_prefabs + 05_images + 15_shader
cab_idx = {}
name_tex = {}
for sub_folder in ("14_effect", "03_prefabs", "05_images", "15_shader"):
    for ab in sorted((CDN_ROOT / sub_folder).rglob("*.ab")):
        env = load_ab(ab)
        for sf_name, sf in env.files.items():
            files = getattr(sf, "files", None)
            subs = files.items() if isinstance(files, dict) else [(sf_name, sf)]
            for k, sub in subs:
                if k.startswith("CAB-") and hasattr(sub, "objects"):
                    for pid, obj in sub.objects.items():
                        if obj.type.name in ("Material", "Texture2D", "Shader"):
                            cab_idx[(k, pid)] = (ab, sub, obj)
                        if obj.type.name == "Texture2D":
                            nm = obj.peek_name()
                            if nm:
                                name_tex.setdefault(nm.lower(), obj)

def resolve_ext(sf, fid, pid):
    if pid == 0:
        return None
    if fid == 0:
        return sf.objects.get(pid)
    if 1 <= fid <= len(sf.externals):
        cab = Path(sf.externals[fid - 1].path).name
        hit = cab_idx.get((cab, pid))
        if hit:
            return hit[2]
    return None

def dump_curve(curve_dict):
    if not isinstance(curve_dict, dict):
        return {"scalar": float(curve_dict or 0)}
    mc = curve_dict.get("maxCurve", {})
    keys = [
        {"t": float(k.get("time", 0)), "v": float(k.get("value", 0)),
         "in": float(k.get("inSlope", 0)), "out": float(k.get("outSlope", 0))}
        for k in mc.get("m_Curve", [])
    ]
    return {
        "mode": int(curve_dict.get("minMaxState", 0)),
        "scalar": float(curve_dict.get("scalar", 1.0)),
        "minScalar": float(curve_dict.get("minScalar", 1.0)),
        "keys": keys,
    }

def dump_gradient(grad_dict):
    if not isinstance(grad_dict, dict):
        return {}
    mg = grad_dict.get("maxGradient", {})
    # Unity serializes color keys as key0..key7 + ctime0..7 + atime0..7 + m_NumColorKeys/m_NumAlphaKeys
    nck = int(mg.get("m_NumColorKeys", 0))
    nak = int(mg.get("m_NumAlphaKeys", 0))
    ckeys = []
    for i in range(nck):
        col = mg.get(f"key{i}", {"r": 1, "g": 1, "b": 1, "a": 1})
        t = float(mg.get(f"ctime{i}", 0)) / 65535.0
        ckeys.append({"t": t, "r": col["r"], "g": col["g"], "b": col["b"]})
    akeys = []
    for i in range(nak):
        col = mg.get(f"key{i}", {"a": 1})
        t = float(mg.get(f"atime{i}", 0)) / 65535.0
        akeys.append({"t": t, "a": col["a"]})
    return {"mode": int(grad_dict.get("minMaxState", 0)), "ckeys": ckeys, "akeys": akeys}

saved_texs = set()

def extract_fx_tree(rel, tid, clip_name, root_offset_ui=(0.0, 0.0)):
    env = load_ab(CDN_ROOT / rel)
    obj_by_id = {o.path_id: o for o in env.objects}
    rid = tid if isinstance(tid, int) else {k.lower(): v.path_id for k, v in env.container.items()}[tid.lower()]

    nodes = []
    def walk(gid, parent_pos=(0.0, 0.0, 0.0), parent_scale=(1.0, 1.0, 1.0)):
        go = obj_by_id[gid].read()
        if not go.m_IsActive:
            return
        rt = None
        lx = ly = lz = 0.0
        sx = sy = sz = 1.0
        rot_euler = (0.0, 0.0, 0.0)
        for c in go.m_Component:
            co = obj_by_id.get(c.component.path_id)
            if co and co.type.name in ("RectTransform", "Transform"):
                rt = co.read()
                pos = rt.m_LocalPosition
                sc = rt.m_LocalScale
                lx, ly, lz = pos.x, pos.y, pos.z
                if co.type.name == "RectTransform":
                    ap = rt.m_AnchoredPosition
                    # Ignore root Aurora_S4_Background offset (-55) if root itself
                    if go.m_Name not in ("Aurora_S4_Background",):
                        lx, ly = ap.x, ap.y
                sx, sy, sz = sc.x, sc.y, sc.z

        wx = parent_pos[0] + lx * parent_scale[0]
        wy = parent_pos[1] + ly * parent_scale[1]
        wz = parent_pos[2] + lz * parent_scale[2]
        wsx = parent_scale[0] * sx
        wsy = parent_scale[1] * sy
        wsz = parent_scale[2] * sz

        # Extract ParticleSystem if rate/burst enabled
        for c in go.m_Component:
            co = obj_by_id.get(c.component.path_id)
            if co and co.type.name == "ParticleSystem":
                tt = co.read_typetree()
                em = tt.get("EmissionModule", {})
                if em.get("enabled"):
                    init = tt.get("InitialModule", {})
                    sh = tt.get("ShapeModule", {})
                    col_m = tt.get("ColorModule", {})
                    sz_m = tt.get("SizeModule", {})
                    vel_m = tt.get("VelocityModule", {})
                    rot_m = tt.get("RotationModule", {})
                    uv_m = tt.get("UVModule", {})

                    # Resolve Material & Texture
                    mat_name = ""
                    tex_name = ""
                    is_add = True
                    tint = {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}
                    sort_order = 0
                    render_mode = 0
                    for c2 in go.m_Component:
                        co2 = obj_by_id.get(c2.component.path_id)
                        if co2 and co2.type.name == "ParticleSystemRenderer":
                            psr = co2.read_typetree()
                            sort_order = int(psr.get("m_SortingOrder", 0))
                            render_mode = int(psr.get("m_RenderMode", 0))
                            mrefs = psr.get("m_Materials", [])
                            if mrefs:
                                mobj = resolve_ext(co2.assets_file, mrefs[0].get("m_FileID", 0), mrefs[0].get("m_PathID", 0))
                                if mobj:
                                    mtt = mobj.read_typetree()
                                    mat_name = mtt.get("m_Name", "")
                                    sp = mtt.get("m_SavedProperties", {})
                                    flts = {fk: fv for fk, fv in sp.get("m_Floats", [])}
                                    cols = {ck: cv for ck, cv in sp.get("m_Colors", [])}
                                    tint = cols.get("_TintColor", cols.get("_Color", tint))
                                    shd_obj = resolve_ext(mobj.assets_file, mtt.get("m_Shader", {}).get("m_FileID", 0), mtt.get("m_Shader", {}).get("m_PathID", 0))
                                    shd_name = shd_obj.peek_name() if shd_obj else ""
                                    dst_b = flts.get("_DstBlend", -1.0)
                                    # SoulTide FX shaders with (1.0, 0.0) or _DstBlend==1 or 'add' are Additive, EXCEPT beike/xianglian alpha sprites!
                                    if "blend" in shd_name.lower() or "alpha" in shd_name.lower() or dst_b == 10.0:
                                        is_add = False
                                    if "beike_01" in mat_name.lower() or "beike_02" in mat_name.lower() or "smoke" in go.m_Name.lower():
                                        is_add = False
                                    # Find texture in m_TexEnvs (_MainTex or _Texture)
                                    for tk, tv in sp.get("m_TexEnvs", []):
                                        if tk in ("_MainTex", "_Texture"):
                                            tref = tv.get("m_Texture", {})
                                            tobj = resolve_ext(mobj.assets_file, tref.get("m_FileID", 0), tref.get("m_PathID", 0))
                                            if tobj and tobj.type.name == "Texture2D":
                                                tex_name = tobj.peek_name()
                                                if tex_name not in saved_texs:
                                                    im = tobj.read().image.convert("RGBA")
                                                    im.save(TEX_DIR / f"{tex_name}.png", "PNG")
                                                    saved_texs.add(tex_name)
                                                break
                    nodes.append({
                        "name": go.m_Name,
                        "world_pos": [wx + root_offset_ui[0], wy + root_offset_ui[1], wz],
                        "world_scale": [wsx, wsy, wsz],
                        "duration": float(tt.get("lengthInSec", 2.0)),
                        "looping": bool(tt.get("looping", False)),
                        "scalingMode": int(tt.get("scalingMode", 0)),
                        "lifetime": dump_curve(init.get("startLifetime", {})),
                        "speed": dump_curve(init.get("startSpeed", {})),
                        "size": dump_curve(init.get("startSize", {})),
                        "rotation": dump_curve(init.get("startRotation", {})),
                        "startColor": init.get("startColor", {}).get("maxColor", {"r": 1, "g": 1, "b": 1, "a": 1}),
                        "startColorMin": init.get("startColor", {}).get("minColor", {"r": 1, "g": 1, "b": 1, "a": 1}),
                        "startColorMode": int(init.get("startColor", {}).get("minMaxState", 0)),
                        "maxParticles": int(init.get("maxNumParticles", 50)),
                        "rate": float(em.get("rateOverTime", {}).get("scalar", 0.0)),
                        "bursts": [
                            {"time": float(b.get("time", 0)), "count": float(b.get("countCurve", {}).get("scalar", 0)), "minCount": float(b.get("countCurve", {}).get("minScalar", 0)), "mode": int(b.get("countCurve", {}).get("minMaxState", 0))}
                            for b in em.get("m_Bursts", [])
                        ],
                        "shapeEnabled": bool(sh.get("enabled", False)),
                        "shapeType": int(sh.get("type", 0)),
                        "shapeRadius": float(sh.get("radius", {}).get("value", 1.0)),
                        "shapeBox": [float(sh.get("m_Scale", {}).get("x", 1)), float(sh.get("m_Scale", {}).get("y", 1)), float(sh.get("m_Scale", {}).get("z", 1))],
                        "colOverLife": dump_gradient(col_m.get("gradient", {})) if col_m.get("enabled") else None,
                        "sizeOverLife": dump_curve(sz_m.get("curve", {})) if sz_m.get("enabled") else None,
                        "velX": float(vel_m.get("x", {}).get("scalar", 0.0)) if vel_m.get("enabled") else 0.0,
                        "velY": float(vel_m.get("y", {}).get("scalar", 0.0)) if vel_m.get("enabled") else 0.0,
                        "rotOverLife": float(rot_m.get("curve", {}).get("scalar", 0.0)) if rot_m.get("enabled") else 0.0,
                        "uvTiles": [int(uv_m.get("tilesX", 1)), int(uv_m.get("tilesY", 1)), float(uv_m.get("cycles", 1.0))] if uv_m.get("enabled") else None,
                        "matName": mat_name,
                        "texName": tex_name,
                        "isAdditive": is_add,
                        "tint": tint,
                        "sortOrder": sort_order,
                        "renderMode": render_mode,
                    })

        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in obj_by_id:
                    walk(obj_by_id[ch.path_id].read().m_GameObject.path_id, (wx, wy, wz), (wsx, wsy, wsz))

    walk(rid)
    # Filter to only FX sub-nodes (not Image/Spine nodes without PS)
    return {"clip": clip_name, "nodes": nodes}

# Image_01 center is UI (0, +11.44); shift Y by -11.44 so canvas center = (0, 0) in 1768x1176!
specs = {
    "idle": extract_fx_tree("03_prefabs/ui.ab", 8268094511723853665, "idle", (0.0, -11.44)),
    "fx_9008135": extract_fx_tree("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_chat.prefab", "fx_9008135", (0.0, -11.44)),
    "fx_9008136": extract_fx_tree("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab", "fx_9008136", (0.0, -11.44)),
}
spec_path = OUT_DIR / "fx_spec.json"
spec_path.write_text(json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8")
print("Wrote", spec_path, "Textures extracted:", sorted(saved_texs))
for k, v in specs.items():
    print(f"  {k}: {len(v['nodes'])} particle systems -> {[n['name'] + ':' + n['texName'] + ('[ADD]' if n['isAdditive'] else '[ALPHA]') for n in v['nodes']]}")
