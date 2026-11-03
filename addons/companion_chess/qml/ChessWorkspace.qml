import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components" as NC
import "../../../ui/qml/theme" as Theme

Rectangle {
    id: root
    objectName: "companionChessWorkspace"
    required property var controller
    readonly property var state: controller ? controller.state : ({})
    readonly property var prefs: Object.assign({}, state.preferences || {}, inFlightSettings, queuedSettings)
    property var queuedSettings: ({})
    property var inFlightSettings: ({})
    property bool settingsBusyObserved: false
    property double settingsSentAt: 0
    readonly property bool settingsPending: Object.keys(queuedSettings).length > 0 || Object.keys(inFlightSettings).length > 0
    readonly property var game: state.game || ({})
    readonly property var hardware: state.hardware || ({})
    readonly property var hardwareModels: controller && controller.hardwareModels || []
    readonly property bool connected: (state.connection || {}).connected === true
    readonly property string connectionMessage: (state.connection || {}).message || "Choose a chess connection in Setup."
    readonly property string styleName: prefs.style || "classic"
    readonly property string boardModel: prefs.board_model || "style"
    readonly property var light: (prefs.lighting || ({}))[styleName] || ({preset:"spotlight",brightness:1.4,warmth:.55,azimuth:25,elevation:68,fill:0,shadows:true})
    readonly property string pendingSquare: game.pending && game.pending.steps[game.pending.step] ? game.pending.steps[game.pending.step].square : ""
    readonly property string pendingInstruction: game.hardware && game.pending && game.pending.steps[game.pending.step] ? game.pending.steps[game.pending.step].instruction : ""
    readonly property string personaName: {
        for (let p of state.personas || []) if (p.id === prefs.persona_id) return p.name || "Persona"
        return "Your companion"
    }
    readonly property bool gameFinished: game.phase === "game_over" || (!!game.result && game.result !== "*")
    readonly property string resultReason: ({checkmate:"Checkmate",stalemate:"Stalemate",
        insufficient_material:"Insufficient material",seventyfive_moves:"75-move rule",
        fivefold_repetition:"Fivefold repetition",fifty_moves:"50-move rule",
        threefold_repetition:"Threefold repetition",resignation:"Resignation",ended:"Game ended"})[game.termination]
        || (gameFinished && game.check ? "Checkmate" : "Game over")
    readonly property string resultTitle: {
        if (game.termination === "ended" || game.result === "*") return "Game ended"
        if (game.result === "1/2-1/2") return "Draw"
        const winner = game.result === "1-0" ? "white" : "black"
        let opponent = "Your companion"
        const personaId = game.persona_id || prefs.persona_id
        for (let persona of state.personas || []) {
            if (persona.id === personaId) { opponent = persona.name || "Your companion"; break }
        }
        return winner === (game.human || prefs.human) ? "You win!" : opponent + " wins!"
    }
    readonly property string resultDescription: game.termination === "ended" || game.result === "*"
        ? "No winner was declared. Your final board and moves are kept."
        : resultReason + " · " + (game.result || "")
    readonly property string resultKey: gameFinished ? [game.game_id, game.result, game.termination || resultReason, game.ply || 0].join(":") : ""
    property string dismissedResultKey: ""
    readonly property string phaseLabel: !connected ? "Not connected" : gameFinished ? resultReason : game.phase ? game.phase.replace(/_/g, " ") : "Ready"
    readonly property bool canStart: connected && !!prefs.persona_id && !state.busy && !game.pending && !settingsPending
    property bool fullScreen3d: false
    property bool lowDetail: false
    property real cameraYaw: 0
    property real cameraPitch: 53
    property real cameraDistance: 1350
    property real cameraFov: 48
    readonly property bool narrow: width < 780
    property int inspectorTab: 0
    property bool onlineMode: Boolean(controller && controller.onlineMode)
    property bool viewReady: false
    onOnlineModeChanged: {
        fullScreen3d = false
        if (controller && controller.onlineMode !== undefined) controller.onlineMode = onlineMode
        if (viewReady) updateOnlineForeground()
    }
    color: Theme.NCTheme.window

    function command(action, fields) { return controller ? controller.command(action, fields || {}) : false }
    function updateOnlineForeground() {
        command("online_settings", {foreground: onlineMode && visible})
        if (onlineMode && visible) command("online_open")
    }
    function setting(key, value) { let fields = Object.assign({}, queuedSettings); fields[key] = value; queuedSettings = fields }
    Connections {
        target: root.controller
        function onStateChanged() {
            if (!Object.keys(root.inFlightSettings).length) return
            if (root.state.busy) root.settingsBusyObserved = true
            let actual = root.state.preferences || {}
            let matched = Object.keys(root.inFlightSettings).every(key => JSON.stringify(actual[key]) === JSON.stringify(root.inFlightSettings[key]))
            if (matched || (root.settingsBusyObserved && !root.state.busy)) {
                root.inFlightSettings = ({})
                root.settingsBusyObserved = false
            }
        }
    }
    Timer {
        interval: 100; repeat: true; running: root.settingsPending
        onTriggered: {
            if (Object.keys(root.inFlightSettings).length && !root.state.busy && Date.now() - root.settingsSentAt > 5000) {
                root.inFlightSettings = ({})
                root.settingsBusyObserved = false
            }
            if (root.state.busy || Object.keys(root.inFlightSettings).length || !Object.keys(root.queuedSettings).length) return
            let fields = root.queuedSettings
            root.inFlightSettings = fields
            root.queuedSettings = ({})
            root.settingsBusyObserved = false
            root.settingsSentAt = Date.now()
            if (!root.command("settings", fields)) {
                root.queuedSettings = Object.assign({}, fields, root.queuedSettings)
                root.inFlightSettings = ({})
            }
        }
    }
    function changeLight(key, value) {
        let lights = JSON.parse(JSON.stringify(prefs.lighting || {}))
        lights[styleName] = Object.assign({}, light)
        lights[styleName][key] = value
        if (key === "preset") {
            lights[styleName].fill = value === "spotlight" ? 0 : value === "studio" ? .65 : .25
            lights[styleName].warmth = value === "study" ? .85 : value === "moon" ? 0 : .55
        }
        setting("lighting", lights)
    }
    function confirmAction(action) {
        if (fullScreen3d) full.confirmAction(action)
        else dialogs.confirmAction(action)
    }
    function openPromotion() {
        if (fullScreen3d) full.openPromotion()
        else dialogs.openPromotion()
    }
    function showSetup() { inspectorTab = 3 }
    Component.onCompleted: {
        viewReady = true
        command("open")
        if (onlineMode) updateOnlineForeground()
    }
    Component.onDestruction: if (onlineMode) command("online_settings", {foreground: false})
    onVisibleChanged: {
        if (!visible) fullScreen3d = false
        if (viewReady && onlineMode) updateOnlineForeground()
    }

    ColumnLayout {
        visible: !root.onlineMode
        anchors.fill: parent; anchors.margins: Theme.NCMetrics.space16
        spacing: Theme.NCMetrics.space12
        RowLayout {
            Layout.fillWidth: true; spacing: Theme.NCMetrics.space8
            NC.NCButton { text: "Local"; compact: true; tone: "primary" }
            NC.NCButton { objectName: "chessOnlineOpen"; text: "Online"; compact: true; onClicked: root.onlineMode = true }
            ChessLabel {
                Layout.fillWidth: true; Layout.minimumWidth: 0
                text: root.personaName === "Your companion" ? "A game with your favourite persona" : "Play with " + root.personaName
                elide: Text.ElideRight; maximumLineCount: 1
            }
            NC.NCButton { text: "2D"; compact: true; checkable: true; checked: (root.prefs.view || "2d") === "2d"; tone: checked ? "primary" : "secondary"; onClicked: root.setting("view", "2d") }
            NC.NCButton { text: "3D"; compact: true; checkable: true; checked: root.prefs.view === "3d"; tone: checked ? "primary" : "secondary"; onClicked: root.setting("view", "3d") }
            NC.NCButton { objectName: "chessFullscreenOpen"; text: root.width < 480 ? "Fullscreen" : "Fullscreen 3D"; compact: true; onClicked: root.fullScreen3d = true }
        }
        ScrollView {
            id: viewport
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            GridLayout {
                width: viewport.availableWidth
                height: root.narrow ? implicitHeight : Math.max(360, viewport.availableHeight)
                columns: root.narrow ? 1 : 2
                columnSpacing: Theme.NCMetrics.space16; rowSpacing: Theme.NCMetrics.space16
                Rectangle {
                    id: boardSurface
                    objectName: "chessBoardSurface"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Layout.minimumWidth: 280
                    Layout.minimumHeight: root.narrow ? 340 : 300
                    Layout.preferredHeight: root.narrow ? Math.min(viewport.availableWidth, 540) : 480
                    color: Theme.NCTheme.surface; radius: Theme.NCMetrics.radiusLarge
                    border.color: Theme.NCTheme.border
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: Theme.NCMetrics.space12
                        spacing: Theme.NCMetrics.space8
                        RowLayout {
                            Layout.fillWidth: true
                            ChessLabel { Layout.fillWidth: true; text: root.phaseLabel; color: root.connected ? Theme.NCTheme.accent : Theme.NCTheme.textSecondary; elide: Text.ElideRight; maximumLineCount: 1 }
                            ChessLabel { text: root.gameFinished ? root.resultTitle : root.game.check ? "Check" : "Move " + (Math.floor((root.game.ply || 0) / 2) + 1); color: root.gameFinished ? Theme.NCTheme.success : root.game.check ? Theme.NCTheme.warning : Theme.NCTheme.textSecondary }
                        }
                        Item {
                            Layout.fillWidth: true; Layout.fillHeight: true
                            Loader {
                                anchors.fill: parent
                                active: root.visible && !root.fullScreen3d && !!root.game.fen
                                enabled: root.connected && !root.state.busy
                                opacity: root.connected ? 1 : .18
                                sourceComponent: root.prefs.view === "3d" ? scene : flatBoard
                            }
                            ColumnLayout {
                                objectName: "chessConnectionEmpty"
                                anchors.centerIn: parent
                                width: Math.min(Math.max(0, parent.width - 32), 360)
                                visible: !root.connected
                                spacing: Theme.NCMetrics.space12
                                ChessLabel { Layout.fillWidth: true; text: "Connect your chess server"; color: Theme.NCTheme.text; font.pixelSize: Theme.NCTypography.headingSize; horizontalAlignment: Text.AlignHCenter }
                                ChessLabel { Layout.fillWidth: true; text: root.connectionMessage; horizontalAlignment: Text.AlignHCenter }
                                NC.NCButton { Layout.alignment: Qt.AlignHCenter; text: "Open connection setup"; tone: "primary"; onClicked: root.showSetup() }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            ChessLabel { Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize; text: "You · " + (root.game.human || root.prefs.human || "white") }
                            ChessLabel { font.pixelSize: Theme.NCTypography.captionSize; text: root.personaName; elide: Text.ElideRight; maximumLineCount: 1; Layout.maximumWidth: boardSurface.width * .5 }
                        }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Layout.preferredWidth: root.narrow ? 0 : 300
                    Layout.maximumWidth: root.narrow ? Infinity : 320
                    Layout.minimumWidth: root.narrow ? 0 : 280
                    Layout.minimumHeight: root.narrow ? 440 : 0
                    color: "transparent"
                    ColumnLayout {
                        anchors.fill: parent; spacing: Theme.NCMetrics.space12
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space4
                            Repeater {
                                model: ["Game", "Scene", "Sounds", "Setup"]
                                NC.NCTabButton {
                                    required property int index
                                    required property string modelData
                                    objectName: "chessInspector" + modelData
                                    Layout.fillWidth: true; Layout.minimumWidth: 0
                                    text: modelData; checkable: true; checked: root.inspectorTab === index
                                    onClicked: root.inspectorTab = index
                                }
                            }
                        }
                        ScrollView {
                            id: inspectorScroll
                            Layout.fillWidth: true; Layout.fillHeight: true
                            clip: true; contentWidth: availableWidth
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ChessInspector {
                                width: inspectorScroll.availableWidth
                                workspace: root
                                section: ["game", "scene", "sounds", "setup"][root.inspectorTab] || "game"
                            }
                        }
                    }
                }
            }
        }
        ChessStatusStrip { Layout.fillWidth: true; workspace: root }
        RowLayout {
            Layout.fillWidth: true; spacing: Theme.NCMetrics.space8
            Rectangle { Layout.preferredWidth: 7; Layout.preferredHeight: 7; radius: 4; color: root.connected ? Theme.NCTheme.success : Theme.NCTheme.disconnected }
            ChessLabel {
                Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize
                text: root.state.status || root.connectionMessage; elide: Text.ElideRight; maximumLineCount: 2
                Accessible.name: text
            }
            ChessLabel { visible: root.hardware.activated === true; text: root.hardware.connected ? "Launchpad connected" : "Hardware activated"; color: root.hardware.connected ? Theme.NCTheme.success : Theme.NCTheme.textSecondary; font.pixelSize: Theme.NCTypography.captionSize }
            BusyIndicator { running: root.state.busy || false; visible: running; Layout.preferredWidth: 22; Layout.preferredHeight: 22; palette.dark: Theme.NCTheme.accent }
        }
    }
    Component {
        id: flatBoard
        Board2D {
            pieces: root.game.pieces || []; selected: root.state.selected || ""; targets: root.state.targets || []
            highlight: root.pendingSquare; orientation: root.game.human || root.prefs.human || "white"
            onSquareClicked: square => root.command("square", {square: square})
        }
    }
    Loader {
        anchors.fill: parent; active: root.onlineMode
        sourceComponent: ChessOnlineWorkspace {
            workspace: root
            onReturnLocal: root.onlineMode = false
        }
    }
    Component {
        id: scene
        Board3D {
            gameState: root.game
            dropWaiting: root.state.busy === true || (root.state.promotion || []).length > 0 || !!root.game.pending
            selected: root.state.selected || ""; targets: root.state.targets || []; highlight: root.pendingSquare
            styleName: root.styleName; boardModel: root.boardModel; lighting: root.light; lowDetail: root.lowDetail
            yaw: root.cameraYaw; pitch: root.cameraPitch; distance: root.cameraDistance
            fieldOfView: root.cameraFov
            onOrbitRequested: (yaw, pitch) => { root.cameraYaw = yaw; root.cameraPitch = pitch }
            onDistanceRequested: distance => root.cameraDistance = distance
            onFieldOfViewRequested: fieldOfView => root.cameraFov = fieldOfView
            onSquareClicked: square => root.command("square", {square: square})
            onMoveDropped: (source,destination,gameId,revision) => { if (!root.command("drop", {source:source,destination:destination,game_id:gameId,revision:revision})) dropPreview = null }
        }
    }
    ChessDialogs { id: dialogs; anchors.fill: parent; workspace: root; surfaceActive: root.visible && !root.fullScreen3d && !root.onlineMode }
    ChessFullscreen { id: full; workspace: root }
}
