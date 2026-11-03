pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "conversationMemoryWorkspace"
    required property var bridge
    readonly property var controller: bridge.memoryWorkspace
    readonly property var state: controller.state
    readonly property bool savedConversation: Boolean(String(state.contextPath || "").trim())
    property bool advancedExpanded: false
    spacing: Theme.NCMetrics.space12
    Component.onCompleted: controller.refresh()

    NCSectionHeader {
        Layout.fillWidth: true
        title: qsTr("Memory")
        description: root.state.contextName
                     ? qsTr("What NC remembers from “%1”.").arg(root.state.contextName)
                     : qsTr("Conversation memory is inactive until you save this conversation. Your memory preferences are kept.")
    }
    NCInlineMessage {
        Layout.fillWidth: true
        visible: Boolean(root.state.busy) || Boolean(root.state.error)
        tone: root.state.error ? "error" : "info"
        title: root.state.error ? qsTr("Memory action failed") : String(root.state.busyLabel || qsTr("Working…"))
        message: String(root.state.error || "")
    }
    Label {
        Layout.fillWidth: true
        visible: text.length > 0
        text: String(root.state.repairHeadline || "")
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }
    NCCard {
        Layout.fillWidth: true
        objectName: "conversationMemorySummaryCard"
        title: qsTr("Conversation summary")
        description: qsTr("Short notes that help NC follow a long conversation.")
        headerAccessory: NCSwitch {
            toolTipText: qsTr("Maintain conversation memory for a saved chat context. This keeps a summary associated with that conversation; save a conversation before enabling its memory controls.")

            text: checked ? qsTr("On") : qsTr("Off")
            Accessible.name: qsTr("Keep a conversation summary")
            checked: root.savedConversation && Boolean(root.bridge.coreSettings.continuity_memory_enabled)
            enabled: root.savedConversation && !root.state.busy
            onClicked: root.bridge.setCoreSetting("continuity_memory_enabled", checked)
        }
        Label {
            Layout.fillWidth: true
            text: String(root.state.summaryHeadline || qsTr("No summary yet."))
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        NCCheckBox {
            toolTipText: qsTr("Include the conversation summary in model requests. The summary can still be stored when this is off; this controls whether the model receives it.")

            text: qsTr("Use the summary in replies")
            checked: root.savedConversation && Boolean(root.bridge.coreSettings.continuity_memory_inject)
            enabled: root.savedConversation && !root.state.busy
            onClicked: root.bridge.setCoreSetting("continuity_memory_inject", checked)
        }
        Flow {
            Layout.fillWidth: true
            spacing: 8
            enabled: root.savedConversation && !root.state.busy
            NCButton { objectName: "reviewMemoryButton"; text: qsTr("Read summary"); onClicked: root.controller.runAction("review_summary", {}) }
            NCButton { text: qsTr("Update now"); onClicked: root.controller.runAction("summarize_recent", {turnCount: Math.max(1, Number(root.state.totalMessages || 120))}) }
        }
    }
    NCCard {
        Layout.fillWidth: true
        objectName: "conversationMemoryArchiveCard"
        title: qsTr("Older messages")
        description: qsTr("Automatically store older messages")
        headerAccessory: NCSwitch {
            toolTipText: qsTr("Automatically archive eligible messages from the saved conversation for later memory searches. Turning this off stops automatic archiving and keeps existing archive records.")

            text: checked ? qsTr("On") : qsTr("Off")
            Accessible.name: qsTr("Automatically store older messages")
            checked: root.savedConversation && Boolean(root.bridge.coreSettings.long_term_memory_auto_archive_enabled)
            enabled: root.savedConversation && !root.state.busy
            onClicked: root.bridge.setCoreSetting("long_term_memory_auto_archive_enabled", checked)
        }
        Label { Layout.fillWidth: true; text: String(root.state.archiveStatus || ""); color: Theme.NCTheme.textSecondary; wrapMode: Text.Wrap }
        NCCheckBox {
            toolTipText: qsTr("Allow NC to retrieve relevant messages from the conversation archive for replies. Existing stored messages remain when retrieval is disabled.")

            Layout.fillWidth: true
            text: qsTr("Allow NC to search stored messages")
            checked: root.savedConversation && Boolean(root.bridge.coreSettings.long_term_memory_retrieval_enabled)
            enabled: root.savedConversation && !root.state.busy
            onClicked: root.bridge.setCoreSetting("long_term_memory_retrieval_enabled", checked)
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("Relevant past messages are given to the LLM as context when it answers.")
            color: Theme.NCTheme.textMuted
            wrapMode: Text.Wrap
        }
        Flow {
            Layout.fillWidth: true
            spacing: 8
            enabled: root.savedConversation && !root.state.busy
            NCButton { text: qsTr("Browse stored messages"); onClicked: root.controller.runAction("review_archive", {}) }
            NCButton { text: qsTr("Find a memory"); onClicked: search.open() }
        }
    }
    NCCard {
        Layout.fillWidth: true
        objectName: "conversationMemorySearchCard"
        title: qsTr("Memory search")
        description: Boolean(root.bridge.coreSettings.long_term_memory_embedding_enabled)
                     ? qsTr("Finds related ideas, even when the wording is different.")
                     : qsTr("Keyword search is available. Add a search model to find related ideas too.")
        Label {
            Layout.fillWidth: true
            text: root.savedConversation ? String(root.state.embeddingStatus || qsTr("Basic keyword search"))
                                         : qsTr("Save this conversation to use memory search.")
            color: root.state.searchNeedsAttention ? Theme.NCTheme.warning : Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            visible: Boolean(root.bridge.coreSettings.long_term_memory_embedding_enabled)
            text: String(root.state.searchSource || "")
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        NCButton {
            objectName: "retryMemoryIndexingButton"
            visible: Boolean(root.state.canRetryIndexing)
            enabled: root.savedConversation && !root.state.busy
            text: qsTr("Retry indexing")
            onClicked: root.controller.runAction("rebuild_embeddings", {limit: 0, clearExisting: false})
        }
        NCButton {
            objectName: "memorySearchSetupButton"
            text: root.bridge.coreSettings.long_term_memory_embedding_enabled ? qsTr("Change setup…") : qsTr("Set up memory search…")
            onClicked: root.bridge.openMemorySearchSetup()
        }
    }
    Label { Layout.fillWidth: true; text: qsTr("Save and load conversations from the Conversation view."); color: Theme.NCTheme.textMuted; wrapMode: Text.Wrap }
    NCButton {
        objectName: "memoryAdvancedToggle"
        text: root.advancedExpanded ? qsTr("▾ Advanced settings") : qsTr("▸ Advanced settings")
        tone: "quiet"
        onClicked: root.advancedExpanded = !root.advancedExpanded
    }
    MemoryAdvancedSettings {
        objectName: "memoryAdvancedSettings"
        Layout.fillWidth: true
        visible: root.advancedExpanded
        bridge: root.bridge
    }
    NCDialog {
        id: search
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Find a memory")
        acceptText: qsTr("Search")
        NCTextField {
            toolTipText: qsTr("Text to search for in stored conversation memories. This searches the archive and does not send a normal chat reply.")
 id: query; width: parent.width; placeholderText: qsTr("What would you like to find?"); onAccepted: search.accept() }
        onAccepted: root.controller.runAction("search_archive", {query: query.text})
    }
}
