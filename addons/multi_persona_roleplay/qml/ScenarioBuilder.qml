import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

Item {
    id: root
    objectName: "mprcScenarioEditor"
    required property var scenarioBuilder
    signal masterRequested()
    property var draft: scenarioBuilder.state
    property string refineTarget: "/story"
    property string refineLabel: "Whole story"
    function fieldHelp(field) {
        const supplied = String(field.help || "")
        const path = String(field.id || "")
        const key = path.split("/").pop()
        if (/\/visual\/mode$/.test(path))
            return "Choose manual story images or an automatic scene, character, choice, story-beat, reply-interval, or user-request trigger. Off disables requests. Send to Master Draft and Apply Draft activate this change."
        if (/\/arguments\/text$/.test(path))
            return "Visible text spoken by the validated story narration action when its event or choice runs. Editing this draft does not execute the action."
        if (/\/personas\/[0-9]+\/role$/.test(path))
            return "Role or archetype for this story character. The draft's existing-persona update option determines whether applying may update a matching saved persona."
        if (supplied && !supplied.startsWith("Edit ")) return supplied
        // Explicit semantic fields; numeric record positions do not affect their meaning.
        const help = {
            title: "Display title for this story, scene, lorebook, or event in the draft.",
            label: "Text shown to the player for this authored choice.",
            text: "Lore fact text supplied to the model when this entry is selected by scene, keywords, priority, and available context space.",
            description: "Character background or scene description supplied as story context from this draft.",
            location: "Place where this story or authored scene occurs.",
            scene_title: "Title for the story's opening scene.",
            time_of_day: "Time of day for the story scene.",
            mood: "Atmosphere for the story scene.",
            objective: "Current story objective that should guide narration.",
            scene_summary: "Compact scene continuity context for the story setup.",
            mode: "Story framing: a single persona, group, narrator with characters, game master, or AlternativeReality.",
            type: "Declared scenario variable type: boolean, integer, number, or string. Initial values and comparisons must match this type.",
            initial: "Starting value for this variable when a new scenario session begins. It must match the declared type and any allowed values.",
            enum: "Allowed values for this scenario variable, one per line. An empty list leaves values unrestricted within its declared type.",
            action_id: "Validated scenario action: change scene, set declared state, or narrate. It must also appear in this story's allowed actions.",
            arguments: "Arguments for the selected validated scenario action. These are data passed to the dispatcher, not executable code.",
            variable_id: "Declared scenario variable used by this condition or state-change action.",
            value: "Typed value for a variable comparison or state change. It must match the selected variable's declared type.",
            op: "Comparison operator. Ordered comparisons require a numeric variable; All and Any combine child conditions.",
            scene_id: "Declared destination scene for a scenario scene-change action.",
            persona_id: "Story persona linked to this authored role.",
            active_persona_id: "Persona selected as active when this story draft is applied.",
            current_speaker_id: "Persona selected as the story's current speaker.",
            narrator_persona_id: "Persona selected for story narration and narrator voice routing.",
            system_prompt: "Character instructions used when this persona participates in the story.",
            display_name: "Name used for this character in the cast and speaker labels.",
            speaking_style: "Character wording, rhythm, and conversational manner.",
            allowed_tone: "Tone guidance for this character's story replies.",
            response_length: "Short, balanced, or detailed reply preference for this character; this is not an exact token limit.",
            temperature_hint: "Saved character style note for randomness or energy; this is not a numeric model temperature setting.",
            memory_scope: "Character continuity guidance: shared, persona-only, session-only, or disabled. This does not delete saved memory.",
            behavior_mode: "Character framing as a companion, RPG character, narrator, game master, or group participant.",
            tags: "Character tags, one per line in this draft editor.",
            ar_profile_enabled: "Allow this character's AlternativeReality description and instructions to replace its normal profile in AR mode.",
            ar_description: "Character identity and background specific to AlternativeReality mode.",
            ar_system_prompt: "Character instructions specific to AlternativeReality mode.",
            master_narrator: "Mark this character as a master narrator candidate.",
            allow_adult_only: "Saved character safety preference for adult-only content. This metadata does not override provider or NC safety rules.",
            avoid_real_person_impersonation: "Saved character safety preference to avoid impersonating real people.",
            notes: "Additional saved safety notes for this character profile.",
            sample_path: "Local reference audio used for this character's voice.",
            preset_name: "Voice preset name interpreted by the selected TTS backend.",
            language: "Optional voice language code supported by the selected TTS backend.",
            size: "Requested story image size; provider support determines available dimensions.",
            style_preset: "Visual style preset included in story image prompts.",
            character_description: "Stable character appearance included in story image prompts.",
            clothing_props: "Clothing and props included in story image prompts.",
            environment_style: "Place and atmosphere included in story image prompts.",
            negative_prompt: "Image content to avoid. Support depends on the image provider.",
            keep_continuity: "Ask image prompts to preserve the character's established appearance across scenes.",
            appearance_freedom: "Strict preserves established appearance. Flexible permits scene-led styling changes without changing the saved avatar.",
            include_scene_summary: "Include the latest scene summary in story image prompts.",
            include_active_speaker: "Include the active speaker in story image prompts.",
            auto_reply_interval: "Number of replies between periodic image checks in Every N replies mode.",
            cooldown_seconds: "Minimum seconds between automatic story images. 0 removes the delay; manual image requests bypass it.",
            max_auto_images_per_session: "Session image-count limit for this visual profile. 0 means unlimited; the current generation gate checks this for manual requests too.",
            auto_show_dock: "Show the Visual Reply dock when this profile requests a story image.",
            master_story_prompt: "Premise and requirements used to generate the Master Story draft.",
            master_story_mode: "Roleplay mode requested for Master Story generation.",
            master_story_scene_title: "Opening scene title requested for Master Story generation.",
            master_story_location: "Opening location requested for Master Story generation.",
            master_story_time_of_day: "Opening time or atmosphere requested for Master Story generation.",
            master_story_mood: "Opening mood requested for Master Story generation.",
            master_story_visual_direction: "Style and presentation guidance for generated character avatars.",
            master_story_sfw_mode: "Request a safe-for-work story brief and draft.",
            master_story_native_persona_count: "Requested persona count for the draft. 0 asks only for characters explicitly required by the premise.",
            master_story_max_created_characters: "Maximum new character profiles allowed when applying the draft, unless exceeding the limit is enabled.",
            master_story_allow_exceed_max_created_characters: "Allow Apply Draft to create more characters than the configured maximum.",
            master_story_use_existing_personas: "Permit the generated story to reuse personas already in the registry.",
            master_story_auto_create: "Allow Apply Draft to create missing persona profiles.",
            master_story_auto_assign_voices: "Assign distinct available voices to new personas when applying the draft.",
            master_story_update_existing: "Allow Apply Draft to update matching existing persona profiles.",
            master_story_auto_avatars: "Request avatar images for new personas when applying the draft.",
            master_story_avatar_style_sheets: "Request avatar style sheets for new personas during avatar creation.",
            master_story_clear_memory: "Start with clean story memory when applying the draft.",
        }
        const text = help[key] || ""
        return text ? text + " Changes remain in this editor until Send to Master Draft and Apply Draft." : ""
    }
    component HelpButton: NCButton {
        property string help: ""
        toolTipText: help
        compact: true
    }
    component HelpLabel: Label {
        color: Theme.NCTheme.text
        font.family: Theme.NCTypography.family
        font.pixelSize: Theme.NCTypography.bodySize
    }
    ColumnLayout {
        anchors.fill: parent; spacing: Theme.NCMetrics.space12
        HelpLabel { text: "Master Story · Scenarios & Lore"; font.pixelSize: Theme.NCTypography.headingSize; font.bold: true }
        HelpLabel {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.NCTheme.textSecondary
            text: "Author scenes, facts, conditions and choices here. Everything stays in the draft until you send it to Master Story and apply it. Refine any field with your current main model, then review the preview."
        }
        Flow {
            objectName: "mprcScenarioCategoryTabs"
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
            spacing: Theme.NCMetrics.space6
            Repeater {
                model: root.draft.groups
                delegate: NCTabButton {
                    required property string modelData
                    objectName: "mprcScenarioCategory_" + modelData
                    text: modelData
                    checked: root.draft.group === modelData
                    Accessible.role: Accessible.PageTab
                    Accessible.name: modelData
                    onClicked: root.scenarioBuilder.selectGroup(modelData)
                    ToolTip.visible: hovered
                    ToolTip.text: "Edit " + modelData.toLowerCase() + " in the story draft. Changes become live only after Send to Master Draft and Apply Draft."
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: root.draft.parents.length > 0 || root.draft.canManage
            NCComboBox {
                visible: root.draft.parents.length > 0; model: root.draft.parents
                textRole: "label"; valueRole: "id"; Layout.preferredWidth: 185
                currentIndex: root.draft.parents.findIndex(item => item.id === root.draft.parentId)
                onActivated: scenarioBuilder.selectParent(currentValue)
                hoverEnabled: true; toolTipText: "Select the parent lorebook, scene or event for this record."
            }
            NCComboBox {
                visible: root.draft.canManage; model: root.draft.records
                textRole: "label"; valueRole: "id"; Layout.fillWidth: true
                currentIndex: root.draft.records.findIndex(item => item.id === root.draft.recordId)
                onActivated: scenarioBuilder.selectRecord(currentValue)
                hoverEnabled: true; toolTipText: "Select a record. Stable IDs are preserved by refinement."
            }
        }
        Flow {
            Layout.fillWidth: true; spacing: Theme.NCMetrics.space8
            HelpButton { visible: root.draft.canManage; text: "Add"; help: "Create a record in this draft. No action runs."; onClicked: scenarioBuilder.manageRecord("add") }
            HelpButton { visible: root.draft.canManage; text: "Duplicate"; enabled: root.draft.recordId !== ""; help: "Copy this record with new stable IDs."; onClicked: scenarioBuilder.manageRecord("duplicate") }
            HelpButton { visible: root.draft.canManage; text: "Delete"; enabled: root.draft.recordId !== ""; help: "Remove this draft record. Referenced records must be unlinked first."; onClicked: scenarioBuilder.manageRecord("delete") }
            HelpButton { text: "Refine section"; help: "Ask the current main model to refine this section as a coherent whole. Preview and Apply are required."; onClicked: { root.refineTarget=root.draft.sectionTarget; root.refineLabel=root.draft.group } }
            HelpButton { visible: !!root.draft.recordTarget; text: "Refine record"; help: "Refine all fields of the selected record together, keeping its stable ID."; onClicked: { root.refineTarget=root.draft.recordTarget; root.refineLabel="Selected " + root.draft.group + " record" } }
        }
        SplitView {
            id: panes
            orientation: root.width >= 980 ? Qt.Horizontal : Qt.Vertical
            handle: Rectangle {
                implicitWidth: 8; implicitHeight: 8
                color: SplitHandle.hovered || SplitHandle.pressed ? Theme.NCTheme.borderStrong : Theme.NCTheme.window
            }
            Layout.fillWidth: true; Layout.fillHeight: true
            ScrollView {
                id: editorScroll
                SplitView.preferredWidth: root.width * 0.60; SplitView.minimumWidth: panes.orientation === Qt.Horizontal ? 410 : 0
                SplitView.preferredHeight: 430; SplitView.minimumHeight: panes.orientation === Qt.Vertical ? Math.min(180, Math.max(0, (panes.height - 8) / 2)) : 180
                clip: true; contentWidth: availableWidth
                ColumnLayout {
                    width: editorScroll.availableWidth - 12; spacing: 14
                    Repeater {
                        model: root.draft.fields
                        delegate: NCCard {
                            required property var modelData
                            Layout.fillWidth: true
                            ColumnLayout {
                                Layout.fillWidth: true
                                RowLayout {
                                    HelpLabel { text: modelData.label; Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.WordWrap; font.bold: true }
                                    HelpButton {
                                        text: "Refine"; help: "Select this field for a main-model proposal. Describe your change in the refinement panel."
                                        onClicked: { root.refineTarget = modelData.id; root.refineLabel = modelData.label }
                                    }
                                }
                                HelpLabel { text: modelData.help; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.NCTheme.textMuted; font.pixelSize: 12 }
                                Loader {
                                    Layout.fillWidth: true
                                    property var field: modelData
                                    sourceComponent: field.options.length > 0 ? enumEditor : field.kind === "boolean" ? boolEditor : textEditor
                                }
                            }
                        }
                    }
                    HelpLabel { visible: root.draft.fields.length === 0; text: "Add or select a record to begin."; color: Theme.NCTheme.textSecondary }
                    NCCard {
                        visible: root.draft.canCondition; Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            HelpLabel { text: "Availability condition"; font.bold: true }
                            HelpLabel { text: "Compare a variable; combine comparisons with All or Any. Clear makes this event or choice always eligible."; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.NCTheme.textMuted }
                            RowLayout {
                                NCComboBox { id: variable; model: root.draft.variables; textRole: "label"; valueRole: "id"; Layout.fillWidth: true; hoverEnabled: true; toolTipText: "Declared variable to compare. Boolean values are true or false." }
                                NCComboBox { id: operation; model: ["eq","ne","lt","le","gt","ge"]; hoverEnabled: true; toolTipText: "Equal / not equal, less / less or equal, greater / greater or equal. Ordered comparisons require numbers." }
                            }
                            NCTextField { id: comparison; Layout.fillWidth: true; placeholderText: "Comparison value (typed to the variable)"; placeholderTextColor: Theme.NCTheme.textMuted; hoverEnabled: true; toolTipText: "Value compared with the selected variable. Enter true or false for booleans, a number for numeric variables, or text for string variables." }
                            RowLayout {
                                Repeater {
                                    model: ["replace","all","any","clear"]
                                    HelpButton {
                                        required property string modelData
                                        text: modelData; help: "Replace, combine with All/Any, or clear the condition. Invalid type combinations are rejected."
                                        onClicked: scenarioBuilder.condition(variable.currentValue || "", operation.currentText, comparison.text, modelData)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            ScrollView {
                id: refineScroll
                SplitView.preferredWidth: root.width * 0.40; SplitView.minimumWidth: panes.orientation === Qt.Horizontal ? 290 : 0;
                SplitView.preferredHeight: 320; SplitView.minimumHeight: panes.orientation === Qt.Vertical ? Math.min(180, Math.max(0, (panes.height - 8) / 2)) : 180; clip: true; contentWidth: availableWidth
                ColumnLayout {
                    width: refineScroll.availableWidth - 12; spacing: 10
                    NCCard {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            HelpLabel { text: "Refine with " + (scenarioBuilder.currentModel || "no main model selected"); font.bold: true; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            HelpLabel { text: root.refineLabel; color: Theme.NCTheme.accent; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            NCTextArea {
                                id: instruction; Layout.fillWidth: true; Layout.preferredHeight: 105
                                placeholderText: "What should the model improve?"; wrapMode: TextEdit.Wrap
                                placeholderTextColor: Theme.NCTheme.textMuted
                                hoverEnabled: true; toolTipText: "Describe a change to the selected field or whole story. A proposal never runs actions or modifies live settings."
                            }
                            RowLayout {
                                HelpButton { text: root.draft.busy ? "Refining…" : "Generate preview"; enabled: !root.draft.busy; help: "Use NC’s current main chat provider and model. Results are checked against the selected field’s type."; onClicked: scenarioBuilder.refine(root.refineTarget,instruction.text) }
                                HelpButton { text: "Whole story"; help: "Select the full Master Story draft for refinement. Existing stable IDs are protected."; onClicked: { root.refineTarget="/story"; root.refineLabel="Whole story" } }
                            }
                            HelpButton { visible: root.draft.busy; text: "Cancel request"; help: "Discard this request and ignore any late response. It may already be running at the provider."; onClicked: scenarioBuilder.cancelRefinement() }
                            HelpLabel { text: root.draft.proposal.summary || "Your original and proposed values appear here for review."; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.NCTheme.textSecondary }
                            HelpLabel { visible: !!root.draft.proposal.before; text: "Original"; font.bold: true }
                            NCTextArea { toolTipText: "Read-only original value used to produce the refinement proposal. Apply preview changes the editor draft only."; visible: !!root.draft.proposal.before; text: root.draft.proposal.before || ""; readOnly: true; wrapMode: TextEdit.Wrap; Layout.fillWidth: true; selectByMouse: true }
                            HelpLabel { visible: !!root.draft.proposal.after; text: "Proposal"; font.bold: true }
                            NCTextArea { toolTipText: "Read-only model proposal. Apply preview accepts it into the editor draft; Send to Master Draft and Apply Draft are still required to activate the story."; visible: !!root.draft.proposal.after; text: root.draft.proposal.after || ""; readOnly: true; wrapMode: TextEdit.Wrap; Layout.fillWidth: true; selectByMouse: true }
                            RowLayout {
                                visible: !!root.draft.proposal.after
                                HelpButton { text: "Apply preview"; help: "Accept this proposal into this editor draft. A changed draft rejects stale proposals."; onClicked: scenarioBuilder.applyPreview() }
                                HelpButton { text: "Discard"; help: "Keep the original draft and discard the proposal."; onClicked: scenarioBuilder.cancelRefinement() }
                            }
                        }
                    }
                    NCCard {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            HelpLabel { text: "Preview draft lore"; font.bold: true }
                            NCTextField { id: loreQuery; Layout.fillWidth: true; placeholderText: "Player action or keywords"; placeholderTextColor: Theme.NCTheme.textMuted; hoverEnabled: true; toolTipText: "Preview against this draft's initial scene, or the selected scene in Scenes. This preview has no Play history and runs no model or action." }
                            HelpButton { text: root.draft.loreBusy ? "Matching…" : "Preview lore"; enabled: !root.draft.loreBusy; help: "Show selected facts and omission reasons using the draft's context budget. Live Play recalculates against its full request and recent messages."; onClicked: scenarioBuilder.previewLore(loreQuery.text) }
                            HelpLabel { text: root.draft.lorePreview; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.NCTheme.textSecondary }
                        }
                    }
                    NCCard {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            HelpLabel { text: "Applied scenario · Play"; font.bold: true }
                            HelpLabel { text: scenarioBuilder.playState.status; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.NCTheme.textSecondary }
                            Repeater {
                                model: scenarioBuilder.playState.choices
                                HelpButton {
                                    required property var modelData
                                    text: modelData.label; Layout.fillWidth: true; help: "Execute this authored choice in the active scenario: " + modelData.action
                                    onClicked: scenarioBuilder.executeChoice(modelData.id)
                                }
                            }
                            Repeater {
                                model: scenarioBuilder.playState.retries
                                HelpButton {
                                    required property var modelData
                                    text: "Retry: " + modelData.label; Layout.fillWidth: true
                                    help: "Explicitly retry this failed once-event. Completed effects are skipped; uncertain effects block retries."
                                    onClicked: scenarioBuilder.retryEvent(modelData.id)
                                }
                            }
                        }
                    }
                }
            }
        }
        HelpLabel { text: root.draft.status; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.NCTheme.textSecondary }
        Flow {
            Layout.fillWidth: true; spacing: Theme.NCMetrics.space8
            HelpButton { text: "Load lighthouse example"; help: "Replace only the scenario extension in this editor with a sample of scenes, lore and choices. Send and Apply are still required."; onClicked: scenarioBuilder.loadExample() }
            HelpButton { text: "Reload Master Draft"; help: "Reload the current Master draft, discarding unsent editor changes and pending proposals."; onClicked: reloadDialog.open() }
            HelpButton { text: "Send to Master Draft"; tone: "primary"; help: "Validate and copy this editor into the Master Story draft. Save or Apply it there; this does not change a running session."; onClicked: scenarioBuilder.acceptDraft() }
            HelpButton { text: "Open Master"; help: "Return to Master Story to review, save or apply the draft. Unsent editor changes stay here."; onClicked: root.masterRequested() }
        }
    }
    NCDialog {
        id: reloadDialog
        title: "Reload Master Draft?"
        width: Math.min(420, root.width - 24)
        anchors.centerIn: parent
        description: "Discard unsent changes in this editor and reload the current Master draft?"
        acceptText: "Reload"
        acceptTone: "warning"
        onAccepted: scenarioBuilder.reload()
    }
    Component {
        id: enumEditor
        NCComboBox {
            model: field.options; currentIndex: field.options.indexOf(field.value)
            onActivated: scenarioBuilder.editField(field.id,currentValue)
            hoverEnabled: true; toolTipText: root.fieldHelp(field)
        }
    }
    Component {
        id: boolEditor
        NCSwitch {
            checked: field.value; text: checked ? "Enabled / true" : "Disabled / false"
            onClicked: scenarioBuilder.editField(field.id,checked)
            hoverEnabled: true; toolTipText: root.fieldHelp(field)
        }
    }
    Component {
        id: textEditor
        ColumnLayout {
            NCTextArea {
                id: input; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredHeight: field.text.length > 100 ? 112 : 72; text: field.text; wrapMode: TextEdit.Wrap
                selectByMouse: true; hoverEnabled: true; toolTipText: root.fieldHelp(field)
            }
            HelpButton {
                text: "Set field"; help: "Keep this value in the editor draft. Use one item per line for lists."
                onClicked: scenarioBuilder.editField(field.id,field.kind === "integer" || field.kind === "number" ? Number(input.text) : input.text)
            }
        }
    }
}
