package expo.modules.audio

internal class NCMuxedTrialStaging<T> {
  private data class Pending<T>(val token:String,val owner:String,val revision:Long,val value:T)
  private var pending:Pending<T>?=null
  fun stage(owner:String,revision:Long,hasSource:Boolean,value:T):String? {
    if(owner.isEmpty()||revision<0||revision==Long.MAX_VALUE)return null
    val token=java.util.UUID.randomUUID().toString()
    pending=Pending(token,owner,revision+if(hasSource)1 else 0,value);return token
  }
  fun take(token:String,owner:String,revision:Long):T? {
    val source=pending?:return null
    if(source.token!=token||source.owner!=owner||source.revision!=revision)return null
    pending=null;return source.value
  }
  fun drop(token:String){if(pending?.token==token)pending=null}
  fun clear(){pending=null}
}

/** Lifetime fence for one development player, not a new output/authority.
 * The ordinary player keeps its original binding. Only an explicitly enabled
 * fresh trial may retire a source and allocate a new immutable guard binding.
 * Every actual play still goes through NCPlaybackGuard's eligibility checks.
 */
internal class NCMuxedTrialSourceOwner(private val guard:NCPlaybackGuard,
  private val actions:NCPlaybackActions,initial:NCPlaybackBinding) {
  /** Exact native retired source. The app-thread owner issues it after reset;
   * only its bounded off-main reader join can certify closure. Source counters
   * and successful reset returns identify a transaction, never prove closure.
   */
  class Retirement private constructor(private val owner:NCMuxedTrialSourceOwner,
    internal val source:Any,private val binding:NCPlaybackBinding,private val revision:Long,
    private val fences:List<NCMuxedTrialReaderFence>) {
    @Volatile private var joined=false
    private fun current()=owner.retirement===this && !owner.closed && owner.enabled
      && owner.actions.ncIsAliveSnapshot && owner.binding===binding && owner.revision==revision
    internal fun matches(expected:NCMuxedTrialSourceOwner)=owner===expected && current() && joined
    fun awaitReaders(timeoutMillis:Long):Boolean {
      if(!current())return false
      val deadline=System.nanoTime()+java.util.concurrent.TimeUnit.MILLISECONDS.toNanos(timeoutMillis.coerceIn(0,5000))
      var closed=true
      for(fence in fences) {
        val remaining=java.util.concurrent.TimeUnit.NANOSECONDS.toMillis((deadline-System.nanoTime()).coerceAtLeast(0))
        if(!fence.awaitClosed(remaining))closed=false
      }
      if(!closed || !current())return false
      joined=true;return current()
    }
    companion object {internal fun create(owner:NCMuxedTrialSourceOwner,source:Any,
      binding:NCPlaybackBinding,revision:Long,fences:List<NCMuxedTrialReaderFence>)=
      Retirement(owner,source,binding,revision,fences.toList())}
  }
  @Volatile private var retirement:Retirement?=null
  var binding=initial
    private set
  var revision=0L
    private set
  var enabled=false
    private set
  private var closed=false
  fun enable(debug:Boolean):Boolean {
    if(!debug||closed||!actions.ncIsAliveSnapshot)return false
    if(enabled)return true
    if(binding.attempted||actions.ncIsPlayingSnapshot)return false
    enabled=true;return true
  }
  fun allowsPrepare(observed:Long)=enabled&&!closed&&observed==revision
    &&actions.ncIsAliveSnapshot&&!actions.ncIsPlayingSnapshot&&!binding.attempted
  fun retire(reset:()->Unit):Boolean {
    if(!enabled||closed||!actions.ncIsAliveSnapshot)return false
    retirement=null
    revision++ // Fence validators before touching a decoder or a binding.
    binding.remove()
    try {reset()} catch(error:RuntimeException){closed=true;throw error}
    binding=guard.newBinding(actions)
    return true
  }
  fun retireWithReaders(source:Any,fences:List<NCMuxedTrialReaderFence>,reset:()->Unit):Retirement? {
    if(fences.isEmpty() || fences.size>64 || fences.toSet().size!=fences.size || !retire(reset))return null
    return Retirement.create(this,source,binding,revision,fences).also {retirement=it}
  }
  fun close(reset:()->Unit) {
    if(closed)return
    retirement=null;closed=true;revision++;binding.remove();reset()
  }
}

/** Metadata fence around Media3's asynchronous removal callback. This grants
 * no playback or file authority; the owner retains files until confirmation.
 */
internal class NCMuxedTrialIdleWindow(first:Int,size:Int) {
  var first=first
    private set
  var size=size
    private set
  class Prune internal constructor(val cursor:Int,val remove:Int)
  class Seal internal constructor(val offset:Int,val frames:Int) {
    val endUs get()=(frames*1000000L+23)/24
  }
  private var pending:Prune?=null
  private var closed=false
  private var sealed=false
  init {require(size in 1..6 && first>=0 && first+size-1<=10005)}
  fun append(index:Int,count:Int):Boolean {
    if(closed||sealed||pending!=null||index!=first+size||count !in 1..6||size+count>6||index+count-1>10005)return false
    size+=count;return true
  }
  fun beginPrune(cursor:Int,playing:Int):Prune? {
    if(closed||sealed||pending!=null||playing !in first until first+size||cursor !in first..playing)return null
    return Prune(cursor,cursor-first).also {pending=it}
  }
  fun completePrune(token:Prune):Boolean {
    if(closed||pending!==token)return false
    first=token.cursor;size-=token.remove;pending=null;return true
  }
  fun seal(target:Int,playing:Int,frames:Int,following:Int):Seal? {
    val offset=target-first
    if(closed||sealed||pending!=null||playing !in first until first+size||target<playing+2
      ||offset !in 0 until size||frames !in 1..12||following !in 0..54
      ||offset+1+following>60||target+following>10005)return null
    sealed=true;return Seal(offset,frames)
  }
  fun close(){closed=true;pending=null}
}

internal object NCMuxedTrialItems {
  fun index(item:String,prefix:String,first:Int,count:Int):Int? {
    require(prefix.matches(Regex("[a-f0-9]{32}"))&&count in 1..60&&first>=0&&first+count-1<=10005)
    if(!item.startsWith("$prefix-"))return null
    val ordinal=item.removePrefix("$prefix-")
    if(!ordinal.matches(Regex("0|[1-9][0-9]{0,4}")))return null
    return ordinal.toIntOrNull()?.takeIf {it in first until first+count}
  }
}
