using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLpkTask {
    static void Main() {
        string exM = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(exM, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(exM, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        var t = asm.GetTypes().First(x => x.Name == "NBPMMGBEHHF");
        Console.WriteLine("=== NBPMMGBEHHF ===");
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
            Console.WriteLine("  F: " + f.FieldType.Name + " " + f.Name);
        foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
            var body = m.GetMethodBody();
            if (body == null) continue;
            var il = body.GetILAsByteArray();
            var hits = new System.Collections.Generic.List<string>();
            int i = 0;
            while (i < il.Length) {
                byte op = il[i++];
                if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) {
                    int tok = BitConverter.ToInt32(il, i); i += 4;
                    try {
                        var mb = mod.ResolveMethod(tok);
                        string mn = (mb.DeclaringType!=null?mb.DeclaringType.Name+".":"") + mb.Name;
                        if (!mn.StartsWith("System.String") && !mn.StartsWith("System.Object"))
                            hits.Add(mn);
                    } catch {}
                }
            }
            if (hits.Count > 0) Console.WriteLine("  M: " + m.Name + " -> " + string.Join(", ", hits.Distinct().Take(15)));
        }
    }
}
