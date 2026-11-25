using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using Spine3_8;

class LoadedTex {
    public int W, H;
    public byte[] Bgra;
}

class PngTexLoader : TextureLoader {
    public void Load(AtlasPage page, string path) {
        using (var src = new Bitmap(path))
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

    static int Run(string[] args) {
        string dir = @"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织";
        string atlasPath = Path.Combine(dir, "SoulDress_Lilyiro_05.atlas.txt");
        string skelPath = Path.Combine(dir, "SoulDress_Lilyiro_05.skel.json");
        string outDir = @".\_scratch\lilyiro05_inspect";

        Atlas atlas;
        using (var sr = new StreamReader(atlasPath, System.Text.Encoding.UTF8)) {
            atlas = new Atlas(sr, dir, new PngTexLoader());
        }
        var sb = new SkeletonBinary(new AtlasAttachmentLoader(atlas));
        var data = sb.ReadSkeletonData(skelPath);
        var skel = new Skeleton(data);
        skel.SetToSetupPose();
        skel.UpdateWorldTransform();

        // Render full body setup pose: x in [-1150, 1350], y in [-520, 1180]
        int minX = -1150, maxX = 1350, minY = -520, maxY = 1180;
        int W = maxX - minX, H = maxY - minY;
        float[] fb = new float[W * H * 4];
        float[] fb83_1 = new float[W * H * 4];
        float[] fb96 = new float[W * H * 4];

        float[] verts = new float[16384];
        int[] quadTris = new int[] { 0, 1, 2, 2, 3, 0 };

        // Also dump exact 83_1 mesh triangles (world XY + atlas pixel XY)
        var meshLines = new List<string>();

        foreach (var slot in skel.DrawOrder) {
            if (slot.Attachment == null || slot.A <= 0.001f || !slot.Bone.Active) continue;
            var ra = slot.Attachment as RegionAttachment;
            var ma = slot.Attachment as MeshAttachment;
            LoadedTex tex = null;
            int[] tris = null;
            float[] uvs = null;
            int vlen = 0;

            if (ra != null) {
                var reg = ra.RendererObject as AtlasRegion;
                if (reg == null) continue;
                tex = reg.page.rendererObject as LoadedTex;
                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2);
                uvs = ra.UVs;
                tris = quadTris;
                vlen = 8;
            } else if (ma != null) {
                var reg = ma.RendererObject as AtlasRegion;
                if (reg == null) continue;
                tex = reg.page.rendererObject as LoadedTex;
                vlen = ma.WorldVerticesLength;
                if (verts.Length < vlen) verts = new float[vlen];
                ma.ComputeWorldVertices(slot, 0, vlen, verts, 0, 2);
                uvs = ma.UVs;
                tris = ma.Triangles;
            } else continue;

            if (tex == null) continue;
            bool is83_1 = slot.Data.Name == "83_1";
            bool is96 = slot.Data.Name == "96";

            if (is83_1) {
                for (int t = 0; t < tris.Length; t += 3) {
                    int i0 = tris[t]*2, i1 = tris[t+1]*2, i2 = tris[t+2]*2;
                    meshLines.Add(string.Format("{0:F4},{1:F4},{2:F4},{3:F4},{4:F4},{5:F4},{6:F6},{7:F6},{8:F6},{9:F6},{10:F6},{11:F6}",
                        verts[i0], verts[i0+1], verts[i1], verts[i1+1], verts[i2], verts[i2+1],
                        uvs[i0]*tex.W, uvs[i0+1]*tex.H, uvs[i1]*tex.W, uvs[i1+1]*tex.H, uvs[i2]*tex.W, uvs[i2+1]*tex.H));
                }
            }

            float sr = slot.R, sg = slot.G, sb_ = slot.B, sa = slot.A;
            bool additive = slot.Data.BlendMode == BlendMode.Additive;

            for (int t = 0; t < tris.Length; t += 3) {
                int i0 = tris[t] * 2, i1 = tris[t+1] * 2, i2 = tris[t+2] * 2;
                float x0 = verts[i0] - minX, y0 = maxY - verts[i0+1];
                float x1 = verts[i1] - minX, y1 = maxY - verts[i1+1];
                float x2 = verts[i2] - minX, y2 = maxY - verts[i2+1];
                float u0 = uvs[i0], v0 = uvs[i0+1];
                float u1 = uvs[i1], v1 = uvs[i1+1];
                float u2 = uvs[i2], v2 = uvs[i2+1];

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
                        int tx = Math.Max(0, Math.Min(tex.W - 1, (int)(u * tex.W)));
                        int ty = Math.Max(0, Math.Min(tex.H - 1, (int)(v * tex.H)));
                        int ti = (ty * tex.W + tx) * 4;
                        float a = tex.Bgra[ti + 3] / 255f * sa;
                        float r = tex.Bgra[ti + 2] / 255f * sr;
                        float g = tex.Bgra[ti + 1] / 255f * sg;
                        float b = tex.Bgra[ti + 0] / 255f * sb_;

                        int fi = (py * W + px) * 4;
                        if (additive) {
                            fb[fi+0] += r; fb[fi+1] += g; fb[fi+2] += b;
                        } else {
                            float invA = 1f - a;
                            fb[fi+0] = r + fb[fi+0] * invA;
                            fb[fi+1] = g + fb[fi+1] * invA;
                            fb[fi+2] = b + fb[fi+2] * invA;
                            fb[fi+3] = a + fb[fi+3] * invA;
                        }
                        if (is83_1) {
                            fb83_1[fi+0] = r; fb83_1[fi+1] = g; fb83_1[fi+2] = b; fb83_1[fi+3] = a;
                        }
                        if (is96) {
                            fb96[fi+0] = r; fb96[fi+1] = g; fb96[fi+2] = b; fb96[fi+3] = a;
                        }
                    }
                }
            }
        }

        File.WriteAllLines(Path.Combine(outDir, "mesh_83_1_setup.csv"), meshLines);
        SaveFb(fb, W, H, Path.Combine(outDir, "setup_pose_full.png"));
        SaveFb(fb96, W, H, Path.Combine(outDir, "setup_pose_96.png"));
        Console.WriteLine("Done setup pose render, 83_1 tris=" + meshLines.Count);
        return 0;
    }

    static void SaveFb(float[] fb, int W, int H, string path) {
        using (var bmp = new Bitmap(W, H, PixelFormat.Format32bppArgb)) {
            var bd = bmp.LockBits(new Rectangle(0, 0, W, H), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
            byte[] outBuf = new byte[W * H * 4];
            for (int i = 0; i < W * H; i++) {
                float a = Math.Max(0f, Math.Min(1f, fb[i*4+3]));
                float r = Math.Max(0f, Math.Min(1f, fb[i*4+0]));
                float g = Math.Max(0f, Math.Min(1f, fb[i*4+1]));
                float b = Math.Max(0f, Math.Min(1f, fb[i*4+2]));
                outBuf[i*4+0] = (byte)(b * 255f);
                outBuf[i*4+1] = (byte)(g * 255f);
                outBuf[i*4+2] = (byte)(r * 255f);
                outBuf[i*4+3] = (byte)(a * 255f);
            }
            Marshal.Copy(outBuf, 0, bd.Scan0, outBuf.Length);
            bmp.UnlockBits(bd);
            bmp.Save(path, ImageFormat.Png);
        }
    }
}
