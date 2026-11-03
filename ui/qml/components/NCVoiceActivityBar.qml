pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "../theme" as Theme

Rectangle {
    id: root

    property string styleMode: "ribbon"
    property string voiceState: "stopped"
    property string stateLabel: qsTr("Runtime stopped")
    property string moodName: "neutral"
    property string primaryColor: "#38bdf8"
    property string secondaryColor: "#22d3ee"
    property string accentColor: "#a78bfa"
    property real audioLevel: 0.0
    property real displayedLevel: Math.max(0.0, Math.min(audioLevel, 1.0))
    property real edgeFadeWidth: 50
    property real phase: 0.0
    property double lastFrameTime: 0

    implicitHeight: 52
    radius: Theme.NCMetrics.radiusMedium
    color: Theme.NCTheme.window
    border.color: voiceState === "failure" ? Theme.NCTheme.error : Theme.NCTheme.borderSubtle
    clip: true
    Accessible.name: qsTr("Voice activity: %1, mood %2").arg(stateLabel).arg(moodName)

    Behavior on displayedLevel {
        NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
    }

    function activeColors() {
        if (voiceState === "failure")
            return ["#ff324b", "#ff6675", "#8e1730"]
        if (voiceState === "recording")
            return ["#ff4054", "#ff7582", "#a51d35"]
        if (voiceState === "thinking")
            return [Theme.NCTheme.accent.toString(), "#785cff", "#d34dff"]
        return [primaryColor, secondaryColor, accentColor]
    }

    function signalAt(position, variant) {
        if (voiceState === "stopped")
            return 0.025
        if (voiceState === "failure")
            return Math.floor(position * 20) % 3 === 0 ? 0.58 : 0.10
        if (voiceState === "ready")
            return 0.07 + Math.sin(phase * 1.3 + position * 5.0) * 0.018
        if (voiceState === "thinking")
            return 0.12 + 0.10 * (0.5 + 0.5 * Math.sin(phase * 2.4 - position * 9.0))

        const floor = voiceState === "recording" ? 0.09 : 0.055
        const level = Math.max(displayedLevel, floor)
        const syllable = 0.58 + 0.42 * Math.sin(phase * 5.2 + Math.sin(phase * 1.6) * 1.7)
        const harmonics = 0.38 * Math.sin(position * 19.0 + phase * 7.8)
                        + 0.23 * Math.sin(position * 41.0 - phase * 4.4)
                        + 0.14 * Math.sin(position * 71.0 + phase * 10.1 + variant)
        return Math.max(floor, (0.50 + harmonics) * syllable * level)
    }

    function horizontalGradient(context, widthValue, colors) {
        const gradient = context.createLinearGradient(0, 0, widthValue, 0)
        gradient.addColorStop(0.0, colors[0])
        gradient.addColorStop(0.5, colors[1])
        gradient.addColorStop(1.0, colors[2])
        return gradient
    }

    function drawRibbon(context, widthValue, heightValue, colors) {
        const middle = heightValue * 0.5
        const maximum = heightValue * 0.34
        const count = Math.max(36, Math.min(120, Math.floor(widthValue / 14)))
        const amplitudes = []
        context.beginPath()
        for (let index = 0; index <= count; ++index) {
            const position = index / count
            const amplitude = signalAt(position, 0) * maximum
            amplitudes.push(amplitude)
            const x = position * widthValue
            const y = middle - amplitude * (0.72 + 0.28 * Math.sin(position * Math.PI))
            if (index === 0)
                context.moveTo(x, y)
            else
                context.lineTo(x, y)
        }
        for (let index = count; index >= 0; --index) {
            const position = index / count
            const amplitude = amplitudes[index]
            context.lineTo(position * widthValue, middle + amplitude * 0.72)
        }
        context.closePath()
        context.globalAlpha = voiceState === "speaking" ? 0.16 : 0.08
        context.fillStyle = colors[1]
        context.fill()
        context.globalAlpha = 1.0
        context.fillStyle = horizontalGradient(context, widthValue, colors)
        context.fill()
        context.globalAlpha = voiceState === "speaking" ? 0.10 : 0.05
        context.fillStyle = horizontalGradient(context, widthValue, colors)
        context.fillRect(0, middle - 5, widthValue, 10)
        context.globalAlpha = 0.46
        context.fillStyle = horizontalGradient(context, widthValue, [colors[2], colors[1], colors[0]])
        context.fillRect(0, middle - 1, widthValue, 2)
        context.globalAlpha = 1.0
    }

    function drawSpectrum(context, widthValue, heightValue, colors) {
        const count = Math.max(28, Math.min(72, Math.floor(widthValue / 15)))
        const gap = Math.max(2, widthValue * 0.003)
        const cellWidth = (widthValue - gap * (count - 1)) / count
        const gradient = horizontalGradient(context, widthValue, colors)
        for (let index = 0; index < count; ++index) {
            const position = index / Math.max(1, count - 1)
            const amplitude = Math.max(0.07, signalAt(position, index * 0.09))
            const barHeight = Math.max(3, amplitude * heightValue * 0.74)
            const x = index * (cellWidth + gap)
            const y = heightValue * 0.5 - barHeight / 2
            context.fillStyle = gradient
            context.fillRect(x, y, cellWidth, barHeight)
        }
    }

    function drawKinetic(context, widthValue, heightValue, colors) {
        const middle = heightValue * 0.5
        const lineBase = voiceState === "speaking" || voiceState === "recording"
                       ? 5 + displayedLevel * 8 : 3
        for (let layer = 0; layer < 3; ++layer) {
            context.beginPath()
            const step = Math.max(6, widthValue / 120)
            for (let x = 0; x <= widthValue; x += step) {
                const position = x / widthValue
                const energy = signalAt(position, layer)
                const drift = Math.sin(position * (7 + layer * 2) + phase * (1.9 + layer * 0.4))
                            * energy * heightValue * 0.25
                const y = middle + drift + (layer - 1) * 3
                if (x === 0)
                    context.moveTo(x, y)
                else
                    context.lineTo(x, y)
            }
            context.strokeStyle = colors[layer]
            context.lineWidth = Math.max(4, lineBase - layer * 1.4 + 6)
            context.globalAlpha = 0.11
            context.stroke()
            context.lineWidth = Math.max(2, lineBase - layer * 1.4)
            context.globalAlpha = 0.84 - layer * 0.18
            context.stroke()
        }
        context.globalAlpha = 1.0
        const particleCount = voiceState === "speaking" ? 8 : voiceState === "thinking" ? 4 : 2
        for (let index = 0; index < particleCount; ++index) {
            const x = ((phase * (112 + index * 7) + index * widthValue / particleCount) % (widthValue + 20)) - 10
            const y = middle + Math.sin(index * 2.1 + phase * 2.0) * heightValue * 0.15
            context.fillStyle = colors[index % 3]
            context.beginPath()
            context.arc(x, y, 2 + index % 2, 0, Math.PI * 2)
            context.fill()
        }
    }

    Canvas {
        id: activityCanvas
        anchors.fill: parent
        renderStrategy: Canvas.Threaded

        onPaint: {
            const context = getContext("2d")
            context.reset()
            context.clearRect(0, 0, width, height)
            const colors = root.activeColors()
            if (root.styleMode === "spectrum")
                root.drawSpectrum(context, width, height, colors)
            else if (root.styleMode === "kinetic")
                root.drawKinetic(context, width, height, colors)
            else
                root.drawRibbon(context, width, height, colors)

            const fadePixels = Math.min(root.edgeFadeWidth, width / 2)
            if (fadePixels > 0 && width > 0) {
                const fadeStop = fadePixels / width
                const edgeMask = context.createLinearGradient(0, 0, width, 0)
                edgeMask.addColorStop(0.0, "rgba(255, 255, 255, 0)")
                edgeMask.addColorStop(fadeStop, "rgba(255, 255, 255, 1)")
                edgeMask.addColorStop(1.0 - fadeStop, "rgba(255, 255, 255, 1)")
                edgeMask.addColorStop(1.0, "rgba(255, 255, 255, 0)")
                context.globalCompositeOperation = "destination-in"
                context.globalAlpha = 1.0
                context.fillStyle = edgeMask
                context.fillRect(0, 0, width, height)
                context.globalCompositeOperation = "source-over"
            }
        }
    }

    Timer {
        interval: root.voiceState === "speaking" || root.voiceState === "recording" ? 33 : 66
        repeat: true
        running: root.visible && root.voiceState !== "stopped" && root.voiceState !== "failure"
        onRunningChanged: root.lastFrameTime = running ? Date.now() : 0
        onTriggered: {
            const now = Date.now()
            const elapsed = root.lastFrameTime > 0
                            ? Math.min(0.12, Math.max(0.0, (now - root.lastFrameTime) / 1000.0))
                            : interval / 1000.0
            root.lastFrameTime = now
            const phaseSpeed = root.styleMode === "kinetic" ? 2.55
                             : root.styleMode === "spectrum" ? 2.35 : 2.15
            root.phase += elapsed * phaseSpeed
            activityCanvas.requestPaint()
        }
    }

    onStyleModeChanged: activityCanvas.requestPaint()
    onVoiceStateChanged: activityCanvas.requestPaint()
    onDisplayedLevelChanged: activityCanvas.requestPaint()
    onPrimaryColorChanged: activityCanvas.requestPaint()
    onSecondaryColorChanged: activityCanvas.requestPaint()
    onAccentColorChanged: activityCanvas.requestPaint()
}
