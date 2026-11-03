pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

ColumnLayout {
    id: root
    required property var bridge
    required property var controller
    readonly property var state: controller ? controller.state : ({})
    readonly property var persona: bridge.activeQuickPersona || ({})
    readonly property var live: bridge.personaState || ({})
    readonly property bool hasPersona: !!persona.id
    readonly property string personaId: String(persona.id || "")
    readonly property string personaName: String(persona.name || qsTr("current session"))
    readonly property var overrides: persona.overrides || ({})
    readonly property string assignedVoice: hasPersona ? String(overrides.liquidai_tts_voice || "") : String(live.liquidaiVoice || state.provider_voice || "")
    readonly property string assignedLanguage: hasPersona ? String(overrides.liquidai_tts_language || "") : String(live.liquidaiLanguage || state.provider_language || "")
    readonly property var voiceOptions: state.voice_options || []
    readonly property var languageOptions: state.language_options || []
    readonly property var voiceChoices: (hasPersona ? [{value: "", label: qsTr("Use provider default")}]: []).concat(voiceOptions)
    readonly property var languageChoices: (hasPersona ? [{value: "", label: qsTr("Use provider default")}]: []).concat(languageOptions)
    property string selectionOwner: ""
    property string savedVoice: ""
    property string savedLanguage: ""
    property string draftVoice: ""
    property string draftLanguage: ""
    property string message: ""
    readonly property bool changed: draftVoice !== assignedVoice || draftLanguage !== assignedLanguage
    readonly property bool validSelection: voiceChoices.some(v => v.value === draftVoice) && languageChoices.some(v => v.value === draftLanguage)
    spacing: Theme.NCMetrics.space12

    function synchronize(force) {
        if (force || selectionOwner !== personaId || savedVoice !== assignedVoice || savedLanguage !== assignedLanguage) {
            selectionOwner = personaId
            savedVoice = assignedVoice
            savedLanguage = assignedLanguage
            draftVoice = assignedVoice
            draftLanguage = assignedLanguage
            message = ""
        }
    }
    function assignedLabel(options, value, providerValue) {
        if (!value && hasPersona) {
            const inherited = options.find(v => v.value === providerValue)
            return qsTr("Provider default: %1").arg(inherited ? inherited.label : providerValue)
        }
        const option = options.find(v => v.value === value)
        return option ? option.label : qsTr("Unavailable: %1").arg(value)
    }
    Component.onCompleted: synchronize(true)
    onVisibleChanged: if (visible) synchronize(true)
    Connections {
        target: root.controller
        function onChanged() { root.synchronize(false) }
    }
    Connections {
        target: root.bridge
        function onPersonaChanged() { root.synchronize(false) }
        function onQuickPersonaChanged() { root.synchronize(false) }
    }

    NCCard {
        Layout.fillWidth: true
        title: qsTr("LiquidAI voice")
        description: qsTr("Choose a built-in voice or installed LoRA and speech language for this persona.")
        Label {
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: qsTr("Assigned to %1").arg(root.personaName)
            color: Theme.NCTheme.success; font.pixelSize: Theme.NCTypography.captionSize
        }
        Label {
            objectName: "personaLiquidAssignedVoice"
            Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; font.bold: true
            text: root.assignedLabel(root.voiceOptions, root.assignedVoice, String(root.state.provider_voice || ""))
            color: Theme.NCTheme.text
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: qsTr("Speech language: %1").arg(root.assignedLabel(root.languageOptions, root.assignedLanguage, String(root.state.provider_language || "")))
            color: Theme.NCTheme.textSecondary
        }
        Label { text: qsTr("Voice"); color: Theme.NCTheme.textSecondary }
        NCComboBox {
            objectName: "personaLiquidVoiceSelector"
            Layout.fillWidth: true; label: qsTr("LiquidAI voice")
            model: root.voiceChoices; textRole: "label"; valueRole: "value"
            currentIndex: root.voiceChoices.findIndex(v => v.value === root.draftVoice)
            displayText: currentIndex < 0 ? qsTr("Unavailable saved voice: %1").arg(root.draftVoice) : currentText
            enabled: Boolean(root.state.available) && !root.state.busy
            toolTipText: qsTr("Installed LoRA voices may be trained for a specific language. Choose a compatible speech language; this setting does not translate the reply.")
            onActivated: { root.draftVoice = String(currentValue); root.message = "" }
        }
        Label { text: qsTr("Speech language"); color: Theme.NCTheme.textSecondary }
        NCComboBox {
            objectName: "personaLiquidLanguageSelector"
            Layout.fillWidth: true; label: qsTr("LiquidAI speech language")
            model: root.languageChoices; textRole: "label"; valueRole: "value"
            currentIndex: root.languageChoices.findIndex(v => v.value === root.draftLanguage)
            displayText: currentIndex < 0 ? qsTr("Unavailable saved language: %1").arg(root.draftLanguage) : currentText
            enabled: Boolean(root.state.available) && !root.state.busy
            toolTipText: qsTr("Language used to synthesize speech. It does not translate text or change the conversation language. LoRA voices may require the language they were trained on.")
            onActivated: { root.draftLanguage = String(currentValue); root.message = "" }
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: qsTr("Selections are drafts until you apply them. LoRA voices may require their training language; speech language does not translate replies.")
            color: Theme.NCTheme.textSecondary; font.pixelSize: Theme.NCTypography.captionSize
        }
        Flow {
            Layout.fillWidth: true; spacing: 8
            NCButton {
                objectName: "personaLiquidRefresh"
                text: qsTr("Refresh voices")
                enabled: Boolean(root.state.available) && !root.state.busy
                onClicked: { root.message = ""; if (root.controller) root.controller.act("refresh", {}) }
            }
            NCButton {
                objectName: "personaLiquidApply"
                text: root.hasPersona ? qsTr("Apply to Persona") : qsTr("Apply to session")
                tone: "primary"
                enabled: root.changed && root.validSelection && Boolean(root.state.available) && !root.state.busy
                onClicked: {
                    if (root.bridge.assignPersonaLiquidVoice(root.selectionOwner, root.draftVoice, root.draftLanguage))
                        root.message = qsTr("Voice saved for %1.").arg(root.personaName)
                }
            }
            NCButton {
                objectName: "personaLiquidOpenSettings"
                text: qsTr("Open LiquidAI settings")
                onClicked: root.bridge.openTechnicalRulesProvider("tts", "liquidai")
            }
        }
    }
    Label {
        objectName: "personaLiquidStatus"
        Layout.fillWidth: true; wrapMode: Text.Wrap
        text: root.message || String(root.state.status || "")
        color: Boolean(root.state.available) ? Theme.NCTheme.textSecondary : Theme.NCTheme.warning
    }
}
