using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectHash {
    static void Main() {
        string exM = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(exM, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(exM, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        foreach (var pair in new[] { Tuple.Create("ABNJPMKACGP", "DFCNBBKOABK"), Tuple.Create("EBEKBDCAOFB", "HJFKBCALBLH"), Tuple.Create("EBEKBDCAOFB", "DBEEBKDAKKC") }) {
            var t = asm.GetTypes().First(x => x.Name == pair.Item1);
            foreach (var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly).Where(x => x.Name == pair.Item2)) {
                Console.WriteLine("=== " + pair.Item1 + "::" + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name)) + ") ===");
                var il = m.GetMethodBody().GetILAsByteArray(); int i = 0;
                while (i < il.Length) {
                    byte op = il[i++];
                    if (op == 0x72 && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try { Console.WriteLine("  S: " + mod.ResolveString(tok)); } catch {}
                    } else if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try { var mb = mod.ResolveMethod(tok); Console.WriteLine("  C: " + (mb.DeclaringType!=null?mb.DeclaringType.Name+".":"") + mb.Name); } catch {}
                    }
                }
            }
        }
    }
}
