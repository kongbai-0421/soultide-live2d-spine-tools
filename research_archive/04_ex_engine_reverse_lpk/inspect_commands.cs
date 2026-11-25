using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectCommands {
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

        // Find the command dispatcher method containing "add_submodel" and "remove_submodel"
        Console.WriteLine("=== Command Dispatcher Methods in lw.exe ===");
        foreach (var t in types) {
            if ((t.FullName ?? "").StartsWith("Spine") || (t.FullName ?? "").StartsWith("DragonBones")) continue;
            foreach (var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)) {
                MethodBody body = null;
                try { body = m.GetMethodBody(); } catch { continue; }
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                var strs = new System.Collections.Generic.List<string>();
                bool hasAdd = false, hasRem = false;
                int i = 0;
                while (i < il.Length) {
                    byte op = il[i++];
                    if (op == 0x72 && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try {
                            string s = mod.ResolveString(tok);
                            if (s == "add_submodel") hasAdd = true;
                            if (s == "remove_submodel") hasRem = true;
                            if (s.Length > 0 && s.Length < 35 && !s.Contains(" ") && s.All(c => char.IsLetterOrDigit(c) || c == '_'))
                                strs.Add(s);
                        } catch {}
                    }
                }
                if (hasAdd && hasRem) {
                    Console.WriteLine("DISPATCHER: " + t.FullName + "::" + m.Name);
                    Console.WriteLine("  COMMANDS: " + string.Join(", ", strs.Distinct()));
                }
            }
        }

        // Also inspect Live2DModelProxyBase::RemoveSubModel and AddSubModel!
        var proxy = types.First(t => t.Name == "Live2DModelProxyBase");
        foreach (var m in proxy.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)) {
            if (m.Name.Contains("SubModel") || m.Name.Contains("KeyTrigger") || m.Name.Contains("Choice")) {
                Console.WriteLine("\nPROXY METHOD: " + m.ReturnType.Name + " " + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name)) + ")");
                var body = m.GetMethodBody();
                if (body == null) continue;
                var il = body.GetILAsByteArray(); int i = 0;
                while (i < il.Length) {
                    byte op = il[i++];
                    if (op == 0x72 && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try { Console.WriteLine("  S: " + mod.ResolveString(tok)); } catch {}
                    } else if ((op == 0x28 || op == 0x6F) && i + 4 <= il.Length) {
                        int tok = BitConverter.ToInt32(il, i); i += 4;
                        try { var mb = mod.ResolveMethod(tok); Console.WriteLine("  C: " + (mb.DeclaringType!=null?mb.DeclaringType.Name+".":"") + mb.Name); } catch {}
                    }
                }
            }
        }
    }
}
