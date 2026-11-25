import io
import json
import os
import re
from pathlib import Path
import UnityPy

cdn = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")

def load_ab(path: Path):
    raw = path.read_bytes()
    return UnityPy.load(io.BytesIO(raw[6:] if raw.startswith(b"iqigam") else raw))

print("=== 1. Inspecting 03_prefabs/art_prefabs.ab for Aurora_S4_Background* ===")
ap_env = load_ab(cdn / "03_prefabs/art_prefabs.ab")
target_cabs = {}

for obj in ap_env.objects:
    if obj.type.name != "GameObject":
        continue
    d = obj.read()
    if d.m_Name not in ("Aurora_S4_Background", "Aurora_S4_Background_chat", "Aurora_S4_Background_touch1"):
        continue
    print(f"\n--- Prefab {d.m_Name} (af={obj.assets_file.name}) ---")
    def dump_go(go_pptr, depth=0):
        go = go_pptr.read()
        af = go.assets_file
        rt_info = ""
        children = []
        comps = []
        for cp in go.m_Components:
            c = cp.read()
            ct = cp.type.name
            if ct in ("RectTransform", "Transform"):
                pos = getattr(c, "m_AnchoredPosition", None) or getattr(c, "m_LocalPosition", None)
                sd = getattr(c, "m_SizeDelta", None)
                sc = getattr(c, "m_LocalScale", None)
                rt_info = f"pos=({pos.x:.2f},{pos.y:.2f})"
                if sd:
                    rt_info += f" size=({sd.x:.1f},{sd.y:.1f})"
                if sc:
                    rt_info += f" scale=({sc.x:.2f},{sc.y:.2f},{sc.z:.2f})"
                children = c.m_Children
            elif ct == "MonoBehaviour":
                try:
                    tt = c.read_typetree()
                    info = []
                    for k in ("m_Sprite", "m_Color", "skeletonDataAsset", "_animationName", "startingAnimation", "m_Order", "order", "loop"):
                        if k in tt:
                            v = tt[k]
                            if isinstance(v, dict) and "m_FileID" in v and "m_PathID" in v:
                                fid, pid = v["m_FileID"], v["m_PathID"]
                                ext_name = af.externals[fid - 1].path if 0 < fid <= len(af.externals) else "self"
                                if pid != 0:
                                    target_cabs.setdefault(ext_name, []).append((go.m_Name, k, pid))
                                info.append(f"{k}=(fid={fid},pid={pid})")
                            else:
                                info.append(f"{k}={v}")
                    if info:
                        comps.append("MB{" + ", ".join(info) + "}")
                except Exception as e:
                    comps.append(f"MB_err({e})")
            elif ct == "ParticleSystemRenderer":
                try:
                    tt = c.read_typetree()
                    mats = tt.get("m_Materials", [])
                    mat_info = []
                    for m in mats:
                        fid, pid = m.get("m_FileID", 0), m.get("m_PathID", 0)
                        if fid == 0 and pid != 0 and pid in af.objects:
                            mo = af.objects[pid].read_typetree()
                            texs = []
                            for tk, tv in mo.get("m_SavedProperties", {}).get("m_TexEnvs", []):
                                tp = tv.get("m_Texture", {})
                                tf, tpid = tp.get("m_FileID", 0), tp.get("m_PathID", 0)
                                tex_name = "none"
                                if tf == 0 and tpid != 0 and tpid in af.objects:
                                    tex_name = af.objects[tpid].read().m_Name
                                elif tf > 0 and tpid != 0:
                                    ext_name = af.externals[tf - 1].path
                                    target_cabs.setdefault(ext_name, []).append((go.m_Name, tk, tpid))
                                    tex_name = f"ext{tf}:{tpid}"
                                texs.append(f"{tk}={tex_name}")
                            mat_info.append(f"{mo.get('m_Name')}({','.join(texs)})")
                        elif fid > 0 and pid != 0:
                            ext_name = af.externals[fid - 1].path
                            target_cabs.setdefault(ext_name, []).append((go.m_Name, "mat", pid))
                            mat_info.append(f"ext{fid}:{pid}")
                    comps.append("PSR[" + "; ".join(mat_info) + "]")
                except Exception as e:
                    comps.append(f"PSR_err({e})")
        print("  " * depth + f"- {go.m_Name} [{rt_info}] {' '.join(comps)}")
        for ch in children:
            dump_go(ch.read().m_GameObject, depth + 1)
    dump_go(obj)

print("\n=== External CABs needed ===")
needed_cab_keys = set()
for ext_path, refs in target_cabs.items():
    m = re.search(r"(CAB-[0-9a-f]+)", ext_path)
    cab = m.group(1) if m else ext_path
    needed_cab_keys.add(cab)
    print(f"  {cab} ({ext_path}) -> {refs}")

print("\n=== 2. Searching bundles for needed CABs ===")
search_files = []
for sub in ("05_images/image_resources", "14_effect", "03_prefabs", "common", "04_models"):
    p = cdn / sub
    if p.exists():
        search_files += list(p.rglob("*.ab"))
for abp in (cdn / "05_images").rglob("*.ab"):
    if abp not in search_files:
        search_files.append(abp)

print(f"Scanning {len(search_files)} .ab files...")
cab_to_bundle = {}
for abp in search_files:
    try:
        env = load_ab(abp)
        for name in env.files.keys():
            for cab in needed_cab_keys:
                if cab in name:
                    cab_to_bundle.setdefault(cab, []).append(str(abp.relative_to(cdn)))
    except Exception:
        pass

