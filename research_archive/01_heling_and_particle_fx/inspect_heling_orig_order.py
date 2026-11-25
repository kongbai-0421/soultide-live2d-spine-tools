import sys, re, json
from pathlib import Path

sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, DECOMPILED_DIR, load_ab, parse_lua_flat_table
from batch_fx_exporter import FullI18nRepo, build_skin_catalog

repo = FullI18nRepo()
cat = build_skin_catalog(repo)
heling = [s for s in cat if "4301" in str(s) or "和铃" in str(s) or "heling" in str(s).lower()]
for s in heling:
    if "古锦新韵" in str(s) or "HeLing_02" in str(s) or "4301" in str(s):
        print("=== CATALOG ENTRY ===")
        print(json.dumps(s, ensure_ascii=False, indent=2))
