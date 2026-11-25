#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Deterministic two-pass (Normal RGBA32 + Additive Black) Unity 2021.3 FX Frame Sequence Exporter.
/// Produces clean PNG sequences directly consumable by `spine_fx_submodel_packer.py`.
/// </summary>
public class SoulTideFxRecorder : EditorWindow
{
    public GameObject targetPrefab;
    public Camera captureCamera;
    public int width = 884;
    public int height = 588;
    public float fps = 15f;
    public float durationSeconds = 2.0f;
    public float warmupSeconds = 1.0f;
    public string outputRoot = @"E:\A灵魂潮汐\fx_captures";
    public string sequenceName = "idle";
    public bool autoDecomposeBlendModes = true;

    [MenuItem("SoulTide/FX Submodel Recorder")]
    public static void ShowWindow()
    {
        GetWindow<SoulTideFxRecorder>("SoulTide FX Recorder");
    }

    private void OnGUI()
    {
        GUILayout.Label("SoulTide FX -> PNG Sequence Exporter", EditorStyles.boldLabel);
        targetPrefab = (GameObject)EditorGUILayout.ObjectField("FX Prefab / Root", targetPrefab, typeof(GameObject), true);
        captureCamera = (Camera)EditorGUILayout.ObjectField("Orthographic Camera", captureCamera, typeof(Camera), true);
        width = EditorGUILayout.IntField("Canvas Width (px)", width);
        height = EditorGUILayout.IntField("Canvas Height (px)", height);
        fps = EditorGUILayout.FloatField("Capture FPS", fps);
        durationSeconds = EditorGUILayout.FloatField("Clip Duration (s)", durationSeconds);
        warmupSeconds = EditorGUILayout.FloatField("Loop Warmup (s)", warmupSeconds);
        outputRoot = EditorGUILayout.TextField("Output Folder", outputRoot);
        sequenceName = EditorGUILayout.TextField("Animation Name", sequenceName);
        autoDecomposeBlendModes = EditorGUILayout.Toggle("Split Normal + Additive", autoDecomposeBlendModes);

        if (GUILayout.Button("Capture FX Sequence (Batch)"))
        {
            Capture();
        }
    }

