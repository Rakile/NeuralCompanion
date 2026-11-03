import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../../../ui/qml/components" as NC
import "../../../ui/qml/theme" as Theme

Rectangle {
    id: root
    objectName: "companionChessOnlineWorkspace"
    required property var workspace
    readonly property var session: workspace.state.online || ({})
    readonly property var game: session.game || ({})
    readonly property var hardware: session.hardware || ({})
    property int page: 0
    property bool sceneSettings: false
    property bool fullscreen: false
    property var pendingAction: ({})
    signal returnLocal()
    color: Theme.NCTheme.window
    function send(action, fields) { return workspace.command("online_" + action, fields || {}) }
    function confirm(action, fields, text) {
        pendingAction = {action: action, fields: Object.assign({}, fields || {}, {confirm: true})}
        confirmLabel.text = text; confirmation.open()
    }
    Component.onDestruction: fullscreen = false
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 16; spacing: 12
        RowLayout {
            Layout.fillWidth: true
            NC.NCButton {
                text: "Local"; compact: true; enabled: !root.hardware.connected
                onClicked: root.game.status === "active"
                    ? root.confirm("return_local", {}, "Return to the saved local game? The untimed online match will remain active and your opponent may be waiting.")
                    : root.returnLocal()
            }
            NC.NCButton { text: "Online"; compact: true; tone: "primary" }
            NC.NCButton { visible: root.hardware.connected === true; text: "Release MIDI"; compact: true; onClicked: root.send("disconnect_hardware") }
            ChessLabel { visible: root.width > 820; Layout.fillWidth: true; text: "Local game preserved" }
            NC.NCButton { text: "Scene"; compact: true; onClicked: root.sceneSettings = !root.sceneSettings }
            NC.NCButton { text: "2D"; compact: true; onClicked: workspace.setting("view", "2d") }
            NC.NCButton { text: "3D"; compact: true; onClicked: workspace.setting("view", "3d") }
            NC.NCButton { text: root.width < 600 ? "Full" : "Fullscreen"; compact: true; onClicked: root.fullscreen = true }
        }
        GridLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            columns: root.width < 820 ? 1 : 2; columnSpacing: 16
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 280
                Layout.preferredHeight: root.width < 820 ? 340 : 600
                color: Theme.NCTheme.surface; border.color: Theme.NCTheme.border; radius: 12
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 12
                    ChessLabel {
                        Layout.fillWidth: true
                        text: !root.game.id ? "Online lobby · no match started" : root.game.status === "ended"
                            ? "Game finished · " + root.game.result : root.game.turn === root.game.your_side ? "Your turn" : "Opponent’s turn"
                        color: Theme.NCTheme.accent
                    }
                    Loader {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        active: !root.fullscreen
                        sourceComponent: workspace.prefs.view === "3d" ? online3d : online2d
                        enabled: root.session.connected && !root.session.busy && root.game.status === "active"
                    }
                    ChessLabel { Layout.fillWidth: true; text: root.game.id ? "You · " + root.game.your_side : "Choose a player or share a private invitation." }
                }
            }
            ScrollView {
                id: onlineInspector
                Layout.fillWidth: root.width < 820; Layout.fillHeight: true
                Layout.preferredWidth: 370; Layout.minimumWidth: 280
                Layout.preferredHeight: root.width < 820 ? 520 : 600
                contentWidth: availableWidth; clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ColumnLayout {
                    width: onlineInspector.availableWidth
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        Repeater {
                            model: ["Find players", "Private invite", "My match"]
                            NC.NCTabButton {
                                required property int index
                                required property string modelData
                                Layout.fillWidth: true; Layout.minimumWidth: 0
                                text: modelData; checked: root.page === index
                                onClicked: { root.page = index; root.sceneSettings = false }
                            }
                        }
                    }
                    Rectangle {
                        objectName: "chessRelayConnectionRequired"
                        visible: root.session.connection_required === true
                        Layout.fillWidth: true; implicitHeight: connectionHelp.implicitHeight + 24
                        color: Theme.NCTheme.surface; border.color: Theme.NCTheme.accent; radius: 8
                        ColumnLayout {
                            id: connectionHelp
                            anchors.fill: parent; anchors.margins: 12
                            ChessLabel { text: "Connect NC Relay"; font.weight: Font.DemiBold }
                            ChessLabel { Layout.fillWidth: true; text: "Open Main Chat Remote → Internet, sign in and connect. Return here and press Refresh. A running LAN phone backend alone does not connect Internet chess." }
                            NC.NCButton { text: "Refresh connection"; enabled: !root.session.busy; onClicked: root.send("refresh") }
                        }
                    }
                    ChessSceneControls { visible: root.sceneSettings; Layout.fillWidth: true; workspace: root.workspace }
                    ColumnLayout {
                        visible: root.page === 0 && !root.sceneSettings; Layout.fillWidth: true
                        ChessLabel { text: "Your availability"; font.weight: Font.DemiBold }
                        NC.NCSwitch {
                            objectName: "chessLookingToPlay"
                            text: "Looking to play"; checked: root.session.available === true
                            enabled: root.session.connected && !root.session.busy && root.game.status !== "active"
                            onToggled: root.send("availability", {enabled: checked, side: sidePreference.currentValue || "either"})
                        }
                        NC.NCComboBox {
                            id: sidePreference; Layout.fillWidth: true
                            model: [{name:"Either side",key:"either"},{name:"White",key:"white"},{name:"Black",key:"black"}]
                            textRole: "name"; valueRole: "key"; label: "Preferred side"
                            enabled: !root.session.available
                        }
                        ChessLabel { Layout.fillWidth: true; text: "Only your NC username is listed. You can browse without listing yourself." }
                        NC.NCTextField {
                            Layout.fillWidth: true; placeholderText: "Search players…"
                            onAccepted: root.send("search", {text: text})
                        }
                        ChessLabel { text: "Players looking to play"; font.weight: Font.DemiBold }
                        Repeater {
                            model: root.session.players || []
                            Rectangle {
                                required property var modelData
                                Layout.fillWidth: true; implicitHeight: 76
                                color: Theme.NCTheme.surface; radius: 8; border.color: Theme.NCTheme.border
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 10
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        ChessLabel { Layout.fillWidth: true; text: modelData.name; color: Theme.NCTheme.text; elide: Text.ElideRight; maximumLineCount: 1 }
                                        ChessLabel { text: "Ready · " + modelData.side; color: Theme.NCTheme.success }
                                    }
                                    NC.NCButton {
                                        text: "Challenge"; compact: true; enabled: !root.session.busy && root.session.available
                                        onClicked: root.confirm("challenge", {player_id: modelData.player_id},
                                            "Save and pause your local game, then challenge " + modelData.name + "? Your local game will remain available.")
                                    }
                                }
                            }
                        }
                        RowLayout {
                            visible: (root.session.offset || 0) > 0 || root.session.next_offset !== null && root.session.next_offset !== undefined
                            NC.NCButton { text: "Previous"; enabled: (root.session.offset || 0) > 0; onClicked: root.send("page", {offset: Math.max(0,root.session.offset-50)}) }
                            NC.NCButton { text: "Next"; enabled: root.session.next_offset !== null && root.session.next_offset !== undefined; onClicked: root.send("page", {offset: root.session.next_offset}) }
                        }
                        ChessLabel {
                            visible: !(root.session.players || []).length; Layout.fillWidth: true
                            text: root.session.connected ? "No players are looking right now. You can make yourself available or share a private invitation." : "Connect NC Relay through Main Chat Remote → Internet, then press Refresh."
                        }
                    }
                    ColumnLayout {
                        visible: root.page === 1 && !root.sceneSettings; Layout.fillWidth: true
                        ChessLabel { text: "Private invitation"; font.weight: Font.DemiBold }
                        NC.NCButton {
                            Layout.fillWidth: true; text: "Create invitation"; enabled: root.session.connected && !root.session.busy && root.game.status !== "active"
                            onClicked: root.confirm("invite", {side: sidePreference.currentValue || "either"}, "Save and pause the local game and create a private online invitation?")
                        }
                        NC.NCTextField { Layout.fillWidth: true; text: root.session.invite || ""; readOnly: true; placeholderText: "Your invitation code"; selectByMouse: true }
                        NC.NCTextField { id: inviteCode; Layout.fillWidth: true; placeholderText: "Enter invitation code"; maximumLength: 32 }
                        NC.NCButton {
                            Layout.fillWidth: true; text: "Join game"; enabled: root.session.connected && !root.session.busy && inviteCode.text.length > 0
                            onClicked: root.confirm("join", {code: inviteCode.text}, "Save and pause the local game and join this online match?")
                        }
                    }
                    ColumnLayout {
                        visible: root.page === 2 && !root.sceneSettings; Layout.fillWidth: true
                        ChessLabel { text: "Online match"; font.weight: Font.DemiBold }
                        Repeater {
                            model: root.game.players || []
                            ChessLabel { required property var modelData; text: modelData.name + " · " + modelData.side }
                        }
                        ChessLabel { Layout.fillWidth: true; text: (root.game.moves || []).join("  "); maximumLineCount: 6; elide: Text.ElideRight }
                        NC.NCButton {
                            Layout.fillWidth: true; text: "Offer draw"; enabled: root.session.connected && !root.session.busy && root.game.status === "active"
                            onClicked: root.send("draw", {action: "offer"})
                        }
                        RowLayout {
                            visible: !!root.game.draw_offer && root.game.draw_offer !== root.game.your_side
                            NC.NCButton { text: "Accept draw"; onClicked: root.confirm("draw", {action: "accept"}, "Accept the draw and end this online game?") }
                            NC.NCButton { text: "Decline"; onClicked: root.send("draw", {action: "decline"}) }
                        }
                        NC.NCButton {
                            Layout.fillWidth: true; text: "Resign"; tone: "danger"; enabled: root.session.connected && !root.session.busy && root.game.status === "active"
                            onClicked: root.confirm("resign", {}, "Resign this online game? The local game is unaffected.")
                        }
                        ChessLabel { text: "Launchpad — optional"; font.weight: Font.DemiBold }
                        ChessLabel { Layout.fillWidth: true; text: "You can play entirely with the mouse on either board." }
                        NC.NCButton { text: "Activate MIDI"; visible: !root.hardware.activated; onClicked: root.send("activate_hardware") }
                        ColumnLayout {
                            visible: root.hardware.activated && !root.hardware.connected; Layout.fillWidth: true
                            NC.NCComboBox {
                                id: hardwareModel; objectName: "chessOnlineHardwareModel"
                                Layout.fillWidth: true; label: "Launchpad model"
                                model: workspace.hardwareModels; textRole: "label"; valueRole: "id"
                            }
                            ChessLabel {
                                Layout.fillWidth: true
                                text: hardwareModel.currentIndex >= 0 ? workspace.hardwareModels[hardwareModel.currentIndex].description : "Choose your Launchpad model."
                            }
                            NC.NCComboBox { id: inputPort; objectName: "chessOnlineHardwareInput"; Layout.fillWidth: true; model: root.hardware.inputs || []; label: "MIDI input"; currentIndex: -1 }
                            NC.NCComboBox { id: outputPort; objectName: "chessOnlineHardwareOutput"; Layout.fillWidth: true; model: root.hardware.outputs || []; label: "MIDI output"; currentIndex: -1 }
                            NC.NCButton {
                                objectName: "chessOnlineConnectHardware"
                                text: "Connect Launchpad"; enabled: !!root.game.id && inputPort.currentIndex >= 0 && outputPort.currentIndex >= 0
                                onClicked: root.send("connect_hardware", {input: inputPort.currentText, output: outputPort.currentText,
                                    model: hardwareModel.currentValue})
                            }
                        }
                        NC.NCButton { visible: root.hardware.connected === true; text: "Physical board matches"; onClicked: root.send("reconcile") }
                        NC.NCButton { visible: root.hardware.connected === true; text: "Disconnect Launchpad"; onClicked: root.send("disconnect_hardware") }
                        ChessLabel { visible: root.hardware.connected === true; Layout.fillWidth: true; text: "Disconnect this Launchpad before returning to Local. Confirm the physical position after each online move." }
                    }
                    Repeater {
                        model: root.session.challenges || []
                        ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            ChessLabel { Layout.fillWidth: true; text: modelData.incoming ? "Challenge from " + modelData.name : "Waiting for " + modelData.name }
                            RowLayout {
                                visible: modelData.incoming
                                NC.NCButton { text: "Accept"; onClicked: root.confirm("accept", {challenge_id: modelData.id}, "Save and pause your local game, then accept " + modelData.name + "’s challenge?") }
                                NC.NCButton { text: "Decline"; onClicked: root.send("decline", {challenge_id: modelData.id}) }
                            }
                            NC.NCButton { visible: !modelData.incoming; text: "Cancel challenge"; onClicked: root.send("cancel", {challenge_id: modelData.id}) }
                        }
                    }
                    ColumnLayout {
                        visible: !root.sceneSettings; Layout.fillWidth: true
                        ChessLabel { text: "Your local commentator"; font.weight: Font.DemiBold }
                        NC.NCComboBox {
                            Layout.fillWidth: true; label: "Your saved persona"
                            model: workspace.state.personas || []; textRole: "name"; valueRole: "id"
                            currentIndex: { for (let i=0; i<count; ++i) if (valueAt(i) === workspace.prefs.persona_id) return i; return -1 }
                            onActivated: workspace.setting("persona_id", currentValue)
                        }
                        NC.NCSwitch { text: "Commentary"; checked: root.session.commentator !== false; onToggled: root.send("settings", {commentator: checked}) }
                        NC.NCSwitch { text: "Voice"; checked: root.session.voice !== false; onToggled: root.send("settings", {voice: checked}) }
                        ChessLabel { Layout.fillWidth: true; text: root.session.commentary || "Only you hear your companion. It comments on confirmed moves and cannot play for either side." }
                    }
                    NC.NCButton {
                        text: "Choose promotion"; visible: (root.session.promotion || []).length > 0
                        onClicked: promotion.open()
                    }
                    NC.NCButton { text: "Refresh / synchronize"; enabled: !root.session.busy; onClicked: root.send("refresh") }
                }
            }
        }
        ChessLabel { Layout.fillWidth: true; text: root.session.error || root.session.status || "Connect NC Relay to play online."; color: root.session.error ? Theme.NCTheme.warning : Theme.NCTheme.textSecondary; maximumLineCount: 3 }
    }
    Component {
        id: online2d
        Board2D {
            pieces: root.game.pieces || []; orientation: root.game.your_side || "white"
            selected: root.session.selected || ""; targets: root.session.targets || []
            onSquareClicked: square => root.send("square", {square: square})
        }
    }
    Component {
        id: online3d
        Board3D {
            gameState: root.game
            dropWaiting: root.session.busy === true || (root.session.promotion || []).length > 0 || !!root.game.pending
            selected: root.session.selected || ""; targets: root.session.targets || []
            boardModel: workspace.boardModel; styleName: workspace.styleName; lighting: workspace.light; lowDetail: workspace.lowDetail
            yaw: workspace.cameraYaw + (root.game.your_side === "black" ? 180 : 0); pitch: workspace.cameraPitch; distance: workspace.cameraDistance
            fieldOfView: workspace.cameraFov
            onOrbitRequested: (yaw, pitch) => {
                const relativeYaw = yaw - (root.game.your_side === "black" ? 180 : 0)
                workspace.cameraYaw = ((relativeYaw + 180) % 360 + 360) % 360 - 180
                workspace.cameraPitch = pitch
            }
            onDistanceRequested: distance => workspace.cameraDistance = distance
            onFieldOfViewRequested: fieldOfView => workspace.cameraFov = fieldOfView
            onSquareClicked: square => root.send("square", {square: square})
            onMoveDropped: (source,destination,gameId,revision) => { if (!root.send("drop", {source:source,destination:destination,game_id:gameId,revision:revision})) dropPreview = null }
        }
    }
    ChessPromotionDialog {
        id: promotion
        parent: root
        surfaceActive: root.visible && !root.fullscreen
        choices: root.session.promotion || []
        canChoose: root.session.connected === true && !root.session.busy
        onPieceChosen: uci => { if (root.send("promote", {uci: uci})) promotion.close() }
    }
    Dialog {
        id: confirmation; parent: Overlay.overlay; anchors.centerIn: parent
        title: "Online chess"; modal: true; standardButtons: Dialog.Ok | Dialog.Cancel
        width: Math.min(root.width-32,440)
        contentItem: ChessLabel { id: confirmLabel; width: parent.width; wrapMode: Text.WordWrap }
        onAccepted: root.pendingAction.action === "return_local" ? root.returnLocal() : root.send(root.pendingAction.action,root.pendingAction.fields)
    }
    Window {
        id: onlineFullscreen
        objectName: "chessOnlineFullscreenWindow"
        visibility: root.fullscreen ? Window.FullScreen : Window.Hidden
        title: "Companion Chess — Online"; color: "black"
        onClosing: root.fullscreen = false
        Loader { anchors.fill: parent; active: root.fullscreen; sourceComponent: online3d; enabled: root.session.connected && !root.session.busy && root.game.status === "active" }
        NC.NCButton { anchors.top: parent.top; anchors.right: parent.right; anchors.margins: 16; text: "Close fullscreen"; onClicked: root.fullscreen = false }
        NC.NCButton {
            anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter; anchors.margins: 16
            text: "Choose promotion"; visible: (root.session.promotion || []).length > 0
            onClicked: fullscreenPromotion.open()
        }
        ChessPromotionDialog {
            id: fullscreenPromotion
            parent: onlineFullscreen.contentItem
            surfaceActive: root.visible && root.fullscreen
            choices: root.session.promotion || []
            canChoose: root.session.connected === true && !root.session.busy
            onPieceChosen: uci => { if (root.send("promote", {uci: uci})) fullscreenPromotion.close() }
        }
    }
}
