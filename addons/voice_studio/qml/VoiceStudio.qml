import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

Control {
    id: root
    objectName: "voiceStudioWorkspace"
    required property var bridge
    property string currentSection: "Create Voices"
    property var voiceDetailsDrafts: ({})
    readonly property var state: {
        const controls = bridge.liveAddonControls || []
        for (let i = 0; i < controls.length; ++i)
            if (controls[i].id === "voice_studio_state") return controls[i].value || {}
        return {}
    }
    function edit(key, value) { bridge.setLiveAddonControl("vs_" + key, value) }
    function act(name, payload) { bridge.triggerLiveAddonActionWithPayload("vs_" + name, payload || {}) }
    palette.window: Theme.NCTheme.surface
    palette.base: Theme.NCTheme.window
    palette.button: Theme.NCTheme.surfaceRaised
    palette.text: Theme.NCTheme.text
    palette.windowText: Theme.NCTheme.text
    palette.buttonText: Theme.NCTheme.text
    palette.highlight: Theme.NCTheme.accent
    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.bodySize
    background: Rectangle { color: Theme.NCTheme.surface; radius: 10; border.color: Theme.NCTheme.border }
    Component.onCompleted: root.act("refresh")
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Voice Studio"; font.pixelSize: 23; font.bold: true; Layout.fillWidth: true }
            BusyIndicator { running: !!root.state.busy; visible: running; implicitWidth: 28; implicitHeight: 28 }
            NCButton { text: "Pause batch"; enabled: !!root.state.busy; onClicked: root.act("pause") }
            NCButton { text: "Stop"; onClicked: root.act("stop") }
        }
        Label { text: root.state.status || "Enable Voice Studio to begin."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.textSecondary }
        RowLayout {
            Layout.fillWidth: true
            NCTabButton { objectName: "voiceStudioCreateTab"; tutorialBridge: root.bridge; tutorialContext: ({workspace: "addons", addon: "voice_studio_tab", section: "Create Voices"}); Layout.fillWidth: true; Layout.preferredWidth: 1; text: "Create Voices"; checked: root.currentSection !== "Voice Library" && root.currentSection !== "Settings"; onClicked: root.currentSection = "Create Voices" }
            NCTabButton { objectName: "voiceStudioLibraryTab"; tutorialBridge: root.bridge; tutorialContext: ({workspace: "addons", addon: "voice_studio_tab", section: "Voice Library"}); Layout.fillWidth: true; Layout.preferredWidth: 1; text: "Voice Library"; checked: root.currentSection === "Voice Library"; onClicked: root.currentSection = "Voice Library" }
            NCTabButton { objectName: "voiceStudioSettingsTab"; tutorialBridge: root.bridge; tutorialContext: ({workspace: "addons", addon: "voice_studio_tab", section: "Settings"}); Layout.fillWidth: true; Layout.preferredWidth: 1; text: "Settings"; checked: root.currentSection === "Settings"; onClicked: root.currentSection = "Settings" }
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width
                spacing: 12
                Loader {
                    Layout.fillWidth: true
                    sourceComponent: root.currentSection === "Voice Library" ? libraryPage : root.currentSection === "Settings" ? settingsPage : createPage
                }
                NCCard {
                    Layout.fillWidth: true
                    visible: !!root.state.refinement
                    title: "Suggested refinement — original stays unchanged until applied"
                    ColumnLayout {
                        Layout.fillWidth: true
                        NCTextArea { toolTipText: qsTr("Read-only proposed refinement from the active NC language model. Review before choosing Use refinement; Keep original discards the suggestion. Applying a suggestion does not start speech generation."); Layout.fillWidth: true; readOnly: true; text: root.state.refinement || ""; wrapMode: TextEdit.Wrap }
                        RowLayout {
                            NCButton { text: "Use refinement"; enabled: !root.state.busy; onClicked: root.act("apply_refinement") }
                            NCButton { text: "Keep original"; enabled: !root.state.busy; onClicked: root.act("keep_original") }
                        }
                    }
                }
            }
        }
    }
    Component { id: createPage; CreateVoices { studio: root } }
    Component { id: libraryPage; VoiceLibrary { studio: root } }
    Component { id: settingsPage; VoiceStudioSettings { studio: root } }
}
