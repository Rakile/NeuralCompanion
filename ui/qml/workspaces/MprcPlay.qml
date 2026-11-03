pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme
import "MprcLayout.js" as LayoutMap

ScrollView {
    id: root
    objectName: "mprcPlayScroll"
    required property var workspace
    contentWidth: availableWidth
    clip: true
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    property string storyState: "Cast"
    property string draft: ""
    readonly property var avatarChat: root.workspace.field("mprc_chat_transcript").chatAvatars || ({})
    Timer {
        interval: 300
        repeat: true
        running: root.visible && root.workspace.bridge.selectedAddonId === "multi_persona_roleplay_tab"
        onTriggered: root.workspace.bridge.refreshLiveAddonControls()
    }
    readonly property var choiceField: root.workspace.field("mprc_chat_next_actions_list")
    readonly property var pendingChoices: (choiceField.options || []).filter(option => option.value !== "")
    readonly property var additionalGroup: LayoutMap.groups("Play",
        root.workspace.controls.filter(field => field.section === "Play"))
        .find(group => group.key === "additional") || ({ids: []})
    readonly property string serverDraft: String(root.workspace.field("mprc_chat_input").value || "")
    Component.onCompleted: composer.text = serverDraft

    function send() {
        if (!composer.text.trim().length || root.workspace.field("mprc_chat_send_button").enabled === false)
            return
        // The native action has no submission acknowledgement. Retain the draft
        // so a failed/disabled provider cannot silently discard the user's input.
        root.workspace.edit("mprc_chat_input", composer.text)
        root.workspace.run(root.workspace.field("mprc_chat_send_button"))
    }
    function remainingAdvanced() {
        return root.workspace.controls.filter(function(field) {
            return field.section === "Play" && (
                /structured|instructor|remote_|chromecast/.test(field.id))
        })
    }
    function selectFields(ids) { return root.workspace.selectFields(ids) }
    function storyText() {
        const raw = String(root.workspace.field("mprc_chat_transcript").value || "")
        try {
            const turns = JSON.parse(raw)
            if (Array.isArray(turns)) {
                const lines = turns.filter(turn => turn && typeof turn === "object").map(turn =>
                    String(turn.speaker || (turn.role === "user" ? "You" : "Narrator"))
                    + ": " + String(turn.text || ""))
                return lines.join("\n\n") || qsTr("No story reply yet. Start Play or send an action.")
            }
        } catch (error) { /* Older snapshots can contain plain text. */ }
        return raw || qsTr("No story reply yet. Start Play or send an action.")
    }
    function selectChoice(option, sendNow) {
        if (!option || option.value === "" || root.choiceField.enabled === false || root.choiceField.readOnly)
            return
        root.workspace.edit("mprc_chat_next_actions_list", option.value)
        composer.text = String(option.label || option.value || "")
        composer.forceActiveFocus()
        if (sendNow) root.send()
    }

    ColumnLayout {
        width: root.availableWidth
        spacing: 10

        MprcPanel {
            Layout.fillWidth: true
            Flow {
                Layout.fillWidth: true
                spacing: 8
                NCSwitch {
                    objectName: "mprcAvatarsToggle"
            toolTipText: qsTr("Show persona portraits beside story messages in this playback view.")
                    text: qsTr("Avatars")
                    checked: root.workspace.chatAvatarsEnabled
                    onToggled: root.workspace.chatAvatarsEnabled = checked
                }
                Repeater {
                    model: ["mprc_chat_start_button", "mprc_chat_pause_button", "mprc_chat_restart_button", "mprc_chat_clear_button", "mprc_chat_float_button"]
                    delegate: MprcField {
                        required property string modelData
                        width: modelData === "mprc_chat_restart_button" ? 116 : 96
                        compact: true
                        showLabel: false
                        field: root.workspace.field(modelData)
                        onActionRequested: field => root.workspace.run(field)
                    }
                }
                MprcField {
                    width: 110
                    compact: true
                    field: root.workspace.field("mprc_chat_story_font_size_spin", "Story Font")
                    onEdited: (id, value) => root.workspace.edit(id, value)
                }
                MprcField {
                    width: 180
                    compact: true
                    field: root.workspace.field("mprc_chat_voice_volume_slider", "Voice")
                    onEdited: (id, value) => root.workspace.edit(id, value)
                }
                MprcField {
                    width: 62
                    compact: true
                    showLabel: false
                    field: root.workspace.field("mprc_chat_voice_volume_popout_button")
                    onActionRequested: field => root.workspace.run(field)
                }
            }
        }
        MprcGroup {
            objectName: "mprcAdvanced"
            Layout.fillWidth: true
            group: ({key: "advanced", title: "Advanced · Structured output, phone & Chromecast", ids: root.remainingAdvanced().map(f => f.id), columns: 2, fold: true, expanded: false})
            controls: root.workspace.controls
            onEdited: (id, value) => root.workspace.edit(id, value)
            onPreviewed: (id, value) => root.workspace.preview(id, value)
            onActionRequested: field => root.workspace.run(field)
            onToggled: expanded => root.workspace.edit("mprc_chat_play_toolbar_advanced_toggle", expanded)
        }

        GridLayout {
            id: playColumns
            Layout.fillWidth: true
            columns: width >= 820 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 12

            MprcPanel {
                Layout.row: playColumns.columns === 2 || !root.workspace.chatAvatarsEnabled ? 0 : 1
                Layout.column: 0
                Layout.rowSpan: playColumns.columns === 2 ? 2 : 1
                Layout.fillWidth: true
                Layout.preferredWidth: playColumns.width * 0.65
                Layout.minimumWidth: 0
                Layout.alignment: Qt.AlignTop
                title: qsTr("Story Feed")
                ScrollView {
                    id: feedScroll
                    objectName: "mprcStoryFeed"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 340
                    contentWidth: availableWidth
                    clip: true
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    MprcChatFeed {
                        width: feedScroll.availableWidth
                        text: root.storyText()
                        pointSize: Math.max(8, Number(root.workspace.field("mprc_chat_story_font_size_spin").value || 13))
                        chat: root.avatarChat
                        avatarsEnabled: root.workspace.chatAvatarsEnabled
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        model: root.pendingChoices.length
                        delegate: NCButton {
                            required property int index
                            readonly property var option: root.pendingChoices[index] || ({})
                            objectName: "mprcChoice_" + index
                            width: Math.min(implicitWidth, parent.width)
                            text: String(option.label || "")
                            enabled: root.choiceField.enabled !== false && !root.choiceField.readOnly
                            compact: true
                            tone: "quiet"
                            toolTipText: qsTr("Click to fill Player Action; double-click or press Enter to send.")
                            onClicked: root.selectChoice(option, false)
                            onDoubleClicked: root.selectChoice(option, true)
                            Keys.onReturnPressed: event => { root.selectChoice(option, true); event.accepted = true }
                            Keys.onEnterPressed: event => { root.selectChoice(option, true); event.accepted = true }
                        }
                    }
                }
                Label { text: qsTr("Player Action"); color: Theme.NCTheme.text; font.pixelSize: 15 }
                RowLayout {
                    Layout.fillWidth: true
                    MprcField {
                        Layout.fillWidth: true
                        field: root.workspace.field("mprc_chat_intent_combo", "Mode")
                        onEdited: (id, value) => root.workspace.edit(id, value)
                    }
                    MprcField {
                        Layout.fillWidth: true
                        field: root.workspace.field("mprc_chat_speaker_combo", "Focus")
                        onEdited: (id, value) => root.workspace.edit(id, value)
                    }
                }
                NCTextArea {
                    id: composer
                    objectName: "mprcComposer"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 104
                    label: qsTr("Player Action")
                    placeholderText: qsTr("What do you do or say next?")
                    enabled: root.workspace.field("mprc_chat_input").enabled !== false
                    text: root.draft
                    wrapMode: TextEdit.Wrap
                    onTextChanged: root.draft = text
                    Keys.onReturnPressed: event => {
                        if (event.modifiers & Qt.ShiftModifier) event.accepted = false
                        else { root.send(); event.accepted = true }
                    }
                    Keys.onEnterPressed: event => {
                        if (event.modifiers & Qt.ShiftModifier) event.accepted = false
                        else { root.send(); event.accepted = true }
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 10
                    Repeater {
                        model: ["mprc_chat_use_ar_checkbox", "mprc_chat_visuals_checkbox"]
                        delegate: MprcField {
                            required property string modelData
                            width: 190
                            field: root.workspace.field(modelData)
                            onEdited: (id, value) => root.workspace.edit(id, value)
                        }
                    }
                    NCButton {
                        objectName: "mprcSend"
                        text: qsTr("Send")
                        compact: true
                        enabled: root.workspace.field("mprc_chat_send_button").enabled !== false
                        onClicked: root.send()
                    }
                }
            }
            MprcSpeakingDock {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: playColumns.width * 0.35
                Layout.row: 0
                Layout.column: playColumns.columns === 2 ? 1 : 0
                Layout.alignment: Qt.AlignTop
                visible: root.workspace.chatAvatarsEnabled
                compact: playColumns.columns === 1
                speaker: root.avatarChat.speaker || ({})
            }
            ColumnLayout {
                Layout.row: playColumns.columns === 2 || !root.workspace.chatAvatarsEnabled ? 1 : 2
                Layout.column: playColumns.columns === 2 ? 1 : 0
                Layout.fillWidth: true
                Layout.preferredWidth: playColumns.width * 0.35
                Layout.minimumWidth: 0
                Layout.alignment: Qt.AlignTop
                spacing: 12
                MprcPanel {
                    objectName: "mprcSceneState"
                    Layout.fillWidth: true
                    title: qsTr("Scene State")
                    MprcField { Layout.fillWidth: true; showLabel: false; field: root.workspace.field("mprc_chat_scene_state_label") }
                    Repeater {
                        model: ["mprc_location", "mprc_time_of_day", "mprc_mood", "mprc_objective"]
                        delegate: Label {
                            required property string modelData
                            Layout.fillWidth: true
                            text: root.workspace.field(modelData).label + ": " + String(root.workspace.field(modelData).value || "—")
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                        }
                    }
                    NCButton { text: qsTr("Edit session"); compact: true; tone: "quiet"; onClicked: root.workspace.sectionRequested("Session") }
                    Label { text: qsTr("Story State"); color: Theme.NCTheme.text; font.pixelSize: 14 }
                    RowLayout {
                        Repeater {
                            model: ["Cast", "Events", "Choices"]
                            delegate: NCTabButton {
                                required property string modelData
                                text: modelData
                                checked: root.storyState === modelData
                                onClicked: root.storyState = modelData
                            }
                        }
                    }
                    MprcField {
                        Layout.fillWidth: true
                        showLabel: false
                        field: root.workspace.field(root.storyState === "Cast" ? "mprc_chat_present_characters_list" : root.storyState === "Events" ? "mprc_chat_recent_events_list" : "mprc_chat_next_actions_list")
                        onEdited: (id, value) => root.workspace.edit(id, value)
                    }
                }
                MprcGroup {
                    Layout.fillWidth: true
                    group: ({key:"director",title:"Director",columns:2,twoColumnMinimum:320,ids:["mprc_chat_director_pacing_combo","mprc_chat_director_tone_combo","mprc_chat_director_agency_combo","mprc_chat_director_choice_mode_combo","mprc_chat_advance_scene_button","mprc_chat_summarize_button","mprc_chat_repair_button"]})
                    controls: root.workspace.controls
                    onEdited: (id, value) => root.workspace.edit(id, value)
                    onActionRequested: field => root.workspace.run(field)
                }
            }
        }
        MprcGroup {
            objectName: "mprcEngine"
            Layout.fillWidth: true
            group: ({key:"engine",title:"Story Engine · Read-only activity",fold:true,expanded:false,columns:2,ids:["unnamed_qlabel_qlabel#28","mprc_chat_story_director_summary","unnamed_qlabel_qlabel#27","mprc_chat_memory_databank_summary","unnamed_qlabel_qlabel#26","mprc_chat_visual_beat_summary","mprc_chat_voice_segments_summary","unnamed_qlabel_qlabel#23","unnamed_qlabel_qlabel#24","mprc_chat_spotify_music_summary"]})
            controls: root.workspace.controls
        }
        MprcGroup {
            objectName: "mprcDiagnostics"
            Layout.fillWidth: true
            group: ({key:"diagnostics",title:"Playback & visual diagnostics",fold:true,expanded:false,columns:2,ids:["mprc_buffer_race_summary","mprc_buffer_race_render_bar","mprc_buffer_race_playback_bar","mprc_visual_prompt_debug_text","mprc_chat_input_legacy"]})
            controls: root.workspace.controls
            onEdited: (id, value) => root.workspace.edit(id, value)
        }
        MprcGroup {
            Layout.fillWidth: true
            visible: (root.additionalGroup.ids || []).length > 0
            group: root.additionalGroup
            controls: root.workspace.controls
            onEdited: (id, value) => root.workspace.edit(id, value)
            onPreviewed: (id, value) => root.workspace.preview(id, value)
            onActionRequested: field => root.workspace.run(field)
        }
        Label {
            objectName: "mprcPlayStatus"
            Layout.fillWidth: true
            text: String(root.workspace.field("mprc_chat_status_label").value || "")
            color: Theme.NCTheme.textMuted
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
    }
}
