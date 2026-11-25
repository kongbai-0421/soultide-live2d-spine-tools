"""Fast Spine3_8 Textured Visual Preview Renderer for Touch Trigger Calibration.

Compiles & invokes a lightweight C# (.NET Framework 4.x) rasterizer backed by
Live2DViewerEX's `Spine3_8` runtime (`Assembly-CSharp.dll`) to render every visible
`RegionAttachment` and `MeshAttachment` in `Skeleton.DrawOrder` at `idle` frame 0,
overlay the Spine world-coordinate grid/ruler and `hit_areas` collider boxes,
and emit `manifest.json` with 4 balanced disjoint shards.

Usage:
    python render_spine_touch_previews.py                # Render all 163 + emit manifest.json
    python render_spine_touch_previews.py --only 伊汐尔/原皮  # Re-render single skin (< 1s)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
OUT_DIR = TOOLS_DIR / "_touch_audit_previews"
GEOM_CACHE_PATH = TOOLS_DIR / "_spine38_geom_cache.json"
MANIFEST_PATH = OUT_DIR / "manifest.json"
CS_PATH = TOOLS_DIR / "_spine38_preview_renderer.cs"
EXE_PATH = TOOLS_DIR / "_spine38_preview_renderer.exe"
HASH_PATH = TOOLS_DIR / "_spine38_preview_renderer.sha256"

CSC_EXE = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
EX_MANAGED_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed")

READONLY_MODELS: set[str] = set()

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

CS_SOURCE = r'''using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Spine3_8;

public class LoadedTex {
    public int W;
    public int H;
    public byte[] Bgra;
}

public class BitmapTexLoader : TextureLoader {
    [DllImport(@"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Plugins\x86_64\libwebp.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern IntPtr WebPDecodeBGRA(byte[] data, UIntPtr data_size, out int width, out int height);
    [DllImport(@"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Plugins\x86_64\libwebp.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern void WebPFree(IntPtr ptr);

    public void Load(AtlasPage page, string path) {
        if (!File.Exists(path)) {
            page.rendererObject = null;
            return;
        }
        if (path.EndsWith(".webp", StringComparison.OrdinalIgnoreCase)) {
            byte[] raw = File.ReadAllBytes(path);
            int w, h;
            IntPtr ptr = WebPDecodeBGRA(raw, (UIntPtr)raw.Length, out w, out h);
            if (ptr == IntPtr.Zero || w <= 0 || h <= 0) {
                page.rendererObject = null;
                return;
            }
            try {
                byte[] buf = new byte[w * h * 4];
                Marshal.Copy(ptr, buf, 0, buf.Length);
                page.rendererObject = new LoadedTex { W = w, H = h, Bgra = buf };
            } finally {
                WebPFree(ptr);
            }
            return;
        }
        using (var src = new Bitmap(path))
        using (var bmp = new Bitmap(src.Width, src.Height, PixelFormat.Format32bppArgb)) {
            using (var g = Graphics.FromImage(bmp)) {
                g.CompositingMode = CompositingMode.SourceCopy;
                g.DrawImage(src, 0, 0, src.Width, src.Height);
            }
            var rect = new Rectangle(0, 0, bmp.Width, bmp.Height);
            var bd = bmp.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            int stride = Math.Abs(bd.Stride);
            byte[] buf = new byte[bmp.Width * bmp.Height * 4];
            if (bd.Stride == bmp.Width * 4) {
                Marshal.Copy(bd.Scan0, buf, 0, buf.Length);
            } else {
                for (int y = 0; y < bmp.Height; y++) {
                    Marshal.Copy(IntPtr.Add(bd.Scan0, y * bd.Stride), buf, y * bmp.Width * 4, bmp.Width * 4);
                }
            }
            bmp.UnlockBits(bd);
            page.rendererObject = new LoadedTex { W = bmp.Width, H = bmp.Height, Bgra = buf };
        }
    }
    public void Unload(object texture) { }
}

class DrawTri {
    public LoadedTex Tex;
    public float X0, Y0, U0, V0;
    public float X1, Y1, U1, V1;
    public float X2, Y2, U2, V2;
    public float R, G, B, A;
    public BlendMode Blend;
}

class HitBoxInfo {
    public string Name;
    public string BoneId;
    public string Motion;
    public float BoxCx, BoxCy, BoxW, BoxH;
    public float BoneWx, BoneWy;
    public bool BoneFound;
}

class Program {
    static readonly string ManagedDir = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";

    static int Main(string[] args) {
        AppDomain.CurrentDomain.AssemblyResolve += (sender, eventArgs) => {
            string name = new AssemblyName(eventArgs.Name).Name + ".dll";
            string candidate = Path.Combine(ManagedDir, name);
            if (File.Exists(candidate)) return Assembly.LoadFrom(candidate);
            return null;
        };
        return Run(args);
    }

    static int Run(string[] args) {
        string mode = "";
        string onlyRel = "";
        string spineRoot = "";
        string outDir = "";

        for (int i = 0; i < args.Length; i++) {
            if (args[i] == "--all") mode = "all";
            else if (args[i] == "--only" && i + 1 < args.Length) { mode = "only"; onlyRel = args[++i].Replace('\\', '/'); }
            else if (args[i] == "--spine-root" && i + 1 < args.Length) spineRoot = args[++i];
            else if (args[i] == "--out-dir" && i + 1 < args.Length) outDir = args[++i];
        }
        if (string.IsNullOrEmpty(spineRoot) || string.IsNullOrEmpty(outDir) || string.IsNullOrEmpty(mode)) {
            Console.Error.WriteLine("Usage: --all|--only <rel> --spine-root <dir> --out-dir <dir>");
            return 2;
        }
        Directory.CreateDirectory(outDir);

        var cfgPaths = new List<string>();
        foreach (var charDir in Directory.GetDirectories(spineRoot)) {
            foreach (var skinDir in Directory.GetDirectories(charDir)) {
                string cp = Path.Combine(skinDir, ".config.json");
                if (File.Exists(cp)) cfgPaths.Add(cp);
            }
        }
        var items = new List<Tuple<int, string, string>>();
        var relList = new List<Tuple<string, string>>();
        foreach (var cp in cfgPaths) {
            string dir = Path.GetDirectoryName(cp);
            string rel = dir.Substring(spineRoot.TrimEnd('\\', '/').Length + 1).Replace('\\', '/');
            relList.Add(Tuple.Create(rel, dir));
        }
        relList.Sort((a, b) => StringComparer.Ordinal.Compare(a.Item1, b.Item1));
        for (int i = 0; i < relList.Count; i++) {
            items.Add(Tuple.Create(i + 1, relList[i].Item1, relList[i].Item2));
        }

        if (mode == "only") {
            Tuple<int, string, string> target = null;
            foreach (var it in items) {
                if (it.Item2 == onlyRel) { target = it; break; }
            }
            if (target == null) {
                Console.Error.WriteLine("Model not found: " + onlyRel);
                return 3;
            }
            var sw = Stopwatch.StartNew();
            string outPath = RenderOne(target.Item1, target.Item2, target.Item3, outDir);
            sw.Stop();
            Console.WriteLine("OK " + target.Item2 + " -> " + outPath + " (" + sw.ElapsedMilliseconds + " ms)");
            return 0;
        }

        var swAll = Stopwatch.StartNew();
        int done = 0;
        var errors = new List<string>();
        object lockObj = new object();
        Parallel.ForEach(items, new ParallelOptions { MaxDegreeOfParallelism = Math.Max(1, Math.Min(6, Environment.ProcessorCount)) }, it => {
            try {
                RenderOne(it.Item1, it.Item2, it.Item3, outDir);
                lock (lockObj) {
                    done++;
                    if (done % 25 == 0 || done == items.Count) {
                        Console.WriteLine("Rendered " + done + "/" + items.Count);
                    }
                }
            } catch (Exception ex) {
                lock (lockObj) {
                    errors.Add(it.Item2 + ": " + ex.Message);
                }
            }
        });
        swAll.Stop();
        if (errors.Count > 0) {
            foreach (var e in errors) Console.Error.WriteLine("ERR: " + e);
            return 1;
        }
        Console.WriteLine("ALL DONE count=" + items.Count + " in " + swAll.ElapsedMilliseconds + " ms");
        return 0;
    }

    static float ToFloat(object obj, float defVal) {
        if (obj == null) return defVal;
        return Convert.ToSingle(obj);
    }

    static string RenderOne(int index, string rel, string dir, string outDir) {
        string cfgText = File.ReadAllText(Path.Combine(dir, ".config.json"), Encoding.UTF8);
        var jss = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 };
        var cfg = jss.Deserialize<Dictionary<string, object>>(cfgText);

        string skelRel = Convert.ToString(cfg["skeleton"]);
        var atlases = (System.Collections.ArrayList)cfg["atlases"];
        var atlasDict = (Dictionary<string, object>)atlases[0];
        string atlasRel = Convert.ToString(atlasDict["atlas"]);

        string skelPath = Path.Combine(dir, skelRel);
        string atlasPath = Path.Combine(dir, atlasRel);

        var texLoader = new BitmapTexLoader();
        Atlas atlas;
        using (var sr = new StreamReader(atlasPath, Encoding.UTF8)) {
            atlas = new Atlas(sr, dir, texLoader);
        }

        bool isJson = false;
        using (var fs = File.OpenRead(skelPath)) {
            byte[] hdr = new byte[32];
            int n = fs.Read(hdr, 0, hdr.Length);
            for (int i = 0; i < n; i++) {
                byte b = hdr[i];
                if (b == ' ' || b == '\t' || b == '\r' || b == '\n') continue;
                if (b == 0xEF || b == 0xBB || b == 0xBF) continue;
                isJson = (b == '{');
                break;
            }
        }

        SkeletonData sd;
        var attLoader = new AtlasAttachmentLoader(atlas);
        if (isJson) {
            var sj = new SkeletonJson(attLoader);
            sd = sj.ReadSkeletonData(skelPath);
        } else {
            var sb = new SkeletonBinary(attLoader);
            sd = sb.ReadSkeletonData(skelPath);
        }

        var sk = new Skeleton(sd);
        string idleName = "";
        var motions = cfg.ContainsKey("motions") ? cfg["motions"] as Dictionary<string, object> : null;
        if (motions != null && motions.ContainsKey("idle")) {
            var idleArr = motions["idle"] as System.Collections.ArrayList;
            if (idleArr != null && idleArr.Count > 0) {
                var firstIdle = idleArr[0] as Dictionary<string, object>;
                if (firstIdle != null && firstIdle.ContainsKey("file")) idleName = Convert.ToString(firstIdle["file"]);
            }
        }
        if (!string.IsNullOrEmpty(idleName)) {
            var anim = sd.FindAnimation(idleName);
            if (anim != null) anim.Apply(sk, 0, 0, true, null, 1.0f, MixBlend.Setup, MixDirection.In);
        }
        sk.UpdateWorldTransform();

        var boneMap = new Dictionary<string, Bone>();
        for (int i = 0; i < sk.Bones.Count; i++) {
            var b = sk.Bones.Items[i];
            boneMap[b.Data.Name] = b;
        }

        var tris = new List<DrawTri>();
        float minX = 1e9f, maxX = -1e9f, minY = 1e9f, maxY = -1e9f;
        float[] verts = new float[8192];

        foreach (var slot in sk.DrawOrder) {
            var att = slot.Attachment;
            if (att == null || slot.A <= 0.01f || !slot.Bone.Active) continue;
            var blend = slot.Data.BlendMode;

            if (att is RegionAttachment) {
                var ra = (RegionAttachment)att;
                var ar = ra.RendererObject as AtlasRegion;
                if (ar == null || ar.page == null) continue;
                var tex = ar.page.rendererObject as LoadedTex;
                if (tex == null) continue;
                float sa = slot.A * ra.A;
                if (sa <= 0.01f) continue;
                float sr = slot.R * ra.R;
                float sg = slot.G * ra.G;
                float sb = slot.B * ra.B;

                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2);
                float[] uvs = ra.UVs;
                for (int k = 0; k < 4; k++) {
                    float vx = verts[k * 2], vy = verts[k * 2 + 1];
                    if (vx < minX) minX = vx; if (vx > maxX) maxX = vx;
                    if (vy < minY) minY = vy; if (vy > maxY) maxY = vy;
                }
                tris.Add(new DrawTri {
                    Tex = tex, Blend = blend, R = sr, G = sg, B = sb, A = sa,
                    X0 = verts[0], Y0 = verts[1], U0 = uvs[0], V0 = uvs[1],
                    X1 = verts[2], Y1 = verts[3], U1 = uvs[2], V1 = uvs[3],
                    X2 = verts[4], Y2 = verts[5], U2 = uvs[4], V2 = uvs[5]
                });
                tris.Add(new DrawTri {
                    Tex = tex, Blend = blend, R = sr, G = sg, B = sb, A = sa,
                    X0 = verts[0], Y0 = verts[1], U0 = uvs[0], V0 = uvs[1],
                    X1 = verts[4], Y1 = verts[5], U1 = uvs[4], V1 = uvs[5],
                    X2 = verts[6], Y2 = verts[7], U2 = uvs[6], V2 = uvs[7]
                });
            } else if (att is MeshAttachment) {
                var ma = (MeshAttachment)att;
                var ar = ma.RendererObject as AtlasRegion;
                if (ar == null || ar.page == null) continue;
                var tex = ar.page.rendererObject as LoadedTex;
                if (tex == null) continue;
                float sa = slot.A * ma.A;
                if (sa <= 0.01f) continue;
                float sr = slot.R * ma.R;
                float sg = slot.G * ma.G;
                float sb = slot.B * ma.B;

                int cnt = ma.WorldVerticesLength;
                if (cnt <= 0) continue;
                if (cnt > verts.Length) verts = new float[cnt * 2];
                ma.ComputeWorldVertices(slot, 0, cnt, verts, 0, 2);
                int nv = cnt / 2;
                float[] uvs = ma.UVs;
                int[] indices = ma.Triangles;
                for (int k = 0; k < nv; k++) {
                    float vx = verts[k * 2], vy = verts[k * 2 + 1];
                    if (vx < minX) minX = vx; if (vx > maxX) maxX = vx;
                    if (vy < minY) minY = vy; if (vy > maxY) maxY = vy;
                }
                for (int t = 0; t + 2 < indices.Length; t += 3) {
                    int i0 = indices[t], i1 = indices[t + 1], i2 = indices[t + 2];
                    if (i0 >= nv || i1 >= nv || i2 >= nv) continue;
                    tris.Add(new DrawTri {
                        Tex = tex, Blend = blend, R = sr, G = sg, B = sb, A = sa,
                        X0 = verts[i0 * 2], Y0 = verts[i0 * 2 + 1], U0 = uvs[i0 * 2], V0 = uvs[i0 * 2 + 1],
                        X1 = verts[i1 * 2], Y1 = verts[i1 * 2 + 1], U1 = uvs[i1 * 2], V1 = uvs[i1 * 2 + 1],
                        X2 = verts[i2 * 2], Y2 = verts[i2 * 2 + 1], U2 = uvs[i2 * 2], V2 = uvs[i2 * 2 + 1]
                    });
                }
            }
        }

        var hitBoxes = new List<HitBoxInfo>();
        if (cfg.ContainsKey("hit_areas") && cfg["hit_areas"] is System.Collections.ArrayList) {
            var haArr = (System.Collections.ArrayList)cfg["hit_areas"];
            foreach (Dictionary<string, object> ha in haArr) {
                string name = ha.ContainsKey("name") ? Convert.ToString(ha["name"]) : "";
                string bid = ha.ContainsKey("id") ? Convert.ToString(ha["id"]) : "";
                string mot = ha.ContainsKey("motion") ? Convert.ToString(ha["motion"]) : name;
                float w = ToFloat(ha.ContainsKey("width") ? ha["width"] : null, 1.5f) * 100f;
                float h = ToFloat(ha.ContainsKey("height") ? ha["height"] : null, 1.5f) * 100f;
                float cxOff = ToFloat(ha.ContainsKey("center_x") ? ha["center_x"] : null, 0f) * 100f;
                float cyOff = ToFloat(ha.ContainsKey("center_y") ? ha["center_y"] : null, 0f) * 100f;

                Bone b;
                bool found = boneMap.TryGetValue(bid, out b);
                float bwx = found ? b.WorldX : 0f;
                float bwy = found ? b.WorldY : 0f;
                float bcx = bwx + cxOff;
                float bcy = bwy + cyOff;
                hitBoxes.Add(new HitBoxInfo {
                    Name = name, BoneId = bid, Motion = mot,
                    BoxCx = bcx, BoxCy = bcy, BoxW = w, BoxH = h,
                    BoneWx = bwx, BoneWy = bwy, BoneFound = found
                });
                if (found) {
                    if (bcx - w * 0.5f < minX) minX = bcx - w * 0.5f;
                    if (bcx + w * 0.5f > maxX) maxX = bcx + w * 0.5f;
                    if (bcy - h * 0.5f < minY) minY = bcy - h * 0.5f;
                    if (bcy + h * 0.5f > maxY) maxY = bcy + h * 0.5f;
                }
            }
        }

        if (minX > maxX) { minX = -500; maxX = 500; minY = 0; maxY = 1000; }
        float spanW = Math.Max(200f, maxX - minX);
        float spanH = Math.Max(200f, maxY - minY);
        float padW = Math.Max(60f, spanW * 0.06f);
        float padH = Math.Max(60f, spanH * 0.06f);
        minX -= padW; maxX += padW;
        minY -= padH; maxY += padH;
        spanW = maxX - minX;
        spanH = maxY - minY;

        const int marginLeft = 52;
        const int marginRight = 14;
        const int marginTop = 32;
        const int marginBottom = 36;
        const int maxTotal = 760;
        int maxPlotW = maxTotal - marginLeft - marginRight;
        int maxPlotH = maxTotal - marginTop - marginBottom;

        float scale = Math.Min((maxPlotW - 1) / spanW, (maxPlotH - 1) / spanH);
        int plotW = Math.Max(120, Math.Min(maxPlotW, (int)Math.Floor(spanW * scale)));
        int plotH = Math.Max(120, Math.Min(maxPlotH, (int)Math.Floor(spanH * scale)));
        int minTotalW = 400;
        int imgW = Math.Max(minTotalW, plotW + marginLeft + marginRight);
        int imgH = plotH + marginTop + marginBottom;
        float extraLeft = (imgW - marginLeft - marginRight - plotW) * 0.5f;

        byte[] canvas = new byte[imgW * imgH * 4];
        // Initialize dark slate background (#262A34) + subtle checkerboard in plot area
        for (int y = 0; y < imgH; y++) {
            for (int x = 0; x < imgW; x++) {
                int idx = (y * imgW + x) * 4;
                bool inPlot = (x >= marginLeft && x < imgW - marginRight && y >= marginTop && y < imgH - marginBottom);
                if (inPlot) {
                    bool chk = (((x / 16) + (y / 16)) & 1) == 0;
                    canvas[idx + 0] = (byte)(chk ? 52 : 44);
                    canvas[idx + 1] = (byte)(chk ? 42 : 36);
                    canvas[idx + 2] = (byte)(chk ? 38 : 32);
                    canvas[idx + 3] = 255;
                } else {
                    canvas[idx + 0] = 36;
                    canvas[idx + 1] = 28;
                    canvas[idx + 2] = 24;
                    canvas[idx + 3] = 255;
                }
            }
        }

        // Rasterize all textured triangles
        float originX = marginLeft + extraLeft;
        foreach (var tri in tris) {
            float sx0 = originX + (tri.X0 - minX) * scale;
            float sy0 = marginTop + (maxY - tri.Y0) * scale;
            float sx1 = originX + (tri.X1 - minX) * scale;
            float sy1 = marginTop + (maxY - tri.Y1) * scale;
            float sx2 = originX + (tri.X2 - minX) * scale;
            float sy2 = marginTop + (maxY - tri.Y2) * scale;

            float area = (sx1 - sx0) * (sy2 - sy0) - (sy1 - sy0) * (sx2 - sx0);
            if (Math.Abs(area) < 1e-3f) continue;
            float invArea = 1.0f / area;

            int bx0 = Math.Max(marginLeft, (int)Math.Floor(Math.Min(sx0, Math.Min(sx1, sx2))));
            int bx1 = Math.Min(imgW - marginRight - 1, (int)Math.Ceiling(Math.Max(sx0, Math.Max(sx1, sx2))));
            int by0 = Math.Max(marginTop, (int)Math.Floor(Math.Min(sy0, Math.Min(sy1, sy2))));
            int by1 = Math.Min(imgH - marginBottom - 1, (int)Math.Ceiling(Math.Max(sy0, Math.Max(sy1, sy2))));
            if (bx0 > bx1 || by0 > by1) continue;

            var tex = tri.Tex;
            int tw = tex.W, th = tex.H;
            byte[] tbuf = tex.Bgra;
            float tr = tri.R, tg = tri.G, tb = tri.B, ta = tri.A;
            var blend = tri.Blend;

            for (int py = by0; py <= by1; py++) {
                float cy = py + 0.5f;
                int rowOff = py * imgW;
                for (int px = bx0; px <= bx1; px++) {
                    float cx = px + 0.5f;
                    float w0 = ((sx1 - cx) * (sy2 - cy) - (sy1 - cy) * (sx2 - cx)) * invArea;
                    if (w0 < -1e-4f) continue;
                    float w1 = ((sx2 - cx) * (sy0 - cy) - (sy2 - cy) * (sx0 - cx)) * invArea;
                    if (w1 < -1e-4f) continue;
                    float w2 = 1.0f - w0 - w1;
                    if (w2 < -1e-4f) continue;

                    float u = w0 * tri.U0 + w1 * tri.U1 + w2 * tri.U2;
                    float v = w0 * tri.V0 + w1 * tri.V1 + w2 * tri.V2;
                    if (u < 0f) u = 0f; else if (u > 1f) u = 1f;
                    if (v < 0f) v = 0f; else if (v > 1f) v = 1f;

                    float ftx = u * tw - 0.5f;
                    float fty = v * th - 0.5f;
                    int tx0 = (int)Math.Floor(ftx);
                    int ty0 = (int)Math.Floor(fty);
                    float fx = ftx - tx0;
                    float fy = fty - ty0;
                    int tx1 = tx0 + 1;
                    int ty1 = ty0 + 1;
                    if (tx0 < 0) tx0 = 0; else if (tx0 >= tw) tx0 = tw - 1;
                    if (tx1 < 0) tx1 = 0; else if (tx1 >= tw) tx1 = tw - 1;
                    if (ty0 < 0) ty0 = 0; else if (ty0 >= th) ty0 = th - 1;
                    if (ty1 < 0) ty1 = 0; else if (ty1 >= th) ty1 = th - 1;

                    int p00 = (ty0 * tw + tx0) * 4;
                    int p10 = (ty0 * tw + tx1) * 4;
                    int p01 = (ty1 * tw + tx0) * 4;
                    int p11 = (ty1 * tw + tx1) * 4;

                    float k00 = (1f - fx) * (1f - fy);
                    float k10 = fx * (1f - fy);
                    float k01 = (1f - fx) * fy;
                    float k11 = fx * fy;

                    float a00 = tbuf[p00 + 3] * k00;
                    float a10 = tbuf[p10 + 3] * k10;
                    float a01 = tbuf[p01 + 3] * k01;
                    float a11 = tbuf[p11 + 3] * k11;
                    float aSum = a00 + a10 + a01 + a11;
                    if (aSum <= 1.0f) continue;

                    float invASum = 1.0f / aSum;
                    float sbVal = (tbuf[p00 + 0] * a00 + tbuf[p10 + 0] * a10 + tbuf[p01 + 0] * a01 + tbuf[p11 + 0] * a11) * invASum * tb;
                    float sgVal = (tbuf[p00 + 1] * a00 + tbuf[p10 + 1] * a10 + tbuf[p01 + 1] * a01 + tbuf[p11 + 1] * a11) * invASum * tg;
                    float srVal = (tbuf[p00 + 2] * a00 + tbuf[p10 + 2] * a10 + tbuf[p01 + 2] * a01 + tbuf[p11 + 2] * a11) * invASum * tr;
                    float srcAlpha = (aSum / 255.0f) * ta;
                    if (srcAlpha <= 0.004f) continue;
                    if (srcAlpha > 1.0f) srcAlpha = 1.0f;

                    int dstIdx = (rowOff + px) * 4;
                    float dbVal = canvas[dstIdx + 0];
                    float dgVal = canvas[dstIdx + 1];
                    float drVal = canvas[dstIdx + 2];

                    float ob, og, orVal;
                    if (blend == BlendMode.Additive) {
                        ob = Math.Min(255f, dbVal + sbVal * srcAlpha);
                        og = Math.Min(255f, dgVal + sgVal * srcAlpha);
                        orVal = Math.Min(255f, drVal + srVal * srcAlpha);
                    } else if (blend == BlendMode.Multiply) {
                        float mb = (sbVal / 255f) * srcAlpha + (1f - srcAlpha);
                        float mg = (sgVal / 255f) * srcAlpha + (1f - srcAlpha);
                        float mr = (srVal / 255f) * srcAlpha + (1f - srcAlpha);
                        ob = dbVal * mb;
                        og = dgVal * mg;
                        orVal = drVal * mr;
                    } else if (blend == BlendMode.Screen) {
                        ob = 255f - (255f - dbVal) * (255f - sbVal * srcAlpha) / 255f;
                        og = 255f - (255f - dgVal) * (255f - sgVal * srcAlpha) / 255f;
                        orVal = 255f - (255f - drVal) * (255f - srVal * srcAlpha) / 255f;
                    } else {
                        float invA = 1.0f - srcAlpha;
                        ob = sbVal * srcAlpha + dbVal * invA;
                        og = sgVal * srcAlpha + dgVal * invA;
                        orVal = srVal * srcAlpha + drVal * invA;
                    }
                    canvas[dstIdx + 0] = (byte)(ob < 0f ? 0 : (ob > 255f ? 255 : ob));
                    canvas[dstIdx + 1] = (byte)(og < 0f ? 0 : (og > 255f ? 255 : og));
                    canvas[dstIdx + 2] = (byte)(orVal < 0f ? 0 : (orVal > 255f ? 255 : orVal));
                }
            }
        }

        using (var bmp = new Bitmap(imgW, imgH, PixelFormat.Format32bppArgb)) {
            var bd = bmp.LockBits(new Rectangle(0, 0, imgW, imgH), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
            if (bd.Stride == imgW * 4) {
                Marshal.Copy(canvas, 0, bd.Scan0, canvas.Length);
            } else {
                for (int y = 0; y < imgH; y++) {
                    Marshal.Copy(canvas, y * imgW * 4, IntPtr.Add(bd.Scan0, y * bd.Stride), imgW * 4);
                }
            }
            bmp.UnlockBits(bd);

            using (var g = Graphics.FromImage(bmp)) {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;

                // 1. Coordinate Grid & Ruler (ticks every 200 Spine units)
                int xStart = (int)(Math.Ceiling(minX / 200.0) * 200);
                int xEnd = (int)(Math.Floor(maxX / 200.0) * 200);
                int yStart = (int)(Math.Ceiling(minY / 200.0) * 200);
                int yEnd = (int)(Math.Floor(maxY / 200.0) * 200);

                int labelStep = 200;
                while (labelStep * scale < 34f) labelStep += 200;

                using (var gridPen = new Pen(Color.FromArgb(42, 255, 255, 255), 1f))
                using (var axisPen = new Pen(Color.FromArgb(95, 110, 195, 255), 1f))
                using (var tickPen = new Pen(Color.FromArgb(160, 190, 200, 215), 1f))
                using (var borderPen = new Pen(Color.FromArgb(120, 140, 155, 175), 1f))
                using (var axisFont = new Font("Microsoft YaHei", 7.5f, FontStyle.Regular))
                using (var axisBrush = new SolidBrush(Color.FromArgb(210, 210, 220, 230))) {
                    for (int gx = xStart; gx <= xEnd; gx += 200) {
                        float sx = originX + (gx - minX) * scale;
                        if (sx < marginLeft || sx > imgW - marginRight) continue;
                        g.DrawLine(gx == 0 ? axisPen : gridPen, sx, marginTop, sx, imgH - marginBottom);
                        g.DrawLine(tickPen, sx, imgH - marginBottom, sx, imgH - marginBottom + 4);
                        if (gx % labelStep == 0) {
                            string txt = gx.ToString();
                            var sz = g.MeasureString(txt, axisFont);
                            float tx = Math.Max(marginLeft, Math.Min(imgW - sz.Width - 2, sx - sz.Width * 0.5f));
                            g.DrawString(txt, axisFont, axisBrush, tx, imgH - marginBottom + 5);
                        }
                    }
                    for (int gy = yStart; gy <= yEnd; gy += 200) {
                        float sy = marginTop + (maxY - gy) * scale;
                        if (sy < marginTop || sy > imgH - marginBottom) continue;
                        g.DrawLine(gy == 0 ? axisPen : gridPen, marginLeft, sy, imgW - marginRight, sy);
                        g.DrawLine(tickPen, marginLeft - 4, sy, marginLeft, sy);
                        if (gy % labelStep == 0) {
                            string txt = gy.ToString();
                            var sz = g.MeasureString(txt, axisFont);
                            float ty = Math.Max(marginTop, Math.Min(imgH - marginBottom - sz.Height, sy - sz.Height * 0.5f));
                            g.DrawString(txt, axisFont, axisBrush, marginLeft - 6 - sz.Width, ty);
                        }
                    }
                    g.DrawRectangle(borderPen, marginLeft, marginTop, imgW - marginLeft - marginRight, imgH - marginTop - marginBottom);
                }

                // 2. Hit area rectangles + bone origin markers + labels
                var colorMap = new Dictionary<string, Color> {
                    { "头", Color.FromArgb(255, 225, 45) },
                    { "胸", Color.FromArgb(255, 65, 145) },
                    { "左手", Color.FromArgb(0, 225, 255) },
                    { "右手", Color.FromArgb(65, 255, 70) },
                    { "腿", Color.FromArgb(255, 140, 20) },
                    { "足", Color.FromArgb(195, 110, 255) },
                };

                var placedLabels = new List<RectangleF>();
                using (var lblFont = new Font("Microsoft YaHei", 8.5f, FontStyle.Bold)) {
                    foreach (var hb in hitBoxes) {
                        Color col = colorMap.ContainsKey(hb.Motion) ? colorMap[hb.Motion]
                                  : (colorMap.ContainsKey(hb.Name) ? colorMap[hb.Name] : Color.White);

                        float xLeft = originX + (hb.BoxCx - hb.BoxW * 0.5f - minX) * scale;
                        float yTop = marginTop + (maxY - (hb.BoxCy + hb.BoxH * 0.5f)) * scale;
                        float rw = Math.Max(4f, hb.BoxW * scale);
                        float rh = Math.Max(4f, hb.BoxH * scale);
                        float cxPx = originX + (hb.BoxCx - minX) * scale;
                        float cyPx = marginTop + (maxY - hb.BoxCy) * scale;
                        float bwxPx = originX + (hb.BoneWx - minX) * scale;
                        float bwyPx = marginTop + (maxY - hb.BoneWy) * scale;

                        using (var fillBr = new SolidBrush(Color.FromArgb(36, col)))
                        using (var boxPen = new Pen(col, 2.0f))
                        using (var linkPen = new Pen(Color.FromArgb(170, col), 1.2f) { DashStyle = DashStyle.Dot })
                        using (var boneBr = new SolidBrush(col)) {
                            g.FillRectangle(fillBr, xLeft, yTop, rw, rh);
                            g.DrawRectangle(boxPen, xLeft, yTop, rw, rh);
                            // Draw bone anchor dot and dashed leader to box center if offset
                            if (Math.Abs(bwxPx - cxPx) > 3f || Math.Abs(bwyPx - cyPx) > 3f) {
                                g.DrawLine(linkPen, bwxPx, bwyPx, cxPx, cyPx);
                            }
                            g.FillEllipse(boneBr, bwxPx - 3f, bwyPx - 3f, 6f, 6f);
                            g.DrawLine(boxPen, cxPx - 4f, cyPx, cxPx + 4f, cyPx);
                            g.DrawLine(boxPen, cxPx, cyPx - 4f, cxPx, cyPx + 4f);
                        }

                        string lbl = hb.Name + "(" + hb.BoneId + ")" + (hb.BoneFound ? "" : "[MISSING]");
                        var tsz = g.MeasureString(lbl, lblFont);
                        float lw = tsz.Width + 6f;
                        float lh = tsz.Height + 2f;
                        float lx = Math.Max(marginLeft + 2, Math.Min(imgW - marginRight - lw - 2, cxPx - lw * 0.5f));
                        float ly = Math.Max(marginTop + 2, Math.Min(imgH - marginBottom - lh - 2, yTop - lh - 2));
                        // Nudge vertically if overlapping an already-placed label
                        var rect = new RectangleF(lx, ly, lw, lh);
                        for (int attempt = 0; attempt < 10; attempt++) {
                            bool overlap = false;
                            foreach (var pr in placedLabels) {
                                if (rect.IntersectsWith(pr)) { overlap = true; break; }
                            }
                            if (!overlap) break;
                            float ny = rect.Y + lh + 2f;
                            if (ny + lh > imgH - marginBottom - 2) ny = Math.Max(marginTop + 2, rect.Y - lh - 2f);
                            rect.Y = ny;
                        }
                        placedLabels.Add(rect);

                        using (var pillBr = new SolidBrush(Color.FromArgb(205, 16, 18, 24)))
                        using (var pillPen = new Pen(col, 1f))
                        using (var txtBr = new SolidBrush(col)) {
                            g.FillRectangle(pillBr, rect);
                            g.DrawRectangle(pillPen, rect.X, rect.Y, rect.Width, rect.Height);
                            g.DrawString(lbl, lblFont, txtBr, rect.X + 3f, rect.Y + 1f);
                        }
                    }
                }

                // 3. Top Header Bar
                string roTag = "";
                string header = string.Format("#{0:000} {1}{2}   (hits={3}, tris={4})", index, rel, roTag, hitBoxes.Count, tris.Count);
                using (var hdrFont = new Font("Microsoft YaHei", 9.5f, FontStyle.Bold))
                using (var hdrBrush = new SolidBrush(Color.FromArgb(245, 248, 255))) {
                    g.DrawString(header, hdrFont, hdrBrush, marginLeft, 7f);
                }
            }

            string safeName = rel.Replace('/', '\u0000').Replace('\\', '\u0000');
            string[] parts = safeName.Split('\u0000');
            string fn = string.Format("{0:000}_{1}__{2}.jpg", index, parts[0], parts[1]);
            string outPath = Path.Combine(outDir, fn);

            ImageCodecInfo jpgEnc = null;
            foreach (var c in ImageCodecInfo.GetImageEncoders()) {
                if (c.MimeType == "image/jpeg") { jpgEnc = c; break; }
            }
            using (var eps = new EncoderParameters(1)) {
                eps.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 80L);
                bmp.Save(outPath, jpgEnc, eps);
            }
            return outPath;
        }
    }
}
'''


def _ensure_exe() -> None:
    src_hash = hashlib.sha256(CS_SOURCE.encode("utf-8")).hexdigest()
    need_compile = not EXE_PATH.is_file() or not HASH_PATH.is_file()
    if not need_compile:
        try:
            need_compile = HASH_PATH.read_text(encoding="utf-8").strip() != src_hash
        except Exception:
            need_compile = True
    if not need_compile:
        return

    CS_PATH.write_text(CS_SOURCE, encoding="utf-8")
    cmd = [
        str(CSC_EXE),
        "/nologo",
        "/optimize+",
        "/platform:x64",
        f"/out:{EXE_PATH}",
        f"/r:{EX_MANAGED_DIR / 'UnityEngine.CoreModule.dll'}",
        f"/r:{EX_MANAGED_DIR / 'Assembly-CSharp.dll'}",
        "/r:System.Drawing.dll",
        "/r:System.Web.Extensions.dll",
        str(CS_PATH),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"csc.exe compilation failed:\n{r.stdout}\n{r.stderr}")
    HASH_PATH.write_text(src_hash, encoding="utf-8")


def _candidate_bones_summary(geom: dict[str, Any], hit_areas: list[dict[str, Any]], max_bones: int = 35) -> list[dict[str, Any]]:
    """Return a compact list of top candidate bones (name, wx, wy, vcx, vcy, vw)."""
    bones = geom.get("bones", [])
    bound_ids = {str(h.get("id", "")) for h in hit_areas}
    anat_re = re.compile(
        r"(tou|head|lian|face|bizi|yan|zui|xiong|chest|bra|shenti|shangshen|qugan|"
        r"shou|hand|bi\d|xiaobi|dabi|wan|tui|leg|datui|xiaotui|jiao|foot|xie|shoe)",
        re.I,
    )

    chosen: dict[str, dict[str, Any]] = {}
    for b in bones:
        nm = b["name"]
        if nm in bound_ids or (nm != "root" and not BG_BONE_RE.search(nm) and anat_re.search(nm) and b.get("vw", 0) > 0):
            chosen[nm] = b

    non_bg_vw = sorted(
        [b for b in bones if b["name"] != "root" and not BG_BONE_RE.search(b["name"]) and b.get("vw", 0) > 0],
        key=lambda x: float(x.get("vw", 0)),
        reverse=True,
    )
    for b in non_bg_vw:
        if len(chosen) >= max_bones:
            break
        chosen.setdefault(b["name"], b)

    if len(chosen) < 12:
        for b in bones:
            if b["name"] != "root" and not BG_BONE_RE.search(b["name"]):
                chosen.setdefault(b["name"], b)
                if len(chosen) >= 16:
                    break

    out = []
    for b in sorted(chosen.values(), key=lambda x: float(x.get("vcy", x["wy"])), reverse=True):
        out.append({
            "name": b["name"],
            "wx": b["wx"],
            "wy": b["wy"],
            "vcx": b.get("vcx", b["wx"]),
            "vcy": b.get("vcy", b["wy"]),
            "vw": b.get("vw", 0),
        })
    return out


def build_manifest() -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    geom_cache = json.loads(GEOM_CACHE_PATH.read_text(encoding="utf-8-sig")) if GEOM_CACHE_PATH.is_file() else {}
    cfg_paths = sorted(SPINE_ROOT.glob("*/*/.config.json"), key=lambda p: p.parent.relative_to(SPINE_ROOT).as_posix())

    models: list[dict[str, Any]] = []
    for idx, cfg_p in enumerate(cfg_paths, start=1):
        skin_dir = cfg_p.parent
        rel = skin_dir.relative_to(SPINE_ROOT).as_posix()
        char_nm, skin_nm = rel.split("/", 1)
        cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        hit_areas = cfg.get("hit_areas", [])
        geom = geom_cache.get(rel, {"bones": [], "slots": []})
        preview_jpg = OUT_DIR / f"{idx:03d}_{char_nm}__{skin_nm}.jpg"
        models.append({
            "index": idx,
            "rel": rel,
            "readonly": rel in READONLY_MODELS,
            "preview_jpg": str(preview_jpg),
            "config_path": str(cfg_p),
            "hit_areas": hit_areas,
            "candidate_bones": _candidate_bones_summary(geom, hit_areas),
        })

    # Split into 4 balanced disjoint shards (41, 41, 41, 40 = 163)
    n = len(models)
    q, rem = divmod(n, 4)
    shards: dict[str, list[dict[str, Any]]] = {}
    shard_ranges: dict[str, dict[str, Any]] = {}
    pos = 0
    for s_idx in range(1, 5):
        sz = q + (1 if s_idx <= rem else 0)
        slice_items = models[pos : pos + sz]
        pos += sz
        sname = f"shard_{s_idx}"
        shards[sname] = slice_items
        editable_in_shard = sum(1 for m in slice_items if not m["readonly"])
        shard_ranges[sname] = {
            "count": len(slice_items),
            "editable_count": editable_in_shard,
            "start_index": slice_items[0]["index"] if slice_items else 0,
            "end_index": slice_items[-1]["index"] if slice_items else 0,
            "first": slice_items[0]["rel"] if slice_items else "",
            "last": slice_items[-1]["rel"] if slice_items else "",
        }

    manifest = {
        "total_count": n,
        "editable_count": sum(1 for m in models if not m["readonly"]),
        "readonly_models": sorted(READONLY_MODELS),
        "preview_dir": str(OUT_DIR),
        "shard_ranges": shard_ranges,
        "shards": shards,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Spine3_8 textured touch-trigger preview JPGs.")
    parser.add_argument("--only", type=str, default="", help="Render a single skin rel path, e.g. '伊汐尔/原皮'")
    parser.add_argument("--no-manifest", action="store_true", help="Skip regenerating manifest.json on full run")
    args = parser.parse_args()

    _ensure_exe()

    if args.only:
        rel = args.only.replace("\\", "/").strip("/")
        r = subprocess.run(
            [str(EXE_PATH), "--only", rel, "--spine-root", str(SPINE_ROOT), "--out-dir", str(OUT_DIR)],
            capture_output=True,
            text=True,
        )
        if r.stdout:
            print(r.stdout.strip())
        if r.returncode != 0:
            if r.stderr:
                print(r.stderr.strip(), file=sys.stderr)
            return r.returncode
        return 0

    r = subprocess.run(
        [str(EXE_PATH), "--all", "--spine-root", str(SPINE_ROOT), "--out-dir", str(OUT_DIR)],
        capture_output=True,
        text=True,
    )
    if r.stdout:
        print(r.stdout.strip())
    if r.returncode != 0:
        if r.stderr:
            print(r.stderr.strip(), file=sys.stderr)
        return r.returncode

    if not args.no_manifest:
        m = build_manifest()
        print(f"Manifest written: {MANIFEST_PATH} (total={m['total_count']}, editable={m['editable_count']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
