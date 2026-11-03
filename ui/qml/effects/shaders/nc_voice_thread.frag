#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float audioLevel;
    float peakLevel;
    float ambientLevel;
    float ambientPeak;
    float ambientReactionTarget;
    float ambientNoiseGate;
    float ambientLinkMainControls;
    float ambientFiberSpreadEnabled;
    float ambientShapeStrength;
    float ambientTravelStrength;
    float ambientGlowStrength;
float ambientFiberStrength;
float ambientColorStrength;
float audioColorsEnabled;
float voiceColorsEnabled;
float desktopColorsEnabled;
float colorVividness;
float colorBassInfluence;
float colorMidInfluence;
float colorHighInfluence;
float colorSmoothing;
float ambientMotionCeiling;
    float ambientBassBend;
    float ambientMidRipple;
    float ambientHighShimmer;
    float speakingReactivity;
    float peakEmphasis;
    float glowRadius;
    float variation;
    float strandMultiplier;
    float idleTime;
    float idleMotion;
    float motionStyle;
    float audioReactivity;
    float motionScale;
    float spectrumSmoothing;
    float spectrumScale;
    float glowIntensity;
    float fluxStrength;
    float fiberSpread;
    float bendiness;
    float organicVariation;
    float phraseMotion;
    float phraseEnergy;
    float postureOffset;
    float postureTilt;
    float postureLag;
    float postureTiltLag;
    float gestureAmount;
    float gestureProgress;
    float gestureType;
    float gestureSeed;
    float motionMemory;
    float physicsRestOffset;
    float physicsGrabX;
    float physicsGrabY;
    float physicsLagX;
    float physicsLagY;
    float physicsGrabAmount;
    float physicsSlack;
    float physicsFeel;
    float physicsGravity;
    float contentVerticalScale;
    float overallScale;
    float aspectRatio;
    float spectralFlux;
    float spectralCentroid;
    vec4 primary;
    vec4 secondary;
    vec4 highlight;
    vec4 spectrum0;
    vec4 spectrum1;
    vec4 spectrum2;
    vec4 ambientSpectrum0;
    vec4 ambientSpectrum1;
    vec4 ambientSpectrum2;
};

void addThread(
    float distanceValue,
    vec3 tint,
    float edgeFade,
    float coreWidth,
    float haloWidth,
    inout vec3 color,
    inout float alpha
)
{
    float aa = max(fwidth(distanceValue) * 1.35, 0.0008);
    float core = 1.0 - smoothstep(coreWidth, coreWidth + aa, distanceValue);
    float halo = 1.0 - smoothstep(coreWidth + aa, max(coreWidth + aa * 2.0, haloWidth), distanceValue);
    core *= edgeFade;
    halo *= edgeFade;
    color += tint * (core * 0.92 + halo * 0.30);
    alpha = max(alpha, core * 0.96 + halo * 0.38);
}

void addNode(
    vec2 offset,
    float radius,
    vec3 tint,
    float visibility,
    inout vec3 color,
    inout float alpha
)
{
    float distanceValue = length(offset);
    float aa = max(fwidth(distanceValue) * 1.25, 0.0008);
    float core = 1.0 - smoothstep(radius, radius + aa, distanceValue);
    float halo = 1.0 - smoothstep(radius + aa, radius * 2.25 + aa, distanceValue);
    core *= visibility;
    halo *= visibility;
    color += tint * (core * 0.72 + halo * 0.18);
    alpha = max(alpha, core * 0.78 + halo * 0.22);
}

float spectrumBand(int index)
{
    if (index < 4) {
        return spectrum0[index];
    }
    if (index < 8) {
        return spectrum1[index - 4];
    }
    return spectrum2[min(3, index - 8)];
}

float ambientSpectrumBand(int index)
{
    if (index < 4) {
        return ambientSpectrum0[index];
    }
    if (index < 8) {
        return ambientSpectrum1[index - 4];
    }
    return ambientSpectrum2[min(3, index - 8)];
}

float ambientSpectrumAt(float normalizedX)
{
    float position = clamp(normalizedX, 0.0, 1.0) * 11.0;
    int lower = min(11, int(floor(position)));
    int upper = min(11, lower + 1);
    float blend = smoothstep(0.0, 1.0, position - float(lower));
    return mix(ambientSpectrumBand(lower), ambientSpectrumBand(upper), blend);
}

float ambientBassAverage()
{
    return dot(ambientSpectrum0, vec4(0.25));
}

float ambientMidAverage()
{
    return dot(ambientSpectrum1, vec4(0.25));
}

float ambientHighAverage()
{
    return dot(ambientSpectrum2, vec4(0.25));
}

float voiceBassAverage()
{
    return dot(spectrum0, vec4(0.25));
}

float voiceMidAverage()
{
    return dot(spectrum1, vec4(0.25));
}

float voiceHighAverage()
{
    return dot(spectrum2, vec4(0.25));
}

vec3 vividColor(vec3 value, float vividness, float energy)
{
    float luminance = dot(value, vec3(0.2126, 0.7152, 0.0722));
    float saturation = clamp(vividness, 0.0, 4.0);
    float gain = 1.0 + max(0.0, saturation - 1.0)
        * 0.12 * clamp(energy, 0.0, 1.0);
    return clamp(mix(vec3(luminance), value, saturation) * gain, 0.0, 1.0);
}

