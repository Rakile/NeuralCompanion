package expo.modules.nclivecapture

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.SystemClock
import android.os.Looper
import java.util.concurrent.CopyOnWriteArraySet
import com.facebook.react.HeadlessJsTaskService
import com.facebook.react.bridge.Arguments
import com.facebook.react.jstasks.HeadlessJsTaskConfig
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

class LiveAudioService : HeadlessJsTaskService() {
  private val handler = Handler(Looper.getMainLooper())
  private val expiryTasks=mutableMapOf<Long,Runnable>()
  private val replyTasks=mutableSetOf<Long>()
  private var lastClockPulse=0L
  private var lastNotification:Notification?=null
  private var safetyTask: Runnable? = null

  override fun onCreate() {
    super.onCreate()
    synchronized(Companion){activeService=this}
    if (Build.VERSION.SDK_INT >= 26) {
      val manager = getSystemService(NotificationManager::class.java)
      manager.createNotificationChannel(NotificationChannel(CHANNEL, "Live conversation", NotificationManager.IMPORTANCE_LOW))
    }
  }

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    val revision=intent?.getLongExtra(EXTRA_GENERATION,-1)?:-1
    val current=registry.snapshot()
    if(current.isEmpty()) {
      acknowledgeRetiredStart()
      synchronized(Companion) {
        settleForegroundStart(intent)
        if(registry.snapshot().isEmpty() && pendingForegroundStarts.isEmpty()) {
          if(activeService===this)activeService=null
          stopSelf(startId)
        }
      }
      return START_NOT_STICKY
    }
    try {
      val types = current.fold(0) { bits, owner -> bits or when (owner.action) {
        ACTION_CONNECTION -> ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
        ACTION_PLAYBACK, ACTION_REPLY, ACTION_SOUNDSCAPE, ACTION_TAIL, ACTION_STOPPING_OUTPUT -> ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
        ACTION_MEDIA -> ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE or ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
        else -> ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
      } }
      val mic=current.any{it.role==ServiceOwnerRegistry.Role.MICROPHONE}
      val connectionOnly=current.all{it.role==ServiceOwnerRegistry.Role.CONNECTION}
      val text=when(current.firstOrNull{it.role==ServiceOwnerRegistry.Role.MICROPHONE}?.action) {
        ACTION_TAIL->"Finishing reply";ACTION_STOPPING->"Stopping microphone…"
        ACTION_STOPPING_OUTPUT->"Stopping conversation…"
        null->if(connectionOnly)"Desktop connection active" else "Reply playback active";else->"Microphone active"
      }
      publish(types,registry.revision,text,
        if(mic)ServiceMode.LIVE else if(connectionOnly)ServiceMode.CONNECTION_ONLY else ServiceMode.PLAYBACK_ONLY)
      synchronized(Companion){settleForegroundStart(intent)}
      if(intent?.action==ACTION_STOP) {
        // Media Stop leaves connection ownership intact. The connection-only
        // notification explicitly labels this action Disconnect.
        val targets=current.filter{it.role!=ServiceOwnerRegistry.Role.CONNECTION}.ifEmpty{current}
        if(revision==registry.revision)targets.forEach{if(registry.current(it))it.controller.stopConversation()}
        return START_NOT_STICKY
      }
      current.forEach { owner -> if(registry.current(owner)) {
        if(owner.role in setOf(ServiceOwnerRegistry.Role.REPLY,ServiceOwnerRegistry.Role.MICROPHONE,ServiceOwnerRegistry.Role.CONNECTION) && replyTasks.add(owner.generation)) {
          val data=Arguments.createMap().apply { putDouble("generation",owner.generation.toDouble()) }
          startTask(HeadlessJsTaskConfig("NCReplyPlayback",data,0L,true))
        }
        synchronized(confirmed){confirmed+=owner.generation}
        owner.controller.serviceStarted(owner.ticket,owner.generation)
      } }
    } catch (_: Throwable) {
      runCatching { acknowledgeRetiredStart(); synchronized(Companion){settleForegroundStart(intent)} }
      // A failed microphone addition must not tear down a confirmed playback
      // role. Unconfirmed roles alone receive the startup failure.
      val unconfirmed=current.filter{ synchronized(confirmed){it.generation !in confirmed} }
      (if(unconfirmed.isEmpty())current else unconfirmed).forEach(::failRegistration)
      if(registry.snapshot().isEmpty())stopSelf(startId)
      else requestRefresh(this)
      return START_NOT_STICKY
    }
    val liveGenerations=current.map{it.generation}.toSet()
    expiryTasks.keys.filter{it !in liveGenerations}.forEach { expiryTasks.remove(it)?.let(handler::removeCallbacks) }
    current.filter{it.role==ServiceOwnerRegistry.Role.MICROPHONE}.forEach { owner ->
      if(owner.generation !in expiryTasks) {
        val expiry=Runnable {if(registry.current(owner))owner.controller.authorizationExpired()}
        expiryTasks[owner.generation]=expiry;handler.postDelayed(expiry,AUTHORIZATION_MILLIS)
      }
    }
    if(safetyTask==null) {
      safetyTask=object:Runnable {
        override fun run() {
          val owners=registry.snapshot()
          owners.forEach{if(registry.current(it))it.controller.safetyTick()}
          val now=SystemClock.elapsedRealtime()
          if(now-lastClockPulse>=1000) {
            lastClockPulse=now
            owners.filter{registry.current(it)&&synchronized(confirmed){it.generation in confirmed}}.forEach { owner ->
              clockListeners.forEach{listener->runCatching{listener(owner.generation)}}
            }
          }
          if(registry.snapshot().isNotEmpty())handler.postDelayed(this,250)
        }
      }.also {handler.postDelayed(it,250)}
    }
    return START_NOT_STICKY
  }

  override fun onDestroy() {
    expiryTasks.values.forEach(handler::removeCallbacks);expiryTasks.clear()
    safetyTask?.let(handler::removeCallbacks);safetyTask=null
    val affected=synchronized(Companion){
      if(activeService!==this)emptyList() else {
        activeService=null
        pendingForegroundStarts.clear()
        registry.snapshot().filter{registry.remove(it)}.also { owners ->
          synchronized(confirmed){owners.forEach{confirmed-=it.generation}}
        }
      }
    }
    affected.forEach{it.controller.serviceDestroyed()}
    super.onDestroy()
  }

  private fun acknowledgeRetiredStart() {
    val notice=NotificationCompat.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_btn_speak_now)
      .setContentTitle("NC Remote").setContentText("Finishing reply").setOnlyAlertOnce(true).build()
    if(Build.VERSION.SDK_INT>=29)startForeground(NOTIFICATION_ID,notice,ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
    else startForeground(NOTIFICATION_ID,notice)
  }

  private fun publish(types: Int, revision:Long, text: String, mode:ServiceMode) {
    val stop = Intent(this, LiveAudioService::class.java).setAction(ACTION_STOP).putExtra(EXTRA_GENERATION, revision)
    val pending = PendingIntent.getService(this, revision.toInt(), stop, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    val notification: Notification = NotificationCompat.Builder(this, CHANNEL)
      .setSmallIcon(android.R.drawable.ic_btn_speak_now)
      .setContentTitle(when(mode){ServiceMode.CONNECTION_ONLY->"NC desktop connection";ServiceMode.PLAYBACK_ONLY->"NC playback";else->"NC Live conversation"})
      .setContentText(text)
      .setOngoing(true)
      .setOnlyAlertOnce(true)
      .addAction(0, when(mode){ServiceMode.CONNECTION_ONLY->"Disconnect";ServiceMode.PLAYBACK_ONLY->"Stop playback";else->"Stop conversation"}, pending)
      .build()
    lastNotification=notification
    val published=if(mode==ServiceMode.PLAYBACK_ONLY)mediaNotification?:notification else notification
    if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION_ID, published, types)
    else startForeground(NOTIFICATION_ID, published)
  }

  interface Controller {
    fun serviceStarted(ticket:String?, generation:Long) {}
    fun stopConversation()
    fun authorizationExpired()
    fun serviceDestroyed()
    fun serviceStartFailed(ticket: String?, generation: Long)
    fun safetyTick()
  }

  enum class ServiceMode { LIVE, PLAYBACK_ONLY, CONNECTION_ONLY }

  companion object {
    private val clockListeners=CopyOnWriteArraySet<(Long)->Unit>()
    fun addClockListener(listener:(Long)->Unit):()->Unit {
      clockListeners.add(listener);return {clockListeners.remove(listener);Unit}
    }
    private var mediaNotification:Notification?=null
    @Synchronized fun setMediaNotification(notification:Notification?) {
      mediaNotification=notification
      val service=activeService?:return
      val owners=registry.snapshot()
      if(owners.isEmpty()||owners.all{it.role==ServiceOwnerRegistry.Role.CONNECTION}||owners.any{it.role==ServiceOwnerRegistry.Role.MICROPHONE})return
      val published=notification?:service.lastNotification?:return
      service.getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID,published)
    }
    fun isPlaybackServiceActive(generation:Long)=activeService!=null&&registry.snapshot().any {
      it.generation==generation&&synchronized(confirmed){generation in confirmed}
    }
    private const val ACTION_REPLY="expo.modules.nclivecapture.REPLY_PLAYBACK"
    private const val ACTION_CONNECTION="expo.modules.nclivecapture.CONNECTION"
    private const val ACTION_SOUNDSCAPE="expo.modules.nclivecapture.SOUNDSCAPE"
    private val soundscape=SoundscapeServiceReason()
    private var soundscapeController:Controller?=null
    @Synchronized fun acquireSoundscape(context:Context,fallbackOwner:Controller,conversationId:String,
      session:Long,playback:Long,revision:Long,revoked:()->Unit):SoundscapeServiceReason.Lease {
      val lease=soundscape.acquire(conversationId,session,playback,revision,revoked)
      if(soundscapeController==null) {
        val owner=object:Controller {
          private fun end() {
            synchronized(Companion) { if(soundscapeController!==this)return; soundscapeController=null }
            soundscape.revoke();stop(context,this)
          }
          override fun stopConversation()=end()
          override fun authorizationExpired()=end()
          override fun serviceDestroyed()=end()
          override fun serviceStartFailed(ticket:String?,generation:Long)=end()
          override fun safetyTick() {if(!soundscape.active)end()}
        }
        soundscapeController=owner
        try{startAuxiliary(context,owner,null,ACTION_SOUNDSCAPE,ServiceOwnerRegistry.Role.SOUNDSCAPE)}
        catch(error:Throwable){soundscapeController=null;soundscape.revoke();throw error}
      }
      return lease
    }
    @Synchronized fun releaseSoundscape(context:Context,lease:SoundscapeServiceReason.Lease) {
      if(!soundscape.release(lease))return
      val owner=soundscapeController?:return;soundscapeController=null;stop(context,owner)
    }
    fun admitsSoundscape(lease:SoundscapeServiceReason.Lease)=soundscape.matches(lease)
    @Synchronized fun canRetainSoundscape()=activeService!=null&&registry.snapshot().any {
      synchronized(confirmed){it.generation in confirmed}&&it.role!=ServiceOwnerRegistry.Role.CONNECTION&&it.action !in setOf(ACTION_STOPPING,ACTION_STOPPING_OUTPUT)
    }
    fun startOutput(context:Context,owner:Controller,ticket:String)=
      startAuxiliary(context,owner,ticket,ACTION_REPLY,ServiceOwnerRegistry.Role.REPLY)
    fun startConnection(context:Context,owner:Controller,ticket:String)=
      startAuxiliary(context,owner,ticket,ACTION_CONNECTION,ServiceOwnerRegistry.Role.CONNECTION)
    @Synchronized private fun startAuxiliary(context:Context,owner:Controller,ticket:String?,action:String,role:ServiceOwnerRegistry.Role) {
      val registration=registry.register(role,owner,ticket,action)
      val intent=Intent(context,LiveAudioService::class.java).setAction(action).putExtra(EXTRA_GENERATION,registry.revision)
      requestForeground(context,intent,registration)
    }
    private const val CHANNEL = "nc_live_capture"
    private const val NOTIFICATION_ID = 7802
    private const val ACTION_MIC = "expo.modules.nclivecapture.MICROPHONE"
    private const val ACTION_MEDIA = "expo.modules.nclivecapture.MEDIA_PLAYBACK"
    private const val ACTION_PLAYBACK = "expo.modules.nclivecapture.PLAYBACK_ONLY"
    private const val ACTION_STOP = "expo.modules.nclivecapture.STOP"
    private const val ACTION_STOPPING = "expo.modules.nclivecapture.STOPPING"
    private const val ACTION_TAIL = "expo.modules.nclivecapture.REPLY_TAIL"
    private const val ACTION_STOPPING_OUTPUT = "expo.modules.nclivecapture.STOPPING_OUTPUT"
    private const val EXTRA_GENERATION = "ncOwnerGeneration"
    private const val EXTRA_FOREGROUND_START = "ncForegroundStart"
    private var foregroundStartSequence=0L
    private val pendingForegroundStarts=mutableSetOf<Long>()
    // Called under the companion monitor: register/start and remove/stop must
    // not cross on separate bridge/audio threads.
    private fun requestForeground(context:Context,intent:Intent,owner:ServiceOwnerRegistry.Registration<Controller>) {
      val sequence=++foregroundStartSequence
      pendingForegroundStarts+=sequence
      intent.putExtra(EXTRA_FOREGROUND_START,sequence)
      try { ContextCompat.startForegroundService(context,intent) }
      catch(error:Throwable) {pendingForegroundStarts-=sequence;failRegistration(owner);throw error}
    }
    private fun settleForegroundStart(intent:Intent?) {
      val sequence=intent?.getLongExtra(EXTRA_FOREGROUND_START,-1)?:-1
      // Android delivers service starts in order. A refresh/notification command
      // without a sequence cannot acknowledge a queued foreground start.
      pendingForegroundStarts.removeAll{it<=sequence}
    }
    private const val AUTHORIZATION_MILLIS = 15 * 60 * 1000L
    private val registry=ServiceOwnerRegistry<Controller>()
    private var activeService:LiveAudioService?=null
    private val confirmed=mutableSetOf<Long>()
    private fun failRegistration(owner:ServiceOwnerRegistry.Registration<Controller>) {
      if(!registry.remove(owner))return
      synchronized(confirmed){confirmed-=owner.generation}
      owner.controller.serviceStartFailed(owner.ticket,owner.generation)
    }
    private fun requestRefresh(context:Context):Boolean = context.startService(
      Intent(context,LiveAudioService::class.java).putExtra(EXTRA_GENERATION,registry.revision))!=null

    fun start(context: Context, owner: Controller, outputActive: Boolean, ticket: String?) {
      startMode(context,owner,ticket,if(outputActive)ACTION_MEDIA else ACTION_MIC,ServiceMode.LIVE)
    }

    fun startPlayback(context:Context,owner:Controller,ticket:String) =
      startMode(context,owner,ticket,ACTION_PLAYBACK,ServiceMode.PLAYBACK_ONLY)

    @Synchronized private fun startMode(context:Context,owner:Controller,ticket:String?,action:String,mode:ServiceMode) {
      val role=if(mode==ServiceMode.LIVE)ServiceOwnerRegistry.Role.MICROPHONE else ServiceOwnerRegistry.Role.PLAYBACK
      val registration=registry.register(role,owner,ticket,action)
      val intent = Intent(context, LiveAudioService::class.java).setAction(action)
        .putExtra(EXTRA_GENERATION, registry.revision)
      requestForeground(context,intent,registration)
    }

    @Synchronized fun setOutputActive(context: Context, owner: Controller, outputActive: Boolean, ticket: String?, lifetime: CaptureLifetime = CaptureLifetime.CAPTURING): Boolean {
      val current = registry.forController(owner)?.takeIf{it.ticket==ticket} ?: return false
      if (!synchronized(confirmed){current.generation in confirmed} || lifetime == CaptureLifetime.CLOSED) return false
      val action = when {
        current.action == ACTION_STOPPING || current.action == ACTION_STOPPING_OUTPUT -> current.action
        current.role==ServiceOwnerRegistry.Role.PLAYBACK -> ACTION_PLAYBACK
        lifetime == CaptureLifetime.REPLY_TAIL || current.action == ACTION_TAIL -> ACTION_TAIL
        outputActive -> ACTION_MEDIA
        else -> ACTION_MIC
      }
      if(registry.update(current,action)==null)return false
      return try { requestRefresh(context) }
      catch (error: Throwable) { failRegistration(current); throw error }
    }

    @Synchronized fun markStopping(context: Context, owner: Controller, captureActive: Boolean = true): Boolean {
      val current = registry.forController(owner) ?: return false
      if (!synchronized(confirmed){current.generation in confirmed}) return false
      val action = if (captureActive && current.role==ServiceOwnerRegistry.Role.MICROPHONE) ACTION_STOPPING else ACTION_STOPPING_OUTPUT
      if(registry.update(current,action)==null)return false
      return try { requestRefresh(context) } catch (_: Throwable) { false }
    }

    fun stop(context: Context, owner: Controller) {
      synchronized(this) {
        val current=registry.forController(owner) ?: return
        if(!registry.remove(current))return
        synchronized(confirmed){confirmed-=current.generation}
        if(registry.snapshot().isEmpty() && pendingForegroundStarts.isEmpty()){
          activeService=null
          context.stopService(Intent(context, LiveAudioService::class.java))
        }
        else if(registry.snapshot().isNotEmpty())requestRefresh(context)
        // An already-queued start must reach onStartCommand and startForeground,
        // even when its owner was cancelled before service creation.
      }
    }
  }
}
