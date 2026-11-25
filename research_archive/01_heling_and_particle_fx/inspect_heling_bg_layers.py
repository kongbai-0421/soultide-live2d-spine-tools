import sys, json
from pathlib import Path
from PIL import Image

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

cab_idx = json.loads(Path(r"E:\A灵魂潮汐\tools\_cab_index_cache.json").read_text(encoding="utf-8"))
print("cab_idx sample keys:", list(cab_idx.items())[:3])
env = load_ab(CDN_ROOT / "03_prefabs" / "art_prefabs.ab")
objs = {o.path_id: o for o in env.objects}

root_tr = None
for o in env.objects:
    if o.type.name == "GameObject":
        tt = o.read_typetree()
        if tt.get("m_Name") == "HeLing_S2_Background":
            for c in tt.get("m_Component", []):
                co = objs.get(c["component"]["m_PathID"])
                if co and co.type.name in ("Transform", "RectTransform"):
                    if (co.read_typetree().get("m_Father") or {}).get("m_PathID", 0) == 0:
                        root_tr = co.path_id
                        break

out_dir = Path(r".\_scratch\heling_orig_layers")
out_dir.mkdir(exist_ok=True)

def resolve_sprite(ext_path, pid):
    if not ext_path: return None, None, None
    cab = Path(ext_path).name
    ab_rel = cab_idx.get(cab) or cab_idx.get(cab.lower())
    if not ab_rel:
        print("  CAB NOT FOUND:", cab, ext_path)
        return None, None, cab
    ab_path = Path(ab_rel) if Path(ab_rel).is_absolute() else (CDN_ROOT / ab_rel)
    e2 = load_ab(ab_path)
    for o in e2.objects:
        if o.path_id == pid:
            d = o.read()
            return getattr(d, "m_Name", getattr(d, "name", "?")), d.image, str(ab_path)
    return None, None, str(ab_path)

def walk(tr_pid, prefix="", parent_xy=(0.0, 0.0), parent_scale=(1.0, 1.0)):
    tr = objs[tr_pid].read_typetree()
    go = objs[tr["m_GameObject"]["m_PathID"]].read_typetree()
    nm = go.get("m_Name", "?")
    act = go.get("m_IsActive", 1)
    path = f"{prefix}/{nm}" if prefix else nm
    ap = tr.get("m_AnchoredPosition") or tr.get("m_LocalPosition") or {}
    sd = tr.get("m_SizeDelta") or {}
    sc = tr.get("m_LocalScale") or {"x":1,"y":1,"z":1}
    wx = parent_xy[0] + ap.get("x", 0.0) * parent_scale[0]
    wy = parent_xy[1] + ap.get("y", 0.0) * parent_scale[1]
    wsx = parent_scale[0] * sc.get("x", 1.0)
    wsy = parent_scale[1] * sc.get("y", 1.0)

    for c in go.get("m_Component", []):
        co = objs.get(c["component"]["m_PathID"])
        if not co or co.type.name != "MonoBehaviour": continue
        ctt = co.read_typetree()
        if "m_Sprite" in ctt and "Limit" not in path and act:
            sp = ctt["m_Sprite"]
            fid, pid = sp.get("m_FileID", 0), sp.get("m_PathID", 0)
            ext = co.assets_file.externals[fid - 1].path if fid > 0 and fid - 1 < len(co.assets_file.externals) else None
            print(f"{path} | fid={fid} pid={pid} ext={ext} | world=({wx:.1f},{wy:.1f}) sizeDelta=({sd.get('x',0):.1f},{sd.get('y',0):.1f}) scale=({wsx:.3f},{wsy:.3f})")
            sname, im, abp = resolve_sprite(ext, pid)
            print(f"   -> sprite={sname} size={im.size if im else None} ab={abp}")
            if im:
                safe = path.replace("/", "__")
                im.save(out_dir / f"{safe}__{sname}.png")
                bg = Image.new("RGBA", im.size, (255, 0, 255, 255))
                comp = Image.alpha_composite(bg, im.convert("RGBA")).convert("RGB")
                comp.resize((max(1, im.width//3), max(1, im.height//3)), Image.Resampling.LANCZOS).save(out_dir / f"preview_{safe}.jpg", "JPEG", quality=80)
    for ch in tr.get("m_Children", []):
        if ch["m_PathID"]:
            walk(ch["m_PathID"], path, (wx, wy), (wsx, wsy))

walk(root_tr)
