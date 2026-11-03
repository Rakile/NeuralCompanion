package expo.modules.nclivecapture

import android.app.ActivityManager
import android.app.KeyguardManager
import android.content.Context
import android.content.BroadcastReceiver
import android.content.Intent
import android.content.IntentFilter
import android.os.PowerManager
import androidx.core.content.ContextCompat
import com.facebook.react.bridge.ReactContext
import expo.modules.audio.NCPlaybackGuard
import expo.modules.kotlin.exception.CodedException
import expo.modules.kotlin.exception.toCodedException
import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import expo.modules.kotlin.functions.Queues
import expo.modules.kotlin.records.Field
import expo.modules.kotlin.records.Record
import java.util.concurrent.CompletableFuture

private class ReplyTailOptions : Record {
  @Field var requestIds: List<String> = emptyList()
  @Field var pendingUploadIds: List<String> = emptyList()
}

private class CaptureCodedException(failure: CaptureFailure, cause: Throwable? = null) :
  CodedException(failure.wireValue, failure.wireValue, cause)

class NcLiveCaptureModule : Module() {
  private lateinit var replyMedia: ReplyMediaControls
  private var characterSound: CharacterAddedSound? = null
  private var removeClockListener: (() -> Unit)? = null
  private lateinit var engine: LiveCaptureEngine
  private lateinit var playback: PlaybackBackgroundController
  private lateinit var playbackWork: PlaybackJsWork
  private lateinit var peerConnection: PeerConnectionBackgroundController
  private var playbackContext:Context?=null
  private val screenReceiver=object:BroadcastReceiver(){
    override fun onReceive(context:Context?,intent:Intent?){
      if(intent?.action==Intent.ACTION_SCREEN_OFF && ::playback.isInitialized)playback.locked()
    }
  }
  @Volatile private var visible = false

