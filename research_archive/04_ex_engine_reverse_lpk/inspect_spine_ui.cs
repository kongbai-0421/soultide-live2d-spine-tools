using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectSpineUI {
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

        // Check ModelConfigData+Controller, KeyTrigger, Choice, HitArea
        foreach (var tn in new[] { "ModelConfigData+Controller", "ModelConfigData+KeyTriggerController", "ModelConfigData+KeyTrigger", "ModelConfigData+Motion", "ModelConfigData+Choice" }) {
            var t = types.FirstOrDefault(x => x.FullName == tn);
            if (t == null) continue;
            Console.WriteLine("=== " + t.FullName + " ===");
            foreach (var f in t.GetFields(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance))
                Console.WriteLine("  " + f.FieldType.Name + " " + f.Name);
        }

        // Check HLGNFAFIPOA::HJGODPFLFKM around remove_submodel & slot_opacities!
        var disp = types.First(t => t.Name == "HLGNFAFIPOA");
        Console.WriteLine("\n=== HLGNFAFIPOA methods ===");
        foreach (var m in disp.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)) {
            Console.WriteLine("  " + m.ReturnType.Name + " " + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name)) + ")");
        }

        // Check if Spine model class (IEJFLMGGNHD) inherits BHNCAHBOMMP (meaning ALL controllers: key_trigger, choices, hit_areas, commands work identically to Live2D!)
        var spineCtrl = types.First(t => t.Name == "IEJFLMGGNHD");
        Console.WriteLine("\nIEJFLMGGNHD base type: " + (spineCtrl.BaseType != null ? spineCtrl.BaseType.FullName : "none"));
        var l2d3Ctrl = types.First(t => t.Name == "IPIMLPLPGOJ");
        Console.WriteLine("IPIMLPLPGOJ base type: " + (l2d3Ctrl.BaseType != null ? l2d3Ctrl.BaseType.FullName : "none"));

        // Check exact parameter syntax for remove_submodel & add_submodel in HLGNFAFIPOA::HJGODPFLFKM
        var hm = disp.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)
                     .First(x => x.Name == "HJGODPFLFKM");
        var il = hm.GetMethodBody().GetILAsByteArray();
        int i = 0;
        bool printNext = false;
        int countdown = 0;
        Console.WriteLine("\n=== IL around add_submodel / remove_submodel / slot_opacities ===");
        while (i < il.Length) {
            byte op = il[i++];
            if (op == 0x72 && i + 4 <= il.Length) {
                int tok = BitConverter.ToInt32(il, i); i += 4;
                try {
                    string s = mod.ResolveString(tok);
                    if (s == "add_submodel" || s == "remove_submodel" || s == "slot_opacities" || s == "start_mtn") {
                        Console.WriteLine("  >> STR: " + s);
                        printNext = true; countdown = 25;
                    } else if (printNext) {
                        Console.WriteLine("     STR: " + s);
                    }
                } catch {}
            } else if ((op == 0x28 || op == 0x6F || op == 0x73) && i + 4 <= il.Length) {
                int tok = BitConverter.ToInt32(il, i); i += 4;
                if (printNext) {
                    try { var mb = mod.ResolveMethod(tok); Console.WriteLine("     CALL: " + (mb.DeclaringType!=null?mb.DeclaringType.Name+".":"") + mb.Name); } catch {}
                    if (--countdown <= 0) printNext = false;
                }
            }
        }
    }
}
