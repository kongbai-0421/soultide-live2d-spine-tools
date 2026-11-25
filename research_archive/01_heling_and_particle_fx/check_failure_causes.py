import json, pathlib

ROOT = pathlib.Path(r"D:\A灵魂潮汐-本地化\服务器")

# 1. Check item 31401 config
for p in [ROOT / "analysis" / "full_clean_items.json", ROOT / "tools" / "full_clean_items.json", ROOT / "analysis" / "module_config.json"]:
    if p.exists():
        print("Exists:", p.relative_to(ROOT))

# Check what storage._ITEM_CFG_BY_CID loads
import os, tempfile, sys
with tempfile.TemporaryDirectory() as td:
    os.environ["SOULTIDE_DB_PATH"] = str(pathlib.Path(td) / "diag.db")
    sys.path.insert(0, str(ROOT))
    import storage
    print("31401 cfg:", storage._ITEM_CFG_BY_CID.get(31401))

    # 2. Check why test_dialog_archive_and_skip failed (line 100)
    lib = storage.get_complete_library_state("nonexistent-test") if hasattr(storage, "get_complete_library_state") else None
    print("has complete_library_state?", hasattr(storage, "complete_library_state"), hasattr(storage, "get_complete_library_state"))

    # 3. Check test_audit_fixes L26 (_guild_player None level)
    import module_handlers
    print("_guild_player check:", [fn for fn in dir(module_handlers) if "guild_player" in fn])
