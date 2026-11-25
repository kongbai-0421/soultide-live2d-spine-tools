"""Full-Fleet Live2D (182 packages) & Spine (170 packages) Touch Trigger Calibrator & Fixer.

Live2D (182 packages):
1. Uses Live2DCubismCore.dll (`csmGetDrawableIds`, `csmGetDrawableVertexPositions`) to verify
   exact Drawable (ArtMesh) IDs — never substring matching (`b"DREFTouchBoxHip" in moc_bytes`)
   and never Cubism Part IDs (`"Body"`).
2. Fixes prefix-shadowed IDs (`DREFTouchBoxHip2` in 光明云/云照海光, `DREFTouchBoxHandL2` in 菲洛多希/闪耀星芒).
3. When `"Body"` / `"Body2"` is a Part ID (not in `csmGetDrawableIds`), merges `"Tap躯干"` entries into
   the 4 core touch groups (`Tap臀部` / `Tap胸` / `Tap手` / `Tap头`) and removes the unreachable `"Body"`
   HitArea across `.model3.json`, `model_en.model3.json`, and `model_ja.model3.json`.
4. Populates balanced touch groups for skins that previously had 0 HitAreas (`叶月雪/夏日盈雪`, `芙丽希娅/囚牢天使`,
   `莉莉艾洛/花间魑祟`, `阿卡赛特/黑鲨信号`, `星见亚砂/夏樱_S2..S5`, `星见亚砂/经典_活动`, `露比·罗斯/原皮_艾妮斯剧情`,
   `黛安娜/原皮`, `星见亚砂/盛夏游乐场`, `梦咲音月/此情无垢`) and maps `ArtMesh*` drawables for `伊汐尔/原皮_变身`.

Spine (170 packages):
1. Evaluates real idle-pose bone transforms and rendered visible slot mesh vertices using
   Live2DViewerEX's `Spine3_8.SkeletonBinary` + `Spine3_8.Atlas` + `Spine3_8.Skeleton`.
2. Excludes hidden alternate-pose slots/bones (e.g. `BU*` / `飞吻` / `扯` in `月本柚/明媚之约`),
   `root (0,0)`, and background/prop/shadow/effect bones (`bj*`, `beijing*`, `lan_*`, `youting*`, `ying*`).
3. Identifies the 6 anatomical regions (`头`, `胸`, `左手`, `右手`, `腿`, `足`) using visible facial/limb
   slots, bone hierarchy topology (`Head -> Chest -> Arms / Pelvis -> Legs -> Feet`), and strict
   non-poisoned token rules (preventing `"zu"` from matching `"zui"`/`"zuiba"`/`"zuoshou"`).
4. Computes `center_x`, `center_y`, `width`, `height` in Spine world units / 100 relative to each chosen
   bone's `(WorldX, WorldY)` so Live2DViewerEX's `BoneFollower` (`followBoneRotation = false`) places
   every `BoxCollider` dead-center on the actual rendered body part mesh.
5. Synchronizes `hit_areas` across `.config.json`, `config_en.config.json`, and `config_ja.config.json`.
"""

from __future__ import annotations

import ctypes
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from soultide_common import write_json

MODEL_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型")
LIVE2D_ROOT = MODEL_ROOT / "live2d"
SPINE_ROOT = MODEL_ROOT / "spine"
BACKUP_SPINE_ROOT = Path(r"E:\A灵魂潮汐\备份\spine")
CORE_DLL = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Plugins\x86_64\Live2DCubismCore.dll"
)
REPORT_PATH = Path(__file__).resolve().parent / "touch_trigger_fix_report.json"

ALIAS_CHAR = {
    "傲慢": "斯贝比尔",
    "安东尼娜": "安东妮娜",
    "安东": "安东妮娜",
    "艾尼斯": "艾妮斯",
    "贞德": "贞德·卢瓦尔",
    "露比": "露比·罗斯",
    "艾瑞妮": "爱瑞妮",
    "莎缇娅": "萨缇娅",
    "菲菲": "菲洛多希",
    "亚砂": "星见亚砂",
    "南宫": "南宫凛",
}
ALIAS_DRESS = {
    "公主": "完美公主",
    "泳装": "明媚之约",
    "玉龙娇娇纳福来": "玉龙娇娇邀福来",
}

BG_BONE_RE = re.compile(
    r"(^root$|^bj|_bj|^beijing|beijing\d|^bg_|_bg_|cloud|harmonious|^ying|_ying|shadow|"
    r"^lan_\d|^youting|^pangxie|^flower_shadow|^guang|_guang|^tx_|^fx_|^water|^tree|^niao|^mao|"
    r"(?:^|_)(?:bg|bj|background|back|yingzi|shadow|deng|light|shafa|sofa|zhuo|table|yi|chair|"
    r"chuang|bed|window|chuanghu|cloud|yun|shui|water|hua_|flower|tree|shu_|cat|mao|dog|gou|"
    r"bird|niao|book|shu\d|cup|bei|wine|jiu|lazhu|candle|guang|fx|effect|smoke|yanwu|wuzi|"
    r"room|floor|diban|wall|qiang|curtain|chuanglian|pillow|zhentou|qiu|ball|umbrella|san|"
    r"frame|kuang|mirror|jingzi|clock|zhong|music|yinfu|star|xing|moon|yue)(?:_|\d|$))",
    re.I,
)


# ---------------------------------------------------------------------------
# Part 1: Live2D Touch Trigger Calibrator (182 packages)
# ---------------------------------------------------------------------------

def _init_cubism_core():
    core = ctypes.CDLL(str(CORE_DLL))
    core.csmReviveMocInPlace.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    core.csmReviveMocInPlace.restype = ctypes.c_void_p
    core.csmGetSizeofModel.argtypes = [ctypes.c_void_p]
    core.csmGetSizeofModel.restype = ctypes.c_uint32
    core.csmInitializeModelInPlace.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    core.csmInitializeModelInPlace.restype = ctypes.c_void_p
    core.csmUpdateModel.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableCount.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableCount.restype = ctypes.c_int32
    core.csmGetDrawableIds.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableIds.restype = ctypes.POINTER(ctypes.c_char_p)
    core.csmGetDrawableVertexCounts.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableVertexCounts.restype = ctypes.POINTER(ctypes.c_int32)
    core.csmGetDrawableVertexPositions.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableVertexPositions.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    core.csmGetDrawableOpacities.argtypes = [ctypes.c_void_p]
    core.csmGetDrawableOpacities.restype = ctypes.POINTER(ctypes.c_float)
    return core


def inspect_moc3_drawables(core, moc_bytes: bytes) -> dict[str, dict[str, float]]:
    moc_buf = ctypes.create_string_buffer(len(moc_bytes) + 64)
    moc_addr = (ctypes.addressof(moc_buf) + 63) & ~63
    ctypes.memmove(moc_addr, moc_bytes, len(moc_bytes))
    moc = core.csmReviveMocInPlace(moc_addr, len(moc_bytes))
    msize = core.csmGetSizeofModel(moc)
    mod_buf = ctypes.create_string_buffer(msize + 64)
    mod_addr = (ctypes.addressof(mod_buf) + 63) & ~63
    model = core.csmInitializeModelInPlace(moc, mod_addr, msize)
    core.csmUpdateModel(model)

    dcnt = core.csmGetDrawableCount(model)
    ids_ptr = core.csmGetDrawableIds(model)
    vcnt_ptr = core.csmGetDrawableVertexCounts(model)
    vpos_ptr = core.csmGetDrawableVertexPositions(model)
    op_ptr = core.csmGetDrawableOpacities(model)

    out: dict[str, dict[str, float]] = {}
    for i in range(dcnt):
        did = ids_ptr[i].decode("utf-8", "ignore")
        vc = vcnt_ptr[i]
        if vc > 0:
            pos = np.ctypeslib.as_array(vpos_ptr[i], shape=(vc, 2))
            x0, y0 = pos.min(axis=0)
            x1, y1 = pos.max(axis=0)
            out[did] = {
                "x0": float(x0),
                "y0": float(y0),
                "x1": float(x1),
                "y1": float(y1),
                "w": float(x1 - x0),
                "h": float(y1 - y0),
                "cx": float((x0 + x1) / 2.0),
                "cy": float((y0 + y1) / 2.0),
                "op": float(op_ptr[i]),
            }
        else:
            out[did] = {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0, "w": 0.0, "h": 0.0, "cx": 0.0, "cy": 0.0, "op": 0.0}
    return out


