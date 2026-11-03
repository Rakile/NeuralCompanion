import ExpoModulesCore
#if os(iOS)
import UIKit
#endif

extension NCPlaybackGuard {
  // One native route identity algorithm for capture seal/arm and Expo events.
  // Empty means unknown; built-in routes are identified but foreground-only.
  // Transient port identifiers never leave native memory.
  public static func nativeRouteKey(_ route: AVAudioSessionRouteDescription = AVAudioSession.sharedInstance().currentRoute) -> String {
    #if os(iOS)
    guard route.outputs.count == 1, let port = route.outputs.first else { return "" }
    let headphones = [AVAudioSession.Port.headphones, .bluetoothHFP, .bluetoothA2DP, .bluetoothLE].contains(port.portType)
    let builtIn = [AVAudioSession.Port.builtInSpeaker, .builtInReceiver].contains(port.portType)
    guard headphones || builtIn else { return "" }
    func identity(_ ports: [AVAudioSessionPortDescription]) -> String {
      ports.map { port in
        let type = port.portType.rawValue
        return "\(type.utf8.count):\(type)\(port.uid.utf8.count):\(port.uid)"
      }.sorted().joined(separator: "|")
    }
    let input = identity(route.inputs)
    return (builtIn ? "foreground:" : "") + "\(input.utf8.count):\(input)\(identity(route.outputs))"
    #else
    return ""
    #endif
  }
}

public class AudioModule: Module {
  private var sessionIsActive = true
  private let registry = AudioComponentRegistry()
  var ncPlaybackOwner = NCPlaybackGuard.shared
  var ncRouteKey: () -> String = { NCPlaybackGuard.nativeRouteKey() }
  var ncMakePlayer: (AVPlayer, Double, NCPlaybackGuard) -> AudioPlayer = {
    AudioPlayer($0, interval: $1, playbackOwner: $2)
  }
  var ncSetSessionActive: (Bool, AVAudioSession.SetActiveOptions) throws -> Void = {
    try AVAudioSession.sharedInstance().setActive($0, options: $1)
  }

  // MARK: Properties
  private var recordingSettings = [String: Any]()
  private var shouldPlayInBackground = false
  private var interruptionMode: InterruptionMode = .mixWithOthers
  private var interruptedPlayers = Set<String>()
  private var playerVolumes = [String: Float]()
  private var allowsRecording = false
  private var allowsBackgroundRecording = false
  private var sessionOptions: AVAudioSession.CategoryOptions = []

