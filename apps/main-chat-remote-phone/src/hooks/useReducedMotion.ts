import React from 'react';
import { AccessibilityInfo } from 'react-native';

export function useReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((value) => {
      if (active) setReducedMotion(value);
    });
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReducedMotion);
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  return reducedMotion;
}
