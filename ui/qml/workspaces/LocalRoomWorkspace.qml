pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

ScrollView {
    id: root
    required property var bridge
    readonly property var room: controlById("discord_local_room_state").roomState || ({})
    readonly property bool discordMode: room.mode === "discord"
    readonly property string roomKey: String(room.room_key || room.mode || "local")
    readonly property string roomTitle: discordMode ? qsTr("Discord room") : qsTr("Local room")
    readonly property bool editCast: phase !== "starting" && !room.stopping && (room.capabilities || {}).edit_cast !== false
    readonly property var preparedBots: [{id: "", name: qsTr("Choose a prepared bot…")}].concat(room.prepared_bots || [])
    readonly property var freeAccounts: (room.available_accounts || []).filter(row => row.available)
    readonly property bool admissionAvailable: !discordMode || room.available_accounts === undefined || freeAccounts.length > 0
    property string admissionBotId: ""
    property string replacementId: ""
    property string replacementAdmission: ""
    readonly property string phase: String(room.phase || "unavailable")
    readonly property bool active: phase === "running" || phase === "starting"
    readonly property bool joined: Boolean(room.joined)
    readonly property bool textOnly: room.input_mode === "text_only"
    readonly property var conversation: root.room.conversation || ({})
    readonly property string conversationTopic: String(root.conversation.topic || "")
    readonly property bool savedHistory: Boolean(root.conversation.has_history) && Boolean(root.conversation.saved)
    readonly property bool continuingConversation: root.active ? Boolean(root.conversation.continuing) : root.savedHistory
    readonly property bool conversationHasMessages: (root.room.messages || []).length > 0
    readonly property string conversationPhaseText: !root.active && root.savedHistory ? qsTr("Saved conversation · ready to continue")
        : root.continuingConversation ? qsTr("Continuing saved conversation")
        : root.active && root.conversationHasMessages ? qsTr("Conversation in progress")
        : qsTr("New conversation")
    readonly property var historyView: root.room.history_view || ({})
    readonly property string historyError: {
        if (root.selected.history_error) return String(root.selected.history_error)
        return root.historyLoaded ? String(root.historyView.history_error || "") : ""
    }
    readonly property bool historyLoaded: Boolean(root.historyView.participant_id)
        && String(root.historyView.participant_id) === root.selectedId
    readonly property bool historyFailed: root.historyError.length > 0
    readonly property bool historyAvailable: root.historyLoaded && !root.historyFailed
    readonly property int historyWindow: Number(root.historyView.context_entries || 0)
    readonly property string historyCountText: {
        const stored = Number(root.historyView.count || 0)
        const shown = root.historyEntries.length
        return shown < stored ? qsTr("%1 stored entries · showing %2").arg(stored).arg(shown)
                              : qsTr("%1 stored entries").arg(stored)
    }
    readonly property string historyWindowText: root.historyWindow > 0
        ? qsTr("Configured context window: latest %1 entries").arg(root.historyWindow)
        : qsTr("Configured context window: all entries (0)")
    readonly property int aiParticipantCount: {
        let count = 0
        for (let i = 0; i < root.roster.length; ++i)
            if (root.isAiParticipant(root.roster[i])) count += 1
        return count
    }
    readonly property int historyParticipantCount: {
        let count = 0
        for (let i = 0; i < root.roster.length; ++i)
            if (root.isAiParticipant(root.roster[i]) && Number(root.roster[i].history_count || 0) > 0) count += 1
        return count
    }
    readonly property string conversationHistorySummary: {
        if (root.discordMode)
            return root.conversation.has_history ? qsTr("This Discord room's conversation is saved separately for this server and voice channel.") : qsTr("A new Discord room conversation.")
        if (!root.conversation.has_history)
            return qsTr("A new conversation. Everyone starts with empty Local room history.")
        if (root.historyParticipantCount > 0 && root.aiParticipantCount > 0)
            return qsTr("%1 of %2 participants have previous Local room history. Only this room's history is kept.").arg(root.historyParticipantCount).arg(root.aiParticipantCount)
        return qsTr("Previous Local room history is saved. Only this room's history is kept.")
    }
    readonly property bool externalConversation: typeof bridge.openLocalRoomConversation === "function"
    property bool chatOpen: false
    property bool chatEnlarged: false
    property var conversationViewport: ({})
    property bool viewLoaded: false
    property bool viewMounted: false
    property bool viewDestroying: false
    property string viewConversationId: ""
    property string loadedRoomKey: ""
    property real savedPageY: 0
    property string userNameDraft: ""
    property string messageDraft: ""
    property bool memoryDetails: false
    property string panel: ""
    property string participantTab: "controls"
    property string topicDraft: ""
    property bool roomDetailsExpanded: false
    readonly property bool roomInfoVisible: discordMode || roomDetailsExpanded
    property string selectedId: String(controlById("discord_local_room_state").selectedParticipantId || "")
    property var roster: []
    ListModel { id: participantRows }
    property var historyEntries: []
    property string historyModelParticipant: ""
    ListModel { id: memoryRows }
    property var library: []
    property string librarySearch: ""
    readonly property var filteredLibrary: library.filter(function(p) { return String(p.name).toLowerCase().indexOf(librarySearch.toLowerCase()) >= 0 })
    readonly property bool wide: availableWidth >= 900
    readonly property var selected: participant(selectedId)
    property bool replyDetails: false
    property string overrideEditingPersonaId: ""
    property string overrideEditingPersonaName: ""
    property var overrideEditingDefaults: ({})
    property var replyCatalog: ({providers: []})
    readonly property var replySettings: selected.reply_settings || ({})
    readonly property var documentWorkspace: bridge.documentMemoryWorkspace || ({})
    readonly property var documentPackages: documentWorkspace.packages || []
    readonly property bool replyRecallEnabled: replySettings.document_memory_enabled === undefined
        || replySettings.document_memory_enabled === null
        ? Boolean((documentWorkspace.settings || {}).enabled) : Boolean(replySettings.document_memory_enabled)
    readonly property string replyPackageId: String(replySettings.document_package_id || documentWorkspace.activePackageId || "")
    readonly property var replyPackage: documentPackages.find(row => String(row.id) === replyPackageId) || ({})
    readonly property string replyPackageName: String(replyPackage.name || replySettings.document_package_name || replyPackageId || qsTr("No package configured"))
    readonly property string replySummary: String(replySettings.model || qsTr("No model selected")) + " · "
        + (Number(replySettings.context_messages) === 0 ? qsTr("All messages") : qsTr("%1 messages").arg(Number(replySettings.context_messages || 20)))
        + " · " + (replyRecallEnabled ? replyPackageName : qsTr("Documents off"))
    readonly property string replyWarning: {
        if (selected.role === "human" || !selected.id) return ""
        const warnings = []
        if (!replySettings.provider || !replySettings.model)
            warnings.push(qsTr("No language model is configured for new replies."))
        else {
            const providers = replyCatalog.providers || []
            const provider = providers.find(row => String(row.id) === String(replySettings.provider))
            if (providers.length && (!provider || !provider.available))
                warnings.push(qsTr("The selected language model connection is unavailable."))
            else if (provider && provider.message) warnings.push(String(provider.message))
        }
        if (replyRecallEnabled) {
            const status = (documentWorkspace.packageStates || {})[replyPackageId] || replyPackage
            if (!replyPackage.id || String(status.state || "") !== "ready")
                warnings.push(qsTr("%1 is %2. Documents are not used; the room continues.").arg(replyPackageName)
                              .arg(replyPackage.id ? qsTr("not ready") : qsTr("unavailable"))
                              + (status.status ? " " + String(status.status) : ""))
            else if (status.warning) warnings.push(replyPackageName + ": " + String(status.warning))
        }
        return warnings.join("\n")
    }
    function replySourceLabel(source) {
        return ({persona: qsTr("Persona override"), participant: qsTr("Participant setting"),
            room: qsTr("Room default"), global: qsTr("Runtime default"),
            document_default: qsTr("Document Memory default")})[String(source)] || qsTr("Default")
    }
    function refreshReplyCatalog() {
        if (panel === "participant" && selected.id && selected.role !== "human"
                && typeof bridge.personaOverrideCatalog === "function")
            replyCatalog = bridge.personaOverrideCatalog()
    }
    function openPersonaOverrides() {
        if (selected.role === "human" || !selected.persona_id) return
        overrideEditingPersonaId = String(selected.persona_id)
        const record = typeof bridge.personaOverrideRecord === "function"
            ? bridge.personaOverrideRecord(overrideEditingPersonaId) : ({})
        overrideEditingPersonaName = String(record.name || selected.name || "")
        overrideEditingDefaults = Object.assign({}, replySettings.inherited_defaults || ({}))
        panel = "personaOverrides"
    }
    onPanelChanged: {
        refreshReplyCatalog()
        if (panel === "controls" && !discordMode)
            userNameDraft = String(root.room.user_name || "You")
    }
    onSelectedIdChanged: {
        replyDetails = false
        // Snapshot rows are rebuilt by polling; refresh only for a new identity.
        Qt.callLater(root.refreshReplyCatalog)
    }

    readonly property var directive: root.room.directive || ({})
    readonly property string directiveStatus: String(root.directive.status || "").trim().toLowerCase()
    readonly property bool directivePending: root.directiveStatus === "queued" || root.directiveStatus === "preparing" || root.directiveStatus === "delivering"
    readonly property string directiveKindLabel: String(root.directive.kind || "") === "guide"
        ? qsTr("Guide bot") : qsTr("Speak through bot")
    readonly property string directiveStatusText: {
        if (root.directiveStatus.length === 0) return ""
        let text = root.directiveKindLabel + " " + root.directiveStatus
        if (root.directiveStatus === "queued")
            text += qsTr(" · %1 speaks next after the current speaker finishes").arg(String(root.participant(String(root.directive.moderator_id || "")).name || qsTr("the selected bot")))
        const detail = String(root.directive.detail || "")
        if (detail.length > 0) text += " · " + detail
        return text
    }
    readonly property color directiveStatusColor: root.directiveStatus === "failed" ? Theme.NCTheme.error
        : root.directivePending ? Theme.NCTheme.accent
        : root.directiveStatus === "delivered" ? Theme.NCTheme.success : Theme.NCTheme.textMuted
    property string composerTargetId: ""
    property string composerAdmission: ""
    property string composerConversation: ""
    property string composerAction: "guide"
    property var botDrafts: ({})
    property var removalTarget: ({})
    readonly property bool composerAvailable: {
        const target = participant(composerTargetId)
        return phase === "running" && !room.stopping && !room.paused && !directivePending
            && composerConversation === String(conversation.id || "") && Boolean(target.id)
            && target.role !== "human" && !target.muted
            && String(target.admission_id || "") === composerAdmission
            && String(target.membership_phase || "ready") === "ready"
            && (!discordMode || target.role === "moderator")
    }
    function composerKey() { return roomKey + ":" + composerConversation + ":" + composerTargetId + ":" + composerAdmission + ":" + composerAction }
    function rememberBotDraft() {
        if (composerTargetId) {
            const values = Object.assign({}, botDrafts)
            values[composerKey()] = guidanceDraft
            botDrafts = values
        }
    }
    function openBotComposer(action, id) {
        const target = participant(id || selectedId)
        if (!target.id || target.role === "human") return
        composerTargetId = memberId(target)
        composerAdmission = String(target.admission_id || "")
        composerConversation = String(conversation.id || "")
        composerAction = action
        selectedId = composerTargetId
        setRoomControl("discord_local_room_participant", composerTargetId)
        guidanceDraftDirty = true
        guidanceDraft = String(botDrafts[composerKey()] || "")
        botComposer.open()
        botMessage.forceActiveFocus()
    }
    function openSelfMenu(anchor, x, y) {
        userNameDraft = String(room.user_name || "You")
        const origin = anchor || selfMenuButton
        const point = origin.mapToItem(selfMenu.parent,
            x === undefined ? 0 : x, y === undefined ? origin.height : y)
        selfMenu.x = Math.max(8, Math.min(point.x, selfMenu.parent.width - selfMenu.width - 8))
        selfMenu.y = Math.max(8, Math.min(point.y, selfMenu.parent.height - selfMenu.height - 8))
        selfMenu.open()
    }
    function speakAsSelfNext() {
        const human = roster.find(person => person.role === "human")
        if (human && joined) {
            selectedId = memberId(human)
            setRoomControl("discord_local_room_participant", selectedId)
            runAction("discord_local_room_next", {participant_id: selectedId})
        }
    }
    function requestParticipantRemoval() {
        removalTarget = {participant_id: selectedId, admission_id: String(selected.admission_id || ""), name: String(selected.name || "")}
        removeParticipantDialog.open()
    }
    function openRoomControls() {
        if (discordMode) openSelfMenu()
        else { loadBehaviorDraft(); behaviorDialog.open() }
    }
    property string guidanceDraft: ""
    property bool guidanceDraftDirty: false
    property var behaviorDraft: ({})
    property bool behaviorLoaded: false
    property bool behaviorDraftDirty: false
    property bool behaviorAdvanced: false
    property string behaviorSubmitted: ""
    readonly property var savedBehavior: normalizedBehavior(root.room.behavior || ({}))
    readonly property bool behaviorManual: root.behaviorDraft.speaker_selection === "manual"
    readonly property bool behaviorRecovery: !root.behaviorManual && Boolean(root.behaviorDraft.moderator_help)
    readonly property string behaviorSaveError: String(root.room.behavior_save_error || "")
    readonly property string behaviorSummary: {
        const value = root.savedBehavior
        const selection = value.speaker_selection === "manual" ? qsTr("You choose each speaker")
            : value.speaker_selection === "names" ? qsTr("Names and questions choose next") : qsTr("AI chooses next")
        const recovery = value.speaker_selection === "manual" || !value.moderator_help ? qsTr("Automatic moderator help off")
            : value.silence_seconds === 0 ? qsTr("Moderator takes charge without added delay")
            : qsTr("Moderator helps after %1 seconds of silence").arg(value.silence_seconds)
        return selection + " · " + recovery
    }
    objectName: "localRoomWorkspace"
    clip: true
    contentWidth: availableWidth

    // Read the Python QVariant list once per change notification. Fetching it
    // separately for every binding repeatedly converts all settings and history.
    readonly property var controlsById: {
        const controls = bridge.liveAddonControls || []
        const index = ({})
        for (let i = 0; i < controls.length; ++i) index[controls[i].id] = controls[i]
        return index
    }
    function controlById(id) { return controlsById[id] || ({}) }
    function participant(id) {
        for (let i = 0; i < roster.length; ++i) if (String(roster[i].participant_id || roster[i].id) === id || roster[i].id === id) return roster[i]
        return ({})
    }
    function memberId(person) { return String(person.participant_id || person.id || "") }
    function normalizedBehavior(value) {
        return {speaker_selection: String(value.speaker_selection || "ai"),
            moderator_help: value.moderator_help === undefined ? true : Boolean(value.moderator_help),
            silence_seconds: Math.max(0, Number(value.silence_seconds || 0)),
            moderator_action: String(value.moderator_action || "moderator_speaks_and_calls_next"),
            allow_repeat: Boolean(value.allow_repeat),
            prepare_ahead: value.prepare_ahead === undefined ? true : Boolean(value.prepare_ahead),
            trigger: String(value.trigger || "no_route_after_any_speech"),
            cooldown_seconds: Math.max(0, Number(value.cooldown_seconds || 0)),
            router_instructions: String(value.router_instructions || "")}
    }
    function loadBehaviorDraft() {
        if (!root.viewMounted) return
        const saved = root.normalizedBehavior(root.room.behavior || ({}))
        if (!root.behaviorLoaded) {
            const view = root.room.view_state || ({})
            root.behaviorDraft = root.normalizedBehavior(view.behavior_draft || saved)
            root.behaviorAdvanced = Boolean(view.behavior_advanced)
            root.behaviorLoaded = true
            root.behaviorDraftDirty = JSON.stringify(root.behaviorDraft) !== JSON.stringify(saved)
        } else if (!root.behaviorDraftDirty) {
            root.behaviorDraft = saved
        } else if (JSON.stringify(root.behaviorDraft) === JSON.stringify(saved)) {
            root.behaviorDraftDirty = false
            root.behaviorSubmitted = ""
        }
    }
    function editBehavior(key, value) {
        const draft = root.normalizedBehavior(root.behaviorDraft)
        draft[key] = value
        if (key === "speaker_selection" && value === "manual") draft.moderator_help = false
        root.behaviorDraft = draft
        root.behaviorDraftDirty = JSON.stringify(draft) !== JSON.stringify(root.savedBehavior)
        root.behaviorSubmitted = ""
    }
    function saveBehavior() {
        if (!root.behaviorDraftDirty || !root.actionEnabled("discord_local_room_save_behavior")) return
        // Canonicalize only the explicit submission; preserve spaces while typing.
        const submitted = root.normalizedBehavior(root.behaviorDraft)
        submitted.router_instructions = submitted.router_instructions.trim()
        root.behaviorDraft = submitted
        root.behaviorSubmitted = JSON.stringify(submitted)
        root.runAction("discord_local_room_save_behavior", {behavior: submitted})
    }
    function loadDrafts() {
        root.loadBehaviorDraft()
        root.messageDraft = String(root.controlById("discord_local_room_message").value || "")
        // Snapshot polls must not overwrite what the user is currently typing.
        if (!root.guidanceDraftDirty)
            root.guidanceDraft = String(root.controlById("discord_local_room_announcement").value || "")
    }
    function setGuidanceDraft(value) {
        if (root.guidanceDraft !== value) {
            root.guidanceDraft = value
            root.guidanceDraftDirty = true
        }
        guidanceSyncTimer.restart()
    }
    function setRoomControl(controlId, value) {
        // Timers and teardown can finish after a different addon is selected.
        root.bridge.setLiveAddonControl("discord_voice_bridge_tab::" + controlId, value)
    }
    function flushDraft(controlId, value) {
        if (String(root.controlById(controlId).value || "") !== value)
            root.setRoomControl(controlId, value)
    }
    function flushGuidanceDraft() {
        guidanceSyncTimer.stop()
        root.flushDraft("discord_local_room_announcement", root.guidanceDraft)
    }
    function locallyReady(id) {
        if (id === "discord_local_room_send")
            return root.phase === "running" && (root.joined || root.discordMode) && !root.room.stopping && !Boolean(root.room.paused) && root.messageDraft.trim().length > 0
                && (!root.discordMode || root.room.text_sender_available !== false)
        if (root.phase !== "running" || Boolean(root.room.paused) || root.room.stopping || root.directivePending) return false
        if (id === "discord_local_room_guide" || id === "discord_local_room_announce")
            return root.guidanceDraft.trim().length > 0 && (!botComposer.visible || root.composerAvailable)
        return false
    }
    function actionEnabled(id) {
        if (id === "discord_local_room_send") return root.locallyReady(id)
        if (id === "discord_local_room_guide" || id === "discord_local_room_announce")
            return root.locallyReady(id)
        return Boolean(root.controlById(id).enabled) || root.locallyReady(id)
    }
    function runAction(id, overrides) {
        const actionId = String(id || "")
        if (actionId === "discord_local_room_guide" || actionId === "discord_local_room_announce")
            root.flushGuidanceDraft()
        const payload = {participant_id: selectedId,
            admission_id: String(selected.admission_id || ""),
            persona_id: String(controlById("discord_local_room_persona").value || ""),
            text: root.messageDraft,
            announcement: root.guidanceDraft}
        if (root.discordMode && actionId === "discord_local_room_send")
            payload.sender_id = String(textSender.currentValue || "")
        if (overrides) Object.assign(payload, overrides)
        if (!root.actionEnabled(actionId)) return false
        root.bridge.triggerLiveAddonActionWithPayload(actionId, payload)
        return true
    }
    function selectParticipant(id) {
        if (!discordMode && participant(id).role === "human") { openSelfMenu(); return }
        root.selectedId = memberId(participant(id))
        root.setRoomControl("discord_local_room_participant", memberId(participant(id)))
        participantTab = "controls"
        panel = "participant"
        if (selected.role === "human") userNameDraft = String(root.room.user_name || selected.name || "You")
    }
    function openParticipantMenu(id, anchor, x, y) {
        const position = anchor.mapToItem(root, x, y)
        const target = participant(id)
        if (!discordMode && target.role === "human") { openSelfMenu(anchor, x, y); return }
        selectedId = memberId(target)
        setRoomControl("discord_local_room_participant", selectedId)
        participantMenu.popup(position.x, position.y)
    }
    function openParticipantHistory(id) {
        const target = memberId(participant(String(id || selectedId || "")))
        if (!target) return
        if (target !== selectedId) selectParticipant(target)
        panel = "participant"
        participantTab = "history"
        runAction("discord_local_room_view_history", {participant_id: target})
    }
    function refreshParticipantHistory() {
        if (selectedId) runAction("discord_local_room_view_history", {participant_id: selectedId})
    }
    function openConversationDetails() {
        topicDraft = conversationTopic
        panel = "conversation"
    }
    function openTopicEditor() {
        topicDraft = conversationTopic
        topicDialog.open()
    }
    function clearTopic() {
        if (runAction("discord_local_room_set_topic", {topic: ""})) {
            topicDraft = ""
            topicDialog.close()
        }
    }
    function saveTopic() {
        const value = topicDraft.trim()
        if (value.length > 0) runAction("discord_local_room_set_topic", {topic: value})
    }
    function historyRoleName(role) {
        if (root.discordMode) return qsTr("Delivered speech")
        const value = String(role || "").toLowerCase()
        if (value === "human" || value === "user" || value === "you") return qsTr("Heard in room")
        return String(selected.name || qsTr("Participant"))
    }
    function isAiParticipant(person) {
        if (!person) return false
        if (person.is_human !== undefined && person.is_human !== null) return !Boolean(person.is_human)
        if (person.is_bot !== undefined && person.is_bot !== null) return Boolean(person.is_bot)
        const role = String(person.role || "").toLowerCase()
        return role !== "human" && role !== "user" && role !== "you"
    }
    function botId(person) {
        const binding = (room.bindings || []).find(row => String(row.participant_id) === String(person.participant_id || person.id)
            || (person.persona_id && String(row.persona_id) === String(person.persona_id)))
        return String((binding || {}).bot_id || person.bot_id || "")
    }
    function botIndex(person) {
        const id = botId(person)
        return preparedBots.findIndex(row => String(row.id) === id)
    }
    function assignBot(person, index) {
        if (!editCast || index < 0 || index >= preparedBots.length) return
        root.bridge.triggerLiveAddonActionWithPayload("discord_room_bot_binding", {
            participant_id: memberId(person), admission_id: String(person.admission_id || ""), bot_id: String(preparedBots[index].id)})
    }
    function canAssignBot(person) {
        return editCast && (phase !== "running" || (person.can_replace === true && person.role !== "moderator"))
    }
    function beginReplacement() {
        if (!controlById("discord_local_room_replace_persona").enabled) return
        replacementId = selectedId
        replacementAdmission = String(selected.admission_id || "")
        admissionBotId = ""
        panel = "personas"
    }
    function addPersona(id) {
        if (!root.editCast || (!replacementId && !admissionAvailable)) return
        root.setRoomControl("discord_local_room_persona", id)
        const payload = {persona_id: id}
        if (discordMode && admissionBotId) payload.bot_id = admissionBotId
        if (replacementId) {
            payload.participant_id = replacementId
            payload.admission_id = replacementAdmission
            if (runAction("discord_local_room_replace_persona", payload)) replacementId = ""
        } else runAction("discord_local_room_add_persona", payload)
    }
    function added(id) {
        for (let i = 0; i < roster.length; ++i) if (roster[i].persona_id === id) return true
        return false
    }
    function refreshRows() {
        const people = room.participants || []
        const personas = controlById("discord_local_room_state").personaLibrary || []
        // Polls must not destroy a delegate while it is being dragged or clicked.
        for (let i = 0; i < people.length; ++i) {
            const identity = memberId(people[i])
            let at = i
            while (at < participantRows.count && memberId(participantRows.get(at).modelData) !== identity) ++at
            if (at === participantRows.count) participantRows.insert(i, {modelData: people[i]})
            else {
                if (at !== i) participantRows.move(at, i, 1)
                if (JSON.stringify(participantRows.get(i).modelData) !== JSON.stringify(people[i]))
                    participantRows.setProperty(i, "modelData", people[i])
            }
        }
        if (participantRows.count > people.length) participantRows.remove(people.length, participantRows.count - people.length)
        if (JSON.stringify(roster) !== JSON.stringify(people)) roster = people
        if (replacementId && (!participant(replacementId).id || String(participant(replacementId).admission_id || "") !== replacementAdmission)) replacementId = ""
        if (admissionBotId && !freeAccounts.some(row => String(row.bot_id) === admissionBotId)) admissionBotId = ""
        if (JSON.stringify(library) !== JSON.stringify(personas)) library = personas
    }
    function refreshHistoryView() {
        const view = room.history_view || ({})
        const viewParticipant = String(view.participant_id || "")
        const current = String(controlById("discord_local_room_state").selectedParticipantId || selectedId || "")
        const failure = String(root.selected.history_error || (viewParticipant === current ? view.history_error : "") || "")
        const windowSize = Number(view.context_entries || 0)
        const raw = viewParticipant && viewParticipant === current && !failure ? (view.entries || []) : []
        const entries = raw.map(function(entry, index) {
            return {role: String(entry.role || ""), content: String(entry.content || ""),
                    outside_context: windowSize > 0 && index < raw.length - windowSize}
        })
        // Polls rebuild the room object; keep the returned history delegates stable.
        if (JSON.stringify(historyEntries) !== JSON.stringify(entries)) historyEntries = entries
        if (historyModelParticipant !== current) {
            memoryRows.clear()
            historyModelParticipant = current
            memoryDetails = false
        }
        if (memoryRows.count > entries.length) memoryRows.remove(entries.length, memoryRows.count - entries.length)
        for (let i = 0; i < entries.length; ++i) {
            const value = {entryRole: entries[i].role, entryContent: entries[i].content, outsideContext: entries[i].outside_context}
            if (i >= memoryRows.count) memoryRows.append(value)
            else {
                for (const key of ["entryRole", "entryContent", "outsideContext"])
                    if (memoryRows.get(i)[key] !== value[key]) memoryRows.setProperty(i, key, value[key])
            }
        }
    }
    function persistConversationView() {
        if (!viewLoaded) return
        root.setRoomControl("discord_local_room_view_state", {
            conversation_id: String((root.room.conversation || {}).id || ""), room_key: root.roomKey, view_id: viewConversationId, open: chatOpen, enlarged: chatEnlarged,
            viewport: conversationViewport, page_y: savedPageY,
            behavior_draft: root.behaviorDraftDirty ? root.behaviorDraft : null,
            behavior_advanced: root.behaviorAdvanced})
    }
    function loadConversationView() {
        if (!viewMounted) return
        const id = root.roomKey + ":" + String((root.room.conversation || {}).id || "")
        if (viewLoaded && viewConversationId === id) return
        const view = root.room.view_state || ({})
        viewConversationId = id
        conversationViewport = String(view.view_id || (root.roomKey + ":" + String(view.conversation_id || ""))) === id ? (view.viewport || ({})) : ({})
        if (!viewLoaded || (view.room_key && view.room_key === root.roomKey)) {
            chatOpen = Boolean(view.open) || textOnly
            chatEnlarged = Boolean(view.enlarged)
            savedPageY = Number(view.page_y || 0)
            restorePage.restart()
        }
        viewLoaded = true
    }
    onChatOpenChanged: if (viewLoaded && !viewDestroying) viewSave.restart()
    onChatEnlargedChanged: if (viewLoaded && !viewDestroying) viewSave.restart()
    onRoomChanged: {
        if (loadedRoomKey !== roomKey) {
            guidanceSyncTimer.stop()
            viewSave.stop()
            guidanceDraftDirty = false
            behaviorDraftDirty = false
            loadedRoomKey = roomKey
        }
        root.loadDrafts(); refreshRows(); refreshHistoryView(); loadConversationView()
    }
    Component.onCompleted: {
        bridge.refreshLiveAddonControls(); root.loadDrafts(); refreshRows(); refreshHistoryView()
        viewMounted = true
        root.loadBehaviorDraft()
        loadConversationView()
    }
    Component.onDestruction: { viewDestroying = true; viewSave.stop(); persistConversationView() }
    Connections {
        target: root.bridge
        ignoreUnknownSignals: true
        function onLocalRoomControlsRequested() { root.openRoomControls() }
    }
    Timer { id: viewSave; interval: 80; onTriggered: root.persistConversationView() }
    Timer { id: restorePage; interval: 0; onTriggered: if (root.contentItem) root.contentItem.contentY = root.savedPageY }
    Connections {
        target: root.contentItem
        function onContentYChanged() {
            if (root.viewLoaded && !root.viewDestroying && !restorePage.running) {
                root.savedPageY = Number(root.contentItem.contentY || 0)
                viewSave.restart()
            }
        }
    }
    Timer {
        id: guidanceSyncTimer
        objectName: "localRoomGuidanceSyncTimer"
        interval: 180; repeat: false
        onTriggered: root.flushGuidanceDraft()
    }
    Timer {
        objectName: "localRoomRefreshTimer"
        interval: 1500; repeat: true; running: root.visible
        onTriggered: {
            root.bridge.refreshLiveAddonControls()
            if (root.replyCatalog.loading) root.refreshReplyCatalog()
            if (root.panel === "participant" && root.participantTab === "history" && root.selectedId)
                root.refreshParticipantHistory()
        }
    }

    component RoomAction: NCButton {
        required property string actionSuffix
        objectName: "localRoomAction_" + actionSuffix
        text: String(root.controlById("discord_local_room_" + actionSuffix).label || "")
        enabled: root.actionEnabled("discord_local_room_" + actionSuffix)
        onClicked: root.runAction("discord_local_room_" + actionSuffix)
    }
    component RoomMenuItem: MenuItem {
        id: roomMenuItem
        required property string actionSuffix
        text: String(root.controlById("discord_local_room_" + actionSuffix).label || "")
        enabled: root.actionEnabled("discord_local_room_" + actionSuffix)
        implicitHeight: Theme.NCMetrics.controlHeight
        contentItem: Label {
            text: roomMenuItem.text
            textFormat: Text.PlainText
            color: roomMenuItem.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 6
            color: roomMenuItem.highlighted ? Theme.NCTheme.surfaceSelected : "transparent"
        }
        onTriggered: root.runAction("discord_local_room_" + actionSuffix)
    }
    component RoomTextField: TextField {
        id: roomTextField
        property string toolTipText: ""
        NCHelp { target: roomTextField; text: roomTextField.toolTipText }
        color: Theme.NCTheme.text
        placeholderTextColor: Theme.NCTheme.textMuted
        selectionColor: Theme.NCTheme.selection
        selectedTextColor: Theme.NCTheme.text
        leftPadding: 12; rightPadding: 12
        background: Rectangle {
            implicitHeight: 40; radius: 8
            color: Theme.NCTheme.window
            border.color: parent.activeFocus ? Theme.NCTheme.accent : Theme.NCTheme.borderStrong
        }
    }
    Menu {
        id: participantMenu
        objectName: "localRoomParticipantMenu"
        parent: root
        width: 232
        palette.text: Theme.NCTheme.text
        palette.window: Theme.NCTheme.surface
        palette.highlight: Theme.NCTheme.accentStrong
        palette.highlightedText: Theme.NCTheme.textInverse
        background: Rectangle { radius: 8; color: Theme.NCTheme.surface; border.color: Theme.NCTheme.borderStrong }
        MenuItem {
            text: qsTr("Guide bot…"); objectName: "localRoomMenuGuide"
            enabled: root.phase === "running" && !root.room.paused && !root.room.stopping && !root.directivePending && !root.selected.muted && String(root.selected.membership_phase || "ready") === "ready" && (!root.discordMode || root.selected.role === "moderator")
            onTriggered: root.openBotComposer("guide", root.selectedId)
        }
        MenuItem {
            text: qsTr("Speak through bot…"); objectName: "localRoomMenuSpeak"
            enabled: root.phase === "running" && !root.room.paused && !root.room.stopping && !root.directivePending && !root.selected.muted && String(root.selected.membership_phase || "ready") === "ready" && (!root.discordMode || root.selected.role === "moderator")
            onTriggered: root.openBotComposer("announce", root.selectedId)
        }
        MenuSeparator {}
        RoomMenuItem { actionSuffix: "next" }
        RoomMenuItem { actionSuffix: "invite" }
        RoomMenuItem { actionSuffix: root.selected.muted ? "unmute_participant" : "mute_participant" }
        MenuSeparator {}
        MenuItem { text: root.discordMode ? qsTr("Room transcript…") : qsTr("Room memory…"); onTriggered: root.openParticipantHistory(root.selectedId) }
        MenuItem { text: qsTr("Persona settings…"); onTriggered: root.selectParticipant(root.selectedId) }
        Menu {
            title: qsTr("Manage participant"); palette: participantMenu.palette
            RoomMenuItem { actionSuffix: "set_moderator"; enabled: !root.active && root.actionEnabled("discord_local_room_set_moderator") }
            MenuItem { text: qsTr("Replace Persona…"); enabled: Boolean(root.controlById("discord_local_room_replace_persona").enabled); onTriggered: root.beginReplacement() }
            RoomMenuItem { actionSuffix: "retry_join" }
            MenuItem { text: qsTr("Remove from room…"); enabled: root.actionEnabled("discord_local_room_remove"); onTriggered: root.requestParticipantRemoval() }
        }
        Menu {
            title: qsTr("Room actions"); palette: participantMenu.palette
            RoomMenuItem { actionSuffix: "clear_next" }
            RoomMenuItem { actionSuffix: "skip_speech"; visible: !root.discordMode; height: visible ? implicitHeight : 0 }
        RoomMenuItem { actionSuffix: "stop_speech" }
        }
    }
    Rectangle {
        id: personaDrag
        objectName: "localRoomPersonaDrag"
        parent: root
        property bool dragging: false
        property string personaId: ""
        property string personaName: ""
        width: 180; height: 48; radius: 8; z: 100
        color: Theme.NCTheme.surfaceRaised
        border.color: Theme.NCTheme.accent
        visible: dragging
        Drag.active: dragging
        Drag.keys: ["nc-persona"]
        Drag.source: personaDrag
        Drag.hotSpot.x: width / 2
        Drag.hotSpot.y: height / 2
        Label { anchors.centerIn: parent; text: personaDrag.personaName; textFormat: Text.PlainText; color: Theme.NCTheme.text }
    }

    ColumnLayout {
        width: root.availableWidth
        spacing: 10
        GridLayout {
            Layout.fillWidth: true
            columns: root.availableWidth >= 740 ? 4 : 2
            ColumnLayout {
                Layout.fillWidth: true
                Layout.columnSpan: root.availableWidth >= 740 ? 1 : 2
                Label { text: root.roomTitle; color: Theme.NCTheme.text; font.pixelSize: 24; font.bold: true }
                Label {
                    Layout.fillWidth: true
                    visible: root.roomInfoVisible
                    text: qsTr("A place to talk, listen and bring your Personas together.")
                    wrapMode: Text.WordWrap; color: Theme.NCTheme.textMuted
                }
            }
            NCButton {
                id: selfMenuButton; objectName: "localRoomSelfMenuButton"; visible: !root.discordMode
                text: String(root.room.user_name || "You") + (root.joined ? qsTr(" (you) · Joined ⋯") : qsTr(" (you) · Observing ⋯"))
                toolTipText: qsTr("Your room controls: join or observe, microphone, speak next, display name and room-wide anonymity. Click or right-click to open.")
                onClicked: root.openSelfMenu()
                TapHandler { acceptedButtons: Qt.RightButton; onTapped: eventPoint => root.openSelfMenu(selfMenuButton, eventPoint.position.x, eventPoint.position.y) }
            }
            NCComboBox {
                toolTipText: qsTr("Choose a desktop-only Local room or a Discord voice-channel room while the room is stopped. Discord requires prepared bot accounts.")

                objectName: "discordRoomMode"
                label: qsTr("Room transport")
                model: [qsTr("Local"), qsTr("Discord")]
                currentIndex: root.discordMode ? 1 : 0
                enabled: Boolean(root.controlById("discord_room_mode").enabled)
                onActivated: index => root.setRoomControl("discord_room_mode", index === 1 ? "discord" : "local")
            }
            Label {
                text: root.room.stopping ? qsTr("Stopping…") : root.room.pausing ? qsTr("Pausing…") : root.room.paused ? qsTr("Paused") : root.phase === "idle" ? qsTr("Ready") : root.phase
                textFormat: Text.PlainText
                color: root.phase === "running" ? Theme.NCTheme.accent : Theme.NCTheme.textMuted
            }
        }
        RowLayout {
            visible: root.discordMode
            Layout.fillWidth: true; spacing: 10
            Label {
                objectName: "discordRoomConnection"; visible: root.discordMode
                Layout.fillWidth: true; textFormat: Text.PlainText; wrapMode: Text.Wrap
                text: qsTr("Server: %1 · Voice: %2 · %3")
                    .arg(String(root.room.guild_name || root.room.guild_id || root.room.server_id || qsTr("Not configured")))
                    .arg(String(root.room.channel_name || root.room.channel_id || qsTr("Not configured")))
                    .arg(String(root.room.connection_status || (root.active ? root.phase : qsTr("Stopped"))))
                color: Theme.NCTheme.textMuted
            }
        }
        Flow {
            Layout.fillWidth: true; spacing: 8
            NCButton {
                objectName: "localRoomStart"
                text: root.room.stopping ? qsTr("Stopping…") : root.active ? qsTr("Stop room")
                    : root.continuingConversation ? qsTr("Continue conversation") : qsTr("Start room")
                tone: root.active ? "danger" : "primary"
                enabled: Boolean(root.controlById(root.active ? "discord_local_room_stop" : "discord_local_room_start").enabled)
                onClicked: root.runAction(root.active ? "discord_local_room_stop" : "discord_local_room_start")
            }
            NCButton {
                objectName: "localRoomNewConversation"
                text: qsTr("New conversation")
                enabled: Boolean(root.controlById("discord_local_room_new_conversation").enabled)
                onClicked: newConversationDialog.open()
            }
            RoomAction {
                objectName: "localRoomPause"
                actionSuffix: root.room.paused ? "resume" : "pause"
                toolTipText: qsTr("Finish the current speaker, then pause. The next speaker and prepared reply are kept until you resume.")
            }
            NCButton {
                objectName: "localRoomConversationDetails"
                text: qsTr("Conversation details")
                onClicked: root.openConversationDetails()
            }
            NCButton { objectName: "localRoomAddPersonas"; enabled: root.editCast; text: qsTr("+ Add Personas"); onClicked: { root.replacementId = ""; root.panel = "personas" } }
            NCButton { objectName: "localRoomControls"; text: qsTr("Room controls"); onClicked: root.openRoomControls() }
        }
        Rectangle {
            id: conversationStatus
            objectName: "localRoomConversationStatus"
            Layout.fillWidth: true
            implicitHeight: statusBody.implicitHeight + (root.roomInfoVisible ? 24 : 12)
            radius: 8
            color: Theme.NCTheme.surface
            border.color: Theme.NCTheme.borderStrong
            Rectangle {
                width: 3
                radius: 2
                color: Theme.NCTheme.accent
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.margins: 1
            }
            ColumnLayout {
                id: statusBody
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: root.roomInfoVisible ? 12 : 6; anchors.leftMargin: 12
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.roomInfoVisible
                    Label {
                        objectName: "localRoomConversationPhase"
                        text: root.conversationPhaseText
                        textFormat: Text.PlainText
                        color: Theme.NCTheme.accent
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        objectName: "localRoomAiParticipantCount"
                        visible: root.aiParticipantCount > 0
                        text: qsTr("%1 Personas in the room").arg(root.aiParticipantCount)
                        textFormat: Text.PlainText
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: 12
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        objectName: "localRoomConversationTopic"
                        Layout.fillWidth: true
                        text: root.conversationTopic.length > 0 ? root.conversationTopic : qsTr("No topic set")
                        textFormat: Text.PlainText
                        color: Theme.NCTheme.text
                        font.pixelSize: 16
                        font.bold: true
                        wrapMode: root.roomInfoVisible ? Text.WordWrap : Text.NoWrap
                        elide: Text.ElideRight
                    }
                    NCButton {
                        objectName: "localRoomInfoToggle"; visible: !root.discordMode
                        compact: true; tone: "quiet"
                        text: root.roomDetailsExpanded ? qsTr("Less info") : qsTr("More info")
                        toolTipText: qsTr("Show or hide saved-conversation information and the turn-taking summary. This changes only the layout.")
                        onClicked: root.roomDetailsExpanded = !root.roomDetailsExpanded
                    }
                    NCButton {
                        objectName: "localRoomConversationTopicAction"
                        compact: true
                        tone: "quiet"
                        text: root.conversationTopic.length > 0 ? qsTr("Edit topic…") : qsTr("Set topic…")
                        toolTipText: qsTr("Set, change or clear the shared discussion focus. This preserves conversation history.")
                        onClicked: root.openTopicEditor()
                    }
                }
                Label {
                    objectName: "localRoomConversationHistorySummary"
                    visible: root.roomInfoVisible
                    Layout.fillWidth: true
                    text: root.conversationHistorySummary
                    textFormat: Text.PlainText
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Label {
                    objectName: "localRoomConversationSaved"
                    visible: root.roomInfoVisible
                    Layout.fillWidth: true
                    text: qsTr("Saved automatically · each participant remembers only what they heard while in the room")
                    textFormat: Text.PlainText
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
            }
        }
        Label {
            objectName: "localRoomBehaviorSummary"
            visible: root.roomInfoVisible
            Layout.fillWidth: true
            text: root.behaviorSummary
            textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap
        }
        Rectangle {
            Layout.fillWidth: true; implicitHeight: liveControls.implicitHeight + 12
            radius: 8; color: Theme.NCTheme.surfaceRaised
            GridLayout {
                id: liveControls
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6
                columns: root.availableWidth >= 900 ? 4 : 2
                columnSpacing: 8; rowSpacing: 6
                Label {
                    id: nowLabel
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    Layout.columnSpan: root.availableWidth >= 900 ? 1 : 2
                text: root.room.stopping ? (root.room.pausing ? qsTr("Finishing the current speaker, then saving and stopping the room…") : qsTr("Saving and stopping the room…"))
                      : root.room.pausing ? qsTr("Pausing after ") + String(root.participant(root.room.current_id).name || qsTr("the current speaker"))
                          + qsTr(" finishes · Next: ") + String(root.participant(root.room.next_id).name || qsTr("Open floor"))
                      : root.room.paused ? qsTr("Room paused · resume when you are ready · Next: ")
                          + String(root.participant(root.room.next_id).name || qsTr("Open floor"))
                      : qsTr("Now: ") + String(root.participant(root.room.current_id).name || (root.phase === "running" ? qsTr("Listening") : qsTr("Room quiet")))
                        + "     ·     " + qsTr("Next: ") + String(root.participant(root.room.next_id).name || qsTr("Open floor"))

                    textFormat: Text.PlainText; color: Theme.NCTheme.text; wrapMode: Text.WordWrap
                }
                NCButton { objectName: "localRoomRoomActions"; text: qsTr("Room actions ⋯"); onClicked: roomActionsMenu.popup() }
                RoomAction { actionSuffix: "skip_speech"; visible: !root.discordMode; toolTipText: qsTr("Stop this reply’s voice, keep the complete message, and count it as delivered to the participants present when you skip.") }
                RoomAction { actionSuffix: "stop_speech"; toolTipText: qsTr("Stop the current speech immediately and hold the room until you resume.") }
            }
        }
        Label {
            objectName: "localRoomRecoveryStatus"
            Layout.fillWidth: true
            visible: Boolean((root.room.pending_recovery || {}).token)
            text: (root.room.pending_recovery || {}).status === "waiting_for_cooldown"
                ? qsTr("Moderator restart waiting for cooldown")
                : Boolean((root.room.pending_recovery || {}).playback_ready)
                ? qsTr("Moderator restart ready · waiting for the current turn and speaker selection to finish")
                : qsTr("Preparing moderator restart")
            textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
        }
        Label {
            objectName: "localRoomDirectiveStatus"
            Layout.fillWidth: true
            visible: root.directiveStatusText.length > 0
            text: root.directiveStatusText
            textFormat: Text.PlainText
            color: root.directiveStatusColor
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }
        Label {
            Layout.fillWidth: true; visible: text.length > 0
            text: String(root.room.error || ""); textFormat: Text.PlainText
            color: Theme.NCTheme.error; wrapMode: Text.WordWrap
        }
        GridLayout {
            id: roomGrid
            Layout.fillWidth: true
            columns: root.wide ? 2 : 1
            columnSpacing: 16; rowSpacing: 16
            Rectangle {
                id: roomCards
                objectName: "localRoomCards"
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                implicitHeight: cards.implicitHeight + 32
                color: drop.containsDrag ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
                border.color: drop.containsDrag ? Theme.NCTheme.accent : Theme.NCTheme.borderStrong
                radius: 12
                MouseArea {
                    anchors.fill: parent; acceptedButtons: Qt.RightButton
                    onClicked: mouse => roomActionsMenu.popup(roomCards, mouse.x, mouse.y)
                }
                DropArea {
                    id: drop
                    objectName: "localRoomPersonaDrop"
                    anchors.fill: parent; keys: ["nc-persona"]
                    onDropped: function(event) {
                        if (root.editCast && event.source && event.source.personaId) {
                            root.addPersona(String(event.source.personaId))
                            event.acceptProposedAction()
                        }
                    }
                }
                ColumnLayout {
                    id: cards
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.top: parent.top; anchors.margins: 16; spacing: 12
                    Label {
                        text: drop.containsDrag ? qsTr("Drop to add this Persona") : qsTr("In the room")
                        font.bold: true; color: Theme.NCTheme.text
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: (!root.externalConversation && root.chatOpen) || (root.textOnly && !root.discordMode) ? Math.max(1, Math.floor((width + 10) / 155))
                            : !root.discordMode && width >= 720 ? 4 : width >= 540 ? 3 : width >= 340 ? 2 : 1
                        columnSpacing: 10; rowSpacing: 10
                        Repeater {
                            model: participantRows
                            delegate: Rectangle {
                                id: tile
                                required property var modelData
                                readonly property bool speaking: Boolean(modelData.speaking)
                                readonly property bool hasFloor: Boolean(modelData.has_floor)
                                readonly property bool isNext: Boolean(modelData.is_next) && !Boolean(modelData.muted)
                                readonly property bool human: modelData.role === "human"
                                readonly property bool compactTile: (!root.externalConversation && root.chatOpen) || (root.textOnly && !root.discordMode)
                                objectName: "localRoomParticipant_" + String(modelData.id)
                                Layout.fillWidth: true; Layout.preferredHeight: tile.compactTile ? (root.discordMode && !tile.human ? 110 : 66) : tile.human ? 168 : root.discordMode ? 248 : 198
                                Layout.minimumWidth: tile.compactTile ? 120 : 140
                                radius: 10
                                color: speaking ? Theme.NCTheme.surfaceRaised : isNext ? Theme.NCTheme.infoSoft
                                     : root.selectedId === root.memberId(modelData) ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.window
                                border.width: hasFloor || speaking || isNext || root.selectedId === root.memberId(modelData) ? 2 : 1
                                border.color: hasFloor ? Theme.NCTheme.success : speaking ? Theme.NCTheme.accent
                                            : isNext ? Theme.NCTheme.info : root.selectedId === root.memberId(modelData) ? Theme.NCTheme.accent : Theme.NCTheme.borderStrong
                                Accessible.name: String(modelData.name) + (modelData.muted ? ", listener only" : "") + (hasFloor ? ", has the floor" : "") + (speaking ? ", speaking" : "") + (isNext ? ", up next" : "")
                                activeFocusOnTab: true
                                Keys.onReturnPressed: root.selectParticipant(String(modelData.id))
                                Keys.onSpacePressed: root.selectParticipant(String(modelData.id))
                                MouseArea {
                                    anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                                    onClicked: function(mouse) {
                                        if (mouse.button === Qt.RightButton)
                                            root.openParticipantMenu(String(tile.modelData.id), tile, mouse.x, mouse.y)
                                        else root.selectParticipant(String(tile.modelData.id))
                                    }
                                }
                                Rectangle {
                                    objectName: "localRoomNextBadge_" + String(tile.modelData.id)
                                    visible: tile.isNext && !tile.compactTile
                                    anchors.top: parent.top; anchors.left: parent.left; anchors.margins: 10
                                    width: nextLabel.implicitWidth + 16; height: 22; radius: 6
                                    color: Theme.NCTheme.info
                                    Label {
                                        id: nextLabel
                                        anchors.centerIn: parent
                                        text: qsTr("UP NEXT")
                                        font.pixelSize: 10; font.bold: true
                                        color: Theme.NCTheme.textInverse
                                    }
                                }
                                Rectangle {
                                    id: avatar
                                    width: tile.compactTile ? 30 : 54; height: width; radius: width / 2
                                    anchors.horizontalCenter: tile.compactTile ? undefined : parent.horizontalCenter
                                    anchors.left: tile.compactTile ? parent.left : undefined; anchors.leftMargin: 10
                                    anchors.verticalCenter: tile.compactTile ? parent.verticalCenter : undefined
                                    anchors.top: tile.compactTile ? undefined : parent.top; anchors.topMargin: tile.isNext ? 42 : 18
                                    color: tile.speaking ? Theme.NCTheme.accentStrong : Theme.NCTheme.surfaceRaised
                                    Image { anchors.fill: parent; source: String(tile.modelData.avatar_url || ""); fillMode: Image.PreserveAspectCrop; visible: status === Image.Ready }
                                    Label {
                                        anchors.centerIn: parent; visible: !tile.modelData.avatar_url
                                        text: String(tile.modelData.name || "?").slice(0, 1).toUpperCase()
                                        font.pixelSize: tile.compactTile ? 14 : 24; font.bold: true; color: Theme.NCTheme.text
                                    }
                                }
                                NCButton {
                                    id: cardActions
                                    anchors.top: parent.top; anchors.right: parent.right
                                    visible: !tile.human || !root.discordMode
                                    iconOnly: true; compact: true; tone: "quiet"; iconText: tile.human ? "Aa" : "..."
                                    text: tile.human ? qsTr("Your room controls") : qsTr("Participant actions")
                                    onClicked: root.openParticipantMenu(String(tile.modelData.id), cardActions, 0, cardActions.height)
                                }
                                Rectangle {
                                    id: historyFooter
                                    visible: !tile.human && !tile.compactTile
                                    anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                                    height: visible ? 30 : 0
                                    color: "transparent"
                                    Rectangle {
                                        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
                                        height: 1
                                        color: Theme.NCTheme.borderStrong
                                    }
                                    Label {
                                        anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                                        verticalAlignment: Text.AlignVCenter
                                        text: root.discordMode ? (tile.modelData.history_error ? qsTr("Transcript unavailable")
                                            : Number(tile.modelData.history_count || 0) > 0 ? qsTr("Delivered transcript: %1 entries").arg(Number(tile.modelData.history_count || 0))
                                            : qsTr("No delivered speech yet"))
                                            : tile.modelData.history_error ? qsTr("History unavailable") : Number(tile.modelData.history_count || 0) > 0
                                            ? qsTr("Room memory · %1 entries").arg(Number(tile.modelData.history_count || 0))
                                            : qsTr("No previous room memory")
                                        textFormat: Text.PlainText
                                        elide: Text.ElideRight
                                        font.pixelSize: 11
                                        color: historyFooterMouse.containsMouse ? Theme.NCTheme.text : Theme.NCTheme.textMuted
                                    }
                                    MouseArea {
                                        id: historyFooterMouse
                                        objectName: "localRoomHistory_" + String(tile.modelData.id)
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        onClicked: root.openParticipantHistory(String(tile.modelData.id))
                                    }
                                }
                                ColumnLayout {
                                    anchors.left: tile.compactTile ? avatar.right : parent.left
                                    anchors.right: parent.right; anchors.rightMargin: tile.compactTile ? 30 : 12
                                    anchors.bottom: tile.compactTile ? undefined : historyFooter.top
                                    anchors.verticalCenter: tile.compactTile ? parent.verticalCenter : undefined
                                    anchors.leftMargin: tile.compactTile ? 8 : 12; anchors.bottomMargin: 12
                                    spacing: 4
                                    Label { Layout.fillWidth: true; text: String(tile.modelData.name || "") + (tile.human && !root.discordMode && tile.modelData.name !== "You" ? qsTr(" (you)") : ""); textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.NCTheme.text; font.bold: true }
                                    Label {
                                        Layout.fillWidth: true
                                        text: tile.modelData.membership_phase === "joining" ? qsTr("Joining")
                                            : tile.modelData.membership_phase === "leaving" ? qsTr("Leaving after this reply")
                                            : tile.modelData.membership_phase === "failed" ? qsTr("Failed · Retry join")
                                            : tile.speaking ? (tile.modelData.muted ? qsTr("Finishing reply · then listener") : qsTr("Speaking"))
                                            : tile.modelData.muted ? (root.discordMode ? qsTr("Routing muted") : qsTr("Listener only · muted"))
                                            : tile.human && root.discordMode ? (tile.hasFloor ? qsTr("Has the floor · Discord microphone") : tile.isNext ? qsTr("Up next") : qsTr("Connected in Discord"))
                                            : tile.human && !root.joined ? qsTr("Observing · not participating")
                                            : tile.human && tile.hasFloor ? ((root.room.muted || root.textOnly) ? qsTr("Your turn · mic off · chat available") : qsTr("Your turn"))
                                            : tile.human && (root.room.muted || root.textOnly) ? qsTr("Mic off · chat available")
                                            : tile.isNext ? qsTr("Up next")
                                            : tile.hasFloor ? qsTr("Has the floor")
                                            : root.active && !tile.modelData.connected ? qsTr("Connecting…")
                                            : String(tile.modelData.role || "")
                                        textFormat: Text.PlainText; elide: Text.ElideRight; font.pixelSize: 12
                                        color: tile.hasFloor ? Theme.NCTheme.success : tile.speaking ? Theme.NCTheme.accent : tile.isNext ? Theme.NCTheme.info : Theme.NCTheme.textMuted
                                    }
                                    Label {
                                        visible: root.discordMode && !tile.human
                                        text: qsTr("Prepared bot"); color: Theme.NCTheme.textMuted; font.pixelSize: 11
                                    }
                                    NCComboBox {
                                        toolTipText: qsTr("Assign an available prepared Discord bot account to this Persona. Each room Persona needs its own account.")

                                        objectName: "discordRoomBot_" + String(tile.modelData.id)
                                        label: qsTr("Prepared bot for %1").arg(String(tile.modelData.name || ""))
                                        visible: root.discordMode && !tile.human
                                        Layout.fillWidth: true
                                        model: root.preparedBots; textRole: "name"; valueRole: "id"
                                        currentIndex: root.botIndex(tile.modelData)
                                        enabled: root.canAssignBot(tile.modelData) && Boolean(root.controlById("discord_room_bot_binding").enabled)
                                        onActivated: index => root.assignBot(tile.modelData, index)
                                    }
                                }
                            }
                        }
                    }
                    Label { Layout.fillWidth: true; text: qsTr("Click a participant for controls · right-click for quick actions"); color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap; font.pixelSize: 12 }
                    NCButton {
                        objectName: "localRoomOpenConversation"
                        Layout.fillWidth: true
                        visible: root.externalConversation
                        text: qsTr("Open conversation")
                        onClicked: root.bridge.openLocalRoomConversation()
                    }
                    LocalRoomConversation {
                        id: roomConversation
                        appearanceBridge: root.bridge
                        visible: !root.externalConversation
                        Layout.fillWidth: true
                        entries: root.room.display_messages !== undefined
                                 ? root.room.display_messages : root.room.messages || []
                        conversationId: root.roomKey + ":" + String(root.conversation.id || "")
                        savedViewport: root.conversationViewport
                        expanded: root.chatOpen || root.textOnly
                        enlarged: root.chatEnlarged
                        onToggleRequested: root.chatOpen = !root.chatOpen
                        onEnlargeRequested: root.chatEnlarged = !root.chatEnlarged
                        onViewportChanged: function(value) {
                            root.conversationViewport = value
                            if (root.viewLoaded && !root.viewDestroying) viewSave.restart()
                        }
                    }
                }
            }
            Rectangle {
                objectName: "localRoomDetailsPanel"
                visible: root.panel.length > 0
                Layout.fillWidth: !root.wide
                Layout.preferredWidth: root.wide ? 294 : -1
                Layout.alignment: Qt.AlignTop
                implicitHeight: Math.min(side.implicitHeight + 32, Math.max(260, root.availableHeight - roomGrid.y - 100))
                radius: 12; color: Theme.NCTheme.surface; border.color: Theme.NCTheme.borderStrong
                ScrollView {
                    id: detailsScroll
                    objectName: "localRoomDetailsScroll"
                    anchors.fill: parent; anchors.margins: 16
                    clip: true; contentWidth: availableWidth
                    ColumnLayout {
                        id: side
                        width: detailsScroll.availableWidth; spacing: 12
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: root.panel === "conversation" ? qsTr("Conversation details")
                                    : root.panel === "personaOverrides" ? qsTr("%1 · Overrides").arg(root.overrideEditingPersonaName)
                                    : root.panel === "participant" && root.selected.id ? String(root.selected.name)
                                    : qsTr("Your Persona library")
                                textFormat: Text.PlainText; font.bold: true; color: Theme.NCTheme.text; wrapMode: Text.WordWrap
                            }
                            NCButton {
                                objectName: "localRoomPanelClose"
                                compact: true; tone: "quiet"
                                text: root.panel === "controls" ? qsTr("Close") : root.panel === "personas" ? qsTr("Controls") : qsTr("Back")
                                onClicked: root.panel = root.panel === "personaOverrides" ? "participant" : ""
                            }
                        }
                        ColumnLayout {
                            visible: root.panel === "personaOverrides"
                            Layout.fillWidth: true
                            spacing: 10
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("Saved on this Persona everywhere it is used. Changes apply to new requests after Save; the current reply keeps its captured settings.")
                                textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap
                            }
                            PersonaOverridesEditor {
                                id: roomOverridesEditor
                                objectName: "localRoomPersonaOverridesEditor"
                                Layout.fillWidth: true
                                bridge: root.bridge
                                personaId: root.overrideEditingPersonaId
                                conversationLabel: qsTr("Room default")
                                inheritedSourceLabel: qsTr("Room defaults")
                                inheritedDefaults: root.overrideEditingDefaults
                            }
                            NCButton {
                                objectName: "localRoomOverridesCancel"
                                Layout.fillWidth: true
                                text: qsTr("Back to participant")
                                onClicked: root.panel = "participant"
                            }
                        }
                        ColumnLayout {
                            visible: root.panel === "participant"; Layout.fillWidth: true; spacing: 10
                            Label { Layout.fillWidth: true; text: root.selected.id ? String(root.selected.role || "") : qsTr("This participant has left the room."); textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap }
                            ColumnLayout {
                                objectName: "localRoomReplySettings"
                                visible: root.selected.role !== "human" && Boolean(root.selected.id)
                                Layout.fillWidth: true; spacing: 6
                                Label { text: qsTr("Reply settings"); font.bold: true; color: Theme.NCTheme.text }
                                Label {
                                    objectName: "localRoomReplySummary"; Layout.fillWidth: true; Layout.minimumWidth: 0
                                    text: root.replySummary
                                    textFormat: Text.PlainText; color: Theme.NCTheme.textSecondary; elide: Text.ElideRight
                                    ToolTip.visible: summaryHover.hovered
                                    ToolTip.text: text
                                    HoverHandler { id: summaryHover }
                                }
                                Label {
                                    objectName: "localRoomReplyWarning"; Layout.fillWidth: true
                                    visible: root.replyWarning.length > 0
                                    text: root.replyWarning
                                    textFormat: Text.PlainText; color: Theme.NCTheme.warning; wrapMode: Text.WordWrap
                                }
                                NCButton {
                                    objectName: "localRoomReplyDetailsToggle"; compact: true; tone: "quiet"
                                    text: root.replyDetails ? qsTr("Hide sources") : qsTr("Settings and sources")
                                    onClicked: root.replyDetails = !root.replyDetails
                                }
                                Label {
                                    objectName: "localRoomReplySources"; visible: root.replyDetails; Layout.fillWidth: true
                                    text: qsTr("Connection: %1 · %2").arg(String(root.replySettings.provider || qsTr("None"))).arg(root.replySourceLabel(root.replySettings.provider_source))
                                        + "\n" + qsTr("Model: %1 · %2").arg(String(root.replySettings.model || qsTr("None"))).arg(root.replySourceLabel(root.replySettings.model_source || root.replySettings.provider_source))
                                        + "\n" + qsTr("Context: %1 · %2").arg(Number(root.replySettings.context_messages) === 0 ? qsTr("All messages") : qsTr("%1 messages").arg(Number(root.replySettings.context_messages || 20))).arg(root.replySourceLabel(root.replySettings.context_source))
                                        + "\n" + qsTr("Document recall: %1 · %2").arg(root.replyRecallEnabled ? qsTr("Enabled") : qsTr("Disabled")).arg(root.replySourceLabel(root.replySettings.document_memory_source))
                                        + "\n" + qsTr("Package: %1 · %2").arg(root.replyPackageName).arg(root.replySourceLabel(root.replySettings.document_package_source))
                                        + "\n" + qsTr("Availability is checked when replying. For new requests; the current reply keeps its captured settings.")
                                    textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WrapAnywhere
                                }
                                NCButton {
                                    objectName: "localRoomEditPersonaOverrides"; Layout.fillWidth: true
                                    visible: Boolean(root.selected.persona_id)
                                    text: qsTr("Edit Persona overrides")
                                    onClicked: root.openPersonaOverrides()
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true; spacing: 8
                                NCButton {
                                    objectName: "localRoomParticipantControls"
                                    Layout.fillWidth: true
                                    text: qsTr("Controls")
                                    tone: root.participantTab === "controls" ? "primary" : "secondary"
                                    onClicked: root.participantTab = "controls"
                                }
                                NCButton {
                                    objectName: "localRoomParticipantHistory"
                                    Layout.fillWidth: true
                                    text: root.discordMode ? qsTr("Transcript") : qsTr("Memory")
                                    tone: root.participantTab === "history" ? "primary" : "secondary"
                                    enabled: Boolean(root.selected.id) && root.selected.role !== "human"
                                    toolTipText: root.discordMode ? qsTr("Confirmed delivered speech from the whole Discord room.") : qsTr("What this participant remembers from this Local room.")
                                    onClicked: root.openParticipantHistory()
                                }
                            }
                            ColumnLayout {
                                visible: root.participantTab === "controls"; Layout.fillWidth: true; spacing: 10
                                Label {
                                    visible: Boolean(root.selected.muted); Layout.fillWidth: true
                                    text: root.discordMode ? qsTr("Routing muted. This does not change Discord server mute.") : qsTr("Listener only · still hears the room. Unmute to let this participant speak again.")
                                    color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap; font.pixelSize: 12
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; visible: root.selected.role === "human" && !root.discordMode; spacing: 8
                                    Label { Layout.fillWidth: true; text: qsTr("Your name in this room"); font.bold: true; color: Theme.NCTheme.text; wrapMode: Text.WordWrap }
                                    RoomTextField {
                                        objectName: "localRoomUserName"; Layout.fillWidth: true
                                        toolTipText: qsTr("Your name for new typed and spoken messages in this Local room. Save name or press Enter to apply; earlier messages retain their original names.")
                                        text: root.userNameDraft
                                        onTextEdited: root.userNameDraft = text
                                        onAccepted: if (text.trim().length > 0) root.runAction("discord_local_room_save_name", {name: text})
                                    }
                                    NCButton {
                                        objectName: "localRoomSaveName"; Layout.fillWidth: true; tone: "primary"
                                        text: qsTr("Save name")
                                        enabled: Boolean(root.controlById("discord_local_room_save_name").enabled) && root.userNameDraft.trim().length > 0
                                        onClicked: root.runAction("discord_local_room_save_name", {name: root.userNameDraft})
                                    }
                                    Label { Layout.fillWidth: true; text: qsTr("Participants see this name for typed and spoken messages. Earlier messages keep their original names."); color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap }
                                }
                                RoomAction { actionSuffix: "next"; Layout.fillWidth: true; tone: "primary" }
                                RoomAction { actionSuffix: "invite"; Layout.fillWidth: true; toolTipText: qsTr("Invite this speaker when the room is quiet.") }
                                RoomAction { actionSuffix: root.selected.muted ? "unmute_participant" : "mute_participant"; Layout.fillWidth: true }
                                Label { visible: root.selected.role !== "human"; Layout.fillWidth: true; text: qsTr("Voice: %1 · linked to Persona").arg(root.selected.voice_path ? String(root.selected.voice_path).split(/[\\/]/).pop() : qsTr("Default voice")); textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; wrapMode: Text.WrapAnywhere }
                                Label { visible: Boolean(root.selected.membership_error); text: String(root.selected.membership_error || ""); Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.NCTheme.error }
                                NCButton { objectName: "localRoomReplacePersona"; Layout.fillWidth: true; text: qsTr("Replace persona"); enabled: Boolean(root.controlById("discord_local_room_replace_persona").enabled); onClicked: root.beginReplacement() }
                                NCButton { objectName: "localRoomRetryJoin"; Layout.fillWidth: true; text: qsTr("Retry join"); enabled: Boolean(root.controlById("discord_local_room_retry_join").enabled); onClicked: root.runAction("discord_local_room_retry_join") }
                                RoomAction { actionSuffix: "set_moderator"; Layout.fillWidth: true; enabled: !root.active && root.actionEnabled("discord_local_room_set_moderator") }
                                NCButton { text: qsTr("Remove from room…"); Layout.fillWidth: true; tone: "danger"; enabled: root.actionEnabled("discord_local_room_remove"); onClicked: root.requestParticipantRemoval() }
                            }
                            ColumnLayout {
                                objectName: "localRoomHistoryPanel"
                                visible: root.participantTab === "history"; Layout.fillWidth: true; spacing: 8
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { Layout.fillWidth: true; text: root.discordMode ? qsTr("Delivered room transcript") : qsTr("%1’s memory").arg(String(root.selected.name || "")); font.bold: true; textFormat: Text.PlainText; color: Theme.NCTheme.text; wrapMode: Text.WordWrap }
                                    NCButton {
                                        objectName: "localRoomHistoryRefresh"
                                        compact: true; tone: "quiet"; text: qsTr("Refresh")
                                        enabled: Boolean(root.controlById("discord_local_room_view_history").enabled)
                                        onClicked: root.refreshParticipantHistory()
                                    }
                                }
                                ColumnLayout {
                                    visible: root.historyAvailable; Layout.fillWidth: true; spacing: 6
                                    Label {
                                        objectName: "localRoomHistorySummary"; Layout.fillWidth: true
                                        text: root.historyCountText + (root.discordMode ? qsTr(" - delivered speech in this Discord room") : qsTr(" · stored only in this Local room"))
                                        textFormat: Text.PlainText; color: Theme.NCTheme.textSecondary; wrapMode: Text.WordWrap
                                    }
                                    Label {
                                        objectName: "localRoomHistoryWindow"; Layout.fillWidth: true
                                        visible: root.memoryDetails
                                        text: root.discordMode ? qsTr("All confirmed delivered speech from this room, across participants.") : root.historyWindowText
                                        textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
                                    }
                                    NCButton {
                                        compact: true; tone: "quiet"; text: root.discordMode ? (root.memoryDetails ? qsTr("Hide transcript details") : qsTr("Transcript details")) : root.memoryDetails ? qsTr("Hide context details") : qsTr("Context details")
                                        onClicked: root.memoryDetails = !root.memoryDetails
                                    }
                                    Label {
                                        objectName: "localRoomHistoryNone"
                                        visible: root.historyEntries.length === 0
                                        Layout.fillWidth: true
                                        text: root.discordMode ? qsTr("No delivered speech saved for this Discord room.") : qsTr("No saved messages for this participant.")
                                        textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap
                                    }
                                    ListView {
                                        id: historyList
                                        objectName: "localRoomHistoryEntries"
                                        visible: root.historyEntries.length > 0
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: Math.min(360, Math.max(120, root.historyEntries.length * 96))
                                        clip: true
                                        spacing: 10
                                        model: memoryRows
                                        reuseItems: true
                                        boundsBehavior: Flickable.StopAtBounds
                                        ScrollBar.vertical: ScrollBar {}
                                        LocalRoomScrollWheel { viewport: historyList }
                                        delegate: ColumnLayout {
                                            id: historyEntry
                                            required property string entryRole
                                            required property string entryContent
                                            required property bool outsideContext
                                            width: historyList.width
                                            spacing: 3
                                            Label {
                                                Layout.fillWidth: true
                                                text: root.historyRoleName(historyEntry.entryRole)
                                                    + (historyEntry.outsideContext ? qsTr(" · older · outside current context") : "")
                                                textFormat: Text.PlainText
                                                color: historyEntry.outsideContext ? Theme.NCTheme.textMuted : Theme.NCTheme.accent
                                                font.bold: true; font.pixelSize: 12; wrapMode: Text.WordWrap
                                            }
                                            Label {
                                                Layout.fillWidth: true
                                                text: historyEntry.entryContent
                                                textFormat: Text.PlainText
                                                color: historyEntry.outsideContext ? Theme.NCTheme.textMuted : Theme.NCTheme.text
                                                wrapMode: Text.WordWrap
                                            }
                                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.NCTheme.borderSubtle }
                                        }
                                    }
                                }
                                Label {
                                    objectName: "localRoomHistoryUnavailable"
                                    visible: root.historyFailed
                                    Layout.fillWidth: true
                                    text: qsTr("History unavailable")
                                    textFormat: Text.PlainText; color: Theme.NCTheme.error; wrapMode: Text.WordWrap
                                }
                                Label {
                                    visible: root.historyFailed
                                    Layout.fillWidth: true
                                    text: qsTr("Select Refresh to try again.")
                                    textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
                                }
                                Label {
                                    objectName: "localRoomHistoryEmpty"
                                    visible: !root.historyLoaded && !root.historyFailed
                                    Layout.fillWidth: true
                                    text: root.discordMode ? qsTr("Select Refresh to load this Discord room transcript.") : qsTr("No room history result yet. Select Refresh to load this participant's history.")
                                    textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: root.discordMode ? qsTr("This transcript contains confirmed delivered room speech. It is shared across participants.") : qsTr("This participant remembers only speech heard while in the room. No catch-up for time away.")
                                    textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
                                }
                            }
                        }
                        ColumnLayout {
                            visible: root.panel === "conversation"; Layout.fillWidth: true; spacing: 10
                            Label { Layout.fillWidth: true; text: root.discordMode ? qsTr("Only this Discord room") : qsTr("Only this Local room"); textFormat: Text.PlainText; color: Theme.NCTheme.accent; font.pixelSize: 12 }
                            Label { Layout.fillWidth: true; text: qsTr("Topic"); textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; font.pixelSize: 12 }
                            RoomTextField {
                                id: topicEdit
                                objectName: "localRoomTopicEdit"
                                toolTipText: qsTr("Topic shared with this room. Save topic or press Enter to apply it while keeping the room history.")
                                Layout.fillWidth: true
                                placeholderText: qsTr("Topic not set")
                                text: root.topicDraft
                                onTextEdited: root.topicDraft = text
                                onAccepted: root.saveTopic()
                            }
                            NCButton {
                                objectName: "localRoomTopicSave"
                                Layout.fillWidth: true
                                text: qsTr("Save topic")
                                tone: "primary"
                                enabled: root.topicDraft.trim().length > 0 && Boolean(root.controlById("discord_local_room_set_topic").enabled)
                                onClicked: root.saveTopic()
                            }
                            NCButton { objectName: "localRoomDetailsTopicClear"; text: qsTr("Clear topic"); enabled: root.conversationTopic.length > 0 && root.actionEnabled("discord_local_room_set_topic"); onClicked: root.clearTopic() }
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("The topic is optional. Changing or clearing it keeps this room's history. Earlier messages may still mention a previous topic.")
                                textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap
                            }
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("The room transcript records the conversation. Each participant remembers only speech heard while present, with no catch-up for time away.")
                                textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
                            }
                            Label {
                                Layout.fillWidth: true
                                text: root.conversationHistorySummary
                                textFormat: Text.PlainText; color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
                            }
                        }
                        ColumnLayout {
                            visible: root.panel === "personas"; Layout.fillWidth: true; spacing: 10
                            Label { visible: Boolean(root.replacementId); Layout.fillWidth: true; text: qsTr("Choose a replacement for %1. Their current reply finishes first.").arg(String(root.participant(root.replacementId).name || "")); wrapMode: Text.WordWrap; color: Theme.NCTheme.textMuted }
                            NCComboBox {
                                toolTipText: qsTr("Prepared Discord account to use when adding a Persona. Automatic picks an available account; replacing a Persona can keep the current account.")

                                objectName: "localRoomAdmissionAccount"; visible: root.discordMode; Layout.fillWidth: true
                                model: [{bot_id: "", label: root.replacementId ? qsTr("Keep current account") : root.freeAccounts.length ? qsTr("Automatic · %1").arg(String(root.freeAccounts[0].label)) : qsTr("No free prepared account")}].concat(root.freeAccounts)
                                textRole: "label"; valueRole: "bot_id"
                                currentIndex: Math.max(0, model.findIndex(row => String(row.bot_id) === root.admissionBotId))
                                onActivated: index => root.admissionBotId = String(model[index].bot_id)
                            }
                            Label { visible: root.discordMode && !root.replacementId && !root.admissionAvailable; Layout.fillWidth: true; text: qsTr("No free prepared Discord account. Add an account in Discord setup or wait for cleanup."); color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap }
                            Label { Layout.fillWidth: true; text: qsTr("Drag a Persona into the room, or choose Add. Their name, prompt, portrait and voice stay linked to their Persona profile."); color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap }
                            Label { visible: root.library.length === 0; Layout.fillWidth: true; text: qsTr("Save Personas in the Persona addon to see them here."); wrapMode: Text.WordWrap; color: Theme.NCTheme.textMuted }
                            RoomTextField { visible: root.library.length > 3; Layout.fillWidth: true; placeholderText: qsTr("Find a Persona…"); onTextChanged: root.librarySearch = text }
                            ScrollView {
                                id: libraryScroll
                                objectName: "localRoomPersonaLibrary"
                                Layout.fillWidth: true
                                Layout.preferredHeight: Math.min(320, libraryRows.implicitHeight)
                                contentWidth: availableWidth; clip: true
                                wheelEnabled: false
                                LocalRoomScrollWheel { viewport: libraryScroll.contentItem }
                                ColumnLayout {
                                    id: libraryRows
                                    width: libraryScroll.availableWidth; spacing: 8
                            Repeater {
                                model: root.filteredLibrary
                                delegate: Rectangle {
                                    id: personaRow
                                    required property var modelData
                                    objectName: "localRoomPersona_" + modelData.id
                                    Layout.fillWidth: true; implicitHeight: 76
                                    radius: 8; color: Theme.NCTheme.surfaceRaised
                                    MouseArea {
                                        anchors.fill: parent; preventStealing: true
                                        drag.target: personaDrag
                                        onPressed: function(mouse) {
                                            const point = mapToItem(personaDrag.parent, mouse.x, mouse.y)
                                            personaDrag.x = point.x - personaDrag.width / 2
                                            personaDrag.y = point.y - personaDrag.height / 2
                                            personaDrag.personaId = String(personaRow.modelData.id)
                                            personaDrag.personaName = String(personaRow.modelData.name)
                                        }
                                        onPositionChanged: if (pressed && drag.active) personaDrag.dragging = true
                                        onReleased: { if (personaDrag.dragging) personaDrag.Drag.drop(); personaDrag.dragging = false }
                                        onCanceled: personaDrag.dragging = false
                                    }
                                    RowLayout {
                                        anchors.fill: parent; anchors.margins: 10; spacing: 8
                                        Image { Layout.preferredWidth: 34; Layout.preferredHeight: 34; source: String(personaRow.modelData.avatar_url || ""); visible: status === Image.Ready; fillMode: Image.PreserveAspectCrop }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            Label { Layout.fillWidth: true; text: String(personaRow.modelData.name); textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.NCTheme.text; font.bold: true }
                                            Label { Layout.fillWidth: true; text: String(personaRow.modelData.voice_label || ""); textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.NCTheme.textMuted; font.pixelSize: 11 }
                                        }
                                        NCButton {
                                            objectName: "localRoomAddPersona_" + personaRow.modelData.id
                                            text: root.added(personaRow.modelData.id) ? qsTr("Added") : root.replacementId ? qsTr("Replace") : qsTr("Add")
                                            enabled: root.editCast && (Boolean(root.replacementId) || root.admissionAvailable) && root.phase !== "starting" && !root.added(personaRow.modelData.id)
                                            onClicked: root.addPersona(String(personaRow.modelData.id))
                                        }
                                    }
                                }
                            }
                                }
                            }
                            Label { Layout.fillWidth: true; text: qsTr("Persona names, prompts, images and voices stay linked to their profiles. Room history is stored only in this Local room."); wrapMode: Text.WordWrap; color: Theme.NCTheme.textMuted; font.pixelSize: 12 }
                        }

                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            objectName: "roomMicrophoneHint"
            text: root.discordMode ? qsTr("Use Discord for your microphone, audio and channel membership. NC routing mute does not change Discord server mute.")
                : root.textOnly ? qsTr("Text only · from Session setup") : root.room.input_mode === "push_to_talk" ? qsTr("Push to talk · use your Session setup hotkey") : qsTr("Voice activation · from Session setup")
            color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
        }
        RowLayout {
            Layout.fillWidth: true
            Label { visible: !root.discordMode; text: qsTr("As %1").arg(String(root.room.user_name || "You")); color: Theme.NCTheme.textMuted; elide: Text.ElideRight; Layout.maximumWidth: 140 }
            NCRoomTextSender {
                id: textSender
                objectName: "localRoomTextSender"
                visible: root.discordMode; Layout.preferredWidth: 190
                room: root.room
                onSenderSelected: senderId => root.runAction("discord_local_room_set_sender", {participant_id: senderId})
            }
            RoomTextField {
                objectName: "localRoomMessage"; Layout.fillWidth: true
                placeholderText: root.discordMode ? root.room.text_sender_name ? qsTr("Message as %1…").arg(String(root.room.text_sender_name)) : qsTr("Choose who is sending…") : root.joined ? qsTr("Bring a topic…") : qsTr("Join the conversation to send a message")
                enabled: Boolean(root.controlById("discord_local_room_message").enabled)
                text: root.messageDraft
                onTextEdited: {
                    root.messageDraft = text
                    root.setRoomControl("discord_local_room_message", text)
                }
                onAccepted: root.runAction("discord_local_room_send")
            }
            NCButton {
                objectName: "localRoomSend"; text: qsTr("Send")
                enabled: root.actionEnabled("discord_local_room_send")
                onClicked: root.runAction("discord_local_room_send")
            }
        }
    }

    LocalRoomBehaviorDialog { id: behaviorDialog; workspace: root }
    Menu {
        id: roomActionsMenu; objectName: "localRoomRoomActionsMenu"; parent: root
        width: 260; palette: participantMenu.palette
        background: Rectangle { radius: 8; color: Theme.NCTheme.surface; border.color: Theme.NCTheme.borderStrong }
        RoomMenuItem { actionSuffix: "clear_next" }
        RoomMenuItem { actionSuffix: "skip_speech"; visible: !root.discordMode; height: visible ? implicitHeight : 0 }
        RoomMenuItem { actionSuffix: "stop_speech" }
        MenuItem { visible: root.discordMode; height: visible ? implicitHeight : 0; text: qsTr("Room anonymity…"); onTriggered: root.openSelfMenu() }
    }
    Popup {
        id: selfMenu; objectName: "localRoomSelfMenu"; parent: Overlay.overlay
        width: Math.min(340, parent ? parent.width - 24 : 340)
        height: Math.min(implicitHeight, parent ? parent.height - 24 : implicitHeight)
        padding: 16; focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 10; color: Theme.NCTheme.surface; border.color: Theme.NCTheme.borderStrong }
        contentItem: ScrollView {
            id: selfScroll
            clip: true; contentWidth: availableWidth
            implicitHeight: selfControls.implicitHeight
            ColumnLayout {
                id: selfControls; width: selfScroll.availableWidth; spacing: 9
                Label { Layout.fillWidth: true; text: root.discordMode ? qsTr("Room anonymity") : String(root.room.user_name || "You") + qsTr(" · Your room controls"); textFormat: Text.PlainText; color: Theme.NCTheme.text; font.bold: true; wrapMode: Text.WordWrap }
                ColumnLayout {
                    visible: !root.discordMode; Layout.fillWidth: true; spacing: 8
                    RoomAction { objectName: "localRoomJoin"; actionSuffix: "join"; Layout.fillWidth: true; toolTipText: qsTr("Leave to observe and listen without appearing in the participant roster. Join again to send messages and speak.") }
                    RoomAction { objectName: "localRoomMute"; actionSuffix: "mute"; Layout.fillWidth: true; enabled: !root.textOnly && root.actionEnabled("discord_local_room_mute"); toolTipText: qsTr("Mute or unmute your room microphone without leaving the conversation. Uses the input mode selected in Session setup.") }
                    NCButton { objectName: "localRoomLetMeSpeak"; text: qsTr("Let me speak next"); Layout.fillWidth: true; enabled: root.phase === "running" && root.joined && !root.room.stopping; toolTipText: qsTr("Queue your turn after the current speaker finishes. You must join the conversation first."); onClicked: { root.speakAsSelfNext(); selfMenu.close() } }
                    Label { Layout.fillWidth: true; text: root.joined ? qsTr("You are part of the conversation. Use your Session setup input mode to speak.") : qsTr("You are observing. You can watch and listen without being part of the room roster."); color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap; font.pixelSize: 12 }
                    Label { text: qsTr("Your name in this room"); color: Theme.NCTheme.text }
                    RoomTextField { objectName: "localRoomControlsUserName"; Layout.fillWidth: true; text: root.userNameDraft; toolTipText: qsTr("Name used for your subsequent messages in this room. Earlier messages keep their original names. Save name or press Enter to apply."); onTextEdited: root.userNameDraft = text; onAccepted: if (text.trim()) root.runAction("discord_local_room_save_name",{name:text}) }
                    NCButton { objectName: "localRoomControlsSaveName"; text: qsTr("Save name"); Layout.fillWidth: true; enabled: root.userNameDraft.trim().length > 0 && root.actionEnabled("discord_local_room_save_name"); onClicked: root.runAction("discord_local_room_save_name",{name:root.userNameDraft}) }
                }
                NCSwitch { objectName: "discord_room_anonymous"; Layout.fillWidth: true; text: qsTr("Anonymous participants"); checked: Boolean(root.controlById("discord_room_anonymous").value); enabled: Boolean(root.controlById("discord_room_anonymous").enabled); toolTipText: qsTr("Room-wide: hide which participants are human or AI in future replies and presentation. Earlier history may reveal identities. This does not erase history."); onClicked: root.setRoomControl("discord_room_anonymous",checked) }
                Label { objectName: "localRoomAnonymousHelp"; Layout.fillWidth: true; text: qsTr("Applies to the whole room and subsequent replies. Earlier messages may already reveal identities. A new conversation is optional for a clean experiment."); color: Theme.NCTheme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap }
            }
        }
    }
    NCDialog {
        id: botComposer; objectName: "localRoomBotComposer"; parent: Overlay.overlay; anchors.centerIn: parent
        title: (root.composerAction === "guide" ? qsTr("Guide %1") : qsTr("Speak through %1")).arg(String(root.participant(root.composerTargetId).name || qsTr("bot")))
        description: root.composerAction === "guide" ? qsTr("Private guidance for one reply. The bot answers in its own words; these instructions are not read aloud or saved as a permanent prompt.") : qsTr("Your exact words, spoken using this bot’s selected voice. The bot does not invent or rewrite a reply.")
        width: Math.min(640, parent ? parent.width - 32 : 640)
        height: Math.min(480, parent ? parent.height - 32 : 480)
        acceptText: root.composerAction === "guide" ? qsTr("Prepare reply & speak next") : qsTr("Prepare speech & speak next")
        acceptEnabled: root.composerAvailable && root.guidanceDraft.trim().length > 0
        contentItem: ScrollView {
            id: composerScroll
            clip: true; contentWidth: availableWidth
            ColumnLayout {
                width: composerScroll.availableWidth; spacing: 10
                TextArea {
                    id: botMessage; objectName: "localRoomAnnouncement"; Layout.fillWidth: true; implicitHeight: 130; wrapMode: TextEdit.Wrap
                    text: root.guidanceDraft; placeholderText: root.composerAction === "guide" ? qsTr("What should this bot respond to or focus on?") : qsTr("Enter the words you want this bot to say…")
                    color: Theme.NCTheme.text; placeholderTextColor: Theme.NCTheme.textMuted; selectionColor: Theme.NCTheme.selection
                    background: Rectangle { radius: 8; color: Theme.NCTheme.window; border.color: Theme.NCTheme.borderStrong }
                    NCHelp { target: botMessage; text: root.composerAction === "guide" ? qsTr("Private guidance for one reply from the selected bot. The guidance itself is not spoken or added to heard history. Submit to start preparation now.") : qsTr("The exact words to speak through the selected bot. Submit to prepare speech now; audio waits for the current speaker to finish.") }
                    onTextChanged: if (root.guidanceDraft !== text) root.setGuidanceDraft(text)
                }
                Label { Layout.fillWidth: true; text: qsTr("Preparation starts on submit. The bot speaks next after the current speaker finishes; the current reply is not interrupted."); color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap }
                Label { Layout.fillWidth: true; visible: !root.composerAvailable; text: qsTr("This bot is unavailable, a direction is already pending, or the room is paused. Close this draft and retry when ready."); color: Theme.NCTheme.warning; wrapMode: Text.WordWrap }
            }
        }
        onClosed: root.rememberBotDraft()
        onAccepted: {
            if (root.composerAvailable && root.runAction("discord_local_room_" + root.composerAction, {participant_id:root.composerTargetId, admission_id:root.composerAdmission})) {
                // Keep the submitted draft available if asynchronous delivery fails.
                root.rememberBotDraft()
            }
        }
    }
    NCDialog {
        id: topicDialog; objectName: "localRoomTopicDialog"; parent: Overlay.overlay; anchors.centerIn: parent
        title: qsTr("Edit discussion topic")
        description: qsTr("A topic is optional. Clear it for an open-ended conversation or brainstorming. Changing or clearing it keeps the conversation and history; earlier messages may still mention the old topic.")
        width: Math.min(640,parent ? parent.width - 32 : 640)
        acceptText: qsTr("Save topic"); acceptEnabled: root.topicDraft.trim().length > 0 && root.actionEnabled("discord_local_room_set_topic")
        contentItem: ColumnLayout {
            RoomTextField { objectName: "localRoomTopicDraft"; Layout.fillWidth: true; text: root.topicDraft; placeholderText: qsTr("What should the room discuss?"); toolTipText: qsTr("Optional shared focus for future replies. Clear topic removes this context without erasing previous messages. No topic set is only a UI label."); onTextEdited: root.topicDraft=text }
            NCButton { objectName: "localRoomTopicClear"; text: qsTr("Clear topic"); enabled: root.conversationTopic.length > 0 && root.actionEnabled("discord_local_room_set_topic"); toolTipText: qsTr("Remove the shared topic for future replies, keeping the conversation and all history."); onClicked: root.clearTopic() }
        }
        onAccepted: root.saveTopic()
    }
    NCDialog {
        id: removeParticipantDialog; objectName: "localRoomRemoveParticipantDialog"; parent: Overlay.overlay; anchors.centerIn: parent
        title: qsTr("Remove %1 from the room?").arg(root.removalTarget.name || "")
        description: qsTr("The participant leaves after their current reply finishes. Their Persona and saved room memory are kept.")
        acceptText: qsTr("Remove from room"); acceptTone: "danger"
        onAccepted: root.runAction("discord_local_room_remove",root.removalTarget)
    }
    NCDialog {
        id: newConversationDialog
        objectName: "localRoomNewConversationDialog"
        anchors.centerIn: parent
        title: root.discordMode ? qsTr("Start a new Discord room conversation?") : qsTr("Start a new Local room conversation?")
        description: root.discordMode ? qsTr("Clear this Discord room's history, saved continuation and topic, then connect the bots and start the room. Persona profiles and prepared bot settings are kept.") : qsTr("Clear ALL Local room history for this room, including participants who have been removed from the room, then start the room. The topic is cleared too. Persona profiles, names, prompts, images and voices are not changed. This cannot be undone.")
        acceptText: qsTr("Clear history and start room")
        acceptTone: "danger"
        onAccepted: {
            root.topicDraft = ""
            root.runAction("discord_local_room_new_conversation")
        }
    }
}
