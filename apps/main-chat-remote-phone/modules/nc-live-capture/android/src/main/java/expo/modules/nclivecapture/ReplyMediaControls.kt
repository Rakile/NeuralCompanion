package expo.modules.nclivecapture

import android.content.Context
import android.media.MediaMetadata
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.Handler
import android.os.Looper
import android.os.Bundle
import android.app.Notification
import android.app.PendingIntent
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.net.Uri
import android.os.Build
import android.view.KeyEvent
import java.io.File
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/** Commands only. The existing reply owner remains responsible for audio. */
internal class ReplyMediaControls(private val context: Context, private val emit: (String, String) -> Unit) {
  private val main = Handler(Looper.getMainLooper())
  private var session: MediaSession? = null
  private var scope: String? = null
  private var nextToggles = false
  private var destroyed = false
  private var playing = false
  private var info: Map<String, Any?>? = null
  private var artwork: Bitmap? = null
  private var artworkPath: String? = null
  private var artworkRevision = 0L
  private val images = Executors.newSingleThreadExecutor()

  companion object {
    private var current: ReplyMediaControls? = null
    fun notificationCommand(scope: String?, command: String?) {
      val owner = current ?: return
      owner.main.post { if (scope != null && scope == owner.scope && command != null) owner.command(command) }
    }
  }

  private fun allowed(name: String): Boolean = when (name) {
    "regenerate" -> info?.get("canRegenerate") == true
    "force_continue" -> info?.get("canForce") == true
    "auto_toggle" -> info?.get("canAuto") == true
    "next" -> nextToggles
    "play", "pause" -> info?.get("buffering") != true
    "stop" -> true
    else -> false
  }
  private fun command(name: String) {
    val owner = scope ?: return
    if (!destroyed && current === this && session != null && allowed(name)) emit(owner, name)
  }