  public func definition() -> ModuleDefinition {
    Name("ExpoAudio")

    Function("ncPlaybackGuardVersion") { NCPlaybackGuard.version }
    // This is the receipt primitive only; capture/UI negotiate their own version.
    Function("ncPhoneReplyReceiptVersion") { NCPlaybackGuard.phoneReplyReceiptVersion }
    Function("ncFreezePhoneReplyReceipt") { (ticket: String, requestId: String, interruptionId: String) -> [String: Any]? in
      self.ncPlaybackOwner.freezePhoneReplyReceipt(ticket: ticket, requestId: requestId, interruptionId: interruptionId)?.payload
    }
    Function("ncSkipPhoneReplyAudio") { (ticket: String, requestId: String) -> Bool in
      self.ncPlaybackOwner.skipPhoneReplyAudio(ticket: ticket, requestId: requestId)
    }
    Function("ncFinishPhoneReplyAudio") { (ticket: String, requestId: String) -> Bool in
      self.ncPlaybackOwner.finishPhoneReplyAudio(ticket: ticket, requestId: requestId)
    }

    OnCreate {
      #if os(iOS)
      self.appContext?.permissions?.register([
        AudioRecordingRequester()
      ])
      #endif

      setupInterruptionHandling()
    }

    AsyncFunction("setAudioModeAsync") { (mode: AudioMode) in
      try setAudioMode(mode: mode)
    }

    AsyncFunction("setIsAudioActiveAsync") { (isActive: Bool)  in
      try setIsAudioActive(isActive)
    }

    AsyncFunction("requestRecordingPermissionsAsync") { (promise: Promise) in
      #if os(iOS)
      appContext?.permissions?.askForPermission(
        usingRequesterClass: AudioRecordingRequester.self,
        resolve: promise.resolver,
        reject: promise.legacyRejecter
      )
      #else
      promise.reject(Exception.init(name: "UnsupportedOperation", description: "Audio recording is not supported on this platform."))
      #endif
    }

    AsyncFunction("getRecordingPermissionsAsync") { (promise: Promise) in
      #if os(iOS)
      appContext?.permissions?.getPermissionUsingRequesterClass(
        AudioRecordingRequester.self,
        resolve: promise.resolver,
        reject: promise.legacyRejecter
      )
      #else
      promise.reject(Exception.init(name: "UnsupportedOperation", description: "Audio recording is not supported on this platform."))
      #endif
    }

    OnDestroy {
      registry.allPlayers.values.forEach { $0.ncBinding.remove() }
      registry.removeAll()
      NotificationCenter.default.removeObserver(self)
    }

    OnAppEntersBackground {
      if !shouldPlayInBackground {
        pauseAllPlayers()
      }
      #if os(iOS)
      if !allowsBackgroundRecording {
        pauseAllRecorders()
      }
      #endif
    }

    OnAppEntersForeground {
      if !shouldPlayInBackground {
        resumeAllPlayers()
      }
      #if os(iOS)
      if !allowsBackgroundRecording {
        resumeAllRecorders()
      }
      #endif
    }

    // swiftlint:disable:next closure_body_length
    Class(AudioPlayer.self) {
      Constructor { (source: AudioSource?, updateInterval: Double, keepAudioSessionActive: Bool) -> AudioPlayer in
        ncCreatePlayer(source: source, updateInterval: updateInterval, keepAudioSessionActive: keepAudioSessionActive)
      }

      Property("id") { player in
        player.id
      }

      Property("isAudioSamplingSupported") {
        true
      }

      Property("isBuffering") { player in
        player.isBuffering
      }

      Property("loop") { player in
        player.isLooping
      }.set { (player, isLooping: Bool) in
        player.isLooping = isLooping
      }

      Property("isLoaded") { player in
        player.isLoaded
      }

      Property("playing") { player in
        player.isPlaying
      }

      Property("muted") { player in
        player.ref.isMuted
      }.set { (player, isMuted: Bool) in
        player.ref.isMuted = isMuted
      }

      Property("shouldCorrectPitch") { player in
        player.shouldCorrectPitch
      }.set { (player, shouldCorrectPitch: Bool) in
        player.shouldCorrectPitch = shouldCorrectPitch
      }

      Property("currentTime") { player in
        player.currentTime
      }

      Property("duration") { player in
        player.ref.status == .readyToPlay ? player.duration : 0.0
      }

      Property("playbackRate") { player in
        return if player.isPlaying {
          player.ref.rate
        } else {
          player.currentRate
        }
      }

      Property("paused") { player in
        player.isPaused
      }

      Property("volume") { player in
        player.ref.volume
      }.set { (player, volume: Double) in
        player.ref.volume = Float(volume)
      }

      Property("currentStatus") { player in
        player.currentStatus()
      }

      Function("ncBindPlaybackTicket") { (player: AudioPlayer, ticket: String) -> Bool in
        player.ncBinding.bind(ticket: ticket)
      }
      Function("ncBindPhoneReplyChunk") { (player: AudioPlayer, ticket: String, requestId: String, chunkId: String) -> Bool in
        player.ncBinding.bindPhoneReplyChunk(ticket: ticket, requestId: requestId, chunkId: chunkId)
      }

      Function("play") { player in
        try ncPlayPlayer(player)
      }

      Function("setPlaybackRate") { (player, rate: Double, pitchCorrectionQuality: PitchCorrectionQuality?) in
        let playerRate = rate < 0 ? 0.0 : Float(min(rate, 2.0))
        player.currentRate = playerRate

        player.ncBinding.setRate(playerRate)

        if player.shouldCorrectPitch {
          player.pitchCorrectionQuality = pitchCorrectionQuality?.toPitchAlgorithm() ?? .timeDomain
          player.ref.currentItem?.audioTimePitchAlgorithm = player.pitchCorrectionQuality
        } else {
          player.ref.currentItem?.audioTimePitchAlgorithm = .varispeed
        }
      }

      Function("replace") { (player, source: AudioSource) in
        player.replaceCurrentSource(source: source)
      }

      Function("pause") { player in
        player.ncBinding.pause()
        if !player.keepAudioSessionActive {
          deactivateSession(for: player)
        }
      }

      Function("remove") { player in
        player.ncBinding.remove()
        self.registry.remove(player)
      }

      Function("setAudioSamplingEnabled") { (player, enabled: Bool) in
        if player.samplingEnabled != enabled {
          player.setSamplingEnabled(enabled: enabled)
        }
      }

      Function("setActiveForLockScreen") { (player: AudioPlayer, active: Bool, metadata: Metadata?, options: LockScreenOptions?) in
        player.setActiveForLockScreen(active, metadata: metadata, options: options)
      }

      Function("updateLockScreenMetadata") { (player: AudioPlayer, metadata: Metadata?) in
        if player.isActiveForLockScreen {
          player.metadata = metadata
          MediaController.shared.updateNowPlayingInfo(for: player)
        }
      }

      Function("clearLockScreenControls") { (player: AudioPlayer) in
        if player.isActiveForLockScreen {
          player.metadata = nil
          player.isActiveForLockScreen = false
          MediaController.shared.setActivePlayer(nil)
        }
      }

      AsyncFunction("seekTo") { (player: AudioPlayer, seconds: Double, toleranceMillisBefore: Double?, toleranceMillisAfter: Double?) in
        await player.seekTo(
          seconds: seconds,
          toleranceMillisBefore: toleranceMillisBefore,
          toleranceMillisAfter: toleranceMillisAfter
        )
      }
    }

    #if os(iOS)
    // swiftlint:disable:next closure_body_length
    Class(AudioRecorder.self) {
      Constructor { (options: RecordingOptions) -> AudioRecorder in
        let recordingDir = try recordingDirectory()
        let avRecorder = AudioUtils.createRecorder(directory: recordingDir, with: options)
        let recorder = AudioRecorder(avRecorder)
        recorder.owningRegistry = self.registry
        recorder.allowsRecording = allowsRecording
        self.registry.add(recorder)

        return recorder
      }

      Property("id") { recorder in
        recorder.id
      }

      Property("isRecording") { recorder in
        recorder.isRecording
      }

      Property("currentTime") { recorder in
        recorder.ref.currentTime
      }

      Property("uri") { recorder in
        recorder.uri
      }

      AsyncFunction("prepareToRecordAsync") { (recorder, options: RecordingOptions?) in
        try recorder.prepare(options: options, sessionOptions: sessionOptions)
      }

      Function("record") { (recorder: AudioRecorder, options: RecordOptions?) in
        try checkPermissions()

        switch (options?.atTime, options?.forDuration) {
        case let (atTime?, forDuration?):
          // Convert relative delay to absolute device time
          let absoluteTime = recorder.ref.deviceCurrentTime + TimeInterval(atTime)
          recorder.ref.record(atTime: absoluteTime, forDuration: TimeInterval(forDuration))
          recorder.updateStateForDirectRecording()
          return recorder.getRecordingStatus()
        case let (atTime?, nil):
          // Convert relative delay to absolute device time
          let absoluteTime = recorder.ref.deviceCurrentTime + TimeInterval(atTime)
          recorder.ref.record(atTime: absoluteTime)
          recorder.updateStateForDirectRecording()
          return recorder.getRecordingStatus()
        case let (nil, forDuration?):
          recorder.ref.record(forDuration: TimeInterval(forDuration))
          recorder.updateStateForDirectRecording()
          return recorder.getRecordingStatus()
        case (nil, nil):
          return try recorder.startRecording()
        }
      }

      Function("pause") { recorder in
        try checkPermissions()
        recorder.pauseRecording()
      }

      AsyncFunction("stop") { recorder in
        try checkPermissions()
        recorder.stopRecording()
      }

      Function("getStatus") { recorder -> [String: Any] in
        recorder.getRecordingStatus()
      }

      Function("startRecordingAtTime") { (recorder, seconds: Double) in
        try checkPermissions()
        recorder.ref.record(atTime: TimeInterval(seconds))
      }

      Function("recordForDuration") { (recorder, seconds: Double) in
        try checkPermissions()
        recorder.ref.record(forDuration: TimeInterval(seconds))
      }

      Function("getAvailableInputs") {
        RecordingUtils.getAvailableInputs()
      }

      Function("getCurrentInput") { () -> [String: Any] in
        try RecordingUtils.getCurrentInput()
      }

      Function("setInput") { (input: String) in
        try RecordingUtils.setInput(input)
      }
    }
    #endif
  }

