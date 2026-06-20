// Minimal starter sketch for a VaM-side Neural Companion bridge.
//
// Goals:
// - poll a shared folder for JSON command files
// - apply expression presets
// - toggle speaking state
// - optionally play head audio
// - optionally trigger Timeline / follow actions
//
// This is intentionally conservative. Treat it as a starter scaffold rather than
// a finished drop-in plugin. The exact expression, head-audio, and Timeline
// hookups vary across VaM scenes and plugin stacks.

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.UI;
using MVR.FileManagementSecure;
using SimpleJSON;
using AssetBundles;
using Object = UnityEngine.Object;

public class NeuralCompanionBridge : MVRScript
{
    private const string BridgeVersion = "2026-06-13-hymotion-events-timeline";

    [Serializable]
    private class BridgeCommand
    {
        public string session_id;
        public string command_id;
        public double sent_at;
        public string action;
        public BridgePayload payload;
    }

    [Serializable]
    private class BridgePayload
    {
        public string target_atom_uid;
        public string target_storable_id;
        public string emotion;
        public bool speaking;
        public bool timeline_auto_resume;
        public string expression_preset;
        public string audio_path;
        public float audio_duration_seconds;
        public string text;
        public string timeline_clip;
        public bool play_audio_in_vam;
        public bool enabled;
        public string motion_source;
        public string prompt;
        public float duration_seconds;
        public int frame_count;
        public string output_dir;
        public string motion_stage_dir;
        public string motion_manifest_path;
        public string motion_file;
        public string motion_fbx_path;
        public string motion_npz_path;
        public string motion_smpl_path;
        public string motion_voxta_debug_path;
        public string motion_proxy_path;
        public string motion_timeline_clip_path;
        public string motion_timeline_storable_path;
        public string motion_meta_path;
        public string motion_asset_status;
        public string notes;
    }

    [Serializable]
    private class BridgeStatus
    {
        public string state;
        public string lastAction;
        public string lastEmotion;
        public bool speaking;
        public string targetAtomUid;
        public string note;
        public string bridgeVersion;
        public double updatedAt;
    }

    private JSONStorableString bridgeVersionJSON;
    private JSONStorableString bridgeRootJSON;
    private JSONStorableBool pollingEnabledJSON;
    private JSONStorableString targetAtomUidJSON;
    private JSONStorableString hyMotionEventJSON;
    private JSONStorableBool hyMotionSmplEnabledJSON;
    private JSONStorableFloat hyMotionStrengthJSON;
    private JSONStorableFloat hyMotionRotationStrengthJSON;
    private JSONStorableBool hyMotionProxyEnabledJSON;
    private JSONStorableFloat hyMotionProxyStrengthJSON;
    private JSONStorableFloat hyMotionBlendSecondsJSON;
    private JSONStorableBool hyMotionLoopJSON;
    private JSONStorableBool hyMotionResetOnStopJSON;
    private JSONStorableBool hyMotionDriveRootJSON;
    private JSONStorableBool hyMotionDriveUpperBodyJSON;
    private JSONStorableBool hyMotionDriveArmsJSON;
    private JSONStorableBool hyMotionDriveLegsJSON;
    private JSONStorableBool hyMotionConflictGuardJSON;
    private JSONStorableString hyMotionLoadNameJSON;
    private JSONStorableString hyMotionLoadedNameJSON;
    private JSONStorableString statusJSON;
    private JSONStorableAction bridgeSelfTestAction;
    private JSONStorableAction playLatestHYMotionAction;
    private JSONStorableAction stopHYMotionAction;
    private JSONStorableAction resetHYMotionPoseAction;
    private JSONStorableAction loadHYMotionByNameAction;
    private JSONStorableAction openHYMotionStartedTriggerAction;
    private JSONStorableAction openHYMotionFinishedTriggerAction;
    private JSONStorableAction openHYMotionFailedTriggerAction;

    private string bridgeRoot;
    private string inboxDir;
    private string outboxDir;
    private string statusPath;
    private string tracePath;
    private string hyMotionEventPath;
    private string hyMotionEventsLogPath;
    private Coroutine pollLoop;
    private Coroutine audioPlaybackLoop;
    private Coroutine speakingWindowLoop;
    private Coroutine hyMotionPlaybackLoop;
    private Coroutine hyMotionResetLoop;
    private AudioSourceControl headAudioSource;

    private string currentEmotion = "neutral";
    private bool currentSpeaking = false;
    private bool hyMotionStopRequested = false;
    private string lastHyMotionSmplPath = "";
    private string lastHyMotionProxyPath = "";
    private string lastHyMotionFbxPath = "";
    private string lastHyMotionNpzPath = "";
    private string lastHyMotionName = "";
    private string lastHyMotionPrompt = "";
    private float lastHyMotionDuration = 0f;
    private int lastHyMotionFrameCount = 0;
    private BridgePayload lastHyMotionPayload;
    private NCBridgeSimpleTrigger hyMotionStartedTrigger;
    private NCBridgeSimpleTrigger hyMotionFinishedTrigger;
    private NCBridgeSimpleTrigger hyMotionFailedTrigger;

    private class ControllerSnapshot
    {
        public FreeControllerV3 controller;
        public Vector3 position;
        public Quaternion rotation;
        public FreeControllerV3.PositionState positionState;
        public FreeControllerV3.RotationState rotationState;
    }

    private class BoolParamSnapshot
    {
        public JSONStorableBool param;
        public bool value;
        public string label;
    }

    private List<ControllerSnapshot> hyMotionPoseSnapshot = new List<ControllerSnapshot>();
    private List<BoolParamSnapshot> hyMotionConflictSnapshot = new List<BoolParamSnapshot>();

    public override void Init()
    {
        try
        {
            bridgeVersionJSON = new JSONStorableString("Bridge Version", BridgeVersion);
            bridgeVersionJSON.isStorable = false;
            bridgeVersionJSON.isRestorable = false;
            bridgeRootJSON = new JSONStorableString("Bridge Root", "Custom/PluginData/NeuralCompanionBridge");
            pollingEnabledJSON = new JSONStorableBool("Polling Enabled", true);
            targetAtomUidJSON = new JSONStorableString("Target Atom UID", containingAtom != null ? containingAtom.uid : "");
            hyMotionEventJSON = new JSONStorableString("Last HY-Motion Event", "");
            hyMotionEventJSON.isStorable = false;
            hyMotionEventJSON.isRestorable = false;
            hyMotionSmplEnabledJSON = new JSONStorableBool("HY-Motion SMPL Playback", true);
            hyMotionStrengthJSON = new JSONStorableFloat("Set HY-Motion Strength", 1.0f, 0.0f, 2.0f, true);
            hyMotionRotationStrengthJSON = new JSONStorableFloat("HY-Motion Rotation Strength", 1.0f, 0.0f, 2.0f, true);
            hyMotionProxyEnabledJSON = new JSONStorableBool("HY-Motion Proxy Playback", true);
            hyMotionProxyStrengthJSON = new JSONStorableFloat("HY-Motion Proxy Strength", 1.0f, 0.0f, 2.0f, true);
            hyMotionBlendSecondsJSON = new JSONStorableFloat("HY-Motion Blend Seconds", 0.35f, 0.0f, 2.0f, true);
            hyMotionLoopJSON = new JSONStorableBool("Loop HY-Motion", false);
            hyMotionResetOnStopJSON = new JSONStorableBool("Reset HY-Motion Pose On Stop", true);
            hyMotionDriveRootJSON = new JSONStorableBool("HY-Motion Drive Root", true);
            hyMotionDriveUpperBodyJSON = new JSONStorableBool("HY-Motion Drive Upper Body", true);
            hyMotionDriveArmsJSON = new JSONStorableBool("HY-Motion Drive Arms", true);
            hyMotionDriveLegsJSON = new JSONStorableBool("HY-Motion Drive Legs", false);
            hyMotionConflictGuardJSON = new JSONStorableBool("HY-Motion Conflict Guard", true);
            hyMotionLoadNameJSON = new JSONStorableString("HY-Motion Name", "");
            hyMotionLoadedNameJSON = new JSONStorableString("Loaded HY-Motion", "");
            hyMotionLoadedNameJSON.isStorable = false;
            hyMotionLoadedNameJSON.isRestorable = false;
            bridgeSelfTestAction = new JSONStorableAction("NC Bridge Self Test", BridgeSelfTest);
            playLatestHYMotionAction = new JSONStorableAction("Play Latest HY-Motion", PlayLatestHYMotion);
            stopHYMotionAction = new JSONStorableAction("Stop HY-Motion", StopHYMotionFromAction);
            resetHYMotionPoseAction = new JSONStorableAction("Reset HY-Motion Pose", ResetHYMotionPoseFromAction);
            loadHYMotionByNameAction = new JSONStorableAction("Load HY-Motion By Name", LoadHYMotionByName);
            openHYMotionStartedTriggerAction = new JSONStorableAction("Open HY-Motion Started Trigger", OpenHYMotionStartedTrigger);
            openHYMotionFinishedTriggerAction = new JSONStorableAction("Open HY-Motion Finished Trigger", OpenHYMotionFinishedTrigger);
            openHYMotionFailedTriggerAction = new JSONStorableAction("Open HY-Motion Missing/Failed Trigger", OpenHYMotionFailedTrigger);
            hyMotionStartedTrigger = new NCBridgeSimpleTrigger("On HY-Motion Started", null);
            hyMotionFinishedTrigger = new NCBridgeSimpleTrigger("On HY-Motion Finished", null);
            hyMotionFailedTrigger = new NCBridgeSimpleTrigger("On HY-Motion Missing/Failed", null);
            statusJSON = new JSONStorableString("Bridge Status", "Idle");
            statusJSON.isStorable = false;
            statusJSON.isRestorable = false;

            RegisterString(bridgeVersionJSON);
            RegisterString(bridgeRootJSON);
            RegisterBool(pollingEnabledJSON);
            RegisterString(targetAtomUidJSON);
            RegisterString(hyMotionEventJSON);
            RegisterBool(hyMotionSmplEnabledJSON);
            RegisterFloat(hyMotionStrengthJSON);
            RegisterFloat(hyMotionRotationStrengthJSON);
            RegisterBool(hyMotionProxyEnabledJSON);
            RegisterFloat(hyMotionProxyStrengthJSON);
            RegisterFloat(hyMotionBlendSecondsJSON);
            RegisterBool(hyMotionLoopJSON);
            RegisterBool(hyMotionResetOnStopJSON);
            RegisterBool(hyMotionDriveRootJSON);
            RegisterBool(hyMotionDriveUpperBodyJSON);
            RegisterBool(hyMotionDriveArmsJSON);
            RegisterBool(hyMotionDriveLegsJSON);
            RegisterBool(hyMotionConflictGuardJSON);
            RegisterString(hyMotionLoadNameJSON);
            RegisterString(hyMotionLoadedNameJSON);
            RegisterAction(bridgeSelfTestAction);
            RegisterAction(playLatestHYMotionAction);
            RegisterAction(stopHYMotionAction);
            RegisterAction(resetHYMotionPoseAction);
            RegisterAction(loadHYMotionByNameAction);
            RegisterAction(openHYMotionStartedTriggerAction);
            RegisterAction(openHYMotionFinishedTriggerAction);
            RegisterAction(openHYMotionFailedTriggerAction);
            RegisterString(statusJSON);

            CreateTextField(bridgeVersionJSON);
            CreateTextField(bridgeRootJSON);
            CreateToggle(pollingEnabledJSON);
            CreateTextField(targetAtomUidJSON);
            CreateTextField(hyMotionEventJSON);
            CreateToggle(hyMotionSmplEnabledJSON);
            CreateSlider(hyMotionStrengthJSON);
            CreateSlider(hyMotionRotationStrengthJSON);
            CreateToggle(hyMotionProxyEnabledJSON);
            CreateSlider(hyMotionProxyStrengthJSON);
            CreateSlider(hyMotionBlendSecondsJSON);
            CreateToggle(hyMotionLoopJSON);
            CreateToggle(hyMotionResetOnStopJSON);
            CreateToggle(hyMotionDriveRootJSON);
            CreateToggle(hyMotionDriveUpperBodyJSON);
            CreateToggle(hyMotionDriveArmsJSON);
            CreateToggle(hyMotionDriveLegsJSON);
            CreateToggle(hyMotionConflictGuardJSON);
            CreateTextField(hyMotionLoadNameJSON);
            CreateTextField(hyMotionLoadedNameJSON);
            CreateButton("NC Bridge Self Test").button.onClick.AddListener(BridgeSelfTest);
            CreateButton("Play Latest HY-Motion").button.onClick.AddListener(PlayLatestHYMotion);
            CreateButton("Stop HY-Motion").button.onClick.AddListener(StopHYMotionFromAction);
            CreateButton("Reset HY-Motion Pose").button.onClick.AddListener(ResetHYMotionPoseFromAction);
            CreateButton("Load HY-Motion By Name").button.onClick.AddListener(LoadHYMotionByName);
            CreateButton("On HY-Motion Started Trigger").button.onClick.AddListener(OpenHYMotionStartedTrigger);
            CreateButton("On HY-Motion Finished Trigger").button.onClick.AddListener(OpenHYMotionFinishedTrigger);
            CreateButton("On HY-Motion Missing/Failed Trigger").button.onClick.AddListener(OpenHYMotionFailedTrigger);
            CreateTextField(statusJSON);

            RebuildPaths();
            WriteStatus("ready", "init", "Bridge initialized " + BridgeVersion);
            if (SuperController.singleton != null)
            {
                SuperController.singleton.onAtomUIDRenameHandlers += OnAtomRename;
            }

            pollLoop = StartCoroutine(PollInboxLoop());
        }
        catch (Exception exc)
        {
            SuperController.LogError("[NeuralCompanionBridge] Init failed: " + exc);
        }
    }

