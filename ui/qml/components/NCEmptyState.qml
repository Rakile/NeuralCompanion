import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

ColumnLayout {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property string glyph: "◇"
    property string title: qsTr("Nothing here yet")
    property string description: ""
    property string actionText: ""
    signal actionTriggered()

    spacing: Theme.NCMetrics.space8

    Rectangle {
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: 56
        Layout.preferredHeight: 56
        radius: 28
        color: Theme.NCTheme.surfaceRaised
        border.color: Theme.NCTheme.border

        Label {
            anchors.centerIn: parent
            text: root.glyph
            color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.accent
            font.pixelSize: 28
        }
    }

    Label {
        Layout.fillWidth: true
        text: root.title
        color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.text
        font.family: Theme.NCTypography.family
        font.pixelSize: Theme.NCTypography.headingSize
        font.weight: Theme.NCTypography.semibold
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
    }

    Label {
        Layout.fillWidth: true
        text: root.description
        color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.textSecondary
        font.family: Theme.NCTypography.family
        font.pixelSize: Theme.NCTypography.bodySize
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        visible: text.length > 0
    }

    NCButton {
        Layout.alignment: Qt.AlignHCenter
        text: root.actionText
        tone: "primary"
        visible: text.length > 0
        onClicked: root.actionTriggered()
    }
}
