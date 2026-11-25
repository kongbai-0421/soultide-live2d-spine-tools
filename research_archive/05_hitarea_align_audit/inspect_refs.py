import pathlib

root = pathlib.Path(r"D:\A灵魂潮汐-本地化\服务器")

print("=== Refs to -release in root/*.py & tools/*.py ===")
for p in sorted(list(root.glob("*.py")) + list((root / "tools").glob("*.py"))):
    txt = p.read_text(encoding="utf-8", errors="ignore")
    for i, line in enumerate(txt.splitlines(), 1):
        if "-release" in line:
            print(f"  {p.relative_to(root)}:{i}: {line.strip()[:120]}")

print("\n=== Test references to analysis/ ===")
for p in sorted(list(root.glob("*.py")) + list((root / "tools").glob("*.py"))):
    txt = p.read_text(encoding="utf-8", errors="ignore")
    if "analysis" in txt:
        for i, line in enumerate(txt.splitlines(), 1):
            if "analysis" in line and ("Path" in line or "/" in line or "\\" in line):
                print(f"  {p.relative_to(root)}:{i}: {line.strip()[:120]}")
                break

print("\n=== Check scratch/ files NOT matching .py ===")
sc = root / "scratch"
for sub in sorted(sc.iterdir()):
    if sub.is_dir():
        print(f"  [SUBDIR] {sub.name}")
print("  Top non-.py files in scratch (>1MB):")
for f in sorted(sc.iterdir()):
    if f.is_file() and f.suffix != ".py" and f.stat().st_size > 1048576:
        print(f"    {f.stat().st_size/1048576:8.2f} MB  {f.name}")

print("\n=== Check root *.bak* or *.tmp* or unused files ===")
for f in sorted(root.iterdir()):
    if f.is_file() and (".bak" in f.name or ".tmp" in f.name or f.stat().st_size == 0):
        print(f"  {f.stat().st_size:10d}  {f.name}")

print("\n=== Check tools/ non-py or bak files ===")
for f in sorted((root / "tools").iterdir()):
    if f.is_dir() or f.suffix != ".py":
        sz = f.stat().st_size if f.is_file() else sum(x.stat().st_size for x in f.rglob("*") if x.is_file())
        print(f"  {sz/1048576:8.2f} MB  {f.name}")
