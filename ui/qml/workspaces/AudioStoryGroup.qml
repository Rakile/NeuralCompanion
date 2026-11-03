pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "AudioStoryLayout.js" as LayoutMap

MprcPanel {
    id: root

    property var group: ({})
    property var controls: []
    property string sectionName: ""
    signal edited(string controlId, var value)
    signal previewed(string controlId, var value)
    signal actionRequested(var field)

    objectName: "audioStoryGroup_" + String(group.key || "")
    title: String(group.title || "")
    description: String(group.description || "")
    foldable: Boolean(group.fold)
    expanded: group.expanded !== false

    function fieldAt(index) {
        const wanted = (root.group.ids || [])[index]
        for (let n = 0; n < root.controls.length; ++n) {
            if (String(root.controls[n].id || "") === String(wanted || "")) {
                const result = Object.assign({}, root.controls[n])
                result.label = LayoutMap.label(result)
                result.value = LayoutMap.value(result)
                return result
            }
        }
        return ({})
    }

    GridLayout {
        id: fields
        Layout.fillWidth: true
        columns: width >= Number(root.group.twoColumnMinimum || 560)
                 ? Number(root.group.columns || 1) : 1
        columnSpacing: 14
        rowSpacing: 10

        Repeater {
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
                Layout.columnSpan: ["multiline", "list", "display", "image", "progress"].indexOf(String(field.type)) >= 0
                                   ? fields.columns : 1
                onEdited: (controlId, value) => root.edited(controlId, value)
                onPreviewed: (controlId, value) => root.previewed(controlId, value)
                onActionRequested: field => root.actionRequested(field)
            }
        }
    }
}
