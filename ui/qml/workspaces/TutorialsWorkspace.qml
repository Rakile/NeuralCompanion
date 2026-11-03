pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Rectangle {
    id: root
    property bool tutorialText: false
    objectName: "tutorialsWorkspace"

    required property var bridge
    property var selectedTutorial: ({})
    property string selectedCategory: ""
    property alias searchText: tutorialSearch.text
    property bool browserReady: false
    property string audience: "desktop"
    readonly property var activeGuide: root.bridge.tutorialState || ({})
    readonly property bool remoteReading: audience === "remote" && activeGuide.active === true
        && activeGuide.audience === "remote" && activeGuide.id === selectedTutorial.id
    readonly property var browserContext: root.bridge.tutorialBrowserContext || ({})
    readonly property bool contextFiltered: audience === "desktop" && Object.keys(browserContext).length > 0
    readonly property var catalog: contextFiltered ? (root.bridge.tutorialBrowserCatalog || [])
        : (root.bridge.tutorialCatalog || []).filter(g => !g.hidden && (g.audience || "desktop") === audience)
    readonly property string categoryMemoryKey: audience === "remote" ? "tutorials:remote-category" : "tutorials:category"
    onAudienceChanged: {
        searchText = ""
        if (browserReady && typeof bridge.rememberNavigationSelection === "function")
            bridge.rememberNavigationSelection("tutorials:audience", audience)
        const saved = typeof bridge.navigationSelection === "function" ? bridge.navigationSelection(categoryMemoryKey, "") : ""
        selectedCategory = root.contextFiltered ? "" : (categoryChoices.some(c => c.value === saved) ? saved : "")
        if (browserReady) ensureTutorialSelection()
    }
    readonly property var categoryChoices: {
        const preferred = ["Getting started", "Conversation", "Visual Reply", "Avatar Preview", "Chat & Memory", "Personas & Voices",
                           "Stories & Group Chats", "Avatars & Images",
                           "Sensors & Awareness", "Connections & Tools", "Workflows"]
        const counts = {}
        for (const guide of root.catalog) {
            const name = String(guide.category || qsTr("Other"))
            counts[name] = (counts[name] || 0) + 1
        }
        const names = preferred.filter(name => counts[name])
        names.push(...Object.keys(counts).filter(name => preferred.indexOf(name) < 0).sort())
        return [{value: "", label: qsTr("All tutorials (%1)").arg(root.catalog.length)}]
            .concat(names.map(name => ({value: name, label: name + " (" + counts[name] + ")"})))
    }
    readonly property var filteredTutorials: {
        const query = String(root.searchText || "").trim().toLowerCase()
        return root.catalog.filter(guide => {
            if (root.selectedCategory && String(guide.category || qsTr("Other")) !== root.selectedCategory)
                return false
            const searchable = [guide.display_title || guide.title, guide.description, guide.id, guide.category]
                .join(" ").toLowerCase()
            return !query || searchable.indexOf(query) >= 0
        })
    }

    function ensureTutorialSelection() {
        const available = root.filteredTutorials
        root.selectedTutorial = available.find(guide => guide.id === root.selectedTutorial.id)
                                || available[0] || ({})
    }

    function selectCategory(category) {
        root.searchText = ""
        root.selectedCategory = category
    }

    onSelectedCategoryChanged: {
        if (root.browserReady && !root.contextFiltered && typeof root.bridge.rememberNavigationSelection === "function")
            root.bridge.rememberNavigationSelection(root.categoryMemoryKey, root.selectedCategory)
        if (root.browserReady)
            tutorialList.positionViewAtBeginning()
    }
    onSearchTextChanged: {
        // Searching is local and visibly switches to the complete catalog.
        if (String(root.searchText).trim())
            root.selectedCategory = ""
        if (String(root.searchText).trim() && root.contextFiltered)
            root.bridge.clearTutorialBrowserContext()
        if (root.browserReady)
            tutorialList.positionViewAtBeginning()
    }
    onFilteredTutorialsChanged: if (root.browserReady) root.ensureTutorialSelection()
    onCatalogChanged: {
        if (root.browserReady && root.contextFiltered
                && !root.categoryChoices.some(choice => choice.value === root.selectedCategory))
            root.selectedCategory = ""
    }
    onBrowserContextChanged: {
        if (root.browserReady && root.contextFiltered) {
            root.selectedCategory = ""
            root.searchText = ""
        }
    }
    Component.onCompleted: {
        const savedAudience = typeof root.bridge.navigationSelection === "function"
            ? root.bridge.navigationSelection("tutorials:audience", "desktop") : "desktop"
        root.audience = savedAudience === "remote" || root.activeGuide.audience === "remote" ? "remote" : "desktop"
        const fallback = root.categoryChoices.some(choice => choice.value === "Getting started")
                         ? "Getting started" : String((root.categoryChoices[1] || {}).value || "")
        const saved = typeof root.bridge.navigationSelection === "function"
                      ? root.bridge.navigationSelection(root.categoryMemoryKey, fallback) : fallback
        root.selectedCategory = root.contextFiltered ? ""
            : (root.categoryChoices.some(choice => choice.value === saved) ? saved : fallback)
        root.browserReady = true
        root.ensureTutorialSelection()
        if (root.activeGuide.active && root.activeGuide.audience === "remote")
            root.selectedTutorial = root.catalog.find(g => g.id === root.activeGuide.id) || root.selectedTutorial
    }
    onVisibleChanged: if (visible && root.browserReady) root.ensureTutorialSelection()
    color: "transparent"

    RowLayout {
        anchors.fill: parent
        spacing: Theme.NCMetrics.space12

        NCCard { tutorialText: false
            Layout.preferredWidth: Math.min(380, Math.max(300, root.width * 0.34))
            Layout.fillHeight: true
            title: qsTr("Interactive guides")
            description: qsTr("Choose a course or chapter. Yellow outlines show the current tutorial location.")

            NCSwitch { tutorialText: false
                objectName: "tutorialShowButtons"
                text: qsTr("Show Tutorial buttons")
                checked: !root.bridge.tutorialLaunchers || root.bridge.tutorialLaunchers.buttons !== false
                onToggled: root.bridge.setTutorialLauncherVisible("buttons", checked)
            }
            NCSwitch { tutorialText: false
                objectName: "tutorialShowContextMenus"
                text: qsTr("Show tutorials in right-click menus")
                checked: !root.bridge.tutorialLaunchers || root.bridge.tutorialLaunchers.context !== false
                onToggled: root.bridge.setTutorialLauncherVisible("context", checked)
            }

            NCButton { tutorialText: false
                objectName: "tutorialClearContextFilter"
                Layout.fillWidth: true
                visible: root.contextFiltered
                text: qsTr("Show all desktop guides")
                onClicked: {
                    root.selectedCategory = ""
                    root.searchText = ""
                    root.bridge.clearTutorialBrowserContext()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                NCButton { tutorialText: false; text: qsTr("NC Desktop"); Layout.fillWidth: true; tone: root.audience === "desktop" ? "primary" : "secondary"; onClicked: root.audience = "desktop" }
                NCButton { tutorialText: false; objectName: "remoteTutorialTab"; text: qsTr("NC Remote app"); Layout.fillWidth: true; tone: root.audience === "remote" ? "primary" : "secondary"; onClicked: root.audience = "remote" }
            }

            NCComboBox { tutorialText: false
                toolTipText: qsTr("Filter the tutorial list by topic category. Selecting a category does not start or reset a tutorial.")

                id: tutorialCategory
                objectName: "tutorialCategorySelector"
                Layout.fillWidth: true
                label: qsTr("Tutorial category")
                model: root.categoryChoices
                textRole: "label"
                valueRole: "value"
                currentIndex: Math.max(0, root.categoryChoices.findIndex(choice => choice.value === root.selectedCategory))
                onActivated: index => root.selectCategory(String(root.categoryChoices[index].value))
            }

            RowLayout {
                Layout.fillWidth: true
                NCTextField { tutorialText: false
                    toolTipText: qsTr("Search tutorial names and descriptions. This filters the list without changing tutorial progress.")

                    id: tutorialSearch
                    objectName: "tutorialSearchField"
                    Layout.fillWidth: true
                    label: qsTr("Search all tutorials")
                    placeholderText: qsTr("Search all tutorials…")
                }
                NCButton { tutorialText: false
                    objectName: "tutorialClearSearchButton"
                    text: qsTr("Clear")
                    compact: true
                    visible: root.searchText.length > 0
                    onClicked: root.searchText = ""
                }
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("%1 of %2 guides").arg(root.filteredTutorials.length).arg(root.catalog.length)
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.microSize
            }

            ListView {
                id: tutorialList
                objectName: "tutorialCatalogList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: Theme.NCMetrics.space6
                model: root.filteredTutorials

                delegate: Button {
                    id: tutorialButton
                    required property var modelData
                    objectName: "tutorialGuide_" + String(modelData.id)
                    width: tutorialList.width
                    implicitHeight: 104
                    hoverEnabled: true
                    checked: String(root.selectedTutorial.id || "") === String(modelData.id)
                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusMedium
                        color: tutorialButton.checked ? Theme.NCTheme.surfaceSelected
                                                      : tutorialButton.hovered ? Theme.NCTheme.surfaceRaised
                                                                               : Theme.NCTheme.windowRaised
                        border.width: tutorialButton.activeFocus || tutorialButton.checked
                                      ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                        border.color: tutorialButton.activeFocus ? Theme.NCTheme.focus
                                                                 : tutorialButton.checked ? Theme.NCTheme.accent
                                                                                          : Theme.NCTheme.border
                    }
                    contentItem: ColumnLayout {
                        spacing: Theme.NCMetrics.space4
                        Label {
                            Layout.fillWidth: true
                            text: String(tutorialButton.modelData.display_title || tutorialButton.modelData.title || tutorialButton.modelData.id)
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.labelSize
                            font.weight: Theme.NCTypography.medium
                            elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true
                            text: String(tutorialButton.modelData.description || "")
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.microSize
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space6
                            Label {
                                text: qsTr("%1 steps").arg(Number(tutorialButton.modelData.step_count || 0))
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.microSize
                            }
                            Label {
                                text: qsTr("About %1 min").arg(Number(tutorialButton.modelData.estimated_minutes || 2))
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.microSize
                            }
                            Item { Layout.fillWidth: true }
                            Label {
                                text: String(tutorialButton.modelData.category || "")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.microSize
                                elide: Text.ElideRight
                            }
                        }
                    }
                    onClicked: root.selectedTutorial = modelData
                }
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            }
        }

        NCCard { tutorialText: false
            id: tutorialDetailCard
            visible: !root.remoteReading
            objectName: "tutorialDetailCard"
            Layout.fillWidth: true
            Layout.fillHeight: true
            elevated: true
            title: String(root.selectedTutorial.display_title || root.selectedTutorial.title || qsTr("Choose a guide"))
            description: String(root.selectedTutorial.description || qsTr("Select a tutorial to review its purpose and start the guided walkthrough."))

            Label {
                Layout.fillWidth: true
                visible: root.audience === "remote" && !!root.selectedTutorial.id
                text: {
                    const refresh = root.activeGuide
                    const saved = typeof root.bridge.navigationSelection === "function"
                        ? root.bridge.navigationSelection("tutorials:progress:" + root.selectedTutorial.id, "0") : "0"
                    return saved === "done" ? qsTr("Reading completed • Open again to review")
                        : qsTr("Resume at step %1 • Reading progress only").arg(Number(saved || 0) + 1)
                }
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.WordWrap
            }

            NCEmptyState { tutorialText: false
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: !root.selectedTutorial.id
                glyph: "GUIDE"
                title: root.catalog.length > 0 ? qsTr("No matching guides") : qsTr("Learn inside NeuralCompanion")
                description: root.catalog.length > 0
                             ? qsTr("Try another category or clear the search.")
                             : qsTr("Guides open the relevant workspace, highlight controls, and can narrate each step.")
            }

            RowLayout {
                id: tutorialSummaryActions
                objectName: "tutorialSummaryActions"
                Layout.fillWidth: true
                visible: Boolean(root.selectedTutorial.id)
                spacing: Theme.NCMetrics.space6
                NCStatusChip { tutorialText: false
                    text: qsTr("%1 steps").arg(Number(root.selectedTutorial.step_count || 0))
                    status: "info"
                }
                NCStatusChip { tutorialText: false
                    text: qsTr("About %1 min").arg(Number(root.selectedTutorial.estimated_minutes || 2))
                    status: "info"
                }
                NCStatusChip { tutorialText: false
                    text: String(root.selectedTutorial.primary_destination || qsTr("Guided navigation"))
                    status: "active"
                }
                NCStatusChip { tutorialText: false
                    text: qsTr("Read aloud available")
                    status: "active"
                }
                Item { Layout.fillWidth: true }
                NCButton { tutorialText: false
                    text: qsTr("Getting Started")
                    compact: true
                    toolTipText: qsTr("Open the NeuralCompanion Welcome Hub")
                    onClicked: root.bridge.requestWelcomeHub()
                }
                NCButton { tutorialText: false
                    id: narrationInfoButton
                    objectName: "tutorialNarrationInfoButton"
                    text: qsTr("Narration info")
                    compact: true
                    tone: "secondary"
                    toolTipText: qsTr("Select Chatterbox, use the large top-right power button OFF → ON, and wait for it to load before using higher-quality narration.")
                    onClicked: narrationInfoDialog.open()
                }
                NCButton { tutorialText: false
                    id: startButton
                    objectName: "tutorialStartButton"
                    property bool attentionPulse: true
                    visible: Boolean(root.selectedTutorial.id)
                    text: root.audience === "remote" ? qsTr("Open walkthrough") : qsTr("Start guide")
                    tone: "primary"
                    onClicked: root.bridge.startTutorial(String(root.selectedTutorial.id))

                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.surfaceRaised
                        border.width: startButton.activeFocus
                                      ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                        border.color: startButton.activeFocus ? Theme.NCTheme.focus
                                                              : Qt.darker(color, 1.35)

                    }
                }
            }

            Label {
                objectName: "tutorialCatalogNarrationHelp"
                Layout.fillWidth: true
                visible: Boolean(root.selectedTutorial.id)
                text: qsTr("For higher-quality narration, select Chatterbox in Runtime → Text-to-speech, use the large top-right power button OFF → ON, and wait for it to load. Otherwise NC tries Windows TTS. Reading guides does not require initialization.")
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.WordWrap
            }

            ScrollView {
                id: tutorialDetailScroll
                objectName: "tutorialDetailScroll"
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: Boolean(root.selectedTutorial.id)
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    width: tutorialDetailScroll.availableWidth
                    spacing: Theme.NCMetrics.space16

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: outcomesLayout.implicitHeight + Theme.NCMetrics.space24
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.windowRaised
                        border.color: Theme.NCTheme.borderSubtle

                        ColumnLayout {
                            id: outcomesLayout
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space12
                            spacing: Theme.NCMetrics.space8
                            Label {
                                text: qsTr("What you will learn")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.labelSize
                                font.weight: Theme.NCTypography.semibold
                            }
                            Repeater {
                                model: root.selectedTutorial.learning_outcomes || []
                                delegate: RowLayout {
                                    id: outcomeRow
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: Theme.NCMetrics.space8
                                    Label {
                                        text: "✓"
                                        color: Theme.NCTheme.textSecondary
                                        font.weight: Theme.NCTypography.semibold
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: String(outcomeRow.modelData)
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.bodySize
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: readinessLayout.implicitHeight + Theme.NCMetrics.space24
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.windowRaised
                        border.color: Theme.NCTheme.borderSubtle

                        ColumnLayout {
                            id: readinessLayout
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space12
                            spacing: Theme.NCMetrics.space6
                            Label {
                                text: qsTr("Before you start")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.labelSize
                                font.weight: Theme.NCTypography.semibold
                            }
                            Label {
                                Layout.fillWidth: true
                                text: String(root.selectedTutorial.before_you_start || "")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.bodySize
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space8
                        Label {
                            text: qsTr("Guide outline")
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.labelSize
                            font.weight: Theme.NCTypography.semibold
                        }
                        Repeater {
                            model: root.selectedTutorial.step_preview || []
                            delegate: Rectangle {
                                id: stepCard
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: stepRow.implicitHeight + Theme.NCMetrics.space16
                                radius: Theme.NCMetrics.radiusMedium
                                color: Theme.NCTheme.windowRaised
                                border.color: Theme.NCTheme.borderSubtle
                                RowLayout {
                                    id: stepRow
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space8
                                    spacing: Theme.NCMetrics.space8
                                    Rectangle {
                                        Layout.preferredWidth: 26
                                        Layout.preferredHeight: 26
                                        radius: 13
                                        color: Theme.NCTheme.surfaceSelected
                                        Label {
                                            anchors.centerIn: parent
                                            text: String(stepCard.modelData.number || "")
                                            color: Theme.NCTheme.textSecondary
                                            font.pixelSize: Theme.NCTypography.microSize
                                            font.weight: Theme.NCTypography.semibold
                                        }
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: String(stepCard.modelData.title || "")
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.bodySize
                                        wrapMode: Text.WordWrap
                                    }
                                    Label {
                                        Layout.maximumWidth: 180
                                        text: String(stepCard.modelData.location || "")
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.microSize
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                visible: Boolean(root.selectedTutorial.id)
                text: root.audience === "remote" ? qsTr("Read on desktop and practise on your phone. Your place in each walkthrough is remembered. No phone connection is needed to read.") : qsTr("The guide opens each destination and highlights the relevant control. Your Read aloud preference is remembered.")
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.microSize
                wrapMode: Text.WordWrap
            }
        }
        Loader {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.remoteReading
            active: root.remoteReading
            sourceComponent: Component { NCRemoteTutorialReader { bridge: root.bridge } }
        }
    }

    NCDialog {
        id: narrationInfoDialog
        objectName: "tutorialNarrationInfoDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Tutorial narration")
        description: qsTr("For higher-quality tutorial narration, open Runtime → Text-to-speech and select Chatterbox. Use the large top-right power button OFF → ON to initialize NC, then wait for Chatterbox to load before Hear step or Read aloud. If changing a running stack requires a restart, save your chat, use ON → OFF, wait for cleanup, then OFF → ON. Selecting a provider alone does not load it. NC tries Windows TTS if Chatterbox is unavailable or narration fails. You can always continue reading; the guide never starts or stops the engine for you.")
        acceptText: qsTr("Got it")
        rejectText: ""
    }
}
