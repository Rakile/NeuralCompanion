import ExpoModulesCore
import Combine

private enum AudioConstants {
  static let playbackStatus = "playbackStatusUpdate"
  static let audioSample = "audioSampleUpdate"
}

public class AudioPlayer: SharedRef<AVPlayer>, NCPlaybackActions {
  private(set) var ncBinding: NCPlaybackBinding!
  private let ncStatusLock = NSRecursiveLock()
  private let ncDispatchStatus: (@escaping () -> Void) -> Void
  private let ncEmitStatus: (AudioPlayer, [String: Any]) -> Void
  var ncIsPlaying: Bool { isPlaying }
  var ncPositionSeconds: Double? { ref.currentTime().seconds }
  var ncCurrentItemIdentity: ObjectIdentifier? { ref.currentItem.map(ObjectIdentifier.init) }
  func ncPlay(rate: Float?) {
    if let rate { ref.playImmediately(atRate: rate) } else { ref.play() }
  }
  func ncPause() { ref.pause() }
  func ncSetRate(_ rate: Float) { ref.rate = rate }

  let id = UUID().uuidString
  var isLooping = false
  var shouldCorrectPitch = true
  var pitchCorrectionQuality: AVAudioTimePitchAlgorithm = .timeDomain
  var isActiveForLockScreen = false
  var metadata: Metadata?
  var currentRate: Float = 0.0
  let interval: Double
  var wasPlaying = false
  var isPaused: Bool {
    ref.rate == 0.0
  }
  var samplingEnabled = false
  var keepAudioSessionActive = false

  // MARK: Observers
  private var timeToken: Any?
  private var cancellables = Set<AnyCancellable>()
  private var endObserver: NSObjectProtocol?
  private var ncPlayingObservation: NSKeyValueObservation?

  private var audioProcessor: AudioTapProcessor?
  private var tapInstalled = false
  private var shouldInstallAudioTap = false
  weak var owningRegistry: AudioComponentRegistry?
  var onPlaybackComplete: (() -> Void)?

  var duration: Double {
    ref.currentItem?.duration.seconds ?? 0.0
  }

  var currentTime: Double {
    ref.currentItem?.currentTime().seconds ?? 0.0
  }

  init(_ ref: AVPlayer, interval: Double, playbackOwner: NCPlaybackGuard = .shared,
       dispatchStatus: @escaping (@escaping () -> Void) -> Void = { DispatchQueue.main.async(execute: $0) },
       emitStatus: @escaping (AudioPlayer, [String: Any]) -> Void = { player, arguments in
         player.emit(event: AudioConstants.playbackStatus, arguments: arguments)
       }) {
    self.interval = interval
    ncDispatchStatus = dispatchStatus
    ncEmitStatus = emitStatus
    super.init(ref)
    ncBinding = NCPlaybackBinding(owner: playbackOwner, actions: self)

    setupPublisher()
  }

  var isLoaded: Bool {
    ref.currentItem?.status == .readyToPlay
  }

  var isPlaying: Bool {
    ref.timeControlStatus == .playing
  }

  var isBuffering: Bool {
    playerIsBuffering()
  }

  func play(at rate: Float, activate: () throws -> Void = {}) rethrows {
    addPlaybackEndNotification()
    registerTimeObserver()
    guard try ncBinding.play(rate: rate, activate: activate) else { return }
    DispatchQueue.main.async { [weak self] in
      guard let self, self.isActiveForLockScreen else { return }
      MediaController.shared.updateNowPlayingInfo(for: self)
    }
  }

  func playForMediaCommand(toggle: Bool = false) -> Bool {
    // Observer removal/registration may involve AVFoundation queues: keep outside ownership.
    addPlaybackEndNotification()
    registerTimeObserver()
    let accepted = ncBinding.mediaPlay(rate: currentRate > 0 ? currentRate : 1.0, toggle: toggle)
    if accepted {
      DispatchQueue.main.async { [weak self] in
        guard let self, self.isActiveForLockScreen else { return }
        MediaController.shared.updateNowPlayingInfo(for: self)
      }
    }
    return accepted
  }

  func setSamplingEnabled(enabled: Bool) {
    if samplingEnabled == enabled {
      return
    }
    samplingEnabled = enabled
    if enabled {
      if isLoaded {
        installTap()
      } else {
        shouldInstallAudioTap = true
      }
    } else {
      uninstallTap()
      shouldInstallAudioTap = false
    }
  }

