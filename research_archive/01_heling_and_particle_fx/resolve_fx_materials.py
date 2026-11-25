import sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

# Build lookup of all CAB-*.ab / m_PathID for Materials in 14_effect & 03_prefabs
# Wait: UnityPy maps each AssetBundle's serializedFile name (`CAB-...`)!
cab_to_mat = {}
for ab_dir in [CDN_ROOT / "14_effect", CDN_ROOT / "03_prefabs"]:
    for ab_path in sorted(ab_dir.rglob("*.ab")):
        env = load_ab(ab_path)
        for sf_name, sf in env.files.items():
            # Also check files inside bundleFile
            files = getattr(sf, "files", None)
            sub_files = files.items() if isinstance(files, dict) else [(sf_name, sf)]
            for k, sub in sub_files:
                if k.startswith("CAB-") and hasattr(sub, "objects"):
                    for pid, obj in sub.objects.items():
                        if obj.type.name == "Material":
                            cab_to_mat[(k, pid)] = (ab_path, obj)

print("Indexed materials across 14_effect + 03_prefabs:", len(cab_to_mat))

def inspect_ps_mats(rel, tid, label):
    print(f"\n=== {label} ===")
    env = load_ab(CDN_ROOT / rel)
    obj_by_id = {o.path_id: o for o in env.objects}
    sf = next(o.assets_file for o in env.objects)
    exts = sf.externals
    rid = tid if isinstance(tid, int) else {k.lower(): v.path_id for k, v in env.container.items()}[tid.lower()]

    def w(gid, path=""):
        go = obj_by_id[gid].read()
        cp = f"{path}/{go.m_Name}" if path else go.m_Name
        rt = None
        for c in go.m_Component:
            co = obj_by_id.get(c.component.path_id)
            if not co: continue
            if co.type.name in ("RectTransform", "Transform"): rt = co.read()
            elif co.type.name == "ParticleSystemRenderer":
                psr = co.read_typetree()
                mats = psr.get("m_Materials", [])
                for mref in mats:
                    fid = mref.get("m_FileID", 0)
                    pid = mref.get("m_PathID", 0)
                    mat_tt = None
                    src_ab = rel
                    if fid == 0 and pid in obj_by_id:
                        mat_tt = obj_by_id[pid].read_typetree()
                    elif 1 <= fid <= len(exts):
                        cab = Path(exts[fid - 1].path).name
                        hit = cab_to_mat.get((cab, pid))
                        if hit:
                            src_ab = str(hit[0].relative_to(CDN_ROOT))
                            mat_tt = hit[1].read_typetree()
                    if mat_tt and mat_tt.get("m_Name") != "Default-ParticleSystem":
                        sp = mat_tt.get("m_SavedProperties", {})
                        texs = []
                        for tk, tv in sp.get("m_TexEnvs", []):
                            tref = tv.get("m_Texture", {})
                            tfid, tpid = tref.get("m_FileID", 0), tref.get("m_PathID", 0)
                            # Find tex name in src_ab
                            tn = "?"
                            if tpid != 0:
                                tenv = load_ab(CDN_ROOT / src_ab) if src_ab != rel else env
                                if tfid == 0:
                                    tobj = {o.path_id: o for o in tenv.objects}.get(tpid)
                                    if tobj: tn = tobj.peek_name()
                                else:
                                    t_sf = next(o.assets_file for o in tenv.objects)
                                    tcab = Path(t_sf.externals[tfid - 1].path).name if tfid <= len(t_sf.externals) else ""
                                    tn = f"{tcab}:{tpid}"
                            texs.append((tk, tn, tv.get("m_Scale"), tv.get("m_Offset")))
                        cols = {ck: cv for ck, cv in sp.get("m_Colors", [])}
                        flts = {fk: fv for fk, fv in sp.get("m_Floats", [])}
                        print(f"  [{cp}] ab={src_ab} mat={mat_tt.get('m_Name')} texs={texs} cols={cols} blend=({flts.get('_SrcBlend')},{flts.get('_DstBlend')}) kw={mat_tt.get('m_ShaderKeywords')}")
        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in obj_by_id:
                    w(obj_by_id[ch.path_id].read().m_GameObject.path_id, cp)
    w(rid)

inspect_ps_mats("03_prefabs/ui.ab", 8268094511723853665, "Aurora_S4_Background")
inspect_ps_mats("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_chat.prefab", "chat")
inspect_ps_mats("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab", "touch1")
