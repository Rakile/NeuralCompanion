pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Item {
    id: root
    property var entries: []
    property bool busy: false
    property string objectPrefix: "avatarEmotion"
    signal actionRequested(string action, string variantId)
    implicitHeight: column.implicitHeight
    implicitWidth: 600

    ColumnLayout {
        id: column
        width: root.width
        spacing: 12
        Repeater {
            model: root.entries || []
            delegate: Rectangle {
                id: row
                required property var modelData
                Layout.fillWidth: true
                implicitHeight: content.implicitHeight + 24
                radius: 12
                color: Theme.NCTheme.surface
                border.color: row.modelData.base ? Theme.NCTheme.accent : Theme.NCTheme.border
                ColumnLayout {
                    id: content
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 12
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        Image {
                            source: row.modelData.thumbnail || ""
                            visible: source.toString().length > 0
                            Layout.preferredWidth: 64
                            Layout.preferredHeight: 64
                            fillMode: Image.PreserveAspectFit
                            cache: false
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Label {
                                text: row.modelData.display_name || row.modelData.id
                                font.bold: true
                                color: Theme.NCTheme.text
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            Label {
                                text: (row.modelData.tags || []).join(", ")
                                color: Theme.NCTheme.textMuted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            Label {
                                text: (row.modelData.base ? qsTr("Base avatar · ") : "") + (row.modelData.prepared ? qsTr("Ready") : qsTr("Needs preparation"))
                                color: row.modelData.base ? Theme.NCTheme.accent : Theme.NCTheme.textMuted
                            }
                        }
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        NCButton {
                            objectName: root.objectPrefix + "_preview_" + row.modelData.id
                            text: qsTr("Preview")
                            enabled: !root.busy && Boolean(row.modelData.prepared)
                            toolTipText: qsTr("Preview this prepared avatar.")
                            onClicked: root.actionRequested("preview", row.modelData.id)
                        }
                        NCButton {
                            objectName: root.objectPrefix + "_redo_" + row.modelData.id
                            text: qsTr("Redo")
                            enabled: !root.busy && Boolean(row.modelData.canRedo)
                            toolTipText: row.modelData.redoHelp || qsTr("Prepare again from the saved source using your current settings. The old version stays until the replacement is ready.")
                            onClicked: root.actionRequested("redo", row.modelData.id)
                        }
                        NCButton {
                            objectName: root.objectPrefix + "_replace_" + row.modelData.id
                            text: qsTr("Replace source")
                            enabled: !root.busy && row.modelData.canReplace !== false
                            toolTipText: qsTr("Choose a different image or video for this entry. Keep its labels and base role.")
                            onClicked: root.actionRequested("replace", row.modelData.id)
                        }
                        NCButton {
                            objectName: root.objectPrefix + "_delete_" + row.modelData.id
                            text: qsTr("Delete")
                            tone: "danger"
                            enabled: !root.busy && Boolean(row.modelData.canDelete)
                            toolTipText: row.modelData.deleteHelp || qsTr("Permanently delete this entry and its own files. Original media outside its folder is kept.")
                            onClicked: root.actionRequested("delete", row.modelData.id)
                        }
                        NCButton {
                            objectName: root.objectPrefix + "_make_base_" + row.modelData.id
                            text: qsTr("Use as base")
                            visible: !Boolean(row.modelData.base)
                            enabled: !root.busy && Boolean(row.modelData.prepared)
                            toolTipText: qsTr("Use this as the package's default avatar when no other label matches.")
                            onClicked: root.actionRequested("make_base", row.modelData.id)
                        }
                    }
                }
            }
        }
    }
}
