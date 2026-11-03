package expo.modules.audio

import android.os.Handler
import android.os.Looper
import android.view.Surface
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.video.VideoFrameMetadataListener
import org.webrtc.EglBase
import org.webrtc.SurfaceTextureHelper
import org.webrtc.VideoFrame

/** Presents pixels from the EXISTING segment player. No decoder/player, RTP,
 * network pacing, audio device or receipt authority is created here. */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
internal class NCBufferedVideoSource(private val player:ExoPlayer,start:Int,frames:Int,egl:EglBase.Context,
  private val frame:(Int,VideoFrame)->Unit) {
  private val main=Handler(Looper.getMainLooper())
  private val timeline=NCBufferedVideoTimeline(start,frames)
  private val applicationThread=check(Looper.myLooper()==player.applicationLooper)
  private val texture=requireNotNull(SurfaceTextureHelper.create("nc-local-video",egl))
  private val surface=Surface(texture.surfaceTexture)
  @Volatile private var closed=false
  @Volatile private var playing=player.isPlaying
  private var prepared:Pair<Int,VideoFrame>?=null
  private var openingOffered=false
  @Volatile var decoded=false
    private set
  private val queued=java.util.concurrent.atomic.AtomicBoolean()
  private val textureObservations=java.util.concurrent.atomic.AtomicInteger()
  private val unmatchedTextures=java.util.concurrent.atomic.AtomicInteger()
  private val busyTextures=java.util.concurrent.atomic.AtomicInteger()
  private val metadataObservations=java.util.concurrent.atomic.AtomicInteger()
  private val metadata=VideoFrameMetadataListener { pts,release,_,_ ->
    timeline.submitted(pts,release)
    if(metadataObservations.incrementAndGet()<=3)
      android.util.Log.d("NC_BUFFERED_VIDEO","submission ptsUs=$pts releaseNs=$release")
  }
  private val listener=object:Player.Listener {
    override fun onIsPlayingChanged(value:Boolean) {
      playing=value
      if(value && !closed){
        val ready=prepared;prepared=null
        if(ready!=null)try{frame(ready.first,ready.second)}finally{ready.second.release()}
      }
    }
    override fun onVideoSizeChanged(size:VideoSize) { resize(size) }
    override fun onPositionDiscontinuity(old:Player.PositionInfo,next:Player.PositionInfo,reason:Int) {
      timeline.clear();prepared?.second?.release();prepared=null
    }
  }
  private fun resize(size:VideoSize) {
    if(!closed && size.width>0 && size.height>0)texture.setTextureSize(size.width,size.height)
  }
  init {
    check(Looper.myLooper()==player.applicationLooper)
    resize(player.videoSize)
    texture.startListening { picture ->
      textureObservations.incrementAndGet()
      val tick=timeline.observed(picture.timestampNs)
      if(tick==null && unmatchedTextures.incrementAndGet()<=3)
        android.util.Log.d("NC_BUFFERED_VIDEO","unmatched timestampNs=${picture.timestampNs}")
      else if(!closed && queued.get())busyTextures.incrementAndGet()
      if(tick!=null && !closed && queued.compareAndSet(false,true)) {
        // updateTexImage runs on this decoder GL context; presentation uses
        // another shared context. Submit that update before handing off the
        // texture. A CPU readback used to hide stale cross-context pixels.
        android.opengl.GLES20.glFlush()
        // A paused pre-roll picture is decoded readiness, not playback. Keep
        // one independent image so starting this same player can present it.
        // Holding the decoder's sole texture while paused would block decoding.
        val delivery=if(!playing){
          val pixels=picture.buffer.toI420()
          if(pixels==null){queued.set(false);return@startListening}
          VideoFrame(pixels,picture.rotation,picture.timestampNs)
        }else{picture.retain();picture}
        main.post { try { if(!closed){
          if(!player.isPlaying){prepared?.second?.release();delivery.retain();prepared=tick to delivery}
          decoded=true;frame(tick,delivery)
        } } finally { delivery.release();queued.set(false) } }
      }
    }
    try { player.addListener(listener);player.setVideoFrameMetadataListener(metadata);player.setVideoSurface(surface) }
    catch(error:RuntimeException){close();throw error}
  }
  /** The guarded audio caller may expose the already-decoded opening while
   * video motion still waits for advancing audio. Never selects a future segment. */
  fun presentOpening(samples:Int):Boolean {
    check(Looper.myLooper()==player.applicationLooper)
    val ready=prepared?:return false
    if(closed||openingOffered||ready.first!=0||samples !in 0..6000)return false
    openingOffered=true // Before callback: presentation can resample this owner.
    frame(ready.first,ready.second)
    return true
  }
  fun close() {
    check(Looper.myLooper()==player.applicationLooper)
    if(closed)return
    closed=true;timeline.clear();player.removeListener(listener)
    android.util.Log.d("NC_BUFFERED_VIDEO","retired decoded=$decoded submissions=${metadataObservations.get()} textures=${textureObservations.get()} unmatched=${unmatchedTextures.get()} busy=${busyTextures.get()}")
    prepared?.second?.release();prepared=null
    player.clearVideoFrameMetadataListener(metadata);player.clearVideoSurface(surface)
    texture.stopListening();surface.release();texture.dispose()
  }
}
