using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectEBEK {
    static void Main() {
        string exM = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(exM, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(exM, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        var t = asm.GetTypes().First(x => x.Name == "EBEKBDCAOFB");
        Console.WriteLine("=== EBEKBDCAOFB ===");
        foreach (var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)) {
            if (m.Name == "DBEEBKDAKKC" || m.Name == "JAHPAOMMKNB" || m.Name.Contains("Encrypt") || m.GetParameters().Length >= 2) {
                Console.WriteLine("M: " + m.ReturnType.Name + " " + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name)) + ")");
                var body = m.GetMethodBody(); if (body == null) continue;
                var il = body.GetILAsByteArray(); int i = 0;
                var items = new System.Collections.Generic.List<string>();
                while (i < il.Length) {
                    byte op = il[i++];
                    if (op == 0x72 && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try { string s = mod.ResolveString(tok); if (s.Length > 0 && s.Length < 35) items.Add("S:" + s); } catch {}
                    } else if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try {
                            var mb = mod.ResolveMethod(tok);
                            string mn = (mb.DeclaringType != null ? mb.DeclaringType.Name + "." : "") + mb.Name;
                            if (mn.Contains("MD5") || mn.Contains("Zip") || mn.Contains("File.") || mn.Contains("Directory.") || mn.Contains("Path.") || mn.Contains("Contains") || mn.Contains("Hash") || mn.Contains("EBEK") || mn.Contains("JHOF") || mn.Contains("ABNJ"))
                                items.Add("C:" + mn);
                        } catch {}
                    }
                }
                if (items.Count > 0) Console.WriteLine("  " + string.Join(", ", items.Distinct().Take(25)));
            }
        }
    }
}