for cab, locs in cab_to_bundle.items():
    print(f"  MATCH {cab} -> {locs}")
    # Inspect referenced PathIDs inside matched bundle!
    abp = cdn / locs[0]
    env = load_ab(abp)
    for ext_path, refs in target_cabs.items():
        if cab in ext_path:
            # Find matching cab serialized file
            for fname, fobj in env.files.items():
                if hasattr(fobj, "objects"):
                    for go_name, kind, pid in refs:
                        if pid in fobj.objects:
                            o = fobj.objects[pid].read()
                            oname = getattr(o, "m_Name", type(o).__name__)
                            extra = ""
                            if fobj.objects[pid].type.name == "Sprite":
                                r = o.m_Rect
                                extra = f"rect=({r.x},{r.y},{r.width},{r.height}) tex_pid={o.m_RD.texture.path_id}"
                            elif fobj.objects[pid].type.name == "Texture2D":
                                extra = f"size={o.m_Width}x{o.m_Height}"
                            print(f"    [{go_name}.{kind}] pid={pid} type={fobj.objects[pid].type.name} name={oname} {extra}")

print("\n=== 3. Inspecting batch35.ab aurora_s4 Live2D ===")
b35 = load_ab(cdn / "20_live2d/live2d_resources/batch35.ab")
motions = []
parts = []
drawables = []
params = []
other_aurora_s4 = []
for obj in b35.objects:
    d = obj.read()
    name = getattr(d, "m_Name", "")
    # Check container/path or name
    if obj.type.name == "TextAsset" and obj.peek_name().endswith(".motion3"):
        motions.append(obj.peek_name())
for cpath, ptr in (b35.container or {}).items():
    if "aurora_s4" in cpath.lower():
        if cpath.endswith(".motion3.json"):
            motions.append(cpath)
        else:
            other_aurora_s4.append((cpath, ptr.type.name))
print("  aurora_s4 non-motion container entries:", other_aurora_s4[:20])
print(f"  aurora_s4 motions in container ({len([m for m in motions if 'aurora_s4' in str(m)])}):")
s4_mots = sorted([m for m in motions if "aurora_s4" in str(m)])
print("   sample:", [Path(m).name for m in s4_mots[:15]])

# Inspect aurora_s4 prefab GameObjects to distinguish Drawable vs Part vs Parameter
for cpath, ptr in (b35.container or {}).items():
    if "aurora_s4" in cpath.lower() and cpath.endswith(".prefab"):
        print("  Found prefab:", cpath)
        go = ptr.read()
        def walk_l2d(go_obj, depth=0):
            comp_types = [cp.type.name for cp in go_obj.m_Components]
            scripts = []
            for cp in go_obj.m_Components:
                if cp.type.name == "MonoBehaviour":
                    c = cp.read()
                    try:
                        sc = c.m_Script.read()
                        scripts.append(sc.m_ClassName or sc.m_Name)
                    except Exception:
                        scripts.append("MB")
                if cp.type.name in ("Transform", "RectTransform"):
                    tr = cp.read()
                    children = [ch.read().m_GameObject.read() for ch in tr.m_Children]
            s_str = ",".join(scripts)
            if "CubismDrawable" in s_str:
                drawables.append(go_obj.m_Name)
            elif "CubismPart" in s_str:
                parts.append(go_obj.m_Name)
            elif "CubismParameter" in s_str:
                params.append(go_obj.m_Name)
            for ch in children:
                walk_l2d(ch, depth + 1)
        walk_l2d(go)
print(f"  CubismDrawable count={len(drawables)} sample={drawables[:25]}")
print(f"  CubismPart count={len(parts)} sample={parts[:25]}")
print(f"  CubismParameter count={len(params)} sample={params[:15]}")
print("  Matching foot/hand/head/chest/ring in drawables:")
for kw in ("head", "tou", "face", "hair", "hand", "shou", "chest", "xiong", "ru", "bra", "foot", "zu", "leg", "tui", "arm", "body", "ring", "jie"):
    m = [x for x in drawables if kw in x.lower()]
    if m:
        print(f"    drawable[{kw}]: {m[:12]}")

print("\n=== 4. Inspecting _batch4.ab souldress_aurora_04 Spine ===")
b4 = load_ab(cdn / "23_spine/dressspine/_batch4.ab")
for cpath, ptr in (b4.container or {}).items():
    if "aurora_04" in cpath.lower():
        print(" ", cpath, ptr.type.name)
        if cpath.endswith(".skel.bytes"):
            raw_skel = ptr.read().m_Script.encode("latin1") if isinstance(ptr.read().m_Script, str) else bytes(ptr.read().script)
            print(f"    skel len={len(raw_skel)} head={raw_skel[:30]}")
            # ASCII strings in binary skel (often includes version, animations, skins, slots)
            strs = re.findall(rb"[A-Za-z0-9_./-]{3,}", raw_skel)
            dec = [s.decode("ascii", "ignore") for s in strs]
            print("    skel strings head:", dec[:15])
            anims = [s for s in dec if any(k in s.lower() for k in ("idle", "chat", "greet", "touch", "marry", "loop", "anim"))]
            print("    skel anim-like strings:", sorted(set(anims)))
        elif cpath.endswith(".atlas.txt"):
            txt = ptr.read().m_Script
            print("    atlas head:", txt[:200].replace("\n", " | "))
