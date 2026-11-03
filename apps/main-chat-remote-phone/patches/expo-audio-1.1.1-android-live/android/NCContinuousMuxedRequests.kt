package expo.modules.audio

/** Exact current-build RPC data. These copied labels are never native grants,
 * presentation proofs, reader certificates or permission to submit output.
 * The registry resolves them back to retained native objects before control.
 */
internal object NCContinuousMuxedRequests {
  data class Run(val id:String,val revision:Long)
  sealed interface TailSource {val run:Run;val id:String}
  data class Source(override val run:Run,override val id:String,val chunkId:String,val sequenceIndex:Int):TailSource
  data class Visual(override val run:Run,override val id:String,val parent:Source):TailSource
  data class Tail(val kind:String,val source:TailSource,val nextRange:Int,val appendRevision:Long)
  fun row(value:Any?):Map<String,Any?> {
    require(value is Map<*,*> && value.keys.all {it is String}) {"Invalid continuous request object"}
    return value.entries.associate {it.key as String to it.value}
  }
  private fun exact(value:Any?,keys:Set<String>):Map<String,Any?> = row(value).also {
    require(it.keys==keys) {"Invalid continuous request fields"}
  }
  fun integer(value:Any?,min:Long,max:Long=9007199254740991L):Long {
    val number=(value as? Number)?.toDouble()?:throw IllegalArgumentException("Invalid continuous integer")
    require(number.isFinite() && number==kotlin.math.floor(number) && number>=min.toDouble() && number<=max.toDouble())
    return number.toLong()
  }
  fun text(value:Any?,max:Int=128):String {
    require(value is String && value.isNotEmpty() && value.codePointCount(0,value.length)<=max)
    return value
  }
  private fun id(value:Any?):String = text(value).also {require(it.matches(Regex("[A-Za-z0-9_.-]{1,128}")))}
  fun envelope(value:Any?,keys:Set<String>,diagnose:(String,Boolean)->Unit={_,_->}):Map<String,Any?> {
    fun report(condition:String,valid:Boolean) {try{diagnose(condition,valid)}catch(_:Exception){}}
    val raw=try {row(value)}catch(error:Exception){report("request.object_valid",false);throw error}
    report("request.object_valid",true)
    val fieldsValid=raw.keys==keys+"version"
    report("request.fields_valid",fieldsValid)
    require(fieldsValid) {"Invalid continuous request fields"}
    try {require(integer(raw["version"],2,2)==2L)}
    catch(error:Exception){report("request.version_valid",false);throw error}
    report("request.version_valid",true)
    return raw
  }
  fun run(value:Any?):Run {
    val raw=exact(value,setOf("id","revision"))
    return Run(id(raw["id"]),integer(raw["revision"],1))
  }
  fun source(value:Any?):Source {
    val raw=exact(value,setOf("run","id","chunkId","sequenceIndex"))
    return Source(run(raw["run"]),id(raw["id"]),id(raw["chunkId"]),integer(raw["sequenceIndex"],0,63).toInt())
  }
  fun visual(value:Any?):Visual {
    val epoch=exact(value,setOf("run","id","parent"))
    val run=run(epoch["run"]);val parent=source(epoch["parent"]);val id=id(epoch["id"])
    require(run==parent.run &&id!=parent.id)
    return Visual(run,id,parent)
  }
  fun tail(value:Any?):Tail {
    val raw=exact(value,setOf("kind","source","nextRange","appendRevision"))
    val kind=raw["kind"];require(kind=="speech" ||kind=="visual")
    val owned=if(kind=="speech")source(raw["source"]) else visual(raw["source"])
    return Tail(kind as String,owned,integer(raw["nextRange"],1,if(kind=="speech")60 else 10006).toInt(),
      integer(raw["appendRevision"],1))
  }
  private fun <T> field(name:String,diagnose:(String,Boolean)->Unit,work:()->T):T {
    fun report(valid:Boolean){try{diagnose("request.$name",valid)}catch(_:Exception){}}
    val result=try{work()}catch(error:Exception){report(false);throw error}
    report(true);return result
  }
  fun descriptor(value:Any?,diagnose:(String,Boolean)->Unit={_,_->}):NCContinuousMuxedSourceDescriptor {
    fun <T> read(name:String,work:()->T)=field("descriptor.$name",diagnose,work)
    val raw=read("fields"){exact(value,setOf("ticket","owner","connectionEpoch","recoveryEpoch","replyId","chunkId",
      "sequenceIndex","expiresAtMs","mediaId","plan","motionId","sourceFrameCount","avatarId","quality",
      "firstSourceFrame","lastSourceFrame","idleReturnEntry","unsupportedAnticipation"))}
    val plan=read("plan.fields"){exact(raw["plan"],setOf("frames","samples"))}
    val quality=read("quality.fields"){exact(raw["quality"],setOf("kbps","width","fps"))}
    val expiry=read("expiresAtMs.type"){(raw["expiresAtMs"] as? Number)?.toDouble()?:throw IllegalArgumentException("Invalid continuous expiry")}
    read("expiry_and_anticipation"){require(expiry.isFinite() && expiry>0 && expiry<=9007199254740991.0 && raw["unsupportedAnticipation"] is Boolean)}
    fun ident(key:String)=read(key){id(raw[key])}
    fun txt(key:String,max:Int=128)=read(key){text(raw[key],max)}
    fun count(key:String,min:Long,max:Long=9007199254740991L)=read(key){integer(raw[key],min,max)}
    return read("contract"){NCContinuousMuxedSourceDescriptor(ident("ticket"),txt("owner",2048),txt("connectionEpoch",256),
      count("recoveryEpoch",0),ident("replyId"),ident("chunkId"),count("sequenceIndex",0,63).toInt(),
      expiry,txt("mediaId"),read("plan.contract"){NCMuxedTrialStreamRanges.Plan(read("plan.frames"){integer(plan["frames"],1,720)}.toInt(),read("plan.samples"){integer(plan["samples"],1,1441999)})},
      txt("motionId"),count("sourceFrameCount",1,1440).toInt(),txt("avatarId",256),
      read("quality.contract"){NCContinuousMuxedSourceDescriptor.Quality(read("quality.kbps"){integer(quality["kbps"],100,2000)}.toInt(),
        read("quality.width"){integer(quality["width"],160,448)}.toInt(),read("quality.fps"){integer(quality["fps"],24,24)}.toInt())},
      count("firstSourceFrame",0,1439).toInt(),count("lastSourceFrame",0,1439).toInt(),
      count("idleReturnEntry",0,1439).toInt(),raw["unsupportedAnticipation"] as Boolean,
      java.util.UUID.randomUUID().toString())}
  }
  fun returnDescriptor(value:Any?,parent:NCContinuousMuxedSourceDescriptor):NCContinuousMuxedReturnDescriptor {
    val raw=exact(value,setOf("finalSequenceIndex","sourceId","requestId","mediaId","scopeIdentity",
      "motionId","sourceFrameCount","avatarId","quality","startFrame","expiresAtMs"))
    val quality=exact(raw["quality"],setOf("kbps","width","fps"))
    val expiry=(raw["expiresAtMs"] as? Number)?.toDouble()?:throw IllegalArgumentException("Invalid continuous expiry")
    require(expiry.isFinite() &&expiry>0 &&expiry<=9007199254740991.0)
    return NCContinuousMuxedReturnDescriptor(parent,integer(raw["finalSequenceIndex"],0,63).toInt(),
      text(raw["sourceId"]),text(raw["requestId"]),text(raw["mediaId"]),text(raw["scopeIdentity"],256),
      text(raw["motionId"]),integer(raw["sourceFrameCount"],1,1440).toInt(),text(raw["avatarId"],256),
      NCContinuousMuxedSourceDescriptor.Quality(integer(quality["kbps"],100,2000).toInt(),
        integer(quality["width"],160,448).toInt(),integer(quality["fps"],24,24).toInt()),
      integer(raw["startFrame"],0,1439).toInt(),expiry,java.util.UUID.randomUUID().toString()).also {
        require(it.matches(parent)) {"Continuous RETURN descriptor changed"}
      }
  }
  fun orderedChunk(value:Any?):NCOrderedOutputChunk {
    val raw=exact(value,setOf("version","streamId","generation","ordinal","predecessor","kind",
      "sourceId","sourceRange","mediaId","frameCount","fps","sampleCount","replyId","sequenceIndex",
      "sha256","byteLength"))
    require(integer(raw["version"],1,1)==1L)
    val range=exact(raw["sourceRange"],setOf("start","totalFrames","frames"))
    val frames=range["frames"] as? List<*>?:throw IllegalArgumentException("Invalid output frame list")
    require(frames.size in 1..12)
    val provenance=frames.map {
      val frame=exact(it,setOf("sourceId","frame","sourceFrameCount"))
      NCOrderedOutputChunk.Frame(text(frame["sourceId"],160),integer(frame["frame"],0),integer(frame["sourceFrameCount"],1))
    }
    return NCOrderedOutputChunk(text(raw["streamId"]),integer(raw["generation"],0),integer(raw["ordinal"],0),
      raw["predecessor"]?.let{integer(it,0)},text(raw["kind"]),text(raw["sourceId"],160),
      NCOrderedOutputChunk.SourceRange(integer(range["start"],0),integer(range["totalFrames"],1),provenance),
      text(raw["mediaId"]),integer(raw["frameCount"],1,12).toInt(),integer(raw["fps"],24,24).toInt(),
      integer(raw["sampleCount"],1,25999).toInt(),raw["replyId"]?.let{text(it,160)},
      raw["sequenceIndex"]?.let{integer(it,0)},text(raw["sha256"]),integer(raw["byteLength"],1,16L*1024*1024))
  }
  fun orderedEnvelope(value:Any?,keys:Set<String>):Map<String,Any?> = exact(value,keys+"version").also {
    require(integer(it["version"],1,1)==1L) {"Invalid ordered output protocol"}
  }
  fun orderedSession(value:Any?):NCOrderedMuxedSessionDescriptor {
    val raw=exact(value,setOf("ticket","owner","connectionEpoch","recoveryEpoch","streamId","generation","expiresAtMs"))
    return NCOrderedMuxedSessionDescriptor(id(raw["ticket"]),text(raw["owner"],2048),text(raw["connectionEpoch"],256),
      integer(raw["recoveryEpoch"],0),text(raw["streamId"]),integer(raw["generation"],0),integer(raw["expiresAtMs"],1).toDouble())
  }
  fun orderedDescriptor(value:Any?,session:NCOrderedMuxedSessionDescriptor):NCOrderedMuxedSourceDescriptor {
    val raw=exact(value,setOf("kind","sourceId","replyId","sequenceIndex","mediaId","plan","firstOrdinal","expiresAtMs"))
    val plan=exact(raw["plan"],setOf("frames","samples"))
    return NCOrderedMuxedSourceDescriptor(session,text(raw["kind"]),id(raw["sourceId"]),raw["replyId"]?.let{ id(it) },
      raw["sequenceIndex"]?.let{integer(it,0,63).toInt()},text(raw["mediaId"]),
      NCMuxedTrialStreamRanges.Plan(integer(plan["frames"],1,720).toInt(),integer(plan["samples"],1,1441999)),
      integer(raw["firstOrdinal"],0),integer(raw["expiresAtMs"],1).toDouble(),java.util.UUID.randomUUID().toString())
  }
}