    private void RebuildPaths()
    {
        bridgeRoot = NormalizeRoot(bridgeRootJSON != null ? bridgeRootJSON.val : "");
        inboxDir = CombinePath(bridgeRoot, "inbox");
        outboxDir = CombinePath(bridgeRoot, "outbox");
        statusPath = CombinePath(outboxDir, "status.json");
        tracePath = CombinePath(outboxDir, "trace.log");
        hyMotionEventPath = CombinePath(outboxDir, "hy_motion_event.json");
        hyMotionEventsLogPath = CombinePath(outboxDir, "hy_motion_events.log");

        FileManagerSecure.CreateDirectory(bridgeRoot);
        FileManagerSecure.CreateDirectory(inboxDir);
        FileManagerSecure.CreateDirectory(outboxDir);
    }

    public override void InitUI()
    {
        base.InitUI();
        try
        {
            if (UITransform != null)
            {
                AssignTriggerParent(hyMotionStartedTrigger);
                AssignTriggerParent(hyMotionFinishedTrigger);
                AssignTriggerParent(hyMotionFailedTrigger);
                StartCoroutine(NCBridgeVamAssets.LoadUIAssets());
            }
        }
        catch (Exception exc)
        {
            AppendTrace("InitUI trigger setup failed: " + exc.Message);
        }
    }

    public override void Validate()
    {
        base.Validate();
        ValidateTrigger(hyMotionStartedTrigger);
        ValidateTrigger(hyMotionFinishedTrigger);
        ValidateTrigger(hyMotionFailedTrigger);
    }

    private void AssignTriggerParent(NCBridgeSimpleTrigger trigger)
    {
        if (trigger != null && trigger.Trigger != null && UITransform != null)
        {
            trigger.Trigger.triggerActionsParent = UITransform;
        }
    }

    private void ValidateTrigger(NCBridgeSimpleTrigger trigger)
    {
        if (trigger != null && trigger.Trigger != null)
        {
            trigger.Trigger.Validate();
        }
    }

    private void OnAtomRename(string before, string after)
    {
        SyncTriggerAtomNames(hyMotionStartedTrigger);
        SyncTriggerAtomNames(hyMotionFinishedTrigger);
        SyncTriggerAtomNames(hyMotionFailedTrigger);
    }

    private void SyncTriggerAtomNames(NCBridgeSimpleTrigger trigger)
    {
        if (trigger != null)
        {
            trigger.OnAtomRename();
        }
    }

    private void OpenHYMotionStartedTrigger()
    {
        OpenHYMotionTrigger(hyMotionStartedTrigger);
    }

    private void OpenHYMotionFinishedTrigger()
    {
        OpenHYMotionTrigger(hyMotionFinishedTrigger);
    }

    private void OpenHYMotionFailedTrigger()
    {
        OpenHYMotionTrigger(hyMotionFailedTrigger);
    }

    private void OpenHYMotionTrigger(NCBridgeSimpleTrigger trigger)
    {
        try
        {
            AssignTriggerParent(trigger);
            if (trigger != null && trigger.Trigger != null)
            {
                trigger.Trigger.OpenTriggerActionsPanel();
            }
        }
        catch (Exception exc)
        {
            WriteStatus("error", "hy_motion_trigger_panel", "Could not open trigger panel: " + exc.Message);
        }
    }

    private string NormalizeRoot(string raw)
    {
        string value = string.IsNullOrEmpty(raw) ? "Custom/PluginData/NeuralCompanionBridge" : raw.Trim();
        value = value.Replace("\\", "/");
        if (
            !value.StartsWith("Custom/PluginData/", StringComparison.OrdinalIgnoreCase) &&
            !value.Equals("Custom/PluginData", StringComparison.OrdinalIgnoreCase) &&
            !value.StartsWith("Saves/PluginData/", StringComparison.OrdinalIgnoreCase) &&
            !value.Equals("Saves/PluginData", StringComparison.OrdinalIgnoreCase)
        )
        {
            value = "Custom/PluginData/NeuralCompanionBridge";
        }
        return FileManagerSecure.NormalizePath(value);
    }

    private string CombinePath(string left, string right)
    {
        string lhs = string.IsNullOrEmpty(left) ? "" : left.TrimEnd('/', '\\');
        string rhs = string.IsNullOrEmpty(right) ? "" : right.TrimStart('/', '\\');
        if (string.IsNullOrEmpty(lhs))
        {
            return rhs;
        }
        if (string.IsNullOrEmpty(rhs))
        {
            return lhs;
        }
        return lhs + "/" + rhs;
    }

    private IEnumerator PollInboxLoop()
    {
        while (true)
        {
            if (pollingEnabledJSON != null && pollingEnabledJSON.val)
            {
                RebuildPaths();
                ProcessInbox();
            }
            yield return new WaitForSeconds(0.10f);
        }
    }

    private void ProcessInbox()
        {
            string[] files;
            try
            {
                files = FileManagerSecure.GetFiles(inboxDir, "*.json");
                Array.Sort(files, StringComparer.Ordinal);
            }
            catch (Exception exc)
            {
                WriteStatus("error", "scan_inbox", exc.Message);
                return;
            }

            foreach (string filePath in files)
            {
                try
                {
                    string json = FileManagerSecure.ReadAllText(filePath);
                    BridgeCommand command = ParseBridgeCommand(json);
                    HandleCommand(command);
                    FileManagerSecure.DeleteFile(filePath);
                }
                catch (Exception exc)
                {
                    WriteStatus("error", "process_command", exc.Message);
                }
            }
        }

    private BridgeCommand ParseBridgeCommand(string json)
    {
        JSONNode root = JSON.Parse(json);
        if (root == null)
        {
            return null;
        }

        JSONNode payloadNode = root["payload"];
        BridgePayload payload = new BridgePayload();
        if (payloadNode != null)
        {
            payload.target_atom_uid = JsonString(payloadNode, "target_atom_uid");
            payload.target_storable_id = JsonString(payloadNode, "target_storable_id");
            payload.emotion = JsonString(payloadNode, "emotion");
            payload.speaking = JsonBool(payloadNode, "speaking");
            payload.timeline_auto_resume = JsonBool(payloadNode, "timeline_auto_resume");
            payload.expression_preset = JsonString(payloadNode, "expression_preset");
            payload.audio_path = JsonString(payloadNode, "audio_path");
            payload.audio_duration_seconds = JsonFloat(payloadNode, "audio_duration_seconds");
            payload.text = JsonString(payloadNode, "text");
            payload.timeline_clip = JsonString(payloadNode, "timeline_clip");
            payload.play_audio_in_vam = JsonBool(payloadNode, "play_audio_in_vam");
            payload.enabled = JsonBool(payloadNode, "enabled");
            payload.motion_source = JsonString(payloadNode, "motion_source");
            payload.prompt = JsonString(payloadNode, "prompt");
            payload.duration_seconds = JsonFloat(payloadNode, "duration_seconds");
            payload.frame_count = JsonInt(payloadNode, "frame_count");
            payload.output_dir = JsonString(payloadNode, "output_dir");
            payload.motion_stage_dir = JsonString(payloadNode, "motion_stage_dir");
            payload.motion_manifest_path = JsonString(payloadNode, "motion_manifest_path");
            payload.motion_file = JsonString(payloadNode, "motion_file");
            payload.motion_fbx_path = JsonString(payloadNode, "motion_fbx_path");
            payload.motion_npz_path = JsonString(payloadNode, "motion_npz_path");
            payload.motion_smpl_path = JsonString(payloadNode, "motion_smpl_path");
            payload.motion_voxta_debug_path = JsonString(payloadNode, "motion_voxta_debug_path");
            payload.motion_proxy_path = JsonString(payloadNode, "motion_proxy_path");
            payload.motion_timeline_clip_path = JsonString(payloadNode, "motion_timeline_clip_path");
            payload.motion_timeline_storable_path = JsonString(payloadNode, "motion_timeline_storable_path");
            payload.motion_meta_path = JsonString(payloadNode, "motion_meta_path");
            payload.motion_asset_status = JsonString(payloadNode, "motion_asset_status");
            payload.notes = JsonString(payloadNode, "notes");
        }

        return new BridgeCommand
        {
            session_id = JsonString(root, "session_id"),
            command_id = JsonString(root, "command_id"),
            sent_at = JsonDouble(root, "sent_at"),
            action = JsonString(root, "action"),
            payload = payload
        };
    }

