// NeuralCompanion, MIT. Android output only; focus/capture remain with NC's owner.
package expo.modules.audio;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;

/** Single output lifetime. Cancellation is terminal and flushes without draining.
 * The owning module prepares this off the UI/decoder threads. No AudioManager
 * mode, communication-device, focus or microphone mutations occur here.
 */
final class NCAndroidPcmDevice implements NCPcmOutput.Device {
  private final Object lock = new Object();
  private final boolean communication;
  private AudioTrack track;
  private boolean terminal, closed;
  private float volume = 1;

  NCAndroidPcmDevice(boolean communication) { this.communication = communication; }

  public boolean prepare() {
    synchronized (lock) {
      if (terminal || closed) return false;
      if (track != null) return true;
    }
    int minimum = AudioTrack.getMinBufferSize(48000, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
    // Refuse unsupported/pathologically large device buffering, not an unbounded
    // hidden queue that cancellation/checkpoints cannot account for.
    if (minimum <= 0 || minimum > 48000) return false;
    AudioTrack candidate = new AudioTrack.Builder()
      .setAudioAttributes(new AudioAttributes.Builder()
        .setUsage(communication ? AudioAttributes.USAGE_VOICE_COMMUNICATION : AudioAttributes.USAGE_MEDIA)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
      .setAudioFormat(new AudioFormat.Builder().setSampleRate(48000)
        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
      .setBufferSizeInBytes(Math.max(3840, minimum))
      .setTransferMode(AudioTrack.MODE_STREAM).build();
    synchronized (lock) {
      if (terminal || closed || track != null || candidate.getState() != AudioTrack.STATE_INITIALIZED) {
        candidate.release(); return track != null && !terminal && !closed;
      }
      track = candidate;
      track.setVolume(volume);
      return true;
    }
  }
  public void play() { synchronized (lock) { if (!terminal && !closed && track != null) track.play(); } }
  public boolean isPlaying() {
    synchronized (lock) { return !terminal && !closed && track != null && track.getPlayState() == AudioTrack.PLAYSTATE_PLAYING; }
  }
  public int write(short[] pcm, int offset, int count) {
    synchronized (lock) {
      if (terminal || closed || track == null) return AudioTrack.ERROR_INVALID_OPERATION;
      return track.write(pcm, offset, count, AudioTrack.WRITE_NON_BLOCKING);
    }
  }
  public long playbackHead() {
    synchronized (lock) {
      if (track == null || closed) return -1;
      return Integer.toUnsignedLong(track.getPlaybackHeadPosition());
    }
  }
  public void setVolume(float value) {
    if (!Float.isFinite(value)) return;
    synchronized (lock) {
      volume = Math.max(0, Math.min(1, value));
      if (!closed && track != null) track.setVolume(volume);
    }
  }
  public void stop() {
    synchronized (lock) {
      if (terminal) return;
      terminal = true; // Fence before platform calls, including if they fail.
      if (track != null && !closed) {
        try { track.pause(); } finally { track.flush(); }
      }
    }
  }
  public void close() {
    synchronized (lock) {
      if (closed) return;
      try { stop(); }
      finally { closed = true; if (track != null) { track.release(); track = null; } }
    }
  }
}
