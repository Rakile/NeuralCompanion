import "dotenv/config";

import { randomUUID } from "node:crypto";
import { appendFileSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { PassThrough } from "node:stream";

import { Client, Events, GatewayIntentBits } from "discord.js";
import {
  AudioPlayerStatus,
  EndBehaviorType,
  StreamType,
  createAudioPlayer,
  createAudioResource,
  entersState,
  joinVoiceChannel,
  VoiceConnectionStatus
} from "@discordjs/voice";
import ffmpegPath from "ffmpeg-static";
import prism from "prism-media";
import { envOrSetting, loadJsonSettings, setting } from "./settings.js";

const jsonSettings = loadJsonSettings();
const tokenEnvVar = String(setting(jsonSettings, "discord.token_env_var", "DISCORD_TOKEN") || "DISCORD_TOKEN");
const token = process.env[tokenEnvVar];
const voiceChannelId = String(envOrSetting("DISCORD_VOICE_CHANNEL_ID", jsonSettings, "discord.voice_channel_id", ""));
const configuredGuildId = String(envOrSetting("DISCORD_GUILD_ID", jsonSettings, "discord.guild_id", ""));
const allowedUserIds = parseUserIdList(envOrSetting("DISCORD_ALLOWED_USER_ID", jsonSettings, "discord.allowed_user_id", ""));
const answerMode = String(envOrSetting("DISCORD_ANSWER_MODE", jsonSettings, "discord.answer_mode", "allowed_user_only"))
  .trim()
  .toLowerCase();
const playTestTone = asBool(
  envOrSetting("DISCORD_PLAY_TEST_TONE", jsonSettings, "playback.play_test_tone_on_join", false)
);
const bridgeMode = String(envOrSetting("NC_BRIDGE_MODE", jsonSettings, "bridge_mode", "mock")).trim().toLowerCase();
const ncTurnEndpoint = String(envOrSetting("NC_TURN_ENDPOINT", jsonSettings, "nc_runtime.http_endpoint", "http://127.0.0.1:8768/turn"));
const ncCancelEndpoint = ncTurnEndpoint.replace(/\/turn\/?$/i, "/cancel");
const ncFinishEndpoint = ncTurnEndpoint.replace(/\/turn\/?$/i, "/finish");
const ncRouteEndpoint = ncTurnEndpoint.replace(/\/turn\/?$/i, "/route");
const ncSpeakEndpoint = ncTurnEndpoint.replace(/\/turn\/?$/i, "/speak");
const ncProbeEndpoint = ncTurnEndpoint.replace(/\/turn\/?$/i, "/probe_transcript");
const ncBridgeToken = String(process.env.NC_DISCORD_BRIDGE_TOKEN || "");
const runtimeStatusPath = String(process.env.NC_DISCORD_BRIDGE_STATUS_JSON || "");
const commandInboxPath = String(process.env.NC_DISCORD_BRIDGE_COMMAND_JSONL || "");
const silenceMs = positiveInt(envOrSetting("DISCORD_SILENCE_MS", jsonSettings, "capture.silence_ms", 900), 900);
const maxTurnSeconds = maxTurnSecondsSetting(envOrSetting("DISCORD_MAX_TURN_SECONDS", jsonSettings, "capture.max_turn_seconds", 30), 30);
const botMaxTurnSeconds = maxTurnSecondsSetting(
  envOrSetting("DISCORD_BOT_MAX_TURN_SECONDS", jsonSettings, "capture.bot_max_turn_seconds", 120),
  120
);
const botIdleFinalizeMs = nonNegativeInt(
  envOrSetting("DISCORD_BOT_IDLE_FINALIZE_MS", jsonSettings, "capture.bot_idle_finalize_ms", 4500),
  4500
);
const minTurnSeconds = positiveFloat(envOrSetting("DISCORD_MIN_TURN_SECONDS", jsonSettings, "capture.min_turn_seconds", 0.6), 0.6);
const captureWavSampleRate = captureSampleRateSetting(
  envOrSetting("DISCORD_CAPTURE_WAV_SAMPLE_RATE", jsonSettings, "capture.wav_sample_rate", 16_000)
);
const captureWavChannels = captureChannelsSetting(
  envOrSetting("DISCORD_CAPTURE_WAV_CHANNELS", jsonSettings, "capture.wav_channels", 1)
);
let sharedCaptureOwnerEnabled = asBool(
  envOrSetting("DISCORD_SHARED_CAPTURE_OWNER_ENABLED", jsonSettings, "capture.shared_capture_owner_enabled", true)
);
let captureOwnerTtlMs = Math.max(
  3000,
  Math.round(positiveFloat(envOrSetting("DISCORD_CAPTURE_OWNER_TTL_SECONDS", jsonSettings, "capture.owner_ttl_seconds", 8.0), 8.0) * 1000)
);
const mockReplyDelayMs = positiveInt(envOrSetting("MOCK_REPLY_DELAY_MS", jsonSettings, "mock.reply_delay_ms", 450), 450);
let interruptReplyOnUserSpeech = asBool(
  envOrSetting("DISCORD_INTERRUPT_REPLY_ON_USER_SPEECH", jsonSettings, "playback.interrupt_reply_on_user_speech", true)
);
let routeProtectedMicSpeech = asBool(
  envOrSetting(
    "DISCORD_ROUTE_PROTECTED_MIC_SPEECH",
    jsonSettings,
    "playback.route_protected_mic_speech",
    setting(jsonSettings, "tiny_mvp.route_protected_mic_speech", false)
  )
);
let interruptAfterSeconds = nonNegativeFloat(
  envOrSetting("DISCORD_INTERRUPT_AFTER_SECONDS", jsonSettings, "playback.interrupt_after_seconds", 4.0),
  4.0
);
let interruptPauseAfterFailedProbeSeconds = nonNegativeFloat(
  envOrSetting(
    "DISCORD_INTERRUPT_PAUSE_AFTER_FAILED_PROBE_SECONDS",
    jsonSettings,
    "playback.interrupt_pause_after_failed_probe_seconds",
    3.0
  ),
  3.0
);
let replyImmunitySeconds = nonNegativeFloat(
  envOrSetting("DISCORD_REPLY_IMMUNITY_SECONDS", jsonSettings, "playback.reply_immunity_seconds", 4.0),
  4.0
);
let discardBotSpeechOnHumanIntervention = asBool(
  envOrSetting(
    "DISCORD_DISCARD_BOT_SPEECH_ON_HUMAN_INTERVENTION",
    jsonSettings,
    "playback.discard_bot_speech_on_human_intervention",
    true
  )
);
let coordinateBotReplies = asBool(
  envOrSetting("DISCORD_COORDINATE_BOT_REPLIES", jsonSettings, "playback.coordinate_bot_replies", true)
);
let replyFloorStaleSeconds = positiveFloat(
  envOrSetting("DISCORD_REPLY_FLOOR_STALE_SECONDS", jsonSettings, "playback.reply_floor_stale_seconds", 180.0),
  180.0
);
let initialReplyBufferChunks = Math.min(
  8,
  nonNegativeInt(envOrSetting("DISCORD_INITIAL_REPLY_BUFFER_CHUNKS", jsonSettings, "playback.initial_buffer_chunks", 2), 2)
);
let playbackDebugEnabled = asBool(
  envOrSetting("DISCORD_PLAYBACK_DEBUG", jsonSettings, "playback.debug_logging", false)
);
const wavCleanupMaxAgeMinutes = nonNegativeFloat(
  envOrSetting("DISCORD_WAV_CLEANUP_MAX_AGE_MINUTES", jsonSettings, "cleanup.wav_max_age_minutes", 60.0),
  60.0
);
const wavCleanupIntervalMinutes = positiveFloat(
  envOrSetting("DISCORD_WAV_CLEANUP_INTERVAL_MINUTES", jsonSettings, "cleanup.interval_minutes", 10.0),
  10.0
);
let persistRoomContextBetweenRestarts = asBool(
  setting(jsonSettings, "chat.persist_room_context_between_restarts", false)
);
const botInstanceId = safeFileSegment(setting(jsonSettings, "id", setting(jsonSettings, "name", "default"))).toLowerCase();
let roomRouterEnabled = asBool(setting(jsonSettings, "room_router.enabled", true));
let roomRouterMode = String(setting(jsonSettings, "room_router.mode", "llm_router") || "llm_router").trim().toLowerCase();
let roomRouterDefaultWhenUncertain = asBool(setting(jsonSettings, "room_router.default_when_uncertain", true));
let roomRouterHumanToBotRouting = asBool(setting(jsonSettings, "room_router.human_to_bot_routing", true));
let roomRouterBotToBotRouting = asBool(setting(jsonSettings, "room_router.bot_to_bot_routing", true));
let roomRouterExcludeSpeakerFromTargets = asBool(setting(jsonSettings, "room_router.exclude_speaker_from_targets", true));
let roomRouterAllowGroupInvitationRouting = asBool(setting(jsonSettings, "room_router.allow_group_invitation_routing", true));
let roomRouterAllowOpenRoomInvitationRouting = asBool(setting(jsonSettings, "room_router.allow_open_room_invitation_routing", true));
let roomRouterSelfRoutePolicy = String(setting(jsonSettings, "room_router.self_route_policy", "ignore") || "ignore").trim().toLowerCase();
let roomRouterDecisionTimeoutMs = Math.max(
  1000,
  Math.round(positiveFloat(setting(jsonSettings, "room_router.decision_timeout_seconds", 20.0), 20.0) * 1000)
);
let roomRouterWindowMs = Math.max(
  500,
  Math.round(positiveInt(setting(jsonSettings, "room_router.route_window_ms", 4000), 4000))
);
let roomRouterCandidateBots = Array.isArray(setting(jsonSettings, "room_router.candidate_bots", []))
  ? setting(jsonSettings, "room_router.candidate_bots", [])
  : [];
let routeBotRepliesFromText = asBool(setting(jsonSettings, "room_router.route_bot_replies_from_text", true));
let prepareRoutedBotRepliesAhead = asBool(setting(jsonSettings, "room_router.prepare_bot_replies_ahead", true));
let competingBotReplyPolicy = String(setting(jsonSettings, "room_router.competing_bot_reply_policy", "first_ready_wins") || "first_ready_wins").trim().toLowerCase();
let replyFloorMode = String(setting(jsonSettings, "room_router.reply_floor_mode", "first_ready_wins") || "first_ready_wins").trim().toLowerCase();
let deadAirRecoveryEnabled = asBool(setting(jsonSettings, "room_router.dead_air_recovery.enabled", false));
let deadAirRecoveryCooldownMs = Math.round(
  nonNegativeFloat(setting(jsonSettings, "room_router.dead_air_recovery.cooldown_seconds", 0.0), 0.0) * 1000
);
let deadAirRecoverySilenceTimeoutMs = Math.round(
  nonNegativeFloat(setting(jsonSettings, "room_router.dead_air_recovery.silence_timeout_seconds", 10.0), 10.0) * 1000
);
let deadAirRecoveryTriggerMode = String(
  setting(jsonSettings, "room_router.dead_air_recovery.trigger_mode", "no_route_after_bot_speech") || "no_route_after_bot_speech"
).trim().toLowerCase();
let deadAirRecoveryActionMode = String(
  setting(jsonSettings, "room_router.dead_air_recovery.action_mode", "moderator_speaks_and_calls_next") || "moderator_speaks_and_calls_next"
).trim().toLowerCase();
let deadAirRecoveryNextSpeakerStrategy = String(
  setting(jsonSettings, "room_router.dead_air_recovery.next_speaker_strategy", "llm_choose") || "llm_choose"
).trim().toLowerCase();
let deadAirRecoveryFallbackTarget = String(
  setting(jsonSettings, "room_router.dead_air_recovery.selected_fallback_target", "") || ""
).trim();
let routedTextPollMs = Math.max(
  100,
  Math.round(positiveInt(setting(jsonSettings, "room_router.routed_text_poll_ms", 250), 250))
);
let routedTextMaxAgeMs = Math.max(
  1000,
  Math.round(positiveFloat(setting(jsonSettings, "room_router.routed_text_max_age_seconds", 30.0), 30.0) * 1000)
);
const botDisplayName = String(setting(jsonSettings, "name", botInstanceId) || botInstanceId).trim() || botInstanceId;

if (!token) {
  throw new Error(
    `Discord token environment variable "${tokenEnvVar}" is missing. ` +
      "Set it before launch, or configure a local test token in the NC Discord Voice Bridge settings."
  );
}
if (!voiceChannelId) {
  throw new Error("DISCORD_VOICE_CHANNEL_ID is missing in .env");
}

const captureDir = join(process.cwd(), "captures");
const replyDir = join(process.cwd(), "mock_replies");
const turnDir = join(process.cwd(), "turns");
const replyFloorPath = join(process.cwd(), `reply_floor_${safeFileSegment(voiceChannelId)}.json`);
const roomContextPath = join(process.cwd(), `room_context_${safeFileSegment(voiceChannelId)}.json`);
const humanInterventionPath = join(process.cwd(), `human_intervention_${safeFileSegment(voiceChannelId)}.json`);
const playbackControlPath = join(process.cwd(), `playback_control_${safeFileSegment(voiceChannelId)}.json`);
const captureOwnerPath = join(process.cwd(), `capture_owner_${safeFileSegment(voiceChannelId)}.json`);
const moderatorStatePath = join(process.cwd(), `moderator_state_${safeFileSegment(voiceChannelId)}.json`);
const playbackDebugPath = join(process.cwd(), `playback_debug_${botInstanceId}.log`);
mkdirSync(captureDir, { recursive: true });
mkdirSync(replyDir, { recursive: true });
mkdirSync(turnDir, { recursive: true });
if (playbackDebugEnabled) {
  writeFileSync(playbackDebugPath, "", "utf8");
}
const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates]
});
const activeCaptures = new Set();
const activeHumanSpeechMonitors = new Set();
const activeCaptureControllers = new Map();
let voicePlayer = null;
let playbackActive = false;
const playbackQueue = [];
let playbackGeneration = 0;
let activeNcAbortController = null;
let activeNcTurnId = null;
let activePlaybackTurnId = null;
let activePlaybackStartedAtMs = 0;
let deliveredReplyTextParts = [];
const completedReplyTurnIds = new Set();
let currentPlaybackItem = null;
let activeReplyProgress = null;
const replyProgressByTurnId = new Map();
let activeVoiceConnection = null;
let playbackPausedForTranscriptProbe = null;
let lastPlaybackControlEventId = "";
let lastTranscriptText = "";
let lastRouteDecision = null;
let lastErrorText = "";
let lastModeratorState = null;
let lastModeratorMuteEnforcementKey = "";
let moderatorMuteEnforcementPromise = null;
let moderatorMuteEnforcementRerunReason = "";
const speakerNameCache = new Map();
const pendingInterruptByUserId = new Map();
let activeVoiceChannel = null;
const routedTextInProgress = new Set();
let lastRoomActivityAtMs = Date.now();
let lastSilenceRecoveryActivityAtMs = 0;

playbackDebug("startup", {
  botInstanceId,
  botDisplayName,
  voiceChannelId,
  bridgeMode,
  initialReplyBufferChunks,
  coordinateBotReplies,
  replyFloorMode,
  prepareRoutedBotRepliesAhead
});
cleanupDeadReplyFloorOnStartup();
cleanupDeadCaptureOwnerOnStartup();
setTimeout(() => {
  refreshCaptureOwnership("startup").catch((error) => {
    console.warn("[DiscordBridgeCapture] Startup capture-owner election failed:", error?.message || error);
  });
}, Math.floor(Math.random() * 1200)).unref();
resetRoomContextOnStartup();
discardPendingRoutedTextTurns("bridge startup");
lastPlaybackControlEventId = String(readJsonFile(playbackControlPath)?.event_id || "");
cleanupOldWavFiles(captureDir, "capture");
setInterval(() => {
  cleanupOldWavFiles(captureDir, "capture");
}, Math.max(60_000, Math.round(wavCleanupIntervalMinutes * 60_000))).unref();
setInterval(() => {
  refreshCaptureOwnership("heartbeat").catch((error) => {
    console.warn("[DiscordBridgeCapture] Capture-owner heartbeat failed:", error?.message || error);
  });
}, Math.max(1000, Math.round(captureOwnerTtlMs / 3))).unref();
setInterval(() => {
  processRoutedTextInbox().catch((error) => {
    console.error("[DiscordBridgeRouter] Routed-text inbox failed:", error);
  });
}, routedTextPollMs).unref();
setInterval(() => {
  processPlaybackControlInbox();
}, 150).unref();
setInterval(() => {
  processCommandInbox().catch((error) => {
    lastErrorText = String(error?.message || error || "command inbox failed");
    console.error("[DiscordBridgeControl] Command inbox failed:", error);
    writeRuntimeStatus("command_error");
  });
}, 350).unref();
setInterval(() => {
  watchModeratorMuteEnforcement().catch((error) => {
    console.warn("[DiscordBridgeModerator] Mute enforcement watcher failed:", error?.message || error);
  });
}, 100).unref();
setInterval(() => {
  maybeDropRoutedPreRenderAfterManualNext();
  maybeRepublishCompletedTextForManualNext();
}, 150).unref();
setInterval(() => {
  maybeQueueSilenceTimeoutRecovery().catch((error) => {
    console.warn("[DiscordBridgeModerator] Silence-timeout recovery failed:", error?.message || error);
  });
}, 500).unref();

client.once(Events.ClientReady, async () => {
  console.log(`[DiscordBridge] Logged in as ${client.user.tag}`);

  const channel = await client.channels.fetch(voiceChannelId);
  if (!channel || !channel.isVoiceBased()) {
    throw new Error(`Channel ${voiceChannelId} is not a voice channel or could not be fetched.`);
  }
  activeVoiceChannel = channel;

  const guildId = configuredGuildId || channel.guild.id;
  console.log(`[DiscordBridge] Joining voice channel "${channel.name}" (${voiceChannelId}) in guild ${guildId}`);
  for (const [memberId, member] of channel.members || []) {
    cacheSpeakerName(memberId, member);
  }

  await connectVoiceChannel(channel, "startup");

  if (playTestTone) {
    console.log("[DiscordBridge] Playing test tone.");
    queuePcmPlayback(makeTonePcm(440, 450), "startup test tone");
  }
});

client.on("error", (error) => {
  console.error("[DiscordBridge] Client error:", error);
});

client.on(Events.VoiceStateUpdate, (_oldState, newState) => {
  if (newState?.member?.id) {
    cacheSpeakerName(newState.member.id, newState.member);
  }
  if (newState?.channelId === voiceChannelId && newState.channel?.isVoiceBased?.()) {
    activeVoiceChannel = newState.channel;
    writeRuntimeStatus("connected");
  }
});

process.on("SIGINT", () => {
  console.log("\n[DiscordBridge] Shutting down.");
  writeRuntimeStatus("stopping");
  releaseReplyFloor("", { force: true, reason: "shutdown" });
  client.destroy();
  process.exit(0);
});

await client.login(token);

function captureSpeechTurn(connection, userId, guildId) {
  if (activeCaptures.has(userId)) {
    return;
  }
  activeCaptures.add(userId);
  noteRoomActivity("speech_start");
  console.log(`[DiscordBridge] Speech started: user=${userId}`);
  const captureStartedAtMs = Date.now();
  const routeKey = roomRouteKey(userId, captureStartedAtMs);

  const opusStream = connection.receiver.subscribe(userId, {
    end: {
      behavior: EndBehaviorType.AfterSilence,
      duration: silenceMs
    }
  });

  const decoder = new prism.opus.Decoder({
    rate: 48_000,
    channels: 2,
    frameSize: 960
  });

  const chunks = [];
  let totalBytes = 0;
  const speakerIsBot = isDiscordBotUser(userId);
  const activeMaxTurnSeconds = speakerIsBot ? botMaxTurnSeconds : maxTurnSeconds;
  const maxBytes = activeMaxTurnSeconds > 0
    ? 48_000 * 2 * 2 * activeMaxTurnSeconds
    : Number.POSITIVE_INFINITY;
  const idleFinalizeMs = speakerIsBot
    ? Math.max(silenceMs + 250, botIdleFinalizeMs)
    : Math.max(250, silenceMs + 250);
  if (speakerIsBot) {
    console.log(
      `[DiscordBridgeDecision] Bot speaker detected: user=${userId}, idle_finalize_ms=${idleFinalizeMs}, max_turn_seconds=${formatMaxTurnSeconds(activeMaxTurnSeconds)}`
    );
  }
  const replyImmunityRemainingAtStartMs = playbackImmunityRemainingMs();
  const replyImmunityUntilMs = replyImmunityRemainingAtStartMs > 0
    ? Date.now() + replyImmunityRemainingAtStartMs
    : 0;
  if (replyImmunityRemainingAtStartMs > 0) {
    console.log(
      `[DiscordBridgeDecision] Capture started during reply immunity: user=${userId}, remaining=${Math.ceil(replyImmunityRemainingAtStartMs)}ms`
    );
  }
  let longSpeechInterruptTimer = null;
  let idleFinalizeTimer = null;
  let maxCaptureTimer = null;
  let captureFinalized = false;
  let continuousInterruptRequested = false;
  let interruptProbeRequested = false;
  let interruptProbeFailed = false;
  let interruptPauseRequested = false;
  let interruptHardCommitted = false;
  const continuousInterruptThresholdSeconds = Math.max(interruptAfterSeconds, minTurnSeconds);
  const interruptPauseThresholdSeconds = interruptPauseAfterFailedProbeSeconds > 0
    ? continuousInterruptThresholdSeconds + interruptPauseAfterFailedProbeSeconds
    : 0;

  const maybePauseAfterFailedProbe = () => {
    if (
      captureFinalized
      || speakerIsBot
      || interruptPauseRequested
      || !interruptProbeFailed
      || interruptPauseThresholdSeconds <= 0
    ) {
      return;
    }
    const durationSeconds = totalBytes / 192000;
    if (durationSeconds < interruptPauseThresholdSeconds) {
      return;
    }
    interruptPauseRequested = true;
    const pauseReason = `speech from user ${userId} reached ${durationSeconds.toFixed(1)}s after failed ${continuousInterruptThresholdSeconds.toFixed(1)}s probe`;
    if (moderatorBlocksSpeechInterruption()) {
      console.log(`[DiscordBridgeModerator] Speech probe pause blocked: moderator routing flow is protected (${pauseReason})`);
      return;
    }
    const pendingInterrupt = pendingPlaybackInterrupt(pauseReason);
    if (pendingInterrupt) {
      pendingInterruptByUserId.set(String(userId), pendingInterrupt);
    }
    emitPlaybackControl("probe_pause", pauseReason);
    const paused = pauseReplyPlaybackForTranscriptProbe(pauseReason);
    if (!paused) {
      console.log(
        `[DiscordBridgeDecision] Speech pause threshold reached without pausable reply: user=${userId}, duration=${durationSeconds.toFixed(2)}s`
      );
    }
  };

  const runInterruptTranscriptProbe = async (durationSeconds) => {
    if (captureFinalized || speakerIsBot || bridgeMode !== "http") {
      return;
    }
    const probePcm = Buffer.concat(chunks);
    if (!probePcm.length) {
      return;
    }
    const probePath = writeCaptureProbeWav(userId, probePcm);
    console.log(
      `[DiscordBridgeDecision] Probing continuous speech transcript: user=${userId}, duration=${durationSeconds.toFixed(2)}s`
    );
    const probe = await requestTranscriptProbe({
      userId,
      filePath: probePath,
      durationSeconds
    });
    if (captureFinalized) {
      return;
    }
    if (probe.accepted) {
      interruptHardCommitted = true;
      pendingInterruptByUserId.delete(String(userId));
      const reason = `valid ${durationSeconds.toFixed(1)}s speech probe from user ${userId}`;
      const shouldInterrupt = !moderatorBlocksSpeechInterruption();
      if (shouldInterrupt) {
        emitPlaybackControl("interrupt", reason);
      }
      const interrupted = shouldInterrupt
        ? interruptCurrentReply(reason, { abortActiveRequest: true, sendCancel: true })
        : false;
      if (!shouldInterrupt) {
        console.log(`[DiscordBridgeModerator] Continuous speech probe did not interrupt: moderator routing flow is protected (${reason}).`);
      }
      console.log(
        `[DiscordBridgeDecision] Continuous speech probe accepted: user=${userId}, interrupted=${interrupted}, text=${previewText(probe.input_text || "")}`
      );
      return;
    }
    interruptProbeFailed = true;
    console.log(
      `[DiscordBridgeDecision] Continuous speech probe did not accept transcript: user=${userId}, reason=${probe.reason || "unknown"}`
    );
    maybePauseAfterFailedProbe();
  };

  const clearCaptureTimers = () => {
    if (longSpeechInterruptTimer) {
      clearTimeout(longSpeechInterruptTimer);
      longSpeechInterruptTimer = null;
    }
    if (idleFinalizeTimer) {
      clearTimeout(idleFinalizeTimer);
      idleFinalizeTimer = null;
    }
    if (maxCaptureTimer) {
      clearTimeout(maxCaptureTimer);
      maxCaptureTimer = null;
    }
  };

  const scheduleIdleFinalize = () => {
    if (idleFinalizeTimer) {
      clearTimeout(idleFinalizeTimer);
    }
    idleFinalizeTimer = setTimeout(() => {
      finalizeCapture("pcm_idle").catch((error) => {
        console.error(`[DiscordBridge] Capture finalization failed for user=${userId}:`, error);
      });
    }, idleFinalizeMs);
  };

  const finalizeCapture = async (reason, options = {}) => {
    if (captureFinalized) {
      return;
    }
    captureFinalized = true;
    noteRoomActivity("speech_end");
    activeCaptures.delete(userId);
    activeCaptureControllers.delete(String(userId));
    clearCaptureTimers();
    try {
      opusStream.destroy();
    } catch {
      // Ignore stream teardown races.
    }
    try {
      decoder.destroy();
    } catch {
      // Ignore decoder teardown races.
    }
    if (!chunks.length) {
      console.log(`[DiscordBridge] Speech ended with no PCM data: user=${userId}, reason=${reason}`);
      resumeReplyPlaybackEverywhere("speech ended with no PCM data");
      return;
    }
    const pcm = Buffer.concat(chunks);
    const durationSeconds = pcm.length / 192000;
    if (options.discard) {
      console.log(
        `[DiscordBridgeDecision] Speech discarded: user=${userId}, duration=${durationSeconds.toFixed(2)}s, reason=${reason}`
      );
      pendingInterruptByUserId.delete(String(userId));
      resumeReplyPlaybackEverywhere(`discarded speech: ${reason}`);
      return;
    }
    const replyImmunityRemainingAtEndMs = Math.max(
      replyImmunityUntilMs > 0 ? replyImmunityUntilMs - Date.now() : 0,
      playbackImmunityRemainingMs()
    );
    if (replyImmunityRemainingAtEndMs > 0) {
      console.log(
        `[DiscordBridge] Speech ignored: ended during reply immunity with ${Math.ceil(replyImmunityRemainingAtEndMs)}ms remaining (${durationSeconds.toFixed(2)}s, reason=${reason})`
      );
      pendingInterruptByUserId.delete(String(userId));
      resumeReplyPlaybackEverywhere("speech ended during reply immunity");
      return;
    }
    if (durationSeconds < minTurnSeconds) {
      console.log(
        `[DiscordBridge] Speech ignored: duration ${durationSeconds.toFixed(2)}s is below minimum ${minTurnSeconds.toFixed(2)}s (reason=${reason})`
      );
      pendingInterruptByUserId.delete(String(userId));
      resumeReplyPlaybackEverywhere("speech below minimum duration");
      return;
    }
    const captureAudio = prepareCaptureWavPcm(pcm, captureWavSampleRate, captureWavChannels);
    const wav = encodeWav(captureAudio.pcm, captureAudio.sampleRate, captureAudio.channels, 16);
    const fileName = `speech_${userId}_${Date.now()}.wav`;
    const filePath = join(captureDir, fileName);
    writeFileSync(filePath, wav);
    console.log(
      `[DiscordBridge] Speech captured: ${filePath} (${durationSeconds.toFixed(2)}s, `
      + `${captureAudio.sampleRate}Hz/${captureAudio.channels}ch, reason=${reason})`
    );
    const speakerName = await resolveSpeakerName(userId, guildId);
    console.log(`[DiscordBridge] Speaker resolved: user=${userId}, name=${speakerName}`);
    const pendingInterrupt = interruptHardCommitted ? null : pendingInterruptByUserId.get(String(userId)) || null;
    pendingInterruptByUserId.delete(String(userId));
    if (speakerIsBot && shouldUseDirectBotTextRouting()) {
      console.log(
        `[DiscordBridgeRouter] Ignoring bot audio capture because direct bot text routing is enabled: speaker=${speakerName}`
      );
      return;
    }
    console.log(
      `[DiscordBridgeDecision] Sending turn to NC: speaker=${speakerName}, duration=${durationSeconds.toFixed(2)}s, pending_interrupt=${Boolean(pendingInterrupt)}`
    );
    handleCapturedSpeech({
      userId,
      speakerName,
      speakerIsBot,
      filePath,
      durationSeconds,
      pendingInterrupt,
      capturedAt: new Date(captureStartedAtMs).toISOString(),
      routeKey
    }).catch((error) => {
      console.error("[DiscordBridge] Captured speech handler failed:", error);
    });
  };

  activeCaptureControllers.set(String(userId), {
    speakerIsBot,
    finalizeDiscarded: (reason) => finalizeCapture(reason, { discard: true })
  });

  if (activeMaxTurnSeconds > 0) {
    maxCaptureTimer = setTimeout(() => {
      console.log(`[DiscordBridge] Capture hard limit reached: user=${userId}, max=${activeMaxTurnSeconds}s`);
      finalizeCapture("max_turn_seconds").catch((error) => {
        console.error(`[DiscordBridge] Capture finalization failed for user=${userId}:`, error);
      });
    }, Math.round(activeMaxTurnSeconds * 1000));
  }

  decoder.on("data", (chunk) => {
    if (captureFinalized) {
      return;
    }
    if (totalBytes >= maxBytes) {
      finalizeCapture("max_bytes").catch((error) => {
        console.error(`[DiscordBridge] Capture finalization failed for user=${userId}:`, error);
      });
      return;
    }
    chunks.push(chunk);
    totalBytes += chunk.length;
    if (
      !speakerIsBot
      && interruptAfterSeconds > 0
      && !continuousInterruptRequested
      && totalBytes / 192000 >= continuousInterruptThresholdSeconds
    ) {
      continuousInterruptRequested = true;
      requestContinuousSpeechInterrupt(userId);
    }
    if (
      !speakerIsBot
      && interruptReplyOnUserSpeech
      && interruptAfterSeconds > 0
      && !interruptProbeRequested
      && totalBytes / 192000 >= continuousInterruptThresholdSeconds
    ) {
      interruptProbeRequested = true;
      runInterruptTranscriptProbe(totalBytes / 192000).catch((error) => {
        interruptProbeFailed = true;
        console.warn(`[DiscordBridgeDecision] Continuous speech probe failed: ${error?.message || error}`);
        maybePauseAfterFailedProbe();
      });
    }
    maybePauseAfterFailedProbe();
    scheduleIdleFinalize();
  });

  decoder.once("end", async () => {
    await finalizeCapture("stream_end");
  });

  decoder.once("error", (error) => {
    activeCaptures.delete(userId);
    activeCaptureControllers.delete(String(userId));
    clearCaptureTimers();
    console.error(`[DiscordBridge] Decoder error for user=${userId}:`, error);
  });

  opusStream.pipe(decoder);
}

async function handleCapturedSpeech(turn) {
  if (bridgeMode === "mock") {
    await handleMockNcTurn(turn);
    return;
  }
  if (bridgeMode === "http") {
    const route = await routeCapturedSpeech(turn);
    if (route.acceptedSpeech) {
      const reason = `accepted speech after route: ${route.reason || "room_router"}`;
      if (moderatorBlocksSpeechInterruption()) {
        console.log(`[DiscordBridgeModerator] Accepted speech did not interrupt after routing: moderator routing flow is protected (${reason}).`);
      } else {
        emitPlaybackControl("interrupt", reason, {
          route_key: String(route.decision?.route_key || turn.routeKey || ""),
          target_bot_id: String(route.decision?.target_bot_id || "")
        });
        interruptCurrentReply(reason, {
          abortActiveRequest: true,
          sendCancel: true,
          discardRoutedTurns: false,
          humanInterventionExtra: {
            accepted_route_key: String(route.decision?.route_key || turn.routeKey || ""),
            target_bot_id: String(route.decision?.target_bot_id || "")
          }
        });
      }
    }
    if (!route.shouldProceed) {
      console.log(`[DiscordBridgeRouter] Turn not routed to this bot: ${route.reason || "not_selected"}`);
      if (route.acceptedSpeech) {
        // The accepted speech already broadcast an interrupt above; the selected bot will handle the routed turn.
      } else {
        resumeReplyPlaybackEverywhere(`turn not routed: ${route.reason || "not_selected"}`);
      }
      return;
    }
    turn.roomRouterDecision = route.decision || null;
    turn.acceptedSpeechInterrupt = Boolean(route.acceptedSpeech);
    await handleHttpNcTurn(turn);
    return;
  }

  console.warn(`[DiscordBridge] Unsupported NC_BRIDGE_MODE="${bridgeMode}". Captured WAV was saved only.`);
}

function writeCaptureProbeWav(userId, discordPcmBuffer) {
  const captureAudio = prepareCaptureWavPcm(discordPcmBuffer, captureWavSampleRate, captureWavChannels);
  const wav = encodeWav(captureAudio.pcm, captureAudio.sampleRate, captureAudio.channels, 16);
  const fileName = `probe_${safeFileSegment(userId)}_${Date.now()}.wav`;
  const filePath = join(captureDir, fileName);
  writeFileSync(filePath, wav);
  return filePath;
}

