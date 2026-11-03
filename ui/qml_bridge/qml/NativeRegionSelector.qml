import QtQuick

Rectangle {
    id: root
    color: "#6c000000"

    property point origin: Qt.point(-1, -1)
    property point current: Qt.point(-1, -1)
    property bool selecting: origin.x >= 0
    property real rawWidth: Math.abs(current.x - origin.x)
    property real rawHeight: Math.abs(current.y - origin.y)
    property real side: Math.max(rawWidth, rawHeight)
    property real selectionWidth: nativeRegionSelector.squareMode ? side : rawWidth
    property real selectionHeight: nativeRegionSelector.squareMode ? side : rawHeight
    property real selectionX: current.x >= origin.x
                              ? origin.x : origin.x - selectionWidth
    property real selectionY: current.y >= origin.y
                              ? origin.y : origin.y - selectionHeight

    Text {
        visible: !root.selecting
        anchors.centerIn: parent
        text: nativeRegionSelector.squareMode
              ? "Drag to select a square. Esc or right-click cancels."
              : "Drag to select an area. Esc or right-click cancels."
        color: "#dbeafe"
        font.pixelSize: 16
        font.bold: true
    }

    Rectangle {
        visible: root.selecting
        x: root.selectionX
        y: root.selectionY
        width: root.selectionWidth
        height: root.selectionHeight
        color: "#2a38bdf8"
        radius: 7
        border.width: 2
        border.color: "#7dd3fc"
        Text {
            anchors {
                left: parent.left
                top: parent.top
                margins: 10
            }
            text: Math.round(parent.width) + " x " + Math.round(parent.height)
            color: "#f1f5f9"
            font.pixelSize: 12
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        cursorShape: Qt.CrossCursor
        onPressed: function(mouse) {
            if (mouse.button === Qt.RightButton) {
                nativeRegionSelector.cancel()
                return
            }
            root.origin = Qt.point(mouse.x, mouse.y)
            root.current = root.origin
        }
        onPositionChanged: function(mouse) {
            if (pressedButtons & Qt.LeftButton)
                root.current = Qt.point(mouse.x, mouse.y)
        }
        onReleased: function(mouse) {
            if (mouse.button !== Qt.LeftButton || !root.selecting)
                return
            root.current = Qt.point(mouse.x, mouse.y)
            nativeRegionSelector.complete(
                root.selectionX,
                root.selectionY,
                root.selectionWidth,
                root.selectionHeight
            )
        }
    }

    focus: true
    Keys.onEscapePressed: nativeRegionSelector.cancel()
    Component.onCompleted: forceActiveFocus()
}