    private string JsonString(JSONNode node, string key)
    {
        if (node == null)
        {
            return "";
        }
        JSONNode child = node[key];
        return child == null ? "" : child.Value;
    }

    private bool JsonBool(JSONNode node, string key)
    {
        if (node == null || node[key] == null)
        {
            return false;
        }
        return node[key].AsBool;
    }

    private float JsonFloat(JSONNode node, string key)
    {
        if (node == null || node[key] == null)
        {
            return 0f;
        }
        return node[key].AsFloat;
    }

    private double JsonDouble(JSONNode node, string key)
    {
        if (node == null || node[key] == null)
        {
            return 0.0;
        }
        return node[key].AsDouble;
    }

    private int JsonInt(JSONNode node, string key)
    {
        if (node == null || node[key] == null)
        {
            return 0;
        }
        return node[key].AsInt;
    }

    private void HandleCommand(BridgeCommand command)
        {
            if (command == null || string.IsNullOrEmpty(command.action))
            {
                return;
            }

            BridgePayload payload = command.payload ?? new BridgePayload();

            if (!string.IsNullOrEmpty(payload.target_atom_uid) && !string.Equals(payload.target_atom_uid, ResolveTargetAtomUid(), StringComparison.Ordinal))
            {
                return;
            }

            switch (command.action)
            {
                case "session_start":
                    AppendTrace("command session_start");
                    WriteStatus("ready", command.action, "Session started");
                    break;

                case "session_stop":
                    SetSpeaking(false);
                    WriteStatus("idle", command.action, "Session stopped");
                    break;

                case "set_emotion":
                    AppendTrace("command set_emotion emotion=" + payload.emotion + " preset=" + payload.expression_preset);
                    ApplyExpressionPreset(payload.expression_preset, payload.emotion);
                    break;

                case "set_speaking":
                    AppendTrace("command set_speaking speaking=" + payload.speaking);
                    SetSpeaking(payload.speaking);
                    break;

                case "speech_chunk":
                    AppendTrace(
                        "command speech_chunk path=" + payload.audio_path +
                        " play_audio_in_vam=" + payload.play_audio_in_vam +
                        " duration=" + payload.audio_duration_seconds
                    );
                    WriteStatus("ready", command.action, string.IsNullOrEmpty(payload.text) ? "Speech chunk queued" : payload.text);
                    if (!string.IsNullOrEmpty(payload.expression_preset) || !string.IsNullOrEmpty(payload.emotion))
                    {
                        ApplyExpressionPreset(payload.expression_preset, payload.emotion);
                    }
                    SetSpeaking(true);
                    ArmSpeakingWindow(payload.audio_duration_seconds);
                    if (payload.play_audio_in_vam && !string.IsNullOrEmpty(payload.audio_path))
                    {
                        AppendTrace("speech_chunk -> PlayHeadAudio");
                        PlayHeadAudio(payload.audio_path, payload.audio_duration_seconds);
                    }
                    if (!string.IsNullOrEmpty(payload.timeline_clip))
                    {
                        PlayTimelineClip(payload.timeline_clip, payload.timeline_auto_resume);
                    }
                    break;

                case "play_timeline_clip":
                    PlayTimelineClip(payload.timeline_clip, payload.timeline_auto_resume);
                    break;

                case "follow_state":
                    SetFollowState(payload.enabled);
                    break;

                case "bridge_self_test":
                    BridgeSelfTest();
                    break;

                case "hy_motion_generated":
                    HandleHYMotionGenerated(command, payload);
                    break;

                case "hy_motion_play_latest":
                    PlayLatestHYMotion();
                    break;

                case "hy_motion_stop":
                    StopHYMotionFromAction();
                    break;

                case "hy_motion_reset_pose":
                    ResetHYMotionPoseFromAction();
                    break;

                case "hy_motion_load_by_name":
                    if (!string.IsNullOrEmpty(payload.motion_stage_dir))
                    {
                        hyMotionLoadNameJSON.val = FileManagerSecure.GetFileName(payload.motion_stage_dir.TrimEnd('/', '\\'));
                    }
                    LoadHYMotionByName();
                    break;

                default:
                    AppendTrace("unknown command action=" + command.action);
                    WriteStatus("warning", command.action, "Unknown bridge command");
                    break;
            }
        }

    private string FirstNonEmpty(params string[] values)
    {
        if (values == null)
        {
            return "";
        }
        for (int i = 0; i < values.Length; i++)
        {
            if (!string.IsNullOrEmpty(values[i]))
            {
                return values[i];
            }
        }
        return "";
    }

    private string NormalizeBridgeReadablePath(string path)
    {
        if (string.IsNullOrEmpty(path))
        {
            return "";
        }
        return FileManagerSecure.NormalizePath(path.Replace("\\", "/"));
    }

    private bool BridgeFileExists(string path, out string normalized)
    {
        normalized = NormalizeBridgeReadablePath(path);
        if (string.IsNullOrEmpty(normalized))
        {
            return false;
        }
        try
        {
            return FileManagerSecure.FileExists(normalized);
        }
        catch
        {
            return false;
        }
    }

