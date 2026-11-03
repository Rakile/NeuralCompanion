import QtQuick
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    property var controls: []
    property var layoutController: null
    signal controlEdited(string controlId, var value)
    signal actionTriggered(string controlId)
    signal refreshRequested()
    title: qsTr("Overview controls")

    function fields(ids) {
        return controls.filter(function(field) { return ids.indexOf(String(field.id)) >= 0 })
    }

    headerAccessory: NCButton {
        text: qsTr("Refresh")
        compact: true
        onClicked: root.refreshRequested()
    }

    GridLayout {
        Layout.fillWidth: true
        columns: width >= 920 ? 2 : 1
        columnSpacing: Theme.NCMetrics.space12
        rowSpacing: Theme.NCMetrics.space12
        Repeater {
            model: [
                ["web_intelligence_enabled", "web_intelligence_overall_status", "web_intelligence_use_llm_context_intent", "web_intelligence_clear_cache"],
                ["web_intelligence_mode", "web_intelligence_max_results", "web_intelligence_fetch_pages",
                 "web_intelligence_include_page_text", "web_intelligence_include_images", "web_intelligence_include_videos"]
            ]
            delegate: NCLiveControlsGroup {
                required property var modelData
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                flat: true
                title: ""
                description: ""
                showRefresh: false
                legacyPlacement: true
                controls: root.fields(modelData)
                layoutController: root.layoutController
                layoutSurfaceId: "web_intelligence_tab"
                layoutSection: "Overview"
                onControlEdited: (controlId, value) => root.controlEdited(controlId, value)
                onActionTriggered: controlId => root.actionTriggered(controlId)
            }
        }
    }
    NCLiveControlsGroup {
        Layout.fillWidth: true
        flat: true
        title: ""
        description: ""
        showRefresh: false
        legacyPlacement: true
        controls: root.fields(["web_intelligence_evidence_prefix", "web_intelligence_restore_evidence_prefix"])
        layoutController: root.layoutController
        layoutSurfaceId: "web_intelligence_tab"
        layoutSection: "Overview"
        onControlEdited: (controlId, value) => root.controlEdited(controlId, value)
        onActionTriggered: controlId => root.actionTriggered(controlId)
    }
}
