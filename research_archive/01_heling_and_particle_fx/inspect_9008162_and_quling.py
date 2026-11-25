import sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as b

idx = b.AssetIndexer()
repo = b.FullI18nRepo()
skins = b.build_skin_catalog(repo)
by_key = {s["skin_key"]: s for s in skins}

def dump_go_tree(objs, gid, d=0):
    go = objs[gid].read()
    rt = None
    for c in go.m_Component:
        co = objs.get(c.component.path_id)
        if co and co.type.name in ("Transform", "RectTransform"):
            rt = co.read()
            p, s, r = rt.m_LocalPosition, rt.m_LocalScale, rt.m_LocalRotation
            ap = getattr(rt, "m_AnchoredPosition", None)
            print("  " * d + f"[{go.m_IsActive}] {go.m_Name} lp=({p.x:.3f},{p.y:.3f},{p.z:.3f}) ls=({s.x:.4f},{s.y:.4f},{s.z:.4f}) lr=({r.x:.4f},{r.y:.4f},{r.z:.4f},{r.w:.4f})" + (f" ap=({ap.x:.3f},{ap.y:.3f})" if ap else ""))
    if rt:
        for ch in rt.m_Children:
            cobj = objs.get(ch.path_id)
            if cobj:
                cgid = cobj.read().m_GameObject.path_id
                if cgid in objs:
                    dump_go_tree(objs, cgid, d + 1)

print("=== 702_Minerdwen_S3 effect 9008162 ===")
for k, gids in idx.art_go_by_name.items():
    if "minerdwen_s3_background" in k or "minerdwen" in k and "fx_" in k:
        print("KEY:", k, gids)
        for g in gids:
            dump_go_tree(idx.art_objs, g)

print("\n=== ALL SKINS WITH STRETCHED BILLBOARD (rm==1) & LOW SPEED IN pilot_manifest ===")
import json
pm = json.loads((b.UNITY_PROJ / "pilot_manifest.json").read_text(encoding="utf-8"))
for s in pm["skins"]:
    for c in s["clips"]:
        for n in c["nodes"]:
            if n.get("renderMode") == 1 or s["skin_key"] == "2301_QuLing_S2":
                print(s["skin_key"], c["clip"], n["name"], "rm=", n.get("renderMode"), "align=", n.get("renderAlignment"),
                      "wscale=", n.get("world_scale"), "wrot=", [round(x,3) for x in n.get("world_rot",[])],
                      "spd=", n.get("speed",{}).get("scalar"), "minSpd=", n.get("speed",{}).get("minScalar"),
                      "vScale=", n.get("velocityScale"), "lenScale=", n.get("lengthScale"),
                      "sz=", n.get("size",{}).get("scalar"), "sm=", n.get("scalingMode"),
                      "tint=", n.get("tint"), "mul=", n.get("tintMultiplier"),
                      "uvScroll=", n.get("uvScroll"), "distort=", n.get("distortTexName"), n.get("distortStrength"))

print("\n=== CHECK ORIGINAL MATERIAL FOR 2301_QuLing_S2 water ===")
bgp = Path(by_key["2301_QuLing_S2"]["bg_prefab"]).name.lower()
objs = idx.ui_objs if bgp in idx.ui_go_by_name else idx.art_objs
for gid in (idx.ui_go_by_name.get(bgp) or idx.art_go_by_name.get(bgp)):
    def find_water(g):
        go = objs[g].read()
        if go.m_Name == "water":
            for c in go.m_Component:
                co = objs.get(c.component.path_id)
                if co and co.type.name == "ParticleSystemRenderer":
                    psr = co.read_typetree()
                    print("water PSR keys:", {k: psr.get(k) for k in ("m_RenderMode","m_VelocityScale","m_LengthScale","m_CameraVelocityScale","m_NormalDirection","m_Alignment","m_Pivot","m_SortMode","m_SortingOrder","m_MaxParticleSize","m_MinParticleSize","m_AllowRoll","m_FreeformStretching","m_RotateWithStretchDirection","m_ShadowCastingMode","m_ReceiveShadows","m_Materials")})
                    for mp in psr.get("m_Materials", []):
                        mo = objs.get(mp["m_PathID"]) or idx.art_objs.get(mp["m_PathID"])
                        if mo:
                            mt = mo.read_typetree()
                            sh = idx.art_objs.get(mt["m_Shader"]["m_PathID"]) or idx.shader_objs.get(mt["m_Shader"]["m_PathID"])
                            sh_name = sh.read().m_ParsedForm.m_Name if sh else "?"
                            print("MAT:", mt.get("m_Name"), "SHADER:", sh_name)
                            sp = mt.get("m_SavedProperties", {})
                            print("  floats:", sp.get("m_Floats"))
                            print("  cols:", sp.get("m_Colors"))
                            print("  texs:", [(k, v.get("m_Scale"), v.get("m_Offset"), v.get("m_Texture")) for k, v in sp.get("m_TexEnvs", [])])
        rt = None
        for c in go.m_Component:
            co = objs.get(c.component.path_id)
            if co and co.type.name in ("Transform", "RectTransform"):
                rt = co.read()
        if rt:
            for ch in rt.m_Children:
                cobj = objs.get(ch.path_id)
                if cobj:
                    cgid = cobj.read().m_GameObject.path_id
                    if cgid in objs:
                        find_water(cgid)
    find_water(gid)
