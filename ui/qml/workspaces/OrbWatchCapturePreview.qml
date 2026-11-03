import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Rectangle {
    id: root
    property var capture: ({})
    signal openRequested(string url)
    function openOriginal() {
        if (capture.imageUrl && captureImage.status === Image.Ready)
            openRequested(String(capture.imageUrl))
    }
    visible: Boolean(capture.timestamp)
    implicitHeight: visible ? previewColumn.implicitHeight + 16 : 0
    radius: Theme.NCMetrics.radiusMedium
    color: Theme.NCTheme.windowRaised
    border.color: Theme.NCTheme.border

    ColumnLayout {
        id: previewColumn
        anchors.fill: parent
        anchors.margins: 8
        Image {
            id: captureImage
            objectName: "orbWatchCaptureImage"
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 140 : 0
            source: String(root.capture.imageUrl || "")
            visible: source.toString().length > 0 && status !== Image.Error
            fillMode: Image.PreserveAspectFit
            asynchronous: true
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("Orb watch capture · %1").arg(String(root.capture.timestamp || ""))
            color: Theme.NCTheme.textSecondary
            font.pixelSize: Theme.NCTypography.microSize
            wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            text: root.capture.imageUrl && captureImage.status !== Image.Error
                  ? qsTr("Click to open the original capture") : qsTr("Capture unavailable")
            color: Theme.NCTheme.textSecondary
            font.pixelSize: Theme.NCTypography.microSize
            wrapMode: Text.Wrap
        }
    }
    TapHandler { onTapped: root.openOriginal() }
}
