import json
import math
from pathlib import Path

cache = json.loads(Path(r"E:\A灵魂潮汐\tools\_spine38_geom_cache.json").read_text(encoding="utf-8-sig"))
spine_root = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")

g = cache["月本柚/原皮"]
print("=== 月本柚/原皮 z-bones ===")
for b in g["bones"]:
    if b["name"].startswith("z") or b["name"] in ("1", "2", "3", "4"):
        print(
            f"  {b['name']:4s} p={b['parent']:4s} w=({b['wx']:7.1f},{b['wy']:7.1f}) "
            f"vc=({b.get('vcx')},{b.get('vcy')}) vx=[{b.get('vx0')},{b.get('vx1')}] "
            f"vy=[{b.get('vy0')},{b.get('vy1')}] vw={b.get('vw', 0)}"
        )

print("\n=== Check all z_rig (47 models) topology ===")
z_rig_consistent = 0
z_rig_diff = []
for rel, g in sorted(cache.items()):
    bmap = {b["name"]: b for b in g["bones"]}
    if {"z2", "z3", "z4", "z5", "z6", "z7", "z8", "z9", "z10"} <= set(bmap):
        # Check if z10 is above z8, z8 is above z2, z3/z5 are below z2, z4/z6 are below z3/z5
        ok = (
            bmap["z10"]["wy"] > bmap["z8"]["wy"]
            and bmap["z8"]["wy"] > bmap["z2"]["wy"]
            and bmap["z4"]["wy"] < bmap["z2"]["wy"]
        )
        if ok:
            z_rig_consistent += 1
        else:
            z_rig_diff.append((rel, bmap["z10"]["wy"], bmap["z8"]["wy"], bmap["z2"]["wy"], bmap["z4"]["wy"]))
print(f"z_rig consistent: {z_rig_consistent}, diff: {len(z_rig_diff)}")
for d in z_rig_diff[:10]:
    print("  DIFF:", d)

print("\n=== Geometric Audit of ALL 170 current Spine hit_areas ===")
issues = []
for rel, g in sorted(cache.items()):
    cfg_p = spine_root / rel / ".config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    bmap = {b["name"]: b for b in g["bones"]}
    # Character vertical bounds from all bones that have rendered vertices (excluding huge bg slots)
    vbones = [b for b in g["bones"] if b.get("vw", 0) > 0]
    if not vbones:
        continue
    cy0 = min(b["vy0"] for b in vbones)
    cy1 = max(b["vy1"] for b in vbones)
    cx0 = min(b["vx0"] for b in vbones)
    cx1 = max(b["vx1"] for b in vbones)
    ch = max(200.0, cy1 - cy0)
    cw = max(150.0, cx1 - cx0)

    boxes = {}
    for ha in cfg.get("hit_areas", []):
        bid = ha["id"]
        b = bmap[bid]
        bx = b["wx"] + float(ha.get("center_x", 0.0)) * 100.0
        by = b["wy"] + float(ha.get("center_y", 0.0)) * 100.0
        bw = float(ha["width"]) * 100.0
        bh = float(ha["height"]) * 100.0
        boxes[ha["motion"]] = (bx, by, bw, bh, bid)

    probs = []
    if "头" in boxes and "胸" in boxes:
        if boxes["胸"][1] >= boxes["头"][1]:
            probs.append(f"胸 above 头 (chest_y={boxes['胸'][1]:.0f} >= head_y={boxes['头'][1]:.0f})")
        if boxes["头"][1] - boxes["胸"][1] > 0.34 * ch:
            probs.append(f"胸 too far below 头 ({(boxes['头'][1] - boxes['胸'][1])/ch:.2f}*H)")
    if "头" in boxes:
        hx, hy, hw, hh, hbid = boxes["头"]
        for hand_k in ("左手", "右手"):
            if hand_k in boxes:
                lx, ly, lw, lh, lbid = boxes[hand_k]
                if math.hypot(lx - hx, ly - hy) < 0.14 * ch and ly > hy - 0.12 * ch:
                    probs.append(f"{hand_k}({lbid}) stacked on 头({hbid})")
    if "腿" in boxes and "足" in boxes:
        if boxes["足"][1] > boxes["腿"][1] + 0.05 * ch:
            probs.append(f"足 above 腿 (foot_y={boxes['足'][1]:.0f} > leg_y={boxes['腿'][1]:.0f})")
    if "胸" in boxes and "腿" in boxes:
        if boxes["腿"][1] >= boxes["胸"][1]:
            probs.append(f"腿 above 胸 (leg_y={boxes['腿'][1]:.0f} >= chest_y={boxes['胸'][1]:.0f})")
    # Check duplicate/overlapping pairs
    keys = list(boxes.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            k1, k2 = keys[i], keys[j]
            if {k1, k2} == {"左手", "右手"}:
                continue
            d = math.hypot(boxes[k1][0] - boxes[k2][0], boxes[k1][1] - boxes[k2][1])
            if d < 0.05 * ch:
                probs.append(f"{k1} & {k2} stacked (dist={d/ch:.3f}*H)")
    if probs:
        issues.append((rel, probs))

print(f"Total models with geometric issues: {len(issues)} / 170")
for rel, probs in issues[:40]:
    print(f"  {rel}: {'; '.join(probs)}")
