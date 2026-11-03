pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCSpellcheckTextArea {
    id: root
    required property var commands
    property bool autoscroll: true
    property bool pasteImageEnabled: false
    readonly property real minimumComposerHeight: Theme.NCMetrics.controlHeight
    readonly property real maximumComposerHeight: Math.ceil(composerMetrics.lineSpacing) * 14
                                                  + topPadding + bottomPadding
    implicitHeight: Math.max(minimumComposerHeight, contentHeight + topPadding + bottomPadding)
    topPadding: Theme.NCMetrics.space8
    bottomPadding: Theme.NCMetrics.space8
    selectByMouse: true
    FontMetrics { id: composerMetrics; font: root.font }
    property var commandRows: []
    property int commandIndex: -1
    readonly property bool commandMenuVisible: commandMenu.visible
    readonly property string highlightedCommand: commandIndex >= 0 && commandIndex < commandRows.length
                                                 ? commandRows[commandIndex].command : ""
    signal sendRequested(string text)
    signal autoscrollRequested(bool value)

    function refreshChoices(preserveSelection) {
        const previousCommand = preserveSelection ? highlightedCommand : ""
        commandRows = commands.choices(text, autoscroll)
        commandIndex = previousCommand ? commandRows.findIndex(row => row.command === previousCommand && row.enabled) : -1
        if (commandIndex < 0)
            moveChoice(1)
        if (activeFocus && commandRows.length > 0 && text.startsWith("/"))
            commandMenu.open()
        else
            commandMenu.close()
    }

    function moveChoice(direction) {
        const count = commandRows.length
        for (let step = 1; step <= count; step++) {
            const index = (commandIndex + direction * step + count) % count
            if (commandRows[index].enabled) {
                commandIndex = index
                commandList.positionViewAtIndex(index, ListView.Contain)
                return
            }
        }
    }

    function replaceInput(value) {
        text = value
        cursorPosition = text.length
        bridge.setConversationComposerDraft(text)
    }

    function runCommand(value) {
        const result = commands.execute(value, autoscroll)
        if (result.action === "chat") {
            sendRequested(value)
        } else if (result.action === "complete") {
            replaceInput(result.text)
            refreshChoices()
        } else if (result.action === "menu") {
            replaceInput("/")
            refreshChoices()
        } else if (result.action === "local" || result.action === "autoscroll") {
            if (result.action === "autoscroll")
                autoscrollRequested(result.value)
            replaceInput("")
            commandMenu.close()
        } else if (result.action === "draft") {
            commandMenu.close()
        }
    }

    function acceptChoice(index) {
        if (index < 0 || index >= commandRows.length || !commandRows[index].enabled)
            return
        const selected = commandRows[index].command
        forceActiveFocus()
        runCommand(selected)
    }

    function submit() {
        if (inputMethodComposing)
            return
        if (commandMenu.visible && commandIndex >= 0)
            acceptChoice(commandIndex)
        else
            runCommand(text.trim())
    }

    function handleCommandKey(event) {
        if (inputMethodComposing || event.modifiers !== Qt.NoModifier)
            return false
        if (!commandMenu.visible)
            return false
        if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
            moveChoice(event.key === Qt.Key_Up ? -1 : 1)
            return true
        }
        if (event.key === Qt.Key_Escape) {
            commandMenu.close()
            return true
        }
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            submit()
            return true
        }
        return false
    }
    Keys.onPressed: event => {
        if (inputMethodComposing)
            return
        if (handleCommandKey(event)) {
            event.accepted = true
            return
        }
        if (pasteImageEnabled && !readOnly && event.matches(StandardKey.Paste)
                && typeof bridge.pasteConversationImage === "function") {
            event.accepted = bridge.pasteConversationImage()
            return
        }
        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                && event.modifiers === Qt.NoModifier) {
            submit()
            event.accepted = true
        }
    }
    onAutoscrollChanged: refreshChoices()
    Connections {
        target: root
        function onTextChanged() { root.refreshChoices() }
        function onActiveFocusChanged() {
            if (!root.activeFocus)
                commandMenu.close()
        }
    }
    Connections {
        target: root.commands
        function onChanged() {
            if (commandMenu.visible)
                root.refreshChoices(true)
        }
    }

    Popup {
        id: commandMenu
        objectName: "slashCommandMenu"
        width: root.width
        height: Math.min(320, commandList.contentHeight + 12)
        y: -height - 8
        padding: 6
        focus: false
        closePolicy: Popup.CloseOnPressOutside
        background: Rectangle {
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.windowRaised
            border.color: Theme.NCTheme.borderStrong
        }
        contentItem: ListView {
            id: commandList
            clip: true
            model: root.commandRows
            currentIndex: root.commandIndex
            ScrollBar.vertical: ScrollBar {}
            delegate: ItemDelegate {
                id: option
                required property var modelData
                required property int index
                width: commandList.width
                height: 48
                enabled: modelData.enabled
                focusPolicy: Qt.NoFocus
                highlighted: index === root.commandIndex
                opacity: enabled ? 1.0 : 0.45
                onClicked: root.acceptChoice(index)
                ToolTip.visible: hovered
                ToolTip.text: modelData.command
                contentItem: RowLayout {
                    spacing: 12
                    Label {
                        text: option.modelData.command
                        color: Theme.NCTheme.accent
                        font.bold: true
                        Layout.preferredWidth: Math.min(220, Math.max(122, root.width * 0.36))
                        elide: Text.ElideRight
                    }
                    ColumnLayout {
                        spacing: 0
                        Layout.fillWidth: true
                        Label {
                            text: option.modelData.description
                            color: Theme.NCTheme.text
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Label {
                            text: option.modelData.detail
                            color: Theme.NCTheme.textMuted
                            font.pixelSize: Theme.NCTypography.microSize
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                }
                background: Rectangle {
                    radius: Theme.NCMetrics.radiusSmall
                    color: option.highlighted || option.hovered ? Theme.NCTheme.selection : "transparent"
                }
            }
        }
    }
}
