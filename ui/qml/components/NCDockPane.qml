pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Rectangle {
    id: root

    required property var bridge
    property string zone: "center"
    property var paneData: ({"active": "", "workspaces": []})
    readonly property string activeWorkspaceKey: String(paneData.active || "")
    readonly property int workspaceCount: (paneData.workspaces || []).length
    readonly property var activeWorkspace: {
        const workspaces = paneData.workspaces || []
        for (let index = 0; index < workspaces.length; ++index) {
            if (String(workspaces[index].key || "") === activeWorkspaceKey)
                return workspaces[index]
        }
        return ({"label": "", "glyph": ""})
    }
    readonly property alias workspaceItem: workspaceSurface.workspaceItem

    objectName: "mainDockPane_" + zone
    color: Theme.NCTheme.window
    radius: Theme.NCMetrics.radiusLarge
    border.width: Theme.NCMetrics.borderWidth
    border.color: Theme.NCTheme.border
    clip: true

    function workspaceItemForKey(workspaceKey) {
        return String(workspaceKey || "") === activeWorkspaceKey
               ? workspaceSurface.workspaceItem : null
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? Theme.NCMetrics.controlHeightCompact : 0
            visible: root.zone !== "center"
            color: Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.borderSubtle

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.NCMetrics.space6
                anchors.rightMargin: Theme.NCMetrics.space6
                spacing: Theme.NCMetrics.space4

                Label {
                    text: String(root.activeWorkspace.glyph || "")
                    color: Theme.NCTheme.accent
                    font.pixelSize: Theme.NCTypography.labelSize
                    Layout.leftMargin: Theme.NCMetrics.space6
                }

                Label {
                    Layout.fillWidth: true
                    text: String(root.activeWorkspace.label || "")
                    color: Theme.NCTheme.text
                    font.pixelSize: Theme.NCTypography.labelSize
                    font.weight: Theme.NCTypography.semibold
                    elide: Text.ElideRight
                }

                Label {
                    text: String(root.zone || "").toUpperCase()
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.microSize
                    font.weight: Theme.NCTypography.bold
                    Layout.rightMargin: Theme.NCMetrics.space6
                }
            }
        }

        NCWorkspaceSurface {
            id: workspaceSurface
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: Theme.NCMetrics.space10
            bridge: root.bridge
            workspaceKey: root.activeWorkspaceKey || String(root.paneData.retainedActive || "")
        }
    }
}
