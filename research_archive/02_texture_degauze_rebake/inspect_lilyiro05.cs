using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using Spine3_8;

class DummyTexLoader : TextureLoader {
    public void Load(AtlasPage page, string path) { page.width = 2048; page.height = 2048; }
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

        Atlas atlas;
        using (var sr = new StreamReader(atlasPath, System.Text.Encoding.UTF8)) {
            atlas = new Atlas(sr, dir, new DummyTexLoader());
        }
        var sb = new SkeletonBinary(new AtlasAttachmentLoader(atlas));
        var data = sb.ReadSkeletonData(skelPath);

        Console.WriteLine("Version: " + data.Version + " Hash: " + data.Hash);
        Console.WriteLine("Bones: " + data.Bones.Count + " Slots: " + data.Slots.Count + " Animations: " + data.Animations.Count);

        var skel = new Skeleton(data);
        skel.SetToSetupPose();
        skel.UpdateWorldTransform();

        Console.WriteLine("\n=== ANIMATIONS ===");
        foreach (var anim in data.Animations) {
            Console.WriteLine("Anim: " + anim.Name + " dur=" + anim.Duration + " timelines=" + anim.Timelines.Count);
        }

        // Apply idle at t=0 if exists
        var idle = data.FindAnimation("idle");
        if (idle != null) {
            idle.Apply(skel, 0, 0, true, null, 1f, MixBlend.Setup, MixDirection.In);
            skel.UpdateWorldTransform();
        }

        Console.WriteLine("\n=== ALL SLOTS (draw order) ===");
        float[] verts = new float[8192];
        for (int i = 0; i < skel.DrawOrder.Count; i++) {
            var slot = skel.DrawOrder.Items[i];
            var att = slot.Attachment;
            string attType = att == null ? "NULL" : att.GetType().Name;
            string attName = att == null ? "-" : att.Name;
            string regName = "-";
            float minX = 1e9f, maxX = -1e9f, minY = 1e9f, maxY = -1e9f;
            bool hasBounds = false;

            var ra = att as RegionAttachment;
            var ma = att as MeshAttachment;
            if (ra != null) {
                regName = ra.Path ?? ra.Name;
                ra.ComputeWorldVertices(slot.Bone, verts, 0, 2);
                for (int k = 0; k < 8; k += 2) {
                    minX = Math.Min(minX, verts[k]); maxX = Math.Max(maxX, verts[k]);
                    minY = Math.Min(minY, verts[k+1]); maxY = Math.Max(maxY, verts[k+1]);
                }
                hasBounds = true;
            } else if (ma != null) {
                regName = ma.Path ?? ma.Name;
                int n = ma.WorldVerticesLength;
                if (verts.Length < n) verts = new float[n];
                ma.ComputeWorldVertices(slot, 0, n, verts, 0, 2);
                for (int k = 0; k < n; k += 2) {
                    minX = Math.Min(minX, verts[k]); maxX = Math.Max(maxX, verts[k]);
                    minY = Math.Min(minY, verts[k+1]); maxY = Math.Max(maxY, verts[k+1]);
                }
                hasBounds = true;
            }

            // Check overlap with chest region x in [-200, 350], y in [150, 700]
            bool inChest = hasBounds && !(maxX < -200 || minX > 350 || maxY < 150 || minY > 700);
            string mark = inChest ? " [CHEST]" : "";
            string bbox = hasBounds ? string.Format("x=[{0:F0},{1:F0}] y=[{2:F0},{3:F0}]", minX, maxX, minY, maxY) : "no-bounds";
            Console.WriteLine(string.Format("{0,3}: slot={1,-16} bone={2,-12} att={3,-12} reg={4,-12} type={5,-16} rgba=({6:F2},{7:F2},{8:F2},{9:F2}) blend={10} {11}{12}",
                i, slot.Data.Name, slot.Bone.Data.Name, attName, regName, attType,
                slot.R, slot.G, slot.B, slot.A, slot.Data.BlendMode, bbox, mark));
        }
        return 0;
    }
}
