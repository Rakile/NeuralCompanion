#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float reflectionAxis;
    float reflectionStrength;
    float reflectionSoftness;
    float colorLift;
    float time;
};

layout(binding = 1) uniform sampler2D source;

void main()
{
    vec2 uv = qt_TexCoord0;
    float belowSurface = smoothstep(
        reflectionAxis,
        reflectionAxis + 0.018,
        uv.y
    );
    float depth = clamp(
        (uv.y - reflectionAxis) / max(0.001, 1.0 - reflectionAxis),
        0.0,
        1.0
    );

    vec2 reflectedUv = vec2(
        uv.x + sin(uv.y * 19.0 + time * 1.7) * (0.0015 + depth * 0.0030),
        reflectionAxis - (uv.y - reflectionAxis) * 0.86
    );
    reflectedUv = clamp(reflectedUv, vec2(0.0), vec2(1.0));

    float blurStep = 0.0028 * clamp(reflectionSoftness, 0.0, 2.0);
    vec4 reflected = texture(source, reflectedUv) * 0.56;
    reflected += texture(source, reflectedUv + vec2(0.0, blurStep)) * 0.22;
    reflected += texture(source, reflectedUv - vec2(0.0, blurStep)) * 0.22;

    float distanceFade = pow(max(0.0, 1.0 - depth), 1.75);
    float surfaceRipple = 0.94 + 0.06 * sin(
        uv.x * 24.0 - time * 1.35 + depth * 7.0
    );
    float strength = belowSurface
        * distanceFade
        * surfaceRipple
        * clamp(reflectionStrength, 0.0, 1.0);
    reflected.rgb *= 1.0 + clamp(colorLift, 0.0, 0.5);
    fragColor = reflected * strength * qt_Opacity;
}
