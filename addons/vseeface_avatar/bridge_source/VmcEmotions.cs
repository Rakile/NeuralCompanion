using System;
using System.Collections.Generic;

namespace NC.VSeeFaceBridge
{
    public static class VmcEmotions
    {
        public static Dictionary<TKey,float> Select<TKey>(bool enabled, bool receiverSynchronizes,
            bool driverSkipsBlendshapes, IDictionary<TKey,float> incoming, Func<TKey,string> name)
        {
            if (!enabled || receiverSynchronizes || driverSkipsBlendshapes || incoming == null) return null;
            var selected = new Dictionary<TKey,float>();
            foreach (var value in incoming)
            {
                string clip = name(value.Key);
                if (clip == null || float.IsNaN(value.Value) || float.IsInfinity(value.Value)) continue;
                switch (clip.ToUpperInvariant())
                {
                    case "NEUTRAL": case "FUN": case "JOY": case "SORROW": case "ANGRY": case "SURPRISED":
                        selected[value.Key] = Math.Max(0f, Math.Min(1f, value.Value));
                        break;
                }
            }
            return selected;
        }
    }
}