    private string JsonEscape(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "";
        }
        return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
    }

    private void WriteHYMotionReceipt(
        BridgePayload payload,
        string normalizedFbx,
        bool fbxExists,
        string normalizedNpz,
        bool npzExists,
        string normalizedSmpl,
        bool smplExists,
        string normalizedProxy,
        bool proxyExists,
        string note
    )
    {
        try
        {
            string receiptPath = CombinePath(outboxDir, "last_hy_motion.json");
            string json =
                "{\n" +
                "  \"source\": \"hy_motion\",\n" +
                "  \"prompt\": \"" + JsonEscape(payload.prompt) + "\",\n" +
                "  \"fbx_path\": \"" + JsonEscape(normalizedFbx) + "\",\n" +
                "  \"fbx_exists\": " + (fbxExists ? "true" : "false") + ",\n" +
                "  \"npz_path\": \"" + JsonEscape(normalizedNpz) + "\",\n" +
                "  \"npz_exists\": " + (npzExists ? "true" : "false") + ",\n" +
                "  \"smpl_path\": \"" + JsonEscape(normalizedSmpl) + "\",\n" +
                "  \"smpl_exists\": " + (smplExists ? "true" : "false") + ",\n" +
                "  \"voxta_debug_path\": \"" + JsonEscape(payload.motion_voxta_debug_path) + "\",\n" +
                "  \"proxy_path\": \"" + JsonEscape(normalizedProxy) + "\",\n" +
                "  \"proxy_exists\": " + (proxyExists ? "true" : "false") + ",\n" +
                "  \"timeline_clip_path\": \"" + JsonEscape(payload.motion_timeline_clip_path) + "\",\n" +
                "  \"timeline_storable_path\": \"" + JsonEscape(payload.motion_timeline_storable_path) + "\",\n" +
                "  \"motion_stage_dir\": \"" + JsonEscape(payload.motion_stage_dir) + "\",\n" +
                "  \"motion_manifest_path\": \"" + JsonEscape(payload.motion_manifest_path) + "\",\n" +
                "  \"frame_count\": " + payload.frame_count + ",\n" +
                "  \"duration_seconds\": " + payload.duration_seconds.ToString("0.###", CultureInfo.InvariantCulture) + ",\n" +
                "  \"note\": \"" + JsonEscape(note) + "\",\n" +
                "  \"updatedAt\": " + ((double)Time.realtimeSinceStartup).ToString("0.###", CultureInfo.InvariantCulture) + "\n" +
                "}\n";
            FileManagerSecure.WriteAllText(receiptPath, json);
        }
        catch (Exception exc)
        {
            AppendTrace("WriteHYMotionReceipt failed: " + exc.Message);
        }
    }

    private void FireHYMotionEvent(string eventName, BridgePayload payload, string note)
    {
        try
        {
            string safeEvent = string.IsNullOrEmpty(eventName) ? "unknown" : eventName;
            string name = !string.IsNullOrEmpty(lastHyMotionName) ? lastHyMotionName : MotionNameFromStageDir(payload != null ? payload.motion_stage_dir : "");
            string json =
                "{\n" +
                "  \"source\": \"NeuralCompanionBridge\",\n" +
                "  \"event\": \"" + JsonEscape(safeEvent) + "\",\n" +
                "  \"motion_name\": \"" + JsonEscape(name) + "\",\n" +
                "  \"prompt\": \"" + JsonEscape(payload != null ? payload.prompt : lastHyMotionPrompt) + "\",\n" +
                "  \"frame_count\": " + ((payload != null && payload.frame_count > 0) ? payload.frame_count : lastHyMotionFrameCount) + ",\n" +
                "  \"duration_seconds\": " + ((payload != null && payload.duration_seconds > 0.0f) ? payload.duration_seconds : lastHyMotionDuration).ToString("0.###", CultureInfo.InvariantCulture) + ",\n" +
                "  \"target_atom_uid\": \"" + JsonEscape(ResolveTargetAtomUid()) + "\",\n" +
                "  \"note\": \"" + JsonEscape(note) + "\",\n" +
                "  \"bridge_version\": \"" + JsonEscape(BridgeVersion) + "\",\n" +
                "  \"updatedAt\": " + ((double)Time.realtimeSinceStartup).ToString("0.###", CultureInfo.InvariantCulture) + "\n" +
                "}\n";
            if (!string.IsNullOrEmpty(hyMotionEventPath))
            {
                FileManagerSecure.WriteAllText(hyMotionEventPath, json);
            }
            if (!string.IsNullOrEmpty(hyMotionEventsLogPath))
            {
                string existing = FileManagerSecure.FileExists(hyMotionEventsLogPath) ? FileManagerSecure.ReadAllText(hyMotionEventsLogPath) : "";
                FileManagerSecure.WriteAllText(hyMotionEventsLogPath, existing + DateTime.Now.ToString("HH:mm:ss.fff") + " | " + safeEvent + " | " + note + "\n");
            }
            if (hyMotionEventJSON != null)
            {
                hyMotionEventJSON.val = safeEvent + " | " + note;
            }
            AppendTrace("HY event " + safeEvent + " | " + note);

            if (safeEvent == "started")
            {
                ToggleHYMotionTrigger(hyMotionStartedTrigger);
            }
            else if (safeEvent == "finished")
            {
                ToggleHYMotionTrigger(hyMotionFinishedTrigger);
            }
            else if (safeEvent == "failed" || safeEvent == "missing")
            {
                ToggleHYMotionTrigger(hyMotionFailedTrigger);
            }
        }
        catch (Exception exc)
        {
            AppendTrace("FireHYMotionEvent failed: " + exc.Message);
        }
    }

    private void ToggleHYMotionTrigger(NCBridgeSimpleTrigger trigger)
    {
        if (trigger != null)
        {
            trigger.Toggle();
        }
    }

    private void HandleHYMotionGenerated(BridgeCommand command, BridgePayload payload)
    {
        string fbxPath = FirstNonEmpty(payload.motion_fbx_path, payload.motion_file);
        string npzPath = payload.motion_npz_path;
        string smplPath = payload.motion_smpl_path;
        string proxyPath = payload.motion_proxy_path;
        string normalizedFbx;
        string normalizedNpz;
        string normalizedSmpl;
        string normalizedProxy;
        bool fbxExists = BridgeFileExists(fbxPath, out normalizedFbx);
        bool npzExists = BridgeFileExists(npzPath, out normalizedNpz);
        bool smplExists = BridgeFileExists(smplPath, out normalizedSmpl);
        bool proxyExists = BridgeFileExists(proxyPath, out normalizedProxy);

        AppendTrace(
            "command hy_motion_generated fbx=" + normalizedFbx +
            " fbx_exists=" + fbxExists +
            " npz=" + normalizedNpz +
            " npz_exists=" + npzExists +
            " smpl=" + normalizedSmpl +
            " smpl_exists=" + smplExists +
            " proxy=" + normalizedProxy +
            " proxy_exists=" + proxyExists +
            " frames=" + payload.frame_count +
            " duration=" + payload.duration_seconds
        );

        RememberHYMotion(payload, normalizedSmpl, smplExists, normalizedProxy, proxyExists, normalizedFbx, fbxExists, normalizedNpz, npzExists);
        string note = StartHYMotionPlayback(payload, normalizedSmpl, smplExists, normalizedProxy, proxyExists, normalizedFbx, fbxExists, normalizedNpz, npzExists, "hy_motion_generated");

        WriteHYMotionReceipt(payload, normalizedFbx, fbxExists, normalizedNpz, npzExists, normalizedSmpl, smplExists, normalizedProxy, proxyExists, note);
    }

    private string MotionNameFromStageDir(string stageDir)
    {
        string clean = string.IsNullOrEmpty(stageDir) ? "" : stageDir.TrimEnd('/', '\\');
        string name = string.IsNullOrEmpty(clean) ? "" : FileManagerSecure.GetFileName(clean);
        return string.IsNullOrEmpty(name) ? "latest" : name;
    }

    private void RememberHYMotion(
        BridgePayload payload,
        string normalizedSmpl,
        bool smplExists,
        string normalizedProxy,
        bool proxyExists,
        string normalizedFbx,
        bool fbxExists,
        string normalizedNpz,
        bool npzExists
    )
    {
        lastHyMotionPayload = payload;
        lastHyMotionSmplPath = smplExists ? normalizedSmpl : "";
        lastHyMotionProxyPath = proxyExists ? normalizedProxy : "";
        lastHyMotionFbxPath = fbxExists ? normalizedFbx : "";
        lastHyMotionNpzPath = npzExists ? normalizedNpz : "";
        lastHyMotionPrompt = payload != null ? payload.prompt : "";
        lastHyMotionDuration = payload != null ? payload.duration_seconds : 0f;
        lastHyMotionFrameCount = payload != null ? payload.frame_count : 0;
        lastHyMotionName = MotionNameFromStageDir(payload != null ? payload.motion_stage_dir : "");
        if (hyMotionLoadedNameJSON != null)
        {
            hyMotionLoadedNameJSON.val = lastHyMotionName;
        }
    }

    private string StartHYMotionPlayback(
        BridgePayload payload,
        string normalizedSmpl,
        bool smplExists,
        string normalizedProxy,
        bool proxyExists,
        string normalizedFbx,
        bool fbxExists,
        string normalizedNpz,
        bool npzExists,
        string actionName
    )
    {
        string note;
        StopHYMotionPlayback(false, false);
        hyMotionStopRequested = false;

        if (smplExists && (hyMotionSmplEnabledJSON == null || hyMotionSmplEnabledJSON.val))
        {
            ApplyHYMotionConflictGuard(payload);
            hyMotionPlaybackLoop = StartCoroutine(PlayHYMotionSmpl(normalizedSmpl, payload));
            note = "HY-Motion SMPL playback started";
            if (hyMotionLoopJSON != null && hyMotionLoopJSON.val)
            {
                note += " | loop on";
            }
            if (payload != null && !string.IsNullOrEmpty(payload.motion_voxta_debug_path))
            {
                note += " | Voxta debug copy: " + payload.motion_voxta_debug_path;
            }
            WriteStatus("playing", actionName, note);
            FireHYMotionEvent("started", payload, note);
            return note;
        }

        if (proxyExists && (hyMotionProxyEnabledJSON == null || hyMotionProxyEnabledJSON.val))
        {
            ApplyHYMotionConflictGuard(payload);
            hyMotionPlaybackLoop = StartCoroutine(PlayHYMotionProxy(normalizedProxy, payload));
            note = "HY-Motion proxy playback started";
            if (hyMotionLoopJSON != null && hyMotionLoopJSON.val)
            {
                note += " | loop on";
            }
            if (fbxExists)
            {
                note += " | FBX reference: " + FileManagerSecure.GetFileName(normalizedFbx);
            }
            WriteStatus("playing", actionName, note);
            FireHYMotionEvent("started", payload, note);
            return note;
        }

        RestoreHYMotionConflictGuard();
        if (fbxExists)
        {
            note = "HY-Motion FBX ready: " + FileManagerSecure.GetFileName(normalizedFbx);
            if (payload != null && !string.IsNullOrEmpty(payload.timeline_clip))
            {
                PlayTimelineClip(payload.timeline_clip, payload.timeline_auto_resume);
                note += " | Timeline clip requested: " + payload.timeline_clip;
            }
            else
            {
                note += " | Native playback file missing or disabled.";
            }
            WriteStatus("ready", actionName, note);
            FireHYMotionEvent("missing", payload, note);
            return note;
        }

        if (npzExists)
        {
            note = "HY-Motion NPZ ready, but native playback JSON is missing: " + FileManagerSecure.GetFileName(normalizedNpz);
            WriteStatus("warning", actionName, note);
            FireHYMotionEvent("missing", payload, note);
            return note;
        }

        note = "HY-Motion files missing or not readable by VaM bridge";
        WriteStatus("error", actionName, note);
        FireHYMotionEvent("failed", payload, note);
        return note;
    }

    private BridgePayload PayloadFromLastHYMotionReceipt()
    {
        string receiptPath = CombinePath(outboxDir, "last_hy_motion.json");
        if (!FileManagerSecure.FileExists(receiptPath))
        {
            return null;
        }

        JSONNode root = JSON.Parse(FileManagerSecure.ReadAllText(receiptPath));
        if (root == null)
        {
            return null;
        }

        BridgePayload payload = new BridgePayload();
        payload.target_atom_uid = ResolveTargetAtomUid();
        payload.motion_source = "hy_motion";
        payload.prompt = JsonString(root, "prompt");
        payload.duration_seconds = JsonFloat(root, "duration_seconds");
        payload.frame_count = JsonInt(root, "frame_count");
        payload.motion_fbx_path = JsonString(root, "fbx_path");
        payload.motion_npz_path = JsonString(root, "npz_path");
        payload.motion_smpl_path = JsonString(root, "smpl_path");
        payload.motion_proxy_path = JsonString(root, "proxy_path");
        payload.motion_timeline_clip_path = JsonString(root, "timeline_clip_path");
        payload.motion_timeline_storable_path = JsonString(root, "timeline_storable_path");
        payload.motion_stage_dir = JsonString(root, "motion_stage_dir");
        payload.motion_manifest_path = JsonString(root, "motion_manifest_path");
        payload.motion_voxta_debug_path = JsonString(root, "voxta_debug_path");
        return payload;
    }

    private BridgePayload PayloadFromMotionName(string motionName)
    {
        string safeName = string.IsNullOrEmpty(motionName) ? "" : motionName.Trim().Replace("\\", "/").Trim('/');
        if (string.IsNullOrEmpty(safeName) || safeName.Contains("/") || safeName.Contains(".."))
        {
            return null;
        }

        string stageDir = CombinePath(CombinePath(bridgeRoot, "motion"), safeName);
        BridgePayload payload = new BridgePayload();
        payload.target_atom_uid = ResolveTargetAtomUid();
        payload.motion_source = "hy_motion";
        payload.motion_stage_dir = stageDir;
        payload.motion_manifest_path = CombinePath(stageDir, "motion_manifest.json");
        payload.motion_smpl_path = CombinePath(stageDir, "motion_smpl.json");
        payload.motion_proxy_path = CombinePath(stageDir, "motion_proxy.json");
        payload.motion_timeline_clip_path = CombinePath(stageDir, "motion_timeline_clip.json");
        payload.motion_timeline_storable_path = CombinePath(stageDir, "motion_timeline_storable.json");

        string[] fbxFiles = SafeGetFiles(stageDir, "*.fbx");
        if (fbxFiles.Length > 0)
        {
            payload.motion_fbx_path = fbxFiles[0];
            payload.motion_file = fbxFiles[0];
        }
        string[] npzFiles = SafeGetFiles(stageDir, "*.npz");
        if (npzFiles.Length > 0)
        {
            payload.motion_npz_path = npzFiles[0];
        }
        if (FileManagerSecure.FileExists(payload.motion_manifest_path))
        {
            JSONNode manifest = JSON.Parse(FileManagerSecure.ReadAllText(payload.motion_manifest_path));
            if (manifest != null)
            {
                payload.prompt = JsonString(manifest, "prompt");
                payload.duration_seconds = JsonFloat(manifest, "duration_seconds");
                payload.frame_count = JsonInt(manifest, "frame_count");
            }
        }
        return payload;
    }

    private string[] SafeGetFiles(string dir, string pattern)
    {
        try
        {
            if (string.IsNullOrEmpty(dir))
            {
                return new string[0];
            }
            string[] files = FileManagerSecure.GetFiles(dir, pattern);
            Array.Sort(files, StringComparer.Ordinal);
            return files;
        }
        catch
        {
            return new string[0];
        }
    }

    private void PlayLatestHYMotion()
    {
        RebuildPaths();
        BridgePayload payload = lastHyMotionPayload;
        if (payload == null || (string.IsNullOrEmpty(lastHyMotionSmplPath) && string.IsNullOrEmpty(lastHyMotionProxyPath)))
        {
            payload = PayloadFromLastHYMotionReceipt();
        }
        if (payload == null)
        {
            WriteStatus("warning", "Play Latest HY-Motion", "No previous HY-Motion receipt found");
            FireHYMotionEvent("missing", payload, "No previous HY-Motion receipt found");
            return;
        }

        string normalizedFbx;
        string normalizedNpz;
        string normalizedSmpl;
        string normalizedProxy;
        bool fbxExists = BridgeFileExists(payload.motion_fbx_path, out normalizedFbx);
        bool npzExists = BridgeFileExists(payload.motion_npz_path, out normalizedNpz);
        bool smplExists = BridgeFileExists(payload.motion_smpl_path, out normalizedSmpl);
        bool proxyExists = BridgeFileExists(payload.motion_proxy_path, out normalizedProxy);
        RememberHYMotion(payload, normalizedSmpl, smplExists, normalizedProxy, proxyExists, normalizedFbx, fbxExists, normalizedNpz, npzExists);
        StartHYMotionPlayback(payload, normalizedSmpl, smplExists, normalizedProxy, proxyExists, normalizedFbx, fbxExists, normalizedNpz, npzExists, "Play Latest HY-Motion");
    }

    private void LoadHYMotionByName()
    {
        RebuildPaths();
        string motionName = hyMotionLoadNameJSON != null ? hyMotionLoadNameJSON.val : "";
        BridgePayload payload = PayloadFromMotionName(motionName);
        if (payload == null)
        {
            WriteStatus("warning", "Load HY-Motion By Name", "Enter a motion folder name under bridge/motion");
            FireHYMotionEvent("missing", payload, "Enter a motion folder name under bridge/motion");
            return;
        }

        string normalizedFbx;
        string normalizedNpz;
        string normalizedSmpl;
        string normalizedProxy;
        bool fbxExists = BridgeFileExists(payload.motion_fbx_path, out normalizedFbx);
        bool npzExists = BridgeFileExists(payload.motion_npz_path, out normalizedNpz);
        bool smplExists = BridgeFileExists(payload.motion_smpl_path, out normalizedSmpl);
        bool proxyExists = BridgeFileExists(payload.motion_proxy_path, out normalizedProxy);
        RememberHYMotion(payload, normalizedSmpl, smplExists, normalizedProxy, proxyExists, normalizedFbx, fbxExists, normalizedNpz, npzExists);
        StartHYMotionPlayback(payload, normalizedSmpl, smplExists, normalizedProxy, proxyExists, normalizedFbx, fbxExists, normalizedNpz, npzExists, "Load HY-Motion By Name");
    }

    private void StopHYMotionFromAction()
    {
        bool resetPose = hyMotionResetOnStopJSON == null || hyMotionResetOnStopJSON.val;
        StopHYMotionPlayback(resetPose, true);
    }

    private void ResetHYMotionPoseFromAction()
    {
        StopHYMotionPlayback(false, false);
        ResetHYMotionPoseSmooth();
    }

    private void BridgeSelfTest()
    {
        string note = BridgeVersion + " | actions: Play Latest HY-Motion, Stop HY-Motion, Reset HY-Motion Pose, Load HY-Motion By Name | events: On HY-Motion Started, On HY-Motion Finished, On HY-Motion Missing/Failed";
        AppendTrace("bridge self test " + note);
        WriteStatus("ready", "bridge_self_test", note);
    }

    private void StopHYMotionPlayback(bool resetPose, bool writeStatus)
    {
        hyMotionStopRequested = true;
        if (hyMotionPlaybackLoop != null)
        {
            StopCoroutine(hyMotionPlaybackLoop);
            hyMotionPlaybackLoop = null;
        }
        RestoreHYMotionConflictGuard();
        if (resetPose)
        {
            ResetHYMotionPoseSmooth();
        }
        if (writeStatus)
        {
            WriteStatus("ready", "Stop HY-Motion", resetPose ? "Stopped and returning to saved pose" : "Stopped");
            FireHYMotionEvent("finished", lastHyMotionPayload, resetPose ? "Stopped and returning to saved pose" : "Stopped");
        }
    }

    private float HYMotionMasterStrength()
    {
        return Mathf.Clamp(hyMotionStrengthJSON != null ? hyMotionStrengthJSON.val : 1.0f, 0.0f, 2.0f);
    }

    private float HYMotionBlendSeconds()
    {
        return Mathf.Max(0.0f, hyMotionBlendSecondsJSON != null ? hyMotionBlendSecondsJSON.val : 0.35f);
    }

    private bool HYMotionShouldLoop()
    {
        return hyMotionLoopJSON != null && hyMotionLoopJSON.val;
    }

    private bool ShouldDriveSmplIndex(int index)
    {
        if (index == 0)
        {
            return hyMotionDriveRootJSON == null || hyMotionDriveRootJSON.val;
        }
        if (index >= 1 && index <= 4)
        {
            return hyMotionDriveUpperBodyJSON == null || hyMotionDriveUpperBodyJSON.val;
        }
        if (index >= 5 && index <= 12)
        {
            return hyMotionDriveArmsJSON == null || hyMotionDriveArmsJSON.val;
        }
        return hyMotionDriveLegsJSON != null && hyMotionDriveLegsJSON.val;
    }

    private void AddControllerSnapshot(FreeControllerV3 controller)
    {
        if (controller == null)
        {
            return;
        }
        for (int i = 0; i < hyMotionPoseSnapshot.Count; i++)
        {
            if (hyMotionPoseSnapshot[i].controller == controller)
            {
                return;
            }
        }
        ControllerSnapshot snap = new ControllerSnapshot();
        snap.controller = controller;
        snap.position = controller.transform.position;
        snap.rotation = controller.transform.rotation;
        snap.positionState = controller.currentPositionState;
        snap.rotationState = controller.currentRotationState;
        hyMotionPoseSnapshot.Add(snap);
    }

    private void CaptureHYMotionPose(FreeControllerV3[] controllers)
    {
        hyMotionPoseSnapshot = new List<ControllerSnapshot>();
        if (controllers == null)
        {
            return;
        }
        for (int i = 0; i < controllers.Length; i++)
        {
            AddControllerSnapshot(controllers[i]);
        }
    }

    private void ResetHYMotionPoseSmooth()
    {
        if (hyMotionPoseSnapshot == null || hyMotionPoseSnapshot.Count == 0)
        {
            WriteStatus("ready", "Reset HY-Motion Pose", "No saved HY-Motion pose to restore");
            return;
        }
        if (hyMotionResetLoop != null)
        {
            StopCoroutine(hyMotionResetLoop);
            hyMotionResetLoop = null;
        }
        hyMotionResetLoop = StartCoroutine(ResetHYMotionPoseRoutine());
    }

    private IEnumerator ResetHYMotionPoseRoutine()
    {
        List<ControllerSnapshot> targets = new List<ControllerSnapshot>(hyMotionPoseSnapshot);
        Vector3[] startPositions = new Vector3[targets.Count];
        Quaternion[] startRotations = new Quaternion[targets.Count];
        for (int i = 0; i < targets.Count; i++)
        {
            if (targets[i].controller != null)
            {
                startPositions[i] = targets[i].controller.transform.position;
                startRotations[i] = targets[i].controller.transform.rotation;
                ArmControllerForMotion(targets[i].controller);
            }
        }

        float duration = Mathf.Max(0.05f, HYMotionBlendSeconds());
        float started = Time.realtimeSinceStartup;
        WriteStatus("playing", "Reset HY-Motion Pose", "Returning to saved pose");
        while (Time.realtimeSinceStartup - started < duration)
        {
            float t = Mathf.Clamp01((Time.realtimeSinceStartup - started) / duration);
            t = t * t * (3f - 2f * t);
            for (int i = 0; i < targets.Count; i++)
            {
                FreeControllerV3 ctrl = targets[i].controller;
                if (ctrl == null)
                {
                    continue;
                }
                ctrl.transform.position = Vector3.Lerp(startPositions[i], targets[i].position, t);
                ctrl.transform.rotation = Quaternion.Slerp(startRotations[i], targets[i].rotation, t);
            }
            yield return null;
        }

        for (int i = 0; i < targets.Count; i++)
        {
            FreeControllerV3 ctrl = targets[i].controller;
            if (ctrl == null)
            {
                continue;
            }
            ctrl.transform.position = targets[i].position;
            ctrl.transform.rotation = targets[i].rotation;
            ctrl.currentPositionState = targets[i].positionState;
            ctrl.currentRotationState = targets[i].rotationState;
        }
        hyMotionResetLoop = null;
        WriteStatus("ready", "Reset HY-Motion Pose", "Saved pose restored");
    }

    private void RememberBoolParam(JSONStorableBool param, string label)
    {
        if (param == null)
        {
            return;
        }
        for (int i = 0; i < hyMotionConflictSnapshot.Count; i++)
        {
            if (hyMotionConflictSnapshot[i].param == param)
            {
                return;
            }
        }
        BoolParamSnapshot snap = new BoolParamSnapshot();
        snap.param = param;
        snap.value = param.val;
        snap.label = label;
        hyMotionConflictSnapshot.Add(snap);
    }

    private bool TrySetBoolParam(Atom atom, string storableId, string paramName, bool value)
    {
        if (atom == null || string.IsNullOrEmpty(storableId) || string.IsNullOrEmpty(paramName))
        {
            return false;
        }
        JSONStorable storable = atom.GetStorableByID(storableId);
        if (storable == null)
        {
            return false;
        }
        JSONStorableBool param = storable.GetBoolJSONParam(paramName);
        if (param == null)
        {
            return false;
        }
        RememberBoolParam(param, storableId + "." + paramName);
        param.val = value;
        AppendTrace("HY conflict guard set " + storableId + "." + paramName + "=" + value);
        return true;
    }

    private void ApplyHYMotionConflictGuard(BridgePayload payload)
    {
        if (hyMotionConflictGuardJSON != null && !hyMotionConflictGuardJSON.val)
        {
            return;
        }

        Atom atom = ResolveTargetAtom(payload);
        if (atom == null)
        {
            return;
        }

        int changed = 0;
        changed += TrySetBoolParam(atom, "JawControl", "driveXRotationFromAudioSource", false) ? 1 : 0;
        changed += TrySetBoolParam(atom, "LipSync", "enabled", false) ? 1 : 0;

        List<string> ids = atom.GetStorableIDs();
        for (int i = 0; i < ids.Count; i++)
        {
            string id = ids[i];
            string lower = id.ToLowerInvariant();
            if (lower.Contains("vammmoan") || lower.Contains("vammoan"))
            {
                changed += TrySetBoolParam(atom, id, "Enable auto-jaw animation", false) ? 1 : 0;
            }
            if (lower.Contains("timeline") || lower.Contains("bodylanguage") || lower.Contains("cheesyfx") || lower.Contains("glance") || lower.Contains("ik"))
            {
                AppendTrace("HY conflict guard detected possible motion peer: " + id);
            }
        }
        if (changed > 0)
        {
            AppendTrace("HY conflict guard stored " + changed + " bool settings for restore");
        }
    }

    private void RestoreHYMotionConflictGuard()
    {
        if (hyMotionConflictSnapshot == null || hyMotionConflictSnapshot.Count == 0)
        {
            return;
        }
        for (int i = 0; i < hyMotionConflictSnapshot.Count; i++)
        {
            BoolParamSnapshot snap = hyMotionConflictSnapshot[i];
            if (snap != null && snap.param != null)
            {
                snap.param.val = snap.value;
                AppendTrace("HY conflict guard restored " + snap.label + "=" + snap.value);
            }
        }
        hyMotionConflictSnapshot.Clear();
    }

    private Atom ResolveTargetAtom(BridgePayload payload)
    {
        string uid = FirstNonEmpty(
            payload != null ? payload.target_atom_uid : "",
            targetAtomUidJSON != null ? targetAtomUidJSON.val : "",
            containingAtom != null ? containingAtom.uid : ""
        );
        if (!string.IsNullOrEmpty(uid) && SuperController.singleton != null)
        {
            Atom atom = SuperController.singleton.GetAtomByUid(uid);
            if (atom != null)
            {
                return atom;
            }
        }
        return containingAtom;
    }

    private FreeControllerV3 FindController(Atom atom, params string[] candidates)
    {
        if (atom == null)
        {
            return null;
        }

        for (int i = 0; i < candidates.Length; i++)
        {
            JSONStorable storable = atom.GetStorableByID(candidates[i]);
            FreeControllerV3 controller = storable as FreeControllerV3;
            if (controller != null)
            {
                return controller;
            }
        }

        List<string> ids = atom.GetStorableIDs();
        for (int i = 0; i < ids.Count; i++)
        {
            string id = ids[i];
            string lower = id.ToLowerInvariant();
            for (int c = 0; c < candidates.Length; c++)
            {
                string candidate = candidates[c].ToLowerInvariant().Replace("control", "");
                if (candidate.Length > 0 && lower.Contains(candidate) && lower.Contains("control"))
                {
                    JSONStorable storable = atom.GetStorableByID(id);
                    FreeControllerV3 controller = storable as FreeControllerV3;
                    if (controller != null)
                    {
                        return controller;
                    }
                }
            }
        }
        return null;
    }

    private string ControllerName(FreeControllerV3 controller)
    {
        return controller == null ? "missing" : controller.name;
    }

    private Vector3 JsonVec3(JSONNode node, float strength)
    {
        if (node == null)
        {
            return Vector3.zero;
        }
        return new Vector3(node[0].AsFloat, node[1].AsFloat, node[2].AsFloat) * strength;
    }

    private Vector3 FrameOffset(JSONNode frame, string key, float strength)
    {
        if (frame == null)
        {
            return Vector3.zero;
        }
        return JsonVec3(frame[key], strength);
    }

    private void ApplyProxyOffset(FreeControllerV3 controller, Vector3 start, Quaternion basis, Vector3 offset)
    {
        if (controller == null)
        {
            return;
        }
        controller.transform.position = start + (basis * offset);
    }

    private FreeControllerV3[] ResolveSmplControllers(Atom atom, string[] controllerIds)
    {
        FreeControllerV3[] result = new FreeControllerV3[controllerIds.Length];
        for (int i = 0; i < controllerIds.Length; i++)
        {
            result[i] = FindController(atom, controllerIds[i]);
        }
        return result;
    }

    private void ArmControllerForMotion(FreeControllerV3 controller)
    {
        if (controller == null)
        {
            return;
        }
        controller.jointRotationDriveXTarget = 0f;
        controller.jointRotationDriveYTarget = 0f;
        controller.jointRotationDriveZTarget = 0f;
        controller.currentPositionState = FreeControllerV3.PositionState.On;
        controller.currentRotationState = FreeControllerV3.RotationState.On;
    }

    private Quaternion AxisAngleToUnityQuaternion(JSONNode values, int offset, float strength)
    {
        if (values == null || values.Count <= offset + 2)
        {
            return Quaternion.identity;
        }
        float x = values[offset].AsFloat;
        float y = values[offset + 1].AsFloat;
        float z = values[offset + 2].AsFloat;
        Vector3 axis = new Vector3(-x, y, z);
        float angle = -axis.magnitude * Mathf.Rad2Deg;
        if (Mathf.Abs(angle) < 0.0001f)
        {
            return Quaternion.identity;
        }
        return Quaternion.AngleAxis(angle * strength, axis.normalized);
    }

    private Quaternion SmplJointRotation(JSONNode poses, JSONNode rh, int frameIndex, int jointIndex, float strength)
    {
        if (jointIndex == 0 && rh != null && rh.Count > frameIndex * 3 + 2)
        {
            return AxisAngleToUnityQuaternion(rh, frameIndex * 3, strength);
        }
        return AxisAngleToUnityQuaternion(poses, frameIndex * 156 + jointIndex * 3, strength);
    }

    private Vector3 SmplRootTranslation(JSONNode trans, int frameIndex)
    {
        int offset = frameIndex * 3;
        if (trans == null || trans.Count <= offset + 2)
        {
            return Vector3.zero;
        }
        return new Vector3(-trans[offset].AsFloat, trans[offset + 1].AsFloat, trans[offset + 2].AsFloat);
    }

    private IEnumerator PlayHYMotionSmpl(string smplPath, BridgePayload payload)
    {
        JSONNode root;
        try
        {
            root = JSON.Parse(FileManagerSecure.ReadAllText(smplPath));
        }
        catch (Exception exc)
        {
            WriteStatus("error", "hy_motion_smpl", "Failed to read SMPL JSON: " + exc.Message);
            FireHYMotionEvent("failed", payload, "Failed to read SMPL JSON: " + exc.Message);
            yield break;
        }

        int frameCount = root["frameCount"].AsInt;
        int fps = root["fps"].AsInt;
        if (frameCount <= 0)
        {
            WriteStatus("error", "hy_motion_smpl", "SMPL JSON has no frames");
            FireHYMotionEvent("failed", payload, "SMPL JSON has no frames");
            yield break;
        }
        if (fps <= 0)
        {
            fps = 30;
        }

        JSONNode poses = root["poses"];
        JSONNode trans = root["trans"];
        JSONNode rh = root["Rh"];
        Atom atom = ResolveTargetAtom(payload);
        string[] ids = new string[]
        {
            "hipControl", "abdomenControl", "chestControl", "neckControl", "headControl",
            "lShoulderControl", "rShoulderControl", "lArmControl", "rArmControl",
            "lElbowControl", "rElbowControl", "lHandControl", "rHandControl",
            "lThighControl", "rThighControl", "lKneeControl", "rKneeControl",
            "lFootControl", "rFootControl"
        };
        int[] joints = new int[]
        {
            0, 3, 9, 12, 15,
            13, 14, 16, 17,
            18, 19, 20, 21,
            1, 2, 4, 5,
            7, 8
        };
        FreeControllerV3[] controllers = ResolveSmplControllers(atom, ids);
        Quaternion[] startRotations = new Quaternion[ids.Length];
        Vector3[] startPositions = new Vector3[ids.Length];
        CaptureHYMotionPose(controllers);
        for (int i = 0; i < controllers.Length; i++)
        {
            if (controllers[i] == null)
            {
                continue;
            }
            startRotations[i] = controllers[i].transform.rotation;
            startPositions[i] = controllers[i].transform.position;
            ArmControllerForMotion(controllers[i]);
        }

        AppendTrace(
            "HY SMPL controllers atom=" + (atom != null ? atom.uid : "missing") +
            " hip=" + ControllerName(controllers[0]) +
            " chest=" + ControllerName(controllers[2]) +
            " head=" + ControllerName(controllers[4]) +
            " leftHand=" + ControllerName(controllers[11]) +
            " rightHand=" + ControllerName(controllers[12])
        );

        float duration = frameCount / Mathf.Max(1f, (float)fps);
        float started = Time.realtimeSinceStartup;
        float blendSeconds = HYMotionBlendSeconds();
        Vector3 firstRoot = SmplRootTranslation(trans, 0);

        WriteStatus("playing", "hy_motion_smpl", "Playing HY-Motion SMPL on " + (atom != null ? atom.uid : "target atom"));
        while (!hyMotionStopRequested)
        {
            float elapsed = Time.realtimeSinceStartup - started;
            bool shouldLoop = HYMotionShouldLoop();
            if (!shouldLoop && elapsed > duration)
            {
                break;
            }
            float localElapsed = shouldLoop ? Mathf.Repeat(elapsed, Mathf.Max(0.01f, duration)) : Mathf.Min(elapsed, duration);
            float frame = Mathf.Clamp(localElapsed * fps, 0f, Mathf.Max(0, frameCount - 1));
            int frameA = Mathf.Clamp(Mathf.FloorToInt(frame), 0, frameCount - 1);
            int frameB = Mathf.Clamp(frameA + 1, 0, frameCount - 1);
            float frameBlend = Mathf.Clamp01(frame - frameA);
            float fade = blendSeconds <= 0.001f ? 1f : Mathf.Clamp01(elapsed / blendSeconds);
            fade = fade * fade * (3f - 2f * fade);
            float masterStrength = HYMotionMasterStrength();
            float rotStrength = (hyMotionRotationStrengthJSON != null ? hyMotionRotationStrengthJSON.val : 1.0f) * masterStrength;
            float moveStrength = (hyMotionProxyStrengthJSON != null ? hyMotionProxyStrengthJSON.val : 1.0f) * masterStrength;
            for (int i = 0; i < controllers.Length; i++)
            {
                FreeControllerV3 ctrl = controllers[i];
                if (ctrl == null || !ShouldDriveSmplIndex(i))
                {
                    continue;
                }
                Quaternion qA = SmplJointRotation(poses, rh, frameA, joints[i], rotStrength);
                Quaternion qB = SmplJointRotation(poses, rh, frameB, joints[i], rotStrength);
                Quaternion q = Quaternion.Slerp(qA, qB, frameBlend);
                Quaternion targetRotation = startRotations[i] * q;
                ctrl.transform.rotation = Quaternion.Slerp(startRotations[i], targetRotation, fade);
                if (i == 0)
                {
                    Vector3 rootA = SmplRootTranslation(trans, frameA);
                    Vector3 rootB = SmplRootTranslation(trans, frameB);
                    Vector3 delta = Vector3.Lerp(rootA, rootB, frameBlend) - firstRoot;
                    delta.y = 0f;
                    Vector3 targetPosition = startPositions[i] + delta * moveStrength;
                    ctrl.transform.position = Vector3.Lerp(startPositions[i], targetPosition, fade);
                }
            }
            yield return null;
        }

        hyMotionPlaybackLoop = null;
        RestoreHYMotionConflictGuard();
        WriteStatus("ready", "hy_motion_smpl", "HY-Motion SMPL playback finished");
        FireHYMotionEvent("finished", payload, "HY-Motion SMPL playback finished");
    }

    private IEnumerator PlayHYMotionProxy(string proxyPath, BridgePayload payload)
    {
        JSONNode root;
        try
        {
            root = JSON.Parse(FileManagerSecure.ReadAllText(proxyPath));
        }
        catch (Exception exc)
        {
            WriteStatus("error", "hy_motion_proxy", "Failed to read proxy: " + exc.Message);
            FireHYMotionEvent("failed", payload, "Failed to read proxy: " + exc.Message);
            yield break;
        }

        JSONNode frames = root["frames"];
        int frameCount = frames != null ? frames.Count : 0;
        if (frameCount <= 0)
        {
            WriteStatus("error", "hy_motion_proxy", "Proxy has no frames");
            FireHYMotionEvent("failed", payload, "Proxy has no frames");
            yield break;
        }

        Atom atom = ResolveTargetAtom(payload);
        FreeControllerV3 hip = FindController(atom, "hipControl", "pelvisControl", "abdomenControl");
        FreeControllerV3 chest = FindController(atom, "chestControl", "abdomen2Control", "abdomenControl");
        FreeControllerV3 head = FindController(atom, "headControl", "neckControl");
        FreeControllerV3 leftHand = FindController(atom, "lHandControl", "leftHandControl", "lArmControl", "leftArmControl");
        FreeControllerV3 rightHand = FindController(atom, "rHandControl", "rightHandControl", "rArmControl", "rightArmControl");

        AppendTrace(
            "HY proxy controllers atom=" + (atom != null ? atom.uid : "missing") +
            " hip=" + ControllerName(hip) +
            " chest=" + ControllerName(chest) +
            " head=" + ControllerName(head) +
            " leftHand=" + ControllerName(leftHand) +
            " rightHand=" + ControllerName(rightHand)
        );

        Vector3 hipStart = hip != null ? hip.transform.position : Vector3.zero;
        Vector3 chestStart = chest != null ? chest.transform.position : Vector3.zero;
        Vector3 headStart = head != null ? head.transform.position : Vector3.zero;
        Vector3 leftStart = leftHand != null ? leftHand.transform.position : Vector3.zero;
        Vector3 rightStart = rightHand != null ? rightHand.transform.position : Vector3.zero;
        Quaternion basis = hip != null ? hip.transform.rotation : (atom != null ? atom.transform.rotation : Quaternion.identity);
        CaptureHYMotionPose(new FreeControllerV3[] { hip, chest, head, leftHand, rightHand });
        ArmControllerForMotion(hip);
        ArmControllerForMotion(chest);
        ArmControllerForMotion(head);
        ArmControllerForMotion(leftHand);
        ArmControllerForMotion(rightHand);

        float duration = root["duration_seconds"].AsFloat;
        if (duration <= 0.01f)
        {
            duration = payload != null && payload.duration_seconds > 0.01f ? payload.duration_seconds : frameCount / 30.0f;
        }
        float started = Time.realtimeSinceStartup;
        float blendSeconds = HYMotionBlendSeconds();

        WriteStatus("playing", "hy_motion_proxy", "Playing HY-Motion proxy on " + (atom != null ? atom.uid : "target atom"));
        while (!hyMotionStopRequested)
        {
            float elapsed = Time.realtimeSinceStartup - started;
            bool shouldLoop = HYMotionShouldLoop();
            if (!shouldLoop && elapsed > duration)
            {
                break;
            }
            float localElapsed = shouldLoop ? Mathf.Repeat(elapsed, Mathf.Max(0.01f, duration)) : Mathf.Min(elapsed, duration);
            float frameFloat = Mathf.Clamp((localElapsed / Mathf.Max(0.01f, duration)) * (frameCount - 1), 0f, frameCount - 1);
            int frameA = Mathf.Clamp(Mathf.FloorToInt(frameFloat), 0, frameCount - 1);
            int frameB = Mathf.Clamp(frameA + 1, 0, frameCount - 1);
            float frameBlend = Mathf.Clamp01(frameFloat - frameA);
            float fade = blendSeconds <= 0.001f ? 1f : Mathf.Clamp01(elapsed / blendSeconds);
            fade = fade * fade * (3f - 2f * fade);
            JSONNode a = frames[frameA];
            JSONNode b = frames[frameB];
            float strength = (hyMotionProxyStrengthJSON != null ? hyMotionProxyStrengthJSON.val : 1.0f) * HYMotionMasterStrength();

            if (hyMotionDriveRootJSON == null || hyMotionDriveRootJSON.val)
            {
                ApplyProxyOffset(hip, hipStart, basis, Vector3.Lerp(FrameOffset(a, "hip", strength), FrameOffset(b, "hip", strength), frameBlend) * fade);
            }
            if (hyMotionDriveUpperBodyJSON == null || hyMotionDriveUpperBodyJSON.val)
            {
                ApplyProxyOffset(chest, chestStart, basis, Vector3.Lerp(FrameOffset(a, "chest", strength), FrameOffset(b, "chest", strength), frameBlend) * fade);
                ApplyProxyOffset(head, headStart, basis, Vector3.Lerp(FrameOffset(a, "head", strength), FrameOffset(b, "head", strength), frameBlend) * fade);
            }
            if (hyMotionDriveArmsJSON == null || hyMotionDriveArmsJSON.val)
            {
                ApplyProxyOffset(leftHand, leftStart, basis, Vector3.Lerp(FrameOffset(a, "leftHand", strength), FrameOffset(b, "leftHand", strength), frameBlend) * fade);
                ApplyProxyOffset(rightHand, rightStart, basis, Vector3.Lerp(FrameOffset(a, "rightHand", strength), FrameOffset(b, "rightHand", strength), frameBlend) * fade);
            }
            yield return null;
        }

        hyMotionPlaybackLoop = null;
        RestoreHYMotionConflictGuard();
        WriteStatus("ready", "hy_motion_proxy", "HY-Motion proxy playback finished");
        FireHYMotionEvent("finished", payload, "HY-Motion proxy playback finished");
    }

    private string ResolveTargetAtomUid()
        {
            if (targetAtomUidJSON != null && !string.IsNullOrEmpty(targetAtomUidJSON.val))
            {
                return targetAtomUidJSON.val.Trim();
            }
            return containingAtom != null ? containingAtom.uid : "";
        }

    private void ApplyExpressionPreset(string presetName, string fallbackEmotion)
        {
            currentEmotion = !string.IsNullOrEmpty(fallbackEmotion) ? fallbackEmotion : currentEmotion;

            // TODO:
            // Replace this with your preferred expression system.
            //
            // Options:
            // - map preset names to morph bundles
            // - call actions on an expression router plugin
            // - write JSONStorableFloat values for DAZ morphs
            //
            // Keep this method scene-specific rather than over-generalizing it.
            string resolved = !string.IsNullOrEmpty(presetName) ? presetName : currentEmotion;
            WriteStatus("ready", "set_emotion", "Expression -> " + resolved);
        }

    private void SetSpeaking(bool speaking)
    {
        currentSpeaking = speaking;
        AppendTrace("SetSpeaking " + speaking);

            // TODO:
            // Hook this into jaw-open / talk-idle / lip-sync state if you have a preferred plugin.
        WriteStatus("ready", "set_speaking", speaking ? "Speaking on" : "Speaking off");
    }

    private void ArmSpeakingWindow(float durationSeconds)
    {
        AppendTrace("ArmSpeakingWindow duration=" + durationSeconds);
        if (speakingWindowLoop != null)
        {
            StopCoroutine(speakingWindowLoop);
            speakingWindowLoop = null;
        }

        if (durationSeconds > 0.01f)
        {
            speakingWindowLoop = StartCoroutine(SpeakingWindowRoutine(durationSeconds));
        }
    }

    private IEnumerator SpeakingWindowRoutine(float durationSeconds)
    {
        AppendTrace("SpeakingWindowRoutine start duration=" + durationSeconds);
        yield return new WaitForSeconds(Mathf.Max(0.01f, durationSeconds));
        AppendTrace("SpeakingWindowRoutine finish");
        SetSpeaking(false);
        speakingWindowLoop = null;
    }

    private AudioSourceControl ResolveHeadAudioSource()
    {
        if (headAudioSource == null && containingAtom != null)
        {
            headAudioSource = containingAtom.GetStorableByID("HeadAudioSource") as AudioSourceControl;
        }
        return headAudioSource;
    }

    private NamedAudioClip LoadExternalAudioClip(string path, out URLAudioClip queuedClip)
    {
        queuedClip = null;
        if (string.IsNullOrEmpty(path) || SuperController.singleton == null || URLAudioClipManager.singleton == null)
        {
            return null;
        }

        string loadPath = SuperController.singleton.NormalizeLoadPath(path);
        NamedAudioClip existing = URLAudioClipManager.singleton.GetClip(loadPath);
        if (existing != null)
        {
            return existing;
        }

        string mediaPath = SuperController.singleton.NormalizeMediaPath(path);
        existing = URLAudioClipManager.singleton.GetClip(mediaPath);
        if (existing != null)
        {
            return existing;
        }

        URLAudioClipManager.singleton.QueueFilePath(path);
        existing = URLAudioClipManager.singleton.GetClip(loadPath)
            ?? URLAudioClipManager.singleton.GetClip(mediaPath)
            ?? URLAudioClipManager.singleton.GetClip(path);
        if (existing != null)
        {
            return existing;
        }

        queuedClip = URLAudioClipManager.singleton.QueueClip(mediaPath, string.Empty, false);
        if (queuedClip == null)
        {
            return null;
        }

        return URLAudioClipManager.singleton.GetClip(queuedClip.uid)
            ?? URLAudioClipManager.singleton.GetClip(loadPath)
            ?? URLAudioClipManager.singleton.GetClip(mediaPath)
            ?? URLAudioClipManager.singleton.GetClip(path);
    }

    private bool IsAudioClipReady(NamedAudioClip clip)
    {
        return clip != null && clip.clipToPlay != null;
    }

    private void PlayHeadAudio(string absoluteAudioPath, float expectedDurationSeconds)
    {
        if (string.IsNullOrEmpty(absoluteAudioPath))
        {
            AppendTrace("PlayHeadAudio skipped: empty path");
            return;
        }

        string normalized = FileManagerSecure.NormalizePath(absoluteAudioPath.Replace("\\", "/"));
        AppendTrace("PlayHeadAudio normalized=" + normalized);
        if (!FileManagerSecure.FileExists(normalized))
        {
            AppendTrace("PlayHeadAudio missing file");
            WriteStatus("error", "play_audio", "Missing file: " + normalized);
            return;
        }

        if (audioPlaybackLoop != null)
        {
            StopCoroutine(audioPlaybackLoop);
            audioPlaybackLoop = null;
        }

        audioPlaybackLoop = StartCoroutine(PlayHeadAudioRoutine(normalized, expectedDurationSeconds));
    }

    private IEnumerator PlayHeadAudioRoutine(string normalizedPath, float expectedDurationSeconds)
    {
        AppendTrace("PlayHeadAudioRoutine start path=" + normalizedPath + " duration=" + expectedDurationSeconds);
        AudioSourceControl source = ResolveHeadAudioSource();
        if (source == null)
        {
            AppendTrace("PlayHeadAudioRoutine source=null");
            WriteStatus("error", "play_audio", "HeadAudioSource not found");
            yield break;
        }
        AppendTrace("PlayHeadAudioRoutine source ok volume=" + source.volume);

        WriteStatus("ready", "play_audio", "Loading " + FileManagerSecure.GetFileName(normalizedPath));

        URLAudioClip queuedClip;
        NamedAudioClip clip = LoadExternalAudioClip(normalizedPath, out queuedClip);
        AppendTrace("LoadExternalAudioClip initial clip=" + (clip != null) + " queued=" + (queuedClip != null));
        float deadline = Time.realtimeSinceStartup + 5.0f;
        while (!IsAudioClipReady(clip) && Time.realtimeSinceStartup < deadline)
        {
            yield return null;
            if (URLAudioClipManager.singleton == null)
            {
                continue;
            }
            if (queuedClip != null)
            {
                clip = URLAudioClipManager.singleton.GetClip(queuedClip.uid);
            }
            if (clip == null && SuperController.singleton != null)
            {
                string loadPath = SuperController.singleton.NormalizeLoadPath(normalizedPath);
                string mediaPath = SuperController.singleton.NormalizeMediaPath(normalizedPath);
                clip = URLAudioClipManager.singleton.GetClip(loadPath)
                    ?? URLAudioClipManager.singleton.GetClip(mediaPath)
                    ?? URLAudioClipManager.singleton.GetClip(normalizedPath);
            }
        }

        if (!IsAudioClipReady(clip))
        {
            AppendTrace("PlayHeadAudioRoutine clip not ready");
            string detail = clip == null ? "Could not load clip: " : "Clip loaded without audio payload: ";
            WriteStatus("error", "play_audio", detail + normalizedPath);
            audioPlaybackLoop = null;
            yield break;
        }
        AppendTrace("PlayHeadAudioRoutine clip ready");

        source.StopAndClearQueue();
        source.PlayNowClearQueue(clip);
        yield return null;

        bool isPlaying = source.audioSource != null && source.audioSource.isPlaying;
        string clipName = FileManagerSecure.GetFileName(normalizedPath);
        if (!isPlaying && source.audioSource != null)
        {
            AppendTrace("PlayNowClearQueue did not start; trying raw AudioSource");
            source.audioSource.Stop();
            source.audioSource.clip = clip.clipToPlay;
            source.audioSource.loop = false;
            source.audioSource.Play();
            yield return null;
            isPlaying = source.audioSource.isPlaying;
        }
        AppendTrace("PlayHeadAudioRoutine isPlaying=" + isPlaying);

        if (isPlaying)
        {
            WriteStatus("playing", "play_audio", clipName + " | volume=" + source.volume.ToString("0.00"));
        }
        else
        {
            WriteStatus("error", "play_audio", "Playback did not start: " + clipName + " | volume=" + source.volume.ToString("0.00"));
            audioPlaybackLoop = null;
            yield break;
        }

        if (expectedDurationSeconds > 0.01f)
        {
            ArmSpeakingWindow(expectedDurationSeconds);
        }
        audioPlaybackLoop = null;
    }

    private void AppendTrace(string note)
    {
        try
        {
            if (string.IsNullOrEmpty(tracePath))
            {
                return;
            }

            string line = DateTime.Now.ToString("HH:mm:ss.fff") + " | " + note + "\n";
            string existing = "";
            if (FileManagerSecure.FileExists(tracePath))
            {
                existing = FileManagerSecure.ReadAllText(tracePath);
            }
            FileManagerSecure.WriteAllText(tracePath, existing + line);
        }
        catch
        {
        }
    }

    private void PlayTimelineClip(string clipName, bool autoResume)
        {
            if (string.IsNullOrEmpty(clipName))
            {
                return;
            }

            // TODO:
            // Wire this to Timeline or your motion plugin on the same Person atom.
            // A common pattern is:
            // - stop follow
            // - trigger a named Timeline clip
            // - let Timeline call back into your follow plugin when the clip ends
            WriteStatus("ready", "timeline_clip", clipName + (autoResume ? " (resume)" : ""));
        }

    private void SetFollowState(bool enabled)
        {
            // TODO:
            // Forward this to your companion follow / self-walk plugin if present.
            WriteStatus("ready", "follow_state", enabled ? "Follow on" : "Follow off");
        }

    private void WriteStatus(string state, string lastAction, string note)
        {
            try
            {
                BridgeStatus payload = new BridgeStatus
                {
                    state = state,
                    lastAction = lastAction,
                    lastEmotion = currentEmotion,
                    speaking = currentSpeaking,
                    targetAtomUid = ResolveTargetAtomUid(),
                    note = note,
                    bridgeVersion = BridgeVersion,
                    updatedAt = (double)Time.realtimeSinceStartup
                };

                string json = JsonUtility.ToJson(payload, true);
                FileManagerSecure.WriteAllText(statusPath, json);
                if (statusJSON != null)
                {
                    statusJSON.val = state + " | " + lastAction + " | " + note;
                }
            }
            catch (Exception exc)
            {
                SuperController.LogError("[NeuralCompanionBridge] Status write failed: " + exc);
            }
        }

    private void OnDestroy()
    {
        if (audioPlaybackLoop != null)
        {
            StopCoroutine(audioPlaybackLoop);
            audioPlaybackLoop = null;
        }
        if (speakingWindowLoop != null)
        {
            StopCoroutine(speakingWindowLoop);
            speakingWindowLoop = null;
        }
        if (hyMotionPlaybackLoop != null)
        {
            StopCoroutine(hyMotionPlaybackLoop);
            hyMotionPlaybackLoop = null;
        }
        if (hyMotionResetLoop != null)
        {
            StopCoroutine(hyMotionResetLoop);
            hyMotionResetLoop = null;
        }
        RestoreHYMotionConflictGuard();
        if (pollLoop != null)
        {
            StopCoroutine(pollLoop);
            pollLoop = null;
        }
        if (SuperController.singleton != null)
        {
            SuperController.singleton.onAtomUIDRenameHandlers -= OnAtomRename;
        }
    }
}

