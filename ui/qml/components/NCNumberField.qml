import QtQuick
import QtQuick.Controls
import "../theme" as Theme

NCTextField {
    id: root

    property real minimum: -1000000000
    property real maximum: 1000000000
    property real stepSize: 0.05
    rightPadding: Theme.NCMetrics.controlHeight + Theme.NCMetrics.space4
    inputMethodHints: Qt.ImhFormattedNumbersOnly
    validator: DoubleValidator {
        // Display and save use JS/Python decimal points, not the OS separator.
        locale: "C"
        bottom: root.minimum
        top: root.maximum
        notation: DoubleValidator.StandardNotation
    }

    function step(direction) {
        if (readOnly || !acceptableInput || !isFinite(Number(text)))
            return
        const next = Math.max(minimum, Math.min(maximum,
            Number((Number(text) + direction * stepSize).toPrecision(15))))
        if (next === Number(text))
            return
        // Native text edits preserve the caller's text binding. Assigning
        // text here disconnects it from later avatar/provider value changes.
        remove(0, length)
        insert(0, String(next))
        editingFinished()
    }

    Column {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: Theme.NCMetrics.controlHeight
        Repeater {
            model: [1, -1]
            delegate: Button {
                required property int modelData
                objectName: modelData > 0 ? "increaseNumber" : "decreaseNumber"
                width: parent.width
                height: root.height / 2
                padding: 0
                focusPolicy: Qt.NoFocus
                hoverEnabled: true
                enabled: !root.readOnly && root.acceptableInput && isFinite(Number(root.text))
                         && (modelData > 0 ? Number(root.text) < root.maximum : Number(root.text) > root.minimum)
                Accessible.name: (modelData > 0 ? qsTr("Increase %1") : qsTr("Decrease %1")).arg(root.label)
                contentItem: Label {
                    text: modelData > 0 ? "+" : "−"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: enabled ? Theme.NCTheme.textSecondary : Theme.NCTheme.textMuted
                }
                background: Rectangle {
                    color: parent.down ? Theme.NCTheme.surfacePressed : parent.hovered ? Theme.NCTheme.surfaceRaised : "transparent"
                    border.color: Theme.NCTheme.borderSubtle
                }
                onClicked: root.step(modelData)
            }
        }
    }
}
