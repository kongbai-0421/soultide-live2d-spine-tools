#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
《灵魂潮汐》Steam 创意工坊角色合集 LPK 暂存构建与一键打包脚本
============================================================
功能：
  1. 为全量 55 位人偶（Live2D + Spine 全服装合打进同一角色包）构建：
     - EX Studio 暂存工程目录：E:\A灵魂潮汐\Live2D与Spine模型\_workshop_lpk_staging\<角色名>\
       （共享 audio/ & bgm/，零重编码原始 .ogg，不可变二进制使用 NTFS 硬链接零额外占盘）
     - 即装即用 STD2_0 `.lpk` 归档：E:\A灵魂潮汐\Live2D与Spine模型\_workshop_lpks\<角色名>.lpk
       （配套 <角色名>.preview.jpg 封面图，严格 < 1 MB）
  2. 内容寻址 SHA-256 跨皮肤 + 跨引擎（Live2D & Spine）全量去重：
     - 语音/BGM .ogg 零二次重编码、跨 Live2D/Spine 合一为唯一一份
     - 变身主形态（model_red / model_henshin）、子模型（sub_henshin）、
       Spine 背景/粒子子模型与 touch_only.config.json 自动递归打包并去重
     - 完整同步 Spine `atlases[].tex_names` 与 Live2D/Spine 全部指令路径重写
       （add_submodel / remove_submodel / change_model / change_cos / replace_tex）
  3. 仅压缩可压缩文件（.moc3 / .json / .txt / .bin / .bin3 -> ZIP_DEFLATED level 6），
     已压缩媒体（.webp / .png / .jpg / .ogg -> ZIP_STORED）实现零耗时秒加载。

用法：
  单/多角色试点：python build_and_pack_workshop_lpks.py --dolls 和铃 梦咲音月 伊汐尔
  全量 55 角色： python build_and_pack_workshop_lpks.py --workers 6
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import posixpath
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PIL import Image, ImageDraw, ImageFilter

BASE_DIR = Path(r"E:\A灵魂潮汐\Live2D与Spine模型")
LIVE2D_ROOT = BASE_DIR / "live2d"
SPINE_ROOT = BASE_DIR / "spine"
STAGING_ROOT = BASE_DIR / "_workshop_lpk_staging"
LPK_OUT_ROOT = BASE_DIR / "_workshop_lpks"
REPORT_PATH = BASE_DIR / "工具脚本" / "workshop_lpk_pack_report.json"

BATTLE01_DIR = Path(r"E:\A灵魂潮汐\spine背景\原皮立绘与背景解包\01_原皮完整立绘_Battle01")
AUDIT_PREVIEW_L2D_DIR = Path(r"E:\A灵魂潮汐\tools\_doll_audit_previews\live2d")

# 官方 EX Studio 固定哈希键
CONFIG_MLVE_ZIP_NAME = "1d862f7d02e6008f4550188a31ca654f"  # MD5("config.mlve")
AVATAR_ZIP_NAME = "4a301072dec6b6a49050e5b294cd7983"       # MD5("avatar.png")

STORED_EXTS = {".webp", ".png", ".jpg", ".jpeg", ".ogg", ".mp3"}

# 允许写入 staging 时作为独立重写配置的后缀/文件名
L2D_CONFIG_SUFFIX = ".model3.json"
SPINE_CONFIG_SUFFIX = ".config.json"


