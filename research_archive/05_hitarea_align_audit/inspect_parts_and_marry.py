import json
import math
import struct
from pathlib import Path
from PIL import Image, ImageDraw

out_dir = Path(r".\_scratch\hitbox_check")
out_dir.mkdir(parents=True, exist_ok=True)

print("=== 1. Live2D Drawables Grouped by Semantic Body Part (UV Crop Contact Sheet) ===", flush=True)
mb = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", mb, 64)
cnt_info = struct.unpack_from("<16I", mb, ptrs[0])
n_draw = cnt_info[4]
n_uv_f = cnt_info[15]
draw_ids = [mb[ptrs[33]+i*64 : ptrs[33]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_draw)]
v_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[43])
v_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[44])
uv_f = struct.unpack_from(f"<{n_uv_f}f", mb, ptrs[78])
tex = Image.open(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Textures\Aurora_texture_00.png").convert("RGBA")

# Print Part hierarchy + Drawables belonging to Parts (sec[34] or PartNames) so we know EXACT Part -> Drawable!
n_parts = cnt_info[0]
part_ids = [mb[ptrs[3]+i*64 : ptrs[3]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_parts)]
# Check sec[37] vs sec[38] vs sec[41]: parent part index for drawables? Let's print min/max of sec[34..42]
for s in range(34, 43):
    vals = struct.unpack_from(f"<{n_draw}i", mb, ptrs[s])
    print(f"  sec[{s}] min={min(vals)} max={max(vals)} sample={vals[:8]}")
# Wait sec[37] or sec[38] -> check which one has range 0..93 (PartIndex!)
# Check sec[47], sec[48], sec[49] too:
for s in range(47, 50):
    vals = struct.unpack_from(f"<{n_draw}i", mb, ptrs[s])
    print(f"  sec[{s}] min={min(vals)} max={max(vals)} sample={vals[:8]}")

# Print all Drawables with keywords OR top UV islands (legs/feet/hands/bra/body)
cands = []
for i, name in enumerate(draw_ids):
    vc = v_cnt[i]
    if vc == 0: continue
    u0 = v_off[i] // 2
    us = [uv_f[2*(u0+k)] for k in range(vc)]
    vs = [uv_f[2*(u0+k)+1] for k in range(vc)]
    x0, x1 = int(min(us)*tex.width), int(max(us)*tex.width)
    y0, y1 = int((1.0-max(vs))*tex.height), int((1.0-min(vs))*tex.height)
    low = name.lower()
    if any(k in low for k in ("foot", "tui", "leg", "ru", "bra", "body", "rhand", "lhand", "l_hand", "face", "head", "tou", "qianfa")):
        if not any(sk in low for sk in ("yy", "bs", "hua")):
            cands.append((name, x0, y0, x1, y1))

# Also include ANY non-ArtMesh numbered or ArtMesh* in top UV leg strip (y < 400, x in 700..1500)
for i, name in enumerate(draw_ids):
    vc = v_cnt[i]
    if vc == 0: continue
    u0 = v_off[i] // 2
    us = [uv_f[2*(u0+k)] for k in range(vc)]
    vs = [uv_f[2*(u0+k)+1] for k in range(vc)]
    x0, x1 = int(min(us)*tex.width), int(max(us)*tex.width)
    y0, y1 = int((1.0-max(vs))*tex.height), int((1.0-min(vs))*tex.height)
    if y0 < 360 and 650 <= x0 <= 1550 and (x1-x0) > 25 and (y1-y0) > 25:
        if all(c[0] != name for c in cands):
            cands.append((name, x0, y0, x1, y1))

print(f"Candidate visual patches to inspect: {len(cands)}")
# Render labeled contact sheet of UV crops (compressed 50% JPG)
cols = 8
cw, ch = 160, 180
rows = (len(cands) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cw, rows * ch), (25, 27, 34))
sdr = ImageDraw.Draw(sheet)
for idx, (nm, x0, y0, x1, y1) in enumerate(cands):
    r, c = divmod(idx, cols)
    px0, py0 = max(0, x0 - 4), max(0, y0 - 4)
    px1, py1 = min(tex.width, x1 + 4), min(tex.height, y1 + 4)
    crop = tex.crop((px0, py0, max(px0+1, px1), max(py0+1, py1)))
    crop.thumbnail((cw - 12, ch - 34), Image.Resampling.LANCZOS)
    bg = Image.new("RGBA", crop.size, (36, 40, 52, 255))
    bg.alpha_composite(crop)
    sheet.paste(bg.convert("RGB"), (c * cw + 6, r * ch + 24))
    sdr.text((c * cw + 4, r * ch + 4), f"{nm[:18]}", fill=(255, 235, 130))
