import React from 'react';

import { modePolicy } from '../utils/interfaceMode';
import type { InterfaceModePolicy, InterfaceStyle } from '../utils/interfaceMode';

type InterfaceModeValue = {
  mode: InterfaceStyle;
  policy: InterfaceModePolicy;
};

const defaultValue: InterfaceModeValue = {
  mode: 'classic',
  policy: modePolicy('classic'),
};

const InterfaceModeContext = React.createContext<InterfaceModeValue>(defaultValue);

export function InterfaceModeProvider({ mode, children }: React.PropsWithChildren<{ mode: InterfaceStyle }>) {
  const value = React.useMemo(() => ({ mode, policy: modePolicy(mode) }), [mode]);
  return <InterfaceModeContext.Provider value={value}>{children}</InterfaceModeContext.Provider>;
}

export function useInterfaceMode(): InterfaceModeValue {
  return React.useContext(InterfaceModeContext);
}
