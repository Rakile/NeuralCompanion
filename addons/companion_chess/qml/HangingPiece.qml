import QtQuick
import QtQuick3D

// Presentation-only damped springs. Never changes board positions or legality.
Node {
    id: root
    required property var board
    required property var slot
    property real vx: 0
    property real vy: 0
    property real vz: 0
    property real rx: 0
    property real rz: 0
    property bool unsettled: false
    property real lift: 0
    y: 85 + lift
    pivot: Qt.vector3d(0,85,0)
    function reset() {
        x=0; z=0; lift=0; eulerRotation = Qt.vector3d(0,0,0)
        vx=0; vy=0; vz=0; rx=0; rz=0; unsettled=false
    }
    function advance(dt) {
        if (!slot.entry) { reset(); return }
        dt = Math.min(.025,dt)
        const home = slot.destination()
        const held = board.dragSquare === slot.entry.square
        const landing = board.dropPreview && board.dropPreview.source === slot.entry.square
        let tx=0,ty=0,tz=0
        if (held) {
            tx=board.dragPoint.x-home.x; tz=board.dragPoint.z-home.z; ty=65
        } else if (landing) {
            const target=board.dropPreview.target
            tx=(target.charCodeAt(0)-97-3.5)*100-home.x
            tz=(3.5-(Number(target[1])-1))*100-home.z
        } else if (board.dragSquare) {
            const dx=home.x-board.dragPoint.x, dz=home.z-board.dragPoint.z
            const distance=Math.sqrt(dx*dx+dz*dz)
            if (distance<65 && distance>.01) {
                const push=Math.min(28,65-distance)
                tx=dx/distance*push; tz=dz/distance*push
            }
        }
        vx += ((tx-x)*180-vx*22)*dt
        vy += ((ty-lift)*160-vy*17)*dt
        vz += ((tz-z)*180-vz*22)*dt
        x+=vx*dt; lift=Math.max(0,lift+vy*dt); z+=vz*dt
        if (lift===0 && vy<0) vy=0
        const ax=held ? Math.max(-22,Math.min(22,vz*.08)) : landing ? 0 : -z*.3
        const az=held ? Math.max(-22,Math.min(22,-vx*.08)) : landing ? 0 : x*.3
        rx+=((ax-eulerRotation.x)*90-rx*12)*dt
        rz+=((az-eulerRotation.z)*90-rz*12)*dt
        eulerRotation=Qt.vector3d(eulerRotation.x+rx*dt,0,eulerRotation.z+rz*dt)
        unsettled=Math.abs(x)+Math.abs(lift)+Math.abs(z)+Math.abs(vx)+Math.abs(vy)+Math.abs(vz)+Math.abs(rx)+Math.abs(rz)+Math.abs(eulerRotation.x)+Math.abs(eulerRotation.z)>.03
        if (!board.dragSquare && !unsettled) reset()
    }
    FrameAnimation {
        running: root.visible && root.board.visible && !!root.slot.entry && (!!root.board.dragSquare || root.unsettled)
        onTriggered: root.advance(frameTime)
    }
}