async function requestTranscriptProbe(turn) {
  if (bridgeMode !== "http") {
    return { ok: true, accepted: false, reason: "bridge_not_http", input_text: "" };
  }
  const response = await fetch(ncProbeEndpoint, {
    method: "POST",
    headers: ncJsonHeaders(),
    body: JSON.stringify({
      user_id: turn.userId,
      wav_path: turn.filePath,
      duration_seconds: turn.durationSeconds
    })
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) {
    throw new Error(`Transcript probe failed: ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function routeCapturedSpeech(turn) {
  if (!shouldUseRoomRouter()) {
    return { shouldProceed: true, reason: "room_router_disabled" };
  }
  if (turn.speakerBotId && !roomRouterBotToBotRouting) {
    console.log(`[DiscordBridgeRouter] Bot-to-bot routing disabled; speaker=${turn.speakerBotId}`);
    return { shouldProceed: false, reason: "bot_to_bot_routing_disabled" };
  }
  if (!turn.speakerBotId && !roomRouterHumanToBotRouting) {
    console.log("[DiscordBridgeRouter] Human-to-bot routing disabled.");
    return { shouldProceed: false, reason: "human_to_bot_routing_disabled" };
  }
  const routeKey = String(turn.routeKey || roomRouteKey(turn.userId, Date.now()));
  const resultPath = roomRouteResultPath(routeKey);
  const lockPath = `${resultPath}.lock`;
  const routeStartedAtMs = Date.now();
  let existing = readJsonFile(resultPath);
  if (
    existing
    && !turn.speakerBotId
    && String(turn.filePath || "").trim()
    && String(existing.source || "") === "human_moderator"
    && String(existing.reason || "").startsWith("human_moderator_route_next")
    && !String(existing.input_text || "").trim()
  ) {
    try {
      unlinkSync(resultPath);
    } catch {
      // A concurrent bridge may have already replaced the stale result.
    }
    console.log("[DiscordBridgeRouter] Ignored stale pre-transcript human_moderator_route_next result for human capture.");
    existing = null;
  }
  if (existing) {
    const existingOverride = moderatorOverrideReasonSince(routeResultTimestampMs(existing, resultPath));
    if (existingOverride && !existing?.moderator_override) {
      const moderatorFallback = moderatorDecisionForTurn(turn, routeKey);
      const reconciled = stampRouteDecision(
        moderatorFallback || noRouteDecisionAfterModeratorOverride(turn, routeKey, existingOverride)
      );
      console.log(`[DiscordBridgeRouter] Existing route decision ignored after moderator override: ${existingOverride}`);
      return routeDecisionForThisBot(reconciled);
    }
    return routeDecisionForThisBot(existing);
  }

  if (tryCreateRouteLock(lockPath)) {
    try {
      console.log(`[DiscordBridgeRouter] Routing utterance once: key=${routeKey}, owner=${botInstanceId}`);
      const needsTranscriptBeforeModeratorDecision = turnNeedsTranscriptBeforeModeratorDecision(turn);
      let decision = null;
      if (!needsTranscriptBeforeModeratorDecision) {
        decision = moderatorDecisionForTurn(turn, routeKey);
      }
      if (!decision) {
        decision = await requestRoomRouteDecision(turn, routeKey);
        if (needsTranscriptBeforeModeratorDecision && decision?.speech_accepted !== false && String(decision?.input_text || "").trim()) {
          const transcriptTurn = turnWithRouteDecisionTranscript(turn, decision);
          const transcriptModeratorDecision = moderatorDecisionForTurn(transcriptTurn, routeKey);
          if (transcriptModeratorDecision) {
            decision = {
              ...transcriptModeratorDecision,
              input_text: String(decision.input_text || transcriptModeratorDecision.input_text || "").trim(),
              context_input_text: String(decision.context_input_text || transcriptModeratorDecision.context_input_text || "").trim(),
              speech_accepted: true
            };
            console.log("[DiscordBridgeRouter] Applied moderator route after transcript was available.");
          }
        }
        const lateOverride = moderatorOverrideReasonSince(routeStartedAtMs);
        if (lateOverride) {
          const freshModeratorDecision = moderatorDecisionForTurn(turnWithRouteDecisionTranscript(turn, decision), routeKey);
          decision = freshModeratorDecision || noRouteDecisionAfterModeratorOverride(turn, routeKey, lateOverride);
          console.log(`[DiscordBridgeRouter] Captured speech route reconciled after moderator override: ${lateOverride}`);
        }
      }
      decision = decisionWithHumanFloorIfNeeded(decision, turn, moderatorEnforcerBotId());
      decision = stampRouteDecision(decision);
      const preBroadcastTarget = safeFileSegment(decision?.target_bot_id || "").toLowerCase();
      await broadcastRoomTurnToBotHistories(decision, turn, routeKey);
      const postContextOverride = moderatorOverrideReasonSince(routeStartedAtMs);
      if (postContextOverride && !decision?.moderator_override) {
        const freshModeratorDecision = moderatorDecisionForTurn(turn, routeKey);
        decision = stampRouteDecision(
          freshModeratorDecision || noRouteDecisionAfterModeratorOverride(turn, routeKey, postContextOverride)
        );
        await broadcastRoomTurnToBotHistories(decision, turn, `${routeKey}:override:${preBroadcastTarget}`, {
          includeSelectedTarget: true,
          onlyCandidateIds: preBroadcastTarget ? [preBroadcastTarget] : []
        });
        console.log(`[DiscordBridgeRouter] Captured speech route queue reconciled after moderator override: ${postContextOverride}`);
      }
      appendRoomContextFromDecision(decision);
      writeFileSync(resultPath, JSON.stringify(decision, null, 2), "utf8");
      appendModeratorRouteFlow(decision, turn, routeKey, decision?.source || "room_router");
      markAcceptedHumanRoute(decision, turn, routeKey);
      const normalizedTarget = normalizeRecoveryTargetId(decision?.target_bot_id || "");
      if (normalizedTarget.startsWith("human:")) {
        setHumanCurrentFromRoute(normalizedTarget, {
          reason: String(decision?.reason || "room_router_human_route"),
          commandPrefix: "room_router_current_human",
          muteReason: "room_router_human_route"
        });
      } else {
        writeRoutedTurnForSelectedTarget(decision, turn, routeKey, routeStartedAtMs);
      }
      await maybeQueueDeadAirRecovery(decision, turn, routeKey, decision?.source || "room_router");
      return routeDecisionForThisBot(decision);
    } finally {
      try {
        unlinkSync(lockPath);
      } catch {
        // Lock may already be gone if the process is stopping.
      }
    }
  }

  const waited = await waitForRouteDecision(resultPath);
  if (!waited) {
    const moderatorFallback = moderatorDecisionForTurn(turn, routeKey);
    if (moderatorFallback) {
      console.log("[DiscordBridgeRouter] Route decision timed out; using current moderator route.");
      return routeDecisionForThisBot(moderatorFallback);
    }
    const timeoutOverride = moderatorOverrideReasonSince(routeStartedAtMs);
    if (timeoutOverride) {
      console.log(`[DiscordBridgeRouter] Route decision timed out after moderator override: ${timeoutOverride}`);
      return routeDecisionForThisBot(noRouteDecisionAfterModeratorOverride(turn, routeKey, timeoutOverride));
    }
    const fallback = {
      ok: true,
      answer: Boolean(roomRouterDefaultWhenUncertain),
      target_bot_id: roomRouterDefaultWhenUncertain ? botInstanceId : "",
      reason: "route_timeout",
      route_key: routeKey,
      created_at_ms: Date.now()
    };
    console.log(`[DiscordBridgeRouter] Route decision timed out; fallback target=${fallback.target_bot_id || "(none)"}`);
    return routeDecisionForThisBot(fallback);
  }
  const waitedOverride = moderatorOverrideReasonSince(routeStartedAtMs);
  if (waitedOverride && !waited?.moderator_override) {
    const moderatorFallback = moderatorDecisionForTurn(turn, routeKey);
    if (moderatorFallback) {
      console.log(`[DiscordBridgeRouter] Waited route decision superseded by moderator route: ${waitedOverride}`);
      return routeDecisionForThisBot(moderatorFallback);
    }
    console.log(`[DiscordBridgeRouter] Waited route decision ignored after moderator override: ${waitedOverride}`);
    return routeDecisionForThisBot(noRouteDecisionAfterModeratorOverride(turn, routeKey, waitedOverride));
  }
  return routeDecisionForThisBot(waited);
}

function shouldUseRoomRouter() {
  return bridgeMode === "http" && roomRouterEnabled && Array.isArray(roomRouterCandidateBots) && roomRouterCandidateBots.length > 1;
}

function shouldUseDirectBotTextRouting() {
  return shouldUseRoomRouter() && roomRouterBotToBotRouting && routeBotRepliesFromText;
}

function readModeratorState() {
  const payload = readJsonFile(moderatorStatePath);
  return payload && typeof payload === "object" ? payload : {};
}

function normalizeModeratorStateForWrite(state) {
  const next = state && typeof state === "object" ? { ...state } : {};
  const currentBot = safeFileSegment(next.current_bot_id || "").toLowerCase();
  const currentBotIsLive = Boolean(currentBot && moderatorLiveTarget(currentBot));
  const effectiveCurrentBot = currentBotIsLive ? currentBot : "";
  const currentHuman = next.current_human_route && typeof next.current_human_route === "object"
    ? { ...next.current_human_route }
    : {};
  const currentHumanId = String(currentHuman.speaker_user_id || "").trim();
  const pendingBot = next.pending_route && typeof next.pending_route === "object"
    ? { ...next.pending_route }
    : {};
  const pendingHuman = next.pending_human_route && typeof next.pending_human_route === "object"
    ? { ...next.pending_human_route }
    : {};
  const pendingBotTarget = safeFileSegment(pendingBot.target_bot_id || "").toLowerCase();
  const pendingBotIsLive = Boolean(pendingBotTarget && moderatorLiveTarget(pendingBotTarget));
  const pendingHumanId = String(pendingHuman.speaker_user_id || "").trim();

  if (effectiveCurrentBot) {
    next.current_bot_id = effectiveCurrentBot;
  } else {
    next.current_bot_id = "";
    next.current_bot_name = "";
    next.current_bot_discord_user_id = "";
    next.current_bot_turn_id = "";
  }

  if (effectiveCurrentBot && currentHumanId) {
    next.current_human_route = {};
    next.current_speaker_user_id = "";
    next.current_speaker_name = "";
  } else if (currentHumanId) {
    next.current_human_route = currentHuman;
    next.current_speaker_user_id = currentHumanId;
    next.current_speaker_name = String(currentHuman.speaker_name || currentHumanId).trim();
  } else {
    next.current_human_route = {};
    next.current_speaker_user_id = "";
    next.current_speaker_name = "";
  }

  let keepPendingBot = Boolean(pendingBotIsLive);
  let keepPendingHuman = Boolean(pendingHumanId);
  if (effectiveCurrentBot && pendingBotTarget === effectiveCurrentBot) {
    keepPendingBot = false;
  }
  if (!effectiveCurrentBot && currentHumanId && pendingHumanId === currentHumanId) {
    keepPendingHuman = false;
  }
  if (keepPendingBot && keepPendingHuman) {
    const pendingBotMs = Number(pendingBot.created_at_ms || 0);
    const pendingHumanMs = Number(pendingHuman.created_at_ms || 0);
    keepPendingHuman = pendingHumanMs > pendingBotMs;
    keepPendingBot = !keepPendingHuman;
  }

  if (keepPendingBot) {
    next.pending_route = {
      ...pendingBot,
      target_bot_id: pendingBotTarget
    };
    next.route_next_target_bot_id = pendingBotTarget;
  } else {
    next.pending_route = {};
    next.route_next_target_bot_id = "";
  }

  if (keepPendingHuman) {
    next.pending_human_route = pendingHuman;
    next.route_next_speaker_user_id = pendingHumanId;
    next.route_next_speaker_name = String(pendingHuman.speaker_name || pendingHumanId).trim();
  } else {
    next.pending_human_route = {};
    next.route_next_speaker_user_id = "";
    next.route_next_speaker_name = "";
  }

  return next;
}

function writeModeratorState(state) {
  const normalized = normalizeModeratorStateForWrite(state);
  const previous = readModeratorState();
  const now = Date.now();
  const previousCommand = String(previous?.last_command || "");
  const nextCommand = String(normalized?.last_command || "");
  const previousCommandAtMs = Number(previous?.last_command_at_ms || 0);
  const explicitCommandAtMs = Number(normalized?.last_command_at_ms || 0);
  const lastCommandAtMs = nextCommand
    ? (nextCommand !== previousCommand
        ? now
        : (Number.isFinite(explicitCommandAtMs) && explicitCommandAtMs > 0
            ? explicitCommandAtMs
            : previousCommandAtMs))
    : 0;
  const payload = {
    enabled: true,
    ...normalized,
    last_command_at_ms: lastCommandAtMs,
    updated_at: new Date().toISOString(),
    updated_at_ms: now,
    source_bot_id: botInstanceId
  };
  writeFileSync(moderatorStatePath, JSON.stringify(payload, null, 2), "utf8");
  lastModeratorState = payload;
  writeRuntimeStatus("moderator_updated");
  return payload;
}

function updateModeratorState(mutator) {
  const current = readModeratorState();
  const next = typeof mutator === "function" ? mutator(current) : current;
  return writeModeratorState(next);
}

function appendModeratorRouteFlow(decision, turn, routeKey, source) {
  const routeId = String(routeKey || decision?.route_key || "");
  const targetId = normalizeRecoveryTargetId(decision?.target_bot_id || "");
  const targetName = targetId ? recoveryTargetName(targetId) : "";
  updateModeratorState((current) => {
    const existing = Array.isArray(current?.route_flow) ? current.route_flow : [];
    if (routeId && existing.some((entry) => String(entry?.route_key || "") === routeId)) {
      return current;
    }
    const entry = {
      at_ms: Date.now(),
      captured_at: String(turn?.capturedAt || decision?.captured_at || new Date().toISOString()),
      route_key: routeId,
      source: String(source || decision?.source || decision?.router_mode || "router"),
      speaker_name: String(turn?.speakerName || decision?.speaker_name || turn?.userId || "unknown"),
      speaker_bot_id: safeFileSegment(turn?.speakerBotId || decision?.speaker_bot_id || "").toLowerCase(),
      answer: Boolean(decision?.answer),
      target_bot_id: targetId,
      target_name: targetName,
      reason: String(decision?.reason || "").trim()
    };
    return {
      ...current,
      route_flow: [...existing, entry].slice(-24)
    };
  });
}

function moderatorPendingBotRouteBlockReason(targetBotId, source = "router", state = readModeratorState()) {
  const target = safeFileSegment(targetBotId || "").toLowerCase();
  if (!target) {
    return "missing_target";
  }
  const sourceKind = String(source || "router").trim().toLowerCase();
  const currentBot = safeFileSegment(state?.current_bot_id || "").toLowerCase();
  if (currentBot === target) {
    return `target_already_current:${target}`;
  }
  if (moderatorBotTargetIsMuted(target, state)) {
    return `target_muted:${target}`;
  }
  const manualPending = moderatorManualPendingRoute(state);
  if (sourceKind !== "human_moderator" && manualPending?.target) {
    return `manual_next:${manualPending.target}`;
  }
  const humanPending = moderatorPendingHumanRoute(state);
  if (sourceKind !== "human_moderator" && (humanPending?.userId || humanPending?.name)) {
    return `manual_human_next:${humanPending.name || humanPending.userId || "unknown"}`;
  }
  return "";
}

function markModeratorPendingBotRoute(targetBotId, reason, routeKey, source = "router") {
  const target = safeFileSegment(targetBotId || "").toLowerCase();
  const sourceKind = String(source || "router").trim().toLowerCase();
  const blockReason = moderatorPendingBotRouteBlockReason(target, sourceKind);
  if (blockReason) {
    console.log(`[DiscordBridgeRouter] Pending bot route rejected by moderator state: ${blockReason}`);
    return false;
  }
  updateModeratorState((current) => ({
    ...current,
    pending_route: {
      target_bot_id: target,
      created_at_ms: Date.now(),
      route_key: String(routeKey || ""),
      source: sourceKind || "router",
      manual: sourceKind === "human_moderator",
      user_command: false,
      reason: String(reason || "router route")
    },
    route_next_target_bot_id: target,
    pending_human_route: {},
    route_next_speaker_user_id: "",
    route_next_speaker_name: "",
    last_error: ""
  }));
  return true;
}

function appendModeratorRecoveryStatus(status = {}) {
  updateModeratorState((current) => {
    const previous = current?.dead_air_recovery && typeof current.dead_air_recovery === "object"
      ? current.dead_air_recovery
      : {};
    return {
      ...current,
      dead_air_recovery: {
        ...previous,
        enabled: Boolean(deadAirRecoveryEnabled),
        updated_at_ms: Date.now(),
        ...status
      }
    };
  });
}

function appendDeadAirRecoveryFlow({ routeKey, speakerName, targetBotId, reason }) {
  const flowKey = `dead_air_${safeFileSegment(routeKey || randomUUID())}`;
  appendModeratorRouteFlow(
    {
      answer: Boolean(targetBotId),
      target_bot_id: targetBotId || "",
      reason: reason || "dead_air_recovery",
      route_key: flowKey
    },
    {
      speakerName: String(speakerName || "Moderator"),
      speakerBotId: String(speakerName || "").trim().toLowerCase() === "moderator" ? moderatorEnforcerBotId() : "",
      capturedAt: new Date().toISOString()
    },
    flowKey,
    "dead_air_recovery"
  );
}

function moderatorEnforcerBotId() {
  const state = readModeratorState();
  return safeFileSegment(state?.enforcer_bot_id || "").toLowerCase();
}

function selectedModeratorTarget() {
  const moderatorId = moderatorEnforcerBotId();
  return moderatorId ? moderatorLiveTarget(moderatorId) : null;
}

function isNoRouteDecision(decision) {
  return !decision?.answer || !safeFileSegment(decision?.target_bot_id || "").toLowerCase();
}

function isTerminalModeratorNoRoute(decision) {
  const source = String(decision?.source || decision?.router_mode || "").trim().toLowerCase();
  const reason = String(decision?.reason || "").trim().toLowerCase();
  return Boolean(
    source === "human_moderator"
    && (
      reason === "human_moderator_speaker_lock_self"
      || reason === "moderator_muted"
      || reason.startsWith("human_moderator_waiting_for_")
      || reason.startsWith("moderator_override:")
    )
  );
}

function deadAirTriggerAllowsTurn(turn) {
  if (turn?.silenceTimeoutRecovery) {
    return true;
  }
  const mode = String(deadAirRecoveryTriggerMode || "no_route_after_bot_speech").toLowerCase();
  if (mode === "no_route_after_any_speech") {
    return true;
  }
  return Boolean(turn?.speakerBotId || turn?.speakerIsBot);
}

function eligibleRecoveryParticipants(turn, moderatorId = "") {
  const speakerBotId = safeFileSegment(turn?.speakerBotId || "").toLowerCase();
  const speakerUserId = String(turn?.userId || "").trim();
  const muted = moderatorMutedBotIds();
  const currentState = readModeratorState();
  const only = new Set(moderatorBotIds(currentState?.only_bot_ids));
  const mutedHumans = new Set((Array.isArray(currentState?.muted_speaker_user_ids) ? currentState.muted_speaker_user_ids : [])
    .map((value) => String(value || "").trim())
    .filter(Boolean));
  const bots = liveRoomRouterCandidateBots().map((candidate) => ({
    kind: "bot",
    id: safeFileSegment(candidate?.id || candidate?.name || "").toLowerCase(),
    name: String(candidate?.name || candidate?.id || "").trim()
  })).filter((candidate) => {
    const candidateId = safeFileSegment(candidate?.id || candidate?.name || "").toLowerCase();
    if (!candidateId) {
      return false;
    }
    if (candidateId === speakerBotId || candidateId === moderatorId) {
      return false;
    }
    if (muted.has(candidateId)) {
      return false;
    }
    if (only.size > 0 && !only.has(candidateId)) {
      return false;
    }
    return Boolean(moderatorLiveTarget(candidateId));
  });
  const humans = currentParticipantSnapshot()
    .filter((participant) => !participant.is_bot && !participant.display_name_conflict)
    .map((participant) => ({
      kind: "human",
      id: `human:${String(participant.id || "").trim()}`,
      userId: String(participant.id || "").trim(),
      name: String(participant.name || participant.id || "").trim()
    }))
    .filter((participant) => (
      participant.userId
      && participant.userId !== speakerUserId
      && !mutedHumans.has(participant.userId)
      && moderatorHumanCandidateAllowed(participant.userId, currentState)
    ));
  return [...bots, ...humans];
}

function eligibleRecoveryTargets(turn, moderatorId = "") {
  return eligibleRecoveryParticipants(turn, moderatorId).map((participant) => participant.id).filter(Boolean);
}

function escapeRegExpLiteral(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function humanTargetFromNoRoute(decision, turn, moderatorId = "") {
  const reason = String(decision?.reason || "").trim();
  const combined = [
    reason,
    String(turn?.inputText || ""),
    String(decision?.input_text || ""),
    String(decision?.context_input_text || "")
  ].filter(Boolean).join("\n");
  if (!combined) {
    return "";
  }
  const loweredReason = reason.toLowerCase();
  const genericHumanRoomTalk = (
    /\bhuman-to-human\b/.test(loweredReason)
    || /\broom talk\b/.test(loweredReason)
    || /\bno bot(?: is)? addressed\b/.test(loweredReason)
    || /\bno specific bot\b/.test(loweredReason)
    || /\bnot a specific bot\b/.test(loweredReason)
  );
  const reasonLooksHumanDirected = !genericHumanRoomTalk && (
    /\baddress(?:es|ed|ing)? (?:the )?(?:human|user|participant)\b/i.test(loweredReason)
    || /\brespond(?:s|ed|ing)? to (?:the )?(?:human|user|participant)\b/i.test(loweredReason)
    || /\bask(?:s|ed|ing)? (?:the )?(?:human|user|participant)\b/i.test(loweredReason)
    || /\brequest(?:s|ed|ing)? (?:input|response|reply|answer) from (?:the )?(?:human|user|participant)\b/i.test(loweredReason)
  );
  const humans = eligibleRecoveryParticipants(turn, moderatorId).filter((participant) => participant.kind === "human");
  for (const human of humans) {
    const name = String(human.name || "").trim();
    const userId = String(human.userId || "").trim();
    const nameMatched = Boolean(name && new RegExp(`(^|[^\\p{L}\\p{N}_])${escapeRegExpLiteral(name)}([^\\p{L}\\p{N}_]|$)`, "iu").test(combined));
    const idMatched = Boolean(userId && combined.includes(userId));
    if (nameMatched || idMatched) {
      return human.id;
    }
  }
  if (reasonLooksHumanDirected && humans.length === 1) {
    return humans[0].id;
  }
  return "";
}

function decisionWithHumanFloorIfNeeded(decision, turn, moderatorId = "") {
  if (decision?.moderator_override) {
    return decision;
  }
  if (!isNoRouteDecision(decision)) {
    return decision;
  }
  if (isTerminalModeratorNoRoute(decision)) {
    return decision;
  }
  const humanTarget = humanTargetFromNoRoute(decision, turn, moderatorId);
  if (!humanTarget) {
    return decision;
  }
  return {
    ...decision,
    answer: true,
    target_bot_id: humanTarget,
    reason: `human_floor:${String(decision?.reason || "addressed human participant")}`
  };
}

function roundRobinRecoveryTarget(turn, moderatorId = "") {
  const candidates = eligibleRecoveryParticipants(turn, moderatorId);
  if (!candidates.length) {
    return "";
  }
  const speakerBotId = safeFileSegment(turn?.speakerBotId || "").toLowerCase();
  const allIds = [
    ...liveRoomRouterCandidateBots().map((candidate) => safeFileSegment(candidate?.id || candidate?.name || "").toLowerCase()),
    ...currentParticipantSnapshot().filter((participant) => !participant.is_bot).map((participant) => `human:${String(participant.id || "").trim()}`)
  ].filter(Boolean);
  const candidateIds = candidates.map((candidate) => candidate.id);
  const startIndex = Math.max(0, allIds.indexOf(speakerBotId));
  for (let offset = 1; offset <= allIds.length; offset += 1) {
    const nextId = allIds[(startIndex + offset) % allIds.length];
    if (candidateIds.includes(nextId)) {
      return nextId;
    }
  }
  return candidateIds[0] || "";
}

async function chooseDeadAirRecoveryTarget(turn, routeKey, moderatorId, decision = null) {
  const humanTarget = humanTargetFromNoRoute(decision || turn?.roomRouterDecision, turn, moderatorId);
  if (humanTarget) {
    return humanTarget;
  }
  const strategy = String(deadAirRecoveryNextSpeakerStrategy || "llm_choose").toLowerCase();
  if (strategy === "selected_fallback") {
    const fallback = normalizeRecoveryTargetId(deadAirRecoveryFallbackTarget || "");
    return eligibleRecoveryTargets(turn, moderatorId).includes(fallback)
      ? fallback
      : roundRobinRecoveryTarget(turn, moderatorId);
  }
  if (strategy === "round_robin") {
    return roundRobinRecoveryTarget(turn, moderatorId);
  }
  try {
    const speaker = String(turn?.speakerName || turn?.speakerBotId || "previous speaker").trim();
    const prompt = [
      "The moderated Discord debate reached dead air because the latest completed turn did not select a next speaker.",
      `Previous speaker: ${speaker}.`,
      "Choose the single best next NC bot participant to continue the debate.",
      "Do not choose the Moderator bot unless no other eligible participant exists."
    ].join(" ");
    const decision = await requestRoomRouteDecision(
      {
        userId: "dead_air_recovery",
        speakerName: "Moderator",
        speakerBotId: moderatorId,
        speakerIsBot: true,
        inputText: prompt,
        durationSeconds: 0,
        capturedAt: new Date().toISOString()
      },
      `dead_air_choose_${safeFileSegment(routeKey || Date.now())}_${randomUUID()}`
    );
    const target = normalizeRecoveryTargetId(decision?.target_bot_id || "");
    if (decision?.answer && target && eligibleRecoveryTargets(turn, moderatorId).includes(target)) {
      return target;
    }
    appendModeratorRecoveryStatus({
      last_reason: `llm_choose_no_target:${decision?.reason || "no valid target"}`,
      last_error: ""
    });
  } catch (error) {
    appendModeratorRecoveryStatus({
      last_error: String(error?.message || error || "LLM next-speaker choice failed")
    });
  }
  return roundRobinRecoveryTarget(turn, moderatorId);
}

async function maybeQueueDeadAirRecovery(decision, turn, routeKey, source, options = {}) {
  if (isProtectedMicContextOnlyDecision(decision)) {
    appendModeratorRecoveryStatus({
      last_reason: "current_speaker_protected",
      cooldown_remaining_ms: 0,
      last_error: ""
    });
    return false;
  }
  if (decision?.moderator_override) {
    appendModeratorRecoveryStatus({
      last_reason: String(decision?.reason || "moderator_override"),
      cooldown_remaining_ms: 0,
      last_error: ""
    });
    return false;
  }
  if (isTerminalModeratorNoRoute(decision)) {
    appendModeratorRecoveryStatus({
      last_reason: String(decision?.reason || "terminal_moderator_no_route"),
      cooldown_remaining_ms: 0,
      last_error: ""
    });
    return false;
  }
  if (!deadAirRecoveryEnabled || !shouldUseRoomRouter() || !isNoRouteDecision(decision) || !deadAirTriggerAllowsTurn(turn)) {
    return false;
  }
  if (turn?.deadAirRecovery || turn?.speakerBotId === moderatorEnforcerBotId()) {
    appendModeratorRecoveryStatus({
      last_reason: "skipped_self_or_recovery_turn",
      cooldown_remaining_ms: 0,
      last_error: ""
    });
    return false;
  }
  const moderatorTarget = selectedModeratorTarget();
  const moderatorId = safeFileSegment(moderatorTarget?.id || moderatorTarget?.name || moderatorEnforcerBotId()).toLowerCase();
  if (!moderatorId) {
    appendModeratorRecoveryStatus({
      last_reason: "disabled_no_moderator",
      cooldown_remaining_ms: 0,
      last_error: "No active Moderator bot selected."
    });
    return false;
  }
  const state = readModeratorState();
  if (moderatorBotTargetIsMuted(moderatorId, state)) {
    appendModeratorRecoveryStatus({
      last_reason: "disabled_moderator_muted",
      cooldown_remaining_ms: 0,
      last_error: "The selected Moderator bot is muted or excluded by moderator floor control."
    });
    return false;
  }
  if (moderatorHasCurrentOrPendingSpeaker(state)) {
    const allowActiveCurrent = Boolean(options.allowActiveCompletedCurrent);
    const currentBot = safeFileSegment(state?.current_bot_id || "").toLowerCase();
    const currentTurnId = String(state?.current_bot_turn_id || "");
    const activeTurnId = String(options.activeTurnId || "");
    const canPrebufferAfterCurrent = Boolean(
      allowActiveCurrent
      && currentBot
      && currentBot === botInstanceId
      && !moderatorPendingBotRoute(state)
      && !moderatorPendingHumanRoute(state)
      && (!currentTurnId || !activeTurnId || currentTurnId === activeTurnId)
    );
    if (canPrebufferAfterCurrent) {
      appendModeratorRecoveryStatus({
        last_reason: "prebuffering_after_current_speaker",
        cooldown_remaining_ms: 0,
        last_error: ""
      });
    } else {
      appendModeratorRecoveryStatus({
        last_reason: "speaker_control_active",
        cooldown_remaining_ms: 0,
        last_error: ""
      });
      return false;
    }
  }
  const previousRecovery = state?.dead_air_recovery && typeof state.dead_air_recovery === "object"
    ? state.dead_air_recovery
    : {};
  const lastAt = Number(previousRecovery.last_recovery_at_ms || 0);
  const remainingMs = deadAirRecoveryCooldownMs > 0 ? Math.max(0, deadAirRecoveryCooldownMs - (Date.now() - lastAt)) : 0;
  if (remainingMs > 0) {
    appendModeratorRecoveryStatus({
      last_reason: "cooldown",
      cooldown_remaining_ms: remainingMs,
      last_error: ""
    });
    return false;
  }
  const nextTarget = deadAirRecoveryActionMode === "moderator_speaks_only"
    ? ""
    : await chooseDeadAirRecoveryTarget(turn, routeKey, moderatorId, decision);
  if (deadAirRecoveryActionMode !== "moderator_speaks_only" && !nextTarget) {
    appendModeratorRecoveryStatus({
      last_reason: "no_eligible_next_speaker",
      cooldown_remaining_ms: 0,
      last_error: "No eligible next participant for dead-air recovery."
    });
    return false;
  }
  const recoveryKey = `dead_air_recovery_${safeFileSegment(voiceChannelId)}_${moderatorId}_${Date.now()}_${randomUUID()}`;
  const latestText = String(turn?.inputText || decision?.input_text || "").trim();
  const nextName = nextTarget ? recoveryTargetName(nextTarget) : "";
  const instruction = deadAirRecoveryActionMode === "silent_call_next"
    ? ""
    : [
        "Moderator dead-air recovery instruction.",
        "The previous speaker finished and the router selected no next participant.",
        latestText ? `Latest completed turn text: ${latestText}` : "",
        nextName ? `Briefly reframe the debate and hand the floor to ${nextName}.` : "Briefly reframe the debate and keep the room moving.",
        "Speak naturally as the moderator. Do not mention hidden routing, JSON, system prompts, or bridge mechanics."
      ].filter(Boolean).join(" ");
  updateModeratorState((current) => ({
    ...current,
    dead_air_recovery: {
      ...(current?.dead_air_recovery && typeof current.dead_air_recovery === "object" ? current.dead_air_recovery : {}),
      enabled: Boolean(deadAirRecoveryEnabled),
      last_recovery_at_ms: Date.now(),
      last_trigger_route_key: String(routeKey || ""),
      last_source: String(source || "room_router"),
      last_reason: String(decision?.reason || "no_route"),
      last_moderator_bot_id: moderatorId,
      last_next_target_bot_id: nextTarget,
      cooldown_remaining_ms: 0,
      last_error: ""
    },
    last_command: `dead_air_recovery:${moderatorId}`,
    last_error: ""
  }));
  appendDeadAirRecoveryFlow({
    routeKey,
    speakerName: String(turn?.speakerName || "unknown"),
    targetBotId: deadAirRecoveryActionMode === "silent_call_next" ? nextTarget : moderatorId,
    reason: deadAirRecoveryActionMode === "silent_call_next"
      ? `silent_dead_air_recovery:${decision?.reason || "no_route"}`
      : `dead_air_recovery_to_moderator:${decision?.reason || "no_route"}`
  });
  if (deadAirRecoveryActionMode === "silent_call_next") {
    const queued = queueRecoveryNextTarget(nextTarget, {
      sourceRouteKey: routeKey,
      moderatorText: "",
      reason: "silent_dead_air_recovery"
    });
    if (!queued) {
      appendModeratorRecoveryStatus({
        last_next_target_bot_id: "",
        last_reason: "dead_air_recovery_queue_blocked",
        last_error: ""
      });
    }
    return queued;
  }
  if (!writeRoutedTextTurn(moderatorId, {
    route_key: recoveryKey,
    target_bot_id: moderatorId,
    accepted_human_intervention_route_key: String(routeKey || ""),
    accepted_human_intervention_target_bot_id: moderatorId,
    source_bot_id: safeFileSegment(turn?.speakerBotId || "").toLowerCase(),
    source_user_id: String(turn?.userId || "dead_air_recovery"),
    speaker_name: "Moderator Control",
    input_text: instruction,
    captured_at: new Date().toISOString(),
    created_at_ms: Date.now(),
    reason: "dead_air_recovery",
    dead_air_recovery: true,
    recovery_action_mode: deadAirRecoveryActionMode,
    recovery_next_target_bot_id: nextTarget,
    decision: {
      answer: true,
      target_bot_id: moderatorId,
      reason: "dead_air_recovery"
    }
  })) {
    appendModeratorRecoveryStatus({
      last_next_target_bot_id: "",
      last_reason: "dead_air_recovery_queue_blocked",
      last_error: ""
    });
    return false;
  }
  return true;
}

async function maybeQueueSilenceTimeoutRecovery() {
  if (
    !deadAirRecoveryEnabled
    || deadAirRecoverySilenceTimeoutMs <= 0
    || !shouldUseRoomRouter()
    || !isCaptureOwner()
    || !isRoomQuietForRecovery()
  ) {
    return false;
  }
  const quietForMs = Date.now() - lastRoomActivityAtMs;
  if (quietForMs < deadAirRecoverySilenceTimeoutMs) {
    return false;
  }
  if (lastSilenceRecoveryActivityAtMs === lastRoomActivityAtMs) {
    return false;
  }
  lastSilenceRecoveryActivityAtMs = lastRoomActivityAtMs;
  const quietSeconds = Math.max(0, quietForMs / 1000);
  const routeKey = `silence_timeout_${safeFileSegment(voiceChannelId)}_${Math.floor(lastRoomActivityAtMs / 1000)}`;
  const turn = {
    userId: "silence_timeout",
    speakerName: "Room silence",
    speakerIsBot: false,
    inputText: `The room has been quiet for ${quietSeconds.toFixed(1)} seconds.`,
    durationSeconds: quietSeconds,
    capturedAt: new Date().toISOString(),
    silenceTimeoutRecovery: true
  };
  const decision = {
    ok: true,
    answer: false,
    target_bot_id: "",
    reason: `silence_timeout:${quietSeconds.toFixed(1)}s`,
    route_key: routeKey,
    input_text: turn.inputText,
    context_input_text: turn.inputText,
    speech_accepted: false,
    source: "silence_timeout"
  };
  console.log(`[DiscordBridgeModerator] Room quiet for ${quietSeconds.toFixed(1)}s; queueing dead-air recovery.`);
  return maybeQueueDeadAirRecovery(decision, turn, routeKey, "silence_timeout");
}

function noteRoomActivity(_reason = "") {
  lastRoomActivityAtMs = Date.now();
}

function isRoomQuietForRecovery() {
  if (moderatorHasCurrentOrPendingSpeaker()) {
    return false;
  }
  if (activeCaptures.size > 0 || activeHumanSpeechMonitors.size > 0 || routedTextInProgress.size > 0) {
    return false;
  }
  if (playbackActive || currentPlaybackItem || playbackQueue.length > 0) {
    return false;
  }
  if (activeNcTurnId || activeNcAbortController) {
    return false;
  }
  const floor = readReplyFloor();
  if (floor && isReplyFloorFresh(floor)) {
    return false;
  }
  return true;
}

function recoveryTargetName(targetBotId) {
  const target = normalizeRecoveryTargetId(targetBotId);
  if (target.startsWith("human:")) {
    const userId = target.slice("human:".length);
    const participant = currentParticipantSnapshot().find((item) => !item.is_bot && String(item.id || "") === userId);
    return String(participant?.name || userId || "").trim();
  }
  const candidate = liveRoomRouterCandidateBots().find((item) => safeFileSegment(item?.id || item?.name || "").toLowerCase() === target);
  return String(candidate?.name || candidate?.id || target || "").trim();
}

function queueRecoveryNextTarget(targetBotId, options = {}) {
  const target = normalizeRecoveryTargetId(targetBotId);
  if (target.startsWith("human:")) {
    return setRecoveryHumanCurrent(target, options);
  }
  if (!target || !moderatorLiveTarget(target) || moderatorMutedBotIds().has(target)) {
    appendModeratorRecoveryStatus({
      last_error: `Recovery target ${target || "(none)"} is not eligible.`
    });
    return false;
  }
  const routeKey = `dead_air_next_${safeFileSegment(voiceChannelId)}_${target}_${Date.now()}_${randomUUID()}`;
  const moderatorText = String(options?.moderatorText || "").trim();
  const inputText = moderatorText
    ? "The moderator has handed you the floor. Continue from the latest shared room context."
    : "The moderator has handed you the floor. Continue the debate from your perspective.";
  if (!writeRoutedTextTurn(target, {
    route_key: routeKey,
    target_bot_id: target,
    accepted_human_intervention_route_key: String(options?.sourceRouteKey || ""),
    accepted_human_intervention_target_bot_id: target,
    source_bot_id: moderatorEnforcerBotId(),
    source_user_id: "dead_air_recovery",
    speaker_name: "Moderator",
    input_text: inputText,
    captured_at: new Date().toISOString(),
    created_at_ms: Date.now(),
    reason: String(options?.reason || "dead_air_recovery_next"),
    decision: {
      answer: true,
      target_bot_id: target,
      reason: String(options?.reason || "dead_air_recovery_next")
    }
  })) {
    return false;
  }
  appendDeadAirRecoveryFlow({
    routeKey,
    speakerName: "Moderator",
    targetBotId: target,
    reason: String(options?.reason || "dead_air_recovery_next")
  });
  appendModeratorRecoveryStatus({
    last_next_target_bot_id: target,
    last_error: ""
  });
  return true;
}

function normalizeRecoveryTargetId(value) {
  const raw = String(value || "").trim();
  if (raw.toLowerCase().startsWith("human:")) {
    const userId = raw.slice(raw.indexOf(":") + 1).trim();
    return userId ? `human:${userId}` : "";
  }
  if (/^human_[a-zA-Z0-9_.-]+$/i.test(raw)) {
    const userId = raw.slice(raw.indexOf("_") + 1).trim();
    return userId ? `human:${userId}` : "";
  }
  return safeFileSegment(raw).toLowerCase();
}

function moderatorPendingBotRoute(state = readModeratorState()) {
  const pending = state?.pending_route && typeof state.pending_route === "object" ? state.pending_route : {};
  const target = safeFileSegment(pending?.target_bot_id || "").toLowerCase();
  if (!target || !moderatorLiveTarget(target)) {
    return null;
  }
  return {
    target,
    reason: String(pending?.reason || "moderator route"),
    routeKey: String(pending?.route_key || ""),
    source: String(pending?.source || ""),
    manual: Boolean(pending?.manual),
    createdAtMs: Number(pending?.created_at_ms || 0)
  };
}

function setHumanCurrentFromRoute(target, options = {}) {
  const userId = String(target || "").replace(/^human:/i, "").trim();
  const participant = currentParticipantSnapshot().find((item) => !item.is_bot && String(item.id || "") === userId);
  const stateBefore = readModeratorState();
  const allowedHuman = moderatorHumanCandidateAllowed(userId, stateBefore);
  if (!participant || moderatorHumanMuted(userId) || !allowedHuman) {
    appendModeratorRecoveryStatus({
      last_error: `Human route target ${userId || "(none)"} is not eligible.`
    });
    return false;
  }
  if (participant.display_name_conflict) {
    appendModeratorRecoveryStatus({
      last_error: `Human route target ${participant.name || userId} has a duplicate display name. Rename or alias the participant before routing.`
    });
    return false;
  }
  const speakerName = String(participant.name || userId).trim();
  const reason = String(options?.reason || "human_route");
  const currentHumanBefore = moderatorCurrentHumanRoute(stateBefore);
  const botOwnsCurrent = Boolean(hasActiveBotPlayback() || moderatorHasCurrentBot(stateBefore));
  if (currentHumanBefore?.userId === userId && !botOwnsCurrent) {
    updateModeratorState((current) => ({
      ...current,
      pending_human_route: {},
      route_next_speaker_user_id: "",
      route_next_speaker_name: "",
      pending_route: {},
      route_next_target_bot_id: "",
      last_command: `current_human:${speakerName}`,
      last_error: ""
    }));
    console.log(`[DiscordBridgeModerator] Human speaker is already current: ${speakerName} (${userId}) reason=${reason}`);
    return true;
  }
  const makePending = Boolean(
    options?.forcePending
    || (
      options?.allowPending !== false
      && (
        hasActiveBotPlayback()
        || moderatorHasCurrentBot(stateBefore)
        || Boolean(moderatorCurrentHumanRoute(stateBefore))
      )
    )
  );
  updateModeratorState((current) => ({
    ...current,
    ...(makePending
      ? {
          pending_human_route: {
            speaker_user_id: userId,
            speaker_name: speakerName,
            created_at_ms: Date.now(),
            reason
          },
          route_next_speaker_user_id: userId,
          route_next_speaker_name: speakerName,
          ...(botOwnsCurrent
            ? {
                current_human_route: {},
                current_speaker_user_id: "",
                current_speaker_name: ""
              }
            : {})
        }
      : {
          current_human_route: {
            speaker_user_id: userId,
            speaker_name: speakerName,
            created_at_ms: Date.now(),
            reason
          },
          current_speaker_user_id: userId,
          current_speaker_name: speakerName,
          pending_human_route: {},
          route_next_speaker_user_id: "",
          route_next_speaker_name: ""
        }),
    pending_route: {},
    route_next_target_bot_id: "",
    last_command: `${makePending ? "route_next_human" : String(options?.commandPrefix || "current_human")}:${speakerName}`,
    last_error: ""
  }));
  console.log(`[DiscordBridgeModerator] Human speaker ${makePending ? "queued next" : "is now current"}: ${speakerName} (${userId}) reason=${reason}`);
  applyDiscordMuteEnforcement(String(options?.muteReason || "human_route")).catch((error) => {
    console.warn(`[DiscordBridgeModerator] Could not update Discord mutes after human route: ${error?.message || error}`);
  });
  return true;
}

function setRecoveryHumanCurrent(target, options = {}) {
  const userId = String(target || "").replace(/^human:/i, "").trim();
  if (!setHumanCurrentFromRoute(target, {
    ...options,
    reason: String(options?.reason || "dead_air_recovery_next_human"),
    commandPrefix: "dead_air_current_human",
    muteReason: "dead_air_recovery_human"
  })) {
    return false;
  }
  updateModeratorState((current) => ({
    ...current,
    dead_air_recovery: {
      ...(current?.dead_air_recovery && typeof current.dead_air_recovery === "object" ? current.dead_air_recovery : {}),
      last_next_target_bot_id: target,
      last_error: ""
    }
  }));
  appendDeadAirRecoveryFlow({
    routeKey: `dead_air_human_${safeFileSegment(userId)}_${Date.now()}`,
    speakerName: "Moderator",
    targetBotId: target,
    reason: "dead_air_recovery_next_human"
  });
  return true;
}

function moderatorBotIds(value) {
  if (Array.isArray(value)) {
    return value.map((item) => safeFileSegment(item || "").toLowerCase()).filter(Boolean);
  }
  return String(value || "")
    .split(/[,\n| ]+/g)
    .map((item) => safeFileSegment(item || "").toLowerCase())
    .filter(Boolean);
}

function moderatorLiveTarget(targetBotId) {
  const target = safeFileSegment(targetBotId || "").toLowerCase();
  if (!target || target === "default") {
    return null;
  }
  return liveRoomRouterCandidateBots().find((candidate) => {
    const candidateId = safeFileSegment(candidate?.id || candidate?.name || "").toLowerCase();
    return candidateId === target;
  }) || null;
}

function moderatorLiveHuman(userId) {
  const target = String(userId || "").trim();
  if (!target) {
    return null;
  }
  return currentParticipantSnapshot().find((participant) => (
    !participant.is_bot && String(participant.id || "") === target
  )) || null;
}

function moderatorHumanFloor(state = readModeratorState()) {
  const speakerUserId = String(state?.floor_speaker_user_id || "").trim();
  if (!speakerUserId) {
    return null;
  }
  return {
    userId: speakerUserId,
    name: String(state?.floor_speaker_name || speakerUserId).trim()
  };
}

function moderatorHumanCandidateAllowed(userId, state = readModeratorState()) {
  const target = String(userId || "").trim();
  if (!target) {
    return false;
  }
  const floor = moderatorHumanFloor(state);
  if (floor && floor.userId !== target) {
    return false;
  }
  return !moderatorHumanMuted(target, state);
}

function moderatorPendingHumanRoute(state = readModeratorState()) {
  const pending = state?.pending_human_route && typeof state.pending_human_route === "object"
    ? state.pending_human_route
    : {};
  const speakerUserId = String(pending?.speaker_user_id || "").trim();
  if (!speakerUserId) {
    return null;
  }
  return {
    userId: speakerUserId,
    name: String(pending?.speaker_name || speakerUserId).trim(),
    reason: String(pending?.reason || "manual moderator route"),
    createdAtMs: Number(pending?.created_at_ms || 0)
  };
}

function moderatorCurrentHumanRoute(state = readModeratorState()) {
  const current = state?.current_human_route && typeof state.current_human_route === "object"
    ? state.current_human_route
    : {};
  const speakerUserId = String(current?.speaker_user_id || "").trim();
  if (!speakerUserId) {
    return null;
  }
  return {
    userId: speakerUserId,
    name: String(current?.speaker_name || speakerUserId).trim(),
    reason: String(current?.reason || "manual moderator floor"),
    createdAtMs: Number(current?.created_at_ms || 0)
  };
}

function moderatorAllowsHumanSpeaker(userId, state = readModeratorState()) {
  if (moderatorHumanMuted(userId, state)) {
    return false;
  }
  if (moderatorProtectsCurrentSpeaker(state)) {
    return false;
  }
  const current = moderatorCurrentHumanRoute(state);
  if (current) {
    return String(userId || "").trim() === current.userId;
  }
  const pending = moderatorPendingHumanRoute(state);
  if (pending) {
    return String(userId || "").trim() === pending.userId;
  }
  const floor = moderatorHumanFloor(state);
  if (!floor) {
    return true;
  }
  return String(userId || "").trim() === floor.userId;
}

function moderatorHumanMuted(userId, state = readModeratorState()) {
  const muted = new Set((Array.isArray(state?.muted_speaker_user_ids) ? state.muted_speaker_user_ids : [])
    .map((value) => String(value || "").trim())
    .filter(Boolean));
  return muted.has(String(userId || "").trim());
}

function moderatorAllowsCurrentInterruption(state = readModeratorState()) {
  return Boolean(state?.allow_current_interruption);
}

function isModeratorEnforcer(state = readModeratorState()) {
  return safeFileSegment(state?.enforcer_bot_id || "").toLowerCase() === botInstanceId;
}

function moderatorCurrentSpeakerUserId(state = readModeratorState()) {
  const currentHuman = moderatorCurrentHumanRoute(state);
  if (currentHuman?.userId) {
    return String(currentHuman.userId);
  }
  const botUserId = String(state?.current_bot_discord_user_id || "").trim();
  if (botUserId) {
    return botUserId;
  }
  return "";
}

function discordMuteLedger(state = readModeratorState()) {
  return new Set((Array.isArray(state?.discord_muted_user_ids) ? state.discord_muted_user_ids : [])
    .map((value) => String(value || "").trim())
    .filter(Boolean));
}

async function clearDiscordMuteLedger(reason) {
  const state = readModeratorState();
  const ledger = discordMuteLedger(state);
  if (!ledger.size || !activeVoiceChannel?.members) {
    return;
  }
  const stillMuted = new Set();
  for (const userId of ledger) {
    const member = activeVoiceChannel.members.get(String(userId));
    if (!member?.voice) {
      continue;
    }
    try {
      if (member.voice.serverMute) {
        await member.voice.setMute(false, `Neural Companion moderator release: ${reason || "clear"}`);
      }
      console.log(`[DiscordBridgeModerator] Discord unmuted ${member.displayName || userId} (${reason || "clear"}).`);
    } catch (error) {
      stillMuted.add(String(userId));
      lastErrorText = `Could not unmute ${member.displayName || userId}: ${error?.message || error}`;
      console.warn(`[DiscordBridgeModerator] ${lastErrorText}`);
    }
  }
  updateModeratorState((current) => ({
    ...current,
    discord_muted_user_ids: [...stillMuted],
    last_error: stillMuted.size ? lastErrorText : ""
  }));
}

async function applyDiscordMuteEnforcement(reason) {
  if (moderatorMuteEnforcementPromise) {
    moderatorMuteEnforcementRerunReason = String(reason || "queued_mute_enforcement");
    await moderatorMuteEnforcementPromise;
    return;
  }
  moderatorMuteEnforcementPromise = (async () => {
    let activeReason = String(reason || "enforce");
    try {
      do {
        moderatorMuteEnforcementRerunReason = "";
        await runDiscordMuteEnforcement(activeReason);
        activeReason = moderatorMuteEnforcementRerunReason;
      } while (activeReason);
    } finally {
      moderatorMuteEnforcementPromise = null;
    }
  })();
  await moderatorMuteEnforcementPromise;
}

async function runDiscordMuteEnforcement(reason) {
  const state = readModeratorState();
  if (!isModeratorEnforcer(state) || !state?.enforce_discord_mute) {
    return;
  }
  if (!activeVoiceChannel?.members) {
    updateModeratorState((current) => ({
      ...current,
      last_error: "Moderator bot is not connected to a Discord voice channel."
    }));
    return;
  }
  const currentUserId = moderatorCurrentSpeakerUserId(state);
  if (!currentUserId) {
    await clearDiscordMuteLedger(`no current speaker:${reason || "idle"}`);
    return;
  }
  const selfUserId = String(client.user?.id || "");
  const previousLedger = discordMuteLedger(state);
  const nextLedger = new Set();
  const errors = [];
  const currentMember = activeVoiceChannel.members.get(String(currentUserId));
  if (
    currentMember?.voice
    && previousLedger.has(String(currentUserId))
    && currentMember.voice.serverMute
  ) {
    try {
      await currentMember.voice.setMute(false, `Neural Companion moderator current speaker: ${reason || "enforce"}`);
      console.log(`[DiscordBridgeModerator] Discord unmuted current speaker ${currentMember.displayName || currentUserId}.`);
    } catch (error) {
      const errorText = `Discord mute enforcement failed for ${currentMember.displayName || currentUserId}: ${error?.message || error}`;
      errors.push(errorText);
      console.warn(`[DiscordBridgeModerator] ${errorText}`);
      nextLedger.add(String(currentUserId));
    }
  }
  const muteTasks = [];
  for (const member of activeVoiceChannel.members.values()) {
    const userId = String(member?.id || "");
    if (!userId || userId === selfUserId || userId === currentUserId) {
      continue;
    }
    const wasMutedByNc = previousLedger.has(userId);
    muteTasks.push((async () => {
      try {
        if (!member.voice?.serverMute) {
          await member.voice.setMute(true, `Neural Companion moderator current speaker: ${reason || "enforce"}`);
          console.log(`[DiscordBridgeModerator] Discord muted ${member.displayName || userId}; current=${currentUserId}.`);
        }
        nextLedger.add(userId);
      } catch (error) {
        const errorText = `Discord mute enforcement failed for ${member.displayName || userId}: ${error?.message || error}`;
        errors.push(errorText);
        console.warn(`[DiscordBridgeModerator] ${errorText}`);
        if (wasMutedByNc) {
          nextLedger.add(userId);
        }
      }
    })());
  }
  await Promise.allSettled(muteTasks);
  updateModeratorState((current) => ({
    ...current,
    discord_muted_user_ids: [...nextLedger],
    last_error: errors[0] || ""
  }));
}

async function watchModeratorMuteEnforcement() {
  const state = readModeratorState();
  if (!isModeratorEnforcer(state)) {
    return;
  }
  const ledger = [...discordMuteLedger(state)].sort().join(",");
  const currentUserId = moderatorCurrentSpeakerUserId(state);
  const key = [
    String(state?.enforcer_bot_id || ""),
    String(state?.enforce_discord_mute ? "1" : "0"),
    currentUserId,
    ledger
  ].join("|");
  if (key === lastModeratorMuteEnforcementKey) {
    return;
  }
  lastModeratorMuteEnforcementKey = key;
  if (state?.enforce_discord_mute) {
    await applyDiscordMuteEnforcement("moderator_state_watch");
  } else if (ledger) {
    await clearDiscordMuteLedger("moderator_state_watch_disabled");
  }
}

function moderatorHasFloorControl(state = readModeratorState()) {
  if (!state || state.enabled === false) {
    return false;
  }
  return Boolean(
    moderatorCurrentHumanRoute(state)
    || moderatorConcreteBotRouteId(state?.current_bot_id)
    || moderatorPendingHumanRoute(state)
    || moderatorConcreteBotRouteId(state?.pending_route?.target_bot_id)
    || moderatorConcreteBotRouteId(state?.floor_target_bot_id)
    || String(state?.floor_speaker_user_id || "").trim()
    || (Array.isArray(state?.only_bot_ids) && state.only_bot_ids.length > 0)
  );
}

function moderatorConcreteBotRouteId(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const target = safeFileSegment(raw).toLowerCase();
  return ["auto", "default", "none", "room"].includes(target) ? "" : target;
}

function moderatorHasProtectedCurrentSpeaker(state = readModeratorState()) {
  if (!state || state.enabled === false) {
    return false;
  }
  return Boolean(
    moderatorCurrentHumanRoute(state)
    || moderatorConcreteBotRouteId(state?.current_bot_id)
    || moderatorPendingHumanRoute(state)
    || moderatorConcreteBotRouteId(state?.pending_route?.target_bot_id)
    || moderatorConcreteBotRouteId(state?.floor_target_bot_id)
    || String(state?.floor_speaker_user_id || "").trim()
  );
}

function moderatorHasRoutedSpeakerFlow(state = readModeratorState()) {
  return Boolean(
    moderatorCurrentHumanRoute(state)
    || moderatorConcreteBotRouteId(state?.current_bot_id)
    || moderatorPendingHumanRoute(state)
    || moderatorConcreteBotRouteId(state?.pending_route?.target_bot_id)
    || moderatorConcreteBotRouteId(state?.floor_target_bot_id)
    || String(state?.floor_speaker_user_id || "").trim()
  );
}

function moderatorProtectsCurrentSpeaker(state = readModeratorState()) {
  return Boolean(
    state?.enabled !== false
    && !moderatorAllowsCurrentInterruption(state)
    && hasActiveBotPlayback()
    && moderatorHasProtectedCurrentSpeaker(state)
  );
}

function moderatorProtectsRoutingFlow(state = readModeratorState()) {
  return Boolean(
    !moderatorAllowsCurrentInterruption(state)
    && moderatorHasRoutedSpeakerFlow(state)
  );
}

function turnIsCurrentOrPendingHumanSpeaker(turn, state = readModeratorState()) {
  const userId = String(turn?.userId || "").trim();
  if (!userId) {
    return false;
  }
  const current = moderatorCurrentHumanRoute(state);
  if (current?.userId && current.userId === userId) {
    return true;
  }
  const pending = moderatorPendingHumanRoute(state);
  if (pending?.userId && pending.userId === userId) {
    return true;
  }
  return String(state?.floor_speaker_user_id || "").trim() === userId;
}

function shouldRecordProtectedMicContext(turn, state = readModeratorState()) {
  return Boolean(
    routeProtectedMicSpeech
    && !turn?.speakerIsBot
    && moderatorProtectsRoutingFlow(state)
    && !turnIsCurrentOrPendingHumanSpeaker(turn, state)
  );
}

function moderatorBlocksSpeechInterruption(state = readModeratorState()) {
  return Boolean(
    moderatorProtectsCurrentSpeaker(state)
    || (routeProtectedMicSpeech && moderatorProtectsRoutingFlow(state))
  );
}

function moderatorMutedBotIds(state = readModeratorState()) {
  const muted = new Set(moderatorBotIds(state?.muted_bot_ids));
  const only = moderatorBotIds(state?.only_bot_ids);
  if (only.length > 0 && !only.includes(botInstanceId)) {
    muted.add(botInstanceId);
  }
  return muted;
}

function moderatorBotTargetIsMuted(targetBotId, state = readModeratorState()) {
  const target = safeFileSegment(targetBotId || "").toLowerCase();
  if (!target) {
    return false;
  }
  const muted = new Set(moderatorBotIds(state?.muted_bot_ids));
  if (muted.has(target)) {
    return true;
  }
  const only = moderatorBotIds(state?.only_bot_ids);
  return Boolean(only.length > 0 && !only.includes(target));
}

function moderatorDecisionForTurn(turn, routeKey) {
  const state = readModeratorState();
  lastModeratorState = state;
  if (state?.enabled === false) {
    return null;
  }
  const muted = moderatorMutedBotIds(state);
  const rawSpeakerBotId = safeFileSegment(turn?.speakerBotId || "").toLowerCase();
  const speakerIsBot = Boolean(turn?.speakerIsBot === true || (turn?.speakerIsBot !== false && rawSpeakerBotId && rawSpeakerBotId !== "default"));
  const speakerBotId = speakerIsBot ? rawSpeakerBotId : "";
  if (rawSpeakerBotId && !speakerIsBot) {
    console.log(`[DiscordBridgeModerator] Ignoring non-bot speakerBotId for human turn: speaker=${turn?.speakerName || turn?.userId || "unknown"}, speakerBotId=${rawSpeakerBotId}`);
  }
  const inputText = String(turn?.inputText || "").trim();
  const base = {
    ok: true,
    route_key: routeKey,
    router_mode: "human_moderator",
    source: "human_moderator",
    input_text: inputText,
    context_input_text: inputText ? contextLineForTurn(turn, inputText) : "",
    speaker_name: String(turn?.speakerName || ""),
    speaker_bot_id: speakerBotId,
    speaker_is_bot: speakerIsBot,
    captured_at: String(turn?.capturedAt || new Date().toISOString()),
    speech_accepted: Boolean(inputText)
  };
  if (muted.has(botInstanceId)) {
    return {
      ...base,
      answer: false,
      target_bot_id: "",
      reason: "moderator_muted"
    };
  }

  const currentHuman = moderatorCurrentHumanRoute(state);
  if (currentHuman) {
    const liveHuman = moderatorLiveHuman(currentHuman.userId);
    if (!liveHuman) {
      console.log(`[DiscordBridgeModerator] Current human speaker is not live: ${currentHuman.userId}`);
      updateModeratorState((current) => ({
        ...current,
        current_human_route: {},
        current_speaker_user_id: "",
        current_speaker_name: "",
        last_error: `Human speaker ${currentHuman.name || currentHuman.userId} is not connected in the voice channel.`
      }));
    } else if (!base.speaker_is_bot && String(turn?.userId || "").trim() === currentHuman.userId) {
      console.log(`[DiscordBridgeModerator] Accepted current human speaker: ${currentHuman.name}`);
      const pendingAfterHuman = safeFileSegment(state?.pending_route?.target_bot_id || "").toLowerCase();
      if (pendingAfterHuman) {
        const liveTarget = moderatorLiveTarget(pendingAfterHuman);
        if (liveTarget) {
          consumeModeratorCurrentHumanRoute(routeKey);
          consumeModeratorPendingRoute(routeKey);
          console.log(`[DiscordBridgeModerator] Routing current human turn to moderator-selected bot: ${pendingAfterHuman}`);
          return {
            ...base,
            answer: true,
            target_bot_id: pendingAfterHuman,
            reason: `human_moderator_route_after_human:${String(state?.pending_route?.reason || currentHuman.reason || "manual")}`
          };
        }
        updateModeratorState((current) => ({
          ...current,
          pending_route: {},
          route_next_target_bot_id: "",
          last_error: `Target ${pendingAfterHuman} is not connected in the voice channel.`
        }));
      }
      consumeModeratorCurrentHumanRoute(routeKey);
      return null;
    } else {
      return {
        ...base,
        answer: false,
        target_bot_id: "",
        reason: `human_moderator_waiting_for_current_human:${currentHuman.name || currentHuman.userId}`,
        speech_accepted: Boolean(inputText && !base.speaker_is_bot)
      };
    }
  }

  const pendingHuman = moderatorPendingHumanRoute(state);
  if (pendingHuman) {
    const liveHuman = moderatorLiveHuman(pendingHuman.userId);
    if (!liveHuman) {
      console.log(`[DiscordBridgeModerator] Pending human route target is not live: ${pendingHuman.userId}`);
      updateModeratorState((current) => ({
        ...current,
        pending_human_route: {},
        route_next_speaker_user_id: "",
        route_next_speaker_name: "",
        last_error: `Human speaker ${pendingHuman.name || pendingHuman.userId} is not connected in the voice channel.`
      }));
    } else if (
      !base.speaker_is_bot
      && String(turn?.userId || "").trim() === pendingHuman.userId
      && !moderatorHasCurrentBot(state)
      && !hasActiveBotPlayback()
    ) {
      console.log(`[DiscordBridgeModerator] Accepted pending human speaker: ${pendingHuman.name}`);
      consumeModeratorPendingHumanRoute(routeKey);
      return null;
    } else {
      return {
        ...base,
        answer: false,
        target_bot_id: "",
        reason: `human_moderator_waiting_for_human:${pendingHuman.name || pendingHuman.userId}`,
        speech_accepted: Boolean(inputText && !base.speaker_is_bot)
      };
    }
  }

  let pendingTarget = safeFileSegment(state?.pending_route?.target_bot_id || "").toLowerCase();
  if (pendingTarget) {
    if (speakerBotId && pendingTarget === speakerBotId) {
      consumeModeratorPendingRoute(routeKey);
      pendingTarget = "";
    } else if (!base.speaker_is_bot && (inputText || turn?.filePath || Number(turn?.durationSeconds || 0) > 0)) {
      if (routeProtectedMicSpeech && moderatorProtectsRoutingFlow(state)) {
        console.log(
          `[DiscordBridgeModerator] Capturing protected mic context while waiting for pending bot route ${pendingTarget}.`
        );
        return {
          ...base,
          answer: false,
          target_bot_id: "",
          reason: "current_speaker_protected",
          protected_mic_context_only: true,
          speech_accepted: Boolean(inputText)
        };
      }
      console.log(
        `[DiscordBridgeModerator] Human speech paused pending bot route ${pendingTarget}; sending utterance through normal room router.`
      );
      return null;
    } else {
    const liveTarget = moderatorLiveTarget(pendingTarget);
    if (!liveTarget) {
      console.log(`[DiscordBridgeModerator] Pending route target is not live: ${pendingTarget}`);
      updateModeratorState((current) => ({
        ...current,
        pending_route: {},
        route_next_target_bot_id: "",
        last_error: `Target ${pendingTarget} is not connected in the voice channel.`
      }));
      pendingTarget = "";
    } else {
      consumeModeratorPendingRoute(routeKey);
      console.log(`[DiscordBridgeModerator] Routing turn to moderator-selected bot: ${pendingTarget}`);
      return {
        ...base,
        answer: true,
        target_bot_id: pendingTarget,
        reason: `human_moderator_route_next:${String(state?.pending_route?.reason || "manual")}`
      };
    }
    }
  }

  const floorTarget = safeFileSegment(state?.floor_target_bot_id || "").toLowerCase();
  if (floorTarget) {
    if (speakerBotId && floorTarget === speakerBotId) {
      return {
        ...base,
        answer: false,
        target_bot_id: "",
        reason: "human_moderator_speaker_lock_self"
      };
    }
    const liveTarget = moderatorLiveTarget(floorTarget);
    if (!liveTarget) {
      console.log(`[DiscordBridgeModerator] Allowed speaker target is not live: ${floorTarget}`);
      updateModeratorState((current) => ({
        ...current,
        floor_target_bot_id: "",
        last_error: `Allowed speaker ${floorTarget} is not connected in the voice channel.`
      }));
      return null;
    }
    return {
      ...base,
      answer: true,
      target_bot_id: floorTarget,
      reason: "human_moderator_speaker_lock"
    };
  }
  return null;
}

function consumeModeratorPendingRoute(routeKey) {
  updateModeratorState((current) => ({
    ...current,
    pending_route: {},
    route_next_target_bot_id: "",
    pending_human_route: {},
    route_next_speaker_user_id: "",
    route_next_speaker_name: "",
    last_consumed_route_key: String(routeKey || ""),
    last_error: ""
  }));
}

function consumeModeratorPendingRouteIfTarget(targetBotId, routeKey, reason = "consume_pending_target") {
  const target = safeFileSegment(targetBotId || "").toLowerCase();
  if (!target) {
    return false;
  }
  const state = readModeratorState();
  const pendingTarget = safeFileSegment(state?.pending_route?.target_bot_id || "").toLowerCase();
  if (pendingTarget !== target) {
    return false;
  }
  console.log(`[DiscordBridgeModerator] Consuming pending route for current target ${target}: ${reason}`);
  consumeModeratorPendingRoute(routeKey);
  return true;
}

function moderatorManualPendingRoute(state = readModeratorState()) {
  const pending = state?.pending_route && typeof state.pending_route === "object" ? state.pending_route : {};
  const target = safeFileSegment(pending?.target_bot_id || "").toLowerCase();
  if (!target || !moderatorLiveTarget(target)) {
    return null;
  }
  const isManual = Boolean(pending?.manual);
  if (!isManual) {
    return null;
  }
  return {
    target,
    reason: String(pending?.reason || "manual moderator route"),
    routeKey: String(pending?.route_key || ""),
    createdAtMs: Number(pending?.created_at_ms || 0),
    userCommand: Boolean(pending?.user_command)
  };
}

function consumeModeratorPendingHumanRoute(routeKey) {
  updateModeratorState((current) => ({
    ...current,
    pending_human_route: {},
    route_next_speaker_user_id: "",
    route_next_speaker_name: "",
    last_consumed_route_key: String(routeKey || ""),
    last_error: ""
  }));
}

function consumeModeratorCurrentHumanRoute(routeKey) {
  updateModeratorState((current) => ({
    ...current,
    current_human_route: {},
    current_speaker_user_id: "",
    current_speaker_name: "",
    last_consumed_route_key: String(routeKey || ""),
    last_error: ""
  }));
  applyDiscordMuteEnforcement("consume_current_human").catch((error) => {
    console.warn(`[DiscordBridgeModerator] Could not update Discord mutes after current human route: ${error?.message || error}`);
  });
}

function hasActiveBotPlayback() {
  return Boolean(playbackActive || currentPlaybackItem || playbackQueue.length > 0);
}

function moderatorHasCurrentBot(state = readModeratorState()) {
  const currentBot = safeFileSegment(state?.current_bot_id || "").toLowerCase();
  return Boolean(currentBot && moderatorLiveTarget(currentBot));
}

function moderatorHasCurrentOrPendingSpeaker(state = readModeratorState()) {
  return Boolean(
    moderatorHasCurrentBot(state)
    || moderatorCurrentHumanRoute(state)
    || moderatorPendingHumanRoute(state)
    || moderatorPendingBotRoute(state)
  );
}

function markBotCurrentForTurn(turnState, reason) {
  if (!turnState || turnState.waitForReplyFloor) {
    return false;
  }
  const turnId = String(turnState.turnId || "");
  updateModeratorState((current) => ({
    ...current,
    current_bot_id: botInstanceId,
    current_bot_name: botDisplayName,
    current_bot_discord_user_id: String(client.user?.id || ""),
    current_bot_turn_id: turnId,
    current_human_route: {},
    current_speaker_user_id: "",
    current_speaker_name: "",
    ...(safeFileSegment(current?.pending_route?.target_bot_id || "").toLowerCase() === botInstanceId
      ? {
          pending_route: {},
          route_next_target_bot_id: ""
        }
      : {}),
    last_error: ""
  }));
  applyDiscordMuteEnforcement(reason || "mark_current_bot").catch((error) => {
    console.warn(`[DiscordBridgeModerator] Could not update Discord mutes after marking current bot: ${error?.message || error}`);
  });
  return true;
}

function clearCurrentBotModeratorState(reason, expectedTurnId = "") {
  updateModeratorState((current) => {
    if (safeFileSegment(current?.current_bot_id || "").toLowerCase() !== botInstanceId) {
      return current;
    }
    const currentTurnId = String(current?.current_bot_turn_id || "");
    const expected = String(expectedTurnId || "");
    if (expected && currentTurnId && currentTurnId !== expected) {
      return current;
    }
    return {
      ...current,
      current_bot_id: "",
      current_bot_name: "",
      current_bot_discord_user_id: "",
      current_bot_turn_id: ""
    };
  });
  applyDiscordMuteEnforcement(reason || "clear_current_bot").catch((error) => {
    console.warn(`[DiscordBridgeModerator] Could not update Discord mutes after clearing current bot: ${error?.message || error}`);
  });
}

function clearCurrentBotIfTurnHasNoPlayback(turnState, reason) {
  const turnId = String(turnState?.turnId || "");
  if (!turnId || hasPendingPlaybackForTurn(turnId)) {
    return false;
  }
  clearCurrentBotModeratorState(reason || "clear_unplayed_current_bot", turnId);
  return true;
}

function promotePendingHumanRouteToCurrent(reason) {
  const state = readModeratorState();
  if (hasActiveBotPlayback() || moderatorHasCurrentBot(state)) {
    return false;
  }
  if (moderatorCurrentHumanRoute(state)) {
    return false;
  }
  const pending = moderatorPendingHumanRoute(state);
  if (!pending) {
    return false;
  }
  const participant = currentParticipantSnapshot().find((item) => !item.is_bot && String(item.id || "") === pending.userId);
  if (!participant || participant.display_name_conflict) {
    updateModeratorState((current) => ({
      ...current,
      pending_human_route: {},
      route_next_speaker_user_id: "",
      route_next_speaker_name: "",
      last_command: "clear_pending_human_name_conflict",
      last_error: participant?.display_name_conflict
        ? `Human route target ${participant.name || pending.userId} has a duplicate display name. Rename or alias the participant before routing.`
        : `Human route target ${pending.userId || "(none)"} is not connected in the voice channel.`
    }));
    return false;
  }
  updateModeratorState((current) => ({
    ...current,
    current_human_route: {
      speaker_user_id: pending.userId,
      speaker_name: pending.name,
      created_at_ms: Date.now(),
      reason: pending.reason || reason || "manual moderator floor"
    },
    current_speaker_user_id: pending.userId,
    current_speaker_name: pending.name,
    pending_human_route: {},
    route_next_speaker_user_id: "",
    route_next_speaker_name: "",
    last_command: `current_human:${pending.name}`,
    last_error: ""
  }));
  console.log(`[DiscordBridgeModerator] Human speaker is now current: ${pending.name} (${pending.userId}) reason=${reason || "playback_idle"}`);
  applyDiscordMuteEnforcement("promote_pending_human").catch((error) => {
    console.warn(`[DiscordBridgeModerator] Could not update Discord mutes after human promotion: ${error?.message || error}`);
  });
  return true;
}

function contextLineForTurn(turn, inputText) {
  const speaker = String(turn?.speakerName || turn?.userId || "Discord user").trim();
  const when = String(turn?.capturedAt || new Date().toISOString()).trim();
  const text = String(inputText || "").trim();
  return `[${when}] ${speaker}: ${text}`;
}

function turnNeedsTranscriptBeforeModeratorDecision(turn) {
  return Boolean(
    !turn?.speakerBotId
    && !String(turn?.inputText || "").trim()
    && String(turn?.filePath || "").trim()
  );
}

function turnWithRouteDecisionTranscript(turn, decision) {
  const inputText = String(decision?.input_text || turn?.inputText || "").trim();
  if (!inputText) {
    return turn;
  }
  return {
    ...turn,
    inputText
  };
}

function roomRouterCandidatesForTurn(turn) {
  const liveCandidates = liveRoomRouterCandidateBots();
  const muted = moderatorMutedBotIds();
  const botCandidates = liveCandidates.filter((candidate) => {
    const candidateId = safeFileSegment(candidate?.id || candidate?.name || "").toLowerCase();
    return candidateId && !muted.has(candidateId);
  }).map((candidate) => ({
    ...candidate,
    router_target: routerTargetTokenForName(candidate?.name || candidate?.id || "", candidate?.id || candidate?.name || "")
  }));
  const speakerUserId = String(turn?.userId || "").trim();
  const currentState = readModeratorState();
  const mutedHumans = new Set((Array.isArray(currentState?.muted_speaker_user_ids) ? currentState.muted_speaker_user_ids : [])
    .map((value) => String(value || "").trim())
    .filter(Boolean));
  const humanCandidates = currentParticipantSnapshot()
    .filter((participant) => !participant.is_bot && !participant.display_name_conflict)
    .map((participant) => {
      const userId = String(participant.id || "").trim();
      const name = String(participant.name || userId).trim() || userId;
      return {
        id: userId ? `human:${userId}` : "",
        name,
        call_names: name,
        router_target: routerTargetTokenForName(name, userId),
        persona_hint: ""
      };
    })
    .filter((candidate) => {
      const userId = String(candidate.id || "").replace(/^human:/i, "").trim();
      if (!userId || mutedHumans.has(userId)) {
        return false;
      }
      if (!moderatorHumanCandidateAllowed(userId, currentState)) {
        return false;
      }
      return !(roomRouterExcludeSpeakerFromTargets && speakerUserId && userId === speakerUserId);
    });
  return [...botCandidates, ...humanCandidates];
}

function liveRoomRouterCandidateBots() {
  const botParticipants = currentParticipantSnapshot().filter((participant) => participant.is_bot);
  if (botParticipants.length === 0) {
    return roomRouterCandidateBots;
  }
  const liveKeys = new Set();
  for (const participant of botParticipants) {
    const participantId = safeFileSegment(participant.id || "").toLowerCase();
    const participantName = safeFileSegment(participant.name || "").toLowerCase();
    if (participantId) {
      liveKeys.add(participantId);
    }
    if (participantName) {
      liveKeys.add(participantName);
    }
  }
  return roomRouterCandidateBots.filter((candidate) => {
    const keys = [
      candidate?.id,
      candidate?.name,
      ...(String(candidate?.call_names || "").split(/[,\n|/]+/g))
    ]
      .map((value) => safeFileSegment(value || "").toLowerCase())
      .filter(Boolean);
    return keys.some((key) => liveKeys.has(key));
  });
}

async function requestRoomRouteDecision(turn, routeKey) {
  const inputText = String(turn.inputText || "").trim();
  const response = await fetch(ncRouteEndpoint, {
    method: "POST",
    headers: ncJsonHeaders(),
    body: JSON.stringify({
      route_key: routeKey,
      router_mode: roomRouterMode,
      user_id: turn.userId,
      speaker_name: turn.speakerName || "",
      speaker_bot_id: turn.speakerBotId || "",
      speaker_is_bot: Boolean(turn.speakerBotId || turn.speakerIsBot),
      captured_at: turn.capturedAt || new Date().toISOString(),
      participants: currentParticipantSnapshot(),
      room_context: readRoomContext(),
      candidate_bots: roomRouterCandidatesForTurn(turn),
      record_route_context: shouldRecordProtectedMicContext(turn),
      routing_policy: {
        human_to_bot_routing: roomRouterHumanToBotRouting,
        bot_to_bot_routing: roomRouterBotToBotRouting,
        exclude_speaker_from_targets: roomRouterExcludeSpeakerFromTargets,
        allow_group_invitation_routing: roomRouterAllowGroupInvitationRouting,
        allow_open_room_invitation_routing: roomRouterAllowOpenRoomInvitationRouting,
        self_route_policy: roomRouterSelfRoutePolicy,
        default_when_uncertain: roomRouterDefaultWhenUncertain,
        competing_bot_reply_policy: competingBotReplyPolicy,
        reply_floor_mode: replyFloorMode
      },
      input_text: inputText,
      wav_path: inputText ? "" : turn.filePath,
      duration_seconds: turn.durationSeconds
    })
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) {
    throw new Error(`Room route failed: ${JSON.stringify(payload)}`);
  }
  console.log(
    `[DiscordBridgeRouter] Decision: speaker=${turn.speakerName || turn.userId || "?"}, candidates=${(payload.candidate_ids || []).join(",") || "(unknown)"}, answer=${Boolean(payload.answer)}, target=${payload.target_bot_id || "(none)"}, reason=${payload.reason || ""}, policy=${JSON.stringify(payload.policy || {})}`
  );
  return payload;
}

async function routeBotReplyText(replyText, turnState, options = {}) {
  const inputText = String(replyText || "").trim();
  const allowRepublish = Boolean(options.allowRepublish);
  const manualOnly = Boolean(options.manualOnly);
  const routeStartedAtMs = Date.now();
  if (!shouldUseDirectBotTextRouting() || !inputText || (turnState.botTextRoutePublished && !allowRepublish)) {
    if (!roomRouterBotToBotRouting) {
      console.log("[DiscordBridgeRouter] Completed bot text not routed: bot-to-bot routing is disabled.");
    }
    return;
  }
  if (turnState.generation !== playbackGeneration || turnState.replyFloorDenied || routedTurnInvalidatedByHumanIntervention(turnState)) {
    console.log("[DiscordBridgeRouter] Completed bot text route skipped because the turn was interrupted or stale.");
    return;
  }
  const manualPending = manualOnly ? moderatorManualPendingRoute() : null;
  if (manualOnly && (!manualPending || !manualPending.target || manualPending.target === botInstanceId)) {
    return;
  }
  const routeKey = completedBotTextRouteKey(turnState, manualPending);
  turnState.publishedCompletedTextRouteKeys = turnState.publishedCompletedTextRouteKeys instanceof Set
    ? turnState.publishedCompletedTextRouteKeys
    : new Set();
  if (turnState.publishedCompletedTextRouteKeys.has(routeKey)) {
    console.log(`[DiscordBridgeRouter] Completed bot text route already published for this turn: key=${routeKey}`);
    return;
  }
  const resultPath = roomRouteResultPath(routeKey);
  const lockPath = `${resultPath}.lock`;
  if (!tryCreateRouteLock(lockPath)) {
    console.log(`[DiscordBridgeRouter] Completed bot text route already in progress: key=${routeKey}`);
    return;
  }
  turnState.botTextRouteInFlight = true;
  turnState.botTextRouteAttemptAtMs = routeStartedAtMs;
  const turn = {
    userId: String(client.user?.id || botInstanceId),
    speakerName: botDisplayName,
    speakerBotId: botInstanceId,
    speakerIsBot: true,
    inputText,
    durationSeconds: 0,
    capturedAt: new Date().toISOString(),
    routeKey
  };
  try {
    console.log(`[DiscordBridgeRouter] Routing completed bot text once: key=${routeKey}, speaker=${botDisplayName}`);
    let decision = moderatorDecisionForTurn(turn, routeKey);
    if (!decision && !manualOnly) {
      decision = await requestRoomRouteDecision(turn, routeKey);
    }
    if (!decision) {
      return;
    }
    const prePublishOverride = completedBotTextRouteModeratorOverrideReason(turnState, routeStartedAtMs);
    if (prePublishOverride) {
      console.log(`[DiscordBridgeRouter] Completed bot text route skipped after moderator override: ${prePublishOverride}`);
      return;
    }
    decision = decisionWithHumanFloorIfNeeded(decision, turn, moderatorEnforcerBotId());
    const preBroadcastTarget = safeFileSegment(decision?.target_bot_id || "").toLowerCase();
    await broadcastRoomTurnToBotHistories(decision, turn, routeKey);
    const postContextOverride = completedBotTextRouteModeratorOverrideReason(turnState, routeStartedAtMs);
    if (postContextOverride) {
      await broadcastRoomTurnToBotHistories(decision, turn, `${routeKey}:override:${preBroadcastTarget}`, {
        includeSelectedTarget: true,
        onlyCandidateIds: preBroadcastTarget ? [preBroadcastTarget] : []
      });
      console.log(`[DiscordBridgeRouter] Completed bot text route not queued after moderator override: ${postContextOverride}`);
      return;
    }
    appendRoomContextFromDecision(decision);
    writeFileSync(resultPath, JSON.stringify(decision, null, 2), "utf8");
    turnState.botTextRoutePublished = true;
    turnState.botTextRoutePublishedAtMs = Date.now();
    turnState.publishedCompletedTextRouteKeys.add(routeKey);
    appendModeratorRouteFlow(decision, turn, routeKey, decision?.source || "bot_text_router");
    const normalizedTarget = normalizeRecoveryTargetId(decision?.target_bot_id || "");
    if (normalizedTarget.startsWith("human:")) {
      setHumanCurrentFromRoute(normalizedTarget, {
        reason: String(decision?.reason || "bot_text_human_route"),
        commandPrefix: "bot_text_current_human",
        muteReason: "bot_text_human_route"
      });
      return;
    }
    const preQueueOverride = completedBotTextRouteModeratorOverrideReason(turnState, routeStartedAtMs);
    if (preQueueOverride) {
      console.log(`[DiscordBridgeRouter] Completed bot text route queue skipped after moderator override: ${preQueueOverride}`);
      return;
    }
    await maybeQueueDeadAirRecovery(decision, turn, routeKey, decision?.source || "bot_text_router", {
      allowActiveCompletedCurrent: true,
      activeTurnId: String(turnState?.turnId || "")
    });
    const postRecoveryOverride = completedBotTextRouteModeratorOverrideReason(turnState, routeStartedAtMs);
    if (postRecoveryOverride) {
      console.log(`[DiscordBridgeRouter] Completed bot text route queue skipped after recovery override: ${postRecoveryOverride}`);
      return;
    }
    const route = routeDecisionForThisBot(decision);
    if (route.shouldProceed) {
      console.log("[DiscordBridgeRouter] Bot text route selected this process; ignoring self-route to avoid echo.");
      return;
    }
    const target = safeFileSegment(decision?.target_bot_id || "").toLowerCase();
    if (!decision?.answer || !target || target === botInstanceId) {
      return;
    }
    writeRoutedTextTurn(target, {
      route_key: routeKey,
      target_bot_id: target,
      source_bot_id: botInstanceId,
      source_user_id: String(client.user?.id || botInstanceId),
      speaker_name: botDisplayName,
      input_text: inputText,
      captured_at: turn.capturedAt,
      route_started_at_ms: routeStartedAtMs,
      created_at_ms: Date.now(),
      reason: String(decision.reason || "bot_text_route"),
      decision
    });
  } catch (error) {
    console.error("[DiscordBridgeRouter] Bot text route failed:", error);
  } finally {
    turnState.botTextRouteInFlight = false;
    try {
      unlinkSync(lockPath);
    } catch {
      // Already removed is fine.
    }
  }
}

function completedBotTextRouteKey(turnState = {}, manualPending = null) {
  const turnId = safeFileSegment(turnState?.turnId || activeNcTurnId || activePlaybackTurnId || Date.now());
  const manualTarget = safeFileSegment(manualPending?.target || "").toLowerCase();
  const manualCreatedAtMs = Number(manualPending?.createdAtMs || 0);
  const suffix = manualTarget && manualCreatedAtMs > 0
    ? `manual_${manualTarget}_${manualCreatedAtMs}`
    : "auto";
  return `text_${safeFileSegment(voiceChannelId)}_${botInstanceId}_${turnId}_${suffix}`;
}

function publishCompletedBotReplyText(replyText, turnState) {
  const inputText = String(replyText || "").trim();
  if (!inputText || !turnState || turnState.botTextRoutePublished) {
    return;
  }
  turnState.completedReplyText = inputText;
}

function routeCompletedBotReplyTextNow(replyText, turnState) {
  const inputText = String(replyText || turnState?.completedReplyText || "").trim();
  if (!inputText || !turnState) {
    return Promise.resolve(false);
  }
  const manualPending = moderatorManualPendingRoute();
  const previousRouteAtMs = Math.max(
    Number(turnState.botTextRoutePublishedAtMs || 0),
    Number(turnState.botTextRouteAttemptAtMs || 0)
  );
  const manualOverride = Boolean(
    previousRouteAtMs > 0
    && manualPending
    && manualPending.userCommand
    && manualPending.target
    && manualPending.target !== botInstanceId
    && Number(manualPending.createdAtMs || 0) > previousRouteAtMs
  );
  if (turnState.botTextRouteInFlight && !manualOverride) {
    return turnState.botTextRoutePromise || Promise.resolve(false);
  }
  if (turnState.botTextRoutePublished && !manualOverride) {
    return turnState.botTextRoutePromise || Promise.resolve(false);
  }
  const routePromise = routeBotReplyText(inputText, turnState, {
    allowRepublish: manualOverride,
    manualOnly: manualOverride
  }).catch((error) => {
    console.error("[DiscordBridgeRouter] Completed bot text route failed:", error);
    return false;
  });
  turnState.botTextRoutePromise = routePromise;
  return routePromise;
}

function maybeRepublishCompletedTextForManualNext() {
  const progress = activeReplyProgress;
  if (!progress || !progress.replyComplete || progress.replyFloorDenied) {
    return;
  }
  const manualPending = moderatorManualPendingRoute();
  if (!manualPending || !manualPending.userCommand || !manualPending.target || manualPending.target === botInstanceId) {
    return;
  }
  const manualCreatedAtMs = Number(manualPending.createdAtMs || 0);
  if (manualCreatedAtMs <= Number(progress.botTextRoutePublishedAtMs || 0)) {
    return;
  }
  const republishKey = `${manualPending.target}:${manualCreatedAtMs}`;
  if (String(progress.manualNextRepublishKey || "") === republishKey) {
    return;
  }
  const inputText = String(progress.completedReplyText || spokenReplyText()).trim();
  if (!inputText) {
    return;
  }
  progress.manualNextRepublishKey = republishKey;
  console.log(`[DiscordBridgeRouter] Manual Next override detected; preparing routed reply for ${manualPending.target}.`);
  routeCompletedBotReplyTextNow(inputText, progress);
}

function maybeDropRoutedPreRenderAfterManualNext() {
  const candidates = [...replyProgressByTurnId.values()];
  if (activeReplyProgress && !candidates.includes(activeReplyProgress)) {
    candidates.push(activeReplyProgress);
  }
  let dropped = false;
  for (const progress of candidates) {
    if (!progress || progress.replyFloorDenied || !progress.routedText) {
      continue;
    }
    const stateReason = routedTurnModeratorStateInvalidationReason(progress);
    if (!stateReason) {
      continue;
    }
    dropRoutedTurnAfterModeratorStateChange(
      progress,
      String(progress.turnId || activeNcTurnId || ""),
      `pre-render invalidated by ${stateReason}`
    );
    dropped = true;
  }
  if (dropped) {
    writeRuntimeStatus("moderator_override_drop");
  }
}

function routedTextPayloadSource(payload = {}) {
  return String(payload?.decision?.source || payload?.decision?.router_mode || payload?.source || "routed_text")
    .trim()
    .toLowerCase();
}

function routedTextWriteBlockedByManualNext(payload = {}) {
  const sourceKind = routedTextPayloadSource(payload);
  if (sourceKind === "human_moderator") {
    return "";
  }
  const routeStartedAtMs = Number(payload?.route_started_at_ms || payload?.decision?.route_started_at_ms || 0);
  const overrideReason = moderatorOverrideReasonSince(routeStartedAtMs);
  if (overrideReason) {
    return `moderator_override:${overrideReason}`;
  }
  const state = readModeratorState();
  const manualPending = moderatorManualPendingRoute(state);
  if (manualPending?.target) {
    return `manual_next:${manualPending.target}`;
  }
  const humanPending = moderatorPendingHumanRoute(state);
  if (humanPending?.userId || humanPending?.name) {
    return `manual_human_next:${humanPending.name || humanPending.userId || "unknown"}`;
  }
  return "";
}

function writeRoutedTextTurn(targetBotId, payload) {
  const blockReason = routedTextWriteBlockedByManualNext(payload);
  if (blockReason) {
    console.log(`[DiscordBridgeRouter] Routed bot text not queued after manual moderator Next: ${blockReason}`);
    return false;
  }
  const sourceKind = routedTextPayloadSource(payload);
  const stateBlockReason = moderatorPendingBotRouteBlockReason(targetBotId, sourceKind);
  if (stateBlockReason) {
    console.log(`[DiscordBridgeRouter] Routed bot text not queued because moderator state rejected target: ${stateBlockReason}`);
    return false;
  }
  const routeKey = String(payload.route_key || randomUUID());
  const path = routedTextTurnPath(targetBotId, routeKey);
  const routedPayload = {
    ...payload,
    route_key: routeKey
  };
  if (!markModeratorPendingBotRoute(
    targetBotId,
    String(routedPayload.reason || routedPayload.decision?.reason || "routed text"),
    routeKey,
    routedTextPayloadSource(payload)
  )) {
    return false;
  }
  try {
    writeFileSync(path, JSON.stringify(routedPayload, null, 2), { encoding: "utf8", flag: "wx" });
  } catch (error) {
    if (error?.code !== "EEXIST") {
      clearModeratorPendingRouteIfKey(routeKey, targetBotId, "routed_text_write_failed");
    }
    throw error;
  }
  console.log(`[DiscordBridgeRouter] Routed bot text queued for ${targetBotId}: ${path}`);
  return true;
}

function clearModeratorPendingRouteIfKey(routeKey, targetBotId, reason) {
  const key = String(routeKey || "");
  const target = safeFileSegment(targetBotId || "").toLowerCase();
  if (!key || !target) {
    return false;
  }
  let cleared = false;
  updateModeratorState((current) => {
    const pending = current?.pending_route && typeof current.pending_route === "object" ? current.pending_route : {};
    const pendingTarget = safeFileSegment(pending?.target_bot_id || "").toLowerCase();
    if (pendingTarget !== target || String(pending?.route_key || "") !== key) {
      return current;
    }
    cleared = true;
    return {
      ...current,
      pending_route: {},
      route_next_target_bot_id: "",
      last_error: reason ? `Pending route cleared: ${reason}` : ""
    };
  });
  return cleared;
}

function routedTextTurnPath(targetBotId, routeKey) {
  return join(turnDir, `routed_text_${safeFileSegment(targetBotId)}_${safeFileSegment(routeKey)}.json`);
}

function writeRoutedTurnForSelectedTarget(decision, turn, routeKey, routeStartedAtMs = Date.now()) {
  const normalizedTarget = normalizeRecoveryTargetId(decision?.target_bot_id || "");
  if (normalizedTarget.startsWith("human:")) {
    setHumanCurrentFromRoute(normalizedTarget, {
      reason: String(decision?.reason || "selected_human_route"),
      commandPrefix: "selected_current_human",
      muteReason: "selected_human_route"
    });
    return;
  }
  const target = safeFileSegment(decision?.target_bot_id || "").toLowerCase();
  if (!decision?.answer || !target || target === botInstanceId) {
    return;
  }
  const inputText = String(decision?.input_text || turn?.inputText || "").trim();
  if (!inputText) {
    console.warn(`[DiscordBridgeRouter] Routed turn for ${target} skipped because the transcript is empty.`);
    return;
  }
  try {
    writeRoutedTextTurn(target, {
      route_key: routeKey,
      target_bot_id: target,
      accepted_human_intervention_route_key: String(routeKey || ""),
      accepted_human_intervention_target_bot_id: target,
      source_bot_id: safeFileSegment(turn?.speakerBotId || "").toLowerCase(),
      source_user_id: String(turn?.userId || ""),
      speaker_name: String(turn?.speakerName || turn?.userId || "Discord user"),
      input_text: inputText,
      captured_at: String(turn?.capturedAt || new Date().toISOString()),
      route_started_at_ms: Number(routeStartedAtMs || 0),
      created_at_ms: Date.now(),
      reason: String(decision.reason || "room_route"),
      decision
    });
  } catch (error) {
    if (error?.code === "EEXIST") {
      return;
    }
    console.warn(`[DiscordBridgeRouter] Could not queue routed turn for ${target}: ${error?.message || error}`);
  }
}

async function processRoutedTextInbox() {
  if (bridgeMode !== "http" || !shouldUseRoomRouter()) {
    return;
  }
  let names = [];
  try {
    names = readdirSync(turnDir);
  } catch {
    return;
  }
  const prefix = `routed_text_${botInstanceId}_`;
  for (const name of names) {
    if (!name.startsWith(prefix) || !name.endsWith(".json")) {
      continue;
    }
    const path = join(turnDir, name);
    if (routedTextInProgress.has(path)) {
      continue;
    }
    const payload = readJsonFile(path);
    if (!payload) {
      continue;
    }
    if (isStaleRoutedTextPayload(payload)) {
      try {
        unlinkSync(path);
      } catch {
        // Already removed is fine.
      }
      console.log(`[DiscordBridgeRouter] Discarded stale routed bot text: ${name}`);
      continue;
    }
    if (routedPayloadInvalidatedByHumanIntervention(payload)) {
      try {
        unlinkSync(path);
      } catch {
        // Already removed is fine.
      }
      console.log(`[DiscordBridgeRouter] Discarded routed bot text after human intervention: ${name}`);
      continue;
    }
    if (routedPayloadInvalidatedByModeratorOverride(payload)) {
      try {
        unlinkSync(path);
      } catch {
        // Already removed is fine.
      }
      console.log(`[DiscordBridgeRouter] Discarded routed bot text after manual moderator override: ${name}`);
      continue;
    }
    routedTextInProgress.add(path);
    try {
      unlinkSync(path);
    } catch {
      // Another process or cleanup may have removed it.
    }
    try {
      console.log(`[DiscordBridgeRouter] Processing routed bot text: ${name}`);
      await handleHttpNcTurn({
        userId: String(payload.source_user_id || payload.source_bot_id || "bot_text"),
        speakerName: String(payload.speaker_name || payload.source_bot_id || "Discord bot"),
        inputText: String(payload.input_text || ""),
        durationSeconds: 0,
        capturedAt: String(payload.captured_at || new Date().toISOString()),
        routeKey: String(payload.route_key || ""),
        routedText: true,
        routedTargetBotId: botInstanceId,
        routedPayloadRouteStartedAtMs: Number(payload.route_started_at_ms || payload.decision?.route_started_at_ms || 0),
        routedPayloadCreatedAtMs: Number(payload.created_at_ms || 0),
        routedPayloadRouteKey: String(payload.route_key || ""),
        routedPayloadTargetBotId: botInstanceId,
        acceptedHumanInterventionRouteKey: String(payload.accepted_human_intervention_route_key || payload.route_key || ""),
        acceptedHumanInterventionTargetBotId: safeFileSegment(payload.accepted_human_intervention_target_bot_id || payload.target_bot_id || botInstanceId).toLowerCase(),
        prepareAhead: prepareRoutedBotRepliesAhead,
        deadAirRecovery: Boolean(payload.dead_air_recovery),
        recoveryActionMode: String(payload.recovery_action_mode || ""),
        recoveryNextTargetBotId: String(payload.recovery_next_target_bot_id || ""),
        roomRouterDecision: {
          answer: true,
          target_bot_id: botInstanceId,
          reason: String(payload.reason || payload.decision?.reason || "bot_text_route")
        }
      });
    } finally {
      routedTextInProgress.delete(path);
    }
  }
}

function isStaleRoutedTextPayload(payload) {
  const createdAtMs = Number(payload?.created_at_ms || 0);
  if (!Number.isFinite(createdAtMs) || createdAtMs <= 0) {
    return true;
  }
  return Date.now() - createdAtMs > routedTextMaxAgeMs;
}

function discardPendingRoutedTextTurns(reason) {
  let removed = 0;
  try {
    for (const name of readdirSync(turnDir)) {
      if (!name.startsWith("routed_text_") || !name.endsWith(".json")) {
        continue;
      }
      rmSync(join(turnDir, name), { force: true });
      removed += 1;
    }
  } catch {
    return;
  }
  if (removed > 0) {
    console.log(`[DiscordBridgeDecision] Discarded ${removed} pending routed bot text turn(s): ${reason}`);
  }
}

function markAcceptedHumanRoute(decision, turn, routeKey) {
  if (turn?.speakerBotId || turn?.speakerIsBot) {
    return;
  }
  if (isProtectedMicContextOnlyDecision(decision)) {
    console.log("[DiscordBridgeDecision] Protected mic speech recorded without consuming moderator routing.");
    return;
  }
  const inputText = String(decision?.input_text || turn?.inputText || "").trim();
  if (decision?.speech_accepted === false || !inputText) {
    return;
  }
  consumeModeratorPendingRoute(routeKey);
  const reason = `accepted human speech route: ${decision?.reason || "room_router"}`;
  markHumanIntervention(reason, {
    accepted_route_key: String(routeKey || ""),
    target_bot_id: String(decision?.target_bot_id || "")
  });
  discardPendingRoutedTextTurns(`${reason} (${routeKey || "no_route_key"})`);
}

function isProtectedMicContextOnlyDecision(decision) {
  return Boolean(decision?.protected_mic_context_only)
    || String(decision?.reason || "").trim() === "current_speaker_protected";
}

function markHumanIntervention(reason, extra = {}) {
  const payload = {
    created_at_ms: Date.now(),
    reason: String(reason || "human_intervention"),
    source_bot_id: botInstanceId,
    ...extra
  };
  try {
    writeFileSync(humanInterventionPath, JSON.stringify(payload, null, 2), "utf8");
  } catch (error) {
    console.warn(`[DiscordBridgeDecision] Could not write human intervention marker: ${error?.message || error}`);
  }
}

function emitPlaybackControl(action, reason, extra = {}) {
  const eventId = `${botInstanceId}_${Date.now()}_${randomUUID()}`;
  const payload = {
    event_id: eventId,
    action: String(action || "").trim(),
    created_at_ms: Date.now(),
    reason: String(reason || ""),
    source_bot_id: botInstanceId,
    ...extra
  };
  try {
    writeFileSync(playbackControlPath, JSON.stringify(payload, null, 2), "utf8");
  } catch (error) {
    console.warn(`[DiscordBridgeDecision] Could not write playback control marker: ${error?.message || error}`);
  }
  return eventId;
}

function processPlaybackControlInbox() {
  const payload = readJsonFile(playbackControlPath);
  const eventId = String(payload?.event_id || "");
  if (!eventId || eventId === lastPlaybackControlEventId) {
    return;
  }
  lastPlaybackControlEventId = eventId;
  if (String(payload?.source_bot_id || "") === botInstanceId) {
    return;
  }
  const action = String(payload?.action || "").trim().toLowerCase();
  const reason = String(payload?.reason || "shared playback control");
  if (action === "probe_pause") {
    pauseReplyPlaybackForTranscriptProbe(`shared ${reason}`);
    return;
  }
  if (action === "probe_resume") {
    resumeReplyPlaybackAfterTranscriptProbe(`shared ${reason}`);
    return;
  }
  if (action === "interrupt") {
    const routeTargetBotId = safeFileSegment(payload?.target_bot_id || "").toLowerCase();
    const routeKey = String(payload?.route_key || "").trim();
    const isRouteTarget = Boolean(routeKey && routeTargetBotId && routeTargetBotId === botInstanceId);
    if (shouldIgnoreSharedRouteInterrupt(payload)) {
      console.log(
        `[DiscordBridgeDecision] Ignoring shared route interrupt for active routed turn: route=${payload.route_key || ""}`
      );
      return;
    }
    interruptCurrentReply(`shared ${reason}`, {
      respectImmunity: false,
      abortActiveRequest: true,
      sendCancel: true,
      broadcastControl: false,
      discardRoutedTurns: !isRouteTarget,
      humanInterventionExtra: routeKey
        ? { accepted_route_key: routeKey, target_bot_id: routeTargetBotId }
        : {}
    });
  }
}

function shouldIgnoreSharedRouteInterrupt(payload) {
  const targetBotId = safeFileSegment(payload?.target_bot_id || "").toLowerCase();
  const routeKey = String(payload?.route_key || "").trim();
  if (!routeKey || !activeReplyProgress?.routedText) {
    return false;
  }
  if (targetBotId && targetBotId === botInstanceId && String(activeReplyProgress.routeKey || "") === routeKey) {
    return true;
  }
  const acceptedRouteKey = String(activeReplyProgress.acceptedHumanInterventionRouteKey || "").trim();
  if (acceptedRouteKey !== routeKey) {
    return false;
  }
  const acceptedTarget = safeFileSegment(
    activeReplyProgress.acceptedHumanInterventionTargetBotId
    || activeReplyProgress.routedTargetBotId
    || ""
  ).toLowerCase();
  return Boolean(!targetBotId || !acceptedTarget || targetBotId === acceptedTarget);
}

function latestHumanInterventionMs() {
  const payload = readJsonFile(humanInterventionPath);
  const value = Number(payload?.created_at_ms || 0);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function stampRouteDecision(decision) {
  const payload = decision && typeof decision === "object" ? { ...decision } : {};
  const existingMs = Number(payload.created_at_ms || 0);
  return {
    ...payload,
    created_at_ms: Number.isFinite(existingMs) && existingMs > 0 ? existingMs : Date.now()
  };
}

function routeResultTimestampMs(decision, resultPath) {
  const explicitMs = Number(decision?.created_at_ms || 0);
  if (Number.isFinite(explicitMs) && explicitMs > 0) {
    return explicitMs;
  }
  try {
    const fileMs = Number(statSync(resultPath).mtimeMs || 0);
    return Number.isFinite(fileMs) && fileMs > 0 ? Math.floor(fileMs) : 0;
  } catch {
    return 0;
  }
}

function routedPayloadInvalidatedByHumanIntervention(payload) {
  const marker = readJsonFile(humanInterventionPath);
  const acceptedRouteKey = String(marker?.accepted_route_key || "").trim();
  const targetBotId = safeFileSegment(marker?.target_bot_id || "").toLowerCase();
  const payloadRouteKey = String(payload?.route_key || "").trim();
  const payloadTargetBotId = safeFileSegment(payload?.target_bot_id || "").toLowerCase();
  if (
    acceptedRouteKey
    && payloadRouteKey
    && payloadRouteKey === acceptedRouteKey
    && (!targetBotId || !payloadTargetBotId || payloadTargetBotId === targetBotId)
  ) {
    return false;
  }
  const markerMs = Number(marker?.created_at_ms || 0);
  const referenceMs = routedPayloadReferenceMs(payload);
  return Boolean(markerMs > 0 && referenceMs > 0 && referenceMs < markerMs);
}

function routedPayloadInvalidatedByModeratorOverride(payload) {
  const state = readModeratorState();
  const referenceMs = routedPayloadReferenceMs(payload);
  if (referenceMs <= 0) {
    return false;
  }
  const clearPendingMs = String(state?.last_command || "") === "clear_pending"
    ? Number(state?.last_command_at_ms || 0)
    : 0;
  if (clearPendingMs > referenceMs) {
    return true;
  }
  const pendingHuman = moderatorPendingHumanRoute(state);
  if (Number(pendingHuman?.createdAtMs || 0) > referenceMs) {
    return true;
  }
  const currentHuman = moderatorCurrentHumanRoute(state);
  if (Number(currentHuman?.createdAtMs || 0) > referenceMs) {
    return true;
  }
  const manual = moderatorManualPendingRoute(state);
  if (!manual || !manual.target || manual.target === botInstanceId) {
    return false;
  }
  const markerMs = Number(manual.createdAtMs || 0);
  return Boolean(markerMs > referenceMs);
}

function routedPayloadReferenceMs(payload = {}) {
  const startedAtMs = Number(payload?.route_started_at_ms || payload?.decision?.route_started_at_ms || 0);
  const createdAtMs = Number(payload?.created_at_ms || 0);
  const candidates = [startedAtMs, createdAtMs].filter((value) => Number.isFinite(value) && value > 0);
  return candidates.length > 0 ? Math.min(...candidates) : 0;
}

function routedPickedPayloadForTurn(turn = {}) {
  return {
    route_started_at_ms: Number(turn?.routedPayloadRouteStartedAtMs || turn?.roomRouterDecision?.route_started_at_ms || 0),
    created_at_ms: Number(turn?.routedPayloadCreatedAtMs || 0),
    route_key: String(turn?.routedPayloadRouteKey || turn?.routeKey || ""),
    target_bot_id: safeFileSegment(
      turn?.routedPayloadTargetBotId
      || turn?.routedTargetBotId
      || turn?.roomRouterDecision?.target_bot_id
      || ""
    ).toLowerCase()
  };
}

function routedPickedPayloadInvalidationReason(turn = {}) {
  if (!turn?.routedText) {
    return "";
  }
  const payload = routedPickedPayloadForTurn(turn);
  if (routedPayloadInvalidatedByHumanIntervention(payload)) {
    return "human_intervention_after_pickup";
  }
  if (routedPayloadInvalidatedByModeratorOverride(payload)) {
    return "moderator_override_after_pickup";
  }
  return "";
}

function routedTurnInvalidatedByHumanIntervention(turnState) {
  if (!turnState?.routedText) {
    return false;
  }
  const marker = readJsonFile(humanInterventionPath);
  const acceptedRouteKey = String(marker?.accepted_route_key || "").trim();
  const acceptedTarget = safeFileSegment(marker?.target_bot_id || "").toLowerCase();
  const turnAcceptedRouteKey = String(turnState.acceptedHumanInterventionRouteKey || "").trim();
  const turnAcceptedTarget = safeFileSegment(turnState.acceptedHumanInterventionTargetBotId || turnState.routedTargetBotId || "").toLowerCase();
  if (
    acceptedRouteKey
    && turnAcceptedRouteKey
    && acceptedRouteKey === turnAcceptedRouteKey
    && (!acceptedTarget || !turnAcceptedTarget || acceptedTarget === turnAcceptedTarget)
  ) {
    return false;
  }
  const markerMs = Number(marker?.created_at_ms || 0);
  return markerMs > Number(turnState.humanInterventionMarkerMs || 0);
}

function routedTurnInvalidatedByModeratorOverride(turnState) {
  if (!turnState?.routedText) {
    return false;
  }
  const startedAtMs = Number(turnState.startedAtMs || 0);
  const reason = moderatorOverrideReasonSince(startedAtMs);
  if (!reason) {
    return false;
  }
  if (turnState.replyFloorClaimed && hasActivePlaybackForTurn(turnState.turnId)) {
    return false;
  }
  return true;
}

function routedTurnModeratorStateInvalidationReason(turnState) {
  if (!turnState?.routedText) {
    return "";
  }
  if (turnState.manualCallOn) {
    return "";
  }
  const startedAtMs = Number(turnState.startedAtMs || 0);
  const manualReason = moderatorOverrideReasonSince(startedAtMs);
  if (manualReason) {
    if (turnState.replyFloorClaimed && hasActivePlaybackForTurn(turnState.turnId)) {
      return "";
    }
    return `manual_override:${manualReason}`;
  }
  if (hasActivePlaybackForTurn(turnState.turnId)) {
    return "";
  }
  const target = safeFileSegment(
    turnState.routedTargetBotId
    || turnState?.roomRouterDecision?.target_bot_id
    || ""
  ).toLowerCase();
  if (!target) {
    return "";
  }
  const state = readModeratorState();
  const currentBot = safeFileSegment(state?.current_bot_id || "").toLowerCase();
  const currentTurnId = String(state?.current_bot_turn_id || "");
  if (currentBot === botInstanceId && currentTurnId && currentTurnId === String(turnState.turnId || "")) {
    return "";
  }
  if (moderatorBotTargetIsMuted(target, state)) {
    return `target_muted:${target}`;
  }
  const pendingBot = moderatorPendingBotRoute(state);
  if (pendingBot?.target) {
    return pendingBot.target === target ? "" : `next_changed:${pendingBot.target}`;
  }
  const pendingHuman = moderatorPendingHumanRoute(state);
  if (pendingHuman?.userId) {
    return `next_changed:human:${pendingHuman.userId}`;
  }
  return "next_cleared";
}

function routedTurnInvalidatedByModeratorState(turnState) {
  return Boolean(routedTurnModeratorStateInvalidationReason(turnState));
}

function moderatorOverrideReasonSince(startedAtMs) {
  const markerMs = Number(startedAtMs || 0);
  if (!Number.isFinite(markerMs) || markerMs <= 0) {
    return "";
  }
  const state = readModeratorState();
  const clearPendingMs = String(state?.last_command || "") === "clear_pending"
    ? Number(state?.last_command_at_ms || 0)
    : 0;
  if (clearPendingMs > markerMs) {
    return "clear_pending";
  }
  const pendingHuman = moderatorPendingHumanRoute(state);
  if (Number(pendingHuman?.createdAtMs || 0) > markerMs) {
    return `manual_human_next:${pendingHuman.name || pendingHuman.userId || "unknown"}`;
  }
  const currentHuman = moderatorCurrentHumanRoute(state);
  if (Number(currentHuman?.createdAtMs || 0) > markerMs) {
    return `manual_human_current:${currentHuman.name || currentHuman.userId || "unknown"}`;
  }
  const manual = moderatorManualPendingRoute(state);
  if (manual?.target && Number(manual.createdAtMs || 0) > markerMs) {
    return `manual_next:${manual.target}`;
  }
  return "";
}

function completedBotTextRouteModeratorOverrideReason(turnState, routeStartedAtMs) {
  return moderatorOverrideReasonSince(Number(routeStartedAtMs || turnState?.startedAtMs || 0));
}

function noRouteDecisionAfterModeratorOverride(turn, routeKey, reason) {
  const inputText = String(turn?.inputText || "").trim();
  return {
    ok: true,
    answer: false,
    target_bot_id: "",
    reason: `moderator_override:${String(reason || "changed")}`,
    route_key: String(routeKey || ""),
    input_text: inputText,
    context_input_text: inputText ? contextLineForTurn(turn, inputText) : "",
    speech_accepted: Boolean(inputText),
    moderator_override: true,
    created_at_ms: Date.now(),
    source: "room_router"
  };
}

function dropRoutedTurn(turnState, turnId, reason) {
  if (!turnState || turnState.replyFloorDenied) {
    return;
  }
  turnState.replyFloorDenied = true;
  const effectiveTurnId = String(turnId || turnState.turnId || "");
  if (Array.isArray(turnState.preparedReplyChunks)) {
    turnState.preparedReplyChunks.length = 0;
  }
  if (turnState.preparedFloorTimer) {
    clearTimeout(turnState.preparedFloorTimer);
    turnState.preparedFloorTimer = null;
  }
  removeQueuedPlaybackForTurn(effectiveTurnId, reason);
  releaseReplyFloor(effectiveTurnId, { force: true, reason: `drop_routed_turn:${reason || "unknown"}` });
  forgetReplyTurnComplete(effectiveTurnId);
  replyProgressByTurnId.delete(effectiveTurnId);
  if (activeReplyProgress === turnState || (effectiveTurnId && String(activeReplyProgress?.turnId || "") === effectiveTurnId)) {
    activeReplyProgress = null;
  }
  clearCurrentBotModeratorState(`drop_routed_turn:${reason || "unknown"}`, effectiveTurnId);
  if (activeNcTurnId === effectiveTurnId && activeNcAbortController) {
    try {
      activeNcAbortController.abort();
    } catch {
      // Ignore abort races.
    }
    activeNcAbortController = null;
    activeNcTurnId = null;
  }
  console.log(`[DiscordBridgeDecision] Dropped routed reply: ${reason} (turn=${effectiveTurnId})`);
}

function clearReplyProgressForTurn(turnId, reason) {
  const id = String(turnId || "");
  if (!id) {
    return false;
  }
  const candidates = [];
  const mapped = replyProgressByTurnId.get(id);
  if (mapped) {
    candidates.push(mapped);
  }
  if (activeReplyProgress && String(activeReplyProgress.turnId || "") === id && !candidates.includes(activeReplyProgress)) {
    candidates.push(activeReplyProgress);
  }
  for (const progress of candidates) {
    if (progress.preparedFloorTimer) {
      clearTimeout(progress.preparedFloorTimer);
      progress.preparedFloorTimer = null;
    }
    if (Array.isArray(progress.preparedReplyChunks)) {
      progress.preparedReplyChunks.length = 0;
    }
    progress.replyFloorDenied = true;
  }
  replyProgressByTurnId.delete(id);
  if (activeReplyProgress && String(activeReplyProgress.turnId || "") === id) {
    activeReplyProgress = null;
  }
  forgetReplyTurnComplete(id);
  playbackDebug("reply_progress_cleared", { turnId: id, reason: reason || "" });
  return candidates.length > 0;
}

function clearAllReplyProgress(reason) {
  const seen = new Set();
  for (const progress of replyProgressByTurnId.values()) {
    if (progress) {
      seen.add(progress);
    }
  }
  if (activeReplyProgress) {
    seen.add(activeReplyProgress);
  }
  for (const progress of seen) {
    if (progress.preparedFloorTimer) {
      clearTimeout(progress.preparedFloorTimer);
      progress.preparedFloorTimer = null;
    }
    if (Array.isArray(progress.preparedReplyChunks)) {
      progress.preparedReplyChunks.length = 0;
    }
    progress.replyFloorDenied = true;
    forgetReplyTurnComplete(progress.turnId);
  }
  replyProgressByTurnId.clear();
  activeReplyProgress = null;
  completedReplyTurnIds.clear();
  playbackDebug("all_reply_progress_cleared", { reason: reason || "" });
}

function dropRoutedTurnAfterHumanIntervention(turnState, turnId, reason) {
  dropRoutedTurn(turnState, turnId, `human intervention: ${reason}`);
}

function dropRoutedTurnAfterModeratorOverride(turnState, turnId, reason) {
  dropRoutedTurn(turnState, turnId, `manual moderator override: ${reason}`);
}

function dropRoutedTurnAfterModeratorStateChange(turnState, turnId, reason) {
  dropRoutedTurn(turnState, turnId, `moderator state changed: ${reason}`);
}

function routeDecisionForThisBot(decision) {
  lastRouteDecision = decision && typeof decision === "object" ? decision : null;
  writeRuntimeStatus("route_decision");
  const answer = Boolean(decision?.answer);
  const target = safeFileSegment(decision?.target_bot_id || "").toLowerCase();
  const speakerBotId = safeFileSegment(decision?.speaker_bot_id || "").toLowerCase();
  const reason = String(decision?.reason || "room_router").trim();
  const acceptedSpeech = Boolean(
    decision?.speech_accepted !== false
    && String(decision?.input_text || "").trim()
    && !isProtectedMicContextOnlyDecision(decision)
  );
  if (!answer || !target) {
    return { shouldProceed: false, reason, decision, acceptedSpeech };
  }
  if (moderatorMutedBotIds().has(target)) {
    const mutedReason = `moderator_muted:${reason}`;
    console.log(`[DiscordBridgeModerator] Route target is muted: target=${target}`);
    return { shouldProceed: false, reason: mutedReason, decision, acceptedSpeech };
  }
  if (speakerBotId && target === speakerBotId && roomRouterSelfRoutePolicy !== "allow") {
    const selfReason = `self_route_${roomRouterSelfRoutePolicy}:${reason}`;
    console.log(`[DiscordBridgeRouter] Self-route blocked by policy: speaker=${speakerBotId}, target=${target}, policy=${roomRouterSelfRoutePolicy}`);
    return { shouldProceed: false, reason: selfReason, decision, acceptedSpeech };
  }
  if (target !== botInstanceId) {
    console.log(`[DiscordBridgeRouter] Skipped bot ${botInstanceId}; selected=${target}, reason=${reason}`);
    return { shouldProceed: false, reason: `selected_${target}`, decision, acceptedSpeech };
  }
  console.log(`[DiscordBridgeRouter] Selected this bot: ${botInstanceId}, reason=${reason}`);
  return { shouldProceed: true, reason, decision, acceptedSpeech };
}

function waitForRouteDecision(resultPath) {
  const deadline = Date.now() + roomRouterDecisionTimeoutMs;
  return new Promise((resolve) => {
    const check = () => {
      const payload = readJsonFile(resultPath);
      if (payload) {
        resolve(payload);
        return;
      }
      if (Date.now() >= deadline) {
        resolve(null);
        return;
      }
      setTimeout(check, 75);
    };
    check();
  });
}

function tryCreateRouteLock(lockPath) {
  try {
    writeFileSync(lockPath, JSON.stringify({ owner: botInstanceId, pid: process.pid, created_at: Date.now() }), {
      encoding: "utf8",
      flag: "wx"
    });
    return true;
  } catch (error) {
    if (error?.code !== "EEXIST") {
      console.warn("[DiscordBridgeRouter] Could not create route lock; waiting for another instance:", error?.message || error);
    }
    return false;
  }
}

function roomRouteKey(userId, startedAtMs) {
  const bucket = Math.floor(Number(startedAtMs || Date.now()) / roomRouterWindowMs);
  return `${safeFileSegment(voiceChannelId)}_${safeFileSegment(userId)}_${bucket}`;
}

function roomRouteResultPath(routeKey) {
  return join(turnDir, `room_route_${safeFileSegment(routeKey)}.json`);
}

function readJsonFile(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function readRoomContext() {
  const payload = readJsonFile(roomContextPath);
  return Array.isArray(payload?.entries) ? payload.entries.slice(-20) : [];
}

function resetRoomContextOnStartup() {
  if (persistRoomContextBetweenRestarts) {
    console.log("[DiscordBridgeRouter] Room context persistence enabled; keeping shared room context across restart.");
    return;
  }
  try {
    rmSync(roomContextPath, { force: true });
    console.log("[DiscordBridgeRouter] Cleared shared room context on startup.");
  } catch (error) {
    console.warn(`[DiscordBridgeRouter] Could not clear shared room context on startup: ${error?.message || error}`);
  }
}

function appendRoomContextFromDecision(decision) {
  const content = String(decision?.context_input_text || "").trim();
  if (!content) {
    return;
  }
  const payload = readJsonFile(roomContextPath) || {};
  const entries = Array.isArray(payload.entries) ? payload.entries : [];
  entries.push({
    role: "user",
    content,
    route_key: String(decision?.route_key || ""),
    target_bot_id: String(decision?.target_bot_id || ""),
    answer: Boolean(decision?.answer),
    reason: String(decision?.reason || ""),
    created_at: new Date().toISOString()
  });
  const trimmed = entries.slice(-200);
  writeFileSync(roomContextPath, JSON.stringify({ entries: trimmed }, null, 2), "utf8");
}

async function broadcastRoomTurnToBotHistories(decision, turn, routeKey, options = {}) {
  if (bridgeMode !== "http") {
    return;
  }
  const contextInputText = String(decision?.context_input_text || "").trim();
  const inputText = String(decision?.input_text || turn?.inputText || "").trim();
  if (decision?.speech_accepted === false || (!contextInputText && !inputText)) {
    return;
  }
  const selectedTarget = safeFileSegment(decision?.target_bot_id || "").toLowerCase();
  const speakerBotId = safeFileSegment(turn?.speakerBotId || "").toLowerCase();
  const includeSelectedTarget = Boolean(options?.includeSelectedTarget);
  const onlyCandidateIds = Array.isArray(options?.onlyCandidateIds)
    ? new Set(options.onlyCandidateIds.map((item) => safeFileSegment(item || "").toLowerCase()).filter(Boolean))
    : null;
  const candidates = liveRoomRouterCandidateBots();
  const jobs = [];
  for (const candidate of candidates) {
    const candidateId = safeFileSegment(candidate?.id || candidate?.name || "").toLowerCase();
    if (!candidateId) {
      continue;
    }
    if (onlyCandidateIds && !onlyCandidateIds.has(candidateId)) {
      continue;
    }
    if (!includeSelectedTarget && decision?.answer && selectedTarget && candidateId === selectedTarget) {
      continue;
    }
    if (speakerBotId && candidateId === speakerBotId) {
      continue;
    }
    const endpoint = recordUserTurnEndpointForCandidate(candidate);
    if (!endpoint) {
      continue;
    }
    jobs.push(recordUserTurnForCandidate(endpoint, candidateId, {
      route_key: String(routeKey || decision?.route_key || ""),
      context_input_text: contextInputText,
      input_text: inputText,
      speaker_name: String(turn?.speakerName || ""),
      user_id: String(turn?.userId || ""),
      captured_at: String(turn?.capturedAt || new Date().toISOString()),
      source_bot_id: botInstanceId,
      speaker_bot_id: String(turn?.speakerBotId || ""),
      target_bot_id: String(decision?.target_bot_id || ""),
      reason: String(decision?.reason || "room_route")
    }));
  }
  if (!jobs.length) {
    return;
  }
  const results = await Promise.allSettled(jobs);
  const recorded = results.filter((item) => item.status === "fulfilled" && item.value?.recorded).length;
  const skipped = results.length - recorded;
  console.log(`[DiscordBridgeRouter] Broadcast room turn to bot histories: recorded=${recorded}, skipped=${skipped}`);
}

function recordUserTurnEndpointForCandidate(candidate) {
  const runtime = candidate?.nc_runtime && typeof candidate.nc_runtime === "object" ? candidate.nc_runtime : {};
  const explicit = String(candidate?.http_endpoint || runtime.http_endpoint || runtime.endpoint || "").trim();
  if (explicit) {
    return explicit.replace(/\/turn\/?$/i, "/record_user_turn");
  }
  const port = Number.parseInt(String(candidate?.runtime_port || runtime.port || ""), 10);
  if (!Number.isFinite(port) || port <= 0) {
    return "";
  }
  const host = String(candidate?.runtime_host || runtime.host || "127.0.0.1").trim() || "127.0.0.1";
  return `http://${host}:${port}/record_user_turn`;
}

async function recordUserTurnForCandidate(endpoint, candidateId, payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1500);
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: ncJsonHeaders(),
      signal: controller.signal,
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      console.warn(`[DiscordBridgeRouter] Could not record human turn for ${candidateId}: ${JSON.stringify(data)}`);
      return { recorded: false };
    }
    return { recorded: Boolean(data.recorded) };
  } catch (error) {
    console.warn(`[DiscordBridgeRouter] Could not record human turn for ${candidateId}: ${error?.message || error}`);
    return { recorded: false };
  } finally {
    clearTimeout(timer);
  }
}

