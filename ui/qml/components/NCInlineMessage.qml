import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Rectangle {
    id: root

    property string tone: "info"
    property string title: ""
    property string message: ""
    property bool dismissible: false
    signal dismissed()

    implicitHeight: row.implicitHeight + Theme.NCMetrics.space20
    radius: Theme.NCMetrics.radiusMedium
    color: Theme.NCTheme.statusSoftColor(tone)
    border.width: Theme.NCMetrics.borderWidth
    border.color: Theme.NCTheme.statusColor(tone)

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: Theme.NCMetrics.space10
        spacing: Theme.NCMetrics.space10

        Rectangle {
            Layout.preferredWidth: 8
            Layout.preferredHeight: 8
            radius: 4
            color: Theme.NCTheme.statusColor(root.tone)
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space2

            Label {
                Layout.fillWidth: true
                text: root.title
                color: Theme.NCTheme.text
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.labelSize
                font.weight: Theme.NCTypography.semibold
                visible: text.length > 0
            }

            Label {
                Layout.fillWidth: true
                text: root.message
                color: Theme.NCTheme.textSecondary
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.Wrap
            }
        }

        NCIconButton {
            visible: root.dismissible
            glyph: "×"
            toolTipText: qsTr("Dismiss")
            onClicked: root.dismissed()
        }
    }
}
