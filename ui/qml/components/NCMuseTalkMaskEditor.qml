import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import NeuralCompanion.Creator 1.0
import "../theme" as Theme

Item {
    id: root

    property var creatorModel: null
    readonly property var creatorState: creatorModel ? creatorModel.state : ({})
    readonly property int sourceWidth: Number(creatorState.maskSourceWidth || 0)
    readonly property int sourceHeight: Number(creatorState.maskSourceHeight || 0)
    readonly property int previewRevision: Number(creatorState.maskPreviewRevision ?? -1)
    readonly property real zoom: Math.max(0.25, Math.min(4.0, Number(creatorState.musetalk_debug_zoom || 1.0)))
    readonly property bool editable: Boolean(creatorState.maskEditable)
    property real panX: 0
    property real panY: 0
    readonly property real fitScale: sourceWidth > 0 && sourceHeight > 0
                                          ? Math.min(maskViewport.width / sourceWidth,
                                                     maskViewport.height / sourceHeight)
                                          : 0
    readonly property real displayScale: fitScale * zoom
    readonly property real brushRadius: Math.max(1, Number(creatorState.musetalk_debug_brush_size ?? 12))
    readonly property real featherStartRadius: Math.max(0, brushRadius - Math.max(0, Number(creatorState.musetalk_debug_brush_feather ?? 6)))
    readonly property real imageLeft: (maskViewport.width - sourceWidth * displayScale) / 2 + panX
    readonly property real imageTop: (maskViewport.height - sourceHeight * displayScale) / 2 + panY
    property bool strokeActive: false
    property bool panning: false
    property point panAnchor: Qt.point(0, 0)
    property point panOrigin: Qt.point(0, 0)

    implicitWidth: 420
    implicitHeight: 360

    function sourcePoint(pointerX, pointerY) {
        if (displayScale <= 0)
            return Qt.point(-1, -1)
        const sourceX = (pointerX - imageLeft) / displayScale
        const sourceY = (pointerY - imageTop) / displayScale
        if (sourceX < 0 || sourceY < 0 || sourceX >= sourceWidth || sourceY >= sourceHeight)
            return Qt.point(-1, -1)
        return Qt.point(sourceX, sourceY)
    }

    function cancelStroke() {
        if (strokeActive && creatorModel)
            creatorModel.endStroke(previewRevision)
        strokeActive = false
        panning = false
    }

    function requestZoom(controlId, pointerX, pointerY) {
        if (!creatorModel)
            return
        if (pointerX !== undefined && pointerY !== undefined && displayScale > 0) {
            const point = sourcePoint(pointerX, pointerY)
            if (point.x >= 0) {
                const factor = controlId === "btn_musetalk_debug_zoom_in" ? 1.2 : 1 / 1.2
                const nextZoom = Math.max(0.25, Math.min(4.0, zoom * factor))
                const nextScale = fitScale * nextZoom
                panX = pointerX - (maskViewport.width - sourceWidth * nextScale) / 2 - point.x * nextScale
                panY = pointerY - (maskViewport.height - sourceHeight * nextScale) / 2 - point.y * nextScale
            }
        }
        creatorModel.trigger(controlId, {})
    }

    onVisibleChanged: if (!visible) cancelStroke()
    Component.onDestruction: cancelStroke()

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.NCMetrics.space8

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space8

            Item { Layout.fillWidth: true }

            NCButton {
                objectName: "maskSaveButton"
                text: qsTr("Save edited mask as override")
                compact: true
                tone: "primary"
                enabled: root.editable && !Boolean(root.creatorState.commandBusy)
                onClicked: if (root.creatorModel) root.creatorModel.saveEditedMask(root.previewRevision)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space8

            Label {
                text: qsTr("Preview zoom")
                color: Theme.NCTheme.textMuted
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.labelSize
            }

            Item { Layout.fillWidth: true }

            NCIconButton {
                objectName: "maskZoomOutButton"
                glyph: "−"
                toolTipText: qsTr("Zoom out")
                onClicked: root.requestZoom("btn_musetalk_debug_zoom_out")
            }

            NCIconButton {
                objectName: "maskZoomFitButton"
                glyph: "↙"
                toolTipText: qsTr("Fit preview")
                onClicked: {
                    root.panX = 0
                    root.panY = 0
                    if (root.creatorModel)
                        root.creatorModel.trigger("btn_musetalk_debug_zoom_reset", {})
                }
            }

            NCIconButton {
                objectName: "maskZoomInButton"
                glyph: "+"
                toolTipText: qsTr("Zoom in")
                onClicked: root.requestZoom("btn_musetalk_debug_zoom_in")
            }
        }

        Label {
            Layout.fillWidth: true
            text: root.editable
                  ? qsTr("Left-drag adds, right-drag subtracts, middle-drag pans. Alt+wheel zooms at the pointer.")
                  : qsTr("Render a source-frame preview to edit its mask here. The clean result appears in Avatar Preview.")
            color: Theme.NCTheme.textMuted
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.captionSize
            wrapMode: Text.Wrap
        }

        Rectangle {
            id: maskViewport
            objectName: "maskViewport"
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.NCTheme.window
            border.width: Theme.NCMetrics.borderWidth
            border.color: root.editable ? Theme.NCTheme.borderStrong : Theme.NCTheme.border
            radius: Theme.NCMetrics.radiusMedium
            clip: true

            MuseTalkMaskSurface {
                id: maskSurface
                objectName: "maskSurface"
                x: root.imageLeft
                y: root.imageTop
                width: root.sourceWidth * root.displayScale
                height: root.sourceHeight * root.displayScale
                image: root.creatorState.maskImage
                visible: root.sourceWidth > 0 && root.sourceHeight > 0
            }

            Label {
                anchors.centerIn: parent
                visible: root.sourceWidth <= 0 || root.sourceHeight <= 0
                text: qsTr("No creator preview")
                color: Theme.NCTheme.textMuted
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.bodySize
            }

            Item {
                id: brushGuide
                x: pointerArea.mouseX
                y: pointerArea.mouseY
                visible: root.enabled && root.editable && !root.panning
                         && pointerArea.containsMouse
                         && root.sourcePoint(x, y).x >= 0

                Rectangle {
                    objectName: "brushOuterRing"
                    x: -width / 2
                    y: -height / 2
                    width: 2 * root.brushRadius * root.displayScale
                    height: width
                    radius: width / 2
                    color: "transparent"
                    border.color: "#161616"
                    border.width: 3
                    antialiasing: true
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 1
                        radius: width / 2
                        color: "transparent"
                        border.color: "white"
                        border.width: 1
                        antialiasing: true
                    }
                }

                Rectangle {
                    objectName: "brushInnerRing"
                    x: -width / 2
                    y: -height / 2
                    width: 2 * root.featherStartRadius * root.displayScale
                    height: width
                    radius: width / 2
                    visible: root.featherStartRadius > 0 && root.featherStartRadius < root.brushRadius
                    color: "transparent"
                    border.color: "#161616"
                    border.width: 3
                    antialiasing: true
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 1
                        radius: width / 2
                        color: "transparent"
                        border.color: Theme.NCTheme.accent
                        border.width: 1
                        antialiasing: true
                    }
                }
            }

            MouseArea {
                id: pointerArea
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                hoverEnabled: true
                preventStealing: true
                focus: true
                cursorShape: root.panning ? Qt.ClosedHandCursor
                                          : brushGuide.visible ? Qt.BlankCursor : Qt.ArrowCursor

                onPressed: function(mouse) {
                    forceActiveFocus()
                    if (mouse.button === Qt.MiddleButton) {
                        root.panning = true
                        root.panAnchor = Qt.point(mouse.x, mouse.y)
                        root.panOrigin = Qt.point(root.panX, root.panY)
                        return
                    }
                    if (!root.editable || !root.creatorModel)
                        return
                    const point = root.sourcePoint(mouse.x, mouse.y)
                    if (point.x < 0)
                        return
                    const bothButtons = (mouse.buttons & Qt.LeftButton)
                                             && (mouse.buttons & Qt.RightButton)
                    const add = bothButtons || mouse.button === Qt.LeftButton
                    root.creatorModel.beginStroke(root.previewRevision, add)
                    root.strokeActive = true
                    root.creatorModel.paintPoint(root.previewRevision, point.x, point.y)
                }

                onPositionChanged: function(mouse) {
                    if (root.panning && (mouse.buttons & Qt.MiddleButton)) {
                        root.panX = root.panOrigin.x + mouse.x - root.panAnchor.x
                        root.panY = root.panOrigin.y + mouse.y - root.panAnchor.y
                        return
                    }
                    if (!root.strokeActive || !root.creatorModel)
                        return
                    const point = root.sourcePoint(mouse.x, mouse.y)
                    if (point.x >= 0)
                        root.creatorModel.paintPoint(root.previewRevision, point.x, point.y)
                }

                onReleased: function(mouse) {
                    if (root.strokeActive && root.creatorModel)
                        root.creatorModel.endStroke(root.previewRevision)
                    root.strokeActive = false
                    if (mouse.button === Qt.MiddleButton)
                        root.panning = false
                }
                onCanceled: root.cancelStroke()
                onActiveFocusChanged: if (!activeFocus) root.cancelStroke()
                onWheel: function(wheel) {
                    if (wheel.modifiers & Qt.AltModifier) {
                        // Alt-wheel may arrive on the horizontal axis; touchpads
                        // can supply only pixel deltas. Zero movement is not zoom-in.
                        const delta = wheel.angleDelta.y || wheel.angleDelta.x
                                      || wheel.pixelDelta.y || wheel.pixelDelta.x
                        if (delta === 0) {
                            wheel.accepted = false
                            return
                        }
                        root.requestZoom(
                            delta > 0
                                ? "btn_musetalk_debug_zoom_in"
                                : "btn_musetalk_debug_zoom_out",
                            wheel.x,
                            wheel.y
                        )
                        wheel.accepted = true
                    } else {
                        wheel.accepted = false
                    }
                }
            }
        }
    }
}
