pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "visionSourceSettings"
    required property var bridge
    required property string providerId
    property var controls: []
    property var sections: []
    property string selectedTab: "setup"
    readonly property var tabs: [
        {key: "setup", label: qsTr("Setup")},
        {key: "prompts", label: qsTr("Prompts")},
        {key: "advanced", label: qsTr("Advanced")}
    ]
    spacing: Theme.NCMetrics.space12
    onProviderIdChanged: selectedTab = "setup"

    function controlsFor(section) {
        return root.controls.filter(control => String(control.section || "Overview") === section)
    }

    // Preserve the existing core-setting bindings as well as the addon controls.
    function screenSchema() {
        return [
            {"key": "screen_source_capture_screen_index", "toolTip": qsTr("Monitor captured by Screen Source. Select a screen from the currently available displays; this is separate from the window on which NC is displayed."), "label": qsTr("Screen selection"), "description": qsTr("Choose the monitor used by the existing Screen Source capture service."), "type": "choice", "options": root.bridge.screenOptions},
            {"key": "screen_source_auto_attach_next_user_turn", "toolTip": qsTr("Queue a fresh Screen Source image for the next user message when this attachment path is used. This does not enable continuous screen capture."), "label": qsTr("Attach fresh screen to next user turn"), "description": qsTr("Use the existing screen-source attachment queue for the next message."), "type": "boolean"}
        ]
    }

    Flow {
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space6
        Repeater {
            model: root.tabs
            delegate: NCTabButton {
                required property var modelData
                objectName: "visionSourceTab_" + modelData.key
                tutorialBridge: root.bridge
                tutorialContext: ({workspace: "runtime", runtime_section: "vision", provider_kind: "vision",
                                   provider_id: root.providerId, sensory_tab: String(modelData.key)})
                text: modelData.label
                checked: root.selectedTab === modelData.key
                onClicked: root.selectedTab = modelData.key
            }
        }
    }

    // Toggle visibility, not the model, so tab changes cannot recreate editors.
    Repeater {
        model: root.sections
        delegate: NCLiveControlsGroup {
            required property var modelData
            objectName: "visionSourceControls_" + String(modelData)
            Layout.fillWidth: true
            visible: root.selectedTab === "setup" && controls.length > 0
            title: String(modelData)
            flatSingleGroup: true
            showRefresh: false
            controls: root.controlsFor(String(modelData))
            onControlEdited: (controlId, value) => root.bridge.setRuntimeProviderControl(controlId, value)
            onActionTriggered: controlId => root.bridge.triggerRuntimeProviderAction(controlId)
            onActionWithPayload: (controlId, payload) => root.bridge.triggerRuntimeProviderActionWithPayload(controlId, payload)
        }
    }

    // Do not instantiate core screen settings for providers that do not use them.
    Loader {
        Layout.fillWidth: true
        active: root.providerId === "screen"
        visible: active && root.selectedTab === "setup"
        sourceComponent: NCSettingsGroup {
            objectName: "visionSourceScreenPolicy"
            title: qsTr("Shared screen policy")
            description: qsTr("Monitor selection stays beside the Screen provider settings.")
            schema: root.screenSchema()
            values: root.bridge.coreSettings
            onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
        }
    }

    NCSensoryPromptSettings {
        Layout.fillWidth: true
        visible: root.selectedTab === "prompts"
        controller: root.bridge.sensoryPromptSettings
        showGeneralFields: false
        showContextFields: false
        sourceFieldGroup: "prompts"
        showSourceToggle: false
        showPreview: false
    }

    NCSensoryPromptSettings {
        Layout.fillWidth: true
        visible: root.selectedTab === "advanced"
        controller: root.bridge.sensoryPromptSettings
        showGeneralFields: false
        showContextFields: false
        sourceFieldGroup: "advanced"
        showSourceToggle: false
    }

    NCButton {
        visible: root.selectedTab === "setup"
        text: qsTr("Refresh settings")
        compact: true
        onClicked: root.bridge.refreshRuntimeProviderSettings()
    }
}
