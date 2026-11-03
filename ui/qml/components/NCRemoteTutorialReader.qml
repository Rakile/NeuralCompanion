pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    objectName: "remoteTutorialReader"
    required property var bridge
    readonly property var guide: bridge.tutorialState || ({})
    readonly property var view: guide.remoteView || ({})
    readonly property string stepKey: String(guide.id) + ":" + String(guide.stepIndex)
    property string ownerGuideId: ""
    function stopOwnedNarration() {
        narration.stop()
        if (bridge && bridge.tutorialState && bridge.tutorialState.id === ownerGuideId
                && typeof bridge.stopTutorialSpeech === "function") bridge.stopTutorialSpeech()
    }
    onStepKeyChanged: if (scroll.contentItem) scroll.contentItem.contentY = 0
    readonly property string narrationKey: String(guide.id) + ":" + String(guide.stepIndex) + ":" + String(guide.speechEnabled)
    title: String(guide.title || "NC Remote app")
    description: qsTr("Desktop walkthrough • Step %1 of %2 • Reading progress, not phone verification").arg(guide.stepNumber || 0).arg(guide.stepCount || 0)
    onNarrationKeyChanged: { if (visible && guide.speechEnabled) narration.restart(); else narration.stop() }
    onVisibleChanged: if (!visible) stopOwnedNarration()
    Component.onDestruction: stopOwnedNarration()
    Component.onCompleted: { ownerGuideId = String(guide.id || ""); if (visible && guide.speechEnabled) narration.restart() }
    Timer { id: narration; interval: 180; onTriggered: if (root.visible && root.guide.active && root.guide.speechEnabled) root.bridge.speakTutorialStep() }

    ScrollView {
        id: scroll
        objectName: "remoteTutorialScroll"
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        GridLayout {
            width: scroll.availableWidth
            columns: width >= 660 ? 2 : 1
            columnSpacing: 20; rowSpacing: 16
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 300
                Layout.alignment: Qt.AlignTop
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(580, width * 2.2456)
                    Image {
                        id: shot
                        objectName: "remoteTutorialScreenshot"
                        readonly property bool loaded: status === Image.Ready
                        anchors.fill: parent
                        source: root.view.screenshot || ""
                        fillMode: Image.PreserveAspectFit
                        sourceSize.width: 912
                        asynchronous: true
                        Item {
                            x: (shot.width-shot.paintedWidth)/2; y: (shot.height-shot.paintedHeight)/2
                            width: shot.paintedWidth; height: shot.paintedHeight
                            Rectangle {
                                readonly property var box: root.view.highlight || []
                                visible: shot.status === Image.Ready && box.length === 4
                                x: (box[0] || 0)*parent.width; y: (box[1] || 0)*parent.height
                                width: (box[2] || 0)*parent.width; height: (box[3] || 0)*parent.height
                                color: "transparent"; border.width: 3; border.color: Theme.NCTheme.accent; radius: 6
                            }
                        }
                    }
                    Label {
                        anchors.centerIn: parent; width: parent.width
                        visible: shot.status === Image.Error || !shot.source.toString()
                        text: qsTr("Screenshot unavailable. You can still follow the written instructions.")
                        color: Theme.NCTheme.textSecondary; wrapMode: Text.WordWrap
                    }
                }
                Label { Layout.fillWidth: true; text: root.view.caption || ""; color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap }
                NCButton { text: qsTr("Enlarge screenshot"); enabled: shot.status === Image.Ready; onClicked: enlarged.open() }
                Label { Layout.fillWidth: true; visible: !!root.view.gesture; text: root.view.gesture || ""; color: Theme.NCTheme.accent; wrapMode: Text.WordWrap }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 340; Layout.alignment: Qt.AlignTop
                spacing: 12
                NCStatusChip { text: root.view.device || ""; status: "info" }
                Label { Layout.fillWidth: true; text: root.guide.stepTitle || ""; color: Theme.NCTheme.text; font.pixelSize: 22; wrapMode: Text.WordWrap }
                Label {
                    Layout.fillWidth: true
                    text: String(root.guide.stepBody || "").split("\n\nExpected result:")[0]
                    textFormat: Text.PlainText; color: Theme.NCTheme.text; font.pixelSize: 16; wrapMode: Text.WordWrap
                }
                Label { text: qsTr("Expected result"); color: Theme.NCTheme.accent; font.bold: true }
                Label { Layout.fillWidth: true; text: root.view.expected || ""; textFormat: Text.PlainText; color: Theme.NCTheme.textSecondary; wrapMode: Text.WordWrap }
                Label { text: qsTr("If it does not work"); color: Theme.NCTheme.text; font.bold: true }
                Label { Layout.fillWidth: true; text: root.view.recovery || ""; textFormat: Text.PlainText; color: Theme.NCTheme.textSecondary; wrapMode: Text.WordWrap }
            }
        }
    }
    Flow {
        Layout.fillWidth: true; spacing: 8
        NCSwitch { text: qsTr("Read aloud"); checked: root.guide.speechEnabled === true; onToggled: root.bridge.setTutorialSpeechEnabled(checked) }
        NCButton { text: qsTr("Hear step"); onClicked: root.bridge.speakTutorialStep() }
        NCButton { text: qsTr("Back"); enabled: root.guide.canGoBack === true; onClicked: root.bridge.previousTutorialStep() }
        NCButton { text: root.guide.canGoForward ? qsTr("Next") : qsTr("Finish"); tone: "primary"; onClicked: root.bridge.nextTutorialStep() }
        NCButton { text: qsTr("Close lesson"); onClicked: root.bridge.closeTutorial() }
    }
    Popup {
        id: enlarged
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(800, parent ? parent.width-32 : 800)
        height: parent ? parent.height-40 : 700
        modal: true; focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: Theme.NCTheme.windowRaised; border.color: Theme.NCTheme.border; radius: 10 }
        ColumnLayout {
            anchors.fill: parent
            Image { Layout.fillWidth: true; Layout.fillHeight: true; source: root.view.screenshot || ""; fillMode: Image.PreserveAspectFit }
            NCButton { text: qsTr("Close image"); onClicked: enlarged.close() }
        }
    }
}
