#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
全量 55 角色创意工坊 STD2_0 `.lpk` + 暂存目录完整性校验脚本
============================================================
逐包校验：
  1. ZIP 结构与条目可读性、必选清单 `1d862f7d02e6008f4550188a31ca654f` 与头像 `4a301072dec6b6a49050e5b294cd7983`
  2. 递归遍历每套 Live2D (.bin3) 与 Spine (.bin) 服装及全部子模型 / 变身形态 / 隐藏背景 touch_only：
     - 断言全部纹理 / 骨架 / 动作 / 物理 / 表情 / 音频 / 指令目标 100% 存在于包内
     - 断言 Spine `atlases[].tex_names` 完整且长度与 `textures` 一致，并与 `.atlas.txt` 页名匹配
     - 断言包内所有 `.ogg` 均以 `OggS` 魔数开头且零内容重复
  3. 断言所有 `preview.jpg` 严格 < 1 MB
  4. 断言保护数据库 `soultide.db` 字节数严格等于 83,886,080
"""

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import List, Set

BASE_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型")
LPK_OUT_ROOT = BASE_DIR / "_workshop_lpks"
STAGING_ROOT = BASE_DIR / "_workshop_lpk_staging"
SOULTIDE_DB = Path(r"D:\A灵魂潮汐-本地化\服务器\soultide.db")

CONFIG_MLVE_ZIP_NAME = "1d862f7d02e6008f4550188a31ca654f"
AVATAR_ZIP_NAME = "4a301072dec6b6a49050e5b294cd7983"


def extract_atlas_page_stems(atlas_text: str) -> List[str]:
    stems = []
    lines = atlas_text.replace("\r\n", "\n").split("\n")
    for idx, line in enumerate(lines):
        if not line or line[0].isspace():
            continue
        if (
            idx + 2 < len(lines)
            and lines[idx + 1].startswith("size:")
            and lines[idx + 2].startswith("format:")
        ):
            stems.append(Path(line.strip()).stem)
    return stems


def verify_one_lpk(lpk_path: Path) -> List[str]:
    errs: List[str] = []
    doll = lpk_path.stem

    prev_path = LPK_OUT_ROOT / f"{doll}.preview.jpg"
    if not prev_path.is_file():
        errs.append(f"Missing preview: {prev_path.name}")
    elif prev_path.stat().st_size >= 1024 * 1024:
        errs.append(f"Preview >= 1MB: {prev_path.stat().st_size}")

    stage_mlve = STAGING_ROOT / doll / "config.mlve"
    is_mega = (doll == "灵魂潮汐_全55人偶合集")
    if (not is_mega) and (not stage_mlve.is_file()):
        errs.append(f"Missing staging config.mlve for {doll}")

    try:
        zf = zipfile.ZipFile(lpk_path, "r")
    except Exception as e:
        return [f"Cannot open ZIP: {e}"]

    with zf:
        names = set(zf.namelist())
        if CONFIG_MLVE_ZIP_NAME not in names:
            errs.append("Missing config.mlve hash entry")
            return errs

        mlve = json.loads(zf.read(CONFIG_MLVE_ZIP_NAME).decode("utf-8"))
        if mlve.get("type") != "STD2_0":
            errs.append(f"Unexpected type: {mlve.get('type')}")
        if mlve.get("encrypt") != "false":
            errs.append(f"Unexpected encrypt: {mlve.get('encrypt')}")

        # 检查每位角色的 avatar 条目存在且为有效 PNG
        seen_avatars: Set[str] = set()
        for ch in mlve.get("list") or []:
            av_name = ch.get("avatar", "")
            if av_name not in names:
                errs.append(f"Missing avatar entry for {ch.get('character')}: {av_name}")
            else:
                if av_name in seen_avatars:
                    errs.append(f"Duplicate avatar entry across characters: {av_name}")
                seen_avatars.add(av_name)
                av = zf.read(av_name)
                if not av.startswith(b"\x89PNG\r\n\x1a\n"):
                    errs.append(f"Avatar for {ch.get('character')} is not valid PNG")

        # 检查所有 .ogg：OggS 魔数 + 零重复内容
        ogg_hashes: Set[str] = set()
        for n in names:
            if n.endswith(".ogg"):
                b = zf.read(n)
                if not b.startswith(b"OggS"):
                    errs.append(f"Audio {n} missing OggS magic")
                h = hashlib.sha256(b).hexdigest()
                if h in ogg_hashes:
                    errs.append(f"Duplicate audio content in LPK: {n}")
                ogg_hashes.add(h)

        # 递归检查所有配置
        queue: List[str] = []
        visited: Set[str] = set()
        for ch in mlve.get("list") or []:
            for cos in ch.get("costume") or []:
                p = cos.get("path", "")
                if p not in names:
                    errs.append(f"Missing costume config: {cos.get('name')} -> {p}")
                else:
                    queue.append(p)

        def check_cmd(cmd: str, owner: str):
            if not cmd:
                return
            for raw in cmd.split(";"):
                seg = raw.strip()
                if not seg:
                    continue
                parts = seg.split()
                v = parts[0]
                if v in ("add_submodel", "remove_submodel", "change_model", "change_cos") and len(parts) >= 2:
                    tgt = parts[1]
                    if tgt not in names:
                        errs.append(f"[{owner}] Command '{seg}' missing target {tgt}")
                    elif tgt not in visited:
                        queue.append(tgt)
                elif v == "replace_tex" and len(parts) >= 3:
                    tgt = parts[2]
                    if tgt not in names:
                        errs.append(f"[{owner}] replace_tex missing {tgt}")

        def check_multilang_group(grp: str, items: list, lang_key: str, owner: str):
            """校验 EX 原生 Motion.Language 规则：若组内存在任意带语言标签条目，
            必须具备完整回退池('')与 zhs/zht/ja 变体且数量一致，绝不允许同组混排导致掩盖。"""
            by_lang = {}
            for it in items or []:
                if isinstance(it, dict):
                    lv = it.get(lang_key) or ""
                    by_lang.setdefault(lv, []).append(it)
            if set(by_lang.keys()) == {""}:
                return
            expected_langs = {"", "zhs", "zht", "ja"}
            if set(by_lang.keys()) != expected_langs:
                errs.append(f"[{owner}] Group '{grp}' incomplete langs: {sorted(by_lang.keys())}")
                return
            counts = {k: len(v) for k, v in by_lang.items()}
            if len(set(counts.values())) != 1:
                errs.append(f"[{owner}] Group '{grp}' uneven lang counts: {counts}")

        while queue:
            cfg_name = queue.pop(0)
            if cfg_name in visited:
                continue
            visited.add(cfg_name)
            try:
                cfg = json.loads(zf.read(cfg_name).decode("utf-8"))
            except Exception as e:
                errs.append(f"Invalid JSON in {cfg_name}: {e}")
                continue

            if "FileReferences" in cfg:
                fr = cfg["FileReferences"]
                for k in ("Moc", "Physics", "Pose"):
                    if fr.get(k) and fr[k] not in names:
                        errs.append(f"[{cfg_name}] Missing {k}: {fr[k]}")
                if isinstance(fr.get("PhysicsV2"), dict) and fr["PhysicsV2"].get("File"):
                    if fr["PhysicsV2"]["File"] not in names:
                        errs.append(f"[{cfg_name}] Missing PhysicsV2: {fr['PhysicsV2']['File']}")
                for t in fr.get("Textures") or []:
                    if t not in names:
                        errs.append(f"[{cfg_name}] Missing Texture: {t}")
                for exp in fr.get("Expressions") or []:
                    if isinstance(exp, dict) and exp.get("File") and exp["File"] not in names:
                        errs.append(f"[{cfg_name}] Missing Expression: {exp['File']}")
                mots = fr.get("Motions") or {}
                for grp, items in mots.items():
                    check_multilang_group(grp, items, "Language", cfg_name)
                    for it in items or []:
                        if not isinstance(it, dict):
                            continue
                        if it.get("File") and it["File"] not in names:
                            errs.append(f"[{cfg_name}] Missing Motion {grp}: {it['File']}")
                        if it.get("Sound") and it["Sound"] not in names:
                            errs.append(f"[{cfg_name}] Missing Sound {grp}: {it['Sound']}")
                        check_cmd(it.get("Command", ""), cfg_name)
                        check_cmd(it.get("PostCommand", ""), cfg_name)
                # 若存在多待机切换，检查 Idle 均带有合法 idle_mode VarFloats 且含 equal 0 默认项
                idle_items = mots.get("Idle") or []
                if len(idle_items) > 1:
                    if not any(
                        any(vf.get("Name") == "idle_mode" and vf.get("Code") == "equal 0" for vf in (it.get("VarFloats") or []))
                        for it in idle_items if isinstance(it, dict)
                    ):
                        errs.append(f"[{cfg_name}] Multi-Idle missing default idle_mode equal 0")
            elif "skeleton" in cfg:
                if cfg["skeleton"] not in names:
                    errs.append(f"[{cfg_name}] Missing skeleton: {cfg['skeleton']}")
                for atl in cfg.get("atlases") or []:
                    an = atl.get("atlas", "")
                    texs = atl.get("textures") or []
                    tnames = atl.get("tex_names") or []
                    if an not in names:
                        errs.append(f"[{cfg_name}] Missing atlas: {an}")
                    else:
                        stems = extract_atlas_page_stems(zf.read(an).decode("utf-8", errors="replace"))
                        if stems and len(tnames) != len(stems):
                            errs.append(f"[{cfg_name}] tex_names count {len(tnames)} != atlas pages {len(stems)}")
                        elif stems and tnames != stems:
                            errs.append(f"[{cfg_name}] tex_names {tnames} != atlas pages {stems}")
                    if len(tnames) != len(texs):
                        errs.append(f"[{cfg_name}] tex_names len {len(tnames)} != textures len {len(texs)}")
                    for t in texs:
                        if t not in names:
                            errs.append(f"[{cfg_name}] Missing spine texture: {t}")
                for grp, items in (cfg.get("motions") or {}).items():
                    check_multilang_group(grp, items, "language", cfg_name)
                    for it in items or []:
                        if not isinstance(it, dict):
                            continue
                        if it.get("sound") and it["sound"] not in names:
                            errs.append(f"[{cfg_name}] Missing spine sound {grp}: {it['sound']}")
                        check_cmd(it.get("command", ""), cfg_name)
                        check_cmd(it.get("post_command", ""), cfg_name)
            else:
                errs.append(f"[{cfg_name}] Unrecognized config schema (neither FileReferences nor skeleton)")

    return errs


def main():
    lpks = sorted(LPK_OUT_ROOT.glob("*.lpk"))
    print(f"Verifying {len(lpks)} LPK archive(s)...")
    failed = {}
    for p in lpks:
        errs = verify_one_lpk(p)
        if errs:
            failed[p.name] = errs
            print(f"  [FAIL] {p.name}: {len(errs)} error(s) -> {errs[:3]}")

    db_size = SOULTIDE_DB.stat().st_size if SOULTIDE_DB.is_file() else -1
    db_ok = (db_size == 83886080)
    print(f"Passed: {len(lpks) - len(failed)} / {len(lpks)} | Failed: {len(failed)} | soultide.db={db_size} (ok={db_ok})")
    if failed or not db_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
