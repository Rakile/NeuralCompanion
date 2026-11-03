pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Column {
    id: root
    objectName: "mprcTranscript"
    property var chat: ({})
    property bool avatarsEnabled: true
    property string text: ""
    property real pointSize: 13
    property var rows: []
    property string rowsSignature: ""
    spacing: 8
    function updateRows() {
        const next = chat.rows || []
        const signature = JSON.stringify(next)
        if (signature !== rowsSignature) { rowsSignature = signature; rows = next }
    }
    onChatChanged: updateRows()
    Component.onCompleted: updateRows()
    readonly property string audibleRow: {
        const speaker = chat.speaker || {}
        if (speaker.state !== "speaking" || !speaker.personaId || !speaker.text) return ""
        const clean = value => String(value || "").replace(/[\s"“”]+/g, " ").trim()
        const spoken = clean(speaker.text)
        const matches = rows.filter(row => row.personaId === speaker.personaId && clean(row.text).includes(spoken))
        // Repeated identical lines are ambiguous without an audio route/turn ID.
        return matches.length === 1 ? matches[0].id : ""
    }
    NCTextArea {
        width: parent.width
        toolTipText: qsTr("Read-only story transcript. Select text here to copy narration and dialogue.")
        visible: !root.avatarsEnabled || !root.rows.length
        readOnly: true
        textFormat: TextEdit.PlainText
        text: root.text
        font.pointSize: root.pointSize
        wrapMode: TextEdit.Wrap
        background: null
    }
    Repeater {
        model: root.avatarsEnabled ? root.rows : []
        delegate: Rectangle {
            id: turn
            required property var modelData
            width: root.width
            height: content.implicitHeight + 16
            radius: 5
            readonly property bool audible: root.audibleRow === String(modelData.id)
            color: audible ? Theme.NCTheme.windowRaised : "transparent"
            border.color: audible ? Theme.NCTheme.accent : "transparent"
            RowLayout {
                id: content
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 8
                spacing: 10
                MprcAvatar {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 40
                    Layout.alignment: Qt.AlignTop
                    visible: ["assistant", "character", "narrator"].includes(String(turn.modelData.role))
                    imageUrl: String(turn.modelData.imageUrl || "")
                    name: String(turn.modelData.name || "")
                    speaking: turn.audible
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Label {
                        Layout.fillWidth: true
                        text: String(turn.modelData.name || "") + (turn.audible ? qsTr(" · Speaking") : "")
                        textFormat: Text.PlainText
                        color: turn.audible ? Theme.NCTheme.accent : Theme.NCTheme.textSecondary
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                    TextEdit {
                        Layout.fillWidth: true
                        text: String(turn.modelData.text || "")
                        readOnly: true
                        selectByMouse: true
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.Wrap
                        color: Theme.NCTheme.text
                        font.pointSize: root.pointSize
                    }
                }
            }
        }
    }
}
