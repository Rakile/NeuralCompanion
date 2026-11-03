#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float level;
    float stateLevel;
    float glowAmount;
    float softness;
    float style;
    vec4 primary;
    vec4 secondary;
    vec4 accent;
    vec4 glow;
};

float ring(float distanceValue, float radius, float thickness)
{
    return 1.0 - smoothstep(thickness, thickness * 2.2, abs(distanceValue - radius));
}

void main()
{
    vec2 p = qt_TexCoord0 * 2.0 - 1.0;
    float angle = atan(p.y, p.x);
    float baseDistance = length(p);
    float styleId = floor(style + 0.5);
    float motion = sin(time * 1.35 + angle * 3.0) * 0.004;

    if (styleId == 3.0)
        motion += sin(angle * 5.0 - time * 0.9) * 0.014;
    else if (styleId == 7.0)
        motion += sin(angle * 7.0 + time * 0.75) * 0.020;
    else if (styleId == 8.0)
        motion += sin(angle * 4.0 + time * 1.1) * 0.018 + cos(angle * 7.0 - time * 0.6) * 0.008;
    else if (styleId == 9.0)
        motion += abs(sin(angle * 3.0)) * 0.016;

    float distanceValue = baseDistance + motion * (1.0 + stateLevel);
    float coreRadius = styleId == 11.0 ? 0.24 : 0.40 + level * 0.018;
    float edgeSoftness = mix(0.018, 0.050, clamp(softness, 0.0, 1.0));
    float coreMask = 1.0 - smoothstep(coreRadius, coreRadius + edgeSoftness, distanceValue);
    float rim = ring(distanceValue, coreRadius, 0.010 + edgeSoftness * 0.26);

    float radial = clamp(distanceValue / max(0.05, coreRadius), 0.0, 1.0);
    float quietTexture = 0.5 + 0.5 * sin(angle * 4.0 - time * 0.42 + radial * 6.0);
    vec3 matte = mix(primary.rgb * 0.12, secondary.rgb * 0.56, 0.22 + radial * 0.58);
    matte = mix(matte, accent.rgb * 0.48, quietTexture * 0.15 + stateLevel * 0.10);

    if (styleId == 1.0) {
        matte = mix(primary.rgb * 0.16, secondary.rgb * 0.48, 0.30 + quietTexture * 0.24);
        rim *= 0.70;
    } else if (styleId == 2.0) {
        float prism = 0.5 + 0.5 * sin(angle * 6.0 + radial * 10.0 - time);
        matte = mix(matte, accent.rgb * 0.64, prism * 0.42);
    } else if (styleId == 4.0) {
        float ember = 0.5 + 0.5 * sin(angle * 5.0 - radial * 13.0 + time * 1.4);
        matte = mix(primary.rgb * 0.20, accent.rgb * 0.62, ember * 0.52);
    } else if (styleId == 5.0) {
        matte = mix(vec3(0.003, 0.006, 0.018), primary.rgb * 0.18, pow(radial, 4.0));
        rim *= 1.35;
    } else if (styleId == 6.0) {
        float iris = 0.5 + 0.5 * sin(angle * 18.0 + radial * 16.0 - time * 0.7);
        matte = mix(primary.rgb * 0.10, secondary.rgb * 0.62, iris * (0.30 + radial * 0.38));
    } else if (styleId == 7.0) {
        float petals = 0.5 + 0.5 * cos(angle * 7.0);
        matte = mix(primary.rgb * 0.12, accent.rgb * 0.55, petals * radial * 0.56);
    } else if (styleId == 8.0) {
        float liquid = 0.5 + 0.5 * sin(radial * 15.0 - time * 1.1 + angle * 2.0);
        matte = mix(primary.rgb * 0.16, secondary.rgb * 0.58, liquid * 0.48);
    } else if (styleId == 9.0) {
        float facet = smoothstep(0.22, 0.85, abs(sin(angle * 3.0 + radial * 4.0)));
        matte = mix(primary.rgb * 0.08, accent.rgb * 0.55, facet * 0.52);
    } else if (styleId == 10.0) {
        matte = mix(primary.rgb * 0.10, secondary.rgb * 0.50, radial * 0.58);
        rim *= 1.22;
    }

    float auraStart = coreRadius + 0.035;
    float aura = (1.0 - smoothstep(auraStart, 0.94, distanceValue));
    aura *= smoothstep(0.99, coreRadius + 0.01, distanceValue);
    aura *= 0.10 + 0.15 * clamp(glowAmount, 0.0, 1.75) + level * 0.07;
    float ripple = ring(distanceValue, coreRadius + 0.09 + 0.015 * sin(time * 1.2), 0.012);
    ripple *= (0.10 + stateLevel * 0.16) * (1.0 - smoothstep(0.72, 0.96, distanceValue));

    vec3 color = matte * coreMask;
    color += secondary.rgb * rim * (0.32 + glowAmount * 0.24);
    color += glow.rgb * aura * 0.54;
    color += accent.rgb * ripple * 0.42;

    float alpha = max(coreMask * 0.94, rim * 0.72);
    alpha = max(alpha, aura);
    alpha = max(alpha, ripple * 0.42);
    alpha *= 1.0 - smoothstep(0.92, 0.995, baseDistance);
    alpha = clamp(alpha, 0.0, 1.0);

    fragColor = vec4(color * alpha, alpha) * qt_Opacity;
}
