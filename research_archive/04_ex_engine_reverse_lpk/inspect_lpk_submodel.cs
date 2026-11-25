using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLpkSubmodelScan {
    static void Main() {
        string exM = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(exM, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(exM, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        var t = asm.GetTypes().First(x => x.Name == "EBEKBDCAOFB");

        // Find which method in EBEKBDCAOFB handles "add_submodel" when packing LPK!
        foreach (var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)) {
            var body = m.GetMethodBody(); if (body == null) continue;
            var il = body.GetILAsByteArray();
            var strs = new System.Collections.Generic.List<string>();
            int i = 0;
            while (i < il.Length) {
                byte op = il[i++];
                if (op == 0x72 && i + 4 <= il.Length) {
                    int tok = BitConverter.ToInt32(il, i); i += 4;
                    try {
                        string s = mod.ResolveString(tok);
                        if (s.Contains("submodel") || s == "start" || s == "motions" || s == "command" || s == "post_command" || s == ";")
                            strs.Add(s);
                    } catch {}
                }
            }
            if (strs.Count > 0) {
                Console.WriteLine(m.Name + " -> " + string.Join(", ", strs.Distinct()));
            }
        }

        // Also check ZipOutputStream UseZip64 in ABNJPMKACGP / EBEKBDCAOFB
        Console.WriteLine("\n=== Checking Zip64 support in ZipOutputStream ===");
        var zipT = asm.GetReferencedAssemblies();
        foreach (var r in zipT) if (r.Name.Contains("Zip") || r.Name.Contains("Sharp")) Console.WriteLine("  Ref: " + r.FullName);
        var zos = AppDomain.CurrentDomain.GetAssemblies().SelectMany(a => { try { return a.GetTypes(); } catch { return new Type[0]; } }).FirstOrDefault(x => x.Name == "ZipOutputStream");
        if (zos != null) Console.WriteLine("  ZipOutputStream: " + zos.FullName + " UseZip64=" + (zos.GetProperty("UseZip64") != null));
    }
}
