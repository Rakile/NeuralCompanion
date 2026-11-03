pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import Qt.labs.folderlistmodel
import "../components"
import "../theme" as Theme

Rectangle {
    id: root

    required property var bridge
    readonly property var setup: bridge.visualReplySetup
    readonly property string viewedProviderId: String(setup.provider || "")
    readonly property string activeProviderId: String(setup.activeProvider || setup.provider || "")

    function workflowIndex() {
        // File paths from Qt use forward slashes, saved Windows paths may not.
        let wanted = String(root.setup.model || "").replace(/\\/g, "/")
        if (Qt.platform.os === "windows") wanted = wanted.toLowerCase()
        for (let index = 0; index < workflowFiles.count; ++index) {
            let candidate = String(workflowFiles.get(index, "filePath")).replace(/\\/g, "/")
            if (Qt.platform.os === "windows") candidate = candidate.toLowerCase()
            if (candidate === wanted) return index
        }
        return -1
    }

    FolderListModel {
        id: workflowFiles
        objectName: "comfyuiWorkflowFiles"
        folder: root.setup.provider === "comfyui" ? String(root.setup.workflowFolderUrl || "") : ""
        nameFilters: ["*.json"]
        caseSensitive: false
        showDirs: false
        showDotAndDotDot: false
        sortField: FolderListModel.Name
        sortCaseSensitive: false
    }

    FolderDialog {
        id: workflowFolderDialog
        title: qsTr("Set ComfyUI workflow folder")
        currentFolder: String(root.setup.workflowFolderUrl || "")
        onAccepted: root.bridge.setVisualReplyField("workflowFolder", String(selectedFolder))
    }

    function stringIndex(values, wanted) {
        for (let index = 0; index < values.length; ++index) {
            if (String(values[index]) === String(wanted))
                return index
        }
        return values.length > 0 ? 0 : -1
    }

    color: Theme.NCTheme.window
    radius: Theme.NCMetrics.radiusLarge
    border.color: Theme.NCTheme.border

    Timer {
        interval: root.bridge.comfyuiGenerationSetup.metadata_available === false ? 8000 : 60000
        repeat: true
        running: root.visible && root.setup.provider === "comfyui"
        onTriggered: root.bridge.refreshComfyUIDetection()
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: Theme.NCMetrics.space16
        anchors.leftMargin: Theme.NCMetrics.space12
        anchors.topMargin: Theme.NCMetrics.space12
        spacing: Theme.NCMetrics.space12

        ColumnLayout {
            Layout.minimumWidth: 206
            Layout.preferredWidth: 206
            Layout.maximumWidth: 206
            Layout.fillHeight: true
            spacing: Theme.NCMetrics.space8

            NCSectionHeader {
                Layout.fillWidth: true
                Layout.bottomMargin: Theme.NCMetrics.space2
                eyebrow: qsTr("Visual reply")
                title: qsTr("Providers")
            }

            Repeater {
                model: root.bridge.visualReplyProviders
                delegate: Button {
                    id: providerButton
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 68
                    checked: String(modelData.id) === root.viewedProviderId
                    hoverEnabled: true
                    Accessible.name: qsTr("Select %1 visual reply provider").arg(String(modelData.label))

                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusMedium
                        color: providerButton.checked ? Theme.NCTheme.surfaceSelected
                                                      : providerButton.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
                        border.width: providerButton.activeFocus || providerButton.checked
                                      ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                        border.color: providerButton.activeFocus ? Theme.NCTheme.focus
                                                                : providerButton.checked ? Theme.NCTheme.accent : Theme.NCTheme.border
                    }
                    contentItem: RowLayout {
                        spacing: Theme.NCMetrics.space8
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Label {
                                Layout.fillWidth: true
                                text: String(providerButton.modelData.label)
                                color: Theme.NCTheme.text
                                font.weight: Theme.NCTypography.semibold
                                font.pixelSize: Theme.NCTypography.labelSize
                                elide: Text.ElideRight
                            }
                            Label {
                                Layout.fillWidth: true
                                text: String(providerButton.modelData.description)
                                color: Theme.NCTheme.textMuted
                                font.pixelSize: Theme.NCTypography.microSize
                                elide: Text.ElideRight
                            }
                        }
                        Label {
                            visible: String(providerButton.modelData.id) === root.activeProviderId
                            text: qsTr("Active")
                            color: Theme.NCTheme.success
                            font.pixelSize: Theme.NCTypography.microSize
                            font.weight: Theme.NCTypography.semibold
                        }
                        Rectangle {
                            Layout.preferredWidth: 10
                            Layout.preferredHeight: 10
                            radius: 5
                            color: String(providerButton.modelData.id) === root.activeProviderId
                                   ? Theme.NCTheme.success : Theme.NCTheme.disconnected
                        }
                    }
                    onClicked: root.bridge.viewVisualReplyProvider(String(providerButton.modelData.id))
                    onDoubleClicked: {
                        const providerId = String(providerButton.modelData.id)
                        root.bridge.viewVisualReplyProvider(providerId)
                        if (providerId !== root.activeProviderId)
                            root.bridge.selectVisualReplyProvider(providerId)
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }

        ScrollView {
            id: visualReplySettingsScroll
            property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
                bridge: root.bridge
                scrollView: visualReplySettingsScroll
                pageKey: "runtime:visual:" + root.viewedProviderId
            }
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: Theme.NCMetrics.space12

                NCCard {
                    Layout.fillWidth: true
                    elevated: true
                    title: root.setup.providerLabel || qsTr("Visual reply")

                    RowLayout {
                        Layout.fillWidth: true
                        NCStatusChip {
                            text: root.viewedProviderId === root.activeProviderId
                                  ? qsTr("Active visual provider") : qsTr("Viewing settings")
                            status: root.viewedProviderId === root.activeProviderId ? "active" : "info"
                        }
                        Label {
                            visible: root.viewedProviderId !== root.activeProviderId
                            text: qsTr("Active: %1").arg(String(root.setup.activeProviderLabel || root.activeProviderId))
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                        }
                        Item { Layout.fillWidth: true }
                        NCButton {
                            text: qsTr("Make active")
                            tone: "primary"
                            visible: root.viewedProviderId !== root.activeProviderId
                            onClicked: root.bridge.selectVisualReplyProvider(root.viewedProviderId)
                        }
                        NCComboBox {
                            Layout.preferredWidth: 190
                            label: qsTr("Visual reply mode")
                            toolTipText: qsTr("Off disables Visual Replies and the active persona visual policy. Automatic enables image requests under the persona visual policy; it does not generate an image immediately.")
                            model: [qsTr("Off"), qsTr("Automatic")]
                            currentIndex: root.setup.mode === "off" ? 0 : 1
                            onActivated: root.bridge.setVisualReplyField("mode", currentIndex === 0 ? "off" : "auto")
                        }
                    }
                }

                NCCard {
                    Layout.fillWidth: true
                    visible: root.setup.provider === "runware" || root.setup.provider === "xai"
                    title: qsTr("Image-to-image")
                    description: root.setup.provider === "xai"
                                 ? qsTr("Optional xAI reference editing. Requests without a reference use the standard image model above.")
                                 : qsTr("Optional Runware transformation. With this off, or when no reference image is supplied, Visual Reply keeps using the standard image model above.")

                    NCSwitch {
                        Layout.fillWidth: true
                        text: qsTr("Use image-to-image when a reference image is supplied")
                        toolTipText: qsTr("Use the selected image-to-image model when the request supplies a valid reference image. With this off, or without a reference, requests use the standard image model. Saved for the viewed provider.")
                        checked: Boolean(root.setup.imageToImageEnabled)
                        onClicked: root.bridge.setVisualReplyField("imageToImageEnabled", checked)
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: width >= 720 ? 2 : 1
                        columnSpacing: Theme.NCMetrics.space16
                        rowSpacing: Theme.NCMetrics.space12
                        enabled: Boolean(root.setup.imageToImageEnabled)

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space6
                            Label {
                                text: qsTr("Image-to-image model")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            NCComboBox {
                                Layout.fillWidth: true
                                label: qsTr("Image-to-image model")
                                toolTipText: qsTr("Model used to edit or transform a supplied reference image. Requires image-to-image to be enabled; requests without a reference keep using the standard image model.")
                                model: root.setup.imageToImageModelOptions || []
                                currentIndex: root.stringIndex(
                                                  root.setup.imageToImageModelOptions || [],
                                                  root.setup.imageToImageModel)
                                onActivated: root.bridge.setVisualReplyField(
                                                 "imageToImageModel", currentText)
                            }
                        }

                        ColumnLayout {
                            visible: root.setup.provider === "runware"
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space6
                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    Layout.fillWidth: true
                                    text: qsTr("Transformation strength")
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                }
                                Label {
                                    text: Number(root.setup.imageToImageStrength || 0.8).toFixed(2)
                                    color: Theme.NCTheme.accentSoft
                                    font.pixelSize: Theme.NCTypography.captionSize
                                }
                            }
                            NCSlider {
                                Layout.fillWidth: true
                                label: qsTr("Image-to-image transformation strength")
                                toolTipText: qsTr("Runware transformation strength sent with a reference-image request, from 0 to 1. Requires image-to-image to be enabled and a valid reference image.")
                                from: 0
                                to: 1
                                stepSize: 0.05
                                value: Number(root.setup.imageToImageStrength || 0.8)
                                onPressedChanged: {
                                    if (!pressed)
                                        root.bridge.setVisualReplyField(
                                                    "imageToImageStrength", value)
                                }
                            }
                        }
                    }

                    NCInlineMessage {
                        Layout.fillWidth: true
                        tone: "info"
                        title: qsTr("Safe fallback")
                        message: qsTr("The image-to-image model is only selected when the request contains a valid reference image. All other Visual Reply requests remain text-to-image.")
                    }

                }

                NCCard {
                    Layout.fillWidth: true
                    title: qsTr("Provider connection")
                    description: root.setup.provider === "comfyui"
                                 ? qsTr("Connect to a local or LAN ComfyUI instance and select its workflow.")
                                 : qsTr("Configure the model and credentials used by the selected hosted provider.")

                    GridLayout {
                        Layout.fillWidth: true
                        columns: width >= 720 ? 2 : 1
                        columnSpacing: Theme.NCMetrics.space16
                        rowSpacing: Theme.NCMetrics.space12

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space6
                            Label {
                                text: root.setup.provider === "comfyui" ? qsTr("Workflow path") : qsTr("Image model")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                visible: root.setup.provider === "comfyui"
                                NCComboBox {
                                    id: workflowPicker
                                    objectName: "comfyuiWorkflowPicker"
                                    Layout.fillWidth: true
                                    label: qsTr("ComfyUI workflow")
                                    toolTipText: qsTr("Select a JSON workflow from the chosen folder. The full path is shown below.")
                                    model: workflowFiles
                                    textRole: "fileName"
                                    currentIndex: root.workflowIndex()
                                    enabled: Boolean(root.setup.workflowFolderUrl) && workflowFiles.count > 0
                                    displayText: currentIndex >= 0 ? currentText
                                        : workflowFiles.status === FolderListModel.Loading ? qsTr("Loading workflows…")
                                        : !root.setup.workflowFolderUrl ? qsTr("Set a workflow folder")
                                        : workflowFiles.count === 0 ? qsTr("No JSON workflows in this folder")
                                        : qsTr("Choose a workflow")
                                    onActivated: function(index) {
                                        root.bridge.setVisualReplyField("model", String(workflowFiles.get(index, "filePath")))
                                    }
                                }
                                NCButton {
                                    objectName: "comfyuiSetWorkflowFolder"
                                    text: qsTr("Set folder")
                                    toolTipText: qsTr("Choose the folder containing your ComfyUI JSON workflows. Your current workflow stays selected until you choose another one.")
                                    onClicked: workflowFolderDialog.open()
                                }
                            }
                            NCTextField {
                                Layout.fillWidth: true
                                label: root.setup.provider === "comfyui" ? qsTr("Workflow path") : qsTr("Image model")
                                toolTipText: root.setup.provider === "comfyui"
                                    ? qsTr("Path to the ComfyUI workflow JSON used for image requests. Changing the workflow refreshes detection and selects its server-specific generation settings.")
                                    : qsTr("Image model identifier for the viewed provider. This provider keeps its own model setting; make the provider active to use it for Visual Replies.")
                                text: String(root.setup.model || "")
                                onEditingFinished: root.bridge.setVisualReplyField("model", text)
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: root.setup.provider !== "comfyui"
                            spacing: Theme.NCMetrics.space6
                            Label {
                                text: qsTr("Output size")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            NCComboBox {
                                Layout.fillWidth: true
                                label: qsTr("Output size")
                                toolTipText: qsTr("Requested image dimensions for the viewed provider. Available choices depend on the provider; Auto leaves size selection to its generation path.")
                                model: root.setup.sizeOptions || []
                                currentIndex: root.stringIndex(root.setup.sizeOptions || [], root.setup.size)
                                onActivated: root.bridge.setVisualReplyField("size", currentText)
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: root.setup.provider !== "comfyui"
                            spacing: Theme.NCMetrics.space6
                            Label {
                                text: qsTr("API key")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            NCTextField {
                                id: visualApiKeyField
                                Layout.fillWidth: true
                                label: qsTr("API key")
                                toolTipText: qsTr("Credential for the viewed image provider, stored separately from other providers. The masked placeholder represents the saved key; replace it only to change the credential.")
                                text: String(root.setup.apiKey || "")
                                echoMode: text === "••••••••" ? TextInput.Normal : TextInput.Password
                                onTextEdited: visualApiKeySaveTimer.restart()
                                onEditingFinished: {
                                    visualApiKeySaveTimer.stop()
                                    root.bridge.setVisualReplyField("apiKey", text)
                                }
                            }
                            Timer {
                                id: visualApiKeySaveTimer
                                interval: 450
                                repeat: false
                                onTriggered: root.bridge.setVisualReplyField(
                                                 "apiKey", visualApiKeyField.text)
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: root.setup.provider === "comfyui" || String(root.setup.baseUrl || "").length > 0
                            spacing: Theme.NCMetrics.space6
                            Label {
                                text: root.setup.provider === "comfyui" ? qsTr("Server address") : qsTr("Base URL")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            NCTextField {
                                Layout.fillWidth: true
                                label: qsTr("Base URL")
                                toolTipText: root.setup.provider === "comfyui"
                                    ? qsTr("HTTP or HTTPS address of the local or LAN ComfyUI server that runs the selected workflow. Changing the server refreshes workflow detection and uses that server/workflow generation profile.")
                                    : qsTr("API server address for the viewed image provider. Requests use this address when that provider is active.")
                                text: String(root.setup.baseUrl || "")
                                onEditingFinished: root.bridge.setVisualReplyField("baseUrl", text)
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: root.setup.provider === "comfyui"
                        spacing: Theme.NCMetrics.space6
                        Label {
                            text: qsTr("Prompting Rules")
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                        }
                        NCComboBox {
                            Layout.fillWidth: true
                            label: qsTr("Prompting Rules")
                            toolTipText: qsTr("Choose the ComfyUI model-family prompt rules. Auto Detect uses the checkpoint found in the workflow; a manual choice overrides detection. Unknown models use Generic / Custom rules.")
                            model: root.setup.promptingRuleLabels || []
                            currentIndex: root.stringIndex(root.setup.promptingRuleIds || [], root.setup.promptingRules)
                            onActivated: root.bridge.setVisualReplyField(
                                             "promptingRules", root.setup.promptingRuleIds[currentIndex])
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Detected model: %1").arg(String(root.setup.detectedModel || qsTr("Unknown")))
                            color: Theme.NCTheme.textSecondary
                            wrapMode: Text.Wrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Active rules: %1%2")
                                  .arg(String(root.setup.activePromptingRules || qsTr("Generic / Custom")))
                                  .arg(root.setup.promptingRules === "auto" ? "" : qsTr(" (manual override)"))
                            color: Theme.NCTheme.accentSoft
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: String(root.setup.promptingDetectionStatus || "") !== "Detected"
                            text: String(root.setup.promptingDetectionStatus || "")
                            color: Theme.NCTheme.textSecondary
                            wrapMode: Text.Wrap
                        }
                    }
                }

                NCComfyUIGenerationSettings {
                    Layout.fillWidth: true
                    visible: root.setup.provider === "comfyui"
                    bridge: root.bridge
                }

                NCCard {
                    Layout.fillWidth: true
                    title: qsTr("Display and story behavior")
                    description: qsTr("These options use the current Visual Reply dock, generation queue, and story pipeline.")
                    NCSwitch {
                        Layout.fillWidth: true
                        text: qsTr("Show Visual Reply automatically when generation starts")
                        toolTipText: qsTr("Allow image-generation activity to open the Visual Reply dock automatically. This controls display behavior rather than enabling image generation.")
                        checked: Boolean(root.setup.autoShow)
                        onClicked: root.bridge.setVisualReplyField("autoShow", checked)
                    }
                    NCSwitch {
                        Layout.fillWidth: true
                        text: qsTr("Allow story mode to request visual replies")
                        toolTipText: qsTr("Generate Visual Replies for spoken story chunks using the active image provider and the image limit configured in Story Visuals.")
                        checked: Boolean(root.setup.storyMode)
                        onClicked: root.bridge.setVisualReplyField("storyMode", checked)
                    }
                }

            }
        }
    }
}
