import QtQuick
import QtQuick3D
import QtQuick3D.Particles3D

ParticleSystem3D {
    id: root
    objectName: "chessDustSystem"
    property bool active: false
    property real warmth: .55
    running: active
    visible: active
    useRandomSeed: false
    seed: 43
    startTime: 18000

    SpriteParticle3D {
        id: dust
        maxAmount: 72
        particleScale: 1
        billboard: true
        castsReflections: false
        color: Qt.rgba(1, 1 - root.warmth * .1, 1 - root.warmth * .22, .35)
        colorVariation: Qt.vector4d(0, 0, 0, .12)
        fadeInDuration: 2500
        fadeOutDuration: 3500
        sortMode: Particle3D.SortDistance
        sprite: Texture { source: "../assets/dust-mote.svg" }
    }
    ParticleEmitter3D {
        particle: dust
        y: 170
        shape: ParticleShape3D { type: ParticleShape3D.Cube; extents: Qt.vector3d(470, 130, 470) }
        emitRate: 2
        lifeSpan: 30000
        lifeSpanVariation: 4000
        particleScale: 3.8
        particleScaleVariation: 1.8
        velocity: VectorDirection3D { direction: Qt.vector3d(1.3, .6, -.5); directionVariation: Qt.vector3d(1.5, .6, 1.5) }
    }
    Wander3D {
        particles: [dust]
        uniqueAmount: Qt.vector3d(12, 8, 12)
        uniquePace: Qt.vector3d(.14, .11, .13)
        uniquePaceVariation: .4
    }
}
