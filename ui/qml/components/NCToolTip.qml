import QtQuick
import QtQuick.Controls
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

ToolTip {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property int maximumWidth: 420

    readonly property var ownerWindow: parent ? parent.Window.window : null
    readonly property real widthLimit: ownerWindow ? Math.max(80, ownerWindow.width - 16) : maximumWidth
    readonly property real heightLimit: ownerWindow ? Math.max(40, ownerWindow.height - 16) : 800
    readonly property bool hovered: tooltipHover.hovered
    closePolicy: Popup.CloseOnEscape

    function scrollPage(direction) {
        const viewport = tooltipScroll.contentItem
        if (!viewport || viewport.contentY === undefined) return
        const maximum = Math.max(0, viewport.contentHeight - viewport.height)
        viewport.contentY = Math.max(0, Math.min(maximum,
            viewport.contentY + direction * viewport.height * 0.85))
    }

    delay: 550
    timeout: 8000
    leftPadding: Theme.NCMetrics.space14
    rightPadding: Theme.NCMetrics.space14
    topPadding: Theme.NCMetrics.space10
    bottomPadding: Theme.NCMetrics.space10
    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.captionSize
    font.weight: Theme.NCTypography.medium
    implicitWidth: Math.min(
                       Math.min(maximumWidth, widthLimit),
                       Math.max(96, textMetrics.advanceWidth
                                + leftPadding + rightPadding))
    implicitHeight: Math.min(heightLimit, Math.max(
                        Theme.NCMetrics.controlHeightCompact,
                        tooltipLabel.implicitHeight + topPadding + bottomPadding))

    TextMetrics {
        id: textMetrics
        font: root.font
        text: root.text
    }

    contentItem: ScrollView {
        id: tooltipScroll
        HoverHandler { id: tooltipHover }
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: tooltipLabel.implicitHeight > availableHeight ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
        Label {
            id: tooltipLabel
            width: Math.max(1, root.availableWidth - 12)
            text: root.text
            textFormat: Text.PlainText
            color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.text
            font: root.font
            wrapMode: Text.Wrap
            verticalAlignment: Text.AlignVCenter
        }
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: Theme.NCTheme.windowRaised
        border.width: Theme.NCMetrics.borderWidth
        border.color: Theme.NCTheme.accent

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.margins: Theme.NCMetrics.space6
            width: 2
            radius: 1
            color: Theme.NCTheme.accent
        }
    }
}
