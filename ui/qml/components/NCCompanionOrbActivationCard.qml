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
    property var statusControl: ({})
    property var showAction: ({})
    property var placementAction: ({})
    property var resetAction: ({})

    readonly property bool orbEnabled: Boolean(enabledControl.value)
    readonly property string displayMode: String(modeControl.value || "off")
    readonly property bool orbRunning: addonLoaded && orbEnabled && displayMode !== "off"
    readonly property string modeLabel: optionLabel(modeControl.options || [], displayMode)

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

    function modeExplanation(mode) {
        if (mode === "docked")
            return qsTr("The Orb stays visible at its home position and can move toward desktop targets.")
        if (mode === "interaction")
            return qsTr("The Orb appears while NeuralCompanion is listening, thinking, or speaking.")
        if (mode === "always")
            return qsTr("The Orb remains visible while NeuralCompanion is running.")
        return qsTr("The Orb is hidden. Choose a visible mode or press Start and show Orb.")
    }

    title: qsTr("Companion Orb activation")
    description: !root.addonLoaded
                 ? qsTr("The addon is not loaded in this session. Enable it for the next restart first.")
                 : root.orbRunning
                   ? qsTr("The desktop Orb is running in %1 mode.").arg(root.modeLabel)
                   : root.orbEnabled
                     ? qsTr("The Orb master switch is on, but its display mode is Off.")
                     : qsTr("The addon is loaded, but the desktop Orb is not running yet.")
    selected: root.orbRunning
    elevated: true

    headerAccessory: NCStatusChip {
        text: !root.addonLoaded ? qsTr("ADDON NOT LOADED")
              : root.orbRunning ? qsTr("ACTIVE · %1").arg(root.modeLabel.toUpperCase())
              : root.orbEnabled ? qsTr("ENABLED · HIDDEN") : qsTr("ORB OFF")
        status: !root.addonLoaded ? "warning"
                : root.orbRunning ? "active"
                : root.orbEnabled ? "warning" : "disconnected"
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
            Layout.minimumHeight: 152
            radius: Theme.NCMetrics.radiusMedium
            color: root.orbRunning
                   ? Theme.NCTheme.withAlpha(Theme.NCTheme.accent, 0.09)
                   : Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.borderWidth
            border.color: root.orbRunning ? Theme.NCTheme.accent : Theme.NCTheme.border

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space16
                spacing: Theme.NCMetrics.space16

                Rectangle {
                    Layout.preferredWidth: 76
                    Layout.preferredHeight: 76
                    radius: 38
                    color: root.orbRunning
                           ? Theme.NCTheme.withAlpha(Theme.NCTheme.accent, 0.18)
                           : Theme.NCTheme.surfaceRaised
                    border.width: root.orbRunning ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                    border.color: root.orbRunning ? Theme.NCTheme.accent : Theme.NCTheme.borderStrong

                    Rectangle {
                        anchors.centerIn: parent
                        width: 48
                        height: 48
                        radius: 24
                        color: "transparent"
                        border.width: 2
                        border.color: root.orbRunning ? Theme.NCTheme.accentStrong : Theme.NCTheme.textMuted

                        Rectangle {
                            anchors.centerIn: parent
                            width: 18
                            height: 18
                            radius: 9
                            color: root.orbRunning ? Theme.NCTheme.accent : Theme.NCTheme.textMuted
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8

                    Label {
                        Layout.fillWidth: true
                        text: root.orbRunning ? qsTr("Orb runtime active") : qsTr("Orb runtime inactive")
                        color: Theme.NCTheme.text
                        font.family: Theme.NCTypography.family
                        font.pixelSize: Theme.NCTypography.headingSize
                        font.weight: Theme.NCTypography.semibold
                    }

                    NCSwitch {
                        enabled: root.addonLoaded && Boolean(root.enabledControl.enabled)
                        text: checked ? qsTr("Companion Orb enabled") : qsTr("Start Companion Orb")
                        toolTipText: String(root.enabledControl.toolTip || root.enabledControl.description || qsTr("Start the desktop Companion Orb. Starting while visibility is Off selects Docked mode."))
                        checked: root.orbEnabled
                        onClicked: root.controlEdited(String(root.enabledControl.id || ""), checked)
                    }

                    Label {
                        Layout.fillWidth: true
                        text: qsTr("This is the master Orb switch. If visibility is Off, starting the Orb automatically selects Docked mode.")
                        color: Theme.NCTheme.textSecondary
                        font.family: Theme.NCTypography.family
                        font.pixelSize: Theme.NCTypography.captionSize
                        wrapMode: Text.Wrap
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 152
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space16
                spacing: Theme.NCMetrics.space8

                Label {
                    text: qsTr("Visibility mode")
                    color: Theme.NCTheme.text
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.labelSize
                    font.weight: Theme.NCTypography.semibold
                }

                NCComboBox {
                    Layout.fillWidth: true
                    enabled: root.addonLoaded && Boolean(root.modeControl.enabled)
                    label: qsTr("Companion Orb visibility mode")
                    toolTipText: String(root.modeControl.toolTip || root.modeControl.description || qsTr("Choose Off, Docked only, During interaction only, or Always visible. The master Orb switch must also be on."))
                    model: root.modeControl.options || []
                    textRole: "label"
                    valueRole: "value"
                    currentIndex: root.optionIndex(model, root.displayMode)
                    onActivated: root.controlEdited(String(root.modeControl.id || ""), currentValue)
                }

                Label {
                    Layout.fillWidth: true
                    text: root.modeExplanation(root.displayMode)
                    color: Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    NCInlineMessage {
        Layout.fillWidth: true
        visible: root.addonLoaded && root.orbEnabled && root.displayMode === "off"
        tone: "warning"
        title: qsTr("The Orb is enabled but hidden")
        message: qsTr("Select Docked, During interaction, or Always visible to display it.")
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space8

        GridLayout {
            id: actionGrid
            Layout.fillWidth: true
            columns: width >= 680 ? 3 : width >= 420 ? 2 : 1
            columnSpacing: Theme.NCMetrics.space8
            rowSpacing: Theme.NCMetrics.space8

            NCButton {
                Layout.fillWidth: true
                visible: String(root.showAction.id || "").length > 0
                enabled: root.addonLoaded && Boolean(root.showAction.enabled)
                text: root.orbRunning ? qsTr("Bring Orb into view") : qsTr("Start and show Orb")
                tone: "primary"
                toolTipText: qsTr("Enables the Orb and selects Docked mode when visibility is Off.")
                onClicked: root.actionTriggered(String(root.showAction.id))
            }

            NCButton {
                Layout.fillWidth: true
                visible: String(root.placementAction.id || "").length > 0
                enabled: root.orbRunning && Boolean(root.placementAction.enabled)
                text: qsTr("Choose desktop target")
                toolTipText: String(root.placementAction.helpText || qsTr("Choose the window or region the Orb should focus on."))
                onClicked: root.actionTriggered(String(root.placementAction.id))
            }

            NCButton {
                Layout.fillWidth: true
                visible: String(root.resetAction.id || "").length > 0
                enabled: root.orbRunning && Boolean(root.resetAction.enabled)
                text: qsTr("Reset position")
                tone: "quiet"
                toolTipText: String(root.resetAction.helpText || qsTr("Return the Orb to its configured home position."))
                onClicked: root.actionTriggered(String(root.resetAction.id))
            }
        }

        Label {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: String(root.statusControl.value || "")
            color: root.orbRunning ? Theme.NCTheme.success : Theme.NCTheme.textSecondary
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.captionSize
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignLeft
            visible: text.length > 0
        }
    }
}
