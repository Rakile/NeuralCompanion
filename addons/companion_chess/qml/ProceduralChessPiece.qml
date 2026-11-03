import QtQuick
import QtQuick3D

Node {
    id: root
    property string piece: "P"
    property string square: "a1"
    property string styleName: "classic"
    property bool lowDetail: false
    property bool resin: false
    readonly property string kind: piece.toLowerCase()
    readonly property bool lightSide: piece === piece.toUpperCase()
    readonly property bool fantasy: styleName === "fantasy"
    readonly property bool modern: styleName === "modern"
    readonly property real stature: kind === "p" ? 55 : kind === "k" ? 105 : kind === "q" ? 98 : 80
    readonly property color bodyColor: resin ? (lightSide ? "#def8ff" : "#ffe4cc") : fantasy ? (lightSide ? "#75976a" : "#684651") : (lightSide ? "#f1e7d4" : "#202329")
    PrincipledMaterial {
        id: body; baseColor: root.bodyColor
        roughness: root.resin ? .3 : root.modern ? .21 : .4; metalness: root.resin ? 0 : root.modern ? .7 : .12
        transmissionFactor: root.resin && !root.lowDetail ? .8 : 0; thicknessFactor: root.resin ? 18 : 0
        attenuationColor: root.resin ? (root.lightSide ? "#b8e2ef" : "#f2d9b7") : "white"; attenuationDistance: 160
        indexOfRefraction: root.resin ? 1.49 : 1.5; clearcoatAmount: root.resin ? .3 : 0; clearcoatRoughnessAmount: root.resin ? .2 : .08
    }
    PrincipledMaterial {
        id: trim; baseColor: root.resin ? root.bodyColor : root.lightSide ? "#d5b474" : "#9b789d"
        metalness: root.resin ? 0 : .75; roughness: root.resin ? .3 : .25
        transmissionFactor: root.resin && !root.lowDetail ? .8 : 0; thicknessFactor: root.resin ? 18 : 0
        attenuationColor: root.resin ? (root.lightSide ? "#b8e2ef" : "#f2d9b7") : "white"; attenuationDistance: 160
        indexOfRefraction: root.resin ? 1.49 : 1.5; clearcoatAmount: root.resin ? .3 : 0; clearcoatRoughnessAmount: root.resin ? .2 : .08
    }
    PrincipledMaterial { id: eye; baseColor: "#edc87a"; emissiveFactor: Qt.vector3d(.5,.23,.03) }
    Model { objectName: root.square; source: "#Cylinder"; y: 5; scale: Qt.vector3d(.58,.1,.58); materials: [body]; pickable: true }
    Model { objectName: root.square; source: "#Cylinder"; y: 12; scale: Qt.vector3d(.48,.07,.48); materials: [trim]; pickable: true }
    Model {
        objectName: root.square
        source: root.modern || (root.fantasy && root.kind === "r") ? "#Cube" : "#Cone"
        y: root.stature * .42; scale: Qt.vector3d(root.kind === "r" ? .39 : .35, root.stature / 100 * .63, .35)
        eulerRotation.y: root.modern ? 45 : 0
        materials: [body]; pickable: true
    }
    Model {
        objectName: root.square
        source: root.kind === "r" || root.modern ? "#Cube" : "#Sphere"
        y: root.stature * .82
        scale: Qt.vector3d(root.kind === "n" ? .29 : .34, root.kind === "n" ? .39 : .28, root.kind === "n" ? .46 : .34)
        eulerRotation.x: root.kind === "n" ? -20 : 0
        materials: [body]; pickable: true
    }
    // Bishop mitre / shaman hood.
    Model { visible: root.kind === "b"; objectName: root.square; source: "#Cone"; y: root.stature; scale: Qt.vector3d(.27,.35,.27); materials: [root.fantasy ? trim : body]; pickable: true }
    // Knight muzzle / warg head, always oriented towards the opponent.
    Model { visible: root.kind === "n"; objectName: root.square; source: "#Cube"; y: root.stature * .85; z: -14; scale: Qt.vector3d(.24,.2,.36); materials: [body]; pickable: true }
    Node {
        visible: root.kind === "r" || root.kind === "q" || (root.fantasy && root.kind === "k")
        y: root.stature * .97
        Repeater3D {
            model: 5
            Model {
                required property int index
                objectName: root.square
                source: root.kind === "r" ? "#Cube" : "#Cone"
                x: Math.cos(index * Math.PI * .4) * 15
                z: Math.sin(index * Math.PI * .4) * 15
                scale: Qt.vector3d(.11,root.kind === "q" ? .25 : .19,.11)
                materials: [root.kind === "r" ? body : trim]; pickable: true
            }
        }
    }
    Node {
        visible: root.kind === "k"; y: root.stature + 5
        Model { objectName: root.square; source: "#Cube"; scale: Qt.vector3d(.09,.32,.09); materials: [trim]; pickable: true }
        Model { objectName: root.square; source: "#Cube"; y: 6; scale: Qt.vector3d(.28,.09,.09); materials: [trim]; pickable: true }
    }
    // Goblin ears, warg ears and a warlord's horns preserve each piece silhouette.
    Repeater3D {
        model: root.fantasy && (root.kind === "p" || root.kind === "n" || root.kind === "k") ? 2 : 0
        Model {
            required property int index
            objectName: root.square; source: "#Cone"
            x: index === 0 ? -18 : 18; y: root.stature * .95
            eulerRotation.z: root.kind === "p" ? (index === 0 ? 65 : -65) : (index === 0 ? 20 : -20)
            scale: Qt.vector3d(.13,root.kind === "k" ? .42 : .3,.12)
            materials: [root.kind === "k" ? trim : body]; pickable: true
        }
    }
    Repeater3D {
        model: root.fantasy && !root.lowDetail ? 2 : 0
        Model {
            required property int index
            objectName: root.square; source: "#Sphere"
            x: index === 0 ? -6 : 6; y: root.stature * .87; z: -15
            scale: Qt.vector3d(.045,.045,.045); materials: [eye]; pickable: true
        }
    }
}
