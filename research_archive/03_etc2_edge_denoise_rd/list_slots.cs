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
        var idle = data.FindAnimation("idle");
        if (idle != null) idle.Apply(skel, 0, 0, true, null, 1f, MixBlend.Setup, MixDirection.In);
        skel.UpdateWorldTransform();

        // Also dump UV triangle mask per slot on the 2048x2048 atlas to check neighbor bleeding into UV triangles!
        // First list slots in head/arm view and check boundary pixels of their UV triangles
        float[] verts = new float[16384];
        int[] quadTris = new int[] { 0, 1, 2, 2, 3, 0 };

        int minX = 0, maxX = 800, minY = 480, maxY = 1280;
        // Let's also check specifically which slot has a straight edge crossing (x in [180..450], y in [750..900]) in render coords (worldX = px, worldY = 1280 - py)
        // In head_and_viol_50.jpg, the sharp diagonal green line goes roughly from render (px=200, py=520) -> world (200, 760) to (px=450, py=680) -> world (450, 600)
        // Wait: in render_head.png (800x800), let's check all slots that draw non-zero low-alpha pixels along the arm (worldX ~ 180..300, worldY ~ 700..1050)
        foreach (var slot in skel.DrawOrder) {
            if (slot.Attachment == null || slot.A <= 0.001f || !slot.Bone.Active) continue;
            var ra = slot.Attachment as RegionAttachment;
            var ma = slot.Attachment as MeshAttachment;
            LoadedTex tex = null; int[] tris = null; float[] uvs = null; string regName = "";
            AtlasRegion reg = null;
            if (ra != null) {
                reg = ra.RendererObject as AtlasRegion; if (reg == null) continue;
                regName = reg.name; tex = reg.page.rendererObject as LoadedTex;
                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2); uvs = ra.UVs; tris = quadTris;
            } else if (ma != null) {
                reg = ma.RendererObject as AtlasRegion; if (reg == null) continue;
                regName = reg.name; tex = reg.page.rendererObject as LoadedTex;
                int vlen = ma.WorldVerticesLength; if (verts.Length < vlen) verts = new float[vlen];
                ma.ComputeWorldVertices(slot, 0, vlen, verts, 0, 2); uvs = ma.UVs; tris = ma.Triangles;
            } else continue;

            float xMin = 1e9f, xMax = -1e9f, yMin = 1e9f, yMax = -1e9f;
            int nVerts = (ra != null) ? 4 : (ma.WorldVerticesLength / 2);
            for (int i = 0; i < nVerts; i++) {
                float x = verts[i*2], y = verts[i*2+1];
                if (x < xMin) xMin = x; if (x > xMax) xMax = x;
                if (y < yMin) yMin = y; if (y > yMax) yMax = y;
            }
            if (xMax < 80 || xMin > 750 || yMax < 500 || yMin > 1250) continue;

            // Check UV bounds vs atlas region bounds
            float uMin = 1e9f, uMax = -1e9f, vMin = 1e9f, vMax = -1e9f;
            for (int i = 0; i < nVerts; i++) {
                float u = uvs[i*2] * tex.W, v = uvs[i*2+1] * tex.H;
                if (u < uMin) uMin = u; if (u > uMax) uMax = u;
                if (v < vMin) vMin = v; if (v > vMax) vMax = v;
            }
            // Check how many boundary edge pixels of the UV polygon have alpha > 0!
            int edgeNonZero = 0;
            for (int t = 0; t < tris.Length; t += 3) {
                for (int e = 0; e < 3; e++) {
                    int ia = tris[t + e] * 2;
                    int ib = tris[t + (e + 1) % 3] * 2;
                    float ua = uvs[ia] * tex.W, va = uvs[ia+1] * tex.H;
                    float ub = uvs[ib] * tex.W, vb = uvs[ib+1] * tex.H;
                    float dist = (float)Math.Sqrt((ub-ua)*(ub-ua)+(vb-va)*(vb-va));
                    int steps = Math.Max(1, (int)dist);
                    for (int s = 0; s <= steps; s++) {
                        float f = s / (float)steps;
                        int tx = Math.Max(0, Math.Min(tex.W-1, (int)(ua + (ub-ua)*f)));
                        int ty = Math.Max(0, Math.Min(tex.H-1, (int)(va + (vb-va)*f)));
                        int ti = (ty * tex.W + tx) * 4;
                        byte a = tex.Bgra[ti+3];
                        byte r = tex.Bgra[ti+2], g = tex.Bgra[ti+1], b = tex.Bgra[ti+0];
                        if ((a > 0 && a < 30) || (a == 0 && (r > 0 || g > 0 || b > 0))) edgeNonZero++;
                    }
                }
            }
            Console.WriteLine(string.Format("Slot {0,-10} reg={1,-8} {2} regXY=({3,4},{4,4}) sz=({5,3},{6,3}) rot={7} world=({8:F0},{9:F0})-({10:F0},{11:F0}) lowA_on_edge={12}",
                slot.Data.Name, regName, ma != null ? "M" : "R", reg.x, reg.y, reg.width, reg.height, reg.rotate ? "T" : "F",
                xMin, yMin, xMax, yMax, edgeNonZero));
        }
        return 0;
    }
}
