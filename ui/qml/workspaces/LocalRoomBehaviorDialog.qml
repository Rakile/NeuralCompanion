pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

NCDialog {
    id: root
    required property var workspace
    objectName: "localRoomBehaviorDialog"
    parent: Overlay.overlay
    anchors.centerIn: parent
    title: qsTr("Conversation behavior")
    description: qsTr("Turn-taking changes apply only to this Local room with Save behavior. Microphone controls keep their existing scope.")
    width: Math.min(920, parent ? parent.width - 32 : 920)
    height: Math.min(800, parent ? parent.height - 32 : 800)
    // Each concrete behavior selector supplies its own semantic toolTipText.
    component BehaviorChoice: NCComboBox {
        id: choice
        implicitHeight: Math.max(40, contentItem.implicitHeight + topPadding + bottomPadding)
        contentItem: Label {
            text: choice.displayText; font: choice.font
            color: choice.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
            wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter
        }
        delegate: ItemDelegate {
            id: choiceOption
            required property int index
            width: choice.width
            implicitHeight: Math.max(40, contentItem.implicitHeight + topPadding + bottomPadding)
            highlighted: choice.highlightedIndex === index
            contentItem: Label {
                text: choice.textAt(choiceOption.index); font: choice.font
                color: Theme.NCTheme.text; wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle { color: choiceOption.highlighted ? Theme.NCTheme.selection : "transparent"; radius: 4 }
        }
    }
    contentItem: ScrollView {
        id: scroll
        clip: true
        contentWidth: availableWidth
        GridLayout {
            width: scroll.availableWidth
            columns: width >= 650 ? 2 : 1
            columnSpacing: 28; rowSpacing: 20
            ColumnLayout {
                Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop; spacing: 9
                Label { text: qsTr("Taking turns"); font.bold: true; color: Theme.NCTheme.text }
                Label { text: qsTr("Who chooses the next speaker?"); color: Theme.NCTheme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                BehaviorChoice {
                    objectName: "localRoomSpeakerSelection"; Layout.fillWidth: true
                    toolTipText: qsTr("NC chooses uses AI to select who speaks next. Follow names and questions uses conversational handoffs. I choose each speaker waits for your Speak next choice and disables automatic moderator restarts. Save behavior to apply.")
                    model: [qsTr("NC chooses from the conversation"),qsTr("Follow names and questions"),qsTr("I choose each speaker")]
                    currentIndex: ["ai","names","manual"].indexOf(root.workspace.behaviorDraft.speaker_selection)
                    onActivated: index => root.workspace.editBehavior("speaker_selection",["ai","names","manual"][index])
                }
                Label { Layout.fillWidth: true; text: root.workspace.behaviorManual ? qsTr("Choose Speak next from a participant menu for each turn.") : qsTr("Your manual Speak next choice takes priority."); color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap }
                NCCheckBox {
                    objectName: "localRoomAllowRepeat"; Layout.fillWidth: true
                    text: qsTr("Allow the same speaker again"); enabled: !root.workspace.behaviorManual
                    checked: Boolean(root.workspace.behaviorDraft.allow_repeat)
                    toolTipText: qsTr("Allow automatic selection to choose the same participant for consecutive turns. Manual Speak next remains available either way. Save behavior to apply.")
                    onClicked: root.workspace.editBehavior("allow_repeat",checked)
                }
                NCCheckBox {
                    objectName: "localRoomPrepareAhead"; Layout.fillWidth: true
                    text: qsTr("Prepare next reply while someone speaks"); enabled: !root.workspace.behaviorManual
                    checked: Boolean(root.workspace.behaviorDraft.prepare_ahead)
                    toolTipText: qsTr("Prepare the next automatically routed reply and speech during the current turn. Playback waits for the current speaker to finish. Save behavior to apply.")
                    onClicked: root.workspace.editBehavior("prepare_ahead",checked)
                }
                Label { Layout.fillWidth: true; text: qsTr("Playback still waits for the current speaker."); color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap }
                ColumnLayout {
                    visible: root.workspace.behaviorDraft.speaker_selection === "ai"
                    Layout.fillWidth: true; spacing: 7
                    Label { text: qsTr("Guidance for choosing the next speaker"); Layout.fillWidth: true; color: Theme.NCTheme.text; wrapMode: Text.WordWrap }
                    Label { text: qsTr("Tell the speaker-selection AI what to prioritize when choosing who speaks next. This affects turn-taking, not what Personas say. Leave blank for NC’s normal rules."); Layout.fillWidth: true; color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap; font.pixelSize: 12 }
                    TextArea {
                        id: instructions
                        objectName: "localRoomRouterInstructions"; Layout.fillWidth: true
                        visible: root.workspace.behaviorDraft.speaker_selection === "ai"
                        implicitHeight: 95; wrapMode: TextEdit.Wrap
                        text: String(root.workspace.behaviorDraft.router_instructions || "")
                        placeholderText: qsTr("For example: Give quieter participants a turn.")
                        color: Theme.NCTheme.text; placeholderTextColor: Theme.NCTheme.textMuted; selectionColor: Theme.NCTheme.selection
                        background: Rectangle { radius: 8; color: Theme.NCTheme.window; border.color: Theme.NCTheme.borderStrong }
                        NCHelp { target: instructions; text: qsTr("Optional priorities for the AI that chooses the next speaker, such as inviting quieter participants. This does not change Persona prompts or tell a bot what to say. Available only with NC chooses from the conversation. Save behavior to apply.") }
                        onTextChanged: if (text !== String(root.workspace.behaviorDraft.router_instructions || "")) root.workspace.editBehavior("router_instructions",text)
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop; spacing: 9
                Label { text: qsTr("When nobody is next"); color: Theme.NCTheme.text; font.bold: true }
                NCCheckBox {
                    objectName: "localRoomModeratorHelp"; Layout.fillWidth: true
                    text: qsTr("Let the moderator restart the discussion")
                    enabled: !root.workspace.behaviorManual; checked: root.workspace.behaviorRecovery
                    toolTipText: qsTr("Let the moderator help when the room is quiet and no speaker is queued. Disable for open pauses. Manual speaker selection always disables this recovery. Save behavior to apply.")
                    onClicked: root.workspace.editBehavior("moderator_help",checked)
                }
                Label { objectName: "localRoomBehaviorManualNote"; visible: root.workspace.behaviorManual; Layout.fillWidth: true; text: qsTr("Manual mode waits for you. Automatic moderator help is off."); color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap; font.pixelSize: 12 }
                ColumnLayout {
                    objectName: "localRoomRestartOptions"; visible: root.workspace.behaviorRecovery; enabled: visible
                    Layout.fillWidth: true; spacing: 7
                    Label { text: qsTr("Seconds before stepping in"); color: Theme.NCTheme.text }
                    NCSpinBox {
                        objectName: "localRoomBehaviorSilence"; Layout.fillWidth: true
                        from: 0; to: 3600; editable: true; value: Number(root.workspace.behaviorDraft.silence_seconds || 0)
                        toolTipText: qsTr("Extra quiet time before the moderator steps in, from 0 to 3600 seconds. 0 adds no delay after the current turn and speaker selection finish. Nobody may be speaking or queued next. Save behavior to apply.")
                        onValueModified: root.workspace.editBehavior("silence_seconds",value)
                    }
                    Label { text: qsTr("What should happen?"); color: Theme.NCTheme.text }
                    BehaviorChoice {
                        objectName: "localRoomModeratorAction"; Layout.fillWidth: true
                        model: [qsTr("Moderator speaks and invites someone"),qsTr("Moderator speaks only"),qsTr("Invite someone silently")]
                        currentIndex: ["moderator_speaks_and_calls_next","moderator_speaks_only","silent_call_next"].indexOf(root.workspace.behaviorDraft.moderator_action)
                        toolTipText: qsTr("Choose whether recovery includes moderator speech and a handoff, speech alone, or a silent invitation. Any next speaker is selected using the rule in Taking turns. Save behavior to apply.")
                        onActivated: index => root.workspace.editBehavior("moderator_action",["moderator_speaks_and_calls_next","moderator_speaks_only","silent_call_next"][index])
                    }
                    Label { objectName: "localRoomModeratorHandoverHelp"; Layout.fillWidth: true; visible: root.workspace.behaviorDraft.moderator_action !== "moderator_speaks_only"; text: qsTr("The next speaker is chosen using the rule in Taking turns."); color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap }
                    Label { text: qsTr("Restart after no response to"); color: Theme.NCTheme.text }
                    BehaviorChoice {
                        objectName: "localRoomBehaviorTrigger"; Layout.fillWidth: true
                        model: [qsTr("AI participant speech only"),qsTr("AI participant or human speech")]
                        currentIndex: root.workspace.behaviorDraft.trigger === "no_route_after_bot_speech" ? 0 : 1
                        toolTipText: qsTr("Choose which completed speech can trigger moderator recovery when nobody responds: AI speech only, or AI and human speech. Save behavior to apply.")
                        onActivated: index => root.workspace.editBehavior("trigger",index === 0 ? "no_route_after_bot_speech" : "no_route_after_any_speech")
                    }
                    Label { text: qsTr("Seconds between moderator restarts"); Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.NCTheme.text }
                    NCSpinBox {
                        objectName: "localRoomBehaviorCooldown"; Layout.fillWidth: true
                        from: 0; to: 3600; editable: true; value: Number(root.workspace.behaviorDraft.cooldown_seconds || 0)
                        toolTipText: qsTr("Minimum time between moderator recovery turns, from 0 to 3600 seconds. 0 allows recovery without an extra cooldown. Save behavior to apply.")
                        onValueModified: root.workspace.editBehavior("cooldown_seconds",value)
                    }
                }
                Label { Layout.fillWidth: true; text: qsTr("Microphone and interruptions"); color: Theme.NCTheme.text; font.bold: true }
                NCSwitch {
                    objectName: "localRoomAllowInterruptCurrent"; Layout.fillWidth: true
                    text: qsTr("Allow interrupt current")
                    checked: Boolean(root.workspace.controlById("discord_moderator_allow_interrupt_current_checkbox").value)
                    enabled: Boolean(root.workspace.controlById("discord_moderator_allow_interrupt_current_checkbox").enabled)
                    toolTipText: qsTr("Let incoming human speech interrupt the current speaker. Off protects the current turn. This is the existing live Moderator control and applies immediately; it does not require Save behavior.")
                    onClicked: root.workspace.setRoomControl("discord_moderator_allow_interrupt_current_checkbox",checked)
                }
                NCSwitch {
                    objectName: "localRoomRouteProtectedMic"; Layout.fillWidth: true
                    text: qsTr("Route protected mic speech")
                    checked: Boolean(root.workspace.controlById("discord_route_protected_mic_speech_checkbox").value)
                    enabled: Boolean(root.workspace.controlById("discord_route_protected_mic_speech_checkbox").enabled)
                    toolTipText: qsTr("When the current speaker is protected, still transcribe your microphone speech and let room routing consider it without cutting off that speaker. Off ignores mic speech during a protected turn. This uses the existing addon playback setting: saved on change; restart the room to apply it.")
                    onClicked: root.workspace.setRoomControl("discord_route_protected_mic_speech_checkbox",checked)
                }
                Label { Layout.fillWidth: true; text: qsTr("These controls use the existing Moderator settings and save separately. Restart the room after changing protected mic routing."); color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap; font.pixelSize: 12 }
            }
        }
    }
    footer: Item {
        implicitHeight: footerRow.implicitHeight + 32
        RowLayout {
            id: footerRow
            anchors.fill: parent
            anchors.leftMargin: 20; anchors.rightMargin: 20
            anchors.topMargin: 12; anchors.bottomMargin: 20
            spacing: 10
            Label {
                objectName: "localRoomBehaviorSaveStatus"; Layout.fillWidth: true
                text: root.workspace.behaviorSaveError ? qsTr("Could not save behavior: %1").arg(root.workspace.behaviorSaveError)
                    : !root.workspace.behaviorDraftDirty ? qsTr("Saved for this room")
                    : root.workspace.behaviorSubmitted ? qsTr("Waiting for saved behavior confirmation…") : qsTr("Unsaved changes")
                color: root.workspace.behaviorSaveError ? Theme.NCTheme.error : Theme.NCTheme.textMuted; wrapMode: Text.WordWrap
            }
            NCButton { text: qsTr("Close"); onClicked: root.close() }
            NCButton { objectName: "localRoomSaveBehavior"; text: qsTr("Save behavior"); tone: "primary"; enabled: root.workspace.behaviorDraftDirty && root.workspace.actionEnabled("discord_local_room_save_behavior"); onClicked: root.workspace.saveBehavior() }
        }
    }
}
