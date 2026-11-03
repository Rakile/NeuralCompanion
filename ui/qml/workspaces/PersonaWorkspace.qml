pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../components"
import "../theme" as Theme

Rectangle {
    id: root
    objectName: "personaWorkspace"

    required property var bridge
    enabled: !Boolean(bridge.quickPersonaReorderBusy)
    property string searchText: ""
    property string selectedPromptId: ""
    property var selectedPrompt: ({})
    property int saveTargetSlot: -1
    property int newPersonaTargetSlot: -1
    property int removeTargetSlot: -1
    property int portraitTargetSlot: -1
    property string portraitTargetId: ""
    property bool portraitManageMode: false
    property string previewMood: ""
    property string portraitContextMood: ""
    property string originalPortraitMood: ""
    property string originalPortraitSource: ""
    property var deletePromptIds: []
    readonly property var tabs: [
        {key: "persona", label: qsTr("Persona")},
        {key: "voice", label: qsTr("Voice")},
        {key: "mcp", label: qsTr("MCP")},
        {key: "overrides", label: qsTr("Overrides")},
        {key: "visual", label: qsTr("Visual identity")},
        {key: "replies", label: qsTr("Visual replies")},
        {key: "library", label: qsTr("Prompt library")},
        {key: "relay", label: qsTr("Identity Relay")},
        {key: "advanced", label: qsTr("Advanced")}
    ]
    readonly property string overridePersonaId: String(bridge.activeQuickPersona.id || "")
    readonly property var overrideDrafts: personaOverridesEditor.overrideDrafts
    readonly property var overrideDraft: personaOverridesEditor.overrideDraft
    readonly property var overrideCatalog: personaOverridesEditor.overrideCatalog
    readonly property var overrideProviders: personaOverridesEditor.overrideProviders
    readonly property bool overrideDirty: personaOverridesEditor.overrideDirty
    readonly property string overrideValidation: personaOverridesEditor.overrideValidation
    function setOverride(key, value) { personaOverridesEditor.setOverride(key, value) }
    function refreshOverrideCatalog() { personaOverridesEditor.refreshOverrideCatalog() }
    function discardOverrides() { personaOverridesEditor.discardOverrides() }
    function saveOverrides() { personaOverridesEditor.saveOverrides() }

    property string selectedTab: {
        const saved = typeof bridge.navigationSelection === "function"
                      ? bridge.navigationSelection("persona:tab", "persona") : "persona"
        return tabs.some(tab => tab.key === saved) ? saved : "persona"
    }
    onSelectedTabChanged: {
        refreshOverrideCatalog()
        if (bridge && typeof bridge.rememberNavigationSelection === "function")
            bridge.rememberNavigationSelection("persona:tab", selectedTab)
    }

    readonly property var overrideTabs: [
        {key: "avatar", label: qsTr("Visual avatar tags")},
        {key: "tts", label: qsTr("TTS voice provider tags")},
        {key: "language", label: qsTr("Language model")},
        {key: "memory", label: qsTr("Conversation memory")}
    ]
    property string selectedOverrideTab: "avatar"

    function selectPrompt(record) {
        selectedPromptId = String(record.id || "")
        selectedPrompt = record
    }

    function personaVisualReferenceStrength() {
        const value = root.bridge.personaState.visualReferenceStrength
        if (value === undefined || value === null || value === "")
            return 0.75
        const numeric = Number(value)
        return Number.isFinite(numeric) ? numeric : 0.75
    }

    function personaSelfImageMode() {
        return String(root.bridge.personaState.selfImageMode || "hybrid")
    }

    function personaSceneInfluenceApplies() {
        return Number(root.bridge.activeQuickPersona.slot) >= 0
               && root.personaSelfImageMode() === "hybrid"
    }

    function personaEffectiveSceneInfluence() {
        const mode = root.personaSelfImageMode()
        if (mode === "reference")
            return 0.35
        if (mode === "prompt")
            return 0
        return root.personaVisualReferenceStrength()
    }

    function personaSceneInfluenceValueText() {
        const mode = root.personaSelfImageMode()
        if (mode === "prompt")
            return qsTr("Not used")
        if (mode === "reference")
            return qsTr("35% fixed")
        return Math.round(root.personaVisualReferenceStrength() * 100) + "%"
    }

    function personaSelfImageMethodToolTip() {
        const mode = root.personaSelfImageMode()
        if (mode === "prompt")
            return qsTr("Uses only the visual identity prompt. Best scene freedom; likeness can drift because the portrait is not attached.")
        if (mode === "reference")
            return qsTr("Uses the portrait with a fixed 35% scene influence. Best for subtle variations and mood portraits; large pose changes and props may be omitted.")
        return qsTr("Uses the identity prompt and portrait seed. Scene influence controls the balance. Recommended for actions and props.")
    }

    function personaSceneInfluenceToolTip() {
        const mode = root.personaSelfImageMode()
        if (mode === "prompt")
            return qsTr("Not used in Identity prompt only because no portrait is attached.")
        if (mode === "reference")
            return qsTr("Fixed at 35% in Portrait reference preferred to preserve the source portrait.")
        return qsTr("Controls Runware transformation: 0–30% closely copies the portrait pose and framing; 40–60% is balanced; 70–85% is recommended for actions and objects; 90–100% follows the scene most strongly and relies more on the identity prompt for likeness.")
    }

    function openPromptPreview(record) {
        selectPrompt(record)
        promptPreviewDialog.open()
    }

    function promptDeleteSelected(promptId) {
        return deletePromptIds.indexOf(String(promptId || "")) >= 0
    }

    function setPromptDeleteSelected(promptId, selected) {
        const wanted = String(promptId || "")
        const next = deletePromptIds.slice()
        const index = next.indexOf(wanted)
        if (Boolean(selected) && wanted.length && index < 0)
            next.push(wanted)
        else if (!Boolean(selected) && index >= 0)
            next.splice(index, 1)
        deletePromptIds = next
    }

    function clearPromptDeleteSelection() {
        deletePromptIds = []
    }

    function openQuickPersonaRemoval(slot) {
        removeTargetSlot = Number(slot)
        removePersonaDialog.open()
    }



    function moodAvatarUrl(mood) {
        const moodUrls = bridge.activeQuickPersona.moodAvatarUrls || ({})
        return String(moodUrls[String(mood || "")] || "")
    }

    function moodDisplayName(mood) {
        const cleaned = String(mood || "neutral").replace(/[_-]+/g, " ").trim()
        if (!cleaned.length)
            return qsTr("Neutral")
        return cleaned.charAt(0).toUpperCase() + cleaned.slice(1)
    }

    function availableMoodNames() {
        const names = ["happy", "sad", "angry", "curious"]
        const moodUrls = bridge.activeQuickPersona.moodAvatarUrls || ({})
        Object.keys(moodUrls).forEach(function(mood) {
            if (mood && names.indexOf(mood) < 0)
                names.push(mood)
        })
        return names.slice(0, 25)
    }

    function previewAvatarUrl() {
        const moodUrl = moodAvatarUrl(previewMood)
        return moodUrl.length
            ? moodUrl
            : String(bridge.activeQuickPersona.avatarUrl || "")
    }

    function previewMoodName() {
        return moodAvatarUrl(previewMood).length
            ? moodDisplayName(previewMood)
            : qsTr("Neutral")
    }

    function openPortraitPromptDialog(slot, includeMoods, selectedMood) {
        const target = Number(slot)
        if (!Number.isFinite(target) || target < 0)
            return
        portraitTargetSlot = target
        portraitTargetId = String(bridge.activeQuickPersona.id || "")
        portraitManageMode = false
        bridge.resetPersonaPortraitEditor()
        const portraitRows = bridge.personaPortraitRows(target)
        portraitEditor.loadRows(portraitRows)
        const requestedMood = String(selectedMood || "")
        if (requestedMood.length) {
            for (let index = 0; index < portraitRows.length; ++index) {
                if (String(portraitRows[index].tag || "") === requestedMood) {
                    portraitEditor.selectedIndex = index
                    break
                }
            }
        }
        portraitGenerationScope.currentIndex = 0
        bridge.resetPersonaAvatarPromptState()
        portraitPromptArea.text = String(bridge.personaAvatarPrompt(target) || "")
        portraitMoodSetCheck.checked = Boolean(includeMoods)
        portraitTransparencyCheck.checked = Boolean(
            bridge.personaAvatarTransparencyEnabled(target)
        )
        portraitPromptDialog.open()
    }

    function openPortraitEditorForMood(mood) {
        const slot = Number(root.bridge.activeQuickPersona.slot)
        if (!Number.isFinite(slot) || slot < 0)
            return
        root.openPortraitPromptDialog(slot, true, mood)
        root.portraitManageMode = true
    }

    function openSaveDialog(slot) {
        let target = Number(slot)
        const cards = bridge.quickPersonaSlots || []
        if (target < 0) {
            const active = bridge.activeQuickPersona || ({})
            target = Number(active.slot)
            if (!Number.isFinite(target) || target < 0) {
                target = cards.length ? Number(cards[0].slot)
                                      : bridge.quickPersonaPage * bridge.quickPersonaPageSize
                for (let index = 0; index < cards.length; ++index) {
                    if (Boolean(cards[index].empty)) {
                        target = Number(cards[index].slot)
                        break
                    }
                }
            }
        }
        saveTargetSlot = target
        const existing = cards.find(function(item) { return Number(item.slot) === target })
        personaNameField.text = existing && !Boolean(existing.empty)
            ? String(existing.name || "")
            : qsTr("Persona %1").arg(target + 1)
        savePromptCheck.checked = false
        generatePortraitCheck.checked = false
        generateMoodSetCheck.checked = false
        savePersonaDialog.open()
    }

    function firstUnusedPersonaSlot() {
        const used = ({})
        for (const persona of bridge.quickPersonaChoices || [])
            used[Number(persona.slot)] = true
        let slot = 0
        while (used[slot])
            ++slot
        return slot
    }

    function openNewPersonaDialog(slot) {
        newPersonaTargetSlot = Number(slot)
        newPersonaNameField.text = qsTr("New persona")
        newPersonaDialog.open()
    }

    function commitActivePersonaName() {
        const active = bridge.activeQuickPersona || ({})
        if (!active.id)
            return
        if (!bridge.renameQuickPersona(String(active.id), activePersonaNameField.text))
            activePersonaNameField.text = String(active.name || "")
    }

    function commitActivePersonaBio() {
        const active = bridge.activeQuickPersona || ({})
        if (!active.id)
            return
        if (!bridge.setQuickPersonaBio(String(active.id), activePersonaBioField.text))
            activePersonaBioField.text = String(active.short_bio || "")
    }

    function voiceIndex() {
        const options = bridge.voiceOptions || []
        const wanted = String(bridge.personaState.voicePath || "").replace(/\\/g, "/").toLowerCase()
        for (let index = 0; index < options.length; ++index) {
            if (String(options[index].value || "").replace(/\\/g, "/").toLowerCase() === wanted)
                return index
        }
        return 0
    }

    function identityRelayIndex() {
        const options = root.bridge.identityRelayState.options || []
        const wanted = String(root.bridge.identityRelayState.personaRef || "")
        for (let index = 0; index < options.length; ++index) {
            if (String(options[index].value || "") === wanted)
                return index
        }
        return 0
    }

    color: "transparent"

    Component.onCompleted: {
        root.bridge.refreshIdentityRelayState()
        root.refreshOverrideCatalog()
    }
    onVisibleChanged: {
        if (visible)
            root.bridge.refreshIdentityRelayState()
    }

    Item {
        id: shortcutsPane
        objectName: "personaShortcutPane"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        // Stay pinned, but reserve settings space in short dock panes.
        // Old collapsed shortcut heights are deliberately ignored.
        height: Math.min(quickPersonaCard.height,
                         Math.max(48, root.height - personaTabs.height
                                  - Theme.NCMetrics.space12 * 2 - 120))
        clip: true

        Flickable {
            id: quickPersonaScroll
            objectName: "personaQuickScroll"
            anchors.fill: parent
            contentWidth: width
            contentHeight: quickPersonaCard.height
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            onHeightChanged: returnToBounds()
            onContentHeightChanged: returnToBounds()
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        NCCard {
            id: quickPersonaCard
            objectName: "personaQuickCard"
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: (Boolean(root.bridge.personaAvatarGenerationState.inFlight) ? 338 : 306)
                    + (root.bridge.quickPersonaRows - 1) * 178
            elevated: true
            title: qsTr("Quick personas")
            description: qsTr("Drag to reorder; hold over an arrow to change pages. Hover a card for its short bio.")

        headerAccessory: RowLayout {
            NCButton {
                id: previousPersonaPage
                objectName: "previousQuickPersonaPage"
                text: "<"
                compact: true
                enabled: root.bridge.quickPersonaPage > 0
                Accessible.name: qsTr("Previous quick persona page")
                onClicked: root.bridge.setQuickPersonaPage(root.bridge.quickPersonaPage - 1)
            }
            Label {
                text: qsTr("Page %1 / %2").arg(root.bridge.quickPersonaPage + 1).arg(root.bridge.quickPersonaPageCount)
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
            }
            NCButton {
                id: nextPersonaPage
                objectName: "nextQuickPersonaPage"
                text: ">"
                compact: true
                enabled: root.bridge.quickPersonaPage + 1 < root.bridge.quickPersonaPageCount
                Accessible.name: qsTr("Next quick persona page")
                onClicked: root.bridge.setQuickPersonaPage(root.bridge.quickPersonaPage + 1)
            }
            NCComboBox {
                toolTipText: qsTr("Number of quick Persona card rows visible in the workspace. This changes the presentation of your library and does not remove Personas.")

                id: visiblePersonaRows
                objectName: "quickPersonaRows"
                Layout.preferredWidth: 116
                label: qsTr("Visible persona rows")
                model: [qsTr("1 row"), qsTr("2 rows"), qsTr("3 rows"), qsTr("4 rows")]
                enabled: !Boolean(root.bridge.quickPersonaRowsBusy)
                currentIndex: Math.max(0, Math.min(3, root.bridge.quickPersonaRows - 1))
                onActivated: root.bridge.setQuickPersonaRows(currentIndex + 1)
            }
            NCComboBox {
                toolTipText: qsTr("Choose how Persona portraits appear beside conversation messages. This display preference is shared with the conversation view.")

                id: avatarModeSelector
                property var modeIds: ["off", "single", "mood", "ring"]
                Layout.preferredWidth: 182
                label: qsTr("Chat avatar display")
                model: [qsTr("Avatar hidden"), qsTr("Single portrait"), qsTr("Mood portraits"), qsTr("Portrait + mood ring")]
                currentIndex: Math.max(0, modeIds.indexOf(root.bridge.conversationPersonaAvatarMode))
                onActivated: root.bridge.setConversationPersonaAvatarMode(modeIds[currentIndex])
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space8

            NCButton {
                id: choosePersonaButton
                objectName: "quickPersonaChooseButton"
                text: qsTr("Search or choose persona…")
                Layout.preferredWidth: 228
                onClicked: personaChooser.openFor(choosePersonaButton)
            }
            NCButton {
                objectName: "quickPersonaCreateButton"
                text: qsTr("+ New persona")
                tone: "primary"
                onClicked: root.openNewPersonaDialog(-1)
            }
            Item { Layout.fillWidth: true }
            Label {
                text: qsTr("No persona limit")
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
            }
        }

        GridLayout {
            id: personaCardsRow
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: 5
            columnSpacing: Theme.NCMetrics.space10
            rowSpacing: Theme.NCMetrics.space10

            property int dragSource: -1
            property string dragIdentity: ""
            property string dragName: ""
            property string dragAvatar: ""
            property bool dragCanceled: false
            readonly property int dropSlot: personaDrag.active && !dragCanceled
                                           ? slotAt(personaDrag.centroid.position) : -1

            function slotAt(point) {
                for (let i = 0; i < personaCards.count; ++i) {
                    const card = personaCards.itemAt(i)
                    if (card && point.x >= card.x && point.x < card.x + card.width
                            && point.y >= card.y && point.y < card.y + card.height)
                        return Number(card.modelData.slot)
                }
                return -1
            }

            function overArrow(button) {
                const point = mapToItem(button, personaDrag.centroid.position)
                return button.enabled && point.x >= 0 && point.x < button.width
                        && point.y >= 0 && point.y < button.height
            }

            // Keep the gesture outside delegates so changing pages cannot destroy it.
            DragHandler {
                id: personaDrag
                target: null
                acceptedButtons: Qt.LeftButton
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                cursorShape: active ? Qt.ClosedHandCursor : Qt.ArrowCursor
                onCanceled: personaCardsRow.dragCanceled = true
                onActiveChanged: {
                    if (active) {
                        personaCardsRow.dragCanceled = false
                        const slot = personaCardsRow.slotAt(centroid.pressPosition)
                        const index = slot - root.bridge.quickPersonaPage * root.bridge.quickPersonaPageSize
                        const card = index >= 0 ? personaCards.itemAt(index) : null
                        // The remove button and empty cards retain their own actions.
                        if (!card || Boolean(card.modelData.empty)
                                || (centroid.pressPosition.x >= card.x + card.width - 38
                                    && centroid.pressPosition.y < card.y + 38)) {
                            personaCardsRow.dragCanceled = true
                            return
                        }
                        personaCardsRow.dragSource = slot
                        personaCardsRow.dragIdentity = String(card.modelData.id)
                        personaCardsRow.dragName = String(card.modelData.name)
                        personaCardsRow.dragAvatar = String(card.modelData.avatarUrl || "")
                    } else {
                        const source = personaCardsRow.dragSource
                        const destination = personaCardsRow.slotAt(centroid.position)
                        const identity = personaCardsRow.dragIdentity
                        // Let canceled/grab-change signals settle before saving the drop.
                        Qt.callLater(function() {
                            if (!personaCardsRow.dragCanceled && source >= 0 && destination >= 0)
                                root.bridge.moveQuickPersona(source, destination, identity)
                            personaCardsRow.dragSource = -1
                        })
                    }
                }
            }

            Shortcut {
                sequence: "Escape"
                enabled: personaDrag.active
                onActivated: personaCardsRow.dragCanceled = true
            }

            Timer {
                interval: 650
                repeat: true
                running: personaDrag.active && !personaCardsRow.dragCanceled
                         && (personaCardsRow.overArrow(previousPersonaPage)
                             || personaCardsRow.overArrow(nextPersonaPage))
                onTriggered: {
                    const delta = personaCardsRow.overArrow(previousPersonaPage) ? -1 : 1
                    root.bridge.setQuickPersonaPage(root.bridge.quickPersonaPage + delta)
                }
            }

            Rectangle {
                parent: root
                z: 100
                visible: personaDrag.active && !personaCardsRow.dragCanceled
                         && personaCardsRow.dragSource >= 0
                readonly property point pointer: personaCardsRow.mapToItem(root, personaDrag.centroid.position)
                x: pointer.x - width / 2
                y: pointer.y - height / 2
                width: 112
                height: 112
                opacity: 0.9
                radius: Theme.NCMetrics.radiusMedium
                color: Theme.NCTheme.surfaceRaised
                border.color: Theme.NCTheme.accent
                border.width: Theme.NCMetrics.focusWidth
                Image {
                    anchors.fill: parent
                    anchors.margins: 8
                    anchors.topMargin: 28
                    source: personaCardsRow.dragAvatar
                    fillMode: Image.PreserveAspectFit
                }
                Label {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 8
                    text: personaCardsRow.dragName
                    color: Theme.NCTheme.text
                    elide: Text.ElideRight
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            Repeater {
                id: personaCards
                model: root.bridge.quickPersonaSlots

                delegate: Button {
                    id: personaCardButton
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: 128
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 168
                    hoverEnabled: true
                    flat: true
                    padding: Theme.NCMetrics.space8
                    opacity: personaDrag.active && personaCardsRow.dragSource === Number(modelData.slot) ? 0.4 : 1
                    Accessible.name: Boolean(modelData.empty)
                                     ? qsTr("Empty quick persona slot %1").arg(Number(modelData.slot) + 1)
                                     : qsTr("Use quick persona %1").arg(String(modelData.name || ""))
                    Accessible.description: (Boolean(modelData.active) ? qsTr("Active persona. ") : "")
                                            + String(modelData.short_bio || "")

                    NCToolTip {
                        visible: !Boolean(personaCardButton.modelData.empty)
                                 && String(personaCardButton.modelData.short_bio || "").length > 0
                                 && (personaCardButton.hovered || personaCardButton.activeFocus)
                        text: String(personaCardButton.modelData.short_bio || "")
                    }

                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusMedium
                        color: Boolean(personaCardButton.modelData.active) ? Theme.NCTheme.surfaceSelected
                              : personaCardButton.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.window
                        border.width: personaCardsRow.dropSlot === Number(personaCardButton.modelData.slot)
                                      || Boolean(personaCardButton.modelData.active)
                                      ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                        border.color: personaCardsRow.dropSlot === Number(personaCardButton.modelData.slot)
                                      || Boolean(personaCardButton.modelData.active)
                                      ? Theme.NCTheme.accent : Theme.NCTheme.border
                    }

                    contentItem: ColumnLayout {
                        spacing: Theme.NCMetrics.space8

                        Item {
                            id: cardNameArea
                            Layout.fillWidth: true
                            Layout.leftMargin: 26
                            Layout.rightMargin: 26
                            Layout.preferredHeight: renaming ? Theme.NCMetrics.controlHeightCompact : 24
                            property bool renaming: false

                            function finishRename(save) {
                                if (!renaming)
                                    return
                                const personaId = String(personaCardButton.modelData.id || "")
                                const name = cardRenameField.text
                                renaming = false
                                if (save)
                                    root.bridge.renameQuickPersona(personaId, name)
                            }

                            Label {
                                objectName: "quickPersonaName_" + Number(personaCardButton.modelData.slot)
                                anchors.fill: parent
                                visible: !cardNameArea.renaming
                                text: Boolean(personaCardButton.modelData.empty)
                                      ? qsTr("Empty slot") : String(personaCardButton.modelData.name || qsTr("Persona"))
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                color: Theme.NCTheme.text
                                font.pixelSize: Theme.NCTypography.labelSize
                                font.weight: Theme.NCTypography.semibold
                                elide: Text.ElideRight
                            }

                            TextField {
NCHelp { target: cardRenameField; text: qsTr("Rename this saved Persona's quick card. The name is shared wherever the Persona is used; finish editing to save it.") }


                                id: cardRenameField
                                objectName: "quickPersonaInlineRename_" + Number(personaCardButton.modelData.slot)
                                anchors.fill: parent
                                visible: cardNameArea.renaming
                                selectByMouse: true
                                color: Theme.NCTheme.text
                                font.pixelSize: Theme.NCTypography.labelSize
                                horizontalAlignment: Text.AlignHCenter
                                background: Rectangle {
                                    radius: Theme.NCMetrics.radiusSmall
                                    color: Theme.NCTheme.windowRaised
                                    border.color: Theme.NCTheme.accent
                                }
                                onEditingFinished: cardNameArea.finishRename(true)
                                Keys.onEscapePressed: cardNameArea.finishRename(false)
                            }

                            Timer {
                                id: cardNameClickTimer
                                interval: 400
                                onTriggered: root.bridge.applyQuickPersona(Number(personaCardButton.modelData.slot))
                            }
                            MouseArea {
                                anchors.fill: parent
                                visible: !cardNameArea.renaming && !Boolean(personaCardButton.modelData.empty)
                                acceptedButtons: Qt.LeftButton
                                onClicked: cardNameClickTimer.restart()
                                onDoubleClicked: {
                                    cardNameClickTimer.stop()
                                    cardNameArea.renaming = true
                                    cardRenameField.text = String(personaCardButton.modelData.name || "")
                                    cardRenameField.forceActiveFocus()
                                    cardRenameField.selectAll()
                                }
                                onPressAndHold: root.openQuickPersonaRemoval(Number(personaCardButton.modelData.slot))
                            }
                        }

                        Rectangle {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: 128
                            Layout.maximumWidth: personaCardButton.availableWidth
                            Layout.fillHeight: true
                            Layout.minimumHeight: 64
                            Layout.preferredHeight: 104
                            Layout.maximumHeight: 128
                            radius: Theme.NCMetrics.radiusMedium
                            color: Boolean(personaCardButton.modelData.empty)
                                   ? Theme.NCTheme.windowRaised : "transparent"
                            border.width: Boolean(personaCardButton.modelData.empty)
                                          ? Theme.NCMetrics.borderWidth : 0
                            border.color: Boolean(personaCardButton.modelData.active)
                                          ? Theme.NCTheme.accent : Theme.NCTheme.borderStrong
                            clip: true

                            Image {
                                anchors.fill: parent
                                anchors.margins: 0
                                source: String(personaCardButton.modelData.avatarUrl || "")
                                fillMode: Image.PreserveAspectCrop
                                visible: status === Image.Ready
                                asynchronous: true
                                cache: false
                            }

                            Label {
                                anchors.centerIn: parent
                                text: Boolean(personaCardButton.modelData.empty)
                                      ? "+" : String(personaCardButton.modelData.name || "P").slice(0, 1).toUpperCase()
                                color: Boolean(personaCardButton.modelData.empty)
                                       ? Theme.NCTheme.textMuted : Theme.NCTheme.accent
                                font.pixelSize: Boolean(personaCardButton.modelData.empty) ? 28 : 24
                                font.weight: Theme.NCTypography.semibold
                                visible: parent.children[0].status !== Image.Ready
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            visible: Boolean(personaCardButton.modelData.empty)
                            text: qsTr("Create or save")
                            horizontalAlignment: Text.AlignHCenter
                            color: Theme.NCTheme.textMuted
                            font.pixelSize: Theme.NCTypography.microSize
                            elide: Text.ElideRight
                        }
                    }

                    NCIconButton {
                        objectName: "quickPersonaRemove_"
                                    + Number(personaCardButton.modelData.slot)
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: Theme.NCMetrics.space4
                        implicitWidth: 30
                        implicitHeight: 30
                        visible: !Boolean(personaCardButton.modelData.empty)
                        glyph: "\u00D7"
                        glyphPixelSize: Theme.NCTypography.titleSize
                        toolTipText: qsTr("Remove this quick persona")
                        z: 5
                        onClicked: root.openQuickPersonaRemoval(
                                       Number(personaCardButton.modelData.slot))
                    }

                    onClicked: {
                        if (Boolean(modelData.empty))
                            root.openNewPersonaDialog(Number(modelData.slot))
                        else
                            root.bridge.applyQuickPersona(Number(modelData.slot))
                    }
                    onPressAndHold: {
                        if (!personaDrag.active && !Boolean(modelData.empty))
                            root.openQuickPersonaRemoval(Number(modelData.slot))
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: Boolean(root.bridge.personaAvatarGenerationState.inFlight)
            spacing: Theme.NCMetrics.space8
            NCProgressBar {
                Layout.fillWidth: true
                indeterminate: true
                value: 0.5
            }
            Label {
                text: String(root.bridge.personaAvatarGenerationState.message || qsTr("Generating portrait"))
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
            }
        }
    }

    }

    }

    Flow {
        id: personaTabs
        objectName: "personaTabs"
        anchors.top: shortcutsPane.bottom
        anchors.topMargin: Theme.NCMetrics.space12
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.NCMetrics.space6
        Repeater {
            model: root.tabs
            delegate: NCTabButton {
                required property var modelData
                objectName: "personaTab_" + modelData.key
                tutorialBridge: root.bridge
                tutorialContext: ({workspace: "addons", addon: "core.persona", persona_tab: String(modelData.key)})
                text: modelData.label
                checked: root.selectedTab === modelData.key
                onClicked: {
                    // Commit focus-loss editors before changing the visible category.
                    forceActiveFocus()
                    root.selectedTab = modelData.key
                }
            }
        }
    }

    Flow {
        id: overrideTabs
        objectName: "personaOverrideTabs"
        visible: root.selectedTab === "overrides"
        anchors.top: personaTabs.bottom
        anchors.topMargin: Theme.NCMetrics.space12
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.NCMetrics.space6
        Repeater {
            model: root.overrideTabs
            delegate: NCTabButton {
                required property var modelData
                objectName: "personaOverrideTab_" + modelData.key
                tutorialBridge: root.bridge
                tutorialContext: ({workspace: "addons", addon: "core.persona", persona_tab: "overrides",
                                   persona_override: String(modelData.key)})
                text: modelData.label
                checked: root.selectedOverrideTab === modelData.key
                onClicked: {
                    forceActiveFocus()
                    root.selectedOverrideTab = modelData.key
                }
            }
        }
    }

    ScrollView {
            id: personaSettingsScroll
            objectName: "personaSettingsScroll"
            property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
                bridge: root.bridge
                scrollView: personaSettingsScroll
                pageKey: "persona:settings:" + root.selectedTab
                         + (root.selectedTab === "overrides" ? ":" + root.selectedOverrideTab : "")
            }
            anchors.top: overrideTabs.visible ? overrideTabs.bottom : personaTabs.bottom
            anchors.topMargin: Theme.NCMetrics.space12
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: Theme.NCMetrics.space12

                NCCard {
                    visible: root.selectedTab === "persona"
                    Layout.fillWidth: true
                    title: qsTr("Persona name")
                    description: qsTr("Edit the name and optional card bio without changing the persona prompt or assets.")

                    NCTextField {
                        toolTipText: qsTr("Name shown for this saved Persona in quick cards and conversation messages. Finish editing to save the new name.")

                        id: activePersonaNameField
                        objectName: "activePersonaNameField"
                        Layout.fillWidth: true
                        label: qsTr("Persona name")
                        placeholderText: qsTr("Create a persona to give it a name")
                        enabled: Boolean(root.bridge.activeQuickPersona.id)
                        text: String(root.bridge.activeQuickPersona.name || "")
                        onEditingFinished: root.commitActivePersonaName()
                    }
                    NCTextField {
                        toolTipText: qsTr("Short description shown when hovering this Persona's card, up to 180 characters. This is library help, separate from the Persona's system prompt.")

                        id: activePersonaBioField
                        objectName: "activePersonaBioField"
                        Layout.fillWidth: true
                        label: qsTr("Short bio shown when a card is hovered")
                        placeholderText: qsTr("Optional, up to 180 characters")
                        maximumLength: 180
                        enabled: Boolean(root.bridge.activeQuickPersona.id)
                        text: String(root.bridge.activeQuickPersona.short_bio || "")
                        onEditingFinished: root.commitActivePersonaBio()
                    }
                }

                PersonaPromptBuilder {
                    objectName: "personaSystemPromptCard"
                    visible: root.selectedTab === "persona"
                    Layout.fillWidth: true
                    controller: root.bridge.promptBuilder
                    onSavePromptRequested: root.bridge.saveCurrentPrompt()
                    onSavePersonaRequested: root.openSaveDialog(-1)
                }

                PersonaVoice {
                    objectName: "personaVoiceCard"
                    visible: root.selectedTab === "voice"
                    Layout.fillWidth: true
                    bridge: root.bridge
                }

                Loader {
                    id: personaMcpLoader
                    Layout.fillWidth: true
                    visible: root.selectedTab === "mcp"
                    active: visible
                    source: active && root.bridge.chatMcpController
                        ? Qt.resolvedUrl("../../../addons/chat_mcp_tools/qml/PersonaMcpTools.qml") : ""
                    onLoaded: {
                        item.controller = Qt.binding(() => root.bridge.chatMcpController)
                        item.personaId = Qt.binding(() => root.overridePersonaId)
                        item.personaName = Qt.binding(() => String(root.bridge.activeQuickPersona.name || ""))
                    }
                }

                PersonaTechnicalRulesEditor {
                    objectName: "personaTechnicalRulesCard"
                    selectedKind: root.selectedOverrideTab
                    visible: root.selectedTab === "overrides" && (root.selectedOverrideTab === "avatar" || root.selectedOverrideTab === "tts")
                    Layout.fillWidth: true
                    bridge: root.bridge
                    personaId: root.overridePersonaId
                }

                NCCard {
                    objectName: "personaOverridesCard"
                    visible: root.selectedTab === "overrides" && (root.selectedOverrideTab === "language" || root.selectedOverrideTab === "memory")
                    Layout.fillWidth: true
                    title: root.selectedOverrideTab === "language" ? qsTr("Override language model") : qsTr("Override conversation memory")
                    description: qsTr("Use defaults unless this saved persona needs its own language model, conversation context, or Document Memory package and recall preference. Changes apply to new requests after saving and leave Runtime and room defaults unchanged. Inherited settings follow the conversation or room where this persona is used.")

                    PersonaOverridesEditor {
                        id: personaOverridesEditor
                        section: root.selectedOverrideTab
                        objectName: "personaOverridesEditor"
                        Layout.fillWidth: true
                        bridge: root.bridge
                        personaId: root.overridePersonaId
                    }
                }

                NCCard {
                    objectName: "personaVisualIdentityCard"
                    visible: root.selectedTab === "visual"
                    Layout.fillWidth: true
                    title: qsTr("Visual identity")
                    description: qsTr("Manage this persona's appearance in self-images and mood portraits. Choose strict continuity or let the requested scene guide their appearance.")

                    headerAccessory: NCStatusChip {
                        objectName: "personaVisualIdentityStatusChip"
                        text: Boolean(root.bridge.personaState.visualReferenceReady)
                              ? qsTr("Identity reference ready")
                              : qsTr("Prompt identity only")
                        status: Boolean(root.bridge.personaState.visualReferenceReady)
                                ? "active" : "disconnected"
                    }

                    GridLayout {
                        id: visualIdentityGrid
                        Layout.fillWidth: true
                        columns: width >= 860 ? 2 : 1
                        columnSpacing: Theme.NCMetrics.space16
                        rowSpacing: Theme.NCMetrics.space12

                        Rectangle {
                            objectName: "personaVisualIdentityPreviewRail"
                            Layout.alignment: Qt.AlignTop
                            Layout.fillWidth: visualIdentityGrid.columns === 1
                            Layout.preferredWidth: visualIdentityGrid.columns === 2 ? 240 : -1
                            Layout.preferredHeight: identityPreviewRailContent.implicitHeight
                                                    + Theme.NCMetrics.space24
                            radius: Theme.NCMetrics.radiusMedium
                            color: Theme.NCTheme.surfaceRaised
                            border.width: Theme.NCMetrics.borderWidth
                            border.color: Theme.NCTheme.border

                            ColumnLayout {
                                id: identityPreviewRailContent
                                anchors.fill: parent
                                anchors.margins: Theme.NCMetrics.space12
                                spacing: Theme.NCMetrics.space8

                            Rectangle {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.preferredWidth: 190
                                Layout.preferredHeight: 190
                                radius: Theme.NCMetrics.radiusMedium
                                color: Theme.NCTheme.surfaceRaised
                                border.width: Theme.NCMetrics.borderWidth
                                border.color: Boolean(root.bridge.personaState.visualReferenceReady)
                                              ? Theme.NCTheme.success : Theme.NCTheme.border

                                Image {
                                    id: identityPreviewImage
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space8
                                    source: root.previewAvatarUrl()
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    visible: String(source).length > 0
                                }

                                Label {
                                    anchors.centerIn: parent
                                    visible: !identityPreviewImage.visible
                                    text: qsTr("No portrait")
                                    color: Theme.NCTheme.textMuted
                                    font.pixelSize: Theme.NCTypography.captionSize
                                }
                            }

                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: qsTr("Preview: %1").arg(root.previewMoodName())
                                color: root.previewMood.length && root.moodAvatarUrl(root.previewMood).length
                                       ? Theme.NCTheme.accentSoft : Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                                font.weight: Font.DemiBold
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space6

                                Label {
                                    Layout.fillWidth: true
                                    text: qsTr("Mood portraits")
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                    font.weight: Font.DemiBold
                                }

                                NCButton {
                                    objectName: "personaMoodSetButton"
                                    text: Boolean(root.bridge.personaState.visualReferenceReady)
                                          ? qsTr("Build / refresh set")
                                          : qsTr("Build mood set")
                                    compact: true
                                    tone: "quiet"
                                    enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                             && !Boolean(root.bridge.personaAvatarGenerationState.inFlight)
                                    onClicked: root.openPortraitPromptDialog(
                                        Number(root.bridge.activeQuickPersona.slot), true
                                    )
                                }
                            }

                            GridLayout {
                                id: moodThumbnailGrid
                                objectName: "personaMoodThumbnailRow"
                                readonly property int maximumPreviewCount: 25
                                Layout.fillWidth: true
                                columns: 5
                                columnSpacing: Theme.NCMetrics.space6
                                rowSpacing: Theme.NCMetrics.space6

                                Repeater {
                                    model: root.availableMoodNames().slice(
                                               0, moodThumbnailGrid.maximumPreviewCount)
                                    delegate: Rectangle {
                                        id: moodThumbnail
                                        required property string modelData
                                        Layout.preferredWidth: 38
                                        Layout.preferredHeight: 38
                                        radius: Theme.NCMetrics.radiusSmall
                                        color: Theme.NCTheme.surfaceRaised
                                        border.width: moodHover.hovered ? 2 : Theme.NCMetrics.borderWidth
                                        border.color: moodHover.hovered
                                                      ? Theme.NCTheme.accent : Theme.NCTheme.border

                                        Image {
                                            id: moodThumbnailImage
                                            anchors.fill: parent
                                            anchors.margins: 2
                                            source: root.moodAvatarUrl(moodThumbnail.modelData)
                                            fillMode: Image.PreserveAspectFit
                                            smooth: true
                                            visible: String(source).length > 0
                                        }

                                        Label {
                                            anchors.centerIn: parent
                                            visible: !moodThumbnailImage.visible
                                            text: root.moodDisplayName(moodThumbnail.modelData).charAt(0)
                                            color: Theme.NCTheme.textMuted
                                            font.pixelSize: Theme.NCTypography.captionSize
                                        }

                                        HoverHandler {
                                            id: moodHover
                                            onHoveredChanged: {
                                                if (hovered && root.moodAvatarUrl(moodThumbnail.modelData).length)
                                                    root.previewMood = moodThumbnail.modelData
                                                else if (!hovered && root.previewMood === moodThumbnail.modelData)
                                                    root.previewMood = ""
                                            }
                                        }

                                        TapHandler {
                                            acceptedButtons: Qt.RightButton
                                            onTapped: moodThumbnailContextMenu.openFor(
                                                          moodThumbnail,
                                                          moodThumbnail.modelData)
                                        }
                                    }
                                }
                            }
                            NCButton {
                                objectName: "personaMoodEditButton"
                                Layout.fillWidth: true
                                text: qsTr("Add / edit")
                                enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                         && !Boolean(root.bridge.personaAvatarGenerationState.inFlight)
                                         && !Boolean(root.bridge.personaPortraitEditorState.inFlight)
                                onClicked: {
                                    root.openPortraitPromptDialog(Number(root.bridge.activeQuickPersona.slot), true)
                                    root.portraitManageMode = true
                                }
                            }
                        }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space10

                            Rectangle {
                                objectName: "personaVisualIdentityStep1"
                                Layout.fillWidth: true
                                Layout.preferredHeight: identityStepOneContent.implicitHeight
                                                        + Theme.NCMetrics.space24
                                radius: Theme.NCMetrics.radiusMedium
                                color: Theme.NCTheme.surfaceRaised
                                border.width: Theme.NCMetrics.borderWidth
                                border.color: Theme.NCTheme.border

                                ColumnLayout {
                                    id: identityStepOneContent
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space12
                                    spacing: Theme.NCMetrics.space8

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Theme.NCMetrics.space10

                                        Rectangle {
                                            Layout.preferredWidth: 30
                                            Layout.preferredHeight: 30
                                            radius: 15
                                            color: Theme.NCTheme.surface
                                            border.width: Theme.NCMetrics.borderWidth
                                            border.color: Theme.NCTheme.accent

                                            Label {
                                                anchors.centerIn: parent
                                                text: "1"
                                                color: Theme.NCTheme.accent
                                                font.pixelSize: Theme.NCTypography.bodySize
                                                font.weight: Font.DemiBold
                                            }
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: qsTr("Describe identity")
                                            color: Theme.NCTheme.text
                                            font.pixelSize: Theme.NCTypography.headingSize
                                            font.weight: Font.DemiBold
                                        }
                                    }

                                    NCScrollableTextArea {
                                        toolTipText: qsTr("Stable traits saved with this Persona and used in every self-image: face, apparent age, gender presentation, hair, eyes, species, palette, and art style. Put actions, props, poses, clothing changes, and backgrounds in the image request.")

                                        id: visualIdentityPrompt
                                        Layout.fillWidth: true
                                        implicitHeight: 132
                                        hoverEnabled: true
                                        label: qsTr("Visual identity prompt")
                                        placeholderText: qsTr("Apparent age, gender presentation, face, eyes, hair, species, color palette, and art style")
                                        text: String(root.bridge.personaState.visualIdentityPrompt || "")
                                        enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                        onEditingFinished: root.bridge.setPersonaField("visualIdentityPrompt", text)

                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                        text: qsTr("Always preserve these traits in self-images. Keep poses, actions, props, clothing changes, composition, and backgrounds in the scene request instead.")
                                        color: Theme.NCTheme.textMuted
                                        font.pixelSize: Theme.NCTypography.captionSize
                                    }

                                    Label {
                                        text: qsTr("Appearance freedom")
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.captionSize
                                    }
                                    NCComboBox {
                                        toolTipText: qsTr("How much generated images may vary from this Persona's visual identity.") + "\n\n"
                                                     + (currentIndex === 0
                                                        ? qsTr("Preserves the saved identity and signature styling. The scene changes only traits the request explicitly overrides.")
                                                        : qsTr("Always preserves identity and art style, while the scene may change pose, expression, clothing, props, background, composition, and framing."))

                                        id: appearanceFreedomSelector
                                        objectName: "personaAppearanceFreedom"
                                        property var freedomIds: ["strict", "flexible"]
                                        Layout.fillWidth: true
                                        label: qsTr("Appearance freedom")
                                        model: [qsTr("Strict continuity"), qsTr("Flexible appearance")]
                                        currentIndex: Math.max(0, freedomIds.indexOf(String(root.bridge.personaState.appearanceFreedom || "strict")))
                                        enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                        onActivated: root.bridge.setPersonaField("appearanceFreedom", freedomIds[currentIndex])

                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                        text: qsTr("Appearance freedom controls which saved traits the scene may change. Self-image method and Scene influence below control portrait use.")
                                        color: Theme.NCTheme.textMuted
                                        font.pixelSize: Theme.NCTypography.captionSize
                                    }
                                }
                            }

                            Rectangle {
                                objectName: "personaVisualIdentityStep2"
                                Layout.fillWidth: true
                                Layout.preferredHeight: identityStepTwoContent.implicitHeight
                                                        + Theme.NCMetrics.space24
                                radius: Theme.NCMetrics.radiusMedium
                                color: Theme.NCTheme.surfaceRaised
                                border.width: Theme.NCMetrics.borderWidth
                                border.color: Theme.NCTheme.border

                                ColumnLayout {
                                    id: identityStepTwoContent
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space12
                                    spacing: Theme.NCMetrics.space10

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Theme.NCMetrics.space10

                                        Rectangle {
                                            Layout.preferredWidth: 30
                                            Layout.preferredHeight: 30
                                            radius: 15
                                            color: Theme.NCTheme.surface
                                            border.width: Theme.NCMetrics.borderWidth
                                            border.color: Theme.NCTheme.accent

                                            Label {
                                                anchors.centerIn: parent
                                                text: "2"
                                                color: Theme.NCTheme.accent
                                                font.pixelSize: Theme.NCTypography.bodySize
                                                font.weight: Font.DemiBold
                                            }
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: qsTr("Create neutral reference")
                                            color: Theme.NCTheme.text
                                            font.pixelSize: Theme.NCTypography.headingSize
                                            font.weight: Font.DemiBold
                                        }
                                    }

                                    NCSwitch {
                                        toolTipText: qsTr("Request transparent backgrounds for generated Persona portraits where the image provider supports them. This does not remove the background from existing images or force self-image backgrounds to be transparent.")

                                        id: personaPortraitTransparencySwitch
                                        objectName: "personaPortraitTransparencySwitch"
                                        Layout.fillWidth: true
                                        text: qsTr("Transparent avatar background")
                                        checked: Boolean(root.bridge.personaState.portraitTransparencyEnabled)
                                        enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                        onClicked: root.bridge.setPersonaField(
                                            "portraitTransparencyEnabled", checked
                                        )

                                    }

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Item { Layout.fillWidth: true }
                                        NCButton {
                                            objectName: "personaVisualIdentityImportButton"
                                            text: qsTr("Import portrait")
                                            tone: "secondary"
                                            toolTipText: qsTr("Choose an existing image as this persona's neutral identity reference. It is reused by Hybrid, Reference preferred, and mood portraits.")
                                            enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                            onClicked: {
                                                avatarFileDialog.targetSlot = Number(root.bridge.activeQuickPersona.slot)
                                                avatarFileDialog.open()
                                            }
                                        }
                                        NCButton {
                                            objectName: "personaVisualIdentityPortraitButton"
                                            text: Boolean(root.bridge.personaState.visualReferenceReady)
                                                  ? qsTr("Update neutral portrait")
                                                  : qsTr("Create neutral portrait")
                                            tone: "primary"
                                            toolTipText: qsTr("Generate or replace the neutral identity portrait from the visual identity prompt. This becomes the saved reference for self-images and mood portraits.")
                                            enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                                     && !Boolean(root.bridge.personaAvatarGenerationState.inFlight)
                                            onClicked: root.openPortraitPromptDialog(
                                                Number(root.bridge.activeQuickPersona.slot), false
                                            )
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                objectName: "personaVisualIdentityStep3"
                                Layout.fillWidth: true
                                Layout.preferredHeight: identityStepThreeContent.implicitHeight
                                                        + Theme.NCMetrics.space24
                                radius: Theme.NCMetrics.radiusMedium
                                color: Theme.NCTheme.surfaceRaised
                                border.width: Theme.NCMetrics.borderWidth
                                border.color: Theme.NCTheme.border

                                ColumnLayout {
                                    id: identityStepThreeContent
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space12
                                    spacing: Theme.NCMetrics.space10

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Theme.NCMetrics.space10

                                        Rectangle {
                                            Layout.preferredWidth: 30
                                            Layout.preferredHeight: 30
                                            radius: 15
                                            color: Theme.NCTheme.surface
                                            border.width: Theme.NCMetrics.borderWidth
                                            border.color: Theme.NCTheme.accent

                                            Label {
                                                anchors.centerIn: parent
                                                text: "3"
                                                color: Theme.NCTheme.accent
                                                font.pixelSize: Theme.NCTypography.bodySize
                                                font.weight: Font.DemiBold
                                            }
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: qsTr("Configure self-images")
                                            color: Theme.NCTheme.text
                                            font.pixelSize: Theme.NCTypography.headingSize
                                            font.weight: Font.DemiBold
                                        }
                                    }

                                    GridLayout {
                                        Layout.fillWidth: true
                                        columns: width >= 620 ? 2 : 1
                                        columnSpacing: Theme.NCMetrics.space16
                                        rowSpacing: Theme.NCMetrics.space8

                                        NCComboBox {
                                            toolTipText: qsTr("Choose how the Persona's visual identity is supplied for self-images.") + "\n\n" + root.personaSelfImageMethodToolTip()

                                            id: selfImageMethodSelector
                                            property var modeIds: ["hybrid", "prompt", "reference"]
                                            Layout.fillWidth: true
                                            label: qsTr("Self-image method")
                                            model: [
                                                qsTr("Hybrid: prompt + portrait reference"),
                                                qsTr("Identity prompt only"),
                                                qsTr("Portrait reference preferred")
                                            ]
                                            currentIndex: Math.max(0, modeIds.indexOf(String(root.bridge.personaState.selfImageMode || "hybrid")))
                                            enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                            onActivated: root.bridge.setPersonaField("selfImageMode", modeIds[currentIndex])

                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: Theme.NCMetrics.space4


                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label {
                                                    Layout.fillWidth: true
                                                    text: qsTr("Scene influence")
                                                    color: Theme.NCTheme.textSecondary
                                                    font.pixelSize: Theme.NCTypography.captionSize
                                                }
                                                Label {
                                                    text: root.personaSceneInfluenceValueText()
                                                    color: Theme.NCTheme.accentSoft
                                                    font.pixelSize: Theme.NCTypography.captionSize
                                                }
                                            }
                                            NCSlider {
                                                toolTipText: qsTr("Strength of the scene's influence when the selected self-image method supports it.") + "\n\n" + root.personaSceneInfluenceToolTip()

                                                id: sceneInfluenceSlider
                                                Layout.fillWidth: true
                                                label: qsTr("Self-image scene influence")
                                                from: 0
                                                to: 1
                                                stepSize: 0.05
                                                value: root.personaEffectiveSceneInfluence()
                                                enabled: root.personaSceneInfluenceApplies()
                                                onPressedChanged: {
                                                    if (!pressed && root.personaSceneInfluenceApplies())
                                                        root.bridge.setPersonaField("visualReferenceStrength", value)
                                                }
                                            }

                                        }
                                    }

                                    NCSwitch {
                                        toolTipText: qsTr("Use the accepted neutral portrait as a reference when generating mood portraits. This helps preserve the Persona's identity across emotions; it does not regenerate existing portraits.")

                                        id: personaMoodReferenceSwitch
                                        objectName: "personaMoodReferenceSwitch"
                                        Layout.fillWidth: true
                                        text: qsTr("Use the accepted neutral portrait as the reference for every mood image")
                                        checked: Boolean(root.bridge.personaState.moodReferenceEnabled)
                                        enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                        onClicked: root.bridge.setPersonaField("moodReferenceEnabled", checked)

                                    }
                                }
                            }

                            NCInlineMessage {
                                Layout.fillWidth: true
                                tone: "info"
                                title: qsTr("One identity workflow")
                                message: qsTr("The neutral portrait is the saved identity reference. Mood portraits and self-images reuse it according to the method and Scene influence above. Normal Visual Replies remain unchanged.")
                            }
                        }
                    }
                }

                NCCard {
                    objectName: "personaVisualRepliesCard"
                    visible: root.selectedTab === "replies"
                    Layout.fillWidth: true
                    title: qsTr("Visual replies")
                    description: qsTr("Decide when this persona may create an image. Completed images always stay attached to the matching spoken assistant reply in Conversation.")

                    GridLayout {
                        id: personaVisualReplyGrid
                        Layout.fillWidth: true
                        columns: width >= 720 ? 2 : 1
                        columnSpacing: Theme.NCMetrics.space16
                        rowSpacing: Theme.NCMetrics.space10

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space6

                            Label {
                                text: qsTr("Generation behavior")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }

                            NCComboBox {
                                toolTipText: qsTr("Choose when this Persona may request a Visual Reply. The configured image provider still needs to be available; this choice is saved with the Persona.")

                                id: personaVisualReplyPolicySelector
                                property var policyIds: ["off", "requested", "spontaneous"]
                                Layout.fillWidth: true
                                label: qsTr("Visual Reply behavior")
                                model: [
                                    qsTr("Do not generate images"),
                                    qsTr("Generate when asked"),
                                    qsTr("Generate when asked or spontaneously")
                                ]
                                currentIndex: Math.max(
                                    0,
                                    policyIds.indexOf(String(root.bridge.personaState.visualReplyPolicy || "off"))
                                )
                                onActivated: root.bridge.setPersonaField(
                                    "visualReplyPolicy",
                                    policyIds[currentIndex]
                                )
                            }

                            Label {
                                Layout.fillWidth: true
                                text: String(root.bridge.personaState.visualReplyPolicy || "off") === "spontaneous"
                                      ? qsTr("The persona responds to direct image requests and may occasionally add a useful image on its own.")
                                      : String(root.bridge.personaState.visualReplyPolicy || "off") === "requested"
                                        ? qsTr("The persona generates only when you ask it to create, draw, show, or make an image.")
                                        : qsTr("The persona never adds a Visual Reply request to normal chat.")
                                color: Theme.NCTheme.textMuted
                                font.pixelSize: Theme.NCTypography.microSize
                                wrapMode: Text.Wrap
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space6

                            Label {
                                text: qsTr("Where images appear")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.captionSize
                            }

                            NCStatusChip {
                                text: Boolean(root.bridge.personaState.visualReplyEnabled)
                                      ? qsTr("Visual Reply enabled")
                                      : qsTr("Visual Reply disabled")
                                status: Boolean(root.bridge.personaState.visualReplyEnabled)
                                        ? "active" : "disconnected"
                            }

                            NCSwitch {
                                toolTipText: qsTr("Automatically show the Visual Reply display when this Persona produces an image. Turning this off keeps image generation available without automatically opening its surface.")

                                Layout.fillWidth: true
                                text: qsTr("Also auto-show the Visual Reply surface")
                                checked: Boolean(root.bridge.personaState.visualReplyAutoShow)
                                onClicked: root.bridge.setPersonaField(
                                    "visualReplyAutoShow",
                                    checked
                                )
                            }

                            Label {
                                Layout.fillWidth: true
                                text: qsTr("Conversation always keeps the generated image with its assistant message. The latest image also remains available in Visuals.")
                                color: Theme.NCTheme.textMuted
                                font.pixelSize: Theme.NCTypography.microSize
                                wrapMode: Text.Wrap
                            }
                        }

                        NCInlineMessage {
                            Layout.fillWidth: true
                            Layout.columnSpan: personaVisualReplyGrid.columns
                            tone: "info"
                            title: qsTr("Uses the existing Visual Reply runtime")
                            message: qsTr("The persona selects when to request an image; provider, model, size, and API settings remain owned by Runtime > Visual reply.")
                        }
                    }
                }

                NCCard {
                    objectName: "personaPromptLibraryCard"
                    Layout.fillWidth: true
                    visible: root.selectedTab === "library"
                    title: qsTr("Prompt library")
                    description: qsTr("Search, preview, load, or quick-save. Right-click a prompt to open the full preview.")

                    NCSearchField {
                        toolTipText: qsTr("Filter the saved prompt library by text. This changes the visible list and does not modify saved prompts.")

                        objectName: "personaPromptLibrarySearchField"
                        Layout.fillWidth: true
                        placeholderText: qsTr("Search prompts")
                        text: root.searchText
                        onTextChanged: root.searchText = text
                    }


                    GridLayout {
                        Layout.fillWidth: true
                        columns: width >= 760 ? 2 : 1
                        columnSpacing: Theme.NCMetrics.space12
                        rowSpacing: Theme.NCMetrics.space12
                        ListView {
                            id: promptList
                            // Cancel queued rows before the workspace context is destroyed.
                            Component.onDestruction: model = null
                            objectName: "personaPromptLibraryList"
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.preferredHeight: 260
                            clip: true
                            spacing: Theme.NCMetrics.space6
                            model: root.bridge.promptLibrary
                            currentIndex: -1

                            delegate: Button {
                                id: promptButton
                                objectName: "personaPrompt_" + String(modelData.id)
                                required property var modelData
                                readonly property bool matches: root.searchText.length === 0
                                    || String(modelData.name || "").toLowerCase().indexOf(root.searchText.toLowerCase()) >= 0
                                    || String(modelData.addon || "").toLowerCase().indexOf(root.searchText.toLowerCase()) >= 0
                                width: promptList.width
                                height: matches ? 58 : 0
                                visible: matches
                                checked: String(modelData.id) === root.selectedPromptId
                                hoverEnabled: true
                                leftPadding: Boolean(modelData.builtin)
                                             ? Theme.NCMetrics.space12
                                             : Theme.NCMetrics.space12 + 30
                                rightPadding: Theme.NCMetrics.space12

                                background: Rectangle {
                                    radius: Theme.NCMetrics.radiusMedium
                                    color: promptButton.checked ? Theme.NCTheme.surfaceSelected
                                                                : promptButton.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.windowRaised
                                    border.width: promptButton.activeFocus || promptButton.checked
                                                  ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                                    border.color: promptButton.activeFocus ? Theme.NCTheme.focus
                                                                           : promptButton.checked ? Theme.NCTheme.accent : Theme.NCTheme.border
                                }
                                contentItem: ColumnLayout {
                                    spacing: 0
                                    Label {
                                        Layout.fillWidth: true
                                        text: String(promptButton.modelData.name || qsTr("Prompt"))
                                        color: Theme.NCTheme.text
                                        font.pixelSize: Theme.NCTypography.labelSize
                                        font.weight: Theme.NCTypography.medium
                                        elide: Text.ElideRight
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: Boolean(promptButton.modelData.quick)
                                              ? qsTr("%1 · Quick").arg(String(promptButton.modelData.addon || qsTr("Core")))
                                              : String(promptButton.modelData.addon || qsTr("Core"))
                                        color: Boolean(promptButton.modelData.quick) ? Theme.NCTheme.accent : Theme.NCTheme.textMuted
                                        font.pixelSize: Theme.NCTypography.microSize
                                        elide: Text.ElideRight
                                    }
                                }

                                NCCheckBox {
                                    toolTipText: qsTr("Select this prompt for a later delete action. Checking it alone does not remove the saved prompt.")

                                    objectName: "personaPromptDeleteCheck_"
                                                + String(promptButton.modelData.id || "")
                                    anchors.left: parent.left
                                    anchors.leftMargin: Theme.NCMetrics.space8
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 24
                                    height: 24
                                    visible: !Boolean(promptButton.modelData.builtin)
                                    text: ""
                                    checked: root.promptDeleteSelected(
                                                 String(promptButton.modelData.id || ""))
                                    Accessible.name: qsTr("Select %1 for deletion")
                                                     .arg(String(promptButton.modelData.name
                                                                 || qsTr("custom prompt")))
                                    z: 4
                                    onClicked: root.setPromptDeleteSelected(
                                                   String(promptButton.modelData.id || ""),
                                                   checked)
                                }
                                onClicked: root.selectPrompt(modelData)

                                TapHandler {
                                    acceptedButtons: Qt.RightButton
                                    onTapped: root.openPromptPreview(promptButton.modelData)
                                }
                            }

                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        }

                        NCScrollableTextArea {
                            toolTipText: qsTr("Read the selected library prompt before loading it. This preview does not replace the active Persona until you choose the load action.")

                            objectName: "personaPromptLibraryPreview"
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            implicitHeight: 260
                            label: root.selectedPromptId.length
                                   ? String(root.selectedPrompt.name || qsTr("Selected prompt"))
                                   : qsTr("Prompt preview")
                            text: String(root.selectedPrompt.prompt || "")
                            placeholderText: qsTr("Select a prompt to preview it before loading.")
                            readOnly: true
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space8

                        NCButton {
                            objectName: "personaPromptLibraryLoadButton"
                            text: qsTr("Load selected")
                            tone: "primary"
                            enabled: root.selectedPromptId.length > 0
                            onClicked: {
                                root.bridge.applyPromptRecord(root.selectedPromptId)
                                root.selectedTab = "persona"
                            }
                        }
                        NCButton {
                            objectName: "personaPromptLibraryQuickButton"
                            text: Boolean(root.selectedPrompt.quick) ? qsTr("Unpin") : qsTr("Quick save current")
                            tone: "secondary"
                            enabled: root.selectedPromptId.length > 0
                            onClicked: root.bridge.setPromptQuick(
                                root.selectedPromptId, !Boolean(root.selectedPrompt.quick)
                            )
                        }
                        NCButton {
                            objectName: "personaPromptClearSelectionButton"
                            text: qsTr("Clear selection")
                            tone: "quiet"
                            visible: root.deletePromptIds.length > 0
                            onClicked: root.clearPromptDeleteSelection()
                        }
                        NCButton {
                            objectName: "personaPromptLibraryDeleteButton"
                            text: qsTr("Delete selected (%1)")
                                  .arg(root.deletePromptIds.length)
                            tone: "danger"
                            enabled: root.deletePromptIds.length > 0
                            toolTipText: enabled
                                             ? qsTr("Delete all checked custom prompts")
                                             : qsTr("Check one or more custom prompts to delete them")
                            onClicked: {
                                deletePromptDialog.open()
                            }
                        }
                    }
                }

                NCCard {
                    visible: root.selectedTab === "relay"
                    objectName: "personaIdentityRelayCard"
                    Layout.fillWidth: true
                    title: qsTr("Identity Relay")
                    description: qsTr("Associate one imported assistant identity with this persona. The relay stays off until you enable it for the current conversation.")

                    headerAccessory: NCStatusChip {
                        text: Boolean(root.bridge.identityRelayState.pending)
                              ? qsTr("Review pending")
                              : String(root.bridge.identityRelayState.personaRef || "").length === 0
                                ? qsTr("Not used by this persona")
                                : String(root.bridge.identityRelayState.connectedRef || "")
                                  === String(root.bridge.identityRelayState.personaRef || "")
                                  && Boolean(root.bridge.identityRelayState.relayAvailable)
                                  ? qsTr("Connected") : qsTr("Needs review")
                        status: Boolean(root.bridge.identityRelayState.pending)
                                ? "info"
                                : String(root.bridge.identityRelayState.personaRef || "").length === 0
                                  ? "disconnected"
                                  : String(root.bridge.identityRelayState.connectedRef || "")
                                    === String(root.bridge.identityRelayState.personaRef || "")
                                    && Boolean(root.bridge.identityRelayState.relayAvailable)
                                    ? "active" : "warning"
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space8

                        NCComboBox {
                            toolTipText: qsTr("Choose an imported identity to link to this Persona. The link controls its Identity Relay association and does not create a new Discord account.")

                            objectName: "personaIdentityRelaySelector"
                            Layout.fillWidth: true
                            label: qsTr("Imported identity")
                            model: root.bridge.identityRelayState.options || []
                            textRole: "label"
                            valueRole: "value"
                            currentIndex: root.identityRelayIndex()
                            enabled: Number(root.bridge.activeQuickPersona.slot) >= 0
                                     && Boolean(root.bridge.identityRelayState.available)
                                     && !Boolean(root.bridge.identityRelayState.pending)
                            onActivated: root.bridge.setPersonaIdentityRelayRef(currentValue)
                        }

                        NCButton {
                            text: qsTr("Manage imports")
                            compact: true
                            tone: "secondary"
                            toolTipText: qsTr("Open Identity Relay to import, inspect, or remove identities")
                            onClicked: root.bridge.openAddonWorkspaceSection("identity_artifacts_tab", "Overview")
                        }
                    }

                    NCButton {
                        objectName: "personaIdentityRelayPreparingButton"
                        Layout.fillWidth: true
                        text: qsTr("Preparing review...")
                        tone: "secondary"
                        enabled: false
                        visible: Boolean(root.bridge.identityRelayState.pending)
                                 && !Boolean(root.bridge.identityRelayState.reviewReady)
                    }

                    NCButton {
                        objectName: "personaIdentityRelayReviewButton"
                        Layout.fillWidth: true
                        text: qsTr("Review identity")
                        tone: "primary"
                        visible: Boolean(root.bridge.identityRelayState.reviewReady)
                        enabled: visible
                        onClicked: identityRelayReviewDialog.openForCurrentReview()
                    }

                    Label {
                        Layout.fillWidth: true
                        text: String(root.bridge.identityRelayState.status || "")
                        color: String(root.bridge.identityRelayState.warning || "").length
                               ? Theme.NCTheme.warning : Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.captionSize
                        wrapMode: Text.Wrap
                        visible: !Boolean(root.bridge.identityRelayState.pending)
                    }
                }

                NCCard {
                    objectName: "personaAdvancedCard"
                    visible: root.selectedTab === "advanced"
                    Layout.fillWidth: true
                    title: qsTr("Technical rules moved to Overrides")
                    description: qsTr("Manage visual avatar and TTS voice rules separately for each provider and persona in Overrides. Provider-wide defaults are in Runtime.")
                    NCButton {
                        text: qsTr("Open Overrides")
                        onClicked: root.selectedTab = "overrides"
                    }
                }
            }
        }

    IdentityRelayReviewDialog {
        id: identityRelayReviewDialog
        bridge: root.bridge
    }

    FileDialog {
        id: avatarFileDialog
        property int targetSlot: -1
        title: qsTr("Choose persona portrait")
        nameFilters: [qsTr("Images (*.png *.jpg *.jpeg *.webp)")]
        fileMode: FileDialog.OpenFile
        onAccepted: root.bridge.importQuickPersonaAvatar(targetSlot, selectedFile.toString(), "")
    }

    NCDialog {
        id: promptPreviewDialog
        anchors.centerIn: parent
        title: String(root.selectedPrompt.name || qsTr("System prompt preview"))
        description: qsTr("Complete system prompt from %1. This preview is read-only.")
                         .arg(String(root.selectedPrompt.addon || qsTr("Custom")))
        acceptText: qsTr("Close")
        rejectText: ""

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space10

            NCStatusChip {
                text: Boolean(root.selectedPrompt.builtin)
                      ? qsTr("Built-in prompt") : qsTr("Saved custom prompt")
                status: Boolean(root.selectedPrompt.builtin) ? "info" : "active"
            }

            ScrollView {
                id: promptPreviewScroll
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(
                                            460,
                                            Math.max(240, promptPreviewArea.contentHeight
                                                     + Theme.NCMetrics.space24))
                clip: true
                contentWidth: availableWidth

                NCTextArea {
                    toolTipText: qsTr("Read the complete saved system prompt for the selected library item. This preview is read-only.")

                    id: promptPreviewArea
                    width: promptPreviewScroll.availableWidth
                    implicitHeight: Math.max(
                                        220,
                                        contentHeight + topPadding + bottomPadding)
                    label: qsTr("Complete system prompt")
                    text: String(root.selectedPrompt.prompt || "")
                    readOnly: true
                    selectByMouse: true
                }

                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            }
        }
    }

    NCDialog {
        id: deletePromptDialog
        anchors.centerIn: parent
        title: root.deletePromptIds.length === 1
               ? qsTr("Delete selected system prompt?")
               : qsTr("Delete %1 selected system prompts?")
                 .arg(root.deletePromptIds.length)
        description: qsTr("The checked custom prompts will be removed from the Prompt Library and Quick prompts in one operation.")
        acceptText: root.deletePromptIds.length === 1
                    ? qsTr("Delete prompt")
                    : qsTr("Delete %1 prompts").arg(root.deletePromptIds.length)
        acceptTone: "danger"
        rejectText: qsTr("Cancel")

        onAccepted: {
            const deleting = root.deletePromptIds.slice()
            if (root.bridge.deletePromptRecords(deleting)) {
                if (deleting.indexOf(root.selectedPromptId) >= 0) {
                    root.selectedPromptId = ""
                    root.selectedPrompt = ({})
                }
                root.clearPromptDeleteSelection()
            }
        }
    }

    NCDialog {
        id: savePersonaDialog
        anchors.centerIn: parent
        title: qsTr("Save quick persona")
        description: qsTr("Capture the current system prompt, technical voice rules, voice reference, and Visual Reply behavior in one reusable slot.")
        acceptText: qsTr("Save persona")
        rejectText: qsTr("Cancel")

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space12

            NCTextField {
                toolTipText: qsTr("Name used for the Persona saved by this dialog. It is shown on its quick card and in Conversation.")

                id: personaNameField
                Layout.fillWidth: true
                label: qsTr("Persona name")
                placeholderText: qsTr("Name shown on the quick card and in Conversation")
            }

            NCComboBox {
                toolTipText: qsTr("Quick Persona slot that receives the saved configuration. Review the target before saving if it already contains a Persona.")

                id: saveSlotSelector
                Layout.fillWidth: true
                label: qsTr("Save to quick slot")
                model: {
                    const cards = root.bridge.quickPersonaSlots || []
                    if (cards.some(function(item) { return Number(item.slot) === root.saveTargetSlot }))
                        return cards
                    return [{slot: root.saveTargetSlot,
                             slotLabel: qsTr("New slot %1").arg(root.saveTargetSlot + 1)}]
                }
                textRole: "slotLabel"
                valueRole: "slot"
                currentIndex: {
                    const cards = root.bridge.quickPersonaSlots || []
                    for (let index = 0; index < cards.length; ++index) {
                        if (Number(cards[index].slot) === root.saveTargetSlot)
                            return index
                    }
                    return 0
                }
                onActivated: root.saveTargetSlot = Number(currentValue)
            }

            NCCheckBox {
                toolTipText: qsTr("Also save a reusable copy of the system prompt in the prompt library. The quick Persona and the library entry are separate saved items.")

                id: savePromptCheck
                Layout.fillWidth: true
                text: qsTr("Also add the system prompt to the prompt library")
            }

            NCCheckBox {
                toolTipText: qsTr("Generate an image for the saved Persona through the active Visual Reply provider. This can start image-model work or a remote image request.")

                id: generatePortraitCheck
                Layout.fillWidth: true
                text: qsTr("Generate a portrait with the active Visual Reply provider")
            }

            NCCheckBox {
                toolTipText: qsTr("Also generate happy, sad, angry, and curious portraits after the base portrait. This requires portrait generation and creates additional image requests.")

                id: generateMoodSetCheck
                Layout.fillWidth: true
                enabled: generatePortraitCheck.checked
                text: qsTr("Also generate happy, sad, angry, and curious portraits")
            }

            NCInlineMessage {
                Layout.fillWidth: true
                tone: "info"
                message: qsTr("Portrait generation uses the existing Visual Reply runtime asynchronously. NC must be initialized and its image provider configured.")
                visible: generatePortraitCheck.checked
            }
        }

        onAccepted: {
            const slot = root.saveTargetSlot
            const saved = root.bridge.saveQuickPersona(slot, personaNameField.text, savePromptCheck.checked)
            if (saved && generatePortraitCheck.checked)
                Qt.callLater(function() { root.openPortraitPromptDialog(slot, generateMoodSetCheck.checked) })
        }
    }

    Popup {
        id: personaChooser
        objectName: "quickPersonaChooser"
        parent: Overlay.overlay
        width: Math.min(420, parent ? parent.width - 24 : 420)
        height: 390
        padding: Theme.NCMetrics.space12
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        function openFor(control) {
            if (!control || !parent)
                return
            personaChooserSearch.text = ""
            const point = control.mapToItem(parent, 0, control.height + Theme.NCMetrics.space4)
            x = Math.max(Theme.NCMetrics.space8,
                         Math.min(point.x, parent.width - width - Theme.NCMetrics.space8))
            y = Math.max(Theme.NCMetrics.space8,
                         Math.min(point.y, parent.height - height - Theme.NCMetrics.space8))
            open()
            personaChooserSearch.forceActiveFocus()
        }

        background: Rectangle {
            radius: Theme.NCMetrics.radiusLarge
            color: Theme.NCTheme.windowRaised
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space8
            Label {
                text: qsTr("Choose persona")
                color: Theme.NCTheme.text
                font.pixelSize: Theme.NCTypography.headingSize
                font.weight: Theme.NCTypography.semibold
            }
            NCTextField {
                toolTipText: qsTr("Filter saved Personas by name. Searching does not change the active Persona or delete any library entry.")

                id: personaChooserSearch
                objectName: "quickPersonaSearchField"
                Layout.fillWidth: true
                label: qsTr("Search personas")
                placeholderText: qsTr("Search by name")
            }
            ListView {
                id: personaChooserResults
                objectName: "quickPersonaSearchResults"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: Theme.NCMetrics.space4
                model: {
                    const query = personaChooserSearch.text.trim().toLowerCase()
                    return (root.bridge.quickPersonaChoices || []).filter(function(persona) {
                        return String(persona.name || "").toLowerCase().includes(query)
                    })
                }
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Button {
                    required property var modelData
                    width: ListView.view.width
                    height: 52
                    flat: true
                    Accessible.name: qsTr("Use quick persona %1").arg(String(modelData.name || ""))
                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusMedium
                        color: Boolean(modelData.active) ? Theme.NCTheme.surfaceSelected
                              : parent.hovered ? Theme.NCTheme.surfaceRaised : "transparent"
                        border.width: Boolean(modelData.active) ? Theme.NCMetrics.focusWidth : 0
                        border.color: Theme.NCTheme.accent
                    }
                    contentItem: RowLayout {
                        spacing: Theme.NCMetrics.space8
                        Rectangle {
                            Layout.preferredWidth: 36
                            Layout.preferredHeight: 36
                            radius: Theme.NCMetrics.radiusSmall
                            color: Theme.NCTheme.surfaceRaised
                            clip: true
                            Image {
                                anchors.fill: parent
                                source: String(modelData.avatarUrl || "")
                                fillMode: Image.PreserveAspectCrop
                                visible: status === Image.Ready
                                asynchronous: true
                            }
                            Label {
                                anchors.centerIn: parent
                                text: String(modelData.name || "P").slice(0, 1).toUpperCase()
                                color: Theme.NCTheme.accent
                                visible: parent.children[0].status !== Image.Ready
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: String(modelData.name || qsTr("Persona"))
                            elide: Text.ElideRight
                            color: Theme.NCTheme.text
                        }
                        Label {
                            visible: Boolean(modelData.active)
                            text: qsTr("Active")
                            color: Theme.NCTheme.success
                            font.pixelSize: Theme.NCTypography.captionSize
                        }
                    }
                    onClicked: {
                        root.bridge.applyQuickPersona(Number(modelData.slot))
                        personaChooser.close()
                    }
                }
            }
            Label {
                visible: personaChooserResults.count === 0
                text: qsTr("No matching personas")
                color: Theme.NCTheme.textMuted
            }
        }
    }

    NCDialog {
        id: newPersonaDialog
        objectName: "newQuickPersonaDialog"
        anchors.centerIn: parent
        title: qsTr("New persona")
        description: qsTr("Start empty or save the current setup as a new persona.")
        acceptText: qsTr("Create blank persona")
        rejectText: qsTr("Cancel")
        acceptEnabled: newPersonaNameField.text.trim().length > 0

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space12
            NCTextField {
                toolTipText: qsTr("Name for the new quick Persona. You can edit its prompt, voice, portrait, and overrides after creating it.")

                id: newPersonaNameField
                objectName: "newQuickPersonaNameField"
                Layout.fillWidth: true
                label: qsTr("Persona name")
                placeholderText: qsTr("Name for the new persona")
            }
            NCButton {
                Layout.fillWidth: true
                text: qsTr("Save current setup instead")
                onClicked: {
                    const target = root.newPersonaTargetSlot >= 0
                                   ? root.newPersonaTargetSlot : root.firstUnusedPersonaSlot()
                    const name = newPersonaNameField.text
                    newPersonaDialog.close()
                    root.openSaveDialog(target)
                    personaNameField.text = name
                }
            }
            NCInlineMessage {
                Layout.fillWidth: true
                tone: "info"
                message: qsTr("Blank personas start without a prompt, voice, or portrait. You can add them in the Persona tabs.")
            }
        }

        onAccepted: {
            const slot = root.bridge.createBlankQuickPersona(newPersonaNameField.text,
                                                              root.newPersonaTargetSlot)
            if (slot >= 0)
                root.selectedTab = "persona"
        }
    }

    Popup {
        id: moodThumbnailContextMenu
        objectName: "personaMoodThumbnailContextMenu"
        parent: Overlay.overlay
        width: 220
        padding: Theme.NCMetrics.space8
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        modal: false
        dim: false

        function openFor(control, mood) {
            if (!control || !parent)
                return
            root.portraitContextMood = String(mood || "")
            const mapped = control.mapToItem(
                             parent, 0,
                             control.height + Theme.NCMetrics.space4)
            x = Math.max(Theme.NCMetrics.space8,
                         Math.min(mapped.x,
                                  parent.width - width - Theme.NCMetrics.space8))
            y = Math.max(Theme.NCMetrics.space8,
                         Math.min(mapped.y,
                                  parent.height - implicitHeight - Theme.NCMetrics.space8))
            open()
        }

        background: Rectangle {
            color: Theme.NCTheme.windowRaised
            radius: Theme.NCMetrics.radiusLarge
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space2

            NCContextMenuItem {
                objectName: "personaMoodViewOriginalAction"
                Layout.fillWidth: true
                text: qsTr("View original size")
                enabled: root.moodAvatarUrl(root.portraitContextMood).length > 0
                onClicked: {
                    moodThumbnailContextMenu.close()
                    root.originalPortraitMood = root.portraitContextMood
                    root.originalPortraitSource = root.moodAvatarUrl(
                                                  root.portraitContextMood)
                    originalPortraitViewer.openCentered()
                }
            }
            NCContextMenuItem {
                objectName: "personaMoodEditAction"
                Layout.fillWidth: true
                text: qsTr("Edit")
                onClicked: {
                    moodThumbnailContextMenu.close()
                    root.openPortraitEditorForMood(root.portraitContextMood)
                }
            }
        }
    }

    Popup {
        id: originalPortraitViewer
        objectName: "personaOriginalPortraitViewer"
        parent: Overlay.overlay
        width: Math.min(parent ? parent.width - Theme.NCMetrics.space40 : 900,
                        Math.max(360, originalPortraitImage.sourceSize.width
                                      + Theme.NCMetrics.space40))
        height: Math.min(parent ? parent.height - Theme.NCMetrics.space40 : 760,
                         Math.max(300, originalPortraitImage.sourceSize.height
                                       + 116))
        padding: Theme.NCMetrics.space16
        modal: true
        dim: true
        closePolicy: Popup.CloseOnEscape

        function centerInOverlay() {
            if (!parent)
                return
            x = Math.max(Theme.NCMetrics.space20, (parent.width - width) / 2)
            y = Math.max(Theme.NCMetrics.space20, (parent.height - height) / 2)
        }

        function openCentered() {
            centerInOverlay()
            open()
            Qt.callLater(centerInOverlay)
        }

        onWidthChanged: {
            if (visible)
                centerInOverlay()
        }
        onHeightChanged: {
            if (visible)
                centerInOverlay()
        }

        background: Rectangle {
            color: Theme.NCTheme.windowRaised
            radius: Theme.NCMetrics.radiusLarge
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space12

            Label {
                Layout.fillWidth: true
                text: qsTr("Original: %1").arg(
                          root.moodDisplayName(root.originalPortraitMood))
                color: Theme.NCTheme.text
                font.pixelSize: Theme.NCTypography.headingSize
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: originalPortraitImage.width
                contentHeight: originalPortraitImage.height
                ScrollBar.horizontal.policy: ScrollBar.AsNeeded
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                Image {
                    id: originalPortraitImage
                    objectName: "personaOriginalPortraitImage"
                    width: Math.max(1, sourceSize.width)
                    height: Math.max(1, sourceSize.height)
                    source: root.originalPortraitSource
                    fillMode: Image.Pad
                    asynchronous: true
                    smooth: false
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                NCButton {
                    objectName: "personaOriginalPortraitEditButton"
                    text: qsTr("Edit")
                    onClicked: {
                        originalPortraitViewer.close()
                        root.openPortraitEditorForMood(root.originalPortraitMood)
                    }
                }
                NCButton {
                    objectName: "personaOriginalPortraitCloseButton"
                    text: qsTr("Close")
                    tone: "primary"
                    onClicked: originalPortraitViewer.close()
                }
            }
        }
    }

    Connections {
        target: root.bridge

        function onPersonaAvatarPromptChanged() {
            const state = root.bridge.personaAvatarPromptState || ({})
            if (!Boolean(state.inFlight) && String(state.text || "").length > 0)
                portraitPromptArea.text = String(state.text)
        }

        function onPersonaPortraitEditorChanged() {
            if (portraitPromptDialog.visible && Boolean(root.bridge.personaPortraitEditorState.saved)) {
                root.previewMood = ""
                portraitPromptDialog.close()
            }
        }
    }

    NCDialog {
        id: portraitPromptDialog
        objectName: "personaPortraitDialog"
        anchors.centerIn: parent
        width: Math.min(parent ? parent.width - Theme.NCMetrics.space40 : 880, 880)
        title: portraitMoodSetCheck.checked
               ? qsTr("Build persona portrait set")
               : qsTr("Create neutral identity portrait")
        description: portraitMoodSetCheck.checked
                     ? qsTr("Create the neutral identity reference and its mood portraits through the same saved identity workflow.")
                     : qsTr("Describe the exact persona appearance. Refine uses the active main language model; Create uses the configured Visual Reply provider.")
        acceptText: portraitMoodSetCheck.checked
                    ? qsTr("Generate portrait set")
                    : qsTr("Create neutral portrait")
        rejectText: qsTr("Cancel")
        acceptEnabled: !Boolean(root.bridge.personaAvatarPromptState.inFlight)
                       && portraitPromptArea.text.trim().length > 0
        closePolicy: Boolean(root.bridge.personaPortraitEditorState.inFlight) ? Popup.NoAutoClose : Popup.CloseOnEscape

        footer: Item {
            implicitWidth: portraitFooterLayout.implicitWidth + portraitPromptDialog.chromeInset * 2
            implicitHeight: root.portraitManageMode
                            ? 0
                            : portraitFooterLayout.implicitHeight + Theme.NCMetrics.space8 + portraitPromptDialog.chromeInset
            visible: !root.portraitManageMode

            RowLayout {
                id: portraitFooterLayout
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: portraitPromptDialog.chromeInset
                anchors.rightMargin: portraitPromptDialog.chromeInset
                anchors.topMargin: Theme.NCMetrics.space8
                spacing: Theme.NCMetrics.space8
            Item { Layout.fillWidth: true }
            NCButton {
                objectName: "personaPortraitFooterCancelButton"
                text: qsTr("Cancel")
                enabled: !Boolean(root.bridge.personaPortraitEditorState.inFlight)
                onClicked: portraitPromptDialog.reject()
            }
            NCButton {
                objectName: "personaPortraitFooterSaveButton"
                text: root.portraitManageMode
                      ? (Boolean(root.bridge.personaPortraitEditorState.inFlight) ? qsTr("Saving…") : qsTr("Save changes"))
                      : portraitPromptDialog.acceptText
                tone: "primary"
                enabled: !Boolean(root.bridge.personaPortraitEditorState.inFlight)
                         && !Boolean(root.bridge.personaAvatarGenerationState.inFlight)
                         && (root.portraitManageMode || (portraitPromptDialog.acceptEnabled && !portraitEditor.dirty))
                onClicked: {
                    if (root.portraitManageMode)
                        root.bridge.savePersonaPortraitSet(root.portraitTargetSlot, root.portraitTargetId, portraitEditor.rows)
                    else if (portraitMoodSetCheck.checked && portraitGenerationScope.currentIndex === 2)
                        refreshAllPortraitsDialog.open()
                    else
                        portraitPromptDialog.accept()
                }
            }
        }
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space12

            RowLayout {
                Layout.fillWidth: true
                visible: portraitMoodSetCheck.checked
                enabled: !Boolean(root.bridge.personaPortraitEditorState.inFlight)
                NCButton { text: qsTr("Manage portraits"); tone: root.portraitManageMode ? "primary" : "secondary"; onClicked: root.portraitManageMode = true }
                NCButton { text: qsTr("Generate portraits"); tone: !root.portraitManageMode ? "primary" : "secondary"; onClicked: root.portraitManageMode = false }
            }

            PersonaPortraitEditor {
                id: portraitEditor
                Layout.fillWidth: true
                visible: root.portraitManageMode
                busy: Boolean(root.bridge.personaPortraitEditorState.inFlight)
                saveEnabled: !Boolean(root.bridge.personaPortraitEditorState.inFlight)
                             && !Boolean(root.bridge.personaAvatarGenerationState.inFlight)
                saveText: Boolean(root.bridge.personaPortraitEditorState.inFlight)
                          ? qsTr("Saving…")
                          : qsTr("Save changes")
                onCancelRequested: portraitPromptDialog.reject()
                onSaveRequested: root.bridge.savePersonaPortraitSet(
                                     root.portraitTargetSlot,
                                     root.portraitTargetId,
                                     portraitEditor.rows)
            }
            NCInlineMessage {
                Layout.fillWidth: true
                visible: root.portraitManageMode && String(root.bridge.personaPortraitEditorState.error || "").length > 0
                tone: "error"
                title: qsTr("Portraits were not saved")
                message: String(root.bridge.personaPortraitEditorState.error || "")
            }

            ColumnLayout {
                Layout.fillWidth: true
                visible: !root.portraitManageMode
                spacing: Theme.NCMetrics.space12

            NCInlineMessage {
                Layout.fillWidth: true
                visible: portraitEditor.dirty
                tone: "info"
                title: qsTr("Save your portrait edits first")
                message: qsTr("Return to Manage portraits and save your changes before generating images.")
            }

            NCScrollableTextArea {
                toolTipText: qsTr("Appearance instructions used for this portrait-generation request. Include the identifying details and style you want the image model to preserve.")

                id: portraitPromptArea
                Layout.fillWidth: true
                implicitHeight: 210
                label: qsTr("Portrait prompt")
                placeholderText: qsTr("Appearance, clothing, art style, and identifying details")
            }

            RowLayout {
                Layout.fillWidth: true
                NCButton {
                    text: Boolean(root.bridge.personaAvatarPromptState.inFlight)
                          ? qsTr("Refining...") : qsTr("Refine prompt")
                    tone: "secondary"
                    enabled: !Boolean(root.bridge.personaAvatarPromptState.inFlight)
                             && portraitPromptArea.text.trim().length > 0
                    onClicked: root.bridge.refinePersonaAvatarPrompt(
                        portraitPromptArea.text,
                        portraitTransparencyCheck.checked
                    )
                }
                NCButton {
                    text: qsTr("Reset suggestion")
                    tone: "quiet"
                    enabled: !Boolean(root.bridge.personaAvatarPromptState.inFlight)
                    onClicked: portraitPromptArea.text = String(root.bridge.personaAvatarPrompt(root.portraitTargetSlot) || "")
                }
                Item { Layout.fillWidth: true }
            }

            RowLayout {
                Layout.fillWidth: true
                NCCheckBox {
                    toolTipText: qsTr("Request a transparent background for this new portrait when supported by the selected image provider. Existing portraits remain unchanged.")

                    id: portraitTransparencyCheck
                    text: qsTr("Transparent avatar background")
                }
                Item { Layout.fillWidth: true }
                NCCheckBox {
                    toolTipText: qsTr("Generate mood portraits as well as the base image. This requires additional image-generation requests and can take longer.")

                    id: portraitMoodSetCheck
                    text: qsTr("Generate mood set")
                }
            }

            NCInlineMessage {
                Layout.fillWidth: true
                tone: String(root.bridge.personaAvatarPromptState.error || "").length ? "error" : "info"
                title: String(root.bridge.personaAvatarPromptState.error || "").length
                       ? qsTr("Refinement problem")
                       : portraitTransparencyCheck.checked
                         ? qsTr("Transparent chat asset")
                         : qsTr("Keep generated background")
                message: String(root.bridge.personaAvatarPromptState.error || "").length
                         ? String(root.bridge.personaAvatarPromptState.error)
                         : portraitTransparencyCheck.checked
                           ? qsTr("The refined prompt requires one isolated character, forbids fake checkerboards, and targets a genuinely clear PNG. With Runware, NC then uses portrait background removal to create the real alpha channel.")
                           : qsTr("Prompt refinement still describes only the character, but NC keeps the image provider's original background and skips local background removal.")
            }
            NCComboBox {
                toolTipText: qsTr("Choose which portrait or mood entries this generation action should create. Review the selected scope before starting image generation.")

                id: portraitGenerationScope
                Layout.fillWidth: true
                visible: portraitMoodSetCheck.checked
                label: qsTr("Generate")
                model: [qsTr("Missing portraits only"), qsTr("Selected mood only"), qsTr("Refresh entire set…")]
            }
            Label {
                Layout.fillWidth: true
                visible: portraitMoodSetCheck.checked
                text: portraitGenerationScope.currentIndex === 1
                      ? qsTr("Selected mood: [%1]. Save new moods in Manage portraits first.").arg(portraitEditor.selectedTag)
                      : qsTr("Missing portraits only keeps your existing imported images.")
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
            }
        }

        onAccepted: {
            const prompt = portraitPromptArea.text.trim()
            if (!prompt.length) {
                root.bridge.refinePersonaAvatarPrompt(
                    "",
                    portraitTransparencyCheck.checked
                )
                return
            }
            if (Boolean(root.bridge.personaAvatarPromptState.inFlight))
                return
            if (portraitMoodSetCheck.checked) {
                root.bridge.generatePersonaPortraitSelection(root.portraitTargetSlot,
                    ["missing", "selected", "all"][portraitGenerationScope.currentIndex],
                    portraitEditor.selectedTag, prompt, portraitTransparencyCheck.checked)
                return
            }
            root.bridge.generateQuickPersonaAvatar(
                root.portraitTargetSlot,
                portraitMoodSetCheck.checked,
                prompt,
                portraitTransparencyCheck.checked
            )
        }
    }

    NCDialog {
        id: refreshAllPortraitsDialog
        anchors.centerIn: parent
        title: qsTr("Replace the entire portrait set?")
        description: qsTr("This generates new portraits for every saved mood, including imported images and the neutral reference.")
        acceptText: qsTr("Refresh entire set")
        rejectText: qsTr("Cancel")
        onAccepted: portraitPromptDialog.accept()
    }

    NCDialog {
        id: removePersonaDialog
        anchors.centerIn: parent
        title: qsTr("Remove quick persona?")
        description: qsTr("This clears the quick slot and its locally owned portrait files. The current NC runtime settings are not reset.")
        acceptText: qsTr("Remove")
        acceptTone: "danger"
        rejectText: qsTr("Cancel")
        onAccepted: root.bridge.removeQuickPersona(root.removeTargetSlot)
    }
}