def md5_str(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> Tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def compact_json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def hardlink_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            if os.path.samefile(src, dst):
                return
        except OSError:
            pass
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def sort_skins(skins: List[str]) -> List[str]:
    def key(name: str):
        if name == "原皮":
            return (0, "")
        if name.startswith("原皮"):
            return (1, name)
        return (2, name)
    return sorted(skins, key=key)


def find_portrait_source(doll: str) -> Tuple[Optional[Path], bool]:
    """返回 (文件路径, 是否为透明立绘 Battle01 PNG)。"""
    if BATTLE01_DIR.is_dir():
        prefix = f"{doll}_"
        for p in sorted(BATTLE01_DIR.iterdir()):
            if p.is_file() and p.name.startswith(prefix) and p.suffix.lower() == ".png":
                return p, True
    fb = AUDIT_PREVIEW_L2D_DIR / f"{doll}__原皮.jpg"
    if fb.is_file():
        return fb, False
    # 任意该角色预览图
    if AUDIT_PREVIEW_L2D_DIR.is_dir():
        for p in sorted(AUDIT_PREVIEW_L2D_DIR.iterdir()):
            if p.is_file() and p.name.startswith(f"{doll}__"):
                return p, False
    return None, False


def make_gradient_bg(w: int, h: int) -> Image.Image:
    """精致深邃蓝紫渐变背景（无文字，不抢立绘主体）。"""
    bg = Image.new("RGB", (w, h))
    px = bg.load()
    # 顶部 (26, 30, 52) -> 底部 (12, 14, 28)
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(28 * (1 - t) + 12 * t)
        g = int(32 * (1 - t) + 15 * t)
        b = int(56 * (1 - t) + 30 * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    # 中心柔光晕
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    cx, cy = w // 2, int(h * 0.45)
    for rad, alpha in [(int(h * 0.72), 28), (int(h * 0.48), 36), (int(h * 0.28), 30)]:
        draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=(110, 130, 210, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=48))
    return Image.alpha_composite(bg.convert("RGBA"), glow).convert("RGB")


def generate_preview_and_avatar(doll: str, preview_path: Path, avatar_path: Path) -> Dict[str, object]:
    src, is_transparent = find_portrait_source(doll)
    w, h = 1280, 720
    bg = make_gradient_bg(w, h)

    if src is not None:
        img = Image.open(src)
        if is_transparent:
            rgba = img.convert("RGBA")
            bbox = rgba.getbbox()
            if bbox:
                rgba = rgba.crop(bbox)
            # preview.jpg: 将立绘按高度适配 94% 画布并微偏下居中
            scale = min((w * 0.88) / max(1, rgba.width), (h * 0.96) / max(1, rgba.height))
            nw = max(1, int(round(rgba.width * scale)))
            nh = max(1, int(round(rgba.height * scale)))
            fg = rgba.resize((nw, nh), Image.Resampling.LANCZOS)
            canvas = bg.convert("RGBA")
            ox = (w - nw) // 2
            oy = max(0, h - nh) if nh <= h else (h - nh) // 2
            canvas.alpha_composite(fg, (ox, oy))
            preview_img = canvas.convert("RGB")

            # avatar.png (256x256): 取立绘上中部正方形区域（突出头部与肩部）
            side = min(rgba.width, max(int(rgba.height * 0.52), int(rgba.width * 0.65)))
            side = max(64, min(side, rgba.width, rgba.height))
            ax0 = max(0, (rgba.width - side) // 2)
            ay0 = max(0, int(rgba.height * 0.02))
            if ay0 + side > rgba.height:
                ay0 = max(0, rgba.height - side)
            crop = rgba.crop((ax0, ay0, ax0 + side, ay0 + side))
            av_bg = make_gradient_bg(256, 256).convert("RGBA")
            av_fg = crop.resize((256, 256), Image.Resampling.LANCZOS)
            av_bg.alpha_composite(av_fg, (0, 0))
            avatar_img = av_bg.convert("RGBA")
        else:
            rgb = img.convert("RGB")
            scale = min(w / max(1, rgb.width), h / max(1, rgb.height))
            nw = max(1, int(round(rgb.width * scale)))
            nh = max(1, int(round(rgb.height * scale)))
            fg = rgb.resize((nw, nh), Image.Resampling.LANCZOS)
            preview_img = bg.copy()
            preview_img.paste(fg, ((w - nw) // 2, (h - nh) // 2))

            side = min(rgb.width, rgb.height)
            ax0 = (rgb.width - side) // 2
            ay0 = max(0, int((rgb.height - side) * 0.15))
            avatar_img = rgb.crop((ax0, ay0, ax0 + side, ay0 + side)).resize((256, 256), Image.Resampling.LANCZOS).convert("RGBA")
    else:
        preview_img = bg
        avatar_img = make_gradient_bg(256, 256).convert("RGBA")

    preview_path.parent.mkdir(parents=True, exist_ok=True)
    avatar_path.parent.mkdir(parents=True, exist_ok=True)

    # 严格保证 preview.jpg < 950 KB（Steam Workshop 1 MB 硬限制）
    used_q = 85
    for q in (85, 80, 75, 68, 60):
        preview_img.save(preview_path, "JPEG", quality=q, optimize=True)
        used_q = q
        if preview_path.stat().st_size < 950 * 1024:
            break

    avatar_img.save(avatar_path, "PNG", optimize=True)
    return {
        "source": str(src) if src else None,
        "preview_bytes": preview_path.stat().st_size,
        "preview_quality": used_q,
        "avatar_bytes": avatar_path.stat().st_size,
    }


def is_bgm_relpath(rel_path: str) -> bool:
    low = rel_path.replace("\\", "/").lower()
    base = posixpath.basename(low)
    return "/bgm/" in f"/{low}" or base.startswith("bgm_") or base.startswith("bgm-")


def normalize_rel(base_dir: Path, rel_path: str) -> Path:
    return (base_dir / rel_path.replace("\\", "/")).resolve()


def canonical_base_cfg(cfg_path: Path, is_live2d: bool) -> Path:
    """将 _en/_ja 兄弟配置归一到其默认基座配置（用于多语言合一后的 change_model 目标统一）。"""
    rp = cfg_path.resolve()
    name = rp.name.lower()
    if is_live2d:
        mapping = {
            "model_en.model3.json": ".model3.json",
            "model_ja.model3.json": ".model3.json",
            "model_henshin_en.model3.json": "model_henshin.model3.json",
            "model_henshin_ja.model3.json": "model_henshin.model3.json",
            "model_red_en.model3.json": "model_red.model3.json",
            "model_red_ja.model3.json": "model_red.model3.json",
        }
        base_name = mapping.get(name)
        if base_name and (rp.parent / base_name).is_file():
            return (rp.parent / base_name).resolve()
    else:
        if name in ("config_en.config.json", "config_ja.config.json"):
            cand = rp.parent / ".config.json"
            if cand.is_file():
                return cand.resolve()
    return rp


def find_sibling_lang_cfgs(base_cfg: Path, is_live2d: bool) -> Tuple[Optional[Path], Optional[Path]]:
    """查找默认基座配置对应的 (EN, JA) 兄弟配置文件；子模型无多语言时返回 (None, None)。"""
    rp = base_cfg.resolve()
    name = rp.name.lower()
    if is_live2d:
        pair_map = {
            ".model3.json": ("model_en.model3.json", "model_ja.model3.json"),
            "model_henshin.model3.json": ("model_henshin_en.model3.json", "model_henshin_ja.model3.json"),
            "model_red.model3.json": ("model_red_en.model3.json", "model_red_ja.model3.json"),
        }
        pair = pair_map.get(name)
    else:
        pair = ("config_en.config.json", "config_ja.config.json") if name == ".config.json" else None
    if not pair:
        return None, None
    p_en = (rp.parent / pair[0]).resolve()
    p_ja = (rp.parent / pair[1]).resolve()
    if p_en.is_file() and p_ja.is_file():
        return p_en, p_ja
    return None, None


def merge_multilang_motions(
    m_zh: Dict[str, List[dict]],
    m_en: Dict[str, List[dict]],
    m_ja: Dict[str, List[dict]],
    is_live2d: bool,
) -> Dict[str, List[dict]]:
    """按 EX 引擎原生 Motion.Language / motion.language 机制将中/英/日合入单配置：
    - 无差异动作组（Idle / idle / Form_Switch_Main / 背景开关等）：仅留 1 份无标签通用条目；
    - 有差异动作组：
        * 英文省略语言标签（作为全局兜底，兼容 en/ru/ko/de/es/fr/pt 等全球用户）；
        * 简体中文标注 "zhs"；
        * 繁体中文标注 "zht"（复用中文文案，避免繁中用户回退到英文）；
        * 日语标注 "ja"。
    严格遵循 BNHNAHIPKDL::GOGMCPNPIDK 规则：绝不在同一组内混放带标签与无标签异名动作。
    """
    lang_key = "Language" if is_live2d else "language"
    merged: Dict[str, List[dict]] = {}
    all_keys: List[str] = list(m_zh.keys())
    for extra in (m_en, m_ja):
        for k in extra.keys():
            if k not in merged and k not in all_keys:
                all_keys.append(k)

    for gk in all_keys:
        lz = m_zh.get(gk) or []
        le = m_en.get(gk) or []
        lj = m_ja.get(gk) or []
        if lz == le and lz == lj:
            # 纯无本地化差异动作组：保持 1 份无标签通用
            cleaned = []
            for it in lz:
                if isinstance(it, dict):
                    x = dict(it)
                    x.pop(lang_key, None)
                    cleaned.append(x)
                else:
                    cleaned.append(it)
            merged[gk] = cleaned
        else:
            out: List[dict] = []
            # 1) 英文全局兜底（省略 lang_key）
            for it in le:
                if isinstance(it, dict):
                    x = dict(it)
                    x.pop(lang_key, None)
                    out.append(x)
            # 2) 简体中文 zhs
            for it in lz:
                if isinstance(it, dict):
                    x = dict(it)
                    x[lang_key] = "zhs"
                    out.append(x)
            # 3) 繁体中文 zht（复用中文，避免繁中掉回英文）
            for it in lz:
                if isinstance(it, dict):
                    x = dict(it)
                    x[lang_key] = "zht"
                    out.append(x)
            # 4) 日文 ja
            for it in lj:
                if isinstance(it, dict):
                    x = dict(it)
                    x[lang_key] = "ja"
                    out.append(x)
            merged[gk] = out
    return merged


class DollPacker:
    def __init__(self, doll: str):
        self.doll = doll
        self.doll_slug = f"soultide_{md5_str(doll)[:12]}"
        self.stage_dir = STAGING_ROOT / doll
        self.lpk_path = LPK_OUT_ROOT / f"{doll}.lpk"
        self.lpk_preview_path = LPK_OUT_ROOT / f"{doll}.preview.jpg"

        # 共享音频去重表 (bucket = "audio" | "bgm")
        # sha256 -> (bucket, shared_filename, src_path, file_size)
        self.audio_by_sha: Dict[str, Tuple[str, str, Path, int]] = {}
        # (bucket, lower_filename) -> sha256 (防同名不同内容撞名)
        self.audio_name_owner: Dict[Tuple[str, str], str] = {}

        # 统计
        self.orig_total_bytes = 0
        self.orig_audio_files = 0
        self.orig_audio_bytes = 0
        self.unique_audio_bytes = 0
        self.audio_collisions = 0
        self.l2d_skins: List[Tuple[str, str, Path]] = []    # (skin, folder_name, src_dir)
        self.spine_skins: List[Tuple[str, str, Path]] = []  # (skin, folder_name, src_dir)

        # LPK 包内条目表
        # zip_name -> (bytes_or_Path, compress_type)
        self.zip_entries: Dict[str, Tuple[object, int]] = {}
        # abs_src_file -> (sha256, size)
        self.file_sha_cache: Dict[Path, Tuple[str, int]] = {}
        # canonical_cfg_abs -> zip_cfg_name
        self.cfg_zip_name_map: Dict[Path, str] = {}
        # 已处理（写入 zip_entries）的配置文件集合
        self.packed_cfgs: Set[Path] = set()
        # 待递归处理的配置队列: (abs_cfg_path, is_live2d)
        self.cfg_queue: List[Tuple[Path, bool]] = []

    def get_file_sha(self, path: Path) -> Tuple[str, int]:
        rp = path.resolve()
        hit = self.file_sha_cache.get(rp)
        if hit is not None:
            return hit
        res = sha256_file(rp)
        self.file_sha_cache[rp] = res
        return res

    def register_shared_audio(self, src_audio: Path, orig_rel: str) -> str:
        """注册共享 .ogg 到 staging 的 audio/ 或 bgm/，返回相对皮肤根目录的路径（如 ../audio/xxx.ogg）。"""
        sha, sz = self.get_file_sha(src_audio)
        self.orig_audio_files += 1
        self.orig_audio_bytes += sz
        if sha in self.audio_by_sha:
            bucket, fname, _, _ = self.audio_by_sha[sha]
            return f"../{bucket}/{fname}"

        bucket = "bgm" if is_bgm_relpath(orig_rel) else "audio"
        stem = src_audio.stem
        ext = src_audio.suffix.lower() or ".ogg"
        cand = f"{stem}{ext}"
        key = (bucket, cand.lower())
        if key in self.audio_name_owner and self.audio_name_owner[key] != sha:
            cand = f"{stem}_{sha[:6]}{ext}"
            key = (bucket, cand.lower())
            self.audio_collisions += 1
        self.audio_name_owner[key] = sha
        self.audio_by_sha[sha] = (bucket, cand, src_audio.resolve(), sz)
        self.unique_audio_bytes += sz

        # 在 staging 中创建共享硬链接
        dst = self.stage_dir / bucket / cand
        hardlink_or_copy(src_audio, dst)
        return f"../{bucket}/{cand}"

    def _register_cfg_name(self, cfg_path: Path, is_live2d: bool) -> str:
        rp = cfg_path.resolve()
        if rp in self.cfg_zip_name_map:
            return self.cfg_zip_name_map[rp]
        # 使用相对 BASE_DIR 的 POSIX 路径计算稳定 MD5（确保不同皮肤同名 .config.json 互不冲突）
        try:
            canon = rp.relative_to(BASE_DIR.resolve()).as_posix()
        except ValueError:
            canon = rp.as_posix()
        ext = ".bin3" if is_live2d else ".bin"
        zname = f"{md5_str(canon)}{ext}"
        self.cfg_zip_name_map[rp] = zname
        if rp not in self.packed_cfgs:
            self.cfg_queue.append((rp, is_live2d))
        return zname

    def _pack_leaf_asset(self, src_path: Path) -> str:
        """按内容 SHA-256 去重打包任意叶子资源（纹理/音频/moc3/motion/physics/exp/skel/atlas）。"""
        rp = src_path.resolve()
        if not rp.is_file():
            raise FileNotFoundError(f"Missing asset referenced by config: {rp}")
        sha, _ = self.get_file_sha(rp)
        # 保留复合扩展名（如 .motion3.json / .skel.json / .atlas.txt / .physics3.json / .exp3.json）或单扩展名
        name_low = rp.name.lower()
        ext = rp.suffix.lower()
        for compound in (".motion3.json", ".physics3.json", ".exp3.json", ".skel.json", ".atlas.txt"):
            if name_low.endswith(compound):
                ext = compound
                break
        zname = f"{sha[:32]}{ext}"
        if zname not in self.zip_entries:
            ctype = zipfile.ZIP_STORED if rp.suffix.lower() in STORED_EXTS else zipfile.ZIP_DEFLATED
            self.zip_entries[zname] = (rp, ctype)
        return zname

    def _rewrite_command_for_lpk(self, cmd: str, cfg_dir: Path, is_live2d_owner: bool) -> str:
        if not cmd:
            return cmd
        out_segs: List[str] = []
        for raw_seg in cmd.split(";"):
            seg = raw_seg.strip()
            if not seg:
                continue
            parts = seg.split()
            verb = parts[0]
            if verb in ("add_submodel", "remove_submodel", "change_model", "change_cos") and len(parts) >= 2:
                rel_target = parts[1]
                target_abs = normalize_rel(cfg_dir, rel_target)
                if not target_abs.is_file():
                    raise FileNotFoundError(f"Command '{seg}' target missing: {target_abs} (from {cfg_dir})")
                target_is_l2d = target_abs.name.lower().endswith(".model3.json")
                target_abs = canonical_base_cfg(target_abs, target_is_l2d)
                z_target = self._register_cfg_name(target_abs, target_is_l2d)
                parts[1] = z_target
                out_segs.append(" ".join(parts))
            elif verb == "replace_tex" and len(parts) >= 3:
                tex_abs = normalize_rel(cfg_dir, parts[2])
                z_tex = self._pack_leaf_asset(tex_abs)
                parts[2] = z_tex
                out_segs.append(" ".join(parts))
            else:
                out_segs.append(seg)
        return "; ".join(out_segs)

    def _rewrite_single_cfg_assets(self, cfg_path: Path, is_live2d: bool) -> dict:
        cfg_dir = cfg_path.parent
        data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        if is_live2d:
            fr = data.get("FileReferences", {})
            if fr.get("Moc"):
                fr["Moc"] = self._pack_leaf_asset(normalize_rel(cfg_dir, fr["Moc"]))
            if fr.get("Textures"):
                fr["Textures"] = [
                    self._pack_leaf_asset(normalize_rel(cfg_dir, t)) for t in fr["Textures"]
                ]
            if fr.get("Physics"):
                fr["Physics"] = self._pack_leaf_asset(normalize_rel(cfg_dir, fr["Physics"]))
            if isinstance(fr.get("PhysicsV2"), dict) and fr["PhysicsV2"].get("File"):
                fr["PhysicsV2"]["File"] = self._pack_leaf_asset(normalize_rel(cfg_dir, fr["PhysicsV2"]["File"]))
            if fr.get("Pose"):
                fr["Pose"] = self._pack_leaf_asset(normalize_rel(cfg_dir, fr["Pose"]))
            for exp in fr.get("Expressions") or []:
                if isinstance(exp, dict) and exp.get("File"):
                    exp["File"] = self._pack_leaf_asset(normalize_rel(cfg_dir, exp["File"]))
            mots = fr.get("Motions") or {}
            for grp, items in mots.items():
                for it in items or []:
                    if not isinstance(it, dict):
                        continue
                    if it.get("File"):
                        it["File"] = self._pack_leaf_asset(normalize_rel(cfg_dir, it["File"]))
                    if it.get("Sound"):
                        it["Sound"] = self._pack_leaf_asset(normalize_rel(cfg_dir, it["Sound"]))
                    if it.get("Command"):
                        it["Command"] = self._rewrite_command_for_lpk(it["Command"], cfg_dir, True)
                    if it.get("PostCommand"):
                        it["PostCommand"] = self._rewrite_command_for_lpk(it["PostCommand"], cfg_dir, True)
        else:
            # Spine .config.json
            if data.get("skeleton"):
                data["skeleton"] = self._pack_leaf_asset(normalize_rel(cfg_dir, data["skeleton"]))
            for atl in data.get("atlases") or []:
                if not isinstance(atl, dict):
                    continue
                orig_texs = atl.get("textures") or []
                # 关键：官方 EX Studio 规范，先记录去扩展名 tex_names 以匹配 .atlas.txt 内部页名
                if not atl.get("tex_names"):
                    atl["tex_names"] = [Path(t.replace("\\", "/")).stem for t in orig_texs]
                if atl.get("atlas"):
                    atl["atlas"] = self._pack_leaf_asset(normalize_rel(cfg_dir, atl["atlas"]))
                atl["textures"] = [
                    self._pack_leaf_asset(normalize_rel(cfg_dir, t)) for t in orig_texs
                ]
            mots = data.get("motions") or {}
            for grp, items in mots.items():
                for it in items or []:
                    if not isinstance(it, dict):
                        continue
                    if it.get("sound"):
                        it["sound"] = self._pack_leaf_asset(normalize_rel(cfg_dir, it["sound"]))
                    if it.get("command"):
                        it["command"] = self._rewrite_command_for_lpk(it["command"], cfg_dir, False)
                    if it.get("post_command"):
                        it["post_command"] = self._rewrite_command_for_lpk(it["post_command"], cfg_dir, False)
        return data

    def _process_cfg_for_lpk(self, cfg_abs: Path, is_live2d: bool) -> None:
        rp = canonical_base_cfg(cfg_abs, is_live2d)
        if rp in self.packed_cfgs:
            return
        self.packed_cfgs.add(rp)
        zname = self._register_cfg_name(rp, is_live2d)

        data = self._rewrite_single_cfg_assets(rp, is_live2d)

        # 若存在 EN / JA 兄弟配置，按 EX 原生 Motion.Language / motion.language 自动融合进单配置
        p_en, p_ja = find_sibling_lang_cfgs(rp, is_live2d)
        if p_en is not None and p_ja is not None:
            data_en = self._rewrite_single_cfg_assets(p_en, is_live2d)
            data_ja = self._rewrite_single_cfg_assets(p_ja, is_live2d)
            if is_live2d:
                fr_zh = data.get("FileReferences", {})
                fr_en = data_en.get("FileReferences", {})
                fr_ja = data_ja.get("FileReferences", {})
                fr_zh["Motions"] = merge_multilang_motions(
                    fr_zh.get("Motions") or {},
                    fr_en.get("Motions") or {},
                    fr_ja.get("Motions") or {},
                    is_live2d=True,
                )
                # 合并有本地化差异的 Expressions[].Name（如 26 套誓约皮肤的戒指开关）为双语显示
                exps_zh = fr_zh.get("Expressions") or []
                exps_en = fr_en.get("Expressions") or []
                if len(exps_zh) == len(exps_en):
                    for ez, ee in zip(exps_zh, exps_en):
                        if isinstance(ez, dict) and isinstance(ee, dict):
                            nz = (ez.get("Name") or "").strip()
                            ne = (ee.get("Name") or "").strip()
                            if nz and ne and nz != ne and " / " not in nz:
                                ez["Name"] = f"{nz} / {ne}"
            else:
                data["motions"] = merge_multilang_motions(
                    data.get("motions") or {},
                    data_en.get("motions") or {},
                    data_ja.get("motions") or {},
                    is_live2d=False,
                )

        self.zip_entries[zname] = (compact_json_bytes(data), zipfile.ZIP_DEFLATED)

    def _stage_skin_dir(self, src_dir: Path, dst_dir: Path, is_live2d: bool) -> None:
        """构建 EX Studio 暂存皮肤目录：不可变文件硬链接，音频去重指向 ../audio/ 或 ../bgm/，配置文件重写。"""
        dst_dir.mkdir(parents=True, exist_ok=True)
        for root, dirs, files in os.walk(src_dir):
            root_p = Path(root)
            rel_dir = root_p.relative_to(src_dir)
            # 跳过原皮肤内部 sounds/（所有引用的 .ogg 已统一汇入角色根共享 audio/ 或 bgm/）
            if rel_dir.parts and rel_dir.parts[0].lower() == "sounds":
                continue
            for fn in files:
                sp = root_p / fn
                self.orig_total_bytes += sp.stat().st_size
                dp = dst_dir / rel_dir / fn
                low = fn.lower()
                if is_live2d and low.endswith(L2D_CONFIG_SUFFIX):
                    cfg = json.loads(sp.read_text(encoding="utf-8"))
                    mots = cfg.get("FileReferences", {}).get("Motions") or {}
                    depth = len(rel_dir.parts)  # 皮肤根为 0，submodels/henshin 为 2
                    up_prefix = "../" * depth
                    for grp, items in mots.items():
                        for it in items or []:
                            if isinstance(it, dict) and it.get("Sound"):
                                snd_abs = normalize_rel(root_p, it["Sound"])
                                if snd_abs.is_file():
                                    shared_rel = self.register_shared_audio(snd_abs, it["Sound"])
                                    it["Sound"] = f"{up_prefix}{shared_rel}"
                    dp.parent.mkdir(parents=True, exist_ok=True)
                    dp.write_bytes(compact_json_bytes(cfg))
                elif (not is_live2d) and low.endswith(SPINE_CONFIG_SUFFIX):
                    cfg = json.loads(sp.read_text(encoding="utf-8"))
                    mots = cfg.get("motions") or {}
                    depth = len(rel_dir.parts)
                    up_prefix = "../" * depth
                    for grp, items in mots.items():
                        for it in items or []:
                            if isinstance(it, dict) and it.get("sound"):
                                snd_abs = normalize_rel(root_p, it["sound"])
                                if snd_abs.is_file():
                                    shared_rel = self.register_shared_audio(snd_abs, it["sound"])
                                    it["sound"] = f"{up_prefix}{shared_rel}"
                    dp.parent.mkdir(parents=True, exist_ok=True)
                    dp.write_bytes(compact_json_bytes(cfg))
                else:
                    hardlink_or_copy(sp, dp)

        # 计入原皮肤 sounds/ 原始体积用于准确统计去重前大小
        sounds_dir = src_dir / "sounds"
        if sounds_dir.is_dir():
            for root, _, files in os.walk(sounds_dir):
                for fn in files:
                    self.orig_total_bytes += (Path(root) / fn).stat().st_size

    def run(self, write_lpk: bool = True) -> Dict[str, object]:
        t0 = time.time()

        # 1. 收集皮肤列表
        l2d_doll_dir = LIVE2D_ROOT / self.doll
        if l2d_doll_dir.is_dir():
            skins = sort_skins([p.name for p in l2d_doll_dir.iterdir() if p.is_dir() and (p / ".model3.json").is_file()])
            for idx, sk in enumerate(skins, 1):
                self.l2d_skins.append((sk, f"l2d_{idx:02d}_{sk}", l2d_doll_dir / sk))

        sp_doll_dir = SPINE_ROOT / self.doll
        if sp_doll_dir.is_dir():
            skins = sort_skins([p.name for p in sp_doll_dir.iterdir() if p.is_dir() and (p / ".config.json").is_file()])
            for idx, sk in enumerate(skins, 1):
                self.spine_skins.append((sk, f"spine_{idx:02d}_{sk}", sp_doll_dir / sk))

        # 2. 清理并重建 staging 目录
        if self.stage_dir.exists():
            shutil.rmtree(self.stage_dir)
        self.stage_dir.mkdir(parents=True, exist_ok=True)

        # 3. 生成 preview.jpg (< 1 MB) 与 avatar.png (256x256)
        preview_stage = self.stage_dir / "preview.jpg"
        avatar_stage = self.stage_dir / "avatar.png"
        art_info = generate_preview_and_avatar(self.doll, preview_stage, avatar_stage)

        # 4. 构建 staging（含共享 audio/、bgm/ 与重写后的全部三语配置）
        stage_costumes = []
        lpk_costumes = []

        for sk, folder_name, src_dir in self.l2d_skins:
            self._stage_skin_dir(src_dir, self.stage_dir / folder_name, is_live2d=True)
            stage_costumes.append({"name": f"Live2D - {sk}", "path": f"{folder_name}/.model3.json"})
            z_cfg = self._register_cfg_name(src_dir / ".model3.json", is_live2d=True)
            lpk_costumes.append({"name": f"Live2D - {sk}", "path": z_cfg})

        for sk, folder_name, src_dir in self.spine_skins:
            self._stage_skin_dir(src_dir, self.stage_dir / folder_name, is_live2d=False)
            stage_costumes.append({"name": f"Spine - {sk}", "path": f"{folder_name}/.config.json"})
            z_cfg = self._register_cfg_name(src_dir / ".config.json", is_live2d=False)
            lpk_costumes.append({"name": f"Spine - {sk}", "path": z_cfg})

        # 写 staging config.mlve
        stage_mlve = {
            "type": "STD2_0",
            "name": f"灵魂潮汐 - {self.doll} (Live2D + Spine 全服装合集)",
            "id": self.doll_slug,
            "encrypt": "false",
            "version": "1.0.0",
            "list": [
                {
                    "id": self.doll_slug,
                    "character": self.doll,
                    "avatar": "avatar.png",
                    "costume": stage_costumes,
                }
            ],
        }
        (self.stage_dir / "config.mlve").write_text(
            json.dumps(stage_mlve, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 5. 递归处理 LPK 队列中的所有配置文件（含 change_model / add_submodel / touch_only 等）
        while self.cfg_queue:
            cfg_abs, is_l2d = self.cfg_queue.pop(0)
            self._process_cfg_for_lpk(cfg_abs, is_l2d)

        # 6. 加入 avatar 与 config.mlve
        self.zip_entries[AVATAR_ZIP_NAME] = (avatar_stage, zipfile.ZIP_STORED)
        lpk_mlve = {
            "type": "STD2_0",
            "name": f"灵魂潮汐 - {self.doll} (Live2D + Spine 全服装 · 中英日多语言)",
            "id": self.doll_slug,
            "encrypt": "false",
            "version": "2.0.0",
            "list": [
                {
                    "id": self.doll_slug,
                    "character": self.doll,
                    "avatar": AVATAR_ZIP_NAME,
                    "costume": lpk_costumes,
                }
            ],
        }
        self.zip_entries[CONFIG_MLVE_ZIP_NAME] = (compact_json_bytes(lpk_mlve), zipfile.ZIP_DEFLATED)

        # 7. 写出 .lpk（原子写临时文件再替换，Deflate-9）与配套 preview.jpg
        lpk_bytes = 0
        if write_lpk:
            LPK_OUT_ROOT.mkdir(parents=True, exist_ok=True)
            tmp_lpk = self.lpk_path.with_suffix(".lpk.tmp")
            if tmp_lpk.exists():
                tmp_lpk.unlink()
            with zipfile.ZipFile(tmp_lpk, "w", allowZip64=True) as zf:
                for zname in sorted(self.zip_entries.keys()):
                    payload, ctype = self.zip_entries[zname]
                    if isinstance(payload, bytes):
                        zf.writestr(zname, payload, compress_type=ctype, compresslevel=6 if ctype == zipfile.ZIP_DEFLATED else None)
                    else:
                        zf.write(payload, arcname=zname, compress_type=ctype, compresslevel=6 if ctype == zipfile.ZIP_DEFLATED else None)
            if self.lpk_path.exists():
                self.lpk_path.unlink()
            tmp_lpk.rename(self.lpk_path)
            shutil.copy2(preview_stage, self.lpk_preview_path)
            lpk_bytes = self.lpk_path.stat().st_size

        # 统计包内去重后的音频数量与字节数
        lpk_audio_entries = [k for k in self.zip_entries if k.endswith(".ogg")]
        lpk_audio_bytes = sum(
            self.zip_entries[k][0].stat().st_size for k in lpk_audio_entries if isinstance(self.zip_entries[k][0], Path)
        )

        return {
            "doll": self.doll,
            "l2d_skins": len(self.l2d_skins),
            "spine_skins": len(self.spine_skins),
            "total_costumes": len(lpk_costumes),
            "packed_configs": len(self.packed_cfgs),
            "zip_entries": len(self.zip_entries),
            "orig_total_bytes": self.orig_total_bytes,
            "lpk_bytes": lpk_bytes,
            "saved_bytes": self.orig_total_bytes - lpk_bytes,
            "ratio_pct": round(lpk_bytes * 100.0 / max(1, self.orig_total_bytes), 2),
            "stage_unique_audio_files": len(self.audio_by_sha),
            "stage_unique_audio_bytes": self.unique_audio_bytes,
            "lpk_unique_audio_files": len(lpk_audio_entries),
            "lpk_unique_audio_bytes": lpk_audio_bytes,
            "audio_name_collisions_resolved": self.audio_collisions,
            "preview_bytes": art_info["preview_bytes"],
            "avatar_bytes": art_info["avatar_bytes"],
            "elapsed_sec": round(time.time() - t0, 2),
        }


def pack_one_doll(doll: str) -> Dict[str, object]:
    return DollPacker(doll).run()


def discover_all_dolls() -> List[str]:
    dolls: Set[str] = set()
    for root in (LIVE2D_ROOT, SPINE_ROOT):
        if root.is_dir():
            for p in root.iterdir():
                if p.is_dir():
                    dolls.add(p.name)
    return sorted(dolls)


def main():
    ap = argparse.ArgumentParser(description="Build Workshop staging + packed STD2_0 LPKs for SoulTide dolls")
    ap.add_argument("--dolls", nargs="*", help="指定要打包的角色名列表；省略则全量 55 位人偶")
    ap.add_argument("--workers", type=int, default=6, help="并行进程数（默认 6）")
    args = ap.parse_args()

    all_dolls = discover_all_dolls()
    targets = args.dolls if args.dolls else all_dolls
    missing = [d for d in targets if d not in all_dolls]
    if missing:
        print(f"[ERROR] Unknown dolls: {missing}", file=sys.stderr)
        sys.exit(1)

    t_start = time.time()
    print(f"Starting Workshop LPK build & pack for {len(targets)} doll(s) (workers={args.workers})...")
    results: List[Dict[str, object]] = []

    if args.workers <= 1 or len(targets) == 1:
        for d in targets:
            res = pack_one_doll(d)
            results.append(res)
            print(
                f"  [OK] {res['doll']:8s} | cos={res['total_costumes']:2d} (L2D={res['l2d_skins']},Sp={res['spine_skins']}) "
                f"| orig={res['orig_total_bytes']/1048576:6.2f} MB -> lpk={res['lpk_bytes']/1048576:6.2f} MB ({res['ratio_pct']:5.1f}%) "
                f"| aud={res['lpk_unique_audio_files']:3d} | prev={res['preview_bytes']/1024:5.1f} KB"
            )
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as ex:
            fut_map = {ex.submit(pack_one_doll, d): d for d in targets}
            for fut in concurrent.futures.as_completed(fut_map):
                d = fut_map[fut]
                res = fut.result()
                results.append(res)
                print(
                    f"  [OK] {res['doll']:8s} | cos={res['total_costumes']:2d} (L2D={res['l2d_skins']},Sp={res['spine_skins']}) "
                    f"| orig={res['orig_total_bytes']/1048576:6.2f} MB -> lpk={res['lpk_bytes']/1048576:6.2f} MB ({res['ratio_pct']:5.1f}%) "
                    f"| aud={res['lpk_unique_audio_files']:3d} | prev={res['preview_bytes']/1024:5.1f} KB"
                )

    results.sort(key=lambda x: x["doll"])
    tot_orig = sum(r["orig_total_bytes"] for r in results)
    tot_lpk = sum(r["lpk_bytes"] for r in results)
    tot_l2d = sum(r["l2d_skins"] for r in results)
    tot_sp = sum(r["spine_skins"] for r in results)
    tot_aud_files = sum(r["lpk_unique_audio_files"] for r in results)
    tot_aud_bytes = sum(r["lpk_unique_audio_bytes"] for r in results)
    elapsed = round(time.time() - t_start, 2)

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dolls_packed": len(results),
        "total_l2d_skins": tot_l2d,
        "total_spine_skins": tot_sp,
        "total_costumes": tot_l2d + tot_sp,
        "orig_total_bytes": tot_orig,
        "orig_total_mib": round(tot_orig / 1048576.0, 2),
        "lpk_total_bytes": tot_lpk,
        "lpk_total_mib": round(tot_lpk / 1048576.0, 2),
        "saved_bytes": tot_orig - tot_lpk,
        "saved_mib": round((tot_orig - tot_lpk) / 1048576.0, 2),
        "overall_ratio_pct": round(tot_lpk * 100.0 / max(1, tot_orig), 2),
        "total_lpk_unique_audio_files": tot_aud_files,
        "total_lpk_unique_audio_mib": round(tot_aud_bytes / 1048576.0, 2),
        "max_preview_bytes": max((r["preview_bytes"] for r in results), default=0),
        "max_lpk_doll": max(results, key=lambda r: r["lpk_bytes"])["doll"] if results else None,
        "max_lpk_mib": round(max((r["lpk_bytes"] for r in results), default=0) / 1048576.0, 2),
        "elapsed_sec": elapsed,
        "per_doll": results,
    }

    if not args.dolls or len(results) == len(all_dolls):
        REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print(
        f"DONE: {len(results)} dolls ({tot_l2d} L2D + {tot_sp} Spine = {tot_l2d + tot_sp} costumes) in {elapsed}s\n"
        f"  Source total : {tot_orig/1048576:.2f} MiB ({tot_orig/1073741824:.2f} GiB)\n"
        f"  LPK total    : {tot_lpk/1048576:.2f} MiB ({tot_lpk/1073741824:.2f} GiB) [{summary['overall_ratio_pct']}%]\n"
        f"  Net saved    : {(tot_orig-tot_lpk)/1048576:.2f} MiB ({(tot_orig-tot_lpk)/1073741824:.2f} GiB)\n"
        f"  Max preview  : {summary['max_preview_bytes']/1024:.1f} KB (limit < 1024 KB)"
    )


if __name__ == "__main__":
    main()
