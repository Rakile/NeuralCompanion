import QtQuick
import QtQuick.Controls

NCDialog {
    id: root
    objectName: "workspaceLayoutResetDialog"
    required property var bridge
    parent: Overlay.overlay
    x: (parent.width - width) / 2
    y: (parent.height - height) / 2
    title: qsTr("Reset window layout?")
    description: qsTr("Show all main tabs, unlock panel positions, and restore the default docking positions and sizes. Your current workspace stays open.")
    acceptText: qsTr("Reset layout")
    onAccepted: root.bridge.resetWorkspaceLayout()
}
