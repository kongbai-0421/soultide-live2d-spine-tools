using System;
using System.Linq;
using Mono.Cecil;

var mod = ModuleDefinition.ReadModule(@"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed\Assembly-CSharp.dll");
foreach (var t in mod.Types) {
    foreach (var m in t.Methods.Where(x => x.HasBody)) {
        bool hit = m.Body.Instructions.Any(i => i.Operand is MemberReference mr && (mr.Name.Contains("Choices") || mr.Name.Contains("NextMtn") || mr.Name.Contains("PlayMotion") || mr.Name.Contains("OnModelTapped")));
        if (hit) {
            Console.WriteLine($"=== {t.FullName}.{m.Name} ===");
            foreach (var ins in m.Body.Instructions) {
                if (ins.Operand != null) Console.WriteLine($"  {ins.OpCode.Name} {ins.Operand}");
            }
        }
    }
}
