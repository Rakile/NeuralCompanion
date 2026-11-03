import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../../../ui/qml/components" as NC
import "../../../ui/qml/theme" as Theme

ColumnLayout {
    id: root
    required property var workspace
    property string section: "game"
    property string soundKey: "move_pawn_white"
    property bool hardwareExpanded: true
    property bool advanced: false
    spacing: Theme.NCMetrics.space12
    Loader {
        Layout.fillWidth: true
        sourceComponent: root.section === "game" ? gamePanel : root.section === "scene" ? scenePanel : root.section === "sounds" ? soundsPanel : setupPanel
    }
    Component {
        id: gamePanel
        ColumnLayout {
            spacing: Theme.NCMetrics.space10
            ChessLabel { text: "Your opponent" }
            NC.NCComboBox {
                Layout.fillWidth: true; label: "Your saved persona"
                model: root.workspace.state.personas || []; textRole: "name"; valueRole: "id"
                currentIndex: { for (let i = 0; i < count; ++i) if (valueAt(i) === root.workspace.prefs.persona_id) return i; return -1 }
                displayText: currentIndex < 0 ? "Choose a saved persona" : currentText
                enabled: !root.workspace.state.busy
                onActivated: root.workspace.setting("persona_id", currentValue)
            }
            NC.NCSwitch { Layout.fillWidth: true; text: "Use persona voice"; checked: root.workspace.prefs.speech !== false; onToggled: root.workspace.setting("speech", checked) }
            NC.NCSwitch {
                Layout.fillWidth: true; text: "Comment on my moves"
                checked: root.workspace.prefs.comment_user_moves === true
                onToggled: root.workspace.setting("comment_user_moves", checked)
            }
            ChessLabel { Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize; text: "Your companion reacts to your last move when announcing its reply. Uses the persona voice when enabled." }
            ChessLabel { text: "Play as" }
            NC.NCComboBox {
                Layout.fillWidth: true; label: "Your side"; model: ["White", "Black"]
                currentIndex: root.workspace.prefs.human === "black" ? 1 : 0
                onActivated: root.workspace.setting("human", currentIndex === 1 ? "black" : "white")
            }
            RowLayout {
                Layout.fillWidth: true
                ChessLabel { Layout.fillWidth: true; text: "Engine strength" }
                ChessLabel { text: String(root.workspace.prefs.skill || 0) + " / 20" }
            }
            NC.NCSlider {
                Layout.fillWidth: true; label: "Engine strength"; from: 0; to: 20; stepSize: 1
                value: root.workspace.prefs.skill || 0
                onMoved: root.workspace.setting("skill", value)
            }
            NC.NCButton {
                objectName: "chessNewGame"
                Layout.fillWidth: true; text: "New game"; tone: "primary"
                enabled: root.workspace.canStart
                onClicked: {
                    if ((root.workspace.game.moves || []).length) root.workspace.confirmAction("new")
                    else root.workspace.command("new")
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: Theme.NCMetrics.space6
                NC.NCButton {
                    text: root.workspace.game.phase === "paused" ? "Resume" : "Pause"; compact: true
                    enabled: root.workspace.connected && !root.workspace.gameFinished && !!root.workspace.game.phase && (!root.workspace.state.busy || root.workspace.game.phase !== "paused")
                    onClicked: root.workspace.command(root.workspace.game.phase === "paused" ? "resume" : "pause")
                }
                NC.NCButton { text: "Take back"; compact: true; enabled: root.workspace.connected && root.workspace.game.termination !== "ended" && !root.workspace.state.busy && (root.workspace.game.moves || []).length > 0 && !root.workspace.game.pending; onClicked: root.workspace.command("takeback") }
                NC.NCButton { text: "Resign"; compact: true; tone: "danger"; enabled: root.workspace.connected && !root.workspace.gameFinished && !root.workspace.state.busy && !!root.workspace.game.phase && !root.workspace.game.pending; onClicked: root.workspace.confirmAction("resign") }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.NCTheme.borderSubtle }
            ChessLabel { text: "Moves" }
            ChessLabel {
                Layout.fillWidth: true; Layout.preferredWidth: 0
                text: (root.workspace.game.moves || []).length ? root.workspace.game.moves.join("  ·  ") : "No moves yet"
                font.family: Theme.NCTypography.monoFamily; font.pixelSize: Theme.NCTypography.captionSize
                maximumLineCount: 6; elide: Text.ElideRight
                Accessible.name: (root.workspace.game.moves || []).join(", ")
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.NCTheme.borderSubtle }
            NC.NCButton {
                objectName: "activateChessHardware"
                Layout.fillWidth: true
                text: root.workspace.hardware.activated ? (root.hardwareExpanded ? "Hide hardware settings" : "Hardware settings") : "Connect / Activate hardware"
                enabled: !root.workspace.state.busy
                onClicked: {
                    if (!root.workspace.hardware.activated) { root.hardwareExpanded = true; root.workspace.command("activate_hardware") }
                    else root.hardwareExpanded = !root.hardwareExpanded
                }
            }
            Loader {
                Layout.fillWidth: true
                active: root.workspace.hardware.activated === true
                visible: active && root.hardwareExpanded
                sourceComponent: Component { ChessHardwareControls { workspace: root.workspace } }
            }
            NC.NCButton { Layout.fillWidth: true; visible: root.workspace.hardware.activated && root.hardwareExpanded; text: "Refresh hardware ports"; enabled: !root.workspace.state.busy; onClicked: root.workspace.command("activate_hardware") }
        }
    }
    Component { id: scenePanel; ChessSceneControls { workspace: root.workspace } }
    Component {
        id: soundsPanel
        ColumnLayout {
            spacing: Theme.NCMetrics.space10
            ChessLabel { text: "Game audio"; color: Theme.NCTheme.text; font.weight: Font.DemiBold }
            NC.NCSwitch { Layout.fillWidth: true; text: "Use persona voice"; checked: root.workspace.prefs.speech !== false; onToggled: root.workspace.setting("speech", checked) }
            NC.NCSwitch { Layout.fillWidth: true; text: "Enable game sounds"; checked: root.workspace.prefs.sound_enabled !== false; onToggled: root.workspace.setting("sound_enabled", checked) }
            ChessLabel { text: "Game volume · " + Math.round((root.workspace.prefs.volume || 0) * 100) + "%" }
            NC.NCSlider { Layout.fillWidth: true; label: "Game sound volume"; from: 0; to: 1; value: root.workspace.prefs.volume || 0; onMoved: root.workspace.setting("volume", value) }
            ChessLabel { text: "Sound event" }
            NC.NCComboBox {
                Layout.fillWidth: true; label: "Sound event"; model: root.workspace.controller ? root.workspace.controller.soundKeys : []
                currentIndex: Math.max(0, model.indexOf(root.soundKey))
                onActivated: root.soundKey = currentText
            }
            ChessLabel { Layout.fillWidth: true; Layout.preferredWidth: 0; font.pixelSize: Theme.NCTypography.captionSize; wrapMode: Text.WrapAnywhere; text: (root.workspace.prefs.sounds || {})[root.soundKey] || "No sound assigned" }
            NC.NCButton { Layout.fillWidth: true; text: "Choose sound…"; onClicked: soundFile.open() }
            RowLayout {
                Layout.fillWidth: true
                NC.NCButton { Layout.fillWidth: true; text: "Preview"; onClicked: root.workspace.controller.previewSound(root.soundKey) }
                NC.NCButton { Layout.fillWidth: true; text: "Stop"; onClicked: root.workspace.controller.stopSound() }
            }
            NC.NCButton { Layout.fillWidth: true; text: "Clear this sound"; onClicked: root.workspace.command("sound_clear", {key: root.soundKey}) }
            NC.NCButton { Layout.fillWidth: true; text: "Import from I:/chess"; onClicked: root.workspace.command("sound_import", {path: "I:/chess/sound_settings.json"}) }
            ChessLabel { Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize; text: "25 custom slots. Imported files are copied into Companion Chess. Persona speech uses NC’s existing voice pipeline." }
        }
    }
    Component {
        id: setupPanel
        ColumnLayout {
            spacing: Theme.NCMetrics.space12
            ChessLabel { text: "Chess connection"; color: Theme.NCTheme.text; font.weight: Font.DemiBold }
            NC.NCInlineMessage { Layout.fillWidth: true; tone: root.workspace.connected ? "success" : "info"; message: root.workspace.connectionMessage }
            ChessLabel { Layout.fillWidth: true; text: "1. Start the local server"; color: Theme.NCTheme.text }
            NC.NCButton { Layout.fillWidth: true; text: "Start Companion Chess Server"; enabled: !root.workspace.state.busy; onClicked: root.workspace.command("start_server") }
            ChessLabel { Layout.fillWidth: true; text: "2. Select its MCP connection"; color: Theme.NCTheme.text }
            NC.NCComboBox {
                Layout.fillWidth: true; label: "Chess MCP connection"
                model: root.workspace.state.servers || []; textRole: "name"; valueRole: "id"
                currentIndex: { for (let i = 0; i < count; ++i) if (valueAt(i) === root.workspace.prefs.server_id) return i; return -1 }
                displayText: currentIndex < 0 ? "Select a chess connection" : currentText
                onActivated: root.workspace.setting("server_id", currentValue)
            }
            RowLayout {
                Layout.fillWidth: true
                NC.NCButton { Layout.fillWidth: true; text: "Request access"; enabled: !!root.workspace.prefs.server_id && !root.workspace.state.busy; onClicked: root.workspace.command("request") }
                NC.NCButton { text: "Refresh"; enabled: !root.workspace.state.busy; onClicked: root.workspace.command("refresh") }
            }
            ChessLabel { Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize; text: "Add the server endpoint in Runtime → MCP Core using Bearer authentication. Approve Companion Chess access to its seven tools." }
            ChessLabel { Layout.fillWidth: true; text: "3. Assign your persona’s move tool"; color: Theme.NCTheme.text }
            ChessLabel { Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize; text: "Grant chess_choose_move to Chat MCP Tools and assign it to your chosen persona in Persona → MCP. Selecting a persona here does not grant tool access." }
            NC.NCButton { Layout.fillWidth: true; text: root.advanced ? "Hide advanced details" : "Advanced connection details"; onClicked: root.advanced = !root.advanced }
            ColumnLayout {
                visible: root.advanced; Layout.fillWidth: true; spacing: Theme.NCMetrics.space8
                ChessLabel { text: "Server port" }
                NC.NCSpinBox { Layout.fillWidth: true; from: 1024; to: 65535; value: root.workspace.prefs.port || 8766; editable: true; onValueModified: root.workspace.setting("port", value) }
                NC.NCTextField { Layout.fillWidth: true; text: root.workspace.state.endpoint || "http://127.0.0.1:8766/mcp"; readOnly: true; selectByMouse: true; Accessible.name: "Chess endpoint" }
                NC.NCButton { Layout.fillWidth: true; text: "Show setup credential"; enabled: root.workspace.state.server_running || false; onClicked: root.workspace.command("reveal_token") }
                NC.NCTextField { Layout.fillWidth: true; visible: !!root.workspace.state.setup_token; text: root.workspace.state.setup_token || ""; readOnly: true; selectByMouse: true; Accessible.name: "Chess setup credential" }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.NCTheme.borderSubtle }
            ChessLabel { text: "Engine"; color: Theme.NCTheme.text; font.weight: Font.DemiBold }
            NC.NCTextField {
                objectName: "chessEnginePath"
                Layout.fillWidth: true
                text: root.workspace.prefs.engine_path === "bundled"
                    ? String(root.workspace.state.bundled_engine_path || "") : String(root.workspace.prefs.engine_path || "")
                placeholderText: "Empty uses the basic engine"
                Accessible.name: "Stockfish executable"
                enabled: !root.workspace.state.busy
                onEditingFinished: root.workspace.setting("engine_path",
                    text.length > 0 && text === String(root.workspace.state.bundled_engine_path || "") ? "bundled" : text)
            }
            NC.NCButton {
                objectName: "chessSelectEngine"
                Layout.fillWidth: true; text: "Select existing engine…"
                enabled: !root.workspace.state.busy && !root.workspace.settingsPending
                onClicked: engineFile.open()
            }
            NC.NCButton {
                objectName: "chessInstallEngine"
                Layout.fillWidth: true; text: "Install Stockfish…"
                visible: !!root.workspace.state.engine_install_supported
                enabled: !root.workspace.state.busy && !root.workspace.settingsPending
                onClicked: engineFolder.open()
            }
            NC.NCButton {
                objectName: "chessCancelEngineInstall"
                Layout.fillWidth: true; text: "Cancel installation"
                visible: !!root.workspace.state.engine_installing
                onClicked: root.workspace.command("engine_cancel")
            }
            NC.NCProgressBar {
                Layout.fillWidth: true
                visible: !!root.workspace.state.engine_installing
                indeterminate: visible
            }
            ChessLabel {
                Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize
                visible: text.length > 0
                text: String(root.workspace.state.engine_message || "")
            }
            ChessLabel {
                Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize
                text: root.workspace.prefs.engine_path === "bundled" && !root.workspace.state.bundled_engine_available
                    ? "Your previously bundled Stockfish is missing. Install Stockfish or select an existing engine. The basic engine is used until then."
                    : "Stockfish is optional. Install it in a Stockfish subfolder of a folder you choose, or select an existing executable. Clear the field for the basic engine. Strength applies to Stockfish. Start a new game to apply changes."
            }
        }
    }
    FileDialog {
        id: engineFile
        objectName: "chessEngineFileDialog"
        title: "Select an existing Stockfish engine"
        nameFilters: ["Executables (*.exe)", "All files (*)"]
        onAccepted: root.workspace.command("engine_select", {path: String(selectedFile)})
    }
    FolderDialog {
        id: engineFolder
        objectName: "chessEngineFolderDialog"
        title: "Choose a parent folder — Stockfish will be installed in its Stockfish subfolder"
        onAccepted: root.workspace.command("engine_install", {folder: String(selectedFolder)})
    }
    FileDialog {
        id: soundFile
        title: "Choose a chess sound"; nameFilters: ["Audio (*.wav *.mp3 *.ogg *.flac *.m4a)"]
        onAccepted: root.workspace.command("sound_assign", {key: root.soundKey, path: String(selectedFile)})
    }
}
