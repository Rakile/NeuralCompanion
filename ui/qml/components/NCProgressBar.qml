import QtQuick
import QtQuick.Controls
import "../theme" as Theme

ProgressBar {
    id: root

    implicitHeight: 8

    background: Rectangle {
        implicitWidth: 200
        implicitHeight: 8
        radius: 4
        color: Theme.NCTheme.surfaceRaised
    }

    contentItem: Item {
        implicitWidth: 200
        implicitHeight: 8
        clip: true

        Rectangle {
            id: progressFill
            width: root.indeterminate
                ? parent.width * 0.35
                : parent.width * Math.max(0.0, Math.min(root.visualPosition, 1.0))
            height: parent.height
            radius: 4
            color: Theme.NCTheme.accent

            SequentialAnimation on x {
                running: root.indeterminate && root.visible
                loops: Animation.Infinite
                NumberAnimation {
                    from: -progressFill.width
                    to: progressFill.parent ? progressFill.parent.width : root.width
                    duration: 950
                    easing.type: Easing.InOutQuad
                }
            }

            Behavior on width { NumberAnimation { duration: Theme.NCMetrics.motionNormal } }
        }
    }
}
