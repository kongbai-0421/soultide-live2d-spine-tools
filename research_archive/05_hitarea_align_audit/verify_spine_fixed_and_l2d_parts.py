import json
import math
import struct
from pathlib import Path
from PIL import Image, ImageDraw

out_dir = Path(r".\_scratch\hitbox_check")

print("=== 1. Spine idle_marry Pose WITH Proper 'noRotationOrReflection' Transform ===", flush=True)
skel = json.loads(Path(r"E:\A灵魂潮汐\备份\spine\欧若拉\童话心绘\有背景\SoulDress_Aurora_04.skel.json").read_text(encoding="utf-8"))
anim = skel["animations"].get("idle_marry", {})
bone_anim = anim.get("bones", {})
def kf_val(arr, keys, default):
    if not arr: return default
    return tuple(arr[0].get(k, default[i]) for i, k in enumerate(keys))

# Spine world matrix `[a, b, x; c, d, y]` per bone!
bone_mat = {}
for b in skel["bones"]:
    name = b["name"]; par = b.get("parent")
    lx = b.get("x", 0.0); ly = b.get("y", 0.0); lrot = b.get("rotation", 0.0)
    lsx = b.get("scaleX", 1.0); lsy = b.get("scaleY", 1.0)
    tmode = b.get("transform", "normal")
    if name in bone_anim:
        ba = bone_anim[name]
        if ba.get("translate"): dx, dy = kf_val(ba["translate"], ("x","y"), (0.0,0.0)); lx += dx; ly += dy
        if ba.get("rotate"): drot, = kf_val(ba["rotate"], ("angle",), (0.0,)); lrot += drot
        if ba.get("scale"): dsx, dsy = kf_val(ba["scale"], ("x","y"), (1.0,1.0)); lsx *= dsx; lsy *= dsy

    rad = math.radians(lrot)
    ca, sa = math.cos(rad), math.sin(rad)
    la, lb, lc, ld = ca * lsx, -sa * lsy, sa * lsx, ca * lsy

    if par and par in bone_mat:
        pa, pb, px, pc, pd, py = bone_mat[par]
        wx = pa * lx + pb * ly + px
        wy = pc * lx + pd * ly + py
        if tmode == "noRotationOrReflection":
            # Inherit scale magnitude without parent rotation/reflection!
            s = math.hypot(pa, pc)
            a, b2, c, d = la * s, lb * s, lc * s, ld * s
        else:
            a = pa * la + pb * lc
            b2 = pa * lb + pb * ld
            c = pc * la + pd * lc
            d = pc * lb + pd * ld
        bone_mat[name] = (a, b2, wx, c, d, wy)
    else:
        bone_mat[name] = (la, lb, lx, lc, ld, ly)

def xform(bname, lx, ly):
    a, b, x, c, d, y = bone_mat[bname]
    return a * lx + b * ly + x, c * lx + d * ly + y

