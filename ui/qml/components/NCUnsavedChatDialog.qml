pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../theme" as Theme

Item {
    id: root
    required property var guard
    property var dialogWindow: root.Window.window
    readonly property bool dialogActive: warning.visible || saveFile.visible
    readonly property var state: guard.state
    onStateChanged: { if (state.active) warning.open(); else warning.close() }
    Connections {
        target: root.guard
        function onSavePathRequested() { saveFile.open() }
    }
    NCDialog {
        id: warning
        objectName: "unsavedChatDialog"
        parent: root.dialogWindow ? root.dialogWindow.Overlay.overlay : null
        anchors.centerIn: parent
        width: Math.min(560, parent ? parent.width - 32 : 560)
        title: root.state.saveOnly ? qsTr("Save conversation") : qsTr("Unsaved chat context")
        modal: true
        closePolicy: Popup.NoAutoClose
        footer: null
        ColumnLayout {
            width: parent.width
            Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: root.state.saveOnly
                      ? qsTr("Save the current conversation before %1.").arg(root.state.action || "")
                      : qsTr("This conversation has unsaved changes. Save them before %1?").arg(root.state.action || "")
                color: Theme.NCTheme.text
            }
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: qsTr("A memory summary or archived chunks do not replace a saved conversation.")
                color: Theme.NCTheme.textSecondary
            }
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                visible: Boolean(root.state.error) || Boolean(root.state.busy)
                text: root.state.error || qsTr("Saving conversation…")
                color: root.state.error ? Theme.NCTheme.error : Theme.NCTheme.textSecondary
            }
            Flow {
                Layout.fillWidth: true; spacing: 8; enabled: !root.state.busy
                NCButton { objectName: "unsavedChatSave"; text: qsTr("Save"); tone: "primary"; onClicked: root.state.path ? root.guard.saveTo(root.state.path) : saveFile.open() }
                NCButton { objectName: "unsavedChatDiscard"; visible: !Boolean(root.state.saveOnly); text: qsTr("Don't Save"); tone: "danger"; onClicked: root.guard.decide("discard") }
                NCButton { objectName: "unsavedChatCancel"; text: qsTr("Cancel"); onClicked: root.guard.decide("cancel") }
            }
        }
    }
    FileDialog {
        id: saveFile
        objectName: "unsavedChatSaveFile"
        parentWindow: root.dialogWindow
        title: qsTr("Save Chat Context As")
        fileMode: FileDialog.SaveFile
        nameFilters: ["Chat context (*.json)"]
        defaultSuffix: "json"
        onAccepted: root.guard.saveTo(String(selectedFile))
        onRejected: {
            if (root.state.saveOnly)
                root.guard.decide("cancel")
        }
    }
}
