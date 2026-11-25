"""Composite Scene Preview Renderer for SoulTide Spine Packages (Main + All Submodels).

Compiles & invokes a lightweight C# (.NET Framework 4.x) rasterizer backed by
Live2DViewerEX's `Spine3_8` runtime (`Assembly-CSharp.dll`) to composite:
  - All negative-order submodels (`-3, -2, -1`), e.g. `bg_static`, `bj_*`, `bg_mid`, `fx_back`
  - Main character (`order = 0`)
  - All positive-order submodels (`+1, +2, +3`), e.g. `fg_static`, `bj_*`, `fx_front`
in Live2DViewerEX's exact draw order, `scale_factor` ratio, and world coordinates!

Saves compact JPG previews (max 800px, quality=80) to `E:\\A灵魂潮汐\\tools\\_bg_audit_previews\\`.

Usage:
    python render_spine_composite_previews.py --all
    python render_spine_composite_previews.py --only 叶隐琉璃/绵绵小懒虫
    python render_spine_composite_previews.py --only 叶隐琉璃/绵绵小懒虫 --tag before
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SPINE_ROOT = Path(r"E:\A灵魂潮汐\Live2D与Spine模型\spine")
OUT_DIR = TOOLS_DIR / "_bg_audit_previews"
CS_PATH = TOOLS_DIR / "_spine38_composite_renderer.cs"
EXE_PATH = TOOLS_DIR / "_spine38_composite_renderer.exe"
HASH_PATH = TOOLS_DIR / "_spine38_composite_renderer.sha256"

CSC_EXE = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
EX_MANAGED_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed")

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

class LayerSpec {
    public int Order;
    public string Label;
    public string ConfigPath;
    public bool IsBgStatic;
    public bool IsFx;
}

class HitBoxInfo {
    public string Name;
    public string BoneId;
    public string Motion;
    public float BoxCx, BoxCy, BoxW, BoxH;
    public float BoneWx, BoneWy;
    public bool BoneFound;
    public float OvL, OvR, OvB, OvT;
    public bool OutOfBg;
}

class BoneMeta {
    public string Id;
    public float Wx, Wy;
    public bool InBg;
    public List<string> Slots;
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
        var onlyRels = new List<string>();
        string spineRoot = "";
        string outDir = "";
        string tag = "";
        bool skipFx = false;
        bool onlyWithSubs = false;
        bool withHits = false;
        bool emitMeta = false;

        for (int i = 0; i < args.Length; i++) {
            if (args[i] == "--all") mode = "all";
            else if (args[i] == "--only" && i + 1 < args.Length) { mode = "only"; onlyRels.Add(args[++i].Replace('\\', '/')); }
            else if (args[i] == "--spine-root" && i + 1 < args.Length) spineRoot = args[++i];
            else if (args[i] == "--out-dir" && i + 1 < args.Length) outDir = args[++i];
            else if (args[i] == "--tag" && i + 1 < args.Length) tag = args[++i];
            else if (args[i] == "--skip-fx") skipFx = true;
            else if (args[i] == "--only-with-subs") onlyWithSubs = true;
            else if (args[i] == "--with-hits") withHits = true;
            else if (args[i] == "--emit-meta") emitMeta = true;
        }
        if (string.IsNullOrEmpty(spineRoot) || string.IsNullOrEmpty(outDir) || string.IsNullOrEmpty(mode)) {
            Console.Error.WriteLine("Usage: --all|--only <rel> --spine-root <dir> --out-dir <dir> [--tag <suffix>] [--skip-fx] [--only-with-subs] [--with-hits] [--emit-meta]");
            return 2;
        }
        Directory.CreateDirectory(outDir);

        var relList = new List<Tuple<string, string>>();
        foreach (var charDir in Directory.GetDirectories(spineRoot)) {
            foreach (var skinDir in Directory.GetDirectories(charDir)) {
                string cp = Path.Combine(skinDir, ".config.json");
                if (File.Exists(cp)) {
                    string rel = skinDir.Substring(spineRoot.TrimEnd('\\', '/').Length + 1).Replace('\\', '/');
                    relList.Add(Tuple.Create(rel, skinDir));
                }
            }
        }
        relList.Sort((a, b) => StringComparer.Ordinal.Compare(a.Item1, b.Item1));
        var items = new List<Tuple<int, string, string>>();
        for (int i = 0; i < relList.Count; i++) {
            items.Add(Tuple.Create(i + 1, relList[i].Item1, relList[i].Item2));
        }

        if (mode == "only") {
            var targets = new List<Tuple<int, string, string>>();
            foreach (var r in onlyRels) {
                var hit = items.Find(it => it.Item2 == r);
                if (hit == null) {
                    Console.Error.WriteLine("Model not found: " + r);
                    return 3;
                }
                targets.Add(hit);
            }
            foreach (var t in targets) {
                var sw = Stopwatch.StartNew();
                try {
                    string outPath = RenderOne(t.Item1, t.Item2, t.Item3, outDir, tag, skipFx, false, withHits, emitMeta);
                    sw.Stop();
                    Console.WriteLine("OK " + t.Item2 + " -> " + outPath + " (" + sw.ElapsedMilliseconds + " ms)");
                } catch (Exception ex) {
                    Console.Error.WriteLine("ERR " + t.Item2 + ": " + ex.GetType().FullName + " :: " + ex.Message);
                    Console.Error.WriteLine(ex.StackTrace);
                    return 1;
                }
            }
            return 0;
        }

        var swAll = Stopwatch.StartNew();
        int done = 0;
        int skipped = 0;
        var errors = new List<string>();
        object lockObj = new object();
        Parallel.ForEach(items, new ParallelOptions { MaxDegreeOfParallelism = Math.Max(1, Math.Min(6, Environment.ProcessorCount)) }, it => {
            try {
                string p = RenderOne(it.Item1, it.Item2, it.Item3, outDir, tag, skipFx, onlyWithSubs, withHits, emitMeta);
                lock (lockObj) {
                    if (p == null) skipped++;
                    else done++;
                    if ((done + skipped) % 25 == 0 || (done + skipped) == items.Count) {
                        Console.WriteLine("Progress " + (done + skipped) + "/" + items.Count + " (rendered=" + done + ", skipped=" + skipped + ")");
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
        Console.WriteLine("ALL DONE rendered=" + done + " skipped=" + skipped + " in " + swAll.ElapsedMilliseconds + " ms");
        return 0;
    }

    static float ToFloat(object obj, float defVal) {
        if (obj == null) return defVal;
        return Convert.ToSingle(obj);
    }

    static void ExtractLayerTriangles(
        string cfgPath,
        float baseScale,
        List<DrawTri> outTris,
        out float lMinX, out float lMaxX, out float lMinY, out float lMaxY,
        out float scaleRatio,
        bool collectMainMeta,
        List<BoneMeta> mainBones,
        List<HitBoxInfo> mainHits
    ) {
        lMinX = 1e9f; lMaxX = -1e9f; lMinY = 1e9f; lMaxY = -1e9f;
        scaleRatio = 1.0f;

        string dir = Path.GetDirectoryName(cfgPath);
        string cfgText = File.ReadAllText(cfgPath, Encoding.UTF8);
        var jss = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 };
        var cfg = jss.Deserialize<Dictionary<string, object>>(cfgText);

        var opts = cfg.ContainsKey("options") ? cfg["options"] as Dictionary<string, object> : null;
        float sc = opts != null && opts.ContainsKey("scale_factor") ? ToFloat(opts["scale_factor"], baseScale) : baseScale;
        scaleRatio = sc / Math.Max(1e-6f, baseScale);

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
            float animT = 0f;
            string envT = Environment.GetEnvironmentVariable("SPINE_ANIM_TIME");
            if (!string.IsNullOrEmpty(envT)) float.TryParse(envT, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out animT);
            if (anim != null) anim.Apply(sk, 0, animT, true, null, 1.0f, MixBlend.Setup, MixDirection.In);
        }
        sk.UpdateWorldTransform();

        if (collectMainMeta) {
            var boneMap = new Dictionary<string, Bone>();
            var boneSlots = new Dictionary<string, List<string>>();
            foreach (var b in sk.Bones) {
                boneMap[b.Data.Name] = b;
            }
            foreach (var slot in sk.DrawOrder) {
                if (slot.Attachment != null && slot.A > 0.01f && slot.Bone.Active) {
                    string bn = slot.Bone.Data.Name;
                    List<string> sl;
                    if (!boneSlots.TryGetValue(bn, out sl)) {
                        sl = new List<string>();
                        boneSlots[bn] = sl;
                    }
                    if (sl.Count < 4) sl.Add(slot.Data.Name);
                }
            }
            foreach (var b in sk.Bones) {
                if (b.Data.Name == "root") continue;
                List<string> sl;
                if (!boneSlots.TryGetValue(b.Data.Name, out sl)) sl = new List<string>();
                mainBones.Add(new BoneMeta {
                    Id = b.Data.Name,
                    Wx = b.WorldX,
                    Wy = b.WorldY,
                    InBg = true,
                    Slots = sl
                });
            }
            if (cfg.ContainsKey("hit_areas") && cfg["hit_areas"] is System.Collections.ArrayList) {
                var haArr = (System.Collections.ArrayList)cfg["hit_areas"];
                foreach (Dictionary<string, object> ha in haArr) {
                    string name = ha.ContainsKey("name") ? Convert.ToString(ha["name"]) : "";
                    string bid = ha.ContainsKey("id") ? Convert.ToString(ha["id"]) : "";
                    string mot = ha.ContainsKey("motion") ? Convert.ToString(ha["motion"]) : name;
                    float hw = ToFloat(ha.ContainsKey("width") ? ha["width"] : null, 1.5f) * 100f;
                    float hh = ToFloat(ha.ContainsKey("height") ? ha["height"] : null, 1.5f) * 100f;
                    float cxOff = ToFloat(ha.ContainsKey("center_x") ? ha["center_x"] : null, 0f) * 100f;
                    float cyOff = ToFloat(ha.ContainsKey("center_y") ? ha["center_y"] : null, 0f) * 100f;
                    Bone b;
                    bool found = boneMap.TryGetValue(bid, out b);
                    float bwx = found ? b.WorldX : 0f;
                    float bwy = found ? b.WorldY : 0f;
                    mainHits.Add(new HitBoxInfo {
                        Name = name,
                        BoneId = bid,
                        Motion = mot,
                        BoxCx = bwx + cxOff,
                        BoxCy = bwy + cyOff,
                        BoxW = hw,
                        BoxH = hh,
                        BoneWx = bwx,
                        BoneWy = bwy,
                        BoneFound = found,
                        OvL = 0f, OvR = 0f, OvB = 0f, OvT = 0f,
                        OutOfBg = false
                    });
                }
            }
        }

        float[] verts = new float[8192];
        int[] quadIdx = new int[] { 0, 1, 2, 0, 2, 3 };
        var clipper = new SkeletonClipping();
        foreach (var slot in sk.DrawOrder) {
            var att = slot.Attachment;
            if (att == null || !slot.Bone.Active) { clipper.ClipEnd(slot); continue; }
            if (att is ClippingAttachment) {
                clipper.ClipStart(slot, (ClippingAttachment)att);
                continue;
            }
            if (slot.A <= 0.01f) { clipper.ClipEnd(slot); continue; }
            var blend = slot.Data.BlendMode;

            if (att is RegionAttachment) {
                var ra = (RegionAttachment)att;
                var ar = ra.RendererObject as AtlasRegion;
                if (ar == null || ar.page == null) { clipper.ClipEnd(slot); continue; }
                var tex = ar.page.rendererObject as LoadedTex;
                if (tex == null) { clipper.ClipEnd(slot); continue; }
                float sa = slot.A * ra.A;
                if (sa <= 0.01f) { clipper.ClipEnd(slot); continue; }
                float sr = slot.R * ra.R;
                float sg = slot.G * ra.G;
                float sb = slot.B * ra.B;

                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2);
                float[] uvs = ra.UVs;
                float[] useVerts = verts;
                float[] useUvs = uvs;
                int[] useIdx = quadIdx;
                int idxCount = 6;
                int nv = 4;
                if (clipper.IsClipping) {
                    clipper.ClipTriangles(verts, 8, quadIdx, 6, uvs);
                    useVerts = clipper.ClippedVertices.Items;
                    useUvs = clipper.ClippedUVs.Items;
                    useIdx = clipper.ClippedTriangles.Items;
                    idxCount = clipper.ClippedTriangles.Count;
                    nv = clipper.ClippedVertices.Count / 2;
                }
                for (int k = 0; k < nv; k++) {
                    float vx = useVerts[k * 2] * scaleRatio, vy = useVerts[k * 2 + 1] * scaleRatio;
                    if (vx < lMinX) lMinX = vx; if (vx > lMaxX) lMaxX = vx;
                    if (vy < lMinY) lMinY = vy; if (vy > lMaxY) lMaxY = vy;
                }
                for (int t = 0; t + 2 < idxCount; t += 3) {
                    int i0 = useIdx[t], i1 = useIdx[t + 1], i2 = useIdx[t + 2];
                    if (i0 >= nv || i1 >= nv || i2 >= nv) continue;
                    outTris.Add(new DrawTri {
                        Tex = tex, Blend = blend, R = sr, G = sg, B = sb, A = sa,
                        X0 = useVerts[i0 * 2] * scaleRatio, Y0 = useVerts[i0 * 2 + 1] * scaleRatio, U0 = useUvs[i0 * 2], V0 = useUvs[i0 * 2 + 1],
                        X1 = useVerts[i1 * 2] * scaleRatio, Y1 = useVerts[i1 * 2 + 1] * scaleRatio, U1 = useUvs[i1 * 2], V1 = useUvs[i1 * 2 + 1],
                        X2 = useVerts[i2 * 2] * scaleRatio, Y2 = useVerts[i2 * 2 + 1] * scaleRatio, U2 = useUvs[i2 * 2], V2 = useUvs[i2 * 2 + 1]
                    });
                }
            } else if (att is MeshAttachment) {
                var ma = (MeshAttachment)att;
                var ar = ma.RendererObject as AtlasRegion;
                if (ar == null || ar.page == null) { clipper.ClipEnd(slot); continue; }
                var tex = ar.page.rendererObject as LoadedTex;
                if (tex == null) { clipper.ClipEnd(slot); continue; }
                float sa = slot.A * ma.A;
                if (sa <= 0.01f) { clipper.ClipEnd(slot); continue; }
                float sr = slot.R * ma.R;
                float sg = slot.G * ma.G;
                float sb = slot.B * ma.B;

                int cnt = ma.WorldVerticesLength;
                if (cnt <= 0) { clipper.ClipEnd(slot); continue; }
                if (cnt > verts.Length) verts = new float[cnt * 2];
                ma.ComputeWorldVertices(slot, 0, cnt, verts, 0, 2);
                int nv = cnt / 2;
                float[] uvs = ma.UVs;
                int[] indices = ma.Triangles;
                float[] useVerts = verts;
                float[] useUvs = uvs;
                int[] useIdx = indices;
                int idxCount = indices.Length;
                if (clipper.IsClipping) {
                    clipper.ClipTriangles(verts, cnt, indices, indices.Length, uvs);
                    useVerts = clipper.ClippedVertices.Items;
                    useUvs = clipper.ClippedUVs.Items;
                    useIdx = clipper.ClippedTriangles.Items;
                    idxCount = clipper.ClippedTriangles.Count;
                    nv = clipper.ClippedVertices.Count / 2;
                }
                for (int k = 0; k < nv; k++) {
                    float vx = useVerts[k * 2] * scaleRatio, vy = useVerts[k * 2 + 1] * scaleRatio;
                    if (vx < lMinX) lMinX = vx; if (vx > lMaxX) lMaxX = vx;
                    if (vy < lMinY) lMinY = vy; if (vy > lMaxY) lMaxY = vy;
                }
                for (int t = 0; t + 2 < idxCount; t += 3) {
                    int i0 = useIdx[t], i1 = useIdx[t + 1], i2 = useIdx[t + 2];
                    if (i0 >= nv || i1 >= nv || i2 >= nv) continue;
                    outTris.Add(new DrawTri {
                        Tex = tex, Blend = blend, R = sr, G = sg, B = sb, A = sa,
                        X0 = useVerts[i0 * 2] * scaleRatio, Y0 = useVerts[i0 * 2 + 1] * scaleRatio, U0 = useUvs[i0 * 2], V0 = useUvs[i0 * 2 + 1],
                        X1 = useVerts[i1 * 2] * scaleRatio, Y1 = useVerts[i1 * 2 + 1] * scaleRatio, U1 = useUvs[i1 * 2], V1 = useUvs[i1 * 2 + 1],
                        X2 = useVerts[i2 * 2] * scaleRatio, Y2 = useVerts[i2 * 2 + 1] * scaleRatio, U2 = useUvs[i2 * 2], V2 = useUvs[i2 * 2 + 1]
                    });
                }
            }
            clipper.ClipEnd(slot);
        }
        clipper.ClipEnd();
    }

    static string RenderOne(int index, string rel, string dir, string outDir, string tag, bool skipFx, bool onlyWithSubs, bool withHits, bool emitMeta) {
        string mainCfgPath = Path.Combine(dir, ".config.json");
        string cfgText = File.ReadAllText(mainCfgPath, Encoding.UTF8);
        var jss = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 };
        var cfg = jss.Deserialize<Dictionary<string, object>>(cfgText);

        var opts = cfg["options"] as Dictionary<string, object>;
        float baseScale = ToFloat(opts["scale_factor"], 0.11f);

        var layers = new List<LayerSpec>();
        layers.Add(new LayerSpec { Order = 0, Label = "MAIN", ConfigPath = mainCfgPath, IsBgStatic = false, IsFx = false });

        string startCmd = "";
        var motions = cfg.ContainsKey("motions") ? cfg["motions"] as Dictionary<string, object> : null;
        if (motions != null && motions.ContainsKey("start")) {
            var arr = motions["start"] as System.Collections.ArrayList;
            if (arr != null && arr.Count > 0) {
                var first = arr[0] as Dictionary<string, object>;
                if (first != null && first.ContainsKey("command")) startCmd = Convert.ToString(first["command"]);
            }
        }
        int subCount = 0;
        if (!string.IsNullOrEmpty(startCmd)) {
            foreach (var rawCmd in startCmd.Split(';')) {
                string cmd = rawCmd.Trim();
                if (string.IsNullOrEmpty(cmd)) continue;
                var toks = cmd.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                if (toks.Length == 3 && toks[0] == "add_submodel") {
                    string subPath = Path.Combine(dir, toks[1].Replace('/', Path.DirectorySeparatorChar));
                    int ord = int.Parse(toks[2]);
                    string folder = Path.GetFileName(Path.GetDirectoryName(subPath));
                    bool isFx = folder.StartsWith("fx_", StringComparison.OrdinalIgnoreCase);
                    subCount++;
                    if (skipFx && isFx) continue;
                    if (File.Exists(subPath)) {
                        layers.Add(new LayerSpec {
                            Order = ord,
                            Label = folder,
                            ConfigPath = subPath,
                            IsBgStatic = folder.Equals("bg_static", StringComparison.OrdinalIgnoreCase),
                            IsFx = isFx,
                        });
                    }
                }
            }
        }
        if (onlyWithSubs && subCount == 0) return null;

        layers.Sort((a, b) => a.Order.CompareTo(b.Order));

        var allTris = new List<DrawTri>();
        var layerLabels = new List<string>();
        bool hasBgBox = false;
        float bgMinX = 1e9f, bgMaxX = -1e9f, bgMinY = 1e9f, bgMaxY = -1e9f;
        float mainMinX = 1e9f, mainMaxX = -1e9f, mainMinY = 1e9f, mainMaxY = -1e9f;
        float allMinX = 1e9f, allMaxX = -1e9f, allMinY = 1e9f, allMaxY = -1e9f;
        var mainBones = new List<BoneMeta>();
        var mainHits = new List<HitBoxInfo>();

        foreach (var lay in layers) {
            float lMinX, lMaxX, lMinY, lMaxY, sr;
            int before = allTris.Count;
            bool isMain = (lay.Order == 0 && !lay.IsBgStatic && !lay.IsFx);
            ExtractLayerTriangles(
                lay.ConfigPath, baseScale, allTris,
                out lMinX, out lMaxX, out lMinY, out lMaxY, out sr,
                isMain && (withHits || emitMeta), mainBones, mainHits
            );
            int added = allTris.Count - before;
            layerLabels.Add(string.Format("{0}:{1}(x{2:0.00})", lay.Order, lay.Label, sr));
            if (added > 0) {
                if (lay.IsBgStatic) {
                    hasBgBox = true;
                    bgMinX = lMinX; bgMaxX = lMaxX; bgMinY = lMinY; bgMaxY = lMaxY;
                }
                if (isMain) {
                    mainMinX = lMinX; mainMaxX = lMaxX; mainMinY = lMinY; mainMaxY = lMaxY;
                }
                if (lMinX < allMinX) allMinX = lMinX;
                if (lMaxX > allMaxX) allMaxX = lMaxX;
                if (lMinY < allMinY) allMinY = lMinY;
                if (lMaxY > allMaxY) allMaxY = lMaxY;
            }
        }

        int outOfBgCount = 0;
        if (hasBgBox) {
            foreach (var bm in mainBones) {
                bm.InBg = (bm.Wx >= bgMinX && bm.Wx <= bgMaxX && bm.Wy >= bgMinY && bm.Wy <= bgMaxY);
            }
            foreach (var hb in mainHits) {
                float hx0 = hb.BoxCx - hb.BoxW * 0.5f;
                float hx1 = hb.BoxCx + hb.BoxW * 0.5f;
                float hy0 = hb.BoxCy - hb.BoxH * 0.5f;
                float hy1 = hb.BoxCy + hb.BoxH * 0.5f;
                hb.OvL = Math.Max(0f, bgMinX - hx0);
                hb.OvR = Math.Max(0f, hx1 - bgMaxX);
                hb.OvB = Math.Max(0f, bgMinY - hy0);
                hb.OvT = Math.Max(0f, hy1 - bgMaxY);
                bool centerOut = (!hb.BoneFound) || (hb.BoxCx < bgMinX - 5f || hb.BoxCx > bgMaxX + 5f || hb.BoxCy < bgMinY - 5f || hb.BoxCy > bgMaxY + 5f);
                hb.OutOfBg = centerOut || hb.OvL > 5f || hb.OvR > 5f || hb.OvB > 5f || hb.OvT > 5f;
                if (hb.OutOfBg) outOfBgCount++;
            }
        }

        // Viewport calculation
        float minX = hasBgBox ? bgMinX : (withHits && mainMinX <= mainMaxX ? mainMinX : allMinX);
        float maxX = hasBgBox ? bgMaxX : (withHits && mainMinX <= mainMaxX ? mainMaxX : allMaxX);
        float minY = hasBgBox ? bgMinY : (withHits && mainMinY <= mainMaxY ? mainMinY : allMinY);
        float maxY = hasBgBox ? bgMaxY : (withHits && mainMinY <= mainMaxY ? mainMaxY : allMaxY);
        if (withHits) {
            if (mainMinX <= mainMaxX) {
                if (mainMinX < minX) minX = mainMinX;
                if (mainMaxX > maxX) maxX = mainMaxX;
                if (mainMinY < minY) minY = mainMinY;
                if (mainMaxY > maxY) maxY = mainMaxY;
            }
            foreach (var hb in mainHits) {
                if (!hb.BoneFound) continue;
                float hx0 = hb.BoxCx - hb.BoxW * 0.5f;
                float hx1 = hb.BoxCx + hb.BoxW * 0.5f;
                float hy0 = hb.BoxCy - hb.BoxH * 0.5f;
                float hy1 = hb.BoxCy + hb.BoxH * 0.5f;
                if (hx0 < minX) minX = hx0;
                if (hx1 > maxX) maxX = hx1;
                if (hy0 < minY) minY = hy0;
                if (hy1 > maxY) maxY = hy1;
            }
        }
        if (minX > maxX) { minX = -500; maxX = 500; minY = 0; maxY = 1000; }

        float spanW = Math.Max(200f, maxX - minX);
        float spanH = Math.Max(200f, maxY - minY);
        float padW = withHits ? Math.Max(50f, spanW * 0.06f) : (spanW * 0.04f);
        float padH = withHits ? Math.Max(50f, spanH * 0.06f) : (spanH * 0.04f);
        minX -= padW; maxX += padW;
        minY -= padH; maxY += padH;
        spanW = maxX - minX;
        spanH = maxY - minY;

        int marginTop = withHits ? 32 : 28;
        int marginLeft = withHits ? 46 : 8;
        int marginRight = withHits ? 14 : 8;
        int marginBottom = withHits ? 28 : 8;
        const int maxTotalW = 800;
        const int maxTotalH = 580;
        int maxPlotW = maxTotalW - marginLeft - marginRight;
        int maxPlotH = maxTotalH - marginTop - marginBottom;

        float scale = Math.Min((maxPlotW - 1) / spanW, (maxPlotH - 1) / spanH);
        int plotW = Math.Max(160, Math.Min(maxPlotW, (int)Math.Floor(spanW * scale)));
        int plotH = Math.Max(120, Math.Min(maxPlotH, (int)Math.Floor(spanH * scale)));
        int imgW = Math.Max(480, plotW + marginLeft + marginRight);
        int imgH = plotH + marginTop + marginBottom;
        float originX = marginLeft + (imgW - marginLeft - marginRight - plotW) * 0.5f;

        byte[] canvas = new byte[imgW * imgH * 4];
        for (int y = 0; y < imgH; y++) {
            for (int x = 0; x < imgW; x++) {
                int idx = (y * imgW + x) * 4;
                bool inPlot = (x >= marginLeft && x < imgW - marginRight && y >= marginTop && y < imgH - marginBottom);
                if (inPlot) {
                    bool chk = (((x / 16) + (y / 16)) & 1) == 0;
                    canvas[idx + 0] = (byte)(chk ? 42 : 34);
                    canvas[idx + 1] = (byte)(chk ? 36 : 30);
                    canvas[idx + 2] = (byte)(chk ? 34 : 28);
                    canvas[idx + 3] = 255;
                } else {
                    canvas[idx + 0] = 24;
                    canvas[idx + 1] = 20;
                    canvas[idx + 2] = 18;
                    canvas[idx + 3] = 255;
                }
            }
        }

        foreach (var tri in allTris) {
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

                    float bSum = tbuf[p00 + 0] * k00 + tbuf[p10 + 0] * k10 + tbuf[p01 + 0] * k01 + tbuf[p11 + 0] * k11;
                    float gSum = tbuf[p00 + 1] * k00 + tbuf[p10 + 1] * k10 + tbuf[p01 + 1] * k01 + tbuf[p11 + 1] * k11;
                    float rSum = tbuf[p00 + 2] * k00 + tbuf[p10 + 2] * k10 + tbuf[p01 + 2] * k01 + tbuf[p11 + 2] * k11;
                    float aSum = tbuf[p00 + 3] * k00 + tbuf[p10 + 3] * k10 + tbuf[p01 + 3] * k01 + tbuf[p11 + 3] * k11;
                    if (aSum <= 0.5f && bSum <= 0.5f && gSum <= 0.5f && rSum <= 0.5f) continue;

                    // Live2DViewerEX DefaultPMAShader (PMA): Blend One OneMinusSrcAlpha / Additive: Blend One One
                    float sbVal = bSum * tb * ta;
                    float sgVal = gSum * tg * ta;
                    float srVal = rSum * tr * ta;
                    float srcAlpha = (aSum / 255.0f) * ta;
                    if (srcAlpha > 1.0f) srcAlpha = 1.0f;

                    int dstIdx = (rowOff + px) * 4;
                    float dbVal = canvas[dstIdx + 0];
                    float dgVal = canvas[dstIdx + 1];
                    float drVal = canvas[dstIdx + 2];

                    float ob, og, orVal;
                    if (blend == BlendMode.Additive) {
                        ob = Math.Min(255f, dbVal + sbVal);
                        og = Math.Min(255f, dgVal + sgVal);
                        orVal = Math.Min(255f, drVal + srVal);
                    } else if (blend == BlendMode.Multiply) {
                        float invA = 1.0f - srcAlpha;
                        ob = dbVal * (sbVal / 255f + invA);
                        og = dgVal * (sgVal / 255f + invA);
                        orVal = drVal * (srVal / 255f + invA);
                    } else if (blend == BlendMode.Screen) {
                        ob = sbVal + dbVal * (1f - sbVal / 255f);
                        og = sgVal + dgVal * (1f - sgVal / 255f);
                        orVal = srVal + drVal * (1f - srVal / 255f);
                    } else {
                        float invA = 1.0f - srcAlpha;
                        ob = sbVal + dbVal * invA;
                        og = sgVal + dgVal * invA;
                        orVal = srVal + drVal * invA;
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

                if (withHits) {
                    int xStart = (int)(Math.Ceiling(minX / 200.0) * 200);
                    int xEnd = (int)(Math.Floor(maxX / 200.0) * 200);
                    int yStart = (int)(Math.Ceiling(minY / 200.0) * 200);
                    int yEnd = (int)(Math.Floor(maxY / 200.0) * 200);
                    int labelStep = 200;
                    while (labelStep * scale < 38f) labelStep += 200;
                    using (var gridPen = new Pen(Color.FromArgb(38, 255, 255, 255), 1f))
                    using (var axisPen = new Pen(Color.FromArgb(85, 110, 195, 255), 1f))
                    using (var borderPen = new Pen(Color.FromArgb(110, 140, 155, 175), 1f))
                    using (var axisFont = new Font("Microsoft YaHei", 7.0f, FontStyle.Regular))
                    using (var axisBrush = new SolidBrush(Color.FromArgb(205, 210, 220, 230))) {
                        for (int gx = xStart; gx <= xEnd; gx += 200) {
                            float sx = originX + (gx - minX) * scale;
                            if (sx < marginLeft || sx > imgW - marginRight) continue;
                            g.DrawLine(gx == 0 ? axisPen : gridPen, sx, marginTop, sx, imgH - marginBottom);
                            if (gx % labelStep == 0) {
                                string txt = gx.ToString();
                                var sz = g.MeasureString(txt, axisFont);
                                float tx = Math.Max(marginLeft, Math.Min(imgW - sz.Width - 2, sx - sz.Width * 0.5f));
                                g.DrawString(txt, axisFont, axisBrush, tx, imgH - marginBottom + 4);
                            }
                        }
                        for (int gy = yStart; gy <= yEnd; gy += 200) {
                            float sy = marginTop + (maxY - gy) * scale;
                            if (sy < marginTop || sy > imgH - marginBottom) continue;
                            g.DrawLine(gy == 0 ? axisPen : gridPen, marginLeft, sy, imgW - marginRight, sy);
                            if (gy % labelStep == 0) {
                                string txt = gy.ToString();
                                var sz = g.MeasureString(txt, axisFont);
                                float ty = Math.Max(marginTop, Math.Min(imgH - marginBottom - sz.Height, sy - sz.Height * 0.5f));
                                g.DrawString(txt, axisFont, axisBrush, marginLeft - 4 - sz.Width, ty);
                            }
                        }
                        g.DrawRectangle(borderPen, marginLeft, marginTop, imgW - marginLeft - marginRight, imgH - marginTop - marginBottom);
                    }
                }

                if (hasBgBox) {
                    float x0 = originX + (bgMinX - minX) * scale;
                    float y0 = marginTop + (maxY - bgMaxY) * scale;
                    float w = (bgMaxX - bgMinX) * scale;
                    float h = (bgMaxY - bgMinY) * scale;
                    int alpha = withHits ? 220 : 140;
                    float pw = withHits ? 2.0f : 1.0f;
                    using (var pen = new Pen(Color.FromArgb(alpha, 0, 235, 255), pw) { DashStyle = DashStyle.Dash }) {
                        g.DrawRectangle(pen, x0, y0, w, h);
                    }
                }

                if (withHits) {
                    var colorMap = new Dictionary<string, Color>();
                    colorMap["头"] = Color.FromArgb(255, 215, 0);
                    colorMap["胸"] = Color.FromArgb(255, 92, 168);
                    colorMap["左手"] = Color.FromArgb(0, 225, 255);
                    colorMap["右手"] = Color.FromArgb(80, 240, 120);
                    colorMap["腿"] = Color.FromArgb(255, 165, 35);
                    colorMap["足"] = Color.FromArgb(196, 130, 255);

                    using (var lblFont = new Font("Microsoft YaHei", 7.5f, FontStyle.Bold)) {
                        var usedLabels = new List<RectangleF>();
                        foreach (var hb in mainHits) {
                            if (!hb.BoneFound) continue;
                            Color baseCol = colorMap.ContainsKey(hb.Name) ? colorMap[hb.Name] : Color.White;
                            Color col = hb.OutOfBg ? Color.FromArgb(255, 45, 45) : baseCol;
                            float boxPenW = hb.OutOfBg ? 3.0f : 1.8f;

                            float px = originX + ((hb.BoxCx - hb.BoxW * 0.5f) - minX) * scale;
                            float py = marginTop + (maxY - (hb.BoxCy + hb.BoxH * 0.5f)) * scale;
                            float pw = Math.Max(4f, hb.BoxW * scale);
                            float ph = Math.Max(4f, hb.BoxH * scale);
                            float bpx = originX + (hb.BoneWx - minX) * scale;
                            float bpy = marginTop + (maxY - hb.BoneWy) * scale;

                            using (var fillBr = new SolidBrush(Color.FromArgb(hb.OutOfBg ? 55 : 28, col)))
                            using (var boxPen = new Pen(Color.FromArgb(240, col), boxPenW)) {
                                g.FillRectangle(fillBr, px, py, pw, ph);
                                g.DrawRectangle(boxPen, px, py, pw, ph);
                            }
                            using (var ptPen = new Pen(Color.FromArgb(245, col), 1.5f)) {
                                g.DrawLine(ptPen, bpx - 4f, bpy, bpx + 4f, bpy);
                                g.DrawLine(ptPen, bpx, bpy - 4f, bpx, bpy + 4f);
                            }

                            string lbl = hb.OutOfBg
                                ? string.Format("{0}({1}) [OUT!]", hb.Name, hb.BoneId)
                                : string.Format("{0}({1})", hb.Name, hb.BoneId);
                            var sz = g.MeasureString(lbl, lblFont);
                            float lx = Math.Max(marginLeft + 1f, Math.Min(imgW - sz.Width - 4f, px));
                            float ly = py - sz.Height - 2f;
                            if (ly < marginTop + 2f) ly = py + 2f;
                            for (int guard = 0; guard < 10; guard++) {
                                var cand = new RectangleF(lx, ly, sz.Width + 4f, sz.Height + 2f);
                                bool hit = false;
                                foreach (var u in usedLabels) {
                                    if (cand.IntersectsWith(u)) { hit = true; break; }
                                }
                                if (!hit) break;
                                ly += sz.Height + 2f;
                            }
                            var rect = new RectangleF(lx - 1f, ly - 1f, sz.Width + 4f, sz.Height + 1f);
                            usedLabels.Add(rect);
                            using (var pillBr = new SolidBrush(Color.FromArgb(215, 16, 18, 26)))
                            using (var pillPen = new Pen(col, 1f))
                            using (var txtBr = new SolidBrush(col)) {
                                g.FillRectangle(pillBr, rect);
                                g.DrawRectangle(pillPen, rect.X, rect.Y, rect.Width, rect.Height);
                                g.DrawString(lbl, lblFont, txtBr, rect.X + 2f, rect.Y);
                            }
                        }
                    }
                }

                string bgStatus = "";
                if (withHits) {
                    bgStatus = hasBgBox
                        ? (outOfBgCount > 0 ? string.Format(" | [OUT_OF_BG={0}]", outOfBgCount) : " | [BG_OK]")
                        : " | [NO_BG]";
                }
                string header = string.Format("#{0:000} {1} | {2}{3}", index, rel, string.Join(" ", layerLabels), bgStatus);
                using (var hdrFont = new Font("Microsoft YaHei", 8.0f, FontStyle.Bold))
                using (var hdrBrush = new SolidBrush(withHits && outOfBgCount > 0 ? Color.FromArgb(255, 130, 130) : Color.FromArgb(240, 245, 255))) {
                    g.DrawString(header, hdrFont, hdrBrush, marginLeft, 6f);
                }
            }

            string[] parts = rel.Split('/');
            string sfx = string.IsNullOrEmpty(tag) ? "" : ("_" + tag);
            string stem = string.Format("{0:000}_{1}__{2}{3}", index, parts[0], parts[1], sfx);
            string outPath = Path.Combine(outDir, stem + ".jpg");

            ImageCodecInfo jpgEnc = null;
            foreach (var c in ImageCodecInfo.GetImageEncoders()) {
                if (c.MimeType == "image/jpeg") { jpgEnc = c; break; }
            }
            using (var eps = new EncoderParameters(1)) {
                eps.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 80L);
                bmp.Save(outPath, jpgEnc, eps);
            }

            if (emitMeta) {
                var meta = new Dictionary<string, object>();
                meta["rel"] = rel;
                meta["index"] = index;
                meta["jpg"] = outPath;
                meta["base_scale"] = baseScale;
                meta["has_bg_box"] = hasBgBox;
                meta["out_of_bg_count"] = outOfBgCount;
                meta["submodels"] = layerLabels;
                if (hasBgBox) {
                    var br = new Dictionary<string, object>();
                    br["x0"] = Math.Round(bgMinX, 2);
                    br["x1"] = Math.Round(bgMaxX, 2);
                    br["y0"] = Math.Round(bgMinY, 2);
                    br["y1"] = Math.Round(bgMaxY, 2);
                    meta["bg_rect"] = br;
                } else {
                    meta["bg_rect"] = null;
                }
                if (mainMinX <= mainMaxX) {
                    var mb = new Dictionary<string, object>();
                    mb["x0"] = Math.Round(mainMinX, 2);
                    mb["x1"] = Math.Round(mainMaxX, 2);
                    mb["y0"] = Math.Round(mainMinY, 2);
                    mb["y1"] = Math.Round(mainMaxY, 2);
                    meta["main_bbox"] = mb;
                } else {
                    meta["main_bbox"] = null;
                }
                var hitList = new List<Dictionary<string, object>>();
                foreach (var hb in mainHits) {
                    var hd = new Dictionary<string, object>();
                    hd["name"] = hb.Name;
                    hd["id"] = hb.BoneId;
                    hd["motion"] = hb.Motion;
                    hd["bone_found"] = hb.BoneFound;
                    hd["bone_wx"] = Math.Round(hb.BoneWx, 2);
                    hd["bone_wy"] = Math.Round(hb.BoneWy, 2);
                    hd["cx"] = Math.Round(hb.BoxCx, 2);
                    hd["cy"] = Math.Round(hb.BoxCy, 2);
                    hd["x0"] = Math.Round(hb.BoxCx - hb.BoxW * 0.5f, 2);
                    hd["x1"] = Math.Round(hb.BoxCx + hb.BoxW * 0.5f, 2);
                    hd["y0"] = Math.Round(hb.BoxCy - hb.BoxH * 0.5f, 2);
                    hd["y1"] = Math.Round(hb.BoxCy + hb.BoxH * 0.5f, 2);
                    hd["w"] = Math.Round(hb.BoxW, 2);
                    hd["h"] = Math.Round(hb.BoxH, 2);
                    hd["ov_l"] = Math.Round(hb.OvL, 2);
                    hd["ov_r"] = Math.Round(hb.OvR, 2);
                    hd["ov_b"] = Math.Round(hb.OvB, 2);
                    hd["ov_t"] = Math.Round(hb.OvT, 2);
                    hd["out_of_bg"] = hb.OutOfBg;
                    hitList.Add(hd);
                }
                meta["hit_areas"] = hitList;
                var boneList = new List<Dictionary<string, object>>();
                foreach (var bm in mainBones) {
                    var bdDict = new Dictionary<string, object>();
                    bdDict["id"] = bm.Id;
                    bdDict["wx"] = Math.Round(bm.Wx, 2);
                    bdDict["wy"] = Math.Round(bm.Wy, 2);
                    bdDict["in_bg"] = bm.InBg;
                    bdDict["slots"] = bm.Slots;
                    boneList.Add(bdDict);
                }
                meta["bones"] = boneList;
                string metaPath = Path.Combine(outDir, stem + ".meta.json");
                File.WriteAllText(metaPath, jss.Serialize(meta), new UTF8Encoding(false));
            }
            return outPath;
        }
    }
}
'''


def ensure_compiled() -> Path:
    src_hash = hashlib.sha256(CS_SOURCE.encode("utf-8")).hexdigest()
    if EXE_PATH.is_file() and HASH_PATH.is_file() and HASH_PATH.read_text(encoding="utf-8").strip() == src_hash:
        return EXE_PATH
    CS_PATH.write_text(CS_SOURCE, encoding="utf-8")
    cmd = [
        str(CSC_EXE),
        "/nologo",
        "/optimize+",
        "/platform:x64",
        f"/out:{EXE_PATH}",
        f"/lib:{EX_MANAGED_DIR}",
        "/r:Assembly-CSharp.dll",
        "/r:UnityEngine.CoreModule.dll",
        "/r:System.Drawing.dll",
        "/r:System.Web.Extensions.dll",
        str(CS_PATH),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"csc.exe compile failed:\n{res.stdout}\n{res.stderr}")
    HASH_PATH.write_text(src_hash, encoding="utf-8")
    return EXE_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Render composite scene previews (main + all submodels) for SoulTide Spine packages.")
    parser.add_argument("--all", action="store_true", help="Render all Spine packages")
    parser.add_argument("--only", action="append", default=[], help="Render specific model(s), e.g. 叶隐琉璃/绵绵小懒虫")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR, help="Output directory for JPG previews")
    parser.add_argument("--tag", type=str, default="", help="Optional filename suffix tag (e.g. before / after)")
    parser.add_argument("--skip-fx", action="store_true", help="Skip fx_* submodels when rendering")
    parser.add_argument("--only-with-subs", action="store_true", help="With --all, only render models that have submodels")
    parser.add_argument("--with-hits", action="store_true", help="Overlay coordinate grid, bg_static box, and Spine hit_areas (red when out of bg)")
    parser.add_argument("--emit-meta", action="store_true", help="Write sibling .meta.json with live bg_rect, hit_areas bounds, and bone coords")
    args = parser.parse_args()

    exe = ensure_compiled()
    cmd = [str(exe), "--spine-root", str(SPINE_ROOT), "--out-dir", str(args.out_dir)]
    if args.tag:
        cmd.extend(["--tag", args.tag])
    if args.skip_fx:
        cmd.append("--skip-fx")
    if args.only_with_subs:
        cmd.append("--only-with-subs")
    if args.with_hits:
        cmd.append("--with-hits")
    if args.emit_meta:
        cmd.append("--emit-meta")
    if args.only:
        for r in args.only:
            cmd.extend(["--only", r])
    else:
        cmd.append("--all")

    res = subprocess.run(cmd, text=True)
    sys.exit(res.returncode)


if __name__ == "__main__":
    main()
