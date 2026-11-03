import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

ColumnLayout {
    id: root
    required property var studio
    readonly property var s: studio.state
    readonly property var character: (s.characters || [])[s.character_index || 0] || {}
    readonly property var job: {
        const rows = s.jobs || []
        for (let i=0; i<rows.length; ++i) if (rows[i].id === character.id) return rows[i]
        return {}
    }
    readonly property var candidates: job.candidates || []
    function stateFor(id) {
        const rows = s.jobs || []
        for (let i = 0; i < rows.length; ++i) if (rows[i].id === id) return rows[i].state
        return "draft"
    }
    spacing: 12
    NCCard {
        title: "Creation provider"
        Layout.fillWidth: true
        ColumnLayout {
            Layout.fillWidth: true
            NCComboBox {
                toolTipText: qsTr("Provider used to design new voices. ElevenLabs sends descriptions and sample text to its cloud API and consumes account credits; Local connects to your separately installed VoiceStudio service. This does not switch the normal chat speech provider.")
                Layout.fillWidth: true
                model: ["ElevenLabs — Cloud", "VoiceStudio — Local"]
                currentIndex: root.s.provider === "local" ? 1 : 0
                enabled: !root.s.busy
                onActivated: root.studio.edit("provider", currentIndex ? "local" : "elevenlabs")
            }
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: root.s.provider === "local" ? root.s.local_status || "Connect to your installation in Settings." : "Generation uses ElevenLabs credits. Preview WAVs do not occupy saved voice slots." }
            Label { visible: root.s.provider !== "local"; Layout.fillWidth: true; wrapMode: Text.Wrap; text: (root.s.characters || []).length + " characters · selected sample: " + String(root.character.preview_text || "").length + " characters · cost/quota estimate unavailable" }
            NCComboBox {
                toolTipText: qsTr("Supported local design engine discovered from VoiceStudio. Install and load the engine in that service, then check the local connection. OmniVoice uses restricted tags; freeform engines accept descriptive instructions.")
                visible: root.s.provider === "local"
                Layout.fillWidth: true
                model: root.s.engines || []; textRole: "label"; valueRole: "id"
                currentIndex: indexOfValue(root.s.engine || "")
                enabled: !root.s.busy
                onActivated: root.studio.edit("engine", currentValue)
            }
            Label { visible: root.s.provider === "local"; text: "Engine instruction / supported OmniVoice tags" }
            NCTextArea {
                toolTipText: qsTr("Local-engine instruction for this character, up to 5,000 characters. Empty uses its voice description. OmniVoice accepts comma-separated gender, age, pitch, whisper and accent tags, with one attribute per category; English accent tags require English speech.")
                visible: root.s.provider === "local"; Layout.fillWidth: true; wrapMode: TextEdit.Wrap
                text: root.character.local_instruction || ""; placeholderText: "Example tags: female, middle-aged, low pitch, british accent"
                readOnly: !!root.s.busy
                onTextChanged: if (activeFocus) root.studio.edit("character.local_instruction", text)
            }
            NCButton { visible: root.s.provider === "local"; text: "Adapt selected character with AI"; enabled: !root.s.busy; onClicked: root.studio.act("adapt_voice") }
            Label { visible: root.s.provider === "local"; Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Instruction belongs to the selected character. Freeform engines use its description when empty. OmniVoice supports gender, age, pitch, whisper and English accent tags only; other traits remain in the original description. Each local candidate is a separate generation." }
        }
    }
    GridLayout {
        Layout.fillWidth: true
        columns: width > 850 ? 2 : 1
        columnSpacing: 16; rowSpacing: 12
        NCCard {
            title: "Your cast"
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            ColumnLayout {
                Layout.fillWidth: true
                Label { text: "What voices do you need?" }
                NCTextArea { toolTipText: qsTr("Describe the cast you want the active NC language model to draft, including character roles and vocal differences. Draft characters with AI uses this brief and Voice count; it does not generate voice audio until a generation action is run."); Layout.fillWidth: true; implicitHeight: 110; wrapMode: TextEdit.Wrap; text: root.s.brief || ""; onTextChanged: if (activeFocus) root.studio.edit("brief", text) }
                RowLayout {
                    Label { text: "Voice count" }
                    NCSpinBox { toolTipText: qsTr("Number of character drafts requested from the active NC language model (1–50). This counts cast members rather than audio candidates; generating the resulting cast later can incur a separate request for each character."); from: 1; to: 50; value: root.s.count || 10; editable: true; onValueModified: root.studio.edit("count", value) }
                }
                NCCheckBox { toolTipText: qsTr("When enabled, save the first valid candidate for each character as a local WAV and continue the batch. When disabled, pause at candidate review so you can listen and choose. This does not save a permanent ElevenLabs cloud voice."); text: "Automatic — save first valid candidate"; checked: !!root.s.automatic; enabled: !root.s.busy; onToggled: root.studio.edit("automatic", checked) }
                NCButton { text: "Draft characters with AI"; enabled: !root.s.busy; onClicked: root.studio.act("draft") }
                Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Uses the active NC LLM. You can also add and edit characters manually." }
                ListView {
                    Layout.fillWidth: true; Layout.preferredHeight: 260; clip: true; spacing: 6
                    model: root.s.characters || []
                    delegate: ItemDelegate {
                        id: castRow
                        required property var modelData
                        required property int index
                        width: ListView.view.width
                        height: 54
                        text: modelData.name + " · " + root.stateFor(modelData.id)
                        highlighted: index === root.s.character_index
                        hoverEnabled: true
                        background: Rectangle {
                            radius: 8
                            color: castRow.highlighted ? Theme.NCTheme.surfaceSelected : Theme.NCTheme.windowRaised
                            border.color: castRow.hovered ? Theme.NCTheme.warning : castRow.highlighted ? Theme.NCTheme.accent : Theme.NCTheme.border
                        }
                        contentItem: Label {
                            text: castRow.text; elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                            color: castRow.hovered ? Theme.NCTheme.warning : Theme.NCTheme.text
                        }
                        enabled: !root.s.busy
                        onClicked: root.studio.edit("character_index", index)
                    }
                    ScrollBar.vertical: ScrollBar {}
                }
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    NCButton { text: "Add character"; enabled: !root.s.busy; onClicked: root.studio.act("add_character") }
                    NCButton { text: "Save cast drafts"; enabled: !root.s.busy; onClicked: root.studio.act("save_cast") }
                    NCButton {
                        objectName: "voiceStudioCastLoad"
                        text: qsTr("Load saved drafts"); enabled: !root.s.busy
                        onClicked: loadCastDialog.open()
                    }
                    NCButton {
                        objectName: "voiceStudioCastRemove"
                        text: qsTr("Remove selected draft"); enabled: !root.s.busy && !!root.character.id
                        onClicked: {
                            removeCastDialog.characterId = root.character.id
                            removeCastDialog.characterName = root.character.name || qsTr("this character")
                            removeCastDialog.open()
                        }
                    }
                    NCButton { text: "Generate all / continue"; enabled: !root.s.busy; onClicked: root.studio.act("generate_all") }
                }
                Label {
                    objectName: "voiceStudioCastPath"
                    Layout.fillWidth: true; wrapMode: Text.Wrap
                    text: qsTr("Saved drafts: %1").arg(root.s.cast_path || "")
                    color: Theme.NCTheme.textSecondary; font.pixelSize: Theme.NCTypography.captionSize
                }
            }
        }
        NCCard {
            title: "Character voice"
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            ColumnLayout {
                Layout.fillWidth: true
                Label { text: "Name" }
                NCTextField { toolTipText: qsTr("Name of the selected character, stored with the cast and used when publishing its local recording. Saved WAVs receive unique filenames; naming a character does not overwrite existing recordings."); Layout.fillWidth: true; text: root.character.name || ""; enabled: !root.s.busy; onTextEdited: root.studio.edit("character.name", text) }
                Label { text: "Character description" }
                NCTextArea { toolTipText: qsTr("Background description stored with this character in the cast, up to 5,000 characters. Use Voice description for the vocal traits actually sent to the design provider."); Layout.fillWidth: true; implicitHeight: 82; wrapMode: TextEdit.Wrap; text: root.character.description || ""; readOnly: !!root.s.busy; onTextChanged: if (activeFocus) root.studio.edit("character.description", text) }
                Label { text: "Voice description" }
                NCTextArea { toolTipText: qsTr("Vocal traits used to design this character voice: tone, accent, age and delivery. ElevenLabs requires 20–1,000 characters. A local freeform engine uses this when its character instruction is empty; OmniVoice requires supported tags."); Layout.fillWidth: true; implicitHeight: 110; wrapMode: TextEdit.Wrap; text: root.character.voice_description || ""; readOnly: !!root.s.busy; onTextChanged: if (activeFocus) root.studio.edit("character.voice_description", text) }
                NCButton { text: "Refine voice description with AI"; enabled: !root.s.busy; onClicked: root.studio.act("refine_voice") }
                Label { text: "Sample text" }
                NCTextArea { toolTipText: qsTr("Words spoken in generated voice candidates. ElevenLabs requires 100–1,000 characters; local generation accepts 1–5,000 characters. Cloud requests consume credits, so use a representative sample when comparing voices."); Layout.fillWidth: true; implicitHeight: 110; wrapMode: TextEdit.Wrap; text: root.character.preview_text || ""; readOnly: !!root.s.busy; onTextChanged: if (activeFocus) root.studio.edit("character.preview_text", text) }
                Label { text: "State: " + (root.job.state || "draft") + (root.job.error ? " — " + root.job.error : ""); Layout.fillWidth: true; wrapMode: Text.Wrap }
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    NCButton { text: "Generate selected"; enabled: !root.s.busy; onClicked: root.studio.act("generate") }
                    NCButton { text: "Regenerate / retry"; enabled: !root.s.busy && ["failed", "review", "saved"].indexOf(root.job.state) >= 0; onClicked: root.studio.act("retry") }
                    NCButton { text: "Allow retry after checking provider"; visible: root.job.state === "unknown"; enabled: !root.s.busy; onClicked: root.studio.act("resolve") }
                }
                Label { text: "Choose a candidate"; visible: root.candidates.length > 0 }
                NCComboBox { toolTipText: qsTr("Candidate used by Preview, Save selected WAV and longer-dialogue generation. Choosing a candidate does not regenerate audio. Manual selection lets you compare returned designs before publishing a unique local recording."); Layout.fillWidth: true; model: root.candidates.map((c, i) => "Candidate " + (i+1) + " · " + c.request.provider + " / " + c.request.model_id); currentIndex: root.s.candidate_index || 0; onActivated: root.studio.edit("candidate_index", currentIndex); visible: root.candidates.length > 0 }
                Flow {
                    Layout.fillWidth: true; spacing: 8; visible: root.candidates.length > 0
                    NCButton { text: "Preview"; enabled: !root.s.busy; onClicked: root.studio.act("play_candidate") }
                    NCButton { text: "Stop"; enabled: !!root.s.busy; onClicked: root.studio.act("stop") }
                    NCButton { text: "Save selected WAV"; enabled: !root.s.busy; onClicked: root.studio.act("save_candidate") }
                }
            }
        }
    }
    NCCard {
        title: "Longer dialogue — ElevenLabs candidate"
        Layout.fillWidth: true
        visible: root.candidates.length > 0 && root.candidates[0].request.provider === "elevenlabs"
        ColumnLayout {
            Layout.fillWidth: true
            NCTextArea { toolTipText: qsTr("Text for longer speech using the selected ElevenLabs candidate. Generation creates a tracked temporary cloud voice, consumes provider credits and saves a verified local WAV before deleting that voice. Uncertain provider outcomes require review before retrying."); Layout.fillWidth: true; implicitHeight: 100; wrapMode: TextEdit.Wrap; text: root.s.dialogue_text || ""; placeholderText: "Write dialogue to record with the selected candidate"; onTextChanged: if (activeFocus) root.studio.edit("dialogue_text", text) }
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Creates an addon-owned temporary cloud voice. After the local WAV is verified, that voice is deleted. Credits and account operations still apply." }
            NCButton { text: "Generate dialogue and clean up"; enabled: !root.s.busy && !!root.s.dialogue_text; onClicked: root.studio.act("dialogue") }
        }
    }
    NCDialog {
        id: loadCastDialog
        objectName: "voiceStudioCastLoadDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Load saved drafts?")
        description: qsTr("Replace current draft edits with the last locally saved cast? This does not generate voices or change saved recordings.")
        acceptText: qsTr("Load saved drafts"); acceptEnabled: !root.s.busy
        onAccepted: root.studio.act("load_cast", {confirmed: true})
    }
    NCDialog {
        id: removeCastDialog
        objectName: "voiceStudioCastRemoveDialog"
        property string characterId: ""
        property string characterName: ""
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Remove selected draft?")
        description: qsTr("Remove %1 from the saved cast? Existing recordings stay in the Voice Library. Unfinished generation jobs must be finished or resolved first.").arg(characterName)
        acceptText: qsTr("Remove draft"); acceptTone: "danger"; acceptEnabled: !root.s.busy
        onAccepted: root.studio.act("remove_character", {character_id: characterId, confirmed: true})
    }
}
