import subprocess

ps = r"""
$cecil = 'D:\Program Files\Unity\Hub\Editor\2021.3.34f1\Editor\Data\Managed\Unity.Cecil.dll'
$managed = 'C:\Program Files (x86)\Steam\steamapps\common\Live2DViewerEX\bin\lw\lw_Data\Managed'
[System.Reflection.Assembly]::LoadFrom($cecil) | Out-Null
$asm = [Mono.Cecil.AssemblyDefinition]::ReadAssembly("$managed\Assembly-CSharp.dll")
$t = $asm.MainModule.Types | Where-Object { $_.Name -eq 'GPALIHHOLBL' }
$m = $t.Methods | Where-Object { $_.Name -eq 'GHLCLBDNNIA' }
Write-Output ('METHOD: ' + $m.FullName)
foreach ($ins in $m.Body.Instructions) {
    Write-Output ('  ' + $ins.ToString())
}
"""
print(subprocess.check_output(["powershell", "-NoProfile", "-Command", ps]).decode("utf-8"))
