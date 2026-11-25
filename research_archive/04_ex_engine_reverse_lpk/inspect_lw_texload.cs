using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLWTexLoad {
    static void Main() {
        string managed = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            string name = new AssemblyName(e.Name).Name + ".dll";
            string p = Path.Combine(managed, name);
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(managed, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        Type[] types;
        try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }

        // Find all methods that call LoadImage or Texture2D.Compress or reference "tex_type" or ".webp" or ".dds" or ".ktx" or "LoadTexture"
        Console.WriteLine("=== Scanning IL for Texture loading / Compression / WebP / SubModel async ===");
        foreach (var t in types) {
            if ((t.FullName ?? "").StartsWith("Spine") || (t.FullName ?? "").StartsWith("DragonBones") || (t.FullName ?? "").StartsWith("CameraFilterPack")) continue;
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                MethodBody body = null;
                try { body = m.GetMethodBody(); } catch { continue; }
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                bool interesting = false;
                var hits = new System.Collections.Generic.List<string>();
                int i = 0;
                while (i < il.Length) {
                    byte op = il[i++];
                    if (op == 0x72 && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try {
                            string s = mod.ResolveString(tok);
                            string sl = s.ToLowerInvariant();
                            if (sl.Contains(".webp") || sl.Contains(".dds") || sl.Contains(".ktx") || sl.Contains(".jpg") || sl.Contains("add_submodel") || sl.Contains("tex_type") || sl.Contains("shader_type")) {
                                interesting = true;
                                hits.Add("STR:" + s);
                            }
                        } catch {}
                    } else if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try {
                            var mb = mod.ResolveMethod(tok);
                            string mn = (mb.DeclaringType != null ? mb.DeclaringType.Name + "." : "") + mb.Name;
                            if (mn.Contains("LoadImage") || mn.Contains("Texture2D.Compress") || mn.Contains("WebP") || mn.Contains("LoadRawTextureData") || mn.Contains("UnityWebRequestTexture")) {
                                interesting = true;
                                hits.Add("CALL:" + mn);
                            }
                        } catch {}
                    }
                }
                if (interesting && hits.Count > 0) {
                    Console.WriteLine(t.FullName + "::" + m.Name + " -> " + string.Join(", ", hits.Distinct().Take(8)));
                }
            }
        }
    }
}
