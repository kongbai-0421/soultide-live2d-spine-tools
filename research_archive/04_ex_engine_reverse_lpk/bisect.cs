using System;
using System.IO;
using System.Reflection;

class Bisect {
    static void Main() {
        string managed = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(managed, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        Run();
    }
    class DL : Spine3_8.TextureLoader {
        public void Load(Spine3_8.AtlasPage p, string path) { p.rendererObject = path; }
        public void Unload(object t) {}
    }
    static void Run() {
        string d = @"E:\A灵魂潮汐\Live2D与Spine模型\spine\和铃\古锦新韵\submodels\fx_heling_s2_back";
        Spine3_8.Atlas atlas;
        using (var sr = new StreamReader(Path.Combine(d, "fx_heling_s2_back.atlas.txt")))
            atlas = new Spine3_8.Atlas(sr, d, new DL());
        var al = new Spine3_8.AtlasAttachmentLoader(atlas);
        var sj = new Spine3_8.SkeletonJson(al);
        foreach (var n in new[] { "t_only_yun.skel.json", "t_no_clip.skel.json", "t_no_anims.skel.json" }) {
            string p = Path.Combine(@".\_scratch", n);
            try {
                var sd = sj.ReadSkeletonData(p);
                Console.WriteLine(n + ": OK! bones=" + sd.Bones.Count);
            } catch (Exception ex) {
                Console.WriteLine(n + ": FAIL " + ex.GetType().Name + ": " + ex.Message);
            }
        }
    }
}
