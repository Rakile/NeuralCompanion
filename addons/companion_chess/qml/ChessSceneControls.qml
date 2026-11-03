import QtQuick

import QtQuick.Controls

import QtQuick.Layouts

import "../../../ui/qml/components" as NC

import "../../../ui/qml/theme" as Theme

import "BoardModels.js" as BoardModels



ColumnLayout {

    id: root

    required property var workspace

    objectName: "chessSceneControls"

    spacing: Theme.NCMetrics.space10

    ChessLabel { text: "Board & atmosphere"; color: Theme.NCTheme.text; font.weight: Font.DemiBold }

    ChessLabel { text: "Board model" }

    NC.NCComboBox {

        objectName: "chessBoardModel"

        Layout.fillWidth: true; label: "Board model"

        model: BoardModels.labels

        currentIndex: BoardModels.index(root.workspace.boardModel)

        onActivated: if (currentIndex >= 0 && currentIndex < BoardModels.keys.length) root.workspace.setting("board_model", BoardModels.keys[currentIndex])

    }

    ChessLabel { text: "Piece style" }

    NC.NCComboBox {

        objectName: "chessStyle"

        Layout.fillWidth: true; label: "Piece style"

        model: ["Classic", "Modern", "Fantasy"]

        currentIndex: ["classic", "modern", "fantasy"].indexOf(root.workspace.styleName)

        onActivated: root.workspace.setting("style", ["classic", "modern", "fantasy"][currentIndex])

    }

    ChessLabel {

        Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize

        text: "Piece materials and lighting remain independent of the board model. Reduced detail uses the lightweight pieces."

    }

    ColumnLayout {

        Layout.fillWidth: true

        visible: root.workspace.boardModel !== "style"

        property real level: root.workspace.light.led_brightness === undefined ? .55 : root.workspace.light.led_brightness

        RowLayout {

            Layout.fillWidth: true

            ChessLabel { Layout.fillWidth: true; text: "LED brightness" }

            ChessLabel { text: Math.round(parent.parent.level * 100) + "%" }

        }

        NC.NCSlider {

            objectName: "chessLedBrightness"; Layout.fillWidth: true; label: "LED brightness"

            from: 0; to: 1; stepSize: .01; value: parent.level

            onMoved: root.workspace.changeLight("led_brightness", value)

        }

        RowLayout {

            NC.NCButton { text: "Low"; onClicked: root.workspace.changeLight("led_brightness", .15) }

            NC.NCButton { text: "Soft"; onClicked: root.workspace.changeLight("led_brightness", .55) }

            NC.NCButton { text: "Full"; onClicked: root.workspace.changeLight("led_brightness", 1) }

        }

        ChessLabel {

            Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize

            text: "Frosted rubber pads. Adjust their light independently from the spotlight; light spill onto pieces follows this level."

        }

    }

    ChessPaletteControls { Layout.fillWidth: true; workspace: root.workspace }

    ChessLabel { text: "Lighting" }

    NC.NCComboBox {

        objectName: "chessLightPreset"

        Layout.fillWidth: true; label: "Lighting preset"

        model: ["Board spotlight", "Warm study", "Studio", "Moonlight"]

        currentIndex: ["spotlight", "study", "studio", "moon"].indexOf(root.workspace.light.preset)

        onActivated: root.workspace.changeLight("preset", ["spotlight", "study", "studio", "moon"][currentIndex])

    }

    ChessLabel {

        Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize

        text: root.workspace.light.preset === "spotlight" ? "Only the board and pieces are lit. Surroundings stay dark." : "The table or natural ground is visible in this lighting."

    }

    Repeater {

        model: [{key:"brightness",label:"Brightness",min:0,max:4,step:.05},{key:"warmth",label:"Warmth",min:0,max:1,step:.01},

            {key:"azimuth",label:"Light direction",min:-180,max:180,step:1},{key:"elevation",label:"Light elevation",min:15,max:90,step:1},

            {key:"fill",label:"Fill light",min:0,max:1,step:.01}]

        ColumnLayout {

            id: lightRow

            required property var modelData

            Layout.fillWidth: true; spacing: 0

            visible: modelData.key !== "fill" || root.workspace.light.preset !== "spotlight"

            RowLayout {

                Layout.fillWidth: true

                ChessLabel { Layout.fillWidth: true; text: lightRow.modelData.label }

                ChessLabel { text: Number(root.workspace.light[lightRow.modelData.key]).toFixed(lightRow.modelData.step < 1 ? 2 : 0) }

            }

            NC.NCSlider {

                Layout.fillWidth: true; label: lightRow.modelData.label

                from: lightRow.modelData.min; to: lightRow.modelData.max; stepSize: lightRow.modelData.step

                value: Number(root.workspace.light[lightRow.modelData.key])

                onMoved: root.workspace.changeLight(lightRow.modelData.key, value)

            }

        }

    }

    NC.NCSwitch { Layout.fillWidth: true; text: "Soft shadows"; checked: root.workspace.light.shadows !== false; onToggled: root.workspace.changeLight("shadows", checked) }

    ChessLabel { text: "Atmosphere"; color: Theme.NCTheme.text; font.weight: Font.DemiBold }

    NC.NCSwitch { objectName: "chessDustToggle"; Layout.fillWidth: true; text: "Drifting dust motes"; checked: root.workspace.light.dust !== false; onToggled: root.workspace.changeLight("dust", checked) }

    NC.NCSwitch { objectName: "chessAOToggle"; Layout.fillWidth: true; text: "Ambient occlusion"; checked: root.workspace.light.ambient_occlusion !== false; onToggled: root.workspace.changeLight("ambient_occlusion", checked) }

    NC.NCSwitch { objectName: "chessGlowToggle"; Layout.fillWidth: true; text: "Soft LED glow"; checked: root.workspace.light.glow !== false; onToggled: root.workspace.changeLight("glow", checked) }

    NC.NCSwitch {

        objectName: "chessReflectionsToggle"; Layout.fillWidth: true; text: "Screen-space reflections"

        checked: root.workspace.light.reflections === true

        enabled: root.workspace.light.depth_of_field !== true && root.workspace.light.tilt_shift !== true

        onToggled: if (enabled) root.workspace.changeLight("reflections", checked)

    }

    ChessLabel {

        Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize

        text: root.workspace.light.depth_of_field === true || root.workspace.light.tilt_shift === true

            ? "Reflections pause while depth of field or tilt-shift is enabled. Your saved reflection setting resumes when both are off."

            : "Reflections use visible scene geometry, not hardware ray tracing (Qt 6.11+). Atmosphere effects pause in reduced detail; dust also pauses when the board is hidden."

    }

    ChessLabel { text: "Rendering & movement"; color: Theme.NCTheme.text; font.weight: Font.DemiBold }

    NC.NCComboBox {

        objectName: "chessAntialiasing"

        Layout.fillWidth: true; label: "Antialiasing"

        model: ["Antialiasing off", "MSAA 2×", "MSAA 4× (recommended)", "MSAA 8×", "Supersampling 1.5× (GPU intensive)"]

        currentIndex: Math.max(0, ["off","msaa2","msaa4","msaa8","ssaa"].indexOf(root.workspace.light.antialiasing || "msaa4"))

        onActivated: root.workspace.changeLight("antialiasing", ["off","msaa2","msaa4","msaa8","ssaa"][currentIndex])

    }

    NC.NCSwitch { objectName: "chessDOFToggle"; Layout.fillWidth: true; text: "Depth of field"; checked: root.workspace.light.depth_of_field === true; onToggled: root.workspace.changeLight("depth_of_field", checked) }

    ChessLabel { Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize; text: "Focus follows the board centre as you zoom. Supersampling and depth of field increase GPU load." }

    ChessLabel { text: "Background blur" }

    NC.NCSlider {

        objectName: "chessFocusBlur"; Layout.fillWidth: true; label: "Background blur"

        enabled: root.workspace.light.depth_of_field === true && !root.workspace.lowDetail

        from: 0; to: 6; stepSize: .1

        value: root.workspace.light.focus_blur === undefined ? 2.5 : root.workspace.light.focus_blur

        onMoved: root.workspace.changeLight("focus_blur", value)

    }

    NC.NCSwitch {
        Layout.fillWidth: true; text: "Tilt-shift"; objectName: "chessTiltShiftToggle"
        checked: root.workspace.light.tilt_shift === true
        onToggled: root.workspace.changeLight("tilt_shift",checked)
    }
    ColumnLayout {
        Layout.fillWidth: true; visible: root.workspace.light.tilt_shift === true
        ChessLabel { Layout.fillWidth: true; text: "Keeps a sharp band across the board. Takes priority over depth of field; pauses in reduced detail." }
        Repeater {
            model: [{key:"tilt_position",label:"Focus position",min:0,max:1,step:.01,initial:.5},
                    {key:"tilt_width",label:"Sharp-band width",min:.05,max:1,step:.01,initial:.25},
                    {key:"tilt_blur",label:"Blur strength",min:0,max:10,step:.1,initial:4},
                    {key:"tilt_angle",label:"Band angle (degrees)",min:-90,max:90,step:1,initial:0}]
            ColumnLayout {
                id: tiltControl
                required property var modelData
                Layout.fillWidth: true
                readonly property real settingValue: root.workspace.light[modelData.key] === undefined ? modelData.initial : root.workspace.light[modelData.key]
                ChessLabel { text: tiltControl.modelData.label + ": " + Number(tiltControl.settingValue).toFixed(tiltControl.modelData.step < 1 ? 2 : 0) }
                NC.NCSlider {
                    Layout.fillWidth: true; label: tiltControl.modelData.label
                    enabled: !root.workspace.lowDetail
                    from: tiltControl.modelData.min; to: tiltControl.modelData.max; stepSize: tiltControl.modelData.step
                    value: tiltControl.settingValue
                    onMoved: root.workspace.changeLight(tiltControl.modelData.key,value)
                }
            }
        }
    }
    NC.NCSwitch {
        Layout.fillWidth: true; text: "Physics dragging (3D)"
        checked: root.workspace.light.physics_drag === true
        onToggled: root.workspace.changeLight("physics_drag",checked)
    }
    ChessLabel { Layout.fillWidth: true; text: "Hold and drag your piece; release over a legal square. Pieces sway and bump visually, then settle back. Illegal drops return home. Click-to-move remains available." }
    NC.NCSwitch { objectName: "chessMotionToggle"; Layout.fillWidth: true; text: "Animate piece moves"; checked: root.workspace.light.move_animation !== false; onToggled: root.workspace.changeLight("move_animation", checked) }

    ChessLabel { text: "Move duration (ms)" }

    NC.NCSlider {

        objectName: "chessMoveDuration"; Layout.fillWidth: true; label: "Move duration (milliseconds)"

        enabled: root.workspace.light.move_animation !== false && !root.workspace.lowDetail

        from: 100; to: 800; stepSize: 20

        value: root.workspace.light.move_duration === undefined ? 280 : root.workspace.light.move_duration

        onMoved: root.workspace.changeLight("move_duration", value)

    }

    ColumnLayout {

        Layout.fillWidth: true; visible: root.workspace.boardModel !== "style"

        NC.NCSwitch {

            Layout.fillWidth: true; text: "Resin refraction"

            checked: root.workspace.light.refraction !== false

            onToggled: root.workspace.changeLight("refraction",checked)

        }

        ChessLabel { text: "Light transmission" }

        NC.NCSlider {

            Layout.fillWidth: true; label: "Light transmission"; from: 0; to: 1; stepSize: .01

            enabled: root.workspace.light.refraction !== false && !root.workspace.lowDetail

            value: root.workspace.light.transmission === undefined ? .8 : root.workspace.light.transmission

            onMoved: root.workspace.changeLight("transmission",value)

        }

        ChessLabel { text: "Refraction index · " + Number(root.workspace.light.ior === undefined ? 1.49 : root.workspace.light.ior).toFixed(2) }

        NC.NCSlider {

            Layout.fillWidth: true; label: "Refraction index"; from: 1; to: 2.4; stepSize: .01

            enabled: root.workspace.light.refraction !== false && !root.workspace.lowDetail

            value: root.workspace.light.ior === undefined ? 1.49 : root.workspace.light.ior

            onMoved: root.workspace.changeLight("ior",value)

        }

        ChessLabel { Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize; text: "Refracts the rendered scene through frosted resin. 1.49 suits plastic resin. Reduced detail disables transmission. This is not hardware ray tracing." }

    }

    NC.NCSwitch { Layout.fillWidth: true; text: "Reduced detail"; checked: root.workspace.lowDetail; onToggled: root.workspace.lowDetail = checked }

    ChessLabel { text: "Camera"; color: Theme.NCTheme.text; font.weight: Font.DemiBold }

    NC.NCSwitch {

        Layout.fillWidth: true; text: "Continuous camera movement"

        checked: root.workspace.light.camera_motion === true

        onToggled: root.workspace.changeLight("camera_motion",checked)

    }

    NC.NCComboBox {

        Layout.fillWidth: true; label: "Camera motion pattern"

        model: ["Soft orbit", "Side-to-side sway", "Figure-eight", "Breathing zoom"]

        currentIndex: Math.max(0,["orbit","sway","figure8","breathe"].indexOf(root.workspace.light.camera_pattern || "orbit"))

        onActivated: root.workspace.changeLight("camera_pattern",["orbit","sway","figure8","breathe"][currentIndex])

    }

    ChessLabel { text: "Motion speed · " + Number(root.workspace.light.camera_speed === undefined ? 1 : root.workspace.light.camera_speed).toFixed(2) + "×" }

    NC.NCSlider {

        Layout.fillWidth: true; label: "Camera motion speed"; from: .25; to: 3; stepSize: .05

        value: root.workspace.light.camera_speed === undefined ? 1 : root.workspace.light.camera_speed

        onMoved: root.workspace.changeLight("camera_speed",value)

    }

    ChessLabel { Layout.fillWidth: true; text: "Continuous movement until switched off. Speed: 0.25ז3×. Hidden views pause automatically." }

    Repeater {

        model: [{key:"cameraYaw",label:"Orbit",min:-180,max:180},{key:"cameraPitch",label:"Tilt",min:20,max:85},{key:"cameraDistance",label:"Distance",min:850,max:2100},{key:"cameraFov",label:"Field of view",min:30,max:70}]

        ColumnLayout {

            id: cameraRow

            required property var modelData

            Layout.fillWidth: true; spacing: 0

            RowLayout {

                Layout.fillWidth: true

                ChessLabel { Layout.fillWidth: true; text: cameraRow.modelData.label }

                ChessLabel { text: Math.round(root.workspace[cameraRow.modelData.key]) }

            }

            NC.NCSlider {

                Layout.fillWidth: true; label: cameraRow.modelData.label

                from: cameraRow.modelData.min; to: cameraRow.modelData.max

                value: root.workspace[cameraRow.modelData.key]

                onMoved: root.workspace[cameraRow.modelData.key] = value

            }

        }

    }

    NC.NCButton {

        Layout.fillWidth: true; text: "Reset camera"

        onClicked: { root.workspace.cameraYaw = 0; root.workspace.cameraPitch = 53; root.workspace.cameraDistance = 1350; root.workspace.cameraFov = 48 }

    }

    ChessLabel { Layout.fillWidth: true; text: "Left-click a piece, then its destination. Right-drag to orbit/tilt. Wheel: distance. Ctrl + wheel: field of view." }

}
