pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../components"
import "../theme" as Theme

ColumnLayout {
    id: root
    required property var bridge
    property string phonePlatform: "android"
    readonly property var connection: field("main_chat_remote_connection")
    readonly property bool ready: Boolean(connection.ready)
    readonly property bool wide: width >= 900
    readonly property var traffic: field("main_chat_remote_traffic")
    objectName: "mainChatRemoteWorkspace"
    NCTutorialMenu { id: tabTutorials; bridge: root.bridge }
    property string currentTab: "connect"
    property string soundKind: "ambience"
    property var soundImportRequest: ({})
    readonly property var soundImportSnapshot: {
        try { return JSON.parse(String(field("main_chat_soundscape_preview").value || "{}")) }
        catch (_) { return ({}) }
    }
    readonly property real availableWidth: width
    spacing: 16
    onCurrentTabChanged: pageScroll.contentItem.contentY = 0

    function field(id) {
        const controls = bridge.liveAddonControls || []
        for (let i = 0; i < controls.length; ++i)
            if (controls[i].id === id) return controls[i]
        return ({})
    }
    function fields(ids) {
        return ids.map(id => field(id)).filter(item => Boolean(item.id))
    }
    function act(id) {
        if (field(id).enabled === true) bridge.triggerLiveAddonAction(id)
    }
    function bytes(value) {
        const n = Math.max(0, Number(value || 0))
        if (n >= 1000000000) return (n / 1000000000).toFixed(2) + " GB"
        if (n >= 1000000) return (n / 1000000).toFixed(2) + " MB"
        if (n >= 1000) return (n / 1000).toFixed(1) + " kB"
        return n.toFixed(0) + " B"
    }
    function usage(kind, direction) {
        const row = traffic[kind] || {}
        return bytes(row[direction]) + "\n" + bytes(row[direction + "_rate"]) + "/s"
    }

    Timer {
        interval: 2000
        repeat: true
        running: root.visible
        onTriggered: root.bridge.refreshLiveAddonControls()
    }
    Component.onCompleted: bridge.refreshLiveAddonControls()
    NCSoundImportDialog {
        id: soundImportDialog
        snapshot: root.soundImportSnapshot
        onAction: request => root.bridge.triggerLiveAddonActionWithPayload("main_chat_soundscape_import", request)
        onRescan: recursive => root.bridge.triggerLiveAddonActionWithPayload("main_chat_soundscape_import", Object.assign({}, root.soundImportRequest, {recursive:recursive}))
    }
    FileDialog {
        id: soundFiles
        title: qsTr("Import background sounds")
        fileMode: FileDialog.OpenFiles
        nameFilters: [qsTr("Audio (*.wav *.flac *.mp3 *.m4a *.aac *.ogg *.opus)")]
        onAccepted: {
            root.soundImportRequest = {kind:root.soundKind,paths:selectedFiles.map(value=>String(value))}
            root.bridge.triggerLiveAddonActionWithPayload("main_chat_soundscape_import", root.soundImportRequest)
        }
    }
    FolderDialog {
        id: soundFolder
        title: qsTr("Import a folder of sounds (including existing AudioFX)")
        onAccepted: {
            root.soundImportRequest = {kind:root.soundKind,folder:String(selectedFolder)}
            root.bridge.triggerLiveAddonActionWithPayload("main_chat_soundscape_import", root.soundImportRequest)
        }
    }

    component Copy: Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        color: Theme.NCTheme.textSecondary
        font.family: Theme.NCTypography.family
    }
    component Controls: NCLiveControlsGroup {
        property var ids: []
        Layout.fillWidth: true
        flat: true
        flatSingleGroup: true
        showRefresh: false
        controls: root.fields(ids)
        onControlEdited: (id, value) => root.bridge.setLiveAddonControl(id, value)
        onActionTriggered: id => root.bridge.triggerLiveAddonAction(id)
        onActionWithPayload: (id, payload) => root.bridge.triggerLiveAddonActionWithPayload(id, payload)
    }
    component Disclosure: NCButton {
        property bool expanded: false
        property string caption
        text: (expanded ? "−  " : "+  ") + caption
        tone: "quiet"
        Layout.fillWidth: true
        onClicked: expanded = !expanded
    }
    component Card: NCCard {
        Layout.fillWidth: true
        Layout.preferredWidth: Layout.columnSpan * 300
        Layout.alignment: Qt.AlignTop
        Layout.minimumWidth: 0
    }

    Card {
        objectName: "remoteGetConnected"
        title: qsTr("Main Chat Remote")
        description: qsTr("Your main chat, voice and persona — on your phone.")
        Copy {
            text: String(root.connection.value || "")
            color: root.connection.needsAttention ? Theme.NCTheme.error : Theme.NCTheme.textSecondary
        }
        RowLayout {
            Layout.fillWidth: true
            NCButton {
                objectName: "remoteConnectPhone"
                text: root.connection.stopping ? qsTr("Stopping…") : root.connection.busy ? qsTr("Connecting…") : root.ready ? qsTr("Phone setup ready") : qsTr("Connect phone")
                tone: "primary"
                enabled: root.field("main_chat_remote_connect").enabled === true && !root.ready
                onClicked: root.act("main_chat_remote_connect")
            }
            BusyIndicator { running: Boolean(root.connection.busy); visible: running; implicitWidth: 28; implicitHeight: 28 }
            NCButton {
                objectName: "remoteStop"
                text: qsTr("Stop")
                tone: "danger"
                toolTipText: qsTr("Disconnect Internet access and stop the phone backend and desktop bridge. Your account stays signed in.")
                enabled: root.field("main_chat_remote_stop").enabled === true
                onClicked: root.act("main_chat_remote_stop")
            }
        }
        Copy { text: qsTr("This prepares the phone backend and starts the two local services. Internet access is optional.") }
    }

    Card {
        title: qsTr("Background sound library")
        description: qsTr("Import your own music, ambience or AudioFX. Choose and mix them in the phone’s Soundscape controls.")
        RowLayout {
            ComboBox {
                id: soundCategory
                NCHelp {
                    target: soundCategory
                    text: qsTr("Category assigned to the next imported sound files: background ambience, music, or effects. Choose the category before importing files or a folder.")
                }
                model:["Ambience","Music","Effects"]
                onActivated: root.soundKind=["ambience","music","effect"][currentIndex]
            }
            NCButton { text:qsTr("Import files"); onClicked:soundFiles.open() }
            NCButton { text:qsTr("Import folder / AudioFX"); onClicked:soundFolder.open() }
        }
        Copy { text:String(root.field("main_chat_soundscape_status").value || "") }
        Copy { text:qsTr("Select up to 100 individual files, or import every included sound in a folder. Large folders are shown 100 at a time. The library holds up to 2,000 sounds; each file may be up to 100 MB and 30 minutes. Originals stay where they are.") }
    }

    Flow {
        Layout.fillWidth: true
        spacing: 24
        Repeater {
            model: [
                { key: "bridge", label: qsTr("Desktop bridge"), ready: Boolean(root.connection.bridgeRunning), busy: Boolean(root.connection.busy), state: root.connection.bridgeRunning ? qsTr("Running") : root.connection.busy ? qsTr("Starting") : qsTr("Stopped") },
                { key: "backend", label: qsTr("Phone backend"), ready: root.ready, busy: Boolean(root.connection.busy), state: root.ready ? qsTr("Ready") : root.connection.busy ? qsTr("Starting") : root.connection.backendRunning ? qsTr("Not ready") : qsTr("Stopped") },
                { key: "internet", label: qsTr("Internet"), ready: Boolean(root.field("main_chat_relay_status").online),
                  busy: Boolean(root.field("main_chat_relay_status").busy || root.field("main_chat_relay_status").internet_enabled),
                  state: root.field("main_chat_relay_status").stopping ? qsTr("Disconnecting")
                       : root.field("main_chat_relay_status").online ? qsTr("Online")
                       : root.field("main_chat_relay_status").internet_enabled ? qsTr("Connecting")
                       : root.field("main_chat_relay_status").busy ? qsTr("Working")
                       : root.field("main_chat_relay_status").worker_running ? qsTr("Error") : qsTr("Offline") }
            ]
            delegate: Row {
                required property var modelData
                spacing: 8
                Rectangle {
                    objectName: "remoteStatusLight_" + modelData.key
                    property string status: modelData.ready ? "ready" : modelData.busy ? "busy" : "offline"
                    width: 9; height: 9; radius: 4.5
                    anchors.verticalCenter: parent.verticalCenter
                    color: status === "ready" ? Theme.NCTheme.success : status === "busy" ? Theme.NCTheme.warning : Theme.NCTheme.error
                }
                Label { text: modelData.label + " · " + modelData.state; color: Theme.NCTheme.textSecondary }
            }
        }
    }
    Flow {
        Layout.fillWidth: true
        spacing: 8
        Repeater {
            model: [{ key: "connect", label: qsTr("Connect") }, { key: "internet", label: qsTr("Internet") }, { key: "media", label: qsTr("Media") }, { key: "usage", label: qsTr("Data usage") }, { key: "advanced", label: qsTr("Advanced") }]
            delegate: NCButton {
                id: tabButton
                required property var modelData
                objectName: "remoteTab_" + modelData.key
                text: modelData.label
                tone: "secondary"
                background: Rectangle {
                    radius: Theme.NCMetrics.radiusMedium
                    color: root.currentTab === tabButton.modelData.key ? Theme.NCTheme.accentSoft : tabButton.backgroundColor()
                    border.width: root.currentTab === tabButton.modelData.key || tabButton.activeFocus ? 2 : 1
                    border.color: tabButton.activeFocus ? Theme.NCTheme.focus : root.currentTab === tabButton.modelData.key ? Theme.NCTheme.accent : Theme.NCTheme.borderSubtle
                }
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData.label
                onClicked: root.currentTab = modelData.key
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: tabTutorials.openFor(tabButton,
                        {workspace: "addons", addon: "main_chat_remote_tab", remote_tab: String(tabButton.modelData.key)})
                }
            }
        }
    }
    ScrollView {
        id: pageScroll
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        contentWidth: availableWidth
        GridLayout {
            width: pageScroll.availableWidth
            columns: root.wide ? 3 : 1
            columnSpacing: 16
            rowSpacing: 16
            Card {
                objectName: "remotePairPhone"
                visible: root.currentTab === "connect"
                Layout.columnSpan: root.wide ? 2 : 1
                title: qsTr("Pair your phone")
                description: qsTr("Choose your phone for setup help. Both use this same connection.")
                RowLayout {
                    NCButton {
                        objectName: "remoteAndroid"
                        text: qsTr("Android")
                        tone: root.phonePlatform === "android" ? "primary" : "quiet"
                        onClicked: root.phonePlatform = "android"
                    }
                    NCButton {
                        objectName: "remoteIphone"
                        text: qsTr("iPhone")
                        tone: root.phonePlatform === "ios" ? "primary" : "quiet"
                        onClicked: root.phonePlatform = "ios"
                    }
                }
                Copy {
                    objectName: "remotePlatformHelp"
                    text: root.phonePlatform === "android"
                          ? qsTr("Install the project's Android APK, open NeuralCompanion and scan this QR from its connection screen. Allow camera and microphone access when requested.")
                          : qsTr("Open the project's iPhone app and scan this QR from its connection screen. Allow local network, camera and microphone access when requested. Use a compatible iPhone build for native voice features.")
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.ready
                    Rectangle {
                        color: "white"
                        implicitWidth: Math.min(220, root.availableWidth - 64)
                        implicitHeight: implicitWidth
                        Image {
                            objectName: "remotePairingQr"
                            anchors.fill: parent
                            anchors.margins: 8
                            source: root.ready ? String(root.field("main_chat_remote_pairing_qr").value || "") : ""
                            fillMode: Image.PreserveAspectFit
                            smooth: false
                        }
                    }
                    Item { Layout.fillWidth: true }
                }
                Copy { visible: !root.ready; text: qsTr("Your pairing QR appears here once the phone backend is ready.") }
                Copy { visible: root.ready; text: qsTr("Keep your phone and PC on the same network. Scan the QR, then tap Connect on your phone.") }
                NCButton {
                    text: qsTr("Copy setup link")
                    visible: root.ready
                    onClicked: root.act("main_chat_remote_copy_setup")
                }
                Disclosure { id: manualToggle; objectName: "remoteManualToggle"; caption: qsTr("Manual pairing") }
                Controls {
                    visible: manualToggle.expanded
                    ids: ["main_chat_remote_pairing_setup", "main_chat_remote_pairing_code", "main_chat_remote_generate_code"]
                }
            }
            Card {
                objectName: "remoteCheck"
                visible: root.currentTab === "connect"
                Layout.columnSpan: root.wide ? 1 : 1
                title: qsTr("Check the connection")
                Copy { text: qsTr("1. Confirm Connected on the phone.\n2. Send a short text message.\n3. Play a voice reply.\n4. Try Live Mic at desk distance.\n5. Check persona moods and video, if enabled.") }
                NCButton { text: qsTr("Refresh status"); onClicked: root.act("main_chat_remote_refresh") }
                Copy { text: qsTr("If speech is missed, adjust input sensitivity in the phone's Settings and check its microphone permission.") }
            }
            Card {
                objectName: "remoteInternet"
                visible: root.currentTab === "internet"
                Layout.columnSpan: root.wide ? 2 : 1
                title: qsTr("Internet access")
                description: qsTr("Optional · Connect when you are away from home.")
                NCRelaySettings { Layout.fillWidth: true; bridge: root.bridge; relay: root.field("main_chat_relay_status") }
            }
            Card {
                objectName: "remotePhones"
                visible: root.currentTab === "internet"
                Layout.columnSpan: root.wide ? 1 : 1
                title: qsTr("Your phones")
                Copy { text: qsTr("For LAN pairing, check that the phone app says Connected. Backend readiness alone does not confirm a phone connection.") }
                Copy { text: qsTr("Internet phones connect through your NC Relay account. Active peer connections: ") + Number(root.field("main_chat_relay_status").peer_count || 0) }
            }
            Card {
                objectName: "remoteMediaQuality"
                visible: root.currentTab === "media"
                Layout.columnSpan: root.wide ? 2 : 1
                title: qsTr("Audio and video quality")
                description: qsTr("Shared by streamed video and cached idle animations on LAN and Internet. Reconnect the phone after changing quality; current speech is not interrupted. Bitrates are targets, not measured usage.")
                Controls { ids: ["main_chat_remote_quality_preset"] }
                Disclosure { id: qualityToggle; caption: qsTr("Advanced quality controls") }
                Controls {
                    visible: qualityToggle.expanded
                    ids: ["main_chat_remote_quality_opus_kbps", "main_chat_remote_quality_video_kbps", "main_chat_remote_quality_video_width", "main_chat_remote_quality_video_fps"]
                }
                Copy { text: qsTr("Video keeps its aspect ratio (height is capped at 1.5 × maximum width). Lower frame rates reduce motion smoothness. Phone Native voice is unchanged.") }
            }
            Card {
                objectName: "remoteIdleCache"
                visible: root.currentTab === "media"
                Layout.columnSpan: root.wide ? 1 : 1
                title: qsTr("Phone idle animations")
                description: qsTr("Optional complete silent H.264 loops, downloaded once per avatar and quality. Shared mood loops are stored once. Speech stays streamed.")
                Controls { ids: ["main_chat_remote_idle_enabled", "main_chat_remote_idle_clear"] }
                Copy { text: qsTr("Uses the video bitrate, resolution and frame rate above, including custom settings. Changed video settings replace cached loops. Until reconnect, mismatched cached quality is not displayed; idle video stays streamed.") }
                Copy { text: qsTr("When off, no idle loops are downloaded or played from cache; idle video is streamed. Existing files are kept until cleared or the avatar changes. Clear applies when each phone next connects with caching enabled. Phone storage shows download progress. Requires an updated native phone build.") }
            }
            Card {
                objectName: "remoteDataUsage"
                visible: root.currentTab === "usage"
                Layout.columnSpan: root.wide ? 3 : 1
                title: qsTr("Data usage")
                description: qsTr("All phones · LAN + Internet · since reset")
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Copy { Layout.preferredWidth: 80; text: qsTr("Traffic") }
                        Copy { Layout.preferredWidth: 95; text: qsTr("Sent ↓ phone") }
                        Copy { Layout.preferredWidth: 95; text: qsTr("Received ↑ PC") }
                    }
                    Repeater {
                        model: ["audio", "video", "other", "transport_extra"]
                        delegate: RowLayout {
                            required property string modelData
                            Layout.fillWidth: true
                            spacing: 10
                            Copy { Layout.preferredWidth: 80; text: modelData === "audio" ? qsTr("Audio") : modelData === "video" ? qsTr("Video") : modelData === "other" ? qsTr("Other") : qsTr("Transport extra") }
                            Copy { Layout.preferredWidth: 95; text: root.usage(modelData, "sent") }
                            Copy { Layout.preferredWidth: 95; text: root.usage(modelData, "received") }
                        }
                    }
                }
                NCButton { objectName: "remoteResetStatistics"; text: qsTr("Reset statistics"); onClicked: root.act("main_chat_remote_traffic_reset") }
                Copy { font.pixelSize: 11; text: qsTr("Media/application bytes, updated about every 2 seconds. Other includes commands, photos and state. Transport extra estimates WebRTC overhead/retries from transport counters. HTTP/IP headers, TURN framing, relay signaling and carrier billing are not included. Reset does not disconnect phones.") }
            }
            Card {
                objectName: "remoteServices"
                visible: root.currentTab === "advanced"
                Layout.columnSpan: root.wide ? 1 : 1
                title: qsTr("Service status")
                Copy { text: qsTr("Desktop bridge · ") + (root.connection.bridgeRunning ? qsTr("Running") : qsTr("Stopped")) }
                Copy { text: qsTr("Phone backend · ") + (root.connection.backendRunning ? qsTr("Running") : qsTr("Stopped")) }
                Copy { text: root.ready ? qsTr("Backend health · Ready") : qsTr("Backend health · Not ready") }
                Disclosure { id: serviceToggle; objectName: "remoteServiceToggle"; caption: qsTr("Individual controls") }
                Controls {
                    visible: serviceToggle.expanded
                    ids: ["main_chat_remote_enabled", "main_chat_remote_start_bridge", "main_chat_remote_stop_bridge", "main_chat_remote_prepare_backend", "main_chat_remote_start_backend", "main_chat_remote_stop_backend"]
                }
            }
            Card {
                objectName: "remoteTroubleshooting"
                visible: root.currentTab === "advanced"
                Layout.columnSpan: root.wide ? 2 : 1
                title: qsTr("Troubleshooting")
                Disclosure { id: troubleshootingToggle; objectName: "remoteTroubleshootingToggle"; caption: qsTr("Show details and diagnostics") }
                Controls {
                    visible: troubleshootingToggle.expanded
                    ids: ["main_chat_remote_bridge_status", "main_chat_remote_backend_status", "main_chat_remote_bridge_info", "main_chat_remote_show_backend_command", "main_chat_internet_copy_diagnostics"]
                }
                Controls {
                    visible: troubleshootingToggle.expanded && Boolean(root.field("main_chat_remote_show_backend_command").value)
                    ids: ["main_chat_remote_backend_command"]
                }
            }
        }
    }
}
