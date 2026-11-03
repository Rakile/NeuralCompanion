import QtQuick

Rectangle {
    id: root
    width: 220
    height: 220
    radius: 110
    color: gazePreviewBridge.theme.surface || "#101b2b"
    border.width: 4
    border.color: gazePreviewBridge.theme.accent || "#a78bfa"
    clip: true

    Image {
        anchors {
            fill: parent
            margins: 10
        }
        source: gazePreviewBridge.item.previewSource || ""
        fillMode: Image.PreserveAspectFit
        smooth: true
    }

    Rectangle {
        x: width * (gazePreviewBridge.item.crosshairX || 0.5) - 10
        y: height * (gazePreviewBridge.item.crosshairY || 0.5) - 10
        width: 20
        height: 20
        radius: 10
        color: "transparent"
        border.width: 3
        border.color: gazePreviewBridge.theme.timer || "#facc15"
    }

    Canvas {
        anchors.fill: parent
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = gazePreviewBridge.theme.timer || "#facc15"
            ctx.lineWidth = 6
            ctx.lineCap = "round"
            ctx.beginPath()
            ctx.arc(
                width / 2,
                height / 2,
                width / 2 - 5,
                -Math.PI / 2,
                -Math.PI / 2 + Math.PI * 2 * gazePreviewBridge.progress
            )
            ctx.stroke()
        }
        Connections {
            target: gazePreviewBridge
            function onChanged() { parent.requestPaint() }
        }
    }
}
