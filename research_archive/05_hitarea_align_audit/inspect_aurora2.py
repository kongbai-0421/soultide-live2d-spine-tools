import io
import json
import re
from pathlib import Path
import UnityPy

cdn = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")

def load_ab(path: Path):
    raw = path.read_bytes()
    return UnityPy.load(io.BytesIO(raw[6:] if raw.startswith(b"iqigam") else raw))

print("=== 1. art_prefabs.ab typetree inspection ===", flush=True)
ap_env = load_ab(cdn / "03_prefabs/art_prefabs.ab")
ext_refs = {}  # cab -> list of (prefab, go, field, pid)

for obj in ap_env.objects:
    if obj.type.name != "GameObject":
        continue
    d = obj.read()
    if d.m_Name not in ("Aurora_S4_Background", "Aurora_S4_Background_chat", "Aurora_S4_Background_touch1"):
        continue
    root_name = d.m_Name
    print(f"\n--- {root_name} ---", flush=True)
    def walk(go_pptr, depth=0):
        go = go_pptr.read()
        af = go.assets_file
        rt_str = ""
        children = []
        notes = []
        for cp in go.m_Components:
            ct = cp.type.name
            if ct in ("RectTransform", "Transform"):
                c = cp.read()
                pos = getattr(c, "m_AnchoredPosition", None) or getattr(c, "m_LocalPosition", None)
                sd = getattr(c, "m_SizeDelta", None)
                sc = getattr(c, "m_LocalScale", None)
                anc_min = getattr(c, "m_AnchorMin", None)
                anc_max = getattr(c, "m_AnchorMax", None)
                piv = getattr(c, "m_Pivot", None)
                rt_str = f"pos=({pos.x:.2f},{pos.y:.2f})"
                if sd:
                    rt_str += f" size=({sd.x:.1f},{sd.y:.1f})"
                if anc_min and anc_max:
                    rt_str += f" anc=({anc_min.x:.2f},{anc_min.y:.2f})-({anc_max.x:.2f},{anc_max.y:.2f})"
                if piv:
                    rt_str += f" piv=({piv.x:.2f},{piv.y:.2f})"
                rt_str += f" scale=({sc.x:.2f},{sc.y:.2f},{sc.z:.2f})"
                children = c.m_Children
            elif ct in ("MonoBehaviour", "ParticleSystemRenderer", "ParticleSystem"):
                try:
                    tt = cp.read_typetree()
                except Exception as e:
                    notes.append(f"{ct}_tt_err({e})")
                    continue
                if ct == "MonoBehaviour":
                    for k in ("m_Sprite", "m_Texture", "m_Color", "m_PreserveAspect", "m_Enabled", "skeletonDataAsset", "startingAnimation", "_animationName", "startingLoop", "m_Order", "order"):
                        if k in tt:
                            v = tt[k]
                            if isinstance(v, dict) and "m_FileID" in v and "m_PathID" in v:
                                fid, pid = v["m_FileID"], v["m_PathID"]
                                if pid != 0:
                                    if fid == 0:
                                        notes.append(f"{k}=self:{pid}")
                                    else:
                                        ep = af.externals[fid - 1].path
                                        m = re.search(r"(CAB-[0-9a-f]+)", ep)
                                        cab = m.group(1) if m else ep
                                        ext_refs.setdefault(cab, []).append((root_name, go.m_Name, k, pid))
                                        notes.append(f"{k}={cab}:{pid}")
                            else:
                                notes.append(f"{k}={v}")
                elif ct == "ParticleSystem":
                    notes.append(
                        f"PS(dur={tt.get('lengthInSec'):.2f},loop={tt.get('looping')},"
                        f"startDelay={tt.get('startDelay',{}).get('scalar')},"
                        f"maxP={tt.get('InitialModule',{}).get('maxNumParticles')})"
                    )
                elif ct == "ParticleSystemRenderer":
                    mats = tt.get("m_Materials", [])
                    minfo = []
                    for m in mats:
                        fid, pid = m.get("m_FileID", 0), m.get("m_PathID", 0)
                        if fid == 0 and pid in af.objects:
                            mo = af.objects[pid].read_typetree()
                            shader_p = mo.get("m_Shader", {})
                            texs = []
                            for tk, tv in mo.get("m_SavedProperties", {}).get("m_TexEnvs", []):
                                tp = tv.get("m_Texture", {})
                                tf, tpid = tp.get("m_FileID", 0), tp.get("m_PathID", 0)
                                if tpid != 0:
                                    if tf == 0 and tpid in af.objects:
                                        tn = af.objects[tpid].read().m_Name
                                    elif tf > 0:
                                        ep = af.externals[tf - 1].path
                                        mc = re.search(r"(CAB-[0-9a-f]+)", ep)
                                        cab = mc.group(1) if mc else ep
                                        ext_refs.setdefault(cab, []).append((root_name, go.m_Name, f"mat.{tk}", tpid))
                                        tn = f"{cab}:{tpid}"
                                    else:
                                        tn = f"self:{tpid}"
                                    texs.append(f"{tk}={tn}")
                            cols = [f"{ck}=({cv.get('r'):.2f},{cv.get('g'):.2f},{cv.get('b'):.2f},{cv.get('a'):.2f})"
                                    for ck, cv in mo.get("m_SavedProperties", {}).get("m_Colors", [])]
                            minfo.append(f"{mo.get('m_Name')}[{','.join(texs)}|{','.join(cols[:2])}]")
                        elif fid > 0 and pid != 0:
                            ep = af.externals[fid - 1].path
                            mc = re.search(r"(CAB-[0-9a-f]+)", ep)
                            cab = mc.group(1) if mc else ep
                            ext_refs.setdefault(cab, []).append((root_name, go.m_Name, "mat", pid))
                            minfo.append(f"ext:{cab}:{pid}")
                    notes.append("PSR=" + ";".join(minfo))
        print("  " * depth + f"{go.m_Name} [{rt_str}] {' | '.join(notes)}", flush=True)
        for ch in children:
            walk(ch.read().m_GameObject, depth + 1)
    walk(obj)