vec3 audioReactiveTint(
    vec3 baseColor,
    float normalizedX,
    float strandBlend,
    float voiceEnergy,
    float desktopEnergy
)
{
    float enabled = step(0.5, audioColorsEnabled);
    float voiceSource = step(0.5, voiceColorsEnabled);
    float desktopSource = step(0.5, desktopColorsEnabled);
    float voiceFloor = clamp(voiceEnergy, 0.0, 1.0) * 0.30;
    float desktopFloor = clamp(desktopEnergy, 0.0, 3.0) * 0.18;
    float voiceBass = voiceBassAverage();
    float voiceMids = voiceMidAverage();
    float voiceHighs = voiceHighAverage();
    float voiceSpectrumMaximum = max(voiceBass, max(voiceMids, voiceHighs));
    float voiceFallback = voiceFloor * (
        1.0 - smoothstep(0.002, 0.040, voiceSpectrumMaximum)
    );
    float desktopBass = ambientBassAverage();
    float desktopMids = ambientMidAverage();
    float desktopHighs = ambientHighAverage();
    float desktopSpectrumMaximum = max(
        desktopBass, max(desktopMids, desktopHighs)
    );
    if (desktopSpectrumMaximum > 0.001) {
        float contrastPower = 2.20;
        desktopBass = desktopSpectrumMaximum * pow(
            clamp(desktopBass / desktopSpectrumMaximum, 0.0, 1.0),
            contrastPower
        );
        desktopMids = desktopSpectrumMaximum * pow(
            clamp(desktopMids / desktopSpectrumMaximum, 0.0, 1.0),
            contrastPower
        );
        desktopHighs = desktopSpectrumMaximum * pow(
            clamp(desktopHighs / desktopSpectrumMaximum, 0.0, 1.0),
            contrastPower
        );
    }
    float desktopFallback = desktopFloor * (
        1.0 - smoothstep(0.002, 0.040, desktopSpectrumMaximum)
    );
    float desktopGain = clamp(ambientColorStrength, 0.0, 12.0);
    float bass = max(
        max(voiceBass, voiceFallback) * voiceSource,
        max(desktopBass, desktopFallback) * desktopSource * desktopGain
    ) * clamp(colorBassInfluence, 0.0, 4.0);
    float mids = max(
        max(voiceMids, voiceFallback) * voiceSource,
        max(desktopMids, desktopFallback) * desktopSource * desktopGain
    ) * clamp(colorMidInfluence, 0.0, 4.0);
    float highs = max(
        max(voiceHighs, voiceFallback) * voiceSource,
        max(desktopHighs, desktopFallback) * desktopSource * desktopGain
    ) * clamp(colorHighInfluence, 0.0, 4.0);
    float maximumEnergy = max(bass, max(mids, highs));
    float colorX = clamp(normalizedX * 0.78 + strandBlend * 0.22, 0.0, 1.0);
    float softness = clamp(colorSmoothing / 2.0, 0.0, 1.0);
    float width = 0.13 + softness * 0.30;
    float crossBlend = mix(0.035, 0.12, softness);
    float focus = 1.0 - crossBlend;
    float bassWeight = bass * (crossBlend + focus * exp(-pow((colorX - 0.16) / width, 2.0)));
    float midWeight = mids * (crossBlend + focus * exp(-pow((colorX - 0.50) / width, 2.0)));
    float highWeight = highs * (crossBlend + focus * exp(-pow((colorX - 0.84) / width, 2.0)));
    float totalWeight = max(0.0001, bassWeight + midWeight + highWeight);
    vec3 target = (
        primary.rgb * bassWeight
        + secondary.rgb * midWeight
        + highlight.rgb * highWeight
    ) / totalWeight;
    target = vividColor(target, colorVividness, maximumEnergy);
    float response = enabled * step(0.001, maximumEnergy)
        * clamp(maximumEnergy / (maximumEnergy + 0.30), 0.0, 1.0) * 0.92;
    return mix(baseColor, target, response);
}

float spectrumAt(float normalizedX)
{
    float position = clamp(normalizedX, 0.0, 1.0) * 11.0;
    int lower = min(11, int(floor(position)));
    int upper = min(11, lower + 1);
    float blend = smoothstep(0.0, 1.0, position - float(lower));
    return mix(spectrumBand(lower), spectrumBand(upper), blend);
}

float catmullRom(float a, float b, float c, float d, float t)
{
    float t2 = t * t;
    float t3 = t2 * t;
    return 0.5 * ((2.0 * b) + (-a + c) * t
        + (2.0 * a - 5.0 * b + 4.0 * c - d) * t2
        + (-a + 3.0 * b - 3.0 * c + d) * t3);
}

float controlHeight(int index, float activeAmount)
{
    int i = clamp(index, 0, 11);
    float raw = spectrumBand(i);
    float neighbor = (
        spectrumBand(max(0, i - 1))
        + spectrumBand(min(11, i + 1))
    ) * 0.5;
    float smoothing = clamp(spectrumSmoothing, 0.0, 2.0);
    float spatiallySmoothed = mix(
        raw,
        raw * 0.56 + neighbor * 0.44,
        min(1.0, smoothing)
    );
    spatiallySmoothed = mix(
        spatiallySmoothed,
        neighbor,
        max(0.0, smoothing - 1.0) * 0.55
    );
    float band = pow(
        clamp(spatiallySmoothed * clamp(spectrumScale, 0.0, 4.0), 0.0, 1.0),
        0.72
    );
    float signValue = (i % 2 == 0) ? 1.0 : -1.0;
    return signValue * band * activeAmount;
}

