import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

ColumnLayout {
    id: root
    property var record: ({})
    property bool busy: false
    property string namePrefix: "voiceStudio"
    objectName: namePrefix + "Details"
    property var drafts: ({})
    property string editingPath: ""
    property bool loading: false
    readonly property bool dirty: description.text !== String(record.description || "") || notes.text !== String(record.notes || "")
    signal action(string name, var payload)
    Layout.fillWidth: true
    visible: !!record.path
    spacing: 8
    function remember() {
        if (!loading && editingPath) drafts[editingPath] = {description: description.text, notes: notes.text}
    }
    function synchronize() {
        loading = true
        const path = String(record.path || "")
        const draft = drafts[path]
        if (draft && draft.description === String(record.description || "") && draft.notes === String(record.notes || "")) delete drafts[path]
        editingPath = path
        const value = drafts[path] || record
        description.text = String(value.description || "")
        notes.text = String(value.notes || "")
        loading = false
    }
    onRecordChanged: synchronize()
    Component.onCompleted: synchronize()
    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.NCTheme.borderSubtle }
    Label { text: qsTr("Description & notes"); color: Theme.NCTheme.text; font.bold: true }
    Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: qsTr("Shared across Persona and Voice Studio. These notes do not change the recording."); color: Theme.NCTheme.textSecondary; font.pixelSize: Theme.NCTypography.captionSize }
    Label { text: qsTr("Description"); color: Theme.NCTheme.textSecondary; font.pixelSize: Theme.NCTypography.captionSize }
    NCTextArea {
        toolTipText: qsTr("Description saved with this voice reference and shared by Persona and Voice Studio, for example tone, accent or character. Save details persists edits; changing metadata does not regenerate or modify the WAV.")
        id: description; objectName: root.namePrefix + "Description"
        Layout.fillWidth: true; implicitHeight: 76; wrapMode: TextEdit.Wrap
        placeholderText: qsTr("Describe the tone, accent and character of this voice…")
        Accessible.name: qsTr("Voice description"); readOnly: root.busy
        onTextChanged: root.remember()
    }
    Label { text: qsTr("Notes"); color: Theme.NCTheme.textSecondary; font.pixelSize: Theme.NCTypography.captionSize }
    NCTextArea {
        toolTipText: qsTr("Personal notes saved with this voice reference and shared by Persona and Voice Studio, such as preferred uses or pronunciation reminders. Save details persists edits; these notes do not automatically change recorded speech.")
        id: notes; objectName: root.namePrefix + "Notes"
        Layout.fillWidth: true; implicitHeight: 76; wrapMode: TextEdit.Wrap
        placeholderText: qsTr("Personal notes, preferred uses or pronunciation tips…")
        Accessible.name: qsTr("Voice notes"); readOnly: root.busy
        onTextChanged: root.remember()
    }
    Flow {
        Layout.fillWidth: true; spacing: 8
        NCButton {
            objectName: root.namePrefix + "SaveDetails"
            text: qsTr("Save details"); tone: "primary"; enabled: !root.busy && root.dirty
            onClicked: root.action("save_voice_details", {reference: root.editingPath, description: description.text, notes: notes.text})
        }
        NCButton {
            objectName: root.namePrefix + "Remove"
            text: root.record.archived ? qsTr("Restore to library") : qsTr("Remove from library")
            enabled: !root.busy
            onClicked: {
                if (root.record.archived) root.action("restore_voice", {reference: root.editingPath})
                else { confirm.reference = root.editingPath; confirm.open() }
            }
        }
    }
    Label { visible: root.dirty; text: qsTr("Unsaved details"); color: Theme.NCTheme.warning; font.pixelSize: Theme.NCTypography.captionSize }
    NCDialog {
        id: confirm
        objectName: root.namePrefix + "RemoveDialog"
        property string reference: ""
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Remove voice from library?")
        description: qsTr("This hides the voice from both libraries. The WAV stays in place so saved personas keep working. Enable Show removed voices to restore it.")
        acceptText: qsTr("Remove from library")
        acceptTone: "danger"
        acceptEnabled: !root.busy
        onAccepted: root.action("remove_voice", {reference: reference})
    }
}
