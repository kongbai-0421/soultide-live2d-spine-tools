import io
import re
from pathlib import Path
import UnityPy

cdn = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")
dec = Path(r"D:\A灵魂潮汐-本地化\服务器\analysis\luajit-pipeline\baseline-20260813\decompiled-x64")

def load_ab(p: Path):
    raw = p.read_bytes()
    return UnityPy.load(io.BytesIO(raw[6:] if raw.startswith(b"iqigam") else raw))

print("=== 1. FX Materials & Textures ===", flush=True)
target_pids = {
    65754890445359314: "beike",
    2331313482108350463: "xianglian",
    8919695548410932974: "FX_glow",
    5677564959687805008: "glow02",
    9142306378696600815: "smoke",
    -3013462422272175626: "shan_s",
    -187576216157495043: "aixin",
    8566848586218849390: "bao",
    4696809865029886123: "glow01_t",
    6717544822340696281: "lizi_san",
    -6215823799543604914: "glow01_bg1",
    -8188828357555011462: "glow01_bg2",
    7393461633868356657: "yinghuochong",
    -7873106136598437370: "shan",
    -7406617868670641507: "stra",
    5893497205202485342: "FX_stra",
}
fx_bundles = [
    "14_effect/battle/_batch1.ab", "14_effect/battle/_batch2.ab", "14_effect/battle/_batch3.ab",
    "14_effect/battle/_batch4.ab", "14_effect/battle/_batch5.ab", "14_effect/battle/_batch6.ab",
    "14_effect/battle/_batch8.ab", "14_effect/battle/_batch9.ab", "14_effect/battle/_batch10.ab",
    "14_effect/battle/_batch11.ab", "14_effect/battle/_common.ab", "14_effect/battle/_maze.ab",
    "14_effect/ui/batch1.ab", "14_effect/ui/batch2.ab",
]
ext_tex_pids = {}
for rel in fx_bundles:
    abp = cdn / rel
    if not abp.exists():
        continue
    env = load_ab(abp)
    for obj in env.objects:
        if obj.path_id in target_pids:
            lbl = target_pids[obj.path_id]
            tt = obj.read_typetree()
            texs = []
            for tk, tv in tt.get("m_SavedProperties", {}).get("m_TexEnvs", []):
                tp = tv.get("m_Texture", {})
                tf, tpid = tp.get("m_FileID", 0), tp.get("m_PathID", 0)
                if tpid != 0:
                    if tf == 0 and tpid in obj.assets_file.objects:
                        tex = obj.assets_file.objects[tpid].read()
                        texs.append(f"{tk}={tex.m_Name}({tex.m_Width}x{tex.m_Height})")
                    else:
                        ext_tex_pids[tpid] = f"{lbl}.{tk}"
                        texs.append(f"{tk}=ext{tf}:{tpid}")
            cols = {ck: (round(cv["r"], 2), round(cv["g"], 2), round(cv["b"], 2), round(cv["a"], 2))
                    for ck, cv in tt.get("m_SavedProperties", {}).get("m_Colors", [])}
            floats = {fk: fv for fk, fv in tt.get("m_SavedProperties", {}).get("m_Floats", [])
                      if fk in ("_BlendOp", "_SrcBlend", "_DstBlend", "_Mode", "_Cutoff")}
            mname = tt.get("m_Name")
            print(f"  [{lbl}] in {rel}: mat={mname} tex={texs} cols={cols} floats={floats}", flush=True)

if ext_tex_pids:
    print("  Checking external texture pids:", ext_tex_pids, flush=True)
    for rel in fx_bundles + ["15_shader/15_shader_base.ab"]:
        abp = cdn / rel
        if not abp.exists():
            continue
        env = load_ab(abp)
        for obj in env.objects:
            if obj.path_id in ext_tex_pids and obj.type.name == "Texture2D":
                to = obj.read()
                print(f"    EXT [{ext_tex_pids[obj.path_id]}] in {rel}: {to.m_Name} ({to.m_Width}x{to.m_Height})", flush=True)

print("\n=== 2. Check Aurora AudioClip names in 06_sounds/cv/_aurora.ab ===", flush=True)
cv_env = load_ab(cdn / "06_sounds/cv/_aurora.ab")
clips = []
for obj in cv_env.objects:
    if obj.type.name == "AudioClip":
        clips.append(obj.peek_name())
print(f"  AudioClips count: {len(clips)} sample: {sorted(clips)[:15]}", flush=True)

print("\n=== 3. Inspect CfgSoulActionTable / CfgCVTable / CfgSoundTable / CfgI18NTable schema ===", flush=True)
def sample_lua_entry(path: Path, key_hint: str = None):
    txt = path.read_text(encoding="utf-8", errors="ignore")
    if key_hint:
        idx = txt.find(key_hint)
        if idx >= 0:
            return txt[max(0, idx - 30):idx + 350]
    m = re.search(r"\n\t\[\d+\] = \{.*?\n\t\},", txt, re.S)
    return m.group(0) if m else txt[:400]

print("  CfgSoulActionTable_1:\n", sample_lua_entry(dec / "CfgSoulActionTable_1.lua", "191701201"), flush=True)
print("  CfgSoulActionTable_2:\n", sample_lua_entry(dec / "CfgSoulActionTable_2.lua", "191701201"), flush=True)
print("  CfgSoulActionTable_3:\n", sample_lua_entry(dec / "CfgSoulActionTable_3.lua", "191701201"), flush=True)
print("  CfgCVTable_2 (49010259):\n", sample_lua_entry(dec / "CfgCVTable_2.lua", "49010259"), flush=True)
print("  CfgCVTable_3 (49010259):\n", sample_lua_entry(dec / "CfgCVTable_3.lua", "49010259"), flush=True)
print("  CfgCVTable_4 (49010259):\n", sample_lua_entry(dec / "CfgCVTable_4.lua", "49010259"), flush=True)
print("  CfgSoundTable_1 sample:\n", sample_lua_entry(dec / "CfgSoundTable_1.lua"), flush=True)
print("  CfgI18NTable_Route sample:\n", (dec / "CfgI18NTable_Route.lua").read_text(encoding="utf-8", errors="ignore")[:300] if (dec / "CfgI18NTable_Route.lua").exists() else "no route", flush=True)
