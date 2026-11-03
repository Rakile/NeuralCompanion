pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../components"
import "../theme" as Theme

Item {
    id: root
    objectName: "localRoomConversationPage"
    required property var session
    property var appearanceBridge: null
    readonly property string viewId: "room-conversation-" + Date.now() + "-" + Math.random().toString(36).slice(2)
    readonly property var viewWindow: root.Window.window
    readonly property bool viewVisible: visible && Boolean(viewWindow) && viewWindow.visible
                                        && viewWindow.visibility !== Window.Minimized
    property var registeredSession: null

    function updateViewVisibility() {
        if (registeredSession && (registeredSession !== session || !viewVisible)) {
            if (typeof registeredSession.setViewVisible === "function") registeredSession.setViewVisible(viewId, false)
            registeredSession = null
        }
        if (viewVisible && session && registeredSession !== session
                && typeof session.setViewVisible === "function") {
            registeredSession = session
            session.setViewVisible(viewId, true)
        }
    }
    onViewVisibleChanged: updateViewVisibility()
    onSessionChanged: updateViewVisibility()
    readonly property var room: session ? session.state : ({})
    readonly property bool discordMode: room.mode === "discord"
    readonly property string roomKey: String(room.room_key || room.mode || "local")
    readonly property string roomTitle: discordMode ? qsTr("Discord room") : qsTr("Local room")
    readonly property var conversation: room.conversation || ({})
    readonly property string phase: String(room.phase || "unavailable")
    readonly property bool active: phase === "running" || phase === "starting"
    readonly property bool stopping: Boolean(room.stopping)
    readonly property bool busy: Boolean(session && session.busy)
    readonly property string errorText: String(room.error || (session && session.confirmation.error) || "")
    readonly property bool canSend: phase === "running" && (discordMode || Boolean(room.joined)) && !Boolean(room.paused) && !stopping && !busy
        && (!discordMode || room.text_sender_available !== false)

    onRoomKeyChanged: {
        draftSave.stop()
        draft.text = session ? String(session.draft || "") : ""
    }
    function participantName(id) {
        const participants = room.participants || []
        for (let i = 0; i < participants.length; ++i)
            if (String(participants[i].id) === String(id)) return String(participants[i].name || id)
        return id ? String(id) : qsTr("—")
    }
    function persistDraft() {
        draftSave.stop()
        if (session && String(session.draft || "") !== draft.text) session.setDraft(draft.text)
    }
    function sendDraft() {
        if (!canSend || !draft.text.trim()) return
        if (discordMode ? session.send(draft.text, String(textSender.currentValue || "")) : session.send(draft.text)) {
            draft.text = ""
            persistDraft()
        }
    }
    Component.onCompleted: {
        draft.text = session ? String(session.draft || "") : ""
        updateViewVisibility()
    }
    Component.onDestruction: {
        persistDraft()
        if (registeredSession && typeof registeredSession.setViewVisible === "function")
            registeredSession.setViewVisible(viewId, false)
    }
    onVisibleChanged: if (!visible) persistDraft()
    Connections {
        target: root.session || null
        function onDraftChanged() {
            if (!draftSave.running && draft.text !== root.session.draft) draft.text = root.session.draft
        }
    }
    Timer { id: draftSave; interval: 350; onTriggered: root.persistDraft() }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.NCMetrics.space12
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: header.implicitHeight + 24
            radius: Theme.NCMetrics.radiusMedium; color: Theme.NCTheme.windowRaised; border.color: Theme.NCTheme.border
            ColumnLayout {
                id: header
                anchors.fill: parent; anchors.margins: 12; spacing: 8
                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space12
                    ColumnLayout {
                        width: 145
                        spacing: Theme.NCMetrics.space2
                        Label { text: root.roomTitle; font.pixelSize: Theme.NCTypography.headingSize; font.weight: Theme.NCTypography.semibold; color: Theme.NCTheme.text }
                        Label {
                            Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText
                            text: String(root.conversation.topic || "")
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                            NCToolTip { visible: topicHover.hovered; text: String(root.conversation.topic || "") }
                            HoverHandler { id: topicHover }
                        }
                    }
                    NCButton {
                        objectName: "conversationSourceMain"
                        text: qsTr("\u2190  Go to Main Chat")
                        width: 160; height: Theme.NCMetrics.iconButtonSize; compact: true
                        enabled: Boolean(root.session)
                        onClicked: root.session.showMain()
                    }
                    NCButton {
                        objectName: "roomConversationControls"; text: qsTr("Room controls"); compact: true
                        onClicked: root.session.openRoomControls()
                    }
                }
                Flow {
                    Layout.fillWidth: true; spacing: 12
                    Label {
                        objectName: "roomConversationNow"
                        text: qsTr("Now: %1").arg(root.participantName(root.room.current_id))
                        color: Theme.NCTheme.text; textFormat: Text.PlainText
                    }
                    Label {
                        objectName: "roomConversationNext"
                        text: qsTr("Next: %1").arg(root.participantName(root.room.next_id))
                        color: Theme.NCTheme.textSecondary; textFormat: Text.PlainText
                    }
                    Label {
                        text: root.stopping ? qsTr("Finishing the current speaker, then stopping…")
                            : root.room.pausing ? qsTr("Pausing after the current speaker…")
                            : root.room.paused ? qsTr("Room paused")
                            : root.phase === "running" ? qsTr("Room running")
                            : root.phase === "starting" ? qsTr("Starting room…") : qsTr("Room stopped")
                        color: Theme.NCTheme.textMuted
                    }
                }
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    NCButton {
                        objectName: "roomConversationPause"; compact: true
                        text: root.room.paused ? qsTr("Resume") : qsTr("Pause")
                        enabled: root.phase === "running" && !root.stopping && !root.busy
                        onClicked: root.session.control(root.room.paused ? "resume" : "pause")
                    }
                    NCButton {
                        objectName: "roomConversationStop"; compact: true
                        text: root.stopping ? qsTr("Stopping…") : root.active ? qsTr("Stop") : qsTr("Continue")
                        enabled: !root.stopping && !root.busy && root.phase !== "starting"
                                 && (root.active || Boolean(root.conversation.has_history))
                        onClicked: root.session.control(root.active ? "stop" : "continue")
                    }
                    NCButton {
                        id: appearanceButton
                        objectName: "roomConversationAppearance"; compact: true
                        text: qsTr("Appearance"); enabled: Boolean(root.appearanceBridge)
                        onClicked: {
                            appearanceLoader.active = true
                            appearanceLoader.item.openFor(appearanceButton)
                        }
                    }
                    NCButton {
                        id: readingButton
                        objectName: "roomConversationSpeechOptions"; compact: true
                        text: qsTr("Text and speech"); enabled: Boolean(root.appearanceBridge)
                        onClicked: readingPopup.openFor(readingButton)
                    }
                    NCSwitch {
                        toolTipText: qsTr("Follow new room messages automatically. Turn off to keep your reading position while the conversation continues.")

                        objectName: "roomConversationAutoScroll"
                        text: checked ? qsTr("Auto-scroll On") : qsTr("Auto-scroll Off")
                        checked: chat.autoScrollEnabled
                        onToggled: chat.setAutoScrollEnabled(checked)
                    }
                    Label {
                        width: Math.min(implicitWidth, header.width)
                        wrapMode: Text.WordWrap
                        text: root.discordMode ? qsTr("Use Discord for voice · typed messages enter NC's conversation; bot replies are audible in Discord") : !root.room.joined ? qsTr("Observing · join from Room controls to send")
                            : root.room.muted ? qsTr("Mic off · chat available") : qsTr("Joined")
                        color: Theme.NCTheme.textMuted; font.pixelSize: 12
                    }
                }
                Label {
                    Layout.fillWidth: true; visible: root.errorText.length > 0
                    text: root.errorText; textFormat: Text.PlainText
                    wrapMode: Text.Wrap; color: Theme.NCTheme.error
                }
            }
        }
        LocalRoomConversation {
            id: chat
            appearanceBridge: root.appearanceBridge
            Layout.fillWidth: true; Layout.fillHeight: true
            fullPage: true; bubbles: true; expanded: true
            entries: root.room.display_messages !== undefined ? root.room.display_messages : root.room.messages || []
            conversationId: root.roomKey + ":" + String(root.conversation.id || "")
            savedViewport: root.session ? root.session.viewport : ({})
            onViewportChanged: value => { if (root.session) root.session.saveViewport(value) }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: composerRow.implicitHeight + Theme.NCMetrics.space24
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.windowRaised; border.color: Theme.NCTheme.border
        RowLayout {
            id: composerRow
            anchors.fill: parent; anchors.margins: Theme.NCMetrics.space12
            spacing: Theme.NCMetrics.space8
            NCRoomTextSender {
                id: textSender
                objectName: "roomConversationTextSender"
                visible: root.discordMode; Layout.preferredWidth: 190
                room: root.room
                enabled: !root.busy && !root.stopping && root.phase !== "starting"
                onSenderSelected: senderId => root.session.setTextSender(senderId)
            }
            NCConversationComposerScroll {
                id: draftScroll
                objectName: "roomConversationDraftScroll"
                editor: draft
                NCTextArea {
                    id: draft; objectName: "roomConversationDraft"
                    implicitHeight: Math.max(draftScroll.minimumComposerHeight, contentHeight + topPadding + bottomPadding)
                    topPadding: Theme.NCMetrics.space8; bottomPadding: Theme.NCMetrics.space8
                    placeholderText: root.discordMode ? root.room.text_sender_name ? qsTr("Message as %1…").arg(String(root.room.text_sender_name)) : qsTr("Choose who is sending…") : root.room.joined ? qsTr("Message the Local room…") : qsTr("Join from Room controls to send a message")
                    onTextChanged: draftSave.restart()
                    Keys.onPressed: event => {
                        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                                && !(event.modifiers & Qt.ShiftModifier)) {
                            event.accepted = true
                            root.sendDraft()
                        }
                    }
                }
            }
            NCButton {
                Layout.alignment: Qt.AlignBottom
                objectName: "roomConversationSend"; text: qsTr("Send"); tone: "primary"
                enabled: root.canSend && draft.text.trim().length > 0
                onClicked: root.sendDraft()
            }
        }
        }
    }
    // Load the existing appearance editor when requested; older/test bridges may
    // expose only the subset of appearance settings needed by the transcript.
    Loader {
        id: appearanceLoader
        active: false
        sourceComponent: Component {
            NCConversationAppearancePopup { parent: root; bridge: root.appearanceBridge }
        }
    }
    NCConversationReadingPopup {
        id: readingPopup
        objectName: "roomConversationReadingPopup"
        bridge: root.appearanceBridge
    }
}
