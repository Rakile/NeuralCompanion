pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme
import "AudioStoryLayout.js" as LayoutMap

Item {
    id: root

    objectName: "audioStoryWorkspace"
    required property var bridge
    property string currentSection: "Project"
    readonly property var controls: root.bridge.liveAddonControls || []
    readonly property var sections: LayoutMap.sections(root.bridge.selectedAddon.sections || [])
    readonly property var workflowSteps: LayoutMap.workflowSteps()
    readonly property var sectionGroups: LayoutMap.groups(
        root.currentSection,
        root.controls.filter(control => String(control.section || "") === root.currentSection)
    )
    signal sectionRequested(string section)

    function field(controlId) {
        for (let index = 0; index < root.controls.length; ++index) {
            if (String(root.controls[index].id || "") === String(controlId || ""))
                return root.controls[index]
        }
        return ({id: controlId, value: "", enabled: false})
    }

    function fieldText(controlId, fallback) {
        const value = root.field(controlId).value
        const text = value === undefined || value === null ? "" : String(value)
        return text.length > 0 ? text : fallback
    }

    function edit(controlId, value) {
        root.bridge.setLiveAddonControl(controlId, value)
    }

    function preview(controlId, value) {
        root.bridge.previewLiveAddonControl(controlId, value)
    }

    function run(action) {
        if (action && action.id && action.type === "action" && action.enabled !== false)
            actionRouter.runAction(action)
    }

    function selectSection(section) {
        if (root.sections.indexOf(section) >= 0)
            root.sectionRequested(section)
    }

    // Keep the established picker, input-prompt, confirmation, and payload flow.
    NCLiveControlsGroup {
        id: actionRouter
        objectName: "audioStoryActionRouter"
        visible: false
        width: 0
        height: 0
        controls: []
        onActionTriggered: controlId => root.bridge.triggerLiveAddonAction(controlId)
        onActionWithPayload: (controlId, payload) => root.bridge.triggerLiveAddonActionWithPayload(controlId, payload)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.NCMetrics.space10

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space12

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Audio Story Mode")
                    color: Theme.NCTheme.text
                    font.pixelSize: Theme.NCTypography.titleSize
                    font.weight: Font.DemiBold
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Turn source audio into a planned, illustrated story, then play or cast it.")
                    color: Theme.NCTheme.textSecondary
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }

            NCStatusChip {
                text: String(root.bridge.selectedAddon.status || qsTr("Initialized"))
                status: "active"
            }
        }

        MprcPanel {
            objectName: "audioStoryProjectContext"
            Layout.fillWidth: true

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space12

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Label {
                        Layout.fillWidth: true
                        text: root.fieldText("audio_story_project_autosave_label", qsTr("No project selected"))
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.labelSize
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.fieldText("audio_story_project_chapter_status_label", qsTr("Choose a project to begin"))
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.captionSize
                        elide: Text.ElideRight
                    }
                }

                NCStatusChip {
                    text: qsTr("Autosave on")
                    status: "connected"
                }
            }
        }

        RowLayout {
            id: workflowRow
            objectName: "audioStoryWorkflowStrip"
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space6

            Repeater {
                model: root.workflowSteps
                delegate: Rectangle {
                    id: workflowStep
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.minimumWidth: 84
                    Layout.preferredHeight: 42
                    radius: Theme.NCMetrics.radiusMedium
                    color: String(workflowStep.modelData.section) === root.currentSection
                           ? Theme.NCTheme.surfaceSelected : Theme.NCTheme.surface
                    border.color: String(workflowStep.modelData.section) === root.currentSection
                                  ? Theme.NCTheme.accent : Theme.NCTheme.border

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.NCMetrics.space10
                        anchors.rightMargin: Theme.NCMetrics.space10
                        spacing: Theme.NCMetrics.space6
                        Label {
                            text: String(workflowStep.modelData.number)
                            color: Theme.NCTheme.accent
                            font.pixelSize: Theme.NCTypography.captionSize
                            font.weight: Font.Bold
                        }
                        Label {
                            Layout.fillWidth: true
                            text: String(workflowStep.modelData.label)
                            color: Theme.NCTheme.text
                            font.pixelSize: Theme.NCTypography.captionSize
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.selectSection(String(workflowStep.modelData.section))
                    }
                }
            }
        }

        Flickable {
            objectName: "audioStoryTabs"
            Layout.fillWidth: true
            Layout.preferredHeight: 40
            contentWidth: tabRow.implicitWidth
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            RowLayout {
                id: tabRow
                spacing: Theme.NCMetrics.space4
                Repeater {
                    model: root.sections
                    delegate: NCTabButton {
                        required property string modelData
                        text: LayoutMap.sectionTitle(modelData)
                        tutorialBridge: root.bridge
                        tutorialContext: ({workspace: "addons", addon: "audio_story_mode_runtime", section: modelData})
                        checked: modelData === root.currentSection
                        onClicked: root.selectSection(modelData)
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space8
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Label {
                    Layout.fillWidth: true
                    text: LayoutMap.sectionTitle(root.currentSection)
                    color: Theme.NCTheme.text
                    font.pixelSize: Theme.NCTypography.headingSize
                    font.weight: Font.DemiBold
                }
                Label {
                    Layout.fillWidth: true
                    text: LayoutMap.sectionDescription(root.currentSection)
                    color: Theme.NCTheme.textSecondary
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }
            NCButton {
                compact: true
                text: qsTr("Refresh")
                tone: "quiet"
                onClicked: root.bridge.refreshLiveAddonControls()
            }
        }

        ScrollView {
            id: pageScroll
            objectName: "audioStoryPageScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            GridLayout {
                width: pageScroll.availableWidth
                columns: width >= 860 ? 2 : 1
                columnSpacing: Theme.NCMetrics.space12
                rowSpacing: Theme.NCMetrics.space12

                Repeater {
                    model: root.sectionGroups.length
                    delegate: AudioStoryGroup {
                        required property int index
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        Layout.columnSpan: pageScroll.availableWidth >= 860
                                           ? Number(group.span || 2) : 1
                        sectionName: root.currentSection
                        group: root.sectionGroups[index] || ({})
                        controls: root.controls
                        onEdited: (controlId, value) => root.edit(controlId, value)
                        onPreviewed: (controlId, value) => root.preview(controlId, value)
                        onActionRequested: field => root.run(field)
                    }
                }
            }
        }
    }
}
