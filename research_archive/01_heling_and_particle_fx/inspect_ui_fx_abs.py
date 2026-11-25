import json, sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

idx = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
cat = bfe.build_skin_catalog(repo)
by_sk = {r["skin_key"]: r for r in cat}

def read_obj(objs, pid):
    o = objs.get(pid)
    if o is None:
        return None
    return o if isinstance(o, dict) else o.read_typetree()

def dump_go_tree(objs, go_pid, depth=0):
    go = read_obj(objs, go_pid)
    if not go:
        return
    name = go.get("m_Name", "?")
    active = go.get("m_IsActive", True)
    tf = None
    ps = None
    skg = None
    for c in go.get("m_Component", []):
        cpid = c["component"]["m_PathID"]
        co = read_obj(objs, cpid)
        if not co: continue
        if "m_Father" in co and ("m_LocalPosition" in co or "m_AnchoredPosition" in co):
            tf = co
        elif "InitialModule" in co:
            ps = co
        elif "skeletonDataAsset" in co:
            skg = co
    extra = ""
    if ps:
        im = ps.get("InitialModule", {})
        extra += f" [PS dur={ps.get('lengthInSec')} sm={ps.get('scalingMode')} sz=({im.get('startSize',{}).get('scalar')},{im.get('startSizeY',{}).get('scalar')}) sz3d={im.get('size3D')}]"
    if skg:
        extra += f" [SkeletonGraphic sda={skg.get('skeletonDataAsset')}]"
    lp = tf.get("m_LocalPosition") if tf else None
    ls = tf.get("m_LocalScale") if tf else None
    ap = tf.get("m_AnchoredPosition") if tf else None
    sd = tf.get("m_SizeDelta") if tf else None
    print("  " * depth + f"- {name!r} act={active} lp={lp} ls={ls} ap={ap} sd={sd}{extra}")
    if tf:
        for ch in tf.get("m_Children", []):
            ch_tf = read_obj(objs, ch["m_PathID"])
            if ch_tf:
                dump_go_tree(objs, ch_tf["m_GameObject"]["m_PathID"], depth + 1)

def find_go_in_idx(res_path):
    stem = Path(res_path).stem.lower()
    for k, pid in idx.art_container.items():
        if res_path.lower() in k.lower():
            print(f"  [art_container match] {k} pid={pid}")
            co = read_obj(idx.art_objs, pid)
            gpid = co["m_GameObject"]["m_PathID"] if (co and "m_GameObject" in co) else pid
            dump_go_tree(idx.art_objs, gpid)
            return
    if stem in idx.ui_go_by_name:
        print(f"  [ui_go_by_name match] {stem} count={len(idx.ui_go_by_name[stem])}")
        for gpid in idx.ui_go_by_name[stem]:
            dump_go_tree(idx.ui_objs, gpid)
        return
    if stem in idx.art_go_by_name:
        print(f"  [art_go_by_name match] {stem} count={len(idx.art_go_by_name[stem])}")
        for gpid in idx.art_go_by_name[stem]:
            dump_go_tree(idx.art_objs, gpid)
        return
    print(f"  NOT FOUND: {res_path}")

for sk in ("402_Freesia_S5", "503_Benten_S4", "1101_NicoletteLamel_S2", "2001_Ennis_S2", "4501_RubyRose_S2"):
    r = by_sk[sk]
    print(f"\n**************** {sk} bg={r.get('bg_prefab')} eff={r.get('effect_prefabs')} ****************")
    if r.get("bg_prefab"):
        layout = bfe.inspect_bg_prefab_layout(idx, r)
        print("  layout:", {k: v for k, v in layout.items() if k != "particles"})
        find_go_in_idx(r["bg_prefab"])
    for eid, ep in (r.get("effect_prefabs") or {}).items():
        print(f"=== effect {eid}: {ep} ===")
        find_go_in_idx(ep)

cfg = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine\芙丽希娅\孤寂天鹅")
if cfg.exists():
    print("\n=== Freesia_S5 folder files ===", [p.name for p in cfg.iterdir()])
    for j in cfg.glob("*.config.json"):
        print(j.name, j.read_text(encoding="utf-8")[:1500])
