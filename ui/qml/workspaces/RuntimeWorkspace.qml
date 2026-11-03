pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Rectangle {
    id: root
    objectName: "runtimeWorkspace"

    required property var bridge
    property string currentSection: "runtime"
    property string currentResponsibility: "language"
    property bool sessionSetupPinned: false
    property bool navigationReady: false
    NCTutorialMenu { id: responsibilityTutorials; bridge: root.bridge }

    function restoredSelection(key, fallback, options) {
        const saved = typeof bridge.navigationSelection === "function"
                      ? bridge.navigationSelection(key, fallback) : fallback
        return options.indexOf(saved) >= 0 ? saved : fallback
    }

    function rememberSelection(key, value) {
        if (navigationReady && typeof bridge.rememberNavigationSelection === "function")
            bridge.rememberNavigationSelection(key, value)
    }

    Component.onCompleted: {
        currentResponsibility = restoredSelection("runtime:responsibility", currentResponsibility,
                                                  ["session", "resources", "language", "speech", "voice", "visual", "avatar"])
        currentSection = restoredSelection("runtime:section", currentSection,
                                          ["runtime", "vision", "chat", "story", "memory", "themes", "mcp"])
        navigationReady = true
    }
    onCurrentSectionChanged: rememberSelection("runtime:section", currentSection)
    onCurrentResponsibilityChanged: rememberSelection("runtime:responsibility", currentResponsibility)

    Connections {
        target: root.bridge
        function onOrbProviderSettingsRequested() {
            root.currentSection = "runtime"
            root.currentResponsibility = "language"
            root.sessionSetupPinned = false
        }
        function onRuntimeSectionRequested(section) {
            const wanted = String(section || "")
            const supported = ["runtime", "vision", "chat", "story", "memory", "themes", "mcp"]
            if (supported.indexOf(wanted) >= 0)
                root.currentSection = wanted
        }
        function onTechnicalRulesProviderRequested(responsibility) {
            root.currentSection = "runtime"
            root.currentResponsibility = responsibility
            root.sessionSetupPinned = false
        }
    }

    color: Theme.NCTheme.window
    radius: Theme.NCMetrics.radiusLarge
    border.color: Theme.NCTheme.borderSubtle

    RowLayout {
        anchors.fill: parent
        spacing: Theme.NCMetrics.space12

        NCSectionRail {
            id: sectionRail
            objectName: "runtimeSectionRail"
            tutorialBridge: root.bridge
            tutorialContext: ({workspace: "runtime"})
            tutorialRouteKey: "runtime_section"
            Layout.fillHeight: true
            Layout.preferredWidth: Theme.NCMetrics.sectionRailWidth
            heading: qsTr("Settings")
            currentKey: root.currentSection
            model: [
                {
                    "key": "runtime",
                    "label": qsTr("Runtime\nSession"),
                    "icon": Qt.resolvedUrl("../../../ui_icons/side_tabs/host.png")
                },
                {
                    "key": "vision",
                    "label": qsTr("Vision\nSensors"),
                    "icon": Qt.resolvedUrl("../../../ui_icons/side_tabs/vision.png")
                },
                {
                    "key": "chat",
                    "label": qsTr("Chat\nBehavior"),
                    "icon": Qt.resolvedUrl("../../../ui_icons/side_tabs/chat.png")
                },
                {
                    "key": "story",
                    "label": qsTr("Story\nVisuals"),
                    "icon": Qt.resolvedUrl("../../../ui_icons/side_tabs/story_visuals.png")
                },
                {
                    "key": "memory",
                    "label": qsTr("Document\nMemory"),
                    "icon": Qt.resolvedUrl("../../../ui_icons/side_tabs/brain.png")
                },
                {
                    "key": "mcp",
                    "label": qsTr("MCP Core"),
                    "icon": Qt.resolvedUrl("../../../ui_icons/side_tabs/mcp_core.png")
                },
                {
                    "key": "themes",
                    "label": qsTr("Appearance\nThemes"),
                    "icon": Qt.resolvedUrl("../../../ui_icons/side_tabs/themes.png")
                }
            ]
            onActivated: key => root.currentSection = key
        }

        Loader {
            id: sectionPage
            Layout.fillWidth: true
            Layout.fillHeight: true
            // Restore navigation before constructing a page with refresh side effects.
            active: root.navigationReady
            sourceComponent: root.currentSection === "runtime" ? runtimePage
                           : root.currentSection === "vision" ? visionProvidersPage
                           : root.currentSection === "memory" ? documentMemoryPage
                           : root.currentSection === "mcp" ? mcpCorePage
                           : coreSettingsPage
        }
    }

    // Hide only the outer-border bridges across the rail/page gap.
    Item {
        x: sectionRail.x + sectionRail.width - root.border.width
        width: Math.max(0, sectionPage.x + root.border.width - x)
        height: root.height

        Rectangle {
            anchors.top: parent.top
            width: parent.width
            height: root.border.width
            color: root.color
        }
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: root.border.width
            color: root.color
        }
    }

    Component {
        id: mcpCorePage
        Loader {
            property var controller: root.bridge.mcpCoreController || null
            source: controller ? Qt.resolvedUrl("../../../addons/mcp_core/qml/McpCorePage.qml") : ""
            onLoaded: item.controller = controller
            Label {
                anchors.centerIn: parent
                visible: !parent.controller || parent.status === Loader.Error
                text: qsTr("MCP Core is unavailable. Enable or restore the addon.")
                color: Theme.NCTheme.textSecondary
            }
        }
    }

    Component {
        id: documentMemoryPage
        ScrollView {
            id: documentSettingsScroll
            objectName: "documentMemoryWorkspace"
            property alias selectedDocumentSection: documentMemoryPanel.selectedSection
            property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
                bridge: root.bridge
                scrollView: documentSettingsScroll
                pageKey: "runtime:memory"
            }
            clip: true
            contentWidth: availableWidth
            Component.onCompleted: root.bridge.refreshDocumentMemory()
            NCDocumentMemoryPanel {
                id: documentMemoryPanel
                width: documentSettingsScroll.availableWidth
                bridge: root.bridge
            }
        }
    }

    Component {
        id: runtimePage
        Rectangle {
            color: Theme.NCTheme.windowRaised
            radius: Theme.NCMetrics.radiusLarge
            border.color: Theme.NCTheme.border

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space12
                spacing: Theme.NCMetrics.space12

                ColumnLayout {
                    objectName: "runtimeResponsibilityRail"
                    Layout.minimumWidth: 136
                    Layout.preferredWidth: 136
                    Layout.maximumWidth: 136
                    Layout.fillHeight: true
                    spacing: Theme.NCMetrics.space8

                    Repeater {
                        model: [
                            {
                                "key": "session",
                                "label": qsTr("Session setup"),
                                "icon": Qt.resolvedUrl("../../../ui_icons/runtime/session.png")
                            },
                            {
                                "key": "resources",
                                "label": qsTr("Resources"),
                                "icon": Qt.resolvedUrl("../../../ui_icons/side_tabs/dry_run.png")
                            },
                            {
                                "key": "language",
                                "label": qsTr("LLM"),
                                "icon": Qt.resolvedUrl("../../../ui_icons/runtime/language.png")
                            },
                            {
                                "key": "speech",
                                "label": qsTr("Speech-to-text"),
                                "icon": Qt.resolvedUrl("../../../ui_icons/runtime/speech_input.png")
                            },
                            {
                                "key": "voice",
                                "label": qsTr("Text-to-speech"),
                                "icon": Qt.resolvedUrl("../../../ui_icons/runtime/voice.png")
                            },
                            {
                                "key": "visual",
                                "label": qsTr("Visual reply"),
                                "icon": Qt.resolvedUrl("../../../ui_icons/runtime/visual_reply.png")
                            },
                            {
                                "key": "avatar",
                                "label": qsTr("Avatar"),
                                "icon": Qt.resolvedUrl("../../../ui_icons/runtime/avatar.png")
                            }
                        ]

                        delegate: Button {
                            id: responsibilityButton
                            NCTutorialMarker { bridge: root.bridge; context: ({workspace: "runtime", runtime_section: "runtime", runtime_responsibility: String(responsibilityButton.modelData.key)}) }
                            required property var modelData
                            property bool selected: String(modelData.key) === root.currentResponsibility
                            Layout.fillWidth: true
                            implicitHeight: 92
                            leftPadding: Theme.NCMetrics.space6
                            rightPadding: Theme.NCMetrics.space6
                            topPadding: Theme.NCMetrics.space6
                            bottomPadding: Theme.NCMetrics.space6
                            hoverEnabled: true
                            Accessible.name: String(modelData.label)

                            background: Rectangle {
                                radius: Theme.NCMetrics.radiusMedium
                                color: responsibilityButton.selected ? Theme.NCTheme.surfaceSelected
                                                                      : responsibilityButton.hovered ? Theme.NCTheme.surfaceRaised : "transparent"
                                border.width: responsibilityButton.activeFocus || responsibilityButton.selected
                                              ? Theme.NCMetrics.focusWidth
                                              : Theme.NCMetrics.borderWidth
                                border.color: responsibilityButton.activeFocus ? Theme.NCTheme.focus
                                                                                 : responsibilityButton.selected ? Theme.NCTheme.accent
                                                                                                                 : Theme.NCTheme.borderSubtle
                            }

                            contentItem: ColumnLayout {
                                spacing: Theme.NCMetrics.space2

                                Label {
                                    objectName: "runtimeResponsibilityTitle"
                                    Layout.fillWidth: true
                                    text: String(responsibilityButton.modelData.label)
                                    color: Theme.NCTheme.text
                                    font.weight: Theme.NCTypography.semibold
                                    font.pixelSize: Theme.NCTypography.labelSize
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                }

                                Image {
                                    objectName: "runtimeResponsibilityIcon"
                                    Layout.preferredWidth: 42
                                    Layout.preferredHeight: 42
                                    Layout.alignment: Qt.AlignHCenter
                                    source: responsibilityButton.modelData.icon
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    mipmap: true
                                }

                                Label {
                                    objectName: "runtimeResponsibilityValue"
                                    Layout.fillWidth: true
                                    text: {
                                        const key = String(responsibilityButton.modelData.key)
                                        if (key === "language") return root.bridge.activeRuntimeStack[0].value
                                        if (key === "speech") return root.bridge.activeRuntimeStack[1].value
                                        if (key === "voice") return root.bridge.activeRuntimeStack[2].value
                                        if (key === "visual") return root.bridge.activeRuntimeStack[3].value
                                        if (key === "avatar") return root.bridge.sessionSetup.avatarMode
                                        if (key === "resources") return qsTr("RAM · VRAM")
                                        return qsTr("Input presets")
                                    }
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                }
                            }

                            onClicked: root.currentResponsibility = String(responsibilityButton.modelData.key)
                            TapHandler {
                                acceptedButtons: Qt.RightButton
                                onTapped: responsibilityTutorials.openFor(responsibilityButton,
                                    {workspace: "runtime", runtime_section: "runtime",
                                     runtime_responsibility: String(responsibilityButton.modelData.key)})
                            }
                        }
                    }

                    NCCard {
                        Layout.fillWidth: true
                        Layout.topMargin: Theme.NCMetrics.space12
                        title: qsTr("Active stack")
                        contentSpacing: Theme.NCMetrics.space6

                        Repeater {
                            model: root.bridge.activeRuntimeStack
                            delegate: RowLayout {
                                id: runtimeStatusRow
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space6
                                Rectangle {
                                    Layout.preferredWidth: 6
                                    Layout.preferredHeight: 6
                                    radius: 3
                                    color: Theme.NCTheme.statusColor(String(runtimeStatusRow.modelData.status))
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: String(runtimeStatusRow.modelData.value)
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }
                }

                ColumnLayout {
                    Layout.minimumWidth: 0
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: Theme.NCMetrics.space8

                    NCCard {
                        Layout.fillWidth: true
                        visible: root.sessionSetupPinned && root.currentResponsibility !== "session"
                        Layout.preferredHeight: visible ? implicitHeight : 0
                        title: qsTr("Pinned session setup")
                        description: qsTr("%1 · %2 · Stream %3")
                                     .arg(String(root.bridge.sessionSetup.inputMode || qsTr("Text only")))
                                     .arg(String(root.bridge.sessionSetup.inputRole || qsTr("User message")))
                                     .arg(Boolean(root.bridge.sessionSetup.streamMode) ? qsTr("on") : qsTr("off"))
                        contentSpacing: Theme.NCMetrics.space4

                        headerAccessory: RowLayout {
                            NCButton {
                                text: qsTr("Open setup")
                                compact: true
                                tone: "quiet"
                                toolTipText: qsTr("Open the complete Session Setup workspace")
                                onClicked: root.currentResponsibility = "session"
                            }
                            NCButton {
                                text: qsTr("Unpin")
                                compact: true
                                tone: "quiet"
                                toolTipText: qsTr("Remove Session Setup from the top of Runtime")
                                onClicked: root.sessionSetupPinned = false
                            }
                        }
                    }

                    Loader {
                        id: runtimeStack
                        objectName: "runtimeResponsibilityStack"
                        Layout.minimumWidth: 0
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        sourceComponent: root.currentResponsibility === "session" ? sessionSetup
                                         : root.currentResponsibility === "resources" ? resourcesPage
                                         : root.currentResponsibility === "language" ? providers
                                         : root.currentResponsibility === "speech" ? speechInput
                                         : root.currentResponsibility === "voice" ? speechOutput
                                         : root.currentResponsibility === "visual" ? visualReply
                                         : root.currentResponsibility === "avatar" ? avatarRuntime
                                         : providers
                    }
                }
            }
        }
    }

    Component {
        id: resourcesPage
        ResourcesWorkspace { bridge: root.bridge }
    }

    Component {
        id: providers
        RuntimeProviderWorkspace { bridge: root.bridge }
    }

    Component {
        id: sessionSetup
        SessionSetupWorkspace {
            bridge: root.bridge
            pinned: root.sessionSetupPinned
            onPinToggled: pinned => root.sessionSetupPinned = pinned
        }
    }

    Component {
        id: speechInput
        SpeechRuntimeWorkspace {
            bridge: root.bridge
            kind: "stt"
        }
    }

    Component {
        id: speechOutput
        SpeechRuntimeWorkspace {
            bridge: root.bridge
            kind: "tts"
        }
    }

    Component {
        id: visualReply
        VisualReplyRuntimeWorkspace { bridge: root.bridge }
    }

    Component {
        id: avatarRuntime
        AvatarRuntimeWorkspace { bridge: root.bridge }
    }

    Component {
        id: visionProvidersPage
        VisionProviderWorkspace { bridge: root.bridge }
    }

    Component {
        id: coreSettingsPage
        CoreSettingsWorkspace {
            bridge: root.bridge
            section: root.currentSection
        }
    }
}
