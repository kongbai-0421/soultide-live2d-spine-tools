#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
为全库 Live2D 模型（含主形态与变身主形态，中/英/日三语）批量添加「全量待机动作切换」菜单
====================================================================================
原理（Live2DViewerEX 字节码实锤）：
  - 利用 EX 原生持久化变量系统 `VarFloats`（存储在 `CharData.varFloats["idle_mode"]`）：
    - 默认未初始化时自动返回 `0`（无缝保持 `standby1` 为默认待机，零破坏既有存档）；
    - `Idle` 组内为每个候选待机/情绪循环动作配置条件 `{"Name":"idle_mode","Type":1,"Code":"equal <idx>"}`，
      并为「随机轮播（全部待机）」配置 `equal 99`；
    - 菜单切换节点 `IdleSet_<idx>` 配置 `{"Name":"idle_mode","Type":2,"Code":"assign <idx>"}`，
      且 `File` 直接指向目标待机 `.motion3.json`（`FadeIn: 500, FadeOut: 0`），点击立即平滑切换、
      写盘持久化（重启 EX 永久记住），播完后自动在 `Idle` 组无缝循环（`FadeIn: 0`）。
  - 完整保留 `Idle[0]` 与 `语音菜单[0]` 上已有的 `Command` / `PostCommand`（如 3 位方案 A 变身人偶的
    `parts unlock; start_mtn ... Hide` 复位指令）。
  - 幂等脚本：重复运行安全，不叠加重复选项或重复动作组。

用法：
  python add_l2d_idle_switch.py
  python add_l2d_idle_switch.py --only 和铃/原皮,梦咲音月/原皮,伊汐尔/原皮
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LIVE2D_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\live2d")
REPORT_PATH = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\工具脚本\l2d_idle_switch_report.json")

VAR_NAME = "idle_mode"
RANDOM_CODE = 99
PAGE_SIZE = 6

# 主形态与变身主形态三语配置组
CONFIG_TRIPLETS: List[Tuple[str, str, str, str]] = [
    ("main", ".model3.json", "model_en.model3.json", "model_ja.model3.json"),
    ("henshin", "model_henshin.model3.json", "model_henshin_en.model3.json", "model_henshin_ja.model3.json"),
    ("red", "model_red.model3.json", "model_red_en.model3.json", "model_red_ja.model3.json"),
]

# 情绪循环基础名 -> (排序权重, 中文, 英文, 日文)
EMOTION_LABELS: Dict[str, Tuple[int, str, str, str]] = {
    "joyful":    (10, "开心循环", "Joyful Loop", "喜びループ"),
    "shy":       (20, "害羞循环", "Shy Loop", "照れループ"),
    "serious":   (30, "严肃循环", "Serious Loop", "真剣ループ"),
    "vexedly":   (40, "苦恼循环", "Vexed Loop", "困りループ"),
    "wordless":  (50, "无语循环", "Speechless Loop", "無言ループ"),
    "sad":       (60, "悲伤循环", "Sad Loop", "悲しみループ"),
    "angry":     (70, "生气循环", "Angry Loop", "怒りループ"),
    "terrified": (80, "惊恐循环", "Terrified Loop", "驚きループ"),
    "mouseidle":   (90, "鼠鼠待机循环", "Mouse Idle Loop", "ネズミ待機ループ"),
    "mousejoyful": (91, "鼠鼠开心循环", "Mouse Joyful Loop", "ネズミ喜びループ"),
    "mouseshy":    (92, "鼠鼠害羞循环", "Mouse Shy Loop", "ネズミ照れループ"),
    "mousesad":    (93, "鼠鼠悲伤循环", "Mouse Sad Loop", "ネズミ悲しみループ"),
    "mouseangry":  (94, "鼠鼠生气循环", "Mouse Angry Loop", "ネズミ怒りループ"),
}

