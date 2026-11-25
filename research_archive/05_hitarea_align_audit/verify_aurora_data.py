import io
import json
import re
from pathlib import Path
from PIL import Image
import UnityPy

cdn = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")
dec = Path(r"D:\A灵魂潮汐-本地化\服务器\analysis\luajit-pipeline\baseline-20260813\decompiled-x64")

def load_ab(p: Path):
    raw = p.read_bytes()
    return UnityPy.load(io.BytesIO(raw[6:] if raw.startswith(b"iqigam") else raw))

print("=== 1. Check SortingOrder / Renderer / MeshRenderer of Aurora_S4_Background BG_01_02 vs BG_02 vs BG_03 ===", flush=True)
ap = load_ab(cdn / "03_prefabs/art_prefabs.ab")
for obj in ap.objects:
    if obj.type.name == "GameObject":
        d = obj.read()
        if d.m_Name in ("Aurora_S4_Background", "SoulDress_Aurora_Person_BG_01_02", "SoulDress_Aurora_Person_BG_02", "SoulDress_Aurora_Person_BG_03", "Point_Root", "Layer_02", "Layer_04"):
            for cp in d.m_Components:
                if cp.type.name in ("Canvas", "MeshRenderer", "SortingGroup", "MonoBehaviour"):
                    try:
                        tt = cp.read_typetree()
                        keys = {k: tt[k] for k in ("m_SortingOrder", "m_SortingLayerID", "m_OverrideSorting", "m_Order", "order", "_Order") if k in tt}
                        if keys or cp.type.name in ("Canvas", "MeshRenderer"):
                            print(f"  {d.m_Name} [{cp.type.name}]: {keys}", flush=True)
                    except Exception:
                        pass

print("\n=== 2. Verify FULL Live2D & Spine Lua Action -> CV -> Sound -> I18N resolution ===", flush=True)
# Load I18N tables (parse route or all CfgI18NTable_*.lua lazily by ID)
route_txt = (dec / "CfgI18NTable_Route.lua").read_text(encoding="utf-8", errors="ignore")
i18n_ranges = [(int(a), int(b), int(c)) for a, b, c in re.findall(r"\{\s*(\d+),\s*(\d+),\s*(\d+)\s*\}", route_txt)]
i18n_cache = {}

def parse_lua_flat_table(path: Path):
    txt = path.read_text(encoding="utf-8", errors="ignore")
    entries = {}
    # Match top-level `\t[id] = { ... \n\t},`
    parts = re.split(r"\n\t\[(\d+)\] = \{", txt)
    for i in range(1, len(parts), 2):
        kid = int(parts[i])
        body = parts[i + 1].split("\n\t}")[0]
        entries[kid] = body
    return entries

def get_i18n(i18n_id: int) -> str:
    shard = None
    for lo, hi, idx in i18n_ranges:
        if lo <= i18n_id <= hi:
            shard = idx
            break
    if shard is None:
        return f"[MissingI18N:{i18n_id}]"
    if shard not in i18n_cache:
        txt = (dec / f"CfgI18NTable_{shard}.lua").read_text(encoding="utf-8", errors="ignore")
        # format: [180826226] = { "text", "text", ... } or [id] = "text" or Str = "..."
        mp = {}
        for m in re.finditer(r'\[(\d+)\]\s*=\s*(?:\{\s*)?"((?:[^"\\]|\\.)*)"', txt, re.S):
            mp[int(m.group(1))] = m.group(2)
        i18n_cache[shard] = mp
    raw_s = i18n_cache[shard].get(i18n_id, f"[UnparsedI18N:{i18n_id}]")
    # Unescape lua string & clean {$br}
    raw_s = raw_s.replace('\\"', '"').replace("\\n", "\n").replace("\\'", "'").replace("\\\\", "\\")
    return raw_s.replace("{$br}", "\n")

# Load CfgCVTable_1..4
cv_map = {}
for p in sorted(dec.glob("CfgCVTable_*.lua")):
    if p.name.endswith("_Route.lua"):
        continue
    for k, body in parse_lua_flat_table(p).items():
        sid = re.search(r"SoundID\s*=\s*(\d+)", body)
        tt = re.search(r"TextTime\s*=\s*([\d.]+)", body)
        tx = re.search(r"Text\s*=\s*getI18NValue\((\d+)\)", body)
        cv_map[k] = {
            "sound_id": int(sid.group(1)) if sid else None,
            "text_time": float(tt.group(1)) if tt else None,
            "text_i18n": int(tx.group(1)) if tx else None,
        }

# Load CfgSoundTable_1..3
sound_map = {}
for p in sorted(dec.glob("CfgSoundTable_*.lua")):
    if p.name.endswith("_Route.lua"):
        continue
    for k, body in parse_lua_flat_table(p).items():
        fn = re.search(r'FileName\s*=\s*"([^"]+)"', body)
        if fn:
            sound_map[k] = fn.group(1)

# Load CfgSoulActionTable_1..3
action_map = {}
for p in sorted(dec.glob("CfgSoulActionTable_*.lua")):
    if p.name.endswith("_Route.lua"):
        continue
    for k, body in parse_lua_flat_table(p).items():
        ba = re.search(r'BodyAction\s*=\s*"([^"]+)"', body)
        cv = re.search(r'CV\s*=\s*"([^"]+)"', body)
        an = re.search(r'ActionName\s*=\s*getI18NValue\((\d+)\)', body)
        sid = re.search(r'SoulId\s*=\s*(\d+)', body)
        action_map[k] = {
            "body_action": ba.group(1) if ba else None,
            "cv": int(cv.group(1)) if cv and cv.group(1).isdigit() else None,
            "action_name_id": int(an.group(1)) if an else None,
            "soul_id": int(sid.group(1)) if sid else None,
        }