async function processCommandInbox() {
  if (!commandInboxPath) {
    return;
  }
  let text = "";
  try {
    text = readFileSync(commandInboxPath, "utf8");
    rmSync(commandInboxPath, { force: true });
  } catch {
    return;
  }
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  for (const line of lines) {
    let command = null;
    try {
      command = JSON.parse(line);
    } catch (error) {
      console.warn("[DiscordBridgeControl] Ignoring invalid command:", error?.message || error);
      continue;
    }
    await handleLiveCommand(command);
  }
}

async function handleLiveCommand(command) {
  const action = String(command?.action || "").trim().toLowerCase();
  console.log(`[DiscordBridgeControl] Command received: ${action || "(empty)"}`);
  if (action === "stop_speech") {
    interruptCurrentReply("live stop speech command", { respectImmunity: false, respectModeratorProtection: false, abortActiveRequest: true });
    writeRuntimeStatus("speech_stopped");
    return;
  }
  if (action === "clear_queue") {
    clearPlaybackQueue("live clear queue command");
    writeRuntimeStatus("queue_cleared");
    return;
  }
  if (action === "reset_context") {
    resetRoomContext("live reset context command");
    writeRuntimeStatus("context_reset");
    return;
  }
  if (action === "disconnect") {
    await disconnectVoice("live disconnect command");
    return;
  }
  if (action === "reconnect") {
    await reconnectVoice("live reconnect command");
    return;
  }
  if (action === "reload_settings") {
    reloadLiveSettings();
    writeRuntimeStatus("settings_reloaded");
    return;
  }
  if (action === "send_message") {
    await speakLiveMessage(command?.payload || {});
    return;
  }
  if (action === "moderator_call_on") {
    await callOnThisBot(command?.payload || {});
    return;
  }
  if (action.startsWith("moderator_")) {
    await handleModeratorCommand(action, command?.payload || {});
    return;
  }
  console.warn(`[DiscordBridgeControl] Unknown command: ${action}`);
}

