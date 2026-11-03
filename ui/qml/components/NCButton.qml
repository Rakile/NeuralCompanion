import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Button {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property string tone: "secondary"
    property string iconText: ""
    property int iconPixelSize: Theme.NCTypography.headingSize
    property bool iconOnly: false
    property bool busy: false
    property bool compact: false

    implicitHeight: compact ? Theme.NCMetrics.controlHeightCompact : Theme.NCMetrics.controlHeight
    implicitWidth: iconOnly ? Theme.NCMetrics.iconButtonSize : Math.max(92, contentRow.implicitWidth + leftPadding + rightPadding)
    leftPadding: iconOnly ? 0 : Theme.NCMetrics.space14
    rightPadding: iconOnly ? 0 : Theme.NCMetrics.space12
    topPadding: iconOnly ? 0 : Theme.NCMetrics.space6
    bottomPadding: iconOnly ? 0 : Theme.NCMetrics.space6
    enabled: !busy
    hoverEnabled: true
    Accessible.name: text
    Accessible.description: toolTipText

    property string toolTipText: ""

    function backgroundColor() {
        if (!enabled)
            return Theme.NCTheme.surfaceRaised
        if (tone === "primary")
            return down ? Theme.NCTheme.accentStrong : hovered ? Qt.lighter(Theme.NCTheme.accentStrong, 1.12) : Theme.NCTheme.accentStrong
        if (tone === "danger")
            return down ? Qt.darker(Theme.NCTheme.errorSoft, 1.2) : hovered ? Qt.lighter(Theme.NCTheme.errorSoft, 1.12) : Theme.NCTheme.errorSoft
        if (tone === "warning")
            return down ? Qt.darker(Theme.NCTheme.warningSoft, 1.2) : hovered ? Qt.lighter(Theme.NCTheme.warningSoft, 1.12) : Theme.NCTheme.warningSoft
        if (tone === "quiet")
            return down ? Theme.NCTheme.surfacePressed : hovered ? Theme.NCTheme.surfaceRaised : "transparent"
        return down ? Theme.NCTheme.surfacePressed : hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
    }

    function foregroundColor() {
        if (root.tutorialText) return TutorialStyle.yellow
        if (!enabled)
            return Theme.NCTheme.textMuted
        if (tone === "primary")
            return Theme.NCTheme.textInverse
        if (tone === "danger")
            return Theme.NCTheme.error
        if (tone === "warning")
            return Theme.NCTheme.warning
        return Theme.NCTheme.text
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: root.backgroundColor()
        border.width: root.activeFocus ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.activeFocus ? Theme.NCTheme.focus
                                       : root.tone === "primary" ? Theme.NCTheme.accent
                                       : root.tone === "danger" ? Theme.NCTheme.error
                                       : root.tone === "warning" ? Theme.NCTheme.warning
                                       : root.tone === "quiet" ? "transparent"
                                       : Theme.NCTheme.borderStrong

        Behavior on color { ColorAnimation { duration: Theme.NCMetrics.motionFast } }
    }

    contentItem: RowLayout {
        id: contentRow
        spacing: root.iconOnly ? 0 : Theme.NCMetrics.space8

        BusyIndicator {
            Layout.preferredWidth: 16
            Layout.preferredHeight: 16
            running: root.busy
            visible: running
            palette.dark: root.foregroundColor()
        }

        Label {
            visible: root.iconText.length > 0 && !root.busy
            text: root.iconText
            color: root.foregroundColor()
            font.family: Theme.NCTypography.family
            font.pixelSize: root.iconPixelSize
            Layout.fillWidth: root.iconOnly
            Layout.alignment: Qt.AlignHCenter | Qt.AlignVCenter
            horizontalAlignment: Text.AlignHCenter
        }

        Label {
            visible: !root.iconOnly
            Layout.fillWidth: true
            text: root.busy ? qsTr("Working…") : root.text
            color: root.foregroundColor()
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.labelSize
            font.weight: Theme.NCTypography.semibold
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    NCToolTip {
        tutorialText: root.tutorialText
        visible: root.hovered && root.toolTipText.length > 0
        text: root.toolTipText
    }
}
