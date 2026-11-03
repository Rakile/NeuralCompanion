import QtQuick

Rectangle {
    id: root
    property var bridge: null
    property var context: ({})
    // Reading tutorialState establishes the notify dependency for the slot.
    visible: Boolean(bridge && bridge.tutorialState && bridge.tutorialState.active
        && typeof bridge.tutorialMarksContext === "function" && bridge.tutorialMarksContext(context))
    anchors.fill: parent
    anchors.margins: 2
    radius: 6
    color: "transparent"
    border.color: "#FFE066"
    border.width: 2
    z: 10
    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        width: 8; height: 8; radius: 4
        color: "#FFE066"
    }
}
