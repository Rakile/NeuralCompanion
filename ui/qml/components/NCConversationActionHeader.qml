pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../theme" as Theme

Item {
    id: root

    property alias statusContent: statusSlot.data
    property alias trailingContent: trailingSlot.data
    default property alias actionContent: actionColumn.data
    property bool docked: false
    readonly property bool previewOpen: actionPopup.visible
    // Includes menus/dialogs launched from actions, whose pointer may leave this surface.
    property bool interactionActive: false
    property bool suppressKeyboardPreview: false

    implicitWidth: 390
    implicitHeight: primary.implicitHeight + (docked ? actionsSurface.implicitHeight + Theme.NCMetrics.space8 : 0)

    function keyboardFocusInside() {
        if (railButton.visualFocus)
            return true
        let item = root.Window.window ? root.Window.window.activeFocusItem : null
        let visualFocus = false
        while (item) {
            visualFocus = visualFocus || Boolean(item.visualFocus)
            if (item === actionsSurface || item === trailingSlot)
                return visualFocus
            item = item.parent
        }
        return false
    }

    function scheduleDismiss() {
        openTimer.stop()
        if (!docked && previewOpen)
            closeTimer.restart()
    }

    function showPreview() {
        closeTimer.stop()
        if (!docked && visible && root.Window.window && !suppressKeyboardPreview)
            actionPopup.open()
    }

    function dismissPreview() {
        openTimer.stop()
        closeTimer.stop()
        actionPopup.close()
    }

    function toggleDocked() {
        dismissPreview()
        docked = !docked
    }

    function focusableItems(container) {
        const result = []
        function visit(item) {
            if (!item.visible || !item.enabled)
                return
            if (item.activeFocusOnTab) {
                result.push(item)
                return
            }
            for (let child of item.children)
                visit(child)
        }
        visit(container)
        return result
    }

    function moveActionFocus(backward) {
        const items = focusableItems(actionColumn)
        let index = items.findIndex(item => item.activeFocus)
        index += backward ? -1 : 1
        if (index >= 0 && index < items.length) {
            items[index].forceActiveFocus(backward ? Qt.BacktabFocusReason : Qt.TabFocusReason)
        } else if (backward) {
            const trailing = focusableItems(trailingSlot)
            if (trailing.length)
                trailing[trailing.length - 1].forceActiveFocus(Qt.BacktabFocusReason)
        } else {
            suppressKeyboardPreview = true
            dismissPreview()
            const status = focusableItems(statusSlot)
            ;(status.length ? status[0] : railButton).forceActiveFocus(Qt.TabFocusReason)
            Qt.callLater(function() { root.suppressKeyboardPreview = false })
        }
    }

    onVisibleChanged: if (!visible) dismissPreview()
    onInteractionActiveChanged: {
        if (interactionActive)
            closeTimer.stop()
        else
            scheduleDismiss()
    }
    Component.onDestruction: dismissPreview()

    GridLayout {
        id: primary
        width: root.width
        columns: root.width < root.implicitWidth ? 1 : 2
        columnSpacing: Theme.NCMetrics.space8
        rowSpacing: Theme.NCMetrics.space4

        Item {
            id: statusSlot
            Layout.fillWidth: true
            implicitWidth: childrenRect.width
            implicitHeight: childrenRect.height
        }

        RowLayout {
            id: trailingRow
            Layout.alignment: Qt.AlignRight
            spacing: Theme.NCMetrics.space8

            NCButton {
                id: railButton
                objectName: "conversationActionRailButton"
                text: root.docked ? qsTr("Hide docked actions")
                                  : root.previewOpen ? qsTr("Dock actions in the interface")
                                                     : qsTr("Show action popover; click to dock actions")
                iconOnly: true
                // Center the visible strokes independently of font ascent and baseline.
                contentItem: Item {
                    implicitWidth: 16
                    implicitHeight: 16

                    Rectangle {
                        anchors.centerIn: parent
                        width: 16
                        height: 2
                        radius: 1
                        color: railButton.foregroundColor()
                    }
                    Rectangle {
                        anchors.centerIn: parent
                        width: 2
                        height: 16
                        radius: 1
                        color: railButton.foregroundColor()
                        visible: !root.docked
                    }
                }
                compact: true
                checkable: false
                Accessible.checkable: true
                Accessible.checked: root.docked
                toolTipText: root.docked ? qsTr("Click to hide docked actions")
                                        : root.previewOpen ? qsTr("Click to dock actions")
                                                           : qsTr("Hover to show actions · Click to dock")
                onClicked: root.toggleDocked()
                onHoveredChanged: {
                    if (hovered) {
                        closeTimer.stop()
                        if (!root.docked)
                            openTimer.restart()
                    } else {
                        root.scheduleDismiss()
                    }
                }
                onVisualFocusChanged: {
                    if (visualFocus)
                        root.showPreview()
                    else
                        root.scheduleDismiss()
                }
            }

            Item {
                id: trailingSlot
                implicitWidth: childrenRect.width
                implicitHeight: childrenRect.height
            }
        }
    }

    Item {
        id: dockSlot
        width: root.width
        y: primary.height + Theme.NCMetrics.space8
        height: root.docked ? actionsSurface.implicitHeight : 0
        visible: root.docked
    }

    // Only the visual parent changes: handlers, settings bindings and object identity survive.
    Item {
        id: actionsSurface
        objectName: "conversationActionRailSurface"
        parent: root.docked ? dockSlot : actionPopup.contentItem
        width: parent ? parent.width : 0
        height: root.docked ? implicitHeight : actionPopup.availableHeight
        implicitHeight: actionColumn.implicitHeight + Theme.NCMetrics.space24
        visible: root.docked || root.previewOpen

        ScrollView {
            id: actionScroll
            anchors.fill: parent
            padding: Theme.NCMetrics.space12
            clip: true
            contentWidth: availableWidth
            contentHeight: actionColumn.implicitHeight
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                id: actionColumn
                width: actionScroll.availableWidth
                spacing: Theme.NCMetrics.space12
            }
        }

        HoverHandler {
            id: surfaceHover
            onHoveredChanged: {
                if (hovered)
                    closeTimer.stop()
                else
                    root.scheduleDismiss()
            }
        }
    }

    Popup {
        id: actionPopup
        objectName: "conversationActionRailPopup"
        parent: Overlay.overlay
        modal: false
        focus: false
        padding: 0
        closePolicy: Popup.NoAutoClose
        width: Math.max(0, Math.min(800, parent ? parent.width - Theme.NCMetrics.space16 : root.width))
        height: Math.max(0, Math.min(actionsSurface.implicitHeight,
                                   parent ? parent.height - y - Theme.NCMetrics.space8 : actionsSurface.implicitHeight))
        onAboutToShow: {
            // Map after layout: mapToItem bindings do not track ancestor movement.
            const right = root.mapToItem(parent, root.width, 0)
            const bottom = railButton.mapToItem(parent, 0, railButton.height)
            x = Math.max(0, Math.min(right.x - width, parent.width - width))
            y = Math.max(0, bottom.y + Theme.NCMetrics.space8)
        }
        background: Rectangle {
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.surface
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.borderStrong
        }
    }

    Timer {
        id: openTimer
        interval: 130
        onTriggered: if (railButton.hovered) root.showPreview()
    }
    Timer {
        id: closeTimer
        interval: 240
        onTriggered: {
            if (!root.docked && !railButton.hovered && !surfaceHover.hovered
                    && !root.interactionActive && !root.keyboardFocusInside())
                root.dismissPreview()
        }
    }

    Connections {
        target: root.Window.window
        function onActiveFocusItemChanged() { root.scheduleDismiss() }
    }
    // Floating Popup content is outside the normal visual focus chain.
    Shortcut {
        sequence: "Tab"
        enabled: root.visible && root.previewOpen && !root.interactionActive && root.keyboardFocusInside()
        onActivated: {
            if (railButton.activeFocus) {
                const items = root.focusableItems(trailingSlot)
                if (items.length)
                    items[0].forceActiveFocus(Qt.TabFocusReason)
            } else if (root.focusableItems(trailingSlot).some(item => item.activeFocus)) {
                const items = root.focusableItems(actionColumn)
                if (items.length)
                    items[0].forceActiveFocus(Qt.TabFocusReason)
            } else {
                root.moveActionFocus(false)
            }
        }
    }
    Shortcut {
        sequence: "Shift+Tab"
        enabled: root.visible && root.previewOpen && !root.interactionActive && root.keyboardFocusInside()
        onActivated: {
            if (root.focusableItems(trailingSlot).some(item => item.activeFocus))
                railButton.forceActiveFocus(Qt.BacktabFocusReason)
            else
                root.moveActionFocus(true)
        }
    }
    Shortcut {
        sequence: "Escape"
        enabled: root.visible && root.previewOpen && !root.interactionActive
        context: Qt.WindowShortcut
        onActivated: {
            root.suppressKeyboardPreview = true
            root.dismissPreview()
            railButton.forceActiveFocus(Qt.ShortcutFocusReason)
            Qt.callLater(function() { root.suppressKeyboardPreview = false })
        }
    }
}
