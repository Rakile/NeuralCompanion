pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Rectangle {
    id: root
    NCTutorialMenu { id: providerTutorials; bridge: root.bridge }

    required property var bridge
    property string kind: "stt"
    readonly property bool isInput: kind === "stt"
    readonly property var backends: isInput ? bridge.speechInputBackends : bridge.speechOutputBackends
    readonly property string activeBackend: isInput ? bridge.selectedSpeechInputBackend : bridge.selectedSpeechOutputBackend
    readonly property string viewedBackend: isInput ? bridge.viewedSpeechInputBackend : bridge.viewedSpeechOutputBackend

    color: Theme.NCTheme.window
    radius: Theme.NCMetrics.radiusLarge
    border.color: Theme.NCTheme.border

    Component.onCompleted: bridge.viewSpeechBackend(kind, viewedBackend)

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
                    eyebrow: root.isInput ? qsTr("Speech input") : qsTr("Text to speech")
                    title: qsTr("Providers")
                }

                ListView {
                    id: providerList
                    objectName: "speechProviderList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: root.backends
                    spacing: Theme.NCMetrics.space8
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Button {
                        id: providerButton
                        NCTutorialMarker { bridge: root.bridge; context: ({workspace: "runtime", runtime_section: "runtime", runtime_responsibility: root.isInput ? "speech" : "voice", provider_kind: root.kind, provider_id: String(providerButton.modelData.id)}) }
                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onTapped: providerTutorials.openFor(providerButton,
                                {workspace: "runtime", runtime_section: "runtime", runtime_responsibility: root.isInput ? "speech" : "voice",
                                 provider_kind: root.kind, provider_id: String(providerButton.modelData.id)})
                        }
                        required property var modelData
                        property bool isActive: String(modelData.id) === root.activeBackend
                        property bool isViewed: String(modelData.id) === root.viewedBackend
                        width: ListView.view.width
                        implicitHeight: 68
                        checked: isViewed
                        hoverEnabled: true
                        enabled: root.bridge.runtimeOperation.length === 0
                        Accessible.name: qsTr("View %1 settings").arg(String(modelData.label))
                        Accessible.description: String(modelData.description || "")

                        background: Rectangle {
                            radius: Theme.NCMetrics.radiusMedium
                            color: providerButton.down ? Theme.NCTheme.surfacePressed
                                                       : providerButton.isViewed ? Theme.NCTheme.surfaceSelected
                                                       : providerButton.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
                            border.width: providerButton.activeFocus || providerButton.isViewed
                                          ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                            border.color: providerButton.activeFocus ? Theme.NCTheme.focus
                                                                   : providerButton.isViewed ? Theme.NCTheme.accent : Theme.NCTheme.border
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
                                    text: providerButton.isActive ? qsTr("Active provider")
                                                                  : String(providerButton.modelData.description || qsTr("Open settings"))
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                    elide: Text.ElideRight
                                }
                            }

                            Rectangle {
                                Layout.preferredWidth: 10
                                Layout.preferredHeight: 10
                                radius: 5
                                color: providerButton.isActive ? Theme.NCTheme.success : "transparent"
                                border.width: 1
                                border.color: providerButton.isActive ? Theme.NCTheme.success : Theme.NCTheme.borderStrong
                            }
                        }

                        onClicked: root.bridge.viewSpeechBackend(root.kind, String(providerButton.modelData.id))
                        onDoubleClicked: {
                            const providerId = String(providerButton.modelData.id)
                            root.bridge.viewSpeechBackend(root.kind, providerId)
                            if (!providerButton.isActive)
                                root.bridge.selectSpeechBackend(root.kind, providerId)
                        }
                    }

                    ScrollBar.vertical: ScrollBar { }
                }
            }
        }

        ScrollView {
            id: providerSettingsScroll
            objectName: "speechProviderSettingsScroll"
            property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
                bridge: root.bridge
                scrollView: providerSettingsScroll
                pageKey: "runtime:" + root.kind + ":" + root.viewedBackend
                         + (root.isInput ? "" : ":" + providerSettingsPanel.currentSectionKey)
            }
            Layout.minimumWidth: 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: Theme.NCMetrics.space12

                NCProviderSettingsPanel {
                    id: providerSettingsPanel
                    objectName: "speechProviderSettingsPanel"
                    Layout.fillWidth: true
                    Layout.margins: Theme.NCMetrics.space16
                    Layout.leftMargin: 0
                    Layout.bottomMargin: 0
                    bridge: root.bridge
                    kind: root.kind
                    providerId: root.viewedBackend
                    activeProviderId: root.activeBackend
                    activateLabel: root.isInput ? qsTr("Use for speech input") : qsTr("Use for voice output")
                    includeVoiceTagRulesTab: !root.isInput
                    onActivateRequested: providerId => root.bridge.selectSpeechBackend(root.kind, providerId)
                }

                ProviderTechnicalRulesCard {
                    objectName: "ttsDefaultRulesCard"
                    visible: !root.isInput && providerSettingsPanel.currentSectionKey === "voice-tag-rules"
                    Layout.fillWidth: true
                    Layout.rightMargin: Theme.NCMetrics.space16
                    bridge: root.bridge
                    kind: "tts"
                    providerId: root.viewedBackend
                }
                Item { Layout.preferredHeight: Theme.NCMetrics.space4 }
            }
        }
    }
}
