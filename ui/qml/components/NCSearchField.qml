import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Control {
    id: root

    property string toolTipText: ""
    Accessible.description: toolTipText
    NCHelp { target: root; focusTarget: field; text: root.toolTipText }

    property alias text: field.text
    property alias placeholderText: field.placeholderText
    signal accepted()

    implicitHeight: Theme.NCMetrics.controlHeight
    implicitWidth: 220

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: Theme.NCTheme.windowRaised
        border.width: field.activeFocus ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: field.activeFocus ? Theme.NCTheme.focus : Theme.NCTheme.border
    }

    contentItem: RowLayout {
        spacing: Theme.NCMetrics.space8

        Label {
            text: "⌕"
            color: Theme.NCTheme.textSecondary
            font.pixelSize: Theme.NCTypography.headingSize
        }

        TextField {
            id: field
            Layout.fillWidth: true
            background: null
            leftPadding: 0
            rightPadding: clearButton.visible ? Theme.NCMetrics.space4 : 0
            color: Theme.NCTheme.text
            placeholderTextColor: Theme.NCTheme.textMuted
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.bodySize
            Accessible.name: placeholderText
            onAccepted: root.accepted()

            ContextMenu.menu: NCTextEditingContextMenu {
                editor: field
            }
        }

        NCIconButton {
            id: clearButton
            visible: field.text.length > 0
            implicitWidth: 28
            implicitHeight: 28
            glyph: "×"
            toolTipText: qsTr("Clear search")
            onClicked: field.clear()
        }
    }
}