print("\n=== External CAB refs ===", flush=True)
for cab, items in ext_refs.items():
    print(f"  {cab}: {items}", flush=True)

print("\n=== 2. Fast targeted CAB scan ===", flush=True)
cand_files = (
    list((cdn / "05_images/image_resources/dress_bg").rglob("*.ab"))
    + [cdn / "05_images/image_resources/_dress_bg.ab"]
    + list((cdn / "14_effect").rglob("*.ab"))
    + list((cdn / "23_spine/dressspine").rglob("*.ab"))
    + list((cdn / "common").rglob("*.ab"))
    + list((cdn / "03_prefabs").rglob("*.ab"))
)
found_cabs = {}
for abp in cand_files:
    if not abp.exists():
        continue
    try:
        env = load_ab(abp)
        for fname in env.files.keys():
            for cab in ext_refs.keys():
                if cab in fname:
                    found_cabs[cab] = abp
                    print(f"  FOUND {cab} in {abp.relative_to(cdn)} ({fname})", flush=True)
    except Exception:
        pass

for cab, abp in found_cabs.items():
    env = load_ab(abp)
    print(f"\n  Inspecting {cab} inside {abp.relative_to(cdn)}:", flush=True)
    for fname, fobj in env.files.items():
        if hasattr(fobj, "objects") and cab in fname:
            for rname, gname, fld, pid in ext_refs[cab]:
                if pid in fobj.objects:
                    o = fobj.objects[pid].read()
                    otype = fobj.objects[pid].type.name
                    oname = getattr(o, "m_Name", otype)
                    detail = ""
                    if otype == "Sprite":
                        r = o.m_Rect
                        tex_ptr = o.m_RD.texture
                        detail = f"rect=({r.x},{r.y},{r.width},{r.height}) tex=fid{tex_ptr.file_id}:pid{tex_ptr.path_id}"
                    elif otype == "Texture2D":
                        detail = f"{o.m_Width}x{o.m_Height} fmt={o.m_TextureFormat}"
                    elif otype == "MonoBehaviour":
                        try:
                            tt = fobj.objects[pid].read_typetree()
                            detail = f"keys={list(tt.keys())[:10]} skel={tt.get('skeletonJSON')}"
                        except Exception:
                            pass
                    print(f"    [{rname}/{gname}.{fld}] pid={pid} {otype} '{oname}' {detail}", flush=True)

print("\n=== 3. batch35 aurora_s4 Drawables & scripts ===", flush=True)
b35 = load_ab(cdn / "20_live2d/live2d_resources/batch35.ab")
for cpath, ptr in (b35.container or {}).items():
    if "aurora_s4" in cpath.lower() and cpath.endswith(".prefab"):
        go = ptr.read()
        script_counts = {}
        drawable_names = []
        def walk_p(g):
            children = []
            scr_names = []
            for cp in g.m_Components:
                if cp.type.name == "MonoBehaviour":
                    c = cp.read()
                    try:
                        sn = c.m_Script.read().m_ClassName or c.m_Script.read().m_Name
                    except Exception:
                        sn = "?"
                    scr_names.append(sn)
                    script_counts[sn] = script_counts.get(sn, 0) + 1
                elif cp.type.name == "Transform":
                    children = [ch.read().m_GameObject.read() for ch in cp.read().m_Children]
            if any("Renderer" in s or "Drawable" in s for s in scr_names):
                drawable_names.append(g.m_Name)
            for ch in children:
                walk_p(ch)
        walk_p(go)
        print("  script counts:", script_counts, flush=True)
        print("  drawable GOs count:", len(drawable_names), "sample:", drawable_names[:20], flush=True)
        for kw in ("tou", "head", "hair", "hand", "foot", "ru", "bra", "body", "ring", "xianglian", "l_foot", "r_foot", "lhand", "rhand"):
            m = [x for x in drawable_names if kw in x.lower()]
            if m:
                print(f"    match[{kw}]: {m[:10]}", flush=True)
    elif "aurora_s4" in cpath.lower() and cpath.endswith("model3.json"):
        print("  official aurora.model3.json:", ptr.read().m_Script[:600], flush=True)

print("\n=== 4. _batch4 souldress_aurora_04 .skel strings ===", flush=True)
b4 = load_ab(cdn / "23_spine/dressspine/_batch4.ab")
for cpath, ptr in (b4.container or {}).items():
    if "aurora_04" in cpath.lower() and cpath.endswith(".skel.bytes"):
        ta = ptr.read()
        raw_bytes = bytes(ta.script)
        strs = re.findall(rb"[ -~]{3,}", raw_bytes)
        dec = [s.decode("ascii", "ignore") for s in strs]
        anims = [s for s in dec if any(k in s.lower() for k in ("idle", "chat", "greet", "touch", "marry", "loop", "anim"))]
        nums = [s for s in dec if s in ("47", "113", "321", "83", "88", "84", "87")]
        print(f"  {Path(cpath).name}: len={len(raw_bytes)} ver_strs={dec[:5]} anims={sorted(set(anims))} hit_nums={nums}", flush=True)
