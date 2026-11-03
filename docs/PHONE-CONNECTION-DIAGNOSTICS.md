# Phone connection diagnostics

Use the matching native phone app connected to the NC desktop. Diagnostic
collection helps distinguish a connection failure from generation, queue, or
playback delays; it does not repair or restart those components.

## Collect and send a diagnostic file

1. Connect the phone in LAN or Internet mode and reproduce the problem. Note the
   time and what you expected to happen. For a cellular test, turn Wi-Fi off.
2. Open **Settings → Tools → Diagnostics → Show** in the phone app. The layout
   can reveal Diagnostics automatically when a connection/provider error exists.
3. Tap **Send diagnostic file** and read the result in that panel.
   **Sent N event(s) to desktop** reports an upload;
   **No queued events to send** means there was no pending event backlog to
   upload, not that NC has just received a new file.
4. Keep the connection open until upload succeeds. If disconnected, allow it to
   reconnect so buffered diagnostics can reach the desktop. Do not clear the
   evidence before recording the failure.

The button sends queued events, not a full capture of everything the app has
previously done. Automatic upload can already have drained the queue, and
logging policy controls which routine events are recorded. An absent route event
is not proof that the media was relayed or that the connection failed.

These diagnostic records exclude chat text, photos, credentials, and pairing
codes. They still contain operational details; review the actual file before
sharing it. The separate full communication logger has broader private content
and should not be confused with these diagnostic files.

## Where evidence lives

- Desktop request trace: `runtime/main_chat_remote/phone_debug/peer_requests.jsonl`
  (1 MiB plus two rotated files, nonblocking bounded writer queue).
- Phone events and desktop ownership snapshots:
  `runtime/main_chat_remote/phone_debug/phone_remote.log` (existing rotation).
- Phone offline backlog: existing `nc-phone-debug.jsonl`, bounded to 2,000 events
  and approximately 3 MiB UTF-8. Uploads go through the encrypted peer to NC desktop.

Match `request_id` across `peer_request`, `request_received`,
`bridge_forward_started`, `bridge_forward_finished`, `response_ready`, and
`request_finished`. UTC timestamps locate events; local elapsed durations avoid
assuming the phone and desktop clocks are identical. A ready response is not proof
the phone received it; look for its `completed` event.

Failure snapshots preserve the last 32 trace events, at most once per 10 seconds.
The desktop snapshots on cancellation, HTTP errors, request exceptions or requests
lasting at least 5 seconds. Phone snapshots on request failure, invalid recovery,
native capture interruptions and an amber-send action missing its predecessor.
Snapshots are best-effort; bounded queues or abrupt process termination can lose events.

`phone_control_result` and `phone_ownership` identify pending replies, binding,
chunk counts, playback acknowledgements, stop requests, holds and unsettled control
operations. `queued_send_attempt`/`queued_send_blocked` identify the reply the amber
button attempted to advance. Existing audio events supply chunk progress.

`rtc_state`, `rtc_ice_state`, and `rtc_route` show peer transitions and selected
candidate type (`relay` means TURN on either side). `phone_lifecycle` and
`native_audio_interruption` show app state and exposed native interruption reasons.
Candidate stats are sampled on connection; no IP addresses, SDP, credentials,
request bodies, chat text, prompt text, audio or image data enter these new traces.
This does not alter the separate opt-in full communication logger.

## Reading the result

- Phone starts, no desktop receive: investigate transport delivery.
- Desktop receives, bridge start without finish: investigate desktop handling.
- Response ready without phone completion: investigate return transport/backpressure.
- Audio ends but acknowledgement/ownership remains pending: investigate playback gate.
- Repeated health timeouts while RTC stays connected: distinguish an unresponsive
  data channel from desktop handling using the matching request events.

The new records are additive; phone/backend API contracts and relay wire version
remain unchanged. A physical cellular reproduction is still required to establish
the cause of the reported intermittent failures.
