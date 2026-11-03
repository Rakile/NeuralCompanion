// WebRTC's Objective-C property is int32_t, but RTP timestamps are unsigned.
// Numeric UInt32(value) traps for half the random RTP origins. Preserve bits.
func ncRtpTimestamp(_ value: Int32) -> UInt32 { UInt32(bitPattern: value) }
