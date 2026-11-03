pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

ScrollView {
    id: root
    objectName: "resourcesWorkspace"

    required property var bridge

    // Older or test bridges may not expose resourceMonitor yet. Keep every
    // access behind this guard so this workspace can still be instantiated.
    readonly property var monitor: bridge && bridge.resourceMonitor ? bridge.resourceMonitor : null
    readonly property bool hasMonitor: root.monitor !== null
    readonly property var snapshot: root.monitor && root.monitor.snapshot ? root.monitor.snapshot : ({})
    readonly property var resources: root.snapshot.resources || []
    readonly property var memory: root.snapshot.memory || ({})
    readonly property var ramMemory: root.memory.ram || ({})
    readonly property var gpus: root.memory.gpus || []
    readonly property int resourceCount: root.resources ? root.resources.length : 0
    readonly property bool busy: root.monitor ? root.monitor.busy === true : false
    readonly property bool refreshing: root.monitor ? root.monitor.refreshing === true : false
    readonly property string errorText: root.joinedErrors()
    readonly property string message: String(root.snapshot.message || "")
    readonly property string updatedLabel: root.updatedText()

    // Resource ids are kept here so expanding a row survives snapshot
    // replacement (the monitor publishes a new map on every refresh).
    property var expandedResources: ({})
    property bool monitorActive: false

    clip: true
    contentWidth: availableWidth

    // Keep delegates and their focus/expanded state across telemetry updates.
    ListModel { id: resourceRows; dynamicRoles: true }
    ListModel { id: gpuRows; dynamicRoles: true }

    function syncRows(target, values, gpu) {
        if (!target)
            return
        for (let index = 0; index < values.length; index += 1) {
            const value = values[index]
            const key = gpu ? String(value.index) : root.resourceKey(value)
            let existing = index
            while (existing < target.count && target.get(existing).entryKey !== key)
                existing += 1
            if (existing === target.count) {
                target.insert(index, {"entryKey": key, "entry": value})
            } else {
                if (existing !== index)
                    target.move(existing, index, 1)
                if (JSON.stringify(target.get(index).entry) !== JSON.stringify(value))
                    target.setProperty(index, "entry", value)
            }
        }
        if (target.count > values.length)
            target.remove(values.length, target.count - values.length)
    }

    onResourcesChanged: root.syncRows(resourceRows, root.resources, false)
    onGpusChanged: root.syncRows(gpuRows, root.gpus, true)

    function byteValue(value) {
        if (value === null || value === undefined || value === "")
            return -1
        const bytes = Number(value)
        return isFinite(bytes) && bytes >= 0 ? bytes : -1
    }

    function hasByteValue(value) {
        return root.byteValue(value) >= 0
    }

    function formatBytes(value) {
        const bytes = root.byteValue(value)
        if (bytes < 0)
            return ""
        const units = ["B", "KB", "MB", "GB", "TB"]
        let amount = bytes
        let unitIndex = 0
        while (amount >= 1024 && unitIndex < units.length - 1) {
            amount = amount / 1024
            unitIndex += 1
        }
        const rounded = unitIndex === 0 ? Math.round(amount) : Math.round(amount * 10) / 10
        return String(rounded) + " " + units[unitIndex]
    }

    function ramLabel(resource) {
        const bytes = resource ? root.byteValue(resource.ramBytes) : -1
        const shared = resource ? root.byteValue(resource.sharedRamBytes) : -1
        return bytes >= 0 ? root.formatBytes(bytes)
                         : shared >= 0 ? qsTr("%1 shared").arg(root.formatBytes(shared)) : qsTr("Unavailable")
    }

    function vramLabel(resource) {
        const bytes = resource ? root.byteValue(resource.vramBytes) : -1
        const shared = resource ? root.byteValue(resource.sharedVramBytes) : -1
        return bytes >= 0 ? root.formatBytes(bytes)
                         : shared >= 0 ? qsTr("%1 shared").arg(root.formatBytes(shared)) : qsTr("Unavailable")
    }

    function percentValue(usedValue, totalValue) {
        const used = root.byteValue(usedValue)
        const total = root.byteValue(totalValue)
        if (total <= 0)
            return 0
        if (used < 0)
            return 0
        return Math.max(0, Math.min(100, Math.round((used / total) * 100)))
    }

    function memoryUsageText(usedValue, totalValue) {
        const used = root.byteValue(usedValue)
        const total = root.byteValue(totalValue)
        if (total <= 0)
            return qsTr("Unavailable")
        if (used < 0)
            return qsTr("%1 total · usage unavailable").arg(root.formatBytes(total))
        return qsTr("%1 of %2 used · %3%")
                .arg(root.formatBytes(used))
                .arg(root.formatBytes(total))
                .arg(root.percentValue(used, total))
    }

    function formatUpdatedAt(value) {
        if (value === null || value === undefined || value === "")
            return ""
        if (typeof value === "number") {
            const milliseconds = value > 100000000000 ? value : value * 1000
            const date = new Date(milliseconds)
            if (isNaN(date.getTime()))
                return ""
            return root.twoDigit(date.getHours()) + ":"
                    + root.twoDigit(date.getMinutes()) + ":"
                    + root.twoDigit(date.getSeconds())
        }
        return String(value)
    }

    function twoDigit(value) {
        return value < 10 ? "0" + String(value) : String(value)
    }

    function updatedText() {
        const formatted = root.formatUpdatedAt(root.snapshot.updatedAt)
        return formatted.length > 0 ? qsTr("Updated %1").arg(formatted) : ""
    }

    function joinedErrors() {
        const list = root.snapshot.errors || []
        const parts = []
        for (let index = 0; index < list.length; index += 1) {
            const text = String(list[index] || "")
            if (text.length > 0)
                parts.push(text)
        }
        return parts.join("\n")
    }

    function resourceStatusKey(status) {
        const key = String(status || "").toLowerCase()
        if (key.indexOf("error") >= 0 || key.indexOf("fail") >= 0)
            return "error"
        if (key.indexOf("unload") >= 0 || key.indexOf("idle") >= 0
                || key.indexOf("stopped") >= 0 || key.indexOf("disconnect") >= 0)
            return "disconnected"
        if (key.indexOf("warn") >= 0 || key.indexOf("block") >= 0
                || key.indexOf("limit") >= 0 || key.indexOf("stale") >= 0)
            return "warning"
        if (key.indexOf("working") >= 0 || key.indexOf("busy") >= 0
                || key.indexOf("starting") >= 0)
            return "working"
        if (key.indexOf("load") >= 0 || key.indexOf("run") >= 0
                || key.indexOf("active") >= 0 || key.indexOf("ready") >= 0
                || key.indexOf("resident") >= 0)
            return "active"
        return "info"
    }

    function resourceStatusText(resource) {
        if (!resource)
            return qsTr("Unavailable")
        const label = String(resource.statusLabel || "")
        if (label.length > 0)
            return label
        const status = String(resource.status || "")
        return status.length > 0 ? status : qsTr("Unavailable")
    }

    function statusLabel(resource) {
        if (!resource)
            return qsTr("Unavailable")
        const label = String(resource.statusLabel || "")
        const status = String(resource.status || "")
        if (label.length > 0 && status.length > 0
                && label.toLowerCase() !== status.toLowerCase())
            return label + " · " + status
        return label.length > 0 ? label
             : status.length > 0 ? status : qsTr("Unavailable")
    }

    function valueOrUnavailable(value) {
        const text = value === null || value === undefined ? "" : String(value)
        return text.length > 0 ? text : qsTr("Unavailable")
    }

    function usersText(resource) {
        if (!resource)
            return qsTr("Unavailable")
        const users = resource.users
        if (Array.isArray(users)) {
            const parts = []
            for (let index = 0; index < users.length; index += 1) {
                const text = String(users[index] || "")
                if (text.length > 0)
                    parts.push(text)
            }
            return parts.length > 0 ? parts.join(", ") : qsTr("Unavailable")
        }
        if (users !== null && users !== undefined && String(users).length > 0)
            return String(users)
        return qsTr("Unavailable")
    }

    function blockedReasonText(resource) {
        if (!resource)
            return qsTr("Unavailable")
        const reason = String(resource.unloadReason || "")
        if (reason.length > 0)
            return reason
        return Boolean(resource.canUnload) ? qsTr("Not blocked")
                                            : qsTr("Unload is not available for this resource.")
    }

    function resourceKey(resource) {
        if (!resource)
            return ""
        const id = String(resource.id || "")
        return id.length > 0 ? id : String(resource.name || "")
    }

    function isExpanded(resourceId) {
        return root.expandedResources[String(resourceId)] === true
    }

    function toggleExpanded(resourceId) {
        const key = String(resourceId)
        const next = ({})
        const current = root.expandedResources || ({})
        for (const existing in current) {
            if (current[existing] === true)
                next[existing] = true
        }
        if (next[key] === true)
            delete next[key]
        else
            next[key] = true
        root.expandedResources = next
    }

    function requestRefresh() {
        if (root.busy || root.refreshing || !root.hasMonitor)
            return
        if (typeof root.monitor.refresh === "function")
            root.monitor.refresh()
    }

    function unloadResource(resourceId) {
        if (root.busy || root.refreshing || !root.hasMonitor)
            return
        if (typeof root.monitor.unload === "function")
            root.monitor.unload(String(resourceId))
    }

    function freeUnused() {
        if (root.busy || root.refreshing || !root.hasMonitor)
            return
        if (typeof root.monitor.freeUnused === "function")
            root.monitor.freeUnused()
    }

    function setMonitorActive(active) {
        if (root.monitorActive === active)
            return
        if (root.hasMonitor && typeof root.monitor.setActive === "function") {
            root.monitor.setActive(active)
            root.monitorActive = active
        }
    }

    Component.onCompleted: {
        root.syncRows(resourceRows, root.resources, false)
        root.syncRows(gpuRows, root.gpus, true)
        root.setMonitorActive(root.visible)
        if (root.visible)
            root.requestRefresh()
    }

    onVisibleChanged: root.setMonitorActive(root.visible)
    Component.onDestruction: root.setMonitorActive(false)

    ColumnLayout {
        width: parent.width
        spacing: Theme.NCMetrics.space12

        NCCard {
            Layout.fillWidth: true
            elevated: true
            title: qsTr("Resources")
            description: qsTr("See what is loaded and free unused memory.")

            headerAccessory: RowLayout {
                spacing: Theme.NCMetrics.space8

                NCButton {
                    objectName: "resourcesRefreshButton"
                    text: qsTr("Refresh")
                    tone: "secondary"
                    compact: true
                    busy: root.refreshing
                    enabled: root.hasMonitor && !root.busy && !root.refreshing
                    onClicked: root.requestRefresh()
                }

                NCButton {
                    objectName: "resourcesFreeUnusedButton"
                    text: qsTr("Free unused resources")
                    tone: "primary"
                    compact: true
                    busy: root.busy
                    enabled: root.hasMonitor && !root.busy && !root.refreshing
                    onClicked: root.freeUnused()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8
                Label {
                    text: qsTr("Refresh every")
                    color: Theme.NCTheme.textSecondary
                    font.pixelSize: Theme.NCTypography.captionSize
                }
                NCSpinBox {
                    toolTipText: qsTr("Seconds between automatic RAM, VRAM, and loaded-resource refreshes. Lower intervals update the display more often and add monitoring work; this does not change inference settings.")

                    objectName: "resourcesRefreshInterval"
                    label: qsTr("Refresh interval in seconds")
                    Layout.preferredWidth: 100
                    from: 1
                    to: 59
                    value: root.monitor && root.monitor.refreshIntervalSeconds !== undefined
                           ? root.monitor.refreshIntervalSeconds : 3
                    enabled: root.hasMonitor
                    onValueModified: {
                        if (root.monitor && root.monitor.setRefreshIntervalSeconds)
                            root.monitor.setRefreshIntervalSeconds(value)
                    }
                }
                Label {
                    text: qsTr("seconds")
                    color: Theme.NCTheme.textSecondary
                    font.pixelSize: Theme.NCTypography.captionSize
                }
                Item { Layout.fillWidth: true }
            }
        }

        NCInlineMessage {
            objectName: "resourcesFeedback"
            Layout.fillWidth: true
            visible: !root.hasMonitor || root.busy || root.refreshing
                     || (root.message.length > 0 && root.errorText.length === 0)
            tone: !root.hasMonitor ? "warning" : root.busy ? "warning" : "info"
            title: !root.hasMonitor ? qsTr("Resource monitoring unavailable")
                   : root.busy ? qsTr("Releasing resources…")
                   : root.refreshing ? qsTr("Refreshing resource usage…")
                   : qsTr("Resource status")
            message: !root.hasMonitor
                     ? qsTr("This runtime bridge does not expose a resource monitor. The workspace is available, but memory and model data cannot be read.")
                     : root.busy
                       ? qsTr("Please wait while loaded resources finish releasing.")
                       : root.refreshing
                         ? qsTr("Reading memory and model usage from the runtime monitor.")
                         : root.message
        }

        NCInlineMessage {
            objectName: "resourcesErrors"
            Layout.fillWidth: true
            visible: root.errorText.length > 0
            tone: "error"
            title: qsTr("Resource monitor errors")
            message: root.errorText
        }

        NCCard {
            objectName: "resourcesMemoryCard"
            Layout.fillWidth: true
            title: qsTr("Memory overview")
            description: qsTr("System memory and per-GPU usage reported by the resource monitor.")

            headerAccessory: Label {
                text: root.updatedLabel
                visible: text.length > 0
                Layout.maximumWidth: 220
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                elide: Text.ElideRight
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space12

                    Label {
                        Layout.fillWidth: true
                        text: qsTr("System RAM")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.labelSize
                        font.weight: Theme.NCTypography.semibold
                    }

                    Label {
                        objectName: "resourcesRamUsage"
                        text: root.memoryUsageText(root.ramMemory.usedBytes, root.ramMemory.totalBytes)
                        color: Theme.NCTheme.textSecondary
                        font.pixelSize: Theme.NCTypography.captionSize
                        horizontalAlignment: Text.AlignRight
                    }
                }

                NCProgressBar {
                    objectName: "resourcesRamBar"
                    Layout.fillWidth: true
                    visible: root.hasByteValue(root.ramMemory.totalBytes)
                             && root.byteValue(root.ramMemory.totalBytes) > 0
                             && root.hasByteValue(root.ramMemory.usedBytes)
                    from: 0
                    to: Math.max(1, root.byteValue(root.ramMemory.totalBytes))
                    value: Math.max(0, Math.min(root.byteValue(root.ramMemory.usedBytes),
                                                root.byteValue(root.ramMemory.totalBytes)))
                }

                Label {
                    visible: !root.hasByteValue(root.ramMemory.totalBytes)
                             || root.byteValue(root.ramMemory.totalBytes) <= 0
                    text: qsTr("Unavailable")
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.captionSize
                }

                Label {
                    Layout.fillWidth: true
                    visible: root.hasByteValue(root.ramMemory.ncBytes)
                             && root.byteValue(root.ramMemory.ncBytes) > 0
                    text: qsTr("NeuralCompanion RAM: %1").arg(root.formatBytes(root.ramMemory.ncBytes))
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: Theme.NCTheme.borderSubtle
            }

            Repeater {
                model: gpuRows

                delegate: ColumnLayout {
                    id: gpuRow
                    required property var entry
                    readonly property var modelData: entry
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space6

                    readonly property real totalBytes: root.byteValue(modelData.totalBytes)
                    readonly property real usedBytes: root.byteValue(modelData.usedBytes)
                    readonly property string gpuName: String(modelData.name || "")

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space12

                        Label {
                            Layout.fillWidth: true
                            text: gpuRow.gpuName.length > 0
                                  ? qsTr("Graphics memory · %1").arg(gpuRow.gpuName)
                                  : qsTr("Graphics memory")
                            color: Theme.NCTheme.text
                            font.pixelSize: Theme.NCTypography.labelSize
                            font.weight: Theme.NCTypography.semibold
                            elide: Text.ElideRight
                        }

                        Label {
                            objectName: "resourcesGpuUsage_"
                                        + String(gpuRow.modelData.index !== undefined
                                                 ? gpuRow.modelData.index : "")
                            text: root.memoryUsageText(gpuRow.usedBytes, gpuRow.totalBytes)
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: Theme.NCTypography.captionSize
                            horizontalAlignment: Text.AlignRight
                        }
                    }

                    NCProgressBar {
                        objectName: "resourcesGpuBar_"
                                    + String(gpuRow.modelData.index !== undefined
                                             ? gpuRow.modelData.index : "")
                        Layout.fillWidth: true
                        visible: gpuRow.totalBytes > 0 && gpuRow.usedBytes >= 0
                        from: 0
                        to: Math.max(1, gpuRow.totalBytes)
                        value: Math.max(0, Math.min(gpuRow.usedBytes, gpuRow.totalBytes))
                    }

                    Label {
                        visible: gpuRow.totalBytes <= 0
                        text: qsTr("Unavailable")
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.captionSize
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                visible: root.gpus.length === 0
                text: qsTr("No GPU memory telemetry was reported.")
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.Wrap
            }
        }

        NCCard {
            objectName: "resourcesListCard"
            Layout.fillWidth: true
            title: qsTr("Loaded resources")
            description: root.resourceCount > 0
                         ? qsTr("%1 resource(s) reporting. Expand a row for owner, device, users, and unload details.")
                           .arg(root.resourceCount)
                         : qsTr("No resources are currently reporting to the resource monitor.")

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8

                Repeater {
                    model: resourceRows

                    delegate: Rectangle {
                        id: resourceRow
                        required property var entry
                        readonly property var modelData: entry
                        objectName: "resourceRow_" + root.resourceKey(modelData)
                        Layout.fillWidth: true
                        implicitHeight: resourceColumn.implicitHeight + Theme.NCMetrics.space20
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.surface
                        border.width: Theme.NCMetrics.borderWidth
                        border.color: Theme.NCTheme.borderSubtle
                        Accessible.role: Accessible.Pane
                        Accessible.name: String(modelData.name || qsTr("Resource"))

                        readonly property string resourceId: root.resourceKey(modelData)
                        readonly property bool expanded: root.isExpanded(resourceRow.resourceId)
                        readonly property bool unloadable: Boolean(modelData.canUnload)
                        readonly property string statusText: root.resourceStatusText(modelData)
                        readonly property string statusKey: root.resourceStatusKey(modelData.status
                                                                                  || modelData.statusLabel)
                        readonly property string error: String(modelData.error || "")
                        readonly property var details: resourceRow.buildDetails()

                        function buildDetails() {
                            const entries = [
                                {
                                    "label": qsTr("Owner"),
                                    "value": root.valueOrUnavailable(resourceRow.modelData.owner)
                                },
                                {
                                    "label": qsTr("Device"),
                                    "value": root.valueOrUnavailable(resourceRow.modelData.device)
                                },
                                {
                                    "label": qsTr("Users"),
                                    "value": root.usersText(resourceRow.modelData)
                                },
                                {
                                    "label": qsTr("Reporting"),
                                    "value": root.statusLabel(resourceRow.modelData)
                                },
                                {
                                    "label": qsTr("Blocked reason"),
                                    "value": root.blockedReasonText(resourceRow.modelData)
                                }
                            ]
                            const note = String(resourceRow.modelData.memoryNote || "")
                            if (note.length > 0)
                                entries.push({"label": qsTr("Memory note"), "value": note})
                            const shared = resourceRow.modelData
                            if (shared.memoryGroupId) {
                                entries.push({"label": qsTr("Shared process"),
                                    "value": String(shared.memoryProcessLabel || "") + " · PID "
                                             + (shared.memoryProcessIds || []).join(", ")})
                                entries.push({"label": qsTr("Process group"), "value": String(shared.memoryGroupId)})
                                entries.push({"label": qsTr("Measurement source"),
                                              "value": String(shared.processMemorySource || "")})
                                entries.push({"label": qsTr("Shared usage"),
                                              "value": String(shared.sharedMemoryNote || "")})
                            }
                            return entries
                        }

                        ColumnLayout {
                            id: resourceColumn
                            anchors.fill: parent
                            anchors.margins: Theme.NCMetrics.space10
                            spacing: Theme.NCMetrics.space8

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space8

                                NCIconButton {
                                    objectName: "resourceToggle_" + resourceRow.resourceId
                                    glyph: resourceRow.expanded ? "▾" : "▸"
                                    toolTipText: resourceRow.expanded
                                                 ? qsTr("Collapse resource details")
                                                 : qsTr("Expand resource details")
                                    onClicked: root.toggleExpanded(resourceRow.resourceId)
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: Theme.NCMetrics.space2

                                    Label {
                                        Layout.fillWidth: true
                                        text: root.valueOrUnavailable(resourceRow.modelData.name)
                                        color: Theme.NCTheme.text
                                        font.pixelSize: Theme.NCTypography.labelSize
                                        font.weight: Theme.NCTypography.semibold
                                        elide: Text.ElideRight
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        visible: String(resourceRow.modelData.model || "").length > 0
                                        text: String(resourceRow.modelData.model || "")
                                        color: Theme.NCTheme.textSecondary
                                        font.pixelSize: Theme.NCTypography.captionSize
                                        elide: Text.ElideRight
                                    }
                                }

                                NCStatusChip {
                                    objectName: "resourceStatus_" + resourceRow.resourceId
                                    compact: true
                                    text: resourceRow.statusText
                                    status: resourceRow.statusKey
                                }

                                NCButton {
                                    objectName: "resourceUnload_" + resourceRow.resourceId
                                    text: qsTr("Unload")
                                    tone: "secondary"
                                    compact: true
                                    enabled: resourceRow.unloadable && !root.busy && !root.refreshing
                                    toolTipText: resourceRow.unloadable
                                                 ? qsTr("Release this resource")
                                                 : root.blockedReasonText(resourceRow.modelData)
                                    onClicked: root.unloadResource(resourceRow.resourceId)
                                }
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: Theme.NCMetrics.space12

                                Label {
                                    objectName: "resourceRam_" + resourceRow.resourceId
                                    text: qsTr("RAM · %1").arg(root.ramLabel(resourceRow.modelData))
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                }

                                Label {
                                    objectName: "resourceVram_" + resourceRow.resourceId
                                    text: qsTr("VRAM · %1").arg(root.vramLabel(resourceRow.modelData))
                                    color: Theme.NCTheme.textSecondary
                                    font.pixelSize: Theme.NCTypography.captionSize
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 1
                                visible: resourceRow.expanded
                                color: Theme.NCTheme.borderSubtle
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: resourceRow.expanded
                                spacing: Theme.NCMetrics.space8

                                GridLayout {
                                    Layout.fillWidth: true
                                    columns: resourceRow.width >= 520 ? 2 : 1
                                    columnSpacing: Theme.NCMetrics.space16
                                    rowSpacing: Theme.NCMetrics.space8

                                    Repeater {
                                        model: resourceRow.details

                                        delegate: ColumnLayout {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            spacing: Theme.NCMetrics.space2

                                            Label {
                                                text: String(modelData.label || "")
                                                color: Theme.NCTheme.textMuted
                                                font.pixelSize: Theme.NCTypography.microSize
                                                font.weight: Theme.NCTypography.medium
                                            }

                                            Label {
                                                Layout.fillWidth: true
                                                text: String(modelData.value || "")
                                                color: Theme.NCTheme.textSecondary
                                                font.pixelSize: Theme.NCTypography.captionSize
                                                wrapMode: Text.Wrap
                                            }
                                        }
                                    }
                                }

                                NCInlineMessage {
                                    objectName: "resourceError_" + resourceRow.resourceId
                                    Layout.fillWidth: true
                                    visible: resourceRow.error.length > 0
                                    tone: "error"
                                    title: qsTr("Resource error")
                                    message: resourceRow.error
                                }
                            }
                        }
                    }
                }

                NCEmptyState {
                    objectName: "resourcesEmptyState"
                    Layout.fillWidth: true
                    Layout.topMargin: Theme.NCMetrics.space16
                    Layout.bottomMargin: Theme.NCMetrics.space16
                    visible: root.resourceCount === 0
                    glyph: "▦"
                    title: qsTr("No resources reported")
                    description: root.hasMonitor
                                 ? qsTr("Refresh after a model or runtime service has loaded.")
                                 : qsTr("Resource monitoring is not available on this bridge.")
                    actionText: root.hasMonitor ? qsTr("Refresh") : ""
                    onActionTriggered: root.requestRefresh()
                }
            }
        }

        Item { Layout.preferredHeight: Theme.NCMetrics.space4 }
    }
}
