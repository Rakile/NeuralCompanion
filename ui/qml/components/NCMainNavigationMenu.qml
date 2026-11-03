pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Popup {
    id: root
    objectName: "mainNavigationMenu"
    required property var bridge
    width: 304
    padding: Theme.NCMetrics.space8
    focus: true
    modal: false
    dim: false
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function openFor(control) {
        if (!control || !root.parent) return
        const position = control.mapToItem(root.parent, 0, control.height + Theme.NCMetrics.space4)
        root.x = Math.max(8, Math.min(position.x, root.parent.width - root.width - 8))
        root.y = Math.max(8, Math.min(position.y, root.parent.height - root.implicitHeight - 8))
        root.open()
    }

    function tabVisible(key) {
        const controls = root.bridge.mainTabControls || []
        for (let i = 0; i < controls.length; ++i)
            if (String(controls[i].key) === key) return Boolean(controls[i].visible)
        return false
    }

    background: Rectangle {
        color: Theme.NCTheme.windowRaised
        radius: Theme.NCMetrics.radiusLarge
        border.color: Theme.NCTheme.borderStrong
        border.width: Theme.NCMetrics.borderWidth
    }

    contentItem: ColumnLayout {
        spacing: Theme.NCMetrics.space2
        Label {
            Layout.margins: Theme.NCMetrics.space10
            text: qsTr("VIEWS & TABS")
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.microSize
            font.weight: Theme.NCTypography.bold
        }
        Repeater {
            model: root.bridge.mainTabControls
            delegate: NCCheckBox {
                toolTipText: qsTr("Show or hide this workspace in the main navigation. The workspace's settings and saved data remain available when its tab is hidden.")

                required property var modelData
                objectName: "mainTabVisibility_" + String(modelData.key)
                Layout.fillWidth: true
                Layout.leftMargin: Theme.NCMetrics.space10
                text: String(modelData.label) + (String(modelData.key) === root.bridge.currentWorkspace ? qsTr("  · Current") : "")
                checked: root.tabVisible(String(modelData.key))
                onClicked: root.bridge.setMainTabVisible(String(modelData.key), checked)
            }
        }
        Rectangle { Layout.fillWidth: true; Layout.margins: 4; implicitHeight: 1; color: Theme.NCTheme.borderSubtle }
        NCContextMenuItem {
            objectName: "mainTabsShowAll"
            Layout.fillWidth: true
            text: qsTr("Show all views and tabs"); glyph: "▣"
            onClicked: root.bridge.setAllMainTabsVisible(true)
        }
        NCContextMenuItem {
            objectName: "mainTabsHideAll"
            Layout.fillWidth: true
            text: qsTr("Hide all views and tabs"); glyph: "−"
            onClicked: root.bridge.setAllMainTabsVisible(false)
        }
        Rectangle { Layout.fillWidth: true; Layout.margins: 4; implicitHeight: 1; color: Theme.NCTheme.borderSubtle }
        NCCheckBox {
            toolTipText: qsTr("Lock docking and main-panel splitters to prevent accidental layout changes. Floating windows can still be moved or closed.")

            objectName: "mainPanelPositionsLock"
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space10
            text: qsTr("Lock panel positions")
            Accessible.description: qsTr("Lock docking and main-panel splitters. Floating windows can still be moved or closed.")
            checked: Boolean(root.bridge.panelPositionsLocked)
            onClicked: root.bridge.setPanelPositionsLocked(checked)
        }
        NCContextMenuItem {
            objectName: "mainTabsResetLayout"
            Layout.fillWidth: true
            text: qsTr("Reset layout…"); glyph: "↺"
            onClicked: { root.close(); resetDialog.open() }
        }
    }

    NCWorkspaceLayoutResetDialog {
        id: resetDialog
        objectName: "mainTabsResetDialog"
        bridge: root.bridge
    }
}
