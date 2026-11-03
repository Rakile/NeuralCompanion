pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "../theme" as Theme

Item {
    id: root
    signal restoreRequested()
    signal contextMenuRequested(point position)
    z: 50

    HoverHandler { id: pointer }

    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: function(eventPoint) { root.contextMenuRequested(eventPoint.position) }
    }

    NCButton {
        objectName: "avatarOnlyRestoreButton"
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: Theme.NCMetrics.space8
        text: qsTr("Restore controls")
        compact: true
        visible: pointer.hovered || hovered || activeFocus
        toolTipText: qsTr("Return to the normal preview window (Esc)")
        onClicked: root.restoreRequested()
    }

    Shortcut {
        sequence: "Esc"
        context: Qt.WindowShortcut
        enabled: root.visible
        onActivated: root.restoreRequested()
    }
}
