pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts
import "../theme" as Theme

Menu {
    id: root
    objectName: "ncTextEditingContextMenu"

    required property Item editor
    property bool showRefine: false
    property bool refineEnabled: false
    signal refineRequested()

    width: 232
    topPadding: Theme.NCMetrics.space8
    bottomPadding: Theme.NCMetrics.space8
    leftPadding: Theme.NCMetrics.space8
    rightPadding: Theme.NCMetrics.space8
    spacing: Theme.NCMetrics.space2
    margins: Theme.NCMetrics.space8
    popupType: Popup.Item
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function glyphFor(iconName) {
        switch (String(iconName || "")) {
        case "edit-undo": return "↶"
        case "edit-redo": return "↷"
        case "edit-cut": return "✂"
        case "edit-copy": return "⧉"
        case "edit-paste": return "▣"
        case "edit-delete": return "×"
        case "edit-select-all": return "⌗"
        default: return ""
        }
    }

    function shortcutFor(iconName) {
        switch (String(iconName || "")) {
        case "edit-undo": return "Ctrl+Z"
        case "edit-redo": return "Ctrl+Y"
        case "edit-cut": return "Ctrl+X"
        case "edit-copy": return "Ctrl+C"
        case "edit-paste": return "Ctrl+V"
        case "edit-delete": return "Del"
        case "edit-select-all": return "Ctrl+A"
        default: return ""
        }
    }

    delegate: MenuItem {
        id: menuItem

        implicitWidth: root.width - root.leftPadding - root.rightPadding
        implicitHeight: Theme.NCMetrics.controlHeight
        leftPadding: Theme.NCMetrics.space10
        rightPadding: Theme.NCMetrics.space10
        hoverEnabled: true

        background: Rectangle {
            radius: Theme.NCMetrics.radiusSmall
            color: menuItem.down ? Theme.NCTheme.surfacePressed
                  : menuItem.highlighted ? Theme.NCTheme.surfaceSelected
                  : "transparent"
            border.width: menuItem.activeFocus ? Theme.NCMetrics.focusWidth : 0
            border.color: Theme.NCTheme.focus
        }

        contentItem: RowLayout {
            spacing: Theme.NCMetrics.space10

            Label {
                Layout.preferredWidth: 18
                text: root.glyphFor(menuItem.icon.name)
                color: menuItem.enabled ? Theme.NCTheme.accent : Theme.NCTheme.textMuted
                opacity: menuItem.enabled ? 1.0 : 0.55
                font.pixelSize: Theme.NCTypography.bodySize
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            Label {
                Layout.fillWidth: true
                text: menuItem.text
                color: menuItem.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
                opacity: menuItem.enabled ? 1.0 : 0.55
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.labelSize
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }

            Label {
                text: root.shortcutFor(menuItem.icon.name)
                color: Theme.NCTheme.textMuted
                opacity: menuItem.enabled ? 0.9 : 0.45
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.microSize
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    background: Rectangle {
        color: Theme.NCTheme.windowRaised
        radius: Theme.NCMetrics.radiusLarge
        border.width: Theme.NCMetrics.focusWidth
        border.color: Theme.NCTheme.borderStrong

        Rectangle {
            anchors.fill: parent
            anchors.margins: Theme.NCMetrics.focusWidth
            radius: Theme.NCMetrics.radiusLarge - Theme.NCMetrics.focusWidth
            color: "transparent"
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.borderSubtle
        }
    }

    UndoAction { editor: root.editor }
    RedoAction { editor: root.editor }

    MenuSeparator {
        topPadding: Theme.NCMetrics.space4
        bottomPadding: Theme.NCMetrics.space4
        contentItem: Rectangle {
            implicitHeight: Theme.NCMetrics.borderWidth
            color: Theme.NCTheme.borderSubtle
        }
    }

    CutAction { editor: root.editor }
    CopyAction { editor: root.editor }
    PasteAction { editor: root.editor }
    DeleteAction { editor: root.editor }

    MenuSeparator {
        topPadding: Theme.NCMetrics.space4
        bottomPadding: Theme.NCMetrics.space4
        contentItem: Rectangle {
            implicitHeight: Theme.NCMetrics.borderWidth
            color: Theme.NCTheme.borderSubtle
        }
    }

    SelectAllAction { editor: root.editor }

    MenuSeparator { visible: root.showRefine }
    MenuItem {
        visible: root.showRefine
        text: qsTr("Refine into system prompt")
        enabled: root.refineEnabled
        onTriggered: root.refineRequested()
    }
}
