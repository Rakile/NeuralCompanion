import QtQuick
import QtQuick.Controls
import "../theme" as Theme

CheckBox {
    id: root

    property string toolTipText: ""
    property string helpDescription: toolTipText

    spacing: Theme.NCMetrics.space10
    hoverEnabled: true
    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.bodySize
    Accessible.description: helpDescription
    Accessible.name: text

    indicator: Rectangle {
        implicitWidth: 20
        implicitHeight: 20
        x: root.leftPadding
        y: parent.height / 2 - height / 2
        radius: Theme.NCMetrics.radiusSmall
        color: root.checked ? Theme.NCTheme.accentStrong
                            : root.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.windowRaised
        border.width: root.activeFocus ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.activeFocus ? Theme.NCTheme.focus
                                       : root.checked ? Theme.NCTheme.accent : Theme.NCTheme.borderStrong

        Label {
            anchors.centerIn: parent
            text: "✓"
            visible: root.checked
            color: Theme.NCTheme.textInverse
            font.pixelSize: Theme.NCTypography.labelSize
            font.weight: Theme.NCTypography.bold
        }
    }

    contentItem: Label {
        text: root.text
        color: root.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
        font: root.font
        verticalAlignment: Text.AlignVCenter
        leftPadding: root.indicator.width + root.spacing
        wrapMode: Text.Wrap
    }
    NCHelp { target: root; text: root.toolTipText }
}
