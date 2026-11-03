pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

Rectangle {
    id: root
    objectName: "mprcStoryWorkflow"
    required property var workspace
    property int selectedStep: 0
    signal navigationRequested(string section, string groupKey)

    readonly property var steps: [
        {title: qsTr("Create story"), section: "Master", group: "builder", optional: false,
            instruction: qsTr("Describe your story, choose a provider/model, then Refine & build complete draft.")},
        {title: qsTr("Scenes & lore"), section: "Scenarios & Lore", group: "", optional: true,
            instruction: qsTr("Review the generated scenes and lore. Send to Master Draft if you make changes.")},
        {title: qsTr("Apply story"), section: "Master", group: "draft", optional: false,
            instruction: qsTr("Review the draft in Master and use Apply when it is ready.")},
        {title: qsTr("Voices & media"), section: "Voice", group: "", optional: true,
            instruction: qsTr("Optionally set character voices, story images and story sounds.")},
        {title: qsTr("Check setup"), section: "Story Health", group: "", optional: false,
            instruction: qsTr("Review Story Health for setup issues before you play.")},
        {title: qsTr("Play"), section: "Play", group: "", optional: false,
            instruction: qsTr("Start or continue your applied story in Play.")}
    ]
    readonly property var currentStep: steps[Math.max(0, Math.min(steps.length - 1, selectedStep))]

    function goToStep(index) {
        if (index < 0 || index >= steps.length)
            return
        selectedStep = index
        navigationRequested(steps[index].section, steps[index].group)
    }

    function syncSection() {
        const section = String(workspace.currentSection || "")
        // Master contains two steps; retain an explicit Apply selection there.
        if (section === "Master")
            selectedStep = selectedStep === 2 ? 2 : 0
        else if (section === "Scenarios & Lore")
            selectedStep = 1
        else if (section === "Voice" || section === "Story Images" || section === "Story Sounds")
            selectedStep = 3
        else if (section === "Story Health")
            selectedStep = 4
        else if (section === "Play")
            selectedStep = 5
    }

    // Selection indicates navigation, never whether a story step is complete.
    Connections {
        target: root.workspace
        function onCurrentSectionChanged() { root.syncSection() }
    }
    Component.onCompleted: syncSection()

    implicitHeight: content.implicitHeight + Theme.NCMetrics.space16
    radius: Theme.NCMetrics.radiusSmall
    color: Theme.NCTheme.surface
    border.color: Theme.NCTheme.border

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.NCMetrics.space8
        spacing: Theme.NCMetrics.space6

        Flow {
            id: stepButtons
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space6
            readonly property int columns: width >= 1150 ? 6 : width >= 600 ? 3 : 2
            Repeater {
                model: root.steps
                delegate: NCButton {
                    required property int index
                    required property var modelData
                    objectName: "mprcWorkflowStep" + (index + 1)
                    width: Math.floor((stepButtons.width - stepButtons.spacing * (stepButtons.columns - 1)) / stepButtons.columns)
                    compact: true
                    text: (index + 1) + ". " + modelData.title + (modelData.optional ? qsTr(" (optional)") : "")
                    tone: root.selectedStep === index ? "primary" : "secondary"
                    toolTipText: modelData.instruction
                    Accessible.description: modelData.instruction
                    onClicked: root.goToStep(index)
                }
            }
        }

        Label {
            Layout.fillWidth: true
            text: qsTr("Step %1 of %2: %3").arg(root.selectedStep + 1).arg(root.steps.length).arg(root.currentStep.instruction)
            color: Theme.NCTheme.textSecondary
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.captionSize
            wrapMode: Text.Wrap
        }

        Flow {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space6
            NCButton {
                objectName: "mprcWorkflowPrevious"
                width: 94
                compact: true
                text: qsTr("Previous")
                enabled: root.selectedStep > 0
                toolTipText: qsTr("Open the previous step.")
                onClicked: root.goToStep(root.selectedStep - 1)
            }
            NCButton {
                objectName: "mprcWorkflowNext"
                width: 80
                compact: true
                text: qsTr("Next")
                enabled: root.selectedStep < root.steps.length - 1
                toolTipText: qsTr("Open the next step. Your story is changed only by the controls in each tab.")
                onClicked: root.goToStep(root.selectedStep + 1)
            }
            NCButton {
                objectName: "mprcWorkflowSkip"
                width: 122
                compact: true
                visible: root.currentStep.optional
                text: qsTr("Skip optional")
                toolTipText: qsTr("Continue without changing this optional setup.")
                onClicked: root.goToStep(root.selectedStep + 1)
            }
            NCButton {
                objectName: "mprcWorkflowImages"
                width: 122
                compact: true
                visible: root.selectedStep === 3
                text: qsTr("Story Images")
                onClicked: root.navigationRequested("Story Images", "")
            }
            NCButton {
                objectName: "mprcWorkflowSounds"
                width: 128
                compact: true
                visible: root.selectedStep === 3
                text: qsTr("Story Sounds")
                onClicked: root.navigationRequested("Story Sounds", "")
            }
            NCButton {
                objectName: "mprcWorkflowContinue"
                width: 188
                compact: true
                text: qsTr("Continue current story")
                toolTipText: qsTr("Open Play to continue the currently applied story.")
                onClicked: root.goToStep(5)
            }
        }
    }
}
