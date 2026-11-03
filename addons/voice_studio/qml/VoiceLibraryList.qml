pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

NCCard {
    id: root
    property var voices: []
    property string selectedPath: ""
    property string assignedPath: ""
    property bool busy: false
    property bool available: true
    property string namePrefix: "voiceStudio"
    property bool showStudioLink: false
    property var pathsEqual: (a, b) => String(a || "").replace(/\\/g, "/").toLowerCase() === String(b || "").replace(/\\/g, "/").toLowerCase()
    signal choose(string path)
    signal play(string path)
    signal refresh()
    signal openStudio()
    title: qsTr("Voice library")
    description: qsTr("Your recordings and voices saved from Voice Studio.")
    headerAccessory: NCButton { text: qsTr("Refresh"); compact: true; enabled: !root.busy && root.available; onClicked: root.refresh() }
    NCTextField { toolTipText: qsTr("Filter the displayed library by voice name, file path, description or notes. Matching is case-insensitive and only changes the list view; Show removed voices also controls which records are included."); id: search; objectName: root.namePrefix + "Search"; Layout.fillWidth: true; placeholderText: qsTr("Find a voice, description or note") }
    NCCheckBox { toolTipText: qsTr("Include voices removed from the library so you can select and restore them. Removal hides records from both Persona and Voice Studio while keeping their WAVs in place for saved personas."); id: removed; objectName: root.namePrefix + "ShowRemoved"; text: qsTr("Show removed voices") }
    ListView {
        id: library
        // Cancel queued row creation before this view loses its QML context.
        Component.onDestruction: model = null
        objectName: root.namePrefix + "Library"
        Layout.fillWidth: true; Layout.preferredHeight: 288; clip: true; spacing: 6
        model: root.voices.filter(v => (removed.checked || !v.archived) &&
            (v.name + " " + v.path + " " + (v.description || "") + " " + (v.notes || "")).toLowerCase().indexOf(search.text.toLowerCase()) >= 0)
        ScrollBar.vertical: ScrollBar {}
        delegate: Rectangle {
            id: row
            required property var modelData
            required property int index
            width: library.width; height: 62; radius: 8
            color: root.pathsEqual(modelData.path, root.selectedPath) ? Theme.NCTheme.surfaceSelected : Theme.NCTheme.windowRaised
            border.color: select.hovered ? Theme.NCTheme.warning : root.pathsEqual(modelData.path, root.selectedPath) ? Theme.NCTheme.accent : Theme.NCTheme.border
            RowLayout {
                anchors.fill: parent; anchors.margins: 6; spacing: 6
                AbstractButton {
                    id: select
                    objectName: root.namePrefix + "Row_" + row.index
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Accessible.name: String(row.modelData.name || "")
                    hoverEnabled: true
                    contentItem: ColumnLayout {
                        spacing: 3
                        Label { Layout.fillWidth: true; text: String(row.modelData.name || ""); elide: Text.ElideRight; color: select.hovered ? Theme.NCTheme.warning : Theme.NCTheme.text }
                        Label {
                            Layout.fillWidth: true; elide: Text.ElideRight
                            text: row.modelData.archived ? qsTr("Removed · Select to restore") : !row.modelData.valid ? String(row.modelData.error || qsTr("Invalid recording"))
                                  : String(row.modelData.source || "WAV") + " · " + Number(row.modelData.duration || 0).toFixed(1) + " s"
                                    + (root.pathsEqual(row.modelData.path, root.assignedPath) ? qsTr(" · Assigned") : "")
                            color: row.modelData.valid ? Theme.NCTheme.textSecondary : Theme.NCTheme.error
                            font.pixelSize: Theme.NCTypography.captionSize
                        }
                    }
                    onClicked: root.choose(row.modelData.path)
                }
                NCButton {
                    text: qsTr("Play"); compact: true
                    Accessible.name: qsTr("Play sample: %1").arg(String(row.modelData.name || ""))
                    enabled: Boolean(row.modelData.valid) && !root.busy
                    onClicked: { root.choose(row.modelData.path); root.play(row.modelData.path) }
                }
            }
        }
        Label {
            anchors.fill: parent; anchors.margins: 12
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            visible: library.count === 0; wrapMode: Text.Wrap
            text: !root.available ? qsTr("Enable Voice Studio to browse and preview recordings.")
                  : root.busy ? qsTr("Loading voice library…") : qsTr("No matching recordings. Refresh, show removed voices, or create a voice in Voice Studio.")
            color: Theme.NCTheme.textSecondary
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Label { Layout.fillWidth: true; text: qsTr("%1 voices").arg(library.count); color: Theme.NCTheme.textMuted }
        NCButton { objectName: root.namePrefix + "OpenStudio"; visible: root.showStudioLink; text: qsTr("Open Voice Studio"); onClicked: root.openStudio() }
    }
}
