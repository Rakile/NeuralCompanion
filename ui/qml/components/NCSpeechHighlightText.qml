pragma ComponentBehavior: Bound

import QtQuick
import "../theme" as Theme

Item {
    id: root

    property string plainText: ""
    property string renderedText: plainText
    property bool highlightActive: false
    property int highlightStart: 0
    property int highlightEnd: 0
    property string highlightStyle: "classic"
    property color textColor: Theme.NCTheme.text
    property string fontFamily: Theme.NCTypography.family
    property bool bionicReading: false
    property int textPixelSize: 16
    // Optional for room snapshots, which can refresh throughout a mouse selection.
    property bool preserveSelection: false
    property alias font: contentText.font
    property alias color: contentText.color
    readonly property string text: plainText
    readonly property real naturalTextWidth: contentText.implicitWidth
    property string documentText: ""
    property string documentPlainText: ""
    property bool documentReady: false
    readonly property bool selectionActive: contentText.selectedText.length > 0

    readonly property int safeStart: Math.max(0, Math.min(plainText.length, highlightStart))
    readonly property int safeEnd: Math.max(safeStart, Math.min(plainText.length, highlightEnd))
    readonly property rect startRectangle: textRectangle(safeStart)
    readonly property rect endRectangle: textRectangle(Math.max(safeStart, safeEnd - 1))
    readonly property bool singleLineHighlight: Math.abs(startRectangle.y - endRectangle.y) < 1
    readonly property real plateWidth: Math.max(
                                                  0,
                                                  endRectangle.x + endRectangle.width
                                                  - startRectangle.x + Theme.NCMetrics.space8)
    readonly property real plateHeight: Math.max(
                                                   startRectangle.height,
                                                   endRectangle.height) + Theme.NCMetrics.space4
    readonly property bool customHighlightVisible: highlightActive
                                                        && highlightStyle !== "classic"
                                                        && safeEnd > safeStart
                                                        && singleLineHighlight
                                                        && plateWidth > 0
    readonly property bool richDocumentActive: contentText.textFormat === TextEdit.RichText
    readonly property string displayText: highlightActive || bionicReading
                                                ? renderedText
                                                : escapeRichText(plainText)

    implicitHeight: contentText.contentHeight

    function textRectangle(position) {
        // Native geometry queries can force layout while a newly realized
        // TextEdit is still initializing, leaving its rich document empty.
        if (!documentReady)
            return Qt.rect(0, 0, 0, 0)
        // positionToRectangle() itself has no notify signal. Track the document
        // and its layout so a width/font reflow also moves the highlight plate.
        const document = contentText.text
        const layoutWidth = contentText.width
        const layoutHeight = contentText.contentHeight
        const layoutContentWidth = contentText.contentWidth
        const layoutFont = contentText.font
        return contentText.positionToRectangle(position)
    }

    onDisplayTextChanged: {
        // Progress-only styling may wait for a selection, but authoritative text
        // changes (including an interrupted preview) must replace the document.
        if (!preserveSelection || !selectionActive || documentPlainText !== plainText) {
            documentPlainText = plainText
            documentText = displayText
        }
    }
    onSelectionActiveChanged: {
        if (!selectionActive) documentText = displayText
    }
    Component.onCompleted: { documentPlainText = plainText; documentText = displayText }

    function escapeRichText(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/\n/g, "<br/>")
    }

    function alphaColor(source, alpha) {
        return Qt.rgba(source.r, source.g, source.b, alpha)
    }

    Rectangle {
        id: outerAura
        visible: root.customHighlightVisible && root.highlightStyle === "glow"
        x: root.startRectangle.x - Theme.NCMetrics.space8
        y: root.startRectangle.y - Theme.NCMetrics.space4
        width: root.plateWidth + Theme.NCMetrics.space8
        height: root.plateHeight + Theme.NCMetrics.space4
        radius: Theme.NCMetrics.radiusMedium
        color: root.alphaColor(Theme.NCTheme.accent, 0.07)
        border.width: 0
        z: 0
    }

    Rectangle {
        id: innerAura
        visible: root.customHighlightVisible && root.highlightStyle === "glow"
        x: root.startRectangle.x - Theme.NCMetrics.space6
        y: root.startRectangle.y - Theme.NCMetrics.space2
        width: root.plateWidth + Theme.NCMetrics.space4
        height: root.plateHeight
        radius: Theme.NCMetrics.radiusMedium
        color: root.alphaColor(Theme.NCTheme.accent, 0.12)
        border.width: 0
        z: 0
    }

    Rectangle {
        id: highlightPlate
        visible: root.customHighlightVisible
        x: root.startRectangle.x - Theme.NCMetrics.space4
        y: root.startRectangle.y
        width: root.plateWidth
        height: root.plateHeight
        radius: root.highlightStyle === "rounded"
                ? Theme.NCMetrics.radiusSmall : Theme.NCMetrics.radiusMedium
        color: root.highlightStyle === "rounded"
               ? Theme.NCTheme.surfaceSelected
               : root.alphaColor(Theme.NCTheme.accent, 0.16)
        border.width: root.highlightStyle === "rounded" ? Theme.NCMetrics.borderWidth : 0
        border.color: root.alphaColor(Theme.NCTheme.accent, 0.45)
        clip: true
        z: 1

        Rectangle {
            id: flowCurrent
            visible: root.highlightStyle === "flow"
            width: Math.max(14, highlightPlate.width * 0.32)
            height: highlightPlate.height * 1.8
            y: -highlightPlate.height * 0.4
            radius: Theme.NCMetrics.radiusSmall
            rotation: 12
            color: root.alphaColor(Theme.NCTheme.accent, 0.38)

            NumberAnimation on x {
                from: -flowCurrent.width
                to: highlightPlate.width + flowCurrent.width
                duration: 1250
                loops: Animation.Infinite
                running: highlightPlate.visible && flowCurrent.visible
            }
        }

        Rectangle {
            visible: root.highlightStyle === "flow"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: Theme.NCMetrics.space6
            anchors.rightMargin: Theme.NCMetrics.space6
            height: Theme.NCMetrics.borderWidth
            radius: Theme.NCMetrics.radiusPill
            color: Theme.NCTheme.accent
        }
    }

    TextEdit {
        id: contentText
        Component.onCompleted: root.documentReady = true
        objectName: "speechHighlightContent"
        anchors.left: parent.left
        anchors.right: parent.right
        text: root.documentText
        color: root.textColor
        selectionColor: Theme.NCTheme.selection
        selectedTextColor: Theme.NCTheme.text
        font.family: root.fontFamily
        font.pixelSize: root.textPixelSize
        readOnly: true
        selectByMouse: true
        activeFocusOnPress: true
        wrapMode: TextEdit.WrapAtWordBoundaryOrAnywhere
        // Keep one document format for the component lifetime. Switching a
        // QTextDocument from rich to plain exposes Qt's normalized HTML source.
        textFormat: TextEdit.RichText
        z: 2
    }
}
