import json
import math
import struct
from pathlib import Path
from PIL import Image, ImageDraw

out_dir = Path(r".\_scratch\hitbox_check")

print("=== 1. Exact 2D Deformer Evaluation for Live2D Aurora.moc3 ===", flush=True)
mb = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", mb, 64)
cnt_info = struct.unpack_from("<16I", mb, ptrs[0])
n_def, n_warp, n_rot, n_draw = cnt_info[1], cnt_info[2], cnt_info[3], cnt_info[4]
n_art_kf, n_pos_f, n_uv_f = cnt_info[9], cnt_info[10], cnt_info[15]

def_ids = [mb[ptrs[11]+i*64 : ptrs[11]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_def)]
def_types = struct.unpack_from(f"<{n_def}i", mb, ptrs[17])       # 0=Warp, 1=Rot
def_spec_idx = struct.unpack_from(f"<{n_def}i", mb, ptrs[18])    # index into Warp or Rot table
def_parents = struct.unpack_from(f"<{n_def}i", mb, ptrs[16])

# Rotation Deformer tables (n_rot = 334): sec[25..32]
# Check exact meaning of sec[26..29] first just to be safe:
rot_kf_beg = struct.unpack_from(f"<{n_rot}i", mb, ptrs[26])
rot_x = struct.unpack_from("<1088f", mb, ptrs[63])
rot_y = struct.unpack_from("<1088f", mb, ptrs[64])
rot_ang = struct.unpack_from("<1088f", mb, ptrs[66])
rot_sx = struct.unpack_from("<1088f", mb, ptrs[65])  # 1.0 scale!

# Warp Deformer tables (n_warp = 228): sec[20]=kf_beg, sec[22]=pt_count, sec[23]=cols, sec[24]=rows
warp_kf_beg = struct.unpack_from(f"<{n_warp}i", mb, ptrs[20])
warp_cols = struct.unpack_from(f"<{n_warp}i", mb, ptrs[23])
warp_rows = struct.unpack_from(f"<{n_warp}i", mb, ptrs[24])
warp_pos_off = struct.unpack_from("<1056I", mb, ptrs[60])
all_pos_f = struct.unpack_from(f"<{n_pos_f}f", mb, ptrs[71])

draw_ids = [mb[ptrs[33]+i*64 : ptrs[33]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_draw)]
draw_kf_beg = struct.unpack_from(f"<{n_draw}I", mb, ptrs[35])
draw_parent = struct.unpack_from(f"<{n_draw}i", mb, ptrs[40])
v_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[43])
v_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[44])
idx_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[45])
idx_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[46])
kf_pos_idx = struct.unpack_from(f"<{n_art_kf}I", mb, ptrs[70])
uv_f = struct.unpack_from(f"<{n_uv_f}f", mb, ptrs[78])
tri_idxs = struct.unpack_from(f"<{len(mb[ptrs[79]:ptrs[80]])//2}H", mb, ptrs[79])

# Check def_spec_idx vs n_warp / n_rot
print("Sample warp spec idx:", [(i, def_ids[i], def_spec_idx[i], def_parents[i]) for i in range(n_def) if def_types[i] == 0][:5])
# Note: in .moc3 Cubism 3/4 WarpDeformer evaluates a Bezier patch on (rows+1) x (cols+1) grid!
# Let's check exact grid ordering using drawables whose parent is WarpDeformer!
def bernstein(n, i, t):
    return math.comb(n, i) * (t ** i) * ((1.0 - t) ** (n - i))

def eval_warp(widx, u, v):
    k0 = warp_kf_beg[widx]
    p0 = warp_pos_off[k0]
    cols = warp_cols[widx]  # degree in u -> (cols+1) points
    rows = warp_rows[widx]  # degree in v -> (rows+1) points
    u = max(-0.2, min(1.2, u))
    v = max(-0.2, min(1.2, v))
    sx = sy = 0.0
    # Grid in Cubism .moc3 is row-major (r in 0..rows, c in 0..cols) or col-major
    for r in range(rows + 1):
        br = bernstein(rows, r, v)
        for c in range(cols + 1):
            bc = bernstein(cols, c, u)
            idx = p0 + 2 * (r * (cols + 1) + c)
            sx += bc * br * all_pos_f[idx]
            sy += bc * br * all_pos_f[idx + 1]
    return sx, sy

