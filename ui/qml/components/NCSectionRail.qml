pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme
import "TutorialStyle.js" as TutorialStyle

Rectangle {
    id: root

    property var model: []
    property var tutorialBridge: null
    property var tutorialContext: ({})
    property string tutorialRouteKey: "addon"
    NCTutorialMenu { id: tutorialMenu; bridge: root.tutorialBridge || ({}) }
    function tutorialRoute(key) {
        const route = Object.assign({}, root.tutorialContext)
        route[root.tutorialRouteKey] = key
        return route
    }
    property string currentKey: ""
    property string heading: ""
    property int iconSize: 50
    property bool searchable: false
    property string searchPlaceholder: qsTr("Search")
    property string filterText: ""
    property bool entriesHideable: false
    property bool entriesReorderable: false
    property int reorderHoldInterval: 1500
    property var hiddenModel: []
    readonly property var filteredModel: {
        const source = root.model || []
        const query = root.filterText.trim().toLowerCase()
        if (!root.searchable || query.length === 0)
            return source
        const matches = []
        for (let index = 0; index < source.length; ++index) {
            const item = source[index]
            const haystack = (
                String(item.label || "") + " "
                + String(item.description || "") + " "
                + String(item.areaLabel || "")
            ).toLowerCase()
            if (haystack.indexOf(query) >= 0)
                matches.push(item)
        }
        return matches
    }
    signal activated(string key)
    signal hideRequested(string key)
    signal unhideRequested(string key)
    signal moveRequested(string key, int targetIndex)

    function dropIndex(item, offset) {
        const count = root.filteredModel.length
        if (!item || count <= 1)
            return 0
        const stride = item.height + railColumn.spacing
        return Math.max(0, Math.min(count - 1, Math.round((item.y + offset) / stride)))
    }

    function openBelow(popup, control) {
        if (!popup || !control || !popup.parent)
            return
        const mapped = control.mapToItem(popup.parent, 0, control.height + Theme.NCMetrics.space4)
        popup.x = Math.max(
                    Theme.NCMetrics.space8,
                    Math.min(mapped.x, popup.parent.width - popup.width - Theme.NCMetrics.space8))
        popup.y = Math.max(
                    Theme.NCMetrics.space8,
                    Math.min(mapped.y, popup.parent.height - popup.implicitHeight - Theme.NCMetrics.space8))
        popup.open()
    }

    implicitWidth: Theme.NCMetrics.sectionRailWidth
    radius: Theme.NCMetrics.radiusLarge
    color: Theme.NCTheme.windowRaised
    border.color: Theme.NCTheme.borderSubtle
    border.width: Theme.NCMetrics.borderWidth
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.NCMetrics.space8
        spacing: Theme.NCMetrics.space8

        Label {
            Layout.fillWidth: true
            text: root.heading.toUpperCase()
            color: Theme.NCTheme.accent
            font.family: Theme.NCTypography.family
            font.pixelSize: Theme.NCTypography.microSize
            font.weight: Theme.NCTypography.bold
            font.letterSpacing: 1.1
            horizontalAlignment: Text.AlignHCenter
            visible: text.length > 0
        }

        NCSearchField {
            toolTipText: qsTr("Filter the sections or entries shown in this navigation rail. Clearing the search restores the full list; no setting or saved item is changed.")

            Layout.fillWidth: true
            visible: root.searchable
            placeholderText: root.searchPlaceholder
            text: root.filterText
            onTextChanged: root.filterText = text
        }

        Flickable {
            id: railFlickable
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: railColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: railColumn
                width: parent.width
                spacing: Theme.NCMetrics.space8

                Repeater {
                    id: repeater
                    objectName: "sectionRailRepeater"
                    model: root.filteredModel

                    delegate: Button {
                        id: navButton
                        objectName: "sectionRailEntry_" + entryKey
                        required property int index
                        required property var modelData
                        readonly property string entryKey: String(
                            modelData.key !== undefined ? modelData.key : (modelData.id || "")
                        )
                        property bool dragArmed: false
                        property real dragOffset: 0
                        property real pressRailY: 0
                        property bool pointerHovered: pointerArea.containsMouse

                        Layout.fillWidth: true
                        implicitHeight: root.iconSize + 44
                        padding: Theme.NCMetrics.space6
                        hoverEnabled: true
                        checked: entryKey === root.currentKey
                        opacity: dragArmed ? 0.48 : 1.0
                        z: dragArmed ? 100 : 0
                        transform: Translate { y: navButton.dragOffset }
                        Accessible.name: String(modelData.label)
                        Accessible.description: String(modelData.description || modelData.areaLabel || "")

                        background: Rectangle {
                            radius: Theme.NCMetrics.radiusMedium
                            color: navButton.down ? Theme.NCTheme.surfacePressed
                                                  : navButton.checked ? Theme.NCTheme.surfaceSelected
                                                  : navButton.pointerHovered ? Theme.NCTheme.surfaceRaised : "transparent"
                            border.width: navButton.activeFocus || navButton.checked ? Theme.NCMetrics.focusWidth : 0
                            border.color: navButton.activeFocus ? Theme.NCTheme.focus : Theme.NCTheme.accent
                        }

                        contentItem: ColumnLayout {
                            spacing: Theme.NCMetrics.space4

                            Rectangle {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.preferredWidth: root.iconSize
                                Layout.preferredHeight: root.iconSize
                                radius: Theme.NCMetrics.radiusMedium
                                color: navButton.checked ? Theme.NCTheme.accentSoft : Theme.NCTheme.surface
                                border.color: navButton.checked ? Theme.NCTheme.accent : Theme.NCTheme.border

                                Image {
                                    anchors.fill: parent
                                    anchors.margins: Theme.NCMetrics.space4
                                    source: String(navButton.modelData.icon || "")
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    mipmap: true
                                    visible: source.toString().length > 0
                                }

                                Label {
                                    anchors.centerIn: parent
                                    text: String(navButton.modelData.glyph || "•")
                                    color: navButton.checked ? Theme.NCTheme.accent : Theme.NCTheme.textSecondary
                                    font.family: Theme.NCTypography.family
                                    font.pixelSize: 24
                                    font.weight: Theme.NCTypography.semibold
                                    visible: String(navButton.modelData.icon || "").length === 0
                                }
                            }

                            Label {
                                Layout.fillWidth: true
                                text: String(navButton.modelData.label)
                                color: navButton.checked ? Theme.NCTheme.text : Theme.NCTheme.textSecondary
                                font.family: Theme.NCTypography.family
                                font.pixelSize: Theme.NCTypography.captionSize
                                font.weight: navButton.checked ? Theme.NCTypography.semibold : Theme.NCTypography.regular
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                            }
                        }

                        onClicked: root.activated(entryKey)
                        NCTutorialMarker { bridge: root.tutorialBridge; context: root.tutorialRoute(navButton.entryKey) }
                        Keys.onPressed: event => {
                            if (root.tutorialBridge && TutorialStyle.showContext(root.tutorialBridge) && (event.key === Qt.Key_Menu
                                    || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier)))) {
                                tutorialMenu.openFor(navButton, root.tutorialRoute(navButton.entryKey))
                                event.accepted = true
                            }
                        }

                        MouseArea {
                            id: pointerArea
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            hoverEnabled: true
                            pressAndHoldInterval: root.reorderHoldInterval
                            preventStealing: navButton.dragArmed

                            onPressed: mouse => {
                                if (mouse.button === Qt.LeftButton) {
                                    const point = pointerArea.mapToItem(
                                                    railColumn, mouse.x, mouse.y)
                                    navButton.pressRailY = point.y
                                }
                            }

                            onPressAndHold: mouse => {
                                if (mouse.button !== Qt.LeftButton
                                        || !root.entriesReorderable
                                        || root.filterText.trim().length > 0)
                                    return
                                navButton.dragArmed = true
                                navButton.dragOffset = 0
                                mouse.accepted = true
                            }

                            onPositionChanged: mouse => {
                                if (!navButton.dragArmed)
                                    return
                                const point = pointerArea.mapToItem(
                                                railColumn, mouse.x, mouse.y)
                                navButton.dragOffset = point.y - navButton.pressRailY
                            }

                            onReleased: mouse => {
                                if (!navButton.dragArmed)
                                    return
                                const targetIndex = root.dropIndex(navButton, navButton.dragOffset)
                                navButton.dragArmed = false
                                navButton.dragOffset = 0
                                root.moveRequested(navButton.entryKey, targetIndex)
                                mouse.accepted = true
                            }

                            onCanceled: {
                                navButton.dragArmed = false
                                navButton.dragOffset = 0
                            }

                            onClicked: mouse => {
                                if (mouse.button === Qt.RightButton) {
                                    if (root.entriesHideable || (root.tutorialBridge && TutorialStyle.showContext(root.tutorialBridge)))
                                        root.openBelow(hideMenu, navButton)
                                    return
                                }
                                if (!navButton.dragArmed)
                                    root.activated(navButton.entryKey)
                            }
                        }

                        Popup {
                            id: hideMenu
                            objectName: "addonRailHideMenu_" + navButton.entryKey
                            parent: Overlay.overlay
                            width: 268
                            padding: Theme.NCMetrics.space8
                            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                            modal: false
                            dim: false

                            background: Rectangle {
                                color: Theme.NCTheme.windowRaised
                                radius: Theme.NCMetrics.radiusLarge
                                border.width: Theme.NCMetrics.focusWidth
                                border.color: Theme.NCTheme.borderStrong
                            }

                            contentItem: ColumnLayout {
                                NCContextMenuItem {
                                    Layout.fillWidth: true
                                    visible: root.tutorialBridge !== null && TutorialStyle.showContext(root.tutorialBridge)
                                    tutorialText: true
                                    text: qsTr("Tutorials…")
                                    onClicked: {
                                        hideMenu.close()
                                        tutorialMenu.openFor(navButton, root.tutorialRoute(navButton.entryKey))
                                    }
                                }
                                NCContextMenuItem {
                                    Layout.fillWidth: true
                                    visible: root.entriesHideable
                                    text: qsTr("Hide %1 addon").arg(String(navButton.modelData.label || ""))
                                    glyph: "−"
                                    destructive: true
                                    onClicked: {
                                        hideMenu.close()
                                        root.hideRequested(navButton.entryKey)
                                    }
                                }
                            }
                        }

                        NCToolTip {
                            visible: navButton.pointerHovered && !navButton.dragArmed
                            delay: 500
                            text: {
                                const detail = String(navButton.modelData.description
                                                      || navButton.modelData.areaLabel || "")
                                return detail.length > 0
                                       ? String(navButton.modelData.label) + "\n" + detail
                                       : String(navButton.modelData.label)
                            }
                        }
                    }
                }
            }

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }
        }

        Button {
            id: unhideButton
            objectName: "addonRailUnhideButton"
            Layout.fillWidth: true
            implicitHeight: Theme.NCMetrics.controlHeight
            visible: root.entriesHideable
            enabled: Boolean(root.hiddenModel) && root.hiddenModel.length > 0
            text: qsTr("Unhide addon")
            hoverEnabled: true
            Accessible.name: text
            Accessible.description: enabled
                                    ? qsTr("Choose an addon icon to restore to the rail.")
                                    : qsTr("No addon icons are hidden.")

            background: Rectangle {
                radius: Theme.NCMetrics.radiusMedium
                color: unhideButton.down ? Theme.NCTheme.surfacePressed
                      : unhideButton.hovered ? Theme.NCTheme.surfaceRaised
                      : Theme.NCTheme.surface
                border.width: unhideButton.activeFocus
                              ? Theme.NCMetrics.focusWidth : Theme.NCMetrics.borderWidth
                border.color: unhideButton.activeFocus
                              ? Theme.NCTheme.focus : Theme.NCTheme.border
            }

            contentItem: Label {
                text: unhideButton.text
                color: unhideButton.enabled
                       ? Theme.NCTheme.textSecondary : Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }

            onClicked: root.openBelow(unhideMenu, unhideButton)
        }
    }

    Popup {
        id: unhideMenu
        objectName: "addonRailUnhideMenu"
        parent: Overlay.overlay
        width: 292
        implicitHeight: Math.min(420, hiddenList.contentHeight + 2 * padding)
        padding: Theme.NCMetrics.space8
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        modal: false
        dim: false

        background: Rectangle {
            color: Theme.NCTheme.windowRaised
            radius: Theme.NCMetrics.radiusLarge
            border.width: Theme.NCMetrics.focusWidth
            border.color: Theme.NCTheme.borderStrong
        }

        contentItem: ListView {
            id: hiddenList
            implicitHeight: contentHeight
            clip: true
            spacing: Theme.NCMetrics.space2
            model: root.hiddenModel || []

            delegate: Button {
                id: hiddenEntry
                required property var modelData
                readonly property string addonKey: String(modelData.key !== undefined
                    ? modelData.key : (modelData.id || ""))
                objectName: "addonRailUnhideEntry_" + addonKey
                width: ListView.view.width
                implicitHeight: 52
                hoverEnabled: true
                enabled: modelData.available !== false
                Accessible.name: String(modelData.label || qsTr("Addon"))

                background: Rectangle {
                    radius: Theme.NCMetrics.radiusSmall
                    color: hiddenEntry.down ? Theme.NCTheme.surfacePressed
                          : hiddenEntry.hovered ? Theme.NCTheme.surfaceSelected
                          : "transparent"
                }

                contentItem: RowLayout {
                    spacing: Theme.NCMetrics.space10

                    Image {
                        Layout.preferredWidth: 34
                        Layout.preferredHeight: 34
                        source: String(hiddenEntry.modelData.icon || "")
                        opacity: hiddenEntry.enabled ? 1.0 : 0.35
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Label {
                            Layout.fillWidth: true
                            text: String(hiddenEntry.modelData.label || qsTr("Addon"))
                            color: hiddenEntry.enabled ? Theme.NCTheme.text : Theme.NCTheme.textMuted
                            font.pixelSize: Theme.NCTypography.labelSize
                            elide: Text.ElideRight
                        }

                        Label {
                            objectName: "addonRailUnhideStatus_" + hiddenEntry.addonKey
                            Layout.fillWidth: true
                            visible: !hiddenEntry.enabled
                            text: hiddenEntry.modelData.enabled === false
                                  || hiddenEntry.modelData.effectiveEnabled === false
                                  ? qsTr("Disabled") : qsTr("Not loaded")
                            color: Theme.NCTheme.textMuted
                            font.pixelSize: Theme.NCTypography.captionSize
                            elide: Text.ElideRight
                        }
                    }
                }

                onClicked: {
                    unhideMenu.close()
                    root.unhideRequested(hiddenEntry.addonKey)
                }
            }

            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        }
    }
}
