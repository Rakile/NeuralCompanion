pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../theme" as Theme

Window {
    id: root

    required property var bridge
    property string previewKind: "visualReply"
    readonly property bool isVisualReply: previewKind === "visualReply"
    property bool avatarOnly: false
    onIsVisualReplyChanged: if (isVisualReply) avatarOnly = false
    readonly property var previewState: isVisualReply
                                                ? bridge.visualReplyState
                                                : bridge.musetalkState
    readonly property string imageUrl: String(previewState.imageUrl || "")
    readonly property bool previewActive: visible && visibility !== Window.Minimized

    objectName: isVisualReply ? "visualReplyPreviewWindow" : "musetalkPreviewWindow"
    title: bridge.applicationTitle + " · "
           + (isVisualReply ? qsTr("Visual Reply") : qsTr("Avatar Preview"))
    color: Theme.NCTheme.window
    minimumWidth: avatarOnly ? 160 : 560
    minimumHeight: avatarOnly ? 160 : 420
    width: 820
    height: 640
    visible: false
    flags: Qt.Window

    onPreviewActiveChanged: {
        if (!isVisualReply)
            bridge.setMusetalkPreviewVisible("floating", previewActive)
    }
    Component.onCompleted: {
        if (!isVisualReply)
            bridge.setMusetalkPreviewVisible("floating", previewActive)
    }
    Component.onDestruction: {
        if (!isVisualReply)
            bridge.setMusetalkPreviewVisible("floating", false)
    }

    function showAndRaise() {
        if (visibility === Window.Minimized)
            showNormal()
        else
            show()
        raise()
        requestActivate()
    }

    NCCard {
        visible: !root.avatarOnly
        anchors.fill: parent
        anchors.margins: Theme.NCMetrics.space16
        elevated: true
        title: root.isVisualReply ? qsTr("Visual Reply") : qsTr("Avatar Preview")
        description: root.isVisualReply
                     ? qsTr("Current image from the existing Visual Reply runtime")
                     : qsTr("Live frames from the selected avatar provider")

        headerAccessory: RowLayout {
            NCButton {
                objectName: "avatarOnlyButton"
                visible: !root.isVisualReply
                text: qsTr("Avatar only")
                compact: true
                toolTipText: qsTr("Hide preview controls and padding. Hover to restore them, or press Esc.")
                onClicked: root.avatarOnly = true
            }
            NCStatusChip {
                text: String(root.previewState.status_text
                             || root.previewState.status
                             || qsTr("Idle"))
                status: String(root.previewState.status || "disconnected")
            }
            NCButton {
                visible: root.isVisualReply
                text: qsTr("Clear")
                compact: true
                tone: "danger"
                enabled: root.imageUrl.length > 0
                onClicked: root.bridge.clearVisualReply()
            }
            NCButton {
                objectName: "musetalkResetZoomButton"
                visible: !root.isVisualReply
                text: qsTr("Reset zoom")
                compact: true
                tone: "quiet"
                toolTipText: qsTr("Alt + mouse wheel to zoom at the pointer. Hold the middle mouse button and drag to pan. Reset fits and centers the image.")
                onClicked: { avatarPreviewImage.resetZoom(); root.bridge.resetMusetalkZoom() }
            }
            NCButton {
                visible: !root.isVisualReply
                text: qsTr("Avatar focus")
                compact: true
                onClicked: root.bridge.toggleAvatarFocus()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.window
            border.color: Theme.NCTheme.borderSubtle
            clip: true

            Image {
                objectName: "visualReplyFloatingImage"
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space12
                source: root.isVisualReply ? root.imageUrl : ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                retainWhileLoading: !root.isVisualReply
                cache: false
                smooth: true
                mipmap: root.isVisualReply
                visible: root.isVisualReply && root.imageUrl.length > 0
            }

            NCMuseTalkPreviewImage {
                id: avatarPreviewImage
                objectName: "musetalkFloatingImage"
                anchors.fill: parent
                anchors.margins: root.avatarOnly ? 0 : Theme.NCMetrics.space12
                previewState: root.isVisualReply ? ({}) : root.previewState
                visible: !root.isVisualReply && root.imageUrl.length > 0
            }

            NCEmptyState {
                anchors.centerIn: parent
                width: Math.min(parent.width - Theme.NCMetrics.space24, 460)
                visible: root.imageUrl.length === 0
                glyph: root.isVisualReply ? "▣" : "◉"
                title: root.isVisualReply
                       ? qsTr("No visual reply selected")
                       : qsTr("Preview is idle")
                description: root.isVisualReply
                             ? String(root.previewState.detail_text
                                      || qsTr("Generated images will appear here."))
                             : qsTr("Avatar frames will appear here when the selected provider is active.")
            }
        }

        Label {
            Layout.fillWidth: true
            text: root.isVisualReply
                  ? String(root.previewState.caption || "")
                  : String(root.previewState.status_text
                           || root.previewState.status
                           || qsTr("Waiting for avatar preview frames."))
            color: Theme.NCTheme.textSecondary
            font.pixelSize: Theme.NCTypography.captionSize
            wrapMode: Text.Wrap
            visible: text.length > 0
        }
    }

    StateGroup {
        states: State {
            name: "avatarOnly"
            when: root.avatarOnly && !root.isVisualReply
            ParentChange { target: avatarPreviewImage; parent: root.contentItem }
        }
    }

    NCAvatarOnlyControls {
        anchors.fill: parent
        visible: root.avatarOnly
        onRestoreRequested: root.avatarOnly = false
    }
}
