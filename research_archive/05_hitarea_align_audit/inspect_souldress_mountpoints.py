import json, sys
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import load_ab, CDN_ROOT
import batch_fx_exporter as bfe

idx = bfe.AssetIndexer()

# Find ALL ab files in 03_prefabs or 23_spine/dressspine that contain SoulDress_Freesia / RubyRose / Benten / Ennis / Nicolette / Minerdwen / Sakuya
targets = ["freesia", "rubyrose", "benten", "ennis_02", "nicolettelamel_02", "minerdwen", "sakuyamako_04"]
print("=== Scanning art_container for SoulDress prefabs ===")
matches = {}
for k, pid in idx.art_container.items():
    kl = k.lower()
    if "dressspine" in kl and ".prefab" in kl:
        for t in targets:
            if t.split("_")[0] in kl:
                matches[k] = pid

def read_obj(objs, pid):
    o = objs.get(pid)
    return None if o is None else o.read_typetree()

def dump_ps_or_mount(objs, go_pid, depth=0):
    go = read_obj(objs, go_pid)
    if not go: return
    name = go.get("m_Name", "?")
    tf = None
    extras = []
    for c in go.get("m_Component", []):
        co = read_obj(objs, c["component"]["m_PathID"])
        if not co: continue
        if "m_Father" in co and ("m_LocalPosition" in co or "m_AnchoredPosition" in co):
            tf = co
        elif "m_Points" in co or "point" in str(co.keys()).lower():
            pass
        # Check MonoBehaviour scripts / fields (MountPoint!)
        if "m_Script" in co:
            keys = [k for k in co.keys() if k not in ("m_GameObject","m_Enabled","m_Script")]
            if any("mount" in k.lower() or "point" in k.lower() or "skeleton" in k.lower() or "effect" in k.lower() for k in keys):
                small = {k: co[k] for k in keys if k in ("m_Name","mountPoint","m_MountPoint","PointType","type","id","ID","MountPointID","_mountPointList","mountPoints","points","skeletonDataAsset","initialSkinName")}
                if not small:
                    small = {k: co[k] for k in list(keys)[:6]}
                extras.append(f"MB({small})")
    lp = tf.get("m_LocalPosition") if tf else None
    ls = tf.get("m_LocalScale") if tf else None
    ap = tf.get("m_AnchoredPosition") if tf else None
    print("  "*depth + f"- {name!r} lp={lp} ls={ls} ap={ap} {' '.join(extras)}")
    if tf:
        for ch in tf.get("m_Children", []):
            ch_tf = read_obj(objs, ch["m_PathID"])
            if ch_tf:
                dump_ps_or_mount(objs, ch_tf["m_GameObject"]["m_PathID"], depth+1)

for k in sorted(matches):
    if any(x in k.lower() for x in ("freesia_s5", "freesia_s6", "rubyrose_s2", "benten_s4", "nicolettelamel_s2", "ennis_s2", "minerdwen_s3", "sakuyamako_s4")):
        if "_bg_" in k.lower() or "unlock" in k.lower(): continue
        print(f"\n=== {k} ===")
        pid = matches[k]
        co = read_obj(idx.art_objs, pid)
        gpid = co["m_GameObject"]["m_PathID"] if (co and "m_GameObject" in co) else pid
        dump_ps_or_mount(idx.art_objs, gpid)
