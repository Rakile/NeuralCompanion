import { useCallback, useEffect, useRef, useState } from 'react';

import type { InterfaceStyle } from '../utils/interfaceMode';

export const IMMERSIVE_HIDE_DELAY_MS = 4000;

type Options = {
  mode: InterfaceStyle;
  forceVisible: boolean;
  timeoutMs?: number;
};

export function useImmersiveChrome({ mode, forceVisible, timeoutMs = IMMERSIVE_HIDE_DELAY_MS }: Options) {
  const [visible, setVisible] = useState(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const immersive = mode === 'immersive';

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const scheduleHide = useCallback(() => {
    clearTimer();
    if (!immersive || forceVisible) {
      setVisible(true);
      return;
    }
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setVisible(false);
    }, timeoutMs);
  }, [clearTimer, forceVisible, immersive, timeoutMs]);

  const revealChrome = useCallback(() => {
    setVisible(true);
    scheduleHide();
  }, [scheduleHide]);

  useEffect(() => {
    setVisible(true);
    scheduleHide();
    return clearTimer;
  }, [clearTimer, scheduleHide]);

  return {
    chromeVisible: !immersive || forceVisible || visible,
    revealChrome,
    scheduleHide,
  };
}
