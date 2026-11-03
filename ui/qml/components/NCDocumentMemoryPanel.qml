pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "documentMemoryPanel"
    required property var bridge
    readonly property var workspace: bridge.documentMemoryWorkspace || ({})
    property string selectedSection: "Sources"
    readonly property var packageChoices: workspace.packages || []
    readonly property var sources: workspace.sources || []
    readonly property var indexing: workspace.indexing || ({})
    readonly property string indexingStage: String(indexing.stage || "")
    readonly property real indexingProgressTotal: Number(indexingStage === "splitting" ? indexing.total_chars || 0 : indexing.total || 0)
    readonly property real indexingProgressValue: Number(indexingStage === "splitting" ? indexing.processed_chars || 0 : indexing.completed || 0)
    readonly property int indexingPercent: indexingProgressTotal > 0 ? Math.min(100, Math.floor(100 * indexingProgressValue / indexingProgressTotal)) : 0
    readonly property bool indexingWaiting: Boolean(indexing.paused) || indexing.state === "paused for reply/audio" || indexing.state === "cancelled" || indexing.state === "failed"
    function indexingProgressText() {
        if (indexingStage === "preparing") return qsTr("Preparing embedding model…")
        if (indexingStage === "extracting") return qsTr("Step 1 of 4 · Extracting document text…")
        if (indexingStage === "splitting") return qsTr("Step 2 of 4 · Splitting text: %1% · %2 chunks prepared").arg(indexingPercent).arg(Number(indexing.completed || 0))
        if (indexingStage === "embedding") return qsTr("Step 3 of 4 · Embedding: %1 of %2 chunks (%3%)").arg(Number(indexing.completed || 0)).arg(Number(indexing.total || 0)).arg(indexingPercent)
        if (indexingStage === "publishing") return qsTr("Step 4 of 4 · Saving knowledge index…")
        if (indexingStage === "ready") return qsTr("Index ready")
        return qsTr("Waiting to start indexing")
    }
    readonly property var usagePresets: workspace.usagePresets || []
    property string usagePackageId: ""
    property int usagePackageRevision: 0
    property int usageActivationRevision: 0
    property string usageMode: "reference"
    property string usageGuide: ""
    property bool usageShowSources: true
    property bool usageDirty: false
    property bool usageConflict: false
    property var usageSavedSettings: ({})
    readonly property var modelControl: (workspace.controls || []).find(c => c.id === "rag_context_tab::model") || ({})
    readonly property var preprocessingControl: (workspace.controls || []).find(c => c.id === "rag_context_tab::prefix_scheme") || ({})
    readonly property var modelChoices: modelControl.options || []
    readonly property var preprocessingChoices: preprocessingControl.options || []
    readonly property int embeddingModelIndex: modelChoices.findIndex(c => c.value === embeddingDraft.model)
    readonly property int preprocessingIndex: preprocessingChoices.findIndex(c => c.value === embeddingDraft.prefix_scheme)
    property var embeddingDraft: ({})
    property var embeddingSaved: ({})
    property var embeddingSubmitted: ({})
    property string embeddingPackageId: ""
    property int embeddingActivation: 0
    property int embeddingSession: 0
    property bool embeddingConflict: false
    readonly property bool embeddingDirty: JSON.stringify(embeddingDraft) !== JSON.stringify(embeddingSaved)
    property var modelWarningScope: ({})
    property var embeddingChange: ({})
    spacing: Theme.NCMetrics.space12

    function syncUsageDraft(forceReload) {
        const packageId = String(workspace.activePackageId || "")
        const activation = Number(workspace.revision || 0)
        const settings = workspace.settings || {}
        const saved = {usage_mode: String(settings.usage_mode || "reference"),
                       prompt_guide: String(settings.prompt_guide || ""),
                       show_sources: settings.show_sources !== false}
        if (!forceReload && usageDirty && packageId === usagePackageId && activation === usageActivationRevision) {
            usageConflict = saved.usage_mode !== usageSavedSettings.usage_mode
                         || saved.prompt_guide !== usageSavedSettings.prompt_guide
                         || saved.show_sources !== usageSavedSettings.show_sources
            // An index publication changes package revision, but not saved usage.
            if (!usageConflict)
                usagePackageRevision = Number(workspace.package_revision || 0)
            return
        }
        usagePackageId = packageId
        usagePackageRevision = Number(workspace.package_revision || 0)
        usageActivationRevision = activation
        usageSavedSettings = saved
        usageMode = saved.usage_mode
        usageGuide = saved.prompt_guide
        usageShowSources = saved.show_sources
        usageDirty = false
        usageConflict = false
    }
    function chooseUsagePreset(index) {
        const preset = usagePresets[index]
        if (!preset) return
        usageMode = String(preset.id)
        usageGuide = String(preset.prompt_guide)
        usageShowSources = Boolean(preset.show_sources)
        usageDirty = true
    }
    function saveUsage() {
        if (!usageDirty || usageConflict) return
        command("runtime.rag.settings.update", {
            changes: {usage_mode: usageMode, prompt_guide: usageGuide, show_sources: usageShowSources},
            package_id: usagePackageId, expected_revision: usagePackageRevision,
            _expected_package_id: usagePackageId, _expected_activation_revision: usageActivationRevision
        })
    }
    function savedEmbedding() {
        const s = workspace.settings || {}
        return {base_url: String(s.base_url || "http://127.0.0.1:1234/v1"), model: String(s.model || ""),
            context_tokens: Number(s.context_tokens || 8192), prefix_scheme: String(s.prefix_scheme || "bge-m3"),
            chunk_prefix: s.chunk_prefix == null ? (s.prefix_scheme === "nomic" ? "search_document: " : "") : String(s.chunk_prefix),
            query_prefix: s.query_prefix == null ? (s.prefix_scheme === "nomic" ? "search_query: " : "") : String(s.query_prefix),
            chunk_size_tokens: s.chunk_size_tokens == null ? null : Number(s.chunk_size_tokens),
            chunk_overlap_tokens: s.chunk_overlap_tokens == null ? null : Number(s.chunk_overlap_tokens)}
    }
    function syncEmbeddingDraft(force) {
        const saved = savedEmbedding()
        const packageId = String(workspace.activePackageId || "")
        const activation = Number(workspace.revision || 0)
        if (embeddingSubmitted.package_id === packageId
                && embeddingSubmitted.session === Number(workspace.session_generation || 0)
                && JSON.stringify(saved) === JSON.stringify(embeddingSubmitted.changes)) {
            // Acknowledge our save while preserving edits made during the command.
            embeddingSaved = saved
            embeddingSubmitted = ({})
        }
        if (!force && embeddingDirty && packageId === embeddingPackageId && Number(workspace.session_generation || 0) === embeddingSession) {
            embeddingConflict = JSON.stringify(saved) !== JSON.stringify(embeddingSaved)
            embeddingActivation = activation
            return
        }
        embeddingPackageId = packageId
        embeddingActivation = activation
        embeddingSession = Number(workspace.session_generation || 0)
        embeddingSaved = saved
        embeddingDraft = Object.assign({}, saved)
        if (embeddingDraft.chunk_size_tokens == null)
            embeddingDraft = Object.assign({}, embeddingDraft, {chunk_size_tokens: Math.min(512, saved.context_tokens-64), chunk_overlap_tokens: 50})
        embeddingConflict = false
        embeddingSubmitted = ({})
    }
    function editEmbedding(key, value) {
        const draft = Object.assign({}, embeddingDraft)
        draft[key] = value
        if (key === "prefix_scheme" && value !== "custom") {
            draft.chunk_prefix = value === "nomic" ? "search_document: " : ""
            draft.query_prefix = value === "nomic" ? "search_query: " : value === "qwen3"
                ? "Instruct: Given a question, retrieve relevant passages that answer the question\nQuery: " : ""
        }
        embeddingDraft = draft
    }
    function requestEmbeddingChange() {
        if (!embeddingPackageId || !embeddingDirty || embeddingConflict) return
        const selectedPackage = packageChoices.find(p => p.id === workspace.activePackageId)
        embeddingChange = {changes: Object.assign({}, embeddingDraft), package_id: workspace.activePackageId,
            package_name: selectedPackage ? selectedPackage.name : workspace.activePackageId,
            expected_revision: Number(workspace.package_revision || 0),
            activation_revision: Number(workspace.revision || 0),
            old_model: embeddingSaved.model, baseline: JSON.stringify(embeddingSaved)}
        modelChangeDialog.open()
    }
    function syncEmbeddingConfirmation() {
        const pending = embeddingChange
        if (!pending.package_id) return
        if (pending.package_id !== workspace.activePackageId
                || pending.activation_revision !== Number(workspace.revision || 0)
                || pending.baseline !== JSON.stringify(savedEmbedding())
                || (pending.changes.model && !modelChoices.some(c => c.value === pending.changes.model))) {
            modelChangeDialog.reject()
            return
        }
        // Publication can advance this revision while the confirmation is open.
        if (pending.expected_revision !== Number(workspace.package_revision || 0))
            embeddingChange = Object.assign({}, pending, {expected_revision: Number(workspace.package_revision || 0)})
    }
    function embeddingChangeDescription() {
        const pending = embeddingChange
        if (!pending.package_id) return ""
        const model = String(pending.changes.model || pending.old_model)
        return qsTr("Package “%1” uses one embedding model.\n\nCurrent model: %2\nNew model: %3\nChunk size: %4 tokens · Overlap: %5 tokens\n\nApply the model, server, context, prefixes and chunk settings together? Changed settings require re-splitting and re-indexing saved snapshots. Processing runs only while NC is idle. Disabled sources are processed when enabled. Unchanged settings keep their existing index.")
            .arg(pending.package_name).arg(pending.old_model).arg(model).arg(pending.changes.chunk_size_tokens).arg(pending.changes.chunk_overlap_tokens)
    }
    function confirmEmbeddingChange() {
        syncEmbeddingConfirmation()
        const pending = embeddingChange
        if (!pending.package_id) return
        embeddingChange = ({})
        embeddingSubmitted = {package_id: pending.package_id, session: embeddingSession,
                              changes: pending.changes}
        command("runtime.rag.settings.update", {changes: pending.changes,
            package_id: pending.package_id, expected_revision: pending.expected_revision,
            _expected_package_id: pending.package_id, _expected_activation_revision: pending.activation_revision})
    }
    function syncModelWarning() {
        const status = workspace.modelAvailability || {}
        if (status.state !== "missing" && status.state !== "unavailable") {
            modelWarning.close()
            modelWarningScope = ({})
            return
        }
        modelWarningScope = {package_id: workspace.activePackageId, activation: Number(workspace.revision || 0),
                             message: String(status.message || ""), state: status.state}
        if (root.Window.window && !modelWarning.visible) modelWarning.open()
    }
    function resolveModelWarning(action) {
        const pending = modelWarningScope
        if (!pending.package_id) return
        command("runtime.rag.packages." + action, {_expected_package_id: pending.package_id,
            _expected_activation_revision: pending.activation})
    }
    onWorkspaceChanged: { syncUsageDraft(); syncEmbeddingDraft(); syncEmbeddingConfirmation(); syncModelWarning() }
    onModelChoicesChanged: syncEmbeddingConfirmation()
    Component.onCompleted: { syncUsageDraft(); syncEmbeddingDraft(); syncModelWarning() }
    Window.onWindowChanged: syncModelWarning()

    function command(capability, payload) { bridge.documentMemoryCommand(capability, payload || {}) }
    function setting(key, value) {
        const changes = {}; changes[key] = value
        command("runtime.rag.settings.update", { changes: changes,
            package_id: workspace.activePackageId, expected_revision: workspace.package_revision })
    }

    NCCard {
        Layout.fillWidth: true
        title: qsTr("Document Memory")
        description: qsTr("Reusable local knowledge packages. Switching uses saved snapshots; source files refresh only when you request it.")
        RowLayout {
            Layout.fillWidth: true
            NCComboBox {
                toolTipText: qsTr("Choose the knowledge package used by Document Memory. Each package keeps its own documents, search index, and presentation settings.")

                id: packages
                objectName: "documentMemoryPackageSelector"
                Layout.fillWidth: true
                label: qsTr("Active knowledge package")
                model: root.packageChoices
                textRole: "name"
                valueRole: "id"
                currentIndex: root.packageChoices.findIndex(p => p.id === root.workspace.activePackageId)
                onActivated: root.bridge.selectDocumentMemoryPackage(String(currentValue))
            }
            NCButton {
                objectName: "documentMemoryNewPackage"
                text: qsTr("New package")
                onClicked: { packageName.text = ""; createDialog.open() }
            }
        }
        Label {
            Layout.fillWidth: true
            text: String(root.workspace.status || qsTr("Loading package library…"))
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
    }
    Flow {
        objectName: "documentMemoryTabBar"
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space6
        Repeater {
            model: ["Sources", "Usage", "Retrieval", "Index", "Test search"]
            delegate: NCTabButton {
                required property string modelData
                objectName: "documentMemoryTab_" + modelData.replace(/\s+/g, "_")
                tutorialBridge: root.bridge
                tutorialContext: ({workspace: "runtime", runtime_section: "memory", document_section: modelData})
                text: modelData
                checked: root.selectedSection === modelData
                onClicked: root.selectedSection = modelData
            }
        }
    }
    NCCard {
        Layout.fillWidth: true
        visible: root.selectedSection === "Usage"
        enabled: root.usagePackageId.length > 0
        title: qsTr("How knowledge is used")
        description: qsTr("Choose a starting prompt, then customize it. The guide and source visibility are saved with this knowledge package.")
        Label {
            text: qsTr("Starting prompt")
            color: Theme.NCTheme.textSecondary
        }
        NCComboBox {
            toolTipText: qsTr("Choose how retrieved passages are introduced to the language model. Manual lets you edit the guide below. Save the presentation changes for this package.")

            objectName: "documentMemoryUsagePreset"
            Layout.fillWidth: true
            label: qsTr("Knowledge presentation")
            model: root.usagePresets
            textRole: "name"
            valueRole: "id"
            currentIndex: root.usagePresets.findIndex(p => p.id === root.usageMode)
            onActivated: index => root.chooseUsagePreset(index)
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("Selecting a starting prompt replaces the guide and source visibility below. You can edit either before saving.")
            color: Theme.NCTheme.textMuted
            wrapMode: Text.Wrap
        }
        Label {
            text: qsTr("Memory prompt guide")
            color: Theme.NCTheme.textSecondary
        }
        NCTextArea {
            toolTipText: qsTr("Instructions placed around this package's retrieved knowledge when it is sent to the language model. Editing this does not alter the documents or search index; save to apply.")

            objectName: "documentMemoryPromptGuide"
            Layout.fillWidth: true
            Layout.preferredHeight: 160
            label: qsTr("Memory prompt guide")
            text: root.usageGuide
            onTextChanged: {
                if (text !== root.usageGuide) {
                    root.usageGuide = text
                    root.usageDirty = true
                }
            }
        }
        NCCheckBox {
            toolTipText: qsTr("Include source document information with retrieved passages so the AI can refer to their origins. Save this presentation choice for the selected package.")

            objectName: "documentMemoryShowSources"
            Layout.fillWidth: true
            text: qsTr("Tell the AI which documents this knowledge came from")
            checked: root.usageShowSources
            onToggled: { root.usageShowSources = checked; root.usageDirty = true }
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("When off, filenames, page and chunk labels, and the package name are hidden from the AI. Source names remain available in Test search diagnostics. This does not remove names written inside the recalled text itself.")
            color: Theme.NCTheme.textMuted
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            NCButton {
                objectName: "documentMemorySaveUsage"
                text: qsTr("Save usage settings")
                enabled: root.usageDirty && !root.usageConflict && root.usageGuide.length <= 2000
                onClicked: root.saveUsage()
            }
            NCButton {
                objectName: "documentMemoryReloadUsage"
                text: qsTr("Reload saved usage")
                visible: root.usageConflict
                onClicked: root.syncUsageDraft(true)
            }
            Label {
                Layout.fillWidth: true
                text: root.usageConflict ? qsTr("Saved usage changed. Reload before saving your edits.")
                      : root.usageGuide.length > 2000 ? qsTr("The guide can contain up to 2,000 characters.")
                      : root.usageDirty ? qsTr("Unsaved changes") : qsTr("Saved with this package")
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
        }
    }
    Label {
        Layout.fillWidth: true
        visible: String(root.workspace.error || "").length > 0
        text: String(root.workspace.error || "")
        color: Theme.NCTheme.error
        wrapMode: Text.Wrap
        Accessible.role: Accessible.AlertMessage
    }
    NCCard {
        Layout.fillWidth: true
        visible: root.selectedSection === "Sources"
        enabled: Boolean(root.workspace.activePackageId) && (!root.workspace.modelAvailability || root.workspace.modelAvailability.state === "ready")
        title: qsTr("Document sources")
        NCSwitch {
            toolTipText: qsTr("Allow retrieved knowledge from the selected package to enter chat requests. Turning this off keeps the package and its indexed documents.")

            objectName: "documentMemoryEnabled"
            text: qsTr("Use Document Memory in chat")
            checked: Boolean((root.workspace.settings || {}).enabled)
            onToggled: root.setting("enabled", checked)
        }
        Flow {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space6
            NCButton { text: qsTr("Add files"); onClicked: {
                fileDialog.packageId = String(root.workspace.activePackageId || "")
                fileDialog.activationRevision = Number(root.workspace.revision || 0)
                fileDialog.open()
            } }
            NCButton {
                text: qsTr("Refresh from sources")
                enabled: root.sources.length > 0
                onClicked: root.bridge.refreshDocumentMemorySources(root.sources.filter(s => s.enabled).map(s => s.id))
            }
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("Enabled chooses what can be recalled. Indexed shows whether the saved snapshot has compatible embeddings.")
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        Repeater {
            model: root.sources
            delegate: NCCard {
                id: sourceRow
                required property var modelData
                Layout.fillWidth: true
                flat: true
                title: String(modelData.title || modelData.path)
                RowLayout {
                    Layout.fillWidth: true
                    NCCheckBox {
                        toolTipText: qsTr("Allow this document to contribute knowledge from the selected package. Disabling it keeps the original file and excludes its passages from retrieval.")

                        objectName: "documentSourceEnabled_" + sourceRow.modelData.id
                        text: qsTr("Enabled")
                        checked: Boolean(sourceRow.modelData.enabled)
                        Accessible.name: qsTr("Include %1 in knowledge package").arg(sourceRow.modelData.title)
                        onToggled: root.bridge.setDocumentMemorySourceEnabled(sourceRow.modelData.id, checked)
                    }
                    NCCheckBox {
                        toolTipText: qsTr("Shows whether this document has been processed into the package's search index. This is a status indicator, not an editable switch.")

                        objectName: "documentSourceIndexed_" + sourceRow.modelData.id
                        text: qsTr("Indexed")
                        checked: Boolean(sourceRow.modelData.indexed)
                        enabled: false
                        Accessible.name: qsTr("Saved snapshot indexed: %1; read-only").arg(sourceRow.modelData.title)
                    }
                    Label {
                        Layout.fillWidth: true
                        text: String(sourceRow.modelData.state || "")
                        color: Theme.NCTheme.textSecondary
                        wrapMode: Text.Wrap
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: String(sourceRow.modelData.path) + "\n" + (sourceRow.modelData.saved_at ? qsTr("Saved snapshot: ") + sourceRow.modelData.saved_at : qsTr("Waiting for its first saved snapshot"))
                    color: Theme.NCTheme.textMuted
                    wrapMode: Text.WrapAnywhere
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space6
                    NCButton { text: qsTr("Refresh / Retry"); compact: true; onClicked: root.bridge.refreshDocumentMemorySources([sourceRow.modelData.id]) }
                    NCButton { text: qsTr("Remove"); tone: "danger"; compact: true; onClicked: root.command("runtime.rag.remove_files", { paths: [sourceRow.modelData.path] }) }
                }
            }
        }
        Label {
            visible: root.sources.length === 0
            text: qsTr("This package has no documents yet.")
            color: Theme.NCTheme.textSecondary
        }
    }
    NCCard {
        Layout.fillWidth: true
        visible: root.selectedSection === "Index"
        enabled: Boolean(root.workspace.activePackageId) && (!root.workspace.modelAvailability || root.workspace.modelAvailability.state === "ready")
        title: qsTr("Background indexing")
        description: qsTr("Indexing waits until replies, recording, speech, and queued audio have finished. Refresh reads original files; rebuild uses saved text.")
        Label {
            Layout.fillWidth: true
            text: String(root.indexing.state || "idle") + (root.indexing.busy_reason ? " — " + root.indexing.busy_reason : "")
            color: Theme.NCTheme.text
            wrapMode: Text.Wrap
        }
        ProgressBar {
            objectName: "documentMemoryIndexingProgress"
            Layout.fillWidth: true
            palette.dark: Theme.NCTheme.accent
            palette.midlight: Theme.NCTheme.surfaceRaised
            from: 0; to: Math.max(1, root.indexingProgressTotal)
            value: root.indexingStage === "ready" ? to : root.indexingProgressValue
            indeterminate: !root.indexingWaiting && ["preparing", "extracting", "publishing"].indexOf(root.indexingStage) >= 0
        }
        Label {
            objectName: "documentMemoryIndexingProgressText"
            Layout.fillWidth: true
            text: root.indexingProgressText()
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        Flow {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space6
            NCButton { text: root.indexing.paused ? qsTr("Resume indexing") : qsTr("Pause indexing"); onClicked: root.command("runtime.rag.index.pause", {paused: !root.indexing.paused}) }
            NCButton { text: qsTr("Refresh from sources"); onClicked: root.bridge.refreshDocumentMemorySources(root.sources.filter(s => s.enabled).map(s => s.id)) }
            NCButton { text: qsTr("Rebuild saved embeddings"); onClicked: root.command("runtime.rag.index.rebuild", {}) }
        }
    }
    NCCard {
        Layout.fillWidth: true
        visible: root.selectedSection === "Retrieval"
        enabled: Boolean(root.workspace.activePackageId)
        title: qsTr("Embedding model for this package")
        description: qsTr("Edit all settings first, then Apply changes. The saved settings remain in use until you confirm. Each package uses the same model and prefixes for indexing and search.")
        Label { text: qsTr("Semantic search model"); color: Theme.NCTheme.textSecondary }
        NCComboBox {
            toolTipText: qsTr("Choose the local model that converts text into searchable vectors for this knowledge package. Model changes require rebuilding the index before matching documents and queries.")

            id: embeddingModel
            objectName: "documentMemoryEmbeddingModel"
            Layout.fillWidth: true
            label: qsTr("Semantic search model")
            model: root.modelChoices
            textRole: "label"
            valueRole: "value"
            currentIndex: root.embeddingModelIndex
            onActivated: index => {
                root.editEmbedding("model", String(root.modelChoices[index].value))
                currentIndex = Qt.binding(function() { return root.embeddingModelIndex })
            }
        }
        Label { text: qsTr("Model preprocessing"); color: Theme.NCTheme.textSecondary }
        NCComboBox {
            toolTipText: qsTr("Choose how text is prepared for the embedding model. Use the model's recommended prefixes, or choose Custom and supply document and query prefixes. Save and reindex after changes.")

            objectName: "documentMemoryPreprocessing"
            Layout.fillWidth: true
            label: qsTr("Model preprocessing")
            model: root.preprocessingChoices
            textRole: "label"
            valueRole: "value"
            currentIndex: root.preprocessingIndex
            onActivated: index => {
                root.editEmbedding("prefix_scheme", String(root.preprocessingChoices[index].value))
                currentIndex = Qt.binding(function() { return root.preprocessingIndex })
            }
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("Presets fill the prefix fields below. You can edit either prefix for any model. Spaces and line breaks are sent exactly as entered; an empty prefix sends plain text.")
            color: Theme.NCTheme.textMuted
            wrapMode: Text.Wrap
        }
        Label { text: qsTr("Document chunk prefix"); color: Theme.NCTheme.textSecondary }
        NCTextArea {
            toolTipText: qsTr("Text prepended to each document chunk before embedding. Use the format required by the chosen model. Changes require reindexing the package.")

            objectName: "documentMemoryChunkPrefix"
            Layout.fillWidth: true
            Layout.preferredHeight: 80
            label: qsTr("Document chunk prefix")
            text: String(root.embeddingDraft.chunk_prefix || "")
            onTextChanged: if (text !== root.embeddingDraft.chunk_prefix) root.editEmbedding("chunk_prefix", text)
        }
        Label { text: qsTr("Search query prefix"); color: Theme.NCTheme.textSecondary }
        NCTextArea {
            toolTipText: qsTr("Text prepended to your search query before embedding. It should match the embedding model's expected query format.")

            objectName: "documentMemoryQueryPrefix"
            Layout.fillWidth: true
            Layout.preferredHeight: 100
            label: qsTr("Search query prefix")
            text: String(root.embeddingDraft.query_prefix || "")
            onTextChanged: if (text !== root.embeddingDraft.query_prefix) root.editEmbedding("query_prefix", text)
        }
        Label { text: qsTr("Local embedding server"); color: Theme.NCTheme.textSecondary }
        NCTextField {
            toolTipText: qsTr("Address of the local server providing this package's embedding model. This is the search-model connection, separate from the chat-model connection.")

            objectName: "documentMemoryEmbeddingServer"
            Layout.fillWidth: true
            label: qsTr("Local embedding server")
            text: String(root.embeddingDraft.base_url || "")
            onTextEdited: root.editEmbedding("base_url", text)
        }
        Label { text: qsTr("Embedding model context (tokens)"); color: Theme.NCTheme.textSecondary }
        NCTextField {
            toolTipText: qsTr("Embedding model input capacity in tokens. Use a value supported by the selected model and server; it bounds the text sent for each embedding request.")

            objectName: "documentMemoryEmbeddingContext"
            Layout.fillWidth: true
            label: qsTr("Embedding model context")
            text: String(root.embeddingDraft.context_tokens || 8192)
            validator: IntValidator { bottom: 256; top: 32768 }
            onTextEdited: if (acceptableInput) root.editEmbedding("context_tokens", Number(text))
        }
        Label { text: qsTr("Target chunk size (tokens)"); color: Theme.NCTheme.textSecondary }
        NCTextField {
            toolTipText: qsTr("Target document chunk length in embedding-model tokens. Smaller chunks give more focused matches; larger chunks retain more surrounding text. Save and reindex to apply.")

            id: chunkSizeTokens
            objectName: "documentMemoryChunkSizeTokens"
            Layout.fillWidth: true
            label: qsTr("Target chunk size in embedding model tokens")
            errorText: acceptableInput ? "" : qsTr("Enter a whole number from 64 up to the available model context.")
            text: String(root.embeddingDraft.chunk_size_tokens == null ? 512 : root.embeddingDraft.chunk_size_tokens)
            validator: IntValidator { bottom: 64; top: Math.min(32768, Number(root.embeddingDraft.context_tokens || 8192)-64) }
            onTextEdited: if (acceptableInput) root.editEmbedding("chunk_size_tokens", Number(text))
        }
        Label { text: qsTr("Chunk overlap (tokens)"); color: Theme.NCTheme.textSecondary }
        NCTextField {
            toolTipText: qsTr("Tokens repeated between neighboring document chunks to preserve context across boundaries. Must be smaller than the target chunk size. Save and reindex to apply.")

            id: chunkOverlapTokens
            objectName: "documentMemoryChunkOverlapTokens"
            Layout.fillWidth: true
            label: qsTr("Chunk overlap in embedding model tokens")
            errorText: acceptableInput ? "" : qsTr("Overlap must be a whole number smaller than the chunk size; zero is allowed.")
            text: String(root.embeddingDraft.chunk_overlap_tokens == null ? 50 : root.embeddingDraft.chunk_overlap_tokens)
            validator: IntValidator { bottom: 0; top: Math.max(0, Number(root.embeddingDraft.chunk_size_tokens || 512)-1) }
            onTextEdited: if (acceptableInput) root.editEmbedding("chunk_overlap_tokens", Number(text))
        }
        NCButton {
            objectName: "documentMemoryDefaultChunking"
            text: qsTr("Use general chunk defaults")
            onClicked: {
                root.editEmbedding("chunk_size_tokens", Math.min(512,Number(root.embeddingDraft.context_tokens || 8192)-64))
                root.editEmbedding("chunk_overlap_tokens",50)
            }
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("General defaults: 512 tokens with 50 tokens overlap. Counts use the selected embedding model’s tokenizer during idle processing. Paragraph/sentence boundaries can make chunks shorter; overlap stays within each page or section. Prefix space is reserved automatically.")
            color: Theme.NCTheme.textMuted
            wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            visible: (root.workspace.settings || {}).chunk_size_tokens == null
            text: qsTr("This package uses the previous character-based splitting. Apply the suggested token settings to rebuild its saved snapshots; its current index remains usable until then.")
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        Flow {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space6
            NCButton {
                objectName: "documentMemoryApplyEmbedding"
                text: qsTr("Apply changes…")
                enabled: root.embeddingDirty && !root.embeddingConflict && chunkSizeTokens.acceptableInput && chunkOverlapTokens.acceptableInput
                onClicked: root.requestEmbeddingChange()
            }
            NCButton {
                objectName: "documentMemoryRevertEmbedding"
                text: qsTr("Revert edits")
                enabled: root.embeddingDirty || root.embeddingConflict
                onClicked: root.syncEmbeddingDraft(true)
            }
        }
        Label {
            Layout.fillWidth: true
            text: root.embeddingConflict ? qsTr("Saved embedding settings changed. Revert edits before applying.")
                  : root.embeddingDirty ? qsTr("Unsaved changes — the current index is still in use.") : qsTr("Saved with this package")
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
    }
    NCLiveControlsGroup {
        objectName: "documentMemorySelectedSection"
        Layout.fillWidth: true
        visible: root.selectedSection === "Retrieval" || root.selectedSection === "Test search"
        enabled: Boolean(root.workspace.activePackageId)
        title: root.selectedSection
        controls: (root.workspace.controls || []).filter(c => c.section === root.selectedSection
            && !["model", "prefix_scheme", "base_url", "context_tokens"].some(k => c.id === "rag_context_tab::" + k))
        onControlEdited: (controlId, value) => root.bridge.setRuntimeProviderControl(controlId, value)
        onActionTriggered: controlId => root.bridge.triggerRuntimeProviderActionWithPayload(controlId, {})
        onActionWithPayload: (controlId, payload) => root.bridge.triggerRuntimeProviderActionWithPayload(controlId, payload)
        onRefreshRequested: root.bridge.refreshDocumentMemory()
    }
    FileDialog {
        id: fileDialog
        property string packageId: ""
        property int activationRevision: 0
        fileMode: FileDialog.OpenFiles
        title: qsTr("Add documents to this knowledge package")
        nameFilters: [qsTr("Documents (*.txt *.md *.markdown *.json *.log *.pdf)")]
        onAccepted: {
            root.bridge.triggerRuntimeProviderActionWithPayload("rag_context_tab::rag_context_add_files", {paths: selectedFiles.map(f => String(f)),
                _expected_package_id: packageId, _expected_activation_revision: activationRevision})
            addNotice.open()
        }
    }
    NCDialog {
        id: modelChangeDialog
        objectName: "documentMemoryModelChangeDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Re-index this knowledge package?")
        description: root.embeddingChangeDescription()
        acceptText: qsTr("Apply and re-index")
        rejectText: qsTr("Cancel")
        acceptEnabled: Boolean(root.embeddingChange.package_id)
        onAccepted: root.confirmEmbeddingChange()
        onRejected: root.embeddingChange = ({})
    }
    NCDialog {
        id: modelWarning
        objectName: "documentMemoryMissingModelDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: root.modelWarningScope.state === "missing" ? qsTr("Package embedding model is missing") : qsTr("Cannot check package embedding model")
        description: String(root.modelWarningScope.message || "")
        acceptText: qsTr("Retry")
        rejectText: qsTr("Cancel package loading")
        onAccepted: root.resolveModelWarning("retry")
        onRejected: root.resolveModelWarning("cancel")
    }
    NCDialog {
        id: createDialog
        objectName: "documentMemoryCreateDialog"
        parent: Overlay.overlay
        title: qsTr("New knowledge package")
        description: qsTr("Choose a unique name. Its permanent UUID is managed automatically.")
        acceptText: qsTr("Create package")
        acceptEnabled: packageName.text.trim().length > 0 && packageName.text.trim().length <= 80
        NCTextField {
            toolTipText: qsTr("Name for a new knowledge package. Documents and search settings belong to that package; use a name that helps you recognize its contents.")
 id: packageName; objectName: "documentMemoryPackageName"; width: parent.width; label: qsTr("Package name"); placeholderText: qsTr("e.g. x64 Assembler"); maximumLength: 80 }
        onAccepted: root.bridge.createDocumentMemoryPackage(packageName.text.trim())
    }
    NCDialog {
        id: addNotice
        objectName: "documentMemoryAddNotice"
        parent: Overlay.overlay
        title: qsTr("Documents queued")
        description: qsTr("Documents added. They will be indexed locally when NC is waiting for input and has finished replying and speaking. Until then, they are not used in replies.")
        acceptText: qsTr("Got it")
        rejectText: ""
    }
}
