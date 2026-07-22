export type TopControlsSwipeAction = 'collapse' | 'expand' | 'none';

type SwipeInput = {
  dx: number;
  dy: number;
  y0: number;
  screenHeight: number;
  collapsed: boolean;
};

const SWIPE_DISTANCE = 56;
const VERTICAL_DOMINANCE = 1.25;

export function topControlsSwipeAction(input: SwipeInput): TopControlsSwipeAction {
  const dx = Number(input.dx || 0);
  const dy = Number(input.dy || 0);
  const y0 = Number(input.y0 || 0);
  const screenHeight = Math.max(1, Number(input.screenHeight || 0));
  if (Math.abs(dy) < SWIPE_DISTANCE || Math.abs(dy) < Math.abs(dx) * VERTICAL_DOMINANCE) {
    return 'none';
  }
  if (!input.collapsed && dy < 0 && y0 >= screenHeight * 0.45) {
    return 'collapse';
  }
  const topEdge = Math.min(140, screenHeight * 0.2);
  if (input.collapsed && dy > 0 && y0 <= topEdge) {
    return 'expand';
  }
  return 'none';
}
