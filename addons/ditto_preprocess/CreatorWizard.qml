pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import "../../ui/qml/components"
import "../../ui/qml/theme" as Theme

Item {
    id: root
    objectName: "dittoCreatorWizard"
    required property var bridge
    readonly property var state: {
        const controls = bridge.liveAddonControls || []
        const entry = controls.find(c => c.id === "ditto_wizard_state")
        return entry ? entry.value : ({})
    }
    readonly property int step: Number(state.step || 1)
    readonly property bool locked: Boolean(state.busy || state.testing || state.chat_active)
    readonly property string previewAvatarName: {
        const avatar = (state.variants || []).find(v => v.id === state.selected_variant)
        return avatar ? avatar.display_name || avatar.id : ""
    }
    function tuningControls(section) {
        return (bridge.liveAddonControls || []).filter(c => c.section === section)
    }
    readonly property var playbackState: bridge.musetalkState || ({})
    readonly property string previewViewId: "ditto-creator-" + Date.now() + "-" + Math.random()
    readonly property bool previewActive: visible && step === 3 && (!Window.window || Window.window.visibility !== Window.Minimized)
    function syncPreviewVisibility() {
        if (typeof bridge.setMusetalkPreviewVisible === "function")
            bridge.setMusetalkPreviewVisible(previewViewId, root.previewActive)
    }
    onPreviewActiveChanged: syncPreviewVisibility()
    Component.onCompleted: syncPreviewVisibility()
    Component.onDestruction: {
        if (bridge && typeof bridge.setMusetalkPreviewVisible === "function")
            bridge.setMusetalkPreviewVisible(previewViewId, false)
    }
    property bool showSaved: false
    property bool showEmotions: false
    property bool showAdvanced: false
    property string pickerEmotion: ""
    property string dropError: ""
    property var pendingRemoval: ({})
    property var pendingReplacement: ({})
    function acceptMedia(url) {
        dropError = ""
        if (pendingReplacement.variant_id) {
            const target = pendingReplacement
            pendingReplacement = ({})
            bridge.triggerLiveAddonActionWithPayload("ditto_replace_variant", {
                package_id:target.package_id, variant_id:target.variant_id, token:target.token,
                source_path:String(url) })
        } else {
            bridge.triggerLiveAddonActionWithPayload("ditto_wizard_media", {path:String(url), emotion:pickerEmotion})
        }
        pickerEmotion = ""
    }
    function chooseMedia(emotion) {
        pickerEmotion = emotion || ""
        mediaPicker.open()
    }
    function emotionAction(action, variantId) {
        const entry = (state.emotion_entries || []).find(row => row.id === variantId)
        if (!entry) return
        const target = {package_id:state.selected_package, variant_id:variantId, token:entry.token,
                        name:entry.display_name || variantId, confirmed:true}
        if (action === "delete") {
            pendingRemoval = target
            removeAvatarDialog.open()
        } else if (action === "replace") {
            pendingReplacement = target
            mediaPicker.open()
        } else if (action === "preview") {
            edit("ditto_creator_variant", variantId)
            root.action("ditto_test_render")
        } else {
            bridge.triggerLiveAddonActionWithPayload(action === "redo" ? "ditto_redo_variant" : "ditto_make_base", target)
        }
    }
    function action(key) { bridge.triggerLiveAddonAction(key) }
    function edit(key, value) { bridge.setLiveAddonControl(key, value) }
    readonly property var cropIds: ["ditto_crop_scale", "ditto_crop_x", "ditto_crop_y", "ditto_crop_rotate"]
    function cropControls() {
        return (bridge.liveAddonControls || []).filter(c => cropIds.indexOf(c.id) >= 0)
    }
    function advancedControls() {
        const ids = ["ditto_test_audio","ditto_choose_audio","ditto_test_emotion","ditto_loop_mode",
            "ditto_source_frames","ditto_max_size","ditto_crop_scale","ditto_crop_x","ditto_crop_y",
            "ditto_crop_rotate","ditto_repo_path","ditto_python_path","ditto_import_path","ditto_choose_import",
            "ditto_wizard_import"]
        return (bridge.liveAddonControls || []).filter(c =>
            (ids.indexOf(c.id) >= 0 || c.id.startsWith("ditto_map_")) &&
            !(root.step === 2 && cropIds.indexOf(c.id) >= 0))
    }
    FileDialog {
        id: mediaPicker
        title: qsTr("Choose your avatar image or video")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("Images and videos (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.mkv *.avi *.webm)")]
        onAccepted: root.acceptMedia(selectedFile)
        onRejected: root.pendingReplacement = ({})
    }
    NCDialog {
        id: removeAvatarDialog
        objectName: "dittoRemoveAvatarDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Permanently delete this emotion?")
        description: qsTr("Permanently delete “%1” from this package and remove its prepared files from disk? This cannot be undone. Original media outside its folder is kept.").arg(root.pendingRemoval.name || "")
        acceptText: qsTr("Delete permanently")
        acceptTone: "danger"
        acceptEnabled: !root.locked && root.pendingRemoval.package_id === root.state.selected_package
        onAccepted: root.bridge.triggerLiveAddonActionWithPayload("ditto_delete_variant", root.pendingRemoval)
    }
    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: Math.min(root.width - 48, 860)
            x: Math.max(24, (root.width-width)/2)
            spacing: 20
            Label {
                text: qsTr("Bring your avatar to life")
                font.pixelSize: 26
                font.bold: true
                color: Theme.NCTheme.text
            }
            Label {
                text: qsTr("Start with an image or a short video. We’ll handle the preparation and save it for you.")
                color: Theme.NCTheme.textMuted
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Repeater {
                    model: [qsTr("Choose media"), qsTr("Prepare"), qsTr("Try & use")]
                    delegate: Rectangle {
                        required property int index
                        required property string modelData
                        Layout.fillWidth: true
                        height: 48
                        radius: 10
                        color: root.step === index+1 ? Theme.NCTheme.surfaceRaised : "transparent"
                        border.color: root.step === index+1 ? Theme.NCTheme.accent : Theme.NCTheme.border
                        Label {
                            anchors.centerIn: parent
                            text: String(index+1) + "  " + modelData
                            color: root.step === index+1 ? Theme.NCTheme.text : Theme.NCTheme.textMuted
                            font.bold: root.step === index+1
                        }
                    }
                }
            }
            NCButton {
                objectName: "dittoBackToMediaButton"
                visible: root.step > 1
                text: qsTr("Back to Choose media")
                enabled: !root.locked
                onClicked: root.action("ditto_wizard_back")
            }
            Rectangle {
                id: dropZone
                objectName: "dittoDropZone"
                visible: root.step === 1
                Layout.fillWidth: true
                height: 260
                radius: 16
                color: drop.containsDrag ? Theme.NCTheme.surfaceRaised : Theme.NCTheme.surface
                border.width: 2
                border.color: drop.containsDrag ? Theme.NCTheme.accent : Theme.NCTheme.border
                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 14
                    Label { Layout.alignment: Qt.AlignHCenter; text: "↓"; font.pixelSize: 40; color: Theme.NCTheme.accent }
                    Label { Layout.alignment: Qt.AlignHCenter; text: qsTr("Drop your image or video here"); font.pixelSize: 20; color: Theme.NCTheme.text }
                    Label { Layout.alignment: Qt.AlignHCenter; text: qsTr("Use a clear, front-facing face for the best result."); color: Theme.NCTheme.textMuted }
                    NCButton { Layout.alignment: Qt.AlignHCenter; text: qsTr("Or choose a file"); enabled: !root.locked; onClicked: root.chooseMedia("") }
                }
                DropArea {
                    id: drop
                    anchors.fill: parent
                    enabled: !root.locked
                    onDropped: event => {
                        if (!event.hasUrls || event.urls.length !== 1) {
                            root.dropError = qsTr("Please drop one image or video at a time.")
                            return
                        }
                        root.pickerEmotion = ""
                        root.acceptMedia(event.urls[0])
                        event.acceptProposedAction()
                    }
                }
            }
            ColumnLayout {
                visible: root.step === 2
                Layout.fillWidth: true
                spacing: 16
                RowLayout {
                    Layout.fillWidth: true
                    NCButton {
                        objectName: "dittoPreviewCropButton"
                        text: qsTr("Preview crop")
                        enabled: !root.locked
                        toolTipText: qsTr("Detect the face in the first source frame without preparing the avatar. Crop controls then update the outline immediately.")
                        onClicked: root.action("ditto_preview_crop")
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.state.crop_preview && root.state.crop_preview.image_url
                              ? qsTr("Crop outline · first source frame")
                              : qsTr("Check the crop before preparing. Face detection runs when you press the button.")
                        color: Theme.NCTheme.textMuted
                        wrapMode: Text.WordWrap
                    }
                }
                Image {
                    id: cropSource
                    objectName: "dittoCropSourceImage"
                    source: (root.state.crop_preview || {}).image_url || root.state.source_url || ""
                    visible: source.toString().length > 0
                    Layout.fillWidth: true
                    Layout.preferredHeight: 300
                    fillMode: Image.PreserveAspectFit
                    cache: false
                    Canvas {
                        id: cropOutline
                        objectName: "dittoCropOutline"
                        anchors.fill: parent
                        visible: cropSource.status === Image.Ready && viewPoints.length === 4
                        readonly property var viewPoints: {
                            const points = (root.state.crop_preview || {}).points || []
                            const width = cropSource.paintedWidth
                            const height = cropSource.paintedHeight
                            const left = (cropSource.width - width) / 2
                            const top = (cropSource.height - height) / 2
                            return points.map(p => ({x: left + p[0]*width, y: top + p[1]*height}))
                        }
                        onViewPointsChanged: requestPaint()
                        onAvailableChanged: requestPaint()
                        onVisibleChanged: requestPaint()
                        onPaint: {
                            const context = getContext("2d")
                            if (!context) return
                            context.clearRect(0, 0, width, height)
                            if (viewPoints.length !== 4) return
                            context.beginPath()
                            context.moveTo(viewPoints[0].x, viewPoints[0].y)
                            for (let i = 1; i < viewPoints.length; ++i)
                                context.lineTo(viewPoints[i].x, viewPoints[i].y)
                            context.closePath()
                            context.strokeStyle = Theme.NCTheme.accent
                            context.lineWidth = 2
                            context.stroke()
                        }
                    }
                }
                NCLiveControlsGroup {
                    Layout.fillWidth: true
                    title: qsTr("Face crop")
                    showRefresh: false
                    description: qsTr("Adjust the outline, then prepare. Changing source or maximum source size requires another crop preview. Existing prepared avatars stay unchanged.")
                    controls: root.cropControls()
                    onControlEdited: (key,value) => root.edit(key,value)
                }
                Label {
                    Layout.fillWidth: true
                    text: (root.state.source || "").split(/[\\/]/).pop()
                    color: Theme.NCTheme.text
                    font.bold: true
                    elide: Text.ElideMiddle
                }
                Label { text: root.state.replacement ? qsTr("Replacing %1 — your existing version stays until the new one is ready").arg(root.state.emotion) : root.state.emotion ? qsTr("Adding the %1 label to this package").arg(root.state.emotion) : qsTr("Avatar name"); color: Theme.NCTheme.textMuted }
                NCTextField {
                    objectName: "dittoAvatarName"
                    toolTipText: qsTr("Name for the avatar package saved by this preparation. Choose a recognizable name so you can find it again among saved avatars.")
                    Layout.fillWidth: true
                    visible: !root.state.emotion
                    text: root.state.name || ""
                    enabled: !root.locked
                    onEditingFinished: root.edit("ditto_package_name", text)
                }
                Label {
                    Layout.fillWidth: true
                    text: qsTr("Preparation runs once. Your avatar is saved automatically and will be ready for chat.")
                    color: Theme.NCTheme.textMuted
                    wrapMode: Text.WordWrap
                }
                RowLayout {
                    NCButton {
                        objectName: "dittoPrepareButton"
                        text: root.state.busy ? qsTr("Working…") : root.state.replacement ? qsTr("Save replacement") : qsTr("Prepare avatar")
                        tone: "primary"
                        enabled: !root.locked && !root.state.fps_choice
                        onClicked: root.action("ditto_wizard_prepare")
                    }
                    NCButton { text: qsTr("Choose another file"); enabled: !root.locked; onClicked: { if (root.state.replacement) { const entry = (root.state.emotion_entries || []).find(row => row.id === root.state.selected_variant); if (entry) root.emotionAction("replace", entry.id) } else root.chooseMedia(root.state.emotion || "") } }
                    NCButton { visible: Boolean(root.state.busy); text: qsTr("Cancel"); onClicked: root.action("ditto_cancel") }
                }
                NCButton { visible: Boolean(root.state.emotion); text: root.state.replacement ? qsTr("Cancel replacement") : qsTr("Discard this unfinished emotion"); tone: "quiet"; enabled: !root.locked; onClicked: root.action(root.state.replacement ? "ditto_cancel_replacement" : "ditto_wizard_discard") }
            }
            ColumnLayout {
                visible: Boolean(root.state.fps_choice)
                Layout.fillWidth: true
                Label {
                    text: root.state.fps_choice ? root.state.fps_choice.message : ""
                    color: Theme.NCTheme.text
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                RowLayout {
                    NCButton { text: qsTr("Convert to 25 FPS"); tone: "primary"; enabled: !root.locked; onClicked: root.action("ditto_package_prepare_convert") }
                    NCButton { text: qsTr("Keep original frames"); enabled: !root.locked; onClicked: root.action("ditto_package_prepare_keep") }
                }
            }
            RowLayout {
                visible: root.step > 1 && (root.state.variants || []).length > 0
                Layout.fillWidth: true
                Label { text: qsTr("Avatar to preview"); color: Theme.NCTheme.text }
                NCComboBox {
                    objectName: "dittoPreviewAvatarSelector"
                    toolTipText: qsTr("Select the avatar to preview and edit. Animation and generation settings below belong only to this avatar and are saved in its package. This does not change the avatar or package selected for chat. Select an unfinished entry to continue preparing it.")
                    Layout.fillWidth: true
                    model: root.state.variants || []
                    textRole: "display_name"
                    valueRole: "id"
                    currentIndex: (root.state.variants || []).findIndex(v => v.id === root.state.selected_variant)
                    enabled: !root.locked
                    onActivated: root.edit("ditto_creator_variant", currentValue)
                }

            }
            Label {
                visible: (root.state.emotion_entries || []).length > 0
                text: qsTr("Your package: emotions and looks")
                font.bold: true
                color: Theme.NCTheme.text
            }
            Label {
                objectName: "dittoCustomLabelHelp"
                visible: (root.state.emotion_entries || []).length > 0
                Layout.fillWidth: true
                text: qsTr("Use any label, such as panic, Santa Claus or whispering, to choose a different prepared image or video loop. Ditto's generated expressions are separate and configured in the avatar settings.")
                color: Theme.NCTheme.textMuted
                wrapMode: Text.Wrap
            }
            AvatarEmotionList {
                Layout.fillWidth: true
                entries: root.state.emotion_entries || []
                busy: root.locked
                objectPrefix: "dittoEmotion"
                onActionRequested: (action, variantId) => root.emotionAction(action, variantId)
            }
            ColumnLayout {
                visible: root.step === 3
                Layout.fillWidth: true
                spacing: 16
                Rectangle {
                    Layout.fillWidth: true
                    height: 330
                    radius: 12
                    color: "#060c13"
                    Image {
                        objectName: "dittoSpeakingPreview"
                        anchors.fill: parent
                        anchors.margins: 8
                        // Only the image follows the shared playback clock;
                        // frames must not rebuild package/settings controls.
                        source: root.playbackState.provider_id === "ditto" && root.playbackState.creator_preview_active
                                ? root.playbackState.imageUrl || ""
                                : root.state.preview_url || root.state.still_url || ""
                        fillMode: Image.PreserveAspectFit
                        cache: false
                        asynchronous: false
                    }
                }
                Label {
                    text: root.state.testing ? (root.state.muted ? qsTr("Speaking preview · muted · 25 FPS") : qsTr("Speaking preview · with audio · 25 FPS")) : qsTr("Ready! Try a short lip-sync preview, then use your avatar in chat.")
                    color: Theme.NCTheme.textMuted
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                RowLayout {
                    NCButton { objectName: "dittoPreviewButton"; text: root.state.testing ? qsTr("Previewing…") : qsTr("Preview speaking"); enabled: !root.locked; onClicked: root.action("ditto_test_render") }
                    NCButton { objectName: "dittoUseButton"; text: root.state.selected_for_chat ? qsTr("Selected for chat") : qsTr("Use in chat"); tone: "primary"; enabled: !root.locked && !(root.state.pending_variants || []).length; onClicked: root.action("ditto_use_package") }
                    NCButton { objectName: "dittoStopPreviewButton"; visible: Boolean(root.state.testing); text: qsTr("Stop preview"); onClicked: root.action("ditto_stop_preview") }
                    CheckBox {
                        objectName: "dittoPreviewMuteCheckbox"
                        ToolTip.visible: hovered || activeFocus
                        ToolTip.text: qsTr("Mute audio in the local speaking preview while retaining the animation. This affects preview playback.")
                        text: qsTr("Mute preview")
                        checked: Boolean(root.state.muted)
                        onToggled: root.edit("ditto_preview_muted", checked)
                    }
                }
                RowLayout {
                    NCButton { text: qsTr("Create another avatar"); tone: "quiet"; enabled: !root.locked; onClicked: root.chooseMedia("") }
                    NCButton { text: root.showEmotions ? qsTr("Hide emotions") : qsTr("Add emotion variants (optional)"); tone: "quiet"; onClicked: root.showEmotions = !root.showEmotions }
                }
                ColumnLayout {
                    visible: root.showEmotions || (root.state.pending_variants || []).length > 0
                    Layout.fillWidth: true
                    Label { text: qsTr("Choose any reply label for a different image or video, such as sleepy, curious or whispering. Ditto's built-in generated expressions are configured separately."); color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    Label { visible: (root.state.pending_variants || []).length > 0; text: qsTr("An emotion still needs preparation. Select it in Avatar to preview above to finish or discard it before using this package."); color: Theme.NCTheme.textMuted; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    RowLayout {
                        NCTextField { id: emotion; objectName: "dittoCustomEmotionName"; toolTipText: qsTr("Reply label to associate with a different source image or video, such as sleepy or whispering. Choose media and prepare it to add the variant; generated Ditto expressions are configured separately."); placeholderText: qsTr("Your emotion or reply label"); enabled: !root.locked; Layout.fillWidth: true }
                        NCButton { objectName: "dittoChooseEmotionMediaButton"; text: qsTr("Choose media for this label"); enabled: !root.locked && emotion.text.trim().length > 0; onClicked: root.chooseMedia(emotion.text.trim()) }
                    }
                    Repeater {
                        model: root.state.variants || []
                        delegate: Label {
                            required property var modelData
                            text: modelData.display_name + (modelData.prepared ? qsTr(" — ready") : qsTr(" — needs preparation")) + (modelData.default ? qsTr(" (default)") : "")
                            color: Theme.NCTheme.textMuted
                        }
                    }
                }
                NCLiveControlsGroup {
                    objectName: "dittoAvatarAnimationSettings"
                    Layout.fillWidth: true
                    showRefresh: false
                    title: qsTr("Animation · %1").arg(root.previewAvatarName)
                    description: qsTr("Saved automatically for this avatar. Other avatars keep their own settings. Preview and chat use the same values.")
                    controls: root.tuningControls("Animation")
                    onControlEdited: (key,value) => root.edit(key,value)
                }
                NCLiveControlsGroup {
                    objectName: "dittoAvatarGenerationSettings"
                    Layout.fillWidth: true
                    showRefresh: false
                    title: qsTr("Generation · %1").arg(root.previewAvatarName)
                    description: qsTr("Applies when this avatar's next speech chunk starts rendering. Frames already rendering or waiting to play keep their current settings.")
                    controls: root.tuningControls("Generation")
                    onControlEdited: (key,value) => root.edit(key,value)
                }
            }
            Label {
                Layout.fillWidth: true
                text: root.dropError || (root.state.chat_active ? qsTr("Stop chat and unload Ditto before preparing or testing avatars.") : root.state.status || "")
                color: root.dropError ? Theme.NCTheme.error : Theme.NCTheme.textMuted
                wrapMode: Text.WordWrap
            }
            BusyIndicator { running: Boolean(root.state.busy || root.state.testing); visible: running; Layout.alignment: Qt.AlignHCenter }
            RowLayout {
                NCButton { text: root.showSaved ? qsTr("Hide saved avatars") : qsTr("Open a saved avatar"); tone: "quiet"; onClicked: root.showSaved = !root.showSaved }
                NCButton { text: root.showAdvanced ? qsTr("Hide advanced") : qsTr("Advanced"); tone: "quiet"; onClicked: root.showAdvanced = !root.showAdvanced }
                Item { Layout.fillWidth: true }
                NCButton {
                    objectName: "dittoCancelOperationButton"
                    visible: (root.step !== 2 || !root.state.busy)
                             && Boolean(root.state.busy || root.state.testing || root.state.loaded || root.state.worker_running)
                    text: root.state.busy || root.state.testing ? qsTr("Cancel and unload") : qsTr("Unload models")
                    toolTipText: qsTr("Stop the Ditto operation and unload its worker, even while a speaking preview is starting. Saved avatar packages and their settings are kept.")
                    tone: "quiet"
                    enabled: !root.state.chat_active
                    onClicked: root.action(root.state.busy || root.state.testing ? "ditto_cancel" : "ditto_unload")
                }
            }
            RowLayout {
                visible: root.showSaved
                Layout.fillWidth: true
                NCComboBox { id: saved; toolTipText: qsTr("Saved package to open in the creator. Select a package here, then press Open to load its avatars and mappings."); model: root.state.packages || []; textRole: "display_name"; valueRole: "id"; Layout.fillWidth: true }
                NCButton { text: qsTr("Open"); enabled: !root.locked && saved.currentIndex >= 0; onClicked: root.edit("ditto_creator_pack", saved.currentValue) }
            }
            NCLiveControlsGroup {
                visible: root.showAdvanced
                Layout.fillWidth: true
                title: qsTr("Advanced settings")
                description: qsTr("The defaults work for most avatars. These controls are optional.")
                controls: root.advancedControls()
                onControlEdited: (key,value) => root.edit(key,value)
                onActionTriggered: key => root.action(key)
                onActionWithPayload: (key,payload) => root.bridge.triggerLiveAddonActionWithPayload(key,payload)
                onRefreshRequested: root.bridge.refreshLiveAddonControls()
            }
            Item { height: 24; Layout.fillWidth: true }
        }
    }
}
