import QtQuick
import QtQuick.Controls
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Switch {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property string toolTipText: ""
    property string helpDescription: toolTipText
    property bool indicatorOnRight: false

    spacing: Theme.NCMetrics.space10
    hoverEnabled: true
    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.bodySize
    Accessible.description: helpDescription
    Accessible.name: text

    indicator: Rectangle {
        implicitWidth: 42
        implicitHeight: 24
        x: root.indicatorOnRight ? root.width - width - root.rightPadding : root.leftPadding
        y: parent.height / 2 - height / 2
        radius: height / 2
        color: root.tutorialText ? TutorialStyle.yellow : root.checked ? Theme.NCTheme.accentStrong
                            : root.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.windowRaised
        border.width: root.activeFocus ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.activeFocus ? Theme.NCTheme.focus
                                       : root.checked ? Theme.NCTheme.accent : Theme.NCTheme.borderStrong

        Rectangle {
            width: 18
            height: 18
            radius: 9
            x: root.checked ? parent.width - width - 3 : 3
            anchors.verticalCenter: parent.verticalCenter
            color: root.tutorialText ? TutorialStyle.yellow : root.checked ? Theme.NCTheme.textInverse : Theme.NCTheme.textSecondary

            Behavior on x { NumberAnimation { duration: Theme.NCMetrics.motionFast; easing.type: Easing.OutCubic } }
        }
    }

    contentItem: Label {
        text: root.text
        color: root.tutorialText ? TutorialStyle.yellow : root.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
        font: root.font
        verticalAlignment: Text.AlignVCenter
        leftPadding: root.indicator.width + root.spacing
        wrapMode: Text.Wrap
    }
    NCHelp { target: root; text: root.toolTipText }
}