  func ncCreatePlayer(source: AudioSource?, updateInterval: Double, keepAudioSessionActive: Bool) -> AudioPlayer {
    let player = ncMakePlayer(AudioUtils.createAVPlayer(from: source), updateInterval, ncPlaybackOwner)
    player.owningRegistry = registry
    player.keepAudioSessionActive = keepAudioSessionActive
    player.onPlaybackComplete = { [weak self, weak player] in
      if !keepAudioSessionActive, let player { self?.deactivateSession(for: player) }
    }
    registry.add(player)
    return player
  }

  func ncPlayPlayer(_ player: AudioPlayer) throws {
    let rate = player.currentRate > 0 ? player.currentRate : 1.0
    try player.play(at: rate, activate: { try activateSession() })
  }

  func setupInterruptionHandling() {
    let session = AVAudioSession.sharedInstance()
    NotificationCenter.default.addObserver(
      self,
      selector: #selector(handleAudioSessionInterruption(_:)),
      name: AVAudioSession.interruptionNotification,
      object: session
    )

    NotificationCenter.default.addObserver(
      self,
      selector: #selector(handleAudioSessionRouteChange(_:)),
      name: AVAudioSession.routeChangeNotification,
      object: session
    )
    NotificationCenter.default.addObserver(
      self, selector: #selector(handleAudioSessionMediaReset(_:)),
      name: AVAudioSession.mediaServicesWereResetNotification, object: session
    )
    #if os(iOS)
    NotificationCenter.default.addObserver(self, selector: #selector(handleUnarmedResign(_:)),
      name: UIApplication.willResignActiveNotification, object: nil)
    #endif
  }

