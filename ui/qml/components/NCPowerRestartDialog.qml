pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCDialog {
    id: root
    objectName: "powerRestartDialog"
    parent: Overlay.overlay
    width: Math.min(480, parent ? parent.width - 40 : 480)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    title: qsTr("Restart NeuralCompanion")
    description: qsTr("Choose whether to save the current conversation. You can cancel the five-second restart countdown.")
    footer: null
    closePolicy: Popup.CloseOnEscape
    signal restartRequested(bool saveConversation)

    function choose(saveConversation) {
        close()
        restartRequested(saveConversation)
    }

    contentItem: ColumnLayout {
        spacing: Theme.NCMetrics.space12
        Image {
            source: "../../../ui_icons/branding/NC_logo.png"
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 96
            Layout.preferredHeight: 96
            fillMode: Image.PreserveAspectFit
            mipmap: true
        }
        NCButton {
            objectName: "powerRestartSave"
            Layout.fillWidth: true
            text: qsTr("Save and restart NC")
            tone: "primary"
            onClicked: root.choose(true)
        }
        NCButton {
            objectName: "powerRestartDiscard"
            Layout.fillWidth: true
            text: qsTr("Do not save and restart NC")
            onClicked: root.choose(false)
        }
        NCButton {
            objectName: "powerRestartCancel"
            Layout.fillWidth: true
            text: qsTr("Cancel")
            onClicked: root.reject()
        }
    }
}
