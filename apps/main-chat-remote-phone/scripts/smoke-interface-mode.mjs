import assert from 'node:assert/strict';

import {
  INTERFACE_STYLES,
  modePolicy,
  normalizeInterfaceStyle,
  resolveInterfaceStyle,
  shouldForceChromeVisible,
} from '../src/utils/interfaceMode.ts';

assert.deepEqual(INTERFACE_STYLES, ['classic', 'adaptive', 'flat', 'immersive']);
assert.equal(normalizeInterfaceStyle('adaptive'), 'adaptive');
assert.equal(normalizeInterfaceStyle('flat'), 'flat');
assert.equal(normalizeInterfaceStyle('immersive'), 'immersive');
assert.equal(normalizeInterfaceStyle('classic'), 'classic');
assert.equal(normalizeInterfaceStyle('bad-value'), 'classic');
assert.equal(normalizeInterfaceStyle(undefined), 'classic');
assert.equal(resolveInterfaceStyle(undefined, 'clean'), 'adaptive');
assert.equal(resolveInterfaceStyle(undefined, 'standard'), 'classic');
assert.equal(resolveInterfaceStyle('immersive', 'clean'), 'immersive');

assert.equal(modePolicy('classic').cards, true);
assert.equal(modePolicy('adaptive').primaryFirst, true);
assert.equal(modePolicy('flat').cards, false);
assert.equal(modePolicy('immersive').immersive, true);
assert.equal(modePolicy('immersive').persistentNavigation, false);

assert.equal(shouldForceChromeVisible({ recording: true }), true);
assert.equal(shouldForceChromeVisible({ disconnected: true }), true);
assert.equal(shouldForceChromeVisible({ playbackError: true }), true);
assert.equal(shouldForceChromeVisible({ buddyProviderError: true }), true);
assert.equal(shouldForceChromeVisible({}), false);

console.log('Interface mode policy smoke passed.');
