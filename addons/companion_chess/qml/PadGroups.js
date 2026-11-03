.pragma library

// Stable semantic groups: dark/light checker, white/black occupied, target,
// pending highlight, selected. All material parameters remain shared per board.
function square(index) {
    return typeof index === 'number' && index >= 0 && index < 64 && index % 1 === 0
        ? 'abcdefgh'[index % 8] + String(Math.floor(index / 8) + 1) : ''
}

function groups(pieces, selected, highlight, targets, launchpad, path) {
    var result = [[],[],[],[],[],[],[]], occupied = {}
    if (path && path.length) result.push([])
    for (var i = 0; i < pieces.length; ++i)
        if (occupied[pieces[i].square] === undefined) occupied[pieces[i].square] = pieces[i].piece
    for (var index = 0; index < 64; ++index) {
        var name = square(index), occupant = occupied[name] || ''
        var group = name === selected ? 6 : name === highlight ? 5
            : targets.indexOf(name) >= 0 ? 4 : path && path.indexOf(name) >= 0 ? 7 : launchpad && occupant
            ? (occupant === occupant.toUpperCase() ? 2 : 3) : (index % 8 + Math.floor(index / 8)) % 2
        result[group].push(index)
    }
    return result
}

var roles = ['dark','light','white','black','target','pending','selected','path']
function colour(group, launchpad, style, palette) {
    var custom = palette && palette[roles[group]]
    if (typeof custom === 'string' && /^#[0-9a-fA-F]{6}$/.test(custom)) return custom
    var dark = launchpad ? '#243847' : style === 'modern' ? '#28303b' : '#65452e'
    var light = launchpad ? '#88b4c6' : style === 'modern' ? '#d8dfe5' : '#dfc396'
    return [dark,light,'#51cce8','#f5aa60','#7d9b70','#dca44a','#9dba69','#6a88ad'][group]
}

function route(game) {
    if (game.hardware && !game.pending) return []
    var moves=game.moves || [], uci=game.pending && game.pending.uci || moves[moves.length-1] || ''
    if (typeof uci !== 'string' || !/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci)) return []
    var from=uci.slice(0,2), to=uci.slice(2,4), x=from.charCodeAt(0)-97,y=Number(from[1])-1
    var dx=to.charCodeAt(0)-from.charCodeAt(0),dy=Number(to[1])-Number(from[1])
    if (dx && dy && Math.abs(dx)!==Math.abs(dy)) return [from,to]
    var count=Math.max(Math.abs(dx),Math.abs(dy)), result=[]
    for(var i=0;i<=count;++i) result.push('abcdefgh'[x+i*Math.sign(dx)]+String(y+i*Math.sign(dy)+1))
    return result
}

function pulse(phase, index, length) {
    return .55+.45*(.5+.5*Math.cos(2*Math.PI*(phase-index/Math.max(1,length))))
}
