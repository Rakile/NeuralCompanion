// NeuralCompanion maintained extension to expo-audio; MIT licensed.
package expo.modules.audio

/** Only explicitly enrolled manual input participates. Live capture is separate. */
class NCManualDeparturePolicy {
  enum class Reason(val wire: String) { UNKNOWN("unknown"), LOCKED("locked"), APP_SWITCH("app_switch") }
  data class Snapshot(val recordingId: String, val recorderId: String, val revision: Long,
    val reason: Reason, val departed: Boolean=false, val stopped: Boolean=false,
    val uri: String?=null, val error: String?=null) {
    fun payload(): Map<String,Any?> = mapOf("recordingId" to recordingId, "revision" to revision,
      "reason" to reason.wire, "departed" to departed, "stopped" to stopped, "uri" to uri, "error" to error)
  }
  private var current: Snapshot?=null
  private var revision=0L
  private var claimed=false

  @Synchronized fun begin(recordingId: String, recorderId: String) {
    require(recordingId.isNotBlank() && recorderId.isNotBlank())
    check(current==null) { "manual_recording_owner_active" }
    current=Snapshot(recordingId,recorderId,++revision,Reason.UNKNOWN);claimed=false
  }
  @Synchronized fun snapshot(recordingId: String): Snapshot? = current?.takeIf { it.recordingId==recordingId }
  @Synchronized fun current(): Snapshot? = current
  @Synchronized fun release(recordingId: String) { if(current?.recordingId==recordingId){current=null;claimed=false} }
  @Synchronized fun completed(recordingId:String,uri:String?) {
    val owner=snapshot(recordingId) ?: return
    if(!owner.stopped)current=owner.copy(revision=++revision,stopped=true,uri=uri)
  }

  @Synchronized fun depart(recordingId: String, recording: Boolean, reason: Reason, stop:()->String?): Snapshot? {
    val owner=snapshot(recordingId) ?: return null
    if(owner.departed)return classify(recordingId,reason)
    // Latch before invoking hardware so duplicate/reentrant lifecycle events cannot stop twice.
    current=owner.copy(revision=++revision,reason=reason,departed=true)
    if(!recording||owner.stopped)return current
    val stopped=try { current!!.copy(stopped=true,uri=stop()) }
      catch(_:Exception){current!!.copy(error="manual_stop_failed")}
    current=stopped
    return stopped
  }
  @Synchronized fun classify(recordingId: String, reason: Reason): Snapshot? {
    val owner=snapshot(recordingId) ?: return null
    if(!owner.departed || owner.reason==Reason.LOCKED || owner.reason==reason)return owner
    // Unknown duplicate pause must not downgrade a confirmed stop observation.
    if(reason==Reason.UNKNOWN)return owner
    return owner.copy(revision=++revision,reason=reason).also {current=it}
  }
  @Synchronized fun claimAutoSend(recordingId:String, expectedRevision:Long, locked:Boolean?, interactive:Boolean?):Boolean {
    val owner=snapshot(recordingId) ?: return false
    if(locked==true || interactive==false){classify(recordingId,Reason.LOCKED);return false}
    if(claimed || owner.revision!=expectedRevision || owner.reason!=Reason.APP_SWITCH || !owner.stopped
      || owner.uri.isNullOrBlank() || owner.error!=null || locked!=false || interactive!=true)return false
    claimed=true
    return true
  }
}
