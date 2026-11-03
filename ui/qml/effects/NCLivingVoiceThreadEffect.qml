pragma ComponentBehavior: Bound

import QtQuick 6.4

Item {
    id: root
    objectName: "ncLivingVoiceThreadEffect"

    property string variation: "silk_ribbon"
    property int strandMultiplier: 1
    property real audioLevel: 0.0
    property real peakLevel: 0.0
    property var voiceSpectrumBands: []
    property real spectralFlux: 0.0
    property real spectralCentroid: 0.0
    // Backward-compatible desktop/output-audio spectrum property.
    property var spectrumBands: []
    property real spectrumStrength: 1.0
    property real musicReactivity: 2.80
    property bool ambientAudioEnabled: true
    property real ambientAudioLevel: 0.0
    property real ambientPeakLevel: 0.0
    property string ambientReactionTarget: "shape_glow"
    property real ambientSmoothing: 0.72
    property real ambientNoiseGate: 0.04
    property real ambientQuietDetail: 1.40
    property real ambientTransientPunch: 1.60
    property int ambientAttackMs: 35
    property int ambientReleaseMs: 260
    property real ambientMix: 1.45
    property bool ambientLinkMainControls: true
    property bool ambientFiberSpreadEnabled: true
    property real ambientShapeStrength: 1.80
    property real ambientTravelStrength: 1.35
    property real ambientGlowStrength: 1.65
    property real ambientFiberStrength: 1.25
    property real ambientColorStrength: 1.50
    property bool audioColorsEnabled: true
    property bool voiceColorsEnabled: true
    property bool desktopColorsEnabled: true
    property real colorVividness: 1.0
    property real colorBassInfluence: 1.0
    property real colorMidInfluence: 1.0
    property real colorHighInfluence: 1.0
    property real colorSmoothing: 0.65
    property real ambientMotionCeiling: 2.20
    property real ambientBassBend: 0.55
    property real ambientMidRipple: 0.38
    property real ambientHighShimmer: 0.42
    property real speakingReactivity: 0.85
    property real peakEmphasis: 0.60
    property real glowRadius: 1.0
    property string motionStyle: "organic_drift"
    property real audioReactivity: 1.0
    property real motionScale: 1.0
    property real idleMotion: 0.16
    property real animationSpeed: 1.0
    property real responseSmoothing: 0.58
    property real spectrumSmoothing: 0.45
    property real spectrumScale: 1.0
    property real glowIntensity: 1.0
    property real fluxStrength: 1.0
    property real fiberSpread: 1.0
    property real bendiness: 1.0
    property real organicVariation: 1.0
    property real phraseMotion: 1.0
    property real gestureIntensity: 1.0
    property real motionMemory: 0.65
    property real accentSensitivity: 0.55
    property real physicsRestOffset: 0.0
    property real physicsGrabX: 0.5
    property real physicsGrabY: 0.0
    property real physicsLagX: physicsGrabX
    property real physicsLagY: physicsGrabY
    property real physicsGrabAmount: 0.0
    property real physicsSlack: 1.0
    property string physicsFeel: "natural"
    property real physicsGravity: 1.2
    property real contentVerticalScale: 1.0
    property real overallScale: 1.0
    property int frameRate: 60
    property bool running: true
    property bool animateWhenHidden: false
    property bool reducedEffects: false
    property bool shadersEnabled: true
    property bool opaqueBackground: false
    property color primaryColor: "#22d3ee"
    property color secondaryColor: "#a78bfa"
    property color highlightColor: "#ecfeff"
    property color backgroundColor: "#030712"
    property real backgroundDarkness: 1.0
    property real phase: 0.0
    property real idlePhase: 0.0
    property real colorPhase: 0.0
    property real vuLevel: 0.0
    property real vuPeak: 0.0
    // Audio analysis frames arrive less often than render frames. Keep a
    // presentation-only spectrum state so band changes cannot make the GPU
    // shape jump between two consecutive frames.
    property var smoothedVoiceSpectrumBands: [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    ]
    property var smoothedAmbientSpectrumBands: [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    ]
    property real smoothedSpectralFlux: 0.0
    property real smoothedSpectralCentroid: 0.0
    property real ambientVuLevel: 0.0
    property real ambientVuPeak: 0.0
    property real previousAmbientInput: 0.0
    property real ambientTransientEnvelope: 0.0
    property real phraseEnergy: 0.0
    property real postureOffset: 0.0
    property real postureTilt: 0.0
    property real postureLag: 0.0
    property real postureTiltLag: 0.0
    property real postureTarget: 0.0
    property real postureTiltTarget: 0.0
    property real gestureAmount: 0.0
    property real gestureProgress: 1.0
    property real gestureDuration: 0.8
    property real gestureSeed: 0.0
    property int gestureType: 0
    property int lastGestureType: 0
    property int gestureCounter: 0
    property real gestureCooldown: 0.0
    property real postureRetargetTimer: 0.0
    property real previousDrive: 0.0
    property bool phraseActive: false
    property bool accentArmed: true

    readonly property int effectiveFrameRate: reducedEffects
        ? Math.min(24, frameRate) : Math.max(15, Math.min(120, frameRate))
    readonly property real variationCode: variation === "double_helix"
        ? 1.0 : (variation === "harmonic_threads"
            ? 2.0 : (variation === "silk_drift" ? 3.0 : 0.0))
    readonly property real motionStyleCode: motionStyle === "breathing_ribbon"
        ? 1.0 : (motionStyle === "tidal_sweep"
            ? 2.0 : (motionStyle === "resonant_bloom" ? 3.0 : 0.0))
    readonly property real physicsFeelCode: physicsFeel === "silk"
        ? 1.0 : (physicsFeel === "cable" ? 2.0 : 0.0)
    readonly property real effectiveGlowRadius: shadersEnabled
        ? Math.max(0.25, Math.min(4.0, glowRadius)) : 0.25
    readonly property real effectiveAmbientNoiseGate:
        mappedAmbientNoiseGate(ambientNoiseGate)
    readonly property real amplifiedAmbientLevel: amplifiedAmbientSample(
        ambientAudioLevel, musicReactivity)
    readonly property real amplifiedAmbientPeak: Math.max(
        amplifiedAmbientLevel,
        amplifiedAmbientSample(ambientPeakLevel, musicReactivity)
    )
    readonly property real ambientReactionTargetCode:
        ambientReactionTarget === "glow_only" ? 0.0
        : (ambientReactionTarget === "full_spectrum" ? 2.0 : 1.0)
    readonly property vector4d spectrum0: Qt.vector4d(
        voiceBand(0), voiceBand(1), voiceBand(2), voiceBand(3))
    readonly property vector4d spectrum1: Qt.vector4d(
        voiceBand(4), voiceBand(5), voiceBand(6), voiceBand(7))
    readonly property vector4d spectrum2: Qt.vector4d(
        voiceBand(8), voiceBand(9), voiceBand(10), voiceBand(11))
    readonly property vector4d ambientSpectrum0: Qt.vector4d(
        ambientBand(0), ambientBand(1), ambientBand(2), ambientBand(3))
    readonly property vector4d ambientSpectrum1: Qt.vector4d(
        ambientBand(4), ambientBand(5), ambientBand(6), ambientBand(7))
    readonly property vector4d ambientSpectrum2: Qt.vector4d(
        ambientBand(8), ambientBand(9), ambientBand(10), ambientBand(11))

    function normalizedBand(bands, index) {
        if (!bands || index < 0 || index >= bands.length)
            return 0.0
        return Math.max(0.0, Math.min(1.0, Number(bands[index]) || 0.0))
    }

    function rawVoiceBand(index) {
        return root.normalizedBand(root.voiceSpectrumBands, index)
    }

    function voiceBand(index) {
        return root.normalizedBand(root.smoothedVoiceSpectrumBands, index)
    }

    function rawAmbientBand(index) {
        if (!root.ambientAudioEnabled)
            return 0.0
        var musicStrength = Math.max(
            0.0,
            Math.min(2.0, Number(root.spectrumStrength) || 0.0)
                * root.clampQuad(root.musicReactivity)
        )
        return root.amplifiedAmbientSample(
            root.normalizedBand(root.spectrumBands, index), musicStrength)
    }

    function ambientBand(index) {
        if (!root.smoothedAmbientSpectrumBands || index < 0
                || index >= root.smoothedAmbientSpectrumBands.length)
            return 0.0
        return Math.max(0.0, Math.min(
            root.ambientMotionCeiling,
            Number(root.smoothedAmbientSpectrumBands[index]) || 0.0))
    }

    function smoothSpectrumFrame(previousBands, ambient, smoothing, dt) {
        var configuredSmoothing = root.clampDouble(smoothing)
        var primarySmoothing = Math.min(1.0, configuredSmoothing)
        var extraSmoothing = Math.max(0.0, configuredSmoothing - 1.0)
        var attackTau = 0.012 + primarySmoothing * 0.045
            + extraSmoothing * 0.070
        var releaseTau = 0.045 + primarySmoothing * 0.120
            + extraSmoothing * 0.200
        var nextBands = []
        for (var index = 0; index < 12; ++index) {
            var current = ambient
                ? Math.max(0.0, Math.min(root.ambientMotionCeiling,
                    Number(previousBands[index]) || 0.0))
                : root.normalizedBand(previousBands, index)
            var target = ambient
                ? root.rawAmbientBand(index) : root.rawVoiceBand(index)
            var tau = target > current ? attackTau : releaseTau
            var follow = 1.0 - Math.exp(-dt / Math.max(0.008, tau))
            var value = current + (target - current) * follow
            if (target < 0.001 && value < 0.0015)
                value = 0.0
            nextBands.push(ambient
                ? Math.max(0.0, Math.min(root.ambientMotionCeiling, value))
                : root.clampUnit(value))
        }
        return nextBands
    }

    function clampUnit(value) {
        return Math.max(0.0, Math.min(1.0, Number(value) || 0.0))
    }

    function clampDouble(value) {
        return Math.max(0.0, Math.min(2.0, Number(value) || 0.0))
    }

    function clampQuad(value) {
        return Math.max(0.0, Math.min(4.0, Number(value) || 0.0))
    }

    function amplifiedAmbientSample(value, strength) {
        if (!root.ambientAudioEnabled)
            return 0.0
        var normalized = root.clampUnit(value)
        var influence = root.clampQuad(strength)
        if (normalized <= 0.0 || influence <= 0.0)
            return 0.0
        var gate = root.effectiveAmbientNoiseGate
        if (normalized <= gate)
            return 0.0
        var gated = (normalized - gate) / Math.max(0.05, 1.0 - gate)
        var detail = Math.max(0.0, Math.min(
            2.5, Number(root.ambientQuietDetail) || 0.0))
        var perceptual = Math.pow(gated, 1.0 / (1.0 + detail * 0.62))
        var gain = influence * Math.max(
            0.0, Math.min(2.0, Number(root.ambientMix) || 0.0))
        return Math.min(root.ambientMotionCeiling, perceptual * gain)
    }

    function mappedAmbientNoiseGate(value) {
        var configured = Math.max(0.0, Number(value) || 0.0)
        if (configured > 0.25 && configured <= 2.0)
            return Math.min(0.10, configured * 0.04)
        return Math.min(0.25, configured)
    }

    function signedNoise(seed) {
        var value = Math.sin(Number(seed) * 12.9898 + 78.233) * 43758.5453
        return (value - Math.floor(value)) * 2.0 - 1.0
    }

    function retargetPosture(seed, centroid, scale) {
        var organic = root.clampQuad(root.organicVariation)
        var amount = organic * Math.max(0.0, Number(scale) || 0.0)
        var centerBias = (root.clampUnit(centroid) - 0.5) * 0.36
        root.postureTarget = Math.max(-1.0, Math.min(
            1.0,
            root.signedNoise(seed + 1.7) * amount + centerBias * amount
        ))
        root.postureTiltTarget = Math.max(-1.0, Math.min(
            1.0,
            root.signedNoise(seed + 9.3) * amount
        ))
    }

    function beginGesture(accent, centroid) {
        root.gestureCounter += 1
        var candidate = 1 + Math.floor(
            (root.signedNoise(root.gestureCounter * 4.31 + centroid * 7.9) + 1.0)
                * 1.9999
        )
        if (candidate === root.lastGestureType)
            candidate = candidate % 4 + 1
        root.lastGestureType = candidate
        root.gestureType = candidate
        root.gestureSeed = root.signedNoise(root.gestureCounter * 8.17 + 3.4)
        root.gestureProgress = 0.0
        root.gestureDuration = 0.48 + (1.0 - root.clampUnit(centroid)) * 0.34
            + Math.abs(root.gestureSeed) * 0.24
        root.gestureAmount = root.clampUnit(accent)
            * root.clampQuad(root.gestureIntensity)
        var sensitivity = root.clampQuad(root.accentSensitivity)
        root.gestureCooldown = Math.max(
            0.08,
            0.24 + (1.0 - Math.min(1.0, sensitivity)) * 0.42
                - Math.max(0.0, sensitivity - 1.0) * 0.12
        )
        root.retargetPosture(
            root.gestureCounter * 13.7,
            centroid,
            0.22 + root.gestureAmount * 0.34
        )
    }

    Timer {
        interval: Math.max(8, Math.round(1000 / root.effectiveFrameRate))
        repeat: true
        running: root.running && (root.visible || root.animateWhenHidden)
        onTriggered: {
            var dt = interval / 1000.0
            var target = Math.max(0.0, Math.min(1.0, root.audioLevel))
            var smoothing = root.clampDouble(root.responseSmoothing)
            var primarySmoothing = Math.min(1.0, smoothing)
            var extraSmoothing = Math.max(0.0, smoothing - 1.0)
            var attack = target > root.vuLevel
                ? 0.92 - primarySmoothing * 0.60
                : 0.50 - primarySmoothing * 0.42
            attack *= 1.0 - extraSmoothing * 0.60
            root.vuLevel += (target - root.vuLevel) * attack
            if (target < 0.002 && root.vuLevel < 0.003)
                root.vuLevel = 0.0

            var targetPeak = target > 0.002
                ? Math.max(target, Math.max(0.0, Math.min(1.0, root.peakLevel))) : 0.0
            var peakAttack = (0.94 - primarySmoothing * 0.42)
                * (1.0 - extraSmoothing * 0.56)
            var peakRelease = (0.28 - primarySmoothing * 0.20)
                * (1.0 - extraSmoothing * 0.58)
            if (targetPeak > root.vuPeak)
                root.vuPeak += (targetPeak - root.vuPeak) * peakAttack
            else
                root.vuPeak += (targetPeak - root.vuPeak) * peakRelease
            if (targetPeak < 0.002 && root.vuPeak < 0.003)
                root.vuPeak = 0.0

            var ambientRaw = root.amplifiedAmbientLevel
            var ambientPeakRaw = root.amplifiedAmbientPeak
            var onset = Math.max(0.0, ambientRaw - root.previousAmbientInput)
            var transientTarget = Math.min(
                root.ambientMotionCeiling,
                onset * Math.max(0.0, Math.min(
                    3.0, root.ambientTransientPunch)) * 3.2
            )
            var transientAttack = 1.0 - Math.exp(-dt / 0.012)
            var transientRelease = 1.0 - Math.exp(-dt / 0.105)
            root.ambientTransientEnvelope += (
                transientTarget - root.ambientTransientEnvelope
            ) * (transientTarget > root.ambientTransientEnvelope
                ? transientAttack : transientRelease)
            root.previousAmbientInput = ambientRaw
            var ambientTarget = Math.min(
                root.ambientMotionCeiling,
                ambientRaw + root.ambientTransientEnvelope
            )
            var ambientPeakTarget = Math.min(
                root.ambientMotionCeiling,
                Math.max(ambientPeakRaw,
                    ambientTarget + root.ambientTransientEnvelope * 0.35)
            )
            var attackTau = Math.max(0.005, root.ambientAttackMs / 1000.0)
            var releaseTau = Math.max(0.040, root.ambientReleaseMs / 1000.0)
            var ambientFollow = 1.0 - Math.exp(
                -dt / (ambientTarget > root.ambientVuLevel
                    ? attackTau : releaseTau))
            root.ambientVuLevel += (ambientTarget - root.ambientVuLevel)
                * ambientFollow
            var ambientPeakFollow = 1.0 - Math.exp(
                -dt / (ambientPeakTarget > root.ambientVuPeak
                    ? attackTau * 0.72 : releaseTau * 1.15))
            root.ambientVuPeak += (ambientPeakTarget - root.ambientVuPeak)
                * ambientPeakFollow
            if (ambientTarget < 0.001 && root.ambientVuLevel < 0.002)
                root.ambientVuLevel = 0.0
            if (ambientPeakTarget < 0.001 && root.ambientVuPeak < 0.002)
                root.ambientVuPeak = 0.0

            root.smoothedVoiceSpectrumBands = root.smoothSpectrumFrame(
                root.smoothedVoiceSpectrumBands,
                false,
                root.spectrumSmoothing,
                dt
            )
            root.smoothedAmbientSpectrumBands = root.smoothSpectrumFrame(
                root.smoothedAmbientSpectrumBands,
                true,
                root.ambientSmoothing,
                dt
            )

            var spectrumSmooth = root.clampDouble(root.spectrumSmoothing)
            var spectrumPrimarySmooth = Math.min(1.0, spectrumSmooth)
            var spectrumExtraSmooth = Math.max(0.0, spectrumSmooth - 1.0)
            var fluxTarget = root.clampUnit(root.spectralFlux)
            var fluxTau = fluxTarget > root.smoothedSpectralFlux
                ? 0.018 + spectrumPrimarySmooth * 0.032
                    + spectrumExtraSmooth * 0.050
                : 0.080 + spectrumPrimarySmooth * 0.130
                    + spectrumExtraSmooth * 0.180
            var fluxFollow = 1.0 - Math.exp(
                -dt / Math.max(0.008, fluxTau))
            root.smoothedSpectralFlux += (
                fluxTarget - root.smoothedSpectralFlux) * fluxFollow
            if (fluxTarget < 0.001 && root.smoothedSpectralFlux < 0.0015)
                root.smoothedSpectralFlux = 0.0

            var centroidTarget = root.clampUnit(root.spectralCentroid)
            var centroidTau = 0.055 + spectrumPrimarySmooth * 0.095
                + spectrumExtraSmooth * 0.120
            var centroidFollow = 1.0 - Math.exp(
                -dt / Math.max(0.012, centroidTau))
            root.smoothedSpectralCentroid += (
                centroidTarget - root.smoothedSpectralCentroid
            ) * centroidFollow
            if (centroidTarget < 0.001
                    && root.smoothedSpectralCentroid < 0.003)
                root.smoothedSpectralCentroid = 0.0

            var drive = Math.max(root.vuLevel, root.vuPeak * 0.48)
            root.idlePhase += dt * root.animationSpeed
                * (root.reducedEffects ? 0.18 : 0.38)
            var colorEnergy = Math.max(root.vuPeak, root.ambientVuPeak)
            var colorAdvance = dt * root.animationSpeed
                * (1.0 + colorEnergy * 1.35)
                * (root.reducedEffects ? 0.72 : 1.0)
            root.colorPhase = (root.colorPhase + colorAdvance)
                % (Math.PI * 2.0)
            if (drive > 0.003) {
                root.phase += dt * root.animationSpeed
                    * (0.12 + drive * 0.95)
                    * (root.reducedEffects ? 0.72 : 1.0)
            }

            var memory = root.clampDouble(root.motionMemory)
            var phraseTarget = Math.max(target, targetPeak * 0.42)
            var phraseTau = phraseTarget > root.phraseEnergy
                ? 0.11 + memory * 0.10 : 0.42 + memory * 0.88
            var phraseFollow = 1.0 - Math.exp(-dt / phraseTau)
            root.phraseEnergy += (phraseTarget - root.phraseEnergy) * phraseFollow
            if (root.phraseEnergy < 0.001 && phraseTarget < 0.001)
                root.phraseEnergy = 0.0

            var nowActive = drive > 0.028 || root.phraseEnergy > 0.020
            if (nowActive && !root.phraseActive) {
                root.phraseActive = true
                root.gestureCounter += 1
                root.retargetPosture(
                    root.gestureCounter * 5.73,
                    root.spectralCentroid,
                    0.34
                )
                root.postureRetargetTimer = 1.8
            } else if (!nowActive && root.phraseActive
                    && root.phraseEnergy < 0.010) {
                root.phraseActive = false
                root.postureRetargetTimer = 0.0
            }

            root.gestureCooldown = Math.max(0.0, root.gestureCooldown - dt)
            var levelRise = Math.max(0.0, drive - root.previousDrive)
            var accentPeakAttack = Math.max(0.0, targetPeak - root.vuLevel)
            var accent = Math.max(
                root.clampUnit(root.spectralFlux) * 1.12,
                Math.min(1.0, levelRise * 3.4),
                Math.min(1.0, accentPeakAttack * 1.7)
            )
            var sensitivity = root.clampQuad(root.accentSensitivity)
            var accentThreshold = 0.64
                - Math.min(1.0, sensitivity) * 0.42
                - Math.max(0.0, sensitivity - 1.0) * 0.10
            if (accent < accentThreshold * 0.62)
                root.accentArmed = true
            if (nowActive && root.gestureCooldown <= 0.0
                    && root.accentArmed && accent > accentThreshold) {
                var normalizedAccent = (accent - accentThreshold)
                    / Math.max(0.05, 1.0 - accentThreshold)
                root.accentArmed = false
                root.beginGesture(
                    0.32 + root.clampUnit(normalizedAccent) * 0.68,
                    root.spectralCentroid
                )
            }

            if (root.gestureProgress < 1.0) {
                root.gestureProgress = Math.min(
                    1.0,
                    root.gestureProgress + dt / Math.max(0.12, root.gestureDuration)
                )
                if (root.gestureProgress >= 1.0)
                    root.gestureAmount = 0.0
            }

            root.postureRetargetTimer -= dt
            if (root.postureRetargetTimer <= 0.0) {
                root.gestureCounter += 1
                root.retargetPosture(
                    root.gestureCounter * 2.91 + root.idlePhase,
                    root.spectralCentroid,
                    root.phraseActive ? 0.24 : 0.10
                )
                var intervalNoise = Math.abs(
                    root.signedNoise(root.gestureCounter * 6.19)
                )
                root.postureRetargetTimer = root.phraseActive
                    ? 1.7 + intervalNoise * 2.0 : 3.8 + intervalNoise * 4.6
            }

            var postureTau = 0.12 + memory * 0.92
            var postureFollow = 1.0 - Math.exp(-dt / postureTau)
            root.postureOffset += (root.postureTarget - root.postureOffset)
                * postureFollow
            root.postureTilt += (root.postureTiltTarget - root.postureTilt)
                * postureFollow
            var lagTau = 0.48 + memory * 1.85
            var lagFollow = 1.0 - Math.exp(-dt / lagTau)
            root.postureLag += (root.postureOffset - root.postureLag) * lagFollow
            root.postureTiltLag += (root.postureTilt - root.postureTiltLag)
                * lagFollow
            root.previousDrive = drive
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: root.opaqueBackground
        color: Qt.rgba(
            root.backgroundColor.r * (0.72 + root.backgroundDarkness * 0.18),
            root.backgroundColor.g * (0.72 + root.backgroundDarkness * 0.18),
            root.backgroundColor.b * (0.72 + root.backgroundDarkness * 0.18),
            0.90
        )
    }

    ShaderEffect {
        id: voiceThreadShader
        objectName: "ncLivingVoiceThreadShader"
        anchors.fill: parent
        blending: true

        property real time: root.phase
        property real audioLevel: root.vuLevel
        property real peakLevel: Math.max(audioLevel, root.vuPeak)
        property real ambientLevel: root.ambientVuLevel
        property real ambientPeak: Math.max(ambientLevel, root.ambientVuPeak)
        property real ambientReactionTarget: root.ambientReactionTargetCode
        property real ambientNoiseGate: root.effectiveAmbientNoiseGate
        property real ambientLinkMainControls:
            root.ambientLinkMainControls ? 1.0 : 0.0
        property real ambientFiberSpreadEnabled:
            root.ambientFiberSpreadEnabled ? 1.0 : 0.0
        property real ambientShapeStrength: Math.max(
            0.0, Math.min(12.0, root.ambientShapeStrength))
        property real ambientTravelStrength: Math.max(
            0.0, Math.min(12.0, root.ambientTravelStrength))
        property real ambientGlowStrength: Math.max(
            0.0, Math.min(12.0, root.ambientGlowStrength))
        property real ambientFiberStrength: Math.max(
            0.0, Math.min(12.0, root.ambientFiberStrength))
        property real ambientColorStrength: Math.max(
            0.0, Math.min(12.0, root.ambientColorStrength))
        property real audioColorsEnabled:
            root.audioColorsEnabled ? 1.0 : 0.0
        property real voiceColorsEnabled:
            root.voiceColorsEnabled ? 1.0 : 0.0
        property real desktopColorsEnabled:
            root.desktopColorsEnabled ? 1.0 : 0.0
        property real colorVividness: Math.max(
            0.0, Math.min(4.0, root.colorVividness))
        property real colorBassInfluence: Math.max(
            0.0, Math.min(4.0, root.colorBassInfluence))
        property real colorMidInfluence: Math.max(
            0.0, Math.min(4.0, root.colorMidInfluence))
        property real colorHighInfluence: Math.max(
            0.0, Math.min(4.0, root.colorHighInfluence))
        property real colorSmoothing: Math.max(
            0.0, Math.min(2.0, root.colorSmoothing))
        property real ambientMotionCeiling: Math.max(
            0.25, Math.min(3.0, root.ambientMotionCeiling))
        property real ambientBassBend: Math.max(
            0.0, Math.min(4.0, root.ambientBassBend))
        property real ambientMidRipple: Math.max(
            0.0, Math.min(4.0, root.ambientMidRipple))
        property real ambientHighShimmer: Math.max(
            0.0, Math.min(4.0, root.ambientHighShimmer))
        property real speakingReactivity: Math.max(0.10, Math.min(1.50, root.speakingReactivity))
        property real peakEmphasis: Math.max(0.0, Math.min(4.0, root.peakEmphasis))
        property real glowRadius: root.effectiveGlowRadius
        property real variation: root.variationCode
        property real strandMultiplier: Math.max(
            1.0, Math.min(5.0, root.strandMultiplier))
        property real idleTime: root.idlePhase
        property real idleMotion: Math.max(0.0, Math.min(3.0, root.idleMotion))
            * (root.reducedEffects ? 0.40 : 1.0)
        property real motionStyle: root.motionStyleCode
        property real audioReactivity: Math.max(0.0, Math.min(4.0, root.audioReactivity))
        property real motionScale: Math.max(0.0, Math.min(4.0, root.motionScale))
            * (root.reducedEffects ? 0.60 : 1.0)
        property real spectrumSmoothing: Math.max(
            0.0, Math.min(2.0, root.spectrumSmoothing))
        property real spectrumScale: Math.max(0.0, Math.min(4.0, root.spectrumScale))
        property real glowIntensity: Math.max(0.0, Math.min(4.0, root.glowIntensity))
        property real fluxStrength: Math.max(0.0, Math.min(4.0, root.fluxStrength))
        property real fiberSpread: Math.max(0.25, Math.min(4.0, root.fiberSpread))
        property real bendiness: Math.max(0.0, Math.min(4.0, root.bendiness))
        property real organicVariation: Math.max(
            0.0, Math.min(4.0, root.organicVariation))
        property real phraseMotion: Math.max(0.0, Math.min(4.0, root.phraseMotion))
        property real phraseEnergy: Math.max(0.0, Math.min(1.0, root.phraseEnergy))
        property real postureOffset: Math.max(-1.0, Math.min(1.0, root.postureOffset))
        property real postureTilt: Math.max(-1.0, Math.min(1.0, root.postureTilt))
        property real postureLag: Math.max(-1.0, Math.min(1.0, root.postureLag))
        property real postureTiltLag: Math.max(
            -1.0, Math.min(1.0, root.postureTiltLag))
        property real gestureAmount: Math.max(
            0.0, Math.min(2.0, root.gestureAmount))
        property real gestureProgress: Math.max(
            0.0, Math.min(1.0, root.gestureProgress))
        property real gestureType: root.gestureType
        property real gestureSeed: root.gestureSeed
        property real motionMemory: Math.max(0.0, Math.min(2.0, root.motionMemory))
        property real physicsRestOffset: Math.max(
            -0.72, Math.min(0.72, root.physicsRestOffset))
        property real physicsGrabX: Math.max(0.0, Math.min(1.0, root.physicsGrabX))
        property real physicsGrabY: Math.max(-0.92, Math.min(0.92, root.physicsGrabY))
        property real physicsLagX: Math.max(0.0, Math.min(1.0, root.physicsLagX))
        property real physicsLagY: Math.max(-0.92, Math.min(0.92, root.physicsLagY))
        property real physicsGrabAmount: Math.max(
            0.0, Math.min(1.0, root.physicsGrabAmount))
        property real physicsSlack: Math.max(0.0, Math.min(4.0, root.physicsSlack))
        property real physicsFeel: root.physicsFeelCode
        property real physicsGravity: Math.max(
            0.2, Math.min(4.0, root.physicsGravity))
        property real contentVerticalScale: Math.max(
            0.45, Math.min(1.0, root.contentVerticalScale))
        property real overallScale: Math.max(
            0.50, Math.min(2.60, root.overallScale))
        property real aspectRatio: root.width / Math.max(1.0, root.height)
        property real spectralFlux: root.smoothedSpectralFlux
        property real spectralCentroid: root.smoothedSpectralCentroid
        property color primary: root.primaryColor
        property color secondary: root.secondaryColor
        property color highlight: root.highlightColor
        property vector4d spectrum0: root.spectrum0
        property vector4d spectrum1: root.spectrum1
        property vector4d spectrum2: root.spectrum2
        property vector4d ambientSpectrum0: root.ambientSpectrum0
        property vector4d ambientSpectrum1: root.ambientSpectrum1
        property vector4d ambientSpectrum2: root.ambientSpectrum2

        vertexShader: "shaders/nc_voice_thread.vert.qsb"
        fragmentShader: "shaders/nc_voice_thread.frag.qsb"
    }
}
