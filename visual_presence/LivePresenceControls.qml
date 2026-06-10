import QtQuick 2.15

Item {
    id: panel

    property var presenceBridge
    property bool expanded: true

    width: expanded ? 292 : 172
    height: expanded ? contentColumn.implicitHeight + 18 : 38
    opacity: visible ? 0.96 : 0.0
    visible: presenceBridge ? presenceBridge.liveControlsVisible : false

    Behavior on opacity { NumberAnimation { duration: 140 } }

    function clamp(value, minValue, maxValue) {
        return Math.max(minValue, Math.min(maxValue, Number(value) || 0))
    }

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: "#101c2bcc"
        border.color: "#3b5f82"
        border.width: 1
    }

    Column {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 9
        spacing: 7

        Row {
            width: parent.width
            height: 22
            spacing: 8

            Text {
                width: parent.width - 54
                text: "Live Visual Controls"
                color: "#e5f6ff"
                font.pixelSize: 12
                font.bold: true
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }

            Text {
                width: 18
                text: panel.expanded ? "-" : "+"
                color: "#8bd7ff"
                font.pixelSize: 16
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                MouseArea {
                    anchors.fill: parent
                    onClicked: panel.expanded = !panel.expanded
                }
            }

            Text {
                width: 18
                text: "x"
                color: "#fb7185"
                font.pixelSize: 15
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                MouseArea {
                    anchors.fill: parent
                    onClicked: if (presenceBridge) presenceBridge.setLiveControlsVisible(false)
                }
            }
        }

        Column {
            visible: panel.expanded
            width: parent.width
            spacing: 5

            PresenceSlider { label: "Opacity"; settingKey: "ai_presence_overlay_opacity"; value: presenceBridge ? presenceBridge.overlayOpacity : 0.72; minValue: 0.10; maxValue: 1.0; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Pulse"; settingKey: "ai_presence_thinking_pulse"; value: presenceBridge ? presenceBridge.pulseIntensity : 0.55; minValue: 0.10; maxValue: 1.0; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Voice"; settingKey: "ai_presence_speaking_reactivity"; value: presenceBridge ? presenceBridge.speakingReactivity : 0.85; minValue: 0.10; maxValue: 1.5; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Glow"; settingKey: "ai_presence_glow_strength"; value: presenceBridge ? presenceBridge.glowStrength : 1.0; minValue: 0.0; maxValue: 1.75; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Speed"; settingKey: "ai_presence_animation_speed"; value: presenceBridge ? presenceBridge.animationSpeed : 1.0; minValue: 0.35; maxValue: 1.75; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Mood"; settingKey: "ai_presence_mood_color_intensity"; value: presenceBridge ? presenceBridge.moodColorIntensity : 0.85; minValue: 0.0; maxValue: 1.0; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Primary"; settingKey: "ai_presence_primary_color_strength"; value: presenceBridge ? presenceBridge.primaryColorStrength : 1.0; minValue: 0.0; maxValue: 1.5; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Secondary"; settingKey: "ai_presence_secondary_color_strength"; value: presenceBridge ? presenceBridge.secondaryColorStrength : 1.0; minValue: 0.0; maxValue: 1.5; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Background"; settingKey: "ai_presence_background_darkness"; value: presenceBridge ? presenceBridge.backgroundDarkness : 1.0; minValue: 0.0; maxValue: 1.0; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Particles"; settingKey: "ai_presence_particle_density"; value: presenceBridge ? presenceBridge.particleDensity : 28; minValue: 0; maxValue: 120; presenceBridge: panel.presenceBridge; integerValue: true }
            PresenceSlider { label: "Nodes"; settingKey: "ai_presence_node_density"; value: presenceBridge ? presenceBridge.nodeDensity : 32; minValue: 8; maxValue: 96; presenceBridge: panel.presenceBridge; integerValue: true }
            PresenceSlider { label: "Halo"; settingKey: "ai_presence_halo_thickness"; value: presenceBridge ? presenceBridge.haloThickness : 1.0; minValue: 0.35; maxValue: 2.0; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Waveform"; settingKey: "ai_presence_waveform_strength"; value: presenceBridge ? presenceBridge.waveformStrength : 1.0; minValue: 0.2; maxValue: 2.0; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Rings"; settingKey: "ai_presence_ring_expansion_speed"; value: presenceBridge ? presenceBridge.ringExpansionSpeed : 1.0; minValue: 0.25; maxValue: 2.0; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Softness"; settingKey: "ai_presence_blur_softness"; value: presenceBridge ? presenceBridge.blurSoftness : 0.35; minValue: 0.0; maxValue: 1.0; presenceBridge: panel.presenceBridge }
            PresenceSlider { label: "Lines"; settingKey: "ai_presence_line_brightness"; value: presenceBridge ? presenceBridge.lineBrightness : 1.0; minValue: 0.2; maxValue: 2.0; presenceBridge: panel.presenceBridge }

            Row {
                width: parent.width
                spacing: 5
                PresenceToggle { label: "Reduced"; settingKey: "ai_presence_reduced_effects"; value: presenceBridge ? presenceBridge.reducedEffects : false; presenceBridge: panel.presenceBridge }
                PresenceToggle { label: "Particles"; settingKey: "ai_presence_particles_enabled"; value: presenceBridge ? presenceBridge.particlesEnabled : true; presenceBridge: panel.presenceBridge }
                PresenceToggle { label: "Glow FX"; settingKey: "ai_presence_shaders_enabled"; value: presenceBridge ? presenceBridge.shadersEnabled : true; presenceBridge: panel.presenceBridge }
            }

            Text {
                width: parent.width
                text: "H toggles controls. Space exits fullscreen."
                color: "#8ea3b8"
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }
    }

    component PresenceSlider: Item {
        property var presenceBridge
        property string label: ""
        property string settingKey: ""
        property real value: 0.0
        property real minValue: 0.0
        property real maxValue: 1.0
        property bool integerValue: false

        width: parent ? parent.width : 260
        height: 21

        function ratio() {
            return panel.clamp((value - minValue) / Math.max(0.0001, maxValue - minValue), 0, 1)
        }

        function setFromX(x) {
            var next = minValue + panel.clamp(x / Math.max(1, track.width), 0, 1) * (maxValue - minValue)
            if (integerValue) {
                next = Math.round(next)
            }
            if (presenceBridge) {
                presenceBridge.setNumericSetting(settingKey, next)
            }
        }

        Text {
            id: sliderLabel
            width: 74
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: label
            color: "#dbeafe"
            font.pixelSize: 10
            elide: Text.ElideRight
        }

        Rectangle {
            id: track
            anchors.left: sliderLabel.right
            anchors.right: valueText.left
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 7
            anchors.rightMargin: 7
            height: 8
            radius: 4
            color: "#0b1320"
            border.color: "#2b4c6d"

            Rectangle {
                width: track.width * ratio()
                height: parent.height
                radius: parent.radius
                color: "#38bdf8"
                opacity: 0.78
            }

            Rectangle {
                x: Math.max(0, Math.min(track.width - width, track.width * ratio() - width * 0.5))
                y: -3
                width: 14
                height: 14
                radius: 7
                color: "#e0f2fe"
                border.color: "#38bdf8"
            }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                preventStealing: true
                onPressed: setFromX(mouse.x)
                onPositionChanged: if (pressed) setFromX(mouse.x)
            }
        }

        Text {
            id: valueText
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: 34
            text: integerValue ? String(Math.round(value)) : Number(value).toFixed(2)
            color: "#93c5fd"
            font.pixelSize: 9
            horizontalAlignment: Text.AlignRight
        }
    }

    component PresenceToggle: Rectangle {
        property var presenceBridge
        property string label: ""
        property string settingKey: ""
        property bool value: false

        width: 86
        height: 23
        radius: 5
        color: value ? "#123f3d" : "#111827"
        border.color: value ? "#22d3ee" : "#334155"

        Text {
            anchors.centerIn: parent
            text: label
            color: value ? "#ccfbf1" : "#cbd5e1"
            font.pixelSize: 10
        }

        MouseArea {
            anchors.fill: parent
            onClicked: if (presenceBridge) presenceBridge.setBooleanSetting(settingKey, !value)
        }
    }
}
