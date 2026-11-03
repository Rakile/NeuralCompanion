pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

ScrollView {
    id: root
    objectName: "coreSettingsWorkspace"

    required property var bridge
    property string section: "vision"
    property string currentChatTab: "conversation"
    Component.onCompleted: {
        if (typeof bridge.navigationSelection === "function")
            currentChatTab = bridge.navigationSelection("runtime:chat-tab", "conversation")
    }
    onCurrentChatTabChanged: {
        if (typeof bridge.rememberNavigationSelection === "function")
            bridge.rememberNavigationSelection("runtime:chat-tab", currentChatTab)
    }
    Connections {
        target: root.bridge
        function onRuntimeSectionRequested(section) {
            if (section === "chat" && typeof root.bridge.navigationSelection === "function")
                root.currentChatTab = root.bridge.navigationSelection("runtime:chat-tab", "conversation")
        }
    }
    readonly property var chatTabs: [
        {"key": "conversation", "label": qsTr("Conversation")},
        {"key": "writing", "label": qsTr("Writing")},
        {"key": "proactive", "label": qsTr("Proactive")},
        {"key": "memory", "label": qsTr("Memory")}
    ]
    property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
        bridge: root.bridge
        scrollView: root
        pageKey: "runtime:" + root.section
    }
    clip: true
    contentWidth: availableWidth

    background: Rectangle {
        color: Theme.NCTheme.windowRaised
        radius: Theme.NCMetrics.radiusLarge
        border.color: Theme.NCTheme.border
    }

    readonly property string sectionTitle: section === "vision" ? qsTr("Vision sensors")
                                                  : section === "chat" ? qsTr("Chat behavior")
                                                  : section === "story" ? qsTr("Story visuals")
                                                  : qsTr("Appearance themes")
    readonly property string sectionDescription: section === "vision"
        ? qsTr("Choose the ambient source and control when sensory context may enter the existing conversation pipeline.")
        : section === "chat"
        ? qsTr("Set context limits, proactive replies, and writing assistance. Companion instructions are managed in Persona.")
        : section === "story"
        ? qsTr("Control story-image continuity and safety rules used by the existing Visual Reply addon.")
        : ""

    function visionPrimarySchema() {
        return [
            {"key": "sensory_feedback_source", "toolTip": qsTr("Source used for background sensory checks. Off stops these ambient checks; choose Screen, Webcam, or Clipboard to use that configured source. Explicit capture actions remain separate."), "label": qsTr("Ambient source"), "description": qsTr("Source used for background sensory feedback."), "type": "choice", "options": [
                {"label": qsTr("Off"), "value": "off"}, {"label": qsTr("Screen"), "value": "screen"},
                {"label": qsTr("Webcam"), "value": "webcam"}, {"label": qsTr("Clipboard"), "value": "clipboard"}
            ]},
            {"key": "sensory_feedback_interval_seconds", "toolTip": qsTr("Minimum interval in seconds between eligible background sensory checks. Shorter intervals can increase capture and model-request work; the sensory policy still decides whether a check may run."), "label": qsTr("Check-in interval"), "description": qsTr("Seconds between eligible background checks."), "type": "number"},
            {"key": "sensory_pingpong_enabled", "toolTip": qsTr("Allow bounded follow-up sensory dialogue between checks. Off prevents this follow-up loop; normal user messages and explicit captures remain available."), "label": qsTr("Continue sensory dialogue"), "description": qsTr("Allow bounded follow-up context between sensory checks."), "type": "boolean"},
            {"key": "sensory_pingpong_history_depth", "toolTip": qsTr("Number of previous sensory turns considered by the follow-up policy. Larger histories retain more sensory context and can increase request size."), "label": qsTr("Sensory history depth"), "description": qsTr("Number of previous sensory turns available to the policy."), "type": "integer"},
            {"key": "sensory_allow_hidden_proactive_speech", "toolTip": qsTr("Allow a hidden sensory-awareness cycle to produce audible speech when the sensory policy permits it. Off keeps hidden checks from reaching normal speech playback."), "label": qsTr("Allow hidden proactive speech"), "description": qsTr("Permit a hidden awareness cycle to reach normal TTS when policy allows it."), "type": "boolean"},
            {"key": "sensory_allow_hidden_visual_generation", "toolTip": qsTr("Allow a hidden sensory-awareness cycle to request a generated image through Visual Reply. Enabling this can start image-generation work without a typed chat request."), "label": qsTr("Allow hidden visual generation"), "description": qsTr("Permit a hidden awareness cycle to request a visual reply."), "type": "boolean"}
        ]
    }

    function visionSecondarySchema() {
        return [
            {"key": "screen_source_capture_screen_index", "toolTip": qsTr("Monitor captured by Screen Source. Select a screen from the currently available displays; this is separate from the window on which NC is displayed."), "label": qsTr("Screen selection"), "description": qsTr("Choose the monitor used by the existing Screen Source capture service."), "type": "choice", "options": root.bridge.screenOptions},
            {"key": "screen_source_auto_attach_next_user_turn", "toolTip": qsTr("Queue a fresh Screen Source image for the next user message when this attachment path is used. This does not enable continuous screen capture."), "label": qsTr("Attach fresh screen to next user turn"), "description": qsTr("Use the existing screen-source attachment queue for the next message."), "type": "boolean"}
        ]
    }

    function chatContextSchema() {
        return [
            {"key": "chat_context_window_messages", "toolTip": qsTr("Recent messages available to each new normal-chat model request. The minimum effective value is 4; 0 uses the default of 20. A Persona override has its own limit, where 0 can mean all messages. Saved history is not deleted by this setting."), "label": qsTr("Context messages"), "description": qsTr("Recent messages included in a normal provider request."), "type": "integer"},
            {"key": "chat_context_overflow_policy", "toolTip": qsTr("Rolling window sends the most recent messages within the context limit. In this build the Keep all choice falls back to rolling-window behavior, so it does not increase the request context. Saved chat history is separate."), "label": qsTr("Overflow policy"), "description": qsTr("How older chat context is handled."), "type": "choice", "options": [
                {"label": qsTr("Rolling window"), "value": "rolling_window"}, {"label": qsTr("Keep all"), "value": "keep_all"}
            ]},
            {"key": "stored_chat_history_limit", "toolTip": qsTr("Maximum messages retained in NC conversation history. 0 keeps unlimited history. A positive limit can remove older messages from the in-memory conversation; save important context before reducing it."), "label": qsTr("Stored history limit"), "description": qsTr("0 keeps the established unlimited behavior."), "type": "integer"}
        ]
    }

    function chatDisplaySchema() {
        return [
            {"key": "chat_visual_batch_size", "toolTip": qsTr("Number of nearby conversation messages displayed in each visual batch while scrolling. -1 displays all rows. This affects rendering and memory use, not saved history or model context."), "label": qsTr("Chat messages per visual batch"), "description": qsTr("Loads nearby messages in batches as you scroll and releases distant display rows. -1 shows all messages. Saved history and LLM context are unchanged."), "type": "integer", "minimum": -1, "maximum": 2147483647},
            {"key": "chat_message_timestamps_enabled", "toolTip": qsTr("Show the saved timestamp beside each conversation message. This changes display only and does not alter the message content."), "label": qsTr("Show message timestamps"), "description": qsTr("Display the time for each message in the conversation."), "type": "boolean"}
        ]
    }

    function chatWritingSchema() {
        return [
            {"key": "spellcheck_enabled", "toolTip": qsTr("Underline potential spelling mistakes in supported writing fields and offer suggestions in their context menus. This does not automatically rewrite your text."), "label": qsTr("Spellcheck composer"), "type": "boolean"},
            {"key": "spellcheck_language", "toolTip": qsTr("Dictionary language code used by the spelling checker, such as en_US. A dictionary must be available for that language; this does not set the chat or speech-recognition language."), "label": qsTr("Spellcheck language"), "type": "text"}
        ]
    }

    function chatProactiveSchema() {
        return [
            {"key": "allow_proactive_replies", "toolTip": qsTr("Allow NC to start a reply after its configured idle conditions are met. Off waits for normal user-triggered replies; enabling this can generate model requests while you are quiet."), "label": qsTr("Allow proactive replies"), "type": "boolean"},
            {"key": "require_first_user_before_proactive", "toolTip": qsTr("Require a user message before proactive replies are eligible in a conversation. Turning it off allows proactive timing before the first user message when proactive replies are enabled."), "label": qsTr("Wait for the first user message"), "type": "boolean"},
            {"key": "listen_idle_window_seconds", "toolTip": qsTr("Seconds of listening inactivity used by the idle policy before proactive timing becomes eligible. This is separate from the additional proactive delay."), "label": qsTr("Listening idle window"), "description": qsTr("Seconds of quiet before proactive timing is considered."), "type": "number"},
            {"key": "proactive_delay_seconds", "toolTip": qsTr("Additional quiet-time delay in seconds before an eligible proactive reply. Longer delays reduce how quickly NC speaks without a new user message; proactive replies must also be enabled."), "label": qsTr("Proactive delay"), "type": "number"}
        ]
    }

    function storyPrimarySchema() {
        return [
            {"key": "visual_reply_story_mode", "toolTip": qsTr("Allow story replies to request images through the active Visual Reply provider. Requires a configured image provider and can create additional image-generation requests."), "label": qsTr("Story visual replies"), "description": qsTr("Allow story mode to request images through Visual Reply."), "type": "boolean"},
            {"key": "visual_reply_story_max_images", "toolTip": qsTr("Maximum number of images allowed for a story reply. Larger limits can increase image-generation time and provider cost."), "label": qsTr("Maximum story images"), "type": "integer"},
            {"key": "visual_reply_story_continuity_strength", "toolTip": qsTr("Influence of prior story visuals on later images, from 0 to 1. Higher values favor visual continuity when supported by the image-generation path."), "label": qsTr("Continuity strength"), "description": qsTr("0 to 1 influence of prior story visuals."), "type": "number"},
            {"key": "visual_reply_master_prompt_safe", "toolTip": qsTr("Include the story image prompt safety instructions when assembling the master visual prompt. This is prompt guidance, not a guarantee about the generated image."), "label": qsTr("Use safe master prompt"), "type": "boolean"},
            {"key": "visual_reply_master_prompt_no_speech_bubbles", "toolTip": qsTr("Ask the image model to avoid speech bubbles in story images. This adds prompt instructions and depends on the image model following them."), "label": qsTr("Avoid speech bubbles"), "type": "boolean"},
            {"key": "visual_reply_master_style_prompt", "toolTip": qsTr("Reusable visual style text appended when assembling story-image prompts. Use it for a consistent art style across future story images."), "label": qsTr("Master visual style"), "description": qsTr("Reusable visual style appended by the established story-image service."), "type": "multiline", "height": 132}
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
            title: root.sectionTitle
            description: root.sectionDescription
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space16
            Layout.rightMargin: Theme.NCMetrics.space16
            Layout.bottomMargin: Theme.NCMetrics.space16
            spacing: Theme.NCMetrics.space12
            visible: root.section !== "themes"

            NCSettingsGroup {
                Layout.fillWidth: true
                visible: root.section === "vision" || root.section === "story"
                title: root.section === "vision" ? qsTr("Ambient awareness")
                     : root.section === "story" ? qsTr("Story image behavior")
                     : ""
                description: root.section === "vision"
                             ? qsTr("Background checks remain subject to normal visibility and privacy policy.")
                             : ""
                schema: root.section === "vision" ? root.visionPrimarySchema()
                      : root.section === "story" ? root.storyPrimarySchema()
                      : []
                values: root.bridge.coreSettings
                onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
            }

            NCSettingsGroup {
                Layout.fillWidth: true
                visible: root.section === "vision"
                title: qsTr("Screen source")
                schema: root.visionSecondarySchema()
                values: root.bridge.coreSettings
                onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
            }

            NCCard {
                objectName: "chatBehaviorTabCard"
                Layout.fillWidth: true
                visible: root.section === "chat"
                contentSpacing: Theme.NCMetrics.space16

                Flow {
                    objectName: "chatBehaviorTabBar"
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space6

                    Repeater {
                        model: root.chatTabs

                        delegate: NCTabButton {
                            required property var modelData
                            objectName: "chatBehaviorTab_" + String(modelData.key)
                            tutorialBridge: root.bridge
                            tutorialContext: ({workspace: "runtime", runtime_section: "chat", chat_tab: String(modelData.key)})
                            text: String(modelData.label)
                            checked: root.currentChatTab === String(modelData.key)
                            onClicked: root.currentChatTab = String(modelData.key)
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 780 ? 2 : 1
                    columnSpacing: Theme.NCMetrics.space12
                    rowSpacing: Theme.NCMetrics.space12
                    visible: root.currentChatTab === "conversation"

                    NCSettingsGroup {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        title: qsTr("Context and history")
                        schema: root.chatContextSchema()
                        values: root.bridge.coreSettings
                        onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
                        NCMemoryContextWarning {
                            objectName: "memoryContextWarning"
                            Layout.fillWidth: true
                            values: root.bridge.coreSettings
                        }
                    }

                    NCSettingsGroup {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        title: qsTr("Display behavior")
                        schema: root.chatDisplaySchema()
                        values: root.bridge.coreSettings
                        onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 1
                    columnSpacing: Theme.NCMetrics.space12
                    rowSpacing: Theme.NCMetrics.space12
                    visible: root.currentChatTab === "writing"

                    NCSettingsGroup {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        title: qsTr("Writing assistance")
                        schema: root.chatWritingSchema()
                        values: root.bridge.coreSettings
                        onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
                    }
                }

                NCSettingsGroup {
                    Layout.fillWidth: true
                    visible: root.currentChatTab === "proactive"
                    title: qsTr("Proactive replies")
                    description: qsTr("Choose when NeuralCompanion may respond without a new message.")
                    schema: root.chatProactiveSchema()
                    values: root.bridge.coreSettings
                    onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
                }

                Loader {
                    Layout.fillWidth: true
                    active: root.section === "chat" && root.currentChatTab === "memory"
                    visible: active
                    sourceComponent: Component { MemoryWorkspace { bridge: root.bridge } }
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space16
            Layout.rightMargin: Theme.NCMetrics.space16
            Layout.bottomMargin: Theme.NCMetrics.space16
            columns: width >= 980 ? 3 : width >= 640 ? 2 : 1
            columnSpacing: Theme.NCMetrics.space12
            rowSpacing: Theme.NCMetrics.space12
            visible: root.section === "themes"

            Repeater {
                model: root.bridge.themeOptions
                delegate: NCCard {
                    id: themeCard
                    required property var modelData
                    Layout.fillWidth: true
                    selected: String(modelData.id) === Theme.NCTheme.currentPreset
                    title: String(modelData.label)
                    description: String(modelData.description)

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 72
                        radius: Theme.NCMetrics.radiusMedium
                        color: String(themeCard.modelData.swatch)
                        border.color: themeCard.selected ? Theme.NCTheme.focus : Theme.NCTheme.borderStrong
                        border.width: themeCard.selected ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                    }

                    NCButton {
                        Layout.fillWidth: true
                        text: themeCard.selected ? qsTr("Applied %1").arg(String(themeCard.modelData.label))
                                                 : qsTr("Apply %1").arg(String(themeCard.modelData.label))
                        tone: themeCard.selected ? "secondary" : "primary"
                        enabled: !themeCard.selected && !root.bridge.appearance.busy
                        onClicked: root.bridge.appearance.selectPreset(String(themeCard.modelData.id))
                    }
                }
            }
        }
        Loader {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space16
            Layout.rightMargin: Theme.NCMetrics.space16
            Layout.bottomMargin: Theme.NCMetrics.space16
            active: root.section === "themes"
            visible: active
            sourceComponent: Component {
                NCAppearanceEditor { controller: root.bridge.appearance }
            }
        }
    }
}
