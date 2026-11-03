pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root

    property var schema: []
    property var values: ({})
    property bool readOnly: false
    signal settingEdited(string key, var value)

    function currentValue(field) {
        const key = String(field.key || "")
        if (values && values[key] !== undefined)
            return values[key]
        return field.defaultValue !== undefined ? field.defaultValue : ""
    }

    function optionIndex(options, wanted) {
        for (let index = 0; index < options.length; ++index) {
            const option = options[index]
            const value = typeof option === "object" ? option.value : option
            if (String(value) === String(wanted))
                return index
        }
        return options.length > 0 ? 0 : -1
    }

    Repeater {
        model: root.schema

        delegate: Rectangle {
            id: settingRow
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: Math.max(54, rowLayout.implicitHeight + Theme.NCMetrics.space12)
            color: "transparent"
            Accessible.description: String(modelData.toolTip || modelData.description || "")
            NCHelp {
                target: settingRow
                focusTarget: settingEditor
                text: String(settingRow.modelData.toolTip || settingRow.modelData.description || "")
            }

            RowLayout {
                id: rowLayout
                anchors.fill: parent
                anchors.topMargin: Theme.NCMetrics.space6
                anchors.bottomMargin: Theme.NCMetrics.space6
                spacing: Theme.NCMetrics.space16

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space2
                    Label {
                        Layout.fillWidth: true
                        text: String(settingRow.modelData.label || settingRow.modelData.key || "")
                        color: Theme.NCTheme.text
                        font.pixelSize: Theme.NCTypography.labelSize
                        font.weight: Theme.NCTypography.medium
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: String(settingRow.modelData.description || "").length > 0
                        text: String(settingRow.modelData.description || "")
                        color: Theme.NCTheme.textMuted
                        font.pixelSize: Theme.NCTypography.captionSize
                        wrapMode: Text.Wrap
                    }
                }

                Loader {
                    id: settingEditor
                    property var field: settingRow.modelData
                    Layout.preferredWidth: Math.min(340, Math.max(220, settingRow.width * 0.38))
                    sourceComponent: {
                        const kind = String(settingRow.modelData.type || "text")
                        if (kind === "boolean") return booleanEditor
                        if (kind === "choice") return choiceEditor
                        if (kind === "integer") return integerEditor
                        if (kind === "number") return numberEditor
                        if (kind === "multiline") return multilineEditor
                        return textEditor
                    }
                    onLoaded: item.field = field
                }
            }
        }
    }

    Component {
        id: booleanEditor
        NCSwitch {
            helpDescription: String(field.toolTip || field.description || "")

            property var field: ({})
            enabled: !root.readOnly
            text: checked ? qsTr("On") : qsTr("Off")
            checked: Boolean(root.currentValue(field))
            onClicked: root.settingEdited(String(field.key), checked)
        }
    }

    Component {
        id: choiceEditor
        NCComboBox {
            helpDescription: String(field.toolTip || field.description || "")

            property var field: ({})
            enabled: !root.readOnly
            label: String(field.label || field.key)
            model: field.options || []
            textRole: model.length > 0 && typeof model[0] === "object" ? "label" : ""
            valueRole: model.length > 0 && typeof model[0] === "object" ? "value" : ""
            currentIndex: root.optionIndex(model, root.currentValue(field))
            onActivated: root.settingEdited(
                String(field.key),
                valueRole.length > 0 ? currentValue : currentText
            )
        }
    }

    Component {
        id: integerEditor
        NCSpinBox {
            helpDescription: String(field.toolTip || field.description || "")

            property var field: ({})
            enabled: !root.readOnly
            label: String(field.label || field.key)
            from: Number(field.minimum === undefined ? -2147483647 : field.minimum)
            to: Number(field.maximum === undefined ? 2147483647 : field.maximum)
            stepSize: Math.max(1, Number(field.step === undefined ? 1 : field.step))
            value: Number(root.currentValue(field) || 0)
            onValueModified: root.settingEdited(String(field.key), value)
        }
    }

    Component {
        id: numberEditor
        NCNumberField {
            helpDescription: String(field.toolTip || field.description || "")

            property var field: ({})
            enabled: !root.readOnly
            label: String(field.label || field.key)
            text: String(root.currentValue(field))
            minimum: Number(field.minimum === undefined ? -1000000000 : field.minimum)
            maximum: Number(field.maximum === undefined ? 1000000000 : field.maximum)
            stepSize: /(?:^|_)(temperature|repetition_penalty|repeat_penalty|min_p)$/.test(String(field.key))
                      ? 0.05 : Number(field.step === undefined ? 0.01 : field.step)
            onEditingFinished: {
                if (!root.readOnly && acceptableInput && isFinite(Number(text)))
                    root.settingEdited(String(field.key), Number(text))
            }
        }
    }

    Component {
        id: textEditor
        NCTextField {
            helpDescription: String(field.toolTip || field.description || "")

            property var field: ({})
            enabled: !root.readOnly
            label: String(field.label || field.key)
            text: String(root.currentValue(field))
            echoMode: Boolean(field.secret) ? TextInput.Password : TextInput.Normal
            validator: {
                const kind = String(field.type || "text")
                if (kind === "integer")
                    return integerValidator
                if (kind === "number")
                    return numberValidator
                return null
            }
            onEditingFinished: {
                const kind = String(field.type || "text")
                let nextValue = text
                if (kind === "integer")
                    nextValue = parseInt(text)
                else if (kind === "number")
                    nextValue = Number(text)
                if (kind === "number" && (!acceptableInput || !isFinite(nextValue)))
                    return
                root.settingEdited(String(field.key), nextValue)
            }
        }
    }

    Component {
        id: multilineEditor
        NCScrollableTextArea {
            helpDescription: String(field.toolTip || field.description || "")

            property var field: ({})
            readOnly: root.readOnly
            label: String(field.label || field.key)
            text: String(root.currentValue(field))
            implicitHeight: Number(field.height || 120)
            onEditingFinished: root.settingEdited(String(field.key), text)
        }
    }

    IntValidator {
        id: integerValidator
        bottom: -2147483647
        top: 2147483647
    }

    DoubleValidator {
        id: numberValidator
        locale: "C"
        bottom: -1000000000
        top: 1000000000
        notation: DoubleValidator.StandardNotation
    }
}
