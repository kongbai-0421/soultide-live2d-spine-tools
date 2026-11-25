#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Exports exact Unity ParticleSystem trajectories (`ParticleSystem.GetParticles`) and
/// UV-scrolling quad specs to JSON for Native Spine 3.8 Particle/Bone reconstruction.
/// </summary>
public static class SoulTideSpineParticleExporter
{
    private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    private static string GetArg(string flag, string fallback)
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (string.Equals(args[i], flag, StringComparison.OrdinalIgnoreCase))
                return args[i + 1];
        }
        return fallback;
    }

    private class SamplePt
    {
        public float t;
        public float x, y;
        public float sx, sy;
        public float rot;
        public float r, g, b, a;
        public int tile;
    }

    private class TrackData
    {
        public int nodeIdx;
        public uint seed;
        public float birthT;
        public float life;
        public float lastRem;
        public float lastVx, lastVy, lastAngVel;
        public float lastAge01;
        public Color startCol;
        public bool alive;
        public bool bornInWindow;
        public List<SamplePt> samples = new List<SamplePt>();
    }

    public static void ExportSkin()
    {
        string manifestPath = GetArg("-fxManifest", Path.Combine(Directory.GetCurrentDirectory(), "fx_manifest.json"));
        string skinKey = GetArg("-skinKey", "4301_HeLing_S2");
        string outJson = GetArg("-outJson", Path.Combine(Directory.GetCurrentDirectory(), "exported_particles.json"));
        float recordDur = float.Parse(GetArg("-recordDur", "42.0"), Inv);
        float sampleFps = float.Parse(GetArg("-sampleFps", "20.0"), Inv);

        string rawJson = File.ReadAllText(manifestPath, Encoding.UTF8);
        var manifest = JsonUtility.FromJson<SoulTideBatchFxRecorder.FxManifestDto>(rawJson);
        SoulTideBatchFxRecorder.FxSkinDto target = null;
        foreach (var s in manifest.skins)
        {
            if (s != null && string.Equals(s.skin_key, skinKey, StringComparison.OrdinalIgnoreCase))
            {
                target = s;
                break;
            }
        }
        if (target == null)
        {
            Debug.LogError("[SpineParticleExporter] Skin not found: " + skinKey);
            EditorApplication.Exit(2);
            return;
        }

        // Load mesh bounds cache
        var meshBounds = new Dictionary<string, Vector3>(StringComparer.OrdinalIgnoreCase);
        meshBounds["BUILTIN_QUAD"] = new Vector3(1f, 1f, 0f);
        if (AssetDatabase.IsValidFolder("Assets/Meshes"))
        {
            foreach (string fullPath in Directory.GetFiles(Path.Combine(Application.dataPath, "Meshes"), "*.obj", SearchOption.AllDirectories))
            {
                string ap = "Assets/Meshes/" + Path.GetFileName(fullPath);
                string stem = Path.GetFileNameWithoutExtension(fullPath);
                foreach (UnityEngine.Object sub in AssetDatabase.LoadAllAssetsAtPath(ap))
                {
                    if (sub is Mesh mm)
                    {
                        meshBounds[stem] = mm.bounds.size;
                        break;
                    }
                }
            }
        }

        var sb = new StringBuilder(1 << 20);
        sb.Append("{\n");
        sb.AppendFormat(Inv, "  \"skin_key\": \"{0}\",\n", Esc(target.skin_key));
        sb.AppendFormat(Inv, "  \"cam_x\": {0:F4}, \"cam_y\": {1:F4},\n", target.cam_x, target.cam_y);
        sb.AppendFormat(Inv, "  \"canvas_w\": {0}, \"canvas_h\": {1},\n", target.canvas_w, target.canvas_h);
        sb.AppendFormat(Inv, "  \"person_wx\": {0:F4}, \"person_wy\": {1:F4},\n", target.person_wx, target.person_wy);
        sb.AppendFormat(Inv, "  \"ui_per_spine_x\": {0:F6}, \"ui_per_spine_y\": {1:F6}, \"person_z_deg\": {2:F4},\n", target.ui_per_spine_x, target.ui_per_spine_y, target.person_z_deg);
        sb.AppendFormat(Inv, "  \"record_dur\": {0:F4}, \"sample_fps\": {1:F4},\n", recordDur, sampleFps);
        sb.Append("  \"clips\": [\n");

        for (int ci = 0; ci < target.clips.Length; ci++)
        {
            var clip = target.clips[ci];
            if (ci > 0) sb.Append(",\n");
            ExportClip(sb, clip, meshBounds, recordDur, sampleFps);
        }

        sb.Append("\n  ]\n}\n");
        Directory.CreateDirectory(Path.GetDirectoryName(outJson) ?? ".");
        File.WriteAllText(outJson, sb.ToString(), Encoding.UTF8);
        Debug.Log("[SpineParticleExporter] Exported -> " + outJson);
    }

    public static void ExportBatch()
    {
        string manifestPath = GetArg("-fxManifest", Path.Combine(Directory.GetCurrentDirectory(), "fx_manifest.json"));
        string skinKeysFile = GetArg("-skinKeysFile", "");
        string outDir = GetArg("-outDir", Path.Combine(Directory.GetCurrentDirectory(), "exported_particles_batch"));
        float recordDur = float.Parse(GetArg("-recordDur", "42.0"), Inv);
        float sampleFps = float.Parse(GetArg("-sampleFps", "20.0"), Inv);

        var wantKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (!string.IsNullOrEmpty(skinKeysFile) && File.Exists(skinKeysFile))
        {
            foreach (string line in File.ReadAllLines(skinKeysFile, Encoding.UTF8))
            {
                string t = line.Trim();
                if (!string.IsNullOrEmpty(t)) wantKeys.Add(t);
            }
        }

        string rawJson = File.ReadAllText(manifestPath, Encoding.UTF8);
        var manifest = JsonUtility.FromJson<SoulTideBatchFxRecorder.FxManifestDto>(rawJson);

        var meshBounds = new Dictionary<string, Vector3>(StringComparer.OrdinalIgnoreCase);
        meshBounds["BUILTIN_QUAD"] = new Vector3(1f, 1f, 0f);
        if (AssetDatabase.IsValidFolder("Assets/Meshes"))
        {
            foreach (string fullPath in Directory.GetFiles(Path.Combine(Application.dataPath, "Meshes"), "*.obj", SearchOption.AllDirectories))
            {
                string ap = "Assets/Meshes/" + Path.GetFileName(fullPath);
                string stem = Path.GetFileNameWithoutExtension(fullPath);
                foreach (UnityEngine.Object sub in AssetDatabase.LoadAllAssetsAtPath(ap))
                {
                    if (sub is Mesh mm)
                    {
                        meshBounds[stem] = mm.bounds.size;
                        break;
                    }
                }
            }
        }

        Directory.CreateDirectory(outDir);
        int exported = 0;
        foreach (var target in manifest.skins)
        {
            if (target == null || target.clips == null || target.clips.Length == 0) continue;
            if (wantKeys.Count > 0 && !wantKeys.Contains(target.skin_key)) continue;

            var sb = new StringBuilder(1 << 20);
            sb.Append("{\n");
            sb.AppendFormat(Inv, "  \"skin_key\": \"{0}\",\n", Esc(target.skin_key));
            sb.AppendFormat(Inv, "  \"cam_x\": {0:F4}, \"cam_y\": {1:F4},\n", target.cam_x, target.cam_y);
            sb.AppendFormat(Inv, "  \"canvas_w\": {0}, \"canvas_h\": {1},\n", target.canvas_w, target.canvas_h);
            sb.AppendFormat(Inv, "  \"person_wx\": {0:F4}, \"person_wy\": {1:F4},\n", target.person_wx, target.person_wy);
            sb.AppendFormat(Inv, "  \"ui_per_spine_x\": {0:F6}, \"ui_per_spine_y\": {1:F6}, \"person_z_deg\": {2:F4},\n", target.ui_per_spine_x, target.ui_per_spine_y, target.person_z_deg);
            sb.AppendFormat(Inv, "  \"record_dur\": {0:F4}, \"sample_fps\": {1:F4},\n", recordDur, sampleFps);
            sb.Append("  \"clips\": [\n");

            for (int ci = 0; ci < target.clips.Length; ci++)
            {
                var clip = target.clips[ci];
                if (ci > 0) sb.Append(",\n");
                ExportClip(sb, clip, meshBounds, recordDur, sampleFps);
            }

            sb.Append("\n  ]\n}\n");
            string outJson = Path.Combine(outDir, target.skin_key + ".json");
            File.WriteAllText(outJson, sb.ToString(), Encoding.UTF8);
            exported++;
            Debug.Log("[SpineParticleExporter] Batch exported (" + exported + "): " + target.skin_key);
        }
        Debug.Log("[SpineParticleExporter] Batch complete. Total exported=" + exported);
    }

    private static void ExportClip(
        StringBuilder sb,
        SoulTideBatchFxRecorder.FxClipDto clip,
        Dictionary<string, Vector3> meshBounds,
        float recordDur,
        float sampleFps
    )
    {
        GameObject root = new GameObject("Export_" + clip.clip);
        int N = clip.nodes.Length;
        var gos = new GameObject[N];
        var pss = new ParticleSystem[N];
        var rootSystems = new List<ParticleSystem>();
        var isUvScroll = new bool[N];
        var effTint = new Color[N];
        var meshSize = new Vector2[N];
        var uvCurves = new AnimationCurve[N];
        var colGrads = new Gradient[N];
        var sizeCurveX = new AnimationCurve[N];
        var sizeCurveY = new AnimationCurve[N];
        var hasOrigFadeIn = new bool[N];
        var hasOrigFadeOut = new bool[N];

        float maxNodeLt = 4f;
        uint seedBase = 1001u;
        for (int ni = 0; ni < N; ni++)
        {
            var n = clip.nodes[ni];
            if (n.ringBufferMode == 0 && n.lifetime != null)
            {
                float simSpdEst = n.simulationSpeed > 0.001f ? n.simulationSpeed : 1f;
                float ltHi = Mathf.Max(n.lifetime.scalar, n.lifetime.minScalar) / simSpdEst;
                if (ltHi < 99f) maxNodeLt = Mathf.Max(maxNodeLt, ltHi);
            }
            GameObject go = new GameObject(n.name ?? ("ps_" + ni));
            go.transform.SetParent(root.transform, false);
            if (n.world_pos != null && n.world_pos.Length >= 3)
                go.transform.position = new Vector3(n.world_pos[0], n.world_pos[1], n.world_pos[2]);
            if (n.world_rot != null && n.world_rot.Length >= 4)
                go.transform.rotation = new Quaternion(n.world_rot[0], n.world_rot[1], n.world_rot[2], n.world_rot[3]);
            if (n.world_scale != null && n.world_scale.Length >= 3)
                go.transform.localScale = new Vector3(
                    Mathf.Approximately(n.world_scale[0], 0f) ? 0.001f : n.world_scale[0],
                    Mathf.Approximately(n.world_scale[1], 0f) ? 0.001f : n.world_scale[1],
                    Mathf.Approximately(n.world_scale[2], 0f) ? 0.001f : n.world_scale[2]
                );

            ParticleSystem ps = go.AddComponent<ParticleSystem>();
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            ps.useAutoRandomSeed = false;
            ps.randomSeed = seedBase++;

            var main = ps.main;
            main.playOnAwake = !n.isSubEmitterChild;
            main.duration = Mathf.Max(0.1f, n.duration);
            main.startDelay = Mathf.Max(0f, n.startDelay);
            main.loop = n.looping;
            main.prewarm = n.prewarm && n.looping;
            if (n.ringBufferMode > 0)
            {
                main.ringBufferMode = (ParticleSystemRingBufferMode)Mathf.Clamp(n.ringBufferMode, 0, 2);
                if (n.ringBufferLoopRange != null && n.ringBufferLoopRange.Length >= 2)
                {
                    main.ringBufferLoopRange = new Vector2(
                        Mathf.Clamp01(n.ringBufferLoopRange[0]),
                        Mathf.Clamp01(n.ringBufferLoopRange[1])
                    );
                }
            }
            main.simulationSpeed = n.simulationSpeed > 0.001f ? n.simulationSpeed : 1f;
            main.scalingMode = ParticleSystemScalingMode.Hierarchy;
            main.simulationSpace = (n.simulationSpace == 1) ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
            main.maxParticles = Mathf.Clamp(n.maxParticles > 0 ? n.maxParticles : 50, 1, 2000);
            if (HasCurve(n.gravityModifier))
            {
                float gScale = Mathf.Abs(n.gravityScale) > 1e-4f ? n.gravityScale : 1f;
                main.gravityModifier = ToCurve(n.gravityModifier, 0f, gScale);
            }
            main.startLifetime = ToCurve(n.lifetime, 1f);
            main.startSpeed = ToCurve(n.speed, 0f);
            if (n.size3D && n.sizeX != null && n.sizeY != null)
            {
                main.startSize3D = true;
                main.startSizeX = ToCurve(n.sizeX, 1f);
                main.startSizeY = ToCurve(n.sizeY, 1f);
                main.startSizeZ = ToCurve(n.sizeZ, 1f);
            }
            else main.startSize = ToCurve(n.size, 1f);

            if (n.rotation3D)
            {
                main.startRotation3D = true;
                main.startRotationX = ToCurve(n.rotationX, 0f);
                main.startRotationY = ToCurve(n.rotationY, 0f);
                main.startRotationZ = ToCurve(n.rotation, 0f);
            }
            else main.startRotation = ToCurve(n.rotation, 0f);

            if ((n.startColorMode == 1 || n.startColorMode == 3 || n.startColorMode == 4) && n.startColorGrad != null &&
                (n.startColorGrad.ckeys?.Length > 0 || n.startColorGrad.akeys?.Length > 0))
            {
                var mmg = new ParticleSystem.MinMaxGradient(BuildGrad(n.startColorGrad));
                if (n.startColorMode == 4)
                    mmg.mode = ParticleSystemGradientMode.RandomColor;
                main.startColor = mmg;
            }
            else if (n.startColorMode == 2)
                main.startColor = new ParticleSystem.MinMaxGradient(ToCol(n.startColorMin), ToCol(n.startColor));
            else
                main.startColor = new ParticleSystem.MinMaxGradient(ToCol(n.startColor));

            var em = ps.emission;
            em.enabled = true;
            em.rateOverTime = HasCurve(n.rateCurve) ? ToCurve(n.rateCurve, n.rate) : new ParticleSystem.MinMaxCurve(Mathf.Max(0f, n.rate));
            if (HasCurve(n.rateOverDistanceCurve) || n.rateOverDistance > 0f)
            {
                em.rateOverDistance = HasCurve(n.rateOverDistanceCurve)
                    ? ToCurve(n.rateOverDistanceCurve, n.rateOverDistance)
                    : new ParticleSystem.MinMaxCurve(Mathf.Max(0f, n.rateOverDistance));
            }
            if (n.bursts != null && n.bursts.Length > 0)
            {
                var arr = new ParticleSystem.Burst[n.bursts.Length];
                for (int i = 0; i < n.bursts.Length; i++)
                {
                    var b = n.bursts[i];
                    short cmax = (short)Mathf.Clamp(Mathf.RoundToInt(b.count), 0, 1000);
                    short cmin = (b.mode == 3) ? (short)Mathf.Clamp(Mathf.RoundToInt(b.minCount), 0, 1000) : cmax;
                    if (cmin > cmax) { short tmp = cmin; cmin = cmax; cmax = tmp; }
                    int cyc = b.cycleCount <= 0 ? 0 : b.cycleCount;
                    float rep = Mathf.Max(0.01f, b.repeatInterval);
                    var burst = new ParticleSystem.Burst(Mathf.Max(0f, b.time), cmin, cmax, cyc == 0 ? 1 : cyc, rep);
                    if (cyc == 0) burst.cycleCount = 0;
                    arr[i] = burst;
                }
                em.SetBursts(arr);
            }

            var sh = ps.shape;
            sh.enabled = n.shapeEnabled;
            if (n.shapeEnabled)
            {
                sh.shapeType = (ParticleSystemShapeType)Mathf.Clamp(n.shapeType, 0, 20);
                sh.radius = n.shapeRadius;
                sh.angle = n.shapeAngle;
                sh.radiusThickness = n.shapeRadiusThickness;
                sh.randomDirectionAmount = n.shapeRandomDir;
                sh.sphericalDirectionAmount = n.shapeSphericalDir;
                sh.alignToDirection = n.shapeAlignToDir;
                if (n.shapeArc > 0.01f) sh.arc = n.shapeArc;
                if (n.shapeBox != null && n.shapeBox.Length >= 3) sh.scale = new Vector3(n.shapeBox[0], n.shapeBox[1], n.shapeBox[2]);
                if (n.shapeRot != null && n.shapeRot.Length >= 3) sh.rotation = new Vector3(n.shapeRot[0], n.shapeRot[1], n.shapeRot[2]);
                if (n.shapePos != null && n.shapePos.Length >= 3) sh.position = new Vector3(n.shapePos[0], n.shapePos[1], n.shapePos[2]);
            }

            if (n.colOverLife != null && (n.colOverLife.ckeys?.Length > 0 || n.colOverLife.akeys?.Length > 0))
            {
                var col = ps.colorOverLifetime;
                col.enabled = true;
                Gradient g = BuildGrad(n.colOverLife);
                colGrads[ni] = g;
                col.color = new ParticleSystem.MinMaxGradient(g);
                if (g.Evaluate(0f).a < 0.15f) hasOrigFadeIn[ni] = true;
                if (g.Evaluate(1f).a < 0.15f) hasOrigFadeOut[ni] = true;
            }
            if (n.sizeOverLife != null && ((n.sizeOverLife.keys != null && n.sizeOverLife.keys.Length > 0) || n.sizeOverLife.mode == 3 || n.sizeOverLifeSeparateAxes))
            {
                var sz = ps.sizeOverLifetime;
                sz.enabled = true;
                if (n.sizeOverLifeSeparateAxes)
                {
                    sz.separateAxes = true;
                    sz.x = ToCurve(n.sizeOverLife, 1f);
                    sz.y = ToCurve(n.sizeOverLifeY, 1f);
                    sz.z = ToCurve(n.sizeOverLifeZ, 1f);
                    sizeCurveX[ni] = BuildEvalCurve(n.sizeOverLife);
                    sizeCurveY[ni] = BuildEvalCurve(n.sizeOverLifeY);
                }
                else
                {
                    sz.size = ToCurve(n.sizeOverLife, 1f);
                    sizeCurveX[ni] = BuildEvalCurve(n.sizeOverLife);
                    sizeCurveY[ni] = sizeCurveX[ni];
                }
                if (sizeCurveX[ni] != null)
                {
                    float s0 = Mathf.Abs(sizeCurveX[ni].Evaluate(0f));
                    float s1 = Mathf.Abs(sizeCurveX[ni].Evaluate(1f));
                    float sMid = Mathf.Max(0.1f, Mathf.Abs(sizeCurveX[ni].Evaluate(0.5f)));
                    if (s0 < 0.15f * sMid) hasOrigFadeIn[ni] = true;
                    if (s1 < 0.15f * sMid) hasOrigFadeOut[ni] = true;
                }
            }
            if (n.velEnabled)
            {
                var vel = ps.velocityOverLifetime;
                vel.enabled = true;
                vel.space = n.velInWorldSpace ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
                vel.x = n.velXCurve != null ? ToCurve(n.velXCurve, n.velX) : new ParticleSystem.MinMaxCurve(n.velX);
                vel.y = n.velYCurve != null ? ToCurve(n.velYCurve, n.velY) : new ParticleSystem.MinMaxCurve(n.velY);
                vel.z = n.velZCurve != null ? ToCurve(n.velZCurve, n.velZ) : new ParticleSystem.MinMaxCurve(n.velZ);
                if (n.velOrbitalX != null) vel.orbitalX = ToCurve(n.velOrbitalX, 0f);
                if (n.velOrbitalY != null) vel.orbitalY = ToCurve(n.velOrbitalY, 0f);
                if (n.velOrbitalZ != null) vel.orbitalZ = ToCurve(n.velOrbitalZ, 0f);
                if (n.velOrbitalOffsetX != null) vel.orbitalOffsetX = ToCurve(n.velOrbitalOffsetX, 0f);
                if (n.velOrbitalOffsetY != null) vel.orbitalOffsetY = ToCurve(n.velOrbitalOffsetY, 0f);
                if (n.velOrbitalOffsetZ != null) vel.orbitalOffsetZ = ToCurve(n.velOrbitalOffsetZ, 0f);
                if (n.velRadial != null) vel.radial = ToCurve(n.velRadial, 0f);
                if (n.velSpeedModifier != null) vel.speedModifier = ToCurve(n.velSpeedModifier, 1f);
            }
            if (n.limitVelEnabled)
            {
                var lim = ps.limitVelocityOverLifetime;
                lim.enabled = true;
                lim.space = n.limitVelInWorld ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
                lim.separateAxes = n.limitVelSeparateAxes;
                lim.dampen = n.limitVelDampen;
                lim.multiplyDragByParticleSize = n.limitVelMulSize;
                lim.multiplyDragByParticleVelocity = n.limitVelMulVel;
                if (n.limitVelSeparateAxes)
                {
                    lim.limitX = ToCurve(n.limitVelX, 1f);
                    lim.limitY = ToCurve(n.limitVelY, 1f);
                    lim.limitZ = ToCurve(n.limitVelZ, 1f);
                }
                else lim.limit = ToCurve(n.limitVel, 1f);
                if (n.limitVelDrag != null) lim.drag = ToCurve(n.limitVelDrag, 0f);
            }
            bool hasRotZ = (n.rotOverLifeCurve != null && (n.rotOverLifeCurve.keys?.Length > 0 || n.rotOverLifeCurve.mode == 3)) || Mathf.Abs(n.rotOverLife) > 1e-4f;
            if (n.rotOverLifeEnabled && (n.rotOverLifeSeparateAxes || hasRotZ))
            {
                var rot = ps.rotationOverLifetime;
                rot.enabled = true;
                if (n.rotOverLifeSeparateAxes)
                {
                    rot.separateAxes = true;
                    rot.x = ToCurve(n.rotOverLifeX, 0f);
                    rot.y = ToCurve(n.rotOverLifeY, 0f);
                    rot.z = n.rotOverLifeCurve != null ? ToCurve(n.rotOverLifeCurve, n.rotOverLife) : new ParticleSystem.MinMaxCurve(n.rotOverLife);
                }
                else rot.z = n.rotOverLifeCurve != null ? ToCurve(n.rotOverLifeCurve, n.rotOverLife) : new ParticleSystem.MinMaxCurve(n.rotOverLife);
            }
            if (n.noiseEnabled)
            {
                var noise = ps.noise;
                noise.enabled = true;
                noise.separateAxes = n.noiseSeparateAxes;
                if (n.noiseSeparateAxes)
                {
                    noise.strengthX = HasCurve(n.noiseStrengthCurve) ? ToCurve(n.noiseStrengthCurve, n.noiseStrength) : new ParticleSystem.MinMaxCurve(n.noiseStrength);
                    noise.strengthY = ToCurve(n.noiseStrengthYCurve, 0f);
                    noise.strengthZ = ToCurve(n.noiseStrengthZCurve, 0f);
                }
                else noise.strength = HasCurve(n.noiseStrengthCurve) ? ToCurve(n.noiseStrengthCurve, n.noiseStrength) : new ParticleSystem.MinMaxCurve(n.noiseStrength);
                noise.frequency = Mathf.Max(0.001f, n.noiseFrequency);
                noise.scrollSpeed = HasCurve(n.noiseScrollSpeedCurve) ? ToCurve(n.noiseScrollSpeedCurve, n.noiseScrollSpeed) : new ParticleSystem.MinMaxCurve(n.noiseScrollSpeed);
                noise.damping = n.noiseDamping;
                noise.octaveCount = Mathf.Clamp(n.noiseOctaves > 0 ? n.noiseOctaves : 1, 1, 4);
                noise.octaveMultiplier = n.noiseOctaveMultiplier;
                noise.octaveScale = Mathf.Max(0.01f, n.noiseOctaveScale);
                noise.quality = (ParticleSystemNoiseQuality)Mathf.Clamp(n.noiseQuality, 0, 2);
                if (HasCurve(n.noisePosAmountCurve) || HasCurve(n.noiseRotAmountCurve) || HasCurve(n.noiseSizeAmountCurve))
                {
                    noise.positionAmount = ToCurve(n.noisePosAmountCurve, 1f);
                    noise.rotationAmount = ToCurve(n.noiseRotAmountCurve, 0f);
                    noise.sizeAmount = ToCurve(n.noiseSizeAmountCurve, 0f);
                }
            }
            if (n.forceEnabled)
            {
                var force = ps.forceOverLifetime;
                force.enabled = true;
                force.space = n.forceInWorldSpace ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
                force.randomized = n.forceRandomized;
                force.x = HasCurve(n.forceXCurve) ? ToCurve(n.forceXCurve, n.forceX) : new ParticleSystem.MinMaxCurve(n.forceX);
                force.y = HasCurve(n.forceYCurve) ? ToCurve(n.forceYCurve, n.forceY) : new ParticleSystem.MinMaxCurve(n.forceY);
                force.z = HasCurve(n.forceZCurve) ? ToCurve(n.forceZCurve, n.forceZ) : new ParticleSystem.MinMaxCurve(n.forceZ);
            }
            if (n.rotBySpeedEnabled)
            {
                var rbs = ps.rotationBySpeed;
                rbs.enabled = true;
                rbs.separateAxes = n.rotBySpeedSeparateAxes;
                if (n.rotBySpeedRange != null && n.rotBySpeedRange.Length >= 2)
                    rbs.range = new Vector2(n.rotBySpeedRange[0], n.rotBySpeedRange[1]);
                if (n.rotBySpeedSeparateAxes)
                {
                    rbs.x = ToCurve(n.rotBySpeedX, 0f);
                    rbs.y = ToCurve(n.rotBySpeedY, 0f);
                    rbs.z = ToCurve(n.rotBySpeedCurve, 0f);
                }
                else rbs.z = ToCurve(n.rotBySpeedCurve, 0f);
            }

            if (n.uvTiles != null && n.uvTiles.Length >= 2)
            {
                var ts = ps.textureSheetAnimation;
                ts.enabled = true;
                ts.numTilesX = Mathf.Max(1, Mathf.RoundToInt(n.uvTiles[0]));
                ts.numTilesY = Mathf.Max(1, Mathf.RoundToInt(n.uvTiles[1]));
                ts.cycleCount = Mathf.Max(1, Mathf.RoundToInt(n.uvTiles.Length > 2 ? n.uvTiles[2] : 1f));
                ts.animation = (n.uvAnim == 1) ? ParticleSystemAnimationType.SingleRow : ParticleSystemAnimationType.WholeSheet;
                ts.rowMode = (n.uvRowMode == 1) ? ParticleSystemAnimationRowMode.Random : ParticleSystemAnimationRowMode.Custom;
                if (n.uvFrameMode == 3)
                {
                    float fLo = Mathf.Min(n.uvFrameMin, n.uvFrameScalar);
                    float fHi = Mathf.Max(n.uvFrameMin, n.uvFrameScalar);
                    ts.frameOverTime = new ParticleSystem.MinMaxCurve(fLo, fHi);
                }
                else if (n.uvFrameMode == 1 && n.uvFrameKeys != null && n.uvFrameKeys.Length > 0)
                {
                    var kfs = new Keyframe[n.uvFrameKeys.Length];
                    for (int i = 0; i < n.uvFrameKeys.Length; i++)
                        kfs[i] = new Keyframe(n.uvFrameKeys[i].t, n.uvFrameKeys[i].v, n.uvFrameKeys[i].@in, n.uvFrameKeys[i].@out);
                    uvCurves[ni] = new AnimationCurve(kfs);
                    ts.frameOverTime = new ParticleSystem.MinMaxCurve(Mathf.Approximately(n.uvFrameScalar, 0f) ? 1f : n.uvFrameScalar, uvCurves[ni]);
                }
                else if (n.uvFrameMode == 0)
                {
                    ts.frameOverTime = new ParticleSystem.MinMaxCurve(n.uvFrameScalar);
                }
                else
                {
                    ts.frameOverTime = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 0f, 1f, 0.9999f));
                }
            }

            // Effective shader tint = 2.0 * _TintColor (matching SoulTideParticleAlpha/Add)
            Color tcol = ToCol(n.tint);
            if (tcol.a <= 0.001f && tcol.r <= 0.001f && tcol.g <= 0.001f && tcol.b <= 0.001f)
                tcol = new Color(0.5f, 0.5f, 0.5f, 0.5f);
            else if (tcol.a <= 0.001f) tcol.a = 0.5f;
            float mul = n.tintMultiplier > 0.001f ? n.tintMultiplier : 1f;
            effTint[ni] = new Color(tcol.r * mul * 2f, tcol.g * mul * 2f, tcol.b * mul * 2f, tcol.a * 2f);

            meshSize[ni] = Vector2.one;
            if (n.renderMode == 4 && !string.IsNullOrEmpty(n.meshName) && meshBounds.TryGetValue(n.meshName, out Vector3 mb))
            {
                meshSize[ni] = new Vector2(Mathf.Max(0.01f, mb.x), Mathf.Max(0.01f, mb.y));
            }

            float su = (n.uvScroll != null && n.uvScroll.Length >= 2) ? n.uvScroll[0] : 0f;
            float sv = (n.uvScroll != null && n.uvScroll.Length >= 2) ? n.uvScroll[1] : 0f;
            isUvScroll[ni] = (n.maxParticles == 1 && (Mathf.Abs(su) > 1e-5f || Mathf.Abs(sv) > 1e-5f));

            gos[ni] = go;
            pss[ni] = ps;
            if (!n.isSubEmitterChild) rootSystems.Add(ps);
        }

        // Wire SubEmitters after all ParticleSystems are constructed
        for (int ni = 0; ni < N; ni++)
        {
            var n = clip.nodes[ni];
            if (n == null || n.subEmitters == null || n.subEmitters.Length == 0) continue;
            ParticleSystem parentPs = pss[ni];
            if (parentPs == null) continue;
            var sub = parentPs.subEmitters;
            bool addedAny = false;
            for (int si = 0; si < n.subEmitters.Length; si++)
            {
                var se = n.subEmitters[si];
                if (se.targetIdx < 0 || se.targetIdx >= N) continue;
                ParticleSystem childPs = pss[se.targetIdx];
                GameObject childGo = gos[se.targetIdx];
                if (childPs == null || childGo == null || childPs == parentPs) continue;
                childGo.transform.SetParent(parentPs.transform, true);
                sub.AddSubEmitter(
                    childPs,
                    (ParticleSystemSubEmitterType)Mathf.Clamp(se.type, 0, 4),
                    (ParticleSystemSubEmitterProperties)se.properties,
                    Mathf.Clamp01(se.emitProbability)
                );
                addedAny = true;
            }
            if (addedAny) sub.enabled = true;
        }

        // Warmup (allow up to 65s for long-lived snow/cloud steady-state convergence)
        float warmDt = 1f / 30f;
        float warmSec = Mathf.Clamp(clip.warmup, 0f, 65f);
        int warmSteps = Mathf.RoundToInt(warmSec / warmDt);
        if (warmSteps > 0)
        {
            for (int w = 0; w < warmSteps; w++)
                foreach (var ps in rootSystems) ps.Simulate(warmDt, true, w == 0, false);
        }
        else
        {
            foreach (var ps in rootSystems) ps.Simulate(0f, true, true, false);
        }

        // Simulate and record tracks (allow up to 120s so 30s-40s long-lived particles complete cleanly)
        bool isIdleClip = string.IsNullOrEmpty(clip.clip) || clip.clip.StartsWith("idle", StringComparison.OrdinalIgnoreCase);
        float effDur = isIdleClip
            ? Mathf.Clamp(Mathf.Max(recordDur, 4.0f + 20.0f + maxNodeLt + 3.0f), 32.0f, 120.0f)
            : Mathf.Clamp(clip.duration > 0.1f ? clip.duration : 4.0f, 0.5f, 60.0f);
        float dt = 1f / sampleFps;
        int totalSteps = Mathf.RoundToInt(effDur * sampleFps);
        var activeTracks = new Dictionary<long, TrackData>();
        var allTracks = new List<TrackData>();
        var uvQuads = new List<string>();
        var uvCaptured = new bool[N];
        var buf = new ParticleSystem.Particle[2048];

        for (int step = 0; step <= totalSteps; step++)
        {
            if (step > 0)
                foreach (var ps in rootSystems) ps.Simulate(dt, true, false, false);
            float t = step * dt;

            for (int ni = 0; ni < N; ni++)
            {
                var n = clip.nodes[ni];
                var ps = pss[ni];
                var go = gos[ni];
                int cnt = ps.GetParticles(buf);
                Vector3 ls = go.transform.lossyScale;
                float lsx = Mathf.Abs(ls.x);
                float lsy = Mathf.Abs(ls.y);
                bool isLocal = (n.simulationSpace != 1);

                if (isUvScroll[ni])
                {
                    if (!uvCaptured[ni] && cnt > 0)
                    {
                        var p = buf[0];
                        Vector3 wp = isLocal ? go.transform.TransformPoint(p.position) : p.position;
                        Vector3 sz = p.GetCurrentSize3D(ps);
                        float sw = sz.x * lsx * meshSize[ni].x;
                        float sh = sz.y * lsy * meshSize[ni].y;
                        float qrot;
                        if (n.renderAlignment == 2)
                        {
                            Quaternion q = go.transform.rotation * Quaternion.Euler(0f, 0f, -p.rotation);
                            Vector3 right = q * Vector3.right;
                            qrot = Mathf.Atan2(right.y, right.x) * Mathf.Rad2Deg;
                        }
                        else
                        {
                            qrot = -p.rotation;
                        }
                        if (n.pivot != null && n.pivot.Length >= 2 && (Mathf.Abs(n.pivot[0]) > 1e-4f || Mathf.Abs(n.pivot[1]) > 1e-4f))
                        {
                            float rad = qrot * Mathf.Deg2Rad;
                            float ox = n.pivot[0] * sw;
                            float oy = n.pivot[1] * sh;
                            wp.x += ox * Mathf.Cos(rad) - oy * Mathf.Sin(rad);
                            wp.y += ox * Mathf.Sin(rad) + oy * Mathf.Cos(rad);
                        }
                        Color32 pc = p.GetCurrentColor(ps);
                        Color tc = effTint[ni];
                        float cr = Mathf.Clamp01((pc.r / 255f) * tc.r);
                        float cg = Mathf.Clamp01((pc.g / 255f) * tc.g);
                        float cb = Mathf.Clamp01((pc.b / 255f) * tc.b);
                        float ca = Mathf.Clamp01((pc.a / 255f) * tc.a);
                        float su = (n.uvScroll != null && n.uvScroll.Length >= 2) ? n.uvScroll[0] : 0f;
                        float sv = (n.uvScroll != null && n.uvScroll.Length >= 2) ? n.uvScroll[1] : 0f;
                        float tsx = (n.texScale != null && n.texScale.Length >= 2) ? n.texScale[0] : 1f;
                        float tsy = (n.texScale != null && n.texScale.Length >= 2) ? n.texScale[1] : 1f;
                        float tox = (n.texOffset != null && n.texOffset.Length >= 2) ? n.texOffset[0] : 0f;
                        float toy = (n.texOffset != null && n.texOffset.Length >= 2) ? n.texOffset[1] : 0f;
                        uvQuads.Add(string.Format(Inv,
                            "{{\"node_idx\":{0},\"name\":\"{1}\",\"tex\":\"{2}\",\"additive\":{3},\"sort_order\":{4},\"eff_sort_order\":{5},\"dfs_seq\":{6},\"x\":{7:F3},\"y\":{8:F3},\"w\":{9:F3},\"h\":{10:F3},\"rot\":{11:F3},\"r\":{12:F4},\"g\":{13:F4},\"b\":{14:F4},\"a\":{15:F4},\"uv_u\":{16:F6},\"uv_v\":{17:F6},\"tex_scale\":[{18:F4},{19:F4}],\"tex_offset\":[{20:F4},{21:F4}]",
                            ni, Esc(n.name), Esc(n.texName), n.isAdditive ? "true" : "false", n.sortOrder, n.effSortOrder, n.dfsSeq,
                            wp.x, wp.y, sw, sh, qrot, cr, cg, cb, ca, su, sv, tsx, tsy, tox, toy
                        ) + "}");
                        uvCaptured[ni] = true;
                    }
                    continue;
                }

                var seenKeys = new HashSet<long>();
                for (int pi = 0; pi < cnt; pi++)
                {
                    var p = buf[pi];
                    long key = ((long)ni << 32) | (long)p.randomSeed;
                    seenKeys.Add(key);

                    Vector3 wp = isLocal ? go.transform.TransformPoint(p.position) : p.position;
                    Vector3 wv = isLocal ? go.transform.TransformVector(p.totalVelocity) : p.totalVelocity;
                    Vector3 sz = p.GetCurrentSize3D(ps);
                    float sw = sz.x * lsx * meshSize[ni].x;
                    float sh = sz.y * lsy * meshSize[ni].y;
                    float rotDeg;

                    if (n.renderMode == 1)
                    {
                        // Stretched billboard
                        float speed2d = new Vector2(wv.x, wv.y).magnitude;
                        float angRad = (speed2d > 1e-4f) ? Mathf.Atan2(wv.y, wv.x) : 0f;
                        // Unity stretched billboard stretches texture along velocity; length = size * abs(lengthScale) + speed * velocityScale
                        float len = sw * Mathf.Abs(n.lengthScale) + speed2d * Mathf.Abs(n.velocityScale);
                        if (n.lengthScale < 0f) angRad += Mathf.PI;
                        sw = Mathf.Max(1f, len);
                        sh = sz.x * lsx;
                        rotDeg = angRad * Mathf.Rad2Deg;
                    }
                    else if (n.renderMode == 4)
                    {
                        // Mesh particle (e.g. caihong)
                        Quaternion q = go.transform.rotation * Quaternion.Euler(p.rotation3D);
                        Vector3 right = q * Vector3.right;
                        rotDeg = Mathf.Atan2(right.y, right.x) * Mathf.Rad2Deg;
                    }
                    else if (n.renderAlignment == 2)
                    {
                        // Local-aligned billboard inherits emitter world rotation (e.g. tilted rain, directional sunbeams)
                        Quaternion q = go.transform.rotation * Quaternion.Euler(0f, 0f, -p.rotation);
                        Vector3 right = q * Vector3.right;
                        rotDeg = Mathf.Atan2(right.y, right.x) * Mathf.Rad2Deg;
                        if (ls.x < 0f) sw = -sw;
                        if (ls.y < 0f) sh = -sh;
                    }
                    else
                    {
                        // Standard screen/view billboard: Unity p.rotation is clockwise degrees -> Spine is CCW
                        rotDeg = -p.rotation;
                    }

                    // Apply ParticleSystemRenderer.pivot offset in particle local space
                    if (n.pivot != null && n.pivot.Length >= 2 && (Mathf.Abs(n.pivot[0]) > 1e-4f || Mathf.Abs(n.pivot[1]) > 1e-4f))
                    {
                        float rad = rotDeg * Mathf.Deg2Rad;
                        float ox = n.pivot[0] * sw;
                        float oy = n.pivot[1] * sh;
                        wp.x += ox * Mathf.Cos(rad) - oy * Mathf.Sin(rad);
                        wp.y += ox * Mathf.Sin(rad) + oy * Mathf.Cos(rad);
                    }

                    // Apply ParticleSystemRenderer.flip probability deterministically per particle seed
                    if (n.flip != null && n.flip.Length >= 2)
                    {
                        if (n.flip[0] > 1e-4f && SeedHash01(p.randomSeed ^ 0x9E3779B9u) < n.flip[0]) sw = -sw;
                        if (n.flip[1] > 1e-4f && SeedHash01(p.randomSeed ^ 0x85EBCA6Bu) < n.flip[1]) sh = -sh;
                    }

                    Color32 pc = p.GetCurrentColor(ps);
                    Color tc = effTint[ni];
                    float cr = Mathf.Clamp01((pc.r / 255f) * tc.r);
                    float cg = Mathf.Clamp01((pc.g / 255f) * tc.g);
                    float cb = Mathf.Clamp01((pc.b / 255f) * tc.b);
                    float ca = Mathf.Clamp01((pc.a / 255f) * tc.a);
                    float age01 = Mathf.Clamp01(1f - p.remainingLifetime / Mathf.Max(1e-5f, p.startLifetime));

                    int tile = 0;
                    if (n.uvTiles != null && n.uvTiles.Length >= 2)
                    {
                        int tx = Mathf.Max(1, Mathf.RoundToInt(n.uvTiles[0]));
                        int ty = Mathf.Max(1, Mathf.RoundToInt(n.uvTiles[1]));
                        int totalTiles = tx * ty;
                        float cycles = Mathf.Max(1f, n.uvTiles.Length > 2 ? n.uvTiles[2] : 1f);
                        float tCycle = (age01 >= 0.9999f) ? 0.9999f : ((age01 * cycles) % 1f);
                        float fVal;
                        if (n.uvFrameMode == 3)
                        {
                            float fLo = Mathf.Min(n.uvFrameMin, n.uvFrameScalar);
                            float fHi = Mathf.Max(n.uvFrameMin, n.uvFrameScalar);
                            fVal = Mathf.Lerp(fLo, fHi, SeedHash01(p.randomSeed ^ 0xC2B2AE35u));
                        }
                        else if (n.uvFrameMode == 0)
                        {
                            fVal = n.uvFrameScalar;
                        }
                        else if (n.uvFrameMode == 1 && uvCurves[ni] != null)
                        {
                            float sc = Mathf.Approximately(n.uvFrameScalar, 0f) ? 1f : n.uvFrameScalar;
                            fVal = uvCurves[ni].Evaluate(tCycle) * sc;
                        }
                        else
                        {
                            fVal = tCycle;
                        }
                        fVal = Mathf.Clamp01(fVal);
                        if (n.uvAnim == 1)
                        {
                            int row = (n.uvRowMode == 1) ? (int)(p.randomSeed % (uint)ty) : 0;
                            int col = Mathf.Clamp(Mathf.FloorToInt(fVal * tx), 0, tx - 1);
                            tile = row * tx + col;
                        }
                        else
                        {
                            tile = Mathf.Clamp(Mathf.FloorToInt(fVal * totalTiles), 0, totalTiles - 1);
                        }
                    }

                    // BUG #1 FIX: When ringBufferMode != 0, remainingLifetime wraps upwards on the SAME continuous particle!
                    TrackData tr;
                    bool isNewTrack = !activeTracks.TryGetValue(key, out tr)
                        || (n.ringBufferMode == 0 && p.remainingLifetime > tr.lastRem + 0.05f);
                    if (isNewTrack)
                    {
                        Color sc0 = new Color(p.startColor.r / 255f, p.startColor.g / 255f, p.startColor.b / 255f, p.startColor.a / 255f);
                        float exactBirth = t - (p.startLifetime - p.remainingLifetime);
                        tr = new TrackData
                        {
                            nodeIdx = ni,
                            seed = p.randomSeed,
                            birthT = exactBirth,
                            life = p.startLifetime,
                            lastRem = p.remainingLifetime,
                            startCol = sc0,
                            alive = true,
                            bornInWindow = (step > 0)
                        };
                        activeTracks[key] = tr;
                        allTracks.Add(tr);

                        // Analytic birth endpoint extrapolation so particles start cleanly at exact t = birthT!
                        float ageAtFirst = t - exactBirth;
                        if (step > 0 && n.ringBufferMode == 0 && ageAtFirst > 0.004f && ageAtFirst < dt * 1.25f)
                        {
                            Color gc0 = colGrads[ni] != null ? colGrads[ni].Evaluate(0f) : Color.white;
                            float br = Mathf.Clamp01(sc0.r * gc0.r * tc.r);
                            float bg = Mathf.Clamp01(sc0.g * gc0.g * tc.g);
                            float bb = Mathf.Clamp01(sc0.b * gc0.b * tc.b);
                            float ba = Mathf.Clamp01(sc0.a * gc0.a * tc.a);
                            float bsw = sw, bsh = sh;
                            if (sizeCurveX[ni] != null)
                            {
                                float cNow = sizeCurveX[ni].Evaluate(age01);
                                float c0 = sizeCurveX[ni].Evaluate(0f);
                                if (Mathf.Abs(cNow) > 1e-4f) bsw = sw * Mathf.Clamp(c0 / cNow, 0f, 2f);
                            }
                            if (sizeCurveY[ni] != null)
                            {
                                float cNow = sizeCurveY[ni].Evaluate(age01);
                                float c0 = sizeCurveY[ni].Evaluate(0f);
                                if (Mathf.Abs(cNow) > 1e-4f) bsh = sh * Mathf.Clamp(c0 / cNow, 0f, 2f);
                            }
                            float angVelDeg = (n.renderMode == 1 || n.renderMode == 4) ? 0f : -p.angularVelocity;
                            tr.samples.Add(new SamplePt
                            {
                                t = Mathf.Max(0f, exactBirth),
                                x = wp.x - wv.x * ageAtFirst,
                                y = wp.y - wv.y * ageAtFirst,
                                sx = bsw,
                                sy = bsh,
                                rot = rotDeg - angVelDeg * ageAtFirst,
                                r = br,
                                g = bg,
                                b = bb,
                                a = ba,
                                tile = tile
                            });
                        }
                    }

                    tr.lastRem = p.remainingLifetime;
                    tr.lastVx = wv.x;
                    tr.lastVy = wv.y;
                    tr.lastAngVel = (n.renderMode == 1 || n.renderMode == 4) ? 0f : -p.angularVelocity;
                    tr.lastAge01 = age01;
                    tr.samples.Add(new SamplePt
                    {
                        t = t,
                        x = wp.x,
                        y = wp.y,
                        sx = sw,
                        sy = sh,
                        rot = rotDeg,
                        r = cr,
                        g = cg,
                        b = cb,
                        a = ca,
                        tile = tile
                    });
                }

                // Mark tracks no longer alive + append analytic death endpoint at exact t = birthT + life!
                var toRemove = new List<long>();
                foreach (var kv in activeTracks)
                {
                    if ((int)(kv.Key >> 32) == ni && !seenKeys.Contains(kv.Key))
                    {
                        var tr = kv.Value;
                        tr.alive = false;
                        if (n.ringBufferMode == 0 && tr.samples.Count >= 1)
                        {
                            var last = tr.samples[tr.samples.Count - 1];
                            float tDeath = tr.birthT + tr.life;
                            float rem = tDeath - last.t;
                            if (rem > 0.004f && rem < dt * 1.25f)
                            {
                                Color tc = effTint[ni];
                                Color gc1 = colGrads[ni] != null ? colGrads[ni].Evaluate(1f) : Color.white;
                                float er = Mathf.Clamp01(tr.startCol.r * gc1.r * tc.r);
                                float eg = Mathf.Clamp01(tr.startCol.g * gc1.g * tc.g);
                                float eb = Mathf.Clamp01(tr.startCol.b * gc1.b * tc.b);
                                float ea = Mathf.Clamp01(tr.startCol.a * gc1.a * tc.a);
                                float esw = last.sx, esh = last.sy;
                                if (sizeCurveX[ni] != null)
                                {
                                    float cNow = sizeCurveX[ni].Evaluate(tr.lastAge01);
                                    float c1 = sizeCurveX[ni].Evaluate(1f);
                                    if (Mathf.Abs(cNow) > 1e-4f) esw = last.sx * Mathf.Clamp(c1 / cNow, 0f, 2f);
                                }
                                if (sizeCurveY[ni] != null)
                                {
                                    float cNow = sizeCurveY[ni].Evaluate(tr.lastAge01);
                                    float c1 = sizeCurveY[ni].Evaluate(1f);
                                    if (Mathf.Abs(cNow) > 1e-4f) esh = last.sy * Mathf.Clamp(c1 / cNow, 0f, 2f);
                                }
                                tr.samples.Add(new SamplePt
                                {
                                    t = tDeath,
                                    x = last.x + tr.lastVx * rem,
                                    y = last.y + tr.lastVy * rem,
                                    sx = esw,
                                    sy = esh,
                                    rot = last.rot + tr.lastAngVel * rem,
                                    r = er,
                                    g = eg,
                                    b = eb,
                                    a = ea,
                                    tile = last.tile
                                });
                            }
                        }
                        toRemove.Add(kv.Key);
                    }
                }
                foreach (var k in toRemove) activeTracks.Remove(k);
            }
        }

        // Write clip JSON
        sb.Append("    {\n");
        sb.AppendFormat(Inv, "      \"clip\": \"{0}\", \"layer\": \"{1}\", \"record_dur\": {2:F4},\n", Esc(clip.clip), Esc(clip.layer), effDur);
        sb.Append("      \"nodes\": [\n");
        for (int ni = 0; ni < N; ni++)
        {
            var n = clip.nodes[ni];
            if (ni > 0) sb.Append(",\n");
            int tx = (n.uvTiles != null && n.uvTiles.Length >= 2) ? Mathf.Max(1, Mathf.RoundToInt(n.uvTiles[0])) : 1;
            int ty = (n.uvTiles != null && n.uvTiles.Length >= 2) ? Mathf.Max(1, Mathf.RoundToInt(n.uvTiles[1])) : 1;
            float rb0 = (n.ringBufferLoopRange != null && n.ringBufferLoopRange.Length >= 2) ? n.ringBufferLoopRange[0] : 0f;
            float rb1 = (n.ringBufferLoopRange != null && n.ringBufferLoopRange.Length >= 2) ? n.ringBufferLoopRange[1] : 1f;
            float burstRep = (n.bursts != null && n.bursts.Length > 0) ? n.bursts[0].repeatInterval : 0f;
            int burstCnt = (n.bursts != null) ? n.bursts.Length : 0;
            sb.AppendFormat(Inv,
                "        {{\"idx\":{0},\"name\":\"{1}\",\"tex\":\"{2}\",\"additive\":{3},\"sort_order\":{4},\"eff_sort_order\":{5},\"dfs_seq\":{6},\"render_mode\":{7},\"tiles_x\":{8},\"tiles_y\":{9},\"is_uv_scroll\":{10},\"ring_buffer_mode\":{11},\"ring_buffer_loop_range\":[{12:F4},{13:F4}],\"max_particles\":{14},\"duration\":{15:F4},\"sim_speed\":{16:F4},\"has_orig_fade_in\":{17},\"has_orig_fade_out\":{18},\"burst_count\":{19},\"burst_interval\":{20:F4}",
                ni, Esc(n.name), Esc(n.texName), n.isAdditive ? "true" : "false", n.sortOrder, n.effSortOrder, n.dfsSeq, n.renderMode, tx, ty,
                isUvScroll[ni] ? "true" : "false", n.ringBufferMode, rb0, rb1, n.maxParticles,
                n.duration, n.simulationSpeed > 0.001f ? n.simulationSpeed : 1f,
                hasOrigFadeIn[ni] ? "true" : "false", hasOrigFadeOut[ni] ? "true" : "false",
                burstCnt, burstRep
            );
            sb.Append("}");
        }
        sb.Append("\n      ],\n");
        sb.Append("      \"uv_quads\": [\n");
        for (int i = 0; i < uvQuads.Count; i++)
        {
            if (i > 0) sb.Append(",\n");
            sb.Append("        ").Append(uvQuads[i]);
        }
        sb.Append("\n      ],\n");
        sb.Append("      \"tracks\": [\n");
        int written = 0;
        for (int ti = 0; ti < allTracks.Count; ti++)
        {
            var tr = allTracks[ti];
            if (tr.samples.Count < 2) continue;
            if (written > 0) sb.Append(",\n");
            written++;
            sb.AppendFormat(Inv, "        {{\"node\":{0},\"seed\":{1},\"birth\":{2:F3},\"life\":{3:F3},\"born_in_window\":{4},\"dead_in_window\":{5},\"pts\":[",
                tr.nodeIdx, tr.seed, tr.birthT, tr.life, tr.bornInWindow ? "true" : "false", (!tr.alive) ? "true" : "false");
            for (int si = 0; si < tr.samples.Count; si++)
            {
                var p = tr.samples[si];
                if (si > 0) sb.Append(",");
                sb.AppendFormat(Inv, "[{0:F3},{1:F2},{2:F2},{3:F2},{4:F2},{5:F2},{6:F3},{7:F3},{8:F3},{9:F3},{10}]",
                    p.t, p.x, p.y, p.sx, p.sy, p.rot, p.r, p.g, p.b, p.a, p.tile);
            }
            sb.Append("]}");
        }
        sb.Append("\n      ]\n");
        sb.Append("    }");

        UnityEngine.Object.DestroyImmediate(root);
    }

    private static AnimationCurve BuildEvalCurve(SoulTideBatchFxRecorder.MinMaxCurveDto dto)
    {
        if (dto == null || dto.mode != 1 || dto.keys == null || dto.keys.Length == 0) return null;
        float sc = Mathf.Approximately(dto.scalar, 0f) ? 1f : dto.scalar;
        var kfs = new Keyframe[dto.keys.Length];
        for (int i = 0; i < dto.keys.Length; i++)
            kfs[i] = new Keyframe(dto.keys[i].t, dto.keys[i].v * sc, dto.keys[i].@in * sc, dto.keys[i].@out * sc);
        return new AnimationCurve(kfs);
    }

    private static bool HasCurve(SoulTideBatchFxRecorder.MinMaxCurveDto c)
    {
        if (c == null) return false;
        if (Mathf.Abs(c.scalar) > 1e-4f) return true;
        if (c.mode == 3 && Mathf.Abs(c.minScalar) > 1e-4f) return true;
        return c.keys != null && c.keys.Length > 0;
    }

    private static Gradient BuildGrad(SoulTideBatchFxRecorder.GradientDto dto)
    {
        Gradient g = new Gradient();
        int nck = dto.ckeys != null && dto.ckeys.Length > 0 ? dto.ckeys.Length : 1;
        var ck = new GradientColorKey[nck];
        if (dto.ckeys != null && dto.ckeys.Length > 0)
            for (int i = 0; i < dto.ckeys.Length; i++)
                ck[i] = new GradientColorKey(new Color(dto.ckeys[i].r, dto.ckeys[i].g, dto.ckeys[i].b, 1f), Mathf.Clamp01(dto.ckeys[i].t));
        else ck[0] = new GradientColorKey(Color.white, 0f);

        int nak = dto.akeys != null && dto.akeys.Length > 0 ? dto.akeys.Length : 1;
        var ak = new GradientAlphaKey[nak];
        if (dto.akeys != null && dto.akeys.Length > 0)
            for (int i = 0; i < dto.akeys.Length; i++)
                ak[i] = new GradientAlphaKey(Mathf.Clamp01(dto.akeys[i].a), Mathf.Clamp01(dto.akeys[i].t));
        else ak[0] = new GradientAlphaKey(1f, 0f);
        g.SetKeys(ck, ak);
        return g;
    }

    private static ParticleSystem.MinMaxCurve ToCurve(SoulTideBatchFxRecorder.MinMaxCurveDto dto, float fallback, float mult = 1f)
    {
        if (dto == null) return new ParticleSystem.MinMaxCurve(fallback * mult);
        if (dto.mode == 3)
        {
            float lo = Mathf.Min(dto.minScalar, dto.scalar) * mult;
            float hi = Mathf.Max(dto.minScalar, dto.scalar) * mult;
            return new ParticleSystem.MinMaxCurve(lo, hi);
        }
        if (dto.mode == 1 && dto.keys != null && dto.keys.Length > 0)
        {
            var kfs = new Keyframe[dto.keys.Length];
            for (int i = 0; i < dto.keys.Length; i++)
                kfs[i] = new Keyframe(dto.keys[i].t, dto.keys[i].v, dto.keys[i].@in, dto.keys[i].@out);
            float sc = (Mathf.Approximately(dto.scalar, 0f) ? 1f : dto.scalar) * mult;
            return new ParticleSystem.MinMaxCurve(sc, new AnimationCurve(kfs));
        }
        if (dto.mode == 2 && dto.keys != null && dto.keys.Length > 0)
        {
            var kmax = new Keyframe[dto.keys.Length];
            for (int i = 0; i < dto.keys.Length; i++)
                kmax[i] = new Keyframe(dto.keys[i].t, dto.keys[i].v, dto.keys[i].@in, dto.keys[i].@out);
            Keyframe[] kmin;
            if (dto.minKeys != null && dto.minKeys.Length > 0)
            {
                kmin = new Keyframe[dto.minKeys.Length];
                for (int i = 0; i < dto.minKeys.Length; i++)
                    kmin[i] = new Keyframe(dto.minKeys[i].t, dto.minKeys[i].v, dto.minKeys[i].@in, dto.minKeys[i].@out);
            }
            else kmin = new Keyframe[] { new Keyframe(0f, 0f), new Keyframe(1f, 0f) };
            float sc = (Mathf.Approximately(dto.scalar, 0f) ? 1f : dto.scalar) * mult;
            return new ParticleSystem.MinMaxCurve(sc, new AnimationCurve(kmin), new AnimationCurve(kmax));
        }
        return new ParticleSystem.MinMaxCurve(dto.scalar * mult);
    }

    private static Color ToCol(SoulTideBatchFxRecorder.ColorDto c)
    {
        return c == null ? Color.white : new Color(c.r, c.g, c.b, c.a);
    }

    private static float SeedHash01(uint s)
    {
        s ^= s >> 16;
        s *= 0x7FEB352Du;
        s ^= s >> 15;
        s *= 0x846CA68Bu;
        s ^= s >> 16;
        return (s & 0x00FFFFFFu) / 16777216.0f;
    }

    private static string Esc(string s)
    {
        return string.IsNullOrEmpty(s) ? "" : s.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }
}
#endif