# Load _aurora.ab clip names
cv_env = load_ab(cdn / "06_sounds/cv/_aurora.ab")
audio_stems = {obj.peek_name().lower() for obj in cv_env.objects if obj.type.name == "AudioClip"}

# Resolve all Spine Actions 192001..192013
sp_act = parse_lua_flat_table(dec / "CfgSoulSpineActionTable.lua")
print("  Spine Actions (192001..192013):", flush=True)
for aid in range(192001, 192014):
    body = sp_act[aid]
    cv_id = int(re.search(r"CV\s*=\s*(\d+)", body).group(1))
    st = re.search(r'SoulActionState\s*=\s*"([^"]+)"', body).group(1)
    mst = re.search(r'MarryActionState\s*=\s*"([^"]+)"', body).group(1)
    eff = re.search(r'EffectId\s*=\s*(\d+)', body)
    cvi = cv_map.get(cv_id, {})
    snd = sound_map.get(cvi.get("sound_id"), "?")
    stem = Path(snd).stem.lower()
    txt = get_i18n(cvi["text_i18n"]) if cvi.get("text_i18n") else ""
    print(f"    {aid}: {st}/{mst} eff={eff.group(1) if eff else '-'} cv={cv_id} snd={Path(snd).name} in_ab={stem in audio_stems} dur={cvi.get('text_time')}s text={txt!r}", flush=True)

# Resolve Aurora Live2D ActionGroups (SoulId=20010019)
g1 = parse_lua_flat_table(dec / "CfgSoulActionGroupTable_1.lua")
aurora_l2d_actions = []
for gid, body in sorted(g1.items()):
    if not re.search(r"SoulId\s*=\s*20010019\b", body):
        continue
    gtype = int(re.search(r"Type\s*=\s*(\d+)", body).group(1))
    # Check if SoulResId override exists
    m_res = re.search(r"SoulResId\s*=\s*\{([^}]+)\}", body)
    m_ract = re.search(r"SoulResAction\s*=\s*\{(.*?)\n\t\t\}", body, re.S)
    chosen_ids = []
    source_tag = "common"
    if m_res and m_ract:
        res_ids = [int(x) for x in re.findall(r"\d+", m_res.group(1))]
        # Find 20021941 (or 20021940) index
        idx = res_ids.index(20021941) if 20021941 in res_ids else (res_ids.index(20021940) if 20021940 in res_ids else -1)
        if idx >= 0:
            sub_groups = re.findall(r"\{([^}]*)\}", m_ract.group(1))
            if idx < len(sub_groups):
                chosen_ids = [int(x) for x in re.findall(r"\d+", sub_groups[idx])]
                source_tag = "s4_override"
    if not chosen_ids:
        m_mood = re.search(r"MoodActionID\s*=\s*\{(.*?)\n\t\t\}", body, re.S)
        if m_mood:
            chosen_ids = sorted(set(int(x) for x in re.findall(r"\d{6,}", m_mood.group(1))))
    for aid in chosen_ids:
        aurora_l2d_actions.append((gid, gtype, source_tag, aid))

print(f"\n  Live2D Action entries for Aurora S4: {len(aurora_l2d_actions)} (unique action IDs: {len(set(x[3] for x in aurora_l2d_actions))})", flush=True)
missing_mot, missing_snd, missing_i18n = [], [], []
b35 = load_ab(cdn / "20_live2d/live2d_resources/batch35.ab")
b35_mots = {Path(c).name.replace(".motion3.json", "").lower() for c in (b35.container or {}) if "aurora_s4" in c.lower() and c.endswith(".motion3.json")}
seen_aid = set()
s4_ov_count = 0
for gid, gtype, tag, aid in aurora_l2d_actions:
    if aid in seen_aid:
        continue
    seen_aid.add(aid)
    act = action_map.get(aid)
    if not act:
        missing_mot.append((aid, "no_action"))
        continue
    mot_l = (act["body_action"] or "").lower()
    if mot_l and mot_l not in b35_mots:
        missing_mot.append((aid, act["body_action"]))
    cv_id = act["cv"]
    snd_ok = True
    i18n_ok = True
    snd_name = None
    txt = None
    if cv_id:
        cvi = cv_map.get(cv_id, {})
        if cvi.get("sound_id"):
            snd = sound_map.get(cvi["sound_id"], "")
            snd_name = Path(snd).name
            if Path(snd).stem.lower() not in audio_stems:
                missing_snd.append((aid, cv_id, snd))
                snd_ok = False
        if cvi.get("text_i18n"):
            txt = get_i18n(cvi["text_i18n"])
            if txt.startswith("[Missing") or txt.startswith("[Unparsed"):
                missing_i18n.append((aid, cvi["text_i18n"], txt))
                i18n_ok = False
    if tag == "s4_override":
        s4_ov_count += 1
        print(f"    [S4] gid={gid} type={gtype} aid={aid} mot={act['body_action']} snd={snd_name} text={txt!r}", flush=True)

print(f"  Summary: unique_actions={len(seen_aid)} s4_override_unique={s4_ov_count} missing_mot={missing_mot} missing_snd={missing_snd} missing_i18n={missing_i18n}", flush=True)
# Check unused b35 motions
used_mots = {(action_map[aid]["body_action"] or "").lower() for aid in seen_aid if aid in action_map}
unused_mots = sorted(b35_mots - used_mots)
print(f"  batch35 aurora_s4 motions total={len(b35_mots)}, used={len(used_mots & b35_mots)}, unused({len(unused_mots)})={unused_mots[:20]}", flush=True)
