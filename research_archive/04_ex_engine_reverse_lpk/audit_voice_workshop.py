import os, re, json, subprocess
from pathlib import Path
import numpy as np

L2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
samples = list((L2D_ROOT / "克拉丽丝" / "夕拾朝珠" / "audio").glob("*.ogg"))[:6]
samples += list((L2D_ROOT / "和铃" / "古锦新韵" / "audio").glob("*.ogg"))[:4]

# Check ffprobe
ffprobe = None
for cand in ["ffprobe", r"C:\ffmpeg\bin\ffprobe.exe"]:
    try:
        subprocess.run([cand, "-version"], capture_output=True, check=True)
        ffprobe = cand; break
    except Exception:
        pass
print("ffprobe:", ffprobe)

if ffprobe:
    print("=== Current OGG Encoding Specs ===")
    for p in samples:
        r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0",
                            "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate,duration",
                            "-of", "json", str(p)], capture_output=True, text=True)
        st = json.loads(r.stdout)["streams"][0]
        sz = p.stat().st_size
        dur = float(st["duration"])
        eff_br = sz * 8 / max(0.01, dur) / 1000.0
        # Check stereo L-R diff and head/tail silence
        r2 = subprocess.run(["ffmpeg", "-i", str(p), "-f", "s16le", "-acodec", "pcm_s16le", "-"], capture_output=True)
        pcm = np.frombuffer(r2.stdout, dtype=np.int16)
        ch = int(st["channels"])
        sr = int(st["sample_rate"])
        extra = ""
        if ch == 2 and len(pcm) >= 2:
            L, R = pcm[0::2].astype(np.int32), pcm[1::2].astype(np.int32)
            diff = int(np.abs(L - R).max())
            rms_diff = float(np.sqrt(np.mean((L - R) ** 2)))
            extra = f" | L-R max={diff} rms={rms_diff:.1f}"
            mono = L
        else:
            mono = pcm
        # Silence at head/tail (threshold < 120 out of 32768 ~ -48 dBFS)
        nz = np.where(np.abs(mono) > 120)[0]
        if len(nz) > 0:
            head_s = nz[0] / sr
            tail_s = (len(mono) - 1 - nz[-1]) / sr
            extra += f" | sil=({head_s:.2f}s,{tail_s:.2f}s)"
        print(f"  {p.parent.parent.parent.name}/{p.name:28s}: {st['codec_name']} {sr}Hz ch={ch} eff={eff_br:5.0f}kbps dur={dur:.2f}s sz={sz/1024:5.1f}KB{extra}")

    # Test re-encoding 3 sample clips to mono Vorbis at q=1 (~48-56kbps), q=2 (~64kbps), q=3 (~80kbps) + 32kHz/44.1kHz + silence trim!
    print("\n=== Re-encode Benchmark (Vorbis Mono, Speech-Optimized) ===")
    test_files = samples[:4]
    for label, args in [
        ("Vorbis Mono 44.1kHz -q:a 3 (~80k)", ["-ac", "1", "-ar", "44100", "-c:a", "libvorbis", "-q:a", "3"]),
        ("Vorbis Mono 44.1kHz -q:a 2 (~64k)", ["-ac", "1", "-ar", "44100", "-c:a", "libvorbis", "-q:a", "2"]),
        ("Vorbis Mono 44.1kHz -q:a 1 (~48k)", ["-ac", "1", "-ar", "44100", "-c:a", "libvorbis", "-q:a", "1"]),
        ("Vorbis Mono 32kHz   -q:a 2 (~56k)", ["-ac", "1", "-ar", "32000", "-c:a", "libvorbis", "-q:a", "2"]),
        ("Vorbis Mono 32kHz   -q:a 1 (~42k)", ["-ac", "1", "-ar", "32000", "-c:a", "libvorbis", "-q:a", "1"]),
    ]:
        orig_b = 0; new_b = 0
        for p in test_files:
            orig_b += p.stat().st_size
            out_p = Path(r".\_scratch\tmp_aud.ogg")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), *args, str(out_p)], check=True)
            new_b += out_p.stat().st_size
        print(f"  {label:38s}: {orig_b/1024:6.1f}KB -> {new_b/1024:6.1f}KB ({(1-new_b/orig_b)*100:5.1f}% saved)")

# Check unused .ogg files across all 182 Live2D models
unused_n = 0; unused_b = 0; total_n = 0
for d in sorted(L2D_ROOT.iterdir()):
    if not d.is_dir(): continue
    for s in sorted(d.iterdir()):
        aud = s / "audio"
        if not aud.is_dir(): continue
        used = set()
        for cf in s.glob("*.model3.json"):
            txt = cf.read_text(encoding="utf-8", errors="ignore")
            for m in re.findall(r'audio/([^"\\]+\.ogg)', txt, re.I):
                used.add(m.lower())
        for f in aud.glob("*.ogg"):
            total_n += 1
            if f.name.lower() not in used:
                unused_n += 1
                unused_b += f.stat().st_size
print(f"\nUnused .ogg across all 182 Live2D skins: {unused_n} / {total_n} ({unused_b/1024/1024:.2f} MB)")
