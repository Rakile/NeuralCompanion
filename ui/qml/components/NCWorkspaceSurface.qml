pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "TutorialRoutes.js" as TutorialRoutes
import "TutorialStyle.js" as TutorialStyle
import "../workspaces"

Item {
    id: root

    required property var bridge
    property string workspaceKey: ""
    property bool avatarOnly: false
    readonly property alias workspaceItem: workspaceLoader.item

    NCButton {
        id: tutorialButton
        objectName: "workspaceTutorialButton"
        anchors.top: parent.top
        anchors.right: parent.right
        text: qsTr("Tutorial")
        tutorialText: true
        visible: !root.avatarOnly && TutorialStyle.showButtons(root.bridge)
        compact: true
        tone: "quiet"
        onClicked: tutorialMenu.openFor(tutorialButton,
            TutorialRoutes.context(root.workspaceItem, root.workspaceKey, root.bridge), false)
    }
    NCTutorialMenu { id: tutorialMenu; bridge: root.bridge }

    Loader {
        id: workspaceLoader
        anchors.fill: parent
        anchors.topMargin: tutorialButton.visible ? tutorialButton.height + 4 : 0
        asynchronous: false
        sourceComponent: {
            switch (root.workspaceKey) {
            case "runtime": return runtimeWorkspace
            case "addons": return addonsWorkspace
            case "conversation": return conversationWorkspace
            case "visuals": return visualsWorkspace
            case "musetalk": return musetalkWorkspace
            default: return null
            }
        }
    }

    Component {
        id: runtimeWorkspace
        RuntimeWorkspace { bridge: root.bridge }
    }

    Component {
        id: addonsWorkspace
        AddonsWorkspace { bridge: root.bridge }
    }

    Component {
        id: conversationWorkspace
        ConversationWorkspace { bridge: root.bridge }
    }

    Component {
        id: visualsWorkspace
        VisualsWorkspace {
            bridge: root.bridge
            previewKind: "visualReply"
            onFloatVisualReplyRequested: root.bridge.detachWorkspace("visuals")
        }
    }

    Component {
        id: musetalkWorkspace
        VisualsWorkspace {
            bridge: root.bridge
            previewKind: "musetalk"
            avatarOnly: root.avatarOnly
            onFloatMusetalkPreviewRequested: root.bridge.detachWorkspace("musetalk")
        }
    }
}
