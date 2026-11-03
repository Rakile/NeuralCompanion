pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

NCCard {
    id: root
    required property var bridge
    readonly property var state: bridge.comfyuiGenerationSetup || ({})
    readonly property var profile: state.profile || ({})
    readonly property var samplers: state.samplers || []
    readonly property string dimensionMode: String(profile.dimension_mode || "legacy")
    readonly property string seedMode: String(profile.seed_mode || "legacy")
    readonly property bool overrides: profile.sampler_enabled === true
    readonly property var target: {
        let id = String(profile.sampler_id || (samplers.length === 1 && !state.requires_target ? samplers[0].id : ""))
        for (let sampler of samplers) {
            if (String(sampler.id) === id) return sampler
        }
        return null
    }
    readonly property var dimensionIds: state.dimensions_supported ? ["legacy", "workflow", "custom"] : ["legacy", "workflow"]
    readonly property var seedIds: target && target.supported.seed ? ["legacy", "random", "workflow", "fixed"] : ["legacy"]
    title: qsTr("Generation settings")
    description: qsTr("Workflow values with optional NC overrides. Settings are saved for this server and workflow.")

    function indexOf(values, wanted) {
        for (let i = 0; i < values.length; ++i) if (String(values[i]) === String(wanted)) return i
        return 0
    }
    function save(key, value) { bridge.setComfyUIGenerationField(key, value) }
    function supported(key) { return target !== null && Boolean(target.supported[key]) }
    function fieldValue(key) {
        if (overrides && profile[key] !== undefined) return String(profile[key])
        return target && target.values[key] !== null && target.values[key] !== undefined ? String(target.values[key]) : ""
    }
    function fieldSource(key) {
        if (!target) return qsTr("Select a sampler")
        if (!supported(key)) return qsTr("Read only / linked / unavailable")
        return overrides && profile[key] !== undefined ? qsTr("NC override") : qsTr("Workflow")
    }
    function summary() {
        if (String(state.status || "") !== "Ready") return qsTr("Workflow inspection unavailable; effective settings cannot be confirmed.")
        let dims = String(state.legacySize || "1024x1024")
        if (!state.dimensions_supported) dims = qsTr("Workflow-controlled dimensions")
        if (dimensionMode === "workflow") dims = state.width && state.height ? state.width + "x" + state.height : qsTr("Workflow dimensions")
        if (dimensionMode === "custom") dims = String(profile.width || "?") + "x" + String(profile.height || "?")
        let seed = seedMode === "fixed" ? qsTr("seed %1").arg(String(profile.seed || "0"))
                 : seedMode === "random" ? qsTr("random seed")
                 : seedMode === "workflow" ? qsTr("workflow seed") : qsTr("NC default seed behavior")
        let items = [dims, seed, qsTr("1 image")]
        if (target) {
            for (let field of [{key:"steps",label:qsTr("steps")},{key:"cfg",label:"CFG"},{key:"sampler_name",label:qsTr("sampler")},{key:"scheduler",label:qsTr("scheduler")},{key:"denoise",label:qsTr("denoise")}]) {
                let value = fieldValue(field.key)
                if (value !== "") items.push(field.label + " " + value)
            }
        }
        return items.join(" · ")
    }

    RowLayout {
        Layout.fillWidth: true
        Label {
            Layout.fillWidth: true
            text: String(root.state.status || qsTr("Inspecting workflow…"))
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
        NCButton { text: qsTr("Refresh workflow"); onClicked: root.bridge.refreshComfyUIDetection() }
    }
    GridLayout {
        Layout.fillWidth: true
        columns: width >= 560 ? 2 : 1
        columnSpacing: Theme.NCMetrics.space16
        rowSpacing: Theme.NCMetrics.space12

        ColumnLayout {
            Layout.fillWidth: true
            Label { text: qsTr("Output dimensions"); color: Theme.NCTheme.textSecondary }
            NCComboBox {
                Layout.fillWidth: true
                label: qsTr("Output dimensions")
                toolTipText: qsTr("Choose NC output size, preserve the workflow dimensions, or override supported latent dimensions. Later upscalers or workflow stages can change the final image size. Saved for this server and workflow.")
                model: root.state.dimensions_supported
                    ? [qsTr("NC output size"), qsTr("Use workflow dimensions"), qsTr("Custom dimensions")]
                    : [qsTr("NC output size"), qsTr("Use workflow dimensions")]
                currentIndex: root.indexOf(root.dimensionIds, root.dimensionMode)
                onActivated: root.save("dimension_mode", root.dimensionIds[currentIndex])
            }
            NCComboBox {
                Layout.fillWidth: true
                visible: root.dimensionMode === "legacy"
                label: qsTr("NC output size")
                toolTipText: qsTr("Initial latent size used by the NC output size mode on supported nodes. Auto uses 1024 × 1024. Workflow upscalers can change the final image size.")
                model: root.bridge.visualReplySetup.sizeOptions || []
                currentIndex: root.indexOf(model, root.bridge.visualReplySetup.size)
                onActivated: root.bridge.setVisualReplyField("size", currentText)
            }
            Label {
                Layout.fillWidth: true
                text: root.dimensionMode === "legacy" ? qsTr("Auto uses 1024 × 1024 on supported latent nodes.")
                     : root.state.dimensions_supported ? qsTr("Workflow: %1 × %2").arg(root.state.width).arg(root.state.height)
                     : qsTr("Dimensions are controlled by the workflow graph.")
                wrapMode: Text.Wrap
                color: Theme.NCTheme.textSecondary
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Label { text: qsTr("Seed mode"); color: Theme.NCTheme.textSecondary }
            NCComboBox {
                Layout.fillWidth: true
                label: qsTr("Seed mode")
                toolTipText: qsTr("NC default randomizes the primary KSampler but leaves Advanced noise_seed unchanged. Random, Workflow, and Fixed apply to the selected supported sampler. A linked seed remains workflow controlled.")
                model: root.seedIds.length > 1
                    ? [qsTr("NC default (existing behavior)"), qsTr("Random each reply"), qsTr("Use workflow seed"), qsTr("Fixed seed")]
                    : [qsTr("NC default (existing behavior)")]
                currentIndex: root.indexOf(root.seedIds, root.seedMode)
                onActivated: root.save("seed_mode", root.seedIds[currentIndex])
            }
            NCTextField {
                Layout.fillWidth: true
                visible: root.seedMode === "fixed"
                label: qsTr("Fixed seed (unsigned 64-bit integer)")
                toolTipText: qsTr("Seed reused for each request in Fixed mode. Enter an integer from 0 to 18446744073709551615; 0 is a valid fixed seed. Other workflow settings still affect the generated image.")
                text: String(root.profile.seed || "0")
                onEditingFinished: root.save("seed", text)
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("NC default randomizes the primary KSampler; Advanced noise_seed stays workflow controlled.")
                color: Theme.NCTheme.textSecondary
                wrapMode: Text.Wrap
            }
        }
        Repeater {
            model: root.dimensionMode === "custom" ? ["width", "height"] : []
            delegate: ColumnLayout {
                id: dimensionRow
                required property string modelData
                Layout.fillWidth: true
                Label { text: dimensionRow.modelData === "width" ? qsTr("Width") : qsTr("Height"); color: Theme.NCTheme.textSecondary }
                NCTextField {
                    Layout.fillWidth: true
                    enabled: Boolean(root.state.dimensions_supported)
                    toolTipText: qsTr("Custom initial latent %1 in pixels, saved for this workflow and server. Use a multiple of 8 from 64 to 8192. Missing or linked dimensions cannot be overridden; larger images require more generation work.").arg(dimensionRow.modelData)
                    text: String(root.profile[dimensionRow.modelData] || root.state[dimensionRow.modelData] || "1024")
                    onEditingFinished: root.save(dimensionRow.modelData, text)
                }
            }
        }
    }
    ColumnLayout {
        Layout.fillWidth: true
        Label { text: qsTr("Sampler node"); color: Theme.NCTheme.textSecondary }
        NCComboBox {
            Layout.fillWidth: true
            visible: root.samplers.length > 1
            label: qsTr("Sampler node")
            toolTipText: qsTr("Choose the sampler stage that receives NC sampler and seed overrides. Changing the target clears sampler overrides and restores NC default seed behavior. Other sampler stages keep their workflow values.")
            model: [root.samplers.length === 1 && !root.state.requires_target ? qsTr("Automatic · %1").arg(root.samplers[0].label) : qsTr("Select sampler…")].concat(root.samplers.map(s => s.label))
            currentIndex: root.profile.sampler_id ? root.indexOf([""].concat(root.samplers.map(s => s.id)), root.profile.sampler_id) : 0
            onActivated: root.save("sampler_id", currentIndex === 0 ? "" : root.samplers[currentIndex - 1].id)
        }
        Label {
            visible: root.samplers.length === 1
            text: root.samplers.length === 1 ? qsTr("One sampler node: %1").arg(root.samplers[0].label) : ""
            color: Theme.NCTheme.textSecondary
        }
        Label {
            Layout.fillWidth: true
            visible: root.samplers.length > 1
            text: qsTr("Detected primary: #%1. Overrides affect only the selected sampler node. Changing target clears sampler overrides and restores NC seed behavior.").arg(String(root.state.primary_id || "?"))
            color: Theme.NCTheme.textSecondary
            wrapMode: Text.Wrap
        }
    }
    NCSwitch {
        Layout.fillWidth: true
        text: qsTr("Override sampler settings")
        toolTipText: qsTr("Apply the NC values below to the selected sampler for subsequent requests. Only supported literal fields can be changed; linked or unavailable inputs stay workflow controlled. Turn off to use workflow sampler values.")
        enabled: root.target !== null
        checked: root.overrides
        onClicked: root.save("sampler_enabled", checked)
    }
    GridLayout {
        Layout.fillWidth: true
        columns: width >= 560 ? 2 : 1
        columnSpacing: Theme.NCMetrics.space16
        rowSpacing: Theme.NCMetrics.space12
        Repeater {
            model: [{key:"steps",label:qsTr("Steps")},{key:"cfg",label:"CFG"},{key:"denoise",label:qsTr("Denoise")}]
            delegate: ColumnLayout {
                id: numericRow
                required property var modelData
                Layout.fillWidth: true
                Label { text: numericRow.modelData.label + " · " + root.fieldSource(numericRow.modelData.key); color: Theme.NCTheme.textSecondary }
                NCTextField {
                    id: valueField
                    toolTipText: numericRow.modelData.key === "steps"
                        ? qsTr("Sampling steps for the selected sampler, from 1 to 10000 within the connected server limits. More steps usually require more generation time. Blank removes the override; enable Override sampler settings to edit.")
                        : numericRow.modelData.key === "cfg"
                          ? qsTr("Classifier-free guidance scale for the selected sampler, from 0 to 100 within server limits. This scales prompt guidance; the useful value depends on the model. Blank uses the workflow value; sampler overrides must be on.")
                          : qsTr("Denoising strength for the selected sampler, from 0 to 1 within server limits. Lower values use a smaller part of the denoising schedule. Blank uses the workflow value; sampler overrides must be on.")
                    Layout.fillWidth: true
                    enabled: root.overrides && root.supported(numericRow.modelData.key)
                    text: root.fieldValue(numericRow.modelData.key)
                    placeholderText: qsTr("Unavailable")
                    onTextEdited: editTimer.restart()
                    onEditingFinished: {
                        editTimer.stop()
                        if (text !== root.fieldValue(numericRow.modelData.key)) root.save(numericRow.modelData.key, text)
                    }
                }
                Timer {
                    id: editTimer
                    interval: 600
                    onTriggered: {
                        if (valueField.text !== root.fieldValue(numericRow.modelData.key))
                            root.save(numericRow.modelData.key, valueField.text)
                    }
                }
            }
        }
        Repeater {
            model: [{key:"sampler_name",label:qsTr("Sampler"),options:"samplers"},{key:"scheduler",label:qsTr("Scheduler"),options:"schedulers"}]
            delegate: ColumnLayout {
                id: choiceRow
                required property var modelData
                readonly property var choices: root.target ? root.target[modelData.options] || [] : []
                Layout.fillWidth: true
                Label { text: choiceRow.modelData.label + " · " + root.fieldSource(choiceRow.modelData.key); color: Theme.NCTheme.textSecondary }
                NCComboBox {
                    Layout.fillWidth: true
                    label: choiceRow.modelData.label
                    toolTipText: choiceRow.modelData.key === "sampler_name"
                        ? qsTr("Sampling algorithm for the selected sampler, using choices reported by this ComfyUI server. Workflow keeps the saved algorithm. Requires sampler overrides and an unlinked supported input.")
                        : qsTr("Noise schedule for the selected sampler, using choices reported by this ComfyUI server. Workflow keeps the saved schedule. Requires sampler overrides and an unlinked supported input.")
                    enabled: root.overrides && root.supported(choiceRow.modelData.key) && choiceRow.choices.length > 0
                    model: [qsTr("Workflow · %1").arg(root.target ? String(root.target.values[choiceRow.modelData.key] || qsTr("unavailable")) : "?")].concat(choiceRow.choices)
                    currentIndex: root.indexOf([""].concat(choiceRow.choices), root.overrides ? root.profile[choiceRow.modelData.key] || "" : "")
                    onActivated: root.save(choiceRow.modelData.key, currentIndex === 0 ? "" : choiceRow.choices[currentIndex - 1])
                }
            }
        }
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Next reply: %1").arg(root.summary())
        wrapMode: Text.Wrap
        color: Theme.NCTheme.text
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Workflow dimensions are the initial latent size; upscalers and later stages may change the final image size. Unsupported and linked fields remain read only.")
        color: Theme.NCTheme.textSecondary
        wrapMode: Text.Wrap
    }
    NCButton { text: qsTr("Reset sampler overrides"); onClicked: root.save("reset_sampler", null) }
    NCSwitch { id: advancedToggle; text: qsTr("Advanced options"); toolTipText: qsTr("Show the workflow-specific negative prompt, generation timeout, and ComfyUI memory cleanup settings.") }
    ColumnLayout {
        Layout.fillWidth: true
        visible: advancedToggle.checked
        Label { text: qsTr("Negative prompt (blank uses saved workflow/provider negative)"); color: Theme.NCTheme.textSecondary; wrapMode: Text.Wrap; Layout.fillWidth: true }
        NCTextField {
            Layout.fillWidth: true
            label: qsTr("Negative prompt")
            toolTipText: qsTr("Descriptions to discourage in ComfyUI output. Blank uses the saved workflow or provider negative prompt. NC rendering exclusions are still added. Saved for this server and workflow.")
            text: String(root.profile.negative_prompt || "")
            onEditingFinished: root.save("negative_prompt", text)
        }
        Label { text: qsTr("NC rendering exclusions are still added."); color: Theme.NCTheme.textSecondary }
        Label { text: qsTr("Generation timeout (seconds)"); color: Theme.NCTheme.textSecondary }
        NCTextField {
            Layout.fillWidth: true
            label: qsTr("Generation timeout")
            toolTipText: qsTr("Maximum wait for ComfyUI image output in seconds, from 5 to 86400. A longer timeout allows slower or queued generation to finish. Blank removes this workflow override and uses the provider or environment timeout, normally 180 seconds.")
            text: String(root.state.timeoutSeconds || 180)
            onEditingFinished: root.save("timeout_seconds", text)
        }
        Label { text: qsTr("After generation"); color: Theme.NCTheme.textSecondary }
        NCComboBox {
            Layout.fillWidth: true
            label: qsTr("Memory cleanup")
            toolTipText: qsTr("After generation, keep the ComfyUI cache for faster repeats, request unused memory release, or unload models and free memory. Unloading can make the next request reload models. Applies to this ComfyUI server and workflow.")
            model: [qsTr("Keep cache (fast repeat generation)"), qsTr("Free unused memory"), qsTr("Unload models + free memory (reload next time)")]
            currentIndex: root.indexOf(["keep_cache", "free_memory", "unload_models"], root.state.cleanupMode)
            onActivated: root.save("cleanup_mode", ["keep_cache", "free_memory", "unload_models"][currentIndex])
        }
    }
}
