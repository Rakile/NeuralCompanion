// NeuralCompanion, MIT. Installed in the WebRTC module BEFORE factory creation.
package com.oney.WebRTCModule;

import java.util.Objects;
import org.webrtc.audio.AudioDeviceModule;

/** Decoder/mixer still runs, but its default Android speaker path stays silent.
 * The patched per-track PCM sink feeds only NC's separately guarded output.
 * This wrapper never acquires audio focus or changes the Live input policy.
 */
final class NCMuteAudioDevice implements AudioDeviceModule {
  private final Object lock = new Object();
  private final AudioDeviceModule delegate;
  private boolean released;
  NCMuteAudioDevice(AudioDeviceModule delegate) {
    this.delegate = Objects.requireNonNull(delegate);
    delegate.setSpeakerMute(true);
  }
  private void checkOpen() { if (released) throw new IllegalStateException("Decoder device released"); }
  @Override public long getNativeAudioDeviceModulePointer() {
    synchronized (lock) {
      checkOpen(); delegate.setSpeakerMute(true);
      return delegate.getNativeAudioDeviceModulePointer();
    }
  }
  @Override public void setSpeakerMute(boolean ignored) {
    synchronized (lock) { checkOpen(); delegate.setSpeakerMute(true); }
  }
  @Override public void setMicrophoneMute(boolean mute) {
    synchronized (lock) { checkOpen(); delegate.setMicrophoneMute(mute); }
  }
  @Override public boolean setNoiseSuppressorEnabled(boolean enabled) {
    synchronized (lock) { checkOpen(); return delegate.setNoiseSuppressorEnabled(enabled); }
  }
  @Override public boolean setPreferredMicrophoneFieldDimension(float dimension) {
    synchronized (lock) { checkOpen(); return delegate.setPreferredMicrophoneFieldDimension(dimension); }
  }
  @Override public void release() {
    synchronized (lock) {
      if (released) return;
      released = true; delegate.release();
    }
  }
}
