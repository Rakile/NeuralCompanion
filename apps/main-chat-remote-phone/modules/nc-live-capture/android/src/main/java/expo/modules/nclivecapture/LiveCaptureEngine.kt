package expo.modules.nclivecapture

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.AudioAttributes
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.Process
import android.os.SystemClock
import androidx.core.content.ContextCompat
import expo.modules.audio.NCPhoneReplyOnset
import expo.modules.audio.NCPlaybackGuard
import expo.modules.audio.NCSoundscapeActivity
import expo.modules.audio.NCSoundscapeScope
import expo.modules.audio.NCCommunicationRoute
import expo.modules.audio.NCConnectionCueOutput
import expo.modules.audio.NCCaptureRoute
import expo.modules.audio.NCMicrophoneRouteEvidence
import java.util.UUID
import java.util.concurrent.ExecutionException
import java.util.concurrent.CompletableFuture
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

data class CaptureNotification(
  val sessionId: String, val sequence: Int, val kind: String, val phase: String,
  val utteranceId: String? = null, val durationMs: Double = 0.0, val meteringDb: Double? = null,
  val error: String? = null, val backgroundAuthorized: Boolean? = null,
  val lifetime: String = CaptureLifetime.CLOSED.wireValue,
  val phoneReplyReceipt: Map<String, Any>? = null, val phoneReplyUnavailable: Boolean = false,
  val captureId:String?=null
) {
  fun payload(): Map<String, Any> = buildMap {
    put("sessionId", sessionId); put("sequence", sequence); put("kind", kind); put("phase", phase); put("durationMs", durationMs)
    utteranceId?.let { put("utteranceId", it) }; meteringDb?.let { put("meteringDb", it) }; error?.let { put("error", it) }
    backgroundAuthorized?.let { put("backgroundAuthorized", it) }; put("lifetime", lifetime)
    phoneReplyReceipt?.let { put("phoneReplyReceipt", it) }; if (phoneReplyUnavailable) put("phoneReplyUnavailable", true)
    captureId?.let{put("captureId",it)}
  }
}

private class NativeCommunicationLease(
  context: Context, private val ticket: String?,
  private val invalidated: (NativeCommunicationLease) -> Unit,
  private val independent:Boolean=false,
  private val routeHandler: Handler
) : CaptureRouteLease {
  val routeInvalidationPending = AtomicBoolean(false)
  private val manager = context.getSystemService(AudioManager::class.java)
  private val selection = NCCaptureRoute(manager, ticket ?: "unprotected-live") {
    ContextCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED
  }.also { route ->
    val retainedTicket = ticket
    if (independent && context.packageName == "com.neuralcompanion.mainchatremote.dev")
      route.enableForegroundRetention { retainedTicket != null && NCPlaybackGuard.shared.isOpen(retainedTicket) }
  }
  @Volatile private var callbackRegistered = false
  private val token: NCCommunicationRoute.Token? get() = selection.token
  private val routeCheck = Runnable { if (callbackRegistered) checkRoute() }
  private fun queueRouteCheck() {
    if (!callbackRegistered) return
    routeHandler.removeCallbacks(routeCheck)
    routeHandler.post(routeCheck)
  }
  private val callback = object : AudioDeviceCallback() {
    override fun onAudioDevicesAdded(devices: Array<out AudioDeviceInfo>?) = queueRouteCheck()
    override fun onAudioDevicesRemoved(devices: Array<out AudioDeviceInfo>?) = queueRouteCheck()
  }
  fun bind(device: AudioDeviceInfo): Boolean {
    if (Build.VERSION.SDK_INT < 31 || ticket == null || token != null) return false
    if (!selection.bind(device)) { release(); return false }
    manager.registerAudioDeviceCallback(callback, routeHandler)
    callbackRegistered = true
    return true
  }
  fun bindBluetooth(actualInput: () -> Int?, current: () -> Boolean): Boolean {
    check(ticket != null) { "capture_route_owner_missing" }
    if (!selection.selectBluetooth()) return false
    manager.registerAudioDeviceCallback(callback, routeHandler)
    callbackRegistered = true
    selection.confirmMicrophone(actualInput, current)
    return true
  }
  val selectedType: Int? get() = token?.deviceType
  fun preparing(): Boolean = token?.let { NCCommunicationRoute.shared.isPreparing(it.ticket) } == true
  fun finishPreparation() = selection.finishPreparation()
  fun valid(evidence: MutableMap<String, Any>? = null): Boolean {
    val started = if (evidence != null) SystemClock.elapsedRealtime() else 0L
    try {
      evidence?.put("lease_check", "token")
      val expected = token ?: run { evidence?.put("lease_selected", false); return true }
      evidence?.put("lease_selected", true)
      evidence?.put("lease_check", "api_level")
      if (Build.VERSION.SDK_INT < 31) return false
      evidence?.put("lease_check", "communication_device_read")
      val actual = manager.communicationDevice
      evidence?.put("communication_device_present", actual != null)
      evidence?.put("lease_check", "communication_mode")
      val modeMatches = manager.mode == AudioManager.MODE_IN_COMMUNICATION
      evidence?.put("communication_mode_matches", modeMatches)
      if (!modeMatches) return false
      evidence?.put("lease_check", "route_ownership_or_device")
      val accepted = NCCommunicationRoute.shared.accepts(expected, actual?.id, actual?.type)
      val idMatches = actual?.id == expected.deviceId
      val typeMatches = actual?.type == expected.deviceType
      evidence?.put("communication_device_id_matches", idMatches)
      evidence?.put("communication_device_type_matches", typeMatches)
      // accepts() checks owner and identity atomically. If identity matches,
      // its result is also exact owner evidence, without rereading shared state.
      if (idMatches && typeMatches) evidence?.put("route_owner_matches", accepted)
      if (!accepted) {
        evidence?.put("lease_check", if (idMatches && typeMatches) "route_owner" else "communication_device")
        return false
      }
      evidence?.put("lease_check", "output_inventory")
      val present = manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any { it.id == expected.deviceId && it.type == expected.deviceType }
      evidence?.put("output_device_present", present)
      if (present) evidence?.put("lease_check", "ready")
      return present
    } catch (error: Throwable) {
      evidence?.put("lease_exception_type", when (error) {
        is SecurityException -> "SecurityException"; is IllegalStateException -> "IllegalStateException"
        is IllegalArgumentException -> "IllegalArgumentException"; else -> "other"
      })
      return false
    } finally {
      evidence?.put("lease_check_elapsed_ms", SystemClock.elapsedRealtime() - started)
    }
  }
  override fun retainedSnapshot(): RouteSnapshot? {
    val expected = token ?: return null
    if (!valid()) return null
    val category = when (expected.deviceType) {
      AudioDeviceInfo.TYPE_BLUETOOTH_SCO, AudioDeviceInfo.TYPE_BLE_HEADSET -> BackgroundRoute.BLUETOOTH
      AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> BackgroundRoute.WIRED
      else -> return null
    }
    val output = when (expected.deviceType) {
      AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "bluetoothSco"
      AudioDeviceInfo.TYPE_BLE_HEADSET -> "bluetoothLE"
      AudioDeviceInfo.TYPE_WIRED_HEADSET -> "wiredHeadset"
      else -> "wiredHeadphones"
    }
    return RouteSnapshot(category, "${expected.deviceType}:${expected.deviceId}", "unknown", output)
  }
  private fun checkRoute() {
    val expected = token ?: return
    if (NCCommunicationRoute.shared.isPreparing(expected.ticket)) return
    if (!valid() && NCCommunicationRoute.shared.isCurrent(expected) &&
      !NCCommunicationRoute.shared.isPreparing(expected.ticket)) {
      // The serial owner checks this exact lease again before retiring output.
      // An Android query may return after this capture has already been replaced.
      invalidated(this)
    }
  }
  override fun release() {
    // Leave each resource owned until that individual cleanup call confirms success.
    token?.let {
      if (!independent && NCPlaybackGuard.shared.outputState().armed)
        NCPlaybackGuard.shared.retire(it.ticket, NCPlaybackGuard.RetirementCause.EXPLICIT)
    }
    if (callbackRegistered) { manager.unregisterAudioDeviceCallback(callback); callbackRegistered = false }
    routeHandler.removeCallbacks(routeCheck)
    selection.release()
  }
}

