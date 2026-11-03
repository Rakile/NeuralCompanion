import QtQuick
import QtQuick.Controls
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Button {
    id: root
    property var tutorialBridge: null
    property var tutorialContext: ({})
    NCTutorialMarker { bridge: root.tutorialBridge; context: root.tutorialContext }
    NCTutorialMenu { id: tutorialMenu; bridge: root.tutorialBridge || ({}) }
    TapHandler {
        acceptedButtons: Qt.RightButton
        enabled: root.tutorialBridge !== null && TutorialStyle.showContext(root.tutorialBridge)
        onTapped: tutorialMenu.openFor(root, root.tutorialContext)
    }
    Keys.onPressed: event => {
        if (root.tutorialBridge && TutorialStyle.showContext(root.tutorialBridge) && (event.key === Qt.Key_Menu
                || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier)))) {
            tutorialMenu.openFor(root, root.tutorialContext)
            event.accepted = true
        }
    }

    hoverEnabled: true
    implicitHeight: Theme.NCMetrics.controlHeight
    implicitWidth: tabLabel.implicitWidth + Theme.NCMetrics.space24
    padding: Theme.NCMetrics.space8

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: root.down ? Theme.NCTheme.surfacePressed
                         : root.checked ? Theme.NCTheme.surfaceSelected
                         : root.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
        border.width: root.activeFocus || root.checked
                      ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.activeFocus ? Theme.NCTheme.focus
                                       : root.checked ? Theme.NCTheme.accent : Theme.NCTheme.border
    }

    contentItem: Label {
        id: tabLabel
        text: root.text
        color: root.checked ? Theme.NCTheme.text : Theme.NCTheme.textSecondary
        font.family: Theme.NCTypography.family
        font.pixelSize: Theme.NCTypography.labelSize
        font.weight: root.checked ? Theme.NCTypography.semibold : Theme.NCTypography.regular
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
