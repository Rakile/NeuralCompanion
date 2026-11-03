using System;
using System.IO;

namespace NC.VSeeFaceBridge
{
    [Serializable]
    public sealed class BridgeState
    {
        public int version;
        public string client;
        public long revision;
        public string clip;
        public double position;
        public bool running;
        public double updated;

        public bool IsValid(double now, double maxAge)
        {
            Guid id;
            return version == 1 && Guid.TryParseExact(client, "N", out id)
                && revision > 0 && !Double.IsNaN(position) && !Double.IsInfinity(position)
                && position >= 0 && !Double.IsNaN(updated) && !Double.IsInfinity(updated)
                && now >= updated && now - updated <= maxAge
                && clip != null && (clip.Length == 0 ||
                    (clip == Path.GetFileName(clip) && clip.StartsWith(client + "-", StringComparison.Ordinal)
                    && clip.EndsWith(".wav", StringComparison.OrdinalIgnoreCase)
                    && clip.IndexOf(':') < 0 && clip.IndexOf('/') < 0 && clip.IndexOf('\\') < 0));
        }

        public double TargetSeconds(double now)
        {
            return position + (running ? Math.Max(0, now - updated) : 0);
        }
    }
}
