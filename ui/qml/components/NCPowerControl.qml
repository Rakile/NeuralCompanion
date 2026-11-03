pragma ComponentBehavior: Bound
import QtQuick

// Keep right-click available even when the runtime action is disabled.
Item {
    id: root
    implicitWidth: powerButton.implicitWidth
    implicitHeight: powerButton.implicitHeight

    property alias active: powerButton.active
    property alias busy: powerButton.busy
    property alias cancellable: powerButton.cancellable
    property alias cancelling: powerButton.cancelling
    property alias cleanupPending: powerButton.cleanupPending
    property alias glowEnabled: powerButton.glowEnabled
    property alias compact: powerButton.compact
    property alias showLabels: powerButton.showLabels
    property alias busyText: powerButton.busyText
    property alias busyDescription: powerButton.busyDescription
    signal clicked()
    signal restartRequested()

    NCPowerSwitch {
        id: powerButton
        anchors.fill: parent
        onClicked: root.clicked()
    }
    MouseArea {
        objectName: "powerRestartRightClickArea"
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onClicked: root.restartRequested()
    }
}
