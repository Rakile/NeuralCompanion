pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "components"
import "workspaces"
import "theme" as Theme

ApplicationWindow {
    id: root
    objectName: "neuralCompanionQmlWindow"

    required property var bridge

    function syncAppearance() {
        const appearance = bridge.appearance
        Theme.NCTheme.applyAppearance(appearance.selection || bridge.currentTheme, appearance.colors)
    }

    Connections {
        target: root.bridge.appearance
        function onStateChanged() { root.syncAppearance() }
    }

    width: 1480
    height: 920
    minimumWidth: Math.min(Theme.NCMetrics.minimumWindowWidth, Number(geometryWorkArea.width || Theme.NCMetrics.minimumWindowWidth))
    minimumHeight: Math.min(Theme.NCMetrics.minimumWindowHeight, Number(geometryWorkArea.height || Theme.NCMetrics.minimumWindowHeight))
    visible: true
    title: bridge.applicationTitle
    color: Theme.NCTheme.window

    property bool geometryRestored: false
    property var geometryWorkArea: ({})
    property bool geometryRecoveryPending: false
    property bool orbMainWindowRaised: false
    property int normalWindowX: x
    property int normalWindowY: y
    property int normalWindowWidth: width
    property int normalWindowHeight: height
    property var floatingWindows: ({})
    readonly property bool uiReviewNotesVisible:
        Boolean(root.bridge.uiReviewNotes.mainWindowControlsVisible)

    MuseTalkCreatorDepartureDialog { creatorModel: root.bridge.museTalkCreator }

    NCRestartConfirmation {
        id: restartConfirmation
        onAccepted: root.bridge.confirmDesktopRestart()
        onRejected: root.bridge.cancelDesktopRestart()
    }

    NCPowerRestartDialog {
        id: powerRestartDialog
        onRestartRequested: saveConversation => root.bridge.requestPowerButtonRestart(saveConversation)
    }

    Connections {
        target: root.bridge.museTalkCreator

        function onRenderPreviewRequested() {
            // Rendering never changes user-selected docking or floating groups.
            // Already-visible previews update without stealing workspace focus.
            if (root.bridge.workspaceHost("musetalk") === "main") {
                const preview = root.workspaceItemForKey("musetalk")
                if (!preview || !preview.visible)
                    root.activateWorkspace("musetalk")
                return
            }
            root.syncFloatingWindows()
            const previewWindow = root.floatingWindowForWorkspace("musetalk")
            if (previewWindow && (!previewWindow.visible
                    || previewWindow.visibility === Window.Minimized
                    || previewWindow.currentWorkspaceKey !== "musetalk")) {
                if (!previewWindow.visible)
                    previewWindow.showNormal()
                root.activateWorkspace("musetalk")
            }
        }
    }

    Label {
        z: 100
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        padding: Theme.NCMetrics.space12
        visible: Boolean(root.bridge.runtimeStarting) || Boolean(root.bridge.applicationClosing)
        text: root.bridge.applicationClosing
              ? qsTr("Waiting for MuseTalk to unload before closing…")
              : root.bridge.runtimeCancelling ? qsTr("Cancelling initialization…")
              : qsTr("Waiting for MuseTalk to unload before starting chat…")
        color: Theme.NCTheme.text
        background: Rectangle { color: Theme.NCTheme.windowRaised }
    }

    // A single global listener/dialog set follows the active NC window.
    NCGlobalFeedbackHost {
        id: globalFeedbackHost
        bridge: root.bridge
        mainWindow: root
    }

    Window {
        id: externalAvatarReturnWindow
        width: 250
        height: 96
        visible: false
        flags: Qt.Tool | Qt.WindowStaysOnTopHint
        color: Theme.NCTheme.windowRaised
        title: qsTr("Return to NeuralCompanion")
        property string modeLabel: qsTr("Avatar")

        Rectangle {
            anchors.fill: parent
            color: Theme.NCTheme.windowRaised
            border.color: Theme.NCTheme.accent
            border.width: Theme.NCMetrics.focusWidth
            radius: Theme.NCMetrics.radiusMedium

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space12
                spacing: Theme.NCMetrics.space8

                Label {
                    Layout.fillWidth: true
                    text: qsTr("%1 focus is active").arg(externalAvatarReturnWindow.modeLabel)
                    color: Theme.NCTheme.textSecondary
                    horizontalAlignment: Text.AlignHCenter
                }
                NCButton {
                    Layout.fillWidth: true
                    text: qsTr("Show NeuralCompanion")
                    tone: "primary"
                    onClicked: {
                        externalAvatarReturnWindow.hide()
                        root.show()
                        root.raise()
                        root.requestActivate()
                    }
                }
            }
        }

        onClosing: function(close) {
            close.accepted = false
            externalAvatarReturnWindow.hide()
            root.show()
            root.raise()
            root.requestActivate()
        }
    }

    function floatingWindowForWorkspace(workspaceKey) {
        const key = String(workspaceKey || "")
        const windowIds = Object.keys(floatingWindows)
        for (let index = 0; index < windowIds.length; ++index) {
            const candidate = floatingWindows[windowIds[index]]
            if (candidate && candidate.containsWorkspace(key))
                return candidate
        }
        return null
    }

    property string tutorialNavigationKey: ""

    function activateTutorialDestination() {
        const state = root.bridge.tutorialState || ({})
        const key = state.active ? JSON.stringify([state.title, state.stepNumber, state.stepTarget,
                                                   state.scoped ? state.navigationToken : 0, state.scoped ? state.viewToken : 0]) : ""
        if (key === root.tutorialNavigationKey) return
        root.tutorialNavigationKey = key
        if (!state.active || state.paused || state.elsewhere) return
        // Resolve through the live docking layout, including grouped, hidden,
        // and minimized floating windows. Never move a user's panels.
        root.syncFloatingWindows()
        root.activateWorkspace(String(state.stepWorkspace || ""))
    }

    function activateWorkspace(workspaceKey) {
        const key = String(workspaceKey || "")
        if (!(root.bridge.mainNavigationWorkspaces || []).some(item => String(item.key) === key))
            return
        if (root.bridge.workspaceHost(key) === "main") {
            root.bridge.activateMainWorkspace(key)
            root.raise()
            root.requestActivate()
            return
        }
        const floatingWindow = floatingWindowForWorkspace(key)
        if (floatingWindow)
            floatingWindow.activateWorkspace(key)
    }

    function workspaceItemForKey(workspaceKey) {
        const key = String(workspaceKey || "")
        if (root.bridge.workspaceHost(key) === "main")
            return mainDockSurface.workspaceItemForKey(key)
        const floatingWindow = floatingWindowForWorkspace(key)
        return floatingWindow ? floatingWindow.workspaceItem : null
    }

    function syncFloatingWindows() {
        const groups = bridge.floatingWorkspaceGroups || []
        const desiredIds = ({})
        for (let index = 0; index < groups.length; ++index) {
            const group = groups[index]
            const groupId = String(group.id || "")
            if (!groupId)
                continue
            desiredIds[groupId] = true
            const existing = floatingWindows[groupId]
            if (existing) {
                existing.groupData = group
                continue
            }
            const created = floatingWorkspaceWindowComponent.createObject(root, {
                "bridge": bridge,
                "groupData": group
            })
            if (created) {
                floatingWindows[groupId] = created
            }
        }

        const existingIds = Object.keys(floatingWindows)
        for (let index = 0; index < existingIds.length; ++index) {
            const groupId = existingIds[index]
            if (desiredIds[groupId])
                continue
            const obsoleteWindow = floatingWindows[groupId]
            delete floatingWindows[groupId]
            if (obsoleteWindow) {
                obsoleteWindow.allowProgrammaticClose = true
                obsoleteWindow.close()
                obsoleteWindow.destroy()
            }
        }
        globalFeedbackHost.floatingWindows = Object.keys(floatingWindows).map(key => floatingWindows[key])
    }

    function scheduleMainGeometrySave() {
        if (!geometryRestored)
            return
        if (visibility === Window.Windowed) {
            normalWindowX = Math.round(x)
            normalWindowY = Math.round(y)
            normalWindowWidth = Math.round(width)
            normalWindowHeight = Math.round(height)
        }
        mainGeometrySaveTimer.restart()
    }

    function restoreMainWindowGeometry(geometry) {
        const restored = bridge.windowGeometry.recover({
            "x": geometry.x === null || geometry.x === undefined ? x : Number(geometry.x),
            "y": geometry.y === null || geometry.y === undefined ? y : Number(geometry.y),
            "width": Math.max(minimumWidth, Number(geometry.width || width)),
            "height": Math.max(minimumHeight, Number(geometry.height || height))
        }, Theme.NCMetrics.minimumWindowWidth, Theme.NCMetrics.minimumWindowHeight)
        geometryWorkArea = restored.workArea
        width = restored.geometry.width
        height = restored.geometry.height
        x = restored.geometry.x
        y = restored.geometry.y
    }

    function recoverMainWindowGeometry() {
        if (!geometryRestored)
            return
        if (visibility !== Window.Windowed) {
            geometryRecoveryPending = true
            return
        }
        geometryRecoveryPending = false
        restoreMainWindowGeometry({"x": x, "y": y, "width": width, "height": height})
    }

    Connections {
        target: root.bridge.windowGeometry
        function onChanged() { root.recoverMainWindowGeometry() }
    }

    function openRuntimeView(section, responsibility) {
        root.activateWorkspace("runtime")
        Qt.callLater(function() {
            const page = root.workspaceItemForKey("runtime")
            if (!page)
                return
            page.currentSection = String(section || "runtime")
            page.currentResponsibility = String(responsibility || "language")
        })
    }

    function navigateToUiReviewNote(note) {
        const workspace = String(note.workspace || "runtime")
        root.activateWorkspace(workspace)
        Qt.callLater(function() {
            if (workspace === "addons" && String(note.addonId || "").length > 0)
                root.bridge.viewAddon(String(note.addonId))
            Qt.callLater(function() {
                const page = root.workspaceItemForKey(workspace)
                const section = String(note.section || "")
                if (page && section.length > 0 && page.currentSection !== undefined)
                    page.currentSection = section
                root.bridge.uiReviewNotes.requestHighlight(String(note.id || ""))
            })
        })
    }

    Shortcut { sequence: "Ctrl+1"; onActivated: root.activateWorkspace("runtime") }
    Shortcut { sequence: "Ctrl+2"; onActivated: root.activateWorkspace("addons") }
    Shortcut { sequence: "Ctrl+3"; onActivated: root.activateWorkspace("conversation") }
    Shortcut { sequence: "Ctrl+4"; onActivated: root.activateWorkspace("visuals") }
    Shortcut { sequence: "Ctrl+5"; onActivated: root.activateWorkspace("musetalk") }

    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.bodySize

    Component.onCompleted: {
        const geometry = bridge.mainWindowLayout || {}
        restoreMainWindowGeometry(geometry)
        normalWindowX = Math.round(x)
        normalWindowY = Math.round(y)
        normalWindowWidth = Math.round(width)
        normalWindowHeight = Math.round(height)
        geometryRestored = true
        if (Boolean(geometry.maximized))
            Qt.callLater(root.showMaximized)
        syncAppearance()
        syncFloatingWindows()
        if (bridge.shouldPromptFirstRun)
            firstRunDialog.open()
    }

    onXChanged: scheduleMainGeometrySave()
    onYChanged: scheduleMainGeometrySave()
    onWidthChanged: scheduleMainGeometrySave()
    onHeightChanged: scheduleMainGeometrySave()
    onVisibilityChanged: {
        if (geometryRecoveryPending && visibility === Window.Windowed)
            recoverMainWindowGeometry()
        scheduleMainGeometrySave()
    }
    onClosing: function(close) {
        if (!root.bridge.beginApplicationShutdown()) {
            close.accepted = false
            return
        }
        const windowIds = Object.keys(root.floatingWindows)
        for (let index = 0; index < windowIds.length; ++index) {
            const floatingWindow = root.floatingWindows[windowIds[index]]
            if (!floatingWindow)
                continue
            floatingWindow.allowProgrammaticClose = true
            floatingWindow.close()
        }
        Qt.callLater(Qt.quit)
    }

    Connections {
        target: root.bridge
        function onApplicationShutdownReady() { root.close() }
        function onDesktopRestartConfirmationRequested() {
            if (root.visibility === Window.Minimized)
                root.showNormal()
            else
                root.show()
            root.raise()
            root.requestActivate()
            // The Enter used to execute the command must not also confirm it.
            Qt.callLater(restartConfirmation.open)
        }
        function onApplicationClosingChanged() {
            if (root.bridge.applicationClosing && restartConfirmation.visible)
                restartConfirmation.reject()
            if (root.bridge.applicationClosing && powerRestartDialog.visible)
                powerRestartDialog.reject()
        }
    }

    Timer {
        id: mainGeometrySaveTimer
        interval: 350
        repeat: false
        onTriggered: root.bridge.updateMainWindowGeometry(
                         root.normalWindowX,
                         root.normalWindowY,
                         root.normalWindowWidth,
                         root.normalWindowHeight,
                         root.visibility === Window.Maximized)
    }

    header: Rectangle {
        id: applicationHeader
        implicitHeight: Theme.NCMetrics.topBarHeight
        color: Theme.NCTheme.windowRaised
        border.color: Theme.NCTheme.borderSubtle
        border.width: Theme.NCMetrics.borderWidth
        readonly property real runtimeStackRequiredWidth:
            applicationIdentityButton.implicitWidth
            + primaryNavigation.implicitWidth
            + primaryNavigation.Layout.leftMargin
            + (root.uiReviewNotesVisible ? noteModeButton.implicitWidth : 0)
            + (root.uiReviewNotesVisible ? reviewNotesButton.implicitWidth : 0)
            + runtimeStackLabels.implicitWidth
            + (headerContent.spacing * (root.uiReviewNotesVisible ? 5 : 3))

        NCMainNavigationMenu {
            id: mainNavigationMenu
            parent: Overlay.overlay
            bridge: root.bridge
        }

        RowLayout {
            id: headerContent
            anchors.left: parent.left
            anchors.right: runtimeSessionControl.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: Theme.NCMetrics.space20
            anchors.rightMargin: Theme.NCMetrics.space16
            spacing: Theme.NCMetrics.space16

            Button {
                id: applicationIdentityButton
                objectName: "mainNavigationMenuButton"
                implicitWidth: identityContents.implicitWidth + leftPadding + rightPadding
                implicitHeight: identityContents.implicitHeight + topPadding + bottomPadding
                padding: Theme.NCMetrics.space4
                hoverEnabled: true
                Accessible.name: qsTr("NeuralCompanion tabs and layout")
                Accessible.description: qsTr("Show or hide main tabs, lock panel positions, or reset the window layout.")
                onClicked: mainNavigationMenu.openFor(applicationIdentityButton)
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: mainNavigationMenu.openFor(applicationIdentityButton)
                }
                background: Rectangle {
                    radius: Theme.NCMetrics.radiusMedium
                    color: applicationIdentityButton.hovered || mainNavigationMenu.opened
                           ? Theme.NCTheme.surfaceRaised : "transparent"
                    border.width: applicationIdentityButton.activeFocus ? Theme.NCMetrics.focusWidth : 0
                    border.color: Theme.NCTheme.focus
                }
                contentItem: RowLayout {
                    id: identityContents
                    spacing: Theme.NCMetrics.space12

                    Rectangle {
                        id: applicationIdentityMark
                        Layout.preferredWidth: 40
                        Layout.preferredHeight: 40
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.window
                        border.color: Theme.NCTheme.accent
                        clip: true

                        Image {
                            objectName: "applicationIdentityLogo"
                            anchors.fill: parent
                            anchors.margins: 2
                            source: "../../ui_icons/branding/NC_logo.png"
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                            mipmap: true
                        }
                    }

                    ColumnLayout {
                        id: applicationTitleBlock
                        spacing: 0

                        Item {
                            implicitWidth: applicationTitleLabel.implicitWidth + 2
                            implicitHeight: applicationTitleLabel.implicitHeight + 2

                            Label {
                                id: applicationTitlePulse
                                objectName: "applicationTitlePulse"
                                anchors.centerIn: applicationTitleLabel
                                text: applicationTitleLabel.text
                                color: Theme.NCTheme.accent
                                opacity: root.bridge.systemRunning ? 0.12 : 0.0
                                scale: 1.018
                                font: applicationTitleLabel.font

                                SequentialAnimation on color {
                                    running: root.bridge.systemRunning
                                    loops: Animation.Infinite
                                    ColorAnimation {
                                        to: Theme.NCTheme.accent
                                        duration: 1600
                                    }
                                    ColorAnimation {
                                        to: Theme.NCTheme.warning
                                        duration: 1600
                                    }
                                }

                                SequentialAnimation on opacity {
                                    running: root.bridge.systemRunning
                                    loops: Animation.Infinite
                                    NumberAnimation {
                                        from: 0.07
                                        to: 0.19
                                        duration: 1600
                                    }
                                    NumberAnimation {
                                        from: 0.19
                                        to: 0.07
                                        duration: 1600
                                    }
                                }
                            }

                            Label {
                                id: applicationTitleLabel
                                text: root.bridge.applicationTitle
                                color: Theme.NCTheme.text
                                font.pixelSize: Theme.NCTypography.headingSize
                                font.weight: Theme.NCTypography.semibold
                            }
                        }
                    }

                    Label {
                        text: "▾"
                        color: Theme.NCTheme.textSecondary
                        font.pixelSize: Theme.NCTypography.bodySize
                    }
                }
            }

            RowLayout {
                id: primaryNavigation
                Layout.leftMargin: Theme.NCMetrics.space16
                spacing: Theme.NCMetrics.space4

                Repeater {
                    model: root.bridge.mainNavigationWorkspaces

                    delegate: Button {
                        id: navigationButton
                        NCTutorialMarker { bridge: root.bridge; context: ({workspace: navigationButton.workspaceKey}) }
                        required property int index
                        required property var modelData
                        property string workspaceKey: String(modelData.key || "")
                        objectName: "mainNavigationTab_" + workspaceKey
                        checked: !Boolean(modelData.detached)
                                 && workspaceKey === root.bridge.currentWorkspace
                        implicitHeight: Theme.NCMetrics.controlHeight
                        implicitWidth: Math.max(86, navigationLabel.implicitWidth + Theme.NCMetrics.space24)
                        padding: Theme.NCMetrics.space8
                        hoverEnabled: true
                        Accessible.name: String(modelData.label)
                        Accessible.description: qsTr("Open %1 workspace. Shortcut Ctrl+%2.")
                                                .arg(String(modelData.label)).arg(Number(modelData.shortcutNumber))

                        background: Rectangle {
                            radius: Theme.NCMetrics.radiusMedium
                            color: navigationButton.down ? Theme.NCTheme.surfacePressed
                                                         : navigationButton.checked ? Theme.NCTheme.surfaceSelected
                                                         : navigationButton.hovered ? Theme.NCTheme.surfaceRaised
                                                         : Theme.NCTheme.surface
                            border.width: navigationButton.activeFocus || navigationButton.checked
                                          ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                            border.color: navigationButton.activeFocus ? Theme.NCTheme.focus
                                        : navigationButton.checked ? Theme.NCTheme.accent
                                        : Theme.NCTheme.border
                        }

                        contentItem: Label {
                            id: navigationLabel
                            text: String(navigationButton.modelData.label)
                                  + (Boolean(navigationButton.modelData.detached) ? "  ↗" : "")
                            color: navigationButton.checked ? Theme.NCTheme.text : Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.labelSize
                            font.weight: navigationButton.checked ? Theme.NCTypography.semibold : Theme.NCTypography.medium
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: root.activateWorkspace(workspaceKey)

                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onTapped: navigationMenu.openFor(navigationButton)
                        }

                        NCDockContextMenu {
                            id: navigationMenu
                            parent: Overlay.overlay
                            bridge: root.bridge
                            workspaceKey: navigationButton.workspaceKey
                            workspaceLabel: String(navigationButton.modelData.label || qsTr("Workspace"))
                            onOpenRequested: function(key) {
                                root.activateWorkspace(key)
                            }
                        }

                        NCToolTip {
                            visible: navigationButton.hovered
                            delay: 500
                            text: qsTr("%1  ·  Ctrl+%2")
                                  .arg(String(navigationButton.modelData.label))
                                  .arg(Number(navigationButton.modelData.shortcutNumber))
                        }
                    }
                }

                Button {
                    id: audioButton
                    objectName: "headerAudioButton"
                    implicitHeight: Theme.NCMetrics.controlHeight
                    implicitWidth: Math.max(98, audioButtonLabel.implicitWidth + Theme.NCMetrics.space24)
                    padding: Theme.NCMetrics.space8
                    hoverEnabled: true
                    checked: audioPopup.opened
                    Accessible.name: qsTr("Audio controls")
                    Accessible.description: qsTr("Select NC input and output devices, volume, and microphone visualization.")

                    function modelIndex(values, selected) {
                        var target = String(selected || "")
                        for (var index = 0; index < values.length; ++index) {
                            if (String(values[index]) === target)
                                return index
                        }
                        return 0
                    }

                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusMedium
                        color: audioButton.down ? Theme.NCTheme.surfacePressed
                                                : audioButton.checked ? Theme.NCTheme.surfaceSelected
                                                : audioButton.hovered ? Theme.NCTheme.surfaceRaised
                                                : Theme.NCTheme.surface
                        border.width: audioButton.activeFocus || audioButton.checked
                                      ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                        border.color: audioButton.activeFocus ? Theme.NCTheme.focus
                                    : audioButton.checked ? Theme.NCTheme.accent
                                    : Theme.NCTheme.border
                    }

                    contentItem: Label {
                        id: audioButtonLabel
                        text: "≋  " + qsTr("Audio")
                        color: audioButton.checked ? Theme.NCTheme.text : Theme.NCTheme.textSecondary
                        font.pixelSize: Theme.NCTypography.labelSize
                        font.weight: audioButton.checked ? Theme.NCTypography.semibold : Theme.NCTypography.medium
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }

                    onClicked: audioPopup.opened ? audioPopup.close() : audioPopup.open()

                    Popup {
                        id: audioPopup
                        objectName: "headerAudioPopup"
                        parent: Overlay.overlay
                        width: Math.min(430, root.width - Theme.NCMetrics.space32)
                        padding: Theme.NCMetrics.space16
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                        modal: false

                        onAboutToShow: {
                            root.bridge.audioControls.refreshDevices()
                            var point = audioButton.mapToItem(
                                Overlay.overlay,
                                0,
                                audioButton.height + Theme.NCMetrics.space6
                            )
                            x = Math.max(
                                Theme.NCMetrics.space8,
                                Math.min(point.x, root.width - width - Theme.NCMetrics.space8)
                            )
                            y = point.y
                        }

                        background: Rectangle {
                            radius: Theme.NCMetrics.radiusLarge
                            color: Theme.NCTheme.windowRaised
                            border.width: Theme.NCMetrics.borderWidth
                            border.color: Theme.NCTheme.borderStrong
                        }

                        contentItem: ColumnLayout {
                            spacing: Theme.NCMetrics.space12

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space8

                                Label {
                                    text: "≋"
                                    color: Theme.NCTheme.accent
                                    font.pixelSize: 24
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    Label {
                                        text: qsTr("Audio")
                                        color: Theme.NCTheme.text
                                        font.pixelSize: Theme.NCTypography.headingSize
                                        font.weight: Theme.NCTypography.semibold
                                    }
                                    Label {
                                        text: qsTr("NC devices, playback level, and Presence routing")
                                        color: Theme.NCTheme.textMuted
                                        font.pixelSize: Theme.NCTypography.microSize
                                    }
                                }
                                NCIconButton {
                                    glyph: "↻"
                                    toolTipText: qsTr("Refresh audio devices")
                                    enabled: !root.bridge.audioControls.refreshing
                                    onClicked: root.bridge.audioControls.refreshDevices()
                                }
                            }

                            Label {
                                text: qsTr("Audio output")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.labelSize
                                font.weight: Theme.NCTypography.semibold
                            }
                            NCComboBox {
                                toolTipText: qsTr("Playback device used by NC. Default Output follows the system default. Changes apply to the next NC playback segment; Discord voice output uses its own connection.")

                                id: audioOutputSelector
                                objectName: "headerAudioOutputSelector"
                                Layout.fillWidth: true
                                label: qsTr("Audio output device")
                                model: root.bridge.audioControls.outputDevices
                                currentIndex: audioButton.modelIndex(
                                    root.bridge.audioControls.outputDevices,
                                    root.bridge.audioControls.selectedOutputDevice
                                )
                                onActivated: root.bridge.audioControls.setOutputDevice(currentText)
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    text: qsTr("Output volume")
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.bodySize
                                }
                                Item { Layout.fillWidth: true }
                                Label {
                                    text: Math.round(root.bridge.audioControls.outputVolume * 100) + "%"
                                    color: Theme.NCTheme.accent
                                    font.pixelSize: Theme.NCTypography.labelSize
                                }
                            }
                            NCSlider {
                                toolTipText: qsTr("NC playback volume from 0 to 1: 0 is silent and 1 is full application volume. This does not change Windows master volume or other applications.")

                                id: audioOutputVolume
                                objectName: "headerAudioOutputVolume"
                                Layout.fillWidth: true
                                from: 0.0
                                to: 1.0
                                stepSize: 0.01
                                value: root.bridge.audioControls.outputVolume
                                label: qsTr("NC output volume")
                                onMoved: root.bridge.audioControls.setOutputVolume(value)
                            }

                            Rectangle {
                                objectName: "headerAudioOutputMeter"
                                Layout.fillWidth: true
                                implicitHeight: 10
                                radius: 5
                                color: Theme.NCTheme.surface
                                border.width: Theme.NCMetrics.borderWidth
                                border.color: Theme.NCTheme.border
                                clip: true
                                Rectangle {
                                    width: parent.width * root.bridge.audioControls.outputLevel
                                    height: parent.height
                                    radius: parent.radius
                                    color: Theme.NCTheme.accent
                                    Behavior on width { NumberAnimation { duration: 45 } }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 1
                                color: Theme.NCTheme.borderSubtle
                            }

                            Label {
                                text: qsTr("Audio input")
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.labelSize
                                font.weight: Theme.NCTypography.semibold
                            }
                            NCComboBox {
                                toolTipText: qsTr("Microphone used by NC. Default Input follows the system default. An already open microphone uses the new selection the next time it opens.")

                                id: audioInputSelector
                                objectName: "headerAudioInputSelector"
                                Layout.fillWidth: true
                                label: qsTr("Audio input device")
                                model: root.bridge.audioControls.inputDevices
                                currentIndex: audioButton.modelIndex(
                                    root.bridge.audioControls.inputDevices,
                                    root.bridge.audioControls.selectedInputDevice
                                )
                                onActivated: root.bridge.audioControls.setInputDevice(currentText)
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    text: qsTr("Presence microphone level")
                                    color: Theme.NCTheme.textMuted
                                    font.pixelSize: Theme.NCTypography.microSize
                                }
                                Item { Layout.fillWidth: true }
                                Label {
                                    text: root.bridge.audioControls.inputVoiceActive
                                          ? qsTr("VOICE") : qsTr("IDLE")
                                    color: root.bridge.audioControls.inputVoiceActive
                                           ? Theme.NCTheme.success : Theme.NCTheme.textMuted
                                    font.pixelSize: Theme.NCTypography.microSize
                                    font.weight: Theme.NCTypography.semibold
                                }
                            }
                            Rectangle {
                                objectName: "headerAudioInputMeter"
                                Layout.fillWidth: true
                                implicitHeight: 10
                                radius: 5
                                color: Theme.NCTheme.surface
                                border.width: Theme.NCMetrics.borderWidth
                                border.color: Theme.NCTheme.border
                                clip: true
                                Rectangle {
                                    width: parent.width * root.bridge.audioControls.inputLevel
                                    height: parent.height
                                    radius: parent.radius
                                    color: root.bridge.audioControls.inputVoiceActive
                                           ? Theme.NCTheme.success : Theme.NCTheme.accent
                                    Behavior on width { NumberAnimation { duration: 45 } }
                                }
                            }

                            NCSwitch {
                                toolTipText: qsTr("Let microphone activity drive a separate user thread in AI Presence. This affects visualization only and does not enable speech recognition or send voice to a language model.")

                                id: microphonePresenceToggle
                                objectName: "headerMicrophonePresenceToggle"
                                Layout.fillWidth: true
                                text: qsTr("Show my voice as a separate Presence thread")
                                checked: root.bridge.audioControls.microphonePresenceEnabled
                                onToggled: root.bridge.audioControls.setMicrophonePresenceEnabled(checked)
                            }

                            Label {
                                Layout.fillWidth: true
                                text: qsTr("The microphone is analyzed only. It is never played through the speakers.")
                                color: Theme.NCTheme.textMuted
                                font.pixelSize: Theme.NCTypography.microSize
                                wrapMode: Text.Wrap
                            }

                            Label {
                                Layout.fillWidth: true
                                text: root.bridge.audioControls.statusMessage
                                color: Theme.NCTheme.textSecondary
                                font.pixelSize: Theme.NCTypography.microSize
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                }
            }

            Item { Layout.fillWidth: true }

            NCButton {
                id: noteModeButton
                visible: root.uiReviewNotesVisible
                compact: true
                text: root.bridge.uiReviewNotes.active ? qsTr("Note mode on") : qsTr("Note mode")
                iconText: "✎"
                tone: root.bridge.uiReviewNotes.active ? "warning" : "secondary"
                toolTipText: root.bridge.uiReviewNotes.active
                             ? qsTr("UI Note Mode is active. Right-click a component to leave an instruction for Codex.")
                             : qsTr("Enable UI Note Mode")
                onClicked: root.bridge.uiReviewNotes.setActive(
                               !root.bridge.uiReviewNotes.active)
            }

            NCButton {
                id: reviewNotesButton
                visible: root.uiReviewNotesVisible
                compact: true
                text: qsTr("Notes %1").arg(root.bridge.uiReviewNotes.openCount)
                tone: root.bridge.uiReviewNotes.openCount > 0 ? "warning" : "secondary"
                toolTipText: qsTr("Open UI review notes")
                onClicked: uiReviewOverlay.openNotes()
            }

            RowLayout {
                id: runtimeStackLabels
                objectName: "runtimeStackLabels"
                visible: root.width >= 1280
                         && headerContent.width
                            >= applicationHeader.runtimeStackRequiredWidth
                spacing: Theme.NCMetrics.space6

                Repeater {
                    model: root.bridge.activeRuntimeStack

                    delegate: NCStatusChip {
                        required property var modelData
                        text: String(modelData.label) + " · " + String(modelData.value)
                        status: String(modelData.status)
                        compact: true
                    }
                }
            }

        }

        RowLayout {
            id: runtimeSessionControl
            objectName: "runtimeSessionControl"
            anchors.right: parent.right
            anchors.rightMargin: Theme.NCMetrics.space20
            anchors.verticalCenter: parent.verticalCenter
            z: 2
            spacing: Theme.NCMetrics.space12

            NCPowerControl {
                id: runtimeSessionButton
                objectName: "runtimeSessionButton"
                active: root.bridge.systemRunning
                cleanupPending: root.bridge.runtimeCleanupPending
                busy: root.bridge.runtimeInitializing || root.bridge.runtimeStopping
                cancellable: root.bridge.runtimeInitializing && !root.bridge.runtimeStopping
                cancelling: root.bridge.runtimeCancelling
                busyText: root.bridge.runtimeCancelling ? qsTr("Cancelling…")
                          : root.bridge.runtimeStopping ? qsTr("Stopping NC…") : qsTr("Initializing NC…")
                busyDescription: root.bridge.runtimeStopping ? qsTr("Please wait · releasing resources")
                                                             : qsTr("Please wait · loading your stack")
                glowEnabled: true
                showLabels: false
                compact: root.width < 1320
                onRestartRequested: {
                    if (!root.bridge.applicationClosing)
                        powerRestartDialog.open()
                }

                onClicked: {
                    if (root.bridge.runtimeInitializing || root.bridge.systemRunning || root.bridge.runtimeCleanupPending)
                        root.bridge.terminateSystem()
                    else
                        root.bridge.initializeSystem()
                }
            }
        }
    }

    NCMainDockSurface {
        id: mainDockSurface
        anchors.fill: parent
        anchors.margins: Theme.NCMetrics.space16
        bridge: root.bridge
    }

    NCTutorialOverlay {
        id: tutorialOverlay
        parent: root.header.parent
        anchors.fill: parent
        z: 80
        bridge: root.bridge
        hostWindow: root
    }

    NCUiReviewOverlay {
        id: uiReviewOverlay
        anchors.fill: parent
        controller: root.bridge.uiReviewNotes
        bridge: root.bridge
        windowObjectName: root.objectName
        workspaceKey: root.bridge.currentWorkspace
        drawerEnabled: root.uiReviewNotesVisible
        onNavigateRequested: function(note) {
            root.navigateToUiReviewNote(note)
        }
    }

    Component {
        id: floatingWorkspaceWindowComponent

        DetachedWorkspaceWindow {}
    }

    NCWelcomeHub {
        id: firstRunDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        bridge: root.bridge
        onWorkspaceRequested: function(workspaceKey) { root.activateWorkspace(workspaceKey) }
    }

    Connections {
        target: root.bridge

        function onThemeChanged() { root.syncAppearance() }

        function onWorkspaceLayoutChanged() {
            root.syncFloatingWindows()
        }

        function onTutorialStateChanged() {
            root.activateTutorialDestination()
        }

        function onWelcomeHubRequested() {
            firstRunDialog.open()
        }

        function onToggleMainWindowRequested() {
            if (root.orbMainWindowRaised
                    && root.visible
                    && root.visibility !== Window.Minimized) {
                root.orbMainWindowRaised = false
                root.showMinimized()
                return
            }
            root.orbMainWindowRaised = true
            root.showNormal()
            root.raise()
            root.requestActivate()
        }

        function onOrbWorkspaceActionRequested(workspaceKey, closeIfFloating) {
            const key = String(workspaceKey || "")
            if (key === "orb_watches") {
                root.bridge.openAddonWorkspaceSection("companion_orb_overlay_tab", "Overview")
                root.showNormal()
                root.raise()
                root.requestActivate()
                return
            }
            const host = root.bridge.workspaceHost(key)
            if (host === "main") {
                root.bridge.detachWorkspace(key)
                Qt.callLater(function() {
                    root.syncFloatingWindows()
                    root.activateWorkspace(key)
                })
                return
            }
            if (Boolean(closeIfFloating)) {
                root.bridge.dockWorkspaceToMain(key)
                return
            }
            root.syncFloatingWindows()
            root.activateWorkspace(key)
        }

        function onExternalAvatarFocusRequested(modeLabel) {
            externalAvatarReturnWindow.modeLabel = String(modeLabel || qsTr("Avatar"))
            root.hide()
            externalAvatarReturnWindow.show()
            externalAvatarReturnWindow.raise()
            externalAvatarReturnWindow.requestActivate()
        }
    }
}
