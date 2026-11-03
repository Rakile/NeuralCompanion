pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Popup {
    id: root
    property bool tutorialText: true
    objectName: "contextualTutorialMenu"
    required property var bridge
    property var context: ({})
    readonly property var guides: typeof bridge.tutorialsForContext === "function"
                                 ? bridge.tutorialsForContext(context) : []
    readonly property var menuGuides: guides.slice(0, 12)
    parent: Overlay.overlay
    width: 360
    padding: Theme.NCMetrics.space12
    modal: false
    dim: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function openFor(control, route, fromContext) {
        if (fromContext !== false && !TutorialStyle.showContext(root.bridge)) return
        context = route || ({})
        if (!control || !parent) return
        const point = control.mapToItem(parent, 0, control.height)
        x = Math.max(0, Math.min(point.x, parent.width - width))
        y = Math.max(0, Math.min(point.y, parent.height - implicitHeight))
        open()
        Qt.callLater(function() {
            if (root.visible && root.parent)
                root.y = Math.max(0, Math.min(root.y, root.parent.height - root.height))
        })
    }

    background: Rectangle {
        radius: Theme.NCMetrics.radiusMedium
        color: Theme.NCTheme.windowRaised
        border.color: Theme.NCTheme.borderStrong
    }
    contentItem: ColumnLayout {
        spacing: Theme.NCMetrics.space8
        Label { text: qsTr("Tutorials for this area"); color: "#FFE066"; font.bold: true }
        Label {
            visible: root.guides.length === 0
            text: qsTr("No guide is available for this area yet.")
            color: "#FFE066"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }
        ListView {
            id: guideList
            objectName: "contextualTutorialList"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(420, contentHeight)
            clip: true
            model: root.menuGuides
            delegate: ItemDelegate {
                id: guideEntry
                required property var modelData
                width: guideList.width
                implicitHeight: Math.max(48, guideLabel.implicitHeight + 16)
                objectName: "contextualTutorial_" + String(modelData.id)
                text: String(modelData.display_title || modelData.title)
                Accessible.description: String(modelData.description || "")
                contentItem: Label {
                    id: guideLabel
                    text: guideEntry.text
                    color: "#FFE066"
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.bodySize
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
                background: Rectangle {
                    radius: Theme.NCMetrics.radiusSmall
                    color: guideEntry.hovered || guideEntry.down ? Theme.NCTheme.surfaceSelected : "transparent"
                    border.width: guideEntry.activeFocus ? Theme.NCMetrics.focusWidth : 0
                    border.color: Theme.NCTheme.focus
                }
                onClicked: {
                    root.close()
                    root.bridge.startTutorial(String(modelData.id))
                }
            }
            ScrollBar.vertical: ScrollBar { }
        }
        NCButton { tutorialText: true
            objectName: "contextualTutorialBrowse"
            Layout.fillWidth: true
            visible: root.guides.length > root.menuGuides.length
            text: qsTr("Browse all %1 guides for this area").arg(root.guides.length)
            onClicked: {
                root.close()
                root.bridge.openTutorialBrowser(root.context)
            }
        }
    }
}
