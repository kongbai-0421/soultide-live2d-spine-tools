import os, sys, json
from pathlib import Path
from PIL import Image, ImageChops
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc
import batch_fx_exporter as bfe

# 1. Create visual composite frames of CURRENT 1703_Juewa_S4 FX on top of bg_static (compressed 50% JPG quality=80)
seq = Path(r'E:\A灵魂潮汐\tools\_batch_fx_sequences\1703_Juewa_S4')
bg_p = Path(r'E:\A灵魂潮汐\Live2D与Spine模型\spine\九华\宇宙恋曲\submodels\bg_static\bg_1703_juewa_s4.png')
bg = Image.open(bg_p).convert('RGBA').resize((884, 588), Image.Resampling.LANCZOS)

out_dir = Path(r'.\_scratch\juewa_s4_preview')
out_dir.mkdir(parents=True, exist_ok=True)

def comp_frame(clip, fidx, out_name):
    base = bg.copy()
    np = seq / clip / 'normal' / f'frame_{fidx:04d}.png'
    ap = seq / clip / 'add' / f'frame_{fidx:04d}.png'
    if np.exists():
        im = Image.open(np).convert('RGBA')
        base = Image.alpha_composite(base, im)
    if ap.exists():
        im = Image.open(ap).convert('RGBA')
        base_rgb = base.convert('RGB')
        im_rgb = im.convert('RGB')
        base = ImageChops.add(base_rgb, im_rgb).convert('RGBA')
    w, h = max(1, base.width // 2), max(1, base.height // 2)
    base.convert('RGB').resize((w, h), Image.Resampling.LANCZOS).save(out_dir / out_name, 'JPEG', quality=80)

# Build a 2x2 grid for idle (f0, f6, f12, f18) and fx_9008193 (f10, f34, f60, f90) and fx_9008194 (f15, f30, f45, f60)
for clip, idxs in [('idle', [0, 6, 12, 18]), ('fx_9008193', [6, 18, 34, 60]), ('fx_9008194', [14, 24, 39, 55])]:
    grid = Image.new('RGB', (884, 588))
    for k, fi in enumerate(idxs):
        base = bg.copy()
        np = seq / clip / 'normal' / f'frame_{fi:04d}.png'
        ap = seq / clip / 'add' / f'frame_{fi:04d}.png'
        if np.exists():
            base = Image.alpha_composite(base, Image.open(np).convert('RGBA'))
        if ap.exists():
            base = ImageChops.add(base.convert('RGB'), Image.open(ap).convert('RGB')).convert('RGBA')
        tile = base.convert('RGB').resize((442, 294), Image.Resampling.LANCZOS)
        grid.paste(tile, ((k % 2) * 442, (k // 2) * 294))
    grid.save(out_dir / f'{clip}_grid_50pct.jpg', 'JPEG', quality=80)
print('Saved grids in', out_dir)

# 2. Check Point_Root & RectTransform layout for Virgina_S3, Colcher_S2, Freesia_S5, Juewa_S4, Aurora_S4
ui_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'ui.ab')
art_env = sc.load_ab(sc.CDN_ROOT / '03_prefabs' / 'art_prefabs.ab')
ui_objs = {o.path_id: o for o in ui_env.objects}
art_objs = {o.path_id: o for o in art_env.objects}
ui_go = {o.peek_name().lower(): o.path_id for o in ui_env.objects if o.type.name == 'GameObject' and o.peek_name()}

for bg_name in ['virgina_s3_background', 'colcher_s2_background', 'freesia_s5_background', 'juewa_s4_background', 'aurora_s4_background']:
    gid = ui_go.get(bg_name)
    if not gid: continue
    print(f'\n=== {bg_name} Point_Root chain ===')
    def walk(g_id, path=''):
        go = ui_objs[g_id].read()
        cur = f'{path}/{go.m_Name}'
        rt = None
        for cr in go.m_Component:
            co = ui_objs.get(cr.component.path_id)
            if co and co.type.name in ('Transform', 'RectTransform'):
                rt = co.read()
        if any(k in cur.lower() for k in ('point_root', 'spine_scale', 'souldress_', 'person', 'cv_point')):
            lp, ls = rt.m_LocalPosition, rt.m_LocalScale
            ap = getattr(rt, 'm_AnchoredPosition', None)
            ap_s = f'anch=({ap.x:.1f},{ap.y:.1f})' if ap else ''
            print(f'  [{go.m_IsActive}] {cur} lpos=({lp.x:.1f},{lp.y:.1f}) lscale=({ls.x:.4f},{ls.y:.4f}) {ap_s}')
        if rt and hasattr(rt, 'm_Children'):
            for ch in rt.m_Children:
                if ch.path_id in ui_objs:
                    walk(ui_objs[ch.path_id].read().m_GameObject.path_id, cur)
    walk(gid)
EOF