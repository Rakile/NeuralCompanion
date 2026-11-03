import QtQuick
import QtQuick.Controls
import "../../../ui/qml/theme" as Theme

Item {
    id: root
    objectName: "mprcScenarioTab"
    required property var workspace
    signal masterRequested()
    readonly property var snapshot: workspace.field("mprc_scenario_builder").scenarioBuilder || ({})
    property string stateFingerprint: ""

    function send(operation, args) {
        workspace.bridge.triggerLiveAddonActionWithPayload("mprc_scenario_builder", {operation: operation, args: args || []})
    }
    function receive() {
        // Play polling must not recreate form editors or discard text being typed.
        if (snapshot.state) {
            const fingerprint = JSON.stringify(snapshot.state)
            if (fingerprint !== stateFingerprint) {
                stateFingerprint = fingerprint
                facade.state = snapshot.state
            }
        }
        facade.playState = snapshot.playState || ({status: "Start MPRC Play to load the applied scenario.", choices: [], retries: []})
        facade.currentModel = snapshot.currentModel || ""
    }
    onSnapshotChanged: receive()
    onVisibleChanged: if (visible) send("open")
    Component.onCompleted: { receive(); if (visible) send("open") }

    Timer {
        interval: 750
        repeat: true
        running: root.visible
        onTriggered: root.workspace.bridge.refreshLiveAddonControls()
    }
    QtObject {
        id: facade
        property var state: null
        property var playState: ({status: "", choices: [], retries: []})
        property string currentModel: ""
        function selectGroup(value) { root.send("selectGroup", [value]) }
        function selectParent(value) { root.send("selectParent", [value]) }
        function selectRecord(value) { root.send("selectRecord", [value]) }
        function editField(id, value) { root.send("editField", [id, value]) }
        function manageRecord(value) { root.send("manageRecord", [value]) }
        function condition(id, op, value, group) { root.send("condition", [id, op, value, group]) }
        function refine(id, instruction) { root.send("refine", [id, instruction]) }
        function cancelRefinement() { root.send("cancelRefinement") }
        function applyPreview() { root.send("applyPreview") }
        function acceptDraft() { root.send("acceptDraft") }
        function loadExample() { root.send("loadExample") }
        function reload() { root.send("reload") }
        function previewLore(text) { root.send("previewLore", [text]) }
        function executeChoice(id) { root.send("executeChoice", [id]) }
        function retryEvent(id) { root.send("retryEvent", [id]) }
    }
    Label {
        anchors.centerIn: parent
        visible: !editor.active
        text: "Loading scenario draft…"
        color: Theme.NCTheme.textSecondary
    }
    Loader {
        id: editor
        anchors.fill: parent
        active: facade.state !== null
        sourceComponent: ScenarioBuilder {
            scenarioBuilder: facade
            onMasterRequested: root.masterRequested()
        }
    }
}
