using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLWDetails {
    static void Main() {
        string managed = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            string name = new AssemblyName(e.Name).Name + ".dll";
            string p = Path.Combine(managed, name);
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(managed, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        Type[] types;
        try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }

        DumpMethod(types, mod, "ModelConfigData", "PostUpdate");
        DumpMethod(types, mod, "BHNCAHBOMMP", "FKJLDFKKNFF");
        DumpMethod(types, mod, "NMCLGFDFFLL", "PHHJAFLKKBN");
        DumpMethod(types, mod, "HLGNFAFIPOA", "FLHADBJDBIM");
        DumpTypeSummary(types, "BHNCAHBOMMP");
        DumpTypeSummary(types, "NMCLGFDFFLL");
        DumpTypeSummary(types, "GIHOEFBECLE");
        DumpTypeSummary(types, "CNPFPOADJLP");
    }

    static void DumpTypeSummary(Type[] types, string name) {
        var t = types.FirstOrDefault(x => x.Name == name);
        if (t == null) return;
        Console.WriteLine("\n=== TYPE " + t.FullName + " : " + (t.BaseType != null ? t.BaseType.Name : "") + " ===");
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly).Take(20))
            Console.WriteLine("  F: " + f.FieldType.Name + " " + f.Name);
        foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly).Take(15))
            Console.WriteLine("  M: " + m.ReturnType.Name + " " + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name)) + ")");
    }

    static void DumpMethod(Type[] types, Module mod, string typeName, string methodName) {
        var t = types.FirstOrDefault(x => x.Name == typeName);
        if (t == null) { Console.WriteLine("Missing type " + typeName); return; }
        foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly).Where(x => x.Name == methodName)) {
            Console.WriteLine("\n=== METHOD " + t.FullName + "::" + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name)) + ") ===");
            var body = m.GetMethodBody();
            if (body == null) continue;
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
                }
            }
        }
    }
}
