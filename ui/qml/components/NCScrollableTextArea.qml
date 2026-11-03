import QtQuick
import QtQuick.Controls
import "../theme" as Theme

ScrollView {
    id: root

    property alias helpDescription: editor.helpDescription
    property alias toolTipText: editor.toolTipText
    property alias text: editor.text
    property alias label: editor.label
    property alias placeholderText: editor.placeholderText
    property alias readOnly: editor.readOnly
    readonly property bool editorActiveFocus: editor.activeFocus
    property alias showRefineAction: editor.showRefineAction
    property alias refineActionEnabled: editor.refineActionEnabled
    property bool accentBorder: false
    signal editingFinished()
    signal refineRequested()

    implicitHeight: 112
    clip: true
    padding: 1
    rightPadding: verticalBar.visible ? verticalBar.width + 3 : 1
    contentWidth: availableWidth
    contentHeight: viewport.contentHeight
    wheelEnabled: false
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ScrollBar.vertical: ScrollBar {
        id: verticalBar
        x: root.width - width - 1
        y: 1
        width: 14
        height: root.height - 2
        minimumSize: 0.15
        policy: root.contentHeight > root.availableHeight ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
        active: true
        interactive: true
    }

    // Consume wheel/trackpad scrolling here rather than moving the Persona page.
    WheelHandler {
        target: null
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        enabled: root.contentHeight > root.availableHeight
        onWheel: function(event) {
            const delta = event.pixelDelta.y !== 0 ? event.pixelDelta.y
                          : event.angleDelta.y / 120 * editor.font.pixelSize * 3
            if (delta === 0) {
                event.accepted = false
                return
            }
            const maximum = Math.max(0, viewport.contentHeight - viewport.height)
            viewport.contentY = Math.max(0, Math.min(maximum, viewport.contentY - delta))
            event.accepted = true
        }
    }

    contentItem: Flickable {
        id: viewport
        objectName: "textAreaViewport"
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        TextArea.flickable: NCTextArea {
            id: editor
            onRefineRequested: root.refineRequested()
            implicitHeight: Math.max(viewport.height, contentHeight + topPadding + bottomPadding)
            background: null
            onActiveFocusChanged: {
                if (!activeFocus && !readOnly)
                    root.editingFinished()
            }
        }
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: root.enabled ? Theme.NCTheme.windowRaised : Theme.NCTheme.surface
        border.width: root.accentBorder ? Math.max(2, Theme.NCMetrics.focusWidth)
                     : editor.activeFocus ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.accentBorder ? Theme.NCTheme.accent
                      : editor.activeFocus ? Theme.NCTheme.focus
                      : root.hovered ? Theme.NCTheme.borderStrong : Theme.NCTheme.border
    }
}
