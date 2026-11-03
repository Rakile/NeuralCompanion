import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../../ui/qml/components"
import "../../../../ui/qml/theme" as Theme

Rectangle {
    width: 380
    height: content.implicitHeight + 32
    radius: 16
    color: Theme.NCTheme.window
    border.color: Theme.NCTheme.accent
    border.width: 1
    focus: true
    Keys.onEscapePressed: if (dropWatch) dropWatch.cancel()
    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 16
        spacing: 10
        Label {
            text: "Add watch of…"
            font.pixelSize: 18
            font.bold: true
            font.family: Theme.NCTypography.family
            color: Theme.NCTheme.text
        }
        Label {
            text: dropWatch ? dropWatch.subject : ""
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
            maximumLineCount: 3
            elide: Text.ElideRight
            Layout.fillWidth: true
            font.family: Theme.NCTypography.family
            color: Theme.NCTheme.text
        }
        Label {
            text: "Uses your selected capture: " + (dropWatch ? dropWatch.scope : "")
                  + ". Keep this subject visible there. Capture settings stay unchanged."
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            font.family: Theme.NCTypography.family
            color: Theme.NCTheme.textSecondary
        }
        Label {
            visible: text.length > 0
            text: dropWatch ? dropWatch.status : ""
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            font.family: Theme.NCTypography.family
            color: Theme.NCTheme.text
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            NCButton { text: dropWatch && dropWatch.added ? "Done" : "Not now"; onClicked: if (dropWatch) dropWatch.cancel() }
            NCButton {
                objectName: "dropWatchAddButton"
                visible: !dropWatch || !dropWatch.added
                text: "Add watch"
                tone: "primary"
                onClicked: if (dropWatch) dropWatch.addWatch()
            }
            NCButton {
                visible: dropWatch && dropWatch.status.length > 0
                text: "Open watches"
                onClicked: if (dropWatch) dropWatch.openWatches()
            }
        }
    }
}
