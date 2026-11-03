pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Dialog {
    id: departure
    objectName: "creatorDepartureDialog"
    required property var creatorModel
    property int promptId: -1
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(480, parent ? parent.width - 32 : 358)
    modal: true
    padding: Theme.NCMetrics.space16
    visible: Boolean(creatorModel.departurePrompt.visible)
    onOpened: promptId = creatorModel.departurePrompt.id
    onClosed: creatorModel.dismissDeparture(promptId)
    background: Rectangle {
        color: Theme.NCTheme.windowRaised
        border.color: Theme.NCTheme.border
        radius: Theme.NCMetrics.radiusMedium
    }
    contentItem: ColumnLayout {
        spacing: Theme.NCMetrics.space16
        Label {
            Layout.fillWidth: true
            text: qsTr("MuseTalk is still loaded")
            color: Theme.NCTheme.text
            font.bold: true
            font.pixelSize: Theme.NCTypography.bodySize
            wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("MuseTalk is still loaded. Unload it to free GPU memory, or keep it loaded for faster previews when you return?")
            color: Theme.NCTheme.textSecondary
            font.pixelSize: Theme.NCTypography.bodySize
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            NCButton {
                objectName: "unloadMuseTalkButton"
                Layout.fillWidth: true
                text: qsTr("Unload MuseTalk")
                onClicked: departure.creatorModel.answerDeparture(departure.promptId, true)
            }
            NCButton {
                objectName: "keepMuseTalkButton"
                Layout.fillWidth: true
                text: qsTr("Keep loaded")
                onClicked: departure.creatorModel.answerDeparture(departure.promptId, false)
            }
        }
    }
}
