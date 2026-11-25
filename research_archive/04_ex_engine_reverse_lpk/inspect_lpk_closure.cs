using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectClosure {
    static void Main() {
        string exM = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(exM, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(exM, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        foreach (var t in asm.GetTypes().Where(x => (x.FullName ?? "").Contains("EJJBLIGMFCJ"))) {
            Console.WriteLine("=== " + t.FullName + " ===");
            foreach (var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)) {
                var body = m.GetMethodBody(); if (body == null) continue;
                Console.WriteLine("M: " + m.Name);
                var il = body.GetILAsByteArray(); int i = 0;
                while (i < il.Length) {
                    byte op = il[i++];
                    if (op == 0x72 && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try { Console.WriteLine("  S: " + mod.ResolveString(tok)); } catch {}
                    } else if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try {
                            var mb = mod.ResolveMethod(tok);
                            Console.WriteLine("  C: " + (mb.DeclaringType != null ? mb.DeclaringType.Name + "." : "") + mb.Name);
                        } catch {}
                    }
                }
            }
        }
    }
}
