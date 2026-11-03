import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    property color selectedColor: "#31d5f4"
    // Keep full precision while editing; round to RGB only at the output boundary.
    property real hue: 0
    property real saturation: 0
    property real brightness: 1
    property bool emittingColor: false
    signal colorEdited(string value)
    spacing: 8

    function syncColor() {
        if (emittingColor)
            return
        if (selectedColor.hsvHue >= 0)
            hue = selectedColor.hsvHue
        saturation = selectedColor.hsvSaturation
        brightness = selectedColor.hsvValue
    }
    onSelectedColorChanged: syncColor()
    Component.onCompleted: syncColor()

    function edit(h, s, v) {
        hue = (h + 1) % 1
        saturation = Math.max(0, Math.min(1, s))
        brightness = Math.max(0, Math.min(1, v))
        emittingColor = true
        try {
            colorEdited(String(Qt.hsva(hue, saturation, brightness, 1)))
        } finally {
            emittingColor = false
        }
    }

    Item {
        id: wheel
        objectName: "appearanceColorWheel"
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: 208
        Layout.preferredHeight: 208
        activeFocusOnTab: true
        Accessible.role: Accessible.Slider
        Accessible.name: qsTr("Color wheel")
        NCHelp {
            target: wheel
            text: qsTr("Drag to choose hue around the wheel and saturation from center to edge. Left and Right change hue; Up and Down change saturation. Brightness is adjusted separately below.")
        }
        Accessible.description: qsTr("Left and right change hue. Up and down change saturation.")
        Keys.onLeftPressed: root.edit(root.hue - 1 / 360, root.saturation, root.brightness)
        Keys.onRightPressed: root.edit(root.hue + 1 / 360, root.saturation, root.brightness)
        Keys.onUpPressed: root.edit(root.hue, root.saturation + 0.02, root.brightness)
        Keys.onDownPressed: root.edit(root.hue, root.saturation - 0.02, root.brightness)

        Canvas {
            anchors.fill: parent
            onPaint: {
                const ctx = getContext("2d")
                const radius = width / 2 - 5
                ctx.reset()
                ctx.translate(width / 2, height / 2)
                for (let degree = 0; degree < 360; ++degree) {
                    const start = degree * Math.PI / 180
                    ctx.beginPath()
                    ctx.moveTo(0, 0)
                    ctx.arc(0, 0, radius, start, (degree + 1.5) * Math.PI / 180)
                    ctx.closePath()
                    ctx.fillStyle = Qt.hsva(degree / 360, 1, 1, 1)
                    ctx.fill()
                }
                const fade = ctx.createRadialGradient(0, 0, 0, 0, 0, radius)
                fade.addColorStop(0, "white")
                fade.addColorStop(1, "transparent")
                ctx.fillStyle = fade
                ctx.beginPath(); ctx.arc(0, 0, radius, 0, 2 * Math.PI); ctx.fill()
            }
        }
        Rectangle {
            anchors.centerIn: parent
            width: parent.width - 10; height: width; radius: width / 2
            color: "black"; opacity: 1 - root.brightness
        }
        Rectangle {
            width: 14; height: 14; radius: 7
            x: wheel.width / 2 + Math.cos(root.hue * Math.PI * 2) * root.saturation * (wheel.width / 2 - 5) - width / 2
            y: wheel.height / 2 + Math.sin(root.hue * Math.PI * 2) * root.saturation * (wheel.height / 2 - 5) - height / 2
            color: root.selectedColor
            border.color: Theme.NCTheme.readableText(root.selectedColor, "#ffffff")
            border.width: 3
        }
        Rectangle {
            anchors.fill: parent
            radius: width / 2; color: "transparent"
            border.width: wheel.activeFocus ? 2 : 0
            border.color: Theme.NCTheme.focus
        }
        MouseArea {
            anchors.fill: parent
            function pick(mouse) {
                const dx = mouse.x - width / 2, dy = mouse.y - height / 2
                root.edit(Math.atan2(dy, dx) / (2 * Math.PI),
                          Math.sqrt(dx * dx + dy * dy) / (width / 2 - 5), root.brightness)
            }
            onPressed: mouse => { wheel.forceActiveFocus(); pick(mouse) }
            onPositionChanged: mouse => { if (pressed) pick(mouse) }
        }
    }
    Label { text: qsTr("Brightness"); color: Theme.NCTheme.textSecondary }
    NCSlider {
        objectName: "appearanceBrightness"
        Layout.fillWidth: true
        label: qsTr("Color brightness")
        toolTipText: qsTr("Brightness of the selected color, from 0 to 1. Zero is black; 1 preserves full brightness for the current hue and saturation. This changes the color value rather than overlay opacity.")
        from: 0; to: 1; stepSize: 0.01
        value: root.brightness
        onMoved: root.edit(root.hue, root.saturation, value)
    }
    NCTextField {
        id: hexInput
        objectName: "appearanceHex"
        Layout.fillWidth: true
        text: String(root.selectedColor)
        Accessible.name: qsTr("Hex color")
        toolTipText: qsTr("Selected color in #RRGGBB hexadecimal format, such as #31D5F4. A complete valid value is applied when editing finishes; invalid input returns to the selected color.")
        placeholderText: "#31d5f4"
        maximumLength: 7
        validator: RegularExpressionValidator { regularExpression: /#[0-9a-fA-F]{6}/ }
        onActiveFocusChanged: {
            if (!activeFocus && !acceptableInput)
                text = Qt.binding(function() { return String(root.selectedColor) })
        }
        onEditingFinished: {
            if (acceptableInput)
                root.colorEdited(text.toLowerCase())
            text = Qt.binding(function() { return String(root.selectedColor) })
        }
    }
}
