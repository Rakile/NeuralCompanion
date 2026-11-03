pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCDialog {
    id: root
    objectName: "desktopRestartConfirmation"
    parent: Overlay.overlay
    width: Math.min(440, parent ? parent.width - 40 : 440)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    title: qsTr("Restart NeuralCompanion")
    description: qsTr("You are about to restart NeuralCompanion.")
    acceptText: qsTr("Restart (Enter)")
    rejectText: qsTr("Cancel (Esc)")
    closePolicy: Popup.NoAutoClose

    property int remainingSeconds: 5
    property bool decisionMade: false

    onAboutToShow: {
        remainingSeconds = 5
        decisionMade = false
    }
    onAccepted: decisionMade = true
    onRejected: decisionMade = true
    onClosed: decisionMade = true

    contentItem: ColumnLayout {
        spacing: Theme.NCMetrics.space12
        Image {
            objectName: "restartNcLogo"
            source: "../../../ui_icons/branding/NC_logo.png"
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 96
            Layout.preferredHeight: 96
            fillMode: Image.PreserveAspectFit
            mipmap: true
        }
        Label {
            objectName: "restartCountdownLabel"
            text: qsTr("Restarting in %1 seconds.").arg(root.remainingSeconds)
            color: Theme.NCTheme.text
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }
        Label {
            text: qsTr("Press Enter to restart now or Esc to cancel.")
            color: Theme.NCTheme.textSecondary
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }
    }
    Timer {
        interval: 5000
        running: root.opened && !root.decisionMade
        repeat: false
        onTriggered: {
            if (root.opened && !root.decisionMade)
                root.accept()
        }
    }
    Timer {
        interval: 1000
        running: root.opened && !root.decisionMade
        repeat: true
        onTriggered: root.remainingSeconds = Math.max(1, root.remainingSeconds - 1)
    }
    Shortcut {
        sequences: ["Return", "Enter"]
        context: Qt.WindowShortcut
        enabled: root.opened && !root.decisionMade
        autoRepeat: false
        onActivated: root.accept()
    }
    Shortcut {
        sequence: "Esc"
        context: Qt.WindowShortcut
        enabled: root.opened && !root.decisionMade
        autoRepeat: false
        onActivated: root.reject()
    }
}
