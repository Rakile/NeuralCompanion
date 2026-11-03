pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as Theme

ColumnLayout {
    id: root

    property var field: ({})
    property bool showLabel: true
    property bool compact: false
    property real editorHeight: 132
    readonly property string controlId: String(field.id || "")
    readonly property string kind: String(field.type || "text")
    readonly property string labelText: String(field.label || "")
    readonly property string textValue: field.value === undefined ? "" : String(field.value)
    readonly property string helpText: String(field.toolTip || field.description || "")
    readonly property bool fieldEnabled: field.enabled !== false
    readonly property bool writable: fieldEnabled && !Boolean(field.readOnly)
    readonly property bool textEnabled: fieldEnabled || Boolean(field.editableWhileInactive)
    readonly property bool textWritable: textEnabled && !Boolean(field.readOnly)
    readonly property real controlHeight: compact ? Theme.NCMetrics.controlHeightCompact
                                                  : Theme.NCMetrics.controlHeight
    signal edited(string controlId, var value)
    signal previewed(string controlId, var value)
    signal actionRequested(var field)

    objectName: "mprcField_" + controlId
    visible: field.visible !== false
    spacing: Theme.NCMetrics.space4

    NCHelp {
        parent: editorLoader
        target: root
        focusTarget: editorLoader
        text: root.helpText
    }

    function optionIndex(options, wanted) {
        for (let index = 0; index < options.length; ++index) {
            if (String(options[index].value) === String(wanted))
                return index
        }
        return options.length ? 0 : -1
    }

    function commit(value) {
        if (writable && controlId)
            edited(controlId, value)
    }
    // Read current editor text as well as committed values when preparing a
    // complete Master builder request. Focus-loss persistence is asynchronous.
    function currentEditorValue() {
        const item = editorLoader.item
        if (!item) return field.value
        if (kind === "multiline") return item.draftText
        if (kind === "text") return item.text
        if (kind === "boolean") return item.checked
        if (kind === "choice") return item.currentValue
        if (kind === "integer") {
            const typed = item.contentItem && item.contentItem.text
            return typed === undefined ? item.value : Number(typed)
        }
        return field.value
    }

    Label {
        Layout.fillWidth: true
        visible: root.showLabel && root.labelText.length > 0
                 && root.kind !== "boolean" && root.kind !== "action"
        text: root.labelText
        color: Theme.NCTheme.textSecondary
        font.family: Theme.NCTypography.family
        font.pixelSize: Theme.NCTypography.captionSize
        elide: Text.ElideRight
    }

    Loader {
        id: editorLoader
        Layout.fillWidth: true
        Layout.preferredHeight: item ? item.implicitHeight : 0
        sourceComponent: {
            switch (root.kind) {
            case "boolean": return booleanEditor
            case "choice": return choiceEditor
            case "integer": return integerEditor
            case "slider": return sliderEditor
            case "multiline": return multilineEditor
            case "display": return displayEditor
            case "list": return listEditor
            case "image": return imageEditor
            case "progress": return progressEditor
            case "action": return actionEditor
            default: return textEditor
            }
        }
    }

    Component {
        id: booleanEditor
        NCCheckBox {
            helpDescription: String(root.field.toolTip || root.field.description || "")

            objectName: "mprcEditor_" + root.controlId
            implicitHeight: root.controlHeight
            enabled: root.writable
            text: root.labelText
            checked: Boolean(root.field.value)
            onClicked: root.commit(checked)
        }
    }

    Component {
        id: choiceEditor
        NCComboBox {
            helpDescription: String(root.field.toolTip || root.field.description || "")

            objectName: "mprcEditor_" + root.controlId
            implicitHeight: root.controlHeight
            enabled: root.writable
            label: root.labelText
            model: root.field.options || []
            textRole: "label"
            valueRole: "value"
            currentIndex: root.optionIndex(model, root.field.value)
            onActivated: root.commit(currentValue)
        }
    }

    Component {
        id: integerEditor
        NCSpinBox {
            helpDescription: String(root.field.toolTip || root.field.description || "")

            id: integerInput
            objectName: "mprcEditor_" + root.controlId
            implicitHeight: root.controlHeight
            enabled: root.writable
            label: root.labelText
            from: Number(root.field.minimum === undefined ? -2147483647 : root.field.minimum)
            to: Number(root.field.maximum === undefined ? 2147483647 : root.field.maximum)
            stepSize: Math.max(1, Number(root.field.step === undefined ? 1 : root.field.step))
            property string valueControlId: ""
            function syncValue() {
                const incomingId = String(root.field.id || "")
                if (valueControlId !== incomingId
                        || (!activeFocus && !contentItem.activeFocus)) {
                    valueControlId = incomingId
                    value = Number(root.field.value || 0)
                }
            }
            Component.onCompleted: syncValue()
            onValueModified: root.commit(value)
            Connections {
                target: root
                function onFieldChanged() { integerInput.syncValue() }
            }
        }
    }

    Component {
        id: sliderEditor
        RowLayout {
            spacing: Theme.NCMetrics.space8
            implicitHeight: root.controlHeight
            NCSlider {
                helpDescription: String(root.field.toolTip || root.field.description || "")

                id: sliderInput
                objectName: "mprcEditor_" + root.controlId
                Layout.fillWidth: true
                enabled: root.writable
                label: root.labelText
                from: Number(root.field.minimum === undefined ? 0 : root.field.minimum)
                to: Number(root.field.maximum === undefined ? 100 : root.field.maximum)
                stepSize: Math.max(1, Number(root.field.step === undefined ? 1 : root.field.step))
                property bool pendingEdit: false
                function syncValue() {
                    if (!pressed && !pendingEdit)
                        value = Number(root.field.value || 0)
                }
                function commitPending() {
                    if (pendingEdit) {
                        pendingEdit = false
                        root.commit(Math.round(value))
                    }
                }
                Component.onCompleted: syncValue()
                onMoved: {
                    if (!root.writable)
                        return
                    if (Boolean(root.field.deferredCommit)) {
                        pendingEdit = true
                        if (Boolean(root.field.livePreview))
                            root.previewed(root.controlId, Math.round(value))
                        if (!pressed)
                            commitPending()
                    } else {
                        root.commit(Math.round(value))
                    }
                }
                onPressedChanged: {
                    if (!pressed)
                        commitPending()
                }
                Connections {
                    target: root
                    function onFieldChanged() { sliderInput.syncValue() }
                }
            }
            Label {
                text: {
                    const scale = Math.max(1, Number(root.field.displayScale || 1))
                    return scale === 1 ? String(Math.round(sliderInput.value))
                                       : (sliderInput.value / scale).toFixed(
                                             Math.max(1, Math.min(3, Math.ceil(Math.log(scale) / Math.LN10))))
                }
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
                Layout.minimumWidth: 30
                horizontalAlignment: Text.AlignRight
            }
        }
    }

    Component {
        id: textEditor
        NCTextField {
            helpDescription: String(root.field.toolTip || root.field.description || "")

            id: textInput
            objectName: "mprcEditor_" + root.controlId
            implicitHeight: root.controlHeight
            enabled: root.textEnabled
            readOnly: Boolean(root.field.readOnly)
            label: root.labelText
            placeholderText: String(root.field.placeholder || "")
            echoMode: Boolean(root.field.secret) ? TextInput.Password : TextInput.Normal
            validator: root.kind === "number" ? numberValidator : null
            property bool draftChanged: false
            property bool syncing: false
            property string draftControlId: ""
            function syncText() {
                const incomingId = String(root.field.id || "")
                if (draftControlId !== incomingId || !activeFocus) {
                    syncing = true
                    text = root.field.value === undefined ? "" : String(root.field.value)
                    draftControlId = incomingId
                    draftChanged = false
                    syncing = false
                }
            }
            Component.onCompleted: syncText()
            onTextEdited: {
                if (!syncing && root.textWritable)
                    draftChanged = true
            }
            onEditingFinished: {
                if (!draftChanged || !root.textWritable || !acceptableInput
                        || draftControlId !== root.controlId)
                    return
                const nextValue = root.kind === "number" ? Number(text) : text
                if (root.kind === "number" && !isFinite(nextValue))
                    return
                draftChanged = false
                root.edited(root.controlId, nextValue)
            }
            DoubleValidator {
                id: numberValidator
                bottom: root.field.minimum === undefined ? -Infinity : Number(root.field.minimum)
                top: root.field.maximum === undefined ? Infinity : Number(root.field.maximum)
                locale: "C"
            }
            Connections {
                target: root
                function onFieldChanged() { textInput.syncText() }
            }
        }
    }

    Component {
        id: multilineEditor
        ScrollView {
            id: multilineScroll
            objectName: "mprcScroll_" + root.controlId
            property alias draftText: multilineInput.text
            implicitHeight: Math.max(72, Number(root.field.editorPreferredHeight || root.editorHeight))
            contentWidth: availableWidth
            contentHeight: multilineInput.implicitHeight
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: root.controlId === "mprc_master_story_draft" ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
            NCTextArea {
                helpDescription: String(root.field.toolTip || root.field.description || "")

                id: multilineInput
                objectName: "mprcEditor_" + root.controlId
                width: multilineScroll.availableWidth
                implicitHeight: Math.max(multilineScroll.availableHeight, contentHeight + topPadding + bottomPadding)
                enabled: root.textEnabled
                readOnly: Boolean(root.field.readOnly)
                label: root.labelText
                placeholderText: String(root.field.placeholder || "")
                property bool draftChanged: false
                property bool syncing: false
                property string draftControlId: ""
                function syncText() {
                    const incomingId = String(root.field.id || "")
                    if (draftControlId !== incomingId || !activeFocus) {
                        syncing = true
                        text = root.field.value === undefined ? "" : String(root.field.value)
                        draftControlId = incomingId
                        draftChanged = false
                        syncing = false
                    }
                }
                Component.onCompleted: syncText()
                onTextChanged: {
                    if (activeFocus && !syncing && root.textWritable)
                        draftChanged = true
                }
                onActiveFocusChanged: {
                    if (!activeFocus && draftChanged && root.textWritable
                            && draftControlId === root.controlId) {
                        draftChanged = false
                        root.edited(root.controlId, text)
                    }
                }
                Connections {
                    target: root
                    function onFieldChanged() { multilineInput.syncText() }
                }
            }
        }
    }

    Component {
        id: displayEditor
        Label {
            objectName: "mprcEditor_" + root.controlId
            text: root.textValue
            color: Theme.NCTheme.textSecondary
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.captionSize
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
        }
    }

    Component {
        id: listEditor
        ListView {
            id: optionList
            objectName: "mprcEditor_" + root.controlId
            implicitHeight: Math.min(190, Math.max(54, contentHeight + 2))
            model: root.field.options || []
            currentIndex: root.optionIndex(model, root.field.value)
            enabled: root.writable
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            function selectOption(index) {
                if (root.writable && index >= 0 && index < count) {
                    currentIndex = index
                    root.commit(model[index].value)
                }
            }
            Keys.onDownPressed: selectOption(Math.min(count - 1, currentIndex + 1))
            Keys.onUpPressed: selectOption(Math.max(0, currentIndex - 1))
            delegate: ItemDelegate {
                id: optionRow
                required property var modelData
                required property int index
                width: optionList.width
                height: Math.max(34, contentItem.implicitHeight + Theme.NCMetrics.space8)
                highlighted: index === optionList.currentIndex
                contentItem: Label {
                    text: String(optionRow.modelData.label || "")
                    color: Theme.NCTheme.text
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.captionSize
                    wrapMode: Text.Wrap
                }
                background: Rectangle {
                    radius: Theme.NCMetrics.radiusSmall
                    color: optionRow.highlighted ? Theme.NCTheme.surfaceSelected
                                                 : optionRow.hovered ? Theme.NCTheme.surfaceRaised : "transparent"
                }
                onClicked: optionList.selectOption(index)
            }
            Label {
                anchors.centerIn: parent
                visible: optionList.count === 0
                text: qsTr("No items")
                color: Theme.NCTheme.textMuted
            }
        }
    }

    Component {
        id: imageEditor
        Rectangle {
            objectName: "mprcEditor_" + root.controlId
            implicitWidth: Number(root.field.imagePreferredWidth || 240)
            implicitHeight: Number(root.field.imagePreferredHeight || 180)
            radius: Theme.NCMetrics.radiusMedium
            color: Theme.NCTheme.windowRaised
            border.color: Theme.NCTheme.border
            Image {
                id: previewImage
                anchors.fill: parent
                anchors.margins: Theme.NCMetrics.space4
                source: root.textValue
                asynchronous: true
                cache: false
                fillMode: Image.PreserveAspectFit
                sourceSize.width: 512
                sourceSize.height: 512
            }
            Label {
                anchors.centerIn: parent
                width: parent.width - Theme.NCMetrics.space16
                visible: previewImage.status !== Image.Ready
                text: String(root.field.imagePlaceholder || qsTr("No preview available"))
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }
        }
    }

    Component {
        id: progressEditor
        NCProgressBar {
            objectName: "mprcEditor_" + root.controlId
            implicitHeight: root.controlHeight
            from: Number(root.field.minimum === undefined ? 0 : root.field.minimum)
            to: Number(root.field.maximum === undefined ? 100 : root.field.maximum)
            value: Number(root.field.value || 0)
        }
    }

    Component {
        id: actionEditor
        NCButton {
            objectName: "mprcEditor_" + root.controlId
            enabled: root.writable
            compact: root.compact
            text: root.labelText || qsTr("Run action")
            tone: Boolean(root.field.destructive) ? "danger" : "secondary"
            toolTipText: String(root.field.toolTip || root.field.tooltip || root.field.description || "")
            onClicked: {
                if (root.writable)
                    root.actionRequested(root.field)
            }
        }
    }
}
