import QtQuick
import QtQuick3D

// Object-space grain needs no UVs or mesh tangents, including imported housings.
CustomMaterial {
    property color casingColor: "#181b20"
    property real grainStrength: 1
    shadingMode: CustomMaterial.Shaded
    vertexShader: "casing.vert"
    fragmentShader: "casing.frag"
}
