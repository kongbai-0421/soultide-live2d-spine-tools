import json, sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

idx = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
cat = bfe.build_skin_catalog(repo)

# 1. Check all DressSpine prefabs & Point_Root (50000) scale vs UI FX root localScale
print("=== CHECKING ALL SKINS WITH EFFECT PREFABS: person.ui_per_spine vs fx_point_root.wsx vs effect root ls ===")
for r in cat:
    if not r.get("bg_prefab") or not r.get("effect_prefabs"):
        continue
    layout = bfe.inspect_bg_prefab_layout(idx, r)
    p = layout["person"]
    pr = layout["fx_point_root"]
    for eid, ep in r["effect_prefabs"].items():
        stem = Path(ep).stem.lower()
        ls_str = "?"
        eff_pid = None
        for k, pid in idx.art_container.items():
            if ep.lower() in k.lower():
                eff_pid = pid
                break
        if eff_pid is not None:
            o = idx.art_objs[eff_pid]
            co = o.read_typetree()
            gpid = co["m_GameObject"]["m_PathID"] if "m_GameObject" in co else eff_pid
            go = idx.art_objs[gpid].read_typetree()
            for c in go.get("m_Component", []):
                comp = idx.art_objs.get(c["component"]["m_PathID"])
                if comp and comp.type.name in ("Transform", "RectTransform"):
                    ct = comp.read_typetree()
                    s = ct["m_LocalScale"]
                    ls_str = f"({s['x']:.4f}, {s['y']:.4f}, {s['z']:.4f})"
                    ap = ct.get("m_AnchoredPosition")
                    lp = ct.get("m_LocalPosition")
                    ls_str += f" lp=({lp['x']:.1f},{lp['y']:.1f}) ap={ap}"
        # Also check sda / unlock_show / GirlDressSpine / Point_Root in Spine prefab
        inv_u = 1.0 / max(1e-6, p["ui_per_spine"])
        flag = ""
        if pr["wsz"] == 0 or abs(pr["wsx"] - p["ui_per_spine"]) > 0.05 or ("?" not in ls_str and "(1.0000," not in ls_str):
            flag = " <-- DIFF"
        if flag:
            print(f"{r['skin_key']:26s} fx_{eid} u_p_s={p['ui_per_spine']:.4f} (1/u={inv_u:.4f}) p.wsx={p['wsx']:.3f} pr.ws=({pr['wsx']:.4f},{pr['wsy']:.4f},{pr['wsz']:.4f}) pr.w=({pr['wx']:.1f},{pr['wy']:.1f}) eff_root_ls={ls_str}")

# 2. Check Canvas and UICamera in 01_scenes or 03_prefabs/ui (MainUI / GirlUI / GirlDressShowUI)
print("\n=== SEARCHING UI PREFABS FOR CANVAS SCALE & CAMERA ===")
for ui_name in ("mainui", "girlui", "girldressshowui", "uirendercam"):
    for stem, gpids in idx.ui_go_by_name.items():
        if ui_name in stem:
            for gpid in gpids[:1]:
                go = idx.ui_objs[gpid].read_typetree()
                for c in go.get("m_Component", []):
                    comp = idx.ui_objs.get(c["component"]["m_PathID"])
                    if comp and comp.type.name in ("Transform", "RectTransform", "Canvas", "Camera"):
                        print(f"  [{stem}] {comp.type.name}: {comp.read_typetree()}")
