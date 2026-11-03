package expo.modules.audio

/** Silent visual execution only. The port supplies real codec/queue evidence;
 * readiness, selection requests and timers cannot manufacture presentation,
 * heard audio, chunk ordinals or reader closure. All methods run on main. */
internal class NCOrderedCachedIdle(private val port:Port) {
  companion object {
    /** Passive operands of tailSettled, captured together by the Queue worker.
     * Missing evidence stays null; this is never used for playback admission. */
    fun boundaryEvidence(c:Candidate,snapshot:Map<String,Any?>?,frame:Map<String,Any>?,actualFrames:Int?):Map<String,Any?> {
      val sources=(snapshot?.get("sources") as? List<*>)?.mapNotNull{it as? Map<*,*>}
      val unfinished=sources?.filter {source->source["kind"]=="speech"
        &&((source["firstOrdinal"] as? Number)?.toLong()?.let{it<=c.afterOrdinal}!=false)
        &&(source["started"]!=true ||source["completed"]!=true)}
      val first=unfinished?.firstOrNull()
      return mapOf("after_ordinal" to c.afterOrdinal,"expected_frames" to c.afterFrameCount,
        "tail_retained" to (actualFrames!=null),"actual_frames" to actualFrames,
        "run_present" to (snapshot!=null),"run_open" to (snapshot?.get("state")=="open"),
        "stream_matches" to (snapshot?.get("streamId")==c.streamId),
        "generation_matches" to (snapshot?.get("generation")==c.generation),
        "run_failed" to (snapshot?.get("failure")!=null),"rendered_known" to frame?.get("known"),
        "rendered_ordinal" to frame?.get("ordinal"),"rendered_frame_offset" to frame?.get("frameOffset"),
        "codec_surface" to (frame?.get("provenance")=="codec_surface"),"rendered_reason" to frame?.get("reason"),
        "unfinished_speech" to unfinished?.size,"first_unfinished_ordinal" to first?.get("firstOrdinal"),
        "first_unfinished_started" to first?.get("started"),"first_unfinished_completed" to first?.get("completed"))
    }
    /** Inputs are copied from this Queue's native authority and codec witness,
     * never caller flags. In particular a last video frame cannot drain speech. */
    fun tailSettled(c:Candidate,snapshot:Map<String,Any?>,frame:Map<String,Any>,actualFrames:Int):Boolean {
      if(snapshot["streamId"]!=c.streamId ||snapshot["generation"]!=c.generation ||snapshot["failure"]!=null
        ||snapshot["state"]!="open" ||actualFrames!=c.afterFrameCount ||frame["known"]!=true
        ||frame["provenance"]!="codec_surface" ||frame["ordinal"]!=c.afterOrdinal
        ||frame["frameOffset"]!=c.afterFrameCount-1)return false
      val sources=snapshot["sources"] as? List<*>?:return false
      return sources.all {value->
        val source=value as? Map<*,*>?:return@all false
        val ordinal=(source["firstOrdinal"] as? Number)?.toLong()?:return@all false
        source["kind"]!="speech" ||ordinal>c.afterOrdinal ||source["started"]==true &&source["completed"]==true
      }
    }
  }
  data class Candidate(val streamId:String,val generation:Long,val loopId:String,val motionId:String,
    val inventoryRevision:String,val cacheEpoch:Long,val sourceFrameCount:Int,val entryFrame:Int,
    val afterOrdinal:Long,val afterFrameCount:Int,val fadeMs:Int) {
    init {
      require(streamId.matches(Regex("[a-f0-9]{32}")) &&generation in 0..9007199254740991L
        &&listOf(loopId,motionId,inventoryRevision).all{it.matches(Regex("[a-f0-9]{64}"))}
        &&cacheEpoch in 0..9007199254740991L &&sourceFrameCount in 1..1440 &&entryFrame in 0 until sourceFrameCount
        &&afterOrdinal in 0..9007199254740991L &&afterFrameCount in 1..12 &&fadeMs in 0..5000)
    }
  }
  interface Port {
    fun current():Boolean
    fun prepare(candidate:Candidate,done:(Boolean)->Unit)
    fun tailSettled(candidate:Candidate):Boolean
    fun select(candidate:Candidate):Boolean
    fun hide(fadeMs:Int)
    fun clear(done:(Boolean)->Unit)
  }
  private data class Selection(val candidate:Candidate,val revision:Long)
  private var token=0L
  private var preparing:((Boolean)->Unit)?=null
  private var ready:Candidate?=null
  private var pending:Selection?=null
  private var active:Selection?=null
  private var selecting=false
  private var highestRevision=0L
  private var first:Map<String,Any>?=null
  private var frame=-1;private var observedAt=0L
  private var closing=false
  private var joined=false;private var joining=false
  private val closeCallbacks=mutableListOf<(Boolean)->Unit>()
  fun prepare(candidate:Candidate,done:(Boolean)->Unit) {
    if(closing ||!port.current()){done(false);return}
    val revision=++token
    val previous=preparing;preparing=null;previous?.invoke(false)
    ready=null;pending=null;selecting=false;preparing=done
    port.prepare(candidate){accepted->
      if(token!=revision ||closing ||!port.current())return@prepare
      val callback=preparing;preparing=null
      if(accepted)ready=candidate
      callback?.invoke(accepted)
    }
  }
  fun arm(candidate:Candidate,revision:Long):Boolean {
    if(closing ||!port.current() ||ready?.copy(fadeMs=candidate.fadeMs,afterFrameCount=candidate.afterFrameCount)!=candidate
      ||revision !in 1..9007199254740991L)return false
    val selection=Selection(candidate,revision)
    if(pending==selection ||active==selection)return true
    if(revision<=highestRevision)return false
    highestRevision=revision;pending=selection;selecting=false;return true
  }
  fun tick() {
    val target=pending?:return
    if(closing ||!port.current() ||selecting ||!port.tailSettled(target.candidate))return
    selecting=true
    if(!port.select(target.candidate))selecting=false
  }
  private fun wire(selection:Selection,source:Int,age:Int):Map<String,Any> = mapOf(
    "activationRevision" to selection.revision,"streamId" to selection.candidate.streamId,
    "generation" to selection.candidate.generation,"loopId" to selection.candidate.loopId,
    "sourceFrame" to source,"ageMs" to age)
  fun presented(source:Int,nanos:Long) {
    if(closing ||!port.current() ||nanos<=0)return
    val target=pending
    if(selecting &&target!=null &&source==target.candidate.entryFrame){
      active=target;pending=null;selecting=false;first=wire(target,source,0)
    }
    val selected=active?:return
    if(source !in 0 until selected.candidate.sourceFrameCount ||nanos<observedAt)return
    frame=source;observedAt=nanos
  }
  fun streamPresented(ordinal:Long,running:Boolean) {
    // Media3 may preroll one real surface frame before it can run. That frame
    // remains valid evidence, but must not replace moving cached idle with a
    // still image while audio/decoder startup or rebuffering is unfinished.
    if(closing ||!port.current() ||!running)return
    val selected=active?:return
    if(ordinal<=selected.candidate.afterOrdinal)return
    active=null;first=null;observedAt=0;frame=-1
    port.hide(selected.candidate.fadeMs)
  }
  fun activation(revision:Long?=null):Map<String,Any>? = if(closing ||!port.current()
    ||revision!=null &&first?.get("activationRevision")!=revision)null else first?.toMap()
  fun position(nowNs:Long):Map<String,Any>? {
    val selected=active?:return null
    val age=nowNs-observedAt
    if(closing ||!port.current() ||observedAt<=0 ||age !in 0..250000000L)return null
    return wire(selected,frame,(age/1000000L).toInt())
  }
  fun revoke(revision:Long):Boolean {
    if(revision!=highestRevision ||revision<=0)return false
    token++;preparing?.invoke(false);preparing=null;ready=null;pending=null;selecting=false
    active=null;first=null;observedAt=0;frame=-1;port.hide(0);return true
  }
  fun close(done:(Boolean)->Unit) {
    if(joined){done(true);return}
    closeCallbacks+=done
    if(joining)return
    joining=true
    closing=true;token++;preparing?.invoke(false);preparing=null;ready=null;pending=null;selecting=false
    active=null;first=null;port.clear {safe->
      joining=false;joined=safe
      val callbacks=closeCallbacks.toList();closeCallbacks.clear();callbacks.forEach{it(safe)}
    }
  }
}
