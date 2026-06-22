import QtQuick 2.15
import "neural_face_reference_topology.js" as NeuralFaceTopology

Item {
    id: root

    property var bridge: presenceBridge
    property string aiState: presenceBridge ? presenceBridge.aiState : "idle"
    property real audioLevel: presenceBridge ? presenceBridge.audioLevel : 0.0
    property real peakLevel: presenceBridge ? presenceBridge.peakLevel : 0.0
    property real musicLevel: presenceBridge ? presenceBridge.musicLevel : 0.0
    property real musicPeak: presenceBridge ? presenceBridge.musicPeak : 0.0
    property bool presenceEnabled: presenceBridge ? presenceBridge.enabled : false
    property string displayMode: presenceBridge ? presenceBridge.displayMode : "fullscreen"
    property string visualStyle: presenceBridge ? presenceBridge.visualStyle : "breathing_orb"
    property real overlayOpacity: presenceBridge ? presenceBridge.overlayOpacity : 0.72
    property real floatingOpacity: presenceBridge ? presenceBridge.floatingOpacity : 0.92
    property real pulseIntensity: presenceBridge ? presenceBridge.pulseIntensity : 0.55
    property real speakingReactivity: presenceBridge ? presenceBridge.speakingReactivity : 0.85
    property int nodeDensity: presenceBridge ? presenceBridge.nodeDensity : 32
    property int particleDensity: presenceBridge ? presenceBridge.particleDensity : 28
    property bool reducedEffects: presenceBridge ? presenceBridge.reducedEffects : false
    property bool shadersEnabled: presenceBridge ? presenceBridge.shadersEnabled : true
    property bool particlesEnabled: presenceBridge ? presenceBridge.particlesEnabled : true
    property bool transparentBackground: presenceBridge ? presenceBridge.transparentBackground : false
    property bool musicReactivityEnabled: presenceBridge ? presenceBridge.musicReactivityEnabled : false
    property real musicReactivity: presenceBridge ? presenceBridge.musicReactivity : 0.65
    property bool moodColorsEnabled: presenceBridge ? presenceBridge.moodColorsEnabled : false
    property string moodName: presenceBridge ? presenceBridge.moodName : "neutral"
    property real moodColorIntensity: presenceBridge ? presenceBridge.moodColorIntensity : 0.85
    property color moodPrimaryTarget: presenceBridge ? presenceBridge.primaryColor : "#38bdf8"
    property color moodSecondaryTarget: presenceBridge ? presenceBridge.secondaryColor : "#22d3ee"
    property color moodAccentTarget: presenceBridge ? presenceBridge.accentColor : "#a78bfa"
    property color moodGlowTarget: presenceBridge ? presenceBridge.glowColor : "#67e8f9"
    property color moodBackgroundTarget: presenceBridge ? presenceBridge.backgroundColor : "#030712"
    property color moodPrimaryColor: moodPrimaryTarget
    property color moodSecondaryColor: moodSecondaryTarget
    property color moodAccentColor: moodAccentTarget
    property color moodGlowColor: moodGlowTarget
    property color moodBackgroundColor: moodBackgroundTarget
    property real moodPulseMultiplier: presenceBridge ? presenceBridge.moodPulseMultiplier : 1.0
    property real moodGlowMultiplier: presenceBridge ? presenceBridge.moodGlowMultiplier : 1.0
    property real moodParticleMultiplier: presenceBridge ? presenceBridge.moodParticleMultiplier : 1.0
    property real glowStrength: presenceBridge ? presenceBridge.glowStrength : 1.0
    property real animationSpeed: presenceBridge ? presenceBridge.animationSpeed : 1.0
    property real idleMotionStrength: presenceBridge ? presenceBridge.idleMotionStrength : 0.16
    property real primaryColorStrength: presenceBridge ? presenceBridge.primaryColorStrength : 1.0
    property real secondaryColorStrength: presenceBridge ? presenceBridge.secondaryColorStrength : 1.0
    property real backgroundDarkness: presenceBridge ? presenceBridge.backgroundDarkness : 1.0
    property real haloThickness: presenceBridge ? presenceBridge.haloThickness : 1.0
    property real waveformStrength: presenceBridge ? presenceBridge.waveformStrength : 1.0
    property real ringExpansionSpeed: presenceBridge ? presenceBridge.ringExpansionSpeed : 1.0
    property real blurSoftness: presenceBridge ? presenceBridge.blurSoftness : 0.35
    property real lineBrightness: presenceBridge ? presenceBridge.lineBrightness : 1.0
    property bool neuralFaceEnabled: presenceBridge ? presenceBridge.neuralFaceEnabled : true
    property string neuralFaceVariant: presenceBridge ? presenceBridge.neuralFaceVariant : "auto"
    property real neuralFaceSize: presenceBridge ? presenceBridge.neuralFaceSize : 1.0
    property real neuralFaceOpacity: presenceBridge ? presenceBridge.neuralFaceOpacity : 0.92
    property real neuralFaceAnimationIntensity: presenceBridge ? presenceBridge.neuralFaceAnimationIntensity : 0.78
    property real neuralFaceLipSyncStrength: presenceBridge ? presenceBridge.neuralFaceLipSyncStrength : 1.0
    property bool neuralFaceEyeMovementEnabled: presenceBridge ? presenceBridge.neuralFaceEyeMovementEnabled : true
    property bool neuralFaceBlinkEnabled: presenceBridge ? presenceBridge.neuralFaceBlinkEnabled : true
    property bool neuralFaceGlowEnabled: presenceBridge ? presenceBridge.neuralFaceGlowEnabled : true
    property bool neuralFaceEmotionEnabled: presenceBridge ? presenceBridge.neuralFaceEmotionEnabled : true
    property bool neuralFaceUseTtsEmotion: presenceBridge ? presenceBridge.neuralFaceUseTtsEmotion : true
    property bool neuralFaceAudioLipSyncEnabled: presenceBridge ? presenceBridge.neuralFaceAudioLipSyncEnabled : true
    property bool neuralFaceReducedAnimation: presenceBridge ? presenceBridge.neuralFaceReducedAnimation : false
    property bool femaleNeuralFaceEnabled: presenceBridge ? presenceBridge.femaleNeuralFaceEnabled : true
    property bool femaleReferenceNodes: presenceBridge ? presenceBridge.femaleReferenceNodes : true
    property bool femaleShowWireNodes: presenceBridge ? presenceBridge.femaleShowWireNodes : true
    property bool femaleShowWireLines: presenceBridge ? presenceBridge.femaleShowWireLines : true
    property bool femaleNodeGlowEnabled: presenceBridge ? presenceBridge.femaleNodeGlowEnabled : true
    property bool femaleWirePulseEnabled: presenceBridge ? presenceBridge.femaleWirePulseEnabled : true
    property bool femaleDepthEnabled: presenceBridge ? presenceBridge.femaleDepthEnabled : true
    property string femaleReferenceAvatarSource: "../addons/ai_presence_mode/assets/neural_face/female/reference_female_avatar_cutout.png"
    property var femaleReferenceTopology: ({ nodes: [], edges: [] })
    property real animationTick: 0.0
    property real renderVoiceLevel: 0.0
    property real renderPeakLevel: 0.0
    property real renderMusicLevel: 0.0
    property real renderMusicPeak: 0.0
    property real waitingLevel: 0.0
    property bool floatingMode: displayMode === "floating" || displayMode === "both"
    property bool active: presenceEnabled && displayMode !== "off" && (aiState !== "idle" || floatingMode)
    property color stateColor: aiState === "speaking" ? "#22d3ee" : "#a78bfa"
    property color accentColor: aiState === "speaking" ? "#34d399" : "#f472b6"

    opacity: active ? overlayOpacity : 0.0
    visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: 240; easing.type: Easing.InOutQuad } }
    Behavior on moodPrimaryColor { ColorAnimation { duration: root.reducedEffects ? 160 : 520; easing.type: Easing.InOutQuad } }
    Behavior on moodSecondaryColor { ColorAnimation { duration: root.reducedEffects ? 160 : 520; easing.type: Easing.InOutQuad } }
    Behavior on moodAccentColor { ColorAnimation { duration: root.reducedEffects ? 160 : 520; easing.type: Easing.InOutQuad } }
    Behavior on moodGlowColor { ColorAnimation { duration: root.reducedEffects ? 160 : 520; easing.type: Easing.InOutQuad } }
    Behavior on moodBackgroundColor { ColorAnimation { duration: root.reducedEffects ? 160 : 520; easing.type: Easing.InOutQuad } }

    function hexChannel(hex, index) {
        return parseInt(String(hex).slice(index, index + 2), 16)
    }

    function rgba(hex, alpha) {
        var value = String(hex)
        if (value.charAt(0) === "#") {
            value = value.slice(1)
        }
        if (value.length === 3) {
            value = value.charAt(0) + value.charAt(0) + value.charAt(1) + value.charAt(1) + value.charAt(2) + value.charAt(2)
        }
        return "rgba(" + hexChannel(value, 0) + "," + hexChannel(value, 2) + "," + hexChannel(value, 4) + "," + Math.max(0, Math.min(1, alpha)) + ")"
    }

    function hexByte(value) {
        var clamped = Math.max(0, Math.min(255, Math.round(value)))
        var text = clamped.toString(16)
        return text.length < 2 ? "0" + text : text
    }

    function colorToHex(colorValue) {
        return "#" + hexByte(colorValue.r * 255) + hexByte(colorValue.g * 255) + hexByte(colorValue.b * 255)
    }

    function mixHex(baseHex, moodHex, amount) {
        var base = String(baseHex || "#38bdf8")
        var mood = String(moodHex || base)
        if (base.charAt(0) === "#") base = base.slice(1)
        if (mood.charAt(0) === "#") mood = mood.slice(1)
        var t = clamp01(amount)
        var r = hexChannel(base, 0) * (1.0 - t) + hexChannel(mood, 0) * t
        var g = hexChannel(base, 2) * (1.0 - t) + hexChannel(mood, 2) * t
        var b = hexChannel(base, 4) * (1.0 - t) + hexChannel(mood, 4) * t
        return "#" + hexByte(r) + hexByte(g) + hexByte(b)
    }

    function clamp01(value) {
        return Math.max(0.0, Math.min(1.0, Number(value) || 0.0))
    }

    function smoothLevel(current, target, attack, release) {
        var factor = target > current ? attack : release
        return current + (target - current) * factor
    }

    function idleMotionOffset(axis, width, height) {
        var strength = root.reducedEffects ? 0.0 : root.clamp01(root.idleMotionStrength)
        if (strength <= 0.0) {
            return 0.0
        }
        var span = Math.max(1.0, Math.min(width, height))
        var maxOffset = Math.min(18.0, Math.max(1.5, span * 0.014)) * strength
        if (axis === "x") {
            return (
                Math.sin(root.animationTick * 0.67 + 0.35)
                + Math.sin(root.animationTick * 1.31 + 1.70) * 0.42
                + Math.sin(root.animationTick * 2.07 + 0.90) * 0.18
            ) * maxOffset
        }
        return (
            Math.cos(root.animationTick * 0.59 + 1.10)
            + Math.cos(root.animationTick * 1.17 + 0.45) * 0.38
            + Math.cos(root.animationTick * 1.83 + 2.20) * 0.20
        ) * maxOffset
    }

    function loadFemaleReferenceTopology() {
        var fallback = { nodes: [], edges: [] }
        try {
            var topology = NeuralFaceTopology.femaleReferenceTopology()
            if (topology && topology.nodes && topology.edges) {
                return topology
            }
        } catch (err) {
            return fallback
        }
        return fallback
    }

    function palettePrimary(style) {
        if (aiState === "speaking") {
            return moodColorsEnabled ? mixHex("#22d3ee", colorToHex(moodPrimaryColor), moodColorIntensity * primaryColorStrength) : "#22d3ee"
        }
        var fallback = "#a78bfa"
        if (style === "hologram_core") {
            fallback = "#67e8f9"
        } else if (style === "signal_bloom") {
            fallback = "#86efac"
        } else if (style === "blue_flame_smoke") {
            fallback = "#38bdf8"
        } else if (style === "vector_voice_orb") {
            fallback = "#38bdf8"
        } else if (style === "neural_face_male" || style === "neural_face_female" || style === "neural_face_auto") {
            fallback = "#38bdf8"
        } else if (style === "crystal_prism") {
            fallback = "#c4b5fd"
        } else if (style === "halo_rings") {
            fallback = "#f59e0b"
        } else if (style === "minimal_dot") {
            fallback = "#e5e7eb"
        }
        return moodColorsEnabled ? mixHex(fallback, colorToHex(moodPrimaryColor), moodColorIntensity * primaryColorStrength) : fallback
    }

    function paletteAccent(style) {
        if (aiState === "speaking") {
            return moodColorsEnabled ? mixHex("#34d399", colorToHex(moodAccentColor), moodColorIntensity * secondaryColorStrength) : "#34d399"
        }
        var fallback = "#f472b6"
        if (style === "hologram_core") {
            fallback = "#22d3ee"
        } else if (style === "signal_bloom") {
            fallback = "#38bdf8"
        } else if (style === "blue_flame_smoke") {
            fallback = "#93c5fd"
        } else if (style === "vector_voice_orb") {
            fallback = "#f472b6"
        } else if (style === "neural_face_male" || style === "neural_face_female" || style === "neural_face_auto") {
            fallback = "#67e8f9"
        } else if (style === "crystal_prism") {
            fallback = "#fb7185"
        } else if (style === "halo_rings") {
            fallback = "#f472b6"
        } else if (style === "minimal_dot") {
            fallback = "#38bdf8"
        }
        return moodColorsEnabled ? mixHex(fallback, colorToHex(moodAccentColor), moodColorIntensity * secondaryColorStrength) : fallback
    }

    function drawEllipse(ctx, cx, cy, rx, ry) {
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(1, ry / Math.max(1, rx))
        ctx.beginPath()
        ctx.arc(0, 0, rx, 0, Math.PI * 2)
        ctx.restore()
    }

    function drawBackground(ctx, width, height) {
        if (transparentBackground) {
            return
        }
        ctx.fillStyle = moodColorsEnabled ? rgba(colorToHex(moodBackgroundColor), 0.58 + backgroundDarkness * 0.30) : "rgba(3, 7, 18, 0.78)"
        ctx.fillRect(0, 0, width, height)
        if (!shadersEnabled || reducedEffects) {
            return
        }
        var glow = ctx.createRadialGradient(width * 0.5, height * 0.5, 0, width * 0.5, height * 0.5, Math.max(width, height) * 0.62)
        glow.addColorStop(0.0, moodColorsEnabled ? rgba(colorToHex(moodGlowColor), 0.20 * glowStrength * moodGlowMultiplier) : "rgba(28, 47, 73, 0.34)")
        glow.addColorStop(0.55, "rgba(7, 16, 28, 0.16)")
        glow.addColorStop(1.0, "rgba(3, 7, 18, 0.0)")
        ctx.fillStyle = glow
        ctx.fillRect(0, 0, width, height)
    }

    function clearCanvas(ctx, width, height) {
        ctx.save()
        ctx.clearRect(0, 0, width, height)
        ctx.globalCompositeOperation = "copy"
        ctx.fillStyle = "rgba(0, 0, 0, 0)"
        ctx.fillRect(0, 0, width, height)
        ctx.restore()
        ctx.globalCompositeOperation = "source-over"
    }

    function drawParticles(ctx, width, height, cx, cy, primary, accent, level) {
        if (!particlesEnabled || reducedEffects || particleDensity <= 0) {
            return
        }
        var count = Math.max(0, Math.min(80, Math.floor(particleDensity * (moodColorsEnabled ? moodParticleMultiplier : 1.0))))
        for (var i = 0; i < count; i++) {
            var angle = animationTick * (0.16 + i * 0.004) + i * 1.61
            var radius = Math.min(width, height) * (0.13 + (i % 9) * 0.028) + Math.sin(animationTick + i) * (8 + level * 20)
            var size = 1.5 + (i % 4) * 0.65 + level * 1.6
            ctx.fillStyle = rgba(i % 2 === 0 ? primary : accent, 0.14 + (i % 5) * 0.026 + level * 0.16)
            ctx.beginPath()
            ctx.arc(cx + Math.cos(angle) * radius, cy + Math.sin(angle * 0.93) * radius, size, 0, Math.PI * 2)
            ctx.fill()
        }
    }

    function drawSoftAura(ctx, cx, cy, radius, primary, accent, level) {
        if (!shadersEnabled || reducedEffects) {
            return
        }
        var glowRadius = radius * (2.2 + level * 1.1 + blurSoftness * 0.35)
        var aura = ctx.createRadialGradient(cx, cy, radius * 0.20, cx, cy, glowRadius)
        aura.addColorStop(0.0, rgba(moodColorsEnabled ? colorToHex(moodGlowColor) : primary, (0.18 + level * 0.18) * glowStrength * moodGlowMultiplier))
        aura.addColorStop(0.44, rgba(accent, (0.08 + level * 0.10) * glowStrength))
        aura.addColorStop(1.0, rgba(primary, 0.0))
        ctx.fillStyle = aura
        ctx.beginPath()
        ctx.arc(cx, cy, glowRadius, 0, Math.PI * 2)
        ctx.fill()
    }

    function drawRings(ctx, cx, cy, radius, primary, accent, level, count, wide) {
        var ringCount = reducedEffects ? Math.min(2, count) : count
        for (var i = 0; i < ringCount; i++) {
            var pulse = ((animationTick * ringExpansionSpeed * (0.18 + level * 0.55) + i * 0.16) % 0.36)
            var r = radius * (1.18 + i * (wide ? 0.44 : 0.30) + level * 0.42 + pulse)
            ctx.strokeStyle = rgba(i % 2 === 0 ? primary : accent, Math.max(0.04, (0.25 - i * 0.028 + level * 0.18) * lineBrightness))
            ctx.lineWidth = (i === 0 ? 2.2 + level * 3.0 : 1.1) * haloThickness
            ctx.beginPath()
            ctx.arc(cx, cy, r, 0, Math.PI * 2)
            ctx.stroke()
        }
    }

    function drawOrb(ctx, cx, cy, radius, primary, accent, level, compact) {
        var coreRadius = compact ? radius * 0.42 : radius
        var glowRadius = coreRadius * (2.1 + level * 0.35)
        var glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowRadius)
        glow.addColorStop(0.0, rgba(primary, 0.70 + level * 0.20))
        glow.addColorStop(0.48, rgba(accent, 0.22 + level * 0.18))
        glow.addColorStop(1.0, rgba(primary, 0.0))
        ctx.fillStyle = glow
        ctx.beginPath()
        ctx.arc(cx, cy, glowRadius, 0, Math.PI * 2)
        ctx.fill()

        var core = ctx.createRadialGradient(cx - coreRadius * 0.26, cy - coreRadius * 0.30, 0, cx, cy, coreRadius)
        core.addColorStop(0.0, "rgba(248, 251, 255, 0.96)")
        core.addColorStop(0.26, rgba(primary, 0.92))
        core.addColorStop(1.0, "rgba(17, 24, 39, 0.94)")
        ctx.fillStyle = core
        ctx.strokeStyle = rgba(accent, 0.76)
        ctx.lineWidth = 2.0 + level * 2.0
        ctx.beginPath()
        ctx.arc(cx, cy, coreRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()
    }

    function drawNeuralNetwork(ctx, width, height, cx, cy, primary, accent, level) {
        var count = Math.max(8, Math.floor(nodeDensity * (reducedEffects ? 0.45 : 1.0)))
        var radius = Math.min(width, height) * 0.34
        var points = []
        for (var i = 0; i < count; i++) {
            var angle = (i / count) * Math.PI * 2 + Math.sin(animationTick * 0.42 + i) * 0.12
            var band = 0.38 + ((i * 37) % 100) / 165.0
            var wobble = Math.sin(animationTick * (0.55 + (i % 5) * 0.11) + i * 1.71) * (14.0 + level * 22.0)
            points.push({
                x: cx + Math.cos(angle) * (radius * band + wobble),
                y: cy + Math.sin(angle) * (radius * band + wobble)
            })
        }
        ctx.lineWidth = 1
        for (var a = 0; a < points.length; a++) {
            var maxSteps = reducedEffects ? 2 : 3
            for (var step = 1; step <= maxSteps; step++) {
                var b = (a + step * 2) % points.length
                var dx = points[a].x - points[b].x
                var dy = points[a].y - points[b].y
                var distance = Math.sqrt(dx * dx + dy * dy)
                if (distance > radius * 0.43) {
                    continue
                }
                ctx.strokeStyle = rgba(primary, (0.12 + level * 0.16) * lineBrightness)
                ctx.beginPath()
                ctx.moveTo(points[a].x, points[a].y)
                ctx.lineTo(points[b].x, points[b].y)
                ctx.stroke()
            }
        }
        for (var p = 0; p < points.length; p++) {
            ctx.fillStyle = rgba(p % 2 === 0 ? accent : primary, (0.55 + level * 0.26) * lineBrightness)
            ctx.beginPath()
            ctx.arc(points[p].x, points[p].y, 2.0 + ((p % 3) * 0.7) + level * 1.8, 0, Math.PI * 2)
            ctx.fill()
        }
    }

    function drawVectorVoiceOrb(ctx, width, height, cx, cy, radius, primary, accent, voice, outer) {
        var outerRadius = radius * (1.42 + outer * 0.20)
        var nodeCount = reducedEffects ? 12 : 18
        var baseAlpha = 0.16 + outer * 0.16

        for (var ring = 0; ring < 3; ring++) {
            var sides = 14 + ring * 4
            var ringRadius = outerRadius * (0.72 + ring * 0.18 + outer * 0.025)
            var rotation = animationTick * (0.10 + ring * 0.045) * (ring === 1 ? -1 : 1)
            ctx.strokeStyle = rgba(ring % 2 === 0 ? primary : accent, Math.max(0.06, baseAlpha - ring * 0.035))
            ctx.lineWidth = ring === 0 ? 1.6 : 1.0
            ctx.beginPath()
            for (var i = 0; i <= sides; i++) {
                var angle = (i / sides) * Math.PI * 2 + rotation
                var wobble = Math.sin(animationTick * 0.85 + i * 1.9 + ring) * (2.0 + outer * 6.0)
                var x = cx + Math.cos(angle) * (ringRadius + wobble)
                var y = cy + Math.sin(angle) * (ringRadius * 0.86 + wobble * 0.45)
                if (i === 0) {
                    ctx.moveTo(x, y)
                } else {
                    ctx.lineTo(x, y)
                }
            }
            ctx.stroke()
        }

        var points = []
        for (var n = 0; n < nodeCount; n++) {
            var lane = n % 2
            var nodeAngle = (n / nodeCount) * Math.PI * 2 + animationTick * (lane === 0 ? 0.16 : -0.11)
            var nodeRadius = outerRadius * (0.80 + lane * 0.15) + Math.sin(animationTick * 0.7 + n) * (4.0 + outer * 10.0)
            points.push({
                x: cx + Math.cos(nodeAngle) * nodeRadius,
                y: cy + Math.sin(nodeAngle) * nodeRadius * 0.82,
                lane: lane
            })
        }
        ctx.lineWidth = 1
        for (var p = 0; p < points.length; p++) {
            var next = points[(p + 1) % points.length]
            var skip = points[(p + 3) % points.length]
            ctx.strokeStyle = rgba(primary, 0.08 + outer * 0.12)
            ctx.beginPath()
            ctx.moveTo(points[p].x, points[p].y)
            ctx.lineTo(next.x, next.y)
            ctx.stroke()
            if (!reducedEffects && p % 3 === 0) {
                ctx.strokeStyle = rgba(accent, 0.045 + outer * 0.08)
                ctx.beginPath()
                ctx.moveTo(points[p].x, points[p].y)
                ctx.lineTo(skip.x, skip.y)
                ctx.stroke()
            }
        }
        for (var dot = 0; dot < points.length; dot++) {
            ctx.fillStyle = rgba(points[dot].lane === 0 ? primary : accent, 0.46 + outer * 0.22)
            ctx.beginPath()
            ctx.arc(points[dot].x, points[dot].y, 1.8 + outer * 1.7, 0, Math.PI * 2)
            ctx.fill()
        }

        var centerPulse = 1.0 + voice * 0.42 * speakingReactivity
        var coreRadius = radius * (0.36 + voice * 0.10) * centerPulse
        var innerRadius = coreRadius * (0.58 + voice * 0.08)
        drawSoftAura(ctx, cx, cy, coreRadius * 1.55, primary, accent, Math.max(voice, outer * 0.45))

        ctx.fillStyle = rgba(primary, 0.09 + voice * 0.24)
        ctx.strokeStyle = rgba(accent, 0.66 + voice * 0.24)
        ctx.lineWidth = 1.7 + voice * 2.4
        ctx.beginPath()
        ctx.arc(cx, cy, coreRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()

        ctx.strokeStyle = rgba("#ecfeff", 0.28 + voice * 0.34)
        ctx.lineWidth = 1.0 + voice * 1.3
        ctx.beginPath()
        ctx.arc(cx, cy, innerRadius, 0, Math.PI * 2)
        ctx.stroke()

        var spokes = reducedEffects ? 12 : 24
        ctx.strokeStyle = rgba(primary, 0.18 + voice * 0.24)
        ctx.lineWidth = 1
        for (var s = 0; s < spokes; s++) {
            var spokeAngle = (s / spokes) * Math.PI * 2 + animationTick * 0.25
            var inside = innerRadius * 0.78
            var outside = coreRadius * (0.92 + voice * 0.24 + Math.sin(animationTick * 2.4 + s) * 0.025)
            ctx.beginPath()
            ctx.moveTo(cx + Math.cos(spokeAngle) * inside, cy + Math.sin(spokeAngle) * inside)
            ctx.lineTo(cx + Math.cos(spokeAngle) * outside, cy + Math.sin(spokeAngle) * outside)
            ctx.stroke()
        }

        var waiting = root.aiState !== "speaking" || voice < 0.08
        var roam = coreRadius * (waiting ? 0.56 : 0.14)
        var driftX = Math.sin(animationTick * 0.53 + Math.sin(animationTick * 0.21) * 2.1)
        var driftY = Math.cos(animationTick * 0.47 + Math.sin(animationTick * 0.29) * 1.7)
        var smallX = cx + driftX * roam
        var smallY = cy + driftY * roam * 0.74
        var smallRadius = coreRadius * (waiting ? 0.18 + outer * 0.06 : 0.13 + voice * 0.06)
        ctx.fillStyle = rgba(accent, 0.13 + outer * 0.18)
        ctx.strokeStyle = rgba("#ecfeff", 0.28 + outer * 0.22)
        ctx.lineWidth = 1.1
        ctx.beginPath()
        ctx.arc(smallX, smallY, smallRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()

        ctx.strokeStyle = rgba(primary, 0.24 + outer * 0.18)
        ctx.beginPath()
        ctx.moveTo(smallX - smallRadius * 0.55, smallY)
        ctx.lineTo(smallX + smallRadius * 0.55, smallY)
        ctx.moveTo(smallX, smallY - smallRadius * 0.55)
        ctx.lineTo(smallX, smallY + smallRadius * 0.55)
        ctx.stroke()
    }

    function drawClassicBackground(ctx, width, height) {
        if (!transparentBackground) {
            ctx.fillStyle = "rgba(3, 7, 18, 0.88)"
            ctx.fillRect(0, 0, width, height)
            if (shadersEnabled && !reducedEffects) {
                var haze = ctx.createRadialGradient(width * 0.5, height * 0.5, 0, width * 0.5, height * 0.5, Math.max(width, height) * 0.46)
                haze.addColorStop(0.0, "rgba(20, 184, 166, 0.18)")
                haze.addColorStop(0.52, "rgba(14, 116, 144, 0.08)")
                haze.addColorStop(1.0, "rgba(3, 7, 18, 0.0)")
                ctx.fillStyle = haze
                ctx.fillRect(0, 0, width, height)
            }
        }
    }

    function drawClassicTalkCircle(ctx, cx, cy, radius, primary, accent, level) {
        var pulse = 1.0 + level * 0.16 * speakingReactivity
        var coreRadius = radius * pulse
        var ringRadius = radius * (1.42 + level * 0.22)

        drawSoftAura(ctx, cx, cy, coreRadius, primary, accent, level)

        ctx.fillStyle = rgba(primary, 0.34 + level * 0.18)
        ctx.strokeStyle = rgba(accent, 0.58 + level * 0.22)
        ctx.lineWidth = 2.0
        ctx.beginPath()
        ctx.arc(cx, cy, coreRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()

        ctx.fillStyle = rgba(primary, 0.18 + level * 0.12)
        ctx.beginPath()
        ctx.arc(cx, cy, coreRadius * 0.66, 0, Math.PI * 2)
        ctx.fill()

        for (var i = 0; i < 4; i++) {
            var r = ringRadius * (1.0 + i * 0.22)
            ctx.strokeStyle = rgba(i % 2 === 0 ? primary : accent, Math.max(0.05, 0.28 - i * 0.045 + level * 0.12))
            ctx.lineWidth = i === 0 ? 2.0 : 1.0
            ctx.beginPath()
            ctx.arc(cx, cy, r, 0, Math.PI * 2)
            ctx.stroke()
        }

        var bars = reducedEffects ? 18 : 36
        ctx.strokeStyle = rgba("#ccfbf1", 0.20 + level * 0.20)
        ctx.lineWidth = 1
        for (var b = 0; b < bars; b++) {
            var angle = (b / bars) * Math.PI * 2
            var inner = coreRadius * 0.76
            var outer = inner + 5 + Math.sin(animationTick * 2.2 + b) * 2 + level * 12
            ctx.beginPath()
            ctx.moveTo(cx + Math.cos(angle) * inner, cy + Math.sin(angle) * inner)
            ctx.lineTo(cx + Math.cos(angle) * outer, cy + Math.sin(angle) * outer)
            ctx.stroke()
        }

        var eyeWidth = coreRadius * (1.12 + level * 0.12)
        var eyeHeight = coreRadius * (0.34 + level * 0.05)
        var lidDrift = Math.sin(animationTick * 0.9) * coreRadius * 0.025
        ctx.fillStyle = rgba("#020617", 0.30)
        ctx.strokeStyle = rgba("#ccfbf1", 0.46 + level * 0.24)
        ctx.lineWidth = 1.6 + level * 1.2
        ctx.beginPath()
        ctx.moveTo(cx - eyeWidth * 0.5, cy + lidDrift)
        ctx.quadraticCurveTo(cx, cy - eyeHeight, cx + eyeWidth * 0.5, cy + lidDrift)
        ctx.quadraticCurveTo(cx, cy + eyeHeight, cx - eyeWidth * 0.5, cy + lidDrift)
        ctx.closePath()
        ctx.fill()
        ctx.stroke()

        var irisRadius = coreRadius * (0.15 + level * 0.05)
        var iris = ctx.createRadialGradient(cx - irisRadius * 0.25, cy - irisRadius * 0.25, 0, cx, cy, irisRadius * 1.5)
        iris.addColorStop(0.0, rgba("#ecfeff", 0.72))
        iris.addColorStop(0.38, rgba(primary, 0.68 + level * 0.18))
        iris.addColorStop(1.0, rgba(accent, 0.30))
        ctx.fillStyle = iris
        ctx.beginPath()
        ctx.arc(cx, cy, irisRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = rgba("#020617", 0.62)
        ctx.beginPath()
        ctx.arc(cx, cy, Math.max(2.5, irisRadius * 0.36), 0, Math.PI * 2)
        ctx.fill()
    }

    function drawOrbitingNeuralNetwork(ctx, width, height, cx, cy, primary, accent, level) {
        var count = Math.max(10, Math.floor(nodeDensity * (reducedEffects ? 0.38 : 0.58)))
        var baseRadius = Math.min(width, height) * 0.31
        var orbit = animationTick * 0.105
        var points = []
        for (var i = 0; i < count; i++) {
            var lane = i % 3
            var angle = (i / count) * Math.PI * 2 + orbit * (lane === 1 ? -0.55 : 1.0)
            var band = baseRadius * (1.00 + lane * 0.17)
            var floatPhase = animationTick * (0.27 + lane * 0.07) + i * 1.37
            var wobble = Math.sin(floatPhase) * (10.0 + level * 18.0)
            var verticalDrift = Math.sin(floatPhase * 0.71 + lane) * (10.0 + level * 10.0)
            points.push({
                x: cx + Math.cos(angle) * (band + wobble),
                y: cy + Math.sin(angle) * (band * 0.82 + wobble * 0.45) + verticalDrift,
                lane: lane
            })
        }

        ctx.lineWidth = 1
        for (var a = 0; a < points.length; a++) {
            var maxSteps = reducedEffects ? 2 : 3
            for (var step = 1; step <= maxSteps; step++) {
                var b = (a + step) % points.length
                var dx = points[a].x - points[b].x
                var dy = points[a].y - points[b].y
                var distance = Math.sqrt(dx * dx + dy * dy)
                if (distance > baseRadius * 0.30) {
                    continue
                }
                ctx.strokeStyle = rgba(primary, 0.075 + level * 0.10)
                ctx.beginPath()
                ctx.moveTo(points[a].x, points[a].y)
                ctx.lineTo(points[b].x, points[b].y)
                ctx.stroke()
            }
        }

        for (var p = 0; p < points.length; p++) {
            var point = points[p]
            var size = 1.8 + (point.lane * 0.55) + level * 1.9 + Math.sin(animationTick * 0.8 + p) * 0.28
            ctx.fillStyle = rgba(point.lane === 1 ? accent : primary, 0.46 + level * 0.24)
            ctx.beginPath()
            ctx.arc(point.x, point.y, size, 0, Math.PI * 2)
            ctx.fill()
            if (p % 5 === 0) {
                ctx.strokeStyle = rgba(accent, 0.07 + level * 0.07)
                ctx.beginPath()
                ctx.moveTo(point.x, point.y)
                ctx.lineTo(cx + (point.x - cx) * 0.54, cy + (point.y - cy) * 0.54)
                ctx.stroke()
            }
        }
    }

    function drawCircularWaveform(ctx, cx, cy, radius, primary, accent, level) {
        var points = reducedEffects ? 64 : 128
        ctx.strokeStyle = rgba(accent, 0.72 * lineBrightness)
        ctx.lineWidth = (2.0 + level * 4.5) * waveformStrength
        ctx.beginPath()
        for (var i = 0; i <= points; i++) {
            var angle = (i / points) * Math.PI * 2
            var wave = Math.sin(angle * 8.0 + animationTick * 4.0) * (7.0 + level * 30.0) * waveformStrength
            wave += Math.sin(angle * 17.0 - animationTick * 2.3) * (2.5 + peakLevel * 10.0) * waveformStrength
            var r = radius * 1.2 + wave
            var x = cx + Math.cos(angle) * r
            var y = cy + Math.sin(angle) * r
            if (i === 0) {
                ctx.moveTo(x, y)
            } else {
                ctx.lineTo(x, y)
            }
        }
        ctx.closePath()
        ctx.stroke()
        drawOrb(ctx, cx, cy, radius * 0.48, primary, accent, level, false)
    }

    function drawHologramCore(ctx, width, height, cx, cy, radius, primary, accent, level) {
        var step = reducedEffects ? 22 : 11
        ctx.strokeStyle = rgba(accent, 0.10 + level * 0.08)
        ctx.lineWidth = 1
        for (var y = 0; y < height; y += step) {
            ctx.beginPath()
            ctx.moveTo(0, y + Math.sin(animationTick * 1.8 + y * 0.03) * 2)
            ctx.lineTo(width, y)
            ctx.stroke()
        }
        for (var i = 0; i < 4; i++) {
            ctx.strokeStyle = rgba(i % 2 === 0 ? primary : accent, 0.42 - i * 0.06 + level * 0.12)
            ctx.lineWidth = 1.5 + level * 2.2
            ctx.save()
            ctx.translate(cx, cy)
            ctx.scale(1, 0.58 + i * 0.05)
            ctx.beginPath()
            ctx.arc(0, 0, radius * (1.0 + i * 0.24), 0, Math.PI * 2)
            ctx.restore()
            ctx.stroke()
        }
        drawOrb(ctx, cx, cy, radius * 0.62, primary, accent, level, false)
    }

    function drawSignalBloom(ctx, cx, cy, radius, primary, accent, level) {
        var beams = reducedEffects ? 7 : 18
        for (var i = 0; i < beams; i++) {
            var angle = (i / beams) * Math.PI * 2 + animationTick * (0.16 + level * 0.24)
            var inner = radius * (0.65 + Math.sin(animationTick + i) * 0.05)
            var outer = radius * (1.9 + (i % 4) * 0.12 + level * 0.55)
            ctx.strokeStyle = rgba(i % 2 === 0 ? primary : accent, 0.10 + level * 0.18)
            ctx.lineWidth = 1.2 + level * 2.8
            ctx.beginPath()
            ctx.moveTo(cx + Math.cos(angle) * inner, cy + Math.sin(angle) * inner)
            ctx.lineTo(cx + Math.cos(angle) * outer, cy + Math.sin(angle) * outer)
            ctx.stroke()
        }
        drawRings(ctx, cx, cy, radius, primary, accent, level, 5, true)
        drawOrb(ctx, cx, cy, radius * 0.56, primary, accent, level, false)
    }

    function drawCrystalPrism(ctx, cx, cy, radius, primary, accent, level) {
        var sides = 6
        var points = []
        for (var i = 0; i < sides; i++) {
            var angle = (i / sides) * Math.PI * 2 + animationTick * 0.18
            var r = radius * (0.92 + Math.sin(animationTick * 1.4 + i) * 0.08 + level * 0.14)
            points.push({ x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r })
        }
        var gradient = ctx.createRadialGradient(cx - radius * 0.2, cy - radius * 0.26, 0, cx, cy, radius * 1.22)
        gradient.addColorStop(0.0, "rgba(255, 255, 255, 0.80)")
        gradient.addColorStop(0.32, rgba(primary, 0.62 + level * 0.18))
        gradient.addColorStop(1.0, rgba(accent, 0.32))
        ctx.fillStyle = gradient
        ctx.strokeStyle = rgba(accent, 0.78)
        ctx.lineWidth = 2.0 + level * 2.2
        ctx.beginPath()
        for (var p = 0; p < points.length; p++) {
            if (p === 0) {
                ctx.moveTo(points[p].x, points[p].y)
            } else {
                ctx.lineTo(points[p].x, points[p].y)
            }
        }
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
        ctx.strokeStyle = "rgba(255, 255, 255, 0.22)"
        ctx.lineWidth = 1
        for (var f = 0; f < points.length; f++) {
            ctx.beginPath()
            ctx.moveTo(cx, cy)
            ctx.lineTo(points[f].x, points[f].y)
            ctx.stroke()
        }
        drawRings(ctx, cx, cy, radius * 0.9, primary, accent, level, 3, false)
    }

    function drawBlueFlameSmoke(ctx, width, height, cx, cy, radius, primary, accent, voice, outer) {
        var level = clamp01(Math.max(voice, outer * 0.72))
        var flameCx = cx
        var flameCy = cy + radius * 0.20
        var flameHeight = radius * (1.18 + level * 0.86 * waveformStrength)
        var baseWidth = radius * (0.52 + level * 0.12)
        var baseY = cy + radius * 0.70
        var tipY = cy - flameHeight * (0.68 + level * 0.07)
        var flicker = Math.sin(animationTick * 4.8 * ringExpansionSpeed) * radius * (0.045 + level * 0.040)
                    + Math.sin(animationTick * 8.9 * ringExpansionSpeed + 1.7) * radius * (0.020 + level * 0.025)

        drawSoftAura(ctx, flameCx, flameCy, radius * (1.05 + level * 0.25), primary, accent, Math.max(level, outer * 0.55))

        if (particlesEnabled && !reducedEffects && particleDensity > 0) {
            var smokeCount = Math.max(4, Math.min(56, Math.floor(particleDensity * 0.52 * (moodColorsEnabled ? moodParticleMultiplier : 1.0))))
            for (var s = 0; s < smokeCount; s++) {
                var lane = ((s * 37) % 100) / 100.0
                var rise = (animationTick * (0.11 + lane * 0.09) * ringExpansionSpeed + s * 0.073) % 1.0
                var sway = Math.sin(animationTick * (0.38 + lane * 0.18) + s * 1.71) * radius * (0.24 + level * 0.18)
                var smokeX = cx + sway + (lane - 0.5) * radius * 0.52
                var smokeY = cy - radius * (0.38 + rise * (1.22 + level * 0.42))
                var smokeRadius = radius * (0.060 + lane * 0.055 + rise * 0.080)
                var smokeAlpha = Math.max(0.0, Math.min(0.52, (0.13 + level * 0.16) * (1.0 - rise * 0.74) * lineBrightness))
                var smoke = ctx.createRadialGradient(smokeX, smokeY, 0, smokeX, smokeY, smokeRadius * 2.0)
                smoke.addColorStop(0.0, "rgba(205, 238, 255, " + smokeAlpha + ")")
                smoke.addColorStop(0.45, "rgba(85, 139, 190, " + smokeAlpha * 0.45 + ")")
                smoke.addColorStop(1.0, "rgba(25, 35, 55, 0)")
                ctx.fillStyle = smoke
                ctx.save()
                ctx.translate(smokeX, smokeY)
                ctx.scale(1.7, 0.82 + lane * 0.25)
                ctx.beginPath()
                ctx.arc(0, 0, smokeRadius, 0, Math.PI * 2)
                ctx.restore()
                ctx.fill()
            }
        }

        var glowRadius = radius * (1.10 + level * 0.28)
        var flameGlow = ctx.createRadialGradient(cx, cy + radius * 0.05, 0, cx, cy + radius * 0.05, glowRadius * 1.8)
        flameGlow.addColorStop(0.00, "rgba(191, 219, 254, " + (0.34 + level * 0.31) * glowStrength * moodGlowMultiplier + ")")
        flameGlow.addColorStop(0.32, rgba(primary, (0.20 + level * 0.26) * glowStrength))
        flameGlow.addColorStop(0.70, rgba(accent, (0.07 + level * 0.13) * glowStrength))
        flameGlow.addColorStop(1.00, rgba(primary, 0.0))
        ctx.fillStyle = flameGlow
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(1.35, 1.18)
        ctx.beginPath()
        ctx.arc(0, 0, glowRadius, 0, Math.PI * 2)
        ctx.restore()
        ctx.fill()

        var outerGradient = ctx.createLinearGradient(cx, tipY, cx, baseY + radius * 0.18)
        outerGradient.addColorStop(0.00, "rgba(236, 254, 255, 0.82)")
        outerGradient.addColorStop(0.20, "rgba(125, 211, 252, 0.84)")
        outerGradient.addColorStop(0.55, rgba(primary, 0.74 + level * 0.16))
        outerGradient.addColorStop(1.00, "rgba(15, 61, 104, 0.66)")
        ctx.fillStyle = outerGradient
        ctx.strokeStyle = rgba(accent, (0.48 + level * 0.27) * lineBrightness)
        ctx.lineWidth = (1.4 + level * 1.8) * haloThickness
        ctx.beginPath()
        ctx.moveTo(cx + flicker * 0.35, tipY)
        ctx.bezierCurveTo(
            cx - radius * (0.62 + level * 0.12) + flicker * 0.28,
            cy - radius * (0.62 + level * 0.34),
            cx - baseWidth,
            baseY - radius * 0.28,
            cx - baseWidth,
            baseY
        )
        ctx.bezierCurveTo(
            cx - baseWidth * 0.46,
            baseY + radius * 0.26,
            cx + baseWidth * 0.44,
            baseY + radius * 0.26,
            cx + baseWidth,
            baseY
        )
        ctx.bezierCurveTo(
            cx + radius * (0.60 + level * 0.12) + flicker * 0.54,
            cy - radius * (0.48 + level * 0.30),
            cx + radius * 0.18 + flicker,
            tipY + radius * 0.27,
            cx + flicker * 0.35,
            tipY
        )
        ctx.closePath()
        ctx.fill()
        ctx.stroke()

        var innerWidth = baseWidth * (0.44 + level * 0.06)
        var innerTipY = cy - flameHeight * (0.44 + level * 0.10) + Math.sin(animationTick * 6.1) * radius * 0.035
        var innerGradient = ctx.createLinearGradient(cx, innerTipY, cx, baseY + radius * 0.14)
        innerGradient.addColorStop(0.00, "rgba(255, 255, 255, 0.88)")
        innerGradient.addColorStop(0.30, "rgba(186, 230, 253, 0.84)")
        innerGradient.addColorStop(0.78, "rgba(56, 189, 248, " + (0.70 + level * 0.18) + ")")
        innerGradient.addColorStop(1.00, "rgba(14, 165, 233, 0.32)")
        ctx.fillStyle = innerGradient
        ctx.beginPath()
        ctx.moveTo(cx - flicker * 0.08, innerTipY)
        ctx.bezierCurveTo(
            cx - innerWidth * 0.82,
            cy - radius * (0.22 + level * 0.18),
            cx - innerWidth,
            baseY - radius * 0.12,
            cx - innerWidth * 0.58,
            baseY + radius * 0.08
        )
        ctx.bezierCurveTo(
            cx - innerWidth * 0.12,
            baseY + radius * 0.20,
            cx + innerWidth * 0.52,
            baseY + radius * 0.08,
            cx + innerWidth * 0.58,
            baseY - radius * 0.05
        )
        ctx.bezierCurveTo(
            cx + innerWidth * 0.92 + flicker * 0.25,
            cy - radius * (0.18 + level * 0.18),
            cx + innerWidth * 0.18,
            innerTipY + radius * 0.18,
            cx - flicker * 0.08,
            innerTipY
        )
        ctx.closePath()
        ctx.fill()

        var baseGlow = ctx.createRadialGradient(cx, baseY - radius * 0.05, 0, cx, baseY - radius * 0.05, radius * (0.78 + level * 0.15))
        baseGlow.addColorStop(0.0, "rgba(224, 242, 254, 0.82)")
        baseGlow.addColorStop(0.35, rgba(primary, 0.56 + level * 0.26))
        baseGlow.addColorStop(1.0, "rgba(14, 116, 144, 0)")
        ctx.fillStyle = baseGlow
        ctx.save()
        ctx.translate(cx, baseY - radius * 0.05)
        ctx.scale(1.0, 0.38 + level * 0.06)
        ctx.beginPath()
        ctx.arc(0, 0, radius * (0.58 + level * 0.08), 0, Math.PI * 2)
        ctx.restore()
        ctx.fill()

        var waves = reducedEffects ? 1 : 3
        for (var w = 0; w < waves; w++) {
            var waveRadius = radius * (0.58 + w * 0.18 + level * 0.16)
            var y = baseY - radius * (0.18 + w * 0.10)
            ctx.strokeStyle = rgba(w % 2 === 0 ? primary : accent, Math.max(0.08, (0.16 + level * 0.24 - w * 0.04) * lineBrightness))
            ctx.lineWidth = Math.max(0.65, haloThickness * 0.72)
            ctx.beginPath()
            ctx.moveTo(cx - waveRadius, y + Math.sin(animationTick * 2.7 + w) * 2.5)
            ctx.bezierCurveTo(
                cx - waveRadius * 0.36,
                y - radius * (0.15 + level * 0.10),
                cx + waveRadius * 0.36,
                y + radius * (0.14 + level * 0.08),
                cx + waveRadius,
                y + Math.cos(animationTick * 2.4 + w) * 2.5
            )
            ctx.stroke()
        }
    }

    function isNeuralFaceStyle(style) {
        return style === "neural_face_male" || style === "neural_face_female" || style === "neural_face_auto"
    }

    function neuralFaceKind(style) {
        if (style === "neural_face_male") return "male"
        if (style === "neural_face_female") return "female"
        var variant = String(neuralFaceVariant || "auto").toLowerCase()
        if (variant === "male" || variant === "female") return variant
        return "female"
    }

    function neuralMoodTuning() {
        var mood = String(moodName || "neutral").toLowerCase()
        var state = String(aiState || "idle").toLowerCase()
        var tuning = { smile: 0.0, brow: 0.0, eye: 0.0, jaw: 0.0 }
        if (!neuralFaceEmotionEnabled) {
            return tuning
        }
        if (mood === "happy" || mood === "excited") {
            tuning.smile = 0.28
            tuning.eye = 0.12
        } else if (state === "listening") {
            tuning.smile = 0.08
            tuning.eye = 0.16
        } else if (mood === "sad") {
            tuning.smile = -0.20
            tuning.brow = -0.18
            tuning.eye = -0.10
        } else if (mood === "concerned" || mood === "focus") {
            tuning.smile = -0.06
            tuning.brow = 0.12
            tuning.eye = 0.02
        } else if (mood === "surprised" || mood === "epic") {
            tuning.smile = 0.02
            tuning.brow = -0.22
            tuning.eye = 0.28
            tuning.jaw = 0.18
        } else if (mood === "angry" || mood === "tension" || mood === "dark") {
            tuning.smile = -0.10
            tuning.brow = 0.25
            tuning.eye = -0.08
        } else if (mood === "curious" || state === "thinking") {
            tuning.smile = 0.08
            tuning.brow = -0.10
            tuning.eye = 0.10
        } else if (mood === "calm") {
            tuning.smile = 0.10
            tuning.eye = -0.04
        } else if (state === "idle") {
            tuning.smile = 0.02
            tuning.eye = -0.10
        }
        if (state === "speaking") {
            tuning.jaw = 0.10
            tuning.eye += 0.04
        }
        return tuning
    }

    function neuralFacePoint(x, y, cx, cy, scale, xScale) {
        return { x: cx + x * scale * xScale, y: cy + y * scale }
    }

    function femaleReferenceFaceTemplate(cx, cy, scale, voice, tuning, blink, gazeX, gazeY) {
        var xScale = 0.88
        var mouthOpen = neuralFaceAudioLipSyncEnabled ? clamp01(voice * neuralFaceLipSyncStrength * (0.94 + speakingReactivity * 0.34)) : 0.0
        var smile = tuning.smile
        var brow = tuning.brow
        var eye = tuning.eye
        var jawDrop = mouthOpen * 0.10 + tuning.jaw * 0.08
        var p = { _female: true }

        function add(name, x, y, customX) {
            p[name] = neuralFacePoint(x, y, cx, cy, scale, customX === undefined ? xScale : customX)
        }

        add("hairTop", 0.00, -1.07)
        add("hairPart", 0.03, -0.90)
        add("hairCrownL", -0.26, -1.00)
        add("hairCrownR", 0.30, -0.99)
        add("hairL0", -0.46, -0.92)
        add("hairL1", -0.62, -0.72)
        add("hairL2", -0.74, -0.44)
        add("hairL3", -0.79, -0.13)
        add("hairL4", -0.76, 0.24)
        add("hairL5", -0.67, 0.54)
        add("hairL6", -0.57, 0.82)
        add("hairL7", -0.43, 1.00)
        add("hairTipL", -0.30, 1.04)
        add("hairR0", 0.46, -0.92)
        add("hairR1", 0.62, -0.72)
        add("hairR2", 0.74, -0.44)
        add("hairR3", 0.79, -0.13)
        add("hairR4", 0.76, 0.24)
        add("hairR5", 0.67, 0.54)
        add("hairR6", 0.57, 0.82)
        add("hairR7", 0.43, 1.00)
        add("hairTipR", 0.30, 1.04)
        add("hairInnerL0", -0.42, -0.72)
        add("hairInnerL1", -0.54, -0.35)
        add("hairInnerL2", -0.50, 0.16)
        add("hairInnerL3", -0.38, 0.63)
        add("hairInnerR0", 0.42, -0.72)
        add("hairInnerR1", 0.54, -0.35)
        add("hairInnerR2", 0.50, 0.16)
        add("hairInnerR3", 0.38, 0.63)

        add("top", 0.00, -0.79)
        add("hairlineC", 0.00, -0.70)
        add("hairlineL", -0.28, -0.67)
        add("hairlineR", 0.28, -0.67)
        add("foreheadL", -0.36, -0.52)
        add("foreheadLC", -0.17, -0.55)
        add("foreheadC", 0.00, -0.54)
        add("foreheadRC", 0.17, -0.55)
        add("foreheadR", 0.36, -0.52)
        add("templeL", -0.47, -0.29)
        add("templeR", 0.47, -0.29)
        add("cheekUpperL", -0.43, -0.02)
        add("cheekUpperR", 0.43, -0.02)
        add("cheekL", -0.42, 0.25)
        add("cheekR", 0.42, 0.25)
        add("cheekLowL", -0.33, 0.49)
        add("cheekLowR", 0.33, 0.49)
        add("jawL", -0.28, 0.68)
        add("jawR", 0.28, 0.68)
        add("chinL", -0.12, 0.78 + jawDrop)
        add("chin", 0.00, 0.84 + jawDrop)
        add("chinR", 0.12, 0.78 + jawDrop)
        add("neckL", -0.18, 0.98)
        add("neckC", 0.00, 1.05)
        add("neckR", 0.18, 0.98)

        add("browCenter", 0.00, -0.26 - brow * 0.03)
        add("browL1", -0.33, -0.29 + brow * 0.045)
        add("browL2", -0.24, -0.33 - brow * 0.045)
        add("browL3", -0.13, -0.31 - brow * 0.030)
        add("browR1", 0.33, -0.29 + brow * 0.045)
        add("browR2", 0.24, -0.33 - brow * 0.045)
        add("browR3", 0.13, -0.31 - brow * 0.030)

        add("eyeLO", -0.34, -0.18)
        add("eyeLI", -0.11, -0.18)
        add("eyeLTL", -0.29, -0.225 - eye * 0.030)
        add("eyeLT", -0.22, -0.248 - eye * 0.034)
        add("eyeLTR", -0.15, -0.228 - eye * 0.030)
        add("eyeLBL", -0.29, -0.142 + eye * 0.024)
        add("eyeLB", -0.22, -0.124 + eye * 0.028)
        add("eyeLBR", -0.15, -0.142 + eye * 0.024)
        add("eyeLP", -0.225, -0.176)
        add("eyeRO", 0.34, -0.18)
        add("eyeRI", 0.11, -0.18)
        add("eyeRTL", 0.15, -0.228 - eye * 0.030)
        add("eyeRT", 0.22, -0.248 - eye * 0.034)
        add("eyeRTR", 0.29, -0.225 - eye * 0.030)
        add("eyeRBL", 0.15, -0.142 + eye * 0.024)
        add("eyeRB", 0.22, -0.124 + eye * 0.028)
        add("eyeRBR", 0.29, -0.142 + eye * 0.024)
        add("eyeRP", 0.225, -0.176)

        add("noseTop", 0.00, -0.14)
        add("noseBridgeL", -0.065, 0.02)
        add("noseBridgeR", 0.065, 0.02)
        add("noseMid", 0.00, 0.10)
        add("noseTip", 0.00, 0.25)
        add("noseL", -0.115, 0.285)
        add("noseR", 0.115, 0.285)
        add("nostrilL", -0.065, 0.315)
        add("nostrilR", 0.065, 0.315)
        add("philtrumTop", 0.00, 0.34)
        add("philtrumL", -0.045, 0.39)
        add("philtrumR", 0.045, 0.39)

        add("mouthL", -0.235, 0.455 - smile * 0.050)
        add("mouthR", 0.235, 0.455 - smile * 0.050)
        add("mouthUL", -0.130, 0.415 - smile * 0.035)
        add("mouthTop", 0.00, 0.395 - smile * 0.045)
        add("mouthUR", 0.130, 0.415 - smile * 0.035)
        add("mouthLL", -0.125, 0.505 + mouthOpen * 0.130 - smile * 0.010)
        add("mouthBottom", 0.00, 0.525 + mouthOpen * 0.180 - smile * 0.010)
        add("mouthLR", 0.125, 0.505 + mouthOpen * 0.130 - smile * 0.010)
        add("mouthInnerTop", 0.00, 0.452 + mouthOpen * 0.030)
        add("mouthInnerBottom", 0.00, 0.470 + mouthOpen * 0.145)
        add("lipCenter", 0.00, 0.462 + mouthOpen * 0.085)

        p.female_face_base = [
            ["top", "hairlineL", "foreheadLC", "foreheadC", "foreheadRC", "hairlineR"],
            ["hairlineL", "templeL", "browL1", "browL2", "foreheadLC"],
            ["hairlineR", "foreheadRC", "browR2", "browR1", "templeR"],
            ["foreheadLC", "browL3", "browCenter", "foreheadC"],
            ["foreheadRC", "foreheadC", "browCenter", "browR3"],
            ["templeL", "cheekUpperL", "noseBridgeL", "eyeLI", "eyeLO"],
            ["templeR", "eyeRO", "eyeRI", "noseBridgeR", "cheekUpperR"],
            ["cheekUpperL", "cheekL", "noseL", "noseBridgeL"],
            ["cheekUpperR", "noseBridgeR", "noseR", "cheekR"],
            ["noseBridgeL", "noseMid", "noseTip", "noseBridgeR"],
            ["noseL", "mouthL", "mouthUL", "noseTip"],
            ["noseTip", "mouthUR", "mouthR", "noseR"],
            ["cheekL", "cheekLowL", "mouthL", "noseL"],
            ["cheekR", "noseR", "mouthR", "cheekLowR"],
            ["mouthL", "cheekLowL", "jawL", "chinL", "mouthBottom"],
            ["mouthR", "mouthBottom", "chinR", "jawR", "cheekLowR"],
            ["chinL", "chin", "chinR", "mouthBottom"],
            ["jawL", "neckL", "neckC", "neckR", "jawR", "chin"]
        ]
        p.female_hair = [
            ["hairTop", "hairCrownL", "hairL0", "hairlineL", "top", "hairlineR", "hairR0", "hairCrownR"],
            ["hairL0", "hairL1", "hairL2", "hairInnerL1", "hairInnerL0", "hairlineL"],
            ["hairL2", "hairL3", "hairL4", "hairInnerL2", "hairInnerL1"],
            ["hairL4", "hairL5", "hairL6", "hairInnerL3", "hairInnerL2"],
            ["hairL6", "hairL7", "hairTipL", "neckL", "jawL", "hairInnerL3"],
            ["hairR0", "hairlineR", "hairInnerR0", "hairInnerR1", "hairR2", "hairR1"],
            ["hairR2", "hairInnerR1", "hairInnerR2", "hairR4", "hairR3"],
            ["hairR4", "hairInnerR2", "hairInnerR3", "hairR6", "hairR5"],
            ["hairR6", "hairInnerR3", "jawR", "neckR", "hairTipR", "hairR7"]
        ]
        p.female_hair_wire = [
            ["hairTop", "hairCrownL"], ["hairTop", "hairCrownR"], ["hairCrownL", "hairL0"], ["hairCrownR", "hairR0"],
            ["hairL0", "hairL1"], ["hairL1", "hairL2"], ["hairL2", "hairL3"], ["hairL3", "hairL4"], ["hairL4", "hairL5"], ["hairL5", "hairL6"], ["hairL6", "hairL7"], ["hairL7", "hairTipL"],
            ["hairR0", "hairR1"], ["hairR1", "hairR2"], ["hairR2", "hairR3"], ["hairR3", "hairR4"], ["hairR4", "hairR5"], ["hairR5", "hairR6"], ["hairR6", "hairR7"], ["hairR7", "hairTipR"],
            ["hairL0", "hairInnerL0"], ["hairInnerL0", "hairInnerL1"], ["hairInnerL1", "hairInnerL2"], ["hairInnerL2", "hairInnerL3"], ["hairInnerL3", "hairTipL"],
            ["hairR0", "hairInnerR0"], ["hairInnerR0", "hairInnerR1"], ["hairInnerR1", "hairInnerR2"], ["hairInnerR2", "hairInnerR3"], ["hairInnerR3", "hairTipR"],
            ["hairCrownL", "hairPart"], ["hairPart", "hairCrownR"], ["hairPart", "hairlineC"], ["hairlineC", "top"], ["hairlineL", "hairlineC"], ["hairlineC", "hairlineR"]
        ]
        p.female_wire_lines = [
            ["top", "hairlineL"], ["top", "hairlineR"], ["top", "foreheadC"], ["hairlineL", "foreheadL"], ["hairlineR", "foreheadR"],
            ["foreheadL", "foreheadLC"], ["foreheadLC", "foreheadC"], ["foreheadC", "foreheadRC"], ["foreheadRC", "foreheadR"],
            ["foreheadLC", "browL3"], ["foreheadRC", "browR3"], ["browL1", "browL2"], ["browL2", "browL3"], ["browR1", "browR2"], ["browR2", "browR3"],
            ["browCenter", "noseTop"], ["noseTop", "noseBridgeL"], ["noseTop", "noseBridgeR"], ["noseBridgeL", "noseMid"], ["noseBridgeR", "noseMid"], ["noseMid", "noseTip"],
            ["noseTip", "noseL"], ["noseTip", "noseR"], ["noseL", "nostrilL"], ["noseR", "nostrilR"], ["noseTip", "philtrumTop"], ["philtrumTop", "philtrumL"], ["philtrumTop", "philtrumR"],
            ["templeL", "cheekUpperL"], ["templeR", "cheekUpperR"], ["cheekUpperL", "cheekL"], ["cheekUpperR", "cheekR"], ["cheekL", "cheekLowL"], ["cheekR", "cheekLowR"],
            ["cheekLowL", "jawL"], ["cheekLowR", "jawR"], ["jawL", "chinL"], ["jawR", "chinR"], ["chinL", "chin"], ["chin", "chinR"],
            ["eyeLO", "eyeLTL"], ["eyeLTL", "eyeLT"], ["eyeLT", "eyeLTR"], ["eyeLTR", "eyeLI"], ["eyeLI", "eyeLBR"], ["eyeLBR", "eyeLB"], ["eyeLB", "eyeLBL"], ["eyeLBL", "eyeLO"],
            ["eyeRO", "eyeRTR"], ["eyeRTR", "eyeRT"], ["eyeRT", "eyeRTL"], ["eyeRTL", "eyeRI"], ["eyeRI", "eyeRBL"], ["eyeRBL", "eyeRB"], ["eyeRB", "eyeRBR"], ["eyeRBR", "eyeRO"],
            ["eyeLO", "cheekUpperL"], ["eyeLI", "noseTop"], ["eyeRO", "cheekUpperR"], ["eyeRI", "noseTop"],
            ["mouthL", "mouthUL"], ["mouthUL", "mouthTop"], ["mouthTop", "mouthUR"], ["mouthUR", "mouthR"], ["mouthR", "mouthLR"], ["mouthLR", "mouthBottom"], ["mouthBottom", "mouthLL"], ["mouthLL", "mouthL"],
            ["mouthL", "philtrumL"], ["mouthR", "philtrumR"], ["mouthTop", "philtrumTop"], ["mouthBottom", "chin"], ["neckL", "neckC"], ["neckC", "neckR"]
        ]
        p.female_wire_nodes = [
            "hairTop", "hairCrownL", "hairCrownR", "hairPart", "hairL0", "hairL1", "hairL2", "hairL3", "hairL4", "hairL5", "hairL6", "hairL7", "hairTipL",
            "hairR0", "hairR1", "hairR2", "hairR3", "hairR4", "hairR5", "hairR6", "hairR7", "hairTipR", "hairInnerL0", "hairInnerL1", "hairInnerL2", "hairInnerL3", "hairInnerR0", "hairInnerR1", "hairInnerR2", "hairInnerR3",
            "top", "hairlineC", "hairlineL", "hairlineR", "foreheadL", "foreheadLC", "foreheadC", "foreheadRC", "foreheadR", "templeL", "templeR",
            "browCenter", "browL1", "browL2", "browL3", "browR1", "browR2", "browR3",
            "eyeLO", "eyeLTL", "eyeLT", "eyeLTR", "eyeLI", "eyeLBL", "eyeLB", "eyeLBR", "eyeLP",
            "eyeRO", "eyeRTR", "eyeRT", "eyeRTL", "eyeRI", "eyeRBR", "eyeRB", "eyeRBL", "eyeRP",
            "noseTop", "noseBridgeL", "noseBridgeR", "noseMid", "noseTip", "noseL", "noseR", "nostrilL", "nostrilR", "philtrumTop", "philtrumL", "philtrumR",
            "cheekUpperL", "cheekUpperR", "cheekL", "cheekR", "cheekLowL", "cheekLowR",
            "mouthL", "mouthUL", "mouthTop", "mouthUR", "mouthR", "mouthLL", "mouthBottom", "mouthLR", "mouthInnerTop", "mouthInnerBottom",
            "jawL", "jawR", "chinL", "chin", "chinR", "neckL", "neckC", "neckR"
        ]
        var topology = femaleReferenceTopology || {}
        var refNodes = topology.nodes || []
        var refEdges = topology.edges || []
        if (refNodes.length > 0 && refEdges.length > 0) {
            p.female_wire_nodes = []
            p.female_wire_lines = []
            p._femaleReferenceLoaded = true
            for (var rn = 0; rn < refNodes.length; rn++) {
                var source = refNodes[rn]
                var nx = Number(source[0])
                var ny = Number(source[1])
                if (Math.abs(nx) < 0.34 && ny > 0.20 && ny < 0.56) {
                    var mouthLower = ny > 0.35 ? 1.0 : -0.24
                    ny += mouthOpen * 0.115 * mouthLower
                    if (Math.abs(nx) > 0.13 && ny < 0.48) {
                        ny -= smile * 0.045
                    }
                    nx *= 1.0 + mouthOpen * 0.045
                }
                if (Math.abs(nx) > 0.08 && Math.abs(nx) < 0.50 && ny > -0.29 && ny < -0.04) {
                    var eyeCenterX = nx < 0 ? -0.245 : 0.245
                    var eyeCenterY = -0.145
                    var insideEye = Math.abs(nx - eyeCenterX) < 0.155 && Math.abs(ny - eyeCenterY) < 0.105
                    if (insideEye) {
                        nx += gazeX * 0.035
                        ny += gazeY * 0.020
                    }
                    ny = eyeCenterY + (ny - eyeCenterY) * (1.0 - blink * 0.72)
                    ny += ny < eyeCenterY ? -tuning.eye * 0.020 : tuning.eye * 0.016
                }
                if (Math.abs(nx) > 0.08 && Math.abs(nx) < 0.45 && ny > -0.39 && ny < -0.20) {
                    ny += brow * (Math.abs(nx) > 0.22 ? 0.035 : -0.040)
                }
                if (aiState === "thinking" && Math.abs(nx) < 0.36 && ny < -0.32 && ny > -0.66) {
                    ny += Math.sin(animationTick * 1.2 + rn * 0.17) * 0.006 * neuralFaceAnimationIntensity
                }
                var key = "ref" + rn
                p[key] = neuralFacePoint(nx, ny, cx, cy, scale, 1.0)
                p.female_wire_nodes.push(key)
            }
            for (var re = 0; re < refEdges.length; re++) {
                var edge = refEdges[re]
                if (edge && edge.length >= 2 && edge[0] < refNodes.length && edge[1] < refNodes.length) {
                    p.female_wire_lines.push(["ref" + edge[0], "ref" + edge[1]])
                }
            }
            function alias(name, index) {
                var ref = p["ref" + index]
                if (ref) p[name] = ref
            }
            alias("eyeLO", 47); alias("eyeLTL", 43); alias("eyeLT", 63); alias("eyeLTR", 45); alias("eyeLI", 54)
            alias("eyeLBL", 59); alias("eyeLB", 52); alias("eyeLBR", 58); alias("eyeLP", 52)
            alias("eyeRO", 48); alias("eyeRTR", 60); alias("eyeRT", 62); alias("eyeRTL", 46); alias("eyeRI", 51)
            alias("eyeRBR", 67); alias("eyeRB", 61); alias("eyeRBL", 57); alias("eyeRP", 53)
            alias("browL1", 30); alias("browL2", 32); alias("browL3", 37)
            alias("browR1", 29); alias("browR2", 31); alias("browR3", 36); alias("browCenter", 24)
            alias("noseTop", 41); alias("noseMid", 103); alias("noseTip", 136); alias("noseL", 110); alias("noseR", 109)
            alias("nostrilL", 115); alias("nostrilR", 114)
            alias("mouthL", 152); alias("mouthUL", 141); alias("mouthTop", 142); alias("mouthUR", 140); alias("mouthR", 151)
            alias("mouthLL", 146); alias("mouthBottom", 159); alias("mouthLR", 148); alias("mouthInnerTop", 144); alias("mouthInnerBottom", 155); alias("lipCenter", 144)
            alias("jawL", 161); alias("jawR", 162); alias("chin", 180); alias("neckL", 186); alias("neckR", 185)
        }
        return p
    }

    function neuralFaceTemplate(kind, cx, cy, scale, voice, tuning, blink, gazeX, gazeY) {
        var female = kind === "female"
        if (female) {
            return femaleReferenceFaceTemplate(cx, cy, scale, voice, tuning, blink || 0.0, gazeX || 0.0, gazeY || 0.0)
        }
        var xScale = female ? 0.88 : 1.0
        var jawScale = female ? 0.90 : 1.10
        var mouthOpen = neuralFaceAudioLipSyncEnabled ? clamp01(voice * neuralFaceLipSyncStrength * (0.92 + speakingReactivity * 0.34)) : 0.0
        var smile = tuning.smile
        var jawDrop = mouthOpen * 0.10 + tuning.jaw

        var p = {}
        function add(name, x, y, customX) {
            p[name] = neuralFacePoint(x, y, cx, cy, scale, customX === undefined ? xScale : customX)
        }

        add("top", 0.00, female ? -0.90 : -0.86)
        add("foreheadL", -0.22, -0.77)
        add("foreheadR", 0.22, -0.77)
        add("templeL", -0.48, -0.53)
        add("templeR", 0.48, -0.53)
        add("cheekL", -0.54, 0.05)
        add("cheekR", 0.54, 0.05)
        add("jawL", -0.38, 0.53, jawScale * xScale)
        add("jawR", 0.38, 0.53, jawScale * xScale)
        add("chin", 0.00, 0.78 + jawDrop * 0.08)
        add("browCenter", 0.00, -0.32)
        add("browL1", -0.36, -0.31 + tuning.brow * 0.04)
        add("browL2", -0.18, -0.35 - tuning.brow * 0.05)
        add("browR1", 0.36, -0.31 + tuning.brow * 0.04)
        add("browR2", 0.18, -0.35 - tuning.brow * 0.05)
        add("eyeLO", -0.34, -0.20)
        add("eyeLI", -0.12, -0.20)
        add("eyeRO", 0.34, -0.20)
        add("eyeRI", 0.12, -0.20)
        add("eyeLT", -0.23, -0.245 - tuning.eye * 0.03)
        add("eyeLB", -0.23, -0.155 + tuning.eye * 0.03)
        add("eyeRT", 0.23, -0.245 - tuning.eye * 0.03)
        add("eyeRB", 0.23, -0.155 + tuning.eye * 0.03)
        add("noseTop", 0.00, -0.16)
        add("noseBridgeL", -0.09, 0.07)
        add("noseBridgeR", 0.09, 0.07)
        add("noseTip", 0.00, 0.22)
        add("noseL", -0.13, 0.26)
        add("noseR", 0.13, 0.26)
        add("mouthL", -0.23, 0.43 - smile * 0.04)
        add("mouthR", 0.23, 0.43 - smile * 0.04)
        add("mouthTop", 0.00, 0.398 - smile * 0.03)
        add("mouthBottom", 0.00, 0.48 + mouthOpen * 0.17 - smile * 0.02)
        add("lipCenter", 0.00, 0.435 + mouthOpen * 0.08)
        add("neckL", -0.20, 0.90)
        add("neckR", 0.20, 0.90)

        if (female) {
            add("hairTop", 0.00, -1.03)
            add("hairL0", -0.44, -0.88)
            add("hairL1", -0.69, -0.46)
            add("hairL2", -0.66, 0.32)
            add("hairL3", -0.46, 0.86)
            add("hairR0", 0.44, -0.88)
            add("hairR1", 0.69, -0.46)
            add("hairR2", 0.66, 0.32)
            add("hairR3", 0.46, 0.86)
        } else {
            add("hairTop", 0.00, -1.00)
            add("hairL0", -0.48, -0.82)
            add("hairL1", -0.58, -0.48)
            add("hairL2", -0.50, -0.18)
            add("hairR0", 0.48, -0.82)
            add("hairR1", 0.58, -0.48)
            add("hairR2", 0.50, -0.18)
        }
        return p
    }

    function neuralDrawPolygon(ctx, points, keys, fill, stroke, lineWidth) {
        if (!keys || keys.length < 3) return
        ctx.beginPath()
        for (var i = 0; i < keys.length; i++) {
            var point = points[keys[i]]
            if (!point) return
            if (i === 0) ctx.moveTo(point.x, point.y)
            else ctx.lineTo(point.x, point.y)
        }
        ctx.closePath()
        if (fill) {
            ctx.fillStyle = fill
            ctx.fill()
        }
        if (stroke) {
            ctx.strokeStyle = stroke
            ctx.lineWidth = lineWidth || 1
            ctx.stroke()
        }
    }

    function neuralDrawLine(ctx, points, a, b, color, width) {
        var p1 = points[a]
        var p2 = points[b]
        if (!p1 || !p2) return
        ctx.strokeStyle = color
        ctx.lineWidth = width || 1
        ctx.beginPath()
        ctx.moveTo(p1.x, p1.y)
        ctx.lineTo(p2.x, p2.y)
        ctx.stroke()
    }

    function drawFemaleReferenceAvatar(ctx, cx, cy, scale, voice, outer) {
        if (!presenceCanvas || !presenceCanvas.isImageLoaded(root.femaleReferenceAvatarSource)) {
            return false
        }
        var topology = root.femaleReferenceTopology || {}
        var imageSize = topology.imageSize || [1254, 1254]
        var centerPx = topology.centerPx || [636.725, 633.206]
        var scalePx = Math.max(1, Number(topology.scalePx) || 594.206)
        var imageW = Math.max(1, Number(imageSize[0]) || 1254)
        var imageH = Math.max(1, Number(imageSize[1]) || 1254)
        var drawW = imageW / scalePx * scale
        var drawH = imageH / scalePx * scale
        var drawX = cx - (Number(centerPx[0]) || 636.725) / scalePx * scale
        var drawY = cy - (Number(centerPx[1]) || 633.206) / scalePx * scale
        var voiceLift = 1.0 + voice * 0.014 * speakingReactivity
        var floatLift = Math.sin(animationTick * 0.45) * 0.004 * neuralFaceAnimationIntensity

        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(1.0 + outer * 0.006, voiceLift + floatLift)
        ctx.translate(-cx, -cy)
        ctx.globalAlpha = ctx.globalAlpha * Math.min(1.0, 0.88 + voice * 0.10 + outer * 0.04)
        ctx.drawImage(root.femaleReferenceAvatarSource, drawX, drawY, drawW, drawH)
        ctx.restore()
        return true
    }

    function drawNeuralFaceHair(ctx, points, kind, primary, accent) {
        var hairFill = "rgba(5, 21, 43, 0.86)"
        var hairFacet = "rgba(17, 54, 93, 0.62)"
        if (kind === "female" && points.female_hair) {
            for (var h = 0; h < points.female_hair.length; h++) {
                var fill = h % 2 === 0 ? hairFill : "rgba(8, 34, 66, 0.80)"
                neuralDrawPolygon(ctx, points, points.female_hair[h], fill, rgba(h % 2 === 0 ? primary : accent, 0.13), 1)
            }
            neuralDrawPolygon(ctx, points, ["hairTop", "hairCrownL", "hairPart", "hairCrownR"], hairFacet, null, 0)
            neuralDrawPolygon(ctx, points, ["hairCrownL", "hairL0", "hairlineL", "hairlineC", "hairPart"], "rgba(17, 54, 93, 0.55)", null, 0)
            neuralDrawPolygon(ctx, points, ["hairPart", "hairlineC", "hairlineR", "hairR0", "hairCrownR"], "rgba(10, 42, 79, 0.55)", null, 0)
        } else {
            neuralDrawPolygon(ctx, points, ["hairTop", "hairL0", "hairL1", "hairL2", "templeL", "foreheadL", "top", "foreheadR", "templeR", "hairR2", "hairR1", "hairR0"], hairFill, rgba(primary, 0.16), 1)
            neuralDrawPolygon(ctx, points, ["hairTop", "hairL0", "foreheadL", "top"], hairFacet, null, 0)
            neuralDrawPolygon(ctx, points, ["hairTop", "top", "foreheadR", "hairR0"], "rgba(8, 34, 66, 0.58)", null, 0)
        }
    }

    function drawNeuralFaceFacets(ctx, points, primary, accent, voice, kind) {
        var faceAlpha = 0.25 + voice * 0.12
        var cool = kind === "female" ? "#5eead4" : "#38bdf8"
        var facets = points._female && points.female_face_base ? points.female_face_base : [
            ["top", "foreheadL", "browCenter", "foreheadR"],
            ["foreheadL", "templeL", "browL1", "browL2", "browCenter"],
            ["foreheadR", "browCenter", "browR2", "browR1", "templeR"],
            ["templeL", "cheekL", "noseBridgeL", "eyeLI", "eyeLO"],
            ["templeR", "eyeRO", "eyeRI", "noseBridgeR", "cheekR"],
            ["browCenter", "eyeLI", "noseTop", "eyeRI"],
            ["noseTop", "noseBridgeL", "noseTip", "noseBridgeR"],
            ["cheekL", "jawL", "mouthL", "noseL", "noseBridgeL"],
            ["cheekR", "noseBridgeR", "noseR", "mouthR", "jawR"],
            ["noseL", "mouthL", "mouthTop", "noseTip"],
            ["noseTip", "mouthTop", "mouthR", "noseR"],
            ["mouthL", "jawL", "chin", "mouthBottom"],
            ["mouthR", "mouthBottom", "chin", "jawR"],
            ["jawL", "neckL", "neckR", "jawR", "chin"]
        ]
        for (var i = 0; i < facets.length; i++) {
            var alpha = faceAlpha + (i % 4) * 0.025
            if (points._female) {
                var facePalette = ["#38bdf8", "#0ea5e9", "#7dd3fc", "#0284c7"]
                neuralDrawPolygon(ctx, points, facets[i], rgba(facePalette[i % facePalette.length], 0.20 + voice * 0.10 + (i % 3) * 0.018), rgba("#e0f2fe", 0.035), 1)
            } else {
                neuralDrawPolygon(ctx, points, facets[i], rgba(i % 2 === 0 ? primary : cool, alpha), rgba(accent, 0.045), 1)
            }
        }
    }

    function drawNeuralFaceWire(ctx, points, primary, accent, voice) {
        if (points._female && !femaleShowWireLines) {
            return
        }
        var edges = points._female && points.female_wire_lines ? points.female_wire_lines.concat(points.female_hair_wire || []) : [
            ["top", "foreheadL"], ["top", "foreheadR"], ["foreheadL", "templeL"], ["foreheadR", "templeR"],
            ["templeL", "cheekL"], ["templeR", "cheekR"], ["cheekL", "jawL"], ["cheekR", "jawR"],
            ["jawL", "chin"], ["jawR", "chin"], ["foreheadL", "browCenter"], ["foreheadR", "browCenter"],
            ["browCenter", "noseTop"], ["noseTop", "noseBridgeL"], ["noseTop", "noseBridgeR"],
            ["noseBridgeL", "noseTip"], ["noseBridgeR", "noseTip"], ["noseTip", "noseL"], ["noseTip", "noseR"],
            ["browL1", "browL2"], ["browR1", "browR2"], ["eyeLO", "eyeLT"], ["eyeLT", "eyeLI"], ["eyeLI", "eyeLB"], ["eyeLB", "eyeLO"],
            ["eyeRO", "eyeRT"], ["eyeRT", "eyeRI"], ["eyeRI", "eyeRB"], ["eyeRB", "eyeRO"],
            ["eyeLI", "noseTop"], ["eyeRI", "noseTop"], ["eyeLO", "cheekL"], ["eyeRO", "cheekR"],
            ["cheekL", "noseBridgeL"], ["cheekR", "noseBridgeR"], ["noseL", "mouthL"], ["noseR", "mouthR"],
            ["mouthL", "mouthTop"], ["mouthTop", "mouthR"], ["mouthR", "mouthBottom"], ["mouthBottom", "mouthL"],
            ["mouthBottom", "chin"], ["jawL", "neckL"], ["jawR", "neckR"], ["neckL", "neckR"]
        ]
        var pulse = points._female && femaleWirePulseEnabled ? (0.72 + 0.28 * Math.sin(animationTick * (2.0 + voice * 2.0))) : 1.0
        var wire = rgba("#f8fbff", (points._female ? 0.68 : 0.30) * pulse * lineBrightness + voice * 0.24)
        var accentWire = rgba(points._female ? "#dff7ff" : accent, (points._female ? 0.52 : 0.18) * pulse * lineBrightness + voice * 0.18)
        for (var i = 0; i < edges.length; i++) {
            var isHair = points._female && i >= (points.female_wire_lines ? points.female_wire_lines.length : 0)
            var width = points._female ? (i % 5 === 0 ? 2.10 : 1.55) : (i % 5 === 0 ? 1.35 : 1.0)
            neuralDrawLine(ctx, points, edges[i][0], edges[i][1], isHair ? rgba("#e0f2fe", 0.62 * pulse) : (i % 3 === 0 ? accentWire : wire), width)
        }
    }

    function drawNeuralFaceEye(ctx, points, side, primary, accent, voice, blink, gazeX, gazeY) {
        var outer = points[side + "O"]
        var inner = points[side + "I"]
        var top = points[side + "T"]
        var bottom = points[side + "B"]
        if (!outer || !inner || !top || !bottom) return
        var midX = (outer.x + inner.x) * 0.5
        var midY = (outer.y + inner.y) * 0.5
        var topOuter = points[side + "TL"] || points[side + "TR"] || top
        var topInner = points[side + "TR"] || points[side + "TL"] || top
        var bottomOuter = points[side + "BL"] || points[side + "BR"] || bottom
        var bottomInner = points[side + "BR"] || points[side + "BL"] || bottom
        if (side === "eyeR") {
            topOuter = points[side + "TR"] || top
            topInner = points[side + "TL"] || top
            bottomOuter = points[side + "BR"] || bottom
            bottomInner = points[side + "BL"] || bottom
        }
        function blinkPoint(point, strength) {
            return { x: point.x, y: midY + (point.y - midY) * (1.0 - blink * strength) }
        }
        var tOuter = blinkPoint(topOuter, 0.88)
        var tMid = blinkPoint(top, 0.92)
        var tInner = blinkPoint(topInner, 0.88)
        var bOuter = blinkPoint(bottomOuter, 0.80)
        var bMid = blinkPoint(bottom, 0.86)
        var bInner = blinkPoint(bottomInner, 0.80)
        ctx.fillStyle = "rgba(1, 10, 22, 0.64)"
        ctx.strokeStyle = rgba("#e0f2fe", 0.44 + voice * 0.24)
        ctx.lineWidth = 1.3 + voice * 0.9
        ctx.beginPath()
        ctx.moveTo(outer.x, outer.y)
        ctx.lineTo(tOuter.x, tOuter.y)
        ctx.quadraticCurveTo(tMid.x, tMid.y, tInner.x, tInner.y)
        ctx.lineTo(inner.x, inner.y)
        ctx.lineTo(bInner.x, bInner.y)
        ctx.quadraticCurveTo(bMid.x, bMid.y, bOuter.x, bOuter.y)
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
        if (blink > 0.78) {
            return
        }
        var eyeWidth = Math.abs(inner.x - outer.x)
        var irisRadius = Math.max(2.5, eyeWidth * (0.115 + voice * 0.025))
        var pupil = points[side + "P"]
        var irisX = (pupil ? pupil.x : midX) + gazeX * eyeWidth
        var irisY = (pupil ? pupil.y : midY) + gazeY * eyeWidth * 0.45
        var iris = ctx.createRadialGradient(irisX - irisRadius * 0.25, irisY - irisRadius * 0.25, 0, irisX, irisY, irisRadius * 1.6)
        iris.addColorStop(0.0, rgba("#ecfeff", 0.86))
        iris.addColorStop(0.42, rgba(primary, 0.84))
        iris.addColorStop(1.0, rgba(accent, 0.32))
        ctx.fillStyle = iris
        ctx.beginPath()
        ctx.arc(irisX, irisY, irisRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = "rgba(2, 6, 23, 0.82)"
        ctx.beginPath()
        ctx.arc(irisX, irisY, Math.max(1.6, irisRadius * 0.42), 0, Math.PI * 2)
        ctx.fill()
    }

    function drawNeuralFaceFeatures(ctx, points, primary, accent, voice, tuning, blink, gazeX, gazeY) {
        drawNeuralFaceEye(ctx, points, "eyeL", primary, accent, voice, blink, gazeX, gazeY)
        drawNeuralFaceEye(ctx, points, "eyeR", primary, accent, voice, blink, gazeX, gazeY)

        ctx.strokeStyle = "rgba(3, 7, 18, 0.82)"
        ctx.lineWidth = 4.2
        neuralDrawLine(ctx, points, "browL1", "browL2", "rgba(3, 7, 18, 0.86)", 5)
        neuralDrawLine(ctx, points, "browL2", "browL3", "rgba(3, 7, 18, 0.78)", points._female ? 4 : 5)
        neuralDrawLine(ctx, points, "browR1", "browR2", "rgba(3, 7, 18, 0.86)", 5)
        neuralDrawLine(ctx, points, "browR2", "browR3", "rgba(3, 7, 18, 0.78)", points._female ? 4 : 5)
        neuralDrawLine(ctx, points, "noseTop", "noseMid", rgba("#e0f2fe", 0.24), 1)
        neuralDrawLine(ctx, points, "noseMid", "noseTip", rgba("#e0f2fe", 0.24), 1)
        neuralDrawLine(ctx, points, "noseL", "noseTip", rgba("#e0f2fe", 0.20), 1)
        neuralDrawLine(ctx, points, "noseR", "noseTip", rgba("#e0f2fe", 0.20), 1)
        neuralDrawLine(ctx, points, "nostrilL", "noseTip", rgba("#e0f2fe", 0.16), 1)
        neuralDrawLine(ctx, points, "nostrilR", "noseTip", rgba("#e0f2fe", 0.16), 1)

        var mL = points["mouthL"]
        var mR = points["mouthR"]
        var mT = points["mouthTop"]
        var mB = points["mouthBottom"]
        if (mL && mR && mT && mB) {
            var mUL = points["mouthUL"] || mT
            var mUR = points["mouthUR"] || mT
            var mLL = points["mouthLL"] || mB
            var mLR = points["mouthLR"] || mB
            var mIT = points["mouthInnerTop"] || points["lipCenter"] || mT
            var mIB = points["mouthInnerBottom"] || points["lipCenter"] || mB
            ctx.fillStyle = "rgba(2, 6, 23, 0.72)"
            ctx.strokeStyle = rgba(accent, 0.42 + voice * 0.32)
            ctx.lineWidth = 1.4 + voice * 1.2
            ctx.beginPath()
            ctx.moveTo(mL.x, mL.y)
            ctx.quadraticCurveTo(mUL.x, mUL.y, mT.x, mT.y)
            ctx.quadraticCurveTo(mUR.x, mUR.y, mR.x, mR.y)
            ctx.quadraticCurveTo(mLR.x, mLR.y, mB.x, mB.y)
            ctx.quadraticCurveTo(mLL.x, mLL.y, mL.x, mL.y)
            ctx.closePath()
            ctx.fill()
            ctx.stroke()
            ctx.fillStyle = "rgba(2, 6, 23, 0.42)"
            ctx.beginPath()
            ctx.moveTo(mL.x + (mIT.x - mL.x) * 0.45, mL.y + (mIT.y - mL.y) * 0.45)
            ctx.quadraticCurveTo(mIT.x, mIT.y, mR.x + (mIT.x - mR.x) * 0.45, mR.y + (mIT.y - mR.y) * 0.45)
            ctx.quadraticCurveTo(mIB.x, mIB.y, mL.x + (mIB.x - mL.x) * 0.45, mL.y + (mIB.y - mL.y) * 0.45)
            ctx.closePath()
            ctx.fill()
            ctx.strokeStyle = "rgba(2, 6, 23, 0.86)"
            ctx.lineWidth = 2.1
            ctx.beginPath()
            ctx.moveTo(mL.x, mL.y)
            ctx.quadraticCurveTo(points["lipCenter"].x, points["lipCenter"].y, mR.x, mR.y)
            ctx.stroke()
        }
    }

    function drawNeuralFaceNodes(ctx, points, primary, accent, voice, compact) {
        if (points._female && !femaleShowWireNodes) {
            return
        }
        var names = points._female && points.female_wire_nodes ? points.female_wire_nodes : [
            "top", "foreheadL", "foreheadR", "templeL", "templeR", "cheekL", "cheekR", "jawL", "jawR", "chin",
            "browCenter", "browL1", "browL2", "browR1", "browR2", "eyeLO", "eyeLI", "eyeRO", "eyeRI",
            "noseTop", "noseBridgeL", "noseBridgeR", "noseTip", "noseL", "noseR", "mouthL", "mouthR", "mouthTop", "mouthBottom"
        ]
        var limit = compact && !points._female ? Math.min(names.length, 18) : names.length
        for (var i = 0; i < limit; i++) {
            var point = points[names[i]]
            if (!point) continue
            var pulse = 0.55 + 0.45 * Math.sin(animationTick * 2.1 + i * 0.93)
            var hot = points._female && femaleReferenceNodes
            var color = hot ? "#f59e0b" : (i % 2 === 0 ? primary : accent)
            var alpha = (hot ? 0.86 : 0.56) + voice * 0.22 + pulse * 0.08
            if (points._female && femaleNodeGlowEnabled && !compact) {
                ctx.fillStyle = rgba(color, 0.10 + voice * 0.08)
                ctx.beginPath()
                ctx.arc(point.x, point.y, 5.0 + voice * 2.2 + pulse * 1.2, 0, Math.PI * 2)
                ctx.fill()
            }
            ctx.fillStyle = rgba(color, alpha * lineBrightness)
            ctx.beginPath()
            ctx.arc(point.x, point.y, (points._female ? 4.0 : 1.8) + voice * 1.6 + pulse * 0.55, 0, Math.PI * 2)
            ctx.fill()
            if (points._female) {
                ctx.strokeStyle = "rgba(255, 255, 255, 0.55)"
                ctx.lineWidth = 0.7
                ctx.stroke()
            }
        }
    }

    function drawNeuralFace(ctx, width, height, cx, cy, primary, accent, voice, outer, style) {
        if (!neuralFaceEnabled) {
            drawOrb(ctx, cx, cy, Math.max(42, Math.min(width, height) * 0.18), primary, accent, voice, false)
            return
        }
        var faceReduced = reducedEffects || neuralFaceReducedAnimation
        var kind = neuralFaceKind(style)
        if (kind === "female" && !femaleNeuralFaceEnabled) {
            drawOrb(ctx, cx, cy, Math.max(42, Math.min(width, height) * 0.18), primary, accent, voice, false)
            return
        }
        var intensity = neuralFaceAnimationIntensity * (faceReduced ? 0.45 : 1.0)
        var scale = Math.min(width, height) * 0.39 * neuralFaceSize
        var faceCx = cx + Math.sin(animationTick * 0.25) * scale * 0.012 * intensity
        var faceCy = cy + Math.cos(animationTick * 0.21) * scale * 0.010 * intensity
        var tuning = neuralMoodTuning()
        var blink = 0.0
        if (neuralFaceBlinkEnabled && !faceReduced) {
            var cycle = Math.floor(animationTick / 4.1)
            var blinkPeriod = 3.3 + (Math.sin(cycle * 12.9898) * 0.5 + 0.5) * 3.6
            var phase = animationTick % blinkPeriod
            if (phase > blinkPeriod - 0.34) {
                blink = Math.sin(((phase - (blinkPeriod - 0.34)) / 0.34) * Math.PI)
            }
            if (aiState === "thinking") {
                var thoughtBlink = (animationTick * 0.75) % 4.9
                if (thoughtBlink > 4.58) {
                    blink = Math.max(blink, Math.sin(((thoughtBlink - 4.58) / 0.32) * Math.PI) * 0.82)
                }
            }
        }
        var gazeX = 0.0
        var gazeY = 0.0
        if (neuralFaceEyeMovementEnabled && !faceReduced) {
            gazeX = Math.sin(animationTick * 0.42) * 0.15 * intensity
            gazeY = Math.cos(animationTick * 0.37) * 0.11 * intensity
        }
        var points = neuralFaceTemplate(kind, faceCx, faceCy, scale, voice, tuning, blink, gazeX, gazeY)

        ctx.save()
        ctx.globalAlpha = neuralFaceOpacity
        if (neuralFaceGlowEnabled) {
            drawSoftAura(ctx, faceCx, faceCy, scale * 0.72, primary, accent, Math.max(voice, outer * 0.60))
        }
        if (!faceReduced && kind !== "female") {
            drawOrbitingNeuralNetwork(ctx, width, height, faceCx, faceCy, primary, accent, Math.max(outer, voice * 0.55))
        }
        var femaleReferenceDrawn = kind === "female" && points._femaleReferenceLoaded
            ? drawFemaleReferenceAvatar(ctx, faceCx, faceCy, scale, voice, outer)
            : false
        if (femaleReferenceDrawn) {
            ctx.save()
            ctx.globalAlpha = ctx.globalAlpha * (0.62 + voice * 0.18 + outer * 0.08)
            drawNeuralFaceWire(ctx, points, primary, accent, voice)
            drawNeuralFaceNodes(ctx, points, primary, accent, voice, faceReduced)
            ctx.restore()
        } else if (kind === "female" && femaleDepthEnabled && !faceReduced) {
            var depthX = Math.sin(animationTick * 0.31) * scale * 0.010 * intensity
            var depthY = Math.cos(animationTick * 0.27) * scale * 0.008 * intensity
            ctx.save()
            ctx.translate(-depthX * 0.85, -depthY * 0.55)
            drawNeuralFaceHair(ctx, points, kind, primary, accent)
            ctx.restore()
            ctx.save()
            ctx.translate(depthX * 0.18, depthY * 0.12)
            drawNeuralFaceFacets(ctx, points, primary, accent, voice, kind)
            ctx.restore()
            ctx.save()
            ctx.translate(depthX * 0.46, depthY * 0.34)
            drawNeuralFaceWire(ctx, points, primary, accent, voice)
            drawNeuralFaceFeatures(ctx, points, primary, accent, voice, tuning, blink, gazeX, gazeY)
            drawNeuralFaceNodes(ctx, points, primary, accent, voice, faceReduced)
            ctx.restore()
        } else {
            drawNeuralFaceHair(ctx, points, kind, primary, accent)
            drawNeuralFaceFacets(ctx, points, primary, accent, voice, kind)
            drawNeuralFaceWire(ctx, points, primary, accent, voice)
            drawNeuralFaceFeatures(ctx, points, primary, accent, voice, tuning, blink, gazeX, gazeY)
            drawNeuralFaceNodes(ctx, points, primary, accent, voice, faceReduced)
        }
        ctx.restore()
    }

    Timer {
        interval: root.reducedEffects ? 50 : 33
        repeat: true
        running: root.visible
        onTriggered: {
            var dt = interval / 1000.0
            root.animationTick += dt * root.animationSpeed * (root.moodColorsEnabled ? root.moodPulseMultiplier : 1.0)
            var voiceTarget = root.clamp01(root.audioLevel)
            var peakTarget = Math.max(voiceTarget, root.clamp01(root.peakLevel))
            var musicTarget = root.musicReactivityEnabled ? root.clamp01(root.musicLevel * root.musicReactivity) : 0.0
            var musicPeakTarget = root.musicReactivityEnabled ? Math.max(musicTarget, root.clamp01(root.musicPeak * root.musicReactivity)) : 0.0
            var waitTarget = root.aiState === "thinking" ? 0.18 + Math.sin(root.animationTick * 1.25) * 0.06 : 0.06 + Math.sin(root.animationTick * 0.75) * 0.025
            root.renderVoiceLevel = root.smoothLevel(root.renderVoiceLevel, voiceTarget, 0.50, 0.24)
            root.renderPeakLevel = root.smoothLevel(root.renderPeakLevel, peakTarget, 0.42, 0.14)
            root.renderMusicLevel = root.smoothLevel(root.renderMusicLevel, musicTarget, 0.38, 0.16)
            root.renderMusicPeak = root.smoothLevel(root.renderMusicPeak, musicPeakTarget, 0.34, 0.10)
            root.waitingLevel = root.smoothLevel(root.waitingLevel, waitTarget, 0.22, 0.14)
            presenceCanvas.requestPaint()
        }
    }

    Canvas {
        id: presenceCanvas
        anchors.fill: parent
        renderTarget: Canvas.Image
        Component.onCompleted: loadImage(root.femaleReferenceAvatarSource)
        onImageLoaded: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            root.clearCanvas(ctx, width, height)
            if (!root.active) {
                return
            }

            var voice = root.clamp01(root.renderVoiceLevel)
            var peak = Math.max(voice, root.clamp01(root.renderPeakLevel))
            var music = root.clamp01(root.renderMusicLevel)
            var musicPeak = Math.max(music, root.clamp01(root.renderMusicPeak))
            var outer = Math.max(musicPeak, root.waitingLevel, peak * 0.32)
            if (root.moodColorsEnabled) {
                outer = root.clamp01(outer * root.moodParticleMultiplier)
            }
            var level = Math.max(voice, outer * 0.42)
            var style = String(root.visualStyle || "breathing_orb").toLowerCase()
            var primary = root.palettePrimary(style)
            var accent = root.paletteAccent(style)
            var cx = width * 0.5 + root.idleMotionOffset("x", width, height)
            var cy = height * 0.5 + root.idleMotionOffset("y", width, height)
            var pulse = 1.0 + Math.sin(root.animationTick * 2.0) * 0.035 * root.pulseIntensity + voice * 0.12 * root.speakingReactivity
            var base = Math.min(width, height) * (style === "minimal_dot" ? 0.075 : 0.19)
            var radius = Math.max(style === "minimal_dot" ? 18 : 42, base * pulse)

            if (style === "classic_neural_orb") {
                var classicRadius = Math.max(46, Math.min(width, height) * (0.145 + voice * 0.018))
                root.drawClassicBackground(ctx, width, height)
                root.drawOrbitingNeuralNetwork(ctx, width, height, cx, cy, primary, accent, outer)
                root.drawClassicTalkCircle(ctx, cx, cy, classicRadius, primary, accent, voice)
                return
            }

            root.drawBackground(ctx, width, height)
            root.drawSoftAura(ctx, cx, cy, radius * 1.45, primary, accent, outer)
            if (style !== "vector_voice_orb" && style !== "blue_flame_smoke") {
                root.drawParticles(ctx, width, height, cx, cy, primary, accent, outer)
            }

            if (root.isNeuralFaceStyle(style)) {
                root.drawNeuralFace(ctx, width, height, cx, cy, primary, accent, voice, outer, style)
            } else if (style === "neural_network_pulse") {
                root.drawNeuralNetwork(ctx, width, height, cx, cy, primary, accent, outer)
                root.drawOrb(ctx, cx, cy, radius * 0.74, primary, accent, voice, false)
            } else if (style === "blue_flame_smoke") {
                root.drawBlueFlameSmoke(ctx, width, height, cx, cy, radius, primary, accent, voice, outer)
            } else if (style === "vector_voice_orb") {
                root.drawVectorVoiceOrb(ctx, width, height, cx, cy, radius, primary, accent, voice, outer)
            } else if (style === "circular_audio_waveform") {
                root.drawCircularWaveform(ctx, cx, cy, radius, primary, accent, Math.max(voice, outer * 0.65))
            } else if (style === "halo_rings") {
                root.drawRings(ctx, cx, cy, radius, primary, accent, outer, 7, true)
                root.drawOrb(ctx, cx, cy, radius * 0.58, primary, accent, voice, false)
            } else if (style === "minimal_dot") {
                root.drawRings(ctx, cx, cy, radius, primary, accent, outer, 2, false)
                root.drawOrb(ctx, cx, cy, radius, primary, accent, voice, true)
            } else if (style === "hologram_core") {
                root.drawHologramCore(ctx, width, height, cx, cy, radius, primary, accent, Math.max(voice, outer * 0.55))
            } else if (style === "signal_bloom") {
                root.drawSignalBloom(ctx, cx, cy, radius, primary, accent, outer)
            } else if (style === "crystal_prism") {
                root.drawCrystalPrism(ctx, cx, cy, radius * 1.1, primary, accent, Math.max(voice, outer * 0.6))
            } else {
                root.drawRings(ctx, cx, cy, radius, primary, accent, outer, 5, false)
                root.drawOrb(ctx, cx, cy, radius, primary, accent, voice, false)
            }
        }
    }

    LivePresenceControls {
        id: liveControls
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 14
        z: 50
        presenceBridge: root.bridge
    }

    Component.onCompleted: {
        root.femaleReferenceTopology = root.loadFemaleReferenceTopology()
        presenceCanvas.requestPaint()
    }

    onAiStateChanged: presenceCanvas.requestPaint()
    onEnabledChanged: presenceCanvas.requestPaint()
    onDisplayModeChanged: presenceCanvas.requestPaint()
    onVisualStyleChanged: presenceCanvas.requestPaint()
    onOverlayOpacityChanged: presenceCanvas.requestPaint()
    onPulseIntensityChanged: presenceCanvas.requestPaint()
    onSpeakingReactivityChanged: presenceCanvas.requestPaint()
    onIdleMotionStrengthChanged: presenceCanvas.requestPaint()
    onNodeDensityChanged: presenceCanvas.requestPaint()
    onParticleDensityChanged: presenceCanvas.requestPaint()
    onReducedEffectsChanged: presenceCanvas.requestPaint()
    onShadersEnabledChanged: presenceCanvas.requestPaint()
    onParticlesEnabledChanged: presenceCanvas.requestPaint()
    onTransparentBackgroundChanged: presenceCanvas.requestPaint()
    onMusicReactivityEnabledChanged: presenceCanvas.requestPaint()
    onMusicReactivityChanged: presenceCanvas.requestPaint()
    onMoodNameChanged: presenceCanvas.requestPaint()
    onNeuralFaceEnabledChanged: presenceCanvas.requestPaint()
    onNeuralFaceVariantChanged: presenceCanvas.requestPaint()
    onNeuralFaceSizeChanged: presenceCanvas.requestPaint()
    onNeuralFaceOpacityChanged: presenceCanvas.requestPaint()
    onNeuralFaceAnimationIntensityChanged: presenceCanvas.requestPaint()
    onNeuralFaceLipSyncStrengthChanged: presenceCanvas.requestPaint()
    onNeuralFaceEyeMovementEnabledChanged: presenceCanvas.requestPaint()
    onNeuralFaceBlinkEnabledChanged: presenceCanvas.requestPaint()
    onNeuralFaceGlowEnabledChanged: presenceCanvas.requestPaint()
    onNeuralFaceEmotionEnabledChanged: presenceCanvas.requestPaint()
    onNeuralFaceAudioLipSyncEnabledChanged: presenceCanvas.requestPaint()
    onNeuralFaceReducedAnimationChanged: presenceCanvas.requestPaint()
    onFemaleNeuralFaceEnabledChanged: presenceCanvas.requestPaint()
    onFemaleReferenceNodesChanged: presenceCanvas.requestPaint()
    onFemaleShowWireNodesChanged: presenceCanvas.requestPaint()
    onFemaleShowWireLinesChanged: presenceCanvas.requestPaint()
    onFemaleNodeGlowEnabledChanged: presenceCanvas.requestPaint()
    onFemaleWirePulseEnabledChanged: presenceCanvas.requestPaint()
    onFemaleDepthEnabledChanged: presenceCanvas.requestPaint()
}
