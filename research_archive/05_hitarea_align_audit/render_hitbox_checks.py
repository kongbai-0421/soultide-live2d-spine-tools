import io
import json
import math
import re
import struct
from pathlib import Path
from PIL import Image, ImageDraw
import UnityPy

cdn = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")
out_dir = Path(r".\_scratch\hitbox_check")
out_dir.mkdir(parents=True, exist_ok=True)

def load_ab(p: Path):
    raw = p.read_bytes()
    return UnityPy.load(io.BytesIO(raw[6:] if raw.startswith(b"iqigam") else raw))

print("=== 1. Inspect Live2D Aurora.moc3 Drawables & Vertex Bounds ===", flush=True)
moc_bytes = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", moc_bytes, 64)
cnt_info = struct.unpack_from("<16I", moc_bytes, ptrs[0])
n_draw = cnt_info[4]  # 429 drawables
n_vert_floats = cnt_info[15]  # 43088 floats (= 21544 xy vertices)
print(f"moc3: n_drawables={n_draw}, n_uv_floats={n_vert_floats}", flush=True)

draw_ids = [
    moc_bytes[ptrs[33] + i * 64 : ptrs[33] + (i + 1) * 64].split(b"\x00", 1)[0].decode("ascii", "ignore")
    for i in range(n_draw)
]
vert_counts = struct.unpack_from(f"<{n_draw}I", moc_bytes, ptrs[43])
vert_pos_offs = struct.unpack_from(f"<{n_draw}I", moc_bytes, ptrs[44])  # index in floats!
idx_offs = struct.unpack_from(f"<{n_draw}I", moc_bytes, ptrs[45])
idx_counts = struct.unpack_from(f"<{n_draw}I", moc_bytes, ptrs[46])

