package expo.modules.audio

import android.Manifest
import android.app.Activity
import android.app.Application
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.Intent
import android.content.IntentFilter
import android.content.ContentResolver
import android.content.Context
import android.content.pm.PackageManager
import android.content.pm.ApplicationInfo
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.AudioPlaybackConfiguration
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.util.Base64
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import androidx.media3.common.C.CONTENT_TYPE_DASH
import androidx.media3.common.C.CONTENT_TYPE_HLS
import androidx.media3.common.C.CONTENT_TYPE_OTHER
import androidx.media3.common.C.CONTENT_TYPE_SS
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.util.Util
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.dash.DashMediaSource
import androidx.media3.exoplayer.hls.HlsMediaSource
import androidx.media3.exoplayer.smoothstreaming.SsMediaSource
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import expo.modules.audio.service.AudioControlsService
import expo.modules.interfaces.permissions.Permissions
import expo.modules.kotlin.Promise
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.functions.Queues
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import expo.modules.kotlin.modules.ModuleDefinitionBuilder
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.Executors
import kotlin.math.min

@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
class AudioModule : Module() {
  private val ncDiagnosticObserver=NCDiagnosticPlayerObserver()
  private lateinit var soundFiles: NCSoundscapeFiles
  private var soundscape: NCSoundscapeController? = null
  private val soundWorker = Executors.newSingleThreadExecutor()
  private lateinit var audioManager: AudioManager
  private val context: Context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()
  private val httpClient = OkHttpClient()

  private val players = ConcurrentHashMap<String, AudioPlayer>()
  private val progressivePcm = NCProgressivePcmStore()
  private val continuousRpcs=ConcurrentHashMap<AudioPlayer,NCContinuousMuxedRpc>()
  private val recorders = ConcurrentHashMap<String, AudioRecorder>()
  private val manualDeparture = NCManualDeparturePolicy()
  private var manualActivity: Activity? = null
  private var manualApplication: Application? = null
  private fun manualDeviceState(): Pair<Boolean?,Boolean?> = try {
    (context.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager).isKeyguardLocked to
      (context.getSystemService(Context.POWER_SERVICE) as PowerManager).isInteractive
  } catch (_:Exception) { null to null }
  private fun observeManualDeparture(activityStopped:Boolean, screenOff:Boolean=false) {
    val owner=manualDeparture.current() ?: return
    val (locked,interactive)=manualDeviceState()
    val reason=when {
      screenOff || locked==true || interactive==false -> NCManualDeparturePolicy.Reason.LOCKED
      activityStopped && locked==false && interactive==true -> NCManualDeparturePolicy.Reason.APP_SWITCH
      else -> NCManualDeparturePolicy.Reason.UNKNOWN
    }
    val recorder=recorders[owner.recorderId]
    val preparing=recorder?.ncMicrophonePreparing==true
    val snapshot=manualDeparture.depart(owner.recordingId,recorder?.isRecording==true,reason) {
      recorder!!.stopRecording().getString("url").takeUnless { preparing }
    } ?: return
    if(snapshot!=owner)sendEvent("ncManualDeparture",snapshot.payload())
  }
  private val manualScreenReceiver=object:BroadcastReceiver() {
    override fun onReceive(context:Context?,intent:Intent?) {
      if(intent?.action==Intent.ACTION_SCREEN_OFF) {
        NCCaptureRoute.setForeground(false)
        observeManualDeparture(false,true)
      }
    }
  }
  private val manualLifecycle=object:Application.ActivityLifecycleCallbacks {
    override fun onActivityStopped(activity:Activity) {if(activity===manualActivity)observeManualDeparture(true)}
    override fun onActivityPaused(activity:Activity) {if(activity===manualActivity)observeManualDeparture(false)}
    override fun onActivityDestroyed(activity:Activity) {
      if(activity===manualActivity) {observeManualDeparture(false);manualActivity=null}
    }
    override fun onActivityCreated(activity:Activity,state:Bundle?) {}
    override fun onActivityStarted(activity:Activity) {}
    override fun onActivityResumed(activity:Activity) {}
    override fun onActivitySaveInstanceState(activity:Activity,state:Bundle) {}
  }
  private var staysActiveInBackground = false
  private var audioEnabled = true
  private var shouldRouteThroughEarpiece = false
  private val focusLifecycle = NCAudioFocusLifecycle()
  private val orderedIdleCacheDelegate = lazy {
    val cache = requireNotNull(appContext.reactContext).cacheDir
    NCOrderedIdleCache(java.io.File(cache, "nc-ordered-idle-v1"), cache)
  }
  private val orderedIdleCache by orderedIdleCacheDelegate
  private var interruptionMode: InterruptionMode? = null
  private var allowsBackgroundRecording = false

