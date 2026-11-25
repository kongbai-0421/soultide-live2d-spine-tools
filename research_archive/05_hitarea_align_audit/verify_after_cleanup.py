import hashlib
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(r"D:\A灵魂潮汐-本地化\服务器")
EXT_ROOT = pathlib.Path(r"D:\A灵魂潮汐-本地化\A本地陪伴版\外置资源\Android")
OUT_APK = pathlib.Path(r"D:\A灵魂潮汐-本地化\A本地陪伴版\APK\灵魂潮汐本地化-单机版-r243.apk")

print("=== 1. Critical file existence & sizes ===")
checks = [
    ROOT / "soultide.db",
    ROOT / "offline_cdn" / "Android" / "version.json",
    ROOT / "offline_cdn" / "Android" / "version-local.json",
    ROOT / "offline_cdn" / "Android" / "version-local-active.json",
    ROOT / "offline_cdn" / "Android" / "version-remote.json",
    ROOT / "build" / "patched_bundles_restored",
    ROOT / "mobile_host" / "build" / "mobile-bootstrap-r243.dex",
    ROOT / "apk_output" / "soultide-mobile-multilang-r242.apk",
    ROOT / "apk_output" / "soultide-mobile-multilang-r243.apk",
    OUT_APK,
]
for p in checks:
    assert p.exists(), f"MISSING: {p}"
    info = f"DIR ({len(list(p.iterdir()))} items)" if p.is_dir() else f"{p.stat().st_size:,} bytes"
    print(f"  OK: {p} -> {info}")

print("\n=== 2. Running offline unit tests (python -B) ===")
test_scripts = [
    "test_r243_fixes.py",
    "test_r242_trial_fixes.py",
    "test_r240_fixes.py",
    "test_activity_explore_rules.py",
    "test_activity_snapshot_rules.py",
    "test_maze_settlement_rules.py",
]
for ts in test_scripts:
    res = subprocess.run(
        [sys.executable, "-B", str(ROOT / ts)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = (res.stdout + "\n" + res.stderr).strip().splitlines()[-3:]
    print(f"  [{res.returncode}] {ts}: {' | '.join(tail)}")
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        sys.exit(res.returncode)

print("\n=== 3. Checking offline_cdn/Android vs A本地陪伴版/外置资源/Android video/manifest sync ===")
for rel in [
    "version.json",
    "version-local.json",
    "21_Media/SoulPV/Asuna/PV_Asuna_01.mp4",
    "21_Media/StoryCG/CG_PV.mp4",
]:
    src = ROOT / "offline_cdn" / "Android" / rel
    dst = EXT_ROOT / rel
    assert src.exists() and dst.exists(), f"Missing sync file {rel}"
    h1 = hashlib.md5(src.read_bytes()).hexdigest()
    h2 = hashlib.md5(dst.read_bytes()).hexdigest()
    assert h1 == h2, f"MD5 mismatch for {rel}: {h1} != {h2}"
    print(f"  MATCH ({h1}): {rel}")

print("\nALL POST-CLEANUP CHECKS PASSED.")
