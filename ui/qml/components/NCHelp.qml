import QtQuick
import QtQuick.Controls

// Passive help: observes pointer movement without taking clicks from the editor.
Item {
    id: root
    required property Item target
    property Item focusTarget: target
    property string text: ""
    property bool keyboardHelp: false
    property bool hoverHelp: false
    // Controls and editor Loaders are focus scopes. Avoid subscribing to the
    // window's entire changing parent chain while a workspace is being destroyed.
    readonly property bool focusWithin: focusTarget ? focusTarget.activeFocus : false
    onFocusWithinChanged: if (!focusWithin) keyboardHelp = false
    readonly property Item hoverParent: {
        let item = target.parent
        while (item && !item.enabled) item = item.parent
        return item
    }
    readonly property bool pointerInside: {
        if (!target.visible || !hoverParent || !helpHover.hovered || !text.length) return false
        let point = target.mapFromItem(hoverParent, helpHover.point.position.x, helpHover.point.position.y)
        if (point.x < 0 || point.y < 0 || point.x >= target.width || point.y >= target.height) return false
        let item = target.parent
        while (item) {
            if (item.clip) {
                point = item.mapFromItem(hoverParent, helpHover.point.position.x, helpHover.point.position.y)
                if (point.x < 0 || point.y < 0 || point.x >= item.width || point.y >= item.height) return false
            }
            if (item === hoverParent) break
            item = item.parent
        }
        return true
    }
    onPointerInsideChanged: {
        if (pointerInside) { hideTimer.stop(); hoverHelp = true }
        else hideTimer.restart()
    }
    HoverHandler {
        id: helpHover
        parent: root.hoverParent
        enabled: root.text.length > 0 && root.target.visible
    }
    Timer {
        id: hideTimer
        interval: 200
        onTriggered: {
            if (helpPopup.hovered) restart()
            else root.hoverHelp = false
        }
    }
    Shortcut {
        sequence: "F1"
        enabled: root.text.length > 0 && root.focusWithin
        context: Qt.WindowShortcut
        onActivated: root.keyboardHelp = !root.keyboardHelp
    }
    Shortcut {
        sequence: "PgDown"
        enabled: root.keyboardHelp && root.focusWithin
        context: Qt.WindowShortcut
        onActivated: helpPopup.scrollPage(1)
    }
    Shortcut {
        sequence: "PgUp"
        enabled: root.keyboardHelp && root.focusWithin
        context: Qt.WindowShortcut
        onActivated: helpPopup.scrollPage(-1)
    }
    NCToolTip {
        id: helpPopup
        objectName: "settingHelpPopup"
        parent: root.target
        visible: root.target.visible && root.text.length > 0 && (root.hoverHelp || root.keyboardHelp)
        text: root.text
        timeout: root.keyboardHelp ? -1 : 12000
        onClosed: root.keyboardHelp = false
    }
}
