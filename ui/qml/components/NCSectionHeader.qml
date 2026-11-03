import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root

    property string eyebrow: ""
    property string title: ""
    property string description: ""
    property alias accessory: accessory.data

    spacing: Theme.NCMetrics.space6

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space12

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space4

            Label {
                text: root.eyebrow.toUpperCase()
                color: Theme.NCTheme.accent
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.microSize
                font.weight: Theme.NCTypography.bold
                font.letterSpacing: 1.1
                visible: text.length > 0
            }

            Label {
                Layout.fillWidth: true
                text: root.title
                color: Theme.NCTheme.text
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.titleSize
                font.weight: Theme.NCTypography.semibold
                wrapMode: Text.Wrap
            }
        }

        RowLayout {
            id: accessory
            spacing: Theme.NCMetrics.space8
        }
    }

    Label {
        Layout.fillWidth: true
        text: root.description
        color: Theme.NCTheme.textSecondary
        font.family: Theme.NCTypography.family
        font.pixelSize: Theme.NCTypography.bodySize
        wrapMode: Text.Wrap
        visible: text.length > 0
    }
}
