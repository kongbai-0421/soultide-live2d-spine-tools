using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLpkExport {
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

        var lpkT = types.First(x => x.Name == "LPKGenerator");
        var m = lpkT.GetMethod("ExportLpk", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
        Console.WriteLine("=== LPKGenerator::ExportLpk calls ===");
        DumpCalls(mod, m);

        // Also check methods called by ExportLpk (in the same or helper class) that mention "config.json" or "entries" or "Zip"
        foreach (var tp in types) {
            foreach (var mi in tp.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                var body = mi.GetMethodBody();
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                bool hit = false;
                for (int i = 0; i < il.Length; i++) {
                    if (il[i] == 0x72 && i + 5 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i + 1);
                        try {
                            string s = mod.ResolveString(tok);
                            if (s == "STD2_0" || s == "entries.json" || s == "config.mlve") { hit = true; break; }
                        } catch {}
                    }
                }
                if (hit) {
                    Console.WriteLine("\n=== MATCH " + tp.FullName + "::" + mi.Name + " ===");
                    DumpCalls(mod, mi);
                }
            }
        }
    }

    static void DumpCalls(Module mod, MethodInfo m) {
        if (m == null) return;
        var body = m.GetMethodBody();
        if (body == null) return;
        var il = body.GetILAsByteArray();
        int i = 0;
        while (i < il.Length) {
            byte op = il[i++];
            if (op == 0x72 && i + 4 <= il.Length) {
                int tok = BitConverter.ToInt32(il, i); i += 4;
                try { Console.WriteLine("  STR: " + mod.ResolveString(tok)); } catch {}
            } else if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) {
                int tok = BitConverter.ToInt32(il, i); i += 4;
                try {
                    var mb = mod.ResolveMethod(tok);
                    string mn = (mb.DeclaringType!=null?mb.DeclaringType.Name+".":"") + mb.Name;
                    if (!mn.StartsWith("UnityEngine") && !mn.StartsWith("System.String"))
                        Console.WriteLine("  CALL: " + mn);
                } catch {}
            }
        }
    }
}