public static class NCBridgeVamAssets
{
    public static RectTransform TriggerActionsPrefab;
    public static RectTransform TriggerActionMiniPrefab;
    public static RectTransform TriggerActionDiscretePrefab;

    public static IEnumerator LoadUIAssets()
    {
        if (TriggerActionsPrefab != null && TriggerActionMiniPrefab != null && TriggerActionDiscretePrefab != null)
        {
            yield break;
        }
        foreach (object x in LoadUIAsset("z_ui2", "TriggerActionsPanel", delegate(RectTransform prefab) { TriggerActionsPrefab = prefab; })) yield return x;
        foreach (object x in LoadUIAsset("z_ui2", "TriggerActionMiniPanel", delegate(RectTransform prefab) { TriggerActionMiniPrefab = prefab; })) yield return x;
        foreach (object x in LoadUIAsset("z_ui2", "TriggerActionDiscretePanel", delegate(RectTransform prefab) { TriggerActionDiscretePrefab = prefab; })) yield return x;
    }

    private static IEnumerable LoadUIAsset(string bundle, string asset, Action<RectTransform> callback)
    {
        AssetBundleLoadAssetOperation request = AssetBundleManager.LoadAssetAsync(bundle, asset, typeof(GameObject));
        if (request == null)
        {
            SuperController.LogError("[NeuralCompanionBridge] Request for " + asset + " in " + bundle + " failed");
            yield break;
        }
        yield return request;
        GameObject go = request.GetAsset<GameObject>();
        if (go == null)
        {
            SuperController.LogError("[NeuralCompanionBridge] Failed to load " + asset);
            yield break;
        }
        RectTransform prefab = go.GetComponent<RectTransform>();
        if (prefab == null)
        {
            SuperController.LogError("[NeuralCompanionBridge] Loaded " + asset + " without RectTransform");
            yield break;
        }
        callback(prefab);
    }
}

