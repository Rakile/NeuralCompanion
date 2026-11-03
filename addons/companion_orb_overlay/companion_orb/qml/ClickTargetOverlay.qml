import QtQuick

Rectangle {
    color: "transparent"

    Repeater {
        model: targetHighlightBridge.items
        delegate: Item {
            required property var modelData
            x: modelData.x
            y: modelData.y
            width: modelData.width
            height: modelData.height

            Rectangle {
                anchors.fill: parent
                color: "transparent"
                radius: 4
                border.width: modelData.active ? 3 : 2
                border.color: modelData.active ? modelData.accent : modelData.primary
            }

            Rectangle {
                visible: String(modelData.label).length > 0
                x: 0
                y: parent.height + 6
                width: Math.min(238, labelText.implicitWidth + 18)
                height: 24
                radius: 4
                color: modelData.surface
                opacity: 0.94
                Text {
                    id: labelText
                    anchors.centerIn: parent
                    width: parent.width - 18
                    text: modelData.label
                    color: modelData.text
                    font.pixelSize: 12
                    font.bold: true
                    elide: Text.ElideRight
                }
            }
        }
    }
}