def _pick_artmesh_hit_areas(drawables: dict[str, dict[str, float]], mots: dict[str, list[dict]]) -> list[dict[str, str]]:
    """Select accurate non-overlapping ArtMesh drawables when DREFTouchBox* is absent (e.g. 伊汐尔/原皮_变身)."""
    valid = {
        k: v for k, v in drawables.items()
        if v["w"] >= 0.04 and v["h"] >= 0.04 and v["w"] <= 0.70 and v["h"] <= 0.70
    }
    if not valid:
        valid = {k: v for k, v in drawables.items() if v["w"] > 0.01 and v["h"] > 0.01}

    all_x0 = min(v["x0"] for v in valid.values())
    all_x1 = max(v["x1"] for v in valid.values())
    all_y0 = min(v["y0"] for v in valid.values())
    all_y1 = max(v["y1"] for v in valid.values())
    char_w = max(0.2, all_x1 - all_x0)
    char_h = max(0.2, all_y1 - all_y0)
    mid_x = (all_x0 + all_x1) / 2.0

    targets = [
        ("头", mid_x, all_y0 + 0.78 * char_h, "Tap头"),
        ("左手", mid_x + 0.18 * char_w, all_y0 + 0.50 * char_h, "Tap手"),
        ("右手", mid_x - 0.18 * char_w, all_y0 + 0.50 * char_h, "Tap手"),
        ("胸", mid_x, all_y0 + 0.58 * char_h, "Tap胸"),
        ("臀部", mid_x, all_y0 + 0.35 * char_h, "Tap臀部"),
    ]
    used: set[str] = set()
    hits: list[dict[str, str]] = []
    for name, tx, ty, mgrp in targets:
        if not mots.get(mgrp):
            continue
        cands = [k for k in valid if k not in used]
        if not cands:
            cands = list(valid.keys())
        best = min(
            cands,
            key=lambda k: math.hypot(valid[k]["cx"] - tx, valid[k]["cy"] - ty)
            + (0.15 if valid[k]["op"] < 0.1 else 0.0),
        )
        used.add(best)
        hits.append({"Name": name, "Id": best, "Motion": mgrp})
    return hits


def fix_all_live2d_packages() -> dict[str, Any]:
    core = _init_cubism_core()
    cfgs = sorted(LIVE2D_ROOT.glob("*/*/.model3.json"))
    fixed_body_part_id = 0
    fixed_prefix_id = 0
    populated_empty_hits = 0
    artmesh_mapped = 0

    for cfg_p in cfgs:
        pkg_dir = cfg_p.parent
        rel = f"{pkg_dir.parent.name}/{pkg_dir.name}"
        is_base = pkg_dir.name == "原皮" or pkg_dir.name.startswith("原皮_")

        lang_files = [
            pkg_dir / ".model3.json",
            pkg_dir / "model_en.model3.json",
            pkg_dir / "model_ja.model3.json",
        ]
        lang_dicts = [json.loads(p.read_text(encoding="utf-8")) for p in lang_files if p.is_file()]
        d0 = lang_dicts[0]
        moc_bytes = (pkg_dir / d0["FileReferences"]["Moc"]).read_bytes()
        drawables = inspect_moc3_drawables(core, moc_bytes)

        has_body_drawable = ("Body2" in drawables and drawables["Body2"]["w"] > 0.01) or (
            "Body" in drawables and drawables["Body"]["w"] > 0.01
        )
        old_has = d0.get("HitAreas") or []
        if any(h["Id"] in ("Body", "Body2") and h["Id"] not in drawables for h in old_has):
            fixed_body_part_id += 1
        if any(h["Id"] not in drawables and h["Id"] not in ("Body", "Body2") for h in old_has):
            fixed_prefix_id += 1
        if not old_has:
            populated_empty_hits += 1

        for ld in lang_dicts:
            mots: dict[str, list[dict]] = ld["FileReferences"]["Motions"]

            # 1. If "Tap躯干" exists but there is no valid Body/Body2 drawable in .moc3,
            #    redistribute Tap躯干 entries into Tap臀部 / Tap胸 / Tap手 / Tap头 and delete Tap躯干.
            if not has_body_drawable and "Tap躯干" in mots:
                torso_items = mots.pop("Tap躯干")
                core_taps = ("Tap臀部", "Tap胸", "Tap手", "Tap头")
                for t_item in torso_items:
                    sig = (t_item.get("File", ""), t_item.get("Sound", ""))
                    # Pick the core tap group with the fewest items that doesn't already have sig
                    eligible = [
                        g for g in core_taps
                        if not any((x.get("File", ""), x.get("Sound", "")) == sig for x in mots.get(g, []))
                    ]
                    dst_g = min(eligible or core_taps, key=lambda g: len(mots.get(g, [])))
                    mots.setdefault(dst_g, []).append(dict(t_item))

            # 2. If some core tap groups are empty while others (e.g. Tap头 in 梦咲音月/此情无垢 or 星见亚砂/盛夏游乐场)
            #    are populated, balance/share across Tap头, Tap手, Tap胸, Tap臀部 so all 5 DREFTouchBox* work.
            core_taps_order = ("Tap头", "Tap手", "Tap胸", "Tap臀部")
            non_empty_core = [g for g in core_taps_order if mots.get(g)]
            if 0 < len(non_empty_core) < 4:
                pool: list[dict] = []
                for g in non_empty_core:
                    for it in mots[g]:
                        if not is_base and "_touch_" in (it.get("Sound") or "").lower():
                            continue
                        pool.append(it)
                if pool:
                    for idx, g in enumerate(core_taps_order):
                        if not mots.get(g):
                            mots[g] = [dict(pool[idx % len(pool)])]

            # 3. If ALL 4 core tap groups are empty (early skins without dedicated dress<N> touch lines),
            #    populate them from non-_touch_ interactive groups (Greeting, Morning/Noon/Evening, Gift, ExtraMotions, Idle).
            if not any(mots.get(g) for g in core_taps_order):
                fallback_mapping = [
                    ("Tap头", ("Greeting", "Morning", "ExtraMotions", "Idle")),
                    ("Tap手", ("Gift", "Food", "Noon", "Greeting", "ExtraMotions", "Idle")),
                    ("Tap胸", ("TouchSpecial", "Evening", "Midnight", "Greeting", "ExtraMotions", "Idle")),
                    ("Tap臀部", ("Festival", "Return", "Sad", "Greeting", "ExtraMotions", "Idle")),
                ]
                for dst_g, src_cands in fallback_mapping:
                    picked: list[dict] = []
                    for sg in src_cands:
                        for it in mots.get(sg, []):
                            if not is_base and "_touch_" in (it.get("Sound") or "").lower():
                                continue
                            picked.append(dict(it))
                            if len(picked) >= 3:
                                break
                        if picked:
                            break
                    if picked:
                        mots[dst_g] = picked

            # 4. Build verified HitAreas strictly from drawables dictionary
            specs = [
                ("头", ("DREFTouchBoxHead2", "DREFTouchBoxHead"), "Tap头"),
                ("左手", ("DREFTouchBoxHandL2", "DREFTouchBoxHandL"), "Tap手"),
                ("右手", ("DREFTouchBoxHandR2", "DREFTouchBoxHandR"), "Tap手"),
                ("胸", ("DREFTouchBoxBra2", "DREFTouchBoxBra"), "Tap胸"),
                ("躯干", ("Body2", "Body"), "Tap躯干"),
                ("臀部", ("DREFTouchBoxHip2", "DREFTouchBoxHip"), "Tap臀部"),
            ]
            new_hits: list[dict[str, str]] = []
            for name, id_cands, mtn_grp in specs:
                if not mots.get(mtn_grp):
                    continue
                for cid in id_cands:
                    if cid in drawables and drawables[cid]["w"] > 0.01 and drawables[cid]["h"] > 0.01:
                        new_hits.append({"Name": name, "Id": cid, "Motion": mtn_grp})
                        break

            if not new_hits:
                new_hits = _pick_artmesh_hit_areas(drawables, mots)
                if ld is d0:
                    artmesh_mapped += 1
            else:
                # If any non-empty Tap* group (e.g. Tap臀部 in 和铃/原皮, 和铃/古锦新韵) lacks its DREFTouchBox* drawable,
                # bind the best non-overlapping ArtMesh* drawable for that anatomical region.
                bound_grps = {h["Motion"] for h in new_hits}
                missing_grps = [g for g in ("Tap头", "Tap手", "Tap胸", "Tap臀部") if mots.get(g) and g not in bound_grps]
                if missing_grps:
                    art_fallbacks = _pick_artmesh_hit_areas(drawables, mots)
                    used_ids = {h["Id"] for h in new_hits}
                    for af in art_fallbacks:
                        if af["Motion"] in missing_grps and af["Id"] not in used_ids:
                            new_hits.append(af)
                            used_ids.add(af["Id"])
                            bound_grps.add(af["Motion"])

            ld["HitAreas"] = new_hits

        for lp, ld in zip([p for p in lang_files if p.is_file()], lang_dicts):
            write_json(lp, ld)

    print(
        f"[Live2D] Audited 182 packages: fixed_part_body={fixed_body_part_id}, "
        f"fixed_prefix_id={fixed_prefix_id}, populated_empty={populated_empty_hits}, "
        f"artmesh_mapped={artmesh_mapped}",
        flush=True,
    )
    return {
        "total_live2d": len(cfgs),
        "fixed_part_body_id": fixed_body_part_id,
        "fixed_prefix_shadowed_id": fixed_prefix_id,
        "populated_previously_empty_hit_areas": populated_empty_hits,
        "artmesh_mapped_packages": artmesh_mapped,
    }


