import QtQuick
import QtQuick3D

Node {
    id: root
    property string piece: "P"
    property string square: "a1"
    property string styleName: "classic"
    property bool lowDetail: false
    property bool resin: false
    property bool refractionEnabled: true
    property real transmission: .8
    property real ior: 1.49
    readonly property bool lightSide: piece === piece.toUpperCase()
    readonly property bool fantasy: styleName === "fantasy"
    readonly property bool modern: styleName === "modern"
    readonly property string meshName: {
        switch (piece.toLowerCase()) {
        case "p": return "pawn"
        case "r": return "rook"
        case "n": return "knight"
        case "b": return "bishop"
        case "q": return "queen"
        case "k": return "king"
        default: return "pawn"
        }
    }
    PrincipledMaterial {
        id: body
        objectName: "chessResinMaterial" + root.square
        baseColor: root.resin ? (root.lightSide ? "#def8ff" : "#ffe4cc")
            : root.fantasy ? (root.lightSide ? "#75976a" : "#684651") : (root.lightSide ? "#f1e7d4" : "#202329")
        roughness: root.resin ? .3 : root.modern ? .21 : .4
        metalness: root.resin ? 0 : root.modern ? .7 : .12
        transmissionFactor: root.resin && root.refractionEnabled && !root.lowDetail ? Math.max(0,Math.min(1,root.transmission)) : 0
        thicknessFactor: root.resin ? 18 : 0
        attenuationColor: root.resin ? (root.lightSide ? "#b8e2ef" : "#f2d9b7") : "white"
        attenuationDistance: 160
        indexOfRefraction: root.resin ? Math.max(1,Math.min(2.4,root.ior)) : 1.5
        clearcoatAmount: root.resin ? .3 : 0
        clearcoatRoughnessAmount: root.resin ? .2 : .08
    }
    // Fixed bundled assets: conversion happens offline, never in the running addon.
    Loader3D {
        sourceComponent: root.lowDetail ? simplePiece : spiralPiece
    }
    Component {
        id: spiralPiece
        Model {
            objectName: root.square
            source: "../assets/spiral/" + root.meshName + ".mesh"
            materials: [body]
            castsShadows: !root.resin
            pickable: true
        }
    }
    Component {
        id: simplePiece
        ProceduralChessPiece {
            piece: root.piece
            square: root.square
            styleName: root.styleName
            lowDetail: true
            resin: root.resin
        }
    }
}