async function handleModeratorCommand(action, payload = {}) {
  const target = safeFileSegment(payload?.target_bot_id || payload?.bot_id || "").toLowerCase();
  const speakerUserId = String(payload?.speaker_user_id || payload?.user_id || "").trim();
  let liveHuman = null;
  if (["moderator_route_next", "moderator_give_floor", "moderator_mute", "moderator_unmute", "moderator_mute_all_except"].includes(action)) {
    if (!target || target === "default") {
      lastErrorText = "Moderator command requires a target bot.";
      console.warn(`[DiscordBridgeModerator] ${lastErrorText}`);
      writeRuntimeStatus("moderator_error");
      return;
    }
    if (!moderatorLiveTarget(target)) {
      lastErrorText = `Moderator target ${target} is not currently connected in the voice channel.`;
      console.warn(`[DiscordBridgeModerator] ${lastErrorText}`);
      writeRuntimeStatus("moderator_error");
      return;
    }
  }
  if (["moderator_route_next_human", "moderator_give_human_floor", "moderator_mute_human", "moderator_unmute_human"].includes(action)) {
    if (!speakerUserId) {
      lastErrorText = "Moderator human speaker command requires a Discord user id.";
      console.warn(`[DiscordBridgeModerator] ${lastErrorText}`);
      writeRuntimeStatus("moderator_error");
      return;
    }
    liveHuman = moderatorLiveHuman(speakerUserId);
    if (!liveHuman) {
      lastErrorText = `Human speaker ${speakerUserId} is not currently connected in the voice channel.`;
      console.warn(`[DiscordBridgeModerator] ${lastErrorText}`);
      writeRuntimeStatus("moderator_error");
      return;
    }
  }
  if (action === "moderator_route_next_human") {
    const speakerName = String(payload?.speaker_name || liveHuman?.name || speakerUserId).trim();
    discardPendingRoutedTextTurns(`manual moderator route_next_human:${speakerName}`);
    setHumanCurrentFromRoute(`human:${speakerUserId}`, {
      reason: String(payload?.reason || "manual moderator human route"),
      forcePending: true,
      muteReason: "moderator_route_next_human"
    });
    appendModeratorRecoveryStatus({
      last_next_target_bot_id: "",
      cooldown_remaining_ms: 0,
      last_error: ""
    });
    lastModeratorState = readModeratorState();
    maybeDropRoutedPreRenderAfterManualNext();
    await applyDiscordMuteEnforcement("moderator_route_next_human");
    return;
  }
  if (action === "moderator_give_human_floor") {
    const speakerName = String(payload?.speaker_name || liveHuman?.name || speakerUserId).trim();
    discardPendingRoutedTextTurns(`manual moderator give_human_floor:${speakerName}`);
    const state = updateModeratorState((current) => ({
      ...current,
      floor_speaker_user_id: speakerUserId,
      floor_speaker_name: speakerName,
      floor_target_bot_id: "",
      pending_route: {},
      route_next_target_bot_id: "",
      pending_human_route: {},
      route_next_speaker_user_id: "",
      route_next_speaker_name: "",
      current_human_route: {},
      current_speaker_user_id: "",
      current_speaker_name: "",
      last_command: `accept_human:${speakerName}`,
      last_error: ""
    }));
    console.log(`[DiscordBridgeModerator] Accepted human speaker locked to ${speakerName} (${speakerUserId}).`);
    lastModeratorState = state;
    maybeDropRoutedPreRenderAfterManualNext();
    await applyDiscordMuteEnforcement("moderator_give_human_floor");
    return;
  }
  if (action === "moderator_mute_human") {
    const speakerName = String(payload?.speaker_name || liveHuman?.name || speakerUserId).trim();
    const state = updateModeratorState((current) => {
      const muted = new Set((Array.isArray(current?.muted_speaker_user_ids) ? current.muted_speaker_user_ids : [])
        .map((value) => String(value || "").trim())
        .filter(Boolean));
      muted.add(speakerUserId);
      const pendingHuman = current?.pending_human_route && typeof current.pending_human_route === "object"
        ? current.pending_human_route
        : {};
      const currentHuman = current?.current_human_route && typeof current.current_human_route === "object"
        ? current.current_human_route
        : {};
      const clearsPending = String(pendingHuman?.speaker_user_id || "").trim() === speakerUserId;
      const clearsCurrent = String(currentHuman?.speaker_user_id || "").trim() === speakerUserId;
      const clearsFloor = String(current?.floor_speaker_user_id || "").trim() === speakerUserId;
      return {
        ...current,
        muted_speaker_user_ids: [...muted],
        ...(clearsPending
          ? {
              pending_human_route: {},
              route_next_speaker_user_id: "",
              route_next_speaker_name: ""
            }
          : {}),
        ...(clearsCurrent
          ? {
              current_human_route: {},
              current_speaker_user_id: "",
              current_speaker_name: ""
            }
          : {}),
        ...(clearsFloor
          ? {
              floor_speaker_user_id: "",
              floor_speaker_name: ""
            }
          : {}),
        last_command: `mute_human:${speakerName}`,
        last_error: ""
      };
    });
    console.log(`[DiscordBridgeModerator] Muted human participant ${speakerName} (${speakerUserId}).`);
    lastModeratorState = state;
    maybeDropRoutedPreRenderAfterManualNext();
    return;
  }
  if (action === "moderator_unmute_human") {
    const speakerName = String(payload?.speaker_name || liveHuman?.name || speakerUserId).trim();
    const state = updateModeratorState((current) => {
      const muted = new Set((Array.isArray(current?.muted_speaker_user_ids) ? current.muted_speaker_user_ids : [])
        .map((value) => String(value || "").trim())
        .filter(Boolean));
      muted.delete(speakerUserId);
      return { ...current, muted_speaker_user_ids: [...muted], last_command: `unmute_human:${speakerName}`, last_error: "" };
    });
    console.log(`[DiscordBridgeModerator] Unmuted human participant ${speakerName} (${speakerUserId}).`);
    lastModeratorState = state;
    return;
  }
  if (action === "moderator_set_current_interruption") {
    const allowed = Boolean(payload?.allow_current_interruption);
    const state = updateModeratorState((current) => ({
      ...current,
      allow_current_interruption: allowed,
      last_command: allowed ? "allow_current_interruption" : "protect_current_speaker",
      last_error: ""
    }));
    console.log(`[DiscordBridgeModerator] Current speaker interruption ${allowed ? "allowed" : "blocked"} by moderator.`);
    lastModeratorState = state;
    return;
  }
  if (action === "moderator_set_enforcer") {
    if (target && target !== botInstanceId) {
      console.log(`[DiscordBridgeModerator] Ignoring hard moderator selection for ${target}; this bot is ${botInstanceId}.`);
      return;
    }
    if (!activeVoiceChannel) {
      lastErrorText = "Moderator bot must be connected to the voice channel before hard moderation can be enabled.";
      console.warn(`[DiscordBridgeModerator] ${lastErrorText}`);
      writeRuntimeStatus("moderator_error");
      return;
    }
    const state = updateModeratorState((current) => ({
      ...current,
      enforcer_bot_id: botInstanceId,
      enforcer_bot_name: botDisplayName,
      enforcer_discord_user_id: String(client.user?.id || ""),
      last_command: `hard_moderator:${botInstanceId}`,
      last_error: ""
    }));
    console.log(`[DiscordBridgeModerator] ${botDisplayName} appointed as Discord hard moderator.`);
    lastModeratorState = state;
    await applyDiscordMuteEnforcement("moderator_set_enforcer");
    return;
  }
  if (action === "moderator_clear_enforcer") {
    await clearDiscordMuteLedger("moderator_clear_enforcer");
    const state = updateModeratorState((current) => ({
      ...current,
      enforcer_bot_id: "",
      enforcer_bot_name: "",
      enforcer_discord_user_id: "",
      enforce_discord_mute: false,
      discord_muted_user_ids: [],
      last_command: "clear_hard_moderator",
      last_error: ""
    }));
    console.log("[DiscordBridgeModerator] Discord hard moderator cleared.");
    lastModeratorState = state;
    return;
  }
  if (action === "moderator_set_mute_enforcement") {
    const state = readModeratorState();
    if (!isModeratorEnforcer(state)) {
      lastErrorText = "Only the appointed hard moderator bot can change Discord mute enforcement.";
      console.warn(`[DiscordBridgeModerator] ${lastErrorText}`);
      writeRuntimeStatus("moderator_error");
      return;
    }
    const enabled = Boolean(payload?.enabled);
    const nextState = updateModeratorState((current) => ({
      ...current,
      enforce_discord_mute: enabled,
      last_command: enabled ? "enable_discord_mute_enforcement" : "disable_discord_mute_enforcement",
      last_error: ""
    }));
    console.log(`[DiscordBridgeModerator] Discord mute enforcement ${enabled ? "enabled" : "disabled"}.`);
    lastModeratorState = nextState;
    if (enabled) {
      await applyDiscordMuteEnforcement("moderator_set_mute_enforcement");
    } else {
      await clearDiscordMuteLedger("moderator_set_mute_enforcement");
    }
    return;
  }
  if (action === "moderator_route_next") {
    discardPendingRoutedTextTurns(`manual moderator route_next:${target}`);
    const stateBefore = readModeratorState();
    if (safeFileSegment(stateBefore?.current_bot_id || "").toLowerCase() === target) {
      const state = updateModeratorState((current) => ({
        ...current,
        pending_route: {},
        route_next_target_bot_id: "",
        pending_human_route: {},
        route_next_speaker_user_id: "",
        route_next_speaker_name: "",
        last_command: `current_bot:${target}`,
        last_error: ""
      }));
      console.log(`[DiscordBridgeModerator] Bot ${target} is already current; pending route cleared.`);
      lastModeratorState = state;
      maybeDropRoutedPreRenderAfterManualNext();
      await applyDiscordMuteEnforcement("moderator_route_next_current_bot");
      return;
    }
    const state = updateModeratorState((current) => ({
      ...current,
      pending_route: {
        target_bot_id: target,
        created_at_ms: Date.now(),
        source: "human_moderator",
        manual: true,
        user_command: true,
        reason: String(payload?.reason || "manual moderator route")
      },
      route_next_target_bot_id: target,
      pending_human_route: {},
      route_next_speaker_user_id: "",
      route_next_speaker_name: "",
      last_command: `route_next:${target}`,
      last_error: ""
    }));
    console.log(`[DiscordBridgeModerator] Next route queued for ${target}.`);
    lastModeratorState = state;
    maybeDropRoutedPreRenderAfterManualNext();
    await applyDiscordMuteEnforcement("moderator_route_next");
    return;
  }
  if (action === "moderator_give_floor") {
    discardPendingRoutedTextTurns(`manual moderator give_floor:${target}`);
    const state = updateModeratorState((current) => ({
      ...current,
      floor_target_bot_id: target,
      floor_speaker_user_id: "",
      floor_speaker_name: "",
      pending_route: {},
      route_next_target_bot_id: "",
      pending_human_route: {},
      route_next_speaker_user_id: "",
      route_next_speaker_name: "",
      current_human_route: {},
      current_speaker_user_id: "",
      current_speaker_name: "",
      last_command: `allow_bot:${target}`,
      last_error: ""
    }));
    console.log(`[DiscordBridgeModerator] Allowed bot speaker locked to ${target}.`);
    lastModeratorState = state;
    maybeDropRoutedPreRenderAfterManualNext();
    await applyDiscordMuteEnforcement("moderator_give_floor");
    return;
  }
  if (action === "moderator_mute") {
    discardPendingRoutedTextTurns(`manual moderator mute:${target}`);
    const state = updateModeratorState((current) => {
      const muted = new Set(moderatorBotIds(current?.muted_bot_ids));
      muted.add(target);
      const pendingTarget = safeFileSegment(current?.pending_route?.target_bot_id || "").toLowerCase();
      const floorTarget = safeFileSegment(current?.floor_target_bot_id || "").toLowerCase();
      const only = moderatorBotIds(current?.only_bot_ids).filter((item) => item !== target);
      return {
        ...current,
        muted_bot_ids: [...muted],
        only_bot_ids: only,
        ...(pendingTarget === target
          ? {
              pending_route: {},
              route_next_target_bot_id: ""
            }
          : {}),
        ...(floorTarget === target
          ? {
              floor_target_bot_id: ""
            }
          : {}),
        last_command: `mute:${target}`,
        last_error: ""
      };
    });
    console.log(`[DiscordBridgeModerator] Muted ${target}.`);
    lastModeratorState = state;
    maybeDropRoutedPreRenderAfterManualNext();
    return;
  }
  if (action === "moderator_unmute") {
    const state = updateModeratorState((current) => {
      const muted = new Set(moderatorBotIds(current?.muted_bot_ids));
      muted.delete(target);
      return { ...current, muted_bot_ids: [...muted], only_bot_ids: [], last_command: `unmute:${target}`, last_error: "" };
    });
    console.log(`[DiscordBridgeModerator] Unmuted ${target}.`);
    lastModeratorState = state;
    return;
  }
  if (action === "moderator_mute_all_except") {
    discardPendingRoutedTextTurns(`manual moderator only:${target}`);
    const state = updateModeratorState((current) => ({
      ...current,
      only_bot_ids: [target],
      muted_bot_ids: [],
      floor_target_bot_id: target,
      floor_speaker_user_id: "",
      floor_speaker_name: "",
      pending_route: {},
      route_next_target_bot_id: "",
      pending_human_route: {},
      route_next_speaker_user_id: "",
      route_next_speaker_name: "",
      current_human_route: {},
      current_speaker_user_id: "",
      current_speaker_name: "",
      last_command: `only:${target}`,
      last_error: ""
    }));
    console.log(`[DiscordBridgeModerator] Muted all except ${target}.`);
    lastModeratorState = state;
    maybeDropRoutedPreRenderAfterManualNext();
    return;
  }
  if (action === "moderator_clear_pending") {
    discardPendingRoutedTextTurns("manual moderator clear_pending");
    const commandAtMs = Date.now();
    const state = updateModeratorState((current) => ({
      ...current,
      pending_route: {},
      route_next_target_bot_id: "",
      pending_human_route: {},
      route_next_speaker_user_id: "",
      route_next_speaker_name: "",
      last_command: "clear_pending",
      last_command_at_ms: commandAtMs,
      last_error: ""
    }));
    appendModeratorRecoveryStatus({
      last_next_target_bot_id: "",
      cooldown_remaining_ms: 0,
      last_error: ""
    });
    console.log("[DiscordBridgeModerator] Pending moderator route cleared.");
    lastModeratorState = readModeratorState();
    maybeDropRoutedPreRenderAfterManualNext();
    return;
  }
  if (action === "moderator_clear_floor") {
    const state = updateModeratorState((current) => ({
      ...current,
      floor_target_bot_id: "",
      floor_speaker_user_id: "",
      floor_speaker_name: "",
      only_bot_ids: [],
      current_human_route: {},
      current_speaker_user_id: "",
      current_speaker_name: "",
      last_command: "clear_speaker_locks",
      last_error: ""
    }));
    console.log("[DiscordBridgeModerator] Moderator speaker locks cleared.");
    lastModeratorState = state;
    return;
  }
  if (action === "moderator_clear") {
    discardPendingRoutedTextTurns("manual moderator clear");
    writeModeratorState({
      enabled: true,
      pending_route: {},
      route_next_target_bot_id: "",
      pending_human_route: {},
      route_next_speaker_user_id: "",
      route_next_speaker_name: "",
      current_bot_id: "",
      current_bot_name: "",
      current_bot_discord_user_id: "",
      current_bot_turn_id: "",
      current_human_route: {},
      current_speaker_user_id: "",
      current_speaker_name: "",
      floor_target_bot_id: "",
      floor_speaker_user_id: "",
      floor_speaker_name: "",
      muted_bot_ids: [],
      only_bot_ids: [],
      muted_speaker_user_ids: [],
      allow_current_interruption: false,
      enforcer_bot_id: readModeratorState()?.enforcer_bot_id || "",
      enforcer_bot_name: readModeratorState()?.enforcer_bot_name || "",
      enforcer_discord_user_id: readModeratorState()?.enforcer_discord_user_id || "",
      enforce_discord_mute: Boolean(readModeratorState()?.enforce_discord_mute),
      discord_muted_user_ids: readModeratorState()?.discord_muted_user_ids || [],
      last_command: "clear",
      last_error: ""
    });
    appendModeratorRecoveryStatus({
      last_next_target_bot_id: "",
      cooldown_remaining_ms: 0,
      last_error: ""
    });
    console.log("[DiscordBridgeModerator] Moderator state cleared.");
    lastModeratorState = readModeratorState();
    maybeDropRoutedPreRenderAfterManualNext();
    await applyDiscordMuteEnforcement("moderator_clear");
    return;
  }
  console.warn(`[DiscordBridgeModerator] Unknown moderator command: ${action}`);
}

