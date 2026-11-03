import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Item {
    id: root
    objectName: "corsairKeyboardPreview"

    property var field: ({})
    readonly property var preview: field && field.value ? field.value : ({})
    readonly property int keyCount: keyboardCanvas.keyCount
    readonly property int rowCount: keyboardCanvas.rows.length
    readonly property real spaceWidthUnits: Number(keyboardCanvas.rows[4][3][1])
    readonly property real backslashWidthUnits: Number(keyboardCanvas.rows[1][13][1])
    property real phase: 0.0

    implicitWidth: 620
    implicitHeight: 310

    function numberValue(name, fallback) {
        const value = Number(preview[name])
        return isFinite(value) ? value : fallback
    }

    function clamp(value, minimum, maximum) {
        return Math.max(minimum, Math.min(maximum, value))
    }

    function colorParts() {
        const source = String(preview.color || "#FF9123")
        const match = /^#?([0-9a-f]{6})$/i.exec(source)
        const packed = parseInt(match ? match[1] : "FF9123", 16)
        return [(packed >> 16) & 255, (packed >> 8) & 255, packed & 255]
    }

    function rgba(parts, alpha, gain) {
        const level = clamp(gain === undefined ? 1.0 : gain, 0.0, 1.8)
        return "rgba(" + Math.round(clamp(parts[0] * level, 0, 255)) + ","
                + Math.round(clamp(parts[1] * level, 0, 255)) + ","
                + Math.round(clamp(parts[2] * level, 0, 255)) + ","
                + clamp(alpha, 0.0, 1.0) + ")"
    }

    function energyFor(x, y, rowIndex, columnIndex) {
        const effect = String(preview.effect || "classic_idle")
        const speed = clamp(numberValue("speed", 1.0), 0.0, 3.0)
        const intensity = clamp(numberValue("intensity", 1.0), 0.0, 2.0)
        const size = clamp(numberValue("size", 1.0), 0.2, 2.0)
        const trail = clamp(numberValue("trail", 0.5), 0.0, 1.0)
        const detail = clamp(numberValue("detail", 0.5), 0.0, 1.0)
        const audio = clamp(numberValue("level", 0.68)
                            * numberValue("audio_reactivity", 1.0), 0.0, 1.5)
        const t = phase * speed
        const dx = x - 0.5
        const dy = y - 0.5
        const distance = Math.sqrt(dx * dx + dy * dy)
        let energy = 0.25

        if (effect === "equalizer" || effect === "audio_columns") {
            const columnWave = 0.5 + 0.5 * Math.sin(
                columnIndex * (0.75 + detail * 2.2) + t * 2.4)
            const height = clamp(0.12 + audio * (0.55 + columnWave * 0.28), 0.08, 1.0)
            energy = (1.0 - y) <= height
                     ? 0.55 + columnWave * 0.45
                     : 0.03 + trail * 0.15
        } else if (effect === "living_wave") {
            const frequency = 5.0 + detail * 9.0
            const wave = 0.5 + 0.5 * Math.sin(
                (x * frequency + y * (2.0 + detail * 4.0)) / size - t * 2.2)
            energy = 0.08 + trail * 0.18 + wave * (0.92 - trail * 0.12)
        } else if (effect === "center_ripple" || effect === "center_shockwave") {
            const ripple = 0.5 + 0.5 * Math.sin(
                distance * (11.0 + detail * 26.0) / size - t * 4.0)
            energy = 0.05 + Math.pow(ripple, 2.4 - trail * 1.5) * 0.95
        } else if (effect === "dual_comet") {
            const left = Math.abs(x - ((t * 0.18) % 1.25))
            const right = Math.abs(x - (1.0 - ((t * 0.18) % 1.25)))
            const cometWidth = 0.035 + size * 0.055 + trail * 0.13
            const verticalTexture = 0.82 + 0.18 * Math.sin(y * (4.0 + detail * 12.0))
            energy = clamp(1.0 - Math.min(left, right) / cometWidth, 0.04, 1.0)
                     * verticalTexture
        } else if (effect === "plasma_field") {
            const frequency = 6.0 + detail * 12.0
            energy = 0.08 + trail * 0.16
                     + (0.92 - trail * 0.08)
                       * (0.5 + 0.5 * Math.sin(x * frequency + t)
                          * Math.cos(y * (frequency * 0.64) - t * 1.4))
        } else if (effect === "classic_thinking") {
            const scanner = Math.abs(x - ((t * 0.22) % 1.2))
            energy = clamp(1.0 - scanner / (0.06 + trail * 0.22), 0.05, 1.0)
                     * (0.88 + 0.12 * Math.sin(y * (4.0 + detail * 10.0)))
        } else if (effect === "classic_listening") {
            energy = 0.16 + trail * 0.16
                     + (0.84 - trail * 0.08)
                       * (0.5 + 0.5 * Math.sin(
                           t * 2.8 - distance * (6.0 + detail * 9.0)))
        } else if (effect === "twin_voicefront") {
            const spread = (t * 0.13) % 0.65
            energy = clamp(
                1.0 - Math.abs(Math.abs(dx) - spread)
                      / (0.055 + trail * 0.16), 0.05, 1.0)
                     * (0.9 + 0.1 * Math.sin(y * (5.0 + detail * 10.0)))
        } else if (effect === "voice_bloom") {
            energy = clamp(1.15 - distance * ((2.3 - trail * 0.9) / size)
                           + audio * 0.35
                           + 0.08 * Math.sin(distance * (8.0 + detail * 18.0))
                           + 0.15 * Math.sin(t * 3.0), 0.1, 1.0)
        } else {
            energy = 0.22 + trail * 0.18
                     + 0.6 * (0.5 + 0.5 * Math.sin(
                         t * 1.7 + x * (1.5 + detail * 3.0)))
        }
        return intensity <= 0.0 ? 0.0 : clamp(energy * intensity, 0.0, 1.0)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.NCMetrics.space8

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space8

            Label {
                text: String(root.preview.state || "speaking").toUpperCase()
                color: Theme.NCTheme.text
                font.pixelSize: Theme.NCTypography.labelSize
                font.weight: Theme.NCTypography.medium
            }

            Rectangle {
                Layout.preferredWidth: 7
                Layout.preferredHeight: 7
                implicitWidth: 7
                implicitHeight: 7
                radius: 3.5
                color: String(root.preview.color || Theme.NCTheme.accent)
            }

            Label {
                Layout.fillWidth: true
                text: String(root.preview.effect || "classic_idle").replace(/_/g, " ")
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                horizontalAlignment: Text.AlignRight
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.window
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.border

            Canvas {
                id: keyboardCanvas
                objectName: "corsairKeyboardCanvas"
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space8
                antialiasing: true

                property var rows: [
                    [["Esc", 1], ["1", 1], ["2", 1], ["3", 1], ["4", 1], ["5", 1], ["6", 1], ["7", 1], ["8", 1], ["9", 1], ["0", 1], ["-", 1], ["=", 1], ["Back", 2]],
                    [["Tab", 1.5], ["Q", 1], ["W", 1], ["E", 1], ["R", 1], ["T", 1], ["Y", 1], ["U", 1], ["I", 1], ["O", 1], ["P", 1], ["[", 1], ["]", 1], ["\\", 1.5]],
                    [["Caps", 1.75], ["A", 1], ["S", 1], ["D", 1], ["F", 1], ["G", 1], ["H", 1], ["J", 1], ["K", 1], ["L", 1], [";", 1], ["'", 1], ["Enter", 2.25]],
                    [["Shift", 2.25], ["Z", 1], ["X", 1], ["C", 1], ["V", 1], ["B", 1], ["N", 1], ["M", 1], [",", 1], [".", 1], ["/", 1], ["Shift", 2.75]],
                    [["Ctrl", 1.25], ["Win", 1.25], ["Alt", 1.25], ["Space", 6.25], ["Alt", 1.25], ["Fn", 1.25], ["Menu", 1.25], ["Ctrl", 1.25]]
                ]
                readonly property int keyCount: {
                    let count = 0
                    for (let row = 0; row < rows.length; ++row)
                        count += rows[row].length
                    return count
                }

                function roundedRect(context, x, y, widthValue, heightValue, radiusValue) {
                    const radius = Math.min(radiusValue, widthValue / 2, heightValue / 2)
                    context.beginPath()
                    context.moveTo(x + radius, y)
                    context.lineTo(x + widthValue - radius, y)
                    context.quadraticCurveTo(x + widthValue, y, x + widthValue, y + radius)
                    context.lineTo(x + widthValue, y + heightValue - radius)
                    context.quadraticCurveTo(x + widthValue, y + heightValue, x + widthValue - radius, y + heightValue)
                    context.lineTo(x + radius, y + heightValue)
                    context.quadraticCurveTo(x, y + heightValue, x, y + heightValue - radius)
                    context.lineTo(x, y + radius)
                    context.quadraticCurveTo(x, y, x + radius, y)
                    context.closePath()
                }

                onPaint: {
                    const context = getContext("2d")
                    context.reset()
                    const colors = root.colorParts()
                    const brightness = root.clamp(root.numberValue("brightness", 0.75), 0.0, 1.0)
                    const gap = Math.max(2.0, width * 0.004)
                    const top = 4
                    const stripHeight = Math.max(18, height * 0.10)
                    const keyboardHeight = height - stripHeight - gap * 5 - 8
                    const keyHeight = keyboardHeight / 5.0
                    const unit = (width - gap * 14) / 15.0
                    const drawingHeight = keyboardHeight + gap * 4

                    for (let row = 0; row < rows.length; ++row) {
                        let x = 0
                        const y = top + row * (keyHeight + gap)
                        for (let column = 0; column < rows[row].length; ++column) {
                            const item = rows[row][column]
                            const keyWidth = item[1] * unit + (item[1] - 1) * gap
                            const centerX = (x + keyWidth / 2) / width
                            const centerY = (y - top + keyHeight / 2) / drawingHeight
                            const energy = root.energyFor(centerX, centerY, row, column)
                            roundedRect(context, x, y, keyWidth, keyHeight, Math.min(6, keyHeight * 0.18))
                            context.fillStyle = root.rgba(
                                colors, 0.12 + energy * 0.7,
                                brightness * energy * 1.25)
                            context.fill()
                            context.strokeStyle = root.rgba(
                                colors, 0.18 + energy * 0.65,
                                brightness * energy * 1.45)
                            context.lineWidth = 1
                            context.stroke()
                            context.fillStyle = energy > 0.58 ? "#FFFFFF" : "#B9C1D0"
                            context.font = Math.max(7, Math.min(11, keyHeight * 0.25)) + "px sans-serif"
                            context.textAlign = "center"
                            context.textBaseline = "middle"
                            context.fillText(item[0], x + keyWidth / 2, y + keyHeight / 2)
                            x += keyWidth + gap
                        }
                    }

                    const stripY = height - stripHeight
                    const zoneGap = gap * 1.5
                    const zoneWidth = (width - zoneGap * 2) / 3.0
                    for (let zone = 0; zone < 3; ++zone) {
                        const zoneEnergy = root.preview.k55_mode === "unified"
                                           ? 0.72
                                           : root.energyFor((zone + 0.5) / 3.0, 0.5, 0, zone)
                        roundedRect(context, zone * (zoneWidth + zoneGap), stripY,
                                    zoneWidth, stripHeight, 5)
                        context.fillStyle = root.rgba(
                            colors, 0.12 + zoneEnergy * 0.72,
                            brightness * zoneEnergy * 1.25)
                        context.fill()
                        context.strokeStyle = root.rgba(
                            colors, 0.2 + zoneEnergy * 0.45,
                            brightness * zoneEnergy * 1.35)
                        context.stroke()
                    }
                }
            }
        }
    }

    Timer {
        interval: 33
        repeat: true
        running: root.visible
                 && root.numberValue("speed", 1.0) > 0.0
                 && root.numberValue("brightness", 0.75) > 0.0
                 && root.numberValue("intensity", 1.0) > 0.0
        onTriggered: {
            root.phase += 0.033
            keyboardCanvas.requestPaint()
        }
    }

    onPreviewChanged: keyboardCanvas.requestPaint()
    onPhaseChanged: keyboardCanvas.requestPaint()
}
