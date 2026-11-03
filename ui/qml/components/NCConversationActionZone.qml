pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "../theme" as Theme

Item {
    id: root

    property var workspace
    property var messageData: ({})
    property string zoneName: "center"
    property string actionScope: "response"
    property var actionKeys: []
    property bool customizable: false
    property bool unifiedRail: false
    property bool dropHovered: false
    readonly property bool labelsEnabled: Boolean(
                                              workspace
                                              && workspace.bridge
                                              && workspace.bridge.conversationActionLabelsEnabled)
    readonly property bool transparentCardsEnabled: Boolean(
                                              workspace
                                              && workspace.bridge
                                              && workspace.bridge.conversationTransparentMessageCardsEnabled)

    implicitHeight: labelsEnabled ? 68 : 44

    function insertionIndex(pointerX) {
        const localX = pointerX - actionRow.x
        for (let index = 0; index < actionRow.children.length; index += 1) {
            const candidate = actionRow.children[index]
            if (!candidate || !candidate.visible || !candidate.actionKey)
                continue
            if (localX < candidate.x + candidate.width / 2)
                return Math.max(0, root.actionKeys.indexOf(candidate.actionKey))
        }
        return root.actionKeys.length
    }

    function placeActionAtScene(actionKey, sceneX, sceneY) {
        if (!root.workspace || !root.parent)
            return false
        const siblings = root.parent.children
        for (let index = 0; index < siblings.length; index += 1) {
            const candidate = siblings[index]
            if (!candidate || candidate.zoneName === undefined
                    || candidate.insertionIndex === undefined)
                continue
            const localPoint = candidate.mapFromItem(null, sceneX, sceneY)
            if (localPoint.x < 0 || localPoint.y < 0
                    || localPoint.x > candidate.width
                    || localPoint.y > candidate.height)
                continue
            const targetIndex = candidate.insertionIndex(localPoint.x)
            if (Boolean(candidate.unifiedRail)) {
                if (root.actionScope === "user")
                    root.workspace.placeUserMessageActionInRail(
                                String(actionKey), targetIndex)
                else
                    root.workspace.placeResponseActionInRail(
                                String(actionKey), targetIndex)
            } else if (root.actionScope === "user") {
                root.workspace.placeUserMessageAction(
                            String(actionKey),
                            String(candidate.zoneName),
                            targetIndex)
            } else {
                root.workspace.placeResponseAction(
                            String(actionKey),
                            String(candidate.zoneName),
                            targetIndex)
            }
            return true
        }
        return false
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.NCMetrics.radiusMedium
        color: root.dropHovered
               ? Theme.NCTheme.selection
               : root.unifiedRail
                 ? Theme.NCTheme.withAlpha(
                       Theme.NCTheme.surfaceRaised,
                       root.transparentCardsEnabled ? 0.16 : 0.52)
               : root.customizable
                 && root.workspace
                 && root.workspace.bridge.conversationResponsePlacementGuidesEnabled
               ? Theme.NCTheme.surfaceRaised : "transparent"
        border.width: root.unifiedRail
                      || (root.customizable
                          && root.workspace
                          && root.workspace.bridge.conversationResponsePlacementGuidesEnabled)
                      ? Theme.NCMetrics.borderWidth : 0
        border.color: root.dropHovered
                      ? Theme.NCTheme.accent
                      : root.unifiedRail
                        ? Theme.NCTheme.borderSubtle : Theme.NCTheme.borderStrong
        opacity: root.customizable ? 1.0 : 0.72
    }

    Label {
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: -Theme.NCMetrics.space12
        visible: root.customizable
                 && root.workspace
                 && root.workspace.bridge.conversationResponsePlacementGuidesEnabled
        text: root.unifiedRail ? qsTr("Action rail")
              : root.zoneName === "left" ? qsTr("Left")
              : root.zoneName === "right" ? qsTr("Right") : qsTr("Center")
        color: Theme.NCTheme.textMuted
        font.pixelSize: Theme.NCTypography.microSize
    }

    Row {
        id: actionRow
        anchors.verticalCenter: parent.verticalCenter
        x: root.zoneName === "left" ? Theme.NCMetrics.space2
           : root.zoneName === "right"
             ? Math.max(Theme.NCMetrics.space2,
                        parent.width - width - Theme.NCMetrics.space2)
             : Math.max(Theme.NCMetrics.space2, (parent.width - width) / 2)
        spacing: Theme.NCMetrics.space2

        Repeater {
            model: root.actionKeys

            delegate: Item {
                id: actionItem

                required property var modelData
                readonly property string actionKey: String(modelData)
                readonly property bool placementEnabled: root.customizable
                                                            && root.workspace
                                                            && !(root.actionScope === "user" && actionKey === "end_waiting")
                readonly property bool actionEnabled: root.workspace
                                                      && (root.actionScope === "user"
                                                          ? root.workspace.userMessageActionEnabled(
                                                                actionKey, root.messageData)
                                                          : root.workspace.responseActionEnabled(
                                                                actionKey, root.messageData))
                property real dragOriginX: 0
                property real dragOriginY: 0
                readonly property bool attention: root.actionScope === "response"
                                                  && root.workspace
                                                  && typeof root.workspace.responseActionAttention === "function"
                                                  && root.workspace.responseActionAttention(actionItem.actionKey)

                objectName: root.actionScope === "user"
                            ? "conversationUserAction_" + actionKey
                            : "conversationResponseAction_" + actionKey
                visible: root.workspace
                         && (root.actionScope === "user"
                             ? root.workspace.userMessageActionVisible(
                                   actionKey, root.messageData)
                             : root.workspace.responseActionVisible(
                                   actionKey, root.messageData))
                implicitWidth: root.labelsEnabled ? 60
                                                   : Theme.NCMetrics.controlHeightLarge
                implicitHeight: root.labelsEnabled ? 64
                                                    : Theme.NCMetrics.controlHeightLarge
                width: implicitWidth
                height: implicitHeight
                enabled: root.workspace
                         && (placementEnabled || actionEnabled)
                opacity: dragArea.drag.active ? 0.52 : 1.0
                z: dragArea.drag.active ? 50 : 1

                Drag.active: dragArea.drag.active
                Drag.source: actionItem
                Drag.keys: [root.actionScope === "user"
                            ? "nc-conversation-user-action"
                            : "nc-conversation-response-action"]
                Drag.dragType: Drag.Internal
                Drag.supportedActions: Qt.MoveAction
                Drag.proposedAction: Qt.MoveAction
                Drag.hotSpot.x: width / 2
                Drag.hotSpot.y: height / 2

                NCIconButton {
                    id: actionButton
                    objectName: "conversationActionButton"
                    interactionHovered: actionItem.actionEnabled && !dragArea.drag.active
                                        && !dragArea.pressed && !down
                                        && (hovered || dragArea.containsMouse)

                    // Feedback belongs to the hit target, not to the artwork.
                    // New icon designs can replace the content without changing it.
                    background: Rectangle {
                        objectName: "conversationActionHoverBackground"
                        radius: Theme.NCMetrics.radiusMedium
                        color: actionItem.attention
                               ? (actionButton.down || dragArea.pressed
                                  ? Theme.NCTheme.error : Theme.NCTheme.errorSoft)
                               : actionButton.down || dragArea.pressed
                               ? Theme.NCTheme.surfacePressed
                               : actionButton.interactionHovered || actionButton.selected
                                 ? Theme.NCTheme.selection : "transparent"
                        border.width: actionButton.activeFocus ? Theme.NCMetrics.focusWidth
                                      : actionItem.attention
                                        ? Theme.NCMetrics.borderWidth
                                      : actionButton.interactionHovered || actionButton.selected
                                        ? Theme.NCMetrics.borderWidth : 0
                        border.color: actionItem.attention
                                      ? Theme.NCTheme.error
                                      : actionButton.activeFocus
                                      ? Theme.NCTheme.focus : Theme.NCTheme.accent
                    }

                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    implicitWidth: Theme.NCMetrics.controlHeightLarge
                    implicitHeight: Theme.NCMetrics.controlHeightLarge
                    selected: root.workspace && (root.actionScope === "user"
                              ? actionItem.actionKey === "edit_draft"
                                && root.workspace.inlineResponseEditIndex === Number(root.messageData.historyIndex)
                              : root.workspace.responseActionSelected(
                                  actionItem.actionKey, root.messageData))
                    enabled: actionItem.actionEnabled
                    toolTipText: selected
                                  ? qsTr("Save edited message")
                                  : root.workspace
                                    ? (root.actionScope === "user"
                                       ? root.workspace.userMessageActionToolTip(
                                             actionItem.actionKey)
                                       : root.workspace.responseActionToolTip(
                                             actionItem.actionKey)) : ""

                    contentItem: Item {
                        NCConversationActionSvg {
                            objectName: "conversationActionIcon_"
                                        + root.actionScope + "_"
                                        + actionItem.actionKey
                            anchors.centerIn: parent
                            width: 24
                            height: 24
                            actionKey: root.actionScope === "response"
                                       && root.workspace
                                       && typeof root.workspace.responseActionIconKey === "function"
                                       ? root.workspace.responseActionIconKey(actionItem.actionKey)
                                       : actionItem.actionKey
                            actionScope: root.actionScope
                            enabled: actionButton.enabled
                        }
                    }

                    onClicked: {
                        if (root.workspace && !actionItem.placementEnabled)
                            if (root.actionScope === "user")
                                root.workspace.triggerUserMessageAction(
                                            actionItem.actionKey,
                                            root.messageData)
                            else
                                root.workspace.triggerResponseAction(
                                            actionItem.actionKey,
                                            root.messageData)
                    }
                }

                Label {
                    id: actionLabel

                    objectName: "conversationActionLabel_"
                                + root.actionScope + "_"
                                + actionItem.actionKey
                    anchors.top: actionButton.bottom
                    anchors.topMargin: Theme.NCMetrics.space2
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: parent.width
                    visible: root.labelsEnabled
                    text: root.workspace
                          ? (root.actionScope === "user"
                             ? root.workspace.userMessageActionLabel(
                                   actionItem.actionKey)
                             : root.workspace.responseActionLabel(
                                   actionItem.actionKey)) : ""
                    color: actionItem.actionEnabled
                           ? Theme.NCTheme.textMuted : Theme.NCTheme.borderStrong
                    font.pixelSize: Theme.NCTypography.microSize
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                }

                MouseArea {
                    id: dragArea
                    anchors.fill: parent
                    enabled: actionItem.placementEnabled
                    hoverEnabled: true
                    preventStealing: true
                    cursorShape: drag.active
                                 ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                    drag.target: actionItem
                    drag.axis: Drag.XAndYAxis
                    drag.threshold: 6

                    onPressed: {
                        actionItem.dragOriginX = actionItem.x
                        actionItem.dragOriginY = actionItem.y
                    }
                    onClicked: {
                        if (root.workspace)
                            if (root.actionScope === "user")
                                root.workspace.triggerUserMessageAction(
                                            actionItem.actionKey,
                                            root.messageData)
                            else
                                root.workspace.triggerResponseAction(
                                            actionItem.actionKey,
                                            root.messageData)
                    }
                    onReleased: function(mouse) {
                        const scenePoint = dragArea.mapToItem(
                                             null, mouse.x, mouse.y)
                        root.placeActionAtScene(
                                    actionItem.actionKey,
                                    scenePoint.x,
                                    scenePoint.y)
                        Qt.callLater(function() {
                            actionItem.x = actionItem.dragOriginX
                            actionItem.y = actionItem.dragOriginY
                        })
                    }
                    onCanceled: Qt.callLater(function() {
                        actionItem.x = actionItem.dragOriginX
                        actionItem.y = actionItem.dragOriginY
                    })
                }
            }
        }

    }

    DropArea {
        anchors.fill: parent
        enabled: root.customizable && root.workspace
        keys: [root.actionScope === "user"
               ? "nc-conversation-user-action"
               : "nc-conversation-response-action"]
        onEntered: root.dropHovered = true
        onExited: root.dropHovered = false
        onDropped: function(drop) {
            root.dropHovered = false
            drop.accept(Qt.MoveAction)
        }
    }
}
