package expo.modules.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.content.pm.ApplicationInfo
import android.media.audiofx.Visualizer
import android.media.AudioRouting
import android.media.AudioTrack
import android.util.Log
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.Renderer
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector
import androidx.media3.exoplayer.audio.AudioRendererEventListener
import androidx.media3.exoplayer.video.VideoRendererEventListener
import androidx.media3.exoplayer.analytics.AnalyticsListener
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.audio.DefaultAudioSink
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.LoadEventInfo
import androidx.media3.exoplayer.source.MediaLoadData
import expo.modules.audio.service.AudioControlsService
import expo.modules.kotlin.AppContext
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.sharedobjects.SharedRef
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.onStart
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID
import java.lang.ref.WeakReference

private const val PLAYBACK_STATUS_UPDATE = "playbackStatusUpdate"
private const val AUDIO_SAMPLE_UPDATE = "audioSampleUpdate"
private const val SEEK_JUMP_INTERVAL_MS: Long = 10_000

/** Observes the very AudioTrack used by this player's normal Media3 sink. */
@UnstableApi
class NCAudioRouteMonitor {
  internal val presentation = NCContinuousMuxedObservation()
  // This constructor runs before ExoPlayer.Builder may construct its sink.
  // Track ownership is independent of the route monitor's weak references.
  internal val outputController = NCContinuousMuxedSinkController()
  @Volatile private var expected: NCCommunicationRoute.Token? = null
  @Volatile private var item: String? = null
  @Volatile private var currentTrack = WeakReference<AudioTrack>(null)
  fun prepare(token: NCCommunicationRoute.Token?, identity: String?) {
    expected = token; item = identity
  }
  fun observe(track: AudioTrack, attributes: AudioAttributes) {
    if (attributes.usage != C.USAGE_VOICE_COMMUNICATION) return
    currentTrack = WeakReference(track)
    track.addOnRoutingChangedListener(AudioRouting.OnRoutingChangedListener {
      val token = expected
      if (token != null) verify(track, token, item)
    }, Handler(Looper.getMainLooper()))
  }
  fun verifyPlaying() {
    val token = expected ?: return
    val identity = item
    currentTrack.get()?.let { verify(it, token, identity) }
  }
  private fun verify(track: AudioTrack, token: NCCommunicationRoute.Token, identity: String?) {
    if (currentTrack.get() !== track || expected !== token || item != identity || !NCCommunicationRoute.shared.isCurrent(token)) return
    if (NCCommunicationRoute.shared.isPreparing(token.ticket)) return
    if (track.playState != AudioTrack.PLAYSTATE_PLAYING) return
    val route = track.routedDevice
    if (!NCCommunicationRoute.shared.accepts(token, route?.id, route?.type))
      NCPlaybackGuard.shared.retire(token.ticket, NCPlaybackGuard.RetirementCause.ROUTE_CHANGE)
  }
}

/** Performance guard only; never output/ownership evidence. Media3 1.8.0
 * queries AudioSystem even when retaining its compatible active AudioTrack.
 * Read the exact delegate's CURRENT configuration, not a stale provider size.
 * Unknown private layout/route simply keeps Media3's normal configuration. */
internal class NCContinuousPcmBufferReuse(private val sink:Any,private val accepted:()->AudioTrack?,
  private val routeSnapshot:(AudioTrack)->Pair<Int,Int>?) {
  private data class Provider(val track:java.lang.ref.WeakReference<AudioTrack>,val attributes:AudioAttributes,
    val session:Int,val thread:Thread)
  private var record:Provider?=null
  private var previousRoute:Pair<Int,Int>?=null
  fun provider(track:AudioTrack,attributes:AudioAttributes) {
    record=Provider(java.lang.ref.WeakReference(track),attributes,track.audioSessionId,Thread.currentThread());previousRoute=null
  }
  private fun read(value:Any,name:String):Any?=value.javaClass.getDeclaredField(name).let {it.isAccessible=true;it.get(value)}
  private fun decline():Int? {previousRoute=null;return null}
  fun size(rate:Int,channels:Int,encoding:Int):Int? {
    val provider=record?:return null
    if(Thread.currentThread()!==provider.thread)return null
    return try {
      val track=provider.track.get()?:return decline()
      if(rate!=48000 ||channels!=1 ||encoding!=2 ||accepted()!==track
        ||read(sink,"audioTrack")!==track ||track.state!=AudioTrack.STATE_INITIALIZED
        ||track.audioSessionId!=provider.session ||read(sink,"audioSessionId")!=provider.session
        ||read(sink,"audioAttributes")!=provider.attributes ||read(sink,"pendingConfiguration")!=null)return decline()
      val config=read(sink,"configuration")?:return decline()
      if(read(config,"outputMode")!=0 ||read(config,"outputSampleRate")!=48000
        ||read(config,"outputChannelConfig")!=4 ||read(config,"outputEncoding")!=2
        ||read(config,"outputPcmFrameSize")!=2)return decline()
      val bytes=read(config,"bufferSize") as? Int?:return decline()
      if(bytes<=0 ||bytes%2!=0)return decline()
      val route=routeSnapshot(track)?:return decline()
      if(route.first<=0 ||route.second<=0)return decline()
      if(previousRoute!=route){previousRoute=route;return null}
      bytes
    }catch(_:Exception){decline()}
  }
}

/** Android's routedDevice lookup can wait for AudioManager's port cache. This
 * optional observer never runs that lookup on main or Media3's output thread.
 * Events invalidate before lookup; replaced/closed providers cannot publish.
 * This snapshot is only a buffer optimization hint, never route authority. */
internal class NCContinuousPcmRouteObserver {
  private data class RouteEvidence(val revision:Long,val route:Pair<Int,Int>)
  private class Registration(track:AudioTrack) {
    val track=java.lang.ref.WeakReference(track)
    val route=java.util.concurrent.atomic.AtomicReference<RouteEvidence?>(null)
    val revision=java.util.concurrent.atomic.AtomicLong()
    val busy=java.util.concurrent.atomic.AtomicBoolean()
    val retry=java.util.concurrent.atomic.AtomicReference<java.util.concurrent.ScheduledFuture<*>?>(null)
    lateinit var listener:AudioRouting.OnRoutingChangedListener
  }
  private val worker=java.util.concurrent.ScheduledThreadPoolExecutor(1) {work->
    Thread(work,"NCPcmRoute").apply {isDaemon=true}
  }.apply {removeOnCancelPolicy=true;executeExistingDelayedTasksAfterShutdownPolicy=false}
  @Volatile private var current:Registration?=null
  @Volatile private var closed=false
  @Synchronized fun provider(track:AudioTrack) {
    if(closed)return
    val old=current;val next=Registration(track)
    next.listener=AudioRouting.OnRoutingChangedListener {
      if(!closed &&current===next){next.revision.incrementAndGet();next.route.set(null);enqueue(next)}
    }
    current=next;old?.retry?.getAndSet(null)?.cancel(false)
    try {worker.execute {
      remove(old)
      if(!closed &&current===next)try {
        next.track.get()?.addOnRoutingChangedListener(next.listener,Handler(Looper.getMainLooper()))
        enqueue(next)
      }catch(_:RuntimeException){next.route.set(null)}
    }}catch(_:RuntimeException){current=null}
  }
  private fun remove(registration:Registration?) {
    try {registration?.track?.get()?.removeOnRoutingChangedListener(registration.listener)}catch(_:RuntimeException) {}
  }
  private fun enqueue(registration:Registration,attempt:Int=0) {
    registration.retry.getAndSet(null)?.cancel(false)
    if(closed ||current!==registration ||!registration.busy.compareAndSet(false,true))return
    try {worker.execute {
      val revision=registration.revision.get()
      try {
        val device=if(!closed &&current===registration)registration.track.get()?.routedDevice else null
        val route=device?.let {if(it.id>0 &&it.type>0)it.id to it.type else null}
        if(!closed &&current===registration &&registration.revision.get()==revision)
          registration.route.set(route?.let {RouteEvidence(revision,it)})
      }catch(_:RuntimeException){registration.route.set(null)}
      finally {
        registration.busy.set(false)
        if(!closed &&current===registration){
          if(registration.revision.get()!=revision)enqueue(registration)
          else if(registration.route.get()==null &&attempt<5)try {
            val retry=worker.schedule({
              registration.retry.set(null)
              if(registration.revision.get()==revision)enqueue(registration,attempt+1)
            },100,java.util.concurrent.TimeUnit.MILLISECONDS)
            registration.retry.getAndSet(retry)?.cancel(false)
            // An event/close may occur between scheduling and publishing the
            // future. Cancel that stale timer too, without interrupting lookup.
            if(closed ||current!==registration ||registration.revision.get()!=revision)
              if(registration.retry.compareAndSet(retry,null))retry.cancel(false)
          }catch(_:RuntimeException) {}
        }
      }
    }}catch(_:RuntimeException){registration.busy.set(false)}
  }
  fun snapshot(track:AudioTrack):Pair<Int,Int>? {
    val selected=current?:return null
    val evidence=selected.route.get()?:return null
    return if(!closed &&selected.track.get()===track &&evidence.revision==selected.revision.get())evidence.route else null
  }
  @Synchronized fun close() {
    if(closed)return
    closed=true;val old=current;current=null;old?.route?.set(null);old?.retry?.getAndSet(null)?.cancel(false)
    try {worker.execute {remove(old)}}catch(_:RuntimeException) {}
    try {worker.shutdown()}catch(_:RuntimeException) {}
  }
}

