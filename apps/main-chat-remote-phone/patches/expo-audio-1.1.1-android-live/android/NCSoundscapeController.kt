package expo.modules.audio

import android.content.Context
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.PlaybackException
import androidx.media3.exoplayer.ExoPlayer
import java.util.concurrent.Executor

@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
class NCSoundscapeController(private val context: Context, private val files: NCSoundscapeFiles,
  private val worker: Executor, private val focus: () -> Int, private val releaseFocus: () -> Unit,
  private val emit: (Map<String,Any?>) -> Unit) {
  private val handler=Handler(Looper.getMainLooper())
  private var scope: NCSoundscapeScope?=null
  private var revision=0L
  private var authorization=0L
  private var previewIntent=0L
  private var foreground=true
  private var retained=false
  private var waitingFocus=false
  private var resumeOnFocus=false
  private var prepared: ValidatedSoundFile?=null
  private val sources=mutableMapOf<String,ValidatedSoundFile>()
  private var stopped=false
  private val policy=NCSoundscapePolicy(::createPlayer,{SystemClock.elapsedRealtime()},::changed)
  private val ticker=object: Runnable { override fun run() {
    if(stopped) return
    policy.tick()
    if(policy.active) { handler.removeCallbacks(this); handler.postDelayed(this,33) }
  } }
  val holdsFocus: Boolean get() = retained
  val needsFocus: Boolean get() = retained && waitingFocus

  private val revoked: (NCSoundscapeScope) -> Unit = { value -> handler.post {
    if(scope?.conversationId==value.conversationId && scope?.sessionGeneration==value.sessionGeneration) {
      retained=false; pause("service")
    }
  } }
  private val paused: (String) -> Unit = { reason -> handler.post { if(!stopped) pause(reason) } }
  init { NCSoundscapeActivity.onRevoked=revoked; NCSoundscapeActivity.onPause=paused }

  fun activate(value: NCSoundscapeScope): Boolean {
    if(stopped || !policy.activate(value)) return false
    if(scope!=value) {
      if(scope?.conversationId!=value.conversationId || scope?.sessionGeneration!=value.sessionGeneration) {
        scope?.let { NCSoundscapeActivity.release(it) }; retained=false; waitingFocus=false; resumeOnFocus=false
      }
      revision++
    }
    scope=value; return true
  }
  fun begin(value: NCSoundscapeScope, layer: String): Long = if(activate(value)) policy.beginLoad(value,layer) else -1
  fun apply(value: NCSoundscapeScope, layer: String, token: Long, file: ValidatedSoundFile?, volume: Float, muted: Boolean, loop: Boolean): Boolean {
    if(scope!=value || stopped) { file?.let { unpin(it) }; return false }
    prepared=file
    return try { policy.apply(value,layer,token,file?.file?.absolutePath,volume,muted,loop) }
    finally { prepared?.let { unpin(it) }; prepared=null }
  }
  fun preview(value: NCSoundscapeScope, token: Long, file: ValidatedSoundFile, volume: Float, mixBackground: Boolean=false, done: (Boolean) -> Unit) {
    val intent=++previewIntent
    if(scope!=value || !foreground || stopped) { unpin(file); done(false); return }
    authorize(value) { allowed ->
      if(!allowed || !foreground || intent!=previewIntent) { unpin(file); done(false) }
      else {
        prepared=file
        try { done(policy.preview(value,token,file.file.absolutePath,volume,mixBackground)) }
        catch(error: Exception) { done(false); changed("preview_error") }
        finally { prepared?.let { unpin(it) }; prepared=null; reconcile() }
      }
    }
  }
  fun stopPreview(value: NCSoundscapeScope) { if(scope==value) { previewIntent++; policy.stopPreview(value) } }
  fun previewPlaying(value: NCSoundscapeScope, playing: Boolean, done: (Boolean) -> Unit) {
    val intent=++previewIntent
    if(scope!=value || !foreground || stopped) { done(false); return }
    if(!playing) { done(policy.previewPlaying(value,false)); reconcile(); return }
    authorize(value) { allowed ->
      done(allowed && foreground && intent==previewIntent && policy.previewPlaying(value,true)); reconcile()
    }
  }
  fun effect(value: NCSoundscapeScope, token: Long, file: ValidatedSoundFile, cueId: String,
    volume: Float, deadline: Long, done: (Boolean) -> Unit) {
    if(scope!=value || !foreground || stopped || System.currentTimeMillis()>deadline) { unpin(file); done(false); return }
    authorize(value) { allowed ->
      if(!allowed || !foreground || System.currentTimeMillis()>deadline) { unpin(file); done(false); reconcile() }
      else {
        prepared=file
        try { done(policy.effect(value,token,file.file.absolutePath,cueId,volume)) }
        catch(error: Exception) { done(false); changed("effect_error") }
        finally { prepared?.let { unpin(it) }; prepared=null; reconcile() }
      }
    }
  }
  fun stopEffect(value: NCSoundscapeScope) { if(scope==value) policy.stopEffect(value) }
  fun resume(value: NCSoundscapeScope, done: (Boolean) -> Unit) {
    if(!activate(value)) { done(false); return }
    authorize(value) { allowed -> done(allowed && policy.resume(value)); reconcile() }
  }
  private fun authorize(value: NCSoundscapeScope, done: (Boolean) -> Unit) {
    val intent=revision
    val admissionId=++authorization
    NCSoundscapeActivity.acquire(value).whenComplete { allowed,error -> handler.post {
      if(stopped || scope!=value || intent!=revision || admissionId!=authorization) {
        // A newer intent may share this exact service lease. An old callback
        // must not release the protection acquired for the replacement intent.
        if(admissionId==authorization) NCSoundscapeActivity.release(value)
        done(false); return@post
      }
      retained=error==null && allowed==true
      if(!retained) { done(false); changed("service_unavailable"); return@post }
      val admission=focus() // 1 granted, 0 delayed, -1 denied.
      if(admission<0) {
        retained=false; NCSoundscapeActivity.release(value); done(false); changed("focus_denied")
      } else {
        if(admission==0) { waitingFocus=true; resumeOnFocus=true; policy.pause(value,"focus") }
        else { waitingFocus=false; resumeOnFocus=false; policy.recover(value,"focus") }
        done(admission==1)
      }
    } }
  }
  fun pause(reason: String) {
    val value=scope ?: return
    if(reason!="focus") { waitingFocus=false; resumeOnFocus=false }
    revision++; policy.pause(value,reason)
    if(reason!="focus") { NCSoundscapeActivity.release(value); retained=false; releaseFocus() }
  }
  fun focusChanged(gained: Boolean) {
    val value=scope ?: return
    if(gained && retained) {
      waitingFocus=false; policy.recover(value,"focus")
      if(resumeOnFocus) { resumeOnFocus=false; policy.resume(value) }
      reconcile()
    } else if(!gained && retained) { waitingFocus=true; policy.pause(value,"focus") }
  }
  fun speech(value: NCSoundscapeScope, id: String, audible: Boolean, terminal: Boolean) {
    if(scope==value) { policy.speech(value,id,audible,terminal); reconcile() }
  }
  fun duck(value: NCSoundscapeScope, enabled: Boolean) { if(scope==value) policy.duck(value,enabled) }
  fun background() { foreground=false; scope?.let { policy.stopPreview(it); policy.stopEffect(it) } }
  fun foreground() { foreground=true }
  fun close(value: NCSoundscapeScope) {
    if(scope!=value) return
    revision++; waitingFocus=false; resumeOnFocus=false
    policy.close(value); NCSoundscapeActivity.release(value); retained=false; releaseFocus()
  }
  fun destroy() {
    scope?.let { close(it) }; stopped=true; handler.removeCallbacks(ticker)
    if(NCSoundscapeActivity.onRevoked===revoked) NCSoundscapeActivity.onRevoked=null
    if(NCSoundscapeActivity.onPause===paused) NCSoundscapeActivity.onPause=null
  }
  private fun unpin(file: ValidatedSoundFile) { worker.execute { files.release(file) } }
  private fun changed(reason: String) {
    emit(mapOf("reason" to reason,"active" to policy.active,"revision" to scope?.revision,
      "conversation_id" to scope?.conversationId,"session_generation" to scope?.sessionGeneration,
      "playback_generation" to scope?.playbackGeneration,"effect_cue_id" to policy.effectCueId,
      "effect_active" to policy.effectActive))
    reconcile()
  }
  private fun reconcile() {
    handler.removeCallbacks(ticker)
    if(policy.active && retained) handler.post(ticker)
    if(!policy.active && !waitingFocus && retained && scope!=null) {
      NCSoundscapeActivity.release(scope!!); retained=false; releaseFocus()
    }
  }
  private fun createPlayer(key: String, loop: Boolean): NCSoundscapePlayer {
    val file=prepared ?: files.retain(sources[key] ?: throw IllegalArgumentException("Unverified sound source"))
    require(file.file.absolutePath==key)
    val player=try { ExoPlayer.Builder(context).build() } catch(error: Exception) { unpin(file); throw error }
    prepared=null
    sources[key]=file
    val wrapper=object: NCSoundscapePlayer {
      private var released=false
      override fun ready() = !released && player.playbackState==Player.STATE_READY
      override fun durationMs(): Long? = if(!released && player.duration>0)player.duration else null
      override fun remainingMs(): Long? = durationMs()?.let { (it-player.currentPosition).coerceAtLeast(0) }
      override fun volume(value: Float) { if(!released)player.volume=value }
      override fun play() { if(!released && retained)player.play() }
      override fun pause() { if(!released)player.pause() }
      override fun release() { if(!released) { released=true; player.release(); if(sources[key]===file)sources.remove(key); unpin(file) } }
    }
    try {
      player.volume=0f
      player.setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(),false)
      player.repeatMode=if(loop)Player.REPEAT_MODE_ONE else Player.REPEAT_MODE_OFF
      player.addListener(object: Player.Listener {
        override fun onPlaybackStateChanged(state: Int) { if(state==Player.STATE_ENDED) policy.ended(wrapper) }
        override fun onPlayerError(error: PlaybackException) { policy.ended(wrapper); changed("player_error") }
      })
      player.setMediaItem(MediaItem.fromUri(Uri.fromFile(file.file))); player.prepare()
      return wrapper
    } catch(error: Throwable) { wrapper.release(); throw error }
  }
}
