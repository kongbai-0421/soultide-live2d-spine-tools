using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectWebP {
    static void Main() {
        string managed = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";
        string plugins = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Plugins";
        Console.WriteLine("=== Plugins in lw ===");
        if (Directory.Exists(plugins)) {
            foreach (var f in Directory.GetFiles(plugins, "*", SearchOption.AllDirectories))
                Console.WriteLine("  " + f);
        }
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            string name = new AssemblyName(e.Name).Name + ".dll";
            string p = Path.Combine(managed, name);
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(managed, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        Type[] types;
        try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }

        var wp = types.First(t => t.Name == "CNPFPOADJLP");
        Console.WriteLine("\n=== CNPFPOADJLP (WebP wrapper) ===");
        foreach (var f in wp.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance))
            Console.WriteLine("  F: " + f.FieldType.Name + " " + f.Name + (f.IsLiteral ? " = " + f.GetRawConstantValue() : ""));
        foreach (var m in wp.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly)) {
            var pi = m.Attributes.HasFlag(MethodAttributes.PinvokeImpl);
            if (pi) {
                var attr = m.GetCustomAttributes(false).FirstOrDefault(a => a.GetType().Name.Contains("DllImport"));
                Console.WriteLine("  PINVOKE: " + m.ReturnType.Name + " " + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name)) + ")");
            }
        }
        // Dump PENKKMCMMFH (called by NMCLGFDFFLL::PHHJAFLKKBN)
        var m2 = wp.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static).FirstOrDefault(x => x.Name == "PENKKMCMMFH");
        if (m2 != null) {
            Console.WriteLine("\n=== CNPFPOADJLP::PENKKMCMMFH ===");
            DumpIL(mod, m2);
        }
        // Dump ModelConfigData::PostUpdate raw ops around .webp & tex_type
        var mcd = types.First(t => t.Name == "ModelConfigData");
        var pu = mcd.GetMethod("PostUpdate", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
        Console.WriteLine("\n=== ModelConfigData::PostUpdate ===");
        DumpIL(mod, pu);

        // Check exstudio too!
        string exManaged = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        string exPlugins = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Plugins";
        Console.WriteLine("\n=== Plugins in exstudio ===");
        if (Directory.Exists(exPlugins)) {
            foreach (var f in Directory.GetFiles(exPlugins, "*", SearchOption.AllDirectories))
                Console.WriteLine("  " + f);
        }
    }

    static void DumpIL(Module mod, MethodInfo m) {
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
                    Console.WriteLine("  CALL: " + (mb.DeclaringType != null ? mb.DeclaringType.Name + "." : "") + mb.Name);
                } catch {}
            } else if ((op == 0x7B || op == 0x7D || op == 0x7E || op == 0x80) && i + 4 <= il.Length) {
                int tok = BitConverter.ToInt32(il, i); i += 4;
                try {
                    var fi = mod.ResolveField(tok);
                    Console.WriteLine("  FLD: " + (fi.DeclaringType != null ? fi.DeclaringType.Name + "." : "") + fi.Name);
                } catch {}
            } else if (op >= 0x16 && op <= 0x1E) {
                Console.WriteLine("  LDC.I4." + (op - 0x16));
            }
        }
    }
}
