import QtQuick
import QtQuick.Controls
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Button {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property string glyph: "⋯"
    property string toolTipText: ""
    property bool selected: false
    // An interaction overlay may own pointer events while this button paints.
    property bool interactionHovered: hovered
    property int glyphPixelSize: Theme.NCTypography.headingSize
    property string glyphFontFamily: Theme.NCTypography.family

    implicitWidth: Theme.NCMetrics.iconButtonSize
    implicitHeight: Theme.NCMetrics.iconButtonSize
    padding: 0
    hoverEnabled: true
    Accessible.name: toolTipText

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: root.down ? Theme.NCTheme.surfacePressed
                         : root.selected ? Theme.NCTheme.selection
                         : root.interactionHovered ? Theme.NCTheme.surfaceRaised : "transparent"
        border.width: root.activeFocus ? Theme.NCMetrics.focusWidth
                                      : root.selected ? Theme.NCMetrics.borderWidth : 0
        border.color: root.activeFocus ? Theme.NCTheme.focus : Theme.NCTheme.accent
    }

    contentItem: Label {
        text: root.glyph
        color: root.tutorialText ? TutorialStyle.yellow : root.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
        font.family: root.glyphFontFamily
        font.pixelSize: root.glyphPixelSize
        font.weight: Theme.NCTypography.semibold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    NCToolTip {
        objectName: "iconButtonToolTip"
        visible: root.interactionHovered && root.toolTipText.length > 0
        text: root.toolTipText
        delay: 500
    }
}
