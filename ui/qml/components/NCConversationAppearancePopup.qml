pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../theme" as Theme

Popup {
    id: root

    required property var bridge

    objectName: "conversationAppearancePopup"
    width: Math.min(480, parent ? parent.width - Theme.NCMetrics.space24 : 480)
    height: Math.min(implicitHeight, parent ? parent.height - Theme.NCMetrics.space16 : implicitHeight)
    padding: Theme.NCMetrics.space16
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    z: 430

    property var styleOptions: [
        { "id": "original", "label": qsTr("Original"),
          "description": qsTr("Current clean conversation") },
        { "id": "glass", "label": qsTr("Floating glass"),
          "description": qsTr("Soft lift and cyan edge") },
        { "id": "recessed", "label": qsTr("Wide recessed"),
          "description": qsTr("Inset edge with full width") },
        { "id": "vignette", "label": qsTr("Ambient vignette"),
          "description": qsTr("Focused cinematic fade") }
    ]

    function openFor(control) {
        if (!control || !parent)
            return
        const mapped = control.mapToItem(parent, control.width - width,
                                         control.height + Theme.NCMetrics.space4)
        x = Math.max(Theme.NCMetrics.space8,
                     Math.min(mapped.x, parent.width - width - Theme.NCMetrics.space8))
        y = Math.max(Theme.NCMetrics.space8,
                     Math.min(mapped.y, parent.height - implicitHeight - Theme.NCMetrics.space8))
        open()
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusLarge
        color: Theme.NCTheme.windowRaised
        border.width: Theme.NCMetrics.focusWidth
        border.color: Theme.NCTheme.borderStrong
    }

    contentItem: ScrollView {
        objectName: "conversationAppearanceScroll"
        implicitHeight: appearanceOptions.implicitHeight
        contentWidth: availableWidth
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
        id: appearanceOptions
        width: parent.width
        spacing: Theme.NCMetrics.space12

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space8

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space2
                Label {
                    Layout.fillWidth: true
                    text: qsTr("CONVERSATION APPEARANCE")
                    color: Theme.NCTheme.accent
                    font.pixelSize: Theme.NCTypography.microSize
                    font.weight: Theme.NCTypography.bold
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Choose a frame and optional background for the chat area.")
                    color: Theme.NCTheme.textSecondary
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
            }

            NCIconButton {
                glyph: "×"
                toolTipText: qsTr("Close conversation appearance")
                onClicked: root.close()
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: Theme.NCMetrics.space8
            rowSpacing: Theme.NCMetrics.space8

            Repeater {
                model: root.styleOptions

                delegate: Button {
                    id: appearanceChoice
                    required property var modelData
                    readonly property bool selected:
                        root.bridge.conversationCanvasStyle === String(modelData.id)
                    Layout.fillWidth: true
                    Layout.preferredHeight: 100
                    hoverEnabled: true
                    Accessible.name: String(modelData.label)
                    Accessible.description: String(modelData.description)
                    onClicked: root.bridge.setConversationCanvasStyle(
                                   String(appearanceChoice.modelData.id))

                    background: Rectangle {
                        radius: Theme.NCMetrics.radiusMedium
                        color: appearanceChoice.selected
                               ? Theme.NCTheme.surfaceSelected
                               : appearanceChoice.hovered
                                 ? Theme.NCTheme.surfaceRaised
                                 : Theme.NCTheme.surface
                        border.width: appearanceChoice.selected || appearanceChoice.activeFocus
                                      ? Theme.NCMetrics.focusWidth
                                      : Theme.NCMetrics.borderWidth
                        border.color: appearanceChoice.selected || appearanceChoice.activeFocus
                                      ? Theme.NCTheme.accent : Theme.NCTheme.border
                    }

                    contentItem: ColumnLayout {
                        spacing: Theme.NCMetrics.space6

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 40
                            radius: Theme.NCMetrics.radiusSmall
                            color: String(appearanceChoice.modelData.id) === "original"
                                   ? Theme.NCTheme.window
                                   : String(appearanceChoice.modelData.id) === "recessed"
                                     ? "#030914" : Theme.NCTheme.windowRaised
                            border.width: String(appearanceChoice.modelData.id) === "original"
                                          ? 0 : Theme.NCMetrics.borderWidth
                            border.color: String(appearanceChoice.modelData.id) === "vignette"
                                          ? Theme.NCTheme.withAlpha(Theme.NCTheme.accent, 0.28)
                                          : Theme.NCTheme.withAlpha(Theme.NCTheme.accent, 0.58)

                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: String(appearanceChoice.modelData.id) === "recessed" ? 5 : 8
                                radius: Theme.NCMetrics.radiusSmall
                                color: "transparent"
                                border.width: String(appearanceChoice.modelData.id) === "original" ? 0 : 1
                                border.color: Theme.NCTheme.withAlpha(Theme.NCTheme.borderStrong, 0.7)
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: String(appearanceChoice.modelData.label)
                            color: Theme.NCTheme.text
                            font.pixelSize: Theme.NCTypography.labelSize
                            font.weight: Theme.NCTypography.semibold
                            elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true
                            text: String(appearanceChoice.modelData.description)
                            color: Theme.NCTheme.textMuted
                            font.pixelSize: Theme.NCTypography.microSize
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: cardTransparencyRow.implicitHeight + Theme.NCMetrics.space16
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.surface
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.border

            RowLayout {
                id: cardTransparencyRow
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space8
                spacing: Theme.NCMetrics.space12

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space2
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Transparent response cards")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.labelSize
                        font.weight: Theme.NCTypography.semibold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Show the background through assistant and user cards.")
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.microSize
                        wrapMode: Text.Wrap
                    }
                }

                NCSwitch {
                    toolTipText: qsTr("Make conversation message-card backgrounds transparent while retaining their text and other configured styling. This is a display preference and does not affect saved messages.")

                    objectName: "conversationTransparentCardsSwitch"
                    text: checked ? qsTr("On") : qsTr("Off")
                    checked: root.bridge.conversationTransparentMessageCardsEnabled
                    onClicked: root.bridge.setConversationTransparentMessageCards(checked)
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.NCMetrics.borderWidth
            color: Theme.NCTheme.borderSubtle
        }

        Label {
            Layout.fillWidth: true
            text: qsTr("MESSAGE TEXT")
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.microSize
            font.weight: Theme.NCTypography.bold
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: messageTextOptions.implicitHeight + Theme.NCMetrics.space16
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.surface
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.border

            ColumnLayout {
                id: messageTextOptions
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space8
                spacing: Theme.NCMetrics.space8

                Label {
                    Layout.fillWidth: true
                    text: qsTr("Assistant and user message preview")
                    color: root.bridge.conversationMessageTextColor.length > 0
                           ? root.bridge.conversationMessageTextColor
                           : Theme.NCTheme.text
                    font.family: root.bridge.conversationMessageFontFamily.length > 0
                                 ? root.bridge.conversationMessageFontFamily
                                 : Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.bodySize
                    elide: Text.ElideRight
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8

                    Label {
                        Layout.fillWidth: true
                        text: root.bridge.conversationMessageFontFamily.length > 0
                              ? root.bridge.conversationMessageFontFamily
                              : qsTr("Theme default font")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.labelSize
                        elide: Text.ElideRight
                    }
                    NCButton {
                        text: qsTr("OpenDyslexic")
                        compact: true
                        tone: root.bridge.conversationMessageFontFamily === "OpenDyslexic"
                              ? "primary" : "quiet"
                        onClicked: root.bridge.setConversationMessageFontFamily("OpenDyslexic")
                    }
                    NCButton {
                        objectName: "conversationChooseMessageFont"
                        text: qsTr("Choose font")
                        compact: true
                        onClicked: {
                            messageFontDialog.selectedFont = Qt.font({
                                "family": root.bridge.conversationMessageFontFamily.length > 0
                                          ? root.bridge.conversationMessageFontFamily
                                          : Theme.NCTypography.family,
                                "pixelSize": Theme.NCTypography.bodySize
                            })
                            messageFontDialog.open()
                        }
                    }
                    NCButton {
                        text: qsTr("Theme default")
                        compact: true
                        tone: "quiet"
                        enabled: root.bridge.conversationMessageFontFamily.length > 0
                        onClicked: root.bridge.setConversationMessageFontFamily("")
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8

                    Rectangle {
                        Layout.preferredWidth: 30
                        Layout.preferredHeight: 30
                        radius: Theme.NCMetrics.radiusSmall
                        color: root.bridge.conversationMessageTextColor.length > 0
                               ? root.bridge.conversationMessageTextColor
                               : Theme.NCTheme.text
                        border.width: Theme.NCMetrics.borderWidth
                        border.color: Theme.NCTheme.borderStrong
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.bridge.conversationMessageTextColor.length > 0
                              ? root.bridge.conversationMessageTextColor
                              : qsTr("Theme default color")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.labelSize
                    }
                    NCButton {
                        objectName: "conversationChooseMessageTextColor"
                        text: qsTr("Choose color")
                        compact: true
                        onClicked: {
                            messageTextColorDialog.selectedColor =
                                root.bridge.conversationMessageTextColor.length > 0
                                ? root.bridge.conversationMessageTextColor
                                : Theme.NCTheme.text
                            messageTextColorDialog.open()
                        }
                    }
                    NCButton {
                        text: qsTr("Theme default")
                        compact: true
                        tone: "quiet"
                        enabled: root.bridge.conversationMessageTextColor.length > 0
                        onClicked: root.bridge.setConversationMessageTextColor("")
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space2
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Bionic reading")
                            color: Theme.NCTheme.text
                            font.pixelSize: Theme.NCTypography.labelSize
                            font.weight: Theme.NCTypography.semibold
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Bold the first half of each word to guide scanning.")
                            color: Theme.NCTheme.textMuted
                            font.pixelSize: Theme.NCTypography.microSize
                            wrapMode: Text.Wrap
                        }
                    }
                    NCSwitch {
                        toolTipText: qsTr("Emphasize the beginnings of words to assist visual scanning. This changes message rendering; it does not alter the text sent to the model or speech engine.")

                        objectName: "conversationBionicReadingSwitch"
                        text: checked ? qsTr("On") : qsTr("Off")
                        checked: root.bridge.conversationBionicReadingEnabled
                        onClicked: root.bridge.setConversationBionicReadingEnabled(checked)
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.NCMetrics.borderWidth
            color: Theme.NCTheme.borderSubtle
        }

        Label {
            Layout.fillWidth: true
            text: qsTr("BACKGROUND")
            color: Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.microSize
            font.weight: Theme.NCTypography.bold
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space8

            Rectangle {
                Layout.preferredWidth: 54
                Layout.preferredHeight: 38
                radius: Theme.NCMetrics.radiusSmall
                color: Theme.NCTheme.window
                border.width: Theme.NCMetrics.borderWidth
                border.color: Theme.NCTheme.border
                clip: true

                Image {
                    anchors.fill: parent
                    source: root.bridge.conversationBackgroundUrl
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    visible: String(source).length > 0
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Label {
                    Layout.fillWidth: true
                    text: root.bridge.conversationBackgroundName.length > 0
                          ? root.bridge.conversationBackgroundName
                          : qsTr("No custom image")
                    color: Theme.NCTheme.text
                    font.pixelSize: Theme.NCTypography.labelSize
                    elide: Text.ElideMiddle
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("The original file stays unchanged.")
                    color: Theme.NCTheme.textMuted
                    font.pixelSize: Theme.NCTypography.microSize
                }
            }

            NCButton {
                text: qsTr("Choose image")
                compact: true
                onClicked: backgroundFileDialog.open()
            }
            NCButton {
                text: qsTr("Clear")
                compact: true
                tone: "quiet"
                enabled: root.bridge.conversationBackgroundName.length > 0
                onClicked: root.bridge.clearConversationBackgroundImage()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            NCButton {
                objectName: "conversationRestoreAppearance"
                text: qsTr("Restore original")
                iconText: "↺"
                compact: true
                enabled: root.bridge.conversationCanvasStyle !== "original"
                         || root.bridge.conversationBackgroundName.length > 0
                         || root.bridge.conversationTransparentMessageCardsEnabled
                         || root.bridge.conversationMessageTextColor.length > 0
                         || root.bridge.conversationMessageFontFamily.length > 0
                         || root.bridge.conversationBionicReadingEnabled
                onClicked: root.bridge.restoreConversationAppearance()
            }
        }
    }
    }

    FileDialog {
        id: backgroundFileDialog
        title: qsTr("Choose conversation background")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")]
        onAccepted: root.bridge.setConversationBackgroundImage(selectedFile.toString())
    }

    FontDialog {
        id: messageFontDialog
        objectName: "conversationMessageFontDialog"
        title: qsTr("Choose conversation message font")
        onAccepted: root.bridge.setConversationMessageFontFamily(selectedFont.family)
    }

    ColorDialog {
        id: messageTextColorDialog
        objectName: "conversationMessageTextColorDialog"
        title: qsTr("Choose conversation message text color")
        onAccepted: root.bridge.setConversationMessageTextColor(selectedColor.toString())
    }
}
