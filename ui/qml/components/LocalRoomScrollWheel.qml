import QtQuick

// An overflowing room panel owns its wheel gesture, including at either end.
WheelHandler {
    id: root
    required property Flickable viewport
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
    enabled: viewport.visible && viewport.interactive && viewport.contentHeight > viewport.height
    onWheel: function(event) {
        const delta = event.pixelDelta.y !== 0 ? event.pixelDelta.y : event.angleDelta.y / 120 * 42
        if (delta === 0) {
            event.accepted = false
            return
        }
        viewport.cancelFlick()
        const minimum = viewport.originY
        const maximum = minimum + Math.max(0, viewport.contentHeight - viewport.height)
        viewport.contentY = Math.max(minimum, Math.min(maximum, viewport.contentY - delta))
        event.accepted = true
    }
}
