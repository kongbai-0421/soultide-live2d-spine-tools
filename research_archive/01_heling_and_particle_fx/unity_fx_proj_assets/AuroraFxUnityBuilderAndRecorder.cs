#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Reconstructs Aurora_S4 ParticleSystems from fx_spec.json in real Unity 2021.3.34f1
/// and captures two-pass (Normal Alpha + Additive Glow) transparent PNG frame sequences.
/// </summary>
public static class AuroraFxUnityBuilderAndRecorder
{
    [Serializable]
    public class CurveKeyDto { public float t, v; public float @in, @out; }
    [Serializable]
    public class MinMaxCurveDto { public int mode; public float scalar, minScalar; public CurveKeyDto[] keys; }
    [Serializable]
    public class ColorDto { public float r, g, b, a; }
    [Serializable]
    public class ColorKeyDto { public float t, r, g, b; }
    [Serializable]
    public class AlphaKeyDto { public float t, a; }
    [Serializable]
    public class GradientDto { public int mode; public ColorKeyDto[] ckeys; public AlphaKeyDto[] akeys; }
    [Serializable]
    public class BurstDto { public float time, count, minCount; public int mode; }

    [Serializable]
    public class FxNodeDto
    {
        public string name;
        public float[] world_pos;
        public float[] world_scale;
        public float[] world_rot;
        public float duration;
        public float startDelay;
        public bool looping;
        public int scalingMode;
        public MinMaxCurveDto lifetime;
        public MinMaxCurveDto speed;
        public MinMaxCurveDto size;
        public MinMaxCurveDto rotation;
        public ColorDto startColor;
        public ColorDto startColorMin;
        public int startColorMode;
        public int maxParticles;
        public float rate;
        public BurstDto[] bursts;
        public bool shapeEnabled;
        public int shapeType;
        public float shapeRadius;
        public float[] shapeBox;
        public float[] shapeRot;
        public float[] shapePos;
        public GradientDto colOverLife;
        public MinMaxCurveDto sizeOverLife;
        public float velX;
        public float velY;
        public float rotOverLife;
        public float[] uvTiles;
        public int uvMode;
        public int uvAnim;
        public int uvRowMode;
        public int uvFrameMode;
        public float uvFrameScalar;
        public float uvFrameMin;
        public string matName;
        public string texName;
        public bool isAdditive;
        public ColorDto tint;
        public int sortOrder;
        public int renderMode;
        public float velocityScale;
        public float lengthScale;
        public float[] pivot;
    }

    [Serializable]
    public class FxClipDto { public string clip; public FxNodeDto[] nodes; }
    [Serializable]
    public class FxSpecRootDto { public FxClipDto idle; public FxClipDto fx_9008135; public FxClipDto fx_9008136; }

    private const string SpecPath = @".\_scratch\unity_fx_proj\fx_spec.json";
    private const string OutputRoot = @"E:\A灵魂潮汐\tools\_aurora_fx_sequences";

    public static void BuildAndCaptureAll()
    {
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        ConfigureAllTextures();

        if (!File.Exists(SpecPath))
        {
            Debug.LogError("[AuroraFxRecorder] Missing fx_spec.json: " + SpecPath);
            EditorApplication.Exit(2);
            return;
        }

        string rawJson = File.ReadAllText(SpecPath);
        FxSpecRootDto spec = JsonUtility.FromJson<FxSpecRootDto>(rawJson);
        if (spec == null || spec.idle == null)
        {
            Debug.LogError("[AuroraFxRecorder] Failed to parse fx_spec.json");
            EditorApplication.Exit(3);
            return;
        }

        Shader addShader = Shader.Find("Legacy Shaders/Particles/Additive");
        Shader alphaShader = Shader.Find("SoulTide/ParticleAlpha");
        if (addShader == null || alphaShader == null)
        {
            Debug.LogError($"[AuroraFxRecorder] Missing particle shader add={addShader} alpha={alphaShader}");
            EditorApplication.Exit(4);
            return;
        }

        GameObject camGo = new GameObject("FxCaptureCamera");
        Camera cam = camGo.AddComponent<Camera>();
        cam.orthographic = true;
        cam.orthographicSize = 588f; // 1176 / 2 UI px -> with 884x588 aspect captures exact 1768x1176 UI canvas!
        cam.nearClipPlane = 0.1f;
        cam.farClipPlane = 5000f;
        cam.allowHDR = false;
        cam.allowMSAA = true;
        camGo.transform.position = new Vector3(0f, 11.44f, -2000f);
        camGo.transform.rotation = Quaternion.identity;

        try
        {
            if (Directory.Exists(OutputRoot)) Directory.Delete(OutputRoot, true);
            Directory.CreateDirectory(OutputRoot);

            CaptureClip(spec.idle, cam, addShader, alphaShader, fps: 12f, duration: 2.0f, warmup: 4.0f);
            CaptureClip(spec.fx_9008135, cam, addShader, alphaShader, fps: 12f, duration: 7.0f, warmup: 0f);
            CaptureClip(spec.fx_9008136, cam, addShader, alphaShader, fps: 12f, duration: 11.0f, warmup: 0f);
            Debug.Log("[AuroraFxRecorder] ALL 3 FX clips captured cleanly -> " + OutputRoot);
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(camGo);
        }
    }

