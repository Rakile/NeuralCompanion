import QtQuick
import "../theme" as Theme

// Presentation only: conversation actions and state remain with each caller.
Rectangle {
    id: root
    property bool assistantResponse: true
    property bool userEdited: false
    property bool draftSelected: false
    property bool bordersEnabled: true
    property bool transparentCards: false
    property color assistantBorderColor: Theme.NCTheme.border
    readonly property int contentPadding: Theme.NCMetrics.space10

    radius: Theme.NCMetrics.radiusLarge
    color: draftSelected
           ? Theme.NCTheme.withAlpha(Theme.NCTheme.accentStrong, 0.18)
           : transparentCards
             ? Theme.NCTheme.withAlpha(assistantResponse ? Theme.NCTheme.surface : Theme.NCTheme.surfaceSelected,
                                      assistantResponse ? 0.18 : 0.24)
             : assistantResponse ? Theme.NCTheme.surface : Theme.NCTheme.surfaceSelected
    border.color: draftSelected ? Theme.NCTheme.accentStrong : userEdited ? Theme.NCTheme.warning
                  : assistantResponse ? assistantBorderColor : Theme.NCTheme.accentStrong
    border.width: draftSelected ? Theme.NCMetrics.focusWidth : bordersEnabled
                  ? userEdited ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                  : userEdited ? Theme.NCMetrics.borderWidth : 0
}
