.pragma library

var yellow = "#FFE066"

function inTutorial(item) {
    for (var current = item; current; current = current.parent) {
        if (current.tutorialText !== undefined) return Boolean(current.tutorialText)
    }
    return false
}

function showButtons(bridge) {
    return !bridge || !bridge.tutorialLaunchers || bridge.tutorialLaunchers.buttons !== false
}

function showContext(bridge) {
    return !bridge || !bridge.tutorialLaunchers || bridge.tutorialLaunchers.context !== false
}
