import io
import json
import re
from pathlib import Path
import UnityPy

cdn = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")
dec = Path(r"D:\A灵魂潮汐-本地化\服务器\analysis\luajit-pipeline\baseline-20260813\decompiled-x64")

def load_ab(path: Path):
    raw = path.read_bytes()
    return UnityPy.load(io.BytesIO(raw[6:] if raw.startswith(b"iqigam") else raw))

print("=== 1. Dress_BG batch4 & _dress_bg ===", flush=True)
bg4 = load_ab(cdn / "05_images/image_resources/dress_bg/dressbackground/_batch4.ab")
print("  batch4 files:", list(bg4.files.keys()), flush=True)
for cpath, ptr in (bg4.container or {}).items():
    if "aurora" in cpath.lower():
        o = ptr.read()
        info = ""
        if ptr.type.name == "Texture2D":
            info = f"{o.m_Width}x{o.m_Height}"
        elif ptr.type.name == "Sprite":
            r = o.m_Rect
            info = f"rect=({r.x},{r.y},{r.width},{r.height}) tex_pid={o.m_RD.texture.path_id}"
        print(f"    [{ptr.path_id}] {cpath} ({ptr.type.name}) {info}", flush=True)

# Also check SpriteAtlas for Aurora_S4_Background
for obj in bg4.objects:
    if obj.type.name == "SpriteAtlas":
        d = obj.read()
        if "aurora_s4" in d.m_Name.lower():
            print(f"  SpriteAtlas {d.m_Name}: sprites={len(d.m_PackedSprites)} pages={len(d.m_RenderDataMap)}", flush=True)
            for sp_p in d.m_PackedSprites:
                sp = sp_p.read()
                print(f"    packed sprite [{sp_p.path_id}]: {sp.m_Name} rect=({sp.m_Rect.x},{sp.m_Rect.y},{sp.m_Rect.width},{sp.m_Rect.height})", flush=True)

print("\n=== 2. Check target Sprite PathIDs in _batch4.ab ===", flush=True)
target_pids = {
    -6056632675904507404: "Image_01",
    -4340755343210567132: "Image_02",
    1980721262472126212: "Image_03",
    -8448701444043422039: "Image_05",
}
for fname, fobj in bg4.files.items():
    if hasattr(fobj, "objects"):
        for pid, label in target_pids.items():
            if pid in fobj.objects:
                o = fobj.objects[pid].read()
                r = o.m_Rect
                print(f"  {label}: pid={pid} name={o.m_Name} rect=({r.x},{r.y},{r.width},{r.height})", flush=True)

