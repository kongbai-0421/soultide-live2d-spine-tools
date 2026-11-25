Shader "SoulTide/ParticleAdd"
{
    Properties
    {
        _TintColor ("Tint Color", Color) = (0.5, 0.5, 0.5, 0.5)
        _MainTex ("Particle Texture", 2D) = "white" {}
        _MaskTex ("Mask Texture", 2D) = "white" {}
        _MaskTex2 ("Mask Texture 2", 2D) = "white" {}
        _DissolveTex ("Dissolve Noise", 2D) = "white" {}
        _Dissolve ("Dissolve Cutoff", Range(0.0, 1.0)) = 0.0
        _DissolveSoft ("Dissolve Softness", Range(0.001, 1.0)) = 0.5
        _DistortTex ("Distort Noise", 2D) = "gray" {}
        _DistortStrength ("Distort Strength", Float) = 0.0
        _FlowClock ("Flow Clock", Float) = 0.0
        _FlowMain ("Flow Main (u,v,T,en)", Vector) = (0,0,6,0)
        _FlowMask ("Flow Mask (u,v,T,en)", Vector) = (0,0,6,0)
        _FlowMask2 ("Flow Mask2 (u,v,T,en)", Vector) = (0,0,6,0)
        _FlowDistort ("Flow Distort (u,v,T,en)", Vector) = (0,0,6,0)
        _MainClamp ("Main Clamp UV (u,v,0,0)", Vector) = (0,0,0,0)
        _MaskClamp ("Mask Clamp UV (u,v,0,0)", Vector) = (0,0,0,0)
        _Mask2Clamp ("Mask2 Clamp UV (u,v,0,0)", Vector) = (0,0,0,0)
        _UseCustomData ("Use Custom1", Float) = 0.0
        _CustomDataMode ("Custom1 Mode", Float) = 0.0
        _CustomWIsDissolve ("Custom1.w Is Dissolve", Float) = 0.0
    }
    SubShader
    {
        Tags { "Queue"="Transparent" "IgnoreProjector"="True" "RenderType"="Transparent" }
        Blend SrcAlpha One
        ColorMask RGB
        Cull Off
        Lighting Off
        ZWrite Off

        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float4 _MainTex_ST;
            sampler2D _MaskTex;
            float4 _MaskTex_ST;
            sampler2D _MaskTex2;
            float4 _MaskTex2_ST;
            sampler2D _DissolveTex;
            float4 _DissolveTex_ST;
            fixed _Dissolve;
            fixed _DissolveSoft;
            sampler2D _DistortTex;
            float4 _DistortTex_ST;
            float _DistortStrength;
            fixed4 _TintColor;
            float _FlowClock;
            float4 _FlowMain;
            float4 _FlowMask;
            float4 _FlowMask2;
            float4 _FlowDistort;
            float4 _MainClamp;
            float4 _MaskClamp;
            float4 _Mask2Clamp;
            float _UseCustomData;
            float _CustomDataMode;
            float _CustomWIsDissolve;

            struct appdata_t
            {
                float4 vertex : POSITION;
                fixed4 color : COLOR;
                float2 texcoord : TEXCOORD0;
                float4 custom1 : TEXCOORD1;
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                fixed4 color : COLOR;
                float4 uv01 : TEXCOORD0;
                float4 uv23 : TEXCOORD1;
                float2 uv4 : TEXCOORD2;
                float4 custom1 : TEXCOORD3;
            };

            inline float2 ApplyClampUV(float2 uv, float4 cl)
            {
                if (cl.x > 0.5) uv.x = clamp(uv.x, 0.0005, 0.9995);
                if (cl.y > 0.5) uv.y = clamp(uv.y, 0.0005, 0.9995);
                return uv;
            }

            inline fixed4 SampleDualFlowColor(sampler2D tex, float2 uv, float4 flow, float4 cl)
            {
                if (flow.w < 0.5)
                    return tex2D(tex, ApplyClampUV(uv, cl));
                float T = max(0.01, flow.z);
                float p0 = frac(_FlowClock / T);
                float p1 = frac(_FlowClock / T + 0.5);
                float s0 = sin(3.14159265 * p0);
                float w0 = s0 * s0;
                float w1 = 1.0 - w0;
                float2 uv0 = ApplyClampUV(uv + flow.xy * (p0 * T), cl);
                float2 uv1 = ApplyClampUV(uv + flow.xy * (p1 * T), cl);
                return tex2D(tex, uv0) * w0 + tex2D(tex, uv1) * w1;
            }

            inline float2 SampleDualFlowDistort(sampler2D tex, float2 uv, float4 flow)
            {
                if (flow.w < 0.5)
                    return (tex2D(tex, uv).rg - 0.5);
                float T = max(0.01, flow.z);
                float p0 = frac(_FlowClock / T);
                float p1 = frac(_FlowClock / T + 0.5);
                float s0 = sin(3.14159265 * p0);
                float w0 = s0 * s0;
                float w1 = 1.0 - w0;
                float invNorm = rsqrt(max(1e-5, w0 * w0 + w1 * w1));
                float a0 = w0 * invNorm;
                float a1 = w1 * invNorm;
                float2 d0 = tex2D(tex, uv + flow.xy * (p0 * T)).rg - 0.5;
                float2 d1 = tex2D(tex, uv + flow.xy * (p1 * T)).rg - 0.5;
                return d0 * a0 + d1 * a1;
            }

            v2f vert(appdata_t v)
            {
                v2f o;
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.color = v.color;
                o.uv01.xy = TRANSFORM_TEX(v.texcoord, _MainTex);
                o.uv01.zw = TRANSFORM_TEX(v.texcoord, _MaskTex);
                o.uv23.xy = TRANSFORM_TEX(v.texcoord, _MaskTex2);
                o.uv23.zw = TRANSFORM_TEX(v.texcoord, _DissolveTex);
                o.uv4 = TRANSFORM_TEX(v.texcoord, _DistortTex);
                o.custom1 = v.custom1;
                return o;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                float2 mainUv = i.uv01.xy;
                float2 maskUv = i.uv01.zw;
                float effDistStr = _DistortStrength;
                float effDissolve = _Dissolve;

                if (_UseCustomData > 0.5)
                {
                    if (_CustomDataMode < 0.5)
                    {
                        mainUv += i.custom1.xy;
                        maskUv.x += i.custom1.z;
                        if (_CustomWIsDissolve > 0.5)
                            effDissolve = saturate(effDissolve + i.custom1.w);
                        else
                            maskUv.y += i.custom1.w;
                    }
                    else
                    {
                        effDistStr += i.custom1.y;
                    }
                }

                if (abs(effDistStr) > 0.0001)
                {
                    float2 dist = SampleDualFlowDistort(_DistortTex, i.uv4, _FlowDistort);
                    mainUv += dist * (2.0 * effDistStr);
                }

                fixed4 tex = SampleDualFlowColor(_MainTex, mainUv, _FlowMain, _MainClamp);
                fixed4 m1 = SampleDualFlowColor(_MaskTex, maskUv, _FlowMask, _MaskClamp);
                fixed4 m2 = SampleDualFlowColor(_MaskTex2, i.uv23.xy, _FlowMask2, _Mask2Clamp);
                fixed mval = min(m1.a, max(m1.r, max(m1.g, m1.b))) * min(m2.a, max(m2.r, max(m2.g, m2.b)));
                fixed dval = 1.0;
                if (effDissolve > 0.001)
                {
                    fixed noise = tex2D(_DissolveTex, i.uv23.zw).r;
                    fixed halfSoft = max(0.005, _DissolveSoft * 0.5);
                    dval = smoothstep(effDissolve - halfSoft, effDissolve + halfSoft, noise);
                }
                fixed4 col = 2.0f * i.color * _TintColor * tex;
                col.a *= mval * dval;
                return col;
            }
            ENDCG
        }
    }
}
