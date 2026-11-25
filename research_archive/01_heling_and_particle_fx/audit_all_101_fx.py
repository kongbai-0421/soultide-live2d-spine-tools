import json
from pathlib import Path
import numpy as np
from PIL import Image

MANIFEST = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json")
FX_ROOT = Path(r"E:\A灵魂潮汐\tools\_batch_fx_sequences")

m = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
total_skins = len(m["skins"])
total_clips = 0
checked_channels = 0
nonempty_channels = 0
mismatches = []
corrupt_pngs = []
total_pngs = 0

for s in m["skins"]:
    sk = s["skin_key"]
    rw, rh = int(s["render_w"]), int(s["render_h"])
    for c in s["clips"]:
        total_clips += 1
        cn = c["clip"]
        nodes = c["nodes"]
        exp_n = any(
            (n.get("hasMainMaterial", True) and n.get("renderMode", 0) != 5 and not n.get("isAdditive", True))
            or (n.get("trailsEnabled", False) and not n.get("trailIsAdditive", True))
            for n in nodes
        )
        exp_a = any(
            (n.get("hasMainMaterial", True) and n.get("renderMode", 0) != 5 and n.get("isAdditive", True))
            or (n.get("trailsEnabled", False) and n.get("trailIsAdditive", True))
            for n in nodes
        )
        for ch, exp in (("normal", exp_n), ("add", exp_a)):
            checked_channels += 1
            ch_dir = FX_ROOT / sk / cn / ch
            fps = sorted(ch_dir.glob("frame_*.png")) if ch_dir.is_dir() else []
            total_pngs += len(fps)
            nz_cnt = 0
            mx = 0
            # Verify every PNG can open cleanly and check non-empty pixels across sampled + all frames when suspicious
            for idx, fp in enumerate(fps):
                try:
                    if fp.stat().st_size == 0:
                        corrupt_pngs.append(f"{fp} (0 bytes)")
                        continue
                    with Image.open(fp) as im:
                        arr = np.asarray(im.convert("RGBA"))
                    if ch == "add":
                        val = int(arr[:, :, :3].max())
                    else:
                        val = int(arr[:, :, 3].max())
                    if val > 2:
                        nz_cnt += 1
                    if val > mx:
                        mx = val
                except Exception as exc:
                    corrupt_pngs.append(f"{fp}: {exc}")
            actual = nz_cnt > 0
            if actual:
                nonempty_channels += 1
            if exp != actual or (not exp and len(fps) > 0):
                mismatches.append(f"{sk}/{cn}/{ch}: exp={exp} frames={len(fps)} nz={nz_cnt} max={mx}")

print(f"Skins={total_skins}, Clips={total_clips}, CheckedChannels={checked_channels}, NonEmptyChannels={nonempty_channels}, TotalPNGs={total_pngs}")
print(f"CorruptPNGs={len(corrupt_pngs)}")
for e in corrupt_pngs[:20]:
    print("  CORRUPT:", e)
print(f"Mismatches={len(mismatches)}")
for mm in mismatches[:50]:
    print("  MISMATCH:", mm)
