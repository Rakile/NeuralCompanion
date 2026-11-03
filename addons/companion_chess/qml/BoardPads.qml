import QtQuick
import QtQuick3D
import "PadGroups.js" as PadGroups
import "BoardModels.js" as BoardModels

Node {
    id: root
    required property var board
    property Texture woodTexture: null
    Texture { id: rubberGrain; source: "../assets/rubber-grain.png" }
    Texture { id: rubberNormal; source: "../assets/rubber-normal.png" }
    Texture { id: ledDiffusion; source: "../assets/tile-emission.svg" }
    readonly property var route: board.lighting.flowing_path === true ? PadGroups.route(board.gameState) : []
    property real phase: 0
    Timer {
        interval: 50; repeat: true
        running: root.route.length > 0 && root.board.effectsActive
        onTriggered: root.phase = (Date.now() % 3000)/3000
    }
    readonly property var groups: PadGroups.groups(board.pieces,board.dragSquare || board.selected,board.highlight,board.dragSquare ? board.dragTargets : board.targets,board.launchpad,route)
    Repeater3D {
        model: 8
        PadBatch {
            required property int index
            groupIndex: index
            indices: root.groups[index] || []
            launchpad: root.board.launchpad
            tileWidth: BoardModels.padWidth(root.board.boardModel)
            styleName: root.board.styleName
            padColour: PadGroups.colour(index,launchpad,styleName,root.board.lighting.palette)
            route: root.route
            phase: root.board.effectsActive ? root.phase : 0
            flowing: index === 7 && root.board.effectsActive
            woodTexture: root.woodTexture
            ledBrightness: root.board.ledBrightness
            grainTexture: rubberGrain
            normalTexture: rubberNormal
            diffusionTexture: ledDiffusion
            source: "../assets/beveled-tile.mesh"
        }
    }
}
