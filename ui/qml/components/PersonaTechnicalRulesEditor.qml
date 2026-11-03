pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    required property var bridge
    property string personaId: ""
    property string selectedKind: "" // Empty keeps both cards for other hosts.
    property var catalog: ({})
    property var drafts: ({})
    property string avatarId: ""
    property string ttsId: ""
    property string message: ""
    property bool failed: false
    property bool showLegacy: false
    readonly property var rules: drafts[personaId] || catalog.rules || ({avatar: {}, tts: {}, legacy_enabled: true})
    readonly property bool dirty: drafts[personaId] !== undefined
    readonly property bool available: Boolean(catalog.available)
    spacing: Theme.NCMetrics.space12
    function refresh() {
        if (!bridge || typeof bridge.personaTechnicalRulesCatalog !== "function") return
        catalog = bridge.personaTechnicalRulesCatalog(personaId)
        if (!(catalog.avatar || []).some(row => row.id === avatarId)) avatarId = String(catalog.activeAvatar || "none")
        if (!(catalog.tts || []).some(row => row.id === ttsId)) ttsId = String(catalog.activeTts || "none")
    }
    function stage(next) {
        const all = Object.assign({}, drafts); all[personaId] = next; drafts = all; message = ""
    }
    function edit(kind, provider, enabled, text) {
        if (!available) return
        const next = JSON.parse(JSON.stringify(rules)); next[kind] = next[kind] || ({})
        next[kind][provider] = {enabled: enabled, text: text}; stage(next)
    }
    function discard() {
        const all = Object.assign({}, drafts); delete all[personaId]; drafts = all; message = ""; refresh()
    }
    function save() {
        if (!available) return
        const result = bridge.savePersonaTechnicalRules(personaId, rules)
        failed = !result.accepted
        if (result.accepted) discard()
        message = String(result.message || "")
    }
    Component.onCompleted: refresh()
    onPersonaIdChanged: { message = ""; refresh() }
    onVisibleChanged: if (visible) refresh()
    Connections {
        target: root.bridge
        ignoreUnknownSignals: true
        function onQuickPersonaChanged() { root.refresh() }
        function onConfigurationChanged() { root.refresh() }
    }
    NCSectionHeader {
        Layout.fillWidth: true
        title: root.selectedKind === "avatar" ? qsTr("Visual avatar tags")
             : root.selectedKind === "tts" ? qsTr("TTS voice provider tags") : qsTr("Expression and voice rules")
        description: qsTr("Use provider defaults, or save custom rules for this persona.")
    }
    Label {
        visible: !root.available
        Layout.fillWidth: true
        text: qsTr("Choose or save a persona to edit its provider-specific rules.")
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }
    ColumnLayout {
        visible: Boolean(root.catalog.hasLegacy)
        Layout.fillWidth: true
        NCSwitch {
            objectName: "keepLegacyTechnicalRules"
            text: qsTr("Keep existing combined rules active")
            toolTipText: qsTr("Keep your original combined avatar and voice instructions active. Turn off and save to use separate provider rules; the original text is preserved.")
            checked: root.rules.legacy_enabled !== false
            onToggled: { const next = Object.assign({}, root.rules); next.legacy_enabled = checked; root.stage(next) }
        }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: Theme.NCTheme.warning
            text: root.rules.legacy_enabled !== false
                  ? qsTr("Your original custom instructions are still active. Turn this off and save to use the separate rules below. The original text stays saved.")
                  : qsTr("Separate provider rules will be used after saving. Your original combined instructions remain preserved.")
        }
        NCButton { text: root.showLegacy ? qsTr("Hide original rules") : qsTr("View original rules"); onClicked: root.showLegacy = !root.showLegacy }
        NCScrollableTextArea {
            visible: root.showLegacy
            Layout.fillWidth: true
            Layout.preferredHeight: 150
            text: String(root.catalog.legacyText || "")
            readOnly: true
            label: qsTr("Preserved original rules")
            toolTipText: qsTr("Read-only copy of your original combined instructions, preserved when separate provider overrides were introduced.")
        }
    }
    GridLayout {
        Layout.fillWidth: true
        columns: !root.selectedKind && root.width >= 900 ? 2 : 1
        columnSpacing: 16
        rowSpacing: 16
        enabled: root.available
        PersonaTechnicalRuleCard {
            objectName: "personaAvatarRulesCard"
            visible: !root.selectedKind || root.selectedKind === "avatar"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            kind: "avatar"
            providers: root.catalog.avatar || []
            providerId: root.avatarId
            personaName: String(root.catalog.name || "")
            entry: (root.rules.avatar || {})[root.avatarId] || ({})
            onProviderChosen: providerId => root.avatarId = providerId
            onRuleEdited: (enabled, text) => root.edit("avatar", root.avatarId, enabled, text)
            onOpenProvider: root.bridge.openTechnicalRulesProvider("avatar", root.avatarId)
        }
        PersonaTechnicalRuleCard {
            objectName: "personaTtsRulesCard"
            visible: !root.selectedKind || root.selectedKind === "tts"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            kind: "tts"
            providers: root.catalog.tts || []
            providerId: root.ttsId
            personaName: String(root.catalog.name || "")
            entry: (root.rules.tts || {})[root.ttsId] || ({})
            onProviderChosen: providerId => root.ttsId = providerId
            onRuleEdited: (enabled, text) => root.edit("tts", root.ttsId, enabled, text)
            onOpenProvider: root.bridge.openTechnicalRulesProvider("tts", root.ttsId)
        }
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Each provider keeps its own rules for this persona. Turning an override off keeps its custom text.")
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }
    Flow {
        Layout.fillWidth: true
        spacing: 8
        NCButton { text: qsTr("Discard changes"); enabled: root.dirty; onClicked: root.discard() }
        NCButton {
            objectName: "savePersonaTechnicalRulesButton"
            text: qsTr("Save persona overrides"); tone: "primary"
            enabled: root.dirty && root.available
            onClicked: root.save()
        }
    }
    Label {
        Layout.fillWidth: true
        text: root.message || qsTr("Changes apply to the next reply after saving.")
        color: root.failed ? Theme.NCTheme.error : Theme.NCTheme.textMuted
        wrapMode: Text.Wrap
    }
}
