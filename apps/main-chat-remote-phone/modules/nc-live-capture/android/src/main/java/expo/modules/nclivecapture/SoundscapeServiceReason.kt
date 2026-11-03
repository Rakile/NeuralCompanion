package expo.modules.nclivecapture

/** A keyed activity reason, deliberately independent of the speech ticket and binding set. */
class SoundscapeServiceReason {
  data class Lease(val conversationId: String, val sessionGeneration: Long,
    val playbackGeneration: Long, val revision: Long, val id: Long)
  private var nextId=0L
  private var lease: Lease?=null
  private var watermark: Lease?=null
  private var revoked: (() -> Unit)?=null
  val active: Boolean @Synchronized get() = lease!=null
  @Synchronized fun matches(value: Lease) = lease==value

  @Synchronized fun acquire(conversationId: String, session: Long, playback: Long, revision: Long,
    onRevoked: () -> Unit): Lease {
    require(conversationId.isNotBlank() && session>=0 && playback>=0 && revision>=0)
    val previous=watermark
    if (previous!=null) {
      require(session>=previous.sessionGeneration) { "Stale soundscape session" }
      if(session==previous.sessionGeneration) {
        require(conversationId==previous.conversationId && playback>=previous.playbackGeneration && revision>=previous.revision) { "Stale soundscape scope" }
      }
    }
    val current=lease
    if(current!=null && current.conversationId==conversationId && current.sessionGeneration==session
      && current.playbackGeneration==playback && current.revision==revision) return current
    return Lease(conversationId,session,playback,revision,++nextId).also {
      lease=it; watermark=it; revoked=onRevoked
    }
  }
  @Synchronized fun release(expected: Lease): Boolean {
    if(lease!=expected) return false
    lease=null; revoked=null; return true
  }
  fun revoke() {
    val notify=synchronized(this) { val callback=revoked; lease=null; revoked=null; callback }
    notify?.invoke()
  }
}
