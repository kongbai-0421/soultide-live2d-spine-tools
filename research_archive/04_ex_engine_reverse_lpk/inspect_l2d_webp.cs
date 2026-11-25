using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectL2DWebP {
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

        Console.WriteLine("=== Live2D ModelConfigData & Model3ConfigData texture loading ===");
        foreach (var name in new[] { "ModelConfigData", "Model3ConfigData" }) {
            var t = types.FirstOrDefault(x => x.Name == name);
            if (t == null) continue;
            Console.WriteLine("TYPE " + t.FullName);
            foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
                Console.WriteLine("  F: " + f.FieldType.Name + " " + f.Name);
        }

        // Check how Live2D (Cubism 3/4/5) loads textures: search for calls to BHNCAHBOMMP.FKJLDFKKNFF or NMCLGFDFFLL
        Console.WriteLine("\n=== Callers of BHNCAHBOMMP.FKJLDFKKNFF (texture loader) ===");
        var bh = types.First(t => t.Name == "BHNCAHBOMMP");
        var loaderToks = bh.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static)
                           .Where(m => m.Name == "FKJLDFKKNFF").Select(m => m.MetadataToken).ToHashSet();
        foreach (var t in types) {
            if ((t.FullName ?? "").StartsWith("Spine") || (t.FullName ?? "").StartsWith("DragonBones")) continue;
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                MethodBody body = null;
                try { body = m.GetMethodBody(); } catch { continue; }
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                for (int i = 0; i + 5 <= il.Length; i++) {
                    byte op = il[i];
                    if (op == 0x28 || op == 0x6F) {
                        int tok = BitConverter.ToInt32(il, i + 1);
                        if (loaderToks.Contains(tok)) {
                            Console.WriteLine("  CALLER: " + t.FullName + "::" + m.Name);
                            break;
                        }
                    }
                }
            }
        }
    }
}
