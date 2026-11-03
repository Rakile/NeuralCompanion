package expo.modules.audio

/** Shared by native file admission; no rounding away a short final voice tail. */
internal object NCMuxedTrialSamples {
  /** Normalize a bounded consecutive idle window for the same exact native
   * file validator. Caller still validates the actual tracks, trim and PTS.
   */
  fun idleRows(values:List<Map<String,Any>>,first:Int):List<Map<String,Any>> {
    require(values.size in 1..6 && first in 0..10005 && first+values.size-1<=10005)
    fun number(row:Map<String,Any>,key:String,expected:Int) {
      require((row[key] as? Number)?.toDouble()==expected.toDouble())
    }
    return values.mapIndexed { offset,row ->
      number(row,"index",first+offset);number(row,"startFrame",(first+offset)*12)
      number(row,"frameCount",12);number(row,"validSamples",24000)
      number(row,"sampleRate",48000);number(row,"fps",24)
      row+mapOf("index" to offset,"startFrame" to offset*12)
    }
  }
  fun matches(valid:Int,delay:Int,padding:Int,raw:Int,observedDelay:Int,durationUs:Long,
    observedPadding:Int?=null):Boolean =
    valid in 1..25999 && delay in 0..2048 && padding in 0..1023 &&
      raw in 1024..28672 && raw%1024==0 && raw-delay-padding==valid &&
      observedDelay==delay && durationUs in 1L..600000L &&
      // Extractors may report either encoded duration or edited content duration.
      // Accept the latter only with independent native evidence of both trims.
      (kotlin.math.abs(durationUs-raw*1000000L/48000L)<=1L ||
        (observedPadding==padding && kotlin.math.abs(durationUs-valid*1000000L/48000L)<=1L))
}

/** Development-only muxed output receipt adapter; native sink events only. */
internal class NCMuxedTrialReceipt(
  guard:NCPlaybackGuard, private val actions:NCPlaybackActions,
  private val ticket:String, private val requestId:String,
  private val chunkId:String, private val validSamples:Long,
  private val binding:NCPlaybackBinding=guard.newBinding(actions)
) {
  private var presented=0L
  private var closed=false
  private var advancing=false
  init { require(validSamples in 1..28800000) }
  fun bind()=binding.bindPhoneReplyChunk(ticket,requestId,chunkId)
  fun play()=binding.play()
  fun observe()=binding.observePhoneReply(ticket,requestId,chunkId)
  // Called only by Media3's native audio-position-advancing callback, not READY.
  fun positionAdvancing(){advancing=true;playingChanged()}
  fun playingChanged(){if(advancing&&actions.ncIsPlayingSnapshot)output(maxOf(1,presented),false)}
  // STATE_ENDED means Media3's audio renderer and sink have drained; a media
  // item transition is explicitly not this event.
  fun ended()=output(validSamples,true)
  fun output(samplesPresented:Long,finalDrained:Boolean):Boolean {
    if(closed||samplesPresented !in presented..validSamples)return false
    val state=observe()?:return false
    if(finalDrained&&(samplesPresented!=validSamples||!state.started||actions.ncIsPlayingSnapshot))return false
    if(samplesPresented>0&&!state.started&&!binding.acknowledgeStarted())return false
    presented=samplesPresented
    return !finalDrained||binding.acknowledgeCompleted()
  }
  fun close(){if(!closed){closed=true;binding.pause();binding.remove()}}
}
