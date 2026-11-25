"""Scheme A Multi-Language Config Generator (ZH / EN / JA) & Deduplicated WAV -> OGG Converter.

1. Streams only the required ~10,500 I18N IDs from baseline (zh-cn), i18n-en, and i18n-ja
   one shard at a time (bounded memory < 150 MB).
2. Deduplicates all ~29,275 .wav files across 182 Live2D and 170 Spine packages into ~8,172
   unique AudioClips, encodes each unique clip once to Ogg Vorbis (.ogg, -c:a libvorbis -q:a 5)
   via batched multi-threaded FFmpeg, propagates to duplicate locations, verifies OggS headers,
   and deletes original .wav files.
3. Updates .model3.json and .config.json sound references (.wav -> .ogg) and generates
   Scheme A sibling configs in every package directory:
   - Live2D (182 packages): .model3.json (zh-cn), model_en.model3.json (en), model_ja.model3.json (ja)
   - Spine  (170 packages): .config.json (zh-cn), config_en.config.json (en), config_ja.config.json (ja)
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import gc
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from soultide_common import write_json

BASE_DIR = Path(r"D:\A灵魂潮汐-本地化\服务器\analysis\luajit-pipeline\baseline-20260813\decompiled-x64")
EN_DIR = Path(r"D:\A灵魂潮汐-本地化\服务器\translation-workspace\build\i18n-en\source-lua")
JA_DIR = Path(r"D:\A灵魂潮汐-本地化\服务器\translation-workspace\build\i18n-ja\source-lua")
MODEL_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型")
LIVE2D_ROOT = MODEL_ROOT / "live2d"
SPINE_ROOT = MODEL_ROOT / "spine"
REPORT_PATH = Path(__file__).resolve().parent / "i18n_ogg_fleet_report.json"

FFMPEG_DEFAULT = Path(r"E:\软件\ffmpeg-N-120957-g66e40840d1-win64-gpl\bin\ffmpeg.EXE")

SYNTHETIC_LABELS: dict[str, tuple[str, str]] = {
    "黛安娜": ("Diana", "ダイアナ"),
    "原皮": ("Default Outfit", "初期衣装"),
    "原皮(立绘)": ("Default Outfit (Portrait)", "初期衣装（立ち絵）"),
    "原皮_变身": ("Default Outfit (Transform)", "初期衣装（変身）"),
    "原皮_柯露雪儿剧情": ("Default Outfit (Colcher Story)", "初期衣装（コルシェルストーリー）"),
    "原皮_活动": ("Default Outfit (Event)", "初期衣装（イベント）"),
    "原皮_艾妮斯剧情": ("Default Outfit (Ennis Story)", "初期衣装（エニスストーリー）"),
    "夏樱_S2": ("Natsuzakura S2", "夏桜 S2"),
    "夏樱_S3": ("Natsuzakura S3", "夏桜 S3"),
    "夏樱_S4": ("Natsuzakura S4", "夏桜 S4"),
    "夏樱_S5": ("Natsuzakura S5", "夏桜 S5"),
    "此情无垢": ("Pure Devotion", "無垢なる想い"),
    "经典_活动": ("Classic (Event)", "クラシック（イベント）"),
}

EXP_NAME_TRANSLATIONS: dict[str, dict[str, str]] = {
    "佩戴誓约戒指": {"en": "Put On Oath Ring", "ja": "誓約の指輪を着ける"},
    "取下誓约戒指": {"en": "Take Off Oath Ring", "ja": "誓約の指輪を外す"},
}

MENU_CAT_TITLES: dict[str, dict[str, str]] = {
    "Menu_Cat_Time": {
        "en": "Time Greetings (Morning / Noon / Evening / Night)",
        "ja": "時間帯挨拶（朝・昼・夜・深夜）",
    },
    "Menu_Cat_Social": {
        "en": "Daily / Festival / Return / System",
        "ja": "日常挨拶・祝日・復帰・システム",
    },
    "Menu_Cat_Gift": {
        "en": "Gifts & Feeding Interactions",
        "ja": "プレゼント＆料理リアクション",
    },
    "Menu_Cat_Archive": {
        "en": "Oath & Profile Archive Voices",
        "ja": "誓約＆プロフィール図鑑ボイス",
    },
    "Menu_Cat_Battle": {
        "en": "Battle Voices & Skill Motions",
        "ja": "戦闘ボイス＆スキルモーション",
    },
    "Menu_Cat_Motion": {
        "en": "Motion Preview (Extra Live2D Motions)",
        "ja": "モーションプレビュー（その他Live2D動作）",
    },
}


def clean_i18n_str(raw: str) -> str:
    return (
        raw.replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\'", "'")
        .replace("\\\\", "\\")
        .replace("{$br}", "\n")
        .strip()
    )


def build_low_memory_i18n_tables(
    l2d_cfgs: list[Path],
    spine_cfgs: list[Path],
) -> dict[str, Any]:
    """Build exact zh->en and zh->ja lookup tables with < 150 MB peak RAM."""
    t0 = time.perf_counter()
    used_stems: set[str] = set()
    used_texts: set[str] = set()

    for p in l2d_cfgs:
        used_texts.add(p.parent.parent.name)
        used_texts.add(p.parent.name)
        d = json.loads(p.read_text(encoding="utf-8"))
        for grp, items in (d.get("FileReferences", {}).get("Motions") or {}).items():
            if grp in ("Tap", "语音菜单") or grp.startswith("Menu_Cat_"):
                continue
            for it in items:
                if it.get("Sound"):
                    used_stems.add(Path(it["Sound"]).stem.lower())
                if it.get("Text"):
                    used_texts.add(it["Text"].strip())

    for p in spine_cfgs:
        used_texts.add(p.parent.parent.name)
        used_texts.add(p.parent.name)
        d = json.loads(p.read_text(encoding="utf-8"))
        for grp, items in (d.get("motions") or {}).items():
            for it in items:
                if it.get("sound"):
                    used_stems.add(Path(it["sound"]).stem.lower())
                if it.get("text"):
                    used_texts.add(it["text"].strip())

    sound_id_to_stem: dict[int, str] = {}
    for p in sorted(BASE_DIR.glob("CfgSoundTable_*.lua")):
        if p.name.endswith("_Route.lua"):
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"\[(\d+)\]\s*=\s*\{([^}]+)\}", txt):
            sid = int(m.group(1))
            fn = re.search(r'FileName\s*=\s*"([^"]+)"', m.group(2))
            if fn:
                st = Path(fn.group(1)).stem.lower()
                if st in used_stems:
                    sound_id_to_stem[sid] = st
        del txt

    stem_to_i18ns: dict[str, list[int]] = {}
    needed_ids: set[int] = set()
    for p in sorted(BASE_DIR.glob("CfgCVTable_*.lua")):
        if p.name.endswith("_Route.lua"):
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"\[(\d+)\]\s*=\s*\{([^}]+)\}", txt):
            body = m.group(2)
            sid_m = re.search(r"SoundID\s*=\s*(\d+)", body)
            tx_m = re.search(r"Text\s*=\s*getI18NValue\((\d+)\)", body)
            if sid_m and tx_m:
                st = sound_id_to_stem.get(int(sid_m.group(1)))
                if st:
                    tid = int(tx_m.group(1))
                    stem_to_i18ns.setdefault(st, []).append(tid)
                    needed_ids.add(tid)
        del txt

    for fname in ("CfgSoulTable.lua", "CfgDressTable.lua"):
        txt = (BASE_DIR / fname).read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"Name\s*=\s*getI18NValue\((\d+)\)", txt):
            needed_ids.add(int(m.group(1)))
        del txt

    pat_str = re.compile(r'\[(\d+)\]\s*=\s*\{\s*Id\s*=\s*\d+,\s*Str\s*=\s*"((?:[^"\\]|\\.)*)"', re.S)
    pat_ref = re.compile(r'\[(\d+)\]\s*=\s*\{\s*Id\s*=\s*\d+,\s*RefId\s*=\s*(\d+)', re.S)

    zh_by_id: dict[int, str] = {}
    ref_map: dict[int, int] = {}
    zh_text_to_id: dict[str, int] = {}

    for p in sorted(BASE_DIR.glob("CfgI18NTable_*.lua")):
        if p.name.endswith("_Route.lua"):
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in pat_ref.finditer(txt):
            ref_map[int(m.group(1))] = int(m.group(2))
        for m in pat_str.finditer(txt):
            k = int(m.group(1))
            s = clean_i18n_str(m.group(2))
            if k in needed_ids or s in used_texts:
                zh_by_id[k] = s
                if s in used_texts:
                    zh_text_to_id.setdefault(s, k)
                    needed_ids.add(k)
        del txt

    extra_refs: set[int] = set()
    for k in list(needed_ids):
        cur = k
        for _ in range(8):
            if cur in ref_map:
                cur = ref_map[cur]
                extra_refs.add(cur)
            else:
                break
    needed_ids |= extra_refs
    missing_zh = extra_refs - set(zh_by_id.keys())
    if missing_zh:
        for p in sorted(BASE_DIR.glob("CfgI18NTable_*.lua")):
            if p.name.endswith("_Route.lua"):
                continue
            txt = p.read_text(encoding="utf-8", errors="ignore")
            for m in pat_str.finditer(txt):
                k = int(m.group(1))
                if k in missing_zh:
                    zh_by_id[k] = clean_i18n_str(m.group(2))
            del txt
    for k in list(needed_ids):
        if k not in zh_by_id:
            cur = k
            for _ in range(8):
                if cur in ref_map:
                    cur = ref_map[cur]
                    if cur in zh_by_id:
                        zh_by_id[k] = zh_by_id[cur]
                        zh_text_to_id.setdefault(zh_by_id[k], k)
                        break
                else:
                    break

    def _stream_lang(lang_dir: Path, tids: set[int]) -> dict[int, str]:
        out: dict[int, str] = {}
        l_ref: dict[int, int] = {}
        for p in sorted(lang_dir.glob("CfgI18NTable_*.lua")):
            if p.name.endswith("_Route.lua"):
                continue
            txt = p.read_text(encoding="utf-8", errors="ignore")
            for m in pat_ref.finditer(txt):
                k, r = int(m.group(1)), int(m.group(2))
                if k in tids:
                    l_ref[k] = r
                    tids.add(r)
            for m in pat_str.finditer(txt):
                k = int(m.group(1))
                if k in tids:
                    out[k] = clean_i18n_str(m.group(2))
            del txt
        for k in list(tids):
            if k not in out:
                cur = k
                for _ in range(8):
                    nxt = l_ref.get(cur) or ref_map.get(cur)
                    if nxt:
                        cur = nxt
                        if cur in out:
                            out[k] = out[cur]
                            break
                    else:
                        break
        return out

    en_by_id = _stream_lang(EN_DIR, set(needed_ids))
    ja_by_id = _stream_lang(JA_DIR, set(needed_ids))
    del ref_map
    gc.collect()

    dt = time.perf_counter() - t0
    print(
        f"[I18N] Loaded {len(needed_ids)} targeted IDs in {dt:.1f}s "
        f"(zh={len(zh_by_id)}, en={len(en_by_id)}, ja={len(ja_by_id)})",
        flush=True,
    )
    return {
        "stem_to_i18ns": stem_to_i18ns,
        "zh_by_id": zh_by_id,
        "en_by_id": en_by_id,
        "ja_by_id": ja_by_id,
        "zh_text_to_id": zh_text_to_id,
    }


def translate_voice_text(
    zh_text: str,
    sound_rel: str,
    lang: str,
    i18n_ctx: dict[str, Any],
) -> str:
    """Resolve English ('en') or Japanese ('ja') subtitle for a voice entry."""
    zh_clean = zh_text.strip()
    if not zh_clean:
        return zh_text
    lang_map = i18n_ctx["en_by_id"] if lang == "en" else i18n_ctx["ja_by_id"]
    zh_by_id = i18n_ctx["zh_by_id"]
    stem_to_i18ns = i18n_ctx["stem_to_i18ns"]
    zh_text_to_id = i18n_ctx["zh_text_to_id"]

    chosen_tid: int | None = None
    if sound_rel:
        stem = Path(sound_rel).stem.lower()
        cands = stem_to_i18ns.get(stem) or []
        if len(cands) == 1:
            chosen_tid = cands[0]
        elif len(cands) > 1:
            for cid in cands:
                if zh_by_id.get(cid, "").strip() == zh_clean:
                    chosen_tid = cid
                    break
            if chosen_tid is None:
                chosen_tid = cands[0]

    if chosen_tid is None or chosen_tid not in lang_map:
        chosen_tid = zh_text_to_id.get(zh_clean)

    if chosen_tid is not None and chosen_tid in lang_map and lang_map[chosen_tid]:
        return lang_map[chosen_tid]
    return zh_clean


def translate_label(name_zh: str, lang: str, i18n_ctx: dict[str, Any]) -> str:
    """Resolve character or skin folder name into English ('en') or Japanese ('ja')."""
    if name_zh in SYNTHETIC_LABELS:
        return SYNTHETIC_LABELS[name_zh][0 if lang == "en" else 1]
    tid = i18n_ctx["zh_text_to_id"].get(name_zh)
    if tid is not None:
        lang_map = i18n_ctx["en_by_id"] if lang == "en" else i18n_ctx["ja_by_id"]
        if tid in lang_map and lang_map[tid]:
            return lang_map[tid]
    return name_zh


def _is_valid_ogg(p: Path) -> bool:
    if not p.is_file():
        return False
    try:
        if p.stat().st_size < 64:
            return False
        with p.open("rb") as f:
            return f.read(4) == b"OggS"
    except Exception:
        return False


def convert_all_wavs_to_ogg(
    ffmpeg_path: Path,
    workers: int = 12,
    batch_size: int = 16,
) -> dict[str, Any]:
    """Deduplicate all .wav files across Live2D and Spine, encode to .ogg, and remove .wav."""
    t0 = time.perf_counter()
    l2d_wavs = list(LIVE2D_ROOT.rglob("*.wav"))
    sp_wavs = list(SPINE_ROOT.rglob("*.wav"))
    all_wavs = l2d_wavs + sp_wavs
    if not all_wavs:
        existing_oggs = list(LIVE2D_ROOT.rglob("*.ogg")) + list(SPINE_ROOT.rglob("*.ogg"))
        print(f"[OGG] 0 WAV files remaining; {len(existing_oggs)} OGG files already on disk.", flush=True)
        return {
            "wav_files_found": 0,
            "unique_clips": 0,
            "wav_bytes_before": 0,
            "ogg_bytes_after": sum(p.stat().st_size for p in existing_oggs),
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }

    wav_bytes_before = sum(p.stat().st_size for p in all_wavs)
    groups: dict[tuple[str, int], list[Path]] = {}
    for w in all_wavs:
        key = (w.name.lower(), w.stat().st_size)
        groups.setdefault(key, []).append(w)

    print(
        f"[OGG] Found {len(all_wavs)} WAV files ({wav_bytes_before / 1048576:.1f} MB) -> "
        f"{len(groups)} unique AudioClips. Starting batched FFmpeg Vorbis encoding (workers={workers}, batch={batch_size})...",
        flush=True,
    )

    to_encode: list[tuple[Path, Path, list[Path]]] = []
    ready_groups: list[tuple[Path, list[Path]]] = []

    for _key, paths in groups.items():
        existing_ogg = next((p.with_suffix(".ogg") for p in paths if _is_valid_ogg(p.with_suffix(".ogg"))), None)
        if existing_ogg is not None:
            ready_groups.append((existing_ogg, paths))
        else:
            src_wav = paths[0]
            dst_ogg = src_wav.with_suffix(".ogg")
            to_encode.append((src_wav, dst_ogg, paths))

    batches = [to_encode[i : i + batch_size] for i in range(0, len(to_encode), batch_size)]

    def _encode_batch(b_idx: int, batch: list[tuple[Path, Path, list[Path]]]) -> int:
        cmd = [str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y"]
        for src_wav, _dst_ogg, _paths in batch:
            cmd.extend(["-i", str(src_wav)])
        for idx, (_src_wav, dst_ogg, _paths) in enumerate(batch):
            cmd.extend(["-map", f"{idx}:a:0", "-c:a", "libvorbis", "-q:a", "5", str(dst_ogg)])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            # Fallback to per-file encode if a batch command failed
            for src_wav, dst_ogg, _paths in batch:
                r1 = subprocess.run(
                    [str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src_wav), "-c:a", "libvorbis", "-q:a", "5", str(dst_ogg)],
                    capture_output=True,
                    text=True,
                )
                if r1.returncode != 0:
                    raise RuntimeError(f"FFmpeg failed on {src_wav}: {r1.stderr}")
        for src_wav, dst_ogg, paths in batch:
            if not _is_valid_ogg(dst_ogg):
                raise RuntimeError(f"Encoded OGG invalid or missing OggS header: {dst_ogg}")
            for p in paths:
                target_ogg = p.with_suffix(".ogg")
                if target_ogg.resolve() != dst_ogg.resolve():
                    shutil.copy2(dst_ogg, target_ogg)
                    if not _is_valid_ogg(target_ogg):
                        raise RuntimeError(f"Copied OGG invalid: {target_ogg}")
            for p in paths:
                if p.is_file():
                    p.unlink()
        return len(batch)

    # First finalize any ready_groups where an OGG already existed
    for existing_ogg, paths in ready_groups:
        for p in paths:
            target_ogg = p.with_suffix(".ogg")
            if target_ogg.resolve() != existing_ogg.resolve():
                shutil.copy2(existing_ogg, target_ogg)
            if not _is_valid_ogg(target_ogg):
                raise RuntimeError(f"Existing OGG propagation failed: {target_ogg}")
        for p in paths:
            if p.is_file():
                p.unlink()

    encoded_unique = 0
    total_unique_to_encode = len(to_encode)
    if batches:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_encode_batch, i, b): i for i, b in enumerate(batches, 1)}
            done_batches = 0
            for fut in as_completed(futs):
                cnt = fut.result()
                encoded_unique += cnt
                done_batches += 1
                if done_batches % 25 == 0 or done_batches == len(batches):
                    el = time.perf_counter() - t0
                    print(
                        f"  [OGG] Batch {done_batches}/{len(batches)} "
                        f"({encoded_unique}/{total_unique_to_encode} unique clips, {el:.1f}s)...",
                        flush=True,
                    )

    remaining_wavs = list(LIVE2D_ROOT.rglob("*.wav")) + list(SPINE_ROOT.rglob("*.wav"))
    if remaining_wavs:
        raise RuntimeError(f"Still found {len(remaining_wavs)} leftover WAV files after conversion!")

    all_oggs = list(LIVE2D_ROOT.rglob("*.ogg")) + list(SPINE_ROOT.rglob("*.ogg"))
    ogg_bytes_after = sum(p.stat().st_size for p in all_oggs)
    dt = time.perf_counter() - t0
    print(
        f"[OGG] Completed {len(all_oggs)} OGG files in {dt:.1f}s | "
        f"WAV {wav_bytes_before / 1048576:.1f} MB -> OGG {ogg_bytes_after / 1048576:.1f} MB "
        f"({ogg_bytes_after / max(1, wav_bytes_before) * 100:.1f}%)",
        flush=True,
    )
    return {
        "wav_files_found": len(all_wavs),
        "unique_clips": len(groups),
        "ogg_files_total": len(all_oggs),
        "wav_bytes_before": wav_bytes_before,
        "ogg_bytes_after": ogg_bytes_after,
        "elapsed_sec": round(dt, 2),
    }


def _wav_to_ogg_ref(snd: str) -> str:
    if snd.lower().endswith(".wav"):
        return snd[:-4] + ".ogg"
    return snd


def _build_l2d_lang_cfg(
    base_data: dict[str, Any],
    char_zh: str,
    skin_zh: str,
    lang: str,
    i18n_ctx: dict[str, Any],
) -> dict[str, Any]:
    """Build model_en.model3.json or model_ja.model3.json from the OGG-updated .model3.json."""
    data = copy.deepcopy(base_data)
    fr = data.get("FileReferences") or {}

    # 1. Translate Expressions display names
    for exp in fr.get("Expressions") or []:
        nm = exp.get("Name", "")
        if nm in EXP_NAME_TRANSLATIONS:
            exp["Name"] = EXP_NAME_TRANSLATIONS[nm][lang]

    char_loc = translate_label(char_zh, lang, i18n_ctx)
    skin_loc = translate_label(skin_zh, lang, i18n_ctx)
    is_base = skin_zh == "原皮" or skin_zh.startswith("原皮_")

    if lang == "en":
        skin_cat_title = (
            f"{skin_loc} · Touch & Interaction Voices"
            if is_base
            else f"{skin_loc} · Outfit Voices & Motions"
        )
    else:
        skin_cat_title = (
            f"{skin_loc} · タッチ＆ふれあいボイス"
            if is_base
            else f"{skin_loc} · 衣装専用ボイス＆モーション"
        )

    cat_titles_for_pkg: dict[str, str] = {"Menu_Cat_Skin": skin_cat_title}
    for cid, tdict in MENU_CAT_TITLES.items():
        cat_titles_for_pkg[cid] = tdict[lang]

    mots: dict[str, list[dict[str, Any]]] = fr.get("Motions") or {}

    # 2. First pass: translate all non-menu motion entries (including MenuPlay_NNN)
    for grp, items in mots.items():
        if grp in ("Tap", "语音菜单") or grp.startswith("Menu_Cat_"):
            continue
        for item in items:
            if "Sound" in item and item["Sound"]:
                item["Sound"] = _wav_to_ogg_ref(item["Sound"])
            if "Text" in item and item["Text"]:
                item["Text"] = translate_voice_text(
                    item["Text"],
                    item.get("Sound", ""),
                    lang,
                    i18n_ctx,
                )

    # 3. Second pass: translate interactive menu nodes (Tap, 语音菜单, Menu_Cat_*, Menu_Cat_*_pN)
    for grp, items in mots.items():
        if grp in ("Tap", "语音菜单"):
            for item in items:
                if lang == "en":
                    item["Text"] = f"Select a voice & motion category for {char_loc} (Press 1 / M / V or tap blank area):"
                else:
                    item["Text"] = f"{char_loc}のボイス・モーションカテゴリを選択してください（1 / M / V キーまたは空白タップ）："
                for ch in item.get("Choices") or []:
                    nxt = ch.get("NextMtn", "")
                    m_cnt = re.search(r"\((\d+)\)\s*$", ch.get("Text", ""))
                    cnt_sfx = f" ({m_cnt.group(1)})" if m_cnt else ""
                    if nxt in cat_titles_for_pkg:
                        ch["Text"] = f"{cat_titles_for_pkg[nxt]}{cnt_sfx}"
        elif grp.startswith("Menu_Cat_"):
            base_cat = re.sub(r"_p\d+$", "", grp)
            cat_title = cat_titles_for_pkg.get(base_cat, base_cat)
            for item in items:
                m_pg = re.search(r"\((\d+/\d+)\)", item.get("Text", ""))
                pg_str = m_pg.group(1) if m_pg else "1/1"
                if lang == "en":
                    item["Text"] = f"[{cat_title}] ({pg_str}) Click an option to play:"
                else:
                    item["Text"] = f"【{cat_title}】({pg_str}) 選択すると再生します："

                for ch in item.get("Choices") or []:
                    nxt = ch.get("NextMtn", "")
                    old_lbl = ch.get("Text", "")
                    if nxt.startswith("MenuPlay_") and nxt in mots and mots[nxt]:
                        play_item = mots[nxt][0]
                        ptxt = (play_item.get("Text") or "").strip().replace("\n", " ")
                        if ptxt:
                            limit = 28 if lang == "en" else 20
                            ch["Text"] = f"{ptxt[:limit]}…" if len(ptxt) > limit else ptxt
                    elif nxt == "语音菜单":
                        ch["Text"] = "« Back to Voice Menu" if lang == "en" else "« ボイスメニューに戻る"
                    elif "下一页" in old_lbl:
                        m_p = re.search(r"\((\d+/\d+)\)", old_lbl)
                        p_str = f"({m_p.group(1)}) " if m_p else ""
                        ch["Text"] = f"Next Page {p_str}▶" if lang == "en" else f"次のページ {p_str}▶"
                    elif "上一页" in old_lbl:
                        m_p = re.search(r"\((\d+/\d+)\)", old_lbl)
                        p_str = f" ({m_p.group(1)})" if m_p else ""
                        ch["Text"] = f"◀ Prev Page{p_str}" if lang == "en" else f"◀ 前のページ{p_str}"

    return data


def update_all_live2d_configs(l2d_cfgs: list[Path], i18n_ctx: dict[str, Any]) -> int:
    """Update .model3.json (.wav -> .ogg) and write model_en.model3.json + model_ja.model3.json."""
    count = 0
    for cfg_path in l2d_cfgs:
        pkg_dir = cfg_path.parent
        char_zh = pkg_dir.parent.name
        skin_zh = pkg_dir.name
        data = json.loads(cfg_path.read_text(encoding="utf-8"))

        # Update .wav -> .ogg in base zh-cn .model3.json
        mots = (data.get("FileReferences") or {}).get("Motions") or {}
        for _grp, items in mots.items():
            for item in items:
                if "Sound" in item and item["Sound"]:
                    item["Sound"] = _wav_to_ogg_ref(item["Sound"])

        write_json(pkg_dir / ".model3.json", data)
        en_data = _build_l2d_lang_cfg(data, char_zh, skin_zh, "en", i18n_ctx)
        ja_data = _build_l2d_lang_cfg(data, char_zh, skin_zh, "ja", i18n_ctx)
        write_json(pkg_dir / "model_en.model3.json", en_data)
        write_json(pkg_dir / "model_ja.model3.json", ja_data)
        count += 1
    print(f"[Live2D] Updated {count} packages with .ogg references + model_en.model3.json + model_ja.model3.json", flush=True)
    return count


def _build_spine_lang_cfg(
    base_cfg: dict[str, Any],
    lang: str,
    i18n_ctx: dict[str, Any],
) -> dict[str, Any]:
    """Build config_en.config.json or config_ja.config.json from the OGG-updated .config.json."""
    cfg = copy.deepcopy(base_cfg)
    for _grp, items in (cfg.get("motions") or {}).items():
        for item in items:
            if "sound" in item and item["sound"]:
                item["sound"] = _wav_to_ogg_ref(item["sound"])
            if "text" in item and item["text"]:
                item["text"] = translate_voice_text(
                    item["text"],
                    item.get("sound", ""),
                    lang,
                    i18n_ctx,
                )
    return cfg


def update_all_spine_configs(spine_cfgs: list[Path], i18n_ctx: dict[str, Any]) -> int:
    """Update .config.json (.wav -> .ogg) and write config_en.config.json + config_ja.config.json."""
    count = 0
    for cfg_path in spine_cfgs:
        pkg_dir = cfg_path.parent
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

        for _grp, items in (cfg.get("motions") or {}).items():
            for item in items:
                if "sound" in item and item["sound"]:
                    item["sound"] = _wav_to_ogg_ref(item["sound"])

        write_json(pkg_dir / ".config.json", cfg)
        en_cfg = _build_spine_lang_cfg(cfg, "en", i18n_ctx)
        ja_cfg = _build_spine_lang_cfg(cfg, "ja", i18n_ctx)
        write_json(pkg_dir / "config_en.config.json", en_cfg)
        write_json(pkg_dir / "config_ja.config.json", ja_cfg)
        count += 1
    print(f"[Spine] Updated {count} packages with .ogg references + config_en.config.json + config_ja.config.json", flush=True)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Scheme A multi-language config builder & WAV->OGG converter.")
    parser.add_argument("--workers", type=int, default=max(1, min(12, os.cpu_count() or 8)))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--skip-ogg", action="store_true", help="Only regenerate multi-language JSON configs")
    args = parser.parse_args()

    ffmpeg_str = shutil.which("ffmpeg")
    ffmpeg_path = Path(ffmpeg_str) if ffmpeg_str else FFMPEG_DEFAULT
    if not ffmpeg_path.is_file():
        raise FileNotFoundError(f"FFmpeg executable not found at {ffmpeg_path}")

    l2d_cfgs = sorted(LIVE2D_ROOT.glob("*/*/.model3.json"))
    spine_cfgs = sorted(SPINE_ROOT.glob("*/*/.config.json"))
    print(f"[Fleet] Found {len(l2d_cfgs)} Live2D packages and {len(spine_cfgs)} Spine packages.", flush=True)

    i18n_ctx = build_low_memory_i18n_tables(l2d_cfgs, spine_cfgs)

    ogg_stats = {}
    if not args.skip_ogg:
        ogg_stats = convert_all_wavs_to_ogg(ffmpeg_path, workers=args.workers, batch_size=args.batch_size)

    l2d_cnt = update_all_live2d_configs(l2d_cfgs, i18n_ctx)
    sp_cnt = update_all_spine_configs(spine_cfgs, i18n_ctx)

    report = {
        "live2d_packages_updated": l2d_cnt,
        "spine_packages_updated": sp_cnt,
        "ogg_conversion": ogg_stats,
    }
    write_json(REPORT_PATH, report)
    print(f"[Fleet] ALL DONE -> {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    main()