async function callOnThisBot(payload = {}) {
  if (bridgeMode !== "http") {
    console.warn("[DiscordBridgeModerator] Call On Target requires HTTP bridge mode.");
    return;
  }
  const target = safeFileSegment(payload?.target_bot_id || payload?.bot_id || botInstanceId).toLowerCase();
  if (target && target !== botInstanceId) {
    console.log(`[DiscordBridgeModerator] Ignoring call-on for ${target}; this bot is ${botInstanceId}.`);
    return;
  }
  const instruction = String(payload?.text || payload?.message || "").trim();
  const inputText = instruction
    ? `Human moderator asks ${botDisplayName} to respond and says: ${instruction}`
    : `Human moderator gives ${botDisplayName} the floor. Respond now, continuing naturally from the latest shared room context.`;
  const routeKey = `moderator_call_${safeFileSegment(voiceChannelId)}_${botInstanceId}_${Date.now()}_${randomUUID()}`;
  updateModeratorState((current) => ({
    ...current,
    last_call_on_bot_id: botInstanceId,
    last_call_on_bot_name: botDisplayName,
    last_call_on_at_ms: Date.now(),
    last_command: `call_on:${botInstanceId}`,
    last_error: ""
  }));
  console.log(
    `[DiscordBridgeModerator] Calling on ${botDisplayName}: ${previewText(inputText, 120)}`
  );
  await handleHttpNcTurn({
    userId: "human_moderator",
    speakerName: "Human Moderator",
    inputText,
    durationSeconds: 0,
    capturedAt: new Date().toISOString(),
    routeKey,
    routedText: true,
    manualCallOn: true,
    prepareAhead: false,
    roomRouterDecision: {
      answer: true,
      target_bot_id: botInstanceId,
      reason: "human_moderator_call_on"
    }
  });
}

