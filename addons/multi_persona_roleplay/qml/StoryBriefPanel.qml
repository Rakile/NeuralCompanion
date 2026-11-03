pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

ColumnLayout {
    id: root
    objectName: "mprcStoryBriefPanel"
    required property var workspace
    readonly property var state: workspace.field("mprc_story_brief").storyBrief || ({})
    readonly property var proposal: state.proposal || null
    readonly property var fields: proposal ? proposal.fields : ({})
    property string chosenProvider: ""
    property bool initialized: false
    function initializeSelection() {
        if (!initialized && state.providers) {
            chosenProvider = state.provider || ""
            modelId.text = state.model || ""
            initialized = true
        }
    }
    property int acceptedRequest: -1
    onStateChanged: {
        initializeSelection()
        if (state.autoFill && state.proposal && !state.busy && acceptedRequest !== state.requestId) {
            acceptedRequest = state.requestId
            // Send the latest typed values, including fields that still have focus.
            // The backend rejects adoption if the user edited during generation.
            Qt.callLater(function() { root.command("apply") })
        }
    }
    Component.onCompleted: initializeSelection()
    spacing: 8

    function command(operation, extras) {
        let args = extras || {}
        if (["refine", "build", "retry", "models", "apply"].indexOf(operation) >= 0) {
            args = Object.assign({provider: chosenProvider, model: modelId.text, auto_fill: !previewOnly.checked, draft_edited: workspace.hasPendingMasterDraft(),
                inputs: workspace.storyBuilderInputs(false), baseline: workspace.storyBuilderInputs(true)}, args)
        }
        workspace.bridge.triggerLiveAddonActionWithPayload("mprc_story_brief",
            Object.assign({operation: operation}, args))
    }
    function selectedIndex(options, value) {
        for (let i = 0; i < options.length; ++i)
            if (options[i].value === value) return i
        return 0
    }
    Timer {
        interval: 600
        repeat: true
        running: root.visible
        onTriggered: root.workspace.bridge.refreshLiveAddonControls()
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Turn your idea into a story plan")
        color: Theme.NCTheme.text
        font.pixelSize: 15
        font.weight: Font.DemiBold
        wrapMode: Text.Wrap
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Write a rough idea above. Refine fills the story fields. Refine & build complete draft also creates the cast, scenes and lore in three steps. Review the result, then Apply Draft to activate it.")
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }
    GridLayout {
        Layout.fillWidth: true
        columns: width >= 720 ? 2 : 1
        columnSpacing: 12
        ColumnLayout {
            Layout.fillWidth: true
            Label { text: qsTr("Refinement provider"); color: Theme.NCTheme.textSecondary }
            NCComboBox {
                objectName: "mprcBriefProvider"
                Layout.fillWidth: true
                enabled: !root.state.busy
                label: qsTr("Refinement provider")
                model: root.state.providers || []
                textRole: "label"
                valueRole: "value"
                currentIndex: root.selectedIndex(model, root.chosenProvider)
                onActivated: { root.chosenProvider = currentValue; modelId.text = "" }
                toolTipText: qsTr("Uses this provider and model for both refinement actions and every complete-draft stage. Current main model follows your chat selection. The separate Generate Story Setup button uses the main model.")
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            visible: Boolean(root.chosenProvider)
            Label { text: qsTr("Model ID"); color: Theme.NCTheme.textSecondary }
            NCTextField {
                id: modelId
                objectName: "mprcBriefModel"
                Layout.fillWidth: true
                enabled: !root.state.busy
                label: qsTr("Refinement model ID")
                placeholderText: qsTr("Enter a model ID or choose from available models")
                toolTipText: qsTr("The model used for both refinement actions and all complete-draft stages. This does not switch or reconfigure the main chat model.")
            }
        }
    }
    Flow {
        Layout.fillWidth: true
        visible: Boolean(root.chosenProvider)
        spacing: 8
        NCButton {
            text: qsTr("Load models")
            compact: true
            enabled: !root.state.busy
            toolTipText: qsTr("Fetch this provider's model list using its existing NC connection.")
            onClicked: root.command("models")
        }
        NCComboBox {
            width: Math.min(380, parent.width)
            visible: root.chosenProvider === root.state.provider && (root.state.models || []).length > 0
            enabled: !root.state.busy
            label: qsTr("Available refinement models")
            toolTipText: qsTr("Choose a discovered model from the selected refinement provider. This fills the model ID for refinement without changing the main chat model.")
            model: root.state.models || []
            textRole: "label"
            valueRole: "value"
            currentIndex: root.selectedIndex(model, modelId.text)
            onActivated: modelId.text = currentValue
        }
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Cast plan: %1 profiles requested · New-character limit: %2 · Mode and SFW choice are preserved.")
            .arg(root.state.castCount === undefined ? "—" : root.state.castCount)
            .arg(root.state.castLimit === undefined ? "—" : root.state.castLimit)
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }
    NCCheckBox {
        id: previewOnly
        objectName: "mprcBriefPreviewOnly"
        text: qsTr("Preview only — do not fill fields automatically")
        enabled: !root.state.busy
        toolTipText: qsTr("By default, successful results fill the builder and, for a complete build, the editable draft. Check this to review before accepting. Neither action starts play.")
    }
    BusyIndicator {
        Layout.preferredWidth: 28
        Layout.preferredHeight: 28
        running: Boolean(root.state.busy)
        visible: running
    }
    Flow {
        Layout.fillWidth: true
        spacing: 8
        NCButton {
            objectName: "mprcBriefRefine"
            text: root.state.busy ? qsTr("Working…") : qsTr("Refine story idea")
            enabled: !root.state.busy
            compact: true
            toolTipText: qsTr("Ask the selected LLM to expand your idea, plan the requested cast, and propose all six text fields. Does not generate personas or start play.")
            onClicked: root.command("refine")
        }
        NCButton {
            objectName: "mprcBriefBuild"
            text: qsTr("Refine & build complete draft")
            enabled: !root.state.busy
            compact: true
            toolTipText: qsTr("Uses the selected model in three calls: refine the story, create the Master draft and cast, then create related scenes and lore. Review before Apply Draft.")
            onClicked: root.command("build")
        }
        NCButton {
            objectName: "mprcBriefRetry"
            text: qsTr("Retry failed stage")
            visible: Boolean(root.state.canRetry) && !root.state.busy
            compact: true
            toolTipText: qsTr("Continue from completed stages kept in memory. Inputs, provider, model and Master draft must be unchanged.")
            onClicked: root.command("retry")
        }
        NCButton {
            objectName: "mprcBriefDiscard"
            text: root.state.busy ? qsTr("Cancel") : qsTr("Discard preview")
            visible: root.state.busy || root.proposal !== null
            compact: true
            toolTipText: qsTr("Discard this request or preview and keep your current builder fields.")
            onClicked: root.command("discard")
        }
    }
    Label {
        Layout.fillWidth: true
        text: root.state.status || ""
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: root.proposal !== null
        Label {
            Layout.fillWidth: true
            text: qsTr("Proposed story prompt")
            color: Theme.NCTheme.text
            font.weight: Font.DemiBold
        }
        ScrollView {
            id: promptScroll
            objectName: "mprcBriefPromptScroll"
            Layout.fillWidth: true
            Layout.preferredHeight: 240
            implicitHeight: 240
            contentWidth: availableWidth
            contentHeight: promptText.implicitHeight
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AlwaysOn
            ScrollBar.vertical.objectName: "mprcBriefPromptScrollBar"
            NCTextArea {
                id: promptText
                objectName: "mprcBriefPromptText"
                width: promptScroll.availableWidth
                implicitHeight: Math.max(promptScroll.availableHeight, contentHeight + topPadding + bottomPadding)
                text: root.fields.master_story_prompt || ""
                readOnly: true
                label: qsTr("Proposed detailed story prompt and cast plan")
                toolTipText: qsTr("Read-only proposed story premise and cast plan. Accepting the preview fills the builder; Apply Draft activates the resulting story setup.")
            }
        }
        Repeater {
            model: [
                {key: "master_story_scene_title", label: qsTr("Opening scene")},
                {key: "master_story_location", label: qsTr("Location")},
                {key: "master_story_time_of_day", label: qsTr("Time / period")},
                {key: "master_story_mood", label: qsTr("Mood")},
                {key: "master_story_visual_direction", label: qsTr("Avatar visual direction")}
            ]
            delegate: Label {
                required property var modelData
                Layout.fillWidth: true
                text: modelData.label + ": " + (root.fields[modelData.key] || "")
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
            }
        }
        Label {
            Layout.fillWidth: true
            visible: Boolean(text)
            text: root.proposal ? (root.proposal.warnings || []).join("\n") : ""
            color: Theme.NCTheme.text
            wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            visible: Boolean(root.state.stale)
            text: qsTr("Your fields, cast settings or main model changed. Refine again to get an up-to-date preview.")
            color: Theme.NCTheme.text
            wrapMode: Text.Wrap
        }
        NCButton {
            objectName: "mprcBriefApply"
            text: root.proposal && root.proposal.master ? qsTr("Use complete draft") : qsTr("Use refined fields")
            compact: true
            enabled: !root.state.busy && !root.state.stale && root.chosenProvider === root.state.provider
                && (!root.chosenProvider || modelId.text === root.state.model)
            toolTipText: qsTr("Replace the Story prompt, Scene title, Location, Time, Mood and Avatar visual direction with this preview. Mode, SFW and cast settings stay as chosen. A complete build also fills the editable Master draft including Scenarios & Lore. Apply Draft remains a separate action.")
            onClicked: root.command("apply")
        }
    }
}
