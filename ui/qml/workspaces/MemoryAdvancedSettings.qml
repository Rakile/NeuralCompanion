pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../components"
import "../theme" as Theme

ColumnLayout {
    id: root
    required property var bridge
    readonly property var controller: bridge.memoryWorkspace
    readonly property var state: controller.state
    property string pendingAction: ""
    property var pendingParams: ({})
    spacing: Theme.NCMetrics.space12
    function run(action, params) { controller.runAction(action, params || {}) }
    function confirm(action, params, message) {
        pendingAction = action; pendingParams = params || {}; confirmationText.text = message; confirmation.open()
    }
    function field(key, label, type, description, minimum, maximum, step) {
        return {key:key, label:label, type:type, description:description,
                minimum:minimum, maximum:maximum, step:step}
    }

    NCSettingsGroup {
        Layout.fillWidth: true
        title: qsTr("Summary updates")
        description: qsTr("Choose when and how much to summarize.")
        readOnly: Boolean(root.state.busy)
        values: root.bridge.coreSettings
        schema: [

            root.field("continuity_memory_auto_summarize", qsTr("Enable Conversation Memory summarization"), "boolean",
                       qsTr("Updates the summary automatically as new messages arrive. Saving the chat context also refreshes it. This is separate from Long-Term archiving.")),

            root.field("continuity_memory_auto_turns", qsTr("Update every (messages)"), "integer",
                       qsTr("New messages needed to trigger an automatic update. If too many accumulate, the status below explains how to catch up."), 1, 10000, 10),
            root.field("continuity_memory_max_chars", qsTr("Summary size (characters)"), "integer",
                       qsTr("Maximum characters kept in the saved summary. Longer text is trimmed to fit."), 500, 20000, 250)
        ]
        onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
        Flow {
            Layout.fillWidth: true
            spacing: 8
            enabled: !root.state.busy
            NCButton { objectName: "advancedReviewMemoryButton"; text: qsTr("Review Summary"); onClicked: root.run("review_summary") }
            NCButton { text: qsTr("Summarize Recent Messages…"); onClicked: summarize.open() }
            NCButton { objectName: "forgetMemoryButton"; text: qsTr("Forget Summary"); onClicked: root.confirm("forget_summary", {}, qsTr("Forget the running conversation summary? The chat and long-term archive are retained.")) }
        }
    }
    NCSettingsGroup {
        Layout.fillWidth: true
        title: qsTr("Recall options and tools")
        description: qsTr("Fine-tune recalled text and images, or repair stored memory.")
        readOnly: Boolean(root.state.busy)
        values: root.bridge.coreSettings
        schema: [

            root.field("long_term_memory_image_review_enabled", qsTr("Review recalled images before sending"), "boolean",
                       qsTr("Shows recalled images for approval before a reply. The reply waits for your selection.")),

            root.field("long_term_memory_archive_batch_turns", qsTr("Archive every (messages)"), "integer",
                       qsTr("Messages between automatic archives. Also the default chunk size when rebuilding an archive candidate."), 1, 10000),
            root.field("long_term_memory_retrieval_max_items", qsTr("Archive notes to use"), "integer",
                       qsTr("Archive records recalled per reply. Related raw chat chunks may be added too (at most four)."), 1, 12),
            root.field("long_term_memory_recall_text_budget", qsTr("Recall text budget (chars, -1 = no cap)"), "integer",
                       qsTr("Character budget for recalled text per reply. -1 means no cap; 0 omits recalled text bodies."), -1, 2147483647, 500),
            root.field("long_term_memory_recall_image_limit", qsTr("Long-Term Memory recalled images to attach"), "integer",
                       qsTr("Recalled images attached per reply. -1 means no limit; 0 recalls text only. The chat model must accept images."), -1, 2147483647),
            root.field("long_term_memory_image_context_max_output_tokens", qsTr("Image-context judge max output tokens (advanced)"), "integer",
                       qsTr("Output token limit for the model that chooses which recalled images to use."), 256, 131072, 256),

        ]
        onSettingEdited: (key, value) => root.bridge.setCoreSetting(key, value)
        Flow {
            Layout.fillWidth: true
            spacing: 8
            enabled: !root.state.busy
            NCButton { text: qsTr("Search Archive…"); onClicked: search.open() }
            NCButton { text: qsTr("Review Archive"); onClicked: root.run("review_archive") }
            NCButton { text: qsTr("Export Session Memory…"); onClicked: reportFile.open() }
            NCButton { text: qsTr("Rebuild Archive Candidate…"); onClicked: archiveFile.open() }
            NCButton { text: qsTr("Rebuild Embeddings"); onClicked: embeddings.open() }
        }
    }
    Label { Layout.fillWidth: true; text: String(root.state.technicalDetails || "") + "\n" + String(root.state.embeddingDiagnostics || "") + "\n" + String(root.state.repairStatus || ""); color: Theme.NCTheme.textSecondary; wrapMode: Text.Wrap }
    Dialog {
        id: confirmation
        objectName: "memoryConfirmation"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(520, parent ? parent.width - 32 : 520)
        modal: true
        title: qsTr("Confirm memory action")
        standardButtons: Dialog.Ok | Dialog.Cancel
        Label { id: confirmationText; width: parent.width; wrapMode: Text.Wrap }
        onAccepted: root.pendingAction === "restart" ? root.bridge.resetConversation() : root.run(root.pendingAction, root.pendingParams)
    }
    Dialog {
        id: summarize
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(460, parent ? parent.width - 32 : 460)
        modal: true
        title: qsTr("Summarize recent messages")
        standardButtons: Dialog.Ok | Dialog.Cancel
        ColumnLayout {
            width: parent.width
            spacing: Theme.NCMetrics.space8
            Label {
                Layout.fillWidth: true
                text: qsTr("Summarizes the latest N messages. Older messages stay in the chat, are marked as handled, and are not summarized again.")
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.fillWidth: true
                Label { text: qsTr("Latest messages"); color: Theme.NCTheme.text; Layout.fillWidth: true }
                SpinBox {
NCHelp { target: turnCount; text: qsTr("Number of the latest messages included in this manual summary update, from 1 to 10000. Older messages stay in chat and are marked as handled rather than summarized again.") }

 id: turnCount; from: 1; to: 10000; value: 120; editable: true }
            }
        }
        onAccepted: root.run("summarize_recent", {turnCount: turnCount.value})
    }
    Dialog {
        id: search; parent: Overlay.overlay; anchors.centerIn: parent; modal: true; width: 480
        title: qsTr("Search Archive"); standardButtons: Dialog.Ok | Dialog.Cancel
        TextField {
NCHelp { target: query; text: qsTr("Words or a question to search for in the conversation archive. Search results are shown for inspection; this does not submit a chat message.") }

 id: query; width: parent.width; placeholderText: qsTr("Search memories") }
        onAccepted: root.run("search_archive", {query: query.text})
    }
    Dialog {
        id: embeddings; parent: Overlay.overlay; anchors.centerIn: parent; modal: true
        title: qsTr("Rebuild embeddings"); standardButtons: Dialog.Ok | Dialog.Cancel
        ColumnLayout {
            Label { text: qsTr("Maximum records (0 = all)") }
            SpinBox {
NCHelp { target: embeddingLimit; text: qsTr("Maximum archive records processed by this embedding rebuild. 0 processes all records. More records take longer and may require more embedding requests.") }

 id: embeddingLimit; from: 0; to: 1000000; value: 0; editable: true }
            CheckBox {
NCHelp { target: clearEmbeddings; text: qsTr("Remove existing stored embedding vectors before rebuilding them. This replaces the semantic search index; confirm only when you intend to regenerate it.") }

 id: clearEmbeddings; text: qsTr("Clear existing embeddings first"); checked: false }
        }
        onAccepted: root.confirm("rebuild_embeddings", {limit: embeddingLimit.value, clearExisting: clearEmbeddings.checked}, qsTr("Rebuild archive embeddings with these options? This may take some time."))
    }
    FileDialog { id: reportFile; title: qsTr("Export Session Memory"); fileMode: FileDialog.SaveFile; nameFilters: ["Markdown (*.md)"]; defaultSuffix: "md"; onAccepted: root.run("export_report", {path: String(selectedFile)}) }
    FileDialog { id: archiveFile; title: qsTr("Choose archive rebuild source"); fileMode: FileDialog.OpenFile; nameFilters: ["Chat context (*.json)"]; onAccepted: root.confirm("rebuild_archive", {path: String(selectedFile)}, qsTr("Build a separate inactive archive candidate from this saved context? The active archive database is left unchanged.")) }
}
