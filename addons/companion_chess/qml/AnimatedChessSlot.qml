import QtQuick
import QtQuick3D

Node {
    id: root
    required property var board
    property var entry: null
    property string lastSquare: ""
    property string lastPiece: ""
    property bool ready: false
    visible: !!entry
    function destination() {
        return entry ? Qt.vector3d((entry.square.charCodeAt(0)-97-3.5)*100,19,
            (3.5-(Number(entry.square[1])-1))*100) : Qt.vector3d(0,19,0)
    }
    function settle() {
        if (!ready) return
        movement.stop()
        hanging.reset()
        position = destination()
    }
    function updateEntry() {
        if (!ready) return
        if (!entry) { settle(); lastSquare = ""; lastPiece = ""; return }
        var unchanged = lastSquare === entry.square && lastPiece === entry.piece
        if (unchanged && !entry.snap) return // A status refresh must not restart/stop an active tween.
        var animate = !unchanged && lastSquare !== "" && entry.animate && !entry.landed && board.motionActive
        movement.stop()
        hanging.reset()
        lastSquare = entry.square; lastPiece = entry.piece
        if (animate) {
            movement.from = position; movement.to = destination(); movement.start()
        } else position = destination()
    }
    onEntryChanged: updateEntry()
    Component.onCompleted: { ready = true; updateEntry() }
    Connections {
        target: root.board
        function onMotionActiveChanged() { if (!root.board.motionActive) root.settle() }
    }
    Vector3dAnimation {
        id: movement
        target: root; property: "position"
        duration: root.board.lighting.move_duration === undefined ? 280 : root.board.lighting.move_duration
        easing.type: Easing.InOutCubic
    }
    HangingPiece {
        id: hanging
        board: root.board; slot: root
        Loader3D {
            active: !!root.entry
            sourceComponent: Component {
                ChessPiece {
                    piece: root.entry ? root.entry.piece : "P"
                    square: root.entry ? root.entry.square : "a1"
                    styleName: root.board.styleName; lowDetail: root.board.lowDetail; resin: root.board.launchpad
                    refractionEnabled: root.board.lighting.refraction !== false
                    transmission: root.board.lighting.transmission === undefined ? .8 : root.board.lighting.transmission
                    ior: root.board.lighting.ior === undefined ? 1.49 : root.board.lighting.ior
                    eulerRotation.y: root.entry && root.entry.color === "white" ? 0 : 180
                }
            }
        }
    }
}
