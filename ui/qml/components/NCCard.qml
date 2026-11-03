import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Rectangle {
    id: root
    property bool tutorialText: TutorialStyle.inTutorial(root.parent)

    property string title: ""
    property string description: ""
    property bool interactive: false
    property bool selected: false
    property bool elevated: false
    property bool flat: false
    property bool fullWidthHeader: false
    property bool collapsible: false
    property bool collapsed: false
    default property alias contentItem: content.data
    property alias headerAccessory: headerAccessory.data
    property int contentSpacing: Theme.NCMetrics.space12
    signal clicked()
    signal collapseRequested(bool collapse)

    function requestCollapse() {
        if (collapsible)
            collapseRequested(!collapsed)
    }

    implicitWidth: 320
    implicitHeight: flat
                    ? layout.implicitHeight
                    : Math.max(90, layout.implicitHeight + Theme.NCMetrics.space32)
    radius: Theme.NCMetrics.radiusLarge
    color: flat ? "transparent"
                    : selected ? Theme.NCTheme.surfaceSelected
                    : mouseArea.containsMouse && interactive ? Theme.NCTheme.surfaceRaised
                    : elevated ? Theme.NCTheme.windowRaised : Theme.NCTheme.surface
    border.width: flat ? 0
                       : selected || activeFocus ? Theme.NCMetrics.focusWidth
                                                 : Theme.NCMetrics.borderWidth
    border.color: activeFocus ? Theme.NCTheme.focus
                              : selected ? Theme.NCTheme.accent
                              : Theme.NCTheme.border
    focus: false
    activeFocusOnTab: interactive
    Accessible.role: interactive ? Accessible.Button : Accessible.Pane
    Accessible.name: title
    Accessible.description: description

    Behavior on color {
        ColorAnimation { duration: Theme.NCMetrics.motionFast }
    }

    ColumnLayout {
        id: layout
        anchors.fill: parent
        anchors.margins: root.flat ? 0 : Theme.NCMetrics.space16
        spacing: root.contentSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.NCMetrics.space12
            visible: root.title.length > 0 || headerAccessory.children.length > 0 || root.collapsible

            ColumnLayout {
                visible: !root.fullWidthHeader
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space4

                Label {
                    Layout.fillWidth: true
                    text: root.title
                    color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.text
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.headingSize
                    font.weight: Theme.NCTypography.semibold
                    wrapMode: Text.Wrap
                    visible: text.length > 0
                }

                Label {
                    Layout.fillWidth: true
                    text: root.description
                    color: root.tutorialText ? TutorialStyle.yellow : Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                    visible: text.length > 0
                }
            }

            RowLayout {
                id: headerAccessory
                Layout.fillWidth: root.fullWidthHeader
                spacing: Theme.NCMetrics.space8
            }

            NCButton {
                objectName: "cardCollapseButton"
                visible: root.collapsible
                compact: true
                text: root.collapsed ? qsTr("Show") : qsTr("Hide")
                Accessible.name: text + " " + root.title
                onClicked: root.requestCollapse()
            }
        }

        ColumnLayout {
            id: content
            objectName: "cardContents"
            visible: !root.collapsible || !root.collapsed
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: root.contentSpacing
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        enabled: root.interactive
        hoverEnabled: true
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: {
            root.forceActiveFocus()
            root.clicked()
        }
    }

    Keys.onSpacePressed: if (interactive) root.clicked()
    Keys.onReturnPressed: if (interactive) root.clicked()
}
