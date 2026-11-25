using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;

class Program {
    static Dictionary<short, OpCode> ops = new Dictionary<short, OpCode>();
    static void InitOps() {
        foreach (var f in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
            if (f.FieldType == typeof(OpCode)) { var op = (OpCode)f.GetValue(null); ops[op.Value] = op; }
    }
    static void DumpIL(MethodBase m) {
        Console.WriteLine("=== " + m.DeclaringType.FullName + "::" + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name)) + ") ===");
        var body = m.GetMethodBody();
        if (body == null) return;
        var il = body.GetILAsByteArray();
        var mod = m.Module;
        int i = 0;
        while (i < il.Length) {
            int pos = i;
            short code = il[i++];
            if (code == 0xFE) code = (short)((code << 8) | il[i++]);
            OpCode op;
            if (!ops.TryGetValue(code, out op)) break;
            string arg = "";
            switch (op.OperandType) {
                case OperandType.InlineNone: break;
                case OperandType.ShortInlineBrTarget: arg = "IL_" + (i + 1 + (sbyte)il[i]).ToString("X4"); i += 1; break;
                case OperandType.InlineBrTarget: arg = "IL_" + (i + 4 + BitConverter.ToInt32(il, i)).ToString("X4"); i += 4; break;
                case OperandType.ShortInlineI: arg = ((sbyte)il[i]).ToString(); i += 1; break;
                case OperandType.InlineI: arg = BitConverter.ToInt32(il, i).ToString(); i += 4; break;
                case OperandType.InlineI8: arg = BitConverter.ToInt64(il, i).ToString(); i += 8; break;
                case OperandType.ShortInlineR: arg = BitConverter.ToSingle(il, i).ToString(); i += 4; break;
                case OperandType.InlineR: arg = BitConverter.ToDouble(il, i).ToString(); i += 8; break;
                case OperandType.ShortInlineVar: arg = "V_" + il[i]; i += 1; break;
                case OperandType.InlineVar: arg = "V_" + BitConverter.ToUInt16(il, i); i += 2; break;
                case OperandType.InlineString:
                    try { arg = "\"" + mod.ResolveString(BitConverter.ToInt32(il, i)) + "\""; } catch { arg = "str"; }
                    i += 4; break;
                case OperandType.InlineMethod:
                case OperandType.InlineField:
                case OperandType.InlineType:
                case OperandType.InlineTok:
                    int tok = BitConverter.ToInt32(il, i); i += 4;
                    try {
                        var mem = mod.ResolveMember(tok, m.DeclaringType.IsGenericType ? m.DeclaringType.GetGenericArguments() : null, (m is MethodInfo && m.IsGenericMethod) ? m.GetGenericArguments() : null);
                        arg = (mem.DeclaringType != null ? mem.DeclaringType.Name + "::" : "") + mem.Name;
                    } catch { arg = "tok_" + tok.ToString("X"); }
                    break;
                case OperandType.InlineSig: i += 4; break;
                case OperandType.InlineSwitch: int cnt = BitConverter.ToInt32(il, i); i += 4 + cnt * 4; arg = "switch(" + cnt + ")"; break;
            }
            Console.WriteLine("  IL_" + pos.ToString("X4") + ": " + op.Name + (arg.Length > 0 ? " " + arg : ""));
        }
    }
    static void Main() {
        InitOps();
        string managed = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed\";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var n = new AssemblyName(e.Name).Name + ".dll";
            var p = Path.Combine(managed, n);
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(managed, "Assembly-CSharp.dll"));
        Type[] types;
        try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }
        foreach (var t in types) {
            if (t.BaseType != null && t.BaseType.Name == "BHNCAHBOMMP") {
                Console.WriteLine("SUBCLASS: " + t.FullName);
                foreach (var f in t.GetFields(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.DeclaredOnly)) {
                    if (f.FieldType.FullName.Contains("Spine3_8")) Console.WriteLine("  SPINE38 FIELD: " + f.Name + " : " + f.FieldType.FullName);
                }
            }
        }
        // Find Spine3_8 SkeletonAnimation loader
        foreach (var t in types) {
            if (t.BaseType != null && t.BaseType.Name == "BHNCAHBOMMP") {
                bool isS38 = t.GetFields(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.DeclaredOnly)
                    .Any(f => f.FieldType.FullName.Contains("Spine3_8"));
                if (isS38) {
                    foreach (var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.DeclaredOnly)) {
                        if (m.Name == "IMEMBNEEADL" || m.Name == "JIGBHLGFJLA" || m.Name.Contains("Scale") || m.Name.Contains("Load")) {
                            DumpIL(m);
                        }
                    }
                }
            }
        }
    }
}
