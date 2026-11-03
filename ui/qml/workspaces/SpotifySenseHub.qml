pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Item {
    id: root

    required property var bridge
    property string currentView: "now"
    readonly property var spotifyState: root.bridge.spotifySenseState || ({})
    readonly property var hub: root.spotifyState.music_hub || ({})
    readonly property var artist: root.hub.artist || ({})
    readonly property var playlists: root.hub.playlists || []
    readonly property var discovery: root.hub.discovery || []

    function refreshHub() {
        root.bridge.refreshSpotifySenseState()
        if (root.spotifyState.connected)
            root.bridge.triggerSpotifySenseAction("dashboard_refresh", ({}))
    }

    function askAboutArtist() {
        const artistName = String(root.artist.name || "").trim()
        if (!artistName.length || !root.bridge.systemRunning)
            return
        root.bridge.submitConversationTurn(
            qsTr("Tell me about the artist %1. Use verified web information when available and do not invent biographical facts.")
            .arg(artistName)
        )
    }

    Component.onCompleted: refreshHub()

    ScrollView {
        id: hubScroll
        property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
            bridge: root.bridge
            scrollView: hubScroll
            pageKey: "addon:spotify_sense_tab:music-hub:" + root.currentView
        }
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: hubScroll.availableWidth
            spacing: Theme.NCMetrics.space12

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space6

                NCTabButton {
                    text: qsTr("Now playing")
                    checked: root.currentView === "now"
                    onClicked: root.currentView = "now"
                }
                NCTabButton {
                    text: qsTr("Artist")
                    checked: root.currentView === "artist"
                    onClicked: root.currentView = "artist"
                }
                NCTabButton {
                    text: qsTr("Your playlists")
                    checked: root.currentView === "playlists"
                    onClicked: root.currentView = "playlists"
                }
                NCTabButton {
                    text: qsTr("Discover")
                    checked: root.currentView === "discover"
                    onClicked: root.currentView = "discover"
                }

                Item { Layout.fillWidth: true }

                NCButton {
                    text: qsTr("Refresh")
                    iconText: "↻"
                    compact: true
                    busy: Boolean(root.hub.loading)
                    enabled: root.spotifyState.connected
                    onClicked: root.refreshHub()
                }
            }

            NCInlineMessage {
                Layout.fillWidth: true
                visible: !root.spotifyState.connected
                tone: "warning"
                title: qsTr("Spotify is not connected")
                message: qsTr("Open Connect in Spotify Sense, log in, and return here to load the Music Hub.")
            }

            NCInlineMessage {
                Layout.fillWidth: true
                visible: String(root.hub.error || "").length > 0
                tone: String(root.hub.error || "").indexOf("Reconnect") >= 0 ? "info" : "warning"
                title: qsTr("Music Hub notice")
                message: String(root.hub.error || "")
            }

            ColumnLayout {
                Layout.fillWidth: true
                visible: root.currentView === "now"
                spacing: Theme.NCMetrics.space12

                SpotifySensePlayerPanel {
                    Layout.fillWidth: true
                    bridge: root.bridge
                }

                NCCard {
                    Layout.fillWidth: true
                    title: qsTr("Companion interactions")
                    description: qsTr("Use the current artist as an explicit conversation request, or open the existing awareness controls.")

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space8

                        NCButton {
                            text: qsTr("Ask NC about this artist")
                            iconText: "?"
                            enabled: root.bridge.systemRunning
                                     && String(root.spotifyState.track && (root.spotifyState.track.artists || [])[0] || "").length > 0
                            onClicked: {
                                const trackArtists = root.spotifyState.track && root.spotifyState.track.artists || []
                                const artistName = trackArtists.length > 0 ? String(trackArtists[0]) : ""
                                if (artistName.length > 0)
                                    root.bridge.submitConversationTurn(
                                        qsTr("Tell me about the artist %1. Use verified web information when available and do not invent biographical facts.")
                                        .arg(artistName)
                                    )
                            }
                        }

                        NCButton {
                            text: qsTr("Awareness settings")
                            tone: "quiet"
                            onClicked: root.bridge.viewRuntimeProviderSettings("vision", "spotify_sense")
                        }

                        Item { Layout.fillWidth: true }
                    }
                }
            }

            NCCard {
                Layout.fillWidth: true
                visible: root.currentView === "artist"
                title: String(root.artist.name || qsTr("Artist spotlight"))
                description: String(root.artist.name || "").length > 0
                             ? qsTr("Spotify artist identity and releases. Biographical questions use an explicit NC request.")
                             : qsTr("Start a track and refresh the Music Hub to load its primary artist.")

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space16
                    visible: String(root.artist.name || "").length > 0

                    Rectangle {
                        Layout.preferredWidth: 190
                        Layout.preferredHeight: 190
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.window
                        border.color: Theme.NCTheme.border
                        clip: true

                        Image {
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space4
                            source: String(root.artist.image_url || "")
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            cache: true
                            smooth: true
                            mipmap: true
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space8

                        Label {
                            Layout.fillWidth: true
                            text: String(root.artist.name || "")
                            color: Theme.NCTheme.text
                            font.pixelSize: Theme.NCTypography.titleSize
                            font.weight: Theme.NCTypography.semibold
                            wrapMode: Text.Wrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: (root.artist.genres || []).join("  •  ")
                            visible: text.length > 0
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                            wrapMode: Text.Wrap
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            NCButton {
                                text: qsTr("Ask NC")
                                enabled: root.bridge.systemRunning
                                onClicked: root.askAboutArtist()
                            }
                            NCButton {
                                text: qsTr("Open in Spotify")
                                tone: "quiet"
                                visible: String(root.artist.external_url || "").length > 0
                                onClicked: Qt.openUrlExternally(String(root.artist.external_url))
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: qsTr("Recent releases")
                    visible: (root.artist.albums || []).length > 0
                    color: Theme.NCTheme.text
                    font.pixelSize: Theme.NCTypography.headingSize
                    font.weight: Theme.NCTypography.semibold
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: visible ? 178 : 0
                    visible: (root.artist.albums || []).length > 0
                    contentWidth: artistAlbumRow.implicitWidth
                    ScrollBar.vertical.policy: ScrollBar.AlwaysOff
                    clip: true

                    Row {
                        id: artistAlbumRow
                        spacing: Theme.NCMetrics.space10

                        Repeater {
                            model: root.artist.albums || []

                            delegate: Rectangle {
                                id: albumTile
                                required property var modelData
                                width: 142
                                height: 164
                                radius: Theme.NCMetrics.radiusMedium
                                color: Theme.NCTheme.window
                                border.color: Theme.NCTheme.borderSubtle

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space6
                                    spacing: Theme.NCMetrics.space4

                                    Image {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 116
                                        source: String(albumTile.modelData.image_url || "")
                                        fillMode: Image.PreserveAspectFit
                                        asynchronous: true
                                        cache: true
                                        smooth: true
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: String(albumTile.modelData.name || "")
                                        color: Theme.NCTheme.text
                                        font.pixelSize: Theme.NCTypography.captionSize
                                        elide: Text.ElideRight
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: String(albumTile.modelData.release_date || "")
                                        color: Theme.NCTheme.textMuted
                                        font.pixelSize: Theme.NCTypography.microSize
                                        elide: Text.ElideRight
                                    }
                                }

                                TapHandler {
                                    enabled: String(albumTile.modelData.external_url || "").length > 0
                                    onTapped: Qt.openUrlExternally(String(albumTile.modelData.external_url))
                                }
                            }
                        }
                    }
                }
            }

            NCCard {
                Layout.fillWidth: true
                visible: root.currentView === "playlists"
                title: qsTr("Your playlists")
                description: root.playlists.length > 0
                             ? qsTr("Play a private or collaborative playlist on the active Spotify device.")
                             : qsTr("No playlists are cached yet. Refresh after connecting Spotify.")

                Repeater {
                    model: root.playlists

                    delegate: Rectangle {
                        id: playlistRow
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 72
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.window
                        border.color: Theme.NCTheme.borderSubtle

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space8
                            spacing: Theme.NCMetrics.space10

                            Rectangle {
                                Layout.preferredWidth: 54
                                Layout.preferredHeight: 54
                                radius: Theme.NCMetrics.radiusSmall
                                color: Theme.NCTheme.surface
                                clip: true
                                Image {
                                    anchors.fill: parent
                                    source: String(playlistRow.modelData.image_url || "")
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    cache: true
                                    smooth: true
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space2
                                Label {
                                    Layout.fillWidth: true
                                    text: String(playlistRow.modelData.name || qsTr("Untitled playlist"))
                                    color: Theme.NCTheme.text
                                    font.pixelSize: Theme.NCTypography.bodySize
                                    font.weight: Theme.NCTypography.semibold
                                    elide: Text.ElideRight
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: qsTr("%1 tracks%2")
                                          .arg(Number(playlistRow.modelData.track_count || 0))
                                          .arg(String(playlistRow.modelData.owner || "").length > 0
                                               ? qsTr("  •  %1").arg(String(playlistRow.modelData.owner)) : "")
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                    elide: Text.ElideRight
                                }
                            }

                            NCButton {
                                text: qsTr("Play")
                                iconText: "▶"
                                compact: true
                                enabled: String(playlistRow.modelData.uri || "").length > 0
                                onClicked: root.bridge.triggerSpotifySenseAction(
                                    "play_context",
                                    ({"uri": String(playlistRow.modelData.uri || "")})
                                )
                            }
                            NCButton {
                                text: qsTr("Open")
                                iconText: "↗"
                                iconOnly: true
                                compact: true
                                tone: "quiet"
                                visible: String(playlistRow.modelData.external_url || "").length > 0
                                onClicked: Qt.openUrlExternally(String(playlistRow.modelData.external_url))
                            }
                        }
                    }
                }
            }

            NCCard {
                Layout.fillWidth: true
                visible: root.currentView === "discover"
                title: qsTr("Discover from your listening")
                description: root.discovery.length > 0
                             ? qsTr("Your short-term top tracks provide a personal discovery starting point.")
                             : qsTr("Reconnect Spotify once to grant the new top-music permission, then refresh.")

                Repeater {
                    model: root.discovery

                    delegate: Rectangle {
                        id: discoveryRow
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 72
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.window
                        border.color: Theme.NCTheme.borderSubtle

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space8
                            spacing: Theme.NCMetrics.space10

                            Rectangle {
                                Layout.preferredWidth: 54
                                Layout.preferredHeight: 54
                                radius: Theme.NCMetrics.radiusSmall
                                color: Theme.NCTheme.surface
                                clip: true
                                Image {
                                    anchors.fill: parent
                                    source: String(discoveryRow.modelData.album_art_url || "")
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    cache: true
                                    smooth: true
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space2
                                Label {
                                    Layout.fillWidth: true
                                    text: String(discoveryRow.modelData.name || qsTr("Unknown track"))
                                    color: Theme.NCTheme.text
                                    font.pixelSize: Theme.NCTypography.bodySize
                                    font.weight: Theme.NCTypography.semibold
                                    elide: Text.ElideRight
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: (discoveryRow.modelData.artists || []).join(", ")
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                    elide: Text.ElideRight
                                }
                            }

                            NCButton {
                                text: qsTr("Queue")
                                iconText: "+"
                                compact: true
                                enabled: String(discoveryRow.modelData.uri || "").length > 0
                                onClicked: root.bridge.triggerSpotifySenseAction(
                                    "queue_uri",
                                    ({"uri": String(discoveryRow.modelData.uri || "")})
                                )
                            }
                            NCButton {
                                text: qsTr("Open")
                                iconText: "↗"
                                iconOnly: true
                                compact: true
                                tone: "quiet"
                                visible: String(discoveryRow.modelData.external_url || "").length > 0
                                onClicked: Qt.openUrlExternally(String(discoveryRow.modelData.external_url))
                            }
                        }
                    }
                }
            }
        }
    }
}
