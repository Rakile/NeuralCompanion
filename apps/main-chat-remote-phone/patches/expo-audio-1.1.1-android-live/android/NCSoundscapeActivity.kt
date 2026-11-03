package expo.modules.audio

import java.util.concurrent.CompletableFuture

/** Cross-module adapter to the existing LiveCaptureEngine; never a second service. */
object NCSoundscapeActivity {
  interface Owner {
    fun acquire(scope: NCSoundscapeScope): CompletableFuture<Boolean>
    fun release(scope: NCSoundscapeScope)
  }
  @Volatile private var owner: Owner?=null
  @Volatile var onRevoked: ((NCSoundscapeScope) -> Unit)?=null
  @Volatile var onPause: ((String) -> Unit)?=null
  fun install(value: Owner) { owner=value }
  fun remove(value: Owner) { if(owner===value) owner=null }
  fun available() = owner!=null
  fun acquire(scope: NCSoundscapeScope): CompletableFuture<Boolean> =
    owner?.acquire(scope) ?: CompletableFuture.completedFuture(false)
  fun release(scope: NCSoundscapeScope) { owner?.release(scope) }
  fun revoked(scope: NCSoundscapeScope) { onRevoked?.invoke(scope) }
}