  func currentStatus() -> [String: Any] {
    let currentDuration = ref.status == .readyToPlay ? duration : 0.0
    let rate = isPlaying ? ref.rate : currentRate
    return [
      "id": id,
      "currentTime": currentTime,
      "playbackState": statusToString(status: ref.status),
      "timeControlStatus": timeControlStatusString(status: ref.timeControlStatus),
      "reasonForWaitingToPlay": reasonForWaitingToPlayString(status: ref.reasonForWaitingToPlay),
      "mute": ref.isMuted,
      "duration": currentDuration,
      "playing": isPlaying,
      "loop": isLooping,
      "didJustFinish": false,
      "isLoaded": isLoaded,
      "playbackRate": rate,
      "shouldCorrectPitch": shouldCorrectPitch,
      "isBuffering": isBuffering
    ]
  }

  func setActiveForLockScreen(_ active: Bool = true, metadata: Metadata? = nil, options: LockScreenOptions?) {
    self.metadata = metadata
    if active && !ncBinding.canUseMediaControls { return }
    if active {
      MediaController.shared.setActivePlayer(self, options: options)
    } else {
      MediaController.shared.setActivePlayer(nil)
    }
  }

  func updateStatus(with dict: [String: Any], for item: AVPlayerItem? = nil) {
    // AVPlayer may synchronously publish KVO while the output lock is held.
    let expectedItem = (item ?? ref.currentItem).map(ObjectIdentifier.init)
    ncDispatchStatus { [weak self] in
      guard let self else { return }
      // Status -> output is the replacement lock order; never acquire status from
      // output actions. JS publication occurs outside the output ownership lock.
      self.ncStatusLock.lock()
      defer { self.ncStatusLock.unlock() }
      guard expectedItem == self.ref.currentItem.map(ObjectIdentifier.init) else { return }
      self.emitStatus(with: dict)
    }
  }

  private func emitStatus(with dict: [String: Any]) {
    var arguments = currentStatus()
    arguments.merge(dict) { _, new in
      new
    }
    ncEmitStatus(self, arguments)

    if isActiveForLockScreen {
      MediaController.shared.updateNowPlayingInfo(for: self)
    }
  }

  func seekTo(seconds: Double, toleranceMillisBefore: Double? = nil, toleranceMillisAfter: Double? = nil) async {
    let time = CMTime(seconds: seconds, preferredTimescale: CMTimeScale(NSEC_PER_SEC))
    let toleranceBefore = toleranceMillisBefore.map {
      CMTime(seconds: $0 / 1000.0, preferredTimescale: CMTimeScale(NSEC_PER_SEC))
    } ?? CMTime.positiveInfinity
    let toleranceAfter = toleranceMillisAfter.map {
      CMTime(seconds: $0 / 1000.0, preferredTimescale: CMTimeScale(NSEC_PER_SEC))
    } ?? CMTime.positiveInfinity

    await ref.currentItem?.seek(to: time, toleranceBefore: toleranceBefore, toleranceAfter: toleranceAfter	)
    updateStatus(with: [
      "currentTime": currentTime
    ])
  }

  private func setupPublisher() {
    // Observe at AVPlayer's native acknowledgement boundary, before any main/JS
    // dispatch. The binding validates this player, its immutable item and actual
    // playing state inside the output lock; do not acquire ncStatusLock here.
    ncPlayingObservation = ref.observe(\.timeControlStatus, options: [.new]) { [weak self] player, _ in
      // Typed KVO enum payloads can be nil; read the player's current native state.
      guard let self, player.timeControlStatus == .playing, let item = player.currentItem else { return }
      guard self.ncBinding.acknowledgePhoneReplyStart(expectedItemIdentity: ObjectIdentifier(item)) else { return }
      // Re-read playing in currentStatus when publication actually runs; an onset
      // may pause output while JS is delayed.
      self.updateStatus(with: [:], for: item)
    }
    ref.publisher(for: \.currentItem?.status)
      .receive(on: DispatchQueue.main)
      .sink { [weak self] status in
        guard let self, let status else {
          return
        }
        if status == .readyToPlay {
          self.updateStatus(with: [
            "isLoaded": true
          ])
          if shouldInstallAudioTap || samplingEnabled {
            installTap()
            shouldInstallAudioTap = false
          }
        }
      }
      .store(in: &cancellables)

    ref.publisher(for: \.currentItem)
      .receive(on: DispatchQueue.main)
      .sink { [weak self] _ in
        guard let self else {
          return
        }
        if self.samplingEnabled && self.isLoaded {
          self.installTap()
        }
      }
      .store(in: &cancellables)
  }