    public void Capture()
    {
        if (targetPrefab == null)
        {
            Debug.LogError("[SoulTideFxRecorder] Please assign a Target FX Prefab or Scene Object.");
            return;
        }
        Camera cam = captureCamera != null ? captureCamera : Camera.main;
        if (cam == null)
        {
            Debug.LogError("[SoulTideFxRecorder] No Orthographic Camera assigned or found.");
            return;
        }

        string seqDir = Path.Combine(outputRoot, sequenceName);
        string normDir = Path.Combine(seqDir, "normal");
        string addDir = Path.Combine(seqDir, "add");
        Directory.CreateDirectory(normDir);
        if (autoDecomposeBlendModes) Directory.CreateDirectory(addDir);

        GameObject instance = PrefabUtility.IsPartOfPrefabAsset(targetPrefab)
            ? (GameObject)PrefabUtility.InstantiatePrefab(targetPrefab)
            : targetPrefab;
        bool spawnedHere = instance != targetPrefab;

        var renderers = instance.GetComponentsInChildren<ParticleSystemRenderer>(true);
        var particles = instance.GetComponentsInChildren<ParticleSystem>(true);
        var origEnabled = new Dictionary<ParticleSystemRenderer, bool>();
        var additiveRenderers = new List<ParticleSystemRenderer>();
        var normalRenderers = new List<ParticleSystemRenderer>();

        foreach (var r in renderers)
        {
            origEnabled[r] = r.enabled;
            Material mat = r.sharedMaterial;
            bool isAdd = false;
            if (mat != null)
            {
                // Detect Additive via shader name or _DstBlend == One (1)
                string sname = mat.shader != null ? mat.shader.name.ToLowerInvariant() : "";
                float dstBlend = mat.HasProperty("_DstBlend") ? mat.GetFloat("_DstBlend") : -1f;
                if (sname.Contains("add") || dstBlend == 1f)
                    isAdd = true;
            }
            if (isAdd) additiveRenderers.Add(r);
            else normalRenderers.Add(r);
        }

        RenderTexture rt = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
        Texture2D tex = new Texture2D(width, height, TextureFormat.RGBA32, false);
        var oldTarget = cam.targetTexture;
        var oldClearFlags = cam.clearFlags;
        var oldBg = cam.backgroundColor;

        try
        {
            cam.targetTexture = rt;
            cam.clearFlags = CameraClearFlags.SolidColor;

            // Optional loop warmup
            if (warmupSeconds > 0f)
            {
                float warmDt = 1f / 30f;
                int warmSteps = Mathf.RoundToInt(warmupSeconds / warmDt);
                for (int w = 0; w < warmSteps; w++)
                {
                    foreach (var ps in particles)
                        ps.Simulate(warmDt, false, w == 0, false);
                }
            }

            int totalFrames = Mathf.Max(1, Mathf.RoundToInt(durationSeconds * fps));
            float stepDt = 1f / Mathf.Max(1f, fps);

            for (int f = 0; f < totalFrames; f++)
            {
                bool restart = (f == 0 && warmupSeconds <= 0f);
                foreach (var ps in particles)
                    ps.Simulate(stepDt, false, restart, false);

                // Pass 1: Normal Alpha pass
                if (!autoDecomposeBlendModes || normalRenderers.Count > 0)
                {
                    SetGroupActive(normalRenderers, true);
                    if (autoDecomposeBlendModes) SetGroupActive(additiveRenderers, false);
                    cam.backgroundColor = new Color(0f, 0f, 0f, 0f);
                    cam.Render();
                    SaveRtPng(rt, tex, Path.Combine(normDir, $"frame_{f:D4}.png"), extractMaxAlpha: false);
                }

                // Pass 2: Additive pass on pure black background -> converted cleanly for Spine additive slot
                if (autoDecomposeBlendModes && additiveRenderers.Count > 0)
                {
                    SetGroupActive(normalRenderers, false);
                    SetGroupActive(additiveRenderers, true);
                    cam.backgroundColor = new Color(0f, 0f, 0f, 1f);
                    cam.Render();
                    SaveRtPng(rt, tex, Path.Combine(addDir, $"frame_{f:D4}.png"), extractMaxAlpha: true);
                }
            }
            Debug.Log($"[SoulTideFxRecorder] Exported {totalFrames} frames -> {seqDir}");
        }
        finally
        {
            foreach (var kv in origEnabled) kv.Key.enabled = kv.Value;
            cam.targetTexture = oldTarget;
            cam.clearFlags = oldClearFlags;
            cam.backgroundColor = oldBg;
            RenderTexture.active = null;
            DestroyImmediate(rt);
            DestroyImmediate(tex);
            if (spawnedHere && instance != null) DestroyImmediate(instance);
        }
    }

    private static void SetGroupActive(List<ParticleSystemRenderer> list, bool active)
    {
        foreach (var r in list) r.enabled = active;
    }

    private static void SaveRtPng(RenderTexture rt, Texture2D buf, string path, bool extractMaxAlpha)
    {
        RenderTexture.active = rt;
        buf.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0);
        if (extractMaxAlpha)
        {
            Color32[] px = buf.GetPixels32();
            for (int i = 0; i < px.Length; i++)
            {
                byte maxRgb = Math.Max(px[i].r, Math.Max(px[i].g, px[i].b));
                px[i].a = maxRgb;
                if (maxRgb > 0)
                {
                    // Un-premultiply RGB by maxRgb so Spine additive (src_rgb * src_a + dst) matches original glow
                    px[i].r = (byte)Mathf.Min(255, px[i].r * 255 / maxRgb);
                    px[i].g = (byte)Mathf.Min(255, px[i].g * 255 / maxRgb);
                    px[i].b = (byte)Mathf.Min(255, px[i].b * 255 / maxRgb);
                }
            }
            buf.SetPixels32(px);
        }
        buf.Apply();
        File.WriteAllBytes(path, buf.EncodeToPNG());
    }
}
#endif
