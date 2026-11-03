import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

// Controlled action button: only the runtime owner changes active/busy.
// A click deliberately does not toggle checked or optimistically claim readiness.
Button {
    id: root
    property bool active: false
    property bool busy: false
    property bool cancellable: false
    property bool cancelling: false
    property bool cleanupPending: false
    property bool glowEnabled: true
    property bool compact: false
    property bool showLabels: true
    property string busyText: qsTr("Initializing NC…")
    property string busyDescription: qsTr("Please wait · loading your stack")
    readonly property bool powered: active && !cleanupPending && !busy
    readonly property color stateColor: busy || cleanupPending ? Theme.NCTheme.warning
                                                       : powered ? Theme.NCTheme.accent : Theme.NCTheme.borderStrong
    readonly property string description: busy && cancellable ? qsTr("Click to cancel initialization") : busy ? busyDescription
        : cleanupPending ? qsTr("Cleanup needed · click to retry")
        : active ? qsTr("On · click to stop session") : qsTr("Off · session stopped")

    text: busy && cancellable ? qsTr("Cancel initialization") : busy ? busyText : cleanupPending ? qsTr("Retry cleanup")
               : active ? qsTr("NC ready") : qsTr("Initialize NC")
    implicitWidth: !showLabels ? 108 : compact ? 240 : 280
    implicitHeight: 48
    padding: 0
    enabled: !busy || cancellable
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    Accessible.description: description
    ToolTip.visible: hovered && busy && cancellable
    ToolTip.delay: 500
    ToolTip.text: qsTr("Cancel initialization")
    background: Item {}

    contentItem: RowLayout {
        spacing: 12
        Item {
            Layout.preferredWidth: 108
            Layout.preferredHeight: 48
            Item {
                id: glow
                objectName: "powerGlow"
                anchors.fill: parent
                visible: root.glowEnabled && (root.powered || root.busy || root.cleanupPending)
                // Layered translucent rings also work with Qt's software renderer.
                Repeater {
                    model: 6
                    Rectangle {
                        required property int index
                        anchors.centerIn: parent
                        width: 110 + index * 2
                        height: 50 + index * 2
                        radius: height / 2
                        color: "transparent"
                        border.width: 2
                        border.color: root.stateColor
                        opacity: (6 - index) * 0.014
                    }
                }
            }
            Rectangle {
                id: track
                anchors.fill: parent
                radius: height / 2
                border.width: root.activeFocus ? 2 : 1
                border.color: root.activeFocus ? Theme.NCTheme.focus
                            : root.hovered ? Qt.lighter(root.stateColor, 1.2) : root.stateColor
                gradient: Gradient {
                    GradientStop { position: 0; color: root.busy || root.cleanupPending ? "#6b4d1a"
                        : root.powered ? "#17c7df" : "#172d40" }
                    GradientStop { position: 1; color: root.busy || root.cleanupPending ? "#302710"
                        : root.powered ? "#008ca7" : "#091522" }
                }
                Label {
                    x: root.cancelling ? (track.width - width) / 2 : root.powered ? 15 : 58
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !root.busy || root.cancelling
                    text: root.cancelling ? qsTr("Cancelling…") : root.powered ? qsTr("ON") : qsTr("OFF")
                    color: root.powered ? "#042634" : Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    font.letterSpacing: root.cancelling ? 0 : 1
                }
                Rectangle {
                    id: thumb
                    objectName: "powerThumb"
                    visible: !root.cancelling
                    x: root.busy ? (track.width - width) / 2 : root.powered ? track.width - width - 5 : 5
                    y: 5 + (root.down ? 1 : 0)
                    width: 38
                    height: 38
                    radius: 19
                    border.width: 1
                    border.color: "#e9f8ff"
                    gradient: Gradient {
                        GradientStop { position: 0; color: "#f3fbff" }
                        GradientStop { position: 0.55; color: "#d5e5ee" }
                        GradientStop { position: 1; color: "#8eacbf" }
                    }
                    Behavior on x { NumberAnimation { duration: Theme.NCMetrics.motionNormal; easing.type: Easing.OutCubic } }
                    Canvas {
                        anchors.fill: parent
                        property bool cancelIcon: root.busy && root.cancellable
                        onCancelIconChanged: requestPaint()
                        property color ink: root.powered ? "#007c96" : "#365568"
                        onInkChanged: requestPaint()
                        onPaint: {
                            const ctx = getContext("2d")
                            ctx.reset()
                            ctx.strokeStyle = ink
                            ctx.lineWidth = 2.2
                            ctx.lineCap = "round"
                            if (cancelIcon) {
                                ctx.beginPath()
                                ctx.moveTo(13, 13)
                                ctx.lineTo(25, 25)
                                ctx.moveTo(25, 13)
                                ctx.lineTo(13, 25)
                                ctx.stroke()
                                return
                            }
                            ctx.beginPath()
                            ctx.arc(19, 20, 8, -Math.PI / 3, Math.PI * 4 / 3)
                            ctx.stroke()
                            ctx.beginPath()
                            ctx.moveTo(19, 9)
                            ctx.lineTo(19, 19)
                            ctx.stroke()
                        }
                    }
                }
            }
        }
        ColumnLayout {
            visible: root.showLabels
            Layout.fillWidth: true
            spacing: 3
            Label {
                Layout.fillWidth: true
                text: root.text
                color: root.busy || root.cleanupPending ? Theme.NCTheme.warning : Theme.NCTheme.text
                font.family: Theme.NCTypography.family
                font.pixelSize: 13
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Label {
                Layout.fillWidth: true
                text: root.description
                visible: !root.compact
                color: Theme.NCTheme.textSecondary
                font.family: Theme.NCTypography.family
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }
    }
}
