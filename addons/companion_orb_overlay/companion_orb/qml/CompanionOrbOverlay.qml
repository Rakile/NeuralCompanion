import QtQuick 2.15

Item {
    id: root
    anchors.fill: parent

    property var orbBridge: companionOrbBridge
    property string aiState: orbBridge ? orbBridge.aiState : "idle"
    property real audioLevel: orbBridge ? orbBridge.audioLevel : 0.0
    property string visualStyle: orbBridge ? orbBridge.visualStyle : "neural_spark"
    property real orbOpacity: orbBridge ? orbBridge.orbOpacity : 0.82
    property int orbSize: orbBridge ? orbBridge.orbSize : 92
    property bool editMode: orbBridge ? orbBridge.editMode : false
    property bool placementMode: orbBridge ? orbBridge.placementMode : false
    property bool targetActive: orbBridge ? orbBridge.targetActive : false
    property bool showTargetLabel: orbBridge ? orbBridge.showTargetLabel : true
    property string targetTitle: orbBridge ? orbBridge.targetTitle : ""
    property bool reducedEffects: orbBridge ? orbBridge.reducedEffects : false
    property bool particlesEnabled: orbBridge ? orbBridge.particlesEnabled : true
    property bool fallingParticlesEnabled: orbBridge ? orbBridge.fallingParticlesEnabled : false
    property bool shadersEnabled: orbBridge ? orbBridge.shadersEnabled : true
    property real speakingReactivity: orbBridge ? orbBridge.speakingReactivity : 0.85
    property int frameRate: orbBridge ? orbBridge.frameRate : 60
    property bool voiceSyncEnabled: orbBridge ? orbBridge.voiceSyncEnabled : true
    property real glowStrength: orbBridge ? orbBridge.glowStrength : 1.0
    property real trailLength: orbBridge ? orbBridge.trailLength : 0.55
    property int particleDensity: orbBridge ? orbBridge.particleDensity : 30
    property int fallingParticleDensity: orbBridge ? orbBridge.fallingParticleDensity : 18
    property real fallingParticleLifetime: orbBridge ? orbBridge.fallingParticleLifetime : 3.8
    property real smokeIntensity: orbBridge ? orbBridge.smokeIntensity : 0.35
    property real moodColorIntensity: orbBridge ? orbBridge.moodColorIntensity : 0.85
    property bool customColorsEnabled: orbBridge ? orbBridge.customColorsEnabled : false
    property bool stateColorsEnabled: orbBridge ? orbBridge.stateColorsEnabled : false
    property bool stateAnimationEnabled: orbBridge ? orbBridge.stateAnimationEnabled : false
    property color primaryColor: orbBridge ? orbBridge.primaryColor : "#38bdf8"
    property color secondaryColor: orbBridge ? orbBridge.secondaryColor : "#22d3ee"
    property color accentColor: orbBridge ? orbBridge.accentColor : "#a78bfa"
    property color glowColor: orbBridge ? orbBridge.glowColor : "#67e8f9"
    property color idleColor: orbBridge ? orbBridge.idleColor : "#38bdf8"
    property color thinkingColor: orbBridge ? orbBridge.thinkingColor : "#a78bfa"
    property color speakingColor: orbBridge ? orbBridge.speakingColor : "#f472b6"
    property bool gazeTimerActive: orbBridge ? orbBridge.gazeTimerActive : false
    property real gazeTimerProgress: orbBridge ? orbBridge.gazeTimerProgress : 0.0
    property color gazeTimerColor: orbBridge ? orbBridge.gazeTimerColor : "#facc15"
    property real renderedGazeTimerProgress: gazeTimerActive ? gazeTimerProgress : 0.0
    property string idleAnimation: orbBridge ? orbBridge.idleAnimation : "calm_breathe"
    property string thinkingAnimation: orbBridge ? orbBridge.thinkingAnimation : "thinking_swirl"
    property string speakingAnimation: orbBridge ? orbBridge.speakingAnimation : "voice_ripple"
    property real tick: 0.0
    property real lastTickMs: 0.0

    Behavior on renderedGazeTimerProgress {
        NumberAnimation {
            duration: root.gazeTimerActive ? 75 : 220
            easing.type: Easing.OutCubic
        }
    }

    function hexByte(value) {
        var number = Math.max(0, Math.min(255, Math.round(value)))
        var text = number.toString(16)
        return text.length < 2 ? "0" + text : text
    }

    function toHex(c) {
        return "#" + hexByte(c.r * 255) + hexByte(c.g * 255) + hexByte(c.b * 255)
    }

    function hexColor(hex) {
        var value = String(hex || "#38bdf8")
        if (value.charAt(0) === "#") value = value.slice(1)
        if (value.length === 3) {
            value = value.charAt(0) + value.charAt(0) + value.charAt(1) + value.charAt(1) + value.charAt(2) + value.charAt(2)
        }
        return Qt.rgba(parseInt(value.slice(0, 2), 16) / 255.0, parseInt(value.slice(2, 4), 16) / 255.0, parseInt(value.slice(4, 6), 16) / 255.0, 1.0)
    }

    function rgba(c, alpha) {
        return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + "," + alpha + ")"
    }

    function blendColor(base, mood, amount) {
        var t = Math.max(0.0, Math.min(1.0, Number(amount) || 0.0))
        return Qt.rgba(
            base.r * (1.0 - t) + mood.r * t,
            base.g * (1.0 - t) + mood.g * t,
            base.b * (1.0 - t) + mood.b * t,
            1.0
        )
    }

    function stylePrimary() {
        if (visualStyle === "aurora_glass") return root.hexColor("#7dd3fc")
        if (visualStyle === "prismatic_pulse") return root.hexColor("#38bdf8")
        if (visualStyle === "aether_wisp") return root.hexColor("#60a5fa")
        if (visualStyle === "celestial_firetrail") return root.hexColor("#fde68a")
        if (visualStyle === "quantum_halo") return root.hexColor("#22d3ee")
        if (visualStyle === "event_horizon") return root.hexColor("#818cf8")
        if (visualStyle === "holographic_iris") return root.hexColor("#2dd4bf")
        if (visualStyle === "synaptic_bloom") return root.hexColor("#34d399")
        if (visualStyle === "liquid_core") return root.hexColor("#38bdf8")
        if (visualStyle === "void_prism") return root.hexColor("#c084fc")
        return root.hexColor("#38bdf8")
    }

    function styleSecondary() {
        if (visualStyle === "aurora_glass") return root.hexColor("#a78bfa")
        if (visualStyle === "prismatic_pulse") return root.hexColor("#e879f9")
        if (visualStyle === "aether_wisp") return root.hexColor("#67e8f9")
        if (visualStyle === "celestial_firetrail") return root.hexColor("#60a5fa")
        if (visualStyle === "quantum_halo") return root.hexColor("#6366f1")
        if (visualStyle === "event_horizon") return root.hexColor("#0f172a")
        if (visualStyle === "holographic_iris") return root.hexColor("#a78bfa")
        if (visualStyle === "synaptic_bloom") return root.hexColor("#06b6d4")
        if (visualStyle === "liquid_core") return root.hexColor("#67e8f9")
        if (visualStyle === "void_prism") return root.hexColor("#22d3ee")
        return root.hexColor("#22d3ee")
    }

    function styleAccent() {
        if (visualStyle === "aurora_glass") return root.hexColor("#f0abfc")
        if (visualStyle === "prismatic_pulse") return root.hexColor("#fb7185")
        if (visualStyle === "aether_wisp") return root.hexColor("#dbeafe")
        if (visualStyle === "celestial_firetrail") return root.hexColor("#fbbf24")
        if (visualStyle === "quantum_halo") return root.hexColor("#f0abfc")
        if (visualStyle === "event_horizon") return root.hexColor("#f472b6")
        if (visualStyle === "holographic_iris") return root.hexColor("#fbbf24")
        if (visualStyle === "synaptic_bloom") return root.hexColor("#f472b6")
        if (visualStyle === "liquid_core") return root.hexColor("#a78bfa")
        if (visualStyle === "void_prism") return root.hexColor("#f8fafc")
        return root.hexColor("#f59e0b")
    }

    function paletteHighlightColor() {
        return root.blendColor(root.accentColor, root.primaryColor, 0.22)
    }

    function paletteCoolColor() {
        return root.blendColor(root.secondaryColor, root.primaryColor, 0.44)
    }

    function observingActive() {
        return (targetActive || placementMode) && aiState !== "speaking" && aiState !== "thinking"
    }

    function stateExpressionColor() {
        if (aiState === "speaking") return root.hexColor("#f472b6")
        if (aiState === "thinking") return root.hexColor("#a78bfa")
        if (root.observingActive()) return root.hexColor("#2dd4bf")
        if (aiState === "listening") return root.hexColor("#60a5fa")
        return root.hexColor("#38bdf8")
    }

    function stateExpressionMix(level) {
        if (aiState === "speaking") return Math.min(0.72, 0.28 + level * 0.62)
        if (aiState === "thinking") return 0.30 + Math.sin(tick * 1.4) * 0.06
        if (root.observingActive()) return 0.36 + Math.sin(tick * 0.9) * 0.05
        if (aiState === "listening") return 0.20 + Math.sin(tick * 1.1) * 0.04
        return 0.05
    }

    function stateTintColor() {
        if (aiState === "speaking") return root.speakingColor
        if (aiState === "thinking") return root.thinkingColor
        return root.idleColor
    }

    function activeStateAnimation() {
        if (!stateAnimationEnabled) return "style_default"
        if (aiState === "speaking") return root.speakingAnimation
        if (aiState === "thinking") return root.thinkingAnimation
        return root.idleAnimation
    }

    function animationPulse(mode, level) {
        if (mode === "calm_breathe") return 0.36 + 0.64 * (0.5 + Math.sin(tick * 0.78) * 0.5)
        if (mode === "slow_orbit") return 0.18 + 0.18 * Math.sin(tick * 0.52)
        if (mode === "focused_pulse") return Math.pow(Math.abs(Math.sin(tick * 2.15)), 1.6) * 0.95
        if (mode === "thinking_swirl") return 0.34 + 0.30 * Math.sin(tick * 1.45)
        if (mode === "voice_ripple") return Math.max(0.08, Math.min(1.0, level * 1.35))
        if (mode === "energetic_sparkle") return 0.28 + 0.72 * Math.abs(Math.sin(tick * 4.1))
        return 0.0
    }

    function stateOrbitSpeed(mode) {
        if (mode === "slow_orbit") return 0.38
        if (mode === "thinking_swirl") return 2.25
        if (mode === "voice_ripple") return 1.35
        if (mode === "energetic_sparkle") return 2.9
        if (mode === "focused_pulse") return 1.15
        return 1.0
    }

    function levelBoost() {
        if (voiceSyncEnabled && aiState === "speaking") {
            return Math.max(0.08, audioLevel * speakingReactivity)
        }
        if (aiState === "thinking") {
            return 0.24 + Math.sin(tick * 1.4) * 0.05
        }
        if (aiState === "listening") {
            return 0.15 + Math.sin(tick * 1.7) * 0.04
        }
        return 0.055 + Math.sin(tick * 0.62) * 0.018
    }

    function frameIntervalMs() {
        var fps = Math.max(30, Math.min(120, Number(root.frameRate) || 60))
        if (root.reducedEffects) {
            fps = Math.min(fps, 30)
        }
        return Math.max(8, Math.floor(1000 / fps))
    }

    Timer {
        id: animationTimer
        interval: root.frameIntervalMs()
        repeat: true
        running: true
        onTriggered: {
            var now = Date.now()
            if (lastTickMs <= 0) {
                lastTickMs = now
            }
            var elapsed = Math.max(0.0, Math.min(0.12, (now - lastTickMs) / 1000.0))
            lastTickMs = now
            tick += elapsed
            orbCanvas.requestPaint()
        }
    }

    Canvas {
        id: orbCanvas
        anchors.fill: parent
        antialiasing: true
        renderTarget: Canvas.Image

        onPaint: {
            var ctx = getContext("2d")
            var w = width
            var h = height
            ctx.clearRect(0, 0, w, h)
            var cx = w / 2
            var cy = h / 2
            var level = Math.max(0.0, Math.min(1.0, root.levelBoost()))
            var stateAnimation = root.activeStateAnimation()
            var statePulse = root.animationPulse(stateAnimation, level)
            var size = Math.max(20, root.orbSize)
            var radius = size * (0.38 + level * 0.08 + statePulse * 0.026)
            var outer = radius * (1.55 + root.glowStrength * 0.45 + level * 0.35 + statePulse * 0.26)
            var stateColor = root.stateTintColor()
            var moodMix = Math.max(0.0, Math.min(1.0, root.moodColorIntensity))
            var glowMoodMix = moodMix <= 0.0 ? 0.0 : Math.max(0.25, moodMix)
            var primary = root.stateColorsEnabled ? stateColor : (root.customColorsEnabled ? root.primaryColor : root.blendColor(root.stylePrimary(), root.primaryColor, moodMix))
            var secondary = root.stateColorsEnabled ? root.blendColor(stateColor, root.hexColor("#ffffff"), 0.30) : (root.customColorsEnabled ? root.secondaryColor : root.blendColor(root.styleSecondary(), root.secondaryColor, moodMix))
            var accent = root.stateColorsEnabled ? root.blendColor(stateColor, root.hexColor("#020617"), 0.26) : (root.customColorsEnabled ? root.accentColor : root.blendColor(root.styleAccent(), root.accentColor, moodMix))
            var glow = root.stateColorsEnabled ? root.blendColor(stateColor, root.hexColor("#ffffff"), 0.42) : (root.customColorsEnabled ? root.glowColor : root.blendColor(primary, root.glowColor, glowMoodMix))
            if (!root.stateColorsEnabled && !root.customColorsEnabled) {
                var expressionColor = root.stateExpressionColor()
                var expressionMix = root.stateExpressionMix(level)
                primary = root.blendColor(primary, expressionColor, expressionMix)
                secondary = root.blendColor(secondary, expressionColor, expressionMix * 0.65)
                accent = root.blendColor(accent, expressionColor, expressionMix * 0.45)
                glow = root.blendColor(glow, expressionColor, Math.min(0.65, expressionMix + 0.12))
            }
            var gazeMix = Math.max(0.0, Math.min(1.0, root.renderedGazeTimerProgress)) * 0.90
            if (gazeMix > 0.0) {
                primary = root.blendColor(primary, root.gazeTimerColor, gazeMix)
                secondary = root.blendColor(secondary, root.gazeTimerColor, gazeMix * 0.88)
                accent = root.blendColor(accent, root.gazeTimerColor, gazeMix * 0.76)
                glow = root.blendColor(glow, root.gazeTimerColor, Math.min(1.0, gazeMix + 0.10))
            }

            ctx.globalAlpha = root.orbOpacity
            if (root.shadersEnabled) {
                var glowGradient = ctx.createRadialGradient(cx, cy, radius * 0.15, cx, cy, outer)
                glowGradient.addColorStop(0.0, root.rgba(glow, 0.32 + level * 0.22 + statePulse * 0.10))
                glowGradient.addColorStop(0.42, root.rgba(primary, 0.16 + level * 0.12 + statePulse * 0.06))
                glowGradient.addColorStop(1.0, "rgba(0,0,0,0)")
                ctx.fillStyle = glowGradient
                ctx.beginPath()
                ctx.arc(cx, cy, outer, 0, Math.PI * 2)
                ctx.fill()
            }

            if (root.particlesEnabled && !root.reducedEffects) {
                drawParticles(ctx, cx, cy, radius, primary, secondary, accent, level)
            }

            drawVisualStyle(ctx, cx, cy, radius, primary, secondary, accent, level)

            if (root.fallingParticlesEnabled && !root.reducedEffects) {
                drawFallingParticles(ctx, cx, cy, radius, primary, secondary, accent, level)
            }

            if (root.targetActive || root.placementMode || root.editMode) {
                ctx.globalAlpha = 0.92
                ctx.strokeStyle = root.targetActive ? root.rgba(accent, 0.72) : root.rgba(primary, 0.54)
                ctx.lineWidth = root.placementMode ? 3 : 2
                ctx.setLineDash(root.placementMode ? [8, 6] : [])
                ctx.beginPath()
                ctx.arc(cx, cy, radius * 1.28, 0, Math.PI * 2)
                ctx.stroke()
                ctx.setLineDash([])
            }
        }

        function drawVisualStyle(ctx, cx, cy, radius, primary, secondary, accent, level) {
            if (visualStyle === "aurora_glass") {
                drawAuroraGlass(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            if (visualStyle === "prismatic_pulse") {
                drawPrismaticPulse(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            if (visualStyle === "aether_wisp") {
                drawAetherWisp(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            if (visualStyle === "celestial_firetrail") {
                drawCelestialFiretrail(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            if (visualStyle === "quantum_halo") {
                drawQuantumHalo(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            if (visualStyle === "event_horizon") {
                drawEventHorizon(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            if (visualStyle === "holographic_iris") {
                drawHolographicIris(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            if (visualStyle === "synaptic_bloom") {
                drawSynapticBloom(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            if (visualStyle === "liquid_core") {
                drawLiquidCore(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            if (visualStyle === "void_prism") {
                drawVoidPrism(ctx, cx, cy, radius, primary, secondary, accent, level)
                return
            }
            drawNeuralSpark(ctx, cx, cy, radius, primary, secondary, accent, level)
        }

        function drawAuroraGlass(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var speaking = aiState === "speaking" ? level : 0.0
            var thinking = aiState === "thinking" ? 1.0 : 0.0
            var observing = root.observingActive() ? 1.0 : 0.0
            var breathe = 0.5 + Math.sin(root.tick * 0.74) * 0.5
            var shell = ctx.createRadialGradient(cx - radius * 0.32, cy - radius * 0.38, radius * 0.05, cx, cy, radius * 1.18)
            shell.addColorStop(0.0, "rgba(255,255,255," + (0.24 + speaking * 0.18) + ")")
            shell.addColorStop(0.25, root.rgba(primary, 0.25 + speaking * 0.12))
            shell.addColorStop(0.62, root.rgba(secondary, 0.12 + thinking * 0.10))
            shell.addColorStop(1.0, root.rgba(accent, 0.04 + observing * 0.06))
            ctx.fillStyle = shell
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (1.0 + speaking * 0.035), 0, Math.PI * 2)
            ctx.fill()

            ctx.lineCap = "round"
            ctx.strokeStyle = root.rgba(primary, 0.46 + speaking * 0.26)
            ctx.lineWidth = 1.4 + speaking * 2.2
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (1.02 + breathe * 0.018), 0, Math.PI * 2)
            ctx.stroke()

            ctx.strokeStyle = root.rgba(root.hexColor("#ffffff"), 0.18 + observing * 0.14)
            ctx.lineWidth = 1.0
            ctx.beginPath()
            ctx.arc(cx - radius * 0.12, cy - radius * 0.08, radius * 0.82, Math.PI * 0.78, Math.PI * 1.45)
            ctx.stroke()

            for (var i = 0; i < 4; i++) {
                var phase = root.tick * (0.32 + i * 0.05 + thinking * 0.10) + i * 1.52
                var alpha = 0.20 + speaking * 0.26 + thinking * 0.12 + observing * 0.08
                ctx.save()
                ctx.translate(cx, cy)
                ctx.rotate(Math.sin(phase) * 0.34 + i * 0.26)
                ctx.strokeStyle = root.rgba(i % 2 ? accent : secondary, alpha)
                ctx.lineWidth = radius * (0.055 + i * 0.010) + speaking * 2.4
                ctx.beginPath()
                ctx.moveTo(-radius * 0.70, Math.sin(phase) * radius * 0.18)
                ctx.bezierCurveTo(
                    -radius * 0.38, -radius * (0.64 + Math.sin(phase * 0.7) * 0.12),
                    radius * 0.36, radius * (0.58 + Math.cos(phase) * 0.08),
                    radius * 0.78, Math.sin(phase + 1.2) * radius * 0.16
                )
                ctx.stroke()
                ctx.restore()
            }

            if (observing > 0.0) {
                var sweep = root.tick * 0.95
                ctx.strokeStyle = root.rgba(accent, 0.44)
                ctx.lineWidth = 2.2
                ctx.beginPath()
                ctx.arc(cx, cy, radius * 1.18, sweep, sweep + Math.PI * 0.36)
                ctx.stroke()
            }
        }

        function drawPrismaticPulse(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var colors = [primary, secondary, accent, root.paletteHighlightColor(), root.paletteCoolColor()]
            var ringPulse = aiState === "speaking" ? level : (0.14 + Math.abs(Math.sin(root.tick * 1.15)) * 0.10)
            ctx.lineCap = "round"

            var core = ctx.createRadialGradient(cx, cy, radius * 0.12, cx, cy, radius * 0.72)
            core.addColorStop(0.0, "rgba(255,255,255," + (0.10 + ringPulse * 0.12) + ")")
            core.addColorStop(0.42, root.rgba(secondary, 0.12 + ringPulse * 0.08))
            core.addColorStop(1.0, "rgba(0,0,0,0)")
            ctx.fillStyle = core
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 0.72, 0, Math.PI * 2)
            ctx.fill()

            for (var i = 0; i < 7; i++) {
                var start = root.tick * (0.34 + i * 0.045) + i * 0.82
                var span = Math.PI * (0.34 + ((i * 17) % 13) / 40.0 + ringPulse * 0.18)
                ctx.strokeStyle = root.rgba(colors[i % colors.length], 0.30 + ringPulse * 0.34)
                ctx.lineWidth = radius * (0.045 + (i % 3) * 0.012) + ringPulse * 3.2
                ctx.beginPath()
                ctx.arc(cx, cy, radius * (0.94 + (i % 4) * 0.030), start, start + span)
                ctx.stroke()
            }

            var count = root.reducedEffects ? 28 : 64
            for (var j = 0; j < count; j++) {
                var angle = (j / count) * Math.PI * 2
                var wobble = 0.5 + Math.sin(root.tick * 3.2 + j * 0.71) * 0.5
                var audioSpike = aiState === "speaking" ? level * (0.55 + wobble * 0.75) : wobble * 0.08
                var inner = radius * (1.02 + audioSpike * 0.03)
                var outer = radius * (1.12 + audioSpike * 0.24 + (j % 5) * 0.004)
                ctx.strokeStyle = root.rgba(colors[j % colors.length], 0.12 + audioSpike * 0.50)
                ctx.lineWidth = 1.0 + audioSpike * 2.4
                ctx.beginPath()
                ctx.moveTo(cx + Math.cos(angle) * inner, cy + Math.sin(angle) * inner)
                ctx.lineTo(cx + Math.cos(angle) * outer, cy + Math.sin(angle) * outer)
                ctx.stroke()
            }
        }

        function drawAetherWisp(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var speaking = aiState === "speaking" ? level : 0.0
            var thinking = aiState === "thinking" ? 1.0 : 0.0
            var tailLean = Math.sin(root.tick * 0.46) * 0.22 + thinking * 0.16
            ctx.lineCap = "round"

            for (var i = 0; i < 5; i++) {
                var phase = root.tick * (0.30 + i * 0.035) + i * 0.94
                ctx.save()
                ctx.translate(cx, cy)
                ctx.rotate(-0.22 + tailLean + Math.sin(phase) * 0.06)
                ctx.strokeStyle = root.rgba(i % 2 ? secondary : primary, 0.14 + root.trailLength * 0.15 + speaking * 0.18)
                ctx.lineWidth = radius * (0.065 - i * 0.006) + speaking * 2.0
                ctx.beginPath()
                ctx.moveTo(-radius * 0.05, radius * (0.10 + i * 0.025))
                ctx.bezierCurveTo(
                    -radius * (0.45 + i * 0.12), radius * (0.34 + Math.sin(phase) * 0.10),
                    -radius * (0.96 + i * 0.18), -radius * (0.10 + Math.cos(phase) * 0.16),
                    -radius * (1.32 + i * 0.16), -radius * (0.44 + Math.sin(phase * 0.8) * 0.20)
                )
                ctx.stroke()
                ctx.restore()
            }

            var core = ctx.createRadialGradient(cx - radius * 0.20, cy - radius * 0.26, radius * 0.08, cx, cy, radius * (1.0 + speaking * 0.08))
            core.addColorStop(0.0, "rgba(255,255,255," + (0.34 + speaking * 0.22) + ")")
            core.addColorStop(0.30, root.rgba(accent, 0.54 + speaking * 0.18))
            core.addColorStop(0.66, root.rgba(primary, 0.52 + speaking * 0.12))
            core.addColorStop(1.0, root.rgba(secondary, 0.12))
            ctx.fillStyle = core
            ctx.beginPath()
            ctx.arc(cx + Math.sin(root.tick * 0.8) * radius * 0.025, cy + Math.cos(root.tick * 0.68) * radius * 0.035, radius * (0.76 + speaking * 0.08), 0, Math.PI * 2)
            ctx.fill()

            ctx.strokeStyle = root.rgba(accent, 0.42 + speaking * 0.20)
            ctx.lineWidth = 1.2 + speaking * 1.5
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (0.85 + speaking * 0.05), Math.PI * 1.10, Math.PI * 1.92)
            ctx.stroke()

            var moteCount = root.reducedEffects ? 8 : Math.max(12, Math.min(34, Math.round(root.particleDensity * 0.38)))
            for (var m = 0; m < moteCount; m++) {
                var progress = ((root.tick * 0.09) + m * 0.137) % 1.0
                var x = cx - radius * (0.30 + progress * 1.40) + Math.sin(root.tick * 0.8 + m) * radius * 0.18
                var y = cy - radius * (0.10 + Math.sin(progress * Math.PI * 2 + m) * 0.36) - progress * radius * 0.54
                var fade = Math.sin(progress * Math.PI)
                ctx.fillStyle = root.rgba(m % 3 === 0 ? accent : secondary, 0.20 + fade * (0.34 + speaking * 0.18))
                ctx.beginPath()
                ctx.arc(x, y, 1.0 + fade * 1.8 + speaking * 1.2, 0, Math.PI * 2)
                ctx.fill()
            }
        }

        function drawCelestialFiretrail(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var speaking = aiState === "speaking" ? level : 0.0
            var thinking = aiState === "thinking" ? 1.0 : 0.0
            var observing = root.observingActive() ? 1.0 : 0.0
            ctx.lineCap = "round"

            for (var i = 0; i < 6; i++) {
                var phase = root.tick * (0.20 + i * 0.025 + thinking * 0.05) + i * 0.86
                var side = i % 2 === 0 ? -1 : 1
                ctx.strokeStyle = root.rgba(i % 3 === 0 ? accent : (i % 2 ? secondary : primary), 0.13 + root.trailLength * 0.18 + speaking * 0.18)
                ctx.lineWidth = radius * (0.028 + i * 0.004) + speaking * 1.8
                ctx.beginPath()
                ctx.moveTo(cx + side * radius * (0.10 + i * 0.035), cy + radius * (0.84 + i * 0.08))
                ctx.bezierCurveTo(
                    cx + side * radius * (0.34 + Math.sin(phase) * 0.18),
                    cy + radius * 0.28,
                    cx - side * radius * (0.42 + Math.cos(phase) * 0.12),
                    cy - radius * (0.62 + i * 0.08),
                    cx + side * radius * (0.18 + observing * 0.18),
                    cy - radius * (1.28 + i * 0.16)
                )
                ctx.stroke()
            }

            var moteCount = root.reducedEffects ? 18 : Math.max(22, Math.min(58, Math.round(root.particleDensity * 0.62)))
            for (var m = 0; m < moteCount; m++) {
                var seed = ((m * 41) % 113) / 113.0
                var progress = (root.tick * (0.055 + speaking * 0.055) + seed + m * 0.047) % 1.0
                var column = radius * (2.65 + root.trailLength * 0.85)
                var sway = Math.sin(root.tick * 0.55 + m * 1.31) * radius * (0.18 + observing * 0.10)
                var x = cx + (seed - 0.5) * radius * 0.72 + sway
                var y = cy + radius * 1.38 - progress * column
                var fade = Math.sin(progress * Math.PI)
                ctx.fillStyle = root.rgba(m % 4 === 0 ? secondary : (m % 3 === 0 ? accent : primary), 0.16 + fade * (0.42 + speaking * 0.28))
                ctx.beginPath()
                ctx.arc(x, y, 1.0 + fade * 2.6 + speaking * 1.8, 0, Math.PI * 2)
                ctx.fill()
            }

            var core = ctx.createRadialGradient(cx - radius * 0.18, cy - radius * 0.20, radius * 0.05, cx, cy, radius * 0.88)
            core.addColorStop(0.0, "rgba(255,255,255," + (0.42 + speaking * 0.22) + ")")
            core.addColorStop(0.34, root.rgba(primary, 0.62 + speaking * 0.16))
            core.addColorStop(0.72, root.rgba(accent, 0.28 + thinking * 0.14))
            core.addColorStop(1.0, root.rgba(secondary, 0.08 + observing * 0.08))
            ctx.fillStyle = core
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (0.58 + speaking * 0.08), 0, Math.PI * 2)
            ctx.fill()

            ctx.strokeStyle = root.rgba(primary, 0.34 + speaking * 0.22)
            ctx.lineWidth = 1.1 + speaking * 1.6
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (0.76 + Math.sin(root.tick * 0.7) * 0.03), 0, Math.PI * 2)
            ctx.stroke()
        }

        function drawQuantumHalo(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var speaking = aiState === "speaking" ? level : 0.0
            var thinking = aiState === "thinking" ? 1.0 : 0.0
            var observing = root.observingActive() ? 1.0 : 0.0
            var spin = root.tick * (0.40 + speaking * 0.56 + thinking * 0.18)
            ctx.lineCap = "round"

            var core = ctx.createRadialGradient(cx - radius * 0.18, cy - radius * 0.22, radius * 0.06, cx, cy, radius * 0.90)
            core.addColorStop(0.0, "rgba(255,255,255," + (0.28 + speaking * 0.22) + ")")
            core.addColorStop(0.25, root.rgba(primary, 0.48 + speaking * 0.16))
            core.addColorStop(0.67, root.rgba(secondary, 0.18 + observing * 0.12))
            core.addColorStop(1.0, root.rgba(accent, 0.04))
            ctx.fillStyle = core
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (0.66 + speaking * 0.06), 0, Math.PI * 2)
            ctx.fill()

            for (var i = 0; i < 6; i++) {
                var phase = spin + i * Math.PI / 3
                var ringRadius = radius * (0.80 + i * 0.055)
                ctx.strokeStyle = root.rgba(i % 2 ? secondary : accent, 0.18 + speaking * 0.26 + observing * 0.08)
                ctx.lineWidth = 1.0 + (i % 3) * 0.55 + speaking * 2.4
                ctx.save()
                ctx.translate(cx, cy)
                ctx.rotate(phase)
                ctx.scale(1.18 + Math.sin(phase) * 0.025, 0.66 + Math.cos(phase * 0.8) * 0.035)
                ctx.beginPath()
                ctx.arc(0, 0, ringRadius, Math.PI * 0.08, Math.PI * (1.26 + speaking * 0.18))
                ctx.stroke()
                ctx.restore()
            }

            var pointCount = root.reducedEffects ? 8 : 14
            for (var p = 0; p < pointCount; p++) {
                var angle = spin * 0.72 + (p / pointCount) * Math.PI * 2
                var pulse = 0.5 + Math.sin(root.tick * 2.4 + p * 1.7) * 0.5
                var dist = radius * (1.02 + pulse * 0.12 + observing * 0.08)
                ctx.fillStyle = root.rgba(p % 3 === 0 ? accent : primary, 0.22 + pulse * 0.32 + speaking * 0.18)
                ctx.beginPath()
                ctx.arc(cx + Math.cos(angle) * dist, cy + Math.sin(angle) * dist * 0.76, 1.2 + pulse * 1.8 + speaking * 1.2, 0, Math.PI * 2)
                ctx.fill()
            }
        }

        function drawEventHorizon(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var speaking = aiState === "speaking" ? level : 0.0
            var thinking = aiState === "thinking" ? 1.0 : 0.0
            var observing = root.observingActive() ? 1.0 : 0.0
            var spin = root.tick * (0.28 + speaking * 0.52 + thinking * 0.16)
            ctx.lineCap = "round"

            for (var i = 0; i < 5; i++) {
                var phase = spin + i * 0.62
                ctx.save()
                ctx.translate(cx, cy)
                ctx.rotate(phase)
                ctx.scale(1.42, 0.42 + i * 0.018)
                ctx.strokeStyle = root.rgba(i % 2 ? primary : accent, 0.16 + speaking * 0.30 + observing * 0.08)
                ctx.lineWidth = 1.2 + i * 0.45 + speaking * 2.0
                ctx.beginPath()
                ctx.arc(0, 0, radius * (0.70 + i * 0.08), Math.PI * 0.08, Math.PI * (0.95 + speaking * 0.22))
                ctx.stroke()
                ctx.restore()
            }

            var lens = ctx.createRadialGradient(cx, cy, radius * 0.22, cx, cy, radius * 1.04)
            lens.addColorStop(0.0, root.rgba(root.hexColor("#020617"), 0.94))
            lens.addColorStop(0.46, root.rgba(root.hexColor("#020617"), 0.84))
            lens.addColorStop(0.64, root.rgba(secondary, 0.30 + speaking * 0.16))
            lens.addColorStop(1.0, root.rgba(primary, 0.04))
            ctx.fillStyle = lens
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (0.72 + speaking * 0.035), 0, Math.PI * 2)
            ctx.fill()

            ctx.strokeStyle = root.rgba(accent, 0.56 + speaking * 0.30)
            ctx.lineWidth = 1.6 + speaking * 2.2
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (0.78 + Math.sin(root.tick * 0.9) * 0.018), spin, spin + Math.PI * 1.36)
            ctx.stroke()

            ctx.strokeStyle = root.rgba(primary, 0.22 + observing * 0.18)
            ctx.lineWidth = 1.0
            ctx.beginPath()
            ctx.moveTo(cx - radius * 1.16, cy + Math.sin(spin) * radius * 0.08)
            ctx.bezierCurveTo(cx - radius * 0.35, cy - radius * 0.18, cx + radius * 0.36, cy + radius * 0.18, cx + radius * 1.16, cy - Math.sin(spin) * radius * 0.08)
            ctx.stroke()
        }

        function drawHolographicIris(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var speaking = aiState === "speaking" ? level : 0.0
            var thinking = aiState === "thinking" ? 1.0 : 0.0
            var observing = root.observingActive() ? 1.0 : 0.0
            var scan = root.tick * (0.68 + speaking * 0.44 + thinking * 0.20)
            var blades = root.reducedEffects ? 10 : 16
            ctx.lineCap = "round"

            var shell = ctx.createRadialGradient(cx, cy, radius * 0.12, cx, cy, radius * 0.95)
            shell.addColorStop(0.0, "rgba(255,255,255," + (0.18 + speaking * 0.16) + ")")
            shell.addColorStop(0.34, root.rgba(primary, 0.25 + observing * 0.10))
            shell.addColorStop(0.68, root.rgba(secondary, 0.16 + speaking * 0.10))
            shell.addColorStop(1.0, root.rgba(root.hexColor("#020617"), 0.08))
            ctx.fillStyle = shell
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 0.82, 0, Math.PI * 2)
            ctx.fill()

            for (var i = 0; i < blades; i++) {
                var a0 = scan * 0.22 + (i / blades) * Math.PI * 2
                var a1 = a0 + Math.PI * 2 / blades * 0.62
                var pulse = 0.5 + Math.sin(root.tick * 1.7 + i * 0.9) * 0.5
                var inner = radius * (0.30 + pulse * 0.025)
                var outer = radius * (0.82 + pulse * 0.035 + speaking * 0.04)
                ctx.fillStyle = root.rgba(i % 3 === 0 ? accent : (i % 2 ? secondary : primary), 0.10 + pulse * 0.16 + speaking * 0.12)
                ctx.beginPath()
                ctx.moveTo(cx + Math.cos(a0) * inner, cy + Math.sin(a0) * inner)
                ctx.lineTo(cx + Math.cos(a0) * outer, cy + Math.sin(a0) * outer)
                ctx.lineTo(cx + Math.cos(a1) * outer, cy + Math.sin(a1) * outer)
                ctx.lineTo(cx + Math.cos(a1) * inner, cy + Math.sin(a1) * inner)
                ctx.closePath()
                ctx.fill()
            }

            ctx.strokeStyle = root.rgba(accent, 0.52 + speaking * 0.24)
            ctx.lineWidth = 1.5 + speaking * 1.8
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 0.94, scan, scan + Math.PI * (0.62 + observing * 0.24))
            ctx.stroke()

            ctx.fillStyle = root.rgba(root.hexColor("#020617"), 0.58)
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (0.24 + speaking * 0.025), 0, Math.PI * 2)
            ctx.fill()
            ctx.strokeStyle = root.rgba(primary, 0.44 + observing * 0.20)
            ctx.lineWidth = 1.0
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 0.34, 0, Math.PI * 2)
            ctx.stroke()
        }

        function drawSynapticBloom(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var speaking = aiState === "speaking" ? level : 0.0
            var thinking = aiState === "thinking" ? 1.0 : 0.0
            var observing = root.observingActive() ? 1.0 : 0.0
            var nodes = root.reducedEffects ? 7 : 11
            var spin = root.tick * (0.22 + thinking * 0.24 + speaking * 0.34)
            ctx.lineCap = "round"

            var bloom = ctx.createRadialGradient(cx - radius * 0.16, cy - radius * 0.22, radius * 0.06, cx, cy, radius * 0.84)
            bloom.addColorStop(0.0, "rgba(255,255,255," + (0.30 + speaking * 0.18) + ")")
            bloom.addColorStop(0.30, root.rgba(primary, 0.44 + speaking * 0.14))
            bloom.addColorStop(0.72, root.rgba(secondary, 0.18 + thinking * 0.10))
            bloom.addColorStop(1.0, root.rgba(accent, 0.06 + observing * 0.08))
            ctx.fillStyle = bloom
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (0.58 + speaking * 0.07), 0, Math.PI * 2)
            ctx.fill()

            for (var i = 0; i < nodes; i++) {
                var angle = spin + (i / nodes) * Math.PI * 2
                var pulse = 0.5 + Math.sin(root.tick * 1.8 + i * 1.33) * 0.5
                var dist = radius * (0.82 + (i % 3) * 0.10 + pulse * 0.06)
                var x = cx + Math.cos(angle) * dist
                var y = cy + Math.sin(angle) * dist * 0.88
                ctx.strokeStyle = root.rgba(i % 2 ? secondary : primary, 0.12 + pulse * 0.20 + speaking * 0.18)
                ctx.lineWidth = 0.9 + pulse * 1.1 + speaking * 1.2
                ctx.beginPath()
                ctx.moveTo(cx + Math.cos(angle + 0.9) * radius * 0.28, cy + Math.sin(angle + 0.9) * radius * 0.20)
                ctx.bezierCurveTo(
                    cx + Math.cos(angle) * radius * 0.52,
                    cy + Math.sin(angle) * radius * 0.34,
                    cx + Math.cos(angle - 0.55) * radius * 0.72,
                    cy + Math.sin(angle - 0.55) * radius * 0.62,
                    x,
                    y
                )
                ctx.stroke()

                ctx.fillStyle = root.rgba(i % 3 === 0 ? accent : primary, 0.26 + pulse * 0.38 + speaking * 0.16)
                ctx.beginPath()
                ctx.arc(x, y, 1.7 + pulse * 2.1 + speaking * 1.4, 0, Math.PI * 2)
                ctx.fill()
            }

            ctx.strokeStyle = root.rgba(accent, 0.28 + observing * 0.18)
            ctx.lineWidth = 1.1 + speaking
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 0.72, spin * -0.8, spin * -0.8 + Math.PI * 1.48)
            ctx.stroke()
        }

        function drawLiquidCore(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var speaking = aiState === "speaking" ? level : 0.0
            var thinking = aiState === "thinking" ? 1.0 : 0.0
            var observing = root.observingActive() ? 1.0 : 0.0
            var wobble = 0.5 + Math.sin(root.tick * (0.74 + thinking * 0.20)) * 0.5
            ctx.lineCap = "round"

            var fill = ctx.createRadialGradient(cx - radius * 0.28, cy - radius * 0.34, radius * 0.04, cx, cy, radius * 0.92)
            fill.addColorStop(0.0, "rgba(255,255,255," + (0.38 + speaking * 0.20) + ")")
            fill.addColorStop(0.26, root.rgba(primary, 0.54 + speaking * 0.14))
            fill.addColorStop(0.62, root.rgba(secondary, 0.32 + observing * 0.12))
            fill.addColorStop(1.0, root.rgba(accent, 0.10 + thinking * 0.08))
            ctx.fillStyle = fill

            var r0 = radius * (0.72 + speaking * 0.06)
            var k = r0 * 0.62
            ctx.beginPath()
            ctx.moveTo(cx, cy - r0 * (0.96 + wobble * 0.06))
            ctx.bezierCurveTo(cx + k * (0.96 + wobble * 0.10), cy - k * 0.90, cx + r0 * (1.04 + speaking * 0.05), cy - k * 0.12, cx + r0 * (0.88 + wobble * 0.08), cy)
            ctx.bezierCurveTo(cx + k * 0.82, cy + k * (0.92 + wobble * 0.10), cx + k * 0.12, cy + r0 * (1.02 + speaking * 0.06), cx, cy + r0 * 0.88)
            ctx.bezierCurveTo(cx - k * (0.96 + wobble * 0.08), cy + k * 0.92, cx - r0 * (0.98 + speaking * 0.04), cy + k * 0.10, cx - r0 * 0.86, cy)
            ctx.bezierCurveTo(cx - k * 0.86, cy - k * 0.88, cx - k * 0.12, cy - r0 * (1.04 + wobble * 0.06), cx, cy - r0 * (0.96 + wobble * 0.06))
            ctx.fill()

            for (var i = 0; i < 5; i++) {
                var phase = root.tick * (0.45 + i * 0.06) + i * 1.18
                ctx.strokeStyle = root.rgba(i % 2 ? accent : secondary, 0.16 + root.smokeIntensity * 0.18 + speaking * 0.18)
                ctx.lineWidth = 1.0 + i * 0.35 + speaking * 1.3
                ctx.beginPath()
                ctx.moveTo(cx - radius * 0.48, cy + Math.sin(phase) * radius * 0.32)
                ctx.bezierCurveTo(
                    cx - radius * 0.18,
                    cy - radius * (0.30 + Math.cos(phase) * 0.12),
                    cx + radius * 0.20,
                    cy + radius * (0.26 + Math.sin(phase * 0.8) * 0.12),
                    cx + radius * 0.50,
                    cy + Math.cos(phase) * radius * 0.30
                )
                ctx.stroke()
            }

            ctx.strokeStyle = root.rgba(root.hexColor("#ffffff"), 0.12 + speaking * 0.10)
            ctx.lineWidth = 1.0
            ctx.beginPath()
            ctx.arc(cx - radius * 0.10, cy - radius * 0.12, radius * 0.58, Math.PI * 0.82, Math.PI * 1.46)
            ctx.stroke()
        }

        function drawVoidPrism(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var speaking = aiState === "speaking" ? level : 0.0
            var thinking = aiState === "thinking" ? 1.0 : 0.0
            var observing = root.observingActive() ? 1.0 : 0.0
            var spin = root.tick * (0.18 + thinking * 0.16 + speaking * 0.24)
            var points = []
            var facets = 7
            for (var i = 0; i < facets; i++) {
                var angle = spin + (i / facets) * Math.PI * 2
                var stretch = 0.88 + ((i * 37) % 11) / 80.0 + speaking * 0.04
                points.push({
                    "x": cx + Math.cos(angle) * radius * stretch,
                    "y": cy + Math.sin(angle) * radius * stretch * 0.92
                })
            }

            var prism = ctx.createRadialGradient(cx - radius * 0.18, cy - radius * 0.24, radius * 0.08, cx, cy, radius * 0.98)
            prism.addColorStop(0.0, "rgba(255,255,255," + (0.26 + speaking * 0.20) + ")")
            prism.addColorStop(0.32, root.rgba(primary, 0.36 + speaking * 0.12))
            prism.addColorStop(0.70, root.rgba(secondary, 0.20 + observing * 0.10))
            prism.addColorStop(1.0, root.rgba(root.hexColor("#020617"), 0.20))
            ctx.fillStyle = prism
            ctx.beginPath()
            ctx.moveTo(points[0].x, points[0].y)
            for (var p = 1; p < points.length; p++) {
                ctx.lineTo(points[p].x, points[p].y)
            }
            ctx.closePath()
            ctx.fill()

            for (var f = 0; f < points.length; f++) {
                var next = points[(f + 1) % points.length]
                ctx.fillStyle = root.rgba(f % 3 === 0 ? accent : (f % 2 ? secondary : primary), 0.06 + ((f % 4) * 0.025) + speaking * 0.05)
                ctx.beginPath()
                ctx.moveTo(cx, cy)
                ctx.lineTo(points[f].x, points[f].y)
                ctx.lineTo(next.x, next.y)
                ctx.closePath()
                ctx.fill()

                ctx.strokeStyle = root.rgba(f % 2 ? accent : primary, 0.22 + speaking * 0.22 + observing * 0.08)
                ctx.lineWidth = 0.9 + speaking * 1.4
                ctx.beginPath()
                ctx.moveTo(cx, cy)
                ctx.lineTo(points[f].x, points[f].y)
                ctx.stroke()
            }

            ctx.strokeStyle = root.rgba(accent, 0.42 + speaking * 0.26)
            ctx.lineWidth = 1.4 + speaking * 1.8
            ctx.beginPath()
            ctx.moveTo(points[0].x, points[0].y)
            for (var q = 1; q < points.length; q++) {
                ctx.lineTo(points[q].x, points[q].y)
            }
            ctx.closePath()
            ctx.stroke()

            ctx.fillStyle = root.rgba(root.hexColor("#020617"), 0.34)
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (0.22 + speaking * 0.025), 0, Math.PI * 2)
            ctx.fill()
        }

        function drawParticles(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var count = Math.max(0, Math.min(120, root.particleDensity))
            var mode = root.activeStateAnimation()
            var speed = root.stateOrbitSpeed(mode)
            var sparkleBoost = mode === "energetic_sparkle" ? Math.abs(Math.sin(root.tick * 5.2)) : 0.0
            for (var i = 0; i < count; i++) {
                var lane = i % 5
                var angle = (i / Math.max(1, count)) * Math.PI * 2 + root.tick * (0.08 + lane * 0.018) * speed
                var drift = Math.sin(root.tick * (0.7 + speed * 0.08) + i * 2.1) * radius * (0.06 + root.trailLength * 0.18 + sparkleBoost * 0.05)
                var dist = radius * (0.92 + lane * (0.10 + root.trailLength * 0.10)) + drift
                var x = cx + Math.cos(angle) * dist
                var y = cy + Math.sin(angle) * dist * 0.82
                ctx.fillStyle = root.rgba(i % 3 === 0 ? accent : (i % 2 ? secondary : primary), 0.16 + root.trailLength * 0.18 + level * 0.32 + sparkleBoost * 0.16)
                ctx.beginPath()
                ctx.arc(x, y, 1.0 + root.trailLength * 0.9 + level * 2.0 + lane * 0.18 + sparkleBoost * 1.8, 0, Math.PI * 2)
                ctx.fill()
            }
        }

        function drawFallingParticles(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var count = Math.max(0, Math.min(80, root.fallingParticleDensity))
            var span = radius * (1.15 + root.trailLength * 0.95)
            var startY = cy + radius * 0.42
            var lifetime = Math.max(0.8, Math.min(8.0, root.fallingParticleLifetime))
            for (var i = 0; i < count; i++) {
                var seed = (i * 37) % 101
                var lane = (seed / 100.0 - 0.5) * radius * 0.92
                var drift = Math.sin(root.tick * (0.35 + (i % 5) * 0.03) + i * 1.7) * radius * 0.10
                var progress = ((root.tick / lifetime) + seed * 0.057 + i * 0.13 + level * 0.08) % 1.0
                var x = cx + lane + drift
                var y = startY + progress * span
                var fade = Math.sin(progress * Math.PI)
                var alpha = (0.18 + level * 0.22) * fade
                var length = 5 + fade * (10 + root.trailLength * 8) + level * 6
                ctx.strokeStyle = root.rgba(i % 2 ? secondary : accent, alpha)
                ctx.lineWidth = 1.1 + level * 0.9
                ctx.beginPath()
                ctx.moveTo(x, y)
                ctx.lineTo(x + Math.sin(root.tick + i) * 1.8, y + length)
                ctx.stroke()
                ctx.fillStyle = root.rgba(i % 3 === 0 ? primary : accent, alpha * 1.4)
                ctx.beginPath()
                ctx.arc(x, y + length, 1.0 + level * 1.2, 0, Math.PI * 2)
                ctx.fill()
            }
        }

        function drawPlasma(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var gradient = ctx.createRadialGradient(cx - radius * 0.18, cy - radius * 0.22, radius * 0.08, cx, cy, radius * 1.08)
            gradient.addColorStop(0.0, root.rgba(accent, 0.95))
            gradient.addColorStop(0.48, root.rgba(primary, 0.62 + level * 0.18))
            gradient.addColorStop(1.0, root.rgba(secondary, 0.16))
            ctx.fillStyle = gradient
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (1.0 + Math.sin(root.tick * 1.2) * 0.025), 0, Math.PI * 2)
            ctx.fill()
            ctx.strokeStyle = root.rgba(accent, 0.32 + level * 0.32)
            ctx.lineWidth = 2 + level * 3
            ctx.beginPath()
            ctx.arc(cx, cy, radius * (1.12 + level * 0.12), 0, Math.PI * 2)
            ctx.stroke()
        }

        function drawNeuralSpark(ctx, cx, cy, radius, primary, secondary, accent, level) {
            drawPlasma(ctx, cx, cy, radius * 0.78, primary, secondary, accent, level)
            ctx.strokeStyle = root.rgba(primary, 0.30 + level * 0.30)
            ctx.lineWidth = 1.15 + level * 1.55
            var points = []
            var count = root.reducedEffects ? 8 : Math.max(10, Math.min(28, Math.round(root.particleDensity * 0.45)))
            var maxCross = Math.min(25.0, radius * 0.36)
            for (var i = 0; i < count; i++) {
                var baseAngle = (i / count) * Math.PI * 2 + ((i * 17) % 11) * 0.035
                var wander = Math.sin(root.tick * (0.11 + (i % 7) * 0.011) + i * 1.91) * 0.36
                var angle = baseAngle + wander
                var baseDist = radius * (0.30 + ((i * 31) % 62) / 100.0)
                var distWander = Math.sin(root.tick * (0.13 + (i % 5) * 0.013) + i * 2.37) * radius * 0.20
                var dist = Math.max(radius * 0.18, Math.min(radius + maxCross, baseDist + distWander))
                points.push({x: cx + Math.cos(angle) * dist, y: cy + Math.sin(angle) * dist})
            }
            ctx.strokeStyle = root.rgba(primary, 0.24 + level * 0.22)
            ctx.lineWidth = 1.0
            ctx.beginPath()
            ctx.arc(cx, cy, radius + maxCross, 0, Math.PI * 2)
            ctx.stroke()
            for (var a = 0; a < points.length; a++) {
                for (var b = a + 1; b < points.length; b++) {
                    var dx = points[a].x - points[b].x
                    var dy = points[a].y - points[b].y
                    if (Math.sqrt(dx * dx + dy * dy) > radius * (0.52 + root.trailLength * 0.22)) {
                        continue
                    }
                    ctx.strokeStyle = root.rgba((a + b) % 3 === 0 ? accent : primary, 0.16 + level * 0.28 + root.trailLength * 0.12)
                    ctx.beginPath()
                    ctx.moveTo(points[a].x, points[a].y)
                    ctx.lineTo(points[b].x, points[b].y)
                    ctx.stroke()
                }
                ctx.fillStyle = root.rgba(a % 2 ? accent : secondary, 0.62 + level * 0.28)
                ctx.beginPath()
                ctx.arc(points[a].x, points[a].y, 2.2 + level * 2.6, 0, Math.PI * 2)
                ctx.fill()
            }
        }

    }

    Text {
        visible: showTargetLabel && targetActive && targetTitle.length > 0
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        width: parent.width - 16
        color: "#dff7ff"
        text: "Focus: " + targetTitle
        elide: Text.ElideRight
        horizontalAlignment: Text.AlignHCenter
        font.pixelSize: 11
    }
}