  override fun definition() = ModuleDefinition {
    Name("NcLiveCapture")
    Events("captureEvent", "playbackBackgroundEvent", "replyMediaCommand", "playbackClock", "peerConnectionStopped")

    OnCreate {
      val context = appContext.reactContext ?: throw CaptureCodedException(CaptureFailure.START_FAILED)
      visible = processForeground(context)
      peerConnection=PeerConnectionBackgroundController(context.applicationContext,{visible}) {
        sendEvent("peerConnectionStopped",mapOf("ticket" to it))
      }
      engine = LiveCaptureEngine(context.applicationContext) { visible }
      characterSound = CharacterAddedSound(context.applicationContext)
      replyMedia = ReplyMediaControls(context.applicationContext) { scope, command ->
        if (command == "pause" || command == "stop") expo.modules.audio.NCSoundscapeActivity.onPause?.invoke("user")
        sendEvent("replyMediaCommand", mapOf("scope" to scope, "command" to command))
      }
      removeClockListener = LiveAudioService.addClockListener { generation ->
        if (!visible) sendEvent("playbackClock", mapOf("generation" to generation.toDouble()))
      }
      engine.setEmitter { sendEvent("captureEvent", it.payload()) }
      playbackContext=context.applicationContext
      playbackWork=PlaybackJsWork(context as? ReactContext
        ?: throw CaptureCodedException(CaptureFailure.START_FAILED))
      playback=PlaybackBackgroundController(context.applicationContext,{visible},{
        runCatching {context.getSystemService(KeyguardManager::class.java)?.isKeyguardLocked==false &&
          context.getSystemService(PowerManager::class.java)?.isInteractive==true}.getOrDefault(false)
      },{ticket,playerId->
        NCPlaybackGuard.shared.backgroundPlaybackOwner(ticket,playerId)?.let { owner ->
          object:PlaybackBackgroundController.Owner {
            override fun current()=owner.current()
            override fun confirm()=owner.confirm()
            override fun ready()=owner.ready()
            override fun pauseForLock()=owner.pauseForLock()
            override fun resumeForeground()=owner.resumeForeground()
            override fun release()=owner.release()
            override fun retire()=owner.retire()
          }
        }
      },playbackWork,{reason->sendEvent("playbackBackgroundEvent",playback.state()+mapOf("reason" to reason))})
      ContextCompat.registerReceiver(context.applicationContext,screenReceiver,
        IntentFilter(Intent.ACTION_SCREEN_OFF),ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    AsyncFunction("beginPlaybackBackground") { ticket:String,playerId:String,promise:Promise ->
      playback.begin(ticket,playerId).thenAccept {promise.resolve(it)}
    }
    AsyncFunction("beginPeerConnectionBackground") { ticket:String,promise:Promise ->
      peerConnection.begin(ticket).whenComplete { ready,error ->
        if(error!=null)promise.reject(error.toCodedException()) else promise.resolve(ready)
      }
    }.runOnQueue(Queues.MAIN)
    AsyncFunction("endPeerConnectionBackground") {ticket:String -> peerConnection.end(ticket)}.runOnQueue(Queues.MAIN)
    AsyncFunction("endPlaybackBackground") {ticket:String,generation:Long -> playback.end(ticket,generation)}
    AsyncFunction("playbackBackgroundState") {playback.state()}
    AsyncFunction("awaitPlaybackBackgroundEnd") {ticket:String,generation:Long,promise:Promise ->
      playbackWork.awaitEnd(ticket,generation).thenAccept{promise.resolve(it)}
    }

    AsyncFunction("playCharacterAddedSound") { characterSound?.play(); true }
    AsyncFunction("configureReplyMediaControls") { scope: String?, playing: Boolean, nextToggles: Boolean ->
      replyMedia.configure(scope, playing, nextToggles)
    }
    AsyncFunction("configureReplyNotification") { scope: String?, playing: Boolean, nextToggles: Boolean, info: Map<String, Any?> ->
      replyMedia.configure(scope, playing, nextToggles, info)
    }
    AsyncFunction("setReplyPlaybackActive") { ticket: String, active: Boolean, promise:Promise ->
      dispatchCapture(promise) { engine.setReplyPlaybackActive(ticket, active) }
    }
    Function("isPlaybackServiceActive") { generation: Double -> LiveAudioService.isPlaybackServiceActive(generation.toLong()) }
    Function("playbackClockVersion") { 1 }

    AsyncFunction("capabilities") { promise:Promise -> dispatchCapture(promise) { engine.capabilities() } }
    AsyncFunction("outputState") { promise:Promise -> dispatchCapture(promise) { engine.outputState() } }
    AsyncFunction("attachCapture") {sessionId:String,ticket:String,foregroundOnly:Boolean,promise:Promise ->
      dispatchCapture(promise){engine.attachCapture(sessionId,ticket,foregroundOnly)}
    }
    Function("admitForegroundReply") {ticket:String,requestId:String ->
      wrap{engine.admitForegroundReply(ticket,requestId)}
    }
    AsyncFunction("captureAttachmentState") {sessionId:String,ticket:String,captureId:String,promise:Promise ->
      dispatchCapture(promise){engine.captureAttachmentState(sessionId,ticket,captureId)}
    }
    AsyncFunction("detachCapture") {sessionId:String,ticket:String,captureId:String,promise:Promise ->
      dispatchCapture(promise){engine.detachCapture(sessionId,ticket,captureId)}
    }
    AsyncFunction("beginProtectedOutput") { sessionId: String, expectedTicket: String?, promise:Promise ->
      dispatchCapture(promise) { engine.beginProtectedOutput(sessionId, expectedTicket, foregroundOnly = false) }
    }
    AsyncFunction("beginForegroundProtectedOutput") { sessionId: String, expectedTicket: String?, promise:Promise ->
      dispatchCapture(promise) { engine.beginProtectedOutput(sessionId, expectedTicket, foregroundOnly = true) }
    }
    AsyncFunction("beginForegroundOutput") { expectedTicket: String?, promise:Promise -> dispatchCapture(promise) { engine.beginForegroundOutput(expectedTicket) } }
    AsyncFunction("retireOutput") { ticket: String, promise:Promise -> dispatchCapture(promise) { engine.retireOutput(ticket) } }
    AsyncFunction("start") { sessionId: String, promise:Promise -> dispatchCapture(promise) { engine.start(sessionId) } }
    AsyncFunction("setSpeechSensitivity") { level: Int, promise:Promise -> dispatchCapture(promise) { engine.setSpeechSensitivity(level) } }
    AsyncFunction("stop") { sessionId: String, promise:Promise -> dispatchCapture(promise) { engine.stop(sessionId) } }
    AsyncFunction("pauseConnection") { sessionId: String, ticket: String, recoveryEpoch: Long, promise:Promise ->
      dispatchCapture(promise) { engine.pauseConnection(sessionId, ticket, recoveryEpoch) }
    }
    AsyncFunction("pauseReplyContinuation") { sessionId: String, ticket: String, recoveryEpoch: Long, promise:Promise ->
      dispatchCapture(promise) { engine.pauseReplyContinuation(sessionId, ticket, recoveryEpoch) }
    }
    AsyncFunction("resumeReplyContinuation") { sessionId: String, ticket: String, recoveryEpoch: Long, requestIds: List<String>, promise: Promise ->
      dispatchCapture(promise) { engine.resumeReplyContinuation(sessionId, ticket, recoveryEpoch, requestIds) }
    }
    AsyncFunction("resumeConnection") { sessionId: String, ticket: String, recoveryEpoch: Long, promise: Promise ->
      dispatchCapture(promise) { engine.resumeConnection(sessionId, ticket, recoveryEpoch) }
    }
    AsyncFunction("stopListening") { sessionId: String, permit: ReplyTailOptions, promise:Promise ->
      dispatchCapture(promise) { engine.stopListening(sessionId, permit.requestIds, permit.pendingUploadIds) }
    }
    AsyncFunction("registerSubmittedUpload") { sessionId: String, utteranceId: String, uploadId: String, promise:Promise ->
      dispatchCapture(promise) { engine.registerSubmittedUpload(sessionId, utteranceId, uploadId) }
    }
    AsyncFunction("registerSubmittedTurn") { sessionId: String, ticket: String, submissionId: String, kind: String, promise:Promise ->
      dispatchCapture(promise) { engine.registerSubmittedTurn(sessionId, ticket, submissionId, kind) }
    }
    AsyncFunction("admitReplyForUpload") { sessionId: String, ticket: String, uploadId: String, requestId: String, promise:Promise ->
      dispatchCapture(promise) { engine.admitReply(sessionId, ticket, uploadId, requestId) }
    }
    AsyncFunction("abandonSubmittedUpload") { sessionId: String, ticket: String, uploadId: String, promise:Promise ->
      dispatchCapture(promise) { engine.abandonUpload(sessionId, ticket, uploadId) }
    }
    AsyncFunction("finishReplyOutput") { sessionId: String, ticket: String, completedRequestIds: List<String>, promise:Promise ->
      dispatchCapture(promise) { engine.finishReply(sessionId, ticket, completedRequestIds) }
    }
    AsyncFunction("armBackground") { sessionId: String, bluetoothConfirmed: Boolean, promise:Promise ->
      dispatchCapture(promise) { engine.armBackground(sessionId, bluetoothConfirmed) }
    }
    AsyncFunction("armForeground") { sessionId: String, promise:Promise -> dispatchCapture(promise) { engine.armForeground(sessionId) } }
    AsyncFunction("disarmBackground") { sessionId: String, promise:Promise -> dispatchCapture(promise) { engine.disarmBackground(sessionId) } }
    AsyncFunction("setPlaybackActive") { sessionId: String, active: Boolean, promise:Promise -> dispatchCapture(promise) { engine.setPlaybackActive(sessionId, active) } }
    AsyncFunction("acquireUtterance") { sessionId: String, utteranceId: String, promise:Promise -> dispatchCapture(promise) { engine.acquire(sessionId, utteranceId) } }
    AsyncFunction("releaseUtterance") { sessionId: String, utteranceId: String, promise:Promise -> dispatchCapture(promise) { engine.release(sessionId, utteranceId) } }
    AsyncFunction("acknowledgeState") { sessionId: String, sequence: Int, promise:Promise -> dispatchCapture(promise) { engine.acknowledgeState(sessionId, sequence) } }

    OnActivityEntersForeground { visible = true; if(::playback.isInitialized)playback.foregrounded() }
    OnActivityEntersBackground { visible = false; if (::engine.isInitialized) engine.activityBackgrounded() }
    OnActivityDestroys { visible = false; if (::engine.isInitialized) engine.activityBackgrounded() }
    OnDestroy {
      if(::peerConnection.isInitialized)android.os.Handler(android.os.Looper.getMainLooper()).post{peerConnection.destroy()}
      characterSound?.close(); characterSound = null
      removeClockListener?.invoke(); removeClockListener = null
      if (::replyMedia.isInitialized) replyMedia.destroy()
      if(::playback.isInitialized)playback.destroy()
      if(::playbackWork.isInitialized)playbackWork.destroy()
      playbackContext?.let{runCatching{it.unregisterReceiver(screenReceiver)}};playbackContext=null
      if (::engine.isInitialized) engine.destroy()
    }
  }

  private fun dispatchCapture(promise: Promise, operation: () -> Any?) {
    fun reject(error: Throwable) {
      val mapped = try { wrap { throw error } } catch (failure: Throwable) { failure }
      promise.reject(mapped.toCodedException())
    }
    fun resolve(value: Any?) { promise.resolve(if (value === Unit) null else value) }
    try {
      engine.dispatchBridge {
        val value = try { wrap(operation) } catch (error: Throwable) { reject(error); return@dispatchBridge }
        // Recovery operations already return futures; never wait on the owner.
        if (value is CompletableFuture<*>) value.whenComplete { result, error ->
          if (error != null) reject(error) else resolve(result)
        } else resolve(value)
      }
    } catch (error: Throwable) { reject(error) }
  }

  private fun <T> wrap(operation: () -> T): T = try { operation() }
  catch (error: CapturePolicyException) { throw CaptureCodedException(error.failure, error) }
  catch (error: UtteranceStoreException) { throw CaptureCodedException(error.failure, error) }

  private fun processForeground(context: Context): Boolean {
    val process = ActivityManager.RunningAppProcessInfo()
    ActivityManager.getMyMemoryState(process)
    return process.importance == ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND
  }
}
