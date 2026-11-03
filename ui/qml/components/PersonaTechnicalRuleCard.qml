pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    required property string kind
    required property var providers
    property string providerId: ""
    property var entry: ({})
    property string personaName: ""
    property bool loading: false
    property bool showDefaults: false
    readonly property var provider: providers.find(row => row.id === providerId) || ({})
    readonly property bool custom: entry.enabled === true
    readonly property string displayText: custom ? String(entry.text || "") : String(provider.defaultText || "")
    signal providerChosen(string providerId)
    signal ruleEdited(bool enabled, string text)
    signal openProvider()
    function syncText() { loading = true; editor.text = displayText; loading = false }
    onDisplayTextChanged: syncText()
    Component.onCompleted: syncText()
    title: kind === "avatar" ? qsTr("Visual avatar tags") : qsTr("TTS voice provider tags")
    headerAccessory: NCStatusChip {
        text: root.custom ? qsTr("Persona override") : qsTr("Inherited")
        status: root.custom ? "active" : "info"
    }
    Label {
        text: root.kind === "avatar" ? qsTr("Avatar provider") : qsTr("TTS provider")
        color: Theme.NCTheme.textSecondary
    }
    NCComboBox {
        objectName: root.kind + "RuleProvider"
        Layout.fillWidth: true
        model: root.providers
        textRole: "label"
        currentIndex: root.providers.findIndex(row => row.id === root.providerId)
        label: root.kind === "avatar" ? qsTr("Avatar rules provider") : qsTr("TTS rules provider")
        toolTipText: qsTr("Choose which provider's rules to edit. This does not change the running engine.")
        onActivated: index => { if (index >= 0) root.providerChosen(String(root.providers[index].id)) }
    }
    NCSwitch {
        objectName: root.kind + "RuleOverride"
        Layout.fillWidth: true
        text: qsTr("Override for this persona")
        checked: root.custom
        toolTipText: qsTr("On replaces the provider defaults. Off inherits defaults and keeps your custom text for later.")
        onToggled: root.ruleEdited(checked, root.entry.text === undefined
                                  ? String(root.provider.defaultText || "") : String(root.entry.text))
    }
    Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        color: Theme.NCTheme.textSecondary
        text: root.custom ? qsTr("Custom rules for %1 · %2").arg(root.personaName).arg(root.provider.label || root.providerId)
                          : qsTr("Using %1 defaults").arg(root.provider.label || root.providerId)
    }
    NCScrollableTextArea {
        id: editor
        objectName: root.kind + "RuleText"
        Layout.fillWidth: true
        Layout.preferredHeight: 190
        accentBorder: root.custom
        readOnly: !root.custom
        label: root.title
        toolTipText: qsTr("Edit this persona's instructions for the selected provider. Enable the override first, then save persona overrides to apply your changes.")
        placeholderText: root.custom ? qsTr("Write custom instructions for this provider…") : qsTr("No default instructions for this provider.")
        onTextChanged: if (!root.loading && editorActiveFocus && root.custom) root.ruleEdited(true, text)
    }
    Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        color: Theme.NCTheme.textMuted
        text: root.custom ? qsTr("Replaces this provider's rules. An empty override adds no instructions.")
                          : qsTr("Enable the override to edit. Only supported tags can affect output.")
    }
    Flow {
        Layout.fillWidth: true
        spacing: 8
        NCButton {
            text: qsTr("Copy provider defaults")
            onClicked: root.ruleEdited(true, String(root.provider.defaultText || ""))
        }
        NCButton { text: root.showDefaults ? qsTr("Hide defaults") : qsTr("View defaults"); onClicked: root.showDefaults = !root.showDefaults }
        NCButton { text: qsTr("Open provider settings"); onClicked: root.openProvider() }
    }
    NCScrollableTextArea {
        visible: root.showDefaults
        Layout.fillWidth: true
        Layout.preferredHeight: 120
        readOnly: true
        text: String(root.provider.defaultText || "")
        label: qsTr("Provider defaults")
        toolTipText: qsTr("Read-only preview of the selected provider's defaults. Copy provider defaults to use them as a starting point for an override.")
    }
}
