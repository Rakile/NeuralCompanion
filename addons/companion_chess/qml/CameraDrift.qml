import QtQuick

// Additive offsets leave the user's orbit, distance and FOV settings untouched.
Item {
    id: root
    property bool motionEnabled: false
    property bool active: false
    property string pattern: "orbit"
    property real phase: 0
    property real speed: 1
    // Smooth setting changes, never the sample that advances on every frame.
    property real motionAmount: motionEnabled ? 1 : 0
    property string displayedPattern: "orbit"
    property vector3d transitionFrom: Qt.vector3d(0,0,0)
    property real patternMix: 1
    readonly property vector3d patternOffset: sample(displayedPattern,phase)
    readonly property vector3d blendedOffset: Qt.vector3d(
        transitionFrom.x + (patternOffset.x-transitionFrom.x)*patternMix,
        transitionFrom.y + (patternOffset.y-transitionFrom.y)*patternMix,
        transitionFrom.z + (patternOffset.z-transitionFrom.z)*patternMix)
    readonly property vector3d offset: Qt.vector3d(blendedOffset.x*motionAmount,
        blendedOffset.y*motionAmount,blendedOffset.z*motionAmount)
    onPatternChanged: {
        const previous = blendedOffset
        patternTransition.stop()
        transitionFrom = previous
        displayedPattern = pattern
        patternTransition.restart()
    }
    function sample(name,t) {
        if (name === "sway") return Qt.vector3d(5*Math.sin(t),0,0)
        if (name === "figure8") return Qt.vector3d(5*Math.sin(t),2*Math.sin(2*t),0)
        if (name === "breathe") return Qt.vector3d(0,0,25*Math.sin(t))
        return Qt.vector3d(5*Math.sin(t),2*Math.cos(t),0)
    }
    FrameAnimation {
        running: root.motionEnabled && root.active
        onTriggered: root.phase = (root.phase + Math.min(frameTime, .1) *
                                  Math.max(.25, Math.min(3, root.speed)) * 2*Math.PI/24) % (2*Math.PI)
    }
    Behavior on motionAmount { NumberAnimation { duration: 500; easing.type: Easing.InOutSine } }
    NumberAnimation {
        id: patternTransition
        target: root; property: "patternMix"; from: 0; to: 1
        duration: 500; easing.type: Easing.InOutSine
    }
}
