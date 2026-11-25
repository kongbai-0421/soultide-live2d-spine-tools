using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectZipPack {
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

        // Find every method calling ZipOutputStream / PutNextEntry / CreateEntry / FastZip / EncryptFile / LPK
        foreach (var t in types) {
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                MethodBody body = null;
                try { body = m.GetMethodBody(); } catch { continue; }
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                bool hit = false;
                var calls = new System.Collections.Generic.List<string>();
                int i = 0;
                while (i < il.Length) {
                    byte op = il[i++];
                    if (op == 0x72 && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try {
                            string s = mod.ResolveString(tok);
                            if (s == "config.mlve" || s == "STD2_0" || s == "entries.json" || s.EndsWith(".lpk") || s.Contains("costume")) {
                                calls.Add("S:" + s);
                            }
                        } catch {}
                    } else if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try {
                            var mb = mod.ResolveMethod(tok);
                            string mn = (mb.DeclaringType!=null?mb.DeclaringType.Name+".":"") + mb.Name;
                            if (mn.Contains("Zip") || mn.Contains("Entry") || mn.Contains("MD5") || mn.Contains("Hash")) {
                                hit = true;
                                calls.Add("C:" + mn);
                            }
                        } catch {}
                    }
                }
                if (hit && calls.Any(c => c.Contains("Zip") || c.Contains("Entry"))) {
                    Console.WriteLine(t.FullName + "::" + m.Name + " -> " + string.Join(", ", calls.Distinct().Take(15)));
                }
            }
        }
    }
}
