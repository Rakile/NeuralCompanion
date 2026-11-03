package expo.modules.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.AudioRouting
import android.media.MediaRecorder
import android.media.MediaRecorder.MEDIA_ERROR_SERVER_DIED
import android.media.MediaRecorder.MEDIA_RECORDER_ERROR_UNKNOWN
import android.media.MediaRecorder.MEDIA_RECORDER_INFO_MAX_FILESIZE_REACHED
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import expo.modules.audio.service.AudioRecordingService
import expo.modules.kotlin.AppContext
import expo.modules.kotlin.sharedobjects.SharedObject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File
import java.io.IOException
import java.util.UUID
import kotlin.math.log10

private const val RECORDING_STATUS_UPDATE = "recordingStatusUpdate"

class AudioRecorder(
  private val context: Context,
  appContext: AppContext,
  private val options: RecordingOptions
) : SharedObject(appContext),
  MediaRecorder.OnErrorListener,
  MediaRecorder.OnInfoListener {
  var filePath: String? = null
  private var meteringEnabled = options.isMeteringEnabled
  private var durationAlreadyRecorded = 0L
  var isPrepared = false

  private var recorder: MediaRecorder? = null
  private var ncCaptureRoute: NCCaptureRoute? = null
  private var ncRecordingOptions: RecordingOptions = options
  var ncMicrophonePreparing = false
    private set
  @Volatile var ncReleased = false
    private set
  val id = UUID.randomUUID().toString()
  var startTime = 0L
  var isRecording = false
  var isPaused = false
  private var recordingTimerJob: Job? = null
  var useForegroundService = false
  private var isRegisteredWithService = false
  private val ncRouteEvidence = NCMicrophoneRouteEvidence("manual")
  private val ncRouteListener = AudioRouting.OnRoutingChangedListener { source ->
    if (source === recorder && isRecording) ncRecordRoute("route_changed")
  }

  private fun ncRecordRoute(reason: String) {
    try {
      // Unlike getCurrentInput(), never substitute a preferred or built-in mic.
      // This recorder does not observe media playback output: leave it unavailable.
      ncRouteEvidence.observe(reason, if (isRecording || reason == "failed") recorder?.routedDevice?.type else null,
        recorder?.preferredDevice?.type ?: ncCaptureRoute?.token?.deviceType)
    } catch (_: Throwable) { ncRouteEvidence.observe(reason, null, null) }
  }

  private fun currentFileUrl(): String? =
    filePath?.let(::File)?.toUri()?.toString()

  private fun getAudioRecorderLevels(): Double? {
    if (!meteringEnabled || recorder == null || !isRecording) {
      return null
    }

    val amplitude: Int = try {
      recorder?.maxAmplitude ?: 0
    } catch (e: Exception) {
      // MediaRecorder maxAmplitude can throw various exceptions:
      // - IllegalStateException: invalid recorder state/race condition
      // - RuntimeException: getMaxAmplitude failed (hardware/driver issues)
      // We return 0 (silence) as fallback for any amplitude reading failure
      0
    }
    return if (amplitude == 0) {
      -160.0
    } else {
      20 * log10(amplitude.toDouble() / 32767.0)
    }
  }

  fun prepareRecording(options: RecordingOptions?) {
    if (recorder != null || isPrepared || isRecording || isPaused) {
      throw AudioRecorderAlreadyPreparedException()
    }
    val recordingOptions = options ?: this.options
    ncRecordingOptions = recordingOptions
    prepareMediaRecorder(recordingOptions)
  }

  fun ncBeginMicrophonePreparation(): NCCaptureRoute {
    check(!ncReleased && ncCaptureRoute == null) { "manual_capture_route_unavailable" }
    val ticket = NCPlaybackGuard.shared.currentTicket()
    val route = NCCaptureRoute(context.getSystemService(AudioManager::class.java),
      ticket ?: "manual-$id") {
      ContextCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED
    }.also { selection ->
      if (context.packageName == "com.neuralcompanion.mainchatremote.dev")
        selection.enableForegroundRetention { ticket != null && NCPlaybackGuard.shared.isOpen(ticket) }
    }
    ncCaptureRoute = route
    ncMicrophonePreparing = true
    return route
  }

  private fun prepareMediaRecorder(recordingOptions: RecordingOptions) {
    val mediaRecorder = createRecorder(recordingOptions)
    recorder = mediaRecorder
    try {
      mediaRecorder.prepare()
      isPrepared = true
      if (Build.VERSION.SDK_INT >= 28) runCatching {
        mediaRecorder.addOnRoutingChangedListener(ncRouteListener, Handler(Looper.getMainLooper()))
      }
    } catch (cause: Exception) {
      ncRecordRoute("failed")
      mediaRecorder.release()
      recorder = null
      isPrepared = false
      throw AudioRecorderPrepareException(cause)
    }
  }

  fun ncActualMicrophone(): Int? = recorder?.routedDevice?.type

  fun ncUsePreparedMicrophone() {
    if (ncCaptureRoute?.token == null) return
    check(!ncReleased && !isRecording) { "manual_capture_route_unavailable" }
    val unusedPath=filePath
    if (Build.VERSION.SDK_INT >= 28) recorder?.removeOnRoutingChangedListener(ncRouteListener)
    recorder?.release();recorder=null;isPrepared=false
    unusedPath?.let { File(it).delete() }
    prepareMediaRecorder(ncRecordingOptions)
  }

  fun ncDiscardPreparationAudio() {
    if (ncCaptureRoute?.token == null) return
    // MediaRecorder exposes the routed input only while running. The first
    // file is a routing probe, never a user utterance or an upload candidate.
    val probePath = filePath
    try {
      // A route can settle before the encoder emits its first packet. There is
      // no clip to finalize here; release is the cleanup confirmation.
      try { recorder?.stop() } catch (_: RuntimeException) {}
    } finally {
      if (Build.VERSION.SDK_INT >= 28) recorder?.removeOnRoutingChangedListener(ncRouteListener)
      recorder?.release(); recorder = null
      isRecording = false; isPaused = false; isPrepared = false
      durationAlreadyRecorded = 0; startTime = 0L
      probePath?.let { File(it).delete() }
    }
    prepareMediaRecorder(ncRecordingOptions)
    record()
  }

  fun ncFinishMicrophonePreparation() {
    ncCaptureRoute?.finishPreparation()
    ncMicrophonePreparing = false
    ncRecordRoute("bind_accepted")
  }

  fun record() {
    try {
    if (isPaused) {
      recorder?.resume()
    } else {
      recorder?.start()
    }
    } catch (error: Exception) { ncRecordRoute("failed"); throw error }
    startTime = System.currentTimeMillis()
    isRecording = true
    isPaused = false
    ncRecordRoute("started")

    if (useForegroundService && !isRegisteredWithService) {
      AudioRecordingService.startService(context, this)
      isRegisteredWithService = true
    }
  }

  fun recordWithOptions(atTimeSeconds: Double? = null, forDurationSeconds: Double? = null) {
    recordingTimerJob?.cancel()

    // Note: atTime is not supported on Android (no native equivalent), so we ignore it entirely
    // Only forDuration is implemented using coroutines

    forDurationSeconds?.let {
      record()
      recordingTimerJob = appContext?.mainQueue?.launch {
        delay((it * 1000).toLong())
        // Stop recording regardless of current state
        // This matches the iOS behaviour where the timer continues regardless of if
        // the recording was paused.
        if (isRecording || isPaused) {
          stopRecording()
        }
      }
    } ?: record()
  }

  // Keep backward compatibility methods
  fun recordForDuration(seconds: Double) {
    recordWithOptions(forDurationSeconds = seconds)
  }

  fun startRecordingAtTime(seconds: Double) {
    recordWithOptions(atTimeSeconds = seconds)
  }

  fun pauseRecording() {
    recorder?.pause()
    durationAlreadyRecorded = getAudioRecorderDurationMillis()
    isRecording = false
    isPaused = true
  }

  fun stopRecording(): Bundle {
    val url = currentFileUrl()
    var durationMillis: Long

    if (useForegroundService && isRegisteredWithService) {
      AudioRecordingService.getInstance()?.unregisterRecorder(this)
      isRegisteredWithService = false
    }

    try {
      if (isRecording || isPaused) {
        try { recorder?.stop() } catch (error: RuntimeException) {
          // Unaccepted startup/probe audio is discarded. Release below still
          // must succeed; real user-recording finalization failures propagate.
          if (!ncMicrophonePreparing) throw error
        }
      }
      durationMillis = getAudioRecorderDurationMillis()
    } finally {
      reset()
    }

    val status = Bundle().apply {
      putBoolean("canRecord", false)
      putBoolean("isRecording", false)
      putLong("durationMillis", durationMillis)
      url?.let { putString("url", it) }
    }

    // Emit completion event on the main thread
    appContext?.mainQueue?.launch {
      emit(
        RECORDING_STATUS_UPDATE,
        mapOf(
          "id" to id,
          "isFinished" to true,
          "hasError" to false,
          "error" to null,
          "url" to url
        )
      )
    }

    return status
  }

  private fun reset() {
    recordingTimerJob?.cancel()
    recordingTimerJob = null

    if (Build.VERSION.SDK_INT >= 28) runCatching { recorder?.removeOnRoutingChangedListener(ncRouteListener) }
    recorder?.release()
    recorder = null
    isRecording = false
    isPaused = false
    durationAlreadyRecorded = 0
    startTime = 0L
    isPrepared = false
    ncCaptureRoute?.release()
    ncCaptureRoute = null
    ncMicrophonePreparing = false
  }

  private fun createRecorder(options: RecordingOptions) =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
      MediaRecorder(context)
    } else {
      MediaRecorder()
    }.apply {
      setRecordingOptions(this, options)
    }

  private fun setRecordingOptions(recorder: MediaRecorder, options: RecordingOptions) {
    if (!hasRecordingPermissions()) {
      return
    }
    with(recorder) {
      setAudioSource(if (ncCaptureRoute?.token != null) MediaRecorder.AudioSource.VOICE_COMMUNICATION
        else options.audioSource?.toAudioSource() ?: MediaRecorder.AudioSource.MIC)
      if (options.outputFormat != null) {
        setOutputFormat(options.outputFormat.toMediaOutputFormat())
      } else {
        setOutputFormat(MediaRecorder.OutputFormat.DEFAULT)
      }
      if (options.audioEncoder != null) {
        setAudioEncoder(options.audioEncoder.toMediaEncoding())
      } else {
        setAudioEncoder(MediaRecorder.AudioEncoder.DEFAULT)
      }
      options.sampleRate?.let {
        setAudioSamplingRate(it.toInt())
      }
      options.numberOfChannels?.let {
        setAudioChannels(it.toInt())
      }
      options.bitRate?.let {
        setAudioEncodingBitRate(it.toInt())
      }
      options.maxFileSize?.let {
        setMaxFileSize(it.toLong())
      }

      val filename = "recording-${UUID.randomUUID()}${options.extension}"
      try {
        val directory = File(context.cacheDir, "Audio")
        ensureDirExists(directory)
        val file = File(directory, filename)
        filePath = file.absolutePath
      } catch (e: IOException) {
        // This only occurs in the case that the scoped path is not in this experience's scope,
        // which is never true.
      }
      setOnErrorListener(this@AudioRecorder)
      setOnInfoListener(this@AudioRecorder)
      setOutputFile(filePath)
      isPrepared = false
    }
  }

  override fun sharedObjectDidRelease() {
    ncReleased = true
    super.sharedObjectDidRelease()
    if (useForegroundService && isRegisteredWithService) {
      AudioRecordingService.getInstance()?.unregisterRecorder(this)
      isRegisteredWithService = false
    }
    reset()
  }

  fun getAudioRecorderStatus() = if (hasRecordingPermissions()) {
    Bundle().apply {
      putBoolean("canRecord", isPrepared)
      putBoolean("isRecording", isRecording)
      putLong("durationMillis", getAudioRecorderDurationMillis())
      getAudioRecorderLevels()?.let {
        putDouble("metering", it)
      }
      currentFileUrl()?.let { putString("url", it) }
    }
  } else {
    Bundle().apply {
      putBoolean("canRecord", false)
      putBoolean("isRecording", false)
      putLong("durationMillis", 0)
      putString("url", null)
    }
  }

  private fun getAudioRecorderDurationMillis(): Long {
    var duration = durationAlreadyRecorded
    if (isRecording) {
      duration += System.currentTimeMillis() - startTime
    }
    return duration
  }

  override fun onError(mr: MediaRecorder?, what: Int, extra: Int) {
    ncRecordRoute("failed")
    val error = when (what) {
      MEDIA_RECORDER_ERROR_UNKNOWN -> "An unknown recording error occurred"
      MEDIA_ERROR_SERVER_DIED -> "The media server has crashed"
      else -> "An unknown recording error occurred"
    }
    emit(
      RECORDING_STATUS_UPDATE,
      mapOf(
        "isFinished" to true,
        "hasError" to true,
        "error" to error,
        "url" to null
      )
    )
  }

  override fun onInfo(mr: MediaRecorder?, what: Int, extra: Int) {
    when (what) {
      MEDIA_RECORDER_INFO_MAX_FILESIZE_REACHED -> {
        recorder?.stop()
        emit(
          RECORDING_STATUS_UPDATE,
          mapOf(
            "isFinished" to true,
            "hasError" to true,
            "error" to null,
            "url" to currentFileUrl()
          )
        )
      }
    }
  }

  fun getCurrentInput(audioManager: AudioManager): Bundle {
    var deviceInfo: AudioDeviceInfo? = null

    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
      throw GetAudioInputNotSupportedException()
    }

    if (isRecording) {
      try {
        // getRoutedDevice() is the most reliable way to return the actual mic input, however it
        // only returns a valid device when actively recording, and may throw otherwise.
        // https://developer.android.com/reference/android/media/MediaRecorder#getRoutedDevice()
        deviceInfo = recorder?.routedDevice
      } catch (e: java.lang.Exception) {
        // no-op
      }
    }

    // If no routed device is found try preferred device
    if (deviceInfo == null) {
      deviceInfo = recorder?.preferredDevice
    }

    if (deviceInfo == null) {
      // If no preferred device is found, set it to the first built-in input we can find
      val audioDevices = audioManager.getDevices(AudioManager.GET_DEVICES_INPUTS)
      for (availableDeviceInfo in audioDevices) {
        val type = availableDeviceInfo.type
        if (type == AudioDeviceInfo.TYPE_BUILTIN_MIC) {
          deviceInfo = availableDeviceInfo
          recorder?.preferredDevice = deviceInfo
          break
        }
      }
    }

    if (deviceInfo == null) {
      throw DeviceInfoNotFoundException()
    }

    return getMapFromDeviceInfo(deviceInfo)
  }

  private fun hasRecordingPermissions() =
    ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

  fun getAvailableInputs(audioManager: AudioManager) =
    audioManager.getDevices(AudioManager.GET_DEVICES_INPUTS).mapNotNull { deviceInfo ->
      val type = deviceInfo.type
      if (type == AudioDeviceInfo.TYPE_BUILTIN_MIC || type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || type == AudioDeviceInfo.TYPE_WIRED_HEADSET) {
        getMapFromDeviceInfo(deviceInfo)
      } else {
        null
      }
    }

  fun setInput(uid: String, audioManager: AudioManager) {
    val deviceInfo: AudioDeviceInfo? = getDeviceInfoFromUid(uid, audioManager)

    if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P) {
      throw SetAudioInputNotSupportedException()
    }

    if (deviceInfo != null && deviceInfo.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO) {
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        audioManager.setCommunicationDevice(deviceInfo)
      } else {
        audioManager.startBluetoothSco()
      }
    } else {
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        audioManager.clearCommunicationDevice()
      } else {
        audioManager.stopBluetoothSco()
      }
    }

    val success = recorder?.setPreferredDevice(deviceInfo)
    if (success == false) {
      throw PreferredInputNotFoundException()
    }
  }

  private fun getDeviceInfoFromUid(uid: String, audioManager: AudioManager): AudioDeviceInfo? {
    val id = uid.toInt()
    val audioDevices: Array<AudioDeviceInfo> = audioManager.getDevices(AudioManager.GET_DEVICES_INPUTS)
    for (device in audioDevices) {
      if (device.id == id) {
        return device
      }
    }
    return null
  }
}
