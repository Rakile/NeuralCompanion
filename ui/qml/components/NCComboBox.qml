pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

ComboBox {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property string toolTipText: ""
    property string helpDescription: toolTipText

    property string label: ""

    implicitHeight: Theme.NCMetrics.controlHeight
    leftPadding: Theme.NCMetrics.space12
    rightPadding: Theme.NCMetrics.space32
    hoverEnabled: true
    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.bodySize
    Accessible.description: helpDescription
    Accessible.name: label

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: root.down ? Theme.NCTheme.surfacePressed
                         : root.hovered ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.windowRaised
        border.width: root.activeFocus || root.popup.visible ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
        border.color: root.activeFocus || root.popup.visible ? Theme.NCTheme.focus : Theme.NCTheme.border
    }

    contentItem: Label {
        text: root.displayText
        color: root.tutorialText ? TutorialStyle.yellow : root.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Label {
        x: root.width - width - Theme.NCMetrics.space12
        anchors.verticalCenter: parent.verticalCenter
        text: root.popup.visible ? "⌃" : "⌄"
        color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.textSecondary
        font.pixelSize: Theme.NCTypography.headingSize
    }

    delegate: ItemDelegate {
        id: optionDelegate
        required property int index
        width: root.width
        height: Theme.NCMetrics.controlHeight
        highlighted: root.highlightedIndex === index
        contentItem: Label {
            text: root.textAt(optionDelegate.index)
            color: root.tutorialText ? TutorialStyle.yellow : optionDelegate.highlighted ? Theme.NCTheme.text : Theme.NCTheme.textSecondary
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.bodySize
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            color: optionDelegate.highlighted ? Theme.NCTheme.selection : "transparent"
            radius: Theme.NCMetrics.radiusSmall
        }
    }

    popup: Popup {
        y: root.height + Theme.NCMetrics.space4
        width: root.width
        implicitHeight: Math.min(contentItem.implicitHeight + Theme.NCMetrics.space8, 320)
        padding: Theme.NCMetrics.space4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        background: Rectangle {
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.surface
            border.color: Theme.NCTheme.borderStrong
            border.width: Theme.NCMetrics.borderWidth
        }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }
    }
    NCHelp { target: root; text: root.toolTipText }
}
