package expo.modules.audio

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Worker-side current-build RPCs. Port schedules the registered player's
 * actual OS effects; native Queue/Authority/Controller own every grant, ACK,
 * output proof and reader. These operations never play or unlink a file.
 */
internal class NCContinuousMuxedRpc(private val port:Port,
  private val orderedDiagnose:(String,Map<String,Any?>)->Unit={_,_->},
  private val diagnose:(String,Boolean)->Unit={_,_->}) {
  private fun observed(condition:String,value:Boolean):Boolean {
    try{diagnose(condition,value)}catch(_:Exception){}
    return value
  }
  companion object {
    const val PROTOCOL_VERSION=2
    const val LIVE_VERSION=2 // Current-build mixed speech/visual protocol; hardware acceptance is separate.
    const val ORDERED_VERSION=1 // Complete Desktop + mobile wiring; physical acceptance is separate.
    const val ORDERED_CONTINUATION_VERSION=1
  }
  data class MixedSettlement(val witness:NCContinuousMuxedSinkController.SinkSettlement?)
  interface Port {
    fun current():Boolean
    fun onMain(action:()->Unit)
    fun validate(rows:List<Map<String,Any>>,first:Int,d:NCContinuousMuxedSourceDescriptor,prefix:Boolean):List<NCMuxedTrialPlayer.Clip>
    fun validateVisual(rows:List<Map<String,Any>>,first:Int):List<NCMuxedTrialPlayer.Clip>
    fun beforeOpen():Boolean
    fun begin(d:NCContinuousMuxedSourceDescriptor):NCContinuousMuxedQueue?
    fun validateOrdered(rows:List<Map<String,Any>>,output:List<NCOrderedOutputChunk>,
      d:NCOrderedMuxedSourceDescriptor):List<NCMuxedTrialPlayer.Clip> = error("Ordered validation unavailable")
    fun beginOrdered(d:NCOrderedMuxedSessionDescriptor):NCContinuousMuxedQueue? = null
    fun forgetClosedOrdered(queue:NCContinuousMuxedQueue):Boolean = false
    fun orderedContinuation(queue:NCContinuousMuxedQueue,scope:NCOrderedContinuation.Scope):NCOrderedContinuation.Port? = null
    fun owns(queue:NCContinuousMuxedQueue):Boolean
    fun attach(queue:NCContinuousMuxedQueue,done:(Boolean)->Unit):Boolean
    fun settle(queue:NCContinuousMuxedQueue,done:(Boolean)->Unit):Boolean
    fun settleOrdered(queue:NCContinuousMuxedQueue,done:(Boolean)->Unit):Boolean = false
    fun settleMixed(queue:NCContinuousMuxedQueue,done:(MixedSettlement)->Unit):Boolean = false
    fun releaseMixed(queue:NCContinuousMuxedQueue,certificate:NCContinuousMuxedQueue.MixedRetirement,done:(Boolean)->Unit):Boolean = false
    fun closeUnenrolled(queue:NCContinuousMuxedQueue,readers:NCContinuousMuxedQueue.DetachedReaders,done:(Boolean)->Unit):Boolean
  }
  private val registry=NCContinuousMuxedRegistry()
  private class OrderedRecord(val session:NCOrderedMuxedSessionDescriptor,val run:NCContinuousMuxedAuthority.RunHandle,
    val queue:NCContinuousMuxedQueue) {
    val sources=java.util.concurrent.ConcurrentHashMap<String,NCContinuousMuxedAuthority.OrderedGrant>()
    val stages=java.util.concurrent.ConcurrentHashMap<String,OrderedStage>()
    var continuation:NCOrderedContinuation?=null
  }
  private data class OrderedStage(val descriptor:NCOrderedMuxedSourceDescriptor,
    val grant:NCContinuousMuxedAuthority.OrderedGrant?)
  private val orderedRecords=java.util.concurrent.ConcurrentHashMap<String,OrderedRecord>()
  private data class OrderedClosure(val run:NCContinuousMuxedAuthority.RunHandle,val result:Map<String,Any?>)
  @Volatile private var lastOrderedClosure:OrderedClosure?=null
  private var orderedStreamId:String?=null
  private var highestOrderedGeneration=-1L
  private val owned=java.util.concurrent.ConcurrentHashMap.newKeySet<NCContinuousMuxedQueue>()
  private val detached=java.util.concurrent.ConcurrentHashMap.newKeySet<NCContinuousMuxedQueue>()
  private val settled=java.util.concurrent.ConcurrentHashMap.newKeySet<NCContinuousMuxedQueue>()
  private val published=java.util.concurrent.ConcurrentHashMap.newKeySet<NCContinuousMuxedQueue>()
  private val abandoned=java.util.concurrent.ConcurrentHashMap.newKeySet<NCContinuousMuxedQueue>()
  @Volatile private var closed=false
  private var opening=false
  private val diagnosticInstance=java.util.UUID.randomUUID().toString()
  // Lifecycle boundaries only. No per-chunk/presentation sampling and no raw capabilities.
  private fun diagnosticRun(id:String,revision:Long)=mapOf(
    "run_hash" to java.security.MessageDigest.getInstance("SHA-256").digest(id.toByteArray(Charsets.UTF_8))
      .joinToString(""){"%02x".format(it)},"run_revision" to revision)
  private fun orderedEvidence(event:String,details:()->Map<String,Any?> = {emptyMap()}) {
    try{orderedDiagnose(event,mapOf("rpc_instance" to diagnosticInstance)+details())}catch(_:Exception){}
  }
  init{orderedEvidence("created")}
  private val request=NCContinuousMuxedRequests
  private fun envelope(value:Any?,keys:Set<String>)=request.envelope(value,keys,diagnose)
  private fun <T> main(action:()->T):T {
    var value:T?=null;var failure:Throwable?=null
    port.onMain {try {value=action()}catch(error:Throwable){failure=error}}
    failure?.let {throw it}
    @Suppress("UNCHECKED_CAST") return value as T
  }
  private fun deadline()=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(5000)
  private fun remaining(end:Long)=TimeUnit.NANOSECONDS.toMillis((end-System.nanoTime()).coerceAtLeast(0))
  private fun <T:Any> await(end:Long,start:((T)->Unit)->Boolean):T? {
    val result=AtomicReference<T?>();val latch=CountDownLatch(1)
    val once=java.util.concurrent.atomic.AtomicBoolean(false)
    val scheduled=main {start {value->if(once.compareAndSet(false,true)){result.set(value);latch.countDown()}}}
    if(!observed("wait.scheduled",scheduled) && !observed("wait.inline_callback",once.get()))return null
    try {if(!observed("wait.callback_completed",latch.await((end-System.nanoTime()).coerceAtLeast(0),TimeUnit.NANOSECONDS)))return null}
    catch(_:InterruptedException){observed("wait.not_interrupted",false);Thread.currentThread().interrupt();return null}
    return result.get()
  }
  private fun <T> found(kind:String,value:T?):T? {observed("registry.${kind}_found",value!=null);return value}
  private fun resolveRun(wire:NCContinuousMuxedRequests.Run)=found("run",registry.resolveRun(wire))
  private fun record(value:Any?)=resolveRun(request.run(value))?:error("Unknown continuous run")
  private fun source(value:Any?):Pair<NCContinuousMuxedRegistry.Record,NCContinuousMuxedAuthority.SourceGrant> {
    val wire=request.source(value);val record=resolveRun(wire.run)?:error("Unknown continuous run")
    return record to (found("source",registry.resolveSource(record,wire))?:error("Unknown continuous source"))
  }
  private fun mutable(record:NCContinuousMuxedRegistry.Record)=observed("mutation.not_closed",!closed)
    && observed("mutation.player_current",port.current()) && observed("mutation.queue_owned",port.owns(record.queue))
  private fun files(value:Any?):List<Map<String,Any>> {
    val isList=value is List<*>;observed("request.files.list",isList)
    require(value is List<*> && observed("request.files.count",value.size in 1..6)) {"Invalid continuous file batch"}
    return value.mapIndexed {index,item->
      val row=try{request.row(item)}catch(error:Exception){observed("request.files.$index.object",false);throw error}
      observed("request.files.$index.object",true)
      row.mapValues {(_,entry)->observed("request.files.$index.value_present",entry!=null);requireNotNull(entry)}
    }
  }
  private fun result(kind:String)=mapOf<String,Any>("version" to PROTOCOL_VERSION,"kind" to kind)
  private fun blocked(reason:String)=result("blocked")+mapOf("reason" to reason)
  private fun orderedCheck(name:String,value:Boolean) {check(observed("ordered.$name",value)) {"Ordered output rejected: $name"}}
  private fun orderedRecord(value:Any?,operation:String,reason:Any?=null):OrderedRecord {
    val wire=request.run(value)
    val found=orderedRecords[wire.id]
    if(found!=null &&found.run.revision==wire.revision)return found
    observed("ordered.lookup.run_found",found!=null)
    if(found!=null)observed("ordered.lookup.revision_matches",false)
    orderedEvidence("lookup_failed") {
      val records=orderedRecords.values.toList()
      mapOf("operation" to operation,"requested" to diagnosticRun(wire.id,wire.revision),
        "reason" to (reason as? String)?.takeIf{it in setOf("stop","skip","replacement","expiry","recovery","failure")},
        "lookup_result" to if(found==null)"absent" else "revision_mismatch",
        "found_at_lookup" to found?.let{diagnosticRun(it.run.id,it.run.revision)},
        "rpc_closed" to closed,"rpc_opening" to opening,"player_current" to port.current(),
        "registered_count" to records.size,"registered" to records.take(4).map {
          diagnosticRun(it.run.id,it.run.revision)+mapOf("generation" to it.session.generation,
            "queue_owned" to port.owns(it.queue),"queue_state" to it.queue.snapshot().state.name)
        },"registered_truncated" to (records.size>4),
        "last_closed" to lastOrderedClosure?.let{diagnosticRun(it.run.id,it.run.revision)})
    }
    error("Ordered output run unavailable")
  }
  private fun orderedMutable(record:OrderedRecord)=observed("ordered.owner.not_closed",!closed)
    &&observed("ordered.owner.player_current",port.current()) &&observed("ordered.owner.queue_owned",port.owns(record.queue))
  private fun orderedChunks(value:Any?,d:NCOrderedMuxedSourceDescriptor):List<NCOrderedOutputChunk> {
    require(value is List<*> &&value.size in 1..6) {"Invalid ordered output batch"}
    return value.map{request.orderedChunk(it)}.also{rows->
      orderedCheck("descriptor_matches",rows.all{d.matches(it)})
      orderedCheck("batch_contiguous",rows.zipWithNext().all{(a,b)->b.ordinal==a.ordinal+1
        &&b.sourceRange.start==a.sourceRange.end})
    }
  }
  fun openOrdered(value:Any?):Map<String,Any?> {
    val raw=request.orderedEnvelope(value,setOf("session","descriptor","output","files"))
    val session=request.orderedSession(raw["session"]);val d=request.orderedDescriptor(raw["descriptor"],session)
    orderedCheck("initial_visual",d.silent &&d.firstOrdinal==0L)
    val chunks=orderedChunks(raw["output"],d)
    synchronized(this) {
      orderedCheck("open_current",!closed &&!opening &&port.current() &&orderedRecords.isEmpty())
      orderedCheck("generation_fresh",(orderedStreamId==null ||orderedStreamId==session.streamId)
        &&session.generation>highestOrderedGeneration)
      opening=true
    }
    var queue:NCContinuousMuxedQueue?=null
    try {
      val clips=port.validateOrdered(files(raw["files"]),chunks,d)
      orderedCheck("initial_settlement",port.current() &&port.beforeOpen())
      val q=main{
        if(closed)orderedCheck("open_main_not_closed",false)
        if(!port.current())orderedCheck("open_main_player_current",false)
        port.beginOrdered(session)
      }
      if(q==null){observed("ordered.open_player_available",false);error("Ordered player unavailable")}
      queue=q;owned+=q
      val run=q.beginOrderedRun(session)?:error("Ordered visual ownership rejected")
      val staged=q.stageOrderedResult(d,chunks,clips,q.runRevision)
      orderedCheck("initial_stage.${staged.reason?:"accepted"}",staged.token!=null)
      val stage=staged.token!!
      var failure:String?=null
      val grant=q.authority.admitOrderedSource(run,d,0){failure=it;observed("ordered.admission.$it",false)}
        ?:error("Ordered initial admission rejected: ${failure?:"missing_reason"}")
      val end=deadline()
      val ack=await<NCContinuousMuxedQueueState.Ack>(end){done->q.appendOrdered(stage,grant,0,done)}
      orderedCheck("initial_timeline_ack",ack?.outcome==NCContinuousMuxedQueueState.Outcome.COMMITTED)
      orderedCheck("output_enrollment",await<Boolean>(end){done->port.attach(q,done)}==true)
      orderedCheck("open_not_cancelled",!closed &&port.current() &&!q.authority.nativeOutputLease(run)!!.isRevoked)
      val record=OrderedRecord(session,run,q);record.sources[grant.id]=grant
      synchronized(this) {
        orderedCheck("publication_current",!closed &&port.current())
        orderedRecords[run.id]=record;published+=q
        orderedStreamId=session.streamId;highestOrderedGeneration=session.generation
        orderedEvidence("published"){diagnosticRun(run.id,run.revision)+mapOf("generation" to session.generation)}
      }
      return mapOf("version" to 1,"run" to registry.wireRun(run),"sourceId" to grant.id,
        "snapshot" to q.authority.orderedSnapshot(run))
    }catch(error:Throwable){queue?.fence("ordered_open_failed");throw error}
    finally{synchronized(this){opening=false}}
  }
  fun stageOrdered(value:Any?):Map<String,Any?> {
    val copied=request.row(value);val continuing="sourceId" in copied
    val raw=request.orderedEnvelope(copied,if(continuing)setOf("run","sourceId","output","files")
      else setOf("run","descriptor","output","files"))
    val record=orderedRecord(raw["run"],"stage")
    val prior=if(continuing)record.sources[request.text(raw["sourceId"])]?:error("Ordered source unavailable") else null
    val d=prior?.descriptor?:request.orderedDescriptor(raw["descriptor"],record.session)
    val chunks=orderedChunks(raw["output"],d)
    orderedCheck("prefix_or_continuation",(chunks.first().sourceRange.start==0L)==!continuing)
    val clips=port.validateOrdered(files(raw["files"]),chunks,d)
    return main {
      orderedCheck("stage_owner",orderedMutable(record))
      val staged=record.queue.stageOrderedResult(d,chunks,clips,record.run.revision)
      if(staged.status==NCContinuousMuxedQueueState.StageStatus.CAPACITY)
        return@main mapOf("version" to 1,"kind" to "blocked","reason" to "capacity")
      if(staged.reason=="mutation_pending")return@main mapOf("version" to 1,"kind" to "blocked","reason" to "mutation_pending")
      orderedCheck("stage.${staged.reason?:"accepted"}",staged.token!=null)
      val token=staged.token!!
      record.stages[token]=OrderedStage(d,prior)
      mapOf("version" to 1,"kind" to "staged","stageId" to token)
    }
  }
  fun appendOrdered(value:Any?):Map<String,Any?> {
    val raw=request.orderedEnvelope(value,setOf("run","stageId","expectedOrdinal","expectedRevision"))
    val record=orderedRecord(raw["run"],"append");val token=request.text(raw["stageId"])
    val stage=record.stages[token]?:error("Ordered stage unavailable")
    val revision=request.integer(raw["expectedRevision"],0);val ordinal=request.integer(raw["expectedOrdinal"],0)
    var rejection:String?=null
    val grant=main {
      orderedCheck("append_owner",orderedMutable(record))
      val snapshot=record.queue.snapshot()
      orderedCheck("append_tail",revision==snapshot.mutationRevision &&ordinal==(snapshot.tail?.ordinal?.plus(1)?:0L))
      stage.grant?:record.queue.authority.admitOrderedSource(record.run,stage.descriptor,revision) {
        rejection=it;if(!it.startsWith("capacity."))observed("ordered.admission.$it",false)
      }?.also{record.sources[it.id]=it}
    }
    if(grant==null) {
      if(rejection?.startsWith("capacity.")==true)return mapOf("version" to 1,"kind" to "blocked","reason" to "capacity")
      error("Ordered source admission rejected: ${rejection?:"missing_reason"}")
    }
    val ack=await<NCContinuousMuxedQueueState.Ack>(deadline()){done->
      if(!orderedMutable(record))false else record.queue.appendOrdered(token,grant,revision,done)}
    if(ack?.outcome!=NCContinuousMuxedQueueState.Outcome.COMMITTED) {
      record.queue.fence("ordered_append_unconfirmed");error("Ordered timeline mutation unconfirmed")
    }
    record.stages.remove(token)
    return mapOf("version" to 1,"kind" to "appended","sourceId" to grant.id,
      "snapshot" to record.queue.authority.orderedSnapshot(record.run))
  }
  fun readOrdered(value:Any?):Map<String,Any?> {
    val raw=request.orderedEnvelope(value,setOf("run","cursor"));val record=orderedRecord(raw["run"],"read")
    return record.queue.authority.readOrderedJournal(record.run,request.integer(raw["cursor"],0))
      ?:error("Ordered journal cursor unavailable")
  }
  fun readOrderedPlaybackClock(value:Any?):Map<String,Any?> {
    val raw=request.orderedEnvelope(value,setOf("ticket","run","streamId","generation"))
    val record=orderedRecord(raw["run"],"clock")
    require(request.text(raw["ticket"])==record.session.ticket &&request.text(raw["streamId"])==record.session.streamId
      &&request.integer(raw["generation"],0)==record.session.generation) {"ordered_playback_clock_scope"}
    check(!closed &&port.current() &&port.owns(record.queue)) {"ordered_playback_clock_owner"}
    return record.queue.authority.orderedPlaybackClock(record.run)?:error("ordered_playback_clock_unavailable")
  }
  internal fun cachedOrderedQueue(value:Any?,cleanup:Boolean=false):NCContinuousMuxedQueue {
    val record=orderedRecord(value,"cached")
    if(!cleanup)orderedCheck("cached.current",orderedMutable(record))
    return record.queue
  }
  private fun continuation(value:Any?,operation:String):Map<String,Any?> {
    val keys=setOf("ticket","run","streamId","generation","recoveryEpoch")+
      if(operation=="suspend")emptySet() else setOf("checkpointId")
    val raw=request.orderedEnvelope(value,keys)
    val record=orderedRecord(raw["run"],"continuation_$operation")
    val scope=NCOrderedContinuation.Scope(request.text(raw["ticket"]),request.text(raw["streamId"]),
      request.integer(raw["generation"],0),record.run.id,record.run.revision)
    require(scope.ticket==record.session.ticket &&scope.streamId==record.session.streamId
      &&scope.generation==record.session.generation) {"ordered_continuation_owner"}
    val command=NCOrderedContinuation.Request(scope,request.integer(raw["recoveryEpoch"],1),
      if(operation=="suspend")null else request.text(raw["checkpointId"]))
    return synchronized(record) {
      if(operation!="cancel")orderedCheck("continuation_current",orderedMutable(record))
      val adapter=record.continuation?:run {
        check(operation=="suspend") {"ordered_continuation_absent"}
        val native=port.orderedContinuation(record.queue,scope)?:error("ordered_continuation_unavailable")
        NCOrderedContinuation(scope,native).also{record.continuation=it}
      }
      when(operation) {
        "suspend"->adapter.suspend(command)
        "read"->adapter.read(command)
        "resume"->adapter.resume(command)
        "cancel"->adapter.cancel(command)
        else->error("ordered_continuation_operation")
      }.wire()
    }
  }
  fun suspendOrderedTransport(value:Any?)=continuation(value,"suspend")
  fun readOrderedContinuation(value:Any?)=continuation(value,"read")
  fun resumeOrderedTransport(value:Any?)=continuation(value,"resume")
  fun cancelOrderedContinuation(value:Any?)=continuation(value,"cancel")
  fun invalidateOrdered(value:Any?):Boolean {
    val raw=request.orderedEnvelope(value,setOf("run","reason"));val record=orderedRecord(raw["run"],"invalidate",raw["reason"])
    val reason=request.text(raw["reason"])
    require(reason in setOf("stop","skip","replacement","expiry","recovery","failure"))
    orderedEvidence("invalidate_requested"){diagnosticRun(record.run.id,record.run.revision)+mapOf("reason" to reason)}
    record.queue.fence(reason)
    record.continuation?.invalidate()
    orderedEvidence("invalidated"){diagnosticRun(record.run.id,record.run.revision)+mapOf("reason" to reason)}
    return true
  }
  fun dropOrdered(value:Any?):Boolean {
    val raw=request.orderedEnvelope(value,setOf("run","stageId"));val record=orderedRecord(raw["run"],"drop")
    val token=request.text(raw["stageId"]);val stage=record.stages[token]?:return false
    return main {record.queue.dropStage(token) &&record.stages.remove(token,stage)}
  }
  /** Return file custody only after native detach, delegated reader joins and
   * positive physical-output settlement. Keep one idempotent closure, not an
   * unbounded history of retired queues or source grants. */
  fun closeOrdered(value:Any?):Map<String,Any?> {
    val raw=request.orderedEnvelope(value,setOf("run"));val wire=request.run(raw["run"])
    lastOrderedClosure?.let {if(it.run.id==wire.id &&it.run.revision==wire.revision)return it.result}
    val record=orderedRecord(raw["run"],"close")
    orderedEvidence("close_requested"){diagnosticRun(record.run.id,record.run.revision)}
    return synchronized(record) {
      lastOrderedClosure?.let {if(it.run===record.run)return@synchronized it.result}
      orderedCheck("close_invalidated",record.queue.snapshot().state in listOf(
        NCContinuousMuxedQueueState.State.FAILED,NCContinuousMuxedQueueState.State.RETIRED))
      record.continuation?.invalidate()
      if(!closeQueue(record.queue,retainOrderedSettlement=true))return@synchronized mapOf("version" to 1,"kind" to "pending")
      val snapshot=record.queue.authority.orderedSnapshot(record.run)?:error("Ordered closure snapshot unavailable")
      if(!main{port.forgetClosedOrdered(record.queue)})return@synchronized mapOf("version" to 1,"kind" to "pending")
      // Physical settlement and all reader joins precede sealing. A pending
      // codec callback remains explicit unknown evidence, never a clock guess.
      val stopped=mapOf("version" to 1,"streamId" to record.session.streamId,
        "generation" to record.session.generation)+record.queue.sealStoppedVideo()
      val result=mapOf("version" to 1,"kind" to "closed","snapshot" to snapshot,"stoppedOutput" to stopped)
      synchronized(this) {
        val q=record.queue
        lastOrderedClosure=OrderedClosure(record.run,result)
        record.stages.clear();record.sources.clear();val removed=orderedRecords.remove(record.run.id,record)
        orderedEvidence("removed"){diagnosticRun(record.run.id,record.run.revision)+mapOf("removed" to removed)}
        owned.remove(q);detached.remove(q);settled.remove(q);published.remove(q);abandoned.remove(q)
      }
      result
    }
  }
  fun completeReplyOrdered(value:Any?):Boolean {
    val raw=request.orderedEnvelope(value,setOf("run","replyId","finalSequenceIndex"))
    val record=orderedRecord(raw["run"],"complete_reply")
    return orderedMutable(record) &&record.queue.authority.completeOrderedReply(record.run,
      request.text(raw["replyId"]),request.integer(raw["finalSequenceIndex"],0,63).toInt())
  }
  fun pruneOrdered(value:Any?):Map<String,Any?> {
    val raw=request.orderedEnvelope(value,setOf("run","beforeOrdinal"));val record=orderedRecord(raw["run"],"prune")
    orderedCheck("prune_owner",orderedMutable(record))
    val before=request.integer(raw["beforeOrdinal"],0);val q=record.queue;val end=deadline()
    val ack=await<NCContinuousMuxedQueueState.Ack>(end){done->
      if(!orderedMutable(record))false else q.prune(before,q.snapshot().mutationRevision,done)}
    val joined=ack?.outcome==NCContinuousMuxedQueueState.Outcome.COMMITTED &&q.awaitPrunedReaders(remaining(end))
    return mapOf("version" to 1,"kind" to if(joined)"joined" else "pending",
      "snapshot" to q.authority.orderedSnapshot(record.run))
  }
  fun acknowledgeOrdered(value:Any?):Boolean {
    val raw=request.orderedEnvelope(value,setOf("run","cursor"));val record=orderedRecord(raw["run"],"acknowledge")
    if(!record.queue.authority.acknowledgeJournal(record.run,request.integer(raw["cursor"],0)))return false
    // ACK only frees event history. Native presentation and delegated joins
    // independently gate any retained-source reclamation.
    record.sources.values.forEach{g->if(record.queue.releaseOrderedSource(g))record.sources.remove(g.id,g)}
    return true
  }
  fun open(value:Any?):Map<String,Any> {
    val raw=envelope(value,setOf("descriptor","files"));val d=request.descriptor(raw["descriptor"],diagnose)
    val rows=files(raw["files"])
    synchronized(this) {check(observed("open.not_closed",!closed) && observed("open.not_opening",!opening)
      && observed("open.player_current",port.current()) && observed("open.source_capacity",registry.hasSourceCapacity()));opening=true}
    var queue:NCContinuousMuxedQueue?=null
    try {
      val clips=port.validate(rows,0,d,true)
      check(observed("open.after_validation_current",port.current()) && observed("open.initial_settlement",port.beforeOpen())) {"Continuous initial output settlement unavailable"}
      val q=main {check(!closed && port.current());port.begin(d)}?:error("Continuous player unavailable")
      queue=q;owned+=q
      val token=q.stageResult(d,0,clips,q.runRevision).token?:error("Continuous initial staging rejected")
      val run=q.beginRun(d)?:error("Continuous run admission rejected")
      val grant=q.authority.admitSource(run,d,0)?:error("Continuous initial source rejected")
      val end=deadline()
      val ack=await<NCContinuousMuxedQueueState.Ack>(end){done->q.open(token,grant,0,done)}
      check(observed("open.mutation_committed",ack?.outcome==NCContinuousMuxedQueueState.Outcome.COMMITTED)) {"Continuous initial mutation unconfirmed"}
      check(observed("open.output_enrolled",await<Boolean>(end){done->port.attach(q,done)}==true)) {"Continuous output enrollment unconfirmed"}
      val entry=registry.publish(run,q,grant)?:error("Continuous native ownership not published")
      published+=q
      return mapOf("version" to PROTOCOL_VERSION,"run" to registry.wireRun(run),"source" to registry.wireSource(grant),
        "tail" to (registry.wireTail(entry)?:error("Missing acknowledged native tail")))
    }catch(error:Throwable){queue?.fence("open_failed");throw error}
    finally {synchronized(this){opening=false}}
  }
  fun stage(value:Any?):Map<String,Any> {
    val copied=request.row(value);val continuation="source" in copied
    val raw=envelope(copied,if(continuation)setOf("source","firstRange","files") else setOf("run","descriptor","files"))
    val record:NCContinuousMuxedRegistry.Record;val grant:NCContinuousMuxedAuthority.SourceGrant?
    val d:NCContinuousMuxedSourceDescriptor;val first:Int
    if(continuation){val pair=source(raw["source"]);record=pair.first;grant=pair.second
      d=record.queue.authority.sourceDescriptor(grant);first=request.integer(raw["firstRange"],1,59).toInt()}
    else {record=record(raw["run"]);grant=null;d=request.descriptor(raw["descriptor"],diagnose);first=0}
    val clips=port.validate(files(raw["files"]),first,d,!continuation)
    return main {
      check(mutable(record)) {"Continuous output owner ended"}
      val staged=record.queue.stageResult(d,first,clips,record.run.revision)
      if(staged.status==NCContinuousMuxedQueueState.StageStatus.CAPACITY)return@main blocked("capacity")
      val token=staged.token?:error("Continuous staging rejected")
      if(!registry.rememberStage(record,token,NCContinuousMuxedRegistry.Stage(d,grant,first))) {
        record.queue.fence("stage_registry");error("Continuous stage ownership unconfirmed")}
      result("staged")+mapOf("stageId" to token)
    }
  }
  fun append(value:Any?):Map<String,Any> {
    val raw=envelope(value,setOf("stageId","tail"));val wire=request.tail(raw["tail"])
    val record=resolveRun(wire.source.run)?:error("Unknown continuous run")
    val token=request.text(raw["stageId"]);val q=record.queue
    var grant:NCContinuousMuxedAuthority.SourceGrant?=null;var blocked:Map<String,Any>?=null
    val ack=await<NCContinuousMuxedQueueState.Ack>(deadline()) {done->
      check(mutable(record));val stage=found("stage",registry.resolveStage(record,token))?:error("Unknown continuous stage")
      if(registry.resolveTail(record,wire)==null){blocked=blocked("tail_changed");return@await false}
      grant=stage.grant
      if(grant==null) {
        if(!registry.hasSourceCapacity()){blocked=blocked("capacity");return@await false}
        val admission=q.authority.admitSourceResult(record.run,stage.descriptor,wire.appendRevision)
        when(admission.status) {
          NCContinuousMuxedAuthority.AdmissionStatus.FUTURE_OCCUPIED->{blocked=blocked("future_occupied");return@await false}
          NCContinuousMuxedAuthority.AdmissionStatus.CAPACITY->{blocked=blocked("capacity");return@await false}
          NCContinuousMuxedAuthority.AdmissionStatus.REJECTED->error("Continuous successor rejected")
          NCContinuousMuxedAuthority.AdmissionStatus.ADMITTED->grant=admission.grant!!
        }
        if(!registry.retainSource(record,grant!!)){q.fence("source_registry");error("Continuous source ownership unconfirmed")}
      }
      q.append(token,grant!!,wire.appendRevision,done)
    }
    blocked?.let {return it}
    if(ack?.outcome!=NCContinuousMuxedQueueState.Outcome.COMMITTED){q.fence("append_unconfirmed");error("Continuous append unconfirmed")}
    check(registry.forgetStage(record,token))
    return result("admitted")+mapOf("source" to registry.wireSource(grant!!))
  }
  fun stageReturn(value:Any?):Map<String,Any> {
    val raw=envelope(value,setOf("tail","descriptor","files"));val wire=request.tail(raw["tail"])
    val parentWire=wire.source as? NCContinuousMuxedRequests.Source?:error("Continuous RETURN requires speech tail")
    val record=resolveRun(parentWire.run)?:error("Unknown continuous run")
    val parent=found("source",registry.resolveSource(record,parentWire))?:error("Unknown continuous source")
    val d=request.returnDescriptor(raw["descriptor"],record.queue.authority.sourceDescriptor(parent))
    val clips=port.validateVisual(files(raw["files"]),0)
    return main {
      check(mutable(record)) {"Continuous output owner ended"}
      val tail=registry.resolveTail(record,wire)?:return@main blocked("tail_changed")
      val staged=record.queue.stageReturnResult(d,tail,wire.appendRevision,clips)
      if(staged.status==NCContinuousMuxedQueueState.StageStatus.CAPACITY)return@main blocked("capacity")
      val token=staged.token?:error("Continuous RETURN staging rejected")
      if(!registry.rememberVisualStage(record,token,NCContinuousMuxedRegistry.VisualStage(d,parent,null,wire))) {
        record.queue.fence("return_stage_registry");error("Continuous RETURN stage ownership unconfirmed")}
      result("staged")+mapOf("stageId" to token)
    }
  }
  fun stageVisual(value:Any?):Map<String,Any> {
    val raw=envelope(value,setOf("tail","firstRange","files"));val wire=request.tail(raw["tail"])
    val epoch=wire.source as? NCContinuousMuxedRequests.Visual?:error("Continuous refill requires visual tail")
    val record=resolveRun(epoch.run)?:error("Unknown continuous run")
    val grant=record.queue.authority.nativeVisualGrant(record.run,epoch.id)?:error("Unknown continuous visual epoch")
    val parent=found("source",registry.resolveSource(record,epoch.parent))?:error("Unknown continuous source")
    require(grant.parent===parent)
    val first=request.integer(raw["firstRange"],1,10005).toInt();require(first==wire.nextRange)
    val clips=port.validateVisual(files(raw["files"]),first)
    return main {
      check(mutable(record)) {"Continuous output owner ended"}
      if(registry.resolveTail(record,wire)==null)return@main blocked("tail_changed")
      val staged=record.queue.stageVisualResult(grant,first,wire.appendRevision,clips)
      if(staged.status==NCContinuousMuxedQueueState.StageStatus.CAPACITY)return@main blocked("capacity")
      val token=staged.token?:error("Continuous visual staging rejected")
      if(!registry.rememberVisualStage(record,token,NCContinuousMuxedRegistry.VisualStage(grant.descriptor,parent,grant,wire))) {
        record.queue.fence("visual_stage_registry");error("Continuous visual stage ownership unconfirmed")}
      result("staged")+mapOf("stageId" to token)
    }
  }
  fun appendReturn(value:Any?):Map<String,Any> {
    val raw=envelope(value,setOf("stageId","tail"));val wire=request.tail(raw["tail"])
    val record=resolveRun(wire.source.run)?:error("Unknown continuous run")
    val token=request.text(raw["stageId"]);val q=record.queue
    var grant:NCContinuousMuxedAuthority.VisualGrant?=null;var changed=false
    val ack=await<NCContinuousMuxedQueueState.Ack>(deadline()) {done->
      check(mutable(record)) {"Continuous output owner ended"}
      val stage=found("visual_stage",registry.resolveVisualStage(record,token))?:error("Unknown continuous RETURN stage")
      val tail=registry.resolveTail(record,wire)
      if(tail==null ||stage.tail!=wire){changed=true;return@await false}
      grant=stage.grant?:q.authority.admitFinalReturn(record.run,stage.parent,stage.descriptor,tail,wire.appendRevision) {
        reason->observed("return_admission.$reason",false)
      }
        ?:error("Continuous RETURN admission rejected")
      q.appendReturn(token,grant!!,wire.appendRevision,done)
    }
    if(changed)return blocked("tail_changed")
    if(ack?.outcome!=NCContinuousMuxedQueueState.Outcome.COMMITTED) {
      q.fence("return_append_unconfirmed");error("Continuous RETURN append unconfirmed")}
    check(registry.forgetVisualStage(record,token))
    return result("admitted")+mapOf("visual" to registry.wireVisual(grant!!))
  }
  fun read(value:Any?):Map<String,Any?> {
    val raw=envelope(value,setOf("run","afterCursor"));val record=record(raw["run"])
    return record.queue.authority.readJournal(record.run,request.integer(raw["afterCursor"],0,256))
      ?:error("Invalid continuous journal cursor")
  }
  fun acknowledge(value:Any?):Boolean {
    val raw=envelope(value,setOf("run","throughCursor"));val record=record(raw["run"])
    return record.queue.authority.acknowledgeJournal(record.run,request.integer(raw["throughCursor"],0,256))
  }
  fun seal(value:Any?):Map<String,Any> {
    val raw=envelope(value,setOf("tail"));val wire=request.tail(raw["tail"])
    val record=resolveRun(wire.source.run)?:error("Unknown continuous run")
    var tailChanged=false
    var scheduled=false
    val ack=await<NCContinuousMuxedQueueState.Ack>(deadline()){done->
      check(mutable(record))
      val tail=registry.resolveTail(record,wire)
      if(tail==null){tailChanged=true;false} else record.queue.seal(tail,wire.appendRevision,done).also {scheduled=it}
    }
    if(tailChanged)return result("tail_changed")
    // A rejected compare before scheduling is not an ambiguous native refresh.
    // Preserve the run so a caller can re-read its exact acknowledged tail.
    if(!scheduled && ack==null)return result("tail_changed")
    if(ack?.outcome!=NCContinuousMuxedQueueState.Outcome.COMMITTED) {
      record.queue.fence("seal_unconfirmed");error("Continuous seal unconfirmed")
    }
    return result("sealed")+mapOf("tail" to (registry.wireTail(record)?:error("Missing sealed tail")))
  }
  fun retireSource(value:Any?):Map<String,Any> {
    val raw=envelope(value,setOf("source"));val(record,grant)=source(raw["source"]);val q=record.queue
    if(q.authority.sourceState(grant)?.readersClosed==true)return result("closed")
    val cutoff=q.sourceRetirementCutoff(grant)?:return result("pending")
    if(!mutable(record))return result("pending")
    val end=deadline()
    val ack=await<NCContinuousMuxedQueueState.Ack>(end){done->
      if(!mutable(record))false else q.prune(cutoff,q.snapshot().mutationRevision,done)}
    if(ack?.outcome!=NCContinuousMuxedQueueState.Outcome.COMMITTED || !q.awaitPrunedReaders(remaining(end)))return result("pending")
    return result(if(q.authority.sourceState(grant)?.readersClosed==true)"closed" else "pending")
  }
  fun pruneVisual(value:Any?):Map<String,Any> {
    val raw=envelope(value,setOf("visual","beforeIndex"));val wire=request.visual(raw["visual"])
    val record=resolveRun(wire.run)?:error("Unknown continuous run")
    val parent=found("return_parent",registry.resolveSource(record,wire.parent))?:error("Unknown continuous RETURN parent")
    val q=record.queue;val grant=q.authority.nativeVisualGrant(record.run,wire.id)
      ?.takeIf {it.parent===parent}?:error("Unknown continuous visual epoch")
    val before=request.integer(raw["beforeIndex"],0,10006).toInt()
    val cutoff=q.visualRetirementCutoff(grant,before)?:error("Continuous visual prune index changed")
    if(!mutable(record))return result("pending")
    val end=deadline()
    val ack=await<NCContinuousMuxedQueueState.Ack>(end){done->
      if(!mutable(record))false else q.prune(cutoff,q.snapshot().mutationRevision,done)}
    if(ack?.outcome!=NCContinuousMuxedQueueState.Outcome.COMMITTED ||!q.awaitPrunedReaders(remaining(end)))return result("pending")
    val through=q.visualReleasedThrough(grant)?:error("Continuous visual closure changed")
    return result("pruned")+mapOf("visual" to registry.wireVisual(grant),"releasedThrough" to through)
  }
  private fun closeQueue(q:NCContinuousMuxedQueue,permanent:Boolean=false,retainOrderedSettlement:Boolean=false):Boolean {
    if(q in settled || q in abandoned)return true
    val end=deadline()
    if(q !in detached) {
      val ack=await<Boolean>(end){done->
        val snapshot=q.snapshot()
        val callback:(Boolean)->Unit={if(it)detached+=q;done(it)}
        when(snapshot.state) {
          NCContinuousMuxedQueueState.State.DRAINED->q.retireRun(snapshot.mutationRevision,callback)
          NCContinuousMuxedQueueState.State.FAILED->q.detachFailedRun(callback)
          else->false
        }}
      if(!observed("cleanup.detach_confirmed",ack==true))return false
    }
    if(!observed("cleanup.readers_closed",q.awaitDetachedReaders(remaining(end))))return false
    if(permanent && q !in published) {
      val readers=q.detachedReaderWitness()?:return false
      if(await<Boolean>(end){done->port.closeUnenrolled(q,readers){if(it)abandoned+=q;done(it)}}==true)return true
    }
    if(!observed("cleanup.retirement_witness",q.retirementWitness()!=null))return false
    while(remaining(end)>0) {
      if(retainOrderedSettlement) {
        if(observed("cleanup.ordered_output_settled",await<Boolean>(end){done->
          port.settleOrdered(q){if(it)settled+=q;done(it)}}==true))return true
      } else if(q.hasVisualMembership()) {
        val witness=await<MixedSettlement>(end){done->port.settleMixed(q,done)}?.witness
        val certificate=q.certifyMixedRetirement(witness)
        if(certificate!=null && await<Boolean>(end){done->port.releaseMixed(q,certificate){
          if(it)settled+=q;done(it)}}==true)return true
      } else if(observed("cleanup.output_settled",await<Boolean>(end){done->port.settle(q){if(it)settled+=q;done(it)}}==true))return true
      try {CountDownLatch(1).await(minOf(25L,remaining(end)),TimeUnit.MILLISECONDS)}
      catch(_:InterruptedException){Thread.currentThread().interrupt();return false}
    }
    return q in settled
  }
  fun retireRun(value:Any?):Map<String,Any> {
    val raw=envelope(value,setOf("run"));val entry=record(raw["run"])
    if(!closeQueue(entry.queue))return result("pending")
    val snapshot=entry.queue.authority.runSnapshot(entry.run)?:error("Continuous retirement snapshot unavailable")
    if(entry.queue.hasVisualMembership())check(snapshot["retirement"]!=null) {"Mixed retirement certificate unavailable"}
    return result("closed")+mapOf("snapshot" to snapshot)
  }
  fun invalidate(value:Any?):Boolean {
    val raw=envelope(value,setOf("run","reason"));val record=record(raw["run"]);val reason=request.text(raw["reason"])
    require(reason in setOf("stop","skip","replacement","expiry","recovery","failure"))
    record.queue.fence(reason);return true
  }
  fun drop(value:Any?):Boolean {
    val raw=envelope(value,setOf("run","stageId"));val record=record(raw["run"]);val token=request.text(raw["stageId"])
    val visual=registry.resolveVisualStage(record,token)!=null
    if(!visual &&registry.resolveStage(record,token)==null)return false
    return main {
      val joined=record.queue.retirementWitness()!=null && record.queue.snapshot().state==NCContinuousMuxedQueueState.State.RETIRED
      (joined || record.queue.dropStage(token)) &&
        if(visual)registry.forgetVisualStage(record,token) else registry.forgetStage(record,token)
    }
  }
  fun closeOwned():Boolean {
    closed=true
    orderedEvidence("owner_close_requested"){mapOf("registered" to orderedRecords.values.take(4).map{diagnosticRun(it.run.id,it.run.revision)})}
    val queues=owned.toList();queues.filter {it !in settled}.forEach {it.fence("stop")}
    orderedRecords.values.forEach{it.continuation?.invalidate()}
    val result=queues.map {closeQueue(it,true)}.all {it} && synchronized(this){!opening}
    orderedEvidence("owner_close_completed"){mapOf("settled" to result)}
    return result
  }
}
