import QtQuick
import QtQuick.Controls
import "../theme" as Theme

Label {
    id: root
    property var values: ({})
    readonly property int batchSize: Math.max(1, Number(values.long_term_memory_archive_batch_turns || 8))
    readonly property int contextSize: Math.max(4, Number(values.chat_context_window_messages || 20))
    visible: Boolean(values.long_term_memory_auto_archive_enabled) && contextSize < batchSize-1
    text: qsTr("Some recent messages may temporarily fall outside both chat context and indexed memory. Saving the conversation still preserves them.\nWith batches of %1, use at least %2 context messages to cover the usual waiting period.").arg(batchSize).arg(batchSize-1)
    color: Theme.NCTheme.warning
    font.pixelSize: Theme.NCTypography.captionSize
    wrapMode: Text.Wrap
}
