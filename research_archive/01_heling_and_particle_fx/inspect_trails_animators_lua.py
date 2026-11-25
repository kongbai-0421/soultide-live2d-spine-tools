"""Inspect TrailModules, Animators, Freesia_S5/QingDai_S2 anchors, z_scale==0, and Lua SoulSpineCell/Effect placement."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe
from soultide_common import CDN_ROOT, DECOMPILED_DIR, load_ab


def main():
    # 1. Inspect Lua files that handle SoulSpineCell, MainUI, GirlUI, GirlDressShowUI, Effect
    print("=" * 80)
    print("1. Lua files for SoulSpineCell / GirlUI / MainUI / GirlDressShowUI")
    print("=" * 80)
    for target in ("SoulSpineCell.lua", "GirlDressShowUI.lua", "MainUI.lua", "GirlUI.lua"):
        hits = list(DECOMPILED_DIR.rglob(target))
        for h in hits:
            print(f"Found: {h}")
            lines = h.read_text(encoding="utf-8", errors="ignore").splitlines()
            for idx, ln in enumerate(lines, 1):
                if any(k in ln for k in ("Point_Root", "Cv_Point", "goEffectPoint", "Spine_Scale", "PlayUIMount", "PlayNormalEffect", "EffectID", "SpineAction", "SetParent", "Background")):
                    start = max(1, idx - 2)
                    end = min(len(lines), idx + 4)
                    if target in ("SoulSpineCell.lua", "GirlDressShowUI.lua") or any(k in ln for k in ("goEffectPoint", "Point_Root", "Cv_Point", "PlayEffect")):
                        print(f"  L{idx}: {ln.strip()[:160]}")

    # Also read SoulSpineCell.lua completely if small
    ssc = list(DECOMPILED_DIR.rglob("SoulSpineCell.lua"))
    if ssc:
        print("--- Full SoulSpineCell.lua ---")
        for i, ln in enumerate(ssc[0].read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            print(f"  {i:3d}: {ln}")

    # 2. Index ABs and inspect inspect_bg_prefab_layout keys on Freesia_S5, QingDai_S2, etc.
    indexer = bfe.AssetIndexer()
    repo = bfe.FullI18nRepo()
    catalog = {c["skin_key"]: c for c in bfe.build_skin_catalog(repo)}

    print("\n" + "=" * 80)
    print("2. inspect_bg_prefab_layout actual keys & fx_anchor positions across all 109 skins")
    print("=" * 80)
    sample_lay = bfe.inspect_bg_prefab_layout(indexer, catalog["402_Freesia_S5"])
    print("Sample keys:", list(sample_lay.keys()))
    for sk in ["402_Freesia_S5", "3501_QingDai_S2", "503_Benten_S4", "1101_NicoletteLamel_S2", "2001_Ennis_S2", "2301_QuLing_S2", "601_Asuna_S6", "4501_RubyRose_S2"]:
        lay = bfe.inspect_bg_prefab_layout(indexer, catalog[sk])
        print(f"  {sk}: {json.dumps({k: v for k, v in lay.items() if k != 'bg_images'}, ensure_ascii=False)}")

    # Check ALL 109 skins for z_scale==0 or huge fx_point outside canvas
    print("--- Skins where fx_point / fx_scale is unusual or z==0 ---")
    for sk, cat in sorted(catalog.items()):
        try:
            lay = bfe.inspect_bg_prefab_layout(indexer, cat)
            print_it = False
            s = json.dumps({k: v for k, v in lay.items() if k != "bg_images"}, ensure_ascii=False)
            # Check numeric fields
            for k, v in lay.items():
                if isinstance(v, list) and len(v) == 3 and abs(v[2]) < 1e-6:
                    print_it = True
            if "Freesia" in sk or "QingDai" in sk or print_it:
                print(f"  [LAY] {sk}: {s}")
        except Exception as e:
            print(f"  [ERR] {sk}: {e}")

    # 3. Scan ALL UI & Art prefabs for TrailModule, rm==5, Animators, and AnimationClips
    print("\n" + "=" * 80)
    print("3. All TrailModule / rm==5 / Animator nodes in manifest skins")
    print("=" * 80)
    # Index all RuntimeAnimatorController / AnimationClip in 03_prefabs & 14_effect
    anim_objs = {}
    for sub in ("03_prefabs", "14_effect"):
        for ab in sorted((CDN_ROOT / sub).rglob("*.ab")):
            env = load_ab(ab)
            for o in env.objects:
                if o.type.name in ("AnimatorController", "AnimationClip", "Mesh"):
                    anim_objs[(o.assets_file.name, o.path_id)] = (o, ab.name)

    def resolve_ext_plus(af, fid, pid):
        if pid == 0: return None
        cab = af.name if fid == 0 else (Path(af.externals[fid - 1].path).name if 0 <= fid - 1 < len(af.externals) else None)
        if not cab: return None
        return anim_objs.get((cab, pid))

    trail_nodes = []
    rm5_nodes = []
    animator_effects = []
    manifest = json.loads(Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json").read_text(encoding="utf-8"))
    active_skins = {s["skin_key"] for s in manifest["skins"]}

    for sk, cat in sorted(catalog.items()):
        if sk not in active_skins:
            continue
        def scan_pf(objs, go_map, pf_name, src):
            base = Path(pf_name).name.lower()
            pids = go_map.get(base, [])
            if not pids: return
            def walk(gid, path):
                go = objs.get(gid)
                if not go: return
                g = go.read()
                active = getattr(g, "m_IsActive", True)
                if not active:
                    return
                tf = None; ps = None; psr = None; anim = None
                for c in g.m_Component:
                    co = objs.get(c.component.path_id)
                    if not co: continue
                    if co.type.name in ("Transform", "RectTransform"): tf = co.read()
                    elif co.type.name == "ParticleSystem": ps = co.read_typetree()
                    elif co.type.name == "ParticleSystemRenderer": psr = co.read_typetree()
                    elif co.type.name == "Animator": anim = co.read_typetree()
                cp = f"{path}/{g.m_Name}" if path else g.m_Name
                if ps:
                    tr = ps.get("TrailModule", {})
                    rm = psr.get("m_RenderMode", 0) if psr else -1
                    if tr.get("enabled"):
                        trail_nodes.append((sk, src, cp, rm, tr.get("mode"), tr.get("lifetime", {}).get("scalar"), tr.get("widthOverTrail", {}).get("scalar"), tr.get("inheritParticleColor"), len(psr.get("m_Materials", [])) if psr else 0))
                    if rm == 5 and not tr.get("enabled"):
                        rm5_nodes.append((sk, src, cp))
                if anim and anim.get("m_Enabled", 1):
                    cref = anim.get("m_Controller", {})
                    if cref.get("m_PathID", 0) != 0:
                        res = resolve_ext_plus(go.assets_file, cref.get("m_FileID", 0), cref.get("m_PathID", 0))
                        animator_effects.append((sk, src, cp, res[0].peek_name() if res else f"pid={cref.get('m_PathID')}", res[1] if res else "?"))
                if tf:
                    for ch in tf.m_Children:
                        ctf = objs.get(ch.path_id)
                        if ctf: walk(ctf.read().m_GameObject.path_id, cp)
            walk(pids[0], "")

        scan_pf(indexer.ui_objs, indexer.ui_go_by_name, cat["bg_prefab"], "bg")
        for eid, ep in cat.get("effect_prefabs", {}).items():
            scan_pf(indexer.art_objs, indexer.art_go_by_name, ep, f"fx_{eid}")

    print(f"Active TrailModule nodes ({len(trail_nodes)}):")
    for t in trail_nodes:
        print(f"  {t}")
    print(f"Active rm==5 WITHOUT TrailModule ({len(rm5_nodes)}):")
    for r in rm5_nodes:
        print(f"  {r}")
    print(f"Active Animators in UI/Effect prefabs ({len(animator_effects)}):")
    for a in animator_effects:
        print(f"  {a}")

    # 4. Inspect QingDai_S2_Background_touch2 AnimatorController & clips
    print("\n" + "=" * 80)
    print("4. Inspect QingDai_S2_Background_touch2 AnimatorController")
    print("=" * 80)
    pids = indexer.art_go_by_name.get("qingdai_s2_background_touch2", [])
    if pids:
        go = indexer.art_objs[pids[0]].read()
        for c in go.m_Component:
            co = indexer.art_objs.get(c.component.path_id)
            if co and co.type.name == "Animator":
                att = co.read_typetree()
                cref = att.get("m_Controller", {})
                res = resolve_ext_plus(co.assets_file, cref.get("m_FileID", 0), cref.get("m_PathID", 0))
                if res:
                    cobj, cab = res
                    ctt = cobj.read_typetree()
                    print(f"AnimatorController {cobj.peek_name()} ({cab}): m_AnimationClips={ctt.get('m_AnimationClips')}")
                    for clref in ctt.get("m_AnimationClips", []):
                        cres = resolve_ext_plus(cobj.assets_file, clref.get("m_FileID", 0), clref.get("m_PathID", 0))
                        if cres:
                            clobj, clab = cres
                            cltt = clobj.read_typetree()
                            print(f"  Clip {clobj.peek_name()} stop={cltt.get('m_MuscleClip',{}).get('m_StopTime')} wrap={cltt.get('m_WrapMode')}")
                            for k in ("m_PositionCurves", "m_ScaleCurves", "m_FloatCurves", "m_EulerCurves", "m_RotationCurves", "m_PPtrCurves"):
                                arr = cltt.get(k, [])
                                if arr:
                                    print(f"    {k} ({len(arr)}):")
                                    for item in arr:
                                        print(f"      path='{item.get('path')}' attr='{item.get('attribute')}' keys={len(item.get('curve',{}).get('m_Curve',[]))} vals={[(round(kv['time'],2), kv['value']) for kv in item.get('curve',{}).get('m_Curve',[])[:5]]}")


if __name__ == "__main__":
    main()
