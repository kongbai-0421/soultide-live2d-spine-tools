using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;

class Program {
    static Dictionary<short, OpCode> ops = new Dictionary<short, OpCode>();
    static void InitOps() {
        foreach (var f in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)) {
            if (f.FieldType == typeof(OpCode)) {
                var op = (OpCode)f.GetValue(null);
                ops[op.Value] = op;
            }
        }
    }
    static void DumpIL(MethodBase m, int maxLines) {
        Console.WriteLine("=== " + m.DeclaringType.FullName + "::" + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name)) + ") ===");
        var body = m.GetMethodBody();
        if (body == null) { Console.WriteLine("  <no body>"); return; }
        var il = body.GetILAsByteArray();
        var mod = m.Module;
        int i = 0, printed = 0;
        while (i < il.Length && printed < maxLines) {
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
                    try { arg = "\"" + mod.ResolveString(BitConverter.ToInt32(il, i)) + "\""; } catch { arg = "str?" + BitConverter.ToInt32(il, i).ToString("X"); }
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
            printed++;
        }
    }
    static bool HasStfldOrLdfld(MethodBase m, HashSet<string> fieldNames, bool onlyStore) {
        var body = m.GetMethodBody();
        if (body == null) return false;
        var il = body.GetILAsByteArray();
        var mod = m.Module;
        int i = 0;
        while (i < il.Length) {
            short code = il[i++];
            if (code == 0xFE) code = (short)((code << 8) | il[i++]);
            OpCode op;
            if (!ops.TryGetValue(code, out op)) break;
            switch (op.OperandType) {
                case OperandType.InlineNone: break;
                case OperandType.ShortInlineBrTarget:
                case OperandType.ShortInlineI:
                case OperandType.ShortInlineVar: i += 1; break;
                case OperandType.InlineVar: i += 2; break;
                case OperandType.InlineBrTarget:
                case OperandType.InlineI:
                case OperandType.ShortInlineR:
                case OperandType.InlineString:
                case OperandType.InlineSig: i += 4; break;
                case OperandType.InlineI8:
                case OperandType.InlineR: i += 8; break;
                case OperandType.InlineSwitch: int cnt = BitConverter.ToInt32(il, i); i += 4 + cnt * 4; break;
                case OperandType.InlineMethod:
                case OperandType.InlineField:
                case OperandType.InlineType:
                case OperandType.InlineTok:
                    int tok = BitConverter.ToInt32(il, i); i += 4;
                    if (op.OperandType == OperandType.InlineField && (!onlyStore || op.Name == "stfld")) {
                        try {
                            var mem = mod.ResolveMember(tok, m.DeclaringType.IsGenericType ? m.DeclaringType.GetGenericArguments() : null, (m is MethodInfo && m.IsGenericMethod) ? m.GetGenericArguments() : null);
                            if (mem != null && fieldNames.Contains(mem.Name)) return true;
                        } catch {}
                    }
                    break;
            }
        }
        return false;
    }
    static void Main(string[] args) {
        InitOps();
        string managed = args[0];
        string mode = args[1];
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            var n = new AssemblyName(e.Name).Name + ".dll";
            var p = Path.Combine(managed, n);
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(managed, "Assembly-CSharp.dll"));
        Type[] types;
        try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }
        var targetFields = new HashSet<string> { "scale_factor", "position_x", "position_y", "BFPMDIFELDD" };
        foreach (var t in types) {
            foreach (var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)) {
                if (mode == "studio") {
                    if (HasStfldOrLdfld(m, new HashSet<string>{"scale_factor","position_x","position_y"}, true)) {
                        DumpIL(m, 200);
                    }
                } else if (mode == "spine_scale") {
                    if ((t.Name == "IPIMLPLPGOJ" && m.Name == "IMEMBNEEADL") ||
                        (t.Name == "BHNCAHBOMMP" && m.Name == "JIGBHLGFJLA") ||
                        (t.Name == "Live2DModelProxyBase" && (HasStfldOrLdfld(m, new HashSet<string>{"BFPMDIFELDD"}, false)))) {
                        DumpIL(m, 250);
                    }
                }
            }
        }
    }
}
