.pragma library

// Stable ordering preserves the original two choices and saved setting keys.
var keys = ["style", "launchpad_pro", "launchpad_s", "launchpad_mk2",
    "launchpad_mini_mk1", "launchpad_mini_mk2", "launchpad_mini_mk3",
    "launchpad_x", "launchpad_pro_mk3"]
var labels = ["Style default (wood / stone / earth)", "Launchpad Pro",
    "Launchpad S", "Launchpad MK2", "Launchpad Mini MK1", "Launchpad Mini MK2",
    "Launchpad Mini MK3", "Launchpad X", "Launchpad Pro MK3"]

function folder(key) {
    if (key === "launchpad_pro") return "../assets/launchpad/"
    return keys.indexOf(key) >= 2 ? "../assets/boards/" + key + "/" : ""
}
function index(key) { return Math.max(0, keys.indexOf(key)) }
// Match each existing hardware footprint; a small gap defines styled tiles.
function padWidth(key) {
    var widths={style:96,launchpad_pro:87.62,launchpad_s:88,launchpad_mk2:88,
        launchpad_mini_mk1:88,launchpad_mini_mk2:88,launchpad_mini_mk3:91,
        launchpad_x:93,launchpad_pro_mk3:90}
    return widths[key] === undefined ? 96 : widths[key]
}
// Pad tops stay Y19; place the existing table beneath each authored case.
function bottomY(key) {
    var thickness = {launchpad_s:82, launchpad_mk2:94, launchpad_mini_mk1:79,
        launchpad_mini_mk2:79, launchpad_mini_mk3:65, launchpad_x:60, launchpad_pro_mk3:65}
    return thickness[key] === undefined ? -17 : 12 - thickness[key]
}
