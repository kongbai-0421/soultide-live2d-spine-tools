using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectMlve {
    static void Main() {
        string exM = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(exM, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(exM, "Assembly-CSharp.dll"));
        Type[] types;
        try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }

        foreach (var t in types) {
            string n = t.FullName ?? "";
            if (n.Contains("MainLveEntity") || n.Contains("LPKData") || n.Contains("CostumeData") || n.Contains("CharacterData") || n.Contains("MLENKLMOFNN")) {
                if (n.Contains("<")) continue;
                Console.WriteLine("=== " + n + " ===");
                foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
                    Console.WriteLine("  F: " + f.FieldType.Name + " " + f.Name);
            }
        }
    }
}
