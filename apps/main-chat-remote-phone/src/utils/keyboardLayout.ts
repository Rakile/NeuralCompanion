export type KeyboardAvoidingBehavior = 'padding' | 'height' | undefined;

export type KeyboardChromeMemory = {
  focused: boolean;
  restoreCollapsed: boolean;
};

export type KeyboardChromeTransition = {
  collapsed: boolean;
  memory: KeyboardChromeMemory;
};

export function keyboardAvoidingBehavior(platform: string): KeyboardAvoidingBehavior {
  if (platform === 'ios' || platform === 'android') {
    return 'padding';
  }
  // Edge-to-edge Android can keep the window full height while the IME overlays
  // it. Padding handles that overlap without caching a shortened initial height.
  return undefined;
}

export function createKeyboardChromeMemory(): KeyboardChromeMemory {
  return {
    focused: false,
    restoreCollapsed: false,
  };
}

export function focusKeyboardChrome(
  currentCollapsed: boolean,
  memory: KeyboardChromeMemory,
): KeyboardChromeTransition {
  return {
    collapsed: true,
    memory: memory.focused
      ? memory
      : {
        focused: true,
        restoreCollapsed: currentCollapsed,
      },
  };
}

export function blurKeyboardChrome(memory: KeyboardChromeMemory): KeyboardChromeTransition {
  return {
    collapsed: memory.restoreCollapsed,
    memory: {
      ...memory,
      focused: false,
    },
  };
}
