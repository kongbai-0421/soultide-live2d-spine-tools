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
    static void Dump(MethodBase m) {
        Console.WriteLine("=== " + m.DeclaringType.FullName + "::" + m.Name + " ===");
        var body = m.GetMethodBody(); if (body == null) return;
        var il = body.GetILAsByteArray(); var mod = m.Module;
        int i = 0;
        while (i < il.Length) {
            int pos = i; short code = il[i++];
            if (code == 0xFE) code = (short)((code << 8) | il[i++]);
            OpCode op; if (!ops.TryGetValue(code, out op)) break;
            string arg = "";
            switch (op.OperandType) {
                case OperandType.InlineNone: break;
                case OperandType.ShortInlineBrTarget: i += 1; break;
                case OperandType.InlineBrTarget: i += 4; break;
                case OperandType.ShortInlineI: arg = ((sbyte)il[i]).ToString(); i += 1; break;
                case OperandType.InlineI: arg = BitConverter.ToInt32(il, i).ToString(); i += 4; break;
                case OperandType.InlineI8: i += 8; break;
                case OperandType.ShortInlineR: arg = BitConverter.ToSingle(il, i).ToString(); i += 4; break;
                case OperandType.InlineR: arg = BitConverter.ToDouble(il, i).ToString(); i += 8; break;
                case OperandType.ShortInlineVar: i += 1; break;
                case OperandType.InlineVar: i += 2; break;
                case OperandType.InlineString: try { arg = "\"" + mod.ResolveString(BitConverter.ToInt32(il, i)) + "\""; } catch {} i += 4; break;
                case OperandType.InlineMethod: case OperandType.InlineField: case OperandType.InlineType: case OperandType.InlineTok:
                    int tok = BitConverter.ToInt32(il, i); i += 4;
                    try { var mem = mod.ResolveMember(tok); arg = (mem.DeclaringType != null ? mem.DeclaringType.Name + "::" : "") + mem.Name; } catch {}
                    break;
                case OperandType.InlineSig: i += 4; break;
                case OperandType.InlineSwitch: int cnt = BitConverter.ToInt32(il, i); i += 4 + cnt * 4; break;
            }
            if (op.Name == "ldc.r4" || op.Name == "mul" || op.Name == "div" || arg.Contains("scale") || arg.Contains("Scale") || arg.Contains("orthographic") || arg.Contains("Position") || arg.Contains("position") || arg.Contains("LoadImage") || arg.Contains("CreateRuntimeInstance"))
                Console.WriteLine("  IL_" + pos.ToString("X4") + ": " + op.Name + " " + arg);
        }
    }
    static void Main() {
        InitOps();
        string managed = @"C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed\";
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => { var p = Path.Combine(managed, new AssemblyName(e.Name).Name + ".dll"); return File.Exists(p) ? Assembly.LoadFrom(p) : null; };
        var asm = Assembly.LoadFrom(Path.Combine(managed, "Assembly-CSharp.dll"));
        foreach (var tn in new[]{"IEJFLMGGNHD", "SpineModel3_8"}) {
            var t = asm.GetType(tn);
            foreach (var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly)) {
                var b = m.GetMethodBody();
                if (b != null && (m.Name == "IMEMBNEEADL" || m.Name.Contains("Create") || m.Name.Contains("Load") || m.Name.Contains("Init") || b.GetILAsByteArray().Length > 400))
                    Dump(m);
            }
        }
    }
}
