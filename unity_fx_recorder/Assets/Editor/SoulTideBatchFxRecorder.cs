#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Generalized batch Unity 2021.3.34f1 GPU ParticleSystem builder and two-pass PMA PNG recorder
/// for SoulTide Spine FX Submodels. Reads a multi-skin manifest via `-fxManifest <path>` so
/// dozens or all 110+ skins can be rendered in a single Unity Editor batchmode invocation.
/// </summary>
public static class SoulTideBatchFxRecorder
{
    [Serializable]
    public class CurveKeyDto { public float t, v; public float @in, @out; }

    [Serializable]
    public class MinMaxCurveDto
    {
        public int mode;
        public float scalar;
        public float minScalar;
        public CurveKeyDto[] keys;
        public CurveKeyDto[] minKeys;
    }

    [Serializable]
    public class ColorDto { public float r, g, b, a; }

    [Serializable]
    public class ColorKeyDto { public float t, r, g, b; }

    [Serializable]
    public class AlphaKeyDto { public float t, a; }

    [Serializable]
    public class GradientDto
    {
        public int mode;
        public ColorKeyDto[] ckeys;
        public AlphaKeyDto[] akeys;
    }

    [Serializable]
    public class BurstDto
    {
        public float time;
        public float count;
        public float minCount;
        public int mode;
        public int cycleCount;
        public float repeatInterval;
    }

    [Serializable]
    public class SubEmitterDto
    {
        public int targetIdx;
        public int type;
        public int properties;
        public float emitProbability = 1.0f;
    }

    [Serializable]
    public class FxNodeDto
    {
        public string name;
        public string path;
        public int effSortOrder;
        public int dfsSeq;
        public bool isSubEmitterChild;
        public SubEmitterDto[] subEmitters;
        public float[] world_pos;
        public float[] world_scale;
        public float[] world_rot;
        public float duration;
        public float startDelay;
        public bool looping;
        public bool prewarm;
        public int ringBufferMode;
        public float[] ringBufferLoopRange;
        public int scalingMode;
        public float simulationSpeed = 1.0f;
        public int simulationSpace;
        public MinMaxCurveDto gravityModifier;
        public float gravityScale = 1.0f;
        public MinMaxCurveDto lifetime;
        public MinMaxCurveDto speed;
        public MinMaxCurveDto size;
        public bool size3D;
        public MinMaxCurveDto sizeX;
        public MinMaxCurveDto sizeY;
        public MinMaxCurveDto sizeZ;
        public MinMaxCurveDto rotation;
        public bool rotation3D;
        public MinMaxCurveDto rotationX;
        public MinMaxCurveDto rotationY;
        public ColorDto startColor;
        public ColorDto startColorMin;
        public int startColorMode;
        public GradientDto startColorGrad;
        public int maxParticles;
        public float rate;
        public MinMaxCurveDto rateCurve;
        public float rateOverDistance;
        public MinMaxCurveDto rateOverDistanceCurve;
        public BurstDto[] bursts;
        public bool shapeEnabled;
        public int shapeType;
        public float shapeRadius;
        public float shapeArc;
        public float shapeAngle = 25f;
        public float shapeRadiusThickness = 1f;
        public float shapeRandomDir;
        public float shapeSphericalDir;
        public bool shapeAlignToDir;
        public float[] shapeBox;
        public float[] shapeRot;
        public float[] shapePos;
        public GradientDto colOverLife;
        public MinMaxCurveDto sizeOverLife;
        public bool sizeOverLifeSeparateAxes;
        public MinMaxCurveDto sizeOverLifeY;
        public MinMaxCurveDto sizeOverLifeZ;
        public bool velEnabled;
        public float velX;
        public float velY;
        public float velZ;
        public MinMaxCurveDto velXCurve;
        public MinMaxCurveDto velYCurve;
        public MinMaxCurveDto velZCurve;
        public bool velInWorldSpace;
        public MinMaxCurveDto velOrbitalX;
        public MinMaxCurveDto velOrbitalY;
        public MinMaxCurveDto velOrbitalZ;
        public MinMaxCurveDto velOrbitalOffsetX;
        public MinMaxCurveDto velOrbitalOffsetY;
        public MinMaxCurveDto velOrbitalOffsetZ;
        public MinMaxCurveDto velRadial;
        public MinMaxCurveDto velSpeedModifier;
        public bool limitVelEnabled;
        public bool limitVelSeparateAxes;
        public MinMaxCurveDto limitVel;
        public MinMaxCurveDto limitVelX;
        public MinMaxCurveDto limitVelY;
        public MinMaxCurveDto limitVelZ;
        public float limitVelDampen = 1f;
        public MinMaxCurveDto limitVelDrag;
        public bool limitVelInWorld;
        public bool limitVelMulSize;
        public bool limitVelMulVel;
        public bool rotOverLifeEnabled;
        public bool rotOverLifeSeparateAxes;
        public float rotOverLife;
        public MinMaxCurveDto rotOverLifeCurve;
        public MinMaxCurveDto rotOverLifeX;
        public MinMaxCurveDto rotOverLifeY;
        public bool noiseEnabled;
        public bool noiseSeparateAxes;
        public float noiseStrength;
        public MinMaxCurveDto noiseStrengthCurve;
        public MinMaxCurveDto noiseStrengthYCurve;
        public MinMaxCurveDto noiseStrengthZCurve;
        public float noiseFrequency;
        public float noiseScrollSpeed;
        public MinMaxCurveDto noiseScrollSpeedCurve;
        public bool noiseDamping = true;
        public int noiseOctaves;
        public float noiseOctaveMultiplier = 0.5f;
        public float noiseOctaveScale = 2.0f;
        public int noiseQuality = 2;
        public MinMaxCurveDto noisePosAmountCurve;
        public MinMaxCurveDto noiseRotAmountCurve;
        public MinMaxCurveDto noiseSizeAmountCurve;
        public bool forceEnabled;
        public bool forceInWorldSpace;
        public bool forceRandomized;
        public float forceX;
        public float forceY;
        public float forceZ;
        public MinMaxCurveDto forceXCurve;
        public MinMaxCurveDto forceYCurve;
        public MinMaxCurveDto forceZCurve;
        public bool rotBySpeedEnabled;
        public bool rotBySpeedSeparateAxes;
        public MinMaxCurveDto rotBySpeedCurve;
        public MinMaxCurveDto rotBySpeedX;
        public MinMaxCurveDto rotBySpeedY;
        public float[] rotBySpeedRange;
        public bool customDataEnabled;
        public int customDataMode;
        public MinMaxCurveDto custom1X;
        public MinMaxCurveDto custom1Y;
        public MinMaxCurveDto custom1Z;
        public MinMaxCurveDto custom1W;
        public float[] uvTiles;
        public int uvMode;
        public int uvAnim;
        public int uvRowMode;
        public int uvFrameMode;
        public float uvFrameScalar;
        public float uvFrameMin;
        public CurveKeyDto[] uvFrameKeys;
        public bool hasMainMaterial = true;
        public string matName;
        public string shaderName;
        public bool customDataFlag;
        public string texName;
        public float[] texScale;
        public float[] texOffset;
        public int[] texWrap;
        public string maskTexName;
        public float[] maskScale;
        public float[] maskOffset;
        public int[] maskWrap;
        public string mask2TexName;
        public float[] mask2Scale;
        public float[] mask2Offset;
        public int[] mask2Wrap;
        public string dissolveTexName;
        public float[] dissolveScale;
        public float[] dissolveOffset;
        public int[] dissolveWrap;
        public float dissolve;
        public float dissolveSoft = 0.5f;
        public string distortTexName;
        public float[] distortScale;
        public float[] distortOffset;
        public int[] distortWrap;
        public float distortStrength;
        public float[] uvScroll;
        public bool isAdditive;
        public ColorDto tint;
        public float tintMultiplier = 1.0f;
        public int sortOrder;
        public int renderMode;
        public int renderAlignment;
        public float maxParticleSize = 0.5f;
        public string meshName;
        public float velocityScale;
        public float lengthScale;
        public float[] pivot;
        public float[] flip;
        public bool trailsEnabled;
        public int trailMode;
        public float trailRatio = 1.0f;
        public MinMaxCurveDto trailLifetime;
        public float trailMinVertexDist = 0.2f;
        public bool trailWorldSpace;
        public bool trailDieWithParticles = true;
        public bool trailSizeAffectsWidth = true;
        public bool trailSizeAffectsLifetime;
        public bool trailInheritColor = true;
        public int trailTextureMode;
        public int trailRibbonCount = 1;
        public MinMaxCurveDto trailWidthOverTrail;
        public GradientDto trailColorOverLifetime;
        public GradientDto trailColorOverTrail;
        public bool hasTrailMaterial;
        public string trailTexName;
        public float[] trailTexScale;
        public float[] trailTexOffset;
        public int[] trailTexWrap;
        public string trailMaskTexName;
        public float[] trailMaskScale;
        public float[] trailMaskOffset;
        public int[] trailMaskWrap;
        public string trailMask2TexName;
        public float[] trailMask2Scale;
        public float[] trailMask2Offset;
        public int[] trailMask2Wrap;
        public string trailDissolveTexName;
        public float[] trailDissolveScale;
        public float[] trailDissolveOffset;
        public int[] trailDissolveWrap;
        public float trailDissolve;
        public float trailDissolveSoft = 0.5f;
        public string trailDistortTexName;
        public float[] trailDistortScale;
        public float[] trailDistortOffset;
        public int[] trailDistortWrap;
        public float trailDistortStrength;
        public float[] trailUvScroll;
        public bool trailIsAdditive;
        public ColorDto trailTint;
        public float trailTintMultiplier = 1.0f;
    }

    [Serializable]
    public class FxClipDto
    {
        public string clip;
        public string layer = "front";
        public float fps = 20f;
        public float duration = 5f;
        public float warmup = 0f;
        public bool crossfadeIdle = false;
        public bool useZeroCrossfade = false;
        public float blendDuration = 1.0f;
        public FxNodeDto[] nodes;
    }

    [Serializable]
    public class FxSkinDto
    {
        public string skin_key;
        public string output_dir;
        public float cam_x;
        public float cam_y;
        public int canvas_w = 1768;
        public int canvas_h = 1176;
        public int render_w = 884;
        public int render_h = 588;
        public float fps = 12f;
        public float person_wx;
        public float person_wy;
        public float ui_per_spine_x;
        public float ui_per_spine_y;
        public float person_z_deg;
        public FxClipDto[] clips;
    }

    [Serializable]
    public class FxManifestDto
    {
        public FxSkinDto[] skins;
    }

