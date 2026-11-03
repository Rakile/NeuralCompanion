pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme
import "../../../addons/voice_studio/qml" as VoiceStudio

ColumnLayout {
    id: root
    required property var bridge
    readonly property var controller: bridge.personaVoice || null
    readonly property var state: controller ? controller.state : ({})
    readonly property var liveVoice: bridge.personaState || ({})
    readonly property bool liquid: String(bridge.selectedSpeechOutputBackend || liveVoice.ttsBackend || state.provider || "") === "liquidai"
    property bool ready: false
    readonly property var savedPersona: bridge.activeQuickPersona || ({})
    readonly property var assigned: savedPersona.id ? ({
        voicePath: String(savedPersona.voice_path || ""),
        voiceName: String(savedPersona.voice_path || "").replace(/\\/g, "/").split("/").pop(),
        useClonedVoice: savedPersona.use_cloned_voice !== false,
        activeQuickPersonaName: String(savedPersona.name || "")
    }) : liveVoice
    readonly property string personaName: String(assigned.activeQuickPersonaName || qsTr("current session"))
    readonly property string personaKey: String((bridge.activeQuickPersona || {}).id || personaName)
    property string selectionOwner: ""
    property string savedPath: ""
    property bool savedClone: true
    property string selectedPath: ""
    property bool useClone: true
    property string message: ""
    readonly property bool busy: Boolean(state.busy)
    readonly property var voices: state.voices || []
    readonly property var selected: voices.find(v => samePath(v.path, selectedPath)) || ({})
    readonly property var choices: [{label: qsTr("Provider default voice"), value: ""}].concat(
        voices.filter(v => v.valid && (!v.archived || samePath(v.path, selectedPath))).map(v => ({label: v.name, value: v.path})))
    readonly property bool changed: !samePath(selectedPath, String(assigned.voicePath || ""))
                                    || useClone !== Boolean(assigned.useClonedVoice)
                                    || !samePath(selectedPath, String(liveVoice.voicePath || ""))
                                    || useClone !== Boolean(liveVoice.useClonedVoice)
    spacing: Theme.NCMetrics.space12

    function pathKey(value) {
        let path = String(value || "").replace(/\\/g, "/").toLowerCase()
        const destination = String(state.destination || "").replace(/\\/g, "/").replace(/\/$/, "").toLowerCase()
        if (destination && path.indexOf("voices/") === 0) path = destination + path.slice(6)
        return path
    }
    function samePath(a, b) { return pathKey(a) === pathKey(b) }
    function synchronize() {
        if (liquid) return
        const path = String(assigned.voicePath || "")
        const cloned = Boolean(assigned.useClonedVoice)
        if (selectionOwner !== personaKey || !samePath(savedPath, path) || savedClone !== cloned) {
            selectionOwner = personaKey
            savedPath = path
            savedClone = cloned
            selectedPath = path
            useClone = cloned
            message = ""
        }
    }
    function choose(path) {
        selectedPath = String(path || "")
        useClone = selectedPath.length > 0
        message = qsTr("Preview selection only. The assigned voice is unchanged.")
    }
    function act(action, payload) {
        if (liquid) return
        message = ""
        if (controller) controller.act(action, payload || {})
    }
    function refresh() { act("refresh", {}) }
    Component.onCompleted: { ready = true; synchronize(); if (visible && !liquid) refresh() }
    onVisibleChanged: if (ready && visible && controller && !liquid) { synchronize(); refresh() }
    onLiquidChanged: if (ready && visible && !liquid) { synchronize(); refresh() }
    Connections {
        target: root.bridge
        function onPersonaChanged() { root.synchronize() }
        function onQuickPersonaChanged() { root.synchronize() }
    }
    Timer {
        interval: 750; repeat: true; running: root.visible && !root.liquid
        onTriggered: if (root.controller) root.controller.refreshState()
    }

    PersonaLiquidVoice {
        Layout.fillWidth: true
        visible: root.liquid
        bridge: root.bridge; controller: root.controller
    }

    NCCard {
        visible: !root.liquid
        Layout.fillWidth: true
        title: qsTr("Give your companion a voice")
        description: qsTr("Browse, listen, then choose a voice for this persona.")
        GridLayout {
            Layout.fillWidth: true
            columns: width >= 600 ? 2 : 1
            rowSpacing: 10; columnSpacing: 16
            ColumnLayout {
                Layout.fillWidth: true; spacing: 4
                Label { text: qsTr("Assigned to %1").arg(root.personaName); color: Theme.NCTheme.success; font.pixelSize: Theme.NCTypography.captionSize }
                Label {
                    objectName: "personaAssignedVoice"
                    Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
                    text: !root.assigned.useClonedVoice ? qsTr("Provider default voice")
                          : String(root.assigned.voiceName || qsTr("Provider default voice"))
                    color: Theme.NCTheme.text; font.bold: true
                }
                Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: root.savedPersona.id ? qsTr("Saved with this persona. Previews do not change it.") : qsTr("Current session voice. Save a quick persona to reuse it."); color: Theme.NCTheme.textSecondary; font.pixelSize: Theme.NCTypography.captionSize }
                Label {
                    Layout.fillWidth: true; wrapMode: Text.Wrap
                    visible: !root.samePath(root.assigned.voicePath, root.liveVoice.voicePath) || root.assigned.useClonedVoice !== root.liveVoice.useClonedVoice
                    text: qsTr("Conversation currently uses: %1").arg(root.liveVoice.useClonedVoice ? String(root.liveVoice.voiceName || qsTr("Provider default voice")) : qsTr("Provider default voice"))
                    color: Theme.NCTheme.warning; font.pixelSize: Theme.NCTypography.captionSize
                }
            }
            NCButton {
                objectName: "personaVoiceApply"
                Layout.maximumWidth: parent.width
                text: root.changed ? qsTr("Use this voice for %1").arg(root.personaName) : qsTr("Voice already assigned")
                tone: "primary"
                enabled: root.changed && !root.busy && (root.selectedPath === "" || Boolean(root.selected.valid))
                onClicked: {
                    if (root.bridge.assignPersonaVoice(root.selectedPath, root.useClone))
                        root.message = qsTr("Voice saved for %1.").arg(root.personaName)
                }
            }
        }
    }

    GridLayout {
        visible: !root.liquid
        Layout.fillWidth: true
        columns: width >= 780 ? 2 : 1
        columnSpacing: 12; rowSpacing: 12
        VoiceStudio.VoiceLibraryList {
            Layout.fillWidth: true; Layout.preferredWidth: 390; Layout.alignment: Qt.AlignTop
            voices: root.voices
            selectedPath: root.selectedPath
            assignedPath: String(root.assigned.voicePath || "")
            busy: root.busy
            available: Boolean(root.state.available)
            namePrefix: "personaVoice"
            pathsEqual: root.samePath
            showStudioLink: true
            onChoose: path => root.choose(path)
            onPlay: path => root.act("play_original", {reference: path})
            onRefresh: root.refresh()
            onOpenStudio: root.bridge.openAddonWorkspaceSection("voice_studio_tab", "Voice Library")
        }
        NCCard {
            Layout.fillWidth: true; Layout.preferredWidth: 500; Layout.alignment: Qt.AlignTop
            title: qsTr("Preview a voice")
            NCComboBox {
                toolTipText: qsTr("Choose the voice reference associated with this Persona. Compatible cloning providers use it when reference use is enabled; providers with fixed voices may use their own voice settings.")

                objectName: "personaVoiceSelector"
                Layout.fillWidth: true; label: qsTr("Voice to preview")
                model: root.choices; textRole: "label"; valueRole: "value"
                currentIndex: root.choices.findIndex(v => root.samePath(v.value, root.selectedPath))
                displayText: currentIndex < 0 ? qsTr("Saved reference unavailable — refresh or choose a voice") : currentText
                onActivated: root.choose(currentValue)
            }
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: String(root.selected.name || (root.selectedPath ? qsTr("Unavailable recording") : qsTr("Provider default voice"))); color: Theme.NCTheme.text; font.bold: true }
            Label {
                Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
                text: root.selectedPath ? String(root.selected.path || root.selectedPath) : qsTr("Uses the active provider's built-in voice. No reference recording to preview.")
                color: Theme.NCTheme.textMuted; font.pixelSize: Theme.NCTypography.captionSize
            }
            Flow {
                Layout.fillWidth: true; spacing: 8
                NCButton {
                    objectName: "personaVoicePlaySample"
                    text: qsTr("Play original sample")
                    enabled: !root.busy && Boolean(root.selected.valid)
                    onClicked: root.act("play_original", {reference: root.selected.path})
                }
                NCButton { objectName: "personaVoiceSampleStop"; text: qsTr("Stop"); enabled: Boolean(root.state.can_stop); onClicked: root.act("stop", {}) }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.NCTheme.borderSubtle }
            Label { text: qsTr("Try your own words"); color: Theme.NCTheme.text; font.bold: true }
            Label {
                objectName: "personaVoiceEngineStatus"
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: root.state.audition_ready ? qsTr("%1 loaded").arg(root.state.audition_backend_label || "Chatterbox") : qsTr("Load Chatterbox or Chatterbox Multilingual in Runtime → Text-to-speech to test your own text. Original recordings can still be played.")
                color: root.state.audition_ready ? Theme.NCTheme.success : Theme.NCTheme.warning
                font.pixelSize: Theme.NCTypography.captionSize
            }
            NCTextArea {
                toolTipText: qsTr("Text spoken when you audition the chosen voice reference. It is a voice test and is not added as a normal conversation message.")

                id: testText; objectName: "personaVoiceTestText"
                Layout.fillWidth: true; implicitHeight: 90; wrapMode: TextEdit.Wrap
                text: qsTr("Hello! What shall we create together today?")
                Accessible.name: qsTr("Text to speak")
            }
            Flow {
                Layout.fillWidth: true; spacing: 8
                NCButton {
                    objectName: "personaVoiceGenerate"
                    text: qsTr("Generate test"); tone: "primary"
                    enabled: !root.busy && Boolean(root.state.audition_ready) && Boolean(root.selected.valid) && testText.text.trim().length > 0
                    onClicked: root.act("test", {reference: root.selected.path, text: testText.text})
                }
                NCButton { objectName: "personaVoiceStop"; text: qsTr("Stop"); enabled: Boolean(root.state.can_stop); onClicked: root.act("stop", {}) }
            }
            ColumnLayout {
                Layout.fillWidth: true; visible: !!(root.state.test_result || {}).path
                Label {
                    Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
                    text: qsTr("Test reference: %1\nText: %2").arg(String((root.state.test_result || {}).reference || "")).arg(String((root.state.test_result || {}).text || ""))
                    color: Theme.NCTheme.textSecondary; font.pixelSize: Theme.NCTypography.captionSize
                }
                NCButton { text: qsTr("Play test"); enabled: !root.busy; onClicked: root.act("play_test", {}) }
            }
            NCSwitch {
                toolTipText: qsTr("Allow compatible TTS providers to use this Persona's selected reference audio. Off uses the provider's normal voice behavior; it does not remove the reference file.")

                objectName: "personaVoiceClone"
                Layout.fillWidth: true
                text: qsTr("Use this reference with compatible TTS providers")
                checked: root.useClone; enabled: !!root.selectedPath
                onClicked: root.useClone = checked
            }
            VoiceStudio.VoiceDetails {
                record: root.selected; busy: root.busy; namePrefix: "personaVoice"
                onAction: (name, payload) => root.act(name, payload)
            }

        }
    }
    Label {
        objectName: "personaVoiceStatus"
        visible: !root.liquid
        Layout.fillWidth: true; wrapMode: Text.Wrap
        text: root.message || String(root.state.status || "")
        color: Theme.NCTheme.textSecondary
    }
}
