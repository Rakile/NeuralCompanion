import QtQuick
import QtQuick.Controls
import "../theme" as Theme

// Opt-in multiline spelling. Preserve TextArea's native selection, undo and wrapping.
NCTextArea {
    id: root
    required property var bridge
    textFormat: TextEdit.PlainText
    readonly property var textEditingContextMenu: spellingMenu
    NCTextEditingContextMenu { id: spellingMenu; editor: root }
    readonly property bool spellcheckEnabled: (bridge.coreSettings || {}).spellcheck_enabled !== false
    readonly property string spellcheckLanguage: String((bridge.coreSettings || {}).spellcheck_language || "en_US")
    property var misspellings: []
    property string spellcheckMessage: ""
    property string checkedText: ""
    property var spellingWord: ({})
    property var spellingChoices: []

    function scheduleCheck() {
        misspellings = []
        spellingChoices = []
        spellingWord = ({})
        spellcheckMessage = ""
        checkTimer.restart()
        marks.requestPaint()
    }

    function checkNow() {
        checkTimer.stop()
        checkedText = text
        if (!spellcheckEnabled || inputMethodComposing
                || typeof bridge.checkComposerSpelling !== "function") {
            misspellings = []
            spellcheckMessage = ""
        } else {
            const result = bridge.checkComposerSpelling(text, spellcheckLanguage)
            misspellings = result.misspellings || []
            spellcheckMessage = String(result.message || "")
        }
        marks.requestPaint()
    }

    function prepareSuggestions(position) {
        checkNow()
        spellingWord = ({})
        spellingChoices = []
        if (!spellcheckEnabled || inputMethodComposing || readOnly)
            return
        for (const word of misspellings) {
            if (position >= word.start && position < word.start + word.length) {
                spellingWord = word
                spellingChoices = bridge.composerSpellingSuggestions(word.word, spellcheckLanguage)
                if (!spellingChoices.length)
                    spellingChoices = [""]
                return
            }
        }
    }

    function applySuggestion(value) {
        if (!value || !spellcheckEnabled || inputMethodComposing || checkedText !== text)
            return
        const word = spellingWord
        if (!word.word || !(word.length > 0) || text.slice(word.start, word.start + word.length) !== word.word)
            return
        // Editing clears the suggestion model and removes the triggering Action.
        // Close first, while that Action is still owned by the menu.
        textEditingContextMenu.close()
        forceActiveFocus()
        bridge.applyComposerSpelling(root, checkedText, word.start, word.length, value)
    }

    onTextChanged: scheduleCheck()
    onSpellcheckEnabledChanged: scheduleCheck()
    onSpellcheckLanguageChanged: scheduleCheck()
    onInputMethodComposingChanged: scheduleCheck()
    onCursorRectangleChanged: marks.requestPaint()
    onFontChanged: marks.requestPaint()
    onContentHeightChanged: marks.requestPaint()
    onContentWidthChanged: marks.requestPaint()
    Component.onCompleted: scheduleCheck()

    ContextMenu.menu: null
    // TextInput maps context-menu requests to the caret. Handle mouse requests
    // at their actual point; keep ContextMenu for the keyboard menu shortcut.
    TapHandler {
        acceptedButtons: Qt.RightButton
        onPressedChanged: {
            if (pressed && Application.styleHints.contextMenuTrigger === Qt.ContextMenuTrigger.Press)
                root.openSpellingMenu(point.position)
        }
        onTapped: {
            if (Application.styleHints.contextMenuTrigger === Qt.ContextMenuTrigger.Release)
                root.openSpellingMenu(point.position)
        }
    }
    ContextMenu.onRequested: position => {
        openSpellingMenu(position)
    }
    function openSpellingMenu(position) {
        prepareSuggestions(positionAt(position.x, position.y))
        textEditingContextMenu.popup(position)
    }

    Instantiator {
        model: root.spellingChoices
        delegate: Action {
            required property string modelData
            text: modelData ? qsTr("Replace with %1").arg(modelData) : qsTr("No spelling suggestions")
            enabled: modelData.length > 0
            onTriggered: root.applySuggestion(modelData)
        }
        onObjectAdded: (index, object) => root.textEditingContextMenu.insertAction(index, object)
        onObjectRemoved: (index, object) => root.textEditingContextMenu.removeAction(object)
    }

    Timer { id: checkTimer; interval: 180; onTriggered: root.checkNow() }

    FontMetrics { id: metrics; font: root.font }

    Canvas {
        id: marks
        objectName: "spellingUnderlines"
        anchors.fill: parent
        visible: root.spellcheckEnabled && !root.inputMethodComposing
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)
            ctx.save()
            ctx.beginPath()
            ctx.rect(root.leftPadding, 0, Math.max(0, width - root.leftPadding - root.rightPadding), height)
            ctx.clip()
            ctx.strokeStyle = Theme.NCTheme.error
            ctx.lineWidth = 1
            // TextEdit and TextInput expose different padded coordinates.
            // Calibrate against the native cursor rectangle, then handle each
            // glyph span so a misspelled word can cross a wrapped line.
            const caret = root.positionToRectangle(root.cursorPosition)
            const dx = root.cursorRectangle.x - caret.x
            const dy = root.cursorRectangle.y - caret.y
            for (const word of root.misspellings) {
                for (let i = word.start; i < word.start + word.length; ++i) {
                    const first = root.positionToRectangle(i)
                    const next = root.positionToRectangle(i + 1)
                    let endX = next.x
                    if (Math.abs(first.y - next.y) > 1) {
                        const advance = metrics.advanceWidth(root.text.slice(i, i + 1))
                        endX = first.x + (root.isRightToLeft(i, i + 1) ? -advance : advance)
                    }
                    const left = Math.max(root.leftPadding, dx + Math.min(first.x, endX))
                    const right = Math.min(width - root.rightPadding, dx + Math.max(first.x, endX))
                    const y = Math.min(height - 2, dy + first.y + first.height - 1)
                    ctx.beginPath()
                    ctx.moveTo(left, y)
                    for (let x = left + 2; x <= right; x += 2)
                        ctx.lineTo(x, y + ((Math.round((x - left) / 2) % 2) ? 1 : -1))
                    ctx.stroke()
                }
            }
            ctx.restore()
        }
    }
}
