import QtQuick
import QtQuick.Window
import QtQuick3D
import QtQuick3D.Helpers
import "BoardModels.js" as BoardModels
import "PieceMotion.js" as PieceMotion

Item {
    id: root
    property var gameState: ({})
    property var pieces: gameState.pieces || []
    signal moveDropped(string source, string destination, string gameId, int revision)
    property string dragSquare: ""
    property vector3d dragPoint: Qt.vector3d(0,19,0)
    property vector3d dragGrabOffset: Qt.vector3d(0,0,0)
    property int dragRevision: -1
    property string dragGameId: ""
    // Visual landing only; the authoritative game still validates the move.
    property var dropPreview: null
    property bool dropWaiting: false
    onDropWaitingChanged: if (!dropWaiting) Qt.callLater(function() {
        synchronizePieces()
        if (!dropWaiting) dropPreview = null
    })
    readonly property var dragTargets: dragSquare ? (gameState.legal_moves || []).filter(m => m.slice(0,2) === dragSquare).map(m => m.slice(2,4)) : []
    function cancelDrag() { dragSquare = "" }
    function boardPoint(x,y) {
        const near=view.mapTo3DScene(Qt.vector3d(x,y,0))
        const far=view.mapTo3DScene(Qt.vector3d(x,y,1000))
        const dy=far.y-near.y
        if (Math.abs(dy)<.001) return null
        const t=(19-near.y)/dy
        if (t<=0) return null
        return Qt.vector3d(near.x+(far.x-near.x)*t,19,near.z+(far.z-near.z)*t)
    }
    function squareAt(p) {
        if (!p) return ""
        const file=Math.floor((p.x+400)/100), rank=7-Math.floor((p.z+400)/100)
        return file>=0 && file<8 && rank>=0 && rank<8 ? "abcdefgh"[file]+String(rank+1) : ""
    }
    function beginDrag(x,y) {
        if (lighting.physics_drag !== true || dropPreview) return false
        const game=gameState, side=game.human || game.your_side
        if (!(game.phase === "human_turn" || (game.status === "active" && game.turn === game.your_side)) || game.pending) return false
        const hit=view.pick(x,y)
        // Require an actual piece, not the empty part of its pad.
        const square=hit.objectHit ? hit.objectHit.objectName : ""
        const piece=pieces.find(p => p.square===square && p.color===side)
        if (!piece) return false
        const point=boardPoint(x,y)
        if (!point) return false
        dragRevision=game.revision; dragGameId=game.game_id || game.id || ""
        dragPoint=Qt.vector3d((square.charCodeAt(0)-97-3.5)*100,19,(3.5-(Number(square[1])-1))*100)
        dragGrabOffset=Qt.vector3d(dragPoint.x-point.x,0,dragPoint.z-point.z)
        dragSquare=square
        return true
    }
    function updateDrag(x,y) {
        const point=boardPoint(x,y)
        if (point) dragPoint=Qt.vector3d(Math.max(-600,Math.min(600,point.x+dragGrabOffset.x)),19,Math.max(-600,Math.min(600,point.z+dragGrabOffset.z)))
    }
    function finishDrag(x,y,moved) {
        if (moved) updateDrag(x,y)
        const source=dragSquare, target=squareAt(dragPoint), revision=dragRevision, identity=dragGameId
        cancelDrag()
        if (!source) return
        if (!moved) { squareClicked(source); return }
        if (source===target || !target) return
        if (gameState.legal_moves && !gameState.legal_moves.some(m => m.slice(0,4)===source+target)) return
        dropPreview = {source:source,target:target,gameId:identity}
        moveDropped(source,target,identity,revision)
    }
    onVisibleChanged: if (!visible) cancelDrag()
    onEnabledChanged: if (!enabled) cancelDrag()
    onLightingChanged: if (lighting.physics_drag !== true) cancelDrag()
    property var visualSlots: []
    property var previousMeta: ({})
    property string styleName: "classic"
    property string boardModel: "style"
    readonly property string boardFolder: BoardModels.folder(boardModel)
    readonly property bool launchpad: boardFolder !== ""
    property string selected: ""
    property string highlight: ""
    property var targets: []
    property var lighting: ({preset:"spotlight",brightness:1.4,warmth:.55,azimuth:25,elevation:68,fill:0,shadows:true})
    property real yaw: 0
    property real pitch: 53
    property real distance: 1350
    property real fieldOfView: 48
    signal orbitRequested(real yaw, real pitch)
    signal distanceRequested(real distance)
    signal fieldOfViewRequested(real fieldOfView)
    property bool lowDetail: false
    readonly property real ledBrightness: lighting.led_brightness === undefined ? .55
        : Math.max(0, Math.min(1, Number(lighting.led_brightness)))
    signal squareClicked(string square)
    readonly property bool spotlightOnly: lighting.preset === "spotlight"
    readonly property var hostWindow: root.Window.window
    readonly property bool effectsActive: visible && !lowDetail && !!hostWindow
        && hostWindow.visible && hostWindow.visibility !== Window.Minimized
    // Qt 6.12/D3D11 crashes with DOF + SSR together. Preserve saved choices;
    // pause reflections while DOF is requested, then restore them automatically.
    readonly property bool reflectionsActive: effectsActive && lighting.reflections === true
        && lighting.depth_of_field !== true && lighting.tilt_shift !== true
    readonly property bool motionActive: effectsActive && lighting.move_animation !== false
    readonly property real viewDistance: Math.max(850,Math.min(2100,distance+cameraDrift.offset.z))
    function synchronizePieces() {
        // Prefer the atomic game object when supplied by local/online workspaces.
        const next = PieceMotion.reconcile(visualSlots, gameState.pieces || pieces, previousMeta, gameState)
        const preview = dropPreview
        let landed = false
        if (preview && preview.gameId === (gameState.game_id || gameState.id || "")) {
            for (let i=0; i<next.length; ++i) {
                if (visualSlots[i] && visualSlots[i].square === preview.source && next[i]
                        && next[i].square === preview.target && next[i].animate) {
                    next[i].landed = true
                    landed = true
                }
            }
        }
        visualSlots = next
        if (preview && (landed || preview.gameId !== (gameState.game_id || gameState.id || ""))) dropPreview = null
        previousMeta = PieceMotion.metadata(gameState)
    }
    onPiecesChanged: Qt.callLater(synchronizePieces)
    onGameStateChanged: {
        if (dragSquare && (gameState.revision!==dragRevision || (gameState.game_id || gameState.id || "")!==dragGameId)) cancelDrag()
        Qt.callLater(synchronizePieces)
    }
    function updateReflections() {
        // Keep the optional Qt 6.11+ feature from raising the addon's Qt floor.
        if ("ssrEnabled" in sceneEnvironment) sceneEnvironment["ssrEnabled"] = reflectionsActive
        if ("ssrMaxSteps" in sceneEnvironment) sceneEnvironment["ssrMaxSteps"] = 256
        if ("ssrThickness" in sceneEnvironment) sceneEnvironment["ssrThickness"] = 10
    }
    function squareForPick(hit) {
        if (!hit.objectHit) return ""
        if (typeof hit.objectHit.squareForInstance === "function")
            return hit.objectHit.squareForInstance(hit.instanceIndex)
        var name = hit.objectHit.objectName
        return /^[a-h][1-8]$/.test(name) ? name : ""
    }
    onReflectionsActiveChanged: updateReflections()
    Component.onCompleted: { updateReflections(); synchronizePieces() }
    View3D {
        id: view
        anchors.fill: parent
        environment: ExtendedSceneEnvironment {
            id: sceneEnvironment
            objectName: "chessSceneEnvironment"
            backgroundMode: SceneEnvironment.Color
            clearColor: root.spotlightOnly ? "#000000" : "#10141b"
            antialiasingMode: root.lowDetail || root.lighting.antialiasing === "off" ? SceneEnvironment.NoAA
                : root.lighting.antialiasing === "ssaa" ? SceneEnvironment.SSAA : SceneEnvironment.MSAA
            antialiasingQuality: root.lighting.antialiasing === "msaa2" ? SceneEnvironment.Medium
                : root.lighting.antialiasing === "msaa8" ? SceneEnvironment.VeryHigh : SceneEnvironment.High
            specularAAEnabled: !root.lowDetail
            // MSAA smooths geometry but not the SSR post-process. Filter that
            // pass and accumulate sub-pixel detail only while reflections run.
            temporalAAEnabled: root.reflectionsActive && root.lighting.antialiasing !== "off"
            fxaaEnabled: root.reflectionsActive && root.lighting.antialiasing !== "off"
            depthOfFieldEnabled: root.effectsActive && root.lighting.depth_of_field === true && root.lighting.tilt_shift !== true
            effects: root.effectsActive && root.lighting.tilt_shift === true ? [tiltShift] : []
            TiltShiftEffect {
                id: tiltShift
                objectName: "chessTiltShift"
                focusPosition: root.lighting.tilt_position === undefined ? .5 : root.lighting.tilt_position
                focusWidth: root.lighting.tilt_width === undefined ? .25 : root.lighting.tilt_width
                blurAmount: root.lighting.tilt_blur === undefined ? 4 : root.lighting.tilt_blur
                bandAngle: root.lighting.tilt_angle || 0
            }
            depthOfFieldBlurAmount: root.lighting.focus_blur === undefined ? 2.5 : root.lighting.focus_blur
            depthOfFieldFocusDistance: root.viewDistance
            depthOfFieldFocusRange: 500
            tonemapMode: root.launchpad ? SceneEnvironment.TonemapModeAces : SceneEnvironment.TonemapModeLinear
            lightProbe: root.launchpad && !root.lowDetail ? studioProbe : null
            probeExposure: root.spotlightOnly ? .22 : .4
            aoEnabled: root.effectsActive && root.lighting.ambient_occlusion !== false
            aoStrength: 25; aoDistance: 8; aoSoftness: 50; aoBias: .5; aoSampleRate: 2
            glowEnabled: root.effectsActive && root.launchpad && root.lighting.glow !== false
            glowStrength: .35; glowIntensity: .35; glowBloom: .04
            glowHDRMinimumValue: 1.15
        }
        Texture { id: studioProbe; source: "../assets/studio-probe.svg" }
        DustMotes {
            active: root.effectsActive && root.lighting.dust !== false
            warmth: root.lighting.warmth === undefined ? .55 : root.lighting.warmth
        }
        Node {
            eulerRotation: Qt.vector3d(-Math.max(20,Math.min(85,root.pitch+cameraDrift.offset.y)),root.yaw+cameraDrift.offset.x,0)
            PerspectiveCamera { id: camera; z: root.viewDistance; clipNear: 10; clipFar: 4500; fieldOfView: root.fieldOfView }
        }
        camera: camera
        SpotLight {
            scope: root.spotlightOnly ? boardRoot : null
            readonly property real az: (root.lighting.azimuth || 0) * Math.PI / 180
            readonly property real el: (root.lighting.elevation || 68) * Math.PI / 180
            x: Math.sin(az) * Math.cos(el) * 1250
            y: Math.sin(el) * 1250
            z: Math.cos(az) * Math.cos(el) * 1250
            eulerRotation: Qt.vector3d(-(root.lighting.elevation || 68),root.lighting.azimuth || 0,0)
            color: Qt.rgba(1,1-.22*(root.lighting.warmth || 0),1-.48*(root.lighting.warmth || 0),1)
            brightness: root.lighting.brightness === undefined ? 1.4 : root.lighting.brightness
            coneAngle: 57; innerConeAngle: 42
            constantFade: 1; linearFade: 0; quadraticFade: 0
            castsShadow: root.lighting.shadows !== false && !root.lowDetail
            shadowMapQuality: Light.ShadowMapQualityHigh
            shadowFactor: 70
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-35,-40,0)
            color: root.lighting.preset === "moon" ? "#9fbfff" : "#edf0ff"
            brightness: root.spotlightOnly ? 0 : Number(root.lighting.fill || .25)
        }
        Texture { id: wood; source: "../assets/wood.svg"; tilingModeHorizontal: Texture.Repeat; tilingModeVertical: Texture.Repeat; scaleU: 3; scaleV: 3 }
        Texture { id: stone; source: "../assets/stone.svg"; tilingModeHorizontal: Texture.Repeat; tilingModeVertical: Texture.Repeat; scaleU: 4; scaleV: 4 }
        Texture { id: earth; source: "../assets/earth.svg"; tilingModeHorizontal: Texture.Repeat; tilingModeVertical: Texture.Repeat; scaleU: 5; scaleV: 5 }
        Model {
            source: "#Cube"; y: BoardModels.bottomY(root.boardModel) - 25; scale: Qt.vector3d(15,.5,13)
            materials: PrincipledMaterial {
                baseColor: root.styleName === "classic" ? "#d4ad7e" : root.styleName === "modern" ? "#959b9c" : "#a7a58a"
                baseColorMap: root.styleName === "classic" ? wood : root.styleName === "modern" ? stone : earth
                roughness: .8
            }
        }
        Node {
        id: boardRoot
        Model {
            visible: !root.launchpad
            source: "#Cube"; y: -9; scale: Qt.vector3d(9,.3,9)
            materials: PrincipledMaterial { baseColor: root.styleName === "modern" ? "#292e35" : "#4e3020"; roughness: .35; metalness: root.styleName === "modern" ? .65 : .05 }
        }
        Model {
            visible: root.launchpad
            source: root.launchpad ? root.boardFolder + "housing.mesh" : ""
            materials: root.boardModel === "launchpad_s" ? silverHousing : texturedHousing
            PrincipledMaterial {
                id: silverHousing
                baseColor: "#a1a8ad"; metalness: 0; roughness: .48
                specularAmount: .5; clearcoatAmount: .16; clearcoatRoughnessAmount: .38
            }
            CasingMaterial {
                id: texturedHousing
                casingColor: "#181b20"
                grainStrength: root.lowDetail ? 0 : 1
            }
        }
        Model {
            visible: root.launchpad
            source: root.launchpad ? root.boardFolder + "controls.mesh" : ""
            materials: PrincipledMaterial { baseColor: "#647079"; roughness: .65 }
        }
        Model {
            visible: root.launchpad
            source: root.launchpad ? root.boardFolder + "details.mesh" : ""
            materials: PrincipledMaterial { baseColor: "#adb9bf"; roughness: .6 }
        }
        Model {
            visible: root.launchpad && root.boardModel !== "launchpad_pro"
            source: visible ? root.boardFolder + "accent.mesh" : ""
            materials: root.boardModel === "launchpad_s" ? satinAccent : texturedAccent
            PrincipledMaterial {
                id: satinAccent
                baseColor: "#252a31"; metalness: 0; roughness: .52
                specularAmount: .5; clearcoatAmount: .12; clearcoatRoughnessAmount: .42
            }
            CasingMaterial {
                id: texturedAccent
                casingColor: root.boardModel === "launchpad_mini_mk1" ? "#dd4a12" : "#181b20"
                grainStrength: root.lowDetail ? 0 : 1
            }
        }
        BoardPads { board: root; woodTexture: wood }
        // Four shadow-free sources approximate the pad array's upward light.
        // Scope them to the pieces so the casing and existing scene stay intact.
        Repeater3D {
            model: root.launchpad && !root.lowDetail ? 4 : 0
            SpotLight {
                required property int index
                scope: piecesRoot
                objectName: "chessPadSpill" + index
                x: index % 2 === 0 ? -220 : 220
                z: index < 2 ? 250 : -250
                y: 23
                eulerRotation.x: 90
                color: index < 2 ? (root.lighting.palette || {}).white || "#73dcff"
                    : (root.lighting.palette || {}).black || "#ffc58c"
                brightness: 1.2 * Math.sqrt(root.ledBrightness)
                coneAngle: 145; innerConeAngle: 100
                constantFade: 1; linearFade: .002; quadraticFade: 0
                castsShadow: false
            }
        }
        Node {
        id: piecesRoot
        Repeater3D {
            model: 64
            AnimatedChessSlot {
                required property int index
                objectName: "chessPieceSlot" + index
                board: root
                entry: root.visualSlots[index] || null
            }
        }
        }
        }
    }
    CameraDrift {
        id: cameraDrift; objectName: "chessCameraDrift"
        motionEnabled: root.lighting.camera_motion === true
        active: !root.dragSquare && root.visible && !!root.hostWindow && root.hostWindow.visible
                && root.hostWindow.visibility !== Window.Minimized
        pattern: root.lighting.camera_pattern || "orbit"
        speed: root.lighting.camera_speed === undefined ? 1 : root.lighting.camera_speed
    }
    MouseArea {
        id: cameraInput
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        preventStealing: true
        property real pressX: 0
        property real pressY: 0
        property real startYaw: 0
        property real startPitch: 0
        property bool dragged: false
        property bool pieceGesture: false
        onPressed: mouse => {
            pressX = mouse.x; pressY = mouse.y
            startYaw = root.yaw; startPitch = root.pitch
            dragged = false
            pieceGesture = mouse.button === Qt.LeftButton && root.beginDrag(mouse.x,mouse.y)
        }
        onPositionChanged: mouse => {
            if (!pressed) return
            const dx = mouse.x - pressX, dy = mouse.y - pressY
            if (dx * dx + dy * dy >= Qt.styleHints.startDragDistance * Qt.styleHints.startDragDistance)
                dragged = true
            if (pieceGesture) { root.updateDrag(mouse.x,mouse.y); return }
            if (dragged && (pressedButtons & Qt.RightButton)) {
                const yaw = ((startYaw - dx * .4 + 180) % 360 + 360) % 360 - 180
                root.orbitRequested(yaw, Math.max(20, Math.min(85, startPitch + dy * .3)))
            }
        }
        onCanceled: { dragged = true; root.cancelDrag(); pieceGesture=false }
        onReleased: mouse => { if (pieceGesture) root.finishDrag(mouse.x,mouse.y,dragged) }
        onClicked: mouse => {
            if (mouse.button !== Qt.LeftButton || dragged || pieceGesture) return
            const square = root.squareForPick(view.pick(mouse.x,mouse.y))
            if (square) root.squareClicked(square)
        }
        onWheel: wheel => {
            if (root.dragSquare) { wheel.accepted=true; return }
            const delta = wheel.angleDelta.y || wheel.pixelDelta.y
            if (wheel.modifiers & Qt.ControlModifier)
                root.fieldOfViewRequested(Math.max(30, Math.min(70, root.fieldOfView - delta / 60)))
            else
                root.distanceRequested(Math.max(850, Math.min(2100, root.distance - delta * .7)))
            wheel.accepted = true
        }
    }
}
