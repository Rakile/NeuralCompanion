import QtQuick
import QtQuick.Controls
import "../theme" as Theme

Slider {
    id: root

    property string toolTipText: ""
    property string helpDescription: toolTipText

    property string label: ""

    implicitWidth: 220
    implicitHeight: Theme.NCMetrics.controlHeight
    hoverEnabled: true
    Accessible.description: helpDescription
    Accessible.name: label

    background: Rectangle {
        x: root.leftPadding
        y: root.topPadding + root.availableHeight / 2 - height / 2
        width: root.availableWidth
        height: 6
        radius: 3
        color: Theme.NCTheme.surfaceRaised
        border.color: Theme.NCTheme.border

        Rectangle {
            width: root.visualPosition * parent.width
            height: parent.height
            radius: parent.radius
            color: root.enabled ? Theme.NCTheme.accent : Theme.NCTheme.disconnected
        }
    }

    handle: Rectangle {
        x: root.leftPadding + root.visualPosition * (root.availableWidth - width)
        y: root.topPadding + root.availableHeight / 2 - height / 2
        implicitWidth: 20
        implicitHeight: 20
        radius: 10
        color: root.pressed ? Theme.NCTheme.accentStrong : Theme.NCTheme.accent
        border.width: root.activeFocus ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.activeFocus ? Theme.NCTheme.focus : Theme.NCTheme.window
    }
    NCHelp { target: root; text: root.toolTipText }
}
