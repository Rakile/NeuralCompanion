package expo.modules.audio

/** Match the SurfaceTexture timestamp to the exact Media3 decoder submission.
 * currentPosition and requested seeks are deliberately not inputs. */
internal class NCBufferedVideoTimeline(private val start:Int,private val frames:Int) {
  companion object {
    fun presentable(tick:Int,samples:Int,playing:Boolean):Boolean {
      if(!playing || tick<0 || samples<0)return false
      val heard=samples/2000 // 48 kHz / 24 source frames per second.
      // Match the existing segment player's 120-ms synchronization tolerance.
      // A stricter one-frame gate drops every picture from a legitimately
      // running file player until its next seek/hold, even with all bytes local.
      return tick.toLong()*2000<=samples.toLong()+5760 && tick>=heard-3
    }
  }
  private val pending=linkedMapOf<Long,Int>()
  init { require(start in 0..14399 && frames in 1..1440 && start+frames<=14400) }
  @Synchronized fun submitted(ptsUs:Long,releaseNs:Long) {
    if(ptsUs<0 || releaseNs<=0 || ptsUs>=frames*1_000_000L/24)return
    val tick=(ptsUs*24+24)/1_000_000 // Media3 truncates fractional microseconds (frame 1 = 41666us).
    if(tick !in 0 until frames.toLong())return
    pending[releaseNs]=start+tick.toInt()
    while(pending.size>64)pending.remove(pending.keys.first())
  }
  @Synchronized fun observed(timestamp:Long):Int?=pending.remove(timestamp)
  @Synchronized fun clear(){pending.clear()}
}
