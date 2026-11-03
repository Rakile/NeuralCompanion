pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "runtimeProviderSettingsPanel"

    required property var bridge
    required property string kind
    required property string providerId
    required property string activeProviderId
    property string activateLabel: qsTr("Make active")
    property bool includeVoiceTagRulesTab: false
    property string selectedSectionKey: ""
    signal activateRequested(string providerId)

    readonly property var settings: bridge.runtimeProviderSettings
    readonly property bool ownsSettings: String(settings.kind || "") === kind
                                                && String(settings.providerId || "") === providerId
    readonly property bool isActive: providerId === activeProviderId
    readonly property bool avatarProviderLocked: kind === "avatar"
                                                && bridge.avatarProviderChangeAllowed === false
    readonly property bool usesSectionTabs: kind === "tts"
    readonly property var sectionTabs: {
        if (!usesSectionTabs || !ownsSettings)
            return []
        const tabs = []
        const sections = settings.sections || []
        for (let index = 0; index < sections.length; ++index) {
            const section = String(sections[index])
            if (controlsFor(section).some(control => control.visible !== false))
                tabs.push({key: "section:" + section, label: section})
        }
        if (includeVoiceTagRulesTab)
            tabs.push({key: "voice-tag-rules", label: qsTr("Voice tag rules")})
        return tabs
    }
    readonly property string currentSectionKey: {
        for (let index = 0; index < sectionTabs.length; ++index) {
            if (sectionTabs[index].key === selectedSectionKey)
                return selectedSectionKey
        }
        return sectionTabs.length > 0 ? sectionTabs[0].key : ""
    }
    onProviderIdChanged: selectedSectionKey = ""
    onKindChanged: selectedSectionKey = ""
    readonly property var visionTest: bridge.visionProviderTest || ({})
    readonly property bool ownsVisionTest: kind === "vision"
                                                   && String(visionTest.providerId || "") === providerId
    readonly property bool settingsLiveInAddon: false
    readonly property bool isOrbTarget: kind === "vision" && providerId === "companion_orb_target"
    readonly property bool isSpotifySense: kind === "vision" && providerId === "spotify_sense"
    readonly property bool isTabbedVisionSource: kind === "vision"
        && ["screen", "clipboard", "webcam", "heart_rate"].indexOf(providerId) >= 0
    readonly property bool compactProviderLayout: providerId === "elevenlabs_tts"
    readonly property bool isVseeface: kind === "avatar" && providerId === "vseeface"
    readonly property var vseefaceCardControl: {
        const source = ownsSettings && isVseeface ? (settings.controls || []) : []
        for (let index = 0; index < source.length; ++index) {
            if (String(source[index].id).split("::").pop() === "btn_vseeface_card_collapse")
                return source[index]
        }
        return ({})
    }
    readonly property var vseefaceCardStates: vseefaceCardControl.value || ({})

    function visionTestTone() {
        const status = String(visionTest.status || "info")
        if (status === "ready")
            return "success"
        if (status === "error")
            return "error"
        if (status === "warning" || status === "waiting")
            return "warning"
        return "info"
    }

    function controlsFor(section) {
        const source = ownsSettings ? (settings.controls || []) : []
        const filtered = []
        for (let index = 0; index < source.length; ++index) {
            if (String(source[index].section || "Overview") === String(section))
                filtered.push(source[index])
        }
        return filtered
    }

    function sectionDescription(section) {
        if (!root.compactProviderLayout)
            return qsTr("Changes use the provider's established controller and saved settings contract.")
        const descriptions = ({
            "Connection": qsTr("API access and current connection status."),
            "Voice": qsTr("Choose a voice and the model's quality/latency balance."),
            "Delivery": qsTr("Fine-tune similarity, expression, stability, and speaking speed.")
        })
        return descriptions[String(section)] || ""
    }

    spacing: Theme.NCMetrics.space12

    NCCard {
        Layout.fillWidth: true
        elevated: true
        title: root.ownsSettings ? String(root.settings.label || root.providerId)
                                 : root.providerId.replace(/_/g, " ")
        description: root.ownsSettings
                     ? String(root.settings.description || qsTr("Runtime provider settings"))
                     : qsTr("Loading provider settings…")

        headerAccessory: RowLayout {
            spacing: Theme.NCMetrics.space8
            NCStatusChip {
                text: root.kind === "vision"
                      ? (root.providerId === "off"
                         ? qsTr("Sensory capture disabled")
                         : (root.isActive ? qsTr("Enabled source") : qsTr("Viewing settings")))
                      : (root.isActive ? qsTr("Active provider") : qsTr("Viewing settings"))
                status: root.kind === "vision" && root.providerId === "off"
                        ? "disconnected" : (root.isActive ? "active" : "info")
                compact: true
            }
            NCButton {
                visible: root.kind === "vision" && root.providerId !== "off"
                enabled: !Boolean(root.visionTest.inFlight)
                text: root.ownsVisionTest && Boolean(root.visionTest.inFlight)
                      ? qsTr("Testing…") : qsTr("Test capture")
                tone: "secondary"
                compact: true
                toolTipText: qsTr("Capture once through the registered sensory provider without calling an LLM.")
                onClicked: root.bridge.testVisionProvider(root.providerId)
            }
            NCButton {
                visible: !root.isActive
                text: root.activateLabel
                enabled: !root.avatarProviderLocked
                toolTipText: root.avatarProviderLocked
                             ? qsTr("Stop the chat engine before changing the avatar provider.") : ""
                tone: "primary"
                compact: true
                onClicked: root.activateRequested(root.providerId)
            }
        }

    }

    NCInlineMessage {
        objectName: "avatarProviderChangeNotice"
        Layout.fillWidth: true
        visible: root.avatarProviderLocked
        message: qsTr("Stop the chat engine before changing the avatar provider. You can still browse its settings.")
    }

    Flow {
        objectName: "providerSettingsSectionTabs"
        Layout.fillWidth: true
        visible: root.usesSectionTabs && root.sectionTabs.length > 0
        spacing: Theme.NCMetrics.space6
        Repeater {
            model: root.sectionTabs
            delegate: NCTabButton {
                required property var modelData
                objectName: "providerSettingsTab_" + modelData.key
                tutorialBridge: root.bridge
                tutorialContext: ({workspace: "runtime", provider_kind: root.kind, provider_id: root.providerId,
                                   runtime_section: "runtime", runtime_responsibility: root.kind === "tts" ? "voice" : "speech",
                                   subsection: String(modelData.key).replace(/^section:/, "")})
                text: modelData.label
                checked: root.currentSectionKey === modelData.key
                onClicked: root.selectedSectionKey = modelData.key
            }
        }
    }

    NCInlineMessage {
        Layout.fillWidth: true
        visible: root.ownsVisionTest && String(root.visionTest.status || "idle") !== "idle"
        tone: root.visionTestTone()
        title: String(root.visionTest.status || "") === "testing"
               ? qsTr("Testing sensory capture") : qsTr("Sensory capture result")
        message: String(root.visionTest.message || "")
    }

    Loader {
        Layout.fillWidth: true
        active: root.isOrbTarget && root.ownsSettings
        visible: active
        sourceComponent: NCOrbSensorySettings {
            bridge: root.bridge
            controls: root.settings.controls || []
        }
    }

    Loader {
        Layout.fillWidth: true
        active: root.isSpotifySense && root.ownsSettings
        visible: active
        sourceComponent: NCSpotifySensorySettings {
            bridge: root.bridge
            controls: root.settings.controls || []
        }
    }

    Loader {
        Layout.fillWidth: true
        active: root.isTabbedVisionSource && root.ownsSettings
        visible: active
        sourceComponent: NCVisionSourceSettings {
            bridge: root.bridge
            providerId: root.providerId
            controls: root.settings.controls || []
            sections: root.settings.sections || []
        }
    }

    Repeater {
        model: root.ownsSettings && !root.isSpotifySense && !root.isOrbTarget
               && !root.isTabbedVisionSource ? (root.settings.sections || []) : []
        delegate: NCLiveControlsGroup {
            id: sectionGroup
            required property var modelData
            objectName: "providerSettingsSection_" + String(sectionGroup.modelData)
            Layout.fillWidth: true
            // Keep editors alive when switching tabs, including unsaved input.
            visible: controls.length > 0 && (!root.usesSectionTabs
                     || root.currentSectionKey === "section:" + String(sectionGroup.modelData))
            title: String(sectionGroup.modelData)
            legacyPlacement: root.isOrbTarget
            cardsCollapsible: root.isVseeface && Boolean(root.vseefaceCardControl.id)
            cardCollapseState: root.vseefaceCardStates
            layoutSection: root.isVseeface
                           ? (String(sectionGroup.modelData) === "Provider settings" ? "Overview" : String(sectionGroup.modelData))
                           : ""
            onCardCollapseEdited: (card, collapsed) => root.bridge.triggerRuntimeProviderActionWithPayload(
                String(root.vseefaceCardControl.id), {card: card, collapsed: collapsed})
            description: root.usesSectionTabs ? "" : root.sectionDescription(sectionGroup.modelData)
            controls: root.controlsFor(sectionGroup.modelData)
            flatSingleGroup: root.usesSectionTabs || root.compactProviderLayout || root.isVseeface
            showRefresh: !root.compactProviderLayout
            onControlEdited: (controlId, value) => root.bridge.setRuntimeProviderControl(controlId, value)
            onActionTriggered: controlId => root.bridge.triggerRuntimeProviderAction(controlId)
            onActionWithPayload: (controlId, payload) => root.bridge.triggerRuntimeProviderActionWithPayload(controlId, payload)
            onRefreshRequested: root.bridge.refreshRuntimeProviderSettings()
        }
    }

    NCCard {
        Layout.fillWidth: true
        visible: root.ownsSettings && !Boolean(root.settings.hasSettings)
                 && root.settingsLiveInAddon
        title: qsTr("Settings remain in the addon")
        description: root.providerId === "companion_orb_target"
                     ? qsTr("Open the Companion Orb addon to configure its modes and actions.")
                     : qsTr("Open the Spotify Sense addon to configure connection and commentary behavior.")
    }
}