  private var audioFocusRequest: AudioFocusRequest? = null
  private var audioFocusChangeListener: AudioManager.OnAudioFocusChangeListener? = null
  private val focusResumeHandler = Handler(Looper.getMainLooper())
  private var focusResumeTicket: String? = null
  private var focusResumeRevision = 0L
  private var permanentFocusLoss = false
  private val playbackCallback = object : AudioManager.AudioPlaybackCallback() {
    override fun onPlaybackConfigChanged(configs: MutableList<AudioPlaybackConfiguration>) {
      if (focusResumeTicket != null && permanentFocusLoss && configs.isEmpty()) scheduleFocusResume()
      if (configs.isEmpty() && soundscape?.needsFocus == true && permanentFocusLoss) {
        focusResumeHandler.postDelayed({
          if(soundscape?.needsFocus == true && audioManager.activePlaybackConfigurations.isEmpty()) {
            requestAudioFocus()
            if(focusLifecycle.isAcquired()) soundscape?.focusChanged(true)
          }
        },400)
      }
    }
  }
  private fun scheduleFocusResume() {
    val ticket = focusResumeTicket ?: return
    val revision = ++focusResumeRevision
    focusResumeHandler.postDelayed({
      if (revision != focusResumeRevision || focusResumeTicket != ticket || !NCPlaybackGuard.shared.isOpen(ticket)) return@postDelayed
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && audioManager.activePlaybackConfigurations.isNotEmpty()) return@postDelayed
      if (players.values.none { it.focusInterrupted && it.ncAllowsFocusEffect(ticket, it.ncItemIdentity) }) {
        focusResumeTicket = null
        return@postDelayed
      }
      requestAudioFocus()
      if (focusLifecycle.isAcquired()) resumeFocusInterrupted(ticket)
      else if (focusLifecycle.currentRequest() == null) {
        // Denied, rather than delayed: restore the JS watchdog instead of
        // leaving a permanently suppressed timeout with no future GAIN.
        NCPlaybackEvidence.record("focus_request_denied")
        focusResumeTicket = null
        players.values.forEach { if (it.ncAllowsFocusEffect(ticket,it.ncItemIdentity)) {
          it.focusInterrupted = false; it.isPaused = false
        } }
      }
    }, 400)
  }
  private fun resumeFocusInterrupted(ticket: String?) {
    if (ticket == null || focusResumeTicket != ticket || !NCPlaybackGuard.shared.isOpen(ticket)) return
    focusResumeTicket = null
    permanentFocusLoss = false
    focusResumeRevision++
    NCPlaybackEvidence.record("focus_resume")
    players.values.forEach { player ->
      if (!player.focusInterrupted || !player.ncAllowsFocusEffect(ticket, player.ncItemIdentity)) return@forEach
      player.focusInterrupted = false
      player.isPaused = false
      NCPlaybackGuard.shared.resumeOrderedFocus(player.ncPlaybackBinding,ticket)
      player.ncGuardedPlay()
    }
  }
  private val audioRouteCallback = object : AudioDeviceCallback() {
    // Enumeration also fires at registration and for USB input/charging events.
    // It is not proof that an existing output route was lost. The Live capture
    // lease separately validates its actual duplex route.
    override fun onAudioDevicesAdded(addedDevices: Array<out AudioDeviceInfo>) = Unit
    override fun onAudioDevicesRemoved(removedDevices: Array<out AudioDeviceInfo>) {
      val ticket = NCPlaybackGuard.shared.currentTicket()
      val route = NCCommunicationRoute.shared.forTicket(ticket)
      if (route != null && removedDevices.any { it.isSink && it.id == route.deviceId } &&
          !NCCommunicationRoute.shared.expectedRemoval(ticket, removedDevices.map { it.id }.toSet()))
        retireForRouteChange(NCPlaybackGuard.shared.currentTicket())
    }
  }

  // Android emits this when the actual media route is about to become noisy.
  // Inventory changes alone do not mean the selected headphones disconnected.
  private val noisyReceiver = object : BroadcastReceiver() {
    override fun onReceive(context: Context?, intent: Intent?) {
      if (intent?.action == AudioManager.ACTION_AUDIO_BECOMING_NOISY) {
        val ticket=NCPlaybackGuard.shared.currentTicket()
        val preparing=NCCommunicationRoute.shared.isPreparing(ticket)
        appContext.mainQueue.launch {if(!preparing) {
          NCPlaybackEvidence.record("output_route_lost")
          soundscape?.pause("route")
          focusResumeTicket=null;focusResumeRevision++
          players.values.forEach {player->
            if(ticket!=null && player.ncAllowsFocusEffect(ticket,player.ncItemIdentity)) {
              player.focusInterrupted=false;player.isPaused=false
              val permit=NCPlaybackGuard.shared.pauseOrderedUser(player.ncPlaybackBinding,ticket)
              if(permit!=null)player.ncPauseForLock(permit) else player.ncGuardedPause()
            }
          }
        }}
      }
    }
  }

  private fun retireForRouteChange(observedTicket: String?) {
    // Capture the authorization when the callback arrives. A queued UI task
    // must not reinterpret a planned selection as a later hardware failure.
    val preparationEvent=NCCommunicationRoute.shared.isPreparing(observedTicket)
    appContext.mainQueue.launch { if (!preparationEvent) {
      NCPlaybackEvidence.record("output_route_lost")
      soundscape?.pause("route")
      NCPlaybackGuard.shared.retireForRouteChange(observedTicket)
    } }
  }
  private fun focusListener(request: Long) = AudioManager.OnAudioFocusChangeListener { focusChange ->
    val event = focusLifecycle.observe(request)
    val observedTicket = NCPlaybackGuard.shared.currentTicket()
    val canDuck = interruptionMode == InterruptionMode.DUCK_OTHERS ||
      (observedTicket != null && NCPlaybackGuard.shared.isOpen(observedTicket))
    val observedPlayers = players.values.map { it to it.ncItemIdentity }
    appContext.mainQueue.launch focusChange@{
      val acquired = when (focusChange) {
        AudioManager.AUDIOFOCUS_GAIN -> true
        AudioManager.AUDIOFOCUS_LOSS, AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> false
        AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> if (canDuck) null else false
        else -> null
      }
      if (!focusLifecycle.apply(event, acquired)) return@focusChange
      when(focusChange) {
        AudioManager.AUDIOFOCUS_GAIN -> soundscape?.focusChanged(true)
        AudioManager.AUDIOFOCUS_LOSS, AudioManager.AUDIOFOCUS_LOSS_TRANSIENT,
        AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> soundscape?.focusChanged(false)
      }
      NCPlaybackEvidence.record("focus_changed", focusChange)
      fun admits(player: AudioPlayer, item: String?): Boolean =
        players[player.id] === player && player.ncAllowsFocusEffect(observedTicket, item)
      when (focusChange) {
        AudioManager.AUDIOFOCUS_LOSS, AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> {
          // A competing media app does not send a later GAIN. Preserve the
          // existing reply ticket and position while its playback is active.
          val recoverable = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            observedTicket != null && NCPlaybackGuard.shared.isOpen(observedTicket) &&
            observedPlayers.any { (player, item) -> admits(player, item) &&
              (player.ref.isPlaying || player.ref.playWhenReady || player.focusInterrupted ||
              NCPlaybackGuard.shared.orderedUserPauseState(player.ncPlaybackBinding,observedTicket)!=null) }
          if (!recoverable) NCPlaybackGuard.shared.retireIfCurrent(observedTicket, NCPlaybackGuard.RetirementCause.AUDIO_FOCUS_LOSS)
          if (focusChange == AudioManager.AUDIOFOCUS_LOSS) {
            if(soundscape?.needsFocus == true) permanentFocusLoss=true
            focusLifecycle.abandon(request)
            audioFocusRequest = null
            audioFocusChangeListener = null
          }
          observedPlayers.forEach { (player, item) ->
            if (!admits(player, item)) return@forEach
            if (recoverable && (player.ref.isPlaying || player.ref.playWhenReady || player.focusInterrupted ||
              NCPlaybackGuard.shared.orderedUserPauseState(player.ncPlaybackBinding,observedTicket)!=null)) {
              player.isPaused = true
              player.focusInterrupted = true
            }
            val permit=if(recoverable && observedTicket!=null)
              NCPlaybackGuard.shared.pauseOrderedFocus(player.ncPlaybackBinding,observedTicket) else null
            if(permit!=null)player.ncPauseForLock(permit) else player.ref.pause()
          }
          if (recoverable) {
            focusResumeTicket = observedTicket
            permanentFocusLoss = focusChange == AudioManager.AUDIOFOCUS_LOSS
            focusResumeRevision++
            // Transient owners (calls, alarms) retain focus until GAIN. Never
            // steal it during a silent stretch of their interruption.
            if (permanentFocusLoss) scheduleFocusResume()
          }
        }

        AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> {
          if (canDuck) {
            observedPlayers.forEach { (player, item) ->
              if (!admits(player, item)) return@forEach
              if (player.previousVolume != player.ref.volume) {
                player.previousVolume = player.ref.volume
              }
              player.ref.volume = player.previousVolume * 0.5f
            }
          } else {
            NCPlaybackGuard.shared.retireIfCurrent(observedTicket, NCPlaybackGuard.RetirementCause.AUDIO_FOCUS_LOSS)
            observedPlayers.forEach { (player, item) ->
              if (!admits(player, item)) return@forEach
              if (player.ref.isPlaying) {
                player.isPaused = true
                player.ref.pause()
              }
            }
          }
        }

        AudioManager.AUDIOFOCUS_GAIN -> {
          if (focusResumeTicket == observedTicket) resumeFocusInterrupted(observedTicket)
          observedPlayers.forEach { (player, item) ->
            if (!admits(player, item)) return@forEach
            player.setVolume(player.previousVolume)
            if (player.isPaused) {
              player.isPaused = false
              player.ncGuardedPlay()
            }
          }
        }
      }
    }
  }

  private fun shouldReleaseFocus(): Boolean {
    // A temporary pause must retain the request whose GAIN resumes this player.
    // Buffering also retains playback intent; ended/idle players do not.
    return soundscape?.holdsFocus != true && players.values.none { it.ref.isPlaying || it.focusInterrupted ||
      (it.ref.playWhenReady && it.ref.playbackState != Player.STATE_ENDED && it.ref.playbackState != Player.STATE_IDLE) }
  }

  private fun resumeOrderedUserWithFocus(player:AudioPlayer,ticket:String):Boolean {
    if(!audioEnabled ||NCPlaybackGuard.shared.orderedUserPauseState(player.ncPlaybackBinding,ticket)==null)return false
    requestAudioFocus()
    if(!focusLifecycle.isAcquired() &&interruptionMode!=InterruptionMode.MIX_WITH_OTHERS)return false
    return NCPlaybackGuard.shared.resumeOrderedUser(player.ncPlaybackBinding,ticket)
  }

  private fun requestAudioFocus() {
    if (focusLifecycle.isAcquired() || focusLifecycle.currentRequest() != null || !audioEnabled || interruptionMode == InterruptionMode.MIX_WITH_OTHERS) {
      return
    }
    val request = focusLifecycle.beginRequest()
    val listener = focusListener(request)
    audioFocusChangeListener = listener

    val result = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      val requestType = interruptionMode?.let {
        if (it == InterruptionMode.DO_NOT_MIX) {
          AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
        } else {
          AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK
        }
      } ?: AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
      audioFocusRequest = AudioFocusRequest.Builder(requestType).run {
        setAudioAttributes(
          AudioAttributes.Builder()
            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
            .build()
        )
        setAcceptsDelayedFocusGain(true)
        setOnAudioFocusChangeListener(listener)
        build()
      }
      audioFocusRequest?.let {
        audioManager.requestAudioFocus(it)
      }
    } else {
      @Suppress("DEPRECATION")
      val requestType = if (interruptionMode == InterruptionMode.DO_NOT_MIX) {
        AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
      } else {
        AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK
      }
      audioManager.requestAudioFocus(listener, AudioManager.STREAM_MUSIC, requestType)
    }

    when (result) {
      AudioManager.AUDIOFOCUS_REQUEST_GRANTED -> focusLifecycle.markGranted(request)
      AudioManager.AUDIOFOCUS_REQUEST_DELAYED -> Unit
      else -> {
        focusLifecycle.abandon(request)
        audioFocusRequest = null
        audioFocusChangeListener = null
        Log.e(TAG, "Audio focus request failed with: $result")
      }
    }
  }

  private fun releaseAudioFocus() {
    val request = focusLifecycle.currentRequest() ?: return
    focusLifecycle.abandon(request)

    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      audioFocusRequest?.let {
        audioManager.abandonAudioFocusRequest(it)
      }
    } else {
      @Suppress("DEPRECATION")
      audioFocusChangeListener?.let { audioManager.abandonAudioFocus(it) }
    }
    audioFocusRequest = null
    audioFocusChangeListener = null
  }

  /** Only this registered player's actual source, sink and loopers may back
   * an RPC. The worker coordinator never supplies output or reader evidence.
   * Retired RPCs stay addressable for ordered journal reconciliation.
   */
  private fun continuousFixtureBuild():Boolean = try {
    // Public app build flag only; ordinary Metro/live builds cannot opt in.
    Class.forName("${context.packageName}.BuildConfig").getField("NC_PRESENTATION_PROBE").getBoolean(null)
  }catch(_:ReflectiveOperationException){false}
  private fun continuousRpc(player:AudioPlayer):NCContinuousMuxedRpc {
    continuousRpcs[player]?.let {return it}
    check(players[player.id]===player)
    val diagnostic=NCDiagnosticPlayerObserver(player.id)
    val created=NCContinuousMuxedRpc(object:NCContinuousMuxedRpc.Port {
      private var revision=0L
      private var pending:NCContinuousMuxedQueue?=null
      private var idleClosure:NCMuxedTrialSourceOwner.Retirement?=null
      private val rotated=mutableSetOf<NCContinuousMuxedQueue>()
      private val returned=mutableSetOf<NCContinuousMuxedQueue>()
      override fun current()=(NCContinuousMuxedRpc.LIVE_VERSION==2 || player.ncContinuousFixtureEnabled) && players[player.id]===player
        && player.ncIsAliveSnapshot && !player.ncMuxedTrialRetired && player.ncMuxedTrialSessionEnabled
      override fun onMain(action:()->Unit) {runOnMain {action()}}
      override fun validate(rows:List<Map<String,Any>>,first:Int,d:NCContinuousMuxedSourceDescriptor,prefix:Boolean)=
        NCMuxedTrialPlayer.validateStream(context,rows,first,d.plan,prefix)
      override fun validateVisual(rows:List<Map<String,Any>>,first:Int):List<NCMuxedTrialPlayer.Clip> {
        val normalized=NCMuxedTrialSamples.idleRows(rows,first)
        return NCMuxedTrialPlayer.validate(context,normalized,rows.size*12,rows.size*24000L)
          .mapIndexed {offset,clip->clip.copy(startSamples=(first+offset)*24000L)}
      }
      override fun validateOrdered(rows:List<Map<String,Any>>,output:List<NCOrderedOutputChunk>,
        d:NCOrderedMuxedSourceDescriptor):List<NCMuxedTrialPlayer.Clip> {
        require(output.size==rows.size &&output.isNotEmpty() &&output.all{d.matches(it)})
        val first=(output.first().sourceRange.start/12).toInt()
        // Keep the real extractor, cache confinement, 24fps and AAC trim checks.
        // Prefix=false permits one ready chunk, not a fabricated complete segment.
        val clips=NCMuxedTrialPlayer.validateStream(context,rows,first,d.plan,prefix=false)
        clips.forEachIndexed{index,clip->
          val descriptor=output[index];val digest=java.security.MessageDigest.getInstance("SHA-256")
          require(clip.bytes==descriptor.byteLength &&clip.frames==descriptor.frameCount &&clip.samples==descriptor.sampleCount)
          clip.file.inputStream().use {input->
            val buffer=ByteArray(65536)
            while(true){val count=input.read(buffer);if(count<0)break;digest.update(buffer,0,count)}
          }
          require(digest.digest().joinToString(""){"%02x".format(it.toInt() and 255)}==descriptor.sha256
            &&clip.file.length()==descriptor.byteLength) {"Ordered media digest mismatch"}
        }
        return clips
      }
      override fun beforeOpen():Boolean {
        val closure=runOnMain {
          if(!current())return@runOnMain null
          if(player.ncMuxedTrialOwner!=null) {
            idleClosure=player.ncBeginInitialIdleRetirement()?:return@runOnMain null
          }
          idleClosure
        }
        if(closure==null)return runOnMain {current() && player.ncMuxedTrialOwner==null && idleClosure==null}
        val end=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(5000)
        if(!closure.awaitReaders(5000))return false
        while(System.nanoTime()<end && current()) {
          val complete=CountDownLatch(1);val accepted=AtomicReference<Boolean?>(null)
          val posted=runOnMain {current() && player.ncSettleInitialIdle {accepted.set(it);complete.countDown()}}
          if(!posted)return false
          try {
            if(!complete.await((end-System.nanoTime()).coerceAtLeast(0),TimeUnit.NANOSECONDS))return false
            if(accepted.get()==true)return current()
            CountDownLatch(1).await(25,TimeUnit.MILLISECONDS)
          }catch(_:InterruptedException){Thread.currentThread().interrupt();return false}
        }
        return false
      }
      override fun begin(d:NCContinuousMuxedSourceDescriptor):NCContinuousMuxedQueue? =
        beginTimeline(d.ticket,false){it.bindPhoneReplyChunk(d.ticket,d.replyId,d.chunkId)}
      override fun beginOrdered(d:NCOrderedMuxedSessionDescriptor):NCContinuousMuxedQueue? =
        beginTimeline(d.ticket,true){it.bind(d.ticket)}
      override fun orderedContinuation(queue:NCContinuousMuxedQueue,scope:NCOrderedContinuation.Scope):NCOrderedContinuation.Port? {
        val run=queue.nativeEnrollment()?.first?.run?:return null
        if(run.id!=scope.runId ||run.revision!=scope.revision)return null
        val owner={current() &&owns(queue) &&queue.continuationCurrent(run)}
        return object:NCOrderedContinuation.Port {
          private val cueLock=Any()
          private val cueHandler=android.os.Handler(android.os.Looper.getMainLooper())
          private val cueClock=NCConnectionRecoveryClock()
          @Volatile private var cueEpoch=0L
          private var cue:NCConnectionCueOutput?=null
          private var cueTask:Runnable?=null
          private fun playCue(epoch:Long,recovered:Boolean)=synchronized(cueLock) {
            if(cueEpoch!=epoch ||!owner())return@synchronized false
            cue?.stop()
            val output=NCConnectionCueOutput(authorize={stop,play->
              cueEpoch==epoch &&queue.continuationCue(run,epoch,stop,play)
            },createTrack={bytes->
              val route=NCCommunicationRoute.shared.forTicket(scope.ticket)
              val candidate=android.media.AudioTrack.Builder().setAudioAttributes(android.media.AudioAttributes.Builder()
                .setUsage(if(route!=null)android.media.AudioAttributes.USAGE_VOICE_COMMUNICATION else android.media.AudioAttributes.USAGE_MEDIA)
                .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                .setAudioFormat(android.media.AudioFormat.Builder().setSampleRate(NCConnectionCueSamples.SAMPLE_RATE)
                  .setEncoding(android.media.AudioFormat.ENCODING_PCM_16BIT).setChannelMask(android.media.AudioFormat.CHANNEL_OUT_MONO).build())
                .setBufferSizeInBytes(bytes).setTransferMode(android.media.AudioTrack.MODE_STATIC).build()
              try {
                if(route!=null) {
                  val device=context.getSystemService(android.media.AudioManager::class.java)
                    .getDevices(android.media.AudioManager.GET_DEVICES_OUTPUTS).firstOrNull{it.id==route.deviceId &&it.type==route.deviceType}
                    ?:error("ordered_continuation_cue_route")
                  check(candidate.setPreferredDevice(device)){"ordered_continuation_cue_route"}
                }
                candidate
              } catch(error:Throwable){candidate.release();throw error}
            })
            cue=output;output.play(recovered)
          }
          private fun scheduleCue(epoch:Long) {synchronized(cueLock) {
            cueTask?.let{cueHandler.removeCallbacks(it)}
            val task=Runnable {
              if(cueEpoch==epoch &&owner())player.ncPostCachedProof {
                if(cueEpoch==epoch &&owner()) {
                  try {
                    synchronized(cueLock) {
                      if(cueEpoch==epoch &&cueClock.takeWaitingCue(android.os.SystemClock.elapsedRealtime()))playCue(epoch,false)
                    }
                  } catch(error:RuntimeException) {diagnostic.continuationCueFailure("waiting",epoch,error);cancel(epoch)}
                  if(cueEpoch==epoch)scheduleCue(epoch)
                }
              }
            }
            cueTask=task;cueHandler.postDelayed(task,5000)
          }}
          override fun current()=owner()
          override fun failed(epoch:Long,error:RuntimeException)=diagnostic.continuationFailure("advance",epoch,error)
          override fun buffered()=queue.continuationBuffered()
            ||runOnMain{owner() &&player.ncCachedIdle?.continuationAvailable()==true}
          override fun cursors():Pair<Long,Long> {
            val snapshot=queue.authority.orderedSnapshot(run)?:error("ordered_continuation_owner")
            return (snapshot["publishedCursor"] as Long) to (snapshot["acknowledgedCursor"] as Long)
          }
          override fun pause(epoch:Long):NCOrderedContinuation.Position? {
            val permit=queue.continuationPause(run,epoch)?:return null
            val done=CountDownLatch(1);val result=AtomicReference<Map<String,Long>?>(null)
            runOnMain {
              if(!owner()){permit.revoke();done.countDown()}
              else player.ncPauseForContinuation(permit){accepted->
                if(accepted)result.set(player.ncContinuousOutputController.orderedContinuationPosition(queue))
                done.countDown()
              }
            }
            try {if(!done.await(5000,TimeUnit.MILLISECONDS))return null}
            catch(_:InterruptedException){Thread.currentThread().interrupt();return null}
            if(!owner())return null
            val native=result.get()?:return null
            synchronized(cueLock) {
              cueEpoch=epoch;cueClock.pause(epoch,android.os.SystemClock.elapsedRealtime())
              try {
                if(cueClock.takeWaitingCue(android.os.SystemClock.elapsedRealtime()))playCue(epoch,false)
                scheduleCue(epoch)
              } catch(error:RuntimeException) {diagnostic.continuationCueFailure("waiting",epoch,error);cancel(epoch)} // Optional local cue is not output admission.
            }
            return NCOrderedContinuation.Position(native.getValue("ordinal"),native.getValue("frameOffset").toInt(),
              native.getValue("consumedSamples"))
          }
          override fun release(epoch:Long):Boolean {
            if(!owner())return false
            val played=synchronized(cueLock) {
              if(cueEpoch==0L)false else {
                if(cueEpoch!=epoch ||!cueClock.resume(epoch,android.os.SystemClock.elapsedRealtime()))return false
                try{playCue(epoch,true)}catch(error:RuntimeException){diagnostic.continuationCueFailure("recovered",epoch,error);cancel(epoch);false}
              }
            }
            // Same existing cue/echo-tail interval. This worker wait never
            // occupies the UI/output looper or acquires a microphone lease.
            if(played)try {CountDownLatch(1).await(NCConnectionRecoveryClock.RESUME_SUPPRESSION_MS,TimeUnit.MILLISECONDS)}
              catch(_:InterruptedException){Thread.currentThread().interrupt();return false}
            cancel(epoch)
            return owner() &&queue.continuationResume(run,epoch)
          }
          override fun cancel(epoch:Long)=synchronized(cueLock) {
            if(cueEpoch>epoch)return@synchronized
            cueEpoch=0;cueClock.cancel();cueTask?.let{cueHandler.removeCallbacks(it)};cueTask=null
            cue?.stop();cue=null
          }
          override fun watch(advance:()->Unit):()->Unit {
            val busy=java.util.concurrent.atomic.AtomicBoolean(false)
            val observer:()->Unit={
              if(busy.compareAndSet(false,true)) {
                val posted=player.ncPostCachedProof{try{advance()}finally{busy.set(false)}}
                if(!posted)busy.set(false)
              }
            }
            queue.onContinuationPresentation=observer
            return {if(queue.onContinuationPresentation===observer)queue.onContinuationPresentation=null}
          }
        }
      }
      private fun beginTimeline(ticket:String,ordered:Boolean,bind:(NCPlaybackBinding)->Boolean):NCContinuousMuxedQueue? {
        fun allowed(name:String,value:Boolean):Boolean {
          if(!value)try{diagnostic.decision("ordered.open.$name",false)}catch(_:Exception){}
          return value
        }
        check(allowed("application_thread",android.os.Looper.myLooper()==player.ref.applicationLooper))
        if(!allowed("player_current",current()) || !allowed("pending_queue_empty",pending==null)
          || !allowed("revision_available",revision<9007199254740991L)
          || !allowed("ticket_current",NCPlaybackGuard.shared.currentTicket()==ticket))return null
        val source=androidx.media3.exoplayer.source.ConcatenatingMediaSource()
        val sourceIdentity=AtomicReference<String?>(null)
        val model=NCContinuousMuxedPresentation(++revision,desktopOrdered=ordered)
        val outputSource=NCContinuousMuxedTailSource(source,ownership=model) {
          current() && sourceIdentity.get()==player.ncItemIdentity
        }.also {it.preparationObserver=player::ncObservePreparation}
        val binding=player.ncPlaybackBinding
        val controller=player.ncContinuousOutputController;val slot=controller.soleSink()
        if(slot==null){allowed("sole_sink_available",false);return null}
        lateinit var queue:NCContinuousMuxedQueue
        val timeline=NCContinuousMuxedTimeline(source,android.os.Handler(player.ref.applicationLooper),
          {current() && player.ncOwnsContinuousTimeline(outputSource) && queue.matchesBinding(player.ncPlaybackBinding)},
          {child->NCMuxedTrialPlayer.mediaSource(context,child.clip,child.mediaId,child.reader)},
          {child->check(player.ncStageContinuousIdentity(model,child.mediaId,child.key))},
          {controller.invalidate(slot,"queue_fence");android.os.Handler(player.ref.applicationLooper).post {
            if(players[player.id]===player && pending===queue) {player.ref.pause();player.ref.stop()}
          };Unit},outputSource::seal,orderedRunRevision=if(ordered)revision else null,
          protectedPeriodMediaIds=outputSource::protectedPeriodMediaIds)
        if(!allowed("timeline_prepared",player.ncPrepareContinuousTimeline(outputSource)))return null
        sourceIdentity.set(player.ncItemIdentity)
        queue=NCContinuousMuxedQueue(NCPlaybackGuard.shared,binding,model,revision,
          {System.currentTimeMillis().toDouble()},{android.os.SystemClock.elapsedRealtime()},timeline)
        pending=queue
        if(!player.ncRegisterUnpreparedContinuousQueue(queue))queue.fence("pending_owner")
        if(!bind(binding))queue.fence("initial_binding")
        return queue
      }
      override fun owns(queue:NCContinuousMuxedQueue)=current() && pending===queue && player.ncContinuousQueue===queue
      override fun forgetClosedOrdered(queue:NCContinuousMuxedQueue):Boolean {
        check(android.os.Looper.myLooper()==player.ref.applicationLooper)
        if(players[player.id]!==player ||pending===queue ||queue !in returned ||queue.retirementWitness()==null)return false
        rotated.remove(queue);returned.remove(queue);return true
      }
      override fun attach(queue:NCContinuousMuxedQueue,done:(Boolean)->Unit):Boolean =
        current() && pending===queue && player.ncAttachContinuousQueue(queue,done)
      override fun closeUnenrolled(queue:NCContinuousMuxedQueue,readers:NCContinuousMuxedQueue.DetachedReaders,done:(Boolean)->Unit):Boolean =
        players[player.id]===player && pending===queue && player.ncCloseUnenrolledContinuousQueue(queue,readers,done)
      override fun settleOrdered(queue:NCContinuousMuxedQueue,done:(Boolean)->Unit):Boolean {
        check(android.os.Looper.myLooper()==player.ref.applicationLooper)
        if(players[player.id]!==player || !player.ncIsAliveSnapshot)return false
        if(queue in returned){done(player.ncContinuousSettledWitness(queue)!=null);return true}
        if(pending!==queue)return false
        fun retained() {
          // Ordered replacement has no intervening ordinary idle source. Keep
          // this exact positive release proof for the successor's enrollSettled;
          // returning to ordinary idle here would consume it prematurely.
          val accepted=players[player.id]===player &&pending===queue
            &&player.ncContinuousSettledWitness(queue)!=null
          if(accepted){returned+=queue;pending=null;idleClosure=null}
          done(accepted)
        }
        if(queue in rotated){retained();return true}
        return player.ncSettleContinuousQueue(queue) {accepted->
          if(!accepted)done(false)
          else {rotated+=queue;retained()}
        }
      }
      override fun settle(queue:NCContinuousMuxedQueue,done:(Boolean)->Unit):Boolean {
        check(android.os.Looper.myLooper()==player.ref.applicationLooper)
        if(queue in returned){done(true);return true}
        if(players[player.id]!==player || !player.ncIsAliveSnapshot || pending!==queue)return false
        fun returnIdle():Boolean = player.ncReturnContinuousOutputToIdle {accepted->
          if(accepted){returned+=queue;pending=null;idleClosure=null}
          done(accepted)
        }
        if(queue in rotated)return returnIdle()
        return player.ncSettleContinuousQueue(queue) {accepted->
          if(!accepted)done(false)
          else {rotated+=queue;if(!returnIdle())done(false)}
        }
      }
      override fun settleMixed(queue:NCContinuousMuxedQueue,done:(NCContinuousMuxedRpc.MixedSettlement)->Unit):Boolean {
        check(android.os.Looper.myLooper()==player.ref.applicationLooper)
        if(players[player.id]!==player || !player.ncIsAliveSnapshot || pending!==queue || queue in returned)return false
        fun observed()=done(NCContinuousMuxedRpc.MixedSettlement(player.ncContinuousSettledWitness(queue)))
        if(queue in rotated){observed();return true}
        return player.ncSettleContinuousQueue(queue) {accepted->
          if(accepted)rotated+=queue
          observed()
        }
      }
      override fun releaseMixed(queue:NCContinuousMuxedQueue,certificate:NCContinuousMuxedQueue.MixedRetirement,done:(Boolean)->Unit):Boolean {
        check(android.os.Looper.myLooper()==player.ref.applicationLooper)
        if(players[player.id]!==player || !player.ncIsAliveSnapshot || pending!==queue || queue !in rotated
          || player.ncContinuousSettledWitness(queue)!==certificate.settlement || !certificate.matches(queue.authority))return false
        return player.ncReturnContinuousOutputToIdle {accepted->
          if(accepted){returned+=queue;pending=null;idleClosure=null}
          done(accepted)
        }
      }
    },orderedDiagnose=diagnostic::orderedLifecycle,diagnose=diagnostic::decision)
    return continuousRpcs.putIfAbsent(player,created)?:created
  }

  private fun orderedRequest(encoded:String):Map<String,Any> {
    require(encoded.length<=524288) {"Ordered request too large"}
    fun decode(value:Any?,depth:Int):Any? {
      require(depth<=12) {"Ordered request too deep"}
      return when(value) {
        null,org.json.JSONObject.NULL -> null
        is org.json.JSONObject -> value.keys().asSequence().associateWith {decode(value.get(it),depth+1)}
        is org.json.JSONArray -> (0 until value.length()).map {decode(value.get(it),depth+1)}
        is String,is Boolean,is Number -> value
        else -> error("Invalid ordered JSON value")
      }
    }
    val parser=org.json.JSONTokener(encoded)
    val value=parser.nextValue()
    require(value is org.json.JSONObject &&parser.nextClean()=='\u0000') {"Invalid ordered JSON envelope"}
    return value.keys().asSequence().associateWith {requireNotNull(decode(value.get(it),0))}
  }

  // Keep inline Expo registrations below the JVM method-size limit.
  private fun expo.modules.kotlin.classcomponent.ClassComponentBuilder<AudioPlayer>.orderedFunctions() {
    AsyncFunction("ncOpenOrderedMuxed") { player:AudioPlayer,value:String -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(orderedRequest(value),"native.rpc.ordered.open") {continuousRpc(player).openOrdered(it)} }
    AsyncFunction("ncReadOrderedPlaybackClock") { player:AudioPlayer,value:Map<String,Any> ->
      runOnMain {
        val clock=continuousRpc(player).readOrderedPlaybackClock(value)
        clock+mapOf("playing" to player.ref.isPlaying,"buffering" to (player.ref.playbackState==Player.STATE_BUFFERING))
      }
    }
    AsyncFunction("ncSetOrderedUserPaused") { player:AudioPlayer,ticket:String,paused:Boolean ->
      synchronized(player.ncUserPauseLock) {
        if(!paused)runOnMain {resumeOrderedUserWithFocus(player,ticket)}
        else {
          val permit=NCPlaybackGuard.shared.pauseOrderedUser(player.ncPlaybackBinding,ticket)
          if(permit==null)false else {
            val done=CountDownLatch(1);val accepted=AtomicReference(false)
            runOnMain {
              player.ncPauseForContinuation(permit){ok->accepted.set(ok);done.countDown()}
            }
            val completed=try{done.await(5000,TimeUnit.MILLISECONDS)}catch(_:InterruptedException){
              Thread.currentThread().interrupt();false
            }
            if(!completed || !accepted.get()) {
              permit.revoke()
              NCPlaybackGuard.shared.invalidateOrderedCarrier(permit.carrier)
              false
            } else accepted.get()
          }
        }
      }
    }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncSuspendOrderedTransport") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_CONTINUATION_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.continuation_suspend") {continuousRpc(player).suspendOrderedTransport(it)} }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncReadOrderedContinuation") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_CONTINUATION_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.continuation_read") {continuousRpc(player).readOrderedContinuation(it)} }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncResumeOrderedTransport") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_CONTINUATION_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.continuation_resume") {continuousRpc(player).resumeOrderedTransport(it)} }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncCancelOrderedContinuation") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_CONTINUATION_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.continuation_cancel") {continuousRpc(player).cancelOrderedContinuation(it)} }.runOnQueue(appContext.backgroundCoroutineScope)
    // Blocking validation/timeline waits must not occupy Expo's shared file-I/O
    // queue. The session serializes mutations; native still checks each commit.
    AsyncFunction("ncStageOrderedMuxed") { player:AudioPlayer,value:String -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(orderedRequest(value),"native.rpc.ordered.stage") {continuousRpc(player).stageOrdered(it)} }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncAppendOrderedMuxed") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.append") {continuousRpc(player).appendOrdered(it)} }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncReadOrderedMuxed") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.read") {continuousRpc(player).readOrdered(it)} }
    AsyncFunction("ncAcknowledgeOrderedMuxed") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.acknowledge") {continuousRpc(player).acknowledgeOrdered(it)} }
    AsyncFunction("ncPruneOrderedMuxed") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.prune") {continuousRpc(player).pruneOrdered(it)} }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncCompleteReplyOrderedMuxed") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.complete_reply") {continuousRpc(player).completeReplyOrdered(it)} }
    AsyncFunction("ncInvalidateOrderedMuxed") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.invalidate") {continuousRpc(player).invalidateOrdered(it)} }
    AsyncFunction("ncDropOrderedMuxed") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.drop") {continuousRpc(player).dropOrdered(it)} }
    AsyncFunction("ncCloseOrderedMuxed") { player:AudioPlayer,value:Map<String,Any> -> check(NCContinuousMuxedRpc.ORDERED_VERSION==1); NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.ordered.close") {continuousRpc(player).closeOrdered(it)} }
    AsyncFunction("ncPrepareOrderedCached") { player:AudioPlayer,value:String,promise:Promise ->
      val raw=NCContinuousMuxedRequests.orderedEnvelope(orderedRequest(value),setOf("run","candidate","file"))
      val queue=continuousRpc(player).cachedOrderedQueue(raw["run"])
      val candidate=NCOrderedCachedVideo.candidate(raw["candidate"])
      check(queue.cachedScope(candidate)) {"ordered_cached_queue_scope"}
      val file=NCOrderedCachedVideo.validate(appContext.reactContext!!.cacheDir,candidate,raw["file"])
      runOnMain {
        check(player.ncContinuousQueue===queue &&player.ncMuxedVideoViewEligible) {"ordered_cached_player_changed"}
        val cached=player.ncCachedIdle?:NCOrderedCachedVideo(player,queue,player.ncCachedIdleHost,player::ncPostCachedProof)
          .also {player.ncCachedIdle=it}
        check(cached.owns(queue)) {"ordered_cached_reader_owner"}
        cached.prepare(candidate,file){promise.resolve(it)}
      }
    }
    AsyncFunction("ncArmOrderedCached") { player:AudioPlayer,value:String ->
      val raw=NCContinuousMuxedRequests.orderedEnvelope(orderedRequest(value),setOf("run","candidate","activationRevision"))
      val queue=continuousRpc(player).cachedOrderedQueue(raw["run"])
      val candidate=NCOrderedCachedVideo.candidate(raw["candidate"])
      val revision=NCContinuousMuxedRequests.integer(raw["activationRevision"],1)
      check(queue.cachedScope(candidate)) {"ordered_cached_queue_scope"}
      runOnMain {player.ncCachedIdle?.takeIf{it.owns(queue)}?.arm(candidate,revision)==true}
    }
    AsyncFunction("ncReadOrderedCached") { player:AudioPlayer,value:String ->
      val raw=NCContinuousMuxedRequests.orderedEnvelope(orderedRequest(value),setOf("run","activationRevision"))
      val queue=continuousRpc(player).cachedOrderedQueue(raw["run"])
      val revision=NCContinuousMuxedRequests.integer(raw["activationRevision"],1)
      runOnMain {player.ncCachedIdle?.takeIf{it.owns(queue)}?.status(revision)
        ?:mapOf("version" to 1,"activation" to null,"position" to null,"failure" to null)}
    }
    AsyncFunction("ncCloseOrderedCached") { player:AudioPlayer,value:String,promise:Promise ->
      val raw=NCContinuousMuxedRequests.orderedEnvelope(orderedRequest(value),setOf("run"))
      val cached=runOnMain {player.ncCachedIdle}
      if(cached==null)promise.resolve(true)
      else {
        val queue=continuousRpc(player).cachedOrderedQueue(raw["run"],cleanup=true)
        runOnMain {
          check(cached===player.ncCachedIdle &&cached.owns(queue)) {"ordered_cached_reader_owner"}
          cached.close {joined->if(joined &&player.ncCachedIdle===cached)player.ncCachedIdle=null;promise.resolve(joined)}
        }
      }
    }
  }

  private fun ModuleDefinitionBuilder.manualDepartureFunctions() {
    Events("ncManualDeparture", "soundscapeState")
    Function("ncManualDepartureState") { recordingId:String -> manualDeparture.snapshot(recordingId)?.payload() }
    Function("ncManualDepartureCanSend") { recordingId:String ->
      val state=manualDeviceState();val snapshot=manualDeparture.snapshot(recordingId)
      state.first==false && state.second==true && snapshot?.stopped==true && snapshot.error==null
    }
    Function("ncManualDepartureClaim") { recordingId:String, revision:Long ->
      runOnMain {
        val (locked,interactive)=manualDeviceState()
        manualDeparture.claimAutoSend(recordingId,revision,locked,interactive)
      }
    }
    Function("ncManualDepartureRelease") { recordingId:String ->
      runOnMain {manualDeparture.release(recordingId);if(manualDeparture.current()==null)manualActivity=null}
    }
  }

  private fun ModuleDefinitionBuilder.recorderFunctions() {
    Class(AudioRecorder::class) {
      Function("ncBeginManualRecording") { recorder:AudioRecorder, recordingId:String ->
        runOnMain {
          check(recorders[recorder.id]===recorder && recorder.isPrepared && !recorder.isRecording) {"manual_recorder_unavailable"}
          val activity=appContext.throwingActivity
          val (locked,interactive)=manualDeviceState()
          check(!activity.isFinishing && activity.hasWindowFocus() && locked==false && interactive==true) {"manual_recorder_not_foreground"}
          manualDeparture.begin(recordingId,recorder.id);manualActivity=activity
        }
      }
      Constructor { options: RecordingOptions ->
        val recorder = AudioRecorder(
          appContext.throwingActivity.applicationContext,
          appContext,
          options
        )
        recorder.useForegroundService = allowsBackgroundRecording
        recorders[recorder.id] = recorder
        recorder
      }

      Property("id") { recorder ->
        recorder.id
      }

      Property("uri") { recorder ->
        recorder.filePath?.let {
          Uri.fromFile(File(it)).toString()
        } ?: ""
      }

      Property("isRecording") { recorder ->
        recorder.isRecording
      }

      Property("currentTime") { recorder ->
        recorder.startTime
      }

      AsyncFunction("prepareToRecordAsync") { recorder: AudioRecorder, options: RecordingOptions? ->
        checkRecordingPermission()
        recorder.prepareRecording(options)
      }

      AsyncFunction("ncRecordPrepared") { recorder: AudioRecorder ->
        checkRecordingPermission()
        fun currentOnMain(): Boolean {
          val (locked,interactive)=manualDeviceState()
          return recorders[recorder.id]===recorder && !recorder.ncReleased && recorder.isPrepared &&
            manualDeparture.current()?.takeIf{it.recorderId==recorder.id}?.departed!=true &&
            appContext.throwingActivity.hasWindowFocus() && locked==false && interactive==true
        }
        fun current() = runOnMain { currentOnMain() }
        val route=runOnMain {
          check(currentOnMain()) {"manual_recorder_departed_before_start"}
          recorder.ncBeginMicrophonePreparation()
        }
        route.selectBluetooth()
        runOnMain {
          check(currentOnMain()) {"manual_recorder_departed_before_start"}
          recorder.ncUsePreparedMicrophone()
          recorder.record()
        }
        // Android SCO negotiation may take seconds. Never wait on the UI thread;
        // lifecycle callbacks can still stop capture while verification waits.
        route.confirmMicrophone({runOnMain {recorder.ncActualMicrophone()}}, ::current)
        runOnMain {
          check(currentOnMain() && recorder.isRecording) {"manual_recorder_departed_during_start"}
          recorder.ncDiscardPreparationAudio()
        }
        route.confirmMicrophone({runOnMain {recorder.ncActualMicrophone()}}, ::current, strict=true)
        runOnMain {
          check(currentOnMain() && recorder.isRecording) {"manual_recorder_departed_during_start"}
          recorder.ncFinishMicrophonePreparation()
        }
      }.runOnQueue(appContext.backgroundCoroutineScope)

      Function("record") { recorder: AudioRecorder, options: RecordOptions? ->
        checkRecordingPermission()
        runOnMain {
          val manual=manualDeparture.current()?.takeIf{it.recorderId==recorder.id}
          check(manual?.departed!=true){"manual_recorder_departed_before_start"}
          if (recorder.isPrepared)recorder.recordWithOptions(options?.atTime, options?.forDuration)
        }
      }

      Function("recordForDuration") { recorder: AudioRecorder, seconds: Double ->
        checkRecordingPermission()
        if (recorder.isPrepared) {
          recorder.recordForDuration(seconds)
        }
      }

      Function("pause") { recorder: AudioRecorder ->
        checkRecordingPermission()
        recorder.pauseRecording()
      }

      AsyncFunction("stop") { recorder: AudioRecorder ->
        checkRecordingPermission()
        runOnMain {
          val departed=manualDeparture.current()?.takeIf {it.recorderId==recorder.id}
          if(departed?.stopped==true) Bundle().apply {
            putBoolean("canRecord",false);putBoolean("isRecording",false);putString("url",departed.uri)
          } else recorder.stopRecording().also {result->
            departed?.let{manualDeparture.completed(it.recordingId,result.getString("url"))}
          }
        }
      }

      Function("getStatus") { recorder: AudioRecorder ->
        try {
          return@Function recorder.getAudioRecorderStatus()
        } catch (e: Exception) {
          throw e
        }
      }

      AsyncFunction("getCurrentInput") { recorder: AudioRecorder ->
        recorder.getCurrentInput(audioManager)
      }

      Function("getAvailableInputs") { recorder: AudioRecorder ->
        return@Function recorder.getAvailableInputs(audioManager)
      }

      Function("setInput") { recorder: AudioRecorder, input: String ->
        recorder.setInput(input, audioManager)
      }

      Function("startRecordingAtTime") { recorder: AudioRecorder, seconds: Double ->
        checkRecordingPermission()
        if (recorder.isPrepared) {
          recorder.startRecordingAtTime(seconds)
        }
      }
    }
  }

  // Keep additive Expo registrations in a separate JVM method; the DSL is inline.
  private fun ModuleDefinitionBuilder.soundscapeFunctions() {
    Function("ncSoundscapeVersion") { if(NCSoundscapeActivity.available()) 1 else 0 }
    Function("ncSoundscapeEffectVersion") { if(NCSoundscapeActivity.available()) 1 else 0 }
    AsyncFunction("ncSoundscapeEffect") { payload: Map<String,Any?>, promise: Promise ->
      val scope=soundScope(payload)
      val token=(payload["load_token"] as Number).toLong()
      val volume=(payload["volume"] as Number).toFloat()
      val cueId=payload["cue_id"] as String
      val deadline=(payload["deadline_utc_ms"] as Number).toLong()
      require(volume.isFinite() && volume in 0f..1f && cueId.isNotBlank() && cueId.length<=128)
      val file=soundFiles.acquire(payload["file_token"] as String)
      runOnMain {
        val current=soundscape
        if(current==null) { soundWorker.execute { soundFiles.release(file) }; promise.resolve(false) }
        else current.effect(scope,token,file,cueId,volume,deadline) { promise.resolve(it) }
      }
    }
    AsyncFunction("ncSoundscapeStopEffect") { payload: Map<String,Any?> ->
      runOnMain { soundscape?.stopEffect(soundScope(payload)) }
    }
    AsyncFunction("ncSoundscapeFileBegin") { scope: String, hash: String, bytes: Double ->
      require(bytes.isFinite() && bytes == bytes.toLong().toDouble())
      val download=soundFiles.begin(scope,NCSoundscapeMedia(hash,bytes.toLong()))
      mapOf("token" to download.token,"ready" to download.ready)
    }
    AsyncFunction("ncSoundscapeFileWrite") { token: String, offset: Double, data: String ->
      require(data.length<=349528 && offset.isFinite() && offset==offset.toLong().toDouble())
      soundFiles.write(token,offset.toLong(),Base64.decode(data,Base64.NO_WRAP)); true
    }
    AsyncFunction("ncSoundscapeFileFinish") { token: String -> soundFiles.finish(token) }
    AsyncFunction("ncSoundscapeFileForget") { token: String -> soundFiles.forget(token); true }
    AsyncFunction("ncSoundscapeImportInfo") { uri: String ->
      val file=soundImportFile(uri); val digest=MessageDigest.getInstance("SHA-256"); var bytes=0L
      file.inputStream().use { input ->
        val buffer=ByteArray(256*1024)
        while(true) {
          val count=input.read(buffer); if(count<0)break
          bytes+=count; require(bytes<=100L*1024*1024); digest.update(buffer,0,count)
        }
      }
      mapOf("sha256" to digest.digest().joinToString(""){"%02x".format(it)},"byte_length" to bytes)
    }
    AsyncFunction("ncSoundscapeImportRead") { uri: String, offset: Double, length: Int ->
      val file=soundImportFile(uri)
      require(offset.isFinite() && offset>=0 && offset==offset.toLong().toDouble() && length in 1..256*1024 && offset+length<=file.length())
      val data=ByteArray(length)
      RandomAccessFile(file,"r").use { input -> input.seek(offset.toLong()); input.readFully(data) }
      mapOf("data" to Base64.encodeToString(data,Base64.NO_WRAP),
        "sha256" to MessageDigest.getInstance("SHA-256").digest(data).joinToString(""){"%02x".format(it)})
    }
    AsyncFunction("ncSoundscapeBeginLoad") { payload: Map<String,Any?> ->
      runOnMain { soundscape?.begin(soundScope(payload),payload["layer"] as String) ?: -1L }
    }
    AsyncFunction("ncSoundscapeApply") { payload: Map<String,Any?> ->
      val scope=soundScope(payload)
      val layer=payload["layer"] as String
      val token=(payload["load_token"] as Number).toLong()
      val volume=(payload["volume"] as Number).toFloat()
      val muted=payload["muted"] as Boolean
      val loop=payload["loop"] as Boolean
      val file=(payload["file_token"] as? String)?.let { soundFiles.acquire(it) }
      runOnMain {
        val current=soundscape
        if(current==null) { file?.let { soundWorker.execute { soundFiles.release(it) } }; false }
        else current.apply(scope,layer,token,file,volume,muted,loop)
      }
    }
    AsyncFunction("ncSoundscapeResume") { payload: Map<String,Any?>, promise: Promise ->
      runOnMain { val current=soundscape; if(current==null) promise.resolve(false)
        else current.resume(soundScope(payload)) { promise.resolve(it) } }
    }
    AsyncFunction("ncSoundscapePreview") { payload: Map<String,Any?>, promise: Promise ->
      val scope=soundScope(payload)
      val token=(payload["load_token"] as Number).toLong()
      val volume=(payload["volume"] as? Number)?.toFloat() ?: 1f
      val file=soundFiles.acquire(payload["file_token"] as String)
      runOnMain { val current=soundscape; if(current==null) { soundWorker.execute { soundFiles.release(file) }; promise.resolve(false) }
        else current.preview(scope,token,file,volume,payload["mix_background"] as? Boolean ?: false) { promise.resolve(it) } }
    }
    AsyncFunction("ncSoundscapeStopPreview") { payload: Map<String,Any?> -> runOnMain { soundscape?.stopPreview(soundScope(payload)) } }
    AsyncFunction("ncSoundscapePreviewPlaying") { payload: Map<String,Any?>, promise: Promise ->
      val scope=soundScope(payload); val playing=payload["playing"] as Boolean
      runOnMain { val current=soundscape; if(current==null) promise.resolve(false)
        else current.previewPlaying(scope,playing) { promise.resolve(it) } }
    }
    AsyncFunction("ncSoundscapePause") { payload: Map<String,Any?> -> runOnMain {
      if(soundscape?.activate(soundScope(payload))==true) soundscape?.pause(payload["reason"] as? String ?: "user")
    } }
    AsyncFunction("ncSoundscapeClose") { payload: Map<String,Any?> -> runOnMain { soundscape?.close(soundScope(payload)) } }
    AsyncFunction("ncSoundscapeSpeech") { payload: Map<String,Any?> -> runOnMain {
      soundscape?.speech(soundScope(payload),payload["reply_id"] as String,payload["audible"] as Boolean,payload["terminal"] as Boolean)
    } }
    AsyncFunction("ncSoundscapeDuck") { payload: Map<String,Any?> -> runOnMain { soundscape?.duck(soundScope(payload),payload["enabled"] as Boolean) } }

  }

  override fun definition() = ModuleDefinition {
    Name("ExpoAudio")
    manualDepartureFunctions()

    Function("ncDiagnosticVersion") { 1 }
    Function("ncDiagnosticPeek") { limit:Int -> ncDiagnostics.peek(limit) }
    Function("ncDiagnosticAck") { ids:List<String> -> ncDiagnostics.ack(ids) }
    Function("ncDiagnosticConfigure") { value:Map<String,Any?> -> ncDiagnostics.configurePolicy(value) }
    Function("ncDiagnosticPolicyStatus") { mapOf("status" to "applied","policy" to ncDiagnosticPolicy.snapshot()) }

    OnCreate {
      ncDiagnosticObserver.lifecycle("created")
      audioManager = appContext.reactContext?.getSystemService(Context.AUDIO_SERVICE) as AudioManager
      audioManager.registerAudioDeviceCallback(audioRouteCallback, null)
      manualApplication=context.applicationContext as? Application
      manualApplication?.registerActivityLifecycleCallbacks(manualLifecycle)
      ContextCompat.registerReceiver(context,manualScreenReceiver,IntentFilter(Intent.ACTION_SCREEN_OFF),ContextCompat.RECEIVER_NOT_EXPORTED)
      ContextCompat.registerReceiver(context, noisyReceiver, IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY), ContextCompat.RECEIVER_NOT_EXPORTED)
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) audioManager.registerAudioPlaybackCallback(playbackCallback, focusResumeHandler)
      soundFiles=NCSoundscapeFiles(File(context.cacheDir,"nc-soundscape"))
      soundscape=NCSoundscapeController(context,soundFiles,soundWorker,
        { requestAudioFocus(); when {
          !audioEnabled -> -1
          focusLifecycle.isAcquired() || interruptionMode == InterruptionMode.MIX_WITH_OTHERS -> 1
          focusLifecycle.currentRequest()!=null -> 0
          else -> -1
        } },
        { if(shouldReleaseFocus()) releaseAudioFocus() }, { sendEvent("soundscapeState",it) })
    }

    soundscapeFunctions()

    Function("ncOrderedIdleCacheVersion") { 1 }
    AsyncFunction("ncOrderedIdleCacheAcquire") { scope: String, digest: String, bytes: Long, epoch: Long ->
      orderedIdleCache.acquire(scope, digest, bytes, epoch)
    }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncOrderedIdleCacheImport") { scope: String, digest: String, bytes: Long, epoch: Long, uri: String ->
      orderedIdleCache.importFile(scope, digest, bytes, epoch, uri)
    }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncOrderedIdleCacheRelease") { pin: String -> orderedIdleCache.release(pin) }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncOrderedIdleCacheClear") { scope: String, epoch: Long, force: Boolean -> orderedIdleCache.clear(scope, epoch, force) }.runOnQueue(appContext.backgroundCoroutineScope)
    AsyncFunction("ncOrderedIdleCacheUsage") { orderedIdleCache.usage() }.runOnQueue(appContext.backgroundCoroutineScope)
    Function("ncProgressivePcmVersion") { 1 }
    Function("ncProgressivePcmOpen") { progressivePcm.open() }
    Function("ncProgressivePcmAppend") { id: String, cursor: Double, encoded: String ->
      require(cursor.isFinite() && cursor >= 0 && cursor <= NCProgressivePcmQueue.MAX_TOTAL_FRAMES &&
        cursor == cursor.toLong().toDouble()) { "progressive_pcm_cursor" }
      require(encoded.isNotEmpty() && encoded.length <= NCProgressivePcmQueue.MAX_APPEND_FRAMES * 8 / 3) {
        "progressive_pcm_append_size"
      }
      progressivePcm.requireSource(id).append(cursor.toLong(), Base64.decode(encoded, Base64.DEFAULT))
    }
    Function("ncProgressivePcmFinish") { id: String, totalFrames: Double ->
      require(totalFrames.isFinite() && totalFrames >= 0 && totalFrames <= NCProgressivePcmQueue.MAX_TOTAL_FRAMES &&
        totalFrames == totalFrames.toLong().toDouble()) { "progressive_pcm_final_cursor" }
      progressivePcm.requireSource(id).finish(totalFrames.toLong())
    }
    Function("ncProgressivePcmClose") { id: String -> progressivePcm.close(id) }
    Function("ncPlaybackGuardVersion") { NCPlaybackGuard.VERSION }
    Function("ncContinuousMuxedFixtureVersion") {
      if(context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE!=0 && continuousFixtureBuild())1 else 0
    }
    // Compilation/state fixtures are not hardware proof or live capability.
    Function("ncContinuousMuxedQueueVersion") {
      NCContinuousMuxedRpc.LIVE_VERSION
    }
    Function("ncOrderedMuxedQueueVersion") { NCContinuousMuxedRpc.ORDERED_VERSION }
    Function("ncOrderedPlaybackClockVersion") { 1 }
    Function("ncOrderedUserPauseVersion") { 1 }
    Function("ncOrderedContinuationVersion") { NCContinuousMuxedRpc.ORDERED_CONTINUATION_VERSION }
    AsyncFunction("ncPreparePlaybackRoute") { ticket: String ->
      NCCaptureRoute.preparePlayback(audioManager, ticket, {
        ContextCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED
      }, { NCPlaybackGuard.shared.currentTicket() == ticket && NCPlaybackGuard.shared.isOpen(ticket) })
    }.runOnQueue(appContext.backgroundCoroutineScope)
    Function("ncMuxedPresentationProbeVersion") {
      if(context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE!=0)1 else 0
    }
    Function("ncMuxedTrialVersion") {
      2
    }
    Function("ncMuxedChunkStreamVersion") {
      1
    }
    Function("ncMuxedSourceFenceVersion") {
      1
    }
    Function("ncMuxedContinuationVersion") {
      1
    }
    Function("ncPhoneReplyReceiptVersion") { NCPlaybackGuard.PHONE_REPLY_RECEIPT_VERSION }
    Function("ncFreezePhoneReplyReceipt") { ticket: String, requestId: String, interruptionId: String ->
      NCPlaybackGuard.shared.freezePhoneReplyReceipt(ticket, requestId, interruptionId)?.payload()
    }
    Function("ncSkipPhoneReplyAudio") { ticket: String, requestId: String ->
      NCPlaybackGuard.shared.skipPhoneReplyAudio(ticket, requestId)
    }
    Function("ncFinishPhoneReplyAudio") { ticket: String, requestId: String ->
      NCPlaybackGuard.shared.finishPhoneReplyAudio(ticket, requestId)
    }

    AsyncFunction("setAudioModeAsync") { mode: AudioMode ->
      staysActiveInBackground = mode.shouldPlayInBackground
      interruptionMode = mode.interruptionMode
      updatePlaySoundThroughEarpiece(mode.shouldRouteThroughEarpiece ?: false)
      allowsBackgroundRecording = mode.allowsBackgroundRecording

      recorders.values.forEach { recorder ->
        recorder.useForegroundService = allowsBackgroundRecording
      }
    }

    AsyncFunction("setIsAudioActiveAsync") { enabled: Boolean ->
      audioEnabled = enabled
      if (!enabled) {
        NCPlaybackGuard.shared.retireProtected(NCPlaybackGuard.RetirementCause.AUDIO_DISABLED)
        releaseAudioFocus()
        runOnMain {
          soundscape?.pause("user")
          players.values.forEach {
            it.ncFenceContinuousControl("audio_disabled")
            if (it.ref.isPlaying) {
              it.ref.pause()
            }
          }
        }
      }
    }

    AsyncFunction("requestRecordingPermissionsAsync") { promise: Promise ->
      Permissions.askForPermissionsWithPermissionsManager(appContext.permissions, promise, Manifest.permission.RECORD_AUDIO)
    }

    AsyncFunction("getRecordingPermissionsAsync") { promise: Promise ->
      Permissions.getPermissionsWithPermissionsManager(appContext.permissions, promise, Manifest.permission.RECORD_AUDIO)
    }

    OnActivityEntersBackground {
      NCCaptureRoute.setForeground(false)
      observeManualDeparture(false)
      soundscape?.background()
      if (!staysActiveInBackground) {
        NCPlaybackGuard.shared.retireForegroundOnly()
        // Only service-confirmed replies and independently retained ordered output continue.
        if (!NCPlaybackGuard.shared.retainsBackgroundFocus() && soundscape?.holdsFocus != true) releaseAudioFocus()
        players.values.forEach { player ->
          if (player.ref.isPlaying && !player.ncPlaybackBinding.allowsBackgroundPlayback()) {
            player.isPaused = true
            player.ref.pause()
          }
        }

        recorders.values.forEach { recorder ->
          if (recorder.isRecording) {
            recorder.pauseRecording()
          }
        }
      }
    }

    OnActivityEntersForeground {
      NCCaptureRoute.setForeground(true)
      soundscape?.foreground()
      if (!staysActiveInBackground) {
        val hasPlayersToResume = players.values.any { it.isPaused && !it.focusInterrupted }
        if (hasPlayersToResume) {
          requestAudioFocus()
        }

        players.values.forEach { player ->
          if (player.isPaused && !player.focusInterrupted) {
            player.isPaused = false
            player.ncGuardedPlay()
          }
        }

        recorders.values.forEach { recorder ->
          if (recorder.isPaused && manualDeparture.current()?.recorderId!=recorder.id) {
            recorder.record()
          }
        }

        if (shouldRouteThroughEarpiece) {
          updatePlaySoundThroughEarpiece(true)
        }
      }
    }

    OnDestroy {
      progressivePcm.closeAll()
      NCCaptureRoute.setForeground(false)
      manualApplication?.unregisterActivityLifecycleCallbacks(manualLifecycle)
      manualApplication=null
      try {context.unregisterReceiver(manualScreenReceiver)} catch (_:Exception) {}
      if (orderedIdleCacheDelegate.isInitialized()) Thread { orderedIdleCache.close() }.start()
      ncDiagnosticObserver.lifecycle("destroyed")
      appContext.mainQueue.launch {
        soundscape?.destroy(); soundscape=null
        soundWorker.execute { soundFiles.close() }; soundWorker.shutdown()
        audioManager.unregisterAudioDeviceCallback(audioRouteCallback)
        context.unregisterReceiver(noisyReceiver)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) audioManager.unregisterAudioPlaybackCallback(playbackCallback)
        focusResumeTicket = null
        NCPlaybackGuard.shared.retireProtected(NCPlaybackGuard.RetirementCause.OTHER)
        releaseAudioFocus()
        players.values.forEach {
          it.ncFenceContinuousControl("module_destroyed")
          it.ref.stop()
        }

        recorders.values.forEach {
          it.stopRecording()
        }

        AudioControlsService.clearSession()
      }
    }

    View(NCMuxedTrialView::class) {
      Events("onReady")
      Prop("player") { view:NCMuxedTrialView, player:AudioPlayer? -> view.attach(player) }
    }

    Class(AudioPlayer::class) {
      Constructor { source: AudioSource?, updateInterval: Double, keepAudioSessionActive: Boolean ->
        val mediaSource = createMediaItem(source)
        runOnMain {
          val player = AudioPlayer(
            context,
            appContext,
            mediaSource,
            updateInterval
          )
          player.onPlaybackStateChange = { isPlaying ->
            if (!isPlaying && shouldReleaseFocus()) {
              releaseAudioFocus()
            }
          }
          players[player.id] = player
          player
        }
      }

      Property("id") { player ->
        player.id
      }

      Property("isBuffering") { player ->
        runOnMain {
          player.ref.playbackState == Player.STATE_BUFFERING
        }
      }

      Property("currentStatus") { player ->
        runOnMain {
          player.currentStatus()
        }
      }

      Property("isAudioSamplingSupported") { _ ->
        true
      }

      Property("loop") { player ->
        runOnMain {
          player.ref.repeatMode == Player.REPEAT_MODE_ONE
        }
      }.set { player, isLooping: Boolean ->
        runOnMain {
          player.ncFenceContinuousControl("public_loop")
          player.ref.repeatMode = if (isLooping) {
            Player.REPEAT_MODE_ONE
          } else {
            Player.REPEAT_MODE_OFF
          }
        }
      }

      Property("isLoaded") { player ->
        runOnMain {
          player.ref.playbackState == Player.STATE_READY
        }
      }

      Property("playing") { player ->
        runOnMain {
          player.ref.isPlaying
        }
      }

      Property("paused") { player ->
        runOnMain {
          !player.ref.isPlaying
        }
      }

      Property("muted") { player ->
        player.isMuted
      }.set { player, muted: Boolean? ->
        val newMuted = muted ?: false
        player.isMuted = newMuted
        player.setVolume(if (newMuted) 0f else player.previousVolume)
      }

      Property("shouldCorrectPitch") { player ->
        player.preservesPitch
      }.set { player, preservesPitch: Boolean ->
        player.preservesPitch = preservesPitch
      }

      Property("currentTime") { player ->
        runOnMain {
          player.currentTime
        }
      }

      Property("duration") { player ->
        runOnMain {
          player.duration
        }
      }

      Property("playbackRate") { player ->
        runOnMain {
          player.ref.playbackParameters.speed
        }
      }

      Property("volume") { player ->
        runOnMain {
          player.ref.volume
        }
      }.set { ref, volume: Float? ->
        ref.setVolume(volume)
      }

      Function("play") { player: AudioPlayer ->
        if (!audioEnabled) {
          Log.e(TAG, "Audio has been disabled. Re-enable to start playing")
          return@Function
        }
        runOnMain {
          if (!focusLifecycle.isAcquired()) {
            requestAudioFocus()
          }
          player.ncGuardedPlay()
        }
      }

      Function("pause") { player: AudioPlayer ->
        runOnMain {
          player.ncGuardedPause()
        }
      }

      Function("replace") { player: AudioPlayer, source: AudioSource ->
        runOnMain {
          if (player.ref.availableCommands.contains(Player.COMMAND_CHANGE_MEDIA_ITEMS)) {
            val mediaSource = createMediaItem(source)
            val wasPlaying = player.ref.isPlaying
            mediaSource?.let {
              if (player.ncGuardedReplace(it) && wasPlaying) {
                if (!focusLifecycle.isAcquired()) {
                  requestAudioFocus()
                }
              }
            }
          }
        }
      }

      Function("setActiveForLockScreen") { ref: AudioPlayer, active: Boolean, metadata: Metadata?, options: AudioLockScreenOptions? ->
        runOnMain {
          ref.setActiveForLockScreen(active, metadata, options)
        }
      }

      Function("updateLockScreenMetadata") { ref: AudioPlayer, metadata: Metadata ->
        runOnMain {
          ref.updateLockScreenMetadata(metadata)
        }
      }

      Function("clearLockScreenControls") { ref: AudioPlayer ->
        runOnMain {
          ref.clearLockScreenControls()
        }
      }

      Function("setAudioSamplingEnabled") { player: AudioPlayer, enabled: Boolean ->
        runOnMain {
          player.setSamplingEnabled(enabled)
        }
      }

      AsyncFunction("seekTo") { player: AudioPlayer, seekTime: Double, _: Double?, _: Double? ->
        check(player.ref.currentMediaItem?.localConfiguration?.uri?.scheme != NCProgressivePcmMediaSource.SCHEME) {
          "progressive_pcm_unseekable"
        }
        player.seekTo(seekTime)
      }.runOnQueue(Queues.MAIN)

      Function("setPlaybackRate") { player: AudioPlayer, rate: Float ->
        appContext.mainQueue.launch {
          if (player.ref.currentMediaItem?.localConfiguration?.uri?.scheme == NCProgressivePcmMediaSource.SCHEME)
            return@launch
          player.ncFenceContinuousControl("public_rate")
          val playbackRate = if (rate <= 0) 0.1f else min(rate, 2.0f)
          val pitch = if (player.preservesPitch) 1f else playbackRate
          player.ref.playbackParameters = PlaybackParameters(playbackRate, pitch)
        }
      }

      Function("remove") { player: AudioPlayer ->
        runOnMain {
          player.ncFenceContinuousControl("registry_remove")
          players.remove(player.id)
        }
      }

      Function("ncBindPlaybackTicket") { player: AudioPlayer, ticket: String ->
        player.ncBindPlaybackTicket(ticket)
      }

      Function("ncBindPhoneReplyChunk") { player: AudioPlayer, ticket: String, requestId: String, chunkId: String ->
        player.ncBindPhoneReplyChunk(ticket, requestId, chunkId)
      }
      Function("ncContinuousMuxedPresentationSnapshot") { player:AudioPlayer ->
        runOnMain {
          if(players[player.id]!==player)null
          else player.ncContinuousPresentation.snapshot()
        }
      }

      AsyncFunction("ncPrepareMuxedTrial") { player:AudioPlayer, files:List<Map<String,Any>>,
          ticket:String, request:String, chunk:String, frames:Int, samples:Long ->
        val revision=runOnMain { player.ncMuxedTrialRevision }
        val clips=NCMuxedTrialPlayer.validate(context,files,frames,samples)
        runOnMain {
          if(players[player.id]!==player || player.ncMuxedTrialRetired || player.ncMuxedTrialOwner!=null
            || player.ncMuxedTrialRevision!=revision) false
          else NCMuxedTrialPlayer.prepare(context,player,clips,ticket,request,chunk)?.let {
            player.ncMuxedTrialOwner=it;true
          }?:false
        }
      }
      AsyncFunction("ncCloseMuxedTrial") { player:AudioPlayer ->
        val rpc=continuousRpcs[player]
        if(rpc!=null && !rpc.closeOwned())return@AsyncFunction false
        val fences=runOnMain {player.ncCloseMuxedTrial();player.ncRetiredMuxedReaderFences()}
        NCMuxedTrialReaderFence.awaitAll(fences)
      }
      AsyncFunction("ncOpenContinuousMuxed") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.open") {continuousRpc(player).open(it)} }
      orderedFunctions()
      Function("ncEnableContinuousMuxedFixture") { player:AudioPlayer ->
        runOnMain {players[player.id]===player && player.ncEnableContinuousFixture(
          context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE!=0 && continuousFixtureBuild())}
      }
      AsyncFunction("ncStageContinuousMuxed") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.stage") {continuousRpc(player).stage(it)} }
      AsyncFunction("ncAppendContinuousMuxed") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.append") {continuousRpc(player).append(it)} }
      AsyncFunction("ncStageContinuousMuxedReturn") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.stage_return") {continuousRpc(player).stageReturn(it)} }
      AsyncFunction("ncStageContinuousMuxedVisual") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.stage_visual") {continuousRpc(player).stageVisual(it)} }
      AsyncFunction("ncAppendContinuousMuxedReturn") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.append_return") {continuousRpc(player).appendReturn(it)} }
      AsyncFunction("ncPruneContinuousMuxedVisual") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.prune_visual") {continuousRpc(player).pruneVisual(it)} }
      AsyncFunction("ncReadContinuousMuxed") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.read") {continuousRpc(player).read(it)} }
      AsyncFunction("ncAcknowledgeContinuousMuxed") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.acknowledge") {continuousRpc(player).acknowledge(it)} }
      AsyncFunction("ncSealContinuousMuxed") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.seal") {continuousRpc(player).seal(it)} }
      AsyncFunction("ncRetireContinuousMuxedSource") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.retire_source") {continuousRpc(player).retireSource(it)} }
      AsyncFunction("ncRetireContinuousMuxedRun") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.retire_run") {continuousRpc(player).retireRun(it)} }
      AsyncFunction("ncInvalidateContinuousMuxed") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.invalidate") {continuousRpc(player).invalidate(it)} }
      AsyncFunction("ncDropContinuousMuxedStage") { player:AudioPlayer,value:Map<String,Any> -> NCDiagnosticPlayerObserver(player.id).rpc(value,"native.rpc.drop") {continuousRpc(player).drop(it)} }
      AsyncFunction("ncPrepareMuxedPresentationFixture") { player:AudioPlayer,files:List<Map<String,Any>>,
          ticket:String,request:String,chunk:String,frames:Int,samples:Long,groups:List<Int> ->
        check(context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE!=0)
        val revision=runOnMain {player.ncMuxedTrialRevision}
        val clips=NCMuxedTrialPlayer.validate(context,files,frames,samples)
        NCContinuousMuxedFixtureLayout.split(groups,clips.map {it.frames},clips.map {it.samples})
        runOnMain {
          if(players[player.id]!==player || player.ncMuxedTrialRetired || player.ncMuxedTrialOwner!=null
            || player.ncMuxedTrialRevision!=revision)false
          else NCMuxedTrialPlayer.prepare(context,player,clips,ticket,request,chunk,groups.toList())?.let {
            player.ncMuxedTrialOwner=it;true
          }?:false
        }
      }
      Function("ncEnableMuxedTrialSession") { player:AudioPlayer ->
        runOnMain {players[player.id]===player && player.ncEnableMuxedTrialSession(true)}
      }
      Function("ncMuxedSourceRevision") { player:AudioPlayer ->
        runOnMain { if(players[player.id]===player && !player.ncMuxedTrialRetired)player.ncMuxedTrialRevision else -1L }
      }
      AsyncFunction("ncRetireMuxedSource") { player:AudioPlayer,revision:Long ->
        val fences=runOnMain {
          if(players[player.id]!==player||player.ncMuxedTrialRevision!=revision||!player.ncRetireMuxedSource())null
          else player.ncRetiredMuxedReaderFences()
        }
        fences!=null&&NCMuxedTrialReaderFence.awaitAll(fences)
      }
      AsyncFunction("ncStageMuxedEpoch") { player:AudioPlayer,files:List<Map<String,Any>>,ticket:String,
          request:String,chunk:String,frames:Int,samples:Long,revision:Long ->
        val clips=NCMuxedTrialPlayer.validate(context,files,frames,samples)
        runOnMain {
          if(players[player.id]!==player || player.ncMuxedTrialRetired || !player.ncMuxedTrialSessionEnabled
            || player.ncMuxedTrialRevision!=revision || NCPlaybackGuard.shared.currentTicket()!=ticket)null
          else player.ncMuxedTrialStaging.stage(player.id,revision,player.ncMuxedTrialOwner!=null,
            NCMuxedTrialPlayer.Prepared(clips,ticket,request,chunk))
        }
      }
      AsyncFunction("ncStageMuxedStream") { player:AudioPlayer,files:List<Map<String,Any>>,ticket:String,
          request:String,chunk:String,totalFrames:Int,totalSamples:Long,revision:Long ->
        val plan=NCMuxedTrialStreamRanges.Plan(totalFrames,totalSamples)
        val clips=NCMuxedTrialPlayer.validateStream(context,files,0,plan,prefix=true)
        runOnMain {
          if(players[player.id]!==player||player.ncMuxedTrialRetired||!player.ncMuxedTrialSessionEnabled
            ||player.ncMuxedTrialRevision!=revision||NCPlaybackGuard.shared.currentTicket()!=ticket)null
          else player.ncMuxedTrialStaging.stage(player.id,revision,player.ncMuxedTrialOwner!=null,
            NCMuxedTrialPlayer.Prepared(clips,ticket,request,chunk,plan))
        }
      }
      Function("ncDropMuxedEpoch") { player:AudioPlayer,token:String ->
        runOnMain { player.ncMuxedTrialStaging.drop(token) }
      }
      AsyncFunction("ncInstallMuxedEpoch") { player:AudioPlayer,token:String,revision:Long ->
        runOnMain {
          val prepared=if(players[player.id]===player && !player.ncMuxedTrialRetired && player.ncMuxedTrialSessionEnabled
            && player.ncMuxedTrialRevision==revision && player.ncMuxedTrialOwner==null)
            player.ncMuxedTrialStaging.take(token,player.id,revision) else null
          if(prepared==null || NCPlaybackGuard.shared.currentTicket()!=prepared.ticket)false
          else (if(prepared.stream==null)
            NCMuxedTrialPlayer.prepare(context,player,prepared.clips,prepared.ticket,prepared.request,prepared.chunk)
          else NCMuxedTrialPlayer.prepareStream(context,player,prepared.clips,prepared.ticket,
            prepared.request,prepared.chunk,prepared.stream))?.let {
            player.ncMuxedTrialOwner=it;true
          }?:false
        }
      }
      AsyncFunction("ncContinueMuxedEpoch") { player:AudioPlayer,token:String,revision:Long,promise:Promise ->
        val deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(5000)
        val completed=CountDownLatch(1)
        val successor=AtomicReference<NCMuxedTrialPlayer?>()
        val outgoingFence=AtomicReference<NCMuxedTrialReaderFence?>()
        val prepared=AtomicReference<NCMuxedTrialPlayer.Prepared?>()
        val mutated=runOnMain {
          val owner=player.ncMuxedTrialOwner
          val value=if(players[player.id]===player&&!player.ncMuxedTrialRetired
            &&player.ncMuxedTrialSessionEnabled&&player.ncMuxedTrialRevision==revision
            &&revision<Long.MAX_VALUE&&owner!=null)
            player.ncMuxedTrialStaging.take(token,player.id,revision+1) else null
          prepared.set(value)
          if(value==null||owner==null||NCPlaybackGuard.shared.currentTicket()!=value.ticket)false
          else owner.continueEpoch(context,value,{players[player.id]===player}){accepted,next,fence->
            if(accepted){successor.set(next);outgoingFence.set(fence)}
            completed.countDown()
          }
        }
        val timeline=mutated&&try {completed.await((deadline-System.nanoTime()).coerceAtLeast(0),TimeUnit.NANOSECONDS)}
          catch(_:InterruptedException){Thread.currentThread().interrupt();false}
        val fence=if(timeline)outgoingFence.get() else null
        val closed=fence?.awaitClosed(TimeUnit.NANOSECONDS.toMillis((deadline-System.nanoTime()).coerceAtLeast(0)))==true
        val accepted=closed&&runOnMain {
          val value=prepared.get()
          players[player.id]===player&&!player.ncMuxedTrialRetired&&player.ncMuxedTrialSessionEnabled
            &&player.ncMuxedTrialRevision==revision+1&&player.ncMuxedTrialOwner===successor.get()
            &&successor.get()!=null&&value!=null&&NCPlaybackGuard.shared.currentTicket()==value.ticket
            &&player.ncPlaybackBinding.ticket==value.ticket&&player.ncPlaybackBinding.requestId==value.request
            &&player.ncPlaybackBinding.chunkId==value.chunk&&player.ncMuxedTrialReceipt?.observe()!=null
            &&!player.ref.isPlaying&&!player.ref.playWhenReady
            &&value.clips.all {it.file.isFile&&it.file.length()==it.bytes}
        }
        if(!accepted&&mutated)runOnMain {if(players[player.id]===player&&!player.ncMuxedTrialRetired)player.ncCloseMuxedTrial()}
        promise.resolve(accepted)
      }
      AsyncFunction("ncAppendMuxedStream") { player:AudioPlayer,files:List<Map<String,Any>>,
          first:Int,revision:Long,promise:Promise ->
        val owner=runOnMain {player.ncMuxedTrialOwner}
        val plan=owner?.streamPlan
        if(plan==null)promise.resolve(false)
        else {
          val clips=NCMuxedTrialPlayer.validateStream(context,files,first,plan)
          runOnMain {
            val ticket=player.ncPlaybackBinding.ticket
            val request=player.ncPlaybackBinding.requestId
            val chunk=player.ncPlaybackBinding.chunkId
            if(players[player.id]!==player||player.ncMuxedTrialRetired||!player.ncMuxedTrialSessionEnabled
              ||player.ncMuxedTrialRevision!=revision||player.ncMuxedTrialOwner!==owner
              ||owner.streamPlan!==plan||ticket==null||request==null||chunk==null
              ||NCPlaybackGuard.shared.currentTicket()!=ticket||player.ncMuxedTrialReceipt?.observe()==null
              ||!owner.appendStream(context,clips,first){confirmed->
                promise.resolve(confirmed&&players[player.id]===player&&!player.ncMuxedTrialRetired
                  &&player.ncMuxedTrialSessionEnabled&&player.ncMuxedTrialRevision==revision
                  &&player.ncMuxedTrialOwner===owner&&owner.streamPlan===plan
                  &&player.ncPlaybackBinding.ticket==ticket&&player.ncPlaybackBinding.requestId==request
                  &&player.ncPlaybackBinding.chunkId==chunk&&NCPlaybackGuard.shared.currentTicket()==ticket
                  &&player.ncMuxedTrialReceipt?.observe()!=null)
              })promise.resolve(false)
          }
        }
      }
      AsyncFunction("ncPrepareMuxedEpoch") { player:AudioPlayer,files:List<Map<String,Any>>,ticket:String,
          request:String,chunk:String,frames:Int,samples:Long,revision:Long ->
        val clips=NCMuxedTrialPlayer.validate(context,files,frames,samples)
        runOnMain {
          if(players[player.id]!==player || player.ncMuxedTrialRetired || !player.ncMuxedTrialSessionEnabled
            || player.ncMuxedTrialRevision!=revision || player.ncMuxedTrialOwner!=null)false
          else NCMuxedTrialPlayer.prepare(context,player,clips,ticket,request,chunk)?.let {
            player.ncMuxedTrialOwner=it;true
          }?:false
        }
      }
      AsyncFunction("ncPrepareMuxedIdle") { player:AudioPlayer, files:List<Map<String,Any>>,ticket:String,first:Int,revision:Long ->
        val values=NCMuxedTrialSamples.idleRows(files,first)
        val clips=NCMuxedTrialPlayer.validate(context,values,values.size*12,values.size*24000L)
        runOnMain {
          if(players[player.id]!==player || player.ncMuxedTrialRevision!=revision || player.ncMuxedTrialRetired
            || player.ncMuxedTrialOwner!=null)false
          else NCMuxedTrialPlayer.prepareIdle(context,player,clips,ticket,first)?.let {
            player.ncMuxedTrialOwner=it;true
          }?:false
        }
      }
      AsyncFunction("ncAppendMuxedIdle") { player:AudioPlayer, files:List<Map<String,Any>>,first:Int,revision:Long ->
        val owner=runOnMain { player.ncMuxedTrialOwner }
        val values=NCMuxedTrialSamples.idleRows(files,first)
        val clips=NCMuxedTrialPlayer.validate(context,values,values.size*12,values.size*24000L)
        runOnMain {
          players[player.id]===player && !player.ncMuxedTrialRetired && player.ncMuxedTrialOwner===owner
            && player.ncMuxedTrialRevision==revision && owner?.appendIdle(context,clips,first)==true
        }
      }
      Function("ncMuxedIdlePosition") { player:AudioPlayer ->
        runOnMain {if(players[player.id]===player && !player.ncMuxedTrialRetired)player.ncMuxedTrialOwner?.idlePosition() else null}
      }
      AsyncFunction("ncSealMuxedIdle") { player:AudioPlayer,files:List<Map<String,Any>>,target:Int,frames:Int,revision:Long,promise:Promise ->
        val owner=runOnMain {player.ncMuxedTrialOwner}
        val count=files.sumOf {(it["frameCount"] as? Number)?.toInt()?:0}
        val clips=if(files.isEmpty())emptyList() else NCMuxedTrialPlayer.validate(context,files,count,count*2000L)
        runOnMain {
          if(players[player.id]!==player||player.ncMuxedTrialRetired||player.ncMuxedTrialRevision!=revision
            ||player.ncPlaybackBinding.ticket==null||player.ncPlaybackBinding.ticket!=NCPlaybackGuard.shared.currentTicket()
            ||player.ncMuxedTrialOwner!==owner||owner==null
            ||!owner.sealIdle(context,target,frames,clips){confirmed->promise.resolve(confirmed
              &&players[player.id]===player&&player.ncMuxedTrialRevision==revision&&player.ncMuxedTrialOwner===owner)})promise.resolve(false)
        }
      }
      Function("ncMuxedSilentEnded") { player:AudioPlayer,revision:Long ->
        runOnMain {players[player.id]===player&&!player.ncMuxedTrialRetired&&player.ncMuxedTrialRevision==revision
          &&player.ncMuxedTrialOwner?.silentEnded==true}
      }
      AsyncFunction("ncPruneMuxedIdle") { player:AudioPlayer,cursor:Int,revision:Long,promise:Promise ->
        // Timeline callback and file-reader closure share one bounded wait on
        // the background module queue. Never wait on the player's looper.
        val deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(5000)
        val completed=CountDownLatch(1)
        val removed=AtomicReference<List<NCMuxedTrialReaderFence.Child>?>()
        val owner=runOnMain {
          val current=player.ncMuxedTrialOwner
          if(players[player.id]!==player||player.ncMuxedTrialRetired||player.ncMuxedTrialRevision!=revision||current==null
            ||!current.pruneIdle(cursor){confirmed,children->
              if(confirmed)removed.set(children)
              completed.countDown()
            })completed.countDown()
          current
        }
        val timelineClosed=try {completed.await((deadline-System.nanoTime()).coerceAtLeast(0),TimeUnit.NANOSECONDS)}
          catch(_:InterruptedException){Thread.currentThread().interrupt();false}
        val children=if(timelineClosed)removed.get() else null
        val closed=children!=null&&NCMuxedTrialReaderFence.awaitChildren(children,
          TimeUnit.NANOSECONDS.toMillis((deadline-System.nanoTime()).coerceAtLeast(0)))
        promise.resolve(closed&&runOnMain {players[player.id]===player&&!player.ncMuxedTrialRetired
          &&player.ncMuxedTrialRevision==revision&&player.ncMuxedTrialOwner===owner})
      }
    }

    recorderFunctions()
  }

  private fun createMediaItem(source: AudioSource?): MediaSource? = source?.uri?.let { uriString ->
    val uri = uriString.toUri()
    if (uri.scheme == NCProgressivePcmMediaSource.SCHEME)
      return@let NCProgressivePcmMediaSource.create(progressivePcm, uri)
    val mediaItem = when {
      isRawResource(uri) -> {
        val file = getResourceName(uri, uriString)
        MediaItem.fromUri(getRawResourceURI(file))
      }
      else -> MediaItem.fromUri(uri)
    }

    val factory = when (uri.scheme) {
      "http", "https" -> httpDataSourceFactory(source.headers)
      else -> DefaultDataSource.Factory(context)
    }
    return buildMediaSourceFactory(factory, mediaItem)
  }

  private fun httpDataSourceFactory(headers: Map<String, String>?): DataSource.Factory {
    return OkHttpDataSource.Factory(httpClient).apply {
      headers?.let { headers ->
        setDefaultRequestProperties(headers)
      }
    }
  }

  private fun isRawResource(uri: Uri): Boolean =
    uri.scheme == null || (uri.scheme == "file" && uri.path?.startsWith("/android_res/raw/") == true)

  private fun getResourceName(uri: Uri, fallback: String): String =
    if (uri.scheme == null) {
      fallback
    } else {
      uri.path?.substringAfterLast("/")?.substringBeforeLast(".") ?: fallback
    }

  private fun getRawResourceURI(file: String): Uri {
    val resId = context.resources.getIdentifier(file, "raw", context.packageName)

    return when {
      resId == 0 ->
        Uri.fromFile(File(file))
      else ->
        Uri.Builder()
          .scheme(ContentResolver.SCHEME_ANDROID_RESOURCE)
          .authority(context.packageName)
          .appendPath("raw")
          .appendPath(file)
          .build()
    }
  }

  @Suppress("DEPRECATION")
  private fun updatePlaySoundThroughEarpiece(playThroughEarpiece: Boolean) {
    if (NCCommunicationRoute.shared.active) return
    audioManager.mode = if (playThroughEarpiece) AudioManager.MODE_IN_COMMUNICATION else AudioManager.MODE_NORMAL
    audioManager.setSpeakerphoneOn(!playThroughEarpiece)
  }

  private fun retrieveStreamType(uri: Uri): Int = Util.inferContentType(uri)

  private fun buildMediaSourceFactory(
    factory: DataSource.Factory,
    mediaItem: MediaItem
  ): MediaSource {
    val uri = mediaItem.localConfiguration?.uri
    return when (val type = uri?.let { retrieveStreamType(it) }) {
      CONTENT_TYPE_SS -> SsMediaSource.Factory(factory)
      CONTENT_TYPE_DASH -> DashMediaSource.Factory(factory)
      CONTENT_TYPE_HLS -> HlsMediaSource.Factory(factory)
      CONTENT_TYPE_OTHER -> ProgressiveMediaSource.Factory(factory)
      else -> throw IllegalStateException("Unsupported type: $type")
    }.createMediaSource(mediaItem)
  }

  private fun <T> runOnMain(block: () -> T): T {
    val observed=NCDiagnosticOperationContext.capture(block)
    return runBlocking(appContext.mainQueue.coroutineContext) { observed() }
  }

  private fun soundScope(payload: Map<String,Any?>): NCSoundscapeScope {
    val value=payload["scope"] as? Map<*,*> ?: throw IllegalArgumentException("Missing sound scope")
    fun number(key: String): Long {
      val n=(value[key] as? Number)?.toDouble() ?: throw IllegalArgumentException("Invalid sound scope")
      require(n.isFinite() && n>=0 && n<=9007199254740991.0 && n==n.toLong().toDouble()); return n.toLong()
    }
    return NCSoundscapeScope(value["conversation_id"] as String,number("session_generation"),number("playback_generation"),number("revision"))
  }

  private fun soundImportFile(value: String): File {
    val uri=Uri.parse(value); require(uri.scheme=="file") { "Copy the selected document into the app cache first" }
    val file=File(uri.path ?: throw IllegalArgumentException("Invalid document")).canonicalFile
    require(file.path.startsWith(context.cacheDir.canonicalPath+File.separator) && file.isFile && file.length() in 1..(100L*1024*1024))
    return file
  }

  private fun checkRecordingPermission() {
    val permission = ContextCompat.checkSelfPermission(appContext.throwingActivity.applicationContext, Manifest.permission.RECORD_AUDIO)
    if (permission != PackageManager.PERMISSION_GRANTED) {
      throw AudioPermissionsException()
    }
  }

  companion object {
    val TAG: String = AudioModule::class.java.simpleName
  }
}
