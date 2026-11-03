import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"

ColumnLayout {
    id: root
    required property var studio
    readonly property var s: studio.state
    spacing: 14
    NCCard {
        title: "ElevenLabs — Cloud"
        Layout.fillWidth: true
        ColumnLayout {
            Layout.fillWidth: true
            Label { text: root.s.cloud_status || "Not checked"; Layout.fillWidth: true; wrapMode: Text.Wrap }
            NCComboBox { toolTipText: qsTr("Use the API key from NC ElevenLabs settings, or a separate in-memory key for this Voice Studio session. The selection can be saved, but session-only key text is never written to settings."); Layout.fillWidth: true; model: ["Use NC ElevenLabs connection", "Session-only API key"]; currentIndex: root.s.key_source === "session" ? 1 : 0; onActivated: root.studio.edit("key_source", currentIndex ? "session" : "nc") }
            NCTextField { toolTipText: qsTr("ElevenLabs API key held only in this Voice Studio session and cleared when the addon closes. It authorizes paid cloud design and dialogue operations; Save settings does not store this key."); Layout.fillWidth: true; visible: root.s.key_source === "session"; echoMode: TextInput.Password; placeholderText: root.s.key_present ? "Session key set (not saved)" : "Enter API key for this session"; onTextEdited: root.studio.edit("session_key", text) }
            Label { text: "Voice Design model" }
            NCComboBox { toolTipText: qsTr("ElevenLabs Voice Design model used to create candidate voices: eleven_ttv_v3 or eleven_multilingual_ttv_v2. This is separate from the TTS model used for longer dialogue; cloud generation consumes account credits."); Layout.fillWidth: true; model: ["eleven_ttv_v3", "eleven_multilingual_ttv_v2"]; currentIndex: root.s.model_id === "eleven_multilingual_ttv_v2" ? 1 : 0; onActivated: root.studio.edit("model_id", currentText) }
            Label { text: "Longer-dialogue TTS model" }
            NCTextField { toolTipText: qsTr("ElevenLabs TTS model ID for longer dialogue, default eleven_multilingual_v2. Used after creating a temporary voice from a candidate; it does not select the Voice Design model or normal chat speech model."); Layout.fillWidth: true; text: root.s.tts_model || "eleven_multilingual_v2"; onTextEdited: root.studio.edit("tts_model", text) }
            NCButton { text: "Check ElevenLabs connection"; enabled: !root.s.busy; onClicked: root.studio.act("check_cloud") }
        }
    }
    NCCard {
        title: "VoiceStudio — Local (optional)"
        Layout.fillWidth: true
        ColumnLayout {
            Layout.fillWidth: true
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Install and start VoiceStudio yourself when ready. NC connects to the separate installation; it does not install packages, download models, or launch the service." }
            NCTextField { toolTipText: qsTr("Address of your separately running VoiceStudio service. Only loopback HTTP URLs such as http://127.0.0.1:3900 are accepted, without a path, query or credentials. NC does not install packages, download models or launch this service."); Layout.fillWidth: true; text: root.s.local_url || "http://127.0.0.1:3900"; enabled: !root.s.busy; onTextEdited: root.studio.edit("local_url", text) }
            NCButton { text: "Check local connection"; enabled: !root.s.busy; onClicked: root.studio.act("check_local") }
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: root.s.local_status || "Not connected" }
            Repeater {
                model: root.s.engines || []
                Label { required property var modelData; Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData.label + " · " + modelData.instruction_mode + " · " + (modelData.ready ? "loaded" : "load manually in VoiceStudio") }
            }
            Label { text: "Local generation language code" }
            NCTextField { toolTipText: qsTr("Language code sent to the selected local engine, such as en. It guides speech generation rather than translating the sample text. Supported languages depend on the loaded engine; OmniVoice accent tags require en or English."); Layout.fillWidth: true; text: root.s.language || "en"; onTextEdited: root.studio.edit("language", text) }
        }
    }
    NCCard {
        title: "Local collection"
        Layout.fillWidth: true
        ColumnLayout {
            Layout.fillWidth: true
            Label { text: root.s.destination || ""; Layout.fillWidth: true; wrapMode: Text.WrapAnywhere }
            Label { text: "Validated WAVs, unique filenames. Tests are stored separately. Existing files are never overwritten."; Layout.fillWidth: true; wrapMode: Text.Wrap }
            NCButton { text: "Save settings"; enabled: !root.s.busy; onClicked: root.studio.act("save_settings") }
        }
    }
    NCCard {
        title: "Temporary cloud voices"
        Layout.fillWidth: true
        ColumnLayout {
            Layout.fillWidth: true
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Only longer ElevenLabs dialogue creates a temporary voice. Cleanup follows verified local saving; preview and local jobs have nothing to delete." }
            Repeater {
                model: root.s.cleanup_records || []
                NCCard {
                    id: cleanupRow
                    required property var modelData
                    Layout.fillWidth: true
                    title: modelData.name
                    Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData.name + " · " + modelData.state + (modelData.error ? " · " + modelData.error : "") }
                    NCButton { text: "Retry cleanup"; enabled: !root.s.busy && modelData.state === "cleanup_pending"; onClicked: root.studio.act("cleanup", {id: modelData.id}) }
                    Label { Layout.fillWidth: true; wrapMode: Text.Wrap; visible: modelData.state === "unknown" || modelData.state === "creation_intent"; text: "Creation outcome unknown. Review your ElevenLabs account; NC will not guess a voice ID or create another automatically." }
                    Label { Layout.fillWidth: true; wrapMode: Text.Wrap; visible: modelData.state === "synthesis_unknown" || modelData.state === "synthesis_intent"; text: "Dialogue outcome uncertain. Check ElevenLabs generation history; NC will not repeat this paid request automatically." }
                    NCCheckBox { toolTipText: qsTr("Consent to discard unsaved dialogue and permanently delete this exact tracked temporary voice from the connected ElevenLabs account. Checking alone does not delete it; Delete tracked temporary voice performs deletion. This cannot recover unverified dialogue or refund generation credits."); id: discardConsent; visible: !!cleanupRow.modelData.voice_id && !cleanupRow.modelData.saved_path && cleanupRow.modelData.state !== "discarded"; text: "Discard unsaved dialogue and delete this temporary voice" }
                    NCButton { visible: discardConsent.visible; text: "Delete tracked temporary voice"; enabled: !root.s.busy && discardConsent.checked; onClicked: root.studio.act("discard_cloud", {id: cleanupRow.modelData.id, confirmed: true}) }
                }
            }
        }
    }
}
