import os, re, glob, sys
sys.path.insert(0, r'E:\A灵魂潮汐\tools')
import soultide_common as sc

# 1. Search Lua decompiled scripts for SpineAction / EffectId / BgPrefabs / Point_Root / PlaySpineAction
lua_root = sc.DECOMPILED_DIR.parent
hits = []
for p in sorted(sc.DECOMPILED_DIR.rglob('*.lua')):
    if p.name.startswith('Cfg'):
        continue
    try:
        txt = p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue
    if any(k in txt for k in ('EffectId', 'BgPrefabs', 'Point_Root', 'MarryEffectId', 'SpineActionControl')):
        lines = txt.splitlines()
        rel = p.relative_to(sc.DECOMPILED_DIR)
        for i, ln in enumerate(lines, 1):
            if any(k in ln for k in ('EffectId', 'BgPrefabs', 'Point_Root', 'MarryEffectId', 'PlayEffect', 'ShowEffect')):
                hits.append(f"{rel}:{i}: {ln.strip()[:140]}")
print(f"Lua hits: {len(hits)}")
for h in hits[:60]:
    print(" ", h)

# 2. Check CfgSoulSpineActionTable schema and sample FX entries
sa = sc.parse_lua_flat_table(sc.DECOMPILED_DIR / 'CfgSoulSpineActionTable.lua')
print(f"\nCfgSoulSpineActionTable rows: {len(sa)}")
eff_rows = [ (k, v) for k, v in sa.items() if 'EffectId' in v ]
print(f"Rows with EffectId: {len(eff_rows)}")
for k, v in eff_rows[:8]:
    print(" ", k, v.replace('\n', ' '))
