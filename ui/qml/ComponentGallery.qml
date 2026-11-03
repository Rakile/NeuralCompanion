import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "theme" as Theme

ApplicationWindow {
    id: root
    width: 1320
    height: 900
    minimumWidth: 980
    minimumHeight: 680
    visible: true
    title: "NeuralCompanion · QML Component Laboratory"
    color: Theme.NCTheme.window
    font.family: Theme.NCTypography.family
    font.pixelSize: Theme.NCTypography.bodySize

    ScrollView {
        anchors.fill: parent
        anchors.margins: Theme.NCMetrics.space20
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: parent.width
            spacing: Theme.NCMetrics.space16

            NCSectionHeader {
                Layout.fillWidth: true
                eyebrow: "NeuralCompanion design system"
                title: "Component laboratory"
                description: "Production states for controls, surfaces, status, focus, feedback, and responsive composition. Use Tab and Shift+Tab to inspect keyboard focus."
            }

            NCCard {
                Layout.fillWidth: true
                title: "Actions"
                description: "Primary, secondary, quiet, dangerous, busy, and disabled states"
                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space8
                    NCButton { text: "Primary action"; tone: "primary" }
                    NCButton { text: "Secondary" }
                    NCButton { text: "Quiet action"; tone: "quiet" }
                    NCButton { text: "Delete"; tone: "danger" }
                    NCButton { text: "Refreshing"; busy: true }
                    NCButton { text: "Unavailable"; enabled: false }
                    NCIconButton { glyph: "⋯"; toolTipText: "More actions" }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: root.width >= 1160 ? 2 : 1
                columnSpacing: Theme.NCMetrics.space16
                rowSpacing: Theme.NCMetrics.space16

                NCCard {
                    Layout.fillWidth: true
                    title: "Fields and selection"
                    description: "Consistent heights, labels, focus rings, validation, and popup styling"
                    NCTextField { Layout.fillWidth: true; label: "Model ID"; placeholderText: "Select or enter a model" }
                    NCTextField { Layout.fillWidth: true; label: "Server address"; text: "http://127.0.0.1:1234/v1" }
                    NCTextField { Layout.fillWidth: true; label: "Invalid value"; text: "broken://"; errorText: "Use an HTTP or HTTPS address." }
                    NCSearchField { Layout.fillWidth: true; placeholderText: "Search addons" }
                    NCComboBox { Layout.fillWidth: true; label: "Runtime"; model: ["LM Studio", "Ollama", "OpenAI"] }
                    NCSpinBox { label: "Context messages"; from: 1; to: 200; value: 24 }
                    NCSlider { Layout.fillWidth: true; label: "Audio reactivity"; from: 0; to: 100; value: 64 }
                }

                NCCard {
                    Layout.fillWidth: true
                    title: "Toggles and status"
                    description: "Selection remains distinct from active runtime state"
                    NCCheckBox { text: "Require image-processing capability"; checked: true }
                    NCCheckBox { text: "Disabled option"; enabled: false }
                    NCSwitch { text: "Continuous background awareness"; checked: true }
                    NCSwitch { text: "Offline" }
                    ButtonGroup { id: densityGroup }
                    NCRadioButton { text: "Compact density"; checked: true; ButtonGroup.group: densityGroup }
                    NCRadioButton { text: "Comfortable density"; ButtonGroup.group: densityGroup }
                    Flow {
                        Layout.fillWidth: true
                        spacing: Theme.NCMetrics.space8
                        NCStatusChip { text: "Connected"; status: "connected" }
                        NCStatusChip { text: "Needs key"; status: "warning" }
                        NCStatusChip { text: "Loading"; status: "loading"; pulse: true }
                        NCStatusChip { text: "Failed"; status: "error" }
                        NCStatusChip { text: "Disconnected"; status: "disconnected" }
                    }
                }
            }

            NCCard {
                Layout.fillWidth: true
                title: "Feedback and progress"
                description: "Information hierarchy remains readable without relying on color alone"
                NCInlineMessage { Layout.fillWidth: true; tone: "info"; title: "Provider settings"; message: "You are viewing OpenAI settings. LM Studio remains the active provider." }
                NCInlineMessage { Layout.fillWidth: true; tone: "warning"; title: "Model required"; message: "Choose a model before initializing this runtime." }
                NCInlineMessage { Layout.fillWidth: true; tone: "error"; title: "Connection failed"; message: "The provider did not respond before the request timeout."; dismissible: true }
                NCProgressBar { Layout.fillWidth: true; value: 0.63 }
                NCProgressBar { Layout.fillWidth: true; indeterminate: true }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 3
                columnSpacing: Theme.NCMetrics.space12
                NCCard { Layout.fillWidth: true; title: "Normal card"; description: "Stable surface and restrained border." }
                NCCard { Layout.fillWidth: true; title: "Selected card"; description: "Selection is obvious and persistent."; selected: true }
                NCCard { Layout.fillWidth: true; title: "Interactive card"; description: "Hover, press, and keyboard states."; interactive: true }
            }

            NCCard {
                Layout.fillWidth: true
                title: "Empty, loading, and error states"
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.NCMetrics.space16
                    NCEmptyState {
                        Layout.fillWidth: true
                        glyph: "◇"
                        title: "No visual reply selected"
                        description: "Create a visual reply or choose one from the history to inspect it here."
                        actionText: "Create visual reply"
                    }
                    NCLoadingState {
                        Layout.fillWidth: true
                        title: "Loading provider models"
                        description: "The existing request runs outside the UI thread."
                    }
                    NCErrorState {
                        Layout.fillWidth: true
                        title: "Provider unavailable"
                        description: "Check the server address and try again."
                        actionText: "Retry"
                    }
                }
            }
        }
    }
}
