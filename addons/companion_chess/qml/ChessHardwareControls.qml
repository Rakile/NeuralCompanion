import QtQuick
import QtQuick.Layouts
import "../../../ui/qml/components" as NC
import "../../../ui/qml/theme" as Theme

ColumnLayout {
    id: root
    required property var workspace
    readonly property var hardware: workspace.state.hardware || ({})
    objectName: "chessHardwareSettings"
    spacing: Theme.NCMetrics.space10
    function preferredPort(ports) {
        const model = root.workspace.prefs.hardware_model
        // Only preselect unambiguous legacy names. Other families need the
        // explicitly selected MIDI/Standalone pair, never a guessed DAW port.
        if (model !== "launchpad_s" && model !== "launchpad_mk1") return -1
        let matches = []
        const name = model === "launchpad_mk1"
            ? /novlpd01|(?:^|\b)launchpad(?:\s+(?:mk\s*1|original|classic))?(?:\s+\d+)?$/i
            : /launchpad\s*s\b/i
        for (let i = 0; i < ports.length; ++i) if (name.test(ports[i])) matches.push(i)
        return matches.length === 1 ? matches[0] : -1
    }
    ChessLabel { text: "Launchpad hardware"; color: Theme.NCTheme.text; font.weight: Font.DemiBold }
    NC.NCComboBox {
        objectName: "chessHardwareModel"
        Layout.fillWidth: true; label: "Launchpad model"
        model: root.workspace.hardwareModels
        textRole: "label"; valueRole: "id"
        enabled: !root.hardware.connected && !root.workspace.state.busy
        currentIndex: {
            for (let i = 0; i < count; ++i) if (valueAt(i) === root.workspace.prefs.hardware_model) return i
            return -1
        }
        onActivated: root.workspace.setting("hardware_model", currentValue)
    }
    ChessLabel {
        Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize
        text: {
            let profile = root.workspace.hardwareModels.find(item => item.id === root.workspace.prefs.hardware_model)
            return profile ? profile.description : "Choose your Launchpad model and matching input/output ports."
        }
    }
    ChessLabel { text: "Input" }
    NC.NCComboBox {
        id: inputPort
        objectName: "chessHardwareInput"
        Layout.fillWidth: true; label: "Launchpad input"
        model: root.hardware.inputs || []
        currentIndex: root.preferredPort(model)
        displayText: currentIndex < 0 ? "Select input port" : currentText
    }
    ChessLabel { text: "Output" }
    NC.NCComboBox {
        id: outputPort
        objectName: "chessHardwareOutput"
        Layout.fillWidth: true; label: "Launchpad output"
        model: root.hardware.outputs || []
        currentIndex: root.preferredPort(model)
        displayText: currentIndex < 0 ? "Select output port" : currentText
    }
    NC.NCButton {
        Layout.fillWidth: true; text: root.hardware.connected ? "Disconnect" : "Connect ports"
        enabled: !root.workspace.state.busy && !root.workspace.settingsPending && (root.hardware.connected || (inputPort.currentIndex >= 0 && outputPort.currentIndex >= 0 && root.workspace.connected))
        onClicked: root.workspace.command(root.hardware.connected ? "disconnect_hardware" : "connect_hardware",
            {input: inputPort.currentText, output: outputPort.currentText})
    }
    ChessLabel { text: "Physical orientation" }
    NC.NCComboBox {
        Layout.fillWidth: true; label: "Physical orientation"; model: ["White", "Black"]
        currentIndex: root.workspace.prefs.orientation === "black" ? 1 : 0
        onActivated: root.workspace.setting("orientation", currentIndex === 1 ? "black" : "white")
    }
    NC.NCButton { Layout.fillWidth: true; text: "Test corner LEDs"; enabled: root.hardware.connected === true && !root.workspace.state.busy; onClicked: root.workspace.command("calibrate") }
    NC.NCButton { Layout.fillWidth: true; text: "Physical board matches"; enabled: root.hardware.connected === true && root.workspace.connected && !root.workspace.state.busy; onClicked: root.workspace.command("reconcile") }
    NC.NCButton { Layout.fillWidth: true; text: "Continue on screen"; enabled: root.workspace.connected && !root.workspace.state.busy; onClicked: root.workspace.confirmAction("continue_desktop") }
    ChessLabel {
        Layout.fillWidth: true; font.pixelSize: Theme.NCTypography.captionSize
        text: root.hardware.error || "Match the displayed position before confirming. Pads confirm moves; they do not sense pieces."
    }
}
