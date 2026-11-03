pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "spotifySensorySettings"
    required property var bridge
    property var controls: []
    property string selectedTab: "awareness_music"
    readonly property var tabs: [
        {key: "awareness_music", label: qsTr("Awareness")},
        {key: "awareness_song_changes", label: qsTr("Song changes")},
        {key: "hidden_presets", label: qsTr("Presets")},
        {key: "hidden_quick_styles", label: qsTr("Quick styles")},
        {key: "hidden_response_prompts", label: qsTr("Response prompts")},
        {key: "hidden_source_guidance", label: qsTr("Source guidance")}
    ]
    spacing: Theme.NCMetrics.space12

    function controlsFor(key) {
        return root.controls.filter(control => String(control.groupKey || "") === key)
    }

    NCButton {
        text: qsTr("Open Spotify Sense addon")
        onClicked: root.bridge.openAddonWorkspaceSection("spotify_sense_tab", "Overview")
    }

    Flow {
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space6
        Repeater {
            model: root.tabs
            delegate: NCTabButton {
                required property var modelData
                objectName: "spotifySensoryTab_" + modelData.key
                tutorialBridge: root.bridge
                tutorialContext: ({workspace: "runtime", runtime_section: "vision", provider_kind: "vision",
                                   provider_id: "spotify_sense", sensory_tab: String(modelData.key)})
                text: modelData.label
                checked: root.selectedTab === modelData.key
                onClicked: root.selectedTab = modelData.key
            }
        }
    }

    // Keep editors alive when switching tabs so unsaved drafts are preserved.
    Repeater {
        model: root.tabs
        delegate: NCLiveControlsGroup {
            required property var modelData
            objectName: "spotifySensoryPanel_" + modelData.key
            Layout.fillWidth: true
            visible: root.selectedTab === modelData.key
            title: modelData.label
            controls: root.controlsFor(modelData.key)
            onControlEdited: (controlId, value) => root.bridge.setRuntimeProviderControl(controlId, value)
            onActionTriggered: controlId => root.bridge.triggerRuntimeProviderAction(controlId)
            onActionWithPayload: (controlId, payload) => root.bridge.triggerRuntimeProviderActionWithPayload(controlId, payload)
            onRefreshRequested: root.bridge.refreshRuntimeProviderSettings()
        }
    }

    NCSensoryPromptSettings {
        Layout.fillWidth: true
        visible: root.selectedTab === "hidden_source_guidance"
        controller: root.bridge.sensoryPromptSettings
        showGeneralFields: false
        showContextFields: false
        showSourceFields: true
    }
}
