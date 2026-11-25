import json
import math
import struct
from pathlib import Path
from PIL import Image, ImageDraw

out_dir = Path(r".\_scratch\hitbox_check")

print("=== 1. Spine Exact Mesh Silhouette + Bone Map in idle_marry ===", flush=True)
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
    if rot == "true":
        # Spine 90 deg CCW rotated region
        px = ax + v * ah
        py = ay + aw - u * aw
    elif rot == "180":
        px = ax + (1.0 - u) * aw
        py = ay + (1.0 - v) * ah
    elif rot == "270":
        px = ax + (1.0 - v) * ah
        py = ay + u * aw
    else:
        px = ax + u * aw
        py = ay + v * ah
    return max(0, min(sp_png.width-1, int(px))), max(0, min(sp_png.height-1, int(py)))

def xform(bname, lx, ly):
    wx, wy, wrot, wsx, wsy = bone_world[bname]
    rad = math.radians(wrot)
    return (
        wx + lx * wsx * math.cos(rad) - ly * wsy * math.sin(rad),
        wy + lx * wsx * math.sin(rad) + ly * wsy * math.cos(rad),
    )

# Decode every weighted/non-weighted mesh attachment vertex into Spine world coordinates!
skin_att = skel["skins"][0]["attachments"]
bones_list = skel["bones"]
SW, SH = 1200, 1000
sp_img = Image.new("RGBA", (SW, SH), (24, 26, 36, 255))
sdr = ImageDraw.Draw(sp_img)
def s2p(x, y):
    return (SW / 2 - 150 + x * 0.55, SH - 120 - y * 0.55)

bone_boxes = {}  # bone_name -> list of world vertices
for sl in skel["slots"]:
    sname = sl["name"]; bname = sl["bone"]; att_name = sl.get("attachment")
    if not att_name or sname not in skin_att or att_name not in skin_att[sname]: continue
    att = skin_att[sname][att_name]
    rkey = att.get("path", att_name)
    if rkey not in regions: continue
    props = regions[rkey]
    atype = att.get("type", "region")
    if atype == "mesh":
        uvs = att["uvs"]
        n_v = len(uvs) // 2
        v_raw = att["vertices"]
        wpts = []
        if len(v_raw) == 2 * n_v:
            wpts = [xform(bname, v_raw[2*k], v_raw[2*k+1]) for k in range(n_v)]
        else:
            p = 0
            while p < len(v_raw):
                cnt = int(v_raw[p]); p += 1
                sx = sy = 0.0
                for _ in range(cnt):
                    bi = int(v_raw[p]); bx = v_raw[p+1]; by = v_raw[p+2]; w = v_raw[p+3]; p += 4
                    btarget = bones_list[bi]["name"]
                    tx, ty = xform(btarget, bx, by)
                    sx += tx * w; sy += ty * w
                wpts.append((sx, sy))
        tris = att["triangles"]
        # Draw textured triangles (Skip gigantic background/rose props if outside character radius? No, draw all!)
        for k in range(0, len(tris), 3):
            a, b, c = tris[k], tris[k+1], tris[k+2]
            if a >= len(wpts) or b >= len(wpts) or c >= len(wpts): continue
            u = (uvs[2*a] + uvs[2*b] + uvs[2*c]) / 3.0
            v = (uvs[2*a+1] + uvs[2*b+1] + uvs[2*c+1]) / 3.0
            tx, ty = region_uv_to_px(props, u, v)
            r, g, bl, al = sp_png.getpixel((tx, ty))
            if al > 30:
                poly = [s2p(wpts[vi][0], wpts[vi][1]) for vi in (a, b, c)]
                sdr.polygon(poly, fill=(r, g, bl))
        # Record character bone world points (rough check: skip distant flower ring)
        for pxy in wpts:
            bone_boxes.setdefault(bname, []).append(pxy)

# Print Spine numeric/named character bones near body (-200..+650, 200..1350)
print("\nKey Spine bones with mesh positions (x in [-300,700], y in [200,1350]):")
for bn in sorted(bone_world.keys()):
    wx, wy, _, _, _ = bone_world[bn]
    if -250 <= wx <= 700 and 250 <= wy <= 1350:
        pts = bone_boxes.get(bn, [])
        cx = sum(p[0] for p in pts)/len(pts) if pts else wx
        cy = sum(p[1] for p in pts)/len(pts) if pts else wy
        # Draw small dot & ID on character for visual picking!
        if bn.isdigit() or bn in ("47","113","321","83","84","87","88"):
            px, py = s2p(wx, wy)
            if bn in ("47","113","321","83","84","87","88","79","80","81","82","85","86","73","65","95","96","97"):
                print(f"  bone {bn:6s}: joint=({wx:6.1f},{wy:6.1f}) mesh_avg=({cx:6.1f},{cy:6.1f}) n_pts={len(pts)}")
                sdr.ellipse([px-4, py-4, px+4, py+4], fill="#ff3333")
                sdr.text((px+5, py-6), bn, fill="#00ffff")

