import QtQuick
import QtQuick.Controls
import "../theme" as Theme

RadioButton {
    id: root

    hoverEnabled: true
    spacing: Theme.NCMetrics.space8
    implicitHeight: Theme.NCMetrics.controlHeight

    indicator: Rectangle {
        implicitWidth: 19
        implicitHeight: 19
        x: root.leftPadding
        y: parent.height / 2 - height / 2
        radius: 10
        color: Theme.NCTheme.surface
        border.width: root.activeFocus ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.activeFocus ? Theme.NCTheme.focus
                                           : root.hovered ? Theme.NCTheme.borderStrong : Theme.NCTheme.border

        Rectangle {
            anchors.centerIn: parent
            width: 9
            height: 9
            radius: 5
            color: Theme.NCTheme.accent
            visible: root.checked
        }
    }

    contentItem: Label {
        leftPadding: root.indicator.width + root.spacing
        text: root.text
        color: root.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
        font.family: Theme.NCTypography.family
        font.pixelSize: Theme.NCTypography.bodySize
        verticalAlignment: Text.AlignVCenter
    }
}
