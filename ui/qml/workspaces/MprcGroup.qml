pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "MprcLayout.js" as LayoutMap

MprcPanel {
    id: root
    property var group: ({})
    property var controls: []
    property Component footerComponent: null
    signal edited(string controlId, var value)
    signal previewed(string controlId, var value)
    signal actionRequested(var field)
    objectName: "mprcGroup_" + String(group.key || "")
    title: String(group.title || "")
    foldable: Boolean(group.fold)
    expanded: group.expanded !== false

    function fieldAt(index) {
        const wanted = (root.group.ids || [])[index]
        for (let n = 0; n < root.controls.length; ++n) {
            if (root.controls[n].id === wanted) {
                const result = Object.assign({}, root.controls[n])
                result.label = LayoutMap.label(result)
                return result
            }
        }
        return ({})
    }
    function editorValues(committed) {
        const result = {}
        for (let index = 0; index < fieldRepeater.count; ++index) {
            const editor = fieldRepeater.itemAt(index)
            if (editor && editor.field.type !== "action")
                result[editor.controlId] = committed ? editor.field.value : editor.currentEditorValue()
        }
        return result
    }

    GridLayout {
        id: fields
        Layout.fillWidth: true
        columns: width >= Number(root.group.twoColumnMinimum || 560) ? Number(root.group.columns || 1) : 1
        columnSpacing: 14
        rowSpacing: 10
        Repeater {
            id: fieldRepeater
            model: (root.group.ids || []).length
            delegate: MprcField {
                id: cell
                required property int index
                field: root.fieldAt(index)
                visible: Boolean(field.id) && field.visible !== false
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                Layout.columnSpan: ["multiline", "list", "display", "image", "progress"].indexOf(String(field.type)) >= 0 ? fields.columns : 1
                onEdited: (controlId, value) => root.edited(controlId, value)
                onPreviewed: (controlId, value) => root.previewed(controlId, value)
                onActionRequested: field => root.actionRequested(field)
            }
        }
    }
    Loader {
        Layout.fillWidth: true
        active: root.footerComponent !== null
        sourceComponent: root.footerComponent
    }
}
