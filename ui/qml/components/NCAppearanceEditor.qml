pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    objectName: "appearanceEditor"
    required property var controller
    property var draft: ({})
    property string selectedRole: "accent"
    property bool dirty: false
    property string saveMessage: ""
    readonly property var preview: Theme.NCTheme.customPalette(draft)
    title: qsTr("Custom theme")
    description: qsTr("Choose a color below, then use the wheel and brightness slider. Preview changes here before saving.")
    selected: Theme.NCTheme.currentPreset === "custom"

    function discard() {
        draft = Object.assign({}, controller.colors)
        dirty = false
        saveMessage = ""
    }
    function updateColor(value) {
        const next = Object.assign({}, draft)
        next[selectedRole] = value
        draft = next
        dirty = true
        saveMessage = ""
    }
    Component.onCompleted: discard()
    Connections {
        target: root.controller
        function onStateChanged() { if (!root.dirty) root.discard() }
        function onSaved() { root.discard(); root.saveMessage = qsTr("Appearance saved.") }
    }

    GridLayout {
        Layout.fillWidth: true
        columns: root.width >= 660 ? 2 : 1
        columnSpacing: 24
        rowSpacing: 16
        enabled: !root.controller.busy

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: 12
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                Repeater {
                    model: [ {key: "accent", label: qsTr("Accent")}, {key: "window", label: qsTr("Background")},
                             {key: "surface", label: qsTr("Panels")}, {key: "text", label: qsTr("Text")} ]
                    delegate: NCButton {
                        required property var modelData
                        Layout.fillWidth: true
                        text: modelData.label
                        leftPadding: 34
                        tone: root.selectedRole === modelData.key ? "primary" : "secondary"
                        onClicked: root.selectedRole = modelData.key
                        Rectangle {
                            x: 10; anchors.verticalCenter: parent.verticalCenter
                            width: 16; height: 16; radius: 8
                            color: root.draft[parent.modelData.key] || "#000000"
                            border.color: Theme.NCTheme.textSecondary
                        }
                    }
                }
            }
            NCColorWheel {
                Layout.fillWidth: true
                selectedColor: root.draft[root.selectedRole] || "#31d5f4"
                onColorEdited: value => root.updateColor(value)
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: 12
            Label { text: qsTr("Live preview"); color: Theme.NCTheme.text; font.bold: true }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 240
                color: root.preview.window
                radius: 12
                border.color: root.preview.border
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 18
                    spacing: 12
                    Label { text: qsTr("Your companion workspace"); color: root.preview.text; Layout.fillWidth: true; wrapMode: Text.Wrap; font.bold: true }
                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        radius: 8; color: root.preview.surface; border.color: root.preview.border
                        Label {
                            anchors.fill: parent; anchors.margins: 14
                            text: qsTr("A comfortable place to chat.\nPanels and borders follow your colors.")
                            color: root.preview.text; wrapMode: Text.Wrap
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: 40
                        radius: 8; color: root.preview.accent
                        Label { anchors.centerIn: parent; text: qsTr("Sample button"); color: root.preview.textInverse }
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("Button states and borders are generated automatically. Text, panels and accent shades adjust when needed for readability.")
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
        }
    }
    Flow {
        Layout.fillWidth: true
        spacing: 8
        NCButton {
            objectName: "appearanceSave"
            text: root.controller.busy ? qsTr("Please wait…") : qsTr("Save and apply")
            tone: "primary"
            enabled: !root.controller.busy
            onClicked: root.controller.saveCustom(root.draft)
        }
        NCButton {
            objectName: "appearanceCancel"
            text: qsTr("Cancel")
            enabled: root.dirty && !root.controller.busy
            onClicked: root.discard()
        }
        NCButton {
            objectName: "appearanceReset"
            text: qsTr("Reset colors")
            enabled: !root.controller.busy
            onClicked: {
                const defaults = Theme.NCTheme.midnightPalette()
                root.draft = {accent: defaults.accent, window: defaults.window, surface: defaults.surface, text: defaults.text}
                root.dirty = true
                root.saveMessage = ""
            }
        }
    }
    Label {
        Layout.fillWidth: true
        visible: text.length > 0
        text: root.controller.error || root.saveMessage
        color: root.controller.error ? Theme.NCTheme.error : Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }
}
