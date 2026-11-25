using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLW {
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

        Console.WriteLine("=== Spine & Atlas & Texture Loader Types ===");
        foreach (var t in types) {
            string n = t.FullName ?? "";
            if (n.IndexOf("Spine", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Atlas", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Texture", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("SubModel", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Submodel", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Particle", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Effect", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Video", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Webp", StringComparison.OrdinalIgnoreCase) >= 0) {
                if (n.Contains("<") || n.StartsWith("Spine.")) continue;
                Console.WriteLine("  TYPE: " + n);
            }
        }

        Console.WriteLine("\n=== SpineModel3_8 & TextureLoader methods ===");
        foreach (var t in types.Where(x => (x.FullName ?? "").Contains("SpineModel3_8") || (x.FullName ?? "").Contains("SpineTexture") || (x.FullName ?? "").Contains("AtlasTexture"))) {
            Console.WriteLine("CLASS " + t.FullName);
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                Console.WriteLine("  " + m.ReturnType.Name + " " + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name)) + ")");
            }
        }

        Console.WriteLine("\n=== All Command names / strings in ModelCommand or Live2DModelProxyBase ===");
        foreach (var t in types) {
            if (t.Name.Contains("Command") || t.Name.Contains("ShaderType") || t.Name.Contains("SpineModel") || t.Name.Contains("TextureLoader")) {
                if (t.FullName.StartsWith("Spine.")) continue;
                Console.WriteLine("CLASS " + t.FullName + (t.IsEnum ? " [ENUM]" : ""));
                if (t.IsEnum) {
                    foreach (var v in Enum.GetNames(t)) Console.WriteLine("    " + v + " = " + Convert.ToInt32(Enum.Parse(t, v)));
                } else {
                    foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                        if (f.IsLiteral) Console.WriteLine("    const " + f.Name + " = " + f.GetRawConstantValue());
                    }
                }
            }
        }
    }
}
