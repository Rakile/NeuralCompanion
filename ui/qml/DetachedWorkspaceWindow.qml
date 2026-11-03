pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "components"
import "theme" as Theme

Window {
    id: detachedWindow

    required property var bridge
    required property var groupData

    property string groupId: String(groupData.id || "")
    property string currentWorkspaceKey: String(groupData.active || "")
    property bool geometryRestored: false
    property var geometryWorkArea: ({})
    property bool geometryRecoveryPending: false
    property bool allowProgrammaticClose: false
    property bool avatarOnly: currentWorkspaceKey === "musetalk" && Boolean(groupData.avatarOnly)
    property bool alwaysOnTop: Boolean(groupData.alwaysOnTop)
    onAvatarOnlyChanged: saveWindowState()
    onCurrentWorkspaceKeyChanged: if (currentWorkspaceKey !== "musetalk") avatarOnly = false
    readonly property alias workspaceItem: detachedSurface.workspaceItem

    objectName: "detachedWorkspaceWindow_" + groupId
    title: bridge.applicationTitle + " · " + String(groupData.title || qsTr("Workspace"))
    color: Theme.NCTheme.window
    minimumWidth: Math.min(avatarOnly ? 160 : 760, Number(geometryWorkArea.width || (avatarOnly ? 160 : 760)))
    minimumHeight: Math.min(avatarOnly ? 160 : 560, Number(geometryWorkArea.height || (avatarOnly ? 160 : 560)))
    visible: (groupData.workspaces || []).length > 0
    flags: Qt.Window | (alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)
    // Floating workspaces are independently managed top-level windows. Keep
    // them visible when the main NeuralCompanion window is minimized.
    transientParent: null

    function containsWorkspace(workspaceKey) {
        const key = String(workspaceKey || "")
        const entries = groupData.workspaces || []
        for (let i = 0; i < entries.length; ++i) {
            if (String(entries[i].key) === key)
                return true
        }
        return false
    }

    function activateWorkspace(workspaceKey) {
        const key = String(workspaceKey || "")
        if (!containsWorkspace(key))
            return false
        currentWorkspaceKey = key
        bridge.setFloatingGroupActive(groupId, key)
        if (visibility === Window.Minimized)
            showNormal()
        raise()
        requestActivate()
        return true
    }

    function scheduleGeometrySave() {
        if (geometryRestored)
            geometrySaveTimer.restart()
    }

    function saveWindowState() {
        if (!geometryRestored)
            return
        geometrySaveTimer.stop()
        bridge.updateFloatingWorkspaceGeometry(groupId, Math.round(x), Math.round(y),
                                               Math.round(width), Math.round(height), avatarOnly)
    }

    function setAlwaysOnTop(enabled) {
        if (bridge.setFloatingWorkspaceAlwaysOnTop(groupId, enabled))
            alwaysOnTop = enabled
    }

    onGroupDataChanged: {
        const requestedWorkspace = String(groupData.active || "")
        if (requestedWorkspace)
            currentWorkspaceKey = requestedWorkspace
    }

    function restoreWindowGeometry(geometry) {
        const restored = bridge.windowGeometry.recover({
            "x": geometry.x === undefined ? x : Number(geometry.x),
            "y": geometry.y === undefined ? y : Number(geometry.y),
            "width": Math.max(minimumWidth, Number(geometry.width || 1180)),
            "height": Math.max(minimumHeight, Number(geometry.height || 780))
        }, avatarOnly ? 160 : 760, avatarOnly ? 160 : 560)
        geometryWorkArea = restored.workArea
        width = restored.geometry.width
        height = restored.geometry.height
        x = restored.geometry.x
        y = restored.geometry.y
    }

    function recoverWindowGeometry() {
        if (!geometryRestored)
            return
        if (visibility !== Window.Windowed) {
            geometryRecoveryPending = true
            return
        }
        geometryRecoveryPending = false
        restoreWindowGeometry({"x": x, "y": y, "width": width, "height": height})
    }

    Connections {
        target: detachedWindow.bridge.windowGeometry
        function onChanged() { detachedWindow.recoverWindowGeometry() }
    }

    Component.onCompleted: {
        restoreWindowGeometry(groupData.geometry || {})
        geometryRestored = true
        if (visible)
            Qt.callLater(requestActivate)
    }

    onXChanged: scheduleGeometrySave()
    onYChanged: scheduleGeometrySave()
    onWidthChanged: scheduleGeometrySave()
    onHeightChanged: scheduleGeometrySave()
    onVisibilityChanged: {
        if (geometryRecoveryPending && visibility === Window.Windowed)
            recoverWindowGeometry()
    }

    onClosing: function(close) {
        saveWindowState()
        if (bridge.applicationClosing || allowProgrammaticClose) {
            close.accepted = true
            return
        }
        close.accepted = false
        bridge.dockFloatingGroupToMain(groupId)
    }

    Timer {
        id: geometrySaveTimer
        interval: 350
        repeat: false
        onTriggered: detachedWindow.saveWindowState()
    }

    NCTutorialOverlay {
        anchors.fill: parent
        z: 80
        bridge: detachedWindow.bridge
        hostWindow: detachedWindow
        guideEnabled: false
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            objectName: "detachedWorkspaceHeader"
            visible: !detachedWindow.avatarOnly
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.NCMetrics.topBarHeight - Theme.NCMetrics.space8
            color: Theme.NCTheme.windowRaised
            border.color: Theme.NCTheme.borderSubtle
            border.width: Theme.NCMetrics.borderWidth

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.NCMetrics.space12
                anchors.rightMargin: Theme.NCMetrics.space12
                spacing: Theme.NCMetrics.space6

                Repeater {
                    model: detachedWindow.groupData.workspaces || []

                    delegate: Button {
                        id: floatingTabButton
                        NCTutorialMarker { bridge: detachedWindow.bridge; context: ({workspace: floatingTabButton.workspaceKey}) }
                        required property var modelData
                        property string workspaceKey: String(modelData.key || "")
                        checked: workspaceKey === detachedWindow.currentWorkspaceKey
                        implicitHeight: Theme.NCMetrics.controlHeight
                        implicitWidth: Math.max(92, floatingTabLabel.implicitWidth + Theme.NCMetrics.space24)
                        hoverEnabled: true
                        Accessible.name: String(modelData.label || "")

                        background: Rectangle {
                            radius: Theme.NCMetrics.radiusMedium
                            color: floatingTabButton.down ? Theme.NCTheme.surfacePressed
                                  : floatingTabButton.checked ? Theme.NCTheme.surfaceSelected
                                  : floatingTabButton.hovered ? Theme.NCTheme.surfaceRaised
                                  : Theme.NCTheme.surface
                            border.width: floatingTabButton.checked || floatingTabButton.activeFocus
                                          ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                            border.color: floatingTabButton.activeFocus ? Theme.NCTheme.focus
                                        : floatingTabButton.checked ? Theme.NCTheme.accent
                                        : Theme.NCTheme.border
                        }

                        contentItem: Label {
                            id: floatingTabLabel
                            text: String(floatingTabButton.modelData.label || "")
                            color: Theme.NCTheme.text
                            font.pixelSize: Theme.NCTypography.labelSize
                            font.weight: floatingTabButton.checked
                                         ? Theme.NCTypography.semibold : Theme.NCTypography.medium
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: detachedWindow.activateWorkspace(workspaceKey)

                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onTapped: floatingTabMenu.openFor(floatingTabButton)
                        }

                        NCDockContextMenu {
                            id: floatingTabMenu
                            parent: Overlay.overlay
                            bridge: detachedWindow.bridge
                            workspaceKey: floatingTabButton.workspaceKey
                            workspaceLabel: String(floatingTabButton.modelData.label || qsTr("Workspace"))
                            floatingGroupId: detachedWindow.groupId
                            floatingGroupWorkspaceCount: (detachedWindow.groupData.workspaces || []).length
                            onOpenRequested: function(key) {
                                detachedWindow.activateWorkspace(key)
                            }
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                NCButton {
                    objectName: "floatingAlwaysOnTopButton"
                    text: qsTr("Always on top")
                    compact: true
                    checkable: true
                    checked: detachedWindow.alwaysOnTop
                    tone: checked ? "primary" : "secondary"
                    toolTipText: qsTr("Keep this floating window above other applications")
                    onClicked: {
                        detachedWindow.setAlwaysOnTop(checked)
                        checked = Qt.binding(function() { return detachedWindow.alwaysOnTop })
                    }
                }

                NCButton {
                    objectName: "avatarOnlyButton"
                    visible: detachedWindow.currentWorkspaceKey === "musetalk"
                    text: qsTr("Avatar only")
                    compact: true
                    toolTipText: qsTr("Hide preview controls and padding. Hover to restore them, or press Esc.")
                    onClicked: detachedWindow.avatarOnly = true
                }

                Button {
                    id: dockButton
                    text: qsTr("Dock")
                    implicitHeight: Theme.NCMetrics.controlHeight
                    hoverEnabled: true
                    onClicked: dockMenu.openFor(dockButton)

                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusMedium
                        color: dockButton.down ? Theme.NCTheme.surfacePressed
                              : dockButton.hovered ? Theme.NCTheme.surfaceRaised
                              : Theme.NCTheme.surface
                        border.width: Theme.NCMetrics.borderWidth
                        border.color: Theme.NCTheme.border
                    }
                    contentItem: Label {
                        text: dockButton.text
                        color: Theme.NCTheme.text
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }

                    NCDockContextMenu {
                        id: dockMenu
                        parent: Overlay.overlay
                        bridge: detachedWindow.bridge
                        workspaceKey: detachedWindow.currentWorkspaceKey
                        workspaceLabel: detachedWindow.currentWorkspaceKey
                        floatingGroupId: detachedWindow.groupId
                        floatingGroupWorkspaceCount: (detachedWindow.groupData.workspaces || []).length
                        onOpenRequested: function(key) {
                            detachedWindow.activateWorkspace(key)
                        }
                    }
                }
            }
        }

        NCWorkspaceSurface {
            id: detachedSurface
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: detachedWindow.avatarOnly ? 0 : Theme.NCMetrics.space16
            bridge: detachedWindow.bridge
            workspaceKey: detachedWindow.currentWorkspaceKey
            avatarOnly: detachedWindow.avatarOnly
        }
    }

    NCAvatarOnlyControls {
        anchors.fill: parent
        visible: detachedWindow.avatarOnly
        onRestoreRequested: detachedWindow.avatarOnly = false
        onContextMenuRequested: function(position) {
            windowOptionsMenu.x = Math.max(8, Math.min(position.x, width - windowOptionsMenu.width - 8))
            windowOptionsMenu.y = Math.max(8, Math.min(position.y, height - windowOptionsMenu.implicitHeight - 8))
            windowOptionsMenu.open()
        }
    }

    Popup {
        id: windowOptionsMenu
        objectName: "floatingWindowOptionsMenu"
        parent: detachedWindow.contentItem
        width: Math.min(240, parent.width - 16)
        padding: Theme.NCMetrics.space8
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: Theme.NCTheme.windowRaised
            radius: Theme.NCMetrics.radiusMedium
            border.color: Theme.NCTheme.borderStrong
            border.width: Theme.NCMetrics.borderWidth
        }
        contentItem: NCCheckBox {
            toolTipText: qsTr("Keep this detached NC workspace above ordinary windows. Turning this off returns it to normal window stacking; it does not close or stop the workspace.")

            objectName: "floatingAlwaysOnTopMenuItem"
            text: qsTr("Always on top")
            checked: detachedWindow.alwaysOnTop
            onClicked: {
                detachedWindow.setAlwaysOnTop(checked)
                checked = Qt.binding(function() { return detachedWindow.alwaysOnTop })
                windowOptionsMenu.close()
            }
        }
    }

    NCUiReviewOverlay {
        anchors.fill: parent
        controller: detachedWindow.bridge.uiReviewNotes
        bridge: detachedWindow.bridge
        windowObjectName: detachedWindow.objectName
        workspaceKey: detachedWindow.currentWorkspaceKey
        drawerEnabled: false
    }
}