# ---------------------------------------------------------------------------
# Part 2: Spine Touch Trigger Calibrator (170 packages via Spine3_8 runtime)
# ---------------------------------------------------------------------------

PS_SPINE_EXTRACTOR = r"""
param([string]$OutJsonPath)
[System.Reflection.Assembly]::LoadFrom("C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed\UnityEngine.CoreModule.dll") | Out-Null
[System.Reflection.Assembly]::LoadFrom("C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed\Assembly-CSharp.dll") | Out-Null

$code = @"
using Spine3_8;
public class DummyTexLoaderBatch : TextureLoader {
    public void Load(AtlasPage page, string path) { }
    public void Unload(object texture) { }
}
"@
Add-Type -TypeDefinition $code -ReferencedAssemblies "C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed\Assembly-CSharp.dll"

$root = "E:\A灵魂潮汐\Live2D与Spine模型\spine"
$cfgs = Get-ChildItem -Path "$root\*\*\*" -Force | Where-Object { $_.Name -eq ".config.json" } | Sort-Object FullName
$allData = @{}
$texLoader = New-Object DummyTexLoaderBatch

foreach ($cfgFile in $cfgs) {
    $dir = $cfgFile.DirectoryName
    $rel = $dir.Substring($root.Length + 1).Replace('\', '/')
    $cfg = Get-Content $cfgFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $skelPath = Join-Path $dir $cfg.skeleton
    $atlasPath = Join-Path $dir $cfg.atlases[0].atlas

    $sr = New-Object System.IO.StreamReader($atlasPath)
    $atlas = New-Object Spine3_8.Atlas($sr, $dir, $texLoader)
    $sr.Close()

    if ($skelPath.ToLower().EndsWith(".json") -and ((Get-Content $skelPath -TotalCount 1 -Encoding UTF8).TrimStart().StartsWith("{"))) {
        $sj = New-Object Spine3_8.SkeletonJson((New-Object Spine3_8.AtlasAttachmentLoader($atlas)))
        $sd = $sj.ReadSkeletonData($skelPath)
    } else {
        $sb = New-Object Spine3_8.SkeletonBinary((New-Object Spine3_8.AtlasAttachmentLoader($atlas)))
        $sd = $sb.ReadSkeletonData($skelPath)
    }

    $sk = New-Object Spine3_8.Skeleton($sd)
    $idleName = $cfg.motions.idle[0].file
    $anim = $sd.FindAnimation($idleName)
    if ($null -ne $anim) {
        $anim.Apply($sk, 0, 0, $true, $null, 1.0, [Spine3_8.MixBlend]::Setup, [Spine3_8.MixDirection]::In)
    }
    $sk.UpdateWorldTransform()

    $bonesList = New-Object System.Collections.ArrayList
    $bIdxMap = @{}
    for ($bi = 0; $bi -lt $sk.Bones.Count; $bi++) {
        $b = $sk.Bones.Items[$bi]
        $bIdxMap[$b.Data.Name] = $bi
        $pName = if ($null -ne $b.Parent) { $b.Parent.Data.Name } else { "" }
        [void]$bonesList.Add(@{
            idx = $bi
            name = $b.Data.Name
            parent = $pName
            wx = [math]::Round([double]$b.WorldX, 2)
            wy = [math]::Round([double]$b.WorldY, 2)
            len = [math]::Round([double]$b.Data.Length, 2)
        })
    }

    $slotsList = New-Object System.Collections.ArrayList
    $verts = New-Object float[] 8000
    foreach ($slot in $sk.DrawOrder) {
        $att = $slot.Attachment
        if ($null -eq $att -or $slot.A -le 0.05) { continue }
        $cnt = 0
        $wBones = New-Object System.Collections.ArrayList
        if ($att -is [Spine3_8.MeshAttachment]) {
            $ma = [Spine3_8.MeshAttachment]$att
            $cnt = $ma.WorldVerticesLength
            if ($cnt -gt $verts.Length) { $verts = New-Object float[] $cnt }
            $ma.ComputeWorldVertices($slot, 0, $cnt, $verts, 0, 2)
            if ($null -ne $ma.Bones -and $ma.Bones.Length -gt 0) {
                $seenB = @{}
                $ii = 0
                while ($ii -lt $ma.Bones.Length) {
                    $nb = $ma.Bones[$ii]
                    $ii += 1
                    for ($jj = 0; $jj -lt $nb; $jj++) {
                        $bIndex = $ma.Bones[$ii + $jj]
                        if (-not $seenB.ContainsKey($bIndex) -and $bIndex -ge 0 -and $bIndex -lt $sk.Bones.Count) {
                            $seenB[$bIndex] = $true
                            [void]$wBones.Add($sk.Bones.Items[$bIndex].Data.Name)
                        }
                    }
                    $ii += $nb
                }
            }
        } elseif ($att -is [Spine3_8.RegionAttachment]) {
            $ra = [Spine3_8.RegionAttachment]$att
            $cnt = 8
            $ra.ComputeWorldVertices($slot.Bone, $verts, 0, 2)
        }
        if ($cnt -gt 0) {
            $minX = 1e9; $maxX = -1e9; $minY = 1e9; $maxY = -1e9
            for ($i = 0; $i -lt $cnt; $i += 2) {
                $vx = $verts[$i]; $vy = $verts[$i+1]
                if ($vx -lt $minX) { $minX = $vx }
                if ($vx -gt $maxX) { $maxX = $vx }
                if ($vy -lt $minY) { $minY = $vy }
                if ($vy -gt $maxY) { $maxY = $vy }
            }
            if ($wBones.Count -eq 0) {
                [void]$wBones.Add($slot.Bone.Data.Name)
            }
            [void]$slotsList.Add(@{
                name = $slot.Data.Name
                att = $att.Name
                bone = $slot.Bone.Data.Name
                wbones = $wBones
                cx = [math]::Round(($minX + $maxX) / 2.0, 2)
                cy = [math]::Round(($minY + $maxY) / 2.0, 2)
                w = [math]::Round(($maxX - $minX), 2)
                h = [math]::Round(($maxY - $minY), 2)
                x0 = [math]::Round($minX, 2)
                x1 = [math]::Round($maxX, 2)
                y0 = [math]::Round($minY, 2)
                y1 = [math]::Round($maxY, 2)
            })
        }
    }

    $allData[$rel] = @{
        bones = $bonesList
        slots = $slotsList
    }
}

$jsonStr = $allData | ConvertTo-Json -Depth 7 -Compress
[System.IO.File]::WriteAllText($OutJsonPath, $jsonStr, [System.Text.Encoding]::UTF8)
"""