  func replaceCurrentSource(source: AudioSource) {
    let item = AudioUtils.createAVPlayerItem(from: source)
    ncStatusLock.lock()
    defer { ncStatusLock.unlock() }
    let wasSamplingEnabled = samplingEnabled
    if samplingEnabled { uninstallTap() }
    ncBinding.replace {
      ref.replaceCurrentItem(with: item)
    }
    if wasSamplingEnabled { shouldInstallAudioTap = true }
    addPlaybackEndNotification()
  }

  private func playerIsBuffering() -> Bool {
    if isPlaying {
      return false
    }

    if ref.timeControlStatus == .waitingToPlayAtSpecifiedRate {
      return true
    }

    if let currentItem = ref.currentItem {
      return !currentItem.isPlaybackLikelyToKeepUp && currentItem.isPlaybackBufferEmpty
    }
    return true
  }

  private func installTap() {
    guard isLoaded else {
      shouldInstallAudioTap = true
      return
    }

    guard audioProcessor?.isTapInstalled != true else {
      tapInstalled = true
      return
    }

    if let audioProcessor {
      audioProcessor.invalidate()
    }

    audioProcessor = AudioTapProcessor(player: ref)
    let success = audioProcessor?.installTap() ?? false
    tapInstalled = success

    if success {
      audioProcessor?.sampleBufferCallback = { [weak self] buffer, frameCount, timestamp in
        guard let self = self,
          let audioBuffer = buffer?.pointee,
          let data = audioBuffer.mData,
          self.samplingEnabled else {
          return
        }

        let channelCount = Int(audioBuffer.mNumberChannels)
        let dataPointer = data.assumingMemoryBound(to: Float.self)

        let channels = (0..<channelCount).map { channelIndex in
          let channelData = stride(from: channelIndex, to: Int(frameCount), by: channelCount).map { frameIndex in
            dataPointer[frameIndex]
          }
          return ["frames": channelData]
        }

        self.emit(event: AudioConstants.audioSample, arguments: [
          "channels": channels,
          "timestamp": timestamp
        ])
      }
    }
  }

  private func uninstallTap() {
    tapInstalled = false
    audioProcessor?.uninstallTap()
    audioProcessor?.sampleBufferCallback = nil
  }

  private func addPlaybackEndNotification() {
    if let endObserver {
      NotificationCenter.default.removeObserver(endObserver)
    }

    let observedItem = ref.currentItem
    endObserver = NotificationCenter.default.addObserver(
      forName: .AVPlayerItemDidPlayToEndTime,
      object: observedItem,
      queue: nil
    ) { [weak self, weak observedItem] _ in
      guard let self, let observedItem, observedItem === self.ref.currentItem else {
        return
      }

      if self.isLooping {
        self.ncBinding.loop(isCurrentItem: { observedItem === self.ref.currentItem }) {
          self.ref.seek(to: CMTime.zero)
        }
      } else {
        self.ncBinding.acknowledgePhoneReplyCompletion(expectedItemIdentity: ObjectIdentifier(observedItem))
        self.updateStatus(with: [
          "playing": false,
          "currentTime": self.duration,
          "didJustFinish": true
        ], for: observedItem)
        // Completion is scheduled outside the guard; its session effect rechecks ownership.
        DispatchQueue.main.async { [weak self, weak observedItem] in
          guard let self, let observedItem, observedItem === self.ref.currentItem else { return }
          self.onPlaybackComplete?()
        }
      }
    }
  }

  private func registerTimeObserver() {
    if let timeToken {
      ref.removeTimeObserver(timeToken)
    }

    let updateInterval = interval / 1000
    let interval = CMTime(seconds: updateInterval, preferredTimescale: CMTimeScale(NSEC_PER_SEC))

    let observedItem = ref.currentItem
    timeToken = ref.addPeriodicTimeObserver(forInterval: interval, queue: nil) { [weak self, weak observedItem] time in
      guard let self else {
        return
      }

      if time.seconds > 0, let observedItem {
        self.ncBinding.acknowledgePhoneReplyStart(expectedItemIdentity: ObjectIdentifier(observedItem))
      }
      self.updateStatus(with: [
        "currentTime": time.seconds
      ], for: observedItem)
    }
  }

  public override func sharedObjectWillRelease() {
    ncBinding.remove()
    owningRegistry?.remove(self)
    ncPlayingObservation?.invalidate()
    ncPlayingObservation = nil
    cancellables.removeAll()

    if samplingEnabled {
      samplingEnabled = false
      uninstallTap()
    }

    if isActiveForLockScreen {
      MediaController.shared.setActivePlayer(nil)
    }

    audioProcessor?.invalidate()
    audioProcessor = nil

    if let timeToken {
      ref.removeTimeObserver(timeToken)
    }

    if let endObserver {
      NotificationCenter.default.removeObserver(endObserver)
    }

    ref.pause()
  }
}
