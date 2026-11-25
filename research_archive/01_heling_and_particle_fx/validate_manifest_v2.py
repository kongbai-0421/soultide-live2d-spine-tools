import json
from pathlib import Path

m_path = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\fx_manifest.json")
m = json.loads(m_path.read_text(encoding="utf-8"))
mesh_dir = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\Assets\Meshes")
objs = list(mesh_dir.glob("*.obj")) if mesh_dir.exists() else []

total_nodes = 0
rm4_total = rm4_resolved = rm4_builtin = rm4_missing = 0
trail_count = 0
trail_no_main = 0
mask2_cnt = diss_cnt = dist_cnt = uv_cnt = 0
low_mul = []
z0_cnt = 0
max_psz_vals = set()
rate_dist_cnt = 0

for s in m["skins"]:
    for c in s["clips"]:
        for n in c["nodes"]:
            total_nodes += 1
            if abs(n["world_scale"][2]) < 1e-4:
                z0_cnt += 1
            max_psz_vals.add(round(n.get("maxParticleSize", -1), 2))
            if n.get("rateOverDistance", 0) > 0:
                rate_dist_cnt += 1
            if n["renderMode"] == 4:
                rm4_total += 1
                mn = n.get("meshName", "")
                if mn.startswith("BUILTIN_"):
                    rm4_builtin += 1
                elif mn and (mesh_dir / f"{mn}.obj").is_file():
                    rm4_resolved += 1
                else:
                    rm4_missing += 1
            if n.get("trailsEnabled"):
                trail_count += 1
                if not n.get("hasMainMaterial") or n["renderMode"] == 5:
                    trail_no_main += 1
            if n.get("mask2TexName"): mask2_cnt += 1
            if n.get("dissolve", 0) > 0.001: diss_cnt += 1
            if abs(n.get("distortStrength", 0)) > 1e-4: dist_cnt += 1
            if any(abs(v) > 1e-5 for v in (n.get("uvScroll") or [])): uv_cnt += 1
            if n.get("tintMultiplier", 1.0) < 0.2:
                low_mul.append((s["skin_key"], c["clip"], n["name"], n.get("matName"), n.get("tintMultiplier")))

print(f"Skins={len(m['skins'])}, Nodes={total_nodes}, ExportedOBJs={len(objs)}")
print(f"rm==4: total={rm4_total}, custom_obj={rm4_resolved}, builtin={rm4_builtin}, missing={rm4_missing}")
print(f"trailsEnabled={trail_count} (trail_only/no_main={trail_no_main}), rateOverDist={rate_dist_cnt}, z0={z0_cnt}")
print(f"mask2={mask2_cnt}, dissolve={diss_cnt}, distort={dist_cnt}, uvScroll={uv_cnt}")
print(f"low_mul (<0.2) count={len(low_mul)}: {low_mul}")

# Check Freesia_S5, RubyRose_S2, Minerdwen_S3, QuLing_S2, Ennis_S2
for sk in ("402_Freesia_S5", "4501_RubyRose_S2", "702_Minerdwen_S3", "2301_QuLing_S2", "2001_Ennis_S2"):
    row = next(s for s in m["skins"] if s["skin_key"] == sk)
    print(f"\n[{sk}] cam=({row['cam_x']},{row['cam_y']}) canvas=({row['canvas_w']}x{row['canvas_h']})")
    for c in row["clips"]:
        for n in c["nodes"]:
            print(f"  {c['clip']}/{n['name']:14s} wpos=({n['world_pos'][0]:.1f},{n['world_pos'][1]:.1f}) wsc=({n['world_scale'][0]:.2f},{n['world_scale'][2]:.2f}) maxPSz={n.get('maxParticleSize')} align={n.get('renderAlignment')} mul={n.get('tintMultiplier')} tint_a={n['tint'].get('a'):.2f} mesh={n.get('meshName')}")

# Write pilot_manifest.json for targeted verification
pilot_keys = {
    "402_Freesia_S5", "3501_QingDai_S2", "2002_Ennis_S3", "1202_Virgina_S3",
    "603_Asuna_S8", "2301_QuLing_S2", "4501_RubyRose_S2", "503_Benten_S4",
    "1101_NicoletteLamel_S2", "2001_Ennis_S2", "2802_Mist_S3", "3801_LightCloud_S2",
    "1601_Gawana_S2", "3602_QingHao_S3", "1903_Aurora_S5", "702_Minerdwen_S3",
    "2003_Ennis_S4", "4002_Philodoxy_S3",
}
pilot = {"skins": [s for s in m["skins"] if s["skin_key"] in pilot_keys]}
pilot_path = Path(r"E:\A灵魂潮汐\tools\SoulTideBatchFxUnity\pilot_manifest.json")
pilot_path.write_text(json.dumps(pilot, ensure_ascii=False), encoding="utf-8")
print(f"\nWrote {pilot_path} with {len(pilot['skins'])} skins")