UI_STRINGS = {
    "zh": {
        "menu_entry": "★ 切换待机动作 ({n})",
        "menu_header": "【切换默认待机动作】({p}/{total}) 点击立即切换并永久记忆：",
        "menu_header_single": "【切换默认待机动作】点击立即切换并永久记忆：",
        "next_page": "下一页 ({p}/{total}) ▶",
        "prev_page": "◀ 上一页 ({p}/{total})",
        "back_main": "« 返回主语音菜单",
        "default_tag": " (默认)",
        "random_label": "🔀 随机轮播 (全部待机)",
        "toast": "已切换待机动作：{label}（重启EX后仍保留）",
    },
    "en": {
        "menu_entry": "★ Switch Idle Motion ({n})",
        "menu_header": "[Switch Default Idle Motion] ({p}/{total}) Tap to switch & save:",
        "menu_header_single": "[Switch Default Idle Motion] Tap to switch & save:",
        "next_page": "Next Page ({p}/{total}) ▶",
        "prev_page": "◀ Prev Page ({p}/{total})",
        "back_main": "« Back to Main Menu",
        "default_tag": " (Default)",
        "random_label": "🔀 Random Standby Rotation",
        "toast": "Idle motion switched to: {label} (Saved across restarts)",
    },
    "ja": {
        "menu_entry": "★ 待機モーション切替 ({n})",
        "menu_header": "【デフォルト待機モーション切替】({p}/{total}) 選択すると即座に切替・保存：",
        "menu_header_single": "【デフォルト待機モーション切替】選択すると即座に切替・保存：",
        "next_page": "次のページ ({p}/{total}) ▶",
        "prev_page": "◀ 前のページ ({p}/{total})",
        "back_main": "« メインメニューに戻る",
        "default_tag": "（デフォルト）",
        "random_label": "🔀 ランダム待機ローテーション",
        "toast": "待機モーションを変更しました：{label}（再起動後も保持）",
    },
}


def write_json_clean(path: Path, obj: Any) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def extract_short_name(filename: str) -> str:
    stem = filename
    if stem.lower().endswith(".motion3.json"):
        stem = stem[:-13]
    if "@live2d_" in stem:
        stem = stem.split("@live2d_", 1)[1]
    return stem


def classify_and_label(short_name: str, is_default: bool) -> Tuple[Tuple[int, int, str], bool, Dict[str, str]]:
    """返回 (sort_key, is_standby, {'zh': ..., 'en': ..., 'ja': ...})。"""
    # 清理原版游戏动作文件名里的异常空格（如 'shy _loop', 'shy_loop_ 2', 'vexedly_ loop', 尾空格）
    norm = re.sub(r"\s+", "", short_name.strip().lower())

    is_standby = "standby" in norm
    zh = en = ja = short_name.strip()

    if is_standby:
        if norm.startswith("standby_sad"):
            sub_rank = 50
            zh, en, ja = "失落待机", "Sad Standby", "しょんぼり待機"
        else:
            # standby1, standby1_2, standby1_white, standby2, standby3
            m = re.match(r"standby(\d+)(?:_(.+))?$", norm)
            if m:
                num = int(m.group(1))
                suf = m.group(2) or ""
                sub_rank = num * 10
                extra_zh = extra_en = extra_ja = ""
                if suf == "white":
                    sub_rank += 1
                    extra_zh, extra_en, extra_ja = " (白)", " (White)", "（白）"
                elif suf:
                    sub_rank += 2
                    extra_zh = f"-{suf}"
                    extra_en = f"-{suf}"
                    extra_ja = f"-{suf}"
                zh = f"待机 {num}{extra_zh}"
                en = f"Standby {num}{extra_en}"
                ja = f"待機 {num}{extra_ja}"
            else:
                sub_rank = 60
                zh = f"待机 ({short_name.strip()})"
                en = f"Standby ({short_name.strip()})"
                ja = f"待機 ({short_name.strip()})"
        sort_key = (0 if is_default else 1, sub_rank, norm)
    else:
        # 情绪循环动作: <emo>[digit][_digit]_loop[_2][_white]
        m = re.match(r"([a-z]+?)(\d*)_?(\d*)_?loop(?:_?(\d+))?(?:_(white))?$", norm)
        if m and m.group(1) in EMOTION_LABELS:
            emo = m.group(1)
            n1 = m.group(2) or ""
            n2 = m.group(3) or ""
            n3 = m.group(4) or ""
            is_white = bool(m.group(5))
            base_rank, l_zh, l_en, l_ja = EMOTION_LABELS[emo]
            var_parts = [x for x in (n1, n2, n3) if x]
            var_tag = (" " + "-".join(var_parts)) if var_parts else ""
            w_zh = " (白)" if is_white else ""
            w_en = " (White)" if is_white else ""
            w_ja = "（白）" if is_white else ""
            sub_num = int(var_parts[0]) if var_parts and var_parts[0].isdigit() else 0
            zh = f"{l_zh}{var_tag}{w_zh}"
            en = f"{l_en}{var_tag}{w_en}"
            ja = f"{l_ja}{var_tag}{w_ja}"
            sort_key = (2, base_rank * 10 + sub_num + (5 if is_white else 0), norm)
        else:
            zh = f"循环动作 ({short_name.strip()})"
            en = f"Loop ({short_name.strip()})"
            ja = f"ループ ({short_name.strip()})"
            sort_key = (3, 999, norm)

    if is_default:
        zh += UI_STRINGS["zh"]["default_tag"]
        en += UI_STRINGS["en"]["default_tag"]
        ja += UI_STRINGS["ja"]["default_tag"]

    return sort_key, is_standby, {"zh": zh, "en": en, "ja": ja}


