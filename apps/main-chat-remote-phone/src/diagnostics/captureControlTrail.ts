// Button/lifecycle calls only, never metering or frames. Kept in memory and
// attached to an existing failure record; optional trace logging may stay off.
const allowed = new Set(['portrait_talk', 'manual_start', 'manual_send', 'manual_blocked',
  'live_toggle_start', 'live_toggle_stop', 'live_tail_stop', 'capture_cancel',
  'chat_reset_begin', 'chat_reset_output_closed', 'chat_reset_dispatched',
  'chat_reset_accepted', 'chat_reset_refreshed', 'chat_reset_failed']);
const recent: Array<{action: string; at: number}> = [];

export function rememberCaptureControl(action: string): void {
  try {
    if (!allowed.has(action)) return;
    recent.push({action, at: Date.now()});
    if (recent.length > 12) recent.shift();
  } catch { /* Diagnostics never affect capture. */ }
}

export function captureControlTrail(): Array<{action: string; age_ms: number}> {
  try {
    const now = Date.now();
    return recent.map(row => ({action: row.action, age_ms: Math.max(0, now - row.at)}));
  } catch { return []; }
}