async function speakLiveMessage(payload = {}) {
  const text = String(payload?.text || payload?.message || "").trim();
  if (!text) {
    console.warn("[DiscordBridgeControl] Send Message ignored: message text is empty.");
    return;
  }
  const turnId = `manual_${botInstanceId}_${Date.now()}_${randomUUID()}`;
  const turnState = {
    generation: playbackGeneration,
    startedAtMs: Date.now(),
    interruptedPlayback: false,
    pendingInterruptSent: false,
    routedText: false,
    waitForReplyFloor: Boolean(coordinateBotReplies && replyFloorMode !== "disabled"),
    humanInterventionMarkerMs: latestHumanInterventionMs(),
    initialPlaybackBufferReleased: true,
    preparedReplyChunks: [],
    readyChunks: 0,
    playedChunks: 0,
    totalChunks: 0,
    replyComplete: true,
    turnId
  };
  activeReplyProgress = turnState;
  replyProgressByTurnId.set(turnId, turnState);
  playbackDebug("manual_speak_start", {
    turnId,
    text: previewText(text),
    waitForReplyFloor: turnState.waitForReplyFloor,
    endpoint: ncSpeakEndpoint
  });
  let response;
  try {
    response = await fetch(ncSpeakEndpoint, {
      method: "POST",
      headers: ncJsonHeaders(),
      body: JSON.stringify({
        turn_id: turnId,
        text
      })
    });
  } catch (error) {
    lastErrorText = String(error?.message || error || "manual speak failed");
    console.error("[DiscordBridgeControl] Send Message failed:", error);
    writeRuntimeStatus("manual_speak_failed");
    return;
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.ok) {
    lastErrorText = String(result?.error || response.statusText || "manual speak failed");
    console.error("[DiscordBridgeControl] Send Message failed:", result);
    writeRuntimeStatus("manual_speak_failed");
    return;
  }
  if (result.skipped) {
    console.log(`[DiscordBridgeControl] Send Message skipped: ${result.reason || "unknown"}`);
    writeRuntimeStatus("manual_speak_skipped");
    return;
  }
  const replyChunks = Array.isArray(result.reply_chunks)
    ? result.reply_chunks.filter((chunk) => String(chunk?.reply_wav_path || "").trim())
    : [];
  if (replyChunks.length <= 0 && String(result.reply_wav_path || "").trim()) {
    replyChunks.push({
      reply_wav_path: String(result.reply_wav_path || ""),
      reply_text: String(result.reply_text || text),
      chunk_index: 0
    });
  }
  if (replyChunks.length <= 0) {
    lastErrorText = "Send Message did not return a reply_wav_path.";
    console.warn(`[DiscordBridgeControl] ${lastErrorText}`);
    writeRuntimeStatus("manual_speak_failed");
    return;
  }
  markReplyProgressComplete(turnState, replyChunks.length);
  markReplyTurnComplete(turnId);
  for (const chunk of replyChunks) {
    const chunkIndex = Number.isFinite(Number(chunk.chunk_index)) ? Number(chunk.chunk_index) : replyChunks.indexOf(chunk);
    const replyWavPath = String(chunk.reply_wav_path || "");
    markReplyChunkReady(turnState, chunkIndex);
    if (!queueReplyWavPlaybackForTurn(turnState, turnId, replyWavPath, `Manual Discord message chunk ${chunkIndex + 1}`, {
      replyText: String(chunk.reply_text || ""),
      turnId
    })) {
      releaseUnplayedReplyFloor(turnState);
      return;
    }
  }
  publishCompletedBotReplyText(String(result.reply_text || text), turnState);
  console.log(`[DiscordBridgeControl] Send Message queued for ${botDisplayName}: ${previewText(text, 100)}`);
  writeRuntimeStatus("manual_speak_queued");
}

function clearPlaybackQueue(reason) {
  playbackGeneration += 1;
  playbackQueue.length = 0;
  currentPlaybackItem = null;
  deliveredReplyTextParts = [];
  clearAllReplyProgress(reason || "clear_playback");
  activePlaybackTurnId = null;
  activePlaybackStartedAtMs = 0;
  releaseReplyFloor("", { force: true, reason: `clear_playback:${reason || "unknown"}` });
  if (voicePlayer) {
    try {
      voicePlayer.stop(true);
    } catch {
      // Ignore player state races.
    }
  }
  playbackActive = false;
  clearCurrentBotModeratorState(`clear_playback:${reason || "unknown"}`);
  console.log(`[DiscordBridgeControl] Playback queue cleared: ${reason}`);
}

function resetRoomContext(reason) {
  try {
    rmSync(roomContextPath, { force: true });
    console.log(`[DiscordBridgeControl] Shared room context cleared: ${reason}`);
  } catch (error) {
    console.warn(`[DiscordBridgeControl] Could not clear shared room context: ${error?.message || error}`);
  }
}

async function disconnectVoice(reason) {
  await clearDiscordMuteLedger(`disconnect:${reason || "unknown"}`);
  clearPlaybackQueue(reason);
  releaseReplyFloor("", { force: true, reason: `disconnect:${reason || "unknown"}` });
  releaseCaptureOwner(`disconnect:${reason || "unknown"}`);
  try {
    activeVoiceConnection?.disconnect?.();
  } catch {
    // Fall through to destroy below.
  }
  try {
    activeVoiceConnection?.destroy?.();
  } catch {
    // Ignore Discord voice teardown races.
  }
  activeVoiceConnection = null;
  console.log(`[DiscordBridgeControl] Voice disconnected: ${reason}`);
  writeRuntimeStatus("disconnected");
}

async function reconnectVoice(reason) {
  try {
    let channel = activeVoiceChannel;
    if (!channel || !channel.isVoiceBased?.()) {
      channel = await client.channels.fetch(voiceChannelId);
    }
    if (!channel || !channel.isVoiceBased?.()) {
      console.warn("[DiscordBridgeControl] Reconnect requested but the configured voice channel is unavailable.");
      writeRuntimeStatus("reconnect_unavailable");
      return;
    }
    try {
      activeVoiceConnection?.destroy?.();
    } catch {
      // Ignore stale connection teardown races.
    }
    activeVoiceConnection = null;
    await connectVoiceChannel(channel, reason || "reconnect");
    console.log(`[DiscordBridgeControl] Voice reconnected: ${reason}`);
  } catch (error) {
    lastErrorText = String(error?.message || error || "reconnect failed");
    console.error("[DiscordBridgeControl] Voice reconnect failed:", error);
    writeRuntimeStatus("reconnect_failed");
  }
}

async function connectVoiceChannel(channel, reason) {
  activeVoiceChannel = channel;
  const guildId = configuredGuildId || channel.guild.id;
  console.log(`[DiscordBridge] Connecting voice channel "${channel.name}" (${voiceChannelId}) reason=${reason || "connect"}`);
  for (const [memberId, member] of channel.members || []) {
    cacheSpeakerName(memberId, member);
  }

  const connection = joinVoiceChannel({
    channelId: voiceChannelId,
    guildId,
    adapterCreator: channel.guild.voiceAdapterCreator,
    selfDeaf: false,
    selfMute: false
  });
  activeVoiceConnection = connection;
  await entersState(connection, VoiceConnectionStatus.Ready, 20_000);
  ensureVoicePlayer();
  connection.subscribe(voicePlayer);
  attachSpeechCapture(connection, guildId);
  console.log("[DiscordBridge] Voice connection ready.");
  writeRuntimeStatus("connected");
}

function ensureVoicePlayer() {
  if (voicePlayer) {
    return voicePlayer;
  }
  const player = createAudioPlayer();
  voicePlayer = player;
  player.on("stateChange", (oldState, newState) => {
    console.log(`[DiscordBridge] Audio player: ${oldState.status} -> ${newState.status}`);
  });
  player.on("error", (error) => {
    console.error("[DiscordBridge] Audio player error:", error);
    lastErrorText = String(error?.message || error || "audio player error");
    const failedTurnId = String(currentPlaybackItem?.turnId || activePlaybackTurnId || "");
    currentPlaybackItem = null;
    playbackActive = false;
    if (failedTurnId && !hasPendingPlaybackForTurn(failedTurnId)) {
      clearReplyProgressForTurn(failedTurnId, "audio_error");
      releaseReplyFloor(failedTurnId, { force: true, reason: "audio_error" });
      clearCurrentBotModeratorState("audio_error", failedTurnId);
      if (activePlaybackTurnId === failedTurnId) {
        activePlaybackTurnId = null;
        activePlaybackStartedAtMs = 0;
        deliveredReplyTextParts = [];
      }
    }
    writeRuntimeStatus("audio_error");
    pumpPlaybackQueue();
  });
  return player;
}

function attachSpeechCapture(connection, guildId) {
  connection.receiver.speaking.on("start", (userId) => {
    if (userId === client.user.id) {
      return;
    }
    if (!canAnswerUser(userId)) {
      return;
    }
    const speakerIsBot = isDiscordBotUser(userId);
    if (speakerIsBot && shouldUseDirectBotTextRouting()) {
      console.log(`[DiscordBridgeRouter] Ignoring bot audio start because direct bot text routing is enabled: user=${userId}`);
      return;
    }
    const protectedMicSpeechAllowed = !speakerIsBot
      && routeProtectedMicSpeech
      && moderatorProtectsRoutingFlow()
      && !moderatorHumanMuted(userId);
    if (!speakerIsBot && !moderatorAllowsHumanSpeaker(userId) && !protectedMicSpeechAllowed) {
      const floor = moderatorHumanFloor();
      const current = moderatorCurrentHumanRoute();
      const pending = moderatorPendingHumanRoute();
      const reason = moderatorHumanMuted(userId)
        ? "participant is muted"
        : moderatorBlocksSpeechInterruption()
          ? "current speaker is protected by moderator"
          : current
            ? `current speaker is ${current.name || current.userId || "unknown"}`
            : pending
              ? `next speaker is ${pending.name || pending.userId || "unknown"}`
              : `speaker lock is ${floor?.name || floor?.userId || "unknown"}`;
      console.log(`[DiscordBridgeModerator] Ignoring human capture: user=${userId}, reason=${reason}`);
      return;
    }
    if (protectedMicSpeechAllowed) {
      console.log(`[DiscordBridgeModerator] Capturing protected human speech for context without interrupting current: user=${userId}`);
    }
    const pendingInterrupt = pendingPlaybackInterrupt(`valid speech from user ${userId}`);
    if (pendingInterrupt) {
      pendingInterruptByUserId.set(String(userId), pendingInterrupt);
    }
    if (!speakerIsBot && !isCaptureOwner()) {
      console.log(`[DiscordBridgeCapture] Ignoring human capture on non-owner ${botInstanceId}; owner=${captureOwnerLabel()}`);
      monitorHumanSpeechForInterruption(connection, userId);
      return;
    }
    captureSpeechTurn(connection, userId, guildId);
  });
}

function reloadLiveSettings() {
  const fresh = loadJsonSettings();
  interruptReplyOnUserSpeech = asBool(setting(fresh, "playback.interrupt_reply_on_user_speech", interruptReplyOnUserSpeech));
  routeProtectedMicSpeech = asBool(
    setting(fresh, "playback.route_protected_mic_speech", setting(fresh, "tiny_mvp.route_protected_mic_speech", routeProtectedMicSpeech))
  );
  interruptAfterSeconds = nonNegativeFloat(setting(fresh, "playback.interrupt_after_seconds", interruptAfterSeconds), interruptAfterSeconds);
  interruptPauseAfterFailedProbeSeconds = nonNegativeFloat(
    setting(fresh, "playback.interrupt_pause_after_failed_probe_seconds", interruptPauseAfterFailedProbeSeconds),
    interruptPauseAfterFailedProbeSeconds
  );
  replyImmunitySeconds = nonNegativeFloat(setting(fresh, "playback.reply_immunity_seconds", replyImmunitySeconds), replyImmunitySeconds);
  discardBotSpeechOnHumanIntervention = asBool(setting(fresh, "playback.discard_bot_speech_on_human_intervention", discardBotSpeechOnHumanIntervention));
  coordinateBotReplies = asBool(setting(fresh, "playback.coordinate_bot_replies", coordinateBotReplies));
  replyFloorStaleSeconds = positiveFloat(setting(fresh, "playback.reply_floor_stale_seconds", replyFloorStaleSeconds), replyFloorStaleSeconds);
  initialReplyBufferChunks = Math.min(
    8,
    nonNegativeInt(setting(fresh, "playback.initial_buffer_chunks", initialReplyBufferChunks), initialReplyBufferChunks)
  );
  playbackDebugEnabled = asBool(setting(fresh, "playback.debug_logging", playbackDebugEnabled));
  roomRouterEnabled = asBool(setting(fresh, "room_router.enabled", roomRouterEnabled));
  roomRouterMode = String(setting(fresh, "room_router.mode", roomRouterMode) || roomRouterMode).trim().toLowerCase();
  roomRouterDefaultWhenUncertain = asBool(setting(fresh, "room_router.default_when_uncertain", roomRouterDefaultWhenUncertain));
  roomRouterHumanToBotRouting = asBool(setting(fresh, "room_router.human_to_bot_routing", roomRouterHumanToBotRouting));
  roomRouterBotToBotRouting = asBool(setting(fresh, "room_router.bot_to_bot_routing", roomRouterBotToBotRouting));
  roomRouterExcludeSpeakerFromTargets = asBool(setting(fresh, "room_router.exclude_speaker_from_targets", roomRouterExcludeSpeakerFromTargets));
  roomRouterAllowGroupInvitationRouting = asBool(setting(fresh, "room_router.allow_group_invitation_routing", roomRouterAllowGroupInvitationRouting));
  roomRouterAllowOpenRoomInvitationRouting = asBool(setting(fresh, "room_router.allow_open_room_invitation_routing", roomRouterAllowOpenRoomInvitationRouting));
  roomRouterSelfRoutePolicy = String(setting(fresh, "room_router.self_route_policy", roomRouterSelfRoutePolicy) || roomRouterSelfRoutePolicy).trim().toLowerCase();
  roomRouterDecisionTimeoutMs = Math.max(1000, Math.round(positiveFloat(setting(fresh, "room_router.decision_timeout_seconds", roomRouterDecisionTimeoutMs / 1000), roomRouterDecisionTimeoutMs / 1000) * 1000));
  roomRouterWindowMs = Math.max(500, Math.round(positiveInt(setting(fresh, "room_router.route_window_ms", roomRouterWindowMs), roomRouterWindowMs)));
  roomRouterCandidateBots = Array.isArray(setting(fresh, "room_router.candidate_bots", []))
    ? setting(fresh, "room_router.candidate_bots", [])
    : roomRouterCandidateBots;
  sharedCaptureOwnerEnabled = asBool(setting(fresh, "capture.shared_capture_owner_enabled", sharedCaptureOwnerEnabled));
  captureOwnerTtlMs = Math.max(
    3000,
    Math.round(positiveFloat(setting(fresh, "capture.owner_ttl_seconds", captureOwnerTtlMs / 1000), captureOwnerTtlMs / 1000) * 1000)
  );
  routeBotRepliesFromText = asBool(setting(fresh, "room_router.route_bot_replies_from_text", routeBotRepliesFromText));
  prepareRoutedBotRepliesAhead = asBool(setting(fresh, "room_router.prepare_bot_replies_ahead", prepareRoutedBotRepliesAhead));
  competingBotReplyPolicy = String(setting(fresh, "room_router.competing_bot_reply_policy", competingBotReplyPolicy) || competingBotReplyPolicy).trim().toLowerCase();
  replyFloorMode = String(setting(fresh, "room_router.reply_floor_mode", replyFloorMode) || replyFloorMode).trim().toLowerCase();
  deadAirRecoveryEnabled = asBool(setting(fresh, "room_router.dead_air_recovery.enabled", deadAirRecoveryEnabled));
  deadAirRecoveryCooldownMs = Math.round(nonNegativeFloat(
    setting(fresh, "room_router.dead_air_recovery.cooldown_seconds", deadAirRecoveryCooldownMs / 1000),
    deadAirRecoveryCooldownMs / 1000
  ) * 1000);
  deadAirRecoverySilenceTimeoutMs = Math.round(nonNegativeFloat(
    setting(fresh, "room_router.dead_air_recovery.silence_timeout_seconds", deadAirRecoverySilenceTimeoutMs / 1000),
    deadAirRecoverySilenceTimeoutMs / 1000
  ) * 1000);
  deadAirRecoveryTriggerMode = String(
    setting(fresh, "room_router.dead_air_recovery.trigger_mode", deadAirRecoveryTriggerMode) || deadAirRecoveryTriggerMode
  ).trim().toLowerCase();
  deadAirRecoveryActionMode = String(
    setting(fresh, "room_router.dead_air_recovery.action_mode", deadAirRecoveryActionMode) || deadAirRecoveryActionMode
  ).trim().toLowerCase();
  deadAirRecoveryNextSpeakerStrategy = String(
    setting(fresh, "room_router.dead_air_recovery.next_speaker_strategy", deadAirRecoveryNextSpeakerStrategy) || deadAirRecoveryNextSpeakerStrategy
  ).trim().toLowerCase();
  deadAirRecoveryFallbackTarget = String(
    setting(fresh, "room_router.dead_air_recovery.selected_fallback_target", deadAirRecoveryFallbackTarget) || deadAirRecoveryFallbackTarget
  ).trim();
  persistRoomContextBetweenRestarts = asBool(
    setting(fresh, "chat.persist_room_context_between_restarts", persistRoomContextBetweenRestarts)
  );
  if (!persistRoomContextBetweenRestarts) {
    resetRoomContext("live settings persistence disabled");
  }
  appendModeratorRecoveryStatus({
    last_reason: "live_settings_reloaded",
    ...(!deadAirRecoveryEnabled ? { last_next_target_bot_id: "" } : {}),
    cooldown_remaining_ms: 0,
    last_error: ""
  });
  lastSilenceRecoveryActivityAtMs = 0;
  routedTextPollMs = Math.max(100, Math.round(positiveInt(setting(fresh, "room_router.routed_text_poll_ms", routedTextPollMs), routedTextPollMs)));
  routedTextMaxAgeMs = Math.max(1000, Math.round(positiveFloat(setting(fresh, "room_router.routed_text_max_age_seconds", routedTextMaxAgeMs / 1000), routedTextMaxAgeMs / 1000) * 1000));
  console.log("[DiscordBridgeControl] Live settings reloaded.");
}

async function handleHttpNcTurn(turn) {
  console.log(`[NC] Sending speech turn to ${ncTurnEndpoint}`);
  const turnId = `discord_${turn.userId}_${Date.now()}_${randomUUID()}`;
  if (turn.routedText && (playbackActive || playbackQueue.length > 0 || currentPlaybackItem)) {
    playbackDebug("routed_turn_wait_own_playback", {
      turnId,
      speaker: turn.speakerName || turn.userId,
      queueLength: playbackQueue.length,
      playbackActive,
      activePlaybackTurnId,
      currentPlaybackTurnId: currentPlaybackItem?.turnId || ""
    });
    await waitForPlaybackGenerationIdle(playbackGeneration);
    playbackDebug("routed_turn_own_playback_idle", {
      turnId,
      speaker: turn.speakerName || turn.userId,
      queueLength: playbackQueue.length,
      playbackActive,
      activePlaybackTurnId
    });
  }
  const pickedPayloadInvalidationReason = routedPickedPayloadInvalidationReason(turn);
  if (pickedPayloadInvalidationReason) {
    console.log(`[DiscordBridgeRouter] Routed turn rejected after pickup: ${pickedPayloadInvalidationReason}`);
    writeRuntimeStatus("routed_turn_start_rejected");
    return;
  }
  const turnState = {
    generation: playbackGeneration,
    startedAtMs: Date.now(),
    interruptedPlayback: false,
    pendingInterruptSent: Boolean(turn.pendingInterrupt?.turnId),
    routedText: Boolean(turn.routedText),
    routedTargetBotId: safeFileSegment(
      turn.routedTargetBotId
      || turn?.roomRouterDecision?.target_bot_id
      || ""
    ).toLowerCase(),
    waitForReplyFloor: Boolean(turn.prepareAhead),
    deadAirRecovery: Boolean(turn.deadAirRecovery),
    recoveryActionMode: String(turn.recoveryActionMode || ""),
    recoveryNextTargetBotId: safeFileSegment(turn.recoveryNextTargetBotId || "").toLowerCase(),
    manualCallOn: Boolean(turn.manualCallOn),
    acceptedSpeechInterrupt: Boolean(turn.acceptedSpeechInterrupt),
    acceptedHumanInterventionRouteKey: String(turn.acceptedHumanInterventionRouteKey || turn.routedPayloadRouteKey || turn.routeKey || ""),
    acceptedHumanInterventionTargetBotId: safeFileSegment(turn.acceptedHumanInterventionTargetBotId || turn.routedPayloadTargetBotId || turn.routedTargetBotId || "").toLowerCase(),
    routeKey: String(turn.routeKey || ""),
    humanInterventionMarkerMs: latestHumanInterventionMs(),
    initialPlaybackBufferReleased: initialReplyBufferChunks <= 1,
    preparedReplyChunks: [],
    readyChunks: 0,
    playedChunks: 0,
    totalChunks: 0,
    replyComplete: false
  };
  turnState.turnId = turnId;
  activeReplyProgress = turnState;
  replyProgressByTurnId.set(turnId, turnState);
  playbackDebug("turn_start", {
    turnId,
    speaker: turn.speakerName || turn.userId,
    routedText: turnState.routedText,
    waitForReplyFloor: turnState.waitForReplyFloor,
    initialPlaybackBufferReleased: turnState.initialPlaybackBufferReleased,
    playbackGeneration,
    activePlaybackTurnId,
    queueLength: playbackQueue.length,
    playbackActive
  });
  const startModeratorStateReason = routedTurnModeratorStateInvalidationReason(turnState);
  if (startModeratorStateReason) {
    dropRoutedTurnAfterModeratorStateChange(turnState, turnId, `turn start ${startModeratorStateReason}`);
    writeRuntimeStatus("routed_turn_start_rejected");
    return;
  }
  if (!turnState.waitForReplyFloor && coordinateBotReplies && replyFloorMode !== "disabled") {
    if (tryAcquireReplyFloor(turnId)) {
      turnState.replyFloorClaimed = true;
    } else {
      turnState.replyFloorDenied = true;
      console.log(`[DiscordBridgeDecision] Dropping NC turn before generation: reply floor is busy (turn=${turnId})`);
      return;
    }
  }
  markBotCurrentForTurn(turnState, "bot_turn_start");
  const abortController = new AbortController();
  activeNcAbortController = abortController;
  activeNcTurnId = turnId;
  let response;
  try {
    response = await fetch(ncTurnEndpoint, {
      method: "POST",
      headers: ncJsonHeaders({ "Accept": "application/x-ndjson" }),
      signal: abortController.signal,
      body: JSON.stringify({
        turn_id: turnId,
        user_id: turn.userId,
        speaker_name: turn.speakerName || "",
        pending_interrupt_turn_id: turn.pendingInterrupt?.turnId || "",
        pending_interrupt_spoken_text: turn.pendingInterrupt?.spokenText || "",
        pending_interrupt_reason: turn.pendingInterrupt?.reason || "",
        captured_at: turn.capturedAt || new Date().toISOString(),
        room_router_selected: Boolean(turn.roomRouterDecision?.answer),
        room_router_reason: String(turn.roomRouterDecision?.reason || ""),
        node_reply_floor_managed: true,
        participants: currentParticipantSnapshot(),
        room_context: readRoomContext(),
        manual_call_on: Boolean(turn.manualCallOn),
        input_text: String(turn.inputText || ""),
        wav_path: turn.inputText || turn.manualCallOn ? "" : turn.filePath,
        duration_seconds: turn.durationSeconds
      })
    });
  } catch (error) {
    releaseUnplayedReplyFloor(turnState);
    if (error?.name === "AbortError") {
      console.log("[NC] Turn request aborted.");
      return;
    }
    throw error;
  }
  try {
    if (turnState.generation !== playbackGeneration) {
      console.log("[NC] Dropping response from interrupted turn.");
      releaseUnplayedReplyFloor(turnState);
      return;
    }
    const contentType = String(response.headers.get("content-type") || "").toLowerCase();
    if (contentType.includes("application/x-ndjson")) {
      await handleNcEventStream(response, turnState);
      releaseUnplayedReplyFloor(turnState);
      return;
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) {
      console.error("[NC] Turn failed:", payload);
      releaseUnplayedReplyFloor(turnState);
      return;
    }
    if (payload.skipped) {
      console.log(`[NC] Turn skipped: ${payload.reason || "unknown"}`);
      handleSkippedNcTurn(payload, turnState);
      releaseUnplayedReplyFloor(turnState);
      writeRuntimeStatus("turn_skipped");
      return;
    }
    console.log(`[NC] Transcript: ${String(payload.input_text || "").slice(0, 180)}`);
    console.log(`[NC] Reply: ${String(payload.reply_text || "").slice(0, 180)}`);
    lastTranscriptText = String(payload.input_text || "").trim();
    writeRuntimeStatus("transcript");
    publishCompletedBotReplyText(String(payload.reply_text || ""), turnState);
    if (Array.isArray(payload.reply_chunks) && payload.reply_chunks.length > 0) {
      markReplyProgressComplete(turnState, payload.reply_chunks.length);
      markReplyTurnComplete(turnId);
      for (const chunk of payload.reply_chunks) {
        const chunkPath = String(chunk.reply_wav_path || "");
        if (chunkPath) {
          markReplyChunkReady(turnState, Number(chunk.chunk_index || 0));
          if (!queueReplyWavPlaybackForTurn(turnState, turnId, chunkPath, `NC TTS reply chunk ${Number(chunk.chunk_index || 0) + 1}`, {
            replyText: String(chunk.reply_text || ""),
            turnId
          })) {
            return;
          }
        }
      }
      return;
    }
    const replyWavPath = String(payload.reply_wav_path || "");
    if (!replyWavPath) {
      console.warn("[NC] No reply_wav_path returned.");
      releaseUnplayedReplyFloor(turnState);
      return;
    }
    markReplyTurnComplete(turnId);
    markReplyProgressComplete(turnState, 1);
    markReplyChunkReady(turnState, 0);
    if (!queueReplyWavPlaybackForTurn(turnState, turnId, replyWavPath, "NC TTS reply", {
      replyText: String(payload.reply_text || ""),
      turnId
    })) {
      return;
    }
  } finally {
    if (activeNcAbortController === abortController) {
      activeNcAbortController = null;
    }
  }
}

async function handleNcEventStream(response, turnState) {
  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    console.error("[NC] Turn failed:", errorText || response.statusText);
    return;
  }
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for await (const rawChunk of response.body) {
      if (routedTurnInvalidatedByHumanIntervention(turnState)) {
        dropRoutedTurnAfterHumanIntervention(turnState, turnState.turnId, "stream");
        return;
      }
      const moderatorStateReason = routedTurnModeratorStateInvalidationReason(turnState);
      if (moderatorStateReason) {
        dropRoutedTurnAfterModeratorStateChange(turnState, turnState.turnId, `stream ${moderatorStateReason}`);
        return;
      }
      if (turnState.generation !== playbackGeneration || turnState.replyFloorDenied) {
        console.log("[NC] Stopping interrupted turn stream.");
        return;
      }
      buffer += decoder.decode(rawChunk, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || "";
      for (const line of lines) {
        handleNcEventLine(line, turnState);
        if (turnState.replyFloorDenied) {
          return;
        }
      }
    }
  } catch (error) {
    if (error?.name === "AbortError") {
      console.log("[NC] Turn stream aborted.");
      return;
    }
    throw error;
  }
  if (turnState.generation !== playbackGeneration || turnState.replyFloorDenied) {
    return;
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    handleNcEventLine(buffer, turnState);
    if (turnState.replyFloorDenied) {
      return;
    }
  }
  if (turnState.generation === playbackGeneration) {
    if (
      Array.isArray(turnState.preparedReplyChunks)
      && turnState.preparedReplyChunks.length > 0
      && !isReplyTurnComplete(turnState.turnId)
    ) {
      markReplyTurnComplete(turnState.turnId);
      releaseInitialReplyBuffer(turnState, { force: true });
    }
    await waitForPreparedReplyFloor(turnState);
    await waitForPlaybackGenerationIdle(turnState.generation);
    if (turnState.generation === playbackGeneration) {
      await sendNcFinish(turnState.turnId);
    }
  }
}

