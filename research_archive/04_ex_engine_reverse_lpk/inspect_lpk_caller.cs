using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectLpkCaller {
    static void Main() {
        string exM = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\exstudio\exstudio_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(exM, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(exM, "Assembly-CSharp.dll"));
        var mod = asm.ManifestModule;
        var abnj = asm.GetTypes().First(x => x.Name == "ABNJPMKACGP");
        var zipToks = abnj.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Static)
                          .Where(m => m.Name == "OHPDOFAAJBF" || m.Name == "PEOHPOHOHLO" || m.Name == "FMMHHFBPGON" || m.Name == "KGLBIFNMELK")
                          .Select(m => m.MetadataToken).ToHashSet();

        foreach (var t in asm.GetTypes()) {
            foreach (var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)) {
                var body = m.GetMethodBody();
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                bool hit = false;
                for (int i = 0; i + 5 <= il.Length; i++) {
                    if ((il[i] == 0x28 || il[i] == 0x6F) && zipToks.Contains(BitConverter.ToInt32(il, i + 1))) { hit = true; break; }
                }
                if (hit) {
                    Console.WriteLine("CALLER: " + t.FullName + "::" + m.Name);
                    // print strings and key calls
                    int j = 0;
                    while (j < il.Length) {
                        byte op = il[j++];
                        if (op == 0x72 && j + 4 <= il.Length) {
                            int tok = BitConverter.ToInt32(il, j); j += 4;
                            try { string s = mod.ResolveString(tok); if (s.Length < 40) Console.WriteLine("  S: " + s); } catch {}
                        } else if ((op == 0x28 || op == 0x6F) && j + 4 <= il.Length) {
                            int tok = BitConverter.ToInt32(il, j); j += 4;
                            try {
                                var mb = mod.ResolveMethod(tok);
                                string mn = (mb.DeclaringType!=null?mb.DeclaringType.Name+".":"") + mb.Name;
                                if (mn.Contains("MD5") || mn.Contains("Encrypt") || mn.Contains("Copy") || mn.Contains("Dict") || mn.Contains("Hash") || mn.Contains("ContainsKey") || mn.Contains("GetDirectory") || mn.Contains("Directory"))
                                    Console.WriteLine("  C: " + mn);
                            } catch {}
                        }
                    }
                }
            }
        }
    }
}
