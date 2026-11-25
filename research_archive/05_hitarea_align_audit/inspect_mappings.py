import io
import re
from pathlib import Path
import UnityPy

cdn = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")
dec = Path(r"D:\A灵魂潮汐-本地化\服务器\analysis\luajit-pipeline\baseline-20260813\decompiled-x64")

def load_ab(p: Path):
    raw = p.read_bytes()
    return UnityPy.load(io.BytesIO(raw[6:] if raw.startswith(b"iqigam") else raw))

print("=== 1. CfgCVTable exact lookup for 49010259 ===", flush=True)
for p in sorted(dec.glob("CfgCVTable_*.lua")):
    txt = p.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"\[49010259\]\s*=\s*\{.*?\}", txt, re.S)
    if m:
        print(" ", p.name, "->", m.group(0), flush=True)
        sm = re.search(r"SoundID\s*=\s*(\d+)", m.group(0))
        if sm:
            sid = sm.group(1)
            for sp in sorted(dec.glob("CfgSoundTable_*.lua")):
                st = sp.read_text(encoding="utf-8", errors="ignore")
                ms = re.search(rf"\[{sid}\]\s*=\s*\{{.*?\}}", st, re.S)
                if ms:
                    print("   ", sp.name, "->", ms.group(0), flush=True)

print("\n=== 2. Check all 13 Spine Action rows 192001..192013 ===", flush=True)
sp_act = (dec / "CfgSoulSpineActionTable.lua").read_text(encoding="utf-8", errors="ignore")
for aid in range(192001, 192014):
    m = re.search(rf"\[{aid}\]\s*=\s*\{{(.*?)\n\t\}}", sp_act, re.S)
    if m:
        print(f"  [{aid}]", m.group(1).replace("\n", " ").replace("\t", " "), flush=True)

sc_ctrl = (dec / "CfgSoulSpineActionControlTable.lua").read_text(encoding="utf-8", errors="ignore")
m = re.search(r"\[1902\]\s*=\s*\{(.*?)\n\t\}", sc_ctrl, re.S)
if m:
    print("  [Control 1902]", m.group(1).replace("\n", " ").replace("\t", " "), flush=True)

print("\n=== 3. Sample Aurora Live2D ActionGroup Types ===", flush=True)
g1 = (dec / "CfgSoulActionGroupTable_1.lua").read_text(encoding="utf-8", errors="ignore")
blocks = re.split(r"\n\t\[(\d+)\] = \{", g1)
type_samples = {}
for i in range(1, len(blocks), 2):
    gid = int(blocks[i])
    body = blocks[i + 1].split("\n\t},")[0]
    if re.search(r"SoulId\s*=\s*20010019\b", body):
        tm = re.search(r"Type\s*=\s*(\d+)", body)
        t = int(tm.group(1)) if tm else -1
        type_samples.setdefault(t, []).append(gid)
print("  ActionGroup Types -> IDs:", {k: (len(v), v[:4]) for k, v in sorted(type_samples.items())}, flush=True)
# Check SoulActionTypeTable & SoulActionModule or CfgSoulActionTypeTable
sat_path = dec / "CfgSoulActionTypeTable.lua"
if sat_path.exists():
    print("  CfgSoulActionTypeTable:\n", sat_path.read_text(encoding="utf-8", errors="ignore")[:800], flush=True)

print("\n=== 4. Inspect _batch4.ab BJ_01 / BJ_02 / BJ_03 atlases & Aurora BG prefabs ===", flush=True)
b4 = load_ab(cdn / "23_spine/dressspine/_batch4.ab")
for cpath, ptr in sorted((b4.container or {}).items()):
    if "aurora_04" in cpath.lower():
        if cpath.endswith(".atlas.txt"):
            txt = ptr.read().m_Script
            lines = txt.splitlines()
            print(f"  {Path(cpath).name}: lines={len(lines)} head={lines[:8]}", flush=True)
        elif cpath.endswith(".png"):
            im = ptr.read().image
            print(f"  {Path(cpath).name}: size={im.size}", flush=True)
        elif cpath.endswith(".skel.bytes"):
            raw_b = ptr.read().m_Script.encode("utf-8", "surrogateescape")
            import struct
            def parse_skel_hdr(buf):
                pos = 0
                def rd_str():
                    nonlocal pos
                    b = buf[pos]; pos += 1
                    length = b & 0x7F
                    shift = 7
                    while b & 0x80:
                        b = buf[pos]; pos += 1
                        length |= (b & 0x7F) << shift
                        shift += 7
                    if length == 0: return None
                    if length == 1: return ""
                    s = buf[pos:pos+length-1].decode("utf-8", "replace")
                    pos += length - 1
                    return s
                def rd_flt():
                    nonlocal pos
                    v = struct.unpack_from(">f", buf, pos)[0]
                    pos += 4
                    return v
                h = rd_str(); ver = rd_str()
                x, y, w, h_dim = rd_flt(), rd_flt(), rd_flt(), rd_flt()
                return h, ver, x, y, w, h_dim
            try:
                h, ver, x, y, w, h_dim = parse_skel_hdr(raw_b)
                print(f"  {Path(cpath).name}: hash={h} ver={ver} bounds=({x:.1f},{y:.1f},{w:.1f},{h_dim:.1f})", flush=True)
            except Exception as e:
                print(f"  {Path(cpath).name}: parse err {e}", flush=True)
