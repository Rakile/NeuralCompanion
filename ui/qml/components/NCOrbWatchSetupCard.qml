import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    objectName: "orbWatchSetupCard"
    property var setupState: ({})
    property string draft: ""
    property bool submitting: false
    property bool reviewing: false
    property var reviewedState: ({})
    signal startOrb()
    signal enableAddon()
    signal initializeRuntime()
    signal configureModel()
    signal chooseTarget()
    signal openSettings()
    signal scopeEdited(string mode)
    signal confirmSetup(string confirmationKey)
    signal draftEdited(string text)
    signal submitWatch(string text)

    function beginReview() {
        reviewedState = setupState
        reviewing = true
    }
    function act() {
        switch (String(setupState.action || "")) {
        case "addon": enableAddon(); break
        case "start": startOrb(); break
        case "initialize": initializeRuntime(); break
        case "model": configureModel(); break
        case "target": chooseTarget(); break
        case "enable": beginReview(); break
        default: openSettings(); break
        }
    }
    function send() {
        if (submitting || !setupState.ready || !draft.trim())
            return
        submitting = true
        submitWatch(draft)
        submitting = false
    }

    title: qsTr("Companion Orb")
    description: qsTr("Ask normally in chat: a question gets an answer; an ongoing request creates a watch. All watches use the current capture target, including a region.")

    Label {
        Layout.fillWidth: true
        objectName: "orbWatchReadiness"
        text: String(root.setupState.state || qsTr("Checking setup…"))
        color: Theme.NCTheme.text
        wrapMode: Text.Wrap
    }
    Label {
        Layout.fillWidth: true
        text: (root.setupState.reasons || []).join("\n")
        visible: text.length > 0
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }
    NCButton {
        objectName: "orbWatchSetupAction"
        visible: !root.setupState.ready
        text: ({addon: qsTr("Enable addon for next restart"), start: qsTr("Start / show Orb"),
            initialize: qsTr("Initialize"), model: qsTr("Choose / verify vision model"),
            target: qsTr("Show Orb to choose a target"), enable: qsTr("Enable watching…"),
            settings: qsTr("Review capture settings")})[String(root.setupState.action || "")] || qsTr("Review setup")
        onClicked: root.act()
    }
    RowLayout {
        Layout.fillWidth: true
        NCButton { text: qsTr("Show Orb"); onClicked: root.startOrb() }
        NCButton { text: qsTr("Vision settings"); onClicked: root.openSettings() }
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("What the Orb can see: %1").arg(String((root.setupState.scope || {}).label || qsTr("No target")))
        wrapMode: Text.Wrap
        color: Theme.NCTheme.text
    }
    NCComboBox {
        objectName: "orbWatchCaptureScope"
        toolTipText: qsTr("Choose the window under the Orb, a region around it, or the entire screen as the capture target for Orb questions and watches. Selecting a scope or target does not create a watch.")
        Layout.fillWidth: true
        model: [qsTr("Window under Orb"), qsTr("Region around Orb"), qsTr("Entire screen")]
        currentIndex: Math.max(0, ["window", "region", "screen"].indexOf(String((root.setupState.scope || {}).mode || "window")))
        enabled: String(root.setupState.action || "") !== "addon"
        onActivated: index => root.scopeEdited(["window", "region", "screen"][index])
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Left-drag: a region. Right-drag: a window; on desktop background: that screen. Resize the region from the Orb’s right-click menu. Selecting a target does not create a watch.")
        wrapMode: Text.Wrap
        color: Theme.NCTheme.textSecondary
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: root.reviewing
        Label {
            Layout.fillWidth: true
            text: qsTr("Enable background capture and proactive replies for: %1").arg(String((root.reviewedState.scope || {}).label || ""))
            color: Theme.NCTheme.text
            wrapMode: Text.Wrap
        }
        Repeater {
            model: root.reviewedState.image_recipients || []
            delegate: Label {
                required property var modelData
                Layout.fillWidth: true
                text: String(modelData.label || "") + " — " + String(modelData.location || "")
                    + (modelData.remote ? qsTr(" (images may leave this computer; API charges may apply)") : qsTr(" (local endpoint)"))
                wrapMode: Text.Wrap
                color: Theme.NCTheme.textSecondary
            }
        }
        Label {
            Layout.fillWidth: true
            visible: (root.reviewedState.affected_sources || []).length > 0
            text: qsTr("These shared background/reply permissions also affect enabled sensors: %1").arg((root.reviewedState.affected_sources || []).join(", "))
            wrapMode: Text.Wrap
            color: Theme.NCTheme.textSecondary
        }
        RowLayout {
            NCButton {
                objectName: "confirmOrbWatchSetup"
                toolTipText: qsTr("Enable the reviewed background capture and proactive-reply permissions for the displayed target and image recipients. Shared permissions also affect the enabled sensors listed above.")
                text: qsTr("Confirm enable watching")
                onClicked: { root.confirmSetup(String(root.reviewedState.confirmation_key || "")); root.reviewing = false }
            }
            NCButton { text: qsTr("Cancel"); onClicked: root.reviewing = false }
        }
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Watch something… (or just ask in normal chat)")
        wrapMode: Text.Wrap
        color: Theme.NCTheme.text
    }
    NCTextField {
        objectName: "orbWatchDraft"
        toolTipText: qsTr("Describe what to keep watching in the current Orb capture target, or ask a one-time visual question. Enter sends the request when setup is ready; typing alone does not create a watch.")
        Layout.fillWidth: true
        text: root.draft
        placeholderText: qsTr("What should I keep an eye on?")
        onTextEdited: root.draftEdited(text)
        onAccepted: root.send()
        Keys.onEscapePressed: root.reviewing = false
    }
    Flow {
        Layout.fillWidth: true
        spacing: 8
        NCButton { text: qsTr("Comment on a video"); onClicked: root.draftEdited("Keep commenting on the video I’m watching.") }
        NCButton { text: qsTr("Watch a title"); onClicked: root.draftEdited("Tell me when the video title changes.") }
    }
    NCButton {
        objectName: "submitOrbWatch"
        text: qsTr("Send request")
        enabled: Boolean(root.setupState.ready) && root.draft.trim().length > 0 && !root.submitting
        onClicked: root.send()
    }
}
