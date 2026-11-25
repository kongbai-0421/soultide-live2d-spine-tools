import sys, json
from pathlib import Path

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

# Search ui.ab and art_prefabs.ab for HeLing_S2_Background and SoulRes_20010043_20024321
ab_candidates = [
    CDN_ROOT / "03_prefabs" / "ui.ab",
    CDN_ROOT / "03_prefabs" / "art_prefabs.ab",
]
# Also check any sub-abs under 03_prefabs
for p in (CDN_ROOT / "03_prefabs").rglob("*.ab"):
    if any(k in p.name.lower() for k in ["heling", "4320", "4321", "maincity", "dress", "soul"]):
        if p not in ab_candidates:
            ab_candidates.append(p)

print("Checking ABs:", [str(p) for p in ab_candidates[:15]])

def dump_prefab_tree(env, target_substrs):
    # Map path_id -> obj
    objs = {}
    for obj in env.objects:
        objs[obj.path_id] = obj

    def read_t(obj):
        try:
            return obj.read_typetree()
        except Exception:
            return None

    # Find matching GameObjects or Prefab roots
    roots = []
    for pid, obj in objs.items():
        if obj.type.name == "GameObject":
            tt = read_t(obj)
            if not tt: continue
            nm = tt.get("m_Name", "")
            if any(sub.lower() in nm.lower() for sub in target_substrs):
                # check if root transform (no father)
                tr_pid = None
                for c in tt.get("m_Component", []):
                    cpid = c.get("component", {}).get("m_PathID", 0)
                    co = objs.get(cpid)
                    if co and co.type.name in ("Transform", "RectTransform"):
                        tr_pid = cpid
                        break
                if tr_pid:
                    tr_tt = read_t(objs[tr_pid])
                    father = (tr_tt.get("m_Father") or {}).get("m_PathID", 0)
                    if father == 0:
                        roots.append((nm, tr_pid))

    def walk(tr_pid, depth=0):
        tr_obj = objs.get(tr_pid)
        if not tr_obj: return
        tr_tt = read_t(tr_obj)
        go_pid = (tr_tt.get("m_GameObject") or {}).get("m_PathID", 0)
        go_obj = objs.get(go_pid)
        go_tt = read_t(go_obj) if go_obj else {}
        nm = go_tt.get("m_Name", "?")
        active = go_tt.get("m_IsActive", 1)
        pos = tr_tt.get("m_LocalPosition") or {}
        if "m_AnchoredPosition" in tr_tt:
            ap = tr_tt["m_AnchoredPosition"]
            pos_str = f"anch=({ap.get('x',0):.1f},{ap.get('y',0):.1f}) z={pos.get('z',0):.1f}"
        else:
            pos_str = f"pos=({pos.get('x',0):.1f},{pos.get('y',0):.1f},{pos.get('z',0):.1f})"

        comps = []
        for c in go_tt.get("m_Component", []):
            cpid = c.get("component", {}).get("m_PathID", 0)
            co = objs.get(cpid)
            if not co: continue
            tn = co.type.name
            if tn in ("Transform", "RectTransform", "CanvasRenderer"): continue
            ctt = read_t(co) or {}
            extra = ""
            if tn == "Canvas":
                extra = f"[overrideSort={ctt.get('m_OverrideSorting')}, order={ctt.get('m_SortingOrder')}, layer={ctt.get('m_SortingLayerID')}]"
            elif tn in ("ParticleSystemRenderer", "MeshRenderer", "SpriteRenderer"):
                extra = f"[order={ctt.get('m_SortingOrder')}, layer={ctt.get('m_SortingLayerID')}, enabled={ctt.get('m_Enabled')}]"
            elif tn == "MonoBehaviour":
                sc_pid = (ctt.get("m_Script") or {}).get("m_PathID", 0)
                keys = [k for k in ctt.keys() if not k.startswith("m_")]
                # detect SkeletonGraphic / Image / Spine / SortOrder
                hint = []
                if "skeletonDataAsset" in ctt: hint.append("SPINE")
                if "m_Sprite" in ctt: hint.append("UI.Image")
                if "startingAnimation" in ctt: hint.append(f"anim={ctt.get('startingAnimation')}")
                if "sortingOrder" in ctt: hint.append(f"sortOrder={ctt.get('sortingOrder')}")
                if "m_Color" in ctt:
                    col = ctt["m_Color"]
                    hint.append(f"a={col.get('a',1):.2f}")
                extra = f"[{' '.join(hint) or ','.join(keys[:4])}]"
            comps.append(f"{tn}{extra}")

        indent = "  " * depth
        print(f"{indent}- {nm} (active={active}) {pos_str} | {' ; '.join(comps)}")
        for ch in tr_tt.get("m_Children", []):
            cpid = ch.get("m_PathID", 0)
            if cpid: walk(cpid, depth + 1)

    for nm, tr_pid in roots:
        print(f"\n================ ROOT PREFAB: {nm} ================")
        walk(tr_pid, 0)

for ab in ab_candidates:
    if not ab.exists(): continue
    env = load_ab(ab)
    dump_prefab_tree(env, ["HeLing_S2_Background", "SoulRes_20010043_20024321", "HeLing_02", "HeLing_S2"])
