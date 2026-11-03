pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Rectangle {
    id: root
    objectName: "runtimeProviderWorkspace"
    NCTutorialMenu { id: providerTutorials; bridge: root.bridge }

    required property var bridge
    property bool advancedExpanded: false

    readonly property var generationFields: root.bridge.viewedProvider.generationFields || []
    readonly property string generationWarning: String((root.bridge.viewedProvider.metadata || {}).generation_warning || "")
    readonly property var connectionFields: (root.bridge.viewedProvider.fields || []).filter(field => field.section !== "model_load")
    readonly property var modelLoadFields: (root.bridge.viewedProvider.fields || []).filter(field => field.section === "model_load")
    readonly property var providerHeaderIcons: ({
        "lmstudio": "../../../ui_icons/providers/lmstudio.png",
        "ollama": "../../../ui_icons/providers/ollama.png",
        "openai": "../../../ui_icons/providers/openai.png",
        "xai": "../../../ui_icons/providers/xai.png",
        "deepseek": "../../../ui_icons/providers/deepseek.png",
        "claude": "../../../ui_icons/providers/claude.png"
    })
    readonly property var reasoningField: {
        if (root.bridge.viewedProviderId === "lmstudio" || root.bridge.viewedProviderId === "lmstudio_sdk") {
            const selected = String(root.bridge.viewedProvider.modelName || "")
            const catalog = root.bridge.unfilteredModelCatalog || []
            const model = catalog.find(item => String(item.id || "") === selected)
            if (root.bridge.viewedProviderId === "lmstudio_sdk") {
                const address = (root.bridge.viewedProvider.fields || []).find(field => field.id === "base_url")
                const current = String(address ? (address.value || address.default || "") : "").trim().replace(/\/+$/, "")
                if (!model || String(model.reasoning_base_url || "").trim().replace(/\/+$/, "") !== current)
                    return null
            }
            const options = model ? Array.from(model.reasoning_options || [])
                                  .map(option => String(option).trim().toLowerCase()) : []
            if (!model || model.supports_reasoning !== true
                    || options.indexOf("off") < 0 || options.indexOf("on") < 0)
                return null
        }
        for (let index = 0; index < generationFields.length; index++) {
            const field = generationFields[index]
            if (String(field.id || "") === "reasoning")
                return field
        }
        return null
    }
    readonly property var standardGenerationFields: {
        const fields = []
        for (let index = 0; index < generationFields.length; index++) {
            const field = generationFields[index]
            if (String(field.id || "") !== "reasoning")
                fields.push(field)
        }
        return fields
    }

    function providerHeaderIconSource(providerId) {
        const normalizedId = String(providerId || "").toLowerCase()
        return root.providerHeaderIcons[normalizedId] || "../../../ui_icons/runtime/language.png"
    }

    color: Theme.NCTheme.window
    radius: Theme.NCMetrics.radiusLarge
    border.color: Theme.NCTheme.border

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Item {
            Layout.minimumWidth: 230
            Layout.preferredWidth: 230
            Layout.maximumWidth: 230
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space12
                spacing: Theme.NCMetrics.space10

                NCSectionHeader {
                    Layout.fillWidth: true
                    eyebrow: qsTr("Language")
                    title: qsTr("Providers")
                }

                ListView {
                    objectName: "runtimeProviderList"
                    id: providerList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: root.bridge.providers
                    spacing: Theme.NCMetrics.space8
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Button {
                        id: providerButton
                        NCTutorialMarker { bridge: root.bridge; context: ({workspace: "runtime", runtime_section: "runtime", runtime_responsibility: "language", provider_kind: "language", provider_id: String(providerButton.modelData.id)}) }
                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onTapped: providerTutorials.openFor(providerButton,
                                {workspace: "runtime", runtime_section: "runtime", runtime_responsibility: "language",
                                 provider_kind: "language", provider_id: String(providerButton.modelData.id)})
                        }
                        required property var modelData
                        width: ListView.view.width
                        implicitHeight: 68
                        checked: String(modelData.id) === root.bridge.viewedProviderId
                        hoverEnabled: true
                        Accessible.name: String(modelData.label)
                        Accessible.description: Boolean(modelData.active) ? qsTr("Active language provider") : qsTr("Open provider settings")

                        background: Rectangle {
                            radius: Theme.NCMetrics.radiusMedium
                            color: providerButton.down ? Theme.NCTheme.surfacePressed
                                                       : providerButton.checked ? Theme.NCTheme.surfaceSelected
                                                       : providerButton.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
                            border.width: providerButton.activeFocus || providerButton.checked ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                            border.color: providerButton.activeFocus ? Theme.NCTheme.focus
                                                                     : providerButton.checked ? Theme.NCTheme.accent : Theme.NCTheme.border
                        }

                        contentItem: RowLayout {
                            spacing: Theme.NCMetrics.space8
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space2
                                Label {
                                    Layout.fillWidth: true
                                    text: String(providerButton.modelData.label)
                                    color: Theme.NCTheme.text
                                    font.pixelSize: Theme.NCTypography.labelSize
                                    font.weight: Theme.NCTypography.semibold
                                    elide: Text.ElideRight
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: Boolean(providerButton.modelData.active) ? qsTr("Active provider")
                                                                                  : String(providerButton.modelData.modelName || qsTr("Open settings"))
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                    elide: Text.ElideRight
                                }
                            }
                            Rectangle {
                                Layout.preferredWidth: 10
                                Layout.preferredHeight: 10
                                radius: 5
                                color: Boolean(providerButton.modelData.active) ? Theme.NCTheme.success : "transparent"
                                border.width: 1
                                border.color: Boolean(providerButton.modelData.active) ? Theme.NCTheme.success : Theme.NCTheme.borderStrong
                            }
                        }

                        onClicked: root.bridge.viewProvider(String(providerButton.modelData.id))
                        onDoubleClicked: {
                            const providerId = String(providerButton.modelData.id)
                            root.bridge.viewProvider(providerId)
                            if (providerId !== root.bridge.activeProviderId)
                                root.bridge.activateProvider(providerId)
                        }
                    }

                    ScrollBar.vertical: ScrollBar { }
                }
            }
        }

        ScrollView {
            id: providerSettingsScroll
            property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
                bridge: root.bridge
                scrollView: providerSettingsScroll
                pageKey: "runtime:language:" + root.bridge.viewedProviderId
            }
            Layout.minimumWidth: 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: Theme.NCMetrics.space12

                NCCard {
                    Layout.fillWidth: true
                    Layout.margins: Theme.NCMetrics.space16
                    Layout.leftMargin: 0
                    Layout.bottomMargin: 0
                    elevated: true

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space12

                        Image {
                            objectName: "providerHeaderIcon"
                            Layout.preferredWidth: 56
                            Layout.preferredHeight: 56
                            source: root.providerHeaderIconSource(root.bridge.viewedProviderId)
                            sourceSize.width: 96
                            sourceSize.height: 96
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                            mipmap: true
                        }

                        ColumnLayout {
                            spacing: Theme.NCMetrics.space2
                            Label {
                                text: String(root.bridge.viewedProvider.label || root.bridge.viewedProviderId)
                                color: Theme.NCTheme.text
                                font.pixelSize: Theme.NCTypography.titleSize
                                font.weight: Theme.NCTypography.semibold
                            }
                        }

                        Item {
                            objectName: "providerHeaderActionSpacer"
                            Layout.fillWidth: true
                        }

                        NCStatusChip {
                            text: root.bridge.viewedProviderId === root.bridge.activeProviderId ? qsTr("Active language provider") : qsTr("Viewing settings")
                            status: root.bridge.viewedProviderId === root.bridge.activeProviderId ? "active" : "info"
                        }

                        NCButton {
                            text: qsTr("Test connection")
                            tone: "quiet"
                            busy: root.bridge.providerTestInFlight
                            enabled: !root.bridge.modelRefreshInFlight && !root.bridge.providerTestInFlight
                            onClicked: root.bridge.testViewedProvider()
                        }

                        NCButton {
                            objectName: "runtimeProviderMakeActiveButton"
                            text: qsTr("Make active")
                            tone: "primary"
                            visible: root.bridge.viewedProviderId !== root.bridge.activeProviderId
                            onClicked: root.bridge.activateProvider(root.bridge.viewedProviderId)
                        }
                    }
                }

                NCCard {
                    Layout.fillWidth: true
                    Layout.leftMargin: 0
                    Layout.rightMargin: Theme.NCMetrics.space16
                    title: qsTr("Model and connection")
                    objectName: "runtimeProviderConnectionCard"

                    GridLayout {
                        Layout.fillWidth: true
                        columns: width >= 760 ? 2 : 1
                        columnSpacing: Theme.NCMetrics.space16
                        rowSpacing: Theme.NCMetrics.space10

                        ColumnLayout {
                            Layout.fillWidth: true
                            Label {
                                text: qsTr("Chat model")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                NCComboBox {
                                    objectName: "runtimeChatModelSelector"
                                    toolTipText: qsTr("Choose a model available on the viewed language-model connection. Selecting a model may require loading it when the runtime next uses it.")

                                    Layout.fillWidth: true
                                    model: root.bridge.modelNames.length > 0 ? root.bridge.modelNames
                                                                                 : [root.bridge.modelRequiresVision
                                                                                    ? qsTr("No vision-capable models")
                                                                                    : qsTr("No models loaded")]
                                    currentIndex: root.bridge.modelNames.length > 0
                                                  ? model.indexOf(String(root.bridge.viewedProvider.modelName || "")) : 0
                                    displayText: currentIndex < 0
                                                 ? (root.bridge.modelRequiresTools && root.bridge.viewedProvider.modelName
                                                    ? qsTr("Current: %1 (hidden by filters)").arg(root.bridge.viewedProvider.modelName)
                                                    : qsTr("Select a chat model")) : currentText
                                    enabled: !root.bridge.modelRefreshInFlight && root.bridge.modelNames.length > 0
                                    onActivated: root.bridge.selectModel(currentText)
                                }
                                NCButton {
                                    text: qsTr("Refresh")
                                    busy: root.bridge.modelRefreshInFlight
                                    onClicked: root.bridge.refreshModels()
                                }
                            }

                            NCInlineMessage {
                                Layout.fillWidth: true
                                visible: root.bridge.viewedProviderId === "lmstudio"
                                         && !root.bridge.modelRefreshInFlight
                                         && root.bridge.modelNames.length === 0
                                         && root.bridge.modelToolFilterMessage.length === 0
                                tone: "warning"
                                title: qsTr("LM Studio models are unavailable")
                                message: root.bridge.modelRefreshMessage.length > 0
                                         ? root.bridge.modelRefreshMessage
                                         : qsTr("Start LM Studio's local server, then refresh the model list.")
                            }
                        }

                        Repeater {
                            model: root.connectionFields
                            delegate: ColumnLayout {
                                id: providerField
                                required property var modelData
                                Layout.fillWidth: true

                                function persistValue(value) {
                                    root.bridge.setProviderField(
                                                String(providerField.modelData.id),
                                                value)
                                }

                                Label {
                                    text: String(providerField.modelData.label)
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                }
                                NCTextField {
                                    toolTipText: String(providerField.modelData.toolTip || providerField.modelData.description || "")

                                    id: providerFieldEditor
                                    objectName: String(providerField.modelData.id) === "api_key"
                                                ? "runtimeProviderApiKeyField"
                                                : "runtimeProviderField_" + String(providerField.modelData.id)
                                    Layout.fillWidth: true
                                    text: String(providerField.modelData.value ?? "")
                                    echoMode: Boolean(providerField.modelData.secret) ? TextInput.PasswordEchoOnEdit : TextInput.Normal
                                    label: String(providerField.modelData.label)
                                    onTextEdited: providerFieldSaveTimer.restart()
                                    onEditingFinished: {
                                        providerFieldSaveTimer.stop()
                                        providerField.persistValue(text)
                                    }
                                }

                                Timer {
                                    id: providerFieldSaveTimer
                                    interval: 450
                                    repeat: false
                                    onTriggered: providerField.persistValue(providerFieldEditor.text)
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: modelCapabilityControls.implicitHeight + Theme.NCMetrics.space16
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.windowRaised
                        border.color: Theme.NCTheme.border

                        ColumnLayout {
                            id: modelCapabilityControls
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space8
                            spacing: Theme.NCMetrics.space10

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space10

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.NCMetrics.space2

                                    Label {
                                        Layout.fillWidth: true
                                        text: qsTr("Vision-capable models only")
                                        color: Theme.NCTheme.text
                                        font.pixelSize: Theme.NCTypography.labelSize
                                        font.weight: Theme.NCTypography.semibold
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: qsTr("Filter the model list to providers that report or identify image input support.")
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.captionSize
                                        wrapMode: Text.Wrap
                                    }
                                }

                                NCSwitch {
                                    toolTipText: qsTr("Only offer models that the provider reports as capable of receiving images. This filters model selection; it does not add vision support to a text-only model.")

                                    id: visionFilterSwitch
                                    text: checked ? qsTr("On") : qsTr("Off")
                                    checked: root.bridge.modelRequiresVision
                                    Accessible.description: qsTr("Only show language models that can process images")
                                    onClicked: root.bridge.setModelRequiresVision(checked)

                                }

                                NCCapabilityIcon {
                                    kind: "vision"
                                    iconSize: 28
                                    toolTipText: qsTr("Vision-capable model filter")
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                visible: root.bridge.modelToolFilterAvailable
                                implicitHeight: 1
                                color: Theme.NCTheme.borderSubtle
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                visible: root.bridge.modelToolFilterAvailable
                                spacing: Theme.NCMetrics.space10

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.NCMetrics.space2

                                    Label {
                                        Layout.fillWidth: true
                                        text: qsTr("Tool-capable models only")
                                        color: Theme.NCTheme.text
                                        font.pixelSize: Theme.NCTypography.labelSize
                                        font.weight: Theme.NCTypography.semibold
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: root.bridge.modelToolFilterAvailable
                                              ? qsTr("Hide models reported without tool support. Models with unknown support remain visible.")
                                              : qsTr("Tool capability information is unavailable for this model list. The tool filter is not applied.")
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.captionSize
                                        wrapMode: Text.Wrap
                                    }
                                }

                                NCSwitch {
                                    objectName: "toolModelFilterSwitch"
                                    text: enabled ? (checked ? qsTr("On") : qsTr("Off")) : qsTr("Unavailable")
                                    checked: root.bridge.modelRequiresTools
                                    enabled: root.bridge.modelToolFilterAvailable
                                    toolTipText: qsTr("Exclude only models reported without tool support. When the API does not report this capability, the filter is not applied. Your selected model stays unchanged.")
                                    Accessible.description: qsTr("Hide models explicitly reported without tool support")
                                    onClicked: root.bridge.setModelRequiresTools(checked)
                                }

                                NCCapabilityIcon {
                                    kind: "tools"
                                    iconSize: 28
                                    toolTipText: qsTr("Tool-capable model filter")
                                }
                            }

                            NCInlineMessage {
                                objectName: "toolModelFilterEmptyMessage"
                                Layout.fillWidth: true
                                visible: !root.bridge.modelRefreshInFlight && root.bridge.modelToolFilterMessage.length > 0
                                tone: "info"
                                title: qsTr("No matching tool-capable models")
                                message: root.bridge.modelToolFilterMessage
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                visible: root.reasoningField !== null
                                implicitHeight: 1
                                color: Theme.NCTheme.borderSubtle
                            }

                            RowLayout {
                                id: reasoningToggleRow
                                Layout.fillWidth: true
                                visible: root.reasoningField !== null
                                spacing: Theme.NCMetrics.space10

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.NCMetrics.space2

                                    Label {
                                        Layout.fillWidth: true
                                        text: qsTr("Enable Thinking")
                                        color: Theme.NCTheme.text
                                        font.pixelSize: Theme.NCTypography.labelSize
                                        font.weight: Theme.NCTypography.semibold
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: String(root.reasoningField && root.reasoningField.description
                                                     ? root.reasoningField.description
                                                     : qsTr("Allow supported models to use their reasoning mode."))
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.captionSize
                                        wrapMode: Text.Wrap
                                    }
                                }

                                NCSwitch {
                                    toolTipText: qsTr("Request supported reasoning behavior for new model replies. Availability and the actual request values depend on the selected provider and model.")

                                    id: reasoningSwitch
                                    text: checked ? qsTr("On") : qsTr("Off")
                                    checked: Boolean(root.reasoningField && root.reasoningField.value)
                                    Accessible.description: qsTr("Enable model thinking and reasoning")
                                    onClicked: root.bridge.setGenerationField("reasoning", checked)

                                }

                                NCCapabilityIcon {
                                    kind: "thinking"
                                    iconSize: 28
                                    toolTipText: qsTr("Model thinking and reasoning")
                                }
                            }
                        }
                    }
                    ColumnLayout {
                        id: samplingWarningContent
                        objectName: "providerGenerationWarning"
                        visible: root.generationWarning.length > 0
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space4
                        property bool expanded: false
                        readonly property string providerId: root.bridge.viewedProviderId
                        readonly property string fullMessage: root.generationWarning
                        onProviderIdChanged: expanded = false
                        onFullMessageChanged: expanded = false

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space8

                            Rectangle {
                                Layout.preferredWidth: 18
                                Layout.preferredHeight: 18
                                Layout.alignment: Qt.AlignTop
                                Layout.topMargin: Theme.NCMetrics.space6
                                radius: 9
                                color: "transparent"
                                border.color: Theme.NCTheme.warning
                                border.width: 1.5
                                Accessible.ignored: true

                                Label {
                                    objectName: "providerGenerationWarningIcon"
                                    anchors.centerIn: parent
                                    text: "i"
                                    color: Theme.NCTheme.warning
                                    font.pixelSize: Theme.NCTypography.labelSize
                                    font.weight: Theme.NCTypography.bold
                                    Accessible.ignored: true
                                }
                            }
                            Label {
                                objectName: "providerGenerationWarningSummary"
                                Layout.fillWidth: true
                                text: samplingWarningContent.providerId === "lmstudio" || samplingWarningContent.providerId === "ollama"
                                      ? qsTr("Top K, Repetition Penalty and Min P are managed in %1.")
                                          .arg(String(root.bridge.viewedProvider.label || samplingWarningContent.providerId))
                                      : qsTr("Sampling settings have provider limitations.")
                                color: Theme.NCTheme.warning
                                font.pixelSize: Theme.NCTypography.labelSize
                                wrapMode: Text.Wrap
                            }
                            NCButton {
                                objectName: "providerGenerationWarningToggle"
                                Layout.alignment: Qt.AlignTop
                                implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
                                leftPadding: Theme.NCMetrics.space6
                                rightPadding: Theme.NCMetrics.space6
                                text: samplingWarningContent.expanded ? qsTr("Hide details") : qsTr("Details")
                                tone: "quiet"
                                compact: true
                                Accessible.description: qsTr("Show or hide sampling settings limitations for this provider.")
                                onClicked: samplingWarningContent.expanded = !samplingWarningContent.expanded
                            }
                        }
                        Label {
                            objectName: "providerGenerationWarningText"
                            Layout.fillWidth: true
                            Layout.leftMargin: 18 + Theme.NCMetrics.space8
                            visible: samplingWarningContent.expanded
                            text: root.generationWarning
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.labelSize
                            wrapMode: Text.Wrap
                        }
                    }
                    NCButton {
                        objectName: "providerAdvancedToggle"
                        text: root.advancedExpanded ? qsTr("Advanced provider settings ▴") : qsTr("Advanced provider settings ▾")
                        tone: "quiet"
                        onClicked: root.advancedExpanded = !root.advancedExpanded
                    }
                    ColumnLayout {
                        objectName: "providerAdvancedSettings"
                        visible: root.advancedExpanded
                        Layout.fillWidth: true

                        GridLayout {
                            Layout.fillWidth: true
                            columns: width >= 760 ? 2 : 1
                            columnSpacing: Theme.NCMetrics.space16
                            rowSpacing: Theme.NCMetrics.space10

                            Repeater {
                                model: root.standardGenerationFields
                                delegate: ColumnLayout {
                                    id: generationField
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Label {
                                        text: String(generationField.modelData.label)
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.captionSize
                                    }
                                    Loader {
                                        Layout.fillWidth: true
                                        property var field: generationField.modelData
                                        sourceComponent: String(field.kind || "").toLowerCase() === "bool"
                                                         ? generationBooleanEditor
                                                         : String(field.kind || "").toLowerCase() === "int"
                                                           ? generationIntegerEditor
                                                           : String(field.kind || "").toLowerCase() === "select"
                                                             ? generationChoiceEditor : generationNumberEditor
                                        onLoaded: item.field = field
                                    }
                                }
                            }

                            NCInlineMessage {
                                Layout.fillWidth: true
                                Layout.columnSpan: parent.columns
                                visible: root.standardGenerationFields.length === 0
                                tone: "info"
                                title: qsTr("No sampling controls")
                                message: qsTr("This provider does not expose additional sampling controls.")
                            }
                        }

                        Repeater {
                            model: root.modelLoadFields
                            delegate: ColumnLayout {
                                id: modelLoadField
                                required property var modelData
                                Layout.fillWidth: true
                                Label {
                                    text: String(modelLoadField.modelData.label)
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                }
                                NCSpinBox {
                                    toolTipText: String(modelLoadField.modelData.toolTip || modelLoadField.modelData.description || "")

                                    objectName: "modelLoad-" + String(modelLoadField.modelData.id)
                                    Layout.fillWidth: true
                                    label: String(modelLoadField.modelData.label)
                                    from: Number(modelLoadField.modelData.min)
                                    to: Number(modelLoadField.modelData.max)
                                    stepSize: Number(modelLoadField.modelData.step)
                                    value: Number(modelLoadField.modelData.value)
                                    onValueModified: root.bridge.setProviderField(String(modelLoadField.modelData.id), value)
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: String(modelLoadField.modelData.description)
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                    }
                }


                NCEmbeddingSetup {
                    Layout.fillWidth: true
                    Layout.rightMargin: Theme.NCMetrics.space16
                    Layout.bottomMargin: Theme.NCMetrics.space16
                    bridge: root.bridge
                }

            }
        }
    }

    Component.onCompleted: root.bridge.ensureViewedProviderModels()

    Connections {
        target: root.bridge
        function onProviderViewChanged() {
            root.bridge.ensureViewedProviderModels()
        }
    }

    Component {
        id: generationBooleanEditor
        NCSwitch {
            toolTipText: String(field.toolTip || field.description || "")

            property var field: ({})
            text: checked ? qsTr("Enabled") : qsTr("Disabled")
            checked: Boolean(field.value)
            onClicked: root.bridge.setGenerationField(String(field.id), checked)
        }
    }

    Component {
        id: generationIntegerEditor
        NCSpinBox {
            toolTipText: String(field.toolTip || field.description || "")

            property var field: ({})
            Layout.fillWidth: true
            label: String(field.label || field.id)
            from: Number(field.min === undefined ? -2147483647 : field.min)
            to: Number(field.max === undefined ? 2147483647 : field.max)
            stepSize: Math.max(1, Number(field.step === undefined ? 1 : field.step))
            value: Number(field.value || 0)
            onValueModified: root.bridge.setGenerationField(String(field.id), value)
        }
    }

    Component {
        id: generationChoiceEditor
        NCComboBox {
            toolTipText: String(field.toolTip || field.description || "")

            property var field: ({})
            Layout.fillWidth: true
            label: String(field.label || field.id)
            model: field.options || []
            textRole: "label"
            valueRole: "value"
            currentIndex: {
                const wanted = field.value === undefined ? field.default : field.value
                for (let index = 0; index < model.length; ++index) {
                    if (String(model[index].value) === String(wanted))
                        return index
                }
                return -1
            }
            onActivated: root.bridge.setGenerationField(String(field.id), currentValue)
        }
    }

    Component {
        id: generationNumberEditor
        NCNumberField {
            toolTipText: String(field.toolTip || field.description || "")

            id: generationNumber
            property var field: ({})
            Layout.fillWidth: true
            label: String(field.label || field.id)
            text: String(field.value === undefined ? "" : field.value)
            minimum: Number(field.min === undefined ? -1000000000 : field.min)
            maximum: Number(field.max === undefined ? 1000000000 : field.max)
            stepSize: ["temperature", "repetition_penalty", "repeat_penalty", "min_p"].indexOf(String(field.id)) >= 0
                      ? 0.05 : Number(field.step === undefined ? 0.01 : field.step)
            onEditingFinished: {
                if (acceptableInput && isFinite(Number(text)))
                    root.bridge.setGenerationField(String(field.id), Number(text))
            }
        }
    }
}
