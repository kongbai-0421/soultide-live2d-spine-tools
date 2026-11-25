import json, re, sys
from collections import Counter
from pathlib import Path
from PIL import Image
import numpy as np

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe
from soultide_common import CDN_ROOT, DECOMPILED_DIR, load_ab, parse_lua_flat_table

# 1. Check SoulAction -> CfgElementEntityTable -> runtime prefab path
elem_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgElementEntityTable.lua")
ctrl_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgSoulSpineActionControlTable.lua")
for cid in (402, 1203, 1302, 1703, 2002, 2801, 2803, 3501, 3601, 4501, 503, 603, 101, 1301):
    b = ctrl_tbl.get(cid, "")
    m = re.search(r"SoulAction\s*=\s*(\d+)", b)
    aid = int(m.group(1)) if m else None
    eb = elem_tbl.get(aid, "") if aid else ""
    print(f"Ctrl[{cid}] SoulAction={aid} -> {' '.join(eb.split())[:180]}")

# 2. Check Launch/Main scene / Boot for UICamera
print("\n=== Searching all ABs for UICamera or ReferenceResolution Canvas ===")
for sub in ("00_boot", "01_scenes", "03_prefabs"):
    p = CDN_ROOT / sub
    if not p.exists(): continue
    for ab in sorted(p.rglob("*.ab")):
        if ab.name in ("art_prefabs.ab",): continue
        env = load_ab(ab)
        objs = {o.path_id: o for o in env.objects}
        for o in env.objects:
            if o.type.name == "Camera":
                nm = o.peek_name()
                tt = o.read_typetree()
                go = objs.get(tt.get("m_GameObject", {}).get("m_PathID", 0))
                gn = go.peek_name() if go else "?"
                if "ui" in gn.lower() or sub == "00_boot":
                    print(f"  {sub}/{ab.name}: Cam '{gn}' ortho={tt.get('orthographic')} size={tt.get('orthographic size')} mask={tt.get('m_CullingMask')}")
            elif o.type.name == "GameObject":
                nm = (o.peek_name() or "").lower()
                if "uiroot" in nm or "uicamera" in nm or "uimanager" in nm or "gameentry" in nm:
                    print(f"  {sub}/{ab.name}: GO '{o.peek_name()}'")

# 3. Check ALL nodes across ALL skins with rateOverDistance > 0 & Animator Effect skins
indexer = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
catalog = {c["skin_key"]: c for c in bfe.build_skin_catalog(repo)}
manifest = json.loads(Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json").read_text(encoding="utf-8"))
active_skins = {s["skin_key"] for s in manifest["skins"]}

rate_d_nodes = []
def scan_rd(objs, go_map, pf, sk, src):
    pids = go_map.get(Path(pf).name.lower(), [])
    if not pids: return
    def walk(gid, path):
        g = objs[gid].read()
        if not getattr(g, "m_IsActive", True): return
        tf = None; ps = None
        for c in g.m_Component:
            co = objs.get(c.component.path_id)
            if not co: continue
            if co.type.name in ("Transform", "RectTransform"): tf = co.read()
            elif co.type.name == "ParticleSystem": ps = co.read_typetree()
        cp = f"{path}/{g.m_Name}" if path else g.m_Name
        if ps:
            em = ps.get("EmissionModule", {})
            rd = em.get("rateOverDistance", {})
            if em.get("enabled") and (abs(rd.get("scalar", 0)) > 1e-4 or (rd.get("minMaxState") == 3 and abs(rd.get("minScalar", 0)) > 1e-4)):
                rt = em.get("rateOverTime", {})
                rate_d_nodes.append((sk, src, cp, rd.get("minMaxState"), rd.get("scalar"), rd.get("minScalar"), rt.get("scalar"), len(em.get("m_Bursts", []))))
        if tf:
            for ch in tf.m_Children:
                ctf = objs.get(ch.path_id)
                if ctf: walk(ctf.read().m_GameObject.path_id, cp)
    walk(pids[0], "")

for sk, cat in sorted(catalog.items()):
    if sk not in active_skins: continue
    scan_rd(indexer.ui_objs, indexer.ui_go_by_name, cat["bg_prefab"], sk, "bg")
    for eid, ep in cat.get("effect_prefabs", {}).items():
        scan_rd(indexer.art_objs, indexer.art_go_by_name, ep, sk, f"fx_{eid}")

print(f"\n=== Nodes with EmissionModule.rateOverDistance > 0 ({len(rate_d_nodes)}) ===")
for r in rate_d_nodes:
    print(" ", r)

# 4. Check 402_Freesia_S5 FX_UI_liehen01 texture & Default-ParticleSystem.png & 2002_Ennis_S3 PNG
tex_dir = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Textures")
for tn in ("Default-ParticleSystem.png", "FX_UI_liehen01.png", "Fx_cfl_caihongguang_02.png", "FX_by_trail01.png", "FX_gra_WL_142.png"):
    tp = tex_dir / tn
    if tp.exists():
        arr = np.array(Image.open(tp).convert("RGBA"))
        print(f"  Tex {tn}: size={arr.shape[1]}x{arr.shape[0]} rgb_max={arr[:,:,:3].max()} rgb_mean={arr[:,:,:3].mean():.2f} a_max={arr[:,:,3].max()} a_mean={arr[:,:,3].mean():.2f} a>10_frac={(arr[:,:,3]>10).mean():.4f}")

# Check 2002_Ennis_S3/fx_9008124/normal max frame to see if FX_yinfu01 appears anywhere
d = Path(r"E:\A灵魂潮汐\tools\_batch_fx_sequences\2002_Ennis_S3\fx_9008124\normal")
if d.exists():
    bbs = []
    for p in sorted(d.glob("*.png"))[::15]:
        arr = np.array(Image.open(p).convert("RGBA"))
        nz = np.argwhere(arr[:,:,3] > 0)
        if len(nz):
            bbs.append((p.name, int(nz[:,1].min()), int(nz[:,0].min()), int(nz[:,1].max()), int(nz[:,0].max()), int(len(nz))))
    print(f"2002_Ennis_S3 fx_9008124/normal sampled bbs: {bbs}")

# Also check if any manifest skin's background uses FX_Freesia_S5_Background_Touch01 posui with Main_color/Alpha
print("\n=== Compare existing 503_Benten_S4, 1101_NicoletteLamel_S2, 2001_Ennis_S2, 601_Asuna_S6 rendered PNGs ===")
for rel in ("503_Benten_S4/idle/add", "503_Benten_S4/idle/normal", "1101_NicoletteLamel_S2/idle/add", "2001_Ennis_S2/idle/normal", "601_Asuna_S6/idle/add", "4501_RubyRose_S2/fx_9008180/normal"):
    dp = Path(r"E:\A灵魂潮汐\tools\_batch_fx_sequences") / rel
    if not dp.exists(): continue
    pngs = sorted(dp.glob("*.png"))
    mid = pngs[len(pngs)//2] if pngs else None
    if mid:
        arr = np.array(Image.open(mid).convert("RGBA"))
        mask = arr[:,:,3] > 0 if "normal" in rel else arr[:,:,:3].max(axis=2) > 5
        nz = np.argwhere(mask)
        bb = (int(nz[:,1].min()), int(nz[:,0].min()), int(nz[:,1].max()), int(nz[:,0].max())) if len(nz) else None
        print(f"  {rel}/{mid.name} ({arr.shape[1]}x{arr.shape[0]}): nonzero={len(nz)} bb={bb} max_rgb={arr[:,:,:3].max()} max_a={arr[:,:,3].max()}")
