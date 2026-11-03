pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCComboBox {
    id: root
    property var options: []
    property var selectedValue: ""
    property string selectionLabel: ""
    property string searchText: ""
    readonly property var filteredOptions: options.filter(function(option) {
        const query = root.searchText.trim().toLowerCase()
        return String(option.label).toLowerCase().includes(query)
            || String(option.value).toLowerCase().includes(query)
    })
    signal valueChosen(var value)

    model: options
    textRole: "label"
    valueRole: "value"
    currentIndex: options.findIndex(function(option) { return String(option.value) === String(root.selectedValue) })
    displayText: selectionLabel
    onActivated: {
        if (String(currentValue || "") !== "") valueChosen(currentValue)
    }
    popup: Popup {
        y: root.height + Theme.NCMetrics.space4
        width: root.width
        height: Math.min(320, 60 + root.filteredOptions.length * Theme.NCMetrics.controlHeight)
        padding: Theme.NCMetrics.space4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        onOpened: {
            root.searchText = ""
            search.forceActiveFocus()
        }
        background: Rectangle {
            color: Theme.NCTheme.surface
            radius: Theme.NCMetrics.radiusMedium
            border.color: Theme.NCTheme.borderStrong
        }
        contentItem: ColumnLayout {
            spacing: Theme.NCMetrics.space4
            TextField {
                id: search
                Layout.fillWidth: true
                placeholderText: "Search vision models"
                text: root.searchText
                onTextEdited: root.searchText = text
                Keys.onDownPressed: results.forceActiveFocus()
            }
            ListView {
                id: results
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: root.filteredOptions
                currentIndex: 0
                ScrollIndicator.vertical: ScrollIndicator { }
                Keys.onReturnPressed: {
                    if (currentItem && currentItem.enabled) currentItem.clicked()
                }
                delegate: ItemDelegate {
                    id: option
                    required property var modelData
                    required property int index
                    width: results.width
                    height: Theme.NCMetrics.controlHeight
                    enabled: String(modelData.value) !== ""
                    highlighted: results.currentIndex === index
                    text: String(modelData.label)
                    onClicked: {
                        root.valueChosen(modelData.value)
                        root.popup.close()
                    }
                }
            }
        }
    }
}
