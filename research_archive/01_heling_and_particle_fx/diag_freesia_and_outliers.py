import json, sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import load_ab, CDN_ROOT
import batch_fx_exporter as bfe

repo = bfe.FullI18nRepo()
cat = bfe.build_skin_catalog(repo)
by_sk = {r["skin_key"]: r for r in cat}

def dump_tree(ab_path):
    env = load_ab(CDN_ROOT / ab_path)
    gos = {o.path_id: o.read_typetree() for o in env.objects if o.type.name == "GameObject"}
    rts = {}
    for o in env.objects:
        if o.type.name in ("Transform", "RectTransform"):
            t = o.read_typetree()
            rts[o.path_id] = (o.type.name, t)
    for pid, (tp, t) in rts.items():
        go_pid = t["m_GameObject"]["m_PathID"]
        name = gos.get(go_pid, {}).get("m_Name", "?")
        fpid = t["m_Father"]["m_PathID"]
        lp = t.get("m_LocalPosition")
        ls = t.get("m_LocalScale")
        ap = t.get("m_AnchoredPosition")
        sd = t.get("m_SizeDelta")
        amin = t.get("m_AnchorMin")
        amax = t.get("m_AnchorMax")
        print(f"  [{tp[0]}] pid={pid} father={fpid} name={name!r} lp={lp} ls={ls} ap={ap} sd={sd} anchor=({amin},{amax})")

row = by_sk["402_Freesia_S5"]
print("=== CATALOG ===", json.dumps(row, ensure_ascii=False))
for k, v in row.items():
    if isinstance(v, str) and v.endswith(".ab"):
        print(f"--- {k}: {v} ---")
        dump_tree(v)
    elif isinstance(v, list):
        for item in v:
            if isinstance(item, str) and item.endswith(".ab"):
                print(f"--- {k}: {item} ---")
                dump_tree(item)
            elif isinstance(item, dict):
                for kk, vv in item.items():
                    if isinstance(vv, str) and vv.endswith(".ab"):
                        print(f"--- {k}.{kk}: {vv} ---")
                        dump_tree(vv)

for p in Path(r"E:\A灵魂潮汐\tools\_batch_spine_output").rglob("*402*/*.config.json"):
    print("CONFIG:", p)
    print(p.read_text(encoding="utf-8")[:1500])

manifest = json.loads(Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json").read_text(encoding="utf-8"))
print("\n=== HUGE / OOB SUMMARY ===")
print("Total manifest nodes:", sum(len(c["nodes"]) for s in manifest["skins"] for c in s["clips"]))
huge = []
for s in manifest["skins"]:
    cw, ch = s["canvas_w"], s["canvas_h"]
    cx, cy = s["cam_x"], s["cam_y"]
    for c in s["clips"]:
        for n in c["nodes"]:
            if n["size3D"]:
                sx = n["sizeX"]["scalar"] * abs(n["world_scale"][0])
                sy = n["sizeY"]["scalar"] * abs(n["world_scale"][1])
            else:
                sx = n["size"]["scalar"] * abs(n["world_scale"][0])
                sy = n["size"]["scalar"] * abs(n["world_scale"][1])
            dx = abs(n["world_pos"][0] - cx)
            dy = abs(n["world_pos"][1] - cy)
            if sx > cw * 2.5 or sy > ch * 2.5 or dx > cw * 1.0 or dy > ch * 1.0:
                huge.append((s["skin_key"], c["clip"], n["name"], n["scalingMode"], round(sx), round(sy), cw, ch, round(n["world_pos"][0]-cx), round(n["world_pos"][1]-cy), round(n["world_scale"][0], 2), n["renderMode"], n["texName"]))
print(f"Huge or OOB nodes ({len(huge)}):")
for row in huge[:80]:
    print(" ", row)
