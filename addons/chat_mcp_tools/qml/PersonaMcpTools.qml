pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

NCCard {
    id: root
    objectName: "personaMcpToolsCard"
    property var controller: null
    property string personaId: ""
    property string personaName: ""
    readonly property var state: controller ? controller.state : ({})
    readonly property var assignments: (state.assignments || {})[personaId] || []
    function assigned(tool) {
        return assignments.some(item => item.server_id === state.server_id && item.tool_name === tool.name
            && item.schema === tool.schema_fingerprint)
    }
    function command(action, fields) { if (controller) controller.command(action, fields || {}) }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: Theme.NCMetrics.space12
        Label { text: qsTr("MCP tools for %1").arg(root.personaName || qsTr("this persona")); font.bold: true; color: Theme.NCTheme.text }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: !root.personaId ? qsTr("Select or save a persona first. Every persona starts with no tools.")
                : qsTr("Choose the tools this persona may use during normal chat. Core approval is also required. These assignments stay on this installation.")
            color: Theme.NCTheme.textSecondary
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: root.state.provider_supported
                ? qsTr("Native tool calling is available through %1. The selected model and endpoint must support tools. Your persona permissions apply to every provider.").arg(root.state.provider)
                : qsTr("Current provider: %1. This adapter has not declared native tool support. Ordinary chat remains available; your provider and model have not been changed.").arg(root.state.provider || qsTr("unavailable"))
            color: Theme.NCTheme.textSecondary
        }
        Label {
            visible: !root.state.available
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: qsTr("Chat MCP Tools or MCP Core is unavailable. Enable Chat MCP Tools in Add-ons and restart NC.")
            color: Theme.NCTheme.textSecondary
        }
        NCComboBox {
            id: servers
            objectName: "personaMcpServerChoice"
            Layout.fillWidth: true
            model: [{id:"", name:qsTr("Select a Core connection"), status:""}].concat(root.state.servers || [])
                .map(item => ({id:item.id, name:item.name + (item.status ? " · " + item.status : "")}))
            textRole: "name"
            currentIndex: Math.max(0, model.findIndex(item => item.id === root.state.server_id))
            onActivated: root.command("select", {server_id: model[currentIndex].id})
            enabled: Boolean(root.state.available) && !root.state.busy
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: qsTr("Connection setup and approval: Runtime → MCP Core → Chat MCP Tools. Grant only the tools you intend to assign here.")
            color: Theme.NCTheme.textSecondary
        }
        NCTextField {
            id: wanted
            objectName: "personaMcpRequestedTool"
            Layout.fillWidth: true
            placeholderText: qsTr("Optional tool name to include in the access request, e.g. get_transcript")
            maximumLength: 256
            enabled: Boolean(root.state.server_id)
        }
        RowLayout {
            NCButton {
                text: qsTr("Request bridge access")
                enabled: Boolean(root.state.server_id) && !root.state.busy
                onClicked: root.command("request", {server_id:root.state.server_id, requested_tool:wanted.text})
            }
            NCButton { text: qsTr("Refresh"); enabled: !root.state.busy; onClicked: root.command("refresh") }
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: qsTr("Core access: %1 · MCP access: %2").arg((root.state.access || {}).status || qsTr("not requested"))
                .arg((root.state.access || {}).master ? qsTr("allowed") : qsTr("off"))
            color: Theme.NCTheme.textSecondary
        }
        Repeater {
            model: root.state.tools || []
            delegate: ColumnLayout {
                id: toolRow
                required property var modelData
                Layout.fillWidth: true
                NCCheckBox {
                    Layout.fillWidth: true
                    text: toolRow.modelData.name
                    checked: root.assigned(toolRow.modelData)
                    enabled: Boolean(root.personaId) && !root.state.busy
                    onClicked: root.command("assign", {persona_id:root.personaId,server_id:root.state.server_id,
                        tool_name:toolRow.modelData.name,enabled:checked})
                }
                Label {
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    text: toolRow.modelData.description || ""
                    color: Theme.NCTheme.textSecondary
                }
            }
        }
        Label {
            visible: !(root.state.tools || []).length
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: qsTr("No Core-granted tools available on this connection. Connect it, allow MCP access, approve Chat MCP Tools, and select tools in Runtime → MCP Core.")
            color: Theme.NCTheme.textSecondary
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: qsTr("Saved for this persona: %1").arg(root.assignments.length
                ? root.assignments.map(item => item.tool_name).join(", ") : qsTr("no tools"))
            color: Theme.NCTheme.textSecondary
        }
        NCButton {
            text: qsTr("Remove all tools from this persona")
            enabled: Boolean(root.personaId) && root.assignments.length > 0 && !root.state.busy
            onClicked: root.command("clear", {persona_id:root.personaId})
        }
        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: root.state.status || ""; color: Theme.NCTheme.textSecondary }
    }
}
