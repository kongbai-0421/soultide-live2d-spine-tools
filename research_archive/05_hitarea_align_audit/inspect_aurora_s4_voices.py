import sys, re
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import LuaTableRepo

repo = LuaTableRepo()
SOUL_ID = 20010019
SKIN_RES_IDS = (20021941, 20021940)
print("=== All ActionGroups with Skin overrides (20021941/20021940) ===")
seen = set()
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
    if skin_aids:
        print(f"G{gid} type={gtype} skin_aids={skin_aids}")
        for aid in skin_aids:
            if aid not in seen:
                seen.add(aid)
                act = repo.action_map.get(aid)
                if act:
                    cv = repo.resolve_cv(act["cv"])
                    print(f"   [{aid}] mot={act['body_action']} snd={cv['sound_stem']} dur={cv['duration_ms']} txt={cv['text']}")

print("\n=== ALL Action rows for Aurora containing fashion3 / dress3 / After_Marriage ===")
for aid, act in sorted(repo.action_map.items()):
    if act["soul_id"] != SOUL_ID: continue
    ba = act["body_action"] or ""
    cv = repo.resolve_cv(act["cv"])
    ss = cv["sound_stem"]
    if any(k in ba.lower() for k in ("fashion3",)) or any(k in ss.lower() for k in ("dress3", "after_marriage")):
        print(f"   act[{aid}] mot={ba} snd={ss} dur={cv['duration_ms']} txt={cv['text']}")
