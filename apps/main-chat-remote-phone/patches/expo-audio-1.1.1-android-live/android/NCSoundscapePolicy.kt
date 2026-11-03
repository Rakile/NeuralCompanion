package expo.modules.audio

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

data class NCSoundscapeScope(val conversationId: String, val sessionGeneration: Long,
  val playbackGeneration: Long, val revision: Long)

interface NCSoundscapePlayer {
  fun remainingMs(): Long? = null
  fun durationMs(): Long? = null
  fun ready(): Boolean = true
  fun volume(value: Float)
  fun play()
  fun pause()
  fun release()
}

/** Serialized by the adapter. No Android, speech bindings, or completion receipts. */
class NCSoundscapePolicy(
  private val create: (String, Boolean) -> NCSoundscapePlayer,
  private val clock: () -> Long,
  private val event: (String) -> Unit = {},
) {
  private data class Layer(var token: Long = 0, var file: String? = null,
    var current: NCSoundscapePlayer? = null, var outgoing: NCSoundscapePlayer? = null,
    var volume: Float = 0f, var muted: Boolean = false, var loop: Boolean = true,
    var fadeStart: Long = 0, var fading: Boolean = false, var outgoingFactor: Float = 1f,
    var fadeDuration: Long = 3000, var fadeWaiting: Boolean = false)
  private val layers = mapOf("ambience" to Layer(volume=.2f), "music" to Layer(volume=.15f))
  private var scope: NCSoundscapeScope? = null
  private var closed = false
  private val pauses = mutableSetOf("user")
  private val speaking = mutableSetOf<String>()
  private var duckEnabled = true
  private var duckFrom = 1f
  private var duckTo = 1f
  private var duckStart = 0L
  private var duckDuration = 0L
  private var holdUntil: Long? = null
  private var preview: NCSoundscapePlayer? = null
  private var previewToken = 0L
  private var previewPaused = false
  private var previewMixBackground = false
  private var effectToken = 0L
  private var effectPlayer: NCSoundscapePlayer? = null
  private val consumedEffects = linkedSetOf<String>()
  var effectCueId: String? = null
    private set
  val effectActive: Boolean get() = effectPlayer != null

  val active: Boolean get() = !closed && (preview != null && pauses.all { it=="user" || it=="story" }
    || pauses.isEmpty() && (effectPlayer != null || layers.values.any { it.current != null }))
  private fun matches(value: NCSoundscapeScope) = !closed && scope == value
  private fun ramp(now: Long): Float {
    val progress = if (duckDuration==0L) 1f else ((now-duckStart).toFloat()/duckDuration).coerceIn(0f,1f)
    return duckFrom+(duckTo-duckFrom)*progress
  }
  private fun setDuck(value: Float, duration: Long) {
    if (duckTo==value) return
    duckFrom=ramp(clock()); duckTo=value; duckStart=clock(); duckDuration=duration
  }
  private fun release(layer: Layer) {
    layer.current?.release(); layer.outgoing?.release()
    layer.current=null; layer.outgoing=null; layer.file=null; layer.fading=false
  }
  fun activate(value: NCSoundscapeScope): Boolean {
    require(value.conversationId.isNotBlank() && value.sessionGeneration>=0 && value.playbackGeneration>=0 && value.revision>=0)
    val old=scope
    if (old!=null) {
      if (value.sessionGeneration<old.sessionGeneration) return false
      if (value.sessionGeneration==old.sessionGeneration) {
        if (value.conversationId!=old.conversationId || value.playbackGeneration<old.playbackGeneration || value.revision<old.revision) return false
        if (closed && value==old) return false
      }
      if (value==old) return true
    }
    val newConversation=old==null || old.sessionGeneration!=value.sessionGeneration || old.conversationId!=value.conversationId
    if (old!=value) { preview?.release(); preview=null; releaseEffect() }
    if (old?.playbackGeneration!=value.playbackGeneration) {
      speaking.clear(); holdUntil=null; setDuck(1f,900)
    }
    if (newConversation || closed) {
      if(newConversation) consumedEffects.clear()
      layers.values.forEach { release(it) }; preview?.release(); preview=null
      pauses.clear(); pauses.add("user"); speaking.clear(); holdUntil=null
      duckFrom=1f; duckTo=1f; duckDuration=0
    }
    layers.values.forEach { it.token++ }; previewToken++
    scope=value; closed=false; event("scope"); return true
  }
  fun beginLoad(value: NCSoundscapeScope, name: String): Long {
    if (!matches(value)) return -1
    if (name=="preview") return ++previewToken
    if (name=="effect") return ++effectToken
    val layer=layers[name] ?: throw IllegalArgumentException("Unknown sound layer")
    return ++layer.token
  }
  fun apply(value: NCSoundscapeScope, name: String, token: Long, file: String?, volume: Float,
    muted: Boolean, loop: Boolean): Boolean {
    if (!matches(value)) return false
    val layer=layers[name] ?: return false
    if (token!=layer.token) return false
    require(volume.isFinite() && volume in 0f..1f)
    val next=if (file!=null && (file!=layer.file || loop!=layer.loop)) create(file,loop) else null
    layer.volume=volume; layer.muted=muted
    if (file==null) release(layer)
    else if (next!=null) {
      next.volume(0f)
      // A rapid change keeps the current player's present level and disposes its predecessor.
      val progress=if (layer.fading) ((clock()-layer.fadeStart).toDouble()/layer.fadeDuration).coerceIn(0.0,1.0) else 1.0
      layer.outgoing?.release(); layer.outgoing=layer.current
      layer.outgoingFactor=sin(progress*PI/2).toFloat()
      layer.current=next; layer.file=file; layer.loop=loop; layer.fadeStart=clock(); layer.fading=true
      layer.fadeDuration=3000; layer.fadeWaiting=!next.ready()
      if (pauses.isEmpty() && (preview==null || previewMixBackground)) next.play()
    }
    tick(); event("selection"); return true
  }
  fun speech(value: NCSoundscapeScope, id: String, audible: Boolean, terminal: Boolean) {
    if (!matches(value)) return
    if (audible && !terminal) speaking.add(id) else speaking.remove(id)
    if (speaking.isNotEmpty()) { holdUntil=null; if (duckEnabled) setDuck(.3f,150) }
    else if (terminal) { holdUntil=null; setDuck(1f,900) }
    else if (holdUntil==null) holdUntil=clock()+400
  }
  fun duck(value: NCSoundscapeScope, enabled: Boolean) {
    if (!matches(value)) return
    duckEnabled=enabled; setDuck(if (enabled && (speaking.isNotEmpty() || holdUntil!=null)) .3f else 1f, if(enabled)150 else 900)
  }
  fun pause(value: NCSoundscapeScope, reason: String) {
    if (!matches(value)) return
    pauses.add(reason)
    releaseEffect()
    if(reason=="focus") preview?.pause() else { preview?.release(); preview=null }
    layers.values.forEach {
      it.token++; it.outgoing?.release(); it.outgoing=null; it.fading=false
      it.current?.pause(); it.current?.volume(0f)
    }
    previewToken++; event("pause:$reason")
  }
  fun recover(value: NCSoundscapeScope, reason: String): Boolean {
    if (!matches(value) || reason=="user" || reason=="route" || reason=="connection") return false
    pauses.remove(reason); startAuthorized(); return active
  }
  fun resume(value: NCSoundscapeScope): Boolean {
    if (!matches(value)) return false
    pauses.removeAll(setOf("user","route","connection","story","service"))
    startAuthorized(); event("resume"); return pauses.isEmpty()
  }
  private fun startAuthorized() {
    if (pauses.isNotEmpty()) return
    if (preview!=null && !previewPaused) preview?.play()
    if (preview==null || previewMixBackground) layers.values.forEach { it.current?.play() }
    tick()
  }
  fun preview(value: NCSoundscapeScope, token: Long, file: String, volume: Float=1f, mixBackground: Boolean=false): Boolean {
    if (!matches(value) || token!=previewToken || pauses.any { it!="user" && it!="story" }) return false
    require(volume.isFinite() && volume in 0f..1f)
    releaseEffect()
    val next=create(file,false); next.volume(volume)
    preview?.release(); preview=next; previewPaused=false; previewMixBackground=mixBackground
    if(!mixBackground) layers.values.forEach { it.current?.pause(); it.outgoing?.release(); it.outgoing=null; it.fading=false }
    next.play(); event("preview"); return true
  }
  fun previewPlaying(value: NCSoundscapeScope, playing: Boolean): Boolean {
    if(!matches(value) || preview==null) return false
    if(playing && pauses.any { it!="user" && it!="story" }) return false
    previewPaused=!playing
    if(playing) preview?.play() else preview?.pause()
    event(if(playing) "preview_resumed" else "preview_paused"); return true
  }
  fun stopPreview(value: NCSoundscapeScope) {
    if (!matches(value)) return
    previewToken++; preview?.release(); preview=null; startAuthorized(); event("preview_stopped")
  }
  fun close(value: NCSoundscapeScope) {
    if (!matches(value)) return
    layers.values.forEach { it.token++; release(it) }; previewToken++
    preview?.release(); preview=null; releaseEffect(); speaking.clear(); holdUntil=null; closed=true; event("closed")
  }
  fun ended(player: NCSoundscapePlayer) {
    if (closed) return
    if(effectPlayer===player) { releaseEffect(); event("effect_ended"); return }
    if (preview===player) { scope?.let { stopPreview(it) }; return }
    layers.values.forEach { layer ->
      if(layer.current===player) release(layer)
      else if(layer.outgoing===player) { layer.outgoing?.release(); layer.outgoing=null }
    }
    event("ended")
  }
  private fun releaseEffect() {
    effectToken++; effectPlayer?.release(); effectPlayer=null; effectCueId=null
  }
  fun stopEffect(value: NCSoundscapeScope) {
    if(!matches(value)) return
    val hadEffect=effectPlayer!=null
    releaseEffect()
    if(hadEffect) event("effect_stopped")
  }
  fun effect(value: NCSoundscapeScope, token: Long, file: String, cueId: String, volume: Float): Boolean {
    if(!matches(value) || token!=effectToken || pauses.isNotEmpty() || preview!=null || consumedEffects.contains(cueId)) return false
    require(cueId.isNotBlank() && cueId.length<=128 && volume.isFinite() && volume in 0f..1f)
    val next=create(file,false)
    releaseEffect(); effectPlayer=next; effectCueId=cueId
    consumedEffects.add(cueId)
    while(consumedEffects.size>128) consumedEffects.remove(consumedEffects.first())
    next.volume(volume); next.play(); event("effect_started"); return true
  }
  fun tick() {
    if (closed) return
    val now=clock()
    if (holdUntil?.let { now>=it }==true && speaking.isEmpty()) {
      holdUntil=null; setDuck(1f,900)
    }
    val duck=ramp(now)
    layers.values.forEach { layer ->
      // Imported/generated tracks need not have matching endpoints. Overlap the
      // next repeat using the same bounded current/outgoing pair as selection.
      val duration=layer.current?.durationMs()
      val remaining=layer.current?.remainingMs()
      if(!layer.fading && layer.loop && pauses.isEmpty() && (preview==null || previewMixBackground)
          && duration!=null && remaining!=null && duration>0 && remaining in 1..minOf(3000,duration/4).coerceAtLeast(1)) {
        try {
          val next=create(layer.file!!,true); next.volume(0f)
          layer.outgoing?.release(); layer.outgoing=layer.current; layer.current=next
          layer.outgoingFactor=1f; layer.fadeDuration=minOf(3000,duration/4).coerceAtLeast(1)
          layer.fadeStart=now; layer.fading=true; layer.fadeWaiting=!next.ready(); next.play()
        } catch(error: Exception) { layer.loop=false; event("loop_error") }
      }
      if(layer.fadeWaiting && layer.current?.ready()==true) { layer.fadeWaiting=false;layer.fadeStart=now }
      val progress=if(layer.fadeWaiting) 0.0 else if(layer.fading) ((now-layer.fadeStart).toDouble()/layer.fadeDuration).coerceIn(0.0,1.0) else 1.0
      val base=if (pauses.isNotEmpty() || (preview!=null && !previewMixBackground) || layer.muted) 0f else layer.volume*duck
      layer.current?.volume((base*sin(progress*PI/2)).toFloat().coerceIn(0f,1f))
      layer.outgoing?.volume((base*layer.outgoingFactor*cos(progress*PI/2)).toFloat().coerceIn(0f,1f))
      if (progress>=1 && layer.fading) { layer.outgoing?.release(); layer.outgoing=null; layer.fading=false }
    }
  }
}
