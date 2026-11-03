import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    required property var bridge
    property var relay: ({})
    property bool showAccountHelp: false
    spacing: 12
    function submit(action, values) {
        const payload = Object.assign({}, values || {}, {action: action})
        bridge.triggerLiveAddonActionWithPayload("main_chat_relay_action", payload)
        password.text = ""
        token.text = ""
        mfaCode.text = ""
        recoveryCode.text = ""
    }
    Label { text: root.relay.value || qsTr("Sign in to NC Relay."); wrapMode: Text.Wrap; Layout.fillWidth: true; color: Theme.NCTheme.textSecondary }
    Label { text: qsTr("LAN pairing stays local. Internet uses your NC Relay account and an encrypted peer connection."); wrapMode: Text.Wrap; Layout.fillWidth: true; color: Theme.NCTheme.textSecondary }
    NCButton { text: qsTr("Prepare Internet runtime"); visible: !root.relay.dependencies_ready; enabled: !root.relay.busy; onClicked: root.submit("prepare") }
    Label { text: qsTr("Signed in as ") + String((root.relay.account || {}).username || ""); visible: Boolean(root.relay.authenticated); color: Theme.NCTheme.textSecondary }
    NCTextField {
        id: inviteCode; objectName: "relayInviteCode"; Layout.fillWidth: true
        visible: !root.relay.authenticated && !root.relay.mfa_pending
        placeholderText: qsTr("Invitation code (required to create an account)")
        selectByMouse: true
    }
    ColumnLayout {
        objectName: "relayMfaPanel"
        visible: Boolean(root.relay.mfa_pending)
        Layout.fillWidth: true
        spacing: 10
        Label {
            text: root.relay.mfa_status === "recovery_codes" ? qsTr("Save your recovery codes") : qsTr("Two-factor authentication")
            font.bold: true; color: Theme.NCTheme.text
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.NCTheme.textSecondary
            text: root.relay.mfa_status === "recovery_codes"
                ? qsTr("Store these codes somewhere safe. Each can be used once if you lose access to your authenticator. They are shown only now.")
                : root.relay.mfa_status === "mfa_enrollment_required"
                ? qsTr("Every account requires an authenticator. Add NC Relay to Google Authenticator by scanning the QR code or entering the setup key, then confirm with its six-digit code.")
                : qsTr("Enter the six-digit code from Google Authenticator, or use one saved recovery code.")
        }
        NCButton {
            text: root.relay.mfa_secret ? qsTr("Generate a new setup key") : qsTr("Set up authenticator")
            visible: root.relay.mfa_status === "mfa_enrollment_required"
            enabled: !root.relay.busy
            onClicked: root.submit("mfa_enroll")
        }
        Image {
            visible: root.relay.mfa_status === "mfa_enrollment_required" && Boolean(root.relay.mfa_qr)
            source: visible ? String(root.relay.mfa_qr || "") : ""
            cache: false; fillMode: Image.PreserveAspectFit
            Layout.preferredWidth: 220; Layout.preferredHeight: 220
        }
        NCTextField {
            id: mfaSecret; objectName: "relayMfaSecret"; Layout.fillWidth: true
            visible: Boolean(root.relay.mfa_secret); readOnly: true; selectByMouse: true
            text: String(root.relay.mfa_secret || "")
        }
        NCButton {
            text: qsTr("Copy setup key"); visible: Boolean(root.relay.mfa_secret)
            onClicked: { mfaSecret.selectAll(); mfaSecret.copy() }
        }
        NCTextField {
            id: mfaCode; objectName: "relayMfaCode"; Layout.fillWidth: true
            visible: root.relay.mfa_status !== "recovery_codes"
            placeholderText: qsTr("Authenticator code"); maximumLength: 6
            inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhNoPredictiveText
            echoMode: TextInput.Password; selectByMouse: true
        }
        NCButton {
            objectName: "relayMfaConfirm"; text: qsTr("Confirm authenticator")
            visible: root.relay.mfa_status === "mfa_enrollment_required"
            enabled: !root.relay.busy && Boolean(root.relay.mfa_secret) && /^\d{6}$/.test(mfaCode.text)
            onClicked: root.submit("mfa_confirm", {code: mfaCode.text})
        }
        NCButton {
            objectName: "relayMfaVerify"; text: qsTr("Verify and sign in")
            visible: root.relay.mfa_status === "mfa_required"
            enabled: !root.relay.busy && /^\d{6}$/.test(mfaCode.text)
            onClicked: root.submit("mfa_verify", {code: mfaCode.text})
        }
        NCTextField {
            id: recoveryCode; objectName: "relayRecoveryCode"; Layout.fillWidth: true
            visible: root.relay.mfa_status === "mfa_required"
            placeholderText: qsTr("Recovery code"); echoMode: TextInput.Password
            maximumLength: 17; selectByMouse: true
        }
        NCButton {
            text: qsTr("Use recovery code"); visible: root.relay.mfa_status === "mfa_required"
            enabled: !root.relay.busy && /^[a-fA-F0-9]{8}-[a-fA-F0-9]{8}$/.test(recoveryCode.text)
            onClicked: root.submit("mfa_verify", {recoveryCode: recoveryCode.text})
        }
        NCTextArea {
            id: recoveryList; objectName: "relayRecoveryList"; Layout.fillWidth: true
            visible: root.relay.mfa_status === "recovery_codes"
            text: (root.relay.mfa_recovery_codes || []).join("\n")
            readOnly: true; selectByMouse: true; Layout.preferredHeight: 220
        }
        NCButton {
            text: qsTr("Copy recovery codes"); visible: recoveryList.visible
            onClicked: { recoveryList.selectAll(); recoveryList.copy() }
        }
        NCCheckBox {
            id: recoverySaved; objectName: "relayRecoverySaved"
            visible: recoveryList.visible; text: qsTr("I have saved my recovery codes")
            onVisibleChanged: if (!visible) checked = false
        }
        NCButton {
            text: qsTr("Continue to NC Relay"); visible: recoveryList.visible
            enabled: recoverySaved.checked && !root.relay.busy
            onClicked: root.submit("mfa_acknowledge")
        }
        NCButton { text: qsTr("Cancel sign-in"); enabled: !root.relay.busy; onClicked: root.submit("mfa_cancel") }
    }
    NCTextField {
        toolTipText: qsTr("NC Relay username or email for sign-in. Create account uses this field as the username.")
        id: identifier; objectName: "relayIdentifier"; Layout.fillWidth: true; placeholderText: qsTr("Username or email"); visible: !root.relay.authenticated; selectByMouse: true }
    NCTextField {
        toolTipText: qsTr("Email address for creating an NC Relay account or requesting a password-reset code.")
        id: email; objectName: "relayEmail"; Layout.fillWidth: true; placeholderText: qsTr("Email for registration / password reset"); visible: !root.relay.authenticated || root.showAccountHelp; selectByMouse: true }
    NCTextField {
        toolTipText: qsTr("NC Relay password. Account creation and password reset require at least 12 characters; desktop replacement also requires your password.")
        id: password; objectName: "relayPassword"; visible: !root.relay.authenticated || root.showAccountHelp || replaceConfirm.visible; Layout.fillWidth: true; placeholderText: qsTr("Password (12+ characters for registration)"); echoMode: TextInput.Password; selectByMouse: true }
    Flow {
        Layout.fillWidth: true; spacing: 8
        NCButton { objectName: "relaySignIn"; text: qsTr("Sign in"); visible: !root.relay.authenticated && !root.relay.mfa_pending; enabled: !root.relay.busy && identifier.text.length > 0 && password.text.length > 0; onClicked: root.submit("login", {identifier: identifier.text, password: password.text}) }
        NCButton { text: qsTr("Create account"); visible: !root.relay.authenticated && !root.relay.mfa_pending; enabled: !root.relay.busy && email.text.length > 0 && password.text.length >= 12 && inviteCode.text.length > 0; onClicked: { root.submit("register_account", {username: identifier.text, email: email.text, password: password.text, inviteCode: inviteCode.text}); inviteCode.text = "" } }
        NCButton { objectName: "relayConnect"; toolTipText: qsTr("Connect to NC Relay using your saved sign-in. Starts the Internet worker; Disconnect stops it without signing out."); text: qsTr("Connect"); visible: !root.relay.internet_enabled && !root.relay.mfa_pending; enabled: !root.relay.busy; onClicked: root.submit("connect") }
        NCButton { toolTipText: qsTr("Disconnect Internet phones and stop the Internet worker. Your saved sign-in and LAN services are kept."); text: qsTr("Disconnect"); visible: Boolean(root.relay.internet_enabled); enabled: !root.relay.busy; onClicked: root.submit("disconnect") }
        NCButton { text: qsTr("Sign out"); visible: Boolean(root.relay.authenticated); enabled: !root.relay.busy; onClicked: root.submit("logout") }
    }
    Label { text: root.relay.online ? qsTr("Desktop online · active phones: ") + Number(root.relay.peer_count || 0) : qsTr("Desktop is not online"); color: root.relay.online ? Theme.NCTheme.text : Theme.NCTheme.textSecondary }
    NCCheckBox {
        objectName: "relayRouterMapping"
        toolTipText: qsTr("Try creating temporary UDP port mappings on a compatible router for a direct phone connection. TURN remains available as fallback. Off by default; disconnect all phones before changing this setting.")
        text: qsTr("Try direct connection using router port mapping")
        checked: Boolean(root.relay.router_mapping_enabled)
        enabled: !root.relay.busy && Number(root.relay.peer_count || 0) === 0
        onClicked: root.submit("set_router_mapping", {enabled: checked})
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Off by default. Opens temporary UDP ports using PCP, NAT-PMP or UPnP. TURN stays available. Disconnect the phone before changing this setting.")
        wrapMode: Text.Wrap
        color: Theme.NCTheme.textSecondary
    }
    Label {
        visible: Boolean(root.relay.router_mapping_enabled)
        text: qsTr("Router mapping: ") + String(root.relay.router_mapping_status || "ready")
        color: Theme.NCTheme.textSecondary
    }
    NCButton { text: root.showAccountHelp ? qsTr("Hide account help") : qsTr("Email verification / password help"); tone: "quiet"; onClicked: root.showAccountHelp = !root.showAccountHelp }
    NCTextField {
        toolTipText: qsTr("Verification or password-reset code supplied by the NC Relay account flow. Use the matching Verify email or Reset password action.")
        visible: root.showAccountHelp; id: token; Layout.fillWidth: true; placeholderText: qsTr("Verification or password-reset code"); echoMode: TextInput.Password; selectByMouse: true }
    Flow {
        visible: root.showAccountHelp
        Layout.fillWidth: true; spacing: 8
        NCButton { text: qsTr("Verify email"); enabled: !root.relay.busy && token.text.length > 0; onClicked: root.submit("verify_email", {token: token.text}) }
        NCButton { text: qsTr("Resend verification"); visible: Boolean(root.relay.authenticated) && !root.relay.email_verified; enabled: !root.relay.busy; onClicked: root.submit("resend_verification") }
        NCButton { text: qsTr("Forgot password"); enabled: !root.relay.busy && email.text.length > 0; onClicked: root.submit("forgot_password", {email: email.text}) }
        NCButton { text: qsTr("Reset password"); enabled: !root.relay.busy && token.text.length > 0 && password.text.length >= 12; onClicked: root.submit("reset_password", {token: token.text, password: password.text}) }
    }
    NCCheckBox {
        toolTipText: qsTr("Confirm replacing the desktop currently registered to your Relay account. The old desktop will be disconnected when you confirm replacement.")
        id: replaceConfirm; visible: root.relay.error_code === "DESKTOP_REPLACEMENT_REQUIRED"; text: qsTr("Replace the registered desktop and disconnect it") }
    NCButton { text: qsTr("Confirm desktop replacement"); visible: replaceConfirm.visible; enabled: replaceConfirm.checked && password.text.length > 0 && !root.relay.busy; onClicked: { root.submit("replace_desktop", {password: password.text}); replaceConfirm.checked = false } }
    BusyIndicator { running: Boolean(root.relay.busy); visible: running; implicitWidth: 28; implicitHeight: 28 }
}