# sec[71]: ArtMesh keyform vertex coordinates (float32); check offset via keyform tables or sec[78] UVs
# Let's inspect sec[47] (keyformCounts), sec[48] (keyformOffsets), sec[20/26/27/39/40] vs sec[71] directly!
#Wait: check where KeyformPositionOffsets lives in sec[40..49] OR simply inspect first 21544 xy in sec[71] + sec[78] UVs!
uv_floats = struct.unpack_from(f"<{n_vert_floats}f", moc_bytes, ptrs[78])
uvs = [(uv_floats[2 * k], uv_floats[2 * k + 1]) for k in range(n_vert_floats // 2)]
# Also check first n_vert_floats in sec[71] (Wait: vert_pos_offs[i] points into sec[71] OR sec[78]!)
# Verify last offset + count*2 == n_vert_floats:
print("max uv float end:", vert_pos_offs[-1] + vert_counts[-1] * 2, "vs n_vert_floats:", n_vert_floats, flush=True)
# Find which section holds Drawable default/rest vertex coordinates by checking sec[71] length / sec[69..77]!
# Wait: sec[43] sums to 21544 vertices; Keyform vertex positions in sec[71] have 301680 floats = 150840 (x,y) pairs across keyforms!
# Each Drawable i has keyform[0] starting at kf_begin[i] * 2 floats -> let's check sec[40] or sec[41]!
kf_begin_or_cnt = struct.unpack_from(f"<{n_draw}I", moc_bytes, ptrs[39])
kf_offs = struct.unpack_from(f"<{n_draw}I", moc_bytes, ptrs[40])
print("sec[39] sample:", kf_begin_or_cnt[:6], "sec[40] sample:", kf_offs[:6], flush=True)
# In .moc3: VertexKeyformOffsets = ptrs[70] (KeyformCount uint32 index into sec[71])!
# Check sec[69] & sec[70]:
sec70_sample = struct.unpack_from("<10I", moc_bytes, ptrs[70])
sec69_sample = struct.unpack_from("<10f", moc_bytes, ptrs[69])
print("sec[69] floats:", sec69_sample[:6], "sec[70] ints:", sec70_sample[:6], flush=True)
# Notice sec[70] ints start at 0x0001a0f0 = 106736! Those are Deformer keyforms first, then ArtMesh keyforms!
# Look at sec[39]: VertexKeyformCounts[i]? Wait sec[39] = 66, 66, 66, 22... and sec[40] = 232, 232, 232, 233!
# No, wait: sec[40] is KeyformColor / KeyformOpacity / DrawableKeyformPosition! Wait: sec[26]=0,2,11,13, sec[27]=2,9,2,2 -> KeyformOffsets & KeyformCounts for Parts/Warp!
# And for Drawables (`n_draw=429`), sec[38]..sec[49] are all 429-element arrays! Let's check sec[35..49] element 0..4!
for s_i in range(34, 50):
    arr = struct.unpack_from("<5i", moc_bytes, ptrs[s_i])
    print(f"  sec[{s_i}] (429): {arr}", flush=True)

# Meanwhile check L_Foot1 UVs on Aurora_texture_00.png AND render Spine HitAreas visually!
l2d_tex = Image.open(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Textures\Aurora_texture_00.png").convert("RGBA")
tex_copy = l2d_tex.copy()
tdr = ImageDraw.Draw(tex_copy)
by_id = {draw_ids[i]: i for i in range(n_draw)}
print("\nKey Live2D Drawable UV centers on texture:", flush=True)
for name in draw_ids:
    if any(k in name.lower() for k in ("dref", "foot", "ru1", "ru2", "body", "qianfa5", "l_hand7", "rhand_b2")):
        idx = by_id[name]
        v0 = vert_pos_offs[idx] // 2
        vc = vert_counts[idx]
        if vc == 0: continue
        us = [uvs[v0 + k][0] for k in range(vc)]
        vs = [uvs[v0 + k][1] for k in range(vc)]
        px0, px1 = min(us) * l2d_tex.width, max(us) * l2d_tex.width
        py0, py1 = (1.0 - max(vs)) * l2d_tex.height, (1.0 - min(vs)) * l2d_tex.height
        print(f"  {name:22s}: uv_x=[{min(us):.3f},{max(us):.3f}] uv_y=[{min(vs):.3f},{max(vs):.3f}] px=({px0:.0f},{py0:.0f})-({px1:.0f},{py1:.0f})", flush=True)
        tdr.rectangle([px0, py0, px1, py1], outline="#ff3333", width=3)
        tdr.text((px0 + 2, py0 + 2), name, fill="#ffff00")

# Save 50% JPG of texture UV overlays -> wait texture is 2048x2048 -> 1024x1024 quality=50!
tex_copy.convert("RGB").resize((l2d_tex.width // 2, l2d_tex.height // 2), Image.Resampling.LANCZOS).save(
    out_dir / "live2d_uv_check_50pct.jpg", "JPEG", quality=50
)
print("Saved live2d_uv_check_50pct.jpg", flush=True)

print("\n=== 2. Inspect Spine SoulDress_Aurora_04 Bones & HitAreas ===", flush=True)
skel = json.loads(Path(r"E:\A灵魂潮汐\备份\spine\欧若拉\童话心绘\有背景\SoulDress_Aurora_04.skel.json").read_text(encoding="utf-8"))
bone_world = {}
for b in skel["bones"]:
    name = b["name"]
    par = b.get("parent")
    lx = b.get("x", 0.0)
    ly = b.get("y", 0.0)
    lrot = b.get("rotation", 0.0)
    lsx = b.get("scaleX", 1.0)
    lsy = b.get("scaleY", 1.0)
    if par and par in bone_world:
        px, py, prot, psx, psy = bone_world[par]
        rad = math.radians(prot)
        wx = px + (lx * psx * math.cos(rad) - ly * psy * math.sin(rad))
        wy = py + (lx * psx * math.sin(rad) + ly * psy * math.cos(rad))
        bone_world[name] = (wx, wy, prot + lrot, psx * lsx, psy * lsy)
    else:
        bone_world[name] = (lx, ly, lrot, lsx, lsy)

hit_cfg = json.loads(Path(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\.config.json").read_text(encoding="utf-8"))
for ha in hit_cfg["hit_areas"]:
    bid = ha["id"]
    wx, wy, _, _, _ = bone_world.get(bid, (0, 0, 0, 1, 1))
    print(f"  HitArea {ha['name']} id={bid}: bone_world=({wx:.1f}, {wy:.1f}) local_offset=({ha.get('center_x',0)}, {ha.get('center_y',0)}) box=({ha.get('width')}, {ha.get('height')})", flush=True)

# Render Spine region attachments onto canvas to visually verify Spine HitAreas!
atlas_txt = Path(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\SoulDress_Aurora_04.atlas.txt").read_text(encoding="utf-8")
sp_png = Image.open(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\SoulDress_Aurora_04.png").convert("RGBA")
regions = {}
lines = atlas_txt.splitlines()
i = 0
while i < len(lines):
    ln = lines[i]
    if ln and not ln.startswith((" ", "\t")) and not ln.lower().endswith(".png") and ":" not in ln:
        rname = ln.strip()
        props = {}
        while i + 1 < len(lines) and lines[i+1].startswith((" ", "\t")):
            i += 1
            k, v = lines[i].strip().split(":", 1)
            props[k.strip()] = v.strip()
        regions[rname] = props
    i += 1

SW, SH = 1200, 900
sp_img = Image.new("RGBA", (SW, SH), (24, 28, 38, 255))
# Aurora character mostly in x=[-800, 900], y=[-100, 1500]
def s2p(x, y):
    scale = 0.45
    return (SW / 2 + x * scale, SH - 100 - y * scale)

skin_att = skel["skins"][0]["attachments"]
for sl in skel["slots"]:
    sname = sl["name"]
    bname = sl["bone"]
    att_name = sl.get("attachment")
    if not att_name or sname not in skin_att or att_name not in skin_att[sname]:
        continue
    att = skin_att[sname][att_name]
    rkey = att.get("path", att_name)
    if rkey not in regions:
        continue
    props = regions[rkey]
    ax, ay = [int(v) for v in props["xy"].split(",")]
    aw, ah = [int(v) for v in props["size"].split(",")]
    rot_s = props.get("rotate", "false")
    if rot_s == "true":
        crop = sp_png.crop((ax, ay, ax + ah, ay + aw)).rotate(90, expand=True)
    elif rot_s == "180":
        crop = sp_png.crop((ax, ay, ax + aw, ay + ah)).rotate(180, expand=True)
    elif rot_s == "270":
        crop = sp_png.crop((ax, ay, ax + ah, ay + aw)).rotate(-90, expand=True)
    else:
        crop = sp_png.crop((ax, ay, ax + aw, ay + ah))
    wx, wy, wrot, wsx, wsy = bone_world[bname]
    # Place center roughly in Spine world
    att_x = att.get("x", 0.0)
    att_y = att.get("y", 0.0)
    att_rot = att.get("rotation", 0.0)
    rad = math.radians(wrot)
    cx = wx + (att_x * wsx * math.cos(rad) - att_y * wsy * math.sin(rad))
    cy = wy + (att_x * wsx * math.sin(rad) + att_y * wsy * math.cos(rad))
    px, py = s2p(cx, cy)
    rw = max(2, int(abs(crop.width * 0.45 * wsx)))
    rh = max(2, int(abs(crop.height * 0.45 * wsy)))
    thumb = crop.resize((rw, rh), Image.Resampling.BILINEAR).rotate(wrot + att_rot, expand=True)
    sp_img.alpha_composite(thumb, (int(px - thumb.width / 2), int(py - thumb.height / 2)))

sdr = ImageDraw.Draw(sp_img)
for ha in hit_cfg["hit_areas"]:
    bid = ha["id"]
    if bid not in bone_world:
        continue
    wx, wy, _, _, _ = bone_world[bid]
    # Note: in EX Studio Spine, hit_area center_x/y and width/height are in EX units (~100 Spine px = 1 unit)!
    hx = wx + ha.get("center_x", 0.0) * 100.0
    hy = wy + ha.get("center_y", 0.0) * 100.0
    hw = ha.get("width", 1.0) * 100.0
    hh = ha.get("height", 1.0) * 100.0
    x0, y0 = s2p(hx - hw / 2.0, hy + hh / 2.0)
    x1, y1 = s2p(hx + hw / 2.0, hy - hh / 2.0)
    sdr.rectangle([x0, y0, x1, y1], outline="#00ff88", width=3)
    cxp, cyp = s2p(wx, wy)
    sdr.ellipse([cxp - 4, cyp - 4, cxp + 4, cyp + 4], fill="#ff3333")
    sdr.text((x0 + 4, y0 + 2), f"{ha['name']}({bid})", fill="#ffff00")

sp_50 = sp_img.convert("RGB").resize((SW // 2, SH // 2), Image.Resampling.LANCZOS)
sp_50.save(out_dir / "spine_hitbox_check_50pct.jpg", "JPEG", quality=50)
print("Saved spine_hitbox_check_50pct.jpg", flush=True)
