export type FullscreenGesture = 'none' | 'single' | 'double' | 'long';

export type FullscreenGestureInput = {
  heldMs: number;
  thresholdMs: number;
  taps: number;
  movedPx: number;
};

export const FULLSCREEN_GESTURE_MOVE_LIMIT_PX = 16;
export const FULLSCREEN_DOUBLE_TAP_MS = 280;

export function decideFullscreenGesture(input: FullscreenGestureInput): FullscreenGesture {
  if (Math.max(0, Number(input.movedPx) || 0) > FULLSCREEN_GESTURE_MOVE_LIMIT_PX) {
    return 'none';
  }
  if (
    Math.max(0, Number(input.heldMs) || 0)
    >= Math.max(1, Number(input.thresholdMs) || 1)
  ) {
    return 'long';
  }
  if (Number(input.taps) >= 2) {
    return 'double';
  }
  return Number(input.taps) === 1 ? 'single' : 'none';
}
