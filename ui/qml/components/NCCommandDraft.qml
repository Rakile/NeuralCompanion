pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    required property var bridge
    required property var commands
    readonly property var draft: commands.draft
    readonly property bool imagePrompt: draft.command === "generate_visual_refine"
    visible: String(draft.original || "").length > 0
    spacing: 6

    RowLayout {
        Layout.fillWidth: true
        BusyIndicator { running: Boolean(root.draft.busy); visible: running; implicitWidth: 24; implicitHeight: 24 }
        Label {
            text: root.imagePrompt
                ? (root.draft.busy ? qsTr("Refining image prompt…") : qsTr("Image prompt · Not generated"))
                : (root.draft.busy ? qsTr("Creating draft…") : qsTr("Draft · Not sent"))
            color: Theme.NCTheme.accent
            font.bold: true
        }
        Label {
            text: String(root.draft.provider || "")
            color: Theme.NCTheme.textMuted
            Layout.fillWidth: true
            elide: Text.ElideMiddle
        }
    }
    Label {
        Layout.fillWidth: true
        visible: text.length > 0
        text: String(root.draft.error || "")
        color: Theme.NCTheme.error
        wrapMode: Text.Wrap
    }
    ScrollView {
        Layout.fillWidth: true
        Layout.preferredHeight: 160
        visible: !root.draft.ideas || root.draft.ideas.length === 0
        clip: true
        NCSpellcheckTextArea {
            toolTipText: qsTr("Review and edit the proposed command output before using the send or generate action. Editing this draft does not submit a model request by itself.")

            id: editor
            objectName: "commandDraftEditor"
            bridge: root.bridge
            implicitHeight: Math.max(160, contentHeight + topPadding + bottomPadding)
            text: String(root.draft.text || "")
            readOnly: Boolean(root.draft.busy)
            placeholderText: root.imagePrompt ? qsTr("Review and edit the image prompt before generating") : qsTr("Your editable draft will appear here")
            label: root.imagePrompt ? qsTr("Image generation prompt") : qsTr("Unsent command draft")
            onTextChanged: {
                if (text !== String(root.draft.text || ""))
                    root.commands.setDraftText(text)
            }
        }
    }
    ScrollView {
        Layout.fillWidth: true
        Layout.preferredHeight: 160
        visible: Boolean(root.draft.ideas && root.draft.ideas.length > 0)
        clip: true
        Column {
            width: parent.width
            Repeater {
                model: root.draft.ideas || []
                delegate: ItemDelegate {
                    id: idea
                    required property string modelData
                    required property int index
                    width: parent.width
                    enabled: !root.draft.busy
                    contentItem: Label { text: idea.modelData; color: Theme.NCTheme.text; wrapMode: Text.Wrap }
                    onClicked: root.commands.chooseIdea(index)
                }
            }
        }
    }
    Flow {
        Layout.fillWidth: true
        spacing: 6
        NCButton { objectName: "commandDraftSubmit"; text: root.imagePrompt ? qsTr("Generate image") : qsTr("Send draft"); compact: true; tone: "primary"; enabled: !root.draft.busy && String(root.draft.text || "").trim().length > 0; onClicked: root.commands.sendDraft() }
        NCButton { text: qsTr("Copy"); compact: true; enabled: String(root.draft.text || "").length > 0; onClicked: root.commands.copy() }
        NCButton { text: qsTr("Regenerate"); compact: true; enabled: !root.draft.busy; onClicked: root.commands.regenerate() }
        NCButton { text: qsTr("Restore original"); compact: true; onClicked: root.commands.restore() }
        NCButton { text: qsTr("Discard"); compact: true; onClicked: root.commands.discard() }
        NCButton { text: qsTr("Cancel"); compact: true; visible: Boolean(root.draft.busy); onClicked: root.commands.cancel() }
    }
}
