pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root

    property var controls: []
    property bool flatSingleGroup: false
    property bool showRefresh: true
    // Optional runtime gate; keep transient availability out of field descriptors.
    property var controlEnabled: null
    property bool legacyPlacement: false
    property var layoutController: null
    property string layoutSurfaceId: ""
    property string layoutSection: ""
    property var pendingAction: ({})
    property bool cardsCollapsible: false
    property var cardCollapseState: ({})
    collapsible: cardsCollapsible
    collapsed: cardsCollapsible && Boolean(cardCollapseState[layoutSection + "::__controls"])
    onCollapseRequested: collapse => cardCollapseEdited(layoutSection + "::__controls", collapse)
    readonly property var renderedControlGroups: controlGroups()
    signal controlEdited(string controlId, var value)
    signal controlPreviewed(string controlId, var value)
    signal actionTriggered(string controlId)
    signal actionWithPayload(string controlId, var payload)
    signal refreshRequested()
    signal cardCollapseEdited(string card, bool collapsed)

    function optionIndex(options, wanted) {
        for (let index = 0; index < options.length; ++index) {
            if (String(options[index].value) === String(wanted))
                return index
        }
        return options.length > 0 ? 0 : -1
    }

    function displayScaledValue(field) {
        if (field.value === undefined)
            return ""
        return displayScaledNumber(field, field.value)
    }

    function displayScaledNumber(field, rawValue) {
        const scale = Math.max(1, Number(field.displayScale || 1))
        if (scale === 1)
            return String(Math.round(Number(rawValue)))
        const decimals = Math.max(1, Math.min(3, Math.ceil(Math.log(scale) / Math.LN10)))
        return (Number(rawValue) / scale).toFixed(decimals)
    }

    function fieldLabel(field) {
        const explicitLabel = String(field.label || "").trim()
        const fallbackLabel = String(field.objectName || "").trim()
        const candidate = explicitLabel.length > 0 ? explicitLabel : fallbackLabel
        const normalized = candidate.toLowerCase()
        if (normalized.indexOf("unnamed_") === 0
                || normalized.indexOf("unnamed ") === 0)
            return ""
        return candidate
    }

    function fieldToolTip(field) {
        const explicitHelp = String(
            field.toolTip || field.tooltip || field.description || "").trim()
        if (explicitHelp.length > 0)
            return explicitHelp
        return ""
    }

    function regularFields(group) {
        const result = []
        const source = group && group.controls ? group.controls : []
        for (let index = 0; index < source.length; ++index) {
            if (source[index].visible !== false
                    && !Boolean(source[index].actionStrip))
                result.push(source[index])
        }
        return result
    }

    function actionStripFields(group) {
        const result = []
        const source = group && group.controls ? group.controls : []
        for (let index = 0; index < source.length; ++index) {
            if (source[index].visible !== false
                    && Boolean(source[index].actionStrip))
                result.push(source[index])
        }
        return result
    }

    function runAction(field) {
        if (Boolean(field.destructive) || Boolean(field.confirmAction)) {
            root.pendingAction = field
            actionDialog.open()
        } else if (Boolean(field.inputPrompt)) {
            root.pendingAction = field
            actionInput.text = ""
            actionInputDialog.open()
        } else if (Boolean(field.saveFilePicker)) {
            root.pendingAction = field
            nativeFileDialog.fileMode = FileDialog.SaveFile
            nativeFileDialog.nameFilters = field.nameFilters || [qsTr("All files (*)")]
            nativeFileDialog.open()
        } else if (Boolean(field.filePicker)) {
            root.pendingAction = field
            nativeFileDialog.fileMode = Boolean(field.multiple)
                                        ? FileDialog.OpenFiles
                                        : FileDialog.OpenFile
            nativeFileDialog.nameFilters = field.nameFilters || [qsTr("All files (*)")]
            nativeFileDialog.open()
        } else if (Boolean(field.folderPicker)) {
            root.pendingAction = field
            nativeFolderDialog.open()
        } else if (Boolean(field.textViewer)) {
            root.pendingAction = field
            textViewerDialog.open()
        } else {
            root.actionTriggered(String(field.id))
        }
    }

    function controlGroups() {
        // Reading the revision makes this model react immediately after a
        // layout edit without touching the runtime-owned control values.
        const layoutRevision = root.layoutController
                               ? root.layoutController.layoutRevision : 0
        const layout = root.layoutController
                       ? (root.layoutController.layoutFor(
                              root.layoutSurfaceId, root.layoutSection) || ({}))
                       : ({})
        const cardOverrides = layout.cards || ({})
        const controlOverrides = layout.controls || ({})
        let groups = []
        const indexes = ({})

        function copied(source) {
            const target = ({})
            for (const key in (source || ({})))
                target[key] = source[key]
            return target
        }

        function ensureGroup(key, title, description, fallbackOrder, fallbackSpan) {
            let groupIndex = indexes[key]
            if (groupIndex !== undefined)
                return groups[groupIndex]
            const override = cardOverrides[key] || ({})
            groupIndex = groups.length
            indexes[key] = groupIndex
            const group = {
                "key": key,
                "title": override.label !== undefined
                         ? String(override.label)
                         : String(title || ""),
                "description": override.description !== undefined
                               ? String(override.description)
                               : String(description || ""),
                "columnSpan": override.columnSpan !== undefined
                              ? Math.max(1, Math.min(2, Number(override.columnSpan)))
                              : Math.max(1, Math.min(2, Number(fallbackSpan || 2))),
                "minimumHeight": Math.max(0, Number(override.minimumHeight || 0)),
                "order": override.order !== undefined
                         ? Number(override.order) : Number(fallbackOrder),
                "custom": Boolean(override.custom),
                "overridden": cardOverrides[key] !== undefined,
                "controls": []
            }
            groups.push(group)
            return group
        }

        for (let index = 0; index < root.controls.length; ++index) {
            const sourceField = root.controls[index]
            const controlId = String(sourceField.id || sourceField.objectName || "")
            const override = controlOverrides[controlId] || ({})
            const defaultKey = root.legacyPlacement
                               ? String(sourceField.groupKey || "general") : "general"
            const defaultTitle = root.legacyPlacement
                                 ? String(sourceField.groupTitle || "") : ""
            const defaultDescription = root.legacyPlacement
                                       ? String(sourceField.groupDescription || "") : ""
            const defaultOrder = sourceField.groupOrder !== undefined
                                 ? Number(sourceField.groupOrder) : index * 100
            ensureGroup(
                defaultKey,
                defaultTitle,
                defaultDescription,
                defaultOrder,
                root.legacyPlacement ? sourceField.groupColumnSpan : 2
            )
            const targetKey = String(override.groupKey || defaultKey)
            const targetGroup = ensureGroup(
                targetKey,
                targetKey === defaultKey ? defaultTitle : targetKey,
                targetKey === defaultKey ? defaultDescription : "",
                defaultOrder,
                2
            )
            const field = copied(sourceField)
            if (override.label !== undefined)
                field.label = String(override.label)
            field.groupKey = targetKey
            field.groupTitle = targetGroup.title
            field.layoutKind = "control"
            field.layoutId = controlId
            field.surfaceId = root.layoutSurfaceId
            field.section = root.layoutSection
            field.layoutEditable = Boolean(root.layoutController
                                           && root.layoutController.layoutEditingEnabled
                                           && controlId)
            field.defaultLabel = String(sourceField.label || sourceField.objectName || "")
            field.defaultGroupKey = defaultKey
            field.defaultGroupTitle = defaultTitle
            field.layoutOrder = override.order !== undefined
                                ? Number(override.order) : index * 100
            targetGroup.controls.push(field)
        }

        for (const cardKey in cardOverrides)
            ensureGroup(
                String(cardKey), String(cardKey), "",
                100000 + groups.length * 100, 2)

        groups = groups.filter(function(group) {
            return group.controls.length > 0 || group.custom || group.overridden
        })
        groups.sort(function(left, right) {
            if (left.order === right.order)
                return String(left.title).localeCompare(String(right.title))
            return left.order - right.order
        })
        const cardOptions = []
        for (let groupIndex = 0; groupIndex < groups.length; ++groupIndex) {
            const group = groups[groupIndex]
            cardOptions.push({"value": group.key,
                              "label": group.title || qsTr("Untitled card")})
        }
        for (let groupIndex = 0; groupIndex < groups.length; ++groupIndex) {
            const group = groups[groupIndex]
            group.controls.sort(function(left, right) {
                return Number(left.layoutOrder || 0) - Number(right.layoutOrder || 0)
            })
            for (let controlIndex = 0; controlIndex < group.controls.length; ++controlIndex) {
                group.controls[controlIndex].layoutCards = cardOptions
                group.controls[controlIndex].groupTitle = group.title
            }
        }
        void layoutRevision
        return groups
    }

    headerAccessory: NCButton {
        objectName: "liveControlsRefreshButton"
        visible: root.showRefresh
        text: qsTr("Refresh")
        tone: "secondary"
        compact: true
        onClicked: root.refreshRequested()
    }

    GridLayout {
        id: groupGrid
        Layout.fillWidth: true
        columns: width >= 920 ? 2 : 1
        columnSpacing: Theme.NCMetrics.space12
        rowSpacing: Theme.NCMetrics.space12

        Repeater {
            model: root.renderedControlGroups.length

            delegate: NCCard {
                id: legacyGroup
                required property int index
                property var modelData: index >= 0
                                        && index < root.renderedControlGroups.length
                                        ? root.renderedControlGroups[index] : ({})
                property var regularControlFields: root.regularFields(modelData)
                property var field: ({
                    "id": "layout-card:" + root.layoutSurfaceId + ":"
                          + root.layoutSection + ":" + String(modelData.key || ""),
                    "label": String(modelData.title || qsTr("Untitled card")),
                    "type": "layout-card",
                    "layoutKind": "card",
                    "layoutId": String(modelData.key || ""),
                    "surfaceId": root.layoutSurfaceId,
                    "section": root.layoutSection,
                    "groupKey": String(modelData.key || ""),
                    "groupTitle": String(modelData.title || ""),
                    "layoutColumnSpan": Number(modelData.columnSpan || 2),
                    "layoutMinimumHeight": Number(modelData.minimumHeight || 0),
                    "layoutCustom": Boolean(modelData.custom),
                    "layoutEditable": Boolean(root.layoutController
                                               && root.layoutController.layoutEditingEnabled
                                               && root.layoutSurfaceId
                                               && root.layoutSection),
                    "currentValue": qsTr("%1 controls · %2 column span")
                                    .arg((modelData.controls || []).length)
                                    .arg(Number(modelData.columnSpan || 2))
                })
                objectName: "layoutCard_" + String(modelData.key || "general")
                flat: root.flatSingleGroup
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                Layout.minimumHeight: Math.max(0, Number(modelData.minimumHeight || 0))
                Layout.columnSpan: groupGrid.columns > 1
                                   ? Math.min(groupGrid.columns, Number(modelData.columnSpan || 2))
                                   : 1
                title: String(modelData.title || "")
                description: String(modelData.description || "")
                elevated: !flat

                Repeater {
                    model: legacyGroup.regularControlFields.length
                    delegate: Loader {
                        id: liveRowLoader
                        required property int index
                        property var modelData: index >= 0
                                                && index < legacyGroup.regularControlFields.length
                                                ? legacyGroup.regularControlFields[index]
                                                : ({})
                        Layout.fillWidth: true
                        sourceComponent: liveControlRow
                        Binding {
                            target: liveRowLoader
                            property: "enabled"
                            value: !root.controlEnabled || root.controlEnabled(String(liveRowLoader.modelData.id || ""))
                            // Disabling a focused editor may commit it. Finish evaluation first.
                            delayed: true
                        }

                        Binding {
                            target: liveRowLoader.item
                            property: "field"
                            value: liveRowLoader.modelData
                            when: liveRowLoader.item !== null
                        }
                    }
                }

                GridLayout {
                    id: compactActionGrid
                    Layout.fillWidth: true
                    property var actionFields: root.actionStripFields(legacyGroup.modelData)
                    visible: actionFields.length > 0
                    columns: width >= 900 ? Math.min(6, actionFields.length)
                                           : width >= 560 ? Math.min(3, actionFields.length)
                                                          : Math.min(2, actionFields.length)
                    columnSpacing: Theme.NCMetrics.space8
                    rowSpacing: Theme.NCMetrics.space8

                    Repeater {
                        model: compactActionGrid.actionFields.length
                        delegate: NCButton {
                            id: compactActionButton
                            required property int index
                            property var modelData: index >= 0
                                                    && index < compactActionGrid.actionFields.length
                                                    ? compactActionGrid.actionFields[index]
                                                    : ({})
                            Layout.fillWidth: true
                            Layout.preferredWidth: Math.max(
                                                       112,
                                                       Number(modelData.compactActionWidth || 140))
                            enabled: Boolean(modelData.enabled)
                                     && (!root.controlEnabled || root.controlEnabled(String(modelData.id || "")))
                            text: String(modelData.label || qsTr("Run action"))
                            tone: Boolean(modelData.destructive) ? "danger" : "secondary"
                            toolTipText: root.fieldToolTip(modelData)
                            onClicked: root.runAction(modelData)
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: (legacyGroup.modelData.controls || []).length === 0
                    text: qsTr("Empty card · move a control here from its right-click layout editor")
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    Component {
        id: liveControlRow
        Rectangle {
            id: liveRow
            objectName: "tutorialControl_" + String(field.id || "")
            property var field: ({})
            property string controlKind: String(field.type || "text")
            property string displayLabel: root.fieldLabel(field)
            property string helpText: root.fieldToolTip(field)
            property bool contentOnlyDisplay: String(field.type || "") === "display"
                                              && displayLabel.length === 0
            property bool contentOnlyAction: controlKind === "action"
                                             && String(field.description || "").trim().length === 0
            property bool stackedLayout: Boolean(field.stackedLayout)
            property real editorPreferredWidth: Math.max(
                                                    0,
                                                    Number(field.editorPreferredWidth || 0))
            property bool expansiveEditor: controlKind === "multiline"
                                            || controlKind === "list"
                                            || controlKind === "image"
                                            || controlKind === "progress"
                                            || String(field.renderer || "").length > 0
            property real maximumContentWidth: stackedLayout || contentOnlyDisplay || expansiveEditor
                                               ? width
                                               : contentOnlyAction
                                                 ? 420
                                               : controlKind === "boolean"
                                                 ? 560
                                                 : controlKind === "display"
                                                   ? 760
                                                 : controlKind === "action"
                                                   ? 760
                                                   : 920
            Accessible.description: helpText
            property int minimumRowHeight: contentOnlyDisplay
                                           ? 0
                                           : controlKind === "boolean"
                                             || controlKind === "display"
                                             || controlKind === "action"
                                             ? 38 : 46
            implicitHeight: Math.max(
                                minimumRowHeight,
                                controlLayout.implicitHeight + Theme.NCMetrics.space8)
            color: "transparent"

            GridLayout {
                id: controlLayout
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.topMargin: Theme.NCMetrics.space4
                anchors.bottomMargin: Theme.NCMetrics.space4
                width: Math.min(liveRow.width, liveRow.maximumContentWidth)
                columns: liveRow.stackedLayout ? 1 : 2
                columnSpacing: Theme.NCMetrics.space12
                rowSpacing: Theme.NCMetrics.space4

                ColumnLayout {
                    Layout.row: 0
                    Layout.column: 0
                    Layout.fillWidth: liveRow.stackedLayout
                    Layout.preferredWidth: liveRow.expansiveEditor
                                           ? Math.min(300, controlLayout.width * 0.3)
                                           : Math.min(320, controlLayout.width * 0.45)
                    Layout.maximumWidth: liveRow.expansiveEditor ? 300 : 320
                    visible: !liveRow.contentOnlyDisplay && !liveRow.contentOnlyAction
                    spacing: Theme.NCMetrics.space2
                    Label {
                        Layout.fillWidth: true
                        visible: liveRow.controlKind !== "action"
                        text: liveRow.displayLabel
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.labelSize
                        font.weight: Theme.NCTypography.medium
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: String(liveRow.field.description || "").length > 0
                        text: String(liveRow.field.description || "")
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.captionSize
                        wrapMode: Text.Wrap
                    }
                }

                Loader {
                    id: liveEditor
                    property var field: liveRow.field
                    Layout.row: liveRow.stackedLayout ? 1 : 0
                    Layout.column: liveRow.stackedLayout ? 0 : 1
                    Layout.fillWidth: liveRow.editorPreferredWidth <= 0
                    Layout.preferredWidth: liveRow.editorPreferredWidth > 0
                                           ? liveRow.editorPreferredWidth
                                           : liveRow.contentOnlyDisplay
                                           ? controlLayout.width
                                           : liveRow.expansiveEditor
                                             ? Math.max(320, controlLayout.width * 0.62)
                                             : liveRow.stackedLayout
                                               ? controlLayout.width
                                               : Math.min(420, Math.max(220, controlLayout.width * 0.48))
                    sourceComponent: {
                        if (String(field.renderer || "") === "corsairKeyboard")
                            return corsairKeyboardEditor
                        if (String(field.renderer || "") === "color")
                            return colorEditor
                        const kind = String(field.type || "text")
                        if (kind === "boolean") return booleanEditor
                        if (kind === "choice") return field.searchable === true ? searchableChoiceEditor : choiceEditor
                        if (kind === "integer") return integerEditor
                        if (kind === "number") return numberEditor
                        if (kind === "slider") return sliderEditor
                        if (kind === "multiline")
                            return Boolean(field.scrollable)
                                   ? scrollableMultilineEditor : multilineEditor
                        if (kind === "list") return listEditor
                        if (kind === "display") return displayEditor
                        if (kind === "image") return imageEditor
                        if (kind === "progress") return progressEditor
                        if (kind === "action") return actionEditor
                        return textEditor
                    }
                    Binding {
                        target: liveEditor.item
                        property: "field"
                        value: liveRow.field
                        when: liveEditor.item !== null
                        restoreMode: Binding.RestoreNone
                    }
                }
            }

            NCHelp {
                target: liveRow
                focusTarget: liveEditor
                text: liveRow.helpText
            }

        }
    }

    Component {
        id: booleanEditor
        NCSwitch {
            helpDescription: root.fieldToolTip(field)

            property var field: ({})
            enabled: Boolean(field.enabled)
            text: checked ? qsTr("On") : qsTr("Off")
            checked: Boolean(field.value)
            onClicked: {
                if (checked && Boolean(field.confirmOnEnable)) {
                    checked = false
                    root.pendingAction = field
                    booleanConfirmDialog.open()
                } else {
                    root.controlEdited(String(field.id), checked)
                }
            }
        }
    }

    Component {
        id: searchableChoiceEditor
        NCSearchChoice {
            helpDescription: root.fieldToolTip(field)

            property var field: ({})
            objectName: String(field.id) + "_selector"
            enabled: Boolean(field.enabled)
            label: root.fieldLabel(field)
            options: field.options || []
            selectedValue: field.value
            selectionLabel: String(field.selectionLabel || field.value || "Select a model")
            onValueChosen: function(value) { root.controlEdited(String(field.id), value) }
        }
    }

    Component {
        id: choiceEditor
        NCComboBox {
            helpDescription: root.fieldToolTip(field)

            property var field: ({})
            enabled: Boolean(field.enabled)
            label: root.fieldLabel(field)
            model: field.options || []
            textRole: "label"
            valueRole: "value"
            displayText: field.selectionLabel !== undefined ? String(field.selectionLabel) : currentText
            currentIndex: root.optionIndex(model, field.value)
            onActivated: root.controlEdited(String(field.id), currentValue)
        }
    }

    Component {
        id: integerEditor
        NCSpinBox {
            helpDescription: root.fieldToolTip(field)

            property var field: ({})
            enabled: Boolean(field.enabled)
            label: root.fieldLabel(field)
            from: Number(field.minimum === undefined ? -2147483647 : field.minimum)
            to: Number(field.maximum === undefined ? 2147483647 : field.maximum)
            stepSize: Math.max(1, Number(field.step === undefined ? 1 : field.step))
            value: Number(field.value || 0)
            onValueModified: {
                // Optional sentinel boundary: -1 means all, and zero is invalid.
                // Native step methods preserve the value binding to refreshed state.
                if (Boolean(field.skipZero) && value === 0) {
                    if (Number(field.value) < 0) increase()
                    else decrease()
                }
                root.controlEdited(String(field.id), value)
            }
        }
    }

    Component {
        id: sliderEditor
        RowLayout {
            id: sliderRow
            property var field: ({})
            spacing: Theme.NCMetrics.space8

            onFieldChanged: {
                if (!sliderControl)
                    return
                if (!sliderControl.valueTrackingReady) {
                    sliderControl.fieldRefreshPending = true
                    return
                }
                if (sliderControl.pressed || sliderControl.commitInFlight
                        || sliderControl.hasPendingEdit) {
                    sliderControl.fieldRefreshPending = true
                    return
                }
                sliderControl.syncFromField()
            }

            Timer {
                id: livePreviewTimer
                interval: Math.max(16, Number(sliderRow.field.livePreviewInterval || 40))
                repeat: false
                onTriggered: root.controlPreviewed(
                    String(sliderRow.field.id), sliderControl.pendingValue)
            }

            Timer {
                id: deferredCommitTimer
                interval: 180
                repeat: false
                onTriggered: {
                    if (!sliderControl.pressed)
                        sliderControl.commitPendingValue()
                }
            }

            Timer {
                id: committedEchoTimer
                interval: 1500
                repeat: false
                onTriggered: {
                    // A failed/rejected backend write must eventually return
                    // the control to its authoritative value. Normal native
                    // writes echo synchronously and stop this timer.
                    sliderControl.awaitingCommittedEcho = false
                    if (!sliderControl.pressed)
                        sliderControl.syncFromField()
                }
            }

            NCSlider {
                helpDescription: root.fieldToolTip(sliderRow.field)

                id: sliderControl
                objectName: "liveControlSlider_" + String(sliderRow.field.id || "")
                Layout.fillWidth: true
                property int pendingValue: Math.round(value)
                property int lastCommittedValue: Math.round(value)
                property bool valueTrackingReady: false
                property bool syncingFromField: false
                property bool commitInFlight: false
                property bool fieldRefreshPending: false
                property bool awaitingCommittedEcho: false
                property int expectedCommittedValue: Math.round(value)
                readonly property bool deferredCommit: Boolean(sliderRow.field.deferredCommit)
                readonly property bool livePreview: deferredCommit
                                                    && Boolean(sliderRow.field.livePreview)
                readonly property bool hasPendingEdit: deferredCommit
                                                       && pendingValue !== lastCommittedValue
                enabled: Boolean(sliderRow.field.enabled)
                label: root.fieldLabel(sliderRow.field)
                from: Number(sliderRow.field.minimum === undefined ? 0 : sliderRow.field.minimum)
                to: Number(sliderRow.field.maximum === undefined ? 100 : sliderRow.field.maximum)
                stepSize: Math.max(1, Number(sliderRow.field.step === undefined ? 1 : sliderRow.field.step))
                Component.onCompleted: {
                    syncingFromField = true
                    value = boundedFieldValue()
                    pendingValue = Math.round(value)
                    lastCommittedValue = pendingValue
                    syncingFromField = false
                    valueTrackingReady = true
                    // Loader delegates can receive their authoritative field
                    // after child completion. Reconcile once the current event
                    // has delivered that binding instead of keeping the
                    // delegate's stale construction-time value.
                    Qt.callLater(syncFromField)
                }
                function boundedFieldValue() {
                    const rawValue = sliderRow.field.value === undefined
                                     ? 0 : Number(sliderRow.field.value)
                    if (!isFinite(rawValue))
                        return from
                    return Math.max(from, Math.min(to, rawValue))
                }
                function syncFromField() {
                    if (!valueTrackingReady || pressed || commitInFlight) {
                        fieldRefreshPending = true
                        return
                    }
                    const incomingValue = Math.round(boundedFieldValue())
                    if (awaitingCommittedEcho
                            && incomingValue !== expectedCommittedValue) {
                        fieldRefreshPending = true
                        return
                    }
                    if (awaitingCommittedEcho) {
                        awaitingCommittedEcho = false
                        committedEchoTimer.stop()
                    }
                    syncingFromField = true
                    value = incomingValue
                    pendingValue = Math.round(value)
                    lastCommittedValue = pendingValue
                    fieldRefreshPending = false
                    syncingFromField = false
                }
                function commitPendingValue() {
                    if (!deferredCommit || pendingValue === lastCommittedValue)
                        return
                    lastCommittedValue = pendingValue
                    expectedCommittedValue = pendingValue
                    awaitingCommittedEcho = true
                    committedEchoTimer.restart()
                    commitInFlight = true
                    root.controlEdited(String(sliderRow.field.id), pendingValue)
                    Qt.callLater(function() {
                        commitInFlight = false
                        if (fieldRefreshPending)
                            syncFromField()
                    })
                }
                onValueChanged: {
                    if (!valueTrackingReady || syncingFromField || !deferredCommit)
                        return
                    pendingValue = Math.round(value)
                    if (livePreview && !livePreviewTimer.running)
                        livePreviewTimer.start()
                    deferredCommitTimer.restart()
                }
                onMoved: {
                    pendingValue = Math.round(value)
                    if (!deferredCommit) {
                        root.controlEdited(String(sliderRow.field.id), pendingValue)
                    } else if (!pressed) {
                        livePreviewTimer.stop()
                        deferredCommitTimer.stop()
                        commitPendingValue()
                    }
                }
                onPressedChanged: {
                    if (pressed) {
                        fieldRefreshPending = false
                        return
                    }
                    if (!deferredCommit)
                        return
                    livePreviewTimer.stop()
                    deferredCommitTimer.stop()
                    pendingValue = Math.round(value)
                    commitPendingValue()
                }
            }
            NCSpinBox {
                helpDescription: root.fieldToolTip(sliderRow.field)

                id: valueEditor
                objectName: "liveControlValueEditor_"
                            + String(sliderRow.field.id || "")
                Layout.preferredWidth: 92
                Layout.minimumWidth: 80
                visible: Boolean(sliderRow.field.preciseEditor)
                enabled: sliderControl.enabled
                label: qsTr("Exact %1 value").arg(
                           root.fieldLabel(sliderRow.field))
                from: Math.round(sliderControl.from)
                to: Math.round(sliderControl.to)
                stepSize: Math.max(1, Math.round(sliderControl.stepSize))
                editable: true

                function displayScale() {
                    return Math.max(
                        1, Number(sliderRow.field.displayScale || 1))
                }

                validator: displayScale() > 1 ? scaledNumberValidator : integerValidator
                DoubleValidator {
                    id: scaledNumberValidator
                    locale: "C"
                    bottom: valueEditor.from / valueEditor.displayScale()
                    top: valueEditor.to / valueEditor.displayScale()
                    notation: DoubleValidator.StandardNotation
                }

                textFromValue: function(rawValue, locale) {
                    return root.displayScaledNumber(
                        sliderRow.field, rawValue)
                }

                valueFromText: function(text, locale) {
                    const normalized = String(text).trim()
                    const parsed = Number(normalized)
                    if (!isFinite(parsed))
                        return value
                    const rawValue = Math.round(parsed * displayScale())
                    return Math.max(from, Math.min(to, rawValue))
                }

                Component.onCompleted: value = Math.round(sliderControl.value)
                onValueModified: sliderControl.value = value

                Connections {
                    target: sliderControl
                    function onValueChanged() {
                        const nextValue = Math.round(sliderControl.value)
                        if (valueEditor.value !== nextValue)
                            valueEditor.value = nextValue
                    }
                }
            }
            Label {
                visible: !Boolean(sliderRow.field.preciseEditor)
                text: root.displayScaledNumber(
                          sliderRow.field, sliderControl.value)
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
                Layout.preferredWidth: 44
                horizontalAlignment: Text.AlignRight
            }
        }
    }

    Component {
        id: numberEditor
        NCNumberField {
            helpDescription: root.fieldToolTip(field)

            property var field: ({})
            enabled: Boolean(field.editableWhileInactive) || Boolean(field.enabled)
            readOnly: Boolean(field.readOnly)
            label: root.fieldLabel(field)
            text: String(field.value === undefined ? "" : field.value)
            minimum: Number(field.minimum === undefined ? -1000000000 : field.minimum)
            maximum: Number(field.maximum === undefined ? 1000000000 : field.maximum)
            stepSize: /(?:^|_)(temperature|repetition_penalty|repeat_penalty|min_p)$/.test(String(field.id))
                      ? 0.05 : Number(field.step === undefined ? 0.01 : field.step)
            onEditingFinished: {
                if (!readOnly && acceptableInput && isFinite(Number(text)))
                    root.controlEdited(String(field.id), Number(text))
            }
        }
    }

    Component {
        id: textEditor
        NCTextField {
            helpDescription: root.fieldToolTip(field)

            property var field: ({})
            enabled: Boolean(field.editableWhileInactive) || Boolean(field.enabled)
            readOnly: Boolean(field.readOnly)
            label: root.fieldLabel(field)
            text: String(field.value === undefined ? "" : field.value)
            echoMode: Boolean(field.secret) ? TextInput.Password : TextInput.Normal
            validator: String(field.type) === "integer" ? integerValidator
                     : String(field.type) === "number" ? numberValidator : null
            onEditingFinished: {
                if (Boolean(field.readOnly))
                    return
                let nextValue = text
                if (String(field.type) === "integer") nextValue = parseInt(text)
                if (String(field.type) === "number") {
                    nextValue = Number(text)
                    if (!acceptableInput || !isFinite(nextValue))
                        return
                }
                root.controlEdited(String(field.id), nextValue)
            }
        }
    }

    Component {
        id: colorEditor
        RowLayout {
            id: colorRow
            property var field: ({})
            objectName: "liveControlColorEditor_" + String(field.id || "")
            spacing: Theme.NCMetrics.space8

            function normalizedHex(value) {
                const text = String(value || "").trim().toUpperCase()
                return /^#[0-9A-F]{6}$/.test(text) ? text : ""
            }

            function commitColor(value) {
                const normalized = normalizedHex(value)
                if (normalized.length > 0)
                    root.controlEdited(String(field.id), normalized)
            }

            Button {
                id: colorSwatch
                objectName: "liveControlColorSwatch_" + String(colorRow.field.id || "")
                Layout.preferredWidth: 48
                Layout.preferredHeight: 40
                enabled: Boolean(colorRow.field.enabled)
                Accessible.name: qsTr("Choose %1 color").arg(root.fieldLabel(colorRow.field))
                onClicked: {
                    const current = String(colorRow.field.value || "#000000")
                    if (Boolean(colorRow.field.colorWheel)) {
                        colorWheelLoader.item.draftColor = current
                        colorWheelLoader.item.open()
                    } else {
                        colorDialog.selectedColor = current
                        colorDialog.open()
                    }
                }
                contentItem: Item {}
                background: Rectangle {
                    radius: Theme.NCMetrics.radiusSmall
                    color: String(colorRow.field.value || "#000000")
                    border.width: colorSwatch.activeFocus
                                  ? Theme.NCMetrics.focusWidth
                                  : Theme.NCMetrics.borderWidth
                    border.color: colorSwatch.activeFocus
                                  ? Theme.NCTheme.focus
                                  : colorSwatch.hovered
                                    ? Theme.NCTheme.borderStrong
                                    : Theme.NCTheme.border
                }
            }

            NCTextField {
                helpDescription: root.fieldToolTip(colorRow.field)

                id: colorHexField
                objectName: "liveControlColorText_" + String(colorRow.field.id || "")
                Layout.fillWidth: true
                enabled: Boolean(colorRow.field.enabled)
                label: qsTr("%1 hex color").arg(root.fieldLabel(colorRow.field))
                text: String(colorRow.field.value === undefined
                             ? "" : colorRow.field.value)
                validator: RegularExpressionValidator {
                    regularExpression: /^#[0-9A-Fa-f]{6}$/
                }
                onEditingFinished: {
                    if (acceptableInput)
                        colorRow.commitColor(text)
                    else
                        text = String(colorRow.field.value || "")
                }
            }

            ColorDialog {
                id: colorDialog
                objectName: "liveControlColorDialog_" + String(colorRow.field.id || "")
                title: qsTr("Choose %1 color").arg(root.fieldLabel(colorRow.field))
                onAccepted: colorRow.commitColor(selectedColor.toString())
            }

            Loader {
                id: colorWheelLoader
                active: Boolean(colorRow.field.colorWheel)
                sourceComponent: NCDialog {
                    id: colorWheelDialog
                    objectName: "liveControlColorWheelDialog_" + String(colorRow.field.id || "")
                    parent: Overlay.overlay
                    anchors.centerIn: parent
                    width: Math.min(380, parent ? parent.width - 24 : 380)
                    property color draftColor: "#000000"
                    title: root.fieldLabel(colorRow.field)
                    description: qsTr("Choose a color, then Apply. Select the Custom palette to use your custom colors.")
                    acceptText: qsTr("Apply")
                    acceptEnabled: Boolean(colorRow.field.enabled) && !Boolean(colorRow.field.readOnly)
                    onAccepted: colorRow.commitColor(draftColor.toString())
                    contentItem: NCColorWheel {
                        objectName: "liveControlColorWheel_" + String(colorRow.field.id || "")
                        selectedColor: colorWheelDialog.draftColor
                        onColorEdited: value => colorWheelDialog.draftColor = value
                    }
                }
            }
        }
    }

    Component {
        id: multilineEditor
        NCTextArea {
            helpDescription: root.fieldToolTip(field)

            property var field: ({})
            enabled: Boolean(field.enabled)
            readOnly: Boolean(field.readOnly)
            implicitHeight: 132
            label: root.fieldLabel(field)
            text: String(field.value === undefined ? "" : field.value)
            onActiveFocusChanged: {
                if (!activeFocus && !Boolean(field.readOnly))
                    root.controlEdited(String(field.id), text)
            }
        }
    }

    Component {
        id: scrollableMultilineEditor
        ScrollView {
            id: multilineScroll
            property var field: ({})
            objectName: String(field.id || "") + "_scrollableEditor"
            implicitHeight: Math.max(
                96, Number(field.editorPreferredHeight || 132))
            clip: true
            padding: 1
            rightPadding: multilineBar.visible ? multilineBar.width + 3 : 1
            contentWidth: availableWidth
            contentHeight: multilineViewport.contentHeight
            wheelEnabled: false
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: ScrollBar {
                id: multilineBar
                x: multilineScroll.width - width - 1
                y: 1
                width: 14
                height: multilineScroll.height - 2
                minimumSize: 0.15
                policy: multilineScroll.contentHeight > multilineScroll.availableHeight
                        ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                active: true
                interactive: true
            }

            // Keep wheel input local to the text box, including pixel-delta devices.
            WheelHandler {
                target: null
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                enabled: multilineScroll.contentHeight > multilineScroll.availableHeight
                onWheel: function(event) {
                    const viewport = multilineScroll.contentItem
                    const delta = event.pixelDelta.y !== 0 ? event.pixelDelta.y
                                  : event.angleDelta.y / 120 * multilineText.font.pixelSize * 3
                    if (delta === 0) {
                        event.accepted = false
                        return
                    }
                    const maximum = Math.max(0, viewport.contentHeight - viewport.height)
                    viewport.contentY = Math.max(0, Math.min(maximum, viewport.contentY - delta))
                    event.accepted = true
                }
            }

            // An explicit viewport prevents ScrollView from sizing the text item
            // to the box when a reused row receives its descriptor after creation.
            contentItem: Flickable {
                id: multilineViewport
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                TextArea.flickable: NCTextArea {
                    helpDescription: root.fieldToolTip(multilineScroll.field)

                    id: multilineText
                    implicitHeight: Math.max(multilineViewport.height,
                                             contentHeight + topPadding + bottomPadding)
                    enabled: Boolean(multilineScroll.field.enabled)
                    readOnly: Boolean(multilineScroll.field.readOnly)
                    label: root.fieldLabel(multilineScroll.field)
                    text: String(multilineScroll.field.value === undefined
                                 ? "" : multilineScroll.field.value)
                    background: null
                    onActiveFocusChanged: {
                        if (!activeFocus && !Boolean(multilineScroll.field.readOnly))
                            root.controlEdited(
                                String(multilineScroll.field.id), text)
                    }
                }
            }

            background: Rectangle {
                radius: Theme.NCMetrics.radiusMedium
                color: multilineText.enabled
                       ? Theme.NCTheme.windowRaised : Theme.NCTheme.surface
                border.width: multilineText.activeFocus
                              ? Theme.NCMetrics.focusWidth
                              : Theme.NCMetrics.borderWidth
                border.color: multilineText.activeFocus
                              ? Theme.NCTheme.focus
                              : multilineScroll.hovered
                                ? Theme.NCTheme.borderStrong
                                : Theme.NCTheme.border
            }
        }
    }

    Component {
        id: corsairKeyboardEditor
        NCCorsairKeyboardPreview {}
    }

    Component {
        id: displayEditor
        Label {
            property var field: ({})
            text: String(field.value === undefined ? "" : field.value)
            color: Theme.NCTheme.textSecondary
            font.pixelSize: Theme.NCTypography.captionSize
            wrapMode: Text.Wrap
            verticalAlignment: Text.AlignVCenter
        }
    }

    Component {
        id: imageEditor
        Rectangle {
            property var field: ({})
            implicitWidth: Math.max(
                               Number(field.imageMinimumWidth || 0),
                               Number(field.imagePreferredWidth || 240))
            implicitHeight: Math.max(
                                Number(field.imageMinimumHeight || 0),
                                Number(field.imagePreferredHeight || 180))
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.window
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.border
            Image {
                id: previewImage
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space4
                source: String(parent.field.value || "")
                asynchronous: true
                cache: false
                fillMode: Image.PreserveAspectFit
                sourceSize.width: 512
                sourceSize.height: 512
            }
            Label {
                anchors.centerIn: parent
                width: Math.max(0, parent.width - Theme.NCMetrics.space24)
                visible: previewImage.status !== Image.Ready
                text: String(parent.field.imagePlaceholder || qsTr("No preview available"))
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }
        }
    }

    Component {
        id: progressEditor
        ColumnLayout {
            id: progressColumn
            property var field: ({})
            spacing: Theme.NCMetrics.space6
            NCProgressBar {
                Layout.fillWidth: true
                from: Number(progressColumn.field.minimum === undefined ? 0 : progressColumn.field.minimum)
                to: Number(progressColumn.field.maximum === undefined ? 100 : progressColumn.field.maximum)
                value: Number(progressColumn.field.value || 0)
            }
            Label {
                Layout.fillWidth: true
                text: String(progressColumn.field.value === undefined ? "" : progressColumn.field.value)
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.microSize
                horizontalAlignment: Text.AlignRight
            }
        }
    }

    Component {
        id: listEditor
        Rectangle {
            id: listSurface
            property var field: ({})
            implicitHeight: Math.min(190, Math.max(54, optionList.contentHeight + 2))
            radius: Theme.NCMetrics.radiusSmall
            color: Theme.NCTheme.window
            border.color: Theme.NCTheme.border

            ListView {
                id: optionList
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                model: listSurface.field.options || []
                currentIndex: root.optionIndex(model, listSurface.field.value)
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    id: optionRow
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    height: Math.max(34, optionLabel.implicitHeight + Theme.NCMetrics.space12)
                    color: index === optionList.currentIndex
                           ? Theme.NCTheme.surfaceSelected
                           : optionMouse.containsMouse
                             ? Theme.NCTheme.surfaceRaised
                             : "transparent"

                    Label {
                        id: optionLabel
                        anchors.fill: parent
                        anchors.leftMargin: Theme.NCMetrics.space10
                        anchors.rightMargin: Theme.NCMetrics.space10
                        verticalAlignment: Text.AlignVCenter
                        text: String(optionRow.modelData.label || "")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.captionSize
                        wrapMode: Text.Wrap
                    }

                    MouseArea {
                        id: optionMouse
                        anchors.fill: parent
                        enabled: Boolean(listSurface.field.enabled)
                        hoverEnabled: true
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            optionList.currentIndex = optionRow.index
                            root.controlEdited(
                                String(listSurface.field.id),
                                optionRow.modelData.value
                            )
                        }
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: optionList.count === 0
                    text: qsTr("No items")
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.captionSize
                }
            }
        }
    }

    Component {
        id: actionEditor
        NCButton {
            property var field: ({})
            enabled: Boolean(field.enabled)
            text: String(field.label || qsTr("Run action"))
            tone: Boolean(field.destructive) ? "danger" : "secondary"
            onClicked: root.runAction(field)
        }
    }

    IntValidator { id: integerValidator; bottom: -2147483647; top: 2147483647 }
    DoubleValidator { id: numberValidator; locale: "C"; bottom: -1000000000; top: 1000000000 }

    FileDialog {
        id: nativeFileDialog
        title: String(root.pendingAction.dialogTitle || root.pendingAction.label || qsTr("Select file"))
        onAccepted: {
            const values = []
            if (fileMode === FileDialog.OpenFiles) {
                for (let index = 0; index < selectedFiles.length; ++index)
                    values.push(String(selectedFiles[index]))
            } else {
                values.push(String(selectedFile))
            }
            root.actionWithPayload(String(root.pendingAction.id || ""), values)
        }
    }

    FolderDialog {
        id: nativeFolderDialog
        title: String(root.pendingAction.dialogTitle || root.pendingAction.label || qsTr("Select folder"))
        onAccepted: root.actionWithPayload(
                        String(root.pendingAction.id || ""),
                        [String(selectedFolder)])
    }

    NCDialog {
        id: actionInputDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: String(root.pendingAction.dialogTitle || root.pendingAction.label || qsTr("Enter value"))
        description: String(root.pendingAction.description || "")
        acceptText: qsTr("Continue")
        rejectText: qsTr("Cancel")
        acceptEnabled: actionInput.text.trim().length > 0
        contentItem: NCTextField {
            id: actionInput
            toolTipText: String(root.pendingAction.toolTip || root.pendingAction.description || qsTr("Enter the name or value requested by this action. Continue submits it to the selected add-on; Cancel leaves the action unapplied."))
            label: String(root.pendingAction.inputLabel || root.pendingAction.label || qsTr("Value"))
            placeholderText: String(root.pendingAction.placeholderText || "")
            onAccepted: {
                if (actionInputDialog.acceptEnabled)
                    actionInputDialog.accept()
            }
        }
        onAccepted: root.actionWithPayload(
                        String(root.pendingAction.id || ""),
                        actionInput.text.trim())
    }

    NCDialog {
        id: booleanConfirmDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: String(root.pendingAction.confirmationTitle || qsTr("Confirm setting"))
        description: String(root.pendingAction.confirmationText || root.pendingAction.description || "")
        acceptText: qsTr("Enable")
        rejectText: qsTr("Cancel")
        acceptTone: "danger"
        onAccepted: root.controlEdited(String(root.pendingAction.id || ""), true)
    }

    NCDialog {
        id: textViewerDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(980, Overlay.overlay ? Overlay.overlay.width - 64 : 980)
        height: Math.min(720, Overlay.overlay ? Overlay.overlay.height - 64 : 720)
        title: String(root.pendingAction.dialogTitle || root.pendingAction.label || qsTr("Details"))
        description: String(root.pendingAction.viewerDescription || "")
        acceptText: qsTr("Close")
        rejectText: ""
        contentItem: ScrollView {
            clip: true
            TextArea {
                id: viewerArea
                text: String(root.pendingAction.viewerText || "")
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.NoWrap
                color: Theme.NCTheme.text
                selectionColor: Theme.NCTheme.accent
                selectedTextColor: Theme.NCTheme.window
                background: Rectangle {
                    color: Theme.NCTheme.window
                    border.color: Theme.NCTheme.border
                    radius: Theme.NCMetrics.radiusSmall
                }
                ContextMenu.menu: NCTextEditingContextMenu {
                    editor: viewerArea
                }
            }
        }
    }

    NCDialog {
        id: actionDialog
        objectName: "nativeActionConfirmation"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: String(root.pendingAction.confirmationTitle || qsTr("Confirm addon action"))
        description: String(root.pendingAction.confirmationText || qsTr("Run “%1”? The existing addon controller will perform this action.")
                     .arg(String(root.pendingAction.label || qsTr("this action"))))
        acceptText: String(root.pendingAction.confirmationAcceptText || qsTr("Run action"))
        rejectText: qsTr("Cancel")
        acceptTone: String(root.pendingAction.confirmationTone || "danger")
        onAccepted: {
            if (root.pendingAction.confirmationPayload !== undefined)
                root.actionWithPayload(String(root.pendingAction.id || ""), root.pendingAction.confirmationPayload)
            else
                root.actionTriggered(String(root.pendingAction.id || ""))
        }
    }
}