    private static void ConfigureAllTextures()
    {
        string texFolder = "Assets/Textures";
        string[] guids = AssetDatabase.FindAssets("t:Texture2D", new[] { texFolder });
        bool changed = false;
        foreach (string g in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(g);
            TextureImporter ti = AssetImporter.GetAtPath(path) as TextureImporter;
            if (ti == null) continue;
            if (ti.npotScale != TextureImporterNPOTScale.None || ti.mipmapEnabled || ti.textureCompression != TextureImporterCompression.Uncompressed)
            {
                ti.npotScale = TextureImporterNPOTScale.None;
                ti.mipmapEnabled = false;
                ti.textureCompression = TextureImporterCompression.Uncompressed;
                ti.wrapMode = TextureWrapMode.Clamp;
                ti.SaveAndReimport();
                changed = true;
            }
        }
        if (changed) AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
    }

    private static void CaptureClip(FxClipDto clip, Camera cam, Shader addShader, Shader alphaShader, float fps, float duration, float warmup)
    {
        GameObject root = new GameObject("Root_" + clip.clip);
        var createdMats = new List<Material>();
        var normalRenderers = new List<ParticleSystemRenderer>();
        var additiveRenderers = new List<ParticleSystemRenderer>();
        var systems = new List<ParticleSystem>();

        uint seedBase = 1001u;
        foreach (FxNodeDto n in clip.nodes)
        {
            GameObject go = new GameObject(n.name);
            go.transform.SetParent(root.transform, false);
            go.transform.position = new Vector3(n.world_pos[0], n.world_pos[1], n.world_pos[2]);
            if (n.world_rot != null && n.world_rot.Length == 4)
                go.transform.rotation = new Quaternion(n.world_rot[0], n.world_rot[1], n.world_rot[2], n.world_rot[3]);
            go.transform.localScale = new Vector3(
                Mathf.Approximately(n.world_scale[0], 0f) ? 0.001f : n.world_scale[0],
                Mathf.Approximately(n.world_scale[1], 0f) ? 0.001f : n.world_scale[1],
                Mathf.Approximately(n.world_scale[2], 0f) ? 0.001f : n.world_scale[2]
            );

            ParticleSystem ps = go.AddComponent<ParticleSystem>();
            ParticleSystemRenderer psr = go.GetComponent<ParticleSystemRenderer>();
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            ps.useAutoRandomSeed = false;
            ps.randomSeed = seedBase++;

            var main = ps.main;
            main.duration = Mathf.Max(0.1f, n.duration);
            main.startDelay = Mathf.Max(0f, n.startDelay);
            main.loop = n.looping;
            main.scalingMode = (ParticleSystemScalingMode)Mathf.Clamp(n.scalingMode, 0, 2);
            main.simulationSpace = ParticleSystemSimulationSpace.Local;
            main.maxParticles = Mathf.Max(1, n.maxParticles);
            main.startLifetime = ToMinMaxCurve(n.lifetime, 1f);
            main.startSpeed = ToMinMaxCurve(n.speed, 0f);
            main.startSize = ToMinMaxCurve(n.size, 1f);
            main.startRotation = ToMinMaxCurve(n.rotation, 0f);
            main.startColor = (n.startColorMode == 2 || n.startColorMode == 4)
                ? new ParticleSystem.MinMaxGradient(ToCol(n.startColorMin), ToCol(n.startColor))
                : new ParticleSystem.MinMaxGradient(ToCol(n.startColor));

            var em = ps.emission;
            em.enabled = true;
            em.rateOverTime = new ParticleSystem.MinMaxCurve(n.rate);
            if (n.bursts != null && n.bursts.Length > 0)
            {
                var arr = new ParticleSystem.Burst[n.bursts.Length];
                for (int i = 0; i < n.bursts.Length; i++)
                {
                    var b = n.bursts[i];
                    short cmax = (short)Mathf.Clamp(Mathf.RoundToInt(b.count), 0, 1000);
                    short cmin = (b.mode == 3) ? (short)Mathf.Clamp(Mathf.RoundToInt(b.minCount), 0, 1000) : cmax;
                    if (cmin > cmax) { short tmp = cmin; cmin = cmax; cmax = tmp; }
                    arr[i] = new ParticleSystem.Burst(b.time, cmin, cmax);
                }
                em.SetBursts(arr);
            }

            var sh = ps.shape;
            sh.enabled = n.shapeEnabled;
            if (n.shapeEnabled)
            {
                sh.shapeType = (ParticleSystemShapeType)n.shapeType;
                sh.radius = n.shapeRadius;
                if (n.shapeBox != null && n.shapeBox.Length == 3)
                    sh.scale = new Vector3(n.shapeBox[0], n.shapeBox[1], n.shapeBox[2]);
                if (n.shapeRot != null && n.shapeRot.Length == 3)
                    sh.rotation = new Vector3(n.shapeRot[0], n.shapeRot[1], n.shapeRot[2]);
                if (n.shapePos != null && n.shapePos.Length == 3)
                    sh.position = new Vector3(n.shapePos[0], n.shapePos[1], n.shapePos[2]);
            }

            if (n.colOverLife != null && (n.colOverLife.ckeys?.Length > 0 || n.colOverLife.akeys?.Length > 0))
            {
                var col = ps.colorOverLifetime;
                col.enabled = true;
                Gradient g = new Gradient();
                var ck = new GradientColorKey[Mathf.Max(1, n.colOverLife.ckeys?.Length ?? 0)];
                if (n.colOverLife.ckeys != null && n.colOverLife.ckeys.Length > 0)
                {
                    for (int i = 0; i < n.colOverLife.ckeys.Length; i++)
                        ck[i] = new GradientColorKey(new Color(n.colOverLife.ckeys[i].r, n.colOverLife.ckeys[i].g, n.colOverLife.ckeys[i].b, 1f), n.colOverLife.ckeys[i].t);
                }
                else ck[0] = new GradientColorKey(Color.white, 0f);

                var ak = new GradientAlphaKey[Mathf.Max(1, n.colOverLife.akeys?.Length ?? 0)];
                if (n.colOverLife.akeys != null && n.colOverLife.akeys.Length > 0)
                {
                    for (int i = 0; i < n.colOverLife.akeys.Length; i++)
                        ak[i] = new GradientAlphaKey(n.colOverLife.akeys[i].a, n.colOverLife.akeys[i].t);
                }
                else ak[0] = new GradientAlphaKey(1f, 0f);

                g.SetKeys(ck, ak);
                col.color = new ParticleSystem.MinMaxGradient(g);
            }

            if (n.sizeOverLife != null && n.sizeOverLife.keys != null && n.sizeOverLife.keys.Length > 0)
            {
                var sz = ps.sizeOverLifetime;
                sz.enabled = true;
                sz.size = ToAnimationCurve(n.sizeOverLife);
            }

            if (Mathf.Abs(n.velX) > 1e-4f || Mathf.Abs(n.velY) > 1e-4f)
            {
                var vel = ps.velocityOverLifetime;
                vel.enabled = true;
                vel.space = ParticleSystemSimulationSpace.Local;
                vel.x = new ParticleSystem.MinMaxCurve(n.velX);
                vel.y = new ParticleSystem.MinMaxCurve(n.velY);
            }

            if (Mathf.Abs(n.rotOverLife) > 1e-4f)
            {
                var rot = ps.rotationOverLifetime;
                rot.enabled = true;
                rot.z = new ParticleSystem.MinMaxCurve(n.rotOverLife);
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
                else
                {
                    ts.frameOverTime = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 0f, 1f, 0.9999f));
                }
            }

