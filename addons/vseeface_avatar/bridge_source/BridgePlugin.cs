using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace NC.VSeeFaceBridge
{
    // Added AFTER the existing driver. Samples reach its analyzer before this final filter silences them.
    public sealed class SilentOutput : MonoBehaviour
    {
        public volatile bool Muted;
        public AudioProbe Probe;
        private void OnAudioFilterRead(float[] data, int channels)
        {
            if (Probe != null) Probe.Silencer(data);
            if (Muted) Array.Clear(data, 0, data.Length);
        }
    }

    [BepInPlugin("nc.vseeface.speech.prototype", "NC VSeeFace speech bridge", "0.2.0")]
    public sealed class BridgePlugin : BaseUnityPlugin
    {
        internal static AudioPlayer ControlledPlayer;
        internal static OpenSeeVRMDriver ControlledDriver;
        private static BridgePlugin _instance;
        private Harmony _patches;
        private readonly StatusHeartbeat _status = new StatusHeartbeat();
        private ConfigEntry<string> _folder;
        private ConfigEntry<float> _maxAge;
        private ConfigEntry<float> _tolerance;
        private ConfigEntry<bool> _diagnostics;
        private ConfigEntry<float> _diagnosticInterval;
        private ConfigEntry<bool> _preserveVmcEmotions;
        private OpenSeeVRMDriver _emotionDriver;
        private Dictionary<VRM.BlendShapeKey,float> _emotionValues;
        private double _nextEmotionDiagnostic;
        private bool _emotionError;
        private AudioProbe _probe;
        private double _nextDiagnostic;
        private long _cycle;
        private string _directory;
        private AudioSource _source;
        private SilentOutput _silencer;
        private string _requested = "";
        private string _client = "";
        private long _revision;
        private bool _loading;
        private bool _paused;
        private bool _atEnd;
        private AudioClip _ownedClip;
        private bool _oldLoop;
        private bool _hadError;
        private BridgeState _lastState;
        private static readonly BindingFlags Hidden = BindingFlags.Instance | BindingFlags.NonPublic;
        private static readonly FieldInfo Playing = typeof(AudioPlayer).GetField("playing", Hidden);
        private static readonly FieldInfo Frame = typeof(OpenSeeVRMDriver).GetField("visemeData", Hidden);
        private static readonly FieldInfo Context = typeof(OpenSeeVRMDriver).GetField("context", Hidden);
        private static readonly FieldInfo Partial = typeof(OpenSeeVRMDriver).GetField("partialAudio", Hidden);
        private static readonly FieldInfo PartialPos = typeof(OpenSeeVRMDriver).GetField("partialPos", Hidden);
        private static readonly FieldInfo IsCanned = typeof(OpenSeeVRMDriver).GetField("isCanned", Hidden);
        private static readonly FieldInfo ExpressionAllows = typeof(OpenSeeVRMDriver).GetField("currentExpressionEnableVisemes", Hidden);
        private static readonly FieldInfo ExpressionFactor = typeof(OpenSeeVRMDriver).GetField("currentExpressionVisemeFactor", Hidden);
        private static readonly FieldInfo Expression = typeof(OpenSeeVRMDriver).GetField("currentExpression", Hidden);
        private static readonly FieldInfo ReceivedBlendValues = typeof(EVMC4U.ExternalReceiver).GetField("BlendShapeToValueDictionary", Hidden);

        private static double Now()
        {
            return (DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds;
        }

        private void Awake()
        {
            _folder = Config.Bind("Bridge", "SharedDirectory", Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "NeuralCompanion", "VSeeFaceBridgePrototype"), "Must match NC_VSEEFACE_BRIDGE_DIR in NC.");
            _maxAge = Config.Bind("Bridge", "MaxClockAgeSeconds", 2.0f,
                "Fail closed if NC clock updates stop. Must be greater than zero. No audio continues indefinitely after NC exits.");
            _tolerance = Config.Bind("Bridge", "SeekToleranceSeconds", 0.08f,
                "Seek the silent source when it differs from NC's audio clock by more than this amount.");
            _diagnostics = Config.Bind("Diagnostics", "Enabled", true,
                "Record sample peaks, visemes and lifecycle flags; no speech text or audio samples are saved.");
            _diagnosticInterval = Config.Bind("Diagnostics", "IntervalSeconds", 1.0f,
                "Write a diagnostic sample at this interval while NC owns playback.");
            _preserveVmcEmotions = Config.Bind("Bridge", "PreserveVmcEmotions", true,
                "Keep incoming VMC emotion presets when Track blendshapes disables native VMC blendshape reception. Vowels, blinks and other tracked shapes stay local.");
            if (_maxAge.Value <= 0 || _tolerance.Value < 0 || _diagnosticInterval.Value <= 0)
                throw new InvalidOperationException("Bridge clock settings are invalid.");
            _directory = Path.GetFullPath(_folder.Value);
            Directory.CreateDirectory(_directory);
            if (Playing == null || Frame == null || Context == null || Partial == null || PartialPos == null || ReceivedBlendValues == null)
                throw new NotSupportedException("This VSeeFace build has different lip-sync fields; bridge not activated.");
            _patches = new Harmony("nc.vseeface.speech.prototype");
            Patch(typeof(AudioPlayer), "Update", "BeforePlayerUpdate");
            Patch(typeof(OpenSeeVRMDriver), "ReadAudio", "BeforeReadAudio");
            Patch(typeof(OpenSeeVRMDriver), "ApplyMouthShape", "BeforeMouthTracking");
            _patches.Patch(AccessTools.Method(typeof(EVMC4U.ExternalReceiver), "Update"),
                postfix: new HarmonyMethod(typeof(BridgePlugin), "AfterReceiverUpdate"));
            _instance = this;
            _status.Value.pid = System.Diagnostics.Process.GetCurrentProcess().Id;
            _status.Value.bridge_version = "0.2.0";
            _status.Value.installation_path = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
            Logger.LogInfo("NC speech bridge ready: " + _directory);
            Status("ready", "Waiting for NC. Audible speech remains in NC.");
        }

        private void Patch(Type type, string original, string prefix)
        {
            MethodInfo method = AccessTools.Method(type, original);
            if (method == null) throw new MissingMethodException(type.FullName, original);
            _patches.Patch(method, new HarmonyMethod(typeof(BridgePlugin), prefix));
        }

        private static bool BeforePlayerUpdate(AudioPlayer __instance)
        {
            return !ReferenceEquals(ControlledPlayer, __instance);
        }
        private static bool BeforeReadAudio(OpenSeeVRMDriver __instance)
        {
            // File samples arrive on OnAudioFilterRead; bypass microphone and its restart watchdog.
            return !ReferenceEquals(ControlledDriver, __instance);
        }
        private static bool BeforeMouthTracking(OpenSeeVRMDriver __instance)
        {
            // Hybrid camera mouth tracking must not open the mouth during a paused file.
            return !ReferenceEquals(ControlledDriver, __instance);
        }

        private static void AfterReceiverUpdate(EVMC4U.ExternalReceiver __instance)
        {
            BridgePlugin plugin = _instance;
            if (plugin == null || __instance.vrmDriver == null) return;
            try
            {
                // Native SetMode disables ALL external blendshapes when local tracking is selected.
                // Reuse its accumulator for emotions only, preserving native visemes and blinking.
                var incoming = (Dictionary<VRM.BlendShapeKey,float>)ReceivedBlendValues.GetValue(__instance);
                var emotions = VmcEmotions.Select(plugin._preserveVmcEmotions.Value,
                    __instance.BlendShapeSynchronize, __instance.vrmDriver.skipApply, incoming,
                    delegate(VRM.BlendShapeKey key) { return key.Name; });
                plugin._emotionDriver = __instance.vrmDriver;
                plugin._emotionValues = emotions;
                if (emotions != null && emotions.Count != 0) __instance.vrmDriver.SetProxyValues(emotions);
                plugin._emotionError = false;
            }
            catch (Exception error)
            {
                if (!plugin._emotionError) plugin.Logger.LogWarning("VMC emotion mixing unavailable: " + error.Message);
                plugin._emotionError = true;
                plugin._emotionValues = null;
            }
        }

        private void LateUpdate()
        {
            if (_status.Due(Now(), _maxAge.Value)) WriteStatus();
            TraceEmotions();
            if (ControlledDriver != null && _probe != null && Now() >= _nextDiagnostic)
            {
                Trace("sample");
                _nextDiagnostic=Now()+_diagnosticInterval.Value;
            }
        }

        private void TraceEmotions()
        {
            if (!_diagnostics.Value || _emotionDriver == null || _emotionValues == null
                || Now() < _nextEmotionDiagnostic) return;
            _nextEmotionDiagnostic = Now() + _diagnosticInterval.Value;
            try
            {
                var proxy = _emotionDriver.vrmBlendShapeProxy;
                if (proxy == null) return;
                var values = new List<VmcEmotionValue>();
                foreach (var emotion in _emotionValues)
                    values.Add(new VmcEmotionValue { name = emotion.Key.Name,
                        received = emotion.Value, applied = proxy.GetValue(emotion.Key) });
                File.WriteAllText(Path.Combine(_directory, "emotion_diagnostics.json"),
                    JsonUtility.ToJson(new VmcEmotionDiagnostic { updated = Now(), values = values.ToArray() }));
            }
            catch (Exception error) { Logger.LogWarning("Emotion diagnostic read failed: " + error.Message); }
        }

        private void Update()
        {
            try
            {
                string path = Path.Combine(_directory, "state.json");
                string snapshot = StateFile.TryRead(path);
                if (snapshot != null) _lastState = JsonUtility.FromJson<BridgeState>(snapshot);
                BridgeState state = _lastState;
                double now = Now();
                if (state == null || !state.IsValid(now, _maxAge.Value))
                {
                    if (ControlledPlayer != null) { Release(); Status("stopped", "NC clock expired or state invalid."); }
                    return;
                }
                if (state.client == _client && state.revision < _revision) return;
                _client = state.client;
                _revision = state.revision;
                if (state.clip.Length == 0)
                {
                    if (ControlledPlayer != null) { Release(); Status("stopped", "NC stopped or interrupted speech."); }
                    return;
                }
                if (state.clip != _requested) Begin(state.clip);
                if (_loading)
                {
                    if (!(bool)Playing.GetValue(ControlledPlayer) || _source.clip == null
                        || _source.clip.name != Path.Combine(_directory, state.clip)
                        || _source.clip.loadState != AudioDataLoadState.Loaded) return;
                    _ownedClip = _source.clip;
                    ControlledDriver.InitializeLipSync();
                    ControlledDriver.initializeLipSync = false;
                    _source.loop = false;
                    _loading = false;
                    _paused = false;
                    _atEnd = false;
                    Status("loaded", "Silent analysis clip loaded.");
                    Trace("loaded");
                }
                double target = state.TargetSeconds(now);
                if (!state.running)
                {
                    if (_source.isPlaying) _source.Pause();
                    _paused = true;
                    ClearVisemes();
                    return;
                }
                if (target >= _ownedClip.length)
                {
                    if (!_atEnd) { _source.Stop(); ClearVisemes(); Status("ended", "Silent clip reached its end."); }
                    _atEnd = true;
                    return;
                }
                int sample = Math.Min(_ownedClip.samples - 1, (int)(target * _ownedClip.frequency));
                if (!_source.isPlaying)
                {
                    _source.timeSamples = sample;
                    if (_paused) _source.UnPause(); else _source.Play();
                    _paused = false;
                    _atEnd = false;
                    Status("playing", "Silent analysis follows NC's audible clock.");
                }
                else if (Math.Abs((double)_source.timeSamples / _ownedClip.frequency - target) > _tolerance.Value)
                    _source.timeSamples = sample;
                _hadError = false;
            }
            catch (Exception ex)
            {
                Release();
                if (!_hadError) { Logger.LogError(ex); Status("error", ex.Message); _hadError = true; }
            }
        }

        private void Begin(string clip)
        {
            if (ControlledPlayer == null)
            {
                foreach (AudioPlayer player in Resources.FindObjectsOfTypeAll<AudioPlayer>())
                {
                    if (player.audioSource != null && player.openSeeVRMDriver != null
                        && player.gameObject.activeInHierarchy
                        && player.audioSource.gameObject == player.openSeeVRMDriver.gameObject)
                    {
                        ControlledPlayer = player;
                        ControlledDriver = player.openSeeVRMDriver;
                        break;
                    }
                }
                if (ControlledPlayer == null) throw new InvalidOperationException("No compatible active VSeeFace AudioPlayer was found.");
                _source = ControlledPlayer.audioSource;
                _oldLoop = _source.loop;
                if (!ControlledDriver.lipSync) throw new InvalidOperationException("Enable Audio lip sync in VSeeFace first.");
                _cycle++;
                _probe=_diagnostics.Value ? new AudioProbe() : null;
                Trace("acquired_before_filter");
                // Keep the filter for the source's lifetime. Destroy/re-add at reply
                // boundaries rebuilds Unity 2019.4's DSP graph and is unsafe on this build.
                if (_silencer == null || _silencer.gameObject != _source.gameObject)
                    _silencer = _source.gameObject.AddComponent<SilentOutput>();
                _silencer.Muted = true;
                _silencer.Probe=_probe;
                Trace("acquired_after_filter");
            }
            StopCurrent();
            _requested = clip;
            _loading = true;
            string fullPath = Path.Combine(_directory, clip);
            if (!File.Exists(fullPath)) throw new FileNotFoundException("NC staged audio is missing.", fullPath);
            ControlledPlayer.Play(fullPath);
            Status("loading", "Loading NC speech without audible VSeeFace output.");
        }

        private void ClearVisemes()
        {
            OpenSeeVRMDriver driver = ControlledDriver;
            if (driver == null) return;
            lock (driver) // Matches ProcessBuffer's lock; never race the native audio callback.
            {
                uint context = (uint)Context.GetValue(driver);
                if (context != 0) OVRLipSync.ResetContext(context);
                OVRLipSync.Frame frame = (OVRLipSync.Frame)Frame.GetValue(driver);
                if (frame != null && frame.Visemes != null)
                {
                    Array.Clear(frame.Visemes, 0, frame.Visemes.Length);
                    frame.Visemes[(int)OVRLipSync.Viseme.sil] = 1;
                }
                float[] partial = (float[])Partial.GetValue(driver);
                if (partial != null) Array.Clear(partial, 0, partial.Length);
                PartialPos.SetValue(driver, 0);
            }
        }

        private void StopCurrent()
        {
            if (ControlledPlayer == null) return;
            ControlledPlayer.StopAllCoroutines(); // Stop() alone leaves LoadFile alive.
            ControlledPlayer.Stop();
            _source.Stop();
            Trace("before_clear");
            ClearVisemes();
            Trace("after_clear");
            AudioClip clip = _ownedClip;
            if (clip == null && _source.clip != null && _requested.Length > 0
                && _source.clip.name == Path.Combine(_directory, _requested)) clip = _source.clip;
            _source.clip = null;
            if (clip != null) Destroy(clip);
            _ownedClip = null;
            _loading = false;
            _paused = false;
            _requested = "";
        }

        private void Release()
        {
            if (ControlledPlayer == null) return;
            try
            {
                StopCurrent();
                _source.loop = _oldLoop;
                // Return to normal VSeeFace microphone/tracking behavior when NC releases ownership.
                ControlledDriver.initializeLipSync = true;
                Trace("released_filter_retained");
            }
            finally
            {
                ControlledPlayer = null;
                ControlledDriver = null;
                if (_silencer != null) { _silencer.Muted = false; _silencer.Probe = null; }
                _probe=null;
            }
        }

        private void Status(string state, string detail)
        {
            _status.Value.state=state; _status.Value.detail=detail;
            _status.Value.client=_client; _status.Value.revision=_revision;
            WriteStatus();
        }

        private void WriteStatus()
        {
            try
            {
                _status.Touch(Now(), _maxAge.Value);
                string temp=Path.Combine(_directory,"status.tmp"), target=Path.Combine(_directory,"status.json");
                File.WriteAllText(temp,JsonUtility.ToJson(_status.Value));
                if(File.Exists(target))File.Replace(temp,target,null);else File.Move(temp,target);
            }
            catch(IOException) { }
        }

        private void Trace(string phase)
        {
            if (_probe == null || ControlledDriver == null || _source == null) return;
            try
            {
                OpenSeeVRMDriver d=ControlledDriver;
                AudioProbeSample measured=_probe.Snapshot();
                BridgeDiagnostic value=new BridgeDiagnostic { phase=phase, cycle=_cycle, clip=_requested,
                    revision=_revision, updated=Now(), driver_id=d.GetInstanceID(), source_id=_source.GetInstanceID(),
                    lip_sync=d.lipSync, skip_apply=d.skipApply, use_canned=d.useCanned,
                    is_canned=(bool)IsCanned.GetValue(d), active=d.active, driver_enabled=d.enabled,
                    has_expression=Expression.GetValue(d) != null,
                    expression_allows=(bool)ExpressionAllows.GetValue(d), expression_factor=(float)ExpressionFactor.GetValue(d),
                    is_playing=_source.isPlaying, virtualized=_source.isVirtual, muted=_source.mute,
                    source_volume=_source.volume, source_pitch=_source.pitch, source_time=_source.time,
                    source_count=_source.gameObject.GetComponents<AudioSource>().Length,
                    listener_count=_source.gameObject.GetComponents<AudioListener>().Length,
                    output_frequency=AudioSettings.outputSampleRate, silencer_calls=measured.silencer_calls,
                    silencer_input_peak=measured.silencer_peak, analyzer_hooks=false,
                    silencer_id=_silencer == null ? 0 : _silencer.GetInstanceID() };
                lock(d)
                {
                    value.context=(uint)Context.GetValue(d);
                    OVRLipSync.Frame frame=(OVRLipSync.Frame)Frame.GetValue(d);
                    if (frame != null && frame.Visemes != null)
                        for(int i=1;i<frame.Visemes.Length;i++) value.current_viseme_peak=Math.Max(value.current_viseme_peak,frame.Visemes[i]);
                }
                AudioClip clip=_source.clip;
                if (clip != null) { value.clip_length=clip.length; value.clip_frequency=clip.frequency; value.clip_channels=clip.channels; }
                MonoBehaviour[] components=_source.gameObject.GetComponents<MonoBehaviour>();
                value.driver_filter_index=Array.IndexOf(components,d);
                value.silencer_filter_index=Array.IndexOf(components,_silencer);
                var proxy=d.vrmBlendShapeProxy;
                value.proxy_exists=proxy != null;
                if (proxy != null && proxy.BlendShapeAvatar != null)
                {
                    foreach(var shape in proxy.BlendShapeAvatar.Clips)
                    {
                        if (shape == null || !(shape.Preset == VRM.BlendShapePreset.A || shape.Preset == VRM.BlendShapePreset.I
                            || shape.Preset == VRM.BlendShapePreset.U || shape.Preset == VRM.BlendShapePreset.E
                            || shape.Preset == VRM.BlendShapePreset.O)) continue;
                        value.proxy_mouth_peak=Math.Max(value.proxy_mouth_peak,proxy.GetValue(VRM.BlendShapeKey.CreateFromPreset(shape.Preset)));
                        foreach(var binding in shape.Values)
                        {
                            Transform t=String.IsNullOrEmpty(binding.RelativePath) ? proxy.transform : proxy.transform.Find(binding.RelativePath);
                            SkinnedMeshRenderer renderer=t == null ? null : t.GetComponent<SkinnedMeshRenderer>();
                            if (renderer != null && renderer.sharedMesh != null && binding.Index>=0 && binding.Index<renderer.sharedMesh.blendShapeCount)
                            {
                                value.mouth_binding_count++;
                                value.mesh_mouth_peak=Math.Max(value.mesh_mouth_peak,renderer.GetBlendShapeWeight(binding.Index));
                            }
                        }
                    }
                }
                string json=JsonUtility.ToJson(value);
                File.WriteAllText(Path.Combine(_directory,"diagnostics.json"),json);
                File.AppendAllText(Path.Combine(_directory,"diagnostics.jsonl"),json+Environment.NewLine);
            }
            catch(Exception error) { Logger.LogWarning("Diagnostic read failed: "+error.Message); }
        }

        private void OnDestroy()
        {
            _instance = null;
            Release();
            if (_patches != null) _patches.UnpatchSelf();
        }
    }

    [Serializable]
    public sealed class VmcEmotionValue
    {
        public string name;
        public float received, applied;
    }

    [Serializable]
    public sealed class VmcEmotionDiagnostic
    {
        public double updated;
        public VmcEmotionValue[] values;
    }

    [Serializable]
    public sealed class BridgeDiagnostic
    {
        public string phase,clip;
        public long cycle,revision;
        public double updated;
        public int driver_id,source_id,source_count,listener_count,driver_filter_index,silencer_filter_index,silencer_id;
        public long silencer_calls;
        public bool analyzer_hooks;
        public float silencer_input_peak;
        public uint context;
        public int output_frequency,clip_frequency,clip_channels,mouth_binding_count;
        public bool lip_sync,skip_apply,use_canned,is_canned,active,driver_enabled,has_expression,expression_allows,is_playing,virtualized,muted,proxy_exists;
        public float expression_factor,source_volume,source_pitch,source_time,clip_length,current_viseme_peak,proxy_mouth_peak,mesh_mouth_peak;
    }
}
