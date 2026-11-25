import json
from pathlib import Path
from PIL import Image, ImageChops

seq_root = Path(r'E:\A灵魂潮汐\tools\_batch_fx_sequences')
out_dir = Path(r'.\_scratch\juewa_s4_after')
out_dir.mkdir(parents=True, exist_ok=True)

# 1. Check pixel densities & loop continuity on 1703_Juewa_S4
j4_seq = seq_root / '1703_Juewa_S4'
print("clip_meta:", (j4_seq / 'clip_meta.json').read_text(encoding='utf-8'))
for clip in ('idle', 'fx_9008193', 'fx_9008194'):
    for ch in ('normal', 'add'):
        p = j4_seq / clip / ch
        if not p.is_dir(): continue
        fs = sorted(p.glob('frame_*.png'))
        nzs = []
        for idx in (0, 1, len(fs)//4, len(fs)//2, len(fs)*3//4, len(fs)-2, len(fs)-1):
            if 0 <= idx < len(fs):
                im = Image.open(fs[idx])
                nz = sum(1 for px in im.get_flattened_data() if px[3] > 5)
                nzs.append((idx, nz))
        # Also compare frame 0 vs frame -1 max diff for idle seamlessness
        diff_info = ''
        if clip == 'idle' and len(fs) >= 2:
            d = ImageChops.difference(Image.open(fs[0]), Image.open(fs[-1]))
            mx = max(max(px) for px in d.get_flattened_data())
            diff_info = f' f0_vs_last_maxdiff={mx}'
        print(f"1703 {clip}/{ch}: {len(fs)} frames -> {nzs}{diff_info}")

# 2. Check 1202_Virgina_S3 & 1801_SakuyaMako_S2 non-empty bboxes
for sk, clips in [('1202_Virgina_S3', ['fx_9008114']), ('1801_SakuyaMako_S2', ['fx_9008113'])]:
    for c in clips:
        for ch in ('normal', 'add'):
            p = seq_root / sk / c / ch
            if not p.is_dir(): continue
            fs = sorted(p.glob('frame_*.png'))
            ne = [i for i, fp in enumerate(fs) if Image.open(fp).getbbox() is not None]
            sb = Image.open(fs[ne[len(ne)//2]]).getbbox() if ne else None
            print(f"{sk} {c}/{ch}: {len(ne)}/{len(fs)} non-empty frames, mid_bbox={sb}")

# 3. Render 2x2 grids for 1703_Juewa_S4 (idle, fx_9008193, fx_9008194)
bg_p = Path(r'E:\A灵魂潮汐\Live2D与Spine模型\spine\九华\宇宙恋曲\submodels\bg_static\bg_1703_juewa_s4.png')
bg = Image.open(bg_p).convert('RGBA').resize((884, 588), Image.Resampling.LANCZOS)

for clip, idxs in [('idle', [0, 20, 40, 79]), ('fx_9008193', [10, 25, 45, 70]), ('fx_9008194', [25, 45, 65, 95])]:
    grid = Image.new('RGB', (884, 588))
    fs_n = sorted((j4_seq / clip / 'normal').glob('frame_*.png')) if (j4_seq / clip / 'normal').is_dir() else []
    fs_a = sorted((j4_seq / clip / 'add').glob('frame_*.png')) if (j4_seq / clip / 'add').is_dir() else []
    tot = max(len(fs_n), len(fs_a))
    for k, fi in enumerate(idxs):
        fi = min(fi, max(0, tot - 1))
        base = bg.copy()
        if fi < len(fs_n):
            base = Image.alpha_composite(base, Image.open(fs_n[fi]).convert('RGBA'))
        if fi < len(fs_a):
            base = ImageChops.add(base.convert('RGB'), Image.open(fs_a[fi]).convert('RGB')).convert('RGBA')
        grid.paste(base.convert('RGB').resize((442, 294), Image.Resampling.LANCZOS), ((k % 2) * 442, (k // 2) * 294))
    grid.save(out_dir / f'{clip}_grid_after_50pct.jpg', 'JPEG', quality=80)
print("Saved after grids to", out_dir)
EOF