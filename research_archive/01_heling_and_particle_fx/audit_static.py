import ast
import os
import pathlib
import py_compile
import re
import sys

ROOT = pathlib.Path(r"D:\A灵魂潮汐-本地化\服务器")

SKIP_DIRS = {
    "dependencies",
    "analysis",
    "translation-workspace",
    "android-13",
    "offline_cdn",
    "assets",
    "story_voice_tasks",
    "temp",
    "mobile-runtime",
    "build",
    "apk_output",
}

def iter_code_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = pathlib.Path(dirpath).relative_to(ROOT)
        parts = rel.parts
        if parts and parts[0] in SKIP_DIRS:
            dirnames[:] = []
            continue
        if parts and parts[0] == "__pycache__":
            dirnames[:] = []
            continue
        for fn in sorted(filenames):
            if fn.endswith((".py", ".ps1", ".sh", ".java", ".bat", ".cmd")):
                yield pathlib.Path(dirpath) / fn

files = list(iter_code_files())
print(f"Found {len(files)} active code/script files (excluding vendor/assets/analysis):")
by_top = {}
for f in files:
    rel = f.relative_to(ROOT)
    top = rel.parts[0] if len(rel.parts) > 1 else "(root)"
    by_top[top] = by_top.get(top, 0) + 1
for k, v in sorted(by_top.items()):
    print(f"  {k:20s}: {v}")

print("\n=== 1. Python syntax & AST static checks ===")
syntax_errors = []
dup_defs = []
bare_excepts = []
missing_test_paths = []
db_hardcode_tests = []
root_py_imports = {}

py_files = [f for f in files if f.suffix == ".py"]
for p in py_files:
    rel = p.relative_to(ROOT).as_posix()
    try:
        src = p.read_text(encoding="utf-8-sig")
    except Exception as e:
        syntax_errors.append((rel, f"read error: {e}"))
        continue
    try:
        tree = ast.parse(src, filename=str(p))
    except SyntaxError as e:
        syntax_errors.append((rel, f"SyntaxError line {e.lineno}: {e.msg}"))
        continue

    # Top-level duplicate function/class names
    seen_top = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in seen_top:
                dup_defs.append((rel, node.name, seen_top[node.name], node.lineno))
            else:
                seen_top[node.name] = node.lineno

    # Bare except: / except Exception: pass (only check core runtime files, not 700 tools)
    if not rel.startswith("tools/"):
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                bare_excepts.append((rel, node.lineno))

    # Track imports in non-tools files to detect local broken imports
    if not rel.startswith(("tools/", "scratch/")):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_py_imports.setdefault(rel, []).append((alias.name.split(".")[0], node.lineno))
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                root_py_imports.setdefault(rel, []).append((node.module.split(".")[0], node.lineno))

    # Check if any test_* reads soultide.db directly without tempfile/SOULTIDE_DB_PATH
    if rel.startswith(("test_", "tests/")) and "soultide.db" in src:
        uses_env = "SOULTIDE_DB_PATH" in src or "tempfile" in src or "shutil.copy" in src or "tmp_path" in src
        # Find exact lines with soultide.db
        lines = [(i + 1, l.strip()) for i, l in enumerate(src.splitlines()) if "soultide.db" in l]
        db_hardcode_tests.append((rel, uses_env, lines[:6]))

print("Syntax errors:", len(syntax_errors))
for x in syntax_errors:
    print(" ", x)

print("\nDuplicate top-level defs (excluding tools/ or including all):", len(dup_defs))
for x in dup_defs:
    print(" ", x)

print("\nBare except: in runtime/root/tests:", len(bare_excepts))
for x in bare_excepts[:30]:
    print(" ", x)
if len(bare_excepts) > 30:
    print(f"  ... ({len(bare_excepts) - 30} more)")

print("\nTests mentioning soultide.db:")
for rel, safe_hint, lines in db_hardcode_tests:
    flag = "HAS_ISOLATION_HINT" if safe_hint else "NO_ISOLATION_HINT!!"
    print(f"  [{flag}] {rel}")
    if not safe_hint:
        for ln, txt in lines:
            print(f"    L{ln}: {txt[:120]}")

print("\n=== 2. Check local module imports in root & tests/*.py ===")
import importlib.util
sys.path.insert(0, str(ROOT))
broken_imports = []
for rel, imps in sorted(root_py_imports.items()):
    for mod, ln in imps:
        if mod in sys.stdlib_module_names:
            continue
        if (ROOT / f"{mod}.py").exists() or (ROOT / mod / "__init__.py").exists():
            continue
        if (ROOT / "tests" / f"{mod}.py").exists():
            continue
        spec = importlib.util.find_spec(mod)
        if spec is None:
            broken_imports.append((rel, ln, mod))
print("Broken imports in root & tests/*.py:", len(broken_imports))
for x in broken_imports:
    print(" ", x)