  @objc private func handleUnarmedResign(_ notification: Notification) {
    ncPlaybackOwner.retireUnarmedProtected()
  }

  @objc private func handleAudioSessionMediaReset(_ notification: Notification) {
    ncPlaybackOwner.retireProtected(cause: .mediaReset)
  }

  @objc private func handleAudioSessionInterruption(_ notification: Notification) {
    guard let userInfo = notification.userInfo,
      let interruptionTypeRaw = userInfo[AVAudioSessionInterruptionTypeKey] as? UInt,
      let interruptionType = AVAudioSession.InterruptionType(rawValue: interruptionTypeRaw) else {
      return
    }

    switch interruptionType {
    case .began:
      handleInterruptionBegan()

    case .ended:
      if let optionsRaw = userInfo[AVAudioSessionInterruptionOptionKey] as? UInt {
        let options = AVAudioSession.InterruptionOptions(rawValue: optionsRaw)
        handleInterruptionEnded(with: options)
      } else {
        handleInterruptionEnded(with: [])
      }

    @unknown default:
      break
    }
  }

  private func handleInterruptionBegan() {
    ncPlaybackOwner.retireProtected(cause: .interruption)
    interruptedPlayers.removeAll()
    playerVolumes.removeAll()

    registry.allPlayers.values.forEach { player in
      if player.isPlaying {
        interruptedPlayers.insert(player.id)
        switch interruptionMode {
        case .duckOthers:
          playerVolumes[player.id] = player.ref.volume
          player.ref.volume *= 0.5
        case .doNotMix, .mixWithOthers:
          player.ref.pause()
        }
      }
    }

#if os(iOS)
    registry.allRecorders.values.forEach { recorder in
      if recorder.isRecording {
        recorder.pauseRecording()
      }
    }
#endif
  }

  func handleInterruptionEnded(with options: AVAudioSession.InterruptionOptions) {
    do {
      // Unmanaged/recorder activation keeps upstream behavior; managed resume activates atomically per player.
      let bindings = registry.allPlayers.values.map { $0.ncBinding! }
      var hasRecorders = false
      #if os(iOS)
      hasRecorders = !registry.allRecorders.isEmpty
      #endif
      try ncPlaybackOwner.activateSession(players: bindings, hasRecorders: hasRecorders) {
        try ncSetSessionActive(true, [])
      }
      if options.contains(.shouldResume) {
        resumeInterruptedPlayers()
      }
    } catch {
      print("Failed to reactivate audio session: \(error)")
    }
  }