@UnstableApi
private fun ncRenderers(context: Context, monitor: NCAudioRouteMonitor) = object : DefaultRenderersFactory(context) {
  private var outputSlot:NCContinuousMuxedSinkController.SinkSlot?=null
  override fun buildVideoRenderers(context:Context,extensionRendererMode:Int,mediaCodecSelector:MediaCodecSelector,
    enableDecoderFallback:Boolean,eventHandler:Handler,listener:VideoRendererEventListener,
    allowedJoiningTimeMs:Long,out:ArrayList<Renderer>) {
    if(extensionRendererMode==EXTENSION_RENDERER_MODE_OFF) {
      // Media3 builds video BEFORE the sink. Resolve the same exact installed
      // slot on playback; do not capture null or construct a second sink.
      out.add(NCContinuousMuxedVideoRenderer(context,codecAdapterFactory,mediaCodecSelector,
        allowedJoiningTimeMs,enableDecoderFallback,eventHandler,listener,50,monitor.presentation,
        monitor.outputController,{outputSlot}))
    } else super.buildVideoRenderers(context,extensionRendererMode,mediaCodecSelector,
      enableDecoderFallback,eventHandler,listener,allowedJoiningTimeMs,out)
  }
  override fun buildAudioSink(context: Context, enableFloatOutput: Boolean, enableAudioTrackPlaybackParams: Boolean): AudioSink {
    val controller=monitor.outputController
    val slot=controller.openSink()
    outputSlot=slot
    var bufferReuse:NCContinuousPcmBufferReuse?=null
    val routeObserver=NCContinuousPcmRouteObserver()
    val sink=DefaultAudioSink.Builder(context)
      .setEnableFloatOutput(enableFloatOutput)
      .setEnableAudioTrackPlaybackParams(enableAudioTrackPlaybackParams)
      .setAudioTrackProvider { config, attributes, sessionId, audioContext ->
        DefaultAudioSink.AudioTrackProvider.DEFAULT.getAudioTrack(config, attributes, sessionId, audioContext).also {
          if(slot!=null) {
            val record=controller.providerCreated(slot,it)
              ?:throw IllegalStateException("NC native provider ownership unavailable")
            check(controller.providerReady(slot,record)) {"NC native provider origin rejected"}
            // Pixel Android 17 routes can require more PCM than a short idle
            // period contains. Keep buffer capacity, but start within 100 ms.
            if(controller.isTargeted(slot) && android.os.Build.VERSION.SDK_INT>=37) {
              it.setStartThresholdInFrames(minOf(it.startThresholdInFrames,maxOf(1,it.sampleRate/10)))
            }
          }
          monitor.observe(it, attributes)
          if(slot!=null && !controller.isTargeted(slot))monitor.presentation.observe(it)
          bufferReuse?.provider(it,attributes)
          if(slot!=null &&controller.isTargeted(slot))routeObserver.provider(it)
        }
      }.build()
    if(slot!=null)check(controller.bindDelegate(slot,sink)) {"NC native sink ownership unavailable"}
    if(slot!=null)bufferReuse=NCContinuousPcmBufferReuse(sink,{
      controller.capturedTrack(slot)?.takeIf {record->controller.isTargeted(slot)
        &&controller.ownsTrack(slot,record,record.actual)}?.actual
    },routeObserver::snapshot)
    return if(slot!=null)NCContinuousMuxedAudioSink(sink,monitor.presentation,controller,slot,
      {rate,channels,encoding->bufferReuse?.size(rate,channels,encoding)},routeObserver::close) else sink
  }
  override fun buildAudioRenderers(context:Context,extensionRendererMode:Int,mediaCodecSelector:MediaCodecSelector,
    enableDecoderFallback:Boolean,audioSink:AudioSink,eventHandler:Handler,
    audioRendererEventListener:AudioRendererEventListener,out:ArrayList<Renderer>) {
    if(extensionRendererMode==EXTENSION_RENDERER_MODE_OFF) {
      val slot=checkNotNull(outputSlot) {"NC renderer requires its exact native sink"}
      out.add(NCContinuousMuxedAudioRenderer(context,codecAdapterFactory,mediaCodecSelector,
        enableDecoderFallback,eventHandler,audioRendererEventListener,audioSink,monitor.presentation,
        monitor.outputController,slot))
    } else {
      monitor.presentation.fence("extension_renderer")
      super.buildAudioRenderers(context,extensionRendererMode,mediaCodecSelector,
        enableDecoderFallback,audioSink,eventHandler,audioRendererEventListener,out)
    }
  }
}