def eval_rot(ridx, x, y):
    k0 = rot_kf_beg[ridx]
    ox, oy, ang, sc = rot_x[k0], rot_y[k0], rot_ang[k0], rot_sx[k0]
    rad = math.radians(ang)
    return ox + (x * math.cos(rad) - y * math.sin(rad)) * sc, oy + (x * math.sin(rad) + y * math.cos(rad)) * sc

def transform_pt(x, y, def_idx):
    while 0 <= def_idx < n_def:
        dt = def_types[def_idx]
        si = def_spec_idx[def_idx]
        if dt == 0:
            x, y = eval_warp(si, x, y)
        elif dt == 1:
            x, y = eval_rot(si, x, y)
        def_idx = def_parents[def_idx]
    return x, y

l2d_tex = Image.open(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Textures\Aurora_texture_00.png").convert("RGBA")

# Verify DREFTouchBox* + Face + L_Foot* + R_Foot* + Ru1/Ru2 + Hands true 2D positions!
eval_boxes = {}
for i, dnm in enumerate(draw_ids):
    vc = v_cnt[i]
    if vc == 0: continue
    p0 = kf_pos_idx[draw_kf_beg[i]]
    dp = draw_parent[i]
    # Transform all vertices! (fast: skip tiny/ignored for full render? Wait 21544 verts total, only ~0.3s!)
    wpts = [transform_pt(all_pos_f[p0 + 2*k], all_pos_f[p0 + 2*k + 1], dp) for k in range(vc)]
    xs = [p[0] for p in wpts]; ys = [p[1] for p in wpts]
    u0 = v_off[i] // 2
    d_uvs = [(uv_f[2*(u0+k)], uv_f[2*(u0+k)+1]) for k in range(vc)]
    # Check skin & alpha
    tot_a = 0; max_a = 0; skin = 0; vis = 0
    for u, v in d_uvs[::max(1, vc//6)]:
        px = max(0, min(l2d_tex.width-1, int(u*l2d_tex.width)))
        py = max(0, min(l2d_tex.height-1, int((1.0-v)*l2d_tex.height)))
        r, g, b, al = l2d_tex.getpixel((px, py))
        max_a = max(max_a, al)
        if al > 40:
            vis += 1
            if r > 180 and g > 130 and b > 100 and r > g > b - 10 and (r - b) > 15: skin += 1
    eval_boxes[dnm] = {
        "idx": i, "id": dnm, "pts": wpts, "uvs": d_uvs,
        "min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys),
        "cx": (min(xs)+max(xs))/2, "cy": (min(ys)+max(ys))/2,
        "w": max(xs)-min(xs), "h": max(ys)-min(ys),
        "alpha": max_a, "skin": (skin / vis) if vis else 0.0,
    }

gx0 = min(b["min_x"] for b in eval_boxes.values()); gx1 = max(b["max_x"] for b in eval_boxes.values())
gy0 = min(b["min_y"] for b in eval_boxes.values()); gy1 = max(b["max_y"] for b in eval_boxes.values())
print(f"Live2D Full Character Bounds: x=[{gx0:.1f},{gx1:.1f}] y=[{gy0:.1f},{gy1:.1f}]")
fb = eval_boxes["Face"]
print(f"Face center=({fb['cx']:.1f},{fb['cy']:.1f}) size=({fb['w']:.1f}x{fb['h']:.1f})")
for kw in ("DREFTouchBox", "L_Foot", "R_Foot", "Ru", "Body", "L_hand", "Rhand_B", "H_qianfa5", "H_Rhand_A18", "H_Lhand_A13", "X_jingjiA10"):
    for nm, b in sorted(eval_boxes.items()):
        if kw.lower() in nm.lower() and not any(s in nm.lower() for s in ("yy","bs","hua")):
            print(f"  {nm:20s}: cx={b['cx']:7.1f} cy={b['cy']:7.1f} size=({b['w']:5.1f}x{b['h']:5.1f}) skin={b['skin']:.2f} a={b['alpha']}")

# Find ALL drawables located near Face vs Chest vs Hands vs Legs vs Feet!
# Note whether +Y is UP or DOWN by comparing Face Y vs gy0/gy1:
y_down = fb["cy"] < (gy0 + gy1) / 2
print("Coordinate orientation: y_down =", y_down)

# Render full textured Live2D Aurora!
W, H = 1000, 1200
img = Image.new("RGBA", (W, H), (26, 28, 36, 255))
dr = ImageDraw.Draw(img)
sc = min((W - 80) / max(1, gx1 - gx0), (H - 80) / max(1, gy1 - gy0))
def to_px(x, y):
    px = W/2 + (x - (gx0+gx1)/2) * sc
    py = H/2 + ((y - (gy0+gy1)/2)*sc if y_down else -(y - (gy0+gy1)/2)*sc)
    return px, py

# Skip background/wing giant items or draw all visible drawables:
for b in eval_boxes.values():
    if b["alpha"] < 20: continue
    i = b["idx"]; io0 = idx_off[i]; ic = idx_cnt[i]; pts = b["pts"]; d_uvs = b["uvs"]
    for k in range(0, ic - 2, 3):
        a, c1, c2 = tri_idxs[io0+k], tri_idxs[io0+k+1], tri_idxs[io0+k+2]
        u = (d_uvs[a][0]+d_uvs[c1][0]+d_uvs[c2][0])/3.0
        v = (d_uvs[a][1]+d_uvs[c1][1]+d_uvs[c2][1])/3.0
        tx = max(0, min(l2d_tex.width-1, int(u*l2d_tex.width)))
        ty = max(0, min(l2d_tex.height-1, int((1.0-v)*l2d_tex.height)))
        r, g, bl, al = l2d_tex.getpixel((tx, ty))
        if al > 30:
            poly = [to_px(pts[vi][0], pts[vi][1]) for vi in (a, c1, c2)]
            dr.polygon(poly, fill=(r, g, bl))

# Draw labeled boxes for key Drawables + skin leg/foot drawables!
highlights = [
    ("DREFTouchBoxHead", "#ff3333"), ("DREFTouchBoxBra", "#ff55dd"),
    ("DREFTouchBoxHandL", "#33ff55"), ("DREFTouchBoxHandR", "#33ddff"),
    ("DREFTouchBoxHip", "#ffaa00"), ("L_Foot1", "#aaaaaa"), ("R_Foot2", "#ffff33"),
    ("R_Foot3", "#ff8844"), ("Ru1", "#ff88cc"), ("Body2", "#ffffff"),
]
# Find visible skin drawables below Hip/Belly (`min_y` or `max_y` near feet!)
print("\nLower body / feet visible skin Drawables (skin > 0.35):")
for b in sorted(eval_boxes.values(), key=lambda x: -x["cy"] if y_down else x["cy"]):
    if b["skin"] > 0.35 and b["w"] * b["h"] > 5000 and ((b["cy"] > fb["cy"] + 700) if y_down else (b["cy"] < fb["cy"] - 700)):
        print(f"  LOWER SKIN: {b['id']:20s} cx={b['cx']:7.1f} cy={b['cy']:7.1f} size=({b['w']:5.1f}x{b['h']:5.1f}) skin={b['skin']:.2f}")
        highlights.append((b["id"], "#00ffcc"))

for dname, col in highlights:
    if dname in eval_boxes:
        b = eval_boxes[dname]
        p0 = to_px(b["min_x"], b["min_y"] if y_down else b["max_y"])
        p1 = to_px(b["max_x"], b["max_y"] if y_down else b["min_y"])
        dr.rectangle([p0[0], p0[1], p1[0], p1[1]], outline=col, width=3)
        dr.text((p0[0]+3, p0[1]+3), dname, fill=col)

img.convert("RGB").resize((W//2, H//2), Image.Resampling.LANCZOS).save(out_dir / "live2d_full_2d_map_50pct.jpg", "JPEG", quality=50)
print("Saved live2d_full_2d_map_50pct.jpg", flush=True)
