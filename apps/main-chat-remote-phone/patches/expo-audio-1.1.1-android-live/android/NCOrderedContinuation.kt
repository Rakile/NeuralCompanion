package expo.modules.audio

/** Native checkpoint identity, not a playback grant. The registered output
 * adapter owns serialization, pause effects, queue custody and lock composition.
 * No input/capture API or client-supplied position participates here. */
internal class NCOrderedContinuation(private val scope:Scope,private val port:Port) {
  data class Scope(val ticket:String,val streamId:String,val generation:Long,val runId:String,val revision:Long) {
    init {require(ticket.isNotBlank() &&ticket.length<=128 &&streamId.matches(Regex("[a-f0-9]{32}"))
      &&generation in 0..MAX &&runId.isNotBlank() &&runId.length<=128 &&revision in 1..MAX)}
  }
  data class Request(val scope:Scope,val epoch:Long,val checkpointId:String?=null) {
    init {require(epoch in 1..MAX &&(checkpointId==null ||checkpointId.matches(Regex("[a-f0-9]{32}"))))}
  }
  data class Position(val ordinal:Long,val frameOffset:Int,val consumedSamples:Long) {
    init {require(ordinal in 0..MAX &&frameOffset in 0..11 &&consumedSamples in 0..MAX)}
    fun wire()=mapOf("ordinal" to ordinal,"frameOffset" to frameOffset,"consumedSamples" to consumedSamples)
  }
  data class Snapshot(val scope:Scope,val checkpointId:String,val epoch:Long,val state:String,
    val position:Position?,val publishedCursor:Long,val acknowledgedCursor:Long) {
    fun wire():Map<String,Any?> = mapOf("version" to 1,"checkpointId" to checkpointId,
      "streamId" to scope.streamId,"generation" to scope.generation,
      "run" to mapOf("id" to scope.runId,"revision" to scope.revision),"recoveryEpoch" to epoch,
      "state" to state,"position" to position?.wire(),"publishedCursor" to publishedCursor,
      "acknowledgedCursor" to acknowledgedCursor)
  }
  interface Port {
    fun current():Boolean
    fun buffered():Boolean
    fun cursors():Pair<Long,Long>
    fun pause(epoch:Long):Position?
    // Remove only the connection pause; a lock must retain its own pause.
    fun release(epoch:Long):Boolean
    fun cancel(epoch:Long)
    fun failed(epoch:Long,error:RuntimeException) {}
    fun watch(advance:()->Unit):()->Unit = {}
  }
  private var epoch=0L
  private var checkpoint:String?=null
  private var state="cancelled"
  private var position:Position?=null
  private var failure:String?=null
  private var stopWatching:(()->Unit)?=null
  @Synchronized fun suspend(request:Request):Snapshot {
    require(request.scope==scope &&request.checkpointId==null &&port.current()) {"ordered_continuation_owner"}
    check(epoch==0L ||state!="cancelled") {failure?:"ordered_continuation_cancelled"}
    require(request.epoch>=epoch) {"ordered_continuation_stale"}
    if(request.epoch==epoch) {
      check(state!="cancelled") {failure?:"ordered_continuation_cancelled"}
      return snapshot()
    }
    val held=state=="paused"
    epoch=request.epoch;checkpoint=java.util.UUID.randomUUID().toString().replace("-","")
    state="buffered";position=null
    if(held)sealPause() else settleStarvation()
    if(stopWatching==null)stopWatching=port.watch{advance()}
    return snapshot()
  }
  @Synchronized fun read(request:Request):Snapshot {
    validate(request);settleStarvation();return snapshot()
  }
  @Synchronized fun resume(request:Request):Snapshot {
    validate(request)
    if(state!="resumed") {
      settleStarvation()
      if(state=="paused")check(port.release(epoch)) {"ordered_continuation_resume_rejected"}
      check(port.current()) {"ordered_continuation_owner"}
      state="resumed"
      stopWatching?.invoke();stopWatching=null
    }
    return snapshot()
  }
  @Synchronized fun cancel(request:Request):Snapshot {
    require(request.scope==scope &&request.epoch==epoch &&request.checkpointId==checkpoint) {"ordered_continuation_stale"}
    if(state!="cancelled")invalidate()
    return snapshot()
  }
  @Synchronized fun invalidate(reason:String="ordered_continuation_cancelled") {
    if(state=="cancelled" &&epoch>0)return
    failure=reason
    state="cancelled";stopWatching?.invoke();stopWatching=null
    if(epoch>0)port.cancel(epoch)
  }
  @Synchronized private fun advance() {
    if(state!="buffered")return
    try {
      check(port.current()) {"ordered_continuation_owner"}
      settleStarvation()
    } catch(error:RuntimeException) {
      // This native watcher runs outside an RPC. Preserve its original cause
      // before later reads see only the normalized checkpoint rejection.
      try{port.failed(epoch,error)}catch(_:Exception){} // Observation has no safety authority.
      if(state!="cancelled")invalidate(if(error.message=="ordered_continuation_owner")
        "ordered_continuation_owner" else "ordered_continuation_native_failure")
    }
  }
  private fun validate(request:Request) {
    require(request.scope==scope &&port.current()) {"ordered_continuation_owner"}
    require(request.epoch==epoch &&checkpoint!=null &&request.checkpointId==checkpoint) {"ordered_continuation_stale"}
    check(state!="cancelled") {failure?:"ordered_continuation_cancelled"}
  }
  private fun settleStarvation() {
    if(state!="buffered" ||port.buffered())return
    sealPause()
  }
  private fun sealPause() {
    position=port.pause(epoch)
    if(position==null ||!port.current()) {
      invalidate("ordered_continuation_position_unavailable");error("ordered_continuation_position_unavailable")
    }
    state="paused"
  }
  private fun snapshot():Snapshot {
    val (published,acknowledged)=port.cursors()
    check(published in 0..MAX &&acknowledged in 0..published) {"ordered_continuation_cursor"}
    return Snapshot(scope,checkNotNull(checkpoint),epoch,state,position,published,acknowledged)
  }
  companion object {private const val MAX=9007199254740991L}
}
