import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCLiveControlsGroup {
    id: root
    objectName: "orbConversationalWatchPanel"
    property var readControls: null
    property var readRows: null
    property var watchRows: []
    property int refreshInterval: 2000
    legacyPlacement: true

    function refreshWatch() {
        if (!visible)
            return
        if (typeof readRows === "function") {
            const nextRows = readRows()
            if (JSON.stringify(nextRows) !== JSON.stringify(watchRows))
                watchRows = nextRows
            return
        }
        if (typeof readControls !== "function")
            return
        const next = readControls()
        if (JSON.stringify(next) !== JSON.stringify(controls))
            controls = next
    }

    onRefreshRequested: refreshWatch()
    title: typeof readRows === "function" ? qsTr("Conversational watches") : ""
    ColumnLayout {
        Layout.fillWidth: true
        visible: typeof root.readRows === "function"
        Label {
            Layout.fillWidth: true
            visible: root.watchRows.length === 0
            text: qsTr("No conversational watches. Ask the Orb to watch a visible subject.")
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        Repeater {
            model: root.watchRows
            delegate: ColumnLayout {
                id: row
                required property var modelData
                Layout.fillWidth: true
                function identity() {
                    return {watch_id:modelData.id, expected_revision:modelData.revision, session_key:modelData.session_key}
                }
                RowLayout {
                    Layout.fillWidth: true
                    NCButton {
                        objectName: "removeWatch_" + row.modelData.id
                        text: "X"
                        Accessible.name: "Remove " + row.modelData.instruction
                        onClicked: root.actionWithPayload("companion_orb_watch_stop", row.identity())
                    }
                    Label {
                        Layout.fillWidth: true
                        text: String(row.modelData.instruction || "")
                        color: Theme.NCTheme.text
                        wrapMode: Text.Wrap
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: String(row.modelData.condition_label || "") + "\n" + String(row.modelData.message || "")
                          + "\n" + String(row.modelData.checked || "")
                          + (row.modelData.observation_text ? "\n" + row.modelData.observation_text : "")
                    color: Theme.NCTheme.textSecondary
                    wrapMode: Text.Wrap
                }
                NCButton {
                    text: qsTr("Open latest capture")
                    enabled: Boolean(row.modelData.capture_available)
                    onClicked: root.actionWithPayload("companion_orb_watch_open_capture", row.identity())
                }
            }
        }
    }
    Timer {
        interval: root.refreshInterval
        running: root.visible
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refreshWatch()
    }
}
