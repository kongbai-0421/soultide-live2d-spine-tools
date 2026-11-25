"""Resumable batch runner for Unity SpineParticleExporter v2 (104 skins) + Zero-Crossfade GPU Recorder (73 GPU skins)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

UNITY = r"D:\Program Files\Unity\Hub\Editor\2021.3.34f1\Editor\Unity.exe"
PROJ = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity")
EXP_OUT = Path(r"E:\A灵魂潮汐\tools\_batch_fx_particles_v2")
GPU_OUT = Path(r"E:\A灵魂潮汐\tools\_batch_fx_gpu_v2")


def main() -> None:
    EXP_OUT.mkdir(parents=True, exist_ok=True)
    GPU_OUT.mkdir(parents=True, exist_ok=True)

    # 1. SpineParticleExporter v2 for all missing skins
    full_mf = json.loads((PROJ / "fx_manifest.json").read_text(encoding="utf-8-sig"))
    all_keys = [s["skin_key"] for s in full_mf["skins"]]
    todo_exp = [k for k in all_keys if not (EXP_OUT / f"{k}.json").is_file() or (EXP_OUT / f"{k}.json").stat().st_size < 100]
    print(f"[Phase 1] ParticleExport v2: total={len(all_keys)}, already_done={len(all_keys)-len(todo_exp)}, todo={len(todo_exp)}", flush=True)

    if todo_exp:
        # Process in chunks of 35 skins for crisp progress & memory hygiene
        for ci in range(0, len(todo_exp), 35):
            chunk = todo_exp[ci : ci + 35]
            kf = PROJ / f"_exp_chunk_{ci}.txt"
            kf.write_text("\n".join(chunk) + "\n", encoding="utf-8")
            t0 = time.time()
            print(f"  [Exp chunk {ci // 35 + 1}] {len(chunk)} skins ({chunk[0]} .. {chunk[-1]})...", flush=True)
            r = subprocess.run([
                UNITY, "-batchmode", "-quit", "-nographics", "-projectPath", str(PROJ),
                "-executeMethod", "SoulTideSpineParticleExporter.ExportBatch",
                "-fxManifest", str(PROJ / "fx_manifest.json"),
                "-skinKeysFile", str(kf),
                "-outDir", str(EXP_OUT),
                "-logFile", str(PROJ / f"_log_exp_chunk_{ci}.log"),
            ])
            print(f"  [Exp chunk {ci // 35 + 1}] rc={r.returncode} ({time.time() - t0:.1f}s)", flush=True)
            if r.returncode != 0:
                raise SystemExit(r.returncode)

    # 2. Zero-Crossfade GPU Recorder for all missing GPU skins
    gpu_mf = json.loads((PROJ / "fx_gpu_bands_manifest.json").read_text(encoding="utf-8-sig"))
    todo_gpu_skins = []
    for s in gpu_mf["skins"]:
        sk = s["skin_key"]
        meta_p = GPU_OUT / sk / "clip_meta.json"
        if meta_p.is_file():
            try:
                m = json.loads(meta_p.read_text(encoding="utf-8-sig"))
                want_clips = {c["clip"] for c in s["clips"]}
                got_clips = set((m.get("clips") or {}).keys())
                if want_clips.issubset(got_clips):
                    continue
            except Exception:
                pass
        todo_gpu_skins.append(s)

    print(f"[Phase 2] Zero-Crossfade GPU Recorder: total={len(gpu_mf['skins'])}, already_done={len(gpu_mf['skins'])-len(todo_gpu_skins)}, todo={len(todo_gpu_skins)}", flush=True)

    # Process in chunks of 14 skins (~3-4 min per chunk!)
    for ci in range(0, len(todo_gpu_skins), 14):
        chunk = todo_gpu_skins[ci : ci + 14]
        sub_mf = PROJ / f"_gpu_chunk_{ci}.json"
        sub_mf.write_text(json.dumps({"skins": chunk}, ensure_ascii=False), encoding="utf-8")
        clip_cnt = sum(len(s["clips"]) for s in chunk)
        t0 = time.time()
        print(f"  [GPU chunk {ci // 14 + 1}] {len(chunk)} skins, {clip_cnt} clips ({chunk[0]['skin_key']} .. {chunk[-1]['skin_key']})...", flush=True)
        r = subprocess.run([
            UNITY, "-batchmode", "-quit", "-projectPath", str(PROJ),
            "-executeMethod", "SoulTideBatchFxRecorder.BuildAndCaptureAll",
            "-fxManifest", str(sub_mf),
            "-logFile", str(PROJ / f"_log_gpu_chunk_{ci}.log"),
        ])
        print(f"  [GPU chunk {ci // 14 + 1}] rc={r.returncode} ({time.time() - t0:.1f}s)", flush=True)
        if r.returncode != 0:
            raise SystemExit(r.returncode)

    print("\nALL UNITY V2 EXPORTS & GPU RECORDINGS COMPLETE!", flush=True)


if __name__ == "__main__":
    main()
