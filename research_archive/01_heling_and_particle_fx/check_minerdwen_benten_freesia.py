import json, sys, glob
from pathlib import Path
from PIL import Image
import numpy as np

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe

seq_root = Path(r"E:\A灵魂潮汐\tools\_batch_fx_sequences")
for sk, cl in [
    ("702_Minerdwen_S3", "fx_9008162"),
    ("404_Freesia_S6", "fx_9008181"),
    ("404_Freesia_S6", "fx_9008182"),
    ("1803_SakuyaMako_S4", "fx_9008175"),
    ("4501_RubyRose_S2", "fx_9008180"),
    ("5101_Louisa_S2", "fx_9008206"),
    ("4801_Micha_S2", "fx_9008183"),
    ("402_Freesia_S5", "fx_9008161"),
    ("2002_Ennis_S3", "fx_9008124"),
    ("503_Benten_S4", "idle"),
]:
    for mode in ("normal", "add"):
        fs = sorted((seq_root / sk / cl / mode).glob("frame_*.png"))
        mx = 0
        nz_cnt = 0
        for f in fs[::4]:
            v = int(np.array(Image.open(f)).max())
            if v > 0: nz_cnt += 1
            if v > mx: mx = v
        print(f"SEQ {sk:22s} {cl:11s} {mode:6s} n_frames={len(fs):3d} sampled_nz={nz_cnt} max={mx}")

# Inspect AB objects for specific suspects
idx = bfe.AssetIndexer()

def inspect_ps_nodes(prefab_sub, filter_names=None):
    for k, pid in idx.art_container.items():
        if prefab_sub.lower() in k.lower():
            co = idx.art_objs[pid].read_typetree()
            gpid = co["m_GameObject"]["m_PathID"] if "m_GameObject" in co else pid
            print(f"\n=== {k} ===")
            def walk(gp):
                go = idx.art_objs[gp].read_typetree()
                name = go.get("m_Name", "?")
                tf = None; ps = None; psr = None
                for c in go.get("m_Component", []):
                    o = idx.art_objs.get(c["component"]["m_PathID"])
                    if not o: continue
                    if o.type.name in ("Transform", "RectTransform"): tf = o.read_typetree()
                    elif o.type.name == "ParticleSystem": ps = o.read_typetree()
                    elif o.type.name == "ParticleSystemRenderer": psr = o.read_typetree()
                if ps and (not filter_names or name in filter_names):
                    im = ps.get("InitialModule", {})
                    em = ps.get("EmissionModule", {})
                    se = ps.get("SubModule", {})
                    print(f"  PS {name!r} ls={tf.get('m_LocalScale') if tf else None} sm={ps.get('scalingMode')} sz3d={im.get('size3D')} sz=({im.get('startSize',{}).get('scalar')},{im.get('startSizeY',{}).get('scalar')}) szOL={ps.get('SizeModule',{}).get('enabled')} maxP={im.get('maxNumParticles')} rateT={em.get('rateOverTime',{}).get('scalar')} rateD={em.get('rateOverDistance',{}).get('scalar')} sub_en={se.get('enabled')} sub_list={se.get('subEmitters')}")
                    if psr:
                        print(f"     PSR rm={psr.get('m_RenderMode')} align={psr.get('m_RenderAlignment')} maxPSz={psr.get('m_MaxParticleSize')} minPSz={psr.get('m_MinParticleSize')} normS={psr.get('m_NormalDirection')}")
                if tf:
                    for ch in tf.get("m_Children", []):
                        ct = idx.art_objs.get(ch["m_PathID"])
                        if ct: walk(ct.read_typetree()["m_GameObject"]["m_PathID"])
            walk(gpid)

inspect_ps_nodes("minerdwen_s3")
inspect_ps_nodes("benten_s4_background.prefab", {"cahihonghuan"})
inspect_ps_nodes("ennis_s3", None)
inspect_ps_nodes("freesia_s5_background_touch01", None)
inspect_ps_nodes("rubyrose_s2_background_chat", None)
inspect_ps_nodes("louisa", None)
