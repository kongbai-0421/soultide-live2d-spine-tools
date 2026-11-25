import io
import json
import re
import struct
from pathlib import Path
import UnityPy

cdn = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")
dec = Path(r"D:\A灵魂潮汐-本地化\服务器\analysis\luajit-pipeline\baseline-20260813\decompiled-x64")

def load_ab(p: Path):
    raw = p.read_bytes()
    return UnityPy.load(io.BytesIO(raw[6:] if raw.startswith(b"iqigam") else raw))

print("=== 1. SkeletonDataAsset & DressSpine Aurora_S4 Prefabs ===", flush=True)
ap_env = load_ab(cdn / "03_prefabs/art_prefabs.ab")
for obj in ap_env.objects:
    if obj.type.name == "GameObject":
        d = obj.read()
        if "SoulDress_Aurora" in d.m_Name:
            for cp in d.m_Components:
                if cp.type.name == "RectTransform" or cp.type.name == "Transform":
                    c = cp.read()
                    sc = c.m_LocalScale
                    pos = getattr(c, "m_AnchoredPosition", None) or c.m_LocalPosition
                    print(f"  Prefab {d.m_Name}: pos=({pos.x:.2f},{pos.y:.2f}) scale=({sc.x:.4f},{sc.y:.4f},{sc.z:.4f})", flush=True)

b4 = load_ab(cdn / "23_spine/dressspine/_batch4.ab")
for obj in b4.objects:
    if obj.type.name == "MonoBehaviour":
        try:
            tt = obj.read_typetree()
            if "skeletonJSON" in tt and "aurora_04" in str(tt.get("m_Name", "")).lower():
                print(f"  SkeletonDataAsset {tt.get('m_Name')}: scale={tt.get('scale')} defaultMix={tt.get('defaultMix')}", flush=True)
        except Exception:
            pass

print("\n=== 2. Check _aurora.ab AudioClip container & names ===", flush=True)
cv_env = load_ab(cdn / "06_sounds/cv/_aurora.ab")
dress_clips = []
for cpath, ptr in sorted((cv_env.container or {}).items()):
    if "dress" in cpath.lower() or "fashion" in cpath.lower() or "marry" in cpath.lower():
        dress_clips.append((cpath, ptr.read().m_Name))
print(f"  container size={len(cv_env.container or {})}, dress/marry clips={len(dress_clips)}:", dress_clips[:20], flush=True)
all_clip_names = [obj.peek_name() for obj in cv_env.objects if obj.type.name == "AudioClip"]
print("  alpha clip names:", sorted([x for x in all_clip_names if not x[0].isdigit()])[:25], flush=True)
print("  aurora_dress3 clips:", sorted([x for x in all_clip_names if "dress" in x.lower()])[:30], flush=True)

print("\n=== 3. Check CfgSoulActionTypeTable full ===", flush=True)
print((dec / "CfgSoulActionTypeTable.lua").read_text(encoding="utf-8", errors="ignore"), flush=True)

print("\n=== 4. Check aurora.moc3 Drawable IDs vs Part IDs ===", flush=True)
b35 = load_ab(cdn / "20_live2d/live2d_resources/batch35.ab")
for cpath, ptr in (b35.container or {}).items():
    if "aurora_s4" in cpath.lower() and cpath.endswith("aurora.asset"):
        mb = bytes(ptr.read_typetree()["_bytes"])
        # Parse .moc3 header (version, little endian)
        # In .moc3, offset 64 has Section Offset Table (first table is CountInfo, Drawables, etc.)
        # Let's extract all ASCII strings and check positions of DREFTouchBox* vs ArtMesh* vs Param*
        for kw in ("DREFTouchBox", "L_Foot", "R_Foot", "Body", "L_Hand", "Rhand", "Ru1", "Ru2"):
            matches = sorted(set(s.decode("ascii") for s in re.findall(rf"{kw}[A-Za-z0-9_]*".encode(), mb)))
            print(f"  [{kw}]: {matches[:20]}", flush=True)

print("\n=== 5. Search backup folder for any Submodel examples ===", flush=True)
bak = Path(r"E:\A灵魂潮汐\备份")
for cfg in list(bak.rglob("*.model3.json")) + list(bak.rglob("*.config.json")):
    txt = cfg.read_text(encoding="utf-8", errors="ignore")
    if "submodel" in txt.lower() or "add_submodel" in txt.lower() or "start_mtn" in txt.lower():
        print("  Found in backup:", cfg, flush=True)
