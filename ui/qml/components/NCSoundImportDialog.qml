pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCDialog {
    id: root
    property var snapshot: ({})
    property var selected: ({})
    property var folderOverrides: ({})
    property string reviewedScan: ""
    property string selectedEntry: ""
    property var edits: ({})
    property string previewToken: ""
    signal action(var request)
    signal rescan(bool recursive)
    readonly property int selectedCount: Object.keys(selected).length
    readonly property var entries: snapshot.entries || []
    readonly property var entry: entries.find(value => value.id === selectedEntry) || null
    modal: true
    title: qsTr("Import sounds")
    width: Math.min(640, parent ? parent.width - 24 : 640)
    height: Math.min(840, parent ? parent.height - 24 : 840)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    closePolicy: Popup.NoAutoClose
    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.bodySize
    onSnapshotChanged: {
        if ((snapshot.phase === "scanning" || snapshot.phase === "review") && snapshot.scan_id !== reviewedScan) {
            reviewedScan = snapshot.scan_id; selected = ({}); folderOverrides = ({}); edits = ({}); selectedEntry = ""
            open()
        }
    }
    function cancel() {
        preview.active = false
        if (snapshot.phase === "review" || snapshot.busy) action({operation:"cancel",scan_id:snapshot.scan_id})
        close()
    }
    function selectVisible() {
        const next = Object.assign({}, selected)
        let count = Object.keys(next).length
        for (const value of entries) {
            if (!next[value.id] && count < 100) {
                next[value.id] = true
                count++
            }
        }
        selected = next
    }
    function folderIncluded(path) {
        let included = folderOverrides[""] === undefined ? true : folderOverrides[""]
        let parent = ""
        for (const part of path ? path.split("/") : []) {
            parent = parent ? parent + "/" + part : part
            if (folderOverrides[parent] !== undefined) included = folderOverrides[parent]
        }
        return included
    }
    function setFolderIncluded(path, included) {
        if (path === "") { folderOverrides = {"":included}; return }
        const next = Object.assign({}, folderOverrides)
        for (const key of Object.keys(next)) {
            if (key === path || key.startsWith(path + "/")) delete next[key]
        }
        next[path] = included
        folderOverrides = next
    }
    contentItem: ScrollView {
        id: body
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            width: body.availableWidth
            spacing: Theme.NCMetrics.space12
            Label { text:String(root.snapshot.message || ""); wrapMode:Text.Wrap; Layout.fillWidth:true; color:Theme.NCTheme.textSecondary }
            NCCheckBox { toolTipText:qsTr("Rescan the chosen folder recursively to include audio in nested folders. Rescanning resets this dialog selection and metadata edits; only selected files are imported."); text:qsTr("Include subfolders"); checked:true; enabled:!root.snapshot.busy; onToggled:root.rescan(checked) }
            Label { text:qsTr("%1 manually selected / 100 per custom import · %2 files found").arg(root.selectedCount).arg(root.snapshot.discovered_count || 0); color:Theme.NCTheme.text }
            Rectangle {
                visible:Boolean(root.snapshot.from_folder) && root.snapshot.phase === "review"
                Layout.fillWidth:true
                Layout.preferredHeight:folderWarning.implicitHeight + Theme.NCMetrics.space16 * 2
                radius:Theme.NCMetrics.radiusMedium
                color:Theme.NCTheme.warningSoft
                border.color:Theme.NCTheme.warning
                Label {
                    id:folderWarning
                    objectName:"soundImportFolderWarning"
                    anchors.fill:parent
                    anchors.margins:Theme.NCMetrics.space16
                    color:Theme.NCTheme.text
                    wrapMode:Text.Wrap
                    text:root.snapshot.scan_limited
                         ? qsTr("At least %1 importable sounds found. The scan stopped at its safety limit; choose a smaller folder to import all.").arg(root.snapshot.discovered_count || 0)
                         : qsTr("%1 importable sounds found. Review the folder tree below before importing all.").arg(root.snapshot.discovered_count || 0)
                }
            }
            ColumnLayout {
                visible:Boolean(root.snapshot.from_folder) && root.snapshot.phase === "review"
                Layout.fillWidth:true
                spacing:Theme.NCMetrics.space8
                RowLayout {
                    Layout.fillWidth:true
                    Label { text:qsTr("Folders to include"); color:Theme.NCTheme.text; font.bold:true; Layout.fillWidth:true }
                    NCButton { text:qsTr("Include all folders"); onClicked:root.folderOverrides=({}) }
                }
                Label {
                    text:qsTr("Uncheck a folder to exclude its sounds. You can recheck a child folder.")
                    color:Theme.NCTheme.textSecondary
                    wrapMode:Text.Wrap
                    Layout.fillWidth:true
                }
                Rectangle {
                    Layout.fillWidth:true
                    Layout.preferredHeight:190
                    color:Theme.NCTheme.windowRaised
                    radius:Theme.NCMetrics.radiusMedium
                    border.color:Theme.NCTheme.border
                    ColumnLayout {
                        anchors.fill:parent
                        anchors.margins:Theme.NCMetrics.space8
                        NCCheckBox {
                            id:rootFolder
                            objectName:"soundImportRootFolder"
                            toolTipText:qsTr("Include or exclude all scanned folders for the Import included sounds action. This resets individual folder choices; you can then include child folders separately. Original audio files stay in place.")
                            text:qsTr("Selected folder (%1 sounds)").arg(root.snapshot.discovered_count || 0)
                            checked:root.folderIncluded("")
                            enabled:!root.snapshot.busy
                            onToggled:root.setFolderIncluded("",checked)
                        }
                        ListView {
                            Layout.fillWidth:true
                            Layout.fillHeight:true
                            clip:true
                            model:root.snapshot.folders || []
                            ScrollBar.vertical:ScrollBar { policy:ScrollBar.AsNeeded }
                            delegate:NCCheckBox {
                                required property var modelData
                                objectName:"soundImportFolder_" + modelData.path
                                width:ListView.view.width
                                leftPadding:Math.min(modelData.depth + 1, 8) * 18
                                text:modelData.name + " (" + modelData.total_count + ")"
                                checked:root.folderIncluded(modelData.path)
                                enabled:!root.snapshot.busy
                                ToolTip.visible:hovered
                                ToolTip.text:modelData.path
                                onToggled:root.setFolderIncluded(modelData.path,checked)
                            }
                        }
                    }
                }
                RowLayout {
                    visible:(root.snapshot.folder_page_count || 1) > 1
                    Layout.fillWidth:true
                    Label {
                        text:qsTr("Folders %1–%2 of %3").arg((root.snapshot.folder_page || 0) * 100 + 1)
                             .arg(Math.min(((root.snapshot.folder_page || 0) + 1) * 100, root.snapshot.folder_count || 0))
                             .arg(root.snapshot.folder_count || 0)
                        color:Theme.NCTheme.textSecondary
                        Layout.fillWidth:true
                    }
                    NCButton {
                        text:qsTr("Previous")
                        enabled:!root.snapshot.busy && (root.snapshot.folder_page || 0) > 0
                        onClicked:root.action({operation:"folder_page",scan_id:root.snapshot.scan_id,page:root.snapshot.folder_page - 1})
                    }
                    NCButton {
                        text:qsTr("Next")
                        enabled:!root.snapshot.busy && (root.snapshot.folder_page || 0) + 1 < root.snapshot.folder_page_count
                        onClicked:root.action({operation:"folder_page",scan_id:root.snapshot.scan_id,page:root.snapshot.folder_page + 1})
                    }
                }
            }
            RowLayout {
                Layout.fillWidth:true
                NCButton {
                    objectName:"soundImportSelectAll"
                    text:root.snapshot.page_count > 1 ? qsTr("Select shown") : qsTr("Select all")
                    enabled:root.snapshot.phase === "review" && !root.snapshot.busy && root.selectedCount < 100
                    onClicked:root.selectVisible()
                }
                NCButton { text:qsTr("Clear selection"); enabled:root.selectedCount > 0 && !root.snapshot.busy; onClicked:root.selected=({}) }
                Item { Layout.fillWidth:true }
                NCButton {
                    objectName:"soundImportAll"
                    text:Object.keys(root.folderOverrides).length
                         ? qsTr("Import included sounds") : qsTr("Import all %1").arg(root.snapshot.discovered_count || 0)
                    tone:"primary"
                    enabled:root.snapshot.phase === "review" && !root.snapshot.busy
                             && !root.snapshot.scan_limited && (root.snapshot.discovered_count || 0) > 0
                    onClicked: {
                        preview.active=false
                        const request = {operation:"confirm_all",scan_id:root.snapshot.scan_id}
                        if (Object.keys(root.folderOverrides).length) request.folder_overrides = root.folderOverrides
                        root.action(request)
                    }
                }
            }
            RowLayout {
                Layout.fillWidth:true
                visible:(root.snapshot.page_count || 1) > 1
                Label {
                    text:qsTr("Showing %1–%2 of %3").arg((root.snapshot.page || 0) * 100 + 1)
                         .arg(Math.min(((root.snapshot.page || 0) + 1) * 100, root.snapshot.discovered_count || 0))
                         .arg(root.snapshot.discovered_count || 0)
                    color:Theme.NCTheme.textSecondary
                    Layout.fillWidth:true
                }
                NCButton {
                    text:qsTr("Previous")
                    enabled:!root.snapshot.busy && (root.snapshot.page || 0) > 0
                    onClicked:root.action({operation:"page",scan_id:root.snapshot.scan_id,page:root.snapshot.page - 1})
                }
                NCButton {
                    objectName:"soundImportNextPage"
                    text:qsTr("Next")
                    enabled:!root.snapshot.busy && (root.snapshot.page || 0) + 1 < root.snapshot.page_count
                    onClicked:root.action({operation:"page",scan_id:root.snapshot.scan_id,page:root.snapshot.page + 1})
                }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 230
                color: Theme.NCTheme.windowRaised
                radius: Theme.NCMetrics.radiusMedium
                border.color: Theme.NCTheme.border
                ListView {
                    anchors.fill: parent
                    anchors.margins: Theme.NCMetrics.space8
                    clip:true
                    model:root.entries
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate:NCCheckBox {
                        required property var modelData
                        width:ListView.view.width
                        readonly property var result:(root.snapshot.results || []).find(row=>row.id===modelData.id)
                        toolTipText:qsTr("Select this audio file for import, up to 100 files per batch. Selecting also opens its metadata for review; originals stay in place and exact duplicates are skipped.")
                        text:modelData.relative_name + (result ? " · " + result.state + (result.error ? " — " + result.error : "") : "")
                        checked:Boolean(root.selected[modelData.id])
                        enabled:!root.snapshot.busy && (checked || root.selectedCount < 100)
                        onToggled: {
                            const next = Object.assign({}, root.selected)
                            if (checked) next[modelData.id] = true
                            else delete next[modelData.id]
                            root.selected = next; root.selectedEntry = modelData.id
                        }
                    }
                }
            }
            NCCard {
                visible:Boolean(root.entry)
                Layout.fillWidth:true
                title:root.entry ? root.entry.relative_name : ""
                NCComboBox {
                    id: kind
                    toolTipText:qsTr("Sound-library role for this file: Ambience and Music enable looping by default; Effect disables looping. This changes imported metadata rather than the original audio.")
                    model:["Ambience","Music","Effect"]
                    currentIndex:root.entry ? ["ambience","music","effect"].indexOf((root.edits[root.selectedEntry] || root.entry.metadata).kind) : 0
                    onActivated:root.saveEdit("kind",["ambience","music","effect"][currentIndex])
                }
                NCTextField { Layout.fillWidth:true; placeholderText:qsTr("Category"); toolTipText:qsTr("Library category saved with this sound. Initially suggested from its folder; edit it to group the sound under an appropriate category when imported."); text:root.entry ? (root.edits[root.selectedEntry] || root.entry.metadata).category : ""; onTextEdited:root.saveEdit("category",text) }
                NCTextField { Layout.fillWidth:true; placeholderText:qsTr("Content tags, comma separated"); toolTipText:qsTr("Comma-separated content tags saved with this sound for library matching. Suggestions come from filenames and folders; describe what the audio actually contains."); text:root.entry ? (root.edits[root.selectedEntry] || root.entry.metadata).tags.join(", ") : ""; onTextEdited:root.saveEdit("tags",text.split(",").map(v=>v.trim()).filter(Boolean)) }
                Label { text:qsTr("Suggested from filenames and folders. Preview and edit to describe what you hear."); wrapMode:Text.Wrap; Layout.fillWidth:true; color:Theme.NCTheme.textSecondary }
                RowLayout {
                    NCButton { text:qsTr("Preview sound"); enabled:!root.snapshot.busy; onClicked:root.action({operation:"preview",scan_id:root.snapshot.scan_id,entry_id:root.selectedEntry}) }
                    NCButton { text:qsTr("Stop"); onClicked:preview.active=false }
                }
            }
            Label { text:preview.status === Loader.Error ? qsTr("Audio preview is unavailable. Import is still available.") : qsTr("Original files stay where they are. Exact duplicates are skipped."); wrapMode:Text.Wrap; Layout.fillWidth:true; color:Theme.NCTheme.textSecondary }
        }
    }
    function saveEdit(key, value) {
        if (!entry) return
        const next = Object.assign({}, edits)
        next[selectedEntry] = Object.assign({}, edits[selectedEntry] || entry.metadata)
        next[selectedEntry][key] = value
        if (key === "kind") next[selectedEntry].loop=value !== "effect"
        edits = next
    }
    Loader {
        id:preview
        active:false
        source:"NCSoundImportPreview.qml"
        onLoaded:item.playSource(root.snapshot.preview_url)
    }
    onClosed:preview.active=false
    Connections {
        target:root
        function onSnapshotChanged() {
            if (root.snapshot.speech_active || !root.visible) {
                preview.active=false
                root.previewToken=String(root.snapshot.preview_token || "")
            }
            else if (root.snapshot.preview_token && root.snapshot.preview_token !== root.previewToken) {
                root.previewToken=root.snapshot.preview_token
                if (preview.active && preview.item) preview.item.playSource(root.snapshot.preview_url)
                else preview.active=true
            }
        }
    }
    footer:Item {
        implicitHeight: footerButtons.implicitHeight + Theme.NCMetrics.space8 + root.chromeInset
        RowLayout {
            id: footerButtons
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: root.chromeInset
            anchors.rightMargin: root.chromeInset
            anchors.topMargin: Theme.NCMetrics.space8
            spacing: Theme.NCMetrics.space8
            Item { Layout.fillWidth: true }
            NCButton { objectName:"soundImportCancel"; text:root.snapshot.busy ? qsTr("Cancel") : qsTr("Done"); onClicked:root.cancel() }
            NCButton {
                objectName:"soundImportConfirm"
                text:qsTr("Import %1 sounds").arg(root.selectedCount)
                tone:"primary"
                enabled:root.selectedCount > 0 && root.selectedCount <= 100 && !root.snapshot.busy && root.snapshot.phase === "review"
                onClicked: {
                    preview.active=false
                    root.action({operation:"confirm",scan_id:root.snapshot.scan_id,selections:Object.keys(root.selected).map(id=>{
                        const selection = {id:id}
                        if (root.edits[id]) selection.metadata = root.edits[id]
                        return selection
                    })})
                }
            }
        }
    }
}
