import json
import shutil
import sys
from pathlib import Path

TOOLS_DIR = Path(r"E:\A灵魂潮汐\tools")
sys.path.insert(0, str(TOOLS_DIR))
import batch_fx_exporter as bfe

SCRATCH_DIR = Path(r".\_scratch")
MANIFEST_PATH = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json")
SUB_MANIFEST = SCRATCH_DIR / "fx_manifest_rot3d_27.json"
LOG_PATH = SCRATCH_DIR / "unity_rot3d_27.log"
SUMMARY_PATH = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\batch_unity_summary.json")

manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
target_skins = []
for s in manifest["skins"]:
    has_rot3d = any(
        n.get("rotation3D") or n.get("rotOverLifeSeparateAxes")
        for c in s["clips"]
        for n in c["nodes"]
    )
    if has_rot3d:
        target_skins.append(s)

print(f"Filtered skins with rotation3D/rotOverLifeSeparateAxes: {len(target_skins)}", flush=True)
print("Keys:", [s["skin_key"] for s in target_skins], flush=True)

for s in target_skins:
    out_dir = Path(s["output_dir"])
    if out_dir.exists():
        shutil.rmtree(out_dir)

SUB_MANIFEST.write_text(json.dumps({"skins": target_skins}, ensure_ascii=False), encoding="utf-8")
rc = bfe.run_unity_batch(SUB_MANIFEST, LOG_PATH)
print(f"Unity exit code: {rc}", flush=True)
if rc != 0:
    raise SystemExit(rc)

summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8-sig"))
print(f"Summary: ok={summary.get('ok')}, errors={summary.get('errors')}", flush=True)
if summary.get("errors", 0) != 0:
    raise SystemExit(2)
