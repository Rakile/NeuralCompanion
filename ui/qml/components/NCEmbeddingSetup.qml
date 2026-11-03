pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    objectName: "providerEmbeddingSetup"
    required property var bridge
    readonly property var controller: bridge.embeddingSetup
    readonly property var state: controller.state
    property bool advancedExpanded: false
    title: qsTr("Memory search model")
    description: qsTr("Finds relevant details in older conversations.")
    function selectProvider() { controller.viewProvider(String(bridge.viewedProviderId || "lmstudio")) }
    Component.onCompleted: selectProvider()
    Connections { target: root.bridge; function onProviderViewChanged() { root.selectProvider() } }

    NCStatusChip {
        visible: Boolean(root.state.selected) && Boolean(root.state.enabled)
        text: qsTr("Used for memory search")
        status: "active"
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: Boolean(root.state.supported)
        spacing: Theme.NCMetrics.space10
        Label { text: qsTr("Embedding model"); color: Theme.NCTheme.textSecondary }
        RowLayout {
            Layout.fillWidth: true
            NCTextField {
                toolTipText: qsTr("Installed model used to turn archived conversation text into vectors for semantic search. Choose a model supported by your current embedding provider. Save and rebuild the index after changing it.")

                id: modelEditor
                objectName: "embeddingModelEditor"
                Layout.fillWidth: true
                text: String(root.state.model || "")
                label: qsTr("Embedding model")
                placeholderText: qsTr("Refresh and choose, or enter an installed model name")
                enabled: !root.state.busy
                onEditingFinished: root.controller.setDraft("model", text)
            }
            NCButton { objectName: "refreshEmbeddingModels"; text: qsTr("Refresh"); busy: Boolean(root.state.busy); enabled: !root.state.busy; onClicked: root.controller.refreshModels() }
        }
        NCComboBox {
            toolTipText: qsTr("Select an embedding model reported by the current server. This changes the search model draft, not the language model used for chat replies.")

            objectName: "embeddingModelChoices"
            Layout.fillWidth: true
            visible: (root.state.models || []).length > 0
            model: root.state.models || []
            label: qsTr("Available embedding models")
            displayText: qsTr("Choose an available embedding model")
            onActivated: root.controller.setDraft("model", currentText)
        }
        Label {
            Layout.fillWidth: true
            text: root.state.provider === "openai" ? qsTr("Suggested: text-embedding-3-small")
                  : root.state.provider === "ollama" ? qsTr("Suggested: EmbeddingGemma") : qsTr("Suggested: BGE-M3 · Multilingual search")
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            text: root.state.provider === "openai"
                  ? qsTr("Text is sent to OpenAI for indexing and search. API usage charges apply. Uses the API key above.")
                  : qsTr("Uses this provider's search server. Keep a local server address to run on your computer.")
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        Flow {
            Layout.fillWidth: true
            spacing: 8
            enabled: !root.state.busy
            NCButton {
                objectName: "testEmbeddingConnection"
                text: qsTr("Test memory search")
                onClicked: { root.controller.setDraft("model", modelEditor.text); root.controller.testConnection() }
            }
            NCButton {
                objectName: "useEmbeddingProvider"
                text: qsTr("Use for memory search")
                tone: "primary"
                visible: !root.state.selected || !root.state.enabled
                onClicked: {
                    root.controller.setDraft("model", modelEditor.text)
                    confirmSelection.open()
                }
            }
            NCButton { text: qsTr("Setup instructions"); onClicked: instructions.open() }
        }
        NCInlineMessage {
            Layout.fillWidth: true
            visible: Boolean(root.state.error) || Boolean(root.state.feedback)
            tone: root.state.error ? "error" : "info"
            title: root.state.error ? qsTr("Memory search needs attention") : qsTr("Memory search")
            message: String(root.state.error || root.state.feedback || "")
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("Your memory-search provider stays selected when you change your chat provider.")
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        NCButton {
            objectName: "rebuildMemorySearchIndex"
            visible: Boolean(root.state.selected) && Boolean(root.bridge.memoryWorkspace.state.searchNeedsAttention)
            enabled: !root.bridge.memoryWorkspace.state.busy
            text: qsTr("Rebuild search index…")
            onClicked: rebuildConfirmation.open()
        }
        NCButton {
            text: root.advancedExpanded ? qsTr("▾ Advanced search settings") : qsTr("▸ Advanced search settings")
            tone: "quiet"
            onClicked: root.advancedExpanded = !root.advancedExpanded
        }
        ColumnLayout {
            Layout.fillWidth: true
            visible: root.advancedExpanded
            enabled: !root.state.busy
            Label { text: qsTr("Search server address"); color: Theme.NCTheme.textSecondary }
            NCTextField {
                toolTipText: qsTr("Server address for the conversation archive's embedding requests. Use the address of your running local embedding server and save the draft to apply.")
 Layout.fillWidth: true; text: String(root.state.baseUrl || ""); onEditingFinished: root.controller.setDraft("baseUrl", text) }
            Label { text: qsTr("Search model context (tokens)"); color: Theme.NCTheme.textSecondary }
            NCSpinBox {
                toolTipText: qsTr("Token capacity requested for the search model. Larger contexts may require more memory. Use a value the model and server support; save and rebuild the index after changing it.")
 Layout.fillWidth: true; from: 512; to: 262144; stepSize: 512; value: Number(root.state.contextLength || 8192); onValueModified: root.controller.setDraft("contextLength", value) }
            Label { text: qsTr("Minimum similarity score"); color: Theme.NCTheme.textSecondary }
            NCNumberField {
                toolTipText: qsTr("Minimum similarity for an archived memory to qualify as a semantic match, from 0 to 1. Higher values return fewer, closer matches; lower values admit broader matches.")

                Layout.fillWidth: true
                text: String(root.bridge.coreSettings.long_term_memory_embedding_min_score ?? 0.25)
                minimum: 0; maximum: 1; stepSize: 0.01
                onEditingFinished: if (acceptableInput) root.bridge.setCoreSetting("long_term_memory_embedding_min_score", Number(text))
            }
            NCButton { text: qsTr("Use basic keyword search instead"); visible: Boolean(root.state.enabled); onClicked: root.controller.setEnabled(false) }
        }
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: !root.state.supported
        Label { Layout.fillWidth: true; text: qsTr("This provider is available for chat. Choose LM Studio, Ollama or OpenAI for memory search."); color: Theme.NCTheme.textSecondary; wrapMode: Text.Wrap }
        NCButton { text: qsTr("Choose a search provider…"); onClicked: root.bridge.openMemorySearchSetup() }
    }
    NCButton { text: qsTr("Back to Memory"); onClicked: root.bridge.openConversationMemory() }
    NCDialog {
        id: rebuildConfirmation
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Rebuild this conversation’s search index?")
        description: qsTr("NC will replace the search index using your selected model. Stored messages are kept. This can take a while. For OpenAI, text is sent to the API and usage charges apply.")
        acceptText: qsTr("Rebuild index")
        onAccepted: root.bridge.memoryWorkspace.runAction("rebuild_embeddings", {limit: 0, clearExisting: true})
    }
    NCDialog {
        id: confirmSelection
        objectName: "embeddingSelectionConfirmation"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Use this model for memory search?")
        description: root.state.provider === "openai"
                     ? qsTr("NC will send text to OpenAI when indexing and searching memories. API usage charges apply. Existing chats may need their search index rebuilt; stored messages are kept.")
                     : qsTr("This changes only memory search. Existing chats may need their search index rebuilt; stored messages are kept.")
        acceptText: qsTr("Use model")
        onAccepted: root.controller.activate()
    }
    NCDialog {
        id: instructions
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Set up memory search")
        acceptText: qsTr("Close")
        rejectText: ""
        description: root.state.provider === "openai"
                     ? qsTr("Add your OpenAI API key in Model and connection. Choose text-embedding-3-small, test memory search, then select Use for memory search.")
                     : root.state.provider === "ollama"
                       ? qsTr("Install EmbeddingGemma in Ollama (ollama pull embeddinggemma), and leave Ollama running. Refresh here, choose the installed model, test it, then select Use for memory search.")
                       : qsTr("Download a BGE-M3 embedding model in LM Studio and enable its local server. Refresh here, choose the installed model, test it, then select Use for memory search. You can also load the model in LM Studio if automatic loading is unavailable.")
    }
}
