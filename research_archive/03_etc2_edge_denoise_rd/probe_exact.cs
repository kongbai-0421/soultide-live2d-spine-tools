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
        return Run();
    }

    static int Run() {
        string dir = @"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织";
        string atlasPath = Path.Combine(dir, "SoulDress_Lilyiro_05.atlas.txt");
        string skelPath = Path.Combine(dir, "SoulDress_Lilyiro_05.skel.json");
        Atlas atlas;
        using (var sr = new StreamReader(atlasPath, System.Text.Encoding.UTF8))
            atlas = new Atlas(sr, dir, new PngTexLoader { OverridePng = @"E:\A灵魂潮汐\人偶spine\Texture2D\SoulDress_Lilyiro_05.png" });
        var data = new SkeletonBinary(new AtlasAttachmentLoader(atlas)).ReadSkeletonData(skelPath);
        var skel = new Skeleton(data);
        skel.SetToSetupPose();
        skel.UpdateWorldTransform();

        // Probe exact render_setup.png pixel coordinates (minX=0, maxY=1280):
        // Row 2 crop was (100, 440, 260, 600) -> dotted diagonal across arm is around (px=175..210, py=560..585)
        // Row 3 crop was (400, 500, 560, 660) -> diagonal line above blue eye is around (px=445..475, py=570..595)
        // Row 4 crop was (640, 600, 800, 760) -> top-left dotted line is around (px=660..690, py=620..660)
        int[,] probes = new int[,] {
            {185, 575}, {200, 565}, {215, 555},
            {455, 585}, {465, 575},
            {675, 640}
        };
        float[] verts = new float[16384];
        int[] quadTris = new int[] { 0, 1, 2, 2, 3, 0 };

        for (int p = 0; p < probes.GetLength(0); p++) {
            float wx = probes[p, 0] + 0.5f;
            float wy = 1280f - (probes[p, 1] + 0.5f);
            Console.WriteLine(string.Format("=== Probe render({0},{1}) -> world({2:F1},{3:F1}) ===", probes[p,0], probes[p,1], wx, wy));
            foreach (var slot in skel.DrawOrder) {
                if (slot.Attachment == null || slot.A <= 0.001f || !slot.Bone.Active) continue;
                var ra = slot.Attachment as RegionAttachment;
                var ma = slot.Attachment as MeshAttachment;
                LoadedTex tex = null; int[] tris = null; float[] uvs = null; AtlasRegion reg = null;
                if (ra != null) { reg = ra.RendererObject as AtlasRegion; tex = reg.page.rendererObject as LoadedTex; ra.ComputeWorldVertices(slot.Bone, verts, 0, 2); uvs = ra.UVs; tris = quadTris; }
                else if (ma != null) { reg = ma.RendererObject as AtlasRegion; tex = reg.page.rendererObject as LoadedTex; int vlen = ma.WorldVerticesLength; if (verts.Length < vlen) verts = new float[vlen]; ma.ComputeWorldVertices(slot, 0, vlen, verts, 0, 2); uvs = ma.UVs; tris = ma.Triangles; }
                else continue;

                for (int t = 0; t < tris.Length; t += 3) {
                    int i0 = tris[t]*2, i1 = tris[t+1]*2, i2 = tris[t+2]*2;
                    float x0 = verts[i0], y0 = verts[i0+1], x1 = verts[i1], y1 = verts[i1+1], x2 = verts[i2], y2 = verts[i2+1];
                    float denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2);
                    if (Math.Abs(denom) < 1e-6f) continue;
                    float w0 = ((y1 - y2) * (wx - x2) + (x2 - x1) * (wy - y2)) / denom;
                    float w1 = ((y2 - y0) * (wx - x2) + (x0 - x2) * (wy - y2)) / denom;
                    float w2 = 1f - w0 - w1;
                    if (w0 >= -1e-3f && w1 >= -1e-3f && w2 >= -1e-3f) {
                        float u = (w0*uvs[i0] + w1*uvs[i1] + w2*uvs[i2]) * tex.W;
                        float v = (w0*uvs[i0+1] + w1*uvs[i1+1] + w2*uvs[i2+1]) * tex.H;
                        int tx = Math.Max(0, Math.Min(tex.W-1, (int)u)), ty = Math.Max(0, Math.Min(tex.H-1, (int)v));
                        // Check 3x3 max alpha around (tx, ty)
                        int maxA = 0, maxR = 0;
                        for (int dy=-2; dy<=2; dy++) for (int dx=-2; dx<=2; dx++) {
                            int nx = Math.Max(0, Math.Min(tex.W-1, tx+dx)), ny = Math.Max(0, Math.Min(tex.H-1, ty+dy));
                            int ni = (ny*tex.W + nx)*4;
                            if (tex.Bgra[ni+3] > maxA) maxA = tex.Bgra[ni+3];
                            int mx = Math.Max(tex.Bgra[ni], Math.Max(tex.Bgra[ni+1], tex.Bgra[ni+2]));
                            if (mx > maxR) maxR = mx;
                        }
                        int ti = (ty*tex.W + tx)*4;
                        if (maxA > 0 || maxR > 0) {
                            Console.WriteLine(string.Format("  Slot {0,-8} reg={1,-6} uv=({2:F1},{3:F1}) RGBA=({4},{5},{6},{7}) 5x5_maxA={8}",
                                slot.Data.Name, reg.name, u, v, tex.Bgra[ti+2], tex.Bgra[ti+1], tex.Bgra[ti], tex.Bgra[ti+3], maxA));
                        }
                        break;
                    }
                }
            }
        }
        return 0;
    }
}
