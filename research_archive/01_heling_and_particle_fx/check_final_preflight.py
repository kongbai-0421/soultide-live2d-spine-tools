import json, sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

idx = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
cat = bfe.build_skin_catalog(repo)
by_sk = {r["skin_key"]: r for r in cat}

# 1. Check Freesia_S5 & RubyRose_S2 effect RectTransform anchors/pivots and parent chain
for ep in ("FX_UI/FX_Freesia_S5_Background_Touch01", "FX_UI/FX_RubyRose_S2_Background_chat"):
    for k, pid in idx.art_container.items():
        if ep.lower() in k.lower():
            co = idx.art_objs[pid].read_typetree()
            gpid = co["m_GameObject"]["m_PathID"] if "m_GameObject" in co else pid
            print(f"\n=== FULL RECT/TRANSFORM: {k} ===")
            def walk(gp, d=0):
                go = idx.art_objs[gp].read_typetree()
                for c in go.get("m_Component", []):
                    o = idx.art_objs.get(c["component"]["m_PathID"])
                    if o and o.type.name in ("Transform", "RectTransform"):
                        t = o.read_typetree()
                        print("  "*d + f"{go['m_Name']!r} ({o.type.name}) lp={t.get('m_LocalPosition')} ls={t.get('m_LocalScale')} ap={t.get('m_AnchoredPosition')} amin={t.get('m_AnchorMin')} amax={t.get('m_AnchorMax')} piv={t.get('m_Pivot')} sd={t.get('m_SizeDelta')}")
                        for ch in t.get("m_Children", []):
                            ct = idx.art_objs.get(ch["m_PathID"])
                            if ct: walk(ct.read_typetree()["m_GameObject"]["m_PathID"], d+1)
            walk(gpid)

# 2. Check why inspect_bg_prefab_layout picked cam=(-319,-275) for 402_Freesia_S5 & check bg_static margins skins
for sk in ("402_Freesia_S5", "2002_Ennis_S3", "4402_Dora_S3", "4501_RubyRose_S2", "1101_NicoletteLamel_S2", "1702_Juewa_S3", "1802_SakuyaMako_S3", "4401_Dora_S2"):
    r = by_sk[sk]
    lay = bfe.inspect_bg_prefab_layout(idx, r)
    bgp = Path(r["bg_prefab"]).name.lower()
    objs = idx.ui_objs if bgp in idx.ui_go_by_name else idx.art_objs
    gid = idx.ui_go_by_name[bgp][0] if bgp in idx.ui_go_by_name else idx.art_go_by_name[bgp][0]
    print(f"\n=== LAYOUT {sk}: cam=({lay['cam_x']},{lay['cam_y']}) canvas=({lay['canvas_w']}x{lay['canvas_h']}) pr={lay['fx_point_root']} p={lay['person']} ===")
    # Check active image rects
    def walk_imgs(gp, wx=0.0, wy=0.0, wsx=1.0, wsy=1.0, depth=0):
        go = objs[gp].read_typetree()
        if not go.get("m_IsActive", True): return
        if any(x in go.get("m_Name","").lower() for x in ("limit","harmonious")): return
        tf = None; has_img = False; img_type = ""
        for c in go.get("m_Component", []):
            o = objs.get(c["component"]["m_PathID"])
            if not o: continue
            if o.type.name in ("Transform", "RectTransform"): tf = o.read_typetree()
            elif o.type.name == "MonoBehaviour":
                t = o.read_typetree()
                if "m_Sprite" in t:
                    has_img = True
                    img_type = f"col={round(t.get('m_Color',{}).get('a',1),2)}"
        if not tf: return
        lp = tf.get("m_LocalPosition", {"x":0,"y":0}); ap = tf.get("m_AnchoredPosition"); ls = tf.get("m_LocalScale", {"x":1,"y":1}); sd = tf.get("m_SizeDelta", {"x":0,"y":0})
        lx = ap["x"] if ap is not None else lp["x"]; ly = ap["y"] if ap is not None else lp["y"]
        if depth == 0: lx, ly = 0.0, 0.0
        nx, ny = wx + lx * wsx, wy + ly * wsy; nsx, nsy = wsx * ls["x"], wsy * ls["y"]
        if has_img:
            print(f"  img {go['m_Name']:15s} {img_type} c=({nx:6.1f},{ny:6.1f}) sz=({sd['x']*nsx:6.1f}x{sd['y']*nsy:6.1f})")
        for ch in tf.get("m_Children", []):
            ct = objs.get(ch["m_PathID"])
            if ct: walk_imgs(ct.read_typetree()["m_GameObject"]["m_PathID"], nx, ny, nsx, nsy, depth+1)
    walk_imgs(gid)
