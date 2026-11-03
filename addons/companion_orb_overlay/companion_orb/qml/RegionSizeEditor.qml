import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../../ui/qml/components"
import "../../../../ui/qml/theme" as Theme

Rectangle {
    width: 360
    height: 250
    color: Theme.NCTheme.window
    focus: true
    Keys.onEscapePressed: if (regionEditor) regionEditor.cancel()
    Shortcut { sequence: "Escape"; onActivated: if (regionEditor) regionEditor.cancel() }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 12
        Label { text: "Region around Orb"; color: Theme.NCTheme.text; font.pixelSize: 18; font.family: Theme.NCTypography.family }
        Label { text: "Live preview • clipped at screen edges"; color: Theme.NCTheme.textSecondary; font.family: Theme.NCTypography.family }
        RowLayout {
            Label { text: "Width"; color: Theme.NCTheme.text; font.family: Theme.NCTypography.family; Layout.fillWidth: true }
            NCSpinBox {
                label: "Region width"
                toolTipText: qsTr("Capture-region width in desktop logical pixels, from 64 to 2560. The preview is clipped at screen edges. Done applies the draft size; Cancel or Escape discards it.")
                objectName: "regionWidthInput"
                from: 64; to: 2560; editable: true
                value: regionEditor ? regionEditor.regionWidth : 640
                onValueModified: if (regionEditor) regionEditor.setWidth(value)
            }
        }
        RowLayout {
            Label { text: "Height"; color: Theme.NCTheme.text; font.family: Theme.NCTypography.family; Layout.fillWidth: true }
            NCSpinBox {
                label: "Region height"
                toolTipText: qsTr("Capture-region height in desktop logical pixels, from 64 to 1440. The preview is clipped at screen edges. Done applies the draft size; Cancel or Escape discards it.")
                objectName: "regionHeightInput"
                from: 64; to: 1440; editable: true
                value: regionEditor ? regionEditor.regionHeight : 420
                onValueModified: if (regionEditor) regionEditor.setHeight(value)
            }
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            NCButton { text: "Cancel"; onClicked: if (regionEditor) regionEditor.cancel() }
            NCButton { objectName: "regionDoneButton"; text: "Done"; tone: "primary"; onClicked: if (regionEditor) regionEditor.accept() }
        }
    }
}
