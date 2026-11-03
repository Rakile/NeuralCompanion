pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../components"
import "../theme" as Theme

Item {
    id: root
    required property var bridge
    property var dialogWindow: root.Window.window
    readonly property bool dialogActive: saveFile.visible || loadFile.visible || imageReview.visible || result.visible
    readonly property var controller: bridge.memoryWorkspace
    readonly property var review: controller.imageReview
    readonly property var memoryState: controller.state
    property var selectedIds: []
    property string activeRequest: ""
    property string lastResult: ""
    property bool detailsExpanded: false
    Connections {
        target: root.controller
        function onSaveFileRequested() { saveFile.open() }
        function onLoadFileRequested() { loadFile.open() }
    }
    FileDialog {
        id: saveFile; objectName: "memorySaveFile"
        parentWindow: root.dialogWindow
        title: qsTr("Save conversation as")
        fileMode: FileDialog.SaveFile
        nameFilters: ["Conversation (*.json)"]
        defaultSuffix: "json"
        onAccepted: root.controller.runAction("save_context", {path: String(selectedFile)})
    }
    FileDialog {
        id: loadFile; objectName: "memoryLoadFile"
        parentWindow: root.dialogWindow
        title: qsTr("Load conversation")
        fileMode: FileDialog.OpenFile
        nameFilters: ["Conversation (*.json)"]
        onAccepted: root.controller.runAction("load_context", {path: String(selectedFile)})
    }
    function syncReview() {
        if (!review.active) { imageReview.close(); return }
        if (activeRequest !== String(review.requestId)) {
            activeRequest = String(review.requestId)
            selectedIds = (review.images || []).filter(item => Boolean(item.selected)).map(item => String(item.id))
        }
        imageReview.open()
    }
    onReviewChanged: syncReview()
    Component.onCompleted: syncReview()
    onMemoryStateChanged: {
        const text = String(memoryState.resultText || "")
        if (!text) {
            root.lastResult = ""
            root.detailsExpanded = false
            result.close()
            return
        }
        if (!memoryState.busy && !memoryState.error && text !== root.lastResult) {
            root.lastResult = text
            root.detailsExpanded = false
            result.open()
        }
    }
    Dialog {
        id: imageReview
        objectName: "memoryImageReview"
        parent: root.dialogWindow ? root.dialogWindow.Overlay.overlay : null
        anchors.centerIn: parent
        width: Math.min(760, parent ? parent.width - 32 : 760)
        height: Math.min(620, parent ? parent.height - 32 : 620)
        modal: true
        title: qsTr("Review recalled images before sending")
        standardButtons: Dialog.Ok | Dialog.Cancel
        closePolicy: Popup.NoAutoClose
        onAccepted: root.controller.answerImageReview(root.activeRequest, root.selectedIds, true)
        onRejected: root.controller.answerImageReview(root.activeRequest, [], false)
        ColumnLayout {
            anchors.fill: parent
            Label { Layout.fillWidth: true; text: String(root.review.prompt || ""); wrapMode: Text.Wrap }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    Repeater {
                        model: root.review.images || []
                        delegate: RowLayout {
                            id: imageRow
                            required property var modelData
                            Layout.fillWidth: true
                            Image { Layout.preferredWidth: 220; Layout.preferredHeight: 150; source: String(imageRow.modelData.source || ""); fillMode: Image.PreserveAspectFit; asynchronous: true }
                            CheckBox {
                                id: settingsHelpTarget0; NCHelp { target: settingsHelpTarget0; text: qsTr("Choose whether this recalled image is included in the pending request. Confirm the dialog to send the selected images; unchecking does not delete the stored image.") }

                                Layout.fillWidth: true
                                text: String(imageRow.modelData.label || imageRow.modelData.id)
                                checked: root.selectedIds.indexOf(String(imageRow.modelData.id)) >= 0
                                onClicked: {
                                    const id = String(imageRow.modelData.id)
                                    root.selectedIds = checked ? root.selectedIds.concat([id]) : root.selectedIds.filter(value => value !== id)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    NCDialog {
        id: result; objectName: "memoryResults"; parent: root.dialogWindow ? root.dialogWindow.Overlay.overlay : null; anchors.centerIn: parent; modal: true
        width: Math.min(760, parent ? parent.width - 32 : 760)
        height: Math.min(560, parent ? parent.height - 32 : 560)
        title: String(root.memoryState.resultTitle || qsTr("Memory results"))
        footer: null
        ColumnLayout {
            anchors.fill: parent
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth
                TextArea {
                    objectName: "memoryResultText"
                    text: root.lastResult + (root.detailsExpanded ? "\n\n" + String(root.memoryState.resultDetails || "") : "")
                    readOnly: true; selectByMouse: true
                    wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText
                    color: Theme.NCTheme.text
                    selectionColor: Theme.NCTheme.selection
                    selectedTextColor: Theme.NCTheme.text
                    background: Rectangle { color: Theme.NCTheme.windowRaised }
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: 8
                NCButton {
                    objectName: "memoryResultDetailsToggle"
                    visible: Boolean(root.memoryState.resultDetails)
                    text: root.detailsExpanded ? qsTr("Hide technical details") : qsTr("Technical details")
                    onClicked: root.detailsExpanded = !root.detailsExpanded
                }
                NCButton {
                    visible: Boolean(root.memoryState.resultDetails) && Boolean(root.memoryState.summaryText)
                    text: qsTr("Read summary")
                    onClicked: root.controller.runAction("review_summary", {})
                }
                NCButton { text: qsTr("Close"); tone: "primary"; onClicked: result.close() }
            }
        }
    }
}
