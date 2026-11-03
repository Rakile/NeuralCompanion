import MediaPlayer
import AVFoundation
import ExpoModulesCore

protocol NCNowPlayingInfoSink: AnyObject {
  var nowPlayingInfo: [String: Any]? { get set }
}
extension MPNowPlayingInfoCenter: NCNowPlayingInfoSink {}

class MediaController {
  static let shared = MediaController()

  private var activePlayer: AudioPlayer?
  private let playbackOwner: NCPlaybackGuard
  private var remoteCommandCenter = MPRemoteCommandCenter.shared()
  private let nowPlayingInfoCenter: NCNowPlayingInfoSink
  private let dispatchMedia: (@escaping () -> Void) -> Void

  init(playbackOwner: NCPlaybackGuard = .shared, nowPlayingInfoCenter: NCNowPlayingInfoSink = MPNowPlayingInfoCenter.default(),
       dispatchMedia: @escaping (@escaping () -> Void) -> Void = { DispatchQueue.main.async(execute: $0) }) {
    self.playbackOwner = playbackOwner
    self.nowPlayingInfoCenter = nowPlayingInfoCenter
    self.dispatchMedia = dispatchMedia
  }

  private var currentArtworkUrl: URL?
  private var cachedArtwork: MPMediaItemArtwork?
  
  func setActivePlayer(_ player: AudioPlayer?, options: LockScreenOptions? = nil) {
    let accepted = playbackOwner.publishMedia(for: player?.ncBinding, claimsOwnership: false) {
      if let previous = activePlayer, previous.id != player?.id {
        previous.isActiveForLockScreen = false
      }
      activePlayer = player
      player?.isActiveForLockScreen = true
    }
    guard accepted else { return }

    dispatchMedia {
      self.playbackOwner.publishMedia(for: player?.ncBinding, ifCurrent: { self.activePlayer?.id == player?.id }) {
        if let player {
          self.enableRemoteCommands(options: options)
          self.updateNowPlayingInfo(for: player)
        } else {
          self.disableRemoteCommands()
          self.clearNowPlayingInfo()
        }
      }
    }
  }

  func updateNowPlayingInfo(for player: AudioPlayer) {
    guard player.ncBinding.canUseMediaControls, player.id == activePlayer?.id else {
      return
    }
    var nowPlayingInfo = nowPlayingInfoCenter.nowPlayingInfo ?? [String: Any]()

    nowPlayingInfo[MPMediaItemPropertyPlaybackDuration] = player.duration
    nowPlayingInfo[MPNowPlayingInfoPropertyElapsedPlaybackTime] = player.currentTime
    nowPlayingInfo[MPNowPlayingInfoPropertyPlaybackRate] = player.isPlaying ? player.ref.rate : 1.0
    nowPlayingInfo[MPNowPlayingInfoPropertyMediaType] = MPNowPlayingInfoMediaType.audio.rawValue

    if let userMetadata = player.metadata {
      if let title = userMetadata.title {
        nowPlayingInfo[MPMediaItemPropertyTitle] = title
      }
      if let artist = userMetadata.artist {
        nowPlayingInfo[MPMediaItemPropertyArtist] = artist
      }
      if let album = userMetadata.albumTitle {
        nowPlayingInfo[MPMediaItemPropertyAlbumTitle] = album
      }
      if let artworkUrl = userMetadata.artworkUrl {
        if currentArtworkUrl != artworkUrl {
          currentArtworkUrl = artworkUrl
        } else {
          if let cachedArtwork {
            nowPlayingInfo[MPMediaItemPropertyArtwork] = cachedArtwork
            self.publishNowPlayingInfo(nowPlayingInfo, for: player)
          }
        }
        loadArtworkFromURL(url: artworkUrl) { [weak self, weak player] artwork in
          guard let player, player.ncBinding.canUseMediaControls,
            self?.activePlayer?.id == player.id else { return }
          if let artwork {
            nowPlayingInfo[MPMediaItemPropertyArtwork] = artwork
            self?.publishNowPlayingInfo(nowPlayingInfo, for: player, artwork: artwork)
          }
        }
      }
    } else {
      // Try to get the metadata from the provided asset
      if let currentItem = player.ref.currentItem,
      let asset = currentItem.asset as? AVURLAsset {
        let metadata = asset.commonMetadata

        for item in metadata {
          switch item.commonKey {
          case .commonKeyTitle:
            if let title = item.stringValue {
              nowPlayingInfo[MPMediaItemPropertyTitle] = title
            }
          case .commonKeyArtist:
            if let artist = item.stringValue {
              nowPlayingInfo[MPMediaItemPropertyArtist] = artist
            }
          case .commonKeyAlbumName:
            if let album = item.stringValue {
              nowPlayingInfo[MPMediaItemPropertyAlbumTitle] = album
            }
          case .commonKeyArtwork:
            if let imageData = item.dataValue,
              let image = UIImage(data: imageData) {
              let artwork = MPMediaItemArtwork(boundsSize: image.size) { _ in image }
              nowPlayingInfo[MPMediaItemPropertyArtwork] = artwork
            }
          default:
            break
          }
        }
      }
    }
    publishNowPlayingInfo(nowPlayingInfo, for: player)
  }

