pragma Singleton

import QtQuick

QtObject {
    readonly property string family: "Segoe UI Variable"
    readonly property string monoFamily: "Cascadia Mono"

    readonly property int displaySize: 28
    readonly property int titleSize: 22
    readonly property int headingSize: 17
    readonly property int bodySize: 14
    readonly property int labelSize: 13
    readonly property int captionSize: 12
    readonly property int microSize: 11

    readonly property int regular: Font.Normal
    readonly property int medium: Font.Medium
    readonly property int semibold: Font.DemiBold
    readonly property int bold: Font.Bold
}
