pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../theme" as Theme

Item {
    id: root

    property bool consoleVisible: true
    property alias consoleContent: consoleHost.data
    property alias conversationContent: conversationHost.data
    property real rememberedConsoleWidth: 500
    property real minimumConversationWidth: 440
    readonly property real maximumConsoleWidth: Math.max(0, width - 18 - minimumConversationWidth)
    readonly property real consoleWidth: dragging ? dragWidth
                                                 : consoleVisible ? boundedWidth(rememberedConsoleWidth) : 0
    property bool dragging: false
    property real dragWidth: 0
    property bool tutorialDemonstrating: false
    signal consoleVisibilityRequested(bool value)

    function boundedWidth(value) {
        return Math.max(0, Math.min(maximumConsoleWidth, value))
    }

    function finishDrag() {
        if (!dragging)
            return
        if (dragWidth <= 24) {
            consoleVisibilityRequested(false)
        } else {
            rememberedConsoleWidth = boundedWidth(Math.max(320, dragWidth))
            consoleVisibilityRequested(true)
        }
        dragging = false
    }

    function demonstrateCollapse() {
        if (dragging || maximumConsoleWidth <= 0)
            return false
        tutorialDemonstrating = true
        dragWidth = boundedWidth(consoleVisible ? consoleWidth : rememberedConsoleWidth)
        dragging = true
        tutorialDrag.start()
        return true
    }

    function cancelTutorialDemonstration() {
        if (!tutorialDemonstrating) return
        tutorialDrag.stop()
        dragging = false
        tutorialDemonstrating = false
    }

    // Presentation only: use the same width as a pointer drag, without calling
    // finishDrag(), emitting visibility requests, or changing the saved width.
    SequentialAnimation {
        id: tutorialDrag
        PauseAnimation { duration: 250 }
        NumberAnimation {
            target: root; property: "dragWidth"; to: 0
            duration: 850; easing.type: Easing.InOutCubic
        }
        PauseAnimation { duration: 700 }
        NumberAnimation {
            target: root; property: "dragWidth"
            to: root.consoleVisible ? root.boundedWidth(root.rememberedConsoleWidth) : 0
            duration: 450; easing.type: Easing.InOutCubic
        }
        onStopped: {
            root.dragging = false
            root.tutorialDemonstrating = false
        }
    }

    onConsoleVisibleChanged: cancelTutorialDemonstration()
    onWidthChanged: cancelTutorialDemonstration()

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Item {
            id: consoleHost
            objectName: "conversationConsoleHost"
            Layout.fillHeight: true
            Layout.minimumWidth: root.consoleWidth
            Layout.preferredWidth: root.consoleWidth
            Layout.maximumWidth: root.consoleWidth
            clip: true
        }

        Item {
            id: handle
            objectName: "conversationSplitHandle"
            Layout.fillHeight: true
            Layout.minimumWidth: 18
            Layout.preferredWidth: 18
            Layout.maximumWidth: 18
            activeFocusOnTab: true
            Accessible.role: Accessible.Separator
            Accessible.name: root.consoleVisible
                             ? qsTr("Resize or hide system console")
                             : qsTr("Show system console")
            Keys.onSpacePressed: { root.cancelTutorialDemonstration(); root.consoleVisibilityRequested(!root.consoleVisible) }
            Keys.onReturnPressed: { root.cancelTutorialDemonstration(); root.consoleVisibilityRequested(!root.consoleVisible) }

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: pointer.pressed ? 3 : 1
                color: pointer.pressed ? Theme.NCTheme.accent
                       : pointer.containsMouse || handle.activeFocus ? Theme.NCTheme.borderStrong
                       : Theme.NCTheme.borderSubtle
            }

            Rectangle {
                anchors.centerIn: parent
                width: 12
                height: 54
                radius: 6
                color: pointer.pressed ? Theme.NCTheme.accentSoft
                       : pointer.containsMouse ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
                border.width: Theme.NCMetrics.borderWidth
                border.color: pointer.pressed ? Theme.NCTheme.accent
                              : pointer.containsMouse || handle.activeFocus ? Theme.NCTheme.borderStrong
                              : Theme.NCTheme.border
                Column {
                    anchors.centerIn: parent
                    spacing: 4
                    Repeater {
                        model: 3
                        delegate: Rectangle {
                            width: 3; height: 3; radius: 2
                            color: pointer.pressed ? Theme.NCTheme.accent : Theme.NCTheme.textMuted
                        }
                    }
                }
            }

            MouseArea {
                id: pointer
                anchors.fill: parent
                hoverEnabled: true
                preventStealing: true
                cursorShape: Qt.SplitHCursor
                property real pressOffset: 0
                property bool doubleClickConsumed: false
                onPressed: function(mouse) {
                    root.cancelTutorialDemonstration()
                    handle.forceActiveFocus()
                    pressOffset = mouse.x
                    doubleClickConsumed = false
                    root.dragWidth = consoleHost.width
                    root.dragging = true
                }
                onPositionChanged: function(mouse) {
                    if (pressed && !doubleClickConsumed)
                        root.dragWidth = root.boundedWidth(mapToItem(root, mouse.x, mouse.y).x - pressOffset)
                }
                onReleased: {
                    if (!doubleClickConsumed)
                        root.finishDrag()
                }
                onCanceled: root.dragging = false
                onDoubleClicked: {
                    doubleClickConsumed = true
                    root.dragging = false
                    root.consoleVisibilityRequested(!root.consoleVisible)
                }
            }

            NCToolTip {
                visible: pointer.containsMouse
                text: root.consoleVisible
                      ? qsTr("Drag to resize. Drag fully left or double-click to hide the console.")
                      : qsTr("Drag right or double-click to show the system console.")
            }
        }

        Item {
            id: conversationHost
            objectName: "conversationChatHost"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: Math.min(root.minimumConversationWidth, Math.max(0, root.width - 18))
        }
    }
}
