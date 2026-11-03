pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../theme" as Theme
import "OrbSensoryLayout.js" as OrbLayout

ColumnLayout {
    id: root
    objectName: "orbSensorySettings"
    required property var bridge
    property var controls: []
    property string selectedTab: "setup"
    readonly property string captureScope: {
        for (let control of root.controls) {
            if (OrbLayout.localId(control) === "companion_orb_capture_scope_combo")
                return String(control.value || "window")
        }
        return "window"
    }
    readonly property var tabs: [
        {key: "setup", label: qsTr("Setup")},
        {key: "watches", label: qsTr("Watches")},
        {key: "behavior", label: qsTr("Behavior")},
        {key: "prompts", label: qsTr("Prompts")},
        {key: "desktop_map", label: qsTr("Desktop map")},
        {key: "actions", label: qsTr("Actions")},
        {key: "advanced", label: qsTr("Advanced")}
    ]
    readonly property var cards: [
        {key: "capture", tab: "setup", title: qsTr("What the Orb can see")},
        {key: "model", tab: "setup", title: qsTr("Vision model")},
        {key: "personality", tab: "behavior", title: qsTr("Orb personality rules")},
        {key: "triggers", tab: "behavior", title: qsTr("Response triggers")},
        {key: "rules", tab: "behavior", title: qsTr("Behavior rules"), wide: true,
         details: qsTr("Rule conditions and repetition")},
        {key: "reply_style", tab: "prompts", title: qsTr("Reply style"), wide: true,
         details: qsTr("Reset all reply styles")},
        {key: "supervisor", tab: "prompts", title: qsTr("Supervisor prompt"), wide: true,
         details: qsTr("Supervisor prompt preview")},
        {key: "source_guidance", tab: "prompts", title: qsTr("Source guidance"), wide: true,
         collapsed: true},
        {key: "scan", tab: "desktop_map", title: qsTr("Desktop map scanning"),
         details: qsTr("Detection tuning")},
        {key: "categories", tab: "desktop_map", title: qsTr("Desktop map content")},
        {key: "movement", tab: "desktop_map", title: qsTr("Movement and focus"), wide: true,
         details: qsTr("Movement tuning")},
        {key: "click", tab: "actions", title: qsTr("Confirmed clicks"),
         details: qsTr("Verification thresholds and help")},
        {key: "guidance", tab: "actions", title: qsTr("Visual guidance"),
         details: qsTr("Guidance help")},
        {key: "runtime", tab: "advanced", title: qsTr("Vision runtime"), wide: true},
        {key: "model_tuning", tab: "advanced", title: qsTr("Model tuning")},
        {key: "capture_details", tab: "advanced", title: qsTr("Capture details")},
        {key: "pipeline", tab: "advanced", title: qsTr("Vision pipeline"), wide: true},
        {key: "supervisor_status", tab: "advanced", title: qsTr("Supervisor flow and focus"),
         wide: true, collapsed: true},
        {key: "source_status", tab: "advanced", title: qsTr("Source diagnostics"),
         wide: true, collapsed: true},
        {key: "other", tab: "advanced", title: qsTr("Other settings"), wide: true}
    ]
    spacing: Theme.NCMetrics.space12

    // Only navigation state changes on tab switches, not descriptor models.
    // This preserves drafts and the established editors/confirmation dialogs.
    component Controls: NCLiveControlsGroup {
        Layout.fillWidth: true
        flat: true
        flatSingleGroup: true
        showRefresh: false
        onControlEdited: (controlId, value) => root.bridge.setRuntimeProviderControl(controlId, value)
        onActionTriggered: controlId => root.bridge.triggerRuntimeProviderAction(controlId)
        onActionWithPayload: (controlId, payload) => root.bridge.triggerRuntimeProviderActionWithPayload(controlId, payload)
    }

    Flow {
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space6
        Repeater {
            model: root.tabs
            delegate: NCTabButton {
                required property var modelData
                objectName: "orbSensoryTab_" + modelData.key
                tutorialBridge: root.bridge
                tutorialContext: ({workspace: "runtime", runtime_section: "vision", provider_kind: "vision",
                                   provider_id: "companion_orb_target", sensory_tab: String(modelData.key)})
                text: modelData.label
                checked: root.selectedTab === modelData.key
                onClicked: root.selectedTab = modelData.key
            }
        }
    }

    NCOrbWatchPanel {
        Layout.fillWidth: true
        visible: root.selectedTab === "watches"
        readRows: () => root.bridge.companionOrbWatchRows()
        onActionWithPayload: (controlId, payload) => {
            root.bridge.triggerRuntimeProviderActionWithPayload("companion_orb_overlay_tab::" + controlId, payload)
            refreshWatch()
        }
    }

    GridLayout {
        id: cardGrid
        Layout.fillWidth: true
        columns: width >= 1000 ? 2 : 1
        columnSpacing: Theme.NCMetrics.space12
        rowSpacing: Theme.NCMetrics.space12
        visible: root.selectedTab !== "watches"
        Repeater {
            model: root.cards
            delegate: NCCard {
                id: card
                required property var modelData
                readonly property var mainControls: OrbLayout.controlsFor(root.controls, modelData.key, false, root.captureScope)
                readonly property var detailControls: OrbLayout.controlsFor(root.controls, modelData.key, true, root.captureScope)
                property bool expanded: !Boolean(modelData.collapsed)
                property bool detailsExpanded: false
                objectName: "orbSensoryCard_" + modelData.key
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                Layout.columnSpan: modelData.wide ? cardGrid.columns : 1
                visible: root.selectedTab === modelData.tab
                         && (mainControls.length > 0 || detailControls.length > 0)
                title: modelData.title
                headerAccessory: RowLayout {
                    NCButton {
                        visible: Boolean(card.modelData.collapsed)
                        text: card.expanded ? qsTr("Hide") : qsTr("Show")
                        compact: true
                        onClicked: card.expanded = !card.expanded
                    }
                }
                Controls {
                    objectName: "orbSensoryControls_" + card.modelData.key + "_main"
                    visible: card.expanded && controls.length > 0
                    controls: card.mainControls
                }
                NCButton {
                    objectName: "orbSensoryDetails_" + card.modelData.key
                    visible: card.detailControls.length > 0
                    text: (card.detailsExpanded ? qsTr("Hide %1") : qsTr("Show %1"))
                          .arg(String(card.modelData.details || qsTr("details")))
                    compact: true
                    onClicked: card.detailsExpanded = !card.detailsExpanded
                }
                Controls {
                    objectName: "orbSensoryControls_" + card.modelData.key + "_details"
                    visible: card.detailsExpanded && controls.length > 0
                    controls: card.detailControls
                }
            }
        }
    }

    NCButton {
        visible: root.selectedTab === "prompts"
        text: sensoryPrompts.visible ? qsTr("Hide source prompt details") : qsTr("Show source prompt details")
        onClicked: root.showSourcePrompts = !root.showSourcePrompts
    }
    property bool showSourcePrompts: false
    NCSensoryPromptSettings {
        id: sensoryPrompts
        objectName: "orbSensorySourcePrompts"
        Layout.fillWidth: true
        visible: root.selectedTab === "prompts" && root.showSourcePrompts
        controller: root.bridge.sensoryPromptSettings
        showGeneralFields: false
        showContextFields: false
        showSourceFields: true
    }

    NCButton {
        visible: root.selectedTab !== "watches"
        text: qsTr("Refresh settings")
        compact: true
        onClicked: root.bridge.refreshRuntimeProviderSettings()
    }
}
