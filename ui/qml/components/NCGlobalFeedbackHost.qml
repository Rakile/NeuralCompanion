pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Window
import QtQml.Models
import "../workspaces"
import "../theme" as Theme

Item {
    id: root
    objectName: "globalFeedbackHost"
    required property var bridge
    required property var mainWindow
    property var floatingWindows: []
    property var selectedWindow: mainWindow
    readonly property var hostWindow: canHost(selectedWindow) ? selectedWindow : mainWindow
    readonly property bool dialogActive: memoryDialogs.dialogActive || unsavedChat.dialogActive || roomSwitch.dialogActive
    property string toastTone: "info"
    property string toastTitle: ""
    property string toastMessage: ""

    parent: hostWindow.contentItem
    anchors.fill: parent

    function canHost(window) {
        return window && (window === mainWindow || floatingWindows.indexOf(window) >= 0)
                && window.visible && window.visibility !== Window.Minimized
    }

    function selectWindow(window) {
        if ((!dialogActive || !canHost(selectedWindow)) && canHost(window))
            selectedWindow = window
    }

    function reelect() {
        // Native file dialogs temporarily take focus from their initiating window.
        if (dialogActive && canHost(selectedWindow))
            return
        for (let index = 0; index < floatingWindows.length; ++index) {
            const window = floatingWindows[index]
            if (canHost(window) && window.active) {
                selectedWindow = window
                return
            }
        }
        if (canHost(mainWindow) && mainWindow.active) {
            selectedWindow = mainWindow
            return
        }
        // Focus can temporarily belong to a native dialog or another app.
        if (canHost(selectedWindow))
            return
        if (!canHost(mainWindow)) {
            for (let index = 0; index < floatingWindows.length; ++index) {
                if (canHost(floatingWindows[index])) {
                    selectedWindow = floatingWindows[index]
                    return
                }
            }
        }
        selectedWindow = mainWindow
    }

    onFloatingWindowsChanged: reelect()
    onDialogActiveChanged: if (!dialogActive) reelect()

    Connections {
        target: root.mainWindow
        function onActiveChanged() { if (target.active) root.selectWindow(target) }
    }

    Instantiator {
        model: root.floatingWindows
        delegate: Connections {
            required property var modelData
            target: modelData
            function onActiveChanged() { if (target.active) root.selectWindow(target) }
            function onVisibleChanged() { if (!root.canHost(target)) root.reelect() }
            function onVisibilityChanged() { if (!root.canHost(target)) root.reelect() }
        }
    }

    MemoryDialogs {
        id: memoryDialogs
        bridge: root.bridge
        dialogWindow: root.hostWindow
    }
    NCUnsavedChatDialog {
        id: unsavedChat
        guard: root.bridge.chatContextGuard
        dialogWindow: root.hostWindow
    }
    NCLocalRoomSwitchDialog {
        id: roomSwitch
        session: root.bridge.roomConversation || null
        dialogWindow: root.hostWindow
    }

    Popup {
        id: toast
        objectName: "globalNotificationToast"
        parent: root.hostWindow.Overlay.overlay
        x: root.width - width - Theme.NCMetrics.space24
        y: Theme.NCMetrics.space24
        width: Math.min(420, root.width - Theme.NCMetrics.space48)
        padding: 0
        closePolicy: Popup.NoAutoClose

        background: Rectangle { color: "transparent" }
        contentItem: NCInlineMessage {
            tone: root.toastTone
            title: root.toastTitle
            message: root.toastMessage
            dismissible: true
            onDismissed: toast.close()
        }
        Timer {
            id: toastTimer
            interval: 4200
            onTriggered: toast.close()
        }
    }

    Connections {
        target: root.bridge
        function onNotificationRaised(tone, title, message) {
            root.reelect()
            root.toastTone = tone
            root.toastTitle = title
            root.toastMessage = message
            toast.open()
            toastTimer.restart()
        }
    }
}
