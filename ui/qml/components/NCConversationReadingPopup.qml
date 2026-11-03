pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

// The same persisted reading and card preferences used by Main chat.
Popup {
    id: root
    required property var bridge
    width: Math.min(470, parent ? parent.width - 24 : 470)
    height: Math.min(implicitHeight, parent ? parent.height - 24 : implicitHeight)
    padding: 16
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    function preference(key, fallback) {
        return bridge && bridge[key] !== undefined ? bridge[key] : fallback
    }
    function openFor(control) {
        const point = control.mapToItem(parent, control.width - width, control.height + 4)
        x = Math.max(8, Math.min(point.x, parent.width - width - 8))
        y = Math.max(8, Math.min(point.y, parent.height - height - 8))
        open()
    }
    background: Rectangle {
        radius: Theme.NCMetrics.radiusLarge
        color: Theme.NCTheme.windowRaised
        border.color: Theme.NCTheme.borderStrong
    }
    contentItem: ScrollView {
        implicitHeight: options.implicitHeight
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            id: options
            width: parent.width
            spacing: 10
            Label { text: qsTr("TEXT AND SPEECH"); color: Theme.NCTheme.accent }
            RowLayout {
                Layout.fillWidth: true
                Label { Layout.fillWidth: true; text: qsTr("Font size"); color: Theme.NCTheme.text }
                NCComboBox {
                    toolTipText: qsTr("Font size in pixels for conversation messages. Changes the reading view without changing stored messages or model context.")

                    objectName: "roomConversationFontSize"
                    model: [8, 10, 12, 14, 16, 18, 20]
                    currentIndex: Math.max(0, model.indexOf(Number(root.preference("conversationFontSize", 12))))
                    onActivated: root.bridge.setConversationFontSize(Number(model[currentIndex]))
                }
            }
            NCSwitch {
                toolTipText: qsTr("Show or hide each conversation message's timestamp. The saved conversation data is unchanged.")

                objectName: "roomConversationTimestamps"
                text: qsTr("Timestamps")
                checked: Boolean(root.preference("conversationTimestampsEnabled", true))
                onClicked: root.bridge.toggleConversationTimestamps()
            }
            NCSwitch {
                toolTipText: qsTr("Show or hide borders around conversation messages. Other reading preferences remain in effect.")

                objectName: "roomConversationBorders"
                text: qsTr("Message borders")
                checked: Boolean(root.preference("conversationMessageBordersEnabled", true))
                onClicked: root.bridge.toggleConversationMessageBorders()
            }
            RowLayout {
                Layout.fillWidth: true
                Label { Layout.fillWidth: true; text: qsTr("Spoken text"); color: Theme.NCTheme.text }
                NCComboBox {
                    toolTipText: qsTr("Choose which speech units NC highlights while a reply is spoken. Highlighting follows playback and does not change speech generation.")

                    objectName: "roomConversationSpeechMode"
                    property var modes: ["off", "word", "reading"]
                    model: [qsTr("Off"), qsTr("Word spotlight"), qsTr("Reading current")]
                    currentIndex: Math.max(0, modes.indexOf(String(root.preference("conversationSpeechHighlightMode", "off"))))
                    onActivated: root.bridge.setConversationSpeechHighlightMode(modes[currentIndex])
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Label { Layout.fillWidth: true; text: qsTr("Highlight appearance"); color: Theme.NCTheme.text }
                NCComboBox {
                    toolTipText: qsTr("Choose the visual treatment used for the current spoken text. This affects highlighting appearance, not playback order or speed.")

                    objectName: "roomConversationSpeechStyle"
                    property var styles: ["classic", "rounded", "glow", "flow"]
                    model: [qsTr("Current"), qsTr("Rounded focus"), qsTr("Aura glow"), qsTr("Kinetic flow")]
                    currentIndex: Math.max(0, styles.indexOf(String(root.preference("conversationSpeechHighlightStyle", "classic"))))
                    onActivated: root.bridge.setConversationSpeechHighlightStyle(styles[currentIndex])
                }
            }
            Label { text: qsTr("CARD SIZE"); color: Theme.NCTheme.accent }
            Repeater {
                model: [
                    {label: qsTr("Response width"), key: "conversationResponseWidthRatio", fallback: 0.68, minimum: 0.35, maximum: 0.96, user: false, height: false},
                    {label: qsTr("Response minimum height"), key: "conversationResponseMinHeight", fallback: 140, minimum: 96, maximum: 420, user: false, height: true},
                    {label: qsTr("User width (0 = automatic)"), key: "conversationUserWidthRatio", fallback: 0, minimum: 0, maximum: 0.92, user: true, height: false},
                    {label: qsTr("User minimum height"), key: "conversationUserMinHeight", fallback: 96, minimum: 96, maximum: 420, user: true, height: true}]
                delegate: ColumnLayout {
                    id: sizeOption
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 2
                    Label { text: sizeOption.modelData.label; color: Theme.NCTheme.text }
                    Slider {
                        NCHelp { target: settingHelpTarget5; text: qsTr("Adjust the %1 of conversation message cards. This changes reading layout only.").arg(String(sizeOption.modelData.label || sizeOption.modelData.key)) }

                        id: settingHelpTarget5

                        objectName: "roomCardSize_" + sizeOption.modelData.key
                        Layout.fillWidth: true
                        from: sizeOption.modelData.minimum; to: sizeOption.modelData.maximum
                        value: Number(root.preference(sizeOption.modelData.key, sizeOption.modelData.fallback))
                        onMoved: {
                            const user = sizeOption.modelData.user
                            const ratio = sizeOption.modelData.height
                                ? Number(root.preference(user ? "conversationUserWidthRatio" : "conversationResponseWidthRatio", user ? 0 : 0.68)) : value
                            const minimumHeight = sizeOption.modelData.height ? Math.round(value)
                                : Number(root.preference(user ? "conversationUserMinHeight" : "conversationResponseMinHeight", user ? 96 : 140))
                            if (user) root.bridge.setConversationUserFrameSize(ratio, minimumHeight)
                            else root.bridge.setConversationResponseFrameSize(ratio, minimumHeight)
                        }
                    }
                }
            }
        }
    }
}