@UnstableApi
class AudioPlayer(
  context: Context,
  appContext: AppContext,
  source: MediaSource?,
  private val updateInterval: Double,
  private val ncRouteMonitor: NCAudioRouteMonitor = NCAudioRouteMonitor()
) : SharedRef<ExoPlayer>(
  ExoPlayer.Builder(context, ncRenderers(context, ncRouteMonitor))
    .apply {
      if (source?.mediaItem?.localConfiguration?.uri?.scheme == NCProgressivePcmMediaSource.SCHEME)
        setLoadControl(NCProgressivePcmMediaSource.loadControl())
    }
    .setLooper(context.mainLooper)
    .setAudioAttributes(AudioAttributes.DEFAULT, false)
    .setHandleAudioBecomingNoisy(false)
    .setPauseAtEndOfMediaItems(false)
    .setSuppressPlaybackOnUnsuitableOutput(false)
    .setSeekForwardIncrementMs(SEEK_JUMP_INTERVAL_MS)
    .setSeekBackIncrementMs(SEEK_JUMP_INTERVAL_MS)
    .build(),
  appContext
), NCPlaybackActions {
  val id = UUID.randomUUID().toString()
  var preservesPitch = true
  var isPaused = false
  // Set only for an external audio-focus interruption, never for a user pause.
  var focusInterrupted = false
  internal val ncUserPauseLock=Any()
  var isMuted = false
  var previousVolume = 1f
  var onPlaybackStateChange: ((Boolean) -> Unit)? = null
  @Volatile private var sourceGeneration = 0L
  @Volatile private var nativePlayerErrorCode: Int? = null
  @Volatile private var playingSnapshot = false
  @Volatile private var releasedSnapshot = false
  private val ncMuxedSources = NCMuxedTrialSourceOwner(NCPlaybackGuard.shared, this,
    NCPlaybackGuard.shared.newBinding(this))
  internal val ncPlaybackBinding get() = ncMuxedSources.binding
  internal val ncContinuousPresentation get() = ncRouteMonitor.presentation
  internal val ncCachedIdleHost by lazy {android.widget.FrameLayout(context).apply {alpha=0f}}
  internal var ncCachedIdle:NCOrderedCachedVideo?=null
  internal var ncCachedSurfaceAvailable=false
  internal fun ncPostCachedProof(work:()->Unit)=ncPostContinuousProof(work)
  internal val ncContinuousOutputController get() = ncRouteMonitor.outputController
  // Native queue attachment is inert until the current capability/RPC gate is
  // enabled. It reuses this registered player, route, surface and Guard binding.
  @Volatile internal var ncContinuousQueue:NCContinuousMuxedQueue?=null
    private set
  @Volatile internal var ncContinuousFixtureEnabled=false
    private set
  // Sticky even while service start is pending: an old forwarding wrapper must
  // never reach a later diagnostic continuous run on this same player.
  private var ncMediaSessionExposed=false
  internal fun ncEnableContinuousFixture(diagnosticBuild:Boolean):Boolean {
    check(Looper.myLooper()==ref.applicationLooper)
    if(!diagnosticBuild || ncMediaSessionExposed || releasedSnapshot || ncMuxedTrialRetired || !ncMuxedSources.enabled || sourceGeneration!=0L
      || ncContinuousPendingSource!=null || ncContinuousQueue!=null || ncMuxedTrialOwner!=null
      || ncPlaybackBinding.attempted || ref.isPlaying || ref.playWhenReady)return false
    ncContinuousFixtureEnabled=true;return true
  }
  private var ncContinuousPendingSource:MediaSource?=null
  private var ncContinuousPendingQueue:NCContinuousMuxedQueue?=null
  private var ncContinuousEnrollmentAttempted=false
  private var ncContinuousAttaching=false
  private var ncContinuousSettling=false
  private var ncContinuousSettlement:NCContinuousMuxedSinkController.SinkSettlement?=null
  private var ncContinuousIdleRetirement:NCMuxedTrialSourceOwner.Retirement?=null
  private var ncContinuousIdleSettlement:NCContinuousMuxedSinkController.IdleSettlement?=null
  private var ncContinuousGeneration=0L
  private var ncContinuousSlot:NCContinuousMuxedSinkController.SinkSlot?=null
  /** Main-actor external controls deny this exact pending/enrolled owner before
   * any raw player effect, including BUFFERING where isPlaying is false.
   * Retain failed Queue/source ownership; this is not output settlement.
   */
  internal fun ncFenceContinuousControl(cause:String) {
    val queue=ncContinuousQueue?:ncContinuousPendingQueue
    if(queue==null && ncContinuousPendingSource==null)return
    check(Looper.myLooper()==ref.applicationLooper)
    val controller=ncContinuousOutputController
    (ncContinuousSlot?:controller.soleSink())?.let {if(controller.isTargeted(it))controller.invalidate(it,cause)}
    queue?.fence(cause)
    ncPlaybackBinding.remove()
    // A reservation before Queue registration has no model/permit to cancel.
    // Use the existing generation fence so no delayed startup can adopt it.
    if(queue==null)sourceGeneration++
  }
  private val ncContinuousProofWorker = lazy {
    java.util.concurrent.Executors.newSingleThreadExecutor {work->
      Thread(work,"NCContinuousProof").apply {isDaemon=true}
    }
  }
  private var ncContinuousProofClosed=false
  private fun ncPostContinuousProof(work:()->Unit):Boolean = synchronized(ncContinuousProofWorker) {
    if(ncContinuousProofClosed)return@synchronized false
    try {ncContinuousProofWorker.value.execute(work);true}
    catch(_:java.util.concurrent.RejectedExecutionException) {false}
  }
  private fun ncCloseContinuousProofWorker() = synchronized(ncContinuousProofWorker) {
    // Guard removal fences output first. Drain already posted proof/cleanup;
    // never create a thread merely to close an otherwise unused player.
    ncContinuousProofClosed=true
    if(ncContinuousProofWorker.isInitialized())ncContinuousProofWorker.value.shutdown()
  }

  /** Reserve the real timeline before binding the item, but install/prepare its
   * decoder/provider only after initial layout ACK and exact output enrollment.
   * Used-sink startup requires the separate positive settlement transaction;
   * ordinary previously-used sources are refused, never replaced by a player.
   */
  internal fun ncPrepareContinuousTimeline(source:MediaSource):Boolean {
    fun allowed(name:String,value:Boolean):Boolean {
      if(!value)try{ncDiagnosticObserver.decision("ordered.prepare.$name",false)}catch(_:Exception){}
      return value
    }
    check(allowed("application_thread",Looper.myLooper()==ref.applicationLooper))
    if(!allowed("media_session_hidden",!ncMediaSessionExposed)
      || !allowed("player_not_released",!releasedSnapshot)
      || !allowed("trial_not_retired",!ncMuxedTrialRetired)
      || !allowed("sources_enabled",ncMuxedSources.enabled)
      || !allowed("prior_source_settled",sourceGeneration==0L || ncContinuousSettlement?.isConsumed==false || ncContinuousIdleSettlement?.isConsumed==false)
      || !allowed("pending_source_empty",ncContinuousPendingSource==null)
      || !allowed("queue_empty",ncContinuousQueue==null)
      || !allowed("not_attaching",!ncContinuousAttaching)
      || !allowed("not_settling",!ncContinuousSettling)
      || !allowed("trial_owner_empty",ncMuxedTrialOwner==null)
      || !allowed("trial_receipt_empty",ncMuxedTrialReceipt==null)
      || !allowed("play_when_ready_false",!ref.playWhenReady)
      || !allowed("binding_not_attempted",!ncPlaybackBinding.attempted))return false
    sourceGeneration++
    ncContinuousGeneration=sourceGeneration;ncContinuousPendingSource=source
    ncContinuousEnrollmentAttempted=false
    // setMediaSource can auto-prepare on an already prepared player. The old
    // source has positive settlement above; quiesce before reserving new input.
    // Installing the empty concat here would snapshot zero windows before its
    // initial append ACK and leave the later preparation at native END.
    ref.stop()
    return true
  }
  internal fun ncStageContinuousIdentity(model:NCContinuousMuxedPresentation,mediaId:String,
    key:NCContinuousMuxedClipKey):Boolean {
    val accepted=ncContinuousIdleSettlement?.let {
      ncContinuousPresentation.stageIdleSettledLiveIdentity(model,mediaId,key,it)
    } ?: ncContinuousSettlement?.let {
      ncContinuousPresentation.stageSettledLiveIdentity(model,mediaId,key,it)
    } ?: ncContinuousPresentation.stageLiveIdentity(model,mediaId,key)
    ncDiagnosticObserver.sourceStaged(mediaId,accepted)
    return accepted
  }
  internal fun ncOwnsContinuousTimeline(source:MediaSource):Boolean {
    check(Looper.myLooper()==ref.applicationLooper)
    return !releasedSnapshot && !ncMuxedTrialRetired && ncMuxedSources.enabled
      && sourceGeneration==ncContinuousGeneration && ncContinuousPendingSource===source
  }
  internal fun ncRegisterUnpreparedContinuousQueue(queue:NCContinuousMuxedQueue):Boolean {
    check(Looper.myLooper()==ref.applicationLooper)
    if(releasedSnapshot || ncMuxedTrialRetired || ncContinuousPendingSource==null || ncContinuousPendingQueue!=null
      || ncContinuousQueue!=null || ncContinuousEnrollmentAttempted || ncContinuousAttaching || ncContinuousSettling
      || sourceGeneration!=ncContinuousGeneration || !queue.matchesBinding(ncPlaybackBinding))return false
    ncContinuousPendingQueue=queue;return true
  }
  internal fun ncCloseUnenrolledContinuousQueue(queue:NCContinuousMuxedQueue,
    readers:NCContinuousMuxedQueue.DetachedReaders,done:(Boolean)->Unit):Boolean {
    check(Looper.myLooper()==ref.applicationLooper)
    if(releasedSnapshot || ncMuxedTrialRetired || ncContinuousPendingQueue!==queue || ncContinuousPendingSource==null
      || ncContinuousQueue!=null || ncContinuousEnrollmentAttempted || ncContinuousAttaching || ncContinuousSettling
      || sourceGeneration!=ncContinuousGeneration || !queue.matchesBinding(ncPlaybackBinding) || !readers.matches(queue))return false
    val controller=ncContinuousOutputController;val slot=controller.soleSink()?:return false
    ncContinuousSettling=true
    val posted=controller.postOutput {
      val denied=controller.closeUnenrolled(slot,queue,readers)
      if(!Handler(ref.applicationLooper).post {
        val current=!releasedSnapshot && !ncMuxedTrialRetired && ncContinuousPendingQueue===queue
          && ncContinuousQueue==null && !ncContinuousEnrollmentAttempted && sourceGeneration==ncContinuousGeneration
        if(denied && current) {
          ncMuxedTrialRetired=true
          ncMuxedSources.close {ncClearMuxedSource()}
          ncContinuousPendingQueue=null;ncContinuousPendingSource=null
        }
        ncContinuousSettling=false;done(denied && current)
      })done(false)
    }
    if(!posted)ncContinuousSettling=false
    return posted
  }

  /** Only the Desktop-planned sealed idle endpoint may enter this initial
   * transfer. Retire its real source/fences before joining off-main; neither
   * the returned token nor source revision is sink-release evidence.
   */
  internal fun ncBeginInitialIdleRetirement():NCMuxedTrialSourceOwner.Retirement? {
    check(Looper.myLooper()==ref.applicationLooper)
    val idle=ncMuxedTrialOwner?:return null
    if(releasedSnapshot || ncMuxedTrialRetired || !ncMuxedSources.enabled || !idle.silentEnded
      || ncContinuousQueue!=null || ncContinuousPendingSource!=null || ncContinuousAttaching || ncContinuousSettling
      || ncContinuousIdleRetirement!=null || ncContinuousSettlement!=null || ncMuxedTrialReceipt!=null
      || ncPlaybackBinding.ticket==null || ncPlaybackBinding.requestId!=null || ncPlaybackBinding.chunkId!=null
      || ref.isPlaying || playingSnapshot)return null
    return ncMuxedSources.retireWithReaders(idle,ncMuxedTrialReaderFences.toList(),::ncClearMuxedSource)
      ?.also {ncContinuousIdleRetirement=it}
  }
  internal fun ncSettleInitialIdle(done:(Boolean)->Unit):Boolean {
    check(Looper.myLooper()==ref.applicationLooper)
    val closure=ncContinuousIdleRetirement?:return false
    val controller=ncContinuousOutputController;val slot=controller.soleSink()?:return false
    if(releasedSnapshot || ncMuxedTrialRetired || ncContinuousQueue!=null || ncContinuousPendingSource!=null
      || ncContinuousAttaching || ncContinuousSettling || ncContinuousIdleSettlement?.isConsumed==true
      || !closure.matches(ncMuxedSources) || ref.isPlaying || playingSnapshot)return false
    val generation=sourceGeneration;val binding=ncPlaybackBinding
    ncContinuousSettling=true
    val posted=controller.postOutput {
      val settled=controller.settleInitialSource(slot,closure)
      val accepted=Handler(ref.applicationLooper).post {
        val current=!releasedSnapshot && !ncMuxedTrialRetired && ncContinuousIdleRetirement===closure
          && sourceGeneration==generation && ncPlaybackBinding===binding && closure.matches(ncMuxedSources)
          && !ref.isPlaying && !playingSnapshot
        val exact=settled!=null && !settled.isConsumed
          && (ncContinuousIdleSettlement==null || ncContinuousIdleSettlement===settled)
        if(current && exact)ncContinuousIdleSettlement=settled
        ncContinuousSettling=false;done(current && exact)
      }
      if(!accepted)done(false)
    }
    if(!posted)ncContinuousSettling=false
    return posted
  }
  /** Return the already positively settled output to ordinary planned idle.
   * This transfers no receipt, starts no source and never replaces the sink.
   * The exact used-run witness is consumed on its actual output thread.
   */
  internal fun ncReturnContinuousOutputToIdle(done:(Boolean)->Unit):Boolean {
    check(Looper.myLooper()==ref.applicationLooper)
    val settled=ncContinuousSettlement?:return false
    if(releasedSnapshot || ncMuxedTrialRetired || ncContinuousQueue!=null || ncContinuousPendingSource!=null
      || ncContinuousAttaching || ncContinuousSettling || settled.isConsumed || ncMuxedTrialOwner!=null
      || ncMuxedTrialReceipt!=null || ref.isPlaying || ref.playWhenReady || playingSnapshot)return false
    val generation=sourceGeneration;val binding=ncPlaybackBinding;val controller=ncContinuousOutputController
    ncContinuousSettling=true
    val posted=controller.postOutput {
      val returned=controller.returnToOrdinaryIdle(settled)
      val accepted=Handler(ref.applicationLooper).post {
        val current=!releasedSnapshot && !ncMuxedTrialRetired && ncContinuousSettlement===settled
          && sourceGeneration==generation && ncPlaybackBinding===binding && !ref.isPlaying && !ref.playWhenReady
        if(current && returned)ncContinuousSettlement=null
        ncContinuousSettling=false;done(current && returned)
      }
      if(!accepted) {controller.soleSink()?.let {controller.invalidate(it,"idle_return_post")};done(false)}
    }
    if(!posted)ncContinuousSettling=false
    return posted
  }

  /** Worker certification observes this unconsumed native witness before release. */
  internal fun ncContinuousSettledWitness(queue:NCContinuousMuxedQueue):NCContinuousMuxedSinkController.SinkSettlement? {
    check(Looper.myLooper()==ref.applicationLooper)
    val settled=ncContinuousSettlement?:return null
    if(releasedSnapshot || ncMuxedTrialRetired || settled.prior.queue!==queue || settled.isConsumed
      || ncContinuousQueue!=null || ncContinuousPendingSource!=null || ncContinuousAttaching || ncContinuousSettling
      || ncMuxedTrialOwner!=null || ncMuxedTrialReceipt!=null || ref.isPlaying || ref.playWhenReady || playingSnapshot)return null
    return settled
  }

  /** The caller has already joined the exact detached Queue off-main. Observe
   * asynchronous release on the real output thread, then rotate only its Guard
   * binding and source generation. False completion retains the old ownership
   * for retry; it is never permission to guess release or create another sink.
   */
  internal fun ncSettleContinuousQueue(queue:NCContinuousMuxedQueue,done:(Boolean)->Unit):Boolean {
    check(Looper.myLooper()==ref.applicationLooper)
    val slot=ncContinuousSlot?:return false
    if(releasedSnapshot || ncMuxedTrialRetired || ncContinuousQueue!==queue || ncContinuousAttaching
      || ncContinuousSettling || ref.isPlaying || playingSnapshot)return false
    val closure=queue.retirementWitness()?:return false
    val generation=sourceGeneration;val binding=ncPlaybackBinding
    val controller=ncContinuousOutputController
    ncContinuousSettling=true
    val posted=controller.postOutput {
      val settled=controller.settleQueue(slot,queue,closure)
      val accepted=Handler(ref.applicationLooper).post {
        val current=!releasedSnapshot && !ncMuxedTrialRetired && ncContinuousQueue===queue
          && sourceGeneration==generation && ncPlaybackBinding===binding && !ref.isPlaying && !playingSnapshot
        var rotated=false
        if(settled!=null && current) {
          rotated=ncMuxedSources.retire {
            ref.pause();sourceGeneration++
            ncContinuousPendingSource=null;ncContinuousQueue=null;ncContinuousSlot=null
            ncContinuousPendingQueue=null
            ncContinuousSettlement=settled
          }
        }
        ncContinuousSettling=false;done(rotated)
      }
      if(!accepted) {controller.invalidate(slot,"player_settle_post");done(false)}
    }
    if(!posted)ncContinuousSettling=false
    return posted
  }
  /** The caller owns the actual validated/ACKed Queue. Completion reports only
   * enrollment/preparation, not playing, source onset or any output receipt.
   * Native RPC completion must be thread-safe when an application post fails.
   */
  internal fun ncAttachContinuousQueue(queue:NCContinuousMuxedQueue,done:(Boolean)->Unit):Boolean {
    check(Looper.myLooper()==ref.applicationLooper)
    val installed=ncContinuousPendingSource?:return false
    if(releasedSnapshot || ncMuxedTrialRetired || ncContinuousAttaching || ncContinuousSettling || ncContinuousQueue!=null
      || sourceGeneration!=ncContinuousGeneration || ref.playWhenReady || !queue.matchesBinding(ncPlaybackBinding))return false
    val native=queue.nativeEnrollment()?:return false
    val controller=ncContinuousOutputController;val slot=controller.soleSink()?:return false
    val settled=ncContinuousSettlement
    val idleSettled=ncContinuousIdleSettlement
    ncContinuousEnrollmentAttempted=true
    ncContinuousAttaching=true
    val posted=controller.postOutput {
      val enrollment=when {
        idleSettled!=null->controller.enrollIdleSettled(idleSettled,native.first,native.second,ncContinuousPresentation)
        settled!=null->controller.enrollSettled(settled,native.first,native.second,ncContinuousPresentation)
        else->controller.enrollFresh(slot,native.first,native.second,ncContinuousPresentation)
      }
      val accepted=Handler(ref.applicationLooper).post {
        if(enrollment==null || releasedSnapshot || ncMuxedTrialRetired || ncContinuousPendingSource!==installed
          || sourceGeneration!=ncContinuousGeneration || ref.playWhenReady
          || !queue.matchesBinding(ncPlaybackBinding)
          || !controller.connectQueue(enrollment,queue,::ncPostContinuousProof)) {
          controller.invalidate(slot,"player_enrollment");queue.fence("player_enrollment")
          ncContinuousAttaching=false;done(false)
        } else {
          ncContinuousQueue=queue;ncContinuousSlot=slot;ncContinuousAttaching=false;ncContinuousSettlement=null
          ncContinuousIdleSettlement=null;ncContinuousIdleRetirement=null
          val prepared=try {ref.setMediaSource(installed);ref.prepare();startUpdating();true} catch(_:RuntimeException) {
            controller.invalidate(slot,"player_prepare");queue.fence("player_prepare");false
          }
          done(prepared)
        }
      }
      if(!accepted) {
        controller.invalidate(slot,"player_attach_post")
        ncPostContinuousProof {queue.fence("player_attach_post")}
        done(false)
      }
    }
    if(!posted)ncContinuousAttaching=false
    return posted
  }
  private fun ncObserveContinuousNativeEnd(playbackState:Int) {
    val queue=ncContinuousQueue?:return;val slot=ncContinuousSlot?:return
    if(playbackState!=Player.STATE_ENDED || ref.playbackState!=Player.STATE_ENDED || ref.isPlaying
      || sourceGeneration!=ncContinuousGeneration)return
    if(queue.snapshot().state!=NCContinuousMuxedQueueState.State.SEALED)return // Open-prefix exhaustion is not run drain.
    playingSnapshot=false // Copied genuine current-player output state, not a receipt.
    if(!ncContinuousOutputController.recordNativeEnd(slot))queue.fence("native_end")
  }
  internal var ncMuxedTrialReceipt: NCMuxedTrialReceipt? = null
    private set
  internal var ncMuxedTrialPosition: (() -> Double?)? = null
  internal var ncMuxedTrialOwner: NCMuxedTrialPlayer? = null
  internal val ncMuxedTrialStaging = NCMuxedTrialStaging<NCMuxedTrialPlayer.Prepared>()
  private val ncMuxedTrialReaderFences = mutableListOf<NCMuxedTrialReaderFence>()
  internal fun ncTrackMuxedReaderFence(fence:NCMuxedTrialReaderFence) {
    check(Looper.myLooper()==ref.applicationLooper)
    ncMuxedTrialReaderFences.removeAll {it.awaitClosed(0)}
    ncMuxedTrialReaderFences+=fence
  }
  internal fun ncRetiredMuxedReaderFences():List<NCMuxedTrialReaderFence> {
    check(Looper.myLooper()==ref.applicationLooper)
    return ncMuxedTrialReaderFences.toList()
  }
  internal var ncMuxedTrialRetired = false
    private set
  private var ncMuxedTrialAnalytics: AnalyticsListener? = null
  internal fun ncEnableMuxedTrialSession(debug: Boolean): Boolean {
    val enabled = !ncMuxedTrialRetired && (sourceGeneration == 0L || ncMuxedSources.enabled) && ncMuxedSources.enable(debug)
    if (enabled) ncRouteEffects.prepareCommunication()
    return enabled
  }
  internal val ncMuxedTrialRevision get() = ncMuxedSources.revision
  internal val ncMuxedTrialSessionEnabled get() = ncMuxedSources.enabled
  internal val ncMuxedVideoViewEligible get() = ncMuxedTrialSessionEnabled && ncIsAliveSnapshot && !ncMuxedTrialRetired
  internal fun ncRetireMuxedSource(): Boolean = ncMuxedSources.retire { ncClearMuxedSource() }
  private fun ncClearMuxedSource() {
    ncContinuousPresentation.fence("source_retired")
    sourceGeneration++
    ncMuxedTrialReaderFences.forEach {it.retire()}
    ncMuxedTrialOwner?.close()
    ncMuxedTrialReceipt?.close()
    ncMuxedTrialAnalytics?.let { ref.removeAnalyticsListener(it) }
    ncMuxedTrialAnalytics = null
    ncMuxedTrialOwner = null
    ncMuxedTrialReceipt = null
    ncMuxedTrialPosition = null
    ref.pause(); ref.stop(); ref.clearMediaItems()
    playingSnapshot = false
  }
  internal fun ncCloseMuxedTrial() {
    ncMuxedTrialRetired = true
    ncMuxedTrialStaging.clear()
    ncMuxedSources.close { ncClearMuxedSource() }
  }
  override val ncIsPlayingSnapshot: Boolean get() = playingSnapshot
  override val ncIsAliveSnapshot: Boolean get() = !releasedSnapshot
  override val ncPlayerIdentity: String get() = id
  override val ncItemIdentity: String get() = sourceGeneration.toString()
  override val ncPositionSeconds: Double? get() =
    if (!releasedSnapshot && Looper.myLooper() == ref.applicationLooper)
      if (ncMuxedTrialReceipt == null) ref.currentPosition / 1000.0 else ncMuxedTrialPosition?.invoke()
    else null
  override fun ncDispatch(effect: () -> Unit) {
    val looper = ref.applicationLooper
    if (Looper.myLooper() == looper) effect() else Handler(looper).post(effect)
  }
  private val ncRouteEffects by lazy { NCPlaybackRouteEffects(NCCommunicationRoute.shared, { route ->
    ncRouteMonitor.prepare(route, ncItemIdentity)
    ncRouteMonitor.verifyPlaying()
  }, { ref.play() }, { ref.pause() }, { communication ->
    ref.setAudioAttributes(if (!communication) AudioAttributes.DEFAULT else AudioAttributes.Builder()
      .setUsage(C.USAGE_VOICE_COMMUNICATION).setContentType(C.AUDIO_CONTENT_TYPE_SPEECH).build(), false)
  }, { effect -> Handler(ref.applicationLooper).post(effect) }, { ticket ->
    !releasedSnapshot && !ncMuxedTrialRetired && ncPlaybackBinding.ticket == ticket
      && NCPlaybackGuard.shared.currentTicket() == ticket
  }) }
  override fun ncPlay() {ncRouteEffects.play(ncPlaybackBinding.ticket);ncCachedIdle?.pause(false)}
  override fun ncPause() {ncCachedIdle?.pause(true);ncRouteEffects.pause()}
  override fun ncPauseForLock(permit:NCPlaybackGuard.LockPausePermit) {
    ncContinuousOutputController.pauseForLock(permit,{effect->
      ref.createMessage {_,_->effect()}.send()
    },{ncPause()})
  }
  internal fun ncPauseForContinuation(permit:NCPlaybackGuard.LockPausePermit,done:(Boolean)->Unit) {
    ncContinuousOutputController.pauseForLock(permit,{effect->
      ref.createMessage {_,_->effect()}.send()
    },{ncPause()},done)
  }

  fun ncBindPlaybackTicket(ticket: String): Boolean = ncPlaybackBinding.bind(ticket).also {
    if (it) ncDispatch { clearLockScreenControls() }
  }
  fun ncBindPhoneReplyChunk(ticket: String, requestId: String, chunkId: String): Boolean =
    ncPlaybackBinding.bindPhoneReplyChunk(ticket, requestId, chunkId)
  fun ncGuardedPlay(): Boolean = ncPlaybackBinding.play()
  fun ncSystemPlay(expectedItemIdentity: String? = ncItemIdentity): Boolean = ncPlaybackBinding.systemPlay(expectedItemIdentity)
  fun ncAllowsFocusEffect(observedTicket: String?, expectedItemIdentity: String?): Boolean =
    ncPlaybackBinding.allowsFocusEffect(observedTicket, expectedItemIdentity)
  fun ncGuardedPause() {
    focusInterrupted = false
    isPaused = false
    ncPlaybackBinding.pause()
  }
  fun ncGuardedReplace(source: MediaSource): Boolean = ncPlaybackBinding.replace { setMediaSource(source) }

  internal fun ncPrepareMuxedIdle(source: MediaSource, ticket: String): Boolean {
    if(ncMuxedTrialRetired || !ncMuxedSources.allowsPrepare(ncMuxedTrialRevision)
      || ncMuxedTrialOwner != null || ncMuxedTrialReceipt != null || ref.playWhenReady)return false
    setMediaSource(source)
    return ncPlaybackBinding.bind(ticket)
  }

  /** Development-only preparation on a fresh registered player. Reuses its
   * existing focus, route and guard binding; never creates a second audio owner.
   * The caller must first validate and retain the complete local media source.
   */
  internal fun ncPrepareMuxedTrial(source: MediaSource, ticket: String, requestId: String,
                                   chunkId: String, validSamples: Long): Boolean {
    if (releasedSnapshot || ncMuxedTrialRetired || (!ncMuxedSources.enabled && sourceGeneration != 0L) || ncPlaybackBinding.attempted
        || ref.playWhenReady || ncMuxedTrialReceipt != null) return false
    require(validSamples in 1..28800000)
    setMediaSource(source)
    val receipt = NCMuxedTrialReceipt(NCPlaybackGuard.shared, this, ticket, requestId,
                                     chunkId, validSamples, ncPlaybackBinding)
    ncMuxedTrialReceipt = receipt
    val listener = object : AnalyticsListener {
      override fun onAudioPositionAdvancing(eventTime: AnalyticsListener.EventTime,
                                            playoutStartSystemTimeMs: Long) {
        if(ncMuxedTrialOwner?.ownsEvent(eventTime)==true)receipt.positionAdvancing()
      }
    }
    ncMuxedTrialAnalytics = listener
    ref.addAnalyticsListener(listener)
    return receipt.bind().also { accepted -> if (!accepted) receipt.close() }
  }

  /** Rotate a genuinely completed speech owner, but leave its prepared
   * concatenation and decoder intact. This allocates no playback permission:
   * the successor is bound paused and must still use ordinary guarded play.
   */
  internal fun ncRotateMuxedSource(outgoing:NCMuxedTrialPlayer,ticket:String,request:String,
                                  chunk:String,validSamples:Long):Boolean {
    check(Looper.myLooper()==ref.applicationLooper)
    val ended=ncMuxedTrialReceipt?.observe()
    if(releasedSnapshot||ncMuxedTrialRetired||!ncMuxedSources.enabled
      ||ncMuxedTrialOwner!==outgoing||!outgoing.acceptsDrain
      ||ref.playbackState!=Player.STATE_ENDED||ref.isPlaying||playingSnapshot
      ||ended?.started!=true||ended.completed!=true||ended.playing
      ||NCPlaybackGuard.shared.currentTicket()!=ticket||ncPlaybackBinding.ticket!=ticket
      ||ncPlaybackBinding.requestId!=request||ncPlaybackBinding.chunkId==chunk
      ||validSamples !in 1..28800000)return false
    ref.pause()
    if(!ncMuxedSources.retire {
      sourceGeneration++ // Late effects from the old binding cannot pause its successor.
      outgoing.retireForContinuation()
      ncMuxedTrialReceipt?.close()
      ncMuxedTrialAnalytics?.let {ref.removeAnalyticsListener(it)}
      ncMuxedTrialAnalytics=null;ncMuxedTrialReceipt=null;ncMuxedTrialPosition=null
      playingSnapshot=false
    })return false
    val receipt=NCMuxedTrialReceipt(NCPlaybackGuard.shared,this,ticket,request,chunk,
      validSamples,ncPlaybackBinding)
    ncMuxedTrialReceipt=receipt
    val listener=object:AnalyticsListener {
      override fun onAudioPositionAdvancing(eventTime:AnalyticsListener.EventTime,
                                           playoutStartSystemTimeMs:Long) {
        if(ncMuxedTrialReceipt===receipt&&ncMuxedTrialOwner?.ownsEvent(eventTime)==true)
          receipt.positionAdvancing()
      }
    }
    ncMuxedTrialAnalytics=listener;ref.addAnalyticsListener(listener)
    return receipt.bind().also {accepted->if(!accepted)ncCloseMuxedTrial()}
  }

  // Lock screen controls
  var isActiveForLockScreen = false
  private var metadata: Metadata? = null

  private var playerScope = CoroutineScope(Dispatchers.Default)
  private var samplingEnabled = false
  private var visualizer: Visualizer? = null
  private var playing = false
  private val context by lazy {
    appContext.reactContext
      ?: throw Exceptions.ReactContextLost()
  }

  private var updateJob: Job? = null

  val currentTime get() = if (ncMuxedTrialOwner == null) ref.currentPosition / 1000f
    else (ncPositionSeconds ?: 0.0).toFloat()
  val duration get() = ncMuxedTrialOwner?.durationSeconds?.toFloat()
    ?: if (ref.duration != C.TIME_UNSET) ref.duration / 1000f else 0f

  private val ncDiagnosticObserver=NCDiagnosticPlayerObserver(id)
  internal fun ncObservePreparation(mediaId:String?,stage:String) {
    ncDiagnosticObserver.chunkPreparation(mediaId,stage,android.os.SystemClock.elapsedRealtime(),null,null,null)
  }
  init {
    check(ncContinuousOutputController.attachPlaybackHandler(Handler(ref.playbackLooper)))
    ncContinuousOutputController.soleSink()?.let {check(ncContinuousOutputController.bindSourceOwner(it,ncMuxedSources))}
    addPlayerListeners()
    // Aggregate callbacks only: no frame polling and no changes to renderer scheduling.
    ref.addAnalyticsListener(object:AnalyticsListener {
      private fun callbackMediaId(time:AnalyticsListener.EventTime):String? {
        // Use the event's period, which may be a future buffered chunk. The
        // currently playing window is not evidence of which file was loaded.
        return try {
          time.mediaPeriodId?.let {periodId->
            val index=time.timeline.getIndexOfPeriod(periodId.periodUid)
            if(index<0)null else {
              val period=time.timeline.getPeriod(index,Timeline.Period())
              time.timeline.getWindow(period.windowIndex,Timeline.Window()).mediaItem.mediaId
            }
          }
        }catch(_:Exception){null}
      }
      private fun load(stage:String,time:AnalyticsListener.EventTime,info:LoadEventInfo) {
        if(!ncDiagnosticPolicy.siteEnabled("native.player.preparation"))return
        val mediaId=callbackMediaId(time)
        ncDiagnosticObserver.chunkPreparation(mediaId,stage,info.elapsedRealtimeMs,
          info.loadTaskId,info.loadDurationMs,info.bytesLoaded)
      }
      override fun onLoadStarted(eventTime:AnalyticsListener.EventTime,loadEventInfo:LoadEventInfo,mediaLoadData:MediaLoadData) {
        load("load_started",eventTime,loadEventInfo)
      }
      override fun onLoadCompleted(eventTime:AnalyticsListener.EventTime,loadEventInfo:LoadEventInfo,mediaLoadData:MediaLoadData) {
        load("load_completed",eventTime,loadEventInfo)
      }
      override fun onLoadCanceled(eventTime:AnalyticsListener.EventTime,loadEventInfo:LoadEventInfo,mediaLoadData:MediaLoadData) {
        load("load_cancelled",eventTime,loadEventInfo)
      }
      override fun onLoadError(eventTime:AnalyticsListener.EventTime,loadEventInfo:LoadEventInfo,mediaLoadData:MediaLoadData,
        error:java.io.IOException,wasCanceled:Boolean) {
        load("load_error",eventTime,loadEventInfo)
      }
      private fun audio(kind:String,time:AnalyticsListener.EventTime,values:Map<String,Long>) {
        if(kind!="underrun" &&!ncDiagnosticPolicy.siteEnabled("native.player.audio_output"))return
        ncDiagnosticObserver.postAudioOutput(kind,time.realtimeMs,time.currentPlaybackPositionMs,time.totalBufferedDurationMs,values,
          callbackMediaId(time))
      }
      override fun onAudioTrackInitialized(eventTime:AnalyticsListener.EventTime,audioTrackConfig:AudioSink.AudioTrackConfig) {
        audio("track_initialized",eventTime,mapOf("sample_rate_hz" to audioTrackConfig.sampleRate.toLong(),"buffer_size_bytes" to audioTrackConfig.bufferSize.toLong()))
      }
      override fun onAudioTrackReleased(eventTime:AnalyticsListener.EventTime,audioTrackConfig:AudioSink.AudioTrackConfig) {
        audio("track_released",eventTime,emptyMap())
      }
      override fun onAudioPositionAdvancing(eventTime:AnalyticsListener.EventTime,playoutStartSystemTimeMs:Long) {
        audio("position_advancing",eventTime,mapOf("start_system_time_ms" to playoutStartSystemTimeMs))
      }
      override fun onAudioUnderrun(eventTime:AnalyticsListener.EventTime,bufferSize:Int,bufferSizeMs:Long,elapsedSinceLastFeedMs:Long) {
        audio("underrun",eventTime,mapOf("buffer_size_bytes" to bufferSize.toLong(),"buffer_size_ms" to bufferSizeMs,"elapsed_since_feed_ms" to elapsedSinceLastFeedMs))
      }
      override fun onDroppedVideoFrames(eventTime:AnalyticsListener.EventTime,droppedFrames:Int,elapsedMs:Long) {
        ncDiagnosticObserver.videoCadence("dropped_frames",droppedFrames.toLong(),elapsedMs)
      }
      override fun onVideoFrameProcessingOffset(eventTime:AnalyticsListener.EventTime,
        totalProcessingOffsetUs:Long,frameCount:Int) {
        ncDiagnosticObserver.videoCadence("processing_offset_us",totalProcessingOffsetUs,frameCount.toLong())
      }
    })
    source?.let {
      setMediaSource(source)
    }
  }

  fun setVolume(volume: Float?) = appContext?.mainQueue?.launch {
    val boundedVolume = volume?.coerceIn(0f, 1f) ?: 1f
    if (isMuted) {
      if (boundedVolume > 0f) {
        previousVolume = boundedVolume
      }
      ref.volume = 0f
    } else {
      previousVolume = boundedVolume
      ref.volume = boundedVolume
    }
  }

  fun setMediaSource(source: MediaSource) {
    ncFenceContinuousControl("public_source")
    sourceGeneration += 1
    nativePlayerErrorCode = null
    ref.setMediaSource(source)
    ref.prepare()
    startUpdating()
  }

  fun setActiveForLockScreen(active: Boolean, metadata: Metadata? = null, options: AudioLockScreenOptions? = null) {
    if (active && (ncContinuousFixtureEnabled || ncContinuousPendingSource!=null
      || ncContinuousPendingQueue!=null || ncContinuousQueue!=null)) return
    if (active && !ncPlaybackBinding.canUseMediaControls()) return
    if (active) {
      ncMediaSessionExposed=true
      this.metadata = metadata
      AudioControlsService.setActivePlayer(context, this, metadata, options)
    } else if (isActiveForLockScreen) {
      AudioControlsService.setActivePlayer(context, null)
    }
  }

  fun updateLockScreenMetadata(metadata: Metadata) {
    if (isActiveForLockScreen) {
      this.metadata = metadata
      AudioControlsService.updateMetadata(this, metadata)
    }
  }

  fun clearLockScreenControls() {
    if (isActiveForLockScreen) {
      AudioControlsService.setActivePlayer(context, null)
    }
  }

  private fun startUpdating() {
    updateJob?.cancel()
    updateJob = flow {
      while (true) {
        emit(Unit)
        delay(updateInterval.toLong())
      }
    }
      .onStart {
        sendPlayerUpdate()
      }
      .onEach {
        if (playing) {
          sendPlayerUpdate()
        }
      }
      .launchIn(playerScope)
  }

  private fun addPlayerListeners() = ref.addListener(object : Player.Listener {
    override fun onPlayerError(error: PlaybackException) {
      nativePlayerErrorCode = error.errorCode
      ncDiagnosticObserver.playerFailure(error.errorCode,sourceGeneration,error)
      playerScope.launch { sendPlayerUpdate() }
    }

    override fun onEvents(player: Player, events: Player.Events) {
      if(events.containsAny(Player.EVENT_PLAYBACK_STATE_CHANGED,Player.EVENT_IS_PLAYING_CHANGED,
          Player.EVENT_MEDIA_ITEM_TRANSITION,Player.EVENT_PLAY_WHEN_READY_CHANGED,
          Player.EVENT_PLAYBACK_SUPPRESSION_REASON_CHANGED))ncDiagnosticObserver.withBoundary(
            events.contains(Player.EVENT_PLAYBACK_STATE_CHANGED)&&player.playWhenReady&&player.playbackState==Player.STATE_BUFFERING) {
        ncDiagnosticObserver.playbackBoundary(player.currentMediaItem?.mediaId,
          player.currentPosition,player.totalBufferedDuration,player.mediaItemCount,
          player.playbackState,player.isPlaying,player.playWhenReady,player.playbackSuppressionReason)
      }
      if(!events.containsAny(Player.EVENT_PLAYBACK_STATE_CHANGED,Player.EVENT_IS_PLAYING_CHANGED,
          Player.EVENT_MEDIA_ITEM_TRANSITION,Player.EVENT_TIMELINE_CHANGED,
          Player.EVENT_PLAY_WHEN_READY_CHANGED,Player.EVENT_PLAYBACK_SUPPRESSION_REASON_CHANGED,
          Player.EVENT_PLAYER_ERROR))return
      // Media3 calls onEvents on its application thread after individual callbacks.
      // Read one coherent observation here; never query guards, receipts or a second player.
      ncDiagnosticObserver.withSnapshot(events.contains(Player.EVENT_PLAYER_ERROR)) { try {
        val mediaId=player.currentMediaItem?.mediaId
        val count=player.mediaItemCount
        val lastId=if(count>0)player.getMediaItemAt(count-1).mediaId else null
        val owner=ncMuxedTrialOwner
        ncDiagnosticObserver.playbackSnapshot(mediaId,sourceGeneration,player.currentMediaItemIndex,count,
          owner?.diagnosticChunkIndex(mediaId),owner?.diagnosticChunkIndex(lastId),
          player.currentPosition,player.totalBufferedDuration,player.playbackState,player.isPlaying,
          player.playWhenReady,player.playbackSuppressionReason,player.playerError?.errorCode)
      }catch(_:Exception){ncDiagnosticObserver.decision("snapshot_read",false)} }
    }

    override fun onIsPlayingChanged(isPlaying: Boolean) {
      ncDiagnosticObserver.playing(isPlaying)
      playingSnapshot = isPlaying
      ncCachedIdle?.playbackStateChanged()
      if (isPlaying) {
        ncRouteMonitor.verifyPlaying()
        val trial = ncMuxedTrialReceipt
        if(ncContinuousQueue==null) {
          if (trial == null) ncPlaybackBinding.acknowledgeStarted() else trial.playingChanged()
        }
      }
      playing = isPlaying
      playerScope.launch {
        sendPlayerUpdate(mapOf("playing" to isPlaying))
      }
      onPlaybackStateChange?.invoke(isPlaying)
    }

    override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
      ncDiagnosticObserver.playWhenReady(playWhenReady,reason)
    }

    override fun onIsLoadingChanged(isLoading: Boolean) {
      playerScope.launch {
        sendPlayerUpdate(mapOf("isLoaded" to !isLoading))
      }
    }

    override fun onPlaybackStateChanged(playbackState: Int) {
      ncDiagnosticObserver.state(playbackState)
      if (playbackState == Player.STATE_ENDED) {
        if(ncContinuousQueue!=null)ncObserveContinuousNativeEnd(playbackState)
        else {
        val trial = ncMuxedTrialReceipt
        if (trial == null) ncPlaybackBinding.acknowledgeCompleted()
        else if(ref.playbackState==Player.STATE_ENDED && ncMuxedTrialOwner?.acceptsDrain==true) {
          playingSnapshot = false
          trial.ended()
        }
        }
      }
      playerScope.launch {
        sendPlayerUpdate(mapOf("playbackState" to playbackStateToString(playbackState)))
      }
    }

    override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
      ncDiagnosticObserver.mediaTransition(mediaItem?.mediaId,reason)
      playerScope.launch {
        sendPlayerUpdate()
      }
    }

    override fun onTimelineChanged(timeline: androidx.media3.common.Timeline, reason: Int) {
      // The source's append callback can precede the player's timeline event.
      // Only the unsealed silent owner can recover a temporary ended tail.
      ncMuxedTrialOwner?.resumeIdle()
      ncMuxedTrialOwner?.resumeStream()
    }
  })

  fun setSamplingEnabled(enabled: Boolean) {
    appContext?.reactContext?.let {
      if (ContextCompat.checkSelfPermission(it, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
        Log.d(TAG, "\'android.permission.RECORD_AUDIO\' is required to use audio sampling. Please request this permission and try again.")
        return
      }
    }

    samplingEnabled = enabled
    if (enabled) {
      createVisualizer()
    } else {
      visualizer?.release()
      visualizer = null
    }
  }

  fun seekTo(seekTime: Double) {
    ncFenceContinuousControl("public_seek")
    ncContinuousPresentation.fence("public_seek")
    ref.seekTo((seekTime * 1000L).toLong())
    playerScope.launch {
      sendPlayerUpdate()
    }
  }

  private fun extractAmplitudes(chunk: ByteArray): List<Float> = chunk.map { byte ->
    val unsignedByte = byte.toInt() and 0xFF
    ((unsignedByte - 128).toDouble() / 128.0).toFloat()
  }

  fun currentStatus(): Map<String, Any?> {
    val isMuted = ref.volume == 0f
    val isLooping = ref.repeatMode == Player.REPEAT_MODE_ONE
    val isLoaded = ref.playbackState == Player.STATE_READY
    val isBuffering = ref.playbackState == Player.STATE_BUFFERING
    val receipt = ncMuxedTrialReceipt
    val output = receipt?.observe()
    val outputPlaying = ref.isPlaying && (receipt == null || output?.started == true)
    val streamWaiting=ncMuxedTrialOwner?.waitingForStream==true
    val outputEnded = !streamWaiting && ref.playbackState == Player.STATE_ENDED && (receipt == null || output?.completed == true)

    return mapOf(
      "id" to id,
      "currentTime" to currentTime,
      "playbackState" to if(streamWaiting) "buffering" else playbackStateToString(ref.playbackState),
      "timeControlStatus" to if (outputPlaying) "playing" else "paused",
      "reasonForWaitingToPlay" to null,
      "mute" to isMuted,
      "duration" to duration,
      "playing" to outputPlaying,
      "playWhenReady" to ref.playWhenReady,
      "nativePlayerErrorCode" to nativePlayerErrorCode,
      "focusInterrupted" to focusInterrupted,
      "loop" to isLooping,
      "didJustFinish" to outputEnded,
      "isLoaded" to if (streamWaiting) false else if (ref.playbackState == Player.STATE_ENDED) true else isLoaded,
      "playbackRate" to ref.playbackParameters.speed,
      "shouldCorrectPitch" to preservesPitch,
      "isBuffering" to (streamWaiting || isBuffering)
    ) + if (receipt != null && ref.playbackState == Player.STATE_ENDED && !outputEnded && !streamWaiting)
      mapOf("error" to "Muxed native output was not confirmed.") else emptyMap()
  }

  private suspend fun sendPlayerUpdate(map: Map<String, Any?>? = null) =
    withContext(Dispatchers.Main) {
      ncRouteMonitor.verifyPlaying()
      val data = currentStatus()
      // A queued ENDED event can outlive a stream append and guarded resume.
      val statusMap=if(ncMuxedTrialOwner?.streamPlan!=null)map?.filterKeys {it!="playbackState"} else map
      val body = if (ncMuxedTrialReceipt == null) map?.let { data + it } ?: data
        else data + (statusMap?.filterKeys { it !in setOf("playing", "didJustFinish", "error") } ?: emptyMap())
      emit(PLAYBACK_STATUS_UPDATE, body)
    }

  private fun sendAudioSampleUpdate(sample: List<Float>) {
    val body = mapOf(
      "channels" to listOf(
        mapOf("frames" to sample)
      ),
      "timestamp" to ref.currentPosition
    )
    emit(AUDIO_SAMPLE_UPDATE, body)
  }

  private fun playbackStateToString(state: Int): String {
    return when (state) {
      Player.STATE_READY -> "ready"
      Player.STATE_BUFFERING -> "buffering"
      Player.STATE_IDLE -> "idle"
      Player.STATE_ENDED -> "ended"
      else -> "unknown"
    }
  }

  private fun createVisualizer() {
    // It must only be created once, otherwise the app will crash
    if (visualizer == null) {
      visualizer = Visualizer(ref.audioSessionId).apply {
        captureSize = Visualizer.getCaptureSizeRange()[1]
        setDataCaptureListener(
          object : Visualizer.OnDataCaptureListener {
            override fun onWaveFormDataCapture(visualizer: Visualizer?, waveform: ByteArray?, samplingRate: Int) {
              waveform?.let {
                if (samplingEnabled && ref.isPlaying) {
                  val data = extractAmplitudes(it)
                  sendAudioSampleUpdate(data)
                }
              }
            }

            override fun onFftDataCapture(visualizer: Visualizer?, fft: ByteArray?, samplingRate: Int) = Unit
          },
          Visualizer.getMaxCaptureRate() / 2,
          true,
          false
        )
        enabled = true
      }
    }
  }

  override fun sharedObjectDidRelease() {
    super.sharedObjectDidRelease()
    releasedSnapshot = true
    ncMuxedTrialReceipt?.close()
    ncRouteMonitor.prepare(null, null)
    ncPlaybackBinding.remove()
    ncCloseContinuousProofWorker()
    appContext?.mainQueue?.launch {
      ncRouteEffects.close()
      ncCloseMuxedTrial()
      if (isActiveForLockScreen) {
        AudioControlsService.clearSession()
      }
      playerScope.cancel()
      visualizer?.release()
      ref.release()
    }
  }

  companion object {
    val TAG = AudioPlayer::class.simpleName
  }
}
