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

        // Probe specific render_setup.png pixel locations where diagonal lines appear:
        // render_setup has minX=0, maxY=1280, so worldX = px, worldY = 1280 - py.
        // In render_setup_50.jpg (400x400 -> 800x800):
        // 1) Hairbang diagonal bright dotted line near right eye: approx 50%-coord (295, 345) -> render (590, 690) -> world (590, 590)
        // 2) Arm diagonal faint line below left hair tip: approx 50%-coord (115, 290) -> render (230, 580) -> world (230, 700)
        // Let's probe a scanline across world (570..630, 580..620) and (200..260, 680..720) for any slot whose UV boundary edge is within 2px!
        float[] verts = new float[16384];
        int[] quadTris = new int[] { 0, 1, 2, 2, 3, 0 };

        Console.WriteLine("Slots with outer boundary edge passing near hairbang (550..650, 540..660) or arm (180..290, 650..760):");
        foreach (var slot in skel.DrawOrder) {
            if (slot.Attachment == null || slot.A <= 0.001f || !slot.Bone.Active) continue;
            var ra = slot.Attachment as RegionAttachment;
            var ma = slot.Attachment as MeshAttachment;
            LoadedTex tex = null; int[] tris = null; float[] uvs = null; AtlasRegion reg = null;
            if (ra != null) { reg = ra.RendererObject as AtlasRegion; tex = reg.page.rendererObject as LoadedTex; ra.ComputeWorldVertices(slot.Bone, verts, 0, 2); uvs = ra.UVs; tris = quadTris; }
            else if (ma != null) { reg = ma.RendererObject as AtlasRegion; tex = reg.page.rendererObject as LoadedTex; int vlen = ma.WorldVerticesLength; if (verts.Length < vlen) verts = new float[vlen]; ma.ComputeWorldVertices(slot, 0, vlen, verts, 0, 2); uvs = ma.UVs; tris = ma.Triangles; }
            else continue;

            var edgeCount = new Dictionary<long, int>();
            for (int t = 0; t < tris.Length; t += 3) {
                for (int e = 0; e < 3; e++) {
                    int a = tris[t + e], b = tris[t + (e + 1) % 3];
                    long key = a < b ? (((long)a << 32) | (uint)b) : (((long)b << 32) | (uint)a);
                    int c; edgeCount.TryGetValue(key, out c); edgeCount[key] = c + 1;
                }
            }
            foreach (var kv in edgeCount) {
                if (kv.Value != 1) continue;
                int ia = (int)(kv.Key >> 32), ib = (int)(kv.Key & 0xFFFFFFFF);
                float wx0 = verts[ia*2], wy0 = verts[ia*2+1], wx1 = verts[ib*2], wy1 = verts[ib*2+1];
                float mx = 0.5f * (wx0 + wx1), my = 0.5f * (wy0 + wy1);
                bool hitHair = (mx >= 530 && mx <= 660 && my >= 520 && my <= 680);
                bool hitArm = (mx >= 170 && mx <= 300 && my >= 640 && my <= 780);
                if (!hitHair && !hitArm) continue;
                // Check if texels within 1px of this UV edge have non-zero RGB or A!
                float ua = uvs[ia*2]*tex.W, va = uvs[ia*2+1]*tex.H, ub = uvs[ib*2]*tex.W, vb = uvs[ib*2+1]*tex.H;
                int dirty = 0, maxA = 0, maxRGB = 0;
                int steps = Math.Max(1, (int)Math.Sqrt((ub-ua)*(ub-ua)+(vb-va)*(vb-va)));
                for (int s = 0; s <= steps; s++) {
                    float f = s / (float)steps;
                    int tx = Math.Max(0, Math.Min(tex.W-1, (int)(ua + (ub-ua)*f)));
                    int ty = Math.Max(0, Math.Min(tex.H-1, (int)(va + (vb-va)*f)));
                    int ti = (ty * tex.W + tx) * 4;
                    int a = tex.Bgra[ti+3], rgb = Math.Max(tex.Bgra[ti], Math.Max(tex.Bgra[ti+1], tex.Bgra[ti+2]));
                    if (a > 0 || rgb > 0) dirty++;
                    if (a > maxA) maxA = a; if (rgb > maxRGB) maxRGB = rgb;
                }
                if (dirty > 5) {
                    Console.WriteLine(string.Format("  [{0}] Slot {1,-8} reg={2,-6} world({3:F0},{4:F0})-({5:F0},{6:F0}) uv({7:F1},{8:F1})-({9:F1},{10:F1}) dirty={11}/{12} maxA={13} maxRGB={14}",
                        hitHair ? "HAIR" : "ARM ", slot.Data.Name, reg.name, wx0, wy0, wx1, wy1, ua, va, ub, vb, dirty, steps+1, maxA, maxRGB));
                }
            }
        }
        return 0;
    }
}
