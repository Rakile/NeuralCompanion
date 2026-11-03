// NeuralCompanion, MIT. Peer/factory scoping only; never a playback authority.
package com.oney.WebRTCModule;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.webrtc.AudioTrack;
import org.webrtc.MediaStreamTrack;
import org.webrtc.VideoSink;
import org.webrtc.VideoTrack;

/** A fresh namespace per React module prevents numeric peer IDs crossing reloads.
 * Register ONLY factories with NC's immutable default-output mute installed.
 * SDK calls stay on RN WebRTC's serial executor, including delayed cleanup.
 */
public final class NCTrackAccess {
  private static final Object lock = new Object();
  private static final HashMap<String, Factory> factories = new HashMap<>();
  private static final class Factory {
    final WeakReference<WebRTCModule> module;
    final HashSet<Attachment> attachments = new HashSet<>();
    Factory(WebRTCModule module) { this.module = new WeakReference<>(module); }
  }
  static String register(WebRTCModule module) {
    if (module == null) throw new IllegalArgumentException("Missing factory");
    String key = UUID.randomUUID().toString();
    synchronized (lock) { factories.put(key, new Factory(module)); }
    return key;
  }
  static void unregister(String key) {
    ArrayList<Attachment> previous;
    synchronized (lock) {
      Factory factory = factories.remove(key);
      previous = factory == null ? new ArrayList<>() : new ArrayList<>(factory.attachments);
    }
    for (Attachment attachment : previous) attachment.close();
  }
  public static Attachment attach(String factoryId, int peerId, String audioId, String videoId,
                                  AudioTrack.RtpAudioSink audioSink, VideoSink videoSink) {
    return attach(factoryId, peerId, audioId, videoId, audioSink, videoSink, () -> {});
  }
  public static Attachment attach(String factoryId, int peerId, String audioId, String videoId,
                                  AudioTrack.RtpAudioSink audioSink, VideoSink videoSink, Runnable onClosed) {
    Attachment result = new Attachment(factoryId, audioSink, videoSink, onClosed);
    synchronized (lock) {
      Factory factory = factories.get(factoryId);
      if (factory != null) factory.attachments.add(result);
    }
    ThreadUtils.runOnExecutor(() -> result.attach(peerId, audioId, videoId));
    return result;
  }

  public static final class Attachment implements AutoCloseable {
    private final String factoryId;
    private final AudioTrack.RtpAudioSink audioSink;
    private final VideoSink videoSink;
    private final Runnable onClosed;
    private final AtomicBoolean closed = new AtomicBoolean();
    private volatile boolean ready, failed;
    // Accessed only on the SDK executor.
    private AudioTrack audio;
    private VideoTrack video;
    private Attachment(String factoryId, AudioTrack.RtpAudioSink audioSink, VideoSink videoSink, Runnable onClosed) {
      this.factoryId = factoryId; this.audioSink = audioSink; this.videoSink = videoSink;
      this.onClosed = onClosed;
    }
    public boolean isReady() { return ready && !closed.get(); }
    public boolean failed() { return failed; }
    private void attach(int peerId, String audioId, String videoId) {
      if (closed.get()) { failed = true; return; }
      WebRTCModule module;
      synchronized (lock) {
        Factory factory = factories.get(factoryId);
        module = factory == null ? null : factory.module.get();
      }
      try {
        if (module == null || peerId < 0 || audioSink == null || videoSink == null || onClosed == null
            || audioId == null || videoId == null || audioId.length() > 256 || videoId.length() > 256)
          throw new IllegalArgumentException("Invalid remote media identity");
        MediaStreamTrack a = module.getTrack(peerId, audioId), v = module.getTrack(peerId, videoId);
        if (!(a instanceof AudioTrack) || !(v instanceof VideoTrack)
            || a.state() != MediaStreamTrack.State.LIVE || v.state() != MediaStreamTrack.State.LIVE)
          throw new IllegalArgumentException("Remote media unavailable");
        ((AudioTrack) a).addRtpAudioSink(audioSink); audio = (AudioTrack) a;
        ((VideoTrack) v).addSink(videoSink); video = (VideoTrack) v;
        ready = !closed.get();
        if (!ready) detach();
      } catch (RuntimeException error) {
        failed = true; close();
      }
    }
    private void detach() {
      if (audio != null) {
        try { audio.removeRtpAudioSink(audioSink); } catch (IllegalStateException ignored) { /* peer already disposed */ }
        audio = null;
      }
      if (video != null) {
        try { video.removeSink(videoSink); } catch (IllegalStateException ignored) { /* peer already disposed */ }
        video = null;
      }
    }
    @Override public void close() {
      if (!closed.compareAndSet(false, true)) return;
      ready = false;
      synchronized (lock) {
        Factory factory = factories.get(factoryId);
        if (factory != null) factory.attachments.remove(this);
      }
      // Caller must supply a bounded native output fence, not a JS callback.
      try { if (onClosed != null) onClosed.run(); }
      finally { ThreadUtils.runOnExecutor(this::detach); }
    }
  }
}
