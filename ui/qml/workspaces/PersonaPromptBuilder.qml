pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

NCCard {
    id: root
    required property var controller
    readonly property var state: controller ? controller.state : ({})
    property bool advancedOpen: false
    signal savePersonaRequested()
    signal savePromptRequested()
    title: qsTr("System prompt builder")
    description: qsTr("Describe the persona, refine a draft, then apply it when you are ready.")
    Component.onCompleted: if (controller) controller.synchronize()
    Component.onDestruction: if (controller) controller.flush()

    function indexFor(rows, value, key) {
        for (let i = 0; i < rows.length; ++i)
            if (String(rows[i][key]) === String(value)) return i
        return -1
    }

    headerAccessory: NCStatusChip {
        text: Boolean(root.state.hasChanges) ? qsTr("Draft · not applied") : qsTr("Applied prompt active")
        status: Boolean(root.state.hasChanges) ? "warning" : "active"
    }

    GridLayout {
        Layout.fillWidth: true
        columns: width >= 820 ? 2 : 1
        columnSpacing: Theme.NCMetrics.space16
        rowSpacing: Theme.NCMetrics.space12

        ColumnLayout {
            Layout.preferredWidth: 285
            Layout.fillWidth: parent.columns === 1
            Layout.alignment: Qt.AlignTop
            Label { text: qsTr("Type"); color: Theme.NCTheme.textSecondary }
            NCComboBox {
                toolTipText: qsTr("Choose the kind of Persona prompt to build. It controls the prompt structure and available behavior preferences; apply the finished prompt to use it in chat.")

                objectName: "promptBuilderType"
                Layout.fillWidth: true
                label: qsTr("Prompt type")
                model: root.state.types || []
                textRole: "label"; valueRole: "value"
                enabled: !Boolean(root.state.applying)
                currentIndex: root.indexFor(model, root.state.prompt_type, "value")
                onActivated: root.controller.setField("prompt_type", currentValue)
            }
            Label {
                Layout.fillWidth: true
                text: root.state.prompt_type === "custom"
                      ? qsTr("Use an existing prompt directly or refine it without a type preset.")
                      : qsTr("Type rules are added separately when this prompt is applied.")
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.Wrap
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Label { text: qsTr("Describe the persona"); color: Theme.NCTheme.textSecondary }
            NCScrollableTextArea {
                toolTipText: qsTr("Describe the Persona's identity, speaking style, and behavior. The refiner uses this draft to propose a prompt; the active prompt changes only when you apply it.")

                objectName: "promptBuilderDescription"
                Layout.fillWidth: true
                implicitHeight: 100
                label: qsTr("Describe the persona")
                placeholderText: qsTr("Who are they? How should they speak and behave?")
                readOnly: Boolean(root.state.applying)
                showRefineAction: true
                refineActionEnabled: Boolean(root.state.canRefine)
                text: String(root.state.description || "")
                onTextChanged: if (text !== String(root.state.description || ""))
                                   root.controller.setField("description", text)
                onRefineRequested: root.controller.generate(false)
            }
            Label {
                text: qsTr("Your description stays intact when you refine or regenerate.")
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }
            NCButton {
                objectName: "promptBuilderApplyDescription"
                text: qsTr("Apply description as system prompt")
                enabled: Boolean(root.state.canApplyDescription)
                onClicked: root.controller.applyDescription()
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        NCButton {
            objectName: "promptBuilderRefine"
            text: Boolean(root.state.inFlight) ? qsTr("Refining…") : qsTr("Refine")
            tone: "primary"; enabled: Boolean(root.state.canRefine)
            onClicked: root.controller.generate(false)
        }
        NCButton {
            objectName: "promptBuilderRegenerate"
            text: qsTr("Regenerate")
            enabled: Boolean(root.state.canRefine)
            onClicked: root.controller.generate(true)
        }
        Item { Layout.fillWidth: true }
        NCButton {
            objectName: "promptBuilderAdvanced"
            text: root.advancedOpen ? qsTr("Advanced ▾") : qsTr("Advanced ▸")
            tone: "secondary"
            onClicked: root.advancedOpen = !root.advancedOpen
        }
    }
    NCInlineMessage {
        Layout.fillWidth: true
        visible: String(root.state.error || root.state.message || "").length > 0
        tone: String(root.state.error || "").length ? "error" : "info"
        message: String(root.state.error || root.state.message || "")
    }

    NCCard {
        Layout.fillWidth: true
        visible: root.advancedOpen
        title: qsTr("Shape the persona")
        description: qsTr("Choose who writes the draft, then tune how your persona speaks and responds.")
        GridLayout {
            Layout.fillWidth: true
            columns: width >= 720 ? 2 : 1
            columnSpacing: Theme.NCMetrics.space16
            rowSpacing: Theme.NCMetrics.space12
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: parent.columns === 2 ? 260 : -1
                Layout.maximumWidth: parent.columns === 2 ? 300 : Infinity
                Layout.alignment: Qt.AlignTop
                spacing: Theme.NCMetrics.space8
                Label { text: qsTr("Draft provider"); color: Theme.NCTheme.textSecondary }
                NCComboBox {
                    toolTipText: qsTr("Connection used to refine the Persona prompt. This is separate from the Persona's chat-model override and does not switch your normal chat connection.")

                    id: refinerProvider
                    objectName: "promptBuilderProvider"
                    Layout.fillWidth: true
                    label: qsTr("Prompt refiner provider")
                    model: root.state.providers || []
                    textRole: "label"; valueRole: "id"
                    enabled: !Boolean(root.state.applying)
                    currentIndex: root.indexFor(model, root.state.provider_id, "id")
                    displayText: currentIndex >= 0 ? currentText : qsTr("Provider unavailable")
                    onActivated: root.controller.setField("provider_id", currentValue)
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Service used to write the prompt.")
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 620
                Layout.alignment: Qt.AlignTop
                spacing: Theme.NCMetrics.space8
                Label { text: qsTr("Draft model"); color: Theme.NCTheme.textSecondary }
                RowLayout {
                    Layout.fillWidth: true
                    NCComboBox {
                        toolTipText: qsTr("Model used for prompt refinement on the selected connection. A text model is enough; vision is not required. Refinement sends the draft for generation; applying the result remains a separate action.")

                        id: refinerModel
                        objectName: "promptBuilderModel"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        label: qsTr("Prompt refiner model")
                        model: root.state.models || []
                        textRole: "label"; valueRole: "id"
                        enabled: !Boolean(root.state.modelsLoading) && !Boolean(root.state.applying)
                        currentIndex: root.indexFor(model, root.state.model_id, "id")
                        displayText: Boolean(root.state.modelsLoading) ? qsTr("Loading models…")
                                     : currentIndex >= 0 ? currentText : qsTr("Choose an available model")
                        onActivated: root.controller.setField("model_id", currentValue)
                    }
                    NCButton {
                        text: qsTr("Refresh")
                        toolTipText: qsTr("Reload configured providers and the selected provider's available models.")
                        enabled: !Boolean(root.state.modelsLoading)
                        onClicked: root.controller.refreshProviders()
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Writes the draft; your conversation keeps its current model.")
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: Theme.NCTheme.border
            Layout.topMargin: Theme.NCMetrics.space4
            Layout.bottomMargin: Theme.NCMetrics.space4
        }
        Label {
            text: qsTr("Behavior preferences")
            color: Theme.NCTheme.text
            font.weight: Font.DemiBold
        }
        GridLayout {
            Layout.fillWidth: true
            columns: width >= 720 ? 2 : 1
            columnSpacing: Theme.NCMetrics.space12
            rowSpacing: Theme.NCMetrics.space12
            Repeater {
                model: [
                    {key: "verbosity", label: qsTr("Verbosity"), values: ["terse", "normal", "expansive"],
                     labels: [qsTr("Terse"), qsTr("Normal"), qsTr("Expansive")],
                     summary: qsTr("How much detail the persona gives"),
                     effects: [qsTr("Brief replies with little elaboration."), qsTr("Balanced detail, expanding when useful."), qsTr("Richer detail, fuller explanations and longer scenes.")],
                     help: qsTr("Terse: concise replies with little elaboration.\nNormal: moderate detail, expanding when useful.\nExpansive: fuller explanations or scene development.\nThis guides writing style; it does not set a token limit.")},
                    {key: "initiative", label: qsTr("Initiative"), values: ["reactive", "suggestive", "proactive"],
                     labels: [qsTr("Reactive"), qsTr("Suggestive"), qsTr("Proactive")],
                     summary: qsTr("How much the persona takes the lead"),
                     effects: [qsTr("Follows your lead without introducing new directions."), qsTr("Responds and offers a useful next step."), qsTr("Moves the conversation, scene or task forward when your intent is clear.")],
                     help: qsTr("Reactive: follows your request.\nSuggestive: offers a useful next step.\nProactive: helps move things forward when your intent is clear.\nThis affects replies; it does not enable automatic messages or background actions.")},
                    {key: "warmth", label: qsTr("Warmth"), values: ["cool", "warm", "expressive"],
                     labels: [qsTr("Cool"), qsTr("Warm"), qsTr("Expressive")],
                     summary: qsTr("How openly the persona expresses emotion"),
                     effects: [qsTr("Restrained, matter-of-fact emotional expression."), qsTr("Friendly, responsive and emotionally balanced."), qsTr("More emotion, lively reactions and conversational energy.")],
                     help: qsTr("Cool: emotionally restrained and matter-of-fact.\nWarm: balanced warmth and responsiveness.\nExpressive: stronger emotional presence in wording and reactions.\nThis shapes the prompt, not voice or audio settings.")},
                    {key: "formality", label: qsTr("Formality"), values: ["casual", "neutral", "formal"],
                     labels: [qsTr("Casual"), qsTr("Neutral"), qsTr("Formal")],
                     summary: qsTr("How relaxed or formal the wording feels"),
                     effects: [qsTr("Relaxed, everyday conversational language."), qsTr("Natural language with a professional, neutral tone."), qsTr("Precise, structured and formal language.")],
                     help: qsTr("Casual: relaxed conversational wording.\nNeutral: natural, professional-neutral language.\nFormal: precise and structured wording.\nThis changes expression, not the persona's expertise or accuracy.")}
                ]
                delegate: Rectangle {
                    id: behaviorControl
                    required property var modelData
                    objectName: "promptBuilderTile_" + modelData.key
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.minimumWidth: 0
                    Layout.fillHeight: true
                    implicitHeight: behaviorContent.implicitHeight + 28
                    color: Theme.NCTheme.windowRaised
                    border.color: Theme.NCTheme.border
                    radius: Theme.NCMetrics.radiusMedium
                    ColumnLayout {
                        id: behaviorContent
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                        spacing: Theme.NCMetrics.space8
                        Label {
                            Layout.fillWidth: true
                            text: behaviorControl.modelData.label
                            color: Theme.NCTheme.text
                            font.weight: Font.DemiBold
                        }
                        Label {
                            Layout.fillWidth: true
                            text: behaviorControl.modelData.summary
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                            wrapMode: Text.Wrap
                        }
                        NCComboBox {
                            toolTipText: String(behaviorControl.modelData.help || behaviorControl.modelData.summary || "")

                            id: behaviorChoice
                            objectName: "promptBuilderControl_" + behaviorControl.modelData.key
                            readonly property string helpText: behaviorControl.modelData.help
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            label: behaviorControl.modelData.label
                            Accessible.description: helpText
                            model: behaviorControl.modelData.labels
                            enabled: !Boolean(root.state.applying)
                            currentIndex: behaviorControl.modelData.values.indexOf(root.state[behaviorControl.modelData.key])
                            onActivated: root.controller.setField(behaviorControl.modelData.key,
                                                                  behaviorControl.modelData.values[currentIndex])
                        }
                        Label {
                            objectName: "promptBuilderHelp_" + behaviorControl.modelData.key
                            Layout.fillWidth: true
                            text: behaviorControl.modelData.effects[Math.max(0, behaviorChoice.currentIndex)]
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("Change preferences → Refine or Regenerate → review → Apply to Persona. Your description takes priority if it conflicts with a preference.")
            color: Theme.NCTheme.textSecondary
            font.pixelSize: Theme.NCTypography.captionSize
            wrapMode: Text.Wrap
        }
    }

    GridLayout {
        Layout.fillWidth: true
        columns: width >= 850 ? 2 : 1
        columnSpacing: Theme.NCMetrics.space16
        rowSpacing: Theme.NCMetrics.space12
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            RowLayout {
                id: draftPromptHeader
                Layout.fillWidth: true
                Label { text: qsTr("Generated persona prompt"); color: Theme.NCTheme.text }
                Item { Layout.fillWidth: true }
                NCButton {
                    objectName: "promptBuilderRefineDraft"
                    text: qsTr("Refine draft")
                    compact: true
                    enabled: Boolean(root.state.canRefineDraft)
                    onClicked: root.controller.refineDraft()
                }
            }
            NCScrollableTextArea {
                toolTipText: qsTr("Proposed Persona prompt. Edit or refine it, then apply it to make it active. Generating a proposal does not automatically replace the current system prompt.")

                objectName: "promptBuilderCandidate"
                Layout.fillWidth: true
                implicitHeight: 270
                label: qsTr("Generated persona prompt")
                placeholderText: qsTr("Refine a description or write your own persona prompt here.")
                readOnly: Boolean(root.state.applying)
                showRefineAction: true
                refineActionEnabled: Boolean(root.state.canRefineDraft)
                text: String(root.state.candidate || "")
                onTextChanged: if (text !== String(root.state.candidate || ""))
                                   root.controller.setField("candidate", text)
                onRefineRequested: root.controller.refineDraft()
            }
            RowLayout {
                Layout.fillWidth: true
                NCButton {
                    text: qsTr("Copy draft")
                    enabled: String(root.state.candidate || "").length > 0
                    onClicked: root.controller.copyCandidate()
                }
                Item { Layout.fillWidth: true }
                NCButton {
                    objectName: "promptBuilderApply"
                    text: Boolean(root.state.applying) ? qsTr("Saving…") : qsTr("Apply as persona system prompt")
                    tone: "primary"
                    enabled: Boolean(root.state.canApply)
                    onClicked: root.controller.apply()
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: draftPromptHeader.implicitHeight
                Label { text: qsTr("Active persona system prompt"); color: Theme.NCTheme.text }
                Item { Layout.fillWidth: true }
                NCStatusChip {
                    text: Boolean(root.state.activeEditDirty) ? qsTr("Edits not applied")
                          : String(root.state.appliedPrompt || "").length ? qsTr("Live") : qsTr("Empty")
                    status: Boolean(root.state.activeEditDirty) ? "warning"
                            : String(root.state.appliedPrompt || "").length ? "active" : "disconnected"
                }
            }
            NCScrollableTextArea {
                toolTipText: qsTr("Edit the Persona's active prompt draft directly. Apply your edits to replace the saved Persona prompt; the running reply keeps its captured instructions.")

                objectName: "promptBuilderActivePrompt"
                Layout.fillWidth: true
                implicitHeight: 270
                label: qsTr("Active persona system prompt")
                placeholderText: qsTr("Write a persona prompt, then apply your edits.")
                accentBorder: true
                readOnly: Boolean(root.state.applying)
                text: String(root.state.activeEdit || "")
                onTextChanged: if (text !== String(root.state.activeEdit || ""))
                                   root.controller.setActivePromptText(text)
            }
            RowLayout {
                Layout.fillWidth: true
                NCButton {
                    text: qsTr("Use live as draft")
                    compact: true
                    enabled: String(root.state.appliedPrompt || "").length > 0
                             && !Boolean(root.state.applying)
                    onClicked: root.controller.useApplied()
                }
                Item { Layout.fillWidth: true }
                NCButton {
                    objectName: "promptBuilderApplyActive"
                    text: Boolean(root.state.applying) ? qsTr("Saving…") : qsTr("Apply active edits")
                    tone: "primary"
                    enabled: Boolean(root.state.canApplyActiveEdit)
                    onClicked: root.controller.applyActiveEdit()
                }
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("Edits change the live persona only after you apply them.")
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.Wrap
            }
        }
    }
    GridLayout {
        id: saveActions
        Layout.fillWidth: true
        columns: width >= 650 ? 2 : 1
        NCButton {
            Layout.fillWidth: true
            text: qsTr("Save applied prompt to library")
            enabled: !Boolean(root.state.applying)
            onClicked: root.savePromptRequested()
        }
        NCButton {
            Layout.fillWidth: true
            text: qsTr("Save persona…")
            enabled: !Boolean(root.state.saving)
            onClicked: root.savePersonaRequested()
        }
    }

}

