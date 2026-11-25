import json, re, sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, LuaTableRepo, load_ab

p = Path(r"E:\A灵魂潮汐\备份\spine\欧若拉\童话心绘\有背景\.config.json")
print("=== 备份有背景 .config.json options ===")
cfg = json.loads(p.read_text("utf-8", "ignore"))
print("options:", cfg.get("options"))
print("hit_areas:", cfg.get("hit_areas"))
print("motions keys:", list(cfg.get("motions", {}).keys()))

print("\n=== Search backup for Choices ===")
bkp = Path(r"E:\A灵魂潮汐\备份")
for jf in bkp.rglob("*.json"):
    if jf.name.endswith((".motion3.json", ".physics3.json")):
        continue
    t = jf.read_text("utf-8", "ignore")
    if '"Choices"' in t or '"choices"' in t:
        print("FOUND Choices:", jf)
        pos = max(t.find('"Choices"'), t.find('"choices"'))
        print(t[max(0, pos - 120):pos + 500])
        break

print("\n=== Aurora.moc3 DREFTouchBox & mesh check ===")
moc = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
toks = sorted(set(m.decode("ascii", "ignore") for m in re.findall(rb"[A-Za-z0-9_]{3,}", moc)))
print("DREFTouchBox*:", [x for x in toks if "touch" in x.lower() or "box" in x.lower()])

print("\n=== Aurora S4 (20021941 / 20021940) ActionGroups breakdown ===")
repo = LuaTableRepo()
SOUL_ID = 20010019
SKIN_RES_IDS = (20021941, 20021940)
for gid, body in sorted(repo.action_groups.items()):
    if not re.search(rf"SoulId\s*=\s*{SOUL_ID}\b", body):
        continue
    gtype = int(re.search(r"Type\s*=\s*(\d+)", body).group(1))
    m_res = re.search(r"SoulResId\s*=\s*\{([^}]+)\}", body)
    m_ract = re.search(r"SoulResAction\s*=\s*\{(.*?)\n\t\t\}", body, re.S)
    skin_aids = []
    if m_res and m_ract:
        rids = [int(x) for x in re.findall(r"\d+", m_res.group(1))]
        sub_lists = re.findall(r"\{([^}]*)\}", m_ract.group(1))
        for srid in SKIN_RES_IDS:
            if srid in rids:
                idx = rids.index(srid)
                if idx < len(sub_lists):
                    skin_aids = [int(x) for x in re.findall(r"\d+", sub_lists[idx])]
                    break
    m_mood = re.search(r"MoodActionID\s*=\s*\{(.*?)\n\t\t\}", body, re.S)
    base_aids = [int(x) for x in re.findall(r"\d{6,}", m_mood.group(1))] if m_mood else []
    if skin_aids or gtype in (801, 901, 1001, 1101, 1201, 1401, 1402, 1403, 1404, 1409):
        print(f"G{gid} type={gtype} skin_aids={skin_aids} base_aids={base_aids}")
        for aid in skin_aids:
            act = repo.action_map.get(aid)
            if act:
                cv = repo.resolve_cv(act["cv"])
                print(f"   SKIN act {aid}: mot={act['body_action']} snd={cv['sound_stem']} txt={cv['text'][:40]}")
