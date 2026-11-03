import QtQuick

Rectangle {
    color: "transparent"
    border.color: "#56ddf3"
    border.width: 2
    Rectangle {
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        width: dimensions.implicitWidth + 16
        height: 24
        color: "#102b3b"
        Text {
            id: dimensions
            anchors.centerIn: parent
            color: "#e6f7ff"
            text: regionEditor ? regionEditor.regionWidth + " × " + regionEditor.regionHeight : ""
        }
    }
}
