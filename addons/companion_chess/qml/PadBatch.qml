import QtQuick
import QtQuick3D
import "PadGroups.js" as PadGroups

Model {
    id: root
    required property int groupIndex
    required property var indices
    required property bool launchpad
    required property string styleName
    required property color padColour
    property Texture woodTexture: null
    property Texture grainTexture: null
    property Texture normalTexture: null
    property Texture diffusionTexture: null
    property real ledBrightness: .55
    property var route: []
    property real phase: 0
    property bool flowing: false
    property var entries: []
    property string layoutKey: ""
    property bool ready: false
    property real tileWidth: 96
    readonly property int padCount: table.instanceCount
    readonly property vector3d padScale: Qt.vector3d(tileWidth/100,1,tileWidth/100)
    objectName: "chessPadBatch" + groupIndex
    visible: indices.length > 0
    pickable: true

    function squareForInstance(instanceIndex) {
        return typeof instanceIndex === 'number' && instanceIndex % 1 === 0
            && instanceIndex >= 0 && instanceIndex < indices.length
            ? PadGroups.square(indices[instanceIndex]) : ""
    }
    function synchronize() {
        if (!ready) return
        var key = indices.join(',') + '|' + launchpad + '|' + padScale.x + ',' + padScale.y + ',' + padScale.z
        if (key === layoutKey) return
        layoutKey = key
        var previous = entries, next = []
        for (var i = 0; i < indices.length; ++i) {
            var entry = i < previous.length ? previous[i] : entryComponent.createObject(table)
            var index = indices[i]
            // Authored top Y19; styled top stays at its original Y18.
            entry.position = Qt.vector3d((index % 8 - 3.5)*100,launchpad ? 0 : -1,
                (3.5 - Math.floor(index / 8))*100)
            entry.scale = padScale
            next.push(entry)
        }
        // Clear table references before deferred destruction; retain live Qt
        // entry objects explicitly. Total entries across all groups stays 64.
        table.instances = next
        entries = next
        for (i = next.length; i < previous.length; ++i) previous[i].destroy()
        updatePulse()
    }
    function updatePulse() {
        if (groupIndex !== 7) return
        for (var i=0;i<entries.length;++i) {
            var routeIndex=route.indexOf(PadGroups.square(indices[i]))
            var value=flowing ? PadGroups.pulse(phase,Math.max(0,routeIndex),route.length) : 1
            entries[i].color=Qt.rgba(value,value,value,1)
        }
    }
    onPhaseChanged: updatePulse()
    onFlowingChanged: updatePulse()
    onRouteChanged: updatePulse()
    onIndicesChanged: synchronize()
    onPadScaleChanged: synchronize()
    Component.onCompleted: { ready = true; synchronize() }
    Component { id: entryComponent; InstanceListEntry { color: "white" } }
    instancing: InstanceList { id: table }
    materials: PrincipledMaterial {
        objectName: "chessPadMaterial" + root.groupIndex
        baseColor: root.padColour
        baseColorMap: root.launchpad ? root.grainTexture : root.styleName === "classic" ? root.woodTexture : null
        normalMap: root.launchpad ? root.normalTexture : null
        normalStrength: root.launchpad ? .35 : 1
        emissiveMap: root.launchpad ? root.diffusionTexture : null
        roughness: root.launchpad ? .82 : root.styleName === "modern" ? .2 : .5
        specularAmount: root.launchpad ? .35 : .5
        clearcoatAmount: .12
        clearcoatRoughnessAmount: .3
        metalness: !root.launchpad && root.styleName === "modern" ? .45 : 0
        emissiveFactor: root.launchpad ? Qt.vector3d(baseColor.r*.55*root.ledBrightness,
            baseColor.g*.55*root.ledBrightness,baseColor.b*.55*root.ledBrightness) : Qt.vector3d(0,0,0)
    }
}
