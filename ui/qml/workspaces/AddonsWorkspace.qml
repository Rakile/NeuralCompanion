pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme
import "../components/TutorialStyle.js" as TutorialStyle

Rectangle {
    id: root
    objectName: "addonsWorkspace"

    required property var bridge
    property string currentSection: "Overview"
    property string sectionOwnerId: ""
    property bool restoringSection: false
    property string searchText: ""
    property bool showOrbAdvanced: false
    property bool showRoomWorkspaceInfo: false
    property var orbSetup: ({})
    NCTutorialMenu { id: managedAddonTutorials; bridge: root.bridge }
    function refreshOrbSetup() {
        if (root.isCompanionOrbOverview() && typeof root.bridge.companionOrbWatchSetup === "function")
            root.orbSetup = root.bridge.companionOrbWatchSetup()
    }
    Timer {
        interval: 2000
        running: root.visible && root.isCompanionOrbOverview()
        triggeredOnStart: true
        repeat: true
        onTriggered: root.refreshOrbSetup()
    }
    readonly property bool isMprcWorkspace: String(root.bridge.selectedAddonId || "") === "multi_persona_roleplay_tab"
    readonly property bool isMuseTalkCreator: String(root.bridge.selectedAddonId || "") === "musetalk_preprocess_tab"
    readonly property bool isDittoCreator: String(root.bridge.selectedAddonId || "") === "ditto_preprocess_tab"
    readonly property bool isAudioStoryWorkspace: String(root.bridge.selectedAddonId || "") === "audio_story_mode_runtime"
    readonly property bool dedicatedWorkspace: [
        "core.addons",
        "core.persona",
        "core.tutorials",
        "core.speech_timing",
        "core.performance",
        "main_chat_remote_tab",
        "voice_studio_tab",
        "scenic_pack_creator_tab",
        "companion_chess_tab",
        "audio_story_mode_runtime",
        "musetalk_preprocess_tab",
        "ditto_preprocess_tab",
        "multi_persona_roleplay_tab"
    ].indexOf(String(root.bridge.selectedAddonId || "")) >= 0
    readonly property int selectedSectionCount: (root.bridge.selectedAddon.sections || []).length
    readonly property bool addonContentSearchable:
        (root.bridge.selectedAddonSettings.schema || []).length > 0
        || (root.bridge.liveAddonControls || []).length > 0

    function ensureCurrentSection() {
        const addonId = String(root.bridge.selectedAddonId || "")
        const sections = root.bridge.selectedAddon.sections || []
        const firstSection = root.isMprcWorkspace && sections.indexOf("Play") >= 0
                             ? "Play"
                             : root.isAudioStoryWorkspace && sections.indexOf("Project") >= 0
                               ? "Project"
                               : sections.length > 0 ? String(sections[0]) : qsTr("Overview")
        let wanted = root.currentSection
        if (root.sectionOwnerId !== addonId) {
            // Keep an explicit initial tab, but never carry another addon's tab over.
            const fallback = root.sectionOwnerId ? firstSection : root.currentSection
            wanted = typeof root.bridge.navigationSelection === "function"
                     ? root.bridge.navigationSelection("addon:" + addonId, fallback)
                     : fallback
        }
        let selected = firstSection
        for (let index = 0; index < sections.length; ++index) {
            if (String(sections[index]) === wanted) {
                selected = wanted
                break
            }
        }
        root.restoringSection = true
        root.sectionOwnerId = addonId
        root.currentSection = selected
        root.restoringSection = false
        root.rememberCurrentSection()
    }

    function rememberCurrentSection() {
        if (root.restoringSection || !root.sectionOwnerId
                || root.sectionOwnerId !== String(root.bridge.selectedAddonId || ""))
            return
        const sections = root.bridge.selectedAddon.sections || []
        if (sections.indexOf(root.currentSection) >= 0
                && typeof root.bridge.rememberNavigationSelection === "function")
            root.bridge.rememberNavigationSelection("addon:" + root.sectionOwnerId, root.currentSection)
    }

    onCurrentSectionChanged: rememberCurrentSection()

    function visibleAddonSchema() {
        // The native Filter and removed Bots sections hide deprecated settings.
        // Do not bring them back through schema fallback when a search has no matches.
        if (String(root.bridge.selectedAddonId || "") === "discord_voice_bridge_tab"
                && ["filter", "bots"].indexOf(String(root.currentSection || "").toLowerCase()) >= 0)
            return []
        const fields = root.bridge.selectedAddonSettings.schema || []
        const wantedSection = String(root.currentSection || "Overview").toLowerCase()
        const query = String(root.searchText || "").trim().toLowerCase()
        const matches = []
        for (let index = 0; index < fields.length; ++index) {
            const field = fields[index]
            if (String(field.section || "Overview").toLowerCase() !== wantedSection)
                continue
            const haystack = (String(field.label || "") + " " + String(field.key || "")).toLowerCase()
            if (query.length === 0 || haystack.indexOf(query) >= 0)
                matches.push(field)
        }
        return matches
    }

    function visibleLiveControls() {
        const fields = root.bridge.liveAddonControls || []
        const wantedSection = String(root.currentSection || "Overview").toLowerCase()
        const query = String(root.searchText || "").trim().toLowerCase()
        const matches = []
        for (let index = 0; index < fields.length; ++index) {
            const field = fields[index]
            if (field.presentationHidden === true)
                continue
            if (String(field.section || "Overview").toLowerCase() !== wantedSection)
                continue
            const haystack = (String(field.label || "") + " " + String(field.objectName || "")).toLowerCase()
            if (query.length === 0 || haystack.indexOf(query) >= 0)
                matches.push(field)
        }
        return matches
    }

    function isCompanionOrbOverview() {
        return String(root.bridge.selectedAddon.id || "") === "companion_orb_overlay_tab"
               && String(root.currentSection || "").toLowerCase() === "overview"
    }

    function isAIPresenceOverview() {
        return String(root.bridge.selectedAddon.id || "") === "ai_presence_mode_tab"
               && String(root.currentSection || "").toLowerCase() === "overview"
    }

    function isSpotifySenseMusicHub() {
        return String(root.bridge.selectedAddonId || "") === "spotify_sense_tab"
               && String(root.currentSection || "").toLowerCase() === "music hub"
    }

    function isDiscordModerator() {
        return String(root.bridge.selectedAddonId || "") === "discord_voice_bridge_tab"
               && String(root.currentSection || "").toLowerCase() === "moderator"
    }

    function isDiscordAccounts() {
        return String(root.bridge.selectedAddonId || "") === "discord_voice_bridge_tab"
               && String(root.currentSection || "").toLowerCase() === "discord"
    }

    function isLocalRoom() {
        return String(root.bridge.selectedAddonId || "") === "discord_voice_bridge_tab"
               && String(root.currentSection || "").toLowerCase() === "local room"
    }

    function liveControlById(controlId) {
        const fields = root.bridge.liveAddonControls || []
        for (let index = 0; index < fields.length; ++index) {
            if (String(fields[index].id || "") === String(controlId || ""))
                return fields[index]
        }
        return ({})
    }

    readonly property bool vseefaceCardsCollapsible: String(root.bridge.selectedAddon.id || "") === "vseeface_avatar_tab"
                                                    && Boolean(liveControlById("btn_vseeface_card_collapse").id)
    readonly property var vseefaceCardStates: liveControlById("btn_vseeface_card_collapse").value || ({})

    function saveVseefaceCardState(card, collapsed) {
        root.bridge.triggerLiveAddonActionWithPayload("btn_vseeface_card_collapse", {card: card, collapsed: collapsed})
    }

    function standardLiveControls() {
        const controls = root.visibleLiveControls().filter(field =>
            !root.isDiscordAccounts() || String(field.id || "") !== "discord_accounts_view")
        if (!root.isCompanionOrbOverview() && !root.isAIPresenceOverview())
            return controls
        const primaryIds = root.isCompanionOrbOverview() ? [
            "companion_orb_enabled_checkbox",
            "companion_orb_display_mode_combo",
            "companion_orb_activation_status",
            "companion_orb_show_button",
            "companion_orb_placement_mode_button",
            "companion_orb_reset_position_button"
        ] : [
            "ai_presence_summary",
            "ai_presence_status",
            "ai_presence_enabled",
            "ai_presence_display_mode",
            "ai_presence_visual_style",
            "ai_presence_show",
            "ai_presence_activate_silk_threads",
            "ai_presence_preview_fullscreen",
            "ai_presence_open_floating"
        ]
        const remaining = []
        for (let index = 0; index < controls.length; ++index) {
            if (primaryIds.indexOf(String(controls[index].id || "")) < 0)
                remaining.push(controls[index])
        }
        return remaining
    }

    function addonManagerColumn(columnIndex, columnCount) {
        const registry = root.bridge.addonRegistry || []
        const count = Math.max(1, Number(columnCount) || 1)
        const columns = []
        const weights = []
        for (let column = 0; column < count; ++column) {
            columns.push([])
            weights.push(0)
        }
        for (let index = 0; index < registry.length; ++index) {
            const category = registry[index]
            let targetColumn = 0
            for (let column = 1; column < count; ++column) {
                if (weights[column] < weights[targetColumn])
                    targetColumn = column
            }
            columns[targetColumn].push(category)
            weights[targetColumn] += (category.addons || []).length + 3
        }
        return columns[Math.max(0, Math.min(count - 1, Number(columnIndex) || 0))]
    }

    color: Theme.NCTheme.window
    radius: Theme.NCMetrics.radiusLarge
    border.color: Theme.NCTheme.borderSubtle

    onVisibleChanged: if (visible) {
        bridge.refreshAddonState()
        ensureCurrentSection()
    }

    Component.onCompleted: ensureCurrentSection()

    Connections {
        target: root.bridge

        function onAddonViewChanged() {
            root.searchText = ""
            root.ensureCurrentSection()
        }

        function onAddonsChanged() {
            root.ensureCurrentSection()
        }

        function onAddonSectionRequested(addonId, section) {
            if (String(addonId || "") !== String(root.bridge.selectedAddonId || ""))
                return
            const sections = root.bridge.selectedAddon.sections || []
            for (let index = 0; index < sections.length; ++index) {
                if (String(sections[index]) === String(section || "")) {
                    root.currentSection = String(section)
                    return
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: Theme.NCMetrics.space12

        NCSectionRail {
            objectName: "addonSectionRail"
            tutorialBridge: root.bridge
            tutorialContext: ({workspace: "addons"})
            Layout.fillHeight: true
            Layout.preferredWidth: Theme.NCMetrics.sectionRailWidth
            searchable: true
            searchPlaceholder: qsTr("Find addon")
            currentKey: root.bridge.selectedAddonId
            model: root.bridge.addonWorkspaces
            hiddenModel: root.bridge.hiddenAddonWorkspaces
            entriesHideable: true
            entriesReorderable: true
            onActivated: key => {
                root.bridge.viewAddon(key)
                root.ensureCurrentSection()
            }
            onHideRequested: key => root.bridge.hideAddonFromRail(key)
            onUnhideRequested: key => root.bridge.unhideAddonOnRail(key)
            onMoveRequested: (key, targetIndex) => root.bridge.moveAddonOnRail(key, targetIndex)
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.NCMetrics.radiusLarge
            color: Theme.NCTheme.windowRaised
            border.color: Theme.NCTheme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space16
                spacing: Theme.NCMetrics.space12

                RowLayout {
                    Layout.fillWidth: true
                    visible: !root.isMprcWorkspace && !root.isMuseTalkCreator && !root.isDittoCreator && !root.isAudioStoryWorkspace && (!root.isLocalRoom() || root.showRoomWorkspaceInfo)
                    spacing: Theme.NCMetrics.space12

                    NCSectionHeader {
                        Layout.fillWidth: true
                        title: String(root.bridge.selectedAddon.label || qsTr("Addon"))
                        description: String(root.bridge.selectedAddon.description || qsTr("Open this workspace."))
                    }

                    NCStatusChip {
                        text: Boolean(root.bridge.selectedAddon.core) ? qsTr("Core workspace") : String(root.bridge.selectedAddon.status || qsTr("Initialized"))
                        status: "active"
                    }
                }

                NCSearchField {
                    toolTipText: qsTr("Filter the controls shown in this add-on workspace by their displayed text. Clearing the search restores the full workspace.")

                    Layout.fillWidth: true
                    Layout.maximumWidth: 420
                    visible: !root.dedicatedWorkspace && root.addonContentSearchable && (!root.isLocalRoom() || root.showRoomWorkspaceInfo)
                    placeholderText: qsTr("Search within this workspace")
                    text: root.searchText
                    onTextChanged: root.searchText = text
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: !root.dedicatedWorkspace && root.selectedSectionCount > 1
                    Flickable {
                        objectName: "addonSectionTabs"
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? 42 : 0
                        visible: true
                        contentWidth: sectionRow.implicitWidth
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        RowLayout {
                            id: sectionRow
                            spacing: Theme.NCMetrics.space6

                            Repeater {
                                model: root.bridge.selectedAddon.sections || [qsTr("Overview")]

                                delegate: NCTabButton {
                                    id: sectionButton
                                    required property string modelData
                                    checked: modelData === root.currentSection
                                    text: sectionButton.modelData
                                    tutorialBridge: root.bridge
                                    tutorialContext: ({workspace: "addons", addon: String(root.bridge.selectedAddonId),
                                                       section: sectionButton.modelData})
                                    onClicked: root.currentSection = modelData
                                }
                            }
                        }
                    }
                    NCButton {
                        objectName: "localRoomWorkspaceInfoToggle"
                        visible: root.isLocalRoom(); compact: true; tone: "quiet"
                        text: root.showRoomWorkspaceInfo ? qsTr("Hide workspace info") : qsTr("Workspace info")
                        toolTipText: qsTr("Show the Discord Voice introduction and settings search. Hide them again to give the room more space.")
                        onClicked: root.showRoomWorkspaceInfo = !root.showRoomWorkspaceInfo
                    }
                }

                Loader {
                    objectName: "addonSettingsContent"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: root.bridge.selectedAddonId === "core.addons" ? addonManagerPage
                                     : root.bridge.selectedAddonId === "core.persona" ? personaPage
                                     : root.bridge.selectedAddonId === "core.tutorials" ? tutorialsPage
                                     : root.bridge.selectedAddonId === "core.speech_timing" ? timingPage
                                     : root.bridge.selectedAddonId === "core.performance" ? performancePage
                                     : root.bridge.selectedAddonId === "main_chat_remote_tab" ? mainChatRemotePage
                                     : root.bridge.selectedAddonId === "voice_studio_tab" ? voiceStudioPage
                                     : root.bridge.selectedAddonId === "scenic_pack_creator_tab" ? scenicCreatorPage
                                     : root.bridge.selectedAddonId === "companion_chess_tab" ? companionChessPage
                                     : root.isSpotifySenseMusicHub() ? spotifySenseHubPage
                                     : root.isDiscordModerator() ? discordModeratorPage
                                     : root.isLocalRoom() ? localRoomPage
                                     : root.isMuseTalkCreator ? musetalkCreatorPage
                                     : root.isDittoCreator ? dittoCreatorPage
                                     : root.isMprcWorkspace ? mprcPage
                                     : root.isAudioStoryWorkspace ? audioStoryPage
                                     : addonOverviewPage
                }
            }
        }
    }

    Component {
        id: companionChessPage
        Loader {
            Component.onCompleted: setSource(Qt.resolvedUrl("../../../addons/companion_chess/qml/ChessWorkspace.qml"),
                                             {"controller": root.bridge.chessController})
        }
    }

    Component {
        id: voiceStudioPage
        Loader {
            // Keep the optional addon's editor behind the existing native boundary.
            Component.onCompleted: setSource(Qt.resolvedUrl("../../../addons/voice_studio/qml/VoiceStudio.qml"),
                                             {"bridge": root.bridge, "currentSection": Qt.binding(() => root.currentSection)})
        }
    }

    Component {
        id: scenicCreatorPage
        Loader {
            Component.onCompleted: setSource(Qt.resolvedUrl("../../../addons/scenic_pack_creator/qml/ScenicCreator.qml"),
                                             {"bridge": root.bridge})
        }
    }

    Component {
        id: audioStoryPage
        AudioStoryWorkspace {
            bridge: root.bridge
            currentSection: root.currentSection
            onSectionRequested: section => root.currentSection = section
        }
    }

    Component {
        id: mprcPage
        MprcWorkspace {
            bridge: root.bridge
            currentSection: root.currentSection
            onSectionRequested: section => root.currentSection = section
        }
    }

    Component {
        id: dittoCreatorPage
        Loader {
            // The optional addon owns its wizard; keep the existing native command boundary.
            Component.onCompleted: setSource(Qt.resolvedUrl("../../../addons/ditto_preprocess/CreatorWizard.qml"), {"bridge": root.bridge})
        }
    }

    Component {
        id: musetalkCreatorPage
        MuseTalkCreatorWorkspace {
            // The host retains the model, including the painted mask, across
            // loader recreation and navigation to another addon.
            creatorModel: root.bridge.museTalkCreator
            addonControls: root.bridge.liveAddonControls
            onSettingEdited: (controlId, value) => root.bridge.setLiveAddonControl(controlId, value)
        }
    }

    Component {
        id: personaPage
        PersonaWorkspace { bridge: root.bridge }
    }

    Component {
        id: tutorialsPage
        TutorialsWorkspace { bridge: root.bridge }
    }

    Component {
        id: timingPage
        OperationsWorkspace {
            bridge: root.bridge
            mode: "timing"
        }
    }

    Component {
        id: performancePage
        OperationsWorkspace {
            bridge: root.bridge
            mode: "performance"
        }
    }

    Component {
        id: spotifySenseHubPage
        SpotifySenseHub { bridge: root.bridge }
    }

    Component {
        id: mainChatRemotePage
        MainChatRemoteWorkspace { bridge: root.bridge }
    }

    Component {
        id: discordModeratorPage
        DiscordModeratorWorkspace { bridge: root.bridge }
    }

    Component {
        id: localRoomPage
        LocalRoomWorkspace { bridge: root.bridge }
    }

    Component {
        id: addonOverviewPage
        ScrollView {
            id: addonSettingsScroll
            property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
                bridge: root.bridge
                scrollView: addonSettingsScroll
                pageKey: "addon:" + root.sectionOwnerId + ":" + root.currentSection
            }
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width
                spacing: Theme.NCMetrics.space12

                NCCard {
                    Layout.fillWidth: true
                    title: root.currentSection
                    collapsible: root.vseefaceCardsCollapsible
                    collapsed: collapsible && Boolean(root.vseefaceCardStates[root.currentSection + "::__summary"])
                    onCollapseRequested: collapse => root.saveVseefaceCardState(root.currentSection + "::__summary", collapse)
                    description: Boolean(root.bridge.selectedAddon.core)
                                 ? qsTr("Core workspace backed by the established NeuralCompanion controller.")
                                 : qsTr("Settings write through the existing addon runtime configuration. Runtime ownership remains in Python.")

                    NCCompanionOrbActivationCard {
                        Layout.fillWidth: true
                        visible: root.isCompanionOrbOverview()
                        addonLoaded: Boolean(root.bridge.selectedAddon.effectiveEnabled)
                        enabledControl: root.liveControlById("companion_orb_enabled_checkbox")
                        modeControl: root.liveControlById("companion_orb_display_mode_combo")
                        statusControl: root.liveControlById("companion_orb_activation_status")
                        showAction: root.liveControlById("companion_orb_show_button")
                        placementAction: root.liveControlById("companion_orb_placement_mode_button")
                        resetAction: root.liveControlById("companion_orb_reset_position_button")
                        onControlEdited: (controlId, value) => root.bridge.setLiveAddonControl(controlId, value)
                        onActionTriggered: controlId => root.bridge.triggerLiveAddonAction(controlId)
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: !Boolean(root.bridge.selectedAddon.core)
                        NCStatusChip {
                            text: Boolean(root.bridge.selectedAddon.effectiveEnabled) ? qsTr("Loaded this session") : qsTr("Not loaded")
                            status: Boolean(root.bridge.selectedAddon.effectiveEnabled) ? "active" : "disconnected"
                        }
                        Item { Layout.fillWidth: true }
                        NCSwitch {
                            toolTipText: qsTr("Activate or deactivate this contribution using the add-on's live control. Availability depends on the add-on's current runtime state.")

                            visible: Boolean(root.bridge.selectedAddon.contributionCheckable)
                            text: checked ? qsTr("Feature active") : qsTr("Feature inactive")
                            checked: Boolean(root.bridge.selectedAddon.contributionEnabled)
                            onClicked: root.bridge.setAddonContributionEnabled(
                                String(root.bridge.selectedAddon.id),
                                checked
                            )
                        }
                        NCSwitch {
                            toolTipText: qsTr("Choose whether this add-on loads when NC next starts. Changing this switch does not unload an already running add-on; restart NC to apply startup loading changes.")

                            text: checked ? qsTr("Enabled after restart") : qsTr("Disabled after restart")
                            checked: Boolean(root.bridge.selectedAddon.enabled)
                            onClicked: root.bridge.setAddonEnabled(String(root.bridge.selectedAddon.addonId), checked)
                        }
                    }

                    NCButton {
                        visible: String(root.bridge.selectedAddonId || "") === "spotify_sense_tab"
                        text: qsTr("Open Spotify sensory settings")
                        onClicked: root.bridge.viewRuntimeProviderSettings("vision", "spotify_sense")
                    }

                    NCSettingsGroup {
                        Layout.fillWidth: true
                        visible: root.visibleLiveControls().length === 0 && root.visibleAddonSchema().length > 0
                        title: qsTr("%1 settings").arg(root.currentSection)
                        description: root.searchText.length > 0
                                     ? qsTr("Filtered by “%1”.").arg(root.searchText)
                                     : qsTr("Saved through the normal NeuralCompanion session configuration.")
                        schema: root.visibleAddonSchema()
                        values: root.bridge.selectedAddonSettings.values || ({})
                        onSettingEdited: (key, value) => root.bridge.setSelectedAddonSetting(key, value)
                    }

                    NCDiscordBotAccounts {
                        Layout.fillWidth: true
                        visible: root.isDiscordAccounts()
                                 && String(root.liveControlById("discord_accounts_view").id || "") === "discord_accounts_view"
                        bridge: root.bridge
                        control: root.liveControlById("discord_accounts_view")
                    }

                    NCOrbWatchSetupCard {
                        Layout.fillWidth: true
                        visible: root.isCompanionOrbOverview()
                        setupState: root.orbSetup
                        draft: String(root.bridge.orbWatchDraft || "")
                        onDraftEdited: text => root.bridge.setOrbWatchDraft(text)
                        onStartOrb: { root.bridge.triggerOrbWatchAction("companion_orb_show_button", {}); root.refreshOrbSetup() }
                        onChooseTarget: root.bridge.triggerOrbWatchAction("companion_orb_show_button", {})
                        onEnableAddon: root.bridge.setAddonEnabled("nc.companion_orb_overlay", true)
                        onInitializeRuntime: root.bridge.initializeSystem()
                        onConfigureModel: root.bridge.viewRuntimeProviderSettings("vision", "companion_orb_target")
                        onOpenSettings: root.bridge.viewRuntimeProviderSettings("vision", "companion_orb_target")
                        onScopeEdited: mode => { root.bridge.setOrbCaptureScope(mode); root.refreshOrbSetup() }
                        onConfirmSetup: key => { root.bridge.applyOrbWatchSetup(key); root.refreshOrbSetup() }
                        onSubmitWatch: text => { root.bridge.submitOrbWatchRequest(text); root.refreshOrbSetup() }
                    }

                    NCOrbWatchPanel {
                        Layout.fillWidth: true
                        visible: root.isCompanionOrbOverview()
                        readRows: () => root.bridge.companionOrbWatchRows()
                        onActionWithPayload: (controlId, payload) => {
                            root.bridge.triggerOrbWatchAction(controlId, payload)
                            refreshWatch()
                            root.refreshOrbSetup()
                        }
                    }

                    NCButton {
                        visible: root.isCompanionOrbOverview()
                        text: root.showOrbAdvanced ? qsTr("Hide advanced Orb controls") : qsTr("Advanced Orb controls")
                        onClicked: root.showOrbAdvanced = !root.showOrbAdvanced
                    }

                    NCAIPresenceActivationCard {
                        Layout.fillWidth: true
                        visible: root.isAIPresenceOverview()
                        addonLoaded: Boolean(root.bridge.selectedAddon.effectiveEnabled)
                        enabledControl: root.liveControlById("ai_presence_enabled")
                        modeControl: root.liveControlById("ai_presence_display_mode")
                        styleControl: root.liveControlById("ai_presence_visual_style")
                        statusControl: root.liveControlById("ai_presence_status")
                        showAction: root.liveControlById("ai_presence_show")
                        silkAction: root.liveControlById("ai_presence_activate_silk_threads")
                        fullscreenAction: root.liveControlById("ai_presence_preview_fullscreen")
                        floatingAction: root.liveControlById("ai_presence_open_floating")
                        onControlEdited: (controlId, value) => root.bridge.setLiveAddonControl(controlId, value)
                        onActionTriggered: controlId => root.bridge.triggerLiveAddonAction(controlId)
                    }

                    NCWebSearchOverview {
                        Layout.fillWidth: true
                        visible: String(root.bridge.selectedAddon.id || "") === "web_intelligence_tab"
                                 && root.currentSection === "Overview"
                        controls: visible ? root.standardLiveControls() : []
                        layoutController: root.bridge.uiReviewNotes
                        onControlEdited: (controlId, value) => root.bridge.setLiveAddonControl(controlId, value)
                        onActionTriggered: controlId => root.bridge.triggerLiveAddonAction(controlId)
                        onRefreshRequested: root.bridge.refreshLiveAddonControls()
                    }

                    NCLiveControlsGroup {
                        Layout.fillWidth: true
                        visible: root.standardLiveControls().length > 0
                                 && !(String(root.bridge.selectedAddon.id || "") === "web_intelligence_tab"
                                      && root.currentSection === "Overview")
                                 && (!root.isCompanionOrbOverview() || root.showOrbAdvanced || root.searchText.length > 0)
                        title: qsTr("%1 controls").arg(root.currentSection)
                        description: qsTr("These controls operate the already-initialized addon controller used by the current NC runtime.")
                        controls: (String(root.bridge.selectedAddon.id || "") === "web_intelligence_tab"
                                   && root.currentSection === "Overview") ? [] : root.standardLiveControls()
                        legacyPlacement: true
                        layoutController: root.bridge.uiReviewNotes
                        layoutSurfaceId: String(root.bridge.selectedAddon.id || "")
                        layoutSection: root.currentSection
                        cardsCollapsible: root.vseefaceCardsCollapsible
                        cardCollapseState: root.vseefaceCardStates
                        onCardCollapseEdited: (card, collapsed) => root.saveVseefaceCardState(card, collapsed)
                        onControlEdited: (controlId, value) => root.bridge.setLiveAddonControl(controlId, value)
                        onControlPreviewed: (controlId, value) => root.bridge.previewLiveAddonControl(controlId, value)
                        onActionTriggered: controlId => root.bridge.triggerLiveAddonAction(controlId)
                        onActionWithPayload: (controlId, payload) => root.bridge.triggerLiveAddonActionWithPayload(controlId, payload)
                        onRefreshRequested: root.bridge.refreshLiveAddonControls()
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        visible: root.visibleAddonSchema().length === 0
                                 && root.standardLiveControls().length === 0
                                 && !root.isCompanionOrbOverview()
                                 && !root.isAIPresenceOverview()
                                 && !(root.isDiscordAccounts() && root.liveControlById("discord_accounts_view").id)
                        columns: width >= 760 ? 2 : 1
                        columnSpacing: Theme.NCMetrics.space12
                        rowSpacing: Theme.NCMetrics.space12

                        NCCard {
                            Layout.fillWidth: true
                            title: qsTr("Runtime ownership")
                            description: qsTr("Initialized by the existing addon manager. No model, worker, or audio behavior is duplicated in QML.")
                            NCStatusChip { text: qsTr("Connected to current runtime"); status: "connected" }
                        }

                        NCCard {
                            Layout.fillWidth: true
                            title: qsTr("No editable fields in this section")
                            description: qsTr("This section is action/status oriented, or its addon does not declare session defaults. Its established controller stays active.")
                            NCStatusChip { text: qsTr("Runtime contract available"); status: "info" }
                        }
                    }
                }

            }
        }
    }

    Component {
        id: addonManagerPage
        ScrollView {
            id: addonManagerScroll
            property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
                bridge: root.bridge
                scrollView: addonManagerScroll
                pageKey: "addon:core.addons"
            }
            clip: true
            contentWidth: availableWidth
            RowLayout {
                id: addonManagerColumns
                width: parent.width
                spacing: Theme.NCMetrics.space12
                readonly property int columnCount: width >= 940 ? 3 : width >= 620 ? 2 : 1

                Repeater {
                    model: addonManagerColumns.columnCount

                    delegate: ColumnLayout {
                        id: addonManagerColumn
                        required property int index
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        spacing: Theme.NCMetrics.space12

                        Repeater {
                            model: root.addonManagerColumn(
                                addonManagerColumn.index,
                                addonManagerColumns.columnCount
                            )

                            delegate: NCCard {
                                id: addonCard
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignTop
                                title: String(modelData.label || modelData.id || qsTr("Addon group"))
                                description: qsTr("%1 installed addons").arg((modelData.addons || []).length)
                                NCSwitch {
                                    toolTipText: qsTr("Enable or disable this add-on category in the manager. Category controls affect the contained add-ons; review their individual startup state before restarting NC.")

                                    Layout.fillWidth: true
                                    text: Boolean(addonCard.modelData.enabled) ? qsTr("Category enabled") : qsTr("Category disabled")
                                    checked: Boolean(addonCard.modelData.enabled)
                                    onClicked: root.bridge.setAddonCategoryEnabled(String(addonCard.modelData.id), checked)
                                }

                                Repeater {
                                    model: addonCard.modelData.addons || []
                                    delegate: Item {
                                        id: managedAddonEntry
                                        required property var modelData
                                        Layout.fillWidth: true
                                        implicitHeight: managedAddonRow.implicitHeight
                                        NCTutorialMarker { bridge: root.bridge; context: ({owner_addon: String(managedAddonEntry.modelData.id)}) }
                                        RowLayout {
                                        id: managedAddonRow
                                        property var modelData: managedAddonEntry.modelData
                                        anchors.fill: parent
                                        objectName: "managedAddon_" + String(modelData.id || "")
                                        spacing: Theme.NCMetrics.space8

                                        TapHandler {
                                            acceptedButtons: Qt.RightButton
                                            onTapped: managedAddonTutorials.openFor(managedAddonRow,
                                                {owner_addon: String(managedAddonRow.modelData.id)})
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 0
                                            Label {
                                                Layout.fillWidth: true
                                                text: String(managedAddonRow.modelData.name || managedAddonRow.modelData.id)
                                                color: Theme.NCTheme.text
                                                font.pixelSize: Theme.NCTypography.labelSize
                                                elide: Text.ElideRight
                                            }
                                            Label {
                                                Layout.fillWidth: true
                                                text: String(managedAddonRow.modelData.state || qsTr("Not loaded"))
                                                color: Theme.NCTheme.textMuted
                                                font.pixelSize: Theme.NCTypography.microSize
                                                elide: Text.ElideRight
                                            }
                                        }
                                        NCSwitch {
                                            toolTipText: qsTr("Choose whether this add-on is enabled for the next NC startup. Already initialized add-ons keep their current session state until restart.")

                                            text: ""
                                            checked: Boolean(managedAddonRow.modelData.enabled)
                                            onClicked: root.bridge.setAddonEnabled(String(managedAddonRow.modelData.id), checked)
                                            Accessible.name: qsTr("Enable %1 after restart").arg(String(managedAddonRow.modelData.name))
                                        }
                                        NCButton {
                                            text: qsTr("Tutorial")
                                            tutorialText: true
                                            visible: TutorialStyle.showButtons(root.bridge)
                                            compact: true
                                            tone: "quiet"
                                            onClicked: managedAddonTutorials.openFor(managedAddonRow,
                                                {owner_addon: String(managedAddonRow.modelData.id)}, false)
                                        }
                                    }
                                    }
                                }
                            }
                        }

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                        }
                    }
                }
            }
        }
    }
}
