import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    required property var bridge
    readonly property var status: bridge.communicationLogging
    title: qsTr("Communication logging")
    description: qsTr("Local debugging log of visible and hidden messages, full prompts, provider replies and original images. Contains private chat and desktop content. No upload. Off on app launch; independent of Orb settings.")
    RowLayout {
        Layout.fillWidth: true
        NCSwitch {
            objectName: "communicationLoggingSwitch"
            toolTipText: qsTr("Record subsequent visible and hidden messages, full prompts, provider replies and original images to a local debug folder. Logs can contain private chat and desktop content; no upload. Off on app launch. Turning off keeps existing logs; recording stops at 1 GiB with an incomplete status.")
            text: checked ? qsTr("On") : qsTr("Off")
            checked: root.status.state === "recording"
            enabled: root.status.state !== "unavailable" && root.status.state !== "stopping"
            onClicked: root.bridge.setCommunicationLogging(checked)
        }
        Label {
            Layout.fillWidth: true
            text: String(root.status.state || "off") + " · " + Math.round(Number(root.status.byte_count || 0)/1048576) + qsTr(" MiB / 1024 MiB")
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
    }
    Label {
        Layout.fillWidth: true
        text: String(root.status.incomplete_reason || root.status.path || qsTr("Existing logs are kept. Reaching the 1 GiB limit stops recording with an explicit incomplete status."))
        color: root.status.incomplete_reason ? Theme.NCTheme.error : Theme.NCTheme.textSecondary
        wrapMode: Text.WrapAnywhere
    }
    Flow {
        Layout.fillWidth: true
        spacing: 8
        NCButton { text: qsTr("Open transcript"); enabled: Boolean(root.status.path); onClicked: root.bridge.openCommunicationLog("transcript") }
        NCButton { text: qsTr("Open folder"); enabled: Boolean(root.status.path); onClicked: root.bridge.openCommunicationLog("folder") }
        NCButton { text: qsTr("Copy path"); enabled: Boolean(root.status.path); onClicked: root.bridge.openCommunicationLog("copy") }
    }
    Timer { interval: 1000; running: root.visible; repeat: true; onTriggered: root.bridge.refreshCommunicationLogging() }
}