private class NativeCaptureDriver(
  private val context: Context,
  override val routeLease: NativeCommunicationLease,
  private val samples: (NativeCaptureDriver, ShortArray, Long, Long) -> Unit,
  private val invalidated: (NativeCaptureDriver, CaptureFailure) -> Unit,
  private val routeHandler: Handler
) : CaptureDriver {
  val routeInvalidationPending = AtomicBoolean(false)
  private val audioManager = context.getSystemService(AudioManager::class.java)
  private val stopping = AtomicBoolean(false)
  private val inputAdmitted = AtomicBoolean(false)
  private var record: AudioRecord? = null
  private val flushInputEpoch = AtomicLong(0)
  private var worker: Thread? = null
  private var echo: AcousticEchoCanceler? = null
  private var deviceCallbackRegistered = false
  private var recordingCallbackRegistered = false
  @Volatile private var routeNegotiating = false
  @Volatile private var expectedRouteKey = ""
  @Volatile private var voiceActive = false
  private val routeEvidence = NCMicrophoneRouteEvidence("live")
  @Volatile private var requestedInputType: Int? = null
  private val routeCheck = Runnable { routeChanged() }
  private fun queueRouteCheck() {
    if (stopping.get()) return
    routeHandler.removeCallbacks(routeCheck)
    routeHandler.post(routeCheck)
  }
  private val deviceCallback = object : AudioDeviceCallback() {
    override fun onAudioDevicesAdded(addedDevices: Array<out AudioDeviceInfo>?) = queueRouteCheck()
    override fun onAudioDevicesRemoved(removedDevices: Array<out AudioDeviceInfo>?) = queueRouteCheck()
  }
  private val recordingCallback: AudioManager.AudioRecordingCallback? = if (Build.VERSION.SDK_INT >= 29) object : AudioManager.AudioRecordingCallback() {
    override fun onRecordingConfigChanged(configs: MutableList<android.media.AudioRecordingConfiguration>?) {
      val mine = configs?.firstOrNull { it.clientAudioSessionId == record?.audioSessionId }
      if (mine != null && !stopping.get()) runCatching {
        routeEvidence.observe("route_changed", mine.audioDevice?.type, requestedInputType, outputObserved = false)
      }
      if (mine?.isClientSilenced == true) invalidated(this@NativeCaptureDriver, CaptureFailure.INTERRUPTED)
    }
  } else null

  val inputRouteAdmitted get() = inputAdmitted.get()
  override val voiceProcessingActive get() = voiceActive
  override val routeKey get() = expectedRouteKey

  override fun start() {
    if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
      throw CapturePolicyException(CaptureFailure.PERMISSION_DENIED)
    val minBytes = AudioRecord.getMinBufferSize(16_000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
    if (minBytes <= 0) throw CapturePolicyException(CaptureFailure.UNSUPPORTED_FORMAT)
    val candidate = AudioRecord.Builder()
      .setAudioSource(MediaRecorder.AudioSource.VOICE_COMMUNICATION)
      .setAudioFormat(AudioFormat.Builder().setSampleRate(16_000).setChannelMask(AudioFormat.CHANNEL_IN_MONO)
        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
      .setBufferSizeInBytes(maxOf(minBytes, 6_400))
      .build()
    if (candidate.state != AudioRecord.STATE_INITIALIZED) { candidate.release(); throw CapturePolicyException(CaptureFailure.START_FAILED) }
    record = candidate
    if (AcousticEchoCanceler.isAvailable()) {
      echo = AcousticEchoCanceler.create(candidate.audioSessionId)?.also { it.enabled = true }
      voiceActive = echo?.enabled == true
    }
    audioManager.registerAudioDeviceCallback(deviceCallback, routeHandler)
    deviceCallbackRegistered = true
    if (Build.VERSION.SDK_INT >= 29 && recordingCallback != null) {
      audioManager.registerAudioRecordingCallback(recordingCallback, routeHandler)
      recordingCallbackRegistered = true
    }
    candidate.startRecording()
    if (candidate.recordingState != AudioRecord.RECORDSTATE_RECORDING) throw CapturePolicyException(CaptureFailure.START_FAILED)
    val initialRoute = snapshot()
    expectedRouteKey = initialRoute.key.substringBefore('|')
    recordRouteEvidence("started", initialRoute)
    worker = Thread({ readLoop(candidate) }, "nc-live-capture-audiorecord").apply { priority = Thread.MAX_PRIORITY; start() }
  }

  fun bindConfirmedBluetoothDuplex(): RouteSnapshot? {
    if (Build.VERSION.SDK_INT < 31) return null
    routeNegotiating = true
    try {
      if (!routeLease.bindBluetooth({ record?.routedDevice?.type }, { !stopping.get() })) return null
      requestedInputType = routeLease.selectedType
      val route = snapshot()
      if (route.category != BackgroundRoute.BLUETOOTH) {
        recordRouteEvidence("bind_rejected", route)
        throw CapturePolicyException(CaptureFailure.ROUTE_CHANGED)
      }
      recordRouteEvidence("bind_accepted", route)
      expectedRouteKey = route.key
      return route
    } finally { routeNegotiating = false }
  }

  fun bindWiredDuplex(): RouteSnapshot? {
    if (Build.VERSION.SDK_INT < 31) return null
    val device = audioManager.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_WIRED_HEADSET } ?: return null
    requestedInputType = device.type
    routeNegotiating = true
    try {
      if (!routeLease.bind(device)) {
        routeEvidence.observe("selection_rejected", null, requestedInputType); requestedInputType = null; return null
      }
      Thread.sleep(80)
      val route = snapshot()
      if (route.category != BackgroundRoute.WIRED) {
        recordRouteEvidence("bind_rejected", route); routeLease.release(); requestedInputType = null; return null
      }
      recordRouteEvidence("bind_accepted", route)
      expectedRouteKey = route.key
      return route
    } finally { routeNegotiating = false }
  }

  fun bindForegroundDuplex() {
    // Foreground routing grants no background microphone permission. Reuse an
    // already verified route on repeated arm; otherwise prefer a headphone mic.
    if (routeLease.retainedSnapshot() != null) return
    if (bindConfirmedBluetoothDuplex() != null || bindWiredDuplex() != null) return
    expectedRouteKey = foregroundArmInputKey(expectedRouteKey, snapshot().key)
  }

  fun foregroundRouteReady(): Boolean {
    val evidence = mutableMapOf<String, Any>("readiness_result" to "failed")
    val started = SystemClock.elapsedRealtime()
    try {
      evidence["readiness_check"] = "stopping"
      if (stopping.get()) return false
      evidence["readiness_check"] = "negotiating"
      if (routeNegotiating) return false
      evidence["readiness_check"] = "recording_state"
      if (record?.recordingState != AudioRecord.RECORDSTATE_RECORDING) return false
      evidence["readiness_check"] = "route_lease"
      if (!routeLease.valid(evidence)) return false
      evidence["readiness_check"] = "route_identity"
      val actual = snapshot()
      evidence["readiness_input"] = actual.input
      evidence["readiness_output"] = actual.output
      if (!routeKeyMatches(expectedRouteKey, actual.key)) return false
      evidence["readiness_result"] = "ready"
      evidence["readiness_check"] = "ready"
      return true
    } catch (error: Throwable) {
      evidence["readiness_result"] = "exception"
      throw error
    } finally {
      evidence["readiness_elapsed_ms"] = SystemClock.elapsedRealtime() - started
      foregroundReadinessEvidence = evidence.toMap()
    }
  }
  var foregroundReadinessEvidence: Map<String, Any> = emptyMap()
    private set

  fun recordRouteEvidence(reason: String, route: RouteSnapshot?) {
    routeEvidence.observe(reason, route?.key?.substringBefore(':')?.toIntOrNull(), requestedInputType,
      route?.key?.substringAfter('|')?.substringBefore(':')?.toIntOrNull())
  }

  fun recordInputFailure() {
    // Capture the actual microphone before release, without a potentially
    // blocking communication-output query on the failure/cleanup path.
    val actual = runCatching { record?.routedDevice?.type }.getOrNull()
    routeEvidence.observe("failed", actual, requestedInputType, outputObserved = false)
  }

  fun snapshot(): RouteSnapshot {
    // Android's communication-device read can wait while SCO is connecting.
    // Sample the actual input afterward, not from before that routing update.
    val outputDevice = if (Build.VERSION.SDK_INT >= 31) audioManager.communicationDevice else null
    val inputDevice = record?.routedDevice
    val inputType = inputDevice?.type ?: -1
    val outputType = outputDevice?.type ?: -1
    val bluetooth = inputType == outputType &&
      (inputType == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || inputType == AudioDeviceInfo.TYPE_BLE_HEADSET)
    val wired = inputType == AudioDeviceInfo.TYPE_WIRED_HEADSET &&
      (outputType == AudioDeviceInfo.TYPE_WIRED_HEADSET || outputType == AudioDeviceInfo.TYPE_WIRED_HEADPHONES)
    val category = when { bluetooth -> BackgroundRoute.BLUETOOTH; wired -> BackgroundRoute.WIRED; else -> BackgroundRoute.INELIGIBLE }
    return RouteSnapshot(category, "$inputType:${inputDevice?.id ?: -1}|$outputType:${outputDevice?.id ?: -1}",
      routeName(inputType), routeName(outputType))
  }

  private fun routeChanged() {
    // Android delivers initial device callbacks as soon as registration returns.
    // Foreground/background arm validates the selected route before admitting
    // samples; a pre-admission observation must not stop that setup transaction.
    if (!inputAdmitted.get() || routeNegotiating || stopping.get() || routeLease.preparing()) return
    val route = snapshot()
    if (!inputAdmitted.get() || routeNegotiating || stopping.get() || routeLease.preparing()) return
    recordRouteEvidence("route_changed", route)
    if (!routeKeyMatches(expectedRouteKey, route.key)) invalidated(this, CaptureFailure.ROUTE_CHANGED)
  }

  private fun readLoop(source: AudioRecord) {
    Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_AUDIO)
    val buffer = ShortArray(1_600)
    var appliedInputEpoch = 0L
    while (!stopping.get()) {
      val requestedInputEpoch = flushInputEpoch.get()
      if (requestedInputEpoch != appliedInputEpoch) {
        // Empty native AudioRecord backlog without stopping/restarting its authorized microphone.
        while (!stopping.get() && source.read(buffer, 0, buffer.size, AudioRecord.READ_NON_BLOCKING) > 0) {}
        appliedInputEpoch = requestedInputEpoch
      }
      val capturedAt = SystemClock.elapsedRealtime()
      val admittedBeforeRead = inputAdmitted.get()
      val count = source.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING)
      if (count > 0) {
        // Drain during route negotiation without filling the serial owner's
        // bounded queue. Discard the read straddling admission as well.
        if (admittedBeforeRead && inputAdmitted.get() && !stopping.get())
          samples(this, buffer.copyOf(count), capturedAt, appliedInputEpoch)
      }
      else if (!stopping.get()) {
        routeEvidence.captureFailure("audio_record_read", "audio_read", mapOf("read_result" to count))
        invalidated(this, CaptureFailure.CAPTURE_OVERFLOW); break
      }
    }
  }

  fun discardBufferedInput(epoch: Long) { flushInputEpoch.set(epoch) }

  fun admitInput() {
    routeLease.finishPreparation()
    if (!stopping.get()) inputAdmitted.set(true)
  }

  @Synchronized override fun stopAndDrain() {
    inputAdmitted.set(false)
    val firstStop = stopping.compareAndSet(false, true)
    routeHandler.removeCallbacks(routeCheck)
    val source = record
    if (firstStop) try { source?.stop() } catch (_: IllegalStateException) {}
    val failures = mutableListOf<Throwable>()
    try { worker?.join(5_000) } catch (error: Throwable) { failures += error }
    if (recordingCallbackRegistered && Build.VERSION.SDK_INT >= 29 && recordingCallback != null) {
      try { audioManager.unregisterAudioRecordingCallback(recordingCallback); recordingCallbackRegistered = false }
      catch (error: Throwable) { failures += error }
    }
    if (deviceCallbackRegistered) {
      try { audioManager.unregisterAudioDeviceCallback(deviceCallback); deviceCallbackRegistered = false }
      catch (error: Throwable) { failures += error }
    }
    echo?.let { effect ->
      try { effect.release(); echo = null; voiceActive = false } catch (error: Throwable) { failures += error }
    }
    source?.let { capture ->
      try { capture.release(); record = null } catch (error: Throwable) { failures += error }
    }
    try { worker?.join(1_000) } catch (error: Throwable) { failures += error }
    if (worker?.isAlive == true) failures += IllegalStateException("AudioRecord worker did not drain after release")
    else worker = null
    if (record != null || echo != null || deviceCallbackRegistered || recordingCallbackRegistered ||
      worker != null) {
      failures += IllegalStateException("AudioRecord cleanup is incomplete")
    }
    failures.firstOrNull()?.let { throw it }
  }

  private fun routeName(type: Int) = when (type) {
    AudioDeviceInfo.TYPE_BUILTIN_MIC -> "builtInMic"; AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> "builtInSpeaker"
    AudioDeviceInfo.TYPE_WIRED_HEADSET -> "wiredHeadset"; AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> "wiredHeadphones"
    AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "bluetoothSco"; AudioDeviceInfo.TYPE_BLE_HEADSET -> "bluetoothLE"
    else -> "unknown"
  }
}

