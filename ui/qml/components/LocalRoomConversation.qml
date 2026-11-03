pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme
import "ConversationText.js" as ConversationText
import "../workspaces/ConversationSpeechSync.js" as SpeechSync

Rectangle {
    id: root
    objectName: "localRoomConversation"
    property var appearanceBridge: null
    readonly property int messageFontPixels: appearanceBridge && appearanceBridge.conversationFontSize !== undefined
        ? Math.round(Number(appearanceBridge.conversationFontSize || 12) * 4 / 3) : 14
    readonly property bool timestampsEnabled: appearanceBridge && appearanceBridge.conversationTimestampsEnabled !== undefined
        ? Boolean(appearanceBridge.conversationTimestampsEnabled) : true
    readonly property bool messageBordersEnabled: appearanceBridge && appearanceBridge.conversationMessageBordersEnabled !== undefined
        ? Boolean(appearanceBridge.conversationMessageBordersEnabled) : true
    readonly property string messageFontFamily: appearanceBridge && appearanceBridge.conversationMessageFontFamily
        ? String(appearanceBridge.conversationMessageFontFamily) : Theme.NCTypography.family
    readonly property color messageTextColor: appearanceBridge && appearanceBridge.conversationMessageTextColor
        ? appearanceBridge.conversationMessageTextColor : Theme.NCTheme.text
    readonly property bool transparentCards: appearanceBridge && appearanceBridge.conversationTransparentMessageCardsEnabled !== undefined
        ? Boolean(appearanceBridge.conversationTransparentMessageCardsEnabled) : false
    readonly property real responseWidthRatio: appearanceBridge && appearanceBridge.conversationResponseWidthRatio !== undefined
        ? Math.max(0.35, Math.min(0.96, Number(appearanceBridge.conversationResponseWidthRatio))) : 0.68
    readonly property real userWidthRatio: appearanceBridge && appearanceBridge.conversationUserWidthRatio > 0
        ? Math.max(0.28, Math.min(0.92, Number(appearanceBridge.conversationUserWidthRatio))) : 0
    readonly property int responseMinHeight: appearanceBridge && appearanceBridge.conversationResponseMinHeight !== undefined
        ? Math.max(96, Math.min(420, Number(appearanceBridge.conversationResponseMinHeight))) : 0
    readonly property int userMinHeight: appearanceBridge && appearanceBridge.conversationUserMinHeight !== undefined
        ? Math.max(96, Math.min(420, Number(appearanceBridge.conversationUserMinHeight))) : 0
    readonly property bool bionicReading: Boolean(appearanceBridge && appearanceBridge.conversationBionicReadingEnabled)
    readonly property string speechMode: appearanceBridge && appearanceBridge.conversationSpeechHighlightMode
        ? String(appearanceBridge.conversationSpeechHighlightMode) : "off"
    readonly property string speechStyle: appearanceBridge && appearanceBridge.conversationSpeechHighlightStyle
        ? String(appearanceBridge.conversationSpeechHighlightStyle) : "classic"
    property var entries: []
    property string conversationId: ""
    property var savedViewport: ({})
    property bool fullPage: false
    property bool bubbles: false
    property bool expanded: false
    property bool enlarged: false
    property bool autoScrollEnabled: true
    property bool followingLatest: true
    property int unreadCount: 0
    property var readingState: ({})
    property bool ready: false
    property bool applying: false
    property int latestPassesRemaining: 0
    property string modelConversationId: ""
    property var pendingRestore: ({})
    signal toggleRequested()
    signal enlargeRequested()
    signal viewportChanged(var value)
    implicitHeight: heading.implicitHeight + 20 + (expanded ? chatBody.implicitHeight + 10 : 0)
    radius: 10; color: fullPage ? "transparent" : Theme.NCTheme.window
    border.color: fullPage ? "transparent" : Theme.NCTheme.borderStrong

    ListModel { id: rows }

    function rowAt(index) {
        const entry = entries[index] || ({})
        return {messageId: String(entry.id !== undefined ? entry.id : index),
                author: String(entry.name || "Room"), body: String(entry.text || ""),
                stamp: String(entry.time || entry.timestamp || ""), messageRole: String(entry.role || ""),
                speechActive: Boolean(entry.speech_active), speechProgress: Number(entry.speech_progress || 0),
                spokenText: String(entry.spoken_text || ""), spokenPrefix: String(entry.spoken_prefix || ""),
                displayPending: Boolean(entry.display_pending)}
    }
    function sameViewport(first, second) {
        // QVariantMap round-trips reorder keys; compare values rather than JSON key order.
        const keys = Object.keys(first || ({}))
        return keys.length === Object.keys(second || ({})).length
            && keys.every(key => first[key] === second[key])
    }
    function captureViewport() {
        if (!ready || applying || !expanded) return
        let index = -1
        for (let dy = 1; dy <= 33 && index < 0; dy += 4)
            index = messages.indexAt(1, messages.contentY + dy)
        const item = index >= 0 ? messages.itemAtIndex(index) : null
        readingState = {anchor_id: index >= 0 ? rows.get(index).messageId : "",
            anchor_offset: item ? messages.contentY - item.y : 0,
            content_y: messages.contentY, follow_latest: followingLatest, unread_count: unreadCount,
            auto_scroll: autoScrollEnabled}
        viewportChanged(readingState)
    }
    function setAutoScrollEnabled(enabled) {
        autoScrollEnabled = enabled
        if (enabled) atLatest()
        else {
            latest.stop()
            latestPassesRemaining = 0
            followingLatest = false
            captureViewport()
        }
    }
    function scheduleLatest() {
        latestPassesRemaining = 4
        latest.restart()
    }
    function atLatest() {
        latestPassesRemaining = 4
        settleLatest()
        Qt.callLater(function() {
            if (root.latestPassesRemaining > 0 && root.ready && root.expanded) root.settleLatest()
        })
    }
    function positionAtEnd() {
        messages.positionViewAtEnd()
        // Like Main chat, include the canvas's bottom gutter in the final offset.
        // ListView's contentHeight is estimated after jumping over unloaded
        // rich-text rows. Prefer the now-instantiated final card's real edge.
        const last = rows.count > 0 ? messages.itemAtIndex(rows.count - 1) : null
        if (last)
            messages.contentY = Math.max(messages.originY,
                last.y + last.height - messages.height + messages.bottomMargin)
        else if (messages.bottomMargin > 0)
            messages.contentY = messages.originY + Math.max(0,
                messages.contentHeight - messages.height + messages.bottomMargin)
    }
    function settleLatest() {
        applying = true
        messages.forceLayout()
        positionAtEnd()
        // Positioning may instantiate a taller last delegate after a font change.
        messages.forceLayout()
        positionAtEnd()
        followingLatest = autoScrollEnabled
        unreadCount = 0
        applying = false
        captureViewport()
        // Revealing a variable-height delegate can require another layout frame.
        // Bound the work so estimated ListView heights cannot keep a timer alive.
        // atYEnd can be true before newly instantiated rich-text delegates
        // finish their layout. Complete the bounded passes even at that point.
        latestPassesRemaining = Math.max(0, latestPassesRemaining - 1)
        if (latestPassesRemaining > 0) latest.restart()
        else latest.stop()
    }
    function restoreViewport() {
        if (!expanded || width <= 0) return
        applying = true
        messages.forceLayout()
        const view = pendingRestore || ({})
        autoScrollEnabled = view.auto_scroll !== false
        followingLatest = autoScrollEnabled && view.follow_latest !== false
        unreadCount = Number(view.unread_count || 0)
        if (followingLatest) {
            positionAtEnd()
        } else {
            let index = -1
            for (let i = 0; i < rows.count; ++i)
                if (rows.get(i).messageId === String(view.anchor_id || "")) { index = i; break }
            if (index >= 0) {
                messages.positionViewAtIndex(index, ListView.Beginning)
                messages.forceLayout()
                const item = messages.itemAtIndex(index)
                if (item) messages.contentY = item.y + Number(view.anchor_offset || 0)
            } else {
                messages.contentY = Math.max(messages.originY, Math.min(
                    Number(view.content_y || 0), messages.originY + messages.contentHeight - messages.height))
            }
        }
        ready = true
        applying = false
        captureViewport()
        if (followingLatest) scheduleLatest()
    }
    function syncEntries() {
        const changedRoom = modelConversationId !== conversationId
        const previousCount = rows.count
        let messagesChanged = changedRoom || previousCount !== entries.length
        applying = true
        if (changedRoom) {
            rows.clear()
            modelConversationId = conversationId
            ready = false
            readingState = ({})
            followingLatest = true
            unreadCount = 0
            pendingRestore = savedViewport || ({})
        }
        // Stable rows preserve delegates, selection and the viewport on append.
        let common = 0
        const count = entries.length
        while (common < Math.min(rows.count, count)
                && rows.get(common).messageId === rowAt(common).messageId) ++common
        if (common < rows.count) {
            messagesChanged = true
            rows.remove(common, rows.count - common)
        }
        for (let i = 0; i < count; ++i) {
            const value = rowAt(i)
            if (i >= rows.count) rows.append(value)
            else {
                const old = rows.get(i)
                if (old.body !== value.body) {
                    messagesChanged = true
                    rows.setProperty(i, "body", value.body)
                }
                if (old.author !== value.author) rows.setProperty(i, "author", value.author)
                if (old.stamp !== value.stamp) rows.setProperty(i, "stamp", value.stamp)
                if (old.displayPending !== value.displayPending) messagesChanged = true
                for (const key of ["messageRole", "speechActive", "speechProgress", "spokenText", "spokenPrefix", "displayPending"])
                    if (old[key] !== value[key]) rows.setProperty(i, key, value[key])
            }
        }
        if (!changedRoom && !followingLatest) unreadCount += Math.max(0, count - previousCount)
        // The full-page switch explicitly controls whether new speech follows the end.
        // Status-only refreshes and the embedded room reader keep their current position.
        if (fullPage && autoScrollEnabled && messagesChanged) followingLatest = true
        if (!autoScrollEnabled && !changedRoom && messagesChanged) {
            latest.stop()
            latestPassesRemaining = 0
        }
        applying = false
        if (!ready) {
            pendingRestore = savedViewport || ({})
            initialise.restart()
        } else if (messagesChanged && followingLatest) scheduleLatest()
        else if (messagesChanged) captureViewport()
    }
    onMessageFontPixelsChanged: {
        if (ready && expanded) {
            if (followingLatest) scheduleLatest()
            else { pendingRestore = readingState; initialise.restart() }
        }
    }
    onEntriesChanged: syncEntries()
    onConversationIdChanged: syncEntries()
    onSavedViewportChanged: {
        if (!sameViewport(savedViewport, readingState)) {
            pendingRestore = savedViewport
            ready = false
            initialise.restart()
        }
    }
    onExpandedChanged: {
        if (expanded) {
            if (!ready) initialise.restart()
            else { pendingRestore = Object.assign({}, readingState, {unread_count: unreadCount}); initialise.restart() }
        }
    }
    onWidthChanged: {
        if (expanded && width > 0) {
            if (ready) { pendingRestore = readingState; ready = false }
            initialise.restart()
        }
    }
    Component.onCompleted: { syncEntries(); initialise.restart() }
    Timer { id: initialise; interval: 0; onTriggered: root.restoreViewport() }
    Timer { id: latest; interval: 16; onTriggered: if (root.ready && root.expanded) root.settleLatest() }

    ColumnLayout {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.bottom: root.fullPage ? parent.bottom : undefined
        anchors.margins: root.fullPage ? 0 : 10; spacing: 10
        RowLayout {
            id: heading
            visible: !root.fullPage
            Layout.fillWidth: true
            NCButton {
                objectName: "localRoomChatToggle"
                text: (root.expanded ? "▾ " : "▸ ") + qsTr("Conversation") + " · " + rows.count
                tone: "quiet"; Layout.fillWidth: true
                toolTipText: qsTr("The shared conversation in this Local room")
                onClicked: root.toggleRequested()
            }
            NCButton {
                objectName: "localRoomConversationEnlarge"
                visible: root.expanded; compact: true; tone: "quiet"
                text: root.enlarged ? qsTr("Restore") : qsTr("Enlarge")
                onClicked: root.enlargeRequested()
            }
        }
        ColumnLayout {
            id: chatBody
            Layout.fillWidth: true; Layout.fillHeight: root.fullPage
            visible: root.expanded; spacing: 6
            Label {
                visible: !root.followingLatest
                Layout.fillWidth: true; text: qsTr("Reading earlier messages · your position is kept")
                color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
            }
            Item {
                Layout.fillWidth: true; Layout.fillHeight: root.fullPage
                implicitHeight: root.enlarged ? 540 : 350
                NCConversationBackdrop {
                    id: roomBackdrop
                    objectName: "roomConversationBackdrop"
                    anchors.fill: parent
                    visible: root.fullPage
                    style: root.appearanceBridge && root.appearanceBridge.conversationCanvasStyle
                        ? root.appearanceBridge.conversationCanvasStyle : "original"
                    backgroundUrl: root.appearanceBridge && root.appearanceBridge.conversationBackgroundUrl
                        ? root.appearanceBridge.conversationBackgroundUrl : ""
                }
                ListView {
                    id: messages
                    objectName: "localRoomMessages"
                    anchors.fill: parent
                    anchors.margins: root.fullPage ? roomBackdrop.frameInset
                        + (roomBackdrop.frameVisible ? Theme.NCMetrics.space4 : 0) : 0
                    clip: true; spacing: root.fullPage ? Theme.NCMetrics.space10 : 14
                    bottomMargin: root.fullPage ? Theme.NCMetrics.space24 : 0
                    model: rows; reuseItems: true
                    opacity: root.ready ? 1 : 0
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}
                    LocalRoomScrollWheel { viewport: messages }
                    onContentYChanged: {
                        if (root.ready && !root.applying && root.expanded) {
                            // A reader navigation supersedes any pending tail
                            // settling; our own positioning is guarded by applying.
                            latest.stop()
                            root.latestPassesRemaining = 0
                            root.followingLatest = root.autoScrollEnabled && (atYEnd || contentHeight <= height)
                            if (root.followingLatest) root.unreadCount = 0
                            root.captureViewport()
                        }
                    }
                    onContentHeightChanged: if (root.ready && root.followingLatest && !root.applying
                            && root.latestPassesRemaining > 0) latest.restart()
                    onHeightChanged: if (root.ready && root.followingLatest) root.scheduleLatest()
                    delegate: Item {
                        id: messageRow
                        required property int index
                        required property string messageId
                        required property string author
                        required property string body
                        required property string stamp
                        required property string messageRole
                        required property bool speechActive
                        required property real speechProgress
                        required property string spokenText
                        required property string spokenPrefix
                        required property bool displayPending
                        width: messages.width
                        height: message.height
                        // A jump can realize the final card before ListView
                        // corrects its estimated position. Follow that correction
                        // within this bounded settling request, even with Auto-scroll Off.
                        onYChanged: {
                            if (index === rows.count - 1 && root.latestPassesRemaining > 0 && !root.applying) {
                                root.applying = true
                                messages.contentY = Math.max(messages.originY,
                                    y + height - messages.height + messages.bottomMargin)
                                root.applying = false
                            }
                        }
                        onHeightChanged: {
                            if (index === rows.count - 1 && root.latestPassesRemaining > 0 && !root.applying) {
                                root.applying = true
                                messages.contentY = Math.max(messages.originY,
                                    y + height - messages.height + messages.bottomMargin)
                                root.applying = false
                            }
                        }
                    NCConversationMessageCard {
                        id: message
                        objectName: "localRoomMessageCard_" + messageId
                        readonly property string messageId: messageRow.messageId
                        readonly property string author: messageRow.author
                        readonly property string body: messageRow.body
                        readonly property string stamp: messageRow.stamp
                        readonly property bool userEntry: ["user", "human"].indexOf(messageRow.messageRole) >= 0
                        assistantResponse: !userEntry
                        assistantBorderColor: Theme.NCTheme.borderStrong
                        bordersEnabled: root.bubbles && root.messageBordersEnabled
                        transparentCards: root.fullPage && root.transparentCards
                        x: root.fullPage ? userEntry ? messages.width - width - Theme.NCMetrics.space24 : Theme.NCMetrics.space24 : 0
                        readonly property real cardAreaWidth: Math.max(0, messages.width - Theme.NCMetrics.space48)
                        width: root.fullPage ? userEntry
                            ? root.userWidthRatio > 0
                                ? Math.min(cardAreaWidth * 0.92, Math.max(260, cardAreaWidth * root.userWidthRatio))
                                : Math.min(cardAreaWidth * 0.86, Math.max(260, roomMessageText.naturalTextWidth + Theme.NCMetrics.space24))
                            : Math.min(cardAreaWidth * 0.96, Math.max(360, cardAreaWidth * root.responseWidthRatio))
                            : root.bubbles ? Math.min(messages.width - 18, Math.max(260, messages.width * 0.84)) : messages.width - 18
                        height: Math.max(messageBody.implicitHeight + (root.bubbles ? contentPadding * 2 : 0),
                            root.fullPage ? userEntry ? root.userMinHeight : root.responseMinHeight : 0)
                        radius: root.bubbles ? 12 : 0
                        // Embedded readers keep their established compact surface;
                        // full-page cards retain the shared Main chat bindings.
                        Binding {
                            target: message; property: "color"; when: !root.fullPage
                            value: root.bubbles ? Theme.NCTheme.windowRaised : "transparent"
                            restoreMode: Binding.RestoreBinding
                        }
                        Binding {
                            target: message.border; property: "color"; when: !root.fullPage
                            value: Theme.NCTheme.borderStrong
                            restoreMode: Binding.RestoreBinding
                        }
                        Column {
                            id: messageBody
                            x: root.bubbles ? message.contentPadding : 0
                            y: root.bubbles ? message.contentPadding : 0
                            width: parent.width - (root.bubbles ? message.contentPadding * 2 : 0); spacing: 4
                            RowLayout {
                                width: parent.width; spacing: Theme.NCMetrics.space6
                                Label {
                                    Layout.fillWidth: true; Layout.minimumWidth: 0; elide: Text.ElideRight
                                    text: message.author; textFormat: Text.PlainText
                                    color: message.assistantResponse ? Theme.NCTheme.accent : Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.microSize
                                    font.weight: Theme.NCTypography.bold; font.letterSpacing: 0.7
                                }
                                Label {
                                    objectName: "localRoomMessageTimestamp_" + message.messageId
                                    visible: root.timestampsEnabled && message.stamp.length > 0
                                    text: message.stamp; textFormat: Text.PlainText
                                    color: Theme.NCTheme.textMuted; font.pixelSize: 11
                                }
                            }
                            NCSpeechHighlightText {
                                id: roomMessageText
                                objectName: "localRoomMessageText_" + message.messageId
                                width: parent.width
                                plainText: messageRow.displayPending
                                    ? messageRow.speechActive ? qsTr("Speaking…") : qsTr("Preparing reply…") : message.body
                                preserveSelection: true
                                readonly property var speechBounds: SpeechSync.spokenWordBounds(plainText,
                                    messageRow.speechProgress, messageRow.spokenText, messageRow.spokenPrefix)
                                highlightActive: !message.userEntry && root.speechMode !== "off"
                                    && !messageRow.displayPending && messageRow.speechActive && speechBounds.end > speechBounds.start
                                renderedText: highlightActive
                                    ? ConversationText.highlightedMessageText(plainText, root.speechMode,
                                        root.speechStyle, messageRow.speechProgress, messageRow.spokenText,
                                        bionicReading, {text: String(root.messageTextColor),
                                            muted: String(Theme.NCTheme.textMuted), accent: String(Theme.NCTheme.accent),
                                            selected: String(Theme.NCTheme.surfaceSelected)}, messageRow.spokenPrefix)
                                    : ConversationText.conversationMessageRichText(plainText, bionicReading)
                                bionicReading: root.bionicReading && !messageRow.displayPending
                                highlightStart: Number(speechBounds.start || 0)
                                highlightEnd: Number(speechBounds.end || 0)
                                highlightStyle: root.speechStyle
                                textColor: root.messageTextColor
                                textPixelSize: root.messageFontPixels
                                fontFamily: root.messageFontFamily
                            }
                        }
                    }
                    }
                }
                Label {
                    anchors.centerIn: parent; visible: rows.count === 0
                    text: qsTr("The room conversation will appear here.")
                    color: Theme.NCTheme.textMuted
                }
                NCButton {
                    objectName: "localRoomLatest"
                    anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter
                    visible: !root.followingLatest
                    text: root.unreadCount > 0 ? qsTr("↓ %1 new messages").arg(root.unreadCount) : qsTr("↓ Back to latest")
                    tone: "primary"; compact: true
                    onClicked: root.atLatest()
                }
            }
        }
    }
}
