import io
import json
import re
import struct
from pathlib import Path
import UnityPy

cdn = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")

def load_ab(path: Path):
    raw = path.read_bytes()
    return UnityPy.load(io.BytesIO(raw[6:] if raw.startswith(b"iqigam") else raw))

print("=== 1. Query assetMap.clv ===", flush=True)
am_lines = (cdn / "assetMap.clv").read_text(encoding="utf-8-sig", errors="ignore").splitlines()
for line in am_lines:
    low = line.lower()
    if "aurora_s4" in low or "souldress_aurora_04" in low or "live2d_aurora_s4" in low:
        parts = line.split("\t")
        if not parts[0].endswith((".anim", ".mat", ".png", ".motion3.json")):
            print(" ", parts[0], "->", parts[1], "| dep_ab:", parts[4] if len(parts) > 4 else "", flush=True)

# Grab DepAbList specifically for Aurora_S4_Background, chat, touch1
dep_abs = set()
for line in am_lines:
    parts = line.split("\t")
    if any(x in parts[0] for x in ("Aurora_S4_Background.prefab", "Aurora_S4_Background_chat.prefab", "Aurora_S4_Background_touch1.prefab")):
        print(f"\nFOUND TARGET: {parts[0]} -> {parts[1]}", flush=True)
        print(f"  DependenceList: {parts[3] if len(parts)>3 else ''}", flush=True)
        print(f"  DepAbList: {parts[4] if len(parts)>4 else ''}", flush=True)
        if len(parts) > 3:
            for d in parts[3].split(","):
                if d.strip():
                    print(f"    dep asset: {d.strip()}", flush=True)
        if len(parts) > 4:
            for d in parts[4].split(","):
                if d.strip():
                    dep_abs.add(d.strip())

# Lookup dep assets in assetMap too
dep_ab_to_assets = {}
for line in am_lines:
    parts = line.split("\t")
    if len(parts) >= 2 and parts[1] in dep_abs:
        if "aurora" in parts[0].lower() or parts[1] not in ("15_shader/15_shader_base.ab", "03_prefabs/art_prefabs.ab", "05_images/common.ab"):
            dep_ab_to_assets.setdefault(parts[1], []).append(parts[0])
print("\n=== DepAbList bundles & matching assets ===", flush=True)
for ab in sorted(dep_abs):
    assets = dep_ab_to_assets.get(ab, [])
    print(f"  {ab} (sample={assets[:8]})", flush=True)

print("\n=== 2. Inspect aurora.asset (moc3) in batch35.ab ===", flush=True)
b35 = load_ab(cdn / "20_live2d/live2d_resources/batch35.ab")
for cpath, ptr in (b35.container or {}).items():
    if "aurora_s4" in cpath.lower() and cpath.endswith("aurora.asset"):
        tt = ptr.read_typetree()
        print("  aurora.asset keys:", list(tt.keys()), flush=True)
        m_bytes = bytes(tt["_bytes"]) if "_bytes" in tt else b""
        print("  _bytes len:", len(m_bytes), "magic:", m_bytes[:16], flush=True)
        # Extract printable ASCII IDs inside .moc3
        # Check ASCII strings in .moc3 (ArtMesh/D_...)
        strs = re.findall(rb"[A-Za-z0-9_.\-]{3,}", m_bytes)
        dec = [s.decode("ascii", "ignore") for s in strs]
        print("  moc3 ASCII strings total:", len(dec), "tail/sample:", dec[-40:], flush=True)
        for kw in ("artmesh", "hand", "foot", "head", "tou", "body", "bra", "ru", "chest", "arm", "leg", "tui", "ring", "xianglian"):
            m = [x for x in dec if kw in x.lower()]
            if m:
                print(f"    moc3[{kw}]: {sorted(set(m))[:12]}", flush=True)
    elif "aurora_s4" in cpath.lower() and cpath.endswith("aurora.prefab"):
        # Check CubismRendererCombine or CubismDrawable typetree
        go = ptr.read()
        for cp in go.m_Components:
            if cp.type.name == "MonoBehaviour":
                try:
                    tt = cp.read_typetree()
                    if "Drawables" in tt or "_drawables" in tt or "Renderers" in tt or "m_GameObjects" in tt:
                        print("  prefab MB keys:", list(tt.keys()), flush=True)
                except Exception:
                    pass

print("\n=== 3. Inspect _batch4.ab souldress_aurora_04 .skel.bytes ===", flush=True)
b4 = load_ab(cdn / "23_spine/dressspine/_batch4.ab")
for cpath, ptr in (b4.container or {}).items():
    if "aurora_04" in cpath.lower() and cpath.endswith(".skel.bytes"):
        ta = ptr.read()
        raw_bytes = ta.m_Script.encode("utf-8", "surrogateescape")
        # Compare with raw_data after 4-byte name + aligned bytes just in case
        strs = re.findall(rb"[ -~]{2,}", raw_bytes)
        dec = [s.decode("ascii", "ignore") for s in strs]
        anims = [s for s in dec if any(k in s.lower() for k in ("idle", "chat", "greet", "touch", "marry", "loop"))]
        nums = sorted(set(s for s in dec if s in ("47", "113", "321", "83", "88", "84", "87")))
        print(f"  {Path(cpath).name}: len={len(raw_bytes)} ver={dec[:3]} anims={sorted(set(anims))} hit_nums={nums}", flush=True)