public class NCBridgeSimpleTrigger : TriggerHandler
{
    private readonly string startName;
    private readonly string stopName;
    public Trigger Trigger { get; private set; }

    public NCBridgeSimpleTrigger(string startName, string stopName)
    {
        this.startName = startName;
        this.stopName = stopName;
        Trigger = new Trigger();
        Trigger.handler = this;
    }

    public void RemoveTrigger(Trigger trigger)
    {
    }

    public void DuplicateTrigger(Trigger trigger)
    {
    }

    public RectTransform CreateTriggerActionsUI()
    {
        if (NCBridgeVamAssets.TriggerActionsPrefab == null)
        {
            return null;
        }
        RectTransform rt = Object.Instantiate(NCBridgeVamAssets.TriggerActionsPrefab);
        Transform content = rt.Find("Content");
        if (content != null)
        {
            Transform transitionTab = content.Find("Tab2");
            if (transitionTab != null)
            {
                transitionTab.parent = null;
                Object.Destroy(transitionTab.gameObject);
            }
            Transform startTab = content.Find("Tab1");
            if (startTab != null)
            {
                Text text = startTab.GetComponentInChildren<Text>();
                if (text != null)
                {
                    text.text = startName;
                }
            }
            Transform endTab = content.Find("Tab3");
            if (endTab != null)
            {
                if (!string.IsNullOrEmpty(stopName))
                {
                    RectTransform endRect = endTab.GetComponent<RectTransform>();
                    if (endRect != null)
                    {
                        endRect.offsetMin = new Vector2(264, endRect.offsetMin.y);
                        endRect.offsetMax = new Vector2(560, endRect.offsetMax.y);
                    }
                    Text text = endTab.GetComponentInChildren<Text>();
                    if (text != null)
                    {
                        text.text = stopName;
                    }
                }
                else
                {
                    endTab.gameObject.SetActive(false);
                }
            }
        }
        return rt;
    }

    public RectTransform CreateTriggerActionMiniUI()
    {
        return NCBridgeVamAssets.TriggerActionMiniPrefab != null ? Object.Instantiate(NCBridgeVamAssets.TriggerActionMiniPrefab) : null;
    }

    public RectTransform CreateTriggerActionDiscreteUI()
    {
        return NCBridgeVamAssets.TriggerActionDiscretePrefab != null ? Object.Instantiate(NCBridgeVamAssets.TriggerActionDiscretePrefab) : null;
    }

    public RectTransform CreateTriggerActionTransitionUI()
    {
        return null;
    }

    public void RemoveTriggerActionUI(RectTransform rt)
    {
        if (rt != null)
        {
            Object.Destroy(rt.gameObject);
        }
    }

    public void OnAtomRename()
    {
        if (Trigger != null)
        {
            Trigger.SyncAtomNames();
        }
    }

    public void Toggle()
    {
        try
        {
            if (Trigger == null)
            {
                return;
            }
            Trigger.active = true;
            Trigger.active = false;
        }
        catch (Exception exc)
        {
            SuperController.LogError("[NeuralCompanionBridge] Error while activating trigger: " + exc);
        }
    }
}
