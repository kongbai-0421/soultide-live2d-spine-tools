import io
import json
import math
import struct
from pathlib import Path
from PIL import Image, ImageDraw
import UnityPy

out_dir = Path(r".\_scratch\hitbox_check")
out_dir.mkdir(parents=True, exist_ok=True)

print("=== 1. Live2D Aurora.moc3: Find TRUE skin/body/foot/hand/chest/head Drawables by Part & Texture Skin Detection ===", flush=True)
mb = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", mb, 64)
cnt_info = struct.unpack_from("<16I", mb, ptrs[0])
n_parts = cnt_info[0]
n_draw = cnt_info[4]
n_uv_f = cnt_info[15]

part_ids = [mb[ptrs[3]+i*64 : ptrs[3]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_parts)]
draw_ids = [mb[ptrs[33]+i*64 : ptrs[33]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_draw)]
draw_part = struct.unpack_from(f"<{n_draw}i", mb, ptrs[39])
v_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[43])
v_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[44])
uv_f = struct.unpack_from(f"<{n_uv_f}f", mb, ptrs[78])
tex = Image.open(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Textures\Aurora_texture_00.png").convert("RGBA")

# List all Parts and how many drawables belong to each Part!
part_to_draws = {}
for i in range(n_draw):
    pi = draw_part[i]
    pnm = part_ids[pi] if 0 <= pi < n_parts else f"NONE({pi})"
    part_to_draws.setdefault(pnm, []).append(i)

print("Live2D Parts -> Drawables summary:")
for pnm, idxs in part_to_draws.items():
    names = [draw_ids[i] for i in idxs]
    print(f"  Part '{pnm}' ({len(idxs)}): {names[:10]}{'...' if len(names)>10 else ''}")

# Measure each Drawable's UV crop: size and skin-tone pixel fraction!
def skin_score(crop: Image.Image) -> float:
    w, h = crop.size
    if w == 0 or h == 0: return 0.0
    tot = 0; skin = 0
    step = max(1, (w * h) // 400)
    pxs = list(crop.getdata())[::step]
    for r, g, b, a in pxs:
        if a > 40:
            tot += 1
            if r > 180 and g > 130 and b > 100 and r > g > b - 10 and (r - b) > 15:
                skin += 1
    return (skin / tot) if tot > 0 else 0.0

interesting = []
for i, dnm in enumerate(draw_ids):
    vc = v_cnt[i]
    if vc == 0: continue
    u0 = v_off[i] // 2
    us = [uv_f[2*(u0+k)] for k in range(vc)]
    vs = [uv_f[2*(u0+k)+1] for k in range(vc)]
    x0, x1 = int(min(us)*tex.width), int(max(us)*tex.width)
    y0, y1 = int((1.0-max(vs))*tex.height), int((1.0-min(vs))*tex.height)
    pw, ph = x1 - x0, y1 - y0
    if pw < 16 or ph < 16: continue
    crop = tex.crop((max(0, x0), max(0, y0), min(tex.width, x1), min(tex.height, y1)))
    sc = skin_score(crop)
    pi = draw_part[i]
    pnm = part_ids[pi] if 0 <= pi < n_parts else "?"
    # Pick skin-toned drawables OR interesting part names (Foot, Leg, Tui, Hand, Bra, Body, Tou)
    if sc > 0.12 or any(k in pnm.lower() or k in dnm.lower() for k in ("foot", "tui", "leg", "hand", "bra", "ru", "body", "shangti", "tou", "jiao", "zu", "xiong")):
        if not any(sk in dnm.lower() for sk in ("yy", "bs", "shouchi")):
            interesting.append((pnm, dnm, pw, ph, sc, crop, x0, y0, x1, y1))

print(f"\nLive2D skin/part candidates found: {len(interesting)}")
for pnm, dnm, pw, ph, sc, _, x0, y0, x1, y1 in interesting:
    if sc > 0.15 or any(k in pnm.lower() for k in ("foot", "hand", "bra", "shangti", "body")):
        print(f"  Part={pnm:18s} Draw={dnm:22s} uv_px=({x0},{y0})-({x1},{y1}) {pw}x{ph} skin={sc:.2f}")

# Render readable labeled contact sheet (max 6 cols, huge readable text)
cols = 6
cw, ch = 220, 220
rows = (len(interesting) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cw, rows * ch), (24, 26, 34))
sdr = ImageDraw.Draw(sheet)
for idx, (pnm, dnm, pw, ph, sc, crop, *_) in enumerate(interesting):
    r, c = divmod(idx, cols)
    th = crop.copy()
    th.thumbnail((cw - 16, ch - 44), Image.Resampling.LANCZOS)
    bg = Image.new("RGBA", th.size, (38, 42, 54, 255))
    bg.alpha_composite(th)
    sheet.paste(bg.convert("RGB"), (c * cw + 8, r * ch + 38))
    sdr.text((c * cw + 6, r * ch + 4), f"[{pnm[:14]}]", fill=(120, 220, 255))
    sdr.text((c * cw + 6, r * ch + 20), f"{dnm[:18]} s={sc:.2f}", fill=(255, 240, 120))

sheet.resize((sheet.width // 2, sheet.height // 2), Image.Resampling.LANCZOS).save(
    out_dir / "live2d_true_parts_50pct.jpg", "JPEG", quality=50
)
print("Saved live2d_true_parts_50pct.jpg", flush=True)

print("\n=== 2. Spine SoulDress_Aurora_04: Inspect ALL Bones & Slots (legs, feet, hands, chest, head) in idle_marry ===", flush=True)
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

# Print all Spine bones with attachments having skin tones OR mesh names in region bounds
skin_att = skel["skins"][0]["attachments"]
sp_cands = []
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
    if rot_s == "true": crop = sp_png.crop((ax, ay, ax+ah, ay+aw)).rotate(90, expand=True)
    elif rot_s == "180": crop = sp_png.crop((ax, ay, ax+aw, ay+ah)).rotate(180, expand=True)
    elif rot_s == "270": crop = sp_png.crop((ax, ay, ax+ah, ay+aw)).rotate(-90, expand=True)
    else: crop = sp_png.crop((ax, ay, ax+aw, ay+ah))
    sc = skin_score(crop)
    wx, wy, wrot, wsx, wsy = bone_world[bname]
    if sc > 0.15 or bname in ("47", "113", "321", "83", "84", "87", "88", "79", "80", "81", "82", "85", "86", "89", "90"):
        sp_cands.append((bname, sname, att_name, wx, wy, sc, crop))
        print(f"  Spine bone={bname:6s} slot={sname:6s} world=({wx:6.1f},{wy:6.1f}) size={crop.size} skin={sc:.2f}")

# Contact sheet for Spine skin/key bones!
scols = 6; scw, sch = 200, 200
srows = (len(sp_cands) + scols - 1) // scols
ssheet = Image.new("RGB", (scols * scw, max(1, srows) * sch), (24, 26, 34))
ssdr = ImageDraw.Draw(ssheet)
for idx, (bn, sn, an, wx, wy, sc, crop) in enumerate(sp_cands):
    r, c = divmod(idx, scols)
    th = crop.copy(); th.thumbnail((scw - 16, sch - 44), Image.Resampling.LANCZOS)
    bg = Image.new("RGBA", th.size, (38, 42, 54, 255)); bg.alpha_composite(th)
    ssheet.paste(bg.convert("RGB"), (c * scw + 8, r * sch + 38))
    ssdr.text((c * scw + 6, r * sch + 4), f"bone={bn} slot={sn}", fill=(120, 220, 255))
    ssdr.text((c * scw + 6, r * sch + 20), f"({wx:.0f},{wy:.0f}) s={sc:.2f}", fill=(255, 240, 120))
ssheet.resize((max(1, ssheet.width // 2), max(1, ssheet.height // 2)), Image.Resampling.LANCZOS).save(
    out_dir / "spine_true_parts_50pct.jpg", "JPEG", quality=50
)
print("Saved spine_true_parts_50pct.jpg", flush=True)
