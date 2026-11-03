import QtQuick

Rectangle {
    id: root
    width: 660
    height: 660
    color: "transparent"
    focus: true

    property var palette: gazeRadialBridge.theme
    property real centerX: width / 2
    property real centerY: height / 2

    Canvas {
        id: backgroundCanvas
        anchors.fill: parent
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const radius = 271
            const gradient = ctx.createRadialGradient(
                root.centerX, root.centerY, 20,
                root.centerX, root.centerY, radius
            )
            gradient.addColorStop(0, "#1807111f")
            gradient.addColorStop(0.58, "#24101b2b")
            gradient.addColorStop(1, "#0007111f")
            ctx.fillStyle = gradient
            ctx.beginPath()
            ctx.arc(root.centerX, root.centerY, radius, 0, Math.PI * 2)
            ctx.fill()
            ctx.strokeStyle = palette.primary || "#38bdf8"
            ctx.globalAlpha = 0.28
            ctx.lineWidth = 1.2
            ctx.stroke()
            ctx.globalAlpha = 1
        }
    }

    MouseArea {
        anchors.fill: parent
        onClicked: gazeRadialBridge.cancel()
    }

    Repeater {
        model: gazeRadialBridge.items
        delegate: Item {
            id: actionItem
            required property var modelData
            x: modelData.x
            y: modelData.y
            width: modelData.width
            height: modelData.height
            opacity: modelData.enabled ? 1.0 : 0.48
            property bool candidate: gazeRadialBridge.candidateId === modelData.id

            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: actionItem.candidate
                       ? (palette.accent || "#a78bfa")
                       : (palette.surface || "#101b2b")
                border.width: actionItem.candidate ? 4 : 2
                border.color: modelData.checked
                              ? (palette.timer || "#facc15")
                              : (palette.primary || "#38bdf8")
            }

            Image {
                visible: String(modelData.previewSource).length > 0
                anchors {
                    fill: parent
                    margins: 8
                }
                source: modelData.previewSource
                fillMode: Image.PreserveAspectFit
                smooth: true
                clip: true
            }

            Rectangle {
                visible: String(modelData.previewSource).length > 0
                x: width * modelData.crosshairX - 7
                y: height * modelData.crosshairY - 7
                width: 14
                height: 14
                radius: 7
                color: "transparent"
                border.width: 2
                border.color: "#facc15"
            }

            Text {
                anchors {
                    fill: parent
                    margins: modelData.visualInspection ? 20 : 10
                }
                visible: String(modelData.previewSource).length === 0
                text: modelData.label
                color: palette.text || "#eef7ff"
                font.pixelSize: modelData.visualInspection ? 13 : 12
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.Wrap
                elide: Text.ElideRight
            }

            Canvas {
                anchors.fill: parent
                visible: actionItem.candidate && gazeRadialBridge.progress > 0
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.reset()
                    ctx.strokeStyle = palette.timer || "#facc15"
                    ctx.lineWidth = 5
                    ctx.lineCap = "round"
                    ctx.beginPath()
                    ctx.arc(
                        width / 2,
                        height / 2,
                        Math.max(4, width / 2 - 4),
                        -Math.PI / 2,
                        -Math.PI / 2 + Math.PI * 2 * gazeRadialBridge.progress
                    )
                    ctx.stroke()
                }
                Connections {
                    target: gazeRadialBridge
                    function onChanged() { parent.requestPaint() }
                }
            }

            MouseArea {
                anchors.fill: parent
                enabled: modelData.enabled
                onClicked: function(mouse) {
                    mouse.accepted = true
                    gazeRadialBridge.activate(String(modelData.id))
                }
            }
        }
    }

    Rectangle {
        id: centerButton
        x: root.centerX - 46
        y: root.centerY - 46
        width: 92
        height: 92
        radius: 46
        color: gazeRadialBridge.candidateId === gazeRadialBridge.centerId
               ? (palette.accent || "#a78bfa")
               : (palette.surface || "#101b2b")
        border.width: 2
        border.color: palette.secondary || "#22d3ee"
        Text {
            anchors {
                fill: parent
                margins: 9
            }
            text: gazeRadialBridge.centerLabel
            color: palette.text || "#eef7ff"
            font.pixelSize: 12
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
        }
        MouseArea {
            anchors.fill: parent
            onClicked: {
                mouse.accepted = true
                gazeRadialBridge.activate(gazeRadialBridge.centerId)
            }
        }
    }

    Text {
        x: root.centerX - 100
        y: root.centerY + 54
        width: 200
        height: 30
        text: gazeRadialBridge.title
        color: palette.text || "#eef7ff"
        font.pixelSize: 12
        font.bold: true
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
    }

    Keys.onEscapePressed: gazeRadialBridge.cancel()
    Component.onCompleted: forceActiveFocus()
}
