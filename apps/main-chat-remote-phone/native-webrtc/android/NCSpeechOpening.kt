package expo.modules.audio

import android.view.TextureView
import android.widget.FrameLayout
import android.widget.ImageView
import java.io.File
import org.webrtc.VideoFrame

/** Prepare one existing speech segment behind the outgoing surface, then pause
 * at its first observed picture. No audio device, admission or receipt API. */
class NCSpeechOpening(private val host: FrameLayout,
  private val observed: (TextureView,Int,Long) -> Unit = { _,_,_ -> }) {
  private inner class Slot(val key: Long, val first: Int) {
    val container = FrameLayout(host.context)
    var ended = false
    var ready = false
    var shown = false
    var selected = false
    var completion: ((Boolean) -> Unit)? = null
    val renderer: NCHandoffVideo = NCHandoffVideo(container,object: NCHandoffVideo.Observer {
      override fun presented(view: TextureView, segment: Int, positionMs: Int, atNs: Long) {
        if (active !== this@Slot || ended) return
        if (ready) { if (shown) observed(view,renderer.status()["sourceFrame"] as Int,atNs); return }
        val source = renderer.status()["sourceFrame"] as? Int
        if (source != first || segment != 0 || positionMs != 0) { clear(key) {}; return }
        renderer.setPaused(true); ready = true
        observed(view,source,atNs)
        if (active !== this@Slot || ended) return
        val callback = completion; completion = null; callback?.invoke(true)
      }
      override fun failed(reason: String) { if (active === this@Slot) clear(key) {} }
    })
  }
  private var active: Slot? = null
  private var lastView: TextureView? = null
  private var fadeImage: ImageView? = null
  private var fadeBitmap: android.graphics.Bitmap? = null
  private var fadeMs = 0
  private var fading = false
  var fadeCount = 0; private set
  private fun clearFade() {
    fadeImage?.animate()?.cancel();fadeImage?.let { host.removeView(it);it.setImageDrawable(null) }
    fadeImage=null;fadeBitmap?.recycle();fadeBitmap=null;fadeMs=0;fading=false
  }
  fun beginFade(milliseconds: Int) {
    clearFade()
    if(milliseconds<=0)return
    val picture=lastView?.bitmap ?: return
    val image=ImageView(host.context);image.scaleType=ImageView.ScaleType.FIT_XY;image.setImageBitmap(picture)
    fadeBitmap=picture;fadeImage=image;fadeMs=milliseconds.coerceAtMost(5000)
    // Exactly one outgoing displayed picture, only on a changed motion. No
    // extra decoder, file transfer or animation restart on repeated mood tags.
    host.addView(image,FrameLayout.LayoutParams(-1,-1))
  }
  private val retiring = mutableSetOf<Slot>()
  fun layout() { active?.renderer?.layout() }
  fun ready(key: Long): Boolean = active?.let { it.key == key && it.ready && !it.ended } == true
  fun heard(key: Long, samples: Int): Boolean {
    val slot = active ?: return false
    if (slot.key != key || !slot.ready || slot.ended || samples < 0) return false
    slot.renderer.limitTo(samples/2000)
    if (!slot.shown) {
      slot.shown = true; slot.container.bringToFront()
      // The prepared first image was observed behind the outgoing layer.
      // Confirm its selection before advancing or accepting file pictures.
      slot.renderer.observeSelected {
        // This decoder prepares the opening only. The buffered file player
        // supplies subsequent pictures; two advancing players would compete.
        if (active === slot && slot.shown && !slot.ended) { slot.selected = true }
      }
    }
    return true
  }
  fun cover() { clearFade();active?.let { it.shown = false; it.selected = false; it.container.alpha = 0f; it.renderer.setPaused(true) } }
  fun stream(key: Long, frame: VideoFrame, shown: (TextureView,Long)->Unit): Boolean {
    val slot = active ?: return false
    if (slot.key != key || !slot.ready || !slot.shown || !slot.selected || slot.ended) return false
    return slot.renderer.streamFrame(frame) { view,at ->
      if (active === slot && slot.shown && !slot.ended) {
        lastView=view;slot.container.alpha = 1f; slot.container.bringToFront()
        fadeImage?.let { image ->
          image.bringToFront()
          if(!fading){fading=true;fadeCount++;image.animate().alpha(0f).setDuration(fadeMs.toLong()).withEndAction { if(fadeImage===image)clearFade() }.start()}
        }
        shown(view,at)
      }
    }
  }
  fun prepare(owner: String, key: Long, media: String, file: File, indices: IntArray, sourceCount: Int, done: (Boolean) -> Unit) {
    if (active != null || retiring.isNotEmpty() || key !in 1..2147483647L || indices.size !in 1..12) { done(false); return }
    val slot = Slot(key,indices[0]); active = slot; slot.completion = done
    // Keep traversable for TextureView readiness, behind the outgoing image.
    host.addView(slot.container,0,FrameLayout.LayoutParams(-1,-1))
    if (!slot.renderer.begin(owner,media,indices,sourceCount)) { clear(key) {}; return }
    slot.renderer.append(owner,media,0,file) { accepted -> if (!accepted && active === slot) clear(key) {} }
  }
  fun clear(key: Long, done: (Boolean) -> Unit) {
    val slot = active
    if (slot != null && slot.key != key) { done(false); return }
    clearFade();lastView=null
    if (slot != null) {
      active = null; slot.ended = true; retiring.add(slot)
      val callback = slot.completion; slot.completion = null; callback?.invoke(false)
    }
    val pending = retiring.filter { it.key == key }
    if (pending.isEmpty()) { done(true); return }
    var remaining = pending.size; var safe = true
    pending.forEach { old -> old.renderer.clearDetached { detached ->
      if (detached) { old.renderer.close(); host.removeView(old.container); retiring.remove(old) }
      safe = safe && detached; remaining--; if (remaining == 0) done(safe)
    } }
  }
  fun clearAll(done: (Boolean) -> Unit) {
    val key = active?.key ?: retiring.firstOrNull()?.key
    if (key == null) done(true) else clear(key,done)
  }
}
