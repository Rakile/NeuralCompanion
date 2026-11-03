package expo.modules.audio

import android.content.Context
import android.graphics.Matrix
import android.view.TextureView
import android.widget.FrameLayout
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import expo.modules.kotlin.AppContext
import expo.modules.kotlin.views.ExpoView
import expo.modules.kotlin.viewevent.EventDispatcher

/** Pixels from the registered muxed AudioPlayer, never another decoder/clock. */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
internal class NCMuxedTrialView(context:Context,appContext:AppContext):ExpoView(context,appContext) {
  override val shouldUseAndroidLayout=true
  // ExpoView is a LinearLayout. Give it one full-size child, then overlap
  // both video layers inside that child. bringToFront must change only z-order,
  // never consume the sibling's width or collapse the selected idle surface.
  private val canvas=FrameLayout(context)
  private val picture=TextureView(context)
  private var owner:AudioPlayer?=null
  private var requestedPlayer:AudioPlayer?=null
  private var windowDetached=false
  private var videoSize=VideoSize.UNKNOWN
  private var listener:Player.Listener?=null
  val onReady by EventDispatcher<Map<String,String>>()
  init {
    addView(canvas,LayoutParams(LayoutParams.MATCH_PARENT,LayoutParams.MATCH_PARENT))
    canvas.addView(picture,FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT,LayoutParams.MATCH_PARENT))
  }
  fun attach(player:AudioPlayer?) {
    requestedPlayer=player
    if(windowDetached)return
    if(owner===player && player?.ncMuxedVideoViewEligible==true)return
    detach()
    if(player?.ncMuxedVideoViewEligible!=true)return
    owner=player;videoSize=player.ref.videoSize
    // The same retained silent host follows this presentation view. Reparenting
    // does not create a decoder, reset its clock or acquire microphone/audio.
    val cached=player.ncCachedIdleHost
    // A contained idle picture has margins. They must cover the retained
    // speech texture too, not expose a second differently scaled avatar.
    cached.setBackgroundColor(android.graphics.Color.BLACK)
    (cached.parent as? android.view.ViewGroup)?.removeView(cached)
    canvas.addView(cached,0,FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT,LayoutParams.MATCH_PARENT))
    player.ncCachedSurfaceAvailable=true;player.ncCachedIdle?.surface(true)
    val observed=object:Player.Listener {
      override fun onVideoSizeChanged(value:VideoSize){
        if(owner===player && listener===this && player.ncMuxedVideoViewEligible){videoSize=value;fit()}
      }
      override fun onRenderedFirstFrame(){
        if(owner===player && listener===this && player.ncMuxedVideoViewEligible)onReady(mapOf("playerId" to player.id))
      }
    }
    listener=observed;player.ref.addListener(observed)
    player.ref.setVideoTextureView(picture);fit()
  }
  private fun detach() {
    val previous=owner;val observed=listener
    owner=null;listener=null
    previous?.let { player ->
      player.ncCachedSurfaceAvailable=false;player.ncCachedIdle?.surface(false)
      player.ref.clearVideoTextureView(picture)
      observed?.let { player.ref.removeListener(it) }
    }
  }
  private fun fit() {
    if(picture.width<1||picture.height<1||videoSize.width<1||videoSize.height<1)return
    val target=videoSize.width.toFloat()*videoSize.pixelWidthHeightRatio/videoSize.height
    val aspect=picture.width.toFloat()/picture.height
    val matrix=Matrix()
    if(target>aspect)matrix.setScale(1f,aspect/target,picture.width/2f,picture.height/2f)
    else matrix.setScale(target/aspect,1f,picture.width/2f,picture.height/2f)
    picture.setTransform(matrix)
    owner?.ncCachedIdle?.layout()
  }
  // Android may detach/reparent the retained view during fullscreen layout.
  // Its unchanged JS player prop is not delivered again on window attachment.
  override fun onDetachedFromWindow(){windowDetached=true;detach();super.onDetachedFromWindow()}
  override fun onAttachedToWindow(){
    super.onAttachedToWindow()
    windowDetached=false
    attach(requestedPlayer) // Rechecks eligibility; never grants or starts playback.
  }
  override fun onSizeChanged(w:Int,h:Int,oldw:Int,oldh:Int){super.onSizeChanged(w,h,oldw,oldh);picture.post { fit() }}
}
