pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Item {
    id: root
    objectName: "uiReviewOverlay"

    required property var controller
    required property var bridge
    required property string windowObjectName
    required property string workspaceKey
    property bool drawerEnabled: false
    property bool uiReviewIgnore: true
    property var hoverTarget: ({})
    property var pendingTarget: ({})
    property bool creatingLayoutCard: false
    readonly property bool targetBelongsHere:
        String(hoverTarget.windowObjectName || "") === root.windowObjectName
    readonly property point targetPoint: mapFromItem(
        null, Number(hoverTarget.x || 0), Number(hoverTarget.y || 0))

    signal navigateRequested(var note)

    z: 10000
    visible: controller.active || noteDialog.visible || (drawerEnabled && notesDrawer.visible)

    function workspaceLabel(key) {
        const entries = root.bridge.workspaces || []
        for (let index = 0; index < entries.length; ++index) {
            if (String(entries[index].key || "") === String(key || ""))
                return String(entries[index].label || key)
        }
        return String(key || "")
    }

    function noteContext() {
        const selectedAddon = root.bridge.selectedAddon || {}
        return {
            "workspace": root.workspaceKey,
            "workspaceLabel": workspaceLabel(root.workspaceKey),
            "addonId": root.workspaceKey === "addons"
                       ? String(root.bridge.selectedAddonId || "") : "",
            "addonLabel": root.workspaceKey === "addons"
                          ? String(selectedAddon.label || "") : "",
            "section": String(root.pendingTarget.section || "")
        }
    }

    function openNotes() {
        if (root.drawerEnabled)
            notesDrawer.open()
    }

    onDrawerEnabledChanged: {
        if (!drawerEnabled)
            notesDrawer.close()
    }

    function layoutPayload() {
        if (!Boolean(root.pendingTarget.layoutEditable))
            return ({})
        return root.controller.layoutFor(
            String(root.pendingTarget.surfaceId || ""),
            String(root.pendingTarget.section || "")) || ({})
    }

    function openTargetMenu() {
        const point = root.mapFromItem(
            null,
            Number(root.pendingTarget.x || 0)
                + Math.min(28, Number(root.pendingTarget.width || 0)),
            Number(root.pendingTarget.y || 0)
                + Math.min(28, Number(root.pendingTarget.height || 0)))
        targetMenu.x = Math.max(8, Math.min(root.width - targetMenu.width - 8, point.x))
        targetMenu.y = Math.max(8, Math.min(root.height - targetMenu.height - 8, point.y))
        targetMenu.open()
    }

    function openNoteEditor() {
        instructionText.text = ""
        noteDialog.open()
        Qt.callLater(instructionText.forceActiveFocus)
    }

    function openCardEditor(createCard) {
        root.creatingLayoutCard = Boolean(createCard)
        const cards = root.layoutPayload().cards || ({})
        const cardId = String(root.pendingTarget.layoutId || "")
        const override = cards[cardId] || ({})
        cardLabel.text = createCard
                         ? qsTr("New card")
                         : String(override.label
                                  || root.pendingTarget.groupTitle
                                  || root.pendingTarget.label
                                  || qsTr("Card"))
        cardWidth.currentIndex = Number(
            override.columnSpan !== undefined
            ? override.columnSpan
            : root.pendingTarget.layoutColumnSpan || 2) === 1 ? 1 : 0
        cardMinimumHeight.value = Math.max(
            0,
            Number(override.minimumHeight !== undefined
                   ? override.minimumHeight
                   : root.pendingTarget.layoutMinimumHeight || 0))
        cardPlacement.currentIndex = createCard ? 2 : 0
        cardDialog.open()
    }

    function openControlEditor() {
        controlLabel.text = String(root.pendingTarget.label
                                   || root.pendingTarget.defaultLabel
                                   || root.pendingTarget.identifier || "")
        controlCard.model = root.pendingTarget.layoutCards || []
        controlCard.currentIndex = 0
        for (let index = 0; index < controlCard.model.length; ++index) {
            if (String(controlCard.model[index].value)
                    === String(root.pendingTarget.groupKey || "")) {
                controlCard.currentIndex = index
                break
            }
        }
        controlPlacement.currentIndex = 0
        controlDialog.open()
    }

    Rectangle {
        id: targetOutline
        visible: root.controller.active && root.targetBelongsHere
                 && Number(root.hoverTarget.width || 0) > 1
                 && Number(root.hoverTarget.height || 0) > 1
        x: root.targetPoint.x - 3
        y: root.targetPoint.y - 3
        width: Number(root.hoverTarget.width || 0) + 6
        height: Number(root.hoverTarget.height || 0) + 6
        color: Theme.NCTheme.withAlpha(Theme.NCTheme.warning, 0.10)
        border.width: 2
        border.color: Theme.NCTheme.warning
        radius: Theme.NCMetrics.radiusSmall

        Rectangle {
            anchors.left: parent.left
            anchors.bottom: parent.top
            anchors.bottomMargin: Theme.NCMetrics.space4
            width: Math.min(root.width - x, targetLabel.implicitWidth + Theme.NCMetrics.space12)
            height: targetLabel.implicitHeight + Theme.NCMetrics.space6
            radius: Theme.NCMetrics.radiusSmall
            color: Theme.NCTheme.warningSoft
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.warning

            Label {
                id: targetLabel
                anchors.centerIn: parent
                width: Math.min(implicitWidth, parent.width - Theme.NCMetrics.space8)
                text: String(root.hoverTarget.label || root.hoverTarget.identifier || qsTr("UI component"))
                color: Theme.NCTheme.warning
                font.pixelSize: Theme.NCTypography.microSize
                font.weight: Theme.NCTypography.semibold
                elide: Text.ElideRight
            }
        }
    }

    Connections {
        target: root.controller

        function onHoverTargetChanged(target) {
            root.hoverTarget = String(target.windowObjectName || "") === root.windowObjectName
                               ? target : ({})
        }

        function onTargetRequested(target) {
            if (String(target.windowObjectName || "") !== root.windowObjectName)
                return
            root.pendingTarget = target
            root.openTargetMenu()
        }
    }

    Popup {
        id: targetMenu
        objectName: "uiReviewTargetMenu"
        parent: Overlay.overlay
        width: 300
        padding: Theme.NCMetrics.space6
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.surface
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space2

            Label {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.NCMetrics.space10
                Layout.rightMargin: Theme.NCMetrics.space10
                Layout.topMargin: Theme.NCMetrics.space6
                Layout.bottomMargin: Theme.NCMetrics.space4
                text: String(root.pendingTarget.label
                             || root.pendingTarget.identifier
                             || qsTr("UI component"))
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
                font.weight: Theme.NCTypography.semibold
                elide: Text.ElideRight
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                text: qsTr("Add note for Codex")
                glyph: "✎"
                onClicked: {
                    targetMenu.close()
                    root.openNoteEditor()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                Layout.leftMargin: Theme.NCMetrics.space8
                Layout.rightMargin: Theme.NCMetrics.space8
                visible: Boolean(root.pendingTarget.layoutEditable)
                color: Theme.NCTheme.borderSubtle
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                visible: Boolean(root.pendingTarget.layoutEditable)
                text: qsTr("Create a new card")
                glyph: "+"
                onClicked: {
                    targetMenu.close()
                    root.openCardEditor(true)
                }
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                visible: Boolean(root.pendingTarget.layoutEditable)
                         && String(root.pendingTarget.layoutKind || "") === "card"
                text: qsTr("Edit this card")
                glyph: "▣"
                onClicked: {
                    targetMenu.close()
                    root.openCardEditor(false)
                }
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                visible: Boolean(root.pendingTarget.layoutEditable)
                         && String(root.pendingTarget.layoutKind || "") === "control"
                text: qsTr("Edit label or placement")
                glyph: "↔"
                onClicked: {
                    targetMenu.close()
                    root.openControlEditor()
                }
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                visible: Boolean(root.pendingTarget.layoutEditable)
                         && root.controller.hasLayoutOverride(
                             String(root.pendingTarget.surfaceId || ""),
                             String(root.pendingTarget.section || ""),
                             String(root.pendingTarget.layoutKind || ""),
                             String(root.pendingTarget.layoutId || ""))
                text: qsTr("Reset this layout change")
                glyph: "↶"
                onClicked: {
                    targetMenu.close()
                    root.controller.resetLayoutTarget(
                        String(root.pendingTarget.surfaceId || ""),
                        String(root.pendingTarget.section || ""),
                        String(root.pendingTarget.layoutKind || ""),
                        String(root.pendingTarget.layoutId || ""))
                }
            }

            NCContextMenuItem {
                Layout.fillWidth: true
                visible: Boolean(root.pendingTarget.layoutEditable)
                         && root.controller.canUndoLayout
                text: qsTr("Undo last layout edit")
                glyph: "↩"
                onClicked: {
                    targetMenu.close()
                    root.controller.undoLayout()
                }
            }
        }
    }

    NCDialog {
        id: noteDialog
        objectName: "uiReviewNoteDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Add instruction for Codex")
        description: qsTr("This note records the exact native QML component. It does not change the interface automatically.")
        acceptText: qsTr("Save note")
        acceptTone: "warning"
        acceptEnabled: instructionText.text.trim().length > 0
        onAccepted: {
            root.controller.addNote(instructionText.text,
                                    root.pendingTarget,
                                    root.noteContext())
            root.pendingTarget = ({})
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space12

            NCInlineMessage {
                Layout.fillWidth: true
                tone: "warning"
                title: String(root.pendingTarget.label
                              || root.pendingTarget.identifier
                              || qsTr("UI component"))
                message: qsTr("%1 · %2")
                         .arg(String(root.pendingTarget.type || "QML item"))
                         .arg(String(root.pendingTarget.locator || ""))
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Theme.NCMetrics.space12
                rowSpacing: Theme.NCMetrics.space6

                Label { text: qsTr("Location"); color: Theme.NCTheme.textMuted }
                Label {
                    Layout.fillWidth: true
                    text: [root.workspaceLabel(root.workspaceKey),
                           root.pendingTarget.groupTitle,
                           root.pendingTarget.section].filter(Boolean).join("  ›  ")
                    color: Theme.NCTheme.textSecondary
                    elide: Text.ElideRight
                }
                Label { text: qsTr("Current value"); color: Theme.NCTheme.textMuted }
                Label {
                    Layout.fillWidth: true
                    text: String(root.pendingTarget.currentValue || qsTr("Not exposed"))
                    color: Theme.NCTheme.textSecondary
                    elide: Text.ElideRight
                }
            }

            Label {
                Layout.fillWidth: true
                text: qsTr("What should Codex change about this component?")
                color: Theme.NCTheme.text
                font.weight: Theme.NCTypography.semibold
            }

            NCTextArea {
                toolTipText: qsTr("Describe the UI change you want recorded for Codex. This creates a review note; it does not execute a code change automatically.")

                id: instructionText
                Layout.fillWidth: true
                Layout.preferredHeight: 150
                label: qsTr("Instruction for Codex")
                placeholderText: qsTr("Example: Move this control below the provider selector and shorten its label.")
            }
        }
    }

    NCDialog {
        id: cardDialog
        objectName: "uiReviewCardEditorDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: root.creatingLayoutCard ? qsTr("Create layout card")
                                       : qsTr("Edit layout card")
        description: qsTr("Only presentation metadata changes. Runtime controls and their saved setting IDs remain untouched.")
        acceptText: root.creatingLayoutCard ? qsTr("Create card") : qsTr("Save layout")
        acceptTone: "warning"
        acceptEnabled: cardLabel.text.trim().length > 0
        onAccepted: {
            const widthValue = Number(cardWidth.model[cardWidth.currentIndex].value)
            const placementValue = String(cardPlacement.model[cardPlacement.currentIndex].value)
            if (root.creatingLayoutCard) {
                root.controller.createLayoutCard(
                    String(root.pendingTarget.surfaceId || ""),
                    String(root.pendingTarget.section || ""),
                    cardLabel.text.trim(),
                    widthValue,
                    cardMinimumHeight.value,
                    placementValue)
            } else {
                root.controller.updateLayoutCard(
                    String(root.pendingTarget.surfaceId || ""),
                    String(root.pendingTarget.section || ""),
                    String(root.pendingTarget.layoutId || ""),
                    cardLabel.text.trim(),
                    widthValue,
                    cardMinimumHeight.value,
                    placementValue)
            }
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space12

            NCTextField {
                toolTipText: qsTr("Custom heading shown for this settings card in the interface. This changes its display label, not its underlying setting identifiers.")

                id: cardLabel
                Layout.fillWidth: true
                label: qsTr("Card label")
                placeholderText: qsTr("Card label")
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Theme.NCMetrics.space12
                rowSpacing: Theme.NCMetrics.space8

                Label { text: qsTr("Width"); color: Theme.NCTheme.textSecondary }
                NCComboBox {
                    toolTipText: qsTr("Choose how much horizontal space this card occupies in the settings layout. This is a saved UI layout preference.")

                    id: cardWidth
                    Layout.fillWidth: true
                    label: qsTr("Card width")
                    model: [
                        {"label": qsTr("Full width"), "value": 2},
                        {"label": qsTr("Half width"), "value": 1}
                    ]
                    textRole: "label"
                    valueRole: "value"
                }

                Label { text: qsTr("Minimum height"); color: Theme.NCTheme.textSecondary }
                NCSpinBox {
                    toolTipText: qsTr("Minimum height of this settings card in pixels. 0 allows its content and normal layout to determine the height.")

                    id: cardMinimumHeight
                    Layout.fillWidth: true
                    label: qsTr("Minimum card height in pixels")
                    from: 0
                    to: 1600
                    stepSize: 10
                }

                Label { text: qsTr("Placement"); color: Theme.NCTheme.textSecondary }
                NCComboBox {
                    toolTipText: qsTr("Choose the card's position relative to other cards in this settings section. This changes layout only.")

                    id: cardPlacement
                    Layout.fillWidth: true
                    label: qsTr("Card placement")
                    model: [
                        {"label": qsTr("Keep current position"), "value": "keep"},
                        {"label": qsTr("Move first"), "value": "first"},
                        {"label": qsTr("Move last"), "value": "last"}
                    ]
                    textRole: "label"
                    valueRole: "value"
                }
            }
        }
    }

    NCDialog {
        id: controlDialog
        objectName: "uiReviewControlEditorDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Edit component layout")
        description: qsTr("Change the display label or move this component between cards. Its runtime control ID remains unchanged.")
        acceptText: qsTr("Save layout")
        acceptTone: "warning"
        acceptEnabled: controlLabel.text.trim().length > 0
        onAccepted: {
            const cardValue = controlCard.currentIndex >= 0
                              ? String(controlCard.model[controlCard.currentIndex].value)
                              : String(root.pendingTarget.groupKey || "")
            const placementValue = String(
                controlPlacement.model[controlPlacement.currentIndex].value)
            root.controller.updateControlLayout(
                String(root.pendingTarget.surfaceId || ""),
                String(root.pendingTarget.section || ""),
                String(root.pendingTarget.layoutId || ""),
                controlLabel.text.trim(),
                cardValue,
                placementValue)
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space12

            NCTextField {
                toolTipText: qsTr("Custom label shown for this control. The underlying setting key and its behavior are unchanged.")

                id: controlLabel
                Layout.fillWidth: true
                label: qsTr("Display label")
                placeholderText: qsTr("Component label")
            }

            Label {
                Layout.fillWidth: true
                text: qsTr("Card")
                color: Theme.NCTheme.textSecondary
            }
            NCComboBox {
                toolTipText: qsTr("Choose which settings card contains this control. This changes its display placement and preserves its runtime binding.")

                id: controlCard
                Layout.fillWidth: true
                label: qsTr("Destination card")
                textRole: "label"
                valueRole: "value"
            }

            Label {
                Layout.fillWidth: true
                text: qsTr("Position inside card")
                color: Theme.NCTheme.textSecondary
            }
            NCComboBox {
                toolTipText: qsTr("Choose the control's position within the destination card. This changes presentation order only.")

                id: controlPlacement
                Layout.fillWidth: true
                label: qsTr("Component position")
                model: [
                    {"label": qsTr("Keep current position"), "value": "keep"},
                    {"label": qsTr("Move first"), "value": "first"},
                    {"label": qsTr("Move last"), "value": "last"}
                ]
                textRole: "label"
                valueRole: "value"
            }
        }
    }

    NCUiNotesDrawer {
        id: notesDrawer
        objectName: "uiReviewNotesDrawerHost"
        parent: Overlay.overlay
        controller: root.controller
        width: Math.min(520, parent ? parent.width * 0.46 : 520)
        height: parent ? parent.height : 760
        onNoteActivated: function(note) {
            root.navigateRequested(note)
            root.controller.requestHighlight(String(note.id || ""))
        }
    }
}
