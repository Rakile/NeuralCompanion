import QtQuick
import QtQuick.Controls
import "../theme" as Theme

TextArea {
    id: root

    property string toolTipText: ""
    property string helpDescription: toolTipText

    property string label: ""
    property string errorText: ""
    property bool showRefineAction: false
    property bool refineActionEnabled: false
    signal refineRequested()

    implicitHeight: 112
    leftPadding: Theme.NCMetrics.space12
    rightPadding: Theme.NCMetrics.space12
    topPadding: Theme.NCMetrics.space10
    bottomPadding: Theme.NCMetrics.space10
    color: enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
    placeholderTextColor: Theme.NCTheme.textMuted
    selectionColor: Theme.NCTheme.selection
    selectedTextColor: Theme.NCTheme.text
    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.bodySize
    wrapMode: TextEdit.Wrap
    Accessible.name: label.length > 0 ? label : placeholderText
    Accessible.description: [errorText, helpDescription].filter(Boolean).join(" ")

    ContextMenu.menu: NCTextEditingContextMenu {
        editor: root
        showRefine: root.showRefineAction
        refineEnabled: root.refineActionEnabled
        onRefineRequested: root.refineRequested()
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: root.enabled ? Theme.NCTheme.windowRaised : Theme.NCTheme.surface
        border.width: root.activeFocus || root.errorText.length > 0
                      ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.errorText.length > 0 ? Theme.NCTheme.error
                                              : root.activeFocus ? Theme.NCTheme.focus
                                              : root.hovered ? Theme.NCTheme.borderStrong
                                              : Theme.NCTheme.border
    }
    NCHelp { target: root; text: root.toolTipText }
}
