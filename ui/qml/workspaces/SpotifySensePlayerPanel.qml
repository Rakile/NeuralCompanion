import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Rectangle {
    id: root

    required property var bridge
    property bool compact: false
    readonly property var spotifyState: root.bridge.spotifySenseState || ({})
    readonly property var track: root.spotifyState.track || ({})
    readonly property bool hasTrack: String(root.track.id || "").length > 0
    readonly property real progressRatio: {
        const duration = Math.max(0, Number(root.track.duration_ms || 0))
        if (duration <= 0)
            return 0
        return Math.max(0, Math.min(1, Number(root.track.progress_ms || 0) / duration))
    }

    function timeLabel(milliseconds) {
        const totalSeconds = Math.max(0, Math.floor(Number(milliseconds || 0) / 1000))
        const minutes = Math.floor(totalSeconds / 60)
        const seconds = totalSeconds % 60
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds
    }

    implicitHeight: playerLayout.implicitHeight + Theme.NCMetrics.space32
    radius: Theme.NCMetrics.radiusLarge
    color: Theme.NCTheme.surface
    border.color: Theme.NCTheme.border

    GridLayout {
        id: playerLayout
        anchors.fill: parent
        anchors.margins: Theme.NCMetrics.space16
        columns: root.width >= (root.compact ? 610 : 720) ? 2 : 1
        columnSpacing: Theme.NCMetrics.space20
        rowSpacing: Theme.NCMetrics.space16

        Rectangle {
            Layout.preferredWidth: root.compact ? 190 : 280
            Layout.preferredHeight: Layout.preferredWidth
            Layout.maximumWidth: root.width
            Layout.alignment: Qt.AlignTop | Qt.AlignHCenter
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.window
            border.color: Theme.NCTheme.borderSubtle
            clip: true

            Image {
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space4
                source: String(root.track.album_art_url || "")
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: true
                smooth: true
                mipmap: true
            }

            Label {
                anchors.centerIn: parent
                width: parent.width - Theme.NCMetrics.space24
                visible: !root.hasTrack || String(root.track.album_art_url || "").length === 0
                text: root.spotifyState.connected
                      ? qsTr("No album artwork available")
                      : qsTr("Connect Spotify to show artwork")
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: Theme.NCMetrics.space8

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8

                Label {
                    Layout.fillWidth: true
                    text: root.hasTrack ? qsTr("Now playing") : qsTr("Spotify Sense")
                    color: Theme.NCTheme.success
                    font.pixelSize: Theme.NCTypography.microSize
                    font.weight: Theme.NCTypography.semibold
                    font.capitalization: Font.AllUppercase
                }

                NCStatusChip {
                    text: root.spotifyState.connected ? qsTr("Connected") : qsTr("Not connected")
                    status: root.spotifyState.connected ? "connected" : "disconnected"
                    compact: true
                }
            }

            Label {
                Layout.fillWidth: true
                text: root.hasTrack ? String(root.track.name || qsTr("Unknown track"))
                                    : qsTr("Nothing is currently playing")
                color: Theme.NCTheme.text
                font.pixelSize: root.compact
                                ? Theme.NCTypography.titleSize
                                : Theme.NCTypography.displaySize
                font.weight: Theme.NCTypography.semibold
                wrapMode: Text.Wrap
            }

            Label {
                Layout.fillWidth: true
                text: (root.track.artists || []).join(", ")
                visible: text.length > 0
                color: Theme.NCTheme.accent
                font.pixelSize: Theme.NCTypography.headingSize
                wrapMode: Text.Wrap
            }

            Label {
                Layout.fillWidth: true
                text: [String(root.track.album || ""), String(root.track.release_date || "")]
                      .filter(value => value.length > 0).join("  •  ")
                visible: text.length > 0
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.Wrap
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: Theme.NCMetrics.space8
                implicitHeight: 6
                radius: 3
                color: Theme.NCTheme.borderSubtle

                Rectangle {
                    width: parent.width * root.progressRatio
                    height: parent.height
                    radius: parent.radius
                    color: Theme.NCTheme.accent
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Label {
                    Layout.fillWidth: true
                    text: root.timeLabel(root.track.progress_ms)
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.microSize
                }
                Label {
                    text: root.timeLabel(root.track.duration_ms)
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.microSize
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.NCMetrics.space8
                spacing: Theme.NCMetrics.space8

                NCButton {
                    text: qsTr("Previous")
                    iconText: "◀|"
                    iconOnly: true
                    compact: true
                    tone: "quiet"
                    enabled: root.spotifyState.connected
                    toolTipText: qsTr("Previous Spotify track")
                    onClicked: root.bridge.triggerSpotifySenseAction("previous", ({}))
                }

                NCButton {
                    text: Boolean(root.track.is_playing) ? qsTr("Pause") : qsTr("Play")
                    iconText: Boolean(root.track.is_playing) ? "Ⅱ" : "▶"
                    iconOnly: true
                    tone: "primary"
                    enabled: root.spotifyState.connected
                    toolTipText: text
                    onClicked: root.bridge.triggerSpotifySenseAction(
                        Boolean(root.track.is_playing) ? "pause" : "play",
                        ({})
                    )
                }

                NCButton {
                    text: qsTr("Next")
                    iconText: "|▶"
                    iconOnly: true
                    compact: true
                    tone: "quiet"
                    enabled: root.spotifyState.connected
                    toolTipText: qsTr("Next Spotify track")
                    onClicked: root.bridge.triggerSpotifySenseAction("next", ({}))
                }

                Item { Layout.fillWidth: true }

                NCButton {
                    text: qsTr("Open in Spotify")
                    iconText: "↗"
                    compact: true
                    tone: "quiet"
                    visible: String(root.track.external_url || "").length > 0
                    onClicked: Qt.openUrlExternally(String(root.track.external_url))
                }
            }

            Label {
                Layout.fillWidth: true
                visible: Number(root.track.album_art_width || 0) > 0
                text: qsTr("Artwork source: %1 × %2 • original aspect ratio")
                      .arg(Number(root.track.album_art_width || 0))
                      .arg(Number(root.track.album_art_height || 0))
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.microSize
                wrapMode: Text.Wrap
            }
        }
    }
}