print("\n=== 3. Inspect FX bundles for Particle Materials & Textures ===", flush=True)
fx_bundles = [
    "14_effect/battle/_batch1.ab", "14_effect/battle/_batch2.ab", "14_effect/battle/_batch3.ab",
    "14_effect/battle/_batch4.ab", "14_effect/battle/_batch5.ab", "14_effect/battle/_batch6.ab",
    "14_effect/battle/_batch8.ab", "14_effect/battle/_batch9.ab", "14_effect/battle/_batch10.ab",
    "14_effect/battle/_batch11.ab", "14_effect/battle/_common.ab", "14_effect/battle/_maze.ab",
    "14_effect/ui/batch1.ab", "14_effect/ui/batch2.ab",
]
target_cabs = {
    "cab-f0797fff216ab3076bf8d38f2ec5d697": [("beike", 65754890445359314), ("xianglian", 2331313482108350463), ("FX_glow", 8919695548410932974), ("glow02", 5677564959687805008), ("smoke", 9142306378696600815), ("shan_s", -3013462422272175626)],
    "cab-e181e17c58b0124ff3936c9ef4412f70": [("aixin", -187576216157495043)],
    "cab-0ea714bf4ee4ac80649b8188db7f63f0": [("bao", 8566848586218849390)],
    "cab-63d13e89e78f4f756b98b28ac6bddf7a": [("glow01_t", 4696809865029886123), ("lizi_san", 6717544822340696281), ("glow01_bg1", -6215823799543604914), ("glow01_bg2", -8188828357555011462), ("yinghuochong", 7393461633868356657)],
    "cab-2d893663d14e805cb8884952bccc6d80": [("shan", -7873106136598437370)],
    "cab-dea5ca9badbf69c4684503f73ac215e5": [("stra", -7406617868670641507)],
    "cab-070f7949ccb9c7cfd4871315192a65f8": [("FX_stra", 5893497205202485342)],
}
for rel in fx_bundles:
    abp = cdn / rel
    if not abp.exists():
        continue
    env = load_ab(abp)
    for fname, fobj in env.files.items():
        if not hasattr(fobj, "objects"):
            continue
        low = fname.lower()
        for cab, items in target_cabs.items():
            if cab in low:
                print(f"  CAB {cab} -> {rel} ({fname})", flush=True)
                for lbl, pid in items:
                    if pid in fobj.objects:
                        tt = fobj.objects[pid].read_typetree()
                        texs = []
                        for tk, tv in tt.get("m_SavedProperties", {}).get("m_TexEnvs", []):
                            tp = tv.get("m_Texture", {})
                            tf, tpid = tp.get("m_FileID", 0), tp.get("m_PathID", 0)
                            if tpid != 0:
                                tname = f"ext{tf}:{tpid}"
                                if tf == 0 and tpid in fobj.objects:
                                    to = fobj.objects[tpid].read()
                                    tname = f"{to.m_Name}({to.m_Width}x{to.m_Height})"
                                elif tf > 0:
                                    ep = fobj.externals[tf - 1].path
                                    tname = f"{ep}:{tpid}"
                                texs.append(f"{tk}={tname}")
                        floats = {fk: fv for fk, fv in tt.get("m_SavedProperties", {}).get("m_Floats", []) if fk in ("_BlendOp", "_SrcBlend", "_DstBlend", "_Mode")}
                        cols = {ck: (round(cv['r'],2), round(cv['g'],2), round(cv['b'],2), round(cv['a'],2)) for ck, cv in tt.get("m_SavedProperties", {}).get("m_Colors", [])}
                        sh_p = tt.get("m_Shader", {})
                        sh_info = f"fid={sh_p.get('m_FileID')},pid={sh_p.get('m_PathID')}"
                        print(f"    [{lbl}] mat='{tt.get('m_Name')}' tex={texs} cols={cols} floats={floats} shader={sh_info}", flush=True)

print("\n=== 4. aurora.moc3 DREFTouchBox & Params ===", flush=True)
b35 = load_ab(cdn / "20_live2d/live2d_resources/batch35.ab")
for cpath, ptr in (b35.container or {}).items():
    if "aurora_s4" in cpath.lower() and cpath.endswith("aurora.asset"):
        mb = bytes(ptr.read_typetree()["_bytes"])
        strs = sorted(set(s.decode("ascii", "ignore") for s in re.findall(rb"[A-Za-z0-9_.\-]{3,}", mb)))
        print("  DREFTouchBox:", [s for s in strs if "touch" in s.lower() or "dref" in s.lower()], flush=True)
        print("  Params (Lip/Eye/Ring):", [s for s in strs if any(k in s.lower() for k in ("mouth", "eye", "ring"))], flush=True)

print("\n=== 5. Parse Aurora ActionGroups & Spine Actions ===", flush=True)
# Find all Group entries for SoulId = 20010019 in CfgSoulActionGroupTable_1.lua
g1 = (dec / "CfgSoulActionGroupTable_1.lua").read_text(encoding="utf-8", errors="ignore")
# Split by top-level entries [id] = {
blocks = re.split(r"\n\t\[(\d+)\] = \{", g1)
aurora_groups = []
for i in range(1, len(blocks), 2):
    gid = int(blocks[i])
    body = blocks[i + 1].split("\n\t},")[0]
    if re.search(r"SoulId\s*=\s*20010019\b", body):
        aurora_groups.append((gid, body))
print(f"  Aurora ActionGroups total: {len(aurora_groups)}", flush=True)
s4_groups = [(gid, b) for gid, b in aurora_groups if "20021941" in b]
common_groups = [(gid, b) for gid, b in aurora_groups if "SoulResId" not in b]
print(f"  With 20021941 override: {len(s4_groups)}, Without SoulResId (base/common): {len(common_groups)}", flush=True)
if s4_groups:
    print("  Sample s4_group:\n", s4_groups[0][0], s4_groups[0][1][:400], flush=True)
if common_groups:
    print("  Sample common_group:\n", common_groups[0][0], common_groups[0][1][:400], flush=True)
