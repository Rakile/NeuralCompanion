import QtQuick

Rectangle {
    color: "transparent"

    Repeater {
        model: spatialOverlayBridge.items
        delegate: Item {
            required property var modelData
            x: modelData.x
            y: modelData.y
            width: modelData.width
            height: modelData.height

            Rectangle {
                anchors.fill: parent
                color: "transparent"
                radius: 5
                opacity: modelData.opacity
                border.width: modelData.lineWidth
                border.color: modelData.color
            }

            Canvas {
                anchors.fill: parent
                visible: modelData.progress > 0
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.reset()
                    ctx.strokeStyle = modelData.color
                    ctx.lineWidth = modelData.lineWidth + 2
                    ctx.beginPath()
                    ctx.arc(width / 2, height / 2,
                            Math.max(8, Math.min(width, height) / 2 + 4),
                            -Math.PI / 2,
                            -Math.PI / 2 + Math.PI * 2 * modelData.progress)
                    ctx.stroke()
                }
            }

            Rectangle {
                visible: String(modelData.label).length > 0
                x: 0
                y: parent.y > 30 ? -28 : parent.height + 5
                width: Math.min(258, labelText.implicitWidth + 18)
                height: 24
                radius: 4
                color: modelData.surface
                opacity: 0.94
                Text {
                    id: labelText
                    anchors.centerIn: parent
                    width: parent.width - 18
                    text: modelData.label
                    color: modelData.text
                    font.pixelSize: 12
                    font.bold: true
                    elide: Text.ElideRight
                }
            }
        }
    }
}