float spectrumSpline(float normalizedX, float activeAmount)
{
    float position = clamp(normalizedX, 0.0, 1.0) * 11.0;
    int current = min(10, int(floor(position)));
    float local = clamp(position - float(current), 0.0, 1.0);
    return catmullRom(
        controlHeight(current - 1, activeAmount),
        controlHeight(current, activeAmount),
        controlHeight(current + 1, activeAmount),
        controlHeight(current + 2, activeAmount),
        local
    );
}

float spectrumMaximum()
{
    float value = 0.0;
    for (int index = 0; index < 12; ++index) {
        value = max(value, spectrumBand(index));
    }
    return value;
}

float gesturePulse()
{
    float progress = clamp(gestureProgress, 0.0, 1.0);
    return sin(progress * 3.14159265);
}

float gestureDisplacement(float normalizedX)
{
    float x = clamp(normalizedX, 0.0, 1.0);
    float localX = x * 2.0 - 1.0;
    float edgeEnvelope = pow(max(0.0, sin(x * 3.14159265)), 1.35);
    float pulse = gesturePulse();
    float seedPhase = gestureSeed * 2.7;
    float kind = floor(gestureType + 0.5);
    if (kind < 1.5) {
        return sin(localX * (3.4 + abs(gestureSeed) * 1.8) + seedPhase)
            * edgeEnvelope * pulse;
    }
    if (kind < 2.5) {
        return localX * edgeEnvelope * pulse * (gestureSeed < 0.0 ? -1.0 : 1.0);
    }
    if (kind < 3.5) {
        float center = gestureSeed < 0.0
            ? 1.0 - clamp(gestureProgress, 0.0, 1.0)
            : clamp(gestureProgress, 0.0, 1.0);
        float sweep = exp(-pow((x - center) / 0.18, 2.0));
        return sweep * pulse * (gestureSeed < 0.0 ? -1.0 : 1.0);
    }
    return cos(localX * 3.14159265 * 0.72 + seedPhase * 0.24)
        * edgeEnvelope * pulse;
}

float voiceBodyY(
    float normalizedX,
    float activeAmount,
    float energy,
    float transient
)
{
    float localX = normalizedX * 2.0 - 1.0;
    float configuredMotion = clamp(motionScale, 0.0, 4.0);
    float configuredBend = clamp(bendiness, 0.0, 4.0);
    float bendAmplitude = 0.35 + configuredBend * 0.65;
    float bendFrequency = clamp(1.15 - configuredBend * 0.15, 0.775, 1.15);
    float splineY = spectrumSpline(normalizedX, activeAmount)
        * 0.19 * bendAmplitude;
    float driftY = sin(localX * 5.2 * bendFrequency - time * 0.55)
        * 0.018 * activeAmount * configuredMotion * bendAmplitude;
    float idleStrength = clamp(idleMotion, 0.0, 3.0);
    float idleEnabled = step(0.001, idleStrength);
    float idleAmplitude = idleEnabled * (0.012 + idleStrength * 0.030);
    float idleY = (
        sin(localX * 2.6 * bendFrequency + idleTime * 0.42)
        + sin(localX * 5.1 * bendFrequency - idleTime * 0.27) * 0.34
        + sin(localX * 0.92 - idleTime * 0.16) * 0.46
    ) * idleAmplitude
        * (1.0 - activeAmount * 0.65) * bendAmplitude;
    float phrase = clamp(phraseEnergy, 0.0, 1.0);
    float configuredPhraseMotion = clamp(phraseMotion, 0.0, 4.0);
    float idleVisibility = mix(
        idleEnabled * mix(0.38, 1.0, min(1.0, idleStrength)),
        1.0,
        activeAmount
    );
    float postureY = (
        postureOffset + postureTilt * localX
    ) * 0.065 * configuredPhraseMotion * idleVisibility;
    float phraseBreath = sin(normalizedX * 3.14159265)
        * phrase * (0.014 + 0.006 * sin(idleTime * 0.17 + gestureSeed * 1.9))
        * configuredPhraseMotion * bendAmplitude;
    float organicY = (
        sin(localX * 2.7 * bendFrequency + idleTime * 0.13 + gestureSeed * 1.3)
        + sin(localX * 4.1 * bendFrequency - idleTime * 0.071
            + gestureSeed * 2.1) * 0.42
    ) * 0.009 * clamp(organicVariation, 0.0, 4.0)
        * idleVisibility * bendAmplitude;
    float gestureY = gestureDisplacement(normalizedX)
        * clamp(gestureAmount, 0.0, 4.0)
        * 0.072 * configuredMotion * activeAmount * bendAmplitude;
    float macroY = 0.0;
    float styleId = floor(motionStyle + 0.5);
    if (styleId > 0.5 && styleId < 1.5) {
        macroY = (
            sin(localX * 2.1 * bendFrequency - time * 0.31)
                * (0.024 + energy * 0.026)
            + sin(time * 0.38) * 0.012
        ) * activeAmount * configuredMotion * bendAmplitude;
    } else if (styleId > 1.5 && styleId < 2.5) {
        macroY = sin(localX * 3.6 * bendFrequency - time * 0.86)
            * (0.030 + energy * 0.050)
            * activeAmount * configuredMotion * bendAmplitude;
    } else if (styleId > 2.5) {
        float bloom = 1.0 + energy * 0.46 * configuredMotion;
        splineY *= bloom;
        macroY = sin(localX * 1.7 * bendFrequency + time * 0.44)
            * transient * 0.040 * configuredMotion * bendAmplitude;
    }
    float ambientCeiling = clamp(ambientMotionCeiling, 0.25, 3.0);
    float ambientDrive = min(
        ambientCeiling,
        max(clamp(ambientLevel, 0.0, ambientCeiling),
            clamp(ambientPeak, 0.0, ambientCeiling) * 0.55)
    );
    float speechDuck = mix(1.0, 0.16, smoothstep(0.02, 0.55, energy));
    ambientDrive *= speechDuck;
    ambientDrive *= smoothstep(
        0.0,
        max(0.004, clamp(ambientNoiseGate, 0.0, 0.25) * 0.5),
        ambientDrive
    );
    float bass = ambientBassAverage();
    float mids = ambientMidAverage();
    float localAmbient = ambientSpectrumAt(normalizedX);
    float edgeEnvelope = pow(max(0.0, sin(normalizedX * 3.14159265)), 1.28);
    float shapeEnabled = step(0.5, ambientReactionTarget);
    float fullSpectrum = step(1.5, ambientReactionTarget);
    float shapeDrive = clamp(ambientShapeStrength, 0.0, 12.0);
    float travelDrive = clamp(ambientTravelStrength, 0.0, 12.0);
    float ambientY = edgeEnvelope * shapeEnabled * ambientDrive
        * shapeDrive * (
        (
            sin(localX * 1.65 * bendFrequency
                - idleTime * (0.42 + travelDrive * 0.46))
            + sin(localX * 0.72
                + idleTime * (0.18 + travelDrive * 0.22)) * 0.34
        ) * bass * clamp(ambientBassBend, 0.0, 4.0) * 0.105
        + sin(localX * 7.4 * bendFrequency
            - idleTime * (1.1 + travelDrive * 1.15))
            * mids * clamp(ambientMidRipple, 0.0, 4.0) * 0.072
        + sin(localX * 12.0 * bendFrequency
            + idleTime * (1.4 + travelDrive * 1.35))
            * localAmbient * clamp(ambientMidRipple, 0.0, 4.0)
            * fullSpectrum * 0.056
    );
    float restY = clamp(physicsRestOffset, -0.72, 0.72);
    float animatedY = splineY + driftY + idleY + postureY + phraseBreath
        + organicY + gestureY + macroY + ambientY;
    return restY + animatedY
        * clamp(contentVerticalScale, 0.45, 1.0)
        * clamp(overallScale, 0.50, 2.60);
}

