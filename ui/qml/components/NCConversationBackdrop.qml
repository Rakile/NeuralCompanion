import QtQuick
import QtQuick.Effects
import "../theme" as Theme

Item {
    id: root

    property string style: "original"
    property url backgroundUrl: ""

    readonly property bool frameVisible: style !== "original"
    readonly property bool backgroundVisible: String(backgroundUrl).length > 0
    readonly property int frameInset: style === "recessed" ? 6
                                       : frameVisible ? 8 : 0

    Rectangle {
        anchors.fill: frame
        anchors.margins: -Theme.NCMetrics.space6
        radius: frame.radius + Theme.NCMetrics.space6
        color: "transparent"
        border.width: root.style === "glass" ? Theme.NCMetrics.space4
                                              : Theme.NCMetrics.space2
        border.color: root.style === "glass"
                      ? Theme.NCTheme.withAlpha("#000000", 0.28)
                      : Theme.NCTheme.withAlpha("#000000", 0.18)
        opacity: root.style === "vignette" ? 0.72 : 1.0
        visible: root.frameVisible
    }

    Rectangle {
        id: roundedMask
        anchors.fill: frame
        radius: frame.radius
        color: "white"
        visible: frame.layer.enabled
    }

    ShaderEffectSource {
        id: maskTexture
        sourceItem: roundedMask
        hideSource: true
        visible: false
        live: frame.layer.enabled
    }

    Rectangle {
        id: frame
        anchors.fill: parent
        anchors.margins: root.frameInset
        radius: Theme.NCMetrics.radiusLarge
        color: root.style === "glass"
               ? Theme.NCTheme.withAlpha(Theme.NCTheme.windowRaised, 0.78)
               : root.style === "recessed"
                 ? Theme.NCTheme.withAlpha("#020711", 0.88)
                 : Theme.NCTheme.withAlpha(Theme.NCTheme.window, 0.72)
        border.width: root.style === "original" ? 0
                      : root.style === "recessed" ? Theme.NCMetrics.focusWidth
                                                   : Theme.NCMetrics.borderWidth
        border.color: root.style === "glass"
                      ? Theme.NCTheme.withAlpha(Theme.NCTheme.accent, 0.58)
                      : root.style === "recessed"
                        ? Theme.NCTheme.withAlpha(Theme.NCTheme.borderStrong, 0.88)
                        : Theme.NCTheme.withAlpha(Theme.NCTheme.accent, 0.34)
        clip: true
        visible: root.frameVisible || root.backgroundVisible
        // Item clipping is rectangular; mask the image and tint to the same radius.
        layer.enabled: visible && GraphicsInfo.api !== GraphicsInfo.Software
        layer.smooth: true
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: maskTexture
            autoPaddingEnabled: false
        }

        Image {
            anchors.fill: parent
            source: root.backgroundUrl
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
            opacity: root.style === "vignette" ? 0.56 : 0.42
            visible: root.backgroundVisible
        }

        Rectangle {
            anchors.fill: parent
            color: root.style === "glass"
                   ? Theme.NCTheme.withAlpha(Theme.NCTheme.window, 0.48)
                   : root.style === "recessed"
                     ? Theme.NCTheme.withAlpha("#020711", 0.44)
                     : root.style === "original"
                       ? Theme.NCTheme.withAlpha(Theme.NCTheme.window, 0.48)
                       : Theme.NCTheme.withAlpha(Theme.NCTheme.window, 0.24)
        }

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: Theme.NCMetrics.space8
            border.color: Theme.NCTheme.withAlpha("#000000", 0.34)
            radius: frame.radius
            visible: root.style === "vignette"
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: Theme.NCMetrics.space2
            radius: Math.max(0, frame.radius - Theme.NCMetrics.space2)
            color: "transparent"
            border.width: Theme.NCMetrics.borderWidth
            border.color: Theme.NCTheme.withAlpha(Theme.NCTheme.accent, 0.16)
            visible: root.style === "recessed"
        }
    }
}
