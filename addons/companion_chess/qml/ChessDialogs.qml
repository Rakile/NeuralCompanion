import QtQuick
import QtQuick.Layouts
import "../../../ui/qml/components" as NC
import "../../../ui/qml/theme" as Theme

Item {
    id: root
    required property var workspace
    property bool surfaceActive: true
    property string action: ""
    property string seenPromotion: ""
    readonly property bool dialogOpen: confirmation.visible || promotion.visible || result.visible
    function confirmAction(value) { action = value; promotion.close(); confirmation.open() }
    function openPromotion() { if (surfaceActive && (workspace.state.promotion || []).length) promotion.open() }
    function closeTop() {
        if (confirmation.visible) { confirmation.close(); return true }
        if (promotion.visible) { promotion.close(); return true }
        if (result.visible) { result.reject(); return true }
        return false
    }
    onSurfaceActiveChanged: {
        if (!surfaceActive) { confirmation.close(); promotion.close(); result.close() }
        else { openPromotion(); syncState() }
    }
    function syncState() {
        let choices = root.workspace.state.promotion || []
        let key = JSON.stringify(choices)
        if (!choices.length || root.workspace.gameFinished) { root.seenPromotion = ""; promotion.close() }
        else if (!confirmation.visible && key !== root.seenPromotion) { root.seenPromotion = key; root.openPromotion() }
        if (root.surfaceActive && root.workspace.gameFinished
                && root.workspace.resultKey !== root.workspace.dismissedResultKey) result.open()
        else result.close()
    }
    Component.onCompleted: Qt.callLater(syncState)
    Connections {
        target: root.workspace.controller
        function onStateChanged() {
            Qt.callLater(root.syncState)
        }
    }
    NC.NCDialog {
        id: confirmation
        objectName: "chessConfirmationDialog"
        parent: root
        x: Math.max(0, (root.width - width) / 2); y: Math.max(0, (root.height - height) / 2)
        title: root.action === "end" ? "End this game?" : root.action === "resign" ? "Resign this game?" : root.action === "new" ? "Start a new game?" : "Continue on screen?"
        description: root.action === "end" ? "No winner will be declared. Your current board and moves are kept. Any unfinished physical move will be cancelled." : root.action === "resign" ? "This ends your current game." : root.action === "new" ? "Your current game will be replaced." : "This disconnects the Launchpad and completes an announced pending move digitally. Match the physical board before reconnecting."
        acceptText: root.action === "end" ? "End game" : root.action === "resign" ? "Resign" : root.action === "new" ? "New game" : "Continue on screen"
        acceptTone: root.action === "resign" || root.action === "end" ? "danger" : "primary"
        acceptEnabled: root.workspace.connected && (root.action === "end" || !root.workspace.state.busy)
        onAccepted: root.workspace.command(root.action)
    }
    ChessPromotionDialog {
        id: promotion
        parent: root
        autoOpen: false
        surfaceActive: root.surfaceActive
        choices: root.workspace.state.promotion || []
        canChoose: root.workspace.connected && !root.workspace.state.busy
        onPieceChosen: uci => { if (root.workspace.command("promote", {uci: uci})) promotion.close() }
    }
    NC.NCDialog {
        id: result
        objectName: "chessResultDialog"
        parent: root
        width: Math.min(Math.max(0, root.width - 32), 480)
        x: Math.max(0, (root.width - width) / 2); y: Math.max(0, (root.height - height) / 2)
        title: root.workspace.resultTitle
        description: root.workspace.resultDescription
        acceptText: "New game"
        rejectText: "Close"
        acceptEnabled: root.workspace.canStart
        onAccepted: {
            if (root.workspace.command("new")) root.workspace.dismissedResultKey = root.workspace.resultKey
            else Qt.callLater(root.syncState)
        }
        onRejected: root.workspace.dismissedResultKey = root.workspace.resultKey
    }
}
