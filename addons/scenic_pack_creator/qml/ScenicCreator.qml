pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../../../ui/qml/components"
import "../../../ui/qml/theme" as Theme

Control {
    id: root
    objectName: "scenicPackCreator"
    padding: 16
    required property var bridge
    readonly property var state: {
        const rows = bridge.liveAddonControls || []
        for (const row of rows) if (row.id === "scenic_creator_state") return row.value || {}
        return {}
    }
    readonly property bool busy: Boolean(state.busy)
    readonly property bool editable: !busy && state.available !== false && bridge.avatarProviderChangeAllowed !== false
    readonly property var images: state.images || []
    readonly property var packs: state.packs || []
    property string selectedTag: ""
    property string pickTag: ""
    property string pickPack: ""
    property string pickToken: ""
    property var pending: ({})
    readonly property var preview: images.find(row => row.tag === selectedTag) || images[0] || ({})
    function act(action, payload) {
        const data = Object.assign({pack_id: String(state.selected || ""), token:String(state.token || "")}, payload || {})
        bridge.triggerLiveAddonActionWithPayload("scenic_creator_command", {action:action, payload:data})
    }
    function normalizeTag(value) {
        return String(value || "").trim().toLowerCase().replace(/^\[|\]$/g, "").replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "")
    }
    function syncName() { if (nameEdit && !nameEdit.activeFocus) nameEdit.text = String(state.name || "") }
    onStateChanged: Qt.callLater(syncName)
    function confirm(action, data, title, message) {
        pending = {action:action, payload:Object.assign({pack_id: String(state.selected || ""), token:String(state.token || ""), confirmed:true},data)}
        confirmation.title = title; confirmation.description = message; confirmation.open()
    }
    function acceptImage(url) {
        const data = {tag:pickTag, source_path:String(url), pack_id:pickPack, token:pickToken}
        if (images.some(row => row.tag === normalizeTag(pickTag)))
            confirm("add_image", data, qsTr("Replace image?"), qsTr("Replace the image for [%1] in this pack? Your original file outside the pack is kept.").arg(normalizeTag(pickTag)))
        else act("add_image", data)
    }
    Component.onCompleted: act("refresh")
    background: Rectangle { color: Theme.NCTheme.surface; radius: 10; border.color: Theme.NCTheme.border }
    contentItem: ScrollView {
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: parent.width
            spacing: 12
            NCSectionHeader { Layout.fillWidth:true; title:qsTr("Scenic Pack Creator"); description:qsTr("Create a pack of images. Reply tags such as [happy] or [panic] choose which image is displayed.") }
            RowLayout {
                Layout.fillWidth:true
                NCComboBox {
                    id: packChoice; objectName:"scenicCreatorPackChoice"
                    Layout.fillWidth:true; textRole:"label"; valueRole:"id"; model:root.packs
                    enabled:!root.busy
                    currentIndex:root.packs.findIndex(row => row.id === root.state.selected)
                    toolTipText:qsTr("Open a saved pack for editing. This does not change the pack selected for chat.")
                    onActivated:root.act("select", {pack_id:String(currentValue)})
                }
                NCButton { objectName:"scenicCreatorNew"; text:qsTr("New pack"); tone:"primary"; enabled:root.editable; toolTipText:qsTr("Create an empty pack with its own folder. Existing packs are never overwritten."); onClicked:{newName.text="";newPack.open()} }
                NCButton { text:qsTr("Refresh"); enabled:!root.busy; toolTipText:qsTr("Scan ScenicPacks once for added or changed packs."); onClicked:root.act("refresh") }
            }
            NCInlineMessage { Layout.fillWidth:true; visible:root.bridge.avatarProviderChangeAllowed === false; message:qsTr("Stop the chat engine before editing or changing the selected Scenic pack. You can still browse and preview images.") }
            NCInlineMessage { Layout.fillWidth:true; tone:root.state.error ? "error" : "info"; message:String(root.state.error || root.state.status || qsTr("Create your first pack to begin.")) }
            BusyIndicator { running:root.busy; visible:running; Layout.alignment:Qt.AlignHCenter }
            NCCard {
                Layout.fillWidth:true; visible:Boolean(root.state.selected)
                title:qsTr("Pack details")
                Label { text:qsTr("Pack display name"); color:Theme.NCTheme.textSecondary }
                RowLayout {
                    Layout.fillWidth:true
                    NCTextField { id:nameEdit; objectName:"scenicCreatorName"; Layout.fillWidth:true; enabled:root.editable; label:qsTr("Pack display name"); toolTipText:qsTr("Name shown in the pack list. Saving changes the display name while keeping the package folder and ID stable.") }
                    NCButton { text:qsTr("Save name"); enabled:root.editable && nameEdit.text.trim().length>0; toolTipText:qsTr("Save the edited display name. Image and tag changes save automatically."); onClicked:root.act("save",{name:nameEdit.text}) }
                }
                RowLayout {
                    Layout.fillWidth:true
                    NCButton { objectName:"scenicCreatorSelectRuntime"; text:qsTr("Select for Scenic"); enabled:root.editable && root.images.some(row=>row.available); toolTipText:qsTr("Select this pack for the Scenic provider. Activate Scenic separately under Runtime → Avatar; this button does not switch avatar engines."); onClicked:root.bridge.triggerLiveAddonActionWithPayload("scenic_creator_select_runtime",{pack_id:String(root.state.selected)}) }
                    NCButton { text:qsTr("Open pack folder"); enabled:!root.busy; toolTipText:qsTr("Open this pack's folder so you can copy or share the complete package."); onClicked:Qt.openUrlExternally(String(root.state.folder_url || "")) }
                }
            }
            GridLayout {
                Layout.fillWidth:true; visible:Boolean(root.state.selected)
                columns:width>=850 ? 2:1; columnSpacing:12; rowSpacing:12
                NCCard {
                    Layout.fillWidth:true; Layout.preferredWidth:1; Layout.alignment:Qt.AlignTop; title:qsTr("Images and tags")
                    description:qsTr("Use any tag. Tags become lowercase; spaces become underscores. Images are copied into the pack.")
                    ListView {
                        id:imageList; objectName:"scenicCreatorImageList"
                        Component.onDestruction:model=null
                        Layout.fillWidth:true; Layout.preferredHeight:300; clip:true; spacing:6
                        model:root.images
                        ScrollBar.vertical:ScrollBar {}
                        delegate:Button {
                            id:imageRow
                            required property var modelData
                            width:imageList.width; height:60; checkable:true; checked:root.preview.tag === modelData.tag
                            Accessible.name: "[" + modelData.tag + "]"
                            background: Rectangle {
                                radius:8; color:imageRow.checked ? Theme.NCTheme.surfaceSelected : Theme.NCTheme.surface
                                border.color:imageRow.checked ? Theme.NCTheme.accent : Theme.NCTheme.border
                            }
                            contentItem:RowLayout {
                                Image { source:imageRow.modelData.source; sourceSize.width:48; sourceSize.height:48; Layout.preferredWidth:48; Layout.preferredHeight:48; fillMode:Image.PreserveAspectFit; asynchronous:true; cache:false }
                                Label { Layout.fillWidth:true; text:"["+imageRow.modelData.tag+"]"+(imageRow.modelData.available ? "":qsTr(" — missing image")); color:Theme.NCTheme.text; elide:Text.ElideRight }
                            }
                            onClicked:{root.selectedTag=modelData.tag;tagEdit.text=modelData.tag}
                        }
                        Label { anchors.centerIn:parent; visible:root.images.length===0; text:qsTr("Add the first image below."); color:Theme.NCTheme.textMuted }
                    }
                    Label { text:qsTr("Image tag"); color:Theme.NCTheme.textSecondary }
                    NCTextField { id:tagEdit; objectName:"scenicCreatorTag"; Layout.fillWidth:true; enabled:root.editable; label:qsTr("Image tag"); placeholderText:qsTr("For example: neutral, panic, Santa Claus"); toolTipText:qsTr("Tag associated with an image. Reply tags select images by this name. Spaces become underscores, for example Santa Claus becomes [santa_claus].") }
                    Flow {
                        Layout.fillWidth:true; spacing:8
                        NCButton { objectName:"scenicCreatorAddImage"; text:qsTr("Add / replace image"); enabled:root.editable && root.normalizeTag(tagEdit.text).length>0; toolTipText:qsTr("Choose an image to copy into this pack. An existing tag asks before its image is replaced."); onClicked:{root.pickTag=tagEdit.text;root.pickPack=String(root.state.selected);root.pickToken=String(root.state.token || "");imagePicker.open()} }
                        NCButton {
                            objectName:"scenicCreatorRenameTag"; text:qsTr("Rename selected tag")
                            enabled:root.editable && Boolean(root.selectedTag) && root.normalizeTag(tagEdit.text).length>0
                            toolTipText:qsTr("Rename the selected image's tag to the text above. If the new tag already exists, confirm before replacing that entry.")
                            onClicked:{
                                const data={tag:root.selectedTag,new_tag:tagEdit.text}
                                if (root.normalizeTag(tagEdit.text)!==root.selectedTag && root.images.some(row=>row.tag===root.normalizeTag(tagEdit.text)))
                                    root.confirm("rename_tag",data,qsTr("Replace existing tag?"),qsTr("Rename [%1] to [%2] and replace that tag's existing image?").arg(root.selectedTag).arg(root.normalizeTag(tagEdit.text)))
                                else root.act("rename_tag",data)
                            }
                        }
                        NCButton { objectName:"scenicCreatorRemoveImage"; text:qsTr("Remove image"); tone:"danger"; enabled:root.editable && Boolean(root.selectedTag); toolTipText:qsTr("Remove the selected tag and its managed image from this pack. Source files outside the pack are kept."); onClicked:root.confirm("remove_image",{tag:root.selectedTag},qsTr("Remove image?"),qsTr("Remove [%1] and its image file from this pack? Your original image outside the pack is kept.").arg(root.selectedTag)) }
                    }
                }
                NCCard {
                    Layout.fillWidth:true; Layout.preferredWidth:1; Layout.alignment:Qt.AlignTop; title:qsTr("Image preview")
                    Image { objectName:"scenicCreatorPreview"; Layout.fillWidth:true; Layout.preferredHeight:390; source:String(root.preview.source || ""); fillMode:Image.PreserveAspectFit; asynchronous:true; cache:false }
                    Label { Layout.fillWidth:true; text:root.preview.tag ? "["+root.preview.tag+"]" : qsTr("Select an image to preview it."); wrapMode:Text.Wrap; color:Theme.NCTheme.textSecondary }
                }
            }
            Item { Layout.preferredHeight:12 }
        }
    }
    FileDialog { id:imagePicker; title:qsTr("Choose a Scenic image"); nameFilters:[qsTr("Images (*.png *.jpg *.jpeg *.webp *.bmp)")]; onAccepted:root.acceptImage(selectedFile) }
    NCDialog {
        id:newPack; objectName:"scenicCreatorNewDialog"; parent:Overlay.overlay
        title:qsTr("New Scenic pack"); description:qsTr("Choose a name. Add images and tags after the pack is created.")
        acceptText:qsTr("Create pack"); acceptEnabled:newName.text.trim().length>0
        NCTextField { id:newName; objectName:"scenicCreatorNewName"; width:parent.width; label:qsTr("New pack name"); toolTipText:qsTr("Name of the new pack. A folder is created under ScenicPacks; an existing folder with the same name is preserved.") }
        onAccepted:root.act("create",{name:newName.text})
    }
    NCDialog { id:confirmation; objectName:"scenicCreatorConfirmation"; parent:Overlay.overlay; acceptText:qsTr("Confirm"); acceptTone:"danger"; onAccepted:root.act(root.pending.action,root.pending.payload) }
}
