import json, sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

idx = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
cat = bfe.build_skin_catalog(repo)
by_sk = {r["skin_key"]: r for r in cat}

# Check 402_Freesia_S5 Image sizes & positions in Background prefab to see why cam=(-319,-275) happened!
# Wait: earlier walk_img skipped Sprite lookup or Image because Freesia_S5 used a different component? Let's inspect components of Image_02, Image_12, Image_15 in Freesia_S5_Background!
for k, pid in idx.art_container.items():
    if "freesia_s5_background" in k.lower():
        co = idx.art_objs[pid].read_typetree()
        gpid = co["m_GameObject"]["m_PathID"] if "m_GameObject" in co else pid
        print("=== Freesia_S5_Background Children & Components ===")
        def walk(gp, depth=0):
            go = idx.art_objs[gp].read_typetree()
            tf = None
            comps = []
            for c in go.get("m_Component", []):
                o = idx.art_objs.get(c["component"]["m_PathID"])
                if not o: continue
                comps.append(o.type.name)
                if o.type.name in ("Transform", "RectTransform"):
                    tf = o.read_typetree()
            ap = tf.get("m_AnchoredPosition") if tf else None
            sd = tf.get("m_SizeDelta") if tf else None
            print("  "*depth + f"{go.get('m_Name')} {comps} ap={ap} sd={sd}")
            if tf:
                for ch in tf.get("m_Children", []):
                    ct = idx.art_objs.get(ch["m_PathID"])
                    if ct: walk(ct.read_typetree()["m_GameObject"]["m_PathID"], depth+1)
        walk(gpid)

# Also check 5101_Louisa_S2, 1803_SakuyaMako_S4, 404_Freesia_S6, 702_Minerdwen_S3, 4801_Micha_S2 in manifest
m = json.loads(Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json").read_text(encoding="utf-8"))
by_m = {s["skin_key"]: s for s in m["skins"]}
for sk in ("402_Freesia_S5", "404_Freesia_S6", "702_Minerdwen_S3", "1803_SakuyaMako_S4", "4501_RubyRose_S2", "4801_Micha_S2", "5101_Louisa_S2", "503_Benten_S4"):
    s = by_m[sk]
    print(f"\n=== MANIFEST {sk} cam=({s['cam_x']},{s['cam_y']}) canvas=({s['canvas_w']}x{s['canvas_h']}) ===")
    for c in s["clips"]:
        if c["clip"].startswith("fx_") or sk == "503_Benten_S4":
            print(f"  clip={c['clip']}:")
            for n in c["nodes"]:
                sz = (n["sizeX"]["scalar"], n["sizeY"]["scalar"]) if n["size3D"] else (n["size"]["scalar"], n["size"]["scalar"])
                px_x = sz[0] * abs(n["world_scale"][0])
                px_y = sz[1] * abs(n["world_scale"][1])
                print(f"    {n['name']:18s} sm={n['scalingMode']} wpos=({n['world_pos'][0]:.1f},{n['world_pos'][1]:.1f},{n['world_pos'][2]:.1f}) wsc=({n['world_scale'][0]:.2f},{n['world_scale'][2]:.2f}) wrot={[round(x,2) for x in n['world_rot']]} est_px=({px_x:.0f}x{px_y:.0f}) maxP={n['maxParticles']} tex={n['texName']}")
