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
        string pngPath = @"E:\A灵魂潮汐\人偶spine\Texture2D\SoulDress_Lilyiro_05.png";
        Atlas atlas;
        using (var sr = new StreamReader(atlasPath, System.Text.Encoding.UTF8))
            atlas = new Atlas(sr, dir, new PngTexLoader { OverridePng = pngPath });
        var data = new SkeletonBinary(new AtlasAttachmentLoader(atlas)).ReadSkeletonData(skelPath);
        var skel = new Skeleton(data);
        skel.SetToSetupPose();
        var idle = data.FindAnimation("idle");
        if (idle != null) idle.Apply(skel, 0, 0, true, null, 1f, MixBlend.Setup, MixDirection.In);
        skel.UpdateWorldTransform();

        // Check every slot's outer UV boundary edges: count how many pixels ALONG THE OUTER BOUNDARY of the UV mesh/rect
        // have alpha > 0 or RGB > 0 (either directly on the edge or within 1px outside it = bilinear bleed!)
        // Even better: also check if ANY non-zero texel lies along a straight edge of a RegionAttachment or Mesh boundary!
        float[] verts = new float[16384];
        int[] quadTris = new int[] { 0, 1, 2, 2, 3, 0 };

        // Let's also export a map of ALL slot UV outlines drawn on the 2048x2048 atlas,
        // AND specifically inspect pixels on the diagonal line over the arm & face in render_head.png!
        // In render_head.png (minX=0, maxX=800, minY=480, maxY=1280):
        // Let's trace every slot that touches render pixel (px, py) along the diagonal green line in viol_head.png!
        // First find which slots contributed to viol_head.png red/green pixels in two boxes:
        // Box A (arm cross): px in [160..320], py in [450..620]  -> world x in [160..320], y in [660..830]
        // Box B (face/cheek): px in [320..520], py in [500..700] -> world x in [320..520], y in [580..780]
        int minX = 0, maxX = 800, minY = 480, maxY = 1280;
        int W = 800, H = 800;

        foreach (var slot in skel.DrawOrder) {
            if (slot.Attachment == null || slot.A <= 0.001f || !slot.Bone.Active) continue;
            var ra = slot.Attachment as RegionAttachment;
            var ma = slot.Attachment as MeshAttachment;
            LoadedTex tex = null; int[] tris = null; float[] uvs = null; AtlasRegion reg = null;
            if (ra != null) {
                reg = ra.RendererObject as AtlasRegion; if (reg == null) continue;
                tex = reg.page.rendererObject as LoadedTex;
                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2); uvs = ra.UVs; tris = quadTris;
            } else if (ma != null) {
                reg = ma.RendererObject as AtlasRegion; if (reg == null) continue;
                tex = reg.page.rendererObject as LoadedTex;
                int vlen = ma.WorldVerticesLength; if (verts.Length < vlen) verts = new float[vlen];
                ma.ComputeWorldVertices(slot, 0, vlen, verts, 0, 2); uvs = ma.UVs; tris = ma.Triangles;
            } else continue;

            // Find boundary edges (edges belonging to only 1 triangle)
            var edgeCount = new Dictionary<long, int>();
            for (int t = 0; t < tris.Length; t += 3) {
                for (int e = 0; e < 3; e++) {
                    int a = tris[t + e], b = tris[t + (e + 1) % 3];
                    long key = a < b ? (((long)a << 32) | (uint)b) : (((long)b << 32) | (uint)a);
                    int c; edgeCount.TryGetValue(key, out c); edgeCount[key] = c + 1;
                }
            }

            // Sample along boundary edges ONLY: check if boundary edge passes through arm/face area AND has non-zero alpha/RGB in atlas!
            int bndDirty = 0;
            int bndBilinDirty = 0;
            string sampleInfo = "";
            foreach (var kv in edgeCount) {
                if (kv.Value != 1) continue;
                int ia = (int)(kv.Key >> 32), ib = (int)(kv.Key & 0xFFFFFFFF);
                float wx0 = verts[ia*2], wy0 = verts[ia*2+1];
                float wx1 = verts[ib*2], wy1 = verts[ib*2+1];
                if (Math.Max(wx0, wx1) < 100 || Math.Min(wx0, wx1) > 750 || Math.Max(wy0, wy1) < 520 || Math.Min(wy0, wy1) > 1100) continue;
                float ua = uvs[ia*2] * tex.W, va = uvs[ia*2+1] * tex.H;
                float ub = uvs[ib*2] * tex.W, vb = uvs[ib*2+1] * tex.H;
                float len = (float)Math.Sqrt((ub-ua)*(ub-ua)+(vb-va)*(vb-va));
                int steps = Math.Max(1, (int)len);
                for (int s = 0; s <= steps; s++) {
                    float f = s / (float)steps;
                    float u = ua + (ub - ua) * f;
                    float v = va + (vb - va) * f;
                    int tx = Math.Max(0, Math.Min(tex.W - 1, (int)Math.Floor(u)));
                    int ty = Math.Max(0, Math.Min(tex.H - 1, (int)Math.Floor(v)));
                    int ti = (ty * tex.W + tx) * 4;
                    byte a = tex.Bgra[ti+3], r = tex.Bgra[ti+2], g = tex.Bgra[ti+1], b = tex.Bgra[ti+0];
                    if (a > 0 || r > 0 || g > 0 || b > 0) {
                        bndDirty++;
                        if (sampleInfo == "" && (a > 0 && a < 200 || (a == 0 && (r+g+b)>0))) {
                            float wx = wx0 + (wx1 - wx0) * f, wy = wy0 + (wy1 - wy0) * f;
                            sampleInfo = string.Format("world({0:F0},{1:F0}) uv({2:F1},{3:F1}) RGBA=({4},{5},{6},{7})", wx, wy, u, v, r, g, b, a);
                        }
                    }
                    // Also check 3x3 neighborhood for bilinear bleed from adjacent packed regions!
                    bool neigh = false;
                    for (int dy = -1; dy <= 1 && !neigh; dy++)
                    for (int dx = -1; dx <= 1 && !neigh; dx++) {
                        int nx = Math.Max(0, Math.Min(tex.W-1, tx+dx));
                        int ny = Math.Max(0, Math.Min(tex.H-1, ty+dy));
                        int ni = (ny * tex.W + nx) * 4;
                        if (tex.Bgra[ni+3] > 20 || tex.Bgra[ni+2] > 20 || tex.Bgra[ni+1] > 20 || tex.Bgra[ni+0] > 20) neigh = true;
                    }
                    if (neigh) bndBilinDirty++;
                }
            }
            if (bndDirty > 15 || bndBilinDirty > 40) {
                Console.WriteLine(string.Format("Slot {0,-10} reg={1,-8} {2} bndDirty={3,4} bilinDirty={4,4} | {5}",
                    slot.Data.Name, reg.name, ma != null ? "M" : "R", bndDirty, bndBilinDirty, sampleInfo));
            }
        }
        return 0;
    }
}
