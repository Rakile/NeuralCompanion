pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    objectName: "discordBotAccounts"

    required property var bridge
    property var control: ({})
    readonly property var rows: root.control.rows || []
    property string editingId: ""
    property string removingId: ""
    property string requestNote: ""

    title: qsTr("Bot accounts")
    description: String(root.control.description || qsTr("Reuse these Discord accounts with your personas. Server and voice channel settings below are shared by the room."))
                 + " " + qsTr("Assign accounts on the persona cards in Local room → Discord mode. Live changes finish the current reply first; the moderator keeps its account.")

    function openEditor(account) {
        root.editingId = account ? String(account.id || "") : ""
        labelInput.text = account ? String(account.label || "") : ""
        tokenInput.text = ""
        editor.open()
    }

    function avatarSource(value) {
        const url = String(value || "").trim()
        return /^https:\/\/(?:cdn\.discordapp\.com|media\.discordapp\.net)(?::443)?\/(?:avatars\/\d+\/[A-Za-z0-9_]+|guilds\/\d+\/users\/\d+\/avatars\/[A-Za-z0-9_]+|embed\/avatars\/\d+)\.(?:png|webp|jpg|gif)(?:\?[^#]*)?$/.test(url) ? url : ""
    }

    function accountById(accountId) {
        for (let index = 0; index < root.rows.length; ++index) {
            if (String(root.rows[index].id || "") === accountId)
                return root.rows[index]
        }
        return null
    }

    function submitEditor() {
        if (!root.editingId && !tokenInput.text.trim())
            return
        if (root.editingId) {
            const account = root.accountById(root.editingId)
            if (!account || !account.can_edit)
                return
        }
        const payload = {label: labelInput.text.trim()}
        if (root.editingId)
            payload.account_id = root.editingId
        if (tokenInput.text.trim())
            payload.token = tokenInput.text.trim()
        const action = root.editingId ? "discord_account_update" : "discord_account_add"
        // Dispatch is asynchronous; the refreshed list and normal notifications
        // report the result. Closing this draft does not claim a successful save.
        tokenInput.text = ""
        root.bridge.triggerLiveAddonActionWithPayload(action, payload)
        root.requestNote = qsTr("Account change requested. Check the list and notifications for the result.")
        editor.close()
    }

    onVisibleChanged: if (!visible) {
        editor.close()
        removal.close()
        tokenInput.text = ""
    }

    headerAccessory: RowLayout {
        spacing: Theme.NCMetrics.space8
        NCButton {
            objectName: "discordAccountCheckAll"
            text: qsTr("Check all accounts")
            enabled: root.control.enabled !== false && root.rows.length > 0
            onClicked: {
                root.bridge.triggerLiveAddonActionWithPayload("discord_account_check_all", {})
                root.requestNote = qsTr("Account checks requested. Results will appear on each account.")
            }
        }
        NCButton {
            objectName: "discordAccountAdd"
            text: qsTr("Add account")
            tone: "primary"
            enabled: root.control.enabled !== false
            onClicked: root.openEditor(null)
        }
    }

    Label {
        Layout.fillWidth: true
        visible: root.rows.length === 0
        text: qsTr("No bot accounts yet. Add a bot token to get started.")
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }

    Repeater {
        model: root.rows
        delegate: Rectangle {
            id: accountRow
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: rowLayout.implicitHeight + Theme.NCMetrics.space24
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.windowRaised
            border.color: Theme.NCTheme.border

            ColumnLayout {
                id: rowLayout
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space12
                spacing: Theme.NCMetrics.space6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8
                    Rectangle {
                        Layout.preferredWidth: 44
                        Layout.preferredHeight: 44
                        Layout.alignment: Qt.AlignTop
                        radius: Theme.NCMetrics.radiusMedium
                        color: Theme.NCTheme.windowRaised
                        border.color: Theme.NCTheme.border
                        clip: true
                        Image {
                            id: portrait
                            objectName: "discordAccountAvatar_" + String(accountRow.modelData.id || "")
                            anchors.fill: parent
                            source: root.avatarSource(accountRow.modelData.avatar_url)
                            sourceSize.width: 88
                            sourceSize.height: 88
                            fillMode: Image.PreserveAspectCrop
                            visible: status === Image.Ready
                        }
                        Label {
                            objectName: "discordAccountInitial_" + String(accountRow.modelData.id || "")
                            anchors.centerIn: parent
                            text: String(accountRow.modelData.discord_name || accountRow.modelData.label || "B").trim().charAt(0).toUpperCase()
                            textFormat: Text.PlainText
                            color: Theme.NCTheme.textSecondary
                            font.pixelSize: 20
                            visible: portrait.status !== Image.Ready
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space4
                        Label {
                            Layout.fillWidth: true
                            text: String(accountRow.modelData.label || qsTr("Bot account"))
                            textFormat: Text.PlainText
                            color: Theme.NCTheme.text
                            font.weight: Font.DemiBold
                            wrapMode: Text.Wrap
                        }
                        Label {
                            objectName: "discordAccountName_" + String(accountRow.modelData.id || "")
                            Layout.fillWidth: true
                            visible: text.length > 0
                            text: String(accountRow.modelData.discord_name || "")
                            textFormat: Text.PlainText
                            color: Theme.NCTheme.textSecondary
                            wrapMode: Text.Wrap
                        }
                        Label {
                            objectName: "discordAccountNickname_" + String(accountRow.modelData.id || "")
                            Layout.fillWidth: true
                            visible: Boolean(accountRow.modelData.bot_nickname)
                            text: qsTr("Server nickname: %1").arg(String(accountRow.modelData.bot_nickname || ""))
                            textFormat: Text.PlainText
                            color: Theme.NCTheme.textSecondary
                            wrapMode: Text.Wrap
                        }
                        Label {
                            objectName: "discordAccountNicknameWarning_" + String(accountRow.modelData.id || "")
                            Layout.fillWidth: true
                            visible: text.length > 0
                            text: String(accountRow.modelData.nickname_error || "")
                            textFormat: Text.PlainText
                            color: Theme.NCTheme.textSecondary
                            wrapMode: Text.Wrap
                        }
                        Label {
                            objectName: "discordAccountPersona_" + String(accountRow.modelData.id || "")
                            Layout.fillWidth: true
                            text: accountRow.modelData.assigned_persona
                                  ? qsTr("Assigned persona: %1").arg(String(accountRow.modelData.assigned_persona))
                                  : qsTr("Available")
                            textFormat: Text.PlainText
                            color: Theme.NCTheme.textSecondary
                            wrapMode: Text.Wrap
                        }
                        Label {
                            objectName: "discordAccountVerification_" + String(accountRow.modelData.id || "")
                            Layout.fillWidth: true
                            text: String(accountRow.modelData.verification_message || qsTr("Not checked yet."))
                            textFormat: Text.PlainText
                            color: Theme.NCTheme.textMuted
                            wrapMode: Text.Wrap
                        }
                        Label {
                            objectName: "discordAccountStatus_" + String(accountRow.modelData.id || "")
                            Layout.fillWidth: true
                            text: String(accountRow.modelData.status || qsTr("Disconnected"))
                            textFormat: Text.PlainText
                            color: Theme.NCTheme.textMuted
                            wrapMode: Text.Wrap
                        }
                    }
                    NCButton {
                        objectName: "discordAccountEdit_" + String(accountRow.modelData.id || "")
                        text: qsTr("Edit")
                        compact: true
                        enabled: root.control.enabled !== false && Boolean(accountRow.modelData.can_edit)
                        onClicked: root.openEditor(accountRow.modelData)
                    }
                    NCButton {
                        objectName: "discordAccountRemove_" + String(accountRow.modelData.id || "")
                        text: qsTr("Remove")
                        compact: true
                        enabled: root.control.enabled !== false && Boolean(accountRow.modelData.can_remove)
                        onClicked: {
                            root.removingId = String(accountRow.modelData.id || "")
                            removal.open()
                        }
                    }
                }
                Label {
                    objectName: "discordAccountBlocked_" + String(accountRow.modelData.id || "")
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: String(accountRow.modelData.blocked_reason || "")
                    textFormat: Text.PlainText
                    color: Theme.NCTheme.textMuted
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    Label {
        Layout.fillWidth: true
        visible: root.requestNote.length > 0
        text: root.requestNote
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }

    NCDialog {
        id: editor
        objectName: "discordAccountEditor"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: root.editingId ? qsTr("Edit bot account") : qsTr("Add bot account")
        description: qsTr("Only a bot token is required for a new account. Discord discovers the bot ID when it connects.")
        footer: null
        onClosed: { tokenInput.text = ""; labelInput.text = ""; root.editingId = "" }

        ColumnLayout {
            width: parent.width
            spacing: Theme.NCMetrics.space12
            NCTextField {
                toolTipText: qsTr("Optional local label for this reusable Discord bot account. Leave blank for an automatic Bot1, Bot2 label.")

                id: labelInput
                objectName: "discordAccountLabel"
                Layout.fillWidth: true
                label: qsTr("Account label (optional)")
                placeholderText: qsTr("Label (optional, defaults to Bot1, Bot2, …)")
            }
            NCTextField {
                toolTipText: qsTr("Discord bot token checked when saving this account. When editing an existing account, leave blank to retain its saved token.")

                id: tokenInput
                objectName: "discordAccountToken"
                Layout.fillWidth: true
                label: qsTr("Bot token")
                placeholderText: root.editingId ? qsTr("Leave blank to keep the saved token") : qsTr("Bot token (required)")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
            }
            RowLayout {
                NCButton {
                    objectName: "discordAccountSave"
                    text: root.editingId ? qsTr("Save changes") : qsTr("Add account")
                    tone: "primary"
                    enabled: root.control.enabled !== false && (root.editingId
                        ? Boolean(root.accountById(root.editingId) && root.accountById(root.editingId).can_edit)
                        : tokenInput.text.trim().length > 0)
                    onClicked: root.submitEditor()
                }
                NCButton {
                    objectName: "discordAccountCancel"
                    text: qsTr("Cancel")
                    onClicked: { tokenInput.text = ""; editor.reject() }
                }
            }
        }
    }

    NCDialog {
        id: removal
        objectName: "discordAccountRemoveDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Remove account?")
        description: qsTr("Remove this saved Discord bot account? Personas and conversation history will be kept.")
        footer: null
        onClosed: root.removingId = ""
        RowLayout {
            NCButton {
                objectName: "discordAccountRemoveConfirm"
                text: qsTr("Remove account")
                tone: "danger"
                enabled: root.control.enabled !== false
                    && Boolean(root.accountById(root.removingId) && root.accountById(root.removingId).can_remove)
                onClicked: {
                    root.bridge.triggerLiveAddonActionWithPayload("discord_account_remove", {account_id: root.removingId})
                    root.requestNote = qsTr("Account change requested. Check the list and notifications for the result.")
                    removal.close()
                }
            }
            NCButton {
                objectName: "discordAccountRemoveCancel"
                text: qsTr("Cancel")
                onClicked: removal.reject()
            }
        }
    }
}
