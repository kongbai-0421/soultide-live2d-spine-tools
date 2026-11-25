import pathlib

root = pathlib.Path(r"D:\A灵魂潮汐-本地化\服务器")
an = root / "analysis"

print("=== analysis/ items > 20 MB ===")
for item in sorted(an.iterdir()):
    sz = item.stat().st_size if item.is_file() else sum(x.stat().st_size for x in item.rglob("*") if x.is_file())
    if sz > 20 * 1048576:
        print(f"  {sz/1048576:8.2f} MB  {'DIR ' if item.is_dir() else 'FILE'}  analysis/{item.name}")

check_files = list(root.glob("*.py")) + list((root / "tools").glob("*.py"))
for tok in [".tmp-", ".tmp_", "temp_test"]:
    hits = [str(p.relative_to(root)) for p in check_files if tok in p.read_text(encoding="utf-8", errors="ignore")]
    print(f"Refs to {tok}: {hits}")

tmp_pngs = [f for f in an.iterdir() if f.is_file() and (f.name.startswith(".tmp-") or f.name.startswith(".tmp_") or f.name in ("temp_test.db", "temp_test2.db", "temp_test_suite.db", "temp_test_use_item.db"))]
print(f"analysis/.tmp* + temp_test*.db: {len(tmp_pngs)} files, {sum(f.stat().st_size for f in tmp_pngs)/1048576:.2f} MB")
