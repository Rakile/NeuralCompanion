import QtQuick
import QtQuick.Controls
import "../theme" as Theme

Rectangle {
    id: root
    property string imageUrl: ""
    property string name: ""
    property bool speaking: false
    readonly property bool imageReady: portrait.status === Image.Ready
    implicitWidth: 44
    implicitHeight: 44
    radius: 6
    color: Theme.NCTheme.windowRaised
    border.color: speaking ? Theme.NCTheme.accent : Theme.NCTheme.border
    border.width: speaking ? 2 : 1
    Accessible.name: name.length ? name + qsTr(" portrait") : qsTr("No speaker portrait")
    Image {
        id: portrait
        anchors.fill: parent
        anchors.margins: 4
        source: root.imageUrl
        asynchronous: true
        sourceSize.width: 320
        sourceSize.height: 320
        fillMode: Image.PreserveAspectFit
        visible: root.imageReady
    }
    Label {
        anchors.centerIn: parent
        visible: !root.imageReady
        text: root.name.trim().charAt(0).toUpperCase() || "?"
        color: Theme.NCTheme.textSecondary
        font.pixelSize: Math.max(18, Math.min(60, root.height * 0.38))
    }
}