SPINE_GEOM_CACHE_PATH = Path(__file__).resolve().parent / "_spine38_geom_cache.json"


def _extract_all_spine38_geometries() -> dict[str, Any]:
    if SPINE_GEOM_CACHE_PATH.is_file():
        return json.loads(SPINE_GEOM_CACHE_PATH.read_text(encoding="utf-8-sig"))
    with tempfile.TemporaryDirectory(prefix="spine38_geom_") as td:
        ps_file = Path(td) / "extract.ps1"
        ps_file.write_text(PS_SPINE_EXTRACTOR, encoding="utf-8-sig")
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps_file),
                "-OutJsonPath",
                str(SPINE_GEOM_CACHE_PATH),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"PowerShell Spine3_8 extractor failed:\n{r.stderr}\n{r.stdout}")
        return json.loads(SPINE_GEOM_CACHE_PATH.read_text(encoding="utf-8-sig"))


def _index_backup_spine_hit_areas() -> dict[tuple[str, str], list[dict[str, Any]]]:
    bkp_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in sorted(BACKUP_SPINE_ROOT.rglob(".config.json")):
        rel = p.parent.relative_to(BACKUP_SPINE_ROOT)
        if len(rel.parts) < 2:
            continue
        ch_nm = ALIAS_CHAR.get(rel.parts[0], rel.parts[0])
        dr_nm = ALIAS_DRESS.get(rel.parts[1], rel.parts[1])
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        ha = d.get("hit_areas") or []
        if ha and (ch_nm, dr_nm) not in bkp_map:
            bkp_map[(ch_nm, dr_nm)] = ha
    return bkp_map


def _is_bg_token(s: str) -> bool:
    return bool(BG_BONE_RE.search(s))


