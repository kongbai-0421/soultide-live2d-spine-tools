import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
import batch_fx_exporter as b

parser = argparse.ArgumentParser()
parser.add_argument("--start-chunk", type=int, default=0)
args = parser.parse_args()

SC = Path(r".\_scratch")
MANIFEST = b.UNITY_PROJ / "fx_manifest.json"
m = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
skins = m["skins"]
print(f"Total skins in fx_manifest: {len(skins)}", flush=True)

# 3 chunks: 34, 34, 33
sizes = [34, 34, len(skins) - 68]
idx = 0
chunks = []
for ci, sz in enumerate(sizes):
    sub = skins[idx : idx + sz]
    idx += sz
    cp = SC / f"fx_chunk_{ci}.json"
    cp.write_text(json.dumps({"skins": sub}, ensure_ascii=False), encoding="utf-8")
    chunks.append((ci, cp, len(sub)))

total_ok = 0
total_err = 0
for ci, cp, count in chunks:
    if ci < args.start_chunk:
        continue
    log_p = SC / f"unity_full_chunk_{ci}.log"
    sum_p = SC / "batch_unity_summary.json"
    if sum_p.is_file():
        sum_p.unlink()
    print(f"\n--- Running chunk {ci} ({count} skins) -> {cp} ---", flush=True)
    rc = b.run_unity_batch(cp, log_p)
    if rc != 0:
        raise RuntimeError(f"Chunk {ci} exited with rc={rc} (see {log_p})")
    if not sum_p.is_file():
        raise RuntimeError(f"Missing summary {sum_p} after chunk {ci}")
    summary = json.loads(sum_p.read_text(encoding="utf-8-sig"))
    ok = int(summary.get("ok", 0))
    err = int(summary.get("errors", 0))
    print(f"Chunk {ci} summary: ok={ok}, errors={err}", flush=True)
    if err != 0 or ok != count:
        raise RuntimeError(f"Chunk {ci} summary mismatch: ok={ok}/{count}, errors={err}")
    total_ok += ok
    total_err += err

print(f"\nALL CHUNKS COMPLETE: total_ok={total_ok}, total_err={total_err}", flush=True)
