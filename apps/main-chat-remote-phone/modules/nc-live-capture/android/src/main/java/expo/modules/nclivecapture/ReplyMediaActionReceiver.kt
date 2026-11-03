package expo.modules.nclivecapture

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Explicit, non-exported PendingIntents only; the session rechecks ownership. */
class ReplyMediaActionReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    ReplyMediaControls.notificationCommand(intent.getStringExtra("scope"), intent.getStringExtra("command"))
  }
}