    private static string GetArgValue(string flag, string fallback)
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (string.Equals(args[i], flag, StringComparison.OrdinalIgnoreCase))
                return args[i + 1];
        }
        return fallback;
    }

    public static void BuildAndCaptureAll()
    {
        string manifestPath = GetArgValue(
            "-fxManifest",
            Path.Combine(Directory.GetCurrentDirectory(), "fx_manifest.json")
        );
        if (!File.Exists(manifestPath))
        {
            Debug.LogError("[BatchFxRecorder] Missing manifest: " + manifestPath);
            EditorApplication.Exit(2);
            return;
        }

        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        ConfigureAllTextures(manifestPath);
        ConfigureAllMeshes();

        string rawJson = File.ReadAllText(manifestPath, Encoding.UTF8);
        FxManifestDto manifest = JsonUtility.FromJson<FxManifestDto>(rawJson);
        if (manifest == null || manifest.skins == null || manifest.skins.Length == 0)
        {
            Debug.LogError("[BatchFxRecorder] Empty or invalid manifest: " + manifestPath);
            EditorApplication.Exit(3);
            return;
        }

        Shader addShader = Shader.Find("Legacy Shaders/Particles/Additive");
        Shader addMaskShader = Shader.Find("SoulTide/ParticleAdd");
        Shader alphaShader = Shader.Find("SoulTide/ParticleAlpha");
        if (addShader == null || alphaShader == null)
        {
            Debug.LogError($"[BatchFxRecorder] Missing shader add={addShader} alpha={alphaShader}");
            EditorApplication.Exit(4);
            return;
        }
        if (addMaskShader == null) addMaskShader = addShader;

        Mesh quadMesh = Resources.GetBuiltinResource<Mesh>("Quad.fbx");
        if (quadMesh == null)
        {
            GameObject tmp = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quadMesh = tmp.GetComponent<MeshFilter>().sharedMesh;
            UnityEngine.Object.DestroyImmediate(tmp);
        }

        var meshCache = new Dictionary<string, Mesh>(StringComparer.OrdinalIgnoreCase);
        meshCache["BUILTIN_QUAD"] = quadMesh;
        foreach (var kv in new[] { ("BUILTIN_PLANE", PrimitiveType.Plane), ("BUILTIN_CUBE", PrimitiveType.Cube) })
        {
            GameObject tmp = GameObject.CreatePrimitive(kv.Item2);
            meshCache[kv.Item1] = tmp.GetComponent<MeshFilter>().sharedMesh;
            UnityEngine.Object.DestroyImmediate(tmp);
        }
        if (AssetDatabase.IsValidFolder("Assets/Meshes"))
        {
            string[] objPaths = Directory.GetFiles(Path.Combine(Application.dataPath, "Meshes"), "*.obj", SearchOption.AllDirectories);
            foreach (string fullPath in objPaths)
            {
                string ap = "Assets/Meshes/" + Path.GetFileName(fullPath);
                string stem = Path.GetFileNameWithoutExtension(fullPath);
                foreach (UnityEngine.Object sub in AssetDatabase.LoadAllAssetsAtPath(ap))
                {
                    if (sub is Mesh mm)
                    {
                        meshCache[stem] = mm;
                        break;
                    }
                }
            }
        }

        // Pre-cache all textures under Assets/Textures for O(1) lookup across 100+ skins
        var texCache = new Dictionary<string, Texture2D>(StringComparer.OrdinalIgnoreCase);
        foreach (string g in AssetDatabase.FindAssets("t:Texture2D", new[] { "Assets/Textures" }))
        {
            string ap = AssetDatabase.GUIDToAssetPath(g);
            Texture2D t = AssetDatabase.LoadAssetAtPath<Texture2D>(ap);
            if (t != null)
                texCache[Path.GetFileNameWithoutExtension(ap)] = t;
        }

        GameObject camGo = new GameObject("BatchFxCaptureCamera");
        Camera cam = camGo.AddComponent<Camera>();
        cam.orthographic = true;
        cam.nearClipPlane = 0.1f;
        cam.farClipPlane = 5000f;
        cam.allowHDR = false;
        cam.allowMSAA = true;

        RenderTexture rt = null;
        Texture2D texBuf = null;
        int curW = -1, curH = -1;
        var summaryEntries = new List<string>();
        int okSkins = 0;
        int errSkins = 0;

        try
        {
            foreach (FxSkinDto skin in manifest.skins)
            {
                if (skin == null || skin.clips == null || skin.clips.Length == 0)
                    continue;

                try
                {
                    int rw = Mathf.Max(64, skin.render_w);
                    int rh = Mathf.Max(64, skin.render_h);
                    if (rt == null || rw != curW || rh != curH)
                    {
                        cam.targetTexture = null;
                        RenderTexture.active = null;
                        if (rt != null) UnityEngine.Object.DestroyImmediate(rt);
                        if (texBuf != null) UnityEngine.Object.DestroyImmediate(texBuf);
                        rt = new RenderTexture(rw, rh, 24, RenderTextureFormat.ARGB32);
                        rt.antiAliasing = 4;
                        rt.Create();
                        texBuf = new Texture2D(rw, rh, TextureFormat.RGBA32, false);
                        curW = rw;
                        curH = rh;
                    }

                    cam.orthographicSize = Mathf.Max(10f, skin.canvas_h * 0.5f);
                    cam.aspect = (float)rw / (float)rh;
                    camGo.transform.position = new Vector3(skin.cam_x, skin.cam_y, -2000f);
                    camGo.transform.rotation = Quaternion.identity;

                    Directory.CreateDirectory(skin.output_dir);

                    int clipOk = 0;
                    var clipMetaEntries = new List<string>();
                    foreach (FxClipDto clip in skin.clips)
                    {
                        if (clip == null || clip.nodes == null || clip.nodes.Length == 0)
                            continue;
                        string clipDir = Path.Combine(skin.output_dir, clip.clip);
                        if (Directory.Exists(clipDir))
                            Directory.Delete(clipDir, true);
                        float clipFps = clip.fps > 0.1f ? clip.fps : (skin.fps > 0.1f ? skin.fps : 20f);
                        int writtenFrames = CaptureClip(
                            skin.output_dir,
                            clip,
                            cam,
                            rt,
                            texBuf,
                            addShader,
                            addMaskShader,
                            alphaShader,
                            quadMesh,
                            meshCache,
                            texCache,
                            clipFps
                        );
                        clipMetaEntries.Add($"\"{EscapeJson(clip.clip)}\":{{\"fps\":{clipFps.ToString(System.Globalization.CultureInfo.InvariantCulture)},\"frames\":{writtenFrames},\"duration\":{clip.duration.ToString(System.Globalization.CultureInfo.InvariantCulture)},\"crossfade\":{(clip.crossfadeIdle ? "true" : "false")},\"zeroCrossfade\":{(clip.useZeroCrossfade ? "true" : "false")},\"layer\":\"{EscapeJson(string.IsNullOrEmpty(clip.layer) ? "front" : clip.layer)}\"}}");
                        clipOk++;
                    }
                    File.WriteAllText(
                        Path.Combine(skin.output_dir, "clip_meta.json"),
                        "{\"clips\":{" + string.Join(",", clipMetaEntries) + "}}",
                        Encoding.UTF8
                    );
                    okSkins++;
                    summaryEntries.Add($"{{\"skin\":\"{EscapeJson(skin.skin_key)}\",\"status\":\"ok\",\"clips\":{clipOk}}}");
                    Debug.Log($"[BatchFxRecorder] OK {skin.skin_key}: {clipOk} clips -> {skin.output_dir}");
                }
                catch (Exception ex)
                {
                    errSkins++;
                    summaryEntries.Add($"{{\"skin\":\"{EscapeJson(skin.skin_key)}\",\"status\":\"error\",\"error\":\"{EscapeJson(ex.Message)}\"}}");
                    Debug.LogError($"[BatchFxRecorder] ERROR {skin.skin_key}: {ex}");
                }
            }
        }
        finally
        {
            cam.targetTexture = null;
            RenderTexture.active = null;
            if (rt != null) UnityEngine.Object.DestroyImmediate(rt);
            if (texBuf != null) UnityEngine.Object.DestroyImmediate(texBuf);
            UnityEngine.Object.DestroyImmediate(camGo);
        }

        string summaryPath = Path.Combine(Path.GetDirectoryName(manifestPath) ?? ".", "batch_unity_summary.json");
        string summaryJson = $"{{\"ok\":{okSkins},\"errors\":{errSkins},\"items\":[{string.Join(",", summaryEntries)}]}}";
        File.WriteAllText(summaryPath, summaryJson, Encoding.UTF8);
        Debug.Log($"[BatchFxRecorder] DONE ok={okSkins} errors={errSkins} -> {summaryPath}");
    }

    private static TextureWrapMode ToUnityWrapMode(int w)
    {
        switch (w)
        {
            case 1: return TextureWrapMode.Clamp;
            case 2: return TextureWrapMode.Mirror;
            case 3: return TextureWrapMode.MirrorOnce;
            default: return TextureWrapMode.Repeat;
        }
    }

    private static Dictionary<string, int[]> LoadTextureWrapModes(string manifestPath)
    {
        var map = new Dictionary<string, int[]>(StringComparer.OrdinalIgnoreCase);
        string[] cands = new[]
        {
            Path.Combine(Path.GetDirectoryName(manifestPath) ?? ".", "tex_wrap_modes.json"),
            Path.Combine(Directory.GetCurrentDirectory(), "tex_wrap_modes.json"),
        };
        string found = null;
        foreach (string c in cands)
        {
            if (File.Exists(c)) { found = c; break; }
        }
        if (found == null) return map;
        string txt = File.ReadAllText(found, Encoding.UTF8);
        var rx = new Regex("\"([^\"]+)\"\\s*:\\s*\\[\\s*(\\d+)\\s*,\\s*(\\d+)\\s*\\]");
        foreach (Match m in rx.Matches(txt))
        {
            int wu = int.Parse(m.Groups[2].Value);
            int wv = int.Parse(m.Groups[3].Value);
            map[m.Groups[1].Value] = new[] { wu, wv };
        }
        Debug.Log($"[BatchFxRecorder] Loaded {map.Count} original texture wrap modes from {found}");
        return map;
    }

    private static void ConfigureAllTextures(string manifestPath)
    {
        var wrapMap = LoadTextureWrapModes(manifestPath);
        string[] guids = AssetDatabase.FindAssets("t:Texture2D", new[] { "Assets/Textures" });
        bool changed = false;
        int clampCount = 0;
        foreach (string g in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(g);
            TextureImporter ti = AssetImporter.GetAtPath(path) as TextureImporter;
            if (ti == null) continue;
            string stem = Path.GetFileNameWithoutExtension(path);
            TextureWrapMode wantU = TextureWrapMode.Repeat;
            TextureWrapMode wantV = TextureWrapMode.Repeat;
            if (wrapMap.TryGetValue(stem, out int[] wuv) && wuv != null && wuv.Length >= 2)
            {
                wantU = ToUnityWrapMode(wuv[0]);
                wantV = ToUnityWrapMode(wuv[1]);
                if (wantU == TextureWrapMode.Clamp || wantV == TextureWrapMode.Clamp)
                    clampCount++;
            }
            if (ti.npotScale != TextureImporterNPOTScale.None ||
                ti.mipmapEnabled ||
                ti.textureCompression != TextureImporterCompression.Uncompressed ||
                ti.wrapModeU != wantU ||
                ti.wrapModeV != wantV)
            {
                ti.npotScale = TextureImporterNPOTScale.None;
                ti.mipmapEnabled = false;
                ti.textureCompression = TextureImporterCompression.Uncompressed;
                ti.wrapModeU = wantU;
                ti.wrapModeV = wantV;
                ti.SaveAndReimport();
                changed = true;
            }
        }
        Debug.Log($"[BatchFxRecorder] Configured {guids.Length} textures (clamp={clampCount}, reimported={changed})");
        if (changed) AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
    }

    private static void ConfigureAllMeshes()
    {
        if (!AssetDatabase.IsValidFolder("Assets/Meshes")) return;
        string[] objPaths = Directory.GetFiles(Path.Combine(Application.dataPath, "Meshes"), "*.obj", SearchOption.TopDirectoryOnly);
        bool changed = false;
        foreach (string fullPath in objPaths)
        {
            string ap = "Assets/Meshes/" + Path.GetFileName(fullPath);
            ModelImporter mi = AssetImporter.GetAtPath(ap) as ModelImporter;
            if (mi == null) continue;
            if (!Mathf.Approximately(mi.globalScale, 1f) ||
                !mi.useFileScale ||
                !mi.isReadable ||
                mi.importBlendShapes ||
                mi.importCameras ||
                mi.importLights ||
                mi.animationType != ModelImporterAnimationType.None ||
                mi.materialImportMode != ModelImporterMaterialImportMode.None)
            {
                mi.globalScale = 1f;
                mi.useFileScale = true;
                mi.isReadable = true;
                mi.importBlendShapes = false;
                mi.importCameras = false;
                mi.importLights = false;
                mi.animationType = ModelImporterAnimationType.None;
                mi.materialImportMode = ModelImporterMaterialImportMode.None;
                mi.SaveAndReimport();
                changed = true;
            }
        }
        if (changed) AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
    }

    private class UvScrollEntry
    {
        public Material mat;
        public string prop;
        public Vector2 baseOffset;
        public float u, v;
        public bool wobbleU;
        public bool wobbleV;
        public float periodT;
    }

    private class RenderPassItem
    {
        public ParticleSystemRenderer psr;
        public Material mainMat;
        public Material trailMat;
        public bool mainNorm;
        public bool mainAdd;
        public bool trailNorm;
        public bool trailAdd;
        public bool isMixed;
    }

    private class CloneRunner
    {
        public ParticleSystem rootPs;
        public int startTick;
        public int stopTick;
        public int[] emitSchedule; // non-null for saturated steady-state replay
        public bool started;
        public bool stopped;
        public bool emittedTick0;
    }

    private static bool HasLifetimeModulation(FxNodeDto n)
    {
        if (n == null) return false;
        if (n.colOverLife != null)
        {
            if (n.colOverLife.akeys != null && n.colOverLife.akeys.Length >= 2)
            {
                float a0 = n.colOverLife.akeys[0].a;
                for (int i = 1; i < n.colOverLife.akeys.Length; i++)
                    if (Mathf.Abs(n.colOverLife.akeys[i].a - a0) > 0.01f) return true;
            }
            if (n.colOverLife.ckeys != null && n.colOverLife.ckeys.Length >= 2)
            {
                var c0 = n.colOverLife.ckeys[0];
                for (int i = 1; i < n.colOverLife.ckeys.Length; i++)
                {
                    var ck = n.colOverLife.ckeys[i];
                    if (Mathf.Abs(ck.r - c0.r) > 0.01f || Mathf.Abs(ck.g - c0.g) > 0.01f || Mathf.Abs(ck.b - c0.b) > 0.01f)
                        return true;
                }
            }
        }
        if (n.sizeOverLife != null && ((n.sizeOverLife.keys != null && n.sizeOverLife.keys.Length > 0) || n.sizeOverLife.mode == 3 || n.sizeOverLifeSeparateAxes))
            return true;
        if (n.velEnabled || n.limitVelEnabled || n.forceEnabled || n.noiseEnabled || n.rotOverLifeEnabled || n.rotBySpeedEnabled)
            return true;
        if (GetCurveMax(n.speed, 0f) > 1e-4f) return true;
        if (HasNonZeroCurve(n.gravityModifier) || HasCurveData(n.gravityModifier)) return true;
        if (n.customDataEnabled) return true;
        if (n.uvTiles != null && n.uvTiles.Length >= 2) return true;
        if (n.trailsEnabled) return true;
        return false;
    }

    private static bool HasSpatialMotion(FxNodeDto n)
    {
        if (n == null) return false;
        if (n.velEnabled || n.limitVelEnabled || n.forceEnabled || n.noiseEnabled || n.trailsEnabled) return true;
        if (GetCurveMax(n.speed, 0f) > 1e-4f) return true;
        if (HasNonZeroCurve(n.gravityModifier) || HasCurveData(n.gravityModifier)) return true;
        return false;
    }

    private static bool IsDeterministicLifetime(MinMaxCurveDto lt)
    {
        if (lt == null) return true;
        if (lt.mode == 0) return true;
        if (lt.mode == 3) return Mathf.Abs(lt.scalar - lt.minScalar) < 0.01f;
        return false;
    }

    private static float GetCurveMax(MinMaxCurveDto c, float fallback)
    {
        if (c == null) return fallback;
        float hi = Mathf.Max(c.scalar, c.mode == 3 ? c.minScalar : c.scalar);
        if ((c.mode == 1 || c.mode == 2) && c.keys != null && c.keys.Length > 0)
        {
            float km = 0f;
            for (int i = 0; i < c.keys.Length; i++) km = Mathf.Max(km, c.keys[i].v);
            hi = Mathf.Max(0.01f, Mathf.Approximately(c.scalar, 0f) ? 1f : c.scalar) * km;
        }
        return hi;
    }

    private static void CollectTreeIndices(FxNodeDto[] nodes, int rootIdx, List<int> outList, HashSet<int> visited)
    {
        if (rootIdx < 0 || rootIdx >= nodes.Length || visited.Contains(rootIdx)) return;
        visited.Add(rootIdx);
        outList.Add(rootIdx);
        var n = nodes[rootIdx];
        if (n != null && n.subEmitters != null)
        {
            for (int i = 0; i < n.subEmitters.Length; i++)
                CollectTreeIndices(nodes, n.subEmitters[i].targetIdx, outList, visited);
        }
    }

    private static float EstimateTreeMaxLife(FxNodeDto[] nodes, List<int> treeIdx)
    {
        if (treeIdx.Count == 0) return 1f;
        var root = nodes[treeIdx[0]];
        float simSpd = root.simulationSpeed > 0.001f ? root.simulationSpeed : 1f;
        float rootLt = GetCurveMax(root.lifetime, 1f) / simSpd;
        float extraTrail = 0f;
        if (root.trailsEnabled && !root.trailDieWithParticles)
            extraTrail = GetCurveMax(root.trailLifetime, 0.5f) / simSpd;
        float maxSubLt = 0f;
        for (int i = 1; i < treeIdx.Count; i++)
        {
            var cn = nodes[treeIdx[i]];
            if (cn == null) continue;
            float cs = cn.simulationSpeed > 0.001f ? cn.simulationSpeed : 1f;
            float clt = GetCurveMax(cn.lifetime, 1f) / cs;
            if (clt < 99f) maxSubLt = Mathf.Max(maxSubLt, clt);
        }
        return Mathf.Max(0.25f, rootLt + maxSubLt + extraTrail);
    }

    private static ParticleSystem BuildTreeInstance(
        Transform parentRoot,
        FxNodeDto[] clipNodes,
        List<int> treeIndices,
        uint seedBase,
        int sortOrderOffset,
        bool disableRootEmissionForManualReplay,
        int minMaxParticlesOverride,
        float rootSimSpeedMultiplier,
        float periodicLoopT,
        Dictionary<string, Mesh> meshCache,
        Mesh quadMesh,
        Dictionary<string, Texture2D> texCache,
        Shader addShader,
        Shader addMaskShader,
        Shader alphaShader,
        List<Material> createdMats,
        List<UvScrollEntry> uvEntries,
        List<RenderPassItem> passItems,
        ref bool anyNormal,
        ref bool anyAdditive,
        bool registerRendering,
        bool forceStaticRingBufferLoop = false
    )
    {
        var idxToGo = new Dictionary<int, GameObject>();
        var idxToPs = new Dictionary<int, ParticleSystem>();
        int rootNodeIdx = treeIndices[0];

        for (int ti = 0; ti < treeIndices.Count; ti++)
        {
            int ni = treeIndices[ti];
            FxNodeDto n = clipNodes[ni];
            if (n == null) continue;
            bool isRootOfTree = (ni == rootNodeIdx);
            GameObject go = new GameObject((n.name ?? "ps") + (sortOrderOffset != 0 ? $"_c{sortOrderOffset}" : ""));
            go.transform.SetParent(parentRoot, false);
            if (n.world_pos != null && n.world_pos.Length >= 3)
                go.transform.position = new Vector3(n.world_pos[0], n.world_pos[1], n.world_pos[2]);
            if (n.world_rot != null && n.world_rot.Length >= 4)
                go.transform.rotation = new Quaternion(n.world_rot[0], n.world_rot[1], n.world_rot[2], n.world_rot[3]);
            if (n.world_scale != null && n.world_scale.Length >= 3)
            {
                go.transform.localScale = new Vector3(
                    Mathf.Approximately(n.world_scale[0], 0f) ? 0.001f : n.world_scale[0],
                    Mathf.Approximately(n.world_scale[1], 0f) ? 0.001f : n.world_scale[1],
                    Mathf.Approximately(n.world_scale[2], 0f) ? 0.001f : n.world_scale[2]
                );
            }

            ParticleSystem ps = go.AddComponent<ParticleSystem>();
            ParticleSystemRenderer psr = go.GetComponent<ParticleSystemRenderer>();
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            ps.useAutoRandomSeed = false;
            ps.randomSeed = seedBase + (uint)ni;

            var main = ps.main;
            main.playOnAwake = !n.isSubEmitterChild;
            main.duration = (isRootOfTree && forceStaticRingBufferLoop) ? 99999f : Mathf.Max(0.1f, n.duration);
            main.startDelay = Mathf.Max(0f, n.startDelay);
            main.loop = (isRootOfTree && forceStaticRingBufferLoop) ? false : n.looping;
            main.prewarm = false; // explicit deterministic simulation handles warmup/cloning cleanly
            if (isRootOfTree && forceStaticRingBufferLoop)
            {
                main.ringBufferMode = ParticleSystemRingBufferMode.LoopUntilReplaced;
                main.ringBufferLoopRange = new Vector2(0f, 1f);
            }
            else if (n.ringBufferMode > 0)
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
            float baseSimSpd = n.simulationSpeed > 0.001f ? n.simulationSpeed : 1f;
            main.simulationSpeed = isRootOfTree ? (baseSimSpd * rootSimSpeedMultiplier) : baseSimSpd;
            main.scalingMode = ParticleSystemScalingMode.Hierarchy;
            main.simulationSpace = (n.simulationSpace == 1) ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
            int effMaxP = n.maxParticles > 0 ? n.maxParticles : 50;
            if (isRootOfTree && minMaxParticlesOverride > effMaxP)
                effMaxP = minMaxParticlesOverride;
            main.maxParticles = Mathf.Clamp(effMaxP, 1, 2000);
            if (HasNonZeroCurve(n.gravityModifier) || HasCurveData(n.gravityModifier))
            {
                float gScale = Mathf.Abs(n.gravityScale) > 1e-4f ? n.gravityScale : 1f;
                main.gravityModifier = ToMinMaxCurve(n.gravityModifier, 0f, gScale);
            }
            main.startLifetime = ToMinMaxCurve(n.lifetime, 1f);
            main.startSpeed = ToMinMaxCurve(n.speed, 0f);
            if (n.size3D && n.sizeX != null && n.sizeY != null)
            {
                main.startSize3D = true;
                main.startSizeX = ToMinMaxCurve(n.sizeX, 1f);
                main.startSizeY = ToMinMaxCurve(n.sizeY, 1f);
                main.startSizeZ = ToMinMaxCurve(n.sizeZ, 1f);
            }
            else main.startSize = ToMinMaxCurve(n.size, 1f);

            if (n.rotation3D)
            {
                main.startRotation3D = true;
                main.startRotationX = ToMinMaxCurve(n.rotationX, 0f);
                main.startRotationY = ToMinMaxCurve(n.rotationY, 0f);
                main.startRotationZ = ToMinMaxCurve(n.rotation, 0f);
            }
            else main.startRotation = ToMinMaxCurve(n.rotation, 0f);

            if ((n.startColorMode == 1 || n.startColorMode == 3 || n.startColorMode == 4) && n.startColorGrad != null &&
                (n.startColorGrad.ckeys?.Length > 0 || n.startColorGrad.akeys?.Length > 0))
            {
                var mmg = new ParticleSystem.MinMaxGradient(BuildGradient(n.startColorGrad));
                if (n.startColorMode == 4)
                    mmg.mode = ParticleSystemGradientMode.RandomColor;
                main.startColor = mmg;
            }
            else if (n.startColorMode == 2)
                main.startColor = new ParticleSystem.MinMaxGradient(ToCol(n.startColorMin), ToCol(n.startColor));
            else
                main.startColor = new ParticleSystem.MinMaxGradient(ToCol(n.startColor));

            var em = ps.emission;
            if (isRootOfTree && forceStaticRingBufferLoop)
            {
                em.enabled = true;
                em.rateOverTime = new ParticleSystem.MinMaxCurve(0f);
                em.rateOverDistance = new ParticleSystem.MinMaxCurve(0f);
                short cnt = (short)Mathf.Clamp(effMaxP, 1, 1000);
                em.SetBursts(new[] { new ParticleSystem.Burst(0f, cnt, cnt, 1, 0.01f) });
            }
            else
            {
                em.enabled = !(isRootOfTree && disableRootEmissionForManualReplay);
                em.rateOverTime = HasCurveData(n.rateCurve)
                    ? ToMinMaxCurve(n.rateCurve, n.rate)
                    : new ParticleSystem.MinMaxCurve(Mathf.Max(0f, n.rate));
                if (HasCurveData(n.rateOverDistanceCurve) || HasNonZeroCurve(n.rateOverDistanceCurve) || n.rateOverDistance > 0f)
                {
                    em.rateOverDistance = HasCurveData(n.rateOverDistanceCurve)
                        ? ToMinMaxCurve(n.rateOverDistanceCurve, n.rateOverDistance)
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
                if (n.shapeBox != null && n.shapeBox.Length >= 3)
                    sh.scale = new Vector3(n.shapeBox[0], n.shapeBox[1], n.shapeBox[2]);
                if (n.shapeRot != null && n.shapeRot.Length >= 3)
                    sh.rotation = new Vector3(n.shapeRot[0], n.shapeRot[1], n.shapeRot[2]);
                if (n.shapePos != null && n.shapePos.Length >= 3)
                    sh.position = new Vector3(n.shapePos[0], n.shapePos[1], n.shapePos[2]);
            }

            if (n.colOverLife != null && (n.colOverLife.ckeys?.Length > 0 || n.colOverLife.akeys?.Length > 0))
            {
                var col = ps.colorOverLifetime;
                col.enabled = true;
                col.color = new ParticleSystem.MinMaxGradient(BuildGradient(n.colOverLife));
            }
            if (n.sizeOverLife != null && ((n.sizeOverLife.keys != null && n.sizeOverLife.keys.Length > 0) || n.sizeOverLife.mode == 3 || n.sizeOverLifeSeparateAxes))
            {
                var sz = ps.sizeOverLifetime;
                sz.enabled = true;
                if (n.sizeOverLifeSeparateAxes)
                {
                    sz.separateAxes = true;
                    sz.x = ToMinMaxCurve(n.sizeOverLife, 1f);
                    sz.y = ToMinMaxCurve(n.sizeOverLifeY, 1f);
                    sz.z = ToMinMaxCurve(n.sizeOverLifeZ, 1f);
                }
                else sz.size = ToMinMaxCurve(n.sizeOverLife, 1f);
            }
            if (n.velEnabled)
            {
                var vel = ps.velocityOverLifetime;
                vel.enabled = true;
                vel.space = n.velInWorldSpace ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
                vel.x = n.velXCurve != null ? ToMinMaxCurve(n.velXCurve, n.velX) : new ParticleSystem.MinMaxCurve(n.velX);
                vel.y = n.velYCurve != null ? ToMinMaxCurve(n.velYCurve, n.velY) : new ParticleSystem.MinMaxCurve(n.velY);
                vel.z = n.velZCurve != null ? ToMinMaxCurve(n.velZCurve, n.velZ) : new ParticleSystem.MinMaxCurve(n.velZ);
                if (n.velOrbitalX != null) vel.orbitalX = ToMinMaxCurve(n.velOrbitalX, 0f);
                if (n.velOrbitalY != null) vel.orbitalY = ToMinMaxCurve(n.velOrbitalY, 0f);
                if (n.velOrbitalZ != null) vel.orbitalZ = ToMinMaxCurve(n.velOrbitalZ, 0f);
                if (n.velOrbitalOffsetX != null) vel.orbitalOffsetX = ToMinMaxCurve(n.velOrbitalOffsetX, 0f);
                if (n.velOrbitalOffsetY != null) vel.orbitalOffsetY = ToMinMaxCurve(n.velOrbitalOffsetY, 0f);
                if (n.velOrbitalOffsetZ != null) vel.orbitalOffsetZ = ToMinMaxCurve(n.velOrbitalOffsetZ, 0f);
                if (n.velRadial != null) vel.radial = ToMinMaxCurve(n.velRadial, 0f);
                if (n.velSpeedModifier != null) vel.speedModifier = ToMinMaxCurve(n.velSpeedModifier, 1f);
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
                    lim.limitX = ToMinMaxCurve(n.limitVelX, 1f);
                    lim.limitY = ToMinMaxCurve(n.limitVelY, 1f);
                    lim.limitZ = ToMinMaxCurve(n.limitVelZ, 1f);
                }
                else lim.limit = ToMinMaxCurve(n.limitVel, 1f);
                if (n.limitVelDrag != null) lim.drag = ToMinMaxCurve(n.limitVelDrag, 0f);
            }
            bool hasRotZ = (n.rotOverLifeCurve != null && (n.rotOverLifeCurve.keys?.Length > 0 || n.rotOverLifeCurve.mode == 3)) ||
                Mathf.Abs(n.rotOverLife) > 1e-4f;
            if (n.rotOverLifeEnabled && (n.rotOverLifeSeparateAxes || hasRotZ))
            {
                var rot = ps.rotationOverLifetime;
                rot.enabled = true;
                if (n.rotOverLifeSeparateAxes)
                {
                    rot.separateAxes = true;
                    rot.x = ToMinMaxCurve(n.rotOverLifeX, 0f);
                    rot.y = ToMinMaxCurve(n.rotOverLifeY, 0f);
                    rot.z = n.rotOverLifeCurve != null ? ToMinMaxCurve(n.rotOverLifeCurve, n.rotOverLife) : new ParticleSystem.MinMaxCurve(n.rotOverLife);
                }
                else rot.z = n.rotOverLifeCurve != null ? ToMinMaxCurve(n.rotOverLifeCurve, n.rotOverLife) : new ParticleSystem.MinMaxCurve(n.rotOverLife);
            }
            if (n.noiseEnabled)
            {
                var noise = ps.noise;
                noise.enabled = true;
                noise.separateAxes = n.noiseSeparateAxes;
                if (n.noiseSeparateAxes)
                {
                    noise.strengthX = (HasCurveData(n.noiseStrengthCurve) || HasNonZeroCurve(n.noiseStrengthCurve))
                        ? ToMinMaxCurve(n.noiseStrengthCurve, n.noiseStrength)
                        : new ParticleSystem.MinMaxCurve(n.noiseStrength);
                    noise.strengthY = ToMinMaxCurve(n.noiseStrengthYCurve, 0f);
                    noise.strengthZ = ToMinMaxCurve(n.noiseStrengthZCurve, 0f);
                }
                else
                {
                    noise.strength = (HasCurveData(n.noiseStrengthCurve) || HasNonZeroCurve(n.noiseStrengthCurve))
                        ? ToMinMaxCurve(n.noiseStrengthCurve, n.noiseStrength)
                        : new ParticleSystem.MinMaxCurve(n.noiseStrength);
                }
                noise.frequency = Mathf.Max(0.001f, n.noiseFrequency);
                noise.scrollSpeed = (HasCurveData(n.noiseScrollSpeedCurve) || HasNonZeroCurve(n.noiseScrollSpeedCurve))
                    ? ToMinMaxCurve(n.noiseScrollSpeedCurve, n.noiseScrollSpeed)
                    : new ParticleSystem.MinMaxCurve(n.noiseScrollSpeed);
                noise.damping = n.noiseDamping;
                noise.octaveCount = Mathf.Clamp(n.noiseOctaves > 0 ? n.noiseOctaves : 1, 1, 4);
                noise.octaveMultiplier = n.noiseOctaveMultiplier;
                noise.octaveScale = Mathf.Max(0.01f, n.noiseOctaveScale);
                noise.quality = (ParticleSystemNoiseQuality)Mathf.Clamp(n.noiseQuality, 0, 2);
                if (HasNonZeroCurve(n.noisePosAmountCurve) || HasCurveData(n.noisePosAmountCurve) ||
                    HasNonZeroCurve(n.noiseRotAmountCurve) || HasCurveData(n.noiseRotAmountCurve) ||
                    HasNonZeroCurve(n.noiseSizeAmountCurve) || HasCurveData(n.noiseSizeAmountCurve))
                {
                    noise.positionAmount = ToMinMaxCurve(n.noisePosAmountCurve, 1f);
                    noise.rotationAmount = ToMinMaxCurve(n.noiseRotAmountCurve, 0f);
                    noise.sizeAmount = ToMinMaxCurve(n.noiseSizeAmountCurve, 0f);
                }
            }
            if (n.forceEnabled)
            {
                var force = ps.forceOverLifetime;
                force.enabled = true;
                force.space = n.forceInWorldSpace ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
                force.randomized = n.forceRandomized;
                force.x = (HasCurveData(n.forceXCurve) || HasNonZeroCurve(n.forceXCurve)) ? ToMinMaxCurve(n.forceXCurve, n.forceX) : new ParticleSystem.MinMaxCurve(n.forceX);
                force.y = (HasCurveData(n.forceYCurve) || HasNonZeroCurve(n.forceYCurve)) ? ToMinMaxCurve(n.forceYCurve, n.forceY) : new ParticleSystem.MinMaxCurve(n.forceY);
                force.z = (HasCurveData(n.forceZCurve) || HasNonZeroCurve(n.forceZCurve)) ? ToMinMaxCurve(n.forceZCurve, n.forceZ) : new ParticleSystem.MinMaxCurve(n.forceZ);
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
                    rbs.x = ToMinMaxCurve(n.rotBySpeedX, 0f);
                    rbs.y = ToMinMaxCurve(n.rotBySpeedY, 0f);
                    rbs.z = ToMinMaxCurve(n.rotBySpeedCurve, 0f);
                }
                else rbs.z = ToMinMaxCurve(n.rotBySpeedCurve, 0f);
            }
            if (n.customDataEnabled)
            {
                var cd = ps.customData;
                cd.enabled = true;
                cd.SetMode(ParticleSystemCustomData.Custom1, ParticleSystemCustomDataMode.Vector);
                cd.SetVectorComponentCount(ParticleSystemCustomData.Custom1, 4);
                if (n.custom1X != null) cd.SetVector(ParticleSystemCustomData.Custom1, 0, ToMinMaxCurve(n.custom1X, 0f));
                if (n.custom1Y != null) cd.SetVector(ParticleSystemCustomData.Custom1, 1, ToMinMaxCurve(n.custom1Y, 0f));
                if (n.custom1Z != null) cd.SetVector(ParticleSystemCustomData.Custom1, 2, ToMinMaxCurve(n.custom1Z, 0f));
                if (n.custom1W != null) cd.SetVector(ParticleSystemCustomData.Custom1, 3, ToMinMaxCurve(n.custom1W, 0f));
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
                    ts.frameOverTime = new ParticleSystem.MinMaxCurve(Mathf.Approximately(n.uvFrameScalar, 0f) ? 1f : n.uvFrameScalar, new AnimationCurve(kfs));
                }
                else if (n.uvFrameMode == 0)
                    ts.frameOverTime = new ParticleSystem.MinMaxCurve(n.uvFrameScalar);
                else
                    ts.frameOverTime = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 0f, 1f, 0.9999f));
            }

            if (registerRendering)
            {
                int rm = Mathf.Clamp(n.renderMode, 0, 5);
                bool mainActive = n.hasMainMaterial && rm != 5;
                Material mainMat = null;
                if (mainActive)
                {
                    mainMat = CreateNodeMaterial(
                        n.isAdditive, n.tint, n.tintMultiplier,
                        n.texName, n.texScale, n.texOffset, n.texWrap,
                        n.maskTexName, n.maskScale, n.maskOffset, n.maskWrap,
                        n.mask2TexName, n.mask2Scale, n.mask2Offset, n.mask2Wrap,
                        n.dissolveTexName, n.dissolveScale, n.dissolveOffset, n.dissolve, n.dissolveSoft,
                        n.distortTexName, n.distortScale, n.distortOffset, n.distortStrength,
                        n.uvScroll, n.customDataEnabled, n.customDataMode, periodicLoopT,
                        texCache, addShader, addMaskShader, alphaShader,
                        createdMats, uvEntries
                    );
                    psr.sharedMaterial = mainMat;
                }
                else psr.sharedMaterial = null;

                if (!mainActive) psr.renderMode = ParticleSystemRenderMode.None;
                else if (rm == 4)
                {
                    psr.renderMode = ParticleSystemRenderMode.Mesh;
                    Mesh chosenMesh = (!string.IsNullOrEmpty(n.meshName) && meshCache.TryGetValue(n.meshName, out Mesh cm) && cm != null)
                        ? cm : quadMesh;
                    psr.mesh = chosenMesh;
                }
                else psr.renderMode = (ParticleSystemRenderMode)rm;

                psr.alignment = (ParticleSystemRenderSpace)Mathf.Clamp(n.renderAlignment, 0, 4);
                psr.maxParticleSize = n.maxParticleSize > 0.001f ? n.maxParticleSize : 0.5f;
                if (rm == 1)
                {
                    psr.velocityScale = n.velocityScale;
                    psr.lengthScale = n.lengthScale;
                }
                if (n.pivot != null && n.pivot.Length >= 3)
                    psr.pivot = new Vector3(n.pivot[0], n.pivot[1], n.pivot[2]);
                if (n.flip != null && n.flip.Length >= 3)
                    psr.flip = new Vector3(n.flip[0], n.flip[1], n.flip[2]);
                // Keep monotone sortingOrder per clone so oldest/newest alpha overlap stays bit-identical across wrap!
                psr.sortingOrder = n.effSortOrder * 100 + (n.sortOrder % 50) + sortOrderOffset;
                if (n.customDataEnabled)
                {
                    // UV (TEXCOORD0.xy) + UV2 (TEXCOORD0.zw) + Custom1XYZW (TEXCOORD1.xyzw) matches official Unity/SoulTide layout!
                    psr.SetActiveVertexStreams(new List<ParticleSystemVertexStream>
                    {
                        ParticleSystemVertexStream.Position,
                        ParticleSystemVertexStream.Normal,
                        ParticleSystemVertexStream.Color,
                        ParticleSystemVertexStream.UV,
                        ParticleSystemVertexStream.UV2,
                        ParticleSystemVertexStream.Custom1XYZW,
                    });
                }

                Material trailMat = null;
                bool trailActive = n.trailsEnabled && n.hasTrailMaterial;
                if (trailActive)
                {
                    trailMat = CreateNodeMaterial(
                        n.trailIsAdditive, n.trailTint, n.trailTintMultiplier,
                        n.trailTexName, n.trailTexScale, n.trailTexOffset, n.trailTexWrap,
                        n.trailMaskTexName, n.trailMaskScale, n.trailMaskOffset, n.trailMaskWrap,
                        n.trailMask2TexName, n.trailMask2Scale, n.trailMask2Offset, n.trailMask2Wrap,
                        n.trailDissolveTexName, n.trailDissolveScale, n.trailDissolveOffset, n.trailDissolve, n.trailDissolveSoft,
                        n.trailDistortTexName, n.trailDistortScale, n.trailDistortOffset, n.trailDistortStrength,
                        n.trailUvScroll, false, 0, periodicLoopT,
                        texCache, addShader, addMaskShader, alphaShader,
                        createdMats, uvEntries
                    );
                    var tr = ps.trails;
                    tr.enabled = true;
                    tr.mode = (ParticleSystemTrailMode)Mathf.Clamp(n.trailMode, 0, 1);
                    tr.ratio = Mathf.Clamp01(n.trailRatio);
                    tr.lifetime = ToMinMaxCurve(n.trailLifetime, 0.5f);
                    tr.minVertexDistance = Mathf.Max(0f, n.trailMinVertexDist);
                    tr.worldSpace = n.trailWorldSpace;
                    tr.dieWithParticles = n.trailDieWithParticles;
                    tr.sizeAffectsWidth = n.trailSizeAffectsWidth;
                    tr.sizeAffectsLifetime = n.trailSizeAffectsLifetime;
                    tr.inheritParticleColor = n.trailInheritColor;
                    tr.textureMode = (ParticleSystemTrailTextureMode)Mathf.Clamp(n.trailTextureMode, 0, 3);
                    tr.ribbonCount = Mathf.Max(1, n.trailRibbonCount);
                    if (n.trailWidthOverTrail != null) tr.widthOverTrail = ToMinMaxCurve(n.trailWidthOverTrail, 1f);
                    if (n.trailColorOverLifetime != null && (n.trailColorOverLifetime.ckeys?.Length > 0 || n.trailColorOverLifetime.akeys?.Length > 0))
                        tr.colorOverLifetime = new ParticleSystem.MinMaxGradient(BuildGradient(n.trailColorOverLifetime));
                    if (n.trailColorOverTrail != null && (n.trailColorOverTrail.ckeys?.Length > 0 || n.trailColorOverTrail.akeys?.Length > 0))
                        tr.colorOverTrail = new ParticleSystem.MinMaxGradient(BuildGradient(n.trailColorOverTrail));
                    psr.trailMaterial = trailMat;
                }

                if (mainActive || trailActive)
                {
                    bool mainNorm = mainActive && !n.isAdditive;
                    bool mainAdd = mainActive && n.isAdditive;
                    bool trailNorm = trailActive && !n.trailIsAdditive;
                    bool trailAdd = trailActive && n.trailIsAdditive;
                    bool needsNorm = mainNorm || trailNorm;
                    bool needsAdd = mainAdd || trailAdd;
                    if (needsNorm) anyNormal = true;
                    if (needsAdd) anyAdditive = true;
                    passItems.Add(new RenderPassItem
                    {
                        psr = psr,
                        mainMat = mainMat,
                        trailMat = trailMat,
                        mainNorm = mainNorm,
                        mainAdd = mainAdd,
                        trailNorm = trailNorm,
                        trailAdd = trailAdd,
                        isMixed = needsNorm && needsAdd,
                    });
                }
                else psr.enabled = false;
            }
            else
            {
                psr.enabled = false;
            }

            idxToGo[ni] = go;
            idxToPs[ni] = ps;
        }

        // Wire SubEmitters within this tree instance
        for (int ti = 0; ti < treeIndices.Count; ti++)
        {
            int ni = treeIndices[ti];
            FxNodeDto n = clipNodes[ni];
            if (n == null || n.subEmitters == null || n.subEmitters.Length == 0) continue;
            if (!idxToPs.TryGetValue(ni, out ParticleSystem parentPs)) continue;
            var sub = parentPs.subEmitters;
            bool addedAny = false;
            for (int si = 0; si < n.subEmitters.Length; si++)
            {
                var se = n.subEmitters[si];
                if (!idxToPs.TryGetValue(se.targetIdx, out ParticleSystem childPs)) continue;
                if (!idxToGo.TryGetValue(se.targetIdx, out GameObject childGo)) continue;
                if (childPs == parentPs) continue;
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

        return idxToPs.TryGetValue(rootNodeIdx, out ParticleSystem rps) ? rps : null;
    }

    private static int[] ProbeSaturatedEmitSchedule(
        FxNodeDto[] clipNodes,
        List<int> treeIndices,
        uint seedBase,
        float warmSec,
        int stepsPerPeriod,
        float subDt,
        Dictionary<string, Mesh> meshCache,
        Mesh quadMesh,
        Dictionary<string, Texture2D> texCache,
        Shader addShader,
        Shader addMaskShader,
        Shader alphaShader
    )
    {
        GameObject probeRoot = new GameObject("ProbeSaturated");
        var dummyMats = new List<Material>();
        var dummyUv = new List<UvScrollEntry>();
        var dummyPass = new List<RenderPassItem>();
        bool dN = false, dA = false;
        int[] schedule = new int[stepsPerPeriod];
        try
        {
            ParticleSystem ps = BuildTreeInstance(
                probeRoot.transform, clipNodes, treeIndices, seedBase, 0,
                disableRootEmissionForManualReplay: false, minMaxParticlesOverride: 0,
                rootSimSpeedMultiplier: 1f, periodicLoopT: 0f,
                meshCache, quadMesh, texCache, addShader, addMaskShader, alphaShader,
                dummyMats, dummyUv, dummyPass, ref dN, ref dA, registerRendering: false
            );
            if (ps == null) return schedule;
            int warmTicks = Mathf.Max(1, Mathf.RoundToInt(warmSec / subDt));
            for (int w = 0; w < warmTicks; w++)
                ps.Simulate(subDt, true, w == 0, false);

            var buf = new ParticleSystem.Particle[2048];
            var lastRemBySeed = new Dictionary<uint, float>();
            int cnt0 = ps.GetParticles(buf);
            for (int i = 0; i < cnt0; i++)
                lastRemBySeed[buf[i].randomSeed] = buf[i].remainingLifetime;

            var seenNow = new HashSet<uint>();
            int totalBirths = 0;
            void RecordOnePeriod(bool accumulate)
            {
                for (int tick = 0; tick < stepsPerPeriod; tick++)
                {
                    ps.Simulate(subDt, true, false, false);
                    int cnt = ps.GetParticles(buf);
                    seenNow.Clear();
                    int births = 0;
                    for (int i = 0; i < cnt; i++)
                    {
                        uint s = buf[i].randomSeed;
                        float rem = buf[i].remainingLifetime;
                        seenNow.Add(s);
                        if (!lastRemBySeed.TryGetValue(s, out float prevRem) || rem > prevRem + 0.02f)
                            births++;
                        lastRemBySeed[s] = rem;
                    }
                    // Remove dead seeds so a reused seed is detected cleanly
                    var dead = new List<uint>();
                    foreach (var kv in lastRemBySeed)
                        if (!seenNow.Contains(kv.Key)) dead.Add(kv.Key);
                    for (int i = 0; i < dead.Count; i++) lastRemBySeed.Remove(dead[i]);
                    if (accumulate) schedule[tick] += births;
                    else schedule[tick] = births;
                    totalBirths += births;
                }
            }
            RecordOnePeriod(accumulate: false);
            // If lifetime > T and warmProbe landed mid-life (0 births in 1 period), probe extra periods
            // until at least 1 birth is captured so sparse saturated trees (e.g. hudie lt=12s in T=6s) never go blank!
            int extraTries = 0;
            while (totalBirths == 0 && extraTries < 5)
            {
                RecordOnePeriod(accumulate: true);
                extraTries++;
            }
            if (totalBirths == 0)
            {
                var rn0 = clipNodes[treeIndices[0]];
                schedule[0] = Mathf.Clamp(rn0 != null && rn0.maxParticles > 0 ? rn0.maxParticles : 1, 1, 16);
            }
        }
        finally
        {
            foreach (var m in dummyMats) UnityEngine.Object.DestroyImmediate(m);
            UnityEngine.Object.DestroyImmediate(probeRoot);
        }
        return schedule;
    }

    private static void UpdatePeriodicShaders(List<Material> mats, List<UvScrollEntry> uvEntries, float simTime)
    {
        for (int mi = 0; mi < mats.Count; mi++)
        {
            var m = mats[mi];
            if (m != null && m.HasProperty("_FlowClock"))
                m.SetFloat("_FlowClock", simTime);
        }
        for (int ui = 0; ui < uvEntries.Count; ui++)
        {
            var uv = uvEntries[ui];
            float ox = uv.wobbleU
                ? uv.u * (uv.periodT / (2f * Mathf.PI)) * Mathf.Sin(2f * Mathf.PI * simTime / Mathf.Max(0.01f, uv.periodT))
                : uv.u * simTime;
            float oy = uv.wobbleV
                ? uv.v * (uv.periodT / (2f * Mathf.PI)) * Mathf.Sin(2f * Mathf.PI * simTime / Mathf.Max(0.01f, uv.periodT))
                : uv.v * simTime;
            uv.mat.SetTextureOffset(uv.prop, uv.baseOffset + new Vector2(ox, oy));
        }
    }

    private static int CaptureClip(
        string skinOutDir,
        FxClipDto clip,
        Camera cam,
        RenderTexture rt,
        Texture2D texBuf,
        Shader addShader,
        Shader addMaskShader,
        Shader alphaShader,
        Mesh quadMesh,
        Dictionary<string, Mesh> meshCache,
        Dictionary<string, Texture2D> texCache,
        float fps
    )
    {
        GameObject root = new GameObject("Root_" + clip.clip);
        var createdMats = new List<Material>();
        var uvEntries = new List<UvScrollEntry>();
        var passItems = new List<RenderPassItem>();
        bool anyNormal = false;
        bool anyAdditive = false;
        Material invisibleAlphaMat = new Material(alphaShader);
        invisibleAlphaMat.SetColor("_TintColor", new Color(0f, 0f, 0f, 0f));
        createdMats.Add(invisibleAlphaMat);
        Material invisibleAddMat = new Material(addMaskShader);
        invisibleAddMat.SetColor("_TintColor", new Color(0f, 0f, 0f, 0f));
        createdMats.Add(invisibleAddMat);

        // Group nodes into root trees (root node + its subEmitter descendants)
        var trees = new List<List<int>>();
        for (int ni = 0; ni < clip.nodes.Length; ni++)
        {
            var n = clip.nodes[ni];
            if (n == null || n.isSubEmitterChild) continue;
            var tList = new List<int>();
            CollectTreeIndices(clip.nodes, ni, tList, new HashSet<int>());
            if (tList.Count > 0) trees.Add(tList);
        }

        float T = Mathf.Max(0.25f, clip.duration);
        int outFrames = Mathf.Max(1, Mathf.RoundToInt(T * fps));
        float stepDt = T / outFrames;

        if (clip.useZeroCrossfade)
        {
            // Exact integer ticks per period guarantees BIT-EXACT State(T) == State(0) across clones!
            int subSteps = Mathf.Max(1, Mathf.CeilToInt(stepDt / (1f / 60f)));
            int stepsPerPeriod = outFrames * subSteps;
            float subDt = T / stepsPerPeriod;

            var persistentSystems = new List<ParticleSystem>();
            var clonePlan = new List<(List<int> tree, uint seed, int K, int[] emitSchedule, int minMaxP, float spdMul)>();
            int KGlobal = 1;
            uint seedBase = 1001u;

            for (int ti = 0; ti < trees.Count; ti++)
            {
                var tree = trees[ti];
                var rn = clip.nodes[tree[0]];
                uint treeSeed = seedBase + (uint)(ti * 37);
                float simSpd = rn.simulationSpeed > 0.001f ? rn.simulationSpeed : 1f;
                float ltHi = GetCurveMax(rn.lifetime, 1f) / simSpd;
                bool isPersistent = (rn.ringBufferMode != 0 || ltHi >= 99f);
                bool hasMod = HasLifetimeModulation(rn);

                if (isPersistent)
                {
                    int pMaxP = rn.maxParticles > 0 ? rn.maxParticles : 50;
                    bool staticRb = (rn.ringBufferMode == 2 && !hasMod && pMaxP <= 4 && tree.Count == 1);
                    float spdMul = 1f;
                    if (!staticRb && rn.ringBufferMode == 2 && ltHi < 99f && hasMod)
                    {
                        float r0 = (rn.ringBufferLoopRange != null && rn.ringBufferLoopRange.Length >= 2) ? rn.ringBufferLoopRange[0] : 0f;
                        float r1 = (rn.ringBufferLoopRange != null && rn.ringBufferLoopRange.Length >= 2) ? rn.ringBufferLoopRange[1] : 1f;
                        float prb = ltHi * Mathf.Max(0.05f, r1 - r0);
                        if (prb >= 0.25f && prb <= T * 2.5f)
                        {
                            int kCyc = Mathf.Max(1, Mathf.RoundToInt(T / prb));
                            float targetPrb = T / kCyc;
                            spdMul = Mathf.Clamp(prb / targetPrb, 0.55f, 2.5f);
                        }
                    }
                    ParticleSystem pps = BuildTreeInstance(
                        root.transform, clip.nodes, tree, treeSeed, 0,
                        disableRootEmissionForManualReplay: false, minMaxParticlesOverride: 0,
                        rootSimSpeedMultiplier: spdMul, periodicLoopT: T,
                        meshCache, quadMesh, texCache, addShader, addMaskShader, alphaShader,
                        createdMats, uvEntries, passItems, ref anyNormal, ref anyAdditive,
                        registerRendering: true, forceStaticRingBufferLoop: staticRb
                    );
                    if (pps != null) persistentSystems.Add(pps);
                }
                else
                {
                    float lTree = EstimateTreeMaxLife(clip.nodes, tree);
                    float rateEff = Mathf.Max(rn.rate, GetCurveMax(rn.rateCurve, rn.rate)) * simSpd;
                    int maxP = rn.maxParticles > 0 ? rn.maxParticles : 50;
                    bool isSaturated = (rateEff * ltHi > maxP * 1.05f && maxP >= 1);
                    bool isEternalInstant = isSaturated
                        && tree.Count == 1
                        && rn.looping
                        && maxP <= 4
                        && IsDeterministicLifetime(rn.lifetime)
                        && (rateEff >= 50f || (maxP == 1 && !HasSpatialMotion(rn) && ltHi >= T * 0.6f));

                    if (isEternalInstant && !hasMod)
                    {
                        // Subcase A: static/UV-scrolling carrier quad (cloud01/02, hailang, water, smoke, deng, etc.)
                        // Emit maxP once and keep alive forever via LoopUntilReplaced -> zero blank frames, 100% steady alpha!
                        ParticleSystem pps = BuildTreeInstance(
                            root.transform, clip.nodes, tree, treeSeed, 0,
                            disableRootEmissionForManualReplay: false, minMaxParticlesOverride: 0,
                            rootSimSpeedMultiplier: 1f, periodicLoopT: T,
                            meshCache, quadMesh, texCache, addShader, addMaskShader, alphaShader,
                            createdMats, uvEntries, passItems, ref anyNormal, ref anyAdditive,
                            registerRendering: true, forceStaticRingBufferLoop: true
                        );
                        if (pps != null) persistentSystems.Add(pps);
                    }
                    else if (isEternalInstant)
                    {
                        // Subcase B: deterministic pulsing/flipbook/rotating/CustomData instant-respawn node
                        // Shorten targetLt by 1.5*subDt so Clone 0's last particle dies cleanly on tick capStartTick-1
                        // (after N-1 Unity integrations) right before Clone 1 emits at f=0, preventing f=0 double-alpha!
                        int kCyc = Mathf.Max(1, Mathf.RoundToInt(T / Mathf.Max(0.25f, ltHi)));
                        float targetLt = T / kCyc;
                        float spdMul = Mathf.Clamp(ltHi / Mathf.Max(0.05f, targetLt - 1.5f * subDt), 0.4f, 2.5f);
                        int[] sched = new int[stepsPerPeriod];
                        int phaseTicks = (rn.startDelay > 0.001f)
                            ? (Mathf.RoundToInt((rn.startDelay % T) / subDt) % stepsPerPeriod)
                            : 0;
                        for (int k = 0; k < kCyc; k++)
                        {
                            int tk = (phaseTicks + Mathf.RoundToInt((float)k * stepsPerPeriod / kCyc)) % stepsPerPeriod;
                            sched[tk] += maxP;
                        }
                        int K = 2;
                        KGlobal = Mathf.Max(KGlobal, K);
                        int minMaxP = Mathf.Clamp(maxP * 4, 16, 2000);
                        clonePlan.Add((tree, treeSeed, K, sched, minMaxP, spdMul));
                    }
                    else
                    {
                        int K = Mathf.Clamp(Mathf.CeilToInt(lTree / T) + 1, 2, 12);
                        KGlobal = Mathf.Max(KGlobal, K);
                        int[] sched = null;
                        int minMaxP = 0;
                        if (isSaturated)
                        {
                            float warmProbe = Mathf.Clamp(lTree + 2f, 4f, 45f);
                            sched = ProbeSaturatedEmitSchedule(
                                clip.nodes, tree, treeSeed, warmProbe, stepsPerPeriod, subDt,
                                meshCache, quadMesh, texCache, addShader, addMaskShader, alphaShader
                            );
                            minMaxP = Mathf.Clamp(maxP * 4, 32, 2000);
                        }
                        clonePlan.Add((tree, treeSeed, K, sched, minMaxP, 1f));
                    }
                }
            }

            // Instantiate K identical clones per finite tree with exact staggered start ticks!
            int capStartTick = (KGlobal - 1) * stepsPerPeriod;
            var runners = new List<CloneRunner>();
            for (int pi = 0; pi < clonePlan.Count; pi++)
            {
                var cp = clonePlan[pi];
                // Clone c=0..K-1 covers [capStartTick - (K-1)*stepsPerPeriod .. capStartTick + stepsPerPeriod)
                for (int c = 0; c < cp.K; c++)
                {
                    int stTick = capStartTick - (cp.K - 1 - c) * stepsPerPeriod;
                    ParticleSystem cps = BuildTreeInstance(
                        root.transform, clip.nodes, cp.tree, cp.seed, sortOrderOffset: c,
                        disableRootEmissionForManualReplay: (cp.emitSchedule != null),
                        minMaxParticlesOverride: cp.minMaxP,
                        rootSimSpeedMultiplier: cp.spdMul, periodicLoopT: T,
                        meshCache, quadMesh, texCache, addShader, addMaskShader, alphaShader,
                        createdMats, uvEntries, passItems, ref anyNormal, ref anyAdditive, registerRendering: true
                    );
                    if (cps != null)
                    {
                        runners.Add(new CloneRunner
                        {
                            rootPs = cps,
                            startTick = stTick,
                            stopTick = stTick + stepsPerPeriod,
                            emitSchedule = cp.emitSchedule,
                            started = false,
                            stopped = false,
                            emittedTick0 = false,
                        });
                    }
                }
            }

            string normDir = Path.Combine(skinOutDir, clip.clip, "normal");
            string addDir = Path.Combine(skinOutDir, clip.clip, "add");
            if (anyNormal) Directory.CreateDirectory(normDir);
            if (anyAdditive) Directory.CreateDirectory(addDir);

            try
            {
                cam.targetTexture = rt;
                cam.clearFlags = CameraClearFlags.SolidColor;

                // Warm up persistent systems for an exact integer multiple of T so rbm=2 phase aligns cleanly!
                if (persistentSystems.Count > 0)
                {
                    int persCycles = Mathf.Max(1, Mathf.CeilToInt(Mathf.Clamp(clip.warmup, 4f, 12f) / T));
                    int persWarmTicks = persCycles * stepsPerPeriod;
                    for (int w = 0; w < persWarmTicks; w++)
                        for (int i = 0; i < persistentSystems.Count; i++)
                            persistentSystems[i].Simulate(subDt, true, w == 0, false);
                }

                // Advance finite clones from tick 0 .. capStartTick - 1
                void StepAllRunnersAtTick(int tick, bool advancePersistent)
                {
                    if (advancePersistent)
                    {
                        for (int i = 0; i < persistentSystems.Count; i++)
                            persistentSystems[i].Simulate(subDt, true, false, false);
                    }
                    for (int ri = 0; ri < runners.Count; ri++)
                    {
                        var r = runners[ri];
                        if (tick < r.startTick) continue;
                        int localTick = tick - r.startTick;
                        if (!r.started)
                        {
                            r.rootPs.Simulate(0f, true, true, false);
                            r.started = true;
                        }
                        if (r.emitSchedule != null)
                        {
                            if (localTick == 0 && r.emittedTick0)
                            {
                                r.emittedTick0 = false;
                            }
                            else if (localTick >= 0 && localTick < r.emitSchedule.Length && r.emitSchedule[localTick] > 0)
                            {
                                r.rootPs.Emit(r.emitSchedule[localTick]);
                            }
                        }
                        else if (!r.stopped && tick >= r.stopTick)
                        {
                            var em = r.rootPs.emission;
                            em.enabled = false;
                            r.stopped = true;
                        }
                        r.rootPs.Simulate(subDt, true, false, false);
                    }
                }

                for (int tick = 0; tick < capStartTick; tick++)
                    StepAllRunnersAtTick(tick, advancePersistent: false);

                // Capture outFrames [0 .. outFrames-1] with ZERO crossfade!
                for (int f = 0; f < outFrames; f++)
                {
                    if (f > 0)
                    {
                        int baseTick = capStartTick + (f - 1) * subSteps;
                        for (int s = 0; s < subSteps; s++)
                            StepAllRunnersAtTick(baseTick + s, advancePersistent: true);
                    }
                    else
                    {
                        // Initialize any clone starting exactly at capStartTick (localTick=0) so bursts AND schedule[0] appear at f=0!
                        for (int ri = 0; ri < runners.Count; ri++)
                        {
                            var r = runners[ri];
                            if (r.startTick == capStartTick && !r.started)
                            {
                                r.rootPs.Simulate(0f, true, true, false);
                                if (r.emitSchedule != null && r.emitSchedule.Length > 0 && r.emitSchedule[0] > 0)
                                {
                                    r.rootPs.Emit(r.emitSchedule[0]);
                                    r.rootPs.Simulate(0f, true, false, false);
                                    r.emittedTick0 = true;
                                }
                                r.started = true;
                            }
                        }
                    }

                    float simTime = f * stepDt;
                    UpdatePeriodicShaders(createdMats, uvEntries, simTime);

                    if (anyNormal)
                    {
                        ApplyRenderPass(passItems, isAddPass: false, invisibleAlphaMat, invisibleAddMat);
                        cam.backgroundColor = new Color(0f, 0f, 0f, 0f);
                        cam.Render();
                        SaveRtPng(rt, texBuf, Path.Combine(normDir, $"frame_{f:D4}.png"), extractMaxAlpha: false);
                    }
                    if (anyAdditive)
                    {
                        ApplyRenderPass(passItems, isAddPass: true, invisibleAlphaMat, invisibleAddMat);
                        cam.backgroundColor = new Color(0f, 0f, 0f, 1f);
                        cam.Render();
                        SaveRtPng(rt, texBuf, Path.Combine(addDir, $"frame_{f:D4}.png"), extractMaxAlpha: true);
                    }
                }
            }
            finally
            {
                foreach (var m in createdMats) UnityEngine.Object.DestroyImmediate(m);
                UnityEngine.Object.DestroyImmediate(root);
            }
            return outFrames;
        }

        // Legacy / One-Shot Trigger FX path (fx_9008xxx, crossfadeIdle=false)
        var rootSystems = new List<ParticleSystem>();
        uint legacySeed = 1001u;
        for (int ti = 0; ti < trees.Count; ti++)
        {
            ParticleSystem ps = BuildTreeInstance(
                root.transform, clip.nodes, trees[ti], legacySeed + (uint)(ti * 37), 0,
                disableRootEmissionForManualReplay: false, minMaxParticlesOverride: 0,
                rootSimSpeedMultiplier: 1f, periodicLoopT: 0f,
                meshCache, quadMesh, texCache, addShader, addMaskShader, alphaShader,
                createdMats, uvEntries, passItems, ref anyNormal, ref anyAdditive, registerRendering: true
            );
            if (ps != null) rootSystems.Add(ps);
        }

        string normDirL = Path.Combine(skinOutDir, clip.clip, "normal");
        string addDirL = Path.Combine(skinOutDir, clip.clip, "add");
        if (anyNormal) Directory.CreateDirectory(normDirL);
        if (anyAdditive) Directory.CreateDirectory(addDirL);

        int blendFrames = 0;
        if (clip.crossfadeIdle && outFrames >= 4)
        {
            float bd = clip.blendDuration > 0.05f ? clip.blendDuration : clip.duration;
            blendFrames = Mathf.Clamp(Mathf.RoundToInt(bd * fps), 2, outFrames);
        }
        bool doXfade = blendFrames > 0;
        int simFrames = doXfade ? (outFrames + blendFrames) : outFrames;

        try
        {
            cam.targetTexture = rt;
            cam.clearFlags = CameraClearFlags.SolidColor;

            if (clip.warmup > 0f)
            {
                float warmDt = 1f / 30f;
                int warmSteps = Mathf.RoundToInt(clip.warmup / warmDt);
                for (int w = 0; w < warmSteps; w++)
                    foreach (var ps in rootSystems) ps.Simulate(warmDt, true, w == 0, false);
            }

            var normBufs = (doXfade && anyNormal) ? new Color32[simFrames][] : null;
            var addBufs = (doXfade && anyAdditive) ? new Color32[simFrames][] : null;

            for (int f = 0; f < simFrames; f++)
            {
                if (clip.warmup <= 0f)
                {
                    if (f == 0)
                        foreach (var ps in rootSystems) ps.Simulate(0f, true, true, false);
                    else
                        foreach (var ps in rootSystems) ps.Simulate(stepDt, true, false, false);
                }
                else if (f > 0)
                {
                    foreach (var ps in rootSystems) ps.Simulate(stepDt, true, false, false);
                }

                float simTime = (clip.warmup > 0f ? clip.warmup : 0f) + (f * stepDt);
                UpdatePeriodicShaders(createdMats, uvEntries, simTime);

                if (anyNormal)
                {
                    ApplyRenderPass(passItems, isAddPass: false, invisibleAlphaMat, invisibleAddMat);
                    cam.backgroundColor = new Color(0f, 0f, 0f, 0f);
                    cam.Render();
                    if (doXfade) normBufs[f] = CaptureRtPixels(rt, texBuf, extractMaxAlpha: false);
                    else SaveRtPng(rt, texBuf, Path.Combine(normDirL, $"frame_{f:D4}.png"), extractMaxAlpha: false);
                }
                if (anyAdditive)
                {
                    ApplyRenderPass(passItems, isAddPass: true, invisibleAlphaMat, invisibleAddMat);
                    cam.backgroundColor = new Color(0f, 0f, 0f, 1f);
                    cam.Render();
                    if (doXfade) addBufs[f] = CaptureRtPixels(rt, texBuf, extractMaxAlpha: true);
                    else SaveRtPng(rt, texBuf, Path.Combine(addDirL, $"frame_{f:D4}.png"), extractMaxAlpha: true);
                }
            }

            if (doXfade)
            {
                for (int i = 0; i < outFrames; i++)
                {
                    if (i < blendFrames)
                    {
                        float t = (float)i / (float)blendFrames;
                        float u = t * t * (3f - 2f * t);
                        if (normBufs != null) SaveBlendedPng(texBuf, normBufs[i + outFrames], normBufs[i], u, Path.Combine(normDirL, $"frame_{i:D4}.png"), isAdd: false);
                        if (addBufs != null) SaveBlendedPng(texBuf, addBufs[i + outFrames], addBufs[i], u, Path.Combine(addDirL, $"frame_{i:D4}.png"), isAdd: true);
                    }
                    else
                    {
                        if (normBufs != null) { texBuf.SetPixels32(normBufs[i]); texBuf.Apply(); File.WriteAllBytes(Path.Combine(normDirL, $"frame_{i:D4}.png"), texBuf.EncodeToPNG()); }
                        if (addBufs != null) { texBuf.SetPixels32(addBufs[i]); texBuf.Apply(); File.WriteAllBytes(Path.Combine(addDirL, $"frame_{i:D4}.png"), texBuf.EncodeToPNG()); }
                    }
                }
            }
        }
        finally
        {
            foreach (var m in createdMats) UnityEngine.Object.DestroyImmediate(m);
            UnityEngine.Object.DestroyImmediate(root);
        }
        return outFrames;
    }

    private static bool HasCurveData(MinMaxCurveDto c)
    {
        if (c == null) return false;
        if (c.mode == 3) return true;
        if ((c.mode == 1 || c.mode == 2) && c.keys != null && c.keys.Length > 0) return true;
        return false;
    }

    private static bool HasNonZeroCurve(MinMaxCurveDto c)
    {
        if (c == null) return false;
        if (Mathf.Abs(c.scalar) > 1e-4f) return true;
        if (c.mode == 3 && Mathf.Abs(c.minScalar) > 1e-4f) return true;
        return c.keys != null && c.keys.Length > 0;
    }

    private static Color32[] CaptureRtPixels(RenderTexture rt, Texture2D buf, bool extractMaxAlpha)
    {
        RenderTexture.active = rt;
        buf.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0);
        Color32[] px = buf.GetPixels32();
        if (extractMaxAlpha)
        {
            for (int i = 0; i < px.Length; i++)
                px[i].a = Math.Max(px[i].r, Math.Max(px[i].g, px[i].b));
        }
        return px;
    }

    private static void SaveBlendedPng(Texture2D buf, Color32[] tail, Color32[] head, float u, string path, bool isAdd)
    {
        float wTail = 1f - u;
        float wHead = u;
        int len = tail.Length;
        Color32[] dst = new Color32[len];
        for (int i = 0; i < len; i++)
        {
            Color32 t = tail[i];
            Color32 h = head[i];
            byte r = (byte)Mathf.Clamp(Mathf.RoundToInt(t.r * wTail + h.r * wHead), 0, 255);
            byte g = (byte)Mathf.Clamp(Mathf.RoundToInt(t.g * wTail + h.g * wHead), 0, 255);
            byte b = (byte)Mathf.Clamp(Mathf.RoundToInt(t.b * wTail + h.b * wHead), 0, 255);
            byte a = isAdd
                ? Math.Max(r, Math.Max(g, b))
                : (byte)Mathf.Clamp(Mathf.RoundToInt(t.a * wTail + h.a * wHead), 0, 255);
            dst[i] = new Color32(r, g, b, a);
        }
        buf.SetPixels32(dst);
        buf.Apply();
        File.WriteAllBytes(path, buf.EncodeToPNG());
    }

    private static void BindTexSlot(
        Material mat,
        string prop,
        string flowProp,
        string clampProp,
        string texName,
        float[] scale,
        float[] offset,
        int[] wrap,
        float scrollU,
        float scrollV,
        float periodicLoopT,
        Dictionary<string, Texture2D> texCache,
        List<UvScrollEntry> uvEntries
    )
    {
        Texture2D tex = null;
        if (!string.IsNullOrEmpty(texName))
        {
            if (texCache.TryGetValue(texName, out tex))
                mat.SetTexture(prop, tex);
            else if (prop == "_MainTex")
                Debug.LogWarning("[BatchFxRecorder] Missing texture: " + texName);
        }
        Vector2 sc = (scale != null && scale.Length >= 2) ? new Vector2(scale[0], scale[1]) : Vector2.one;
        Vector2 off = (offset != null && offset.Length >= 2) ? new Vector2(offset[0], offset[1]) : Vector2.zero;
        mat.SetTextureScale(prop, sc);
        mat.SetTextureOffset(prop, off);

        if (!string.IsNullOrEmpty(clampProp) && mat.HasProperty(clampProp))
        {
            float cu = (wrap != null && wrap.Length >= 1 && wrap[0] == 1) ? 1f : 0f;
            float cv = (wrap != null && wrap.Length >= 2 && wrap[1] == 1) ? 1f : 0f;
            if (tex != null)
            {
                if (tex.wrapModeU == TextureWrapMode.Clamp) cu = 1f;
                if (tex.wrapModeV == TextureWrapMode.Clamp) cv = 1f;
            }
            mat.SetVector(clampProp, new Vector4(cu, cv, 0f, 0f));
        }

        if (Mathf.Abs(scrollU) > 1e-5f || Mathf.Abs(scrollV) > 1e-5f)
        {
            if (periodicLoopT > 0.05f)
            {
                float absU = Mathf.Abs(scrollU) * periodicLoopT;
                float absV = Mathf.Abs(scrollV) * periodicLoopT;
                float maxCyc = Mathf.Max(absU, absV);
                if (maxCyc < 0.70f && !string.IsNullOrEmpty(flowProp) && mat.HasProperty(flowProp))
                {
                    // Ultra-slow UV scroll: variance-preserving C1 Dual-Phase Flow inside shader!
                    mat.SetVector(flowProp, new Vector4(scrollU, scrollV, periodicLoopT, 1f));
                }
                else
                {
                    bool wobU = (Mathf.Abs(scrollU) > 1e-5f && absU < 0.50f);
                    bool wobV = (Mathf.Abs(scrollV) > 1e-5f && absV < 0.50f);
                    float effU = (!wobU && Mathf.Abs(scrollU) > 1e-5f)
                        ? (Mathf.Max(1f, Mathf.Round(absU)) * Mathf.Sign(scrollU) / periodicLoopT)
                        : scrollU;
                    float effV = (!wobV && Mathf.Abs(scrollV) > 1e-5f)
                        ? (Mathf.Max(1f, Mathf.Round(absV)) * Mathf.Sign(scrollV) / periodicLoopT)
                        : scrollV;
                    uvEntries.Add(new UvScrollEntry
                    {
                        mat = mat,
                        prop = prop,
                        baseOffset = off,
                        u = effU,
                        v = effV,
                        wobbleU = wobU,
                        wobbleV = wobV,
                        periodT = periodicLoopT,
                    });
                }
            }
            else
            {
                uvEntries.Add(new UvScrollEntry
                {
                    mat = mat,
                    prop = prop,
                    baseOffset = off,
                    u = scrollU,
                    v = scrollV,
                    wobbleU = false,
                    wobbleV = false,
                    periodT = 0f,
                });
            }
        }
    }

    private static bool HasClampWrap(int[] w)
    {
        return w != null && ((w.Length >= 1 && w[0] == 1) || (w.Length >= 2 && w[1] == 1));
    }

    private static Material CreateNodeMaterial(
        bool isAdditive,
        ColorDto tintDto,
        float tintMultiplier,
        string texName, float[] texScale, float[] texOffset, int[] texWrap,
        string maskTexName, float[] maskScale, float[] maskOffset, int[] maskWrap,
        string mask2TexName, float[] mask2Scale, float[] mask2Offset, int[] mask2Wrap,
        string dissolveTexName, float[] dissolveScale, float[] dissolveOffset, float dissolve, float dissolveSoft,
        string distortTexName, float[] distortScale, float[] distortOffset, float distortStrength,
        float[] uvScroll,
        bool customDataEnabled,
        int customDataMode,
        float periodicLoopT,
        Dictionary<string, Texture2D> texCache,
        Shader addShader,
        Shader addMaskShader,
        Shader alphaShader,
        List<Material> createdMats,
        List<UvScrollEntry> uvEntries
    )
    {
        float su0 = (uvScroll != null && uvScroll.Length >= 2) ? uvScroll[0] : 0f;
        float sv0 = (uvScroll != null && uvScroll.Length >= 2) ? uvScroll[1] : 0f;
        float su1 = (uvScroll != null && uvScroll.Length >= 4) ? uvScroll[2] : 0f;
        float sv1 = (uvScroll != null && uvScroll.Length >= 4) ? uvScroll[3] : 0f;
        float su2 = (uvScroll != null && uvScroll.Length >= 6) ? uvScroll[4] : 0f;
        float sv2 = (uvScroll != null && uvScroll.Length >= 6) ? uvScroll[5] : 0f;
        float sud = (uvScroll != null && uvScroll.Length >= 8) ? uvScroll[6] : 0f;
        float svd = (uvScroll != null && uvScroll.Length >= 8) ? uvScroll[7] : 0f;

        bool anyUvScroll = (Mathf.Abs(su0) > 1e-5f || Mathf.Abs(sv0) > 1e-5f ||
                            Mathf.Abs(su1) > 1e-5f || Mathf.Abs(sv1) > 1e-5f ||
                            Mathf.Abs(su2) > 1e-5f || Mathf.Abs(sv2) > 1e-5f ||
                            Mathf.Abs(sud) > 1e-5f || Mathf.Abs(svd) > 1e-5f);
        bool needsExtendedShader = !string.IsNullOrEmpty(maskTexName)
            || !string.IsNullOrEmpty(mask2TexName)
            || (dissolve > 0.001f && !string.IsNullOrEmpty(dissolveTexName))
            || (Mathf.Abs(distortStrength) > 0.0001f && !string.IsNullOrEmpty(distortTexName))
            || customDataEnabled
            || HasClampWrap(texWrap)
            || HasClampWrap(maskWrap)
            || HasClampWrap(mask2Wrap)
            || (periodicLoopT > 0.05f && anyUvScroll);
        Shader chosenShader = isAdditive
            ? (needsExtendedShader ? addMaskShader : addShader)
            : alphaShader;
        Material mat = new Material(chosenShader);

        BindTexSlot(mat, "_MainTex", "_FlowMain", "_MainClamp", texName, texScale, texOffset, texWrap, su0, sv0, periodicLoopT, texCache, uvEntries);
        if (mat.HasProperty("_MaskTex"))
            BindTexSlot(mat, "_MaskTex", "_FlowMask", "_MaskClamp", maskTexName, maskScale, maskOffset, maskWrap, su1, sv1, periodicLoopT, texCache, uvEntries);
        if (mat.HasProperty("_MaskTex2"))
            BindTexSlot(mat, "_MaskTex2", "_FlowMask2", "_Mask2Clamp", mask2TexName, mask2Scale, mask2Offset, mask2Wrap, su2, sv2, periodicLoopT, texCache, uvEntries);
        if (mat.HasProperty("_DissolveTex"))
        {
            BindTexSlot(mat, "_DissolveTex", null, null, dissolveTexName, dissolveScale, dissolveOffset, null, 0f, 0f, periodicLoopT, texCache, uvEntries);
            mat.SetFloat("_Dissolve", Mathf.Clamp01(dissolve));
            mat.SetFloat("_DissolveSoft", Mathf.Clamp(dissolveSoft, 0.01f, 2f));
        }
        if (mat.HasProperty("_DistortTex"))
        {
            BindTexSlot(mat, "_DistortTex", "_FlowDistort", null, distortTexName, distortScale, distortOffset, null, sud, svd, periodicLoopT, texCache, uvEntries);
            mat.SetFloat("_DistortStrength", distortStrength);
        }
        if (mat.HasProperty("_UseCustomData"))
        {
            mat.SetFloat("_UseCustomData", customDataEnabled ? 1f : 0f);
            mat.SetFloat("_CustomDataMode", customDataMode);
            bool wIsDissolve = customDataEnabled && customDataMode == 0 && !string.IsNullOrEmpty(dissolveTexName);
            mat.SetFloat("_CustomWIsDissolve", wIsDissolve ? 1f : 0f);
        }

        Color tcol = ToCol(tintDto);
        if (tcol.a <= 0.001f && tcol.r <= 0.001f && tcol.g <= 0.001f && tcol.b <= 0.001f)
            tcol = new Color(0.5f, 0.5f, 0.5f, 0.5f);
        else if (tcol.a <= 0.001f)
            tcol.a = 0.5f;
        float mul = tintMultiplier > 0.001f ? tintMultiplier : 1f;
        tcol = new Color(tcol.r * mul, tcol.g * mul, tcol.b * mul, tcol.a);
        mat.SetColor("_TintColor", tcol);
        createdMats.Add(mat);
        return mat;
    }

    private static void ApplyRenderPass(
        List<RenderPassItem> items,
        bool isAddPass,
        Material invisibleAlphaMat,
        Material invisibleAddMat
    )
    {
        Material dummy = isAddPass ? invisibleAddMat : invisibleAlphaMat;
        for (int i = 0; i < items.Count; i++)
        {
            var it = items[i];
            bool enableThisPass = isAddPass ? (it.mainAdd || it.trailAdd) : (it.mainNorm || it.trailNorm);
            it.psr.enabled = enableThisPass;
            if (!enableThisPass) continue;
            if (it.isMixed)
            {
                bool useMain = isAddPass ? it.mainAdd : it.mainNorm;
                bool useTrail = isAddPass ? it.trailAdd : it.trailNorm;
                it.psr.sharedMaterial = useMain ? it.mainMat : dummy;
                it.psr.trailMaterial = useTrail ? it.trailMat : dummy;
            }
        }
    }

    private static Gradient BuildGradient(GradientDto dto)
    {
        Gradient g = new Gradient();
        int nck = dto.ckeys != null && dto.ckeys.Length > 0 ? dto.ckeys.Length : 1;
        var ck = new GradientColorKey[nck];
        if (dto.ckeys != null && dto.ckeys.Length > 0)
        {
            for (int i = 0; i < dto.ckeys.Length; i++)
                ck[i] = new GradientColorKey(new Color(dto.ckeys[i].r, dto.ckeys[i].g, dto.ckeys[i].b, 1f), Mathf.Clamp01(dto.ckeys[i].t));
        }
        else ck[0] = new GradientColorKey(Color.white, 0f);

        int nak = dto.akeys != null && dto.akeys.Length > 0 ? dto.akeys.Length : 1;
        var ak = new GradientAlphaKey[nak];
        if (dto.akeys != null && dto.akeys.Length > 0)
        {
            for (int i = 0; i < dto.akeys.Length; i++)
                ak[i] = new GradientAlphaKey(Mathf.Clamp01(dto.akeys[i].a), Mathf.Clamp01(dto.akeys[i].t));
        }
        else ak[0] = new GradientAlphaKey(1f, 0f);

        g.SetKeys(ck, ak);
        return g;
    }

    private static ParticleSystem.MinMaxCurve ToMinMaxCurve(MinMaxCurveDto dto, float fallback, float mult = 1f)
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
            else
            {
                kmin = new Keyframe[] { new Keyframe(0f, 0f), new Keyframe(1f, 0f) };
            }
            float sc = (Mathf.Approximately(dto.scalar, 0f) ? 1f : dto.scalar) * mult;
            return new ParticleSystem.MinMaxCurve(sc, new AnimationCurve(kmin), new AnimationCurve(kmax));
        }
        return new ParticleSystem.MinMaxCurve(dto.scalar * mult);
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
            // Keep premultiplied black-bg RGB intact for Spine DefaultPMAShader (Blend One One) - NO un-premultiply!
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

    private static string EscapeJson(string s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", " ").Replace("\n", " ");
    }
}
#endif