/** A small native PCM cue on the already selected route; never requests audio focus. */
private class NativeRecoveryCue(private val context: Context) {
  private var output: NCConnectionCueOutput? = null
  @Synchronized fun stop() {
    output?.stop(); output = null
  }
  @Synchronized fun play(resumed: Boolean, session: String, ticket: String, epoch: Long) {
    stop()
    val rate = ConnectionCue.SAMPLE_RATE
    val cue = NCConnectionCueOutput(authorize = { stop, play ->
      NCPlaybackGuard.shared.performConnectionCue(ticket, session, epoch, stop, play)
    }, createTrack = { bytes ->
      val route = NCCommunicationRoute.shared.forTicket(ticket)
      val candidate = AudioTrack.Builder().setAudioAttributes(AudioAttributes.Builder()
      .setUsage(if (route != null) AudioAttributes.USAGE_VOICE_COMMUNICATION else AudioAttributes.USAGE_MEDIA)
      .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
      .setAudioFormat(AudioFormat.Builder().setSampleRate(rate).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
      .setBufferSizeInBytes(bytes).setTransferMode(AudioTrack.MODE_STATIC).build()
      try {
        if (route != null) {
          val device = context.getSystemService(AudioManager::class.java).getDevices(AudioManager.GET_DEVICES_OUTPUTS)
            .firstOrNull { it.id == route.deviceId && it.type == route.deviceType }
            ?: throw CapturePolicyException(CaptureFailure.ROUTE_CHANGED)
          if (!candidate.setPreferredDevice(device)) throw CapturePolicyException(CaptureFailure.ROUTE_CHANGED)
        }
        candidate
      } catch (error: Throwable) { candidate.release(); throw error }
    })
    output = cue
    if (!cue.play(resumed)) throw CapturePolicyException(CaptureFailure.INTERRUPTED)
  }
}

class LiveCaptureEngine(private val context: Context, private val foreground: () -> Boolean) : LiveAudioService.Controller {
  private val overflow = AtomicBoolean(false)
  private var observedAudioDrops = 0
  private var observedAudioEvictions = 0
  private val cleanupRetryScheduled = AtomicBoolean(false)
  private val destroyAdmissionPending = AtomicBoolean(false)
  private val serviceDestroyedAdmissionPending = AtomicBoolean(false)
  private val stopAdmissionPending = AtomicBoolean(false)
  private val backgroundAdmissionPending = AtomicBoolean(false)
  private val pendingStopLock = Any()
  private var pendingStop: Pair<CaptureFailure, Boolean>? = null
  private val cleanupSupervisor = CleanupSupervisor()
  private val mainHandler = Handler(Looper.getMainLooper())
  // Bluetooth Binder reads can take seconds. Never perform callback route reads
  // on the UI thread or the bounded PCM/control dispatcher.
  private val routeThread = HandlerThread("nc-live-capture-route").apply { start() }
  private val routeHandler = Handler(routeThread.looper)
  private val executor = BoundedSerialDispatcher("nc-live-capture-owner", audioCapacity = 12, controlReserve = 4)
  private val captureEvidence = NCMicrophoneRouteEvidence("live")
  @Volatile private var captureWork = "steady" to 0L
  private val segmenter = LiveSegmenter()
  private val store = UtteranceStore(context.cacheDir)
  private val leases = mutableMapOf<Pair<String, String>, Long>()
  private var emitter: ((CaptureNotification) -> Unit)? = null
  private var sequence = 0
  private var eventSession: String? = null
  private var playbackActive = false
  private var closed = false
  private var lastForegroundArm: Map<String, Any?>? = null
  private var cleanupFailurePublished = false
  private var cleanupSessionId: String? = null
  private var outstandingState: Int? = null
  private var pendingState: Triple<String, Double, Double?>? = null
  private val onsetFence = CaptureOnsetFence()
  private var recovery = ConnectionRecoveryClock()
  private val recoveryCue = NativeRecoveryCue(context)
  private var resumeResult: CompletableFuture<Boolean>? = null
  private var recoveryCallback: Runnable? = null
  @Volatile private var inputEpoch = 0L
  private val guard = NCPlaybackGuard.shared
  private val policy = LiveCapturePolicy(
    retireOutput = { ticket -> guard.retire(ticket); if (ticket == protectedTicket) { protectedTicket = null; protectedSession = null } },
    registerSubmission = { ticket, session, upload -> guard.registerReplySubmission(ticket, session, upload) },
    sealReplyTail = { session, ticket, requests, pending -> guard.sealReplyTail(ticket, session, requests, pending) },
    finishEmptyTail = { ticket, session -> guard.finishEmptyTail(ticket, session) },
    detachCapture = { session,ticket ->
      val attachment=captureAttachments[session]?.takeIf{it.ticket==ticket}
        ?: throw CapturePolicyException(CaptureFailure.RELEASE_FAILED)
      // Real output retirement already invalidates this attachment. It does
      // not excuse a failed input drain: policy calls here only after release.
      if(guard.isOpen(ticket)&&!guard.detachCapture(attachment))throw CapturePolicyException(CaptureFailure.RELEASE_FAILED)
      if(protectedSession==session){protectedSession=null;protectedTicket=null}
    }
  )
  private val captureAttachments=linkedMapOf<String,NCPlaybackGuard.CaptureAttachment>()
  @Volatile private var activeAttachment:NCPlaybackGuard.CaptureAttachment?=null
  private var eventCaptureId:String?=null
  private var captureController:LiveAudioService.Controller=this
  private fun controllerFor(a:NCPlaybackGuard.CaptureAttachment)=object:LiveAudioService.Controller {
    private fun deliver(action:()->Unit) {
      if(executor.isShutdown)return
      call {if(activeAttachment==a)action()}
    }
    override fun stopConversation()=deliver {
      guard.retire(a.ticket);systemStop(CaptureFailure.CONVERSATION_STOPPED)
    }
    override fun authorizationExpired()=deliver {systemStop(CaptureFailure.BACKGROUND_SESSION_LIMIT)}
    override fun serviceDestroyed()=deliver {
      cleanupSupervisor.serviceDestroyed();systemStop(CaptureFailure.INTERRUPTED,false)
    }
    override fun serviceStartFailed(ticket:String?,generation:Long)=deliver {systemStop(CaptureFailure.START_FAILED,false)}
    override fun safetyTick() {if(activeAttachment==a)this@LiveCaptureEngine.safetyTick()}
  }
  private var protectedTicket: String? = null
  private var protectedSession: String? = null
  @Volatile private var activeDriver: NativeCaptureDriver? = null
  private var soundscapeLease: SoundscapeServiceReason.Lease? = null
  private var soundscapeScope: NCSoundscapeScope? = null
  private val soundscapeOwner = object: NCSoundscapeActivity.Owner {
    override fun acquire(scope: NCSoundscapeScope): CompletableFuture<Boolean> {
      val result=CompletableFuture<Boolean>()
      try { executor.executeControl {
        try {
          if(closed || (!foreground() && !LiveAudioService.canRetainSoundscape()
              && soundscapeLease?.let { LiveAudioService.admitsSoundscape(it) } != true)) {
            result.complete(false); return@executeControl
          }
          val lease=LiveAudioService.acquireSoundscape(context,this@LiveCaptureEngine,scope.conversationId,
            scope.sessionGeneration,scope.playbackGeneration,scope.revision) {
            mainHandler.post { NCSoundscapeActivity.revoked(scope) }
          }
          soundscapeLease=lease; soundscapeScope=scope; result.complete(true)
        } catch(error: Throwable) { result.completeExceptionally(error) }
      } } catch(error: Throwable) { result.completeExceptionally(error) }
      return result
    }
    override fun release(scope: NCSoundscapeScope) {
      try { executor.executeControl {
        val current=soundscapeScope
        if(current!=null && current.conversationId==scope.conversationId && current.sessionGeneration==scope.sessionGeneration
          && scope.revision>=current.revision && scope.playbackGeneration>=current.playbackGeneration) {
          soundscapeLease?.let { LiveAudioService.releaseSoundscape(context,it) }
          soundscapeLease=null; soundscapeScope=null
        }
      } } catch (_: RejectedExecutionException) { }
    }
  }
  init { NCSoundscapeActivity.install(soundscapeOwner) }

  fun setEmitter(value: (CaptureNotification) -> Unit) = call { emitter = value }

  fun capabilities(): Map<String, Any> = call {
    val driver = policy.driverIdentity as? NativeCaptureDriver
    val route = policy.capabilityRoute(driver?.snapshot())
    val state = guard.outputState()
    mapOf("available" to !closed, "reason" to if (closed) "Capture module is closed." else "",
      "voiceProcessingSupported" to AcousticEchoCanceler.isAvailable(), "voiceProcessingActive" to policy.voiceProcessingActive,
      "lastRetirementCause" to state.lastRetirementCause, "duckingSupported" to false,
      "backgroundLiveVersion" to 1, "independentCaptureVersion" to 1, "playbackGuardVersion" to NCPlaybackGuard.VERSION,
      "stopListeningVersion" to 1, "foregroundReplyControlsVersion" to 1, "connectionRecoveryVersion" to 1, "replyContinuationVersion" to 1,
      "backgroundRoute" to (route?.category?.wireValue ?: "ineligible"),
      "inputRoute" to (route?.input ?: "unknown"), "outputRoute" to (route?.output ?: "unknown"))
  }

  fun outputState(): Map<String, Any?> = call {
    val state = guard.outputState()
    mapOf("ticket" to state.ticket, "open" to state.open, "sessionId" to state.sessionId,
      "lastRetirementCause" to state.lastRetirementCause, "foregroundArmFailure" to lastForegroundArm)
  }

  fun beginProtectedOutput(session: String, expected: String?, foregroundOnly: Boolean): String = call {
    if (closed) fail(CaptureFailure.START_FAILED)
    val ticket = try { guard.begin(expected, session, foregroundOnly) } catch (error: Throwable) { throw CapturePolicyException(CaptureFailure.START_FAILED, error) }
    try { policy.adoptProtectedOutput(session, ticket, foregroundOnly); protectedTicket = ticket; protectedSession = session; ticket }
    catch (error: Throwable) { guard.retire(ticket); throw error }
  }

  fun attachCapture(session:String,ticket:String,foregroundOnly:Boolean):Map<String,String> = call {
    if(closed||cleanupSupervisor.pending||policy.currentSessionId!=null||policy.outputSessionId!=null)fail(CaptureFailure.START_FAILED)
    // Remove only scopes whose playback owner was genuinely revoked.
    captureAttachments.entries.removeAll{!guard.isOpen(it.value.ticket)}
    val attachment=guard.attachCapture(ticket,session)
    try {policy.adoptCapture(session,ticket,foregroundOnly)}catch(error:Throwable){guard.detachCapture(attachment);throw error}
    captureAttachments[session]=attachment;activeAttachment=attachment;eventCaptureId=attachment.captureId
    captureController=controllerFor(attachment)
    protectedTicket=ticket;protectedSession=session
    mapOf("ticket" to ticket,"sessionId" to session,"captureId" to attachment.captureId)
  }
  fun captureAttachmentState(session:String,ticket:String,captureId:String):Map<String,Any?> = call {
    guard.captureState(NCPlaybackGuard.CaptureAttachment(ticket,session,captureId))
  }
  fun detachCapture(session:String,ticket:String,captureId:String):Boolean = call {
    val attachment=captureAttachments[session]?.takeIf{it.ticket==ticket&&it.captureId==captureId}?:return@call false
    if(policy.currentSessionId==session||policy.outputSessionId==session)stopOwned(session)
    val detached=guard.detachCapture(attachment)
    if(activeAttachment==attachment)activeAttachment=null
    detached||!guard.isOpen(ticket)
  }
  private fun armCapture(ticket:String,session:String):Boolean =
    captureAttachments[session]?.let{it.ticket==ticket&&guard.captureCurrent(it)}?:guard.arm(ticket,session)

  // Manual replies use the same media service without owning a microphone.
  // A controller belongs to one output ticket, so late cleanup cannot stop its successor.
  private inner class ReplyPlaybackOwner(val ticket: String) : LiveAudioService.Controller {
    private var serviceGeneration:Long?=null
    override fun serviceStarted(ticket:String?,generation:Long) {
      if(ticket!=this.ticket)return
      if(!guard.confirmReplyPlayback(this.ticket,generation)) {stop(false);return}
      serviceGeneration=generation
    }
    fun stop(retire: Boolean) {
      serviceGeneration?.let{guard.releaseReplyPlayback(ticket,it)};serviceGeneration=null
      if (retire) guard.retire(ticket, NCPlaybackGuard.RetirementCause.INTERRUPTION)
      LiveAudioService.stop(context, this)
    }
    override fun stopConversation() = stop(true)
    override fun authorizationExpired() = stop(true)
    override fun serviceDestroyed() = stop(true)
    override fun serviceStartFailed(ticket: String?, generation: Long) = stop(true)
    override fun safetyTick() { if (!guard.isOpen(ticket)) stop(false) }
  }
  private var replyPlaybackOwner: ReplyPlaybackOwner? = null

  fun setReplyPlaybackActive(ticket: String, active: Boolean) = call {
    if (!active) {
      replyPlaybackOwner?.takeIf { it.ticket == ticket }?.let { it.stop(false); replyPlaybackOwner = null }
    } else {
      val state = guard.outputState()
      if (closed || !state.open || state.ticket != ticket) fail(CaptureFailure.INTERRUPTED)
      // Protected Live already owns its service, including its retained reply tail.
      if (state.sessionId == null && replyPlaybackOwner?.ticket != ticket) {
        if (!foreground()) fail(CaptureFailure.INTERRUPTED)
        replyPlaybackOwner?.stop(false)
        val owner = ReplyPlaybackOwner(ticket)
        replyPlaybackOwner = owner
        try { LiveAudioService.startOutput(context, owner, ticket) }
        catch (error: Throwable) { owner.stop(true); replyPlaybackOwner = null; throw error }
      }
    }
  }

  fun beginForegroundOutput(expected: String?): String = call {
    try { guard.beginForegroundOutput(expected) } catch (error: Throwable) { throw CapturePolicyException(CaptureFailure.START_FAILED, error) }
  }

  fun retireOutput(ticket: String) = call {
    guard.retire(ticket)
    replyPlaybackOwner?.takeIf { it.ticket == ticket }?.let { it.stop(false); replyPlaybackOwner = null }
    if (ticket == protectedTicket) { cancelRecovery(); policy.endForSystemEvent(CaptureFailure.INTERRUPTED, policy.driverIdentity) }
  }

  fun setSpeechSensitivity(level: Int) = call { segmenter.setSensitivity(level) }

  fun start(session: String) = call {
    if (closed || !foreground()) fail(CaptureFailure.INTERRUPTED)
    eventSession = session; sequence = 0; outstandingState = null; pendingState = null; segmenter.reset(); playbackActive = false
    inputEpoch = 0
    recovery = ConnectionRecoveryClock()
    val lease = NativeCommunicationLease(context, protectedTicket, ::enqueueRouteInvalidation, policy.independentCapture, routeHandler)
    val candidate = NativeCaptureDriver(context, lease, ::enqueueSamples, ::enqueueInvalidation, routeHandler)
    captureWork = "capture_start" to SystemClock.elapsedRealtime()
    try {
      store.cleanup()
      activeDriver = candidate
      policy.start(session) { candidate }
      protectedTicket?.let { if (!guard.isOpen(it)) throw CapturePolicyException(CaptureFailure.INTERRUPTED) }
      LiveAudioService.start(context, captureController, false, protectedTicket)
      state("listening", 0.0, null)
    } catch (error: Throwable) {
      val cleanup = try { policy.stop(session); null } catch (stopError: Throwable) { stopError }
      if (cleanup == null) activeDriver = null
      val reported = cleanup ?: error
      publish("error", "off", error = failureOf(reported).wireValue)
      throw reported
    } finally { captureWork = "steady" to 0L }
  }

  fun stop(session: String) = call { stopOwned(session) }
  fun pauseReplyContinuation(session: String, ticket: String, epoch: Long): Map<String, Any>? = call {
    if (!connectionOwnerValid(session, ticket)) return@call null
    val checkpoint = guard.pauseReplyContinuation(ticket, session, epoch) ?: return@call null
    if (!pauseConnection(session, ticket, epoch)) { guard.retire(ticket); return@call null }
    checkpoint.payload()
  }
  fun resumeReplyContinuation(session: String, ticket: String, epoch: Long, requestIds: List<String>): CompletableFuture<Boolean> {
    val allowed = call { connectionOwnerValid(session, ticket) && guard.prepareReplyContinuation(ticket, session, epoch, requestIds) }
    return if (allowed) resumeConnection(session, ticket, epoch) else CompletableFuture.completedFuture(false)
  }

  fun pauseConnection(session: String, ticket: String, epoch: Long): Boolean = call {
    if (!connectionOwnerValid(session, ticket) || !policy.pauseConnection(session, ticket, epoch)) return@call false
    if (!guard.pauseConnection(ticket, session, epoch)) { systemStop(CaptureFailure.INTERRUPTED); return@call false }
    if (recovery.epoch == epoch) return@call true
    cancelRecovery()
    inputEpoch = epoch
    recovery.pause(epoch, SystemClock.elapsedRealtime())
    segmenter.reset(); onsetFence.clear(); playbackActive = false
    try { store.stop(session) } catch (_: Throwable) { systemStop(CaptureFailure.FILE_FAILED); return@call false }
    state("listening", 0.0, null)
    recoveryTick(session, ticket, epoch)
    policy.canResumeConnection(session, ticket, epoch)
  }

  // Completion stays asynchronous, leaving both Expo and the capture owner free
  // to process Stop/expiry while the resumed cue and echo tail finish.
  fun resumeConnection(session: String, ticket: String, epoch: Long): CompletableFuture<Boolean> {
    val result = call {
      if (!connectionOwnerValid(session, ticket) || !policy.canResumeConnection(session, ticket, epoch))
        return@call CompletableFuture.completedFuture(false)
      resumeResult?.let { return@call it }
      val pending = CompletableFuture<Boolean>()
      resumeResult = pending
      recoveryCallback?.let { mainHandler.removeCallbacks(it) }; recoveryCallback = null
      try {
        recoveryCue.play(true, session, ticket, epoch)
        if (!recovery.resume(epoch, SystemClock.elapsedRealtime())) { cancelRecovery(); return@call pending }
        scheduleRecovery(ConnectionRecoveryClock.RESUME_SUPPRESSION_MS) {
          if (!connectionOwnerValid(session, ticket) || !policy.canResumeConnection(session, ticket, epoch)) {
            cancelRecovery(); return@scheduleRecovery
          }
          recoveryCue.stop()
          segmenter.reset(); onsetFence.clear()
          // The first fresh read after this flush completes the promise below.
          activeDriver?.discardBufferedInput(epoch)
          scheduleRecovery(1_500) {
            if (resumeResult === pending) {
              recordCaptureFailure("recovery_timeout")
              systemStop(CaptureFailure.CAPTURE_OVERFLOW)
            }
          }
        }
      } catch (_: Throwable) { systemStop(CaptureFailure.INTERRUPTED) }
      pending
    }
    return result
  }

  private fun connectionOwnerValid(session: String, ticket: String): Boolean {
    val driver = policy.driverIdentity as? NativeCaptureDriver ?: return false
    return !closed && !cleanupSupervisor.pending && policy.ownsConnection(session, ticket) && guard.isOpen(ticket) &&
      (foreground() || policy.permitsBackground(driver.routeKey)) && driver.routeLease.valid() &&
      routeKeyMatches(driver.routeKey, driver.snapshot().key) &&
      ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
  }

  private fun recoveryTick(session: String, ticket: String, epoch: Long) {
    if (recovery.epoch != epoch || !policy.connectionPaused || resumeResult != null) return
    if (!connectionOwnerValid(session, ticket)) { systemStop(CaptureFailure.INTERRUPTED); return }
    try {
      if (recovery.takeWaitingCue(SystemClock.elapsedRealtime())) recoveryCue.play(false, session, ticket, epoch)
      scheduleRecovery(5_000) { recoveryTick(session, ticket, epoch) }
    } catch (_: Throwable) { systemStop(CaptureFailure.INTERRUPTED) }
  }

  private fun scheduleRecovery(delay: Long, action: () -> Unit) {
    lateinit var callback: Runnable
    callback = Runnable {
      try { executor.executeControl {
        if (recoveryCallback === callback) { recoveryCallback = null; action() }
      } }
      catch (_: RejectedExecutionException) {
        recordCaptureFailure("recovery_control_rejected")
        enqueueSystemStop(CaptureFailure.CAPTURE_OVERFLOW)
      }
    }
    recoveryCallback = callback
    mainHandler.postDelayed(callback, delay)
  }

  private fun cancelRecovery() {
    recoveryCallback?.let { mainHandler.removeCallbacks(it) }; recoveryCallback = null
    recovery.cancel(); recoveryCue.stop()
    resumeResult?.complete(false); resumeResult = null
  }

  fun stopListening(session: String, requests: List<String>, pending: List<String>) = call {
    val independent=captureAttachments.containsKey(session)
    if(independent&&policy.currentSessionId!=session&&policy.outputSessionId!=session){
      // Native input failure may already have drained/detached this driver.
      // Seal its accepted work without consulting or stopping replacement input.
      val attachment=captureAttachments.getValue(session)
      if(guard.sealReplyTail(attachment.ticket,session,requests,pending)==null)fail(CaptureFailure.REPLY_TAIL_UNAVAILABLE)
      return@call
    }
    if (policy.currentSessionId == session) cancelRecovery()
    val current = activeDriver
    val snapshot = try { policy.stopListening(session, requests, pending) }
    catch (error: Throwable) {
      if (policy.driverIdentity === current) activeDriver = current
      retainFailedCleanup((error as? CapturePolicyException)?.failure ?: CaptureFailure.RELEASE_FAILED, serviceVisible = true)
      throw error
    }
    if (policy.driverIdentity == null) activeDriver = null
    if (!independent && snapshot.lifetime == CaptureLifetime.REPLY_TAIL &&
      !LiveAudioService.setOutputActive(context, captureController, playbackActive, protectedTicket, snapshot.lifetime)) {
      systemStop(CaptureFailure.INTERRUPTED, serviceVisible = false)
      fail(CaptureFailure.INTERRUPTED)
    }
    try { store.stop(session) } catch (error: UtteranceStoreException) {
      cleanupSessionId = session
      retainFailedCleanup(error.failure, serviceVisible = true)
      throw error
    }
    if (independent || snapshot.lifetime == CaptureLifetime.CLOSED) LiveAudioService.stop(context, captureController)
    if(independent&&activeAttachment?.sessionId==session)activeAttachment=null
    state("off", 0.0, null)
  }

  fun registerSubmittedUpload(session: String, utterance: String, upload: String): Boolean = call {
    if (leases[session to utterance] != inputEpoch) false
    else policy.outputTicket?.let { policy.registerSubmittedUpload(session, it, utterance, upload) } ?: false
  }

  fun registerSubmittedTurn(session: String, ticket: String, submission: String, kind: String): Boolean = call {
    policy.registerSubmittedTurn(session, ticket, submission, kind)
  }

  fun admitForegroundReply(ticket:String,request:String)=guard.admitForegroundReply(ticket,request)
  fun admitReply(session: String, ticket: String, upload: String, request: String): Boolean = call {
    if (!guard.admitReplyForUpload(ticket, session, upload, request)) false else { policy.abandonSubmission(session, ticket, upload); true }
  }

  fun abandonUpload(session: String, ticket: String, upload: String) = call {
    if (policy.abandonSubmission(session, ticket, upload)||captureAttachments[session]?.ticket==ticket) guard.abandonSubmittedUpload(ticket, session, upload)
  }

  fun finishReply(session: String, ticket: String, completed: List<String>) = call {
    if (!guard.finishReplyTail(ticket, session, completed)) fail(CaptureFailure.REPLY_TAIL_UNAVAILABLE)
    if(captureAttachments[session]?.ticket!=ticket)stopOwned(session)
  }

  fun armBackground(session: String, bluetoothConfirmed: Boolean): Boolean = call {
    val driver = policy.driverIdentity as? NativeCaptureDriver ?: return@call false
    captureWork = "background_arm" to SystemClock.elapsedRealtime()
    try { BackgroundAdmission(policy).arm(session, bluetoothConfirmed, foreground,
      bind = {
        if (bluetoothConfirmed) driver.bindConfirmedBluetoothDuplex() ?: driver.bindWiredDuplex()
        else driver.bindWiredDuplex()
      },
      armOutput = { ticket, requested -> armCapture(ticket, requested) },
      startService = { LiveAudioService.start(context, captureController, false, protectedTicket) },
      failClose = { systemStop(CaptureFailure.INTERRUPTED) }).also { if (it) driver.admitInput() }
    } finally { captureWork = "steady" to 0L }
  }

  fun armForeground(session: String): Boolean = call {
    lastForegroundArm = null
    if (!policy.armForeground(session, foreground())) {
      recordForegroundArmFailure(session, "policy_rejected"); return@call false
    }
    val ticket = policy.outputTicket ?: run {
      recordForegroundArmFailure(session, "ticket_missing"); return@call false
    }
    var readinessStarted = false
    captureWork = "foreground_arm" to SystemClock.elapsedRealtime()
    try {
      val driver = policy.driverIdentity as? NativeCaptureDriver ?: run {
        recordForegroundArmFailure(session, "driver_missing"); return@call false
      }
      driver.bindForegroundDuplex()
      readinessStarted = true
      if (!driver.foregroundRouteReady()) {
        recordForegroundArmFailure(session, "route_unsettled", includeReadiness = true)
        systemStop(CaptureFailure.INTERRUPTED); return@call false
      }
      // A Bluetooth selection can yield to Android; recheck visibility before
      // arming output. Input stays foreground-only after a recovery.
      val visible = foreground()
      if (!visible || !armCapture(ticket, session)) {
        recordForegroundArmFailure(session, if (!visible) "foreground_lost" else "guard_rejected", includeReadiness = true)
        systemStop(CaptureFailure.INTERRUPTED); false
      } else if (!driver.foregroundRouteReady()) {
        // Close the selection/arm race: a deferred unplug must not be admitted.
        recordForegroundArmFailure(session, "route_unsettled", includeReadiness = true)
        systemStop(CaptureFailure.INTERRUPTED); false
      } else { driver.admitInput(); true }
    } catch (error: Throwable) {
      recordForegroundArmFailure(session, "route_exception", error, includeReadiness = readinessStarted)
      systemStop(CaptureFailure.INTERRUPTED); false
    } finally { captureWork = "steady" to 0L }
  }

  private fun recordForegroundArmFailure(session: String, reason: String, error: Throwable? = null, includeReadiness: Boolean = false) {
    // Snapshot before cleanup destroys the rejected state. No IDs, addresses,
    // exception text, device names or per-frame work cross this diagnostic boundary.
    try {
      val state = guard.outputState()
      val route = runCatching { (policy.driverIdentity as? NativeCaptureDriver)?.snapshot() }.getOrNull()
      (policy.driverIdentity as? NativeCaptureDriver)?.recordRouteEvidence("failed", route)
      lastForegroundArm = mapOf("reason" to reason, "foreground" to foreground(),
        "policy_session_matches" to (policy.currentSessionId == session),
        "driver_present" to (policy.driverIdentity != null),
        "guard_ticket_matches" to (state.ticket == policy.outputTicket),
        "guard_session_matches" to (state.sessionId == session),
        "guard_open" to state.open, "guard_armed" to state.armed,
        "retirement_cause" to state.lastRetirementCause,
        "input_route" to (route?.input ?: "unavailable"), "output_route" to (route?.output ?: "unavailable"),
        "exception_type" to when (error) {
          null -> "none"; is SecurityException -> "SecurityException"
          is IllegalStateException -> "IllegalStateException"
          is IllegalArgumentException -> "IllegalArgumentException"; else -> "other"
        }) + (if (includeReadiness) (policy.driverIdentity as? NativeCaptureDriver)?.foregroundReadinessEvidence ?: emptyMap() else emptyMap())
    } catch (_: Throwable) { /* Diagnostics must not alter admission or cleanup. */ }
  }

  fun disarmBackground(session: String) = call {
    policy.disarmBackground(session)
    if (!foreground()) systemStop(CaptureFailure.INTERRUPTED)
  }

  fun setPlaybackActive(session: String, active: Boolean) = call {
    if (policy.currentSessionId == session && !policy.connectionPaused) {
      playbackActive = active
      LiveAudioService.setOutputActive(context, captureController, active, protectedTicket, policy.lifetime)
    }
  }

  fun acquire(session: String, utterance: String): Map<String, Any> = call {
    val clip = store.acquire(session, utterance); leases[session to utterance] = inputEpoch
    mapOf("sessionId" to clip.sessionId, "utteranceId" to clip.utteranceId, "uri" to clip.uri,
      "byteLength" to clip.byteLength, "durationMs" to clip.durationMs)
  }
  fun release(session: String, utterance: String) = call {
    try { store.release(session, utterance) } finally { leases -= session to utterance }
  }
  fun acknowledgeState(session: String, acknowledged: Int) = call {
    if (eventSession == session && outstandingState == acknowledged) { outstandingState = null; flushState() }
  }

  fun activityBackgrounded() = submitLatched(backgroundAdmissionPending) {
    if (foreground() || policy.lifetime == CaptureLifetime.REPLY_TAIL) return@submitLatched
    val driver = policy.driverIdentity as? NativeCaptureDriver
    if (driver != null && policy.permitsBackground(driver.routeKey)) return@submitLatched
    if(activeAttachment!=null) {
      policy.currentSessionId?.let{stopOwned(it)}
      return@submitLatched
    }
    val session = policy.currentSessionId
    val ticket = policy.outputTicket
    val permit = if (session != null && ticket != null) guard.currentReplyTailPermit(ticket, session) else null
    if (session != null && permit != null) {
      // Reuse Live-off: stop/drain only capture and retain exactly the admitted
      // reply/pending uploads. Switching apps never grants background mic access.
      try { stopListening(session, permit.first, permit.second) }
      catch (_: Throwable) { systemStop(CaptureFailure.INTERRUPTED) }
    } else if (driver != null || policy.foregroundOnly) systemStop(CaptureFailure.INTERRUPTED)
  }

  fun destroy() {
    recoveryCue.stop()
    if (executor.isShutdown) return
    submitLatched(destroyAdmissionPending) {
      closed = true
      NCSoundscapeActivity.remove(soundscapeOwner)
      soundscapeLease?.let { LiveAudioService.releaseSoundscape(context,it) }; soundscapeLease=null
      replyPlaybackOwner?.stop(true); replyPlaybackOwner = null
      cancelRecovery()
      cleanupSupervisor.requestDestroy()
      if (cleanupSupervisor.pending) attemptSupervisedCleanup()
      else if (policy.currentSessionId == null && policy.outputSessionId == null) finalizeDestroy()
      else {
        protectedTicket?.let { guard.retire(it, NCPlaybackGuard.RetirementCause.INTERRUPTION) }
        LiveAudioService.markStopping(context, captureController, policy.driverIdentity != null)
        cleanupSessionId = policy.currentSessionId ?: policy.outputSessionId
        cleanupSupervisor.begin(CaptureFailure.INTERRUPTED, serviceVisible = true)
        attemptSupervisedCleanup()
      }
    }
  }

  override fun stopConversation() = retireThenEnqueue(CaptureFailure.CONVERSATION_STOPPED)
  override fun authorizationExpired() = enqueueSystemStop(CaptureFailure.BACKGROUND_SESSION_LIMIT)
  override fun serviceDestroyed() {
    recoveryCue.stop()
    submitLatched(serviceDestroyedAdmissionPending) {
      cleanupSupervisor.serviceDestroyed()
      if (cleanupSupervisor.pending) scheduleCleanupRetry()
      else systemStop(CaptureFailure.INTERRUPTED, serviceVisible = false)
    }
  }
  override fun serviceStartFailed(ticket: String?, generation: Long) {
    if (ticket == protectedTicket || (ticket == null && protectedTicket == null)) {
      if(activeAttachment==null)ticket?.let { guard.retire(it, NCPlaybackGuard.RetirementCause.OTHER) }
      enqueueSystemStop(CaptureFailure.START_FAILED, serviceVisible = false)
    }
  }
  override fun safetyTick() {
    val observedAttachment=activeAttachment
    try { executor.executeControl {
      if(activeAttachment!=observedAttachment)return@executeControl
      if (cleanupSupervisor.pending) { scheduleCleanupRetry(); return@executeControl }
      val ticket = protectedTicket
      if (ticket != null && !guard.isOpen(ticket)) systemStop(CaptureFailure.INTERRUPTED)
      val driver = policy.driverIdentity as? NativeCaptureDriver
      val route = policy.routeIdentity as? NativeCommunicationLease
      // An independent avatar is already armed while its microphone is still
      // selecting a route. Match routeChanged(): arm validates initial routing;
      // ongoing route-loss enforcement starts only after input admission.
      if ((driver == null || driver.inputRouteAdmitted) && ((route != null && !route.valid()) ||
        (driver != null && !routeKeyMatches(driver.routeKey, driver.snapshot().key)))) {
        if (ticket == null || !guard.retireForRouteChange(ticket)) systemStop(CaptureFailure.ROUTE_CHANGED)
      }
      if (driver != null && ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
        systemStop(CaptureFailure.PERMISSION_DENIED)
    } } catch (_: RejectedExecutionException) { /* A later 250 ms safety tick retries actionably. */ }
  }

  private fun recordCaptureFailure(origin: String, capturedAt: Long? = null) { try {
    val work = captureWork
    val now = SystemClock.elapsedRealtime()
    val evidence = mutableMapOf<String, Number>("queue_depth" to executor.audioQueued,
      "queue_capacity" to executor.audioLimit, "drop_count" to executor.audioDrops, "evicted_count" to executor.audioEvictions,
      "phase_elapsed_ms" to if (work.second > 0) (now - work.second).coerceAtLeast(0) else 0L)
    capturedAt?.let { evidence["buffer_age_ms"] = (now - it).coerceAtLeast(0) }
    captureEvidence.captureFailure(origin, work.first, evidence)
  } catch (_: Throwable) { /* Evidence never changes capture admission or cleanup. */ } }

  private fun enqueueSamples(source: NativeCaptureDriver, samples: ShortArray, capturedAt: Long, capturedEpoch: Long) {
    if (!executor.executeAudio {
      val drops = executor.audioDrops
      if (drops != observedAudioDrops) {
        val evictions = executor.audioEvictions
        if (evictions != observedAudioEvictions) {
          observedAudioEvictions = evictions
          recordCaptureFailure("queue_evicted", capturedAt)
        }
        observedAudioDrops = drops; overflow.set(true)
      }
      if (overflow.getAndSet(false)) {
        recordCaptureFailure("queue_overflow_observed", capturedAt)
        systemStop(CaptureFailure.CAPTURE_OVERFLOW); return@executeAudio
      }
      if (source !== policy.driverIdentity) return@executeAudio
      val session = policy.currentSessionId ?: return@executeAudio
      val ticket = protectedTicket
      if (ticket != null && !guard.isOpen(ticket)) { systemStop(CaptureFailure.INTERRUPTED); return@executeAudio }
      if (capturedEpoch != inputEpoch) return@executeAudio
      if (inputEpoch > 0) {
        if (!recovery.acceptsInput(capturedEpoch, capturedAt)) return@executeAudio
        if (policy.connectionPaused) {
          val pending = resumeResult ?: return@executeAudio
          if (ticket == null || !connectionOwnerValid(session, ticket) ||
            !guard.resumeConnection(ticket, session, inputEpoch) || !policy.resumeConnection(session, ticket, inputEpoch)) {
            systemStop(CaptureFailure.INTERRUPTED); return@executeAudio
          }
          recoveryCallback?.let { mainHandler.removeCallbacks(it) }; recoveryCallback = null
          resumeResult = null; pending.complete(true)
        }
      }
      try {
        for (event in segmenter.consume(samples, playbackActive)) when (event) {
          is SegmentEvent.Onset -> {
            val id = event.id.toString()
            val attachment: OnsetAttachment
            if (ticket != null) {
              val accepted = onsetFence.freeze(id, freeze = {
                when (val onset = guard.freezeCurrentPhoneReplyReceipt(ticket, session, UUID.randomUUID().toString())) {
                  is NCPhoneReplyOnset.Receipt -> OnsetAttachment(onset.value.payload(), false)
                  NCPhoneReplyOnset.Unavailable -> OnsetAttachment(unavailable = true)
                  NCPhoneReplyOnset.None -> OnsetAttachment()
                }
              }, stillOpen = { guard.isOpen(ticket) })
              if (!accepted) throw CapturePolicyException(CaptureFailure.INTERRUPTED)
              attachment = onsetFence.peek(id) ?: OnsetAttachment()
            } else {
              onsetFence.clear()
              attachment = OnsetAttachment()
            }
            publish("onset", "speech", id, segmenter.durationMs, segmenter.meteringDb,
              receipt = attachment.receipt, unavailable = attachment.unavailable)
          }
          is SegmentEvent.Completed -> {
            val id = event.id.toString()
            val clip = CompletedClipFence.persist(sourceIsCurrent = { source === policy.driverIdentity },
              takeOverflow = { overflow.getAndSet(false) }, write = { store.write(session, id, event.samples) },
              discard = { try { store.release(session, id) } catch (_: Throwable) {} })
            val fallback = onsetFence.takeForCompletion(id)
            publish("utterance", segmenter.phase, id, clip.durationMs, segmenter.meteringDb,
              receipt = fallback?.receipt, unavailable = fallback?.unavailable == true)
          }
        }
        state(segmenter.phase, segmenter.durationMs, segmenter.meteringDb)
      } catch (error: UtteranceStoreException) { systemStop(error.failure) }
      catch (error: CapturePolicyException) {
        if (error.failure == CaptureFailure.CAPTURE_OVERFLOW) recordCaptureFailure("clip_overflow", capturedAt)
        systemStop(error.failure)
      }
    }) {
      if (overflow.compareAndSet(false, true)) recordCaptureFailure("queue_rejected", capturedAt)
    }
  }

  private fun enqueueInvalidation(source: NativeCaptureDriver, reason: CaptureFailure) {
    if (reason == CaptureFailure.ROUTE_CHANGED) {
      // Apply a slow route observation only on its still-current serial owner.
      submitLatched(source.routeInvalidationPending) {
        if (source !== policy.driverIdentity) return@submitLatched
        val ticket = protectedTicket
        if (ticket != null && guard.retireForRouteChange(ticket)) return@submitLatched
        systemStop(reason)
      }
      return
    }
    if (source === activeDriver) protectedTicket?.let {
      if (reason == CaptureFailure.ROUTE_CHANGED && guard.retireForRouteChange(it)) return
      if(activeAttachment==null||reason==CaptureFailure.ROUTE_CHANGED)guard.retire(it, retirementCause(reason))
    }
    try { executor.executeControl { if (source === policy.driverIdentity) systemStop(reason) } }
    catch (_: RejectedExecutionException) { enqueueSystemStop(reason) }
  }
  private fun enqueueRouteInvalidation(source: NativeCommunicationLease) {
    // Recheck identity on admission and execution; an old queued callback cannot stop a new session.
    submitLatched(source.routeInvalidationPending) {
      if (source !== policy.routeIdentity) return@submitLatched
      val ticket = protectedTicket
      // Selecting SCO emits device changes; retain the existing negotiation guard.
      if (ticket != null && guard.retireForRouteChange(ticket)) return@submitLatched
      systemStop(CaptureFailure.ROUTE_CHANGED)
    }
  }
  private fun retireThenEnqueue(reason: CaptureFailure) {
    recoveryCue.stop()
    protectedTicket?.let { guard.retire(it, retirementCause(reason)) }
    LiveAudioService.markStopping(context, captureController, activeDriver != null)
    enqueueSystemStop(reason, serviceVisible = true)
  }
  private fun enqueueSystemStop(reason: CaptureFailure, serviceVisible: Boolean = true) {
    if (executor.isShutdown) return
    synchronized(pendingStopLock) {
      val current = pendingStop
      pendingStop = if (current == null) reason to serviceVisible else current.first to (current.second || serviceVisible)
    }
    submitLatched(stopAdmissionPending) {
      val request = synchronized(pendingStopLock) { pendingStop.also { pendingStop = null } }
      request?.let { systemStop(it.first, it.second) }
    }
  }
  private fun systemStop(reason: CaptureFailure, serviceVisible: Boolean = true) {
    cancelRecovery()
    if (cleanupSupervisor.pending) {
      if (!serviceVisible) cleanupSupervisor.serviceDestroyed()
      scheduleCleanupRetry()
      return
    }
    val session = policy.currentSessionId ?: policy.outputSessionId ?: return
    if(!policy.independentCapture)protectedTicket?.let { guard.retire(it, retirementCause(reason)) }
    (policy.driverIdentity as? NativeCaptureDriver)?.recordInputFailure()
    if (serviceVisible) LiveAudioService.markStopping(context, captureController, policy.driverIdentity != null)
    cleanupSessionId = session
    cleanupSupervisor.begin(reason, serviceVisible)
    attemptSupervisedCleanup(session)
  }
  private fun stopOwned(session: String) {
    if (policy.currentSessionId != session && policy.outputSessionId != session) return
    cancelRecovery()
    LiveAudioService.markStopping(context, captureController, policy.driverIdentity != null)
    val current = activeDriver
    try { policy.stop(session); activeDriver = null; if(activeAttachment?.sessionId==session)activeAttachment=null;store.stop(session); cleanupSessionId = null }
    catch (error: CapturePolicyException) {
      if (policy.driverIdentity === current) activeDriver = current
      cleanupSessionId = session
      retainFailedCleanup(error.failure, serviceVisible = true)
      throw error
    }
    catch (error: UtteranceStoreException) {
      cleanupSessionId = session
      retainFailedCleanup(error.failure, serviceVisible = true)
      throw CapturePolicyException(error.failure, error)
    }
    segmenter.reset(); onsetFence.clear(); playbackActive = false; LiveAudioService.stop(context, captureController)
    state("off", 0.0, null)
  }

  private fun retainFailedCleanup(reason: CaptureFailure, serviceVisible: Boolean) {
    cancelRecovery()
    if (cleanupSessionId == null) cleanupSessionId = policy.currentSessionId ?: policy.outputSessionId
    if(!policy.independentCapture)protectedTicket?.let { guard.retire(it, retirementCause(reason)) }
    cleanupSupervisor.begin(reason, serviceVisible)
    if (cleanupSupervisor.retainsVisibleService) LiveAudioService.markStopping(context, captureController, policy.driverIdentity != null)
    if (!cleanupFailurePublished) {
      cleanupFailurePublished = true
      publish("error", "off", error = CaptureFailure.RELEASE_FAILED.wireValue)
    }
    scheduleCleanupRetry()
  }

  private fun attemptSupervisedCleanup(sessionHint: String? = null) {
    val reason = cleanupSupervisor.pendingReason ?: return
    val session = sessionHint ?: cleanupSessionId ?: policy.currentSessionId ?: policy.outputSessionId
    val disposition = cleanupSupervisor.attempt {
      if (session != null) {
        policy.endForSystemEvent(reason, policy.driverIdentity)
        store.stop(session)
      }
    }
    when (disposition) {
      CleanupDisposition.COMPLETE -> {
        activeDriver = null
        if(activeAttachment?.sessionId==session)activeAttachment=null
        cleanupSessionId = null
        cleanupFailurePublished = false
        segmenter.reset(); onsetFence.clear(); playbackActive = false
        LiveAudioService.stop(context, captureController)
        publish("error", "off", error = reason.wireValue)
        if (cleanupSupervisor.mayShutdown) finalizeDestroy()
      }
      CleanupDisposition.RETRY_VISIBLE, CleanupDisposition.RETRY_HIDDEN -> {
        activeDriver = policy.driverIdentity as? NativeCaptureDriver
        retainFailedCleanup(reason, disposition == CleanupDisposition.RETRY_VISIBLE)
      }
    }
  }

  private fun scheduleCleanupRetry() {
    if (!cleanupSupervisor.pending || executor.isShutdown || !cleanupRetryScheduled.compareAndSet(false, true)) return
    mainHandler.postDelayed({
      if (executor.isShutdown) { cleanupRetryScheduled.set(false); return@postDelayed }
      try { executor.executeControl {
          cleanupRetryScheduled.set(false)
          if (cleanupSupervisor.pending) attemptSupervisedCleanup()
        }
      } catch (_: RejectedExecutionException) {
        cleanupRetryScheduled.set(false)
        scheduleCleanupRetry()
      }
    }, 250)
  }

  private fun finalizeDestroy() {
    if (cleanupSupervisor.pending || policy.currentSessionId != null || policy.outputSessionId != null) return
    mainHandler.removeCallbacksAndMessages(null)
    routeHandler.removeCallbacksAndMessages(null)
    routeThread.quitSafely()
    cleanupRetryScheduled.set(false)
    LiveAudioService.stop(context, captureController)
    leases.keys.forEach { try { store.release(it.first, it.second) } catch (_: Throwable) {} }
    leases.clear(); emitter = null
    executor.shutdown()
  }

  private fun submitLatched(latch: AtomicBoolean, action: () -> Unit) {
    if (executor.isShutdown || !latch.compareAndSet(false, true)) return
    admitLatched(latch, action)
  }

  private fun admitLatched(latch: AtomicBoolean, action: () -> Unit) {
    if (executor.isShutdown) { latch.set(false); return }
    try { executor.executeControl { latch.set(false); action() } }
    catch (_: RejectedExecutionException) { mainHandler.postDelayed({ admitLatched(latch, action) }, 50) }
  }

  private fun state(phase: String, duration: Double, meter: Double?) { pendingState = Triple(phase, duration, meter); flushState() }
  private fun flushState() {
    val pending = pendingState ?: return
    if (outstandingState != null) return
    pendingState = null; outstandingState = sequence + 1
    publish("state", pending.first, duration = pending.second, meter = pending.third)
  }
  private fun publish(kind: String, phase: String, utterance: String? = null, duration: Double = 0.0,
    meter: Double? = null, error: String? = null, receipt: Map<String, Any>? = null, unavailable: Boolean = false) {
    val session = eventSession ?: return
    sequence += 1
    emitter?.invoke(CaptureNotification(session, sequence, kind, phase, utterance, duration, meter, error,
      policy.eventBackgroundAuthorized, policy.lifetime.wireValue, receipt, unavailable,eventCaptureId))
  }

  private fun failureOf(error: Throwable): CaptureFailure = (error as? CapturePolicyException)?.failure ?: CaptureFailure.START_FAILED
  private fun retirementCause(reason: CaptureFailure): NCPlaybackGuard.RetirementCause = when (reason) {
    CaptureFailure.ROUTE_CHANGED -> NCPlaybackGuard.RetirementCause.ROUTE_CHANGE
    CaptureFailure.INTERRUPTED -> NCPlaybackGuard.RetirementCause.INTERRUPTION
    else -> NCPlaybackGuard.RetirementCause.OTHER
  }
  private fun fail(failure: CaptureFailure): Nothing = throw CapturePolicyException(failure)
  // Expo's shared AsyncFunction queue must not wait for Bluetooth negotiation.
  // Bridge operations execute on the same owner as synchronous native callers.
  internal fun dispatchBridge(action: () -> Unit) {
    try { executor.executeControl(action) }
    catch (error: RejectedExecutionException) {
      recordCaptureFailure("control_rejected")
      throw CapturePolicyException(CaptureFailure.CAPTURE_OVERFLOW, error)
    }
  }
  private fun <T> call(action: () -> T): T {
    if (executor.isOwnerThread) return action()
    try { return executor.submitControl(action).get() }
    catch (error: ExecutionException) { throw error.cause ?: error }
    catch (error: RejectedExecutionException) {
      recordCaptureFailure("control_rejected")
      throw CapturePolicyException(CaptureFailure.CAPTURE_OVERFLOW, error)
    }
  }
}
