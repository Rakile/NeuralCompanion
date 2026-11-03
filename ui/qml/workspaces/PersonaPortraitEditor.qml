pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../components"
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "personaPortraitEditor"
    property var rows: []
    property int selectedIndex: 0
    readonly property var selected: rows[selectedIndex] || ({})
    readonly property string selectedTag: String(selected.tag || "neutral")
    property bool busy: false
    property bool saveEnabled: !busy
    property string saveText: qsTr("Save changes")
    property string savedRows: "[]"
    readonly property bool dirty: JSON.stringify(rows) !== savedRows
    signal cancelRequested
    signal saveRequested
    spacing: Theme.NCMetrics.space12

    function loadRows(values) {
        rows = JSON.parse(JSON.stringify(values || []))
        savedRows = JSON.stringify(rows)
        selectedIndex = 0
    }
    function updateField(key, value) {
        const next = rows.slice()
        if (selectedIndex < 0 || selectedIndex >= next.length)
            return
        const row = Object.assign({}, next[selectedIndex])
        row[key] = value
        next[selectedIndex] = row
        rows = next
    }
    function addMood() {
        const next = rows.slice()
        let tag = "excited"
        let number = 2
        while (next.some(function(row) { return row.tag === tag }))
            tag = "custom_" + number++
        next.push({tag: tag, path: "", url: "", hint: ""})
        rows = next
        selectedIndex = next.length - 1
        tagField.forceActiveFocus()
        tagField.selectAll()
    }

    RowLayout {
        Layout.fillWidth: true
        Label { text: qsTr("Your portraits"); color: Theme.NCTheme.text; Layout.fillWidth: true }
        NCButton { objectName: "addPersonaMoodButton"; text: qsTr("+ Add mood"); enabled: !root.busy; onClicked: root.addMood() }
    }
    ScrollView {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(158, portraitGrid.implicitHeight + 8)
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        GridLayout {
            id: portraitGrid
            width: parent.width
            columns: Math.max(2, Math.floor(width / 94))
            columnSpacing: 8
            rowSpacing: 8
            Repeater {
                model: root.rows
                delegate: Button {
                    id: tile
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 92
                    enabled: !root.busy
                    Accessible.name: qsTr("Edit mood %1").arg(String(modelData.tag))
                    onClicked: root.selectedIndex = index
                    background: Rectangle {
                        color: Theme.NCTheme.surfaceRaised
                        radius: Theme.NCMetrics.radiusSmall
                        border.width: root.selectedIndex === tile.index ? 2 : 1
                        border.color: root.selectedIndex === tile.index ? Theme.NCTheme.accent : Theme.NCTheme.border
                    }
                    contentItem: ColumnLayout {
                        Image { Layout.fillWidth: true; Layout.preferredHeight: 56; source: String(tile.modelData.url || ""); fillMode: Image.PreserveAspectFit; asynchronous: true }
                        Label { Layout.fillWidth: true; text: "[" + String(tile.modelData.tag) + "]"; color: Theme.NCTheme.text; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight }
                    }
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space16
        Image {
            objectName: "personaSelectedMoodPreview"
            Layout.preferredWidth: 250
            Layout.preferredHeight: 250
            Layout.minimumWidth: 250
            Layout.minimumHeight: 250
            Layout.alignment: Qt.AlignTop
            source: String(root.selected.url || "")
            fillMode: Image.PreserveAspectFit
            asynchronous: true
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: Theme.NCMetrics.space8
            Label { text: qsTr("Mood tag"); color: Theme.NCTheme.textSecondary }
            NCTextField {
                toolTipText: qsTr("Emotion or mood tag used to select this portrait. The neutral base tag is fixed; other entries can use your own labels.")

                id: tagField
                objectName: "personaMoodTagField"
                Layout.fillWidth: true
                text: root.selectedTag
                enabled: !root.busy && root.selectedIndex !== 0
                placeholderText: qsTr("e.g. excited")
                maximumLength: 32
                onTextEdited: root.updateField("tag", text.trim().toLowerCase())
            }
            Label { Layout.fillWidth: true; text: qsTr("Used in replies as [%1]").arg(root.selectedTag); color: Theme.NCTheme.textSecondary; wrapMode: Text.Wrap }
            Label { text: qsTr("When to use this mood (optional)"); color: Theme.NCTheme.textSecondary }
            NCTextField {
                toolTipText: qsTr("Describe when this mood portrait should be used. This helps identify the mood entry and is separate from the Persona's main system prompt.")

                objectName: "personaMoodHintField"
                Layout.fillWidth: true
                text: String(root.selected.hint || "")
                enabled: !root.busy && root.selectedIndex > 0
                placeholderText: qsTr("e.g. Delighted by a successful project")
                onTextEdited: root.updateField("hint", text)
            }
            Item { Layout.fillHeight: true }
            RowLayout {
                objectName: "personaPortraitActionRow"
                Layout.fillWidth: true
                NCButton {
                    objectName: "replacePersonaMoodImageButton"
                    Layout.preferredWidth: 128
                    Layout.minimumWidth: 0
                    text: root.selected.url ? qsTr("Replace image…") : qsTr("Choose image…")
                    enabled: !root.busy
                    onClicked: imagePicker.open()
                }
                NCButton {
                    objectName: "removePersonaMoodButton"
                    Layout.preferredWidth: 150
                    Layout.minimumWidth: 0
                    text: root.selectedIndex === 0 ? qsTr("Remove portrait") : qsTr("Remove mood")
                    tone: "quiet"
                    enabled: !root.busy
                             && (root.selectedIndex > 0
                                 || String(root.selected.path || "").length > 0
                                 || String(root.selected.url || "").length > 0)
                    onClicked: {
                        if (root.selectedIndex === 0) {
                            root.updateField("path", "")
                            root.updateField("url", "")
                            return
                        }
                        const next = root.rows.slice()
                        next.splice(root.selectedIndex, 1)
                        root.rows = next
                        root.selectedIndex = 0
                    }
                }
                Item { Layout.fillWidth: true }
                NCButton {
                    objectName: "personaPortraitCancelButton"
                    Layout.preferredWidth: 104
                    Layout.minimumWidth: 0
                    text: qsTr("Cancel")
                    enabled: !root.busy
                    onClicked: root.cancelRequested()
                }
                NCButton {
                    objectName: "personaPortraitSaveButton"
                    Layout.preferredWidth: 130
                    Layout.minimumWidth: 0
                    text: root.saveText
                    tone: "primary"
                    enabled: root.saveEnabled
                    onClicked: root.saveRequested()
                }
            }
        }
    }
    FileDialog {
        id: imagePicker
        title: qsTr("Choose mood portrait")
        nameFilters: [qsTr("Images (*.png *.jpg *.jpeg *.webp)")]
        onAccepted: {
            root.updateField("path", String(selectedFile))
            root.updateField("url", String(selectedFile))
        }
    }
}