def _check_hit_areas_geometry(
    hit_areas: list[dict[str, Any]],
    geom: dict[str, Any],
) -> list[str]:
    """Return list of geometric anomaly messages for a Spine hit_areas list (empty = clean)."""
    bmap = {b["name"]: b for b in geom["bones"]}
    vbones = [b for b in geom["bones"] if b.get("vw", 0) > 0 and not _is_bg_token(b["name"])]
    if not vbones:
        vbones = [b for b in geom["bones"] if b.get("vw", 0) > 0]
    if not vbones:
        return []

    cy0 = min(b["vy0"] for b in vbones)
    cy1 = max(b["vy1"] for b in vbones)
    ch = max(200.0, cy1 - cy0)

    boxes: dict[str, tuple[float, float, float, float, str]] = {}
    for ha in hit_areas:
        bid = ha["id"]
        if bid not in bmap:
            return [f"missing bone {bid}"]
        b = bmap[bid]
        bx = b["wx"] + float(ha.get("center_x", 0.0)) * 100.0
        by = b["wy"] + float(ha.get("center_y", 0.0)) * 100.0
        bw = float(ha.get("width", 1.5)) * 100.0
        bh = float(ha.get("height", 1.5)) * 100.0
        boxes[ha["motion"]] = (bx, by, bw, bh, bid)

    probs: list[str] = []
    if "头" in boxes and "胸" in boxes:
        if boxes["胸"][1] >= boxes["头"][1]:
            probs.append(f"胸 above 头 ({boxes['胸'][1]:.0f} >= {boxes['头'][1]:.0f})")
        if boxes["头"][1] - boxes["胸"][1] > 0.34 * ch:
            probs.append(f"胸 too far below 头 ({(boxes['头'][1] - boxes['胸'][1]) / ch:.2f}*H)")
    if "头" in boxes:
        hx, hy, _, _, hbid = boxes["头"]
        for hand_k in ("左手", "右手"):
            if hand_k in boxes:
                lx, ly, _, _, lbid = boxes[hand_k]
                if math.hypot(lx - hx, ly - hy) < 0.14 * ch and ly > hy - 0.12 * ch:
                    probs.append(f"{hand_k}({lbid}) stacked on 头({hbid})")
    if "腿" in boxes and "足" in boxes:
        if boxes["足"][1] > boxes["腿"][1] + 0.04 * ch:
            probs.append(f"足 above 腿 ({boxes['足'][1]:.0f} > {boxes['腿'][1]:.0f})")
    if "胸" in boxes and "腿" in boxes:
        if boxes["腿"][1] >= boxes["胸"][1]:
            probs.append(f"腿 above 胸 ({boxes['腿'][1]:.0f} >= {boxes['胸'][1]:.0f})")

    keys = list(boxes.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            k1, k2 = keys[i], keys[j]
            if {k1, k2} == {"左手", "右手"}:
                continue
            d = math.hypot(boxes[k1][0] - boxes[k2][0], boxes[k1][1] - boxes[k2][1])
            if d < 0.055 * ch:
                probs.append(f"{k1} & {k2} stacked ({d / ch:.3f}*H)")
    return probs


def solve_spine_anatomical_hit_areas(
    geom: dict[str, Any],
    motions: dict[str, Any],
    is_battlehead_orig: bool = False,
) -> list[dict[str, Any]]:
    """V3 Per-Bone Weighted Vertex Anatomical Solver across all 170 Spine packages."""
    bones_raw: list[dict[str, Any]] = geom["bones"]
    slots_raw: list[dict[str, Any]] = geom["slots"]
    bone_by_name: dict[str, dict[str, Any]] = {b["name"]: b for b in bones_raw}

    children_by_name: dict[str, list[str]] = {b["name"]: [] for b in bones_raw}
    for b in bones_raw:
        p = b["parent"]
        if p and p in children_by_name:
            children_by_name[p].append(b["name"])

    def get_subtree_bones(root_b: str) -> set[str]:
        res = {root_b}
        stack = [root_b]
        while stack:
            cur = stack.pop()
            for ch in children_by_name.get(cur, []):
                if ch not in res:
                    res.add(ch)
                    stack.append(ch)
        return res

    def get_ancestors(bname: str) -> list[str]:
        anc = []
        cur = bone_by_name.get(bname, {}).get("parent", "")
        while cur and cur in bone_by_name:
            anc.append(cur)
            cur = bone_by_name[cur].get("parent", "")
        return anc

    def vpos(bname: str) -> tuple[float, float]:
        b = bone_by_name[bname]
        if b.get("vw", 0) > 0 and b.get("vcx") is not None and b.get("vcy") is not None:
            return float(b["vcx"]), float(b["vcy"])
        return float(b["wx"]), float(b["wy"])

    # 1. Filter visible slots & rendered bones to character geometry (exclude BG/props)
    char_slots = [
        s for s in slots_raw
        if not _is_bg_token(s["name"])
        and not _is_bg_token(s["att"])
        and not _is_bg_token(s["bone"])
    ]
    if not char_slots:
        char_slots = slots_raw

    active_deform_bones: set[str] = {
        b["name"] for b in bones_raw
        if b.get("vw", 0) > 0 and b["name"] != "root" and not _is_bg_token(b["name"])
    }
    if not active_deform_bones:
        for s in char_slots:
            for wb in s.get("wbones") or [s["bone"]]:
                if wb in bone_by_name and wb != "root" and not _is_bg_token(wb):
                    active_deform_bones.add(wb)

    char_bones: set[str] = set(active_deform_bones)
    for ab in list(active_deform_bones):
        for anc in get_ancestors(ab):
            if anc != "root" and not _is_bg_token(anc):
                char_bones.add(anc)

    if not char_bones:
        char_bones = {b["name"] for b in bones_raw if b["name"] != "root"} or {bones_raw[0]["name"]}

    # True character visual bounds from rendered vertices of non-BG active bones
    vbones = [bone_by_name[b] for b in active_deform_bones if bone_by_name[b].get("vw", 0) > 0]
    if vbones:
        c_x0 = min(b["vx0"] for b in vbones)
        c_x1 = max(b["vx1"] for b in vbones)
        c_y0 = min(b["vy0"] for b in vbones)
        c_y1 = max(b["vy1"] for b in vbones)
        xs_med = sorted(b["vcx"] for b in vbones)
        char_mid_x = float(xs_med[len(xs_med) // 2])
    else:
        c_x0 = min(bone_by_name[b]["wx"] for b in char_bones)
        c_x1 = max(bone_by_name[b]["wx"] for b in char_bones)
        c_y0 = min(bone_by_name[b]["wy"] for b in char_bones)
        c_y1 = max(bone_by_name[b]["wy"] for b in char_bones)
        char_mid_x = (c_x0 + c_x1) / 2.0

    char_w = max(150.0, c_x1 - c_x0)
    char_h = max(200.0, c_y1 - c_y0)

    # Filter out extreme outlier background slots when inspecting named slots
    if len(char_slots) >= 4:
        med_w = sorted(s["w"] for s in char_slots)[len(char_slots) // 2]
        core_slots = [s for s in char_slots if s["w"] <= max(800.0, med_w * 8.0)] or char_slots
    else:
        core_slots = char_slots

    # 2. Identify Head Hub Bone (`head_bone_name`) & Head Center (`head_cx, head_cy`)
    face_re = re.compile(
        r"(^口$|^bizi\d*$|^nose|^zuiba\d*$|^zui\d*$|^mouth|^xiao\d*$|^lianhong|^saihong|"
        r"^zuoyan|^youyan|^l_eye|^r_eye|eye\d*$|^yan\d*$|^meimao|^zuomei|^youmei|"
        r"^lian\d*$|^lianlian\d*$|^face\d*$|^head\d*$|^tou\d*$)",
        re.I,
    )
    not_head_re = re.compile(r"(xiaoxiong|guazhui|xiong|shou|tui|jiao|qun|hudiejie|bj|beijing)", re.I)

    face_slots = [
        s for s in core_slots
        if (face_re.search(s["name"]) or face_re.search(s["att"]) or face_re.search(s["bone"]))
        and not not_head_re.search(s["name"])
        and not not_head_re.search(s["bone"])
        and s["cy"] >= c_y0 + 0.45 * char_h
    ]
    named_head_bones = [
        b for b in char_bones
        if re.search(r"(^lian\d*$|^lianlian\d*$|^face\d*$|^head\d*$|^tou\d*$)", b, re.I)
        and not not_head_re.search(b)
        and vpos(b)[1] >= c_y0 + 0.45 * char_h
    ]

    head_bone_name = ""
    if named_head_bones:
        head_bone_name = max(
            named_head_bones,
            key=lambda b: (len(children_by_name.get(b, [])), vpos(b)[1]),
        )
    elif face_slots:
        cand_hubs: dict[str, int] = {}
        for s in face_slots:
            sb = s["bone"]
            for cand in [sb] + get_ancestors(sb)[:2]:
                if cand in char_bones and cand != "root":
                    cand_hubs[cand] = cand_hubs.get(cand, 0) + 1 + len(children_by_name.get(cand, []))
        if cand_hubs:
            head_bone_name = max(cand_hubs, key=lambda k: cand_hubs[k])

    if not head_bone_name:
        upper_cands = [
            b for b in char_bones
            if vpos(b)[1] >= c_y0 + 0.55 * char_h
            and b.lower() not in ("root", "all", "bone", "man", "z", "z2")
        ]
        if not upper_cands:
            upper_cands = [b for b in char_bones if vpos(b)[1] >= c_y0 + 0.42 * char_h and b.lower() not in ("root", "all")]
        if upper_cands:
            def _head_hub_score(b: str) -> float:
                sub = get_subtree_bones(b) & active_deform_bones
                n_ch = len(children_by_name.get(b, []))
                vy_frac = (vpos(b)[1] - c_y0) / char_h
                if len(sub) > len(active_deform_bones) * 0.65 and n_ch < 12:
                    return -1.0
                return n_ch * 3.0 + min(25, len(sub)) + vy_frac * 12.0
            head_bone_name = max(upper_cands, key=_head_hub_score)
        else:
            head_bone_name = max(char_bones, key=lambda b: vpos(b)[1])

    # Promote head_bone_name upward 1 step ONLY if its direct parent is a broader head root
    # (e.g. z10 above u_81 in BattleHead: z10 has >= 3 children including hair & face, whereas neck z9 only has 1 child z10!).
    p = bone_by_name[head_bone_name]["parent"]
    if p and p in char_bones and p.lower() not in ("root", "all", "bone", "man", "z", "z2"):
        p_sub = get_subtree_bones(p) & active_deform_bones
        p_ch_cnt = len(children_by_name.get(p, []))
        hx0, hy0 = vpos(head_bone_name)
        px0, py0 = vpos(p)
        if (
            p_ch_cnt >= 3
            and len(p_sub) <= max(8, int(len(active_deform_bones) * 0.58))
            and py0 >= c_y0 + 0.65 * char_h
            and abs(py0 - hy0) <= 0.12 * char_h
            and abs(px0 - hx0) <= 0.16 * char_w
            and not re.search(r"(xiong|chest|shenti|body|shangshen|bozi|neck)", p, re.I)
        ):
            head_bone_name = p

    head_sub = get_subtree_bones(head_bone_name)
    # Compute head_cx, head_cy cleanly without being dragged sideways by long flowing hair/ponytails
    if face_slots:
        head_cx = sum(s["cx"] for s in face_slots) / len(face_slots)
        head_cy = sum(s["cy"] for s in face_slots) / len(face_slots)
    else:
        hb = bone_by_name[head_bone_name]
        hx_base, hy_base = vpos(head_bone_name)
        compact_head_bones = [
            b for b in head_sub
            if bone_by_name[b].get("vw", 0) > 0
            and abs(vpos(b)[0] - hx_base) <= 0.18 * char_w
            and abs(vpos(b)[1] - hy_base) <= 0.15 * char_h
        ]
        if hb.get("vw", 0) >= 8:
            head_cx, head_cy = hx_base, hy_base
        elif compact_head_bones:
            w_tot = sum(bone_by_name[b]["vw"] for b in compact_head_bones)
            head_cx = sum(vpos(b)[0] * bone_by_name[b]["vw"] for b in compact_head_bones) / w_tot
            head_cy = sum(vpos(b)[1] * bone_by_name[b]["vw"] for b in compact_head_bones) / w_tot
        else:
            head_cx, head_cy = hx_base, hy_base

    # 3. Identify Chest / Upper Torso (`胸`) — strictly below head by 0.11..0.30 * char_h
    chest_re = re.compile(r"(^xiong|xiong\d|xiongyi|chest|breast|bra|rufang|^ren60$|^ren61$|^shangshen[678]$)", re.I)
    torso_re = re.compile(r"(^shangshen\d*$|^shenti\d*$|^shengti\d*$|^body\d*$|^qugan\d*$)", re.I)
    not_chest_re = re.compile(r"(xiaoxiong|fasheng|guazhui|tou|lian|shou|hand|tui|leg|jiao|foot|zui|meimao|yan|bj|beijing)", re.I)

    chest_y_min = head_cy - 0.30 * char_h
    chest_y_max = head_cy - 0.11 * char_h
    ideal_chest_y = head_cy - (0.165 if is_battlehead_orig else 0.195) * char_h

    chest_named_bones = [
        b for b in char_bones
        if chest_re.search(b)
        and not not_chest_re.search(b)
        and b not in head_sub
        and (head_cy - 0.32 * char_h <= vpos(b)[1] <= head_cy - 0.08 * char_h)
    ]
    torso_named_bones = [
        b for b in char_bones
        if torso_re.search(b)
        and not not_chest_re.search(b)
        and b not in head_sub
        and (head_cy - 0.34 * char_h <= vpos(b)[1] <= head_cy - 0.08 * char_h)
    ]

    head_ancs = [a for a in get_ancestors(head_bone_name) if a in char_bones and a != "root"]
    # Walk down head_ancs to find the first torso ancestor in the chest band (skipping neck/bozi!)
    spine_chest_hub = ""
    for anc in head_ancs:
        if re.search(r"(bozi|neck)", anc, re.I):
            continue
        ay = vpos(anc)[1]
        if head_cy - 0.30 * char_h <= ay <= head_cy - 0.10 * char_h:
            spine_chest_hub = anc
            break
    if not spine_chest_hub and head_ancs:
        # Take first non-neck ancestor below head_cy - 0.08*H, or head_ancs[0]
        for anc in head_ancs:
            if not re.search(r"(bozi|neck)", anc, re.I) and vpos(anc)[1] < head_cy - 0.07 * char_h:
                spine_chest_hub = anc
                break
        if not spine_chest_hub:
            spine_chest_hub = head_ancs[min(1, len(head_ancs) - 1)]

    if chest_named_bones:
        chest_cx = sum(vpos(b)[0] for b in chest_named_bones) / len(chest_named_bones)
        chest_cy = sum(vpos(b)[1] for b in chest_named_bones) / len(chest_named_bones)
    elif spine_chest_hub and (chest_y_min <= vpos(spine_chest_hub)[1] <= chest_y_max):
        chest_cx, chest_cy = vpos(spine_chest_hub)
    elif torso_named_bones:
        tb = min(torso_named_bones, key=lambda b: abs(vpos(b)[1] - ideal_chest_y))
        chest_cx, chest_cy = vpos(tb)
    else:
        chest_cx = head_cx * 0.75 + char_mid_x * 0.25
        chest_cy = ideal_chest_y

    # Strictly clamp chest_cy inside the anatomical band below head_cy!
    chest_cy = max(chest_y_min, min(chest_y_max, chest_cy))

    # 4. Helpers & Bone Picker (using per-bone weighted vertex position vpos!)
    used_bones: set[str] = {head_bone_name}

    def _in_head_exclusion(bname: str, allow_named_hand: bool = False) -> bool:
        if bname in head_sub:
            return True
        bx, by = vpos(bname)
        if allow_named_hand and re.search(r"(shou|hand|wrist|wan)", bname, re.I):
            # Even named hands shouldn't stack dead-center on head
            return math.hypot(bx - head_cx, by - head_cy) < 0.10 * char_h
        if math.hypot(bx - head_cx, by - head_cy) < 0.16 * char_h:
            return True
        if by > head_cy - 0.10 * char_h and abs(bx - head_cx) < 0.24 * char_w:
            return True
        return False

    def _pick_distinct_bone(
        pref_bones: list[str],
        target_x: float,
        target_y: float,
        forbid_re: re.Pattern[str] | None = None,
        y_bounds: tuple[float, float] | None = None,
        exclude_head_zone: bool = False,
        min_dist_from: list[tuple[float, float, float]] | None = None,
        allow_named_hand: bool = False,
    ) -> tuple[str, float, float]:
        def _ok(b: str, check_forbid: bool = True, check_y: bool = True, check_dist: bool = True) -> bool:
            if b in used_bones or b.lower() in ("root", "all") or _is_bg_token(b):
                return False
            if check_forbid and forbid_re is not None and forbid_re.search(b):
                return False
            if exclude_head_zone and _in_head_exclusion(b, allow_named_hand=allow_named_hand):
                return False
            bx, by = vpos(b)
            if check_y and y_bounds is not None:
                if not (y_bounds[0] <= by <= y_bounds[1]):
                    return False
            if check_dist and min_dist_from:
                for ox, oy, md in min_dist_from:
                    if math.hypot(bx - ox, by - oy) < md:
                        return False
            return True

        pool = [b for b in pref_bones if _ok(b, True, True, True)]
        if not pool:
            pool = [b for b in pref_bones if _ok(b, True, False, True)]
        if not pool:
            pool = [b for b in active_deform_bones if _ok(b, True, True, True)]
        if not pool:
            pool = [b for b in char_bones if _ok(b, True, True, True)]
        if not pool:
            pool = [b for b in active_deform_bones if _ok(b, True, False, True)]
        if not pool:
            pool = [b for b in active_deform_bones if _ok(b, False, False, True)]
        if not pool:
            pool = [b for b in char_bones if b not in used_bones and b.lower() not in ("root", "all") and not _is_bg_token(b)]
        if not pool:
            pool = [b["name"] for b in bones_raw if b["name"] not in used_bones and b["name"].lower() not in ("root", "all") and not _is_bg_token(b["name"])] or [bones_raw[0]["name"]]

        chosen = min(pool, key=lambda bn: math.hypot(vpos(bn)[0] - target_x, vpos(bn)[1] - target_y))
        used_bones.add(chosen)
        vx, vy = vpos(chosen)
        return chosen, vx, vy

    hit_areas: list[dict[str, Any]] = []
    u_scale = max(0.55, min(2.6, char_h / 1150.0))

    def _emit_hit(
        name: str,
        motion: str,
        bname: str,
        vis_cx: float,
        vis_cy: float,
        base_w: float,
        base_h: float,
        max_off_mult: float = 5.5,
    ) -> tuple[float, float]:
        if motion not in motions:
            return vis_cx, vis_cy
        b = bone_by_name[bname]
        w_u = round(base_w * u_scale, 2)
        h_u = round(base_h * u_scale, 2)
        dx_u = round((vis_cx - b["wx"]) / 100.0, 2)
        dy_u = round((vis_cy - b["wy"]) / 100.0, 2)
        max_off = round(max_off_mult * u_scale, 2)
        dx_u = max(-max_off, min(max_off, dx_u))
        dy_u = max(-max_off, min(max_off, dy_u))
        entry: dict[str, Any] = {
            "name": name,
            "id": bname,
            "motion": motion,
            "width": w_u,
            "height": h_u,
        }
        if abs(dx_u) >= 0.08:
            entry["center_x"] = dx_u
        if abs(dy_u) >= 0.08:
            entry["center_y"] = dy_u
        hit_areas.append(entry)
        return b["wx"] + dx_u * 100.0, b["wy"] + dy_u * 100.0

    # A. Head (`头`)
    em_head_x, em_head_y = _emit_hit("头", "头", head_bone_name, head_cx, head_cy, 2.5, 2.3)

    # B. Chest (`胸`) — never pick a top-level root/All bone whose wy sits far above head_y
    chest_pool = [
        b for b in (chest_named_bones + ([spine_chest_hub] if spine_chest_hub and spine_chest_hub != head_bone_name else []) + torso_named_bones)
        if b.lower() not in ("root", "all") and abs(bone_by_name[b]["wy"] - chest_cy) <= 0.45 * char_h
    ]
    chest_b, _, _ = _pick_distinct_bone(
        chest_pool,
        chest_cx,
        chest_cy,
        forbid_re=not_chest_re,
        y_bounds=(head_cy - 0.34 * char_h, head_cy - 0.08 * char_h),
        exclude_head_zone=False,
        min_dist_from=[(em_head_x, em_head_y, 0.08 * char_h)],
    )
    em_chest_x, em_chest_y = _emit_hit("胸", "胸", chest_b, chest_cx, chest_cy, 2.3, 1.9, max_off_mult=8.5)

    # C. Left Hand (`左手`) & Right Hand (`右手`)
    lhand_re = re.compile(
        r"(zuoshou|l_hand|hand_l|shou_l|shou_left|zuoxiaobi|l_xiaobi|l_arm|arm_l|zuodabi|l_dabi|zbushou|qqshou|^shou_[1-9])",
        re.I,
    )
    rhand_re = re.compile(
        r"(youshou|r_hand|hand_r|shou_r|shou_right|youxiaobi|r_xiaobi|r_arm|arm_r|youdabi|r_dabi|hqshou|^bushou)",
        re.I,
    )
    any_hand_re = re.compile(r"(shou|hand|xiaobi|dabi|arm|wan|wrist|finger|zhi)", re.I)
    not_hand_re = re.compile(
        r"(tou|houfa|qianfa|toufa|liuhai|toushi|lian|face|head|yan|eye|meimao|zui|mouth|bizi|xiong|chest|tui|leg|jiao|foot|qun|skirt|"
        r"pifeng|youting|hulu|piaodai|piaodia|shiping|yaodai|lingdang|fasheng|guazhui|weiba|hua\d|hudiejie|bj|beijing)",
        re.I,
    )

    lhand_cands = [b for b in char_bones if lhand_re.search(b) and not not_hand_re.search(b) and not _in_head_exclusion(b, True)]
    rhand_cands = [b for b in char_bones if rhand_re.search(b) and not not_hand_re.search(b) and not _in_head_exclusion(b, True)]

    # Discover arm chains structurally from chest_b & spine_chest_hub (e.g. z8 -> z11..z18 and z14..z17 in BattleHead!)
    arm_branch_tips: list[tuple[str, float, float, float, int]] = []
    seen_roots: set[str] = set()
    hub_search_list = []
    for h in (chest_b, spine_chest_hub) + tuple(head_ancs[:3]):
        if h and h not in hub_search_list and h not in head_sub and h != "root":
            hub_search_list.append(h)
    neck_branch_roots = set(head_ancs) | {head_bone_name}
    chest_prefix_m = re.match(r"^([a-zA-Z]+)", chest_b)
    chest_prefix = chest_prefix_m.group(1).lower() if chest_prefix_m else ""

    for hub_rank, sh in enumerate(hub_search_list):
        for ch in children_by_name.get(sh, []):
            if (
                ch in seen_roots
                or ch in neck_branch_roots
                or ch in head_sub
                or ch in chest_named_bones
                or not_hand_re.search(ch)
            ):
                continue
            seen_roots.add(ch)
            sub_b = (get_subtree_bones(ch) & active_deform_bones) - head_sub - set(chest_named_bones)
            # Exclude leg branches (whose distal bone is down near the bottom 25% of character!)
            if 2 <= len(sub_b) <= 48:
                ch_pref_m = re.match(r"^([a-zA-Z]+)", ch)
                same_pref = 1 if (chest_prefix and ch_pref_m and ch_pref_m.group(1).lower() == chest_prefix) else 0
                tip_pool = [
                    b for b in sub_b
                    if same_pref and re.match(r"^([a-zA-Z]+)", b) and re.match(r"^([a-zA-Z]+)", b).group(1).lower() == chest_prefix
                ] or list(sub_b)
                tip_b = max(
                    tip_pool,
                    key=lambda b: math.hypot(vpos(b)[0] - em_chest_x, vpos(b)[1] - em_chest_y),
                )
                tcx, tcy = vpos(tip_b)
                if tcy < c_y0 + 0.25 * char_h or _in_head_exclusion(tip_b):
                    continue
                reach = math.hypot(tcx - em_chest_x, tcy - em_chest_y)
                if reach >= 0.12 * char_h:
                    direct_chest = 1 if hub_rank == 0 else 0
                    prio = direct_chest * 4 + same_pref * 2
                    arm_branch_tips.append((tip_b, tcx, tcy, reach, prio))

    if not lhand_cands and not rhand_cands:
        generic_hands = [
            b for b in char_bones
            if any_hand_re.search(b) and not not_hand_re.search(b) and not _in_head_exclusion(b, True)
        ]
        if len(generic_hands) >= 2:
            generic_hands_sorted = sorted(generic_hands, key=lambda b: vpos(b)[0])
            lhand_cands = generic_hands_sorted[: len(generic_hands_sorted) // 2]
            rhand_cands = generic_hands_sorted[len(generic_hands_sorted) // 2 :]
        elif len(arm_branch_tips) >= 2:
            top2_arms = sorted(arm_branch_tips, key=lambda t: (t[4], t[3]), reverse=True)[:2]
            top2_sorted = sorted(top2_arms, key=lambda t: (t[1], -t[2]))
            lhand_cands = [top2_sorted[0][0]]
            rhand_cands = [top2_sorted[1][0]]

    lh_tx = em_chest_x - 0.22 * char_w
    lh_ty = em_chest_y - 0.08 * char_h
    rh_tx = em_chest_x + 0.22 * char_w
    rh_ty = em_chest_y - 0.08 * char_h
    hand_y_bounds = (c_y0 + 0.24 * char_h, em_head_y - 0.12 * char_h)
    hand_excl = [(em_head_x, em_head_y, 0.16 * char_h), (em_chest_x, em_chest_y, 0.08 * char_h)]

    lh_b, lh_vx, lh_vy = _pick_distinct_bone(
        lhand_cands, lh_tx, lh_ty, forbid_re=not_hand_re, y_bounds=hand_y_bounds,
        exclude_head_zone=True, min_dist_from=hand_excl, allow_named_hand=True,
    )
    if math.hypot(lh_vx - em_head_x, lh_vy - em_head_y) < 0.16 * char_h and lh_vy > em_head_y - 0.12 * char_h:
        lh_vx, lh_vy = lh_tx, lh_ty
    em_lh_x, em_lh_y = _emit_hit("左手", "左手", lh_b, lh_vx, lh_vy, 1.6, 1.6)

    rh_b, rh_vx, rh_vy = _pick_distinct_bone(
        rhand_cands, rh_tx, rh_ty, forbid_re=not_hand_re, y_bounds=hand_y_bounds,
        exclude_head_zone=True, min_dist_from=hand_excl, allow_named_hand=True,
    )
    if math.hypot(rh_vx - em_head_x, rh_vy - em_head_y) < 0.16 * char_h and rh_vy > em_head_y - 0.12 * char_h:
        rh_vx, rh_vy = rh_tx, rh_ty
    em_rh_x, em_rh_y = _emit_hit("右手", "右手", rh_b, rh_vx, rh_vy, 1.6, 1.6)

    # D. Legs (`腿`) — strictly below chest (`< em_chest_y - 0.12*H`) and above feet (`> c_y0 + 0.18*H`)
    leg_re = re.compile(r"(datui|xiaotui|neitui|waitui|zuotui|youtui|[lr]_tui|tui\d|[lr]_leg|leg\d|thigh|knee|qunzi|skirt)", re.I)
    not_leg_re = re.compile(
        r"(tou|houfa|qianfa|toufa|liuhai|toushi|lian|face|head|yan|meimao|zui|bizi|xiong|shou|hand|bi\d|arm|"
        r"pifeng|youting|hua\d|hudiejie|piaodai|yaodai|shiping|lingdang|weiba|bj|beijing)",
        re.I,
    )
    leg_y_lo = c_y0 + 0.18 * char_h
    leg_y_hi = min(em_chest_y - 0.11 * char_h, c_y0 + 0.56 * char_h)
    if leg_y_hi <= leg_y_lo:
        leg_y_lo = c_y0 + 0.14 * char_h
        leg_y_hi = max(leg_y_lo + 20.0, em_chest_y - 0.08 * char_h)
    leg_tx = char_mid_x
    leg_ty = c_y0 + (0.42 if is_battlehead_orig else 0.32) * char_h
    leg_ty = max(leg_y_lo, min(leg_y_hi, leg_ty))

    leg_cands = [
        b for b in char_bones
        if leg_re.search(b) and not not_leg_re.search(b) and b not in head_sub
        and (leg_y_lo <= vpos(b)[1] <= leg_y_hi)
    ]
    if not leg_cands:
        # In z_rig (BattleHead), z3 and z5 are the exact thigh bones!
        z_thighs = [b for b in ("z3", "z5") if b in active_deform_bones and leg_y_lo <= vpos(b)[1] <= leg_y_hi]
        if z_thighs:
            leg_cands = z_thighs
        else:
            leg_cands = [
                b for b in active_deform_bones
                if b not in used_bones and not not_leg_re.search(b) and b not in head_sub
                and (leg_y_lo <= vpos(b)[1] <= leg_y_hi)
            ]

    leg_b, leg_vx, leg_vy = _pick_distinct_bone(
        leg_cands, leg_tx, leg_ty, forbid_re=not_leg_re,
        y_bounds=(leg_y_lo, leg_y_hi), exclude_head_zone=True,
        min_dist_from=[
            (em_head_x, em_head_y, 0.20 * char_h),
            (em_chest_x, em_chest_y, 0.10 * char_h),
            (em_lh_x, em_lh_y, 0.08 * char_h),
            (em_rh_x, em_rh_y, 0.08 * char_h),
        ],
    )
    leg_vy = min(leg_vy, em_chest_y - 0.11 * char_h)
    em_leg_x, em_leg_y = _emit_hit("腿", "腿", leg_b, leg_vx, leg_vy, 3.0, 2.8, max_off_mult=6.5)

    # E. Feet (`足`) — strictly below legs (`<= em_leg_y - 0.06*H`)
    foot_re = re.compile(r"(zuojiao|youjiao|[lr]_jiao|^jiao\d*$|[lr]_foot|^foot\d*$|shoe|xie|ankle|jiaozhi)", re.I)
    not_foot_re = re.compile(
        r"(zui|zuiba|bizui|zuoshou|zuobi|zuodabi|zuoxiaobi|zuoxiu|zuoyan|zuomei|zuojiemao|"
        r"tou|houfa|qianfa|toufa|liuhai|toushi|lian|face|head|yan|meimao|xiong|shou|hand|qun|weisha|fasheng|guazhui|"
        r"hua\d|hudiejie|pifeng|piaodai|yaodai|shiping|lingdang|weiba|bj|beijing|^root$)",
        re.I,
    )
    foot_y_hi = em_leg_y - 0.06 * char_h
    foot_tx = char_mid_x
    foot_ty = c_y0 + 0.07 * char_h

    foot_cands = [
        b for b in char_bones
        if foot_re.search(b) and not not_foot_re.search(b) and b not in head_sub
        and vpos(b)[1] <= foot_y_hi
    ]
    has_named_foot = bool(foot_cands)
    if not foot_cands:
        low_bones = sorted(
            [
                b for b in active_deform_bones
                if b not in used_bones and not not_foot_re.search(b) and b not in head_sub
                and vpos(b)[1] <= foot_y_hi
            ],
            key=lambda b: vpos(b)[1],
        )
        foot_cands = low_bones[:4]

    foot_b, foot_vx, foot_vy = _pick_distinct_bone(
        foot_cands, foot_tx, foot_ty, forbid_re=not_foot_re,
        y_bounds=(c_y0 - 50.0, foot_y_hi), exclude_head_zone=True,
        min_dist_from=[
            (em_head_x, em_head_y, 0.25 * char_h),
            (em_chest_x, em_chest_y, 0.16 * char_h),
            (em_leg_x, em_leg_y, 0.07 * char_h),
            (em_lh_x, em_lh_y, 0.07 * char_h),
            (em_rh_x, em_rh_y, 0.07 * char_h),
        ],
    )
    # If the chosen foot bone is a knee/shin joint whose own rendered vertex bbox extends far from its joint
    # (like bone19 in 月本柚/明媚之约), push the box center toward the distal end of its vertex bbox!
    fb = bone_by_name[foot_b]
    if not has_named_foot and fb.get("vw", 0) > 0:
        vx0, vx1 = float(fb["vx0"]), float(fb["vx1"])
        vy0, vy1 = float(fb["vy0"]), float(fb["vy1"])
        bw_v, bh_v = vx1 - vx0, vy1 - vy0
        dist_right = abs(vx1 - fb["wx"])
        dist_left = abs(vx0 - fb["wx"])
        dist_down = abs(vy0 - fb["wy"])
        if max(dist_right, dist_left) > max(200.0, dist_down * 1.4):
            foot_vx = (vx0 + 0.78 * bw_v) if dist_right >= dist_left else (vx0 + 0.22 * bw_v)
            foot_vy = vy0 + 0.35 * bh_v
        elif bh_v > 260.0 and dist_down > 180.0:
            foot_vx = float(fb["vcx"])
            foot_vy = vy0 + 0.20 * bh_v

    foot_vy = min(foot_vy, em_leg_y - 0.06 * char_h)
    _emit_hit("足", "足", foot_b, foot_vx, foot_vy, 2.5, 1.6, max_off_mult=8.5)

    return hit_areas


def _is_backup_hit_areas_clean(
    bkp_ha: list[dict[str, Any]],
    geom: dict[str, Any],
    motions: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    """Validate manual backup hit_areas: bones exist, non-BG, unique IDs, AND pass geometric audit."""
    bone_names = {b["name"] for b in geom["bones"]}
    cleaned: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for ha in bkp_ha:
        bid = str(ha.get("id", ""))
        mot = str(ha.get("motion", ""))
        if bid not in bone_names or _is_bg_token(bid) or bid in seen_ids:
            return False, []
        if mot == "身体":
            mot = "胸"
        if mot not in motions:
            mot = "闲聊与问答" if "闲聊与问答" in motions else ("头" if "头" in motions else next(iter(motions)))
        seen_ids.add(bid)
        nha: dict[str, Any] = {
            "name": ha.get("name", mot),
            "id": bid,
            "motion": mot,
            "width": float(ha.get("width", 1.5)),
            "height": float(ha.get("height", 1.5)),
        }
        if "center_x" in ha:
            nha["center_x"] = float(ha["center_x"])
        if "center_y" in ha:
            nha["center_y"] = float(ha["center_y"])
        cleaned.append(nha)
    if len(cleaned) < 3:
        return False, []
    # Reject backup hit_areas if they fail the geometric sanity check!
    geom_probs = _check_hit_areas_geometry(cleaned, geom)
    if geom_probs:
        return False, []
    return True, cleaned


ORIG_VOICE_ONLY_GROUPS = ("头", "胸", "左手", "右手", "腿", "足", "闲聊与问答")


def _apply_orig_spine_voice_only(motions: dict[str, Any]) -> None:
    """For 原皮* Spine models, make touch & chat triggers play voice+subtitle ONLY (file='') without triggering battle animations."""
    idle_list = motions.get("idle") or []
    idle_anim = idle_list[0].get("file", "idle") if idle_list else "idle"
    for grp in ORIG_VOICE_ONLY_GROUPS:
        items = motions.get(grp)
        if not items:
            continue
        for item in items:
            item["file"] = ""
            item.pop("fade_in", None)
            item.pop("fade_out", None)
    # Keep start greeting smooth in idle instead of triggering combat 'action'
    for item in motions.get("start") or []:
        item["file"] = idle_anim


def fix_all_spine_packages() -> dict[str, Any]:
    print("[Spine] Loading Spine3_8 per-bone weighted vertex geometry across all 170 packages...", flush=True)
    all_geoms = _extract_all_spine38_geometries()
    bkp_map = _index_backup_spine_hit_areas()

    used_clean_backup = 0
    solved_anatomical = 0
    orig_voice_only_updated = 0

    for cfg_p in sorted(SPINE_ROOT.glob("*/*/.config.json")):
        skin_dir = cfg_p.parent
        char_nm = skin_dir.parent.name
        dress_nm = skin_dir.name
        rel = f"{char_nm}/{dress_nm}"
        is_orig = dress_nm.startswith("原皮")

        geom = all_geoms.get(rel)
        if not geom:
            raise KeyError(f"Missing extracted Spine3_8 geometry for {rel}")

        lang_files = [
            skin_dir / ".config.json",
            skin_dir / "config_en.config.json",
            skin_dir / "config_ja.config.json",
        ]
        lang_dicts = [json.loads(p.read_text(encoding="utf-8")) for p in lang_files if p.is_file()]
        motions = lang_dicts[0]["motions"]

        bkp_ha = bkp_map.get((char_nm, dress_nm))
        ok_bkp, clean_ha = _is_backup_hit_areas_clean(bkp_ha, geom, motions) if bkp_ha else (False, [])
        if ok_bkp:
            final_ha = clean_ha
            used_clean_backup += 1
        else:
            final_ha = solve_spine_anatomical_hit_areas(geom, motions, is_battlehead_orig=is_orig)
            solved_anatomical += 1

        if is_orig:
            orig_voice_only_updated += 1

        for lp, ld in zip([p for p in lang_files if p.is_file()], lang_dicts):
            ld["hit_areas"] = final_ha
            if is_orig:
                _apply_orig_spine_voice_only(ld["motions"])
            write_json(lp, ld)

    print(
        f"[Spine] Updated 170 packages: clean_manual_backup={used_clean_backup}, "
        f"anatomical_mesh_solved={solved_anatomical}, orig_voice_only={orig_voice_only_updated}",
        flush=True,
    )
    return {
        "total_spine": len(all_geoms),
        "clean_manual_backup": used_clean_backup,
        "anatomical_mesh_solved": solved_anatomical,
        "orig_voice_only_updated": orig_voice_only_updated,
    }


def main() -> None:
    l2d_res = fix_all_live2d_packages()
    sp_res = fix_all_spine_packages()
    report = {
        "live2d": l2d_res,
        "spine": sp_res,
    }
    write_json(REPORT_PATH, report)
    print(f"[TouchTriggerFix] ALL DONE -> {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    main()
