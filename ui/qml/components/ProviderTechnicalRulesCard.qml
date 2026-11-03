pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    required property var bridge
    required property string kind
    required property string providerId
    property var catalog: ({})
    property var drafts: ({})
    property string message: ""
    property bool failed: false
    property bool loading: false
    readonly property bool packBased: kind === "avatar" && (providerId === "musetalk" || providerId === "ditto")
    readonly property string draftKey: kind + ":" + providerId
    readonly property var provider: (catalog[kind] || []).find(row => row.id === providerId) || ({})
    readonly property bool dirty: drafts[draftKey] !== undefined
    readonly property string value: dirty ? drafts[draftKey] : String(provider.defaultText || "")
    function syncText() { loading = true; editor.text = value; loading = false }
    function refresh() {
        if (bridge && typeof bridge.personaTechnicalRulesCatalog === "function") catalog = bridge.personaTechnicalRulesCatalog("")
    }
    function stage(text) { const next = Object.assign({}, drafts); next[draftKey] = text; drafts = next; message = "" }
    function discard() { const next = Object.assign({}, drafts); delete next[draftKey]; drafts = next; message = "" }
    function save() {
        const result = bridge.saveProviderTechnicalRules(kind, providerId, editor.text)
        failed = !result.accepted
        if (result.accepted) { discard(); refresh() }
        message = String(result.message || "")
    }
    onValueChanged: syncText()
    onProviderIdChanged: { message = ""; refresh(); syncText() }
    Component.onCompleted: { refresh(); syncText() }
    Connections {
        target: root.bridge
        ignoreUnknownSignals: true
        function onConfigurationChanged() { root.refresh() }
    }
    title: kind === "avatar" ? qsTr("Default visual avatar tag rules") : qsTr("Default TTS voice tag rules")
    description: qsTr("Default instructions for %1. Personas inherit these unless they use their own override or preserved combined rules.").arg(provider.label || providerId)
    NCScrollableTextArea {
        id: editor
        objectName: "providerTechnicalRulesText"
        Layout.fillWidth: true
        Layout.preferredHeight: 190
        label: root.title
        toolTipText: qsTr("Edit the default instructions inherited by personas using this provider. Save provider defaults to apply changes to the next reply; persona overrides stay unchanged.")
        accentBorder: editorActiveFocus
        placeholderText: qsTr("Write the supported tag instructions for this provider…")
        onTextChanged: if (!root.loading && editorActiveFocus) root.stage(text)
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Instructions do not add new provider capabilities. Use tags supported by your selected model or avatar package.")
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }
    Flow {
        Layout.fillWidth: true
        spacing: 8
        NCButton { text: root.packBased ? qsTr("Use pack defaults") : qsTr("Restore factory text"); onClicked: root.stage(String(root.provider.factoryText || "")) }
        NCButton { text: qsTr("Discard changes"); enabled: root.dirty; onClicked: root.discard() }
        NCButton {
            objectName: "saveProviderTechnicalRulesButton"
            text: qsTr("Save provider defaults"); tone: "primary"
            enabled: root.dirty
            onClicked: root.save()
        }
    }
    Label {
        Layout.fillWidth: true
        text: root.message || (root.packBased
              ? qsTr("Pack defaults follow the selected pack and enabled emotions automatically. Saved custom rules take priority. Persona overrides are not changed.")
              : qsTr("Changes apply to the next reply after saving. Persona overrides are not changed."))
        color: root.failed ? Theme.NCTheme.error : Theme.NCTheme.textMuted
        wrapMode: Text.Wrap
    }
}
