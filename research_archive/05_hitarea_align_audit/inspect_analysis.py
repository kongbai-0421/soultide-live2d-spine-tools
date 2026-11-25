import pathlib

root = pathlib.Path(r"D:\A灵魂潮汐-本地化\服务器")

print("=== analysis/ top-level breakdown ===")
an = root / "analysis"
if an.exists():
    for item in sorted(an.iterdir()):
        if item.is_dir():
            files = [x for x in item.rglob("*") if x.is_file()]
            sz = sum(x.stat().st_size for x in files)
            print(f"  [DIR]  {sz/1048576:8.2f} MB  {len(files):6d} files  analysis/{item.name}/")
        else:
            print(f"  [FILE] {item.stat().st_size/1048576:8.2f} MB  analysis/{item.name}")

print("\n=== Refs to tools/ non-py items in *.py / *.ps1 / *.md ===")
tools_nonpy = [f.name for f in (root / "tools").iterdir() if f.is_file() and f.suffix not in (".py", ".ps1", ".sh")]
check_files = list(root.glob("*.py")) + list((root / "tools").glob("*.py")) + list(root.glob("*.ps1"))
for name in ["11_tables_base.ab", "apk_CfgDressTable", "apk_DressModule", "apk_SplitConfigInfo", "Dress.bin", "Dress.lua", "battle_official.pcap"]:
    hits = [str(p.relative_to(root)) for p in check_files if name in p.read_text(encoding="utf-8", errors="ignore")]
    print(f"  {name:25s}: {hits}")