function handleNcEventLine(line, turnState = { generation: playbackGeneration, interruptedPlayback: false }) {
  let generation = turnState.generation;
  if (generation !== playbackGeneration) {
    return;
  }
  const trimmed = String(line || "").trim();
  if (!trimmed) {
    return;
  }
  let event;
  try {
    event = JSON.parse(trimmed);
  } catch (error) {
    console.error("[NC] Invalid event:", trimmed, error);
    return;
  }
  const type = String(event.type || "");
  if (type === "transcript") {
    console.log(`[NC] Transcript: ${String(event.input_text || "").slice(0, 180)}`);
    lastTranscriptText = String(event.input_text || "").trim();
    writeRuntimeStatus("transcript");
    turnState.latestTranscript = {
      inputText: String(event.input_text || "").trim(),
      speakerName: String(event.speaker_name || "").trim(),
      userId: String(event.user_id || "").trim(),
      replyDecisionPending: Boolean(event.reply_decision_pending)
    };
    if (turnState.latestTranscript.replyDecisionPending) {
      console.log("[DiscordBridgeDecision] Reply interruption waiting for response-filter decision.");
      return;
    }
    maybeInterruptForAcceptedReply(turnState, event);
    return;
  }
  if (type === "audio_chunk") {
    if (Boolean(turnState.latestTranscript?.replyDecisionPending)) {
      maybeInterruptForAcceptedReply(turnState, event);
      generation = turnState.generation;
    }
    const replyWavPath = String(event.reply_wav_path || "");
    const turnId = String(event.turn_id || activeNcTurnId || "");
    markReplyChunkReady(turnState, Number(event.chunk_index || 0));
    playbackDebug("nc_audio_chunk", {
      turnId,
      chunkIndex: Number(event.chunk_index || 0),
      wavPath: replyWavPath,
      wavDurationSeconds: wavDurationSeconds(replyWavPath),
      text: previewText(event.reply_text),
      queueLength: playbackQueue.length,
      preparedLength: Array.isArray(turnState.preparedReplyChunks) ? turnState.preparedReplyChunks.length : 0,
      playbackActive,
      activePlaybackTurnId
    });
    console.log(
      `[NC] Audio chunk ${Number(event.chunk_index || 0) + 1}: ${String(event.reply_text || "").slice(0, 140)}`
    );
    writeRuntimeStatus("audio_chunk");
    if (replyWavPath) {
      if (!queueReplyWavPlaybackForTurn(turnState, turnId, replyWavPath, `NC TTS reply chunk ${Number(event.chunk_index || 0) + 1}`, {
        replyText: String(event.reply_text || ""),
        turnId
      })) {
        return;
      }
    }
    return;
  }
  if (type === "done") {
    console.log(`[NC] Reply complete: ${String(event.reply_text || "").slice(0, 180)}`);
    writeRuntimeStatus("reply_complete");
    markReplyProgressComplete(turnState, Number(event.reply_chunks || 0));
    markReplyTurnComplete(String(event.turn_id || turnState.turnId || activeNcTurnId || ""));
    playbackDebug("nc_done", {
      turnId: String(event.turn_id || turnState.turnId || activeNcTurnId || ""),
      text: previewText(event.reply_text),
      queueLength: playbackQueue.length,
      preparedLength: Array.isArray(turnState.preparedReplyChunks) ? turnState.preparedReplyChunks.length : 0,
      playbackActive,
      activePlaybackTurnId
    });
    releaseInitialReplyBuffer(turnState, { force: true });
    publishCompletedBotReplyText(String(event.reply_text || ""), turnState);
    maybePrepareDeadAirRecoveryNextFromCompletedText(String(event.reply_text || ""), turnState);
    if (shouldPrepareRoutedReplyAheadFromCompletedTurn(turnState)) {
      console.log("[DiscordBridgeRouter] Preparing next routed bot reply ahead from completed text.");
      routeCompletedBotReplyTextNow(String(event.reply_text || ""), turnState);
    }
    return;
  }
  if (type === "skipped") {
    const extra = event.filter_reason ? ` (${event.filter_reason})` : "";
    console.log(`[NC] Turn skipped: ${event.reason || "unknown"}${extra}`);
    handleSkippedNcTurn(event, turnState);
    releaseUnplayedReplyFloor(turnState);
    return;
  }
  if (type === "error") {
    console.error("[NC] Turn failed:", event);
    resumeReplyPlaybackEverywhere("turn error");
    releaseUnplayedReplyFloor(turnState);
    return;
  }
  console.log("[NC] Event:", event);
}

function shouldPrepareRoutedReplyAheadFromCompletedTurn(turnState = {}) {
  if (!prepareRoutedBotRepliesAhead || !shouldUseDirectBotTextRouting() || turnState.deadAirRecovery) {
    return false;
  }
  if (String(roomRouterMode || "").trim().toLowerCase() !== "llm_router") {
    return false;
  }
  if (!coordinateBotReplies || replyFloorMode === "disabled") {
    return false;
  }
  // A prebuffered bot may generate before it owns the floor. It should not route
  // the next-next speaker until it has actually become the current floor holder.
  return Boolean(!turnState.waitForReplyFloor || turnState.replyFloorClaimed);
}

function maybeRouteCompletedBotTextAfterFloorClaim(turnState) {
  const inputText = String(turnState?.completedReplyText || "").trim();
  if (!inputText || turnState?.botTextRoutePublished) {
    return;
  }
  if (!shouldPrepareRoutedReplyAheadFromCompletedTurn(turnState)) {
    return;
  }
  console.log("[DiscordBridgeRouter] Prepared bot owns floor; routing completed text ahead.");
  routeCompletedBotReplyTextNow(inputText, turnState);
}

function handleSkippedNcTurn(event, turnState = {}) {
  const reason = String(event?.reason || "unknown");
  const speechAccepted = Boolean(event?.speech_accepted || turnState.acceptedSpeechInterrupt);
  if (speechAccepted) {
    if (moderatorBlocksSpeechInterruption()) {
      console.log(`[DiscordBridgeModerator] Skipped accepted speech did not interrupt: moderator routing flow is protected (${reason}).`);
      return;
    }
    const interruptReason = `accepted speech skipped reply: ${reason}`;
    emitPlaybackControl("interrupt", interruptReason);
    const interrupted = interruptCurrentReply(interruptReason, {
      abortActiveRequest: false,
      sendCancel: false,
      respectImmunity: false
    });
    console.log(
      `[DiscordBridgeDecision] Valid speech produced no reply; old playback remains stopped: reason=${reason}, interrupted=${interrupted}`
    );
    return;
  }
  resumeReplyPlaybackEverywhere(`turn skipped: ${reason}`);
}

function maybeInterruptForAcceptedReply(turnState, event = {}) {
  const transcript = turnState.latestTranscript || {};
  const inputText = String(transcript.inputText || event.input_text || "").trim();
  if (!interruptReplyOnUserSpeech || turnState.interruptedPlayback || !inputText) {
    return false;
  }
  if (moderatorBlocksSpeechInterruption()) {
    console.log("[DiscordBridgeModerator] Accepted speech did not interrupt: moderator routing flow is protected.");
    if (turnState.latestTranscript) {
      turnState.latestTranscript.replyDecisionPending = false;
    }
    return false;
  }
  if (turnState.routedText || turnState.waitForReplyFloor) {
    playbackDebug("accepted_reply_interrupt_skipped_routed", {
      turnId: turnState.turnId || "",
      routedText: turnState.routedText,
      waitForReplyFloor: turnState.waitForReplyFloor,
      inputText: previewText(inputText)
    });
    if (turnState.latestTranscript) {
      turnState.latestTranscript.replyDecisionPending = false;
    }
    return false;
  }
  const speaker = String(
    transcript.speakerName
    || event.speaker_name
    || transcript.userId
    || event.user_id
    || "Discord user"
  ).trim();
  const interrupted = interruptCurrentReply(`valid speech from ${speaker}`, {
    abortActiveRequest: false,
    sendCancel: !turnState.pendingInterruptSent
  });
  if (interrupted) {
    turnState.generation = playbackGeneration;
    turnState.interruptedPlayback = true;
    console.log(`[DiscordBridgeDecision] Reply accepted; interrupted current playback for ${speaker}.`);
  }
  if (turnState.latestTranscript) {
    turnState.latestTranscript.replyDecisionPending = false;
  }
  return interrupted;
}

async function handleMockNcTurn(turn) {
  console.log(`[MockNC] Received speech turn from user=${turn.userId}: ${turn.durationSeconds.toFixed(2)}s`);
  if (mockReplyDelayMs > 0) {
    await delay(mockReplyDelayMs);
  }

  const replyText = `Mock NC heard a ${turn.durationSeconds.toFixed(1)} second Discord voice turn.`;
  const replyPcm = makeMockReplyPcm(turn.durationSeconds);
  const replyWav = encodeWav(replyPcm, 48_000, 2, 16);
  const replyPath = join(replyDir, `mock_reply_${turn.userId}_${Date.now()}.wav`);
  writeFileSync(replyPath, replyWav);

  const record = {
    type: "mock_nc_turn",
    createdAt: new Date().toISOString(),
    bridgeMode,
    userId: turn.userId,
    speakerName: turn.speakerName || "",
    input: {
      wavPath: turn.filePath,
      durationSeconds: Number(turn.durationSeconds.toFixed(3))
    },
    mockReply: {
      text: replyText,
      wavPath: replyPath,
      durationSeconds: Number((replyPcm.length / 192000).toFixed(3))
    }
  };
  const recordPath = join(turnDir, `turn_${turn.userId}_${Date.now()}.json`);
  writeFileSync(recordPath, JSON.stringify(record, null, 2), "utf8");

  console.log(`[MockNC] Reply queued: ${replyText}`);
  console.log(`[MockNC] Turn record: ${recordPath}`);
  queuePcmPlayback(replyPcm, "mock NC reply", playbackGeneration);
}

function interruptCurrentReply(reason, options = {}) {
  const abortActiveRequest = options.abortActiveRequest !== false;
  const sendCancelRequest = options.sendCancel !== false;
  const respectImmunity = options.respectImmunity !== false;
  const respectModeratorProtection = options.respectModeratorProtection !== false;
  const discardRoutedTurns = options.discardRoutedTurns !== false;
  const hasPlayback = playbackActive || playbackQueue.length > 0 || currentPlaybackItem;
  if (!hasPlayback && (!abortActiveRequest || !activeNcAbortController)) {
    return false;
  }
  if (respectModeratorProtection && moderatorBlocksSpeechInterruption()) {
    console.log(`[DiscordBridgeModerator] Reply interruption blocked: moderator routing flow is protected (${reason})`);
    return false;
  }
  const immunityRemainingMs = playbackImmunityRemainingMs();
  if (respectImmunity && immunityRemainingMs > 0) {
    console.log(
      `[DiscordBridge] Reply interruption deferred during ${Math.ceil(immunityRemainingMs)}ms immunity window: ${reason}`
    );
    return false;
  }
  const turnId = activePlaybackTurnId || (abortActiveRequest ? activeNcTurnId : null);
  const spokenText = spokenReplyText();
  playbackPausedForTranscriptProbe = null;
  markHumanIntervention(reason, options.humanInterventionExtra || {});
  if (discardRoutedTurns) {
    discardPendingRoutedTextTurns(reason);
  }
  releaseReplyFloor(turnId, { force: true, reason });
  clearReplyProgressForTurn(turnId, reason);
  playbackGeneration += 1;
  playbackQueue.length = 0;
  currentPlaybackItem = null;
  deliveredReplyTextParts = [];
  activePlaybackTurnId = null;
  activePlaybackStartedAtMs = 0;
  if (turnId && sendCancelRequest) {
    sendNcCancel(turnId, spokenText, reason).catch((error) => {
      console.error("[NC] Cancel request failed:", error);
    });
  }
  if (abortActiveRequest && activeNcAbortController) {
    try {
      activeNcAbortController.abort();
    } catch {
      // Ignore abort races during shutdown or completed requests.
    }
    activeNcAbortController = null;
    activeNcTurnId = null;
  }
  if (voicePlayer) {
    try {
      voicePlayer.stop(true);
    } catch {
      // Ignore player state races.
    }
  }
  playbackActive = false;
  clearCurrentBotModeratorState(`interrupt:${reason || "unknown"}`);
  console.log(`[DiscordBridge] Interrupted reply: ${reason}`);
  return true;
}

function pauseReplyPlaybackForTranscriptProbe(reason) {
  if (playbackPausedForTranscriptProbe || !interruptReplyOnUserSpeech || !voicePlayer) {
    return false;
  }
  const hasPlayback = playbackActive || currentPlaybackItem || playbackQueue.length > 0;
  if (!hasPlayback) {
    return false;
  }
  const immunityRemainingMs = playbackImmunityRemainingMs();
  if (immunityRemainingMs > 0) {
    console.log(
      `[DiscordBridgeDecision] Speech probe pause skipped during ${Math.ceil(immunityRemainingMs)}ms reply immunity: ${reason}`
    );
    return false;
  }
  let paused = false;
  try {
    paused = voicePlayer.pause(true);
  } catch {
    paused = false;
  }
  if (!paused) {
    return false;
  }
  playbackPausedForTranscriptProbe = {
    generation: playbackGeneration,
    reason,
    pausedAtMs: Date.now()
  };
  console.log(`[DiscordBridge] Paused reply audio while checking continued speech: ${reason}`);
  writeRuntimeStatus("probe_pause");
  return true;
}

function resumeReplyPlaybackAfterTranscriptProbe(reason) {
  const paused = playbackPausedForTranscriptProbe;
  if (!paused) {
    return false;
  }
  playbackPausedForTranscriptProbe = null;
  if (paused.generation !== playbackGeneration || !voicePlayer) {
    console.log(`[DiscordBridge] Speech probe pause abandoned after playback changed: ${reason}`);
    return false;
  }
  let resumed = false;
  try {
    resumed = voicePlayer.unpause();
  } catch {
    resumed = false;
  }
  console.log(
    `[DiscordBridge] ${resumed ? "Resumed" : "Could not resume"} reply audio after speech check: ${reason}`
  );
  writeRuntimeStatus(resumed ? "probe_resume" : "probe_resume_failed");
  return resumed;
}

function resumeReplyPlaybackEverywhere(reason) {
  emitPlaybackControl("probe_resume", reason);
  return resumeReplyPlaybackAfterTranscriptProbe(reason);
}

function claimReplyFloorForTurn(turnState, turnId, options = {}) {
  if (!turnId || !coordinateBotReplies || replyFloorMode === "disabled") {
    playbackDebug("claim_floor_bypassed", { turnId, coordinateBotReplies, replyFloorMode });
    return true;
  }
  if (turnState.replyFloorClaimed) {
    playbackDebug("claim_floor_already_claimed", { turnId });
    return true;
  }
  if (turnState.replyFloorDenied) {
    playbackDebug("claim_floor_already_denied", { turnId });
    return false;
  }
  const moderatorStateReason = routedTurnModeratorStateInvalidationReason(turnState);
  if (moderatorStateReason) {
    dropRoutedTurnAfterModeratorStateChange(turnState, turnId, `reply floor claim ${moderatorStateReason}`);
    return false;
  }
  if (tryAcquireReplyFloor(turnId)) {
    turnState.replyFloorClaimed = true;
    playbackDebug("claim_floor_success", { turnId });
    consumeModeratorPendingRouteIfTarget(botInstanceId, turnState.routeKey || turnId, "reply_floor_claimed");
    maybeRouteCompletedBotTextAfterFloorClaim(turnState);
    maybePrepareDeadAirRecoveryNextAfterFloorClaim(turnState);
    return true;
  }
  if (options.deferOnBusy) {
    playbackDebug("claim_floor_deferred_busy", { turnId });
    return false;
  }

  const reason = "another Discord bot claimed the reply floor first";
  turnState.replyFloorDenied = true;
  console.log(`[DiscordBridgeDecision] Dropping NC reply: ${reason} (turn=${turnId})`);
  sendNcCancel(turnId, "", reason, { recordUserTurn: true }).catch((error) => {
    console.error("[NC] Reply-floor cancel failed:", error);
  });
  if (activeNcTurnId === turnId && activeNcAbortController) {
    try {
      activeNcAbortController.abort();
    } catch {
      // Ignore abort races.
    }
    activeNcAbortController = null;
    activeNcTurnId = null;
  }
  return false;
}

function releaseUnplayedReplyFloor(turnState) {
  const turnId = String(turnState?.turnId || "");
  clearCurrentBotIfTurnHasNoPlayback(turnState, "release_unplayed_current_bot");
  if (!turnId || !turnState?.replyFloorClaimed) {
    return;
  }
  if (activePlaybackTurnId === turnId || hasPendingPlaybackForTurn(turnId)) {
    playbackDebug("release_unplayed_floor_deferred", {
      turnId,
      activePlaybackTurnId,
      hasPendingPlayback: hasPendingPlaybackForTurn(turnId),
      queueLength: playbackQueue.length,
      playbackActive
    });
    return;
  }
  playbackDebug("release_unplayed_floor", { turnId });
  releaseReplyFloor(turnId);
  turnState.replyFloorClaimed = false;
}

function queueReplyWavPlaybackForTurn(turnState, turnId, wavPath, label, metadata = {}) {
  if (turnState.generation !== playbackGeneration) {
    playbackDebug("queue_reply_rejected_generation", {
      turnId,
      label,
      turnGeneration: turnState.generation,
      playbackGeneration
    });
    return false;
  }
  playbackDebug("queue_reply_enter", {
    turnId,
    label,
    wavPath,
    wavDurationSeconds: wavDurationSeconds(wavPath),
    floorClaimed: turnState.replyFloorClaimed,
    waitForReplyFloor: turnState.waitForReplyFloor,
    preparedLength: Array.isArray(turnState.preparedReplyChunks) ? turnState.preparedReplyChunks.length : 0,
    queueLength: playbackQueue.length,
    playbackActive
  });
  if (claimReplyFloorForTurn(turnState, turnId, { deferOnBusy: Boolean(turnState.waitForReplyFloor) })) {
    turnState.preparedReplyChunks.push({ wavPath, label, metadata });
    if (!releaseInitialReplyBuffer(turnState)) {
      console.log(`[DiscordBridge] Buffered reply start chunk ${turnState.preparedReplyChunks.length}/${initialReplyBufferChunks}: ${label}`);
    }
    return true;
  }
  if (!turnState.waitForReplyFloor || turnState.replyFloorDenied) {
    playbackDebug("queue_reply_rejected_floor", {
      turnId,
      label,
      waitForReplyFloor: turnState.waitForReplyFloor,
      replyFloorDenied: turnState.replyFloorDenied
    });
    return false;
  }
  turnState.preparedReplyChunks.push({ wavPath, label, metadata });
  ensurePreparedReplyFloorPump(turnState, turnId);
  console.log(`[DiscordBridgeDecision] Prepared audio waiting for reply floor: ${label}`);
  return true;
}

function ensurePreparedReplyFloorPump(turnState, turnId) {
  if (turnState.preparedFloorTimer || turnState.replyFloorClaimed || turnState.replyFloorDenied) {
    return;
  }
  const pump = () => {
    turnState.preparedFloorTimer = null;
    if (routedTurnInvalidatedByHumanIntervention(turnState)) {
      dropRoutedTurnAfterHumanIntervention(turnState, turnId, "prepared floor wait");
      return;
    }
    const moderatorStateReason = routedTurnModeratorStateInvalidationReason(turnState);
    if (moderatorStateReason) {
      dropRoutedTurnAfterModeratorStateChange(turnState, turnId, `prepared floor wait ${moderatorStateReason}`);
      return;
    }
    if (turnState.generation !== playbackGeneration || turnState.replyFloorDenied) {
      turnState.preparedReplyChunks.length = 0;
      return;
    }
    const floor = readReplyFloor();
    if (!floor || !isReplyFloorFresh(floor)) {
      if (floor) {
        removeReplyFloor("stale");
      }
    }
    if (claimReplyFloorForTurn(turnState, turnId, { deferOnBusy: true })) {
      releaseInitialReplyBuffer(turnState);
      return;
    }
    turnState.preparedFloorTimer = setTimeout(pump, 150);
  };
  turnState.preparedFloorTimer = setTimeout(pump, 150);
}

function flushPreparedReplyChunks(turnState) {
  if (!Array.isArray(turnState.preparedReplyChunks) || turnState.preparedReplyChunks.length === 0) {
    return;
  }
  if (turnState.waitForReplyFloor && !turnState.replyFloorClaimed) {
    playbackDebug("flush_prepared_chunks_blocked_floor", {
      turnId: turnState.turnId || "",
      count: turnState.preparedReplyChunks.length,
      queueLength: playbackQueue.length,
      playbackActive,
      activePlaybackTurnId
    });
    return;
  }
  const chunks = turnState.preparedReplyChunks.splice(0);
  playbackDebug("flush_prepared_chunks", {
    turnId: turnState.turnId,
    count: chunks.length,
    labels: chunks.map((item) => item.label),
    queueLengthBefore: playbackQueue.length,
    playbackActive
  });
  for (const item of chunks) {
    queueWavPlayback(item.wavPath, item.label, turnState.generation, item.metadata || {});
  }
}

function releaseInitialReplyBuffer(turnState, options = {}) {
  if (!Array.isArray(turnState?.preparedReplyChunks) || turnState.preparedReplyChunks.length === 0) {
    playbackDebug("initial_buffer_empty", {
      turnId: turnState?.turnId || "",
      force: Boolean(options.force)
    });
    return false;
  }
  const force = Boolean(options.force);
  const turnId = String(turnState.turnId || turnState.preparedReplyChunks[0]?.metadata?.turnId || "");
  const hasEnoughBuffered = turnState.preparedReplyChunks.length >= initialReplyBufferChunks;
  if (
    !force
    && !turnState.initialPlaybackBufferReleased
    && !isReplyTurnComplete(turnId)
    && initialReplyBufferChunks > 1
    && !hasEnoughBuffered
  ) {
    playbackDebug("initial_buffer_hold", {
      turnId,
      force,
      preparedLength: turnState.preparedReplyChunks.length,
      initialReplyBufferChunks,
      replyComplete: isReplyTurnComplete(turnId),
      hasEnoughBuffered
    });
    return false;
  }
  playbackDebug("initial_buffer_release", {
    turnId,
    force,
    preparedLength: turnState.preparedReplyChunks.length,
    initialReplyBufferChunks,
    replyComplete: isReplyTurnComplete(turnId),
    hasEnoughBuffered
  });
  turnState.initialPlaybackBufferReleased = true;
  flushPreparedReplyChunks(turnState);
  return true;
}

async function waitForPreparedReplyFloor(turnState) {
  while (
    turnState.generation === playbackGeneration
    && !turnState.replyFloorDenied
    && (
      (Array.isArray(turnState.preparedReplyChunks) && turnState.preparedReplyChunks.length > 0)
      || turnState.preparedFloorTimer
    )
  ) {
    if (routedTurnInvalidatedByHumanIntervention(turnState)) {
      dropRoutedTurnAfterHumanIntervention(turnState, turnState.turnId || "", "prepared playback wait");
      return;
    }
    const moderatorStateReason = routedTurnModeratorStateInvalidationReason(turnState);
    if (moderatorStateReason) {
      dropRoutedTurnAfterModeratorStateChange(turnState, turnState.turnId || "", `prepared playback wait ${moderatorStateReason}`);
      return;
    }
    await delay(75);
  }
}

function queuePcmPlayback(pcmBuffer, label, generation = playbackGeneration) {
  if (generation !== playbackGeneration) {
    return;
  }
  playbackQueue.push({ pcmBuffer, label, generation });
  pumpPlaybackQueue();
}

function queueWavPlayback(wavPath, label, generation = playbackGeneration, metadata = {}) {
  if (generation !== playbackGeneration) {
    playbackDebug("queue_wav_rejected_generation", { label, generation, playbackGeneration });
    return;
  }
  if (metadata.turnId && !activePlaybackTurnId) {
    activePlaybackTurnId = String(metadata.turnId);
    activePlaybackStartedAtMs = 0;
    deliveredReplyTextParts = [];
  }
  playbackDebug("queue_wav", {
    turnId: metadata.turnId || "",
    label,
    wavPath,
    wavDurationSeconds: wavDurationSeconds(wavPath),
    queueLengthBefore: playbackQueue.length,
    playbackActive,
    activePlaybackTurnId
  });
  playbackQueue.push({ wavPath, label, generation, ...metadata });
  pumpPlaybackQueue();
}

function hasPendingPlaybackForTurn(turnId) {
  const id = String(turnId || "");
  if (!id) {
    return false;
  }
  return (playbackActive && String(activePlaybackTurnId || "") === id)
    || String(currentPlaybackItem?.turnId || "") === id
    || playbackQueue.some((item) => String(item?.turnId || "") === id);
}

function hasActivePlaybackForTurn(turnId) {
  const id = String(turnId || "");
  if (!id || !playbackActive) {
    return false;
  }
  return String(activePlaybackTurnId || "") === id || String(currentPlaybackItem?.turnId || "") === id;
}

function removeQueuedPlaybackForTurn(turnId, reason) {
  const id = String(turnId || "");
  if (!id) {
    return 0;
  }
  const before = playbackQueue.length;
  for (let index = playbackQueue.length - 1; index >= 0; index -= 1) {
    if (String(playbackQueue[index]?.turnId || "") === id) {
      playbackQueue.splice(index, 1);
    }
  }
  const removed = before - playbackQueue.length;
  if (removed > 0) {
    playbackDebug("queued_playback_removed", { turnId: id, removed, reason: reason || "" });
  }
  if (activePlaybackTurnId === id && !hasActivePlaybackForTurn(id) && !playbackQueue.some((item) => String(item?.turnId || "") === id)) {
    activePlaybackTurnId = null;
    activePlaybackStartedAtMs = 0;
    deliveredReplyTextParts = [];
  }
  return removed;
}

function isReplyTurnComplete(turnId) {
  const id = String(turnId || "");
  return Boolean(id && completedReplyTurnIds.has(id));
}

function markReplyTurnComplete(turnId) {
  const id = String(turnId || "");
  if (id) {
    completedReplyTurnIds.add(id);
    playbackDebug("turn_mark_complete", { turnId: id });
  }
}

function markReplyChunkReady(turnState, chunkIndex = 0) {
  if (!turnState) {
    return;
  }
  const index = Math.max(0, Number.isFinite(Number(chunkIndex)) ? Number(chunkIndex) : 0);
  turnState.readyChunks = Math.max(Number(turnState.readyChunks || 0), index + 1);
  turnState.totalChunks = Math.max(Number(turnState.totalChunks || 0), index + 1);
  if (activeReplyProgress === turnState) {
    writeRuntimeStatus("audio_chunk");
  }
}

function markReplyProgressComplete(turnState, totalChunks = 0) {
  if (!turnState) {
    return;
  }
  const total = Math.max(0, Number.isFinite(Number(totalChunks)) ? Number(totalChunks) : 0);
  turnState.replyComplete = true;
  if (total > 0) {
    turnState.totalChunks = Math.max(Number(turnState.totalChunks || 0), total);
  } else {
    turnState.totalChunks = Math.max(Number(turnState.totalChunks || 0), Number(turnState.readyChunks || 0));
  }
  if (activeReplyProgress === turnState) {
    writeRuntimeStatus("reply_complete");
  }
}

function markReplyChunkPlayed(turnId) {
  const progress = activeReplyProgress;
  if (!progress || String(progress.turnId || "") !== String(turnId || "")) {
    return;
  }
  progress.playedChunks = Math.min(
    Math.max(Number(progress.totalChunks || 0), Number(progress.readyChunks || 0), 1),
    Number(progress.playedChunks || 0) + 1
  );
  writeRuntimeStatus("playback");
}

function forgetReplyTurnComplete(turnId) {
  const id = String(turnId || "");
  if (id) {
    completedReplyTurnIds.delete(id);
  }
}

function pumpPlaybackQueue() {
  if (playbackActive || !voicePlayer || playbackQueue.length === 0) {
    if (playbackQueue.length > 0) {
      playbackDebug("pump_blocked", {
        playbackActive,
        hasVoicePlayer: Boolean(voicePlayer),
        queueLength: playbackQueue.length,
        activePlaybackTurnId
      });
    }
    return;
  }

  const next = playbackQueue.shift();
  if (!next || next.generation !== playbackGeneration) {
    playbackDebug("pump_skip_generation", {
      label: next?.label || "",
      nextGeneration: next?.generation,
      playbackGeneration
    });
    pumpPlaybackQueue();
    return;
  }
  currentPlaybackItem = next;
  if (next.turnId) {
    if (activePlaybackTurnId !== String(next.turnId)) {
      activePlaybackStartedAtMs = 0;
    }
    activePlaybackTurnId = String(next.turnId);
  }
  if (next.turnId && !activePlaybackStartedAtMs) {
    activePlaybackStartedAtMs = Date.now();
  }
  playbackActive = true;
  noteRoomActivity("playback_start");
  const playbackStartedAtMs = Date.now();
  updateModeratorState((current) => ({
    ...current,
    current_bot_id: botInstanceId,
    current_bot_name: botDisplayName,
    current_bot_discord_user_id: String(client.user?.id || ""),
    current_bot_turn_id: String(next.turnId || ""),
    current_human_route: {},
    current_speaker_user_id: "",
    current_speaker_name: "",
    ...(safeFileSegment(current?.pending_route?.target_bot_id || "").toLowerCase() === botInstanceId
      ? {
          pending_route: {},
          route_next_target_bot_id: ""
        }
      : {}),
    last_error: ""
  }));
  applyDiscordMuteEnforcement("bot_playback_start").catch((error) => {
    console.warn(`[DiscordBridgeModerator] Could not update Discord mutes at playback start: ${error?.message || error}`);
  });
  writeRuntimeStatus("playback");
  playbackDebug("playback_start", {
    turnId: next.turnId || "",
    label: next.label,
    wavPath: next.wavPath || "",
    wavDurationSeconds: wavDurationSeconds(next.wavPath || ""),
    queueLengthAfterShift: playbackQueue.length,
    replyComplete: isReplyTurnComplete(next.turnId),
    activePlaybackTurnId
  });
  console.log(`[DiscordBridge] Playing queued audio: ${next.label}`);
  const resource = next.wavPath
    ? createAudioResource(wavToDiscordPcmStream(next.wavPath), { inputType: StreamType.Raw })
    : createAudioResource(bufferToStream(next.pcmBuffer), { inputType: StreamType.Raw });
  voicePlayer.play(resource);
  voicePlayer.once(AudioPlayerStatus.Idle, async () => {
    if (next.generation !== playbackGeneration) {
      return;
    }
    console.log(`[DiscordBridge] Queued audio finished: ${next.label}`);
    playbackDebug("playback_idle", {
      turnId: next.turnId || "",
      label: next.label,
      elapsedSeconds: Number(((Date.now() - playbackStartedAtMs) / 1000).toFixed(3)),
      wavDurationSeconds: wavDurationSeconds(next.wavPath || ""),
      queueLength: playbackQueue.length,
      replyComplete: isReplyTurnComplete(next.turnId),
      willReleaseFloor: Boolean(next.turnId && isReplyTurnComplete(next.turnId) && !hasPendingPlaybackForTurn(next.turnId))
    });
    if (next.replyText) {
      deliveredReplyTextParts.push(String(next.replyText));
    }
    if (next.turnId) {
      markReplyChunkPlayed(next.turnId);
    }
    if (currentPlaybackItem === next) {
      currentPlaybackItem = null;
    }
    playbackActive = false;
    noteRoomActivity("playback_idle");
    const replyTurnFinished = Boolean(next.turnId && isReplyTurnComplete(next.turnId) && !hasPendingPlaybackForTurn(next.turnId));
    if (!next.turnId) {
      updateModeratorState((current) => {
        if (safeFileSegment(current?.current_bot_id || "").toLowerCase() !== botInstanceId) {
          return current;
        }
        const currentTurnId = String(current?.current_bot_turn_id || "");
        if (currentTurnId && currentTurnId !== String(next.turnId || "")) {
          return current;
        }
        return {
          ...current,
          current_bot_id: "",
          current_bot_name: "",
          current_bot_discord_user_id: "",
          current_bot_turn_id: ""
        };
      });
    }
    writeRuntimeStatus("playback");
    if (replyTurnFinished) {
      const completedProgress = replyProgressByTurnId.get(String(next.turnId))
        || (activeReplyProgress && String(activeReplyProgress.turnId || "") === String(next.turnId) ? activeReplyProgress : null);
      if (completedProgress) {
        if (completedProgress.deadAirRecovery) {
          await completeDeadAirRecoveryTurn(spokenReplyText(), completedProgress);
        } else {
          await routeCompletedBotReplyTextNow(spokenReplyText(), completedProgress);
        }
      }
      updateModeratorState((current) => {
        if (safeFileSegment(current?.current_bot_id || "").toLowerCase() !== botInstanceId) {
          return current;
        }
        const currentTurnId = String(current?.current_bot_turn_id || "");
        if (currentTurnId && currentTurnId !== String(next.turnId || "")) {
          return current;
        }
        return {
          ...current,
          current_bot_id: "",
          current_bot_name: "",
          current_bot_discord_user_id: "",
          current_bot_turn_id: ""
        };
      });
      releaseReplyFloor(String(next.turnId));
      if (activePlaybackTurnId === String(next.turnId)) {
        activePlaybackTurnId = null;
        activePlaybackStartedAtMs = 0;
        deliveredReplyTextParts = [];
      }
      replyProgressByTurnId.delete(String(next.turnId));
      if (activeReplyProgress && String(activeReplyProgress.turnId || "") === String(next.turnId)) {
        activeReplyProgress = null;
      }
      forgetReplyTurnComplete(next.turnId);
      writeRuntimeStatus("reply_finished");
    }
    if (replyTurnFinished || !next.turnId) {
      promotePendingHumanRouteToCurrent("bot playback finished");
      applyDiscordMuteEnforcement("bot_playback_idle").catch((error) => {
        console.warn(`[DiscordBridgeModerator] Could not update Discord mutes at playback idle: ${error?.message || error}`);
      });
    }
    pumpPlaybackQueue();
  });
}

function maybePrepareDeadAirRecoveryNextFromCompletedText(spokenText, turnState) {
  const text = String(spokenText || "").trim();
  if (!text || !turnState?.deadAirRecovery || turnState.deadAirRecoveryNextQueued || !turnState.replyFloorClaimed) {
    return false;
  }
  const action = String(turnState?.recoveryActionMode || deadAirRecoveryActionMode || "").toLowerCase();
  const target = normalizeRecoveryTargetId(turnState?.recoveryNextTargetBotId || "");
  if (!target || action !== "moderator_speaks_and_calls_next") {
    return false;
  }
  const routeKey = String(turnState?.routeKey || `dead_air_complete_${Date.now()}`);
  const queued = queueRecoveryNextTarget(target, {
    sourceRouteKey: routeKey,
    moderatorText: text,
    reason: "dead_air_recovery_after_moderator"
  });
  if (queued) {
    turnState.deadAirRecoveryNextQueued = true;
    appendModeratorRecoveryStatus({
      last_moderator_reply: previewText(text, 160),
      last_next_target_bot_id: target,
      last_reason: "moderator_prebuffered_next",
      last_error: ""
    });
  }
  return queued;
}

function maybePrepareDeadAirRecoveryNextAfterFloorClaim(turnState) {
  if (!turnState?.deadAirRecovery || turnState.deadAirRecoveryNextQueued || !turnState.replyFloorClaimed) {
    return false;
  }
  const completedText = String(turnState.completedReplyText || "").trim();
  return completedText ? maybePrepareDeadAirRecoveryNextFromCompletedText(completedText, turnState) : false;
}

