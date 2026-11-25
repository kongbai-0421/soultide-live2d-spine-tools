import json
from pathlib import Path

m = json.loads(Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json").read_text(encoding="utf-8"))

print("=== ALL FX CLIPS POSITION & SCALE SUMMARY ===")
for s in m["skins"]:
    cw, ch, cx, cy = s["canvas_w"], s["canvas_h"], s["cam_x"], s["cam_y"]
    for c in s["clips"]:
        if not c["clip"].startswith("fx_") or not c["nodes"]:
            continue
        xs = [round(n["world_pos"][0] - cx) for n in c["nodes"]]
        ys = [round(n["world_pos"][1] - cy) for n in c["nodes"]]
        oob = any(abs(x) > cw * 0.52 or abs(y) > ch * 0.52 for x, y in zip(xs, ys))
        sc0 = min(abs(n["world_scale"][0]) for n in c["nodes"])
        sc1 = max(abs(n["world_scale"][0]) for n in c["nodes"])
        print(f"{s['skin_key']:24s} {c['clip']:12s} n={len(c['nodes']):2d} rel_x=({min(xs):5d}..{max(xs):5d}) rel_y=({min(ys):5d}..{max(ys):5d}) wsc=({sc0:6.2f}..{sc1:6.2f}) {'OOB!' if oob else 'ok  '} cam=({cx:.0f},{cy:.0f})")

print("\n=== ALL SCALING_MODE == 1 NODES (World px vs /100 local px) ===")
sm1 = []
for s in m["skins"]:
    cw, ch, cx, cy = s["canvas_w"], s["canvas_h"], s["cam_x"], s["cam_y"]
    for c in s["clips"]:
        for n in c["nodes"]:
            if n["scalingMode"] == 1:
                szx = n["sizeX"]["scalar"] if n["size3D"] else n["size"]["scalar"]
                szy = n["sizeY"]["scalar"] if n["size3D"] else n["size"]["scalar"]
                px_x = szx * abs(n["world_scale"][0])
                px_y = szy * abs(n["world_scale"][1])
                sm1.append((px_x, px_y, s["skin_key"], c["clip"], n["name"], round(n["world_pos"][0]-cx), round(n["world_pos"][1]-cy), round(n["world_scale"][0], 2), szx, szy, n["texName"], n["renderMode"]))

for px_x, px_y, sk, cl, nn, rx, ry, wsc, szx, szy, tex, rm in sorted(sm1, reverse=True):
    print(f"  px100=({px_x:7.1f}x{px_y:7.1f}) no100=({px_x/100:5.2f}x{px_y/100:5.2f}) rel=({rx:5d},{ry:5d}) wsc100={wsc:7.2f} sz=({szx:.1f},{szy:.1f}) rm={rm} {sk}/{cl}/{nn} [{tex}]")
