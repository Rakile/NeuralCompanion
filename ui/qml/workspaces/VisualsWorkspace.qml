import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import "../components"
import "../theme" as Theme

Rectangle {
    id: root

    required property var bridge
    property string previewKind: "visualReply"
    objectName: isMusetalk ? "avatarPreviewWorkspace" : "visualReplyPreviewWorkspace"
    readonly property bool isMusetalk: previewKind === "musetalk"
    property bool avatarOnly: false
    readonly property bool creatorPreview: isMusetalk && Boolean(bridge.musetalkState.creatorPreview)
    // A dock move can briefly overlap old/new instances during QML teardown.
    readonly property string previewViewId: "workspace-" + Math.random().toString(36).slice(2)
    readonly property bool previewActive: visible && (!Window.window || Window.window.visibility !== Window.Minimized)

    function updatePreviewVisibility(active) {
        if (isMusetalk)
            bridge.setMusetalkPreviewVisible(previewViewId, active)
        else
            bridge.setVisualReplyPreviewVisible(previewViewId, active)
    }

    function openVisualReplyImagePicker() {
        awaitingVisualReplyStorage = bridge.prepareVisualReplyStorage()
    }
    property bool awaitingVisualReplyStorage: false
    Connections {
        target: root.bridge
        function onVisualReplyStorageReady(storageUrl) {
            if (root.awaitingVisualReplyStorage && !root.isMusetalk && root.previewActive) {
                visualReplyImageDialog.currentFolder = storageUrl
                visualReplyImageDialog.open()
            }
            root.awaitingVisualReplyStorage = false
        }
    }
    onPreviewActiveChanged: updatePreviewVisibility(previewActive)
    Component.onCompleted: updatePreviewVisibility(previewActive)
    Component.onDestruction: updatePreviewVisibility(false)

    signal floatVisualReplyRequested()
    signal floatMusetalkPreviewRequested()

    color: Theme.NCTheme.window
    radius: avatarOnly ? 0 : Theme.NCMetrics.radiusLarge
    border.width: avatarOnly ? 0 : Theme.NCMetrics.borderWidth
    border.color: Theme.NCTheme.borderSubtle

    GridLayout {
        visible: !root.avatarOnly
        anchors.fill: parent
        columns: 1
        columnSpacing: Theme.NCMetrics.space12
        rowSpacing: Theme.NCMetrics.space12

        NCCard {
            visible: !root.isMusetalk
            Layout.fillWidth: true
            Layout.fillHeight: true
            title: qsTr("Visual Reply")

            headerAccessory: Item {}

            Item {
                id: visualReplyToolbarContainer
                Layout.fillWidth: true
                Layout.preferredHeight: visualReplyToolbar.implicitHeight
                clip: true
                property bool widthAllowsExpandedTools: false
                readonly property real expandedToolsWidth:
                    visualReplyStatusChip.implicitWidth
                    + visualReplyPreviousButton.implicitWidth
                    + visualReplyLoadButton.implicitWidth
                    + visualReplyNextButton.implicitWidth
                    + visualReplyStoryImageButton.implicitWidth
                    + visualReplyUseStyleButton.implicitWidth
                    + visualReplyCaptionButton.implicitWidth
                    + visualReplyDeleteButton.implicitWidth
                    + visualReplyToolsButton.implicitWidth
                    + floatVisualReplyButton.implicitWidth
                    + visualReplyClearButton.implicitWidth
                    + visualReplyDeleteAllButton.implicitWidth
                    + Theme.NCMetrics.space8 * 11
                readonly property bool showExpandedTools:
                    root.bridge.visualReplyToolbarExpanded
                    && widthAllowsExpandedTools
                onWidthChanged: visualReplyResizeSettleTimer.restart()
                onExpandedToolsWidthChanged: visualReplyResizeSettleTimer.restart()
                Component.onCompleted: widthAllowsExpandedTools =
                                           width >= expandedToolsWidth

                Timer {
                    id: visualReplyResizeSettleTimer
                    interval: 110
                    repeat: false
                    onTriggered: visualReplyToolbarContainer.widthAllowsExpandedTools =
                                     visualReplyToolbarContainer.width
                                     >= visualReplyToolbarContainer.expandedToolsWidth
                }

                RowLayout {
                    id: visualReplyToolbar
                    objectName: "visualReplyToolbar"
                    anchors.verticalCenter: parent.verticalCenter
                    x: visualReplyToolbarContainer.showExpandedTools
                       ? Math.round((parent.width - width) / 2)
                       : parent.width - width
                    spacing: Theme.NCMetrics.space8

                NCStatusChip {
                    id: visualReplyStatusChip
                    text: String(root.bridge.visualReplyState.status_text || root.bridge.visualReplyState.status || qsTr("Idle"))
                    status: String(root.bridge.visualReplyState.status || "disconnected")
                }
                NCButton {
                    id: visualReplyPreviousButton
                    objectName: "visualReplyPreviousButton"
                    visible: visualReplyToolbarContainer.showExpandedTools
                    text: qsTr("Previous")
                    compact: true
                    tone: "secondary"
                    enabled: Number(root.bridge.visualReplyState.storage_count || 0) > 0
                    onClicked: root.bridge.navigateVisualReply(-1)
                }
                NCButton {
                    id: visualReplyLoadButton
                    objectName: "visualReplyLoadButton"
                    visible: visualReplyToolbarContainer.showExpandedTools
                    text: qsTr("Load Image")
                    compact: true
                    tone: "secondary"
                    onClicked: root.openVisualReplyImagePicker()
                }
                NCButton {
                    id: visualReplyNextButton
                    objectName: "visualReplyNextButton"
                    visible: visualReplyToolbarContainer.showExpandedTools
                    text: qsTr("Next")
                    compact: true
                    tone: "secondary"
                    enabled: Number(root.bridge.visualReplyState.storage_count || 0) > 0
                    onClicked: root.bridge.navigateVisualReply(1)
                }
                NCButton {
                    id: visualReplyStoryImageButton
                    objectName: "visualReplyStoryImageButton"
                    visible: visualReplyToolbarContainer.showExpandedTools
                    text: qsTr("Load Current Story Image")
                    compact: true
                    tone: "secondary"
                    onClicked: root.bridge.loadCurrentStoryVisualReply()
                }
                NCButton {
                    id: visualReplyUseStyleButton
                    objectName: "visualReplyUseStyleButton"
                    visible: visualReplyToolbarContainer.showExpandedTools
                    text: qsTr("Use Current Image Style")
                    compact: true
                    tone: "secondary"
                    onClicked: root.bridge.useCurrentVisualReplyStyle()
                }
                NCButton {
                    id: visualReplyCaptionButton
                    objectName: "visualReplyCaptionButton"
                    visible: visualReplyToolbarContainer.showExpandedTools
                    text: qsTr("Caption")
                    compact: true
                    tone: "secondary"
                    enabled: Boolean(root.bridge.visualReplyState.has_current_image)
                    onClicked: captionVisualDialog.open()
                }
                NCButton {
                    id: visualReplyDeleteButton
                    objectName: "visualReplyDeleteButton"
                    visible: visualReplyToolbarContainer.showExpandedTools
                    text: qsTr("Delete Image")
                    compact: true
                    tone: "danger"
                    enabled: Boolean(root.bridge.visualReplyState.has_current_image)
                    onClicked: deleteVisualDialog.open()
                }
                NCButton {
                    id: visualReplyToolsButton
                    objectName: "visualReplyToolsButton"
                    text: qsTr("Tools")
                    compact: true
                    tone: "secondary"
                    onClicked: visualReplyToolsMenu.openFor(visualReplyToolsButton)
                }
                NCButton {
                    id: floatVisualReplyButton
                    objectName: "floatVisualReplyButton"
                    text: qsTr("Float")
                    compact: true
                    tone: "quiet"
                    toolTipText: qsTr("Open Visual Reply in a separate window")
                    onClicked: root.floatVisualReplyRequested()
                }
                NCButton {
                    id: visualReplyClearButton
                    objectName: "visualReplyClearButton"
                    text: qsTr("Clear")
                    compact: true
                    tone: "danger"
                    enabled: String(root.bridge.visualReplyState.imageUrl || "").length > 0
                    onClicked: clearVisualDialog.open()
                }
                NCButton {
                    id: visualReplyDeleteAllButton
                    objectName: "visualReplyDeleteAllButton"
                    visible: visualReplyToolbarContainer.showExpandedTools
                    text: qsTr("Delete All")
                    compact: true
                    tone: "danger"
                    enabled: Number(root.bridge.visualReplyState.storage_count || 0) > 0
                    onClicked: deleteAllVisualDialog.open()
                }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.NCMetrics.radiusMedium
                color: Theme.NCTheme.window
                border.color: Theme.NCTheme.borderSubtle
                clip: true

                Image {
                    anchors.fill: parent
                    anchors.margins: Theme.NCMetrics.space8
                    source: !root.isMusetalk ? String(root.bridge.visualReplyState.imageUrl || "") : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    cache: false
                    smooth: true
                    mipmap: true
                    visible: source.toString().length > 0
                }

                NCEmptyState {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 60, 440)
                    visible: String(root.bridge.visualReplyState.imageUrl || "").length === 0
                    glyph: "▣"
                    title: qsTr("No visual reply selected")
                    description: String(root.bridge.visualReplyState.detail_text || qsTr("Generated images will appear here through the established Visual Reply state owner."))
                }
            }

            Label {
                Layout.fillWidth: true
                text: String(root.bridge.visualReplyState.caption || "")
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.Wrap
                visible: text.length > 0
            }
        }

        NCCard {
            visible: root.isMusetalk
            Layout.fillWidth: true
            Layout.fillHeight: true
            title: qsTr("Avatar Preview")
            description: root.creatorPreview
                         ? qsTr("Clean Creator render. Edit the mask in the MuseTalk Avatar Creator.")
                         : ""

            headerAccessory: RowLayout {
                NCButton {
                    objectName: "floatMusetalkPreviewButton"
                    text: qsTr("Float preview")
                    compact: true
                    tone: "quiet"
                    toolTipText: qsTr("Open Avatar Preview in a separate window")
                    onClicked: root.floatMusetalkPreviewRequested()
                }
                NCButton {
                    objectName: "musetalkResetZoomButton"
                    text: qsTr("Reset zoom")
                    visible: !root.creatorPreview
                    compact: true
                    tone: "quiet"
                    toolTipText: qsTr("Alt + mouse wheel to zoom at the pointer. Hold the middle mouse button and drag to pan. Reset fits and centers the image.")
                    onClicked: { avatarPreviewImage.resetZoom(); root.bridge.resetMusetalkZoom() }
                }
                NCButton {
                    text: qsTr("Avatar focus")
                    visible: !root.creatorPreview
                    compact: true
                    onClicked: root.bridge.toggleAvatarFocus()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.NCMetrics.radiusMedium
                color: Theme.NCTheme.window
                border.color: Theme.NCTheme.borderSubtle
                clip: true

                NCMuseTalkPreviewImage {
                    id: avatarPreviewImage
                    objectName: "musetalkEmbeddedImage"
                    anchors.fill: parent
                    anchors.margins: root.avatarOnly ? 0 : Theme.NCMetrics.space8
                    previewState: root.isMusetalk ? root.bridge.musetalkState : ({})
                    visible: source.toString().length > 0
                }

                NCEmptyState {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 60, 440)
                    visible: String(root.bridge.musetalkState.imageUrl || "").length === 0
                    glyph: "◉"
                    title: qsTr("Preview is idle")
                    description: qsTr("Frames from the selected avatar provider will appear here.")
                }
            }

            NCInlineMessage {
                Layout.fillWidth: true
                tone: "info"
                title: root.creatorPreview ? qsTr("Creator preview") : qsTr("Runtime state")
                message: String(root.bridge.musetalkState.status_text || root.bridge.musetalkState.status || qsTr("Waiting for avatar preview frames."))
            }
        }
    }

    states: State {
        name: "avatarOnly"
        when: root.avatarOnly && root.isMusetalk
        ParentChange { target: avatarPreviewImage; parent: root }
    }

    Popup {
        id: visualReplyToolsMenu
        objectName: "visualReplyToolsMenu"
        parent: Overlay.overlay
        width: 320
        padding: Theme.NCMetrics.space8
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        modal: false
        dim: false

        function openFor(control) {
            if (!control || !parent)
                return
            const mapped = control.mapToItem(parent, 0, control.height + Theme.NCMetrics.space4)
            x = Math.max(Theme.NCMetrics.space8,
                         Math.min(mapped.x, parent.width - width - Theme.NCMetrics.space8))
            y = Math.max(Theme.NCMetrics.space8,
                         Math.min(mapped.y, parent.height - implicitHeight - Theme.NCMetrics.space8))
            open()
        }

        background: Rectangle {
            color: Theme.NCTheme.windowRaised
            radius: Theme.NCMetrics.radiusLarge
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space2

            NCContextMenuItem {
                objectName: "visualReplyMenuPrevious"
                Layout.fillWidth: true
                text: qsTr("Previous")
                enabled: Number(root.bridge.visualReplyState.storage_count || 0) > 0
                onClicked: { visualReplyToolsMenu.close(); root.bridge.navigateVisualReply(-1) }
            }
            NCContextMenuItem {
                objectName: "visualReplyMenuLoad"
                Layout.fillWidth: true
                text: qsTr("Load Image")
                onClicked: { visualReplyToolsMenu.close(); root.openVisualReplyImagePicker() }
            }
            NCContextMenuItem {
                objectName: "visualReplyMenuNext"
                Layout.fillWidth: true
                text: qsTr("Next")
                enabled: Number(root.bridge.visualReplyState.storage_count || 0) > 0
                onClicked: { visualReplyToolsMenu.close(); root.bridge.navigateVisualReply(1) }
            }
            NCContextMenuItem {
                objectName: "visualReplyMenuStoryImage"
                Layout.fillWidth: true
                text: qsTr("Load Current Story Image")
                onClicked: { visualReplyToolsMenu.close(); root.bridge.loadCurrentStoryVisualReply() }
            }
            NCContextMenuItem {
                objectName: "visualReplyMenuUseStyle"
                Layout.fillWidth: true
                text: qsTr("Use Current Image Style")
                onClicked: { visualReplyToolsMenu.close(); root.bridge.useCurrentVisualReplyStyle() }
            }
            NCContextMenuItem {
                objectName: "visualReplyMenuCaption"
                Layout.fillWidth: true
                text: qsTr("Caption")
                enabled: Boolean(root.bridge.visualReplyState.has_current_image)
                onClicked: { visualReplyToolsMenu.close(); captionVisualDialog.open() }
            }
            NCContextMenuItem {
                objectName: "visualReplyMenuDelete"
                Layout.fillWidth: true
                text: qsTr("Delete Image")
                destructive: true
                enabled: Boolean(root.bridge.visualReplyState.has_current_image)
                onClicked: { visualReplyToolsMenu.close(); deleteVisualDialog.open() }
            }
            NCContextMenuItem {
                objectName: "visualReplyMenuDeleteAll"
                Layout.fillWidth: true
                text: qsTr("Delete All")
                destructive: true
                enabled: Number(root.bridge.visualReplyState.storage_count || 0) > 0
                onClicked: { visualReplyToolsMenu.close(); deleteAllVisualDialog.open() }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.NCMetrics.borderWidth
                Layout.topMargin: Theme.NCMetrics.space4
                Layout.bottomMargin: Theme.NCMetrics.space4
                color: Theme.NCTheme.borderSubtle
            }

            NCContextMenuItem {
                objectName: "visualReplyMenuExpandedToggle"
                Layout.fillWidth: true
                text: qsTr("Show tools as buttons")
                glyph: root.bridge.visualReplyToolbarExpanded ? "✓" : ""
                trailingText: root.bridge.visualReplyToolbarExpanded ? qsTr("On") : qsTr("Off")
                onClicked: {
                    visualReplyToolsMenu.close()
                    root.bridge.setVisualReplyToolbarExpanded(
                                !root.bridge.visualReplyToolbarExpanded)
                }
            }
        }
    }

    FileDialog {
        id: visualReplyImageDialog
        title: qsTr("Load Visual Reply image")
        fileMode: FileDialog.OpenFile
        nameFilters: [
            qsTr("Images (*.png *.jpg *.jpeg *.webp *.bmp)"),
            qsTr("All files (*)")
        ]
        onAccepted: root.bridge.loadVisualReplyImage(selectedFile.toString())
    }

    NCDialog {
        id: captionVisualDialog
        anchors.centerIn: parent
        title: qsTr("Visual Reply Caption")
        description: qsTr("Enter the caption shown below the current image.")
        acceptText: qsTr("Save caption")
        onAboutToShow: captionVisualField.text = String(root.bridge.visualReplyState.caption || "")
        onAccepted: root.bridge.setVisualReplyCaption(captionVisualField.text)
        contentItem: NCTextField {
            id: captionVisualField
            objectName: "visualReplyCaptionField"
            toolTipText: qsTr("Caption displayed below the current Visual Reply image. Save caption applies the text through the image controller; this does not regenerate the image.")
            Layout.fillWidth: true
            placeholderText: qsTr("Enter caption")
            selectByMouse: true
        }
    }

    NCDialog {
        id: deleteVisualDialog
        objectName: "visualReplyDeleteDialog"
        property string confirmedImagePath: ""
        anchors.centerIn: parent
        title: qsTr("Delete the current image?")
        description: qsTr("This permanently deletes the displayed image file. Stored history advances to the next available image.")
        acceptText: qsTr("Delete image")
        acceptTone: "danger"
        onAboutToShow: confirmedImagePath = String(root.bridge.visualReplyState.image_path || "")
        onAccepted: root.bridge.deleteVisualReplyImage(confirmedImagePath)
    }

    NCDialog {
        id: clearVisualDialog
        anchors.centerIn: parent
        title: qsTr("Clear the current visual reply?")
        description: qsTr("This clears the currently displayed image through the existing Visual Reply controller.")
        acceptText: qsTr("Clear visual")
        acceptTone: "danger"
        onAccepted: root.bridge.clearVisualReply()
    }

    NCDialog {
        id: deleteAllVisualDialog
        anchors.centerIn: parent
        title: qsTr("Delete all Visual Reply images?")
        description: qsTr("This permanently deletes every image stored in the Visual Reply history folder.")
        acceptText: qsTr("Delete all")
        acceptTone: "danger"
        onAccepted: root.bridge.deleteAllVisualReplyImages()
    }
}
