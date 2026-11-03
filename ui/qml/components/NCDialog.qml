import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Dialog {
    id: root

    property string description: ""
    property string acceptText: qsTr("Continue")
    property string rejectText: qsTr("Cancel")
    property string acceptTone: "primary"
    property bool acceptEnabled: true
    property int chromeInset: Theme.NCMetrics.space20

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    width: Math.min(parent ? parent.width - Theme.NCMetrics.space40 : Theme.NCMetrics.dialogMaximumWidth,
                    Theme.NCMetrics.dialogMaximumWidth)
    padding: Theme.NCMetrics.space20
    standardButtons: Dialog.NoButton

    background: Rectangle {
        radius: Theme.NCMetrics.radiusLarge
        color: Theme.NCTheme.surface
        border.width: Theme.NCMetrics.focusWidth
        border.color: Theme.NCTheme.borderStrong
    }

    header: Item {
        implicitWidth: headerLayout.implicitWidth + root.chromeInset * 2
        implicitHeight: headerLayout.implicitHeight
                        + root.chromeInset + Theme.NCMetrics.space8

        ColumnLayout {
            id: headerLayout
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: root.chromeInset
            anchors.rightMargin: root.chromeInset
            anchors.topMargin: root.chromeInset
            spacing: Theme.NCMetrics.space6

            Label {
                Layout.fillWidth: true
                text: root.title
                color: Theme.NCTheme.text
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.titleSize
                font.weight: Theme.NCTypography.semibold
                wrapMode: Text.Wrap
            }

            Label {
                Layout.fillWidth: true
                text: root.description
                color: Theme.NCTheme.textSecondary
                font.family: Theme.NCTypography.family
                font.pixelSize: Theme.NCTypography.bodySize
                wrapMode: Text.Wrap
                visible: text.length > 0
            }
        }
    }

    footer: Item {
        implicitWidth: footerLayout.implicitWidth + root.chromeInset * 2
        implicitHeight: footerLayout.implicitHeight
                        + Theme.NCMetrics.space8 + root.chromeInset

        RowLayout {
            id: footerLayout
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: root.chromeInset
            anchors.rightMargin: root.chromeInset
            anchors.topMargin: Theme.NCMetrics.space8
            spacing: Theme.NCMetrics.space8
            layoutDirection: Qt.RightToLeft

            NCButton {
                text: root.acceptText
                tone: root.acceptTone
                enabled: root.acceptEnabled
                onClicked: root.accept()
            }

            NCButton {
                text: root.rejectText
                visible: text.length > 0
                onClicked: root.reject()
            }

            Item { Layout.fillWidth: true }
        }
    }

    Overlay.modal: Rectangle { color: Theme.NCTheme.scrim }
}
