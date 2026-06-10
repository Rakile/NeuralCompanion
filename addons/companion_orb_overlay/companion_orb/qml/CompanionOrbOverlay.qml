import QtQuick 2.15

Item {
    id: root
    anchors.fill: parent

    property var orbBridge: companionOrbBridge
    property string aiState: orbBridge ? orbBridge.aiState : "idle"
    property real audioLevel: orbBridge ? orbBridge.audioLevel : 0.0
    property string visualStyle: orbBridge ? orbBridge.visualStyle : "soft_plasma"
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
    property bool voiceSyncEnabled: orbBridge ? orbBridge.voiceSyncEnabled : true
    property real glowStrength: orbBridge ? orbBridge.glowStrength : 1.0
    property real trailLength: orbBridge ? orbBridge.trailLength : 0.55
    property int particleDensity: orbBridge ? orbBridge.particleDensity : 30
    property int fallingParticleDensity: orbBridge ? orbBridge.fallingParticleDensity : 18
    property real fallingParticleLifetime: orbBridge ? orbBridge.fallingParticleLifetime : 3.8
    property real smokeIntensity: orbBridge ? orbBridge.smokeIntensity : 0.35
    property real moodColorIntensity: orbBridge ? orbBridge.moodColorIntensity : 0.85
    property color primaryColor: orbBridge ? orbBridge.primaryColor : "#38bdf8"
    property color secondaryColor: orbBridge ? orbBridge.secondaryColor : "#22d3ee"
    property color accentColor: orbBridge ? orbBridge.accentColor : "#a78bfa"
    property color glowColor: orbBridge ? orbBridge.glowColor : "#67e8f9"
    property real tick: 0.0

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
        if (visualStyle === "neural_spark") return root.hexColor("#38bdf8")
        if (visualStyle === "smoke_wisp") return root.hexColor("#94a3b8")
        if (visualStyle === "hologram_drone") return root.hexColor("#67e8f9")
        if (visualStyle === "mood_orb") return root.hexColor("#a78bfa")
        return root.hexColor("#22d3ee")
    }

    function styleSecondary() {
        if (visualStyle === "neural_spark") return root.hexColor("#22d3ee")
        if (visualStyle === "smoke_wisp") return root.hexColor("#64748b")
        if (visualStyle === "hologram_drone") return root.hexColor("#22d3ee")
        if (visualStyle === "mood_orb") return root.hexColor("#f472b6")
        return root.hexColor("#38bdf8")
    }

    function styleAccent() {
        if (visualStyle === "neural_spark") return root.hexColor("#f59e0b")
        if (visualStyle === "smoke_wisp") return root.hexColor("#c4b5fd")
        if (visualStyle === "hologram_drone") return root.hexColor("#a78bfa")
        if (visualStyle === "mood_orb") return root.hexColor("#f0abfc")
        return root.hexColor("#a78bfa")
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

    Timer {
        id: animationTimer
        interval: reducedEffects ? 50 : 33
        repeat: true
        running: true
        onTriggered: {
            tick += interval / 1000.0
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
            var size = Math.max(20, root.orbSize)
            var radius = size * (0.38 + level * 0.08)
            var outer = radius * (1.55 + root.glowStrength * 0.45 + level * 0.35)
            var primary = root.blendColor(root.stylePrimary(), root.primaryColor, root.moodColorIntensity)
            var secondary = root.blendColor(root.styleSecondary(), root.secondaryColor, root.moodColorIntensity)
            var accent = root.blendColor(root.styleAccent(), root.accentColor, root.moodColorIntensity)
            var glow = root.blendColor(primary, root.glowColor, Math.max(0.25, root.moodColorIntensity))

            ctx.globalAlpha = root.orbOpacity
            if (root.shadersEnabled) {
                var glowGradient = ctx.createRadialGradient(cx, cy, radius * 0.15, cx, cy, outer)
                glowGradient.addColorStop(0.0, root.rgba(glow, 0.32 + level * 0.22))
                glowGradient.addColorStop(0.42, root.rgba(primary, 0.16 + level * 0.12))
                glowGradient.addColorStop(1.0, "rgba(0,0,0,0)")
                ctx.fillStyle = glowGradient
                ctx.beginPath()
                ctx.arc(cx, cy, outer, 0, Math.PI * 2)
                ctx.fill()
            }

            if (root.particlesEnabled && !root.reducedEffects) {
                drawParticles(ctx, cx, cy, radius, primary, secondary, accent, level)
            }

            if (root.visualStyle === "neural_spark") {
                drawNeuralSpark(ctx, cx, cy, radius, primary, secondary, accent, level)
            } else if (root.visualStyle === "smoke_wisp") {
                drawSmokeWisp(ctx, cx, cy, radius, primary, secondary, accent, level)
            } else if (root.visualStyle === "hologram_drone") {
                drawHologram(ctx, cx, cy, radius, primary, secondary, accent, level)
            } else if (root.visualStyle === "mood_orb") {
                drawMoodOrb(ctx, cx, cy, radius, primary, secondary, accent, level)
            } else {
                drawPlasma(ctx, cx, cy, radius, primary, secondary, accent, level)
            }

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

        function drawParticles(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var count = Math.max(0, Math.min(120, root.particleDensity))
            for (var i = 0; i < count; i++) {
                var lane = i % 5
                var angle = (i / Math.max(1, count)) * Math.PI * 2 + root.tick * (0.08 + lane * 0.018)
                var drift = Math.sin(root.tick * 0.7 + i * 2.1) * radius * (0.06 + root.trailLength * 0.18)
                var dist = radius * (0.92 + lane * (0.10 + root.trailLength * 0.10)) + drift
                var x = cx + Math.cos(angle) * dist
                var y = cy + Math.sin(angle) * dist * 0.82
                ctx.fillStyle = root.rgba(i % 3 === 0 ? accent : (i % 2 ? secondary : primary), 0.16 + root.trailLength * 0.18 + level * 0.32)
                ctx.beginPath()
                ctx.arc(x, y, 1.0 + root.trailLength * 0.9 + level * 2.0 + lane * 0.18, 0, Math.PI * 2)
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

        function drawSmokeWisp(ctx, cx, cy, radius, primary, secondary, accent, level) {
            var wisps = root.reducedEffects ? 3 : 7
            for (var i = 0; i < wisps; i++) {
                var phase = root.tick * (0.35 + i * 0.03) + i
                ctx.strokeStyle = root.rgba(i % 2 ? secondary : accent, 0.12 + root.smokeIntensity * 0.24 + level * 0.12)
                ctx.lineWidth = 6 + i * 1.4 + level * 5
                ctx.beginPath()
                ctx.arc(cx + Math.sin(phase) * radius * 0.2, cy + Math.cos(phase * 0.9) * radius * 0.14, radius * (0.78 + i * 0.09), phase, phase + Math.PI * 1.2)
                ctx.stroke()
            }
            drawPlasma(ctx, cx, cy, radius * 0.86, primary, secondary, accent, level)
        }

        function drawHologram(ctx, cx, cy, radius, primary, secondary, accent, level) {
            ctx.strokeStyle = root.rgba(primary, 0.35 + level * 0.26)
            ctx.lineWidth = 2
            ctx.beginPath()
            ctx.ellipse(cx, cy, radius * 1.18, radius * 0.58, 0, 0, Math.PI * 2)
            ctx.stroke()
            ctx.beginPath()
            ctx.ellipse(cx, cy, radius * 0.58, radius * 1.18, 0, 0, Math.PI * 2)
            ctx.stroke()
            ctx.strokeStyle = root.rgba(accent, 0.42 + level * 0.34)
            ctx.beginPath()
            ctx.moveTo(cx - radius * 0.85, cy)
            ctx.lineTo(cx + radius * 0.85, cy)
            ctx.moveTo(cx, cy - radius * 0.85)
            ctx.lineTo(cx, cy + radius * 0.85)
            ctx.stroke()
            drawPlasma(ctx, cx, cy, radius * 0.58, primary, secondary, accent, level)
        }

        function drawMoodOrb(ctx, cx, cy, radius, primary, secondary, accent, level) {
            for (var i = 4; i >= 1; i--) {
                ctx.strokeStyle = root.rgba(i % 2 ? primary : accent, 0.12 + level * 0.16)
                ctx.lineWidth = 1.4
                ctx.beginPath()
                ctx.arc(cx, cy, radius * (0.65 + i * 0.22 + Math.sin(root.tick * 0.5 + i) * 0.02), 0, Math.PI * 2)
                ctx.stroke()
            }
            drawPlasma(ctx, cx, cy, radius * 0.82, primary, secondary, accent, level)
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
