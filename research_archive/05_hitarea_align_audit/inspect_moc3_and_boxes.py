import json
import math
import struct
from pathlib import Path
from PIL import Image, ImageDraw

out_dir = Path(r".\_scratch\hitbox_check")
out_dir.mkdir(parents=True, exist_ok=True)

print("=== 1. Live2D .moc3 Keyform0 Rendering ===", flush=True)
mb = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", mb, 64)
cnt_info = struct.unpack_from("<16I", mb, ptrs[0])
n_draw = cnt_info[4]       # 429
n_uv_f = cnt_info[15]      # 43088
n_art_kf = cnt_info[9]     # 1478
n_pos_f = cnt_info[10]     # 301680

# CanvasInfo at sec[1]
ppu, ox, oy, cw, ch = struct.unpack_from("<5f", mb, ptrs[1])
print(f"CanvasInfo: PPU={ppu}, origin=({ox},{oy}), size=({cw},{ch})", flush=True)

draw_ids = [mb[ptrs[33]+i*64 : ptrs[33]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_draw)]
kf_begin = struct.unpack_from(f"<{n_draw}I", mb, ptrs[35])   # ArtMesh keyform begin index into [sec[69..70]]
kf_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[36])     # ArtMesh keyform count
v_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[43])      # vertex count
v_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[44])      # uv float offset (2 * vertex_index)
idx_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[45])    # triangle index offset
idx_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[46])    # triangle index count
kf_pos_idx = struct.unpack_from(f"<{n_art_kf}I", mb, ptrs[70])
all_pos_f = struct.unpack_from(f"<{n_pos_f}f", mb, ptrs[71])
uv_f = struct.unpack_from(f"<{n_uv_f}f", mb, ptrs[78])
tri_idxs = struct.unpack_from(f"<{len(mb[ptrs[79]:ptrs[80]])//2}H", mb, ptrs[79])

print("Check Drawable 0..3:", [(draw_ids[i], kf_begin[i], kf_cnt[i], v_cnt[i], kf_pos_idx[kf_begin[i]]) for i in range(4)])

