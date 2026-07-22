import assert from 'node:assert/strict';

const { topControlsSwipeAction } = await import('../src/utils/swipeControls.ts');

assert.equal(
  topControlsSwipeAction({ dx: 4, dy: -110, y0: 650, screenHeight: 800, collapsed: false }),
  'collapse',
);
assert.equal(
  topControlsSwipeAction({ dx: 2, dy: 120, y0: 30, screenHeight: 800, collapsed: true }),
  'expand',
);
assert.equal(
  topControlsSwipeAction({ dx: 2, dy: 120, y0: 500, screenHeight: 800, collapsed: true }),
  'none',
);
assert.equal(
  topControlsSwipeAction({ dx: 100, dy: -70, y0: 650, screenHeight: 800, collapsed: false }),
  'none',
);
assert.equal(
  topControlsSwipeAction({ dx: 2, dy: -20, y0: 650, screenHeight: 800, collapsed: false }),
  'none',
);

console.log('Top control swipe smoke passed.');
