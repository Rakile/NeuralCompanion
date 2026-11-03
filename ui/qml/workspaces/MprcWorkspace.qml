pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../components"
import "../theme" as Theme
import "MprcLayout.js" as LayoutMap
import "../../../addons/multi_persona_roleplay/qml" as Scenario

Item {
    id: root
    objectName: "mprcWorkspace"
    required property var bridge
    property string currentSection: "Play"
    readonly property var controls: root.bridge.liveAddonControls || []
    readonly property var sections: LayoutMap.sections(root.bridge.selectedAddon.sections || [])
    readonly property var sectionGroups: root.currentSection === "Play" ? [] : LayoutMap.groups(root.currentSection,
        root.controls.filter(f => f.section === root.currentSection))
    property bool floating: false
    property bool chatAvatarsEnabled: true
    signal sectionRequested(string section)

    function field(controlId, displayLabel) {
        for (let index = 0; index < root.controls.length; ++index) {
            if (root.controls[index].id === controlId) {
                const result = Object.assign({}, root.controls[index])
                result.label = displayLabel === undefined ? LayoutMap.label(result) : displayLabel
                if (controlId === "mprc_chat_float_button")
                    result.label = root.floating ? qsTr("Dock") : qsTr("Float")
                return result
            }
        }
        return ({id: controlId, label: displayLabel || "", type: "display", value: "", enabled: false})
    }
    function selectFields(ids) { return ids.map(id => root.field(id)) }
    function edit(controlId, value) { root.bridge.setLiveAddonControl(controlId, value) }
    function preview(controlId, value) { root.bridge.previewLiveAddonControl(controlId, value) }
    function storyBuilderInputs(committed) {
        const result = {}
        for (let index = 0; index < groupRepeater.count; ++index) {
            const item = groupRepeater.itemAt(index)
            if (item && ["builder", "cast_generation"].indexOf(item.group.key) >= 0)
                Object.assign(result, item.editorValues(committed))
        }
        return result
    }
    function hasPendingMasterDraft() {
        for (let index = 0; index < groupRepeater.count; ++index) {
            const item = groupRepeater.itemAt(index)
            if (item && item.group.key === "draft") {
                const current = item.editorValues(false).mprc_master_story_draft
                const committed = item.editorValues(true).mprc_master_story_draft
                return current !== committed
            }
        }
        return false
    }
    function navigateStory(section, groupKey) {
        root.sectionRequested(section)
        Qt.callLater(function() {
            secondary.contentItem.contentY = 0
            if (!groupKey) return
            for (let index = 0; index < groupRepeater.count; ++index) {
                const item = groupRepeater.itemAt(index)
                if (item && item.group.key === groupKey) {
                    item.expanded = true
                    const position = item.mapToItem(secondary.contentItem.contentItem, 0, 0)
                    secondary.contentItem.contentY = Math.max(0, Math.min(position.y,
                        secondary.contentItem.contentHeight - secondary.contentItem.height))
                    break
                }
            }
        })
    }
    function run(action) {
        if (action && action.id && action.type === "action" && action.enabled !== false)
            actionRouter.runAction(action)
    }
    function dispatch(controlId) {
        if (controlId === "mprc_scenario_play_panel" || controlId === "mprc_scenario_builder") {
            root.sectionRequested("Scenarios & Lore")
            return
        }
        root.bridge.triggerLiveAddonAction(controlId)
        if (controlId === "mprc_quick_edit_persona")
            root.sectionRequested("Editor")
        if (controlId === "mprc_chat_float_button") {
            root.floating = !root.floating
            if (root.floating) {
                playWindow.raise()
                playWindow.requestActivate()
            }
        }
    }

    // Reuse the existing confirmation, file-picker and payload flow unchanged.
    NCLiveControlsGroup {
        id: actionRouter
        objectName: "mprcActionRouter"
        visible: false
        width: 0
        height: 0
        controls: []
        onActionTriggered: controlId => root.dispatch(controlId)
        onActionWithPayload: (controlId, payload) => root.bridge.triggerLiveAddonActionWithPayload(controlId, payload)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        Flow {
            Layout.fillWidth: true
            spacing: 14
            Label {
                text: qsTr("Multi-Persona Roleplay")
                color: Theme.NCTheme.text
                font.pixelSize: 18
                font.weight: Font.DemiBold
                height: 32
                verticalAlignment: Text.AlignVCenter
            }
            Repeater {
                model: ["mprc_enabled_checkbox", "mprc_ar_mode_checkbox", "mprc_show_character_checkbox"]
                delegate: MprcField {
                    required property string modelData
                    width: modelData === "mprc_show_character_checkbox" ? 200 : 180
                    compact: true
                    field: root.field(modelData, modelData === "mprc_enabled_checkbox" ? "Enable roleplay" : modelData === "mprc_ar_mode_checkbox" ? "AlternativeReality" : "Track current speaker")
                    onEdited: (id, value) => root.edit(id, value)
                }
            }
        }
        MprcPanel {
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Rectangle {
                    Layout.preferredWidth: 54
                    Layout.preferredHeight: 54
                    radius: 8
                    color: Theme.NCTheme.windowRaised
                    border.color: Theme.NCTheme.border
                    Label {
                        anchors.centerIn: parent
                        text: String(root.field("mprc_current_character_name").value || "?").charAt(0).toUpperCase()
                        color: Theme.NCTheme.accent
                        font.pixelSize: 25
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 2
                    Label { text: qsTr("Current Character"); color: Theme.NCTheme.textMuted; font.pixelSize: 12 }
                    Label {
                        Layout.fillWidth: true
                        text: String(root.field("mprc_current_character_name").value || "No character selected")
                        color: Theme.NCTheme.text
                        font.pixelSize: 16
                        elide: Text.ElideRight
                    }
                }
                MprcField {
                    Layout.preferredWidth: Math.min(220, root.width * 0.27)
                    Layout.maximumWidth: Math.min(220, root.width * 0.27)
                    field: root.field("mprc_active_persona_combo", "Active persona")
                    onEdited: (id, value) => root.edit(id, value)
                }
                MprcField {
                    Layout.preferredWidth: 116
                    Layout.maximumWidth: 116
                    compact: true
                    field: root.field("mprc_quick_edit_persona")
                    onActionRequested: field => root.run(field)
                }
            }
        }
        MprcPanel {
            objectName: "mprcRoster"
            Layout.fillWidth: true
            title: qsTr("Roster & persona actions")
            foldable: true
            expanded: false
            Flow {
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: ["mprc_quick_change_avatar", "mprc_quick_save_persona", "mprc_quick_import_persona", "mprc_quick_export_personas", "mprc_quick_duplicate_persona"]
                    delegate: MprcField {
                        required property string modelData
                        width: 170
                        compact: true
                        field: root.field(modelData)
                        onActionRequested: field => root.run(field)
                    }
                }
                NCButton { text: qsTr("Open Registry"); compact: true; onClicked: root.sectionRequested("Registry") }
            }
            MprcField {
                Layout.fillWidth: true
                field: root.field("mprc_current_character_view_mode", "Character view")
                onEdited: (id, value) => root.edit(id, value)
            }
            MprcField { Layout.fillWidth: true; showLabel: false; field: root.field("mprc_current_character_view_label") }
            RowLayout {
                Layout.fillWidth: true
                NCStatusChip { text: String(root.bridge.selectedAddon.status || ""); status: "active" }
                Item { Layout.fillWidth: true }
                NCSwitch {
                    text: qsTr("Enabled after restart")
                    toolTipText: qsTr("Load the Multi Persona Roleplay addon when NC next starts. This is separate from enabling the current roleplay session.")
                    checked: Boolean(root.bridge.selectedAddon.enabled)
                    onClicked: root.bridge.setAddonEnabled(String(root.bridge.selectedAddon.addonId), checked)
                }
            }
        }
        Scenario.StoryWorkflow {
            Layout.fillWidth: true
            workspace: root
            onNavigationRequested: (section, groupKey) => root.navigateStory(section, groupKey)
        }
        Flow {
            Layout.fillWidth: true
            spacing: 4
            Repeater {
                model: root.sections
                delegate: NCTabButton {
                    required property string modelData
                    text: modelData
                    tutorialBridge: root.bridge
                    tutorialContext: ({workspace: "addons", addon: "multi_persona_roleplay_tab", section: modelData})
                    checked: modelData === root.currentSection
                    onClicked: root.sectionRequested(modelData)
                }
            }
        }
        Item {
            id: pageArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            MprcPlay {
                id: playPage
                workspace: root
                parent: root.floating ? floatArea : pageArea
                anchors.fill: parent
                visible: root.floating || root.currentSection === "Play"
            }
            Label {
                anchors.centerIn: parent
                visible: root.currentSection === "Play" && root.floating
                text: qsTr("Play is open in its own window.")
                color: Theme.NCTheme.textSecondary
            }
            Scenario.ScenarioTab {
                anchors.fill: parent
                workspace: root
                visible: root.currentSection === "Scenarios & Lore"
                onMasterRequested: root.sectionRequested("Master")
            }
            ScrollView {
                id: secondary
                objectName: "mprcSecondaryScroll"
                anchors.fill: parent
                visible: root.currentSection !== "Play" && root.currentSection !== "Scenarios & Lore"
                contentWidth: availableWidth
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                GridLayout {
                    width: secondary.availableWidth
                    columns: width >= 820 ? 2 : 1
                    columnSpacing: 12
                    rowSpacing: 12
                    Repeater {
                        id: groupRepeater
                        model: root.sectionGroups.length
                        delegate: MprcGroup {
                            required property int index
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: 1
                            Layout.alignment: Qt.AlignTop
                            Layout.columnSpan: secondary.availableWidth >= 820 ? Number(group.span || 2) : 1
                            group: root.sectionGroups[index] || ({})
                            controls: root.controls
                            footerComponent: root.currentSection === "Master" && group.key === "builder" ? briefComponent : null
                            onEdited: (id, value) => root.edit(id, value)
                            onPreviewed: (id, value) => root.preview(id, value)
                            onActionRequested: field => root.run(field)
                        }
                    }
                }
            }
        }
    }
    Component {
        id: briefComponent
        Scenario.StoryBriefPanel { workspace: root }
    }
    Window {
        id: playWindow
        objectName: "mprcPlayWindow"
        visible: root.floating
        width: 1240
        height: 940
        minimumWidth: 660
        minimumHeight: 540
        title: qsTr("MPRC · Play")
        color: Theme.NCTheme.windowRaised
        onClosing: close => { close.accepted = false; root.floating = false }
        Item { id: floatArea; anchors.fill: parent; anchors.margins: 12 }
    }
}
