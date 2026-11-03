import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Rectangle {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property string text: "Ready"
    property string status: "ready"
    property bool compact: false
    property bool pulse: false

    implicitWidth: row.implicitWidth + Theme.NCMetrics.space16
    implicitHeight: compact ? 24 : 28
    radius: Theme.NCMetrics.radiusPill
    color: Theme.NCTheme.statusSoftColor(status)
    border.width: Theme.NCMetrics.borderWidth
    border.color: Theme.NCTheme.withAlpha(Theme.NCTheme.statusColor(status), 0.7)
    Accessible.role: Accessible.StaticText
    Accessible.name: text

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: Theme.NCMetrics.space6

        Rectangle {
            Layout.preferredWidth: 7
            Layout.preferredHeight: 7
            radius: 4
            color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.statusColor(root.status)

            SequentialAnimation on opacity {
                running: root.pulse && root.visible
                loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 650 }
                NumberAnimation { to: 1.0; duration: 650 }
            }
        }

        Label {
            text: root.text
            color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.text
            font.family: Theme.NCTypography.family
            font.pixelSize: root.compact ? Theme.NCTypography.microSize : Theme.NCTypography.captionSize
            font.weight: Theme.NCTypography.medium
        }
    }
}
