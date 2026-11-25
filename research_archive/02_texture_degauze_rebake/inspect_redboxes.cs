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
        var idle = data.FindAnimation("idle");
        if (idle != null) idle.Apply(skel, 0, 0, true, null, 1f, MixBlend.Setup, MixDirection.In);
        skel.UpdateWorldTransform();

        // Viewport matching 06_chest_context (700x700): cx = wx + 220, cy = 720 - wy
        // Let's zoom into the two red boxes: cx in [0..350], cy in [200..550]
        int xOff = 0, yOff = 200, W = 350, H = 350;
        var layers = new Dictionary<string, float[]>();
        foreach (string k in new[] { "96", "83", "83_1", "84", "99" }) {
            layers[k] = new float[W * H * 4];
        }

        float[] verts = new float[16384];
        int[] quadTris = new int[] { 0, 1, 2, 2, 3, 0 };
        var mesh83Lines = new List<string>();
        var mesh96Lines = new List<string>();

        foreach (var slot in skel.DrawOrder) {
            if (slot.Attachment == null || slot.A <= 0.001f || !slot.Bone.Active) continue;
            string sn = slot.Data.Name;
            if (!layers.ContainsKey(sn)) continue;

            var ra = slot.Attachment as RegionAttachment;
            var ma = slot.Attachment as MeshAttachment;
            LoadedTex tex = null;
            int[] tris = null;
            float[] uvs = null;
            if (ra != null) {
                var reg = ra.RendererObject as AtlasRegion;
                if (reg == null) continue;
                tex = reg.page.rendererObject as LoadedTex;
                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2);
                uvs = ra.UVs; tris = quadTris;
            } else if (ma != null) {
                var reg = ma.RendererObject as AtlasRegion;
                if (reg == null) continue;
                tex = reg.page.rendererObject as LoadedTex;
                int n = ma.WorldVerticesLength;
                if (verts.Length < n) verts = new float[n];
                ma.ComputeWorldVertices(slot, 0, n, verts, 0, 2);
                uvs = ma.UVs; tris = ma.Triangles;
            } else continue;

            if (sn == "83" || sn == "96") {
                var dstList = (sn == "83") ? mesh83Lines : mesh96Lines;
                for (int t = 0; t < tris.Length; t += 3) {
                    int i0 = tris[t]*2, i1 = tris[t+1]*2, i2 = tris[t+2]*2;
                    dstList.Add(string.Format("{0:F4},{1:F4},{2:F4},{3:F4},{4:F4},{5:F4},{6:F6},{7:F6},{8:F6},{9:F6},{10:F6},{11:F6}",
                        verts[i0]+220f, 720f-verts[i0+1], verts[i1]+220f, 720f-verts[i1+1], verts[i2]+220f, 720f-verts[i2+1],
                        uvs[i0]*tex.W, uvs[i0+1]*tex.H, uvs[i1]*tex.W, uvs[i1+1]*tex.H, uvs[i2]*tex.W, uvs[i2+1]*tex.H));
                }
            }

            float[] fb = layers[sn];
            float sr = slot.R, sg = slot.G, sb_ = slot.B, sa = slot.A;
            for (int t = 0; t < tris.Length; t += 3) {
                int i0 = tris[t]*2, i1 = tris[t+1]*2, i2 = tris[t+2]*2;
                float x0 = verts[i0]+220f-xOff, y0 = 720f-verts[i0+1]-yOff;
                float x1 = verts[i1]+220f-xOff, y1 = 720f-verts[i1+1]-yOff;
                float x2 = verts[i2]+220f-xOff, y2 = 720f-verts[i2+1]-yOff;
                float u0 = uvs[i0], v0 = uvs[i0+1];
                float u1 = uvs[i1], v1 = uvs[i1+1];
                float u2 = uvs[i2], v2 = uvs[i2+1];

                int bx0 = Math.Max(0, (int)Math.Floor(Math.Min(x0, Math.Min(x1, x2))));
                int bx1 = Math.Min(W-1, (int)Math.Ceiling(Math.Max(x0, Math.Max(x1, x2))));
                int by0 = Math.Max(0, (int)Math.Floor(Math.Min(y0, Math.Min(y1, y2))));
                int by1 = Math.Min(H-1, (int)Math.Ceiling(Math.Max(y0, Math.Max(y1, y2))));
                if (bx0 > bx1 || by0 > by1) continue;
                float denom = (y1-y2)*(x0-x2) + (x2-x1)*(y0-y2);
                if (Math.Abs(denom) < 1e-6f) continue;
                float invD = 1f / denom;
                for (int py = by0; py <= by1; py++) {
                    float fy = py + 0.5f;
                    for (int px = bx0; px <= bx1; px++) {
                        float fx = px + 0.5f;
                        float w0 = ((y1-y2)*(fx-x2) + (x2-x1)*(fy-y2))*invD;
                        if (w0 < -1e-4f) continue;
                        float w1 = ((y2-y0)*(fx-x2) + (x0-x2)*(fy-y2))*invD;
                        if (w1 < -1e-4f) continue;
                        float w2 = 1f - w0 - w1;
                        if (w2 < -1e-4f) continue;
                        float u = w0*u0 + w1*u1 + w2*u2;
                        float v = w0*v0 + w1*v1 + w2*v2;
                        int tx = Math.Max(0, Math.Min(tex.W-1, (int)(u*tex.W)));
                        int ty = Math.Max(0, Math.Min(tex.H-1, (int)(v*tex.H)));
                        int ti = (ty*tex.W + tx)*4;
                        int fi = (py*W + px)*4;
                        fb[fi+0] = tex.Bgra[ti+2]/255f*sr;
                        fb[fi+1] = tex.Bgra[ti+1]/255f*sg;
                        fb[fi+2] = tex.Bgra[ti+0]/255f*sb_;
                        fb[fi+3] = tex.Bgra[ti+3]/255f*sa;
                    }
                }
            }
        }

        File.WriteAllLines(Path.Combine(outDir, "mesh_83_idle0.csv"), mesh83Lines);
        File.WriteAllLines(Path.Combine(outDir, "mesh_96_idle0.csv"), mesh96Lines);
        foreach (var kv in layers) {
            using (var bmp = new Bitmap(W, H, PixelFormat.Format32bppArgb)) {
                var bd = bmp.LockBits(new Rectangle(0, 0, W, H), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
                byte[] buf = new byte[W*H*4];
                for (int i = 0; i < W*H; i++) {
                    buf[i*4+0] = (byte)(Math.Max(0, Math.Min(1, kv.Value[i*4+2]))*255);
                    buf[i*4+1] = (byte)(Math.Max(0, Math.Min(1, kv.Value[i*4+1]))*255);
                    buf[i*4+2] = (byte)(Math.Max(0, Math.Min(1, kv.Value[i*4+0]))*255);
                    buf[i*4+3] = (byte)(Math.Max(0, Math.Min(1, kv.Value[i*4+3]))*255);
                }
                Marshal.Copy(buf, 0, bd.Scan0, buf.Length);
                bmp.UnlockBits(bd);
                bmp.Save(Path.Combine(outDir, "layer_" + kv.Key + "_redbox.png"), ImageFormat.Png);
            }
        }
        Console.WriteLine("Saved per-layer redbox renders + mesh_83/96 idle0 CSVs!");
        return 0;
    }
}