float physicsSegmentDistance(vec2 pointValue, vec2 start, vec2 end)
{
    float ratio = max(0.25, aspectRatio);
    vec2 pointMetric = vec2(pointValue.x * ratio, pointValue.y);
    vec2 startMetric = vec2(start.x * ratio, start.y);
    vec2 endMetric = vec2(end.x * ratio, end.y);
    vec2 segment = endMetric - startMetric;
    float amount = clamp(
        dot(pointMetric - startMetric, segment)
            / max(0.000001, dot(segment, segment)),
        0.0,
        1.0
    );
    return length(pointMetric - (startMetric + segment * amount));
}

vec2 physicsCurvePoint(float side, float amount, float grab)
{
    float grabX = clamp(physicsGrabX, 0.0, 1.0);
    float grabXCoordinate = grabX * 2.0 - 1.0;
    float grabY = clamp(physicsGrabY, -0.92, 0.92);
    float lagXCoordinate = clamp(physicsLagX, 0.0, 1.0) * 2.0 - 1.0;
    float lagY = clamp(physicsLagY, -0.92, 0.92);
    float restY = clamp(physicsRestOffset, -0.72, 0.72);
    float edgeX = side < 0.0 ? -1.0 : 1.0;
    float span = side < 0.0 ? grabX * 2.0 : (1.0 - grabX) * 2.0;
    float tensionX = mix(grabXCoordinate, edgeX, amount);
    float tensionY = mix(grabY, restY, amount);

    float feel = floor(clamp(physicsFeel, 0.0, 2.0) + 0.5);
    float residualReach = feel > 1.5 ? 0.055 : (feel > 0.5 ? 0.13 : 0.085);
    float swayStrength = feel > 1.5 ? 0.010 : (feel > 0.5 ? 0.042 : 0.024);
    float swaySpeed = feel > 1.5 ? 0.48 : (feel > 0.5 ? 1.18 : 0.74);
    float gravityWeight = feel > 1.5 ? 1.18 : (feel > 0.5 ? 0.92 : 1.06);
    float slack = clamp(physicsSlack, 0.0, 4.0);
    float gravity = clamp(physicsGravity, 0.2, 4.0) * gravityWeight;
    float inertiaWeight = feel > 1.5 ? 0.58 : (feel > 0.5 ? 1.08 : 0.84);
    float ropeFollow = pow(amount, feel > 1.5 ? 1.42 : 1.08);
    float trailEnvelope = ropeFollow * (1.0 - amount * 0.10);
    float dragTrailX = (lagXCoordinate - grabXCoordinate)
        * trailEnvelope * inertiaWeight;
    float dragTrailY = (lagY - grabY) * trailEnvelope * inertiaWeight;
    float dragEnergy = length(vec2(
        (lagXCoordinate - grabXCoordinate) * max(0.25, aspectRatio),
        lagY - grabY
    ));
    float delayedReach = pow(amount, feel > 1.5 ? 2.45 : 2.05);
    float freeEndWeight = pow(amount, 1.18);
    float waveEnvelope = freeEndWeight * (0.28 + amount * 0.72);
    float primarySway = sin(
        idleTime * swaySpeed + side * 1.37 + amount * 5.1
    );
    float secondarySway = sin(
        idleTime * swaySpeed * 0.63 - side * 2.19 + amount * 8.7
    );
    float sway = (primarySway + secondarySway * 0.42)
        * swayStrength * waveEnvelope * gravity;
    float ropeWave = sin(amount * 5.7 + side * 0.82)
        * dragEnergy * (0.055 + slack * 0.018)
        * sin(amount * 3.14159265);
    float hangingX = grabXCoordinate
        + dragTrailX
        + side * span * residualReach * delayedReach
        + sway + side * ropeWave;
    float drop = clamp(
        (0.56 + span * 0.26) * gravity * (0.76 + slack * 0.32),
        0.34,
        1.84
    );
    float dropProfile = mix(pow(amount, 0.70), amount, 0.14);
    float verticalRipple = sin(
        idleTime * swaySpeed * 0.52 + side * 0.91 + amount * 6.4
    ) * swayStrength * 0.38 * waveEnvelope;
    float desiredDrop = max(
        0.0,
        drop * dropProfile + dragTrailY + verticalRipple
            + abs(sway) * 0.10 + abs(ropeWave) * 0.16
    );
    float availableDrop = max(0.04, 0.96 - grabY);
    float compressedDrop = availableDrop * (
        1.0 - exp(-desiredDrop / availableDrop * 1.72)
    );
    float hangingY = grabY + compressedDrop;
    return mix(vec2(tensionX, tensionY), vec2(hangingX, hangingY), grab);
}

