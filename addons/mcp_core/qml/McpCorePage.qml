pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

ScrollView {
    id: root
    objectName: "mcpCorePage"
    property var controller: null
    readonly property var state: controller ? controller.state : ({})
    readonly property var servers: state.servers || ({})
    readonly property var addons: state.addons || ({})
    readonly property var serverIds: Object.keys(servers)
    readonly property var addonIds: Object.keys(addons)
    property string serverId: ""
    property string addonId: ""
    readonly property bool usable: Boolean(state.available) && !state.closed && !state.storage_error
    readonly property bool editable: usable && !state.busy
    readonly property var selectedAddon: addons[addonId] || ({})
    readonly property var catalog: (state.catalogs || ({}))[serverId] || ({})
    readonly property var requestedSpecs: requestedSpecsFor(addonId, serverId)
    readonly property var matchingRequestedNames: requestedNamesFor(addonId, serverId)
    readonly property var shownCatalog: {
        if (!requestedSpecs.length || showAllTools) return catalog
        const filtered = {}
        for (const name of Object.keys(catalog))
            if (matchingRequestedNames.indexOf(name) >= 0 || Object.prototype.hasOwnProperty.call(selectedGrants, name))
                filtered[name] = catalog[name]
        return filtered
    }
    readonly property var toolGroups: groupTools(shownCatalog, (servers[serverId] || ({})).name || qsTr("Server tools"))
    property var expandedGroups: ({})
    property bool showAllTools: false
    property bool viewReady: false
    property bool restoringView: false
    readonly property var selectedGrants: ((state.grants || ({}))[addonId] || ({}))[serverId] || ({})
    clip: true
    contentWidth: availableWidth

    function send(action, values) {
        if (!controller) return false
        const payload = Object.assign({"action": action}, values || {})
        return controller.manage(payload)
    }
    function addonName(aid) { return (state.addon_names || ({}))[aid] || aid }
    function approvalLabel(item) {
        if (item.status === "pending") return qsTr("Awaiting your approval")
        if (item.status === "approved") return item.enabled ? qsTr("Approved · access enabled") : qsTr("Approved · access paused")
        if (item.status === "rejected") return qsTr("Request declined")
        if (item.status === "revoked") return qsTr("Approval revoked")
        return qsTr("No access request")
    }
    function requestedSpecsFor(aid, sid) {
        return ((addons[aid] || ({})).requested_tools || ({}))[sid] || []
    }
    function requestedNamesFor(aid, sid) {
        const specs = requestedSpecsFor(aid, sid)
        const tools = (state.catalogs || ({}))[sid] || ({})
        return Object.keys(tools).filter(name => specs.some(spec => name === spec.name ||
            (spec.match === "name_or_namespace" && name.endsWith("__" + spec.name))))
    }
    function rememberView() {
        if (controller && viewReady && !restoringView && typeof controller.rememberViewState === "function")
            controller.rememberViewState({"server_id":serverId,"addon_id":addonId,
                "expanded_groups":expandedGroups,"show_all_tools":showAllTools})
    }
    function restoreView() {
        if (!controller || !viewReady) return
        const saved = controller.viewState || ({})
        restoringView = true
        chooseServer(saved.server_id && servers[saved.server_id] ? saved.server_id : "")
        addonId = saved.addon_id && addons[saved.addon_id] ? saved.addon_id : ""
        expandedGroups = saved.expanded_groups || ({})
        showAllTools = Boolean(saved.show_all_tools)
        restoringView = false
        rememberView()
    }
    function reviewRequest(aid, sid) {
        addonId = aid
        if (sid) chooseServer(sid)
        showAllTools = false
    }
    onServerIdChanged: rememberView()
    onAddonIdChanged: rememberView()
    onExpandedGroupsChanged: rememberView()
    onShowAllToolsChanged: rememberView()
    function groupKey(groupId) { return JSON.stringify([serverId, groupId]) }
    function groupTools(tools, serverName) {
        const groups = {}
        const names = Object.keys(tools).sort()
        for (const name of names) {
            const separator = name.indexOf("__")
            const namespaced = separator > 0 && separator + 2 < name.length
            const namespace = namespaced ? name.substring(0, separator) : ""
            const groupId = namespaced ? "namespace:" + namespace : "connection"
            if (!Object.prototype.hasOwnProperty.call(groups, groupId))
                groups[groupId] = {"id":groupId, "title":namespace || serverName, "tools":[]}
            groups[groupId].tools.push(name)
        }
        return Object.keys(groups).sort((a, b) => {
            if (a === "connection") return 1
            if (b === "connection") return -1
            return groups[a].title.localeCompare(groups[b].title)
        }).map(key => groups[key])
    }
    function toggleGroup(groupId) {
        const key = groupKey(groupId)
        const updated = Object.assign({}, expandedGroups)
        const wasExpanded = Object.prototype.hasOwnProperty.call(updated, key) ?
            Boolean(updated[key]) : requestedSpecs.length > 0
        updated[key] = !wasExpanded
        expandedGroups = updated
    }
    function chooseServer(sid) {
        serverId = sid
        const config = servers[sid] || ({})
        serverName.text = config.name || ""
        endpoint.text = config.endpoint || ""
        auth.currentIndex = Math.max(0, ["none", "bearer", "api_key"].indexOf(config.auth || "none"))
        principal.text = config.principal || ""
        header.text = config.header || ""
        secret.text = ""
    }
    function updatePolling() {
        if (controller) controller.setActive(visible)
    }
    Timer {
        id: viewRestoreTimer
        interval: 0
        repeat: false
        onTriggered: root.restoreView()
    }
    onControllerChanged: {
        updatePolling()
        // Runtime's Loader assigns the controller after page construction.
        // Restore after dependent state/server bindings have received it.
        // An owned timer cancels the restore if navigation destroys this page.
        if (viewReady) viewRestoreTimer.restart()
    }
    onVisibleChanged: updatePolling()
    Component.onCompleted: { viewReady = true; updatePolling(); restoreView() }
    Component.onDestruction: { if (controller) controller.setActive(false) }

    ColumnLayout {
        width: root.availableWidth
        spacing: Theme.NCMetrics.space12

        NCCard {
            Layout.fillWidth: true
            title: qsTr("MCP Core")
            description: qsTr("Shared access to externally managed HTTP MCP servers. Connections start disconnected. Addons need your approval and individual tool selections.")
            NCSwitch {
                objectName: "mcpMasterSwitch"
                text: qsTr("Allow MCP access")
                checked: Boolean(root.state.master)
                enabled: root.editable
                toolTipText: qsTr("Turning this off blocks calls and disconnects NC clients. External servers keep running.")
                onToggled: root.send("master", {"enabled": checked})
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: Theme.NCTheme.textSecondary
                text: root.state.storage_error || root.state.dependency_status ||
                      (root.state.busy ? qsTr("Applying changes…") : root.state.management_status || "")
            }
            NCButton {
                text: qsTr("Clear status")
                enabled: root.editable
                onClicked: root.send("clear_status")
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("Server connections")
            description: qsTr("Streamable HTTP only. Authentication: none, bearer token or secret API-key header. OAuth and stdio are not supported.")
            RowLayout {
                Layout.fillWidth: true
                NCComboBox {
                    objectName: "mcpServerSelector"
                    Layout.fillWidth: true
                    model: root.serverIds.map(sid => ({"text": root.servers[sid].name, "sid": sid}))
                    textRole: "text"
                    currentIndex: root.serverIds.indexOf(root.serverId)
                    displayText: root.serverId ? currentText : qsTr("Choose a saved server")
                    enabled: root.editable
                    onActivated: index => root.chooseServer(root.serverIds[index])
                }
                NCButton { text: qsTr("New server"); enabled: root.editable; onClicked: root.chooseServer("") }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                Label { text: qsTr("Name"); color: Theme.NCTheme.text }
                NCTextField { id: serverName; objectName: "mcpServerName"; Layout.fillWidth: true; enabled: root.editable; label: qsTr("Server name") }
                Label { text: qsTr("Endpoint"); color: Theme.NCTheme.text }
                NCTextField { id: endpoint; objectName: "mcpEndpoint"; Layout.fillWidth: true; enabled: root.editable; label: qsTr("HTTP MCP endpoint"); placeholderText: "http://localhost:8000/mcp" }
                Label { text: qsTr("Authentication"); color: Theme.NCTheme.text }
                NCComboBox { id: auth; Layout.fillWidth: true; enabled: root.editable; model: ["none", "bearer", "api_key"] }
                Label { text: qsTr("Account identity"); visible: auth.currentIndex > 0; color: Theme.NCTheme.text }
                NCTextField { id: principal; Layout.fillWidth: true; visible: auth.currentIndex > 0; enabled: root.editable; placeholderText: qsTr("A label for the authenticated account"); toolTipText: qsTr("Keep this label for credential refresh. Change it when switching accounts; tool selections will be cleared.") }
                Label { text: qsTr("API-key header"); visible: auth.currentIndex === 2; color: Theme.NCTheme.text }
                NCTextField { id: header; Layout.fillWidth: true; visible: auth.currentIndex === 2; enabled: root.editable; placeholderText: "X-API-Key" }
                Label { text: qsTr("Secret"); visible: auth.currentIndex > 0; color: Theme.NCTheme.text }
                NCTextField { id: secret; objectName: "mcpSecret"; Layout.fillWidth: true; visible: auth.currentIndex > 0; enabled: root.editable; echoMode: TextInput.Password; placeholderText: qsTr("Empty keeps the secret for the same endpoint/account"); toolTipText: qsTr("Stored in Windows Credential Manager. Re-enter when changing the endpoint or account.") }
            }
            Label {
                visible: auth.currentIndex > 0 && root.serverId.length > 0
                text: ((root.state.credentials_configured || ({}))[root.serverId]) ? qsTr("A secure credential is configured.") : qsTr("No secure credential is available.")
                color: Theme.NCTheme.textSecondary
            }
            Flow {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8
                NCButton {
                    objectName: "mcpSaveServer"; text: qsTr("Save server"); enabled: root.editable && endpoint.text.length > 0
                    onClicked: {
                        const config = {"name": serverName.text, "endpoint": endpoint.text,
                            "auth": auth.currentText, "principal": principal.text, "header": header.text}
                        if (root.serverId) config.id = root.serverId
                        root.send("save_server", {"config": config, "secret": secret.text})
                        secret.text = ""
                    }
                }
                NCButton { objectName: "mcpRemoveServer"; text: qsTr("Remove"); tone: "danger"; enabled: root.editable && root.serverId.length > 0; onClicked: { root.send("remove_server", {"server_id": root.serverId}); root.chooseServer("") } }
                NCButton { objectName: "mcpConnect"; text: qsTr("Connect"); enabled: root.editable && root.state.master && root.serverId.length > 0; onClicked: root.send("connect", {"server_id": root.serverId}) }
                NCButton { objectName: "mcpDisconnect"; text: qsTr("Disconnect"); enabled: root.editable && root.serverId.length > 0; onClicked: root.send("disconnect", {"server_id": root.serverId}) }
                NCButton { objectName: "mcpTest"; text: qsTr("Test connection"); enabled: root.editable && root.state.master && root.serverId.length > 0; onClicked: root.send("test", {"server_id": root.serverId}) }
                NCButton { objectName: "mcpRefresh"; text: qsTr("Refresh tools"); enabled: root.editable && root.serverId.length > 0; onClicked: root.send("refresh", {"server_id": root.serverId}) }
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: Theme.NCTheme.textSecondary
                text: {
                    const status = (root.state.connections || ({}))[root.serverId] || ({})
                    return (status.status || qsTr("Disconnected")) + (status.error ? " · " + status.error : "") +
                           (status.tested ? qsTr(" · Connection test passed") : "")
                }
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("1. Review addon requests")
            description: qsTr("Each addon tells you why it needs access and which tools it wants. Approve the addon first, then select its tools below. Approval alone grants no tools.")
            Repeater {
                model: root.addonIds.filter(aid => root.addons[aid].status === "pending")
                delegate: NCCard {
                    id: pending
                    required property string modelData
                    Layout.fillWidth: true
                    title: root.addonName(pending.modelData)
                    description: pending.modelData
                    Repeater {
                        model: Object.keys(root.addons[pending.modelData].requests)
                        delegate: ColumnLayout {
                            id: requestedServer
                            required property string modelData
                            Layout.fillWidth: true
                            Label { text: qsTr("Server: %1").arg((root.servers[requestedServer.modelData] || ({})).name || requestedServer.modelData); color: Theme.NCTheme.text; font.bold: true }
                            Label {
                                Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.textSecondary
                                text: qsTr("Purpose: %1").arg(root.addons[pending.modelData].requests[requestedServer.modelData] || qsTr("No purpose supplied."))
                            }
                            Repeater {
                                model: root.requestedSpecsFor(pending.modelData, requestedServer.modelData)
                                delegate: Label {
                                    required property var modelData
                                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.text
                                    text: qsTr("Tool requested: %1").arg(modelData.name) +
                                        (modelData.match === "name_or_namespace" ? qsTr(" (including its namespaced form)") : "")
                                }
                            }
                            Label {
                                Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.textSecondary
                                text: {
                                    const declared = root.requestedSpecsFor(pending.modelData, requestedServer.modelData)
                                    const matches = root.requestedNamesFor(pending.modelData, requestedServer.modelData)
                                    return !declared.length ? qsTr("This addon has not declared its requested tools. Update its request before choosing permissions.") :
                                        matches.length ? qsTr("Matching tools on this server: %1").arg(matches.join(", ")) :
                                        qsTr("The requested tool is not in this server's catalog. Connect the server and refresh its tools.")
                                }
                            }
                        }
                    }
                    RowLayout {
                        NCButton {
                            objectName: "mcpApprove"; text: qsTr("Approve addon"); enabled: root.editable
                            onClicked: {
                                root.reviewRequest(pending.modelData, Object.keys(root.addons[pending.modelData].requests)[0] || "")
                                root.send("approval", {"addon_id": pending.modelData, "decision": "approve"})
                            }
                        }
                        NCButton { objectName: "mcpReject"; text: qsTr("Decline request"); enabled: root.editable; onClicked: root.send("approval", {"addon_id": pending.modelData, "decision": "reject"}) }
                    }
                }
            }
            Label {
                visible: !root.addonIds.some(aid => root.addons[aid].status === "pending")
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: qsTr("No requests are waiting for approval. Open an MCP-enabled addon and choose Request access to see its purpose and requested tools here.")
                color: Theme.NCTheme.textSecondary
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("2. Choose whose access to manage")
            description: qsTr("Permissions apply only to the addon and server selected here.")
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                Label { text: qsTr("Addon"); color: Theme.NCTheme.text }
                NCComboBox {
                    objectName: "mcpAddonSelector"; Layout.fillWidth: true
                    model: root.addonIds.map(aid => ({"text": root.addonName(aid) + " · " + root.approvalLabel(root.addons[aid]), "aid": aid}))
                    textRole: "text"; currentIndex: root.addonIds.indexOf(root.addonId)
                    displayText: root.addonId ? currentText : qsTr("Choose an addon")
                    enabled: root.editable && root.addonIds.length > 0
                    onActivated: index => { root.addonId = root.addonIds[index]; root.showAllTools = false }
                }
                Label { text: qsTr("Server"); color: Theme.NCTheme.text }
                NCComboBox {
                    objectName: "mcpPermissionServerSelector"; Layout.fillWidth: true
                    model: root.serverIds.map(sid => ({"text": root.servers[sid].name, "sid": sid}))
                    textRole: "text"; currentIndex: root.serverIds.indexOf(root.serverId)
                    displayText: root.serverId ? currentText : qsTr("Choose a server")
                    enabled: root.editable && root.serverIds.length > 0
                    onActivated: index => root.chooseServer(root.serverIds[index])
                }
            }
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.textSecondary
                text: !root.addonId ? qsTr("Choose an addon to review its request and tool permissions.") :
                    root.approvalLabel(root.selectedAddon)
            }
            Flow {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8
                NCButton { objectName: "mcpToggleAddon"; visible: root.selectedAddon.status === "approved"; text: root.selectedAddon.enabled ? qsTr("Pause addon access") : qsTr("Resume addon access"); enabled: root.editable && root.selectedAddon.status === "approved"; onClicked: root.send("approval", {"addon_id": root.addonId, "decision": root.selectedAddon.enabled ? "disable" : "enable"}) }
                NCButton { objectName: "mcpRevoke"; visible: root.selectedAddon.status === "approved"; text: qsTr("Revoke approval"); tone: "danger"; enabled: root.editable && root.selectedAddon.status === "approved"; onClicked: root.send("approval", {"addon_id": root.addonId, "decision": "revoke"}) }
            }
        }

        NCCard {
            Layout.fillWidth: true
            title: qsTr("3. Select the tools this addon may use")
            description: qsTr("Requested tools are shown first. Each switch grants only that exact tool on the selected server. Nothing is selected automatically.")
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.textSecondary
                text: qsTr("Addon: %1 · Server: %2").arg(root.addonId ? root.addonName(root.addonId) : qsTr("Choose above")).arg((root.servers[root.serverId] || ({})).name || qsTr("Choose above"))
            }
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.text
                visible: root.addonId.length > 0 && root.serverId.length > 0
                text: qsTr("Purpose: %1").arg((root.selectedAddon.requests || ({}))[root.serverId] || qsTr("No request for this server."))
            }
            Repeater {
                model: root.requestedSpecs
                delegate: Label {
                    required property var modelData
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.text
                    text: qsTr("Tool requested: %1").arg(modelData.name)
                }
            }
            Label {
                visible: root.addonId.length > 0 && root.serverId.length > 0 && !root.requestedSpecs.length
                Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.textSecondary
                text: qsTr("This request has no tool declaration. Core will not guess which tools the addon needs. Update the addon's request before choosing tools.")
            }
            NCCheckBox {
                visible: root.requestedSpecs.length > 0 && Object.keys(root.catalog).length > root.matchingRequestedNames.length
                text: qsTr("Show other tools this addon did not request")
                checked: root.showAllTools
                onToggled: root.showAllTools = checked
            }
            Flow {
                Layout.fillWidth: true; spacing: Theme.NCMetrics.space8
                NCButton { objectName: "mcpEnableAll"; text: qsTr("Allow all current server tools"); visible: root.selectedAddon.status === "approved" && (!root.requestedSpecs.length || root.showAllTools); enabled: root.editable && root.selectedAddon.status === "approved" && root.serverId.length > 0; onClicked: root.send("select_all", {"addon_id": root.addonId, "server_id": root.serverId, "enabled": true}) }
                NCButton { objectName: "mcpDisableAll"; visible: root.selectedAddon.status === "approved"; text: qsTr("Clear this addon's tool permissions"); enabled: root.editable && root.selectedAddon.status === "approved" && root.serverId.length > 0; onClicked: root.send("select_all", {"addon_id": root.addonId, "server_id": root.serverId, "enabled": false}) }
            }
            Repeater {
                model: root.toolGroups
                delegate: ColumnLayout {
                    id: toolGroup
                    required property var modelData
                    readonly property bool expanded: Object.prototype.hasOwnProperty.call(root.expandedGroups, root.groupKey(modelData.id)) ?
                        Boolean(root.expandedGroups[root.groupKey(modelData.id)]) : root.requestedSpecs.length > 0
                    Layout.fillWidth: true
                    NCButton {
                        objectName: "mcpToolGroup_" + toolGroup.modelData.id
                        Layout.fillWidth: true
                        text: toolGroup.modelData.title + " · " + (toolGroup.modelData.tools.length === 1 ? qsTr("1 tool") : qsTr("%1 tools").arg(toolGroup.modelData.tools.length)) + " · " +
                              (toolGroup.expanded ? qsTr("Hide tools") : qsTr("Show tools"))
                        onClicked: root.toggleGroup(toolGroup.modelData.id)
                    }
                    ColumnLayout {
                        visible: toolGroup.expanded
                        Layout.fillWidth: true
                        Repeater {
                            model: toolGroup.modelData.tools
                            delegate: ColumnLayout {
                                id: toolRow
                                required property string modelData
                                Layout.fillWidth: true
                                NCCheckBox {
                                    objectName: "mcpTool_" + toolRow.modelData
                                    Layout.fillWidth: true
                                    text: toolRow.modelData + (root.matchingRequestedNames.indexOf(toolRow.modelData) >= 0 ? qsTr(" · requested by this addon") :
                                        Object.prototype.hasOwnProperty.call(root.selectedGrants, toolRow.modelData) ? qsTr(" · already allowed, not requested") : "")
                                    checked: Object.prototype.hasOwnProperty.call(root.selectedGrants, toolRow.modelData)
                                    enabled: root.editable && root.selectedAddon.status === "approved"
                                    onToggled: root.send("select", {"addon_id": root.addonId, "server_id": root.serverId, "tool": toolRow.modelData, "enabled": checked})
                                }
                                Label { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.textSecondary; text: (root.catalog[toolRow.modelData] || ({})).description || qsTr("No description supplied.") }
                            }
                        }
                    }
                }
            }
            Label { visible: Object.keys(root.catalog).length === 0; text: qsTr("Select and connect a server to discover tools."); color: Theme.NCTheme.textSecondary }
            Label { visible: Object.keys(root.catalog).length > 0 && root.requestedSpecs.length > 0 && !root.matchingRequestedNames.length; Layout.fillWidth: true; wrapMode: Text.Wrap; text: qsTr("No tool matches this addon's declaration on the selected server. Choose the correct server or refresh its tools."); color: Theme.NCTheme.textSecondary }
        }
    }
}
