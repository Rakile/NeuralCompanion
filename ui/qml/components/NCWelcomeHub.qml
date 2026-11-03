pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Dialog {
    id: root
    required property var bridge
    property bool showAtStartup: true
    signal workspaceRequested(string workspaceKey)
    modal: true
    focus: true
    closePolicy: Popup.NoAutoClose
    width: Math.min(parent ? parent.width - Theme.NCMetrics.space40 : 960, 960)
    height: Math.min(parent ? parent.height - Theme.NCMetrics.space40 : 620, 620)
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.round((parent.height - height) / 2) : 0
    padding: Theme.NCMetrics.space16
    standardButtons: Dialog.NoButton

    function finish() {
        bridge.setWelcomeHubStartup(showAtStartup)
        bridge.completeFirstRunPrompt(false)
        close()
    }
    function startTutorial(id) {
        bridge.setWelcomeHubStartup(showAtStartup)
        bridge.completeFirstRunPrompt(false)
        bridge.currentWorkspace = "addons"
        bridge.viewAddon("core.tutorials")
        bridge.startTutorial(id)
        close()
    }
    function openConversation() {
        finish()
        workspaceRequested("conversation")
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusLarge
        color: Theme.NCTheme.surface
        border.width: Theme.NCMetrics.focusWidth
        border.color: Theme.NCTheme.borderStrong
    }

    header: Item {
        implicitHeight: welcomeHeader.implicitHeight + Theme.NCMetrics.space24
        RowLayout {
            id: welcomeHeader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.NCMetrics.space16
            spacing: Theme.NCMetrics.space12
            Rectangle {
                Layout.preferredWidth: 56
                Layout.preferredHeight: 56
                Layout.alignment: Qt.AlignTop
                radius: Theme.NCMetrics.radiusLarge
                color: Theme.NCTheme.surfaceRaised
                border.width: Theme.NCMetrics.borderWidth
                border.color: Theme.NCTheme.borderStrong
                clip: true
                Image {
                    anchors.fill: parent
                    anchors.margins: 3
                    source: "../../../ui_icons/branding/NC_logo.png"
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space4
                Label {
                    Layout.fillWidth: true
                    text: root.bridge.systemRunning ? qsTr("NeuralCompanion is ready") : qsTr("Welcome to NeuralCompanion")
                    color: Theme.NCTheme.text
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.titleSize
                    font.weight: Theme.NCTypography.semibold
                }
                Label {
                    Layout.fillWidth: true
                    text: root.bridge.systemRunning ? qsTr("Continue to main chat, or choose a guide to explore more.") : qsTr("Start with your first main-chat reply. The guide shows the required setup; voice, images, and avatars can come later.")
                    color: Theme.NCTheme.textSecondary
                    font.pixelSize: Theme.NCTypography.bodySize
                    wrapMode: Text.Wrap
                }
            }
            NCIconButton {
                text: "×"
                toolTipText: qsTr("Close for now")
                onClicked: root.finish()
            }
        }
    }

    contentItem: ScrollView {
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded
        ColumnLayout {
            width: parent.width
            height: Math.max(implicitHeight, parent.height)
            spacing: Theme.NCMetrics.space12
            GridLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                columns: width >= 760 ? 2 : 1
                columnSpacing: Theme.NCMetrics.space12
                rowSpacing: Theme.NCMetrics.space12

                NCCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: qsTr("Recommended path for new users")
                    description: qsTr("Start here for step-by-step help: choose a chat provider, connect a model, switch power ON, and send your first message.")
                    contentItem: ColumnLayout {
                        spacing: Theme.NCMetrics.space8
                        Repeater {
                            model: [
                                {
                                    title: qsTr("Default companion"),
                                    detail: qsTr("Echo is available to guide you."),
                                    ready: true
                                },
                                {
                                    title: qsTr("Language model"),
                                    detail: root.bridge.systemRunning ? qsTr("The runtime is initialized.") : qsTr("Double-click an LLM provider, configure its connection and model, then use the top-right OFF/ON power button."),
                                    statusLabel: root.bridge.systemRunning ? qsTr("Initialized") : qsTr("Setup needed"),
                                    ready: root.bridge.systemRunning
                                },
                                {
                                    title: qsTr("Text input"),
                                    detail: qsTr("Type messages in Conversation."),
                                    ready: true
                                },
                                {
                                    title: qsTr("Voice output"),
                                    detail: root.bridge.selectedSpeechOutputBackend === "none" ? qsTr("Optional · You can start with text replies.") : qsTr("Selected: %1 · Top-right power OFF → ON loads it; test by listening.").arg(root.bridge.selectedSpeechOutputBackend),
                                    statusLabel: root.bridge.selectedSpeechOutputBackend === "none" ? qsTr("Optional") : qsTr("Selected"),
                                    statusTone: "info",
                                    ready: false
                                },
                                {
                                    title: qsTr("Visual Reply"),
                                    detail: qsTr("Optional · Configure image generation when wanted."),
                                    ready: false
                                }
                            ]
                            delegate: Rectangle {
                                id: setupDelegate
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: 48
                                radius: Theme.NCMetrics.radiusMedium
                                color: Theme.NCTheme.surfaceRaised
                                border.width: Theme.NCMetrics.borderWidth
                                border.color: Theme.NCTheme.border
                                RowLayout {
                                    id: row
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space8
                                    Label {
                                        text: setupDelegate.modelData.ready ? "✓" : "○"
                                        color: setupDelegate.modelData.statusTone === "info" ? Theme.NCTheme.textMuted : setupDelegate.modelData.ready ? Theme.NCTheme.success : Theme.NCTheme.warning
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Label {
                                            text: setupDelegate.modelData.title
                                            color: Theme.NCTheme.text
                                            font.weight: Theme.NCTypography.semibold
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: setupDelegate.modelData.detail
                                            color: Theme.NCTheme.textSecondary
                                            font.pixelSize: Theme.NCTypography.captionSize
                                            maximumLineCount: 1
                                            elide: Text.ElideRight
                                        }
                                    }
                                    NCStatusChip {
                                        text: setupDelegate.modelData.statusLabel || (setupDelegate.modelData.ready ? qsTr("Ready") : qsTr("Optional"))
                                        status: setupDelegate.modelData.statusTone || (setupDelegate.modelData.ready ? "ready" : "warning")
                                        compact: true
                                    }
                                }
                            }
                        }
                        NCButton {
                            Layout.fillWidth: true
                            tone: "primary"
                            text: root.bridge.systemRunning ? qsTr("Open Conversation") : qsTr("Start your first chat")
                            onClicked: root.bridge.systemRunning ? root.openConversation() : root.startTutorial("first_run")
                        }
                    }
                }

                NCCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: qsTr("Explore when you are ready")
                    description: qsTr("Optional next steps after your first main-chat reply. All guides remain available in Tutorials.")
                    contentItem: ColumnLayout {
                        spacing: Theme.NCMetrics.space8
                        GridLayout {
                            Layout.fillWidth: true
                            columns: width >= 410 ? 2 : 1
                            rowSpacing: Theme.NCMetrics.space8
                            columnSpacing: Theme.NCMetrics.space8
                            Repeater {
                                model: [
                                    {
                                        title: qsTr("Start a conversation"),
                                        detail: qsTr("Chat, queue messages, and control playback."),
                                        tutorial: "conversation"
                                    },
                                    {
                                        title: qsTr("Hear your companion speak"),
                                        detail: qsTr("Configure voice output and speech streaming."),
                                        tutorial: "speech_and_streaming"
                                    },
                                    {
                                        title: qsTr("Create a visual identity"),
                                        detail: qsTr("Build a persona portrait and mood set."),
                                        tutorial: "personas_and_chat"
                                    },
                                    {
                                        title: qsTr("Generate a Visual Reply"),
                                        detail: qsTr("Configure an image provider and create a reply."),
                                        tutorial: "visual_reply_controls"
                                    },
                                    {
                                        title: qsTr("Search the web together"),
                                        detail: qsTr("Install, start, and use Web Search."),
                                        tutorial: "web_search"
                                    },
                                    {
                                        title: qsTr("Bring NC to the desktop"),
                                        detail: qsTr("Explore Companion Orb and AI Presence."),
                                        tutorial: "ai_presence_and_overlays"
                                    }
                                ]
                                delegate: Button {
                                    id: activityButton
                                    required property var modelData
                                    Layout.fillWidth: true
                                    implicitHeight: 74
                                    Layout.minimumHeight: Math.max(74, contentItem.implicitHeight + topPadding + bottomPadding)
                                    hoverEnabled: true
                                    Accessible.name: activityButton.modelData.title
                                    Accessible.description: activityButton.modelData.detail
                                    leftPadding: Theme.NCMetrics.space10
                                    rightPadding: Theme.NCMetrics.space10
                                    topPadding: Theme.NCMetrics.space8
                                    bottomPadding: Theme.NCMetrics.space8
                                    onClicked: root.startTutorial(activityButton.modelData.tutorial)
                                    NCToolTip {
                                        visible: activityButton.hovered || activityButton.activeFocus
                                        text: activityButton.modelData.title + "\n" + activityButton.modelData.detail
                                    }
                                    background: Rectangle {
                                        radius: Theme.NCMetrics.radiusMedium
                                        color: activityButton.hovered ? Theme.NCTheme.surfaceSelected : Theme.NCTheme.surfaceRaised
                                        border.width: Theme.NCMetrics.borderWidth
                                        border.color: activityButton.hovered ? Theme.NCTheme.accent : Theme.NCTheme.border
                                    }
                                    contentItem: RowLayout {
                                        spacing: Theme.NCMetrics.space10
                                        Rectangle {
                                            Layout.preferredWidth: 30
                                            Layout.preferredHeight: 30
                                            radius: Theme.NCMetrics.radiusMedium
                                            color: Theme.NCTheme.accentSoft
                                            Label {
                                                anchors.centerIn: parent
                                                text: "↗"
                                                color: Theme.NCTheme.accent
                                                font.pixelSize: Theme.NCTypography.headingSize
                                            }
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: activityButton.modelData.title
                                            color: Theme.NCTheme.text
                                            font.weight: Theme.NCTypography.semibold
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 70
                            radius: Theme.NCMetrics.radiusMedium
                            color: Theme.NCTheme.surfaceRaised
                            border.width: Theme.NCMetrics.borderWidth
                            border.color: Theme.NCTheme.border
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: Theme.NCMetrics.space6
                                spacing: Theme.NCMetrics.space4
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.NCMetrics.space8
                                    Label {
                                        text: qsTr("Community")
                                        color: Theme.NCTheme.text
                                        font.weight: Theme.NCTypography.semibold
                                    }
                                    Label {
                                        id: communityThanks
                                        Layout.fillWidth: true
                                        text: qsTr("Thank you from Rakila & Lainol")
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.captionSize
                                        maximumLineCount: 1
                                        elide: Text.ElideRight
                                    }
                                }
                                RowLayout {
                                    id: communityLinkRow
                                    Layout.fillWidth: true
                                    spacing: Theme.NCMetrics.space8
                                    Repeater {
                                        model: [
                                            {
                                                title: qsTr("Discord"),
                                                badge: "",
                                                badgeColor: "#5865F2",
                                                iconSource: "../../../ui_icons/side_tabs/discord_chatt.png",
                                                url: "https://discord.com/invite/UqnwX46rcK"
                                            },
                                            {
                                                title: qsTr("Patreon"),
                                                badge: "P",
                                                badgeColor: "#FF424D",
                                                iconSource: "",
                                                url: "https://www.patreon.com/cw/Neuralcompanion"
                                            },
                                            {
                                                title: qsTr("Coffee"),
                                                badge: "B",
                                                badgeColor: "#FFDD00",
                                                iconSource: "",
                                                url: "https://buymeacoffee.com/neuralcompanion"
                                            }
                                        ]
                                        delegate: Button {
                                            id: communityButton
                                            required property var modelData
                                            Layout.fillWidth: true
                                            implicitHeight: 34
                                            leftPadding: Theme.NCMetrics.space6
                                            rightPadding: Theme.NCMetrics.space6
                                            hoverEnabled: true
                                            Accessible.name: qsTr("Open %1").arg(communityButton.modelData.title)
                                            onClicked: Qt.openUrlExternally(communityButton.modelData.url)
                                            background: Rectangle {
                                                radius: Theme.NCMetrics.radiusMedium
                                                color: communityButton.hovered ? Theme.NCTheme.surfaceSelected : Theme.NCTheme.surface
                                                border.width: Theme.NCMetrics.borderWidth
                                                border.color: communityButton.hovered ? Theme.NCTheme.accent : Theme.NCTheme.borderStrong
                                            }
                                            contentItem: RowLayout {
                                                spacing: Theme.NCMetrics.space4
                                                Image {
                                                    visible: communityButton.modelData.iconSource.length > 0
                                                    Layout.preferredWidth: 22
                                                    Layout.preferredHeight: 22
                                                    source: communityButton.modelData.iconSource
                                                    fillMode: Image.PreserveAspectFit
                                                    smooth: true
                                                }
                                                Rectangle {
                                                    visible: communityButton.modelData.iconSource.length === 0
                                                    Layout.preferredWidth: 22
                                                    Layout.preferredHeight: 22
                                                    radius: Theme.NCMetrics.space6
                                                    color: communityButton.modelData.badgeColor
                                                    Label {
                                                        anchors.centerIn: parent
                                                        text: communityButton.modelData.badge
                                                        color: "#111827"
                                                        font.weight: Theme.NCTypography.bold
                                                        font.pixelSize: Theme.NCTypography.captionSize
                                                    }
                                                }
                                                Label {
                                                    Layout.fillWidth: true
                                                    text: communityButton.modelData.title
                                                    color: Theme.NCTheme.text
                                                    font.pixelSize: Theme.NCTypography.captionSize
                                                    font.weight: Theme.NCTypography.semibold
                                                    elide: Text.ElideRight
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    footer: Item {
        implicitHeight: welcomeFooter.implicitHeight + Theme.NCMetrics.space24
        RowLayout {
            id: welcomeFooter
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.NCMetrics.space16
            spacing: Theme.NCMetrics.space10
            NCCheckBox {
                toolTipText: qsTr("Choose whether this welcome screen is shown when NC starts. Save or finish the welcome flow to keep the preference; hiding it does not disable tutorials.")

                text: qsTr("Show this welcome screen at startup")
                checked: root.showAtStartup
                onToggled: root.showAtStartup = checked
            }
            Item {
                Layout.fillWidth: true
            }
            NCButton {
                text: qsTr("Explore all tutorials")
                onClicked: root.startTutorial("first_run")
            }
            NCButton {
                text: qsTr("Close")
                onClicked: root.finish()
            }
        }
    }
}
