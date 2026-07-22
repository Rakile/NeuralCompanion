import { registerRootComponent } from 'expo';
import React from 'react';

import App from './App';
import { PhoneErrorBoundary } from './src/components/PhoneErrorBoundary';

function Root() {
  return React.createElement(PhoneErrorBoundary, null, React.createElement(App));
}

registerRootComponent(Root);
