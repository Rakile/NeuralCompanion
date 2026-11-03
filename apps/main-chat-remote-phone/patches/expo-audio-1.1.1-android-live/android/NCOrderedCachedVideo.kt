package expo.modules.audio

import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Handler
import android.widget.FrameLayout
import java.io.File
import java.net.URI
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

/** Adapter for the existing silent complete-loop renderer, not another audio
 * player. Exact registered Queue identity survives Live and view changes. */
internal class NCOrderedCachedVideo(private val player:AudioPlayer,private val queue:NCContinuousMuxedQueue,
  private val host:FrameLayout,private val postProof:((()->Unit)->Boolean)) {
  companion object {
    fun candidate(value:Any?):NCOrderedCachedIdle.Candidate {
      val r=NCContinuousMuxedRequests.row(value)
      require(r.keys==setOf("streamId","generation","loopId","motionId","inventoryRevision","cacheEpoch",
        "sourceFrameCount","entryFrame","afterOrdinal","afterFrameCount","fadeMs")) {"ordered_cached_candidate_fields"}
      fun text(key:String)=NCContinuousMuxedRequests.text(r[key])
      fun number(key:String)=NCContinuousMuxedRequests.integer(r[key],0)
      fun small(key:String,max:Long)=NCContinuousMuxedRequests.integer(r[key],0,max).toInt()
      return NCOrderedCachedIdle.Candidate(text("streamId"),number("generation"),text("loopId"),text("motionId"),
        text("inventoryRevision"),number("cacheEpoch"),small("sourceFrameCount",1440),small("entryFrame",1439),
        number("afterOrdinal"),small("afterFrameCount",12),small("fadeMs",5000))
    }
    /** Worker-only IO/media validation; the UI thread does no hashing/extraction. */
    fun validate(root:File,c:NCOrderedCachedIdle.Candidate,value:Any?):File {
      val r=NCContinuousMuxedRequests.row(value)
      require(r.keys==setOf("uri","sha256","bytes")) {"ordered_cached_file_fields"}
      val uri=URI(NCContinuousMuxedRequests.text(r["uri"],2048))
      require(uri.scheme=="file" &&uri.query==null &&uri.fragment==null) {"ordered_cached_file_uri"}
      val file=File(uri);val size=NCContinuousMuxedRequests.integer(r["bytes"],1,16L*1024*1024)
      val sha=NCContinuousMuxedRequests.text(r["sha256"])
      require(sha.matches(Regex("[a-f0-9]{64}")) &&file.canonicalFile==file.absoluteFile
        &&file==File(root.canonicalFile,"nc-idle-v1/${c.loopId}.mp4") &&file.isFile &&file.length()==size) {"ordered_cached_file_identity"}
      val modified=file.lastModified()
      val digest=MessageDigest.getInstance("SHA-256")
      file.inputStream().use{input->val bytes=ByteArray(65536);var count=input.read(bytes)
        while(count>=0){if(count>0)digest.update(bytes,0,count);count=input.read(bytes)}}
      require(digest.digest().joinToString(""){"%02x".format(it)}==sha) {"ordered_cached_file_digest"}
      val extractor=MediaExtractor()
      try {
        extractor.setDataSource(file.absolutePath)
        require(extractor.trackCount==1) {"ordered_cached_track_count"}
        val format=extractor.getTrackFormat(0)
        val duration=format.getLong(MediaFormat.KEY_DURATION)
        val expectedDuration=c.sourceFrameCount*1000000L/24
        // Android can expose the MP4 movie duration rounded up to milliseconds.
        // Admit that exact representation only with independent sample evidence below.
        val movieDuration=(c.sourceFrameCount*1000L+23)/24*1000
        require(format.getString(MediaFormat.KEY_MIME)=="video/avc"
          &&format.getInteger(MediaFormat.KEY_FRAME_RATE)==24
          &&format.getInteger(MediaFormat.KEY_WIDTH) in 2..448 &&format.getInteger(MediaFormat.KEY_HEIGHT) in 2..672
          &&(duration in expectedDuration-1..expectedDuration+1 ||duration==movieDuration)) {"ordered_cached_media_mapping"}
        extractor.selectTrack(0)
        var ordinal=0
        while(extractor.sampleTime>=0) {
          require(ordinal<c.sourceFrameCount
            &&kotlin.math.abs(extractor.sampleTime-ordinal*1000000L/24)<=2) {"ordered_cached_sample_mapping"}
          ordinal++;extractor.advance()
        }
        require(ordinal==c.sourceFrameCount) {"ordered_cached_sample_count"}
      }finally{extractor.release()}
      require(file.length()==size &&file.lastModified()==modified) {"ordered_cached_file_changed"}
      return file
    }
  }
  private val main=Handler(player.ref.applicationLooper)
  private var file:File?=null
  private var prepared:NCOrderedCachedIdle.Candidate?=null
  private var closed=false;private var paused=false;private var selected=false;private var effect=0L
  private var surfaceAvailable=player.ncCachedSurfaceAvailable
  private var tail=false
  private var failure:String?=null
  private var armedAtNs=0L;private var armedCandidate:NCOrderedCachedIdle.Candidate?=null
  private var reportedRevision=0L;private var selectionRequested=false
  private val proofBusy=AtomicBoolean(false)
  private val observer:()->Unit={signal()}
  private val video:NCIdleVideo=NCIdleVideo(host){_,frame,nanos->state.presented(frame,nanos)}
  private val state:NCOrderedCachedIdle=NCOrderedCachedIdle(object:NCOrderedCachedIdle.Port {
    override fun current()=!closed &&player.ncMuxedVideoViewEligible &&player.ncContinuousQueue===queue
    override fun prepare(candidate:NCOrderedCachedIdle.Candidate,done:(Boolean)->Unit) {
      if(!surfaceAvailable){done(false);return}
      video.prepareAt(candidate.streamId,candidate.loopId,requireNotNull(file),0,candidate.sourceFrameCount,candidate.entryFrame,done)
    }
    override fun tailSettled(candidate:NCOrderedCachedIdle.Candidate)=tail
    override fun select(candidate:NCOrderedCachedIdle.Candidate):Boolean {
      selectionRequested=true
      if(!surfaceAvailable ||paused)return false
      effect++;host.animate().cancel();host.alpha=1f;host.bringToFront()
      video.display(!paused,false)
      val accepted=video.selectContinuation(candidate.entryFrame)
      selected=accepted;return accepted
    }
    override fun hide(fadeMs:Int) {
      selected=false;val ticket=++effect
      host.animate().cancel();host.animate().alpha(0f).setDuration(fadeMs.toLong()).withEndAction {
        if(effect==ticket)video.display(false,false)
      }.start()
    }
    override fun clear(done:(Boolean)->Unit) {
      effect++;selected=false;host.animate().cancel()
      video.clearDetached {safe->if(safe){host.alpha=0f};done(safe)}
    }
  })
  init {
    queue.onCachedPresentation=observer;queue.observeCachedFrames(observer)
    video.cadenceEvidenceObserver={details->NCDiagnosticPlayerObserver(player.id).postCachedCadence(details)}
    video.failureEvidenceObserver={reason,details->
      if(failure==null)NCDiagnosticPlayerObserver(player.id).cachedRendererFailure(reason,details)
    }
    video.failureObserver={reason->
      if(failure==null){
        val safe=when {reason.startsWith("decode_")->"decode";reason=="presentation_timeout"->reason;else->"renderer"}
        failure=safe
      }
    }
  }
  fun owns(value:NCContinuousMuxedQueue)=queue===value
  fun prepare(candidate:NCOrderedCachedIdle.Candidate,path:File,done:(Boolean)->Unit) {
    check(!closed);file=path;prepared=candidate;tail=false;armedAtNs=0L;armedCandidate=null
    if(!selected){host.animate().cancel();host.alpha=0.001f}
    state.prepare(candidate,done)
  }
  fun arm(candidate:NCOrderedCachedIdle.Candidate,revision:Long):Boolean {
    val accepted=state.arm(candidate,revision)
    if(accepted){prepared=candidate;tail=false;armedCandidate=candidate;armedAtNs=System.nanoTime();selectionRequested=false;signal()};return accepted
  }
  private fun signal() {
    if(closed ||!proofBusy.compareAndSet(false,true))return
    val captured=prepared
    val posted=postProof {
      val frame=queue.cachedPresentedFrame()
      val settled=captured!=null &&queue.cachedTailSettled(captured)
      main.post {
        proofBusy.set(false)
        if(!closed &&player.ncContinuousQueue===queue){
          if(frame?.get("known")==true)state.streamPresented((frame["ordinal"] as Number).toLong(),player.ref.isPlaying)
          if(captured==prepared){tail=settled;state.tick()}
        }
      }
    }
    if(!posted)proofBusy.set(false)
  }
  fun status(revision:Long):Map<String,Any?> {
    signal();val now=System.nanoTime()
    val activation=state.activation(revision)
    if(activation!=null)reportedRevision=revision // An already displayed grant is not a later activation stall.
    val position=state.position(now)?.takeIf{it["activationRevision"]==revision}
    val captured=armedCandidate
    if(activation==null &&failure==null &&captured!=null &&armedAtNs>0 &&now-armedAtNs>=5_000_000_000L
      &&reportedRevision!=revision){
      val context=mapOf("activation_revision" to revision,"waiting_ms" to (now-armedAtNs)/1_000_000L,
        "selection_requested" to selectionRequested,"selected" to selected,"paused" to paused,"closed" to closed,
        "surface_available" to surfaceAvailable,"view_eligible" to player.ncMuxedVideoViewEligible,
        "queue_current" to (player.ncContinuousQueue===queue))
      try{
        if(postProof {try{NCDiagnosticPlayerObserver(player.id).postCachedBoundaryWaiting(queue.cachedBoundaryEvidence(captured)+
            context+mapOf("proof_queue_delay_ms" to (System.nanoTime()-now)/1_000_000L))}catch(_:Exception){}})
          reportedRevision=revision
      }catch(_:Exception){} // Diagnostics cannot reject an otherwise valid native status read.
    }
    return mapOf("version" to 1,"activation" to activation,"position" to position,"failure" to failure)
  }
  fun layout(){video.layout()}
  // A preroll frame need not produce another callback when Media3 becomes
  // ready. Recheck that same Queue's witness on the actual running transition.
  fun playbackStateChanged(){signal()}
  fun pause(value:Boolean){paused=value;video.display(selected &&!paused,false)}
  // Complete selected local media stays available during a lock/user pause.
  // This is not evidence of movement or permission to remove either pause.
  internal fun continuationAvailable()=!closed &&selected
  fun surface(value:Boolean){surfaceAvailable=value;video.suspendSurface(!value);if(value)signal()}
  fun close(done:(Boolean)->Unit) {
    closed=true
    if(queue.onCachedPresentation===observer){queue.onCachedPresentation=null;queue.observeCachedFrames(null)}
    state.close(done)
  }
}
