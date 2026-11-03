import QtQuick

Item {
    id: root

    property string kind: "vision"
    property string toolTipText: ""
    property int iconSize: 28

    readonly property url iconSource: {
        if (kind === "thinking")
            return Qt.resolvedUrl("../../../ui_icons/capabilities/thinking.svg")
        if (kind === "tools")
            return Qt.resolvedUrl("../../../ui_icons/capabilities/tools.svg")
        return Qt.resolvedUrl("../../../ui_icons/capabilities/vision.svg")
    }

    implicitWidth: iconSize
    implicitHeight: iconSize
    Accessible.name: toolTipText

    Image {
        anchors.fill: parent
        source: root.iconSource
        sourceSize.width: root.iconSize * 2
        sourceSize.height: root.iconSize * 2
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
    }

    MouseArea {
        id: hoverArea
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        hoverEnabled: true
    }

    NCToolTip {
        visible: hoverArea.containsMouse && root.toolTipText.length > 0
        text: root.toolTipText
    }
}
