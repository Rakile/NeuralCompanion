# expo-audio 1.1.1: persistent native playback ownership

This maintained, iOS-native-only patch adds ownership to the existing Expo
AVPlayers. No new player, npm dependency, Android change or capture-module import
is introduced. The original Expo MIT license is retained in `LICENSE`; upstream
source is from the installed 1.1.1 package. Before-images are in `upstream/ios/`,
exact after-images in `ios/`, and every installed target/hash is in `manifest.json`.
The patch-local `.gitattributes` preserves hash-pinned LF bytes across checkouts.

## Review follow-on: shared native publication and cleanup ownership

Task4 must use these native-only public APIs on `NCPlaybackGuard.shared`:

```swift
publishConversationMedia(ticket: String, sessionId: String, effect: () -> Void) -> Bool
clearConversationMedia(ticket: String, effect: () -> Void) -> Bool
```

Publication requires the matching open protected ticket AND session. Put all NC
metadata writes and global command-enabled configuration in the accepted effect.
Cleanup requires only that this ticket still owns the last NC publication; it
consumes that right once. A new issued ticket that has not published does not strand
old metadata. Actual accepted Expo metadata/control publication, or a newer NC
publication, invalidates old NC cleanup even when the current ticket is unchanged.
Failed publication/cleanup runs no effect and preserves the prior owner. Selecting
an Expo player without publishing, and stale/no-op callbacks, do not claim ownership.
The marker is a single optional ticket, never a history or tombstone collection.

Task4 always removes its own command tokens outside this boundary, but must restore
global command-enabled state and clear/restore metadata only inside accepted cleanup.
Both effects are synchronous native sink writes under the media-publication lock,
with the output lock released. Do not wait for main/capture/JS, call playback, change
ownership, or recursively publish/clear from an effect. Reentrant public effects
and output-to-media calls fail closed; ownership begins inside an NC effect throw.
Retirement remains output-only and its observer schedules cleanup asynchronously,
so it never waits for media while holding output. Lock order remains media -> output.

Six new Foundation ownership cases and one actual MediaController case bring Task8
to 31 Foundation plus eight actual-adapter tests at that checkpoint, all authored but unexecuted on
Windows. The actual adapter case checks both metadata and MPRemoteCommand enabled
state after Expo supersedes a retired NC publisher. Apple and device gates remain.

## Final setup correction: negotiate, seal, arm

Protected Begin creates an open ownership ticket that permits binding but denies
managed playback until native arm. `prepareProtectedInput(ticket:sessionId:snapshot:start:)`
wraps the production capture Start with native foreground/route checks before and
after it. Start and snapshots run outside both guard locks. Failed or superseded
Start retires only its captured ticket; capture retains its existing exact-session
drain. `armProtectedOutput(ticket:sessionId:foreground:routeKey:)` requires the same
sealed native route after the capture headphone/confirmation policy succeeds.

Only category/configuration notifications for an eligible candidate pass during
negotiation. After sealing, delayed setup notifications pass only for that exact
route. Every route notification after arm retires output; loss, changed/ineligible
sealed routes, unknown reasons, interruption, reset and Stop remain terminal before
arm. AudioModule's native will-resign-active observer retires unarmed ownership,
preserving armed lock/Control Center behavior. Foreground return never reopens.
Both native observers use the same admission boundary and native route-key function;
no guard action synchronously waits on main or the capture worker.

Six added actual adapter cases exercise Start-generated notifications through the
production preparation boundary and registered AudioModule observer, unarmed real
player paths, delayed same-route delivery, changed route denial, native resign,
Start failures and supersession. Existing playback tests now explicitly arm their
fixture tickets. Inventory: 31 Foundation guard + 14 actual adapter methods; all
remain UNEXECUTED on Windows. The runner rejects thirteen all-pass methods.
