pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Button {
    id: root
    property var bufferState: ({})
    property var sessionState: ({})
    property bool systemRunning: false
    property string voiceStyle: "ribbon"
    signal voiceStyleRequested(string style)

    // Percentages share a denominator. A 20-point render lead is full green;
    // a zero/negative lead is red only while rendering is incomplete.
    readonly property real fullGreenLead: 0.20
    // Match the displayed whole percentage, including its rounding at 100%.
    readonly property bool renderComplete: Math.round(normalizedProgress(bufferState.renderProgress) * 100) === 100
    readonly property real renderLead: Math.max(0, normalizedProgress(bufferState.renderProgress)
                                                 - normalizedProgress(bufferState.playbackProgress))
    readonly property bool trackingBufferLead: systemRunning && !renderComplete
        && (Boolean(bufferState.active) || Boolean(bufferState.speechActive) || Boolean(sessionState.playbackActive))
    readonly property color bufferLeadColor: {
        if (bufferState.failed)
            return Theme.NCTheme.error
        if (!systemRunning)
            return Theme.NCTheme.disconnected
        if (!trackingBufferLead)
            return Theme.NCTheme.success
        const headroom = Math.min(renderLead / fullGreenLead, 1)
        return headroom < 0.5
               ? blendColor(Theme.NCTheme.error, Theme.NCTheme.warning, headroom * 2)
               : blendColor(Theme.NCTheme.warning, Theme.NCTheme.success, (headroom - 0.5) * 2)
    }
    readonly property string bufferLeadDescription: {
        if (bufferState.failed)
            return qsTr("Buffer processing failed")
        if (!systemRunning)
            return qsTr("Runtime stopped")
        if (renderComplete)
            return normalizedProgress(bufferState.playbackProgress) === 1
                   ? qsTr("Render and playback complete") : qsTr("Rendering complete; playback is finishing")
        if (!trackingBufferLead)
            return qsTr("No active playback")
        return qsTr("Render lead: %1 percentage points. Green at 20 or more; red when playback catches up.")
               .arg((renderLead * 100).toFixed(1))
    }

    function normalizedProgress(value) {
        const number = Number(value || 0)
        return Math.max(0, Math.min(isFinite(number) ? number : 0, 1))
    }
    function percent(value) {
        return Math.round(normalizedProgress(value) * 100) + "%"
    }
    function blendColor(from, to, amount) {
        return Qt.rgba(from.r + (to.r - from.r) * amount,
                       from.g + (to.g - from.g) * amount,
                       from.b + (to.b - from.b) * amount, 1)
    }

    implicitWidth: 210
    implicitHeight: Theme.NCMetrics.iconButtonSize
    padding: Theme.NCMetrics.space4
    hoverEnabled: true
    onVisibleChanged: if (!visible) details.close()
    Accessible.name: qsTr("Render %1, Playback %2").arg(percent(bufferState.renderProgress)).arg(percent(bufferState.playbackProgress))
    Accessible.description: root.bufferState.failed
                            ? qsTr("Buffer processing failed. Open live session details.")
                            : root.bufferLeadDescription + ". "
                              + String(root.sessionState.stateLabel || (root.systemRunning ? qsTr("Runtime active") : qsTr("Runtime stopped")))
                              + ". " + qsTr("Open live session and buffer details")

    background: Rectangle {
        radius: Theme.NCMetrics.radiusSmall
        color: root.hovered ? Theme.NCTheme.surfaceSelected : "transparent"
        border.width: root.activeFocus ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.activeFocus ? Theme.NCTheme.focus : root.hovered ? Theme.NCTheme.borderStrong : "transparent"
    }
    // Reserve the widest displayed percentage using the actual rich-text font.
    Text {
        id: renderWidthMeasure
        visible: false
        font: renderProgressLabel.font
        textFormat: Text.RichText
        text: qsTr("Render <b>%1</b>").arg("100%")
    }
    Text {
        id: playbackWidthMeasure
        visible: false
        font: playbackProgressLabel.font
        textFormat: Text.RichText
        text: qsTr("Playback <b>%1</b>").arg("100%")
    }
    contentItem: RowLayout {
        spacing: Theme.NCMetrics.space4
        Label {
            id: renderProgressLabel
            objectName: "compactRenderProgress"
            Layout.preferredWidth: Math.ceil(renderWidthMeasure.implicitWidth)
            Layout.minimumWidth: Layout.preferredWidth
            Layout.maximumWidth: Layout.preferredWidth
            text: qsTr("Render <b>%1</b>").arg(root.percent(root.bufferState.renderProgress))
            textFormat: Text.RichText
            color: root.bufferState.failed ? Theme.NCTheme.error : Theme.NCTheme.text
            font.pixelSize: Theme.NCTypography.captionSize
        }
        Label {
            id: playbackProgressLabel
            objectName: "compactPlaybackProgress"
            Layout.preferredWidth: Math.ceil(playbackWidthMeasure.implicitWidth)
            Layout.minimumWidth: Layout.preferredWidth
            Layout.maximumWidth: Layout.preferredWidth
            text: qsTr("Playback <b>%1</b>").arg(root.percent(root.bufferState.playbackProgress))
            textFormat: Text.RichText
            color: root.bufferState.failed ? Theme.NCTheme.error : Theme.NCTheme.text
            font.pixelSize: Theme.NCTypography.captionSize
        }
        Rectangle {
            objectName: "compactBufferLeadIndicator"
            width: 12; height: 12; radius: 6
            color: root.bufferLeadColor
        }
        Item { Layout.fillWidth: true }
        Label {
            text: "\u203A"
            rotation: 90
            color: Theme.NCTheme.accent
            font.pixelSize: Theme.NCTypography.titleSize
            font.weight: Theme.NCTypography.bold
        }
    }
    NCToolTip {
        visible: root.hovered
        text: root.bufferLeadDescription + "\n"
              + String(root.bufferState.summary || root.sessionState.stateLabel || qsTr("Open live session details"))
    }
    onClicked: {
        if (!details.parent)
            return
        const mapped = root.mapToItem(details.parent, 0, root.height + Theme.NCMetrics.space4)
        details.x = Math.max(Theme.NCMetrics.space8, Math.min(mapped.x, details.parent.width - details.width - Theme.NCMetrics.space8))
        details.y = Math.max(Theme.NCMetrics.space8, Math.min(mapped.y, details.parent.height - details.implicitHeight - Theme.NCMetrics.space8))
        details.open()
    }

    Popup {
        id: details
        objectName: "compactBufferDetailsPopup"
        parent: Overlay.overlay
        width: Math.max(0, Math.min(520, parent ? parent.width - Theme.NCMetrics.space16 : 520))
        padding: Theme.NCMetrics.space12
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        function keepInsideOverlay() {
            if (!parent)
                return
            x = Math.max(Theme.NCMetrics.space8, Math.min(x, parent.width - width - Theme.NCMetrics.space8))
            y = Math.max(Theme.NCMetrics.space8, Math.min(y, parent.height - height - Theme.NCMetrics.space8))
        }
        onOpened: keepInsideOverlay()
        onWidthChanged: if (opened) keepInsideOverlay()
        onHeightChanged: if (opened) keepInsideOverlay()
        Connections {
            target: details.parent
            function onWidthChanged() { if (details.opened) details.keepInsideOverlay() }
            function onHeightChanged() { if (details.opened) details.keepInsideOverlay() }
        }
        background: Rectangle {
            color: Theme.NCTheme.windowRaised
            radius: Theme.NCMetrics.radiusMedium
            border.color: Theme.NCTheme.borderStrong
        }
        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space8
            RowLayout {
                Layout.fillWidth: true
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Live session")
                    color: Theme.NCTheme.text
                    font.pixelSize: Theme.NCTypography.headingSize
                }
                NCStatusChip {
                    text: root.systemRunning ? qsTr("Runtime active") : qsTr("Runtime stopped")
                    status: root.bufferState.failed ? "error" : root.systemRunning ? "active" : "disconnected"
                }
                NCButton { text: qsTr("Close"); compact: true; onClicked: details.close() }
            }
            Label {
                Layout.fillWidth: true
                text: String(root.sessionState.stateLabel || root.bufferState.summary || qsTr("Waiting for TTS"))
                color: root.bufferState.failed ? Theme.NCTheme.error : Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                text: root.sessionState.recording ? qsTr("Microphone recording")
                      : root.sessionState.ready ? qsTr("Ready for voice or text input") : qsTr("Microphone not recording")
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
            }
            NCTtsBufferRace {
                objectName: "compactBufferDetailsRace"
                Layout.fillWidth: true
                renderProgress: Number(root.bufferState.renderProgress || 0)
                playbackProgress: Number(root.bufferState.playbackProgress || 0)
                phoneReadyVisible: Boolean(root.bufferState.phoneReadyVisible)
                phoneReadyProgress: Number(root.bufferState.phoneReadyProgress || 0)
                downloadReadyVisible: Boolean(root.bufferState.downloadReadyVisible)
                downloadReadyProgress: Number(root.bufferState.downloadReadyProgress || 0)
                downloadReadyLabel: String(root.bufferState.downloadReadyLabel || "")
                renderLabel: String(root.bufferState.renderLabel || "")
                phoneReadyLabel: String(root.bufferState.phoneReadyLabel || "")
                playbackLabel: String(root.bufferState.playbackLabel || "")
                active: Boolean(root.bufferState.active)
                failed: Boolean(root.bufferState.failed)
                summary: String(root.bufferState.summary || qsTr("Waiting for TTS"))
            }
            RowLayout {
                Layout.fillWidth: true
                Label { text: qsTr("Voice display"); color: Theme.NCTheme.textMuted }
                NCComboBox {
                    Layout.fillWidth: true
                    property var styleIds: ["ribbon", "spectrum", "kinetic"]
                    label: qsTr("Voice activity display")
                    model: [qsTr("Breathing ribbon"), qsTr("Spectrum cells"), qsTr("Kinetic current")]
                    currentIndex: Math.max(0, styleIds.indexOf(root.voiceStyle))
                    onActivated: root.voiceStyleRequested(styleIds[currentIndex])
                }
            }
            NCVoiceActivityBar {
                Layout.fillWidth: true
                styleMode: root.voiceStyle
                voiceState: String(root.sessionState.state || "stopped")
                stateLabel: String(root.sessionState.stateLabel || qsTr("Runtime stopped"))
                moodName: String(root.sessionState.moodName || root.sessionState.mood || "neutral")
                primaryColor: String(root.sessionState.primaryColor || "#38bdf8")
                secondaryColor: String(root.sessionState.secondaryColor || "#22d3ee")
                accentColor: String(root.sessionState.accentColor || "#a78bfa")
                audioLevel: Number(root.sessionState.audioLevel || 0)
            }
        }
    }
}
