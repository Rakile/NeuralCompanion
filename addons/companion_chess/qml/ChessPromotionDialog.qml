import QtQuick
import QtQuick.Layouts
import "../../../ui/qml/components" as NC
import "../../../ui/qml/theme" as Theme

NC.NCDialog {
    id: root
    objectName: "chessPromotionDialog"
    property var choices: []
    property bool canChoose: false
    property bool surfaceActive: true
    property bool autoOpen: true
    property string seenChoices: ""
    readonly property real previewHeight: Math.max(48, Math.min(140,
        ((parent ? parent.height : 600) - 180) / (width < 520 ? 2 : 1) - 38))
    signal pieceChosen(string uci)
    width: Math.min(Math.max(0, parent ? parent.width - 32 : 640), 640)
    x: Math.max(0, ((parent ? parent.width : width) - width) / 2)
    y: Math.max(0, ((parent ? parent.height : height) - height) / 2)
    title: "Promote your pawn"
    description: "Choose the piece your pawn becomes."
    footer: Item { implicitHeight: 8 }
    function sync(force) {
        if (!surfaceActive || !choices.length) {
            close()
            if (!choices.length) seenChoices = ""
            return
        }
        const key = JSON.stringify(choices)
        if (autoOpen && (force || key !== seenChoices)) {
            seenChoices = key
            open()
        }
    }
    onChoicesChanged: Qt.callLater(sync, false)
    onSurfaceActiveChanged: {
        if (!surfaceActive) close()
        else Qt.callLater(sync, true)
    }
    Component.onCompleted: Qt.callLater(sync, false)
    contentItem: GridLayout {
        columns: root.width < 520 ? 2 : 4
        columnSpacing: Theme.NCMetrics.space8; rowSpacing: Theme.NCMetrics.space8
        Repeater {
            model: root.choices
            NC.NCButton {
                id: card
                required property string modelData
                objectName: "chessPromote_" + modelData[4]
                Layout.fillWidth: true; Layout.minimumWidth: 0
                implicitWidth: 120; implicitHeight: root.previewHeight + 42
                text: ({q:"Queen",r:"Rook",b:"Bishop",n:"Knight"})[modelData[4]] || modelData
                toolTipText: "Promote to " + text.toLowerCase()
                enabled: root.canChoose
                contentItem: ColumnLayout {
                    spacing: 4
                    Image {
                        objectName: "chessPromotionImage_" + card.modelData[4]
                        Layout.fillWidth: true; Layout.preferredHeight: root.previewHeight
                        source: "../assets/promotion/" + (card.modelData[3] === "8" ? "white" : "black")
                            + "-" + card.modelData[4] + ".png"
                        fillMode: Image.PreserveAspectFit
                        sourceSize: Qt.size(320,320)
                    }
                    ChessLabel {
                        Layout.fillWidth: true
                        text: card.text; horizontalAlignment: Text.AlignHCenter
                        color: card.foregroundColor(); font.weight: Font.DemiBold
                    }
                }
                onClicked: root.pieceChosen(modelData)
            }
        }
    }
}
