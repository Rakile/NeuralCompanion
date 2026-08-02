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
  if (platform === 'ios') {
    return 'padding';
  }
  if (platform === 'android') {
    return 'height';
  }
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
