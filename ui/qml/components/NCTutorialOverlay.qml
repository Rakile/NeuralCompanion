pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtQml.Models
import "../theme" as Theme
import "TutorialRoutes.js" as TutorialRoutes

Item {
    id: root
    property bool tutorialText: true
    objectName: "tutorialGuideOverlay"

    required property var bridge
    property var hostWindow: null
    property bool guideEnabled: true
    property bool navigationPending: true
    property bool showNarrationHelp: false
    property string targetNotice: ""
    readonly property string contextKey: JSON.stringify(TutorialRoutes.context(root.ownerItem(),
        String(root.bridge.tutorialState.stepWorkspace || ""), root.bridge))
    onContextKeyChanged: contextReportDelay.restart()

    function matchesScope(actual) {
        const scope = root.bridge.tutorialState.scope || ({})
        return Object.keys(scope).every(key => key === "owner_addon" || actual[key] === scope[key])
    }

    function reportContext(allowUnsettled) {
        const state = root.bridge.tutorialState
        if (!root.guideEnabled || !state.active || !state.scoped || state.paused) return
        const actual = JSON.parse(root.contextKey)
        // A tab/property binding must finish before it can notify the bridge.
        // Only the periodic reconciliation counts incomplete navigation attempts.
        if (!allowUnsettled && root.navigationPending && !root.matchesScope(actual)) return
        root.bridge.reportTutorialContext(actual, Number(state.navigationToken))
    }

    Timer {
        id: contextReportDelay
        interval: 0
        onTriggered: root.reportContext(false)
    }
    property var targetItem: null
    property var targetAncestors: []
    property var revealedPrimary: null
    property var revealedFallback: null
    property var demonstrationItem: null
    readonly property string stepKey: root.bridge.tutorialState.active
        ? JSON.stringify([root.bridge.tutorialState.title, root.bridge.tutorialState.stepNumber,
                          root.bridge.tutorialState.stepTarget,
                          root.bridge.tutorialState.scoped ? root.bridge.tutorialState.navigationToken : 0]) : ""

    readonly property string narrationKey: root.bridge.tutorialState.scoped
        ? JSON.stringify([root.bridge.tutorialState.active, root.bridge.tutorialState.navigationToken,
                          root.bridge.tutorialState.speechEnabled]) : ""
    readonly property string viewKey: stepKey + ":" + String(root.bridge.tutorialState.viewToken || 0)
    onNarrationKeyChanged: {
        if (root.guideEnabled && root.bridge.tutorialState.active && root.bridge.tutorialState.speechEnabled)
            narrationDelay.restart()
        else narrationDelay.stop()
    }
    onViewKeyChanged: {
        navigationPending = true
        revealedPrimary = null
        revealedFallback = null
        targetDelay.restart()
    }

    visible: Boolean(root.bridge.tutorialState.active) && root.bridge.tutorialState.audience !== "remote"

    function findTarget(item, wantedName) {
        if (!item || !wantedName || item === root || item.visible === false)
            return null
        if (String(item.objectName || "") === wantedName)
            return item
        const children = item.children || []
        for (let index = 0; index < children.length; ++index) {
            const match = root.findTarget(children[index], wantedName)
            if (match)
                return match
        }
        return null
    }

    function searchRoot() {
        let content = root.hostWindow ? root.hostWindow.contentItem : null
        // ApplicationWindow headers are siblings of contentItem. A plain Window
        // already exposes its full root here, so keep that host unchanged.
        while (content && content.parent)
            content = content.parent
        return content
    }

    function ownerItem() {
        if (!root.hostWindow) return null
        const key = String(root.bridge.tutorialState.stepWorkspace || "")
        const item = typeof root.hostWindow.workspaceItemForKey === "function"
            ? root.hostWindow.workspaceItemForKey(key)
            : (root.hostWindow.currentWorkspaceKey === key ? root.hostWindow.workspaceItem : null)
        if (item && item.Window.window && item.Window.window.currentWorkspaceKey !== undefined
                && item.Window.window.currentWorkspaceKey !== key) return null
        return item
    }

    function scopedRoot() {
        if (!root.bridge.tutorialState.scoped || root.bridge.tutorialState.allowGlobalTarget) return root.searchRoot()
        const item = root.ownerItem()
        return item && item.Window.window === root.hostWindow ? item : null
    }

    function cancelConsoleDemonstration() {
        if (root.demonstrationItem
                && typeof root.demonstrationItem.cancelTutorialDemonstration === "function")
            root.demonstrationItem.cancelTutorialDemonstration()
        root.demonstrationItem = null
    }

    function demonstrateConsole() {
        root.cancelConsoleDemonstration()
        let area = root.searchRoot()
        if (root.hostWindow && typeof root.hostWindow.workspaceItemForKey === "function")
            area = root.hostWindow.workspaceItemForKey("conversation") || area
        const split = root.findTarget(area, "conversationConsoleSplit")
        if (split && typeof split.demonstrateCollapse === "function" && split.demonstrateCollapse())
            root.demonstrationItem = split
        else
            root.targetNotice = qsTr("Open the Conversation window and leave room beside the chat to demonstrate its console handle.")
    }

    function intersectRects(a, b) {
        const left = Math.max(a.x, b.x)
        const top = Math.max(a.y, b.y)
        return Qt.rect(left, top, Math.max(0, Math.min(a.x + a.width, b.x + b.width) - left),
                       Math.max(0, Math.min(a.y + a.height, b.y + b.height) - top))
    }

    function revealTarget() {
        // Work from the inner scroll area outward so nested viewports also reveal the control.
        for (let item = root.targetItem.parent; item; item = item.parent) {
            if (item instanceof Flickable) {
                const bounds = root.targetItem.mapToItem(item.contentItem, 0, 0,
                                                        root.targetItem.width, root.targetItem.height)
                const margin = Theme.NCMetrics.space6
                let x = item.contentX
                let y = item.contentY
                if (bounds.width + 2 * margin > item.width || bounds.x - margin < x)
                    x = bounds.x - margin
                else if (bounds.x + bounds.width + margin > x + item.width)
                    x = bounds.x + bounds.width + margin - item.width
                if (bounds.height + 2 * margin > item.height || bounds.y - margin < y)
                    y = bounds.y - margin
                else if (bounds.y + bounds.height + margin > y + item.height)
                    y = bounds.y + bounds.height + margin - item.height
                item.contentX = Math.max(item.originX, Math.min(x, item.originX + Math.max(0, item.contentWidth - item.width)))
                item.contentY = Math.max(item.originY, Math.min(y, item.originY + Math.max(0, item.contentHeight - item.height)))
            }
            // Prevent saved scroll restoration from undoing this deliberate navigation on resize.
            if (item.scrollMemory && typeof item.scrollMemory.takeControl === "function")
                item.scrollMemory.takeControl()
        }
    }

    function needsReveal() {
        if (!root.targetItem || !root.targetItem.visible
                || root.targetItem.width <= 0 || root.targetItem.height <= 0)
            return false
        return String(root.targetItem.objectName) === String(root.bridge.tutorialState.stepTarget)
               ? root.targetItem !== root.revealedPrimary : root.targetItem !== root.revealedFallback
    }

    function revealOnce() {
        if (!root.needsReveal()) return
        // A fallback must not consume the primary control's first reveal. Track
        // actual instances so a remounted workspace can reveal its new control.
        if (String(root.targetItem.objectName) === String(root.bridge.tutorialState.stepTarget))
            root.revealedPrimary = root.targetItem
        else
            root.revealedFallback = root.targetItem
        root.revealTarget()
    }

    function updateHighlight() {
        if (root.bridge.tutorialState.paused || root.bridge.tutorialState.elsewhere) { targetHighlight.visible = false; return }
        if (root.bridge.tutorialState.scoped && root.targetItem
                && root.targetItem.Window.window !== root.hostWindow) {
            targetHighlight.visible = false
            return
        }
        if (!root.visible || !root.targetItem || !root.targetItem.visible
                || root.targetItem.width <= 0 || root.targetItem.height <= 0) {
            targetHighlight.visible = false
            return
        }
        const bounds = root.targetItem.mapToItem(root, 0, 0, root.targetItem.width, root.targetItem.height)
        let viewport = Qt.rect(0, 0, root.width, root.height)
        for (let item = root.targetItem.parent; item; item = item.parent) {
            if (!item.visible) {
                targetHighlight.visible = false
                return
            }
            if (item.clip)
                viewport = root.intersectRects(viewport, item.mapToItem(root, 0, 0, item.width, item.height))
        }
        const visibleBounds = root.intersectRects(bounds, viewport)
        if (visibleBounds.width <= 0 || visibleBounds.height <= 0) {
            targetHighlight.visible = false
            return
        }
        const margin = Theme.NCMetrics.space6
        const padded = root.intersectRects(Qt.rect(bounds.x - margin, bounds.y - margin,
            bounds.width + 2 * margin, bounds.height + 2 * margin), viewport)
        targetViewport.x = viewport.x
        targetViewport.y = viewport.y
        targetViewport.width = viewport.width
        targetViewport.height = viewport.height
        targetHighlight.x = padded.x - viewport.x
        targetHighlight.y = padded.y - viewport.y
        targetHighlight.width = padded.width
        targetHighlight.height = padded.height
        targetHighlight.visible = true
    }

    function refreshTarget() {
        if (root.bridge.tutorialState.audience === "remote") { targetHighlight.visible = false; return }
        if (root.bridge.tutorialState.paused) { targetHighlight.visible = false; return }
        const wantedName = String(root.bridge.tutorialState.stepTarget || "")
        const searchRoot = root.scopedRoot()
        if (root.navigationPending && searchRoot && !root.bridge.tutorialState.elsewhere) {
            const nav = root.bridge.tutorialState.stepNavigation || ({})
            // Only presentation properties are writable. Never click controls or
            // change provider activation/settings while navigating a tutorial.
            const routes = [
                ["runtime_section", "runtimeWorkspace", "currentSection"],
                ["runtime_responsibility", "runtimeWorkspace", "currentResponsibility"],
                ["persona_tab", "personaWorkspace", "selectedTab"],
                ["persona_override", "personaWorkspace", "selectedOverrideTab"],
                ["remote_tab", "mainChatRemoteWorkspace", "currentTab"],
                ["document_section", "documentMemoryWorkspace", "selectedDocumentSection"],
                ["subsection", "runtimeProviderSettingsPanel", "selectedSectionKey"],
                ["chat_tab", "coreSettingsWorkspace", "currentChatTab"],
                ["studio_section", "voiceStudioWorkspace", "currentSection"]
            ]
            let ready = true
            let navigated = false
            for (const route of routes) {
                if (!nav[route[0]]) continue
                const page = root.findTarget(searchRoot, route[1])
                if (page) {
                    if (route[0] === "subsection" && root.bridge.tutorialState.scoped) {
                        const scope = root.bridge.tutorialState.scope || ({})
                        if ((scope.provider_id && page.providerId !== scope.provider_id)
                                || (scope.provider_kind && page.kind !== scope.provider_kind)
                                || page.ownsSettings === false) {
                            ready = false
                            continue
                        }
                    }
                    // Older hosts may show the same named cards on one page.
                    const value = route[0] === "subsection" && nav[route[0]] !== "voice-tag-rules"
                        ? "section:" + String(nav[route[0]]) : String(nav[route[0]])
                    if (page[route[2]] !== undefined && page[route[2]] !== value) {
                        page[route[2]] = value
                        navigated = true
                    }
                } else ready = false
            }
            if (nav.sensory_tab) {
                const page = root.findTarget(searchRoot, "orbSensorySettings")
                          || root.findTarget(searchRoot, "spotifySensorySettings")
                          || root.findTarget(searchRoot, "visionSourceSettings")
                if (page) {
                    if (page.selectedTab !== String(nav.sensory_tab)) {
                        page.selectedTab = String(nav.sensory_tab)
                        navigated = true
                    }
                } else ready = false
            }
            if (ready && !navigated && (!root.bridge.tutorialState.scoped
                    || root.matchesScope(TutorialRoutes.context(root.ownerItem(),
                        String(root.bridge.tutorialState.stepWorkspace || ""), root.bridge))))
                root.navigationPending = false
            if (navigated) {
                // A newly visible tab still has its previous layout geometry
                // this turn. Reveal after layout, without retrying manual scroll.
                targetDelay.restart()
                return
            }
        }
        root.targetItem = root.findTarget(searchRoot, wantedName)
        root.targetNotice = ""
        if (!root.targetItem) {
            root.targetItem = root.findTarget(searchRoot, String(root.bridge.tutorialState.stepFallbackTarget || ""))
            root.targetNotice = String(root.bridge.tutorialState.stepTargetHint
                || qsTr("If the control is not visible, open the destination described below. It may need content or a loaded addon. Check any floating workspace window as well."))
        }
        const initialReveal = !root.bridge.tutorialState.elsewhere && root.needsReveal()
        if (!root.bridge.tutorialState.elsewhere) root.revealOnce()
        root.updateHighlight()
        root.reportTarget()
        if (!targetHighlight.visible) {
            const fallback = root.findTarget(searchRoot,
                String(root.bridge.tutorialState.stepFallbackTarget || ""))
            if (fallback && fallback !== root.targetItem) {
                root.targetItem = fallback
                root.targetNotice = String(root.bridge.tutorialState.stepTargetHint
                    || qsTr("Open the control described below from this area."))
                if (initialReveal) root.revealOnce()
                root.updateHighlight()
            }
        }
    }

    function reportTarget() {
        if (!root.bridge.tutorialState.scoped || typeof root.bridge.reportTutorialTarget !== "function") return
        const state = root.bridge.tutorialState
        const actual = TutorialRoutes.context(root.ownerItem(), String(state.stepWorkspace || ""), root.bridge)
        const scope = state.scope || ({})
        const routeReady = Object.keys(scope).every(key => key === "owner_addon" || actual[key] === scope[key])
        const exact = routeReady && targetHighlight.visible && root.targetItem
            && String(root.targetItem.objectName) === String(state.stepTarget)
            && !root.navigationPending && !state.elsewhere
        // Only the destination's own overlay reports; another floating window
        // must not overwrite its readiness with a negative report.
        if (root.scopedRoot()) {
            const token = Number(state.navigationToken)
            Qt.callLater(function() { root.bridge.reportTutorialTarget(token, Boolean(exact)) })
        }
    }

    onStepKeyChanged: {
        cancelConsoleDemonstration()
        if (root.bridge.tutorialState.scoped) targetItem = null
        navigationPending = true
        revealedPrimary = null
        revealedFallback = null
        targetHighlight.visible = false
        if (!root.bridge.tutorialState.paused) targetDelay.restart()
    }
    onTargetItemChanged: {
        const ancestors = []
        for (let item = targetItem; item; item = item.parent)
            ancestors.push(item)
        targetAncestors = ancestors
    }
    onWidthChanged: updateHighlight()
    onHeightChanged: updateHighlight()

    Instantiator {
        model: root.targetAncestors
        delegate: Connections {
            required property var modelData
            target: modelData
            ignoreUnknownSignals: true
            function onXChanged() { root.updateHighlight() }
            function onYChanged() { root.updateHighlight() }
            function onWidthChanged() { root.updateHighlight() }
            function onHeightChanged() { root.updateHighlight() }
            function onContentXChanged() { root.updateHighlight() }
            function onContentYChanged() { root.updateHighlight() }
            function onVisibleChanged() { root.updateHighlight() }
            function onScaleChanged() { root.updateHighlight() }
        }
    }

    Item {
        id: targetViewport
        clip: true
        z: 1

    Rectangle {
        id: targetHighlight
        objectName: "tutorialTargetHighlight"
        visible: false
        z: 1
        radius: Theme.NCMetrics.radiusLarge
        color: "transparent"
        border.width: 3
        border.color: "#FFE066"

        SequentialAnimation on border.color {
            running: targetHighlight.visible
            loops: Animation.Infinite
            ColorAnimation {
                from: "#FFE066"
                to: "#FFE066"
                duration: 850
            }
            ColorAnimation {
                from: "#FFE066"
                to: "#FFE066"
                duration: 850
            }
        }

        Rectangle {
            id: focusRipple
            objectName: "tutorialFocusRipple"
            anchors.fill: parent
            anchors.margins: -Theme.NCMetrics.space6
            radius: targetHighlight.radius + Theme.NCMetrics.space6
            color: "transparent"
            border.width: 2
            border.color: "#FFE066"
            opacity: 0

            SequentialAnimation {
                running: targetHighlight.visible
                loops: Animation.Infinite
                ParallelAnimation {
                    NumberAnimation {
                        target: focusRipple
                        property: "opacity"
                        from: 0.72
                        to: 0.0
                        duration: 1350
                    }
                    NumberAnimation {
                        target: focusRipple
                        property: "scale"
                        from: 1.0
                        to: 1.08
                        duration: 1350
                        easing.type: Easing.OutCubic
                    }
                    ColorAnimation {
                        target: focusRipple
                        property: "border.color"
                        from: "#FFE066"
                        to: "#FFE066"
                        duration: 1350
                    }
                }
                PauseAnimation { duration: 350 }
            }
        }
    }

    }

    Window {
        id: guideWindow
        objectName: "tutorialGuideWindow"
        property bool hasInitialPosition: false

        width: 540
        height: root.bridge.tutorialState.scoped ? 600 : 480
        minimumWidth: root.bridge.tutorialState.scoped ? 540 : 380
        minimumHeight: root.bridge.tutorialState.scoped ? 540 : 360
        visible: root.visible && root.guideEnabled
        transientParent: root.hostWindow
        flags: Qt.Tool | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
        color: Theme.NCTheme.window
        title: qsTr("Tutorial Guide · %1").arg(
                   String(root.bridge.tutorialState.title || qsTr("NeuralCompanion")))

        function placeBesideHost() {
            if (hasInitialPosition || !root.hostWindow || !screen)
                return
            const geometry = typeof root.bridge.tutorialScreenGeometry === "function"
                ? root.bridge.tutorialScreenGeometry(root.hostWindow.x, root.hostWindow.y)
                : {x: screen.virtualX, y: screen.virtualY,
                   width: screen.desktopAvailableWidth, height: screen.desktopAvailableHeight}
            if (!geometry || !geometry.width || !geometry.height)
                return
            const gap = Theme.NCMetrics.space16
            let preferredX = root.hostWindow.x + root.hostWindow.width + gap
            if (preferredX + width > geometry.x + geometry.width)
                preferredX = root.hostWindow.x - width - gap
            x = Math.max(geometry.x + gap,
                         Math.min(preferredX,
                                  geometry.x + geometry.width - width - gap))
            y = Math.max(geometry.y + gap,
                         Math.min(root.hostWindow.y + Theme.NCMetrics.space48,
                                  geometry.y + geometry.height - height - gap))
            hasInitialPosition = true
        }

        onVisibleChanged: {
            if (visible)
                Qt.callLater(placeBesideHost)
        }
        onClosing: function(close) {
            close.accepted = false
            root.bridge.closeTutorial()
        }
        Component.onCompleted: if (visible) Qt.callLater(placeBesideHost)

        NCCard { tutorialText: false
            id: guideCard
            objectName: "tutorialGuideCard"
            parent: guideWindow.contentItem
            x: Theme.NCMetrics.space12
            y: Theme.NCMetrics.space12
            width: guideWindow.width - Theme.NCMetrics.space24
            height: guideWindow.height - Theme.NCMetrics.space24
            elevated: true
            title: String(root.bridge.tutorialState.stepTitle || qsTr("Interactive guide"))
            description: root.bridge.tutorialState.continuousCourse
                ? qsTr("Course · %1").arg(String(root.bridge.tutorialState.title || ""))
                : root.bridge.tutorialState.guideKind === "workflow"
                ? qsTr("Workflow · %1").arg(String(root.bridge.tutorialState.title || ""))
                : String(root.bridge.tutorialState.title || "")

            headerAccessory: NCIconButton { tutorialText: false
                glyph: "×"
                toolTipText: qsTr("Close tutorial")
                onClicked: root.bridge.closeTutorial()
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8

                Label {
                    text: qsTr("Step %1 of %2").arg(
                              Number(root.bridge.tutorialState.stepNumber || 0)).arg(
                              Number(root.bridge.tutorialState.stepCount || 0))
                    color: Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.microSize
                }
                Item { Layout.fillWidth: true }
                Label {
                    visible: String(root.bridge.tutorialState.stepLocation || "").length > 0
                    text: String(root.bridge.tutorialState.stepLocation || "")
                    color: Theme.NCTheme.textSecondary
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.microSize
                }
            }

            NCComboBox { tutorialText: false
                objectName: "tutorialChapterSelector"
                Layout.fillWidth: true
                visible: Boolean(root.bridge.tutorialState.continuousCourse)
                model: root.bridge.tutorialState.chapters || []
                textRole: "title"
                valueRole: "id"
                currentIndex: {
                    const chapters = root.bridge.tutorialState.chapters || []
                    const stepIndex = Number(root.bridge.tutorialState.stepIndex || 0)
                    let selected = 0
                    for (let i = 0; i < chapters.length; ++i)
                        if (Number(chapters[i].step_index) <= stepIndex) selected = i
                    return selected
                }
                onActivated: root.bridge.startTutorial(String(currentValue))
            }

            NCProgressBar {
                Layout.fillWidth: true
                value: Number(root.bridge.tutorialState.stepNumber || 0)
                from: 0
                to: Math.max(1, Number(root.bridge.tutorialState.stepCount || 1))
            }

            Label {
                Layout.fillWidth: true
                visible: text.length > 0
                text: root.bridge.tutorialState.paused
                    ? qsTr("Tutorial paused.")
                    : root.bridge.tutorialState.elsewhere
                        ? qsTr("Narration continues while you browse. Follow the yellow tab markers, or show the current step. The next step waits until its control is visible.")
                        : ["failed", "interrupted"].indexOf(String(root.bridge.tutorialState.audioStatus)) >= 0
                            ? qsTr("Narration did not finish. Replay this step or choose Continue; no steps were skipped.")
                            : String(root.bridge.tutorialState.stepNotice || root.targetNotice || "")
                color: Theme.NCTheme.textSecondary
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.WordWrap
            }

            ScrollView {
                id: tutorialStepScroll
                objectName: "tutorialStepScroll"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                property NCSettingsScrollMemory scrollMemory: NCSettingsScrollMemory {
                    bridge: root.bridge
                    scrollView: tutorialStepScroll
                    pageKey: "tutorial:" + String(root.bridge.tutorialState.id || "")
                             + ":" + String(root.bridge.tutorialState.stepIndex || 0)
                }

                Label {
                    id: tutorialStepBody
                    objectName: "tutorialStepBody"
                    width: tutorialStepScroll.availableWidth
                    text: String(root.bridge.tutorialState.stepBody || "")
                    color: Theme.NCTheme.text
                    font.family: Theme.NCTypography.family
                    font.pixelSize: Theme.NCTypography.bodySize
                    lineHeight: 1.25
                    wrapMode: Text.WordWrap
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8

                NCButton { tutorialText: false
                    visible: Boolean(root.bridge.tutorialState.scoped)
                    text: qsTr("Stop narration")
                    compact: true
                    onClicked: root.bridge.stopTutorialSpeech()
                }

                NCSwitch { tutorialText: false
                    toolTipText: qsTr("Read tutorial guidance aloud using the available speech path. Turning it off stops tutorial narration; it does not disable normal conversation speech.")

                    id: readAloudSwitch
                    objectName: "tutorialReadAloudSwitch"
                    text: qsTr("Read aloud")
                    checked: Boolean(root.bridge.tutorialState.speechEnabled)
                    onToggled: root.bridge.setTutorialSpeechEnabled(checked)
                }

                NCButton { tutorialText: false
                    text: root.bridge.tutorialState.scoped ? qsTr("Replay step") : qsTr("Hear step")
                    enabled: !Boolean(root.bridge.tutorialState.paused)
                    compact: true
                    tone: "secondary"
                    onClicked: root.bridge.speakTutorialStep()
                }

                NCButton { tutorialText: false
                    visible: Boolean(root.bridge.tutorialState.hasTryAction)
                    enabled: !Boolean(root.bridge.tutorialState.paused)
                    text: String(root.bridge.tutorialState.tryLabel || qsTr("Try it"))
                    compact: true
                    tone: "secondary"
                    onClicked: root.bridge.performTutorialTryAction()
                }
            }

            NCButton { tutorialText: false
                objectName: "tutorialConsoleDemoButton"
                Layout.fillWidth: true
                visible: String(root.bridge.tutorialState.stepDemonstration || "") === "console_split"
                enabled: !root.demonstrationItem || !root.demonstrationItem.tutorialDemonstrating
                text: qsTr("Show me: hide and restore the console")
                compact: true
                onClicked: root.demonstrateConsole()
            }

            NCButton { tutorialText: false
                visible: Boolean(root.bridge.tutorialState.scoped)
                text: root.showNarrationHelp ? qsTr("Hide narration help") : qsTr("Narration help")
                compact: true
                tone: "quiet"
                onClicked: root.showNarrationHelp = !root.showNarrationHelp
            }

            Label {
                objectName: "tutorialNarrationHelp"
                visible: !root.bridge.tutorialState.scoped || root.showNarrationHelp
                Layout.fillWidth: true
                text: qsTr("Higher-quality narration: select Chatterbox in Runtime → Text-to-speech, then use the large top-right power button OFF → ON to initialize NC. Wait for Chatterbox to load, then Hear step. ON → OFF stops the engine. If Chatterbox is unavailable or fails, NC tries Windows TTS. You can always read without starting the engine.")
                color: Theme.NCTheme.textMuted
                font.pixelSize: Theme.NCTypography.captionSize
                wrapMode: Text.WordWrap
            }

            RowLayout {
                id: followUpRow
                Layout.fillWidth: true
                visible: !root.bridge.tutorialState.paused
                         && !root.bridge.tutorialState.canGoForward
                         && (root.bridge.tutorialState.children || []).length > 0
                NCComboBox { tutorialText: false
                    id: followUpSelector
                    label: qsTr("Next tutorial")
                    objectName: "tutorialFollowUpSelector"
                    Layout.fillWidth: true
                    textRole: "display_title"
                    valueRole: "id"
                    model: followUpRow.visible && (root.bridge.tutorialState.children || []).length > 0
                        ? (root.bridge.tutorialCatalog || []).filter(guide =>
                            (root.bridge.tutorialState.children || []).indexOf(guide.id) >= 0) : []
                }
                NCButton { tutorialText: false
                    objectName: "tutorialStartFollowUp"
                    text: qsTr("Start guide")
                    enabled: followUpSelector.currentIndex >= 0
                    onClicked: root.bridge.startTutorial(String(followUpSelector.currentValue))
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.NCMetrics.space8

                NCButton { tutorialText: false
                    objectName: "tutorialReturnButton"
                    visible: Boolean(root.bridge.tutorialState.scoped)
                    text: qsTr("Show current step")
                    onClicked: root.bridge.resumeTutorial()
                }
                NCButton { tutorialText: false
                    objectName: "tutorialEndButton"
                    visible: Boolean(root.bridge.tutorialState.paused)
                    text: qsTr("End tutorial")
                    tone: "secondary"
                    onClicked: root.bridge.closeTutorial()
                }

                NCStatusChip { tutorialText: false
                    visible: !root.bridge.tutorialState.paused && String(root.bridge.tutorialState.stepLocation || "").length > 0
                    text: String(root.bridge.tutorialState.stepLocation || "")
                    status: "info"
                }
                Item { Layout.fillWidth: true }
                NCButton { tutorialText: false
                    text: qsTr("Back")
                    visible: !root.bridge.tutorialState.paused
                    compact: true
                    tone: "secondary"
                    enabled: Boolean(root.bridge.tutorialState.canGoBack)
                    onClicked: root.bridge.previousTutorialStep()
                }
                NCButton { tutorialText: false
                    text: Boolean(root.bridge.tutorialState.canGoForward) ? (root.bridge.tutorialState.scoped ? qsTr("Continue") : qsTr("Next")) : qsTr("Finish")
                    visible: !root.bridge.tutorialState.paused
                    enabled: !Boolean(root.bridge.tutorialState.paused)
                    compact: true
                    onClicked: root.bridge.nextTutorialStep()
                }
            }
        }
    }

    Connections {
        target: root.bridge
        function onTutorialStateChanged() {
            if (root.bridge.tutorialState.audience === "remote") {
                targetDelay.stop(); narrationDelay.stop(); return
            }
            if (root.bridge.tutorialState.paused) {
                targetDelay.stop(); narrationDelay.stop()
                root.targetHighlightVisible(false)
                root.cancelConsoleDemonstration()
                return
            }
            targetDelay.restart()
            if (root.bridge.tutorialState.scoped) return
            if (root.guideEnabled && root.bridge.tutorialState.audience !== "remote" && root.bridge.tutorialState.active
                    && root.bridge.tutorialState.speechEnabled)
                narrationDelay.restart()
            else
                narrationDelay.stop()
        }
    }

    Timer {
        id: targetDelay
        interval: 180
        repeat: false
        onTriggered: root.refreshTarget()
    }

    Timer {
        id: targetRefresh
        interval: 500
        repeat: true
        running: root.visible && !Boolean(root.bridge.tutorialState.paused)
        onTriggered: root.refreshTarget()
    }

    function targetHighlightVisible(value) { targetHighlight.visible = value }

    Timer {
        interval: 200
        repeat: true
        running: root.guideEnabled && root.bridge.tutorialState.active
                 && root.bridge.tutorialState.scoped && !root.bridge.tutorialState.paused
        onTriggered: root.reportContext(true)
    }

    Timer {
        id: narrationDelay
        interval: 180
        repeat: false
        onTriggered: {
            if (root.guideEnabled && root.bridge.tutorialState.audience !== "remote" && root.bridge.tutorialState.active
                    && !root.bridge.tutorialState.paused
                    && root.bridge.tutorialState.speechEnabled)
                root.bridge.speakTutorialStep()
        }
    }

    onVisibleChanged: {
        if (visible) targetDelay.restart()
        else cancelConsoleDemonstration()
    }
}
