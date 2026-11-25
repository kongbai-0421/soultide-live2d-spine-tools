using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLW2 {
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

        Console.WriteLine("=== Non-Spine, Non-DragonBones interesting types ===");
        foreach (var t in types) {
            string n = t.FullName ?? "";
            if (n.StartsWith("Spine") || n.StartsWith("DragonBones") || n.Contains("<") || n.StartsWith("Live2D.")) continue;
            if (n.IndexOf("Spine", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Texture", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Image", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Effect", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Particle", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Video", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Movie", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("WebP", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Shader", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("ModelConfig", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("SubModel", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Async", StringComparison.OrdinalIgnoreCase) >= 0 ||
                n.IndexOf("Load", StringComparison.OrdinalIgnoreCase) >= 0) {
                Console.WriteLine("  " + n);
            }
        }
    }
}