  fun configure(value: String?, playing: Boolean, allowNext: Boolean, details: Map<String, Any?>? = null) { main.post {
    if (destroyed) return@post
    val scopeChanged = value != scope
    if (scopeChanged) {
      // Releasing the session linked to the service notification can demote
      // that service on Android. Reply handoffs change command ownership, not
      // the Android media-session lifetime. Null still ends that lifetime.
      if (value == null) { session?.release(); session = null }
      scope = value; artworkRevision++; artwork = null; artworkPath = null
    }
    this.playing = playing
    info = details
    nextToggles = allowNext
    if (value == null) {
      if (current === this) { current = null; LiveAudioService.setMediaNotification(null) }
      return@post
    }
    current = this
    if (session == null || scopeChanged) {
      val owner = value
      session = (session ?: MediaSession(context, "NC reply")).also { media ->
        media.setCallback(object : MediaSession.Callback() {
          private fun command(name: String) { if (scope == owner && session === media) this@ReplyMediaControls.command(name) }
          override fun onPlay() = command("play")
          override fun onPause() = command("pause")
          override fun onStop() = command("stop")
          override fun onSkipToNext() { if (nextToggles) command("next") }
          override fun onCustomAction(action: String, extras: Bundle?) = command(action)
          override fun onMediaButtonEvent(intent: Intent): Boolean {
            @Suppress("DEPRECATION") val key = intent.getParcelableExtra<KeyEvent>(Intent.EXTRA_KEY_EVENT)
            if (nextToggles && key?.keyCode == KeyEvent.KEYCODE_MEDIA_NEXT) {
              if (key.action == KeyEvent.ACTION_DOWN && key.repeatCount == 0) command("next")
              return true
            }
            return super.onMediaButtonEvent(intent)
          }
        }, main)
        media.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS or MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS)
        context.packageManager.getLaunchIntentForPackage(context.packageName)?.let { launch ->
          media.setSessionActivity(PendingIntent.getActivity(context, 30, launch, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        }
        media.isActive = true
      }
    }
    publish()
    loadArtwork(details?.get("artwork") as? String ?: "")
  } }

  private data class Button(val command: String, val label: String, val icon: Int)
  private fun buttons() = listOf(
    Button("regenerate", "Regenerate", android.R.drawable.ic_menu_rotate),
    Button(if (playing) "pause" else "play", if (playing) "Pause" else "Play", if (playing) android.R.drawable.ic_media_pause else android.R.drawable.ic_media_play),
    Button("force_continue", "Force continuation", android.R.drawable.ic_media_next),
    Button("auto_toggle", if (info?.get("autoOn") == true) "Auto: On" else "Auto: Off", android.R.drawable.ic_menu_revert),
    Button("stop", "Stop", android.R.drawable.ic_menu_close_clear_cancel)
  ).filter { allowed(it.command) }

  private fun publish() {
    val media = session ?: return
    val owner = scope ?: return
    val metadata = MediaMetadata.Builder()
      .putString(MediaMetadata.METADATA_KEY_TITLE, (info?.get("title") as? String)?.take(100) ?: "NeuralCompanion")
      .putString(MediaMetadata.METADATA_KEY_ARTIST, (info?.get("subtitle") as? String)?.take(150) ?: "Conversation audio")
    artwork?.let { metadata.putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, it) }
    media.setMetadata(metadata.build())
    var actions = PlaybackState.ACTION_STOP
    if (info?.get("buffering") != true) actions = actions or PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_PLAY_PAUSE
    if (info == null && nextToggles) actions = actions or PlaybackState.ACTION_SKIP_TO_NEXT
    val state = PlaybackState.Builder().setActions(actions)
      .setState(if (info?.get("buffering") == true) PlaybackState.STATE_BUFFERING else if (playing) PlaybackState.STATE_PLAYING else PlaybackState.STATE_PAUSED,
        PlaybackState.PLAYBACK_POSITION_UNKNOWN, if (playing) 1f else 0f)
    if (info != null) buttons().filter { it.command !in setOf("play", "pause") }.forEach {
      state.addCustomAction(it.command, it.label, it.icon)
    }
    media.setPlaybackState(state.build())
    if (info == null) { LiveAudioService.setMediaNotification(null); return }
    @Suppress("DEPRECATION")
    val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(context, "nc_live_capture") else Notification.Builder(context)
    builder.setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle(metadata.build().getString(MediaMetadata.METADATA_KEY_TITLE))
      .setContentText(metadata.build().getString(MediaMetadata.METADATA_KEY_ARTIST))
      .setOnlyAlertOnce(true).setOngoing(true).setShowWhen(false)
      .setVisibility(Notification.VISIBILITY_PRIVATE)
    artwork?.let { builder.setLargeIcon(it) }
    context.packageManager.getLaunchIntentForPackage(context.packageName)?.let { launch ->
      builder.setContentIntent(PendingIntent.getActivity(context, 30, launch, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
    }
    val items = buttons()
    items.forEachIndexed { index, item ->
      val intent = Intent(context, ReplyMediaActionReceiver::class.java)
        .setData(Uri.parse("nc-reply-control://${Uri.encode(owner)}/${item.command}"))
        .putExtra("scope", owner).putExtra("command", item.command)
      val pending = PendingIntent.getBroadcast(context, index, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
      @Suppress("DEPRECATION")
      builder.addAction(item.icon, item.label, pending)
    }
    builder.setStyle(Notification.MediaStyle().setMediaSession(media.sessionToken)
      .setShowActionsInCompactView(*items.indices.filter { items[it].command in setOf("regenerate", "play", "pause", "force_continue") }.take(3).toIntArray()))
    LiveAudioService.setMediaNotification(builder.build())
  }

  private fun loadArtwork(path: String) {
    if (artworkPath == path) return
    artworkPath = path
    artwork = null
    val revision = ++artworkRevision
    images.execute {
      val bitmap = try {
        val uri = Uri.parse(path)
        val file = if (uri.scheme == "file") File(uri.path ?: "").canonicalFile else null
        val roots = listOf(context.cacheDir, context.filesDir).map { it.canonicalPath + File.separator }
        if (file != null && roots.any { file.path.startsWith(it) } && file.length() in 1..8_000_000) {
          val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
          BitmapFactory.decodeFile(file.path, bounds)
          val options = BitmapFactory.Options().apply {
            inSampleSize = 1
            while (bounds.outWidth / inSampleSize > 512 || bounds.outHeight / inSampleSize > 512) inSampleSize *= 2
          }
          BitmapFactory.decodeFile(file.path, options)
        } else if (uri.scheme in setOf("http", "https")) {
          // URL already came through the app's authenticated media resolver.
          // LAN artwork has no peer cache file. Never log credentials, follow
          // redirects, or let an image request hold up audio/the main thread.
          val connection = URL(path).openConnection() as HttpURLConnection
          try {
            connection.connectTimeout = 4000; connection.readTimeout = 4000
            connection.instanceFollowRedirects = false
            check(connection.responseCode == 200 && connection.contentLengthLong <= 8_000_000)
            val bytes = connection.inputStream.use { input ->
              val output = ByteArrayOutputStream(); val buffer = ByteArray(8192)
              while (true) {
                val count = input.read(buffer); if (count < 0) break
                check(output.size() + count <= 8_000_000); output.write(buffer, 0, count)
              }
              output.toByteArray()
            }
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
            val options = BitmapFactory.Options().apply {
              inSampleSize = 1
              while (bounds.outWidth / inSampleSize > 512 || bounds.outHeight / inSampleSize > 512) inSampleSize *= 2
            }
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
          } finally { connection.disconnect() }
        } else {
          val icon = context.packageManager.getApplicationIcon(context.packageName)
          Bitmap.createBitmap(256, 256, Bitmap.Config.ARGB_8888).also {
            icon.setBounds(0, 0, 256, 256); icon.draw(Canvas(it))
          }
        }
      } catch (_: Exception) { null }
      main.post { if (!destroyed && revision == artworkRevision && scope != null) { artwork = bitmap; publish() } }
    }
  }
  fun destroy() { main.post {
    destroyed = true; scope = null; artworkRevision++; session?.release(); session = null; images.shutdownNow()
    if (current === this) { current = null; LiveAudioService.setMediaNotification(null) }
  } }
}
