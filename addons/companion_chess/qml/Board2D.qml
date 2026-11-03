import QtQuick
import '../../../ui/qml/theme' as Theme

Item {
    id: root
    objectName: "board2d"

    property var pieces: []
    property string selected: ""
    property var targets: []
    property string orientation: "white"
    property string highlight: ""

    signal squareClicked(string square)

    readonly property real cellSize: Math.max(0, Math.min(width, height) - 52) / 8
    readonly property real boardSize: cellSize * 8
    readonly property real marginSize: 26
    readonly property real boardX: Math.max(0, (width - boardSize) / 2)
    readonly property real boardY: Math.max(0, (height - boardSize) / 2)

    readonly property color lightColor: "#e4d4b6"
    readonly property color darkColor: "#80674f"
    readonly property color borderColor: "#3b2b20"
    readonly property color whitePieceColor: "#fffaf0"
    readonly property color blackPieceColor: "#171a20"

    readonly property bool flipped: orientation === "black"

    readonly property var files: ["a", "b", "c", "d", "e", "f", "g", "h"]
    readonly property var ranks: ["8", "7", "6", "5", "4", "3", "2", "1"]

    function squareName(fileIndex, rankIndex) {
        var f = flipped ? 7 - fileIndex : fileIndex
        var r = flipped ? 7 - rankIndex : rankIndex
        if (f < 0 || f > 7 || r < 0 || r > 7)
            return ""
        return files[f] + ranks[r]
    }

    function pieceAt(sq) {
        var list = pieces
        if (!list || !list.length)
            return null
        for (var i = 0; i < list.length; i++) {
            var p = list[i]
            if (p && p.square === sq)
                return p
        }
        return null
    }

    function isTargetSquare(sq) {
        var t = targets
        if (!t || !t.length)
            return false
        for (var i = 0; i < t.length; i++) {
            if (t[i] === sq)
                return true
        }
        return false
    }

    function glyphFor(code) {
        if (!code || code.length === 0)
            return ""
        switch (code) {
        case "P": return "\u2659"
        case "N": return "\u2658"
        case "B": return "\u2657"
        case "R": return "\u2656"
        case "Q": return "\u2655"
        case "K": return "\u2654"
        case "p": return "\u265F"
        case "n": return "\u265E"
        case "b": return "\u265D"
        case "r": return "\u265C"
        case "q": return "\u265B"
        case "k": return "\u265A"
        default: return ""
        }
    }

    function isBlackCode(code) {
        return code && code.length === 1 && code >= "a" && code <= "z"
    }

    function accessibleNameFor(sq) {
        var p = pieceAt(sq)
        if (!p || !p.piece)
            return sq
        var name = ""
        switch (p.piece) {
        case "P": case "p": name = qsTr("pawn"); break
        case "N": case "n": name = qsTr("knight"); break
        case "B": case "b": name = qsTr("bishop"); break
        case "R": case "r": name = qsTr("rook"); break
        case "Q": case "q": name = qsTr("queen"); break
        case "K": case "k": name = qsTr("king"); break
        default: name = p.piece; break
        }
        return sq + ", " + name
    }

    Rectangle {
        id: boardBg
        x: root.boardX
        y: root.boardY
        width: root.boardSize
        height: root.boardSize
        color: root.borderColor
        visible: root.boardSize > 0
        clip: false

        Grid {
            id: cells
            x: 0
            y: 0
            columns: 8
            rows: 8

            Repeater {
                model: 64

                Rectangle {
                    id: cell
                    readonly property int idx: index
                    readonly property int fileIndex: idx % 8
                    readonly property int rankIndex: Math.floor(idx / 8)
                    readonly property string square: root.squareName(fileIndex, rankIndex)
                    readonly property var occupant: root.pieceAt(square)
                    readonly property bool isSelected: root.selected !== "" && root.selected === square
                    readonly property bool isTarget: root.isTargetSquare(square)
                    readonly property bool isHighlight: root.highlight !== "" && root.highlight === square

                    objectName: "square_" + square
                    width: root.cellSize
                    height: root.cellSize
                    color: ((fileIndex + rankIndex) % 2 === 0) ? root.lightColor : root.darkColor
                    visible: root.cellSize > 0 && square !== ""
                    activeFocusOnTab: true

                    Accessible.role: Accessible.Button
                    Accessible.name: root.accessibleNameFor(square)

                    Rectangle {
                        anchors.fill: parent
                        visible: cell.isHighlight
                        color: Theme.NCTheme.accent
                        opacity: 0.35
                    }

                    Rectangle {
                        anchors.fill: parent
                        visible: cell.isSelected
                        color: "transparent"
                        border.color: Theme.NCTheme.focus
                        border.width: Math.max(2, cell.width * 0.06)
                    }

                    Rectangle {
                        anchors.centerIn: parent
                        width: cell.width * 0.28
                        height: width
                        radius: width / 2
                        visible: cell.isTarget
                        color: "transparent"
                        border.color: Theme.NCTheme.focus
                        border.width: Math.max(1.5, cell.width * 0.05)
                        opacity: 0.85
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: cell.occupant !== null && cell.occupant !== undefined && cell.occupant.piece
                        text: cell.occupant ? root.glyphFor(cell.occupant.piece) : ""
                        font.family: "Segoe UI Symbol"
                        font.pixelSize: Math.max(1, cell.width * 0.68)
                        color: cell.occupant && root.isBlackCode(cell.occupant.piece) ? root.blackPieceColor : root.whitePieceColor
                        style: Text.Outline
                        styleColor: cell.occupant && root.isBlackCode(cell.occupant.piece) ? "#4a4a4a" : "#2a2a2a"
                    }

                    Rectangle {
                        anchors.fill: parent
                        color: "transparent"
                        radius: 0
                        border.width: cell.activeFocus ? Math.max(2, cell.width * 0.05) : 0
                        border.color: Theme.NCTheme.focus
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            cell.forceActiveFocus()
                            root.squareClicked(cell.square)
                        }
                    }

                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            root.squareClicked(cell.square)
                            event.accepted = true
                        }
                    }

                    Keys.onSpacePressed: function(event) {
                        root.squareClicked(cell.square)
                        event.accepted = true
                    }
                }
            }
        }

        Repeater {
            model: 8

            Text {
                property int i: index
                x: i * root.cellSize
                y: -root.marginSize
                width: root.cellSize
                height: root.marginSize
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                text: root.flipped ? root.files[7 - i] : root.files[i]
                font.family: "Segoe UI"
                font.pixelSize: Math.max(1, root.marginSize * 0.6)
                color: Theme.NCTheme.textMuted !== undefined ? Theme.NCTheme.textMuted : "#4a4a4a"
                visible: root.cellSize > 0
            }
        }

        Repeater {
            model: 8

            Text {
                property int i: index
                x: -root.marginSize
                y: i * root.cellSize
                width: root.marginSize
                height: root.cellSize
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                text: root.flipped ? root.ranks[7 - i] : root.ranks[i]
                font.family: "Segoe UI"
                font.pixelSize: Math.max(1, root.marginSize * 0.6)
                color: Theme.NCTheme.textMuted !== undefined ? Theme.NCTheme.textMuted : "#4a4a4a"
                visible: root.cellSize > 0
            }
        }

        Repeater {
            model: 8

            Text {
                property int i: index
                x: i * root.cellSize
                y: root.boardSize + (root.marginSize - height) / 2
                width: root.cellSize
                height: root.marginSize
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                text: root.flipped ? root.files[7 - i] : root.files[i]
                font.family: "Segoe UI"
                font.pixelSize: Math.max(1, root.marginSize * 0.6)
                color: Theme.NCTheme.textMuted !== undefined ? Theme.NCTheme.textMuted : "#4a4a4a"
                visible: root.cellSize > 0
            }
        }

        Repeater {
            model: 8

            Text {
                property int i: index
                x: root.boardSize + (root.marginSize - width) / 2
                y: i * root.cellSize
                width: root.marginSize
                height: root.cellSize
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                text: root.flipped ? root.ranks[7 - i] : root.ranks[i]
                font.family: "Segoe UI"
                font.pixelSize: Math.max(1, root.marginSize * 0.6)
                color: Theme.NCTheme.textMuted !== undefined ? Theme.NCTheme.textMuted : "#4a4a4a"
                visible: root.cellSize > 0
            }
        }
    }
}
