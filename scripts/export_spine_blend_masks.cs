using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using Spine3_8;

class DummyTexLoader : TextureLoader {
    public void Load(AtlasPage page, string path) {
        // Read actual image dimensions from atlas header or file
        if (page.width <= 0 || page.height <= 0) {
            if (File.Exists(path)) {
                try {
                    using (var img = Image.FromFile(path)) {
                        page.width = img.Width;
                        page.height = img.Height;
                    }
                } catch {
                    page.width = 2048; page.height = 2048;
                }
            } else {
                page.width = 2048; page.height = 2048;
            }
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
        // Usage: export_spine_blend_masks.exe <spineRootDir> <outMaskDir>
        // Scans main Spine models & submodels (excluding fx_*, bg_static, fg_static)
        // Exports 1-bit/8-bit PNG protect masks for any texture page that has Additive or Screen slots!
        if (args.Length < 2) {
            Console.WriteLine("Usage: export_spine_blend_masks.exe <spineRootDir> <outMaskDir>");
            return 1;
        }
        string spineRoot = args[0];
        string outDir = args[1];
        Directory.CreateDirectory(outDir);

        var targets = new List<string>();
        foreach (var dollDir in Directory.GetDirectories(spineRoot)) {
            foreach (var skinDir in Directory.GetDirectories(dollDir)) {
                targets.Add(skinDir);
                string subRoot = Path.Combine(skinDir, "submodels");
                if (Directory.Exists(subRoot)) {
                    foreach (var subDir in Directory.GetDirectories(subRoot)) {
                        string subName = Path.GetFileName(subDir).ToLowerInvariant();
                        if (subName.StartsWith("fx_") || subName.StartsWith("bg_static") || subName.StartsWith("fg_static") || subName.StartsWith("bg_mid"))
                            continue;
                        targets.Add(subDir);
                    }
                }
            }
        }

        int scanned = 0, withSpecial = 0, masksWritten = 0, errors = 0;
        var manifest = new List<string>();

        foreach (var dir in targets) {
            var atlasFiles = Directory.GetFiles(dir, "*.atlas.txt");
            var skelFiles = Directory.GetFiles(dir, "*.skel.json");
            if (atlasFiles.Length == 0 || skelFiles.Length == 0) continue;
            string atlasPath = atlasFiles[0];
            string skelPath = skelFiles[0];
            scanned++;

            try {
                Atlas atlas;
                using (var sr = new StreamReader(atlasPath, System.Text.Encoding.UTF8))
                    atlas = new Atlas(sr, dir, new DummyTexLoader());

                SkeletonData data;
                byte[] head = new byte[16];
                using (var fs = File.OpenRead(skelPath)) fs.Read(head, 0, head.Length);
                bool isJson = false;
                for (int i = 0; i < head.Length; i++) {
                    if (head[i] == '{') { isJson = true; break; }
                    if (head[i] > 32) break;
                }
                if (isJson)
                    data = new SkeletonJson(new AtlasAttachmentLoader(atlas)).ReadSkeletonData(skelPath);
                else
                    data = new SkeletonBinary(new AtlasAttachmentLoader(atlas)).ReadSkeletonData(skelPath);

                // Collect all Additive / Screen attachments across ALL skins (not just default!)
                // Key: page full path -> list of UV polygons (in pixel coords)
                var pagePolys = new Dictionary<string, List<PointF[]>>(StringComparer.OrdinalIgnoreCase);
                var pageSizes = new Dictionary<string, Size>(StringComparer.OrdinalIgnoreCase);

                // Map slot index -> BlendMode
                var specialSlotIndices = new HashSet<int>();
                for (int si = 0; si < data.Slots.Count; si++) {
                    var bm = data.Slots.Items[si].BlendMode;
                    if (bm == BlendMode.Additive || bm == BlendMode.Screen)
                        specialSlotIndices.Add(si);
                }
                if (specialSlotIndices.Count == 0) continue;

                withSpecial++;
                int[] quadTris = new int[] { 0, 1, 2, 2, 3, 0 };

                foreach (var skin in data.Skins) {
                    foreach (var entry in skin.Attachments) {
                        if (!specialSlotIndices.Contains(entry.Key.SlotIndex)) continue;
                        var att = entry.Value;
                        AtlasRegion reg = null;
                        float[] uvs = null;
                        int[] tris = null;
                        var ra = att as RegionAttachment;
                        var ma = att as MeshAttachment;
                        if (ra != null) { reg = ra.RendererObject as AtlasRegion; uvs = ra.UVs; tris = quadTris; }
                        else if (ma != null) { reg = ma.RendererObject as AtlasRegion; uvs = ma.UVs; tris = ma.Triangles; }
                        if (reg == null || uvs == null || tris == null) continue;

                        string texPath = Path.Combine(dir, reg.page.name);
                        int pw = reg.page.width > 0 ? reg.page.width : 2048;
                        int ph = reg.page.height > 0 ? reg.page.height : 2048;
                        if (!pagePolys.ContainsKey(texPath)) {
                            pagePolys[texPath] = new List<PointF[]>();
                            pageSizes[texPath] = new Size(pw, ph);
                        }
                        var list = pagePolys[texPath];
                        for (int t = 0; t < tris.Length; t += 3) {
                            int i0 = tris[t] * 2, i1 = tris[t + 1] * 2, i2 = tris[t + 2] * 2;
                            list.Add(new PointF[] {
                                new PointF(uvs[i0] * pw, uvs[i0 + 1] * ph),
                                new PointF(uvs[i1] * pw, uvs[i1 + 1] * ph),
                                new PointF(uvs[i2] * pw, uvs[i2 + 1] * ph)
                            });
                        }
                    }
                }

                foreach (var kv in pagePolys) {
                    if (kv.Value.Count == 0) continue;
                    string texPath = kv.Key;
                    Size sz = pageSizes[texPath];
                    string rel = texPath.Substring(spineRoot.Length).TrimStart('\\', '/');
                    string safeName = rel.Replace('\\', '_').Replace('/', '_') + ".mask.png";
                    string maskPath = Path.Combine(outDir, safeName);

                    using (var bmp = new Bitmap(sz.Width, sz.Height, PixelFormat.Format24bppRgb)) {
                        using (var g = Graphics.FromImage(bmp)) {
                            g.Clear(Color.Black);
                            g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.None;
                            using (var br = new SolidBrush(Color.White))
                            using (var pen = new Pen(Color.White, 5f)) {
                                foreach (var tri in kv.Value) {
                                    g.FillPolygon(br, tri);
                                    g.DrawPolygon(pen, tri);
                                }
                            }
                        }
                        bmp.Save(maskPath, ImageFormat.Png);
                    }
                    manifest.Add(texPath + "\t" + maskPath + "\t" + kv.Value.Count);
                    masksWritten++;
                }
            } catch (Exception ex) {
                errors++;
                Console.WriteLine("ERR " + dir + ": " + ex.Message);
            }
        }

        File.WriteAllLines(Path.Combine(outDir, "manifest.tsv"), manifest.ToArray(), System.Text.Encoding.UTF8);
        Console.WriteLine(string.Format("Scanned={0}, WithAdditiveOrScreen={1}, MasksWritten={2}, Errors={3}", scanned, withSpecial, masksWritten, errors));
        return 0;
    }
}