sheet.resize((sheet.width // 2, sheet.height // 2), Image.Resampling.LANCZOS).save(
    out_dir / "live2d_uv_parts_sheet_50pct.jpg", "JPEG", quality=50
)
print("Saved live2d_uv_parts_sheet_50pct.jpg", flush=True)

print("\n=== 2. Render Spine idle_marry (t=0) Pose + HitAreas ===", flush=True)
skel = json.loads(Path(r"E:\A灵魂潮汐\备份\spine\欧若拉\童话心绘\有背景\SoulDress_Aurora_04.skel.json").read_text(encoding="utf-8"))
anim = skel["animations"].get("idle_marry", {})
bone_anim = anim.get("bones", {})

# Apply t=0 keyframes onto setup bone transforms!
def kf_val(arr, keys, default):
    if not arr: return default
    k0 = arr[0]
    return tuple(k0.get(k, default[i]) for i, k in enumerate(keys))

bone_world = {}
for b in skel["bones"]:
    name = b["name"]
    par = b.get("parent")
    lx = b.get("x", 0.0)
    ly = b.get("y", 0.0)
    lrot = b.get("rotation", 0.0)
    lsx = b.get("scaleX", 1.0)
    lsy = b.get("scaleY", 1.0)
    if name in bone_anim:
        ba = bone_anim[name]
        if "translate" in ba and ba["translate"]:
            dx, dy = kf_val(ba["translate"], ("x", "y"), (0.0, 0.0))
            lx += dx; ly += dy
        if "rotate" in ba and ba["rotate"]:
            drot, = kf_val(ba["rotate"], ("angle",), (0.0,))
            lrot += drot
        if "scale" in ba and ba["scale"]:
            dsx, dsy = kf_val(ba["scale"], ("x", "y"), (1.0, 1.0))
            lsx *= dsx; lsy *= dsy
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

SW, SH = 1200, 1000
sp_img = Image.new("RGBA", (SW, SH), (22, 26, 36, 255))
def s2p(x, y):
    return (SW / 2 - 150 + x * 0.45, SH - 80 - y * 0.45)

skin_att = skel["skins"][0]["attachments"]
# Also draw bones connected for visual reference of legs/feet/hands!
for sl in skel["slots"]:
    sname = sl["name"]; bname = sl["bone"]; att_name = sl.get("attachment")
    if not att_name or sname not in skin_att or att_name not in skin_att[sname]: continue
    att = skin_att[sname][att_name]
    rkey = att.get("path", att_name)
    if rkey not in regions: continue
    props = regions[rkey]
    ax, ay = [int(v) for v in props["xy"].split(",")]
    aw, ah = [int(v) for v in props["size"].split(",")]
    rot_s = props.get("rotate", "false")
    if rot_s == "true": crop = sp_png.crop((ax, ay, ax + ah, ay + aw)).rotate(90, expand=True)
    elif rot_s == "180": crop = sp_png.crop((ax, ay, ax + aw, ay + ah)).rotate(180, expand=True)
    elif rot_s == "270": crop = sp_png.crop((ax, ay, ax + ah, ay + aw)).rotate(-90, expand=True)
    else: crop = sp_png.crop((ax, ay, ax + aw, ay + ah))
    wx, wy, wrot, wsx, wsy = bone_world[bname]
    att_x = att.get("x", 0.0); att_y = att.get("y", 0.0); att_rot = att.get("rotation", 0.0)
    rad = math.radians(wrot)
    cx = wx + (att_x * wsx * math.cos(rad) - att_y * wsy * math.sin(rad))
    cy = wy + (att_x * wsx * math.sin(rad) + att_y * wsy * math.cos(rad))
    px, py = s2p(cx, cy)
    rw = max(2, int(abs(crop.width * 0.45 * wsx)))
    rh = max(2, int(abs(crop.height * 0.45 * wsy)))
    thumb = crop.resize((rw, rh), Image.Resampling.BILINEAR).rotate(wrot + att_rot, expand=True)
    sp_img.alpha_composite(thumb, (int(px - thumb.width / 2), int(py - thumb.height / 2)))

sdr = ImageDraw.Draw(sp_img)
hit_cfg = json.loads(Path(r"E:\A灵魂潮汐\spine\欧若拉\童话心绘\.config.json").read_text(encoding="utf-8"))
print("Spine HitAreas in idle_marry pose:")
for ha in hit_cfg["hit_areas"]:
    bid = ha["id"]
    wx, wy, _, _, _ = bone_world.get(bid, (0, 0, 0, 1, 1))
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
    print(f"  {ha['name']} id={bid}: world=({wx:.1f},{wy:.1f}) box_center=({hx:.1f},{hy:.1f}) wh=({hw:.0f}x{hh:.0f})")

sp_img.convert("RGB").resize((SW // 2, SH // 2), Image.Resampling.LANCZOS).save(
    out_dir / "spine_idle_marry_hitboxes_50pct.jpg", "JPEG", quality=50
)
print("Saved spine_idle_marry_hitboxes_50pct.jpg", flush=True)
