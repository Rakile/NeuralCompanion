pragma ComponentBehavior: Bound

import QtQuick 6.4

Item {
    id: root
    objectName: "ncGpuOrbEffect"

    property string role: "presence"
    property string aiState: "idle"
    property string visualStyle: "neural_network_pulse"
    property string stateAnimation: "style_default"
    property real audioLevel: 0.0
    property real peakLevel: 0.0
    property real ambientLevel: 0.0
    property real orbDiameter: 92.0
    property real opacityStrength: 1.0
    property real pulseIntensity: 0.55
    property real speakingReactivity: 0.85
    property real glowStrength: 1.0
    property real animationSpeed: 1.0
    property real idleMotionStrength: 0.16
    property real haloThickness: 1.0
    property real waveformStrength: 1.0
    property real ringExpansionSpeed: 1.0
    property real blurSoftness: 0.35
    property real lineBrightness: 1.0
    property real trailLength: 0.55
    property real smokeIntensity: 0.0
    property int nodeDensity: 32
    property int particleDensity: 28
    property int fallingParticleDensity: 18
    property real fallingParticleLifetime: 3.8
    property int frameRate: 60
    property bool running: true
    property bool reducedEffects: false
    property bool shadersEnabled: true
    property bool particlesEnabled: true
    property bool fallingParticlesEnabled: false
    property bool opaqueBackground: false
    property bool targetActive: false
    property bool placementMode: false
    property bool gazeTimerActive: false
    property real gazeTimerProgress: 0.0
    property color gazeTimerColor: "#facc15"
    property color primaryColor: "#38bdf8"
    property color secondaryColor: "#22d3ee"
    property color accentColor: "#a78bfa"
    property color glowColor: "#67e8f9"
    property color backgroundColor: "#030712"
    property real backgroundDarkness: 1.0

    property real phase: 0.0
    readonly property real boundedAudio: Math.max(0.0, Math.min(1.0, audioLevel))
    readonly property real boundedPeak: Math.max(boundedAudio, Math.max(0.0, Math.min(1.0, peakLevel)))
    readonly property real activity: Math.max(boundedPeak, Math.max(0.0, Math.min(1.0, ambientLevel)))
    readonly property int effectiveFrameRate: reducedEffects ? Math.min(30, frameRate) : Math.max(30, Math.min(120, frameRate))
    readonly property real visualDiameter: role === "companion"
        ? Math.max(36.0, orbDiameter)
        : Math.max(84.0, Math.min(width, height) * 0.38)
    readonly property real effectDiameter: visualDiameter * (role === "companion" ? 2.05 : 2.35)
    readonly property real stateEnergy: aiState === "speaking"
        ? Math.min(1.0, 0.25 + boundedAudio * speakingReactivity)
        : (aiState === "thinking" ? 0.42 : (targetActive || placementMode ? 0.30 : 0.12))
    readonly property real motionScale: reducedEffects ? 0.28 : 1.0
    readonly property real animationMultiplier: stateAnimation === "calm_breathe" ? 0.72
        : (stateAnimation === "slow_orbit" ? 0.55
        : (stateAnimation === "focused_pulse" ? 1.05
        : (stateAnimation === "thinking_swirl" ? 1.16
        : (stateAnimation === "voice_ripple" ? 1.30
        : (stateAnimation === "energetic_sparkle" ? 1.45 : 1.0)))))
    readonly property int styleCode: styleCodeFor(visualStyle)

    function styleCodeFor(styleName) {
        var style = String(styleName || "").toLowerCase()
        if (style === "aurora_glass") return 1
        if (style === "prismatic_pulse") return 2
        if (style === "aether_wisp") return 3
        if (style === "celestial_firetrail") return 4
        if (style === "event_horizon") return 5
        if (style === "holographic_iris") return 6
        if (style === "synaptic_bloom") return 7
        if (style === "liquid_core") return 8
        if (style === "void_prism" || style === "crystal_prism") return 9
        if (style === "quantum_halo" || style === "halo_rings") return 10
        if (style === "minimal_dot") return 11
        return 0
    }

    function deterministic(index, salt) {
        return Math.abs(Math.sin((index + 1) * (12.9898 + salt * 3.17)) * 43758.5453) % 1.0
    }

    FrameAnimation {
        id: frameDriver
        running: root.visible && root.running
        onTriggered: {
            var quantized = Math.floor(elapsedTime * root.effectiveFrameRate) / root.effectiveFrameRate
            root.phase = quantized * root.animationSpeed * root.animationMultiplier
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: root.opaqueBackground
        color: Qt.rgba(
            root.backgroundColor.r * (0.72 + root.backgroundDarkness * 0.18),
            root.backgroundColor.g * (0.72 + root.backgroundDarkness * 0.18),
            root.backgroundColor.b * (0.72 + root.backgroundDarkness * 0.18),
            0.90
        )
    }

    Item {
        id: visualStage
        width: root.effectDiameter
        height: width
        opacity: root.opacityStrength
        x: (parent.width - width) / 2
            + Math.sin(root.phase * 0.53) * root.idleMotionStrength * 7.0 * root.motionScale
        y: (parent.height - height) / 2
            + Math.cos(root.phase * 0.41) * root.idleMotionStrength * 5.0 * root.motionScale
        scale: 1.0 + Math.sin(root.phase * 1.15) * 0.012 * root.pulseIntensity * root.motionScale
            + root.boundedAudio * 0.055 * root.speakingReactivity
            + (root.stateAnimation === "focused_pulse" ? root.stateEnergy * 0.025 : 0.0)

        ShaderEffect {
            id: matteCore
            objectName: "ncGpuMatteCore"
            anchors.fill: parent
            visible: root.shadersEnabled && !root.reducedEffects
            blending: true

            property real time: root.phase
            property real level: root.activity
            property real stateLevel: root.stateEnergy
            property real glowAmount: Math.max(0.0, Math.min(1.75, root.glowStrength))
            property real softness: Math.max(0.0, Math.min(1.0, root.blurSoftness))
            property real style: root.styleCode
            property color primary: root.primaryColor
            property color secondary: root.secondaryColor
            property color accent: root.accentColor
            property color glow: root.glowColor

            vertexShader: "shaders/nc_orb.vert.qsb"
            fragmentShader: "shaders/nc_orb.frag.qsb"
        }

        Item {
            anchors.centerIn: parent
            width: root.visualDiameter * 0.92
            height: width
            visible: !root.shadersEnabled || root.reducedEffects

            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: Qt.rgba(root.primaryColor.r * 0.20, root.primaryColor.g * 0.20, root.primaryColor.b * 0.20, 0.94)
                border.width: Math.max(1, 2.2 * root.haloThickness)
                border.color: Qt.rgba(root.secondaryColor.r, root.secondaryColor.g, root.secondaryColor.b, 0.78)
            }
            Rectangle {
                anchors.centerIn: parent
                width: parent.width * (0.58 + root.boundedAudio * 0.08)
                height: width
                radius: width / 2
                color: Qt.rgba(root.primaryColor.r * 0.52, root.primaryColor.g * 0.52, root.primaryColor.b * 0.52, 0.76)
                border.width: 1
                border.color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.48)
            }
        }

        Repeater {
            model: root.styleCode === 11 ? 2 : (root.reducedEffects ? 2 : (root.styleCode === 10 ? 7 : 4))
            delegate: Rectangle {
                required property int index
                anchors.centerIn: parent
                width: root.visualDiameter * (1.08 + index * 0.18)
                    * (1.0 + Math.sin(root.phase * root.ringExpansionSpeed + index * 1.31) * 0.025 * root.motionScale)
                height: width
                radius: width / 2
                color: "transparent"
                border.width: Math.max(1.0, root.haloThickness * (index === 0 ? 1.7 : 1.0))
                border.color: Qt.rgba(
                    (index % 2 ? root.accentColor : root.secondaryColor).r,
                    (index % 2 ? root.accentColor : root.secondaryColor).g,
                    (index % 2 ? root.accentColor : root.secondaryColor).b,
                    Math.max(0.04, (0.28 - index * 0.035) * root.lineBrightness * (0.65 + root.activity * 0.35))
                )
            }
        }

        Repeater {
            model: root.reducedEffects ? 10 : Math.max(10, Math.min(48, root.nodeDensity))
            delegate: Rectangle {
                required property int index
                readonly property real orbit: root.visualDiameter * (0.64 + root.deterministic(index, 1) * 0.44)
                readonly property real angle: index * 2.39996 + root.phase * (0.08 + root.deterministic(index, 2) * 0.09) * root.motionScale
                width: 2.2 + root.deterministic(index, 3) * 3.0 + root.activity * 1.7
                height: width
                radius: width / 2
                x: parent.width / 2 + Math.cos(angle) * orbit - width / 2
                y: parent.height / 2 + Math.sin(angle) * orbit * 0.76 - height / 2
                color: index % 3 === 0 ? root.accentColor : (index % 2 ? root.secondaryColor : root.primaryColor)
                opacity: (0.28 + root.deterministic(index, 4) * 0.44) * root.lineBrightness
            }
        }

        Repeater {
            model: root.particlesEnabled && !root.reducedEffects ? Math.min(48, Math.max(0, root.particleDensity)) : 0
            delegate: Rectangle {
                required property int index
                readonly property real radiusFactor: 0.78 + root.deterministic(index, 6) * (0.42 + root.trailLength * 0.25)
                readonly property real angle: index * 2.118 + root.phase * (0.11 + root.deterministic(index, 7) * 0.16)
                    * (root.stateAnimation === "slow_orbit" ? 0.62 : (root.stateAnimation === "thinking_swirl" ? 1.38 : 1.0))
                width: 1.4 + root.deterministic(index, 8) * 2.8 + root.activity * 1.4
                height: width
                radius: width / 2
                x: parent.width / 2 + Math.cos(angle) * root.visualDiameter * radiusFactor - width / 2
                y: parent.height / 2 + Math.sin(angle) * root.visualDiameter * radiusFactor * 0.82 - height / 2
                color: index % 3 === 0 ? root.glowColor : (index % 2 ? root.primaryColor : root.accentColor)
                opacity: 0.18 + root.deterministic(index, 9) * 0.46 + root.activity * 0.18
                    + (root.stateAnimation === "energetic_sparkle"
                        ? Math.max(0.0, Math.sin(root.phase * 6.0 + index)) * 0.20 : 0.0)
            }
        }

        Repeater {
            model: root.role === "companion" && root.fallingParticlesEnabled && !root.reducedEffects
                ? Math.min(40, Math.max(0, root.fallingParticleDensity)) : 0
            delegate: Rectangle {
                required property int index
                readonly property real cycle: Math.max(0.8, root.fallingParticleLifetime)
                readonly property real progress: (root.phase / cycle + root.deterministic(index, 11)) % 1.0
                width: 1.5 + root.deterministic(index, 12) * 2.3
                height: width * (1.2 + root.trailLength * 2.2)
                radius: width / 2
                x: parent.width / 2 + (root.deterministic(index, 13) - 0.5) * root.visualDiameter * 1.8
                y: parent.height / 2 - root.visualDiameter * 0.95 + progress * root.visualDiameter * 1.9
                color: index % 2 ? root.secondaryColor : root.accentColor
                opacity: Math.sin(progress * Math.PI) * (0.22 + root.activity * 0.36)
            }
        }

        Repeater {
            model: root.reducedEffects ? 12 : 32
            delegate: Rectangle {
                required property int index
                readonly property real angle: index * Math.PI * 2.0 / (root.reducedEffects ? 12 : 32)
                readonly property real wave: 0.5 + 0.5 * Math.sin(root.phase * 3.2 - index * 0.72)
                readonly property real radial: root.visualDiameter * 0.59
                width: Math.max(1.2, root.haloThickness * 1.25)
                height: 3.0 + (root.boundedAudio * 18.0 + root.stateEnergy * 4.0) * wave * root.waveformStrength
                radius: width / 2
                x: parent.width / 2 + Math.cos(angle) * radial - width / 2
                y: parent.height / 2 + Math.sin(angle) * radial - height / 2
                rotation: angle * 180.0 / Math.PI + 90.0
                transformOrigin: Item.Center
                color: index % 3 === 0 ? root.accentColor : root.secondaryColor
                opacity: 0.38 + root.boundedAudio * 0.48
            }
        }

        Repeater {
            model: root.role === "companion" && root.smokeIntensity > 0.01 && !root.reducedEffects ? 5 : 0
            delegate: Rectangle {
                required property int index
                width: root.visualDiameter * (0.30 + index * 0.055)
                height: width * 0.72
                radius: width / 2
                x: parent.width / 2 - width / 2 + Math.sin(root.phase * (0.22 + index * 0.03) + index) * root.visualDiameter * 0.34
                y: parent.height / 2 - root.visualDiameter * (0.48 + index * 0.09)
                color: Qt.rgba(root.glowColor.r * 0.26, root.glowColor.g * 0.26, root.glowColor.b * 0.26, 0.12 * root.smokeIntensity)
                opacity: (0.28 + index * 0.07) * root.smokeIntensity
            }
        }

        Repeater {
            model: root.role === "companion" && (root.targetActive || root.placementMode) ? 4 : 0
            delegate: Item {
                required property int index
                width: root.visualDiameter * 1.48
                height: width
                anchors.centerIn: parent
                rotation: index * 90
                Rectangle {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    width: parent.width * 0.18
                    height: 2
                    color: root.targetActive ? root.accentColor : root.primaryColor
                    opacity: 0.78
                }
                Rectangle {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    width: 2
                    height: parent.height * 0.18
                    color: root.targetActive ? root.accentColor : root.primaryColor
                    opacity: 0.78
                }
            }
        }

        Repeater {
            model: root.role === "companion" && root.gazeTimerActive ? 40 : 0
            delegate: Rectangle {
                required property int index
                readonly property real angle: index * Math.PI * 2.0 / 40.0 - Math.PI / 2.0
                visible: index / 40.0 <= root.gazeTimerProgress
                width: 3.0
                height: 8.0
                radius: 1.5
                x: parent.width / 2 + Math.cos(angle) * root.visualDiameter * 0.86 - width / 2
                y: parent.height / 2 + Math.sin(angle) * root.visualDiameter * 0.86 - height / 2
                rotation: angle * 180.0 / Math.PI + 90.0
                color: root.gazeTimerColor
                opacity: 0.94
            }
        }
    }
}
