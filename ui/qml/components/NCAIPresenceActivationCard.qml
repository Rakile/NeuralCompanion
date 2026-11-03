pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root

    property bool addonLoaded: false
    property var enabledControl: ({})
    property var modeControl: ({})
    property var styleControl: ({})
    property var statusControl: ({})
    property var showAction: ({})
    property var silkAction: ({})
    property var fullscreenAction: ({})
    property var floatingAction: ({})

    readonly property bool presenceEnabled: Boolean(enabledControl.value)
    readonly property string displayMode: String(modeControl.value || "off")
    readonly property string visualStyle: String(styleControl.value || "neural_network_pulse")
    readonly property bool presenceRunning: addonLoaded && presenceEnabled && displayMode !== "off"

    signal controlEdited(string controlId, var value)
    signal actionTriggered(string controlId)

    function optionIndex(options, value) {
        for (let index = 0; index < options.length; ++index) {
            if (String(options[index].value) === String(value))
                return index
        }
        return -1
    }

    function optionLabel(options, value) {
        const index = optionIndex(options, value)
        return index >= 0 ? String(options[index].label || value) : String(value || qsTr("Off"))
    }

    title: qsTr("AI Presence activation")
    description: !root.addonLoaded
                 ? qsTr("The addon is not loaded in this session. Enable it for the next restart first.")
                 : root.presenceRunning
                   ? qsTr("AI Presence is active in %1 mode.").arg(root.optionLabel(root.modeControl.options || [], root.displayMode))
                   : qsTr("Choose where Presence should appear, then start it or activate the recommended Silk Threads style.")
    selected: root.presenceRunning
    elevated: true

    headerAccessory: NCStatusChip {
        text: !root.addonLoaded ? qsTr("ADDON NOT LOADED")
              : root.presenceRunning ? qsTr("ACTIVE")
              : root.presenceEnabled ? qsTr("ENABLED · HIDDEN") : qsTr("PRESENCE OFF")
        status: !root.addonLoaded ? "warning"
                : root.presenceRunning ? "active"
                : root.presenceEnabled ? "warning" : "disconnected"
        compact: true
    }

    GridLayout {
        Layout.fillWidth: true
        columns: width >= 820 ? 2 : 1
        columnSpacing: Theme.NCMetrics.space12
        rowSpacing: Theme.NCMetrics.space12

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 150
            radius: Theme.NCMetrics.radiusMedium
            color: root.presenceRunning
                   ? Theme.NCTheme.withAlpha(Theme.NCTheme.accent, 0.09)
                   : Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.borderWidth
            border.color: root.presenceRunning ? Theme.NCTheme.accent : Theme.NCTheme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space16
                spacing: Theme.NCMetrics.space8

                Label {
                    text: root.presenceRunning ? qsTr("Presence runtime active") : qsTr("Turn on AI Presence")
                    color: Theme.NCTheme.text
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.headingSize
                    font.weight: Theme.NCTypography.semibold
                }

                NCSwitch {
                    enabled: root.addonLoaded && Boolean(root.enabledControl.enabled)
                    text: checked ? qsTr("AI Presence enabled") : qsTr("Enable AI Presence")
                    toolTipText: String(root.enabledControl.toolTip || root.enabledControl.description || qsTr("Run AI Presence using the selected screen mode. A visible screen mode is also required."))
                    checked: root.presenceEnabled
                    onClicked: root.controlEdited(String(root.enabledControl.id || ""), checked)
                }

                Label {
                    Layout.fillWidth: true
                    text: qsTr("This master switch enables the visualizer. A visible screen mode is also required before it appears.")
                    color: Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 150
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space16
                spacing: Theme.NCMetrics.space8

                Label {
                    text: qsTr("Where it appears")
                    color: Theme.NCTheme.text
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.labelSize
                    font.weight: Theme.NCTypography.semibold
                }

                NCComboBox {
                    Layout.fillWidth: true
                    enabled: root.addonLoaded && Boolean(root.modeControl.enabled)
                    label: qsTr("AI Presence screen mode")
                    toolTipText: String(root.modeControl.toolTip || root.modeControl.description || qsTr("Choose Off, Fullscreen, Floating Window, or Both. AI Presence must be enabled before the visualizer appears."))
                    model: root.modeControl.options || []
                    textRole: "label"
                    valueRole: "value"
                    currentIndex: root.optionIndex(model, root.displayMode)
                    onActivated: root.controlEdited(String(root.modeControl.id || ""), currentValue)
                }

                Label {
                    Layout.fillWidth: true
                    text: root.displayMode === "off"
                          ? qsTr("Off hides the visualizer. Start and show Presence will select Floating Window automatically.")
                          : qsTr("You can adjust window behavior and placement on the Display page.")
                    color: Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space8

        Label {
            text: qsTr("Choose a visual style")
            color: Theme.NCTheme.text
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.labelSize
            font.weight: Theme.NCTypography.semibold
        }

        GridLayout {
            Layout.fillWidth: true
            columns: width >= 720 ? 3 : 1
            columnSpacing: Theme.NCMetrics.space8
            rowSpacing: Theme.NCMetrics.space8

            NCButton {
                Layout.fillWidth: true
                enabled: root.addonLoaded && Boolean(root.styleControl.enabled)
                text: qsTr("Neural Pulse")
                tone: root.visualStyle === "neural_network_pulse" ? "primary" : "quiet"
                toolTipText: qsTr("A pulsing neural field driven by state, voice, music, and mood.")
                onClicked: root.controlEdited(String(root.styleControl.id || ""), "neural_network_pulse")
            }
            NCButton {
                Layout.fillWidth: true
                enabled: root.addonLoaded && Boolean(root.silkAction.enabled)
                text: qsTr("Activate Silk Threads · Recommended")
                tone: root.visualStyle === "living_voice_thread" ? "primary" : "quiet"
                toolTipText: qsTr("Activates the GPU Living Voice Thread renderer with the Silk ribbon variation and voice-reactive colors.")
                onClicked: root.actionTriggered(String(root.silkAction.id || ""))
            }
            NCButton {
                Layout.fillWidth: true
                enabled: root.addonLoaded && Boolean(root.styleControl.enabled)
                text: qsTr("Silk Drift")
                tone: root.visualStyle === "silk_drift" ? "primary" : "quiet"
                toolTipText: qsTr("A calmer flowing style with less detailed thread motion.")
                onClicked: root.controlEdited(String(root.styleControl.id || ""), "silk_drift")
            }
        }

        NCInlineMessage {
            Layout.fillWidth: true
            tone: "info"
            title: qsTr("Silk Threads keeps all advanced tuning")
            message: qsTr("Open the Silk Threads page to adjust every motion, audio, color, physics, placement, and performance control. You can load built-in presets or save and delete your own presets there.")
        }

        GridLayout {
            Layout.fillWidth: true
            columns: width >= 700 ? 3 : 1
            columnSpacing: Theme.NCMetrics.space8
            rowSpacing: Theme.NCMetrics.space8

            NCButton {
                Layout.fillWidth: true
                enabled: root.addonLoaded && Boolean(root.showAction.enabled)
                text: qsTr("Start and show Presence")
                tone: "primary"
                toolTipText: qsTr("Enables AI Presence and uses Floating Window if the current screen mode is Off.")
                onClicked: root.actionTriggered(String(root.showAction.id || ""))
            }
            NCButton {
                Layout.fillWidth: true
                enabled: root.addonLoaded && Boolean(root.fullscreenAction.enabled)
                text: qsTr("Preview fullscreen")
                toolTipText: qsTr("Open a temporary fullscreen preview of the current visual style.")
                onClicked: root.actionTriggered(String(root.fullscreenAction.id || ""))
            }
            NCButton {
                Layout.fillWidth: true
                enabled: root.addonLoaded && Boolean(root.floatingAction.enabled)
                text: qsTr("Open floating window")
                toolTipText: qsTr("Enable AI Presence and show it as a floating desktop window.")
                onClicked: root.actionTriggered(String(root.floatingAction.id || ""))
            }
        }

        Label {
            Layout.fillWidth: true
            text: String(root.statusControl.value || "")
            color: root.presenceRunning ? Theme.NCTheme.success : Theme.NCTheme.textSecondary
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.captionSize
            wrapMode: Text.Wrap
            visible: text.length > 0
        }
    }
}
