import QtQuick
import QtQuick.Controls

// Only main settings scroll views opt in. Does not retain pages or follow log tails.
QtObject {
    id: root
    required property var bridge
    required property var scrollView
    required property string pageKey
    readonly property var flickable: scrollView ? scrollView.contentItem : null
    property bool ready: false
    property bool applying: false
    property real wantedPosition: 0
    property string activeKey: ""

    function restorePage() {
        if (!ready)
            return
        activeKey = pageKey
        wantedPosition = typeof bridge.settingsScrollPosition === "function"
                         ? bridge.settingsScrollPosition(activeKey) : 0
        restoreTimer.restart()
    }

    function restorePosition() {
        if (!flickable || flickable.height <= 0 || !scrollView.visible)
            return
        const maximum = Math.max(0, flickable.contentHeight - flickable.height)
        applying = true
        flickable.contentY = Math.min(wantedPosition, maximum)
        applying = false
        // Keep wantedPosition while late-loaded controls grow the page.
    }

    function rememberPosition() {
        if (!ready || applying || restoreTimer.running || activeKey !== pageKey
                || !flickable || !scrollView.visible)
            return
        const maximum = Math.max(0, flickable.contentHeight - flickable.height)
        // A shrinking layout can clamp the offset before its geometry signals arrive.
        // Keep the target in that case; an explicit gesture can still take control.
        if (wantedPosition > maximum && flickable.contentY >= maximum - 0.5)
            return
        wantedPosition = Math.max(0, Math.min(flickable.contentY, maximum))
        if (typeof bridge.rememberSettingsScrollPosition === "function")
            bridge.rememberSettingsScrollPosition(activeKey, wantedPosition)
    }

    function takeControl() {
        if (!ready || !flickable || !scrollView.visible || activeKey !== pageKey)
            return
        restoreTimer.stop()
        wantedPosition = Math.max(0, Math.min(flickable.contentY,
                                  Math.max(0, flickable.contentHeight - flickable.height)))
        if (typeof bridge.rememberSettingsScrollPosition === "function")
            bridge.rememberSettingsScrollPosition(activeKey, wantedPosition)
    }

    onPageKeyChanged: restorePage()
    onFlickableChanged: restorePage()
    Component.onCompleted: { ready = true; restorePage() }

    property Timer restoreTimer: Timer {
        interval: 0
        onTriggered: root.restorePosition()
    }
    property Connections scrollConnections: Connections {
        target: root.flickable
        function onMovementStarted() { root.takeControl() }
        function onContentYChanged() {
            root.rememberPosition()
        }
        function onContentHeightChanged() {
            root.restoreTimer.restart()
        }
        function onHeightChanged() {
            root.restoreTimer.restart()
        }
    }
    property Connections scrollbarConnections: Connections {
        target: root.scrollView ? root.scrollView.ScrollBar.vertical : null
        function onPressedChanged() { if (target.pressed) root.takeControl() }
    }
    property Connections visibilityConnections: Connections {
        target: root.scrollView
        function onVisibleChanged() { if (root.scrollView.visible) root.restorePage() }
    }
}
