import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root

    property string title: qsTr("Loading")
    property string description: ""

    spacing: Theme.NCMetrics.space10

    BusyIndicator {
        Layout.alignment: Qt.AlignHCenter
        running: root.visible
        palette.highlight: Theme.NCTheme.accent
        Accessible.name: root.title
    }
    Label {
        Layout.fillWidth: true
        text: root.title
        color: Theme.NCTheme.text
        font.pixelSize: Theme.NCTypography.headingSize
        font.weight: Theme.NCTypography.semibold
        horizontalAlignment: Text.AlignHCenter
    }
    Label {
        Layout.fillWidth: true
        visible: text.length > 0
        text: root.description
        color: Theme.NCTheme.textSecondary
        font.pixelSize: Theme.NCTypography.captionSize
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
    }
}
