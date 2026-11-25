using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using Spine3_8;

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

    class DummyLoader : TextureLoader {
        public void Load(AtlasPage page, string path) { page.width = 2048; page.height = 2048; }
        public void Unload(object texture) {}
    }

    static int Run() {
        string dir = @"E:\A灵魂潮汐\Live2D与Spine模型\spine\莉莉艾洛\花与剑的交织";
        string atlasPath = Path.Combine(dir, "SoulDress_Lilyiro_05.atlas.txt");
        string skelPath = Path.Combine(dir, "SoulDress_Lilyiro_05.skel.json");
        string outCsv = @".\_scratch\edge_noise_study\all_uv_tris.csv";

        Atlas atlas;
        using (var sr = new StreamReader(atlasPath, System.Text.Encoding.UTF8))
            atlas = new Atlas(sr, dir, new DummyLoader());
        var data = new SkeletonBinary(new AtlasAttachmentLoader(atlas)).ReadSkeletonData(skelPath);
        var skel = new Skeleton(data);
        skel.SetToSetupPose();
        var idle = data.FindAnimation("idle");
        if (idle != null) idle.Apply(skel, 0, 0, true, null, 1f, MixBlend.Setup, MixDirection.In);
        skel.UpdateWorldTransform();

        int[] quadTris = new int[] { 0, 1, 2, 2, 3, 0 };
        using (var sw = new StreamWriter(outCsv, false, System.Text.Encoding.UTF8)) {
            sw.WriteLine("slot_idx,slot_name,reg_name,is_mesh,blend,u0,v0,u1,v1,u2,v2");
            int sidx = 0;
            foreach (var slot in skel.DrawOrder) {
                sidx++;
                if (slot.Attachment == null) continue;
                var ra = slot.Attachment as RegionAttachment;
                var ma = slot.Attachment as MeshAttachment;
                float[] uvs = null; int[] tris = null; AtlasRegion reg = null; bool isMesh = false;
                if (ra != null) { reg = ra.RendererObject as AtlasRegion; uvs = ra.UVs; tris = quadTris; }
                else if (ma != null) { reg = ma.RendererObject as AtlasRegion; uvs = ma.UVs; tris = ma.Triangles; isMesh = true; }
                else continue;
                if (reg == null) continue;
                for (int t = 0; t < tris.Length; t += 3) {
                    int i0 = tris[t]*2, i1 = tris[t+1]*2, i2 = tris[t+2]*2;
                    sw.WriteLine(string.Format(System.Globalization.CultureInfo.InvariantCulture,
                        "{0},{1},{2},{3},{4},{5:F4},{6:F4},{7:F4},{8:F4},{9:F4},{10:F4}",
                        sidx, slot.Data.Name, reg.name, isMesh ? 1 : 0, slot.Data.BlendMode,
                        uvs[i0]*2048f, uvs[i0+1]*2048f, uvs[i1]*2048f, uvs[i1+1]*2048f, uvs[i2]*2048f, uvs[i2+1]*2048f));
                }
            }
        }
        Console.WriteLine("Exported " + outCsv);
        return 0;
    }
}
