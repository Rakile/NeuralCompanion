pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

ScrollView {
    id: root

    required property var bridge
    property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
        bridge: root.bridge
        scrollView: root
        pageKey: "addon:discord_voice_bridge_tab:Moderator"
    }
    readonly property var stateControl: controlById("discord_moderator_state_label")
    readonly property var summaryRows: stateControl.summaryRows || []
    readonly property var quickChoices: stateControl.quickChoices || []
    property bool lifecycleReady: false

    objectName: "discordModeratorWorkspace"
    clip: true
    contentWidth: availableWidth

    Component.onCompleted: {
        lifecycleReady = true
        if (visible)
            bridge.refreshLiveAddonControls()
    }
    onVisibleChanged: {
        if (lifecycleReady && visible)
            bridge.refreshLiveAddonControls()
    }

    Timer {
        objectName: "moderatorRefreshTimer"
        interval: 2000
        repeat: true
        running: root.visible
        onTriggered: {
            if (root.visible)
                root.bridge.refreshLiveAddonControls()
        }
    }

    function controlById(controlId) {
        const controls = root.bridge.liveAddonControls || []
        for (let index = 0; index < controls.length; ++index) {
            if (String(controls[index].id || "") === String(controlId || ""))
                return controls[index]
        }
        return ({})
    }

    function optionIndex(control) {
        const options = control.options || []
        for (let index = 0; index < options.length; ++index) {
            if (String(options[index].value) === String(control.value))
                return index
        }
        return options.length > 0 ? 0 : -1
    }

    function setChoice(control, index) {
        const options = control.options || []
        if (index >= 0 && index < options.length)
            root.bridge.setLiveAddonControl(String(control.id || ""), options[index].value)
    }

    function runAction(controlId) {
        const control = controlById(controlId)
        if (Boolean(control.enabled))
            root.bridge.triggerLiveAddonAction(controlId)
    }

    function runQuickNext(index) {
        const choice = quickChoices[index]
        if (!choice || !Boolean(choice.canNext))
            return
        bridge.setLiveAddonControl("discord_moderator_participants_table", choice.value)
        runAction("discord_moderator_route_next_button")
    }

    function runQuickCall(index) {
        const choice = quickChoices[index]
        if (!choice || !Boolean(choice.canCall))
            return
        bridge.setLiveAddonControl("discord_moderator_participants_table", choice.value)
        runAction("discord_moderator_call_on_button")
    }

    ColumnLayout {
        width: parent.width
        spacing: Theme.NCMetrics.space12

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Bridge controls")
            description: String(root.controlById("discord_bridge_status_label").value || qsTr("Discord bridge status is unavailable."))

            Flow {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8
                NCButton {
                    objectName: "discord_bridge_save_button"
                    text: qsTr("Save Settings")
                    enabled: Boolean(root.controlById(objectName).enabled)
                    onClicked: root.runAction(objectName)
                }
                NCButton {
                    objectName: "discord_bridge_start_button"
                    text: qsTr("Start Bridge")
                    tone: "primary"
                    enabled: Boolean(root.controlById(objectName).enabled)
                    onClicked: root.runAction(objectName)
                }
                NCButton {
                    objectName: "discord_bridge_stop_button"
                    text: qsTr("Stop Bridge")
                    tone: "danger"
                    enabled: Boolean(root.controlById(objectName).enabled)
                    onClicked: root.runAction(objectName)
                }
                NCButton {
                    objectName: "discord_bridge_restart_button"
                    text: qsTr("Restart Bridge")
                    enabled: Boolean(root.controlById(objectName).enabled)
                    onClicked: root.runAction(objectName)
                }
                NCButton {
                    objectName: "discord_bridge_refresh_button"
                    text: qsTr("Refresh Status")
                    enabled: Boolean(root.controlById(objectName).enabled)
                    onClicked: root.runAction(objectName)
                }
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Moderator assignment")
            description: qsTr("Choose the active bot, assign moderator responsibility, and decide whether speaker control should enforce Discord mute state.")

            GridLayout {
                Layout.fillWidth: true
                columns: width >= 760 ? 2 : 1
                columnSpacing: Theme.NCMetrics.space12
                rowSpacing: Theme.NCMetrics.space8

                ColumnLayout {
                    Layout.fillWidth: true
                    Label {
                        text: qsTr("Selected bot")
                        color: Theme.NCTheme.textSecondary
                        font.pixelSize: Theme.NCTypography.captionSize
                    }
                    NCComboBox {
                        toolTipText: String(root.controlById("discord_moderator_target_combo").toolTip || "")

                        id: moderatorTarget
                        Layout.fillWidth: true
                        label: qsTr("Selected bot")
                        enabled: Boolean(root.controlById("discord_moderator_target_combo").enabled)
                        model: root.controlById("discord_moderator_target_combo").options || []
                        textRole: "label"
                        valueRole: "value"
                        currentIndex: root.optionIndex(root.controlById("discord_moderator_target_combo"))
                        onActivated: index => root.setChoice(root.controlById("discord_moderator_target_combo"), index)
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space4
                    NCSwitch {
                        toolTipText: String(root.controlById("discord_moderator_enforce_mute_checkbox").toolTip || "")

                        objectName: "discordModeratorMuteSwitch"
                        Layout.fillWidth: true
                        text: qsTr("Mute other participants while someone speaks")
                        checked: Boolean(root.controlById("discord_moderator_enforce_mute_checkbox").value)
                        enabled: Boolean(root.controlById("discord_moderator_enforce_mute_checkbox").enabled)
                        onClicked: root.bridge.setLiveAddonControl("discord_moderator_enforce_mute_checkbox", checked)
                    }
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Uses Discord server mute. The Moderator stays unmuted.")
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.captionSize
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Flow {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8
                NCButton {
                    text: qsTr("Use Selected As Moderator Bot")
                    enabled: Boolean(root.controlById("discord_moderator_set_enforcer_button").enabled)
                    onClicked: root.runAction("discord_moderator_set_enforcer_button")
                }
                NCButton {
                    text: qsTr("Clear Moderator Bot")
                    tone: "quiet"
                    enabled: Boolean(root.controlById("discord_moderator_clear_enforcer_button").enabled)
                    onClicked: root.runAction("discord_moderator_clear_enforcer_button")
                }
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Now / Next / Speaker Control")
            description: String(root.stateControl.value || qsTr("Moderator state is unavailable."))

            GridLayout {
                Layout.fillWidth: true
                columns: width >= 720 ? 3 : 1
                columnSpacing: Theme.NCMetrics.space12
                rowSpacing: Theme.NCMetrics.space8

                Repeater {
                    model: root.summaryRows
                    delegate: Rectangle {
                        id: summaryTile
                        required property int index
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: Math.max(70, summaryColumn.implicitHeight + Theme.NCMetrics.space20)
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.windowRaised
                        border.color: Theme.NCTheme.borderSubtle

                        ColumnLayout {
                            id: summaryColumn
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space10
                            spacing: Theme.NCMetrics.space4
                            Label {
                                Layout.fillWidth: true
                                text: String(summaryTile.modelData.label || "")
                                color: Theme.NCTheme.textMuted
                                font.pixelSize: Theme.NCTypography.microSize
                                font.weight: Theme.NCTypography.semibold
                                elide: Text.ElideRight
                            }
                            Label {
                                Layout.fillWidth: true
                                text: String(summaryTile.modelData.value || "—")
                                color: Theme.NCTheme.text
                                font.pixelSize: Theme.NCTypography.bodySize
                                font.weight: Theme.NCTypography.semibold
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                }
            }

            NCInlineMessage {
                objectName: "moderatorWarningMessage"
                Layout.fillWidth: true
                visible: Boolean(root.stateControl.hasWarning)
                tone: "warning"
                title: qsTr("Moderator notice")
                message: String(root.controlById("discord_moderator_warning_label").value || "")
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Route Flow")
            description: qsTr("The current route expressed as a readable speaker sequence.")

            Flickable {
                id: routeFlowFlick
                objectName: "moderatorRouteFlowFlick"
                property bool disposed: false
                Layout.fillWidth: true
                Layout.preferredHeight: 180
                contentWidth: width
                contentHeight: routeFlowText.height
                boundsBehavior: Flickable.StopAtBounds
                clip: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                function syncFromBackend() {
                    const oldMaximum = Math.max(0, contentHeight - height)
                    const wasAtTail = contentY >= oldMaximum - 2
                    const oldPosition = contentY
                    routeFlowText.text = String(
                        root.controlById("discord_moderator_route_flow_view").value
                        || qsTr("No shared route flow yet."))
                    const flow = routeFlowFlick
                    Qt.callLater(function() {
                        if (!flow || flow.disposed)
                            return
                        const newMaximum = Math.max(0, flow.contentHeight - flow.height)
                        flow.contentY = wasAtTail
                                ? newMaximum : Math.min(oldPosition, newMaximum)
                    })
                }

                Component.onCompleted: syncFromBackend()
                Component.onDestruction: disposed = true
                Connections {
                    target: root.bridge
                    function onLiveAddonControlsChanged() { routeFlowFlick.syncFromBackend() }
                }

                NCTextArea {
                    toolTipText: String(root.controlById("discord_moderator_route_flow_view").toolTip || "")

                    id: routeFlowText
                    width: routeFlowFlick.width
                    height: Math.max(routeFlowFlick.height, contentHeight + topPadding + bottomPadding)
                    readOnly: true
                    selectByMouse: true
                    color: Theme.NCTheme.text
                    font.family: Theme.NCTypography.monoFamily
                    wrapMode: TextEdit.Wrap
                    Accessible.name: qsTr("Route flow history")
                }
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Dead-Air Recovery")
            description: String(root.controlById("discord_dead_air_status_label").value || qsTr("No recovery activity yet."))

            NCSwitch {
                toolTipText: String(root.controlById("discord_dead_air_enabled_checkbox").toolTip || "")

                Layout.fillWidth: true
                text: qsTr("Enable recovery")
                checked: Boolean(root.controlById("discord_dead_air_enabled_checkbox").value)
                enabled: Boolean(root.controlById("discord_dead_air_enabled_checkbox").enabled)
                onClicked: root.bridge.setLiveAddonControl("discord_dead_air_enabled_checkbox", checked)
            }

            GridLayout {
                Layout.fillWidth: true
                columns: width >= 760 ? 2 : 1
                columnSpacing: Theme.NCMetrics.space12
                rowSpacing: Theme.NCMetrics.space8

                Repeater {
                    model: ["discord_dead_air_cooldown_spin", "discord_dead_air_silence_timeout_spin"]
                    delegate: ColumnLayout {
                        id: deadAirNumber
                        required property string modelData
                        readonly property var control: root.controlById(deadAirNumber.modelData)
                        Layout.fillWidth: true
                        Label {
                            text: String(deadAirNumber.control.label || "")
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                        }
                        NCTextField {
                            toolTipText: String(deadAirNumber.control.toolTip || deadAirNumber.control.description || "")

                            id: deadAirNumberEditor
                            Layout.fillWidth: true
                            objectName: String(deadAirNumber.modelData)
                            label: String(deadAirNumber.control.label || "")
                            enabled: Boolean(deadAirNumber.control.enabled)
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            validator: DoubleValidator {
                                locale: "C"
                                bottom: Number(deadAirNumber.control.minimum === undefined
                                               ? 0 : deadAirNumber.control.minimum)
                                top: Number(deadAirNumber.control.maximum === undefined
                                            ? 3600 : deadAirNumber.control.maximum)
                                decimals: 6
                                notation: DoubleValidator.StandardNotation
                            }

                            function syncFromBackend() {
                                if (!activeFocus)
                                    text = String(deadAirNumber.control.value === undefined
                                                  ? "" : deadAirNumber.control.value)
                            }

                            Component.onCompleted: syncFromBackend()
                            Connections {
                                target: root.bridge
                                function onLiveAddonControlsChanged() {
                                    deadAirNumberEditor.syncFromBackend()
                                }
                            }
                            onEditingFinished: {
                                if (!acceptableInput)
                                    return
                                const parsed = Number(String(text).trim().replace(",", "."))
                                if (isFinite(parsed))
                                    root.bridge.setLiveAddonControl(deadAirNumber.modelData, parsed)
                            }
                        }
                    }
                }

                Repeater {
                    model: [
                        "discord_dead_air_trigger_combo",
                        "discord_dead_air_action_combo",
                        "discord_dead_air_strategy_combo",
                        "discord_dead_air_fallback_target_combo"
                    ]
                    delegate: ColumnLayout {
                        id: deadAirChoice
                        required property string modelData
                        readonly property var control: root.controlById(deadAirChoice.modelData)
                        Layout.fillWidth: true
                        Label {
                            text: String(deadAirChoice.control.label || "")
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                        }
                        NCComboBox {
                            toolTipText: String(deadAirChoice.control.toolTip || deadAirChoice.control.description || "")

                            Layout.fillWidth: true
                            label: String(deadAirChoice.control.label || "")
                            enabled: Boolean(deadAirChoice.control.enabled)
                            model: deadAirChoice.control.options || []
                            textRole: "label"
                            valueRole: "value"
                            currentIndex: root.optionIndex(deadAirChoice.control)
                            onActivated: index => root.setChoice(deadAirChoice.control, index)
                        }
                    }
                }
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Quick Turn Choices")
            description: String(root.controlById("discord_moderator_shortcuts_hint_label").value || qsTr("No safe turn choices are available."))

            Repeater {
                model: root.quickChoices
                delegate: RowLayout {
                    id: quickChoice
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8

                    Label {
                        Layout.fillWidth: true
                        text: String(quickChoice.modelData.name || qsTr("Participant"))
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.bodySize
                        font.weight: Theme.NCTypography.semibold
                        elide: Text.ElideRight
                    }
                    NCButton {
                        objectName: "moderatorQuickNext" + quickChoice.index
                        text: qsTr("Next")
                        compact: true
                        enabled: Boolean(quickChoice.modelData.canNext)
                        onClicked: root.runQuickNext(quickChoice.index)
                    }
                    NCButton {
                        objectName: "moderatorQuickCall" + quickChoice.index
                        text: qsTr("Call now")
                        compact: true
                        tone: "primary"
                        enabled: Boolean(quickChoice.modelData.canCall)
                        onClicked: root.runQuickCall(quickChoice.index)
                    }
                }
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Bot Status")
            description: qsTr("Select the bridge instance used by moderator commands.")
            DiscordModeratorTable {
                id: instancesTable
                Layout.fillWidth: true
                bridge: root.bridge
                control: root.controlById("discord_moderator_instances_table")
                headers: [qsTr("ID"), qsTr("Name"), qsTr("Discord"), qsTr("Speaking"), qsTr("Listening"), qsTr("Queued"), qsTr("Render"), qsTr("Playback"), qsTr("Last Route")]
                columnWidths: [130, 160, 100, 88, 92, 70, 100, 100, 150]
                tableObjectName: "moderatorInstancesTable"
                flickObjectName: "moderatorInstancesTableFlick"
                rowObjectPrefix: "moderatorInstanceRow"
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Participants")
            description: qsTr("Select a participant for speaker-control and queue actions.")
            DiscordModeratorTable {
                id: participantsTable
                Layout.fillWidth: true
                bridge: root.bridge
                control: root.controlById("discord_moderator_participants_table")
                headers: [qsTr("ID"), qsTr("Name"), qsTr("Connected"), qsTr("Speaking"), qsTr("Listening"), qsTr("Queued"), qsTr("Moderator State")]
                columnWidths: [145, 175, 96, 90, 92, 70, 160]
                tableObjectName: "moderatorParticipantsTable"
                flickObjectName: "moderatorParticipantsTableFlick"
                rowObjectPrefix: "moderatorParticipantRow"
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Speaker Control")
            description: String(root.controlById("discord_moderator_selected_action_label").value || qsTr("Choose a participant."))

            Flow {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8
                Repeater {
                    model: [
                        "discord_moderator_route_next_button",
                        "discord_moderator_give_floor_button",
                        "discord_moderator_mute_button",
                        "discord_moderator_unmute_button",
                        "discord_moderator_clear_pending_button",
                        "discord_moderator_clear_floor_button"
                    ]
                    delegate: NCButton {
                        id: participantAction
                        required property string modelData
                        readonly property var control: root.controlById(participantAction.modelData)
                        text: String(control.label || participantAction.modelData)
                        enabled: Boolean(control.enabled)
                        compact: true
                        onClicked: root.runAction(participantAction.modelData)
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space12
                NCSwitch {
                    toolTipText: String(root.controlById("discord_moderator_allow_interrupt_current_checkbox").toolTip || "")

                    Layout.fillWidth: true
                    text: qsTr("Allow interrupt current")
                    checked: Boolean(root.controlById("discord_moderator_allow_interrupt_current_checkbox").value)
                    enabled: Boolean(root.controlById("discord_moderator_allow_interrupt_current_checkbox").enabled)
                    onClicked: root.bridge.setLiveAddonControl("discord_moderator_allow_interrupt_current_checkbox", checked)
                }
                NCSwitch {
                    toolTipText: String(root.controlById("discord_route_protected_mic_speech_checkbox").toolTip || "")

                    Layout.fillWidth: true
                    text: qsTr("Route protected mic speech")
                    checked: Boolean(root.controlById("discord_route_protected_mic_speech_checkbox").value)
                    enabled: Boolean(root.controlById("discord_route_protected_mic_speech_checkbox").enabled)
                    onClicked: root.bridge.setLiveAddonControl("discord_route_protected_mic_speech_checkbox", checked)
                }
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Announcement")
            description: qsTr("Send a one-off announcement through the selected Discord bot.")

            NCTextField {
                toolTipText: String(root.controlById("discord_moderator_announcement_edit").toolTip || "")

                id: announcementEditor
                objectName: "moderatorAnnouncement"
                Layout.fillWidth: true
                label: qsTr("Announcement")
                placeholderText: qsTr("What should the selected bot say?")
                enabled: Boolean(root.controlById("discord_moderator_announcement_edit").enabled)
                onTextEdited: root.bridge.setLiveAddonControl(
                    "discord_moderator_announcement_edit", text)

                function syncFromBackend() {
                    if (!activeFocus)
                        text = String(root.controlById("discord_moderator_announcement_edit").value || "")
                }

                Component.onCompleted: syncFromBackend()
                Connections {
                    target: root.bridge
                    function onLiveAddonControlsChanged() { announcementEditor.syncFromBackend() }
                }
            }

            Flow {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8
                NCButton {
                    text: qsTr("Speak Through Target")
                    tone: "primary"
                    enabled: Boolean(root.controlById("discord_moderator_announce_button").enabled)
                    onClicked: root.runAction("discord_moderator_announce_button")
                }
                NCButton {
                    text: qsTr("Call Target Now")
                    enabled: Boolean(root.controlById("discord_moderator_call_on_button").enabled)
                    onClicked: root.runAction("discord_moderator_call_on_button")
                }
                NCButton {
                    text: qsTr("Stop All Speech")
                    tone: "danger"
                    enabled: Boolean(root.controlById("discord_moderator_stop_all_button").enabled)
                    onClicked: root.runAction("discord_moderator_stop_all_button")
                }
                NCButton {
                    text: qsTr("Clear All Queues")
                    tone: "warning"
                    enabled: Boolean(root.controlById("discord_moderator_clear_all_queues_button").enabled)
                    onClicked: root.runAction("discord_moderator_clear_all_queues_button")
                }
                NCButton {
                    text: qsTr("Clear All")
                    tone: "warning"
                    enabled: Boolean(root.controlById("discord_moderator_clear_button").enabled)
                    onClicked: root.runAction("discord_moderator_clear_button")
                }
            }

            Label {
                Layout.fillWidth: true
                text: String(root.controlById("discord_moderator_note_label").value || "")
                visible: text.length > 0
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.Wrap
            }
        }
    }
}