  @objc private func handleAudioSessionRouteChange(_ notification: Notification) {
    let reasonRaw = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
    let reason = reasonRaw.flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))
    ncPlaybackOwner.admitSetupRouteChange(
      isSetupChange: reason == .categoryChange || reason == .routeConfigurationChange, routeKey: ncRouteKey())

    switch reason {
    case .some(.oldDeviceUnavailable):
      pauseAllPlayers()
    default:
      break
    }
  }

  private func resumeInterruptedPlayers() {
    registry.allPlayers.values.forEach { player in
      if interruptedPlayers.contains(player.id) {
        switch interruptionMode {
        case .duckOthers:
          if let originalVolume = playerVolumes[player.id] {
            player.ref.volume = originalVolume
          }
        case .doNotMix, .mixWithOthers:
          try? player.ncBinding.resume(activate: { try self.activateSession() })
        }
      }
    }

#if os(iOS)
    registry.allRecorders.values.forEach { recorder in
      if recorder.allowsRecording && !recorder.isRecording {
        _ = try? recorder.startRecording()
      }
    }
#endif

    interruptedPlayers.removeAll()
    playerVolumes.removeAll()
  }

  private func pauseAllPlayers() {
    registry.allPlayers.values.forEach { player in
      if player.isPlaying {
        player.wasPlaying = true
        player.ref.pause()
      }
    }
  }

  func resumeAllPlayers() {
    registry.allPlayers.values.forEach { player in
      if player.wasPlaying {
        try? player.ncBinding.resume(activate: { try self.activateSession() })
        player.wasPlaying = false
      }
    }
  }

  private func pauseAllRecorders() {
#if os(iOS)
    registry.allRecorders.values.forEach { recorder in
      if recorder.isRecording {
        recorder.pauseRecording()
      }
    }
#endif
  }

  private func resumeAllRecorders() {
#if os(iOS)
    registry.allRecorders.values.forEach { recorder in
      if recorder.allowsRecording && !recorder.isRecording {
        _ = try? recorder.startRecording()
      }
    }
#endif
  }

  private func recordingDirectory() throws -> URL {
    guard let cachesDir = appContext?.fileSystem?.cachesDirectory else {
      throw Exceptions.AppContextLost()
    }
    return URL(fileURLWithPath: cachesDir)
  }

  private func setIsAudioActive(_ isActive: Bool) throws {
    if !isActive {
      pauseAllPlayers()
    }

    do {
      if isActive {
        let bindings = registry.allPlayers.values.map { $0.ncBinding! }
        var hasRecorders = false
        #if os(iOS)
        hasRecorders = !registry.allRecorders.isEmpty
        #endif
        try ncPlaybackOwner.activateSession(players: bindings, hasRecorders: hasRecorders, explicitPreparation: true) {
          try ncSetSessionActive(true, [])
          sessionIsActive = true
        }
      } else {
        try ncSetSessionActive(false, [.notifyOthersOnDeactivation])
        sessionIsActive = false
      }
    } catch {
      throw AudioStateException(error.localizedDescription)
    }
  }

  private func setAudioMode(mode: AudioMode) throws {
    try AudioUtils.validateAudioMode(mode: mode)
    let session = AVAudioSession.sharedInstance()
    var category: AVAudioSession.Category = session.category

    self.shouldPlayInBackground = mode.shouldPlayInBackground
    self.interruptionMode = mode.interruptionMode
    self.allowsRecording = mode.allowsRecording
    self.allowsBackgroundRecording = mode.allowsBackgroundRecording

    #if os(iOS)
    if !mode.allowsRecording {
      registry.allRecorders.values.forEach { recorder in
        if recorder.isRecording {
          recorder.ref.stop()
        }
        recorder.allowsRecording = false
      }
    } else {
      registry.allRecorders.values.forEach { recorder in
        recorder.allowsRecording = true
      }
    }
    #endif

    if !mode.playsInSilentMode {
      if mode.interruptionMode == .doNotMix {
        category = .soloAmbient
      } else {
        category = .ambient
      }
      sessionOptions = []
    } else {
      category = mode.allowsRecording ? .playAndRecord : .playback

      var categoryOptions: AVAudioSession.CategoryOptions = []
      switch mode.interruptionMode {
      case .doNotMix:
        break
      case .duckOthers:
        categoryOptions.insert(.duckOthers)
      case .mixWithOthers:
        categoryOptions.insert(.mixWithOthers)
      }

#if !os(tvOS)
      if category == .playAndRecord {
#if compiler(>=6.2) // Xcode 26
        categoryOptions.insert(.allowBluetoothHFP)
#else
        categoryOptions.insert(.allowBluetooth)
#endif
      }
#endif

      sessionOptions = categoryOptions
    }

    if sessionOptions.isEmpty {
      try session.setCategory(category, mode: .default)
    } else {
      try session.setCategory(category, options: sessionOptions)
    }
  }

  private func activateSession() throws {
    try ncSetSessionActive(true, [])
  }

  private func deactivateSession(for player: AudioPlayer) {
    // We need to give isPlaying time to update before running this
    let binding = player.ncBinding!
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
      guard let self else {
        return
      }
      let players = Array(self.registry.allPlayers.values)
      binding.deactivate {
        if !players.contains(where: { $0.isPlaying }) {
          // Never publish status or wait on another queue while holding output ownership.
          try? self.ncSetSessionActive(false, [.notifyOthersOnDeactivation])
        }
      }
    }
  }

  private func checkPermissions() throws {
    #if os(iOS)
    if #available(iOS 17.0, *) {
      switch AVAudioApplication.shared.recordPermission {
      case .denied, .undetermined:
        throw AudioPermissionsException()
      default:
        break
      }
    } else {
      switch AVAudioSession.sharedInstance().recordPermission {
      case .denied, .undetermined:
        throw AudioPermissionsException()
      default:
        break
      }
    }
    #endif
  }
}
