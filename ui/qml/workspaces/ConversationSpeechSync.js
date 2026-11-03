.pragma library

function _appendWords(ranges, text, start, end) {
    let wordStart = -1
    for (let index = start; index < end; ++index) {
        const character = text.charAt(index)
        if (/\s/.test(character)) {
            if (wordStart >= 0) {
                // Standalone punctuation has no spoken word to align or time.
                if (_normalizedWord(text.slice(wordStart, index)).length)
                    ranges.push({ start: wordStart, end: index, text: text.slice(wordStart, index) })
                wordStart = -1
            }
        } else if (wordStart < 0) {
            wordStart = index
        }
    }
    if (wordStart >= 0 && _normalizedWord(text.slice(wordStart, end)).length)
        ranges.push({ start: wordStart, end: end, text: text.slice(wordStart, end) })
}

function speakableWordRanges(value) {
    const text = String(value || "")
    const ranges = []
    let plainStart = 0
    let index = 0
    while (index < text.length) {
        if (text.charAt(index) !== "[") {
            ++index
            continue
        }
        const bracketEnd = text.indexOf("]", index + 1)
        if (bracketEnd < 0) {
            ++index
            continue
        }
        _appendWords(ranges, text, plainStart, index)
        if (text.charAt(bracketEnd + 1) === "(") {
            const linkEnd = text.indexOf(")", bracketEnd + 2)
            if (linkEnd >= 0) {
                _appendWords(ranges, text, index + 1, bracketEnd)
                index = linkEnd + 1
                plainStart = index
                continue
            }
        }
        index = bracketEnd + 1
        plainStart = index
    }
    _appendWords(ranges, text, plainStart, text.length)
    return ranges
}

function _normalizedWord(value) {
    return String(value || "")
        .toLocaleLowerCase()
        .replace(/^[\s.,!?;:"'`*_(){}<>\-–—…]+/, "")
        .replace(/[\s.,!?;:"'`*_(){}<>\-–—…]+$/, "")
}

function _wordWeight(range) {
    const raw = String(range && range.text || "")
    const length = Math.max(1, _normalizedWord(raw).length)
    let weight = 0.19 + (Math.min(length, 14) * 0.025)
    if (/[.!?]["')\]}]*$/.test(raw))
        weight += 0.16
    else if (/[;:]["')\]}]*$/.test(raw))
        weight += 0.08
    return weight
}

function _wordIndexForProgress(ranges, progress) {
    if (!ranges.length)
        return -1
    const bounded = Math.max(0, Math.min(Number(progress || 0), 0.999999))
    let total = 0
    for (let index = 0; index < ranges.length; ++index)
        total += _wordWeight(ranges[index])
    const target = total * bounded
    let elapsed = 0
    for (let index = 0; index < ranges.length; ++index) {
        elapsed += _wordWeight(ranges[index])
        if (target < elapsed)
            return index
    }
    return ranges.length - 1
}

function _matchingStart(displayRanges, spokenRanges) {
    if (!displayRanges.length || !spokenRanges.length)
        return -1
    let bestStart = -1
    let bestScore = 0
    for (let start = 0; start < displayRanges.length; ++start) {
        let score = 0
        while (start + score < displayRanges.length && score < spokenRanges.length) {
            const displayWord = _normalizedWord(displayRanges[start + score].text)
            const spokenWord = _normalizedWord(spokenRanges[score].text)
            if (!displayWord.length || displayWord !== spokenWord)
                break
            ++score
        }
        if (score > bestScore) {
            bestStart = start
            bestScore = score
        }
    }
    return bestScore === spokenRanges.length ? bestStart : -1
}

function spokenWordBounds(value, progress, spokenText, spokenPrefix) {
    const text = String(value || "")
    const displayRanges = speakableWordRanges(text)
    if (!displayRanges.length)
        return ({ start: 0, end: 0 })

    const currentSpokenText = String(spokenText || "")
    const spokenRanges = speakableWordRanges(currentSpokenText)
    if (!spokenRanges.length)
        return ({ start: 0, end: 0 })
    // Rooms know the delivered prefix before this audio chunk. Match that
    // context as well so repeated phrases stay on the current occurrence,
    // while keeping the same word weighting as Main chat's current chunk.
    const prefix = String(spokenPrefix || "")
    if (prefix.length) {
        const prefixRanges = speakableWordRanges(prefix)
        const combinedRanges = speakableWordRanges(prefix + " " + currentSpokenText)
        const combinedStart = _matchingStart(displayRanges, combinedRanges)
        const chunkIndex = _wordIndexForProgress(spokenRanges, progress)
        const index = combinedStart + prefixRanges.length + chunkIndex
        if (combinedStart < 0 || chunkIndex < 0 || index >= displayRanges.length)
            return ({ start: 0, end: 0 })
        return displayRanges[index]
    }
    let targetIndex = -1
    if (spokenRanges.length) {
        const segmentStart = _matchingStart(displayRanges, spokenRanges)
        const spokenIndex = _wordIndexForProgress(spokenRanges, progress)
        if (segmentStart >= 0 && spokenIndex >= 0)
            targetIndex = Math.min(displayRanges.length - 1, segmentStart + spokenIndex)
    }
    if (targetIndex < 0)
        return ({start: 0, end: 0})
    return displayRanges[Math.max(0, Math.min(targetIndex, displayRanges.length - 1))]
}
