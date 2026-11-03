pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Rectangle {
    id: root
    objectName: "sessionSetupWorkspace"

    required property var bridge
    property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
        bridge: root.bridge
        scrollView: sessionSetupScroll
        pageKey: "runtime:session"
    }
    property bool pinned: false
    property bool communicationLoggingVisible: true
    signal pinToggled(bool pinned)

    color: Theme.NCTheme.window
    radius: Theme.NCMetrics.radiusLarge
    border.color: Theme.NCTheme.border

    function displaySessionValue(value, fallback) {
        const normalized = String(value || fallback || "").replace(/_/g, " ")
        return normalized.length > 0
               ? normalized.charAt(0).toUpperCase() + normalized.slice(1)
               : ""
    }

    function indexForValue(values, wanted) {
        for (let index = 0; index < values.length; ++index) {
            const item = values[index]
            const value = typeof item === "object" ? item.id : item
            if (String(value) === String(wanted))
                return index
        }
        return values.length > 0 ? 0 : -1
    }

    property var inputModes: [
        {"id": "text_only", "label": qsTr("Text Only")},
        {"id": "voice_activation", "label": qsTr("Voice Activation")},
        {"id": "push_to_talk", "label": qsTr("Push-to-Talk")},
        {"id": "always_on", "label": qsTr("Always On")}
    ]
    property var inputRoles: [
        {"id": "user", "label": qsTr("User Message")},
        {"id": "system", "label": qsTr("System Message")},
        {"id": "assistant", "label": qsTr("Assistant Message")}
    ]
    property var streamModes: [
        {"id": false, "label": qsTr("Off")},
        {"id": true, "label": qsTr("On")}
    ]

    ScrollView {
        id: sessionSetupScroll
        anchors.fill: parent
        anchors.margins: Theme.NCMetrics.space16
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: sessionSetupScroll.availableWidth
            spacing: Theme.NCMetrics.space12

            NCSectionHeader {
                Layout.fillWidth: true
                eyebrow: qsTr("Runtime")
                title: qsTr("Session setup")
                description: qsTr("Configure input, profile, and runtime options for your session.")

                accessory: RowLayout {
                    spacing: Theme.NCMetrics.space8

                    NCButton {
                        objectName: "communicationLoggingVisibilityButton"
                        text: root.communicationLoggingVisible
                              ? qsTr("Hide communication logging")
                              : qsTr("Show communication logging")
                        compact: true
                        tone: "secondary"
                        onClicked: root.communicationLoggingVisible = !root.communicationLoggingVisible
                    }

                    NCButton {
                        text: root.pinned ? qsTr("Unpin") : qsTr("Pin to Runtime")
                        iconText: root.pinned ? "−" : "+"
                        compact: true
                        tone: root.pinned ? "primary" : "secondary"
                        toolTipText: root.pinned
                                     ? qsTr("Remove the compact Session Setup summary from Runtime")
                                     : qsTr("Keep a compact Session Setup summary above the active Runtime page")
                        onClicked: root.pinToggled(!root.pinned)
                    }
                }
            }

            NCCard {
                Layout.fillWidth: true
                title: qsTr("Input and profile")
                description: qsTr("Choose how you interact and which reusable preset to use.")

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 780 ? 2 : 1
                    columnSpacing: Theme.NCMetrics.space24
                    rowSpacing: Theme.NCMetrics.space12

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space10

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.preferredWidth: 118
                                text: qsTr("Input mode")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            NCComboBox {
                                toolTipText: qsTr("Text Only disables microphone speech recognition. Voice Activation listens for speech, Push-to-Talk records while its hotkey is held, and Always On uses continuous input. Typing remains available.")

                                Layout.fillWidth: true
                                model: root.inputModes
                                textRole: "label"
                                valueRole: "id"
                                currentIndex: root.indexForValue(root.inputModes, root.bridge.sessionSetup.inputMode)
                                objectName: "sessionInputModeSelector"
                                label: qsTr("Input mode")
                                onActivated: root.bridge.setSessionField("inputMode", currentValue)
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.preferredWidth: 118
                                text: qsTr("Input role")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            NCComboBox {
                                toolTipText: qsTr("Choose which role submitted input uses in the conversation. This changes how the model receives the input; it does not change your Discord account name.")

                                Layout.fillWidth: true
                                model: root.inputRoles
                                textRole: "label"
                                valueRole: "id"
                                currentIndex: root.indexForValue(root.inputRoles, root.bridge.sessionSetup.inputRole)
                                objectName: "sessionInputRoleSelector"
                                label: qsTr("Input role")
                                onActivated: root.bridge.setSessionField("inputRole", currentValue)
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.preferredWidth: 118
                                text: qsTr("Stream mode")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            NCComboBox {
                                toolTipText: qsTr("On uses streamed replies from the selected language model where supported. Off requests a complete response. This does not change the selected provider or model.")

                                Layout.fillWidth: true
                                model: root.streamModes
                                textRole: "label"
                                valueRole: "id"
                                currentIndex: root.indexForValue(root.streamModes, root.bridge.sessionSetup.streamMode)
                                objectName: "sessionStreamModeSelector"
                                label: qsTr("Stream mode")
                                onActivated: root.bridge.setSessionField("streamMode", currentValue)
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Push-to-Talk hotkey: Right Ctrl. Text Only disables microphone STT.")
                            color: Theme.NCTheme.textMuted
                            font.pixelSize: Theme.NCTypography.microSize
                            wrapMode: Text.Wrap
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space10

                        Label {
                            text: qsTr("Preset and workspace actions")
                            color: Theme.NCTheme.text
                            font.pixelSize: Theme.NCTypography.headingSize
                            font.weight: Theme.NCTypography.semibold
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Load or save a complete setup, then open related visual workspaces when needed.")
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                            wrapMode: Text.Wrap
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            NCComboBox {
                                toolTipText: qsTr("Select a saved session setup to load. Loading restores its configured settings; Save records the current setup under the selected name.")

                                id: presetCombo
                                Layout.fillWidth: true
                                model: root.bridge.presetNames.length > 0 ? root.bridge.presetNames : [qsTr("No presets")]
                                currentIndex: Math.max(0, model.indexOf(String(root.bridge.sessionSetup.activePreset || "")))
                                enabled: root.bridge.presetNames.length > 0
                                label: qsTr("Preset")
                                onActivated: root.bridge.selectPreset(currentText)
                            }
                            NCButton {
                                text: qsTr("Refresh")
                                compact: true
                                onClicked: root.bridge.refreshProviderState()
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            columnSpacing: Theme.NCMetrics.space8
                            rowSpacing: Theme.NCMetrics.space8

                            NCButton {
                                Layout.fillWidth: true
                                text: qsTr("Load")
                                enabled: root.bridge.presetNames.length > 0 && !root.bridge.systemRunning
                                toolTipText: root.bridge.systemRunning ? qsTr("Terminate the active session before loading a preset.") : ""
                                onClicked: root.bridge.loadPreset(presetCombo.currentText)
                            }
                            NCButton {
                                Layout.fillWidth: true
                                text: qsTr("Save")
                                tone: "primary"
                                enabled: presetCombo.enabled
                                onClicked: root.bridge.savePreset(presetCombo.currentText)
                            }
                            NCButton {
                                Layout.fillWidth: true
                                text: qsTr("Save As")
                                tone: "primary"
                                onClicked: {
                                    presetNameField.text = ""
                                    saveAsDialog.open()
                                }
                            }
                            NCButton {
                                Layout.fillWidth: true
                                text: qsTr("Delete")
                                tone: "danger"
                                enabled: presetCombo.enabled
                                onClicked: deleteDialog.open()
                            }
                        }
                    }
                }
            }

            NCCard {
                Layout.fillWidth: true
                title: qsTr("Main window tools")
                description: qsTr("Choose whether UI review controls appear in the main window header.")

                NCSwitch {
                    toolTipText: qsTr("Show or hide the Note mode and Notes controls in the main window. Existing notes are kept when these controls are hidden.")

                    objectName: "uiReviewNotesVisibilitySwitch"
                    Layout.fillWidth: true
                    text: qsTr("Show Note mode and Notes")
                    checked: root.bridge.uiReviewNotes.mainWindowControlsVisible
                    onClicked: root.bridge.uiReviewNotes.setMainWindowControlsVisible(checked)
                }

                Label {
                    Layout.fillWidth: true
                    text: qsTr("Turning this off also exits Note mode and closes the Notes drawer.")
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.microSize
                    wrapMode: Text.Wrap
                }
            }

            NCCard {
                Layout.fillWidth: true
                title: qsTr("Performance guidance")
                description: qsTr("Review context and hardware recommendations before initializing a demanding configuration.")

                NCSwitch {
                    toolTipText: qsTr("Show performance guidance in the session setup UI. This controls advice visibility; it does not apply a performance profile.")

                    text: qsTr("Show performance guidance")
                    checked: Boolean(root.bridge.sessionSetup.performanceGuidance)
                    onClicked: root.bridge.setSessionField("performanceGuidance", checked)
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    visible: Boolean(root.bridge.sessionSetup.performanceGuidance)
                    spacing: Theme.NCMetrics.space8

                    NCInlineMessage {
                        Layout.fillWidth: true
                        tone: "info"
                        title: qsTr("Current workload profile")
                        message: qsTr("Input: %1  ·  Streaming: %2  ·  Avatar: %3")
                                 .arg(root.displaySessionValue(root.bridge.sessionSetup.inputMode, qsTr("Text only")))
                                 .arg(Boolean(root.bridge.sessionSetup.streamMode) ? qsTr("On") : qsTr("Off"))
                                 .arg(root.displaySessionValue(root.bridge.sessionSetup.avatarMode, qsTr("None")))
                    }

                    NCInlineMessage {
                        Layout.fillWidth: true
                        tone: "warning"
                        title: qsTr("Before initialization")
                        message: Boolean(root.bridge.sessionSetup.streamMode)
                                 ? qsTr("Streaming can reduce time to first speech, but model, TTS, and avatar work may overlap. If the computer becomes sluggish, reduce model context or avatar load before disabling streaming.")
                                 : qsTr("Buffered replies avoid overlapping model and speech work, but TTS starts after the complete reply. If the computer becomes sluggish, reduce model context or avatar load first.")
                    }
                }
            }

            NCCommunicationLoggingCard {
                visible: root.communicationLoggingVisible
                Layout.fillWidth: true
                bridge: root.bridge
            }

            Item { Layout.preferredHeight: Theme.NCMetrics.space4 }
        }
    }

    NCDialog {
        id: saveAsDialog
        anchors.centerIn: parent
        title: qsTr("Save preset as")
        description: qsTr("Choose a clear name for this reusable NeuralCompanion setup.")
        acceptText: qsTr("Save preset")
        onOpened: presetNameField.forceActiveFocus()
        onAccepted: root.bridge.savePreset(presetNameField.text.trim())

        NCTextField {
            toolTipText: qsTr("Name used when saving the current session setup as a preset. Choose a distinct name to recognize this configuration later.")

            id: presetNameField
            width: parent ? parent.width : 420
            label: qsTr("Preset name")
            placeholderText: qsTr("My companion setup")
        }
    }

    NCDialog {
        id: deleteDialog
        anchors.centerIn: parent
        title: qsTr("Delete preset?")
        description: qsTr("Delete '%1'? This cannot be undone.").arg(presetCombo.currentText)
        acceptText: qsTr("Delete preset")
        acceptTone: "danger"
        onAccepted: root.bridge.deletePreset(presetCombo.currentText)
    }
}
