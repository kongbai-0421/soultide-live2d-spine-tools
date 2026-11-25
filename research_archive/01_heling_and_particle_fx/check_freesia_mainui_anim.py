import json, sys, zlib
from pathlib import Path
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe
from soultide_common import CDN_ROOT, load_ab

indexer = bfe.AssetIndexer()

# 1. Check MainUI & GirlDressShowUI Canvas/CanvasScaler
for nm in ("mainui", "girldressshowui", "girlui"):
    pids = indexer.ui_go_by_name.get(nm, [])
    if pids:
        go = indexer.ui_objs[pids[0]].read()
        print(f"=== UI Prefab {go.m_Name} ===")
        for c in go.m_Component:
            co = indexer.ui_objs.get(c.component.path_id)
            if not co: continue
            if co.type.name == "Canvas":
                tt = co.read_typetree()
                print("  Canvas:", {k: tt.get(k) for k in ("m_RenderMode", "m_SortingOrder", "m_PixelPerfect")})
            elif co.type.name == "RectTransform":
                r = co.read()
                print(f"  RT lsc=({r.m_LocalScale.x},{r.m_LocalScale.y},{r.m_LocalScale.z}) sd=({r.m_SizeDelta.x},{r.m_SizeDelta.y})")
            elif co.type.name == "MonoBehaviour":
                try:
                    tt = co.read_typetree()
                    if "m_UiScaleMode" in tt or "m_ReferenceResolution" in tt:
                        print("  CanvasScaler:", {k: tt.get(k) for k in ("m_UiScaleMode", "m_ReferenceResolution", "m_ScreenMatchMode", "m_MatchWidthOrHeight", "m_ReferencePixelsPerUnit", "m_ScaleFactor")})
                except Exception:
                    pass

# 2. Check why Freesia_S5 Touch01 ended up at [850.6, 520.0]
print("\n=== Check FX_Freesia_S5_Background_Touch01 & Freesia_S5_Background Point_Root ===")
pids = indexer.art_go_by_name.get("fx_freesia_s5_background_touch01", [])
def dump_full(gid, objs, depth=0):
    go = objs[gid].read()
    tf = None
    for c in go.m_Component:
        co = objs.get(c.component.path_id)
        if co and co.type.name in ("RectTransform", "Transform"):
            tf = co.read()
            if co.type.name == "RectTransform":
                print(f"{'  '*depth}{go.m_Name} [RT]: ap=({tf.m_AnchoredPosition.x:.2f},{tf.m_AnchoredPosition.y:.2f}) pos=({tf.m_LocalPosition.x:.2f},{tf.m_LocalPosition.y:.2f},{tf.m_LocalPosition.z:.2f}) amin=({tf.m_AnchorMin.x},{tf.m_AnchorMin.y}) amax=({tf.m_AnchorMax.x},{tf.m_AnchorMax.y}) lsc=({tf.m_LocalScale.x:.4f},{tf.m_LocalScale.y:.4f},{tf.m_LocalScale.z:.4f})")
            else:
                print(f"{'  '*depth}{go.m_Name} [TF]: pos=({tf.m_LocalPosition.x:.2f},{tf.m_LocalPosition.y:.2f},{tf.m_LocalPosition.z:.2f}) lsc=({tf.m_LocalScale.x:.4f},{tf.m_LocalScale.y:.4f},{tf.m_LocalScale.z:.4f})")
    if tf:
        for ch in tf.m_Children:
            ctf = objs.get(ch.path_id)
            if ctf: dump_full(ctf.read().m_GameObject.path_id, objs, depth+1)

if pids:
    dump_full(pids[0], indexer.art_objs)

print("=== Check SoulDress_Freesia in ui.ab / art_prefabs.ab ===")
for label, objs, go_map in [("ui", indexer.ui_objs, indexer.ui_go_by_name), ("art", indexer.art_objs, indexer.art_go_by_name)]:
    if "souldress_freesia" in go_map:
        print(f"--- {label}/SoulDress_Freesia ---")
        dump_full(go_map["souldress_freesia"][0], objs)

# 3. Check 28_battle or 01_scenes Canvas/Camera? Wait check Freesia_S5 inspect_bg_prefab_layout & fx_9008161 extraction!
repo = bfe.FullI18nRepo()
cat = next(c for c in bfe.build_skin_catalog(repo) if c["skin_key"] == "402_Freesia_S5")
lay = bfe.inspect_bg_prefab_layout(indexer, cat)
print("\n=== Freesia_S5 layout ===")
print({k: v for k, v in lay.items() if k != "bg_images"})
# Check where SoulDress_Freesia_Person is vs Point_Root inside Freesia_S5_Background!
fbg = indexer.ui_go_by_name["freesia_s5_background"][0]
dump_full(fbg, indexer.ui_objs)

# 4. Resolve CRC32 path hashes for all 5 AnimatorClips
print("\n=== AnimationClip CRC32 Path Hashes & Raw Clip keys ===")
def collect_paths(gid, objs, prefix="", out=None):
    if out is None: out = {}
    go = objs[gid].read()
    p = f"{prefix}/{go.m_Name}" if prefix else go.m_Name
    out[zlib.crc32(p.encode("utf-8")) & 0xFFFFFFFF] = p
    # Wait: Unity AnimationClip hashes relative to Animator GO!
    for c in go.m_Component:
        co = objs.get(c.component.path_id)
        if co and co.type.name in ("Transform", "RectTransform"):
            tf = co.read()
            for ch in tf.m_Children:
                ctf = objs.get(ch.path_id)
                if ctf: collect_paths(ctf.read().m_GameObject.path_id, objs, p, out)
    return out

# On QingDai_S2_Background_touch2, Animator is at root QingDai_S2_Background_touch2!
q_pid = indexer.art_go_by_name["qingdai_s2_background_touch2"][0]
q_go = indexer.art_objs[q_pid].read()
path_map = {}
for c in q_go.m_Component:
    co = indexer.art_objs.get(c.component.path_id)
    if co and co.type.name in ("Transform", "RectTransform"):
        for ch in co.read().m_Children:
            ctf = indexer.art_objs.get(ch.path_id)
            if ctf: collect_paths(ctf.read().m_GameObject.path_id, indexer.art_objs, "", path_map)
print("QingDai_S2 path CRC32s:", path_map)
print("Matches:", {k: path_map.get(k) for k in [2729465105]})

# Also check what AnimationClip m_ClipBindingConstant / m_MuscleClip has in UnityPy
for ab_name in ("_batch11.ab", "_batch12.ab"):
    ab = CDN_ROOT / "14_effect" / ab_name
    if not ab.exists():
        ab = next((CDN_ROOT / "14_effect").rglob(ab_name), None)
    if ab and ab.exists():
        env = load_ab(ab)
        for o in env.objects:
            if o.type.name == "AnimationClip" and o.peek_name() in ("QingDai_S2_Background_touch2", "Benten_S3_Background_touch3", "FX_Clotho_S2_Background_touch1", "FX_Mist_S3_Background_chat"):
                tt = o.read_typetree()
                mc = tt.get("m_MuscleClip", {}).get("m_Clip", {})
                print(f"Clip {o.peek_name()} mc keys:", list(mc.keys()), "streamed data len:", len(mc.get("m_StreamedClip", {}).get("data", [])), "dense float len:", len(mc.get("m_DenseClip", {}).get("m_SampleArray", [])))
