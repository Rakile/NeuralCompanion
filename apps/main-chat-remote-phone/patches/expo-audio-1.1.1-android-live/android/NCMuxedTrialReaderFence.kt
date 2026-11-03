package expo.modules.audio

import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import java.io.IOException
import java.util.concurrent.TimeUnit

/** One native source epoch's file readers. Retirement blocks new opens before
 * Media3 is stopped; completion requires every delegated close to succeed.
 * Waiting belongs on the module's background queue, never the player looper. */
internal class NCMuxedTrialReaderFence {
  private val monitor=Object()
  private var retired=false
  private var readers=0
  private var closeFailed=false

  /** Identity belongs to one Media3 child, not its file URI. A sealed child
   * may be replaced by a distinct child reading the same retained file. */
  inner class Child internal constructor() {
    private var retired=false
    private var readers=0
    private var closeFailed=false
    fun retire()=synchronized(monitor){retired=true;monitor.notifyAll()}
    fun awaitClosed(timeoutMillis:Long=MAX_WAIT_MILLIS):Boolean=synchronized(monitor){
      if(!retired||closeFailed)return@synchronized false
      val deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(timeoutMillis.coerceIn(0,MAX_WAIT_MILLIS))
      while(readers>0&&!closeFailed){
        val remaining=deadline-System.nanoTime()
        if(remaining<=0)return@synchronized false
        try {TimeUnit.NANOSECONDS.timedWait(monitor,remaining)}catch(_:InterruptedException){
          Thread.currentThread().interrupt();return@synchronized false
        }
      }
      !closeFailed&&readers==0
    }
    fun wrap(factory:DataSource.Factory)=this@NCMuxedTrialReaderFence.wrap(factory,this)
    internal fun acquire(){
      if(retired||closeFailed)throw IOException("Muxed child reader is retired")
      readers++
    }
    internal fun finish(closed:Boolean){readers--;if(!closed)closeFailed=true}
  }
  fun child()=Child()

  private fun acquire(child:Child?):Pin=synchronized(monitor){
    if(retired||closeFailed)throw IOException("Muxed source reader is retired")
    child?.acquire();readers++;Pin(child)
  }
  private inner class Pin(private val child:Child?) {
    private var released=false
    fun finish(closed:Boolean)=synchronized(monitor){
      if(!released){
        released=true;readers--;child?.finish(closed)
        if(!closed)closeFailed=true
        monitor.notifyAll()
      }
    }
  }
  fun retire()=synchronized(monitor){retired=true;monitor.notifyAll()}

  fun awaitClosed(timeoutMillis:Long=MAX_WAIT_MILLIS):Boolean=synchronized(monitor){
    if(!retired||closeFailed)return@synchronized false
    val deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(timeoutMillis.coerceIn(0,MAX_WAIT_MILLIS))
    while(readers>0&&!closeFailed){
      val remaining=deadline-System.nanoTime()
      if(remaining<=0)return@synchronized false
      try {TimeUnit.NANOSECONDS.timedWait(monitor,remaining)}catch(_:InterruptedException){
        Thread.currentThread().interrupt();return@synchronized false
      }
    }
    !closeFailed&&readers==0
  }

  fun wrap(factory:DataSource.Factory)=wrap(factory,null)
  private fun wrap(factory:DataSource.Factory,child:Child?):DataSource.Factory=DataSource.Factory {
    val delegate=factory.createDataSource()
    object:DataSource by delegate {
      private var pin:Pin?=null
      @Synchronized override fun open(dataSpec:DataSpec):Long {
        if(pin!=null)throw IOException("Muxed reader is already open")
        val held=acquire(child);pin=held
        try {return delegate.open(dataSpec)}catch(error:Throwable){
          var closed=false
          try {delegate.close();closed=true}catch(cleanup:Throwable){if(cleanup!==error)error.addSuppressed(cleanup)}
          finally {held.finish(closed);pin=null}
          throw error
        }
      }
      @Synchronized override fun close(){
        val held=pin?:return
        var closed=false
        try {delegate.close();closed=true}
        finally {held.finish(closed);pin=null}
      }
    }
  }

  companion object {
    private const val MAX_WAIT_MILLIS=5000L
    fun awaitAll(fences:List<NCMuxedTrialReaderFence>,timeoutMillis:Long=MAX_WAIT_MILLIS):Boolean {
      val deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(timeoutMillis.coerceIn(0,MAX_WAIT_MILLIS))
      return fences.all {it.awaitClosed(TimeUnit.NANOSECONDS.toMillis((deadline-System.nanoTime()).coerceAtLeast(0)))}
    }
    fun awaitChildren(children:List<NCMuxedTrialReaderFence.Child>,timeoutMillis:Long=MAX_WAIT_MILLIS):Boolean {
      val deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(timeoutMillis.coerceIn(0,MAX_WAIT_MILLIS))
      return children.all {it.awaitClosed(TimeUnit.NANOSECONDS.toMillis((deadline-System.nanoTime()).coerceAtLeast(0)))}
    }
  }
}
