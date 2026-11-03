pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

NCCard {
    id: root
    required property var controller
    readonly property var profileState: controller ? controller.state : ({profiles: [], selectedName: "", selectedSummary: "", canLoad: false, error: "", status: ""})
    property string replacementName: ""
    title: qsTr("Saved speech timing setups")
    description: qsTr("Save the current timing values without running a Performance Check. Each setup also records the avatar engine, TTS provider, language provider/model and streaming mode.")

    function saveCurrent() {
        const name = profileName.text.trim()
        const existing = (root.profileState.profiles || []).find(item => String(item.name).toLowerCase() === name.toLowerCase())
        if (existing) {
            root.replacementName = String(existing.name)
            replaceDialog.open()
        } else if (root.controller) {
            root.controller.save(name, false)
        }
    }

    NCComboBox {
        id: profiles
        objectName: "timingProfileSelector"
        Layout.fillWidth: true
        label: qsTr("Saved speech timing setup")
        toolTipText: qsTr("Choose a saved setup to view it. Your timing and provider selections change only when you press Load.")
        model: root.profileState.profiles || []
        textRole: "display_name"
        valueRole: "name"
        currentIndex: {
            const rows = root.profileState.profiles || []
            return rows.findIndex(item => String(item.name) === String(root.profileState.selectedName))
        }
        displayText: currentIndex < 0 ? qsTr("Choose a saved setup") : currentText
        onActivated: {
            if (root.controller && currentValue !== undefined) {
                root.controller.select(String(currentValue))
                profileName.text = String(currentValue)
            }
        }
    }

    Label {
        Layout.fillWidth: true
        visible: text.length > 0
        text: String(root.profileState.selectedSummary || "")
        wrapMode: Text.Wrap
        color: Theme.NCTheme.textSecondary
    }

    Flow {
        Layout.fillWidth: true
        spacing: 10
        NCButton {
            objectName: "timingProfileLoad"
            text: qsTr("Load")
            enabled: Boolean(root.profileState.canLoad)
            toolTipText: qsTr("Apply this setup's timing values. Turn on the adjacent switch to also restore its saved providers, language model and streaming mode. No models are started by this button.")
            onClicked: root.controller.load(loadSetup.checked)
        }
        NCSwitch {
            id: loadSetup
            objectName: "timingProfileLoadSetup"
            checked: false
            text: qsTr("Also load providers and model")
            enabled: Boolean(root.profileState.canLoad)
            toolTipText: qsTr("Off: load timing only. On: also restore the saved avatar engine, TTS provider, language provider/model and streaming mode when you press Load. Stop the chat before changing providers or model. Credentials, voices, avatar packages and generation settings are not loaded from the profile.")
        }
        NCButton {
            objectName: "timingProfileDelete"
            text: qsTr("Delete")
            tone: "quiet"
            enabled: Boolean(root.profileState.selectedName)
            toolTipText: qsTr("Delete the selected saved profile file after confirmation. This does not change current timing or remove models, voices or avatar packages.")
            onClicked: deleteDialog.open()
        }
    }

    RowLayout {
        Layout.fillWidth: true
        NCTextField {
            id: profileName
            objectName: "timingProfileName"
            Layout.fillWidth: true
            label: qsTr("Setup name")
            placeholderText: qsTr("For example, Ditto + Chatterbox")
            maximumLength: 100
            toolTipText: qsTr("Give this timing setup a name you will recognize. Saving an existing name asks before replacing its file.")
            onAccepted: root.saveCurrent()
        }
        NCButton {
            objectName: "timingProfileSave"
            text: qsTr("Save current")
            enabled: profileName.text.trim().length > 0 && root.controller !== null
            toolTipText: qsTr("Save all current speech timing values and provider/model selections under this name. A Dry Run is not required, and saving does not change your active setup.")
            onClicked: root.saveCurrent()
        }
    }

    Label {
        objectName: "timingProfileStatus"
        Layout.fillWidth: true
        visible: text.length > 0
        wrapMode: Text.Wrap
        text: String(root.profileState.error || root.profileState.status || "")
        color: root.profileState.error ? Theme.NCTheme.error : Theme.NCTheme.textSecondary
    }

    NCDialog {
        id: replaceDialog
        objectName: "timingProfileReplaceDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Replace saved setup?")
        description: qsTr("Replace “%1” with the current speech timing and provider/model selections?").arg(root.replacementName)
        footer: null
        Flow {
            width: parent.width
            spacing: 8
            NCButton {
                objectName: "timingProfileReplaceConfirm"
                text: qsTr("Replace")
                onClicked: { if (root.controller.save(root.replacementName, true)) replaceDialog.close() }
            }
            NCButton { text: qsTr("Cancel"); onClicked: replaceDialog.close() }
        }
    }
    NCDialog {
        id: deleteDialog
        objectName: "timingProfileDeleteDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Delete saved setup?")
        description: qsTr("Permanently delete “%1”? Your current settings and installed models stay available. This profile may also appear in Performance Check.").arg(String(root.profileState.selectedName || ""))
        footer: null
        Flow {
            width: parent.width
            spacing: 8
            NCButton {
                objectName: "timingProfileDeleteConfirm"
                text: qsTr("Delete")
                tone: "danger"
                onClicked: { if (root.controller.deleteSelected()) deleteDialog.close() }
            }
            NCButton { text: qsTr("Cancel"); onClicked: deleteDialog.close() }
        }
    }
}