  private func publishNowPlayingInfo(_ info: [String: Any], for player: AudioPlayer, artwork: MPMediaItemArtwork? = nil) {
    playbackOwner.publishMedia(for: player.ncBinding, ifCurrent: { self.activePlayer?.id == player.id }) {
      if let artwork { cachedArtwork = artwork }
      nowPlayingInfoCenter.nowPlayingInfo = info
    }
  }

  func clearNowPlayingInfo() {
    playbackOwner.publishMedia(for: activePlayer?.ncBinding) {
      nowPlayingInfoCenter.nowPlayingInfo = nil
      activePlayer = nil
    }
  }

  private func loadArtworkFromURL(url: URL, completion: @escaping (MPMediaItemArtwork?) -> Void) {
    URLSession.shared.dataTask(with: url) { data, _, error in
      if error != nil {
        completion(nil)
        return
      }

      guard let data, let image = UIImage(data: data) else {
        completion(nil)
        return
      }

      let artwork = MPMediaItemArtwork(boundsSize: image.size) { _ in image }
      DispatchQueue.main.async {
        completion(artwork)
      }
    }
    .resume()
  }

  private func enableRemoteCommands(options: LockScreenOptions?) {
    remoteCommandCenter.playCommand.addTarget { [weak self] _ in
      guard let player = self?.activePlayer else {
        return .commandFailed
      }

      return player.playForMediaCommand() ? .success : .commandFailed
    }

    remoteCommandCenter.pauseCommand.addTarget { [weak self] _ in
      guard let player = self?.activePlayer else {
        return .commandFailed
      }

      return player.ncBinding.command { player.ncBinding.pause() } ? .success : .commandFailed
    }

    remoteCommandCenter.togglePlayPauseCommand.addTarget { [weak self] _ in
      guard let player = self?.activePlayer else {
        return .commandFailed
      }

      return player.playForMediaCommand(toggle: true) ? .success : .commandFailed
    }

    remoteCommandCenter.changePlaybackPositionCommand.addTarget { [weak self] event in
      guard let player = self?.activePlayer,
      let event = event as? MPChangePlaybackPositionCommandEvent else {
        return .commandFailed
      }

      let seekTime = CMTime(seconds: event.positionTime, preferredTimescale: 1)
      return player.ncBinding.command { player.ref.seek(to: seekTime) } ? .success : .commandFailed
    }

    remoteCommandCenter.skipForwardCommand.preferredIntervals = [10.0]
    remoteCommandCenter.skipForwardCommand.addTarget { [weak self] event in
      guard let player = self?.activePlayer,
      let event = event as? MPSkipIntervalCommandEvent else {
        return .commandFailed
      }

      let currentTime = player.ref.currentTime()
      let seekTime = currentTime + CMTime(seconds: event.interval, preferredTimescale: 1)
      return player.ncBinding.command {
        player.ref.seek(to: seekTime, toleranceBefore: .zero, toleranceAfter: .zero)
      } ? .success : .commandFailed
    }

    remoteCommandCenter.skipBackwardCommand.preferredIntervals = [10.0]
    remoteCommandCenter.skipBackwardCommand.addTarget { [weak self] event in
      guard let player = self?.activePlayer,
      let event = event as? MPSkipIntervalCommandEvent else {
        return .commandFailed
      }

      let currentTime = player.ref.currentTime()
      let seekTime = currentTime - CMTime(seconds: event.interval, preferredTimescale: 1)
      return player.ncBinding.command {
        player.ref.seek(to: seekTime, toleranceBefore: .zero, toleranceAfter: .zero)
      } ? .success : .commandFailed
    }
    
    remoteCommandCenter.playCommand.isEnabled = true
    remoteCommandCenter.pauseCommand.isEnabled = true
    remoteCommandCenter.togglePlayPauseCommand.isEnabled = true
    remoteCommandCenter.changePlaybackPositionCommand.isEnabled = true
    remoteCommandCenter.skipForwardCommand.isEnabled = options?.showSeekForward ?? false
    remoteCommandCenter.skipBackwardCommand.isEnabled = options?.showSeekBackward ?? false
  }

  private func disableRemoteCommands() {
    remoteCommandCenter.playCommand.isEnabled = false
    remoteCommandCenter.pauseCommand.isEnabled = false
    remoteCommandCenter.togglePlayPauseCommand.isEnabled = false
    remoteCommandCenter.changePlaybackPositionCommand.isEnabled = false
    remoteCommandCenter.skipForwardCommand.isEnabled = false
    remoteCommandCenter.skipBackwardCommand.isEnabled = false
    
    // Remove event targets
    remoteCommandCenter.playCommand.removeTarget(self);
    remoteCommandCenter.pauseCommand.removeTarget(self);
    remoteCommandCenter.togglePlayPauseCommand.removeTarget(self);
    remoteCommandCenter.changePlaybackPositionCommand.removeTarget(self);
    remoteCommandCenter.skipForwardCommand.removeTarget(self);
    remoteCommandCenter.skipBackwardCommand.removeTarget(self);
  }
}
