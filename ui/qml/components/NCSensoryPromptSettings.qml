pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    required property var controller
    property bool showContext: false
    property bool showSource: true
    property bool showGeneralFields: true
    property bool showContextFields: true
    property bool showSourceFields: true
    // Opt-in grouping for small sensory providers; existing callers keep all fields.
    property string sourceFieldGroup: "all"
    property bool showSourceToggle: true
    property bool showPreview: true
    readonly property var filteredSourceFields: (root.controller.sourceFields || []).filter(field => {
        const name = String(field.key || "").split("/").pop()
        const technical = ["ping_payload", "pong_influences", "tag_subscriptions"].indexOf(name) >= 0
        return root.sourceFieldGroup === "all"
                || (root.sourceFieldGroup === "advanced" ? technical : !technical)
    })
    property string restoreKey: ""
    spacing: Theme.NCMetrics.space12

    component PromptCard: NCCard {
        id: card
        required property var field
        // Unrelated map notifications must not overwrite a draft in this editor.
        readonly property string savedText: String(root.controller.values[String(field.key)] || "")
        Layout.fillWidth: true
        title: String(field.label)
        description: String(field.description || "")
        headerAccessory: NCButton {
            text: qsTr("Restore recommended")
            compact: true
            tone: "quiet"
            onClicked: {
                root.restoreKey = String(card.field.key)
                restoreDialog.open()
            }
        }
        NCScrollableTextArea {
            toolTipText: String(card.field.description || card.field.help || "")

            id: editor
            objectName: "sensoryPromptEditor_" + String(card.field.key)
            Layout.fillWidth: true
            Layout.preferredHeight: Number(card.field.height || 180)
            label: String(card.field.label)
            text: card.savedText
            onEditingFinished: root.controller.setField(String(card.field.key), text)
        }
    }

    Repeater {
        model: root.showGeneralFields ? root.controller.generalFields : []
        delegate: PromptCard {
            required property var modelData
            field: modelData
        }
    }

    NCSwitch {
        toolTipText: qsTr("Show the hidden-context templates used around sensory information. This expands the editing section without enabling any sensor or sending a model request.")

        Layout.fillWidth: true
        visible: root.showContextFields
        text: qsTr("Show general hidden-context templates")
        checked: root.showContext
        onClicked: root.showContext = checked
    }
    Repeater {
        model: root.showContextFields ? root.controller.contextFields : []
        delegate: PromptCard {
            required property var modelData
            field: modelData
            visible: root.showContext
        }
    }

    NCSwitch {
        toolTipText: qsTr("Show prompt details for the selected sensory source. Expanding the section does not start capture or change its enabled state.")

        Layout.fillWidth: true
        visible: root.showSourceToggle && root.showSourceFields && root.filteredSourceFields.length > 0
        text: qsTr("Show source prompt details · %1").arg(root.controller.sourceLabel)
        checked: root.showSource
        onClicked: root.showSource = checked
    }
    Repeater {
        model: root.showSourceFields ? root.filteredSourceFields : []
        delegate: PromptCard {
            required property var modelData
            field: modelData
            visible: root.showSource
        }
    }

    NCInlineMessage {
        Layout.fillWidth: true
        visible: root.controller.error.length > 0
        tone: "error"
        title: qsTr("Prompt not saved")
        message: root.controller.error
    }

    NCCard {
        Layout.fillWidth: true
        visible: root.showPreview
        title: qsTr("Combined hidden review prompt preview")
        description: root.controller.previewNotice
        headerAccessory: NCButton {
            text: qsTr("Refresh preview")
            compact: true
            onClicked: root.controller.refreshPreview()
        }
        NCScrollableTextArea {
            toolTipText: qsTr("Read the assembled hidden-review prompt from the saved templates. This is a preview and does not send a request to the model.")

            objectName: "sensoryCombinedPromptPreview"
            Layout.fillWidth: true
            Layout.preferredHeight: 340
            readOnly: true
            label: qsTr("Combined hidden review prompt preview")
            text: root.controller.preview
        }
    }

    NCDialog {
        id: restoreDialog
        anchors.centerIn: Overlay.overlay
        title: qsTr("Restore this prompt field?")
        description: qsTr("Only this field will return to its recommended value. Other custom prompts remain unchanged.")
        acceptText: qsTr("Restore")
        onAccepted: root.controller.restoreField(root.restoreKey)
    }
}
