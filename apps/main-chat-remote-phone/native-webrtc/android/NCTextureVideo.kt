package expo.modules.audio

import android.content.Context
import android.graphics.SurfaceTexture
import android.view.Gravity
import android.view.TextureView
import android.widget.FrameLayout
import com.oney.WebRTCModule.EglUtils
import org.webrtc.EglBase
import org.webrtc.EglRenderer
import org.webrtc.GlRectDrawer
import org.webrtc.VideoFrame
import org.webrtc.VideoSink

/** Texture-backed WebRTC output so local/video surfaces compose with real alpha. */
internal class NCTextureVideo(context: Context, private val displayed: () -> Unit) :
  TextureView(context), TextureView.SurfaceTextureListener, VideoSink {
  private val renderer = EglRenderer("nc-av-texture")
  @Volatile private var closed = false
  private var frameWidth = 1; private var frameHeight = 1
  private var layoutHost: android.view.View? = null
  private val hostLayout = android.view.View.OnLayoutChangeListener { _,l,t,r,b,ol,ot,or,ob ->
    if (r-l != or-ol || b-t != ob-ot) layoutVideo()
  }
  private val trackedLock = Any()
  private var trackedBusy = false
  private var trackedRevision = 0
  private var trackedRendered = false
  private var trackedTexture = false
  private var trackedCallback: (() -> Unit)? = null
  private var queuedTracked: Pair<VideoFrame,()->Unit>? = null
  init {
    isOpaque = false
    renderer.init(EglUtils.getRootEglBaseContext(), EglBase.CONFIG_PLAIN, GlRectDrawer())
    surfaceTextureListener = this
  }
  override fun onSurfaceTextureAvailable(surface: SurfaceTexture, width: Int, height: Int) {
    if (!closed) renderer.createEglSurface(surface)
  }
  override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture, width: Int, height: Int) {}
  override fun onSurfaceTextureUpdated(surface: SurfaceTexture) { if (!closed) {
    displayed()
    val token = synchronized(trackedLock) { trackedRevision }
    post { if (token == synchronized(trackedLock) { trackedRevision }) { trackedTexture = true; confirmTracked() } }
  } }
  override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean {
    if (closed) return true
    renderer.releaseEglSurface { surface.release() }; return false
  }
  override fun onAttachedToWindow() {
    super.onAttachedToWindow()
    // Nested idle/opening containers resize after NCAVView's outer callback.
    // Observe our actual parent so unchanged video dimensions are refitted too.
    layoutHost = parent as? android.view.View
    layoutHost?.addOnLayoutChangeListener(hostLayout)
    layoutVideo()
  }
  override fun onDetachedFromWindow() {
    layoutHost?.removeOnLayoutChangeListener(hostLayout); layoutHost = null
    super.onDetachedFromWindow()
  }
  fun layoutVideo() {
    val host = parent as? android.view.View ?: return
    val scale = minOf(host.width.toFloat()/frameWidth, host.height.toFloat()/frameHeight)
    if (scale > 0) {
      val width = (frameWidth*scale).toInt().coerceAtLeast(1)
      val height = (frameHeight*scale).toInt().coerceAtLeast(1)
      layoutParams = FrameLayout.LayoutParams(width,height,Gravity.CENTER)
      // React Native can swallow a second parent pass requested during layout.
      // Apply the fitted child bounds now, just as Expo forces native layout.
      measure(MeasureSpec.makeMeasureSpec(width,MeasureSpec.EXACTLY),
        MeasureSpec.makeMeasureSpec(height,MeasureSpec.EXACTLY))
      val left = (host.width-width)/2; val top = (host.height-height)/2
      layout(left,top,left+width,top+height)
    }
  }
  override fun onFrame(frame: VideoFrame) {
    if (closed) return
    val width = frame.rotatedWidth; val height = frame.rotatedHeight
    post { if (!closed && (width != frameWidth || height != frameHeight)) {
      frameWidth = width; frameHeight = height; layoutVideo()
    } }
    renderer.setLayoutAspectRatio(width.toFloat()/height)
    renderer.onFrame(frame)
  }
  /** Decode-driven callers serialize submissions until both this render-thread
   * callback and a TextureView update are observed. A scale-zero frame listener
   * is not a GPU fence or display proof. Streaming callers are unchanged. */
  fun onFrameObserved(frame: VideoFrame, rendered: () -> Unit) {
    if (closed) return
    renderer.addFrameListener({ if (!closed) rendered() },0f)
    onFrame(frame)
  }
  /** Optional exact-frame observation for the transition. One submission at a
   * time, with one bounded successor. Both render and texture callbacks are needed;
   * callers may not equate onFrame() submission with presentation. */
  fun onFrameTracked(frame: VideoFrame, observed: () -> Unit) {
    val token = synchronized(trackedLock) {
      if (closed) return
      if (trackedBusy) {
        queuedTracked?.first?.release(); frame.retain(); queuedTracked = frame to observed
        return
      }
      trackedBusy = true; ++trackedRevision
    }
    frame.retain()
    post {
      try {
        if (closed || token != synchronized(trackedLock) { trackedRevision }) return@post
        trackedRendered = false; trackedTexture = false; trackedCallback = observed
        onFrameObserved(frame) { post {
          if (token == synchronized(trackedLock) { trackedRevision }) { trackedRendered = true; confirmTracked() }
        } }
        postDelayed({ if (token == synchronized(trackedLock) { trackedRevision }) clearTracked() },500)
      } finally { frame.release() }
    }
  }
  private fun confirmTracked() {
    if (!trackedRendered || !trackedTexture) return
    val callback = trackedCallback ?: return
    val queued = synchronized(trackedLock) { val next = queuedTracked; queuedTracked = null; next }
    clearTracked(); callback()
    if (queued != null) { try { onFrameTracked(queued.first,queued.second) } finally { queued.first.release() } }
  }
  private fun clearTracked() {
    synchronized(trackedLock) { trackedRevision++; trackedBusy = false; queuedTracked?.first?.release(); queuedTracked = null }
    trackedCallback = null; trackedRendered = false; trackedTexture = false
  }
  fun clearImage() { if (!closed) { post { clearTracked() }; renderer.clearImage() } }
  fun close() { if (!closed) { closed = true; synchronized(trackedLock) {
    trackedRevision++; queuedTracked?.first?.release(); queuedTracked = null
  }; renderer.release() } }
}