def discover_idle_candidates(pkg_dir: Path, base_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    """发现该配置对应的全部可切换待机/循环动作，并保留原 Idle[0] 的 Command/PostCommand。"""
    mots = (base_data.get("FileReferences") or {}).get("Motions") or {}
    idle_list = mots.get("Idle") or []
    if not idle_list:
        return [], None, None

    # 找到默认项（兼容已运行过本脚本：优先找 idle_mode == 0 的条目，否则取 Idle[0]）
    default_entry = idle_list[0]
    for it in idle_list:
        vfs = it.get("VarFloats") or []
        if any(vf.get("Name") == VAR_NAME and vf.get("Code") == "equal 0" for vf in vfs):
            default_entry = it
            break

    default_file = default_entry.get("File", "").replace("\\", "/")
    idle_cmd = default_entry.get("Command")
    idle_post_cmd = default_entry.get("PostCommand")
    if not default_file:
        return [], idle_cmd, idle_post_cmd

    default_abs = (pkg_dir / default_file).resolve()
    mot_dir = default_abs.parent
    rel_dir = Path(default_file).parent.as_posix()
    if not mot_dir.is_dir():
        return [], idle_cmd, idle_post_cmd

    raw_items = []
    seen_files = set()
    for mf in sorted(mot_dir.glob("*.motion3.json")):
        if mf.name.lower() == "menu_silent.motion3.json":
            continue
        short = extract_short_name(mf.name)
        low = short.lower()
        is_def = (mf.resolve() == default_abs)
        if not (is_def or "standby" in low or "loop" in low):
            continue
        # 验证动作文件为合法 JSON
        try:
            json.loads(mf.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        rel_path = f"{rel_dir}/{mf.name}" if rel_dir and rel_dir != "." else mf.name
        if rel_path in seen_files:
            continue
        seen_files.add(rel_path)
        sort_key, is_sb, labels = classify_and_label(short, is_default=is_def)
        raw_items.append({
            "sort_key": sort_key,
            "is_default": is_def,
            "is_standby": is_sb,
            "short": short.strip(),
            "rel_file": rel_path,
            "labels": labels,
        })

    # 若发现不到至少 2 个待机/循环动作（例如纯剧情模型），跳过
    if len(raw_items) < 2:
        return [], idle_cmd, idle_post_cmd

    raw_items.sort(key=lambda x: x["sort_key"])

    # 确保 default 排在第 0 位（idle_mode == 0）
    def_idx = next((i for i, x in enumerate(raw_items) if x["is_default"]), 0)
    if def_idx != 0:
        raw_items.insert(0, raw_items.pop(def_idx))

    for idx, it in enumerate(raw_items):
        it["code_val"] = idx
        it["motion_name"] = f"idle_{idx:02d}_{re.sub(r'[^a-zA-Z0-9_]+', '_', it['short']).strip('_') or 'default'}"

    return raw_items, idle_cmd, idle_post_cmd


def patch_one_config(
    cfg_path: Path,
    lang: str,
    candidates: List[Dict[str, Any]],
    idle_cmd: Optional[str],
    idle_post_cmd: Optional[str],
) -> Dict[str, Any]:
    data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    mots: Dict[str, List[Dict[str, Any]]] = data["FileReferences"]["Motions"]
    ui = UI_STRINGS[lang]

    # 1. 清理历史幂等写入的 Menu_Cat_Idle* 与 IdleSet_*
    for k in list(mots.keys()):
        if k == "Menu_Cat_Idle" or k.startswith("Menu_Cat_Idle_p") or k.startswith("IdleSet_"):
            del mots[k]

    # 2. 构建新的 Idle 组（每个候选绑定 equal <idx>，再附带随机轮播 equal 99）
    standby_cands = [c for c in candidates if c["is_standby"]]
    random_pool = standby_cands if len(standby_cands) >= 2 else candidates
    has_random = len(random_pool) >= 2

    new_idle: List[Dict[str, Any]] = []
    for c in candidates:
        entry: Dict[str, Any] = {
            "Name": c["motion_name"],
            "File": c["rel_file"],
            "FadeIn": 0,
            "VarFloats": [{"Name": VAR_NAME, "Type": 1, "Code": f"equal {c['code_val']}"}],
        }
        if idle_cmd:
            entry["Command"] = idle_cmd
        if idle_post_cmd:
            entry["PostCommand"] = idle_post_cmd
        new_idle.append(entry)

    if has_random:
        for c in random_pool:
            entry = {
                "Name": f"rand_{c['motion_name']}",
                "File": c["rel_file"],
                "FadeIn": 500,
                "VarFloats": [{"Name": VAR_NAME, "Type": 1, "Code": f"equal {RANDOM_CODE}"}],
            }
            if idle_cmd:
                entry["Command"] = idle_cmd
            if idle_post_cmd:
                entry["PostCommand"] = idle_post_cmd
            new_idle.append(entry)

    mots["Idle"] = new_idle

    # 3. 如果配置包含 语音菜单，挂载二级切换菜单 Menu_Cat_Idle* 与动作设置节点 IdleSet_*
    vm_list = mots.get("语音菜单") or []
    if not vm_list:
        write_json_clean(cfg_path, data)
        return {"menu_added": False, "idle_entries": len(new_idle)}

    vm = vm_list[0]
    menu_file = vm.get("File", "motions/menu_silent.motion3.json")
    menu_cmd = vm.get("Command")
    menu_post_cmd = vm.get("PostCommand")

    # 构造菜单展示项列表：先放所有 standby* -> 随机轮播 -> 其余情绪 *_loop
    menu_items: List[Tuple[str, str, str, int]] = []  # (group_key, label, target_file, assign_val)
    standby_entries = [c for c in candidates if c["is_standby"]]
    loop_entries = [c for c in candidates if not c["is_standby"]]

    for c in standby_entries:
        menu_items.append((f"IdleSet_{c['code_val']}", c["labels"][lang], c["rel_file"], c["code_val"]))

    if has_random:
        # 点击随机轮播时先切到第 2 个待机（直观反馈已开始轮播），之后由 Idle 组自动随机交替
        preview_rand_file = random_pool[1]["rel_file"] if len(random_pool) >= 2 else random_pool[0]["rel_file"]
        menu_items.append(("IdleSet_Random", ui["random_label"], preview_rand_file, RANDOM_CODE))

    for c in loop_entries:
        menu_items.append((f"IdleSet_{c['code_val']}", c["labels"][lang], c["rel_file"], c["code_val"]))

    # 生成各个 IdleSet_* 执行节点
    for grp_key, label, target_file, assign_val in menu_items:
        setter: Dict[str, Any] = {
            "Name": grp_key.lower(),
            "File": target_file,
            "FadeIn": 500,
            "FadeOut": 0,
            "VarFloats": [{"Name": VAR_NAME, "Type": 2, "Code": f"assign {assign_val}"}],
            "Text": ui["toast"].format(label=label),
            "TextDuration": 2500,
        }
        if menu_cmd:
            setter["Command"] = menu_cmd
        if menu_post_cmd:
            setter["PostCommand"] = menu_post_cmd
        mots[grp_key] = [setter]

    # 生成分页菜单 Menu_Cat_Idle / Menu_Cat_Idle_p2 / ...
    pages = [menu_items[i : i + PAGE_SIZE] for i in range(0, len(menu_items), PAGE_SIZE)]
    total_pages = len(pages)
    for pidx, page in enumerate(pages, 1):
        grp_name = "Menu_Cat_Idle" if pidx == 1 else f"Menu_Cat_Idle_p{pidx}"
        choices: List[Dict[str, str]] = [
            {"Text": label, "NextMtn": grp_key} for grp_key, label, _, _ in page
        ]
        if pidx > 1:
            prev_grp = "Menu_Cat_Idle" if pidx == 2 else f"Menu_Cat_Idle_p{pidx - 1}"
            choices.append({"Text": ui["prev_page"].format(p=pidx - 1, total=total_pages), "NextMtn": prev_grp})
        if pidx < total_pages:
            choices.append({"Text": ui["next_page"].format(p=pidx + 1, total=total_pages), "NextMtn": f"Menu_Cat_Idle_p{pidx + 1}"})
        choices.append({"Text": ui["back_main"], "NextMtn": "语音菜单"})

        header_text = (
            ui["menu_header_single"]
            if total_pages == 1
            else ui["menu_header"].format(p=pidx, total=total_pages)
        )
        node: Dict[str, Any] = {
            "Name": grp_name,
            "File": menu_file,
            "FadeIn": 0,
            "FadeOut": 0,
            "Text": header_text,
            "TextDuration": 60000,
            "Choices": choices,
        }
        if menu_cmd:
            node["Command"] = menu_cmd
        if menu_post_cmd:
            node["PostCommand"] = menu_post_cmd
        mots[grp_name] = [node]

    # 幂等插入/更新主菜单 语音菜单 的入口按钮（插在 形态切换 / 誓约戒指切换 之前，或末尾）
    vm_choices: List[Dict[str, str]] = [
        ch for ch in (vm.get("Choices") or []) if ch.get("NextMtn") != "Menu_Cat_Idle"
    ]
    new_choice = {"Text": ui["menu_entry"].format(n=len(menu_items)), "NextMtn": "Menu_Cat_Idle"}
    insert_at = len(vm_choices)
    for idx, ch in enumerate(vm_choices):
        if ch.get("NextMtn") in ("Form_Switch_Main", "誓约戒指切换"):
            insert_at = idx
            break
    vm_choices.insert(insert_at, new_choice)
    vm["Choices"] = vm_choices

    write_json_clean(cfg_path, data)
    return {
        "menu_added": True,
        "idle_entries": len(new_idle),
        "menu_options": len(menu_items),
        "pages": total_pages,
        "standby_count": len(standby_entries),
        "loop_count": len(loop_entries),
        "has_random": has_random,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Add full Live2D Idle-Switch menu (VarFloats) across all 3 languages.")
    ap.add_argument("--only", help="逗号分隔的 <人偶>/<皮肤> 子串过滤（省略则全量 182 套 Live2D）")
    args = ap.parse_args()

    pkgs = sorted(p.parent for p in LIVE2D_ROOT.glob("*/*/.model3.json"))
    if args.only:
        wants = [x.strip().replace("\\", "/") for x in args.only.split(",") if x.strip()]
        pkgs = [p for p in pkgs if any(w in f"{p.parent.name}/{p.name}" for w in wants)]

    updated_triplets = 0
    updated_files = 0
    skipped: List[str] = []
    details: List[Dict[str, Any]] = []

    for pkg in pkgs:
        rel = f"{pkg.parent.name}/{pkg.name}"
        for kind, fn_zh, fn_en, fn_ja in CONFIG_TRIPLETS:
            p_zh = pkg / fn_zh
            if not p_zh.is_file():
                continue
            p_en = pkg / fn_en
            p_ja = pkg / fn_ja
            if not (p_en.is_file() and p_ja.is_file()):
                raise FileNotFoundError(f"Missing EN/JA sibling for {p_zh}")

            base_data = json.loads(p_zh.read_text(encoding="utf-8-sig"))
            candidates, idle_cmd, idle_post_cmd = discover_idle_candidates(pkg, base_data)
            if not candidates:
                skipped.append(f"{rel} ({kind})")
                continue

            info_zh = patch_one_config(p_zh, "zh", candidates, idle_cmd, idle_post_cmd)
            patch_one_config(p_en, "en", candidates, idle_cmd, idle_post_cmd)
            patch_one_config(p_ja, "ja", candidates, idle_cmd, idle_post_cmd)

            updated_triplets += 1
            updated_files += 3
            details.append({
                "package": rel,
                "form": kind,
                **info_zh,
            })

    report = {
        "packages_scanned": len(pkgs),
        "triplets_updated": updated_triplets,
        "files_written": updated_files,
        "skipped": skipped,
        "summary": {
            "min_options": min((d["menu_options"] for d in details), default=0),
            "max_options": max((d["menu_options"] for d in details), default=0),
            "total_idle_entries": sum(d["idle_entries"] for d in details),
        },
        "details": details,
    }
    if not args.only:
        write_json_clean(REPORT_PATH, report)

    print(
        f"DONE: scanned={len(pkgs)} pkgs | updated={updated_triplets} form-triplets ({updated_files} files) "
        f"| skipped={len(skipped)} ({skipped}) "
        f"| options/pkg={report['summary']['min_options']}..{report['summary']['max_options']}"
    )


if __name__ == "__main__":
    main()