/** Per registered player, finite-trial reference ownership only. Output and
 * receipt state stay in the retained Queue/Authority/Guard, including after a
 * run retires. Registry locks never enter Queue/Authority/Guard monitors.
 */
internal class NCContinuousMuxedRegistry {
  class Record internal constructor(val run:NCContinuousMuxedAuthority.RunHandle,val queue:NCContinuousMuxedQueue) {
    internal val sources=linkedMapOf<String,NCContinuousMuxedAuthority.SourceGrant>()
    internal val stages=linkedMapOf<String,Stage>()
    internal val visualStages=linkedMapOf<String,VisualStage>()
  }
  data class Stage(val descriptor:NCContinuousMuxedSourceDescriptor,
    val grant:NCContinuousMuxedAuthority.SourceGrant?,val firstRange:Int)
  data class VisualStage(val descriptor:NCContinuousMuxedReturnDescriptor,
    val parent:NCContinuousMuxedAuthority.SourceGrant,val grant:NCContinuousMuxedAuthority.VisualGrant?,
    val tail:NCContinuousMuxedRequests.Tail)
  private val records=linkedMapOf<String,Record>()
  @Synchronized fun hasSourceCapacity():Boolean=records.values.sumOf {it.sources.size}<64
  fun publish(run:NCContinuousMuxedAuthority.RunHandle,queue:NCContinuousMuxedQueue,
    source:NCContinuousMuxedAuthority.SourceGrant):Record? {
    if(source.run!==run || source.origin!==queue.authority || queue.runRevision!=run.revision
      || queue.authority.sourceState(source)==null || queue.snapshot().tail?.sourceHandle!=source.id
      || queue.nativeEnrollment()?.first?.run!==run)return null
    return synchronized(this) {
      if(run.id in records || records.values.sumOf {it.sources.size}>=64)return@synchronized null
      Record(run,queue).also {it.sources[source.id]=source;records[run.id]=it}
    }
  }
  @Synchronized fun resolveRun(wire:NCContinuousMuxedRequests.Run):Record? =
    records[wire.id]?.takeIf {it.run.revision==wire.revision}
  fun retainSource(record:Record,source:NCContinuousMuxedAuthority.SourceGrant):Boolean {
    if(source.run!==record.run || source.origin!==record.queue.authority || record.queue.authority.sourceState(source)==null)return false
    return synchronized(this) {
      if(records[record.run.id]!==record)return@synchronized false
      record.sources[source.id]?.let {return@synchronized it===source}
      if(records.values.sumOf {it.sources.size}>=64)return@synchronized false
      record.sources[source.id]=source;true
    }
  }
  fun resolveSource(record:Record,wire:NCContinuousMuxedRequests.Source):NCContinuousMuxedAuthority.SourceGrant? {
    val source=synchronized(this) {
      if(records[record.run.id]!==record || wire.run.id!=record.run.id || wire.run.revision!=record.run.revision)return null
      record.sources[wire.id]?.takeIf {it.chunkId==wire.chunkId && it.sequenceIndex==wire.sequenceIndex}
    }?:return null
    return source.takeIf {it.run===record.run && it.origin===record.queue.authority && record.queue.authority.sourceState(it)!=null}
  }
  fun resolveTail(record:Record,wire:NCContinuousMuxedRequests.Tail):NCContinuousMuxedQueueState.Tail? {
    val sourceId=when(val source=wire.source) {
      is NCContinuousMuxedRequests.Source->resolveSource(record,source)?.id?:return null
      is NCContinuousMuxedRequests.Visual->{
        val parent=resolveSource(record,source.parent)?:return null
        val visual=record.queue.authority.nativeVisualGrant(record.run,source.id)?:return null
        if(visual.parent!==parent)return null
        visual.id
      }
    }
    val snapshot=record.queue.snapshot();val tail=snapshot.tail?:return null
    return tail.takeIf {it.sourceHandle==sourceId && it.lastRange+1==wire.nextRange && snapshot.mutationRevision==wire.appendRevision}
  }
  fun sourceDescriptor(record:Record,wire:NCContinuousMuxedRequests.Source):NCContinuousMuxedSourceDescriptor? =
    resolveSource(record,wire)?.let {record.queue.authority.sourceDescriptor(it)}
  @Synchronized fun rememberStage(record:Record,token:String,stage:Stage):Boolean {
    if(records[record.run.id]!==record || token in record.stages ||token in record.visualStages
      ||record.stages.size+record.visualStages.size>=60)return false
    if(stage.grant!=null && record.sources[stage.grant.id]!==stage.grant)return false
    record.stages[token]=stage;return true
  }
  @Synchronized fun resolveStage(record:Record,token:String):Stage? =
    record.stages[token].takeIf {records[record.run.id]===record}
  @Synchronized fun forgetStage(record:Record,token:String):Boolean =
    records[record.run.id]===record && record.stages.remove(token)!=null
  @Synchronized fun rememberVisualStage(record:Record,token:String,stage:VisualStage):Boolean {
    if(records[record.run.id]!==record ||token in record.stages ||token in record.visualStages
      ||record.stages.size+record.visualStages.size>=60 ||record.sources[stage.parent.id]!==stage.parent)return false
    record.visualStages[token]=stage;return true
  }
  @Synchronized fun resolveVisualStage(record:Record,token:String):VisualStage? =
    record.visualStages[token].takeIf {records[record.run.id]===record}
  @Synchronized fun forgetVisualStage(record:Record,token:String):Boolean =
    records[record.run.id]===record &&record.visualStages.remove(token)!=null
  fun wireRun(run:NCContinuousMuxedAuthority.RunHandle):Map<String,Any> = mapOf("id" to run.id,"revision" to run.revision)
  fun wireSource(source:NCContinuousMuxedAuthority.SourceGrant):Map<String,Any> = mapOf("run" to wireRun(source.run),
    "id" to source.id,"chunkId" to source.chunkId,"sequenceIndex" to source.sequenceIndex)
  fun wireVisual(visual:NCContinuousMuxedAuthority.VisualGrant):Map<String,Any> =
    mapOf("run" to wireRun(visual.run),"id" to visual.id,"parent" to wireSource(visual.parent))
  fun wireTail(record:Record):Map<String,Any>? {
    val snapshot=record.queue.snapshot();val tail=snapshot.tail?:return null
    val source=synchronized(this) {if(records[record.run.id]!==record)return null;record.sources[tail.sourceHandle]}
    val visual=if(source==null)record.queue.authority.nativeVisualGrant(record.run,tail.sourceHandle)?:return null else null
    if(visual!=null &&synchronized(this) {record.sources[visual.parent.id]!==visual.parent})return null
    val wire=source?.let {wireSource(it)}?:mapOf("run" to wireRun(visual!!.run),"id" to visual.id,
      "parent" to wireSource(visual.parent))
    return mapOf("kind" to if(source!=null)"speech" else "visual","source" to wire,
      "nextRange" to tail.lastRange+1,"appendRevision" to snapshot.mutationRevision)
  }
}