async function completeDeadAirRecoveryTurn(spokenText, turnState) {
  const text = String(spokenText || "").trim();
  const routeKey = String(turnState?.routeKey || `dead_air_complete_${Date.now()}`);
  if (text) {
    const contextTurn = {
      speakerName: botDisplayName,
      capturedAt: new Date().toISOString()
    };
    const contextText = contextLineForTurn(contextTurn, text);
    const decision = {
      ok: true,
      answer: false,
      target_bot_id: "",
      reason: "dead_air_recovery_moderator_spoke",
      route_key: routeKey,
      input_text: text,
      context_input_text: contextText,
      speech_accepted: true,
      speaker_name: botDisplayName,
      user_id: String(client.user?.id || botInstanceId),
      speaker_bot_id: botInstanceId
    };
    appendRoomContextFromDecision(decision);
    await broadcastRoomTurnToBotHistories(decision, {
      userId: String(client.user?.id || botInstanceId),
      speakerName: botDisplayName,
      speakerBotId: botInstanceId,
      speakerIsBot: true,
      inputText: text,
      capturedAt: new Date().toISOString(),
      routeKey
    }, routeKey).catch((error) => {
      console.warn(`[DiscordBridgeRouter] Could not broadcast moderator recovery text: ${error?.message || error}`);
    });
  }
  const action = String(turnState?.recoveryActionMode || deadAirRecoveryActionMode || "").toLowerCase();
  const target = normalizeRecoveryTargetId(turnState?.recoveryNextTargetBotId || "");
  appendModeratorRecoveryStatus({
    last_moderator_reply: previewText(text, 160),
    last_next_target_bot_id: target,
    last_reason: "moderator_spoke",
    last_error: ""
  });
  if (target && action === "moderator_speaks_and_calls_next" && !turnState?.deadAirRecoveryNextQueued) {
    queueRecoveryNextTarget(target, {
      sourceRouteKey: routeKey,
      moderatorText: text,
      reason: "dead_air_recovery_after_moderator"
    });
    if (turnState) {
      turnState.deadAirRecoveryNextQueued = true;
    }
  }
}

function spokenReplyText() {
  const parts = [...deliveredReplyTextParts];
  const currentText = String(currentPlaybackItem?.replyText || "").trim();
  if (currentText && !parts.includes(currentText)) {
    parts.push(currentText);
  }
  return parts.map((part) => String(part || "").trim()).filter(Boolean).join("\n\n");
}

function pendingPlaybackInterrupt(reason) {
  const hasPlayback = playbackActive || playbackQueue.length > 0 || currentPlaybackItem;
  const turnId = activePlaybackTurnId;
  if (!interruptReplyOnUserSpeech || !hasPlayback || !turnId) {
    return null;
  }
  if (moderatorBlocksSpeechInterruption()) {
    console.log(`[DiscordBridgeModerator] Reply interruption blocked: moderator routing flow is protected (${reason})`);
    return null;
  }
  const immunityRemainingMs = playbackImmunityRemainingMs();
  if (immunityRemainingMs > 0) {
    console.log(
      `[DiscordBridge] Pending interrupt ignored during ${Math.ceil(immunityRemainingMs)}ms reply immunity: ${reason}`
    );
    return null;
  }
  return {
    turnId,
    spokenText: spokenReplyText(),
    reason
  };
}

function requestContinuousSpeechInterrupt(userId) {
  if (!activeCaptures.has(userId)) {
    return;
  }
  const reason = `continuous speech from user ${userId} reached ${interruptAfterSeconds.toFixed(1)}s`;
  const pendingInterrupt = pendingPlaybackInterrupt(reason);
  if (pendingInterrupt) {
    pendingInterruptByUserId.set(String(userId), pendingInterrupt);
    console.log(
      `[DiscordBridgeDecision] Continuous speech threshold reached: user=${userId}; pending until transcript is accepted`
    );
    return;
  }
  const immunityRemainingMs = playbackImmunityRemainingMs();
  if (immunityRemainingMs > 0) {
    console.log(
      `[DiscordBridgeDecision] Continuous speech interrupt waits for reply immunity: user=${userId}, remaining=${Math.ceil(immunityRemainingMs)}ms`
    );
    setTimeout(() => requestContinuousSpeechInterrupt(userId), immunityRemainingMs + 25);
    return;
  }
  console.log(
    `[DiscordBridgeDecision] Continuous speech threshold reached: user=${userId}; no interruptible playback snapshot`
  );
}

function monitorHumanSpeechForInterruption(connection, userId) {
  if (interruptAfterSeconds <= 0 || activeHumanSpeechMonitors.has(userId)) {
    return;
  }
  activeHumanSpeechMonitors.add(userId);
  const opusStream = connection.receiver.subscribe(userId, {
    end: {
      behavior: EndBehaviorType.AfterSilence,
      duration: silenceMs
    }
  });
  const decoder = new prism.opus.Decoder({
    rate: 48_000,
    channels: 2,
    frameSize: 960
  });
  let finished = false;
  let totalBytes = 0;
  let interruptRequested = false;
  const thresholdSeconds = Math.max(interruptAfterSeconds, minTurnSeconds);
  const cleanup = () => {
    if (finished) {
      return;
    }
    finished = true;
    activeHumanSpeechMonitors.delete(userId);
    try {
      opusStream.destroy();
    } catch {
      // Ignore stream teardown races.
    }
    try {
      decoder.destroy();
    } catch {
      // Ignore decoder teardown races.
    }
  };
  decoder.on("data", (chunk) => {
    if (finished || interruptRequested) {
      return;
    }
    totalBytes += chunk.length;
    if (totalBytes / 192000 < thresholdSeconds) {
      return;
    }
    interruptRequested = true;
    const reason = `continuous speech from non-captor user ${userId} reached ${interruptAfterSeconds.toFixed(1)}s`;
    console.log(
      `[DiscordBridgeDecision] Non-captor continuous speech threshold observed without interrupt: user=${userId}, reason=${reason}`
    );
    cleanup();
  });
  decoder.once("error", () => {
    cleanup();
  });
  opusStream.pipe(decoder);
  opusStream.once("end", () => {
    cleanup();
  });
  opusStream.once("error", () => {
    cleanup();
  });
}

function discardActiveBotCaptures(reason) {
  for (const [capturedUserId, capture] of [...activeCaptureControllers.entries()]) {
    if (!capture?.speakerIsBot || typeof capture.finalizeDiscarded !== "function") {
      continue;
    }
    console.log(
      `[DiscordBridgeDecision] Discarding bot speech capture: user=${capturedUserId}, reason=${reason}`
    );
    capture.finalizeDiscarded(reason).catch((error) => {
      console.error(`[DiscordBridge] Failed to discard bot capture user=${capturedUserId}:`, error);
    });
  }
}

function playbackImmunityRemainingMs() {
  if (!replyImmunitySeconds || replyImmunitySeconds <= 0 || !activePlaybackStartedAtMs) {
    return 0;
  }
  return Math.max(0, Math.round(replyImmunitySeconds * 1000 - (Date.now() - activePlaybackStartedAtMs)));
}

async function refreshCaptureOwnership(reason) {
  if (!sharedCaptureOwnerEnabled) {
    return true;
  }
  if (!isVoiceCaptureEligible()) {
    releaseCaptureOwner(`not_voice_ready:${reason || "refresh"}`);
    return false;
  }
  return tryAcquireCaptureOwner(reason);
}

function isCaptureOwner() {
  if (!sharedCaptureOwnerEnabled) {
    return true;
  }
  if (!isVoiceCaptureEligible()) {
    releaseCaptureOwner("not_voice_ready:speech_start");
    return false;
  }
  const owner = readCaptureOwner();
  if (owner && isCaptureOwnerFresh(owner) && isCaptureOwnerProcessAlive(owner)) {
    return String(owner.owner_id || "") === captureOwnerId();
  }
  return tryAcquireCaptureOwner("speech_start");
}

function tryAcquireCaptureOwner(reason) {
  if (!sharedCaptureOwnerEnabled) {
    return true;
  }
  if (!isVoiceCaptureEligible()) {
    releaseCaptureOwner(`not_voice_ready:${reason || "acquire"}`);
    return false;
  }
  const ownerId = captureOwnerId();
  const now = Date.now();
  const payload = {
    owner_id: ownerId,
    bot_instance_id: botInstanceId,
    bot_id: String(client.user?.id || ""),
    bot_name: String(client.user?.tag || client.user?.username || botDisplayName || botInstanceId),
    voice_channel_id: voiceChannelId,
    reason: String(reason || "capture_owner"),
    created_at: now,
    updated_at: now,
    expires_at: now + captureOwnerTtlMs
  };

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      writeFileSync(captureOwnerPath, JSON.stringify(payload, null, 2), { encoding: "utf8", flag: "wx" });
      console.log(`[DiscordBridgeCapture] Claimed capture owner: ${payload.bot_name}`);
      return true;
    } catch (error) {
      if (error?.code !== "EEXIST") {
        console.warn("[DiscordBridgeCapture] Could not create capture-owner lock; allowing capture:", error?.message || error);
        return true;
      }
    }

    const existing = readCaptureOwner();
    if (!existing || !isCaptureOwnerFresh(existing) || !isCaptureOwnerProcessAlive(existing)) {
      removeCaptureOwner("stale_or_dead");
      continue;
    }
    if (String(existing.owner_id || "") === ownerId) {
      refreshCaptureOwner(existing);
      return true;
    }
    return false;
  }
  return false;
}

function refreshCaptureOwner(existing) {
  if (!existing || String(existing.owner_id || "") !== captureOwnerId()) {
    return;
  }
  const now = Date.now();
  const updated = {
    ...existing,
    bot_id: String(client.user?.id || existing.bot_id || ""),
    bot_name: String(client.user?.tag || client.user?.username || existing.bot_name || botDisplayName || botInstanceId),
    updated_at: now,
    expires_at: now + captureOwnerTtlMs
  };
  try {
    writeFileSync(captureOwnerPath, JSON.stringify(updated, null, 2), "utf8");
  } catch {
    // Refresh failure should not interrupt capture.
  }
}

function readCaptureOwner() {
  try {
    return JSON.parse(readFileSync(captureOwnerPath, "utf8"));
  } catch {
    return null;
  }
}

function cleanupDeadCaptureOwnerOnStartup() {
  const owner = readCaptureOwner();
  if (!owner) {
    return;
  }
  if (!isCaptureOwnerFresh(owner) || !isCaptureOwnerProcessAlive(owner)) {
    removeCaptureOwner("stale_startup");
  }
}

function isCaptureOwnerFresh(owner) {
  const expiresAt = Number(owner?.expires_at || 0);
  return Number.isFinite(expiresAt) && expiresAt > Date.now();
}

function isCaptureOwnerProcessAlive(owner) {
  const ownerText = String(owner?.owner_id || "");
  const pidText = ownerText.includes(":") ? ownerText.split(":").pop() : "";
  const pid = Number(pidText);
  if (!Number.isInteger(pid) || pid <= 0) {
    return false;
  }
  if (pid === process.pid) {
    return true;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function releaseCaptureOwner(reason) {
  const owner = readCaptureOwner();
  if (!owner || String(owner.owner_id || "") !== captureOwnerId()) {
    return;
  }
  removeCaptureOwner(reason || "release");
}

function removeCaptureOwner(reason) {
  try {
    unlinkSync(captureOwnerPath);
    console.log(`[DiscordBridgeCapture] Capture owner cleared: ${reason}`);
  } catch {
    // Missing or already removed is fine.
  }
}

function captureOwnerId() {
  return `${botInstanceId}:${process.pid}`;
}

function captureOwnerLabel() {
  const owner = readCaptureOwner();
  if (!owner || !isCaptureOwnerFresh(owner)) {
    return "(none)";
  }
  return String(owner.bot_name || owner.bot_instance_id || owner.owner_id || "(unknown)");
}

function isVoiceCaptureEligible() {
  if (!activeVoiceConnection) {
    return false;
  }
  return activeVoiceConnection.state?.status === VoiceConnectionStatus.Ready;
}

function tryAcquireReplyFloor(turnId) {
  if (!coordinateBotReplies || replyFloorMode === "disabled" || !turnId) {
    return true;
  }
  const ownerId = replyFloorOwnerId();
  const now = Date.now();
  const payload = {
    owner_id: ownerId,
    bot_id: String(client.user?.id || ""),
    bot_name: String(client.user?.tag || client.user?.username || ""),
    turn_id: String(turnId),
    voice_channel_id: voiceChannelId,
    created_at: now,
    expires_at: now + Math.max(1000, Math.round(replyFloorStaleSeconds * 1000))
  };

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      writeFileSync(replyFloorPath, JSON.stringify(payload, null, 2), { encoding: "utf8", flag: "wx" });
      console.log(`[DiscordBridgeDecision] Claimed reply floor: turn=${turnId}`);
      return true;
    } catch (error) {
      if (error?.code !== "EEXIST") {
        console.warn("[DiscordBridge] Could not create reply-floor lock; allowing reply:", error?.message || error);
        return true;
      }
    }

    const existing = readReplyFloor();
    if (!existing || !isReplyFloorFresh(existing)) {
      removeReplyFloor("stale");
      continue;
    }
    if (String(existing.owner_id || "") === ownerId) {
      if (String(existing.turn_id || "") === String(turnId)) {
        refreshReplyFloor(existing);
        return true;
      }
      removeReplyFloor("replace_own_turn");
      continue;
    }
    console.log(
      `[DiscordBridgeDecision] Reply floor busy: owner=${existing.bot_name || existing.owner_id || "unknown"}, turn=${existing.turn_id || "?"}`
    );
    return false;
  }
  return false;
}

function releaseReplyFloor(turnId = "", options = {}) {
  if (!coordinateBotReplies || replyFloorMode === "disabled") {
    playbackDebug("release_floor_bypassed", {
      turnId,
      coordinateBotReplies,
      replyFloorMode,
      force: Boolean(options.force),
      reason: options.reason || ""
    });
    return;
  }
  const existing = readReplyFloor();
  if (!existing || String(existing.owner_id || "") !== replyFloorOwnerId()) {
    playbackDebug("release_floor_not_owner", {
      turnId,
      existingOwner: existing?.owner_id || "",
      owner: replyFloorOwnerId()
    });
    return;
  }
  if (turnId && String(existing.turn_id || "") !== String(turnId)) {
    playbackDebug("release_floor_turn_mismatch", {
      turnId,
      existingTurnId: existing.turn_id || ""
    });
    return;
  }
  const effectiveTurnId = String(turnId || existing.turn_id || "");
  if (!options.force && effectiveTurnId && hasPendingPlaybackForTurn(effectiveTurnId)) {
    playbackDebug("release_floor_deferred_playback", {
      turnId: effectiveTurnId,
      existingTurnId: existing.turn_id || "",
      queueLength: playbackQueue.length,
      playbackActive,
      activePlaybackTurnId,
      currentPlaybackTurnId: currentPlaybackItem?.turnId || ""
    });
    return;
  }
  playbackDebug("release_floor", {
    turnId,
    existingTurnId: existing.turn_id || "",
    queueLength: playbackQueue.length,
    playbackActive,
    activePlaybackTurnId,
    force: Boolean(options.force),
    reason: options.reason || ""
  });
  removeReplyFloor("release");
}

function refreshReplyFloor(existing) {
  const updated = {
    ...existing,
    expires_at: Date.now() + Math.max(1000, Math.round(replyFloorStaleSeconds * 1000))
  };
  try {
    writeFileSync(replyFloorPath, JSON.stringify(updated, null, 2), "utf8");
  } catch {
    // Refresh failure should not interrupt an already-owned floor.
  }
}

function readReplyFloor() {
  try {
    return JSON.parse(readFileSync(replyFloorPath, "utf8"));
  } catch {
    return null;
  }
}

function cleanupDeadReplyFloorOnStartup() {
  const floor = readReplyFloor();
  if (!floor) {
    return;
  }
  if (!isReplyFloorFresh(floor)) {
    removeReplyFloor("stale_startup");
    return;
  }
  if (!isReplyFloorOwnerProcessAlive(floor)) {
    removeReplyFloor("dead_owner_startup");
  }
}

function isReplyFloorFresh(floor) {
  const expiresAt = Number(floor?.expires_at || 0);
  return Number.isFinite(expiresAt) && expiresAt > Date.now() && isReplyFloorOwnerVoicePresent(floor);
}

function isReplyFloorOwnerProcessAlive(floor) {
  const owner = String(floor?.owner_id || "");
  const pidText = owner.includes(":") ? owner.split(":").pop() : "";
  const pid = Number(pidText);
  if (!Number.isInteger(pid) || pid <= 0) {
    return false;
  }
  if (pid === process.pid) {
    return true;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function isReplyFloorOwnerVoicePresent(floor) {
  const ownerId = String(floor?.owner_id || "");
  const ownerBotId = String(floor?.bot_id || (ownerId.includes(":") ? ownerId.split(":")[0] : "") || "").trim();
  if (!ownerBotId) {
    return true;
  }
  if (ownerId === replyFloorOwnerId()) {
    return isVoiceCaptureEligible();
  }
  const channel = activeVoiceChannel;
  if (!channel?.members) {
    return true;
  }
  return channel.members.has(ownerBotId);
}

function removeReplyFloor(reason) {
  try {
    unlinkSync(replyFloorPath);
    console.log(`[DiscordBridgeDecision] Reply floor cleared: ${reason}`);
  } catch {
    // Missing or already removed is fine.
  }
}

function replyFloorOwnerId() {
  return `${String(client.user?.id || tokenEnvVar || "discord_bot")}:${process.pid}`;
}

async function sendNcCancel(turnId, spokenText, reason, options = {}) {
  if (!turnId || bridgeMode !== "http") {
    return;
  }
  await fetch(ncCancelEndpoint, {
    method: "POST",
    headers: ncJsonHeaders(),
    body: JSON.stringify({
      turn_id: turnId,
      spoken_text: spokenText,
      reason,
      record_user_turn: Boolean(options.recordUserTurn)
    })
  }).catch((error) => {
    console.error("[NC] Cancel request failed:", error);
  });
}

async function sendNcFinish(turnId) {
  if (!turnId || bridgeMode !== "http") {
    return;
  }
  playbackDebug("send_finish_start", {
    turnId,
    queueLength: playbackQueue.length,
    playbackActive,
    activePlaybackTurnId,
    hasPendingPlayback: hasPendingPlaybackForTurn(turnId)
  });
  const payload = await fetch(ncFinishEndpoint, {
    method: "POST",
    headers: ncJsonHeaders(),
    body: JSON.stringify({ turn_id: turnId })
  }).then((response) => response.json().catch(() => ({}))).catch((error) => {
    console.error("[NC] Finish request failed:", error);
    return {};
  });
  if (activeNcTurnId === turnId) {
    activeNcTurnId = null;
  }
  if (activePlaybackTurnId === turnId) {
    if (hasPendingPlaybackForTurn(turnId)) {
      playbackDebug("send_finish_defer_floor_release", {
        turnId,
        queueLength: playbackQueue.length,
        playbackActive,
        activePlaybackTurnId
      });
      return;
    }
    releaseReplyFloor(turnId);
    forgetReplyTurnComplete(turnId);
    activePlaybackTurnId = null;
    activePlaybackStartedAtMs = 0;
    deliveredReplyTextParts = [];
  }
  if (payload && payload.ok === false) {
    console.warn("[NC] Finish was not accepted:", payload);
  }
}

function waitForPlaybackGenerationIdle(generation) {
  if (generation !== playbackGeneration || (!playbackActive && playbackQueue.length === 0 && !currentPlaybackItem)) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const check = () => {
      if (generation !== playbackGeneration || (!playbackActive && playbackQueue.length === 0 && !currentPlaybackItem)) {
        resolve();
        return;
      }
      setTimeout(check, 75);
    };
    check();
  });
}

function wavToDiscordPcmStream(wavPath) {
  if (!ffmpegPath) {
    throw new Error("ffmpeg-static did not provide an ffmpeg executable path.");
  }
  return new prism.FFmpeg({
    executable: ffmpegPath,
    args: [
      "-hide_banner",
      "-loglevel", "error",
      "-i", wavPath,
      "-f", "s16le",
      "-ar", "48000",
      "-ac", "2"
    ]
  });
}

function makeMockReplyPcm(inputDurationSeconds) {
  const first = makeTonePcm(392, 140);
  const pause = Buffer.alloc(48_000 * 2 * 2 * 0.08);
  const second = makeTonePcm(inputDurationSeconds > 4 ? 523 : 494, 180);
  const tailPause = Buffer.alloc(48_000 * 2 * 2 * 0.05);
  const third = makeTonePcm(330, 160);
  return Buffer.concat([first, pause, second, tailPause, third]);
}

function makeTonePcm(frequencyHz, durationMs) {
  const sampleRate = 48_000;
  const channels = 2;
  const samples = Math.floor(sampleRate * (durationMs / 1000));
  const buffer = Buffer.alloc(samples * channels * 2);

  for (let i = 0; i < samples; i += 1) {
    const envelope = Math.min(1, i / 1200, (samples - i) / 1200);
    const value = Math.sin((2 * Math.PI * frequencyHz * i) / sampleRate) * 0.08 * envelope;
    const int16 = Math.max(-32768, Math.min(32767, Math.round(value * 32767)));
    for (let channel = 0; channel < channels; channel += 1) {
      buffer.writeInt16LE(int16, (i * channels + channel) * 2);
    }
  }

  return buffer;
}

function bufferToStream(buffer) {
  const stream = new PassThrough();
  stream.end(buffer);
  return stream;
}

function encodeWav(pcmBuffer, sampleRate, channels, bitsPerSample) {
  const byteRate = sampleRate * channels * (bitsPerSample / 8);
  const blockAlign = channels * (bitsPerSample / 8);
  const header = Buffer.alloc(44);

  header.write("RIFF", 0);
  header.writeUInt32LE(36 + pcmBuffer.length, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write("data", 36);
  header.writeUInt32LE(pcmBuffer.length, 40);

  return Buffer.concat([header, pcmBuffer]);
}

function prepareCaptureWavPcm(discordPcmBuffer, targetSampleRate, targetChannels) {
  if (targetSampleRate === 48_000 && targetChannels === 2) {
    return { pcm: discordPcmBuffer, sampleRate: 48_000, channels: 2 };
  }
  if (targetSampleRate === 16_000 && targetChannels === 1) {
    return { pcm: downsampleDiscordPcmToMono16k(discordPcmBuffer), sampleRate: 16_000, channels: 1 };
  }
  console.warn(
    `[DiscordBridge] Unsupported capture WAV format ${targetSampleRate}Hz/${targetChannels}ch; using 16000Hz/mono.`
  );
  return { pcm: downsampleDiscordPcmToMono16k(discordPcmBuffer), sampleRate: 16_000, channels: 1 };
}

function downsampleDiscordPcmToMono16k(discordPcmBuffer) {
  const sourceFrames = Math.floor(discordPcmBuffer.length / 4);
  const targetFrames = Math.ceil(sourceFrames / 3);
  const output = Buffer.alloc(targetFrames * 2);
  let outputOffset = 0;

  for (let sourceFrame = 0; sourceFrame < sourceFrames; sourceFrame += 3) {
    let sum = 0;
    let count = 0;
    for (let offsetFrame = 0; offsetFrame < 3 && sourceFrame + offsetFrame < sourceFrames; offsetFrame += 1) {
      const inputOffset = (sourceFrame + offsetFrame) * 4;
      const left = discordPcmBuffer.readInt16LE(inputOffset);
      const right = discordPcmBuffer.readInt16LE(inputOffset + 2);
      sum += (left + right) / 2;
      count += 1;
    }
    output.writeInt16LE(clampInt16(Math.round(sum / Math.max(1, count))), outputOffset);
    outputOffset += 2;
  }

  return output.subarray(0, outputOffset);
}

function clampInt16(value) {
  return Math.max(-32768, Math.min(32767, value));
}

function positiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function captureSampleRateSetting(value) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return parsed === 48_000 ? 48_000 : 16_000;
}

function captureChannelsSetting(value) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return parsed === 2 ? 2 : 1;
}

function maxTurnSecondsSetting(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (parsed === -1) {
    return -1;
  }
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function formatMaxTurnSeconds(value) {
  return value === -1 ? "none" : `${value}s`;
}

function safeFileSegment(value) {
  return String(value || "default").replace(/[^a-zA-Z0-9_.-]+/g, "_").slice(0, 96) || "default";
}

function positiveFloat(value, fallback) {
  const parsed = Number.parseFloat(String(value ?? ""));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function nonNegativeFloat(value, fallback) {
  const parsed = Number.parseFloat(String(value ?? ""));
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function nonNegativeInt(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function asBool(value) {
  if (typeof value === "boolean") {
    return value;
  }
  return ["1", "true", "yes", "on"].includes(String(value ?? "").trim().toLowerCase());
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseUserIdList(value) {
  return String(value || "")
    .split(/[,\s;]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function ncJsonHeaders(extra = {}) {
  const headers = { "Content-Type": "application/json", ...extra };
  if (ncBridgeToken) {
    headers["X-NC-Discord-Bridge-Token"] = ncBridgeToken;
  }
  return headers;
}

function canAnswerUser(userId) {
  if (answerMode === "anyone") {
    return true;
  }
  if (!allowedUserIds.length) {
    return true;
  }
  return allowedUserIds.includes(String(userId));
}

function isDiscordBotUser(userId) {
  const member = activeVoiceChannel?.members?.get?.(String(userId));
  return Boolean(member?.user?.bot);
}

function cacheSpeakerName(userId, member) {
  const label = String(
    member?.displayName
    || member?.nickname
    || member?.user?.globalName
    || member?.user?.username
    || ""
  ).trim();
  if (label) {
    speakerNameCache.set(String(userId), label);
  }
}

function currentParticipantSnapshot() {
  const channel = activeVoiceChannel;
  if (!channel?.members) {
    return [];
  }
  const participants = [...channel.members.values()]
    .map((member) => {
      cacheSpeakerName(member.id, member);
      return {
        id: String(member.id),
        name: String(speakerNameCache.get(String(member.id)) || member.displayName || member.user?.username || member.id),
        is_bot: Boolean(member.user?.bot)
      };
    })
    .filter((item) => item.id && item.name)
    .sort((a, b) => a.name.localeCompare(b.name));
  const humanNameCounts = new Map();
  for (const participant of participants) {
    if (participant.is_bot) {
      continue;
    }
    const key = participantDisplayNameKey(participant.name);
    if (key) {
      humanNameCounts.set(key, (humanNameCounts.get(key) || 0) + 1);
    }
  }
  return participants.map((participant) => {
    const key = participantDisplayNameKey(participant.name);
    const conflict = Boolean(!participant.is_bot && key && humanNameCounts.get(key) > 1);
    return conflict
      ? {
          ...participant,
          display_name_conflict: true,
          name_conflict_reason: "Duplicate display name. Rename or alias this participant before routing."
        }
      : participant;
  });
}

function participantDisplayNameKey(value) {
  return String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function routerTargetTokenForName(name, fallback = "") {
  return safeFileSegment(String(name || "").trim() || String(fallback || "").trim()).toLowerCase();
}

function progressCounts(progress = {}, options = {}) {
  const readyChunks = Math.max(0, Number(progress?.readyChunks || 0));
  const completedChunks = Math.max(0, Number(progress?.playedChunks || 0));
  const inProgress = Boolean(options.inProgress);
  const playedChunks = inProgress
    ? Math.max(completedChunks, Math.min(Math.max(Number(progress?.totalChunks || 0), readyChunks, completedChunks, 1), completedChunks + 1))
    : completedChunks;
  const totalChunks = Math.max(
    Number(progress?.totalChunks || 0),
    readyChunks,
    playedChunks,
    Boolean(progress?.replyComplete) ? 0 : readyChunks
  );
  return { readyChunks, playedChunks, totalChunks };
}

function queuedAudioCountForStatus(activeTurnId) {
  const turnId = String(activeTurnId || "");
  if (!turnId) {
    return playbackQueue.length;
  }
  return playbackQueue.filter((item) => String(item?.turnId || "") === turnId).length;
}

function writeRuntimeStatus(state) {
  if (!runtimeStatusPath) {
    return;
  }
  try {
    mkdirSync(dirname(runtimeStatusPath), { recursive: true });
    const channel = activeVoiceChannel;
    const guild = channel?.guild || null;
    const floor = readReplyFloor();
    const floorFresh = floor && isReplyFloorFresh(floor);
    const ownsFloor = Boolean(floorFresh && String(floor?.owner_id || "") === replyFloorOwnerId());
    const localSpeaking = Boolean(playbackActive || currentPlaybackItem);
    const effectiveSpeaking = coordinateBotReplies && replyFloorMode !== "disabled" ? Boolean(localSpeaking && ownsFloor) : localSpeaking;
    const playbackTurnId = String(activePlaybackTurnId || currentPlaybackItem?.turnId || "");
    const renderProgress = activeReplyProgress || (playbackTurnId ? replyProgressByTurnId.get(playbackTurnId) : null) || {};
    const playbackProgress = (playbackTurnId ? replyProgressByTurnId.get(playbackTurnId) : null) || renderProgress || {};
    const moderatorState = readModeratorState();
    lastModeratorState = moderatorState;
    const renderCounts = progressCounts(renderProgress);
    const playbackCounts = progressCounts(playbackProgress, {
      inProgress: Boolean(playbackTurnId && localSpeaking && String(playbackProgress?.turnId || "") === playbackTurnId)
    });
    const payload = {
      state: String(state || "unknown"),
      updated_at: new Date().toISOString(),
      pid: process.pid,
      bridge_mode: bridgeMode,
      bot_id: String(client.user?.id || ""),
      bot_tag: String(client.user?.tag || client.user?.username || ""),
      guild_id: String(guild?.id || configuredGuildId || ""),
      guild_name: String(guild?.name || ""),
      voice_channel_id: String(channel?.id || voiceChannelId || ""),
      voice_channel_name: String(channel?.name || ""),
      participants: currentParticipantSnapshot(),
      speaking: effectiveSpeaking,
      local_speaking: localSpeaking,
      reply_floor_owner: String(floorFresh ? (floor?.owner_id || "") : ""),
      reply_floor_owner_bot: String(floorFresh ? (floor?.bot_name || "") : ""),
      owns_reply_floor: ownsFloor,
      capture_owner_enabled: sharedCaptureOwnerEnabled,
      capture_owner: String(captureOwnerLabel()),
      owns_capture: isCaptureOwner(),
      listening: activeCaptures.size > 0,
      active_captures: activeCaptures.size,
      queued_audio: queuedAudioCountForStatus(playbackTurnId),
      active_turn_id: String(playbackTurnId || activeNcTurnId || ""),
      render_ready_chunks: renderCounts.readyChunks,
      render_total_chunks: renderCounts.totalChunks,
      playback_completed_chunks: playbackCounts.playedChunks,
      playback_total_chunks: playbackCounts.totalChunks,
      reply_complete: Boolean(renderProgress?.replyComplete || playbackProgress?.replyComplete),
      last_transcript: String(lastTranscriptText || ""),
      last_route_decision: lastRouteDecision || {},
      moderator_state: moderatorState || {},
      last_error: String(lastErrorText || "")
    };
    writeFileSync(runtimeStatusPath, JSON.stringify(payload, null, 2), "utf8");
  } catch (error) {
    console.warn("[DiscordBridge] Could not write runtime status:", error?.message || error);
  }
}

function playbackDebug(event, fields = {}) {
  if (!playbackDebugEnabled) {
    return;
  }
  try {
    const payload = {
      ts: new Date().toISOString(),
      ms: Date.now(),
      bot: botInstanceId,
      event: String(event || "unknown"),
      ...fields
    };
    appendFileSync(playbackDebugPath, `${JSON.stringify(payload)}\n`, "utf8");
  } catch {
    // Debug logging must never affect Discord audio.
  }
}

function previewText(value, limit = 160) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function wavDurationSeconds(filePath) {
  const path = String(filePath || "");
  if (!path) {
    return null;
  }
  try {
    const header = readFileSync(path, { encoding: null, flag: "r" });
    if (header.length < 44 || header.toString("ascii", 0, 4) !== "RIFF" || header.toString("ascii", 8, 12) !== "WAVE") {
      return null;
    }
    const channels = header.readUInt16LE(22);
    const sampleRate = header.readUInt32LE(24);
    const bitsPerSample = header.readUInt16LE(34);
    let offset = 12;
    let dataSize = 0;
    while (offset + 8 <= header.length) {
      const chunkId = header.toString("ascii", offset, offset + 4);
      const chunkSize = header.readUInt32LE(offset + 4);
      if (chunkId === "data") {
        dataSize = chunkSize;
        break;
      }
      offset += 8 + chunkSize + (chunkSize % 2);
    }
    const bytesPerSecond = sampleRate * channels * Math.max(1, bitsPerSample / 8);
    if (!bytesPerSecond || !dataSize) {
      return null;
    }
    return Number((dataSize / bytesPerSecond).toFixed(3));
  } catch {
    return null;
  }
}

async function resolveSpeakerName(userId, guildId) {
  const cached = String(speakerNameCache.get(String(userId)) || "").trim();
  if (cached) {
    return cached;
  }
  try {
    const guild = client.guilds.cache.get(String(guildId)) || await client.guilds.fetch(String(guildId));
    const member = await guild.members.fetch(String(userId));
    cacheSpeakerName(userId, member);
    return speakerNameCache.get(String(userId)) || String(userId);
  } catch {
    // Some bots may not have member-fetch privileges; user fetch still gives a readable fallback.
  }
  try {
    const user = await client.users.fetch(String(userId));
    const label = String(user.globalName || user.username || "").trim();
    if (label) {
      speakerNameCache.set(String(userId), label);
      return label;
    }
  } catch {
    // Keep the bridge running even if Discord identity lookup fails.
  }
  return String(userId);
}

function cleanupOldWavFiles(directory, label) {
  if (!wavCleanupMaxAgeMinutes || wavCleanupMaxAgeMinutes <= 0) {
    return;
  }
  const cutoffMs = Date.now() - wavCleanupMaxAgeMinutes * 60_000;
  let removed = 0;
  let entries = [];
  try {
    entries = readdirSync(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (!entry.isFile() || !String(entry.name || "").toLowerCase().endsWith(".wav")) {
      continue;
    }
    const filePath = join(directory, entry.name);
    try {
      const stats = statSync(filePath);
      if (stats.mtimeMs >= cutoffMs) {
        continue;
      }
      rmSync(filePath, { force: true });
      removed += 1;
    } catch {
      // Ignore files being touched by another capture or antivirus scan.
    }
  }
  if (removed > 0) {
    console.log(`[DiscordBridge] Cleaned ${removed} old ${label} WAV file(s).`);
  }
}
