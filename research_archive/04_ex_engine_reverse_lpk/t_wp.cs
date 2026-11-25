using System;
using System.IO;
using System.Linq;
using System.Reflection;

class T {
    static void Main() {
        string m = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var p = Path.Combine(m, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var a = Assembly.LoadFrom(Path.Combine(m, "Assembly-CSharp.dll"));
        var t = a.GetTypes().First(x => x.Name == "CNPFPOADJLP");
        foreach (var mi in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)) {
            if ((mi.Attributes & MethodAttributes.PinvokeImpl) != 0) {
                var dll = mi.GetCustomAttributesData().FirstOrDefault(d => d.AttributeType.Name == "DllImportAttribute");
                Console.WriteLine(mi.Name + " -> " + (dll != null ? dll.ToString() : "?"));
            }
        }
    }
}
