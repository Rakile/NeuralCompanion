pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import "../components"
import "../theme" as Theme
import "ConversationSpeechSync.js" as SpeechSync
import "../components/ConversationText.js" as ConversationText

Rectangle {
    id: root
    objectName: "conversationWorkspace"

    required property var bridge
    readonly property var roomConversation: bridge.roomConversation || null
    readonly property bool roomConversationAvailable: Boolean(roomConversation && roomConversation.available)
    readonly property bool showingLocalRoom: Boolean(roomConversation && roomConversation.source === "local_room")
    // Dock moves can overlap old/new delegates; each owns its registration.
    readonly property string conversationViewId: "conversation-" + Math.random().toString(36).slice(2)
    property bool conversationViewDisposed: false
    property bool conversationViewReady: false
    property bool conversationViewPositionSaved: false
    readonly property bool conversationViewActive: !showingLocalRoom && !conversationViewDisposed && visible && Window.window !== null
                                                    && Window.window.visible
                                                    && Window.window.visibility !== Window.Minimized
    onConversationViewActiveChanged: {
        if (conversationViewReady) {
            if (conversationViewActive) {
                conversationViewPositionSaved = false
                restoreConversationViewPosition()
            } else {
                saveConversationViewPosition()
            }
        }
        bridge.setConversationViewVisible(conversationViewId, conversationViewActive)
    }
    property alias conversationComposer: composer
    readonly property var liveSession: bridge.liveSessionState
    property var messageDeletionSelection: ({})
    readonly property bool messageDeletionAvailable: bridge.conversationMessageDeletionAvailable
            && !bridge.conversationContextBusy && !bridge.conversationEditMode && inlineResponseEditIndex < 0
    readonly property var conversationActions: bridge.conversationActionsState

    function beginMessageDeletion(historyIndex) {
        const selection = bridge.prepareConversationMessageDeletion(historyIndex)
        if (!selection || !selection.messageId)
            return
        messageDeletionSelection = selection
        messageDeleteDialog.open()
    }
    readonly property var bufferState: liveSession.buffer || ({})
    readonly property var pendingAttachment: bridge.conversationAttachment || ({})
    readonly property var pendingImages: pendingAttachment.images || (pendingAttachment.active ? [pendingAttachment] : [])
    readonly property var visualReplyRuntimeState: bridge.visualReplyState || ({})
    readonly property string visualReplyRuntimeStatus: String(
                                                              visualReplyRuntimeState.status
                                                              || "idle").toLowerCase()
    readonly property bool consoleAutoScroll: Boolean(bridge.conversationConsoleAutoScroll)
    property var pendingConsoleAnchor: null
    property bool conversationAutoScroll: true
    property bool conversationNearBottom: true
    property bool loadingOlderMessages: false
    property bool olderMessagesScrollIntent: false
    property string observedNewestMessageId: ""
    property string observedNewestMessageContent: ""
    property bool conversationLayoutFollowPending: false
    property bool conversationLayoutFollowForced: false
    property bool conversationLayoutFollowSettled: false
    property int conversationLayoutFollowPasses: 0
    property bool userViewportMoved: false
    property bool browsingConversationHistory: !bridge.conversationFollowingLatest
    property var selectedMessageIds: ({})
    readonly property bool conversationWindowProtected: bridge.conversationEditMode
                                                       || inlineResponseEditIndex >= 0
                                                       || Object.keys(selectedMessageIds).length > 0
    property bool visualReplyFollowPending: false
    property bool visualReplyNoticeVisible: false
    property bool visualReplyFollowAnimating: false
    property string observedVisualReplyStatus: ""
    property string observedVisualReplyRequestId: ""
    property string completedVisualReplyRequestId: ""
    readonly property bool consoleVisible: Boolean(bridge.conversationConsoleVisible)
    property string avatarContextSection: "persona"
    property string visualReplyFocusUrl: ""
    property string visualReplyFocusPrompt: ""
    property string visualReplyFocusLabel: qsTr("Visual Reply")
    property real visualReplyFocusZoom: 1.0
    property var visualReplyContextAsset: ({})
    property string visualReplySaveSource: ""
    readonly property var conversationDraftState: bridge.conversationDraftState || ({})
    readonly property int inlineResponseEditIndex: Number(
                                                        conversationDraftState.inlineResponseHistoryIndex !== undefined
                                                        ? conversationDraftState.inlineResponseHistoryIndex : -1)
    readonly property string inlineResponseEditText: String(
                                                         conversationDraftState.inlineResponseText || "")
    readonly property string pendingUserDraftText: String(
                                                      conversationDraftState.copiedPromptText || "")
    readonly property var responseActionLayout: bridge.conversationResponseActionLayout || ({})
    readonly property var userActionLayout: bridge.conversationUserActionLayout || ({})
    property real responseFrameWidthRatio: Math.max(
                                                0.35,
                                                Math.min(
                                                    0.96,
                                                    Number(bridge.conversationResponseWidthRatio || 0.68)))
    property int responseFrameMinHeight: Math.max(
                                             96,
                                             Math.min(
                                                 420,
                                                 Number(bridge.conversationResponseMinHeight || 140)))
    property real userFrameWidthRatio: {
        const requested = Number(bridge.conversationUserWidthRatio || 0.0)
        return requested > 0.0
               ? Math.max(0.28, Math.min(0.92, requested)) : 0.0
    }
    property int userFrameMinHeight: Math.max(
                                         96,
                                         Math.min(
                                             420,
                                             Number(bridge.conversationUserMinHeight || 96)))
    readonly property int conversationFontPixels: Math.round(Number(bridge.conversationFontSize || 12) * 4 / 3)

    function saveResponseFrameSize() {
        bridge.setConversationResponseFrameSize(
                    responseFrameWidthRatio,
                    responseFrameMinHeight)
    }

    function saveUserFrameSize() {
        bridge.setConversationUserFrameSize(
                    userFrameWidthRatio,
                    userFrameMinHeight)
    }

    function syncComposerDraft() {
        const savedText = String(conversationDraftState.composerText || "")
        if (composer.text !== savedText)
            composer.text = savedText
    }

    function beginResponseEdit(message) {
        bridge.beginConversationInlineResponseDraft(
                    Number(message && message.historyIndex !== undefined
                           ? message.historyIndex : -1),
                    String(message && message.content || ""))
    }

    function cancelResponseEdit() {
        bridge.clearConversationInlineResponseDraft()
    }

    function saveResponseEdit() {
        if (inlineResponseEditIndex < 0)
            return
        const anchor = conversationViewportAnchor()
        let anchorHistoryIndex = -1
        if (anchor) {
            for (let i = 0; i < messageList.count; ++i) {
                if (String(messageList.model.get(i).messageId) === anchor.firstId) {
                    anchorHistoryIndex = Number(messageList.model.get(i).historyIndex)
                    break
                }
            }
            loadingOlderMessages = true
            messageList.cancelFlick()
            conversationFollowAnimation.stop()
            conversationLayoutFollowPending = false
            conversationViewportTimer.stop()
        }
        const saved = bridge.updateConversationMessage(
                    inlineResponseEditIndex,
                    inlineResponseEditText)
        if (saved) {
            cancelResponseEdit()
            // A revision-checked edit preserves row order, but an untagged
            // edited message can receive a new ID. Rebind only after success;
            // never use row position to anchor a rejected/stale edit.
            if (anchor) {
                for (let i = 0; i < messageList.count; ++i) {
                    if (Number(messageList.model.get(i).historyIndex) === anchorHistoryIndex) {
                        anchor.firstId = String(messageList.model.get(i).messageId)
                        break
                    }
                }
            }
        }
        if (anchor)
            restoreConversationAnchorLater(anchor, false, true)
    }

    function responseActionKeys(zoneName) {
        const configured = responseActionLayout
                           ? responseActionLayout[String(zoneName)] : null
        const values = []
        if (!configured || configured.length === undefined)
            return values
        for (let index = 0; index < configured.length; index += 1)
            values.push(String(configured[index]))
        return values
    }

    function responseActionRailKeys() {
        const values = []
        const zones = ["left", "center", "right"]
        for (let zoneIndex = 0; zoneIndex < zones.length; zoneIndex += 1) {
            const configured = responseActionKeys(zones[zoneIndex])
            for (let index = 0; index < configured.length; index += 1) {
                if (values.indexOf(configured[index]) < 0)
                    values.push(configured[index])
            }
        }
        return values
    }

    function responseActionLabel(actionKey) {
        if (String(actionKey) === "pause_speech" && Boolean(liveSession.paused))
            return qsTr("Play")
        const labels = {
            "pause_speech": qsTr("Pause"),
            "skip_speech": qsTr("Skip speech"),
            "skip_user_reply": qsTr("End waiting"),
            "copy": qsTr("Copy"),
            "replay": qsTr("Replay"),
            "edit": qsTr("Edit"),
            "delete": qsTr("Delete"),
            "regenerate": qsTr("Regenerate")
        }
        return String(labels[String(actionKey)] || qsTr("Action"))
    }

    function responseActionToolTip(actionKey) {
        if (String(actionKey) === "skip_speech"
                && responseActionAttention(actionKey))
            return qsTr("Skip the current speech to handle the queued reply")
        if (String(actionKey) === "pause_speech")
            return Boolean(liveSession.paused)
                    ? qsTr("Resume the active response")
                    : qsTr("Pause the active response")
        const labels = {
            "skip_speech": qsTr("Skip the current spoken response"),
            "skip_user_reply": qsTr("Skip waiting for the user reply"),
            "copy": qsTr("Copy this response"),
            "replay": qsTr("Replay this response with text-to-speech"),
            "edit": qsTr("Edit this response"),
            "delete": qsTr("Delete this message and its attachments"),
            "regenerate": qsTr("Regenerate the latest assistant response")
        }
        return String(labels[String(actionKey)] || qsTr("Conversation action"))
    }

    function responseActionIconKey(actionKey) {
        const key = String(actionKey)
        return key === "pause_speech" && Boolean(liveSession.paused)
                ? "resume_speech" : key
    }

    function responseActionAttention(actionKey) {
        return String(actionKey) === "skip_speech"
                && Boolean(liveSession.playbackActive)
                && String(conversationActions.disabled_reason || "")
                   === "manual_input_pending"
    }

    function responseActionVisible(actionKey, message) {
        const key = String(actionKey)
        const latest = Boolean(message && message.isLatestAssistant)
        if (key === "pause_speech" || key === "skip_speech"
                || key === "skip_user_reply"
                || key === "regenerate")
            return latest
        return key === "copy" || key === "replay" || key === "edit" || key === "delete"
    }

    function responseActionSelected(actionKey, message) {
        return String(actionKey) === "edit"
                && inlineResponseEditIndex
                   === Number(message && message.historyIndex !== undefined
                              ? message.historyIndex : -1)
    }

    function responseActionEnabled(actionKey, message) {
        const key = String(actionKey)
        const editing = inlineResponseEditIndex
                        === Number(message && message.historyIndex !== undefined
                                   ? message.historyIndex : -1)
        if (inlineResponseEditIndex >= 0)
            return key === "edit" && editing
        if (key === "delete")
            return messageDeletionAvailable
        if (key === "edit")
            return true
        if (key === "copy")
            return true
        return bridge.systemRunning
    }

    function triggerResponseAction(actionKey, message) {
        const key = String(actionKey)
        if (!responseActionEnabled(key, message))
            return
        const historyIndex = Number(
                    message && message.historyIndex !== undefined
                    ? message.historyIndex : -1)
        if (key === "copy") {
            bridge.copyConversationMessage(historyIndex)
        } else if (key === "delete") {
            beginMessageDeletion(historyIndex)
        } else if (key === "replay") {
            bridge.replayConversationMessage(historyIndex)
        } else if (key === "edit") {
            if (inlineResponseEditIndex === historyIndex)
                saveResponseEdit()
            else
                beginResponseEdit(message)
        } else if (key === "regenerate") {
            bridge.triggerRuntimeAction("regenerate_response")
        } else {
            bridge.triggerRuntimeAction(key)
        }
    }

    function placeResponseAction(actionKey, targetZone, targetIndex) {
        const zones = ["left", "center", "right"]
        const nextLayout = ({
            "left": responseActionKeys("left"),
            "center": responseActionKeys("center"),
            "right": responseActionKeys("right")
        })
        let sourceZone = ""
        let sourceIndex = -1
        for (let zoneIndex = 0; zoneIndex < zones.length; zoneIndex += 1) {
            const zone = zones[zoneIndex]
            const index = nextLayout[zone].indexOf(String(actionKey))
            if (index >= 0) {
                sourceZone = zone
                sourceIndex = index
                nextLayout[zone].splice(index, 1)
                break
            }
        }
        if (!sourceZone || zones.indexOf(String(targetZone)) < 0)
            return
        let requestedIndex = Number(targetIndex)
        if (sourceZone === String(targetZone) && sourceIndex < requestedIndex)
            requestedIndex -= 1
        const insertion = Math.max(
                    0,
                    Math.min(
                        requestedIndex,
                        nextLayout[String(targetZone)].length))
        nextLayout[String(targetZone)].splice(insertion, 0, String(actionKey))
        bridge.setConversationResponseActionLayout(nextLayout)
    }

    function placeResponseActionInRail(actionKey, targetIndex) {
        const next = responseActionRailKeys()
        const sourceIndex = next.indexOf(String(actionKey))
        if (sourceIndex < 0)
            return
        next.splice(sourceIndex, 1)
        let requestedIndex = Number(targetIndex)
        if (sourceIndex < requestedIndex)
            requestedIndex -= 1
        const insertion = Math.max(0, Math.min(requestedIndex, next.length))
        next.splice(insertion, 0, String(actionKey))
        bridge.setConversationResponseActionLayout({
                                                       "left": [],
                                                       "center": next,
                                                       "right": []
                                                   })
    }

    function userMessageActionKeys(zoneName) {
        const configured = userActionLayout
                           ? userActionLayout[String(zoneName)] : null
        const values = []
        if (!configured || configured.length === undefined)
            return values
        for (let index = 0; index < configured.length; index += 1)
            values.push(String(configured[index]))
        if (String(zoneName) === "right" && values.indexOf("end_waiting") < 0)
            values.push("end_waiting")
        return values
    }

    function userMessageActionRailKeys() {
        const values = []
        const zones = ["left", "center", "right"]
        for (let zoneIndex = 0; zoneIndex < zones.length; zoneIndex += 1) {
            const configured = userMessageActionKeys(zones[zoneIndex])
            for (let index = 0; index < configured.length; index += 1) {
                if (values.indexOf(configured[index]) < 0)
                    values.push(configured[index])
            }
        }
        return values
    }

    function userMessageActionLabel(actionKey) {
        const labels = {
            "copy": qsTr("Copy"),
            "edit_draft": qsTr("Edit"),
            "delete": qsTr("Delete"),
            "retry_user_input": qsTr("Retry input"),
            "end_waiting": qsTr("End waiting")
        }
        return String(labels[String(actionKey)] || qsTr("Action"))
    }

    function userMessageActionToolTip(actionKey) {
        const labels = {
            "copy": qsTr("Copy this message"),
            "edit_draft": qsTr("Edit this message"),
            "delete": qsTr("Delete this message and its attachments"),
            "retry_user_input": qsTr("Retry the latest user input"),
            "end_waiting": qsTr("Reply to this user message")
        }
        return String(labels[String(actionKey)] || qsTr("User message action"))
    }

    function userMessageActionVisible(actionKey, message) {
        if (!Boolean(message && message.isUser))
            return false
        const key = String(actionKey)
        if (key === "retry_user_input")
            return Boolean(message.isLatestUser)
        if (key === "end_waiting")
            return Boolean(conversationActions.end_waiting && conversationActions.end_waiting.message_id === message.messageId)
        return key === "copy" || key === "edit_draft" || key === "delete"
    }

    function userMessageActionEnabled(actionKey, message) {
        const key = String(actionKey)
        if (key === "delete")
            return userMessageActionVisible(key, message) && messageDeletionAvailable
        if (key === "end_waiting")
            return userMessageActionVisible(key, message) && messageDeletionAvailable
        if (!userMessageActionVisible(key, message))
            return false
        if (inlineResponseEditIndex === Number(message.historyIndex) && key !== "edit_draft")
            return false
        return key !== "retry_user_input" || bridge.systemRunning
    }

    function triggerUserMessageAction(actionKey, message) {
        const key = String(actionKey)
        if (!userMessageActionEnabled(key, message))
            return
        const historyIndex = Number(
                    message && message.historyIndex !== undefined
                    ? message.historyIndex : -1)
        if (key === "copy") {
            bridge.copyConversationMessage(historyIndex)
        } else if (key === "delete") {
            beginMessageDeletion(historyIndex)
        } else if (key === "edit_draft") {
            if (inlineResponseEditIndex === historyIndex)
                saveResponseEdit()
            else
                beginResponseEdit(message)
        } else if (key === "retry_user_input") {
            bridge.triggerRuntimeAction("retry_user_input")
        } else if (key === "end_waiting") {
            const target = conversationActions.end_waiting
            bridge.endWaitingForMessage(target.message_id, target.revision, target.session_generation)
        }
    }

    function placeUserMessageAction(actionKey, targetZone, targetIndex) {
        const zones = ["left", "center", "right"]
        const nextLayout = ({
            "left": userMessageActionKeys("left"),
            "center": userMessageActionKeys("center"),
            "right": userMessageActionKeys("right")
        })
        let sourceZone = ""
        let sourceIndex = -1
        for (let zoneIndex = 0; zoneIndex < zones.length; zoneIndex += 1) {
            const zone = zones[zoneIndex]
            const index = nextLayout[zone].indexOf(String(actionKey))
            if (index >= 0) {
                sourceZone = zone
                sourceIndex = index
                nextLayout[zone].splice(index, 1)
                break
            }
        }
        if (!sourceZone || zones.indexOf(String(targetZone)) < 0)
            return
        let requestedIndex = Number(targetIndex)
        if (sourceZone === String(targetZone) && sourceIndex < requestedIndex)
            requestedIndex -= 1
        const insertion = Math.max(
                    0,
                    Math.min(
                        requestedIndex,
                        nextLayout[String(targetZone)].length))
        nextLayout[String(targetZone)].splice(insertion, 0, String(actionKey))
        bridge.setConversationUserActionLayout(nextLayout)
    }

    function placeUserMessageActionInRail(actionKey, targetIndex) {
        const next = userMessageActionRailKeys()
        const sourceIndex = next.indexOf(String(actionKey))
        if (sourceIndex < 0)
            return
        next.splice(sourceIndex, 1)
        let requestedIndex = Number(targetIndex)
        if (sourceIndex < requestedIndex)
            requestedIndex -= 1
        const insertion = Math.max(0, Math.min(requestedIndex, next.length))
        next.splice(insertion, 0, String(actionKey))
        bridge.setConversationUserActionLayout({
                                                   "left": [],
                                                   "center": next,
                                                   "right": []
                                               })
    }

    function openAvatarContextMenu(avatarItem) {
        avatarContextSection = "persona"
        const point = avatarItem.mapToItem(avatarContextPopup.parent, avatarItem.width, 0)
        avatarContextPopup.x = Math.max(
            Theme.NCMetrics.space12,
            Math.min(avatarContextPopup.parent.width - avatarContextPopup.width - Theme.NCMetrics.space12,
                     point.x + Theme.NCMetrics.space8)
        )
        avatarContextPopup.y = Math.max(
            Theme.NCMetrics.space12,
            Math.min(avatarContextPopup.parent.height - avatarContextPopup.height - Theme.NCMetrics.space12,
                     point.y)
        )
        avatarContextPopup.open()
    }

    function openVisualReplyFocus(asset) {
        visualReplyFocusUrl = String(asset && asset.url || "")
        visualReplyFocusPrompt = String(asset && asset.prompt || "")
        visualReplyFocusLabel = String(asset && asset.label || qsTr("Visual Reply"))
        visualReplyFocusZoom = 1.0
        visualReplyFocusPopup.open()
    }

    function openVisualReplyContext(asset, item, localX, localY) {
        if (!item || !visualReplyContextPopup.parent)
            return
        visualReplyContextAsset = asset || ({})
        const point = item.mapToItem(
                    visualReplyContextPopup.parent,
                    Number(localX || 0),
                    Number(localY || 0))
        visualReplyContextPopup.x = Math.max(
                    Theme.NCMetrics.space8,
                    Math.min(
                        point.x,
                        visualReplyContextPopup.parent.width
                        - visualReplyContextPopup.width
                        - Theme.NCMetrics.space8))
        visualReplyContextPopup.y = Math.max(
                    Theme.NCMetrics.space8,
                    Math.min(
                        point.y,
                        visualReplyContextPopup.parent.height
                        - visualReplyContextPopup.implicitHeight
                        - Theme.NCMetrics.space8))
        visualReplyContextPopup.open()
    }

    function normalizedVoicePath(value) {
        return String(value || "").replace(/\\/g, "/").toLowerCase()
    }

    function scrollConsoleToBottom() {
        if (!consoleAutoScroll || !consoleScroll.contentItem)
            return
        consoleArea.cursorPosition = consoleArea.length
        const flickable = consoleScroll.contentItem
        flickable.contentY = Math.max(0, flickable.contentHeight - flickable.height)
    }

    function consoleOverlapLength(oldText, nextText) {
        const maximum = Math.min(oldText.length, nextText.length)
        if (maximum <= 0)
            return 0
        if (oldText.slice(oldText.length - maximum)
                === nextText.slice(0, maximum))
            return maximum
        const markerLength = Math.min(64, nextText.length)
        const marker = nextText.slice(0, markerLength)
        let searchFrom = Math.max(0, oldText.length - nextText.length)
        while (searchFrom <= oldText.length - markerLength) {
            const candidate = oldText.indexOf(marker, searchFrom)
            if (candidate < 0)
                return 0
            const overlap = oldText.length - candidate
            if (overlap <= nextText.length
                    && oldText.slice(candidate) === nextText.slice(0, overlap))
                return overlap
            searchFrom = candidate + 1
        }
        return 0
    }

    function syncConsoleText() {
        const nextText = String(bridge.consoleText || "")
        const oldText = String(consoleArea.text || "")
        if (nextText === oldText)
            return
        const flickable = consoleScroll.contentItem
        // Qt may scroll to the cursor during insert(). Keep the first anchor
        // until the entire pending burst has settled, not that intermediate jump.
        if (!consoleAutoScroll && !pendingConsoleAnchor && flickable) {
            const oldY = Number(flickable.contentY || 0)
            const anchorPosition = consoleArea.positionAt(
                        consoleArea.leftPadding + 2,
                        oldY + consoleArea.topPadding + 2)
            const anchorRectangle = consoleArea.positionToRectangle(anchorPosition)
            pendingConsoleAnchor = {
                position: anchorPosition,
                offset: Number(anchorRectangle.y || 0) - oldY
            }
        }
        if (!nextText.length) {
            pendingConsoleAnchor = null
            consoleArea.clear()
            if (flickable)
                flickable.contentY = 0
            return
        }

        let removedPrefix = 0
        if (nextText.indexOf(oldText) === 0) {
            consoleArea.insert(consoleArea.length, nextText.slice(oldText.length))
        } else {
            const overlap = consoleOverlapLength(oldText, nextText)
            removedPrefix = oldText.length - overlap
            if (removedPrefix > 0)
                consoleArea.remove(0, removedPrefix)
            const suffix = nextText.slice(overlap)
            if (suffix.length > 0)
                consoleArea.insert(consoleArea.length, suffix)
        }

        if (pendingConsoleAnchor)
            pendingConsoleAnchor.position = Math.max(
                        0, pendingConsoleAnchor.position - removedPrefix)
        Qt.callLater(root.restoreConsoleAnchor)
    }

    function restoreConsoleAnchor() {
        const anchor = pendingConsoleAnchor
        pendingConsoleAnchor = null
        if (consoleAutoScroll) {
            scrollConsoleToBottom()
            return
        }
        const flickable = consoleScroll.contentItem
        if (!anchor || !flickable)
            return
        const rectangle = consoleArea.positionToRectangle(anchor.position)
        const maximumY = Math.max(0, flickable.contentHeight - flickable.height)
        flickable.contentY = Math.max(
                    0, Math.min(maximumY, Number(rectangle.y || 0) - anchor.offset))
    }

    onConsoleAutoScrollChanged: {
        pendingConsoleAnchor = null
        if (consoleAutoScroll)
            Qt.callLater(root.scrollConsoleToBottom)
    }

    Connections {
        target: root.bridge
        function onConsoleChanged() { root.syncConsoleText() }
        function onConversationDraftStateChanged() { root.syncComposerDraft() }
        function onConversationAboutToChange() {
            if (!root.loadingOlderMessages
                    && (!root.conversationAutoScroll || root.browsingConversationHistory
                        || !root.bridge.conversationFollowingLatest)) {
                const anchor = root.conversationViewportAnchor()
                if (anchor) {
                    root.loadingOlderMessages = true
                    root.restoreConversationAnchorLater(anchor)
                }
            }
        }
    }

    function handleConversationModelUpdate() {
        // Reused delegates can now represent new message IDs after loading a
        // different history. Release selections belonging to the old messages.
        const selectedIds = Object.keys(root.selectedMessageIds)
        if (selectedIds.length > 0) {
            const presentIds = ({})
            for (let i = 0; i < messageList.count; ++i)
                presentIds[String(messageList.model.get(i).messageId)] = true
            for (const id of selectedIds) {
                if (!presentIds[id])
                    root.setMessageSelection(id, false)
            }
        }
        if (!root.loadingOlderMessages)
            root.olderMessagesScrollIntent = false
        const newest = messageList.count > 0 ? messageList.model.get(messageList.count - 1) : ({})
        const newestId = String(newest.messageId || "")
        const newestContent = String(newest.content || "")
        const changed = newestId !== root.observedNewestMessageId
                        || newestContent !== root.observedNewestMessageContent
        root.observedNewestMessageId = newestId
        root.observedNewestMessageContent = newestContent
        if (changed && root.conversationAutoScroll && !root.loadingOlderMessages
                && !root.browsingConversationHistory && root.bridge.conversationFollowingLatest)
            root.requestConversationLayoutFollow()
    }

    function conversationBottomY() {
        const origin = Number(messageList.originY || 0)
        return origin + Math.max(0, messageList.contentHeight - messageList.height + messageList.bottomMargin)
    }

    function isConversationNearBottom() {
        if (bridge.conversationHasNewerMessages)
            return false
        if (messageList.count <= 0 || messageList.atYEnd)
            return true
        return Math.max(0, conversationBottomY() - messageList.contentY) <= 140
    }

    function updateConversationBottomState() {
        conversationNearBottom = isConversationNearBottom()
        if (conversationNearBottom)
            visualReplyNoticeVisible = false
    }

    function scrollConversationToBottom(smooth, force) {
        // A queued follow can outlive a tab switch/dock teardown.
        if (!root.conversationViewActive)
            return
        if (loadingOlderMessages || (!conversationAutoScroll && !force) || messageList.count <= 0)
            return
        if (force && bridge.conversationHasNewerMessages) {
            jumpToLatestConversation()
            return
        }
        if (!force && (browsingConversationHistory || !bridge.conversationFollowingLatest))
            return
        messageList.forceLayout()
        const targetY = conversationBottomY()
        if (smooth && Math.abs(messageList.contentY - targetY) > 1) {
            conversationFollowAnimation.stop()
            conversationFollowAnimation.from = messageList.contentY
            conversationFollowAnimation.to = targetY
            conversationFollowAnimation.start()
        } else {
            messageList.contentY = conversationBottomY()
            updateConversationBottomState()
        }
    }

    function requestConversationLayoutFollow(force) {
        if (!root.conversationViewActive || (!conversationAutoScroll && !force)
                || conversationWindowProtected || loadingOlderMessages
                || browsingConversationHistory || !bridge.conversationFollowingLatest)
            return
        conversationLayoutFollowSettled = false
        conversationLayoutFollowPasses = 0
        conversationLayoutFollowForced = Boolean(force)
        conversationLayoutFollowPending = true
    }

    Timer {
        interval: 16
        repeat: true
        running: root.conversationLayoutFollowPending
        onTriggered: {
            if (!root.conversationViewActive
                    || (!root.conversationAutoScroll && !root.conversationLayoutFollowForced)
                    || root.conversationWindowProtected || root.loadingOlderMessages
                    || root.browsingConversationHistory || !root.bridge.conversationFollowingLatest) {
                root.conversationLayoutFollowPending = false
                return
            }
            // Positioning can instantiate a tall tail and change the estimated
            // extent again. Require a quiet layout pass, with a bounded retry.
            if (root.conversationLayoutFollowSettled && messageList.atYEnd) {
                root.conversationLayoutFollowPending = false
                return
            }
            root.conversationLayoutFollowSettled = true
            root.scrollConversationToBottom(false, root.conversationLayoutFollowForced)
            root.conversationLayoutFollowPasses += 1
            if (root.conversationLayoutFollowPasses >= 12)
                root.conversationLayoutFollowPending = false
        }
    }

    function conversationViewportAnchor() {
        messageList.forceLayout()
        let first = -1
        let last = -1
        let offset = 0
        for (let i = 0; i < messageList.count; ++i) {
            const item = messageList.itemAtIndex(i)
            if (item && item.y + item.height > messageList.contentY
                    && item.y < messageList.contentY + messageList.height) {
                if (first < 0) {
                    first = i
                    offset = item.y - messageList.contentY
                }
                last = i
            }
        }
        if (first < 0)
            return null
        return {firstId: String(messageList.model.get(first).messageId),
                lastId: String(messageList.model.get(last).messageId), offset: offset,
                atLatest: messageList.atYEnd && !bridge.conversationHasNewerMessages}
    }

    function changeCanonicalEdit(action) {
        const anchor = conversationViewportAnchor()
        let appliedHistoryIndex = -1
        if (anchor) {
            anchor.screenY = messageList.mapToItem(root, 0, anchor.offset).y
            if (action === "apply") {
                const remaining = bridge.conversationEditMessages
                for (let i = 0; i < remaining.length; ++i) {
                    if (String(remaining[i].messageId) === anchor.firstId) {
                        appliedHistoryIndex = Number(remaining[i].historyIndex)
                        break
                    }
                }
                const deletedBefore = bridge.conversationMessages.filter(function(row) {
                    return Number(row.historyIndex) < appliedHistoryIndex
                           && !remaining.some(function(draft) {
                               return Number(draft.historyIndex) === Number(row.historyIndex)
                           })
                }).length
                appliedHistoryIndex -= deletedBefore
            }
            loadingOlderMessages = true
            messageList.cancelFlick()
            conversationFollowAnimation.stop()
            conversationLayoutFollowPending = false
            visualReplyFollowPending = false
            conversationViewportTimer.stop()
        }
        if (action === "begin")
            bridge.beginConversationEdit()
        else if (action === "apply")
            bridge.applyConversationEdit()
        else if (action === "cancel")
            bridge.cancelConversationEdit()
        if (anchor) {
            // Applying canonical history can assign new message IDs. Only
            // remap after success, to the surviving row's new history index.
            if (action === "apply" && !bridge.conversationEditMode) {
                for (let i = 0; i < messageList.count; ++i) {
                    if (Number(messageList.model.get(i).historyIndex) === appliedHistoryIndex) {
                        anchor.firstId = String(messageList.model.get(i).messageId)
                        break
                    }
                }
            }
            restoreConversationAnchorLater(anchor, true, true)
        }
    }

    function saveConversationViewPosition() {
        if (!conversationViewReady || conversationViewPositionSaved)
            return
        const anchor = conversationViewportAnchor()
        if (!anchor)
            return
        anchor.autoScroll = conversationAutoScroll
        anchor.browsingHistory = browsingConversationHistory
        bridge.saveConversationViewState(conversationViewId, anchor)
        conversationViewPositionSaved = true
        conversationViewportTimer.stop()
        conversationFollowAnimation.stop()
        conversationLayoutFollowPending = false
    }

    function restoreConversationViewPosition() {
        const anchor = bridge.conversationViewState()
        if (!anchor || !anchor.firstId)
            return
        conversationAutoScroll = Boolean(anchor.autoScroll)
        browsingConversationHistory = Boolean(anchor.browsingHistory)
        loadingOlderMessages = true
        conversationFollowAnimation.stop()
        conversationLayoutFollowPending = false
        visualReplyFollowPending = false
        conversationViewportTimer.stop()
        restoreConversationAnchorLater(anchor, true)
    }

    function restoreConversationAnchorLater(anchor, allowEditing, immediate) {
        const restore = function() {
            if (!root || root.conversationViewDisposed)
                return
            if (immediate) {
                const polish = function(item) {
                    for (let i = 0; i < item.children.length; ++i)
                        polish(item.children[i])
                    item.ensurePolished()
                }
                polish(messageList.contentItem)
            }
            // Settle parent layouts before mapping a screen-space anchor;
            // edit-mode toolbar changes must not move it on the next frame.
            const parents = []
            for (let item = messageList.parent; item && item !== root; item = item.parent)
                parents.push(item)
            for (let i = 0; i < parents.length; ++i)
                parents[i].ensurePolished()
            for (let i = parents.length - 1; i >= 0; --i)
                parents[i].ensurePolished()
            // The conversation can be reset/replaced before this deferred layout.
            let anchorIndex = -1
            if (allowEditing || !root.bridge.conversationEditMode) {
                for (let i = 0; i < messageList.count; ++i) {
                    if (String(messageList.model.get(i).messageId) === anchor.firstId) {
                        anchorIndex = i
                        break
                    }
                }
            }
            if (anchorIndex >= 0) {
                messageList.forceLayout()
                let anchorItem = messageList.itemAtIndex(anchorIndex)
                if (!anchorItem) {
                    messageList.positionViewAtIndex(anchorIndex, ListView.Beginning)
                    messageList.forceLayout()
                    anchorItem = messageList.itemAtIndex(anchorIndex)
                }
                if (anchorItem) {
                    const offset = anchor.screenY !== undefined
                                   ? anchor.screenY - messageList.mapToItem(root, 0, 0).y
                                   : anchor.offset
                    messageList.contentY = anchorItem.y - offset
                }
            }
            root.loadingOlderMessages = false
            if (anchorIndex < 0) {
                root.browsingConversationHistory = !root.bridge.conversationFollowingLatest
                if (!root.browsingConversationHistory)
                    root.scrollConversationToBottom(false, false)
            }
            root.updateConversationBottomState()
        }
        if (immediate) {
            restore()
            return
        }
        Qt.callLater(function() {
            if (!root)
                return
            // Canonical mode also adds/removes a toolbar; let its parent
            // layout settle before restoring the screen-space anchor.
            if (allowEditing)
                Qt.callLater(restore)
            else
                restore()
        })
    }

    function changeConversationWindow(direction) {
        if (loadingOlderMessages || conversationWindowProtected || messageList.count <= 0)
            return
        const anchor = conversationViewportAnchor()
        if (!anchor)
            return
        userViewportMoved = false
        olderMessagesScrollIntent = false
        conversationViewportTimer.stop()
        loadingOlderMessages = true
        messageList.cancelFlick()
        conversationFollowAnimation.stop()
        visualReplyFollowPending = false
        if (direction === "older") {
            browsingConversationHistory = true
            bridge.setConversationViewport(anchor.firstId, anchor.lastId, false)
        } else if (direction === "newer") {
            bridge.setConversationViewport(anchor.firstId, anchor.lastId, false)
        } else {
            browsingConversationHistory = !(anchor.atLatest && conversationAutoScroll)
            bridge.setConversationViewport(anchor.firstId, anchor.lastId, !browsingConversationHistory)
        }
        restoreConversationAnchorLater(anchor)
    }

    function requestOlderConversationMessages() {
        if (bridge.conversationHasOlderMessages)
            changeConversationWindow("older")
    }

    function rebalanceConversationViewport() {
        changeConversationWindow("viewport")
    }

    function jumpToLatestConversation() {
        if (loadingOlderMessages || conversationWindowProtected)
            return
        conversationViewportTimer.stop()
        messageList.cancelFlick()
        conversationFollowAnimation.stop()
        conversationLayoutFollowPending = false
        visualReplyFollowPending = false
        userViewportMoved = false
        browsingConversationHistory = false
        loadingOlderMessages = true
        bridge.jumpToLatestConversationMessages()
        Qt.callLater(function() {
            root.loadingOlderMessages = false
            root.scrollConversationToBottom(false, true)
            // Newly instantiated tail messages can change the estimated height.
            // Finish this explicit jump without changing the auto-scroll setting.
            root.requestConversationLayoutFollow(true)
        })
    }

    function setMessageSelection(id, active) {
        if (Boolean(selectedMessageIds[id]) === Boolean(active))
            return
        const next = Object.assign({}, selectedMessageIds)
        if (active)
            next[id] = true
        else
            delete next[id]
        selectedMessageIds = next
        bridge.setConversationSelectionActive(Object.keys(next).length > 0)
    }

    function maybeLoadOlderConversationMessages() {
        if (olderMessagesScrollIntent && messageList.atYBeginning)
            requestOlderConversationMessages()
        else if (userViewportMoved && messageList.atYEnd && bridge.conversationHasNewerMessages)
            changeConversationWindow("newer")
    }

    Timer {
        id: conversationViewportTimer
        interval: 160
        onTriggered: {
            if (root.userViewportMoved && !messageList.moving)
                root.rebalanceConversationViewport()
        }
    }

    function scheduleVisualReplyFollow(finalizeAfterScroll) {
        if (!visualReplyFollowPending)
            return
        Qt.callLater(function() {
            if (!root.visualReplyFollowPending)
                return
            messageList.forceLayout()
            Qt.callLater(function() {
                if (!root.visualReplyFollowPending)
                    return
                if (!root.conversationAutoScroll
                        || !root.bridge.conversationVisualReplyAutoFollow) {
                    root.visualReplyFollowPending = false
                    return
                }
                root.scrollConversationToBottom(true, false)
                root.visualReplyNoticeVisible = false
                if (finalizeAfterScroll)
                    root.visualReplyFollowPending = false
            })
        })
    }

    function handleVisualReplyState() {
        const status = visualReplyRuntimeStatus
        const requestId = String(visualReplyRuntimeState.request_id || "")
        const requestChanged = requestId.length > 0
                               && requestId !== observedVisualReplyRequestId
        if (status === "loading"
                && (observedVisualReplyStatus !== "loading" || requestChanged)) {
            visualReplyFollowPending = Boolean(
                        bridge.conversationVisualReplyAutoFollow)
                    && conversationAutoScroll
                    && isConversationNearBottom()
            visualReplyNoticeVisible = false
            if (visualReplyFollowPending)
                scheduleVisualReplyFollow(false)
        } else if (status === "ready" && requestId.length > 0
                   && requestId !== completedVisualReplyRequestId) {
            completedVisualReplyRequestId = requestId
            // The first snapshot is existing state, not a generation event.
            // Image decoding/recreated history delegates never own this notice.
            const newlyCompleted = observedVisualReplyStatus.length > 0
            if (newlyCompleted && visualReplyFollowPending
                    && conversationAutoScroll && bridge.conversationVisualReplyAutoFollow)
                scheduleVisualReplyFollow(false)
            else {
                visualReplyFollowPending = false
                if (newlyCompleted && !isConversationNearBottom())
                    visualReplyNoticeVisible = true
            }
        } else if (status === "error") {
            visualReplyFollowPending = false
        }
        observedVisualReplyStatus = status
        observedVisualReplyRequestId = requestId
    }

    function visualReplyImageLoaded() {
        // Decoding can occur again whenever old messages re-enter the window.
        if (visualReplyFollowPending)
            scheduleVisualReplyFollow(true)
    }

    onConversationAutoScrollChanged: {
        if (conversationAutoScroll)
            Qt.callLater(root.jumpToLatestConversation)
        else {
            visualReplyFollowPending = false
            Qt.callLater(root.rebalanceConversationViewport)
        }
    }

    NumberAnimation {
        id: conversationFollowAnimation
        target: messageList
        property: "contentY"
        duration: 240
        easing.type: Easing.OutCubic
        onStarted: root.visualReplyFollowAnimating = true
        onStopped: {
            root.visualReplyFollowAnimating = false
            root.updateConversationBottomState()
        }
    }

    Connections {
        target: root.bridge
        function onVisualStateChanged() {
            root.handleVisualReplyState()
        }
    }

    Component.onCompleted: {
        root.bridge.setConversationViewVisible(conversationViewId, conversationViewActive)
        root.bridge.refreshIdentityRelayState()
        root.bridge.validateConversationInlineResponseDraft()
        root.syncComposerDraft()
        root.syncConsoleText()
        root.handleVisualReplyState()
        conversationViewReady = true
        restoreConversationViewPosition()
        if (root.pendingUserDraftText.length > 0)
            Qt.callLater(function() { userMessageDraftDialog.open() })
    }

    Component.onDestruction: {
        saveConversationViewPosition()
        conversationViewDisposed = true
        visualReplyFollowPending = false
        bridge.setConversationViewVisible(conversationViewId, false)
        bridge.setConversationSelectionActive(false)
    }

    function firstDroppedImageUrl(urls) {
        const supported = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"]
        for (let index = 0; urls && index < urls.length; ++index) {
            const candidate = String(urls[index] || "")
            const comparable = candidate.split("?")[0].split("#")[0].toLowerCase()
            for (let suffixIndex = 0; suffixIndex < supported.length; ++suffixIndex) {
                if (comparable.endsWith(supported[suffixIndex]))
                    return candidate
            }
        }
        return ""
    }

    function acceptImageDrop(drop) {
        const imageUrls = []
        const urls = drop.urls || []
        for (let i = 0; i < urls.length; ++i) {
            const imageUrl = firstDroppedImageUrl([urls[i]])
            if (imageUrl.length)
                imageUrls.push(imageUrl)
        }
        if (!imageUrls.length)
            return false
        const accepted = root.bridge.stageConversationImages(imageUrls)
        if (accepted)
            drop.acceptProposedAction()
        return accepted
    }

    function escapeRichText(value) { return ConversationText.escapeRichText(value) }
    function isBionicWordCharacter(character) { return ConversationText.isBionicWordCharacter(character) }
    function bionicMessageText(value) { return ConversationText.bionicMessageText(value) }
    function conversationMessageRichText(value) {
        return ConversationText.conversationMessageRichText(value, root.bridge.conversationBionicReadingEnabled)
    }
    function spokenWordBounds(value, progress, spokenText) {
        return SpeechSync.spokenWordBounds(value, progress, spokenText)
    }
    function highlightedMessageText(value, mode, style, progress, spokenText) {
        return ConversationText.highlightedMessageText(value, mode, style, progress, spokenText,
            root.bridge.conversationBionicReadingEnabled, {
                text: root.bridge.conversationMessageTextColor.length > 0
                    ? String(root.bridge.conversationMessageTextColor) : String(Theme.NCTheme.text),
                muted: String(Theme.NCTheme.textMuted), accent: String(Theme.NCTheme.accent),
                selected: String(Theme.NCTheme.surfaceSelected) })
    }

    function speechHighlightActive(message) {
        return root.bridge.conversationSpeechHighlightMode !== "off"
            && Boolean(root.bufferState.speechActive)
            && Boolean(message && root.bufferState.speechMessageId
                       && String(message.messageId) === String(root.bufferState.speechMessageId))
    }

    color: Theme.NCTheme.window
    radius: Theme.NCMetrics.radiusLarge
    border.color: Theme.NCTheme.borderSubtle

    LocalRoomConversationPage {
        anchors.fill: parent
        session: root.roomConversation
        appearanceBridge: root.bridge
        visible: root.showingLocalRoom
    }

    ColumnLayout {
        id: mainConversationBody
        objectName: "mainConversationBody"
        anchors.fill: parent
        visible: !root.showingLocalRoom
        enabled: visible
        spacing: Theme.NCMetrics.space12

        Label {
            Layout.fillWidth: true
            readonly property var mcpController: root.bridge.chatMcpController || null
            text: mcpController ? String(mcpController.state.activity || "") : ""
            visible: text.length > 0 && mcpController.state.activity_persona === String(root.bridge.activeQuickPersona.id || "")
            wrapMode: Text.WordWrap
            color: Theme.NCTheme.textSecondary
        }

        Rectangle {
            objectName: "conversationLiveSessionCard"
            Layout.fillWidth: true
            implicitHeight: liveHeaderColumn.implicitHeight + Theme.NCMetrics.space24
            visible: root.bridge.conversationLiveSessionVisible
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.windowRaised
            border.color: Theme.NCTheme.border

            ColumnLayout {
                id: liveHeaderColumn
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space12
                spacing: Theme.NCMetrics.space8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space10

                    Label {
                        text: qsTr("Live session")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.headingSize
                        font.weight: Theme.NCTypography.semibold
                    }
                    NCStatusChip {
                        text: root.bridge.systemRunning ? qsTr("Runtime active") : qsTr("Runtime stopped")
                        status: root.liveSession.state === "failure" ? "error"
                              : root.bridge.systemRunning ? "active" : "disconnected"
                    }

                    Rectangle {
                        id: readyLed
                        Layout.preferredWidth: 18
                        Layout.preferredHeight: 18
                        radius: 9
                        color: root.liveSession.ready ? Theme.NCTheme.success : Theme.NCTheme.disconnected
                        border.color: root.liveSession.ready ? "#9cf2bd" : Theme.NCTheme.borderStrong
                        border.width: 1
                        Accessible.name: root.liveSession.ready ? qsTr("Ready for voice or text input") : qsTr("Not waiting for input")
                        NCToolTip {
                            visible: readyHover.hovered
                            text: root.liveSession.ready
                                  ? qsTr("Ready for voice or text input")
                                  : qsTr("Runtime is busy or stopped")
                        }
                        HoverHandler { id: readyHover }

                        Rectangle {
                            anchors.centerIn: parent
                            width: 8
                            height: 8
                            radius: 4
                            color: "#d8ffec"
                            opacity: root.liveSession.ready ? 0.72 : 0.0
                        }
                    }

                    Rectangle {
                        id: recordingLed
                        Layout.preferredWidth: 18
                        Layout.preferredHeight: 18
                        radius: 9
                        color: root.liveSession.recording ? Theme.NCTheme.error : Theme.NCTheme.disconnected
                        border.color: root.liveSession.recording ? "#ffadb5" : Theme.NCTheme.borderStrong
                        border.width: 1
                        Accessible.name: root.liveSession.recording ? qsTr("Microphone recording") : qsTr("Microphone not recording")
                        NCToolTip {
                            visible: recordingHover.hovered
                            text: root.liveSession.recording
                                  ? qsTr("Recording microphone input")
                                  : qsTr("Microphone is not recording")
                        }
                        HoverHandler { id: recordingHover }

                        SequentialAnimation on scale {
                            running: root.liveSession.recording
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.82; duration: 420; easing.type: Easing.InOutSine }
                            NumberAnimation { to: 1.0; duration: 420; easing.type: Easing.InOutSine }
                        }
                    }

                    Label {
                        text: String(root.liveSession.stateLabel || "")
                        color: root.liveSession.state === "failure" ? Theme.NCTheme.error : Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.captionSize
                    }

                    Item { Layout.fillWidth: true }

                    Label {
                        text: qsTr("Voice display")
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.captionSize
                    }
                    NCComboBox {
                        toolTipText: qsTr("Choose how voice-input activity is displayed in the conversation. This controls the meter's appearance, not the microphone or recording level.")

                        id: voiceDisplaySelector
                        property var styleIds: ["ribbon", "spectrum", "kinetic"]
                        Layout.preferredWidth: 190
                        label: qsTr("Voice activity display")
                        model: [
                            qsTr("Breathing ribbon"),
                            qsTr("Spectrum cells"),
                            qsTr("Kinetic current")
                        ]
                        currentIndex: Math.max(0, styleIds.indexOf(root.bridge.conversationVoiceIndicatorStyle))
                        onActivated: root.bridge.setConversationVoiceIndicatorStyle(styleIds[currentIndex])
                    }
                }

                NCTtsBufferRace {
                    Layout.fillWidth: true
                    renderProgress: Number(root.bufferState.renderProgress || 0.0)
                    playbackProgress: Number(root.bufferState.playbackProgress || 0.0)
                    phoneReadyVisible: Boolean(root.bufferState.phoneReadyVisible)
                    phoneReadyProgress: Number(root.bufferState.phoneReadyProgress || 0.0)
                    downloadReadyVisible: Boolean(root.bufferState.downloadReadyVisible)
                    downloadReadyProgress: Number(root.bufferState.downloadReadyProgress || 0.0)
                    downloadReadyLabel: String(root.bufferState.downloadReadyLabel || "")
                    renderLabel: String(root.bufferState.renderLabel || "")
                    phoneReadyLabel: String(root.bufferState.phoneReadyLabel || "")
                    playbackLabel: String(root.bufferState.playbackLabel || "")
                    active: Boolean(root.bufferState.active)
                    failed: Boolean(root.bufferState.failed)
                    summary: String(root.bufferState.summary || qsTr("Waiting for TTS"))
                }

                NCVoiceActivityBar {
                    Layout.fillWidth: true
                    styleMode: root.bridge.conversationVoiceIndicatorStyle
                    voiceState: String(root.liveSession.state || "stopped")
                    stateLabel: String(root.liveSession.stateLabel || qsTr("Runtime stopped"))
                    moodName: String(root.liveSession.moodName || root.liveSession.mood || "neutral")
                    primaryColor: String(root.liveSession.primaryColor || "#38bdf8")
                    secondaryColor: String(root.liveSession.secondaryColor || "#22d3ee")
                    accentColor: String(root.liveSession.accentColor || "#a78bfa")
                    audioLevel: Number(root.liveSession.audioLevel || 0.0)
                }
            }
        }

        NCConsoleSplit {
            objectName: "conversationConsoleSplit"
            Layout.fillWidth: true
            Layout.fillHeight: true
            consoleVisible: root.consoleVisible
            onConsoleVisibilityRequested: function(value) {
                root.bridge.setConversationConsoleVisible(value)
            }

            consoleContent: NCCard {
                anchors.fill: parent
                title: qsTr("System console")

                headerAccessory: RowLayout {
                    NCButton {
                        text: root.consoleAutoScroll ? qsTr("Autoscroll: On") : qsTr("Autoscroll: Off")
                        compact: true
                        tone: "secondary"
                        toolTipText: root.consoleAutoScroll
                                     ? qsTr("Turn automatic console scrolling off")
                                     : qsTr("Turn automatic console scrolling on")
                        onClicked: root.bridge.setConversationConsoleAutoScroll(
                                       !root.consoleAutoScroll)
                    }
                    NCButton {
                        text: qsTr("Clear")
                        compact: true
                        tone: "secondary"
                        toolTipText: qsTr("Clear the visible system console output")
                        onClicked: root.bridge.clearConsole()
                    }
                    NCButton {
                        text: root.consoleVisible ? qsTr("Split: On") : qsTr("Split: Off")
                        compact: true
                        tone: "secondary"
                        toolTipText: root.consoleVisible
                                     ? qsTr("Hide the system console and give the conversation the full workspace")
                                     : qsTr("Show the system console beside the conversation")
                        onClicked: root.bridge.setConversationConsoleVisible(
                                       !root.consoleVisible)
                    }
                }

                ScrollView {
                    id: consoleScroll
                    objectName: "conversationConsoleScroll"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ScrollBar.vertical.policy: ScrollBar.AsNeeded
                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.window
                        border.color: consoleArea.activeFocus ? Theme.NCTheme.focus : Theme.NCTheme.borderSubtle
                    }

                    TextArea {
                        id: consoleArea
                        objectName: "conversationConsoleArea"
                        width: consoleScroll.availableWidth
                        text: ""
                        readOnly: true
                        wrapMode: TextEdit.WrapAnywhere
                        color: Theme.NCTheme.textSecondary
                        selectionColor: Theme.NCTheme.selection
                        selectedTextColor: Theme.NCTheme.text
                        font.family: Theme.NCTypography.monoFamily
                        font.pixelSize: Number(root.bridge.conversationConsoleFontSize || Theme.NCTypography.captionSize)
                        leftPadding: Theme.NCMetrics.space10
                        rightPadding: Theme.NCMetrics.space10
                        topPadding: Theme.NCMetrics.space10
                        bottomPadding: Theme.NCMetrics.space10
                        background: null
                        onContentHeightChanged: {
                            if (root.consoleAutoScroll)
                                Qt.callLater(root.scrollConsoleToBottom)
                        }
                        Accessible.name: qsTr("System console")
                        ContextMenu.menu: NCTextEditingContextMenu {
                            objectName: "consoleTextContextMenu"
                            editor: consoleArea
                            MenuSeparator {}
                            MenuItem {
                                objectName: "consoleFontSizeMenuItem"
                                text: qsTr("Font size…")
                                onTriggered: consoleFontSizeDialog.open()
                            }
                        }
                    }
                }
            }

            conversationContent: NCCard {
                anchors.fill: parent
                title: ""
                Accessible.name: qsTr("Conversation")
                fullWidthHeader: true

                headerAccessory: NCConversationActionHeader {
                    id: conversationHeaderControls
                    objectName: "conversationHeaderControls"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredWidth: 1
                    interactionActive: avatarModeSelector.popup.visible || conversationEditPopup.visible
                                       || spotifySenseQuickViewPopup.visible || resetDialog.visible
                                       || conversationWebSearchUnavailableDialog.visible

                    statusContent: NCConversationBufferSummary {
                        id: compactBufferSummary
                        objectName: "conversationCompactBufferSummary"
                        visible: !root.bridge.conversationLiveSessionVisible
                        bufferState: root.bufferState
                        sessionState: root.liveSession
                        systemRunning: root.bridge.systemRunning
                        voiceStyle: root.bridge.conversationVoiceIndicatorStyle
                        onVoiceStyleRequested: style => root.bridge.setConversationVoiceIndicatorStyle(style)
                    }

                    trailingContent: NCButton {
                        id: conversationControlsButton
                        objectName: "conversationControlsButton"
                        text: qsTr("Controls")
                        iconText: "\u2630"
                        compact: true
                        tone: "secondary"
                        toolTipText: qsTr("Open conversation display and context controls")
                        onClicked: {
                            conversationHeaderControls.dismissPreview()
                            conversationControlsPopup.openFor(conversationControlsButton)
                        }
                    }

                    Label {
                        text: qsTr("Chat & tools")
                        color: Theme.NCTheme.textSecondary
                        font.family: Theme.NCTypography.family
                        font.pixelSize: Theme.NCTypography.captionSize
                    }
                    Flow {
                        objectName: "conversationSecondaryActions"
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space8
                        NCButton {
                            id: roomNavigation
                            objectName: "conversationSourceRoom"
                            width: 161
                            height: Theme.NCMetrics.iconButtonSize
                            text: root.roomConversation && root.roomConversation.state.mode === "discord"
                                  ? qsTr("Go to Discord Room  \u2192") : qsTr("Go to Local Room  \u2192")
                            compact: true
                            visible: root.roomConversationAvailable
                            onClicked: root.roomConversation.showRoom()
                        }
                        NCButton {
                            objectName: "conversationStopReplay"
                            text: qsTr("Stop replay")
                            compact: true
                            tone: "danger"
                            visible: Boolean(root.liveSession.replayActive)
                            toolTipText: qsTr("Stop replay audio and remaining text-to-speech generation")
                            onClicked: root.bridge.stopConversationReplay()
                        }

                        RowLayout {
                            objectName: "conversationIdentityRelayControl"
                            spacing: Theme.NCMetrics.space6
                            visible: Boolean(root.bridge.identityRelayState.relayAvailable)

                            Label {
                                text: qsTr("Identity Relay")
                                color: Theme.NCTheme.text
                                font.family: Theme.NCTypography.family
                                font.pixelSize: Theme.NCTypography.bodySize
                            }

                            NCSwitch {
                                toolTipText: qsTr("Enable or disable Identity Relay for this conversation using the current identity configuration. This does not change the selected chat-model provider.")

                                objectName: "conversationIdentityRelaySwitch"
                                checked: Boolean(root.bridge.identityRelayState.enabled)
                                text: ""
                                Accessible.name: qsTr("Identity Relay for this conversation")
                                onClicked: {
                                    if (!root.bridge.setIdentityRelayEnabled(checked))
                                        checked = Boolean(root.bridge.identityRelayState.enabled)
                                }
                            }

                            NCToolTip {
                                visible: identityRelayHover.hovered
                                text: Boolean(root.bridge.identityRelayState.enabled)
                                      ? qsTr("Imported persona continuity is active for this conversation")
                                      : qsTr("Imported persona continuity is connected but suspended")
                            }
                            HoverHandler { id: identityRelayHover }
                        }

                        RowLayout {
                            objectName: "conversationWebSearchControl"
                            spacing: Theme.NCMetrics.space6
                            visible: root.bridge.conversationWebSearchVisible

                            Label {
                                text: qsTr("Web Search")
                                color: Theme.NCTheme.text
                                font.family: Theme.NCTypography.family
                                font.pixelSize: Theme.NCTypography.bodySize
                            }

                            NCSwitch {
                                toolTipText: qsTr("Allow the conversation to use configured web-search assistance. Provider availability and search settings still control which requests can run.")

                                id: conversationWebSearchSwitch
                                objectName: "conversationWebSearchSwitch"
                                checked: root.bridge.conversationWebSearchEnabled
                                text: ""
                                Accessible.name: qsTr("Web Search")
                                onClicked: {
                                    const result = root.bridge.setConversationWebSearchEnabled(checked)
                                    if (!Boolean(result.accepted)) {
                                        checked = Boolean(result.enabled)
                                        if (String(result.reason) === "servers_not_installed")
                                            conversationWebSearchUnavailableDialog.open()
                                    }
                                }
                            }
                        }

                        NCComboBox {
                            id: avatarModeSelector
                            objectName: "conversationAvatarModeSelector"
                            toolTipText: qsTr("Choose how Persona portraits are displayed beside conversation messages. This changes the reading view, not the Persona's saved portrait files.")

                            property var avatarModeIds: ["off", "single", "mood", "ring"]
                            width: 174
                            Layout.preferredWidth: 174
                            label: qsTr("Persona avatar display")
                            model: [qsTr("Avatar hidden"), qsTr("Single portrait"), qsTr("Mood portraits"), qsTr("Portrait + mood ring")]
                            currentIndex: Math.max(0, avatarModeIds.indexOf(root.bridge.conversationPersonaAvatarMode))
                            onActivated: root.bridge.setConversationPersonaAvatarMode(avatarModeIds[currentIndex])
                        }

                        NCButton {
                            id: conversationEditButton
                            text: root.bridge.conversationEditMode ? qsTr("Editing conversation") : qsTr("Edit conversation")
                            iconText: "\u270E"
                            iconOnly: true
                            iconPixelSize: Theme.NCTypography.titleSize
                            compact: true
                            tone: root.bridge.conversationEditMode ? "primary" : "quiet"
                            toolTipText: qsTr("Edit the canonical conversation history")
                            onClicked: conversationEditPopup.openFor(conversationEditButton)
                        }

                        NCButton {
                            id: spotifySenseQuickViewButton
                            objectName: "spotifySenseQuickViewButton"
                            text: qsTr("Spotify")
                            iconText: "♫"
                            compact: true
                            tone: Boolean(root.bridge.spotifySenseState.connected)
                                  ? "quiet" : "warning"
                            visible: Boolean(root.bridge.spotifySenseState.available)
                                     && Boolean(root.bridge.spotifySenseState.enabled)
                            toolTipText: Boolean(root.bridge.spotifySenseState.connected)
                                         ? qsTr("Open Spotify Sense quick view")
                                         : qsTr("Spotify Sense is active but needs connection")
                            onClicked: spotifySenseQuickViewPopup.open()
                        }

                        NCButton {
                            objectName: "conversationOrbButton"
                            text: qsTr("Orb")
                            compact: true
                            toolTipText: qsTr("Show the Orb, choose what it can see, and set up a watch")
                            onClicked: root.bridge.openAddonWorkspaceSection("companion_orb_overlay_tab", "Overview")
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: Theme.NCMetrics.borderWidth
                        color: Theme.NCTheme.border
                    }
                    Label {
                        text: qsTr("Conversation")
                        color: Theme.NCTheme.textSecondary
                        font.family: Theme.NCTypography.family
                        font.pixelSize: Theme.NCTypography.captionSize
                    }
                    Flow {
                        objectName: "conversationFileActions"
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space8
                        NCButton {
                            objectName: "conversationSaveButton"
                            text: qsTr("Save")
                            compact: true
                            visible: root.bridge.conversationSaveButtonVisible
                            enabled: !Boolean(root.bridge.memoryWorkspace.state.busy) && !root.bridge.conversationContextBusy
                            onClicked: root.bridge.memoryWorkspace.saveConversation()
                        }
                        NCButton {
                            objectName: "conversationSaveAsButton"
                            text: qsTr("Save as…")
                            compact: true
                            visible: root.bridge.conversationSaveAsButtonVisible
                            enabled: !Boolean(root.bridge.memoryWorkspace.state.busy) && !root.bridge.conversationContextBusy
                            onClicked: root.bridge.memoryWorkspace.saveConversationAs()
                        }
                        NCButton {
                            objectName: "conversationLoadButton"
                            text: qsTr("Load…")
                            compact: true
                            visible: root.bridge.conversationLoadButtonVisible
                            enabled: !Boolean(root.bridge.memoryWorkspace.state.busy) && !root.bridge.conversationContextBusy
                            onClicked: root.bridge.memoryWorkspace.loadConversation()
                        }
                        NCButton {
                            objectName: "conversationMemoryButton"
                            text: qsTr("Memory")
                            compact: true
                            visible: root.bridge.conversationMemoryButtonVisible
                            toolTipText: qsTr("Open conversation memory settings")
                            onClicked: root.bridge.openConversationMemory()
                        }
                        Label {
                            text: String(root.bridge.memoryWorkspace.state.contextName || qsTr("Unsaved conversation"))
                            color: Theme.NCTheme.textSecondary
                            height: Theme.NCMetrics.controlHeight
                            verticalAlignment: Text.AlignVCenter
                        }
                        NCButton {
                            id: conversationResetMemoryButton
                            objectName: "conversationResetMemoryButton"
                            text: qsTr("Reset chat memory")
                            compact: true
                            tone: "danger"
                            visible: root.bridge.conversationResetButtonVisible
                            toolTipText: qsTr("Clear the current chat memory")
                            onClicked: resetDialog.open()
                        }
                    }
                }

                RowLayout {
                    visible: root.bridge.conversationEditMode
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: 1
                        text: qsTr("%1 messages selected · Shift-click to select a range. Deletions are saved with Apply changes.")
                              .arg(root.bridge.conversationEditSelectionCount)
                        wrapMode: Text.WordWrap
                        color: Theme.NCTheme.textSecondary
                    }
                    NCButton {
                        objectName: "canonicalDeleteSelected"
                        text: qsTr("Delete selected")
                        enabled: root.bridge.conversationEditSelectionCount > 0
                        onClicked: root.bridge.deleteSelectedConversationEditMessages()
                    }
                    NCButton {
                        objectName: "canonicalClearSelection"
                        text: qsTr("Clear selection")
                        enabled: root.bridge.conversationEditSelectionCount > 0
                        onClicked: root.bridge.clearConversationEditSelection()
                    }
                }

                Item {
                    id: conversationDropSurface
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    NCConversationBackdrop {
                        id: conversationBackdrop
                        objectName: "conversationBackdrop"
                        anchors.fill: parent
                        style: root.bridge.conversationCanvasStyle
                        backgroundUrl: root.bridge.conversationBackgroundUrl
                        z: 0
                    }

                    ListView {
                        id: messageList
                        objectName: "conversationMessageList"
                        anchors.fill: parent
                        // Clip scrolling cards inside the backdrop's innermost border.
                        anchors.margins: conversationBackdrop.frameInset
                                         + (conversationBackdrop.frameVisible ? Theme.NCMetrics.space4 : 0)
                        model: root.bridge.conversationDisplayModel
                        spacing: Theme.NCMetrics.space10
                        bottomMargin: Theme.NCMetrics.space24
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        currentIndex: count - 1
                        z: 1
                        onHeightChanged: root.requestConversationLayoutFollow()
                        onContentHeightChanged: root.conversationLayoutFollowSettled = false
                        onOriginYChanged: root.conversationLayoutFollowSettled = false
                        onContentYChanged: {
                            root.updateConversationBottomState()
                            if (root.userViewportMoved && !root.loadingOlderMessages)
                                conversationViewportTimer.restart()
                            Qt.callLater(root.maybeLoadOlderConversationMessages)
                        }
                        onMovementStarted: {
                            if (!root.loadingOlderMessages)
                                root.olderMessagesScrollIntent = true
                            if (!root.loadingOlderMessages && !root.visualReplyFollowAnimating) {
                                root.userViewportMoved = true
                                root.browsingConversationHistory = true
                            }
                            if (!root.visualReplyFollowAnimating)
                                root.visualReplyFollowPending = false
                        }
                        onMovementEnded: {
                            root.maybeLoadOlderConversationMessages()
                            if (root.userViewportMoved)
                                conversationViewportTimer.restart()
                        }
                        onModelChanged: root.handleConversationModelUpdate()
                        Connections {
                            target: root.bridge.conversationDisplayModel
                            function onRowsUpdated() { root.handleConversationModelUpdate() }
                        }

                        WheelHandler {
                            target: null
                            blocking: false
                            onWheel: function(event) {
                                root.olderMessagesScrollIntent = event.angleDelta.y > 0
                                root.userViewportMoved = true
                                if (event.angleDelta.y > 0)
                                    root.browsingConversationHistory = true
                                conversationViewportTimer.restart()
                                Qt.callLater(root.maybeLoadOlderConversationMessages)
                            }
                        }


                    delegate: Item {
                        id: messageDelegate
                        objectName: "conversationMessageDelegate"
                        required property var modelData
                        readonly property real cardAreaWidth: Math.max(
                            0, width - Theme.NCMetrics.space24 * 2)
                        Component.onDestruction: root.setMessageSelection(String(modelData.messageId), false)
                        width: ListView.view.width
                        height: messageStack.implicitHeight

                        Column {
                            id: messageStack
                            objectName: "conversationMessageStack"
                            anchors.left: Boolean(messageDelegate.modelData.isAssistant) ? parent.left : undefined
                            anchors.right: Boolean(messageDelegate.modelData.isAssistant) ? undefined : parent.right
                            anchors.leftMargin: Boolean(messageDelegate.modelData.isAssistant)
                                                ? Theme.NCMetrics.space24 : 0
                            anchors.rightMargin: Boolean(messageDelegate.modelData.isAssistant)
                                                 ? 0 : Theme.NCMetrics.space24
                            width: bubble.width
                            spacing: Boolean(messageDelegate.modelData.isAssistant)
                                     && Boolean(messageDelegate.modelData.avatarVisible)
                                     ? -Theme.NCMetrics.space24
                                     : Theme.NCMetrics.space8

                            Rectangle {
                                id: personaAvatar
                                readonly property string playbackMood: String(
                                    (root.bridge.conversationPortraitMoods || ({}))[String(messageDelegate.modelData.messageId)] || "")
                                readonly property bool liveMoodPortrait: Boolean(messageDelegate.modelData.isAssistant)
                                    && String(messageDelegate.modelData.avatarMode) === "mood" && playbackMood.length > 0
                                anchors.left: Boolean(messageDelegate.modelData.isAssistant)
                                              ? parent.left : undefined
                                anchors.right: Boolean(messageDelegate.modelData.isUser)
                                               ? parent.right : undefined
                                width: visible ? root.bridge.conversationPersonaAvatarSize : 0
                                height: visible ? root.bridge.conversationPersonaAvatarSize : 0
                                radius: 0
                                visible: Boolean(messageDelegate.modelData.avatarVisible)
                                color: "transparent"
                                border.width: 0
                                clip: false
                                Accessible.name: qsTr("%1 portrait, %2 mood")
                                                 .arg(String(messageDelegate.modelData.displayRole || qsTr("Assistant")))
                                                 .arg(personaAvatar.liveMoodPortrait ? personaAvatar.playbackMood
                                                      : String(messageDelegate.modelData.avatarMood || qsTr("neutral")))

                                Image {
                                    id: personaAvatarImage
                                    anchors.fill: parent
                                    anchors.margins: 0
                                    source: personaAvatar.liveMoodPortrait
                                            ? String((messageDelegate.modelData.moodAvatarUrls || ({}))[personaAvatar.playbackMood]
                                                     || messageDelegate.modelData.neutralAvatarUrl || "")
                                            : String(messageDelegate.modelData.avatarUrl || "")
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    cache: false
                                    visible: status === Image.Ready
                                }

                                Label {
                                    anchors.centerIn: parent
                                    text: String(messageDelegate.modelData.avatarInitials || "NC")
                                    color: String(messageDelegate.modelData.avatarMoodColor || Theme.NCTheme.accent)
                                    font.pixelSize: Theme.NCTypography.labelSize
                                    font.weight: Theme.NCTypography.bold
                                    visible: personaAvatarImage.status !== Image.Ready
                                }

                                TapHandler {
                                    acceptedButtons: Qt.RightButton
                                    enabled: Boolean(messageDelegate.modelData.isAssistant)
                                    onTapped: root.openAvatarContextMenu(personaAvatar)
                                }

                                HoverHandler {
                                    id: avatarHover
                                    cursorShape: Qt.PointingHandCursor
                                }

                                NCToolTip {
                                    visible: avatarHover.hovered
                                    text: Boolean(messageDelegate.modelData.isUser)
                                          ? qsTr("User Identity portrait")
                                          : qsTr("Right-click to change avatar size, quick persona, or voice")
                                }
                            }

                            NCConversationMessageCard {
                                id: bubble
                                assistantResponse: Boolean(
                                                                              messageDelegate.modelData.isAssistant)
                                readonly property bool userMessage: Boolean(
                                                                        messageDelegate.modelData.isUser)
                                readonly property bool responseEditActive: (assistantResponse || userMessage)
                                                                           && root.inlineResponseEditIndex
                                                                              === Number(messageDelegate.modelData.historyIndex)
                                userEdited: assistantResponse
                                                                    && Boolean(messageDelegate.modelData.isUserEdited)
                                property real resizeStartPointerX: 0
                                property real resizeStartPointerY: 0
                                property real resizeStartWidth: 0
                                property real resizeStartMinimumHeight: 0
                                width: assistantResponse
                                       ? Math.min(
                                             messageDelegate.cardAreaWidth * 0.96,
                                             Math.max(
                                                 Boolean(messageDelegate.modelData.hasVisualReply) ? 540 : 360,
                                                  messageDelegate.cardAreaWidth * root.responseFrameWidthRatio))
                                       : userMessage && root.userFrameWidthRatio > 0.0
                                         ? Math.min(
                                               messageDelegate.cardAreaWidth * 0.92,
                                               Math.max(
                                                   Boolean(messageDelegate.modelData.hasAttachment) ? 360 : 260,
                                                    messageDelegate.cardAreaWidth * root.userFrameWidthRatio))
                                       : Math.min(
                                             messageDelegate.cardAreaWidth * 0.86,
                                             Math.max(
                                                 Boolean(messageDelegate.modelData.hasAttachment) ? 360 : 260,
                                                 messageBody.implicitWidth + Theme.NCMetrics.space24))
                                implicitHeight: Math.max(
                                                    messageColumn.implicitHeight + Theme.NCMetrics.space20,
                                                    assistantResponse
                                                    ? root.responseFrameMinHeight
                                                    : userMessage
                                                      ? root.userFrameMinHeight : 0)
                                draftSelected: root.bridge.conversationEditMode
                                                                      && Boolean(messageDelegate.modelData.selected)
                                transparentCards: root.bridge.conversationTransparentMessageCardsEnabled
                                bordersEnabled: root.bridge.conversationMessageBordersEnabled

                                Rectangle {
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space2
                                    radius: Math.max(0, bubble.radius - Theme.NCMetrics.space2)
                                    color: bubble.userEdited
                                           ? Theme.NCTheme.withAlpha(Theme.NCTheme.warning, 0.08)
                                           : "transparent"
                                    border.width: bubble.userEdited ? Theme.NCMetrics.borderWidth : 0
                                    border.color: Theme.NCTheme.withAlpha(Theme.NCTheme.warning, 0.34)
                                    visible: bubble.userEdited
                                    z: 0
                                }

                                // Empty bubble space must not start a chat drag.
                                // Text, action controls and resize handles sit above it.
                                MouseArea {
                                    anchors.fill: parent
                                    acceptedButtons: Qt.LeftButton
                                    preventStealing: true
                                    enabled: !root.bridge.conversationEditMode
                                    z: 0
                                }

                                ColumnLayout {
                                    id: messageColumn
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space10
                                    spacing: Theme.NCMetrics.space4
                                    z: 1

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Theme.NCMetrics.space6

                                        NCCheckBox {
                                            toolTipText: qsTr("Select this message for conversation editing. Selection alone does not delete or resend it.")

                                            objectName: "canonicalSelectMessage" + String(messageDelegate.modelData.index)
                                            visible: root.bridge.conversationEditMode
                                            checked: Boolean(messageDelegate.modelData.selected)
                                            Accessible.name: qsTr("Select message %1").arg(Number(messageDelegate.modelData.index) + 1)
                                            // Keep pointer modifiers on the click, including Windows Shift-click.
                                            MouseArea {
                                                anchors.fill: parent
                                                onClicked: function(mouse) {
                                                    root.bridge.selectConversationEditMessage(
                                                                Number(messageDelegate.modelData.index),
                                                                Boolean(mouse.modifiers & Qt.ShiftModifier))
                                                }
                                            }
                                            onClicked: root.bridge.selectConversationEditMessage(Number(messageDelegate.modelData.index), false)
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: String(messageDelegate.modelData.displayRole || "Message")
                                            color: Boolean(messageDelegate.modelData.isAssistant) ? Theme.NCTheme.accent : Theme.NCTheme.textSecondary
                                            font.pixelSize: Theme.NCTypography.microSize
                                            font.weight: Theme.NCTypography.bold
                                            font.letterSpacing: 0.7
                                        }
                                        Label {
                                            visible: root.bridge.conversationTimestampsEnabled
                                                     && String(messageDelegate.modelData.displayTimestamp || "").length > 0
                                            text: String(messageDelegate.modelData.displayTimestamp || "")
                                            color: Theme.NCTheme.textMuted
                                            font.pixelSize: Theme.NCTypography.microSize
                                        }
                                        NCStatusChip {
                                            visible: bubble.userEdited
                                            text: qsTr("Edited")
                                            status: "warning"
                                        }
                                    }

                                    Rectangle {
                                        id: visualReplyGeneratingPlaceholder
                                        objectName: "visualReplyGeneratingPlaceholder"
                                        Layout.fillWidth: true
                                        Layout.minimumHeight: visible ? 220 : 0
                                        Layout.preferredHeight: visible
                                                                ? Math.max(
                                                                      220,
                                                                      Math.min(
                                                                          360,
                                                                          Math.max(1, width - Theme.NCMetrics.space8)
                                                                          * 9 / 16))
                                                                : 0
                                        visible: root.bridge.conversationVisualRepliesVisible
                                                 && Boolean(messageDelegate.modelData.isLatestAssistant)
                                                 && root.visualReplyRuntimeStatus === "loading"
                                        radius: Theme.NCMetrics.radiusMedium
                                        color: Theme.NCTheme.windowRaised
                                        border.color: Theme.NCTheme.borderStrong
                                        border.width: Theme.NCMetrics.borderWidth
                                        clip: true

                                        Column {
                                            anchors.centerIn: parent
                                            width: Math.min(parent.width - Theme.NCMetrics.space24, 420)
                                            spacing: Theme.NCMetrics.space8

                                            BusyIndicator {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                running: visualReplyGeneratingPlaceholder.visible
                                            }

                                            Label {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                text: qsTr("Generating visual reply…")
                                                color: Theme.NCTheme.text
                                                font.pixelSize: Theme.NCTypography.bodySize
                                                font.weight: Theme.NCTypography.bold
                                            }

                                            Label {
                                                width: parent.width
                                                text: String(root.visualReplyRuntimeState.detail_text
                                                             || qsTr("The reply will appear here when it is ready."))
                                                color: Theme.NCTheme.textSecondary
                                                font.pixelSize: Theme.NCTypography.captionSize
                                                horizontalAlignment: Text.AlignHCenter
                                                wrapMode: Text.Wrap
                                                maximumLineCount: 3
                                                elide: Text.ElideRight
                                            }
                                        }
                                    }

                                    Repeater {
                                        model: messageDelegate.modelData.visualReplies || []

                                        delegate: Rectangle {
                                            id: visualReplyAsset
                                            objectName: "visualReplyAsset"
                                            required property var modelData
                                            readonly property string displayMode: String(
                                                root.bridge.conversationVisualReplyDisplayMode || "fit")
                                            readonly property real sourceAspectRatio:
                                                visualReplyImage.status === Image.Ready
                                                && visualReplyImage.sourceSize.width > 0
                                                && visualReplyImage.sourceSize.height > 0
                                                ? visualReplyImage.sourceSize.width
                                                  / visualReplyImage.sourceSize.height
                                                : 16 / 9
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: displayMode === "compact" ? 190
                                                                    : displayMode === "fit"
                                                                      ? Math.max(
                                                                            220,
                                                                            Math.min(
                                                                                520,
                                                                                Math.max(1, width - Theme.NCMetrics.space8)
                                                                                / sourceAspectRatio))
                                                                      : displayMode === "original" ? 360 : 310
                                            radius: Theme.NCMetrics.radiusMedium
                                            color: root.bridge.conversationTransparentMessageCardsEnabled
                                                   ? "transparent"
                                                   : Theme.NCTheme.windowRaised
                                            border.color: Theme.NCTheme.accent
                                            border.width: root.bridge.conversationTransparentMessageCardsEnabled
                                                          ? 0
                                                          : Theme.NCMetrics.borderWidth
                                            clip: true
                                            Accessible.name: qsTr("Generated Visual Reply: %1")
                                                             .arg(String(modelData.name || qsTr("image")))

                                            Flickable {
                                                id: visualReplyViewport
                                                anchors.fill: parent
                                                anchors.margins: Theme.NCMetrics.space4
                                                clip: true
                                                interactive: visualReplyAsset.displayMode === "original"
                                                boundsBehavior: Flickable.StopAtBounds
                                                contentWidth: visualReplyAsset.displayMode === "original"
                                                              ? Math.max(width, visualReplyImage.width)
                                                              : width
                                                contentHeight: visualReplyAsset.displayMode === "original"
                                                               ? Math.max(height, visualReplyImage.height)
                                                               : height

                                                Image {
                                                    id: visualReplyImage
                                                    x: visualReplyAsset.displayMode === "original"
                                                       ? Math.max(0, (visualReplyViewport.width - width) / 2) : 0
                                                    y: visualReplyAsset.displayMode === "original"
                                                       ? Math.max(0, (visualReplyViewport.height - height) / 2) : 0
                                                    width: visualReplyAsset.displayMode === "original"
                                                           ? Math.max(1, sourceSize.width)
                                                           : visualReplyViewport.width
                                                    height: visualReplyAsset.displayMode === "original"
                                                            ? Math.max(1, sourceSize.height)
                                                            : visualReplyViewport.height
                                                    source: String(visualReplyAsset.modelData.url || "")
                                                    fillMode: visualReplyAsset.displayMode === "fill"
                                                              ? Image.PreserveAspectCrop
                                                              : Image.PreserveAspectFit
                                                    asynchronous: true
                                                    cache: false
                                                    smooth: true
                                                    mipmap: true
                                                    onStatusChanged: {
                                                        if (status === Image.Ready)
                                                            root.visualReplyImageLoaded()
                                                    }
                                                }
                                            }

                                            NCStatusChip {
                                                anchors.left: parent.left
                                                anchors.top: parent.top
                                                anchors.margins: Theme.NCMetrics.space8
                                                text: qsTr("Visual Reply")
                                                status: "active"
                                            }

                                            NCIconButton {
                                                anchors.right: parent.right
                                                anchors.top: parent.top
                                                anchors.margins: Theme.NCMetrics.space8
                                                glyph: "↗"
                                                toolTipText: qsTr("Open this Visual Reply in a zoomable focus view")
                                                onClicked: root.openVisualReplyFocus(visualReplyAsset.modelData)
                                            }

                                            TapHandler {
                                                acceptedButtons: Qt.RightButton
                                                onTapped: function(eventPoint) {
                                                    root.openVisualReplyContext(
                                                                visualReplyAsset.modelData,
                                                                visualReplyAsset,
                                                                eventPoint.position.x,
                                                                eventPoint.position.y)
                                                }
                                            }

                                            HoverHandler { id: visualReplyHover }
                                            NCToolTip {
                                                visible: visualReplyHover.hovered
                                                         && String(visualReplyAsset.modelData.prompt || "").length > 0
                                                text: String(visualReplyAsset.modelData.prompt || "")
                                            }
                                        }
                                    }

                                    Repeater {
                                        model: messageDelegate.modelData.attachments || (messageDelegate.modelData.hasAttachment
                                               ? [{url: messageDelegate.modelData.attachmentUrl, name: messageDelegate.modelData.attachmentName}]
                                               : [])
                                        delegate: Rectangle {
                                            id: userAttachmentAsset
                                            objectName: "userAttachmentAsset"
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: visible ? 190 : 0
                                            radius: Theme.NCMetrics.radiusMedium
                                            color: root.bridge.conversationTransparentMessageCardsEnabled
                                                   ? "transparent"
                                                   : Theme.NCTheme.windowRaised
                                            border.color: Theme.NCTheme.border
                                            border.width: root.bridge.conversationTransparentMessageCardsEnabled
                                                          ? 0
                                                          : Theme.NCMetrics.borderWidth
                                            clip: true

                                            Image {
                                                anchors.fill: parent
                                                anchors.margins: 4
                                                source: String(userAttachmentAsset.modelData.url || "")
                                                fillMode: Image.PreserveAspectFit
                                                asynchronous: true
                                                cache: false
                                            }

                                            NCIconButton {
                                                objectName: "userAttachmentFocusButton"
                                                anchors.right: parent.right
                                                anchors.top: parent.top
                                                anchors.margins: Theme.NCMetrics.space8
                                                glyph: "↗"
                                                enabled: String(userAttachmentAsset.modelData.url || "").length > 0
                                                toolTipText: qsTr("Open this image in a zoomable focus view")
                                                onClicked: root.openVisualReplyFocus({
                                                    url: userAttachmentAsset.modelData.url,
                                                    prompt: userAttachmentAsset.modelData.name || "",
                                                    label: qsTr("Attached image")
                                                })
                                            }

                                            Label {
                                                anchors.left: parent.left
                                                anchors.bottom: parent.bottom
                                                anchors.margins: Theme.NCMetrics.space8
                                                text: String(userAttachmentAsset.modelData.name || "")
                                                color: Theme.NCTheme.textSecondary
                                                font.pixelSize: Theme.NCTypography.microSize
                                                visible: text.length > 0
                                            }
                                        }
                                    }

                                    NCSpeechHighlightText {
                                        id: messageBody
                                        objectName: "conversationMessageBody"
                                        onSelectionActiveChanged: root.setMessageSelection(
                                            String(messageDelegate.modelData.messageId), selectionActive)
                                        Layout.fillWidth: true
                                        readonly property bool speechHighlighted: root.speechHighlightActive(messageDelegate.modelData)
                                        readonly property var speechBounds: root.spokenWordBounds(
                                                                                 plainText,
                                                                                 root.bufferState.speechProgress,
                                                                                 root.bufferState.speechText)
                                        plainText: String(messageDelegate.modelData.content || "")
                                        renderedText: speechHighlighted
                                                      ? root.highlightedMessageText(
                                                            plainText,
                                                            root.bridge.conversationSpeechHighlightMode,
                                                            root.bridge.conversationSpeechHighlightStyle,
                                                            root.bufferState.speechProgress,
                                                            root.bufferState.speechText)
                                                      : root.conversationMessageRichText(plainText)
                                        highlightActive: speechHighlighted
                                        bionicReading: root.bridge.conversationBionicReadingEnabled
                                        highlightStart: Number(speechBounds.start || 0)
                                        highlightEnd: Number(speechBounds.end || 0)
                                        highlightStyle: root.bridge.conversationSpeechHighlightStyle
                                        textColor: root.bridge.conversationMessageTextColor.length > 0
                                                   ? root.bridge.conversationMessageTextColor
                                                   : Theme.NCTheme.text
                                        fontFamily: root.bridge.conversationMessageFontFamily.length > 0
                                                    ? root.bridge.conversationMessageFontFamily
                                                    : Theme.NCTypography.family
                                        textPixelSize: root.conversationFontPixels
                                        visible: !root.bridge.conversationEditMode
                                                 && !bubble.responseEditActive
                                    }

                                    NCSpellcheckTextArea {
                                        toolTipText: qsTr("Edit this message's text in place, then use the available save or cancel action. Editing a draft does not generate a new reply by itself.")

                                        id: inlineResponseEditor
                                        bridge: root.bridge
                                        objectName: "conversationInlineResponseEditor"
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: visible
                                                                ? Math.max(
                                                                      120,
                                                                      contentHeight + topPadding + bottomPadding)
                                                                : 0
                                        visible: bubble.responseEditActive
                                                 && !root.bridge.conversationEditMode
                                        text: visible ? root.inlineResponseEditText : ""
                                        color: messageBody.textColor
                                        font.family: messageBody.fontFamily
                                        font.pixelSize: root.conversationFontPixels
                                        label: qsTr("Edit message")
                                        onTextChanged: {
                                            if (visible)
                                                root.bridge.setConversationInlineResponseDraftText(text)
                                        }
                                    }

                                    OrbWatchCapturePreview {
                                        objectName: "conversationOrbWatchCapture"
                                        Layout.fillWidth: true
                                        capture: messageDelegate.modelData.watchCapture || ({})
                                        onOpenRequested: (url) => Qt.openUrlExternally(url)
                                    }
                                    Repeater {
                                        model: messageDelegate.modelData.watchCaptures || []
                                        delegate: OrbWatchCapturePreview {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            capture: modelData
                                            onOpenRequested: (url) => Qt.openUrlExternally(url)
                                        }
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        visible: inlineResponseEditor.visible && text.length > 0
                                        text: inlineResponseEditor.spellcheckMessage
                                        color: Theme.NCTheme.error
                                        wrapMode: Text.Wrap
                                    }

                                    RowLayout {
                                        visible: bubble.responseEditActive && !root.bridge.conversationEditMode
                                        NCButton {
                                            objectName: "conversationInlineEditSave"
                                            text: qsTr("Save")
                                            enabled: root.inlineResponseEditText.trim().length > 0
                                            onClicked: root.saveResponseEdit()
                                        }
                                        NCButton {
                                            objectName: "conversationInlineEditCancel"
                                            text: qsTr("Cancel")
                                            onClicked: root.cancelResponseEdit()
                                        }
                                    }

                                    NCTextArea {
                                        toolTipText: qsTr("Edit the selected message's text. Save the change using the conversation editor; the draft is separate from live speech playback.")

                                        id: editableMessageBody
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: Math.max(
                                                                    92,
                                                                    contentHeight + topPadding + bottomPadding)
                                        visible: root.bridge.conversationEditMode
                                        text: String(messageDelegate.modelData.content || "")
                                        color: messageBody.textColor
                                        font.family: messageBody.fontFamily
                                        font.pixelSize: root.conversationFontPixels
                                        label: qsTr("Edit %1 message")
                                               .arg(String(messageDelegate.modelData.displayRole || qsTr("conversation")))
                                        onTextChanged: {
                                            if (root.bridge.conversationEditMode
                                                    && messageDelegate.modelData.index !== undefined)
                                                root.bridge.setConversationEditContent(
                                                            Number(messageDelegate.modelData.index),
                                                            text)
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.topMargin: Theme.NCMetrics.space4
                                        implicitHeight: Theme.NCMetrics.borderWidth
                                        color: Theme.NCTheme.borderSubtle
                                        visible: (bubble.assistantResponse || bubble.userMessage)
                                                 && !root.bridge.conversationEditMode
                                    }

                                    NCConversationActionZone {
                                        id: conversationResponseActions
                                        objectName: "conversationResponseActions"
                                        Layout.fillWidth: true
                                        visible: bubble.assistantResponse
                                                 && !root.bridge.conversationEditMode
                                        workspace: root
                                        messageData: messageDelegate.modelData
                                        zoneName: "center"
                                        unifiedRail: true
                                        actionKeys: root.responseActionRailKeys()
                                        customizable: Boolean(
                                                          messageDelegate.modelData.isLatestAssistant)
                                    }

                                    NCConversationActionZone {
                                        id: conversationUserActions
                                        objectName: "conversationUserActions"
                                        Layout.fillWidth: true
                                        visible: bubble.userMessage
                                                 && !root.bridge.conversationEditMode
                                        workspace: root
                                        messageData: messageDelegate.modelData
                                        actionScope: "user"
                                        zoneName: "center"
                                        unifiedRail: true
                                        actionKeys: root.userMessageActionRailKeys()
                                        customizable: Boolean(
                                                          messageDelegate.modelData.isLatestUser)
                                    }
                                }

                                Item {
                                    id: responseWidthHandle
                                    objectName: bubble.userMessage
                                                ? "conversationUserWidthHandle"
                                                : "conversationResponseWidthHandle"
                                    anchors.top: parent.top
                                    anchors.bottom: parent.bottom
                                    anchors.left: bubble.userMessage ? parent.left : undefined
                                    anchors.right: bubble.assistantResponse ? parent.right : undefined
                                    anchors.topMargin: Theme.NCMetrics.space24
                                    anchors.bottomMargin: Theme.NCMetrics.space24
                                    anchors.leftMargin: bubble.userMessage ? -6 : 0
                                    anchors.rightMargin: bubble.assistantResponse ? -6 : 0
                                    width: 12
                                    visible: (bubble.assistantResponse || bubble.userMessage)
                                             && !root.bridge.conversationEditMode
                                    z: 20

                                    Rectangle {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        anchors.top: parent.top
                                        anchors.bottom: parent.bottom
                                        width: 2
                                        radius: Theme.NCMetrics.radiusPill
                                        color: Theme.NCTheme.accent
                                        opacity: responseWidthMouse.containsMouse
                                                 || responseWidthMouse.pressed ? 0.9 : 0.34
                                    }

                                    MouseArea {
                                        id: responseWidthMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.SizeHorCursor
                                        acceptedButtons: Qt.LeftButton
                                        preventStealing: true

                                        onPressed: function(mouse) {
                                            const point = mapToItem(
                                                            messageDelegate,
                                                            mouse.x,
                                                            mouse.y)
                                            bubble.resizeStartPointerX = point.x
                                            bubble.resizeStartWidth = bubble.width
                                        }
                                        onPositionChanged: function(mouse) {
                                            if (!pressed)
                                                return
                                            const point = mapToItem(
                                                            messageDelegate,
                                                            mouse.x,
                                                            mouse.y)
                                            const horizontalDelta = point.x
                                                                    - bubble.resizeStartPointerX
                                            const requestedWidth = bubble.resizeStartWidth
                                                                 + (bubble.userMessage
                                                                    ? -horizontalDelta
                                                                    : horizontalDelta)
                                            if (bubble.userMessage)
                                                root.userFrameWidthRatio = Math.max(
                                                            0.28,
                                                            Math.min(
                                                                0.92,
                                                                requestedWidth
                                                                / Math.max(1, messageDelegate.width)))
                                            else
                                                root.responseFrameWidthRatio = Math.max(
                                                            0.35,
                                                            Math.min(
                                                                0.96,
                                                                requestedWidth
                                                                / Math.max(1, messageDelegate.width)))
                                        }
                                        onReleased: {
                                            if (bubble.userMessage)
                                                root.saveUserFrameSize()
                                            else
                                                root.saveResponseFrameSize()
                                        }
                                        onCanceled: {
                                            if (bubble.userMessage)
                                                root.saveUserFrameSize()
                                            else
                                                root.saveResponseFrameSize()
                                        }
                                        onDoubleClicked: {
                                            if (bubble.userMessage) {
                                                root.userFrameWidthRatio = 0.0
                                                root.userFrameMinHeight = 96
                                                root.saveUserFrameSize()
                                            } else {
                                                root.responseFrameWidthRatio = 0.68
                                                root.responseFrameMinHeight = 140
                                                root.saveResponseFrameSize()
                                            }
                                        }
                                    }

                                    NCToolTip {
                                        visible: responseWidthMouse.containsMouse
                                        text: bubble.userMessage
                                              ? qsTr("Drag to resize all user message widths; double-click for automatic width")
                                              : qsTr("Drag to resize all assistant response widths; double-click to reset")
                                    }
                                }

                                Item {
                                    id: responseCornerHandle
                                    objectName: bubble.userMessage
                                                ? "conversationUserCornerHandle"
                                                : "conversationResponseCornerHandle"
                                    anchors.left: bubble.userMessage ? parent.left : undefined
                                    anchors.right: bubble.assistantResponse ? parent.right : undefined
                                    anchors.bottom: parent.bottom
                                    anchors.leftMargin: bubble.userMessage ? -5 : 0
                                    anchors.rightMargin: bubble.assistantResponse ? -5 : 0
                                    anchors.bottomMargin: -5
                                    width: 28
                                    height: 28
                                    visible: (bubble.assistantResponse || bubble.userMessage)
                                             && !root.bridge.conversationEditMode
                                    z: 21

                                    Rectangle {
                                        x: bubble.userMessage ? 6 : 8
                                        y: 17
                                        width: 14
                                        height: 2
                                        rotation: bubble.userMessage ? 45 : -45
                                        radius: Theme.NCMetrics.radiusPill
                                        color: Theme.NCTheme.accent
                                        opacity: responseCornerMouse.containsMouse
                                                 || responseCornerMouse.pressed ? 0.95 : 0.5
                                    }
                                    Rectangle {
                                        x: bubble.userMessage ? 7 : 13
                                        y: 18
                                        width: 8
                                        height: 2
                                        rotation: bubble.userMessage ? 45 : -45
                                        radius: Theme.NCMetrics.radiusPill
                                        color: Theme.NCTheme.accent
                                        opacity: responseCornerMouse.containsMouse
                                                 || responseCornerMouse.pressed ? 0.95 : 0.5
                                    }

                                    MouseArea {
                                        id: responseCornerMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: bubble.userMessage
                                                     ? Qt.SizeBDiagCursor : Qt.SizeFDiagCursor
                                        acceptedButtons: Qt.LeftButton
                                        preventStealing: true

                                        onPressed: function(mouse) {
                                            const point = mapToItem(
                                                            messageDelegate,
                                                            mouse.x,
                                                            mouse.y)
                                            bubble.resizeStartPointerX = point.x
                                            bubble.resizeStartPointerY = point.y
                                            bubble.resizeStartWidth = bubble.width
                                            bubble.resizeStartMinimumHeight = bubble.userMessage
                                                                              ? root.userFrameMinHeight
                                                                              : root.responseFrameMinHeight
                                        }
                                        onPositionChanged: function(mouse) {
                                            if (!pressed)
                                                return
                                            const point = mapToItem(
                                                            messageDelegate,
                                                            mouse.x,
                                                            mouse.y)
                                            const horizontalDelta = point.x
                                                                    - bubble.resizeStartPointerX
                                            const requestedWidth = bubble.resizeStartWidth
                                                                 + (bubble.userMessage
                                                                    ? -horizontalDelta
                                                                    : horizontalDelta)
                                            const requestedHeight = bubble.resizeStartMinimumHeight
                                                                  + point.y
                                                                  - bubble.resizeStartPointerY
                                            if (bubble.userMessage) {
                                                root.userFrameWidthRatio = Math.max(
                                                            0.28,
                                                            Math.min(
                                                                0.92,
                                                                requestedWidth
                                                                / Math.max(1, messageDelegate.width)))
                                                root.userFrameMinHeight = Math.round(
                                                            Math.max(
                                                                96,
                                                                Math.min(420, requestedHeight)))
                                            } else {
                                                root.responseFrameWidthRatio = Math.max(
                                                            0.35,
                                                            Math.min(
                                                                0.96,
                                                                requestedWidth
                                                                / Math.max(1, messageDelegate.width)))
                                                root.responseFrameMinHeight = Math.round(
                                                            Math.max(
                                                                96,
                                                                Math.min(420, requestedHeight)))
                                            }
                                        }
                                        onReleased: {
                                            if (bubble.userMessage)
                                                root.saveUserFrameSize()
                                            else
                                                root.saveResponseFrameSize()
                                        }
                                        onCanceled: {
                                            if (bubble.userMessage)
                                                root.saveUserFrameSize()
                                            else
                                                root.saveResponseFrameSize()
                                        }
                                        onDoubleClicked: {
                                            if (bubble.userMessage) {
                                                root.userFrameWidthRatio = 0.0
                                                root.userFrameMinHeight = 96
                                                root.saveUserFrameSize()
                                            } else {
                                                root.responseFrameWidthRatio = 0.68
                                                root.responseFrameMinHeight = 140
                                                root.saveResponseFrameSize()
                                            }
                                        }
                                    }

                                    NCToolTip {
                                        visible: responseCornerMouse.containsMouse
                                        text: bubble.userMessage
                                              ? qsTr("Drag to resize user message width and minimum height; double-click to reset")
                                              : qsTr("Drag to resize width and minimum height; double-click to reset")
                                    }
                                }
                            }
                        }
                    }

                    ScrollBar.vertical: ScrollBar {
                        onPressedChanged: {
                            if (pressed) {
                                root.olderMessagesScrollIntent = true
                                root.userViewportMoved = true
                                root.browsingConversationHistory = true
                            } else if (root.userViewportMoved) {
                                conversationViewportTimer.restart()
                            }
                        }
                    }

                    NCEmptyState {
                        anchors.centerIn: parent
                        width: Math.min(parent.width - 60, 440)
                        visible: messageList.count === 0
                        glyph: "◌"
                        title: qsTr("Start a conversation")
                        description: qsTr("Send a message or drop an image here, then add an optional question or comment.")
                    }
                    }

                    NCButton {
                        objectName: "conversationLoadOlderMessages"
                        z: 2
                        anchors.top: parent.top
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: Boolean(root.bridge.conversationHasOlderMessages)
                                 && messageList.atYBeginning && !root.bridge.conversationEditMode
                        text: qsTr("Load older messages")
                        toolTipText: qsTr("%1 of %2 messages shown").arg(messageList.count)
                                     .arg(root.bridge.conversationTotalDisplayMessages)
                        tone: "quiet"
                        onClicked: root.requestOlderConversationMessages()
                    }

                    NCButton {
                        objectName: "conversationJumpToLatest"
                        z: 2
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.margins: Theme.NCMetrics.space16
                        visible: messageList.count > 0
                                 && (root.bridge.conversationHasNewerMessages || !messageList.atYEnd)
                        enabled: !root.conversationWindowProtected && !root.loadingOlderMessages
                        text: qsTr("Jump to latest ↓")
                        tone: root.visualReplyNoticeVisible ? "primary" : "secondary"
                        toolTipText: root.visualReplyNoticeVisible
                                     ? qsTr("New image available. Jump to the latest message.")
                                     : qsTr("Jump to the latest message")
                        onClicked: root.jumpToLatestConversation()
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 118
                    visible: root.pendingImages.length > 0
                    radius: Theme.NCMetrics.radiusMedium
                    color: Theme.NCTheme.windowRaised
                    border.color: Theme.NCTheme.accent

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: Theme.NCMetrics.space8
                        contentHeight: availableHeight
                        clip: true
                        ScrollBar.vertical.policy: ScrollBar.AlwaysOff
                        ScrollBar.horizontal.policy: ScrollBar.horizontal.size < 1
                                                     ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                        Row {
                            spacing: Theme.NCMetrics.space8
                            Repeater {
                                model: root.pendingImages
                                delegate: Rectangle {
                                    id: pendingImageCard
                                    required property var modelData
                                    required property int index
                                    objectName: "conversationPendingImage" + index
                                    width: 112
                                    height: 94
                                    radius: Theme.NCMetrics.radiusSmall
                                    color: Theme.NCTheme.surface
                                    border.color: Theme.NCTheme.border
                                    Image {
                                        anchors.top: parent.top
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        anchors.topMargin: 4
                                        width: 104
                                        height: 66
                                        source: String(pendingImageCard.modelData.url || "")
                                        fillMode: Image.PreserveAspectFit
                                        asynchronous: true
                                        cache: false
                                    }
                                    Label {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.bottom: parent.bottom
                                        anchors.margins: 4
                                        text: String(pendingImageCard.modelData.name || "")
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.microSize
                                        elide: Text.ElideMiddle
                                    }
                                    NCIconButton {
                                        objectName: "conversationRemoveImage" + pendingImageCard.index
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.margins: 2
                                        width: 24
                                        height: 24
                                        background: Rectangle {
                                            radius: 12
                                            color: Theme.NCTheme.windowRaised
                                            border.color: Theme.NCTheme.border
                                        }
                                        glyph: "×"
                                        toolTipText: qsTr("Remove %1 (%2)")
                                                     .arg(String(pendingImageCard.modelData.name || ""))
                                                     .arg(String(pendingImageCard.modelData.sizeLabel || ""))
                                        onClicked: root.bridge.removeConversationImage(pendingImageCard.index)
                                    }
                                }
                            }
                        }
                    }
                }

                NCCommandDraft {
                    Layout.fillWidth: true
                    bridge: root.bridge
                    commands: root.bridge.conversationCommands
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8

                    NCButton {
                        objectName: "conversationAddImage"
                        text: qsTr("Add image")
                        Layout.alignment: Qt.AlignBottom
                        compact: true
                        enabled: !root.bridge.conversationEditMode
                        onClicked: conversationImageFileDialog.open()
                    }

                    NCConversationComposerScroll {
                        id: composerScroll
                        objectName: "conversationComposerScroll"
                        editor: composer
                        ScrollBar.vertical.objectName: "conversationComposerScrollBar"

                        NCCommandComposer {
                            id: composer
                            objectName: "conversationComposer"
                            bridge: root.bridge
                            commands: root.bridge.conversationCommands
                            autoscroll: root.conversationAutoScroll
                            onAutoscrollRequested: value => root.conversationAutoScroll = value
                            pasteImageEnabled: true
                            placeholderText: qsTr("Type a message… (Shift+Enter for a new line)") + " — "
                                             + (root.bridge.systemRunning ? qsTr("Type / for commands")
                                                                          : qsTr("Type /initialize NC to start, or / for commands"))
                            enabled: !root.bridge.applicationClosing && !root.bridge.conversationEditMode
                            label: qsTr("Chat message")
                            onTextChanged: {
                                if (text !== String(root.conversationDraftState.composerText || ""))
                                    root.bridge.setConversationComposerDraft(text)
                            }
                            onSendRequested: outgoing => {
                                if (!outgoing.length && !Boolean(root.pendingAttachment.active))
                                    return
                                if (root.bridge.submitConversationTurn(outgoing))
                                    root.bridge.clearConversationComposerDraft()
                            }
                        }
                    }
                    NCButton {
                        id: sendButton
                        Layout.alignment: Qt.AlignBottom
                        text: composer.text.trim().startsWith("/") ? qsTr("Run command") : qsTr("Send")
                        tone: "primary"
                        enabled: !root.bridge.applicationClosing && !root.bridge.conversationEditMode
                                 && (root.bridge.systemRunning || composer.text.trim().startsWith("/"))
                                 && (composer.text.trim().length > 0
                                     || Boolean(root.pendingAttachment.active))
                        onClicked: composer.submit()
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: root.bridge.conversationCommands.status
                    visible: text.length > 0
                    color: Theme.NCTheme.textSecondary
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }

                Label {
                    Layout.fillWidth: true
                    visible: composer.spellcheckMessage.length > 0
                    text: composer.spellcheckMessage
                    color: Theme.NCTheme.error
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }

            }
        }
    }

    Popup {
        id: spotifySenseQuickViewPopup
        objectName: "spotifySenseQuickViewPopup"
        parent: Overlay.overlay
        width: Math.min(940, parent ? parent.width - Theme.NCMetrics.space24 : 940)
        height: Math.min(700, parent ? parent.height - Theme.NCMetrics.space24 : 700)
        x: parent ? Math.max(Theme.NCMetrics.space12, (parent.width - width) / 2) : 0
        y: parent ? Math.max(Theme.NCMetrics.space12, (parent.height - height) / 2) : 0
        padding: 0
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape
        z: 460

        onOpened: {
            root.bridge.refreshSpotifySenseState()
            if (root.bridge.spotifySenseState.connected)
                root.bridge.triggerSpotifySenseAction("dashboard_refresh", ({}))
        }

        background: Rectangle {
            radius: Theme.NCMetrics.radiusLarge
            color: Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.accent
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.NCMetrics.space16
            spacing: Theme.NCMetrics.space12

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space12

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space2
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Spotify Sense quick view")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.titleSize
                        font.weight: Theme.NCTypography.semibold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Control playback without leaving the conversation.")
                        color: Theme.NCTheme.textSecondary
                        font.pixelSize: Theme.NCTypography.captionSize
                    }
                }

                NCStatusChip {
                    text: Boolean(root.bridge.spotifySenseState.connected)
                          ? qsTr("Connected") : qsTr("Connection needed")
                    status: Boolean(root.bridge.spotifySenseState.connected)
                            ? "connected" : "warning"
                    compact: true
                }

                NCButton {
                    text: qsTr("Close")
                    iconText: "×"
                    iconOnly: true
                    compact: true
                    tone: "quiet"
                    toolTipText: qsTr("Close Spotify quick view")
                    onClicked: spotifySenseQuickViewPopup.close()
                }
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true

                ColumnLayout {
                    width: parent.width
                    spacing: Theme.NCMetrics.space12

                    SpotifySensePlayerPanel {
                        Layout.fillWidth: true
                        bridge: root.bridge
                        compact: true
                    }

                    NCInlineMessage {
                        Layout.fillWidth: true
                        visible: !Boolean(root.bridge.spotifySenseState.connected)
                        tone: "warning"
                        title: qsTr("Spotify connection required")
                        message: qsTr("Open the full Spotify Sense addon and use Connect to log in.")
                    }

                    NCCard {
                        Layout.fillWidth: true
                        title: qsTr("Companion actions")
                        description: qsTr("These are explicit user actions; existing Spotify awareness and safety settings remain authoritative.")

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space8

                            NCButton {
                                text: qsTr("Ask NC about artist")
                                iconText: "?"
                                enabled: root.bridge.systemRunning
                                         && ((root.bridge.spotifySenseState.track || ({})).artists || []).length > 0
                                onClicked: {
                                    const artists = ((root.bridge.spotifySenseState.track || ({})).artists || [])
                                    if (artists.length <= 0)
                                        return
                                    spotifySenseQuickViewPopup.close()
                                    root.bridge.submitConversationTurn(
                                        qsTr("Tell me about the artist %1. Use verified web information when available and do not invent biographical facts.")
                                        .arg(String(artists[0]))
                                    )
                                }
                            }

                            NCButton {
                                text: qsTr("Open Music Hub")
                                iconText: "↗"
                                tone: "primary"
                                onClicked: {
                                    spotifySenseQuickViewPopup.close()
                                    root.bridge.openAddonWorkspaceSection(
                                        "spotify_sense_tab",
                                        "Music Hub"
                                    )
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }
                }
            }
        }
    }

    // Local to Conversation Controls: keep other menus and their styling unchanged.
    component ConversationControlSwitch: NCSwitch {
        id: preferenceSwitch
        property string description: ""
        property bool preferenceChecked: false
        signal preferenceChangeRequested(bool value)
        checked: preferenceChecked
        onClicked: {
            preferenceChangeRequested(checked)
            // A rejected setting may not emit configurationChanged. Restore the
            // binding after requesting the edit so the switch still reflects it.
            checked = Qt.binding(function() { return preferenceSwitch.preferenceChecked })
        }
        Layout.fillWidth: true
        leftPadding: Theme.NCMetrics.space8
        rightPadding: Theme.NCMetrics.space8
        topPadding: Theme.NCMetrics.space6
        bottomPadding: Theme.NCMetrics.space6
        indicatorOnRight: true
        contentItem: Column {
            spacing: Theme.NCMetrics.space2
            Label {
                width: parent.width - preferenceSwitch.indicator.width - preferenceSwitch.spacing
                text: preferenceSwitch.text
                color: Theme.NCTheme.text
                font.pixelSize: Theme.NCTypography.labelSize
                wrapMode: Text.Wrap
            }
            Label {
                width: parent.width - preferenceSwitch.indicator.width - preferenceSwitch.spacing
                visible: text.length > 0
                text: preferenceSwitch.description
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.microSize
                wrapMode: Text.Wrap
            }
        }
    }

    component ConversationControlsGroup: ColumnLayout {
        id: controlsGroup
        property string title: ""
        property string description: ""
        property bool expanded: false
        default property alias content: groupBody.data
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space4

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.NCMetrics.space8
            Layout.rightMargin: Theme.NCMetrics.space8
            implicitHeight: Theme.NCMetrics.borderWidth
            color: Theme.NCTheme.borderSubtle
        }
        Button {
            id: disclosure
            objectName: controlsGroup.objectName + "Header"
            Layout.fillWidth: true
            implicitHeight: Math.max(Theme.NCMetrics.controlHeightLarge + Theme.NCMetrics.space8,
                                     contentItem.implicitHeight + topPadding + bottomPadding)
            leftPadding: Theme.NCMetrics.space8
            rightPadding: Theme.NCMetrics.space8
            checkable: true
            checked: controlsGroup.expanded
            hoverEnabled: true
            Accessible.name: controlsGroup.title
            Accessible.description: controlsGroup.description
            onToggled: controlsGroup.expanded = checked
            background: Rectangle {
                radius: Theme.NCMetrics.radiusSmall
                color: disclosure.hovered ? Theme.NCTheme.surfaceSelected : "transparent"
                border.width: disclosure.activeFocus ? Theme.NCMetrics.focusWidth : 0
                border.color: Theme.NCTheme.focus
            }
            contentItem: RowLayout {
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space2
                    Label {
                        text: controlsGroup.title
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.labelSize
                        font.weight: Theme.NCTypography.semibold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: controlsGroup.description
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.microSize
                        wrapMode: Text.Wrap
                    }
                }
                Label {
                    Layout.preferredWidth: Theme.NCMetrics.space24
                    Layout.preferredHeight: Theme.NCTypography.displaySize
                    text: "\u203A"
                    rotation: controlsGroup.expanded ? 90 : 0
                    color: Theme.NCTheme.accent
                    font.pixelSize: Theme.NCTypography.displaySize
                    font.weight: Theme.NCTypography.bold
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
        ColumnLayout {
            id: groupBody
            Layout.fillWidth: true
            visible: controlsGroup.expanded
            enabled: visible
            spacing: Theme.NCMetrics.space4
        }
    }

    Popup {
        id: conversationControlsPopup
        onHeightChanged: {
            if (opened && parent)
                y = Math.max(Theme.NCMetrics.space8,
                             Math.min(y, parent.height - height - Theme.NCMetrics.space8))
        }
        objectName: "conversationControlsPopup"
        parent: Overlay.overlay
        width: 360
        padding: Theme.NCMetrics.space8
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        z: 420
        readonly property int menuGlyphSize: Theme.NCTypography.titleSize
        readonly property int menuGlyphWidth: 30

        function openFor(control) {
            if (!control || !parent)
                return
            const mapped = control.mapToItem(parent, control.width - width,
                                             control.height + Theme.NCMetrics.space4)
            x = Math.max(Theme.NCMetrics.space8,
                         Math.min(mapped.x, parent.width - width - Theme.NCMetrics.space8))
            y = Math.max(Theme.NCMetrics.space8,
                         Math.min(mapped.y, parent.height - implicitHeight - Theme.NCMetrics.space8))
            open()
        }

        background: Rectangle {
            radius: Theme.NCMetrics.radiusLarge
            color: Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ScrollView {
            id: conversationControlsScroll
            implicitHeight: Math.min(conversationControlsContent.implicitHeight,
                                      Math.max(100, conversationControlsPopup.parent.height
                                               - 2 * conversationControlsPopup.padding - Theme.NCMetrics.space16))
            contentWidth: availableWidth
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                id: conversationControlsContent
                width: conversationControlsScroll.availableWidth
                spacing: Theme.NCMetrics.space4

            Label {
                Layout.fillWidth: true
                Layout.margins: Theme.NCMetrics.space8
                text: qsTr("CONVERSATION CONTROLS")
                color: Theme.NCTheme.accent
                font.pixelSize: Theme.NCTypography.microSize
                font.weight: Theme.NCTypography.bold
            }

            NCContextMenuItem {
                id: appearanceControl
                Layout.fillWidth: true
                objectName: "conversationAppearanceControl"
                text: qsTr("Conversation appearance")
                glyph: "◫"
                glyphPixelSize: conversationControlsPopup.menuGlyphSize
                glyphColumnWidth: conversationControlsPopup.menuGlyphWidth
                glyphFontFamily: "Segoe UI Symbol"
                trailingText: root.bridge.conversationCanvasStyle === "original"
                              ? qsTr("Original") : qsTr("Custom")
                background: Rectangle {
                    radius: Theme.NCMetrics.radiusMedium
                    color: appearanceControl.down ? Theme.NCTheme.surfacePressed
                          : appearanceControl.hovered ? Theme.NCTheme.surfaceSelected
                          : Theme.NCTheme.surface
                    border.width: appearanceControl.activeFocus
                                  ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                    border.color: appearanceControl.activeFocus
                                  ? Theme.NCTheme.focus : Theme.NCTheme.borderStrong
                }
                onClicked: {
                    conversationControlsPopup.close()
                    conversationAppearancePopup.openFor(conversationControlsButton)
                }
            }

            ConversationControlSwitch {
                objectName: "conversationLiveSessionVisibilityControl"
                text: qsTr("Show Live session card")
                description: qsTr("Status, buffer bars and voice display")
                preferenceChecked: root.bridge.conversationLiveSessionVisible
                toolTipText: qsTr("Show or hide the Live session card. Voice, rendering and playback continue when hidden.")
                onPreferenceChangeRequested: value => root.bridge.setConversationLiveSessionVisible(value)
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.NCMetrics.space8
                Layout.rightMargin: Theme.NCMetrics.space8
                spacing: Theme.NCMetrics.space10

                Label {
                    Layout.fillWidth: true
                    text: qsTr("Message font size")
                    color: Theme.NCTheme.text
                    font.pixelSize: Theme.NCTypography.labelSize
                }

                NCComboBox {
                    toolTipText: qsTr("Font size in pixels for the conversation's reading view. Saved messages and model context are unchanged.")

                    Layout.preferredWidth: 94
                    label: qsTr("Conversation font size")
                    model: [8, 10, 12, 14, 16, 18, 20]
                    currentIndex: Math.max(0, model.indexOf(root.bridge.conversationFontSize))
                    onActivated: root.bridge.setConversationFontSize(Number(model[currentIndex]))
                }
            }

            ConversationControlsGroup {
                objectName: "conversationControlsReadingGroup"
                title: qsTr("Reading")
                description: qsTr("Highlights, timestamps and scrolling")
                expanded: true

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.NCMetrics.space8
                    Layout.rightMargin: Theme.NCMetrics.space8
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Spoken text")
                        color: Theme.NCTheme.text
                    }
                    NCComboBox {
                        objectName: "conversationSpeechHighlightModeControl"
                        Layout.preferredWidth: 174
                        property var modeIds: ["off", "word", "reading"]
                        label: qsTr("Spoken-text highlight mode")
                        model: [qsTr("Off"), qsTr("Word spotlight"), qsTr("Reading current")]
                        currentIndex: Math.max(0, modeIds.indexOf(root.bridge.conversationSpeechHighlightMode))
                        toolTipText: qsTr("Choose how spoken text is highlighted, or turn highlighting off.")
                        onActivated: root.bridge.setConversationSpeechHighlightMode(modeIds[currentIndex])
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.NCMetrics.space8
                    Layout.rightMargin: Theme.NCMetrics.space8
                    spacing: Theme.NCMetrics.space8

                    Label {
                        Layout.fillWidth: true
                        text: qsTr("HIGHLIGHT APPEARANCE")
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.microSize
                        font.weight: Theme.NCTypography.bold
                    }
                    Label {
                        text: {
                            const style = root.bridge.conversationSpeechHighlightStyle
                            if (style === "rounded")
                                return qsTr("Rounded focus")
                            if (style === "glow")
                                return qsTr("Aura glow")
                            if (style === "flow")
                                return qsTr("Kinetic flow")
                            return qsTr("Current")
                        }
                        color: Theme.NCTheme.accent
                        font.pixelSize: Theme.NCTypography.microSize
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.NCMetrics.space8
                    Layout.rightMargin: Theme.NCMetrics.space8
                    spacing: Theme.NCMetrics.space6

                    NCButton {
                        Layout.fillWidth: true
                        text: qsTr("Current")
                        compact: true
                        tone: root.bridge.conversationSpeechHighlightStyle === "classic" ? "primary" : "quiet"
                        toolTipText: qsTr("Use the original flat spoken-word highlight")
                        onClicked: root.bridge.setConversationSpeechHighlightStyle("classic")
                    }
                    NCButton {
                        Layout.fillWidth: true
                        text: qsTr("Rounded focus")
                        compact: true
                        tone: root.bridge.conversationSpeechHighlightStyle === "rounded" ? "primary" : "quiet"
                        toolTipText: qsTr("Use a softly rounded focus shape around the spoken word")
                        onClicked: root.bridge.setConversationSpeechHighlightStyle("rounded")
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.NCMetrics.space8
                    Layout.rightMargin: Theme.NCMetrics.space8
                    spacing: Theme.NCMetrics.space6

                    NCButton {
                        Layout.fillWidth: true
                        text: qsTr("Aura glow")
                        compact: true
                        tone: root.bridge.conversationSpeechHighlightStyle === "glow" ? "primary" : "quiet"
                        toolTipText: qsTr("Use a restrained layered glow around the spoken word")
                        onClicked: root.bridge.setConversationSpeechHighlightStyle("glow")
                    }
                    NCButton {
                        Layout.fillWidth: true
                        text: qsTr("Kinetic flow")
                        compact: true
                        tone: root.bridge.conversationSpeechHighlightStyle === "flow" ? "primary" : "quiet"
                        toolTipText: qsTr("Animate a lightweight current through the spoken-word highlight")
                        onClicked: root.bridge.setConversationSpeechHighlightStyle("flow")
                    }
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    text: qsTr("Timestamps")
                    preferenceChecked: root.bridge.conversationTimestampsEnabled
                    onPreferenceChangeRequested: root.bridge.toggleConversationTimestamps()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    text: qsTr("Message borders")
                    preferenceChecked: root.bridge.conversationMessageBordersEnabled
                    onPreferenceChangeRequested: root.bridge.toggleConversationMessageBorders()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    text: qsTr("Autoscroll")
                    preferenceChecked: root.conversationAutoScroll
                    onPreferenceChangeRequested: root.conversationAutoScroll = !root.conversationAutoScroll
                }
            }

            ConversationControlsGroup {
                objectName: "conversationControlsVisualRepliesGroup"
                title: qsTr("Visual replies")
                description: qsTr("Image visibility, sizing and following")

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationVisualRepliesVisibleControl"
                    text: qsTr("Show generated images in chat")
                    preferenceChecked: root.bridge.conversationVisualRepliesVisible
                    onPreferenceChangeRequested: root.bridge.toggleConversationVisualRepliesVisible()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationVisualReplyAutoFollowControl"
                    text: qsTr("Auto-follow new visuals")
                    preferenceChecked: root.bridge.conversationVisualReplyAutoFollow
                    onPreferenceChangeRequested: root.bridge.toggleConversationVisualReplyAutoFollow()
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.NCMetrics.space8
                    Layout.rightMargin: Theme.NCMetrics.space8
                    spacing: Theme.NCMetrics.space6

                    NCButton {
                        Layout.fillWidth: true
                        text: qsTr("Fit window")
                        compact: true
                        tone: root.bridge.conversationVisualReplyDisplayMode === "fit" ? "primary" : "quiet"
                        toolTipText: qsTr("Show the complete generated image scaled to the conversation width")
                        onClicked: root.bridge.setConversationVisualReplyDisplayMode("fit")
                    }
                    NCButton {
                        Layout.fillWidth: true
                        text: qsTr("Fill width")
                        compact: true
                        tone: root.bridge.conversationVisualReplyDisplayMode === "fill" ? "primary" : "quiet"
                        toolTipText: qsTr("Fill the image area edge to edge; wide or tall images may be cropped")
                        onClicked: root.bridge.setConversationVisualReplyDisplayMode("fill")
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.NCMetrics.space8
                    Layout.rightMargin: Theme.NCMetrics.space8
                    spacing: Theme.NCMetrics.space6

                    NCButton {
                        Layout.fillWidth: true
                        text: qsTr("Actual size")
                        compact: true
                        tone: root.bridge.conversationVisualReplyDisplayMode === "original" ? "primary" : "quiet"
                        toolTipText: qsTr("Keep the generated pixel dimensions and pan inside the image area")
                        onClicked: root.bridge.setConversationVisualReplyDisplayMode("original")
                    }
                    NCButton {
                        Layout.fillWidth: true
                        text: qsTr("Compact")
                        compact: true
                        tone: root.bridge.conversationVisualReplyDisplayMode === "compact" ? "primary" : "quiet"
                        toolTipText: qsTr("Use a shorter preview so long conversations remain easy to scan")
                        onClicked: root.bridge.setConversationVisualReplyDisplayMode("compact")
                    }
                }
            }

            ConversationControlsGroup {
                objectName: "conversationControlsToolbarGroup"
                title: qsTr("Toolbar")
                description: qsTr("Labels and visible buttons")

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationActionLabelsControl"
                    text: qsTr("Icon labels")
                    preferenceChecked: root.bridge.conversationActionLabelsEnabled
                    onPreferenceChangeRequested: root.bridge.toggleConversationActionLabels()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationWebSearchVisibilityControl"
                    text: qsTr("Web Search control")
                    preferenceChecked: root.bridge.conversationWebSearchVisible
                    onPreferenceChangeRequested: root.bridge.toggleConversationWebSearchVisible()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationSaveButtonControl"
                    text: qsTr("Save button")
                    preferenceChecked: root.bridge.conversationSaveButtonVisible
                    onPreferenceChangeRequested: root.bridge.toggleConversationSaveButtonVisible()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationSaveAsButtonControl"
                    text: qsTr("Save as button")
                    preferenceChecked: root.bridge.conversationSaveAsButtonVisible
                    onPreferenceChangeRequested: root.bridge.toggleConversationSaveAsButtonVisible()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationLoadButtonControl"
                    text: qsTr("Load button")
                    preferenceChecked: root.bridge.conversationLoadButtonVisible
                    onPreferenceChangeRequested: root.bridge.toggleConversationLoadButtonVisible()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationMemoryButtonControl"
                    text: qsTr("Memory button")
                    preferenceChecked: root.bridge.conversationMemoryButtonVisible
                    onPreferenceChangeRequested: root.bridge.toggleConversationMemoryButtonVisible()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationResetMemoryButtonControl"
                    text: qsTr("Reset memory button")
                    preferenceChecked: root.bridge.conversationResetButtonVisible
                    onPreferenceChangeRequested: root.bridge.toggleConversationResetButtonVisible()
                }
            }

            ConversationControlsGroup {
                objectName: "conversationControlsAdvancedGroup"
                title: qsTr("Advanced")
                description: qsTr("Slash commands, guides and console")

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.NCMetrics.space8
                    Layout.rightMargin: Theme.NCMetrics.space8
                    Label {
                        text: qsTr("/commands LLM")
                        color: Theme.NCTheme.text
                    }
                    NCComboBox {
                        toolTipText: qsTr("Choose the model connection used for slash-command assistance. It is separate from the provider selected for normal conversation replies.")

                        id: commandProviderSelector
                        objectName: "conversationCommandProviderSelector"
                        Layout.fillWidth: true
                        label: qsTr("Provider for slash commands only")
                        model: root.bridge.conversationCommands.providerOptions
                        textRole: "label"
                        currentIndex: {
                            const selected = root.bridge.conversationCommands.selectedProvider
                            for (let i = 0; i < model.length; i++) {
                                if (model[i].id === selected)
                                    return i
                            }
                            return 0
                        }
                        onActivated: index => root.bridge.conversationCommands.selectProvider(model[index].id)
                        delegate: ItemDelegate {
                            id: providerOption
                            required property int index
                            readonly property var option: commandProviderSelector.model[index]
                            width: commandProviderSelector.width
                            enabled: option.enabled
                            opacity: enabled ? 1 : 0.45
                            highlighted: commandProviderSelector.highlightedIndex === index
                            contentItem: Column {
                                Label { text: providerOption.option.label; color: Theme.NCTheme.text }
                                Label {
                                    width: parent.width
                                    text: providerOption.option.detail
                                    elide: Text.ElideMiddle
                                    color: Theme.NCTheme.textMuted
                                    font.pixelSize: Theme.NCTypography.microSize
                                }
                            }
                        }
                    }
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    objectName: "conversationResponsePlacementGuidesControl"
                    text: qsTr("Placement guides")
                    preferenceChecked: root.bridge.conversationResponsePlacementGuidesEnabled
                    onPreferenceChangeRequested: root.bridge.toggleConversationResponsePlacementGuides()
                }

                ConversationControlSwitch {
                    Layout.fillWidth: true
                    text: qsTr("Split console and conversation")
                    preferenceChecked: root.consoleVisible
                    onPreferenceChangeRequested: root.bridge.setConversationConsoleVisible(
                                   !root.consoleVisible)
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.NCMetrics.space8
                Layout.rightMargin: Theme.NCMetrics.space8
                Layout.topMargin: Theme.NCMetrics.space4
                Layout.bottomMargin: Theme.NCMetrics.space4
                implicitHeight: Theme.NCMetrics.borderWidth
                color: Theme.NCTheme.borderSubtle
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.NCMetrics.space8
                Layout.rightMargin: Theme.NCMetrics.space8
                spacing: Theme.NCMetrics.space6

                NCButton {
                    objectName: "conversationQuickSaveButton"
                    Layout.fillWidth: true
                    text: qsTr("Quick Save")
                    compact: true
                    tone: "secondary"
                    enabled: !root.bridge.conversationContextBusy
                    toolTipText: qsTr("Save the complete current chat context to the quick-save file")
                    onClicked: {
                        conversationControlsPopup.close()
                        Qt.callLater(function() {
                            root.bridge.quickSaveConversationContext()
                        })
                    }
                }
                NCButton {
                    objectName: "conversationQuickLoadButton"
                    Layout.fillWidth: true
                    text: qsTr("Quick Load")
                    compact: true
                    tone: "secondary"
                    enabled: !root.bridge.conversationContextBusy
                    toolTipText: qsTr("Restore the complete chat context from the quick-save file")
                    onClicked: {
                        conversationControlsPopup.close()
                        Qt.callLater(function() {
                            root.bridge.quickLoadConversationContext()
                        })
                    }
                }
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                text: qsTr("Clear visible transcript")
                glyph: "\u232B"
                glyphPixelSize: conversationControlsPopup.menuGlyphSize
                glyphColumnWidth: conversationControlsPopup.menuGlyphWidth
                glyphFontFamily: "Segoe UI Symbol"
                onClicked: {
                    root.bridge.clearConversationDisplay()
                    conversationControlsPopup.close()
                }
            }

            }
        }
    }

    NCConversationAppearancePopup {
        id: conversationAppearancePopup
        parent: Overlay.overlay
        bridge: root.bridge
    }

    Popup {
        id: visualReplyContextPopup
        objectName: "visualReplyContextPopup"
        parent: Overlay.overlay
        width: 320
        padding: Theme.NCMetrics.space8
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        z: 435

        background: Rectangle {
            radius: Theme.NCMetrics.radiusLarge
            color: Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space4

            Label {
                Layout.fillWidth: true
                Layout.margins: Theme.NCMetrics.space8
                text: qsTr("VISUAL REPLY")
                color: Theme.NCTheme.accent
                font.pixelSize: Theme.NCTypography.microSize
                font.weight: Theme.NCTypography.bold
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                text: qsTr("Open and zoom")
                glyph: "↗"
                onClicked: {
                    const asset = root.visualReplyContextAsset
                    visualReplyContextPopup.close()
                    root.openVisualReplyFocus(asset)
                }
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                text: qsTr("Comment on this image")
                glyph: "✎"
                onClicked: {
                    const url = String(root.visualReplyContextAsset.url || "")
                    visualReplyContextPopup.close()
                    if (root.bridge.stageVisualReplyComment(url)) {
                        root.conversationComposer.forceActiveFocus()
                        root.scrollConversationToBottom(true, true)
                    }
                }
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                text: qsTr("Add variation")
                glyph: "↻"
                trailingText: qsTr("Keep original")
                enabled: root.bridge.systemRunning
                         && String(root.visualReplyContextAsset.prompt || "").length > 0
                onClicked: {
                    const historyIndex = Number(
                                root.visualReplyContextAsset.historyIndex !== undefined
                                ? root.visualReplyContextAsset.historyIndex : -1)
                    visualReplyContextPopup.close()
                    root.bridge.addVisualReplyVariation(historyIndex)
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.NCMetrics.space8
                Layout.rightMargin: Theme.NCMetrics.space8
                Layout.topMargin: Theme.NCMetrics.space4
                Layout.bottomMargin: Theme.NCMetrics.space4
                implicitHeight: Theme.NCMetrics.borderWidth
                color: Theme.NCTheme.borderSubtle
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                text: qsTr("Save image as…")
                glyph: "⇩"
                onClicked: {
                    root.visualReplySaveSource = String(
                                root.visualReplyContextAsset.url || "")
                    visualReplyContextPopup.close()
                    visualReplySaveDialog.currentFile = root.visualReplySaveSource
                    visualReplySaveDialog.open()
                }
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                text: qsTr("Copy image")
                glyph: "⧉"
                onClicked: {
                    root.bridge.copyVisualReplyImage(
                                String(root.visualReplyContextAsset.url || ""))
                    visualReplyContextPopup.close()
                }
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                text: qsTr("Open file location")
                glyph: "▣"
                onClicked: {
                    root.bridge.openVisualReplyLocation(
                                String(root.visualReplyContextAsset.url || ""))
                    visualReplyContextPopup.close()
                }
            }
        }
    }

    Popup {
        id: visualReplyFocusPopup
        objectName: "visualReplyFocusPopup"
        parent: Overlay.overlay
        width: Math.min(1100, parent ? parent.width - Theme.NCMetrics.space24 : 1100)
        height: Math.min(760, parent ? parent.height - Theme.NCMetrics.space24 : 760)
        x: parent ? Math.max(Theme.NCMetrics.space12, (parent.width - width) / 2) : 0
        y: parent ? Math.max(Theme.NCMetrics.space12, (parent.height - height) / 2) : 0
        padding: 0
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        z: 440

        background: Rectangle {
            radius: Theme.NCMetrics.radiusLarge
            color: Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.accent
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.NCMetrics.space12
            spacing: Theme.NCMetrics.space10

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8

                NCStatusChip {
                    text: root.visualReplyFocusLabel
                    status: "active"
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Focus view")
                    color: Theme.NCTheme.text
                    font.pixelSize: Theme.NCTypography.headingSize
                    font.weight: Theme.NCTypography.semibold
                }
                Label {
                    text: qsTr("Zoom")
                    color: Theme.NCTheme.textSecondary
                    font.pixelSize: Theme.NCTypography.captionSize
                }
                NCSlider {
                    toolTipText: qsTr("Zoom the focused image view. This changes display magnification and does not regenerate or resize the stored image.")

                    Layout.preferredWidth: 180
                    label: qsTr("Image focus zoom")
                    from: 1.0
                    to: 3.0
                    stepSize: 0.1
                    value: root.visualReplyFocusZoom
                    onMoved: root.visualReplyFocusZoom = value
                }
                Label {
                    text: Math.round(root.visualReplyFocusZoom * 100) + "%"
                    color: Theme.NCTheme.accentSoft
                    font.pixelSize: Theme.NCTypography.captionSize
                }
                NCIconButton {
                    glyph: "×"
                    toolTipText: qsTr("Close image focus view")
                    onClicked: visualReplyFocusPopup.close()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.NCMetrics.radiusMedium
                color: Theme.NCTheme.window
                border.width: Theme.NCMetrics.borderWidth
                border.color: Theme.NCTheme.border
                clip: true

                Flickable {
                    id: visualReplyFocusViewport
                    anchors.fill: parent
                    anchors.margins: Theme.NCMetrics.space8
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    contentWidth: Math.max(width, visualReplyFocusImage.width)
                    contentHeight: Math.max(height, visualReplyFocusImage.height)

                    Image {
                        id: visualReplyFocusImage
                        readonly property real imageRatio:
                            status === Image.Ready && sourceSize.width > 0 && sourceSize.height > 0
                            ? sourceSize.width / sourceSize.height : 16 / 9
                        readonly property real fittedWidth:
                            Math.min(visualReplyFocusViewport.width,
                                     visualReplyFocusViewport.height * imageRatio)
                        readonly property real fittedHeight: fittedWidth / imageRatio
                        x: Math.max(0, (visualReplyFocusViewport.width - width) / 2)
                        y: Math.max(0, (visualReplyFocusViewport.height - height) / 2)
                        width: Math.max(1, fittedWidth * root.visualReplyFocusZoom)
                        height: Math.max(1, fittedHeight * root.visualReplyFocusZoom)
                        source: root.visualReplyFocusUrl
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        cache: false
                        smooth: true
                        mipmap: true
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                visible: root.visualReplyFocusPrompt.length > 0
                text: root.visualReplyFocusPrompt
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }
    }

    Popup {
        id: conversationEditPopup
        parent: Overlay.overlay
        width: 272
        padding: Theme.NCMetrics.space8
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        z: 420

        function openFor(control) {
            if (!control || !parent)
                return
            const mapped = control.mapToItem(parent, 0, control.height + Theme.NCMetrics.space4)
            x = Math.max(Theme.NCMetrics.space8,
                         Math.min(mapped.x, parent.width - width - Theme.NCMetrics.space8))
            y = Math.max(Theme.NCMetrics.space8,
                         Math.min(mapped.y, parent.height - implicitHeight - Theme.NCMetrics.space8))
            open()
        }

        background: Rectangle {
            radius: Theme.NCMetrics.radiusLarge
            color: Theme.NCTheme.windowRaised
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space4

            Label {
                Layout.fillWidth: true
                Layout.margins: Theme.NCMetrics.space8
                text: qsTr("CONVERSATION EDITING")
                color: Theme.NCTheme.accent
                font.pixelSize: Theme.NCTypography.microSize
                font.weight: Theme.NCTypography.bold
            }

            NCContextMenuItem {
                visible: !root.bridge.conversationEditMode
                Layout.preferredHeight: visible ? implicitHeight : 0
                text: qsTr("Start edit mode")
                glyph: "✎"
                onClicked: {
                    conversationEditPopup.close()
                    root.changeCanonicalEdit("begin")
                }
            }

            NCContextMenuItem {
                visible: root.bridge.conversationEditMode
                Layout.preferredHeight: visible ? implicitHeight : 0
                text: qsTr("Apply changes")
                glyph: "✓"
                onClicked: {
                    conversationEditPopup.close()
                    root.changeCanonicalEdit("apply")
                }
            }

            NCContextMenuItem {
                visible: root.bridge.conversationEditMode
                Layout.preferredHeight: visible ? implicitHeight : 0
                text: qsTr("Cancel editing")
                glyph: "×"
                onClicked: {
                    conversationEditPopup.close()
                    root.changeCanonicalEdit("cancel")
                }
            }
        }
    }

    Popup {
        id: avatarContextPopup
        parent: Overlay.overlay
        width: Math.min(420, parent ? parent.width - Theme.NCMetrics.space24 : 420)
        height: Math.min(560, parent ? parent.height - Theme.NCMetrics.space24 : 560)
        padding: 0
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        z: 400

        background: Rectangle {
            radius: Theme.NCMetrics.radiusLarge
            color: Theme.NCTheme.surface
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.NCMetrics.space16
            spacing: Theme.NCMetrics.space12

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space2

                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Avatar options")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.headingSize
                        font.weight: Theme.NCTypography.semibold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Resize the portrait, change the active quick persona, or switch only its conversation voice.")
                        color: Theme.NCTheme.textSecondary
                        font.pixelSize: Theme.NCTypography.captionSize
                        wrapMode: Text.Wrap
                    }
                }

                NCIconButton {
                    glyph: "×"
                    toolTipText: qsTr("Close avatar options")
                    onClicked: avatarContextPopup.close()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: avatarSizeRow.implicitHeight + Theme.NCMetrics.space16
                radius: Theme.NCMetrics.radiusMedium
                color: Theme.NCTheme.windowRaised
                border.width: Theme.NCMetrics.borderWidth
                border.color: Theme.NCTheme.border

                RowLayout {
                    id: avatarSizeRow
                    anchors.fill: parent
                    anchors.margins: Theme.NCMetrics.space8
                    spacing: Theme.NCMetrics.space8

                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Avatar size")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.bodySize
                        font.weight: Theme.NCTypography.semibold
                    }

                    NCIconButton {
                        glyph: "−"
                        enabled: root.bridge.conversationPersonaAvatarSize > 80
                        toolTipText: qsTr("Decrease avatar size")
                        onClicked: root.bridge.setConversationPersonaAvatarSize(
                                       root.bridge.conversationPersonaAvatarSize - 20)
                    }

                    Label {
                        Layout.preferredWidth: 58
                        text: qsTr("%1 px").arg(root.bridge.conversationPersonaAvatarSize)
                        color: Theme.NCTheme.textSecondary
                        font.pixelSize: Theme.NCTypography.labelSize
                        horizontalAlignment: Text.AlignHCenter
                    }

                    NCIconButton {
                        glyph: "+"
                        enabled: root.bridge.conversationPersonaAvatarSize < 400
                        toolTipText: qsTr("Increase avatar size")
                        onClicked: root.bridge.setConversationPersonaAvatarSize(
                                       root.bridge.conversationPersonaAvatarSize + 20)
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8

                NCButton {
                    Layout.fillWidth: true
                    text: qsTr("Change avatar / persona")
                    iconText: "◉"
                    tone: root.avatarContextSection === "persona" ? "primary" : "secondary"
                    onClicked: root.avatarContextSection = "persona"
                }
                NCButton {
                    Layout.fillWidth: true
                    text: qsTr("Change voice")
                    iconText: "♪"
                    tone: root.avatarContextSection === "voice" ? "primary" : "secondary"
                    onClicked: root.avatarContextSection = "voice"
                }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: root.avatarContextSection === "voice" ? 1 : 0

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ListView {
                        id: personaChoiceList
                        anchors.fill: parent
                        clip: true
                        spacing: Theme.NCMetrics.space8
                        boundsBehavior: Flickable.StopAtBounds
                        model: root.bridge.quickPersonaChoices

                        delegate: Rectangle {
                            id: personaChoice
                            required property var modelData
                            width: ListView.view.width
                            height: 78
                            radius: Theme.NCMetrics.radiusMedium
                            color: Boolean(modelData.active) ? Theme.NCTheme.surfaceSelected
                                  : personaChoiceHover.hovered ? Theme.NCTheme.surfaceRaised
                                  : Theme.NCTheme.windowRaised
                            border.width: Boolean(modelData.active) ? Theme.NCMetrics.focusWidth : 1
                            border.color: Boolean(modelData.active) ? Theme.NCTheme.accent : Theme.NCTheme.border

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: Theme.NCMetrics.space8
                                spacing: Theme.NCMetrics.space10

                                Rectangle {
                                    Layout.preferredWidth: 58
                                    Layout.preferredHeight: 58
                                    radius: 29
                                    color: personaChoiceImage.status === Image.Ready ? "transparent" : Theme.NCTheme.surface
                                    border.width: 1
                                    border.color: Theme.NCTheme.borderStrong
                                    clip: true

                                    Image {
                                        id: personaChoiceImage
                                        anchors.fill: parent
                                        anchors.margins: 1
                                        source: String(personaChoice.modelData.avatarUrl || "")
                                        fillMode: Image.PreserveAspectFit
                                        asynchronous: true
                                        cache: false
                                        visible: status === Image.Ready
                                    }

                                    Label {
                                        anchors.centerIn: parent
                                        visible: personaChoiceImage.status !== Image.Ready
                                        text: String(personaChoice.modelData.name || "NC").slice(0, 2).toUpperCase()
                                        color: Theme.NCTheme.accent
                                        font.pixelSize: Theme.NCTypography.labelSize
                                        font.weight: Theme.NCTypography.bold
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.NCMetrics.space2

                                    Label {
                                        Layout.fillWidth: true
                                        text: String(personaChoice.modelData.name || qsTr("Quick persona"))
                                        color: Theme.NCTheme.text
                                        font.pixelSize: Theme.NCTypography.bodySize
                                        font.weight: Theme.NCTypography.semibold
                                        elide: Text.ElideRight
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: Boolean(personaChoice.modelData.active)
                                              ? qsTr("Active quick persona")
                                              : String(personaChoice.modelData.slotLabel || "")
                                        color: Boolean(personaChoice.modelData.active) ? Theme.NCTheme.success : Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.captionSize
                                        elide: Text.ElideRight
                                    }
                                }

                                Label {
                                    text: Boolean(personaChoice.modelData.active) ? "✓" : "›"
                                    color: Boolean(personaChoice.modelData.active) ? Theme.NCTheme.success : Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.headingSize
                                }
                            }

                            HoverHandler { id: personaChoiceHover }
                            TapHandler {
                                onTapped: {
                                    root.bridge.applyQuickPersona(Number(personaChoice.modelData.slot))
                                    avatarContextPopup.close()
                                }
                            }
                            Accessible.name: qsTr("Use quick persona %1").arg(String(modelData.name || ""))
                        }

                        ScrollBar.vertical: ScrollBar { }
                    }

                    NCEmptyState {
                        anchors.centerIn: parent
                        width: Math.min(parent.width - Theme.NCMetrics.space24, 300)
                        visible: personaChoiceList.count === 0
                        glyph: "◌"
                        title: qsTr("No quick personas yet")
                        description: qsTr("Save a quick persona in the Persona workspace, then right-click an avatar again.")
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: Theme.NCMetrics.space8

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("Voice references")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            NCButton {
                                text: qsTr("Update list")
                                compact: true
                                tone: "quiet"
                                onClicked: root.bridge.refreshVoiceOptions()
                            }
                        }

                        ListView {
                            id: voiceChoiceList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: Theme.NCMetrics.space6
                            boundsBehavior: Flickable.StopAtBounds
                            model: root.bridge.voiceOptions

                            delegate: Rectangle {
                                id: voiceChoice
                                required property var modelData
                                readonly property bool activeVoice:
                                    root.normalizedVoicePath(modelData.value)
                                    === root.normalizedVoicePath(root.bridge.personaState.voicePath)
                                width: ListView.view.width
                                height: 52
                                radius: Theme.NCMetrics.radiusMedium
                                color: activeVoice ? Theme.NCTheme.surfaceSelected
                                      : voiceChoiceHover.hovered ? Theme.NCTheme.surfaceRaised
                                      : Theme.NCTheme.windowRaised
                                border.width: activeVoice ? Theme.NCMetrics.focusWidth : 1
                                border.color: activeVoice ? Theme.NCTheme.accent : Theme.NCTheme.border

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: Theme.NCMetrics.space12
                                    anchors.rightMargin: Theme.NCMetrics.space12

                                    Label {
                                        text: "♪"
                                        color: voiceChoice.activeVoice ? Theme.NCTheme.accent : Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.headingSize
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: String(voiceChoice.modelData.label || qsTr("Voice"))
                                        color: Theme.NCTheme.text
                                        font.pixelSize: Theme.NCTypography.bodySize
                                        elide: Text.ElideMiddle
                                    }
                                    Label {
                                        text: voiceChoice.activeVoice ? qsTr("Active") : "›"
                                        color: voiceChoice.activeVoice ? Theme.NCTheme.success : Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.captionSize
                                    }
                                }

                                HoverHandler { id: voiceChoiceHover }
                                TapHandler {
                                    onTapped: {
                                        root.bridge.setConversationVoiceReference(String(voiceChoice.modelData.value || ""))
                                        avatarContextPopup.close()
                                    }
                                }
                                Accessible.name: qsTr("Use voice %1").arg(String(modelData.label || ""))
                            }

                            ScrollBar.vertical: ScrollBar { }
                        }
                    }
                }
            }
        }
    }

    DropArea {
        id: conversationImageDropArea
        enabled: !root.showingLocalRoom
        anchors.fill: parent
        z: 100
        onEntered: drag => {
            drag.accepted = root.firstDroppedImageUrl(drag.urls || []).length > 0
        }
        onDropped: drop => root.acceptImageDrop(drop)

        Rectangle {
            anchors.fill: parent
            visible: conversationImageDropArea.containsDrag
            color: Theme.NCTheme.windowRaised
            opacity: 0.96
            radius: Theme.NCMetrics.radiusLarge
            border.width: 2
            border.color: Theme.NCTheme.accent

            Column {
                anchors.centerIn: parent
                spacing: Theme.NCMetrics.space8

                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr("Drop image to attach")
                    color: Theme.NCTheme.text
                    font.pixelSize: Theme.NCTypography.titleSize
                    font.weight: Theme.NCTypography.bold
                }
                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr("You can add a question or comment before sending")
                    color: Theme.NCTheme.textSecondary
                    font.pixelSize: Theme.NCTypography.bodySize
                }
            }
        }
    }

    FileDialog {
        id: conversationImageFileDialog
        title: qsTr("Attach images")
        fileMode: FileDialog.OpenFiles
        nameFilters: [
            qsTr("Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"),
            qsTr("All files (*)")
        ]
        onAccepted: root.bridge.stageConversationImages(selectedFiles.map(file => file.toString()))
    }

    FileDialog {
        id: visualReplySaveDialog
        title: qsTr("Save Visual Reply image")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("Image files (*.png *.jpg *.jpeg *.webp *.bmp)")]
        onAccepted: root.bridge.saveVisualReplyImage(
                        root.visualReplySaveSource,
                        selectedFile.toString())
    }

    NCDialog {
        id: consoleFontSizeDialog
        objectName: "consoleFontSizeDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(360, parent ? parent.width - 24 : 360)
        title: qsTr("System console font size")
        acceptText: qsTr("Apply")
        onOpened: consoleFontSizeSpinBox.value = Number(root.bridge.conversationConsoleFontSize || 12)
        contentItem: RowLayout {
            spacing: Theme.NCMetrics.space12
            Label {
                Layout.fillWidth: true
                text: qsTr("Size (pixels)")
                color: Theme.NCTheme.text
            }
            NCSpinBox {
                id: consoleFontSizeSpinBox
                objectName: "consoleFontSizeSpinBox"
                label: qsTr("Console font size")
                toolTipText: qsTr("Choose a console text size from 8 to 32 pixels.")
                from: 8
                to: 32
            }
        }
        onAccepted: root.bridge.setConversationConsoleFontSize(consoleFontSizeSpinBox.value)
    }

    NCDialog {
        id: messageDeleteDialog
        objectName: "conversationDeleteMessageDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Delete message?")
        description: qsTr("Delete this message, its attachments, and associated memories. Later replies will remain. Save afterward to update the saved chat.")
        acceptText: qsTr("Delete")
        acceptTone: "danger"
        acceptEnabled: root.messageDeletionAvailable
        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space8
            Label {
                Layout.fillWidth: true
                text: String(root.messageDeletionSelection.preview || qsTr("Image attachment"))
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Theme.NCTheme.text
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("Images still used by other messages are kept.")
                wrapMode: Text.Wrap
                color: Theme.NCTheme.textSecondary
            }
        }
        onAccepted: root.bridge.deleteConversationMessage(
                        String(root.messageDeletionSelection.messageId),
                        Number(root.messageDeletionSelection.revision),
                        Number(root.messageDeletionSelection.session), true)
    }

    NCDialog {
        id: userMessageDraftDialog
        objectName: "conversationCopiedPromptDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(720, Overlay.overlay ? Overlay.overlay.width - 64 : 720)
        title: qsTr("Edit as a new prompt")
        description: composer.text.trim().length > 0
                     ? qsTr("The original message and its replies stay unchanged. Using this copy will replace the unsent draft in the composer.")
                     : qsTr("The original message and its replies stay unchanged. Edit this copy, then place it in the composer as a new prompt.")
        acceptText: composer.text.trim().length > 0
                    ? qsTr("Replace draft") : qsTr("Use draft")
        acceptEnabled: userMessageDraftEditor.text.trim().length > 0

        contentItem: NCTextArea {
            toolTipText: qsTr("Edit a copy of a previous user prompt before sending it as a new message. The original message remains unchanged.")

            id: userMessageDraftEditor
            objectName: "conversationCopiedPromptEditor"
            label: qsTr("New prompt draft")
            implicitHeight: Math.max(180, contentHeight + topPadding + bottomPadding)
            font.pixelSize: root.conversationFontPixels
            onTextChanged: root.bridge.setConversationCopiedPromptDraft(text)
        }

        onOpened: {
            userMessageDraftEditor.text = root.pendingUserDraftText
            Qt.callLater(function() {
                userMessageDraftEditor.forceActiveFocus()
                userMessageDraftEditor.cursorPosition = userMessageDraftEditor.length
            })
        }
        onAccepted: {
            root.bridge.setConversationComposerDraft(userMessageDraftEditor.text)
            root.bridge.clearConversationCopiedPromptDraft()
            Qt.callLater(function() {
                composer.forceActiveFocus()
                composer.cursorPosition = composer.length
            })
        }
        onRejected: root.bridge.clearConversationCopiedPromptDraft()
    }

    NCDialog {
        id: conversationWebSearchUnavailableDialog
        objectName: "conversationWebSearchUnavailableDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Web Search servers are not installed")
        description: qsTr("No Web Search server launcher is installed. Open the addon to install the servers, then use this toggle to start them and enable Web Search.")
        acceptText: qsTr("Open Web Search addon")
        rejectText: qsTr("Cancel")
        onAccepted: root.bridge.openAddonWorkspaceSection("web_intelligence_tab", "Servers")
    }

    NCDialog {
        id: resetDialog
        anchors.centerIn: parent
        title: qsTr("Reset chat memory?")
        description: qsTr("This clears the current in-memory conversation using the existing session reset path.")
        acceptText: qsTr("Reset memory")
        acceptTone: "danger"
        onAccepted: root.bridge.resetConversation()
    }
}
