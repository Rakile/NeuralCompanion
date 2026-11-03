import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

MprcPanel {
    id: root
    objectName: "mprcSpeakingDock"
    property var speaker: ({})
    property bool compact: false
    readonly property bool speaking: speaker.state === "speaking"
    title: speaking ? qsTr("Now speaking") : speaker.state === "paused" ? qsTr("Playback paused") : qsTr("Speaking portrait")
    GridLayout {
        Layout.fillWidth: true
        columns: root.compact ? 2 : 1
        columnSpacing: 12
        MprcAvatar {
            objectName: "mprcDockAvatar"
            Layout.preferredWidth: root.compact ? 88 : Math.min(root.width - 26, 210)
            Layout.preferredHeight: root.compact ? 100 : 170
            Layout.alignment: Qt.AlignHCenter
            imageUrl: String(root.speaker.imageUrl || "")
            name: String(root.speaker.name || "")
            speaking: root.speaking
        }
        ColumnLayout {
            Layout.fillWidth: true
            Label {
                objectName: "mprcSpeakingState"
                Layout.fillWidth: true
                text: root.speaking ? qsTr("Speaking") : root.speaker.state === "paused" ? qsTr("Paused") : qsTr("Not speaking")
                color: root.speaking ? Theme.NCTheme.accent : Theme.NCTheme.textMuted
                font.pixelSize: 12
            }
            Label {
                objectName: "mprcSpeakingName"
                Layout.fillWidth: true
                text: String(root.speaker.name || qsTr("No speaker yet"))
                textFormat: Text.PlainText
                color: Theme.NCTheme.text
                font.pixelSize: 17
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                text: String(root.speaker.text || qsTr("The portrait follows voice playback, not persona selection."))
                textFormat: Text.PlainText
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
                maximumLineCount: root.compact ? 3 : 5
                elide: Text.ElideRight
            }
            Label {
                Layout.fillWidth: true
                text: root.speaker.state === "idle" && root.speaker.text ? qsTr("Last speaker · no active voice") : qsTr("Saved persona image · follows playback")
                color: Theme.NCTheme.textMuted
                wrapMode: Text.Wrap
                font.pixelSize: 11
            }
        }
    }
}
