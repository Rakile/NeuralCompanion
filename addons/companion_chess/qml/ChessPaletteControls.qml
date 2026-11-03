import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../../../ui/qml/components" as NC
import "../../../ui/qml/theme" as Theme
import "PadGroups.js" as PadGroups

ColumnLayout {
    id: root
    required property var workspace
    property string editingRole: ""
    spacing: Theme.NCMetrics.space10
    ChessLabel { text: "Board colours & move path"; color: Theme.NCTheme.text; font.weight: Font.DemiBold }
    ChessLabel {
        Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize
        text: "Saved for " + root.workspace.styleName + ". Applies to the onscreen board and connected Launchpad. Pro uses RGB; S approximates colours with red/green LEDs."
    }
    Repeater {
        model: ["Dark squares","Light squares","White occupancy","Black occupancy","Legal destinations","Pending step","Selected piece","Move path"]
        RowLayout {
            required property string modelData
            required property int index
            Layout.fillWidth: true
            ChessLabel { Layout.fillWidth: true; text: parent.modelData }
            Rectangle {
                width: 28; height: 28; radius: 5; border.color: Theme.NCTheme.textSecondary
                color: PadGroups.colour(parent.index,root.workspace.boardModel !== "style",root.workspace.styleName,root.workspace.light.palette)
            }
            NC.NCButton {
                text: "Choose…"
                onClicked: {
                    root.editingRole=PadGroups.roles[parent.index]
                    chooser.selectedColor=PadGroups.colour(parent.index,root.workspace.boardModel !== "style",root.workspace.styleName,root.workspace.light.palette)
                    chooser.open()
                }
            }
        }
    }
    ColorDialog {
        id: chooser
        objectName: "chessPaletteChooser"
        title: "Choose board colour"
        onAccepted: {
            let palette=Object.assign({},root.workspace.light.palette || {})
            palette[root.editingRole]=Qt.rgba(selectedColor.r,selectedColor.g,selectedColor.b,1).toString()
            root.workspace.changeLight("palette",palette)
        }
    }
    NC.NCButton { Layout.fillWidth: true; text: "Reset colours for this setup"; onClicked: root.workspace.changeLight("palette",{}) }
    NC.NCSwitch {
        objectName: "chessFlowingPath"; Layout.fillWidth: true; text: "Slow flowing move path"
        checked: root.workspace.light.flowing_path === true
        onToggled: root.workspace.changeLight("flowing_path",checked)
    }
    ChessLabel {
        Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize
        text: "A gentle pulse follows the pending or latest move. Selected pieces, legal destinations and physical placement instructions stay clearly marked."
    }
}
