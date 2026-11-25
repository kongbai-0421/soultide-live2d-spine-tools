import os, json, io, hashlib
from collections import Counter, defaultdict
from pathlib import Path
from PIL import Image
import numpy as np

L2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")

ext_bytes = Counter()
ext_counts = Counter()
tex_res = Counter()
total_vram_mb = 0.0
model_sizes = []
has_submodels = 0
audio_by_doll = defaultdict(lambda: {"files": 0, "bytes": 0, "unique_names": set(), "unique_bytes": 0})
sample_model3 = None
l2d_model_count = 0

for doll_dir in sorted(L2D_ROOT.iterdir()):
    if not doll_dir.is_dir(): continue
    for skin_dir in sorted(doll_dir.iterdir()):
        if not skin_dir.is_dir(): continue
        m3s = list(skin_dir.glob("*.model3.json"))
        if not m3s: continue
        l2d_model_count += 1
        if sample_model3 is None and doll_dir.name == "和铃":
            sample_model3 = m3s[0]
        if (skin_dir / "submodels").exists():
            has_submodels += 1
        s_bytes = 0
        s_tex = 0
        s_aud = 0
        s_vram = 0.0
        for root, dirs, files in os.walk(skin_dir):
            for fn in files:
                p = os.path.join(root, fn)
                sz = os.path.getsize(p)
                ext = os.path.splitext(fn)[1].lower()
                ext_bytes[ext] += sz
                ext_counts[ext] += 1
                s_bytes += sz
                if ext in (".png", ".webp", ".jpg"):
                    s_tex += sz
                    try:
                        with Image.open(p) as im:
                            w, h = im.size
                        tex_res[f"{w}x{h}"] += 1
                        v = w * h * 4 / (1024 * 1024)
                        total_vram_mb += v
                        s_vram += v
                    except Exception:
                        pass
                elif ext in (".ogg", ".wav", ".mp3"):
                    s_aud += sz
                    info = audio_by_doll[doll_dir.name]
                    info["files"] += 1
                    info["bytes"] += sz
                    key = (fn.lower(), sz)
                    if key not in info["unique_names"]:
                        info["unique_names"].add(key)
                        info["unique_bytes"] += sz
        model_sizes.append((s_bytes, s_tex, s_aud, s_vram, f"{doll_dir.name}/{skin_dir.name}"))

print(f"=== LIVE2D FLEET AUDIT ({l2d_model_count} models) ===")
print(f"with_submodels: {has_submodels}")
total_b = sum(ext_bytes.values())
print(f"Total disk size: {total_b/(1024*1024):.2f} MB ({total_b/(1024**3):.2f} GB)")
for ext, b in ext_bytes.most_common(12):
    print(f"  {ext:8s}: {ext_counts[ext]:6d} files  {b/(1024*1024):8.2f} MB ({b/max(1,total_b)*100:5.1f}%)")
print(f"Total texture VRAM (all models combined): {total_vram_mb:.1f} MB (avg {total_vram_mb/max(1,l2d_model_count):.1f} MB/model)")
print("Texture resolutions:", tex_res.most_common(12))

tot_aud_b = sum(v["bytes"] for v in audio_by_doll.values())
uniq_aud_b = sum(v["unique_bytes"] for v in audio_by_doll.values())
print(f"\nAudio across skins of same doll: total={tot_aud_b/1024/1024:.2f} MB, unique={uniq_aud_b/1024/1024:.2f} MB, duplicate={(tot_aud_b-uniq_aud_b)/1024/1024:.2f} MB ({(1-uniq_aud_b/max(1,tot_aud_b))*100:.1f}%)")

model_sizes.sort(reverse=True)
print("\nTop 10 largest Live2D models:")
for sb, st, sa, sv, rel in model_sizes[:10]:
    print(f"  {rel:25s}: total={sb/1024/1024:6.2f} MB (tex={st/1024/1024:5.2f} MB, audio={sa/1024/1024:5.2f} MB, VRAM={sv:5.1f} MB)")

# Benchmark lossless exact=True WebP on 5 Live2D PNGs
sample_pngs = []
for _, _, _, _, rel in model_sizes[:5]:
    p_dir = L2D_ROOT / rel
    for f in sorted(p_dir.rglob("*.png"))[:1]:
        sample_pngs.append((rel, f))

print("\n=== Sample Lossless Exact WebP Benchmark on 5 Live2D PNGs ===")
orig_sum = 0
webp_sum = 0
for rel, p in sample_pngs:
    orig = p.stat().st_size
    with Image.open(p) as im:
        rgba = im.convert("RGBA")
        buf = io.BytesIO()
        rgba.save(buf, "WEBP", lossless=True, exact=True, quality=100, method=4)
        wsz = len(buf.getvalue())
        arr = np.array(rgba)
        emp = (arr[:,:,3] == 0).mean() * 100
        orig_sum += orig
        webp_sum += wsz
        print(f"  {rel:22s} {p.name:28s} {im.size[0]}x{im.size[1]} empty={emp:4.1f}% | PNG={orig/1024:7.1f}KB -> WebP_exact={wsz/1024:7.1f}KB ({(1-wsz/orig)*100:4.1f}% saved)")
print(f"  Sample avg savings: {(1-webp_sum/max(1,orig_sum))*100:.1f}%")

if sample_model3:
    print(f"\n=== Sample model3.json ({sample_model3}) ===")
    c = json.loads(sample_model3.read_text(encoding="utf-8"))
    print("  Version:", c.get("Version"), "FileReferences keys:", list(c.get("FileReferences", {}).keys()))
    print("  Textures:", c.get("FileReferences", {}).get("Textures"))
    print("  Options:", c.get("Options"))
    print("  Files in dir:", [x.name for x in sorted(sample_model3.parent.iterdir())])
