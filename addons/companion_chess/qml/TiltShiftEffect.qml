import QtQuick
import QtQuick3D

Effect {
    property real focusPosition: .5
    property real focusWidth: .25
    property real blurAmount: 4
    property real bandAngle: 0
    Buffer {
        id: intermediate
        name: "chessTiltIntermediate"
        format: Buffer.RGBA16F
        textureFilterOperation: Buffer.Linear
        textureCoordOperation: Buffer.ClampToEdge
    }
    passes: [
        Pass {
            shaders: [ Shader { stage: Shader.Vertex; shader: "tilt-horizontal.vert" },
                       Shader { stage: Shader.Fragment; shader: "tilt.frag" } ]
            output: intermediate
        },
        Pass {
            shaders: [ Shader { stage: Shader.Vertex; shader: "tilt-vertical.vert" },
                       Shader { stage: Shader.Fragment; shader: "tilt.frag" } ]
            commands: BufferInput { buffer: intermediate }
        }
    ]
}
