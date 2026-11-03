using System;

namespace NC.VSeeFaceBridge
{
    // No Unity calls, file writes or audio mutation on the audio thread.
    public sealed class AudioProbe
    {
        private readonly object _gate = new object();
        private long _driver, _processor, _silencer, _apply, _frames, _errors;
        private int _channels, _nativeResult;
        private float _driverPeak, _processorPeak, _silencerPeak, _visemePeak;

        private static float Peak(float[] values, int start)
        {
            float peak = 0;
            if (values != null) for (int i=start; i<values.Length; i++) peak = Math.Max(peak, Math.Abs(values[i]));
            return peak;
        }

        public void Driver(float[] samples, int channels)
        {
            float peak = Peak(samples, 0);
            lock (_gate) { _driver++; _channels=channels; _driverPeak=Math.Max(_driverPeak, peak); }
        }
        public void Processor(float[] samples)
        {
            float peak = Peak(samples, 0);
            lock (_gate) { _processor++; _processorPeak=Math.Max(_processorPeak, peak); }
        }
        public void Silencer(float[] samples)
        {
            float peak = Peak(samples, 0);
            lock (_gate) { _silencer++; _silencerPeak=Math.Max(_silencerPeak, peak); }
        }
        public void Visemes(float[] values)
        {
            float peak = Peak(values, 1); // Index zero is sil, not speech.
            lock (_gate) _visemePeak=Math.Max(_visemePeak, peak);
        }
        public void Apply() { lock (_gate) _apply++; }
        public void NativeResult(int result)
        {
            lock (_gate) { _frames++; _nativeResult=result; if (result != 0) _errors++; }
        }
        public AudioProbeSample Snapshot()
        {
            lock (_gate)
            {
                AudioProbeSample sample = new AudioProbeSample { driver_calls=_driver, processor_calls=_processor,
                    silencer_calls=_silencer, apply_calls=_apply, channels=_channels, native_frames=_frames,
                    native_errors=_errors, native_result=_nativeResult, driver_peak=_driverPeak,
                    processor_peak=_processorPeak, silencer_peak=_silencerPeak, speech_viseme_peak=_visemePeak };
                _driverPeak=_processorPeak=_silencerPeak=_visemePeak=0;
                return sample;
            }
        }
    }

    [Serializable]
    public sealed class AudioProbeSample
    {
        public long driver_calls, processor_calls, silencer_calls, apply_calls, native_frames, native_errors;
        public int channels, native_result;
        public float driver_peak, processor_peak, silencer_peak, speech_viseme_peak;
    }
}
