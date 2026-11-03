pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    required property var bridge
    property string personaId: ""
    property string section: "all" // Other hosts retain the combined editor.
    property string conversationLabel: qsTr("Main chat default")
    property string inheritedSourceLabel: qsTr("Conversation defaults")
    readonly property var mainDefaults: bridge.personaOverrideDefaults || ({})
    property var inheritedDefaults: ({provider: mainDefaults.provider || "", model: mainDefaults.model || "",
        context_messages: mainDefaults.contextMessages === undefined ? 20 : mainDefaults.contextMessages,
        document_memory_enabled: null})
    readonly property bool inheritedRecallEnabled: inheritedDefaults.document_memory_enabled === undefined
        || inheritedDefaults.document_memory_enabled === null
        ? Boolean((documentWorkspace.settings || {}).enabled) : Boolean(inheritedDefaults.document_memory_enabled)
    readonly property string overridePersonaId: personaId
    property var savedRecord: ({})
    readonly property bool personaAvailable: overridePersonaId.length > 0
        && String(savedRecord.id || "") === overridePersonaId
    readonly property var documentWorkspace: bridge.documentMemoryWorkspace || ({})
    readonly property var packages: documentWorkspace.packages || []
    readonly property var packageOptions: {
        const options = [{id: "", name: qsTr("Use configured default")}].concat(packages)
        if (packageId && !packages.some(row => String(row.id) === packageId))
            options.push({id: packageId, name: qsTr("%1 (unavailable)").arg(packageName), unavailable: true})
        return options
    }
    readonly property string packageId: String(overrideDraft.document_package_id || "")
    readonly property string effectivePackageId: packageId || String(documentWorkspace.activePackageId || "")
    readonly property var packageRecord: packages.find(row => String(row.id) === effectivePackageId) || ({})
    readonly property string packageName: String(packageRecord.name || overrideDraft.document_package_name || effectivePackageId || qsTr("No package configured"))
    readonly property bool recallEnabled: overrideDraft.document_memory === "enabled"
        || (overrideDraft.document_memory !== "disabled" && inheritedRecallEnabled)
    readonly property string packageWarning: {
        if (!recallEnabled) return ""
        if (!effectivePackageId || !packageRecord.id)
            return qsTr("%1 is unavailable. Documents are not used; the conversation continues.").arg(packageName)
        const status = (documentWorkspace.packageStates || {})[effectivePackageId] || packageRecord
        if (String(status.state || "") !== "ready")
            return qsTr("%1 is not ready. Documents are not used; the conversation continues.").arg(packageName)
                   + (status.status ? " " + String(status.status) : "")
        return status.warning ? packageName + ": " + String(status.warning) : ""
    }
    function refreshRecord() {
        savedRecord = personaId && typeof bridge.personaOverrideRecord === "function"
            ? bridge.personaOverrideRecord(personaId) : ({})
    }
    function choosePackage(index) {
        if (index < 0 || index >= packageOptions.length) return
        const row = packageOptions[index]
        if (row.unavailable) return
        setOverride("document_package_id", String(row.id || ""))
        setOverride("document_package_name", row.id ? String(row.name || row.id) : "")
    }
    Connections {
        target: root.bridge
        ignoreUnknownSignals: true
        function onQuickPersonaChanged() { root.refreshRecord() }
    }
    Component.onCompleted: { refreshRecord(); refreshOverrideCatalog() }
    onVisibleChanged: if (visible) { refreshRecord(); refreshOverrideCatalog() }
    Timer {
        interval: 400; repeat: true
        running: root.visible && root.personaAvailable && root.overrideDraft.llm_enabled && Boolean(root.overrideCatalog.loading)
        onTriggered: root.refreshOverrideCatalog()
    }
    property var overrideDrafts: ({})
    property var overrideCatalog: ({providers: []})
    property string overrideMessage: ""
    property bool overrideSaveError: false
    readonly property var overrideDraft: overrideDrafts[overridePersonaId]
        || savedRecord.overrides
        || ({llm_enabled: false, llm_provider: "", llm_model: "",
             context_enabled: false, context_messages: 20, document_memory: "inherit", document_package_id: "", document_package_name: ""})
    readonly property bool overrideDirty: overrideDrafts[overridePersonaId] !== undefined
    readonly property var overrideProviders: overrideCatalog.providers || []
    readonly property var overrideProvider: overrideProviders.find(
        row => row.id === String(overrideDraft.llm_provider || "")) || ({})
    readonly property var overrideModels: overrideProvider.models || []
    readonly property string overrideValidation: {
        if (!overrideDraft.llm_enabled)
            return ""
        if (!overrideProvider.id || !overrideProvider.available)
            return qsTr("Choose an available configured language model connection.")
        if (overrideProvider.loading)
            return qsTr("Loading models…")
        if (overrideProvider.message)
            return String(overrideProvider.message)
        if (!overrideModels.some(row => String(row.id || row.model || row.name || "") === overrideDraft.llm_model))
            return qsTr("Choose a model available on the selected connection.")
        return ""
    }
    onOverridePersonaIdChanged: {
        overrideMessage = ""
        overrideSaveError = false
        refreshRecord()
        // Let the selected persona draft binding settle before querying models.
        Qt.callLater(root.refreshOverrideCatalog)
    }

    function setOverride(key, value) {
        if (!personaAvailable)
            return
        const draft = Object.assign({}, overrideDraft)
        draft[key] = value
        const drafts = Object.assign({}, overrideDrafts)
        drafts[overridePersonaId] = draft
        overrideDrafts = drafts
        overrideMessage = ""
    }

    function refreshOverrideCatalog() {
        if (visible && personaAvailable && overrideDraft.llm_enabled)
            overrideCatalog = bridge.personaOverrideCatalog()
    }

    function discardOverrides() {
        const drafts = Object.assign({}, overrideDrafts)
        delete drafts[overridePersonaId]
        overrideDrafts = drafts
        overrideMessage = ""
    }

    function saveOverrides() {
        if (!personaAvailable) return
        const identity = overridePersonaId
        const result = bridge.savePersonaOverrides(identity, overrideDraft)
        overrideSaveError = !Boolean(result.accepted)
        if (result.accepted) {
            const drafts = Object.assign({}, overrideDrafts)
            delete drafts[identity]
            overrideDrafts = drafts
        }
        overrideMessage = String(result.message || "")
    }

    function overrideContextText(count) {
        return Number(count) === 0 ? qsTr("All messages") : qsTr("%1 messages").arg(count)
    }


    Layout.fillWidth: true
    spacing: Theme.NCMetrics.space12

    NCInlineMessage {
        Layout.fillWidth: true
        visible: !root.overridePersonaId.length
        tone: "info"
        title: qsTr("Save a persona first")
        message: qsTr("Choose or save a quick persona to give these overrides a permanent identity.")
    }
    NCInlineMessage {
        objectName: "personaOverrideUnavailable"
        Layout.fillWidth: true
        visible: root.overridePersonaId.length > 0 && !root.personaAvailable
        tone: "warning"
        title: qsTr("Persona unavailable")
        message: qsTr("This saved Persona is no longer available. Its overrides are read-only; choose an available Persona to edit overrides.")
    }
    ColumnLayout {
        Layout.fillWidth: true
        enabled: root.personaAvailable
        spacing: Theme.NCMetrics.space12
        ColumnLayout {
            objectName: "personaLanguageOverrideSection"
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space12
            visible: root.section === "all" || root.section === "language"
            NCSwitch {
                toolTipText: qsTr("Use a separate language model for this Persona everywhere it is used. Save to apply to new requests; the current reply keeps its captured settings.")

                objectName: "personaOverrideLlmEnabled"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: qsTr("Override language model")
                checked: Boolean(root.overrideDraft.llm_enabled)
                onToggled: {
                    root.setOverride("llm_enabled", checked)
                    root.refreshOverrideCatalog()
                }
            }
            Label {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: (root.overrideDraft.llm_enabled
                       ? (root.overrideDirty ? qsTr("After save") : qsTr("Effective"))
                       : root.conversationLabel) + ": "
                      + (root.overrideDraft.llm_enabled
                         ? String(root.overrideDraft.llm_provider || qsTr("Choose connection")) + " / " + String(root.overrideDraft.llm_model || qsTr("Choose model"))
                         : String(root.inheritedDefaults.provider || "") + " / " + String(root.inheritedDefaults.model || qsTr("No model selected")))
                      + " · " + (root.overrideDraft.llm_enabled ? qsTr("Persona override") : root.inheritedSourceLabel)
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
            NCComboBox {
                toolTipText: qsTr("Choose an existing configured connection for this Persona. Configure connections in Runtime; an unavailable connection reports an error rather than switching providers.")

                objectName: "personaOverrideProvider"
                Layout.fillWidth: true
                visible: root.overrideDraft.llm_enabled
                label: qsTr("Existing language model connection")
                model: root.overrideProviders
                textRole: "label"
                currentIndex: root.overrideProviders.findIndex(row => row.id === root.overrideDraft.llm_provider)
                displayText: currentIndex >= 0 ? currentText : String(root.overrideDraft.llm_provider || qsTr("Choose connection"))
                onActivated: {
                    root.setOverride("llm_provider", root.overrideProviders[currentIndex].id)
                    root.setOverride("llm_model", "")
                }
            }
            NCComboBox {
                toolTipText: qsTr("Choose a model on the selected connection for this Persona. Save the override before starting a new request.")

                objectName: "personaOverrideModel"
                Layout.fillWidth: true
                visible: root.overrideDraft.llm_enabled
                label: qsTr("Language model")
                model: root.overrideModels.map(row => String(row.id || row.model || row.name || ""))
                currentIndex: model.indexOf(root.overrideDraft.llm_model)
                displayText: currentIndex >= 0 ? currentText : String(root.overrideDraft.llm_model || qsTr("Choose model"))
                onActivated: root.setOverride("llm_model", currentText)
            }
            Label {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                visible: root.overrideValidation.length > 0
                text: root.overrideValidation
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
            Label {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                visible: root.overrideDraft.llm_enabled
                text: qsTr("Uses connections already configured in Runtime. An unavailable connection or model reports an error when requested; it does not fall back to another model.")
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
        }
        ColumnLayout {
            objectName: "personaMemoryOverrideSection"
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space12
            visible: root.section === "all" || root.section === "memory"
            NCSwitch {
                toolTipText: qsTr("Give this Persona its own conversation context limit. Off follows the conversation or room default. Save to apply to new requests.")

                objectName: "personaOverrideContextEnabled"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: qsTr("Override conversation context")
                checked: Boolean(root.overrideDraft.context_enabled)
                onToggled: root.setOverride("context_enabled", checked)
            }
            NCSpinBox {
                toolTipText: qsTr("Maximum recent messages this Persona receives for each new reply. 0 includes all available conversation messages. This does not delete saved history. Save to apply.")

                objectName: "personaOverrideContextMessages"
                visible: root.overrideDraft.context_enabled
                label: qsTr("Conversation context messages (0 = all)")
                from: 0
                to: 2147483647
                value: Number(root.overrideDraft.context_messages)
                onValueModified: root.setOverride("context_messages", value)
            }
            Label {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: (root.overrideDraft.context_enabled
                       ? (root.overrideDirty ? qsTr("After save") : qsTr("Effective"))
                       : root.conversationLabel) + ": "
                      + root.overrideContextText(root.overrideDraft.context_enabled
                          ? root.overrideDraft.context_messages : root.inheritedDefaults.context_messages)
                      + " · " + (root.overrideDraft.context_enabled ? qsTr("Persona override") : root.inheritedSourceLabel)
                      + "\n" + qsTr("0 uses all available conversation messages. With Use defaults, the limit follows the conversation or room where this persona is used.")
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
            Label { text: qsTr("Document Memory"); color: Theme.NCTheme.text }
            NCComboBox {
                toolTipText: qsTr("Use defaults inherits Document Memory behavior; Enabled or Disabled overrides it for this Persona. Save to apply to new requests.")

                objectName: "personaOverrideDocumentMemory"
                Layout.fillWidth: true
                label: qsTr("Document Memory override")
                model: [qsTr("Use defaults"), qsTr("Enabled"), qsTr("Disabled")]
                currentIndex: ["inherit", "enabled", "disabled"].indexOf(root.overrideDraft.document_memory)
                onActivated: root.setOverride("document_memory", ["inherit", "enabled", "disabled"][currentIndex])
            }
            Label { text: qsTr("Knowledge package"); color: Theme.NCTheme.text }
            NCComboBox {
                toolTipText: qsTr("Choose the knowledge package used for this Persona's new requests. Use configured default follows the current Document Memory package. Does not copy documents into the Persona.")

                objectName: "personaOverrideDocumentPackage"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                enabled: root.overrideDraft.document_memory !== "disabled"
                id: packagePicker
                contentItem: Label {
                    text: packagePicker.displayText
                    textFormat: Text.PlainText
                    font: packagePicker.font
                    color: packagePicker.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                delegate: ItemDelegate {
                    id: packageOption
                    required property int index
                    width: packagePicker.width
                    height: Theme.NCMetrics.controlHeight
                    highlighted: packagePicker.highlightedIndex === index
                    contentItem: Label {
                        text: packagePicker.textAt(packageOption.index)
                        textFormat: Text.PlainText
                        font: packagePicker.font
                        color: Theme.NCTheme.text
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                }
                label: qsTr("Knowledge package")
                model: root.packageOptions
                textRole: "name"
                currentIndex: root.packageOptions.findIndex(row => String(row.id) === root.packageId)
                displayText: currentIndex >= 0 ? currentText : qsTr("%1 · unavailable").arg(root.packageName)
                onActivated: root.choosePackage(currentIndex)
            }
            Label {
                textFormat: Text.PlainText
                objectName: "personaOverridePackageWarning"
                Layout.fillWidth: true
                visible: root.packageWarning.length > 0
                text: root.packageWarning
                color: Theme.NCTheme.warning
                wrapMode: Text.Wrap
            }
            Label {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: root.overrideDraft.document_memory === "disabled"
                    ? qsTr("Package selection is kept while recall is disabled.")
                    : qsTr("%1 · %2. Uses this existing package without copying documents.").arg(root.packageName)
                        .arg(root.packageId ? qsTr("Persona override") : qsTr("Configured Document Memory default"))
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
            Label {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: (root.overrideDirty ? qsTr("After save") : qsTr("Effective")) + ": "
                      + (root.overrideDraft.document_memory === "inherit"
                         ? (root.inheritedRecallEnabled ? qsTr("Enabled") : qsTr("Disabled"))
                         : (root.overrideDraft.document_memory === "enabled" ? qsTr("Enabled") : qsTr("Disabled")))
                      + " · " + (root.overrideDraft.document_memory === "inherit" ? root.conversationLabel : qsTr("Persona override"))
                      + "\n" + qsTr("Enabled requires an available Document Memory addon and a ready knowledge package.")
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
        }
        Flow {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space8
            NCButton {
                objectName: "personaOverrideDefaultsButton"
                width: Math.min(implicitWidth, parent.width)
                text: root.section === "all" ? qsTr("Use defaults for all") : qsTr("Use defaults for this tab")
                onClicked: {
                    if (root.section !== "memory") root.setOverride("llm_enabled", false)
                    if (root.section !== "language") {
                        root.setOverride("context_enabled", false)
                        root.setOverride("document_memory", "inherit")
                        root.setOverride("document_package_id", "")
                        root.setOverride("document_package_name", "")
                    }
                }
            }
            NCButton {
                width: Math.min(implicitWidth, parent.width)
                text: qsTr("Discard changes")
                enabled: root.overrideDirty
                onClicked: root.discardOverrides()
            }
            NCButton {
                objectName: "personaOverrideSaveButton"
                width: Math.min(implicitWidth, parent.width)
                text: qsTr("Save overrides")
                tone: "primary"
                enabled: root.personaAvailable && root.overrideDirty && !root.overrideValidation.length
                onClicked: root.saveOverrides()
            }
        }
        NCInlineMessage {
            Layout.fillWidth: true
            visible: root.overrideMessage.length > 0
            tone: root.overrideSaveError ? "error" : "info"
            title: root.overrideSaveError ? qsTr("Overrides were not saved") : qsTr("Overrides saved")
            message: root.overrideMessage
        }
    }

}
