import json
import math
import struct
from pathlib import Path
from PIL import Image, ImageDraw

out_dir = Path(r".\_scratch\hitbox_check")

print("=== 1. Find ALL Large Skin Drawables in Aurora.moc3 UV + Check Exact Warp Grid Order ===", flush=True)
mb = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", mb, 64)
cnt_info = struct.unpack_from("<16I", mb, ptrs[0])
n_def, n_warp, n_rot, n_draw = cnt_info[1], cnt_info[2], cnt_info[3], cnt_info[4]
n_art_kf, n_pos_f, n_uv_f = cnt_info[9], cnt_info[10], cnt_info[15]
n_parts = cnt_info[0]
part_ids = [mb[ptrs[3]+i*64 : ptrs[3]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_parts)]
draw_ids = [mb[ptrs[33]+i*64 : ptrs[33]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_draw)]
draw_part = struct.unpack_from(f"<{n_draw}i", mb, ptrs[39])
v_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[43])
v_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[44])
uv_f = struct.unpack_from(f"<{n_uv_f}f", mb, ptrs[78])
tex = Image.open(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Textures\Aurora_texture_00.png").convert("RGBA")

# Find EVERY drawable covering the top-middle bare legs/ankles/hands/chest in Aurora_texture_00.png!
skin_limbs = []
for i, dnm in enumerate(draw_ids):
    vc = v_cnt[i]
    if vc == 0: continue
    u0 = v_off[i] // 2
    us = [uv_f[2*(u0+k)] for k in range(vc)]
    vs = [uv_f[2*(u0+k)+1] for k in range(vc)]
    x0, x1 = int(min(us)*2048), int(max(us)*2048)
    y0, y1 = int((1-max(vs))*2048), int((1-min(vs))*2048)
    pw, ph = x1-x0, y1-y0
    if max(pw, ph) < 70: continue
    crop = tex.crop((max(0,x0), max(0,y0), min(2048,x1), min(2048,y1)))
    # Check skin pixels strictly inside polygon bounding box (approx)
    pxs = list(crop.get_flattened_data())[::max(1, (crop.width*crop.height)//400)]
    tot = sum(1 for r,g,b,a in pxs if a > 40)
    sk = sum(1 for r,g,b,a in pxs if a > 40 and r > 200 and 155 < g < 225 and 130 < b < 205 and (r-b) > 25)
    ratio = sk / tot if tot else 0.0
    pnm = part_ids[draw_part[i]] if 0 <= draw_part[i] < n_parts else "NONE"
    if ratio > 0.25 or dnm in ("L_Foot1", "L_Foot2", "L_Foot3", "R_Foot1", "R_Foot2", "R_Foot3", "Ru1", "Ru2", "Body1", "Body2", "Face"):
        skin_limbs.append((ratio, pnm, dnm, x0, y0, x1, y1, crop))

skin_limbs.sort(key=lambda x: -x[0])
print(f"Big skin/body drawables ({len(skin_limbs)}):")
for ratio, pnm, dnm, x0, y0, x1, y1, _ in skin_limbs[:35]:
    print(f"  skin={ratio:.2f} Part={pnm:16s} Draw={dnm:20s} uv=({x0},{y0})-({x1},{y1}) ({x1-x0}x{y1-y0})")

# Save a huge legible 5-col contact sheet of top 30 items!
items = skin_limbs[:30]
cols = 5; cw, ch = 260, 260
rows = (len(items) + cols - 1) // cols
sh = Image.new("RGB", (cols*cw, rows*ch), (22, 24, 32))
dr = ImageDraw.Draw(sh)
for idx, (ratio, pnm, dnm, x0, y0, x1, y1, crop) in enumerate(items):
    r, c = divmod(idx, cols)
    th = crop.copy(); th.thumbnail((cw-20, ch-50), Image.Resampling.LANCZOS)
    bg = Image.new("RGBA", th.size, (36, 40, 52, 255)); bg.alpha_composite(th)
    sh.paste(bg.convert("RGB"), (c*cw+10, r*ch+44))
    dr.text((c*cw+8, r*ch+6), f"Part:{pnm[:15]}", fill=(100, 220, 255))
    dr.text((c*cw+8, r*ch+24), f"{dnm[:18]} s={ratio:.2f}", fill=(255, 240, 110))
sh.resize((sh.width//2, sh.height//2), Image.Resampling.LANCZOS).save(out_dir / "live2d_skin_limbs_50pct.jpg", "JPEG", quality=50)
print("Saved live2d_skin_limbs_50pct.jpg", flush=True)

print("\n=== 2. Check ALL Spine Bones in Aurora_04 leg/foot/hand/chest/head region ===", flush=True)
skel = json.loads(Path(r"E:\A灵魂潮汐\备份\spine\欧若拉\童话心绘\有背景\SoulDress_Aurora_04.skel.json").read_text(encoding="utf-8"))
anim = skel["animations"].get("idle_marry", {})
bone_anim = anim.get("bones", {})
def kf_val(arr, keys, default):
    if not arr: return default
    return tuple(arr[0].get(k, default[i]) for i, k in enumerate(keys))

bone_world = {}
for b in skel["bones"]:
    name = b["name"]; par = b.get("parent")
    lx = b.get("x", 0.0); ly = b.get("y", 0.0); lrot = b.get("rotation", 0.0)
    lsx = b.get("scaleX", 1.0); lsy = b.get("scaleY", 1.0)
    if name in bone_anim:
        ba = bone_anim[name]
        if ba.get("translate"): dx, dy = kf_val(ba["translate"], ("x","y"), (0.0,0.0)); lx += dx; ly += dy
        if ba.get("rotate"): drot, = kf_val(ba["rotate"], ("angle",), (0.0,)); lrot += drot
        if ba.get("scale"): dsx, dsy = kf_val(ba["scale"], ("x","y"), (1.0,1.0)); lsx *= dsx; lsy *= dsy
    if par and par in bone_world:
        px, py, prot, psx, psy = bone_world[par]
        rad = math.radians(prot)
        wx = px + (lx * psx * math.cos(rad) - ly * psy * math.sin(rad))
        wy = py + (lx * psx * math.sin(rad) + ly * psy * math.cos(rad))
        bone_world[name] = (wx, wy, prot + lrot, psx * lsx, psy * lsy)
    else:
        bone_world[name] = (lx, ly, lrot, lsx, lsy)

# Find which bones deform the bare legs/feet slots (78, 81, 82)
skin_att = skel["skins"][0]["attachments"]
bones_list = skel["bones"]
for sl in skel["slots"]:
    sname = sl["name"]
    if sname in ("78", "81", "82", "89", "47", "113", "321", "88", "84", "87", "83"):
        att_name = sl.get("attachment")
        att = skin_att.get(sname, {}).get(att_name, {}) if att_name else {}
        used_bones = {sl["bone"]}
        v_raw = att.get("vertices", [])
        n_v = len(att.get("uvs", [])) // 2
        if n_v and len(v_raw) > 2 * n_v:
            p = 0
            while p < len(v_raw):
                cnt = int(v_raw[p]); p += 1
                for _ in range(cnt):
                    bi = int(v_raw[p]); used_bones.add(bones_list[bi]["name"]); p += 4
        print(f"  Spine slot {sname:4s} (host={sl['bone']}): deforming bones={sorted(used_bones)}")
        for ub in sorted(used_bones):
            wx, wy, _, _, _ = bone_world[ub]
            print(f"    -> bone {ub:5s} idle_marry=({wx:6.1f}, {wy:6.1f})")
