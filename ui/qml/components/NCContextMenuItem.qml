pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Button {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property string glyph: ""
    property string trailingText: ""
    property bool destructive: false
    property int glyphPixelSize: Theme.NCTypography.bodySize
    property real glyphColumnWidth: 18
    property string glyphFontFamily: Theme.NCTypography.family

    implicitWidth: 276
    implicitHeight: Theme.NCMetrics.controlHeight
    leftPadding: Theme.NCMetrics.space12
    rightPadding: Theme.NCMetrics.space12
    hoverEnabled: true

    background: Rectangle {
        radius: Theme.NCMetrics.radiusSmall
        color: root.down ? Theme.NCTheme.surfacePressed
              : root.hovered ? Theme.NCTheme.surfaceSelected
              : "transparent"
        border.width: root.activeFocus ? Theme.NCMetrics.focusWidth : 0
        border.color: Theme.NCTheme.focus
    }

    contentItem: RowLayout {
        spacing: Theme.NCMetrics.space10

        Label {
            Layout.preferredWidth: root.glyphColumnWidth
            text: root.glyph
            color: root.tutorialText ? TutorialStyle.yellow : root.destructive ? Theme.NCTheme.error : Theme.NCTheme.accent
            font.family: root.glyphFontFamily
            font.pixelSize: root.glyphPixelSize
            horizontalAlignment: Text.AlignHCenter
        }

        Label {
            Layout.fillWidth: true
            text: root.text
            color: root.tutorialText ? TutorialStyle.yellow : !root.enabled ? Theme.NCTheme.textMuted
                  : root.destructive ? Theme.NCTheme.error
                  : Theme.NCTheme.text
            font.pixelSize: Theme.NCTypography.labelSize
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }

        Label {
            visible: Boolean(root.trailingText)
            text: root.trailingText
            color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.textMuted
            font.pixelSize: Theme.NCTypography.microSize
        }
    }
}
