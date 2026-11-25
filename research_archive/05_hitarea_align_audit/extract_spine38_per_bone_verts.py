import json
import subprocess
import tempfile
from pathlib import Path

CACHE_PATH = Path(r"E:\A灵魂潮汐\tools\_spine38_geom_cache.json")

PS_EXTRACTOR = r"""
param([string]$OutJsonPath)
$ErrorActionPreference = "Stop"
[System.Reflection.Assembly]::LoadFrom("C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed\Assembly-CSharp.dll") | Out-Null
$code = @"
using System;
using System.Collections.Generic;
using Spine3_8;

public class DummyTexLoaderV2 : TextureLoader {
    public void Load(AtlasPage page, string path) {
        page.rendererObject = path;
        if (page.width == 0) page.width = 2048;
        if (page.height == 0) page.height = 2048;
    }
    public void Unload(object texture) {}
}

public class BoneVertAccum {
    public double WSum = 0;
    public double Sx = 0;
    public double Sy = 0;
    public double X0 = 1e9;
    public double X1 = -1e9;
    public double Y0 = 1e9;
    public double Y1 = -1e9;
    public void Add(double x, double y, double w) {
        WSum += w;
        Sx += x * w;
        Sy += y * w;
        if (x < X0) X0 = x;
        if (x > X1) X1 = x;
        if (y < Y0) Y0 = y;
        if (y > Y1) Y1 = y;
    }
}

public static class SpineGeomHelper {
    public static Dictionary<int, BoneVertAccum> ComputeBoneVerts(Skeleton sk, out List<Dictionary<string, object>> slotsOut) {
        Dictionary<int, BoneVertAccum> acc = new Dictionary<int, BoneVertAccum>();
        slotsOut = new List<Dictionary<string, object>>();
        float[] verts = new float[8000];
        Bone[] skBones = sk.Bones.Items;
        int boneCount = sk.Bones.Count;
        Dictionary<Bone, int> boneIndexByRef = new Dictionary<Bone, int>();
        for (int bi = 0; bi < boneCount; bi++) boneIndexByRef[skBones[bi]] = bi;

        foreach (Slot slot in sk.DrawOrder) {
            Attachment att = slot.Attachment;
            if (att == null || slot.A <= 0.05f) continue;
            int cnt = 0;
            List<string> wBones = new List<string>();
            HashSet<int> seenB = new HashSet<int>();

            MeshAttachment ma = att as MeshAttachment;
            RegionAttachment ra = att as RegionAttachment;
            if (ma != null) {
                cnt = ma.WorldVerticesLength;
                if (cnt > verts.Length) verts = new float[cnt];
                ma.ComputeWorldVertices(slot, 0, cnt, verts, 0, 2);

                if (ma.Bones != null && ma.Bones.Length > 0) {
                    int[] mb = ma.Bones;
                    float[] mv = ma.Vertices;
                    int vi = 0;
                    int biPtr = 0;
                    for (int w = 0; w < cnt; w += 2) {
                        double wx = verts[w];
                        double wy = verts[w + 1];
                        int nb = mb[vi++];
                        for (int j = 0; j < nb; j++) {
                            int bIdx = mb[vi++];
                            float weight = mv[biPtr + 2];
                            biPtr += 3;
                            if (bIdx >= 0 && bIdx < boneCount) {
                                if (seenB.Add(bIdx)) wBones.Add(skBones[bIdx].Data.Name);
                                if (weight >= 0.15f) {
                                    BoneVertAccum ba;
                                    if (!acc.TryGetValue(bIdx, out ba)) {
                                        ba = new BoneVertAccum();
                                        acc[bIdx] = ba;
                                    }
                                    ba.Add(wx, wy, weight);
                                }
                            }
                        }
                    }
                } else {
                    int bIdx = boneIndexByRef[slot.Bone];
                    wBones.Add(slot.Bone.Data.Name);
                    BoneVertAccum ba;
                    if (!acc.TryGetValue(bIdx, out ba)) {
                        ba = new BoneVertAccum();
                        acc[bIdx] = ba;
                    }
                    for (int w = 0; w < cnt; w += 2) ba.Add(verts[w], verts[w + 1], 1.0);
                }
            } else if (ra != null) {
                cnt = 8;
                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2);
                int bIdx = boneIndexByRef[slot.Bone];
                wBones.Add(slot.Bone.Data.Name);
                BoneVertAccum ba;
                if (!acc.TryGetValue(bIdx, out ba)) {
                    ba = new BoneVertAccum();
                    acc[bIdx] = ba;
                }
                for (int w = 0; w < cnt; w += 2) ba.Add(verts[w], verts[w + 1], 1.0);
            }

            if (cnt > 0) {
                double minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9;
                for (int i = 0; i < cnt; i += 2) {
                    double vx = verts[i], vy = verts[i + 1];
                    if (vx < minX) minX = vx;
                    if (vx > maxX) maxX = vx;
                    if (vy < minY) minY = vy;
                    if (vy > maxY) maxY = vy;
                }
                Dictionary<string, object> sDict = new Dictionary<string, object>();
                sDict["name"] = slot.Data.Name;
                sDict["att"] = att.Name;
                sDict["bone"] = slot.Bone.Data.Name;
                sDict["wbones"] = wBones;
                sDict["cx"] = Math.Round((minX + maxX) / 2.0, 2);
                sDict["cy"] = Math.Round((minY + maxY) / 2.0, 2);
                sDict["w"] = Math.Round(maxX - minX, 2);
                sDict["h"] = Math.Round(maxY - minY, 2);
                sDict["x0"] = Math.Round(minX, 2);
                sDict["x1"] = Math.Round(maxX, 2);
                sDict["y0"] = Math.Round(minY, 2);
                sDict["y1"] = Math.Round(maxY, 2);
                slotsOut.Add(sDict);
            }
        }
        return acc;
    }
}
"@
Add-Type -TypeDefinition $code -ReferencedAssemblies "C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed\Assembly-CSharp.dll"

$root = "E:\A灵魂潮汐\Live2D与Spine模型\spine"
$cfgs = Get-ChildItem -Path "$root\*\*\*" -Force | Where-Object { $_.Name -eq ".config.json" } | Sort-Object FullName
$allData = @{}
$texLoader = New-Object DummyTexLoaderV2

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

    $slotsList = $null
    $bvMap = [SpineGeomHelper]::ComputeBoneVerts($sk, [ref]$slotsList)

    $bonesList = New-Object System.Collections.ArrayList
    for ($bi = 0; $bi -lt $sk.Bones.Count; $bi++) {
        $b = $sk.Bones.Items[$bi]
        $pName = if ($null -ne $b.Parent) { $b.Parent.Data.Name } else { "" }
        $bObj = @{
            idx = $bi
            name = $b.Data.Name
            parent = $pName
            wx = [math]::Round([double]$b.WorldX, 2)
            wy = [math]::Round([double]$b.WorldY, 2)
            len = [math]::Round([double]$b.Data.Length, 2)
        }
        if ($bvMap.ContainsKey($bi)) {
            $ba = $bvMap[$bi]
            $bObj["vw"] = [math]::Round($ba.WSum, 1)
            $bObj["vcx"] = [math]::Round($ba.Sx / $ba.WSum, 2)
            $bObj["vcy"] = [math]::Round($ba.Sy / $ba.WSum, 2)
            $bObj["vx0"] = [math]::Round($ba.X0, 2)
            $bObj["vx1"] = [math]::Round($ba.X1, 2)
            $bObj["vy0"] = [math]::Round($ba.Y0, 2)
            $bObj["vy1"] = [math]::Round($ba.Y1, 2)
        }
        [void]$bonesList.Add($bObj)
    }

    $allData[$rel] = @{
        bones = $bonesList
        slots = $slotsList
    }
}

$jsonStr = $allData | ConvertTo-Json -Depth 7 -Compress
[System.IO.File]::WriteAllText($OutJsonPath, $jsonStr, [System.Text.Encoding]::UTF8)
Write-Output ("Extracted " + $allData.Count + " Spine geometries to " + $OutJsonPath)
"""

with tempfile.TemporaryDirectory(prefix="spine38_v2_") as td:
    ps_file = Path(td) / "extract_v2.ps1"
    ps_file.write_text(PS_EXTRACTOR, encoding="utf-8-sig")
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_file), "-OutJsonPath", str(CACHE_PATH)],
        capture_output=True,
        text=True,
    )
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr)
        raise SystemExit(r.returncode)
