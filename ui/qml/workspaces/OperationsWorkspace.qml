pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

ScrollView {
    id: root
    objectName: "operationsWorkspace"

    required property var bridge
    property string mode: "timing"
    property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
        bridge: root.bridge
        scrollView: root
        pageKey: "operations:" + root.mode
    }
    property int targetSamples: 5
    property bool autoReplies: false
    property string selectedProfile: ""
    readonly property var runtimeSnapshot: bridge.operationsState
    readonly property var speechTimingValues: bridge.speechTimingSettings
    clip: true
    contentWidth: availableWidth

    function standardTimingFields() {
        return [
            {
                "key": "chunk_target_chars",
                "label": qsTr("Target characters"),
                "description": qsTr("Preferred size for normal non-stream TTS chunks. Lower starts sooner; higher sounds more continuous."),
                "minimum": 40, "maximum": 220, "step": 1, "defaultValue": 100, "integer": true
            },
            {
                "key": "chunk_max_chars",
                "label": qsTr("Maximum characters"),
                "description": qsTr("Hard upper bound for normal non-stream chunks before text is split."),
                "minimum": 60, "maximum": 320, "step": 1, "defaultValue": 200, "integer": true
            }
        ]
    }

    function museTalkTimingFields() {
        return [
            {
                "key": "musetalk_chunk_target_chars",
                "label": qsTr("Target characters"),
                "description": qsTr("Preferred avatar non-stream chunk size. Smaller lowers wait time; larger reduces avatar transitions."),
                "minimum": 60, "maximum": 220, "step": 1, "defaultValue": 110, "integer": true
            },
            {
                "key": "musetalk_chunk_max_chars",
                "label": qsTr("Maximum characters"),
                "description": qsTr("Hard upper bound for normal avatar chunks."),
                "minimum": 80, "maximum": 320, "step": 1, "defaultValue": 220, "integer": true
            },
            {
                "key": "musetalk_quickstart_1_target_chars",
                "label": qsTr("Quickstart 1 target"),
                "description": qsTr("Preferred size for the first avatar startup chunk."),
                "minimum": 60, "maximum": 260, "step": 1, "defaultValue": 170, "integer": true
            },
            {
                "key": "musetalk_quickstart_1_max_chars",
                "label": qsTr("Quickstart 1 maximum"),
                "description": qsTr("Hard upper bound for the first avatar startup chunk."),
                "minimum": 80, "maximum": 360, "step": 1, "defaultValue": 320, "integer": true
            },
            {
                "key": "musetalk_quickstart_2_target_chars",
                "label": qsTr("Quickstart 2 target"),
                "description": qsTr("Preferred size for the second startup chunk that smooths the handoff after speech begins."),
                "minimum": 60, "maximum": 240, "step": 1, "defaultValue": 130, "integer": true
            },
            {
                "key": "musetalk_quickstart_2_max_chars",
                "label": qsTr("Quickstart 2 maximum"),
                "description": qsTr("Hard upper bound for the second avatar startup chunk."),
                "minimum": 80, "maximum": 320, "step": 1, "defaultValue": 240, "integer": true
            }
        ]
    }

    function streamingTimingFields() {
        return [
            {
                "key": "stream_chunk_target_chars",
                "label": qsTr("Target minimum characters"),
                "description": qsTr("Normally wait for at least this many characters before choosing a sentence boundary. The flush deadline may produce a shorter chunk."),
                "minimum": 40, "maximum": 220, "step": 1, "defaultValue": 80, "integer": true
            },
            {
                "key": "stream_chunk_max_chars",
                "label": qsTr("Maximum characters"),
                "description": qsTr("Hard upper bound for streaming chunks before the stream is flushed."),
                "minimum": 60, "maximum": 320, "step": 1, "defaultValue": 185, "integer": true
            },
            {
                "key": "stream_first_chunk_min_chars",
                "label": qsTr("First chunk minimum"),
                "description": qsTr("Minimum text required before the first streaming chunk can be spoken."),
                "minimum": 10, "maximum": 80, "step": 1, "defaultValue": 40, "integer": true
            },
            {
                "key": "stream_force_flush_seconds",
                "label": qsTr("First flush"),
                "description": qsTr("Maximum wait before the first streaming chunk is sent, even below its target size."),
                "minimum": 0.2, "maximum": 2.5, "step": 0.01, "defaultValue": 0.30, "integer": false, "suffix": qsTr(" s")
            },
            {
                "key": "stream_force_flush_later_seconds",
                "label": qsTr("Later flush"),
                "description": qsTr("Maximum wait between later streaming chunks after speech has started."),
                "minimum": 0.3, "maximum": 4.0, "step": 0.01, "defaultValue": 0.70, "integer": false, "suffix": qsTr(" s")
            }
        ]
    }

    function speechTimingValue(field) {
        const key = String(field.key || "")
        if (root.speechTimingValues && root.speechTimingValues[key] !== undefined
                && root.speechTimingValues[key] !== null)
            return Number(root.speechTimingValues[key])
        return Number(field.defaultValue || 0)
    }

    function formattedSpeechTimingValue(field, value) {
        const formatted = Boolean(field.integer) ? String(Math.round(value)) : Number(value).toFixed(2)
        return formatted + String(field.suffix || "")
    }

    Component.onCompleted: bridge.refreshOperationsState()

    ColumnLayout {
        width: parent.width
        spacing: Theme.NCMetrics.space12

        NCCard {
            Layout.fillWidth: true
            elevated: true
            title: root.mode === "timing" ? qsTr("Pipeline and speech timing") : qsTr("Performance check")
            description: root.mode === "timing"
                         ? qsTr("Live, low-frequency status from the existing engine, STT capture, TTS queue, and playback services.")
                         : qsTr("Run the established bounded Dry Run workflow and load saved performance profiles.")
        }

        GridLayout {
            Layout.fillWidth: true
            columns: width >= 900 ? 3 : width >= 560 ? 2 : 1
            columnSpacing: Theme.NCMetrics.space12
            rowSpacing: Theme.NCMetrics.space12
            visible: root.mode === "timing"

            NCCard {
                Layout.fillWidth: true
                title: qsTr("Conversation engine")
                description: qsTr("Session lifecycle and current processing owner.")
                NCStatusChip {
                    text: root.bridge.systemRunning ? qsTr("Running") : qsTr("Stopped")
                    status: root.bridge.systemRunning ? "active" : "disconnected"
                }
            }

            NCCard {
                Layout.fillWidth: true
                title: qsTr("Speech input")
                description: qsTr("%1 · %2").arg(String(root.runtimeSnapshot.speechInput.backend_name || root.bridge.selectedSpeechInputBackend))
                             .arg(String(root.runtimeSnapshot.speechInput.device_label || qsTr("Default input")))
                NCStatusChip {
                    text: Boolean(root.runtimeSnapshot.speechInput.listening) ? qsTr("Listening")
                          : Boolean(root.runtimeSnapshot.speechInput.running) ? qsTr("Ready") : qsTr("Idle")
                    status: Boolean(root.runtimeSnapshot.speechInput.listening) ? "working"
                          : Boolean(root.runtimeSnapshot.speechInput.running) ? "active" : "disconnected"
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Active captures: %1").arg(Number(root.runtimeSnapshot.speechInput.active_captures || 0))
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.captionSize
                }
            }

            NCCard {
                Layout.fillWidth: true
                title: qsTr("Voice playback")
                description: qsTr("Current TTS audio route and bounded next-item queue.")
                NCStatusChip {
                    text: Boolean(root.runtimeSnapshot.playback.paused) ? qsTr("Paused")
                          : Boolean(root.runtimeSnapshot.playback.active) ? qsTr("Speaking") : qsTr("Idle")
                    status: Boolean(root.runtimeSnapshot.playback.paused) ? "warning"
                          : Boolean(root.runtimeSnapshot.playback.active) ? "working" : "disconnected"
                }
                Label {
                    Layout.fillWidth: true
                    text: Boolean(root.runtimeSnapshot.playback.queued) ? qsTr("One item is queued next") : qsTr("No queued playback")
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.captionSize
                }
            }
        }

        NCCard {
            Layout.fillWidth: true
            visible: root.mode === "timing"
            title: qsTr("Speech chunking and flush timing")
            description: qsTr("The original NeuralCompanion pipeline controls. Changes apply globally and are saved with the current session, not with a persona.")

            headerAccessory: NCButton {
                text: qsTr("Reset defaults")
                tone: "secondary"
                onClicked: root.bridge.resetSpeechTimingDefaults()
            }
        }

        SpeechTimingProfilesCard {
            Layout.fillWidth: true
            visible: root.mode === "timing"
            controller: root.mode === "timing" ? root.bridge.speechTimingProfiles : null
        }

        GridLayout {
            Layout.fillWidth: true
            visible: root.mode === "timing"
            columns: width >= 1100 ? 3 : width >= 720 ? 2 : 1
            columnSpacing: Theme.NCMetrics.space12
            rowSpacing: Theme.NCMetrics.space12

            Repeater {
                model: [
                    {
                        "title": qsTr("Standard"),
                        "description": qsTr("Non-stream speech chunk sizes when Ditto or MuseTalk is not active."),
                        "fields": root.standardTimingFields()
                    },
                    {
                        "title": qsTr("Avatar non-stream"),
                        "description": qsTr("Shared by Ditto and MuseTalk when streaming is off, including the first two quickstart chunks."),
                        "fields": root.museTalkTimingFields()
                    },
                    {
                        "title": qsTr("Avatar streaming"),
                        "description": qsTr("Shared streaming settings for Ditto, MuseTalk and speech without an avatar. Flush timing controls how soon text is sent to speech."),
                        "fields": root.streamingTimingFields()
                    }
                ]

                delegate: NCCard {
                    id: timingCard
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    title: String(modelData.title || "")
                    description: String(modelData.description || "")

                    Repeater {
                        model: timingCard.modelData.fields || []

                        delegate: ColumnLayout {
                            id: timingRow
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: Theme.NCMetrics.space4
                            property real pendingValue: root.speechTimingValue(modelData)
                            property bool hasPendingValue: false

                            function commitPendingValue() {
                                if (!hasPendingValue)
                                    return
                                const committed = Boolean(modelData.integer)
                                                ? Math.round(pendingValue)
                                                : Math.round(pendingValue * 100) / 100
                                hasPendingValue = false
                                root.bridge.setSpeechTimingSetting(String(modelData.key), committed)
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space8

                                Label {
                                    Layout.fillWidth: true
                                    text: String(timingRow.modelData.label || timingRow.modelData.key || "")
                                    color: Theme.NCTheme.text
                                    font.pixelSize: Theme.NCTypography.labelSize
                                    font.weight: Theme.NCTypography.medium
                                }
                                Label {
                                    text: root.formattedSpeechTimingValue(timingRow.modelData, timingRow.pendingValue)
                                    color: Theme.NCTheme.accentSoft
                                    font.pixelSize: Theme.NCTypography.labelSize
                                    font.weight: Theme.NCTypography.semibold
                                }
                            }

                            Label {
                                Layout.fillWidth: true
                                text: String(timingRow.modelData.description || "")
                                color: Theme.NCTheme.textMuted
                                font.pixelSize: Theme.NCTypography.captionSize
                                wrapMode: Text.Wrap
                            }

                            NCSlider {
                                toolTipText: String(timingRow.modelData.description || timingRow.modelData.help || "")

                                id: timingSlider
                                Layout.fillWidth: true
                                label: String(timingRow.modelData.label || timingRow.modelData.key || "")
                                from: Number(timingRow.modelData.minimum)
                                to: Number(timingRow.modelData.maximum)
                                stepSize: Number(timingRow.modelData.step || 1)
                                snapMode: Slider.SnapAlways
                                value: timingRow.pendingValue
                                onMoved: {
                                    timingRow.pendingValue = value
                                    timingRow.hasPendingValue = true
                                    if (!pressed)
                                        timingRow.commitPendingValue()
                                }
                                onPressedChanged: {
                                    if (!pressed)
                                        timingRow.commitPendingValue()
                                }
                            }

                            Connections {
                                target: root.bridge
                                function onSpeechTimingSettingsChanged() {
                                    if (!timingSlider.pressed) {
                                        timingRow.pendingValue = root.speechTimingValue(timingRow.modelData)
                                        timingRow.hasPendingValue = false
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        NCCard {
            Layout.fillWidth: true
            visible: root.mode === "timing"
            title: qsTr("Playback controls")
            description: qsTr("These buttons call the current runtime action service; they do not manipulate audio devices directly.")
            RowLayout {
                Layout.fillWidth: true
                NCButton {
                    text: Boolean(root.runtimeSnapshot.playback.paused) ? qsTr("Resume") : qsTr("Pause")
                    tone: "secondary"
                    enabled: root.bridge.systemRunning
                    onClicked: root.bridge.triggerRuntimeAction("pause_speech")
                }
                NCButton {
                    text: qsTr("Skip speech")
                    tone: "secondary"
                    enabled: root.bridge.systemRunning
                    onClicked: root.bridge.triggerRuntimeAction("skip_speech")
                }
                NCButton {
                    text: qsTr("Skip user turn")
                    tone: "secondary"
                    enabled: root.bridge.systemRunning
                    onClicked: root.bridge.triggerRuntimeAction("skip_user_reply")
                }
                Item { Layout.fillWidth: true }
                NCButton {
                    text: qsTr("Refresh")
                    tone: "secondary"
                    onClicked: root.bridge.refreshOperationsState()
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: width >= 880 ? 2 : 1
            columnSpacing: Theme.NCMetrics.space12
            rowSpacing: Theme.NCMetrics.space12
            visible: root.mode === "performance"

            NCCard {
                Layout.fillWidth: true
                title: qsTr("Dry Run session")
                description: Boolean(root.runtimeSnapshot.dryRun.active)
                             ? qsTr("The normal Dry Run observer is collecting bounded reply samples.")
                             : qsTr("A Dry Run temporarily evaluates response, speech, and avatar timing under the current stack.")

                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: qsTr("Reply samples")
                        color: Theme.NCTheme.textSecondary
                        font.pixelSize: Theme.NCTypography.captionSize
                    }
                    NCTextField {
                        toolTipText: qsTr("Number of replies collected for the timing and performance test, from 1 to 100. More samples give a broader measurement but take longer.")

                        Layout.fillWidth: true
                        label: qsTr("Reply samples")
                        text: String(root.targetSamples)
                        validator: IntValidator { bottom: 1; top: 100 }
                        onEditingFinished: root.targetSamples = Math.max(1, Math.min(100, parseInt(text)))
                    }
                }
                NCSwitch {
                    toolTipText: qsTr("Generate the test's sample replies automatically instead of waiting for manual inputs. This can make repeated model and speech requests.")

                    Layout.fillWidth: true
                    text: qsTr("Generate automatic sample replies")
                    checked: root.autoReplies
                    onClicked: root.autoReplies = checked
                }
                NCProgressBar {
                    Layout.fillWidth: true
                    value: Number(root.runtimeSnapshot.dryRun.sample_count || 0)
                    from: 0
                    to: Math.max(1, Number(root.runtimeSnapshot.dryRun.target_samples || root.targetSamples))
                    indeterminate: Boolean(root.runtimeSnapshot.dryRun.active) && Boolean(root.runtimeSnapshot.dryRun.auto_mode)
                }
                RowLayout {
                    Layout.fillWidth: true
                    NCStatusChip {
                        text: Boolean(root.runtimeSnapshot.dryRun.active) ? qsTr("Running")
                              : Boolean(root.runtimeSnapshot.dryRun.complete) ? qsTr("Complete") : qsTr("Ready")
                        status: Boolean(root.runtimeSnapshot.dryRun.active) ? "working"
                              : Boolean(root.runtimeSnapshot.dryRun.complete) ? "success" : "info"
                    }
                    Item { Layout.fillWidth: true }
                    NCButton {
                        text: Boolean(root.runtimeSnapshot.dryRun.active) ? qsTr("Stop") : qsTr("Start check")
                        tone: Boolean(root.runtimeSnapshot.dryRun.active) ? "danger" : "primary"
                        onClicked: {
                            if (root.runtimeSnapshot.dryRun.active)
                                root.bridge.stopDryRun()
                            else
                                root.bridge.startDryRun(root.targetSamples, root.autoReplies)
                        }
                    }
                }
            }

            NCCard {
                Layout.fillWidth: true
                title: qsTr("Saved performance profiles")
                description: qsTr("Profiles are loaded through the existing performance-profile validator and apply only its approved keys.")

                NCComboBox {
                    toolTipText: qsTr("Select a saved performance profile to inspect or apply with the profile actions. Choosing a list entry alone does not establish that its values are active.")

                    Layout.fillWidth: true
                    label: qsTr("Performance profile")
                    model: root.bridge.performanceProfiles
                    textRole: "display_name"
                    valueRole: "name"
                    onActivated: root.selectedProfile = String(currentValue || "")
                }
                RowLayout {
                    Layout.fillWidth: true
                    NCButton {
                        text: qsTr("Load profile")
                        enabled: root.selectedProfile.length > 0
                        onClicked: root.bridge.loadPerformanceProfile(root.selectedProfile)
                    }
                    NCButton {
                        text: qsTr("Apply latest recommendation")
                        tone: "secondary"
                        enabled: Boolean(root.runtimeSnapshot.dryRun.complete)
                        onClicked: root.bridge.applyDryRunRecommendation()
                    }
                }
            }
        }

    }
}