atlas_txt = Path(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\SoulDress_Aurora_04.atlas.txt").read_text(encoding="utf-8")
sp_png = Image.open(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\SoulDress_Aurora_04.png").convert("RGBA")
regions = {}
lines = atlas_txt.splitlines()
i = 0
while i < len(lines):
    ln = lines[i]
    if ln and not ln.startswith((" ", "\t")) and not ln.lower().endswith(".png") and ":" not in ln:
        rname = ln.strip(); props = {}
        while i + 1 < len(lines) and lines[i+1].startswith((" ", "\t")):
            i += 1; k, v = lines[i].strip().split(":", 1); props[k.strip()] = v.strip()
        regions[rname] = props
    i += 1

def region_uv_to_px(props, u, v):
    ax, ay = [int(z) for z in props["xy"].split(",")]
    aw, ah = [int(z) for z in props["size"].split(",")]
    rot = props.get("rotate", "false")
    if rot == "true": px, py = ax + v * ah, ay + aw - u * aw
    elif rot == "180": px, py = ax + (1.0 - u) * aw, ay + (1.0 - v) * ah
    elif rot == "270": px, py = ax + (1.0 - v) * ah, ay + u * aw
    else: px, py = ax + u * aw, ay + v * ah
    return max(0, min(sp_png.width-1, int(px))), max(0, min(sp_png.height-1, int(py)))

skin_att = skel["skins"][0]["attachments"]
bones_list = skel["bones"]
SW, SH = 1200, 1000
sp_img = Image.new("RGBA", (SW, SH), (24, 26, 36, 255))
sdr = ImageDraw.Draw(sp_img)
def s2p(x, y):
    return (SW / 2 - 120 + x * 0.55, SH - 120 - y * 0.55)

for sl in skel["slots"]:
    sname = sl["name"]; bname = sl["bone"]; att_name = sl.get("attachment")
    if not att_name or sname not in skin_att or att_name not in skin_att[sname]: continue
    att = skin_att[sname][att_name]
    rkey = att.get("path", att_name)
    if rkey not in regions: continue
    props = regions[rkey]
    if att.get("type", "region") == "mesh":
        uvs = att["uvs"]; n_v = len(uvs) // 2; v_raw = att["vertices"]; wpts = []
        if len(v_raw) == 2 * n_v:
            wpts = [xform(bname, v_raw[2*k], v_raw[2*k+1]) for k in range(n_v)]
        else:
            p = 0
            while p < len(v_raw):
                cnt = int(v_raw[p]); p += 1; sx = sy = 0.0
                for _ in range(cnt):
                    bi = int(v_raw[p]); bx = v_raw[p+1]; by = v_raw[p+2]; w = v_raw[p+3]; p += 4
                    tx, ty = xform(bones_list[bi]["name"], bx, by)
                    sx += tx * w; sy += ty * w
                wpts.append((sx, sy))
        tris = att["triangles"]
        for k in range(0, len(tris), 3):
            a, b, c = tris[k], tris[k+1], tris[k+2]
            if a >= len(wpts) or b >= len(wpts) or c >= len(wpts): continue
            u = (uvs[2*a]+uvs[2*b]+uvs[2*c])/3.0; v = (uvs[2*a+1]+uvs[2*b+1]+uvs[2*c+1])/3.0
            tx, ty = region_uv_to_px(props, u, v)
            r, g, bl, al = sp_png.getpixel((tx, ty))
            if al > 30:
                sdr.polygon([s2p(wpts[vi][0], wpts[vi][1]) for vi in (a, b, c)], fill=(r, g, bl))

hit_cfg = json.loads(Path(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\.config.json").read_text(encoding="utf-8"))
print("Spine FIXED world HitAreas in idle_marry:")
for ha in hit_cfg["hit_areas"]:
    bid = ha["id"]
    _, _, wx, _, _, wy = bone_mat[bid]
    hx = wx + ha.get("center_x", 0.0)*100.0; hy = wy + ha.get("center_y", 0.0)*100.0
    hw = ha.get("width", 1.0)*100.0; hh = ha.get("height", 1.0)*100.0
    p0 = s2p(hx - hw/2, hy + hh/2); p1 = s2p(hx + hw/2, hy - hh/2)
    sdr.rectangle([p0[0], p0[1], p1[0], p1[1]], outline="#00ff66", width=3)
    cxp, cyp = s2p(wx, wy)
    sdr.ellipse([cxp-4, cyp-4, cxp+4, cyp+4], fill="#ff3333")
    sdr.text((p0[0]+3, p0[1]+3), f"{ha['name']}({bid})", fill="#ffff00")
    print(f"  {ha['name']}({bid}): bone=({wx:6.1f},{wy:6.1f}) box_center=({hx:6.1f},{hy:6.1f}) size=({hw:.0f}x{hh:.0f})")

for bn in ("79", "83", "84", "85", "86", "87", "88", "47", "113", "321"):
    _, _, wx, _, _, wy = bone_mat[bn]
    print(f"  bone {bn}: ({wx:6.1f},{wy:6.1f})")

sp_img.convert("RGB").resize((SW//2, SH//2), Image.Resampling.LANCZOS).save(out_dir / "spine_fixed_50pct.jpg", "JPEG", quality=50)
print("Saved spine_fixed_50pct.jpg", flush=True)

print("\n=== 2. Check Live2D UV legs near (200..600, 1400..2048) & (1800..2048, 800..1300) ===", flush=True)
mb = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", mb, 64)
cnt_info = struct.unpack_from("<16I", mb, ptrs[0])
n_draw, n_uv_f = cnt_info[4], cnt_info[15]
n_parts = cnt_info[0]
part_ids = [mb[ptrs[3]+i*64 : ptrs[3]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_parts)]
draw_ids = [mb[ptrs[33]+i*64 : ptrs[33]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_draw)]
draw_part = struct.unpack_from(f"<{n_draw}i", mb, ptrs[39])
v_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[43])
v_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[44])
uv_f = struct.unpack_from(f"<{n_uv_f}f", mb, ptrs[78])

# Remember in QQ20261118-152921.png, Aurora has her left leg/foot (`R_Foot2`? Look at the flower garland on her leg!) and right leg (`?`)!
# Let's print ALL drawables in Parts 'Body', 'L_Foot', 'R_Foot', 'Lhand_A', 'Lhand_B', 'Rhand_A', 'Rhand_B', 'H_Rhand_A4_Skinning', 'H_Lhand_A5_Skinning', 'Ru', 'H_qunzi', 'Tou', 'H_qianfa'!
for pnm_target in ("R_Foot", "L_Foot", "Ru", "Tou", "Lhand_A", "Lhand_B", "Rhand_A", "Rhand_B", "Body"):
    items = []
    for i in range(n_draw):
        pnm = part_ids[draw_part[i]] if 0 <= draw_part[i] < n_parts else "NONE"
        if pnm == pnm_target:
            u0 = v_off[i]//2; vc = v_cnt[i]
            us = [uv_f[2*(u0+k)] for k in range(vc)]; vs = [uv_f[2*(u0+k)+1] for k in range(vc)]
            x0, x1 = int(min(us)*2048), int(max(us)*2048)
            y0, y1 = int((1-max(vs))*2048), int((1-min(vs))*2048)
            items.append(f"{draw_ids[i]}({x0},{y0}-{x1},{y1})")
    print(f"  Part {pnm_target}: {items}")
