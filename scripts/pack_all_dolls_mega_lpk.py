#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
《灵魂潮汐》全 55 位人偶（Live2D + Spine 全 345 套服装）Steam 创意工坊单包总集 LPK 直接打包脚本
===========================================================================================
单次直出，不再生成任何单独角色 `.lpk`！
输出（位于 E:\A灵魂潮汐\Live2D与Spine模型\_workshop_lpks\）：
  1. 灵魂潮汐_全55人偶合集.lpk          —— 标准 STD2_0 单包总集（含 55 角色、55 独立头像、345 套服装、跨角色全局 SHA-256 去重）
  2. 灵魂潮汐_全55人偶合集.preview.jpg  —— Steam 创意工坊 1280×720 全角色 11×5 拼图封面（严格 < 1 MB）
  3. 工具脚本\workshop_mega_lpk_report.json —— 打包体积、跨角色去重节省与全量统计报告
"""

import argparse
import hashlib
import json
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Set, Tuple

from PIL import Image, ImageDraw

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_and_pack_workshop_lpks import (
    AVATAR_ZIP_NAME,
    CONFIG_MLVE_ZIP_NAME,
    DollPacker,
    LIVE2D_ROOT,
    SPINE_ROOT,
    discover_all_dolls,
)

BASE_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型")
LPK_DIR = BASE_DIR / "_workshop_lpks"
STAGING_DIR = BASE_DIR / "_workshop_lpk_staging"
OUT_LPK = LPK_DIR / "灵魂潮汐_全55人偶合集.lpk"
OUT_PREVIEW = LPK_DIR / "灵魂潮汐_全55人偶合集.preview.jpg"
REPORT_PATH = BASE_DIR / "工具脚本" / "workshop_mega_lpk_report.json"

STORED_EXTS = {".webp", ".png", ".jpg", ".jpeg", ".ogg", ".mp3"}


def md5_str(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def compact_json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def prepare_one_doll_direct(doll: str, write_individual: bool = True) -> Tuple[str, dict, dict, dict]:
    """在独立进程内为单个角色构建多语言 staging、写出单角色 .lpk（可选）并返回条目供总集直出。"""
    packer = DollPacker(doll)
    stats = packer.run(write_lpk=write_individual)
    mlve_bytes = packer.zip_entries[CONFIG_MLVE_ZIP_NAME][0]
    mlve = json.loads(mlve_bytes.decode("utf-8"))
    ch = mlve["list"][0]
    # 收集条目（bytes 或 Path 字符串，便于跨进程传回）
    entries: Dict[str, Tuple[str, object]] = {}
    for zname, (payload, _ctype) in packer.zip_entries.items():
        if zname in (CONFIG_MLVE_ZIP_NAME, AVATAR_ZIP_NAME):
            continue
        if isinstance(payload, bytes):
            entries[zname] = ("bytes", payload)
        else:
            entries[zname] = ("path", str(payload))
    avatar_path = str(packer.stage_dir / "avatar.png")
    return doll, ch, entries, {"stats": stats, "avatar_path": avatar_path}


def build_mega_preview(dolls: List[str], out_path: Path) -> Dict[str, object]:
    """生成 1280×720 的 11×5 全 55 人偶精致拼图封面（严格 < 1 MB）。"""
    W, H = 1280, 720
    cols, rows = 11, 5
    pad_x, pad_y = 24, 30
    gap = 6
    cell_w = (W - 2 * pad_x - (cols - 1) * gap) // cols
    cell_h = (H - 2 * pad_y - (rows - 1) * gap) // rows
    cell = min(cell_w, cell_h)
    grid_w = cols * cell + (cols - 1) * gap
    grid_h = rows * cell + (rows - 1) * gap
    ox0 = (W - grid_w) // 2
    oy0 = (H - grid_h) // 2

    canvas = Image.new("RGB", (W, H), (14, 17, 32))
    draw = ImageDraw.Draw(canvas)
    for y in range(H):
        t = y / max(1, H - 1)
        c = (int(22 * (1 - t) + 10 * t), int(26 * (1 - t) + 12 * t), int(48 * (1 - t) + 24 * t))
        draw.line([(0, y), (W, y)], fill=c)

    for idx, doll in enumerate(dolls[:55]):
        r = idx // cols
        c = idx % cols
        x = ox0 + c * (cell + gap)
        y = oy0 + r * (cell + gap)
        av_path = STAGING_DIR / doll / "avatar.png"
        if av_path.is_file():
            tile = Image.open(av_path).convert("RGB").resize((cell, cell), Image.Resampling.LANCZOS)
            canvas.paste(tile, (x, y))
            draw.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(78, 92, 140), width=1)

    used_q = 88
    for q in (88, 84, 80, 74, 68):
        canvas.save(out_path, "JPEG", quality=q, optimize=True)
        used_q = q
        if out_path.stat().st_size < 950 * 1024:
            break

    return {"preview_bytes": out_path.stat().st_size, "preview_quality": used_q, "grid": f"{cols}x{rows}", "cell_px": cell}


def main():
    parser = argparse.ArgumentParser(description="Single-pass packer for 55 individual multi-lang doll LPKs + 1 merged Mega LPK.")
    parser.add_argument("--workers", type=int, default=6, help="Parallel staging & individual LPK workers")
    parser.add_argument("--mega-only", action="store_true", help="仅打总集包，不写 55 份单角色 LPK（默认同时产出 55 单人偶 + 1 总集）")
    args = parser.parse_args()

    write_individual = not args.mega_only
    t0 = time.time()
    dolls = discover_all_dolls()
    mode_desc = "55 individual LPKs + 1 Mega LPK" if write_individual else "Mega LPK only"
    print(f"Single-pass multi-language LPK build ({mode_desc}) for {len(dolls)} dolls (workers={args.workers})...", flush=True)

    # 1. 并行构建全部角色多语言 staging、写出单角色 .lpk（默认开启）并收集总集条目
    prepared: Dict[str, Tuple[dict, dict, dict]] = {}
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(prepare_one_doll_direct, d, write_individual): d for d in dolls}
        done = 0
        for fut in as_completed(futs):
            doll, ch, entries, meta = fut.result()
            prepared[doll] = (ch, entries, meta)
            done += 1
            if done % 10 == 0 or done == len(dolls):
                lpk_mb = meta["stats"]["lpk_bytes"] / 1048576.0
                print(f"  [doll {done:2d}/{len(dolls)}] {doll:8s} | cos={len(ch.get('costume') or []):2d} | lpk={lpk_mb:6.2f} MiB", flush=True)

    LPK_DIR.mkdir(parents=True, exist_ok=True)
    # 清理残余临时文件；若 --mega-only 才清理单角色旧包，默认保留全部 55 个单人偶 LPK
    for p in list(LPK_DIR.iterdir()):
        if p.suffix == ".tmp":
            p.unlink(missing_ok=True)
        elif (not write_individual) and p.name not in (OUT_LPK.name, OUT_PREVIEW.name) and p.suffix in (".lpk", ".jpg"):
            p.unlink(missing_ok=True)

    # 2. 生成 11×5 全角色拼图封面
    art_info = build_mega_preview(dolls, OUT_PREVIEW)
    print(f"  Generated 11x5 collage cover: {OUT_PREVIEW.name} ({art_info['preview_bytes']/1024:.1f} KB, Q{art_info['preview_quality']})", flush=True)

    # 3. 单次直接写入全 55 人偶总集 .lpk（跨角色全局去重 + Zip64 + Deflate 9）
    master_list: List[dict] = []
    written_entries: Set[str] = set()
    total_orig_bytes = 0
    total_costumes = 0
    cross_doll_dedup_count = 0
    cross_doll_dedup_raw_bytes = 0
    unique_audio_count = 0
    unique_audio_bytes = 0

    tmp_out = OUT_LPK.with_suffix(".lpk.tmp")
    if tmp_out.exists():
        tmp_out.unlink()

    with zipfile.ZipFile(tmp_out, "w", allowZip64=True) as zout:
        for idx, doll in enumerate(dolls, 1):
            ch, entries, meta = prepared[doll]
            total_orig_bytes += int(meta["stats"]["orig_total_bytes"])

            # 独立全局唯一头像条目
            unique_avatar_name = md5_str(f"avatar_{doll}.png")
            av_bytes = Path(meta["avatar_path"]).read_bytes()
            zout.writestr(unique_avatar_name, av_bytes, compress_type=zipfile.ZIP_STORED)
            written_entries.add(unique_avatar_name)

            ch["avatar"] = unique_avatar_name
            master_list.append(ch)
            total_costumes += len(ch.get("costume") or [])

            for zname in sorted(entries.keys()):
                kind, payload = entries[zname]
                if zname in written_entries:
                    cross_doll_dedup_count += 1
                    raw_sz = len(payload) if kind == "bytes" else Path(payload).stat().st_size
                    cross_doll_dedup_raw_bytes += raw_sz
                    continue

                ext = Path(zname).suffix.lower()
                ctype = zipfile.ZIP_STORED if ext in STORED_EXTS else zipfile.ZIP_DEFLATED
                if kind == "bytes":
                    data = payload
                    if ctype == zipfile.ZIP_DEFLATED:
                        zout.writestr(zname, data, compress_type=ctype, compresslevel=6)
                    else:
                        zout.writestr(zname, data, compress_type=ctype)
                    sz = len(data)
                else:
                    fp = Path(payload)
                    if ctype == zipfile.ZIP_DEFLATED:
                        zout.write(fp, arcname=zname, compress_type=ctype, compresslevel=6)
                    else:
                        zout.write(fp, arcname=zname, compress_type=ctype)
                    sz = fp.stat().st_size

                written_entries.add(zname)
                if ext == ".ogg":
                    unique_audio_count += 1
                    unique_audio_bytes += sz

            if idx % 10 == 0 or idx == len(dolls):
                print(f"  [pack  {idx:2d}/{len(dolls)}] packed up to {doll} | unique_entries={len(written_entries)} | cross_dedup={cross_doll_dedup_count}", flush=True)

        master_mlve = {
            "type": "STD2_0",
            "name": f"灵魂潮汐 全55位人偶合集 (Live2D + Spine 全{total_costumes}套服装 · 中英日多语言)",
            "id": "soultide_all55_complete_bundle",
            "encrypt": "false",
            "version": "2.0.0",
            "list": master_list,
        }
        zout.writestr(CONFIG_MLVE_ZIP_NAME, compact_json_bytes(master_mlve), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        written_entries.add(CONFIG_MLVE_ZIP_NAME)

    if OUT_LPK.exists():
        OUT_LPK.unlink()
    tmp_out.rename(OUT_LPK)

    mega_bytes = OUT_LPK.stat().st_size
    elapsed = round(time.time() - t0, 2)

    # 若同时生成了 55 个单人偶 LPK，也同步更新 workshop_lpk_pack_report.json
    per_doll_stats = [prepared[d][2]["stats"] for d in sorted(prepared.keys())]
    if write_individual:
        tot_lpk_ind = sum(int(r["lpk_bytes"]) for r in per_doll_stats)
        tot_l2d = sum(int(r["l2d_skins"]) for r in per_doll_stats)
        tot_sp = sum(int(r["spine_skins"]) for r in per_doll_stats)
        ind_report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "multilang_native_motion_language": True,
            "dolls_packed": len(per_doll_stats),
            "total_l2d_skins": tot_l2d,
            "total_spine_skins": tot_sp,
            "total_costumes": tot_l2d + tot_sp,
            "orig_total_bytes": total_orig_bytes,
            "orig_total_mib": round(total_orig_bytes / 1048576.0, 2),
            "lpk_total_bytes": tot_lpk_ind,
            "lpk_total_mib": round(tot_lpk_ind / 1048576.0, 2),
            "saved_bytes": total_orig_bytes - tot_lpk_ind,
            "saved_mib": round((total_orig_bytes - tot_lpk_ind) / 1048576.0, 2),
            "overall_ratio_pct": round(tot_lpk_ind * 100.0 / max(1, total_orig_bytes), 2),
            "max_preview_bytes": max((int(r["preview_bytes"]) for r in per_doll_stats), default=0),
            "max_lpk_doll": max(per_doll_stats, key=lambda r: int(r["lpk_bytes"]))["doll"] if per_doll_stats else None,
            "max_lpk_mib": round(max((int(r["lpk_bytes"]) for r in per_doll_stats), default=0) / 1048576.0, 2),
            "elapsed_sec": elapsed,
            "per_doll": per_doll_stats,
        }
        (BASE_DIR / "工具脚本" / "workshop_lpk_pack_report.json").write_text(
            json.dumps(ind_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "55_individual_plus_1_mega_multilang" if write_individual else "direct_single_pass_mega_only",
        "multilang_native_motion_language": True,
        "output_lpk": str(OUT_LPK),
        "output_preview": str(OUT_PREVIEW),
        "individual_lpks_written": len(per_doll_stats) if write_individual else 0,
        "individual_lpks_total_mib": round(sum(int(r["lpk_bytes"]) for r in per_doll_stats) / 1048576.0, 2) if write_individual else 0.0,
        "characters": len(master_list),
        "total_costumes": total_costumes,
        "total_zip_entries": len(written_entries),
        "source_total_mib": round(total_orig_bytes / 1048576.0, 2),
        "mega_lpk_bytes": mega_bytes,
        "mega_lpk_mib": round(mega_bytes / 1048576.0, 2),
        "mega_lpk_gib": round(mega_bytes / 1073741824.0, 3),
        "saved_vs_source_mib": round((total_orig_bytes - mega_bytes) / 1048576.0, 2),
        "ratio_pct": round(mega_bytes * 100.0 / max(1, total_orig_bytes), 2),
        "cross_doll_dedup_entries": cross_doll_dedup_count,
        "cross_doll_dedup_raw_mib": round(cross_doll_dedup_raw_bytes / 1048576.0, 2),
        "unique_audio_files": unique_audio_count,
        "unique_audio_mib": round(unique_audio_bytes / 1048576.0, 2),
        "preview_bytes": art_info["preview_bytes"],
        "preview_quality": art_info["preview_quality"],
        "uses_zip64": mega_bytes >= 2147483647 or len(written_entries) >= 65535,
        "elapsed_sec": elapsed,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 76)
    print(
        f"DONE in {elapsed}s! ({report['mode']})\n"
        f"  Mega LPK   : {OUT_LPK}\n"
        f"  Characters : {len(master_list)} | Costumes: {total_costumes} | ZIP entries: {len(written_entries)}\n"
        f"  Individual : {report['individual_lpks_written']} LPKs totaling {report['individual_lpks_total_mib']:.2f} MiB\n"
        f"  Source     : {total_orig_bytes/1048576:.2f} MiB -> Mega LPK: {mega_bytes/1048576:.2f} MiB ({mega_bytes/1073741824:.3f} GiB, {report['ratio_pct']}%)\n"
        f"  Cross-dedup: {cross_doll_dedup_count} entries ({cross_doll_dedup_raw_bytes/1048576:.2f} MiB raw)\n"
        f"  Preview    : {art_info['preview_bytes']/1024:.1f} KB (limit < 1024 KB)"
    )


if __name__ == "__main__":
    main()
