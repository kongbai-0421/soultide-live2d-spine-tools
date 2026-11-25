using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using Spine3_8;

class LoadedTex { public int W, H; public byte[] Bgra; }
class PngTexLoader : TextureLoader {
    public string OverridePng;
    public void Load(AtlasPage page, string path) {
        string loadPath = !string.IsNullOrEmpty(OverridePng) ? OverridePng : path;
        using (var src = new Bitmap(loadPath))
        using (var bmp = new Bitmap(src.Width, src.Height, PixelFormat.Format32bppArgb)) {
            using (var g = Graphics.FromImage(bmp)) {
                g.CompositingMode = System.Drawing.Drawing2D.CompositingMode.SourceCopy;
                g.DrawImage(src, 0, 0, src.Width, src.Height);
            }
            var bd = bmp.LockBits(new Rectangle(0, 0, bmp.Width, bmp.Height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            byte[] buf = new byte[bmp.Width * bmp.Height * 4];
            Marshal.Copy(bd.Scan0, buf, 0, buf.Length);
            bmp.UnlockBits(bd);
            page.rendererObject = new LoadedTex { W = bmp.Width, H = bmp.Height, Bgra = buf };
        }
    }
    public void Unload(object texture) {}
}

class Program {
    static readonly string ManagedDir = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";
    static int Main(string[] args) {
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            string name = new AssemblyName(e.Name).Name + ".dll";
            string cand = Path.Combine(ManagedDir, name);
            return File.Exists(cand) ? Assembly.LoadFrom(cand) : null;
        };
        return Run(args);
    }

    static void SampleBilinear(LoadedTex tex, float u, float v, out float r, out float g, out float b, out float a) {
        float fx = u * tex.W - 0.5f;
        float fy = v * tex.H - 0.5f;
        int x0 = (int)Math.Floor(fx), y0 = (int)Math.Floor(fy);
        float tx = fx - x0, ty = fy - y0;
        int x1 = x0 + 1, y1 = y0 + 1;
        if (x0 < 0) x0 = 0; if (x0 >= tex.W) x0 = tex.W - 1;
        if (x1 < 0) x1 = 0; if (x1 >= tex.W) x1 = tex.W - 1;
        if (y0 < 0) y0 = 0; if (y0 >= tex.H) y0 = tex.H - 1;
        if (y1 < 0) y1 = 0; if (y1 >= tex.H) y1 = tex.H - 1;
        int i00 = (y0 * tex.W + x0) * 4, i10 = (y0 * tex.W + x1) * 4;
        int i01 = (y1 * tex.W + x0) * 4, i11 = (y1 * tex.W + x1) * 4;
        float w00 = (1f - tx) * (1f - ty), w10 = tx * (1f - ty), w01 = (1f - tx) * ty, w11 = tx * ty;
        b = (tex.Bgra[i00] * w00 + tex.Bgra[i10] * w10 + tex.Bgra[i01] * w01 + tex.Bgra[i11] * w11) / 255f;
        g = (tex.Bgra[i00+1] * w00 + tex.Bgra[i10+1] * w10 + tex.Bgra[i01+1] * w01 + tex.Bgra[i11+1] * w11) / 255f;
        r = (tex.Bgra[i00+2] * w00 + tex.Bgra[i10+2] * w10 + tex.Bgra[i01+2] * w01 + tex.Bgra[i11+2] * w11) / 255f;
        a = (tex.Bgra[i00+3] * w00 + tex.Bgra[i10+3] * w10 + tex.Bgra[i01+3] * w01 + tex.Bgra[i11+3] * w11) / 255f;
    }

    static int Run(string[] args) {
        string dir = @"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织";
        string atlasPath = Path.Combine(dir, "SoulDress_Lilyiro_05.atlas.txt");
        string skelPath = Path.Combine(dir, "SoulDress_Lilyiro_05.skel.json");
        string overridePng = args.Length >= 1 && args[0] != "-" ? args[0] : @"E:\A灵魂潮汐\人偶spine\Texture2D\SoulDress_Lilyiro_05.png";
        string outPath = args.Length >= 2 ? args[1] : @".\_scratch\edge_noise_study\render_setup.png";
        bool useIdle = args.Length >= 3 && args[2] == "idle";
        float animT = args.Length >= 4 ? float.Parse(args[3], System.Globalization.CultureInfo.InvariantCulture) : 0f;

        Atlas atlas;
        using (var sr = new StreamReader(atlasPath, System.Text.Encoding.UTF8))
            atlas = new Atlas(sr, dir, new PngTexLoader { OverridePng = overridePng });
        var data = new SkeletonBinary(new AtlasAttachmentLoader(atlas)).ReadSkeletonData(skelPath);
        Console.Write("Animations: ");
        foreach (var an in data.Animations) Console.Write(an.Name + "(" + an.Duration.ToString("F2") + "s) ");
        Console.WriteLine();

        var skel = new Skeleton(data);
        skel.SetToSetupPose();
        if (useIdle) {
            var idle = data.FindAnimation("idle");
            if (idle != null) idle.Apply(skel, animT, animT, true, null, 1f, MixBlend.Setup, MixDirection.In);
        }
        skel.UpdateWorldTransform();

        int minX = 0, maxX = 800, minY = 480, maxY = 1280;
        int W = maxX - minX, H = maxY - minY;
        float[] fb = new float[W * H * 4];
        for (int i = 0; i < W * H; i++) {
            fb[i*4+0] = 0.72f; fb[i*4+1] = 0.68f; fb[i*4+2] = 0.88f; fb[i*4+3] = 1f;
        }
        float[] verts = new float[16384];
        int[] quadTris = new int[] { 0, 1, 2, 2, 3, 0 };

        foreach (var slot in skel.DrawOrder) {
            if (slot.Attachment == null || slot.A <= 0.001f || !slot.Bone.Active) continue;
            var ra = slot.Attachment as RegionAttachment;
            var ma = slot.Attachment as MeshAttachment;
            LoadedTex tex = null; int[] tris = null; float[] uvs = null;
            if (ra != null) {
                var reg = ra.RendererObject as AtlasRegion; if (reg == null) continue;
                tex = reg.page.rendererObject as LoadedTex;
                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2); uvs = ra.UVs; tris = quadTris;
            } else if (ma != null) {
                var reg = ma.RendererObject as AtlasRegion; if (reg == null) continue;
                tex = reg.page.rendererObject as LoadedTex;
                int vlen = ma.WorldVerticesLength; if (verts.Length < vlen) verts = new float[vlen];
                ma.ComputeWorldVertices(slot, 0, vlen, verts, 0, 2); uvs = ma.UVs; tris = ma.Triangles;
            } else continue;

            float sr = slot.R, sg = slot.G, sb_ = slot.B, sa = slot.A;
            bool additive = slot.Data.BlendMode == BlendMode.Additive;

            for (int t = 0; t < tris.Length; t += 3) {
                int i0 = tris[t]*2, i1 = tris[t+1]*2, i2 = tris[t+2]*2;
                float x0 = verts[i0] - minX, y0 = maxY - verts[i0+1];
                float x1 = verts[i1] - minX, y1 = maxY - verts[i1+1];
                float x2 = verts[i2] - minX, y2 = maxY - verts[i2+1];
                float u0 = uvs[i0], v0 = uvs[i0+1], u1 = uvs[i1], v1 = uvs[i1+1], u2 = uvs[i2], v2 = uvs[i2+1];
                int bx0 = Math.Max(0, (int)Math.Floor(Math.Min(x0, Math.Min(x1, x2))));
                int bx1 = Math.Min(W - 1, (int)Math.Ceiling(Math.Max(x0, Math.Max(x1, x2))));
                int by0 = Math.Max(0, (int)Math.Floor(Math.Min(y0, Math.Min(y1, y2))));
                int by1 = Math.Min(H - 1, (int)Math.Ceiling(Math.Max(y0, Math.Max(y1, y2))));
                if (bx0 > bx1 || by0 > by1) continue;
                float denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2);
                if (Math.Abs(denom) < 1e-6f) continue;
                float invD = 1f / denom;
                for (int py = by0; py <= by1; py++) {
                    float fy = py + 0.5f;
                    for (int px = bx0; px <= bx1; px++) {
                        float fx = px + 0.5f;
                        float w0 = ((y1 - y2) * (fx - x2) + (x2 - x1) * (fy - y2)) * invD;
                        if (w0 < -1e-4f) continue;
                        float w1 = ((y2 - y0) * (fx - x2) + (x0 - x2) * (fy - y2)) * invD;
                        if (w1 < -1e-4f) continue;
                        float w2 = 1f - w0 - w1;
                        if (w2 < -1e-4f) continue;
                        float u = w0 * u0 + w1 * u1 + w2 * u2;
                        float v = w0 * v0 + w1 * v1 + w2 * v2;
                        float r, g, b, a;
                        SampleBilinear(tex, u, v, out r, out g, out b, out a);
                        r *= sr; g *= sg; b *= sb_; a *= sa;
                        int fi = (py * W + px) * 4;
                        if (additive) { fb[fi+0] += r; fb[fi+1] += g; fb[fi+2] += b; }
                        else {
                            float invA = 1f - a;
                            fb[fi+0] = r + fb[fi+0] * invA;
                            fb[fi+1] = g + fb[fi+1] * invA;
                            fb[fi+2] = b + fb[fi+2] * invA;
                            fb[fi+3] = a + fb[fi+3] * invA;
                        }
                    }
                }
            }
        }
        using (var bmp = new Bitmap(W, H, PixelFormat.Format32bppArgb)) {
            var bd = bmp.LockBits(new Rectangle(0, 0, W, H), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
            byte[] outBuf = new byte[W * H * 4];
            for (int i = 0; i < W * H; i++) {
                outBuf[i*4+0] = (byte)(Math.Max(0f, Math.Min(1f, fb[i*4+2])) * 255f);
                outBuf[i*4+1] = (byte)(Math.Max(0f, Math.Min(1f, fb[i*4+1])) * 255f);
                outBuf[i*4+2] = (byte)(Math.Max(0f, Math.Min(1f, fb[i*4+0])) * 255f);
                outBuf[i*4+3] = 255;
            }
            Marshal.Copy(outBuf, 0, bd.Scan0, outBuf.Length);
            bmp.UnlockBits(bd);
            bmp.Save(outPath, ImageFormat.Png);
        }
        Console.WriteLine("Saved " + outPath);
        return 0;
    }
}
