using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectAudioAndLpk {
    static void Main() {
        string managed = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(managed, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(managed, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        Type[] types;
        try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }

        Console.WriteLine("=== Audio formats & BASS / AudioClip strings in lw.exe ===");
        foreach (var t in types) {
            if ((t.FullName ?? "").StartsWith("Spine") || (t.FullName ?? "").StartsWith("DragonBones")) continue;
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                MethodBody body = null;
                try { body = m.GetMethodBody(); } catch { continue; }
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                var hits = new System.Collections.Generic.List<string>();
                int i = 0;
                while (i < il.Length) {
                    byte op = il[i++];
                    if (op == 0x72 && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try {
                            string s = mod.ResolveString(tok);
                            string sl = s.ToLowerInvariant();
                            if (sl.Contains(".ogg") || sl.Contains(".opus") || sl.Contains(".mp3") || sl.Contains(".m4a") || sl.Contains(".aac") || sl.Contains(".flac") || sl.Contains(".wav") || sl.Contains(".lpk") || sl.Contains("costume")) {
                                if (s.Length < 40) hits.Add(s);
                            }
                        } catch {}
                    }
                }
                if (hits.Count > 0 && (t.Name.IndexOf("Audio", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                       t.Name.IndexOf("Sound", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                       t.Name.IndexOf("Lpk", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                       t.Name.IndexOf("Pack", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                       hits.Any(h => h.Contains(".ogg") || h.Contains(".opus") || h.Contains(".mp3") || h.Contains(".lpk")))) {
                    Console.WriteLine("  " + t.FullName + "::" + m.Name + " -> " + string.Join(", ", hits.Distinct().Take(10)));
                }
            }
        }

        Console.WriteLine("\n=== LPK / Costume / Package types in exstudio.exe ===");
        string exM = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        var exAsm = Assembly.LoadFrom(Path.Combine(exM, "Assembly-CSharp.dll"));
        Type[] exTypes;
        try { exTypes = exAsm.GetTypes(); } catch (ReflectionTypeLoadException ex) { exTypes = ex.Types.Where(t => t != null).ToArray(); }
        foreach (var t in exTypes) {
            string n = t.FullName ?? "";
            if (n.IndexOf("Lpk", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Workshop", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Costume", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Sound", StringComparison.OrdinalIgnoreCase) >= 0) {
                if (n.Contains("<")) continue;
                Console.WriteLine("  EX: " + n);
            }
        }
    }
}
