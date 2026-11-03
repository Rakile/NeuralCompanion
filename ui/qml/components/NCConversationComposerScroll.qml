import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

// Share the growing, bounded input viewport without sharing submission behavior.
ScrollView {
    id: root
    property Item editor: null
    readonly property real minimumComposerHeight: editor && editor.minimumComposerHeight !== undefined
        ? editor.minimumComposerHeight : Theme.NCMetrics.controlHeight
    readonly property real maximumComposerHeight: editor && editor.maximumComposerHeight !== undefined
        ? editor.maximumComposerHeight : Math.ceil(composerMetrics.lineSpacing) * 14
            + (editor ? editor.topPadding + editor.bottomPadding : Theme.NCMetrics.space16)

    FontMetrics { id: composerMetrics; font: root.editor ? root.editor.font : Qt.font({pixelSize: Theme.NCTypography.bodySize}) }
    Layout.fillWidth: true
    Layout.minimumHeight: minimumComposerHeight
    Layout.preferredHeight: Math.min(editor ? editor.implicitHeight : minimumComposerHeight, maximumComposerHeight)
    Layout.maximumHeight: maximumComposerHeight
    contentWidth: availableWidth
    clip: true
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ScrollBar.vertical.policy: ScrollBar.vertical.size < 1.0 ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
}
