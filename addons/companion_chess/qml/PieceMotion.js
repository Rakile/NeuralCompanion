.pragma library

// Visual identity only. The game snapshot remains the sole chess authority.
function metadata(game) {
    var moves = [], source = game && game.moves || []
    for (var i = 0; i < source.length; ++i) moves.push(String(source[i]))
    return {game_id: game && (game.game_id || game.id) || "", moves: moves}
}

function moveSources(slots, next, before, after) {
    before = metadata(before); after = metadata(after)
    var moves = after.moves, previous = before.moves
    if (!before.game_id || before.game_id !== after.game_id || moves.length !== previous.length + 1) return {}
    for (var i = 0; i < previous.length; ++i) if (previous[i] !== moves[i]) return {}
    var uci = moves[moves.length - 1]
    if (!/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci)) return {}
    var expected = {}, actual = {}, from = uci.slice(0,2), to = uci.slice(2,4)
    for (i = 0; i < slots.length; ++i) if (slots[i]) expected[slots[i].square] = slots[i].piece
    for (i = 0; i < next.length; ++i) actual[next[i].square] = next[i].piece
    var piece = expected[from]
    if (!piece || from === to) return {}
    var white = piece === piece.toUpperCase(), kind = piece.toLowerCase(), sources = {}
    if (expected[to] && (expected[to] === expected[to].toUpperCase()) === white) return {}
    if (kind === 'p' && from[0] !== to[0] && !expected[to]) {
        var captured = to[0] + from[1]
        if (expected[captured] !== (white ? 'p' : 'P')) return {}
        delete expected[captured]
    }
    if (kind === 'k' && from[0] === 'e' && from[1] === to[1] && (to[0] === 'g' || to[0] === 'c')) {
        var rookFrom = (to[0] === 'g' ? 'h' : 'a') + from[1]
        var rookTo = (to[0] === 'g' ? 'f' : 'd') + from[1]
        if (expected[rookFrom] !== (white ? 'R' : 'r') || expected[rookTo]) return {}
        expected[rookTo] = expected[rookFrom]; delete expected[rookFrom]
        sources[rookTo] = rookFrom
    }
    if (uci.length === 5) {
        if (kind !== 'p' || to[1] !== (white ? '8' : '1')) return {}
        piece = white ? uci[4].toUpperCase() : uci[4]
    }
    delete expected[from]; expected[to] = piece; sources[to] = from
    var keys = Object.keys(expected)
    if (keys.length !== Object.keys(actual).length) return {}
    for (i = 0; i < keys.length; ++i) if (expected[keys[i]] !== actual[keys[i]]) return {}
    return sources
}

function reconcile(previousSlots, next, previousMeta, nextMeta) {
    var slots = previousSlots || [], pieces = next || [], result = [], used = {}, matched = {}
    var sources = moveSources(slots, pieces, previousMeta, nextMeta)
    var changedGame = metadata(previousMeta).game_id !== metadata(nextMeta).game_id
    for (var s = 0; s < 64; ++s) result.push(null)
    function assign(index, slot, animate) {
        var p = pieces[index]
        result[slot] = {piece:p.piece, square:p.square, color:p.color || (p.piece === p.piece.toUpperCase() ? 'white' : 'black'),
                        animate:animate, snap:changedGame}
        used[slot] = true; matched[index] = true
    }
    // Reserve all stationary identities before considering arrivals or free slots.
    for (var i = 0; i < pieces.length; ++i) {
        for (s = 0; s < slots.length; ++s) {
            if (!used[s] && slots[s] && slots[s].square === pieces[i].square && slots[s].piece === pieces[i].piece) {
                assign(i,s,false); break
            }
        }
    }
    for (i = 0; i < pieces.length; ++i) {
        if (matched[i] || !sources[pieces[i].square]) continue
        for (s = 0; s < slots.length; ++s) {
            if (!used[s] && slots[s] && slots[s].square === sources[pieces[i].square]) {
                assign(i,s,true); break
            }
        }
    }
    for (i = 0; i < pieces.length; ++i) {
        if (matched[i]) continue
        for (s = 0; s < 64; ++s) if (!used[s]) { assign(i,s,false); break }
    }
    return result
}
