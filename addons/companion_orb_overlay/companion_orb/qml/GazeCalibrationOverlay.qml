import QtQuick

Rectangle {
    color: "transparent"

    Item {
        x: gazeCalibrationBridge.targetX - 190
        y: gazeCalibrationBridge.targetY - 34
        width: 380
        height: 120

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 4
            width: 60
            height: 60
            radius: 30
            color: gazeCalibrationBridge.settling ? "#46f59e0b" : "#4638d9f8"
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 19
            width: 30
            height: 30
            radius: 15
            color: "transparent"
            border.width: 3
            border.color: gazeCalibrationBridge.themeColor
            opacity: 0.65
        }
        Canvas {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 9
            width: 50
            height: 50
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                ctx.strokeStyle = gazeCalibrationBridge.settling
                                  ? "#f59e0b" : gazeCalibrationBridge.themeColor
                ctx.lineWidth = 5
                ctx.lineCap = "round"
                ctx.beginPath()
                ctx.arc(25, 25, 22, -Math.PI / 2,
                        -Math.PI / 2 + Math.PI * 2 * gazeCalibrationBridge.progress)
                ctx.stroke()
            }
            Connections {
                target: gazeCalibrationBridge
                function onChanged() { parent.requestPaint() }
            }
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 25
            width: 18
            height: 18
            radius: 9
            color: gazeCalibrationBridge.settling
                   ? "#f59e0b" : gazeCalibrationBridge.themeColor
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 68
            text: "Target " + (gazeCalibrationBridge.targetIndex + 1)
                  + " of " + gazeCalibrationBridge.targetCount
            color: "#f8fafc"
            font.pixelSize: 14
            font.bold: true
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 89
            width: 360
            horizontalAlignment: Text.AlignHCenter
            text: gazeCalibrationBridge.message
            color: "#d7e3f0"
            font.pixelSize: 12
            elide: Text.ElideRight
        }
    }
}
