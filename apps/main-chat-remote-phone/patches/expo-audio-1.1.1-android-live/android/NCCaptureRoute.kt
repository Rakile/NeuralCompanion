// NeuralCompanion maintained extension to expo-audio; MIT licensed.
package expo.modules.audio

import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.SystemClock

/** Shared selection/verification machinery, without Live's background policy.
 * Calls which negotiate Android routing must run off the UI/audio-reader thread.
 */
class NCCaptureRoute(
  private val manager: AudioManager,
  private val ticket: String,
  private val bluetoothPermission: () -> Boolean
) {
  @Volatile var token: NCCommunicationRoute.Token? = null
    private set
  private var previousMode: Int? = null
  private var selected = false
  private var released = false
  private var verified = false
  private var outputVerified = false
  private var parkedEpoch = 0L
  private var retentionEligible: (() -> Boolean)? = null
  private val evidence = NCMicrophoneRouteEvidence("shared")
  private data class RetentionStatus(val condition: String? = null, val actual: Any? = null,
    val exceptionType: String? = null) { val valid get() = condition == null }
  private var lastRetentionDecision: Pair<String, RetentionStatus>? = null
  private fun reportRetention(origin: String, status: RetentionStatus) {
    if (status.valid || retentionEligible == null) return
    val decision = origin to status
    if (lastRetentionDecision == decision) return
    lastRetentionDecision = decision
    evidence.retentionDecision(origin, requireNotNull(status.condition), status.actual, status.exceptionType)
  }

  /** Dev experiment: retain routing only, never an AudioRecord or its reader. */
  fun enableForegroundRetention(eligible: () -> Boolean) { retentionEligible = eligible }

  fun selectBluetooth(): Boolean = synchronized(retentionLock) {
    check(!released) { "capture_route_cancelled" }
    if (Build.VERSION.SDK_INT < 31) return false
    check(bluetoothPermission()) { "Bluetooth permission is required to verify the recording microphone." }
    val devices = manager.availableCommunicationDevices
    val device = devices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
      ?: devices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLE_HEADSET }
    if (device == null) {
      check(manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS).none {
        it.type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP || it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO ||
          it.type == AudioDeviceInfo.TYPE_BLE_HEADSET || it.type == AudioDeviceInfo.TYPE_BLE_SPEAKER
      }) { "Connected Bluetooth device has no available headset microphone. Reconnect it before recording." }
      return false
    }
    check(bind(device)) { "Bluetooth headset microphone selection failed. Reconnect the headset and try again." }
    return true
  }

  fun bind(device: AudioDeviceInfo): Boolean = synchronized(retentionLock) {
    check(!released) { "capture_route_cancelled" }
    check(token == null) { "capture_route_already_selected" }
    if (Build.VERSION.SDK_INT < 31) return false
    retained?.let { parked ->
      val logical = parked.retentionStatus()
      val status = if (logical.valid) parked.routeStatus() else logical
      if (!status.valid) {
        parked.reportRetention("reuse", status)
        parked.releaseHardware(); retained = null; cancelMaintenance()
      }
    }
    val parked = retained
    if (parked != null && parked.ticket == ticket &&
      parked.token?.deviceId == device.id && parked.token?.deviceType == device.type) {
      evidence.routeStep("reuse_route") {
        if (parked.outputVerified) parked.ensureOutput { parked.retentionEligible?.invoke() == true }
        // Output-only admission owns this route independently of microphone use.
        if (retentionEligible == null) retentionEligible = parked.retentionEligible
        outputVerified = parked.outputVerified
        token = parked.token; previousMode = parked.previousMode; selected = parked.selected
        parked.token = null; parked.previousMode = null; parked.selected = false
        retained = null; cancelMaintenance()
        NCCommunicationRoute.shared.beginPreparation(requireNotNull(token))
      }
      return true
    }
    // Acquire before touching global Android state. A failed competing capture
    // must never restore/clear the current recorder's route.
    val owner = NCCommunicationRoute.shared.acquire(ticket, device.id, device.type)
    token = owner
    NCCommunicationRoute.shared.beginPreparation(owner)
    previousMode = manager.mode
    evidence.routeStep("set_mode") { manager.mode = AudioManager.MODE_IN_COMMUNICATION }
    selected = evidence.routeStep("select_device") { manager.setCommunicationDevice(device) }
    return selected
  }

  fun confirmMicrophone(actualInput: () -> Int?, current: () -> Boolean, strict: Boolean = false) {
    val owner = token ?: return
    evidence.routeStep("confirm_microphone") {
    val deadline = SystemClock.elapsedRealtime() + 4_000L
    do {
      check(current() && NCCommunicationRoute.shared.isCurrent(owner)) { "capture_route_cancelled" }
      if (strict) check(actualInput() == owner.deviceType) {
        "Bluetooth microphone was not active when recording started. Recording was not accepted."
      }
      // This read can wait for SCO. Sample input afterward, never before it.
      val output = manager.communicationDevice
      val input = actualInput()
      check(current() && NCCommunicationRoute.shared.isCurrent(owner)) { "capture_route_cancelled" }
      check(!strict || input == owner.deviceType) {
        "Recording microphone changed away from the Bluetooth headset. Recording was not accepted."
      }
      if (manager.mode == AudioManager.MODE_IN_COMMUNICATION &&
        NCCommunicationRoute.shared.accepts(owner, output?.id, output?.type) && input == owner.deviceType) {
        return@routeStep
      }
      SystemClock.sleep(40)
    } while (SystemClock.elapsedRealtime() < deadline)
    error("Bluetooth headset microphone did not become active. Recording was not accepted.")
    }
  }

  fun finishPreparation() = synchronized(retentionLock) {
    token?.let { NCCommunicationRoute.shared.endPreparation(it); verified = true }
  }

  private fun confirmOutput(current: () -> Boolean) {
    val owner = requireNotNull(token)
    val deadline = SystemClock.elapsedRealtime() + 4_000L
    do {
      check(current() && NCCommunicationRoute.shared.isCurrent(owner)) { "playback_route_cancelled" }
      val output = manager.communicationDevice
      check(current() && NCCommunicationRoute.shared.isCurrent(owner)) { "playback_route_cancelled" }
      if (manager.mode == AudioManager.MODE_IN_COMMUNICATION &&
        NCCommunicationRoute.shared.accepts(owner, output?.id, output?.type)) {
        outputVerified = true
        NCCommunicationRoute.shared.endPreparation(owner)
        return
      }
      SystemClock.sleep(40)
    } while (SystemClock.elapsedRealtime() < deadline)
    error("Bluetooth headset output did not become active.")
  }

  private fun ensureOutput(current: () -> Boolean) {
    val owner = requireNotNull(token)
    try {
      check(current() && NCCommunicationRoute.shared.isCurrent(owner)) { "playback_route_cancelled" }
      val output = manager.communicationDevice
      if (manager.mode == AudioManager.MODE_IN_COMMUNICATION &&
        NCCommunicationRoute.shared.accepts(owner, output?.id, output?.type)) return
      val device = manager.availableCommunicationDevices.firstOrNull {
        it.id == owner.deviceId && it.type == owner.deviceType
      } ?: error("Bluetooth headset output is no longer available.")
      check(current() && NCCommunicationRoute.shared.isCurrent(owner)) { "playback_route_cancelled" }
      NCCommunicationRoute.shared.beginPreparation(owner)
      evidence.routeStep("set_mode") { manager.mode = AudioManager.MODE_IN_COMMUNICATION }
      check(evidence.routeStep("select_device") { manager.setCommunicationDevice(device) }) {
        "Bluetooth headset output selection failed."
      }
      confirmOutput(current)
    } catch (error: Exception) {
      // This is a parked route: preserve custody and retry exact cleanup.
      retentionEligible = { false }
      scheduleMaintenance()
      throw error
    }
  }

  fun release() = synchronized(retentionLock) {
    if (retained === this && released) return@synchronized
    released = true
    parkedEpoch = foregroundEpoch.get()
    val status = if (verified || outputVerified) retentionStatus() else RetentionStatus("microphone_verified", false)
    if (status.valid) {
      evidence.routeStep("retain_route") {
        check(retained == null) { "capture_route_retention_busy" }
        retained = this
        scheduleMaintenance()
      }
      return@synchronized
    }
    reportRetention("stop", status)
    releaseHardware()
  }

  private fun retentionStatus(): RetentionStatus {
    var check = "foreground"
    try {
    if (!outputVerified && !foreground) return RetentionStatus(check, false)
    check = "foreground_epoch_current"
    if (!outputVerified && parkedEpoch != foregroundEpoch.get()) return RetentionStatus(check, false)
    val owner = token
    if (owner == null) return RetentionStatus("route_token_present", false)
    if (owner.deviceType != AudioDeviceInfo.TYPE_BLUETOOTH_SCO &&
      !(outputVerified && owner.deviceType == AudioDeviceInfo.TYPE_BLE_HEADSET)) return RetentionStatus("sco_route", false)
    if (retentionEligible == null) return RetentionStatus("retention_enabled", false)
    check = "output_open"
    if (retentionEligible?.invoke() != true) return RetentionStatus(check, false)
    if (!selected) return RetentionStatus("route_selected", false)
    check = "route_owner_current"
    if (!NCCommunicationRoute.shared.isCurrent(owner)) return RetentionStatus(check, false)
    return retainedValid
    } catch (error: Exception) { return RetentionStatus(check, null, exceptionKind(error)) }
  }

  // Worker only: Android's route getters can block while SCO is negotiating.
  private fun routeStatus(): RetentionStatus {
    var check = "route_token_present"
    try {
      val owner = token ?: return RetentionStatus(check, false)
      check = "bluetooth_permission"
      if (!bluetoothPermission()) return RetentionStatus(check, false)
      check = "communication_mode"
      val mode = manager.mode
      if (outputVerified && mode == AudioManager.MODE_NORMAL) {
        // Android may suspend an inactive communication client while cached
        // idle has no audio. This is retention evidence, NOT a play grant.
        return if (manager.availableCommunicationDevices.any {it.id == owner.deviceId && it.type == owner.deviceType})
          retainedValid else RetentionStatus("device_available", false)
      }
      if (mode != AudioManager.MODE_IN_COMMUNICATION) return RetentionStatus(check, mode)
      check = "communication_device_read"
      val device = manager.communicationDevice ?: return RetentionStatus("communication_device_present", false)
      if (device.id != owner.deviceId) return RetentionStatus("communication_device_id_matches", false)
      if (device.type != owner.deviceType) return RetentionStatus("communication_device_type_matches", false)
      check = "device_available"
      if (!manager.availableCommunicationDevices.any { it.id == owner.deviceId && it.type == owner.deviceType })
        return RetentionStatus(check, false)
      return retainedValid
    } catch (error: Exception) { return RetentionStatus(check, null, exceptionKind(error)) }
  }

  private fun releaseHardware() {
    val owner = token ?: return
    evidence.routeStep("release_route") {
    check(NCCommunicationRoute.shared.isCurrent(owner)) { "capture_route_owner_changed" }
    NCCommunicationRoute.shared.beginPreparation(owner)
    // Retain exact ownership if an Android cleanup operation fails.
    if (selected && Build.VERSION.SDK_INT >= 31) {
      // Android may deliver these exact SCO-device removals after clear returns.
      // Preserve a one-shot expectation, not a general route-change grace period.
      if (owner.deviceType == AudioDeviceInfo.TYPE_BLUETOOTH_SCO) {
        val transientIds = manager.getDevices(AudioManager.GET_DEVICES_ALL)
          .filter { it.type == owner.deviceType }.map { it.id }.toSet() + owner.deviceId
        NCCommunicationRoute.shared.expectRestoration(owner, transientIds)
      }
      evidence.routeStep("clear_device") { manager.clearCommunicationDevice() }; selected = false
    }
    previousMode?.let { evidence.routeStep("restore_mode") { manager.mode = it }; previousMode = null }
    NCCommunicationRoute.shared.release(owner)
    token = null
    }
  }

  companion object {
    /** Worker-only output setup, before player creation. No recorder/input API.
     * Park under the same ticket so subsequent capture reuses, not steals, it.
     */
    @JvmStatic fun preparePlayback(manager: AudioManager, ticket: String,
      bluetoothPermission: () -> Boolean, current: () -> Boolean): Boolean = synchronized(retentionLock) {
      if (!current() || Build.VERSION.SDK_INT < 31 || !bluetoothPermission()) return@synchronized false
      val existing = NCCommunicationRoute.shared.forTicket(ticket)
      if (existing != null) {
        val parked = retained
        if (parked == null || parked.token !== existing || !parked.outputVerified) return@synchronized true
        val status = parked.routeStatus()
        if (status.valid) {
          parked.ensureOutput(current)
          return@synchronized true
        }
        parked.releaseHardware(); retained = null; cancelMaintenance()
      }
      val devices = manager.availableCommunicationDevices
      val device = devices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
        ?: devices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLE_HEADSET }
        ?: return@synchronized false // Output-only devices never require a microphone.
      if (!current()) return@synchronized false
      val route = NCCaptureRoute(manager, ticket, bluetoothPermission)
      route.enableForegroundRetention(current)
      try {
        check(route.bind(device)) { "Bluetooth headset output selection failed." }
        route.confirmOutput(current)
        true
      } finally {
        try { route.release() }
        catch (error: Exception) {
          // The short-lived output preparer has no recorder to retain a failed
          // close. Keep its exact token/custody until maintenance confirms it.
          if (route.token != null && retained == null) {
            route.retentionEligible = { false }
            retained = route
            scheduleMaintenance()
          }
          throw error
        }
      }
    }

    private val retainedValid = RetentionStatus()
    private fun exceptionKind(error: Exception): String = when(error) {
      is SecurityException -> "SecurityException"
      is IllegalStateException -> "IllegalStateException"
      is IllegalArgumentException -> "IllegalArgumentException"
      else -> "other"
    }
    private val retentionLock = Any()
    @Volatile private var foreground = true
    private val foregroundEpoch = java.util.concurrent.atomic.AtomicLong()
    private var retained: NCCaptureRoute? = null
    // Device queries/cleanup can block; never put them on the UI/audio thread.
    private val maintenance = java.util.concurrent.Executors.newSingleThreadScheduledExecutor { work ->
      Thread(work, "nc-retained-bt-route").apply { isDaemon = true }
    }
    private var maintenanceTask: java.util.concurrent.ScheduledFuture<*>? = null
    @JvmStatic fun setForeground(value: Boolean) {
      foreground = value
      if (!value) {
        foregroundEpoch.incrementAndGet()
        maintenance.execute { cleanupRetainedSafely() }
      }
    }
    private fun scheduleMaintenance() {
      if (maintenanceTask == null) maintenanceTask = maintenance.scheduleWithFixedDelay({
        cleanupRetainedSafely()
      }, 500, 500, java.util.concurrent.TimeUnit.MILLISECONDS)
    }
    private fun cancelMaintenance() { maintenanceTask?.cancel(false); maintenanceTask = null }
    private fun cleanupRetained() {
      val parked = synchronized(retentionLock) { retained } ?: return
      val route = parked.routeStatus()
      synchronized(retentionLock) {
        if (retained !== parked) return
        val status = if (route.valid) parked.retentionStatus() else route
        if (!status.valid) {
          parked.reportRetention("maintenance", status)
          parked.releaseHardware()
          retained = null; cancelMaintenance()
        }
      }
    }
    private fun cleanupRetainedSafely() {
      // releaseHardware records failure. Keep ownership and retry; never admit
      // a replacement on unconfirmed cleanup or kill the maintenance worker.
      try { cleanupRetained() } catch (_: Exception) {}
    }
  }
}

