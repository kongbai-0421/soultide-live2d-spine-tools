using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLpkPack {
    static void Main() {
        string exM = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(exM, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(exM, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        Type[] types;
        try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }

        // Check how LPKUIController / LPK packer handles paths, costumes, zip entries, and MD5/dedup!
        foreach (var t in types) {
            if ((t.Name ?? "").Contains("LPK") || (t.Name ?? "").Contains("Lpk")) {
                Console.WriteLine("=== " + t.FullName + " ===");
                foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                    var body = m.GetMethodBody();
                    if (body == null) continue;
                    var il = body.GetILAsByteArray();
                    var hits = new System.Collections.Generic.List<string>();
                    int i = 0;
                    while (i < il.Length) {
                        byte op = il[i++];
                        if (op == 0x72 && i + 4 <= il.Length) {
                            int tok = BitConverter.ToInt32(il, i); i += 4;
                            try { string s = mod.ResolveString(tok); if (s.Length > 0 && s.Length < 40) hits.Add("S:" + s); } catch {}
                        } else if ((op == 0x28 || op == 0x6F) && i + 4 <= il.Length) {
                            int tok = BitConverter.ToInt32(il, i); i += 4;
                            try {
                                var mb = mod.ResolveMethod(tok);
                                string mn = (mb.DeclaringType!=null?mb.DeclaringType.Name+".":"") + mb.Name;
                                if (mn.Contains("MD5") || mn.Contains("Hash") || mn.Contains("Zip") || mn.Contains("Combine") || mn.Contains("GetFullPath") || mn.Contains("Encrypt"))
                                    hits.Add("C:" + mn);
                            } catch {}
                        }
                    }
                    if (hits.Count > 0) Console.WriteLine("  " + m.Name + " -> " + string.Join(", ", hits.Distinct().Take(12)));
                }
            }
        }
    }
}
