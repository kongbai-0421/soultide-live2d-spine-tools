using System;
using System.IO;
using System.Linq;
using System.Reflection;

class InspectWebPAtlas {
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

        // Check where Option.tex_type is read across the whole assembly!
        var optType = types.First(t => t.FullName == "ModelConfigData+Option");
        var texTypeField = optType.GetField("tex_type");
        int targetToken = texTypeField.MetadataToken;
        Console.WriteLine("Option.tex_type token: 0x" + targetToken.ToString("X"));

        foreach (var t in types) {
            if ((t.FullName ?? "").StartsWith("Spine") || (t.FullName ?? "").StartsWith("DragonBones")) continue;
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                MethodBody body = null;
                try { body = m.GetMethodBody(); } catch { continue; }
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                for (int i = 0; i + 5 <= il.Length; i++) {
                    byte op = il[i];
                    if (op == 0x7B || op == 0x7D) {
                        int tok = BitConverter.ToInt32(il, i + 1);
                        if (tok == targetToken) {
                            Console.WriteLine("  REF: " + t.FullName + "::" + m.Name + " (" + (op == 0x7B ? "LDFLD" : "STFLD") + ")");
                        }
                    }
                }
            }
        }

        // Also check SpineAtlas.tex_names usage!
        var saType = types.First(t => t.FullName == "ModelConfigData+SpineAtlas");
        int tnTok = saType.GetField("tex_names").MetadataToken;
        int txTok = saType.GetField("textures").MetadataToken;
        Console.WriteLine("\n=== References to SpineAtlas.tex_names & textures ===");
        foreach (var t in types) {
            if ((t.FullName ?? "").StartsWith("Spine") || (t.FullName ?? "").StartsWith("DragonBones")) continue;
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)) {
                MethodBody body = null;
                try { body = m.GetMethodBody(); } catch { continue; }
                if (body == null) continue;
                var il = body.GetILAsByteArray();
                bool hitTn = false, hitTx = false;
                for (int i = 0; i + 5 <= il.Length; i++) {
                    byte op = il[i];
                    if (op == 0x7B || op == 0x7D) {
                        int tok = BitConverter.ToInt32(il, i + 1);
                        if (tok == tnTok) hitTn = true;
                        if (tok == txTok) hitTx = true;
                    }
                }
                if (hitTn || hitTx) Console.WriteLine("  " + t.FullName + "::" + m.Name + " tn=" + hitTn + " tx=" + hitTx);
            }
        }
    }
}
