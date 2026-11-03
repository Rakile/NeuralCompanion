pragma Singleton

import QtQuick

QtObject {
    readonly property int space2: 2
    readonly property int space4: 4
    readonly property int space6: 6
    readonly property int space8: 8
    readonly property int space10: 10
    readonly property int space12: 12
    readonly property int space14: 14
    readonly property int space16: 16
    readonly property int space20: 20
    readonly property int space24: 24
    readonly property int space32: 32
    readonly property int space40: 40
    readonly property int space48: 48

    readonly property int radiusSmall: 6
    readonly property int radiusMedium: 9
    readonly property int radiusLarge: 12
    readonly property int radiusPill: 999

    readonly property int borderWidth: 1
    readonly property int focusWidth: 2
    readonly property int focusGap: 2

    readonly property int controlHeightCompact: 32
    readonly property int controlHeight: 38
    readonly property int controlHeightLarge: 44
    readonly property int iconButtonSize: 36

    readonly property int topBarHeight: 68
    readonly property int utilityBarHeight: 34
    readonly property int sectionRailWidth: 108
    readonly property int contextRailWidth: 214
    readonly property int detailMinimumWidth: 480
    readonly property int dialogMaximumWidth: 680

    readonly property int motionFast: 110
    readonly property int motionNormal: 160
    readonly property int motionSlow: 220

    readonly property int minimumWindowWidth: 1120
    readonly property int minimumWindowHeight: 720
}
