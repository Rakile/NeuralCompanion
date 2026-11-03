pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Popup {
    id: root

    required property var bridge
    property string workspaceKey: ""
    property string workspaceLabel: qsTr("Workspace")
    property string floatingGroupId: ""
    property int floatingGroupWorkspaceCount: 0
    readonly property bool positionsLocked: Boolean(root.bridge.panelPositionsLocked)
    signal openRequested(string workspaceKey)

    NCTutorialMenu { id: tutorialMenu; bridge: root.bridge }

    NCWorkspaceLayoutResetDialog {
        id: resetDialog
        bridge: root.bridge
    }

    width: 304
    padding: Theme.NCMetrics.space8
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    modal: false
    dim: false

    function openFor(control) {
        if (!control || !root.parent)
            return
        const mapped = control.mapToItem(root.parent, 0, control.height + Theme.NCMetrics.space4)
        root.x = Math.max(
                    Theme.NCMetrics.space8,
                    Math.min(mapped.x, root.parent.width - root.width - Theme.NCMetrics.space8))
        root.y = Math.max(
                    Theme.NCMetrics.space8,
                    Math.min(mapped.y, root.parent.height - root.implicitHeight - Theme.NCMetrics.space8))
        root.open()
    }

    function hasOtherFloatingGroup() {
        const groups = root.bridge.floatingWorkspaceGroups || []
        const currentHost = root.bridge.workspaceHost(root.workspaceKey)
        for (let index = 0; index < groups.length; ++index) {
            const groupId = String(groups[index].id || "")
            if (groupId && groupId !== root.floatingGroupId && groupId !== currentHost)
                return true
        }
        return false
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

    contentItem: ColumnLayout {
        spacing: Theme.NCMetrics.space2

        NCContextMenuItem {
            objectName: "dockTutorialsItem"
            tutorialText: true
            visible: TutorialStyle.showContext(root.bridge)
            text: qsTr("Tutorials…")
            glyph: "?"
            onClicked: {
                tutorialMenu.openFor(root.contentItem, {workspace: root.workspaceKey})
                root.close()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space8
            Layout.rightMargin: Theme.NCMetrics.space8
            Layout.topMargin: Theme.NCMetrics.space4
            Layout.bottomMargin: Theme.NCMetrics.space4

            Label {
                Layout.fillWidth: true
                text: root.workspaceLabel
                color: Theme.NCTheme.text
                font.pixelSize: Theme.NCTypography.labelSize
                font.weight: Theme.NCTypography.semibold
                elide: Text.ElideRight
            }

            Label {
                text: qsTr("WORKSPACE")
                color: Theme.NCTheme.accent
                font.pixelSize: Theme.NCTypography.microSize
                font.weight: Theme.NCTypography.bold
            }
        }

        NCContextMenuItem {
            text: qsTr("Open workspace")
            glyph: "↗"
            trailingText: "Ctrl+" + String(
                              ["runtime", "addons", "conversation", "visuals", "musetalk"]
                              .indexOf(root.workspaceKey) + 1)
            onClicked: {
                root.close()
                root.openRequested(root.workspaceKey)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.NCMetrics.borderWidth
            Layout.topMargin: Theme.NCMetrics.space4
            Layout.bottomMargin: Theme.NCMetrics.space4
            color: Theme.NCTheme.borderSubtle
        }

        Label {
            Layout.leftMargin: Theme.NCMetrics.space10
            Layout.topMargin: Theme.NCMetrics.space2
            text: qsTr("DOCK INSIDE MAIN WINDOW")
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.microSize
            font.weight: Theme.NCTypography.bold
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: Theme.NCMetrics.space4
            rowSpacing: Theme.NCMetrics.space2

            NCContextMenuItem {
                Layout.fillWidth: true
                implicitWidth: 0
                text: qsTr("Left")
                enabled: !root.positionsLocked
                glyph: "←"
                onClicked: {
                    root.close()
                    root.bridge.dockWorkspaceInMain(root.workspaceKey, "left")
                }
            }
            NCContextMenuItem {
                Layout.fillWidth: true
                implicitWidth: 0
                text: qsTr("Right")
                enabled: !root.positionsLocked
                glyph: "→"
                onClicked: {
                    root.close()
                    root.bridge.dockWorkspaceInMain(root.workspaceKey, "right")
                }
            }
            NCContextMenuItem {
                Layout.fillWidth: true
                implicitWidth: 0
                text: qsTr("Above")
                enabled: !root.positionsLocked
                glyph: "↑"
                onClicked: {
                    root.close()
                    root.bridge.dockWorkspaceInMain(root.workspaceKey, "top")
                }
            }
            NCContextMenuItem {
                Layout.fillWidth: true
                implicitWidth: 0
                text: qsTr("Below")
                enabled: !root.positionsLocked
                glyph: "↓"
                onClicked: {
                    root.close()
                    root.bridge.dockWorkspaceInMain(root.workspaceKey, "bottom")
                }
            }
        }

        NCContextMenuItem {
            text: qsTr("Tabbed in main workspace")
            enabled: !root.positionsLocked
            glyph: "▣"
            onClicked: {
                root.close()
                root.bridge.dockWorkspaceInMain(root.workspaceKey, "center")
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.NCMetrics.borderWidth
            Layout.topMargin: Theme.NCMetrics.space4
            Layout.bottomMargin: Theme.NCMetrics.space4
            color: Theme.NCTheme.borderSubtle
        }

        NCContextMenuItem {
            text: qsTr("Detach to floating window")
            glyph: "□"
            enabled: !root.positionsLocked && (root.bridge.workspaceHost(root.workspaceKey) === "main"
                     || root.floatingGroupWorkspaceCount > 1)
            onClicked: {
                root.close()
                root.bridge.detachWorkspace(root.workspaceKey)
            }
        }

        Label {
            visible: root.hasOtherFloatingGroup()
            Layout.leftMargin: Theme.NCMetrics.space10
            Layout.topMargin: Theme.NCMetrics.space4
            text: qsTr("MOVE TO ANOTHER NC WINDOW")
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.microSize
            font.weight: Theme.NCTypography.bold
        }

        Repeater {
            model: root.bridge.floatingWorkspaceGroups || []

            delegate: NCContextMenuItem {
                required property var modelData
                visible: String(modelData.id || "") !== root.floatingGroupId
                         && String(modelData.id || "")
                            !== root.bridge.workspaceHost(root.workspaceKey)
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? implicitHeight : 0
                text: qsTr("Join %1").arg(String(modelData.title || qsTr("workspace window")))
                enabled: !root.positionsLocked
                glyph: "⊞"
                onClicked: {
                    root.close()
                    root.bridge.dockWorkspaceWithGroup(
                                root.workspaceKey,
                                String(modelData.id || ""))
                }
            }
        }

        NCContextMenuItem {
            visible: Boolean(root.floatingGroupId)
            Layout.preferredHeight: visible ? implicitHeight : 0
            text: qsTr("Dock entire floating window to main")
            enabled: !root.positionsLocked
            glyph: "⇲"
            onClicked: {
                root.close()
                root.bridge.dockFloatingGroupToMain(root.floatingGroupId)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.NCMetrics.borderWidth
            Layout.topMargin: Theme.NCMetrics.space4
            Layout.bottomMargin: Theme.NCMetrics.space4
            color: Theme.NCTheme.borderSubtle
        }

        NCContextMenuItem {
            text: qsTr("Default Layout")
            glyph: "↺"
            trailingText: qsTr("Reset")
            onClicked: {
                root.close()
                resetDialog.open()
            }
        }
    }
}