            Material mat = new Material(n.isAdditive ? addShader : alphaShader);
            Texture2D tex = AssetDatabase.LoadAssetAtPath<Texture2D>($"Assets/Textures/{n.texName}.png");
            if (tex != null) mat.SetTexture("_MainTex", tex);
            else Debug.LogWarning("[AuroraFxRecorder] Missing texture: " + n.texName);

            Color tcol = ToCol(n.tint);
            if (tcol.a <= 0.001f) tcol = new Color(0.5f, 0.5f, 0.5f, 0.5f);
            mat.SetColor("_TintColor", tcol);
            createdMats.Add(mat);

            psr.sharedMaterial = mat;
            psr.renderMode = (ParticleSystemRenderMode)Mathf.Clamp(n.renderMode, 0, 4);
            if (n.renderMode == 1)
            {
                psr.velocityScale = n.velocityScale;
                psr.lengthScale = n.lengthScale;
            }
            if (n.pivot != null && n.pivot.Length == 3)
                psr.pivot = new Vector3(n.pivot[0], n.pivot[1], n.pivot[2]);
            psr.sortingOrder = n.sortOrder;

            if (n.isAdditive) additiveRenderers.Add(psr);
            else normalRenderers.Add(psr);
            systems.Add(ps);
        }

        // Capture frames using two-pass clean RenderTexture decomposition
        int W = 884, H = 588;
        string normDir = Path.Combine(OutputRoot, clip.clip, "normal");
        string addDir = Path.Combine(OutputRoot, clip.clip, "add");
        if (normalRenderers.Count > 0) Directory.CreateDirectory(normDir);
        if (additiveRenderers.Count > 0) Directory.CreateDirectory(addDir);

        RenderTexture rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32);
        Texture2D texBuf = new Texture2D(W, H, TextureFormat.RGBA32, false);
        try
        {
            cam.targetTexture = rt;
            cam.clearFlags = CameraClearFlags.SolidColor;

            if (warmup > 0f)
            {
                float warmDt = 1f / 30f;
                int warmSteps = Mathf.RoundToInt(warmup / warmDt);
                for (int w = 0; w < warmSteps; w++)
                    foreach (var ps in systems) ps.Simulate(warmDt, false, w == 0, false);
            }

            int totalFrames = Mathf.Max(1, Mathf.RoundToInt(duration * fps));
            float stepDt = 1f / fps;
            for (int f = 0; f < totalFrames; f++)
            {
                if (warmup <= 0f)
                {
                    if (f == 0)
                        foreach (var ps in systems) ps.Simulate(0f, false, true, false);
                    else
                        foreach (var ps in systems) ps.Simulate(stepDt, false, false, false);
                }
                else
                {
                    foreach (var ps in systems) ps.Simulate(stepDt, false, false, false);
                }

                if (normalRenderers.Count > 0)
                {
                    SetActive(normalRenderers, true);
                    SetActive(additiveRenderers, false);
                    cam.backgroundColor = new Color(0f, 0f, 0f, 0f);
                    cam.Render();
                    SaveRtPng(rt, texBuf, Path.Combine(normDir, $"frame_{f:D4}.png"), extractMaxAlpha: false);
                }

                if (additiveRenderers.Count > 0)
                {
                    SetActive(normalRenderers, false);
                    SetActive(additiveRenderers, true);
                    cam.backgroundColor = new Color(0f, 0f, 0f, 1f);
                    cam.Render();
                    SaveRtPng(rt, texBuf, Path.Combine(addDir, $"frame_{f:D4}.png"), extractMaxAlpha: true);
                }
            }
            Debug.Log($"[AuroraFxRecorder] Captured {clip.clip}: {totalFrames} frames (norm={normalRenderers.Count}, add={additiveRenderers.Count})");
        }
        finally
        {
            cam.targetTexture = null;
            RenderTexture.active = null;
            UnityEngine.Object.DestroyImmediate(rt);
            UnityEngine.Object.DestroyImmediate(texBuf);
            foreach (var m in createdMats) UnityEngine.Object.DestroyImmediate(m);
            UnityEngine.Object.DestroyImmediate(root);
        }
    }

    private static void SetActive(List<ParticleSystemRenderer> list, bool active)
    {
        foreach (var r in list) r.enabled = active;
    }

    private static ParticleSystem.MinMaxCurve ToMinMaxCurve(MinMaxCurveDto dto, float fallback)
    {
        if (dto == null) return new ParticleSystem.MinMaxCurve(fallback);
        if (dto.mode == 3)
        {
            float lo = Mathf.Min(dto.minScalar, dto.scalar);
            float hi = Mathf.Max(dto.minScalar, dto.scalar);
            return new ParticleSystem.MinMaxCurve(lo, hi);
        }
        return new ParticleSystem.MinMaxCurve(dto.scalar);
    }

    private static ParticleSystem.MinMaxCurve ToAnimationCurve(MinMaxCurveDto dto)
    {
        var kfs = new Keyframe[dto.keys.Length];
        for (int i = 0; i < dto.keys.Length; i++)
            kfs[i] = new Keyframe(dto.keys[i].t, dto.keys[i].v, dto.keys[i].@in, dto.keys[i].@out);
        var curve = new AnimationCurve(kfs);
        return new ParticleSystem.MinMaxCurve(Mathf.Approximately(dto.scalar, 0f) ? 1f : dto.scalar, curve);
    }

    private static Color ToCol(ColorDto c)
    {
        if (c == null) return Color.white;
        return new Color(c.r, c.g, c.b, c.a);
    }

    private static void SaveRtPng(RenderTexture rt, Texture2D buf, string path, bool extractMaxAlpha)
    {
        RenderTexture.active = rt;
        buf.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0);
        if (extractMaxAlpha)
        {
            // Keep RGB premultiplied as rendered on black so Spine DefaultPMAShader (Blend One One) adds exact glow without white clipping!
            Color32[] px = buf.GetPixels32();
            for (int i = 0; i < px.Length; i++)
            {
                px[i].a = Math.Max(px[i].r, Math.Max(px[i].g, px[i].b));
            }
            buf.SetPixels32(px);
        }
        buf.Apply();
        File.WriteAllBytes(path, buf.EncodeToPNG());
    }
}
#endif
