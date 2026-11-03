using System;

namespace NC.VSeeFaceBridge
{
    [Serializable]
    public sealed class BridgeStatus
    {
        public string state, detail, client, bridge_version, installation_path;
        public long revision;
        public int pid;
        public double updated, max_clock_age_seconds;
    }

    public sealed class StatusHeartbeat
    {
        public readonly BridgeStatus Value = new BridgeStatus();
        public bool Due(double now, double maxAge)
        {
            if (maxAge <= 0 || Double.IsNaN(maxAge) || Double.IsInfinity(maxAge))
                throw new ArgumentException("Clock age must be finite and positive.");
            return now - Value.updated >= maxAge / 2;
        }
        public void Touch(double now, double maxAge)
        {
            Value.updated = now;
            Value.max_clock_age_seconds = maxAge;
        }
    }
}
