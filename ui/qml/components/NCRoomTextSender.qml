pragma ComponentBehavior: Bound
import QtQuick

NCComboBox {
    id: root
    required property var room
    signal senderSelected(string senderId)
    readonly property var senders: [{id: "", name: qsTr("Choose sender…")}].concat(room.text_senders || [])
    label: qsTr("Send as")
    toolTipText: qsTr("Choose a human participant or NC operator as the author of typed room context. Sending does not post a Discord text-channel message.")
    model: senders
    textRole: "name"
    valueRole: "id"
    displayText: currentIndex > 0 ? qsTr("Send as: %1").arg(currentText) : currentText
    currentIndex: Math.max(0, senders.findIndex(person => String(person.id) === String(room.text_sender_id || "")))
    enabled: !Boolean(room.stopping) && String(room.phase || "") !== "starting"
    onActivated: index => {
        if (index > 0 && index < senders.length) senderSelected(String(senders[index].id))
    }
}
