pragma ComponentBehavior: Bound

import QtQuick

// Display-only crossfade. The incoming Image keeps following the existing
// playback clock; neither a fade nor an image load gates frame advancement.
Item {
    id: root
    property var previewState: ({})
    property real zoomFactor: 1.0
    property real panX: 0
    property real panY: 0
    clip: true
    readonly property url source: String(previewState.imageUrl || "")
    readonly property int status: current.status
    readonly property int fillMode: Image.PreserveAspectFit
    readonly property bool transitionRunning: fade.running
    property Image current: first
    property Image outgoing: second
    property string identity: ""
    property bool wasCreator: false
    property bool pendingFade: false
    property int fadeDuration: 0
    property real outgoingOpacity: 0

    function resetZoom() {
        zoomFactor = 1.0
        panX = 0
        panY = 0
    }

    MouseArea {
        anchors.fill: parent
        z: 2
        acceptedButtons: Qt.MiddleButton
        preventStealing: true
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.ArrowCursor
        property point lastPosition: Qt.point(0, 0)
        enabled: !root.previewState.creatorPreview && root.source.toString().length > 0
        onPressed: function(mouse) {
            lastPosition = Qt.point(mouse.x, mouse.y)
        }
        onPositionChanged: function(mouse) {
            if (pressed && (pressedButtons & Qt.MiddleButton)) {
                root.panX += mouse.x - lastPosition.x
                root.panY += mouse.y - lastPosition.y
                lastPosition = Qt.point(mouse.x, mouse.y)
            }
        }
        onWheel: function(event) {
            if (!(event.modifiers & Qt.AltModifier)) {
                event.accepted = false
                return
            }
            // Qt on Windows maps Alt + vertical wheel to the horizontal axis.
            // Read both axes without WheelHandler's orientation filtering.
            const angle = event.angleDelta.y || event.angleDelta.x
            const pixels = event.pixelDelta.y || event.pixelDelta.x
            const steps = angle !== 0 ? angle / 120 : pixels / 20
            if (steps === 0) {
                event.accepted = false
                return
            }
            const nextZoom = Math.max(0.25, Math.min(4.0, root.zoomFactor * Math.pow(1.1, steps)))
            const ratio = nextZoom / root.zoomFactor
            // Image scale is centered; offsets are in viewport pixels.
            // Keep the same image point underneath the wheel's position.
            root.panX = event.x - root.width / 2 - ratio * (event.x - root.width / 2 - root.panX)
            root.panY = event.y - root.height / 2 - ratio * (event.y - root.height / 2 - root.panY)
            root.zoomFactor = nextZoom
            event.accepted = true
        }
    }

    function finishFade() {
        pendingFade = false
        fade.stop()
        outgoingOpacity = 0
        outgoing.source = ""
    }

    function ready() {
        if (pendingFade && current.status === Image.Ready) {
            pendingFade = false
            fade.start()
        }
    }

    function updateFrame() {
        const url = String(previewState.imageUrl || "")
        const creator = !!previewState.creatorPreview
        if (creator)
            resetZoom()
        const loop = !!previewState.loop
        const paths = previewState.frame_paths || []
        const key = JSON.stringify([String(previewState.avatar_id || ""), loop,
                                    loop ? String(previewState.frame_dir || "") : "",
                                    loop ? String(previewState.chunk_id || "") : "",
                                    loop && paths.length ? String(paths[0]) : ""])
        const duration = Math.max(0, Number(previewState.loopFadeMs || 0))
        if (!url) {
            finishFade()
            current.source = ""
            identity = ""
            wasCreator = false
            return
        }
        if (creator || wasCreator || duration === 0)
            finishFade()
        if (identity && key !== identity && !creator && !wasCreator
                && duration > 0 && visible && current.lastReadySource.toString().length
                && (current.status === Image.Ready || current.status === Image.Loading)) {
            finishFade()
            const previous = current
            current = outgoing
            outgoing = previous
            // A retained frame is still visible while the next PNG decodes.
            // Cancel that pending decode so it cannot change the outgoing
            // image mid-fade. This reload is only needed at such a boundary.
            if (outgoing.status === Image.Loading)
                outgoing.source = outgoing.lastReadySource
            fadeDuration = duration
            outgoingOpacity = 1
            pendingFade = true
        }
        identity = key
        wasCreator = creator
        current.source = url
        ready()
    }

    onPreviewStateChanged: updateFrame()
    onVisibleChanged: { if (!visible) finishFade() }
    Component.onCompleted: updateFrame()

    NumberAnimation {
        id: fade
        target: root
        property: "outgoingOpacity"
        from: 1
        to: 0
        duration: root.fadeDuration
        onFinished: root.finishFade()
    }

    Image {
        id: first
        scale: root.zoomFactor
        property url lastReadySource: ""
        width: root.width
        height: root.height
        x: root.panX
        y: root.panY
        z: root.outgoing === first ? 1 : 0
        opacity: root.outgoing === first ? root.outgoingOpacity : 1
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        retainWhileLoading: true
        cache: false
        smooth: true
        onStatusChanged: {
            if (status === Image.Ready) lastReadySource = source
            else if (status === Image.Null) lastReadySource = ""
            root.ready()
        }
    }
    Image {
        id: second
        scale: root.zoomFactor
        property url lastReadySource: ""
        width: root.width
        height: root.height
        x: root.panX
        y: root.panY
        z: root.outgoing === second ? 1 : 0
        opacity: root.outgoing === second ? root.outgoingOpacity : 1
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        retainWhileLoading: true
        cache: false
        smooth: true
        onStatusChanged: {
            if (status === Image.Ready) lastReadySource = source
            else if (status === Image.Null) lastReadySource = ""
            root.ready()
        }
    }
}
