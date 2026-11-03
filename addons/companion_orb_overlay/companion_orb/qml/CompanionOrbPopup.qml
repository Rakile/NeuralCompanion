import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../../ui/qml/components"
import "../../../../ui/qml/theme" as Theme

Rectangle {
    id: root
    objectName: "companionOrbPopupRoot"

    property bool menuMode: orbPopupBridge.mode === "menu"
    property bool compactMenu: menuMode && orbPopupBridge.compactMode
    property bool compactPersonaOpen: false
    property bool guidedPersonaOpen: false
    property color cyan: Theme.NCTheme.accent
    property color violet: Theme.NCTheme.accentStrong
    property color amber: Theme.NCTheme.warning

    function ncStateColor() {
        if (orbPopupBridge.runtimeFault)
            return Theme.NCTheme.error
        if (!orbPopupBridge.runtimeRunning)
            return Theme.NCTheme.textMuted
        if (orbPopupBridge.aiState === "listening")
            return "#60a5fa"
        if (orbPopupBridge.aiState === "thinking")
            return orbPopupBridge.thinkingColor
        if (orbPopupBridge.aiState === "speaking")
            return orbPopupBridge.speakingColor
        return orbPopupBridge.idleColor
    }

    width: menuMode
        ? (compactMenu ? (compactPersonaOpen ? 382 : 92) : orbPopupBridge.menuWidth)
        : 410
    height: menuMode
        ? Math.min(780, Math.max(470, 176 + Math.max(
            actionRailColumn.implicitHeight,
            guidedMenu.contentHeight
        )))
        : inputColumn.implicitHeight + 24
    radius: 24
    color: Theme.NCTheme.window
    border.width: compactMenu ? 0 : 1
    border.color: Theme.NCTheme.borderStrong
    clip: true
    antialiasing: true

    Connections {
        target: orbPopupBridge
        function onChanged() {
            Theme.NCTheme.applyPreset(orbPopupBridge.themePreset)
            root.compactPersonaOpen = false
            if (orbPopupBridge.compactMode)
                root.guidedPersonaOpen = false
        }
    }

    Component.onCompleted: Theme.NCTheme.applyPreset(
        orbPopupBridge.themePreset
    )

    Timer {
        interval: 400
        repeat: true
        running: root.menuMode
        onTriggered: orbPopupBridge.refreshRuntimeState()
    }

    component ActionIcon: Canvas {
        id: iconCanvas
        property string iconName: "chat"
        property color strokeColor: root.cyan
        antialiasing: true
        onIconNameChanged: requestPaint()
        onStrokeColorChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d")
            const s = Math.min(width, height)
            ctx.reset()
            ctx.strokeStyle = strokeColor
            ctx.fillStyle = strokeColor
            ctx.lineWidth = Math.max(1.5, s * 0.075)
            ctx.lineCap = "round"
            ctx.lineJoin = "round"

            function line(x1, y1, x2, y2) {
                ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke()
            }
            function selectionCorners() {
                line(s * .16, s * .36, s * .16, s * .16)
                line(s * .16, s * .16, s * .36, s * .16)
                line(s * .64, s * .16, s * .84, s * .16)
                line(s * .84, s * .16, s * .84, s * .36)
                line(s * .16, s * .64, s * .16, s * .84)
                line(s * .16, s * .84, s * .36, s * .84)
                line(s * .64, s * .84, s * .84, s * .84)
                line(s * .84, s * .64, s * .84, s * .84)
            }
            function bubble(x, y, bw, bh) {
                ctx.beginPath()
                ctx.roundedRect(x, y, bw, bh, s * .08, s * .08)
                ctx.stroke()
                line(x + bw * .28, y + bh, x + bw * .18, y + bh + s * .12)
            }

            if (iconName === "close") {
                line(s * .25, s * .25, s * .75, s * .75)
                line(s * .75, s * .25, s * .25, s * .75)
            } else if (iconName === "collapse") {
                line(s * .62, s * .22, s * .34, s * .50)
                line(s * .34, s * .50, s * .62, s * .78)
            } else if (iconName === "expand") {
                line(s * .38, s * .22, s * .66, s * .50)
                line(s * .66, s * .50, s * .38, s * .78)
            } else if (iconName === "power") {
                line(s * .50, s * .12, s * .50, s * .48)
                ctx.beginPath()
                ctx.arc(s * .50, s * .54, s * .34, -Math.PI * .72, Math.PI * .72)
                ctx.stroke()
            } else if (iconName === "pin") {
                ctx.beginPath()
                ctx.moveTo(s * .34, s * .16)
                ctx.lineTo(s * .70, s * .16)
                ctx.lineTo(s * .63, s * .37)
                ctx.lineTo(s * .74, s * .50)
                ctx.lineTo(s * .28, s * .50)
                ctx.lineTo(s * .39, s * .37)
                ctx.closePath()
                ctx.stroke()
                line(s * .51, s * .50, s * .51, s * .86)
            } else if (iconName === "conversation_window") {
                ctx.beginPath()
                ctx.roundedRect(s * .12, s * .17, s * .76, s * .66, s * .08, s * .08)
                ctx.stroke()
                line(s * .12, s * .34, s * .88, s * .34)
                bubble(s * .29, s * .46, s * .43, s * .23)
            } else if (iconName === "musetalk_window") {
                ctx.beginPath()
                ctx.roundedRect(s * .12, s * .17, s * .76, s * .66, s * .08, s * .08)
                ctx.stroke()
                line(s * .12, s * .34, s * .88, s * .34)
                ctx.beginPath(); ctx.arc(s * .50, s * .49, s * .10, 0, Math.PI * 2); ctx.stroke()
                ctx.beginPath(); ctx.arc(s * .50, s * .76, s * .20, Math.PI * 1.15, Math.PI * 1.85); ctx.stroke()
            } else if (iconName === "chat") {
                bubble(s * .14, s * .20, s * .72, s * .50)
                line(s * .31, s * .39, s * .69, s * .39)
                line(s * .31, s * .52, s * .58, s * .52)
            } else if (iconName === "persona") {
                ctx.beginPath(); ctx.arc(s * .50, s * .34, s * .17, 0, Math.PI * 2); ctx.stroke()
                ctx.beginPath(); ctx.arc(s * .50, s * .91, s * .34, Math.PI * 1.13, Math.PI * 1.87); ctx.stroke()
            } else if (iconName === "clipboard") {
                ctx.strokeRect(s * .23, s * .20, s * .54, s * .66)
                ctx.beginPath(); ctx.roundedRect(s * .35, s * .12, s * .30, s * .18, s * .05, s * .05); ctx.stroke()
                line(s * .34, s * .45, s * .66, s * .45)
                line(s * .34, s * .60, s * .62, s * .60)
            } else if (iconName === "region_size") {
                selectionCorners()
                ctx.strokeRect(s * .32, s * .36, s * .36, s * .28)
            } else if (iconName === "select_read") {
                selectionCorners()
                ctx.beginPath(); ctx.moveTo(s * .36, s * .49); ctx.lineTo(s * .48, s * .49); ctx.lineTo(s * .62, s * .37); ctx.lineTo(s * .62, s * .67); ctx.lineTo(s * .48, s * .55); ctx.lineTo(s * .36, s * .55); ctx.closePath(); ctx.stroke()
                ctx.beginPath(); ctx.arc(s * .60, s * .52, s * .19, -0.72, 0.72); ctx.stroke()
            } else if (iconName === "read_comment") {
                selectionCorners()
                bubble(s * .31, s * .34, s * .45, s * .32)
                line(s * .43, s * .50, s * .64, s * .50)
            } else if (iconName === "comment") {
                selectionCorners()
                bubble(s * .29, s * .34, s * .47, s * .32)
                line(s * .52, s * .41, s * .52, s * .59)
                line(s * .43, s * .50, s * .61, s * .50)
            } else {
                ctx.beginPath(); ctx.arc(s * .50, s * .50, s * .23, 0, Math.PI * 2); ctx.stroke()
            }
        }
    }

    component RailActionButton: Button {
        id: railButton
        objectName: "companionOrbRailActionButton"
        required property var actionData
        property bool selected: false
        property bool externalHovered: false
        readonly property bool visualHovered: hovered || externalHovered
        width: 48
        height: 48
        enabled: actionData.enabled === undefined || actionData.enabled
        flat: true
        hoverEnabled: true
        scale: pressed ? 0.96 : visualHovered ? 1.04 : 1.0
        Behavior on scale {
            enabled: !orbPopupBridge.reducedEffects
            NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
        }
        function pulse() {
            if (!orbPopupBridge.reducedEffects)
                actionRipple.restart()
        }
        contentItem: ActionIcon {
            width: 24
            height: 24
            iconName: String(railButton.actionData.icon || "")
            strokeColor: railButton.visualHovered ? root.amber
                : railButton.selected ? Theme.NCTheme.text : root.cyan
        }
        background: Rectangle {
            id: railButtonBackground
            radius: width / 2
            color: railButton.selected ? Theme.NCTheme.selection
                : railButton.visualHovered ? Theme.NCTheme.warningSoft
                : Theme.NCTheme.surfaceRaised
            border.width: railButton.visualHovered || railButton.selected ? 2 : 1
            border.color: railButton.visualHovered ? root.amber
                : railButton.selected ? root.cyan : Theme.NCTheme.borderStrong
            Behavior on color {
                enabled: !orbPopupBridge.reducedEffects
                ColorAnimation { duration: 100 }
            }
            Behavior on border.color {
                enabled: !orbPopupBridge.reducedEffects
                ColorAnimation { duration: 100 }
            }
            Rectangle {
                anchors.fill: parent
                anchors.margins: -2
                radius: width / 2
                color: "transparent"
                border.width: railButton.visualHovered ? 3 : 0
                border.color: Theme.NCTheme.withAlpha(root.amber, 0.22)
            }
            Rectangle {
                id: railRipple
                anchors.centerIn: parent
                width: parent.width
                height: width
                radius: width / 2
                color: root.cyan
                opacity: 0
                scale: 0.35
            }
            ParallelAnimation {
                id: actionRipple
                NumberAnimation { target: railRipple; property: "opacity"; from: 0.30; to: 0; duration: 260 }
                NumberAnimation { target: railRipple; property: "scale"; from: 0.35; to: 1.12; duration: 260; easing.type: Easing.OutCubic }
            }
        }
        NCToolTip {
            visible: railButton.hovered && root.compactMenu
            delay: 300
            maximumWidth: 240
            text: String(railButton.actionData.label || "")
        }
    }

    component WorkspaceClickArea: MouseArea {
        required property string workspaceKey
        required property string actionLabel
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        preventStealing: true

        function dispatch(closeIfFloating) {
            orbPopupBridge.activateWorkspace(
                workspaceKey,
                Boolean(closeIfFloating)
            )
            orbPopupBridge.dismissAfterAction()
        }

        Timer {
            id: singleClickTimer
            interval: Qt.styleHints.mouseDoubleClickInterval
            repeat: false
            onTriggered: parent.dispatch(false)
        }

        NCToolTip {
            visible: parent.containsMouse && root.compactMenu
            delay: 300
            maximumWidth: 240
            text: parent.actionLabel
        }

        onClicked: {
            if (!singleClickTimer.running)
                singleClickTimer.start()
        }
        onDoubleClicked: {
            singleClickTimer.stop()
            dispatch(true)
        }
    }

    Item {
        id: menuSurface
        anchors.fill: parent
        visible: root.menuMode

        Rectangle {
            id: edgeCurrent
            objectName: "companionOrbPopupEdgeCurrent"
            anchors.fill: parent
            anchors.margins: 1
            radius: Math.max(0, root.radius - 1)
            color: "transparent"
            border.width: 1
            border.color: root.cyan
            opacity: orbPopupBridge.pinned ? 0.72 : 0.38
            z: 20
            SequentialAnimation on border.color {
                running: root.menuMode && !orbPopupBridge.reducedEffects
                loops: Animation.Infinite
                ColorAnimation { to: root.amber; duration: 1500; easing.type: Easing.InOutSine }
                ColorAnimation { to: root.cyan; duration: 1500; easing.type: Easing.InOutSine }
            }
        }

        MouseArea {
            id: resizeHandle
            objectName: "companionOrbPopupResizeHandle"
            visible: root.menuMode && !root.compactMenu
            enabled: visible
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 6
            z: 40
            hoverEnabled: true
            cursorShape: Qt.SizeHorCursor
            preventStealing: true
            onPressed: orbPopupBridge.beginMenuResize()
            onPositionChanged: if (pressed) orbPopupBridge.updateMenuResize()
            onReleased: orbPopupBridge.endMenuResize()
            onCanceled: orbPopupBridge.endMenuResize()
        }

        Rectangle {
            id: actionRail
            objectName: "companionOrbActionRail"
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 92
            radius: root.radius
            color: Theme.NCTheme.windowRaised
            border.width: 1
            border.color: Theme.NCTheme.borderStrong
            antialiasing: true

            Rectangle {
                id: orbMark
                objectName: "companionOrbPopupOrbMark"
                anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 36 }
                width: 62
                height: 62
                radius: 31
                color: Theme.NCTheme.surfaceRaised
                border.width: 2
                border.color: root.cyan

                Rectangle {
                    id: orbCore
                    objectName: "companionOrbPopupOrbCore"
                    anchors.centerIn: parent
                    width: 42
                    height: 42
                    radius: 21
                    color: root.ncStateColor()
                    border.width: 2
                    border.color: Qt.lighter(root.ncStateColor(), 1.28)
                    Behavior on color {
                        enabled: !orbPopupBridge.reducedEffects
                        ColorAnimation { duration: 180; easing.type: Easing.InOutSine }
                    }
                    Behavior on border.color {
                        enabled: !orbPopupBridge.reducedEffects
                        ColorAnimation { duration: 180; easing.type: Easing.InOutSine }
                    }

                    MouseArea {
                        objectName: "companionOrbPopupDragHandle"
                        anchors.fill: parent
                        hoverEnabled: true
                        property real pressX: 0
                        property real pressY: 0
                        property bool dragStarted: false
                        cursorShape: pressed
                            ? Qt.ClosedHandCursor
                            : Qt.OpenHandCursor
                        onPressed: function(mouse) {
                            pressX = mouse.x
                            pressY = mouse.y
                            dragStarted = false
                        }
                        onPositionChanged: function(mouse) {
                            if (!pressed || dragStarted)
                                return
                            const dx = mouse.x - pressX
                            const dy = mouse.y - pressY
                            if (Math.sqrt(dx * dx + dy * dy) < 6)
                                return
                            dragStarted = true
                            orbPopupBridge.startWindowDrag()
                        }
                        onReleased: dragStarted = false
                        onCanceled: dragStarted = false
                        onDoubleClicked: function(mouse) {
                            if (!dragStarted)
                                orbPopupBridge.toggleMainWindow()
                            mouse.accepted = true
                        }
                    }
                }

                Item {
                    anchors.fill: parent
                    width: 6
                    height: 6
                    Rectangle {
                        width: 6
                        height: 6
                        radius: 3
                        color: root.amber
                        x: parent.width / 2 - width / 2
                        y: -2
                    }
                    NumberAnimation on rotation {
                        running: !orbPopupBridge.reducedEffects
                        from: 0
                        to: 360
                        duration: 3200
                        loops: Animation.Infinite
                    }
                }
            }

            ToolButton {
                id: pinButton
                objectName: "companionOrbPopupPinButton"
                anchors { left: parent.left; top: parent.top; margins: 5 }
                width: 24
                height: 24
                flat: true
                hoverEnabled: true
                onClicked: orbPopupBridge.togglePinned()
                contentItem: ActionIcon {
                    width: 13
                    height: 13
                    iconName: "pin"
                    strokeColor: orbPopupBridge.pinned
                        ? root.amber
                        : parent.hovered ? root.amber : Theme.NCTheme.textMuted
                }
                background: Rectangle {
                    radius: 8
                    color: parent.hovered
                        ? Theme.NCTheme.warningSoft
                        : orbPopupBridge.pinned ? Theme.NCTheme.surfaceSelected
                        : "transparent"
                    border.width: parent.hovered || orbPopupBridge.pinned ? 1 : 0
                    border.color: root.amber
                }
                NCToolTip {
                    visible: parent.hovered
                    text: orbPopupBridge.pinned
                        ? "Unpin the action rail"
                        : "Pin the action rail on top"
                }
            }

            ToolButton {
                objectName: "companionOrbPopupMenuCloseButton"
                anchors { right: parent.right; top: parent.top; margins: 5 }
                width: 24
                height: 24
                flat: true
                onClicked: orbPopupBridge.close()
                contentItem: ActionIcon {
                    width: 12
                    height: 12
                    iconName: "close"
                    strokeColor: parent.hovered ? root.amber : Theme.NCTheme.textMuted
                }
                background: Rectangle { radius: 8; color: parent.hovered ? Theme.NCTheme.warningSoft : "transparent"; border.width: parent.hovered ? 1 : 0; border.color: root.amber }
                NCToolTip {
                    visible: parent.hovered
                    text: orbPopupBridge.pinned
                        ? "Unpin and close menu"
                        : "Close menu"
                }
            }

            Column {
                id: actionRailColumn
                objectName: "companionOrbActionRailItems"
                anchors { top: orbMark.bottom; topMargin: 12; horizontalCenter: parent.horizontalCenter }
                spacing: 7

                Repeater {
                    model: orbPopupBridge.items
                    delegate: Item {
                        required property var modelData
                        objectName: String(modelData.kind || "") === "separator"
                            ? "companionOrbRailSeparator"
                            : "companionOrbRailActionButton"
                        width: 48
                        height: String(modelData.kind || "") === "separator" ? 8 : 48
                        visible: height > 8

                        RailActionButton {
                            id: railActionButton
                            anchors.fill: parent
                            actionData: modelData
                            externalHovered: railWorkspaceArea.containsMouse
                            selected: String(modelData.id || "") === "persona"
                                && (root.compactPersonaOpen || root.guidedPersonaOpen)
                            onClicked: {
                                if (String(modelData.id || "").indexOf("workspace:") === 0)
                                    return
                                const hasChildren = modelData.children !== undefined
                                    && modelData.children !== null
                                    && modelData.children.length > 0
                                if (hasChildren) {
                                    if (root.compactMenu)
                                        root.compactPersonaOpen = !root.compactPersonaOpen
                                    else
                                        root.guidedPersonaOpen = !root.guidedPersonaOpen
                                } else {
                                    pulse()
                                    orbPopupBridge.dismissAfterAction()
                                    orbPopupBridge.activate(String(modelData.id))
                                }
                            }
                        }
                        WorkspaceClickArea {
                            id: railWorkspaceArea
                            anchors.fill: parent
                            visible: String(modelData.id || "").indexOf("workspace:") === 0
                            enabled: visible
                            workspaceKey: String(modelData.id || "").substring(10)
                            actionLabel: String(modelData.label || "")
                        }
                    }
                }
            }

            ToolButton {
                id: modeButton
                objectName: "companionOrbPopupModeButton"
                anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 12 }
                width: 42
                height: 42
                flat: true
                hoverEnabled: true
                enabled: !orbPopupBridge.pinned
                onClicked: orbPopupBridge.toggleCompactMode()
                contentItem: ActionIcon {
                    width: 16
                    height: 16
                    iconName: root.compactMenu ? "expand" : "collapse"
                    strokeColor: parent.hovered ? root.amber : root.cyan
                }
                background: Rectangle {
                    radius: width / 2
                    color: parent.pressed
                        ? Theme.NCTheme.surfacePressed
                        : parent.hovered ? Theme.NCTheme.warningSoft
                        : Theme.NCTheme.surfaceRaised
                    border.width: parent.hovered ? 2 : 1
                    border.color: parent.hovered ? root.amber : Theme.NCTheme.borderStrong
                    antialiasing: true
                }
                NCToolTip {
                    visible: parent.hovered
                    text: root.compactMenu
                        ? (orbPopupBridge.pinned
                            ? "Unpin to show action labels"
                            : "Show action labels")
                        : "Use icon rail only"
                }
            }
        }

        Item {
            id: guidedPanel
            objectName: "companionOrbGuidedPanel"
            visible: !root.compactMenu
            anchors { left: actionRail.right; right: parent.right; top: parent.top; bottom: parent.bottom }

            Column {
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
                spacing: 2
                RowLayout {
                    width: parent.width
                    spacing: 7
                    Label {
                        Layout.fillWidth: true
                        text: orbPopupBridge.title
                        color: Theme.NCTheme.text
                        font.pixelSize: 18
                        font.bold: true
                    }
                    ToolButton {
                        id: initializeButton
                        objectName: "companionOrbInitializeButton"
                        Layout.preferredWidth: 76
                        Layout.preferredHeight: 34
                        Layout.minimumWidth: 76
                        Layout.maximumWidth: 76
                        Layout.minimumHeight: 34
                        Layout.maximumHeight: 34
                        padding: 0
                        flat: true
                        hoverEnabled: true
                        enabled: !orbPopupBridge.runtimeStarting
                        onClicked: orbPopupBridge.toggleRuntime()
                        contentItem: Item {
                            Text {
                                id: powerToggleLabel
                                objectName: "companionOrbPowerToggleLabel"
                                text: orbPopupBridge.runtimeRunning ? "ON" : "OFF"
                                anchors.verticalCenter: parent.verticalCenter
                                x: orbPopupBridge.runtimeRunning ? 11 : parent.width - width - 10
                                color: orbPopupBridge.runtimeRunning
                                    ? "#06291f"
                                    : Theme.NCTheme.text
                                font.pixelSize: 12
                                font.bold: true
                            }
                            Rectangle {
                                id: powerToggleKnob
                                objectName: "companionOrbPowerToggleKnob"
                                width: 24
                                height: 24
                                radius: 12
                                y: 5
                                x: orbPopupBridge.runtimeRunning
                                    ? parent.width - width - 5
                                    : 5
                                color: "#f8fafc"
                                border.width: 1
                                border.color: Theme.NCTheme.withAlpha("#07111d", 0.18)
                                Behavior on x {
                                    enabled: !orbPopupBridge.reducedEffects
                                    NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
                                }
                            }
                            opacity: orbPopupBridge.runtimeStarting ? 0.55 : 1.0
                            SequentialAnimation on opacity {
                                running: orbPopupBridge.runtimeStarting
                                    && !orbPopupBridge.reducedEffects
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.35; duration: 420 }
                                NumberAnimation { to: 1.0; duration: 420 }
                            }
                        }
                        background: Rectangle {
                            radius: height / 2
                            color: orbPopupBridge.runtimeFault
                                ? Theme.NCTheme.errorSoft
                                : orbPopupBridge.runtimeRunning
                                  ? Theme.NCTheme.success
                                  : orbPopupBridge.runtimeStarting
                                    ? Theme.NCTheme.warningSoft
                                : initializeButton.hovered
                                ? Theme.NCTheme.warningSoft
                                : Theme.NCTheme.surfaceRaised
                            border.width: 2
                            border.color: orbPopupBridge.runtimeFault
                                ? Theme.NCTheme.error
                                : orbPopupBridge.runtimeRunning
                                  ? Theme.NCTheme.success
                                  : orbPopupBridge.runtimeStarting
                                    ? root.amber
                                : initializeButton.hovered
                                  ? root.amber
                                  : Theme.NCTheme.borderStrong
                            Behavior on color {
                                enabled: !orbPopupBridge.reducedEffects
                                ColorAnimation { duration: 150 }
                            }
                            Behavior on border.color {
                                enabled: !orbPopupBridge.reducedEffects
                                ColorAnimation { duration: 150 }
                            }
                        }
                        NCToolTip {
                            visible: parent.hovered
                            delay: 250
                            maximumWidth: 260
                            text: orbPopupBridge.runtimeFault
                                ? "Retry runtime cleanup"
                                : orbPopupBridge.runtimeRunning
                                  ? "Terminate NeuralCompanion"
                                : orbPopupBridge.runtimeStarting
                                  ? "NeuralCompanion is starting"
                                  : "Initialize NeuralCompanion"
                        }
                    }
                }
                Label { width: parent.width; text: "Choose an action"; color: Theme.NCTheme.textSecondary; font.pixelSize: 12 }
            }

            ListView {
                id: guidedMenu
                objectName: "companionOrbPopupMenu"
                anchors { left: parent.left; right: parent.right; top: parent.top; bottom: parent.bottom; leftMargin: 18; rightMargin: 18; topMargin: 110; bottomMargin: 18 }
                clip: true
                spacing: 5
                model: orbPopupBridge.items
                delegate: Item {
                    id: menuEntry
                    required property var modelData
                    width: guidedMenu.width
                    property bool isSeparator: String(modelData.kind || "") === "separator"
                    property bool hasChildren: modelData.children !== undefined && modelData.children !== null && modelData.children.length > 0
                    property bool expanded: hasChildren && root.guidedPersonaOpen
                    height: isSeparator ? 9 : primaryButton.height + (expanded ? childColumn.implicitHeight + 5 : 0)

                    Rectangle { visible: menuEntry.isSeparator; anchors.centerIn: parent; width: parent.width; height: 1; color: Theme.NCTheme.borderSubtle }

                    Button {
                        id: primaryButton
                        objectName: "companionOrbPopupItem"
                        visible: !menuEntry.isSeparator
                        width: parent.width
                        height: 48
                        enabled: modelData.enabled === undefined || modelData.enabled
                        flat: true
                        hoverEnabled: true
                        readonly property bool visualHovered: hovered
                            || guidedWorkspaceArea.containsMouse
                        contentItem: RowLayout {
                            spacing: 11
                            ActionIcon {
                                Layout.preferredWidth: 24
                                Layout.preferredHeight: 24
                                iconName: String(modelData.icon || "")
                                strokeColor: primaryButton.visualHovered ? root.amber : root.cyan
                            }
                            Text { Layout.fillWidth: true; text: String(modelData.label || ""); color: primaryButton.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted; font.pixelSize: 13; elide: Text.ElideRight }
                            Text { visible: String(modelData.detail || "").length > 0; text: String(modelData.detail || ""); color: Theme.NCTheme.textSecondary; font.pixelSize: 11; elide: Text.ElideRight; Layout.maximumWidth: 120 }
                            Text { visible: menuEntry.hasChildren; text: menuEntry.expanded ? "⌄" : "›"; color: root.cyan; font.pixelSize: 17 }
                        }
                        background: Rectangle {
                            radius: 13
                            color: primaryButton.visualHovered ? Theme.NCTheme.warningSoft
                                : menuEntry.expanded ? Theme.NCTheme.surfaceSelected : Theme.NCTheme.surface
                            border.width: primaryButton.visualHovered ? 2 : 1
                            border.color: primaryButton.visualHovered ? root.amber
                                : menuEntry.expanded ? root.cyan : Theme.NCTheme.border
                            Behavior on color {
                                enabled: !orbPopupBridge.reducedEffects
                                ColorAnimation { duration: 100 }
                            }
                            Behavior on border.color {
                                enabled: !orbPopupBridge.reducedEffects
                                ColorAnimation { duration: 100 }
                            }
                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: -2
                                radius: parent.radius + 2
                                color: "transparent"
                                border.width: primaryButton.visualHovered ? 3 : 0
                                border.color: Theme.NCTheme.withAlpha(root.amber, 0.20)
                            }
                        }
                        onClicked: {
                            if (String(modelData.id || "").indexOf("workspace:") === 0)
                                return
                            if (menuEntry.hasChildren)
                                root.guidedPersonaOpen = !root.guidedPersonaOpen
                            else {
                                orbPopupBridge.dismissAfterAction()
                                orbPopupBridge.activate(String(modelData.id))
                            }
                        }
                    }

                    WorkspaceClickArea {
                        id: guidedWorkspaceArea
                        anchors.fill: primaryButton
                        visible: !menuEntry.isSeparator
                            && String(modelData.id || "").indexOf("workspace:") === 0
                        enabled: visible
                        workspaceKey: String(modelData.id || "").substring(10)
                        actionLabel: String(modelData.label || "")
                    }

                    Column {
                        id: childColumn
                        visible: menuEntry.expanded
                        x: 14
                        y: primaryButton.height + 5
                        width: parent.width - x
                        spacing: 4

                        Repeater {
                            model: menuEntry.hasChildren ? modelData.children : []
                            delegate: Button {
                                id: personaButton
                                required property var modelData
                                width: childColumn.width
                                height: 44
                                enabled: modelData.enabled === undefined || modelData.enabled
                                flat: true
                                contentItem: RowLayout {
                                    spacing: 8
                                    Rectangle {
                                        Layout.preferredWidth: 30; Layout.preferredHeight: 30; radius: 10; color: Theme.NCTheme.windowRaised; border.width: 1; border.color: Theme.NCTheme.borderStrong
                                        Image { anchors.fill: parent; anchors.margins: 2; source: String(modelData.avatarSource || ""); fillMode: Image.PreserveAspectFit; asynchronous: true; visible: source.toString().length > 0 }
                                        ActionIcon { anchors.centerIn: parent; width: 18; height: 18; visible: String(modelData.avatarSource || "").length === 0; iconName: "persona" }
                                    }
                                    Text { Layout.fillWidth: true; text: String(modelData.label || ""); color: personaButton.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted; font.pixelSize: 12; elide: Text.ElideRight }
                                    Text { visible: Boolean(modelData.checked); text: "✓"; color: Theme.NCTheme.success; font.pixelSize: 14 }
                                }
                                background: Rectangle {
                                    radius: 11
                                    color: Boolean(modelData.checked) ? Theme.NCTheme.selection : personaButton.hovered ? Theme.NCTheme.warningSoft : Theme.NCTheme.surface
                                    border.width: personaButton.hovered ? 2 : 1
                                    border.color: personaButton.hovered ? root.amber : Boolean(modelData.checked) ? root.cyan : Theme.NCTheme.border
                                }
                                onClicked: { orbPopupBridge.dismissAfterAction(); orbPopupBridge.activate(String(modelData.id)) }
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            id: compactPersonaPanel
            visible: root.compactMenu && root.compactPersonaOpen
            anchors { left: actionRail.right; right: parent.right; top: parent.top; bottom: parent.bottom; margins: 10 }
            radius: 16
            color: Theme.NCTheme.surface
            border.width: 1
            border.color: root.violet

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; text: "Choose persona"; color: Theme.NCTheme.text; font.bold: true }
                    ToolButton {
                        flat: true
                        onClicked: root.compactPersonaOpen = false
                        contentItem: ActionIcon { width: 14; height: 14; iconName: "close"; strokeColor: parent.hovered ? Theme.NCTheme.text : Theme.NCTheme.textSecondary }
                    }
                }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 5
                    model: {
                        for (let index = 0; index < orbPopupBridge.items.length; ++index) {
                            const item = orbPopupBridge.items[index]
                            if (String(item.id || "") === "persona")
                                return item.children || []
                        }
                        return []
                    }
                    delegate: Button {
                        required property var modelData
                        width: ListView.view.width
                        height: 44
                        flat: true
                        enabled: modelData.enabled === undefined || modelData.enabled
                        text: String(modelData.label || "")
                        onClicked: { orbPopupBridge.dismissAfterAction(); orbPopupBridge.activate(String(modelData.id)) }
                        background: Rectangle { radius: 11; color: Boolean(modelData.checked) ? Theme.NCTheme.selection : parent.hovered ? Theme.NCTheme.warningSoft : Theme.NCTheme.surface; border.width: parent.hovered ? 2 : 1; border.color: parent.hovered ? root.amber : Boolean(modelData.checked) ? root.cyan : Theme.NCTheme.border }
                        contentItem: Text { text: parent.text + (Boolean(modelData.checked) ? "  ✓" : ""); color: parent.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                    }
                }
            }
        }
    }

    ColumnLayout {
        id: inputColumn
        visible: !root.menuMode
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
        spacing: 9

        RowLayout {
            Layout.fillWidth: true
            Label { Layout.fillWidth: true; text: orbPopupBridge.title; color: Theme.NCTheme.text; font.pixelSize: 14; font.bold: true; wrapMode: Text.Wrap }
            ToolButton {
                objectName: "companionOrbPopupCloseButton"
                flat: true
                onClicked: orbPopupBridge.close()
                contentItem: ActionIcon { width: 14; height: 14; iconName: "close"; strokeColor: parent.hovered ? Theme.NCTheme.text : Theme.NCTheme.textSecondary }
                NCToolTip {
                    visible: parent.hovered
                    text: "Close menu"
                }
            }
        }

        NCTextField {
            id: messageInput
            toolTipText: qsTr("Enter a request for the current Orb menu action. Enter or Send submits the text; Close dismisses the menu.")
            Layout.fillWidth: true
            placeholderText: orbPopupBridge.placeholder
            selectByMouse: true
            onAccepted: orbPopupBridge.submit(text)
            Component.onCompleted: if (visible) forceActiveFocus()
            onVisibleChanged: if (visible) { text = ""; forceActiveFocus() }
        }

        Label { visible: text.length > 0; Layout.fillWidth: true; text: orbPopupBridge.status; color: Theme.NCTheme.textSecondary; wrapMode: Text.Wrap }

        RowLayout {
            Layout.alignment: Qt.AlignRight
            Button { text: "Close"; onClicked: orbPopupBridge.close() }
            Button { text: "Send"; highlighted: true; onClicked: orbPopupBridge.submit(messageInput.text) }
        }
    }
}
