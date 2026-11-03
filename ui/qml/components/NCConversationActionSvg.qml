import QtQuick

Image {
    id: root

    property string actionKey: ""
    property string actionScope: "response"
    readonly property url iconSource: {
        switch (String(actionKey)) {
        case "pause_speech": return "../../../ui_icons/conversation_actions/01_pause.svg"
        case "resume_speech": return "../../../ui_icons/conversation_actions/01_play.svg"
        case "skip_speech": return "../../../ui_icons/conversation_actions/02_play_next.svg"
        case "skip_user_reply":
        case "end_waiting": return "../../../ui_icons/conversation_actions/03_message.svg"
        case "copy": return "../../../ui_icons/conversation_actions/04_copy.svg"
        case "replay": return "../../../ui_icons/conversation_actions/05_fast_forward_next.svg"
        case "edit":
        case "edit_draft": return "../../../ui_icons/conversation_actions/06_edit.svg"
        case "regenerate":
        case "retry_user_input": return "../../../ui_icons/conversation_actions/07_refresh.svg"
        case "delete": return "../../../ui_icons/conversation_actions/08_trash.svg"
        default: return ""
        }
    }

    source: iconSource
    sourceSize.width: 24
    sourceSize.height: 24
    fillMode: Image.PreserveAspectFit
    asynchronous: false
    cache: true
    smooth: true
    mipmap: true
    opacity: enabled ? 1.0 : 0.28
}
