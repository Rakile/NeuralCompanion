pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Drawer {
    id: root
    objectName: "uiReviewNotesDrawer"

    required property var controller
    property bool uiReviewIgnore: true
    property string filter: "open"
    property var pendingDeleteNote: ({})
    readonly property var filteredNotes: {
        const source = root.controller ? root.controller.notes : []
        if (root.filter === "all")
            return source
        const resolved = root.filter === "resolved"
        return source.filter(function(note) { return Boolean(note.resolved) === resolved })
    }

    signal noteActivated(var note)

    edge: Qt.RightEdge
    modal: false
    interactive: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    padding: 0

    background: Rectangle {
        color: Theme.NCTheme.windowRaised
        border.width: Theme.NCMetrics.focusWidth
        border.color: Theme.NCTheme.warning
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 78
            color: Theme.NCTheme.warningSoft
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.warning

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space16
                spacing: Theme.NCMetrics.space10

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space2

                    Label {
                        text: qsTr("UI review notes")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.titleSize
                        font.weight: Theme.NCTypography.semibold
                    }
                    Label {
                        text: qsTr("%1 open instruction(s) for Codex").arg(root.controller.openCount)
                        color: Theme.NCTheme.textSecondary
                        font.pixelSize: Theme.NCTypography.captionSize
                    }
                }

                NCIconButton {
                    glyph: "×"
                    toolTipText: qsTr("Close notes")
                    onClicked: root.close()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.NCMetrics.space12
            spacing: Theme.NCMetrics.space6

            Repeater {
                model: [
                    { "key": "open", "label": qsTr("Open") },
                    { "key": "resolved", "label": qsTr("Resolved") },
                    { "key": "all", "label": qsTr("All") }
                ]

                delegate: NCButton {
                    required property var modelData
                    Layout.fillWidth: true
                    compact: true
                    text: String(modelData.label)
                    tone: root.filter === String(modelData.key) ? "warning" : "secondary"
                    onClicked: root.filter = String(modelData.key)
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.NCMetrics.borderWidth
            color: Theme.NCTheme.border
        }

        Label {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: Theme.NCMetrics.space20
            visible: root.filteredNotes.length === 0
            text: root.filter === "open"
                  ? qsTr("No open UI notes. Enable Note mode, then right-click a component to add one.")
                  : qsTr("No notes match this filter.")
            color: Theme.NCTheme.textMuted
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        ListView {
            id: notesList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: Theme.NCMetrics.space12
            Layout.rightMargin: Theme.NCMetrics.space12
            visible: root.filteredNotes.length > 0
            clip: true
            spacing: Theme.NCMetrics.space8
            model: root.filteredNotes
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                id: noteCard
                required property var modelData
                width: notesList.width
                height: noteLayout.implicitHeight + Theme.NCMetrics.space24
                radius: Theme.NCMetrics.radiusMedium
                color: Theme.NCTheme.surface
                border.width: Theme.NCMetrics.borderWidth
                border.color: Boolean(modelData.resolved)
                              ? Theme.NCTheme.border
                              : Theme.NCTheme.warning

                ColumnLayout {
                    id: noteLayout
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: Theme.NCMetrics.space12
                    spacing: Theme.NCMetrics.space8

                    RowLayout {
                        Layout.fillWidth: true

                        Label {
                            Layout.fillWidth: true
                            text: String(noteCard.modelData.target.label
                                         || noteCard.modelData.target.identifier
                                         || qsTr("UI component"))
                            color: Theme.NCTheme.text
                            font.weight: Theme.NCTypography.semibold
                            elide: Text.ElideRight
                        }
                        NCStatusChip {
                            compact: true
                            text: Boolean(noteCard.modelData.resolved) ? qsTr("Resolved") : qsTr("Open")
                            status: Boolean(noteCard.modelData.resolved) ? "success" : "warning"
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: [noteCard.modelData.workspaceLabel,
                               noteCard.modelData.addonLabel,
                               noteCard.modelData.section].filter(Boolean).join("  ›  ")
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.microSize
                        elide: Text.ElideRight
                    }

                    Label {
                        Layout.fillWidth: true
                        text: String(noteCard.modelData.instruction || "")
                        color: Theme.NCTheme.textSecondary
                        wrapMode: Text.Wrap
                        maximumLineCount: 5
                        elide: Text.ElideRight
                    }

                    Label {
                        Layout.fillWidth: true
                        text: String(noteCard.modelData.target.locator || "")
                        color: Theme.NCTheme.warning
                        font.family: Theme.NCTypography.monoFamily
                        font.pixelSize: Theme.NCTypography.microSize
                        elide: Text.ElideMiddle
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space6

                        NCButton {
                            compact: true
                            text: qsTr("Open")
                            tone: "warning"
                            onClicked: root.noteActivated(noteCard.modelData)
                        }
                        NCButton {
                            compact: true
                            text: Boolean(noteCard.modelData.resolved) ? qsTr("Reopen") : qsTr("Resolve")
                            onClicked: root.controller.setResolved(
                                           String(noteCard.modelData.id),
                                           !Boolean(noteCard.modelData.resolved))
                        }
                        Item { Layout.fillWidth: true }
                        NCButton {
                            compact: true
                            text: qsTr("Delete")
                            tone: "quiet"
                            onClicked: {
                                root.pendingDeleteNote = noteCard.modelData
                                deleteDialog.open()
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 66
            color: Theme.NCTheme.surface
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.border

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space12
                spacing: Theme.NCMetrics.space8

                NCButton {
                    Layout.fillWidth: true
                    compact: true
                    text: qsTr("Copy open notes")
                    onClicked: root.controller.copyOpenNotes()
                }
                NCButton {
                    Layout.fillWidth: true
                    compact: true
                    text: qsTr("Export Markdown")
                    onClicked: root.controller.exportMarkdown()
                }
            }
        }
    }

    NCDialog {
        id: deleteDialog
        objectName: "uiReviewDeleteDialog"
        parent: Overlay.overlay
        title: qsTr("Delete UI note?")
        description: qsTr("This removes the selected Codex instruction from the review file.")
        acceptText: qsTr("Delete")
        acceptTone: "danger"
        onAccepted: {
            root.controller.deleteNote(String(root.pendingDeleteNote.id || ""))
            root.pendingDeleteNote = ({})
        }
    }
}
