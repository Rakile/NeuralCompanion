pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root

    required property var bridge
    property var control: ({})
    property var headers: []
    property var columnWidths: []
    property string selectedValue: ""
    property string tableObjectName: ""
    property string flickObjectName: ""
    property string rowObjectPrefix: ""
    readonly property int columnCount: headers.length
    readonly property var rows: control.rows || []
    readonly property real tableWidth: {
        let total = 0
        for (let index = 0; index < columnWidths.length; ++index)
            total += Number(columnWidths[index])
        return total
    }

    objectName: tableObjectName
    spacing: 0

    function rowValueAt(index) {
        return index >= 0 && index < rows.length ? String(rows[index].value || "") : ""
    }

    function containsValue(value) {
        const wanted = String(value || "")
        for (let index = 0; index < rows.length; ++index) {
            if (rowValueAt(index) === wanted)
                return true
        }
        return false
    }

    function reconcileSelection() {
        selectedValue = containsValue(control.value) ? String(control.value || "") : ""
    }

    function activateRow(index) {
        const value = rowValueAt(index)
        if (!Boolean(control.enabled) || value.length === 0)
            return
        selectedValue = value
        bridge.setLiveAddonControl(String(control.id || ""), value)
    }

    onControlChanged: reconcileSelection()
    Component.onCompleted: reconcileSelection()

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 34
        color: Theme.NCTheme.windowRaised
        border.color: Theme.NCTheme.border
        radius: Theme.NCMetrics.radiusSmall

        Flickable {
            id: tableFlick
            objectName: root.flickObjectName + "Header"
            anchors.fill: parent
            contentWidth: Math.max(width, root.tableWidth)
            contentHeight: height
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            interactive: false
            contentX: bodyFlick.contentX

            Row {
                height: parent.height
                Repeater {
                    model: root.headers.length
                    delegate: Label {
                        id: headerCell
                        required property int index
                        width: Number(root.columnWidths[index] || 120)
                        height: parent.height
                        leftPadding: Theme.NCMetrics.space8
                        rightPadding: Theme.NCMetrics.space8
                        text: String(root.headers[index] || "")
                        color: Theme.NCTheme.textSecondary
                        font.family: Theme.NCTypography.family
                        font.pixelSize: Theme.NCTypography.microSize
                        font.weight: Theme.NCTypography.semibold
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }

    Flickable {
        id: bodyFlick
        objectName: root.flickObjectName
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(214, Math.max(48, bodyColumn.implicitHeight))
        contentWidth: Math.max(width, root.tableWidth)
        contentHeight: bodyColumn.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: bodyColumn
            width: Math.max(bodyFlick.width, root.tableWidth)

            Repeater {
                model: root.rows.length

                delegate: Rectangle {
                    id: dataRow
                    required property int index
                    readonly property var rowData: root.rows[index] || ({})
                    signal clicked()

                    objectName: root.rowObjectPrefix + dataRow.index
                    width: bodyColumn.width
                    height: 38
                    color: root.selectedValue === root.rowValueAt(dataRow.index)
                           ? Theme.NCTheme.surfaceSelected
                           : dataRow.index % 2 === 0 ? Theme.NCTheme.surface : Theme.NCTheme.windowRaised
                    border.color: root.selectedValue === root.rowValueAt(dataRow.index)
                                  ? Theme.NCTheme.accent : Theme.NCTheme.borderSubtle

                    onClicked: {
                        root.activateRow(dataRow.index)
                    }

                    Row {
                        anchors.fill: parent
                        Repeater {
                            model: root.headers.length
                            delegate: Label {
                                id: dataCell
                                required property int index
                                width: Number(root.columnWidths[index] || 120)
                                height: dataRow.height
                                leftPadding: Theme.NCMetrics.space8
                                rightPadding: Theme.NCMetrics.space8
                                text: String((dataRow.rowData.cells || [])[dataCell.index] || "")
                                color: Boolean(root.control.enabled) ? Theme.NCTheme.text : Theme.NCTheme.textMuted
                                font.family: Theme.NCTypography.family
                                font.pixelSize: Theme.NCTypography.captionSize
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }
                        }
                    }

                    TapHandler {
                        enabled: Boolean(root.control.enabled)
                        onTapped: dataRow.clicked()
                    }
                }
            }
        }
    }
}
