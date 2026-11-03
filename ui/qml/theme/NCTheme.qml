pragma Singleton

import QtQuick

QtObject {
    property string currentPreset: "midnight"
    property var palette: midnightPalette()

    readonly property string name: currentPreset === "custom" ? "Custom"
                                   : currentPreset === "dark_gray" ? "Dark Gray"
                                   : currentPreset === "forest" ? "Forest" : "Midnight"

    readonly property color window: palette.window
    readonly property color windowRaised: palette.windowRaised
    readonly property color surface: palette.surface
    readonly property color surfaceRaised: palette.surfaceRaised
    readonly property color surfaceSelected: palette.surfaceSelected
    readonly property color surfacePressed: palette.surfacePressed
    readonly property color overlay: palette.overlay

    readonly property color border: palette.border
    readonly property color borderSubtle: palette.borderSubtle
    readonly property color borderStrong: palette.borderStrong

    readonly property color text: palette.text
    readonly property color textSecondary: palette.textSecondary
    readonly property color textMuted: palette.textMuted
    readonly property color textInverse: palette.textInverse

    readonly property color accent: palette.accent
    readonly property color accentStrong: palette.accentStrong
    readonly property color accentSoft: palette.accentSoft
    readonly property color selection: palette.selection

    readonly property color success: "#34d399"
    readonly property color successSoft: "#113c34"
    readonly property color warning: "#f5b942"
    readonly property color warningSoft: "#453716"
    readonly property color error: "#ff6b7a"
    readonly property color errorSoft: "#49212a"
    readonly property color info: "#68a8ff"
    readonly property color infoSoft: "#1a3150"
    readonly property color disconnected: "#7d8da1"

    readonly property color focus: currentPreset === "custom" ? accent : "#79e8ff"
    readonly property color shadow: "#00000066"
    readonly property color scrim: "#02060bcc"

    function midnightPalette() {
        return {
            "window": "#07111d", "windowRaised": "#0a1624", "surface": "#0c1928",
            "surfaceRaised": "#122235", "surfaceSelected": "#103149", "surfacePressed": "#173b53",
            "overlay": "#06101bcc", "border": "#263b50", "borderSubtle": "#182b3e",
            "borderStrong": "#4d6f8d", "text": "#f4f8fc", "textSecondary": "#a7bad0",
            "textMuted": "#7188a1", "textInverse": "#031018", "accent": "#31d5f4",
            "accentStrong": "#00b8d9", "accentSoft": "#123c50", "selection": "#194c6a"
        }
    }

    function darkGrayPalette() {
        return {
            "window": "#11161d", "windowRaised": "#131a23", "surface": "#18202a",
            "surfaceRaised": "#223247", "surfaceSelected": "#233245", "surfacePressed": "#29405b",
            "overlay": "#0d1117d9", "border": "#283342", "borderSubtle": "#202b38",
            "borderStrong": "#4c6682", "text": "#f2f5f9", "textSecondary": "#b7c1ce",
            "textMuted": "#7f8791", "textInverse": "#0f141b", "accent": "#66d9ef",
            "accentStrong": "#35bfd7", "accentSoft": "#183b49", "selection": "#294b60"
        }
    }

    function forestPalette() {
        return {
            "window": "#1d2b25", "windowRaised": "#263830", "surface": "#31463d",
            "surfaceRaised": "#3b5549", "surfaceSelected": "#365f50", "surfacePressed": "#496d5d",
            "overlay": "#14201bd9", "border": "#486256", "borderSubtle": "#334b40",
            "borderStrong": "#759887", "text": "#f5fbf6", "textSecondary": "#c4d5ca",
            "textMuted": "#91aa9a", "textInverse": "#14231b", "accent": "#72e6b1",
            "accentStrong": "#49c892", "accentSoft": "#244f3e", "selection": "#376f58"
        }
    }

    function applyPreset(presetId) {
        const selected = String(presetId || "midnight").toLowerCase()
        currentPreset = selected === "dark_gray" || selected === "forest" ? selected : "midnight"
        palette = currentPreset === "dark_gray" ? darkGrayPalette()
                : currentPreset === "forest" ? forestPalette() : midnightPalette()
    }

    function colorValue(value, fallback) {
        if (value && value.r !== undefined)
            return value
        const hex = /^#[0-9a-f]{6}$/i.test(String(value)) ? String(value) : (fallback || "#000000")
        return Qt.rgba(parseInt(hex.slice(1, 3), 16) / 255,
                       parseInt(hex.slice(3, 5), 16) / 255,
                       parseInt(hex.slice(5, 7), 16) / 255, 1)
    }

    function mix(first, second, amount) {
        const a = colorValue(first), b = colorValue(second)
        return Qt.rgba(a.r + (b.r - a.r) * amount, a.g + (b.g - a.g) * amount,
                       a.b + (b.b - a.b) * amount, 1)
    }

    function luminance(value) {
        const c = colorValue(value)
        function linear(n) { return n <= 0.04045 ? n / 12.92 : Math.pow((n + 0.055) / 1.055, 2.4) }
        return 0.2126 * linear(c.r) + 0.7152 * linear(c.g) + 0.0722 * linear(c.b)
    }

    function contrast(first, second) {
        const a = luminance(first), b = luminance(second)
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
    }

    function readableText(background, preferred) {
        if (contrast(background, preferred) >= 4.5)
            return colorValue(preferred)
        return colorValue(contrast(background, "#ffffff") >= contrast(background, "#000000")
                          ? "#ffffff" : "#000000")
    }

    function readableSurface(background, foreground) {
        const target = luminance(foreground) > 0.179 ? "#000000" : "#ffffff"
        for (let i = 0; i <= 20; ++i) {
            const candidate = mix(background, target, i / 20)
            if (contrast(candidate, foreground) >= 4.5)
                return candidate
        }
        return colorValue(target)
    }

    function readableAccent(preferred, foreground, backgrounds) {
        for (let i = 0; i <= 20; ++i) {
            const candidate = mix(preferred, foreground, i / 20)
            if (backgrounds.every(function(background) { return contrast(candidate, background) >= 4.5 }))
                return candidate
        }
        return foreground
    }

    function customPalette(colors) {
        const c = colors || {}
        const windowColor = colorValue(c.window, "#07111d")
        const textColor = readableText(windowColor, colorValue(c.text, "#f4f8fc"))
        const panel = readableSurface(colorValue(c.surface, "#0c1928"), textColor)
        const requestedAccent = colorValue(c.accent, "#31d5f4")
        const windowRaisedColor = readableSurface(mix(windowColor, textColor, 0.04), textColor)
        const raised = readableSurface(mix(panel, textColor, 0.07), textColor)
        const selected = readableSurface(mix(panel, requestedAccent, 0.22), textColor)
        const pressed = readableSurface(mix(panel, requestedAccent, 0.32), textColor)
        const soft = readableSurface(mix(panel, requestedAccent, 0.16), textColor)
        const accentColor = readableAccent(requestedAccent, textColor,
                                          [windowColor, windowRaisedColor, panel, raised, selected, pressed, soft])
        const inverse = readableText(accentColor, "#ffffff")
        const accentStrongColor = mix(accentColor, luminance(inverse) > 0.179 ? "#000000" : "#ffffff", 0.12)
        return {
            window: windowColor, windowRaised: windowRaisedColor,
            surface: panel, surfaceRaised: raised, surfaceSelected: selected,
            surfacePressed: pressed,
            overlay: Qt.rgba(windowColor.r, windowColor.g, windowColor.b, 0.94),
            border: mix(panel, textColor, 0.28), borderSubtle: mix(panel, textColor, 0.14),
            borderStrong: mix(panel, textColor, 0.52),
            text: textColor, textSecondary: textColor, textMuted: textColor, textInverse: inverse,
            accent: accentColor, accentStrong: accentStrongColor,
            accentSoft: soft, selection: selected
        }
    }

    function applyAppearance(presetId, colors) {
        if (presetId === "custom") {
            currentPreset = "custom"
            palette = customPalette(colors)
        } else {
            applyPreset(presetId)
        }
    }

    function withAlpha(colorValue, alphaValue) {
        return Qt.rgba(colorValue.r, colorValue.g, colorValue.b, alphaValue)
    }

    function statusColor(status) {
        const key = String(status || "").toLowerCase()
        if (key === "success" || key === "ready" || key === "connected" || key === "active")
            return success
        if (key === "warning" || key === "needs-key" || key === "needs-model")
            return warning
        if (key === "error" || key === "failed")
            return error
        if (key === "info" || key === "loading" || key === "working")
            return info
        return disconnected
    }

    function statusSoftColor(status) {
        const key = String(status || "").toLowerCase()
        if (key === "success" || key === "ready" || key === "connected" || key === "active")
            return successSoft
        if (key === "warning" || key === "needs-key" || key === "needs-model")
            return warningSoft
        if (key === "error" || key === "failed")
            return errorSoft
        if (key === "info" || key === "loading" || key === "working")
            return infoSoft
        return surfaceRaised
    }
}
