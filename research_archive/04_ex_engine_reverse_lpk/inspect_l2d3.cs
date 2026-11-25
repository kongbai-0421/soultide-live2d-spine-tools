using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectL2D3 {
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

        var m3 = types.First(t => t.Name == "Model3ConfigData");
        Console.WriteLine("=== Model3ConfigData+COption ===");
        var copt = types.First(t => t.FullName == "Model3ConfigData+COption");
        foreach (var f in copt.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            Console.WriteLine("  " + f.FieldType.Name + " " + f.Name);

        var t3 = types.First(t => t.Name == "IPIMLPLPGOJ");
        Console.WriteLine("\n=== IPIMLPLPGOJ::OELMECJMNJK calls/strings ===");
        var m = t3.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                  .First(x => x.Name == "OELMECJMNJK");
        var il = m.GetMethodBody().GetILAsByteArray();
        int i = 0;
        while (i < il.Length) {
            byte op = il[i++];
            if (op == 0x72 && i + 4 <= il.Length) {
                int tok = BitConverter.ToInt32(il, i); i += 4;
                try { Console.WriteLine("  STR: " + mod.ResolveString(tok)); } catch {}
            } else if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) {
                int tok = BitConverter.ToInt32(il, i); i += 4;
                try { var mb = mod.ResolveMethod(tok); Console.WriteLine("  CALL: " + (mb.DeclaringType!=null?mb.DeclaringType.Name+".":"") + mb.Name); } catch {}
            }
        }
    }
}