# Extract 2D bounds for each Drawable using keyform[0]!
l2d_tex = Image.open(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Textures\Aurora_texture_00.png").convert("RGBA")
boxes = []
draw_polys = []
for i in range(n_draw):
    vc = v_cnt[i]
    if vc == 0:
        continue
    k0 = kf_begin[i]
    pstart = kf_pos_idx[k0]
    pts = [(all_pos_f[pstart + 2*k], all_pos_f[pstart + 2*k + 1]) for k in range(vc)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    u0 = v_off[i] // 2
    d_uvs = [(uv_f[2*(u0+k)], uv_f[2*(u0+k)+1]) for k in range(vc)]
    # Check texture non-transparent ratio for this drawable
    alpha_max = 0
    for u, v in d_uvs[::max(1, vc//5)]:
        px = max(0, min(l2d_tex.width - 1, int(u * l2d_tex.width)))
        py = max(0, min(l2d_tex.height - 1, int((1.0 - v) * l2d_tex.height)))
        alpha_max = max(alpha_max, l2d_tex.getpixel((px, py))[3])
    boxes.append({
        "idx": i, "id": draw_ids[i],
        "min_x": min(xs), "max_x": max(xs),
        "min_y": min(ys), "max_y": max(ys),
        "cx": (min(xs)+max(xs))/2, "cy": (min(ys)+max(ys))/2,
        "w": max(xs)-min(xs), "h": max(ys)-min(ys),
        "alpha": alpha_max, "pts": pts, "uvs": d_uvs,
    })

gx0 = min(b["min_x"] for b in boxes); gx1 = max(b["max_x"] for b in boxes)
gy0 = min(b["min_y"] for b in boxes); gy1 = max(b["max_y"] for b in boxes)
print(f"Live2D Canvas Bounds: x=[{gx0:.1f},{gx1:.1f}] y=[{gy0:.1f},{gy1:.1f}]", flush=True)

print("\nDREFTouchBox* exact positions:")
for b in boxes:
    if "touchbox" in b["id"].lower() or "dref" in b["id"].lower():
        print(f"  {b['id']:22s} center=({b['cx']:6.1f},{b['cy']:6.1f}) size=({b['w']:5.1f}x{b['h']:5.1f}) x=[{b['min_x']:.1f},{b['max_x']:.1f}] y=[{b['min_y']:.1f},{b['max_y']:.1f}]")

print("\nALL L_Foot / R_Foot / Ru / Body / Hand / Hair exact positions:")
for b in boxes:
    low = b["id"].lower()
    if any(k in low for k in ("foot", "ru1", "ru2", "body", "qianfa5", "l_hand", "lhand_a2", "rhand_a3", "rhand_b2", "bra", "tui")):
        print(f"  {b['id']:22s} center=({b['cx']:6.1f},{b['cy']:6.1f}) size=({b['w']:5.1f}x{b['h']:5.1f}) alpha={b['alpha']}")

print("\nVisible Drawables near TRUE FEET (highest Y in Live2D canvas since Y-down or check head vs feet!):", flush=True)
# Find Head/Face Y vs Foot Y so we know whether Y points UP or DOWN!
face_b = next((b for b in boxes if b["id"] == "Face"), None)
print("Face box:", face_b["id"], face_b["cx"], face_b["cy"], "size", face_b["w"], face_b["h"])
# Sort by distance from center bottom/top depending on Face cy vs gy0/gy1!
if face_b["cy"] < (gy0 + gy1) / 2:
    # Y points DOWN (head is lower Y, feet are higher Y!)
    cands = sorted([b for b in boxes if b["max_y"] > face_b["cy"] + 800 and b["alpha"] > 20], key=lambda x: -x["max_y"])
else:
    # Y points UP (feet are lower Y!)
    cands = sorted([b for b in boxes if b["min_y"] < face_b["cy"] - 800 and b["alpha"] > 20], key=lambda x: x["min_y"])
print("Lowest (true feet/ankles) 20 visible drawables:")
for b in cands[:20]:
    print(f"  {b['id']:24s} center=({b['cx']:6.1f},{b['cy']:6.1f}) y=[{b['min_y']:6.1f},{b['max_y']:6.1f}] size=({b['w']:5.1f}x{b['h']:5.1f})")

# Render Live2D full model triangles & labeled HitAreas
W, H = 1000, 1200
img = Image.new("RGBA", (W, H), (26, 28, 36, 255))
dr = ImageDraw.Draw(img)
sc = min((W - 80) / max(1, gx1 - gx0), (H - 80) / max(1, gy1 - gy0))
y_down = (face_b["cy"] < (gy0 + gy1) / 2)
def to_px(x, y):
    px = W/2 + (x - (gx0+gx1)/2) * sc
    py = H/2 + ((y - (gy0+gy1)/2) * sc if y_down else -(y - (gy0+gy1)/2) * sc)
    return px, py

# Render triangles sorted by simple drawable order or opacity
for b in boxes:
    i = b["idx"]
    io0 = idx_off[i]
    ic = idx_cnt[i]
    pts = b["pts"]
    d_uvs = b["uvs"]
    for k in range(0, ic - 2, 3):
        a, c1, c2 = tri_idxs[io0+k], tri_idxs[io0+k+1], tri_idxs[io0+k+2]
        u = (d_uvs[a][0] + d_uvs[c1][0] + d_uvs[c2][0]) / 3.0
        v = (d_uvs[a][1] + d_uvs[c1][1] + d_uvs[c2][1]) / 3.0
        tx = max(0, min(l2d_tex.width - 1, int(u * l2d_tex.width)))
        ty = max(0, min(l2d_tex.height - 1, int((1.0 - v) * l2d_tex.height)))
        r, g, bl, al = l2d_tex.getpixel((tx, ty))
        if al > 30:
            poly = [to_px(pts[vi][0], pts[vi][1]) for vi in (a, c1, c2)]
            dr.polygon(poly, fill=(r, g, bl))

# Overlay DREFTouchBox* + L_Foot1 + candidate feet!
by_name = {b["id"]: b for b in boxes}
check_names = [
    ("DREFTouchBoxHead", "#ff3333"), ("DREFTouchBoxBra", "#ff44dd"),
    ("DREFTouchBoxHandL", "#44ff44"), ("DREFTouchBoxHandR", "#44ddff"),
    ("DREFTouchBoxHip", "#ffaa00"), ("L_Foot1", "#ffffff"), ("R_Foot1", "#ffffff"),
    ("L_Foot2", "#ffff44"), ("R_Foot2", "#ffff44"),
]
for dname, col in check_names:
    if dname in by_name:
        b = by_name[dname]
        p0 = to_px(b["min_x"], b["min_y"] if y_down else b["max_y"])
        p1 = to_px(b["max_x"], b["max_y"] if y_down else b["min_y"])
        dr.rectangle([p0[0], p0[1], p1[0], p1[1]], outline=col, width=3)
        dr.text((p0[0] + 3, p0[1] + 3), dname, fill=col)

img.convert("RGB").resize((W // 2, H // 2), Image.Resampling.LANCZOS).save(out_dir / "live2d_canvas_hitboxes_50pct.jpg", "JPEG", quality=50)
print("Saved live2d_canvas_hitboxes_50pct.jpg", flush=True)
