import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

GridLayout {
    id: root
    required property var studio
    readonly property var s: studio.state
    readonly property var selected: (s.voices || []).find(v => v.path === s.selected_voice) || ({})
    readonly property var choices: (s.voices || []).filter(v => v.valid && (!v.archived || v.path === s.selected_voice))
    columns: width >= 780 ? 2 : 1
    columnSpacing: 12; rowSpacing: 12
    VoiceLibraryList {
        Layout.fillWidth: true; Layout.preferredWidth: 390; Layout.alignment: Qt.AlignTop
        voices: root.s.voices || []
        selectedPath: String(root.s.selected_voice || "")
        busy: Boolean(root.s.busy)
        available: !root.s.closed
        onChoose: path => root.studio.edit("selected_voice", path)
        onPlay: path => root.studio.act("play_original", {reference: path})
        onRefresh: root.studio.act("refresh")
        NCButton { text: qsTr("Open voices folder"); onClicked: Qt.openUrlExternally("file:///" + String(root.s.destination || "").replace(/\\/g, "/")) }
    }
    NCCard {
        Layout.fillWidth: true; Layout.preferredWidth: 500; Layout.alignment: Qt.AlignTop
        title: qsTr("Preview a voice")
        NCComboBox {
            toolTipText: qsTr("Saved local recording to audition and inspect. Preview selection is independent of the normal chat voice; use Play original sample to hear the recording or Generate test to synthesize your own words with an already loaded Chatterbox backend.")
            objectName: "voiceStudioSelector"
            Layout.fillWidth: true; label: qsTr("Voice to preview")
            model: root.choices; textRole: "name"; valueRole: "path"
            currentIndex: root.choices.findIndex(v => v.path === root.s.selected_voice)
            displayText: currentIndex < 0 ? qsTr("Choose a recording from the library") : currentText
            onActivated: root.studio.edit("selected_voice", currentValue)
        }
        Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: root.selected.name || qsTr("No voice selected"); font.bold: true; color: Theme.NCTheme.text }
        Label { Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; text: root.selected.path || qsTr("Refresh or create a voice to begin."); font.pixelSize: Theme.NCTypography.captionSize; color: Theme.NCTheme.textMuted }
        Flow {
            Layout.fillWidth: true; spacing: 8
            NCButton { objectName: "voiceStudioPlaySample"; text: qsTr("Play original sample"); enabled: !root.s.busy && !!root.selected.valid; onClicked: root.studio.act("play_original", {reference: root.selected.path}) }
            NCButton { objectName: "voiceStudioSampleStop"; text: qsTr("Stop"); enabled: !!root.s.busy; onClicked: root.studio.act("stop") }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.NCTheme.borderSubtle }
        Label { text: qsTr("Try your own words"); color: Theme.NCTheme.text; font.bold: true }
        Label {
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: root.s.audition_ready ? qsTr("%1 loaded").arg(root.s.audition_backend_label || "Chatterbox") : qsTr("Load Chatterbox or Chatterbox Multilingual in Runtime → Text-to-speech to test your own text. Original recordings can still be played.")
            color: root.s.audition_ready ? Theme.NCTheme.success : Theme.NCTheme.warning
            font.pixelSize: Theme.NCTypography.captionSize
        }
        NCTextArea {
            toolTipText: qsTr("Words for a separate local audition using the selected recording as a voice reference. Requires loaded Chatterbox or Chatterbox Multilingual; it does not start a model or replace your normal chat voice. Refine with AI uses the active NC language model and requires applying its suggestion.")
            objectName: "voiceStudioTestText"
            Layout.fillWidth: true; implicitHeight: 90; wrapMode: TextEdit.Wrap
            text: root.s.test_text || ""; placeholderText: qsTr("Write the words you want this voice to say…")
            onTextChanged: if (activeFocus) root.studio.edit("test_text", text)
        }
        Flow {
            Layout.fillWidth: true; spacing: 8
            NCButton { text: qsTr("Generate test"); tone: "primary"; enabled: !root.s.busy && !!root.s.audition_ready && !!String(root.s.test_text || "").trim() && !!root.selected.valid; onClicked: root.studio.act("test") }
            NCButton { text: qsTr("Stop"); enabled: !!root.s.busy; onClicked: root.studio.act("stop") }
            NCButton { text: qsTr("Refine with AI"); enabled: !root.s.busy && !!root.s.test_text; onClicked: root.studio.act("refine_test") }
        }
        Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: qsTr("Refinement uses the active NC LLM. Voice tests preserve your normal chat voice."); font.pixelSize: Theme.NCTypography.captionSize; color: Theme.NCTheme.textSecondary }
        Label { visible: !!(root.s.test_result || {}).path; text: qsTr("Test reference: %1\nText: %2").arg((root.s.test_result || {}).reference || "").arg((root.s.test_result || {}).text || ""); Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; color: Theme.NCTheme.textSecondary; font.pixelSize: Theme.NCTypography.captionSize }
        Flow {
            visible: !!(root.s.test_result || {}).path; Layout.fillWidth: true; spacing: 8
            NCButton { text: qsTr("Play test"); enabled: !root.s.busy; onClicked: root.studio.act("play_test") }
            NCButton { text: qsTr("Save test recording…"); enabled: !root.s.busy; onClicked: exportDialog.open() }
        }
        VoiceDetails { record: root.selected; drafts: root.studio.voiceDetailsDrafts; busy: Boolean(root.s.busy); onAction: (name, payload) => root.studio.act(name, payload) }
    }
    FileDialog {
        id: exportDialog
        title: qsTr("Save a separate test recording")
        fileMode: FileDialog.SaveFile
        nameFilters: ["WAV recording (*.wav)"]
        defaultSuffix: "wav"
        onAccepted: root.studio.act("export_test", {path: selectedFile.toString()})
    }
}
