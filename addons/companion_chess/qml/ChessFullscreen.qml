import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../../../ui/qml/components" as NC
import "../../../ui/qml/theme" as Theme

Window {
    id: root
    required property var workspace
    property string settingsSection: ""
    property var returnFocus: null
    readonly property bool narrow: width < 800
    title: "Companion Chess"
    color: workspace.light.preset === "spotlight" ? "black" : Theme.NCTheme.window
    visibility: workspace.fullScreen3d && workspace.visible ? Window.FullScreen : Window.Hidden
    function confirmAction(action) { closeSettings(); dialogs.confirmAction(action) }
    function openPromotion() { closeSettings(); dialogs.openPromotion() }
    function closeSettings() {
        settingsSection = ""
        if (returnFocus) returnFocus.forceActiveFocus()
    }
    function toggleSettings(section, button) {
        if (settingsSection === section) closeSettings()
        else { settingsSection = section; returnFocus = button; settingsPanel.forceActiveFocus() }
    }
    onClosing: workspace.fullScreen3d = false
    onVisibleChanged: if (!visible) settingsSection = ""
    Shortcut {
        sequence: "Escape"; enabled: root.visible
        onActivated: {
            if (dialogs.closeTop()) return
            if (root.settingsSection) root.closeSettings()
            else root.workspace.fullScreen3d = false
        }
    }
    Item {
        anchors.fill: parent
        ColumnLayout {
            anchors.fill: parent; anchors.margins: Theme.NCMetrics.space20
            spacing: Theme.NCMetrics.space12
            GridLayout {
                Layout.fillWidth: true; columns: root.narrow ? 1 : 2
                ColumnLayout {
                    Layout.fillWidth: true; spacing: Theme.NCMetrics.space4
                    ChessLabel { text: "Companion Chess"; font.pixelSize: Theme.NCTypography.headingSize; color: Theme.NCTheme.text; font.weight: Font.DemiBold }
                    ChessLabel { Layout.fillWidth: true; text: root.workspace.personaName + " · " + root.workspace.phaseLabel; elide: Text.ElideRight; maximumLineCount: 1 }
                }
                RowLayout {
                    Layout.alignment: Qt.AlignRight; spacing: Theme.NCMetrics.space8
                    NC.NCButton { id: sceneButton; objectName: "chessFullscreenScene"; text: "Scene"; onClicked: root.toggleSettings("scene", sceneButton) }
                    NC.NCButton { id: audioButton; text: "Audio"; onClicked: root.toggleSettings("sounds", audioButton) }
                    NC.NCButton { id: gameButton; text: "Game"; onClicked: root.toggleSettings("game", gameButton) }
                    NC.NCButton { text: "Exit · Esc"; onClicked: root.workspace.fullScreen3d = false }
                }
            }
            ScrollView {
                id: stageScroll
                objectName: "chessFullscreenStage"
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            GridLayout {
                width: stageScroll.availableWidth
                height: Math.max(stageScroll.availableHeight, implicitHeight)
                columns: root.narrow ? 1 : 2
                columnSpacing: Theme.NCMetrics.space16; rowSpacing: Theme.NCMetrics.space12
                Item {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Layout.minimumHeight: 220
                    Loader {
                        anchors.fill: parent
                        active: root.visible && !!root.workspace.game.fen
                        enabled: root.workspace.connected && !root.workspace.state.busy
                        sourceComponent: Component {
                            Board3D {
                                gameState: root.workspace.game
                                dropWaiting: root.workspace.state.busy === true || (root.workspace.state.promotion || []).length > 0 || !!root.workspace.game.pending
                                selected: root.workspace.state.selected || ""; targets: root.workspace.state.targets || []
                                highlight: root.workspace.pendingSquare; styleName: root.workspace.styleName; boardModel: root.workspace.boardModel; lighting: root.workspace.light
                                lowDetail: root.workspace.lowDetail; yaw: root.workspace.cameraYaw; pitch: root.workspace.cameraPitch; distance: root.workspace.cameraDistance
                                fieldOfView: root.workspace.cameraFov
                                onOrbitRequested: (yaw, pitch) => { root.workspace.cameraYaw = yaw; root.workspace.cameraPitch = pitch }
                                onDistanceRequested: distance => root.workspace.cameraDistance = distance
                                onFieldOfViewRequested: fieldOfView => root.workspace.cameraFov = fieldOfView
                                onSquareClicked: square => root.workspace.command("square", {square: square})
                                onMoveDropped: (source,destination,gameId,revision) => { if (!root.workspace.command("drop", {source:source,destination:destination,game_id:gameId,revision:revision})) dropPreview = null }
                            }
                        }
                    }
                    ColumnLayout {
                        anchors.centerIn: parent; width: Math.min(parent.width - 24, 380)
                        visible: !root.workspace.connected
                        ChessLabel { Layout.fillWidth: true; text: root.workspace.connectionMessage; horizontalAlignment: Text.AlignHCenter }
                        NC.NCButton { Layout.alignment: Qt.AlignHCenter; text: "Return to setup"; onClicked: { root.workspace.fullScreen3d = false; root.workspace.showSetup() } }
                    }
                }
                Rectangle {
                    id: settingsPanel
                    objectName: "chessFullscreenSettings"
                    Layout.fillHeight: true; Layout.fillWidth: root.narrow
                    Layout.preferredWidth: root.narrow ? 0 : 320
                    Layout.maximumWidth: root.narrow ? Infinity : 360
                    Layout.preferredHeight: root.narrow ? 300 : 0
                    Layout.minimumHeight: root.narrow ? 200 : 0
                    visible: !!root.settingsSection
                    color: Theme.NCTheme.surface; border.color: Theme.NCTheme.borderStrong; radius: Theme.NCMetrics.radiusLarge
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: Theme.NCMetrics.space16
                        RowLayout {
                            Layout.fillWidth: true
                            ChessLabel { Layout.fillWidth: true; text: root.settingsSection === "scene" ? "Scene" : root.settingsSection === "sounds" ? "Audio" : "Game"; color: Theme.NCTheme.text; font.pixelSize: Theme.NCTypography.headingSize }
                            NC.NCButton { text: "Close"; compact: true; onClicked: root.closeSettings() }
                        }
                        ScrollView {
                            id: settingsScroll
                            Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            Loader {
                                width: settingsScroll.availableWidth
                                active: !!root.settingsSection
                                sourceComponent: Component { ChessInspector { workspace: root.workspace; section: root.settingsSection } }
                            }
                        }
                    }
                }
            }
            }
            ChessStatusStrip { objectName: "chessFullscreenStatus"; Layout.fillWidth: true; workspace: root.workspace; showPause: true }
            ChessLabel { Layout.fillWidth: true; text: root.workspace.state.status || root.workspace.connectionMessage; font.pixelSize: Theme.NCTypography.captionSize; maximumLineCount: 2; elide: Text.ElideRight }
        }
        ChessDialogs { id: dialogs; anchors.fill: parent; workspace: root.workspace; surfaceActive: root.visible }
    }
}
