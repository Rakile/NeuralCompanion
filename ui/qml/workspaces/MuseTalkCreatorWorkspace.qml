pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

NCCard {
    id: root
    objectName: "musetalkCreatorWorkspace"

    required property var creatorModel
    property var addonControls: []
    signal settingEdited(string controlId, var value)
    readonly property var creatorState: creatorModel ? creatorModel.state : ({})
    readonly property var creatorAccess: creatorState.creator_access || ({})
    readonly property var residency: creatorState.creator_residency || ({})
    readonly property bool wideLayout: width >= 1080
    readonly property bool commandBusy: Boolean(creatorState.commandBusy)
    readonly property bool fieldBusy: commandBusy && !Boolean(creatorState.quietCommand)
    // Stable signatures avoid rebuilding unchanged delegates on every state notification.
    readonly property string rangesSignature: JSON.stringify(creatorState.musetalk_mask_ranges || [])
    readonly property var rangeRows: JSON.parse(rangesSignature)
    readonly property string overridesSignature: JSON.stringify(creatorState.musetalk_mask_overrides || [])
    readonly property var overrideRows: JSON.parse(overridesSignature)
    readonly property string settingControlsSignature: JSON.stringify(filteredSettingControls())
    property int settingCommitRevision: 0
    readonly property var settingControls: {
        // An explicit commit must also restore a rejected edit to its saved value.
        const revision = settingCommitRevision
        return JSON.parse(settingControlsSignature)
    }
    readonly property var generalSettingControls: settingControls.filter(field => maskGroup(field.id) === "")
    readonly property var maskSettingControls: settingControls.filter(field => maskGroup(field.id) !== "")
    readonly property bool creatorBusy: Boolean(creatorState.creator_busy)
    readonly property int emotionRowCount: (creatorState.musetalk_native_pack_emotions || []).length
    readonly property int rangeRowCount: (creatorState.musetalk_mask_ranges || []).length
    readonly property bool accessFree: String(creatorAccess.owner || "") === ""
                                       && String(creatorAccess.phase || "") === "free"
    readonly property bool mutatingAllowed: (accessFree || (String(creatorAccess.owner || "") === "creator"
                                                           && (Boolean(residency.loaded) || Boolean(residency.worker_failed))))
                                           && !creatorBusy && !fieldBusy && !Boolean(creatorState.releaseBusy)
    readonly property bool restrictionVisible:
        String(creatorAccess.owner || "") === "chat"
        || String(creatorAccess.phase || "") === "unavailable"
        || (!accessFree && String(creatorAccess.owner || "") !== "creator")
    readonly property var preparedPreview: creatorState.musetalk_native_preview_details || ({})
    readonly property string preparedPreviewSignature: JSON.stringify(preparedPreview)
    property bool preparedPreviewArmed: false
    property int preparedFrameIndex: 0
    readonly property var preparedFrameUrls: preparedPreview.mode === "prepared" ? (preparedPreview.frame_urls || []) : []
    readonly property bool preparedPreviewActive: preparedPreviewArmed && visible && !fieldBusy && !creatorBusy
        && !restrictionVisible && preparedFrameUrls.length > 0
        && Number(preparedPreview.selection_revision) === Number(creatorState.musetalk_native_selection_revision)
    onPreparedPreviewSignatureChanged: {
        preparedFrameIndex = 0
        preparedPreviewArmed = preparedPreview.mode === "prepared"
    }
    onCommandBusyChanged: if (commandBusy) preparedPreviewArmed = false
    onCreatorBusyChanged: if (creatorBusy) preparedPreviewArmed = false
    onRestrictionVisibleChanged: if (restrictionVisible) preparedPreviewArmed = false
    Timer {
        objectName: "musetalkPreparedPreviewTimer"
        interval: Math.max(16, Math.round(1000 / Math.max(1, Math.min(30, Number(root.preparedPreview.fps || 24)))))
        repeat: true
        running: root.preparedPreviewActive && root.preparedFrameUrls.length > 1
        onTriggered: root.preparedFrameIndex = (root.preparedFrameIndex + 1) % root.preparedFrameUrls.length
    }
    property var pendingVariant: ({})
    property string pickerPurpose: ""
    property string pendingConfirmationControl: ""
    property var pendingConfirmation: ({})
    // Session-only scheduling: automatic ticks never queue behind GPU work.
    property string continuousRenderMode: ""
    property string pendingRenderMode: ""
    readonly property bool renderSessionAllowed: visible && !restrictionVisible
        && !Boolean(creatorState.startupPending)
        && !Boolean(creatorState.releaseBusy) && !Boolean(residency.release_requested)
        && String(creatorAccess.phase || "") !== "cleanup_failed"
    readonly property bool renderCommandBusy: (creatorState.pendingKeys || []).some(
        key => key === "trigger:btn_musetalk_debug_first_frame"
            || key === "trigger:btn_musetalk_debug_first_frame_modified")
    readonly property bool renderReady: renderSessionAllowed && mutatingAllowed && !commandBusy
        && Boolean(creatorState.previewSubmissionReady)
        && !maskEditor.strokeActive && !maskEditor.panning
    readonly property bool renderSelectable: renderSessionAllowed && (mutatingAllowed || renderCommandBusy)

    function stopContinuousRender() {
        continuousRenderMode = ""
        pendingRenderMode = ""
    }

    function requestRender(mode) {
        if (!renderSelectable)
            return
        if (continuousRenderMode !== mode)
            continuousRenderMode = ""
        // Only an explicit click may wait; a newer click replaces this request.
        pendingRenderMode = mode
        dispatchRender()
    }

    function dispatchRender() {
        if (!renderReady || pendingRenderMode === "")
            return
        const mode = pendingRenderMode
        pendingRenderMode = ""
        if (mode === "edited" && !Boolean(creatorState.maskEditable)) {
            stopContinuousRender()
            return
        }
        trigger(mode === "edited" ? "btn_musetalk_debug_first_frame_modified"
                                  : "btn_musetalk_debug_first_frame", {})
        if (continuousRenderMode !== "")
            continuousRenderTimer.restart()
    }

    function setContinuousRender(mode, checked) {
        if (!checked) {
            if (continuousRenderMode === mode)
                stopContinuousRender()
            return
        }
        if (!renderSelectable)
            return
        continuousRenderMode = mode
        requestRender(mode)
    }

    Timer {
        id: continuousRenderTimer
        interval: 1000
        repeat: true
        running: root.continuousRenderMode !== "" && root.renderSessionAllowed
        onTriggered: {
            if (root.renderReady && root.pendingRenderMode === "")
                root.requestRender(root.continuousRenderMode)
        }
    }
    // Defer dispatch until state notifications finish, avoiding reentrant model updates.
    Timer {
        id: renderStateTimer
        interval: 0
        onTriggered: {
            if (!root.renderSessionAllowed || (!root.commandBusy && root.creatorState.error))
                root.stopContinuousRender()
            else
                root.dispatchRender()
        }
    }
    onRenderReadyChanged: renderStateTimer.restart()
    onRenderSessionAllowedChanged: renderStateTimer.restart()
    Connections {
        target: root.creatorModel
        function onStateChanged() { renderStateTimer.restart() }
    }

    title: qsTr("MuseTalk Avatar Creator")
    description: qsTr("Prepare avatars while the chat runtime is stopped.")

    function isStandardSetting(controlId) {
        const id = String(controlId || "")
        if (id.indexOf("musetalk_pack_emotion_") === 0)
            return true
        return [
            "musetalk_target_pack_combo",
            "musetalk_avatar_combo",
            "musetalk_source_edit",
            "musetalk_avatar_id_edit",
            "musetalk_recreate_checkbox",
            "musetalk_create_frame_cache_checkbox",
            "musetalk_emotion_tags_edit",
            "musetalk_bbox_shift_spin",
            "musetalk_parsing_mode_combo",
            "musetalk_extra_margin_spin",
            "musetalk_left_cheek_width_spin",
            "musetalk_right_cheek_width_spin",
            "musetalk_mask_range_start_spin",
            "musetalk_mask_range_end_spin",
            "musetalk_mask_range_passthrough_checkbox",
            "musetalk_debug_frame_index_spin",
            "musetalk_debug_brush_size_spin",
            "musetalk_debug_brush_feather_spin",
            "musetalk_debug_brush_transparency_spin",
            "musetalk_test_audio_edit"
        ].indexOf(id) >= 0
    }

    function maskGroup(controlId) {
        if (["musetalk_bbox_shift_spin", "musetalk_parsing_mode_combo",
             "musetalk_extra_margin_spin", "musetalk_left_cheek_width_spin",
             "musetalk_right_cheek_width_spin"].indexOf(controlId) >= 0)
            return "geometry"
        if (["musetalk_mask_range_start_spin", "musetalk_mask_range_end_spin",
             "musetalk_mask_range_passthrough_checkbox", "musetalk_debug_frame_index_spin"].indexOf(controlId) >= 0)
            return "frame"
        if (["musetalk_debug_brush_size_spin", "musetalk_debug_brush_feather_spin",
             "musetalk_debug_brush_transparency_spin"].indexOf(controlId) >= 0)
            return "brush"
        return ""
    }

    function filteredSettingControls() {
        const result = []
        const source = addonControls || []
        for (let index = 0; index < source.length; ++index) {
            const original = source[index]
            const controlId = String(original.id || original.objectName || "")
            if (!isStandardSetting(controlId))
                continue
            const field = ({})
            for (const key in original)
                field[key] = original[key]
            const group = maskGroup(controlId)
            if (group !== "") {
                field.groupKey = "mask_" + group
                field.groupTitle = group === "geometry" ? qsTr("Mask geometry")
                                   : group === "frame" ? qsTr("Frame and range") : qsTr("Brush")
                field.groupDescription = ""
                field.groupOrder = group === "geometry" ? 0 : group === "frame" ? 100 : 200
            }
            result.push(field)
        }
        return result
    }

    function settingEnabled(controlId) {
        // Emotion toggles perform pack mutations, unlike ordinary settings.
        if (controlId.indexOf("musetalk_pack_emotion_") === 0)
            return mutatingAllowed
        const state = creatorState
        if (state.releaseBusy || state.startupPending || restrictionVisible)
            return false
        return !(state.pendingKeys || []).some(key => key !== "refresh"
            && key !== "trigger:btn_musetalk_debug_first_frame"
            && key !== "trigger:btn_musetalk_debug_first_frame_modified")
    }

    function controlValue(controlId) {
        const source = addonControls || []
        for (let index = 0; index < source.length; ++index) {
            const field = source[index]
            if (String(field.id || field.objectName || "") === String(controlId))
                return field.value
        }
        return undefined
    }

    function valuesEqual(currentValue, nextValue) {
        if (typeof currentValue === "number" || typeof nextValue === "number")
            return Number(currentValue) === Number(nextValue)
        if (typeof currentValue === "boolean" || typeof nextValue === "boolean")
            return Boolean(currentValue) === Boolean(nextValue)
        return String(currentValue === undefined ? "" : currentValue)
            === String(nextValue === undefined ? "" : nextValue)
    }

    function submitSetting(controlId, value) {
        const currentValue = controlValue(controlId)
        if (currentValue === undefined || valuesEqual(currentValue, value))
            return
        settingEdited(controlId, value)
        settingCommitRevision += 1
    }

    function trigger(controlId, payload) {
        if (creatorModel && !fieldBusy)
            creatorModel.trigger(controlId, payload === undefined ? ({}) : payload)
    }

    function variantAction(action, variantId) {
        const rows = creatorState.musetalk_native_variant_entries || []
        const entry = rows.find(row => row.id === variantId)
        if (!entry || !mutatingAllowed)
            return
        if (action === "preview")
            stopContinuousRender()
        preparedPreviewArmed = false
        const identity = JSON.parse(JSON.stringify(entry.identity || {}))
        if (action === "delete") {
            pendingVariant = identity
            variantDeleteDialog.open()
        } else if (action === "replace") {
            pendingVariant = identity
            variantSourceDialog.open()
        } else {
            trigger("btn_musetalk_variant_" + action, identity)
        }
    }

    function replaceVariantSource(path) {
        const payload = JSON.parse(JSON.stringify(pendingVariant))
        payload.source_path = path
        trigger("btn_musetalk_variant_replace", payload)
        pendingVariant = ({})
    }

    function requestConfirmation(controlId, key) {
        const targets = creatorState.musetalk_native_confirmation_targets || ({})
        const contract = targets[key] || ({})
        if (!Boolean(contract.required)) {
            trigger(controlId, {})
            return
        }
        pendingConfirmationControl = controlId
        pendingConfirmation = contract
        creatorConfirmationDialog.open()
    }

    function submitConfirmation() {
        const payload = ({})
        for (const key in pendingConfirmation)
            payload[key] = pendingConfirmation[key]
        payload.confirmed = true
        trigger(pendingConfirmationControl, payload)
        pendingConfirmationControl = ""
        pendingConfirmation = ({})
    }

    onVisibleChanged: {
        if (!visible) {
            preparedPreviewArmed = false
            stopContinuousRender()
        }
        else if (creatorModel)
            creatorModel.refresh()
    }
    Component.onCompleted: if (creatorModel) creatorModel.refresh()

    NCInlineMessage {
        id: restrictionBanner
        objectName: "creatorRestrictionBanner"
        Layout.fillWidth: true
        visible: root.restrictionVisible
        tone: "warning"
        title: qsTr("Stop the chat runtime to create or modify avatars")
        message: String(root.creatorAccess.reason
                        || qsTr("Creator jobs require the chat runtime to be fully stopped, including cleanup."))
    }

    ScrollView {
        id: workspaceScroll
        objectName: "creatorWorkspaceScroll"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        GridLayout {
            id: creatorGrid
            width: workspaceScroll.availableWidth
            columns: root.wideLayout ? 2 : 1
            columnSpacing: Theme.NCMetrics.space12
            rowSpacing: Theme.NCMetrics.space12

            NCLiveControlsGroup {
                id: creatorSettingsGroup
                objectName: "creatorSettingsGroup"
                Layout.column: 0
                Layout.row: 1
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                title: qsTr("Addon settings")
                description: qsTr("Saved through the standard MuseTalk addon settings path.")
                controls: root.generalSettingControls
                controlEnabled: controlId => root.settingEnabled(controlId)
                legacyPlacement: true
                onControlEdited: (controlId, value) => root.submitSetting(controlId, value)
            }

            NCCard {
                Layout.column: root.wideLayout ? 1 : 0
                Layout.row: root.wideLayout ? 1 : 2
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                title: qsTr("Creator actions")
                description: qsTr("Choose files and run guarded MuseTalk operations after reviewing the active settings.")

                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8
                    NCButton {
                        compact: true
                        text: qsTr("Refresh packs")
                        onClicked: root.trigger("btn_musetalk_target_pack_refresh", {})
                    }
                    NCButton {
                        compact: true
                        text: qsTr("New pack")
                        enabled: root.mutatingAllowed
                        onClicked: {
                            packName.text = ""
                            packDialog.open()
                        }
                    }
                    NCButton {
                        compact: true
                        text: qsTr("Refresh avatars")
                        onClicked: root.trigger("btn_musetalk_avatar_refresh", {})
                    }
                    NCButton {
                        compact: true
                        text: qsTr("Make default")
                        enabled: root.mutatingAllowed
                        onClicked: root.trigger("btn_musetalk_make_default_avatar", {})
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8
                    NCButton {
                        compact: true
                        text: qsTr("Choose video")
                        onClicked: {
                            root.pickerPurpose = "source"
                            sourceFileDialog.nameFilters = [qsTr("Video files (*.mp4 *.mov *.mkv *.avi *.webm)"), qsTr("All files (*)")]
                            sourceFileDialog.open()
                        }
                    }
                    NCButton {
                        compact: true
                        text: qsTr("Choose still image")
                        onClicked: {
                            root.pickerPurpose = "source"
                            sourceFileDialog.nameFilters = [qsTr("Image files (*.png *.jpg *.jpeg *.webp *.bmp)"), qsTr("All files (*)")]
                            sourceFileDialog.open()
                        }
                    }
                    NCButton {
                        compact: true
                        text: qsTr("Choose frame folder")
                        onClicked: sourceFolderDialog.open()
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: qsTr("Destination: %1").arg(String(root.creatorState.musetalk_native_destination || qsTr("Not selected")))
                    color: Theme.NCTheme.textMuted
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.WrapAnywhere
                }
                Label {
                    Layout.fillWidth: true
                    text: String(root.creatorState.musetalk_native_source_frame_info
                                 || root.creatorState.musetalk_native_source_frame_reason || "")
                    color: Theme.NCTheme.textMuted
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                    visible: text.length > 0
                }

                RowLayout {
                    Layout.fillWidth: true
                    NCButton {
                        id: preprocessButton
                        objectName: "preprocessButton"
                        Layout.fillWidth: true
                        text: qsTr("Preprocess avatar")
                        tone: "primary"
                        busy: root.fieldBusy || root.creatorBusy
                        enabled: root.mutatingAllowed
                        onClicked: root.requestConfirmation("btn_musetalk_prepare_avatar", "preprocess")
                    }
                    NCButton {
                        id: clearCacheButton
                        objectName: "clearCacheButton"
                        text: qsTr("Clear cache")
                        tone: "danger"
                        enabled: root.mutatingAllowed
                        onClicked: root.requestConfirmation("btn_musetalk_clear_frame_cache", "clear_frame_cache")
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: String(root.creatorState.musetalk_native_pack_emotion_summary || "")
                    color: Theme.NCTheme.textMuted
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                    visible: text.length > 0
                }
                AvatarEmotionList {
                    Layout.fillWidth: true
                    objectPrefix: "musetalkEmotion"
                    entries: root.creatorState.musetalk_native_variant_entries || []
                    busy: !root.mutatingAllowed
                    onActionRequested: (action, variantId) => root.variantAction(action, variantId)
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8
                    NCButton {
                        compact: true
                        text: qsTr("Enable all emotions")
                        enabled: root.mutatingAllowed
                        onClicked: root.trigger("btn_musetalk_pack_emotions_all", {})
                    }
                    NCButton {
                        compact: true
                        text: qsTr("Disable optional emotions")
                        enabled: root.mutatingAllowed
                        onClicked: root.trigger("btn_musetalk_pack_emotions_none", {})
                    }
                    NCButton {
                        compact: true
                        text: qsTr("Save metadata")
                        tone: "primary"
                        enabled: root.mutatingAllowed
                        onClicked: root.trigger("btn_musetalk_avatar_save_metadata", {})
                    }
                }
            }

            NCCard {
                Layout.column: 0
                Layout.row: root.wideLayout ? 2 : 3
                Layout.columnSpan: root.wideLayout ? 2 : 1
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                title: qsTr("Mask and frame ranges")
                description: qsTr("Tune the global mouth mask, then add frame-specific ranges or passthrough sections.")

                NCButton {
                    text: qsTr("Add range from current settings")
                    enabled: root.mutatingAllowed
                    onClicked: root.trigger("btn_musetalk_mask_range_add", {})
                }

                Label {
                    Layout.fillWidth: true
                    text: qsTr("Saved ranges")
                    color: Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.labelSize
                }
                Repeater {
                    model: root.rangeRows
                    delegate: Rectangle {
                        id: rangeRow
                        objectName: "rangeRow_" + rangeRow.index
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        implicitHeight: rangeLayout.implicitHeight + Theme.NCMetrics.space16
                        radius: Theme.NCMetrics.radiusMedium
                        color: index === Number(root.creatorState.musetalk_mask_range_selected_index)
                               ? Theme.NCTheme.surfaceSelected : Theme.NCTheme.windowRaised
                        border.color: Theme.NCTheme.border
                        RowLayout {
                            id: rangeLayout
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space8
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("Frames %1–%2 · %3").arg(rangeRow.modelData.start_frame)
                                      .arg(rangeRow.modelData.end_frame)
                                      .arg(Boolean(rangeRow.modelData.passthrough)
                                           ? qsTr("passthrough") : String(rangeRow.modelData.parsing_mode || "jaw"))
                                color: Theme.NCTheme.text
                                font.family: Theme.NCTypography.family
                                font.pixelSize: Theme.NCTypography.captionSize
                                wrapMode: Text.Wrap
                            }
                            NCButton {
                                objectName: "rangeLoadButton_" + rangeRow.index
                                compact: true
                                text: qsTr("Load")
                                enabled: root.mutatingAllowed
                                onClicked: root.trigger("btn_musetalk_mask_range_load", {"selected_index": rangeRow.index})
                            }
                            NCButton {
                                compact: true
                                text: qsTr("Update")
                                enabled: root.mutatingAllowed
                                onClicked: root.trigger("btn_musetalk_mask_range_update", {"selected_index": rangeRow.index})
                            }
                            NCButton {
                                compact: true
                                text: qsTr("Remove")
                                tone: "danger"
                                enabled: root.mutatingAllowed
                                onClicked: root.trigger("btn_musetalk_mask_range_remove", {"selected_index": rangeRow.index})
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: qsTr("Exact-frame edited mask overrides")
                    color: Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.labelSize
                }
                Repeater {
                    model: root.overrideRows
                    delegate: Rectangle {
                        id: overrideRow
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        implicitHeight: overrideLayout.implicitHeight + Theme.NCMetrics.space16
                        radius: Theme.NCMetrics.radiusMedium
                        color: index === Number(root.creatorState.musetalk_mask_override_selected_index)
                               ? Theme.NCTheme.surfaceSelected : Theme.NCTheme.windowRaised
                        border.color: Theme.NCTheme.border
                        RowLayout {
                            id: overrideLayout
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space8
                            Label {
                                Layout.fillWidth: true
                                text: qsTr("Frame %1 · %2 · %3")
                                      .arg(overrideRow.modelData.frame_index)
                                      .arg(String(overrideRow.modelData.range_label || qsTr("Global")))
                                      .arg(String(overrideRow.modelData.status || ""))
                                color: Theme.NCTheme.text
                                font.family: Theme.NCTypography.family
                                font.pixelSize: Theme.NCTypography.captionSize
                            }
                            NCButton {
                                compact: true
                                text: qsTr("Load")
                                enabled: root.mutatingAllowed
                                onClicked: root.trigger("btn_musetalk_mask_override_load", {"selected_index": overrideRow.index})
                            }
                            NCButton {
                                compact: true
                                text: qsTr("Remove")
                                tone: "danger"
                                enabled: root.mutatingAllowed
                                onClicked: root.trigger("btn_musetalk_mask_override_remove", {"selected_index": overrideRow.index})
                            }
                        }
                    }
                }
            }

            NCCard {
                objectName: "creatorMaskCard"
                Layout.column: 0
                Layout.row: 0
                Layout.columnSpan: root.wideLayout ? 2 : 1
                Layout.fillWidth: true
                Layout.preferredHeight: implicitHeight
                Layout.maximumHeight: implicitHeight
                Layout.alignment: Qt.AlignTop
                title: root.preparedPreviewActive ? qsTr("Prepared avatar preview") : qsTr("Mask editor")
                description: root.preparedPreviewActive
                    ? qsTr("Looping up to 10 seconds of prepared source frames. Stop the preview to return to mask editing.")
                    : qsTr("The mask overlay stays visible here. Rendered results open in Avatar Preview; paint and save an exact-frame override here.")

                GridLayout {
                    id: maskToolsGrid
                    Layout.fillWidth: true
                    columns: width >= 1000 ? 2 : 1
                    columnSpacing: Theme.NCMetrics.space12
                    rowSpacing: Theme.NCMetrics.space12

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 600
                        Layout.alignment: Qt.AlignTop
                        spacing: Theme.NCMetrics.space12

                        NCButton {
                            Layout.fillWidth: true
                            Layout.maximumHeight: implicitHeight
                            text: qsTr("Render preview")
                            tone: "primary"
                            busy: root.fieldBusy || root.creatorBusy
                            enabled: root.renderSelectable
                            onClicked: root.requestRender("normal")
                        }
                        NCSwitch {
                            objectName: "continuousRenderSwitch"
                            toolTipText: qsTr("Repeatedly request a normal mask preview while the creator is available. Checks once per second and skips ticks while GPU work or mask interaction is busy; this adds ongoing render work until switched off or the workspace closes.")
                            Layout.fillWidth: true
                            text: checked ? qsTr("Continuous Render: ON") : qsTr("Continuous Render: OFF")
                            checked: root.continuousRenderMode === "normal"
                            enabled: checked || root.renderSelectable
                            onToggled: root.setContinuousRender("normal", checked)
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: root.wideLayout ? 520 : 360
                            visible: root.preparedPreviewActive
                            color: Theme.NCTheme.windowRaised
                            Image {
                                objectName: "musetalkPreparedPreview"
                                anchors.fill: parent
                                source: root.preparedPreviewActive ? root.preparedFrameUrls[root.preparedFrameIndex] : ""
                                fillMode: Image.PreserveAspectFit
                                asynchronous: true
                                sourceSize.width: 800
                                sourceSize.height: 600
                            }
                        }
                        NCButton {
                            text: qsTr("Stop prepared preview")
                            visible: root.preparedPreviewActive
                            onClicked: root.preparedPreviewArmed = false
                        }
                        NCMuseTalkMaskEditor {
                            id: maskEditor
                            objectName: "creatorMaskEditor"
                            visible: !root.preparedPreviewActive
                            Layout.fillWidth: true
                            Layout.preferredHeight: root.wideLayout ? 520 : 360
                            Layout.maximumHeight: Layout.preferredHeight
                            creatorModel: root.creatorModel
                            enabled: !root.fieldBusy
                        }
                        NCButton {
                            Layout.fillWidth: true
                            Layout.maximumHeight: implicitHeight
                            text: qsTr("Render with edited mask")
                            enabled: root.renderSelectable && Boolean(root.creatorState.maskEditable)
                            onClicked: root.requestRender("edited")
                        }
                        NCSwitch {
                            objectName: "continuousEditedRenderSwitch"
                            toolTipText: qsTr("Repeatedly render using the edited mask while the creator is available. Requires an editable mask; checks once per second and skips busy ticks instead of building a render queue. Switch off to stop repeated GPU work.")
                            Layout.fillWidth: true
                            text: checked ? qsTr("Continuous Render: ON") : qsTr("Continuous Render: OFF")
                            checked: root.continuousRenderMode === "edited"
                            enabled: checked || (root.renderSelectable && Boolean(root.creatorState.maskEditable))
                            onToggled: root.setContinuousRender("edited", checked)
                        }

                        Label {
                            Layout.fillWidth: true
                            Layout.maximumHeight: implicitHeight
                            text: qsTr("Audio frame test")
                            color: Theme.NCTheme.textSecondary
                            font.family: Theme.NCTypography.family
                            font.pixelSize: Theme.NCTypography.labelSize
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.maximumHeight: implicitHeight
                            Item { Layout.fillWidth: true }
                            NCButton {
                                compact: true
                                text: qsTr("Choose")
                                onClicked: {
                                    root.pickerPurpose = "audio"
                                    sourceFileDialog.nameFilters = [qsTr("Audio files (*.wav *.mp3 *.flac *.m4a *.ogg)"), qsTr("All files (*)")]
                                    sourceFileDialog.open()
                                }
                            }
                            NCButton {
                                compact: true
                                text: qsTr("Run test")
                                enabled: root.mutatingAllowed
                                onClicked: root.trigger("btn_musetalk_first_frame_test", {})
                            }
                        }
                        NCScrollableTextArea {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 110
                            Layout.maximumHeight: Layout.preferredHeight
                            label: qsTr("Preview details")
                            toolTipText: qsTr("Read-only details from the latest preparation preview, including available frame, crop and mask diagnostics.")
                            readOnly: true
                            text: JSON.stringify(root.creatorState.musetalk_native_preview_details || ({}), null, 2)
                        }
                    }

                    NCLiveControlsGroup {
                        objectName: "creatorMaskSettingsGroup"
                        Layout.fillWidth: true
                        Layout.preferredWidth: 460
                        Layout.alignment: Qt.AlignTop
                        title: qsTr("Mask and preview settings")
                        controls: root.maskSettingControls
                        controlEnabled: controlId => root.settingEnabled(controlId)
                        legacyPlacement: true
                        onControlEdited: (controlId, value) => root.submitSetting(controlId, value)
                        onRefreshRequested: if (root.creatorModel) root.creatorModel.refresh()
                    }
                }
            }

            NCCard {
                Layout.column: 0
                Layout.row: root.wideLayout ? 3 : 4
                Layout.columnSpan: root.wideLayout ? 2 : 1
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                title: qsTr("Status")
                description: qsTr("Creator operations report real stages; no synthetic percentage is shown.")

                NCInlineMessage {
                    Layout.fillWidth: true
                    tone: root.creatorState.error ? "error"
                          : root.creatorBusy ? "warning" : "info"
                    title: root.creatorBusy
                           ? qsTr("Creator operation active") : qsTr("MuseTalk creator")
                    message: String(root.creatorState.error
                                    || root.creatorState.musetalk_native_status
                                    || qsTr("Ready."))
                }
                Label {
                    objectName: "creatorJobStage"
                    Layout.fillWidth: true
                    visible: root.creatorBusy
                    text: {
                        const job = root.creatorState.musetalk_native_active_job || ({})
                        return qsTr("Job %1 · %2 · %3")
                            .arg(String(root.creatorState.creator_job_id || job.job_id || ""))
                            .arg(String(job.action || qsTr("operation")))
                            .arg(String(job.stage || qsTr("working")))
                    }
                    color: Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.bodySize
                    wrapMode: Text.Wrap
                }
                Label {
                    objectName: "creatorResidencyStatus"
                    Layout.fillWidth: true
                    text: root.residency.release_requested ? qsTr("Waiting for active work, then unloading MuseTalk…")
                          : root.residency.loading ? qsTr("Loading MuseTalk for this editing session…")
                          : root.residency.loaded ? qsTr("MuseTalk is loaded for faster previews. GPU memory remains reserved.")
                          : root.residency.worker_failed ? qsTr("MuseTalk worker exited. The next preview will reload it.")
                          : qsTr("MuseTalk is unloaded. The first preview loads the worker.")
                    wrapMode: Text.Wrap
                    color: Theme.NCTheme.textSecondary
                }
                NCButton {
                    id: retryCreatorCleanupButton
                    objectName: "retryCreatorCleanupButton"
                    visible: Boolean(root.creatorState.musetalk_native_cleanup_pending)
                             && String(root.creatorAccess.owner || "") === "creator"
                             && String(root.creatorAccess.phase || "") === "cleanup_failed"
                    text: qsTr("Retry creator cleanup")
                    tone: "danger"
                    enabled: !root.fieldBusy
                    toolTipText: qsTr("Retry stopping the retained creator worker and release its existing reservation only after cleanup succeeds.")
                    onClicked: root.trigger("btn_musetalk_retry_cleanup", {})
                }
            }
        }
    }

    FileDialog {
        id: sourceFileDialog
        title: root.pickerPurpose === "audio"
               ? qsTr("Select MuseTalk test audio") : qsTr("Select MuseTalk source")
        fileMode: FileDialog.OpenFile
        onAccepted: {
            if (root.pickerPurpose === "variant") {
                root.replaceVariantSource(String(selectedFile))
                return
            }
            root.trigger(
            root.pickerPurpose === "audio"
                ? "btn_musetalk_test_audio" : "btn_musetalk_source_video",
            [String(selectedFile)])
        }
    }

    FolderDialog {
        id: sourceFolderDialog
        title: qsTr("Select MuseTalk source frame folder")
        onAccepted: root.trigger("btn_musetalk_source_folder", [String(selectedFolder)])
    }

    FolderDialog {
        id: variantFolderDialog
        title: qsTr("Choose replacement frame folder")
        onAccepted: root.replaceVariantSource(String(selectedFolder))
        onRejected: root.pendingVariant = ({})
    }

    NCDialog {
        id: variantSourceDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Replace source for %1").arg(String(root.pendingVariant.display_name || ""))
        description: qsTr("Tags and the base role stay with this entry. Its working files are kept until preparation succeeds.")
        acceptText: qsTr("Choose file")
        contentItem: NCButton {
            text: qsTr("Choose frame folder")
            onClicked: { variantSourceDialog.close(); variantFolderDialog.open() }
        }
        onAccepted: {
            root.pickerPurpose = "variant"
            sourceFileDialog.nameFilters = [qsTr("Media (*.mp4 *.mov *.mkv *.avi *.webm *.png *.jpg *.jpeg *.webp *.bmp)"), qsTr("All files (*)")]
            sourceFileDialog.open()
        }
    }

    NCDialog {
        id: variantDeleteDialog
        objectName: "musetalkVariantDeleteDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Delete %1 permanently?").arg(String(root.pendingVariant.display_name || ""))
        description: qsTr("Permanently removes this entry and its prepared files. Original source media outside its managed folder is kept.")
        acceptText: qsTr("Delete permanently")
        acceptTone: "danger"
        contentItem: Label {
            text: String(root.pendingVariant.directory || "")
            wrapMode: Text.WrapAnywhere
            color: Theme.NCTheme.text
        }
        onAccepted: {
            const payload = JSON.parse(JSON.stringify(root.pendingVariant))
            payload.confirmed = true
            root.trigger("btn_musetalk_variant_delete", payload)
            root.pendingVariant = ({})
        }
        onRejected: root.pendingVariant = ({})
    }

    NCDialog {
        id: packDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Create avatar pack")
        description: qsTr("Create a destination pack for related avatar and emotion variants.")
        acceptText: qsTr("Create pack")
        acceptEnabled: packName.text.trim().length > 0
        contentItem: NCTextField {
            id: packName
            label: qsTr("Pack name")
            toolTipText: qsTr("Name for a new destination pack grouping related prepared avatars and emotion variants. Creating the pack does not prepare source media; add or prepare avatars inside it afterward.")
            onAccepted: if (packDialog.acceptEnabled) packDialog.accept()
        }
        onAccepted: root.trigger("btn_musetalk_target_pack_new", packName.text.trim())
    }

    NCDialog {
        id: creatorConfirmationDialog
        objectName: "creatorConfirmationDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Confirm exact MuseTalk target")
        description: qsTr("This action changes or removes prepared data at the captured target below. Review it before continuing.")
        acceptText: qsTr("Continue with this target")
        acceptTone: "danger"
        contentItem: ColumnLayout {
            Label {
                Layout.fillWidth: true
                text: qsTr("Captured target")
                color: Theme.NCTheme.textSecondary
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.labelSize
            }
            Label {
                objectName: "creatorConfirmationTarget"
                Layout.fillWidth: true
                text: String(root.pendingConfirmation.target || "")
                color: Theme.NCTheme.text
                font.family: Theme.NCTypography.monoFamily
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.WrapAnywhere
            }
        }
        onAccepted: root.submitConfirmation()
    }
}
