pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Item {
    id: root
    property var session: null
    property var dialogWindow: root.Window.window
    readonly property bool dialogActive: warning.visible
    readonly property var confirmation: session ? session.confirmation : ({})
    function syncDialog() {
        if (confirmation.active) warning.open()
        else warning.close()
    }
    onConfirmationChanged: syncDialog()
    Component.onCompleted: syncDialog()
    NCDialog {
        id: warning
        objectName: "localRoomSwitchDialog"
        parent: root.dialogWindow ? root.dialogWindow.Overlay.overlay : null
        anchors.centerIn: parent
        width: Math.min(540, parent ? parent.width - 32 : 540)
        title: qsTr("Switch to Local room?")
        modal: true
        closePolicy: Popup.NoAutoClose
        footer: null
        ColumnLayout {
            width: parent.width; spacing: 12
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: qsTr("The normal chat engine will stop and switch to the Local room. Main chat and the Local room keep separate conversations. You will be asked to save unsaved main-chat changes before the room starts. Saved main chats can be loaded again later.")
                color: Theme.NCTheme.text
            }
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                visible: Boolean(root.confirmation.error)
                text: String(root.confirmation.error || ""); textFormat: Text.PlainText
                color: Theme.NCTheme.error
            }
            RowLayout {
                NCButton {
                    objectName: "localRoomSwitchAccept"; text: qsTr("Switch"); tone: "primary"
                    onClicked: root.session.decideSwitch(true)
                }
                NCButton {
                    objectName: "localRoomSwitchCancel"; text: qsTr("Cancel")
                    onClicked: root.session.decideSwitch(false)
                }
            }
        }
    }
}
