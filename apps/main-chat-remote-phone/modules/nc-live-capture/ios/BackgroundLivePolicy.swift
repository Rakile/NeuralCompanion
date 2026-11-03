enum BackgroundOutput: Equatable { case wired, bluetooth, ineligible }

// Native-only identity. Never include routeKey in bridge payloads or diagnostics.
struct BackgroundLivePolicy {
    private(set) var armed = false
    private var routeKey: String?

    mutating func arm(foreground: Bool, output: BackgroundOutput,
                      routeKey: String, bluetoothConfirmed: Bool) -> Bool {
        guard foreground, !routeKey.isEmpty,
              output == .wired || (output == .bluetooth && bluetoothConfirmed)
        else { return false }
        self.routeKey = routeKey
        armed = true
        return true
    }

    mutating func revoke() { armed = false; routeKey = nil }

    func permitsBackground(routeKey: String) -> Bool {
        armed && self.routeKey == routeKey
    }
}
