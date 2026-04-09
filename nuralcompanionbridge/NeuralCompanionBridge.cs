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
using UnityEngine;
using MVR.FileManagementSecure;
using SimpleJSON;

public class NeuralCompanionBridge : MVRScript
{
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
        public double updatedAt;
    }

    private JSONStorableString bridgeRootJSON;
    private JSONStorableBool pollingEnabledJSON;
    private JSONStorableString targetAtomUidJSON;
    private JSONStorableString statusJSON;

    private string bridgeRoot;
    private string inboxDir;
    private string outboxDir;
    private string statusPath;
    private string tracePath;
    private Coroutine pollLoop;
    private Coroutine audioPlaybackLoop;
    private Coroutine speakingWindowLoop;
    private AudioSourceControl headAudioSource;

    private string currentEmotion = "neutral";
    private bool currentSpeaking = false;

    public override void Init()
    {
        try
        {
            bridgeRootJSON = new JSONStorableString("Bridge Root", "Custom/PluginData/NeuralCompanionBridge");
            pollingEnabledJSON = new JSONStorableBool("Polling Enabled", true);
            targetAtomUidJSON = new JSONStorableString("Target Atom UID", containingAtom != null ? containingAtom.uid : "");
            statusJSON = new JSONStorableString("Bridge Status", "Idle");
            statusJSON.isStorable = false;
            statusJSON.isRestorable = false;

            RegisterString(bridgeRootJSON);
            RegisterBool(pollingEnabledJSON);
            RegisterString(targetAtomUidJSON);
            RegisterString(statusJSON);

            CreateTextField(bridgeRootJSON);
            CreateToggle(pollingEnabledJSON);
            CreateTextField(targetAtomUidJSON);
            CreateTextField(statusJSON);

            RebuildPaths();
            WriteStatus("ready", "init", "Bridge initialized");

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

        FileManagerSecure.CreateDirectory(bridgeRoot);
        FileManagerSecure.CreateDirectory(inboxDir);
        FileManagerSecure.CreateDirectory(outboxDir);
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
            }
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
        if (pollLoop != null)
        {
            StopCoroutine(pollLoop);
            pollLoop = null;
        }
    }
}
