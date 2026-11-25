using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLpk {
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

        foreach (var tn in new[] { "ModelData+LPKData", "ModelData+CostumeData", "MainLveEntity+Costume", "LPKUIController", "WorkshopUIController" }) {
            var t = types.FirstOrDefault(x => x.FullName == tn || x.Name == tn);
            if (t == null) continue;
            Console.WriteLine("=== " + t.FullName + " ===");
            foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly).Take(25))
                Console.WriteLine("  F: " + f.FieldType.Name + " " + f.Name);
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly).Take(15))
                Console.WriteLine("  M: " + m.ReturnType.Name + " " + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name)) + ")");
        }
    }
}
