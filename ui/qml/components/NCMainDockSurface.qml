pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "../theme" as Theme

Item {
    id: root

    required property var bridge
    property var layoutState: bridge.mainDockLayout
    readonly property var panes: layoutState.panes || ({})
    readonly property var splits: layoutState.splits || ({})

    function paneData(zone) {
        return panes[zone] || ({"zone": zone, "active": "", "workspaces": []})
    }

    function hasPane(zone) {
        return (paneData(zone).workspaces || []).length > 0
    }

    function workspaceItemForKey(workspaceKey) {
        const zone = bridge.mainWorkspaceZone(String(workspaceKey || ""))
        switch (zone) {
        case "left": return leftPane.workspaceItemForKey(workspaceKey)
        case "top": return topPane.workspaceItemForKey(workspaceKey)
        case "center": return centerPane.workspaceItemForKey(workspaceKey)
        case "bottom": return bottomPane.workspaceItemForKey(workspaceKey)
        case "right": return rightPane.workspaceItemForKey(workspaceKey)
        default: return null
        }
    }

    function scheduleSplitSave() {
        splitSaveTimer.restart()
    }

    Timer {
        id: splitSaveTimer
        interval: 320
        repeat: false
        onTriggered: root.bridge.updateMainDockSplitSizes(
                         root.hasPane("left") ? Math.round(leftPane.width)
                                              : Number(root.splits.left_width || 360),
                         root.hasPane("right") ? Math.round(rightPane.width)
                                               : Number(root.splits.right_width || 520),
                         root.hasPane("top") ? Math.round(topPane.height)
                                             : Number(root.splits.top_height || 300),
                         root.hasPane("bottom") ? Math.round(bottomPane.height)
                                                : Number(root.splits.bottom_height || 300))
    }

    SplitView {
        id: horizontalSplit
        anchors.fill: parent
        orientation: Qt.Horizontal
        onResizingChanged: if (!resizing) root.scheduleSplitSave()

        handle: Rectangle {
            objectName: "mainHorizontalDockHandle"
            enabled: !Boolean(root.bridge.panelPositionsLocked)
            implicitWidth: Theme.NCMetrics.space6
            implicitHeight: Theme.NCMetrics.space6
            color: SplitHandle.pressed ? Theme.NCTheme.accent
                  : SplitHandle.hovered ? Theme.NCTheme.borderStrong
                  : Theme.NCTheme.borderSubtle

            Rectangle {
                anchors.centerIn: parent
                width: parent.width > parent.height ? parent.width : Theme.NCMetrics.borderWidth
                height: parent.width > parent.height ? Theme.NCMetrics.borderWidth : parent.height
                color: SplitHandle.hovered ? Theme.NCTheme.accent : Theme.NCTheme.border
            }
        }

        NCDockPane {
            id: leftPane
            visible: root.hasPane("left")
            SplitView.preferredWidth: Number(root.splits.left_width || 360)
            SplitView.minimumWidth: 280
            bridge: root.bridge
            zone: "left"
            paneData: root.paneData("left")
        }

        SplitView {
            id: verticalSplit
            visible: root.hasPane("top") || root.hasPane("center") || root.hasPane("bottom")
                     || (!root.hasPane("left") && !root.hasPane("right"))
            SplitView.fillWidth: true
            SplitView.fillHeight: true
            SplitView.minimumWidth: 420
            orientation: Qt.Vertical
            onResizingChanged: if (!resizing) root.scheduleSplitSave()

            handle: Rectangle {
                objectName: "mainVerticalDockHandle"
                enabled: !Boolean(root.bridge.panelPositionsLocked)
                implicitWidth: Theme.NCMetrics.space6
                implicitHeight: Theme.NCMetrics.space6
                color: SplitHandle.pressed ? Theme.NCTheme.accent
                      : SplitHandle.hovered ? Theme.NCTheme.borderStrong
                      : Theme.NCTheme.borderSubtle
            }

            NCDockPane {
                id: topPane
                visible: root.hasPane("top")
                SplitView.preferredHeight: Number(root.splits.top_height || 300)
                SplitView.minimumHeight: 240
                bridge: root.bridge
                zone: "top"
                paneData: root.paneData("top")
            }

            NCDockPane {
                id: centerPane
                visible: root.hasPane("center")
                SplitView.fillHeight: true
                SplitView.minimumHeight: 320
                bridge: root.bridge
                zone: "center"
                paneData: root.paneData("center")
            }

            NCDockPane {
                id: bottomPane
                visible: root.hasPane("bottom")
                SplitView.preferredHeight: Number(root.splits.bottom_height || 300)
                SplitView.minimumHeight: 240
                bridge: root.bridge
                zone: "bottom"
                paneData: root.paneData("bottom")
            }
        }

        NCDockPane {
            id: rightPane
            visible: root.hasPane("right")
            SplitView.preferredWidth: Number(root.splits.right_width || 520)
            SplitView.minimumWidth: 320
            bridge: root.bridge
            zone: "right"
            paneData: root.paneData("right")
        }
    }
}