# Draw existing Spine hit_areas on TRUE mesh silhouette
hit_cfg = json.loads(Path(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\.config.json").read_text(encoding="utf-8"))
for ha in hit_cfg["hit_areas"]:
    bid = ha["id"]
    wx, wy, _, _, _ = bone_world[bid]
    hx = wx + ha.get("center_x", 0.0)*100.0
    hy = wy + ha.get("center_y", 0.0)*100.0
    hw = ha.get("width", 1.0)*100.0; hh = ha.get("height", 1.0)*100.0
    p0 = s2p(hx - hw/2, hy + hh/2); p1 = s2p(hx + hw/2, hy - hh/2)
    sdr.rectangle([p0[0], p0[1], p1[0], p1[1]], outline="#00ff66", width=3)
    sdr.text((p0[0]+3, p0[1]+3), f"{ha['name']}({bid})", fill="#ffff00")

sp_img.convert("RGB").resize((SW//2, SH//2), Image.Resampling.LANCZOS).save(out_dir / "spine_true_mesh_50pct.jpg", "JPEG", quality=50)
print("Saved spine_true_mesh_50pct.jpg", flush=True)

print("\n=== 2. Evaluate Live2D .moc3 Rotation/Warp Deformer Bounds for Key Drawables ===", flush=True)
# Let's check exact WarpDeformer / RotationDeformer sections in Aurora.moc3!
mb = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", mb, 64)
cnt_info = struct.unpack_from("<16I", mb, ptrs[0])
# sec[11] = DeformerIDs? Let's print CountInfo[0..6]: parts=94, deformers=562, warps=228, rots=334, drawables=429!
n_def = cnt_info[1]
n_warp = cnt_info[2]
n_rot = cnt_info[3]
n_draw = cnt_info[4]
print(f"parts={cnt_info[0]} deformers={n_def} (warps={n_warp}, rots={n_rot}) drawables={n_draw}")
def_ids = [mb[ptrs[11]+i*64 : ptrs[11]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_def)]
def_types = struct.unpack_from(f"<{n_def}i", mb, ptrs[13])  # 0=Warp, 1=Rot
def_type_idx = struct.unpack_from(f"<{n_def}i", mb, ptrs[15])  # spec index! Wait check sec[14..18]!
def_parents = struct.unpack_from(f"<{n_def}i", mb, ptrs[16])
print("Deformer 0..5:", [(def_ids[i], def_types[i], def_type_idx[i], def_parents[i]) for i in range(6)])
# Find specific warp deformer keyforms & rotation deformer keyforms!
# Warp: sec[19..25] (len 228?), Rot: sec[25..32]? Wait earlier sec[19] size=960 -> 960/4=240 (>=228)!
# Rot: sec[25..32] size=1344 -> 1344/4=336 (>=334)!
rot_kf_beg = struct.unpack_from(f"<{n_rot}i", mb, ptrs[26])
rot_kf_cnt = struct.unpack_from(f"<{n_rot}i", mb, ptrs[27])
# Check sec[63..68] for RotationDeformer keyform data (count = n_rot_kf ~ 1088? Wait CountInfo[8]=1088 -> 1088*4=4352 = sec[62..68] size!!)
rot_x = struct.unpack_from("<1088f", mb, ptrs[63])
rot_y = struct.unpack_from("<1088f", mb, ptrs[64])
rot_ang = struct.unpack_from("<1088f", mb, ptrs[65])
rot_sx = struct.unpack_from("<1088f", mb, ptrs[68])
print("RotDeformer sample 0..4:", [(rot_x[rot_kf_beg[i]], rot_y[rot_kf_beg[i]], rot_ang[rot_kf_beg[i]], rot_sx[rot_kf_beg[i]]) for i in range(5)])
# Check WarpDeformer: sec[19]=cols?, sec[20]=rows?, sec[21]=kf_beg?, sec[22]=kf_cnt? Wait sec[19..24] sizes were 960 bytes (=240 ints, for 228 warps!)
for s in range(19, 25):
    arr = struct.unpack_from("<6i", mb, ptrs[s])
    print(f"  warp sec[{s}]: {arr}")
# Check Warp keyform table: CountInfo[7]=1056 (*4=4224 = sec[60..61] size!)
warp_kf_beg = struct.unpack_from(f"<{n_warp}i", mb, ptrs[19])
# Wait earlier sec[19]=(121,120,123,120)?? Oh! Wait sec[20]=(0,3,6,9), sec[21]=(3,3,3,3) -> rows*cols or kf_beg/cnt! Wait sec[60]=(0, 80, 160, 240) (step 80 floats = 40 xy pairs = 4x5 or 5x4 grid?!)!
# Let's check sec[20..24] & sec[60] (step 80 = 2*(cols+1)*(rows+1) or 2*40? Wait (4+1)*(7+1)=40!! Look sec[22]=36,81,81,36? Wait (5+1)*(5+1)=36! (8+1)*(8+1)=81! sec[23]=5,8,8,5 -> cols=5, rows=5 => (cols+1)*(rows+1)=36? No 5+1=6*6=36, 8+1=9*9=81!! So cols+1=6, rows+1=6 or similar -> let's print sec[19..24] for i=0..3!)
