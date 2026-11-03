pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

Dialog {
    id: root
    objectName: "identityRelayReviewDialog"

    required property var bridge
    property var review: ({})
    property string selectedSubject: ""
    property var localDecisions: []
    property bool transientActive: false
    property bool advancedVisible: false
    property bool awaitingApply: false
    property string errorMessage: ""
    readonly property bool disconnectReview: Boolean(review.isDisconnect)
    readonly property var reviewItems: listValue(review.reviewItems)
    readonly property var transientRecords: listValue(review.transientRecords)
    readonly property var approveAction: ({label: qsTr("Approve"), value: "approve"})
    readonly property var reclassifyAction: ({label: qsTr("Reclassify"), value: "reclassify"})
    readonly property var narrowAction: ({label: qsTr("Narrow use"), value: "narrow_use"})
    readonly property var quarantineAction: ({label: qsTr("Quarantine"), value: "quarantine"})
    readonly property var actionOptions: [approveAction, reclassifyAction,
                                          narrowAction, quarantineAction]
    readonly property bool canSubmit: reviewIsComplete()

    modal: true
    focus: true
    closePolicy: Popup.NoAutoClose
    width: Math.min(parent ? parent.width - Theme.NCMetrics.space40 : 880, 880)
    height: Math.min(parent ? parent.height - Theme.NCMetrics.space40 : 720, 720)
    padding: Theme.NCMetrics.space20
    standardButtons: Dialog.NoButton

    function listValue(value) {
        return value && value.length !== undefined ? value : []
    }

    function optionIndex(options, value) {
        const values = listValue(options)
        for (let index = 0; index < values.length; ++index) {
            if (String(values[index].value || "") === String(value || ""))
                return index
        }
        return -1
    }

    function subjectOptions() {
        const supplied = listValue(review.subjectChoices)
        return [{label: qsTr("Choose the identity subject"), value: ""}].concat(supplied)
    }

    function choiceAllowed(options, value) {
        return optionIndex(options, value) >= 0
    }

    function allowedActionsFor(item) {
        return actionOptions.filter(function(action) {
            if (action.value === "reclassify")
                return listValue(item.supportedReclassifications).length > 0
            if (action.value === "narrow_use")
                return listValue(item.supportedRuntimeUseScopes).length > 0
            return true
        })
    }

    function initializeLocalState() {
        const current = String(review.subjectClass || "")
        selectedSubject = current !== "unknown"
                          && choiceAllowed(review.subjectChoices, current)
                          ? current : ""
        const defaults = []
        for (let index = 0; index < reviewItems.length; ++index) {
            const item = reviewItems[index] || {}
            defaults.push({
                reviewId: String(item.reviewId || ""),
                action: "approve",
                proposedValue: String(item.proposedValue || ""),
                replacementValue: "",
                allowedScope: "",
                sourceReason: String(item.reason || ""),
                priorState: String(item.state || "pending")
            })
        }
        localDecisions = defaults
        transientActive = false
        advancedVisible = false
        awaitingApply = false
        errorMessage = ""
    }

    function openForCurrentReview() {
        const state = bridge.identityRelayState || {}
        const nextReview = state.review || {}
        if (!Boolean(state.reviewReady)
                || Number(nextReview.reviewContractVersion || 0) !== 1)
            return false
        review = nextReview
        initializeLocalState()
        open()
        return true
    }

    function chooseSubject(value) {
        const candidate = String(value || "")
        if (candidate !== "" && !choiceAllowed(review.subjectChoices, candidate))
            return false
        selectedSubject = candidate
        errorMessage = ""
        return true
    }

    function chooseItemAction(index, action) {
        if (index < 0 || index >= localDecisions.length)
            return false
        const item = reviewItems[index] || {}
        const nextAction = String(action || "")
        if (!choiceAllowed(actionOptions, nextAction))
            return false
        const decisions = localDecisions.slice()
        const current = decisions[index]
        const next = {
            reviewId: current.reviewId,
            action: nextAction,
            proposedValue: current.proposedValue,
            replacementValue: "",
            allowedScope: "",
            sourceReason: current.sourceReason,
            priorState: current.priorState
        }
        if (nextAction === "reclassify") {
            const choices = listValue(item.supportedReclassifications)
            next.replacementValue = choices.length ? String(choices[0].value || "") : ""
        } else if (nextAction === "narrow_use") {
            const scopes = listValue(item.supportedRuntimeUseScopes)
            next.allowedScope = scopes.length ? String(scopes[0].value || "") : ""
        }
        decisions[index] = next
        localDecisions = decisions
        errorMessage = ""
        return true
    }

    function chooseReplacement(index, value) {
        if (index < 0 || index >= localDecisions.length)
            return false
        const item = reviewItems[index] || {}
        if (!choiceAllowed(item.supportedReclassifications, value))
            return false
        const decisions = localDecisions.slice()
        decisions[index] = Object.assign({}, decisions[index], {
            replacementValue: String(value || "")
        })
        localDecisions = decisions
        return true
    }

    function chooseScope(index, value) {
        if (index < 0 || index >= localDecisions.length)
            return false
        const item = reviewItems[index] || {}
        if (!choiceAllowed(item.supportedRuntimeUseScopes, value))
            return false
        const decisions = localDecisions.slice()
        decisions[index] = Object.assign({}, decisions[index], {
            allowedScope: String(value || "")
        })
        localDecisions = decisions
        return true
    }

    function reviewIsComplete() {
        if (!visible || awaitingApply || !Boolean(bridge.identityRelayState.reviewReady))
            return false
        if (!disconnectReview && selectedSubject.length === 0)
            return false
        if (localDecisions.length !== reviewItems.length)
            return false
        for (let index = 0; index < localDecisions.length; ++index) {
            const decision = localDecisions[index]
            const item = reviewItems[index] || {}
            if (String(decision.reviewId || "") !== String(item.reviewId || ""))
                return false
            if (decision.action === "reclassify"
                    && !choiceAllowed(item.supportedReclassifications,
                                      decision.replacementValue))
                return false
            if (decision.action === "narrow_use"
                    && !choiceAllowed(item.supportedRuntimeUseScopes,
                                      decision.allowedScope))
                return false
        }
        return true
    }

    function buildResult() {
        return {
            reviewContractVersion: Number(review.reviewContractVersion || 0),
            artifactRef: String(review.artifactRef || ""),
            artifactHash: String(review.artifactHash || ""),
            isDisconnect: disconnectReview,
            subjectClass: disconnectReview ? "" : selectedSubject,
            approved: reviewIsComplete(),
            itemDecisions: localDecisions.slice(),
            transientActive: disconnectReview || transientRecords.length === 0
                             ? null : Boolean(transientActive)
        }
    }

    function submitReview() {
        if (!reviewIsComplete()) {
            errorMessage = disconnectReview
                           ? qsTr("Confirm the disconnect review before continuing.")
                           : qsTr("Choose the identity subject and complete every review item.")
            return false
        }
        const result = buildResult()
        awaitingApply = true
        errorMessage = ""
        const accepted = Boolean(bridge.applyIdentityRelayReview(result))
        syncBackendState()
        if (!accepted) {
            awaitingApply = false
            errorMessage = String(bridge.identityRelayState.status
                                  || qsTr("The review was rejected. Check the values and try again."))
        }
        return accepted
    }

    function cancelReview() {
        if (awaitingApply)
            return false
        const accepted = Boolean(bridge.cancelIdentityRelayReview())
        if (accepted)
            close()
        return accepted
    }

    function syncBackendState() {
        if (!visible)
            return
        const state = bridge.identityRelayState || {}
        const phase = String(state.phase || "idle")
        if (phase === "applying") {
            awaitingApply = true
            return
        }
        if (phase === "review_ready") {
            const wasAwaiting = awaitingApply
            const nextReview = state.review || {}
            if (Number(nextReview.reviewContractVersion || 0) === 1) {
                const identityChanged = String(nextReview.artifactRef || "")
                                        !== String(review.artifactRef || "")
                                        || String(nextReview.artifactHash || "")
                                           !== String(review.artifactHash || "")
                                        || String(nextReview.normalizerRevision || "")
                                           !== String(review.normalizerRevision || "")
                review = nextReview
                if (identityChanged)
                    initializeLocalState()
            }
            awaitingApply = false
            if (wasAwaiting)
                errorMessage = String(state.status || qsTr("The review could not be applied."))
            return
        }
        const terminalSuccess = phase === "idle"
                                && !Boolean(state.pending)
                                && Object.keys(state.review || {}).length === 0
        if (awaitingApply && terminalSuccess) {
            awaitingApply = false
            close()
        } else if (awaitingApply && !Boolean(state.pending)) {
            awaitingApply = false
            errorMessage = String(state.status
                                  || qsTr("The review did not complete. Try again."))
        }
    }

    function itemEvidence(item) {
        const lines = []
        const paths = listValue(item.sourcePaths)
        const ids = listValue(item.recordIds)
        if (paths.length)
            lines.push(qsTr("Paths: %1").arg(paths.join(", ")))
        const sourceText = review.sourceTextByRecord || {}
        for (let index = 0; index < ids.length; ++index) {
            const text = String(sourceText[String(ids[index])] || "")
            if (text.length)
                lines.push(text)
        }
        return lines.join("\n")
    }

    Connections {
        target: root.bridge
        function onIdentityRelayChanged() { root.syncBackendState() }
    }

    Shortcut {
        sequences: [StandardKey.Cancel]
        enabled: root.visible && !root.awaitingApply
        onActivated: root.cancelReview()
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusLarge
        color: Theme.NCTheme.surface
        border.width: Theme.NCMetrics.focusWidth
        border.color: Theme.NCTheme.borderStrong
    }

    header: ColumnLayout {
        spacing: Theme.NCMetrics.space6
        Label {
            Layout.fillWidth: true
            text: root.disconnectReview ? qsTr("Disconnect Identity Relay")
                                        : qsTr("Review imported identity")
            color: Theme.NCTheme.text
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.titleSize
            font.weight: Theme.NCTypography.semibold
            wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            text: root.disconnectReview
                  ? qsTr("Confirm that this persona should stop using its imported identity.")
                  : String(root.review.identityLabel || qsTr("Imported identity"))
            color: Theme.NCTheme.textSecondary
            font.pixelSize: Theme.NCTypography.bodySize
            wrapMode: Text.Wrap
        }
    }

    contentItem: ScrollView {
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        ColumnLayout {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.NCMetrics.space12

            Rectangle {
                objectName: "identityRelayDisconnectConfirmation"
                Layout.fillWidth: true
                implicitHeight: disconnectText.implicitHeight + Theme.NCMetrics.space24
                radius: Theme.NCMetrics.radiusMedium
                color: Theme.NCTheme.errorSoft
                border.color: Theme.NCTheme.error
                visible: root.disconnectReview
                Label {
                    id: disconnectText
                    anchors.fill: parent
                    anchors.margins: Theme.NCMetrics.space12
                    text: qsTr("This disconnects Identity Relay from the persona after you confirm. The imported artifact is not deleted.")
                    color: Theme.NCTheme.text
                    wrapMode: Text.Wrap
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space6
                visible: !root.disconnectReview
                Label {
                    text: qsTr("Identity subject")
                    color: Theme.NCTheme.text
                    font.weight: Theme.NCTypography.semibold
                }
                NCComboBox {
                    toolTipText: qsTr("Identity subject to attach this reviewed artifact to. Changing the subject updates the review before confirmation.")

                    id: subjectSelector
                    objectName: "identityRelaySubjectSelector"
                    Layout.fillWidth: true
                    label: qsTr("Identity subject")
                    model: root.subjectOptions()
                    textRole: "label"
                    valueRole: "value"
                    currentIndex: root.optionIndex(model, root.selectedSubject)
                    enabled: !root.awaitingApply
                    onActivated: root.chooseSubject(currentValue)
                }
                Label {
                    Layout.fillWidth: true
                    visible: String(root.review.proposalStatus || "") !== "not_needed"
                    text: String(root.review.proposalMessage || "")
                          + (root.review.proposal && root.review.proposal.reason
                             ? "\n" + String(root.review.proposal.reason) : "")
                    color: Theme.NCTheme.textSecondary
                    wrapMode: Text.Wrap
                }
            }

            Repeater {
                model: root.disconnectReview ? [] : root.reviewItems
                delegate: NCCard {
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    title: qsTr("Review item %1").arg(index + 1)
                    description: String(modelData.reason || "")

                    NCComboBox {
                        toolTipText: qsTr("Choose how this item may be applied: approve it, quarantine it, reclassify it, or narrow its runtime use when those actions are supported. Changes remain in review until confirmation.")

                        objectName: "identityRelayItemDecisionControl"
                        Layout.fillWidth: true
                        label: qsTr("Decision")
                        model: root.allowedActionsFor(modelData)
                        textRole: "label"
                        valueRole: "value"
                        currentIndex: root.optionIndex(
                                          model,
                                          root.localDecisions[index]
                                          ? root.localDecisions[index].action : "approve")
                        enabled: !root.awaitingApply
                        onActivated: root.chooseItemAction(index, currentValue)
                    }

                    NCComboBox {
                        toolTipText: qsTr("Choose the supported replacement classification for this review item. Used only when its decision is Reclassify.")

                        Layout.fillWidth: true
                        label: qsTr("Reclassification")
                        model: modelData.supportedReclassifications || []
                        textRole: "label"
                        valueRole: "value"
                        visible: root.localDecisions[index]
                                 ? root.localDecisions[index].action === "reclassify"
                                 : false
                        enabled: !root.awaitingApply
                        currentIndex: root.optionIndex(
                                          model,
                                          root.localDecisions[index]
                                          ? root.localDecisions[index].replacementValue : "")
                        onActivated: root.chooseReplacement(index, currentValue)
                    }

                    NCComboBox {
                        toolTipText: qsTr("Choose the permitted runtime scope for this item. Used only when its decision narrows use; confirmation applies the reviewed restriction.")

                        Layout.fillWidth: true
                        label: qsTr("Allowed runtime use")
                        model: modelData.supportedRuntimeUseScopes || []
                        textRole: "label"
                        valueRole: "value"
                        visible: root.localDecisions[index]
                                 ? root.localDecisions[index].action === "narrow_use"
                                 : false
                        enabled: !root.awaitingApply
                        currentIndex: root.optionIndex(
                                          model,
                                          root.localDecisions[index]
                                          ? root.localDecisions[index].allowedScope : "")
                        onActivated: root.chooseScope(index, currentValue)
                    }

                    Label {
                        objectName: "identityRelayEvidence"
                        Layout.fillWidth: true
                        visible: root.advancedVisible
                        text: root.itemEvidence(modelData)
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.captionSize
                        wrapMode: Text.Wrap
                    }
                }
            }

            NCCard {
                objectName: "identityRelayTransientControls"
                Layout.fillWidth: true
                visible: !root.disconnectReview && root.transientRecords.length > 0
                title: qsTr("Transient continuity")
                description: qsTr("Temporary continuity is inactive by default and applies only to the current chat session.")
                NCCheckBox {
                    toolTipText: qsTr("Enable the reviewed temporary continuity for the current chat session. It is inactive by default and does not become permanent continuity.")

                    Layout.fillWidth: true
                    text: qsTr("Activate reviewed transient continuity for this session")
                    checked: root.transientActive
                    enabled: !root.awaitingApply
                    onToggled: root.transientActive = checked
                }
            }

            NCCheckBox {
                toolTipText: qsTr("Show source evidence and detailed transparency information for the review. This does not change which items are approved.")

                objectName: "identityRelayAdvancedReview"
                Layout.fillWidth: true
                visible: !root.disconnectReview
                text: qsTr("Show advanced evidence and transparency")
                checked: root.advancedVisible
                enabled: !root.awaitingApply
                onToggled: root.advancedVisible = checked
            }

            NCCard {
                objectName: "identityRelayTransparency"
                Layout.fillWidth: true
                visible: !root.disconnectReview && root.advancedVisible
                title: qsTr("Transparency")
                description: qsTr("Normalizer %1 · schema %2 · index %3")
                             .arg(String(root.review.normalizerRevision || ""))
                             .arg(String(root.review.schemaVersion || ""))
                             .arg(String(root.review.indexStatus || ""))
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Attestation: %1").arg(
                              String(root.review.attestationStatus || qsTr("not reviewed")))
                    color: Theme.NCTheme.textSecondary
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    visible: (root.review.policyNarrowing || []).length > 0
                    text: (root.review.policyNarrowing || []).join("\n")
                    color: Theme.NCTheme.warning
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    visible: (root.review.migrationMessages || []).length > 0
                    text: (root.review.migrationMessages || []).join("\n")
                    color: Theme.NCTheme.textMuted
                    wrapMode: Text.Wrap
                }
            }

            Label {
                Layout.fillWidth: true
                visible: root.errorMessage.length > 0
                text: root.errorMessage
                color: Theme.NCTheme.error
                wrapMode: Text.Wrap
            }
        }
    }

    footer: RowLayout {
        spacing: Theme.NCMetrics.space8
        layoutDirection: Qt.RightToLeft

        NCButton {
            objectName: "identityRelayReviewApply"
            text: root.disconnectReview ? qsTr("Disconnect") : qsTr("Apply review")
            tone: root.disconnectReview ? "danger" : "primary"
            busy: root.awaitingApply
            enabled: root.canSubmit
            onClicked: root.submitReview()
        }
        NCButton {
            objectName: "identityRelayReviewCancel"
            text: qsTr("Cancel")
            enabled: !root.awaitingApply
            onClicked: root.cancelReview()
        }
        Item { Layout.fillWidth: true }
    }
}
