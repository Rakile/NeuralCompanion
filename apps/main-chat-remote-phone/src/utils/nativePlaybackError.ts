/** Expo's Android status reports Media3 failures separately from `error`. */
export function nativePlaybackError(status: {error?: string; nativePlayerErrorCode?: number | null}): string | undefined {
  if (status.error) return status.error;
  const code = status.nativePlayerErrorCode;
  return typeof code === 'number' && Number.isFinite(code) && code > 0
    ? `Audio playback failed (Android error ${code}).` : undefined;
}
