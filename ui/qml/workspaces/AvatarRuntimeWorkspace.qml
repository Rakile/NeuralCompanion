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
    readonly property string activeProvider: String(bridge.sessionSetup.avatarMode || "none")
    readonly property string viewedProvider: String(bridge.viewedAvatarProvider || activeProvider)

    color: Theme.NCTheme.window
    radius: Theme.NCMetrics.radiusLarge
    border.color: Theme.NCTheme.border

    Component.onCompleted: bridge.viewAvatarProvider(viewedProvider)

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
                    eyebrow: qsTr("Avatar")
                    title: qsTr("Providers")
                }

                ListView {
                    id: providerList
                    objectName: "avatarProviderList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: root.bridge.avatarOptions
                    spacing: Theme.NCMetrics.space8
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Button {
                        id: avatarButton
                        NCTutorialMarker { bridge: root.bridge; context: ({workspace: "runtime", runtime_section: "runtime", runtime_responsibility: "avatar", provider_kind: "avatar", provider_id: String(avatarButton.modelData.id)}) }
                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onTapped: providerTutorials.openFor(avatarButton,
                                {workspace: "runtime", runtime_section: "runtime", runtime_responsibility: "avatar",
                                 provider_kind: "avatar", provider_id: String(avatarButton.modelData.id)})
                        }
                        required property var modelData
                        property bool isActive: String(modelData.id) === root.activeProvider
                        property bool isViewed: String(modelData.id) === root.viewedProvider
                        width: ListView.view.width
                        implicitHeight: 68
                        checked: isViewed
                        hoverEnabled: true
                        Accessible.name: qsTr("View %1 settings").arg(String(modelData.label))
                        Accessible.description: String(modelData.description || "")

                        background: Rectangle {
                            radius: Theme.NCMetrics.radiusMedium
                            color: avatarButton.down ? Theme.NCTheme.surfacePressed
                                                     : avatarButton.isViewed ? Theme.NCTheme.surfaceSelected
                                                     : avatarButton.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
                            border.width: avatarButton.activeFocus || avatarButton.isViewed
                                          ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                            border.color: avatarButton.activeFocus ? Theme.NCTheme.focus
                                                                 : avatarButton.isViewed ? Theme.NCTheme.accent : Theme.NCTheme.border
                        }

                        contentItem: RowLayout {
                            spacing: Theme.NCMetrics.space8

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space2

                                Label {
                                    Layout.fillWidth: true
                                    text: String(avatarButton.modelData.label)
                                    color: Theme.NCTheme.text
                                    font.pixelSize: Theme.NCTypography.labelSize
                                    font.weight: Theme.NCTypography.semibold
                                    elide: Text.ElideRight
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: avatarButton.isActive ? qsTr("Active provider")
                                                                : String(avatarButton.modelData.description || qsTr("Open settings"))
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                    elide: Text.ElideRight
                                }
                            }

                            Rectangle {
                                Layout.preferredWidth: 10
                                Layout.preferredHeight: 10
                                radius: 5
                                color: avatarButton.isActive ? Theme.NCTheme.success : "transparent"
                                border.width: 1
                                border.color: avatarButton.isActive ? Theme.NCTheme.success : Theme.NCTheme.borderStrong
                            }
                        }

                        onClicked: root.bridge.viewAvatarProvider(String(avatarButton.modelData.id))
                        onDoubleClicked: {
                            const providerId = String(avatarButton.modelData.id)
                            root.bridge.viewAvatarProvider(providerId)
                            if (!avatarButton.isActive)
                                root.bridge.setSessionField("avatarMode", providerId)
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
                pageKey: "runtime:avatar:" + root.viewedProvider
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
                    Layout.fillWidth: true
                    Layout.margins: Theme.NCMetrics.space16
                    Layout.leftMargin: 0
                    Layout.bottomMargin: 0
                    bridge: root.bridge
                    kind: "avatar"
                    providerId: root.viewedProvider
                    activeProviderId: root.activeProvider
                    activateLabel: qsTr("Use this avatar")
                    onActivateRequested: providerId => root.bridge.setSessionField("avatarMode", providerId)
                }

                ProviderTechnicalRulesCard {
                    objectName: "avatarDefaultRulesCard"
                    Layout.fillWidth: true
                    Layout.rightMargin: Theme.NCMetrics.space16
                    bridge: root.bridge
                    kind: "avatar"
                    providerId: root.viewedProvider
                }
                Item { Layout.preferredHeight: Theme.NCMetrics.space4 }
            }
        }
    }
}
