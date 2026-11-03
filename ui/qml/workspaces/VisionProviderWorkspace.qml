pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

ScrollView {
    id: root
    objectName: "visionProviderWorkspace"
    NCTutorialMenu { id: providerTutorials; bridge: root.bridge }

    required property var bridge
    readonly property string sharedAwarenessId: "shared_awareness"
    readonly property var activeProviders: bridge.activeVisionProviders || []
    readonly property string activeProvider: activeProviders.length > 0
                                                     ? String(activeProviders[0]) : sharedAwarenessId
    readonly property string viewedProvider: String(bridge.viewedVisionProvider || activeProvider)
    readonly property bool viewingSharedAwareness: viewedProvider === sharedAwarenessId
    readonly property bool providerOwnsPrompts: ["companion_orb_target", "spotify_sense",
        "screen", "clipboard", "webcam", "heart_rate"].indexOf(viewedProvider) >= 0
    property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
        bridge: root.bridge
        scrollView: root
        pageKey: "runtime:vision:" + root.viewedProvider
    }

    clip: true
    contentWidth: availableWidth

    background: Rectangle {
        color: Theme.NCTheme.windowRaised
        radius: Theme.NCMetrics.radiusLarge
        border.color: Theme.NCTheme.border
    }

    Component.onCompleted: {
        bridge.viewVisionProvider(viewedProvider)
        bridge.sensoryPromptSettings.viewSource(
                    viewedProvider === sharedAwarenessId ? "off" : viewedProvider)
    }
    onViewedProviderChanged: bridge.sensoryPromptSettings.viewSource(
                                 viewedProvider === sharedAwarenessId ? "off" : viewedProvider)

    function providerIsActive(providerId) {
        const normalized = String(providerId || "off")
        if (normalized === root.sharedAwarenessId)
            return Boolean(root.bridge.coreSettings.sensory_pingpong_enabled)
        if (!Boolean(root.bridge.coreSettings.sensory_pingpong_enabled))
            return false
        for (let index = 0; index < activeProviders.length; ++index) {
            if (String(activeProviders[index]) === normalized)
                return true
        }
        return false
    }

    function awarenessSchema() {
        return [
            {"key": "sensory_feedback_interval_seconds", "label": qsTr("Check-in interval"), "description": qsTr("Seconds between eligible background checks."), "toolTip": qsTr("Minimum spacing in seconds between eligible shared background checks. The runtime uses at least 2 seconds, and activity or pause policy can delay a check. Shorter spacing can cause more captures and model requests."), "type": "number"},
            {"key": "sensory_pingpong_history_depth", "label": qsTr("Sensory history depth"), "description": qsTr("Number of previous sensory turns available to the policy."), "toolTip": qsTr("Number of previous sensory turns included as context for background awareness. Higher depth carries more previous observations into the model prompt."), "type": "integer"},
            {"key": "sensory_allow_hidden_proactive_speech", "label": qsTr("Allow hidden proactive speech"), "description": qsTr("Permit a hidden awareness cycle to reach normal TTS when policy allows it."), "toolTip": qsTr("Allow eligible background observations to become spoken replies when speech is ready and the sensory policy permits it. Shared awareness and an enabled source are also required."), "type": "boolean"},
            {"key": "sensory_allow_hidden_visual_generation", "label": qsTr("Allow hidden visual generation"), "description": qsTr("Permit a hidden awareness cycle to request a visual reply."), "toolTip": qsTr("Allow an eligible background awareness cycle to request an image. Visual Reply must also be enabled; generation uses the active image provider and can add provider requests."), "type": "boolean"}
        ]
    }

    ColumnLayout {
        width: parent.width
        spacing: Theme.NCMetrics.space12

        NCCard {
            Layout.fillWidth: true
            Layout.margins: Theme.NCMetrics.space16
            Layout.bottomMargin: 0
            elevated: true
            title: qsTr("Vision and sensory providers")
            description: qsTr("Enable any combination of sensory sources. Select a card to inspect its settings; enabled sources participate together in the existing sensory pipeline.")
        }

        NCSensoryImageStatus {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space16
            Layout.rightMargin: Theme.NCMetrics.space16
            controller: root.bridge.sensoryImageStatus
        }

        GridLayout {
            id: providerGrid

            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space16
            Layout.rightMargin: Theme.NCMetrics.space16
            columns: width >= 1260 ? 3 : width >= 760 ? 2 : 1
            uniformCellWidths: true
            columnSpacing: Theme.NCMetrics.space8
            rowSpacing: Theme.NCMetrics.space8

            Repeater {
                model: root.bridge.visionProviderOptions
                delegate: Button {
                    id: visionButton
                        NCTutorialMarker { bridge: root.bridge; context: ({workspace: "runtime", runtime_section: "vision", provider_kind: "vision", provider_id: String(visionButton.modelData.id)}) }
                    required property var modelData
                    property bool isActive: root.providerIsActive(String(modelData.id))
                    property bool isViewed: String(modelData.id) === root.viewedProvider
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredWidth: 1
                    implicitHeight: 68
                    hoverEnabled: true
                    ToolTip.visible: hovered
                    ToolTip.text: String(modelData.description || "")
                    Accessible.name: qsTr("View %1 settings").arg(String(modelData.label))

                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusLarge
                        color: visionButton.isViewed ? Theme.NCTheme.surfaceSelected
                                                     : visionButton.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
                        border.width: visionButton.activeFocus || visionButton.isViewed
                                      ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                        border.color: visionButton.activeFocus ? Theme.NCTheme.focus
                                                             : visionButton.isViewed ? Theme.NCTheme.accent : Theme.NCTheme.border
                    }

                    contentItem: RowLayout {
                        spacing: Theme.NCMetrics.space12
                        Rectangle {
                            Layout.preferredWidth: 42
                            Layout.preferredHeight: 42
                            radius: Theme.NCMetrics.radiusMedium
                            color: visionButton.isViewed ? Theme.NCTheme.accentSoft : Theme.NCTheme.windowRaised
                            Label {
                                anchors.centerIn: parent
                                text: "VIS"
                                color: visionButton.isViewed ? Theme.NCTheme.accent : Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.microSize
                                font.weight: Theme.NCTypography.bold
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space2
                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    Layout.fillWidth: true
                                    text: String(visionButton.modelData.label)
                                    color: Theme.NCTheme.text
                                    font.pixelSize: Theme.NCTypography.labelSize
                                    font.weight: Theme.NCTypography.semibold
                                    elide: Text.ElideRight
                                }
                                NCStatusChip {
                                    visible: visionButton.isActive
                                    text: qsTr("Enabled")
                                    status: "active"
                                    compact: true
                                }
                                NCSwitch {
                                    objectName: "visionProviderSwitch_" + String(visionButton.modelData.id)
                                    toolTipText: String(visionButton.modelData.id) === root.sharedAwarenessId
                                        ? qsTr("Run shared background sensory checks for the enabled sources. Turning this off stops shared awareness and disables the source activation controls.")
                                        : qsTr("Include %1 in the background sensory pipeline alongside other enabled sources. Shared Awareness must be on; the source capture settings and permissions still apply.").arg(String(visionButton.modelData.label))
                                    enabled: String(visionButton.modelData.id) === root.sharedAwarenessId
                                             || Boolean(root.bridge.coreSettings.sensory_pingpong_enabled)
                                    checked: visionButton.isActive
                                    text: ""
                                    Accessible.name: visionButton.isActive
                                                     ? qsTr("Disable %1").arg(String(visionButton.modelData.label))
                                                     : qsTr("Enable %1").arg(String(visionButton.modelData.label))
                                    onClicked: {
                                        root.bridge.viewVisionProvider(String(visionButton.modelData.id))
                                        root.bridge.setVisionProviderEnabled(
                                                    String(visionButton.modelData.id),
                                                    !visionButton.isActive)
                                    }
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: String(visionButton.modelData.description || "")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                                maximumLineCount: 1
                                elide: Text.ElideRight
                            }
                        }
                    }

                    onClicked: root.bridge.viewVisionProvider(String(visionButton.modelData.id))
                    TapHandler {
                        acceptedButtons: Qt.RightButton
                        onTapped: providerTutorials.openFor(visionButton,
                            {workspace: "runtime", runtime_section: "vision", provider_kind: "vision",
                             provider_id: String(visionButton.modelData.id)})
                    }
                }
            }
        }

        NCProviderSettingsPanel {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space16
            Layout.rightMargin: Theme.NCMetrics.space16
            visible: !root.viewingSharedAwareness
            bridge: root.bridge
            kind: "vision"
            providerId: root.viewedProvider
            activeProviderId: root.providerIsActive(root.viewedProvider)
                              ? root.viewedProvider : root.activeProvider
            activateLabel: qsTr("Enable this sensory source")
            onActivateRequested: providerId => root.bridge.activateVisionProvider(providerId)
        }

        NCSettingsGroup {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space16
            Layout.rightMargin: Theme.NCMetrics.space16
            visible: root.viewingSharedAwareness
            title: qsTr("Shared Awareness Policy")
            description: qsTr("These shared rules apply after the enabled providers capture sensory context.")
            schema: root.awarenessSchema()
            values: root.bridge.coreSettings
            onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
        }

        NCSensoryPromptSettings {
            visible: !root.providerOwnsPrompts
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space16
            Layout.rightMargin: Theme.NCMetrics.space16
            controller: root.bridge.sensoryPromptSettings
            showGeneralFields: root.viewingSharedAwareness
            showContextFields: root.viewingSharedAwareness
            showSourceFields: !root.viewingSharedAwareness && !root.providerOwnsPrompts
        }

        Item { Layout.preferredHeight: Theme.NCMetrics.space4 }
    }
}
