import json, re, sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as bfe
from soultide_common import CDN_ROOT, DECOMPILED_DIR, load_ab, parse_lua_flat_table

# First compress 5 preview PNGs to 50% WxH JPG quality=80 in scratch/audit_previews
out_prev = Path(r".\_scratch\audit_previews")
out_prev.mkdir(parents=True, exist_ok=True)
seq_root = Path(r"E:\A灵魂潮汐\tools\_batch_fx_sequences")
samples = [
    ("503_Benten_S4/idle/add/frame_0036.png", "chk_503_Benten_S4_add_50pct.jpg"),
    ("1101_NicoletteLamel_S2/idle/add/frame_0036.png", "chk_1101_Nicolette_S2_add_50pct.jpg"),
    ("601_Asuna_S6/idle/add/frame_0036.png", "chk_601_Asuna_S6_add_50pct.jpg"),
    ("4501_RubyRose_S2/fx_9008180/normal/frame_0126.png", "chk_4501_RubyRose_S2_normal_50pct.jpg"),
]
for rel, dst_name in samples:
    src = seq_root / rel
    if src.exists():
        img = Image.open(src).convert("RGBA")
        # Composite onto dark checkerboard for clear visibility
        bg = Image.new("RGBA", img.size, (18, 22, 30, 255))
        comp = Image.alpha_composite(bg, img).convert("RGB")
        w, h = max(1, comp.width // 2), max(1, comp.height // 2)
        comp.resize((w, h), Image.Resampling.LANCZOS).save(out_prev / dst_name, "JPEG", quality=80)

# Compare runtime SoulDress_* (exact AssetBundle container path from CfgElementEntityTable) vs ui.ab baked mockup!
indexer = bfe.AssetIndexer()
repo = bfe.FullI18nRepo()
elem_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgElementEntityTable.lua")
ctrl_tbl = parse_lua_flat_table(DECOMPILED_DIR / "CfgSoulSpineActionControlTable.lua")

ui_container = {k.lower(): v.path_id for k, v in (indexer.ui_env.container or {}).items()}
art_container = indexer.art_container

def find_node(pid, objs, name):
    def walk(gid, ap, asc):
        g = objs[gid].read()
        _, _, lp, ls, _ = bfe._node_local_tf(g, objs, False)
        nx, ny, nz = ap[0] + asc[0]*lp[0], ap[1] + asc[1]*lp[1], ap[2] + asc[2]*lp[2]
        ns = (asc[0]*ls[0], asc[1]*ls[1], asc[2]*ls[2])
        if g.m_Name == name:
            return (nx, ny, nz), ns, lp, ls, g.m_IsActive
        for c in g.m_Component:
            co = objs.get(c.component.path_id)
            if co and co.type.name in ("RectTransform", "Transform"):
                for ch in co.read().m_Children:
                    ctf = objs.get(ch.path_id)
                    if ctf:
                        r = walk(ctf.read().m_GameObject.path_id, (nx, ny, nz), ns)
                        if r: return r
        return None
    return walk(pid, (0.0,0.0,0.0), (1.0,1.0,1.0))

print("=== Exact container match: ui baked mockup vs runtime SoulDress prefab ===")
for cat in sorted(bfe.build_skin_catalog(repo), key=lambda x: x["ctrl_id"]):
    if not cat.get("effect_prefabs"): continue
    sk = cat["skin_key"]
    cid = cat["ctrl_id"]
    m = re.search(r"SoulAction\s*=\s*(\d+)", ctrl_tbl.get(cid, ""))
    if not m: continue
    eb = elem_tbl.get(int(m.group(1)), "")
    mp = re.search(r'PrefabName\s*=\s*"([^"]+)"', eb)
    if not mp: continue
    pfn = mp.group(1).lower()
    # Find in art_container or ui_container
    hit_pid = None; hit_objs = None; hit_ab = ""
    for cpath, pid in art_container.items():
        if pfn in cpath and cpath.endswith(".prefab"):
            hit_pid, hit_objs, hit_ab = pid, indexer.art_objs, "art"
            break
    if not hit_pid:
        for cpath, pid in ui_container.items():
            if pfn in cpath and cpath.endswith(".prefab"):
                hit_pid, hit_objs, hit_ab = pid, indexer.ui_objs, "ui"
                break
    bg_pid = indexer.ui_go_by_name.get(Path(cat["bg_prefab"]).name.lower(), [None])[0]
    lay = bfe.inspect_bg_prefab_layout(indexer, cat) if bg_pid else {}
    ui_fx = lay.get("fx_point_root", {})
    sp_sc = find_node(bg_pid, indexer.ui_objs, "Spine_Scale") if bg_pid else None
    pr_bg = find_node(bg_pid, indexer.ui_objs, "Point_Root") if bg_pid else None
    art_pr = find_node(hit_pid, hit_objs, "Point_Root") if hit_pid else None
    art_person = find_node(hit_pid, hit_objs, pfn.split("/")[-1] + "_Person") if hit_pid else None
    rt_sc = (sp_sc[1][0] * art_pr[1][0]) if (sp_sc and art_pr) else (sp_sc[1][0] if sp_sc else None)
    if (rt_sc and abs(rt_sc - ui_fx.get("wsx", 0)) > 0.05) or ui_fx.get("wsz", 1) == 0 or not art_pr or sk in ("402_Freesia_S5", "3501_QingDai_S2", "4501_RubyRose_S2", "1803_SakuyaMako_S4", "502_Benten_S3", "5101_Louisa_S2"):
        print(f"  {sk:22s} ({hit_ab}:{pfn}): ui_fx=({ui_fx.get('wx',0):.1f},{ui_fx.get('wy',0):.1f}) sc=({ui_fx.get('wsx',0):.3f},{ui_fx.get('wsz',0):.3f}) | SpineScale={sp_sc[0][:2] if sp_sc else None} sc={sp_sc[1][:2] if sp_sc else None} | art_PR pos={art_pr[0][:2] if art_pr else None} sc={art_pr[1] if art_pr else None} -> rt_sc={rt_sc}")
