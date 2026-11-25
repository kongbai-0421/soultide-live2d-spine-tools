using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

class InspectLWTexture {
    static void Main() {
        string managed = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            string name = new AssemblyName(e.Name).Name + ".dll";
            string p = Path.Combine(managed, name);
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(managed, "Assembly-CSharp.dll"));
        Type[] types;
        try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }

        // Find methods in SpineModel3_8 that create SpineAtlasAsset[] (taking List<ModelConfigData.SpineAtlas> or similar)
        var sm = types.First(t => t.FullName == "SpineModel3_8");
        Console.WriteLine("=== SpineModel3_8 fields ===");
        foreach (var f in sm.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
            Console.WriteLine("  " + f.FieldType.Name + " " + f.Name);

        Console.WriteLine("\n=== ModelConfigData+Option fields ===");
        var opt = types.First(t => t.FullName == "ModelConfigData+Option");
        foreach (var f in opt.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            Console.WriteLine("  " + f.FieldType.Name + " " + f.Name);

        Console.WriteLine("\n=== ModelConfigData+SpineAtlas fields ===");
        var sa = types.First(t => t.FullName == "ModelConfigData+SpineAtlas");
        foreach (var f in sa.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            Console.WriteLine("  " + f.FieldType.Name + " " + f.Name);

        Console.WriteLine("\n=== SpineModel3_8 CreateAtlas method calls & strings ===");
        // Dump all method calls + string literals inside SpineModel3_8 methods taking List`1
        var mod = asm.ManifestModule;
        foreach (var m in sm.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
            var ps = m.GetParameters();
            if (ps.Length == 1 && ps[0].ParameterType.Name.StartsWith("List")) {
                var body = m.GetMethodBody();
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                Console.WriteLine("METHOD " + m.Name + " (IL=" + il.Length + " bytes):");
                DumpILCallsAndStrings(mod, il);
                break; // just one of the obfuscated copies
            }
        }

        Console.WriteLine("\n=== Live2DModelProxyBase AddSubModel ===");
        var proxy = types.First(t => t.Name == "Live2DModelProxyBase");
        foreach (var m in proxy.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
            if (m.Name.Contains("SubModel") || m.Name.Contains("Submodel") || m.Name.Contains("Command")) {
                Console.WriteLine("  " + m.ReturnType.Name + " " + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name)) + ")");
            }
        }

        Console.WriteLine("\n=== EffectData & BaseEffect ===");
        foreach (var name in new[] { "EffectData", "BaseEffect", "FloatingParticleSetting" }) {
            var t = types.FirstOrDefault(x => x.Name == name);
            if (t == null) continue;
            Console.WriteLine("CLASS " + t.FullName);
            foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
                Console.WriteLine("  " + f.FieldType.Name + " " + f.Name);
        }
    }

    static void DumpILCallsAndStrings(Module mod, byte[] il) {
        int i = 0;
        while (i < il.Length) {
            byte op = il[i++];
            if (op == 0x72 && i + 4 <= il.Length) { // ldstr
                int tok = BitConverter.ToInt32(il, i); i += 4;
                try { Console.WriteLine("    STR: " + mod.ResolveString(tok)); } catch {}
            } else if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) { // call, callvirt, newobj
                int tok = BitConverter.ToInt32(il, i); i += 4;
                try {
                    var mb = mod.ResolveMethod(tok);
                    Console.WriteLine("    CALL: " + (mb.DeclaringType != null ? mb.DeclaringType.Name + "." : "") + mb.Name);
                } catch {}
            }
        }
    }
}
