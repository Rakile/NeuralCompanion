// NeuralCompanion, MIT. Local decoded video view; no audio/session authority.
package expo.modules.audio

import android.content.Context
import android.widget.FrameLayout
import expo.modules.kotlin.AppContext
import expo.modules.kotlin.views.ExpoView
import java.io.File

internal class NCAVView(context: Context, appContext: AppContext) : ExpoView(context, appContext) {
  override val shouldUseAndroidLayout = true
  private val canvas = FrameLayout(context)
  init { addView(canvas, LayoutParams(LayoutParams.MATCH_PARENT,LayoutParams.MATCH_PARENT)) }
  private var surface: NCTextureVideo? = null
  private var entry: NCAVBridge.Entry? = null
  private var transitionDisplayed=false
  private val transition = NCVisualTransition(canvas) { _,kind,_,_ ->
    if(kind!="idle" && kind!="returned")transitionDisplayed=true
  }
  private val local = transition.idle
  private val opening = NCSpeechOpening(canvas)
  init { canvas.addOnLayoutChangeListener { _,l,t,r,b,ol,ot,or,ob ->
    if (r-l != or-ol || b-t != ob-ot) { transition.layout(); opening.layout(); surface?.layoutVideo() }
  } }
  private var speechDisplayed = false
  val idleVisible: Boolean get() = local.visible && entry?.localVisualAllowed() == true
  private val refresh = object : Runnable {
    override fun run() { refreshIdle(); if (isAttachedToWindow) postDelayed(this,50) }
  }
  private fun refreshIdle() {
    val allowed = entry?.localVisualAllowed() == true
    canvas.visibility = if (allowed) android.view.View.VISIBLE else android.view.View.INVISIBLE
    if (entry?.buffered==true) entry?.bufferedClock?.states()?.forEach { bufferedHeard(it,false) }
    transition.display(allowed,speechDisplayed)
    entry?.handoffStatus = transition.status()
    entry?.idlePosition = local.position()
    entry?.setLocalVisible(allowed && (local.visible || speechDisplayed || transitionDisplayed))
    surface?.alpha = if (allowed && speechDisplayed) 1f else 0f
  }
  fun prepareIdle(generation: String, id: String, file: File, fade: Int, sourceCount: Int, done: (Boolean) -> Unit) {
    if (entry?.localVisualAllowed() != true) { done(false); return }
    local.prepareAt(generation,id,file,fade,sourceCount,0,done)
  }
  internal fun prepareIdleChunks(value: NCIdleChunkFile, done: (Boolean)->Unit) {
    if (entry?.localVisualAllowed() != true) { done(false); return }
    local.prepareChunks(value.generation,value.motion,value.media,value.file,value.fade,value.sourceCount,value.start,value.sequence,value.sha,done)
  }
  internal fun appendIdleChunk(value: NCIdleChunkFile, done: (Boolean)->Unit) {
    if (entry?.localVisualAllowed() != true) { done(false); return }
    local.appendChunk(value,done)
  }
  fun bufferedHeard(value:NCBufferedAudioClock.State,refresh:Boolean=true) {
    if (entry?.buffered!=true) return
    if (value.stopped && value.key==transition.activeKey()) transition.clearDetached {}
    else if (value.started) transition.heard(value.key,value.samples,value.completed,value.successor)
    if(entry?.localVisualAllowed()==true && value.started && value.playing && !value.completed && !value.stopped)
      entry?.bufferedVideo?.values?.toList()?.filter { it.first==value.key }?.forEach { it.second.presentOpening(value.samples) }
    if ((value.completed || value.stopped) && !value.successor) speechDisplayed=false
    if (refresh) refreshIdle()
  }
  fun selectIdle(generation: String, id: String): Boolean {
    if (entry?.localVisualAllowed() != true) return false
    val result = local.select(generation,id); refreshIdle(); return result
  }
  fun selectIdleChunks(generation: String, id: String, media: String): Boolean {
    if (entry?.localVisualAllowed() != true) return false
    val result = local.selectChunks(generation,id,media); refreshIdle(); return result
  }
  fun bufferedFrame(key:Long,tick:Int,frame:org.webrtc.VideoFrame) {
    if(entry?.buffered!=true || entry?.localVisualAllowed()!=true)return
    val heard=entry?.bufferedClock?.sample(key) ?: return
    if(!NCBufferedVideoTimeline.presentable(tick,heard.samples,heard.started && heard.playing && !heard.stopped))return
    if(transition.activeKey()>0) {
      bufferedHeard(heard,false)
      transition.streamFrame(key,tick,frame)
    }
    else surface?.onFrameTracked(frame) {
      if(entry?.bufferedClock?.sample(key)?.playing==true) { speechDisplayed=true;refreshIdle() }
    }
  }
  fun clearIdle() { transition.clearDetached {}; local.clear(); entry?.setLocalVisible(false) }
  fun clearIdleDetached(done: (Boolean) -> Unit) { local.clearDetached(done); entry?.setLocalVisible(false) }
  fun clearIdleChunksDetached(generation: String, media: String, done: (Boolean)->Unit) {
    local.clearChunksDetached(generation,media,done); refreshIdle()
  }
  fun idlePosition(): Map<String,Any>? = local.position()
  fun prepareOpening(owner: String, key: Long, media: String, file: File, indices: IntArray, sourceCount: Int, done: (Boolean) -> Unit) {
    if (entry?.localVisualAllowed() != true) { done(false); return }
    if (transition.activeKey() == key) transition.prepareOpening(owner,key,media,file,indices,sourceCount,done)
    else opening.prepare(owner,key,media,file,indices.take(12).toIntArray(),sourceCount,done)
  }
  fun beginHandoff(owner: String, key: Long, plan: String, count: Int, indices: IntArray): Boolean {
    if (entry?.localVisualAllowed() != true) return false
    return transition.begin(owner,key,plan,indices,count)
  }
  fun appendHandoff(key: Long, index: Int, file: File, done: (Boolean)->Unit) = transition.append(key,index,file,done)
  fun nextHandoff(key: Long, count: Int, indices: IntArray): Boolean = transition.next(key,count,indices)
  internal fun bufferedSource(key: Long, source: NCBufferedVisualSource, done: (Boolean)->Unit) = transition.configure(key,source,done)
  fun armHandoff(key: Long): Double {
    val at = transition.arm(key,700,1800)
    return if (at == 0L) 0.0 else (at-System.nanoTime())/1_000_000.0
  }
  fun clearOpeningDetached(done: (Boolean) -> Unit) {
    transitionDisplayed=false
    transition.clearDetached { first -> opening.clearAll { second -> done(first && second) } }
  }
  var handle: String = ""
    set(value) { if (field != value) { detach(); field = value; attach() } }

  private fun attach() {
    if (surface == null) return
    val next = NCAVBridge.viewEntry(handle) ?: return
    entry = next; next.setView(this)
  }
  private fun detach() { entry?.idlePosition = null; entry?.removeView(this); entry = null; transition.clearDetached {}; local.clear(); opening.clearAll {}; speechDisplayed = false; transitionDisplayed=false }
  override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
    super.onSizeChanged(w,h,oldw,oldh); transition.layout(); opening.layout(); surface?.layoutVideo()
  }
  override fun onAttachedToWindow() {
    super.onAttachedToWindow()
    if (surface == null) {
      val target = NCTextureVideo(context) {
        refreshIdle()
      }
      try {
        canvas.addView(target,0,FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        surface = target
      } catch (_: RuntimeException) { target.close(); return }
    }
    attach()
    removeCallbacks(refresh); post(refresh)
  }
  override fun onDetachedFromWindow() {
    detach()
    removeCallbacks(refresh)
    surface?.let { it.clearImage(); it.close(); canvas.removeView(it) }
    surface = null
    super.onDetachedFromWindow()
  }
}
