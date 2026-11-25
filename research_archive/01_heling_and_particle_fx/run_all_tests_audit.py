import concurrent.futures
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(r"D:\A灵魂潮汐-本地化\服务器")

test_files = sorted(
    [p.relative_to(ROOT).as_posix() for p in ROOT.glob("test_*.py")]
    + [p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_*.py")]
    + [p.relative_to(ROOT).as_posix() for p in (ROOT / "tools").glob("test_*.py")]
)

print(f"Discovered {len(test_files)} test_*.py files total.")

def run_one(rel: str):
    t0 = time.perf_counter()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(ROOT)
    # Force non-existent private temp db path for each test process
    with tempfile.TemporaryDirectory(prefix="audit-db-") as td:
        env["SOULTIDE_DB_PATH"] = str(pathlib.Path(td) / "soultide.db")
        cmd = [sys.executable, "-B", "-m", "unittest", rel[:-3].replace("/", ".")]
        try:
            res = subprocess.run(
                cmd,
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            out = (res.stdout or "") + "\n" + (res.stderr or "")
            rc = res.returncode
        except subprocess.TimeoutExpired:
            out = "TIMEOUT 120s"
            rc = 124
    # Summarize output
    m_ran = re.findall(r"Ran (\d+) tests? in ([0-9.]+)s", out)
    tail = [l.strip() for l in out.strip().splitlines() if l.strip()][-4:]
    return rel, rc, time.perf_counter() - t0, m_ran, tail, out

db_before = (ROOT / "soultide.db").stat().st_mtime, (ROOT / "soultide.db").stat().st_size

results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    for r in ex.map(run_one, test_files):
        results.append(r)

db_after = (ROOT / "soultide.db").stat().st_mtime, (ROOT / "soultide.db").stat().st_size

passed = [r for r in results if r[1] == 0]
failed = [r for r in results if r[1] != 0]

print(f"\nPassed: {len(passed)}/{len(results)}, Failed/Errored: {len(failed)}")
print(f"Live soultide.db changed during isolated run? {db_before != db_after} (before={db_before}, after={db_after})")

print("\n=== FAILED / ERRORED TESTS ===")
for rel, rc, sec, m_ran, tail, out in failed:
    print(f"\n[FAIL rc={rc} {sec:.1f}s] {rel}")
    for line in out.strip().splitlines()[-15:]:
        print("  ", line)

print("\n=== PASSED WITH 0 TESTS OR SKIPPED ===")
for rel, rc, sec, m_ran, tail, out in passed:
    if not m_ran or "skipped=" in "\n".join(tail) or m_ran[-1][0] == "0":
        print(f"  {rel} ({sec:.1f}s): {' | '.join(tail[-2:])}")
