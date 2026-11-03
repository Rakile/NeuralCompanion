import QtQuick
import QtQuick.Controls
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

TextField {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property string toolTipText: ""
    property string helpDescription: toolTipText

    property string label: ""
    property string errorText: ""
    readonly property var textEditingContextMenu: contextMenu

    implicitHeight: Theme.NCMetrics.controlHeight
    leftPadding: Theme.NCMetrics.space12
    rightPadding: Theme.NCMetrics.space12
    topPadding: Theme.NCMetrics.space8
    bottomPadding: Theme.NCMetrics.space8
    color: root.tutorialText ? TutorialStyle.yellow : enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
    placeholderTextColor: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.textMuted
    selectionColor: Theme.NCTheme.selection
    selectedTextColor: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.text
    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.bodySize
    Accessible.name: label.length > 0 ? label : placeholderText
    Accessible.description: [errorText, helpDescription].filter(Boolean).join(" ")

    ContextMenu.menu: NCTextEditingContextMenu {
        id: contextMenu
        editor: root
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: root.enabled ? Theme.NCTheme.windowRaised : Theme.NCTheme.surface
        border.width: root.activeFocus || root.errorText.length > 0 ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.errorText.length > 0 ? Theme.NCTheme.error
                                             : root.activeFocus ? Theme.NCTheme.focus
                                             : root.hovered ? Theme.NCTheme.borderStrong
                                             : Theme.NCTheme.border
    }
    NCHelp { target: root; text: root.toolTipText }
}
