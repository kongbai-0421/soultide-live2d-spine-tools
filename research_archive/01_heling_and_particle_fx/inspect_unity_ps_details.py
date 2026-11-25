import sys
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab

def inspect_fx(rel, container_key_or_id):
    print(f"\n=== {rel} :: {container_key_or_id} ===")
    env = load_ab(CDN_ROOT / rel)
    obj_by_id = {o.path_id: o for o in env.objects}
    if isinstance(container_key_or_id, int):
        root_id = container_key_or_id
    else:
        root_id = {k.lower(): v.path_id for k, v in (env.container or {}).items()}[container_key_or_id.lower()]

    def walk(go_id, path=""):
        go = obj_by_id[go_id].read()
        cur_path = f"{path}/{go.m_Name}" if path else go.m_Name
        rt = None
        for c in go.m_Component:
            co = obj_by_id.get(c.component.path_id)
            if not co: continue
            if co.type.name in ("RectTransform", "Transform"):
                rt = co.read()
            elif co.type.name == "ParticleSystem":
                tt = co.read_typetree()
                em = tt.get("EmissionModule", {})
                sh = tt.get("ShapeModule", {})
                sz = tt.get("SizeModule", {})
                col = tt.get("ColorModule", {})
                vel = tt.get("VelocityModule", {})
                uv = tt.get("UVModule", {})
                rot = tt.get("RotationModule", {})
                init = tt.get("InitialModule", {})
                mat_name = "?"
                tex_names = []
                cols = {}
                for c2 in go.m_Component:
                    co2 = obj_by_id.get(c2.component.path_id)
                    if co2 and co2.type.name == "ParticleSystemRenderer":
                        psr_tt = co2.read_typetree()
                        mids = [m["m_PathID"] for m in psr_tt.get("m_Materials", []) if m.get("m_PathID")]
                        if mids and mids[0] in obj_by_id:
                            mat = obj_by_id[mids[0]].read_typetree()
                            mat_name = mat.get("m_Name", "?")
                            shd_id = mat.get("m_Shader", {}).get("m_PathID", 0)
                            shd_name = obj_by_id[shd_id].peek_name() if shd_id in obj_by_id else f"ext_shd:{mat.get('m_Shader')}"
                            sp = mat.get("m_SavedProperties", {})
                            for k, v in sp.get("m_TexEnvs", []):
                                tpid = v.get("m_Texture", {}).get("m_PathID", 0)
                                tname = obj_by_id[tpid].peek_name() if tpid in obj_by_id else f"ext:{v.get('m_Texture', {})}"
                                tex_names.append(f"{k}:{tname}")
                            cols = {k: v for k, v in sp.get("m_Colors", [])}
                            flts = {k: v for k, v in sp.get("m_Floats", [])}
                if "FX" in cur_path or "effect" in cur_path:
                    print(f"[{cur_path}] act={go.m_IsActive}")
                    print(f"  PS: dur={tt.get('lengthInSec')} loop={tt.get('looping')} prewarm={tt.get('prewarm')} scaling={tt.get('scalingMode')} simSpace={tt.get('moveWithTransform')}")
                    print(f"  Init: life=({init.get('startLifetime',{}).get('scalar')},{init.get('startLifetime',{}).get('minScalar')}) spd=({init.get('startSpeed',{}).get('scalar')},{init.get('startSpeed',{}).get('minScalar')}) size=({init.get('startSize',{}).get('scalar')},{init.get('startSize',{}).get('minScalar')}) rot=({init.get('startRotation',{}).get('scalar')},{init.get('startRotation',{}).get('minScalar')}) col={init.get('startColor',{}).get('maxColor')} maxP={init.get('maxNumParticles')}")
                    print(f"  Emis: en={em.get('enabled')} rate={em.get('rateOverTime',{}).get('scalar')} bursts={em.get('m_Bursts', [])}")
                    print(f"  Shape: en={sh.get('enabled')} type={sh.get('type')} rad={sh.get('radius',{}).get('value')} box={sh.get('m_Scale')}")
                    if uv.get("enabled"):
                        print(f"  UV: tiles=({uv.get('tilesX')},{uv.get('tilesY')}) cycles={uv.get('cycles')}")
                    if col.get("enabled"):
                        print(f"  ColorOverLife: enabled=True")
                    if sz.get("enabled"):
                        print(f"  SizeOverLife: enabled=True")
                    if vel.get("enabled"):
                        print(f"  Vel: x={vel.get('x',{}).get('scalar')} y={vel.get('y',{}).get('scalar')}")
                    if rot.get("enabled"):
                        print(f"  RotOverLife: curve={rot.get('curve',{}).get('scalar')}")
                    print(f"  Mat={mat_name} tex={tex_names} matCols={cols}")
        if rt and hasattr(rt, "m_Children"):
            for ch in rt.m_Children:
                if ch.path_id in obj_by_id:
                    ch_tf = obj_by_id[ch.path_id].read()
                    if ch_tf.m_GameObject.path_id in obj_by_id:
                        walk(ch_tf.m_GameObject.path_id, cur_path)

    walk(root_id)

inspect_fx("03_prefabs/ui.ab", 8268094511723853665)
inspect_fx("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_chat.prefab")
inspect_fx("03_prefabs/art_prefabs.ab", "assets/03_prefabs/art_prefabs/effect/fx_ui/aurora_s4_background_touch1.prefab")
