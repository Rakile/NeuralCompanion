import QtQuick
import QtQuick.Layouts
import "../../../ui/qml/components" as NC
import "../../../ui/qml/theme" as Theme

Rectangle {
    id: root
    required property var workspace
    property bool showPause: false
    implicitHeight: content.implicitHeight + Theme.NCMetrics.space24
    color: Theme.NCTheme.surface
    radius: Theme.NCMetrics.radiusLarge
    border.color: Theme.NCTheme.border
    ColumnLayout {
        id: content
        anchors.fill: parent; anchors.margins: Theme.NCMetrics.space12
        spacing: Theme.NCMetrics.space8
        NC.NCInlineMessage {
            Layout.fillWidth: true
            visible: !!root.workspace.pendingInstruction
            tone: "warning"; title: "Physical move"
            message: root.workspace.pendingInstruction
        }
        RowLayout {
            Layout.fillWidth: true; spacing: Theme.NCMetrics.space12
            Rectangle {
                Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: 18
                color: Theme.NCTheme.surfaceSelected; border.color: Theme.NCTheme.borderStrong
                ChessLabel { anchors.centerIn: parent; text: root.workspace.personaName.slice(0, 1).toUpperCase(); color: Theme.NCTheme.accent; font.pixelSize: Theme.NCTypography.headingSize }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: Theme.NCMetrics.space4
                ChessLabel { Layout.fillWidth: true; text: root.workspace.personaName; color: Theme.NCTheme.text; font.weight: Font.DemiBold; elide: Text.ElideRight; maximumLineCount: 1 }
                ChessLabel {
                    objectName: "chessCommentary"
                    Layout.fillWidth: true; Layout.preferredWidth: 0
                    text: root.workspace.gameFinished ? root.workspace.resultTitle + " · " + root.workspace.resultDescription : root.workspace.state.commentary || (root.workspace.connected ? "Choose your persona and start a game." : "Connect your chess server in Setup to begin.")
                    color: Theme.NCTheme.text; maximumLineCount: 4; elide: Text.ElideRight
                    Accessible.name: text
                }
            }
            NC.NCButton {
                visible: root.showPause; text: root.workspace.game.phase === "paused" ? "Resume" : "Pause"
                enabled: root.workspace.connected && !root.workspace.gameFinished && !!root.workspace.game.phase && (!root.workspace.state.busy || root.workspace.game.phase !== "paused")
                onClicked: root.workspace.command(root.workspace.game.phase === "paused" ? "resume" : "pause")
            }
            NC.NCButton {
                objectName: "chessEndGame"
                text: "End game"; compact: true; tone: "danger"
                enabled: root.workspace.connected && !!root.workspace.game.phase && !root.workspace.gameFinished
                onClicked: root.workspace.confirmAction("end")
            }
        }
        ChessLabel {
            Layout.fillWidth: true; visible: root.workspace.state.fallback || false
            color: Theme.NCTheme.warning; text: "Engine fallback: the persona did not return a valid choice."
        }
        Flow {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space8
            visible: (root.workspace.state.promotion || []).length > 0 || root.workspace.game.phase === "paused" || root.workspace.game.phase === "awaiting_persona" || !root.workspace.connected
            NC.NCButton { text: "Choose promotion"; visible: (root.workspace.state.promotion || []).length > 0; onClicked: root.workspace.openPromotion() }
            NC.NCButton { text: "Refresh"; visible: !root.workspace.connected || root.workspace.game.phase === "paused"; enabled: !root.workspace.state.busy; onClicked: root.workspace.command("refresh") }
            NC.NCButton { text: "Retry persona"; visible: root.workspace.game.phase === "awaiting_persona"; enabled: root.workspace.connected && !root.workspace.state.busy; onClicked: root.workspace.command("retry_persona") }
            NC.NCButton { text: "Physical board matches"; visible: root.workspace.hardware.connected === true && root.workspace.game.reconciled === false; enabled: root.workspace.connected && !root.workspace.state.busy; onClicked: root.workspace.command("reconcile") }
            NC.NCButton { text: "Continue on screen"; visible: root.workspace.game.reconciled === false; enabled: root.workspace.connected && !root.workspace.state.busy; onClicked: root.workspace.confirmAction("continue_desktop") }
        }
    }
}
