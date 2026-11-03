import QtQuick
import QtQuick.Controls
import "../theme" as Theme

SpinBox {
    id: root

    property string toolTipText: ""
    property string helpDescription: toolTipText

    property string label: ""
    property string errorText: ""

    implicitWidth: 180
    implicitHeight: Theme.NCMetrics.controlHeight
    editable: true
    hoverEnabled: true
    Accessible.description: helpDescription
    Accessible.name: label

    contentItem: TextInput {
        id: editor
        Accessible.description: root.helpDescription
        z: 2
        text: root.textFromValue(root.value, root.locale)
        color: root.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
        selectionColor: Theme.NCTheme.selection
        selectedTextColor: Theme.NCTheme.text
        font.family: Theme.NCTypography.family
        font.pixelSize: Theme.NCTypography.bodySize
        horizontalAlignment: TextInput.AlignLeft
        verticalAlignment: TextInput.AlignVCenter
        leftPadding: Theme.NCMetrics.space12
        rightPadding: Theme.NCMetrics.controlHeight + Theme.NCMetrics.space4
        readOnly: !root.editable
        validator: root.validator
        inputMethodHints: Qt.ImhFormattedNumbersOnly

        ContextMenu.menu: NCTextEditingContextMenu {
            editor: editor
        }
    }

    up.indicator: Rectangle {
        x: root.width - width
        width: Theme.NCMetrics.controlHeight
        height: root.height / 2
        color: root.up.pressed ? Theme.NCTheme.surfacePressed
                               : root.up.hovered ? Theme.NCTheme.surfaceRaised : "transparent"
        border.color: Theme.NCTheme.borderSubtle
        Label {
            anchors.centerIn: parent
            text: "+"
            color: root.enabled ? Theme.NCTheme.textSecondary : Theme.NCTheme.textMuted
            font.weight: Theme.NCTypography.semibold
        }
    }

    down.indicator: Rectangle {
        x: root.width - width
        y: root.height / 2
        width: Theme.NCMetrics.controlHeight
        height: root.height / 2
        color: root.down.pressed ? Theme.NCTheme.surfacePressed
                                 : root.down.hovered ? Theme.NCTheme.surfaceRaised : "transparent"
        border.color: Theme.NCTheme.borderSubtle
        Label {
            anchors.centerIn: parent
            text: "−"
            color: root.enabled ? Theme.NCTheme.textSecondary : Theme.NCTheme.textMuted
            font.weight: Theme.NCTypography.semibold
        }
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: root.enabled ? Theme.NCTheme.surface : Theme.NCTheme.windowRaised
        border.width: root.activeFocus ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.errorText.length > 0 ? Theme.NCTheme.error
                                               : root.activeFocus ? Theme.NCTheme.focus
                                               : root.hovered ? Theme.NCTheme.borderStrong : Theme.NCTheme.border
    }
    NCHelp { target: root; text: root.toolTipText }
}
