pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    required property var controller
    readonly property var status: controller.state
    visible: Boolean(status.active)
    title: String(status.title || "")
    description: String(status.message || "")
    border.color: Theme.NCTheme.statusColor("warning")

    NCButton {
        objectName: "retrySensoryImages"
        text: qsTr("Retry images now")
        enabled: Boolean(root.status.canRetry)
        onClicked: root.controller.retryImages()
    }
}
