import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Rectangle {
    id: root
    property string title: ""
    property string description: ""
    property bool foldable: false
    property bool expanded: true
    readonly property int panelPadding: foldable && !expanded ? 6 : 12
    default property alias contentData: body.data
    signal toggled(bool expanded)
    implicitWidth: 300
    implicitHeight: column.implicitHeight + panelPadding * 2
    radius: 6
    color: Theme.NCTheme.surface
    border.color: Theme.NCTheme.border

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: root.panelPadding
        spacing: 10
        NCButton {
            id: foldButton
            objectName: root.objectName + "Toggle"
            Layout.fillWidth: true
            visible: root.foldable
            compact: true
            text: (root.expanded ? "▾  " : "▸  ") + root.title
            tone: "quiet"
            contentItem: Label {
                text: foldButton.text
                color: Theme.NCTheme.textSecondary
                font.pixelSize: 13
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            onClicked: {
                root.expanded = !root.expanded
                root.toggled(root.expanded)
            }
        }
        Label {
            Layout.fillWidth: true
            visible: !root.foldable && root.title.length > 0
            text: root.title
            color: Theme.NCTheme.text
            font.pixelSize: 15
            font.weight: Font.DemiBold
            wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            visible: (!root.foldable || root.expanded) && root.description.length > 0
            text: root.description
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.captionSize
            wrapMode: Text.Wrap
        }
        ColumnLayout {
            id: body
            Layout.fillWidth: true
            visible: !root.foldable || root.expanded
            spacing: 10
        }
    }
}
