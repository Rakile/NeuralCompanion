pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Item {
    id: root

    property real renderProgress: 0.0
    property real playbackProgress: 0.0
    property real phoneReadyProgress: 0.0
    property bool phoneReadyVisible: false
    property real downloadReadyProgress: 0.0
    property bool downloadReadyVisible: false
    property string downloadReadyLabel: ""
    property string renderLabel: ""
    property string phoneReadyLabel: ""
    property string playbackLabel: ""
    property bool active: false
    property bool failed: false
    property string summary: qsTr("Waiting for TTS")

    implicitHeight: raceGrid.implicitHeight
    Accessible.name: qsTr("TTS buffer race. %1").arg(summary)

    GridLayout {
        id: raceGrid
        anchors.fill: parent
        columns: 3
        columnSpacing: Theme.NCMetrics.space8
        rowSpacing: Theme.NCMetrics.space4

        Label {
            text: qsTr("Render")
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.captionSize
            Layout.preferredWidth: 58
        }
        Item {
            Layout.fillWidth: true
            implicitHeight: 8

            Rectangle {
                anchors.fill: parent
                radius: height / 2
                color: Theme.NCTheme.surfaceRaised
            }
            Rectangle {
                width: parent.width * Math.max(0.0, Math.min(root.renderProgress, 1.0))
                height: parent.height
                radius: height / 2
                color: root.failed ? Theme.NCTheme.error : Theme.NCTheme.accent

                Behavior on width {
                    NumberAnimation { duration: Theme.NCMetrics.motionNormal; easing.type: Easing.OutCubic }
                }
            }
        }
        Label {
            text: root.renderLabel || Math.round(Math.max(0.0, Math.min(root.renderProgress, 1.0)) * 100) + "%"
            color: root.failed ? Theme.NCTheme.error : Theme.NCTheme.textMuted
            horizontalAlignment: Text.AlignRight
            font.pixelSize: Theme.NCTypography.captionSize
            font.family: Theme.NCTypography.monoFamily
            Layout.preferredWidth: root.downloadReadyVisible ? 220 : root.phoneReadyVisible ? 130 : 42
        }

        Label {
            visible: root.downloadReadyVisible
            text: qsTr("Download-ready")
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.captionSize
            Layout.preferredWidth: 100
        }
        Item {
            visible: root.downloadReadyVisible
            Layout.fillWidth: true
            implicitHeight: 8
            Rectangle { anchors.fill: parent; radius: height / 2; color: Theme.NCTheme.surfaceRaised }
            Rectangle {
                width: parent.width * Math.max(0.0, Math.min(root.downloadReadyProgress, 1.0))
                height: parent.height
                radius: height / 2
                color: root.failed ? Theme.NCTheme.error : Theme.NCTheme.info
                Behavior on width {
                    NumberAnimation { duration: Theme.NCMetrics.motionNormal; easing.type: Easing.OutCubic }
                }
            }
        }
        Label {
            visible: root.downloadReadyVisible
            text: root.downloadReadyLabel
            color: Theme.NCTheme.textMuted
            horizontalAlignment: Text.AlignRight
            font.pixelSize: Theme.NCTypography.captionSize
            font.family: Theme.NCTypography.monoFamily
            Layout.preferredWidth: 220
        }

        Label {
            visible: root.phoneReadyVisible
            text: qsTr("Phone-ready")
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.captionSize
            Layout.preferredWidth: root.phoneReadyVisible ? 82 : 58
        }
        Item {
            visible: root.phoneReadyVisible
            Layout.fillWidth: true
            implicitHeight: 8
            Rectangle { anchors.fill: parent; radius: height / 2; color: Theme.NCTheme.surfaceRaised }
            Rectangle {
                width: parent.width * Math.max(0.0, Math.min(root.phoneReadyProgress, 1.0))
                height: parent.height
                radius: height / 2
                color: root.failed ? Theme.NCTheme.error : Theme.NCTheme.warning
                Behavior on width {
                    NumberAnimation { duration: Theme.NCMetrics.motionNormal; easing.type: Easing.OutCubic }
                }
            }
        }
        Label {
            visible: root.phoneReadyVisible
            text: root.phoneReadyLabel
            color: Theme.NCTheme.textMuted
            horizontalAlignment: Text.AlignRight
            font.pixelSize: Theme.NCTypography.captionSize
            font.family: Theme.NCTypography.monoFamily
            Layout.preferredWidth: 130
        }

        Label {
            text: qsTr("Playback")
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.captionSize
            Layout.preferredWidth: 58
        }
        Item {
            Layout.fillWidth: true
            implicitHeight: 8

            Rectangle {
                anchors.fill: parent
                radius: height / 2
                color: Theme.NCTheme.surfaceRaised
            }
            Rectangle {
                width: parent.width * Math.max(0.0, Math.min(root.playbackProgress, 1.0))
                height: parent.height
                radius: height / 2
                color: root.failed ? Theme.NCTheme.error : Theme.NCTheme.success

                Behavior on width {
                    NumberAnimation { duration: Theme.NCMetrics.motionNormal; easing.type: Easing.OutCubic }
                }
            }
        }
        Label {
            text: root.playbackLabel || Math.round(Math.max(0.0, Math.min(root.playbackProgress, 1.0)) * 100) + "%"
            color: root.failed ? Theme.NCTheme.error : Theme.NCTheme.textMuted
            horizontalAlignment: Text.AlignRight
            font.pixelSize: Theme.NCTypography.captionSize
            font.family: Theme.NCTypography.monoFamily
            Layout.preferredWidth: root.phoneReadyVisible ? 130 : 42
        }
    }
}
