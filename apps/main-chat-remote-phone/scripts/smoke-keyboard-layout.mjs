import assert from 'node:assert/strict';

import {
  blurKeyboardChrome,
  createKeyboardChromeMemory,
  focusKeyboardChrome,
  keyboardAvoidingBehavior,
} from '../src/utils/keyboardLayout.ts';

assert.equal(keyboardAvoidingBehavior('ios'), 'padding');
assert.equal(keyboardAvoidingBehavior('android'), 'height');
assert.equal(keyboardAvoidingBehavior('web'), undefined);

let memory = createKeyboardChromeMemory();
let transition = focusKeyboardChrome(false, memory);
assert.equal(transition.collapsed, true);
assert.equal(transition.memory.restoreCollapsed, false);

memory = transition.memory;
transition = focusKeyboardChrome(true, memory);
assert.equal(transition.memory.restoreCollapsed, false);

transition = blurKeyboardChrome(transition.memory);
assert.equal(transition.collapsed, false);

memory = createKeyboardChromeMemory();
transition = focusKeyboardChrome(true, memory);
transition = blurKeyboardChrome(transition.memory);
assert.equal(transition.collapsed, true);

console.log('Keyboard layout policy smoke passed.');
