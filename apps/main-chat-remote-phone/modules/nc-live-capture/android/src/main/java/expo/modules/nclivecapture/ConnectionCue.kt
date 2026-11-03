package expo.modules.nclivecapture

/** Compatibility delegate; output and ordered playback share one cue policy. */
object ConnectionCue {
  const val SAMPLE_RATE = expo.modules.audio.NCConnectionCueSamples.SAMPLE_RATE
  const val RECOVERED_DURATION_MS = expo.modules.audio.NCConnectionCueSamples.RECOVERED_DURATION_MS
  fun samples(recovered: Boolean) = expo.modules.audio.NCConnectionCueSamples.samples(recovered)
}