void physicsThreadDistance(
    vec2 pointValue,
    float grab,
    out float distanceValue,
    out float visibility
)
{
    distanceValue = 10.0;
    visibility = 0.0;
    const int segmentCount = 22;
    for (int sideIndex = 0; sideIndex < 2; ++sideIndex) {
        float side = sideIndex == 0 ? -1.0 : 1.0;
        vec2 previous = physicsCurvePoint(side, 0.0, grab);
        for (int segmentIndex = 1; segmentIndex <= segmentCount; ++segmentIndex) {
            float amount = float(segmentIndex) / float(segmentCount);
            vec2 current = physicsCurvePoint(side, amount, grab);
            float candidate = physicsSegmentDistance(
                pointValue, previous, current
            );
            if (candidate < distanceValue) {
                distanceValue = candidate;
                float midpoint = (float(segmentIndex) - 0.5)
                    / float(segmentCount);
                visibility = 1.0 - smoothstep(0.72, 1.0, midpoint);
            }
            previous = current;
        }
    }
}

void main()
{
    vec2 p = qt_TexCoord0 * 2.0 - 1.0;
    float x = qt_TexCoord0.x;
    float physicsGrab = clamp(physicsGrabAmount, 0.0, 1.0);
    float variantId = floor(variation + 0.5);
    float silkMode = step(2.5, variantId);
    float standardEdgeFade = smoothstep(0.0, 0.18, x)
        * (1.0 - smoothstep(0.82, 1.0, x));
    float silkEdgeFade = smoothstep(0.0, 0.28, x)
        * (1.0 - smoothstep(0.72, 1.0, x));
    float baseEdgeFade = mix(standardEdgeFade, silkEdgeFade, silkMode);
    float edgeFade = baseEdgeFade
        * (1.0 - smoothstep(0.04, 0.82, physicsGrab));
    float reaction = clamp(audioReactivity, 0.0, 4.0);
    float voice = clamp(audioLevel * speakingReactivity * reaction, 0.0, 1.0);
    float heldPeak = clamp(peakLevel * speakingReactivity * reaction, 0.0, 1.0);
    float transient = clamp(max(0.0, heldPeak - voice * 0.92) * peakEmphasis * 2.4, 0.0, 1.0);
    float energy = clamp(voice + transient * 0.48, 0.0, 1.0);
    float vuEnergy = pow(energy, 0.72);
    float spectralMaximum = spectrumMaximum();
    float activeAmount = smoothstep(0.008, 0.035, max(voice, spectralMaximum));
    float spectralEnergy = pow(clamp(spectrumAt(x), 0.0, 1.0), 0.68);
    // Blend the spectrum lane in continuously. A hard threshold here made
    // low-energy band noise alternate the rendered curve on adjacent frames.
    float spectrumActive = smoothstep(0.002, 0.018, spectralMaximum);
    float localEnergy = mix(
        vuEnergy,
        max(vuEnergy * 0.18, spectralEnergy),
        spectrumActive
    );
    float configuredOverallScale = clamp(overallScale, 0.50, 2.60);
    float thicknessScale = mix(
        0.78,
        1.42,
        (configuredOverallScale - 0.50) / 2.10
    );
    float coreWidth = mix(0.0050, 0.0085, clamp(energy, 0.0, 1.0))
        * thicknessScale;
    float requestedHaloWidth = mix(
        0.013,
        0.070,
        clamp((glowRadius - 0.25) / 1.75, 0.0, 1.0)
    );
    requestedHaloWidth *= 1.0
        + clamp((glowRadius - 2.0) / 2.0, 0.0, 1.0) * 1.20;
    float glowAmount = clamp(glowIntensity, 0.0, 4.0);
    float haloWidth = mix(
        coreWidth * 1.8,
        requestedHaloWidth,
        min(1.0, glowAmount)
    );
    haloWidth *= mix(0.82, 1.36, (configuredOverallScale - 0.50) / 2.10);
    haloWidth *= 1.0 + max(0.0, glowAmount - 1.0) * 0.78;
    float ambientCeilingMain = clamp(ambientMotionCeiling, 0.25, 3.0);
    float ambientGlowDrive = min(
        ambientCeilingMain,
        max(clamp(ambientLevel, 0.0, ambientCeilingMain),
            clamp(ambientPeak, 0.0, ambientCeilingMain) * 0.55)
    ) * mix(1.0, 0.16, smoothstep(0.02, 0.55, energy));
    ambientGlowDrive *= smoothstep(
        0.0,
        max(0.004, clamp(ambientNoiseGate, 0.0, 0.25) * 0.5),
        ambientGlowDrive
    );
    float ambientHigh = ambientHighAverage();
    float ambientShimmer = ambientGlowDrive * ambientHigh
        * clamp(ambientHighShimmer, 0.0, 4.0)
        * clamp(ambientGlowStrength, 0.0, 12.0);
    float localAmbientFiber = ambientSpectrumAt(x);
    float ambientFiberDrive = min(
        ambientCeilingMain,
        ambientGlowDrive * (0.38 + localAmbientFiber * 0.62)
    );
    float ambientFiberToggle = step(0.5, ambientFiberSpreadEnabled);
    float ambientFiberExpansion = 1.0 + ambientFiberToggle
        * ambientFiberDrive * clamp(ambientFiberStrength, 0.0, 12.0) * 0.34;
    float ambientColorEnergy = clamp(
        ambientGlowDrive * clamp(ambientColorStrength, 0.0, 12.0),
        0.0,
        3.0
    );
    float voiceColorEnergy = max(energy, spectralMaximum);
    float idleGlow = step(0.001, idleMotion)
        * (0.34 + min(3.0, idleMotion) * 0.26)
        * (1.0 - activeAmount * 0.52);
    haloWidth *= 1.0 + idleGlow * 0.48;
    haloWidth *= 1.0 + ambientShimmer * (
        0.48 + 0.14 * sin(idleTime * 5.4 + x * 18.0)
    );
    float bodyY = voiceBodyY(x, activeAmount, energy, transient);
    bodyY += silkMode * (
        sin(x * 4.2 - idleTime * 0.43) * 0.012
        + sin(x * 8.7 + idleTime * 0.21) * 0.005
    ) * (0.45 + clamp(idleMotion, 0.0, 3.0) * 0.55);
    float looseEndAmount = 0.0;
    float centroidValue = clamp(spectralCentroid, 0.0, 1.0);
    float flux = clamp(
        spectralFlux * clamp(fluxStrength, 0.0, 4.0), 0.0, 1.0
    ) * activeAmount;
    vec3 color = vec3(0.0);
    float alpha = 0.0;

    float localX = x * 2.0 - 1.0;
    float configuredBendMain = clamp(bendiness, 0.0, 4.0);
    float bendAmplitudeMain = 0.35 + configuredBendMain * 0.65;
    float bendFrequencyMain = clamp(
        1.15 - configuredBendMain * 0.15, 0.775, 1.15
    );
    float lagDelta = (
        (postureLag - postureOffset)
        + (postureTiltLag - postureTilt) * localX
    ) * 0.065 * clamp(phraseMotion, 0.0, 4.0);
    float wakeVisibility = edgeFade * clamp(phraseEnergy, 0.0, 1.0)
        * clamp(motionMemory, 0.0, 1.0) * activeAmount * 0.28;
    addThread(
        abs(p.y - bodyY - lagDelta),
        audioReactiveTint(
            mix(primary.rgb, secondary.rgb, 0.48),
            x,
            0.48,
            voiceColorEnergy,
            ambientColorEnergy
        ),
        wakeVisibility * (1.0 - silkMode),
        coreWidth * 0.52,
        haloWidth * 0.48,
        color,
        alpha
    );

    vec3 spineTint = mix(
        highlight.rgb,
        mix(primary.rgb, secondary.rgb, centroidValue),
        0.18
    );
    spineTint = mix(
        spineTint,
        highlight.rgb,
        clamp(ambientShimmer * 0.22 + ambientColorEnergy * 0.10, 0.0, 0.46)
    );
    spineTint = audioReactiveTint(
        spineTint, x, 0.50, voiceColorEnergy, ambientColorEnergy
    );
    addThread(
        abs(p.y - bodyY),
        mix(primary.rgb, secondary.rgb, 0.42),
        edgeFade * idleGlow * 0.44 * (1.0 - silkMode),
        coreWidth * 0.72,
        haloWidth * 1.42,
        color,
        alpha
    );
    addThread(
        abs(p.y - bodyY),
        spineTint,
        edgeFade * mix(1.0, 0.18, silkMode),
        coreWidth * 1.05,
        haloWidth,
        color,
        alpha
    );

    if (physicsGrab > 0.001 && silkMode < 0.5) {
        float hangingDistance;
        float hangingVisibility;
        physicsThreadDistance(
            p, physicsGrab, hangingDistance, hangingVisibility
        );
        float hangingAlpha = hangingVisibility * smoothstep(
            0.0, 0.22, physicsGrab
        );
        addThread(
            hangingDistance,
            audioReactiveTint(
                mix(primary.rgb, secondary.rgb, 0.46),
                x,
                0.46,
                voiceColorEnergy,
                ambientColorEnergy
            ),
            hangingAlpha * 0.42,
            coreWidth * 0.82,
            haloWidth * 1.55,
            color,
            alpha
        );
        addThread(
            hangingDistance,
            audioReactiveTint(
                mix(highlight.rgb, primary.rgb, 0.24),
                x,
                0.24,
                voiceColorEnergy,
                ambientColorEnergy
            ),
            hangingAlpha,
            coreWidth * 1.12,
            haloWidth * 1.08,
            color,
            alpha
        );
    } else if (physicsGrab > 0.001) {
        for (int hangingStrand = 0; hangingStrand < 5; ++hangingStrand) {
            float strandValue = float(hangingStrand) - 2.0;
            float hangingDistance;
            float hangingVisibility;
            float strandShift = strandValue * 0.0065
            * clamp(fiberSpread, 0.25, 4.0);
            physicsThreadDistance(
                vec2(p.x, p.y - strandShift),
                physicsGrab,
                hangingDistance,
                hangingVisibility
            );
            float hangingAlpha = hangingVisibility * smoothstep(
                0.0, 0.18, physicsGrab
            );
            vec3 hangingTint = mix(
                primary.rgb,
                secondary.rgb,
                float(hangingStrand) / 4.0
            );
            hangingTint = audioReactiveTint(
                hangingTint,
                x,
                float(hangingStrand) / 4.0,
                voiceColorEnergy,
                ambientColorEnergy
            );
            addThread(
                hangingDistance,
                hangingTint,
                hangingAlpha,
                coreWidth * 0.58,
                haloWidth * 0.78,
                color,
                alpha
            );
        }
    }

    float idleFiberVisibility = idleGlow * (
        0.24 + min(1.0, clamp(idleMotion, 0.0, 3.0)) * 0.18
    );
    float ambientFiberVisibility = ambientFiberToggle
        * smoothstep(0.001, 0.10, ambientFiberDrive)
        * (0.22 + localAmbientFiber * 0.34);
    float fiberVisibility = max(
        activeAmount * (0.22 + localEnergy * 0.62),
        max(idleFiberVisibility, ambientFiberVisibility)
    );
    int configuredStrandMultiplier = int(floor(
        clamp(strandMultiplier, 1.0, 5.0) + 0.5
    ));
    int standardStrandCount = 4 * configuredStrandMultiplier;
    if (silkMode < 0.5) for (int fiber = 0; fiber < 20; ++fiber) {
        if (fiber >= standardStrandCount) {
            break;
        }
        float f = float(fiber);
        float fiberCenter = (float(standardStrandCount) - 1.0) * 0.5;
        float fiberBlend = f / max(1.0, float(standardStrandCount - 1));
        float fiberY = bodyY;
        float spread = clamp(fiberSpread, 0.25, 4.0)
            * ambientFiberExpansion;
        float separation = (f - fiberCenter)
            * (0.014 + energy * 0.010) * spread
            * configuredOverallScale;
        float fiberWidth = 0.55;
        float fiberHalo = 0.58;

        if (variantId > 0.5 && variantId < 1.5) {
            float role = mod(f, 4.0);
            float mirrorSide = role < 2.0 ? 1.0 : -1.0;
            float pairOffset = (mod(role, 2.0) - 0.5)
                * (0.016 + energy * 0.008);
            float layer = floor(f / 4.0)
                - (float(configuredStrandMultiplier) - 1.0) * 0.5;
            fiberY = mix(bodyY * mirrorSide, bodyY, physicsGrab);
            separation = (pairOffset + layer * 0.040) * spread
                * configuredOverallScale;
            fiberBlend = mirrorSide > 0.0 ? fiberBlend * 0.5 : 0.5 + fiberBlend * 0.5;
            fiberWidth = 0.58;
        } else if (variantId > 1.5) {
            separation = (f - fiberCenter)
                * (0.030 + energy * 0.014) * spread
                * configuredOverallScale;
            fiberWidth = mix(
                0.60,
                0.46,
                abs(f - fiberCenter) / max(1.0, fiberCenter)
            );
            fiberHalo = 0.62;
        }

        float gestureKind = floor(gestureType + 0.5);
        if (gestureKind > 1.5 && gestureKind < 2.5) {
            float forkSide = f < fiberCenter ? -1.0 : 1.0;
            separation += forkSide * gesturePulse()
            * clamp(gestureAmount, 0.0, 4.0)
                * sin(x * 3.14159265) * 0.025;
        }

        separation += (f - fiberCenter) * 0.020 * looseEndAmount;
        separation += sin(f * 2.17 + x * 9.0) * 0.006 * looseEndAmount;

        float micro = sin(
            p.x * (7.0 + f * 1.7) * bendFrequencyMain
                + time * (0.25 + f * 0.04)
        ) * 0.006 * activeAmount * bendAmplitudeMain;
        vec3 fiberTint = mix(primary.rgb, secondary.rgb, clamp(fiberBlend, 0.0, 1.0));
        fiberTint = audioReactiveTint(
            fiberTint,
            x,
            clamp(fiberBlend, 0.0, 1.0),
            voiceColorEnergy,
            ambientColorEnergy
        );
        addThread(
            abs(p.y - fiberY - separation - micro),
            fiberTint,
            edgeFade * fiberVisibility,
            coreWidth * fiberWidth,
            haloWidth * fiberHalo,
            color,
            alpha
        );
    }

    if (silkMode > 0.5) {
        float silkSpread = clamp(fiberSpread, 0.25, 4.0)
            * ambientFiberExpansion;
        float tailEnvelope = pow(max(0.0, 1.0 - x), 1.42);
        float leadingFocus = smoothstep(0.42, 0.90, x);
        float silkVisibility = edgeFade * (
            0.52 + idleGlow * 0.26 + activeAmount * (0.18 + localEnergy * 0.30)
        );
        int silkStrandCount = 7 * configuredStrandMultiplier;
        float silkStrandCenter = (float(silkStrandCount) - 1.0) * 0.5;
        for (int silkStrand = 0; silkStrand < 35; ++silkStrand) {
            if (silkStrand >= silkStrandCount) {
                break;
            }
            float strandValue = float(silkStrand) - silkStrandCenter;
            float strandBlend = float(silkStrand)
                / max(1.0, float(silkStrandCount - 1));
            float strandPhase = float(silkStrand) * 1.37;
            float strandSeparation = strandValue * 0.0230 * silkSpread
                * (0.34 + tailEnvelope * 0.92) * configuredOverallScale;
            float strandWake = sin(
                x * (7.0 + float(silkStrand) * 0.34)
                    - idleTime * (0.44 + float(silkStrand) * 0.025)
                    + strandPhase
            ) * (0.004 + tailEnvelope * 0.010)
            * clamp(organicVariation, 0.0, 4.0);
            float strandAudio = sin(
                x * 12.0 + time * 0.42 + strandPhase
        ) * localEnergy * 0.008 * clamp(motionScale, 0.0, 4.0);
            float strandY = bodyY + strandSeparation + strandWake + strandAudio;
            vec3 strandTint = mix(
                primary.rgb,
                secondary.rgb,
                clamp(strandBlend * 0.78 + leadingFocus * 0.12, 0.0, 1.0)
            );
            strandTint = mix(
                strandTint,
                highlight.rgb,
                leadingFocus * (0.08 + localEnergy * 0.18)
            );
            strandTint = audioReactiveTint(
                strandTint,
                x,
                strandBlend,
                voiceColorEnergy,
                ambientColorEnergy
            );
            addThread(
                abs(p.y - strandY),
                strandTint,
                silkVisibility,
                coreWidth * mix(
                    0.42,
                    0.64,
                    1.0 - abs(strandValue) / max(1.0, silkStrandCenter)
                ),
                haloWidth * mix(
                    0.45,
                    0.72,
                    1.0 - abs(strandValue) / max(1.0, silkStrandCenter)
                ),
                color,
                alpha
            );
        }

        float leaderAlong = exp(-pow((x - 0.84) / 0.115, 2.0));
        float leaderAcross = 1.0 - smoothstep(
            coreWidth * 0.55,
            max(coreWidth, haloWidth * 0.62),
            abs(p.y - bodyY)
        );
        float leader = leaderAlong * leaderAcross * edgeFade
            * (0.20 + activeAmount * 0.26 + transient * 0.34);
        color += highlight.rgb * leader * 0.82;
        alpha = max(alpha, leader * 0.72);
    }

    vec3 nodeTint = mix(primary.rgb, secondary.rgb, centroidValue);
    nodeTint = audioReactiveTint(
        nodeTint, x, centroidValue, voiceColorEnergy, ambientColorEnergy
    );
    for (int nodeIndex = 0; nodeIndex < 12; ++nodeIndex) {
        float nodeX = float(nodeIndex) / 11.0;
        float nodeBand = pow(clamp(spectrumBand(nodeIndex), 0.0, 1.0), 0.72);
        float nodeBodyY = voiceBodyY(
            nodeX, activeAmount, energy, transient
        );
        float nodeRadius = min(
            haloWidth * 0.42,
            coreWidth * (0.68 + nodeBand * 0.82)
        );
        float nodeVisibility = edgeFade * activeAmount * nodeBand * 0.76;
        addNode(
            vec2((x - nodeX) * 2.0, p.y - nodeBodyY),
            nodeRadius,
            nodeTint,
            nodeVisibility,
            color,
            alpha
        );
    }

    float gestureWave = gesturePulse() * clamp(gestureAmount, 0.0, 4.0);
    float gestureTravel = gestureSeed < 0.0
        ? 1.0 - clamp(gestureProgress, 0.0, 1.0)
        : clamp(gestureProgress, 0.0, 1.0);
    float impulseX = gestureWave > 0.002
        ? gestureTravel
        : fract(time * 0.42 + 0.08 + centroidValue * 0.24);
    float impulseAlong = exp(-pow((x - impulseX) / 0.040, 2.0));
    float impulseAcross = 1.0 - smoothstep(
        coreWidth * 0.70,
        max(coreWidth, haloWidth * 0.52),
        abs(p.y - bodyY)
    );
    float impulseDrive = max(flux, min(1.0, gestureWave));
    float impulse = impulseAlong * impulseAcross * impulseDrive * edgeFade;
    float secondImpulseX = fract(impulseX + 0.47);
    float secondImpulse = exp(-pow((x - secondImpulseX) / 0.032, 2.0))
        * impulseAcross * smoothstep(0.58, 1.0, impulseDrive)
        * impulseDrive * edgeFade * 0.52;
    float impulseEnergy = impulse + secondImpulse;
    vec3 impulseTint = mix(highlight.rgb, nodeTint, centroidValue * 0.22);
    color += impulseTint * impulseEnergy * 1.55;
    alpha = max(alpha, clamp(impulseEnergy * 0.88, 0.0, 1.0));

    float visibleEnergy = max(0.10, max(vuEnergy, localEnergy));
    float finalVisibility = max(
        edgeFade,
        smoothstep(0.0, 0.22, physicsGrab)
    );
    alpha = clamp(alpha, 0.0, 1.0) * finalVisibility
        * mix(0.62, 1.0, visibleEnergy);
    float glowBrightness = 0.65 + glowAmount * 0.35
        + ambientColorEnergy * 0.10;
    color = min(
        color * (0.58 + visibleEnergy * 0.82 + transient * 0.24)
            * glowBrightness,
        vec3(1.65)
    );
    fragColor = vec4(color * alpha, alpha) * qt_Opacity;
}
