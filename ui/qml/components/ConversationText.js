.pragma library
.import "../workspaces/ConversationSpeechSync.js" as SpeechSync

function escapeRichText(value) {
    return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/\n/g, "<br/>")
}

function isBionicWordCharacter(character) {
    const value = String(character || "")
    if (!value.length)
        return false
    if (value === "'" || value === "’")
        return true
    const code = value.charCodeAt(0)
    return (code >= 48 && code <= 57)
            || value.toLocaleUpperCase() !== value.toLocaleLowerCase()
}

function bionicMessageText(value) {
    const text = String(value || "")
    let rendered = ""
    let index = 0
    while (index < text.length) {
        if (!isBionicWordCharacter(text[index])) {
            rendered += escapeRichText(text[index])
            index += 1
            continue
        }
        const start = index
        while (index < text.length && isBionicWordCharacter(text[index]))
            index += 1
        const word = text.slice(start, index)
        const emphasisLength = Math.max(1, Math.ceil(word.length / 2))
        rendered += "<b>" + escapeRichText(word.slice(0, emphasisLength)) + "</b>"
                  + escapeRichText(word.slice(emphasisLength))
    }
    return rendered
}

function conversationMessageRichText(value, bionic) {
    return bionic
           ? bionicMessageText(value) : escapeRichText(value)
}

function spokenWordBounds(value, progress, spokenText, spokenPrefix) {
    return SpeechSync.spokenWordBounds(value, progress, spokenText, spokenPrefix)
}

function highlightedMessageText(value, mode, style, progress, spokenText, bionic, colors, spokenPrefix) {
    const text = String(value || "")
    const bounds = spokenWordBounds(text, progress, spokenText, spokenPrefix)
    if (!text.length || bounds.end <= bounds.start)
        return conversationMessageRichText(text, bionic)
    const before = text.slice(0, bounds.start)
    const current = text.slice(bounds.start, bounds.end)
    const after = text.slice(bounds.end)
    const textColor = String(colors.text)
    const mutedColor = String(colors.muted)
    const accentColor = String(colors.accent)
    const selectedColor = String(colors.selected)
    const backgroundStyle = String(style || "classic") === "classic"
                          ? "; background-color:" + selectedColor : ""
    // Highlight styling must not change glyph metrics. A heavier active
    // word reflows every character after it as TTS advances.
    if (mode === "word") {
        return "<span style='color:" + textColor + "'>"
             + conversationMessageRichText(before, bionic)
             + "<span style='color:" + accentColor
             + backgroundStyle
             + "'>" + conversationMessageRichText(current, bionic) + "</span>"
             + conversationMessageRichText(after, bionic) + "</span>"
    }
    return "<span style='color:" + accentColor + "'>"
         + conversationMessageRichText(before, bionic)
         + "<span style='" + backgroundStyle
         + "'>" + conversationMessageRichText(current, bionic) + "</span>"
         + "<span style='color:" + mutedColor + "'>" + conversationMessageRichText(after, bionic) + "</span>"
         + "</span>"
}
