using System;
using System.IO;
using System.Linq;
using System.Reflection;

class TestSpineLoad {
    static void Main() {
        string managed = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(managed, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        Run();
    }

    static void Run() {
        string[] dirs = new[] {
            @"E:\A灵魂潮汐\Live2D与Spine模型\spine\和铃\古锦新韵",
            @"E:\A灵魂潮汐\Live2D与Spine模型\spine\和铃\古锦新韵\submodels\bg_static",
            @"E:\A灵魂潮汐\Live2D与Spine模型\spine\和铃\古锦新韵\submodels\bj_01",
            @"E:\A灵魂潮汐\Live2D与Spine模型\spine\和铃\古锦新韵\submodels\fx_heling_s2_back",
            @"E:\A灵魂潮汐\Live2D与Spine模型\spine\和铃\古锦新韵\submodels\fx_heling_s2_front",
        };
        foreach (var d in dirs) {
            Console.WriteLine("=== Testing " + d + " ===");
            try {
                TestDir(d);
                Console.WriteLine("  OK!");
            } catch (Exception ex) {
                Console.WriteLine("  FAIL: " + ex.GetType().FullName + ": " + ex.Message);
                if (ex.InnerException != null) Console.WriteLine("  INNER: " + ex.InnerException.GetType().FullName + ": " + ex.InnerException.Message);
                Console.WriteLine("  STACK:\n" + ex.StackTrace);
            }
        }
    }

    class DummyLoader : Spine3_8.TextureLoader {
        public void Load(Spine3_8.AtlasPage page, string path) { page.rendererObject = path; }
        public void Unload(object texture) {}
    }

    static void TestDir(string d) {
        var atlasFile = Directory.GetFiles(d, "*.atlas.txt").First();
        var skelFile = Directory.GetFiles(d, "*.skel.json").First();
        Spine3_8.Atlas atlas;
        using (var sr = new StreamReader(atlasFile)) atlas = new Spine3_8.Atlas(sr, d, new DummyLoader());
        var attLoader = new Spine3_8.AtlasAttachmentLoader(atlas);
        var raw = File.ReadAllBytes(skelFile);
        Spine3_8.SkeletonData sd;
        if (raw.Length > 0 && raw[0] == (byte)'{') {
            var sj = new Spine3_8.SkeletonJson(attLoader);
            sd = sj.ReadSkeletonData(skelFile);
        } else {
            var sb = new Spine3_8.SkeletonBinary(attLoader);
            sd = sb.ReadSkeletonData(skelFile);
        }
        var sk = new Spine3_8.Skeleton(sd);
        var anim = sd.FindAnimation("idle");
        if (anim != null) {
            for (float t = 0f; t <= 10f; t += 2.5f) {
                anim.Apply(sk, 0, t, true, null, 1f, Spine3_8.MixBlend.Setup, Spine3_8.MixDirection.In);
                sk.UpdateWorldTransform();
            }
        }
        // Test SkeletonClipping too!
        var clipper = new Spine3_8.SkeletonClipping();
        float[] verts = new float[8192];
        int[] quadIdx = new int[] { 0, 1, 2, 0, 2, 3 };
        foreach (var slot in sk.DrawOrder) {
            var att = slot.Attachment;
            if (att is Spine3_8.ClippingAttachment) {
                clipper.ClipStart(slot, (Spine3_8.ClippingAttachment)att);
                Console.WriteLine("  ClipStart slot=" + slot.Data.Name + " isClipping=" + clipper.IsClipping);
                continue;
            }
            if (att is Spine3_8.RegionAttachment && clipper.IsClipping) {
                var ra = (Spine3_8.RegionAttachment)att;
                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2);
                clipper.ClipTriangles(verts, 8, quadIdx, 6, ra.UVs);
                Console.WriteLine("    clipped " + slot.Data.Name + " v=" + clipper.ClippedVertices.Count + " t=" + clipper.ClippedTriangles.Count + " uv=" + clipper.ClippedUVs.Count);
            }
            clipper.ClipEnd(slot);
        }
        clipper.ClipEnd();
        Console.WriteLine("  bones=" + sd.Bones.Count + " slots=" + sd.Slots.Count + " anims=" + sd.Animations.Count + " idleDur=" + (anim != null ? anim.Duration : -1f));
    }
}
