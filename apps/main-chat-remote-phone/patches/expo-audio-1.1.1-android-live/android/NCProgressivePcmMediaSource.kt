package expo.modules.audio

import android.net.Uri
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.util.ParsableByteArray
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.BaseDataSource
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import androidx.media3.extractor.Extractor
import androidx.media3.extractor.ExtractorInput
import androidx.media3.extractor.ExtractorOutput
import androidx.media3.extractor.ExtractorsFactory
import androidx.media3.extractor.PositionHolder
import androidx.media3.extractor.SeekMap
import androidx.media3.extractor.TrackOutput
import java.io.IOException

@UnstableApi
internal object NCProgressivePcmMediaSource {
  const val SCHEME = "nc-progressive-pcm"

  fun loadControl(): DefaultLoadControl = DefaultLoadControl.Builder()
    .setBufferDurationsMs(500, 1000, 40, 80).build()

  fun create(store: NCProgressivePcmStore, uri: Uri): MediaSource {
    val id = uri.host ?: throw IllegalArgumentException("progressive_pcm_uri")
    require(uri.toString() == "$SCHEME://$id") { "progressive_pcm_uri" }
    val queue = store.requireSource(id)
    return ProgressiveMediaSource.Factory(
      DataSource.Factory { NCProgressivePcmDataSource(queue) },
      ExtractorsFactory { arrayOf(NCProgressivePcmExtractor(queue)) }
    )
      // No prefix retry, alternate data source, or estimated/WAV duration.
      .setLoadErrorHandlingPolicy(DefaultLoadErrorHandlingPolicy(0))
      .setContinueLoadingCheckIntervalBytes(2400)
      .createMediaSource(MediaItem.fromUri(uri))
  }
}

@UnstableApi
internal class NCProgressivePcmDataSource(private val queue: NCProgressivePcmQueue) : BaseDataSource(false) {
  private var uri: Uri? = null
  private var opened = false

  override fun open(dataSpec: DataSpec): Long {
    transferInitializing(dataSpec)
    if (opened || dataSpec.position != 0L) throw IOException("progressive_pcm_unseekable")
    queue.claimReader()
    uri = dataSpec.uri
    opened = true
    transferStarted(dataSpec)
    return C.LENGTH_UNSET.toLong()
  }

  override fun getUri(): Uri? = uri

  override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
    if (!opened) throw IOException("progressive_pcm_not_open")
    val count = queue.read(buffer, offset, length)
    if (count > 0) bytesTransferred(count)
    return count
  }

  override fun close() {
    // Explicit native cancellation wakes the blocked loader. Successful EOS was
    // already emitted only after finalFrames and all bytes were consumed.
    queue.close()
    if (opened) { opened = false; transferEnded() }
    uri = null
  }
}

/** PCM s16le, mono, 24kHz. Emits native samples through the existing Expo sink. */
@UnstableApi
internal class NCProgressivePcmExtractor(private val queue: NCProgressivePcmQueue) : Extractor {
  private lateinit var output: ExtractorOutput
  private lateinit var track: TrackOutput
  private val bytes = ByteArray(2048)
  private var frames = 0L
  private var pendingByte = 0
  private var ended = false

  override fun sniff(input: ExtractorInput) = true

  override fun init(output: ExtractorOutput) {
    this.output = output
    track = output.track(0, C.TRACK_TYPE_AUDIO)
    track.format(Format.Builder().setSampleMimeType(MimeTypes.AUDIO_RAW)
      .setSampleRate(NCProgressivePcmQueue.SAMPLE_RATE).setChannelCount(1)
      .setPcmEncoding(C.ENCODING_PCM_16BIT).setMaxInputSize(bytes.size).build())
    output.seekMap(SeekMap.Unseekable(C.TIME_UNSET))
    output.endTracks()
  }

  override fun read(input: ExtractorInput, seekPosition: PositionHolder): Int {
    if (ended) return Extractor.RESULT_END_OF_INPUT
    val count = input.read(bytes, 0, bytes.size)
    if (count == C.RESULT_END_OF_INPUT) {
      val total = queue.finalFrames() ?: throw IOException("progressive_pcm_unfinished")
      if (pendingByte != 0 || total != frames) throw IOException("progressive_pcm_final_size")
      output.seekMap(SeekMap.Unseekable(total * 1000000L / NCProgressivePcmQueue.SAMPLE_RATE))
      ended = true
      return Extractor.RESULT_END_OF_INPUT
    }
    if (count == 0) return Extractor.RESULT_CONTINUE
    track.sampleData(ParsableByteArray(bytes, count), count)
    val completeBytes = (pendingByte + count) / 2 * 2
    pendingByte = (pendingByte + count) % 2
    if (completeBytes > 0) {
      track.sampleMetadata(frames * 1000000L / NCProgressivePcmQueue.SAMPLE_RATE,
        C.BUFFER_FLAG_KEY_FRAME, completeBytes, pendingByte, null)
      frames += completeBytes / 2
    }
    return Extractor.RESULT_CONTINUE
  }

  override fun seek(position: Long, timeUs: Long) {
    // Media3 may request the initial zero position before the first sample.
    if (position != 0L || timeUs != 0L || frames != 0L || pendingByte != 0 || ended)
      throw IllegalStateException("progressive_pcm_unseekable")
  }

  override fun release() = Unit
}
